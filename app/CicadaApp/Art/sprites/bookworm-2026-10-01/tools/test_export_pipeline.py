"""Pipeline control regressions; fake Aseprite never edits the delivered art."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import manifest

ART = Path(__file__).resolve().parent.parent
RES = ART.parents[2] / 'Sources/CicadaApp/Resources/sprites'


class ExportPipelineTests(unittest.TestCase):
    def run_export(self, builds, stage='all', reject=False):
        with tempfile.TemporaryDirectory(dir=ART / 'qa', prefix='pipeline-test-') as td:
            root = Path(td)
            art = root / 'app/CicadaApp/Art/sprites/bookworm'
            res = root / 'app/CicadaApp/Sources/CicadaApp/Resources/sprites'
            (art / 'tools').mkdir(parents=True)
            (art / 'src').mkdir()
            res.mkdir(parents=True)
            shutil.copyfile(ART / 'tools/export_all.sh', art / 'tools/export_all.sh')
            for name in ['bookworm-awake', 'bookworm-awake-night-dark', 'bookworm-small', 'room-weather']:
                (art / 'src' / (name + '.aseprite')).write_bytes(b'fixture')
            trace = root / 'trace'
            fake_ase = root / 'aseprite'
            fake_ase.write_text(f'#!{sys.executable}\n' + '''import os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['PIPELINE_TRACE'], 'a') as log:
    if '--script' in args:
        params = [args[i+1] for i, a in enumerate(args) if a == '--script-param']
        values = dict(p.split('=', 1) for p in params)
        log.write('lua ' + values['run'] + '\\n')
        pathlib.Path(values['status']).write_text('completed')
    else:
        log.write('export ' + pathlib.Path(args[1]).stem + '\\n')
        for flag in ['--sheet', '--data']:
            pathlib.Path(args[args.index(flag)+1]).write_bytes(b'fixture')
''')
            fake_ase.chmod(0o755)
            bin_dir = root / 'bin'; bin_dir.mkdir()
            python = bin_dir / 'python3'
            python.write_text('#!/bin/bash\nprintf "python %s\\n" "$(basename "$1")" >> "$PIPELINE_TRACE"\n'
                              '[[ "$PIPELINE_REJECT" != 1 || "$(basename "$1")" != verify.py ]]\n')
            python.chmod(0o755)
            env = dict(os.environ, ASEPRITE=str(fake_ase), BUILDS=builds, STAGE=stage,
                       PIPELINE_TRACE=str(trace), PIPELINE_REJECT=str(int(reject)),
                       PATH=str(bin_dir) + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['bash', str(art / 'tools/export_all.sh')], env=env,
                                    capture_output=True, text=True, timeout=20)
            return result, trace.read_text().splitlines() if trace.exists() else []

    def test_worm_stage_refreshes_night_sources_all_exports_manifest_and_full_verifier(self):
        result, calls = self.run_export('build_worm build_worm_small', stage='worm')
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in ['lua build_room', 'lua build_night', 'export bookworm-awake-night-dark',
                     'export room-weather', 'python manifest.py', 'python verify.py']:
            self.assertIn(call, calls)
        self.assertLess(calls.index('lua build_worm'), calls.index('lua build_night'))
        self.assertLess(calls.index('python manifest.py'), calls.index('python verify.py'))

    def test_partial_skyfx_build_refreshes_weather_before_replacing_motion(self):
        result, calls = self.run_export('build_skyfx')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('lua build_weather', calls)
        self.assertLess(calls.index('lua build_weather'), calls.index('lua build_skyfx'))
        self.assertEqual(calls.count('lua build_skyfx'), 1)

    def test_builder_order_is_canonical_and_whitespace_cannot_skip_requests(self):
        result, calls = self.run_export('build_skyfx\n build_clock\tbuild_spines build_skyfx')
        self.assertEqual(result.returncode, 0, result.stderr)
        for builder in ['build_clock', 'build_spines', 'build_weather', 'build_skyfx']:
            self.assertEqual(calls.count('lua ' + builder), 1, builder)
        self.assertLess(calls.index('lua build_weather'), calls.index('lua build_skyfx'))

    def test_unknown_build_or_stage_fails_before_any_art_write(self):
        for builds, stage in [('build_missing', 'all'), ('build_worm', 'missing')]:
            result, calls = self.run_export(builds, stage=stage)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])
            self.assertNotIn('sprites: OK', result.stdout)

    def test_stale_sheet_verifier_failure_never_prints_ok(self):
        result, calls = self.run_export('build_worm', stage='worm', reject=True)
        self.assertIn('python verify.py', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('sprites: OK', result.stdout)

    def test_manifest_uses_static_authoring_without_a_codex_executable(self):
        with tempfile.TemporaryDirectory(dir=ART / 'qa', prefix='manifest-test-') as td:
            res = Path(td)
            for p in RES.iterdir():
                if p.suffix in ('.png', '.json'):
                    shutil.copyfile(p, res / p.name)
            def version(args, **kwargs):
                self.assertEqual(args, [manifest.os.environ.get('ASEPRITE', '/Applications/Aseprite.app/Contents/MacOS/aseprite'), '--version'],
                                 'only the Aseprite export generator may be queried during rebuild')
                return 'Aseprite 1.3.18.6-dev\n'
            with patch.object(manifest, 'RES', res), patch.object(manifest.subprocess, 'check_output', side_effect=version):
                with contextlib.redirect_stdout(io.StringIO()):
                    manifest.main()
                first = (res / 'sprites.manifest.json').read_bytes()
                with contextlib.redirect_stdout(io.StringIO()):
                    manifest.main()
                self.assertEqual(first, (res / 'sprites.manifest.json').read_bytes())
            assets = json.loads(first)['assets']
            self.assertEqual(len(assets), 36)
            for asset in assets:
                self.assertIn('gpt-6.1-sol', asset['authoring'])
                self.assertIn(asset['date'], ['2026-10-01', '2026-10-02'])


if __name__ == '__main__':
    unittest.main()
