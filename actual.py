import sublime
import sublime_plugin

from .view import ActualVim


class ActualKeypress(sublime_plugin.TextCommand):
    def run(self, edit, key):
        v = ActualVim.get(self.view, exact=False)
        if v and v.actual:
            v.press(key)


class ActualListener(sublime_plugin.EventListener):
    def on_new_async(self, view):
        ActualVim.get(view)

    def on_load(self, view):
        ActualVim.get(view)

    def on_selection_modified_async(self, view):
        v = ActualVim.get(view, create=False)
        if v:
            pass

    def on_modified(self, view):
        v = ActualVim.get(view, create=False)
        if v:
            pass

    def on_close(self, view):
        v = ActualVim.get(view, create=False)
        if v:
            v.close(view)

    def on_post_save_async(self, view):
        v = ActualVim.get(view, create=False)
        if v:
            v.set_path(view.file_name())
