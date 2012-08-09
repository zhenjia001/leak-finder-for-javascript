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

"""Tool for finding possibly leaking JavaScript objects based on heap snapshots.

How does it work?

Since JavaScript is a garbage collected language, all objects have one or
several retaining paths which keep the object alive.

This tool finds objects which are only retained (kept alive) by a specified set
of data structures ("bad stop nodes"). Typically those are data structures of a
JavaScript library (e.g., Closure). If an object is only kept alive by such data
structures, the user code doesn't have a pointer to the object, and it can be
considered a "leak". (E.g., the user code forgot to call a function which was
supposed to remove the object from the data structures.)

Example (Closure):

goog.Disposable implements a monitoring mode which gathers all created but not
yet disposed instances of goog.Disposable (and its subclasses) into an array
goog.Disposable.instances_. This array will keep the objects alive. However, if
an object is only kept alive by this array, it is likely a leak, since the user
code doesn't contain any pointers to the object, and the user cannot call
dispose() on it.

Closure contains other data structures (especially for storing event handlers
under goog.events) which keep objects alive. If all retaining paths of an object
go through goog.Disposable.instances_ or goog.events, the object is likely a
leak.

However, if we find a retaining path that goes through a Window object without
going through these bad stop nodes, the object is not a leak.
"""


import simplejson

import stacktrace


class Error(Exception):
  pass


class Node(object):
  """Data structure for representing a node in the heap snapshot.

  Attributes:
    node_id: int, identifier for the node.
    type_string: str, describes the type of the node.
    class_name: str, describes the class of the JavaScript object
        represented by this Node.
    edges_to: [Edge], edges whose end point this Node is.
    edges_from: [Edge], edges whose start point this Node is.
    string: str, for string Nodes, contains the string the Node represents.
        Empty string for non-string nodes.
  """

  def __init__(self, node_id, type_string, class_name):
    """Initializes the Node object.

    Args:
      node_id: int, identifier for the Node.
      type_string: str, the type of the node.
      class_name: str, the class of the JavaScript object this Node represents.
    """

    self.node_id = node_id
    self.type_string = type_string
    self.class_name = class_name
    self.edges_to = []
    self.edges_from = []
    self.string = ''

  def AddEdgeTo(self, edge):
    """Associates an Edge with the Node (the end point).

    Args:
      edge: Edge, an edge whose end point this Node is.
    """
    self.edges_to.append(edge)

  def AddEdgeFrom(self, edge):
    """Associates an Edge with the Node (the start point).

    Args:
      edge: Edge, an edge whose start point this Node is.
    """
    self.edges_from.append(edge)


class Edge(object):
  """Data structure for representing an edge in the heap snapshot.

  Attributes:
    from_node_id: int, id of the node which is the start point of this Edge.
        Used when the corresponding Node object is not yet contstructed.
    to_node_id: int, id of the node which is the end point of this Edge. Used
        when the corresponding Node object is not yet contstructed.
    from_node: Node, the start point of this Edge.
    to_node: Node, the end point of this Edge.
    type_string: str, the type of the Edge.
    name_string: str, the JavaScript attribute name this Edge represents.
  """

  def __init__(self, from_node_id, to_node_id, type_string, name_string):
    """Initializes the Edge object.

    Args:
      from_node_id: int, id of the node which is the start point of this
          Edge. Used when the corresponding Node object is not yet contstructed.
      to_node_id: int, id of the node which is the end point of this
          Edge. Used when the corresponding Node object is not yet contstructed.
      type_string: str, the type of the Edge.
      name_string: str, the JavaScript attribute name this Edge represents.
    """
    self.from_node_id = from_node_id
    self.to_node_id = to_node_id
    self.from_node = {}
    self.to_node = {}
    self.type_string = type_string
    self.name_string = name_string

  def SetFromNode(self, node):
    self.from_node = node
    return self

  def SetToNode(self, node):
    self.to_node = node
    return self


class LeakNode(object):
  """Data structure for representing a potentially leaked heap object.

  Attributes:
    node: Node, represents the leaked JavaScript object.
    description: str, human-readable desription of the leak.
    how_to_find_node: str, JavaScript expression which evaluates to the
        leaked JavaScript object.
    stack: Stack, the creation stack trace of the JavaScript object, or None if
        the stack trace cannot be retrieved or has not yet been retrieved.
  """

  def __init__(self, node, description, how_to_find_node, stacktrace_suffix):
    """Initializes the LeakNode object.

    Args:
      node: Node, represents the leaked JavaScript object.
      description: str, human-readable desription of the leak.
      how_to_find_node: str, JavaScript expression which evaluates to the
          leaked JavaScript object.
      stacktrace_suffix: str, appended to the leaked objects for referring the
          member variable where the stack trace is stored. E.g., ".stack".
    """
    self.node = node
    self.description = description
    self.how_to_find_node = how_to_find_node
    self._stacktrace_suffix = stacktrace_suffix
    self.stack = None

  def RetrieveStackTrace(self, inspector_client=None):
    """Retrieves the creation stack trace and stores it into this LeakNode.

    Args:
      inspector_client: RemoteInspectorClient, client to use for retrieving the
          full stack trace. If None, we will retrieve a possibly shortened value
          from the snapshot.
    """
    stack = None
    if not self._stacktrace_suffix:
      # No stack trace information.
      self.stack = stacktrace.Stack('')
      return

    if inspector_client:
      # The heap snapshot contains only the first 1000 characters of each
      # string.  As we store the creation stack trace in objects as strings, we
      # will need to evaluate this string using the remote inspector client to
      # get the full stack trace.
      stack = inspector_client.EvaluateJavaScript(
          self.how_to_find_node + self._stacktrace_suffix)
    else:
      # See if the object contains a stack trace.
      for edge in self.node.edges_from:
        if edge.name_string == self._stacktrace_suffix:
          stack = edge.to_node.string
          break
    if stack:
      self.stack = stacktrace.Stack(stack)

  def __str__(self):
    stack = ''
    if self.stack:
      stack = 'Stack:\n  %s' % '\n  '.join(self.stack.frames)
    return '%s\nClass: %s\nObject: %s\n%s' % (
        self.description, self.node.class_name, self.how_to_find_node, stack)


class Snapshotter(object):
  """Reads a heap snapshot from a chromium process and parses it.

  The heap snapshot JSON format is defined by HeapSnapshotJSONSerializer in v8.

  Attributes:
    _node_dict: {int -> Node}, maps integer ids to Node objects.
    _node_list: [int], the raw node data of the heap snapshot.
    _edge_list: [int], the raw edge data of the heap snapshot.
    _node_types: [str], the possible node types in the heap snapshot.
    _edge_types: [str], the possible edge types in the heap snapshot.
    _node_fields: [str], the fields present in the heap snapshot for each node.
    _edge_fields: [str], the fields present in the heap snapshot for each node.
    _node_type_ix: int, index of the node type field.
    _node_name_ix: int, index of the node name field.
    _node_id_ix: int, index of the node id field.
    _node_edges_start_ix: int, index of the "edge start index for a node" field.
    _node_edge_count_ix: int, index of the node edge count field.
    _node_edge_count_format: bool, defines if the snapshot uses edges_start or
        edge_count.
    _node_field_count: int, number of node fields.
    _edge_type_ix: int, index of the edge type field.
    _edge_name_or_ix_ix: int, index of the edge name field.
    _edge_to_node_ix: int, index of the "to node for an edge" field.
    _edge_field_count: int, number of edge fields.
  """

  def __init__(self):
    self._node_dict = {}

  def GetSnapshot(self, inspector_client):
    """Reads a heap snapshot from a chromium process and returns the data.

    Args:
      inspector_client: RemoteInspectorClient, the client to used for taking the
          heap snapshot.
    Returns:
      set(Node), the Node objects in the snapshot or None if the snapshot
          couldn't be read.
    Raises:
      KeyError: The snapshot doesn't contain the required data fields.
      ValueError: The snaphost cannot be parsed.
      Error: The snapshot format cannot be parsed (e.g., too new version).
    """
    self._ReadSnapshot(inspector_client)
    self._ParseSnapshot()
    return self._node_dict.values()

  def _FindField(self, field_name, fields_array):
    """Finds field indices based on the snapshot meta information.

    Args:
      field_name: str, the field to find in fields_array.
      fields_array: [str], array of available fields.
    Returns:
      int, the first index of field_name in fields_array.
    Raises:
      Error: field_name doesn't occur in fields_array.
    """
    if field_name not in fields_array:
      raise Error('Cannot find field %s from the snapshot' % field_name)
    return fields_array.index(field_name)

  def _ReadSnapshot(self, inspector_client):
    """Reads a heap snapshot from a chromium process and stores the data.

    The snapshot contains a list of integers describing nodes (types, names,
    etc.) and a list of integers describing edges (types, the node the edge
    points to, etc.) and a string table. All strings are expressed as indices to
    the string table.

    In addition, the snapshot contains meta information describing the data
    fields for nodes and the data fields for edges.

    Args:
      inspector_client: RemoteInspectorClient, the client to used for taking the
          heap snapshot.
    Raises:
      KeyError: The snapshot doesn't contain the required data fields.
      ValueError: The snaphost cannot be parsed.
      Error: The snapshot format is not supported (e.g., too new version).
    """
    raw_data = inspector_client.HeapSnapshot(include_summary=False)['raw_data']

    heap = simplejson.loads(raw_data)
    self._node_list = heap['nodes']
    self._edge_list = heap['edges']
    self._strings = heap['strings']

    self._node_types = heap['snapshot']['meta']['node_types'][0]
    self._edge_types = heap['snapshot']['meta']['edge_types'][0]
    node_fields = heap['snapshot']['meta']['node_fields']
    edge_fields = heap['snapshot']['meta']['edge_fields']

    # Find the indices of the required node and edge fields.
    self._node_type_ix = self._FindField('type', node_fields)
    self._node_name_ix = self._FindField('name', node_fields)
    self._node_id_ix = self._FindField('id', node_fields)

    # Support 2 different snapshot formats:
    # - Define where edges for a given node start in the edge array as
    # edges_index.
    # - Define how many edges a given node has as edge_count.
    if 'edges_index' in node_fields:
      self._node_edges_start_ix = node_fields.index('edges_index')
      self._node_edge_count_format = False
    else:
      self._node_edge_count_ix = self._FindField('edge_count', node_fields)
      self._node_edge_count_format = True

    self._node_field_count = len(node_fields)

    self._edge_type_ix = self._FindField('type', edge_fields)
    self._edge_name_or_ix_ix = self._FindField('name_or_index',
                                               edge_fields)
    self._edge_to_node_ix = self._FindField('to_node', edge_fields)
    self._edge_field_count = len(edge_fields)

  def _ConstructorName(self, type_string, node_name_ix):
    """Returns the constructor name for a node.

    Args:
      type_string: str, type of the node.
      node_name_ix: int, index of the strings array element which contains the
          name of the node, if the type of the node is 'object'. Otherwise, an
          arbitrary value.

    Returns:
      str, the constructor name for the node.
    """
    if type_string == 'object':
      return self._strings[int(node_name_ix)]
    return '(%s)' % type_string

  @staticmethod
  def _IsNodeTypeUninteresting(type_string):
    """Helper function for filtering out nodes from the heap snapshot.

    Args:
      type_string: str, type of the node.
    Returns:
      bool, True if the node is of an uninteresting type and shouldn't be
          included in the heap snapshot analysis.
    """
    uninteresting_types = ('hidden', 'code', 'number', 'native', 'synthetic')
    return type_string in uninteresting_types

  @staticmethod
  def _IsEdgeTypeUninteresting(edge_type_string):
    """Helper function for filtering out edges from the heap snapshot.

    Args:
      edge_type_string: str, type of the edge.
    Returns:
      bool, True if the edge is of an uninteresting type and shouldn't be
          included in the heap snapshot analysis.
    """
    uninteresting_types = ('weak', 'hidden', 'internal')
    return edge_type_string in uninteresting_types

  def _ReadNodeFromIndex(self, ix, edges_start):
    """Reads the data for a node from the heap snapshot.

    If the index contains an interesting node, constructs a Node object and adds
    it to self._node_dict.

    Args:
      ix: int, index into the self._node_list array.
      edges_start: int, if self._node_edge_count_format is True, the index of
          the edge array where the edges for the node start.
    Returns:
      int, if self._node_edge_count_format is True, the edge start index for the
          next node.
    Raises:
      Error: The node list of the snapshot is malformed.
    """
    if ix + self._node_field_count > len(self._node_list):
      raise Error('Snapshot node list too short')

    type_ix = self._node_list[ix + self._node_type_ix]
    type_string = self._node_types[int(type_ix)]

    # edges_end is noninclusive (the index of the first edge that is not part of
    # this node).
    if self._node_edge_count_format:
      edge_count = self._node_list[ix + self._node_edge_count_ix]
      edges_end = edges_start + edge_count * self._edge_field_count
    else:
      # edges_start is the start point of this node's edges in the edge
      # array. The end point of this node's edges is the start point of the next
      # node minus 1.
      edges_start = self._node_list[ix + self._node_edges_start_ix]
      next_edges_start = ix + self._node_edges_start_ix + self._node_field_count
      if next_edges_start < len(self._node_list):
        edges_end = self._node_list[next_edges_start]
      else:
        edges_end = len(self._edge_list)

    if Snapshotter._IsNodeTypeUninteresting(type_string):
      return edges_end

    name_ix = self._node_list[ix + self._node_name_ix]
    node_id = self._node_list[ix + self._node_id_ix]

    ctor_name = self._ConstructorName(type_string, name_ix)
    n = Node(node_id, type_string, ctor_name)
    if type_string == 'string':
      n.string = self._strings[int(name_ix)]

    for edge_ix in xrange(edges_start, edges_end, self._edge_field_count):
      edge = self._ReadEdgeFromIndex(node_id, edge_ix)
      if edge:
        # The edge will be associated with the other endpoint when all the data
        # has been read.
        n.AddEdgeFrom(edge)

    self._node_dict[node_id] = n
    return edges_end

  def _ReadEdgeFromIndex(self, node_id, edge_ix):
    """Reads the data for an edge from the heap snapshot.

    Args:
      node_id: int, id of the node which is the starting point of the edge.
      edge_ix: int, index into the self._edge_list array.
    Returns:
      Edge, if the index contains an interesting edge, otherwise None.
    Raises:
      Error: The node list of the snapshot is malformed.
    """
    if edge_ix + self._edge_field_count > len(self._edge_list):
      raise Error('Snapshot edge list too short')

    edge_type_ix = self._edge_list[edge_ix + self._edge_type_ix]
    edge_type_string = self._edge_types[int(edge_type_ix)]

    if Snapshotter._IsEdgeTypeUninteresting(edge_type_string):
      return None

    child_name_or_ix = self._edge_list[edge_ix + self._edge_name_or_ix_ix]
    child_node_ix = self._edge_list[edge_ix + self._edge_to_node_ix]

    # The child_node_ix is an index into the node list. Read the actual
    # node information.
    child_node_type_ix = self._node_list[child_node_ix + self._node_type_ix]
    child_node_type_string = self._node_types[int(child_node_type_ix)]
    child_node_id = self._node_list[child_node_ix + self._node_id_ix]

    if Snapshotter._IsNodeTypeUninteresting(child_node_type_string):
      return None

    child_name_string = ''
    # For element nodes, the child has no name (only an index).
    if (edge_type_string == 'element' or
        int(child_name_or_ix) >= len(self._strings)):
      child_name_string = str(child_name_or_ix)
    else:
      child_name_string = self._strings[int(child_name_or_ix)]
    return Edge(node_id, child_node_id, edge_type_string, child_name_string)

  def _ParseSnapshot(self):
    """Parses the stored JSON snapshot data.

    Fills in self._node_dict with Node objects constructed based on the heap
    snapshot. The Node objects contain the associated Edge objects.
    """
    edge_start_ix = 0
    for ix in xrange(0, len(self._node_list), self._node_field_count):
      edge_start_ix = self._ReadNodeFromIndex(ix, edge_start_ix)

    # Add pointers to the endpoints to the edges, and associate the edges with
    # the "to" nodes.
    for node_id in self._node_dict:
      n = self._node_dict[node_id]
      for e in n.edges_from:
        self._node_dict[e.to_node_id].AddEdgeTo(e)
        e.SetFromNode(n)
        e.SetToNode(self._node_dict[e.to_node_id])


class LeakFinder(object):
  """Finds potentially leaking JavaScript objects based on a heap snapshot."""

  def __init__(self, containers, bad_stop_nodes, stacktrace_prefix,
               stacktrace_suffix):
    """Initializes the LeakFinder object.

    Potentially leaking Node objects the are children of the nodes described by
    containers which are only retained by the nodes described by bad_stop_nodes.

    Args:
      containers: [str], describes the container JavaScript objects E.g.,
          ['foo.bar', 'mylibrary.all_objects_array']. Only objects in the
          containers are investigated as potential leaks.
      bad_stop_nodes: [str], describes bad stop nodes which don't contribute to
          valid retaining paths. E.g., ['foo.baz', 'mylibrary.secondary_array'].
          A retaining path is bad if it goes through one of the bad nodes. If
          all the retaining paths of an object are bad, the object is considered
          a leak.
      stacktrace_prefix: str, prefix to add to the container name for retrieving
          the stack trace. Useful e.g., if the JavaScript is in different frame.
      stacktrace_suffix: str, name of the member variable where the stack trace
          is stored.
    """
    self._container_description = [c.split('.') for c in containers]
    self._bad_stop_node_description = [b.split('.') for b in bad_stop_nodes]
    self._stacktrace_prefix = stacktrace_prefix
    self._stacktrace_suffix = stacktrace_suffix

  def FindLeaks(self, nodes):
    """Finds Node objects which are potentially leaking.

    Args:
      nodes: set(Node), Node objects in the snapshot.
    Yields:
      LeakNode objects representing the potential leaks.
    Raises:
      Error: Cannot find the Nodes needed by the leak detection algorithm.
    """

    # The retaining paths are computed until meeting one of these nodes.
    stop_nodes = set()

    # A retaining path is bad if it ends to one of these nodes. These are
    # closure data structures. If all retaining paths end in bad stop nodes, the
    # node is probably a leak.
    bad_stop_nodes = set()

    containers = set()
    found_container_edges = set()

    # Find container nodes and stopper nodes based on the descriptions.
    for node in nodes:
      # Window objects are good stop nodes. If a retaining path goes through a
      # Window object without going through any bad stop nodes, the retaining
      # path is good, and the object is not a leak.
      if node.class_name == 'Window' or node.class_name.startswith('Window / '):
        stop_nodes.add(node)
        continue
      for edges in self._bad_stop_node_description:
        if LeakFinder._IsRetainedByEdges(node, edges):
          stop_nodes.add(node)
          bad_stop_nodes.add(node)
          break
      for edges in self._container_description:
        if LeakFinder._IsRetainedByEdges(node, edges):
          containers.add(node)
          stop_nodes.add(node)
          bad_stop_nodes.add(node)
          node.container_name = '.'.join(edges)
          found_container_edges.add(node.container_name)
          break

    # Check that we found all the containers.
    for edges in self._container_description:
      edge_description = '.'.join(edges)
      if edge_description not in found_container_edges:
        raise Error('Container not found: %s' % edge_description)

    # Find objects such that they are in the specified containers and all
    # retaining paths contain either the container or the specified bad stop
    # objects.
    for container in containers:
      for edge in container.edges_from:
        if edge.type_string != 'element':
          continue

        found_good_path = False
        node = edge.to_node
        for path in LeakFinder._FindRetainingPaths(node, [node], stop_nodes):
          # If the last node on the path is in bad_stop_nodes, the path is bad,
          # otherwise it's good (it may end in a good stop node or in a node
          # which doesn't have parents).
          if not path[-1] in bad_stop_nodes:
            found_good_path = True
            # All the objects on the known good path are known to be non-leaks.
            # Utilize this information when finding paths for other objects: As
            # soon as we find a path which hits one of them, we know the object
            # is not leaked.
            for node in path:
              stop_nodes.add(node)
            break
        if not found_good_path:
          node_description = '%s%s[%s]' % (self._stacktrace_prefix,
                                           container.container_name,
                                           edge.name_string)
          leak = LeakNode(edge.to_node, 'Leak', node_description,
                          self._stacktrace_suffix)
          yield leak

  @staticmethod
  def _IsRetainedByEdges(node, edge_names):
    """Returns True if the node is retained by edges called edge_names.

    E.g., _IsRetainedByEdges(node, ['foo', 'bar', 'baz']) returns True if node
    represents obj.foo.bar.baz for some object obj.

    Args:
      node: Node, the Node which migt be retained by edges called edge_names.
      edge_names: [str], the wanted edge names.
    Returns:
      bool, True if a retaining path with the given edge_names was found, False
      otherwise.
    """
    if not edge_names:
      return True
    edge_name = edge_names[-1]
    for edge in node.edges_to:
      if (edge.name_string == edge_name and
          LeakFinder._IsRetainedByEdges(edge.from_node, edge_names[:-1])):
        return True
    return False

  @staticmethod
  def _FindRetainingPaths(node, visited, stop_nodes, max_depth=30):
    """Finds retaining paths for a Node.

    Args:
      node: Node, the Node to find the retaining paths for.
      visited: [Node], the visited path so far.
      stop_nodes: set(Node), nodes which terminate the path (we don't care how
          they are retained)
      max_depth: int, the maximum length of retaining paths to search. The
          search will be terminated when at least one path exceeding max_depth
          is found.
    Yields:
      [Node], retaining paths.
    """
    if len(visited) > max_depth:
      return
    if not node.edges_to or node in stop_nodes:
      yield visited
      return

    for edge in node.edges_to:
      if edge.from_node not in visited:
        visited.append(edge.from_node)
        for path in LeakFinder._FindRetainingPaths(edge.from_node, visited,
                                                   stop_nodes):
          yield path
        visited.pop()
