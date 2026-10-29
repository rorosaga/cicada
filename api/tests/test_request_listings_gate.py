"""Speed 2026-10-29 (e): a request's ETag and read may answer from the SSE tick's last walk only through one gate.

The gate (``sync_ticker.reusable_listings``): the tick walked under the bank's running watcher, that same watcher
reported nothing since before the walk, this process wrote nothing since (``local_writes``: page writes and every
non-read request), no Sleep run is under way, and the walk is younger than the fallback. Each condition alone must
close it. Also (d): the inbox ETag moves with the predicate map, the held names and the owner's id; and the ledger
(review of #518): a claims ledger changing alone moves the entities stamp and the built inbox's key.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.services import (bank_index, bank_watch, inbox_service, local_writes, markdown_parser, sync_service,
                          sync_ticker)


def _bank(tmp_path: Path) -> Path:
    bank = tmp_path / "bank"
    for sub in ("entities", "episodes", "inbox"):
        (bank / sub).mkdir(parents=True)
    markdown_parser.write(bank / "entities" / "alpha-project.md", {"name": "Alpha", "type": "project"}, "Body.")
    return bank.resolve()


@pytest.fixture
def gate(tmp_path, monkeypatch):
    """A tick that walked this bank under a running watcher, with every condition open."""
    bank = _bank(tmp_path)
    watch = SimpleNamespace(generation=7, seq=3)
    monkeypatch.setattr(bank_watch, "running", lambda mp: watch)
    monkeypatch.setattr(sync_ticker, "get_sleep_state", lambda: SimpleNamespace(status="idle"))
    listings = {str(bank / "entities"): bank_index._scan_uncached(bank / "entities")}
    sync_ticker._ticks[str(bank)] = sync_ticker.Tick(
        info=None, debt=None, at=time.monotonic(), walked_at=time.monotonic(), seq=3, watch_gen=7,
        listings=listings, local_gen=local_writes.current())
    yield SimpleNamespace(bank=bank, watch=watch, listings=listings)
    sync_ticker._ticks.clear()


def test_the_gate_opens_only_when_every_condition_holds(gate, monkeypatch):
    assert sync_ticker.reusable_listings(gate.bank) is gate.listings

    gate.watch.seq = 4                                   # the watcher saw a change
    assert sync_ticker.reusable_listings(gate.bank) is None
    gate.watch.seq = 3

    gate.watch.generation = 8                            # a different watcher's count vouches for nothing
    assert sync_ticker.reusable_listings(gate.bank) is None
    gate.watch.generation = 7

    monkeypatch.setattr(sync_ticker, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    assert sync_ticker.reusable_listings(gate.bank) is None, "never while Sleep runs"
    monkeypatch.setattr(sync_ticker, "get_sleep_state", lambda: SimpleNamespace(status="idle"))

    monkeypatch.setattr(bank_watch, "running", lambda mp: None)
    assert sync_ticker.reusable_listings(gate.bank) is None, "no watcher: every request walks"
    monkeypatch.setattr(bank_watch, "running", lambda mp: gate.watch)

    tick = sync_ticker._ticks[str(gate.bank)]
    sync_ticker._ticks[str(gate.bank)] = sync_ticker.Tick(
        info=None, debt=None, at=tick.at, walked_at=time.monotonic() - bank_watch.FALLBACK_S, seq=3, watch_gen=7,
        listings=tick.listings, local_gen=tick.local_gen)
    assert sync_ticker.reusable_listings(gate.bank) is None, "past the fallback the bank is walked"
    sync_ticker._ticks[str(gate.bank)] = tick
    assert sync_ticker.reusable_listings(gate.bank) is gate.listings


def test_this_processs_own_page_write_closes_it_at_once(gate):
    markdown_parser.write(gate.bank / "entities" / "beta-example.md", {"name": "Beta", "type": "concept"}, "Body.")
    assert sync_ticker.reusable_listings(gate.bank) is None


def test_a_request_that_may_write_closes_it_even_without_a_page_write(gate, monkeypatch):
    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(gate.bank))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        client.get("/healthz")
        assert sync_ticker.reusable_listings(gate.bank) is gate.listings, "a read writes nothing"
        client.post("/no-such-route-for-this-test", json={})
        assert sync_ticker.reusable_listings(gate.bank) is None
    finally:
        config.get_settings.cache_clear()


def test_a_request_answers_from_the_gated_listings_and_walks_once_the_gate_closes(gate, monkeypatch):
    walked = []
    real = bank_index._scan_uncached
    monkeypatch.setattr(bank_index, "_scan_uncached", lambda d: walked.append(Path(d).name) or real(d))
    sync_service.etag_for(gate.bank, "entities")
    assert "entities" not in walked, "the tick's listing answered"
    gate.watch.seq = 4
    sync_service.etag_for(gate.bank, "entities")
    assert "entities" in walked


def test_the_inbox_etag_moves_with_the_files_beside_the_inbox(tmp_path):
    bank = _bank(tmp_path)
    before = sync_service.etag_for(bank, "inbox", "entities", "episodes")
    (bank / "_predicates.yaml").write_text("multi_valued:\n- uses\n", encoding="utf-8")
    after_map = sync_service.etag_for(bank, "inbox", "entities", "episodes")
    assert after_map != before
    (bank / "pending_entities.jsonl").write_text("\n", encoding="utf-8")
    after_held = sync_service.etag_for(bank, "inbox", "entities", "episodes")
    assert after_held != after_map
    (bank / "_state.md").write_text("---\ntype: state\nowner_id: alpha-project\n---\nnow\n", encoding="utf-8")
    after_owner = sync_service.etag_for(bank, "inbox", "entities", "episodes")
    assert after_owner != after_held
    # The now-view rewritten with the same owner: the inbox serves the same, so its stamp stays.
    (bank / "_state.md").write_text("---\ntype: state\nowner_id: alpha-project\n---\nlater\n", encoding="utf-8")
    assert sync_service.etag_for(bank, "inbox", "entities", "episodes") == after_owner


def test_a_bank_without_those_files_or_a_ledger_keeps_its_stamps(tmp_path):
    bank = _bank(tmp_path)
    comps = sync_service.components(bank, keys=("inbox", "entities"))
    assert ":s" not in comps["inbox"] and ":l" not in comps["entities"]


def test_a_ledger_changing_alone_moves_the_entities_stamp_and_the_built_inbox_key(tmp_path):
    bank = _bank(tmp_path)
    today = "2026-10-29"
    key = inbox_service._built_inputs(bank, today)
    stamp = sync_service.components(bank, keys=("entities",))["entities"]
    ledger = bank / "entities" / f"alpha-project{bank_index.LEDGER_SUFFIX}"
    ledger.write_text('{"id": "clm_x"}\n', encoding="utf-8")   # what a page write's after-step does to a ledger
    assert inbox_service._built_inputs(bank, today) != key
    moved = sync_service.components(bank, keys=("entities",))["entities"]
    assert moved != stamp
    ledger.write_text('{"id": "clm_x"}\n{"id": "clm_y"}\n', encoding="utf-8")
    assert sync_service.components(bank, keys=("entities",))["entities"] != moved
