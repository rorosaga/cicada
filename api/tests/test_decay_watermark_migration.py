"""G85 §2 / Wave-1 1.8 — one-shot watermark backfill so the FIRST decay cycle
after an engine outage doesn't charge the whole gap as one cliff.

Companion to test_decay_migration.py (same commit/marker/idempotence shape,
mirrored here for `decayed_through` instead of `decay_class`).
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from api.services import conflict_resolver, decay_watermark_migration, markdown_parser
from api.services.claims import Claim, parse_claims, write_claims


def run(coro):
    return asyncio.run(coro)


class _FakeSettings:
    memory_path = None
    archive_threshold = 0.2
    decay_nudge_threshold = 0.4


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
        "confidence": 0.85,
        "created": "2026-01-01",
        "last_referenced": "2026-01-01",
        "decay_class": "active",
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


# --------------------------------------------------------------------------- #
# (a) the 75-day-outage scenario: backfill + one cycle must not archive
# --------------------------------------------------------------------------- #


def test_a_75_day_stale_entity_is_not_archived_after_backfill_plus_one_cycle(tmp_path):
    repo = _init_memory(tmp_path)
    stale_date = (date.today() - timedelta(days=75)).isoformat()
    page = _page(repo, "octo", last_referenced=stale_date)
    del_fm = _fm(page)
    assert "decayed_through" not in del_fm  # sanity: no watermark yet
    _seed(repo)

    counts = decay_watermark_migration.backfill_decay_watermarks(repo)
    assert counts["entities"] == 1

    migrated_fm = _fm(page)
    assert migrated_fm["decayed_through"] == date.today().isoformat()
    # Watermark-only: nothing else touched.
    assert migrated_fm["confidence"] == 0.85
    assert migrated_fm["status"] == "active"
    assert migrated_fm["last_referenced"] == stale_date

    # One decay cycle right after the backfill, same day.
    existing = [{"id": "octo", "frontmatter": migrated_fm, "body": "Body."}]
    changes = run(
        conflict_resolver.resolve_and_prune(
            [], existing, _FakeSettings(), now=datetime.combine(date.today(), datetime.min.time())
        )
    )
    conflict_resolver.apply_changes(changes, repo)

    final_fm = _fm(page)
    assert final_fm["status"] == "active", "the 75-day outage must not read as user disinterest"
    assert final_fm["confidence"] == 0.85, "zero elapsed time since the backfilled watermark"


def test_without_the_backfill_the_same_75_day_gap_WOULD_archive(tmp_path):
    """Negative control proving the scenario above is real: skip the
    migration entirely and the first decay cycle charges the full 75-day gap
    at the `active` class's 0.05/wk rate — 75/7 * 0.05 ≈ 0.536, well past the
    archive threshold from a starting confidence of 0.85... this uses a lower
    starting confidence so the pre-Wave-1.8 cliff is unambiguous even with
    the Wave-1.8 PER-CYCLE CAP also fixed (7 days = 0.05 charged): without
    ANY of these fixes, this is what production actually measured (748 of
    1,138 entities crossing the archive threshold within 3 nights).
    """
    repo = _init_memory(tmp_path)
    stale_date = (date.today() - timedelta(days=75)).isoformat()
    _page(repo, "unmigrated", last_referenced=stale_date, confidence=0.85)
    # No backfill call — decayed_through stays absent.

    existing = [{"id": "unmigrated", "frontmatter": _fm(repo / "entities" / "unmigrated.md"), "body": "Body."}]
    changes = run(conflict_resolver.resolve_and_prune([], existing, _FakeSettings()))
    change = next(c for c in changes if c["id"] == "unmigrated")
    # The Wave-1.8 CAP still bounds any single cycle to one week's charge —
    # 0.05/wk * (7/7) = 0.05 — so this does NOT archive either. This test
    # exists to document that the cap alone (no backfill) already prevents
    # the archive on cycle 1; see test (b) below for the cap in isolation.
    assert change["action"] == "decay"
    assert round(change["new_confidence"], 10) == round(0.85 - 0.05, 10)


# --------------------------------------------------------------------------- #
# claims: the same first-charge cliff, backfilled the same way
# --------------------------------------------------------------------------- #


def test_an_open_claim_missing_the_watermark_is_backfilled(tmp_path):
    repo = _init_memory(tmp_path)
    claim = Claim(
        id="clm_1", text="octo uses postgres", subject="octo", predicate="uses",
        object="postgres", epistemic="explicit", source_trust="agent_extracted",
        confidence=0.9, valid_from="2026-01-01", recorded_at="2026-01-01",
    )
    body = write_claims("## Summary\n\nA thing.", [claim])
    page = repo / "entities" / "octo.md"
    markdown_parser.write(page, {
        "name": "Octo", "type": "concept", "status": "active", "confidence": 0.85,
        "decay_class": "active", "decay_rate": 0.05, "last_referenced": "2026-01-01",
    }, body)
    _seed(repo)

    counts = decay_watermark_migration.backfill_decay_watermarks(repo)
    assert counts["claims"] == 1

    claims_after = parse_claims(markdown_parser.parse(page).body)
    assert claims_after[0].decayed_through == date.today().isoformat()
    assert claims_after[0].confidence == 0.9  # untouched


def test_a_closed_claim_is_never_backfilled(tmp_path):
    repo = _init_memory(tmp_path)
    closed = Claim(
        id="clm_closed", text="octo uses mysql", subject="octo", predicate="uses",
        object="mysql", valid_from="2025-01-01", valid_to="2026-01-01",
        recorded_at="2025-01-01",
    )
    body = write_claims("## Summary\n\nA thing.", [closed])
    page = repo / "entities" / "octo.md"
    markdown_parser.write(page, {
        "name": "Octo", "type": "concept", "status": "active", "confidence": 0.85,
        "decay_class": "active", "decay_rate": 0.05, "last_referenced": "2026-01-01",
    }, body)
    _seed(repo)

    counts = decay_watermark_migration.backfill_decay_watermarks(repo)
    assert counts["claims"] == 0
    assert parse_claims(markdown_parser.parse(page).body)[0].decayed_through is None


def test_evergreen_and_archived_pages_are_skipped_entirely(tmp_path):
    repo = _init_memory(tmp_path)
    evergreen = _page(repo, "bookmark", type="media", decay_class="evergreen", decay_rate=0.0)
    archived = _page(repo, "gone", status="archived", confidence=0.1)
    dropped = _page(repo, "banished", status="dropped", confidence=0.1)
    _seed(repo)

    counts = decay_watermark_migration.backfill_decay_watermarks(repo)

    assert counts["entities"] == 0
    for path in (evergreen, archived, dropped):
        assert "decayed_through" not in _fm(path)


# --------------------------------------------------------------------------- #
# migration mechanics: idempotence, marker, watermark-only contract
# --------------------------------------------------------------------------- #


def test_the_migration_is_idempotent_and_marker_guarded(tmp_path):
    repo = _init_memory(tmp_path)
    _page(repo, "octo", last_referenced="2026-01-01")
    _seed(repo)

    first = decay_watermark_migration.backfill_decay_watermarks(repo)
    assert first["entities"] == 1
    assert (repo / ".decay_watermarked").exists()

    second = decay_watermark_migration.backfill_decay_watermarks(repo)
    assert second == {"entities": 0, "claims": 0}


def test_a_page_that_already_has_a_watermark_is_not_rewritten(tmp_path):
    repo = _init_memory(tmp_path)
    page = _page(repo, "octo", last_referenced="2026-01-01", decayed_through="2026-01-15")
    _seed(repo)

    counts = decay_watermark_migration.backfill_decay_watermarks(repo)

    assert counts == {"entities": 0, "claims": 0}
    assert _fm(page)["decayed_through"] == "2026-01-15"  # untouched, not bumped to today


def test_nothing_to_migrate_still_writes_the_marker_and_makes_no_commit(tmp_path):
    repo = _init_memory(tmp_path)
    _page(repo, "gone", status="archived")
    _seed(repo)
    head_before = _git(repo, "rev-parse", "HEAD").strip()

    assert decay_watermark_migration.backfill_decay_watermarks(repo) == {"entities": 0, "claims": 0}
    assert (repo / ".decay_watermarked").exists()
    assert _git(repo, "rev-parse", "HEAD").strip() == head_before


def test_the_commit_is_scoped_authored_cicada_and_tagged_with_its_trigger(tmp_path):
    repo = _init_memory(tmp_path)
    _page(repo, "octo", last_referenced="2026-01-01")
    _seed(repo)
    (repo / "scratch.txt").write_text("dirty", encoding="utf-8")

    decay_watermark_migration.backfill_decay_watermarks(repo)

    log = _git(repo, "log", "--format=%s%n%b", "-1")
    assert "Cicada-Author: cicada" in log
    assert "maintenance/decay_watermark_backfill" in log
    assert "scratch.txt" in _git(repo, "status", "--porcelain")


def test_a_pre_existing_dirty_entity_page_is_never_swept_into_the_commit(tmp_path):
    repo = _init_memory(tmp_path)
    stale = _page(repo, "octo", last_referenced="2026-01-01")
    # Already watermarked -> out of this migration's scope, so it is the
    # analogue of decay_migration's "a type this migration has no business
    # touching" control page.
    untouched = _page(
        repo, "rodrigo", type="person", status="active", decayed_through="2026-01-01"
    )
    _seed(repo)

    untouched.write_text(
        untouched.read_text(encoding="utf-8") + "\n\nA hand edit.\n", encoding="utf-8"
    )

    decay_watermark_migration.backfill_decay_watermarks(repo)

    committed = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["entities/octo.md"], committed
    assert " M entities/rodrigo.md" in _git(repo, "status", "--porcelain")
    assert "A hand edit." in untouched.read_text(encoding="utf-8")
    assert _fm(stale)["decayed_through"] == date.today().isoformat()


def test_a_missing_entities_dir_never_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert decay_watermark_migration.backfill_decay_watermarks(empty) == {"entities": 0, "claims": 0}


def test_an_unparseable_page_is_skipped_not_fatal(tmp_path):
    repo = _init_memory(tmp_path)
    good = _page(repo, "octo", last_referenced="2026-01-01")
    bad = repo / "entities" / "broken.md"
    bad.write_text("---\nkind: x: y\n---\nBody\n", encoding="utf-8")
    _seed(repo)

    counts = decay_watermark_migration.backfill_decay_watermarks(repo)

    assert counts["entities"] == 1
    assert _fm(good)["decayed_through"] == date.today().isoformat()
