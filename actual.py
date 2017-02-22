import sublime
import sublime_plugin

from .view import ActualVim


# TODO: use a setting?
class ActualEnable(sublime_plugin.ApplicationCommand):
    def is_enabled(self):
        return not ActualVim.enabled

    def run(self):
        ActualVim.enable()


class ActualDisable(sublime_plugin.ApplicationCommand):
    def is_enabled(self):
        return ActualVim.enabled

    def run(self):
        ActualVim.enable(False)


class ActualKeypress(sublime_plugin.TextCommand):
    def is_enabled(self):
        v = ActualVim.get(self.view, exact=False, create=False)
        return bool(v)

    def run(self, edit, key):
        v = ActualVim.get(self.view, exact=False, create=False)
        if v:
            v.press(key)


class ActualViewListener(sublime_plugin.ViewEventListener):
    @staticmethod
    def is_applicable(settings):
        return True
        return all((
            not settings.get('scratch'),
        ))

    @property
    def v(self):
        return ActualVim.get(self.view)

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

    def on_post_save_async(self):
        self.v.set_path(view.file_name())

class ActualGlobalListener(sublime_plugin.EventListener):
    def on_pre_close(self, view):
        v = ActualVim.get(view, create=False)
        if v:
            v.close()

    # block sublime -> vim copies during text commands
    # to prevent inconsistent updates
    # then force a copy afterwards
    def on_text_command(self, view, name, args):
        v = ActualVim.get(view, create=False)
        if not v:
            return

        if not name.startswith('actual_'):
            v.block = True

    def on_window_command(self, view, name, args):
        self.on_text_command(view, name, args)

    def on_post_text_command(self, view, name, args):
        v = ActualVim.get(view, create=False)
        if not v:
            return

        if v.block:
            v.block = False
            def fix():
                v.sync_to_vim(force=True)
            sublime.set_timeout(fix, 1)
            return

    def on_post_window_command(self, view, name, args):
        self.on_post_text_command(view, name, args)
