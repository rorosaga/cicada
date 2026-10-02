#!/usr/bin/env python3
"""Record/compare two complete saved-source worm rebuilds, including QA GIFs."""
import argparse
import hashlib
import json
from pathlib import Path

ART = Path(__file__).resolve().parent.parent
ROOT = ART.parents[4]
RES = ART.parents[2] / 'Sources/CicadaApp/Resources/sprites'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('mode', choices=['record', 'compare'])
args = parser.parse_args()
files = (list(RES.glob('bookworm-*.png')) + list(RES.glob('bookworm-*.json'))
         + list((ART / 'src').glob('bookworm-*.aseprite'))
         + list((ART / 'parts').glob('worm*.aseprite'))
         + [ART / 'menubar.aseprite', ART / 'demo/bookworm-reading-cycle@6x.gif',
            ART / 'demo/bookworm-mad-demo@6x.gif']
         + list((ART / 'qa').glob('bookworm-*/*.gif')))
hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sorted(files)}
assert len(hashes) == 162, f'Expected 162 rebuild files, found {len(hashes)}'
manifest = ART / 'qa/wormfix-rebuild-first.json'
if args.mode == 'record':
    manifest.write_text(json.dumps(hashes, indent=2) + '\n')
    print(f'Recorded {len(hashes)} saved sources, sheet exports and demos/tag GIFs')
else:
    before = json.loads(manifest.read_text())
    changed = sorted(key for key in set(before) | set(hashes)
                     if before.get(key) != hashes.get(key))
    result = {'files': len(hashes), 'byte_identical': not changed, 'changed': changed,
              'sha256': hashes}
    (ART / 'qa/wormfix-rebuild-comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    assert not changed, f'Rebuild changed files: {changed}'
    print(f'Two complete worm rebuilds: {len(hashes)} files byte-identical')
