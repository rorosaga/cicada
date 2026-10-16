"""A clean subprocess runs real intake, every Sleep stage, indexes and recovery."""
import json
from pathlib import Path
import subprocess
import sys

from benchmarks.system.runner import REPO, prepare_paths


def test_small_preset_runs_production_pipeline_offline(tmp_path):
    bank, home = prepare_paths('temp', 'temp', parent=tmp_path)
    # A reusable home must never shadow the repository packages.
    for name in ("api", "benchmarks"):
        package = home / name
        package.mkdir()
        (package / "__init__.py").write_text("raise RuntimeError('shadow package imported')\n")
    proc = subprocess.run([
        sys.executable, '-m', 'benchmarks.system.runner',
        '--bank-dir', str(bank), '--home', str(home),
        '--config', str(REPO / 'benchmarks/system/small.json'),
        '--clock', '2026-10-06T12:00:00+00:00',
        '--model', 'deterministic-v1', '--effort', 'low', '--preset', 'small',
    ], cwd=REPO, capture_output=True, text=True, timeout=120)
    lines = proc.stdout.strip().splitlines()
    assert lines, proc.stderr[-12000:]
    result_path = Path(json.loads(lines[-1])['manifest'])
    assert not result_path.is_relative_to(bank)
    assert result_path.is_relative_to(home)
    assert not bank.with_name(bank.name + '_results').exists()
    result = json.loads(result_path.read_text())
    assert proc.returncode == 0, {'integrity': result['integrity'], 'failures': result['failures']}
    assert result['engine']['kind'] == 'fake'
    assert result['engine']['production_route'] == 'local-with-fake-completion'
    assert result['diagnostics']['recovery_injections']['subscription_transport_verified'] is False
    assert result['diagnostics']['recovery_injections']['kinds'] == ['pause', 'cancel', 'failure']
    assert result['grading']['method'] == 'structural-exact-and-evidence'
    assert result['integrity'] and all(result['integrity'].values()), result['integrity']
    required = {'no_lost_claims', 'owned_commits', 'idempotent_reimport',
                'revision_safe_retirement', 'recovered_pause', 'recovered_cancel',
                'recovered_failure', 'human_correction_preserved', 'fixed_clock_expiry'}
    assert required <= result['integrity'].keys()
    assert result['index']['claims']['count'] > 0
    assert all(stage in {event['stage'] for event in result['timings']} for stage in
               ('extraction', 'resolution', 'conflicts', 'patterns', 'write', 'batch', 'drain', 'tail', 'index'))
    assert result['model_calls'] and all(call['tokens'] is None for call in result['model_calls'])
    assert {'full_context', 'before_sleep', 'after_sleep'} == set(result['controls'])
    assert len(result['resume_lineage']) >= 3
    assert result['resources']['peak_rss_bytes'] > 0
    assert result['clock']['scope'] == 'benchmark-service-boundaries'
    assert result['failures'], 'injected failures must be observable, not hidden'
    # No held-out questions or answers may be imported or written into memory.
    corpus = '\n'.join(p.read_text() for p in bank.rglob('*.md'))
    assert 'What status does alpha-project have?' not in corpus
    assert 'gold_answers' not in corpus
    assert 'benchmarks._bootstrap' not in result['imports']
