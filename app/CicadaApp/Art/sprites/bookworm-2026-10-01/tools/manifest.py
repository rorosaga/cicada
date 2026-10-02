#!/usr/bin/env python3
"""Record every bundled sheet's provenance and raw-byte SHA-256."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
ART=Path(__file__).resolve().parent.parent
RES=ART.parents[2]/'Sources/CicadaApp/Resources/sprites'

def main():
 ase=os.environ.get('ASEPRITE','/Applications/Aseprite.app/Contents/MacOS/aseprite')
 generator=subprocess.check_output([ase,'--version'],text=True).strip()
 authoring=subprocess.check_output(['codex','--version'],text=True).strip()
 assets=[]
 for png in sorted(RES.glob('*.png')):
  name=png.stem;small='small' in name
  if name.startswith('bookworm-'):role='worm-small' if small else 'worm';script='build_worm_small' if small else 'build_worm'
  elif name=='room-weather':role='weather';script='build_weather'
  elif name=='room-skyfx':role='skyfx';script='build_skyfx'
  elif name=='room-clock':role='room';script='build_clock'
  elif name=='room-spines':role='spines';script='build_spines'
  else:role='fly' if name=='room-fly' else 'room';script='build_room'
  relit='-night-' in name or name in ['room-backdrop','room-window','room-plant','room-lamp','room-beanbag','room-mug']
  if relit:script='build_night'
  scenery=name in ('room-weather','room-skyfx','room-clock')
  asset=dict(id=name,png=png.name,json=name+'.json',role=role,
   generator=generator+', headless (-b), from saved Aseprite sources and Lua',script=f'lua/{script}.lua',source=f'src/{name}.aseprite',
   authoring=authoring+' (gpt-6.1-sol, extra-high effort)'+('; headless night relight from saved day art' if relit else '; headless scenery built from saved parts and declared palette' if scenery else '; original day art authored in Aseprite'),date='2026-10-02' if relit or scenery else '2026-10-01',
   licence="MIT, as this repository (see LICENSE). Own work for Cicada; no third-party artwork or brand marks.",
   processing='export_all.sh: --sheet-pack --format json-array --list-tags --list-slices; no trim; RGBA8888; binary alpha; palette-locked to palette.json',
   pngSha256=hashlib.sha256(png.read_bytes()).hexdigest(),jsonSha256=hashlib.sha256((RES/(name+'.json')).read_bytes()).hexdigest())
  if name.startswith('bookworm-'):
   ref='bookworm_menu_bar.png' if small else 'bookworm.png'
   asset['reference']='reference/'+ref+' '+hashlib.sha256((ART/'reference'/ref).read_bytes()).hexdigest()
  assets.append(asset)
 from verify_night import STATES, NIGHT
 from verify_room import CONTRACT
 expected={f'bookworm-{s}' for s in STATES}|set(NIGHT)|{'bookworm-small'}|set(CONTRACT)
 assert {a['id'] for a in assets}==expected,'Manifest must match the scenery contract sheet set'
 data={'note':"Cicada's sprite sheets (G176, TODO ruling 18). Regenerating a sheet means a new entry in the same commit. Sources and scripts: app/CicadaApp/Art/sprites/bookworm-2026-10-01/.",'assets':assets}
 raw=json.dumps(data,indent=1,ensure_ascii=False)+'\n'
 assert '/Users/' not in raw and '/private/' not in raw
 (RES/'sprites.manifest.json').write_text(raw)
 print(f'manifest: {len(assets)} sheet pairs')
if __name__=='__main__':main()
