"""ONE drain fixture. Every board (pile, cart, crate, shelf, caption, popover, queue view,
Home) is rendered from these numbers, and every moment adds up to the frozen 1,187."""

FROZEN = 1187
BATCH = 25
BATCHES = -(-FROZEN // BATCH)          # 48; the last batch holds 12

ORIGINS = ['claude-code', 'chatgpt-export', 'codex', 'chrome-bookmark', 'apple-notes', 'youtube', 'other']
TOTAL = {'claude-code': 612, 'chatgpt-export': 341, 'codex': 88, 'chrome-bookmark': 96, 'apple-notes': 22, 'youtube': 14, 'other': 14}
CHARS = {'claude-code': 11_000_000, 'chatgpt-export': 2_050_000, 'codex': 1_060_000, 'chrome-bookmark': 144_000,
         'apple-notes': 44_000, 'youtube': 42_000, 'other': 14_000}
OTHER_PARTS = [('Telegram', 6), ('Feeds', 5), ('Calendar', 3)]
NAME = {'claude-code': 'Claude Code', 'chatgpt-export': 'ChatGPT', 'codex': 'Codex', 'chrome-bookmark': 'Chrome bookmarks',
        'apple-notes': 'Apple Notes', 'youtube': 'YouTube', 'other': 'Other sources'}
MARK = {'claude-code': 'claude', 'chatgpt-export': 'chatgptDark', 'codex': 'codexDark', 'chrome-bookmark': 'chrome',
        'apple-notes': 'icon:note', 'youtube': 'youtube', 'other': 'icon:more'}
KIND = {'claude-code': 'Conversations', 'chatgpt-export': 'Conversations', 'codex': 'Conversations', 'chrome-bookmark': 'Pages',
        'apple-notes': 'Notes', 'youtube': 'Videos', 'other': 'Other'}
assert sum(TOTAL.values()) == FROZEN


def moment(filed, read, reading, aside):
    m = {}
    for o in ORIGINS:
        w = TOTAL[o] - filed.get(o, 0) - read.get(o, 0) - reading.get(o, 0) - aside.get(o, 0)
        assert w >= 0, o
        m[o] = dict(filed=filed.get(o, 0), read=read.get(o, 0), reading=reading.get(o, 0), aside=aside.get(o, 0), waiting=w, total=TOTAL[o])
    tot = {k: sum(v[k] for v in m.values()) for k in ('filed', 'read', 'reading', 'aside', 'waiting')}
    assert sum(tot.values()) == FROZEN, tot
    return m, tot


FIRST = moment({}, {}, {}, {})
# batch 20 of 48, Read stage, 14 of its 25 read, one open now
MID = moment({'claude-code': 231, 'chatgpt-export': 161, 'codex': 60, 'chrome-bookmark': 12, 'apple-notes': 4, 'youtube': 2, 'other': 1},
             {'claude-code': 8, 'chatgpt-export': 3, 'codex': 2, 'chrome-bookmark': 1},
             {'chatgpt-export': 1},
             {'chrome-bookmark': 3, 'chatgpt-export': 1})
# batch 48 of 48 (12 items), Notice stage: nothing waiting, 12 read, waiting to file
NEAR = moment({'claude-code': 602, 'chatgpt-export': 338, 'codex': 88, 'chrome-bookmark': 87, 'apple-notes': 22, 'youtube': 14, 'other': 13},
              {'claude-code': 9, 'chrome-bookmark': 3}, {},
              {'chrome-bookmark': 6, 'chatgpt-export': 3, 'claude-code': 1, 'other': 1})
DONE = moment({'claude-code': 611, 'chatgpt-export': 338, 'codex': 88, 'chrome-bookmark': 90, 'apple-notes': 22, 'youtube': 14, 'other': 13},
              {}, {}, {'chrome-bookmark': 6, 'chatgpt-export': 3, 'claude-code': 1, 'other': 1})
ASIDE_REASONS = [('9 parked after two tries', 'the text could not be read'), ('2 failed', 'the engine returned nothing usable')]


def fig(n):
    return f'{n:,}'


def pile_items(m, reading_origin=None):
    return [dict(origin=o if o != 'apple-notes' else 'apple-notes', waiting=v['waiting'] + v['reading'], total=v['total'],
                 chars=CHARS[o], reading=(o == reading_origin)) for o, v in m.items()]


def cart_books(read):
    return min(6, -(-read * 6 // BATCH)) if read else 0


def crate_items(aside):
    return min(3, -(-aside // 4)) if aside else 0


def filed_of(m):
    return {o: v['filed'] for o, v in m.items()}
