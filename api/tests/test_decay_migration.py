"""G66 §1.8 — the one-shot startup backfill (media -> evergreen, skills -> durable)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import decay_migration, markdown_parser


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _init_memory(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    (repo / "entities").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    return repo


def _page(repo: Path, entity_id: str, **fm) -> Path:
    base = {
        "name": entity_id.replace("-", " ").title(),
        "type": "concept",
        "status": "active",
        "confidence": 0.7,
        "created": "2026-01-01",
        "last_referenced": "2026-01-01",
        "decay_rate": 0.05,
        "source_episodes": [],
        "tags": [],
        "related": [],
        "version": 1,
    }
    base.update(fm)
    path = repo / "entities" / f"{entity_id}.md"
    markdown_parser.write(path, base, "## Summary\n\nA thing.")
    return path


def _fm(path: Path) -> dict:
    return markdown_parser.parse(path).frontmatter


def _seed(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")


def test_media_pages_become_evergreen_with_a_zero_rate(tmp_path):
    repo = _init_memory(tmp_path)
    a = _page(repo, "media-one", type="media", decay_rate=0.03)
    b = _page(repo, "media-two", type="media", decay_rate=0.03)
    _seed(repo)

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["media"] == 2
    for path in (a, b):
        fm = _fm(path)
        assert fm["decay_class"] == "evergreen"
        assert fm["decay_rate"] == 0.0


def test_decayed_and_archived_media_are_restored_to_active(tmp_path):
    repo = _init_memory(tmp_path)
    decayed = _page(repo, "media-fading", type="media", status="decaying", confidence=0.31)
    archived = _page(repo, "media-gone", type="media", status="archived", confidence=0.05)
    high = _page(repo, "media-strong", type="media", status="archived", confidence=0.92)
    _seed(repo)

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["restored"] == 3
    assert _fm(decayed)["status"] == "active" and _fm(decayed)["confidence"] == 0.7
    assert _fm(archived)["status"] == "active" and _fm(archived)["confidence"] == 0.7
    assert _fm(high)["confidence"] == 0.92, "never lower a confidence that is already higher"


def test_a_dropped_media_page_is_never_restored(tmp_path):
    repo = _init_memory(tmp_path)
    dropped = _page(repo, "media-banished", type="media", status="dropped", confidence=0.1)
    _seed(repo)

    decay_migration.backfill_decay_classes(repo)

    fm = _fm(dropped)
    assert fm["status"] == "dropped", "user-dismissed means never resurfaced"
    assert fm["decay_class"] == "evergreen", "the class is still corrected"


def test_skill_pages_become_durable_keeping_their_rate(tmp_path):
    repo = _init_memory(tmp_path)
    skill = _page(repo, "prefers-brevity", type="skill", decay_rate=0.02)
    _seed(repo)

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["skills"] == 1
    fm = _fm(skill)
    assert fm["decay_class"] == "durable"
    assert fm["decay_rate"] == 0.02


def test_other_types_are_left_completely_untouched(tmp_path):
    repo = _init_memory(tmp_path)
    person = _page(repo, "rodrigo", type="person")
    before = person.read_text(encoding="utf-8")
    _seed(repo)

    decay_migration.backfill_decay_classes(repo)

    assert person.read_text(encoding="utf-8") == before


def test_a_page_that_already_has_a_class_is_not_rewritten(tmp_path):
    repo = _init_memory(tmp_path)
    pinned = _page(repo, "media-pinned", type="media", decay_class="volatile", decay_rate=0.15)
    before = pinned.read_text(encoding="utf-8")
    _seed(repo)

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["media"] == 0
    assert pinned.read_text(encoding="utf-8") == before


def test_the_commit_is_scoped_authored_cicada_and_tagged_with_its_trigger(tmp_path):
    repo = _init_memory(tmp_path)
    _page(repo, "media-one", type="media")
    _seed(repo)
    # An unrelated dirty file must NOT be swept into the migration commit.
    (repo / "scratch.txt").write_text("dirty", encoding="utf-8")

    decay_migration.backfill_decay_classes(repo)

    log = _git(repo, "log", "--format=%s%n%b", "-1")
    assert "Cicada-Author: cicada" in log
    assert "maintenance/decay_class_backfill" in log
    assert "scratch.txt" in _git(repo, "status", "--porcelain")


def test_a_pre_existing_dirty_entity_page_is_never_swept_into_the_commit(tmp_path):
    """H2: the commit names EXACTLY the pages the migration rewrote.

    The old ``-- entities`` directory pathspec committed the working-tree state
    of every path under ``entities/``, so an unrelated hand edit — or a
    concurrent Sleep write — landed inside a ``Cicada-Author: cicada`` commit
    and corrupted the provenance ledger this system exists to keep honest.
    """
    repo = _init_memory(tmp_path)
    media = _page(repo, "media-one", type="media")
    untouched = _page(repo, "rodrigo", type="person")
    _seed(repo)

    # Someone (a person, or a Sleep cycle in another process) edits a page the
    # migration has no business touching.
    untouched.write_text(
        untouched.read_text(encoding="utf-8") + "\n\nA hand edit.\n", encoding="utf-8"
    )

    decay_migration.backfill_decay_classes(repo)

    committed = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["entities/media-one.md"], committed
    assert " M entities/rodrigo.md" in _git(repo, "status", "--porcelain")
    assert "A hand edit." in untouched.read_text(encoding="utf-8"), "edit left on disk"
    assert _fm(media)["decay_class"] == "evergreen"


def test_an_untracked_page_the_migration_rewrites_is_still_committed(tmp_path):
    """The scoped ``git add`` has to precede the scoped ``git commit``.

    A media page that was never committed is untracked; a bare
    ``git commit -- <path>`` would fail on it ("pathspec did not match"), the
    marker would not be written, and the migration would retry forever.
    """
    repo = _init_memory(tmp_path)
    _page(repo, "rodrigo", type="person")
    _seed(repo)
    _page(repo, "media-new", type="media")  # never committed

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["media"] == 1
    assert (repo / ".decay_classed").exists(), "a failed commit would skip the marker"
    assert "entities/media-new.md" in _git(repo, "show", "--name-only", "--format=", "HEAD")


def test_the_migration_is_idempotent_and_marker_guarded(tmp_path):
    repo = _init_memory(tmp_path)
    _page(repo, "media-one", type="media")
    _page(repo, "skill-one", type="skill")
    _seed(repo)

    first = decay_migration.backfill_decay_classes(repo)
    assert first["media"] == 1 and first["skills"] == 1
    assert (repo / ".decay_classed").exists()

    second = decay_migration.backfill_decay_classes(repo)
    assert second == {"media": 0, "skills": 0, "restored": 0}


def test_nothing_to_migrate_still_writes_the_marker_and_makes_no_commit(tmp_path):
    repo = _init_memory(tmp_path)
    _page(repo, "rodrigo", type="person")
    _seed(repo)
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    assert decay_migration.backfill_decay_classes(repo) == {
        "media": 0, "skills": 0, "restored": 0
    }
    assert (repo / ".decay_classed").exists()
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before


def test_a_non_git_directory_still_migrates_on_disk_without_raising(tmp_path):
    plain = tmp_path / "no-git"
    (plain / "entities").mkdir(parents=True)
    path = _page(plain, "media-one", type="media")

    counts = decay_migration.backfill_decay_classes(plain)

    assert counts["media"] == 1
    assert _fm(path)["decay_class"] == "evergreen"


def test_an_unparseable_page_is_skipped_not_fatal(tmp_path):
    repo = _init_memory(tmp_path)
    (repo / "entities" / "broken.md").write_text("---\n: : :\n---\nbody", encoding="utf-8")
    good = _page(repo, "media-one", type="media")
    _seed(repo)

    counts = decay_migration.backfill_decay_classes(repo)

    assert counts["media"] == 1
    assert _fm(good)["decay_class"] == "evergreen"


def test_a_missing_entities_dir_never_raises(tmp_path):
    assert decay_migration.backfill_decay_classes(tmp_path / "nope") == {
        "media": 0, "skills": 0, "restored": 0
    }
