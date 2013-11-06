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

    def visual(self, mode, start, end):
        view = self.view
        regions = []
        sr, sc = start
        er, ec = end

        left = min(sc, ec) - 1
        right = max(sc, ec)
        top = min(sr, er) - 1
        bot = max(sr, er) - 1

        start = view.text_point(bot, left)
        end = view.text_point(top, right)
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
            regions.append((start, end))
        elif mode == 'v':
            # visual mode
            regions.append((start, end))
        elif mode in ('^V', '\x16'):
            # visual block mode
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
