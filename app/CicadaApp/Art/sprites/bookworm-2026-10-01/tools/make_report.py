#!/usr/bin/env python3
"""Describe actual exported timings and inventory the asset directory; no art changes."""
import json
from itertools import groupby
from pathlib import Path

ART=Path(__file__).resolve().parent.parent
ROOT=ART.parents[4]
RES=ART.parents[2]/'Sources/CicadaApp/Resources/sprites'
IDLE={
    'awake':'Quiet breathing, delayed head rise, tail follow-through, irregular blinks and a double blink.',
    'reading':'Ten lines, three uneven page flips and blinks, close, tuck, next cover rises, open.',
    'sleeping':'Two four-second breaths; small z, paired medium z, then three sizes; palette fade and final-frame size step.',
    'digesting':'Two chews, swallow bulge, satisfied smile.',
    'happy':'Breathing, two blinks, lens glint, small head turn.',
    'hungry':'Heavy breathing, droop, slow lids and a small yawn.',
    'error':'Centered black diagonal X eyes, falling sweat drop, brief tremble; worried brows.',
    'curious':'Raised brow, floating question mark, small head turn and irregular blinks.',
}
ACTION={
    'attentive':'Held gaze, two irregular blinks and a side/up glance.',
    'expectant':'Raised brows and open mouth; brief anticipatory crouch.',
    'eager':'Crouch, two-pixel hop, overlap and landing.',
    'perk':'Crouch, bright-eyed two-pixel hop and settle.',
    'talk':'Six mouth poses with a small head bob.',
    'gulp':'Mouth opens, paper enters, bulge moves down the neck, smile.',
    'shake':'Alternating head offsets with sad brows; settles in its original gaze.',
    'cheer':'Crouch, two/three-pixel rise with sparkle, landing squash and settle.',
    'intro':'Close the book, open-mouth yawn, settle into a slump.',
    'outro':'Stretch upward, yawn, reopen eyes and return to sitting.',
}
SMALL={
    'awake':'Held cross pupils, blink, return, one-pixel bob and settle.',
    'sleeping':'Closed lids; tiny z rises through four held poses.',
    'digesting':'Alternating neck/bob poses.',
    'happy':'Held pose, one-pixel bob, return, sparkle and settle.',
    'curious':'Held pose, raised brow, bob and return; badge corner stays clear of glasses.',
    'hungry':'Heavy lids, droop, hold and return.',
    'reading':'Tiny open book, left/right pupil glance, moving page line and return.',
    'error':'Black diagonal X eyes and cyan drop; neck tremble and falling drop.',
}
rows=['# Worm tag timings — fix pass, 2026-10-01','',
      'Generated from the exported JSON. Times are integer milliseconds, in frame order. `N × ms` abbreviates consecutive equal holds. All tags play forward.','']
for js in sorted(RES.glob('bookworm-*.json')):
    d=json.loads(js.read_text());state=js.stem.removeprefix('bookworm-')
    rows.extend(['## '+js.stem,'','| Tag | Frames | Per-frame ms | Total ms | Action |',
                 '|---|---:|---|---:|---|'])
    for t in d['meta']['frameTags']:
        ms=[f['duration'] for f in d['frames'][t['from']:t['to']+1]]
        chunks=[]
        for value,group in groupby(ms):
            n=len(list(group));chunks.append(f'{n} × {value}' if n>1 else str(value))
        family=t['name'].split('@')[0].split('.')[0]
        action=SMALL[t['name']] if state.startswith('small') else (IDLE[state] if family=='idle' else ACTION[family])
        if state=='sleeping' and family=='talk':action='Closed lids and tiny mumbling mouth; a pale z on the fifth pose.'
        if '.' in t['name']:action+=' Gaze: '+t['name'].split('@')[0].split('.')[1]+'.'
        if state=='reading':
            cover=int(t['name'].split('@')[1]) if '@' in t['name'] else 1
            action+=f' Cover {cover}.'
        rows.append(f'| `{t["name"]}` | {len(ms)} | '+', '.join(chunks)+f' | {sum(ms)} | {action} |')
    rows.append('')
rows.extend(['## Unbundled review demos','',
             'Frame counts below describe the assembled animation before GIF duplicate-frame merging.','',
             '| File / generator tag | Frames | Per-frame ms | Total ms | Action |',
             '|---|---:|---|---:|---|',
             '| `bookworm-mad-demo@6x.gif` / `mad` | 34 | Same holds as awake `idle` above | 13200 | Awake breathing/blinks with the unused mad brows. |',
             '| `bookworm-reading-cycle@6x.gif` / `cycle` | 255 | The three reading idle hold arrays above, in cover order | 65520 | Blue, crimson and ochre reading cycles joined with matching cover seams. |',''])
(ART/'TAG_TIMINGS.md').write_text('\n'.join(rows)+'\n')
paths=[]
for f in ART.rglob('*'):
    if not f.is_file() or '__pycache__' in f.parts:continue
    if 'reference' in f.relative_to(ART).parts:continue
    paths.append(f.relative_to(ROOT).as_posix())
paths.extend(f.relative_to(ROOT).as_posix() for f in RES.glob('bookworm-*') if f.is_file())
paths.extend(['docs/goals/TODO.md','docs/goals/memory-evolution.md',
              'docs/architecture/app.md','docs/specs/2026-10-01-bookworm-sprites-spec.md'])
paths.append((ART/'FILE_INVENTORY.txt').relative_to(ROOT).as_posix())
(ART/'FILE_INVENTORY.txt').write_text('\n'.join(sorted(set(paths)))+'\n')
print(f'Timings for {sum(len(json.loads(p.read_text())["meta"]["frameTags"]) for p in RES.glob("bookworm-*.json"))} tags; {len(set(paths))} files listed')
