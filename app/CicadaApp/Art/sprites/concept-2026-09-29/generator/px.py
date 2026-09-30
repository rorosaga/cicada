"""Tiny pixel engine: a grid of palette keys, SVG + PNG out."""
T = '.'


class G:
    def __init__(s, w, h):
        s.w, s.h = w, h
        s.c = [[T] * w for _ in range(h)]

    def copy(s):
        g = G(s.w, s.h)
        g.c = [r[:] for r in s.c]
        return g

    def ok(s, x, y):
        return 0 <= x < s.w and 0 <= y < s.h

    def set(s, x, y, k):
        x, y = int(x), int(y)
        if k != T and s.ok(x, y):
            s.c[y][x] = k

    def clear(s, x, y):
        if s.ok(x, y):
            s.c[y][x] = T

    def get(s, x, y):
        return s.c[y][x] if s.ok(x, y) else T

    def rect(s, x, y, w, h, k):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                s.set(xx, yy, k)

    def hline(s, x0, x1, y, k):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            s.set(x, y, k)

    def vline(s, x, y0, y1, k):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            s.set(x, y, k)

    def pts(s, pts, k):
        for x, y in pts:
            s.set(x, y, k)

    def rows(s, rows, x0, y0, remap=None):
        """Stamp a list of strings; '.' and ' ' are transparent."""
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch not in (T, ' '):
                    s.set(x0 + i, y0 + j, remap.get(ch, ch) if remap else ch)

    def blit(s, o, x0, y0):
        for y in range(o.h):
            for x in range(o.w):
                k = o.c[y][x]
                if k != T:
                    s.set(x0 + x, y0 + y, k)

    def keys(s):
        return {k for r in s.c for k in r if k != T}

    def bbox(s):
        xs = [x for y in range(s.h) for x in range(s.w) if s.c[y][x] != T]
        ys = [y for y in range(s.h) for x in range(s.w) if s.c[y][x] != T]
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None

    def sig(s):
        return '\n'.join(''.join(r) for r in s.c)

    def svg(s, px, pal, extra=''):
        by = {}
        for y in range(s.h):
            x = 0
            while x < s.w:
                k = s.c[y][x]
                if k == T:
                    x += 1
                    continue
                x2 = x
                while x2 + 1 < s.w and s.c[y][x2 + 1] == k:
                    x2 += 1
                by.setdefault(k, []).append(f'M{x} {y}h{x2 - x + 1}v1h-{x2 - x + 1}z')
                x = x2 + 1
        paths = ''.join(f'<path fill="{pal[k]}" d="{"".join(v)}"></path>' for k, v in by.items())
        return (f'<svg width="{s.w * px}" height="{s.h * px}" viewBox="0 0 {s.w} {s.h}" '
                f'shape-rendering="crispEdges" aria-hidden="true" {extra}>{paths}</svg>')

    def png(s, path, px, pal, bg=(30, 30, 34)):
        from PIL import Image
        im = Image.new('RGB', (s.w * px, s.h * px), bg)
        pp = im.load()
        for y in range(s.h):
            for x in range(s.w):
                k = s.c[y][x]
                if k == T:
                    continue
                h = pal[k].lstrip('#')
                col = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
                for yy in range(px):
                    for xx in range(px):
                        pp[x * px + xx, y * px + yy] = col
        im.save(path)
        return im


def ell(cx, cy, rx, ry):
    out = set()
    for y in range(int(cy - ry - 2), int(cy + ry + 3)):
        for x in range(int(cx - rx - 2), int(cx + rx + 3)):
            if ((x + .5 - cx) / rx) ** 2 + ((y + .5 - cy) / ry) ** 2 <= 1.0:
                out.add((x, y))
    return out


N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def hexrgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(h):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = hexrgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
