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

"""Valgrind-style suppressions for find_js_leaks reports.

The format of the suppressions is modelled after the suppression format used
by valgrind.

Suppressions are defined as follows (short description, name of the leaking
class, and at least one frame is required):

{
  <short human-readable description of the error>
  name of leaking class
  frame_name
  wildcarded_fram*_name
  [object Object].fancyJavaScriptFrame [as someMethod]
  # an ellipsis wildcards zero or more frames in a stack.
  ...
  another_frame
}
"""

import re


class Error(Exception):
  """Base class for exceptions thrown by this module."""


class ParseError(Error):
  """Thrown if a suppression file could not be parsed."""


class UnexpectedEofError(Error):
  """Thrown if the end of a suppression file was reached unexpectedly."""


class Suppression(object):
  """Data structure for representing a single suppression."""

  def __init__(self, description, class_name, stack):
    """Initializes the Suppression object.

    Args:
      description: A human-readable description of the suppressed location.
      class_name: The class name of the leaking object.
      stack: A list of stack frames or wildcards.
    """
    self.description = description
    self.class_name = class_name
    self._stack = stack
    self._regex = self._ConvertStackToRegex()

  def _ConvertStackToRegex(self):
    """Converts the suppression defined by self._stack to a multiline regexp."""

    # To allow for wildcards in the class name as well, we just treat it
    # as another frame.
    frames = [self.class_name] + self._stack

    regex_parts = []

    for frame in frames:
      # The class name can have wildcards but no ellipsis. As we
      # prepended the class name to the stack above, we just check that
      # the regex_parts variable is non-empty, i.e. it at least contains the
      # class name.
      if frame == '...' and regex_parts:
        regex_parts.append('(.*\n)*')
      else:
        regex_parts.append('.*'.join([re.escape(f) for f in frame.split('*')]))
        regex_parts.append('\n')

    return re.compile(''.join(regex_parts), re.MULTILINE)

  def Match(self, class_name, stack):
    """Tests whether the suppression matches the given stack.

    Args:
      class_name: the class of the leaking object.
      stack: list of stack frames.
    Returns:
      True if the suppression is not empty and matches the report.
    """
    frames = [class_name] + stack
    if self._stack and self._regex.match('\n'.join(frames) + '\n'):
      return True
    return False


def ReadSuppressionsFromFile(filename, open=open):  # pylint: disable=W0622
  """Given a file, returns a list of Suppression objects.

  Args:
    filename: The name of the file with the suppressions to load.
    open: Used to inject open for tests

  Returns:
    List of Suppression objects.

  Raises:
    IOError: Something went wrong reading the file.
    ParseError: The file could not be parsed.
    UnexpectedEofError: The end of file was reached unexpectedly.
  """
  result = []

  description = None
  class_name = None
  stack = []
  in_suppression = False

  fp = open(filename)
  line_no = 0
  for line in fp:
    line_no += 1
    line = line.strip()
    if not line or line.startswith('#'):
      continue
    elif line.startswith('{'):
      in_suppression = True
    elif line.startswith('}'):
      result.append(Suppression(description, class_name, stack))
      description = None
      class_name = None
      stack = []
      in_suppression = False
    elif not in_suppression:
      fp.close()
      raise ParseError('%s: %d: Expected beginning of suppression' %
                       (filename, line_no))
    else:
      if not description:
        description = line
      elif not class_name:
        class_name = line
      elif line.startswith('...'):
        stack.append('...')
      else:
        stack.append(line)

  if in_suppression:
    raise UnexpectedEofError('%s: %d: Unexpected end-of-file' %
                             (filename, line_no))
  return result
