"""The supported system runner cannot inherit a developer bank or credentials."""
import json

import pytest

from benchmarks.system.runner import isolated_env, prepare_paths


def test_child_environment_is_allowlisted(tmp_path, monkeypatch):
    monkeypatch.setenv('CICADA_MEMORY_PATH', str(tmp_path / 'forbidden-bank'))
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-secret')
    monkeypatch.setenv('CICADA_LLM_MODE', 'auto')
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'forbidden-agent'))
    env = isolated_env(tmp_path / 'bank', tmp_path / 'home', 'fake')
    assert env['HOME'] == str(tmp_path / 'home')
    assert env['CICADA_HOME'] == str(tmp_path / 'home')
    assert env['CICADA_MEMORY_PATH'] == str(tmp_path / 'bank')
    assert env['CICADA_CAPTURE'] == 'off'
    assert env['PYTHON_DOTENV_DISABLED'] == '1'  # load_dotenv only; home .env is refused
    assert env['PYTHONHASHSEED'] == '0'
    assert 'OPENAI_API_KEY' not in env and 'CODEX_HOME' not in env
    assert env['CICADA_ALLOW_CONNECTOR_FETCH'] == 'off'


def test_unmarked_bank_and_home_are_refused_before_import(tmp_path):
    bank = tmp_path / 'ordinary'
    bank.mkdir()
    (bank / 'sentinel').write_text('unchanged')
    try:
        prepare_paths(str(bank), 'temp')
    except ValueError as exc:
        assert '_bench.yaml' in str(exc)
    else:
        raise AssertionError('unmarked bank accepted')
    assert (bank / 'sentinel').read_text() == 'unchanged'
    assert sorted(p.name for p in bank.iterdir()) == ['sentinel']


def test_temp_paths_are_marked_separate_and_reusable(tmp_path):
    bank, home = prepare_paths('temp', 'temp', parent=tmp_path)
    assert (bank / '_bench.yaml').is_file()
    assert (home / '_bench_home.yaml').is_file()
    assert not home.is_relative_to(bank)
    assert prepare_paths(str(bank), str(home)) == (bank, home)


def test_symlink_bank_is_refused(tmp_path):
    bank, home = prepare_paths('temp', 'temp', parent=tmp_path)
    link = tmp_path / 'linked'
    link.symlink_to(bank, target_is_directory=True)
    try:
        prepare_paths(str(link), str(home))
    except ValueError as exc:
        assert 'symlink' in str(exc)
    else:
        raise AssertionError('symlink bank accepted')


def test_subscription_preflight_fails_closed_without_positive_plan_and_model_evidence():
    import asyncio
    from api.services.codex_app_server import CodexSnapshot
    from benchmarks.system.workload import subscription_preflight

    for snapshot in (None, CodexSnapshot(signed_in=True, account_type='apiKey', models=('synthetic-model',)),
                     CodexSnapshot(signed_in=True, account_type=None, models=('synthetic-model',)),
                     CodexSnapshot(signed_in=True, account_type='chatgpt', models=('different-model',))):
        async def fake_snapshot(**kwargs):
            return snapshot
        try:
            asyncio.run(subscription_preflight('synthetic-model', snapshot_fn=fake_snapshot))
        except ValueError:
            pass
        else:
            raise AssertionError('unverified subscription/model accepted')


def test_subscription_preflight_records_allowance_without_account_identity():
    import asyncio
    from api.services.codex_app_server import CodexSnapshot
    from benchmarks.system.workload import subscription_preflight

    async def snapshot(**kwargs):
        return CodexSnapshot(signed_in=True, account_type='chatgpt', models=('synthetic-model',),
                             email='private@example.com', used_percent=10, windows=(('primary', 10, None),))
    evidence = asyncio.run(subscription_preflight('synthetic-model', snapshot_fn=snapshot))
    assert evidence['used_percent'] == 10
    assert 'email' not in evidence
    assert 'private@example.com' not in json.dumps(evidence)


def test_home_accepts_internal_model_cache_links_but_refuses_escape(tmp_path):
    bank, home = prepare_paths('temp', 'temp', parent=tmp_path)
    cache = home / 'model-cache'
    cache.mkdir()
    (cache / 'blob').write_text('synthetic weights')
    (cache / 'snapshot').symlink_to(cache / 'blob')
    assert prepare_paths(str(bank), str(home)) == (bank, home)
    (cache / 'escape').symlink_to(tmp_path)
    try:
        prepare_paths(str(bank), str(home))
    except ValueError as exc:
        assert 'symlink' in str(exc)
    else:
        raise AssertionError('home symlink escape accepted')


@pytest.mark.parametrize('reverse', [False, True])
def test_dot_dot_paths_cannot_hide_nested_bank_and_home(tmp_path, reverse):
    from benchmarks.system.runner import MARKER
    root = tmp_path / 'home'
    nested = root / 'bank'
    nested.mkdir(parents=True)
    (tmp_path / 'x').mkdir()
    bank, home = (root, nested) if reverse else (nested, root)
    for path, marker in ((bank, '_bench.yaml'), (home, '_bench_home.yaml')):
        (path / marker).write_text(json.dumps({'kind': MARKER}))
    lexical_home = tmp_path / 'x' / '..' / home.relative_to(tmp_path)
    with pytest.raises(ValueError, match='disjoint'):
        prepare_paths(str(bank), str(lexical_home))


def test_home_dotenv_is_refused(tmp_path):
    bank, home = prepare_paths('temp', 'temp', parent=tmp_path)
    (home / '.env').write_text('CICADA_LLM_MODE=byok\n')
    with pytest.raises(ValueError, match=r'\.env'):
        prepare_paths(str(bank), str(home))


def test_dot_dot_config_cannot_hide_bank_containment(tmp_path, capsys):
    from benchmarks.system.runner import main
    bank, home = prepare_paths('temp', 'temp', parent=tmp_path)
    (tmp_path / 'x').mkdir()
    config = bank / 'settings.json'
    config.write_text(json.dumps({'batch_size': 2, 'embedding_model': 'fake-hash-v1'}))
    lexical = tmp_path / 'x' / '..' / bank.name / config.name
    assert main(['--bank-dir', str(bank), '--home', str(home), '--config', str(lexical),
                 '--clock', '2040-01-01T12:00:00Z', '--model', 'deterministic-v1',
                 '--effort', 'low', '--validate-only']) == 2
    assert 'config must be outside' in capsys.readouterr().err
