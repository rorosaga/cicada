# api/tests/test_link_recon.py
"""G102 cheap slice — recon over stored title+description: batched Stage-1
extraction, Stage-2 MATCH (never create), `about` claims on the media page,
edges via Stage 5.7. Hermetic: extract/match/indexer all injected."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from api.services import entity_resolver, link_enrichment, link_recon, markdown_parser
from api.services.claims import parse_claims

# `api/tests/` is not a package and no test imports another, so the three
# fixture helpers are repeated here rather than imported from test_link_backfill.


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def _settings(memory: Path, **over):
    base = dict(
        memory_path=memory, litellm_model="gpt-5.4-mini", litellm_disambiguation_model="gpt-5.4-nano",
        llm_mode="byok", link_enrich_enabled=True, link_enrich_max_per_cycle=20, link_enrich_min_desc_len=120,
        link_enrich_excerpt_chars=2000, link_enrich_backfill_per_cycle=20, link_enrich_fetch_retry_days=30,
        link_recon_batch_size=8, link_recon_max_per_cycle=40,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _media(memory: Path, stem: str, name: str, url: str, *, saved_at: str, description: str = ""):
    fm = {
        "name": name, "type": "media", "status": "active", "confidence": 0.7,
        "created": saved_at, "last_referenced": saved_at, "saved_at": saved_at,
        "source_episodes": [f"ep_{saved_at}_001"], "tags": ["bookmark"], "related": [],
        "media": {"url": url, "media_type": "bookmark", "site": "example.com"},
    }
    body = f"## Summary\nSaved bookmark — {name}."
    if description:
        body += f"\n\n## Description\n{description}"
    markdown_parser.write(memory / "entities" / f"{stem}.md", fm, body)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    return memory


def _fm(memory: Path, stem: str) -> dict:
    return markdown_parser.parse(memory / "entities" / f"{stem}.md").frontmatter


def run(coro):
    return asyncio.run(coro)


def _entity(memory: Path, stem: str, name: str, etype: str = "concept"):
    markdown_parser.write(memory / "entities" / f"{stem}.md",
                          {"name": name, "type": etype, "status": "active", "confidence": 0.8,
                           "created": "2026-01-01", "last_referenced": "2026-05-01", "related": []},
                          f"## Summary\n{name}.")


ROBOTICS = ("A curated list of robotics conferences and workshops for graduate researchers, "
            "with submission deadlines, ROS tutorials and location details.")
GRAPHS = ("An introduction to knowledge graphs for personal memory systems, comparing "
          "Neo4j with plain markdown and wikilinks for small-scale use.")


class _Spy:
    """The pending store's surface as recon uses it: ``pending_by_name`` is
    consulted before every write (final review M2) and ``index_pending_entity``
    REPLACES a same-named entry, exactly as ``SqliteVecIndexer`` does."""

    def __init__(self, existing=None):
        self.pending = list(existing or [])
        self.rebuilt = 0

    def pending_by_name(self, name):
        return next((e for e in self.pending if e.name.lower() == name.lower()), None)

    def index_pending_entity(self, entity):
        self.pending = [e for e in self.pending if e.name.lower() != entity.name.lower()] + [entity]

    def rebuild_pending_index(self):
        self.rebuilt += 1
        return len(self.pending)


def _extract_fixed(entities):
    calls = []

    async def extract(text, settings):
        calls.append(text)
        return entities

    extract.calls = calls
    return extract


async def _match_direct(entity, existing_by_name, settings, cache):
    hit = existing_by_name.get((entity.get("name") or "").lower())
    return hit["id"] if hit else None


def test_render_batch_clips_and_numbers():
    cards = [link_recon.LinkCard(media_id=f"media-{i}", title=f"T{i}", url=f"https://example.com/{i}",
                                 description="word " * 400, episode="ep") for i in range(2)]
    text = link_recon.render_batch(cards)
    assert "[1] Title: T0" in text and "[2] Title: T1" in text
    assert text.count("word") <= 2 * link_recon.MAX_WORDS_PER_LINK + 2


def test_attribute_by_surface_form_drops_ungrounded_entities():
    cards = [link_recon.LinkCard("media-a", "Robotics Conf List", "https://a", ROBOTICS, "ep1"),
             link_recon.LinkCard("media-b", "Graph Intro", "https://b", GRAPHS, "ep2")]
    ents = [{"name": "ROS", "type": "tool", "aliases": []},
            {"name": "Knowledge Graphs", "type": "concept", "aliases": ["knowledge graph"]},
            {"name": "Neo4j", "type": "tool", "aliases": []},
            {"name": "Bob Example", "type": "person", "aliases": []},      # never on either card
            {"name": "Prefers concise", "type": "skill", "aliases": []}]   # type never related
    out = link_recon.attribute(ents, cards)
    assert [e["name"] for e in out["media-a"]] == ["ROS"]
    assert [e["name"] for e in out["media-b"]] == ["Knowledge Graphs", "Neo4j"]


def test_recon_relates_existing_entities_and_candidates_the_rest(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "ros", "ROS", "tool")
    _entity(memory, "knowledge-graphs", "Knowledge Graphs", "concept")
    _media(memory, "media-a", "Robotics Conf List", "https://a.example", saved_at="2026-01-01", description=ROBOTICS)
    _media(memory, "media-b", "Graph Intro", "https://b.example", saved_at="2026-01-02", description=GRAPHS)
    (memory / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "ros", "target": "knowledge-graphs", "label": "used with"}]}))
    extract = _extract_fixed([
        {"name": "ROS", "type": "tool", "confidence": 0.9, "aliases": [], "summary": "Robot Operating System"},
        {"name": "Knowledge Graphs", "type": "concept", "confidence": 0.8, "aliases": ["knowledge graph"]},
        {"name": "Neo4j", "type": "tool", "confidence": 0.6, "aliases": []},
    ])
    spy = _Spy()
    report = run(link_enrichment.backfill(
        memory, _settings(memory), limit=20, extract_fn=extract, match_fn=_match_direct,
        indexer_factory=lambda memory_path: spy, engine="litellm", commit=False))
    assert len(extract.calls) == 1 and "[2] Title: Graph Intro" in extract.calls[0]
    assert report.extracted == 3 and report.related == 2 and report.llm_calls == 1
    about_a = [c for c in parse_claims(markdown_parser.parse(memory / "entities" / "media-a.md").body) if c.predicate == "about"]
    assert [(c.object, c.object_kind, c.observer, c.source_trust, c.origin) for c in about_a] == \
        [("ros", "node", "agent", "agent_extracted", "sleep/link_recon")]
    assert about_a[0].confidence == 0.7 and about_a[0].source_episodes == ["ep_2026-01-01_001"]
    assert about_a[0].authored_by == "gpt-5.4-mini"
    assert _fm(memory, "media-a")["related"] == ["ros"]
    assert _fm(memory, "media-b")["related"] == ["knowledge-graphs"]
    assert _fm(memory, "media-a")["recon_attempted"] == str(date.today())
    # Target pages untouched (R6): no related entry, no last_referenced bump.
    assert _fm(memory, "ros")["related"] == [] and str(_fm(memory, "ros")["last_referenced"]) == "2026-05-01"
    # Neo4j matched nothing -> candidate, never a page.
    assert [p.name for p in spy.pending] == ["Neo4j"] and spy.rebuilt == 1
    assert not (memory / "entities" / "neo4j.md").exists()
    # Stage 5.7 projected the claims into edges and kept the non-claim edge.
    edges = yaml.safe_load((memory / "graph_edges.yaml").read_text())["edges"]
    assert {"source": "ros", "target": "knowledge-graphs", "label": "used with"} in edges
    assert any(e["source"] == "media-a" and e["target"] == "ros" and e["label"] == "about" and e.get("claim_id") for e in edges)
    assert "graph_edges.yaml: updated (trigger: sleep/link_recon)" in report.manifest
    assert "entities/media-a.md: related (source: ep_2026-01-01_001, trigger: sleep/link_recon)" in report.manifest


def test_recon_is_idempotent_and_capped(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "ros", "ROS", "tool")
    for i in range(3):
        _media(memory, f"media-{i}", f"Robotics {i}", f"https://{i}.example", saved_at=f"2026-01-0{i + 1}", description=ROBOTICS)
    extract = _extract_fixed([{"name": "ROS", "type": "tool", "confidence": 0.9}])
    s = _settings(memory, link_recon_batch_size=2)
    first = run(link_enrichment.backfill(memory, s, limit=20, recon_limit=2, extract_fn=extract,
                                         match_fn=_match_direct, indexer_factory=lambda p: None, commit=False))
    assert len(extract.calls) == 1 and first.related == 2 and first.remaining_recon == 1
    second = run(link_enrichment.backfill(memory, s, limit=20, recon_limit=10, extract_fn=extract,
                                          match_fn=_match_direct, indexer_factory=lambda p: None, commit=False))
    assert len(extract.calls) == 2 and second.related == 1 and second.remaining_recon == 0
    third = run(link_enrichment.backfill(memory, s, limit=20, extract_fn=extract, match_fn=_match_direct,
                                         indexer_factory=lambda p: None, commit=False))
    assert len(extract.calls) == 2 and third.related == 0
    claims = parse_claims(markdown_parser.parse(memory / "entities" / "media-0.md").body)
    assert len([c for c in claims if c.predicate == "about"]) == 1


def test_recon_skips_thin_descriptions_and_survives_an_engine_failure(tmp_path):
    from api.services import engine_errors

    memory = _bank(tmp_path)
    _media(memory, "media-thin", "Thin", "https://t.example", saved_at="2026-01-01", description="Short.")
    _media(memory, "media-rich", "Rich", "https://r.example", saved_at="2026-01-02", description=ROBOTICS)

    async def extract(text, settings):
        raise engine_errors.EngineThrottled("429")

    report = run(link_enrichment.backfill(memory, _settings(memory), limit=20, extract_fn=extract,
                                          match_fn=_match_direct, indexer_factory=lambda p: None, commit=False))
    assert report.engine_aborted == "EngineThrottled" and report.related == 0
    assert "recon_attempted" not in _fm(memory, "media-rich")   # unmarked: still a candidate
    assert report.remaining_recon == 1
    assert report.llm_calls == 0                # the engine never answered (final review M3)


def _git_log(memory: Path) -> str:
    return subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"],
                          check=True, capture_output=True, text=True).stdout


def test_recon_engine_abort_commits_the_reuse_writes_as_cicada_with_no_engine_trailer(tmp_path):
    """Final review M3: the reuse tier's ``describes`` claim is a real,
    zero-LLM write (``authored_by: cicada``) and IS committed; recon's engine
    died before answering, so the commit must be ``cicada``'s with no
    ``Cicada-Engine:`` — the fetch tier's Task 1 review M2 rule, and the G85
    decay-only precedent. Before the fix ``llm_calls`` was bumped before the
    call and the commit was stamped ``gpt-5.4-mini`` / ``litellm``."""
    from api.services import engine_errors

    memory = _bank(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        subprocess.run(["git", "-C", str(memory), *args], check=True)
    _media(memory, "media-rich", "Rich", "https://r.example", saved_at="2026-01-02", description=ROBOTICS)
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-q", "-m", "seed"], check=True)

    async def extract(text, settings):
        raise engine_errors.EngineUnavailable("signed out")

    report = run(link_enrichment.backfill(memory, _settings(memory), limit=20, extract_fn=extract,
                                          match_fn=_match_direct, indexer_factory=lambda p: None, engine="litellm"))
    assert report.reused == 1 and report.engine_aborted == "EngineUnavailable" and report.llm_calls == 0
    assert report.commit
    claims = parse_claims(markdown_parser.parse(memory / "entities" / "media-rich.md").body)
    assert [c.authored_by for c in claims if c.predicate == "describes"] == ["cicada"]
    log = _git_log(memory)
    assert "entities/media-rich.md: enriched" in log
    assert "Cicada-Author: cicada" in log
    assert "Cicada-Author: gpt-5.4-mini" not in log
    assert "Cicada-Engine:" not in log


def test_page_level_extraction_failure_still_counts_the_model_call(tmp_path):
    memory = _bank(tmp_path)
    _media(memory, "media-rich", "Rich", "https://r.example", saved_at="2026-01-02", description=ROBOTICS)

    async def extract(text, settings):
        raise ValueError("malformed JSON")

    report = run(link_enrichment.backfill(memory, _settings(memory), limit=20, extract_fn=extract,
                                          match_fn=_match_direct, indexer_factory=lambda p: None, commit=False))
    assert report.engine_aborted is None and report.llm_calls == 1
    assert _fm(memory, "media-rich")["recon_status"] == "no_matches"


def test_recon_never_replaces_a_conversation_originated_pending_candidate(tmp_path):
    """Final review M2: Stage 2 recorded ``Neo4j`` from a real conversation
    (its episode, its history, its confidence) and ``index_pending_entity``
    replaces by name — recon must leave that richer entry alone, or the
    promotion path that merges its history would inherit the blurb's empty one."""
    from api.services.vector_index import PendingEntity

    memory = _bank(tmp_path)
    _media(memory, "media-b", "Graph Intro", "https://b.example", saved_at="2026-01-02", description=GRAPHS)
    earlier = PendingEntity(name="Neo4j", type="tool", description="Graph database the user evaluated",
                            source_episode="ep_2025-12-01_003", confidence=0.55, tags=["databases"],
                            history_entries=[{"date": "2025-12-01", "note": "compared against markdown"}])
    spy = _Spy(existing=[earlier])
    extract = _extract_fixed([
        {"name": "neo4j", "type": "tool", "confidence": 0.3, "aliases": [], "summary": "A graph database"},
        {"name": "Markdown", "type": "tool", "confidence": 0.4, "aliases": []},
    ])
    report = run(link_enrichment.backfill(
        memory, _settings(memory), limit=20, extract_fn=extract, match_fn=_match_direct,
        indexer_factory=lambda memory_path: spy, engine="litellm", commit=False))
    assert report.related == 0
    by_name = {p.name: p for p in spy.pending}
    assert set(by_name) == {"Neo4j", "Markdown"}
    assert by_name["Neo4j"] is earlier                     # untouched, not rewritten
    assert by_name["Neo4j"].history_entries == earlier.history_entries
    assert by_name["Markdown"].source_episode == "ep_2026-01-02_001"
    assert spy.rebuilt == 1                                 # the one genuinely new candidate


def test_match_existing_uses_direct_then_llm_and_never_creates(tmp_path, monkeypatch):
    existing = entity_resolver.existing_by_name([
        {"id": "knowledge-graphs", "frontmatter": {"name": "Knowledge Graphs", "type": "concept"}, "body": "## Summary\nKG."},
    ])
    s = _settings(tmp_path)
    run_ = asyncio.run
    assert run_(entity_resolver.match_existing({"name": "knowledge graphs", "type": "concept"}, existing, s)) == "knowledge-graphs"

    async def judge(**kwargs):
        return "same" if kwargs["new_name"] == "Knowledge Graph Systems" else "unsure"

    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    cache: dict = {}
    assert run_(entity_resolver.match_existing({"name": "Knowledge Graph Systems", "type": "concept"}, existing, s, cache=cache)) == "knowledge-graphs"
    assert run_(entity_resolver.match_existing({"name": "Graphs Weekly", "type": "concept"}, existing, s, cache=cache)) is None
    assert run_(entity_resolver.match_existing({"name": "Knowledge Base", "type": "tool"}, existing, s, cache=cache)) is None  # type gate
    assert not list(tmp_path.rglob("*.md"))
