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
from .screen import Screen

if not '_loaded' in globals():
    NEOVIM_PATH = None
    _loaded = False
    _loading = False

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

    global vim, _loaded, _loading
    try:
        start = time.time()
        vim = Vim()
        _loading = True
        vim._setup()

        _loaded = True
        _loading = False
        from .view import neovim_loaded
        neovim_loaded()
        print('ActualVim: nvim started in {:.2f}ms'.format((time.time() - start) * 1000))
    except Exception:
        print('ActualVim: Error during nvim setup.')
        traceback.print_exc()
        _loaded = False
        _loading = False
        vim = None
        del vim

def plugin_unloaded():
    from .view import neovim_unloaded
    neovim_unloaded()

    global vim, _loaded
    if _loaded:
        vim.nv.command('qa!', async=True)
        vim = None
        _loaded = False


class Vim:
    def __init__(self, nv=None):
        self.nv = nv
        self.ready = threading.Lock()

        self.status_lock = threading.Lock()
        self.status_last = {}
        self.status_dirty = True

        self.av = None
        self.width = 80
        self.height = 24

    def _setup(self):
        self.screen = Screen()
        self.views = {}

        args = settings.get('neovim_args') or []
        if not isinstance(args, list):
            print('ActualVim: ignoring non-list ({}) args: {}'.format(type(args), repr(args)))
            args = []
        self.nv = neovim.attach('child', argv=[NEOVIM_PATH, '--embed', '-n'] + args)

        # toss in <FocusGained> in case there's a blocking prompt on startup (like vimrc errors)
        self.nv.input('<FocusGained>')
        messages = self.nv.eval('execute("messages")').strip()
        if messages:
            print('ActualVim: nvim startup error:')
            print('-'*20)
            print(messages)
            print('-'*20)
            sublime.active_window().run_command('show_panel', {'panel': 'console'})

        self._sem = threading.Semaphore(0)
        self._thread = t = threading.Thread(target=self._event_loop)
        t.daemon = True
        t.start()

        self._sem.acquire()

        # set up UI (before anything else so we can see errors)
        options = {'popupmenu_external': True, 'rgb': True}
        self.nv.ui_attach(self.width, self.height, options)

        # hidden buffers allow us to multiplex them
        self.nv.options['hidden'] = True

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

        self.nvim_mode = False
        try:
            res = self.nv.request('nvim_get_mode')
            if isinstance(res, dict):
                self.nvim_mode = True
        except neovim.api.NvimError:
            pass

    def _event_loop(self):
        def on_notification(method, data):
            # if vim exits, we might get a notification on the way out
            if not (_loaded or _loading):
                return

            if method == 'redraw':
                for cmd in data:
                    name, args = cmd[0], cmd[1:]
                    # TODO: allow subscribing to these
                    if name == 'bell' and self.av:
                        self.av.on_bell()
                    elif name in ('popupmenu_show', 'popupmenu_hide', 'popupmenu_select'):
                        self.av.on_popupmenu(name, args)
                vim.screen.redraw(data)
                if self.av:
                    self.av.on_redraw(data, vim.screen)

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

    def eval(self, *cmds, **kwargs):
        if len(cmds) != 1:
            cmd = '[' + (', '.join(cmds)) + ']'
        else:
            cmd = cmds[0]
        return self.nv.eval(cmd, **kwargs)

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
            self.nv.input('<c-\\><c-n>')

    def press(self, key, onready=None):
        self.status_dirty = True
        mode_last = self.status_last.get('mode')
        was_ready = self.ready.acquire(False)

        ret = self.nv.input(key)
        if key in HALF_KEYS and was_ready and mode_last == 'n':
            ready = False
        else:
            if self.nvim_mode:
                res = self.nv.request('nvim_get_mode') or {}
                ready = not res.get('blocking', True)
            else:
                ready = False
                def tmp():
                    # need to acquire/release so ready lock doesn't get stuck
                    self.ready.acquire(False)
                    self.ready.release()
                    onready()
                self.status(cb=tmp)

        if ready:
            self.ready.release()
        return ret, ready

    def status(self, update=True, force=False, cb=None):
        # TODO: use nvim_atomic? we need to get sel, buf, mode, everything at once if possible
        with self.status_lock:
            if self.status_dirty and update or force:
                items = {
                    'mode': 'mode()',
                    'modified': '&modified',
                    'expandtab': '&expandtab',
                    'ts': '&ts',
                    'changedtick': 'getbufvar(bufnr("%"), "changedtick")',

                    'cline': 'line(".") - 1',
                    'ccol': 'col(".") - 1',
                    'vline': 'line("v") - 1',
                    'vcol': 'col("v") - 1',

                    'wview': 'winsaveview()',
                    'wwidth': 'winwidth(winnr())',
                    'wheight': 'winheight(winnr())',

                    'screenrow': 'screenrow()',
                    'screencol': 'screencol()',
                }
                expr = '[' + (', '.join(items.values())) + ']'
                def update(*a):
                    self.status_last = dict(zip(items.keys(), a[-1]))
                    self.status_dirty = False
                    if cb:
                        # callbacks aren't decoded automatically
                        self.status_last['mode'] = self.status_last['mode'].decode('utf8')
                        cb()
                if cb:
                    self.eval(expr, cb=update)
                else:
                    update(self.eval(expr))
            return self.status_last

    def setpos(self, expr, line, col):
        return self.eval('setpos("{}", [0, {:d}, {:d}])'.format(expr, line, col))

    def select(self, a, b=None, mode='v'):
        if b is None:
            if self.mode in VISUAL_MODES:
                self.nv.input('<c-\\><c-n>')
            self.status_dirty = True
            self.eval('cursor({:d}, {:d}, {:d})'.format(a[0], a[1], a[1]))
        else:
            special = mode.startswith('<c-')
            if self.mode in VISUAL_MODES:
                self.nv.input('<c-\\><c-n>')
            self.status_dirty = True

            self.setpos('.', *a)
            if special:
                self.cmd('exe "normal! \\{}"'.format(mode))
            else:
                self.cmd('normal! {}'.format(mode))
            self.setpos('.', *b)

    def resize(self, width, height):
        w, h = int(width), int(height)
        if w and h and w != self.width and h != self.height and self.check_ready():
            self.width, self.height = w, h
            self.nv.ui_try_resize(w, h)

    @property
    def mode(self):
        return self.status()['mode']

    @property
    def status_line(self):
        return self.screen[-1].strip()
