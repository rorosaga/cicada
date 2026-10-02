#!/usr/bin/env python3
"""Review boards from saved exports; no sprite drawing or reference writes."""
import json
from pathlib import Path
from PIL import Image, ImageDraw

ART = Path(__file__).resolve().parent.parent
RES = ART.parents[2] / 'Sources/CicadaApp/Resources/sprites'
OUT = ART / 'qa/compare'
OUT.mkdir(parents=True, exist_ok=True)

def frame(state, index):
    name = 'bookworm-' + state
    data = json.loads((RES / (name + '.json')).read_text())
    sheet = Image.open(RES / (name + '.png')).convert('RGBA')
    record = data['frames'][index]
    r = record['frame']
    return sheet.crop((r['x'], r['y'], r['x'] + r['w'], r['y'] + r['h'])), record['duration']

def strip(name, state, indices, scale=6):
    width = 64 * scale + 8
    out = Image.new('RGBA', (min(4, len(indices)) * width, ((len(indices)+3)//4)*(48*scale+24)), '#ECECEC')
    draw = ImageDraw.Draw(out)
    for slot, index in enumerate(indices):
        im, ms = frame(state, index)
        x = slot % 4 * width
        y = slot // 4 * (48*scale+24)
        draw.text((x+4, y+3), f'{state} #{index} / {ms}ms', fill='#090707')
        out.alpha_composite(im.resize((64*scale, 48*scale), Image.Resampling.NEAREST), (x+4, y+20))
    out.save(OUT / (name + f'@{scale}x.png'))

boards = [Image.open(ART / 'qa' / ('compare-'+name+'@6x.png')).convert('RGBA')
          for name in ['base','happy','tired','sad','worried','mad']]
out = Image.new('RGBA', (boards[0].width*2, boards[0].height*3), '#ECECEC')
for i, im in enumerate(boards):
    out.alpha_composite(im, (i % 2 * im.width, i // 2 * im.height))
out.save(OUT / 'emotions@6x.png')

# The owner's source has a painted grid; nearest-neighbour fitting is review only.
reference = Image.open(ART / 'reference/bookworm_menu_bar.png').convert('RGBA')
alpha = reference.getchannel('A').point(lambda value: 255 if value >= 128 else 0)
reference.putalpha(alpha)
reference = reference.crop(alpha.getbbox())
factor = min(168/reference.width, 144/reference.height)
reference = reference.resize((round(reference.width*factor), round(reference.height*factor)), Image.Resampling.NEAREST)
board = Image.new('RGBA', (480, 180), '#ECECEC')
draw = ImageDraw.Draw(board)
draw.text((4, 3), 'Owner source / same dark outlines on light and dark bars, 8x', fill='#090707')
board.alpha_composite(reference, (4, 24))
for state, x, bg in [('small',184,'#ECECEC'), ('small',332,'#1E1E1E')]:
    im, _ = frame(state, 0)
    board.paste(Image.new('RGBA',(144,144),bg),(x,24))
    board.alpha_composite(im.resize((144,144),Image.Resampling.NEAREST),(x,24))
board.save(OUT / 'menubar@8x.png')

# New owner decision: original worried drawing beside the room and menu X eyes.
reference = Image.open(ART / 'reference/bookworm_worried.png').convert('RGBA')
alpha = reference.getchannel('A').point(lambda value: 255 if value >= 128 else 0)
reference.putalpha(alpha)
reference = reference.crop(alpha.getbbox())
factor = min(360/reference.width, 288/reference.height)
reference = reference.resize((round(reference.width*factor),round(reference.height*factor)),Image.Resampling.NEAREST)
error = Image.new('RGBA',(1080,320),'#ECECEC')
draw = ImageDraw.Draw(error)
for x,label in [(4,'Owner worried reference'),(388,'Room error key frame, 6x'),(788,'18x18 error, same dark rim, 8x')]:
    draw.text((x,4),label,fill='#090707')
error.alpha_composite(reference,(4,28))
im,_ = frame('error',0)
error.alpha_composite(im.resize((384,288),Image.Resampling.NEAREST),(388,28))
im,_ = frame('small',28)
for x,bg in [(788,'#ECECEC'),(932,'#1E1E1E')]:
    error.paste(Image.new('RGBA',(144,144),bg),(x,72))
    error.alpha_composite(im.resize((144,144),Image.Resampling.NEAREST),(x,72))
error.save(OUT / 'error-owner@6x-8x.png')

strip('outline-breath-tail','awake',[0,1,2,3,4,17,18])
strip('cover-swap','reading',list(range(73,85)))
strip('page-flip','reading',list(range(17,23)))
strip('z-size-fade','sleeping',[0,8,9,18,19,22,30,31])
strip('sweat','error',list(range(8)))
strip('gulp','awake',list(range(113,120)))
strip('landing-eager','awake',list(range(79,83)))
strip('landing-cheer','happy',list(range(128,135)))
print('Worm fix reference, silhouette and motion evidence boards written')
