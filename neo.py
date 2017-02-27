import contextlib
import os
import queue
import sublime
import sys
import threading
import time

from .lib import neovim
from .lib import util

NEOVIM_PATH = None
_loaded = False

def plugin_loaded():
    global NEOVIM_PATH

    NEOVIM_PATH = sublime.load_settings('ActualVim.sublime-settings').get('neovim_path')
    if not NEOVIM_PATH:
        NEOVIM_PATH = util.which('nvim')

    if sys.platform == 'win32':
        if not NEOVIM_PATH:
            candidates = [
                r'C:\Program Files\Neovim',
                r'C:\Program Files (x86)\Neovim',
                r'C:\Neovim',
            ]
            for c in candidates:
                path = os.path.join(c, r'bin\nvim.exe')
                if os.path.exists(path):
                    NEOVIM_PATH = path
                    break
        elif os.path.isdir(NEOVIM_PATH):
            for c in [r'bin\nvim.exe', 'nvim.exe']:
                path = os.path.join(NEOVIM_PATH, c)
                if os.path.exists(path):
                    NEOVIM_PATH = path
                    break
            else:
                NEOVIM_PATH = None

    if not NEOVIM_PATH:
        raise Exception('cannot find nvim executable')

    global vim, _loaded
    if 'vim' in globals():
        new = Vim(vim.nv)
        new.notif_cb = vim.notif_cb
        new.screen = vim.screen
        vim = new
    else:
        vim = Vim()
        vim._setup()

        _loaded = True
        from .view import neovim_loaded
        neovim_loaded()


INSERT_MODES = ['i', 'R']
VISUAL_MODES = ['V', 'v', '\x16']

class Screen:
    def __init__(self):
        self.x = 0
        self.y = 0
        self.resize(1, 1)

    def resize(self, w, h):
        self.w = w
        self.h = h
        # TODO: should resize clear?
        self.screen = [[''] * w for i in range(h)]
        self.scroll_region = [0, self.h, 0, self.w]

    def clear(self):
        self.resize(self.w, self.h)

    def scroll(self, dy):
        ya, yb = self.scroll_region[0:2]
        xa, xb = self.scroll_region[2:4]
        yi = (ya, yb)
        if dy < 0:
            yi = (yb, ya - 1)

        for y in range(yi[0], yi[1], int(dy / abs(dy))):
            if ya <= y + dy < yb:
                self.screen[y][xa:xb] = self.screen[y + dy][xa:xb]
            else:
                self.screen[y][xa:xb] = [' '] * (xb - xa)

    def redraw(self, updates):
        blacklist = [
            'mode_change',
            'bell', 'mouse_on', 'highlight_set',
            'update_fb', 'update_bg', 'update_sp', 'clear',
        ]
        for cmd in updates:
            name, args = cmd[0], cmd[1:]
            if name == 'cursor_goto':
                self.y, self.x = args[0]
            elif name == 'eol_clear':
                self.screen[self.y][self.x:] = [' '] * (self.w - self.x)
            elif name == 'put':
                for cs in args:
                    for c in cs:
                        self[self.x, self.y] = c
                        self.x += 1
            elif name == 'resize':
                self.resize(*args[0])
            elif name in blacklist:
                pass
            elif name == 'set_scroll_region':
                self.scroll_region = args[0]
            elif name == 'scroll':
                self.scroll(args[0][0])
            # else:
            #     print('unknown update cmd', name)
        # if updates:
        #     print(updates)
        #     self.p()

    def p(self):
        print('-' * self.w)
        print(str(self))
        print('-' * self.w)

    def __setitem__(self, xy, c):
        x, y = xy
        try:
            self.screen[y][x] = c
        except IndexError:
            pass

    def __getitem__(self, y):
        return ''.join(self.screen[y])

    def __str__(self):
        return '\n'.join([self[y] for y in range(self.h)])


class Vim:
    def __init__(self, nv=None):
        self.nv = nv
        self.ready = threading.Lock()
        if nv is None:
            self.notif_cb = None
            self.screen = Screen()

        self.mode_last = None
        self.mode_dirty = True

    def _setup(self):
        self.nv = neovim.attach('child', argv=[NEOVIM_PATH, '--embed'])
        self._sem = threading.Semaphore(0)
        self._thread = t = threading.Thread(target=self._event_loop)
        t.daemon = True
        t.start()

        self._sem.acquire()
        self.cmd('set noswapfile')
        self.cmd('set hidden')
        self.nv.ui_attach(80, 24, True)

    def _event_loop(self):
        def on_notification(method, updates):
            if method == 'redraw':
                vim.screen.redraw(updates)
            if vim.notif_cb:
                vim.notif_cb(method, updates)

        def on_request(method, args):
            raise NotImplemented

        def on_setup():
            self._sem.release()

        self.nv.run_loop(on_request, on_notification, on_setup)

    def cmd(self, *args, **kwargs):
        return self.nv.command_output(*args, **kwargs)

    def eval(self, *cmds):
        if len(cmds) == 1:
            return self.nv.eval(cmds[0])
        else:
            return [self.nv.eval(c) for c in cmds]

    # buffer methods
    def buf_activate(self, buf):
        self.cmd('b! {:d}'.format(buf.number))

    def buf_new(self):
        self.cmd('enew')
        return max((b.number, b) for b in self.nv.buffers)[1]

    def buf_close(self, buf):
        self.cmd('bw! {:d}'.format(buf.number))

    # readiness checking methods stuff
    # if you don't use check/force_ready and control your input/cmd interleaving, you'll hang all the time
    def check_ready(self):
        ready = self.ready.acquire(False)
        if ready:
            self.ready.release()
        return ready

    def force_ready(self):
        for i in range(3):
            if self.check_ready():
                break
            time.sleep(0.0001)
        else:
            self.nv.input('<esc>')

    # TODO: remove based on https://github.com/neovim/neovim/issues/6159
    def _ask_async_ready(self):
        # send a sync eval, then a series of async commands
        # if we get the eval before the async commands finish, return True
        state = {'done': False, 'ret': False, 'count': 0}
        cv = threading.Condition()

        def eval_cb(*a):
            with cv:
                state['done'] = True
                state['ret'] = True
                cv.notify()

        def async1(*a):
            with cv:
                self.nv.request('nvim_get_api_info', cb=async2)

        def async2(*a):
            with cv:
                state['done'] = True
                cv.notify()

        self.nv.request('vim_eval', '1', cb=eval_cb)
        self.nv.request('nvim_get_api_info', cb=async1)
        with cv:
            cv.wait_for(lambda: state['done'], timeout=1)
        return state['ret']

    def press(self, key):
        self.mode_dirty = True
        was_ready = self.ready.acquire(False)
        simple_key = len(key) == 1 and (0x20 <= ord(key[0]) <= 0x7e)

        ret = self.nv.input(key)
        if key in 'dyc' and was_ready and self.mode_last == 'n':
            ready = False
        elif self.mode_last in INSERT_MODES and simple_key:
            # TODO: this is an assumption and could break in custom setups
            ready = True
        else:
            ready = self._ask_async_ready()
            if ready:
                self.ready.release()

        return ret, ready

    @property
    def sel(self):
        r1, c1, r2, c2 = self.eval('line(".")', 'col(".")', 'line("v")', 'col("v")')
        return (r2 - 1, c2 - 1), (r1 - 1, c1 - 1)

    def setpos(self, expr, line, col):
        return self.eval('setpos("{}", [0, {:d}, {:d}])'.format(expr, line, col))

    def select(self, a, b=None, block=False):
        add1 = lambda x: [n + 1 for n in x]
        a = add1(a)
        if b is None:
            if self.mode in VISUAL_MODES:
                self.nv.input('<esc>')
            self.eval('cursor({:d}, {:d}, {:d})'.format(a[0], a[1], a[1]))
        else:
            b = add1(b)

            self.nv.input('<esc>')
            self.setpos('.', *a)
            self.cmd('normal! v')
            # fix right hand side alignment
            if a < b:
                b = [b[0], b[1] - 1]
            self.setpos('.', *b)

    @property
    def mode(self):
        if self.mode_dirty:
            self.mode_last = self.eval('mode()')
        return self.mode_last

    @property
    def status_line(self):
        return self.screen[-1].strip()
