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

"""Tests stacktrace."""

import textwrap

import googletest

import stacktrace


class ParseV8FrameTest(googletest.TestCase):
  def _ParseV8Frame(self, frame):
    return stacktrace.Stack('Error\n%s' % frame).frames[0]

  def testConstructor(self):
    fun = self._ParseV8Frame('    at new someFunction (somefile:12:34)')
    self.assertEqual('new someFunction', fun)

    fun = self._ParseV8Frame('    at new <anonymous> (somefile:12:34)')
    self.assertEqual('new <anonymous>', fun)

  def testMethodCall(self):
    fun = self._ParseV8Frame(
        '    at [object Object].function (somefile:12:34)')
    self.assertEqual('[object Object].function', fun)

    fun = self._ParseV8Frame(
        '    at [object Object].function [as method] (somefile:12:34)')
    self.assertEqual('[object Object].function [as method]', fun)

    fun = self._ParseV8Frame(
        '    at [object Object].<anonymous> (somefile:12:34)')
    self.assertEqual('[object Object].<anonymous>', fun)

  def testFunction(self):
    fun = self._ParseV8Frame('    at function (somefile:12:34)')
    self.assertEqual('function', fun)

  def testFileLocation(self):
    fun = self._ParseV8Frame('    at somefile:12:34')
    self.assertEqual('somefile:12:34', fun)

  def testEval(self):
    fun = self._ParseV8Frame('    at eval (native)')
    self.assertEqual('eval', fun)

    fun = self._ParseV8Frame(
        '    at eval at <anonymous> (eval at <anonymous> (unkown source))')
    self.assertEqual('eval at <anonymous>', fun)

  def testInvalid(self):
    fun = self._ParseV8Frame('')
    self.assertEqual('*', fun)

    fun = self._ParseV8Frame('random characters')
    self.assertEqual('*', fun)


class ParseJSCFrameTest(googletest.TestCase):
  def _ParseJSCFrame(self, frame):
    return stacktrace.Stack('--> Stack trace:\n%s' % frame).frames[0]

  def testFunction(self):
    fun = self._ParseJSCFrame('    23   function@somefile:123')
    self.assertEqual('function', fun)

    fun = self._ParseJSCFrame('    23   function@[native code]')
    self.assertEqual('function', fun)

    fun = self._ParseJSCFrame('    23   @somefile:123')
    self.assertEqual('*', fun)

  def testGlobalCode(self):
    fun = self._ParseJSCFrame('    7   global code@somefile:123')
    self.assertEqual('global code', fun)

  def testEval(self):
    fun = self._ParseJSCFrame('    7   eval code@somefile:123')
    self.assertEqual('eval code', fun)

    fun = self._ParseJSCFrame('     7   eval code')
    self.assertEqual('eval code', fun)

  def testInvalid(self):
    fun = self._ParseJSCFrame('')
    self.assertEqual('*', fun)

    fun = self._ParseJSCFrame('random characters')
    self.assertEqual('*', fun)


class StackTest(googletest.TestCase):
  def testJSCStack(self):
    jsc_trace = """--> Stack trace:
    0   frame@somefile:42
    1    @eval code
    2   map@[native code]"""

    stack = stacktrace.Stack(jsc_trace)
    self.assertEqual(stacktrace.Stack.JSC, stack.vm)
    self.assertEqual(3, len(stack.frames))
    self.assertEqual('frame', stack.frames[0])
    self.assertEqual('*', stack.frames[1])
    self.assertEqual('map', stack.frames[2])

  def testV8Stack(self):
    v8_trace = """Error
    at frame (some file:42:1)
    at eval at <anonymous>
    at [object Object].function (unknown source)"""

    stack = stacktrace.Stack(v8_trace)
    self.assertEqual(stacktrace.Stack.V8, stack.vm)
    self.assertEqual(3, len(stack.frames))
    self.assertEqual('frame', stack.frames[0])
    self.assertEqual('eval at <anonymous>', stack.frames[1])
    self.assertEqual('[object Object].function', stack.frames[2])

  def testUnknown(self):
    data = textwrap.dedent("""some data
        across a
      few lines""")
    stack = stacktrace.Stack(data)
    self.assertEqual(stacktrace.Stack.UNKNOWN, stack.vm)
    self.assertEqual(data.split('\n'), stack.frames)


if __name__ == '__main__':
  googletest.main()
