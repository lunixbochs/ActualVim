#!/usr/bin/env python2
# vim.py
# launches and manages a headless vim instance

import os
import pty
import select
import socket
import sublime
import subprocess
import threading

from .edit import Edit
from .term import VT100


class VimSocket:
    def __init__(self, view):
        self.view = view
        self.server = socket.socket()
        self.server.bind(('localhost', 0))
        self.server.listen(1)
        self.client = None
        self.extra = ''
        self.port = self.server.getsockname()[1]

    def spawn(self):
        threading.Thread(target=self.loop).start()

    def active(self):
        return self.view.buffer_id() != 0 and self.server.fileno() >= 0
    
    def handle(self, data):
        view = self.view
        data += self.extra
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
                if cmd == 'insert':
                    pos, text = args.split(' ', 1)
                    text = text.replace('"', '', 1).rsplit('"', 1)[0]
                    text = text.replace('\\n', '\n')
                    pos = int(pos)
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

        with Edit(view) as edit:
            for args in edits:
                edit.step(*args)

    def send(self, data):
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
                ready, _, _ = select.select(sockets, [], [], 0.1)
                if not self.client:
                    if self.server in ready:
                        print('client connection')
                        self.client, addr = self.server.accept()
                        sockets = [self.client]
                        self.send('1:create!1')
                    else:
                        continue
                elif self.client in ready:
                    # the receive buffer is absurdly long
                    # allowing us to batch edits with pretty much any line length
                    # because an edit requires a successive delete/insert
                    # it would flicker without this
                    data = self.client.recv(102400).decode('utf8')
                    # print('data:', data)
                    if data:
                        self.handle(data)
                    else:
                        break
        except socket.error:
            pass
        finally:
            self.close(disconnect=True)


class Vim:
    ROWS = 24
    COLS = 80
    VIMRC = (
        '--cmd', 'set fileformat=unix',
        '--cmd', 'set lines={} columns={}'.format(ROWS, COLS),
        '--cmd', '''set statusline=%{printf(\\"%d+%d,%s,%d+%d\\",line(\\".\\"),col(\\".\\"),mode(),line(\\"v\\"),col(\\"v\\"))}''',
        '--cmd', 'set laststatus=2',
        '--cmd', 'set shortmess=aoOtTWAI',
    )
    DEFAULT_CMD = ('vim',) + VIMRC

    def __init__(self, view, monitor=None, cmd=None, callback=None):
        self.view = view
        self.monitor = monitor
        self.cmd = cmd or self.DEFAULT_CMD
        self.callback = callback
        self.proc = None
        self.input = None
        self.output = None
        self.row = self.col = 0
        self.mode = 'n'
        self.visual = (0, 0)
        self.visual_selected = False

        self.__serve()
        self.__spawn()
        self.tty = None

    def __spawn(self):
        master, slave = pty.openpty()
        devnul = open(os.devnull, 'r')
        cmd = self.cmd + ('-nb::{}'.format(self.port),)
        self.proc = subprocess.Popen(
            cmd, stdin=slave, stdout=slave,
            stderr=devnul, close_fds=True)
        self.output = os.fdopen(master, 'rb')
        self.input = os.fdopen(master, 'wb')

        def pump():
            self.tty = v = VT100(self.COLS, self.ROWS)
            while True:
                b = self.output.read(1)
                old = v.dump()
                v.append(b)
                new = v.dump()
                if new == old:
                    continue
                self.status, self.cmdline = [
                    s.strip() for s in new.rsplit('\n')[-3:-1]
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
                        edit.erase(sublime.Region(0, self.monitor.size()))
                        edit.insert(0, v.dump())
                        edit.reselect(
                            lambda view: view.text_point(v.row - 1, v.col - 1))

                        def update_cursor(view, edit):
                            row, col = (self.row - 1, self.col + 1)
                            # see if it's prompting for input
                            if v.row == self.ROWS and v.col > 0:
                                char = v.buf[v.row - 1][0]
                                if char in ':/':
                                    row, col = (v.row - 1, v.col - 1)
                            pos = view.text_point(row, col)
                            sel = sublime.Region(pos, pos)
                            view.add_regions(
                                'cursor', [sel], 'comment',
                                '', sublime.DRAW_EMPTY,
                            )
                        edit.callback(update_cursor)

                if self.callback:
                    self.callback(self)
        threading.Thread(target=pump).start()

    def __serve(self):
        self.socket = VimSocket(self.view)
        self.port = self.socket.port
        self.socket.spawn()

    def send(self, b):
        # send input
        if self.input:
            self.input.write(b.encode('utf8'))
            self.input.flush()

    def press(self, key):
        b = VT100.map(key)
        self.send(b)

    def close(self):
        print('ending Vim')
        self.view.close()
        if self.monitor:
            self.monitor.close()
        self.proc.kill()
        self.socket.close()

if __name__ == '__main__':
    import time

    v = Vim()
    time.sleep(3)
    v.send('i')
    while True:
        v.send('asdfjkl ')
        time.sleep(1)
