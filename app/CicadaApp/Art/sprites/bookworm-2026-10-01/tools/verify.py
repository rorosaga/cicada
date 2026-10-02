#!/usr/bin/env python3
"""Complete sprite verifier; --worm-only keeps Run A independently usable."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw

ART = Path(__file__).resolve().parent.parent
RES = ART.parents[2] / 'Sources/CicadaApp/Resources/sprites'
ASE = os.environ.get('ASEPRITE', '/Applications/Aseprite.app/Contents/MacOS/aseprite')
COMMON = ['idle', 'attentive.left', 'attentive.center', 'attentive.right',
          'expectant.left', 'expectant.center', 'expectant.right', 'eager',
          'perk.left', 'perk.center', 'perk.right', 'talk.left', 'talk.center',
          'talk.right', 'gulp.center', 'shake.left', 'shake.center', 'shake.right']
SMALL = ['awake', 'sleeping', 'digesting', 'happy', 'curious', 'hungry', 'reading', 'error']
EXPECTED = {f'bookworm-{s}': COMMON for s in ['awake', 'hungry']}
EXPECTED.update({'bookworm-happy': COMMON + ['cheer.center'],
                 'bookworm-reading': [t + suffix for suffix in ['', '@2', '@3'] for t in COMMON],
                 'bookworm-digesting': ['idle', 'expectant.center', 'eager', 'talk.center', 'gulp.center', 'shake.center', 'cheer.center'],
                 'bookworm-sleeping': ['idle', 'talk.center', 'intro', 'outro'],
                 'bookworm-error': ['idle'], 'bookworm-curious': ['idle'],
                 'bookworm-small': SMALL})
BANNED = {0x22C55E, 0xEF4444, 0xF59E0B, 0x3B82F6, 0x4A9EFF, 0x8B5CF6, 0x3BD97A, 0x6B7280, 0x999999}

# Independent transcription of the binding timing tables, not the generator registry.
IDLE_MS = {
    'awake': [700,180,220,600,180,260,900,60,90,60,500,180,220,700,180,260,600,120,120,700,90,120,90,1570,60,90,60,1400,180,220,600,180,260,1450],
    'happy': [700,180,220,600,180,260,200,60,90,60,290,70,70,70,70,600,60,90,60,500,180,220,700,180,260,300,900],
    'hungry': [900,260,300,800,260,360,700,400,1200,120,800,300,600,200,500,200,900],
    'error': [300,150,150,150,150,120,200,300,80,80,80,300,340],
    'curious': [600,90,210,300,600,300,1300,200],
    'digesting': [140,140,140,140,200,300], 'sleeping': [250]*32,
}
READ_BLOCKS = {'L':[420,380,380,420,140], 'Bk':[90,200], 'F':[90,90,100,90,120,200],
               'C':[100,120,140], 'Sw':[140]*6, 'O':[140,160]}
IDLE_MS['reading'] = sum((READ_BLOCKS[k] for k in 'L L L Bk F L Bk L F L L L F L Bk L C Sw O'.split()), [])
POSE_MS = {'attentive':[1400,50,80,50,1250,300,300,50,80,50,2300],
           'expectant':[240,140,140,200], 'eager':[100,120,100,140],
           'perk':[60,80,120,100], 'talk':[80,70,90,70,90,100],
           'gulp':[90,90,80,90,90,90,120], 'shake':[70,70,70,70,150],
           'cheer':[100,100,120,100,100,80,120],
           'intro':[140,120,260,200,120,120,120,120,120,100],
           'outro':[120,160,160,240,140,100,80,120,120]}
SMALL_MS = {'awake':[1800,100,1400,300,600], 'sleeping':[700]*4,
            'digesting':[250,250], 'happy':[1600,160,160,400,1200],
            'curious':[1200,300,900,400], 'hungry':[2000,400,1600,800],
            'reading':[600,600,150,600], 'error':[600,100,400,400]}


def spec_ms(sheet, tag):
    if 'small' in sheet:
        return SMALL_MS[tag]
    state = sheet.removeprefix('bookworm-')
    family = tag.split('@')[0].split('.')[0]
    if family == 'idle':
        return IDLE_MS[state]
    if state == 'sleeping' and family == 'talk':
        return [90]*6
    ms = POSE_MS[family].copy()
    if state == 'hungry' and family == 'attentive':
        ms[2] = ms[8] = 160
    return ms


def check(ok, message):
    if not ok:
        raise AssertionError(message)


def run(*args):
    result = subprocess.run([ASE, '-b', *map(str, args)], capture_output=True, text=True, timeout=60)
    check(result.returncode == 0, result.stdout + result.stderr)


def export(source, directory, name):
    run(source, '--sheet', directory / f'{name}.png', '--data', directory / f'{name}.json',
        '--format', 'json-array', '--sheet-pack', '--list-tags', '--list-slices')


def count(im, rgba):
    return sum(p == rgba for p in im.get_flattened_data())


def crop_frame(sheet, record):
    r = record['frame']
    return sheet.crop((r['x'], r['y'], r['x'] + r['w'], r['y'] + r['h']))


def blink_check(images, durations, white, minimum, label):
    counts = [count(im, white) for im in images]
    flags = [v <= counts[0] - 2 for v in counts]
    starts = [i for i, flag in enumerate(flags) if flag and not flags[i - 1]]
    check(len(starts) >= minimum, f'{label}: only {len(starts)} blink runs')
    times = [sum(durations[:i]) for i in starts]
    gaps = [b - a for a, b in zip(times, times[1:] + [times[0] + sum(durations)])]
    check(max(gaps) / min(gaps) >= 1.6, f'{label}: blink gaps {gaps} are regular')
    return gaps


def rgba_equal(a, b):
    return list(a.get_flattened_data()) == list(b.get_flattened_data()) if a.mode == b.mode == 'RGBA' else False


def opaque_equal(a, b):
    return a.size == b.size and all((x[3] == y[3] and (x[3] == 0 or x == y))
                                   for x, y in zip(a.get_flattened_data(), b.get_flattened_data()))


def verify_gif(path, images, ms, scale):
    # Identical adjacent frames may be merged by the GIF encoder. Compare runs
    # by pixel content and accumulated time, reading duration after seek().
    expected = []
    for im, duration in zip(images, ms):
        scaled = im.resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST)
        if expected and opaque_equal(expected[-1][0], scaled):
            expected[-1][1] += duration
        else:
            expected.append([scaled, duration])
    actual = []
    with Image.open(path) as gif:
        for k in range(gif.n_frames):
            gif.seek(k)
            im = gif.convert('RGBA')
            duration = gif.info.get('duration', 0)
            if actual and opaque_equal(actual[-1][0], im):
                actual[-1][1] += duration
            else:
                actual.append([im, duration])
    check(len(actual) == len(expected), f'{path.name}: GIF frame count')
    for k, ((a, ams), (e, ems)) in enumerate(zip(actual, expected)):
        check(opaque_equal(a, e) and ams == ems, f'{path.name}: GIF differs at run {k} ({ams}/{ems} ms)')


def write_palette_gif(path, images, ms, scale):
    # Aseprite's GIF quantizer merges some distinct, nearby night ramp colours.
    # QA uses an exact indexed palette from the independently decoded PNG frames.
    colors=sorted({p[:3] for im in images for p in im.get_flattened_data() if p[3]})
    check(len(colors)<=255,path.name+': exact GIF palette budget')
    indices={rgb:i+1 for i,rgb in enumerate(colors)}
    palette=[0,0,0]+[v for rgb in colors for v in rgb]
    palette.extend([0]*(768-len(palette)));frames=[]
    for im in images:
        frame=Image.new('P',im.size)
        frame.putpalette(palette)
        frame.putdata([indices[p[:3]] if p[3] else 0 for p in im.get_flattened_data()])
        frames.append(frame.resize((im.width*scale,im.height*scale),Image.Resampling.NEAREST))
    frames[0].save(path,save_all=True,append_images=frames[1:],duration=ms,loop=0,transparency=0,disposal=2,optimize=False)


def contact(name, keys, scale=6):
    cols = 4 if len(keys) > 8 else len(keys)
    cell_w, cell_h = keys[0][1].width * scale + 12, keys[0][1].height * scale + 30
    out = Image.new('RGBA', (cols * cell_w, math.ceil(len(keys) / cols) * cell_h), '#ECECEC')
    draw = ImageDraw.Draw(out)
    for i, (label, im) in enumerate(keys):
        x, y = i % cols * cell_w, i // cols * cell_h
        draw.text((x + 6, y + 4), label, fill='#292929')
        out.alpha_composite(im.resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST), (x + 6, y + 24))
    out.save(ART / 'qa' / f'{name}-contact@{scale}x.png')


def boards(small):
    for name, bg, values in [('light', '#ECECEC', small), ('dark', '#1E1E1E', small)]:
        board = Image.new('RGBA', (8 * 20, 18), bg)
        for i, im in enumerate(values):
            board.alpha_composite(im, (i * 20, 0))
        for scale in [1, 2, 8]:
            board.resize((board.width * scale, board.height * scale), Image.Resampling.NEAREST).save(ART / 'qa' / f'menubar-{name}@{scale}x.png')
    # Owner-requested #ECECEC and #1E1E1E strip at 1x/2x and inspectable 8x.
    strip = Image.new('RGBA', (160, 36), '#ECECEC')
    for row, (bg, values) in enumerate([('#ECECEC', small), ('#1E1E1E', small)]):
        strip.paste(Image.new('RGBA', (160, 18), bg), (0, row * 18))
        for i, im in enumerate(values): strip.alpha_composite(im, (i * 20, row * 18))
    for scale in [1, 2, 8]:
        strip.resize((160 * scale, 36 * scale), Image.Resampling.NEAREST).save(ART / 'qa' / f'menubar-comparison@{scale}x.png')
    small[0].resize((144, 144), Image.Resampling.NEAREST).save(ART / 'qa' / 'menubar-pixel@8x.png')


# Worm fix pass checks. Self-contained helpers for Run B's clean merge.
ROOM_LENS_SLICES = {'eye': dict(x=27,y=21,w=2,h=2),
                    'lensL': dict(x=11,y=17,w=4,h=6),
                    'lensR': dict(x=23,y=18,w=8,h=7)}

def verify_wormfix_lens_slices(slices, label):
    check({k:slices[k] for k in ROOM_LENS_SLICES} == ROOM_LENS_SLICES,
          label + ': review A2 lens slices')


def verify_wormfix_attentive(images, tag, label):
    if tag.startswith('attentive.'):
        check(not opaque_equal(images[0], images[5]), label + ': review A2 glance equals rest')


def verify_wormfix_swap(images, regframes, colors, label):
    for image, record in zip(images, regframes):
        if record.get('note') in ['swap.down.2', 'swap.down.3']:
            cover = record['cover']
            keys = [('B','b','H'), ('1','2','3'), ('4','5','6')]
            for group in [keys[cover-1], keys[cover % 3]]:
                check(sum(count(image, colors[k]) for k in group) >= 6,
                      label + ': review A8 missing outgoing/incoming cover')


def verify_wormfix_body_outline(source, temp, colors, label):
    # Independently export the actual saved body layer, not a generator mask.
    stem = label + '-body'
    run('--layer', 'body', source, '--sheet', temp / (stem+'.png'),
        '--data', temp / (stem+'.json'), '--format', 'json-array', '--sheet-pack')
    data = json.loads((temp / (stem+'.json')).read_text())
    sheet = Image.open(temp / (stem+'.png')).convert('RGBA')
    for index, record in enumerate(data['frames']):
        image = crop_frame(sheet, record)
        def at(x,y):
            return image.getpixel((x,y)) if 0<=x<64 and 0<=y<48 else (0,0,0,0)
        for y in range(48):
            for x in range(64):
                value = at(x,y)
                if value == colors['K']:
                    neighbors = [at(xx,yy) for yy in range(y-1,y+2) for xx in range(x-1,x+2)]
                    # The intentionally enclosed glass rings adjoin D/L. A1
                    # applies to anatomical silhouette lines; preserve the rings.
                    glass = any(p in (colors['D'],colors['L']) for p in neighbors)
                    check(glass or any(p[3]==0 for p in neighbors),
                          f'{label} frame {index}: enclosed skin outline r{y} c{x}')
                elif value in (colors['G'],colors['g']):
                    check(all(at(xx,yy)[3] for xx,yy in [(x-1,y),(x+1,y),(x,y-1),(x,y+1)]),
                          f'{label} frame {index}: exposed skin r{y} c{x}')


def verify_owner_error_xs(image, colors, small, label):
    """Owner 2026-10-01: both diagonal Xs and drop in every error frame."""
    # Independent pixel transcription, including the green air around the room
    # Xs. The two room marks must share the head's tremble offset, not gaze.
    patterns = ([(3,6,['K.K','.K.','K.K']), (11,6,['K.K','.K.','K.K'])]
                if small else
                [(10,17,['.....','.K.K.','..K..','..K..','.K.K.','.....']),
                 (23,18,['........','.K....K.','..K..K..','...KK...',
                         '..K..K..','.K....K.','........'])])
    green = colors['m' if small else 'G']
    def matches(dx):
        return all(image.getpixel((x+col+dx,y+row)) ==
                   (colors['K'] if value == 'K' else green)
                   for x,y,rows in patterns for row,line in enumerate(rows)
                   for col,value in enumerate(line))
    check(any(matches(dx) for dx in ([0] if small else [-1,0,1])),
          label + ': missing/uncentered diagonal Xs or room X touching rim')
    check(count(image, colors['S']) >= (2 if small else 1), label + ': missing drop')
    check(count(image, (229,72,77,255)) == 0, label + ': red error pupil')


def verify_owner_single_menubar():
    check(all(not (folder / ('bookworm-small-dark' + ext)).exists()
              for folder, extensions in [(ART/'src',['.aseprite']), (RES,['.png','.json'])]
              for ext in extensions), 'owner: removed dark menu variant remains')


def verify_owner_error_lens_slice(slices, label):
    check(slices.get('errorLensL') == dict(x=10,y=17,w=5,h=6),
          label + ': owner black-X left lens slice')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worm-only', action='store_true')
    args = parser.parse_args()
    from night_palette import palette_data, allowed_colors
    palette_json = palette_data()
    palette = palette_json['colors']
    colors = {c['key']: tuple(bytes.fromhex(c['hex'].removeprefix('#'))) + (255,) for c in palette}
    allowed = allowed_colors(palette_json)
    book = {colors[c['key']] for c in palette if c['role'].startswith('book.')}
    check(not (BANNED & {int(c['hex'][1:], 16) for c in palette}), 'reserved hue in palette')
    check(len({c['key'] for c in palette}) == len(palette), 'duplicate palette key')
    # Owner 2026-10-01: no error red and no dark-bar rim. Judged by role, because the room
    # palette reuses the freed key letters (`R` is a room wood).
    worm_roles = {c['role'] for c in palette if c['group'] not in ('room', 'weather', 'fly', 'spine')}
    check(not any('error' in r or 'rimDark' in r or 'small.rim' in r for r in worm_roles),
          'owner: unused error-red/dark-rim palette role')
    verify_owner_single_menubar()
    registry = json.loads((ART / 'qa/registry.json').read_text())['sheets']
    report = {'sheets': {}, 'blinkGapsMs': {}, 'deterministic': True}
    small_keys = {}
    baseline_slices = None
    with tempfile.TemporaryDirectory(dir=ART / 'qa', prefix='verify-') as temporary:
        temp = Path(temporary)
        for name, expected_tags in EXPECTED.items():
            source = ART / 'src' / f'{name}.aseprite'
            png, js = RES / f'{name}.png', RES / f'{name}.json'
            check(source.is_file() and png.is_file() and js.is_file(), f'{name}: missing source/export')
            raw = js.read_text();check('/Users/' not in raw and '/private/' not in raw, f'{name}: machine path')
            data = json.loads(raw);sheet = Image.open(png).convert('RGBA')
            check(sheet.size == (data['meta']['size']['w'], data['meta']['size']['h']), f'{name}: size')
            check(max(sheet.size) <= 2048, f'{name}: texture too large')
            check(all(p[3] in (0, 255) and (p[3] == 0 or p in allowed) for p in sheet.get_flattened_data()), f'{name}: palette/alpha')
            tags = data['meta']['frameTags'];check([t['name'] for t in tags] == expected_tags, f'{name}: tag contract')
            records = data['frames'];images = []
            canvas = (18, 18) if 'small' in name else (64, 48)
            for record in records:
                r = record['frame'];check(0 <= r['x'] and 0 <= r['y'] and r['x'] + r['w'] <= sheet.width and r['y'] + r['h'] <= sheet.height, f'{name}: rect')
                check((record['sourceSize']['w'], record['sourceSize']['h']) == canvas and (r['w'], r['h']) == canvas and not record['trimmed'], f'{name}: canvas/trim')
                images.append(crop_frame(sheet, record))
            slices = {s['name']: s['keys'][0]['bounds'] for s in data['meta']['slices']}
            check({'lensL', 'lensR'} <= slices.keys(), f'{name}: lenses')
            if canvas == (64, 48):
                check({'ink', 'eye'} <= slices.keys(), f'{name}: slices')
                bounds = [im.getbbox() for im in images];x0 = min(b[0] for b in bounds);y0 = min(b[1] for b in bounds);x1 = max(b[2] for b in bounds);y1 = max(b[3] for b in bounds)
                check(slices['ink'] == dict(x=x0, y=y0, w=x1-x0, h=y1-y0), f'{name}: ink union')
                same = {n: slices[n] for n in ['eye', 'lensL', 'lensR']}
                if baseline_slices is None: baseline_slices = same
                check(same == baseline_slices and same['eye']['w'] == same['eye']['h'] == 2, f'{name}: lens/eye registration')
            if canvas == (64,48):
                verify_wormfix_lens_slices(slices,name)
                if name == 'bookworm-error': verify_owner_error_lens_slice(slices,name)
                verify_wormfix_body_outline(source,temp,colors,name)
            regtags = {t['name']: t for t in registry[name]['tags']}
            keys = [];times = {}
            for tag in tags:
                label = f'{name}/{tag["name"]}'
                check(tag['direction'] == 'forward' and tag['from'] <= tag['to'] and tag.get('repeat', 0) == 0, label + ': direction')
                ims = images[tag['from']:tag['to']+1];ms = [r['duration'] for r in records[tag['from']:tag['to']+1]]
                check(ms == spec_ms(name, tag['name']), label + ': binding spec timing')
                check(ms == [r['ms'] for r in regtags[tag['name']]['frames']], label + ': duration registry')
                check([r['index'] for r in regtags[tag['name']]['frames']] == list(range(tag['from'], tag['to']+1)), label + ': registry indices')
                times[tag['name']] = ms
                verify_wormfix_attentive(ims,tag['name'],label)
                if name=='bookworm-reading':
                    verify_wormfix_swap(ims,regtags[tag['name']]['frames'],colors,label)
                if len(ms) == 1: check(ms == [1000], label + ': static duration')
                else:
                    check(all(40 <= t <= 4000 and t % 10 == 0 for t in ms), label + ': duration bounds/GIF precision')
                    base = tag['name'].split('@')[0]
                    cap = 1600 if base in ['intro', 'outro'] else (400 if base.startswith('perk.') else (800 if base.startswith(('talk.', 'gulp.', 'shake.', 'cheer.', 'eager')) else 30000))
                    check(sum(ms) <= cap and (cap != 30000 or sum(ms) >= 400), label + ': total cap')
                for k, im in enumerate(ims):
                    if canvas == (64, 48):
                        check(sum(p in book for p in im.get_flattened_data()) >= 20, label + f': frame{k} lost book')
                        check(count(im, colors['D']) >= 30 and count(im, colors['L']) >= 6, label + ': glasses mark')
                        lift = tag['name'].startswith(('perk.', 'eager', 'cheer.center'))
                        lowest = im.getbbox()[3] - 1
                        check((44 <= lowest <= 47) if lift else lowest == 47, label + ': base row')
                        for y in range(48):
                            for x in range(64):
                                if im.getpixel((x,y)) in {colors['Z'], colors['Y'], colors['X']}:
                                    check(40 <= x <= 63 and 0 <= y <= 14, label + ': z box')
                        if name == 'bookworm-sleeping' and tag['name'] in ['idle', 'talk.center']:
                            check(count(im, colors['j']) >= 4 and count(im, colors['W']) == 0, label + ': sleeping eyes')
                        if name == 'bookworm-error': verify_owner_error_xs(im,colors,False,label+f'/frame{k}')
                    else:
                        check(not im.crop((0,16,18,18)).getbbox(), label + ': badge rows')
                        if tag['name'] == 'reading': check(sum(p in book for p in im.get_flattened_data()) >= 8, label + ': book')
                        if tag['name'] == 'error': verify_owner_error_xs(im,colors,True,label+f'/frame{k}')
                        if tag['name'] == 'sleeping':
                            for lens in ['lensL', 'lensR']:
                                r=slices[lens];points=[(x,y) for y in range(r['y'],r['y']+r['h']) for x in range(r['x'],r['x']+r['w']) if im.getpixel((x,y))==colors['K']]
                                check(len(points)>=2 and len({y for x,y in points})==1,label+': lid')
                if name == 'bookworm-sleeping' and tag['name'] == 'idle': check(count(ims[0],colors['Z'])>=3,label+': key z')
                if (tag['name'] == 'idle' and name in ['bookworm-awake','bookworm-happy','bookworm-curious','bookworm-reading']) or (tag['name'].startswith('idle@') and name=='bookworm-reading') or (tag['name'].startswith('attentive.') and name in ['bookworm-awake','bookworm-happy','bookworm-reading']):
                    minimum=3 if tag['name'].startswith('idle') and name in ['bookworm-awake','bookworm-reading'] else 2
                    report['blinkGapsMs'][label]=blink_check(ims,ms,colors['W'],minimum,label)
                if name=='bookworm-reading' and tag['name'].startswith('idle'):
                    line=[]
                    for im, f in zip(ims, regtags[tag['name']]['frames']):
                        if f.get('note','').startswith('line.') and f['note']!='line.return':
                            r=slices['lensR'];pts=[x for y in range(r['y'],r['y']+r['h']) for x in range(r['x'],r['x']+r['w']) if im.getpixel((x,y))==colors['K']]
                            check(pts,label+': pupil missing');line.append(sum(pts)/len(pts))
                            if len(line)==4: check(line==sorted(line) and line[-1]>line[0],label+': eye tracking');line=[]
                directory=ART/'qa'/name;directory.mkdir(exist_ok=True)
                scale=8 if canvas==(18,18) else 6;gif=directory/f'{tag["name"]}@{scale}x.gif'
                run(source,'--tag',tag['name'],'--scale',scale,'--save-as',gif)
                check(gif.is_file(),label+': GIF missing');verify_gif(gif,ims,ms,scale)
                keys.append((tag['name'],ims[0]))
            for tag, ms in times.items():
                if '@' in tag: check(ms==times[tag.split('@')[0]],f'{name}: cover timing')
                if tag.endswith('.left'): check(ms==times[tag[:-5]+'.center']==times[tag[:-5]+'.right'],f'{name}: gaze timing')
            if name == 'bookworm-reading':
                idle = [next(t for t in tags if t['name']==n) for n in ['idle','idle@2','idle@3']]
                for a,b in zip(idle, idle[1:]+idle[:1]):
                    check(opaque_equal(images[a['to']],images[b['from']]), name + ': cover seam')
                cycle_indices = [i for t in idle for i in range(t['from'],t['to']+1)]
                verify_gif(ART/'demo/bookworm-reading-cycle@6x.gif',
                           [images[i] for i in cycle_indices],
                           [records[i]['duration'] for i in cycle_indices],6)
                notes = [f.get('note') for f in regtags['idle']['frames']]
                flips = [i for i,n in enumerate(notes) if n=='flip.1']
                check(len(flips)==3 and len(set(b-a for a,b in zip(flips,flips[1:])))==2, name + ': uneven flips')
            if name == 'bookworm-sleeping':
                tag = next(t for t in tags if t['name']=='idle')
                glyphs = {'s':['ZZZ','.Z.','ZZZ'], 'm':['ZZZZ','..Z.','.Z..','ZZZZ'], 'l':['ZZZZZ','...Z.','..Z..','.Z...','ZZZZZ']}
                for f,im in enumerate(images[tag['from']:tag['to']+1],1):
                    stamps=[]
                    if f<=10: stamps.append(('s','Z' if f<=6 else ('Y' if f<=8 else 'X'),40+(f-1)//2,12-(f-1)))
                    if 9<=f<=20:
                        x,y=43+(f-9)//2,11-(f-9)//2;c='Z' if f<=15 else ('Y' if f<=18 else 'X')
                        stamps.extend([('m',c,x,y),('m',c,x+5,y-5)])
                    if f>=19:
                        x=42+(f-19)//3;c='Z' if f<=26 else ('Y' if f<=29 else 'X')
                        stamps.append(('s',c,x,11))
                        if f>=21: stamps.append(('m',c,x+4,6))
                        if f>=23: stamps.append(('l',c,x+9,0))
                    if f in [10,20,32]:
                        stamps=[('m' if size=='l' else 's',c,x,y) if c=='X' else (size,c,x,y) for size,c,x,y in stamps]
                    want={(x+dx,y+dy,colors[c]) for size,c,x,y in stamps for dy,row in enumerate(glyphs[size]) for dx,p in enumerate(row) if p=='Z'}
                    got={(x,y,im.getpixel((x,y))) for y in range(15) for x in range(40,64) if im.getpixel((x,y)) in {colors[c] for c in ['Z','Y','X']}}
                    check(got==want,f'{name}: z path frame {f}')
            contact(name,keys,8 if canvas==(18,18) else 6)
            if canvas==(18,18): small_keys[name]=[im for n,im in keys]
            export(source,temp,name)
            for ext in ['png','json']: check((temp/f'{name}.{ext}').read_bytes()==(RES/f'{name}.{ext}').read_bytes(),f'{name}: non-deterministic {ext}')
            report['sheets'][name]={'frames':len(records),'tags':len(tags),'pngSha256':hashlib.sha256(png.read_bytes()).hexdigest(),'jsonSha256':hashlib.sha256(js.read_bytes()).hexdigest()}
            print(f'{name}: {len(tags)} tags, {len(records)} frames, pixels/timing/marks/GIFs/determinism OK')
    if not args.worm_only:
        from verify_night import verify_night
        verify_night(report)
        from verify_room import verify_room
        verify_room(report, palette)
    # Reference comparison exports belong to the worm runs; the room run leaves them untouched.
    if args.worm_only:
        boards(small_keys['bookworm-small'])
    (ART/'qa/verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(('worm' if args.worm_only else 'all sprite') + ' verification: OK')


if __name__ == '__main__':
    main()
