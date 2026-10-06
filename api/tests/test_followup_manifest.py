"""G183(b): no current event writer can merge an open inbox item.

Exercise the real resolver/reconciler/writer/commit path, without injecting
an impossible conflict nudge into event reconciliation.
"""

import asyncio
import subprocess
from datetime import date, datetime, timezone

import pytest

from api.config import Settings
from api.models.schemas import InboxResolveRequest
from api.services import bank_index, handshake, inbox_service, markdown_parser, mcp_tools, progress
from api.services.claim_reconciler import reconcile_events
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
    reconcile_calls = []
    reconcile = progress.reconcile_stage3

    def observe(*args, **kwargs):
        reconcile_calls.append(args[0])
        result = reconcile(*args, **kwargs)
        nudges.extend(result[1])
        return result

    monkeypatch.setattr(progress, 'reconcile_stage3', observe)
    result = asyncio.run(inbox_service.resolve('inbox-002', InboxResolveRequest(
        action='resolve', option_key=key, answer=answer), Settings(CICADA_MEMORY_PATH=bank)))
    assert result['status'] == 'resolved'
    if predicate == 'happened' and key == 'didnt':
        # Withdrawal writes directly; this case checks commit ownership only.
        assert not reconcile_calls
    else:
        assert reconcile_calls
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


def _event_claim(cid, predicate, status, *, human, day):
    return Claim(id=cid, subject='alpha-project', predicate=predicate,
                 object='alpha-fixture', text='Testing the alpha-project fixture',
                 observer='owner' if human else 'agent',
                 source_trust='user_stated' if human else 'agent_extracted',
                 origin='manual_edit' if human else 'mcp',
                 authored_by='user' if human else 'codex',
                 valid_from=day, recorded_at=day, confidence=0.8, status=status,
                 target='2026-10-01' if predicate == 'milestone' else None)


def test_agent_milestone_divergence_is_in_progress_paths_and_committed_by_mcp(tmp_path, monkeypatch):
    bank = tmp_path / 'bank'
    (bank / 'entities').mkdir(parents=True)
    (bank / 'inbox').mkdir()
    head = _event_claim('clm_person', 'milestone', 'planned', human=True, day='2026-09-01')
    markdown_parser.write(bank / 'entities/alpha-project.md', {
        'type': 'project', 'name': 'Alpha Project', 'status': 'active',
        'confidence': 0.8, 'created': '2026-09-01', 'last_referenced': '2026-09-01',
    }, write_claims('# Alpha Project\n', [head]))
    conflict = bank / 'inbox/inbox-001.md'
    markdown_parser.write(conflict, {
        'kind': 'conflict', 'status': 'pending', 'entity_id': 'alpha-project',
        'predicate': 'milestone', 'created_date': '2026-09-01',
        'options': [{'key': 'a', 'label': 'alpha'}, {'key': 'b', 'label': 'beta'}],
    }, 'Synthetic open conflict')
    _git(bank, 'init', '-q')
    _git(bank, 'config', 'user.name', 'test')
    _git(bank, 'config', 'user.email', 'test@example.com')
    _git(bank, 'add', '.')
    _git(bank, 'commit', '-qm', 'seed')
    before = conflict.read_bytes()
    bank_index.invalidate()
    monkeypatch.setattr(handshake, 'local_timezone', lambda: 'UTC')
    monkeypatch.setattr(mcp_tools, '_now_in', lambda tz: datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    results = []
    advance = progress.advance

    def observe_advance(*args, **kwargs):
        assert kwargs['observer'] == 'agent'
        result = advance(*args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(progress, 'advance', observe_advance)
    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id='ses_test', harness='codex')
    reply = mcp_tools.note_progress(ctx, 'alpha-project', 'milestone', head.text, 'done',
                                    milestone='alpha-fixture')
    assert reply.startswith("Recorded alongside the person's own milestone"), reply
    [result] = results
    assert result['action'] == 'coexist'
    divergence = bank / 'inbox/inbox-002.md'
    assert markdown_parser.parse(divergence).frontmatter['kind'] == 'divergence'
    assert 'inbox/inbox-002.md' in result['paths']
    assert conflict.read_bytes() == before
    assert _git(bank, 'status', '--porcelain') == ''
    files = _git(bank, 'show', '--format=', '--name-only', 'HEAD').splitlines()
    assert set(files) == {'entities/alpha-project.md', 'inbox/inbox-002.md'}
    body = _git(bank, 'show', '-s', '--format=%B', 'HEAD')
    assert 'Cicada-Author: codex' in body and 'Cicada-Session: ses_test' in body


@pytest.mark.parametrize('predicate,status', [
    *(('happened', status) for status in ('ongoing', 'done', 'dropped')),
    *(('milestone', status) for status in ('planned', 'done', 'missed', 'dropped')),
])
@pytest.mark.parametrize('human_head', [False, True])
@pytest.mark.parametrize('human_incoming', [False, True])
def test_reconcile_events_never_emits_mergeable_conflict_nudges(
        tmp_path, predicate, status, human_head, human_incoming):
    head = _event_claim('clm_head', predicate, 'ongoing' if predicate == 'happened' else 'planned',
                        human=human_head, day='2026-09-01')
    incoming = _event_claim('clm_new', predicate, status, human=human_incoming, day='2026-10-06')
    if predicate == 'milestone':
        incoming.target = '2026-10-02'  # A genuine disagreement even for planned → planned.
    elif status in ('done', 'dropped'):
        incoming._settles = head.id
    nudges = []
    reconcile_events(incoming, [head], progress._Settings(tmp_path), today='2026-10-06',
                     nudges=nudges, audit=[], absorbed=set())
    assert all(nudge['action'] != 'conflict_nudge' for nudge in nudges)
    if predicate == 'milestone' and human_head and not human_incoming:
        assert [nudge['action'] for nudge in nudges] == ['divergence_nudge']
    else:
        assert not nudges
