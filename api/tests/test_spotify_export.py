"""G32: Spotify's own download — plays as one index-only listening day each, the library as saved items.

Synthetic fixtures in Spotify's documented shapes (``fixtures/spotify/``: an Extended streaming history member and an
Account data download's streaming history and library; placeholders only), zipped here as Spotify sends them. No
network: a saved Spotify item is never fetched, and the suite fails any enrichment call.
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (bank_index, demo_guard, history_index, listening_history, markdown_parser, media_ingestor,
                          spotify_export)

FIX = Path(__file__).parent / "fixtures" / "spotify"


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(autouse=True)
def no_fetch(monkeypatch):
    async def refuse(*a, **kw):
        raise AssertionError("a Spotify item was fetched")
    monkeypatch.setattr(media_ingestor, "enrich", refuse)


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _zip(folder: str, members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(f"{folder}/{name}", data)
        zf.writestr(f"{folder}/Playlist1.json", b'{"playlists": [{"name": "never read"}]}')
        zf.writestr(f"{folder}/Userdata.json", b'{"email": "never read"}')
    return buf.getvalue()


def _extended() -> bytes:
    name = "Streaming_History_Audio_2026_0.json"
    return _zip("Spotify Extended Streaming History", {name: (FIX / "extended" / name).read_bytes()})


def _account() -> bytes:
    names = ("StreamingHistory_music_0.json", "StreamingHistory_podcast_0.json", "YourLibrary.json")
    return _zip("Spotify Account Data", {n: (FIX / "account" / n).read_bytes() for n in names})


def _upload(c, data: bytes, name: str = "my_spotify_data.zip", **params):
    return c.post("/sources/upload", files={"file": (name, data, "application/zip")}, params=params)


def _episodes(memory: Path) -> dict[str, markdown_parser.ParsedMarkdown]:
    out = {}
    for path in sorted((memory / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        out[str(parsed.frontmatter.get("source_id") or parsed.frontmatter.get("id"))] = parsed
    return out


def _days(memory: Path) -> dict[str, markdown_parser.ParsedMarkdown]:
    return {k: v for k, v in _episodes(memory).items() if k.startswith(listening_history.SOURCE_PREFIX)}


def test_extended_history_becomes_one_index_only_episode_per_listening_day(client):
    c, memory = client
    answer = _upload(c, _extended())
    assert answer.status_code == 200, answer.text
    days = _days(memory)
    assert sorted(days) == ["listening-history:spotify:2026-09-01", "listening-history:spotify:2026-09-03"]
    first = days["listening-history:spotify:2026-09-01"]
    fm = first.frontmatter
    assert fm["plays"] == 3 and fm["origin"] == "spotify-history" and fm["source"] == "listening-history"
    # Ruling 30: indexed, never read by a model.
    assert fm["processed"] is True and fm["processed_by"] == history_index.INDEXED_BY
    assert history_index.kind(fm) == "listening" and not history_index.waits_for_model(fm)
    assert "Example Song One — Artist A (Album A) · played 2 times" in first.body
    assert "Example Song Two — Artist B (Album B) · 0 min · skipped" in first.body
    podcast = days["listening-history:spotify:2026-09-03"].body
    assert "Episode 12: an example — Example Show · podcast" in podcast
    # A play is never a saved link: no media page, no url_index row.
    assert not list((memory / "entities").glob("*.md"))
    assert media_ingestor.load_url_index(memory) == {}
    assert "listening history" in answer.json()["message"]


def test_the_library_becomes_saved_items_without_a_fetch(client):
    c, memory = client
    assert _upload(c, _account()).status_code == 200
    index = media_ingestor.load_url_index(memory)
    assert len(index) == 4, index          # the track with no URI has no link to save
    pages = [markdown_parser.parse(p).frontmatter for p in (memory / "entities").glob("*.md")]
    assert {p.get("folder") for p in pages} == {"Liked Songs", "Saved albums", "Saved podcasts", "Saved episodes"}
    saves = [markdown_parser.parse(p).frontmatter for p in (memory / "episodes").glob("*.md")
             if markdown_parser.parse(p).frontmatter.get("origin") == spotify_export.SAVED_ORIGIN]
    assert len(saves) == 4 and all(history_index.kind(fm) == "list" for fm in saves)


def test_the_two_downloads_meet_without_doubling(client):
    """Account data's plays (to the minute, no URI) are the same plays as the extended history's (to the second):
    one play each, the account-only play added, and a repeat import writes nothing."""
    c, memory = client
    _upload(c, _extended())
    _upload(c, _account())
    days = _days(memory)
    assert days["listening-history:spotify:2026-09-01"].frontmatter["plays"] == 3
    assert days["listening-history:spotify:2026-09-03"].frontmatter["plays"] == 1
    assert days["listening-history:spotify:2026-09-02"].frontmatter["plays"] == 1
    from datetime import date

    played = listening_history._stored_rows(memory, date(2026, 9, 1))
    assert len(played) == 3
    assert all(r.get("uri") for r in played)            # the extended file's URIs kept
    stamps = {p: p.stat().st_mtime_ns for p in (memory / "episodes").glob("*.md")}
    again = _upload(c, _account()).json()
    assert "No new listening history" in again["message"]
    _upload(c, _extended())
    assert {p: p.stat().st_mtime_ns for p in (memory / "episodes").glob("*.md")} == stamps


def test_the_preview_says_what_comes_in_and_writes_nothing(client):
    c, memory = client
    answer = c.post("/intake/sniff", files={"file": ("my_spotify_data.zip", _account(), "application/zip")})
    body = answer.json()
    assert body["recognized"] is True and body["kind"] == "saved" and body["platform"] == "spotify"
    assert body["counts"]["items"] == 4 + 3        # four saved items, three listening days
    assert any("Listening history: 4 plays over 3 days" in w for w in body["warnings"])
    assert not list((memory / "episodes").glob("*.md"))


def test_one_spotify_file_dropped_by_itself_is_read(client):
    c, memory = client
    name = "Streaming_History_Audio_2026_0.json"
    data = (FIX / "extended" / name).read_bytes()
    assert c.post("/sources/upload", files={"file": (name, data, "application/json")}).status_code == 200
    assert len(_days(memory)) == 2


def test_names_are_scrubbed_and_a_demo_bank_takes_nothing(client, monkeypatch):
    c, memory = client
    entry = [{"endTime": "2026-09-05 10:00", "artistName": "Artist", "msPlayed": 60000,
              "trackName": "Song sk-abcdefghijklmnopqrstuvwx0123456789"}]
    data = _zip("Spotify Account Data", {"StreamingHistory_music_0.json": json.dumps(entry).encode()})
    _upload(c, data)
    text = "".join(p.read_text() for p in (memory / "episodes").glob("*.md"))
    assert "sk-abcdefghijklmnopqrstuvwx0123456789" not in text and "Song" in text
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    before = sorted((memory / "episodes").glob("*.md"))
    assert _upload(c, _extended()).status_code == 409
    assert sorted((memory / "episodes").glob("*.md")) == before


def test_plays_never_count_against_the_saves_cap(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(media_ingestor, "MAX_UPLOAD_ITEMS", 2)
    assert _upload(c, _extended()).status_code == 200      # five plays, no saves
    assert _upload(c, _account()).status_code == 413       # four saves over a cap of two


def test_only_spotifys_listening_and_library_members_are_read():
    for name in ("Playlist1.json", "SearchQueries.json", "Inferences.json", "Userdata.json", "Payments.json",
                 "Identifiers.json", "Follow.json"):
        assert not spotify_export.is_member(name), name
    for name in ("Streaming_History_Audio_2019-2021_0.json", "Streaming_History_Video_2020-2026.json",
                 "StreamingHistory_music_0.json", "StreamingHistory_podcast_1.json", "StreamingHistory0.json",
                 "YourLibrary.json"):
        assert spotify_export.is_member(name), name


def test_an_agent_reading_a_listening_day_by_id_is_told_what_it_is(client):
    """Ruling 30: an agent asking for a listening day by id gets one line saying what it is, never its words."""
    from types import SimpleNamespace

    from api.services import mcp_tools

    c, memory = client
    _upload(c, _extended())
    path = next(p for p in (memory / "episodes").glob("*.md")
                            if "listening-history" in p.read_text())
    ctx = SimpleNamespace(memory_path=lambda: memory, can=lambda tool: False, is_cli=False)
    reply = mcp_tools._episode_read(ctx, path.stem)
    assert "what the person listened to on Spotify" in str(reply) and "Example Song One" not in str(reply)
    assert reply.data["index_only"] == "listening"


def test_a_time_zone_change_between_imports_never_doubles_a_play(tmp_path, monkeypatch):
    """Review of #528, B2's repro: a play imported on a Mac in UTC, then again after it moved to New York, whose local
    day is the day before — still one play, and no second day."""
    from datetime import datetime, timezone

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)

    def plays():
        return [listening_history.Play(at=datetime(2026, 9, 1, 2, 30, tzinfo=timezone.utc), title="Song", by="A")]

    assert listening_history.record(memory, plays()).added == 1
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    again = listening_history.record(memory, plays())
    assert again.added == 0 and again.days_created == 0
    assert len(list((memory / "episodes").glob("*.md"))) == 1


def test_a_compilation_track_is_one_play_across_the_two_downloads(tmp_path):
    """Account data names a track's own artist, Extended its album artist: the same play, never two."""
    from datetime import datetime, timezone

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    at = datetime(2026, 9, 1, 8, 15, 42, tzinfo=timezone.utc)
    extended = listening_history.Play(at=at, title="Track On A Compilation", by="Various Artists", ms=200000,
                                      uri="spotify:track:0000000000000000000077")
    account = listening_history.Play(at=at.replace(second=0), title="Track On A Compilation", by="Artist Z",
                                     ms=200000)
    assert listening_history.record(memory, [extended]).added == 1
    assert listening_history.record(memory, [account]).added == 0


def test_the_play_rows_never_ride_an_episode_header(client):
    """Review of #528, B1: a listening day's play rows live beside it (``sources/listening/spotify/<day>.json``), never
    in the episode's frontmatter, which every cold start reads and caches (a decade of them cost a cold scan 9.5 s)."""
    c, memory = client
    _upload(c, _extended())
    for path in (memory / "episodes").glob("*.md"):
        assert "played:" not in path.read_text()
    rows = sorted((memory / "sources" / "listening" / "spotify").glob("*.json"))
    assert [p.name for p in rows] == ["2026-09-01.json", "2026-09-03.json"]
    assert len(json.loads(rows[0].read_text())) == 3


def test_two_tracks_sharing_a_name_are_two_plays(tmp_path):
    """Review of #528: two different "Intro"s (different URIs) ending 80 s apart, in one Extended file, are two plays —
    and an account-data play of one of them, with no URI, still meets it."""
    from datetime import datetime, timezone

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    a = listening_history.Play(at=datetime(2026, 9, 1, 10, 0, 30, tzinfo=timezone.utc), title="Intro", by="Artist A",
                               ms=80000, uri="spotify:track:" + "1" * 22)
    b = listening_history.Play(at=datetime(2026, 9, 1, 10, 1, 50, tzinfo=timezone.utc), title="Intro", by="Artist B",
                               ms=80000, uri="spotify:track:" + "2" * 22)
    assert listening_history.record(memory, [a, b]).added == 2
    account = listening_history.Play(at=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc), title="Intro",
                                     by="Artist A", ms=80000)
    assert listening_history.record(memory, [account]).added == 0
    assert listening_history.describe([listening_history.play_item(p) for p in (a, b)]) == (2, 1)


def test_a_failed_rows_write_leaves_no_stray_file(tmp_path, monkeypatch):
    from datetime import date

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(listening_history.os, "replace", boom)
    with pytest.raises(OSError):
        listening_history._write_rows(tmp_path, date(2026, 9, 1), [{"key": "k"}])
    folder = tmp_path / "sources" / "listening" / "spotify"
    assert list(folder.iterdir()) == []
