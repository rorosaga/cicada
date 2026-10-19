"""The menu bar counts what waits for Sleep (owner 2026-10-19): `GET /status` carries `episodes.readable`, the same
count Sleep itself would read (`sleep_debt.readable_count`) — not a parked conversation, not index-only history
(ruling 30)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, markdown_parser, sleep_parked


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "episodes").mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    with TestClient(main.app) as c:
        yield c, tmp_path
    config.get_settings.cache_clear()


def _episode(memory, ep_id, **fm):
    markdown_parser.write(memory / "episodes" / f"{ep_id}.md",
                          {"id": ep_id, "processed": False, "source": "mcp",
                           "timestamp": "2026-10-18T10:00:00", **fm}, "A synthetic conversation.")


def test_status_counts_what_sleep_would_read(client):
    c, memory = client
    assert c.get("/status").json()["episodes"]["readable"] == 0
    for i in range(3):
        _episode(memory, f"ep_2026-10-18_00{i}")
    _episode(memory, "ep_2026-10-18_010", source="watch-history", source_id="watch-history:2026-10-18")
    _episode(memory, "ep_2026-10-18_011", processed=True)
    sleep_parked.park(memory, "ep_2026-10-18_002", "other", 2)
    bank_index.invalidate()
    body = c.get("/status").json()["episodes"]
    assert body["readable"] == 2, "three waiting, one of them parked; history and read ones never count"
    assert body["unprocessed"] == 3, "the older count is unchanged (it includes the parked one)"
