import sublime
import traceback

from . import neo
from .edit import Edit


def copy_sel(sel):
    if isinstance(sel, sublime.View):
        sel = sel.sel()
    return [(r.a, r.b) for r in sel]


try:
    _views
except NameError:
    _views = {}


class ActualVim:
    # TODO: use a setting?
    enabled = True

    def __init__(self, view):
        if view.settings().get('actual_proxy'):
            return

        self.view = view
        self.last_sel = None
        self.buf = None
        self.changes = None
        self.block = False

        s = {
            'actual_intercept': True,
            'actual_mode': True,
            # it's most likely a buffer will start in command mode
            'inverse_caret_state': True,
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
            return None

        if m:
            return m

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
        cls.enabled = enable
        for av in _views.values():
            settings = av.view.settings()
            settings.set('actual_intercept', enable)
            settings.set('actual_mode', enable)
            av.update_caret()

    @property
    def actual(self):
        return self.view and self.view.settings().get('actual_mode')

    def sel_changed(self):
        new_sel = copy_sel(self.view)
        changed = new_sel != self.last_sel
        self.last_sel = new_sel
        return changed

    def visual(self, mode, a, b):
        view = self.view
        regions = []
        sr, sc = a
        er, ec = b

        a = view.text_point(sr, sc)
        b = view.text_point(er, ec)

        if mode == 'V':
            # visual line mode
            if a > b:
                start = view.line(a).b
                end = view.line(b).a
            else:
                start = view.line(a).a
                end = view.line(b).b

            regions.append((start, end))
        elif mode == 'v':
            # visual mode
            if a > b:
                a += 1
            else:
                b += 1
            regions.append((a, b))
        elif mode == '\x16':
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
        return self.changes is None or self.changes < self.view.change_count()

    def activate(self):
        # first activate
        if self.buf is None:
            self.buf = neo.vim.buf_new()
            self.sync_to_vim()

        neo.vim.buf_activate(self.buf)
        self.status_from_vim()

    def update_caret(self):
        wide = False
        if self.actual:
            mode = neo.vim.mode
            wide = (mode not in neo.INSERT_MODES + neo.VISUAL_MODES)
        self.view.settings().set('inverse_caret_state', wide)

    def sync_to_vim(self, force=False):
        if self.block or not (self.changed or force):
            return

        text = self.view.substr(sublime.Region(0, self.view.size())).split('\n')
        self.buf[:] = text
        self.sel_to_vim(force)
        self.changes = self.view.change_count()

    def sync_from_vim(self, edit=None):
        if not self.actual:
            return
        # TODO: global UI change is GROSS, do deltas if possible
        text = '\n'.join(self.buf[:])
        everything = sublime.Region(0, self.view.size())
        if self.view.substr(everything) != text:
            with Edit(self.view) as edit:
                edit.replace(everything, text)
        self.sel_from_vim()
        self.changes = self.view.change_count()
        self.status_from_vim()

    def sel_to_vim(self, force=False):
        # defensive, could affect perf
        self.activate()

        if self.sel_changed():
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
            self.update_caret()

    def sel_from_vim(self, edit=None):
        if not self.actual:
            return

        a, b = neo.vim.sel
        new_sel = self.visual(neo.vim.mode, a, b)

        def select():
            sel = self.view.sel()
            sel.clear()
            sel.add_all(new_sel)
            self.sel_changed()

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
        # TODO: can we ever reach here without being the active buffer?
        # defensive, could affect perf
        self.activate()
        if self.buf is None:
            return

        neo.vim.press(key)
        # TODO: trigger UI update on vim event, not here
        self.sync_from_vim()

        # (trigger this somewhere else? vim mode change callback?)
        self.update_caret()

    def close(self):
        if self.buf is not None:
            neo.vim.buf_close(self.buf)

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
        settings = self.panel.settings()
        settings.set('actual_intercept', True)
        settings.set('actual_proxy', self.view.id())
        ActualVim.views[self.panel.id()] = self.actual

    def on_done(self, text):
        self.vim.press('enter')
        self.vim.panel = None

    def on_cancel(self):
        self.vim.press('escape')
        self.vim.panel = None

ActualVim.reload_classes()
