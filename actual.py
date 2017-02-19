import sublime
import sublime_plugin

from .edit import Edit
from .view import ViewMeta

from .lib import neovim

NEOVIM_PATH = '/usr/local/bin/nvim'


KEYMAP = {
    'backspace': '\b',
    'enter': '\n',
    'escape': '\033',
    'space': ' ',
    'tab': '\t',
    'up': '\033[A',
    'down': '\033[B',
    'right': '\033[C',
    'left': '\033[D',
}

def keymap(key):
    if '+' in key and key != '+':
        mods, key = key.rsplit('+', 1)
        mods = mods.split('+')
        if mods == ['ctrl']:
            b = ord(key)
            if b >= 63 and b < 96:
                return chr((b - 64) % 128)

    return KEYMAP.get(key, key)

class ActualVim(ViewMeta):
    def __init__(self, view):
        super().__init__(view)
        if view.settings().get('actual_proxy'):
            return

        view.settings().set('actual_intercept', True)
        view.settings().set('actual_mode', True)
        self.vim = vim = neovim.attach('child', argv=[NEOVIM_PATH, '--embed'])
        # vim.set_path(view.file_name())
        # vim.insert(0, view.substr(sublime.Region(0, view.size())))
        # vim.init_done()
        # view.set_read_only(False)

        self.output = None

    @property
    def actual(self):
        return self.view and self.view.settings().get('actual_mode')

    def close(self, view):
        if self.output:
            self.output.close()
            self.output = None

        if view == self.view:
            self.view.close()
            self.vim.close()

    def set_path(self, path):
        return
        self.vim.set_path(path)

class ActualKeypress(sublime_plugin.TextCommand):
    def run(self, edit, key):
        v = ActualVim.get(self.view, exact=False)
        if v and v.actual:
            # TODO: move these to better places
            key = keymap(key)
            v.vim.input(key)
            buf = '\n'.join(v.vim.current.buffer[:])
            with Edit(self.view) as edit:
                edit.replace(sublime.Region(0, self.view.size()), buf)


class ActualListener(sublime_plugin.EventListener):
    def on_new_async(self, view):
        ActualVim.get(view)

    def on_load(self, view):
        ActualVim.get(view)

    def on_selection_modified_async(self, view):
        v = ActualVim.get(view, create=False)
        return
        if v and v.actual:
            if not v.sel_changed():
                return

            sel = view.sel()
            if not sel:
                return

            vim = v.vim
            sel = sel[0]
            def cursor(args):
                buf, lnum, col, off = [int(a) for a in args.split(' ')]
                # see if we changed selection on Sublime's side
                if vim.mode in VISUAL_MODES:
                    start = vim.visual
                    end = lnum, col + 1
                    region = v.visual(vim.mode, start, end)[0]
                    if (sel.a, sel.b) == region:
                        return

                if off == sel.b or off > view.size():
                    return

                # selection didn't match Vim's, so let's change Vim's.
                if sel.b == sel.a:
                    if vim.mode in VISUAL_MODES:
                        # vim.type('{}go'.format(sel.b))
                        vim.press('escape')

                    vim.set_cursor(sel.b, callback=vim.update_cursor)
                else:
                    # this is currently broken
                    return
                    if vim.mode != 'n':
                        vim.press('escape')
                    a, b = sel.a, sel.b
                    if b > a:
                        a += 1
                    else:
                        b += 1
                    vim.type('{}gov{}go'.format(a, b))

            vim.get_cursor(cursor)

    def on_modified(self, view):
        return
        v = ActualVim.get(view, create=False)
        if v:
            v.sel_changed()

    def on_close(self, view):
        v = ActualVim.get(view, create=False)
        if v:
            v.close(view)

    def on_post_save_async(self, view):
        v = ActualVim.get(view, create=False)
        if v:
            v.set_path(view.file_name())

class ActualPanel:
    def __init__(self, actual):
        self.actual = actual
        self.vim = actual.vim
        self.view = actual.view
        self.panel = None

    def close(self):
        if self.panel:
            self.panel.close()

    def show(self, char):
        window = self.view.window()
        self.panel = window.show_input_panel('Vim', char, self.on_done, None, self.on_cancel)
        settings = self.panel.settings()
        settings.set('actual_intercept', True)
        settings.set('actual_proxy', self.view.id())
        ActualVim.views[self.panel.id()] = self.actual

    def on_done(self, text):
        self.vim.press('enter')
        self.vim.panel = None

    def on_cancel(self):
        self.vim.press('escape')
        self.vim.panel = None
