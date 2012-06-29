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

"""Tests JSLeakCheck."""

import googletest

import jsleakcheck


class LeakDefinitionTest(googletest.TestCase):
  def testConstruction(self):
    definition = jsleakcheck.LeakDefinition('desc', 'file.txt', ['container'],
                                            ['node'])

    self.assertEqual('desc', definition.description)
    self.assertEqual('file.txt', definition.suppressions)
    self.assertEqual(1, len(definition.containers))
    self.assertEqual('container', definition.containers[0])
    self.assertEqual(1, len(definition.bad_nodes))
    self.assertEqual('node', definition.bad_nodes[0])


if __name__ == '__main__':
  googletest.main()
