import sublime
import traceback


def copy_sel(sel):
    if isinstance(sel, sublime.View):
        sel = sel.sel()
    return [(r.a, r.b) for r in sel]


class ViewMeta:
    views = {}

    @classmethod
    def get(cls, view, create=True, exact=True):
        vid = view.id()
        m = cls.views.get(vid)
        if not m and create:
            try:
                m = cls(view)
            except Exception:
                traceback.print_exc()
                return
            cls.views[vid] = m
        elif m and exact and m.view != view:
            return None

        return m

    def __init__(self, view):
        self.view = view
        self.last_sel = copy_sel(view)
        self.buf = ''

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

        return regions

    def size(self):
        return len(self.buf)
