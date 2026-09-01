"""The nightly connector poll rides the Sleep cycle's tail (G71 §2 + Task 14).

Mirrors test_sleep_cycle_logo_warmup.py: hermetic, no network, no real model.
Covers all three peer connectors — Pinterest, Reddit, and X. The idle-path
tests below stay no-real-git; the final-review H1 regression test at the
bottom uses REAL git (mirrors test_sleep_cycle_logo_warmup.py's staleness
test) because it inspects the actual commits the tail poll and `_finalize`
produce, not just that both ran.
"""

from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

from api.services import markdown_parser, media_ingestor, predicates, sleep_cycle


def _empty_memory(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _settings(memory):
    return SimpleNamespace(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        archive_threshold=0.2,
        decay_nudge_threshold=0.4,
        link_enrich_enabled=False,
        inbox_stale_after_days=90,
    )


def test_connectors_are_polled_on_the_idle_early_return(tmp_path, monkeypatch):
    """A quiet night still has to pull new pins, saves, and bookmarks."""
    memory = _empty_memory(tmp_path)
    calls = []

    async def fake_sync(memory_path, **kwargs):
        calls.append(memory_path)
        return {"status": "ok", "new": 0, "seen": 0, "error": None}

    monkeypatch.setattr("api.services.connectors.pinterest.sync", fake_sync)
    monkeypatch.setattr("api.services.connectors.reddit.sync", fake_sync)
    monkeypatch.setattr("api.services.connectors.x.sync", fake_sync)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-empty"))

    assert calls == [memory, memory, memory]
    assert sleep_cycle.get_sleep_state().status == "idle"


def test_a_failing_connector_never_fails_the_cycle_or_stops_its_peers(tmp_path, monkeypatch):
    memory = _empty_memory(tmp_path)
    calls = []

    async def boom(memory_path, **kwargs):
        raise RuntimeError("token expired")

    async def ok(memory_path, **kwargs):
        calls.append(memory_path)
        return {"status": "ok", "new": 0, "seen": 0, "error": None}

    monkeypatch.setattr("api.services.connectors.pinterest.sync", boom)
    monkeypatch.setattr("api.services.connectors.reddit.sync", ok)
    monkeypatch.setattr("api.services.connectors.x.sync", ok)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-boom"))
    assert sleep_cycle.get_sleep_state().status == "idle"
    assert sleep_cycle.get_sleep_state().error is None
    assert calls == [memory, memory], "Pinterest raising must not stop Reddit's or X's poll"


def test_x_failing_never_fails_the_cycle_or_stops_its_peers(tmp_path, monkeypatch):
    """Same guarantee, X-as-the-failing-adapter — order in the poll tuple
    must not matter for isolation."""
    memory = _empty_memory(tmp_path)
    calls = []

    async def boom(memory_path, **kwargs):
        raise RuntimeError("rate limited")

    async def ok(memory_path, **kwargs):
        calls.append(memory_path)
        return {"status": "ok", "new": 0, "seen": 0, "error": None}

    monkeypatch.setattr("api.services.connectors.pinterest.sync", ok)
    monkeypatch.setattr("api.services.connectors.reddit.sync", ok)
    monkeypatch.setattr("api.services.connectors.x.sync", boom)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-x-boom"))
    assert sleep_cycle.get_sleep_state().status == "idle"
    assert sleep_cycle.get_sleep_state().error is None
    assert calls == [memory, memory], "X raising must not stop Pinterest's or Reddit's poll"


# --- final-review H1: the tail poll must not steal the Sleep commit's provenance --


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), check=True,
                          capture_output=True, text=True).stdout


def _seed_bank_with_one_episode(tmp_path):
    """One unprocessed, session-tagged episode (so the cycle takes the FULL
    5-stage path, not the idle early return) in a real git repo."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    (memory / "sources").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    markdown_parser.write(
        memory / "episodes" / "ep_2026-08-31_001.md",
        {"id": "ep_2026-08-31_001", "processed": False, "source": "mcp",
         "timestamp": "2026-08-31T10:00:00",
         "session_id": "ses_2026-08-31_abc12345"},
        "Cicada now supports direct saved-content connectors.",
    )
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    return memory


def test_tail_poll_runs_after_finalize_so_neither_commits_steals_the_others_provenance(
    tmp_path, monkeypatch,
):
    """Final-review H1. Before the fix, `_poll_connectors_safely` ran BEFORE
    `_finalize`: a connector that ingested reached `media_ingestor.ingest_batch`
    -> `_commit_media` -> `git_service.commit_changes`, which is `git add -A` —
    sweeping the Sleep cycle's own uncommitted entity page (dirty from this
    cycle's own pending work) into a `Sources ingest` commit with
    `Cicada-Author: user` and no `Cicada-Session:` trailers. `_finalize` then
    found a clean tree and committed nothing, so no "Sleep cycle" commit
    existed at all even though the cycle reported Completed.

    This drives a REAL (non-idle) cycle with a real git repo end to end: the
    LLM/resolver/vector-index boundaries are stubbed (no network, no real
    model), but `git_service.commit_changes` and `media_ingestor.ingest_batch`
    run for real so the two commits below can be inspected directly.
    """
    memory = _seed_bank_with_one_episode(tmp_path)

    async def fake_extract(episodes, settings):
        return [{
            "episode_id": "ep_2026-08-31_001",
            "episode_timestamp": "2026-08-31T10:00:00",
            "origin": "claude-code",
            "entities": [{"name": "Cicada", "type": "project",
                          "source_episode": "ep_2026-08-31_001"}],
            "relationships": [],
        }]

    async def fake_resolve(extracted_arg, existing, settings):
        return {
            "changes": [{
                "id": "cicada", "action": "create",
                "source_episode": "ep_2026-08-31_001",
                "source_episodes": ["ep_2026-08-31_001"],
                "trigger": "sleep/extraction",
                "entity": {"name": "Cicada", "type": "project", "confidence": 0.8,
                           "key_facts": ["Supports direct saved-content connectors."]},
            }],
            "relationships": [],
            "episode_cooccurrences": {},
        }

    async def fake_detect(changes, existing, settings, **kw):
        return []

    async def fake_resolve_and_prune(resolved, existing, settings):
        return list(resolved)

    class _FakeIndexer:
        def __init__(self, *_a, **_k):
            pass

        def index_entities(self):
            return 0

        def index_episodes(self):
            return 0

        def index_claims(self):
            return 0

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    monkeypatch.setattr("api.services.entity_resolver.resolve", fake_resolve)
    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fake_detect)
    monkeypatch.setattr(
        "api.services.conflict_resolver.resolve_and_prune", fake_resolve_and_prune
    )
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", _FakeIndexer)

    # `enrich` is the one real network call inside `ingest_batch` — offline it,
    # exactly like test_connector_pinterest.py's `_memory` helper does, so the
    # connector's ingest below is hermetic while `_commit_media`'s git commit
    # stays real.
    async def offline_enrich(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="",
            site=media_ingestor._site_of(url), media_type="url")

    monkeypatch.setattr(media_ingestor, "enrich", offline_enrich)

    from api.services.media_ingestor import RawItem

    async def pinterest_sync_that_ingests(memory_path, **kwargs):
        created, _ = await media_ingestor.ingest_batch(
            [RawItem(url="https://example.com/pin-1", title="A pin",
                     folder="Recipes", origin="pinterest")],
            memory_path, from_bookmark_file=False,
        )
        return {"status": "ok", "new": created, "seen": 1, "error": None}

    async def skipped_sync(memory_path, **kwargs):
        return {"status": "skipped", "reason": "not connected",
                "new": 0, "seen": 0, "error": None}

    monkeypatch.setattr("api.services.connectors.pinterest.sync", pinterest_sync_that_ingests)
    monkeypatch.setattr("api.services.connectors.reddit.sync", skipped_sync)
    monkeypatch.setattr("api.services.connectors.x.sync", skipped_sync)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-h1"))

    assert sleep_cycle.get_sleep_state().status == "idle"
    assert sleep_cycle.get_sleep_state().error is None

    log = _git(memory, "log", "--format=%H", "--reverse")
    hashes = [h for h in log.splitlines() if h.strip()]
    assert len(hashes) == 3, f"expected seed + Sleep cycle + Sources ingest, got {len(hashes)}"
    _seed_hash, sleep_hash, sources_hash = hashes

    # The Sleep commit carries its entity line and the episode's session trailer.
    sleep_message = _git(memory, "log", "-1", "--format=%B", sleep_hash)
    assert "Sleep cycle" in sleep_message
    assert "entities/cicada.md: create" in sleep_message
    assert "Cicada-Session: ses_2026-08-31_abc12345" in sleep_message

    # The Sources commit is the connector's own, session-less commit.
    sources_message = _git(memory, "log", "-1", "--format=%B", sources_hash)
    assert "Sources ingest" in sources_message
    assert "Cicada-Session:" not in sources_message

    sleep_files = _git(
        memory, "diff-tree", "--no-commit-id", "--name-only", "-r", sleep_hash
    ).splitlines()
    sources_files = _git(
        memory, "diff-tree", "--no-commit-id", "--name-only", "-r", sources_hash
    ).splitlines()

    # The entity page landed in the Sleep commit, not the Sources commit.
    assert "entities/cicada.md" in sleep_files
    assert "entities/cicada.md" not in sources_files, (
        "the Sources commit must not have swept the Sleep cycle's own dirty "
        "entity page via git add -A"
    )
    # The Sources commit contains ONLY connector-written files: the new
    # episode, the url_index update, and the media entity page `ingest_one`
    # writes directly (media entities bypass the promotion threshold — this
    # is the connector's own file, not a leak from the Sleep cycle's work).
    assert sources_files, "the connector must have actually ingested something"
    assert all(
        f.startswith("episodes/") or f == "sources/url_index.json"
        or f.startswith("entities/media-")
        for f in sources_files
    ), f"Sources commit touched unexpected files: {sources_files}"


# --- Devin PR #25 round 1, finding 3: a pre-existing dirty edit must never --
# --- be swept into a connector/media commit, `git add -A` or otherwise.   --


def test_a_preexisting_dirty_edit_is_never_swept_into_a_media_commit(tmp_path, monkeypatch):
    """H1 (above) proved the ORDERING fix: poll-after-finalize means the
    Sleep cycle's own writes are already committed by the time the connector
    runs. This is the mirror case H1 does not cover — a dirty file that has
    NOTHING to do with Sleep at all (a hand-edit made directly in Obsidian,
    say) sitting in the working tree when a connector happens to poll.
    `_commit_media` used to `git add -A`, which would silently absorb that
    edit into a `Sources ingest` commit under `Cicada-Author: user`
    provenance it never earned. `_commit_media` now stages only the paths
    THIS batch actually wrote (`git_service.commit_paths`), so the
    unrelated dirty file must survive, untouched and still uncommitted,
    no matter what else is sitting dirty in the bank.
    """
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    (memory / "sources").mkdir(parents=True)

    markdown_parser.write(
        memory / "entities" / "unrelated-project.md",
        {"name": "Unrelated Project", "type": "project", "status": "active",
         "confidence": 0.8, "created": "2026-01-01", "last_referenced": "2026-01-01",
         "decay_class": "active", "decay_rate": 0.05, "source_episodes": [],
         "tags": [], "related": [], "version": 1},
        "## Summary\n\nOriginal body.",
    )
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")

    # A hand-edit lands AFTER the seed commit — dirty, unrelated to anything
    # the connector is about to write, and never staged.
    markdown_parser.write(
        memory / "entities" / "unrelated-project.md",
        {"name": "Unrelated Project", "type": "project", "status": "active",
         "confidence": 0.8, "created": "2026-01-01", "last_referenced": "2026-01-01",
         "decay_class": "active", "decay_rate": 0.05, "source_episodes": [],
         "tags": [], "related": [], "version": 2},
        "## Summary\n\nA direct Obsidian edit, mid-flight.",
    )
    dirty_before = _git(memory, "status", "--porcelain").strip()
    assert dirty_before, "sanity: the hand-edit must actually be dirty"

    async def offline_enrich(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="",
            site=media_ingestor._site_of(url), media_type="url")

    monkeypatch.setattr(media_ingestor, "enrich", offline_enrich)

    from api.services.media_ingestor import RawItem

    created, _ = asyncio.run(media_ingestor.ingest_batch(
        [RawItem(url="https://example.com/finding-3", title="A pin",
                 folder="Recipes", origin="pinterest")],
        memory, from_bookmark_file=False,
    ))
    assert created == 1

    log = _git(memory, "log", "--format=%H", "--reverse")
    hashes = [h for h in log.splitlines() if h.strip()]
    assert len(hashes) == 2, f"expected seed + Sources ingest, got {len(hashes)}"
    _seed_hash, sources_hash = hashes

    sources_files = _git(
        memory, "diff-tree", "--no-commit-id", "--name-only", "-r", sources_hash
    ).splitlines()
    assert "entities/unrelated-project.md" not in sources_files, (
        "the connector commit must not have swept the pre-existing dirty "
        "edit via git add -A"
    )
    assert sources_files, "the connector must have actually ingested something"

    # The hand-edit is STILL dirty and uncommitted after the connector ran —
    # not silently absorbed, not silently discarded either.
    dirty_after = _git(memory, "status", "--porcelain").strip()
    assert "entities/unrelated-project.md" in dirty_after
    diff_after = _git(memory, "diff", "--", "entities/unrelated-project.md")
    assert "mid-flight" in diff_after
