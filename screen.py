class Cell:
    def __init__(self, c=' '):
        self.c = c
        self.highlight = {}

    def __mul__(self, n):
        return [Cell(self.c) for i in range(n)]

    def __str__(self):
        return self.c

class Highlight:
    def __init__(self, line, highlight):
        self.line = line
        self.highlight = highlight
        self.start = 0
        self.end = 0

    def s(self):
        return (self.line, self.start, self.end, tuple(self.highlight.items()))

    def __eq__(self, h):
        return self.s() == h.s()

    def __hash__(self):
        return hash((self.line, self.start, self.end, tuple(self.highlight.items())))

class Screen:
    def __init__(self):
        self.x = 0
        self.y = 0
        self.resize(1, 1)
        self.highlight = {}
        self.changes = 0

    def resize(self, w, h):
        self.w = w
        self.h = h
        # TODO: should resize clear?
        self.screen = [Cell() * w for i in range(h)]
        self.scroll_region = [0, self.h, 0, self.w]
        # clamp cursor
        self.x = min(self.x, w - 1)
        self.y = min(self.y, h - 1)

    def clear(self):
        self.resize(self.w, self.h)

    def scroll(self, dy):
        ya, yb = self.scroll_region[0:2]
        xa, xb = self.scroll_region[2:4]
        yi = (ya, yb)
        if dy < 0:
            yi = (yb, ya - 1)

        for y in range(yi[0], yi[1], int(dy / abs(dy))):
            if ya <= y + dy < yb:
                self.screen[y][xa:xb] = self.screen[y + dy][xa:xb]
            else:
                self.screen[y][xa:xb] = Cell() * (xb - xa)

    def redraw(self, updates):
        blacklist = [
            'mode_change',
            'bell', 'mouse_on', 'highlight_set',
            'update_fb', 'update_bg', 'update_sp', 'clear',
        ]
        changed = False
        for cmd in updates:
            if not cmd:
                continue
            name, args = cmd[0], cmd[1:]
            if name == 'cursor_goto':
                self.y, self.x = args[0]
            elif name == 'eol_clear':
                changed = True
                self.screen[self.y][self.x:] = Cell() * (self.w - self.x)
            elif name == 'put':
                changed = True
                for cs in args:
                    for c in cs:
                        cell = self.screen[self.y][self.x]
                        cell.c = c
                        cell.highlight = self.highlight
                        self.x += 1
                        # TODO: line wrap is not specified, neither is wrapping off the end. semi-sane defaults.
                        if self.x >= self.w:
                            self.x = 0
                            self.y += 1
                            if self.y >= self.h:
                                self.y = 0
            elif name == 'resize':
                changed = True
                self.resize(*args[0])
            elif name == 'highlight_set':
                self.highlight = args[0][0]
            elif name == 'set_scroll_region':
                self.scroll_region = args[0]
            elif name == 'scroll':
                changed = True
                self.scroll(args[0][0])
            elif name in blacklist:
                pass
            # else:
            #     print('unknown update cmd', name)

        if changed:
            self.changes += 1

    def highlights(self):
        hlset = []
        for y, line in enumerate(self.screen):
            cur = {}
            h = None
            for x, cell in enumerate(line):
                if h and cur and cell.highlight == cur:
                    h.end = x + 1
                else:
                    cur = cell.highlight
                    if cur:
                        h = Highlight(y, cur)
                        h.start = x
                        h.end = x + 1
                        hlset.append(h)
        return hlset

    def p(self):
        print('-' * self.w)
        print(str(self))
        print('-' * self.w)

    def __setitem__(self, xy, c):
        x, y = xy
        try:
            cell = self.screen[y][x]
            cell.c = c
            cell.highlight = self.highlight
        except IndexError:
            pass

    def __getitem__(self, y):
        if isinstance(y, tuple):
            return self.screen[y[1]][y[0]]
        return ''.join(str(c) for c in self.screen[y])

    def __str__(self):
        return '\n'.join([self[y] for y in range(self.h)])
