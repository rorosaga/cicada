"""Shared rig for the drain tests ("Consolidate reads everything", 2026-09-29).

A real git bank with N unprocessed episodes, and the Sleep pipeline's LLM and
index boundaries faked — everything else (Stage 3, Stage 5, the claim pipeline,
the commit, the tail's tree guard) runs for real, so "three commits" and "the
tree is clean" are proven with ``git``, not asserted about a stub. The tail's
steps are replaced by recorders so a test can say how often each one ran.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

from api.services import markdown_parser, predicates, sleep_cycle


def settings(memory, **overrides):
    base = dict(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        archive_threshold=0.2,
        decay_nudge_threshold=0.4,
        link_enrich_enabled=False,
        inbox_stale_after_days=90,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def episode_ids(n: int, day: str = "2026-09-01") -> list[str]:
    return [f"ep_{day}_{i:03d}" for i in range(n)]


def seed_bank(tmp_path, ids, *, extra=None):
    """A real git repo with unprocessed, session-tagged episodes (one origin);
    ``extra(memory)`` may write more files before the seed commit."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    for i, ep_id in enumerate(ids):
        markdown_parser.write(
            memory / "episodes" / f"{ep_id}.md",
            {"id": ep_id, "processed": False, "source": "mcp",
             "timestamp": f"2026-09-01T10:{i % 60:02d}:00",
             "session_id": f"ses_2026-09-01_{i:08x}"},
            f"Episode {ep_id} body about project X and tool Y.",
        )
    if extra:
        extra(memory)
    git(memory, "init", "-q")
    git(memory, "config", "user.email", "test@cicada.local")
    git(memory, "config", "user.name", "Cicada Test")
    git(memory, "add", "-A")
    git(memory, "commit", "-q", "-m", "seed")
    return memory


def is_processed(memory, ep_id) -> bool:
    return bool(markdown_parser.parse(memory / "episodes" / f"{ep_id}.md").frontmatter.get("processed", False))


def waiting(memory) -> list[str]:
    return [e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)]


class Rig:
    """What the faked boundaries saw, and the hooks a test plugs in."""

    def __init__(self):
        self.extract_batches: list[list[str]] = []     # the ids each Stage 1 call got
        self.prune_calls: list[dict] = []              # the kwargs resolve_and_prune got
        self.pipeline_calls: list[dict] = []           # ... run_claim_pipeline
        self.link_calls = 0                            # Stage 5.57's enrich_media_links
        self.question_refreshes = 0                    # inbox_questions.refresh_open_questions
        self.tail: list[str] = []                      # engine-independent tail steps, in order
        self.on_extract = None                         # async (batch_no, episodes) -> None | list(omit ids)
        self.on_generate = None                        # async (batch_no) -> None
        self.fail_ids: set[str] = set()                # ids Stage 1 "failed" for (omitted from its result)
        self.generate_calls = 0


def install(monkeypatch, *, engine_label: str | None = None) -> Rig:
    """Fake the LLM and index boundaries; record the once-per-drain seams."""
    rig = Rig()

    async def fake_extract(episodes, settings_, cancel_check=None, progress_callback=None,
                           on_episode_done=None, **_kw):
        rig.extract_batches.append([e["id"] for e in episodes])
        omit: set[str] = set(rig.fail_ids)
        if rig.on_extract is not None:
            more = await rig.on_extract(len(rig.extract_batches), episodes)
            omit |= set(more or ())
        out = []
        for ep in episodes:
            if progress_callback:
                progress_callback()
            if on_episode_done:
                on_episode_done(ep)
            if ep["id"] in omit:
                continue
            out.append({
                "episode_id": ep["id"], "episode_timestamp": ep["timestamp"], "origin": "mcp",
                "entities": [{"name": ep["id"], "type": "concept", "confidence": 0.7,
                              "source_episode": ep["id"]}],
                "relationships": [],
            })
        return out

    async def fake_resolve(extracted, existing, settings_, cancel_check=None):
        changes = [{
            "id": f"e-{r['episode_id']}", "action": "create", "source_episode": r["episode_id"],
            "source_episodes": [r["episode_id"]], "trigger": "sleep/extraction",
            "entity": {"name": r["episode_id"], "type": "concept", "confidence": 0.7},
        } for r in extracted]
        return {"changes": changes, "relationships": [], "episode_cooccurrences": {}}

    async def fake_detect(changes, existing, settings_, **_kw):
        return []

    from api.services import conflict_resolver, inbox_generator, inbox_questions
    from api.services import claim_pipeline

    real_prune = conflict_resolver.resolve_and_prune
    real_pipeline = claim_pipeline.run_claim_pipeline
    real_refresh = inbox_questions.refresh_open_questions
    real_generate = inbox_generator.generate

    async def spy_prune(resolved, existing, settings_, **kw):
        rig.prune_calls.append(dict(kw))
        return await real_prune(resolved, existing, settings_, **kw)

    def spy_pipeline(*a, **kw):
        rig.pipeline_calls.append({k: v for k, v in kw.items() if k == "decay"})
        return real_pipeline(*a, **kw)

    def spy_refresh(*a, **kw):
        rig.question_refreshes += 1
        return real_refresh(*a, **kw)

    async def spy_generate(*a, **kw):
        rig.generate_calls += 1
        await real_generate(*a, **kw)
        if rig.on_generate is not None:
            await rig.on_generate(rig.generate_calls)

    async def fake_enrich(*_a, **_kw):
        rig.link_calls += 1
        return 0

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
    monkeypatch.setattr("api.services.conflict_resolver.resolve_and_prune", spy_prune)
    monkeypatch.setattr("api.services.claim_pipeline.run_claim_pipeline", spy_pipeline)
    monkeypatch.setattr("api.services.inbox_questions.refresh_open_questions", spy_refresh)
    monkeypatch.setattr("api.services.inbox_generator.generate", spy_generate)
    monkeypatch.setattr("api.services.link_enrichment.enrich_media_links", fake_enrich)
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", _FakeIndexer)

    if engine_label is not None:
        from api.services import engine_select

        async def fake_probe(_settings):
            return True, "signed in"

        monkeypatch.setattr(sleep_cycle, "_engine_label", lambda s: engine_label)
        monkeypatch.setattr(sleep_cycle, "_probe_engine_cheaply", fake_probe)
        monkeypatch.setattr(engine_select, "author_model", lambda s: "test-model")

    def recorder(name):
        async def _rec(*_a, **_kw):
            rig.tail.append(name)
        return _rec

    for step, name in (
        ("_refresh_state_safely", "state"), ("_expire_claims_safely", "expiry"),
        ("_propose_followups_safely", "followups"), ("_poll_connectors_safely", "connectors"),
        ("_poll_feeds_and_calendars_safely", "feeds"), ("_backfill_links_safely", "links"),
        ("_resolve_papers_safely", "papers"), ("_replay_wispr_todos_safely", "wispr"),
        ("_warm_logos_safely", "logos"), ("_refresh_questions_safely", "questions"),
    ):
        monkeypatch.setattr(sleep_cycle, step, recorder(name))
    return rig
