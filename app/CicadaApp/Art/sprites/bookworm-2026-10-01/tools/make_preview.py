#!/usr/bin/env python3
"""Make the offline file:// art review, with JSON inlined and relative PNGs."""
import json
from pathlib import Path
ART=Path(__file__).resolve().parent.parent
RES=ART.parents[2]/'Sources/CicadaApp/Resources/sprites'
def main():
 sheets={p.stem:json.loads(p.read_text()) for p in sorted(RES.glob('*.json')) if p.name!='sprites.manifest.json'}
 data={'sheets':sheets,'palette':json.loads((ART/'palette.json').read_text()),'plan':json.loads((ART/'room-plan.json').read_text())}
 template=(ART/'tools/preview_template.html').read_text()
 (ART/'preview.html').write_text(template.replace('/*SPRITE_DATA*/',json.dumps(data,separators=(',',':')).replace('</',r'<\/')))
 print('offline preview: 18 sheets / every tag / room / menu strips')
if __name__=='__main__':main()
