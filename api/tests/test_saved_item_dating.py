"""Owner decision B (2026-10-22): a saved item's conversation takes the date it was saved, for new saves and imports.

benchmarks/newuser: three bookmarks saved in August and September were dated the import day, so Ask said "on
2026-10-22 Mara saved a guide". Like a calendar event (dated its start since #435), a new save's episode now carries the
day the person saved it — its id day and its timestamp — when the source records one. Existing episodes are never
renamed (ruling 34); a save with no recorded date is still dated the day Cicada took it in. Synthetic, example.com."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.services import markdown_parser, media_ingestor


def _write(tmp_path, **item):
    episodes = tmp_path / "episodes"
    raw = media_ingestor.RawItem(url="https://example.com/guide", **item)
    meta = media_ingestor.MediaMeta(title="A guide", media_type="bookmark")
    ep = media_ingestor.write_media_episode(episodes, raw, meta, "media-a-guide")
    return ep, markdown_parser.parse(episodes / f"{ep}.md").frontmatter


def test_a_save_with_a_recorded_instant_is_dated_that_instant(tmp_path):
    ep, fm = _write(tmp_path, added="2026-08-20", added_at="2026-08-20T19:30:00+00:00")
    assert ep.startswith("ep_2026-08-20_")
    assert str(fm["timestamp"]).startswith("2026-08-20T19:30:00")
    assert fm["saved_at"] == "2026-08-20"


def test_a_save_with_only_a_day_is_dated_that_day(tmp_path):
    ep, fm = _write(tmp_path, added="2026-09-08")
    assert ep.startswith("ep_2026-09-08_") and str(fm["timestamp"]).startswith("2026-09-08")


def test_a_save_with_no_date_is_dated_the_day_cicada_took_it_in(tmp_path):
    ep, fm = _write(tmp_path)
    today = datetime.now().strftime("%Y-%m-%d")
    assert ep.startswith(f"ep_{today}_") and "saved_at" not in fm


def test_a_save_dated_in_the_future_is_never_trusted_for_the_id(tmp_path):
    later = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec="seconds")
    ep, fm = _write(tmp_path, added_at=later)
    assert not ep.startswith(f"ep_{later[:10]}") or later[:10] == datetime.now().strftime("%Y-%m-%d")


def test_a_day_only_save_keeps_its_day_in_a_zone_past_plus_twelve(tmp_path, monkeypatch):
    """Review of #436: noon UTC is the next calendar day at UTC+14, so the id read through the moment moved the save a
    day later. The id day is the recorded day itself."""
    import time

    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    try:
        ep, fm = _write(tmp_path, added="2026-09-08")
    finally:
        monkeypatch.undo()
        time.tzset()
    assert ep.startswith("ep_2026-09-08_") and fm["saved_at"] == "2026-09-08"
