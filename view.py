import sublime
import traceback

from . import neo
from .edit import Edit

KEYMAP = {
    'backspace': '\b',
    'enter': '\n',
    'escape': '\033',
    'space': ' ',
    'tab': '\t',
    'up': '\033[A',
    'down': '\033[B',
    'right': '\033[C',
    'left': '\033[D',
}

def keymap(key):
    if '+' in key and key != '+':
        mods, key = key.rsplit('+', 1)
        mods = mods.split('+')
        if mods == ['ctrl']:
            b = ord(key)
            if b >= 63 and b < 96:
                return chr((b - 64) % 128)

    return KEYMAP.get(key, key)


def copy_sel(sel):
    if isinstance(sel, sublime.View):
        sel = sel.sel()
    return [(r.a, r.b) for r in sel]


try:
    _views
except NameError:
    _views = {}


class ViewMeta:
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

        return m

    def __init__(self, view):
        self.view = view
        self.last_sel = copy_sel(view)

    def sel_changed(self):
        new_sel = copy_sel(self.view)
        changed = new_sel != self.last_sel
        self.last_sel = new_sel
        return changed

    def visual(self, mode, a, b):
        view = self.view
        regions = []
        sr, sc = a[0] - 1, a[1] - 1
        er, ec = b[0] - 1, b[1] - 1

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
        elif mode in ('^V', '\x16'):
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

class ActualVim(ViewMeta):
    def __init__(self, view):
        super().__init__(view)
        if view.settings().get('actual_proxy'):
            return

        view.settings().set('actual_intercept', True)
        view.settings().set('actual_mode', True)

        self.buf = neo.vim.buf_new()
        # TODO: set cursor here?
        self.buf[:] = view.substr(sublime.Region(0, view.size())).split('\n')
        self.reselect()

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

    @property
    def actual(self):
        return self.view and self.view.settings().get('actual_mode')

    def activate(self):
        neo.vim.buf_activate(self.buf)

    def reselect(self, edit=None):
        mode, a, b = neo.vim.sel
        regions = self.visual(mode, a, b)

        def select():
            sel = self.view.sel()
            sel.clear()
            sel.add_all(regions)

        if edit is None:
            Edit.defer(self.view, select)
        else:
            edit.callback(select)

    def press(self, key):
        self.activate()
        neo.vim.press(keymap(key))
        # TODO: trigger UI update on vim event, not here
        text = '\n'.join(self.buf[:])

        with Edit(self.view) as edit:
            edit.replace(sublime.Region(0, self.view.size()), text)
            self.reselect(edit)

    def close(self, view):
        if view == self.view:
            neo.vim.buf_close(self.buf)
            self.view.close()

    def set_path(self, path):
        return


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
