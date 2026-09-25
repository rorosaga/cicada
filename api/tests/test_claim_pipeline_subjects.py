"""G141 PJ-0 (R-PJ17, R-CS1..R-CS4): Sleep keys a claim's subject and object
through Stage 2's own ids — the map its edges already use — maps "the user"
onto the `owner: true` page, and counts (never silently drops) a claim whose
subject still has no page. Synthetic names only."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from loguru import logger

from api.config import Settings
from api.services import (claim_pipeline, entity_resolver, git_service, markdown_parser, owner_identity,
                          predicates, sleep_cycle, telemetry)
from api.services.claims import parse_claims
from api.services.pending_store import HoldOutcome

REPO = Path(__file__).resolve().parents[2]
EP = "ep_2026-09-22_001"
TS = "2026-09-22T10:00:00+00:00"


def _settings(memory: Path) -> SimpleNamespace:
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4, sleep_promotion_threshold=2,
                           link_enrich_enabled=False)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _page(memory: Path, entity_id: str, name: str, kind: str = "person", **extra) -> dict:
    fm = {"name": name, "type": kind, "status": "active", **extra}
    path = memory / "entities" / f"{entity_id}.md"
    markdown_parser.write(path, fm, "## Summary\nA synthetic page.")
    return {"id": entity_id, "frontmatter": fm, "body": "## Summary\nA synthetic page.", "filepath": path}


def _extracted(*rels: tuple[str, str, str]) -> list[dict]:
    return [{
        "episode_id": EP, "episode_timestamp": TS, "origin": "claude-code", "entities": [],
        "relationships": [{"source": s, "target": t, "label": label, "source_episode": EP,
                           "source_episode_timestamp": TS} for s, label, t in rels],
    }]


def _pairs(memory: Path, entity_id: str) -> list[tuple[str, str]]:
    body = markdown_parser.parse(memory / "entities" / f"{entity_id}.md").body
    return [(c.subject, c.object) for c in parse_claims(body)]


def _stems(memory: Path) -> list[str]:
    return sorted(p.stem for p in (memory / "entities").glob("*.md"))


# --- keyed through Stage 2 (R-CS1) ------------------------------------------------


def test_endpoint_id_is_the_edge_rule_exact_then_fuzzy():
    table = {"alpha project": "alpha-project", "bob example": "bob-example"}
    assert entity_resolver.endpoint_id("Alpha Project", table) == "alpha-project"
    assert entity_resolver.endpoint_id("alpha projects", table) == "alpha-project"  # ratio 96
    assert entity_resolver.endpoint_id("Zed Unknown", table) is None
    assert entity_resolver.endpoint_id("", table) is None
    assert entity_resolver.endpoint_id(None, table) is None  # type: ignore[arg-type]


def test_stage2_returns_the_map_its_edges_used(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    existing = [_page(memory, "alpha-project", "Alpha Project", kind="project")]

    class _NoIndex:
        def __init__(self, *_a, **_k):
            raise RuntimeError("no vector store in this test")

    monkeypatch.setattr(entity_resolver, "SqliteVecIndexer", _NoIndex)
    extracted = [{"episode_id": EP, "relationships": [],
                  "entities": [{"name": "Alpha Projects", "type": "project", "confidence": 0.8,
                                "source_episode": EP}]}]
    result = asyncio.run(entity_resolver.resolve(extracted, existing, _settings(memory)))
    assert result["name_to_id"]["alpha project"] == "alpha-project"
    assert result["name_to_id"]["alpha projects"] == "alpha-project"  # the direct fuzzy match


def test_a_claim_on_a_stage2_matched_short_name_lands_on_the_matched_page(tmp_path):
    memory = _bank(tmp_path)
    existing = [_page(memory, "hana-example", "Hana Example"),
                _page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")]
    # Stage 2 judged the short "Hana" to be the existing person.
    name_to_id = {"hana example": "hana-example", "lab cluster example": "lab-cluster-example",
                  "hana": "hana-example"}
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("Hana", "connects to", "Lab Cluster Example")), existing, memory,
        _settings(memory), now_date="2026-09-22", name_to_id=name_to_id)
    assert _pairs(memory, "hana-example") == [("hana-example", "lab-cluster-example")]
    assert result["claims_page_less"] == 0 and result["page_less_subjects"] == []
    assert _stems(memory) == ["hana-example", "lab-cluster-example"]  # no `hana` page invented


def test_without_the_map_the_same_claim_is_counted_instead_of_vanishing(tmp_path):
    memory = _bank(tmp_path)
    existing = [_page(memory, "hana-example", "Hana Example"),
                _page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")]
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("Hana", "connects to", "Lab Cluster Example")), existing, memory,
        _settings(memory), now_date="2026-09-22")
    assert _pairs(memory, "hana-example") == []
    assert result["claims_page_less"] == 1 and result["subjects_skipped"] == 1
    assert result["page_less_subjects"] == ["hana"]


# --- the owner (R-CS2) --------------------------------------------------------------


def test_the_user_lands_on_the_owner_page_as_subject_and_as_object(tmp_path):
    memory = _bank(tmp_path)
    existing = [_page(memory, "bob-example", "Bob Example", owner=True),
                _page(memory, "hana-example", "Hana Example"),
                _page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")]
    name_to_id = {"bob example": "bob-example", "hana example": "hana-example",
                  "lab cluster example": "lab-cluster-example"}
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("the user", "connects to", "Lab Cluster Example"),
                   ("Hana Example", "gave a guide to", "User")),
        existing, memory, _settings(memory), now_date="2026-09-22", name_to_id=name_to_id)
    assert _pairs(memory, "bob-example") == [("bob-example", "lab-cluster-example")]
    assert _pairs(memory, "hana-example") == [("hana-example", "bob-example")]
    assert result["claims_page_less"] == 0
    assert _stems(memory) == ["bob-example", "hana-example", "lab-cluster-example"]


def test_the_user_without_an_owner_page_is_counted_never_invented(tmp_path):
    memory = _bank(tmp_path)
    existing = [_page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")]
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("the user", "connects to", "Lab Cluster Example")), existing, memory,
        _settings(memory), now_date="2026-09-22", name_to_id={"lab cluster example": "lab-cluster-example"})
    assert result["claims_page_less"] == 1 and result["page_less_subjects"] == ["the-user"]
    assert _stems(memory) == ["lab-cluster-example"]


def test_two_owner_pages_resolve_through_owner_identity(tmp_path):
    memory = _bank(tmp_path)
    existing = [_page(memory, "bob-example", "Bob Example", owner=True),
                _page(memory, "robert-example", "Robert Example", owner=True),
                _page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")]
    owner_identity.save_owner({"entity_id": "robert-example"})  # CICADA_HOME is per-test (conftest)
    claim_pipeline.run_claim_pipeline(
        _extracted(("the user", "connects to", "Lab Cluster Example")), existing, memory,
        _settings(memory), now_date="2026-09-22", name_to_id={"lab cluster example": "lab-cluster-example"})
    assert _pairs(memory, "robert-example") == [("robert-example", "lab-cluster-example")]
    assert _pairs(memory, "bob-example") == []


# --- counted, logged as counts, the seam (R-CS3, R-CS4) -----------------------------


def test_a_page_less_claim_is_logged_as_a_count_and_never_as_text(tmp_path):
    memory = _bank(tmp_path)
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG",
                      filter=lambda r: r["name"] == "api.services.claim_pipeline")
    try:
        result = claim_pipeline.run_claim_pipeline(
            _extracted(("Zed Unknown", "uses", "Alpha Project")), [], memory, _settings(memory),
            now_date="2026-09-22", name_to_id={})
    finally:
        logger.remove(sink)
    assert result["claims_page_less"] == 1
    joined = "\n".join(lines)
    assert "1 claim(s) on 1 subject(s) without a page" in joined
    for needle in ("Zed Unknown", "zed-unknown", "Alpha Project", "alpha-project"):
        assert needle not in joined


def test_a_subject_with_no_pending_line_is_offered_to_the_hold_and_nothing_is_written(tmp_path, monkeypatch):
    """R-PJ17's seam, filled by PJ-0b (R-HP10): every page-less subject is offered
    in one call; with no pending line for it nothing is held, no store is
    invented, and the claim is counted exactly as PJ-0 counted it."""
    memory = _bank(tmp_path)
    assert claim_pipeline.hold_page_less({"zed-unknown": []}, memory) == {"zed-unknown": HoldOutcome(0, 0)}
    asked: list[dict[str, int]] = []
    real = claim_pipeline.hold_page_less
    monkeypatch.setattr(claim_pipeline, "hold_page_less",
                        lambda offers, m: asked.append({s: len(c) for s, c in offers.items()}) or real(offers, m))
    before = sorted(p.relative_to(memory).as_posix() for p in memory.rglob("*") if p.is_file())
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("Zed Unknown", "uses", "Alpha Project")), [], memory, _settings(memory),
        now_date="2026-09-22", name_to_id={})
    assert asked == [{"zed-unknown": 1}]
    assert (result["claims_page_less"], result["claims_held"]) == (1, 0)
    after = sorted(p.relative_to(memory).as_posix() for p in memory.rglob("*") if p.is_file())
    assert after == before


def test_the_false_re_emitted_comment_is_gone():
    text = (REPO / "api" / "services" / "claim_pipeline.py").read_text(encoding="utf-8")
    assert "re-emitted next cycle" not in text
    assert "waits for its subject to be promoted" not in text


# --- wired into Sleep ---------------------------------------------------------------


def test_the_live_cycle_threads_the_map_and_counts_page_less_claims(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "episodes" / f"{EP}.md",
                          {"id": EP, "processed": False, "source": "mcp", "timestamp": TS},
                          "user: Hana connects to Lab Cluster Example. Zed Unknown uses it too.")
    _page(memory, "hana-example", "Hana Example")
    _page(memory, "lab-cluster-example", "Lab Cluster Example", kind="tool")
    extracted = _extracted(("Hana", "connects to", "Lab Cluster Example"),
                           ("Zed Unknown", "uses", "Lab Cluster Example"))

    async def fake_extract(episodes, settings, **_kw):
        return extracted

    async def fake_resolve(extracted_arg, existing, settings, **_kw):
        return {"changes": [], "relationships": [], "episode_cooccurrences": {},
                "name_to_id": {"hana": "hana-example", "lab cluster example": "lab-cluster-example"}}

    async def fake_detect(changes, existing, settings, **kw):
        return []

    async def fake_resolve_and_prune(resolved, existing, settings):
        return list(resolved)

    async def fake_commit(memory_path, message):
        return None

    async def fake_porcelain(memory_path):
        return ""

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
    monkeypatch.setattr("api.services.conflict_resolver.resolve_and_prune", fake_resolve_and_prune)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(git_service, "porcelain_status", fake_porcelain)
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", _FakeIndexer)

    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="pj0_test"))

    assert _pairs(memory, "hana-example") == [("hana-example", "lab-cluster-example")]
    state = sleep_cycle.get_sleep_state()
    assert (state.claims_page_less, state.subjects_page_less) == (1, 1)


def test_the_sleep_run_row_carries_the_page_less_counts(tmp_path, monkeypatch):
    events: list = []

    async def fake_status(_path):
        return ""

    async def fake_commit(_path, _message):
        return "abc1234"

    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(telemetry, "record", events.append)
    monkeypatch.setattr(sleep_cycle._state, "claims_page_less", 3)
    monkeypatch.setattr(sleep_cycle._state, "subjects_page_less", 2)
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(llm_mode="agent"),
        engine="claude-cli", connection="claude-plan", billing="subscription", authors=["claude-sonnet-5"],
    ))
    (row,) = [e for e in events if e.kind == "sleep_run"]
    assert row.refs["claims_page_less"] == 3 and row.refs["subjects_page_less"] == 2
