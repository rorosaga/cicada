"""Exercise actual source helper and extracted release dispatch, scratch HOME."""
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("release", [False, True])
def test_source_and_release_registry_executes_and_noop_hook_fails_open(tmp_path, release):
    env = {**os.environ, "HOME":str(tmp_path), "CICADA_HOME":str(tmp_path/"cicada"),
           "CICADA_MEMORY_PATH":str(tmp_path/"bank"), "CICADA_PORT":"49178",
           "CICADA_DISTRIBUTION":"release" if release else ""}
    if release:
        # G180: the release launchers are written by one script that build-backend.sh calls.
        build = (ROOT/'scripts/release/write-launchers.sh').read_text()
        script = build.split('cat > "$BIN/cicada-hook" <<\'EOF\'\n', 1)[1].split('\nEOF',1)[0]
        binary = tmp_path/'bin'; binary.mkdir()
        (binary/'cicada-env').write_text(f"CICADA_PYTHON='{sys.executable}'\nCICADA_BACKEND_DIR='{tmp_path}/backend'\n")
        hooks = tmp_path/'backend/app/api'; hooks.mkdir(parents=True)
        (hooks/'hooks').symlink_to(ROOT/'api/hooks', target_is_directory=True)
        launcher = binary/'cicada-hook'; launcher.write_text(script+'\n'); launcher.chmod(0o755)
        prefix = [str(launcher), 'cursor_registry']
        hook = [str(launcher), 'cursor']
    else:
        prefix = [sys.executable, str(ROOT/'api/hooks/cursor_registry.py')]
        hook = [sys.executable, str(ROOT/'api/hooks/cursor.py')]
    settings = tmp_path/'.cursor/hooks.json'
    def run(args, input=None):
        return subprocess.run(args, env=env, input=input, text=True, capture_output=True, timeout=5)
    r = run(prefix+['install','--settings',str(settings)])
    assert r.returncode == 0, r.stderr
    before = settings.read_bytes()
    assert run(prefix+['install','--settings',str(settings)]).stdout.strip() == 'present'
    assert settings.read_bytes() == before
    assert set(json.loads(before)['hooks']) == {'sessionStart'}
    assert run(prefix+['status','--settings',str(settings)]).returncode == 0
    if release:
        stable = tmp_path/'cicada/bin'; stable.mkdir(parents=True)
        shim = stable/'cicada-hook'
        shim.write_text(f"#!/bin/sh\nexec '{launcher}' \"$@\"\n")
        shim.chmod(0o755)
    configured = json.loads(before)['hooks']['sessionStart'][0]['command']
    r = run(shlex.split(configured), input=json.dumps({'hook_event_name':'stop'}))
    assert r.returncode == 0 and json.loads(r.stdout) == {}
    r = run(hook,input=json.dumps({'hook_event_name':'stop','transcript_path':'/outside/unreadable'}))
    assert r.returncode == 0 and json.loads(r.stdout) == {}
    assert run(prefix+['uninstall','--settings',str(settings)]).returncode == 0
    assert 'hooks' not in json.loads(settings.read_text())
