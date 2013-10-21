#!/usr/bin/env python2
# term.py
# terminal buffer emulator

import re
import sys
import weakref

def intgroups(m):
    return [int(d) for d in m.groups() if d and d.isdigit()]


class Row(object):
    def __init__(self, buf, data=None):
        if not isinstance(buf, weakref.ProxyType):
            buf = weakref.proxy(buf)
        self.buf = buf
        self.cols = buf.cols
        if data:
            self.data = data[:]
        else:
            self.reset()

    def copy(self):
        return Row(self.buf, data=self.data)

    def reset(self):
        self.data = [' ' for i in range(self.cols)]

    def __add__(self, o):
        if isinstance(o, list):
            return self.data + o
        elif isinstance(o, Row):
            return self.data + o.data
        else:
            raise TypeError('expected int or Row, found {}'.format(type(o)))

    def __mul__(self, n):
        if isinstance(n, int):
            return [self.copy() for i in range(n)]
        else:
            raise TypeError('expected int, found {}'.format(type(n)))

    def __getitem__(self, col):
        return self.data[col]

    def __setitem__(self, col, value):
        dirty = False
        if self.data[col] != value:
            dirty = True
        self.data[col] = value
        if dirty:
            self.buf.dirty = True


class Buffer(object):
    def __init__(self, rows, cols):
        self.rows = rows
        self.cols = cols
        self.reset()
        self.dirty = False

    def reset(self):
        self.data = Row(self) * self.rows
        self.dirty = True

    def __getitem__(self, row):
        return self.data[row]

    def __setitem__(self, row, value):
        if isinstance(value, list):
            self.data[row] = Row(self, data=value)
        else:
            raise TypeError('expected list, found {}'.format(type(value)))

    def insert(self, pos):
        self.data.insert(pos, Row(self))

    def __delitem__(self, row):
        del self.data[row]


class Terminal(object):
    ESCAPE = '\033'

    def __init__(self, cols, rows, debug=False, callback=None):
        self.debug = debug
        self.cols = cols
        self.rows = rows
        self.pending = ''
        # chars are stored at self.buf[row][col]
        self.callback = callback
        self.buf = Buffer(self.rows, self.cols)
        self.reset()

    def reset(self):
        self.scroll = (1, self.rows)
        self.row = 1
        self.col = 1
        self.clear()

    def clear(self):
        self.buf.reset()

    @property
    def dirty(self):
        return self.buf.dirty

    @dirty.setter
    def dirty(self, value):
        self.buf.dirty = value

    def move(self, row=None, col=None, rel=False):
        if rel:
            row = self.row + row or 1
            col = self.col + col or 1
        else:
            if row is None:
                row = self.row
            if col is None:
                col = self.col

        if col > self.cols:
            row += 1
            col = 1
        if col < 1:
            col = self.cols
            row -= 1

        start, end = self.scroll
        if row < start:
            row = start
        if row > end:
            self.del_lines(end - row, start)
            row = end

        self.row = row
        self.col = col

    def rel(self, row=None, col=None):
        self.move(row, col, rel=True)

    def erase(self, start, end):
        save = self.row, self.col
        for row in range(start[0], end[0]):
            for col in range(start[1], end[1]):
                self.move(row, col)
                self.puts(' ')
        self.row, self.col = save

    def insert_lines(self, num=1, row=None):
        if row is None:
            row = self.row

        for i in range(num):
            del self.buf[self.scroll[1] - 1]
            self.buf.insert(row)

    def del_lines(self, num=1, row=None):
        if row is None:
            row = self.row

        for i in range(num):
            del self.buf[row - 1]
            self.buf.insert(self.scroll[1])

    def puts(self, s, move=True):
        if isinstance(s, int):
            s = chr(s)
        for c in s:
            self.buf[self.row-1][self.col-1] = c
            if move:
                self.move(self.row, self.col + 1)

    def sequence(self, data, i):
        if self.debug:
            print('control character!', repr(data[i:i+8]))
        return 1

    def pre(self, data, i):
        b = data[i]
        if b == self.ESCAPE:
            return self.sequence(data, i)
        elif b == '\b':
            self.col = max(0, self.col - 1)
            self.puts(' ', move=False)
            return 1
        elif b == '\r':
            self.move(col=1)
            return 1
        elif b == '\n':
            self.move(self.row + 1, 1)
            return 1
        elif b == '\x07':
            # beep
            return 1
        else:
            if self.debug:
                sys.stdout.write(b)
            return None

    def append(self, data):
        if isinstance(data, bytes):
            data = data.decode('utf8', 'replace')
        data = self.pending + data
        self.pending = ''
        i = 0
        while i < len(data):
            pre = self.pre(data, i)
            if pre == 0:
                if i > len(data) - 8:
                    # we might need more data to complete the sequence
                    self.notify()
                    self.pending = data[i:]
                    return
                else:
                    # looks like we don't know how to read this sequence
                    if self.debug:
                        print('Unknown VT100 sequence:', repr(data[i:i+8]))
                    i += 1
                    continue
            elif pre is not None:
                i += pre
                continue
            else:
                self.puts(data[i])
                i += 1
        self.notify()

    def notify(self):
        if self.dirty:
            self.dirty = False
            if self.callback:
                self.callback(self)

    def dump(self):
        return ''.join(col for row in self.buf for col in row + ['\n'])

    def __str__(self):
        return '<{} ({},{})+{}x{}>'.format(
            self.__class__,
            self.row, self.col, self.cols, self.rows)


class VT100(Terminal):
    control = None
    KEYMAP = {
        'backspace': '\b',
        'enter': '\n',
        'escape': '\033',
        'space': ' ',
        'up': '\033[A',
        'down': '\033[B',
        'right': '\033[C',
        'left': '\033[D',
    }

    @classmethod
    def map(cls, key):
        return cls.KEYMAP.get(key, key)

    def __init__(self, *args, **kwargs):
        if not self.control:
            self.control = []

        # control character handlers
        REGEX = (
            # cursor motion
            (r'\[(\d+)A', lambda g: self.rel(-g[0], 0)),
            (r'\[(\d+)B', lambda g: self.rel(g[0], 0)),
            (r'\[(\d+)C', lambda g: self.rel(0, g[0])),
            (r'\[(\d+)D', lambda g: self.rel(0, -g[0])),
            (r'\[(\d+);(\d+)[Hf]', lambda g: self.move(g[0], g[1])),
            # set scrolling region
            (r'\[(\d+);(\d+)r', lambda g: self.set_scroll(g[0], g[1])),
            # insert lines under cursor
            (r'\[(\d+)L', lambda g: self.insert_lines(g[0])),
            # remove lines from cursor
            (r'\[(\d+)M', lambda g: self.del_lines(g[0])),
            # erase from cursor to end of screen
            (r'\[0\?J', lambda g: self.erase(
                (self.row, self.col), (self.rows, self.cols))),
            # noop
            (r'\[\?(\d+)h', None),
            (r'\[([\d;]+)?m', None),
        )
        SIMPLE = (
            ('[A', lambda: self.rel(row=-1)),
            ('[B', lambda: self.rel(row=1)),
            ('[C', lambda: self.rel(col=1)),
            ('[D', lambda: self.rel(col=1)),
            ('[H', lambda: self.move(1, 1)),
            ('[2J', lambda: self.clear()),
            ('[K', lambda: self.erase(
                (self.row, self.col), (self.row + 1, self.cols))),
            ('[L', lambda: self.insert_lines(1)),
            ('[M', lambda: self.del_lines(1)),
            # noop
            ('>', None),
            ('<', None),
            ('[?1l', None),
            ('=', None),
        )

        for r, func in REGEX:
            r = re.compile(r)
            self.control.append((r, func))

        for s, func in SIMPLE:
            r = re.compile(re.escape(s))
            if func:
                def wrap(func):
                    return lambda g: func()

                func = wrap(func)
            self.control.append((r, func))

        super(self.__class__, self).__init__(*args, **kwargs)

    def sequence(self, data, i):
        def call(func, s, groups):
            if func:
                if self.debug:
                    print()
                    print('<ESC "{}">'.format(s))
                func(groups)
            else:
                if self.debug:
                    print()
                    print('<NOOP "{}">'.format(s))
            return len(s)

        context = data[i+1:i+10]
        if not context:
            return 0
        for r, func in self.control:
            m = r.match(context)
            if m:
                return 1 + call(func, m.group(), intgroups(m))

        return 0

    def set_scroll(self, start, end):
        self.scroll = (start, end)

if __name__ == '__main__':
    def debug():
        v = VT100(142, 32, debug=True)
        data = sys.stdin.read()
        print('-= begin input =-')
        print(repr(data))
        print('-= begin parsing =-')
        for b in data:
            v.append(b)
        print('-= begin dump =-')
        print(repr(v.dump()))
        print('-= begin output =-')
        sys.stdout.write(v.dump())

    def static():
        v = VT100(142, 32)
        data = sys.stdin.read()
        v.append(data)
        sys.stdout.write(v.dump())

    def stream():
        v = VT100(80, 24)
        while True:
            b = sys.stdin.read(1)
            if not b:
                break
            v.append(b)
            print('\r\n'.join(v.dump().rsplit('\n')[-3:-1]) + '\r')
            print(v.row, v.col, '\r')
            # sys.stdout.write(v.dump() + '\r')
            # sys.stdout.flush()

    stream()
