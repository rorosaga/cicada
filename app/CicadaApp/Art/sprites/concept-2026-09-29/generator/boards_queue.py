# Historical 2026-09-29 queue/design boards, not the shipped scenery contract.
# Their seven mood-only weathers/palette labels are superseded by the 2026-10-02 scenery spec:
# five base weathers × day/dusk/night, six overlays, dark rooms lit by the lamp and the wall clock.
import os
HERE = os.path.dirname(os.path.abspath(__file__))
import json, math
from ui import *
from px import G, contrast
from worm import states, responses, mini_set, PAL as WPAL
import room as RM
from room import room, palette, RW, RH, BOOKS, BOOK_KEY, DESK, ORIGIN, DRAW, shelf_slots, bookcase, cart, crate, weather_pane, window, lamp, shell, stage_dots
from fixture import *

OUT = os.path.join(HERE, '..', 'boards') + os.sep
BOARDS = []


def save(name, title, w, h, html):
    open(OUT + name, 'w').write(html)
    BOARDS.append({'file': name, 'w': w, 'h': h, 'title': title})


S = states()
PALS = {'dark': palette('dark'), 'light': palette('light')}
MARKS = {o: MARK[o] for o in MARK}
MARKS.update({'apple-notes': 'icon:note', 'other': 'icon:more', 'youtube': 'youtube', 'cursor': 'icon:chat'})


def plates_to_marks(plates):
    return [(x, y, w, h, MARKS.get(o, 'icon:more'), c) for (x, y, w, h, o, c) in plates]


def scene(theme, weather, lamp_on, fr, m=None, reading=None, dots=None, empty_pile=False):
    items = [] if (m is None or empty_pile) else pile_items(m, reading)
    tot = {k: sum(v[k] for v in m.values()) for k in ('filed', 'read', 'reading', 'aside', 'waiting')} if m else {}
    shelf = shelf_slots(filed_of(m), FROZEN)[0] if m else {}
    g, plates, folds = room(theme, weather, lamp_on, fr, items, cart_books(tot.get('read', 0)), crate_items(tot.get('aside', 0)), shelf, dots)
    return g, plates_to_marks(plates)


def room_html(g, plates, theme, label):
    return pixel_block(g, PALS[theme], 4, plates, label=label)


def twin_caption(t):
    parts = [('shelf', f"{fig(t['filed'])} filed")]
    if t['read']:
        parts.append(('cart', f"{fig(t['read'])} read, waiting to file"))
    if t['reading']:
        parts.append(('openbook', f"{fig(t['reading'])} being read"))
    parts.append(('stack', f"{fig(t['waiting'])} waiting"))
    if t['aside']:
        parts.append(('crate', f"{fig(t['aside'])} set aside"))
    return ('<div style="display: flex; flex-wrap: wrap; justify-content: center; gap: 6px 16px; font-size: 12px; color: var(--t2)">'
            + ''.join(f'<span style="display: inline-flex; align-items: center; gap: 6px">{icon(ic, 14, "var(--t3)")}{esc(tx)}</span>' for ic, tx in parts) + '</div>')


def stage_strip(done):
    names = ['Read', 'Sort', 'Decide', 'Notice', 'File']
    cells = []
    for i, n in enumerate(names):
        if i < done:
            g_, col, fw = icon('check', 12, 'var(--t2)'), 'var(--t2)', 400
        elif i == done:
            g_, col, fw = '<span style="width: 8px; height: 8px; border-radius: 4px; background: var(--t1)"></span>', 'var(--t1)', 600
        else:
            g_, col, fw = '<span style="width: 8px; height: 8px; border-radius: 4px; box-shadow: inset 0 0 0 1.5px var(--t3)"></span>', 'var(--t2)', 400
        cells.append(f'<li style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: {col}; font-weight: {fw}">{g_}{n}</li>')
    return ('<ol aria-label="Stages" style="list-style: none; margin: 0; padding: 0; display: flex; gap: 20px; align-items: center">'
            + ''.join(cells) + '</ol>')


def sleep_card(roomh, lead, tail, controls, whisper, below=''):
    return f'''<section class="card" style="width: 760px; padding: 28px; display: flex; flex-direction: column; align-items: center; gap: 16px">
{roomh}
<div style="display: flex; flex-direction: column; align-items: center; gap: 4px; text-align: center; height: 70px; justify-content: center">
<div class="sentence">{esc(lead)}</div><div class="tail">{esc(tail)}</div></div>
{controls}
{below}
<div class="whisper">{esc(whisper)}</div>
</section>'''


def sleep_page(card, details=''):
    return f'''<div style="padding: 32px 70px; display: flex; flex-direction: column; gap: 16px">
<div style="display: flex; align-items: center; justify-content: space-between; width: 760px; height: 28px"><h1 style="margin: 0; font: 600 28px/28px {DISPLAY}; letter-spacing: -0.4px">Sleep</h1>
<button class="btnn" type="button" aria-label="Help for Sleep" style="width: 28px; height: 28px; padding: 0; justify-content: center; border-radius: 14px">?</button></div>
{card}
<div style="width: 760px">{details_button(bool(details))}</div>
{details}
</div>'''


def ctrl(primary, primary_icon, extra='', engine='Claude plan · Sonnet'):
    return (f'<div style="display: flex; align-items: center; gap: 12px">{button_primary(primary, primary_icon)}{engine_menu(engine)}</div>'
            + (f'<div>{extra}</div>' if extra else ''))


# ------------------------------------------------------------------ moments
m1, t1 = FIRST
m2, t2 = MID
m3, t3 = NEAR
m4, t4 = DONE

# ================================================================== D. the room in three moods, both themes
def mood_cards(theme):
    out = []
    g, pl = scene(theme, 'fair', False, S['reading'][0][1], m1)
    out.append(sleep_card(room_html(g, pl, theme, 'The study room: the worm reads, a pile of 1,187 waits'), f'{fig(t1["waiting"])} things to read.',
                          'Chats, saved pages, notes and videos. One press reads the first 25.',
                          ctrl('Consolidate', 'moon', '<button class="link" type="button">Read all of them…</button>'), 'Manual · nothing runs unless you press'))
    g, pl = scene(theme, 'night', True, S['sleeping'][0][1], m2, 'chatgpt-export', dots=1)
    out.append(sleep_card(room_html(g, pl, theme, 'The study room at night: the worm sleeps while the pile moves to the shelf'), 'Reading batch 20 of 48.',
                          'Now: a ChatGPT chat about trip planning for alpha-project.', ctrl('Pause', 'pause', engine='Claude plan · Haiku'),
                          'Every day at 03:00 · this run started by you at 20:59', twin_caption(t2) + stage_strip(0)))
    g, pl = scene(theme, 'storm', False, S['error'][0][1], m1)
    out.append(sleep_card(room_html(g, pl, theme, 'The study room in a storm: the last cycle failed'), 'The last cycle failed.',
                          'The engine stopped answering while reading. Nothing was lost.', ctrl('Consolidate', 'moon', '<button class="link" type="button">What went wrong ›</button>'),
                          'Manual · nothing runs unless you press'))
    return out


rows = []
for th in ('dark', 'light'):
    cards = ''.join(mood_cards(th))
    rows.append(f'<div class="t-{th} surf" style="padding: 36px 48px; display: grid; grid-template-columns: repeat(3, 760px); gap: 28px">{cards}</div>')
save('WormRoomMoods.dc.html', 'Worm · D · the room in three moods, dark and light', 2432, 1160, page('Study room moods', 2432, 1160, ''.join(rows)))

# ================================================================== E. before and after
import sys
src = open(__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), 'old_worm.py')).read()
src = '\n'.join(l for l in src.splitlines() if not l.startswith('show('))
o = {}
exec(src, o)


def oldgrid(rows_):
    g = G(24, 24)
    for y, r in enumerate(rows_):
        for x, ch in enumerate(r):
            if ch != '.':
                g.set(x, y, ch)
    return g


OLDPAL = {k: WPAL[k] for k in 'oblwrazqe'}
OLD = [oldgrid(o['compose'](o['eyes'](), o['smile'])),
       oldgrid(o['merge'](o['merge'](o['compose'](o['eyes'](), o['smile']), o['glyph'](o['bookOpen'], 15, 8)), o['cap'])),
       oldgrid(o['merge'](o['merge'](o['merge'](o['compose'](o['eyes'](lid='closed'), o['neutral']), o['glyph'](o['zBig'], 0, 19)), o['dots'](3)), o['cap'])),
       oldgrid(o['compose'](o['eyes'](lid='half'), o['neutral']))]
NEW = [S['awake'][0][1], S['reading'][0][1], S['sleeping'][1][1], S['hungry'][0][1]]
MS = dict(mini_set())
NEWM = [MS['awake'], None, MS['sleeping · 2'], MS['hungry']]
oldroom = json.load(open(__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), 'old_room.json')))
DESKOLD = {'d': '#2B2140', 'f': '#4A3C6B', 'k': '#1B1B38', 'm': '#FFE18A', 'n': '#E0A93A', 's': '#FFCB57', 'c': '#5B4B8A', 'p': '#3A2F5C',
           't': '#8A5A3C', 'g': '#4FA85A', 'h': '#7ED77F', 'i': '#6E7B8F', 'u': '#B8C4D4', 'y': '#8EC3F0', 'v': '#D7E8F5', 'j': '#FFFFFF',
           'x': '#C9D3DE', 'K': '#2E3440', 'N': '#4C566A', 'U': '#7FA7C9'}
OPAL = dict(OLDPAL)
OPAL.update({'D_' + k: v for k, v in DESKOLD.items()})


def oldroom_grid(wg):
    g = G(90, 28)
    def put(rows_, cx, cy, remap=None):
        top = 28 - cy - 24
        for y, r in enumerate(rows_):
            for x, ch in enumerate(r):
                if ch != '.':
                    ch = remap.get(ch, ch) if remap else ch
                    g.set(cx + x, top + y, 'D_' + ch)
    put(oldroom['fairPane'], 20, 4); put(oldroom['window'], 18, 4); put(oldroom['lampTemplate'], 0, 0, {'S': 'm', 'R': 's'})
    put(oldroom['plant'], 11, 0); put(oldroom['cushion'], 30, 0); put(oldroom['mug'], 52, 0)
    for y in range(24):
        for x in range(24):
            k = wg.c[y][x]
            if k != '.':
                g.set(28 + x, 28 - 4 - 24 + y, k)
    return g


def tl(content, w, h):
    return f'<div class="tile" style="width: {w}px; height: {h}px; display: flex; align-items: center; justify-content: center; flex: none">{content}</div>'


S18 = 'style="width: 18px; height: 18px; display: block"'
old_sprites = ''.join(tl(gr.svg(5, OPAL), 140, 140) for gr in OLD)
new_sprites = ''.join(tl(gr.svg(4, WPAL), 140, 140) for gr in NEW)
old_mb = ''.join(tl(gr.svg(1, OPAL, S18), 40, 32) for gr in (OLD[0], OLD[2], OLD[3]))
new_mb = ''.join(tl(gr.svg(1, WPAL), 40, 32) for gr in (NEWM[0], NEWM[2], NEWM[3]))
old_mbz = ''.join(tl(f'<div style="width: 90px; height: 90px">{gr.svg(1, OPAL, "style=" + chr(34) + "width: 90px; height: 90px; display: block" + chr(34))}</div>', 104, 104) for gr in (OLD[0], OLD[2]))
new_mbz = ''.join(tl(gr.svg(5, WPAL), 104, 104) for gr in (NEWM[0], NEWM[2]))
og = oldroom_grid(OLD[1])
slabs = [(150, 26, '#0A84FF'), (140, 20, '#8D8F94'), (132, 14, '#10A37F'), (120, 10, '#4285F4')]
slab_html = ''.join(f'<div style="width: {w}px; height: {h}px; border-radius: 3px; background: {c}; opacity: .85"></div>' for (w, h, c) in slabs)
old_room = (f'<div style="position: relative; width: 450px; height: 140px">{og.svg(5, OPAL, BLOCK)}'
            f'<div style="position: absolute; left: 300px; bottom: 0; width: 150px; display: flex; flex-direction: column; justify-content: flex-end; gap: 2px">{slab_html}</div></div>')
g, pl = scene('dark', 'fair', False, S['reading'][0][1], m1)
body = f'''<div style="padding: 40px 48px; display: grid; grid-template-columns: 620px 740px; gap: 28px 64px; align-items: center">
<div style="display: flex; gap: 12px">{old_sprites}</div><div style="display: flex; gap: 12px">{new_sprites}</div>
<div style="display: flex; gap: 12px; align-items: center">{old_mb}{old_mbz}</div><div style="display: flex; gap: 12px; align-items: center">{new_mb}{new_mbz}</div>
{tl(old_room, 620, 216)}{tl(room_html(g, pl, 'dark', 'The new study room'), 740, 236)}
</div>'''
save('WormOldVsNew.dc.html', 'Worm · E · before and after (old left, new right)', 1524, 620, page('Bookworm before and after', 1524, 620, body))

# ================================================================== Queue A. first run
g, pl = scene('dark', 'fair', False, S['reading'][0][1], m1)
card = sleep_card(room_html(g, pl, 'dark', 'A pile of 1,187 things waits beside the worm'), f'{fig(t1["waiting"])} things to read.',
                  'Chats, saved pages, notes and videos. One press reads the first 25.',
                  ctrl('Consolidate', 'moon', '<button class="link" type="button">Read all of them…</button>'), 'Manual · nothing runs unless you press')
save('QueueRoomFirstRun.dc.html', 'Queue · A · first run: two stacks, every item labelled', 900, 620, page('Sleep first run', 900, 620, sleep_page(card)))

# ================================================================== Queue B. mid drain, popover on the ChatGPT book
g, pl = scene('dark', 'night', True, S['sleeping'][0][1], m2, 'chatgpt-export', dots=1)
book = [b for b in g.books if b[0] == 'chatgpt-export'][0]
RX0, RY0 = 70 + 28, 32 + 28 + 16 + 28
bx0 = RX0 + book[1] * 4
by0 = RY0 + (book[2] - 1) * 4
bw, bh = book[3] * 4, (book[4] + 1) * 4
card = sleep_card(room_html(g, pl, 'dark', 'Night in the study room: the pile shrinks, the cart holds what was read, the shelf fills'), 'Reading batch 20 of 48.',
                  'Now: a ChatGPT chat about trip planning for alpha-project.', ctrl('Pause', 'pause', engine='Claude plan · Haiku'),
                  'Started by you at 20:59 · stops at the plan’s limit', twin_caption(t2) + stage_strip(0))
c = m2['chatgpt-export']
pop_rows = [('openbook', 'var(--t1)', 'Trip planning for alpha-project', 'Being read'),
            ('half', 'var(--t2)', 'Recipe scaling question', 'Read'),
            ('dot', 'var(--t3)', 'Helios Labs pitch notes', 'Waiting'),
            ('dot', 'var(--t3)', 'Rust lifetimes, again', 'Waiting')]
rows_html = ''.join(f'<li class="row" style="height: 32px; padding: 0">{icon(ic, 14, col)}<span class="t">{esc(tt)}</span><span class="s">{esc(ss)}</span></li>' for ic, col, tt, ss in pop_rows)
ay = by0 + bh // 2
pop_left = bx0 + bw + 14
pop_top = 64
pop = f'''<div class="pop" role="dialog" aria-label="ChatGPT in the pile" style="left: {pop_left}px; top: {pop_top}px; width: 344px">
<span style="position: absolute; left: -6px; top: {ay - pop_top - 6}px; width: 12px; height: 12px; background: var(--menu); transform: rotate(45deg); box-shadow: -1px 1px 0 0 var(--floatRing)"></span>
<div style="display: flex; align-items: center; gap: 10px">{mark('chatgptDark', 18)}<div style="flex: 1; font-size: 14px; font-weight: 600">ChatGPT</div><span class="meta">oldest 2 years</span></div>
<div style="font-size: 12px; color: var(--t2); line-height: 1.5">{c['filed']} filed · {c['read']} read · {c['reading']} being read · {c['waiting']} waiting · {c['aside']} set aside</div>
<ul style="list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column">{rows_html}</ul>
<div style="display: flex; justify-content: space-between; align-items: center"><button class="link" type="button">Open in What’s waiting ›</button><span class="meta">{c['total'] - 4} more</span></div></div>'''
ring = f'<div aria-hidden="true" style="position: absolute; left: {bx0 - 3}px; top: {by0 - 3}px; width: {bw + 6}px; height: {bh + 6}px; border-radius: 4px; box-shadow: 0 0 0 2px var(--focusRing)"></div>'
save('QueueRoomMidDrain.dc.html', 'Queue · B · mid-drain: pile, cart, crate, shelf and the ChatGPT book open', 900, 650,
     page('Sleep mid drain', 900, 650, sleep_page(card) + ring + pop))

# ================================================================== Queue C. nearly done
g, pl = scene('dark', 'night', True, S['sleeping'][1][1], m3, dots=3)
card = sleep_card(room_html(g, pl, 'dark', 'The pile is gone; twelve read books wait on the cart; the shelf is nearly full'), 'Filing the last batch.',
                  'Batch 48 of 48: the last Claude Code sessions from July.', ctrl('Pause', 'pause', engine='Claude plan · Haiku'),
                  'Started by you at 20:59 · stops at the plan’s limit', twin_caption(t3) + stage_strip(3))
save('QueueRoomNearlyDone.dc.html', 'Queue · C · nearly done: filing the last batch', 900, 650, page('Sleep nearly done', 900, 650, sleep_page(card)))

# ================================================================== Queue D. finished (the 6 s digest) and E. rested (light)
g, pl = scene('dark', 'dawn', False, S['digesting'][1][1], m4)
card = sleep_card(room_html(g, pl, 'dark', 'Dawn: the shelf is full, the crate holds what was set aside'), 'All read.',
                  f'{fig(t4["filed"])} filed. {t4["aside"]} set aside, each with its reason.',
                  ctrl('Consolidate', 'moon', '<button class="link" type="button">See what was set aside ›</button>'), 'Finished at 23:14 · Manual · nothing runs unless you press')
save('QueueRoomDone.dc.html', 'Queue · D · the run finished (the six-second digest)', 900, 620, page('Sleep drain done', 900, 620, sleep_page(card)))

g, pl = scene('light', 'clear', False, S['happy'][0][1], m4)
card = sleep_card(room_html(g, pl, 'light', 'A clear day: nothing waiting, the shelf full, the crate still there'), 'All caught up.',
                  'Nothing waiting. A cycle now would only tidy what is already filed.',
                  ctrl('Consolidate', 'moon', '<button class="link" type="button">See what was set aside ›</button>'), 'Manual · last run finished at 23:14')
save('QueueRoomRested.dc.html', 'Queue · E · rested after the run (light)', 900, 620, page('Sleep rested', 900, 620, sleep_page(card), cls='t-light surf'))

# ================================================================== Queue F. the pile folds
def pile_crop(items, label, frame_=None):
    g = G(60, RH)
    full, plates, folds = room('dark', 'fair', False, None, items, 0, 0, {}, None)
    for y in range(RH):
        for x in range(60):
            g.set(x, y, full.get(x, y))
    pls = [(x, y, w, h, MARKS.get(o, 'icon:more'), c) for (x, y, w, h, o, c) in plates if x + w <= 60]
    return (f'<figure style="margin: 0; display: flex; flex-direction: column; align-items: center; gap: 10px">{pixel_block(g, PALS["dark"], 4, pls, label=label)}'
            f'<figcaption style="font-size: 12px; color: var(--t2)">{esc(label)}</figcaption></figure>')


small = [dict(origin='claude-code', waiting=18, total=18, chars=320_000), dict(origin='chatgpt-export', waiting=9, total=9, chars=60_000),
         dict(origin='chrome-bookmark', waiting=6, total=6, chars=9_000), dict(origin='apple-notes', waiting=7, total=7, chars=8_000)]
big = [dict(origin='claude-code', waiting=2410, total=2410, chars=44_000_000), dict(origin='chatgpt-export', waiting=1296, total=1296, chars=8_000_000),
       dict(origin='codex', waiting=402, total=402, chars=5_000_000), dict(origin='cursor', waiting=204, total=204, chars=2_600_000),
       dict(origin='chrome-bookmark', waiting=380, total=380, chars=600_000), dict(origin='apple-notes', waiting=150, total=150, chars=400_000),
       dict(origin='youtube', waiting=78, total=78, chars=260_000), dict(origin='other', waiting=92, total=92, chars=200_000)]
mid_items = pile_items(m2, 'chatgpt-export')
tiles_ = [pile_crop(small, '40 waiting'), pile_crop(pile_items(m1), '1,187 waiting'), pile_crop(mid_items, '697 waiting · 1 being read'),
          pile_crop(big, '5,012 waiting · folded')]
body = f'<div style="padding: 40px 48px; display: flex; gap: 22px; align-items: flex-end">{"".join(tiles_)}</div>'
save('QueuePileFold.dc.html', 'Queue · F · the pile from 40 to 5,012 (folding)', 1100, 320, page('Pile folding', 1100, 320, body))

# ================================================================== Queue G. props sheet: one book per origin, the props, the shelf
def prop(draw, label, w=34, h=16, plate_key=None, count=None, px=4):
    g = G(w, h)
    pl = draw(g)
    pls = []
    if pl and plate_key:
        pls = [(pl[0], pl[1], pl[2], pl[3], plate_key, count)]
    return (f'<figure style="margin: 0; display: flex; flex-direction: column; align-items: center; gap: 8px">'
            f'<div class="tile" style="width: {w * px + 20}px; height: {h * px + 20}px; display: flex; align-items: center; justify-content: center">{pixel_block(g, PALS["dark"], px, pls, radius=0)}</div>'
            f'<figcaption style="font-size: 12px; color: var(--t2); white-space: nowrap">{esc(label)}</figcaption></figure>')


PLATE_MARK = {'claude-code': 'claude', 'claude-desktop': 'claude', 'claude-export': 'claude', 'chatgpt-export': 'chatgptDark', 'codex': 'codexDark',
              'chrome-bookmark': 'chrome', 'brave-bookmark': 'brave', 'reddit': 'reddit', 'x': 'xDark', 'linkedin': 'linkedin', 'youtube': 'youtube',
              'apple-notes': 'icon:note', 'other': 'icon:more'}
origin_tiles = []
for (oid, name, kind, c_, s_, furn) in BOOKS:
    fn = DRAW[kind]
    t = 9 if kind == 'tape' else 7
    origin_tiles.append(prop(lambda g, fn=fn, oid=oid, t=t: fn(g, oid, 4, 13, 27, t), name, plate_key=PLATE_MARK.get(oid, {'page': 'icon:page', 'note': 'icon:note', 'conv': 'icon:chat', 'tape': 'icon:video', 'letter': 'icon:chat', 'parcel': 'icon:more', 'more': 'icon:more'}[kind]), count=TOTAL.get(oid, 12)))


def carts(n):
    def f(g):
        cart_local(g, n)
    return f


def cart_local(g, n):
    tmp = G(RW, RH)
    cart(tmp, n)
    for y in range(RH):
        for x in range(107, 129):
            k = tmp.get(x, y)
            if k != '.' and 0 <= y - 34 < 20:
                g.set(x - 107, y - 34, k)


def crate_local(g, n):
    tmp = G(RW, RH)
    crate(tmp, n)
    for y in range(RH):
        for x in range(125, 147):
            k = tmp.get(x, y)
            if k != '.' and 0 <= y - 34 < 20:
                g.set(x - 125, y - 34, k)


state_tiles = [prop(lambda g: RM.hardcover(g, 'chatgpt-export', 4, 13, 27, 7, ribbon=True), 'being read · ribbon', plate_key='chatgptDark', count=175)]
state_tiles += [prop(lambda g, n=n: cart_local(g, n), f'cart · {n} of 6', w=22, h=18) for n in (1, 3, 6)]
state_tiles += [prop(lambda g, n=n: crate_local(g, n), f'crate · {n} of 3', w=22, h=18) for n in (1, 3)]


def shelf_tile(filed, label):
    tmp = G(RW, RH)
    per, S_ = shelf_slots(filed, FROZEN) if filed else ({}, 0)
    bookcase(tmp, per)
    g = G(33, 48)
    for y in range(RH):
        for x in range(144, 177):
            k = tmp.get(x, y)
            if k != '.' and 0 <= y - 2 < 48:
                g.set(x - 144, y - 2, k)
    return (f'<figure style="margin: 0; display: flex; flex-direction: column; align-items: center; gap: 8px"><div class="tile" style="width: 152px; height: 212px; display: flex; align-items: center; justify-content: center">{g.svg(4, PALS["dark"])}</div>'
            f'<figcaption style="font-size: 12px; color: var(--t2)">{esc(label)}</figcaption></figure>')


shelves = [shelf_tile({}, 'shelf · 0 of 96'), shelf_tile(filed_of(m2), 'shelf · 38 · 471 filed'), shelf_tile(filed_of(m3), 'shelf · 94 · 1,164 filed'),
           shelf_tile(filed_of(m4), 'shelf · 95 · 1,176 filed')]
body = f'''<div style="padding: 36px 48px; display: flex; flex-direction: column; gap: 28px">
<div style="display: grid; grid-template-columns: repeat(7, 156px); gap: 18px 24px">{"".join(origin_tiles)}</div>
<div style="display: flex; gap: 24px; align-items: flex-end">{"".join(state_tiles)}</div>
<div style="display: flex; gap: 24px; align-items: flex-end">{"".join(shelves)}</div>
</div>'''
save('QueuePropsSheet.dc.html', 'Queue · G · props: one book per origin, the ribbon, cart, crate and shelf', 1440, 970, page('Queue props', 1440, 970, body))

# ================================================================== Queue H. palettes and weather
RESERVED = ['#E5484D', '#F59E0B', '#B45309', '#F87171', '#B91C1C', '#22C55E', '#15803D', '#0A84FF', '#007AFF', '#6FCF6A', '#B8EBA6', '#F28BAE', '#8896FF', '#3F9E57', '#8A2E55']
DELIBERATE = {'d', 'n', 's', 'j'}
bad = []
for k, (dk, lt, role) in DESK.items():
    for hx in (dk, lt):
        if hx.upper() in RESERVED and k not in DELIBERATE:
            bad.append((k, hx))
for oid, name, kind, c_, s_, f in BOOKS:
    for hx in (c_, s_):
        if hx.upper() in RESERVED:
            bad.append((oid, hx))
assert not bad, bad


def sw(hx):
    return f'<span style="width: 18px; height: 18px; border-radius: 4px; background: {hx}; box-shadow: inset 0 0 0 1px var(--ringStrong); flex: none"></span>'


desk_rows = ''.join(f'<div style="display: flex; align-items: center; gap: 8px; height: 26px">{sw(dk)}{sw(lt)}<span style="font: 600 12px ui-monospace, Menlo, monospace; width: 18px">{esc(k)}</span>'
                    f'<span style="font: 12px ui-monospace, Menlo, monospace; color: var(--t2); width: 128px">{dk}{" " + lt if lt != dk else ""}</span><span style="font-size: 12px; color: var(--t3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis">{esc(role)}</span></div>'
                    for k, (dk, lt, role) in DESK.items())
book_rows = ''.join(f'<div style="display: flex; align-items: center; gap: 8px; height: 26px">{sw(c_)}{sw(s_)}<span style="font-size: 12px; width: 118px">{esc(name)}</span>'
                    f'<span style="font: 12px ui-monospace, Menlo, monospace; color: var(--t2); width: 128px">{c_} {s_}</span><span style="font-size: 12px; color: var(--t3); white-space: nowrap">{esc(f)}</span></div>'
                    for oid, name, kind, c_, s_, f in BOOKS)
wtiles = []
for wk in ['curtains', 'night', 'dawn', 'clear', 'fair', 'overcast', 'storm']:
    gg = G(41, 38)
    window(gg, wk, x0=4, y0=4)
    wtiles.append(f'<figure style="margin: 0; display: flex; flex-direction: column; align-items: center; gap: 8px"><div class="tile" style="width: 140px; height: 132px; display: flex; align-items: center; justify-content: center">{gg.svg(3, PALS["dark"])}</div>'
                  f'<figcaption style="font-size: 12px; color: var(--t2)">{esc(wk)}</figcaption></figure>')
for lit in (False, True):
    gg = G(24, 46)
    for y in range(46):
        for x in range(24):
            pass
    tmp = G(RW, RH)
    lamp(tmp, lit, x=4)
    for y in range(4, 52):
        for x in range(0, 24):
            k = tmp.get(x, y)
            if k != '.' and k not in ('W', 'V', 'Y', 'F', 'E', 'H'):
                gg.set(x, y - 6, k)
    wtiles.append(f'<figure style="margin: 0; display: flex; flex-direction: column; align-items: center; gap: 8px"><div class="tile" style="width: 90px; height: 132px; display: flex; align-items: center; justify-content: center">{gg.svg(2, PALS["dark"])}</div>'
                  f'<figcaption style="font-size: 12px; color: var(--t2)">lamp · {"lit" if lit else "dark"}</figcaption></figure>')
body = f'''<div style="padding: 36px 48px; display: flex; flex-direction: column; gap: 28px">
<div style="display: flex; gap: 14px">{"".join(wtiles)}</div>
<div style="display: grid; grid-template-columns: 560px 1fr; gap: 48px">
<div style="display: grid; grid-template-columns: 1fr; gap: 0">{desk_rows}</div>
<div style="display: flex; flex-direction: column">{book_rows}</div></div></div>'''
save('QueuePalette.dc.html', 'Queue · H · DeskPalette v2, BookPalette and the seven weathers', 1440, 1500, page('Room palettes', 1440, 1500, body))

json.dump(BOARDS, open('boards_queue.json', 'w'))
