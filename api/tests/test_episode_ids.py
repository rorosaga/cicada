"""G114 Task 1 — the one episode-id rule + the one clock every capture writer shares.

Before ``episode_ids.py`` existed each writer (importer, MCP, media, Telegram,
calendar, notes) carried its own copy of "next ``ep_<date>_NNN``" and its own
idea of what a timestamp looks like. Two of those copies were count-based and
collided after any deletion; three stamped naive local time with a ``Z``
suffix. These tests pin the rulings (R1: max-suffix+1 per date; R2: aware-UTC
ISO-8601 with ``+00:00``) so a future writer that reaches for a private copy
has something to fail against.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from api.services import episode_ids


# --- parse_episode_id --------------------------------------------------------


def test_parse_episode_id_accepts_three_and_four_digit_suffixes():
    assert episode_ids.parse_episode_id("ep_2026-09-01_001") == ("2026-09-01", 1)
    assert episode_ids.parse_episode_id("ep_2026-09-01_1000") == ("2026-09-01", 1000)


def test_parse_episode_id_rejects_junk():
    assert episode_ids.parse_episode_id("ep_2026-09-01_x") is None
    assert episode_ids.parse_episode_id("ep_2026-09-01") is None
    assert episode_ids.parse_episode_id("sleep_2026-09-01_001") is None
    assert episode_ids.parse_episode_id("ep_2026-09-01_001.md") is None


# --- next_episode_id (R1) ----------------------------------------------------


def test_next_episode_id_is_max_plus_one_not_count_plus_one(tmp_path):
    (tmp_path / "ep_2026-09-01_001.md").write_text("x")
    (tmp_path / "ep_2026-09-01_005.md").write_text("x")
    # count-based would say _003 and clobber nothing today, then collide
    # with _005 two writes later; max+1 never does.
    assert episode_ids.next_episode_id(tmp_path, "2026-09-01") == "ep_2026-09-01_006"


def test_next_episode_id_empty_dir_starts_at_001(tmp_path):
    assert episode_ids.next_episode_id(tmp_path, "2026-09-01") == "ep_2026-09-01_001"


def test_next_episode_id_missing_dir_starts_at_001(tmp_path):
    assert episode_ids.next_episode_id(tmp_path / "nope", "2026-09-01") == "ep_2026-09-01_001"


def test_next_episode_id_ignores_junk_files(tmp_path):
    (tmp_path / "ep_2026-09-01_x.md").write_text("x")
    (tmp_path / "ep_2026-09-01_002.md").write_text("x")
    (tmp_path / "notes.md").write_text("x")
    assert episode_ids.next_episode_id(tmp_path, "2026-09-01") == "ep_2026-09-01_003"


def test_next_episode_id_four_digit_suffix_keeps_counting(tmp_path):
    (tmp_path / "ep_2026-09-01_1000.md").write_text("x")
    assert episode_ids.next_episode_id(tmp_path, "2026-09-01") == "ep_2026-09-01_1001"


def test_next_episode_id_other_dates_do_not_interfere(tmp_path):
    (tmp_path / "ep_2026-08-31_009.md").write_text("x")
    (tmp_path / "ep_2026-09-02_004.md").write_text("x")
    assert episode_ids.next_episode_id(tmp_path, "2026-09-01") == "ep_2026-09-01_001"


# --- max_suffix_by_date ------------------------------------------------------


def test_max_suffix_by_date_mixed_dir(tmp_path):
    for name in (
        "ep_2026-09-01_001.md",
        "ep_2026-09-01_005.md",
        "ep_2026-09-01_003.md",
        "ep_2026-08-31_002.md",
        "ep_2026-08-31_001.md",
        "ep_2026-08-31_x.md",
        "README.md",
    ):
        (tmp_path / name).write_text("x")
    assert episode_ids.max_suffix_by_date(tmp_path) == {
        "2026-09-01": 5,
        "2026-08-31": 2,
    }


def test_max_suffix_by_date_missing_dir_is_empty(tmp_path):
    assert episode_ids.max_suffix_by_date(tmp_path / "nope") == {}


# --- utc_now_iso / to_utc_iso (R2) -------------------------------------------


def test_utc_now_iso_is_aware_utc():
    stamp = episode_ids.utc_now_iso()
    assert stamp.endswith("+00:00")
    parsed = datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def _memory(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    return memory


def _calendar_episode(tmp_path):
    from api.services import calendar_registry

    episodes = _memory(tmp_path) / "episodes"
    event = calendar_registry.ICSEvent(
        uid="evt-1", summary="Placeholder event", dtstart_iso="2026-07-14T10:00:00+00:00",
        dtend_iso="2026-07-14T11:00:00+00:00", all_day=False, location=None, description=None, sequence=0,
        recurring=False)
    # Straight through the writer: no ICS window filtering, so nothing here is date-baked.
    return episodes / f"{calendar_registry._write_calendar_episode(episodes, event, 'https://a.example.com/cal.ics')}.md"


def _imported_conversation(tmp_path):
    from api.routers import conversations as conv

    episodes = _memory(tmp_path) / "episodes"
    episode = {"title": "T", "source": "claude_memory", "messages": [], "timestamp": None}
    return conv._write_new_episode(episode, episodes, "system: x", "abc123", {})


def _apple_note(tmp_path):
    import asyncio

    from api.services import notes_sync

    memory = _memory(tmp_path)
    note = notes_sync.FIELD_SEP.join(["note-1", "Grocery list", "Milk, eggs, bread", "2026-07-01", "2026-07-01",
                                      "Personal"])
    asyncio.run(notes_sync.sync_notes(memory, dump=note))
    (path,) = (memory / "episodes").glob("ep_*.md")
    return path


def _saved_link(tmp_path):
    from api.services import media_ingestor
    from api.services.media_ingestor import MediaMeta, RawItem

    episodes = tmp_path / "episodes"
    ep_id = media_ingestor.write_media_episode(episodes, RawItem(url="https://example.com/a"),
                                               MediaMeta(title="A", media_type="url"), "media-a")
    return episodes / f"{ep_id}.md"


@pytest.mark.parametrize("write", [_calendar_episode, _imported_conversation, _apple_note, _saved_link],
                         ids=["calendar", "conversation-import", "apple-notes", "media"])
def test_every_writer_stamps_its_episode_aware_utc_now(tmp_path, write):
    """R2 at the writers that once had their own clock: the episode ``timestamp`` is aware UTC with an explicit
    ``+00:00`` and is now — never the old naive-local ``datetime.now().isoformat() + "Z"``, which labelled the
    machine's wall clock as UTC and was off by its offset."""
    from api.services import markdown_parser

    ts = markdown_parser.parse(write(tmp_path)).frontmatter["timestamp"]
    assert isinstance(ts, str) and ts.endswith("+00:00"), ts
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - parsed).total_seconds()) < 60


def test_to_utc_iso_epoch_zero():
    assert episode_ids.to_utc_iso(0) == "1970-01-01T00:00:00+00:00"
    assert episode_ids.to_utc_iso(0.0) == "1970-01-01T00:00:00+00:00"


def test_to_utc_iso_naive_datetime_is_assumed_utc():
    assert episode_ids.to_utc_iso(datetime(2026, 1, 1, 12, 0)) == "2026-01-01T12:00:00+00:00"


def test_to_utc_iso_aware_datetime_converts():
    plus_two = timezone(timedelta(hours=2))
    assert (
        episode_ids.to_utc_iso(datetime(2026, 1, 1, 12, 0, tzinfo=plus_two))
        == "2026-01-01T10:00:00+00:00"
    )


# --- timestamp_sort_key ------------------------------------------------------


def test_timestamp_sort_key_z_and_offset_agree():
    assert episode_ids.timestamp_sort_key("2026-09-01T08:00:00Z") == episode_ids.timestamp_sort_key(
        "2026-09-01T08:00:00+00:00"
    )
    assert episode_ids.timestamp_sort_key("2026-09-01T08:00:00Z") == "2026-09-01T08:00:00+00:00"


def test_timestamp_sort_key_non_utc_offset_normalises():
    assert episode_ids.timestamp_sort_key("2026-09-01T10:00:00+02:00") == "2026-09-01T08:00:00+00:00"


@pytest.fixture
def utc_plus_two_tz():
    """Pin the process to a UTC+2 zone (no DST) for the naive-input test.

    ``TZ`` + ``tzset`` is the only lever that changes what ``astimezone()``
    considers "local"; restored afterwards so nothing else in the suite sees it.
    """
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


def test_timestamp_sort_key_naive_input_is_local_time(utc_plus_two_tz):
    # A legacy naive stamp written by `datetime.now().isoformat()` on a UTC+2
    # machine at 10:00 local IS 08:00 UTC — the same instant as the two aware
    # shapes above. This is exactly `sleep_debt._parse_episode_timestamp`'s
    # reading, so the queue sort agrees with the sleep-debt maths.
    assert (
        episode_ids.timestamp_sort_key("2026-09-01T10:00:00")
        == episode_ids.timestamp_sort_key("2026-09-01T08:00:00Z")
        == "2026-09-01T08:00:00+00:00"
    )


def test_timestamp_sort_key_unparseable_is_empty():
    assert episode_ids.timestamp_sort_key(None) == ""
    assert episode_ids.timestamp_sort_key("") == ""
    assert episode_ids.timestamp_sort_key("yesterday-ish") == ""
    assert episode_ids.timestamp_sort_key(12345) == ""  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", ["0001-01-01T00:00:00", "9999-12-31T23:59:59"])
def test_timestamp_sort_key_extreme_naive_year_is_empty_not_raised(raw):
    """A naive stamp at the calendar's edge parses, but the local->UTC
    conversion walks it out of range and raised ValueError — which aborted the
    whole Sleep queue for one absurd file (G114 final review). It must degrade
    to "" exactly like garbage does."""
    assert episode_ids.timestamp_sort_key(raw) == ""
