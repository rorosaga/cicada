"""G50/G76 seam: MCP registration, startup delivery and capture are three separate switches."""
import asyncio
import json
import shlex
from pathlib import Path

import pytest

from api.services import agent_wiring

REPO = Path('/synthetic/cicada'); PY = '/synthetic/cicada/api/.venv/bin/python'


@pytest.mark.parametrize('mcp_on,hook_on,save_on', [(False, False, False), (True, False, False), (False, True, False),
                                                    (True, True, False), (False, False, True), (True, True, True)])
def test_startup_and_capture_are_separate_from_mcp(tmp_path, monkeypatch, mcp_on, hook_on, save_on):
    monkeypatch.delenv('CICADA_DISTRIBUTION', raising=False)
    p = tmp_path / '.cursor'; p.mkdir()
    cmd = f"'{PY}' '{REPO}/api/hooks/cursor.py'"
    if mcp_on: (p/'mcp.json').write_text(json.dumps({'mcpServers':{'cicada':{}}}))
    hooks = {}
    if hook_on: hooks['sessionStart'] = [{'command': cmd, 'timeout': 2}]
    if save_on:
        hooks['beforeSubmitPrompt'] = [{'command': cmd, 'timeout': 2}]
        hooks['afterAgentResponse'] = [{'command': cmd, 'timeout': 5}]
    if hooks: (p/'hooks.json').write_text(json.dumps({'version': 1, 'hooks': hooks}))
    data = asyncio.run(agent_wiring.probe(home=tmp_path,memory_root=tmp_path/'memory',repo=REPO,python=PY,resolve=lambda _:None))
    row = next(r for r in data['agents'] if r['id']=='cursor')
    assert row['recall'] == ('on' if mcp_on else 'off')
    assert row['autorecall'] == ('on' if hook_on else 'off')
    assert row['autosave'] == ('on' if save_on else 'off') and row['capabilities']['capture'] == 'documented'
    assert row['capabilities']['startup'] == 'documented' and row['capabilities']['verification'] == 'synthetic'
    assert row['capabilities']['surface'] == 'local-ide'
    assert all('api/hooks/capture.py' not in s['argv'][-1] for s in row['autorecall_on'])
    assert bool(row['autorecall_on']) != hook_on and bool(row['autorecall_off']) == hook_on
    # Turning startup off never removes capture, and the other way round.
    assert all(s['argv'][-2:] == ['--hook', 'startup'] for s in row['autorecall_off'])
    assert bool(row['connect']) != save_on and bool(row['autosave_off']) == save_on
    assert all(s['argv'][-2:] == ['--hook', 'capture'] for s in row['connect'] + row['autosave_off'])
    assert 'not yet checked' in row['detail'].lower()


def test_half_registered_capture_reads_stale_and_offers_the_repair(tmp_path, monkeypatch):
    monkeypatch.delenv('CICADA_DISTRIBUTION', raising=False)
    p = tmp_path / '.cursor'; p.mkdir()
    cmd = f"'{PY}' '{REPO}/api/hooks/cursor.py'"
    (p/'hooks.json').write_text(json.dumps({'version': 1, 'hooks': {'beforeSubmitPrompt': [{'command': cmd, 'timeout': 2}]}}))
    data = asyncio.run(agent_wiring.probe(home=tmp_path,memory_root=tmp_path/'memory',repo=REPO,python=PY,resolve=lambda _:None))
    row = next(r for r in data['agents'] if r['id']=='cursor')
    assert row['autosave'] == 'stale' and row['connect'] and row['autosave_off']


@pytest.mark.parametrize('release', [False,True])
def test_setup_supplies_stable_startup_command_and_mcp_link(tmp_path, monkeypatch, release):
    monkeypatch.setenv('CICADA_DISTRIBUTION', 'release' if release else '')
    monkeypatch.setenv('CICADA_HOME', str(tmp_path/'cicada'))
    setup = agent_wiring.setup('cursor',home=tmp_path,memory_root=tmp_path/'bank',repo=REPO,python=PY)
    assert setup['kind'] == 'deeplink' and setup['deeplink'].startswith('cursor://')
    assert len(setup['argv']) == 2
    assert setup['argv'][1][-2:] == ['--hook', 'capture']
    argv = setup['argv'][0]
    assert argv[2:5] == ['install','--settings',str(tmp_path/'.cursor/hooks.json')]
    assert argv[-2] == '--command'
    assert ('api/hooks/cursor.py' in argv[-1]) != release
    assert ('bin/cicada-hook' in argv[-1]) == release
    assert 'not yet checked' in setup['note'].lower()
