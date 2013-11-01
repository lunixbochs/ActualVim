import sublime
import sublime_plugin

from .edit import Edit
from .view import ViewMeta
from .vim import Vim, VISUAL_MODES

try:
    v = v.close()
except (NameError, AttributeError):
    v = None


class ActualKeypress(sublime_plugin.TextCommand):
    def run(self, edit, key):
        global v
        if v:
            v.press(key)


class ActualListener(sublime_plugin.EventListener):
    def on_selection_modified_async(self, view):
        if v and view == v.view:
            m = ViewMeta.get(view)
            if not m.sel_changed():
                return

            sel = view.sel()
            if not sel:
                return

            sel = sel[0]
            def cursor(args):
                buf, lnum, col, off = [int(a) for a in args.split(' ')]
                # see if we changed selection on Sublime's side
                if v.mode in VISUAL_MODES:
                    start = v.visual
                    end = lnum, col + 1
                    region = m.visual(v.mode, start, end)[0]
                    if (sel.a, sel.b) == region:
                        return

                if off == sel.b or off > view.size():
                    return

                # selection didn't match Vim's, so let's change Vim's.
                if sel.b == sel.a:
                    if v.mode in VISUAL_MODES:
                        # v.type('{}go'.format(sel.b))
                        v.press('escape')

                    v.set_cursor(sel.b, callback=v.update_cursor)
                else:
                    if v.mode != 'n':
                        v.press('escape')
                    v.type('{}gov{}go'.format(sel.a + 1, sel.b + 1))

            v.get_cursor(cursor)

    def on_modified(self, view):
        if v and view == v.view:
            m = ViewMeta.get(view)
            m.sel_changed()

    def on_close(self, view):
        if v and view == v.view:
            v.close()


class ActualPanel:
    def __init__(self, vim, view):
        self.vim = vim
        self.view = view

    def close(self):
        self.panel.close()

    def show(self, char):
        window = self.view.window()
        self.panel = window.show_input_panel('Vim', char, self.on_done, None, self.on_cancel)
        settings = self.panel.settings()
        settings.set('actual_intercept', True)

    def on_done(self, text):
        self.vim.press('enter')
        self.vim.panel = None

    def on_cancel(self):
        self.vim.press('escape')
        self.vim.panel = None


def update(vim, dirty, moved):
    mode = vim.mode
    view = vim.view
    tty = vim.tty

    if vim.cmdline:
        view.set_status('actual', vim.cmdline)
    else:
        view.erase_status('actual')

    if tty.row == tty.rows and tty.col > 0:
        char = tty.buf[tty.row - 1][0]
        if char in ':/':
            if vim.panel:
                # we already have a panel
                panel = vim.panel.panel
                with Edit(panel) as edit:
                    edit.replace(sublime.Region(0, panel.size()), vim.cmdline)
            else:
                # vim is prompting for input
                row, col = (tty.row - 1, tty.col - 1)
                vim.panel = ActualPanel(vim, view)
                vim.panel.show(char)
            return
    elif vim.panel:
        vim.panel.close()
        vim.panel = None

    if mode in VISUAL_MODES:
        def select():
            m = ViewMeta.get(view)
            start = vim.visual
            end = (vim.row, vim.col)
            regions = m.visual(vim.mode, start, end)
            view.sel().clear()
            for r in regions:
                view.sel().add(sublime.Region(*r))

        Edit.defer(view, select)
        return
    else:
        v.update_cursor()

def modify(vim):
    pass

def plugin_loaded():
    global v

    output = sublime.active_window().new_file()
    output.set_read_only(True)
    output.set_scratch(True)
    output.set_name('Vim Monitor')
    output.settings().set('actual_intercept', True)
    output.settings().set('actual_mode', True)

    view = sublime.active_window().new_file()
    view.set_name('Vim')

    view.settings().set('actual_intercept', True)
    view.settings().set('actual_mode', True)
    v = Vim(view, monitor=output, update=update, modify=modify)
