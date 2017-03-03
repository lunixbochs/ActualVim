import queue
import sublime
import threading
import traceback

from . import neo
from . import settings
from .edit import Edit


def copy_sel(sel):
    if isinstance(sel, sublime.View):
        sel = sel.sel()
    return [(r.a, r.b) for r in sel]

# called by neo.py once neovim is loaded
def neovim_loaded():
    if settings.enabled():
        ActualVim.enable()

try:
    _views
except NameError:
    _views = {}


class ActualVim:
    def __init__(self, view):
        if view.settings().get('actual_proxy'):
            return

        self.busy = threading.RLock()
        self.keyq = queue.Queue()

        self.view = view
        self.last_sel = None
        self.buf = None
        self.changes = None
        self.last_size = None
        self.block = False
        self.block_hit = False

        # first scroll is buggy
        self.first_scroll = True

        # settings are marked here when applying mode-specific settings, and erased after
        self.tmpsettings = []

        # cached indentation settings
        self.indent = None

        en = settings.enabled()
        s = {
            'actual_intercept': en,
            'actual_mode': en,
            # it's most likely a buffer will start in command mode
            'inverse_caret_state': en,
        }
        for k, v in s.items():
            view.settings().set(k, v)

    @classmethod
    def get(cls, view, create=True, exact=True):
        vid = view.id()
        m = _views.get(vid)
        if not m and create:
            try:
                m = cls(view)
            except Exception:
                traceback.print_exc()
                return
            _views[vid] = m
        elif m and exact and m.view != view:
            # TODO: ...what is this solving?
            return None

        if m:
            return m

    @classmethod
    def remove(cls, view):
        _views.pop(view.id(), None)

    @classmethod
    def reload_classes(cls):
        # reload classes by creating a new blank instance without init and overlaying dicts
        for vid, view in _views.items():
            new = cls.__new__(cls)
            nd = {}
            # copy view dict first to get attrs, new second to get methods
            nd.update(view.__dict__)
            nd.update(new.__dict__)
            new.__dict__.update(nd)
            _views[vid] = new

    @classmethod
    def enable(cls, enable=True):
        for av in _views.values():
            s = av.view.settings()
            s.set('actual_intercept', enable)
            s.set('actual_mode', enable)

        # TODO: cursor isn't adjusted here, not sure why
        # (so if it's on a newline, it will stay there when caret switches)
        av = cls.get(sublime.active_window().active_view())
        if av and av.actual:
            av.activate()
            av.sel_to_vim()
            av.sel_from_vim()
        av.update_view()

    @property
    def actual(self):
        return neo._loaded and self.view and self.settings.get('actual_mode')

    def sel_changed(self):
        new_sel = copy_sel(self.view)
        changed = new_sel != self.last_sel
        self.last_sel = new_sel
        return changed

    def vim_text_point(self, row, col):
        view = self.view
        line = view.substr(view.line(view.text_point(row, 0)))
        vcol = len(line.encode('utf-8')[:col].decode('utf-8'))
        return view.text_point(row, vcol)

    def visual(self, mode, a, b):
        view = self.view
        regions = []
        sr, sc = a
        er, ec = b

        a = self.vim_text_point(sr, sc)
        b = self.vim_text_point(er, ec)

        name = neo.MODES.get(mode)
        if not name:
            print('ActualVim warning: unhandled selection mode', repr(mode))

        if name == 'visual line':
            # visual line mode
            if a > b:
                start = view.line(a).b
                end = view.line(b).a
            else:
                start = view.line(a).a
                end = view.line(b).b

            regions.append((start, end))
        elif mode == 'visual':
            # visual mode
            if a > b:
                a += 1
            else:
                b += 1
            regions.append((a, b))
        elif mode == 'visual block':
            # visual block mode
            left = min(sc, ec)
            right = max(sc, ec) + 1
            top = min(sr, er)
            bot = max(sr, er)
            end = view.text_point(top, right)

            for i in range(top, bot + 1):
                line = view.line(view.text_point(i, 0))
                _, end = view.rowcol(line.b)
                if left <= end:
                    a = view.text_point(i, left)
                    b = view.text_point(i, min(right, end))
                    regions.append((a, b))
        else:
            regions.append((a, b))

        return [sublime.Region(*r) for r in regions]

    @property
    def changed(self):
        return any((
            self.changes is None or self.changes < self.view.change_count(),
            # revert changes size without increasing change count
            self.last_size is not None and self.last_size != self.view.size(),
        ))

    def mark_changed(self, advance=0):
        self.changes = self.view.change_count() + advance
        if advance:
            self.last_size = None
        else:
            self.last_size = self.view.size()

    @property
    def settings(self):
        return self.view.settings()

    @property
    def avsettings(self):
        top = settings.get('settings', {})

        base = {}
        if not self.actual:
            combined = top.get('sublime', {})
            base['settings'] = combined
        else:
            combined = top.get('vim', {})
            modes = combined.pop('modes')
            mode = neo.vim.mode
            name = neo.MODES.get(mode)
            combined.update(modes.get(name, {}))
            if mode in neo.VISUAL_MODES:
                combined.update(modes.get('all visual', {}))
            elif mode in neo.INSERT_MODES:
                combined.update(modes.get('all insert', {}))

            base['settings'] = combined
            base['bell'] = combined.pop('bell')
        return base

    def activate(self):
        if not neo._loaded: return
        neo.vim.force_ready()
        # first activate
        if self.buf is None:
            self.buf = neo.vim.buf_new()
            self.sync_to_vim()

        if neo.vim.activate(self):
            self.status_from_vim()
            self.update_view()

    def bell(self):
        bell = self.avsettings.get('bell', {})
        duration = bell.pop('duration', None)
        if duration:
            def remove_bell():
                for name in bell.keys():
                    self.settings.erase(name)
                self.update_view()

            for k, v in bell.items():
                self.settings.set(k, v)
            sublime.set_timeout(remove_bell, int(duration * 1000))

    def update_view(self):
        combined = self.avsettings.get('settings', {})
        for k in self.tmpsettings:
            self.settings.erase(k)
        self.tmpsettings = combined.keys()

        for k, v in combined.items():
            self.settings.set(k, v)

        vp = self.view.viewport_extent()
        width, height = vp[0] / self.view.em_width(), vp[1] / self.view.line_height()
        neo.vim.resize(width, height)

        # update_view is called all the time, and asking vim for things is expensive
        # so vim's tab priority comes automatically during sel_from_vim()
        if settings.get('indent_priority') == 'sublime':
            self.settings_to_vim()

    def settings_to_vim(self):
        # only send this to vim if something changes
        indent = [self.settings.get(s) for s in ('translate_tabs_to_spaces', 'tab_size')]
        if indent != self.indent:
            self.indent = indent
            if indent[0]:
                neo.vim.cmd('set expandtab ts={ts} shiftwidth={ts} softtabstop=0 smarttab'.format(ts=indent[1]))
            else:
                neo.vim.cmd('set noexpandtab softtabstop=0')

    def settings_from_vim(self, et, ts):
        if et:
            self.settings.set('translate_tabs_to_spaces', et)
        self.settings.set('tab_size', ts)

    def sync_to_vim(self, force=False):
        if not neo._loaded: return
        if self.block:
            self.block_hit = True
            return

        if not (self.changed or force) or not self.buf:
            if self.last_size is None:
                self.last_size = self.view.size()
            return

        self.mark_changed()
        neo.vim.force_ready()
        text = self.view.substr(sublime.Region(0, self.view.size())).split('\n')
        self.buf[:] = text
        self.sel_to_vim(force)

    def sync_from_vim(self, edit=None):
        if not neo._loaded: return
        if not self.actual:
            return

        with self.busy:
            self.mark_changed(1)
            # TODO: global UI change is GROSS, do deltas if possible
            text = '\n'.join(self.buf[:])
            everything = sublime.Region(0, self.view.size())
            if self.view.substr(everything) != text:
                with Edit(self.view) as edit:
                    edit.replace(everything, text)
            self.sel_from_vim()
            self.status_from_vim()

    def sel_to_vim(self, force=False):
        if not neo._loaded: return
        if self.sel_changed():
            neo.vim.force_ready()
            # single selection for now...
            # TODO: block
            # TODO multiple select vim plugin integration
            sel = self.view.sel()[0]
            vim = neo.vim
            b = self.view.rowcol(sel.b)
            if sel.b == sel.a:
                vim.select(b)
            else:
                a = self.view.rowcol(sel.a)
                vim.select(a, b)

            self.sel_from_vim()
            self.update_view()

    def sel_from_vim(self, edit=None):
        if not neo._loaded: return
        if not self.actual:
            return

        et, ts, a, b = neo.vim.sel
        if settings.get('indent_priority') == 'vim':
            self.settings_from_vim(et, ts)
        new_sel = self.visual(neo.vim.mode, a, b)

        def select(view, edit):
            sel = view.sel()
            sel.clear()
            sel.add_all(new_sel)
            self.sel_changed()

            # defer first scroll: vis detection seems buggy during load
            if self.first_scroll:
                self.first_scroll = False
                sublime.set_timeout(self.sel_from_vim, 50)
                return

            # make sure new selection is visible
            vis = view.visible_region()
            if len(sel) == 1:
                b = sel[0].b
                lines = view.lines(vis)
                # single cursor might be at edge of screen, make sure line is fully on screen
                if not vis.contains(b) or (lines[0].contains(b) or lines[-1].contains(b)):
                    view.show(b, show_surrounds=False)
            else:
                for cur in sel:
                    if vis.contains(cur.b):
                        break
                else:
                    view.show(sel)

        if edit is None:
            Edit.defer(self.view, select)
        else:
            edit.callback(select)

    def status_from_vim(self):
        status = neo.vim.status_line
        if status:
            self.view.set_status('actual', status)
        else:
            self.view.erase_status('actual')

    def press(self, key):
        if not neo._loaded: return
        if self.buf is None:
            return

        self.keyq.put(key)
        # process the key, then all buffered keys
        with self.busy:
            key = self.keyq.get()
            _, ready = neo.vim.press(key)
            if ready:
                # TODO: trigger UI update on vim event, not here?
                # well, if we don't figure it out before returning control
                # to sublime, we get more events from sublime to figure out if we need to ignore
                self.sync_from_vim()
                # (trigger this somewhere else? vim mode change callback?)
                self.update_view()
            return ready

    def close(self):
        if neo._loaded:
            neo.vim.force_ready()
            if self.buf is not None:
                neo.vim.buf_close(self.buf)
        ActualVim.remove(self.view)

    def set_path(self, path):
        self.buf.name = path


class ActualPanel:
    def __init__(self, actual):
        self.actual = actual
        self.vim = actual.vim
        self.view = actual.view
        self.panel = None

    def close(self):
        if self.panel:
            self.panel.close()

    def show(self, char):
        window = self.view.window()
        self.panel = window.show_input_panel('Vim', char, self.on_done, None, self.on_cancel)
        s = self.panel.settings()
        s.set('actual_intercept', True)
        s.set('actual_proxy', self.view.id())
        ActualVim.views[self.panel.id()] = self.actual

    def on_done(self, text):
        self.vim.press('enter')
        self.vim.panel = None

    def on_cancel(self):
        self.vim.press('escape')
        self.vim.panel = None

ActualVim.reload_classes()
