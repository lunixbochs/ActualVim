from .actual import ActualVim
import sublime_plugin


class actual_monitor(sublime_plugin.WindowCommand):
    @property
    def view(self):
        return self.window.active_view()

    def run(self):
        v = ActualVim.get(self.view)
        if v and v.actual:
            v.monitor()

    def is_enabled(self):
        return self.view.settings().get('actual_mode')
