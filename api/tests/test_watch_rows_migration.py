"""Speed 2026-10-29: a watched day's rows move out of its episode's frontmatter into `sources/watched/`, once.

Readers take either form (`watch_history.stored_rows`); the migration moves a legacy day's rows as they are, leaves
its body and hash alone, keeps a rows file a newer writer already made, commits as `cicada`, and runs once."""
from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import markdown_parser, watch_history, watch_rows_migration

VID = "aaaaaaaaaaa"


def _legacy_day(memory: Path, day: str, rows: list[dict], n: int = 1) -> Path:
    path = memory / "episodes" / f"ep_{day}_{n:03d}.md"
    markdown_parser.write(path, {
        "id": path.stem, "source": "watch-history", "source_id": f"watch-history:youtube:{day}", "platform": "youtube",
        "watched_on": day, "origin": "youtube-history", "processed": True, "processed_by": "index",
        "content_hash": "h", "videos": len(rows), "watched": rows,
    }, f"# Watched on YouTube · {day}\n\n- 09:14 · Bridge design")
    return path


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(memory)], check=True)
    for k, v in (("user.name", "Test"), ("user.email", "test@example.com")):
        subprocess.run(["git", "-C", str(memory), "config", k, v], check=True)
    return memory


ROW = {"url": f"https://www.youtube.com/watch?v={VID}", "title": "Bridge design", "channel": "alice-example",
       "times": ["2026-10-14T09:14:03+00:00"], "via": ["chrome"], "seen": ["2026-10-14T09:14:03+00:00"]}


def test_a_legacy_day_moves_once_and_reads_the_same(tmp_path):
    memory = _bank(tmp_path)
    page = _legacy_day(memory, "2026-10-14", [ROW])
    before = markdown_parser.parse(page)
    assert watch_history.day_rows(memory, before.frontmatter)[0]["url"] == ROW["url"]   # the legacy form reads

    assert watch_rows_migration.move_rows(memory) == 1
    after = markdown_parser.parse(page)
    assert "watched" not in after.frontmatter and after.body == before.body
    assert {k: v for k, v in after.frontmatter.items()} == {k: v for k, v in before.frontmatter.items() if k != "watched"}
    assert watch_history.stored_rows(memory, after.frontmatter) == [ROW]
    assert (memory / ".watch_rows_v1").exists()
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B", "--name-only"],
                         capture_output=True, text=True, check=True).stdout
    assert "Cicada-Author: cicada" in log and "sources/watched/youtube/2026-10-14.json" in log
    assert watch_rows_migration.move_rows(memory) == 0, "once"


def test_a_rows_file_a_newer_writer_made_is_kept(tmp_path):
    memory = _bank(tmp_path)
    page = _legacy_day(memory, "2026-10-15", [ROW])
    newer = [{**ROW, "times": ["2026-10-15T08:00:00+00:00"], "seen": ["2026-10-15T08:00:00+00:00"]}]
    watch_history.write_rows(memory, "youtube", watch_history.parse_day("2026-10-15"), newer)
    assert watch_rows_migration.move_rows(memory) == 1
    fm = markdown_parser.parse(page).frontmatter
    assert "watched" not in fm and watch_history.stored_rows(memory, fm) == newer


def test_a_record_after_the_move_writes_rows_beside_the_day_never_in_it(tmp_path):
    memory = _bank(tmp_path)
    watch_history.record(memory, [watch_history.make(f"https://www.youtube.com/watch?v={VID}",
                                                     at="2026-10-16T09:00:00Z", title="Bridge design", door="chrome")])
    [day] = [markdown_parser.parse(p) for p in (memory / "episodes").glob("*.md")
             if markdown_parser.parse(p).frontmatter.get("source") == "watch-history"]
    assert "watched" not in day.frontmatter and day.frontmatter["videos"] == 1
    assert watch_history.stored_rows(memory, day.frontmatter)[0]["url"].endswith(VID)


def _watch(vid: str, at: str):
    return watch_history.make(f"https://www.youtube.com/watch?v={vid}", at=at, title=f"Video {vid[:3]}", door="chrome")


def _day_urls(memory: Path, day: str) -> list[str]:
    for p in (memory / "episodes").glob("*.md"):
        fm = markdown_parser.parse(p).frontmatter
        if fm.get("source_id") == f"watch-history:youtube:{day}":
            return sorted(r["url"][-11:] for r in watch_history.stored_rows(memory, fm))
    return []


def test_a_rows_write_that_fails_never_loses_a_days_videos(tmp_path, monkeypatch):
    """Review of #533 (the blocker): staging drops a moved day's frontmatter copy, so its rows file is written FIRST.
    Sync 1 fails writing the rows; sync 2 still holds every video sync 1 had — both for a day written before the move
    (its frontmatter copy untouched) and for a new day (nothing staged, so the door's next sync brings it again)."""
    memory = _bank(tmp_path)
    _legacy_day(memory, "2026-10-14", [ROW])                       # video aaaaaaaaaaa, rows in frontmatter
    real = watch_history.write_rows

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(watch_history, "write_rows", broken)
    try:
        watch_history.record(memory, [_watch("bbbbbbbbbbb", "2026-10-14T11:00:00Z"),
                                      _watch("ccccccccccc", "2026-10-15T09:00:00Z")])
    except OSError:
        pass
    monkeypatch.setattr(watch_history, "write_rows", real)
    assert _day_urls(memory, "2026-10-14") == ["aaaaaaaaaaa"], "the failed sync dropped nothing"
    watch_history.record(memory, [_watch("bbbbbbbbbbb", "2026-10-14T11:00:00Z"),
                                  _watch("ccccccccccc", "2026-10-15T09:00:00Z")])
    assert _day_urls(memory, "2026-10-14") == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert _day_urls(memory, "2026-10-15") == ["ccccccccccc"]


def test_the_rows_signature_moves_on_every_rewrite_even_with_its_mtime_put_back(tmp_path):
    """Review of #533 (note 1): per file, with the inode — a coarse or put-back mtime never hides a rewrite."""
    import os

    memory = _bank(tmp_path)
    day = watch_history.parse_day("2026-10-14")
    watch_history.write_rows(memory, "youtube", day, [ROW])
    path = watch_history.rows_path(memory, "youtube", day)
    st = path.stat()
    before = watch_history.rows_signature(memory)
    watch_history.write_rows(memory, "youtube", day, [{**ROW, "title": "Bridge designs"}])
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    os.utime(path.parent, ns=(path.parent.stat().st_atime_ns, path.parent.stat().st_mtime_ns))
    assert watch_history.rows_signature(memory) != before


def test_never_automatic_a_dry_run_names_counts_and_ids_and_apply_moves_on_the_persons_word(tmp_path, monkeypatch):
    """A bulk write to the person's bank waits for their OK: start-up and a bank switch move nothing; the route's GET
    is the dry run (counts and day ids, nothing written) and its POST is the person's --apply."""
    from fastapi.testclient import TestClient

    from api import config, main
    from api.services import bank_migrations

    memory = _bank(tmp_path)
    page = _legacy_day(memory, "2026-10-14", [ROW, {**ROW, "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb"}])
    bank_migrations.run_bank_migrations(memory)
    assert "watched" in markdown_parser.parse(page).frontmatter, "never at start or on a bank switch"

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        plan = client.get("/maintenance/watched-rows").json()
        assert plan == {"days": 1, "rows": 2, "rows_files_kept": 0, "applied": False, "sample": [page.stem]}
        assert "watched" in markdown_parser.parse(page).frontmatter, "a dry run writes nothing"
        done = client.post("/maintenance/watched-rows").json()
        assert done["moved"] == 1 and done["days"] == 0 and done["applied"] is True
        assert "watched" not in markdown_parser.parse(page).frontmatter
        assert client.post("/maintenance/watched-rows").json()["moved"] == 0, "a second apply is a no-op"
    finally:
        config.get_settings.cache_clear()
