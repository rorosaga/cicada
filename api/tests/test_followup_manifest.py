"""G183(b): current follow-up events cannot merge an open conflict item.

Exercise the real resolver/reconciler/writer/commit path, without injecting
an impossible conflict nudge into event reconciliation.
"""

import asyncio
import subprocess
from datetime import date

import pytest

from api.config import Settings
from api.models.schemas import InboxResolveRequest
from api.services import bank_index, handshake, inbox_service, markdown_parser, progress
from api.services.claims import Claim, write_claims


def _git(bank, *args):
    return subprocess.run(["git", "-C", str(bank), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.mark.parametrize("predicate,key,answer", [
    *(('happened', key, None) for key in ('done', 'still', 'stopped', 'didnt')),
    ('happened', None, 'The alpha-project fixture passed'),
    *(('milestone', key, None) for key in ('done', 'missed', 'dropped')),
    ('milestone', None, 'move it to 2026-10-20'),
    *(('due', key, None) for key in ('done', 'missed', 'dropped')),
    ('due', None, 'move it to 2026-10-20'),
])
def test_followup_keeps_open_conflict_unchanged_and_commits_its_own_files(
        tmp_path, monkeypatch, predicate, key, answer):
    bank = tmp_path / 'bank'
    (bank / 'entities').mkdir(parents=True)
    (bank / 'inbox').mkdir()
    today = date(2026, 10, 6)

    class Clock(date):
        today = classmethod(lambda cls: today)

    monkeypatch.setattr(inbox_service, 'date', Clock)
    monkeypatch.setattr(handshake, 'local_timezone', lambda: 'UTC')
    claim = Claim(id='clm_alpha', subject='alpha-project', predicate=predicate,
                  object='2026-10-01' if predicate == 'due' else 'alpha-fixture',
                  text='Testing the alpha-project fixture', observer='agent',
                  authored_by='codex', origin='mcp', valid_from='2026-09-01',
                  recorded_at='2026-09-01', confidence=0.8,
                  status='ongoing' if predicate == 'happened' else 'planned',
                  target='2026-10-01' if predicate == 'milestone' else None)
    markdown_parser.write(bank / 'entities/alpha-project.md', {
        'type': 'project', 'name': 'Alpha Project', 'status': 'active',
        'confidence': 0.8, 'created': '2026-09-01', 'last_referenced': '2026-09-01',
    }, write_claims('# Alpha Project\n', [claim]))
    conflict = bank / 'inbox/inbox-001.md'
    markdown_parser.write(conflict, {
        'kind': 'conflict', 'status': 'pending', 'entity_id': 'alpha-project',
        'predicate': predicate, 'created_date': '2026-09-01',
        'options': [{'key': 'a', 'label': 'alpha'}, {'key': 'b', 'label': 'beta'}],
    }, 'Synthetic open conflict')
    markdown_parser.write(bank / 'inbox/inbox-002.md', {
        'kind': 'followup', 'status': 'pending', 'entity_id': 'alpha-project',
        'predicate': predicate, 'claim_id': claim.id, 'created_date': '2026-10-06',
    }, '')
    _git(bank, 'init', '-q')
    _git(bank, 'config', 'user.name', 'test')
    _git(bank, 'config', 'user.email', 'test@example.com')
    _git(bank, 'add', '.')
    _git(bank, 'commit', '-qm', 'seed')
    before = conflict.read_bytes()
    bank_index.invalidate()
    nudges = []
    reconcile = progress.reconcile_stage3

    def observe(*args, **kwargs):
        result = reconcile(*args, **kwargs)
        nudges.extend(result[1])
        return result

    monkeypatch.setattr(progress, 'reconcile_stage3', observe)
    result = asyncio.run(inbox_service.resolve('inbox-002', InboxResolveRequest(
        action='resolve', option_key=key, answer=answer), Settings(CICADA_MEMORY_PATH=bank)))
    assert result['status'] == 'resolved'
    assert not nudges
    assert conflict.read_bytes() == before
    assert _git(bank, 'status', '--porcelain') == ''
    sha = _git(bank, 'log', '-1', '--grep=^Inbox resolution', '--format=%H')
    files = _git(bank, 'show', '--format=', '--name-only', sha).splitlines()
    assert {'entities/alpha-project.md', 'inbox/inbox-002.md'} <= set(files)
    # No conflict was written; including it would falsely claim ownership.
    assert 'inbox/inbox-001.md' not in files
    assert 'Cicada-Author: user' in _git(bank, 'show', '-s', '--format=%B', sha)
    if answer and predicate == 'happened':
        assert any(path.startswith('episodes/') for path in files)
