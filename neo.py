import contextlib
import os
import queue
import sublime
import sys
import threading
import time

from .lib import neovim
from .lib import util
from . import settings

if not '_loaded' in globals():
    NEOVIM_PATH = None
    _loaded = False

INSERT_MODES = ['i', 'R']
VISUAL_MODES = ['V', 'v', '\x16']
HALF_KEYS = ['d', 'y', 'c', '<lt>', '>']
SIMPLE_KEYS = [chr(c) for c in range(0x20, 0x7f)] + [
    '<bs>', '<lt>',
    '<left>', '<down>', '<right>', '<up>',
    '<del>', '<enter>', '<tab>'
]
MODES = {
    'n': 'normal',
    'c': 'command',
    # ex mode goes and stays "not ready"
    # think I need UI hook to support it for now
    'i':    'insert',
    'R':    'replace',

    'v':    'visual',
    'V':    'visual line',
    '\x16': 'visual block',
    # TODO: select, vreplace?
}

def plugin_loaded():
    global NEOVIM_PATH
    settings.load()

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

        self.mode_last = None
        self.mode_dirty = True
        self.av = None
        self.width = 80
        self.height = 24

    def _setup(self):
        self.notif_cb = None
        self.screen = Screen()

        self.nv = neovim.attach('child', argv=[NEOVIM_PATH, '--embed'])
        self._sem = threading.Semaphore(0)
        self._thread = t = threading.Thread(target=self._event_loop)
        t.daemon = True
        t.start()

        self._sem.acquire()
        self.cmd('set noswapfile')
        self.cmd('set hidden')
        self.nv.ui_attach(self.width, self.height, True)

    def _event_loop(self):
        def on_notification(method, updates):
            if method == 'redraw':
                for cmd in updates:
                    name, args = cmd[0], cmd[1:]
                    if name == 'bell' and self.av:
                        self.av.bell()

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

    def activate(self, av):
        if self.av != av:
            self.av = av
            self.cmd('b! {:d}'.format(av.buf.number))
            return True
        return False

    # buffer methods
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
                self.nv.request('vim_input', cb=async2)

        def async2(*a):
            with cv:
                state['done'] = True
                cv.notify()

        self.nv.request('vim_eval', '1', cb=eval_cb)
        self.nv.request('vim_input', cb=async1)
        with cv:
            cv.wait_for(lambda: state['done'], timeout=1)
        return state['ret']

    def press(self, key):
        self.mode_dirty = True
        was_ready = self.ready.acquire(False)

        ret = self.nv.input(key)
        if key in HALF_KEYS and was_ready and self.mode_last == 'n':
            ready = False
        elif self.mode_last in INSERT_MODES and key in SIMPLE_KEYS:
            # TODO: this is an assumption and could break in custom setups
            ready = True
        else:
            ready = self._ask_async_ready()
        if ready:
            self.ready.release()

        return ret, ready

    @property
    def sel(self):
        # TODO: use nvim_atomic? we need to get sel, buf, mode, everything at once if possible
        ev = 'line("."), col("."), line("v"), col("v")'
        # we always need the mode to calculate selection anyway
        if self.mode_dirty:
            ev += ', mode()'
        data = self.eval('[' + ev + ']')

        if self.mode_dirty:
            self.mode_dirty = False
            self.mode_last = data.pop()

        r1, c1, r2, c2 = data
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

    def resize(self, width, height):
        w, h = int(width), int(height)
        if w != self.width and h != self.height and self.check_ready():
            self.nv.ui_try_resize(w, h)

    @property
    def mode(self):
        if self.mode_dirty:
            self.mode_last = self.eval('mode()')
        return self.mode_last

    @property
    def status_line(self):
        return self.screen[-1].strip()
