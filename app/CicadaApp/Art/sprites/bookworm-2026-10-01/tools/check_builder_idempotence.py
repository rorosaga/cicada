#!/usr/bin/env python3
"""Exercise repeated night/fx builds headless in a disposable copy, never in delivered sources."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ART = Path(__file__).resolve().parent.parent


def snapshot(art):
    files = [*art.glob('src/*.aseprite'), art / 'room-motion.json', art / 'qa/room-registry.json']
    return {str(p.relative_to(art)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def main():
    ase = os.environ.get('ASEPRITE', '/Applications/Aseprite.app/Contents/MacOS/aseprite')
    results = {}
    with tempfile.TemporaryDirectory(dir=ART / 'qa', prefix='builder-repeat-') as td:
        fixture = Path(td) / 'art'
        shutil.copytree(ART, fixture, ignore=shutil.ignore_patterns('qa', '__pycache__'))
        (fixture / 'qa').mkdir()
        shutil.copyfile(ART / 'qa/room-registry.json', fixture / 'qa/room-registry.json')
        for builder in ['build_night', 'build_skyfx']:
            previous = None
            for _ in range(2):
                status = fixture / 'qa/.lua-completed'
                status.unlink(missing_ok=True)
                result = subprocess.run([ase, '-b', '--script-param', f'art={fixture}',
                                         '--script-param', f'run={builder}', '--script-param', f'status={status}',
                                         '--script', str(fixture / 'lua/run_checked.lua')],
                                        capture_output=True, text=True, timeout=60)
                assert result.returncode == 0 and status.is_file() and status.read_text().strip() == 'completed', result.stdout + result.stderr
                current = snapshot(fixture)
                if previous is not None:
                    differences = [p for p in current if current[p] != previous[p]]
                    assert not differences, f'{builder} appended or changed repeated output: {differences}'
                previous = current
            motion = json.loads((fixture / 'room-motion.json').read_text())['tags']
            assert len({t['tag'] for t in motion}) == len(motion), 'duplicate motion tags'
            registry = json.loads((fixture / 'qa/room-registry.json').read_text())['sheets']
            for name, sheet in registry.items():
                tags = [t['name'] for t in sheet['tags']]
                assert len(set(tags)) == len(tags), f'duplicate registry tags: {name}'
            results[builder] = {'runs': 2, 'filesCompared': len(current), 'byteIdentical': True}
    (ART / 'qa/review-builder-idempotence.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results))


if __name__ == '__main__':
    main()
