import os
HERE = os.path.dirname(os.path.abspath(__file__))
import json, sys
from ui import *
from worm import states, responses, mini_set, WORM, PAL as WPAL, frame
from room import room, palette, RW, RH
from fixture import *
from px import G

OUT = os.path.join(HERE, '..', 'boards') + os.sep
BOARDS = []


def save(name, title, w, h, html):
    open(OUT + name, 'w').write(html)
    BOARDS.append({'file': name, 'w': w, 'h': h, 'title': title})


S = states()
R = responses()
M = mini_set()
DARKPAL = palette('dark')
LIGHTPAL = palette('light')


def ftile(g, label, px=4, size=None, bg=None, sub=None):
    size = size or g.w * px + 8
    style = f'background: {bg};' if bg else ''
    return (f'<figure style="margin: 0; display: flex; flex-direction: column; align-items: center; gap: 8px">'
            f'<div class="tile" style="width: {size}px; height: {size}px; display: flex; align-items: center; justify-content: center; {style}">{g.svg(px, WPAL)}</div>'
            f'<figcaption style="font-size: 12px; color: var(--t2); white-space: nowrap">{esc(label)}</figcaption></figure>')


# ================================================================== A. sprite sheet: the states
hero = S['awake'][0][1]
sw = ''.join(
    f'<div style="display: grid; grid-template-columns: 22px 1fr; column-gap: 10px; align-items: center">'
    f'<span style="width: 22px; height: 22px; border-radius: 5px; background: {hexv}; box-shadow: inset 0 0 0 1px var(--ringStrong); grid-row: span 2"></span>'
    f'<span style="font: 600 12px ui-monospace, Menlo, monospace; color: var(--t1)">{k}  {hexv}</span>'
    f'<span style="font-size: 12px; color: var(--t3)">{esc(role)}</span></div>'
    for k, (hexv, role) in WORM.items())
surfaces = [('graphite', '#111213'), ('dark wall', '#372E52'), ('light wall', '#EFE6D8'), ('light base', '#F7F7F5')]
surf_tiles = ''.join(
    f'<figure style="margin: 0; display: flex; flex-direction: column; align-items: center; gap: 8px">'
    f'<div style="width: 104px; height: 104px; border-radius: 10px; background: {c}; box-shadow: inset 0 0 0 1px var(--ring); display: flex; align-items: center; justify-content: center">{hero.svg(3, WPAL)}</div>'
    f'<figcaption style="font-size: 12px; color: var(--t2)">{esc(n)}</figcaption></figure>' for n, c in surfaces)
order = ['awake', 'sleeping', 'reading', 'digesting', 'happy', 'hungry', 'error', 'curious']
tiles = []
for st in order:
    for lab, g in S[st]:
        if st == 'curious':
            lab = lab.replace('curious', 'curious (menu bar)')
        tiles.append(ftile(g, lab))
body = f'''<div style="padding: 40px 48px; display: flex; flex-direction: column; gap: 32px">
<div style="display: flex; gap: 32px; align-items: stretch">
<div class="tile" style="width: 288px; height: 288px; flex: none; display: flex; align-items: center; justify-content: center">{hero.svg(8, WPAL)}</div>
<div style="display: grid; grid-template-columns: repeat(3, 250px); gap: 14px 22px; align-content: center">{sw}</div>
<div style="display: grid; grid-template-columns: repeat(2, 104px); gap: 14px 14px; align-content: center; margin-left: auto">{surf_tiles}</div>
</div>
<div style="display: grid; grid-template-columns: repeat(9, 136px); gap: 20px 14px">{"".join(tiles)}</div>
</div>'''
save('WormSpriteSheet.dc.html', 'Worm · A · room sprites, the eight states', 1440, 920, page('Bookworm states', 1440, 920, body))

# ================================================================== B. responses (Track Z)
rt = []
for key in ['gaze', 'perk', 'talk', 'sleeptalk', 'gulp', 'gulpread', 'shake', 'expectant', 'eager', 'cheer', 'crouch']:
    for lab, g in R[key]:
        rt.append(ftile(g, lab))
# antenna language: the head only, cropped, at 6 px
ant = [('up · awake', frame()), ('perk · happy, cheer', frame(eyes_='happy', mouth_='grin', ant='perk')), ('flat · hungry', frame(eyes_='half', mouth_='frown', ant='flat', blush_=False)),
       ('cross · curious', frame(mouth_='cat', ant='cross')), ('bent · error', frame(eyes_='x', mouth_='flat', ant='bent', blush_=False)),
       ('lean · gaze left', frame(gaze='l', ant='left')), ('lean · gaze right', frame(gaze='r', ant='right'))]


def head_crop(g):
    c = G(24, 22)
    for y in range(22):
        for x in range(24):
            k = g.get(x + 7, y)
            if k != '.':
                c.set(x, y, k)
    return c


at = ''.join(ftile(head_crop(g), lab, px=6, size=160) for lab, g in ant)
body = f'''<div style="padding: 40px 48px; display: flex; flex-direction: column; gap: 34px">
<div style="display: grid; grid-template-columns: repeat(7, 160px); gap: 12px 30px">{at}</div>
<div style="display: grid; grid-template-columns: repeat(9, 136px); gap: 20px 14px">{"".join(rt)}</div>
</div>'''
save('WormResponses.dc.html', 'Worm · B · response art and the antenna language', 1440, 640, page('Bookworm responses', 1440, 640, body))

# ================================================================== C. menu bar and small sizes
APPLE = '<svg width="14" height="16" viewBox="0 0 14 16" aria-hidden="true"><path d="M9.6 2.6c.6-.7 1-1.7.9-2.6-.9 0-1.9.6-2.5 1.3-.5.6-1 1.6-.9 2.5 1 .1 1.9-.5 2.5-1.2zM12.4 11.4c-.4.9-.6 1.3-1.1 2.1-.7 1.1-1.7 2.4-2.9 2.4-1.1 0-1.4-.7-2.8-.7-1.5 0-1.8.7-2.9.7-1.2 0-2.1-1.2-2.8-2.3C-2 10.6.6 6 3.3 6c1 0 1.9.7 2.6.7.7 0 1.9-.8 3.1-.7.5 0 2 .2 2.9 1.6-2.5 1.5-2.1 5 .5 6.1z" fill="currentColor"></path></svg>'


def menubar(dark, worm_svg, scale=1):
    bg = '#1E1E22' if dark else '#ECECEF'
    fg = '#F5F5F6' if dark else '#141415'
    return f'''<div style="height: {24 * scale}px; box-sizing: border-box; background: {bg}; color: {fg}; display: flex; align-items: center; justify-content: space-between; padding: 0 {12 * scale}px; font-size: {13 * scale}px; border-radius: 8px; box-shadow: inset 0 0 0 1px rgba(127,127,127,.25); zoom: 1">
<div style="display: flex; gap: {18 * scale}px; align-items: center">{APPLE if scale == 1 else ""}<span style="font-weight: 600">Cicada</span><span>File</span><span>Edit</span><span>View</span><span>Window</span><span>Help</span></div>
<div style="display: flex; gap: {14 * scale}px; align-items: center"><button type="button" aria-label="Cicada" style="border: 0; background: none; padding: 0; display: flex">{worm_svg}</button>{icon("search", 14 * scale, fg)}<span>Tue 29 Sep  21:40</span></div></div>'''


bars = []
pairs = [('curious · 3', True), ('sleeping · 1', False), ('curious · 10+', False), ('error', True), ('hungry', True), ('happy', False)]
MD = dict(M)
for n, dark in pairs:
    bars.append(menubar(dark, MD[n].svg(1, WPAL)))
bars2 = []
for n, dark in [('curious · 10+', True), ('error', False), ('sleeping · 2', True), ('hungry', False)]:
    bg = '#1E1E22' if dark else '#ECECEF'
    fg = '#F5F5F6' if dark else '#141415'
    bars2.append(f'''<div style="flex: 1; height: 48px; border-radius: 10px; background: {bg}; color: {fg}; box-shadow: inset 0 0 0 1px rgba(127,127,127,.25); display: flex; align-items: center; justify-content: flex-end; gap: 24px; padding: 0 22px; font-size: 26px">
{MD[n].svg(2, WPAL)}{icon("search", 26, fg)}<span>21:40</span></div>''')
strip = ''.join(
    f'''<figure style="margin: 0; display: flex; flex-direction: column; align-items: center; gap: 8px">
<div class="tile" style="width: 116px; height: 116px; display: flex; align-items: center; justify-content: center">{g.svg(6, WPAL)}</div>
<div style="display: flex; gap: 8px"><div style="width: 30px; height: 24px; border-radius: 5px; background: #1E1E22; display: flex; align-items: center; justify-content: center">{g.svg(1, WPAL)}</div><div style="width: 30px; height: 24px; border-radius: 5px; background: #ECECEF; display: flex; align-items: center; justify-content: center">{g.svg(1, WPAL)}</div></div>
<figcaption style="font-size: 12px; color: var(--t2)">{esc(n)}</figcaption></figure>''' for n, g in M)
sizes = []
for st, px_, sz in [('awake', 1, 44), ('hungry', 1, 44), ('happy', 1, 44), ('reading', 2, 76), ('happy', 2, 76)]:
    g = S[st][0][1]
    sizes.append(ftile(g, f'{st} · {32 * px_} pt', px=px_, size=sz))
body = f'''<div style="padding: 40px 48px; display: flex; flex-direction: column; gap: 30px">
<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px 20px">{"".join(bars)}</div>
<div style="display: flex; gap: 20px">{"".join(bars2)}</div>
<div style="display: grid; grid-template-columns: repeat(10, 116px); gap: 16px 17px">{strip}</div>
<div style="display: flex; gap: 22px; align-items: flex-end">{"".join(sizes)}</div>
</div>'''
save('WormMenuBar.dc.html', 'Worm · C · menu bar (18 cells) and small sizes', 1440, 590, page('Bookworm menu bar', 1440, 590, body))

json.dump(BOARDS, open('boards_worm.json', 'w'))
