import sublime
import sublime_plugin

from .edit import Edit
from .view import ViewMeta
from .vim import Vim, VISUAL_MODES


class ActualVim(ViewMeta):
    def __init__(self, view):
        super().__init__(view)
        if view.settings().get('actual_monitor'):
            return

        view.settings().set('actual_intercept', True)
        view.settings().set('actual_mode', True)
        self.vim = vim = Vim(view, update=self.update, modify=self.modify)
        vim.insert(0, view.substr(sublime.Region(0, view.size())))
        vim.init_done()
        # view.set_read_only(False)

        self.output = None

    @property
    def actual(self):
        return self.view and self.view.settings().get('actual_mode')

    def monitor(self):
        if self.output:
            return

        self.output = output = sublime.active_window().new_file()
        ActualVim.views[output.id()] = self

        output.settings().set('actual_monitor', True)
        output.set_read_only(True)
        output.set_scratch(True)
        output.set_name('(tty)')
        output.settings().set('actual_intercept', True)
        output.settings().set('actual_mode', True)
        with Edit(output) as edit:
            edit.insert(0, self.vim.tty.dump())
        self.vim.monitor = output

    def update(self, vim, dirty, moved):
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
            vim.update_cursor()

    def modify(self, vim):
        pass

    def close(self, view):
        if self.output:
            self.output.close()
            self.output = None

        if view == self.view:
            self.view.close()
            self.vim.close()

class ActualKeypress(sublime_plugin.TextCommand):
    def run(self, edit, key):
        v = ActualVim.get(self.view)
        if v and v.actual:
            v.vim.press(key)


class ActualListener(sublime_plugin.EventListener):
    def on_new_async(self, view):
        ActualVim.get(view)

    def on_load(self, view):
        ActualVim.get(view)

    def on_selection_modified_async(self, view):
        v = ActualVim.get(view, create=False)
        if v and v.actual:
            m = ViewMeta.get(view)
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
                    region = m.visual(vim.mode, start, end)[0]
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
        v = ActualVim.get(view, create=False)
        if v:
            v.sel_changed()

    def on_close(self, view):
        v = ActualVim.get(view, create=False)
        if v:
            v.close(view)


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
