import contextlib
import os
import queue
import sublime
import sys
import threading
import time
import traceback

from .lib import neovim
from .lib import util
from . import settings

if not '_loaded' in globals():
    NEOVIM_PATH = None
    _loaded = False

INSERT_MODES = ['i', 'R']
VISUAL_MODES = ['V', 'v', '\x16']
HALF_KEYS = ['d', 'y', 'c', '<lt>', '>', '=']
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
    print('ActualVim: using nvim binary path:', NEOVIM_PATH)

    global vim, _loaded
    if 'vim' in globals():
        new = Vim(vim.nv)
        # anything set in _setup needs to be copied over
        new.notif_cb = vim.notif_cb
        new.screen = vim.screen
        new.nvim_mode = vim.nvim_mode
        new.views = vim.views
        vim = new
    else:
        try:
            vim = Vim()
            vim._setup()

            _loaded = True
            from .view import neovim_loaded
            neovim_loaded()
            print('ActualVim: nvim started')
        except Exception:
            print('ActualVim: Error during nvim setup.')
            traceback.print_exc()
            _loaded = False
            vim = None
            del vim


class Screen:
    def __init__(self):
        self.x = 0
        self.y = 0
        self.resize(1, 1)

    def resize(self, w, h):
        self.w = w
        self.h = h
        # TODO: should resize clear?
        self.screen = [[' '] * w for i in range(h)]
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
            if not cmd:
                continue
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
        self.views = {}

        args = settings.get('neovim_args') or []
        if not isinstance(args, list):
            print('ActualVim: ignoring non-list ({}) args: {}'.format(type(args), repr(args)))
            args = []
        self.nv = neovim.attach('child', argv=[NEOVIM_PATH, '--embed', '-n'] + args)
        self._sem = threading.Semaphore(0)
        self._thread = t = threading.Thread(target=self._event_loop)
        t.daemon = True
        t.start()

        self._sem.acquire()
        self.nv.options['hidden'] = True

        # set up UI
        options = {'popupmenu_external': True}
        self.nv.ui_attach(self.width, self.height, options)

        # set up buffer read/write commands
        cmd = 'autocmd {{}} * :call rpcrequest({}, "{{}}", expand("<abuf>"), expand("<afile>"))'.format(self.nv.channel_id)
        # self.cmd(cmd.format('BufWritePre', 'write_pre'))
        self.cmd(cmd.format('BufReadCmd', 'read'))
        self.cmd(cmd.format('BufWriteCmd', 'write'))
        self.cmd(cmd.format('BufEnter', 'enter'))

        # set up autocomplete from Sublime via completefunc (ctrl-x, ctrl-u)
        # TODO: make this a setting, or at least the buf.options['completefunc'] part
        complete = r'''return rpcrequest({}, \"complete\", bufnr(\"%\"), a:findstart, a:base)'''.format(self.nv.channel_id)
        self.eval(r'''execute(":function! ActualVimComplete(findstart, base) \n {} \n endfunction")'''.format(complete))

        try:
            self.nv.request('nvim_get_mode')
            self.nvim_mode = True
        except neovim.api.NvimError:
            self.nvim_mode = False

    def _event_loop(self):
        def on_notification(method, args):
            if method == 'redraw':
                for cmd in args:
                    name, args = cmd[0], cmd[1:]
                    # TODO: allow subscribing to these
                    if name == 'bell' and self.av:
                        self.av.on_bell()
                    elif name in ('popupmenu_show', 'popupmenu_hide', 'popupmenu_select'):
                        self.av.on_popupmenu(name, args)
                vim.screen.redraw(args)
            if vim.notif_cb:
                vim.notif_cb(method, args)

        def on_request(method, args):
            # TODO: what if I need to handle requests that don't start with bufid?
            bufid = int(args.pop(0))
            av = self.views.get(bufid)
            if not av:
                # TODO: this spews on first "enter"
                print('ActualVim: request "{}" failed: buf:{} has no view'.format(method, bufid))
                return
            if method == 'write':
                # TODO: filename arg?
                return av.on_write()
            elif method == 'read':
                # TODO: filename arg?
                # TODO: pivot view?
                pass
            elif method == 'enter':
                # TODO: focus view?
                pass
            elif method == 'complete':
                return av.on_complete(args[0], args[1])

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
    def buf_new(self, view):
        self.cmd('enew')
        buf = max((b.number, b) for b in self.nv.buffers)[1]
        buf.options['buftype'] = 'acwrite'
        for k, v in settings.get('bufopts').items():
            buf.options[k] = v
        self.views[buf.number] = view
        return buf

    def buf_close(self, buf):
        self.views.pop(buf.number, None)
        self.cmd('bw! {:d}'.format(buf.number))

    def buf_tick(self, buf):
        return self.eval('getbufvar({}, "changedtick")'.format(buf.number))

    # neovim 'readiness' methods
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

        ret = self.nv.input(key)
        if key in HALF_KEYS and was_ready and self.mode_last == 'n':
            ready = False
        elif self.mode_last in INSERT_MODES and key in SIMPLE_KEYS:
            # TODO: this is an assumption and could break in custom setups
            ready = True
        else:
            if self.nvim_mode:
                _, blocked = self.nv.request('nvim_get_mode')
                ready = not blocked
            else:
                ready = self._ask_async_ready()
        if ready:
            self.ready.release()
        return ret, ready

    @property
    def status(self):
        # TODO: use nvim_atomic? we need to get sel, buf, mode, everything at once if possible
        ev = '&modified, &expandtab, &ts, line("."), col("."), line("v"), col("v"), mode()'

        data = self.eval('[' + ev + ']')

        # we always need the mode to calculate selection anyway
        self.mode_dirty = False
        self.mode_last = data.pop()

        # TODO: update these like mode_dirty but with a better @cached_property type
        modified, expandtab, ts, r1, c1, r2, c2 = data
        return modified, expandtab, ts, (r2 - 1, c2 - 1), (r1 - 1, c1 - 1)

    def setpos(self, expr, line, col):
        return self.eval('setpos("{}", [0, {:d}, {:d}])'.format(expr, line, col))

    def select(self, a, b=None, mode='v'):
        if b is None:
            if self.mode in VISUAL_MODES:
                self.nv.input('<esc>')
                self.mode_dirty = True
            self.eval('cursor({:d}, {:d}, {:d})'.format(a[0], a[1], a[1]))
        else:
            special = mode.startswith('<c-')
            if self.mode in VISUAL_MODES:
                self.nv.input('<esc>')

            self.setpos('.', *a)
            if special:
                self.cmd('exe "normal! \\{}"'.format(mode))
            else:
                self.cmd('normal! {}'.format(mode))
            self.mode_dirty = True
            self.setpos('.', *b)

    def resize(self, width, height):
        w, h = int(width), int(height)
        if w and h and w != self.width and h != self.height and self.check_ready():
            self.width, self.height = w, h
            self.nv.ui_try_resize(w, h)

    @property
    def mode(self):
        if self.mode_dirty:
            self.mode_last = self.eval('mode()')
        return self.mode_last

    @property
    def status_line(self):
        return self.screen[-1].strip()
