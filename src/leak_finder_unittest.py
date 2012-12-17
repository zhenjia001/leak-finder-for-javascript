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

"""Tests LeakFinder."""

import unittest

import simplejson
import leak_finder


class LeakFinderTest(unittest.TestCase):

  def _GetLists(self, generator):
    lists = []
    for i in generator:
      lists.append(list(i))
    return lists

  def _GetObjects(self, generator):
    objects = []
    for i in generator:
      objects.append(i)
    return objects

  def _CreatePropertyEdge(self, n1, n2, name):
    """Helper for creating test data."""

    edge = leak_finder.Edge(n1.node_id, n2.node_id, 'property', name)
    edge.SetFromNode(n1).SetToNode(n2)
    n1.AddEdgeFrom(edge)
    n2.AddEdgeTo(edge)

  def _CreateElementEdge(self, n1, n2, name):
    """Helper for creating test data."""

    edge = leak_finder.Edge(n1.node_id, n2.node_id, 'element', name)
    edge.SetFromNode(n1).SetToNode(n2)
    n1.AddEdgeFrom(edge)
    n2.AddEdgeTo(edge)

  def _DataChain(self):
    """Helper for creating test data.

    (n1) - first -> (n2) - second -> (n3)

    Returns:
      List of Nodes in the data.
    """
    n1 = leak_finder.Node(1, 'object', 'Object')
    n2 = leak_finder.Node(2, 'object', 'Object')
    n3 = leak_finder.Node(3, 'object', 'Object')
    self._CreatePropertyEdge(n1, n2, 'first')
    self._CreatePropertyEdge(n2, n3, 'second')
    return [n1, n2, n3]

  def _DataLoop(self):
    """Helper for creating test data.

    (n1) - first -> (n2) - second -> (n3) - loop -> (n1)

    Returns:
      List of Nodes in the data.
    """
    n1 = leak_finder.Node(1, 'object', 'Object')
    n2 = leak_finder.Node(2, 'object', 'Object')
    n3 = leak_finder.Node(3, 'object', 'Object')
    self._CreatePropertyEdge(n1, n2, 'first')
    self._CreatePropertyEdge(n2, n3, 'second')
    self._CreatePropertyEdge(n3, n1, 'loop')
    return [n1, n2, n3]

  def _DataBranch(self):
    """Helper for creating test data.

    (n1) - first -> (n2) - second -> (n3)
                  /
    (n4) - other -

    Returns:
      List of Nodes in the data.
    """
    n1 = leak_finder.Node(1, 'object', 'Object')
    n2 = leak_finder.Node(2, 'object', 'Object')
    n3 = leak_finder.Node(3, 'object', 'Object')
    n4 = leak_finder.Node(4, 'object', 'Object')
    self._CreatePropertyEdge(n1, n2, 'first')
    self._CreatePropertyEdge(n2, n3, 'second')
    self._CreatePropertyEdge(n4, n2, 'second')
    return [n1, n2, n3, n4]

  def _DataLoopAndBranch(self):
    """Helper for creating test data.

    (n1) - first -> (n2) - second -> (n3) - loop -> (n1)
                  /
    (n4) - other -

    Returns:
      List of Nodes in the data.
    """
    n1 = leak_finder.Node(1, 'object', 'Object')
    n2 = leak_finder.Node(2, 'object', 'Object')
    n3 = leak_finder.Node(3, 'object', 'Object')
    n4 = leak_finder.Node(4, 'object', 'Object')
    self._CreatePropertyEdge(n1, n2, 'first')
    self._CreatePropertyEdge(n2, n3, 'second')
    self._CreatePropertyEdge(n3, n1, 'loop')
    self._CreatePropertyEdge(n4, n2, 'other')
    return [n1, n2, n3, n4]

  def _DataLeaks(self):
    """Helper for creating test data.

    (n1) - container -> (n2) - [0] -> (n3)
                         |
                         |   - [1] -> (n4) < - a - (n6) < - bad - (n8)
                         |
                         \   - [2] -> (n5) < - b - (n7) < - good - (n9)

    Returns:
      List of Nodes in the data.
    """
    n1 = leak_finder.Node(1, 'object', 'Object')
    n2 = leak_finder.Node(2, 'array', 'Array')
    n3 = leak_finder.Node(3, 'object', 'Object')
    n4 = leak_finder.Node(4, 'object', 'Object')
    n5 = leak_finder.Node(5, 'object', 'Object')
    n6 = leak_finder.Node(6, 'object', 'Object')
    n7 = leak_finder.Node(7, 'object', 'Object')
    n8 = leak_finder.Node(6, 'object', 'Object')
    n9 = leak_finder.Node(7, 'object', 'Object')
    self._CreatePropertyEdge(n1, n2, 'container')
    self._CreateElementEdge(n2, n3, '0')
    self._CreateElementEdge(n2, n4, '1')
    self._CreateElementEdge(n2, n5, '2')
    self._CreatePropertyEdge(n6, n4, 'a')
    self._CreatePropertyEdge(n7, n5, 'b')
    self._CreatePropertyEdge(n8, n6, 'bad')
    self._CreatePropertyEdge(n9, n7, 'good')
    return [n1, n2, n3, n4, n5, n6, n7, n8, n9]

  def testIsRetainedByEdge(self):
    [_, _, n3] = self._DataChain()
    self.assertTrue(
        leak_finder.LeakFinder._IsRetainedByEdges(n3, ['first', 'second']))
    self.assertTrue(leak_finder.LeakFinder._IsRetainedByEdges(n3, ['second']))
    self.assertFalse(leak_finder.LeakFinder._IsRetainedByEdges(n3, ['first']))
    self.assertFalse(
        leak_finder.LeakFinder._IsRetainedByEdges(n3, ['first', 'foo']))
    self.assertFalse(
        leak_finder.LeakFinder._IsRetainedByEdges(n3, ['foo', 'second']))

  def testFindRetainingPathsBranch(self):
    lf = leak_finder.LeakFinder([], [], '', '')
    [n1, n2, n3, n4] = self._DataBranch()

    paths = self._GetLists(lf._FindRetainingPaths(n3, [n3], set()))
    self.assertEqual(2, len(paths))
    self.assertEqual(3, len(paths[0]))
    self.assertEqual(n3, paths[0][0])
    self.assertEqual(n2, paths[0][1])
    self.assertEqual(3, len(paths[1]))
    self.assertEqual(n3, paths[1][0])
    self.assertEqual(n2, paths[1][1])
    self.assertTrue(paths[0][2] == n1 or paths[1][2] == n1)
    self.assertTrue(paths[0][2] == n4 or paths[1][2] == n4)
    self.assertNotEqual(paths[0][2], paths[1][2])

  def testFindRetainingPathsLoop(self):
    lf = leak_finder.LeakFinder([], [], '', '')
    [_, _, n3] = self._DataLoop()

    paths = self._GetLists(lf._FindRetainingPaths(n3, [n3], set()))
    self.assertEqual(0, len(paths))

  def testFindRetainingPathsLoopAndBranch(self):
    lf = leak_finder.LeakFinder([], [], '', '')
    [_, n2, n3, n4] = self._DataLoopAndBranch()

    paths = self._GetLists(lf._FindRetainingPaths(n3, [n3], set()))
    self.assertEqual(1, len(paths))
    self.assertEqual(3, len(paths[0]))
    self.assertEqual(n3, paths[0][0])
    self.assertEqual(n2, paths[0][1])
    self.assertEqual(n4, paths[0][2])

  def testFindLeaksBranch(self):
    nodelist = [_, _, n3, n4, _, _, _, _, _] = self._DataLeaks()
    nodes = set()
    for n in nodelist:
      nodes.add(n)
    lf = leak_finder.LeakFinder(['container'], ['bad'], '', '')
    leaks = self._GetObjects(lf.FindLeaks(nodes))
    self.assertEqual(2, len(leaks))
    self.assertTrue(leaks[0].node == n3 or leaks[1].node == n3)
    self.assertTrue(leaks[0].node == n4 or leaks[1].node == n4)
    self.assertNotEqual(leaks[0].node, leaks[1].node)

  class MockSnapshotter(object):
    def __init__(self, data_to_return):
      self.called = False
      self.data_to_return = {'raw_data': simplejson.dumps(data_to_return)}

    def HeapSnapshot(self, include_summary):
      if not include_summary:
        self.called = True
      return self.data_to_return

  def _HeapSnapshotData(self, node_types, edge_types, node_fields, edge_fields,
                        node_list, edge_list, strings):
    """Helper for creating heap snapshot data."""
    return {'snapshot': {'meta': {'node_types': [node_types],
                                  'edge_types': [edge_types],
                                  'node_fields': node_fields,
                                  'edge_fields': edge_fields}},
            'nodes': node_list,
            'edges': edge_list,
            'strings': strings}

  def testSnapshotter(self):
    try:
      mock_client = LeakFinderTest.MockSnapshotter({})
      leak_finder.Snapshotter().GetSnapshot(mock_client)
    except KeyError:
      # The data we return is invalid, so a KeyError will be thrown.
      pass
    self.assertTrue(mock_client.called)

  def testParseSimpleSnapshotInOldFormat(self):
    # Create a snapshot containing 2 nodes and an edge between them.
    node_types = ['object']
    edge_types = ['property']
    node_fields = ['type', 'name', 'id', 'edges_index']
    edge_fields = ['type', 'name_or_index', 'to_node']
    node_list = [0, 0, 0, 0,
                 0, 1, 1, 3]
    edge_list = [0, 2, 4]
    strings = ['node1', 'node2', 'edge1']
    heap = self._HeapSnapshotData(node_types, edge_types, node_fields,
                                  edge_fields, node_list, edge_list, strings)
    mock_client = LeakFinderTest.MockSnapshotter(heap)
    nodes = list(leak_finder.Snapshotter().GetSnapshot(mock_client))
    self.assertEqual(2, len(nodes))
    if nodes[0].edges_from:
      from_ix = 0
      to_ix = 1
    else:
      from_ix = 1
      to_ix = 0
    self.assertEqual('node1', nodes[from_ix].class_name)
    self.assertEqual('node2', nodes[to_ix].class_name)
    self.assertEqual(1, len(nodes[from_ix].edges_from))
    self.assertEqual(0, len(nodes[from_ix].edges_to))
    self.assertEqual(0, len(nodes[to_ix].edges_from))
    self.assertEqual(1, len(nodes[to_ix].edges_to))
    self.assertEqual('node1', nodes[from_ix].edges_from[0].from_node.class_name)
    self.assertEqual('node2', nodes[from_ix].edges_from[0].to_node.class_name)
    self.assertEqual('edge1', nodes[from_ix].edges_from[0].name_string)
    self.assertEqual('node1', nodes[to_ix].edges_to[0].from_node.class_name)
    self.assertEqual('node2', nodes[to_ix].edges_to[0].to_node.class_name)
    self.assertEqual('edge1', nodes[to_ix].edges_to[0].name_string)

  def testParseSimpleSnapshot(self):
    # Create a snapshot containing 2 nodes and an edge between them.
    node_types = ['object']
    edge_types = ['property']
    node_fields = ['type', 'name', 'id', 'edge_count']
    edge_fields = ['type', 'name_or_index', 'to_node']
    node_list = [0, 0, 0, 1,
                 0, 1, 1, 0]
    edge_list = [0, 2, 4]
    strings = ['node1', 'node2', 'edge1']
    heap = self._HeapSnapshotData(node_types, edge_types, node_fields,
                                  edge_fields, node_list, edge_list, strings)
    mock_client = LeakFinderTest.MockSnapshotter(heap)
    nodes = list(leak_finder.Snapshotter().GetSnapshot(mock_client))
    self.assertEqual(2, len(nodes))
    if nodes[0].edges_from:
      from_ix = 0
      to_ix = 1
    else:
      from_ix = 1
      to_ix = 0
    self.assertEqual('node1', nodes[from_ix].class_name)
    self.assertEqual('node2', nodes[to_ix].class_name)
    self.assertEqual(1, len(nodes[from_ix].edges_from))
    self.assertEqual(0, len(nodes[from_ix].edges_to))
    self.assertEqual(0, len(nodes[to_ix].edges_from))
    self.assertEqual(1, len(nodes[to_ix].edges_to))
    self.assertEqual('node1', nodes[from_ix].edges_from[0].from_node.class_name)
    self.assertEqual('node2', nodes[from_ix].edges_from[0].to_node.class_name)
    self.assertEqual('edge1', nodes[from_ix].edges_from[0].name_string)
    self.assertEqual('node1', nodes[to_ix].edges_to[0].from_node.class_name)
    self.assertEqual('node2', nodes[to_ix].edges_to[0].to_node.class_name)
    self.assertEqual('edge1', nodes[to_ix].edges_to[0].name_string)

  def testRetainingPathToString(self):
    n1 = leak_finder.Node(1, 'object', 'Object')
    n2 = leak_finder.Node(2, 'object', 'Object')
    n3 = leak_finder.Node(3, 'object', 'Object')
    self._CreatePropertyEdge(n1, n2, 'first')
    self._CreateElementEdge(n2, n3, '5')

    path = leak_finder.LeakFinder._RetainingPathToString([n3, n2, n1])
    self.assertEqual('Node(1 Object).first[5]', path)

    n1.js_name = 'window.node'
    path = leak_finder.LeakFinder._RetainingPathToString([n3, n2, n1])
    self.assertEqual('window.node.first[5]', path)


if __name__ == '__main__':
  unittest.main()
