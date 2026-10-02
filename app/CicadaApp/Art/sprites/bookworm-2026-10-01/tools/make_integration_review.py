#!/usr/bin/env python3
"""Group the app's actual test renders into labelled review boards, preserving every source PNG."""
import json
import shutil
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw

ART = Path(__file__).resolve().parent.parent
SOURCE = Path(tempfile.gettempdir()) / 'cicada-sprite-composites'
OUT = ART / 'qa/integration'
ROOMS = OUT / 'composites'
BOARDS = OUT / 'boards'
BASES = ['sunny', 'cloudy', 'windy', 'rainy', 'curtains']
TIMES = ['day', 'dusk', 'night']
MOODS = ['awake', 'sleeping', 'digesting', 'happy', 'curious', 'hungry', 'reading', 'error']


def main():
    ROOMS.mkdir(parents=True, exist_ok=True)
    BOARDS.mkdir(parents=True, exist_ok=True)
    groups = {}
    for base in BASES:
        for time in TIMES:
            groups[f'room-{base}-{time}'] = [f'{base}-{time}-{mood}-{lamp}-{zoom}.png'
                for zoom in ['1.0', '1.4'] for lamp in ['dark', 'lit'] for mood in MOODS]
    for overlay in ['mist-day', 'mist-dusk', 'mist-night', 'rainbow-day', 'rainbow-dusk', 'shootingstar-night']:
        groups[f'overlay-{overlay}'] = [f'overlay-{base}-{overlay}-{lamp}-{zoom}.png'
            for zoom in ['1.0', '1.4'] for base in ['sunny', 'rainy'] for lamp in ['dark', 'lit']]
    for time in ['12-00-00', '03-15-00', '10-09-55']:
        groups[f'clock-{time}'] = [f'clock-{time}-{phase}-{lamp}-{zoom}.png'
            for zoom in ['1.0', '1.4'] for phase in ['day', 'night'] for lamp in ['dark', 'lit']]
    index = []
    for group, names in groups.items():
        columns = 4
        board = Image.new('RGB', (columns * 328, ((len(names) + columns - 1) // columns) * 158), '#F0F0F0')
        draw = ImageDraw.Draw(board)
        for i, name in enumerate(names):
            source = SOURCE / name
            shutil.copyfile(source, ROOMS / name)
            image = Image.open(source).convert('RGBA')
            image = image.resize((320, 128), Image.Resampling.NEAREST)
            x, y = (i % columns) * 328 + 4, (i // columns) * 158
            draw.text((x, y + 3), name.removesuffix('.png'), fill='#171717')
            board.paste(image, (x, y + 25), image)
        path = BOARDS / (group + '.png')
        board.save(path)
        index.append({'board': str(path.relative_to(ART)), 'composites': ['qa/integration/composites/' + n for n in names]})
    settings = OUT / 'settings'
    settings.mkdir(exist_ok=True)
    for mode in ['localWeather', 'sleep', 'choose']:
        for scheme in ['light', 'dark']:
            name = f'{mode}-{scheme}.png'
            shutil.copyfile(SOURCE / 'settings' / name, settings / name)
            index.append({'settings': str((settings / name).relative_to(ART))})
    (OUT / 'render-index.json').write_text(json.dumps(index, indent=2) + '\n')
    print(f'{sum(len(g) for g in groups.values())} room renders in {len(groups)} boards, six Settings panes')


if __name__ == '__main__':
    main()
