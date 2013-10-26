import sublime
import sublime_plugin

from .edit import Edit
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
    def on_selection_modified(self, view):
        pass # print(view.id())

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


def update(vim):
    mode = vim.mode
    view = vim.view
    tty = vim.tty
    if mode in 'iR':
        return

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

            for i in range(top, bot + 1):
                line = view.line(view.text_point(i, 0))
                if mode == 'V':
                    # visual line mode
                    sel.add(sublime.Region(line.a, line.b))
                else:
                    _, end = view.rowcol(line.b)
                    if left <= end and right <= end:
                        a = view.text_point(i, left)
                        b = view.text_point(i, right)
                        sel.add(sublime.Region(a, b))

        Edit.defer(view, select)
        return
    else:
        def select():
            pos = view.text_point(vim.row-1, vim.col-1)
            sel = view.sel()
            sel.clear()
            sel.add(sublime.Region(pos, pos))

        Edit.defer(view, select)

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
    v = Vim(view, monitor=output, callback=update)
