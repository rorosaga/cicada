import json
from ui import *
from worm import states, PAL as WPAL
from fixture import *
import boards_queue as BQ
from boards_queue import save, BOARDS, scene, room_html, twin_caption, stage_strip, sleep_card, sleep_page, ctrl, S

m2, t2 = MID
BOARDS.clear()

# reading-job fixture for the 96 Chrome pages (its own job, its own noun)
PAGES = dict(read=31, desc=12, login=9, failed=6, waiting=38)
assert sum(PAGES.values()) == 96
VIDEOS = dict(watched=2, transcript=1, agent=1, meta=10)
assert sum(VIDEOS.values()) == 14


def glyph(state, size=14):
    return {
        'filed': icon('check', size, 'var(--t2)', 'Filed'),
        'read': icon('half', size, 'var(--t2)', 'Read, waiting to file'),
        'reading': icon('openbook', size, 'var(--t1)', 'Being read'),
        'waiting': icon('dot', size, 'var(--t3)', 'Waiting'),
        'aside': icon('warn', size, 'var(--warning)', 'Set aside'),
    }[state]


WORD = {'filed': 'Filed', 'read': 'Read', 'reading': 'Being read', 'waiting': 'Waiting', 'aside': 'Set aside'}


def breakdown(v):
    parts = []
    for k, w in (('filed', 'filed'), ('read', 'read'), ('reading', 'being read'), ('waiting', 'waiting'), ('aside', 'set aside')):
        if v[k]:
            parts.append(f'{fig(v[k])} {w}')
    return ' · '.join(parts)


def mini_bar(v, w=120):
    fw = round(w * v['filed'] / v['total']); rw = round(w * (v['read'] + v['reading']) / v['total'])
    return (f'<span role="img" aria-label="{v["filed"]} of {v["total"]} filed" style="width: {w}px; height: 4px; border-radius: 2px; background: var(--badge); display: inline-flex; overflow: hidden; flex: none">'
            f'<span style="width: {fw}px; background: var(--t1)"></span><span style="width: {rw}px; background: var(--t3)"></span></span>')


def mk(o, size=16):
    k = MARK[o]
    return icon(k[5:], size, 'var(--t2)') if k.startswith('icon:') else mark(k, size)


def group(o, open_, extra=''):
    v = m2[o]
    chev = icon('chevd' if open_ else 'chev', 11, 'var(--t3)')
    name = NAME[o] if o != 'other' else 'Other sources'
    sub = f'<span class="meta">Telegram, Feeds, Calendar</span>' if o == 'other' else ''
    return (f'<div class="row" style="height: 40px"><button class="tbtn" type="button" aria-expanded="{"true" if open_ else "false"}" aria-label="{esc(name)}" style="padding: 0; width: 16px">{chev}</button>{mk(o)}'
            f'<span style="font-weight: 600; color: var(--t1); white-space: nowrap">{esc(name)}</span>{sub}<span style="flex: 1"></span>'
            f'<span class="meta" style="white-space: nowrap">{esc(breakdown(v))}</span>{mini_bar(v)}{extra}</div>')


def item(state, title, meta, lead=None, tag=None, selected=False, hover=False, actions=''):
    bg = 'background: var(--selected);' if selected else ('background: var(--hover);' if hover else '')
    lead_html = lead if lead else '<span style="width: 14px; flex: none"></span>'
    tag_html = f'<span class="meta" style="display: inline-flex; align-items: center; gap: 5px; width: 170px; justify-content: flex-end">{tag}</span>' if tag else '<span style="width: 170px"></span>'
    right = actions if actions else f'<span class="s" style="width: 86px">{esc(WORD[state])}</span>'
    return (f'<li class="row" style="{bg} padding-left: 36px">{glyph(state)}{lead_html}<span class="t">{esc(title)}</span>'
            f'<span class="m" style="width: 130px; text-align: right">{esc(meta)}</span>{tag_html}{right}</li>')


def more(n):
    return f'<li style="padding: 2px 0 6px 64px; list-style: none"><button class="link" type="button" style="font-size: 12px">Show {fig(n)} more</button></li>'


def section(title, n):
    return f'<div style="display: flex; align-items: baseline; gap: 8px; padding: 16px 10px 4px"><span class="lbl">{esc(title)}</span><span class="lbl">{esc(n)}</span></div>'


def rail(active='moon'):
    items = [('home', 'Home'), ('graph', 'Graph'), ('clusters', 'Clusters'), ('feed', 'Feed'), ('moon', 'Sleep'), ('inbox', 'Inbox'), ('sources', 'Sources'), ('projects', 'Projects')]
    cells = []
    for it, n in items:
        on = it == active
        badge = '<span style="position: absolute; right: 1px; top: 2px; min-width: 15px; height: 15px; border-radius: 8px; background: var(--badge); font-size: 10px; font-weight: 600; color: var(--t1); display: flex; align-items: center; justify-content: center; padding: 0 4px; box-shadow: 0 0 0 2px var(--rail)">3</span>' if it == 'inbox' else ''
        cells.append(f'<button type="button" aria-label="{n}" {"aria-current=\"page\"" if on else ""} style="position: relative; width: 36px; height: 36px; border: 0; border-radius: 9px; display: flex; align-items: center; justify-content: center; background: {"var(--selected)" if on else "none"}; color: {"var(--t1)" if on else "var(--t3)"}">{icon(it, 18)}{badge}</button>')
    foot = (f'<button type="button" aria-label="Settings" style="width: 36px; height: 36px; border: 0; background: none; color: var(--t3); display: flex; align-items: center; justify-content: center">{icon("gear", 18)}</button>'
            f'<button type="button" aria-label="Appearance" style="width: 36px; height: 36px; border: 0; background: none; color: var(--t3); display: flex; align-items: center; justify-content: center">{icon("sunmoon", 18)}</button>')
    return f'<nav style="width: 56px; background: var(--rail); display: flex; flex-direction: column; align-items: center; padding: 10px 0; gap: 6px; box-shadow: inset -1px 0 0 var(--ring)">{"".join(cells)}<span style="flex: 1"></span>{foot}</nav>'


def titlebar():
    lights = ''.join(f'<span style="width: 12px; height: 12px; border-radius: 6px; background: {c}"></span>' for c in ('#FF5F57', '#FEBC2E', '#28C840'))
    return f'''<div style="height: 52px; display: flex; align-items: center; padding: 0 16px; gap: 14px; background: var(--rail); box-shadow: inset 0 -1px 0 var(--ring); position: relative">
<div style="display: flex; gap: 8px">{lights}</div><button type="button" aria-label="Show labels" style="width: 28px; height: 28px; border: 0; background: none; color: var(--t3); display: flex; align-items: center; justify-content: center">{icon('sidebar', 16)}</button>
<div style="position: absolute; left: 50%; transform: translateX(-50%); display: flex; gap: 8px; align-items: center">
<button class="menu" type="button" style="height: 30px"><span style="width: 8px; height: 8px; border-radius: 4px; background: #6FCF6A"></span>My memory{icon('chevd', 10)}</button>
<button class="menu" type="button" style="height: 30px; width: 380px; justify-content: flex-start; color: var(--t3)">{icon('search', 13)}<span style="flex: 1; text-align: left">Search your memory</span><span class="kbd">⌘K</span></button></div>
<span style="flex: 1"></span><button class="btnn" type="button" aria-label="Help for What’s waiting" style="width: 26px; height: 26px; padding: 0; justify-content: center; border-radius: 13px">?</button></div>'''


# ================================================================== QueueView: What's waiting, full window
lk = mark('linkedin', 14)
rows = [section('Being read', 'batch 20 of 48'),
        '<ul style="list-style: none; margin: 0; padding: 0">' + item('reading', 'Trip planning for alpha-project', 'Sep 3 · 18k characters', lead=mark('chatgptDark', 14)).replace('padding-left: 36px', 'padding-left: 10px') + '</ul>',
        section('Conversations', fig(TOTAL['claude-code'] + TOTAL['chatgpt-export'] + TOTAL['codex'])),
        group('claude-code', True),
        '<ul style="list-style: none; margin: 0; padding: 0">',
        item('filed', 'Sync engine refactor for alpha-project', 'Sep 12 · 14k characters'),
        item('read', 'Onboarding copy pass', 'Sep 10 · 6k characters'),
        item('waiting', 'Pricing notes for Helios Labs', 'Sep 9 · 9k characters', hover=True),
        more(TOTAL['claude-code'] - 3), '</ul>',
        group('chatgpt-export', False), group('codex', False),
        section('Pages', fig(TOTAL['chrome-bookmark'])),
        group('chrome-bookmark', True),
        '<ul style="list-style: none; margin: 0; padding: 0">',
        item('filed', 'bob-example · profile', 'linkedin.com · Sep 3', lead=lk, tag=icon('lock', 12, 'var(--warning)') + 'Sign-in page', selected=True),
        item('aside', 'Helios Labs careers', 'helios-labs.example · Aug 28', lead=mark('chrome', 14), tag='Parked after two tries',
             actions='<span style="width: 86px; display: flex; justify-content: flex-end"><button class="btns" type="button">' + icon('retry', 12) + 'Retry</button></span>'),
        item('waiting', 'Pixel fonts for small sizes', 'fonts.example · Aug 20', lead=mark('chrome', 14), tag='Only a description'),
        more(TOTAL['chrome-bookmark'] - 3), '</ul>',
        section('Notes', fig(TOTAL['apple-notes'])), group('apple-notes', False),
        section('Videos', fig(TOTAL['youtube'])), group('youtube', True, '<button class="link" type="button" style="font-size: 12px; white-space: nowrap">Choose videos in the Feed ›</button>'),
        '<ul style="list-style: none; margin: 0; padding: 0">',
        item('filed', 'Building a pixel renderer in Swift', 'Sep 21 · 38 min', lead=mark('youtube', 14), tag='Watched by an agent'),
        item('waiting', 'How spaced repetition works', 'Sep 18 · 12 min', lead=mark('youtube', 14), tag='Transcript read'),
        more(TOTAL['youtube'] - 2), '</ul>',
        section('Other', fig(TOTAL['other'])), group('other', False)]

tabs = [('All', FROZEN, True), ('Conversations', TOTAL['claude-code'] + TOTAL['chatgpt-export'] + TOTAL['codex'], False), ('Pages', 96, False),
        ('Notes', 22, False), ('Videos', 14, False), ('Other', 14, False)]
assert sum(n for _, n, _ in tabs[1:]) == FROZEN
tabs_html = ''.join(f'<button class="tab" role="tab" type="button" aria-selected="{"true" if on else "false"}">{esc(n)} <span style="color: var(--t3)">{fig(c)}</span></button>' for n, c, on in tabs)
list_col = f'''<main style="flex: 1; min-width: 0; display: flex; flex-direction: column; padding: 16px 24px 0; gap: 12px; overflow: hidden">
<div><button class="tbtn" type="button" style="padding-left: 0">{icon('chevl', 12)}Sleep</button></div>
<div style="display: flex; align-items: flex-end; justify-content: space-between">
<div style="display: flex; flex-direction: column; gap: 4px"><h1 style="margin: 0; font: 600 24px {DISPLAY}; letter-spacing: -0.4px">What’s waiting</h1>
<div class="meta">Everything waiting to be read, and what happened to it.</div></div>
<div style="display: flex; align-items: center; gap: 10px">{S['sleeping'][0][1].svg(1, WPAL)}<span class="meta">{twin_caption(t2).replace('justify-content: center', 'justify-content: flex-end')}</span></div></div>
<div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 2px">
<div class="tabs" role="tablist" aria-label="Kind">{tabs_html}</div>
<div style="display: flex; gap: 8px; align-items: center"><button class="menu" type="button" aria-haspopup="menu">{icon('filter', 12)}Any state{icon('chevd', 9)}</button><button class="menu" type="button" aria-haspopup="menu">All sources{icon('chevd', 9)}</button>
<span style="position: relative; display: flex; align-items: center"><span style="position: absolute; left: 9px; display: flex; color: var(--t3)">{icon('search', 12)}</span><input class="field" type="search" aria-label="Filter the queue" placeholder="Filter"></span></div></div>
<div style="display: flex; flex-direction: column; box-shadow: inset 0 1px 0 var(--ring)">{"".join(rows)}</div>
</main>'''
detail = f'''<aside aria-label="bob-example · profile" style="width: 400px; flex: none; background: var(--pane); box-shadow: inset 1px 0 0 var(--ring); padding: 22px 24px; display: flex; flex-direction: column; gap: 20px">
<div style="display: flex; align-items: flex-start; gap: 12px">{mark('linkedin', 28)}<div style="flex: 1; display: flex; flex-direction: column; gap: 3px">
<div style="font: 600 18px {DISPLAY}; letter-spacing: -0.2px">bob-example · profile</div><div style="font: 12px ui-monospace, Menlo, monospace; color: var(--t3)">linkedin.com/in/bob-example</div></div>
<button type="button" aria-label="Close" style="width: 28px; height: 28px; border: 0; background: none; color: var(--t3); display: flex; align-items: center; justify-content: center">{icon('x', 13)}</button></div>
<div style="display: flex; flex-direction: column; gap: 10px">
<div style="display: flex; gap: 10px; align-items: flex-start">{glyph('filed', 16)}<div><div style="font-size: 13px; font-weight: 600">Filed</div><div class="body" style="line-height: 1.45">Sep 29, batch 12. Only the bookmark was filed: its title, its link and the folder it sits in.</div></div></div>
<div style="display: flex; gap: 10px; align-items: flex-start">{icon('lock', 16, 'var(--warning)', 'Sign-in page')}<div><div style="font-size: 13px; font-weight: 600">The page asks you to sign in</div><div class="body" style="line-height: 1.45">LinkedIn shows it only after a login. Cicada never reads behind a login, and never hands a LinkedIn page to an agent.</div></div></div></div>
<div style="display: flex; gap: 8px"><button class="btns" type="button">{icon('ext', 12)}Open in browser</button><button class="btns" type="button">Take it out of the queue</button></div>
<div style="display: flex; flex-direction: column; gap: 8px"><div class="lbl">Where it came from</div>
<div style="display: flex; align-items: center; gap: 10px; font-size: 13px">{mark('chrome', 16)}<span>Chrome bookmarks › People</span><span style="flex: 1"></span><span class="meta">saved Sep 3</span></div></div>
<div style="display: flex; flex-direction: column; gap: 8px"><div class="lbl">What happened</div>
<div style="display: grid; grid-template-columns: 96px 1fr; gap: 6px 10px; font-size: 13px; color: var(--t2)">
<span class="meta">Sep 29 21:12</span><span>Filed with batch 12.</span>
<span class="meta">Sep 28 21:40</span><span>Found a sign-in page. Nothing was read.</span>
<span class="meta">Sep 3 09:12</span><span>Saved from Chrome.</span></div></div>
<div style="display: flex; flex-direction: column; gap: 8px"><div class="lbl">Also waiting on you</div>
<div style="display: flex; align-items: center; gap: 10px; font-size: 13px">{icon('lock', 14, 'var(--warning)')}<span style="flex: 1">{PAGES['login'] - 1} more sign-in pages</span><button class="link" type="button">Show ›</button></div>
<div style="display: flex; align-items: center; gap: 10px; font-size: 13px">{icon('warn', 14, 'var(--warning)')}<span style="flex: 1">{PAGES['failed']} pages couldn’t load</span><button class="link" type="button">Show ›</button></div></div>
</aside>'''
body = f'''<div class="t-dark surf" style="display: flex; flex-direction: column; height: 100%">{titlebar()}
<div style="flex: 1; display: flex; min-height: 0">{rail()}{list_col}{detail}</div></div>'''
save('QueueView.dc.html', 'Queue · I · What’s waiting, full window (mid-drain)', 1440, 900, page('What’s waiting', 1440, 900, body))

# ================================================================== QueueDetails: Sleep with Details open
v_ = t2


def drain_bar(t, w=760):
    fw = round(w * t['filed'] / FROZEN); rw = round(w * (t['read'] + t['reading']) / FROZEN)
    return (f'<div role="img" aria-label="{t["filed"]} of {FROZEN} filed" style="height: 6px; border-radius: 3px; background: var(--badge); display: flex; overflow: hidden; width: {w}px">'
            f'<span style="width: {fw}px; background: var(--t1)"></span><span style="width: {rw}px; background: var(--t3)"></span></div>')


def job_row(icon_name, title, noun_line, bar_frac, action, open_=False, inner=''):
    fw = round(200 * bar_frac)
    return f'''<div style="display: flex; flex-direction: column">
<div class="row" style="height: 40px; padding: 0"><button class="tbtn" type="button" aria-expanded="{"true" if open_ else "false"}" style="padding: 0 4px 0 0">{icon('chevd' if open_ else 'chev', 11, 'var(--t3)')}</button>{icon(icon_name, 16, 'var(--t2)')}
<span style="font-weight: 600; white-space: nowrap">{esc(title)}</span><span style="flex: 1"></span><span class="meta">{esc(noun_line)}</span>
<span style="width: 200px; height: 4px; border-radius: 2px; background: var(--badge); display: inline-flex; overflow: hidden"><span style="width: {fw}px; background: var(--t1)"></span></span>{action}</div>{inner}</div>'''


origin_rows = ''.join(
    f'<li class="row" style="height: 34px; padding-left: 30px">{mk(o, 14)}<span style="width: 150px">{esc(NAME[o])}</span><span class="meta" style="flex: 1">{esc(breakdown(m2[o]))}</span>{mini_bar(m2[o], 100)}</li>' for o in ORIGINS)
aside_rows = f'''<li class="row" style="height: 34px; padding-left: 30px">{icon('warn', 14, 'var(--warning)', 'Set aside')}<span style="width: 150px">3 Chrome bookmarks</span><span class="meta" style="flex: 1">Parked after two tries: the page text could not be read.</span><button class="btns" type="button">{icon('retry', 12)}Retry</button></li>
<li class="row" style="height: 34px; padding-left: 30px">{icon('warn', 14, 'var(--warning)', 'Set aside')}<span style="width: 150px">1 ChatGPT chat</span><span class="meta" style="flex: 1">Failed: the engine returned nothing usable.</span><button class="btns" type="button">{icon('retry', 12)}Retry</button></li>'''
waiting = job_row('chat', 'Everything captured', f'{fig(t2["filed"])} of {fig(FROZEN)} filed', t2['filed'] / FROZEN, '', True,
                  f'<ul style="list-style: none; margin: 0; padding: 0">{origin_rows}{aside_rows}</ul>')
pages = job_row('page', 'Pages waiting to be read', f'{PAGES["read"]} of 96 read · {PAGES["login"]} need you to sign in', PAGES['read'] / 96,
                '<button class="link" type="button" style="font-size: 12px; white-space: nowrap">Reading ›</button>')
videos = job_row('video', 'Videos waiting', f'{VIDEOS["watched"] + VIDEOS["transcript"]} of 14 watched or read · {VIDEOS["agent"]} picked up by an agent', (VIDEOS["watched"] + VIDEOS["transcript"]) / 14,
                 '<button class="link" type="button" style="font-size: 12px; white-space: nowrap">Choose videos ›</button>')
details = f'''<div style="width: 760px; display: flex; flex-direction: column; gap: 22px; padding: 0 0 0 0">
<section style="display: flex; flex-direction: column; gap: 10px"><div class="lbl">This run</div>
{drain_bar(t2)}
<div style="display: flex; justify-content: space-between; font-size: 12px; color: var(--t2)"><span>{fig(t2['filed'])} filed · {t2['read']} read, waiting to file · {t2['reading']} being read · {fig(t2['waiting'])} waiting · {t2['aside']} set aside</span><span class="meta">412 calls made</span></div>
<div class="meta">Started by you at 20:59 · batches of 25 · Claude plan · Haiku</div></section>
<section style="display: flex; flex-direction: column; gap: 2px"><div class="lbl" style="padding-bottom: 6px">What’s waiting</div>{waiting}{pages}{videos}
<div style="padding: 6px 0 0 20px"><button class="link" type="button" style="font-size: 12px">Open What’s waiting ›</button></div></section>
<section style="display: flex; flex-direction: column; gap: 2px"><div class="lbl" style="padding-bottom: 6px">Past nights</div>
<div class="row" style="height: 36px; padding: 0">{icon('chev', 11, 'var(--t3)')}<span style="font-weight: 600">Tonight</span><span class="meta">a run of 48 batches · 19 done</span><span style="flex: 1"></span><span class="meta">started 20:59</span></div>
<div class="row" style="height: 36px; padding: 0">{icon('chev', 11, 'var(--t3)')}<span style="font-weight: 600">Sep 28</span><span class="meta">one cycle · 25 read · 9 pages updated</span><span style="flex: 1"></span><span class="meta">03:00 · scheduled</span></div>
</section></div>'''
g, pl = scene('dark', 'night', True, S['sleeping'][0][1], m2, 'chatgpt-export', dots=1)
card = sleep_card(room_html(g, pl, 'dark', 'Night in the study room'), 'Reading batch 20 of 48.', 'Now: a ChatGPT chat about trip planning for alpha-project.',
                  ctrl('Pause', 'pause', engine='Claude plan · Haiku'), 'Started by you at 20:59 · stops at the plan’s limit', twin_caption(t2) + stage_strip(0))
save('QueueDetails.dc.html', 'Queue · J · Sleep with Details open: this run, three jobs, past nights', 900, 1360, page('Sleep details', 900, 1360, sleep_page(card, details)))

# ================================================================== Home: Reading and Needs you
m1, t1 = FIRST


def home_col(variant):
    if variant == 'idle':
        today = f'''<div class="row" style="padding: 0; height: 36px"><span style="font-size: 13px">{fig(FROZEN)} captured today</span><span style="flex: 1"></span>{mark('claude', 14)}<span class="meta">612</span>{mark('chatgptDark', 14)}<span class="meta">341</span>{mark('chrome', 14)}<span class="meta">96</span></div>'''
        reading = f'''<div class="row" style="padding: 0; height: 52px; gap: 14px">{S['reading'][0][1].svg(1, WPAL)}<span style="font-size: 13px; color: var(--t1)">None read yet</span><span style="flex: 1"></span><button class="link" type="button" style="font-size: 12px">Open Sleep ›</button></div>'''
        needs = [('inbox', 'var(--t2)', 'Is Helios Labs still a client?', 'Inbox', '2h')]
    else:
        today = f'''<div class="row" style="padding: 0; height: 36px"><span style="font-size: 13px">23 captured today</span><span style="flex: 1"></span>{mark('claude', 14)}<span class="meta">14</span>{mark('chatgptDark', 14)}<span class="meta">6</span>{mark('chrome', 14)}<span class="meta">3</span></div>'''
        fw = round(560 * t2['filed'] / FROZEN); rw = round(560 * (t2['read'] + t2['reading']) / FROZEN)
        reading = f'''<div class="row" style="padding: 0; height: 60px; gap: 14px">{S['sleeping'][0][1].svg(1, WPAL)}<div style="flex: 1; display: flex; flex-direction: column; gap: 8px">
<div style="display: flex; align-items: baseline; gap: 8px"><span style="font-size: 13px; color: var(--t1)">Batch 20 of 48</span><span class="meta">{fig(t2['filed'])} of {fig(FROZEN)} filed</span><span style="flex: 1"></span><button class="link" type="button" style="font-size: 12px">Open Sleep ›</button></div>
<div role="img" aria-label="{t2['filed']} of {FROZEN} filed" style="height: 4px; border-radius: 2px; background: var(--badge); display: flex; overflow: hidden; width: 560px"><span style="width: {fw}px; background: var(--t1)"></span><span style="width: {rw}px; background: var(--t3)"></span></div></div></div>'''
        needs = [('inbox', 'var(--t2)', 'Still working on alpha-project?', 'Inbox', '3d'),
                 ('lock', 'var(--warning)', f'{PAGES["login"]} pages need you to sign in', 'Chrome bookmarks', '1d'),
                 ('warn', 'var(--warning)', f'{PAGES["failed"]} pages couldn’t load', 'Chrome bookmarks', '2d')]
    nrows = ''.join(f'<div class="row" style="padding: 0; height: 36px">{icon(ic, 14, col)}<span style="flex: 1; color: var(--t2)">{esc(tx)}</span><span class="meta">{esc(src)}</span><span class="meta" style="width: 28px; text-align: right">{esc(age)}</span></div>' for ic, col, tx, src, age in needs)
    return f'''<div style="width: 760px; display: flex; flex-direction: column">
<div class="lbl" style="padding: 8px 0 2px">Today</div>{today}
<div class="lbl" style="padding: 18px 0 2px">Reading</div>{reading}
<div style="display: flex; align-items: center; justify-content: space-between; padding: 18px 0 2px"><span class="lbl">Needs you</span><button class="link" type="button" style="font-size: 12px">Open Inbox ›</button></div>{nrows}</div>'''


body = f'''<div style="padding: 40px 48px; display: grid; grid-template-columns: 760px 760px; gap: 72px">{home_col('idle')}{home_col('run')}</div>'''
save('QueueHomeCompact.dc.html', 'Queue · K · Home: Reading and Needs you, idle and running', 1688, 370, page('Home reading rows', 1688, 370, body))

json.dump(BOARDS, open('boards_view.json', 'w'))
