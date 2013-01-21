#!/usr/bin/env python

# Copyright 2012 Google Inc. All Rights Reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License."

"""Tool for finding memory leaks in JavaScript applications.

To use, run Chrome with a single tab open, and with the following command line
flags:

  --remote-debugging-port=9222 --js-flags=--stack_trace_limit=-1

"""

import logging
import optparse
import os
import re
import sys

import leak_finder

sys.path.append("../../pyautolib/")
import remote_inspector_client
import suppressions


class LeakDefinition(object):
  """Holds the necessary configuration parameters to find a class of leaks.

  In a garbage collected language, such as JavaScript, the usual definition of
  memory leaks does not apply: as soon as all pointers to a given cell are
  dropped, the memory is eventually reclaimed.

  Instead, an object is defined as leaking, if all remaining retainers are
  "unintentional". In order to automatically detect such leaks, we need a
  definition of what unintentional retainers are.

  We define a cell as leaking, if it is retained by a certain array, and all
  other retaining paths of this cell go through at least one of a set of
  "bad" nodes.
  """

  def __init__(self, description='', suppression_filename='', containers=None,
               bad_nodes=None, stacktrace_prefix='', stacktrace_suffix=''):
    """Initializes the LeakDefinition.

    Args:
      description: str, a human readable description of this LeakDefinition.
      suppression_filename: str, filename of the suppressions file to use for
          this LeakDefinition.
      containers: [str], a set of arrays which contains potentially leaking
          objects.
      bad_nodes: [str], a set of nodes that qualify a retaining path as
          "unintentional" if it passes through one of these nodes.
      stacktrace_prefix: str, prefix to add to the container name for
          retrieving the stack trace. Useful e.g., if the JavaScript is in
          different frame.
      stacktrace_suffix: str, appended to the leaked objects for referring the
          member variable where the stack trace is stored. E.g., ".stack".
    """
    self.description = description
    self.suppressions = suppression_filename
    self.containers = containers or []
    self.bad_nodes = bad_nodes or []
    self.stacktrace_prefix = stacktrace_prefix
    self.stacktrace_suffix = stacktrace_suffix

# Some default configurations for Closure based apps.
CLOSURE_DISPOSABLE = LeakDefinition(
    ('Detects leaking objects inheriting from goog.Disposable. Remember to set'
     ' goog.Disposable.MONITORING_MODE to'
     ' goog.Disposable.MonitoringMode.INTERACTIVE, and run your application'
     ' with uncompiled JavaScript.'),
    'closure-disposable-suppressions.txt',
    ['goog.Disposable.instances_'],
    ['goog.events'],
    '',
    '.creationStack')

CLOSURE_EVENT_LISTENERS = LeakDefinition(
    ('Detects leaking objects goog.events.Listener. Remember to set'
     ' goog.events.Listener.ENABLE_MONITORING to true, and run your application'
     ' with uncompiled JavaScript.'),
    'closure-event-listeners-suppressions.txt',
    ['goog.events.listeners_'],
    ['goog.events'],
    '',
    '.creationStack')

PREDEFINED_DEFINITIONS = {
    'closure-disposable': CLOSURE_DISPOSABLE,
    'closure-event-listeners': CLOSURE_EVENT_LISTENERS
}


class JSLeakCheck(object):
  """Given a definition, take a heap snapshot, analyze and report new leaks."""

  def __init__(self, leak_definition):
    """Initializes the JSLeakCheck object.

    Args:
      leak_definition: LeakDefinition, defines what kind of leaks to check.
    """
    self.leak_definition = leak_definition
    self._suppressions = []
    if not self.leak_definition.suppressions:
      return
    logging.info('Reading suppressions from "%s"',
                 self.leak_definition.suppressions)
    try:
      self._suppressions = suppressions.ReadSuppressionsFromFile(
          os.path.join(os.path.dirname(__file__),
                       self.leak_definition.suppressions))
    except suppressions.Error as e:
      logging.error('Could not load suppressions: %s', str(e))
    except IOError as e:
      logging.warning('Could not read suppressions file: %s', str(e))

  def Run(self, inspector_client=None):
    """Runs all necessary steps to detect new leaks.

    Args:
      inspector_client: RemoteInspectorClient, used to retrieve the heap
          snapshot. If none is given, a new client is created.
    Returns:
      int, the number of new leaks found.
    Raises:
      leak_finder.Error: Something went wrong with taking or analyzing the
          heap snapshot.
    """

    try:
      client = (inspector_client or
                remote_inspector_client.RemoteInspectorClient())
    except RuntimeError as e:
      raise leak_finder.Error(
          'Cannot create RemoteInspectorClient; most probably you have '
          'DevTools open on the tab we\'re trying to inspect. Original error '
          'message: %s' % e.__str__())

    try:
      leaks = self._FindLeaks(client)
    finally:
      # We don't want to stop a passed-in inspector client so it can be reused.
      if not inspector_client:
        client.Stop()

    if not leaks:
      logging.info('No leaks found.')
      return 0

    logging.info('Scanning for new leaks.')
    return len(self._MatchSuppressions(leaks))

  def _FindLeaks(self, inspector_client):
    """Take a heap snapshot and run LeakFinder on it.

    Args:
      inspector_client: RemoteInspectorClient, used to retrieve the heap
        snapshot.
    Returns:
      [leak_finder.LeakNode], a list of found leaks.
    Raises:
        leak_finder.Error: Something went wrong with taking or analyzing the
            heap snapshot.
    """
    logging.info('Taking heap snapshot')
    try:
      nodes = leak_finder.Snapshotter().GetSnapshot(inspector_client)
    except leak_finder.Error as e:
      logging.error('Error parsing snapshot: %s', str(e))
      raise

    logging.info('Analyzing heap snapshot')
    try:
      leaks = list(leak_finder.LeakFinder(
          self.leak_definition.containers,
          self.leak_definition.bad_nodes,
          self.leak_definition.stacktrace_prefix,
          self.leak_definition.stacktrace_suffix).FindLeaks(nodes))
    except leak_finder.Error as e:
      logging.error('Error analyzing snapshot: %s', str(e))
      raise

    logging.info('Retrieving creating stack traces for leaking objects')
    for leak in leaks:
      leak.RetrieveStackTrace(inspector_client)
    return leaks

  def _MatchSuppressions(self, leaks):
    """Match the list of found leaks against the list of suppressions.

    Prints the leaks not covered by suppressions, and which suppressions
    were used.

    Args:
      leaks: [leak_finder.LeakNode], a list of found leaks.
    Returns:
      [leak_finder.LeakNode], leaks which don't match any suppression.
    """
    matched_suppressions = {}
    new_leaks = []
    for leak in leaks:
      if not leak.stack:
        logging.error('Found leak of type %s without a creation stack',
                      leak.node.class_name)
        continue

      suppression_found = False
      # First, try to match against one of the defined suppressions.
      for index, suppression in enumerate(self._suppressions):
        if suppression.Match(leak.node.class_name, leak.stack.frames):
          matched_suppressions[index] = (
              matched_suppressions.get(index, 0) + 1)
          suppression_found = True
          break

      if not suppression_found:
        # Next, try to match against other unmatched leaks, so we don't
        # end up reporting the same leak over and over again.
        for known_leak in new_leaks:
          if known_leak['suppression'].Match(leak.node.class_name,
                                             leak.stack.frames):
            known_leak['count'] += 1
            suppression_found = True
            break

        if suppression_found:
          continue

        # A new leak.
        new_leaks.append({
            'suppression': suppressions.Suppression(
                '', leak.node.class_name, leak.stack.frames),
            'count': 1,
            'leak': leak})

    if matched_suppressions:
      print 'The following suppressions matched found leaks:'
      for index, count in matched_suppressions.items():
        print ' %d %s' % (count, self._suppressions[index].description)
      print ''

    if new_leaks:
      print 'New memory leaks found:'
      for leak in new_leaks:
        print 'Leak: %d %s' % (leak['count'], leak['leak'].node.class_name)
        print 'allocated at:'
        print '  ' + '\n  '.join(leak['leak'].stack.frames)

    return new_leaks


def main():
  parser = optparse.OptionParser(usage='usage: %prog -d DEFINITION',
                                 epilog='Possible definitions are: %s' %
                                 ', '.join(PREDEFINED_DEFINITIONS.keys()))

  parser.add_option('-d', '--leak_definition', type='choice', action='store',
                    dest='definition', choices=PREDEFINED_DEFINITIONS.keys(),
                    metavar='DEFINITION')

  group = optparse.OptionGroup(parser, 'Manually define conditions for leaks',
                               ('Use this to manually define conditions for '
                                'leaking objects or to modify a predefined '
                                'definition'))
  group.add_option('-s', '--suppressions', metavar='FILENAME',
                   help='Load suppressions from FILENAME')
  group.add_option('-c', '--containers', metavar='VARIABLE', action='append',
                   help=('Name of a JavaScript array that contains '
                         'potentially leaking objects'))
  group.add_option('-b', '--bad-nodes', metavar='VARIABLE', action='append',
                   help=('Name of a JavaScript object that qualifies a '
                         'retaining path as unintentional if it passes '
                         'through this object'))
  group.add_option('-p', '--prefix', metavar='PREFIX',
                   help=('String to prepend to the containers '
                         '(e.g., "jsframe.")'))
  group.add_option('-u', '--suffix', metavar='SUFFIX',
                   help=('String to append to the leaked objects to access the '
                         'member variable where the stack trace is stored '
                         '(e.g. ".stack")'))
  parser.add_option_group(group)

  group = optparse.OptionGroup(parser, 'Specify the tab to debug')
  group.add_option('-t', '--tab_index', type='int', default=0,
                   help='Index of the tab to analyze')
  group.add_option('-T', '--tab_pattern', type='string', default=None,
                   help='Pattern of the tab to analyze')
  group.add_option('-F', '--tab_field', type='string', default='title',
                   help=('Field of the inspect objects to compare against the '
                         'tab_pattern'))
  parser.add_option_group(group)

  parser.add_option('-v', '--verbose', action='store_true', default=False,
                    dest='verbose', help='more verbose output')

  parser.add_option('-r', '--remote-inspector-client-debug',
                    action='store_true', default=False,
                    dest='remote_inspector_client_debug',
                    help='Debug output from RemoteInspectorClient.')

  options = parser.parse_args()[0]

  if options.verbose:
    logging.basicConfig(level=logging.DEBUG)

  leak_definition = LeakDefinition()
  if options.definition:
    leak_definition = PREDEFINED_DEFINITIONS[options.definition]
    logging.info('Using leak definition %s', options.definition)

  if options.suppressions:
    leak_definition.suppressions = options.suppressions
    logging.info('Loading suppressions from %s', options.suppressions)

  if options.containers:
    leak_definition.containers = options.containers
    logging.info('Start searching for leaks from %s',
                 ', '.join(options.containers))

  if options.bad_nodes:
    leak_definition.bad_nodes = options.bad_nodes
    logging.info('Unintential leaks are retained only by %s',
                 ', '.join(options.bad_nodes))

  if options.prefix:
    leak_definition.stacktrace_prefix = options.prefix

  if options.suffix:
    leak_definition.stacktrace_suffix = options.suffix

  if not leak_definition.containers:
    logging.error('Need to specify at least either -d or -c')
    return 1

  tab_filter = None
  if options.tab_pattern:
    pat = re.compile(options.tab_pattern)
    tab_filter = lambda o: pat.search(o[options.tab_field])

  inspector_client = remote_inspector_client.RemoteInspectorClient(
      tab_index=options.tab_index, tab_filter=tab_filter,
      show_socket_messages=options.remote_inspector_client_debug)

  leak_checker = JSLeakCheck(leak_definition)
  try:
    result = leak_checker.Run(inspector_client)
  finally:
    inspector_client.Stop()
  return result

if __name__ == '__main__':
  sys.exit(main())
