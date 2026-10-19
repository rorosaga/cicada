"""`GET /sleep/episodes` (2026-10-19): the Sleep page's Waiting rows without every episode's body.

The page fetched every episode on every load — 8,237 rows, 4.5 MB, seconds on a large bank — to show the handful
still waiting. ``processed=false`` lists only those, from the cached headers; ``processed=true`` pages the read ones;
the bare call keeps the original shape; every variant carries an ETag over the ``episodes`` component.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import main
from api.config import Settings
from api.services import bank_index, folder_source, markdown_parser


def _episode(memory, ep_id: str, *, hours_ago: float, processed: bool = False, **extra) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    fm = {"id": ep_id, "processed": processed, "source": "mcp", "timestamp": ts, **extra}
    if processed:
        fm["processed_by"] = "sleep"
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md", fm, f"Episode {ep_id} body.")


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    for i in range(6):
        _episode(memory, f"ep_read_{i}", hours_ago=100 - i, processed=True)
    _episode(memory, "ep_wait_b", hours_ago=2)
    _episode(memory, "ep_wait_a", hours_ago=3)
    monkeypatch.setattr(Settings, "memory_path", property(lambda self: memory))
    bank_index.invalidate()
    return memory


def test_the_bare_call_keeps_the_original_shape(bank):
    r = TestClient(main.app).get("/sleep/episodes")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and len(rows) == 8
    assert r.headers["X-Total-Count"] == "8"
    assert {"id", "timestamp", "source", "origin", "title", "preview", "chars", "processed", "processedBy",
            "copyKind", "copyValue", "changedAt"} <= set(rows[0])


def test_waiting_only_lists_the_unprocessed_in_the_cycles_order(bank):
    r = TestClient(main.app).get("/sleep/episodes?processed=false")
    assert [row["id"] for row in r.json()] == ["ep_wait_a", "ep_wait_b"]   # oldest first, like the cycle
    assert r.headers["X-Total-Count"] == "2"
    row = r.json()[0]
    assert row["processed"] is False and row["preview"] == "Episode ep_wait_a body." and row["chars"] == 23


def test_waiting_only_reads_no_read_episodes_body(bank, monkeypatch):
    read: list[str] = []
    real = bank_index.IndexedFile.body

    def counting(self):
        read.append(self.stem)
        return real(self)

    monkeypatch.setattr(bank_index.IndexedFile, "body", counting)
    TestClient(main.app).get("/sleep/episodes?processed=false")
    assert sorted(read) == ["ep_wait_a", "ep_wait_b"]


def test_read_ones_page_with_a_total(bank):
    client = TestClient(main.app)
    first = client.get("/sleep/episodes?processed=true&offset=0&limit=4")
    second = client.get("/sleep/episodes?processed=true&offset=4&limit=4")
    assert first.headers["X-Total-Count"] == second.headers["X-Total-Count"] == "6"
    ids = [row["id"] for row in first.json()] + [row["id"] for row in second.json()]
    assert ids == [f"ep_read_{i}" for i in range(6)]
    assert all(row["processed"] for row in first.json())


def test_limit_is_bounded(bank):
    assert TestClient(main.app).get("/sleep/episodes?limit=0").status_code == 422
    assert TestClient(main.app).get("/sleep/episodes?limit=1001").status_code == 422


def test_etag_answers_304_until_an_episode_moves(bank):
    client = TestClient(main.app)
    r = client.get("/sleep/episodes?processed=false")
    etag = r.headers["ETag"]
    again = client.get("/sleep/episodes?processed=false", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""

    # Sleep reads one: the waiting list changes, so the tag must move.
    _episode(bank, "ep_wait_a", hours_ago=3, processed=True)
    moved = client.get("/sleep/episodes?processed=false", headers={"If-None-Match": etag})
    assert moved.status_code == 200
    assert [row["id"] for row in moved.json()] == ["ep_wait_b"]
    assert moved.headers["ETag"] != etag


def test_each_query_has_its_own_tag(bank):
    client = TestClient(main.app)
    tags = {client.get(path).headers["ETag"] for path in (
        "/sleep/episodes", "/sleep/episodes?processed=false", "/sleep/episodes?processed=true",
        "/sleep/episodes?processed=true&limit=2", "/sleep/episodes?processed=true&limit=2&offset=2")}
    assert len(tags) == 5


def test_a_folder_rename_moves_the_tag(bank):
    """A folder file's row copies its full path from the folder registry, which is not an episode file."""
    _episode(bank, "ep_wait_file", hours_ago=1, relpath="notes/a.md", folder_id="fold1", origin="folder")
    client = TestClient(main.app)
    path = folder_source.registry_path(bank)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"folders": [{"id": "fold1", "path": "/tmp/one"}]}', encoding="utf-8")
    r = client.get("/sleep/episodes?processed=false")
    row = next(row for row in r.json() if row["id"] == "ep_wait_file")
    assert row["copyValue"] == "/tmp/one/notes/a.md"
    import os
    path.write_text('{"folders": [{"id": "fold1", "path": "/tmp/two"}]}', encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    moved = client.get("/sleep/episodes?processed=false", headers={"If-None-Match": r.headers["ETag"]})
    assert moved.status_code == 200
    assert next(row for row in moved.json() if row["id"] == "ep_wait_file")["copyValue"] == "/tmp/two/notes/a.md"


def test_an_episode_deleted_between_the_listing_and_its_body_read_is_skipped(bank, monkeypatch):
    """Capture keeps running: a file can go between `episode_headers` and its body read. The list skips it."""
    from api.routers import sleep as sleep_router

    real = sleep_router.episode_headers

    def listing_then_delete(memory_path, processed=None):
        headers = real(memory_path, processed)
        (bank / "episodes" / "ep_wait_a.md").unlink()
        return headers

    monkeypatch.setattr(sleep_router, "episode_headers", listing_then_delete)
    r = TestClient(main.app).get("/sleep/episodes?processed=false")
    assert r.status_code == 200
    assert [row["id"] for row in r.json()] == ["ep_wait_b"]


def test_list_all_episodes_skips_a_file_gone_before_its_body_read(bank, monkeypatch):
    from api.services import sleep_cycle

    real = sleep_cycle.episode_headers

    def listing_then_delete(memory_path, processed=None):
        headers = real(memory_path, processed)
        (bank / "episodes" / "ep_read_0.md").unlink()
        return headers

    monkeypatch.setattr(sleep_cycle, "episode_headers", listing_then_delete)
    ids = [e["id"] for e in sleep_cycle.list_all_episodes(bank)]
    assert "ep_read_0" not in ids and len(ids) == 7
