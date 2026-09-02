"""G114 R2 — the Sleep queue orders episodes by INSTANT, not by string.

A bank holds three timestamp shapes side by side and always will (R2 forbids
a migration): legacy naive-local (``2026-09-01T10:00:00`` — what the old
``datetime.now().isoformat() + "Z"`` writers meant, minus the false ``Z``),
``Z``-suffixed UTC from imports, and the new ``+00:00`` shape every writer
now emits. A lexical sort across those is wrong by the machine's UTC offset:
on a UTC+2 machine a naive ``10:00`` local IS ``08:00Z``, yet it sorts after
a ``08:30Z`` episode captured half an hour later. Both queue loaders
(``_get_unprocessed_episodes`` for the cycle, ``list_all_episodes`` for
``GET /sleep/episodes``) must agree on the true chronology.

The machine's zone is pinned to UTC+2 via ``TZ`` + ``tzset`` so the test is
deterministic on a UTC CI box, where naive-local and UTC coincide and the
old string sort would pass by accident.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import pytest

from api.services import bank_index, markdown_parser, sleep_cycle


@pytest.fixture
def utc_plus_two_tz():
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset unavailable on this platform")
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Etc/GMT-2"  # POSIX sign inversion: GMT-2 == UTC+2
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def _write(episodes_dir, ep_id: str, timestamp: str, *, processed: bool = False) -> None:
    markdown_parser.write(
        episodes_dir / f"{ep_id}.md",
        {
            "id": ep_id,
            "timestamp": timestamp,
            "source": "test",
            "title": ep_id,
            "processed": processed,
            "content_hash": ep_id[-3:],
        },
        f"# {ep_id}\n\nplaceholder body",
    )


def _seed(tmp_path):
    """Three episodes whose id order, string order and instant order all differ.

    True chronology (UTC): ``_003`` (07:30Z) < ``_001`` (08:00Z, written as
    naive local 10:00 on a UTC+2 machine) < ``_002`` (08:30Z).
    A string sort puts the naive ``10:00`` LAST; an id sort puts it FIRST.
    """
    memory = tmp_path / "memory"
    episodes = memory / "episodes"
    episodes.mkdir(parents=True)
    naive_local = (
        datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
        .astimezone()
        .replace(tzinfo=None)
        .isoformat()
    )
    assert naive_local == "2026-09-01T10:00:00"  # the fixture really pinned UTC+2
    _write(episodes, "ep_2026-09-01_001", naive_local)
    _write(episodes, "ep_2026-09-01_002", "2026-09-01T08:30:00+00:00")
    _write(episodes, "ep_2026-09-01_003", "2026-09-01T07:30:00Z")
    return memory


EXPECTED = ["ep_2026-09-01_003", "ep_2026-09-01_001", "ep_2026-09-01_002"]


def test_unprocessed_queue_orders_by_instant(tmp_path, utc_plus_two_tz):
    memory = _seed(tmp_path)
    bank_index.invalidate(memory)
    ids = [e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)]
    assert ids == EXPECTED


def test_list_all_episodes_orders_by_instant(tmp_path, utc_plus_two_tz):
    memory = _seed(tmp_path)
    ids = [e["id"] for e in sleep_cycle.list_all_episodes(memory)]
    assert ids == EXPECTED


def test_missing_timestamp_sorts_first_by_id(tmp_path, utc_plus_two_tz):
    """An episode with no parseable timestamp must not raise or hide the
    queue — it sorts first (empty key), then by id, exactly as before."""
    memory = _seed(tmp_path)
    _write(memory / "episodes", "ep_2026-08-31_001", "not a timestamp")
    ids = [e["id"] for e in sleep_cycle.list_all_episodes(memory)]
    assert ids == ["ep_2026-08-31_001"] + EXPECTED
