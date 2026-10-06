"""The supported system runner cannot inherit a developer bank or credentials."""
import json
import os
from pathlib import Path
import subprocess
import sys

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
    assert env['PYTHON_DOTENV_DISABLED'] == '1'
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


def test_temp_paths_are_marked_separate_and_reusable():
    bank, home = prepare_paths('temp', 'temp')
    assert (bank / '_bench.yaml').is_file()
    assert (home / '_bench_home.yaml').is_file()
    assert not home.is_relative_to(bank)
    assert prepare_paths(str(bank), str(home)) == (bank, home)


def test_symlink_bank_is_refused(tmp_path):
    bank, home = prepare_paths('temp', 'temp')
    link = tmp_path / 'linked'
    link.symlink_to(bank, target_is_directory=True)
    try:
        prepare_paths(str(link), str(home))
    except ValueError as exc:
        assert 'symlink' in str(exc)
    else:
        raise AssertionError('symlink bank accepted')
