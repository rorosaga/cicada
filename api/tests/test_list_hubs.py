"""A saved list (playlist, board, collection, bookmark folder) is provenance, never a hub (owner 2026-10-19).

Synthetic bank only: every name, tag and URL here is a placeholder.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from api.config import Settings
from api.scripts import repair_list_hubs
from api.services import list_hub_repair, markdown_parser, media_ingestor
from api.services.hub_builder import regenerate_hubs_and_index
from api.services.id_utils import folder_tags
from api.services.media_ingestor import MediaMeta, RawItem

PLAYLIST = "Alpha Playlist"
SLUG = "alpha-playlist"


def _settings() -> Settings:
    return Settings(_env_file=None)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], capture_output=True, text=True, check=True).stdout


def _fm(memory: Path, eid: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter


def _legacy_media(memory: Path, eid: str, folder: str | None, tags: list[str], media_type: str = "youtube") -> None:
    """A media page as the writer left it before 2026-10-19: the folder's slug among its tags."""
    fm = {"name": eid.replace("-", " ").title(), "type": "media", "status": "active", "confidence": 0.7,
          "created": "2026-10-01", "last_referenced": "2026-10-01", "decay_class": "evergreen", "decay_rate": 0.0,
          "source_episodes": [], "tags": tags, "related": [], "version": 1, "folder": folder,
          "media": {"url": f"https://video.example/{eid}", "media_type": media_type}}
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, f"# {eid}\n\nA synthetic saved video.\n")


def _concept(memory: Path, eid: str, tags: list[str]) -> None:
    fm = {"name": eid.replace("-", " ").title(), "type": "concept", "status": "active", "confidence": 0.6,
          "created": "2026-10-01", "last_referenced": "2026-10-01", "decay_class": "active", "decay_rate": 0.05,
          "source_episodes": [], "tags": tags, "related": [], "version": 1}
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, f"## Summary\n{eid} is a synthetic fixture.\n")


def _list_hub(memory: Path, tag: str) -> None:
    """The ``topic-<tag>`` hub the old tagging produced (written as Stage 5.6 wrote it)."""
    fm = {"type": "hub", "hub_kind": "tag", "status": "active", "generated": "2026-10-18", "name": tag.title(),
          "member_count": 6, "version": 1, "source_tag": tag, "members": []}
    (memory / "hubs").mkdir(exist_ok=True)
    markdown_parser.write(memory / "hubs" / f"topic-{tag}.md", fm, f"## {tag.title()}\n")


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "bank"
    (memory / "entities").mkdir(parents=True)
    for i in range(6):
        _legacy_media(memory, f"media-video-{i}", PLAYLIST, sorted({"youtube", SLUG}))
    # A Netscape bookmark: the raw folder name was appended to the tags, and the person's own tag sits beside it.
    _legacy_media(memory, "media-page-a", "Reading", ["Reading", "reading", "url", "tag-01"], media_type="url")
    for i in range(5):
        _concept(memory, f"topic-example-{i}", ["tag-02"])
    _list_hub(memory, SLUG)
    regenerate_hubs_and_index(memory, _settings())   # the type hubs and _index.md as Sleep leaves them
    _list_hub(memory, SLUG)                          # …plus the list hub the old tagging held up
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "fixtures")
    return memory


def _idle():
    return False


# --- the rule ---------------------------------------------------------------


def test_folder_tags_names_the_raw_folder_and_its_slug():
    assert folder_tags(PLAYLIST) == {PLAYLIST, SLUG}
    assert folder_tags("Bookmarks bar/AI") == {"Bookmarks bar/AI", "bookmarks-bar-ai"}
    assert folder_tags(None) == set() and folder_tags("  ") == set()


# --- the writers ------------------------------------------------------------


def test_a_saved_video_keeps_its_playlist_as_folder_never_as_a_tag(tmp_path):
    item = RawItem(url="https://video.example/v1", title="V1", folder=PLAYLIST, origin="youtube-playlist")
    media_ingestor.write_media_entity(tmp_path, "media-v1", item, MediaMeta(title="V1", media_type="youtube"), "ep_1")
    fm = markdown_parser.parse(tmp_path / "media-v1.md").frontmatter
    assert fm["folder"] == PLAYLIST and fm["origin"] == "youtube-playlist"
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


def test_the_hub_tier_ignores_a_tag_the_folder_left_so_a_bank_heals_on_its_next_sleep(bank):
    result = regenerate_hubs_and_index(bank, _settings())
    stems = {Path(f).stem for f in result["hub_files"]}
    assert f"topic-{SLUG}" not in stems and not (bank / "hubs" / f"topic-{SLUG}.md").exists()
    assert "topic-tag-02" in stems     # a real shared tag still makes its hub
    assert "topic-youtube" in stems    # the media type is the writer's own tag, not the folder's
    assert "media" in stems            # every saved video is still in the Media type hub


# --- the repair -------------------------------------------------------------


def test_the_dry_run_counts_and_writes_nothing(bank):
    before = {p: p.read_bytes() for p in bank.rglob("*.md") if ".git" not in p.parts}
    counts = list_hub_repair.survey(bank).counts()
    assert counts["to_untag"] == 7 and counts["tags_removed"] == 8 and counts["list_hubs"] == 1
    assert counts["with_folder"] == 7 and counts["dirty"] == 0
    assert SLUG not in json.dumps(counts) and "media-video" not in json.dumps(counts)   # counts only
    assert {p: p.read_bytes() for p in bank.rglob("*.md") if ".git" not in p.parts} == before


def test_apply_folds_the_list_into_the_property_removes_the_hub_in_one_cicada_commit_and_reruns_as_a_no_op(bank):
    before = _fm(bank, "media-video-0")
    result = list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert result.untagged == 7 and result.hubs_removed == 1 and result.committed
    after = _fm(bank, "media-video-0")
    assert after["tags"] == ["youtube"] and after["folder"] == PLAYLIST
    assert {k: v for k, v in after.items() if k != "tags"} == {k: v for k, v in before.items() if k != "tags"}
    assert _fm(bank, "media-page-a")["tags"] == ["url", "tag-01"]   # order kept
    assert not (bank / "hubs" / f"topic-{SLUG}.md").exists()
    assert (bank / "hubs" / "topic-tag-02.md").exists()
    log = _git(bank, "log", "-1", "--format=%s%n%b")
    assert log.startswith("Saved lists are provenance, not hubs: 7 page(s) untagged, 1 hub(s) removed")
    assert "maintenance/list-hubs" in log and "Cicada-Author: cicada" in log
    assert f"hubs/topic-{SLUG}.md" in _git(bank, "show", "--name-only", "--format=", "HEAD")
    assert not _git(bank, "status", "--porcelain")
    head = _git(bank, "rev-parse", "HEAD")
    again = list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert again.untagged == 0 and again.list_hubs == 0 and not again.committed
    assert _git(bank, "rev-parse", "HEAD") == head and not _git(bank, "status", "--porcelain")


def test_a_bank_whose_hubs_already_healed_still_gets_its_pages_untagged(bank):
    regenerate_hubs_and_index(bank, _settings())
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "a sleep regenerated the hubs")
    assert list_hub_repair.survey(bank).list_hubs == 0
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
    assert (bank / "hubs" / f"topic-{SLUG}.md").exists()


def test_the_command(bank, capsys, monkeypatch):
    monkeypatch.setattr(repair_list_hubs, "_sleep_running", _idle)
    assert repair_list_hubs.main(["--bank", str(bank)]) == 0
    assert json.loads(capsys.readouterr().out)["to_untag"] == 7
    assert repair_list_hubs.main(["--bank", str(bank.parent / "missing")]) == 2
    capsys.readouterr()
    assert repair_list_hubs.main(["--bank", str(bank), "--apply"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["untagged"] == 7 and out["hubs_removed"] == 1 and out["committed"] is True


def test_a_large_repair_commits_in_parts_with_the_hub_tier_in_the_last(bank, monkeypatch):
    monkeypatch.setattr(list_hub_repair, "COMMIT_STEP", 3)
    head = _git(bank, "rev-parse", "HEAD").strip()
    result = list_hub_repair.apply(bank, sleep_running=_idle, settings=_settings())
    assert result.untagged == 7 and result.committed
    subjects = _git(bank, "log", "--format=%s", f"{head}..HEAD").splitlines()
    assert subjects == [f"Saved lists are provenance, not hubs: 7 page(s) untagged, 1 hub(s) removed (part {n} of 3)"
                        for n in (3, 2, 1)]
    assert f"hubs/topic-{SLUG}.md" in _git(bank, "show", "--name-only", "--format=", "HEAD")
    assert not _git(bank, "status", "--porcelain")
