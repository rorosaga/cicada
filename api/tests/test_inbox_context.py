"""G115 Phase 1 / G97 — the cause behind an inbox item, resolved at read.

The link is already on disk (a clarification's `source_episode`, a claim's
`source_episodes`, a page's `source_episodes`) and was thrown away at the API
boundary. `inbox_context` resolves it in three tiers, engine-free, and
`GET /inbox` serves it under an ETag that now moves with entities and episodes.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, inbox_context, inbox_service, markdown_parser, predicates

EPISODE_BODY = (
    "user: I have been sketching alpha-project all week, mostly the parser.\n"
    "assistant: Noted. Alpha Project is the parser rewrite, right?\n"
    "user: Yes. Bob Example reviewed the design yesterday and liked it.\n"
)


def _episode(memory: Path, ep_id: str, body: str = EPISODE_BODY, **fm) -> Path:
    (memory / "episodes").mkdir(parents=True, exist_ok=True)
    path = memory / "episodes" / f"{ep_id}.md"
    markdown_parser.write(
        path,
        {"id": ep_id, "timestamp": "2026-08-20T10:00:00+00:00", "title": "Parser planning",
         "session_id": "ses_2026-08-20_abcdef12", "harness": "claude-code", "origin": "claude-code",
         "processed": True, **fm},
        body,
    )
    return path


def _entity(memory: Path, entity_id: str, name: str, *, episodes: list[str], body: str = "", etype="project") -> Path:
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    path = memory / "entities" / f"{entity_id}.md"
    markdown_parser.write(
        path,
        {"name": name, "type": etype, "status": "active", "confidence": 0.6,
         "created": "2026-08-01", "last_referenced": "2026-08-20", "source_episodes": episodes,
         "tags": [], "related": [], "version": 1},
        body or f"# {name}\n",
    )
    return path


CLAIMS = """# Bob Example

```claims
- id: clm_2026-06-01_a1
  subject: bob-example
  predicate: works-at
  object: alpha-corp
  observer: agent
  source_trust: agent_extracted
  confidence: 0.6
  valid_from: '2026-06-01'
  recorded_at: '2026-06-01'
  source_episodes: [ep_2026-06-01_001]
- id: clm_2026-08-20_b2
  subject: bob-example
  predicate: works-at
  object: beta-corp
  observer: agent
  source_trust: agent_extracted
  confidence: 0.6
  valid_from: '2026-08-20'
  recorded_at: '2026-08-20'
  source_episodes: [ep_2026-08-20_001]
```
"""


def _item(memory: Path, item_id: str, fm: dict, body: str = "ctx") -> Path:
    (memory / "inbox").mkdir(parents=True, exist_ok=True)
    path = memory / "inbox" / f"{item_id}.md"
    markdown_parser.write(path, {"status": "pending", "required_input": "choice", "created_date": "2026-08-21", **fm}, body)
    return path


@pytest.fixture
def memory(tmp_path: Path) -> Path:
    bank_index.invalidate()
    m = tmp_path / "memory"
    m.mkdir()
    return m


# ---------- excerpt mechanics (pure) ----------


def test_locate_mention_prefers_name_then_id_then_token():
    text = "user: talked about alpha-project and Bob Example today"
    assert inbox_context.locate_mention(text, "Alpha Project", "alpha-project") == (19, 32)
    assert inbox_context.locate_mention(text, "Bob Example", "bob-example") == (37, 48)
    assert inbox_context.locate_mention(text, "Zeta Thing", "zeta-thing") is None
    # a 4+ char token of the name still finds it ("Example")
    assert inbox_context.locate_mention(text, "Example Person", "example-person") == (41, 48)


def test_excerpt_window_cuts_on_word_boundaries_and_recomputes_offsets():
    text = ("w " * 200) + "the alpha-project parser" + (" w" * 200)
    span = inbox_context.locate_mention(text, "Alpha Project", "alpha-project")
    ex = inbox_context.excerpt_around(text, span, radius=20)
    assert ex.excerpt.startswith("w ") and not ex.excerpt.startswith(" ")
    assert len(ex.excerpt) <= 20 * 2 + len("alpha-project") + 4
    s, e = ex.mention_offsets[0]
    assert ex.excerpt[s:e] == "alpha-project"
    assert text[ex.start:ex.end] == ex.excerpt


def test_excerpt_without_a_mention_is_the_head_and_has_no_offsets():
    text = "a b c " * 300
    ex = inbox_context.excerpt_around(text, None, radius=240)
    assert ex.mention_offsets == [] and 0 < len(ex.excerpt) <= 480
    # start/end stay in step with the trimming — they are what a viewer hands
    # to GET /episodes/{id}/span, so they must slice back to the same string.
    assert text[ex.start:ex.end] == ex.excerpt


# ---------- three tiers ----------


def test_tier_item_uses_the_items_own_source_episode(memory):
    _episode(memory, "ep_2026-08-20_001")
    _entity(memory, "alpha-project", "Alpha Project", episodes=[])
    _item(memory, "inbox-001", {"kind": "clarification", "entity_id": "alpha-project",
                                 "entity_name": "Alpha Project", "title": "Who is Alpha Project?",
                                 "source_episode": "ep_2026-08-20_001", "uncertainty_type": "unclear"})
    [item] = inbox_service.load_inbox(memory)
    assert item.cause.tier == "item" and item.cause.episode_id == "ep_2026-08-20_001"
    assert item.cause.conversation_title == "Parser planning"
    assert item.cause.conversation_id == "ses_2026-08-20_abcdef12" and item.cause.harness == "claude-code"
    s, e = item.cause.mention_offsets[0]
    # R1 orders the candidates display-name first, so the highlighted span is
    # the prose spelling on line 2 ("Alpha Project"), not the slug on line 1.
    assert item.cause.excerpt[s:e] == "Alpha Project"
    assert item.cause.span_kind == "derived"
    assert item.entity_type == "project" and item.source_episode == "ep_2026-08-20_001"


def test_tier_claim_picks_the_freshest_option_claims_episode(memory):
    _episode(memory, "ep_2026-06-01_001", body="user: Bob Example joined alpha-corp.\n")
    _episode(memory, "ep_2026-08-20_001", body="user: Bob Example moved to beta-corp last week.\n")
    _entity(memory, "bob-example", "Bob Example", episodes=["ep_2026-06-01_001"], body=CLAIMS, etype="person")
    _item(memory, "inbox-002", {"kind": "conflict", "entity_id": "bob-example", "entity_name": "Bob Example",
                                 "title": "Where does Bob Example work now?", "predicate": "works-at",
                                 "question": "Where does Bob Example work now?", "claim_id": "clm_2026-08-20_b2",
                                 "options": [
                                     {"key": "a", "label": "alpha-corp", "claim_id": "clm_2026-06-01_a1",
                                      "observed_at": "2026-06-01", "last_referenced": "2026-06-01"},
                                     {"key": "b", "label": "beta-corp", "claim_id": "clm_2026-08-20_b2",
                                      "observed_at": "2026-08-20", "last_referenced": "2026-08-20"}]})
    [item] = inbox_service.load_inbox(memory)
    assert item.cause.tier == "claim" and item.cause.episode_id == "ep_2026-08-20_001"
    assert "beta-corp" in item.cause.excerpt
    assert item.claim_id == "clm_2026-08-20_b2"
    assert item.extractor_confidence == pytest.approx(0.6)


def test_tier_entity_falls_back_to_the_pages_last_source_episode(memory):
    _episode(memory, "ep_2026-08-19_001", body="user: nothing here\n")
    _episode(memory, "ep_2026-08-20_001")
    _entity(memory, "alpha-project", "Alpha Project", episodes=["ep_2026-08-19_001", "ep_2026-08-20_001"])
    _item(memory, "inbox-003", {"kind": "decay", "entity_id": "alpha-project", "entity_name": "Alpha Project",
                                 "title": "No recent mentions of Alpha Project"})
    [item] = inbox_service.load_inbox(memory)
    assert item.cause.tier == "entity" and item.cause.episode_id == "ep_2026-08-20_001"


def test_no_source_recorded_is_served_not_hidden(memory):
    _entity(memory, "alpha-project", "Alpha Project", episodes=["ep_2099-01-01_001"])  # missing on disk
    _item(memory, "inbox-004", {"kind": "decay", "entity_id": "alpha-project", "entity_name": "Alpha Project",
                                 "title": "No recent mentions of Alpha Project"})
    [item] = inbox_service.load_inbox(memory)
    assert item.cause.tier == "none" and item.cause.excerpt == inbox_context.NO_SOURCE
    assert item.cause.episode_id is None


def test_a_g118_span_on_the_chosen_claim_is_the_mention(memory):
    ep = _episode(memory, "ep_2026-08-20_001", body="user: Bob Example moved to beta-corp last week.\n")
    text = markdown_parser.parse(ep).body
    from api.services import evidence
    start = text.index("moved to beta-corp"); end = start + len("moved to beta-corp")
    body = CLAIMS.replace(
        "  source_episodes: [ep_2026-08-20_001]\n",
        "  source_episodes: [ep_2026-08-20_001]\n"
        f"  evidence:\n  - episode: ep_2026-08-20_001\n    start: {start}\n    end: {end}\n    kind: user\n    hash: {evidence.body_hash(text)}\n",
    )
    _entity(memory, "bob-example", "Bob Example", episodes=[], body=body, etype="person")
    _item(memory, "inbox-005", {"kind": "conflict", "entity_id": "bob-example", "entity_name": "Bob Example",
                                 "title": "q", "predicate": "works-at", "question": "q?", "claim_id": "clm_2026-08-20_b2",
                                 "options": [{"key": "b", "label": "beta-corp", "claim_id": "clm_2026-08-20_b2"}]})
    [item] = inbox_service.load_inbox(memory)
    s, e = item.cause.mention_offsets[0]
    assert item.cause.excerpt[s:e] == "moved to beta-corp" and item.cause.span_kind == "asserted"


def test_item_from_file_without_context_keeps_the_legacy_shape(memory):
    path = _item(memory, "inbox-006", {"kind": "decay", "entity_id": "x", "entity_name": "X", "title": "t"})
    item = inbox_service._item_from_file(path)
    assert item.cause is None and item.entity_type is None


# ---------- G98 cardinality ----------


def test_cardinality_unions_the_runtime_map_and_the_seed_with_multi_winning(tmp_path):
    assert predicates.cardinality(tmp_path, "uses") == "multi"          # seed, no runtime map
    assert predicates.cardinality(tmp_path, "works-at") == "single"
    assert predicates.cardinality(tmp_path, "description") == "unknown"
    assert predicates.cardinality(None, "uses") == "multi"
    # A bank map adds predicates the seed never had.
    (tmp_path / "_predicates.yaml").write_text(
        "single_valued: [uses, employer]\nmulti_valued: [description]\n"
    )
    assert predicates.cardinality(tmp_path, "employer") == "single"      # runtime-only single
    assert predicates.cardinality(tmp_path, "description") == "multi"    # runtime-only multi
    # R4: a stale bank map (seeded before commit e9a7c6b moved `uses` to
    # multi_valued, and never refreshed because `install_predicate_map` leaves a
    # populated map alone) must NOT resurrect the false single-valued reading —
    # this is the live-bank case the G98 evidence came from.
    assert predicates.cardinality(tmp_path, "uses") == "multi"


def test_multi_valued_conflict_is_informational_at_read(memory):
    _entity(memory, "alpha-project", "Alpha Project", episodes=[])
    _item(memory, "inbox-007", {"kind": "conflict", "entity_id": "alpha-project", "entity_name": "Alpha Project",
                                 "title": "q", "predicate": "uses", "question": "What does Alpha Project use now?",
                                 "options": [{"key": "a", "label": "fastapi"}, {"key": "b", "label": "sqlite"}]})
    [item] = inbox_service.load_inbox(memory)
    assert item.informational is True


# ---------- budget ----------


def test_fifty_items_resolve_under_budget_and_parse_each_file_once(memory):
    for i in range(60):
        _episode(memory, f"ep_2026-07-{(i % 28) + 1:02d}_{i:03d}", body=f"user: about alpha-project-{i % 50} today\n")
    for i in range(50):
        _entity(memory, f"alpha-project-{i}", f"Alpha Project {i}", episodes=[f"ep_2026-07-{(i % 28) + 1:02d}_{i:03d}"])
        _item(memory, f"inbox-{i + 1:03d}", {"kind": "decay", "entity_id": f"alpha-project-{i}",
                                                "entity_name": f"Alpha Project {i}", "title": "t"})
    bank_index.invalidate()
    before = bank_index.parse_count
    t0 = time.perf_counter(); items = inbox_service.load_inbox(memory); cold = time.perf_counter() - t0
    assert len(items) == 50 and all(i.cause.tier == "entity" for i in items)
    assert bank_index.parse_count - before <= 110, "each episode/entity frontmatter parsed at most once"
    mid = bank_index.parse_count
    t0 = time.perf_counter(); inbox_service.load_inbox(memory); warm = time.perf_counter() - t0
    assert bank_index.parse_count == mid, "a second load re-parses no frontmatter"
    # The parse counts above are the real guard (they are deterministic); these
    # two are loose smoke bounds against an accidental O(items x files) walk.
    # Do NOT tighten them to the ~100 ms G97 measured on the live bank — a
    # wall-clock assertion at that margin is a flaky test, not a budget.
    assert warm < 1.0, f"warm load took {warm * 1000:.0f} ms"
    assert cold < 5.0, f"cold load took {cold * 1000:.0f} ms"


# ---------- ETag: the server half ----------


@pytest.fixture
def client(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(memory.parent / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    with TestClient(main.app) as c:
        yield c
    config.get_settings.cache_clear()


def test_inbox_etag_moves_when_an_episode_or_entity_changes(client, memory):
    ep = _episode(memory, "ep_2026-08-20_001")
    _entity(memory, "alpha-project", "Alpha Project", episodes=["ep_2026-08-20_001"])
    _item(memory, "inbox-001", {"kind": "decay", "entity_id": "alpha-project", "entity_name": "Alpha Project", "title": "t"})
    r1 = client.get("/inbox"); etag = r1.headers["etag"]
    assert client.get("/inbox", headers={"If-None-Match": etag}).status_code == 304
    time.sleep(0.02)
    markdown_parser.write(ep, markdown_parser.parse(ep).frontmatter, EPISODE_BODY + "user: one more line\n")
    r2 = client.get("/inbox", headers={"If-None-Match": etag})
    assert r2.status_code == 200 and r2.headers["etag"] != etag
    assert r2.json()[0]["cause"]["excerpt"]
