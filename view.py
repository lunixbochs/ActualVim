import sublime


def copy_sel(sel):
    if isinstance(sel, sublime.View):
        sel = sel.sel()
    return [(r.a, r.b) for r in sel]


class ViewMeta:
    views = {}

    @classmethod
    def get(cls, view):
        vid = view.id()
        m = cls.views.get(vid)
        if not m:
            m = cls(view)
            cls.views[vid] = m
        return m

    def __init__(self, view):
        self.view = view
        self.last_sel = copy_sel(view)

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
                    b = view.text_point(i, right)
                    regions.append((a, b))

        return regions
