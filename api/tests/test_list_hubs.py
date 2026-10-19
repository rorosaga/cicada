"""A saved list (playlist, board, collection, bookmark folder), a media type and an origin are provenance, never a
hub; a video in several playlists keeps them all (owner 2026-10-19).

Synthetic bank only: every name, tag and URL here is a placeholder.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from api.config import Settings
from api.scripts import repair_list_hubs
from api.services import git_service, list_hub_repair, markdown_parser, media_ingestor, sleep_cycle, write_admission
from api.services.hub_builder import regenerate_hubs_and_index
from api.services.id_utils import folder_tags, page_lists, provenance_tags
from api.services.media_ingestor import MediaMeta, PreparedItem, RawItem

PLAYLIST = "Alpha Playlist"
SLUG = "alpha-playlist"


def _settings() -> Settings:
    return Settings(_env_file=None)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], capture_output=True, text=True, check=True).stdout


def _fm(memory: Path, eid: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter


def _legacy_media(memory: Path, eid: str, folder: str | None, tags: list[str], media_type: str = "youtube",
                  origin: str | None = None) -> None:
    """A media page as the writer left it before 2026-10-19: the folder's slug among its tags."""
    fm = {"name": eid.replace("-", " ").title(), "type": "media", "status": "active", "confidence": 0.7,
          "created": "2026-10-01", "last_referenced": "2026-10-01", "decay_class": "evergreen", "decay_rate": 0.0,
          "source_episodes": [], "tags": tags, "related": [], "version": 1, "folder": folder,
          "media": {"url": f"https://video.example/{eid}", "media_type": media_type}}
    if origin:
        fm["origin"] = origin
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, f"# {eid}\n\nA synthetic saved video.\n")


def _concept(memory: Path, eid: str, tags: list[str]) -> None:
    fm = {"name": eid.replace("-", " ").title(), "type": "concept", "status": "active", "confidence": 0.6,
          "created": "2026-10-01", "last_referenced": "2026-10-01", "decay_class": "active", "decay_rate": 0.05,
          "source_episodes": [], "tags": tags, "related": [], "version": 1}
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, f"## Summary\n{eid} is a synthetic fixture.\n")


def _list_hub(memory: Path, tag: str) -> None:
    """A ``topic-<tag>`` hub the old tier produced (written as Stage 5.6 wrote it)."""
    fm = {"type": "hub", "hub_kind": "tag", "status": "active", "generated": "2026-10-18", "name": tag.title(),
          "member_count": 6, "version": 1, "source_tag": tag, "members": []}
    (memory / "hubs").mkdir(exist_ok=True)
    markdown_parser.write(memory / "hubs" / f"topic-{tag}.md", fm, f"## {tag.title()}\n")


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    for i in range(6):
        # `tag-03` stands for a tag Sleep or the person wrote for meaning: it keeps its hub.
        _legacy_media(memory, f"media-video-{i}", PLAYLIST, sorted({"youtube", SLUG, "tag-03"}),
                      origin="youtube-playlist")
    # A Netscape bookmark: the raw folder name was appended to the tags, and the person's own tag sits beside it.
    _legacy_media(memory, "media-page-a", "Reading", ["Reading", "reading", "url", "tag-01"], media_type="url")
    # Browser bookmarks from before `origin:` was written: the door's stamp is their only origin.
    for i in range(5):
        _legacy_media(memory, f"media-bookmark-{i}", None, ["bookmark", "chrome-bookmark"], media_type="bookmark")
    for i in range(5):
        _concept(memory, f"topic-example-{i}", ["tag-02"])
    regenerate_hubs_and_index(memory, _settings())   # the type hubs and _index.md as Sleep leaves them
    for tag in (SLUG, "youtube", "chrome-bookmark"):
        _list_hub(memory, tag)                       # …plus the hubs the old tagging held up
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "fixtures")
    return memory


def _idle():
    return False


# --- the rule ---------------------------------------------------------------


def test_provenance_is_a_media_pages_lists_type_kind_origin_and_door_stamp_never_a_meaning_tag():
    fm = {"type": "media", "folder": PLAYLIST, "collections": [PLAYLIST, "Beta List"], "origin": "youtube-playlist",
          "media": {"media_type": "youtube", "kind": "paper"},
          "tags": ["youtube", SLUG, "beta-list", "chrome-bookmark", "tag-03"]}
    assert provenance_tags(fm) == {PLAYLIST, SLUG, "Beta List", "beta-list", "youtube", "paper", "youtube-playlist",
                                   "chrome-bookmark"}
    # A concept page's tags are what Sleep or the person meant: none is provenance.
    assert provenance_tags({"type": "concept", "tags": ["youtube", "chrome-bookmark"]}) == set()


def test_page_lists_puts_folder_first_and_reads_a_page_from_before_collections():
    assert page_lists({"folder": PLAYLIST}) == [PLAYLIST]
    assert page_lists({"folder": PLAYLIST, "collections": [PLAYLIST, "Beta List"]}) == [PLAYLIST, "Beta List"]
    assert page_lists({}) == []


def test_folder_tags_names_the_raw_folder_and_its_slug():
    assert folder_tags(PLAYLIST) == {PLAYLIST, SLUG}
    assert folder_tags("Bookmarks bar/AI") == {"Bookmarks bar/AI", "bookmarks-bar-ai"}
    assert folder_tags(None) == set() and folder_tags("  ") == set()


# --- the writers ------------------------------------------------------------


def test_a_saved_video_keeps_its_playlist_as_folder_never_as_a_tag(tmp_path):
    item = RawItem(url="https://video.example/v1", title="V1", folder=PLAYLIST, origin="youtube-playlist")
    media_ingestor.write_media_entity(tmp_path, "media-v1", item, MediaMeta(title="V1", media_type="youtube"), "ep_1")
    fm = markdown_parser.parse(tmp_path / "media-v1.md").frontmatter
    assert fm["folder"] == PLAYLIST and fm["collections"] == [PLAYLIST] and fm["origin"] == "youtube-playlist"
    assert fm["tags"] == ["youtube"]


def test_a_tag_the_parser_took_from_the_folder_is_dropped_but_the_persons_own_tags_stay(tmp_path):
    item = RawItem(url="https://site.example/a", title="A", folder="Reading", tags=["Reading", "tag-01"])
    media_ingestor.write_media_entity(tmp_path, "media-a", item, MediaMeta(title="A", media_type="bookmark"), "ep_1")
    assert markdown_parser.parse(tmp_path / "media-a.md").frontmatter["tags"] == ["bookmark", "tag-01"]


def test_the_netscape_parser_keeps_the_folder_out_of_the_tags():
    html = """<!DOCTYPE NETSCAPE-Bookmark-file-1><DL><p><DT><H3>Reading</H3><DL><p>
      <DT><A HREF="https://blog.example/a" TAGS="tag-01">A</A></DL><p></DL>"""
    [item] = media_ingestor.parse_netscape_bookmarks(html)
    assert item.folder == "Reading" and item.tags == ["tag-01"]


def test_a_folder_named_like_the_media_type_never_takes_the_type_tag(tmp_path):
    item = RawItem(url="https://video.example/v2", title="V2", folder="YouTube")
    media_ingestor.write_media_entity(tmp_path, "media-v2", item, MediaMeta(title="V2", media_type="youtube"), "ep_1")
    assert markdown_parser.parse(tmp_path / "media-v2.md").frontmatter["tags"] == ["youtube"]


# --- the hub tier -----------------------------------------------------------


def test_the_hub_tier_gathers_no_page_by_its_provenance_so_a_bank_heals_on_its_next_sleep(bank):
    result = regenerate_hubs_and_index(bank, _settings())
    stems = {Path(f).stem for f in result["hub_files"]}
    for tag in (SLUG, "youtube", "chrome-bookmark", "bookmark"):
        assert f"topic-{tag}" not in stems and not (bank / "hubs" / f"topic-{tag}.md").exists()
    assert {"topic-tag-02", "topic-tag-03"} <= stems   # a tag written for meaning still makes its hub
    assert "media" in stems                            # every saved item is still in the Media type hub


# --- the repair -------------------------------------------------------------


def test_the_dry_run_counts_and_writes_nothing(bank):
    before = {p: p.read_bytes() for p in bank.rglob("*.md") if ".git" not in p.parts}
    counts = list_hub_repair.survey(bank, settings=_settings()).counts()
    assert counts["to_untag"] == 7 and counts["tags_removed"] == 8 and counts["with_folder"] == 7
    assert counts["tag_hubs"] == 5 and counts["list_hubs"] == 1 and counts["provenance_hubs"] == 2
    assert counts["other_hubs"] == 0 and counts["hubs_to_add"] == 0 and counts["dirty"] == 0
    assert SLUG not in json.dumps(counts) and "media-video" not in json.dumps(counts)   # counts only
    assert {p: p.read_bytes() for p in bank.rglob("*.md") if ".git" not in p.parts} == before


def test_apply_folds_the_list_into_the_property_removes_the_hub_in_one_cicada_commit_and_reruns_as_a_no_op(bank):
    before = _fm(bank, "media-video-0")
    result = list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert result.untagged == 7 and result.hubs_removed == 3 and result.committed
    after = _fm(bank, "media-video-0")
    assert after["tags"] == ["tag-03", "youtube"] and after["folder"] == PLAYLIST   # the media type tag stays
    assert {k: v for k, v in after.items() if k != "tags"} == {k: v for k, v in before.items() if k != "tags"}
    assert _fm(bank, "media-page-a")["tags"] == ["url", "tag-01"]   # order kept
    for tag in (SLUG, "youtube", "chrome-bookmark"):
        assert not (bank / "hubs" / f"topic-{tag}.md").exists()
    assert (bank / "hubs" / "topic-tag-02.md").exists() and (bank / "hubs" / "topic-tag-03.md").exists()
    assert _fm(bank, "media-bookmark-0")["tags"] == ["bookmark", "chrome-bookmark"]   # never stripped
    log = _git(bank, "log", "-1", "--format=%s%n%b")
    assert log.startswith("Saved lists and provenance are not hubs: 7 page(s) untagged, 3 hub(s) removed")
    assert "maintenance/list-hubs" in log and "Cicada-Author: cicada" in log
    assert f"hubs/topic-{SLUG}.md" in _git(bank, "show", "--name-only", "--format=", "HEAD")
    assert not _git(bank, "status", "--porcelain")
    head = _git(bank, "rev-parse", "HEAD")
    again = list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert again.untagged == 0 and again.hubs_to_drop == 0 and not again.committed
    assert _git(bank, "rev-parse", "HEAD") == head and not _git(bank, "status", "--porcelain")


def test_a_bank_whose_hubs_already_healed_still_gets_its_pages_untagged(bank):
    regenerate_hubs_and_index(bank, _settings())
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "a sleep regenerated the hubs")
    assert list_hub_repair.survey(bank, settings=_settings()).hubs_to_drop == 0
    result = list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert result.untagged == 7 and result.hubs_removed == 0 and result.committed
    assert not _git(bank, "status", "--porcelain")


def test_a_page_dirty_in_git_is_skipped(bank):
    path = bank / "entities" / "media-video-0.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nAn uncommitted edit.\n", encoding="utf-8")
    result = list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert result.dirty == 1 and result.untagged == 6
    assert SLUG in _fm(bank, "media-video-0")["tags"]
    assert "entities/media-video-0.md" not in _git(bank, "show", "--name-only", "--format=", "HEAD")


def test_apply_refuses_while_sleep_runs(bank):
    with pytest.raises(list_hub_repair.SleepRunning):
        list_hub_repair.apply(bank, sleep_running=lambda: True, settings=_settings())
    assert SLUG in _fm(bank, "media-video-0")["tags"]
    assert (bank / "hubs" / f"topic-{SLUG}.md").exists() and (bank / "hubs" / "topic-youtube.md").exists()


def test_the_command(bank, capsys, monkeypatch):
    monkeypatch.setattr(repair_list_hubs, "_sleep_running", _idle)
    assert repair_list_hubs.main(["--bank", str(bank)]) == 0
    assert json.loads(capsys.readouterr().out)["to_untag"] == 7
    assert repair_list_hubs.main(["--bank", str(bank.parent / "missing")]) == 2
    capsys.readouterr()
    assert repair_list_hubs.main(["--bank", str(bank), "--apply"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["untagged"] == 7 and out["hubs_removed"] == 3 and out["committed"] is True


def test_a_large_repair_commits_in_parts_with_the_hub_tier_in_the_last(bank, monkeypatch):
    monkeypatch.setattr(list_hub_repair, "COMMIT_STEP", 3)
    head = _git(bank, "rev-parse", "HEAD").strip()
    result = list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert result.untagged == 7 and result.committed
    subjects = _git(bank, "log", "--format=%s", f"{head}..HEAD").splitlines()
    assert subjects == ["Saved lists and provenance are not hubs: 7 page(s) untagged, 3 hub(s) removed (part 3 of 3)",
                        "Saved lists and provenance are not hubs: 7 page(s) untagged (part 2 of 3)",
                        "Saved lists and provenance are not hubs: 7 page(s) untagged (part 1 of 3)"]
    assert f"hubs/topic-{SLUG}.md" in _git(bank, "show", "--name-only", "--format=", "HEAD")
    assert not _git(bank, "status", "--porcelain")


# --- every list a video was saved from ---------------------------------------


def _offline(monkeypatch):
    async def fake_enrich(url, client, from_bookmark_file=False):
        return MediaMeta(title=media_ingestor._fallback_title(url), description="", site="video.example",
                         media_type="youtube")

    monkeypatch.setattr(media_ingestor, "enrich", fake_enrich)


def _git_bank(tmp_path) -> Path:
    memory = tmp_path / "bank"
    for sub in ("entities", "episodes", "sources"):
        (memory / sub).mkdir(parents=True)
    (memory / "README.md").write_text("synthetic\n", encoding="utf-8")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "fixtures")
    return memory


def _page_of(memory: Path, url: str) -> dict:
    idx = media_ingestor.load_url_index(memory)
    row = idx[media_ingestor.existing_hash(RawItem(url=url), idx)]
    return _fm(memory, row["media_entity_id"])


def test_one_export_with_a_video_in_two_playlists_keeps_both(tmp_path, monkeypatch):
    _offline(monkeypatch)
    memory = _git_bank(tmp_path)
    items = [RawItem(url="https://video.example/watch?v=1", folder=PLAYLIST, origin="youtube-playlist"),
             RawItem(url="https://video.example/watch?v=1", folder="Beta List", origin="youtube-playlist"),
             RawItem(url="https://video.example/watch?v=2", folder="Beta List", origin="youtube-playlist")]
    created, _ = asyncio.run(media_ingestor.ingest_batch(items, memory))
    assert created == 2
    fm = _page_of(memory, "https://video.example/watch?v=1")
    assert fm["folder"] == PLAYLIST and fm["collections"] == [PLAYLIST, "Beta List"]
    assert _page_of(memory, "https://video.example/watch?v=2")["collections"] == ["Beta List"]
    assert not _git(memory, "status", "--porcelain")   # the appended list rode the batch's own commit


def test_a_reimport_appends_the_other_playlists_of_a_video_already_saved_and_a_repeat_changes_nothing(
        tmp_path, monkeypatch):
    _offline(monkeypatch)
    memory = _git_bank(tmp_path)
    url = "https://video.example/watch?v=1"
    asyncio.run(media_ingestor.ingest_batch([RawItem(url=url, folder=PLAYLIST)], memory))
    head = _git(memory, "rev-parse", "HEAD")
    again = [RawItem(url=url, folder=PLAYLIST), RawItem(url=url, folder="Beta List")]
    assert asyncio.run(media_ingestor.ingest_batch(again, memory)) == (0, 2)
    assert _page_of(memory, url)["collections"] == [PLAYLIST, "Beta List"]
    assert _git(memory, "rev-parse", "HEAD") != head and not _git(memory, "status", "--porcelain")
    assert "Cicada-Author: user" in _git(memory, "log", "-1", "--format=%b")
    head = _git(memory, "rev-parse", "HEAD")
    asyncio.run(media_ingestor.ingest_batch(again, memory))
    assert _git(memory, "rev-parse", "HEAD") == head   # nothing new: no write, no commit


def test_a_repeat_save_through_write_prepared_appends_its_list_once(tmp_path):
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    url = "https://video.example/watch?v=1"
    meta = MediaMeta(title="V1", media_type="youtube")
    idx: dict = {}
    first = media_ingestor.write_prepared(PreparedItem(RawItem(url=url, folder=PLAYLIST), meta), memory, idx)
    assert first.status == "created" and not first.collection_added
    repeat = media_ingestor.write_prepared(PreparedItem(RawItem(url=url, folder="Watch later"), meta), memory, idx,
                                           append_list=True)
    assert repeat.status == "duplicate" and repeat.collection_added
    same = media_ingestor.write_prepared(PreparedItem(RawItem(url=url, folder="Watch later"), meta), memory, idx,
                                         append_list=True)
    assert not same.collection_added
    fm = _fm(memory, first.media_entity_id)
    assert fm["folder"] == PLAYLIST and fm["collections"] == [PLAYLIST, "Watch later"]
    assert "watch-later" not in fm["tags"]


def test_a_page_saved_with_no_list_takes_the_first_list_as_its_folder(tmp_path):
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    url = "https://video.example/watch?v=1"
    meta = MediaMeta(title="V1", media_type="youtube")
    idx: dict = {}
    first = media_ingestor.write_prepared(PreparedItem(RawItem(url=url), meta), memory, idx)
    media_ingestor.write_prepared(PreparedItem(RawItem(url=url, folder=PLAYLIST), meta), memory, idx, append_list=True)
    fm = _fm(memory, first.media_entity_id)
    assert fm["folder"] == PLAYLIST and fm["collections"] == [PLAYLIST]


def test_a_repeat_outside_an_admitted_caller_never_rewrites_the_page(tmp_path):
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir()
    url = "https://video.example/watch?v=1"
    meta = MediaMeta(title="V1", media_type="youtube")
    idx: dict = {}
    first = media_ingestor.write_prepared(PreparedItem(RawItem(url=url, folder=PLAYLIST), meta), memory, idx)
    repeat = media_ingestor.write_prepared(PreparedItem(RawItem(url=url, folder="Beta List"), meta), memory, idx)
    assert not repeat.collection_added and _fm(memory, first.media_entity_id)["collections"] == [PLAYLIST]


def test_while_sleep_holds_the_pages_a_repeat_appends_nothing_and_the_next_import_does(tmp_path, monkeypatch):
    _offline(monkeypatch)
    memory = _git_bank(tmp_path)
    url = "https://video.example/watch?v=1"
    asyncio.run(media_ingestor.ingest_batch([RawItem(url=url, folder=PLAYLIST)], memory))
    head = _git(memory, "rev-parse", "HEAD")
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    asyncio.run(media_ingestor.ingest_batch([RawItem(url=url, folder="Beta List")], memory))
    assert _page_of(memory, url)["collections"] == [PLAYLIST]
    assert _git(memory, "rev-parse", "HEAD") == head and not _git(memory, "status", "--porcelain")
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    asyncio.run(media_ingestor.ingest_batch([RawItem(url=url, folder="Beta List")], memory))
    assert _page_of(memory, url)["collections"] == [PLAYLIST, "Beta List"]


def test_the_append_and_its_commit_run_inside_admission_and_the_page_lock(tmp_path, monkeypatch):
    _offline(monkeypatch)
    memory = _git_bank(tmp_path)
    url = "https://video.example/watch?v=1"
    asyncio.run(media_ingestor.ingest_batch([RawItem(url=url, folder=PLAYLIST)], memory))
    seen = {}
    real_add, real_commit = media_ingestor.add_collection, git_service.commit_paths_sync

    def add(memory_path, entity_id, folder):
        seen["write"] = write_admission.holders(memory_path)
        return real_add(memory_path, entity_id, folder)

    def commit(memory_path, message, paths):
        seen["commit"] = write_admission.holders(memory_path)
        return real_commit(memory_path, message, paths)

    monkeypatch.setattr(media_ingestor, "add_collection", add)
    monkeypatch.setattr(git_service, "commit_paths_sync", commit)
    asyncio.run(media_ingestor.ingest_batch([RawItem(url=url, folder="Beta List")], memory))
    assert seen == {"write": 1, "commit": 1}
    assert write_admission.holders(memory) == 0


def test_a_large_append_commits_in_parts(tmp_path, monkeypatch):
    _offline(monkeypatch)
    memory = _git_bank(tmp_path)
    urls = [f"https://video.example/watch?v={i}" for i in range(5)]
    asyncio.run(media_ingestor.ingest_batch([RawItem(url=u, folder=PLAYLIST) for u in urls], memory))
    head = _git(memory, "rev-parse", "HEAD").strip()
    monkeypatch.setattr(media_ingestor, "COMMIT_STEP", 2)
    asyncio.run(media_ingestor.ingest_batch([RawItem(url=u, folder="Beta List") for u in urls], memory))
    assert len(_git(memory, "log", "--format=%s", f"{head}..HEAD").splitlines()) == 3
    assert not _git(memory, "status", "--porcelain")


def test_an_interrupted_apply_is_finished_and_committed_by_the_next_run(bank, monkeypatch):
    real = markdown_parser.write
    calls = {"n": 0}

    def flaky(path, fm, body):
        if "entities" in str(path):
            calls["n"] += 1
            if calls["n"] == 4:
                raise KeyboardInterrupt()
        return real(path, fm, body)

    monkeypatch.setattr(markdown_parser, "write", flaky)
    with pytest.raises(KeyboardInterrupt):
        list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    monkeypatch.setattr(markdown_parser, "write", real)
    assert _git(bank, "status", "--porcelain")                     # three pages untagged, uncommitted
    survey = list_hub_repair.survey(bank, settings=_settings())
    assert survey.adopted == 3 and survey.to_untag == 4 and survey.dirty == 0
    result = list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert result.untagged == 7 and result.hubs_removed == 3 and result.committed
    assert not _git(bank, "status", "--porcelain")
    assert "Cicada-Author: cicada" in _git(bank, "log", "-1", "--format=%b")
    assert all(SLUG not in _fm(bank, f"media-video-{i}")["tags"] for i in range(6))


def test_a_dirty_page_with_any_other_change_is_never_adopted(bank):
    path = bank / "entities" / "media-video-0.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "tags": ["tag-03", "youtube"]}, parsed.body + "\nAn edit.\n")
    survey = list_hub_repair.survey(bank, settings=_settings())
    assert survey.adopted == 0
    list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert "entities/media-video-0.md" in _git(bank, "status", "--porcelain")


def test_apply_refuses_when_git_cannot_list_dirty_pages(bank, monkeypatch):
    def broken(*_a, **_k):
        raise git_service.GitError("synthetic")

    monkeypatch.setattr(git_service, "dirty_paths_sync", broken)
    assert list_hub_repair.survey(bank, settings=_settings()).to_untag == 7   # a dry run still counts
    with pytest.raises(list_hub_repair.Refused):
        list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert SLUG in _fm(bank, "media-video-0")["tags"]
