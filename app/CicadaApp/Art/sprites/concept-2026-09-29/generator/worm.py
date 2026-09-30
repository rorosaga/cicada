"""The bookworm, v3: 32 x 32 room frames and an 18 x 18 menu-bar set.

Selective outline: plum `o` only on the underside and shadow side, body shade `B`
on the lit top/left edge and at every internal joint, so the silhouette reads on a
dark wall and the head, chest and curl read as one creature.
"""
from px import G, T, ell, N4

WORM = {  # exactly 11 keys; every frame below uses only these
    'o': ('#2B2140', 'outline on the shadow side, pupils, lines'),
    'b': ('#6FCF6A', 'body'),
    'B': ('#3F9E57', 'body shade, lit-side outline, antenna stalks'),
    'l': ('#B8EBA6', 'belly, highlight'),
    'w': ('#FFFFFF', 'lens, pages, teeth, cap brim'),
    'r': ('#F28BAE', 'blush'),
    'a': ('#E0A93A', 'glasses rim, book cover, bulb shade'),
    'z': ('#8896FF', 'zZ, sweat, tear, nightcap'),
    'q': ('#FFCB57', '?, sparkle, antenna bulb'),
    'e': ('#E5484D', 'error eyes'),
    'p': ('#8A2E55', 'inside of the mouth'),
}
PAL = {k: v[0] for k, v in WORM.items()}

W = 32
HX, HY = 20.0, 14.0          # head centre (pixel x+.5 test)
HEAD = (HX, HY, 11.0, 7.3)
BODY = [  # back to front: (cx, cy, rx, ry, belly_from_row or None)
    ('tip', 7.0, 18.2, 1.7, 2.0, None),
    ('curl', 4.8, 22.4, 2.9, 3.4, None),
    ('floor', 9.8, 26.6, 4.8, 3.1, 27),
    ('chest', 18.6, 25.0, 6.6, 4.7, 25),
]


def _compose(parts, dy=0):
    """parts: list of (name, mask, belly_from). Front parts last."""
    g = G(W, W)
    owner = {}
    for name, m, _ in parts:
        for p in m:
            owner[p] = name
    union = set(owner)
    order = [n for n, _, _ in parts]
    # fill + shading
    for name, m, belly in parts:
        for (x, y) in m:
            if owner.get((x, y)) != name:
                continue
            k = 'b'
            if belly is not None and y >= belly and x >= min(xx for xx, _ in m) + 2:
                k = 'l'
            # shade the bottom-right inner rim of each part
            if (x + 1, y + 1) not in m or (x, y + 1) not in m:
                k = 'B' if k == 'b' else 'b'
            g.set(x, y, k)
    # internal joints: a back part's pixel touching a front part -> B line
    for (x, y), name in owner.items():
        i = order.index(name)
        for dx, dy_ in N4:
            q = (x + dx, y + dy_)
            if q in owner and order.index(owner[q]) > i:
                g.set(x, y, 'B')
                break
    # outline: lit side (above / left of the shape) B, shadow side o
    for (x, y) in union:
        for dx, dy_ in N4:
            q = (x + dx, y + dy_)
            if q in union:
                continue
            lit = dy_ == -1 or (dx == -1 and y < 22)
            if g.get(*q) == T:
                g.set(*q, 'B' if lit else 'o')
            elif not lit:
                g.set(*q, 'o')
    return g, union


def body_parts(dy=0, hdx=0, hdy=0, breath=False):
    parts = []
    for name, cx, cy, rx, ry, belly in BODY:
        if breath and name == 'chest':
            ry += 0.4
            cy -= 0.3
        parts.append((name, ell(cx, cy + dy, rx, ry), None if belly is None else belly + dy))
    parts.append(('head', ell(HX + hdx, HY + dy + hdy, HEAD[2], HEAD[3]), None))
    return parts


# ---------------------------------------------------------------- features
def stamp(g, rows, x, y, remap=None):
    g.rows(rows, x, y, remap)


LENS = ['.aaaaaa.', 'awwwwwwa', 'awwwwwwa', 'awwwwwwa', 'awwwwwwa', '.aaaaaa.']
LX, RX, LY = 11, 21, 10   # lens boxes: cols 11-18 and 21-28, rows 10-15


def glasses(g, ox, oy, fill='w'):
    for x0 in (LX, RX):
        stamp(g, LENS, x0 + ox, LY + oy, {'w': fill})
    g.hline(19 + ox, 20 + ox, LY + 2 + oy, 'a')        # bridge
    g.set(10 + ox, LY + 1 + oy, 'a'); g.set(29 + ox, LY + 1 + oy, 'a')  # temples


def eyes(g, kind, gaze, ox, oy, pupil='o'):
    """Interior of each lens: cols x0+1..x0+6, rows LY+1..LY+4."""
    for side, x0 in ((0, LX), (1, RX)):
        ix, iy = x0 + 1 + ox, LY + 1 + oy
        px = ix + {'l': 0, 'c': 2, 'r': 4}[gaze]
        if kind == 'open':
            g.rect(px, iy, 2, 3, pupil); g.set(px + 1, iy, 'w')
        elif kind == 'down':
            g.rect(px, iy + 1, 2, 3, pupil); g.set(px + 1, iy + 1, 'w')
        elif kind == 'wide':
            g.rect(px, iy, 2, 3, pupil)
        elif kind == 'blink':
            g.hline(ix, ix + 5, iy + 2, 'o')
        elif kind == 'closed':
            g.pts([(ix, iy + 1), (ix + 1, iy + 2), (ix + 2, iy + 2), (ix + 3, iy + 2), (ix + 4, iy + 2), (ix + 5, iy + 1)], 'o')
        elif kind == 'happy':
            g.pts([(ix, iy + 2), (ix + 1, iy + 1), (ix + 2, iy + 1), (ix + 3, iy + 1), (ix + 4, iy + 1), (ix + 5, iy + 2)], 'o')
        elif kind == 'half':
            g.rect(ix, iy, 6, 1, 'b'); g.hline(ix, ix + 5, iy + 1, 'o')
            g.rect(px, iy + 2, 2, 2, pupil)
        elif kind == 'x':
            cx = ix + (1 if side == 0 else 2)
            g.pts([(cx, iy), (cx + 1, iy + 1), (cx + 2, iy + 2), (cx + 2, iy), (cx, iy + 2)], 'e')
        elif kind == 'redlens':
            g.rect(ix, iy, 6, 4, 'e')


MOUTH = {
    'smile': ['o....o', '.oooo.'],
    'flat': ['......', '.oooo.'],
    'frown': ['.oooo.', 'o....o'],
    'cat': ['o.oo.o', '.o..o.'],
    'open': ['.oo.', 'oppo', '.oo.'],
    'grin': ['oooooo', 'owppwo', '.oooo.'],
    'wide': ['.oooo.', 'owwwwo', 'oppppo', '.oooo.'],
    'chew': ['o.o.o.', '.o.o.o'],
    'snore': ['.oo.', 'o..o', '.oo.'],
}


def mouth(g, kind, ox, oy):
    rows = MOUTH[kind]
    w = len(rows[0])
    y0 = 17 if len(rows) <= 2 else 16
    if kind == 'wide':
        y0 = 16
    stamp(g, rows, 20 - w // 2 + ox, y0 + oy)
    # the 'snore' ring is hollow: fill it with the mouth colour
    if kind == 'snore':
        g.hline(19 + ox, 20 + ox, 17 + oy, 'p')


def blush(g, ox, oy):
    g.hline(11 + ox, 12 + ox, 16 + oy, 'r'); g.hline(27 + ox, 28 + ox, 16 + oy, 'r')


ANT = {  # stalk cells (B) and bulb top-left, for the left antenna; right is mirrored
    'up':      ([(14, 6), (14, 5), (13, 4)], (12, 2)),
    'perk':    ([(15, 6), (15, 5), (15, 4), (15, 3)], (14, 1)),
    'flat':    ([(13, 6), (12, 6), (11, 6)], (9, 6)),
    'bent':    ([(14, 6), (14, 5), (13, 4), (12, 4)], (10, 4)),
    'cross':   ([(15, 6), (16, 5), (17, 4)], (18, 2)),
    'left':    ([(14, 6), (13, 5), (12, 4)], (11, 2)),
    'right':   ([(14, 6), (14, 5), (14, 4)], (14, 2)),
}


def antennae(g, pose, ox, oy):
    if pose == 'left' or pose == 'right':
        # lean both toward the gaze by one cell
        s = -1 if pose == 'left' else 1
        L = ([(14, 6), (14 + s * 0, 5), (14 + s, 4)], (13 + s, 2))
        R = ([(25, 6), (25, 5), (25 + s, 4)], (25 + s, 2))
        pairs = [L, R]
    else:
        st, bl = ANT[pose]
        pairs = [(st, bl), ([(39 - x, y) for x, y in st], (39 - bl[0] - 1, bl[1]))]
        if pose == 'cross':
            pairs[1] = ([(39 - x, y) for x, y in st], (39 - bl[0] - 1 + 0, bl[1] + 1))
    for st, (bx, by) in pairs:
        for (x, y) in st:
            g.set(x + ox, y + oy, 'B')
        stamp(g, ['qq', 'qa'], bx + ox, by + oy)


def cap(g, ox, oy):
    """Nightcap: crown flops LEFT, tip and pompom hang left of the head, brim leaves one row of forehead."""
    rows = {
        1: (11, 'oooooooo'),
        2: (9, 'oozzzzzzzzoo'),
        3: (7, 'oozzzzzwzzzzzzo'),
        4: (6, 'ozzzzzzzzzzwzzzo'),
        5: (5, 'ozzzzzzzzzzzzzzzzzo'),
        6: (4, 'ozzzozzzzzzzzzzzzzzzo'),
        7: (3, 'ozzzo.owwwwwwwwwwwwwwo'),
        8: (3, 'ozzo.owwwwwwwwwwwwwwwwwo'),
        9: (2, 'owwwo'),
        10: (2, 'owwwo'),
        11: (3, 'ooo'),
    }
    for y, (x, r) in rows.items():
        stamp(g, [r], x + ox, y + oy)


def zz(g, big):
    if big:
        stamp(g, ['zzzzz', '...z.', '..z..', '.z...', 'zzzzz'], 27, 0)
    else:
        stamp(g, ['zzz', '.z.', 'zzz'], 28, 2)


def qmark(g, lift):
    stamp(g, ['.qqq.', 'q...q', '...q.', '..q..', '.....', '..q..'], 26, 0 + lift)


def sparkle(g, x, y):
    g.pts([(x, y - 1), (x - 1, y), (x, y), (x + 1, y), (x, y + 1)], 'q')


def sweat(g, y):
    stamp(g, ['.z', 'zz', 'zw'], 29, y)


def tear(g, y):
    g.pts([(13, y), (13, y + 1)], 'z')


# ---------------------------------------------------------------- props (worm keys only)
def held_book(g, oy=0, turn=False):
    """An open book seen from behind, held by two hands at its lower corners."""
    y = 19 + oy
    rows = [
        '..owwwwwoowwwwwo..'[1:17],
        '.oaaaaaaaaaaaaao.'[:16],
        'oaaaaaaoaaaaaaao'[:16],
        'oawwwaaoaaaaaaao',
        'oaaaaaaoaaaaaaao',
        'oaaaaaaoaaaaaaao',
        '.oooooooooooooo.',
    ]
    rows[2] = 'oaaaaaaooaaaaaao'
    rows[3] = 'oawwwaaooaaaaaao'
    rows[4] = 'oaaaaaaooaaaaaao'
    rows[5] = 'oaaaaaaooaaaaaao'
    stamp(g, rows, 12, y)
    if turn:
        stamp(g, ['..wwww', '.w....', 'w.....'], 21, y - 2)
        g.pts([(21, y), (22, y)], 'w')
    # hands on the two lower corners, in front of the cover
    for x0 in (10, 26):
        stamp(g, ['.oo.', 'obbo', 'oblo', '.oo.'], x0, y + 3)


def bite_book(g, stage=0, oy=0):
    """A closed book at the right cheek; stage 0 whole, 1 bitten, 2 half gone."""
    x0, y0 = 23, 15 + oy
    if stage == 0:
        rows = ['oooooo', 'oaaaao', 'owwwao', 'oaaaao', 'oaaaao', 'oooooo']
    elif stage == 1:
        rows = ['...ooo', '..oaao', '.owwao', 'oaaaao', 'oaaaao', 'oooooo']
    else:
        rows = ['......', '......', '...ooo', '..oaao', '.oaaao', 'oooooo']
    stamp(g, rows, x0, y0)
    stamp(g, ['.oo.', 'oblo', '.oo.'], x0 + 1, y0 + 5)   # one hand under it
    if stage >= 1:
        g.pts([(30, 13 + oy), (31, 16 + oy)], 'a'); g.set(29, 11 + oy, 'w')


def arms_up(g, oy=0):
    for x0 in (8, 28):
        stamp(g, ['.BB.', 'obbo', 'obbo', '.ob.'] if x0 == 8 else ['.BB.', 'obbo', 'obbo', '.bo.'], x0 - 1, 17 + oy)


# ---------------------------------------------------------------- one frame
def frame(eyes_='open', gaze='c', mouth_='smile', ant='up', dy=0, hdx=0, hdy=0, capped=False,
          blush_=True, pupil='o', breath=False, over=(), props=()):
    g, _ = _compose(body_parts(dy, hdx, hdy, breath), dy)
    ox, oy = hdx, dy + hdy
    # a highlight arc on the crown
    for (x, y) in [(15, 8), (16, 8), (17, 8), (14, 9)]:
        if g.get(x + ox, y + oy) == 'b':
            g.set(x + ox, y + oy, 'l')
    glasses(g, ox, oy)
    eyes(g, eyes_, gaze, ox, oy, pupil)
    mouth(g, mouth_, ox, oy)
    if blush_:
        blush(g, ox, oy)
    for p in props:
        p(g, dy)
    if capped:
        cap(g, ox, oy)
    elif ant:
        antennae(g, ant, ox, oy)
    for o in over:
        o(g)
    return g


# ---------------------------------------------------------------- the state table
def states():
    """state -> [(label, frame)], plus which interval each loop plays at."""
    S = {}
    S['awake'] = [('awake · 1', frame()), ('awake · bob', frame(dy=1)), ('awake · blink', frame(eyes_='blink'))]
    S['sleeping'] = [
        ('sleeping · 1', frame(eyes_='closed', mouth_='flat', capped=True, blush_=False, over=[lambda g: zz(g, False)])),
        ('sleeping · 2', frame(eyes_='closed', mouth_='snore', capped=True, blush_=False, breath=True, over=[lambda g: zz(g, True)])),
    ]
    S['reading'] = [
        ('reading · scan left', frame(eyes_='down', gaze='l', mouth_='cat', capped=True, props=[lambda g, dy: held_book(g, dy)])),
        ('reading · scan right', frame(eyes_='down', gaze='r', mouth_='cat', capped=True, props=[lambda g, dy: held_book(g, dy)])),
        ('reading · page turn', frame(eyes_='down', gaze='c', mouth_='cat', capped=True, props=[lambda g, dy: held_book(g, dy, turn=True)])),
    ]
    S['digesting'] = [
        ('digesting · bite', frame(eyes_='wide', mouth_='wide', props=[lambda g, dy: bite_book(g, 0, dy)])),
        ('digesting · chew', frame(eyes_='happy', mouth_='chew', props=[lambda g, dy: bite_book(g, 1, dy)])),
        ('digesting · swallow', frame(eyes_='happy', mouth_='smile', dy=1, props=[lambda g, dy: bite_book(g, 2, dy)])),
    ]
    S['happy'] = [
        ('happy · 1', frame(eyes_='happy', mouth_='grin', ant='perk', over=[lambda g: (sparkle(g, 3, 9), sparkle(g, 30, 22))])),
        ('happy · bounce', frame(eyes_='happy', mouth_='grin', ant='perk', dy=-1, over=[lambda g: (sparkle(g, 29, 8), sparkle(g, 3, 13))])),
    ]
    S['hungry'] = [
        ('hungry · 1', frame(eyes_='half', mouth_='frown', ant='flat', dy=1, blush_=False, over=[lambda g: sweat(g, 9)])),
        ('hungry · drip', frame(eyes_='half', gaze='l', mouth_='frown', ant='flat', dy=1, blush_=False, over=[lambda g: sweat(g, 12)])),
    ]
    S['error'] = [
        ('error · 1', frame(eyes_='x', mouth_='flat', ant='bent', blush_=False, over=[lambda g: tear(g, 16)])),
        ('error · tear', frame(eyes_='x', mouth_='flat', ant='bent', blush_=False, over=[lambda g: tear(g, 18)])),
    ]
    S['curious'] = [
        ('curious · 1', frame(mouth_='cat', ant='cross', hdx=1, over=[lambda g: qmark(g, 0)])),
        ('curious · lift', frame(mouth_='cat', ant='cross', hdx=1, gaze='r', over=[lambda g: qmark(g, -1)])),
    ]
    return S


def responses():
    R = {}
    R['gaze'] = [('gaze · left', frame(gaze='l', ant='left')), ('gaze · centre', frame(gaze='c', ant='up')), ('gaze · right', frame(gaze='r', ant='right'))]
    R['perk'] = [('perk', frame(eyes_='wide', mouth_='open', ant='perk', dy=-1))]
    R['talk'] = [('talk · open', frame(mouth_='open')), ('talk · rest', frame(mouth_='smile'))]
    R['sleeptalk'] = [('talk · asleep', frame(eyes_='closed', mouth_='open', capped=True, blush_=False))]
    R['gulp'] = [('gulp · 1', frame(eyes_='wide', mouth_='wide', props=[lambda g, dy: bite_book(g, 0, dy)])),
                 ('gulp · 2', frame(eyes_='happy', mouth_='chew', props=[lambda g, dy: bite_book(g, 2, dy)]))]
    R['gulpread'] = [('gulp · reading', frame(eyes_='wide', mouth_='open', capped=True, props=[lambda g, dy: held_book(g, dy + 1)]))]
    R['shake'] = [('shake · left', frame(eyes_='wide', mouth_='flat', ant='up', hdx=-1)), ('shake · right', frame(eyes_='wide', mouth_='flat', ant='up', hdx=1))]
    R['expectant'] = [('expectant · 1', frame(eyes_='wide', gaze='r', mouth_='open', ant='right')),
                      ('expectant · hop', frame(eyes_='wide', gaze='r', mouth_='open', ant='right', dy=-1))]
    R['eager'] = [('eager', frame(eyes_='happy', mouth_='wide', ant='perk', dy=-1, over=[lambda g: (sparkle(g, 3, 8), sparkle(g, 30, 9))]))]
    R['cheer'] = [('cheer', frame(eyes_='happy', mouth_='grin', ant='perk', dy=-1,
                                  over=[lambda g: (sparkle(g, 3, 9), sparkle(g, 30, 20))]))]
    R['crouch'] = [('crouch · capped hop', frame(eyes_='closed', mouth_='open', capped=True, blush_=False, dy=1))]
    return R


# ---------------------------------------------------------------- menu bar: 18 x 18, drawn for its size
MB = 18


def mini(eyes_='open', mouth_='smile', ant='up', capped=False, dy=0, blush_=True, over=(), badge=None, gaze='c'):
    g = G(MB, MB)
    parts = [('curl', ell(3.2, 12.6 + dy, 2.2, 2.6), None),
             ('floor', ell(6.4, 15.0 + dy, 3.2, 2.0), None),
             ('chest', ell(10.6, 14.2 + dy, 4.0, 2.9), 15 + dy),
             ('head', ell(10.5, 7.6 + dy, 6.6, 5.0), None)]
    union = set()
    owner = {}
    for n, m, _ in parts:
        for p in m:
            owner[p] = n
    union = set(owner)
    order = [n for n, _, _ in parts]
    for (x, y), n in owner.items():
        m = dict((nn, mm) for nn, mm, _ in parts)[n]
        k = 'b'
        if n == 'chest' and y >= 15 + dy and x >= 8:
            k = 'l'
        if (x + 1, y + 1) not in m and n != 'head':
            k = 'B'
        g.set(x, y, k)
    for (x, y), n in owner.items():
        for dx, dy_ in N4:
            q = (x + dx, y + dy_)
            if q in owner and order.index(owner[q]) > order.index(n):
                g.set(x, y, 'B'); break
    for (x, y) in union:
        for dx, dy_ in N4:
            q = (x + dx, y + dy_)
            if q not in union and g.get(*q) == T:
                g.set(*q, 'B' if dy_ == -1 else 'o')
    oy = dy
    # glasses: two 4x4 frames with 2x2 lenses, one-cell bridge
    for x0 in (5, 11):
        stamp(g, ['.aa.', 'awwa', 'awwa', '.aa.'], x0, 5 + oy)
    g.hline(9, 10, 6 + oy, 'a')
    for x0 in (5, 11):
        ix, iy = x0 + 1, 6 + oy
        if eyes_ == 'open':
            px_ = ix + {'l': 0, 'c': 1 if x0 == 5 else 0, 'r': 1}[gaze]
            g.vline(px_, iy, iy + 1, 'o')
        elif eyes_ == 'closed':
            g.hline(ix, ix + 1, iy + 1, 'o')
        elif eyes_ == 'happy':
            g.hline(ix, ix + 1, iy, 'o')
        elif eyes_ == 'half':
            g.hline(ix, ix + 1, iy, 'b'); g.set(ix + (1 if x0 == 5 else 0), iy + 1, 'o')
        elif eyes_ == 'red':
            g.rect(ix, iy, 2, 2, 'e')
    my = 10 + oy
    if mouth_ == 'smile':
        g.pts([(8, my), (9, my + 1), (10, my + 1), (11, my)], 'o')
    elif mouth_ == 'grin':
        g.hline(8, 11, my, 'o'); g.hline(9, 10, my + 1, 'p')
    elif mouth_ == 'frown':
        g.pts([(8, my + 1), (9, my), (10, my), (11, my + 1)], 'o')
    elif mouth_ == 'flat':
        g.hline(9, 10, my + 1, 'o')
    elif mouth_ == 'open':
        g.hline(9, 10, my, 'o'); g.hline(9, 10, my + 1, 'p')
    if blush_:
        g.set(5, my, 'r'); g.set(15, my, 'r')
    if capped:
        stamp(g, ['....oooooo..', '..oozzzzzzo.', '.ozzzzzzzzzo', 'owwwwwwwwwwww', 'wo..........'], 3, 0 + oy)
    elif ant == 'up':
        g.pts([(7, 2 + oy), (6, 1 + oy), (13, 2 + oy), (14, 1 + oy)], 'B'); g.set(6, 0 + oy, 'q'); g.set(14, 0 + oy, 'q')
    elif ant == 'perk':
        g.pts([(7, 2 + oy), (7, 1 + oy), (13, 2 + oy), (13, 1 + oy)], 'B'); g.set(7, 0 + oy, 'q'); g.set(13, 0 + oy, 'q')
    elif ant == 'flat':
        g.pts([(6, 2 + oy), (5, 2 + oy), (14, 2 + oy), (15, 2 + oy)], 'B'); g.set(4, 3 + oy, 'q'); g.set(16, 3 + oy, 'q')
    elif ant == 'bent':
        g.pts([(7, 2 + oy), (6, 1 + oy), (5, 1 + oy), (13, 2 + oy), (14, 1 + oy), (15, 1 + oy)], 'B'); g.set(4, 2 + oy, 'q'); g.set(16, 2 + oy, 'q')
    for o in over:
        o(g)
    if badge is not None:
        draw_badge(g, badge)
    return g


DIG = {
    '0': ['ooo', 'o.o', 'o.o', 'o.o', 'ooo'], '1': ['.o.', 'oo.', '.o.', '.o.', 'ooo'], '2': ['ooo', '..o', 'ooo', 'o..', 'ooo'],
    '3': ['ooo', '..o', 'ooo', '..o', 'ooo'], '4': ['o.o', 'o.o', 'ooo', '..o', '..o'], '5': ['ooo', 'o..', 'ooo', '..o', 'ooo'],
    '6': ['ooo', 'o..', 'ooo', 'o.o', 'ooo'], '7': ['ooo', '..o', '..o', '.o.', '.o.'], '8': ['ooo', 'o.o', 'ooo', 'o.o', 'ooo'],
    '9': ['ooo', 'o.o', 'ooo', '..o', 'ooo'], '+': ['...', '.o.', 'ooo', '.o.', '...'],
}


def draw_badge(g, n):
    """One 3x5 glyph in a q pill, 5 x 7, bottom-right: the digit 1-9, or '+' for ten or more."""
    d = '+' if n >= 10 else str(max(1, n))
    x0, y0 = g.w - 5, g.h - 7
    g.rect(x0, y0, 5, 7, 'q')
    for (cx, cy) in ((x0, y0), (x0 + 4, y0), (x0, y0 + 6), (x0 + 4, y0 + 6)):
        g.clear(cx, cy)
    stamp(g, DIG[d], x0 + 1, y0 + 1)


def mini_set():
    zz_s = lambda g: stamp(g, ['zz', '.z', 'zz'], 16, 0)
    zz_b = lambda g: stamp(g, ['zzz', '.z.', 'zzz'], 15, 0)
    return [
        ('awake', mini()), ('awake · blink', mini(eyes_='closed')),
        ('sleeping · 1', mini(eyes_='closed', mouth_='flat', capped=True, blush_=False, over=[zz_s])),
        ('sleeping · 2', mini(eyes_='closed', mouth_='open', capped=True, blush_=False, over=[zz_b])),
        ('digesting', mini(eyes_='happy', mouth_='open', over=[lambda g: stamp(g, ['ooo', 'oao', 'owo', 'ooo'], 14, 8)])),
        ('happy', mini(eyes_='happy', mouth_='grin', ant='perk', over=[lambda g: g.pts([(1, 4), (0, 5), (1, 5), (2, 5), (1, 6)], 'q')])),
        ('hungry', mini(eyes_='half', mouth_='frown', ant='flat', dy=1, blush_=False, over=[lambda g: stamp(g, ['.z', 'zz'], 16, 5)])),
        ('curious · 3', mini(mouth_='smile', badge=3)),
        ('curious · 10+', mini(mouth_='smile', badge=12)),
        ('error', mini(eyes_='red', mouth_='flat', ant='bent', blush_=False)),
    ]
