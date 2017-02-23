import json
import os
import sublime
import sublime_plugin

from .view import ActualVim
from .edit import Edit

DEFAULT_SETTINGS = {
    'enabled': True,
    'neovim_path': '',
}


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
    def on_open_settings(self, view):
        if view.file_name() and os.path.basename(view.file_name()) == 'ActualVim.sublime-settings' and view.size() < 2:
            with Edit(view) as edit:
                j = json.dumps(DEFAULT_SETTINGS, indent=4, sort_keys=True)
                j = j.replace(' \n', '\n')
                edit.replace(sublime.Region(0, view.size()), j)
            view.run_command('save')
            view.sel().clear()
            view.sel().add(sublime.Region(0, 0))

    def on_new(self, view):
        self.on_open_settings(view)

    def on_load(self, view):
        self.on_open_settings(view)

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
