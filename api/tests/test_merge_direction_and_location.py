"""TDD coverage for two M5-prep backend fixes.

#1 — Merge direction: the inbox merge-resolve path must accept which entity id
    is the canonical SURVIVOR, so a merge can go either direction. Default
    (no survivor / survivor == target) keeps the legacy "absorb mention into
    target" behavior verbatim; survivor == the cleaner mention renames the
    surviving file to the cleaner slug.

#7 — Location dir-listing: a safe ``GET /entities/{id}/location`` reads a path
    from the location entity's frontmatter ONLY (never the request), lists the
    immediate children (name / isDir / size, bounded, no file reads), and
    degrades gracefully on missing / permission-denied / non-location.

Every test builds a throwaway git-backed memory workspace in a tmp dir; the live
``memory/`` is never touched.
"""

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.models.schemas import InboxResolveRequest
from api.services import inbox_service, markdown_parser


def run(coro):
    return asyncio.run(coro)


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


# --- workspace harness ------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _init_memory(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True, exist_ok=True)
    (repo / "inbox").mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    return repo


def _commit_all(repo: Path, msg: str = "seed") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _write_entity(repo: Path, eid: str, frontmatter: dict, body: str) -> Path:
    path = repo / "entities" / f"{eid}.md"
    markdown_parser.write(path, frontmatter, body)
    return path


def _write_merge_inbox(repo: Path, item_id: str, mention: str, target_hint: str) -> Path:
    fm = {
        "kind": "merge_suggestion",
        "required_input": "merge",
        "status": "pending",
        "entity_name": mention,
        "entity_id": inbox_service.sanitize_id(mention),
        "merge_target_hint": target_hint,
        "source_episode": "ep_2026-06-17_001",
        "source_episode_timestamp": "2026-06-17T10:00:00",
        "created_date": "2026-06-17",
    }
    path = repo / "inbox" / f"{item_id}.md"
    markdown_parser.write(path, fm, "Possible duplicate.")
    return path


# --- #1 merge direction -----------------------------------------------------


def test_merge_default_absorbs_mention_into_target(tmp_path):
    """Legacy behavior: no merge_survivor -> survivor is the existing target."""
    repo = _init_memory(tmp_path)
    _write_entity(
        repo,
        "driver-js-iife-build",
        {"name": "driver.js IIFE build", "type": "tool", "version": 2,
         "source_episodes": ["ep_old"], "last_referenced": "2026-01-01"},
        "The IIFE build.",
    )
    item = _write_merge_inbox(repo, "inbox-001", "driver.js", "driver-js-iife-build")
    _commit_all(repo)

    res = run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="merge", merge_target="driver-js-iife-build"), _Settings(repo)
    ))
    assert res["status"] == "resolved"
    # Target file survives unchanged in identity; mention file never created.
    assert (repo / "entities" / "driver-js-iife-build.md").exists()
    assert not (repo / "entities" / "driver-js.md").exists()
    assert not item.exists()
    survivor = markdown_parser.parse(repo / "entities" / "driver-js-iife-build.md")
    assert "ep_2026-06-17_001" in survivor.frontmatter["source_episodes"]
    assert survivor.frontmatter["version"] == 3
    assert "driver.js" in survivor.body  # absorbed-mention note


def test_merge_survivor_keeps_existing_when_stem_not_round_trippable(tmp_path):
    """Survivor names the EXISTING target by a value that does not round-trip
    through sanitize_id back to the on-disk stem (accented / punctuated stems
    like ``atlético-de-madrid``). Choosing "keep existing" must NOT rename the
    file — it must absorb the mention into the canonical on-disk file, leaving
    blame/history intact. Guards against deciding rename by raw-slug compare.
    """
    repo = _init_memory(tmp_path)
    # On-disk stem has an accented char + ampersand: sanitize_id won't reproduce it.
    target_stem = "atlético-&-real"
    _write_entity(
        repo,
        target_stem,
        {"name": "Atlético & Real", "type": "concept", "version": 4,
         "source_episodes": ["ep_old"], "last_referenced": "2026-01-01"},
        "The rivalry.",
    )
    item = _write_merge_inbox(repo, "inbox-004", "the derby", target_stem)
    _commit_all(repo)

    # User keeps the existing entity, sending its DISPLAY NAME as the survivor.
    res = run(inbox_service.resolve(
        "inbox-004",
        InboxResolveRequest(
            action="merge",
            merge_target=target_stem,
            merge_survivor="Atlético & Real",
        ),
        _Settings(repo),
    ))
    assert res["status"] == "resolved"
    # No rename: the canonical on-disk file still exists; no spurious slug file.
    assert (repo / "entities" / f"{target_stem}.md").exists()
    assert not (repo / "entities" / "atletico-real.md").exists()
    assert not item.exists()
    survivor = markdown_parser.parse(repo / "entities" / f"{target_stem}.md")
    assert "the derby" in survivor.body  # absorbed-mention note
    assert survivor.frontmatter["version"] == 5


def test_merge_survivor_is_mention_renames_to_cleaner_slug(tmp_path):
    """New path: survivor == the cleaner mention -> rename target file to the
    survivor slug, set name, carry over data + bump version."""
    repo = _init_memory(tmp_path)
    _write_entity(
        repo,
        "driver-js-iife-build",
        {"name": "driver.js IIFE build", "type": "tool", "version": 2,
         "source_episodes": ["ep_old"], "last_referenced": "2026-01-01",
         "confidence": 0.7},
        "The IIFE build details.",
    )
    item = _write_merge_inbox(repo, "inbox-002", "driver.js", "driver-js-iife-build")
    _commit_all(repo)

    res = run(inbox_service.resolve(
        "inbox-002",
        InboxResolveRequest(
            action="merge",
            merge_target="driver-js-iife-build",
            merge_survivor="driver.js",
        ),
        _Settings(repo),
    ))
    assert res["status"] == "resolved"
    # The cleaner-named file now exists; the old target file is gone.
    survivor_path = repo / "entities" / "driver-js.md"
    assert survivor_path.exists()
    assert not (repo / "entities" / "driver-js-iife-build.md").exists()
    assert not item.exists()

    survivor = markdown_parser.parse(survivor_path)
    assert survivor.frontmatter["name"] == "driver.js"
    # Carried-over data from the source target.
    assert survivor.frontmatter["confidence"] == 0.7
    assert "The IIFE build details." in survivor.body
    assert "ep_old" in survivor.frontmatter["source_episodes"]
    assert "ep_2026-06-17_001" in survivor.frontmatter["source_episodes"]
    assert survivor.frontmatter["version"] == 3


def test_merge_survivor_into_existing_survivor_file_appends_no_overwrite(tmp_path):
    """If a file already exists at the survivor slug, append into it (no clobber)."""
    repo = _init_memory(tmp_path)
    _write_entity(
        repo, "driver-js-iife-build",
        {"name": "driver.js IIFE build", "type": "tool", "version": 1,
         "source_episodes": ["ep_old"]},
        "Source body.",
    )
    _write_entity(
        repo, "driver-js",
        {"name": "driver.js", "type": "tool", "version": 5,
         "source_episodes": ["ep_keep"], "confidence": 0.9},
        "Existing survivor body.",
    )
    _write_merge_inbox(repo, "inbox-003", "driver.js", "driver-js-iife-build")
    _commit_all(repo)

    res = run(inbox_service.resolve(
        "inbox-003",
        InboxResolveRequest(
            action="merge", merge_target="driver-js-iife-build", merge_survivor="driver.js"
        ),
        _Settings(repo),
    ))
    assert res["status"] == "resolved"
    survivor = markdown_parser.parse(repo / "entities" / "driver-js.md")
    # Pre-existing survivor data is preserved, not overwritten.
    assert survivor.frontmatter["confidence"] == 0.9
    assert "Existing survivor body." in survivor.body
    assert "ep_keep" in survivor.frontmatter["source_episodes"]


# --- #7 location dir-listing ------------------------------------------------


def test_location_listing_lists_immediate_children(tmp_path):
    repo = _init_memory(tmp_path)
    target = tmp_path / "project_dir"
    (target / "subdir").mkdir(parents=True)
    (target / "a.txt").write_text("hello", encoding="utf-8")
    (target / "b.md").write_text("x" * 42, encoding="utf-8")

    _write_entity(
        repo, "src",
        {"name": "src", "type": "location", "path": str(target)},
        "The source directory.",
    )

    from api.routers import entities as entities_router

    resp = run(entities_router.get_entity_location("src", settings=_Settings(repo)))
    assert resp.path == str(target)
    assert resp.exists is True
    assert resp.accessible is True
    names = {e.name: e for e in resp.entries}
    assert set(names) == {"subdir", "a.txt", "b.md"}
    assert names["subdir"].is_dir is True
    assert names["a.txt"].is_dir is False
    assert names["a.txt"].size == 5
    assert names["b.md"].size == 42
    # dirs sorted first
    assert resp.entries[0].is_dir is True
    assert resp.truncated is False


def test_location_listing_path_in_body_when_no_frontmatter_path(tmp_path):
    repo = _init_memory(tmp_path)
    target = tmp_path / "from_body"
    target.mkdir()
    (target / "f.txt").write_text("y", encoding="utf-8")

    _write_entity(
        repo, "webapp-frontend",
        {"name": "webapp frontend", "type": "location"},
        f"Lives at {target} on disk.",
    )

    from api.routers import entities as entities_router

    resp = run(entities_router.get_entity_location("webapp-frontend", settings=_Settings(repo)))
    assert resp.path == str(target)
    assert resp.exists is True
    assert {e.name for e in resp.entries} == {"f.txt"}


def test_location_listing_missing_path(tmp_path):
    repo = _init_memory(tmp_path)
    _write_entity(
        repo, "gone",
        {"name": "gone", "type": "location", "path": str(tmp_path / "does_not_exist")},
        "Vanished.",
    )
    from api.routers import entities as entities_router

    resp = run(entities_router.get_entity_location("gone", settings=_Settings(repo)))
    assert resp.exists is False
    assert resp.entries == []


def test_location_listing_no_path_declared(tmp_path):
    repo = _init_memory(tmp_path)
    _write_entity(
        repo, "abstract",
        {"name": "abstract place", "type": "location"},
        "Just a description, no path.",
    )
    from api.routers import entities as entities_router

    resp = run(entities_router.get_entity_location("abstract", settings=_Settings(repo)))
    assert resp.path is None
    assert resp.exists is False
    assert resp.entries == []


def test_location_listing_rejects_non_location(tmp_path):
    repo = _init_memory(tmp_path)
    _write_entity(
        repo, "fastapi",
        {"name": "FastAPI", "type": "tool", "path": str(tmp_path)},
        "A web framework.",
    )
    from api.routers import entities as entities_router
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        run(entities_router.get_entity_location("fastapi", settings=_Settings(repo)))
    assert exc.value.status_code == 400


def test_location_listing_404_when_entity_missing(tmp_path):
    repo = _init_memory(tmp_path)
    from api.routers import entities as entities_router
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        run(entities_router.get_entity_location("nope", settings=_Settings(repo)))
    assert exc.value.status_code == 404


def test_location_listing_is_bounded(tmp_path):
    repo = _init_memory(tmp_path)
    target = tmp_path / "many"
    target.mkdir()
    for i in range(250):
        (target / f"f{i:03d}.txt").write_text("z", encoding="utf-8")
    _write_entity(
        repo, "big",
        {"name": "big", "type": "location", "path": str(target)},
        "Lots of files.",
    )
    from api.routers import entities as entities_router

    resp = run(entities_router.get_entity_location("big", settings=_Settings(repo)))
    assert len(resp.entries) <= 200
    assert resp.truncated is True


def test_location_listing_path_must_be_directory_not_file(tmp_path):
    repo = _init_memory(tmp_path)
    afile = tmp_path / "single.txt"
    afile.write_text("hi", encoding="utf-8")
    _write_entity(
        repo, "afilepath",
        {"name": "a file", "type": "location", "path": str(afile)},
        "Points at a file, not a dir.",
    )
    from api.routers import entities as entities_router

    resp = run(entities_router.get_entity_location("afilepath", settings=_Settings(repo)))
    # A file is not a listable directory -> exists False, no entries.
    assert resp.exists is False
    assert resp.entries == []
