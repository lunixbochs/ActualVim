import sublime
import sublime_plugin

from .edit import Edit
from .view import ViewMeta, copy_sel
from .vim import Vim

try:
    v = v.close()
except (NameError, AttributeError):
    pass


class ActualKeypress(sublime_plugin.TextCommand):
    def run(self, edit, key):
        global v
        if v:
            v.press(key)


class ActualListener(sublime_plugin.EventListener):
    def on_selection_modified_async(self, view):
        if view == v.view:
            m = ViewMeta.get(view)
            if v.mode in ('V', 'v', '^V'):
                return

            if not m.sel_changed():
                return

            sel = view.sel()
            if not sel:
                return

            sel = sel[0].b
            def cursor(args):
                buf, lnum, col, off = [int(a) for a in args.split(' ')]
                if off != sel and off < view.size():
                    # looks like we changed selection on Sublime's side
                    v.set_cursor(sel, callback=v.update_cursor)
            v.get_cursor(cursor)

    def on_modified(self, view):
        if view == v.view:
            m = ViewMeta.get(view)
            m.sel_changed()

    def on_close(self, view):
        if view == v.view:
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

    if mode in ('V', 'v', '^V'):
        def select():
            vr, vc = vim.visual
            sel = view.sel()
            sel.clear()

            left = min(vc, vim.col) - 1
            right = max(vc, vim.col)
            top = min(vr, vim.row) - 1
            bot = max(vr, vim.row) - 1

            start = view.text_point(vr - 1, vc - 1)
            end = view.text_point(vim.row - 1, vim.col - 1)
            if mode == 'V':
                # visual line mode
                if start == end:
                    pos = view.line(start)
                    start, end = pos.a, pos.b
                elif start > end:
                    start = view.line(start).b
                    end = view.line(end).a
                else:
                    start = view.line(start).a
                    end = view.line(end).b
                sel.add(sublime.Region(start, end))
            elif mode == 'v':
                # visual mode
                sel.add(sublime.Region(start, end))
            elif mode == '^V':
                # visual block mode
                for i in range(top, bot + 1):
                    line = view.line(view.text_point(i, 0))
                    _, end = view.rowcol(line.b)
                    if left <= end:
                        a = view.text_point(i, left)
                        b = view.text_point(i, right)
                        sel.add(sublime.Region(a, b))

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
