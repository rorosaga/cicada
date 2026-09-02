"""Hermetic tests for ``api/scripts/backfill_bookmark_origins.py``.

Covers the live-test bugfix: bookmark-synced episodes/media entities that
predate G9 origin threading carry ``source: bookmark`` but no ``origin:``.
This script repairs them in place. Every test builds a throwaway
``memory/`` tree in ``tmp_path`` with hand-written episode/entity markdown —
the real ``memory/`` directory is never touched, and this script never runs
``git commit``.
"""

from __future__ import annotations

from pathlib import Path

from api.scripts import backfill_bookmark_origins as backfill
from api.services import markdown_parser


def _write_episode(
    memory: Path,
    episode_id: str,
    *,
    source: str = "bookmark",
    origin: str | None = None,
    media_entity_id: str | None = None,
    title: str | None = None,
) -> None:
    (memory / "episodes").mkdir(parents=True, exist_ok=True)
    fm: dict = {
        "id": episode_id,
        "timestamp": "2026-01-01T00:00:00Z",
        "source": source,
        "processed": True,
    }
    if origin is not None:
        fm["origin"] = origin
    if media_entity_id is not None:
        fm["media_entity_id"] = media_entity_id
    if title is not None:
        fm["title"] = title
    markdown_parser.write(memory / "episodes" / f"{episode_id}.md", fm, "some episode body")


def _write_entity(
    memory: Path,
    entity_id: str,
    *,
    origin: str | None = None,
    tags: list[str] | None = None,
    name: str | None = None,
    entity_type: str = "media",
) -> None:
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    fm: dict = {
        "name": name or entity_id,
        "type": entity_type,
        "status": "active",
        "confidence": 0.7,
        "source_episodes": [],
        "tags": tags or [],
        "version": 1,
    }
    if origin is not None:
        fm["origin"] = origin
    markdown_parser.write(memory / "entities" / f"{entity_id}.md", fm, "## Summary\n\nBody.")


# --- _infer_origin (pure) ----------------------------------------------------


def test_infer_origin_prefers_exact_chrome_tag():
    assert backfill._infer_origin({"tags": ["chrome-bookmark", "reading"]}) == "chrome-bookmark"


def test_infer_origin_prefers_exact_safari_tag():
    assert backfill._infer_origin({"tags": ["safari-bookmark"]}) == "safari-bookmark"


def test_infer_origin_folder_prefix_chrome():
    assert backfill._infer_origin({"tags": ["Bookmarks Bar/Tech"]}) == "chrome-bookmark"


def test_infer_origin_folder_prefix_safari():
    assert backfill._infer_origin({"tags": ["BookmarksBar/Reading"]}) == "safari-bookmark"


def test_infer_origin_folder_prefix_from_title_fallback():
    assert backfill._infer_origin({"tags": [], "title": "BookmarksBar Article"}) == "safari-bookmark"


def test_infer_origin_generic_fallback_when_no_clues():
    assert backfill._infer_origin({"tags": []}) == "bookmark"


# --- plan_backfill -----------------------------------------------------------


def test_plan_backfill_tag_preferred_path_propagates_to_paired_episode(tmp_path):
    memory = tmp_path / "memory"
    _write_entity(memory, "media-a", tags=["chrome-bookmark", "bookmark"])
    _write_episode(memory, "ep_2026-01-01_001", media_entity_id="media-a")

    plan = backfill.plan_backfill(memory)

    assert len(plan["entities"]) == 1
    assert plan["entities"][0]["origin"] == "chrome-bookmark"
    assert len(plan["episodes"]) == 1
    # Episode has no tags of its own -- it borrows the origin resolved for
    # its paired media entity via media_entity_id.
    assert plan["episodes"][0]["origin"] == "chrome-bookmark"


def test_plan_backfill_safari_folder_prefix_heuristic(tmp_path):
    memory = tmp_path / "memory"
    _write_entity(memory, "media-b", tags=["BookmarksBar/Reading List"])
    _write_episode(memory, "ep_2026-01-01_002", media_entity_id="media-b")

    plan = backfill.plan_backfill(memory)

    assert plan["entities"][0]["origin"] == "safari-bookmark"
    assert plan["episodes"][0]["origin"] == "safari-bookmark"


def test_plan_backfill_chrome_folder_prefix_heuristic(tmp_path):
    memory = tmp_path / "memory"
    _write_entity(memory, "media-c", tags=["Bookmarks Bar/Dev Reading"])
    _write_episode(memory, "ep_2026-01-01_003", media_entity_id="media-c")

    plan = backfill.plan_backfill(memory)

    assert plan["entities"][0]["origin"] == "chrome-bookmark"
    assert plan["episodes"][0]["origin"] == "chrome-bookmark"


def test_plan_backfill_generic_fallback_when_no_heuristic_matches(tmp_path):
    memory = tmp_path / "memory"
    _write_entity(memory, "media-d", tags=[])
    _write_episode(memory, "ep_2026-01-01_004", media_entity_id="media-d")

    plan = backfill.plan_backfill(memory)

    assert plan["entities"][0]["origin"] == "bookmark"
    assert plan["episodes"][0]["origin"] == "bookmark"


def test_plan_backfill_episode_without_linked_entity_infers_from_own_title(tmp_path):
    memory = tmp_path / "memory"
    _write_episode(
        memory,
        "ep_2026-01-01_005",
        media_entity_id="media-does-not-exist",
        title="BookmarksBar Orphan Episode",
    )

    plan = backfill.plan_backfill(memory)

    assert len(plan["episodes"]) == 1
    assert plan["episodes"][0]["origin"] == "safari-bookmark"


def test_plan_backfill_skips_already_stamped_files(tmp_path):
    memory = tmp_path / "memory"
    _write_entity(memory, "media-e", origin="chrome-bookmark", tags=["chrome-bookmark"])
    _write_episode(memory, "ep_2026-01-01_006", origin="chrome-bookmark", media_entity_id="media-e")

    plan = backfill.plan_backfill(memory)

    assert plan["entities"] == []
    assert plan["episodes"] == []


def test_plan_backfill_ignores_non_bookmark_episodes(tmp_path):
    memory = tmp_path / "memory"
    _write_episode(memory, "ep_2026-01-01_007", source="telegram")

    plan = backfill.plan_backfill(memory)

    assert plan["episodes"] == []


def test_plan_backfill_ignores_non_media_entities(tmp_path):
    memory = tmp_path / "memory"
    _write_entity(memory, "some-concept", entity_type="concept", tags=["chrome-bookmark"])

    plan = backfill.plan_backfill(memory)

    assert plan["entities"] == []


# --- apply_backfill ------------------------------------------------------


def test_apply_backfill_writes_origin_and_preserves_rest_of_frontmatter(tmp_path):
    memory = tmp_path / "memory"
    _write_entity(memory, "media-f", tags=["safari-bookmark"], name="Some Article")
    _write_episode(memory, "ep_2026-01-01_008", media_entity_id="media-f")

    plan = backfill.plan_backfill(memory)
    backfill.apply_backfill(plan)

    ent_fm = markdown_parser.parse(memory / "entities" / "media-f.md").frontmatter
    assert ent_fm["origin"] == "safari-bookmark"
    assert ent_fm["name"] == "Some Article"  # untouched

    ep_fm = markdown_parser.parse(memory / "episodes" / "ep_2026-01-01_008.md").frontmatter
    assert ep_fm["origin"] == "safari-bookmark"
    assert ep_fm["source"] == "bookmark"  # untouched


# --- main() / CLI -------------------------------------------------------


def test_main_dry_run_is_the_default_and_writes_nothing(tmp_path, capsys):
    memory = tmp_path / "memory"
    _write_entity(memory, "media-g", tags=["chrome-bookmark"])
    _write_episode(memory, "ep_2026-01-01_009", media_entity_id="media-g")

    rc = backfill.main(["--memory", str(memory)])
    assert rc == 0

    out = capsys.readouterr().out
    assert "[dry-run]" in out
    assert "media-g.md" in out or "media-g" in out

    # Nothing written -- still no origin on disk.
    ent_fm = markdown_parser.parse(memory / "entities" / "media-g.md").frontmatter
    assert "origin" not in ent_fm


def test_main_no_dry_run_writes_and_reports(tmp_path, capsys):
    memory = tmp_path / "memory"
    _write_entity(memory, "media-h", tags=["safari-bookmark"])
    _write_episode(memory, "ep_2026-01-01_010", media_entity_id="media-h")

    rc = backfill.main(["--memory", str(memory), "--no-dry-run"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "[dry-run]" not in out
    assert "backfilled" in out

    ent_fm = markdown_parser.parse(memory / "entities" / "media-h.md").frontmatter
    assert ent_fm["origin"] == "safari-bookmark"
    ep_fm = markdown_parser.parse(memory / "episodes" / "ep_2026-01-01_010.md").frontmatter
    assert ep_fm["origin"] == "safari-bookmark"


def test_main_requires_existing_memory_path(tmp_path, capsys):
    missing = tmp_path / "does-not-exist"
    rc = backfill.main(["--memory", str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "does not exist" in err


def test_main_requires_memory_argument():
    import pytest

    with pytest.raises(SystemExit):
        backfill.main([])


def test_main_dry_run_examples_capped_at_five(tmp_path, capsys):
    memory = tmp_path / "memory"
    for i in range(8):
        eid = f"media-cap-{i}"
        _write_entity(memory, eid, tags=["chrome-bookmark"])
        _write_episode(memory, f"ep_2026-01-01_{i:03d}", media_entity_id=eid)

    rc = backfill.main(["--memory", str(memory)])
    assert rc == 0

    out = capsys.readouterr().out
    # 8 entities + 8 episodes = 16 candidates, but only 5 examples are printed.
    example_lines = [line for line in out.splitlines() if line.strip().startswith("/")]
    assert len(example_lines) == 5
