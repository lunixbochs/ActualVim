#!/usr/bin/env python2
# vim.py
# launches and manages a headless vim instance

import itertools
import os
import pty
import select
import socket
import sublime
import subprocess
import threading

from .edit import Edit
from .term import VT100


VISUAL_MODES = ('V', 'v', '^V', '\x16')
replace = [
    ('\\', '\\\\'),
    ('"', '\\"'),
    ('\n', '\\n'),
    ('\r', '\\r'),
    ('\t', '\\t'),
]


def encode(s, t=None):
    types = [
        (str, 'string'),
        ((int, float), 'number'),
        (bool, 'boolean'),
    ]
    if t is None:
        for typ, b in types:
            if isinstance(s, typ):
                t = b
                break
        else:
            return ''

    if t == 'string':
        for a, b in replace:
            s = s.replace(a, b)
        return '"' + s + '"'
    elif t == 'number':
        return str(s)
    elif t == 'boolean':
        return 'T' if s else 'F'
    elif t == 'color':
        if isinstance(s, (int, float)) or s:
            return str(s)
        else:
            return encode('none')


def decode(s, t=None):
    if t is None:
        if s.startswith('"'):
            t = 'string'
        elif s.replace('.', '', 1).isdigit():
            t = 'number'
        elif s in 'TF':
            t = 'boolean'
        else:
            return s

    if t == 'string':
        s = s.replace('"', '', 1)[:-1]
        for a, b in replace:
            s = s.replace(b, a)
        return s
    elif t == 'number':
        return float(s)
    elif t == 'boolean':
        return True if s == 'T' else False
    else:
        return s


class VimSocket:
    def __init__(self, vim, view, callback=None):
        self.vim = vim
        self.view = view
        self.server = socket.socket()
        self.server.bind(('localhost', 0))
        self.server.listen(1)
        self.client = None
        self.extra = ''
        self.port = self.server.getsockname()[1]
        self.serial = itertools.count(start=2)
        self.callbacks = {}
        self.callback = callback
        self.preload = []

    def spawn(self):
        threading.Thread(target=self.loop).start()

    def active(self):
        return self.view.buffer_id() != 0 and self.server.fileno() >= 0

    def handle(self, data):
        view = self.view
        data = self.extra + data
        commands = data.split('\n')
        self.extra = commands.pop()
        edits = []
        for cmd in commands:
            if ':' in cmd:
                buf, cmd = cmd.split(':', 1)
                cmd, args = cmd.split('=', 1)
                if ' ' in args:
                    seq, args = args.split(' ', 1)
                else:
                    seq, args = args, None
                seq = int(seq)

                if cmd == 'insert':
                    pos, text = args.split(' ', 1)
                    text = decode(text, 'string')
                    pos = decode(pos)
                    if text == '\n':
                        pos -= 1

                    edits.append(('insert', pos, text))
                elif cmd == 'remove':
                    pos, length = args.split(' ', 1)
                    pos, length = int(pos), int(length)
                    if length > 0:
                        edits.append(('erase', sublime.Region(pos, pos+length)))
                elif cmd == 'disconnect':
                    view.set_scratch(True)
                    raise socket.error
            else:
                if ' ' in cmd:
                    seq, cmd = cmd.split(' ', 1)
                else:
                    seq, cmd = cmd, ''
                if seq.isdigit():
                    seq = int(seq)
                    callback = self.callbacks.pop(seq, None)
                    if callback:
                        callback(cmd)

        if edits:
            def cursor(args):
                buf, lnum, col, off = [int(a) for a in args.split(' ')]
                with Edit(view) as edit:
                    for args in edits:
                        edit.step(*args)
                    edit.reselect(off)

                self.callback(self.vim)
            self.get_cursor(cursor)

    def send(self, data):
        if not self.client:
            self.preload.append(data)
            return

        try:
            data = (data + '\r\n').encode('utf8')
            self.client.send(data)
        except socket.error:
            self.close()

    def close(self, disconnect=False):
        self.view.close()
        if self.client:
            if disconnect:
                self.send('1:disconnect!1')
            self.client.close()

    def loop(self):
        sockets = [self.server]
        try:
            while self.active():
                try:
                    ready, _, _ = select.select(sockets, [], [], 0.1)
                except ValueError:
                    raise socket.error
                if not self.client:
                    if self.server in ready:
                        print('client connection')
                        self.client, addr = self.server.accept()
                        sockets = [self.client]
                        self.send('1:create!1')
                        for line in self.preload:
                            self.send(line)
                    else:
                        continue
                elif self.client in ready:
                    # we're willing to wait up to 1/120 of a second
                    # for a delete following an erase
                    # this and a big buffer prevent flickering.
                    data = self.client.recv(102400).decode('utf8')
                    if 'remove' in data and not 'insert' in data:
                        more, _, _ = select.select([self.client], [], [], 1.0 / 120)
                        if more:
                            data += self.client.recv(102400).decode('utf8')

                    # print('data:', data)
                    if data:
                        self.handle(data)
                    else:
                        break
        except socket.error:
            pass
        finally:
            self.close(disconnect=True)

    def cmd(self, buf, name, *args, **kwargs):
        seq = kwargs.get('seq', 1)
        sep = kwargs.get('sep', '!')
        cmd = '{}:{}{}{}'.format(buf, name, sep, seq)
        if args is not None:
            cmd += ' ' + ' '.join(encode(a) for a in args)
        self.send(cmd)

    def func(self, *args, **kwargs):
        return self.cmd(*args, sep='/', **kwargs)

    def add_callback(self, callback):
        if not callback:
            return None
        serial = next(self.serial)
        self.callbacks[serial] = callback
        return serial

    def get_cursor(self, callback):
        serial = self.add_callback(callback)
        self.func('1', 'getCursor', seq=serial)

    def set_cursor(self, offset, callback=None):
        serial = self.add_callback(callback)
        self.cmd('1', 'setDot', offset, seq=serial)

    def insert(self, offset, text):
        self.func('1', 'insert', offset, str(text or ''))

    def init_done(self):
        self.cmd('1', 'initDone')


class Vim:
    DEFAULT_CMD = ('vim',)

    @property
    def vimrc(self):
        return (
            '--cmd', 'set fileformat=unix',
            '--cmd', 'set lines={} columns={}'.format(self.rows, self.cols),
            '--cmd', '''set statusline=%{printf(\\"%d+%d,%s,%d+%d\\",line(\\".\\"),col(\\".\\"),mode(),line(\\"v\\"),col(\\"v\\"))}''',
            '--cmd', 'set laststatus=2',
            '--cmd', 'set shortmess=aoOtTWAI',
        )

    def __init__(self, view, rows=24, cols=80, monitor=None, cmd=None, update=None, modify=None):
        self.view = view
        self.monitor = monitor
        self.rows = rows
        self.cols = cols
        self.cmd = cmd or self.DEFAULT_CMD
        self.update_callback = update
        self.modify_callback = modify

        self.proc = None
        self.input = None
        self.output = None
        self.row = self.col = 0
        self.mode = 'n'
        self.visual = (0, 0)
        self.visual_selected = False

        self.panel = None
        self.tty = None
        self.__serve()
        self.__spawn()

    def __spawn(self):
        master, slave = pty.openpty()
        devnul = open(os.devnull, 'r')
        cmd = self.cmd + ('-nb::{}'.format(self.port),) + self.vimrc
        self.proc = subprocess.Popen(
            cmd, stdin=slave, stdout=slave,
            stderr=devnul, close_fds=True)
        self.output = os.fdopen(master, 'rb')
        self.input = os.fdopen(master, 'wb')

        def pump():
            self.tty = v = VT100(self.cols, self.rows, callback=self._update)
            while True:
                b = self.output.read(1)
                if not b:
                    # TODO: subprocess closed tty. recover somehow?
                    break
                v.append(b)
        threading.Thread(target=pump).start()

    def __serve(self):
        self.socket = VimSocket(self, self.view, callback=self.modify_callback)
        self.port = self.socket.port
        self.socket.spawn()

    def _update(self, v, dirty, moved):
        data = v.dump()
        self.status, self.cmdline = [
            s.strip() for s in data.rsplit('\n')[-3:-1]
        ]
        try:
            if self.status.count('+') >= 2:
                pos, rest = self.status.split(',', 1)
                row, col = pos.split('+', 1)
                self.row, self.col = int(row), int(col)

                self.mode, rest = rest.split(',', 1)

                a, b = rest.split('+', 1)
                self.visual = (int(a), int(b))
            # print(self.status)
        except ValueError:
            pass

        if self.monitor:
            with Edit(self.monitor) as edit:
                if dirty:
                    edit.erase(sublime.Region(0, self.monitor.size()))
                    edit.insert(0, data)
                    edit.reselect(
                        lambda view: view.text_point(v.row - 1, v.col - 1))

                def update_cursor(view, edit):
                    row, col = (self.row - 1, self.col + 1)
                    # see if it's prompting for input
                    if v.row == self.rows and v.col > 0:
                        char = v.buf[v.row - 1][0]
                        if char in ':/':
                            row, col = (v.row - 1, v.col - 1)
                    pos = view.text_point(row, col)
                    sel = sublime.Region(pos, pos)
                    view.add_regions(
                        'cursor', [sel], 'comment',
                        '', sublime.DRAW_EMPTY,
                    )
                if moved:
                    edit.callback(update_cursor)

        if self.update_callback:
            self.update_callback(self, dirty, moved)

    def send(self, b):
        # send input
        if self.input:
            self.input.write(b.encode('utf8'))
            self.input.flush()

    def press(self, *keys):
        for key in keys:
            b = VT100.map(key)
            self.send(b)

    def type(self, text):
        self.press(*list(text))

    def close(self):
        print('ending Vim')
        self.view.close()
        if self.monitor:
            self.monitor.close()
        self.proc.kill()
        self.socket.close()

    def update_cursor(self, *args, **kwargs):
        def callback(args):
            buf, lnum, col, off = [int(a) for a in args.split(' ')]
            with Edit(self.view) as edit:
                edit.reselect(off)
        self.socket.get_cursor(callback)

    def get_cursor(self, callback):
        self.socket.get_cursor(callback)

    def set_cursor(self, offset, callback=None):
        self.socket.set_cursor(offset, callback=callback)

    def insert(self, offset, text):
        self.socket.insert(offset, text)

    def init_done(self):
        self.socket.init_done()

if __name__ == '__main__':
    import time

    v = Vim()
    time.sleep(3)
    v.send('i')
    while True:
        v.send('asdfjkl ')
        time.sleep(1)
