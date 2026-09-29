"""The study room v3: 176 x 54 cells at 4 pt (704 x 216), one pixel scale, dark and light.

Left to right the room is the queue's story: the PILE (to read) -> the worm on its
cushion under the window, the lamp beside it -> the CART (read, waiting to file) ->
the CRATE (set aside) -> the BOOKCASE (filed).
"""
import math, random
from px import G, T, ell, N4
from worm import PAL as WORM_PAL

RW, RH = 176, 54
FLOOR = 46          # first floor row
BASE = 49           # bottom row of every object standing on the floor

# ------------------------------------------------------------------ DeskPalette v2
# key: (dark, light, role). No key is a worm key (o b B l w r a z q e p).
DESK = {
    # structure (follows the theme)
    'W': ('#372E52', '#EFE6D8', 'wall'),
    'V': ('#3F3560', '#E6DAC7', 'wallpaper sprig'),
    'Y': ('#2F2747', '#DCCBB2', 'wainscot'),
    'R': ('#4B4070', '#C9B08E', 'chair rail'),
    'F': ('#4A3848', '#C99E74', 'floor'),
    'E': ('#3C2C3B', '#B5885E', 'floor seam'),
    'H': ('#57424F', '#D6AD84', 'floor sheen'),
    'k': ('#261F38', '#B39777', 'cast shadow'),
    'd': ('#2B2140', '#2B2140', 'deep outline, sill (= worm o, deliberate)'),
    # window and sky (art hues, both themes)
    'f': ('#4A3C6B', '#8C77B0', 'window frame'),
    'g': ('#5E4E86', '#A996C8', 'frame light edge'),
    'S': ('#171634', '#171634', 'night sky'),
    'm': ('#FFE18A', '#FFE18A', 'moon, sun, lit shade'),
    'n': ('#E0A93A', '#E0A93A', 'moon terminator, gilt (= worm a, deliberate)'),
    's': ('#FFCB57', '#FFCB57', 'star, lit rim, ribbon (= worm q, deliberate)'),
    'y': ('#8EC3F0', '#8EC3F0', 'day sky'),
    'Z': ('#B9DDF7', '#B9DDF7', 'sky haze band'),
    'j': ('#FFFFFF', '#FFFFFF', 'lit cloud, paper (= worm w, deliberate)'),
    'x': ('#C9D3DE', '#C9D3DE', 'cloud shade, overcast'),
    'K': ('#2E3440', '#2E3440', 'storm sky'),
    'N': ('#4C566A', '#4C566A', 'storm cloud'),
    'U': ('#7FA7C9', '#7FA7C9', 'rain'),
    'D': ('#F2B38A', '#F2B38A', 'dawn glow'),
    'O': ('#B97AA8', '#B97AA8', 'dawn sky'),
    '1': ('#3E7A4A', '#3E7A4A', 'meadow by day'),
    '2': ('#2C4A38', '#2C4A38', 'meadow at night'),
    # soft furnishings
    'c': ('#5B4B8A', '#7A68AE', 'cushion, curtains'),
    'P': ('#3A2F5C', '#5A4A88', 'cushion shadow, curtain fold'),
    'C': ('#7C6BB0', '#9C8BD0', 'cushion highlight, piping'),
    'u': ('#6B3F55', '#C77F86', 'rug'),
    'v': ('#8A5670', '#E0A3A3', 'rug border'),
    # wood, metal, plant
    'h': ('#7A5238', '#8E603F', 'wood'),
    'i': ('#5A3B28', '#6B462E', 'wood shade'),
    'J': ('#9A6C4A', '#AC7D55', 'wood light'),
    'L': ('#1E1830', '#3A2C22', 'shelf back'),
    'M': ('#6E7B8F', '#6E7B8F', 'metal, unlit lamp'),
    'Q': ('#B8C4D4', '#B8C4D4', 'metal highlight'),
    't': ('#8A5A3C', '#8A5A3C', 'terracotta'),
    'G': ('#4FA85A', '#4FA85A', 'leaf'),
    'X': ('#7ED77F', '#7ED77F', 'leaf light'),
    'A': ('#E9DFC8', '#E9DFC8', 'paper'),
    'I': ('#C7B994', '#C7B994', 'paper shade, twine'),
    '#': ('#D8C7A0', '#D8C7A0', 'brown paper'),
    '%': ('#AE9A70', '#AE9A70', 'brown paper shade'),
    '3': ('#1F1829', '#8F7A62', 'stage dot, unlit'),
    '4': ('#E0A93A', '#E0A93A', 'stage dot, lit'),
    '5': ('#241E30', '#241E30', 'cassette body'),
    '6': ('#3A3346', '#3A3346', 'cassette edge'),
}
DESK_LIGHT_OVERRIDE = {}

# ------------------------------------------------------------------ BookPalette (origin cloth hues, art only)
# origin id: (name, kind, cloth key, cloth hex, shade key, shade hex, furniture)
BOOKS = [
    ('claude-code', 'Claude Code', 'conv', '#C8664A', '#9E4A34', 'cloth, two gilt bands, terminal notch'),
    ('claude-desktop', 'Claude', 'conv', '#B8586C', '#8C4052', 'cloth, two gilt bands'),
    ('claude-export', 'Claude export', 'conv', '#C9A26B', '#9E7B49', 'buckram, ruled head and tail'),
    ('chatgpt-export', 'ChatGPT export', 'conv', '#2E8B74', '#1F6655', 'leather, three raised ribs'),
    ('codex', 'Codex', 'conv', '#5A5FB0', '#40448A', 'leather, three raised ribs, notch'),
    ('cursor', 'Cursor', 'conv', '#7A5BB5', '#58418E', 'cloth, one wide band'),
    ('gemini-export', 'Gemini export', 'conv', '#3F74B5', '#2C568C', 'buckram, ruled head and tail'),
    ('mcp', 'Other agents', 'conv', '#5E806B', '#43604F', 'cloth, one wide band'),
    ('chrome-bookmark', 'Chrome', 'page', '#3F74B5', '#2C568C', 'paper bundle, flag'),
    ('safari-bookmark', 'Safari', 'page', '#2E8BA8', '#1F6780', 'paper bundle, flag'),
    ('brave-bookmark', 'Brave', 'page', '#D0743A', '#A5562A', 'paper bundle, flag'),
    ('saved-link', 'Saved links', 'page', '#8C86D6', '#6A64B0', 'paper bundle, flag'),
    ('reddit', 'Reddit', 'page', '#D0743A', '#A5562A', 'clippings, flag'),
    ('x', 'X', 'page', '#4A4A58', '#33333F', 'clippings, flag'),
    ('linkedin', 'LinkedIn', 'page', '#2E6FA8', '#1F5280', 'clippings, flag'),
    ('pinterest', 'Pinterest', 'page', '#B8586C', '#8C4052', 'clippings, flag'),
    ('rss', 'Feeds', 'page', '#D99A3A', '#AE7722', 'newsprint, flag'),
    ('apple-notes', 'Apple Notes', 'note', '#E3B341', '#B88A22', 'spiral notebook'),
    ('folder', 'Watched folder', 'note', '#8E9E5A', '#6C7A40', 'ring binder'),
    ('calendar-local', 'Calendar', 'note', '#C86A5A', '#9E4E42', 'tear-off pad'),
    ('wispr', 'Wispr Flow', 'tape', '#8C86D6', '#6A64B0', 'audio cassettes'),
    ('youtube', 'YouTube', 'tape', '#C8664A', '#9E4A34', 'video cassettes'),
    ('telegram', 'Telegram', 'letter', '#3F8FC8', '#2C6E9E', 'letters, twine'),
    ('other', 'Other sources', 'more', '#7C6BB0', '#5A4A88', 'mixed bundle'),
    ('unknown', 'Unknown origin', 'parcel', '#D8C7A0', '#AE9A70', 'brown paper, twine, tag'),
]
BOOK_KEY = {}
BOOK_PAL = {}
for i, (oid, name, kind, c, s, furn) in enumerate(BOOKS):
    k1, k2 = f'c{i}', f's{i}'
    BOOK_KEY[oid] = (k1, k2)
    BOOK_PAL[k1] = c
    BOOK_PAL[k2] = s
ORIGIN = {b[0]: b for b in BOOKS}


def palette(theme='dark'):
    p = dict(WORM_PAL)
    for k, (dk, lt, _) in DESK.items():
        p[k] = dk if theme == 'dark' else DESK_LIGHT_OVERRIDE.get(k, lt)
    p.update(BOOK_PAL)
    return p


# ------------------------------------------------------------------ room shell
def shell(weather, lamp, theme):
    g = G(RW, RH)
    g.rect(0, 0, RW, FLOOR, 'W')
    # wallpaper: a small sprig on a diagonal lattice
    for y in range(3, 38, 7):
        for x in range((y // 7) % 2 * 6 + 2, RW, 12):
            g.pts([(x, y), (x - 1, y + 1), (x + 1, y + 1), (x, y + 2)], 'V')
    # wainscot
    g.rect(0, 39, RW, 7, 'Y')
    g.hline(0, RW - 1, 39, 'R'); g.hline(0, RW - 1, 40, 'k')
    for x in range(6, RW, 14):
        g.vline(x, 42, 44, 'R'); g.hline(x, x + 9, 42, 'R'); g.hline(x, x + 9, 44, 'k'); g.vline(x + 9, 42, 44, 'k')
    g.hline(0, RW - 1, FLOOR - 1, 'k')
    # floor: planks with staggered seams and a sheen row
    g.rect(0, FLOOR, RW, RH - FLOOR, 'F')
    for i, y in enumerate(range(FLOOR + 1, RH, 2)):
        g.hline(0, RW - 1, y, 'E' if i % 2 == 0 else 'F')
        for x in range((i * 17) % 29, RW, 29):
            g.set(x, y - 1, 'E')
    g.hline(0, RW - 1, FLOOR, 'H')
    # rug under the cushion, cart and crate
    rug = set()
    for y in range(BASE - 1, RH - 1):
        inset = (RH - 2 - y)
        for x in range(64 - inset, 144 + inset):
            rug.add((x, y))
    for (x, y) in rug:
        g.set(x, y, 'u')
    for (x, y) in rug:
        if any((x + dx, y + dy) not in rug for dx, dy in N4):
            g.set(x, y, 'v')
    for x in range(66, 142, 4):
        g.set(x, BASE + 1, 'v')
    return g


def window(g, weather, x0=60, y0=4, w=33, h=30):
    g.rect(x0, y0, w, h, 'f')
    gx, gy, gw, gh = x0 + 2, y0 + 2, w - 4, h - 4
    weather_pane(g, gx, gy, gw, gh, weather)
    mx = x0 + w // 2
    g.vline(mx, y0, y0 + h - 1, 'f'); g.vline(mx - 1, y0, y0 + h - 1, 'f')
    g.hline(x0, x0 + w - 1, y0 + h // 2, 'f'); g.hline(x0, x0 + w - 1, y0 + h // 2 - 1, 'f')
    # light edge on the frame's top-left, outline around
    g.hline(x0 + 1, x0 + w - 2, y0 + 1, 'g'); g.vline(x0 + 1, y0 + 1, y0 + h - 2, 'g')
    g.hline(x0 - 1, x0 + w, y0 - 1, 'd'); g.vline(x0 - 1, y0, y0 + h, 'd'); g.vline(x0 + w, y0, y0 + h, 'd')
    # sill
    g.rect(x0 - 3, y0 + h, w + 6, 2, 'h'); g.hline(x0 - 3, x0 + w + 2, y0 + h, 'J'); g.hline(x0 - 3, x0 + w + 2, y0 + h + 2, 'k')
    # curtains tied back (closed only for 'curtains')
    if weather == 'curtains':
        g.rect(gx, gy, gw, gh, 'c')
        for x in range(gx + 1, gx + gw, 3):
            g.vline(x, gy, gy + gh - 1, 'P')
        g.vline(mx - 1, gy, gy + gh - 1, 'P'); g.vline(mx, gy, gy + gh - 1, 'd')
    for side in (0, 1):
        cx = x0 - 4 if side == 0 else x0 + w
        for y in range(y0 - 2, y0 + h):
            wid = 4 if y < y0 + 12 or y > y0 + 16 else 2
            xs = range(cx, cx + wid) if side == 0 else range(cx + 4 - wid, cx + 4)
            for x in xs:
                g.set(x, y, 'c')
            g.set(xs[0] if side == 1 else xs[-1], y, 'P')
        ty = y0 + 14
        g.hline(cx, cx + 3, ty, 's')
    g.hline(x0 - 6, x0 + w + 5, y0 - 3, 'i'); g.set(x0 - 6, y0 - 3, 'J'); g.set(x0 + w + 5, y0 - 3, 'J')


def weather_pane(g, x0, y0, w, h, kind):
    rnd = random.Random(7)
    def hills(k):
        for x in range(w):
            top = h - 5 + int(round(1.6 * math.sin(x / 4.2 + 0.6)))
            g.vline(x0 + x, y0 + top, y0 + h - 1, k)
    if kind == 'night':
        g.rect(x0, y0, w, h, 'S')
        for (sx, sy) in [(2, 3), (8, 7), (13, 2), (4, 11), (11, 13), (20, 16), (26, 12), (23, 3)]:
            if sx < w and sy < h:
                g.set(x0 + sx, y0 + sy, 's' if (sx + sy) % 3 else 'j')
        for p in ell(x0 + w - 7.0, y0 + 5.5, 3.3, 3.3):
            g.set(*p, 'm')
        for p in ell(x0 + w - 5.6, y0 + 4.5, 2.9, 2.9):
            g.set(*p, 'S')
        hills('2')
    elif kind == 'curtains':
        g.rect(x0, y0, w, h, 'S')
    else:
        sky = {'fair': 'y', 'clear': 'y', 'overcast': 'x', 'storm': 'K', 'dawn': 'O'}[kind]
        g.rect(x0, y0, w, h, sky)
        if kind == 'dawn':
            for yy in range(h // 2 - 2, h):
                g.hline(x0, x0 + w - 1, y0 + yy, 'D' if yy > h * 0.62 else 'O')
            for p in ell(x0 + w * 0.3, y0 + h - 5, 4, 4):
                if p[1] < y0 + h - 5:
                    g.set(*p, 'm')
        if kind in ('clear', 'fair'):
            g.rect(x0, y0 + h - 9, w, 3, 'Z')
            for p in ell(x0 + 6.5, y0 + 5.5, 3.1, 3.1):
                g.set(*p, 'm')
            if kind == 'clear':
                for (sx, sy) in [(6, 1), (6, 10), (1, 5), (11, 5)]:
                    g.set(x0 + sx, y0 + sy, 'm')
        if kind in ('fair', 'overcast', 'storm'):
            cc = {'fair': ('j', 'x'), 'overcast': ('j', 'x'), 'storm': ('N', 'K')}[kind]
            clouds = [(17, 5, 5, 2.2), (10, 12, 6, 2.4)] if kind == 'fair' else [(6, 4, 7, 2.6), (21, 6, 7, 2.8), (13, 11, 8, 2.8)]
            for (cx, cy, rx, ry) in clouds:
                m = ell(x0 + cx, y0 + cy, rx, ry) | ell(x0 + cx - rx * .5, y0 + cy + .8, rx * .6, ry * .8) | ell(x0 + cx + rx * .6, y0 + cy + .8, rx * .5, ry * .7)
                for (x, y) in m:
                    if x0 <= x < x0 + w and y0 <= y < y0 + h:
                        g.set(x, y, cc[1] if y > y0 + cy + .5 else cc[0])
        if kind == 'storm':
            for i in range(16):
                rx_, ry_ = rnd.randrange(w), rnd.randrange(12, h - 4)
                g.set(x0 + rx_, y0 + ry_, 'U'); g.set(x0 + rx_ - 1, y0 + ry_ + 1, 'U')
            g.pts([(x0 + 18, y0 + 12), (x0 + 17, y0 + 13), (x0 + 16, y0 + 14), (x0 + 17, y0 + 14), (x0 + 18, y0 + 14), (x0 + 17, y0 + 15), (x0 + 16, y0 + 16)], 's')
        hills('1' if kind in ('fair', 'clear', 'dawn') else '2')


def picture(g, x=112, y=11):
    """A small framed pixel cicada on the wall: decoration, never reacts."""
    g.rect(x, y, 15, 12, 'h'); g.rect(x + 1, y + 1, 13, 10, 'J'); g.rect(x + 2, y + 2, 11, 8, 'Z')
    g.hline(x - 1, x + 15, y - 1, 'd'); g.vline(x - 1, y, y + 12, 'd'); g.vline(x + 15, y, y + 12, 'd'); g.hline(x - 1, x + 15, y + 12, 'd')
    g.rect(x + 2, y + 7, 11, 3, '1')
    g.rows(['.jj.jj.', 'jxGGGxj', '.xGGGx.', '..GGG..', '...G...'], x + 4, y + 2)
    g.pts([(x + 7, y - 2), (x + 6, y - 3), (x + 8, y - 3)], 'd')


def lamp(g, lit, x=56):
    shade = 'm' if lit else 'M'
    rim = 's' if lit else 'M'
    # light pool on the wall and floor, dithered, only when lit
    if lit:
        # a pool of light on the floor under the shade, dithered at its rim
        for (xx, yy) in ell(x + 6.5, BASE + 1.5, 13, 3.2):
            k = g.get(xx, yy)
            if k in ('F', 'E', 'H', 'u', 'v'):
                inner = ((xx + .5 - x - 6.5) / 13) ** 2 + ((yy + .5 - BASE - 1.5) / 3.2) ** 2 < 0.45
                if inner or (xx + yy) % 2 == 0:
                    g.set(xx, yy, {'F': 'H', 'E': 'F', 'H': 'H', 'u': 'v', 'v': 'v'}[k])
    for i, y in enumerate(range(9, 17)):
        g.hline(x + 3 - i // 2, x + 9 + i // 2, y, shade)
        g.set(x + 2 - i // 2, y, 'd'); g.set(x + 10 + i // 2, y, 'd')
    g.hline(x + 3, x + 9, 8, 'd')
    g.hline(x - 2, x + 14, 17, rim); g.hline(x - 2, x + 14, 18, 'd')
    g.vline(x + 6, 19, BASE - 1, 'M'); g.vline(x + 7, 19, BASE - 1, 'Q')
    g.rect(x + 2, BASE - 1, 10, 2, 'M'); g.hline(x + 2, x + 11, BASE - 1, 'Q'); g.hline(x + 1, x + 12, BASE + 1, 'k')


def plant(g, x=67, yb=33):
    g.rect(x, yb - 3, 6, 4, 't'); g.hline(x - 1, x + 6, yb - 3, 't'); g.hline(x, x + 5, yb, 'i')
    for (px_, py_, k) in [(x + 2, yb - 5, 'G'), (x + 1, yb - 7, 'X'), (x + 3, yb - 8, 'G'), (x + 4, yb - 6, 'X'), (x, yb - 5, 'G'), (x + 5, yb - 9, 'G'), (x + 2, yb - 10, 'X')]:
        g.rect(px_, py_, 2, 2, k)
    g.vline(x + 3, yb - 6, yb - 4, 'G')


def cushion(g, x=72, w=35):
    """A plump floor cushion: piping, a highlight row, tufts and a cast shadow."""
    y0 = BASE - 4
    g.hline(x + 1, x + w, BASE + 1, 'k')
    m = ell(x + w / 2, y0 + 2.6, w / 2, 3.0)
    for (xx, yy) in m:
        g.set(xx, yy, 'c')
    for (xx, yy) in m:
        if (xx, yy + 1) not in m:
            g.set(xx, yy, 'P')
        if (xx, yy - 1) not in m:
            g.set(xx, yy, 'C')
    for (xx, yy) in m:
        for dx, dy in N4:
            q = (xx + dx, yy + dy)
            if q not in m:
                g.set(*q, 'd')
    for tx in (x + 9, x + w // 2, x + w - 9):
        g.set(tx, y0 + 3, 'P')
    for xx in (x, x + w):
        g.set(xx, y0 + 2, 'C')


def stage_dots(g, lit, x=79):
    for i in range(5):
        xx = x + i * 5
        k = '4' if i < lit else '3'
        g.rect(xx, BASE + 2, 2, 2, k)


# ------------------------------------------------------------------ the pile
def plate_rect(x, y0, w, t):
    """A 4-cell label plate, centred vertically, 1 cell in from the spine's left band."""
    pw = 12
    py = y0 + (t - 4) // 2
    px_ = x + (w - pw) // 2
    return (px_, py, pw, 4)


def hardcover(g, oid, x, yb, w, t, ribbon=False, plate=True):
    c, s = BOOK_KEY[oid]
    furn = ORIGIN[oid][5]
    y0 = yb - t + 1
    g.rect(x, y0, w, t, c)
    g.hline(x, x + w - 1, yb, s)
    g.hline(x + 1, x + w - 2, y0, s if 'leather' in furn else c)
    g.vline(x, y0, yb, 'd'); g.vline(x + w - 1, y0, yb, 'd'); g.hline(x, x + w - 1, y0 - 1, 'd')
    # page block showing at the right end (cream fore-edge)
    g.vline(x + w - 2, y0 + 1, yb - 1, 'A')
    if 'gilt' in furn:
        for bx in (x + 2, x + 4, x + w - 6):
            g.vline(bx, y0 + 1, yb - 1, 'n')
    if 'ribs' in furn:
        for bx in (x + 2, x + 5, x + w - 6):
            g.vline(bx, y0, yb, s); g.set(bx, y0, 'n')
    if 'wide band' in furn:
        g.rect(x + 2, y0 + 1, 3, t - 2, s)
    if 'ruled' in furn:
        g.hline(x + 1, x + w - 3, y0 + 1, 'n'); g.hline(x + 1, x + w - 3, yb - 1, 'n')
    if 'notch' in furn:
        g.set(x + w - 4, y0 + 1, 'd')
    pl = None
    if plate and t >= 5 and w >= 16:
        pl = plate_rect(x, y0, w, t)
        g.rect(*pl, 'd')
    if ribbon:
        rx = x + w - 6
        g.vline(rx, y0 - 1, y0 + 3, 's'); g.vline(rx + 1, y0 - 1, y0 + 3, 's')
        g.set(rx, y0 + 4, 's')   # notched end: one cell longer on the left
    return pl


def bundle(g, oid, x, yb, w, t, plate=True, ribbon=False):
    """Pages: a squared bundle of paper tied with twine, an origin flag on the left."""
    c, s = BOOK_KEY[oid]
    y0 = yb - t + 1
    for i in range(t):
        y = yb - i
        off = (i * 5) % 3 - 1
        g.hline(x + 1 + off, x + w - 2 + off, y, 'A' if i % 2 else 'j')
        g.set(x + 1 + off, y, 'I'); g.set(x + w - 2 + off, y, 'I')
    g.hline(x, x + w - 1, y0 - 1, 'd')
    for sx in (x + 7, x + w - 7):
        g.vline(sx, y0, yb, 'I')
    g.rect(x - 1, y0 + 1, 3, min(4, t - 1), c); g.vline(x - 1, y0 + 1, y0 + min(4, t - 1), s)
    pl = None
    if plate and t >= 5 and w >= 16:
        pl = plate_rect(x, y0, w, t)
        g.rect(*pl, 'd')
    if ribbon:
        rx = x + w - 6
        g.vline(rx, y0 - 1, y0 + 3, 's'); g.vline(rx + 1, y0 - 1, y0 + 3, 's'); g.set(rx, y0 + 4, 's')
    return pl


def notebook(g, oid, x, yb, w, t, plate=True, ribbon=False):
    c, s = BOOK_KEY[oid]
    y0 = yb - t + 1
    g.rect(x, y0, w, t, c); g.hline(x, x + w - 1, yb, s)
    g.vline(x, y0, yb, 'd'); g.vline(x + w - 1, y0, yb, 'd'); g.hline(x, x + w - 1, y0 - 1, 'd')
    furn = ORIGIN[oid][5]
    if 'spiral' in furn:
        for yy in range(y0, yb + 1):
            g.set(x + 1, yy, 'Q' if (yy - y0) % 2 == 0 else 'M')
        g.vline(x + w - 2, y0 + 1, yb - 1, 'A')
    elif 'binder' in furn:
        g.rect(x + 1, y0 + 1, 3, t - 2, s)
        for yy in (y0 + 1, yb - 1):
            g.set(x + 2, yy, 'Q')
    elif 'pad' in furn:
        g.rect(x + 1, y0, w - 2, 2, s)
        g.hline(x + 1, x + w - 2, y0 + 2, 'j')
    pl = None
    if plate and t >= 5 and w >= 16:
        pl = plate_rect(x, y0, w, t)
        g.rect(*pl, 'd')
    if ribbon:
        rx = x + w - 6
        g.vline(rx, y0 - 1, y0 + 3, 's'); g.vline(rx + 1, y0 - 1, y0 + 3, 's'); g.set(rx, y0 + 4, 's')
    return pl


def tapes(g, oid, x, yb, w, t, plate=True, ribbon=False):
    """Cassettes stacked, 3 rows each, an origin-coloured label."""
    c, s = BOOK_KEY[oid]
    n = max(1, t // 3)
    small = 'audio' in ORIGIN[oid][5]
    ww = w - 6 if small else w
    for i in range(n):
        y0 = yb - 3 * i - 2
        xo = x + (i % 2) + (3 if small else 0)
        g.rect(xo, y0, ww, 3, '5'); g.hline(xo, xo + ww - 1, y0, '6')
        g.hline(xo, xo + ww - 1, y0 - 1, 'd'); g.vline(xo, y0, y0 + 2, 'd'); g.vline(xo + ww - 1, y0, y0 + 2, 'd')
        g.hline(xo + 3, xo + ww - 4, y0 + 1, c)
    top = yb - 3 * n + 1
    pl = None
    if plate and 3 * n >= 5 and w >= 16:
        pl = plate_rect(x, top, w, 3 * n)
        g.rect(*pl, 'd')
    return pl


def letters(g, oid, x, yb, w, t, plate=True, ribbon=False):
    c, s = BOOK_KEY[oid]
    y0 = yb - t + 1
    for i in range(t):
        y = yb - i
        off = (i * 7) % 3
        g.hline(x + off, x + w - 3 + off, y, 'j' if i % 2 else 'A')
        g.set(x + off + w - 5, y, c)
    g.hline(x, x + w - 1, y0 - 1, 'd')
    g.vline(x + w // 2, y0, yb, 'I')
    pl = None
    if plate and t >= 5 and w >= 16:
        pl = plate_rect(x, y0, w, t)
        g.rect(*pl, 'd')
    return pl


def more(g, oid, x, yb, w, t, plate=True, ribbon=False):
    """The folded remainder: thin pamphlets of mixed tone, tied."""
    y0 = yb - t + 1
    tones = ['c23', 's23', 'A', 'c23', 'I']
    for i in range(t):
        y = yb - i
        off = (i * 3) % 3
        g.hline(x + 1 + off, x + w - 3 + off, y, tones[i % len(tones)])
    g.hline(x, x + w - 1, y0 - 1, 'd')
    g.vline(x + 5, y0, yb, 'I'); g.vline(x + w - 6, y0, yb, 'I')
    pl = None
    if plate and t >= 5 and w >= 16:
        pl = plate_rect(x, y0, w, t)
        g.rect(*pl, 'd')
    return pl


def parcel(g, oid, x, yb, w, t, plate=True, ribbon=False):
    y0 = yb - t + 1
    g.rect(x, y0, w, t, '#'); g.hline(x, x + w - 1, yb, '%')
    g.vline(x, y0, yb, 'd'); g.vline(x + w - 1, y0, yb, 'd'); g.hline(x, x + w - 1, y0 - 1, 'd')
    g.vline(x + w // 2, y0, yb, 'I'); g.hline(x + 1, x + w - 2, y0 + t // 2, 'I')
    g.rows(['jjj', 'jdj', 'jjj'], x + w // 2 + 1, y0 + t // 2 + 1)
    pl = None
    if plate and t >= 5 and w >= 16:
        pl = plate_rect(x, y0, w, t)
        g.rect(*pl, 'd')
    return pl


DRAW = {'conv': hardcover, 'page': bundle, 'note': notebook, 'tape': tapes, 'letter': letters, 'more': more, 'parcel': parcel}


def thickness(chars):
    """Height encodes the origin's characters: 3 + 0.55 * log2(1 + chars / 1000), 5..10 cells."""
    return max(5, min(10, round(3 + 0.55 * math.log2(1 + chars / 1000))))


def pile(g, items, x=2, base=BASE, ceiling=10, gap_x=29):
    """items: dicts {origin, waiting, total, chars, reading}; split into two stacks by kind.
    Returns plates [(x, y, w, h, origin, waiting)] and the fold factor."""
    conv = [i for i in items if ORIGIN[i['origin']][2] == 'conv']
    rest = [i for i in items if ORIGIN[i['origin']][2] != 'conv']
    plates = []
    folds = []
    for si, stack in enumerate((conv, rest)):
        stack = sorted(stack, key=lambda i: -i['chars'])
        if ORIGIN.get('other') and any(i['origin'] == 'other' for i in stack):
            stack = [i for i in stack if i['origin'] != 'other'] + [i for i in stack if i['origin'] == 'other']
        ts = [thickness(i['chars']) for i in stack]
        avail = base - ceiling + 1 - len(ts)
        need = sum(ts)
        f = 1.0
        if need > avail:
            f = avail / need
            ts = [max(5, int(t * f)) for t in ts]
        folds.append(f)
        yb = base
        full = 27 if si == 0 else 26
        sx = x + si * gap_x
        jit = [0, 1, -1, 1, 0, 1, -1, 0]
        for j, (it, t) in enumerate(zip(stack, ts)):
            if it['waiting'] <= 0 and not it.get('reading'):
                continue
            frac = it['waiting'] / it['total']
            w = full if frac >= 1 else max(16, round(16 + (full - 16) * frac))
            xx = sx + jit[j % 8] + (full - w) // 2
            kind = ORIGIN[it['origin']][2]
            pl = DRAW[kind](g, it['origin'], xx, yb, w, t, ribbon=it.get('reading', False))
            g.books = getattr(g, 'books', []) + [(it['origin'], xx, yb - t + 1, w, t)]
            if pl:
                plates.append(pl + (it['origin'], it['waiting'] - (1 if it.get('reading') else 0)))
            yb -= t + 1
    return plates, folds


# ------------------------------------------------------------------ cart, crate, bookcase
def cart(g, n, x=110):
    """A small wooden book cart: read, waiting to file. n closed books lie on it."""
    y_top = BASE - 9
    g.rect(x, y_top, 16, 2, 'h'); g.hline(x, x + 15, y_top, 'J'); g.hline(x - 1, x + 16, y_top - 1, 'd')
    g.rect(x, BASE - 3, 16, 2, 'h'); g.hline(x, x + 15, BASE - 3, 'J')
    for lx in (x, x + 15):
        g.vline(lx, y_top, BASE - 1, 'i')
    for wx in (x + 1, x + 13):
        g.rows(['dd', 'dd'], wx, BASE)
        g.set(wx, BASE, 'M')
    g.hline(x - 1, x + 16, BASE + 2, 'k')
    order = ['claude-code', 'chatgpt-export', 'codex', 'chrome-bookmark', 'claude-code', 'chatgpt-export']
    yb = y_top - 2
    for i in range(n):
        oid = order[i % len(order)]
        c, s = BOOK_KEY[oid]
        bw = 12 - (i % 2) * 2
        bx = x + 2 + (i % 2)
        g.rect(bx, yb, bw, 2, c); g.hline(bx, bx + bw - 1, yb + 1, s)
        g.vline(bx, yb, yb + 1, 'd'); g.vline(bx + bw - 1, yb, yb + 1, 'd'); g.hline(bx, bx + bw - 1, yb - 1, 'd')
        g.vline(bx + bw - 2, yb, yb, 'A')
        yb -= 3


def crate(g, n, x=128):
    """A slatted crate: set aside. n items sit in it (1..3)."""
    w, h = 16, 8
    y0 = BASE - h + 1
    items = [('bundle', 'chrome-bookmark'), ('book', 'chatgpt-export'), ('bundle', 'saved-link')]
    for i in range(n):
        kind, oid = items[i]
        c, s = BOOK_KEY[oid]
        yy = y0 - 2 - 2 * i
        xx = x + 2 + (i % 2) * 2
        if kind == 'book':
            g.rect(xx, yy, 11, 2, c); g.hline(xx, xx + 10, yy + 1, s); g.hline(xx, xx + 10, yy - 1, 'd')
        else:
            g.hline(xx, xx + 10, yy, 'j'); g.hline(xx, xx + 10, yy + 1, 'A'); g.hline(xx, xx + 10, yy - 1, 'd'); g.set(xx + 5, yy, 'I')
    g.rect(x, y0, w, h, 'h')
    for yy in range(y0 + 2, BASE, 3):
        g.hline(x, x + w - 1, yy, 'i')
    g.vline(x, y0, BASE, 'd'); g.vline(x + w - 1, y0, BASE, 'd'); g.hline(x, x + w - 1, y0 - 1, 'd'); g.hline(x, x + w - 1, BASE, 'i')
    g.vline(x + 2, y0, BASE - 1, 'J'); g.vline(x + w - 3, y0, BASE - 1, 'J')
    g.hline(x - 1, x + w, BASE + 1, 'k')


SHELF_ORDER = ['claude-code', 'chatgpt-export', 'codex', 'chrome-bookmark', 'apple-notes', 'youtube', 'other']


def shelf_slots(filed, frozen, slots=96):
    """Deterministic fill: S = floor(slots * filed_total / frozen); each origin floor(slots * f_o / frozen);
    the remainder of S goes to the origin with the most filed. Slots run in origin order."""
    total = sum(filed.values())
    S = slots * total // frozen
    per = {o: slots * filed.get(o, 0) // frozen for o in SHELF_ORDER}
    rem = S - sum(per.values())
    big = max(SHELF_ORDER, key=lambda o: filed.get(o, 0))
    per[big] += rem
    return per, S


def bookcase(g, per, x=145, y=4):
    w = 31
    g.rect(x, y, w, BASE - y + 1, 'L')
    g.rect(x, y, w, 2, 'h'); g.hline(x, x + w - 1, y, 'J')
    g.vline(x, y, BASE, 'h'); g.vline(x + 1, y, BASE, 'i'); g.vline(x + w - 1, y, BASE, 'h'); g.vline(x + w - 2, y, BASE, 'i')
    g.hline(x - 1, x + w, y - 1, 'd'); g.vline(x - 1, y, BASE, 'd')
    boards = [y + 12, y + 23, y + 34, BASE - 1]
    for b in boards:
        g.rect(x, b, w, 2, 'h'); g.hline(x, x + w - 1, b, 'J')
    tops = [y + 3, y + 14, y + 25, y + 36]
    seq = []
    for o in SHELF_ORDER:
        seq += [o] * per.get(o, 0)
    i = 0
    for si, (top, b) in enumerate(zip(tops, boards)):
        for k in range(24):
            if i >= len(seq):
                break
            sx = x + 3 + k
            bot = b - 1
            ht = 6 + ((i * 7 + si) % 4)
            ht = min(ht, bot - top + 1)
            c, s = BOOK_KEY[seq[i]]
            g.vline(sx, bot - ht + 1, bot, c if k % 2 else s)
            g.set(sx, bot - ht + 2, 'n' if (i % 5 == 0) else (c if k % 2 else s))
            g.set(sx, bot - ht, 'd')
            i += 1
    g.hline(x - 1, x + w, BASE + 1, 'k')


# ------------------------------------------------------------------ one room
def room(theme='dark', weather='fair', lamp_on=True, frame=None, items=(), cart_n=0, crate_n=0, shelf=None, dots=None):
    g = shell(weather, lamp_on, theme)
    window(g, weather)
    plant(g)
    picture(g)
    lamp(g, lamp_on)
    bookcase(g, shelf or {})
    plates, folds = pile(g, list(items))
    cart(g, cart_n)
    crate(g, crate_n)
    cushion(g)
    if frame is not None:
        g.blit(frame, 73, BASE - 32)
    if dots is not None:
        stage_dots(g, dots)
    return g, plates, folds
