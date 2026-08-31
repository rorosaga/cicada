"""Hermetic tests for the shared ``base.run_sync``/``base.forget`` skeleton
(Task 15 §2, §4) that every connector's ``sync()``/``forget()`` now wraps.

These exercise the shared driver directly with a synthetic ``fetch``, rather
than through a real connector — the per-platform contract tests
(test_connector_{pinterest,reddit,x}.py) still cover each adapter's actual
``fetch`` logic end to end.
"""

from __future__ import annotations

import asyncio

import pytest

from api.services import media_ingestor, sync_state
from api.services.connections import secrets
from api.services.connectors import base
from api.services.media_ingestor import RawItem


def run(coro):
    return asyncio.run(coro)


def _memory(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="",
            site=media_ingestor._site_of(url), media_type="url")

    async def no_commit(memory_path, count):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    return memory


def test_run_sync_skips_when_not_connected(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    called = []

    async def fetch(fn):
        called.append(1)
        return [], None

    result = run(base.run_sync(
        "acme", memory, fetch, is_connected=lambda: False))
    assert result == {"status": "skipped", "reason": "not connected",
                       "new": 0, "seen": 0, "error": None}
    assert called == [], "fetch must never run when not connected"


def test_run_sync_skips_when_the_network_gate_is_closed(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    called = []

    async def fetch(fn):
        called.append(1)
        return [], None

    result = run(base.run_sync(
        "acme", memory, fetch, is_connected=lambda: True, allow_fetch=False))
    assert result == {"status": "skipped", "reason": "network disabled",
                       "new": 0, "seen": 0, "error": None}
    assert called == [], "fetch must never run with the gate closed"


def test_run_sync_never_raises_and_records_the_error(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)

    async def fetch(fn):
        raise RuntimeError("boom")

    result = run(base.run_sync(
        "acme", memory, fetch, is_connected=lambda: True,
        http_fn=lambda *a, **k: None))
    assert result["status"] == "error"
    assert result["reason"] is None
    assert result["new"] == 0 and result["seen"] == 0
    assert result["error"] == "RuntimeError: boom"
    assert "boom" in sync_state.read_sync_state(memory)["acme"]["last_error"]


def test_run_sync_ingests_and_records_a_success_with_extra_cursor_state(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    items = [RawItem(url="https://example.com/a", origin="acme"),
              RawItem(url="https://example.com/b", origin="acme")]

    async def fetch(fn):
        return items, {"cursor": "abc123"}

    result = run(base.run_sync(
        "acme", memory, fetch, is_connected=lambda: True,
        http_fn=lambda *a, **k: None))
    assert result == {"status": "ok", "reason": None, "new": 2, "seen": 2, "error": None}
    entry = sync_state.read_sync_state(memory)["acme"]
    assert entry["count"] == 2
    assert entry["cursor"] == "abc123"


def test_run_sync_is_idempotent_via_the_url_index(tmp_path, monkeypatch):
    memory = _memory(tmp_path, monkeypatch)
    items = [RawItem(url="https://example.com/a", origin="acme")]

    async def fetch(fn):
        return items, None

    run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                       http_fn=lambda *a, **k: None))
    second = run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                                http_fn=lambda *a, **k: None))
    assert second["new"] == 0
    assert second["seen"] == 1


# --- final-review H2: an opt-OUT gate, and a gate-skip that stays visible ---


def test_network_allowed_defaults_to_on_and_off_disables_it(monkeypatch):
    """Opt-OUT, mirroring ``logo_service.fetch_allowed()`` — on by default,
    ``=off``/``=0``/``=false`` disables it. An explicit ``allow_fetch``
    override always wins over the env value either direction."""
    monkeypatch.delenv(base.GATE_ENV, raising=False)
    assert base.network_allowed() is True, "unset must default to allowed"
    monkeypatch.setenv(base.GATE_ENV, "off")
    assert base.network_allowed() is False
    monkeypatch.setenv(base.GATE_ENV, "0")
    assert base.network_allowed() is False
    monkeypatch.setenv(base.GATE_ENV, "false")
    assert base.network_allowed() is False
    monkeypatch.setenv(base.GATE_ENV, "1")
    assert base.network_allowed() is True, "any non-off-ish value still allows"
    monkeypatch.setenv(base.GATE_ENV, "off")
    assert base.network_allowed(True) is True, "an explicit override always wins"
    monkeypatch.delenv(base.GATE_ENV, raising=False)
    assert base.network_allowed(False) is False, "override wins even against the default-on env"


def test_run_sync_records_a_skip_not_an_error_when_the_gate_is_closed(tmp_path, monkeypatch):
    """A gate-skipped BACKGROUND poll must stay visible in ``sync_state.json``
    — distinctly from ``record_error``, since the connector is configured
    and working, not broken."""
    memory = _memory(tmp_path, monkeypatch)
    called = []

    async def fetch(fn):
        called.append(1)
        return [], None

    result = run(base.run_sync(
        "acme", memory, fetch, is_connected=lambda: True, allow_fetch=False))
    assert result["status"] == "skipped"
    assert called == [], "fetch must never run with the gate closed"

    entry = sync_state.read_sync_state(memory)["acme"]
    assert entry.get("last_skip")
    assert entry.get("last_skip_reason") == "network fetch disabled"
    assert "last_error" not in entry


# --- final-review H3: a >MAX_BATCH fetch must never silently drop a tail ----


def test_run_sync_chunks_ingestion_so_a_batch_larger_than_max_batch_is_never_dropped(
    tmp_path, monkeypatch,
):
    """Before this fix, ``items[:MAX_BATCH]`` silently truncated a larger
    fetch: ``seen``/``count`` still claimed everything was handled, and a
    cursor-based connector's ``extra`` (already computed by the time
    ``fetch()`` returns, from the FULL list) would advance the stored cursor
    past items that were never actually ingested — permanently losing them.
    Chunking must call ``ingest_batch`` more than once and account for every
    item across all of the calls."""
    memory = _memory(tmp_path, monkeypatch)
    monkeypatch.setattr(media_ingestor, "MAX_BATCH", 3)

    items = [RawItem(url=f"https://example.com/{i}", origin="acme") for i in range(7)]
    chunk_sizes: list[int] = []
    real_ingest_batch = media_ingestor.ingest_batch

    async def counting_ingest_batch(batch_items, memory_path, from_bookmark_file=False, **kw):
        chunk_sizes.append(len(batch_items))
        return await real_ingest_batch(
            batch_items, memory_path, from_bookmark_file=from_bookmark_file, **kw
        )

    monkeypatch.setattr(media_ingestor, "ingest_batch", counting_ingest_batch)

    async def fetch(fn):
        return items, {"cursor": "last-of-all-seven"}

    result = run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                                http_fn=lambda *a, **k: None))

    assert chunk_sizes == [3, 3, 1], "chunked into MAX_BATCH-sized slices, nothing dropped"
    assert result["seen"] == 7, "seen must count every fetched item, not just the first slice"
    assert result["new"] == 7, "every item across every chunk must have been ingested"
    entry = sync_state.read_sync_state(memory)["acme"]
    assert entry["count"] == 7
    # The cursor only ever advances over items that were actually ingested —
    # true here because the chunking loop ingested the whole list.
    assert entry["cursor"] == "last-of-all-seven"


# --- Devin round-1, finding 1: overlapping run_sync calls must serialize --


def test_run_sync_serializes_two_overlapping_calls_for_the_same_channel(tmp_path, monkeypatch):
    """A manual `sync_now` POST can overlap the Sleep-tail poll — both
    read-modify-write the SAME `url_index.json`/`sync_state.json`/git tree.
    The module-level `_sync_lock` must make one call's ENTIRE body finish
    before the other's starts, not just avoid a mid-write crash. Ordering
    probe: if both `fetch()` calls ran concurrently, both "start" events
    would land before either "end" — under the lock they cannot interleave.
    """
    memory = _memory(tmp_path, monkeypatch)
    events: list[str] = []

    async def slow_fetch(fn):
        events.append("start")
        await asyncio.sleep(0.05)
        events.append("end")
        return [], None

    async def one_sync():
        return await base.run_sync("acme", memory, slow_fetch, is_connected=lambda: True,
                                    http_fn=lambda *a, **k: None)

    async def both():
        await asyncio.gather(one_sync(), one_sync())

    run(both())

    assert events == ["start", "end", "start", "end"], (
        "the two run_sync calls interleaved instead of serializing"
    )


# --- Devin round-1, finding 2: a suppressed per-item failure must not -----
# --- advance the cursor past the item that was lost -----------------------


def test_run_sync_does_not_advance_the_cursor_when_ingest_batch_silently_drops_an_item(
    tmp_path, monkeypatch,
):
    """`media_ingestor.ingest_batch`'s own `worker` SUPPRESSES a per-item
    `ingest_one` failure — it catches the exception, logs a warning, and
    returns, never letting it escape `ingest_batch`/the `asyncio.gather`
    inside it (verified against the REAL `ingest_batch`, not a mock, so this
    pins actual behavior rather than an assumption about it). A batch that
    silently lost one item to that suppression still returns normally with
    `created` short by one — run_sync must detect that by elimination
    (chunk size vs created+duplicates) and refuse to advance the cursor,
    or the lost item would never be re-fetched again. The two items that DID
    succeed must still count as `new` — they are real, safe progress,
    protected from being re-created on a future retry by url_index dedup.
    """
    memory = _memory(tmp_path, monkeypatch)

    async def flaky_enrich(url, client, from_bookmark_file=False):
        if "bad" in url:
            raise RuntimeError("enrichment boom")
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="",
            site=media_ingestor._site_of(url), media_type="url")

    monkeypatch.setattr(media_ingestor, "enrich", flaky_enrich)

    items = [
        RawItem(url="https://example.com/good-1", origin="acme"),
        RawItem(url="https://example.com/bad-item", origin="acme"),
        RawItem(url="https://example.com/good-2", origin="acme"),
    ]

    async def fetch(fn):
        return items, {"cursor": "must-not-be-recorded"}

    result = run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                                http_fn=lambda *a, **k: None))

    assert result["status"] == "error"
    assert result["new"] == 2, "the two good items still landed"
    assert result["error"] == "1 item(s) failed to ingest"

    entry = sync_state.read_sync_state(memory).get("acme", {})
    assert "cursor" not in entry, "record_sync must not run — the cursor stays put"
    assert entry.get("last_error") == "1 item(s) failed to ingest"

    # The good items really were written — url_index dedup protects them on
    # the inevitable retry, so only the failed one re-ingests next time.
    idx = media_ingestor.load_url_index(memory)
    assert len(idx) == 2


def test_run_sync_reports_success_when_nothing_actually_failed(tmp_path, monkeypatch):
    """Guards the finding-2 fix's own arithmetic: a batch with a genuine
    pre-existing duplicate (not a failure) must not be misread as a failed
    item and must still record the sync."""
    memory = _memory(tmp_path, monkeypatch)
    items = [RawItem(url="https://example.com/a", origin="acme")]

    async def fetch(fn):
        return items, {"cursor": "abc"}

    # First sync creates it; a second sync re-fetching the SAME item hits
    # the pre-existing-duplicate path in `ingest_batch`, not a failure path.
    run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                       http_fn=lambda *a, **k: None))
    second = run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                                http_fn=lambda *a, **k: None))
    assert second["status"] == "ok"
    assert second["new"] == 0
    assert sync_state.read_sync_state(memory)["acme"]["cursor"] == "abc"


# --- final-review L1: no URL (PII) in a sync_state.json error, ever --------


def test_run_sync_sanitizes_an_http_status_error_to_status_only_no_url(tmp_path, monkeypatch):
    """``sync_state.json`` lives INSIDE the bank and is git-committed — unlike
    a log line, it is versioned memory. ``httpx.HTTPStatusError``'s own
    ``str()`` embeds the full request URL (for Reddit that is
    ``/user/<username>/saved``) — not a credential, but PII that must never
    land in committed history. Recorded down to ``ClassName: HTTP <status>``."""
    import httpx

    memory = _memory(tmp_path, monkeypatch)

    async def fetch(fn):
        request = httpx.Request("GET", "https://oauth.reddit.com/user/janedoe123/saved")
        response = httpx.Response(429, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    result = run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                                http_fn=lambda *a, **k: None))
    assert result["status"] == "error"
    assert result["error"] == "HTTPStatusError: HTTP 429"
    assert "janedoe123" not in result["error"]
    assert "janedoe123" not in sync_state.read_sync_state(memory)["acme"]["last_error"]


def test_run_sync_scrubs_a_url_from_a_generic_exception_message(tmp_path, monkeypatch):
    """Defensive fallback for a non-httpx exception whose message happens to
    embed a URL (a raw response body, a lower-level connection error)."""
    memory = _memory(tmp_path, monkeypatch)

    async def fetch(fn):
        raise RuntimeError(
            "connection refused to https://oauth.reddit.com/user/janedoe123/saved"
        )

    result = run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                                http_fn=lambda *a, **k: None))
    assert "janedoe123" not in result["error"]
    assert result["error"] == "RuntimeError: connection refused to <url>"


def test_run_sync_drops_no_platform_specific_counters(tmp_path, monkeypatch):
    """Task 15 §2: the canonical dict carries no ``boards``/``pages`` (or any
    other per-platform) counter — a caller that wants one adds it itself
    after calling in, the way ``x.sync()`` adds ``resources_read``."""
    memory = _memory(tmp_path, monkeypatch)

    async def fetch(fn):
        return [], None

    result = run(base.run_sync("acme", memory, fetch, is_connected=lambda: True,
                                http_fn=lambda *a, **k: None))
    assert set(result) == {"status", "reason", "new", "seen", "error"}


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    names = ("BASE_TEST_A", "BASE_TEST_B")
    for name in names:
        monkeypatch.delenv(name, raising=False)
    yield
    for name in names:
        os.environ.pop(name, None)


def test_forget_removes_every_named_secret():
    secrets.set_secret("BASE_TEST_A", "value-a")
    secrets.set_secret("BASE_TEST_B", "value-b")
    base.forget(("BASE_TEST_A", "BASE_TEST_B"))
    assert not secrets.has_secret("BASE_TEST_A")
    assert not secrets.has_secret("BASE_TEST_B")


def test_forget_tolerates_a_name_that_was_never_set():
    base.forget(("BASE_TEST_A", "BASE_TEST_B"))  # neither was ever stored
    assert not secrets.has_secret("BASE_TEST_A")
