import sublime
import sublime_plugin

from .view import ActualVim


class ActualKeypress(sublime_plugin.TextCommand):
    def run(self, edit, key):
        v = ActualVim.get(self.view, exact=False, create=False)
        if v and v.actual:
            v.press(key)


class ActualViewListener(sublime_plugin.ViewEventListener):
    @staticmethod
    def is_applicable(settings):
        return True
        return all((
            not settings.get('scratch'),
        ))

    def __init__(self, view):
        self.view = view
        self.v = ActualVim.get(view)

    def on_new(self):
        # vim buffer only gets created when we call activate()
        # to prevent goto anything / other ephemeral views from spewing buffers
        self.v.activate()

    def on_load(self):
        self.v.activate()

    def on_activated(self):
        self.v.activate()

    # def on_deactivated_async(self):
    #    pass

    # if we don't do this async, bad selections never display, which reduces flickering
    def on_selection_modified(self):
        self.v.sel_to_vim()

    def on_modified(self):
        self.v.sync_to_vim()

    def on_close(self):
        self.v.close(view)

    def on_post_save_async(self):
        self.v.set_path(view.file_name())


class ActualGlobalListener(sublime_plugin.EventListener):
    def on_pre_close(self, view):
        v = ActualVim.get(view, create=False)
        if v:
            v.close()
