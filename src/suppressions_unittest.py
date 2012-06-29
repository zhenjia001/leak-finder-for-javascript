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

"""Tests Suppressions."""

import StringIO
import textwrap

import googletest

import suppressions


class SuppressionTest(googletest.TestCase):
  def testEmpty(self):
    supp = suppressions.Suppression('', '', [])
    self.assertFalse(supp.Match('', []))
    self.assertFalse(supp.Match('foo', []))
    self.assertFalse(supp.Match('foo', ['bar']))

  def testClassNames(self):
    supp = suppressions.Suppression('', '*Event', ['...'])
    self.assertTrue(supp.Match('someEvent', ['foo']))
    self.assertTrue(supp.Match('Event', ['foo']))
    self.assertFalse(supp.Match('someEvents', ['foo']))

    supp = suppressions.Suppression('', '...', ['foo'])
    self.assertFalse(supp.Match('foo', []))
    self.assertFalse(supp.Match('foo', ['foo']))

  def testEllipsis(self):
    supp = suppressions.Suppression('', '*', ['...'])
    self.assertTrue(supp.Match('foo', []))
    self.assertTrue(supp.Match('foo', ['bar']))
    self.assertTrue(supp.Match('foo', ['bar', 'baz']))

    supp = suppressions.Suppression('', '*', ['foo', '...', 'bar'])
    self.assertTrue(supp.Match('foo', ['foo', 'bar']))
    self.assertTrue(supp.Match('foo', ['foo', '1', 'bar']))
    self.assertTrue(supp.Match('foo', ['foo', '1', '2', 'bar']))
    self.assertFalse(supp.Match('foo', ['foo', '1', '2']))
    self.assertFalse(supp.Match('foo', ['1', '2', 'bar']))


class ReadSuppressionsFromFileTest(googletest.TestCase):
  def testReadFile(self):
    test_file = textwrap.dedent("""\
      # some comment
      {
        a sample suppression
        myClass
        frame
        ...
        another frame
      }

      # more comments
      {
        another suppression
        class*
        frame1
        frame2
        frame3
      }
      """)

    dummy_open = lambda x: StringIO.StringIO(test_file)
    result = suppressions.ReadSuppressionsFromFile('', open=dummy_open)

    self.assertEqual(2, len(result))

    supp = result[0]
    self.assertEqual('myClass', supp.class_name)
    self.assertEqual(['frame', '...', 'another frame'], supp._stack)

    supp = result[1]
    self.assertEqual('class*', supp.class_name)
    self.assertEqual(['frame1', 'frame2', 'frame3'], supp._stack)

  def testParseError(self):
    test_file_early_eof = textwrap.dedent("""\
      # some comment
      {
        a sample suppression
        myClass
        frame
        ...
      """)
    dummy_open = lambda x: StringIO.StringIO(test_file_early_eof)
    with self.assertRaises(suppressions.UnexpectedEofError):
      suppressions.ReadSuppressionsFromFile('', open=dummy_open)

    test_file_unparsable = textwrap.dedent("""\
      # some comment
      {
        a sample suppression
        myClass
        frame
        ...
        another frame
      }

      this doesn't parse
      """)
    dummy_open = lambda x: StringIO.StringIO(test_file_unparsable)
    with self.assertRaises(suppressions.ParseError):
      suppressions.ReadSuppressionsFromFile('', open=dummy_open)


if __name__ == '__main__':
  googletest.main()
