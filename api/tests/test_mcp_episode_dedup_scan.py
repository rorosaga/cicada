"""G183(c): optimistic hash scan, with an authoritative locked delta check."""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import os
from pathlib import Path
from threading import Barrier

import pytest

from api.services import episode_ids, markdown_parser, mcp_tools


CONTENT = 'Synthetic alpha-project note'
HASH = hashlib.sha256(CONTENT.encode()).hexdigest()[:12]


@pytest.fixture
def bank(tmp_path):
    (tmp_path / 'episodes').mkdir()
    return tmp_path


def _write(bank, suffix, content_hash='different', body='Synthetic beta-project note'):
    eid = f"ep_{datetime.now().strftime('%Y-%m-%d')}_{suffix:03d}"
    path = bank / 'episodes' / f'{eid}.md'
    markdown_parser.write(path, {'id': eid, 'content_hash': content_hash, 'processed': False}, body)
    return path


def _save(bank, content=CONTENT):
    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id='ses_test', harness='codex')
    return mcp_tools.save_episode(ctx, content, 'Alpha Project')


def test_existing_episode_text_is_scanned_without_holding_capture_lock(bank, monkeypatch):
    existing = _write(bank, 1)
    read = Path.read_text
    seen = []

    def probe(path, *args, **kwargs):
        if path == existing:
            seen.append(path)
            assert not episode_ids.dir_lock_held(bank / 'episodes')
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', probe)
    assert 'Episode saved' in _save(bank)
    assert seen == [existing]


@pytest.mark.parametrize('race', ['new', 'replace_same_size', 'edit_same_size', 'grow'])
def test_duplicate_raced_between_scan_and_lock_is_refused_and_only_delta_is_read(
        bank, monkeypatch, race):
    unchanged = _write(bank, 1)
    changed = _write(bank, 2, content_hash='f' * 12)
    lock = episode_ids.episode_lock
    read = Path.read_text
    locked_reads = []

    @contextmanager
    def raced_lock(directory):
        # A cooperating capture writer wins immediately before this save.
        with lock(directory):
            if race == 'new':
                _write(bank, 3, content_hash=HASH, body=CONTENT)
            elif race == 'grow':
                _write(bank, 2, content_hash=HASH, body=CONTENT * 5)
            else:
                original_stat = changed.stat()
                text = read(changed).replace('f' * 12, HASH)
                if race == 'replace_same_size':
                    _write(bank, 2, content_hash=HASH)
                else:
                    changed.write_text(text)
                os.utime(changed, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        with lock(directory):
            yield

    def probe(path, *args, **kwargs):
        if path.parent == bank / 'episodes' and episode_ids.dir_lock_held(path.parent):
            locked_reads.append(path)
        return read(path, *args, **kwargs)

    monkeypatch.setattr(episode_ids, 'episode_lock', raced_lock)
    monkeypatch.setattr(Path, 'read_text', probe)
    assert 'duplicate detected' in _save(bank)
    assert unchanged not in locked_reads
    assert len(locked_reads) == 1
    assert len(list((bank / 'episodes').glob('*.md'))) == (3 if race == 'new' else 2)


def test_file_disappearing_during_unlocked_scan_does_not_abort_save(bank, monkeypatch):
    existing = _write(bank, 1)
    read = Path.read_text

    def disappear(path, *args, **kwargs):
        if path == existing:
            path.unlink()
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', disappear)
    assert 'Episode saved' in _save(bank)
    assert len(list((bank / 'episodes').glob('*.md'))) == 1


def test_changed_matching_file_is_rechecked_even_if_removed_after_scan(bank, monkeypatch):
    duplicate = _write(bank, 1, content_hash=HASH)
    lock = episode_ids.episode_lock

    @contextmanager
    def raced_lock(directory):
        with lock(directory):
            duplicate.unlink()
        with lock(directory):
            yield

    monkeypatch.setattr(episode_ids, 'episode_lock', raced_lock)
    assert 'Episode saved' in _save(bank)


def test_duplicate_dedup_and_gap_allocation_keep_the_existing_episode(bank):
    existing = _write(bank, 3)
    before = existing.read_bytes()
    assert '_004' in _save(bank)
    assert 'duplicate detected' in _save(bank)
    assert existing.read_bytes() == before
    assert len(list((bank / 'episodes').glob('*.md'))) == 2


def test_replacement_during_scan_cannot_certify_the_text_read_from_old_inode(bank, monkeypatch):
    existing = _write(bank, 1)
    read = Path.read_text
    held = []

    def replace_after_read(path, *args, **kwargs):
        text = read(path, *args, **kwargs)
        if path == existing:
            held.append(episode_ids.dir_lock_held(path.parent))
            if len(held) == 1:
                _write(bank, 1, content_hash=HASH)
        return text

    monkeypatch.setattr(Path, 'read_text', replace_after_read)
    assert 'duplicate detected' in _save(bank)
    assert held == [False, True]
    assert len(list((bank / 'episodes').glob('*.md'))) == 1


def test_simultaneous_saves_with_the_same_unlocked_snapshot_create_one_episode(bank, monkeypatch):
    scan = mcp_tools._scan_episode_hashes
    scanned = Barrier(2)

    def simultaneous_scan(*args):
        result = scan(*args)
        scanned.wait(timeout=5)
        return result

    monkeypatch.setattr(mcp_tools, '_scan_episode_hashes', simultaneous_scan)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _save(bank), range(2)))
    assert sum('Episode saved' in result for result in results) == 1
    assert sum('duplicate detected' in result for result in results) == 1
    assert len(list((bank / 'episodes').glob('*.md'))) == 1
