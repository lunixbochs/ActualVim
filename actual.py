import sublime
import sublime_plugin

from .edit import Edit
from .vim import Vim

try:
    v = v.close()
except NameError:
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


def update(vim):
    mode = vim.mode
    view = vim.view
    if mode in 'iR':
        return

    if mode in 'Vv\x16':
        def select():
            vr, vc = vim.visual
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
            sel = view.sel()
            sel.clear()
            sel.add(sublime.Region(start, end))

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

    view = sublime.active_window().new_file()
    view.settings().set('actual_intercept', True)
    view.settings().set('actual_mode', True)
    v = Vim(view, callback=update)
