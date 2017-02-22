import contextlib

from .lib import neovim
from .lib import util

NEOVIM_PATH = util.which('nvim')
if not NEOVIM_PATH:
    raise Exception('cannot find nvim executable')

INSERT_MODES = ['i']
VISUAL_MODES = ['V', 'v', '\x16']


class Vim:
    def __init__(self, nv=None):
        self.nv = nv
        if nv is None:
            self.nv = neovim.attach('child', argv=[NEOVIM_PATH, '--embed'])
            self.cmd('set noswapfile')
            self.cmd('set hidden')

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

    def press(self, key):
        self.nv.feedkeys(self.nv.replace_termcodes(key))

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
                # TODO: map key?
                self.press('\033')
            self.eval('cursor({:d}, {:d}, {:d})'.format(a[0], a[1], a[1]))
        else:
            b = add1(b)

            self.press('\033')
            self.setpos('.', *a)
            self.cmd('normal! v')
            # fix right hand side alignment
            if a < b:
                b = [b[0], b[1] - 1]
            self.setpos('.', *b)

    @property
    def mode(self):
        return self.eval('mode()')

try:
    vim = Vim(vim.nv)
except NameError:
    vim = Vim()
