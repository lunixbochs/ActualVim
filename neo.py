import contextlib

from .lib import neovim
from .lib import util

NEOVIM_PATH = util.which('nvim')
if not NEOVIM_PATH:
    raise Exception('cannot find nvim executable')


class Vim:
    def __init__(self, nv=None):
        self.nv = nv
        if nv is None:
            self.nv = neovim.attach('child', argv=[NEOVIM_PATH, '--embed'])
            self.cmd('noswapfile')

    def cmd(self, *args, **kwargs):
        return self.nv.command_output(*args, **kwargs)

    def eval(self, *cmds):
        if len(cmds) == 1:
            return self.nv.eval(cmds[0])
        else:
            return [self.nv.eval(cmd) for cmd in cmds]

    # buffer methods
    def buf_activate(self, buf):
        self.cmd('b! {:d}'.format(buf.number))

    def buf_new(self):
        self.cmd('new')
        return max((b.number, b) for b in self.nv.buffers)[1]

    def buf_close(self, buf):
        self.cmd('bd! {:d}'.format(buf.number))

    # ???
    def press(self, key):
        self.nv.input(key)

    @property
    def sel(self):
        m, r1, c1, r2, c2 = self.eval('mode()', 'line(".")', 'col(".")', 'line("v")', 'col("v")')
        return m, (r2, c2), (r1, c1)

try:
    vim = Vim(vim.nv)
except NameError:
    vim = Vim()
