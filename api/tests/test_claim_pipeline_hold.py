"""G141 PJ-0b (R-HP2, R-HP5..R-HP8, R-HP10, R-HP12): Stage 5.56 holds what it
heard about a name with no page WITH that name's pending entity, and releases
it — first, through Stage 3, spans intact, the first conversation credited —
in the cycle whose Stage 5 gave the name a page. Synthetic names only."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from loguru import logger

from api.services import claim_pipeline, evidence, fact_sources, markdown_parser, pending_store, predicates
from api.services.claims import Claim, parse_claims, write_claims
from api.services.pending_store import HoldOutcome, PendingEntity

EP_A, TS_A = "ep_2026-09-20_001", "2026-09-20T10:00:00+00:00"
EP_B, TS_B = "ep_2026-09-22_001", "2026-09-22T10:00:00+00:00"
BODY_A = "user: Zed Unknown works at Alpha Lab and recommends Gamma Board.\nassistant: Noted."
BODY_B = "user: Zed Unknown works at Beta Lab now.\nassistant: Good to know."
FENCE = "`" * 3
BROKEN = f"## Summary\nA synthetic page.\n\n{FENCE}claims\n- id: [unclosed\n{FENCE}"


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


def _episode(memory: Path, ep: str, ts: str, body: str) -> str:
    """Write an episode and return its stored evidence text (what a span hashes)."""
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "processed": True, "source": "mcp", "timestamp": ts}, body)
    return evidence.source_text(memory, ep)


def _park(memory: Path, name: str) -> None:
    """What Stage 2's flush does for a name it did not promote."""
    pending_store.upsert(memory, PendingEntity(
        name=name, type="person", description="Mentioned once.", source_episode=EP_A,
        confidence=0.6, tags=[], history_entries=[]))


def _rel(source: str, label: str, target: str, ep: str, ts: str, text: str, quote: str) -> dict:
    return {"source": source, "target": target, "label": label, "source_episode": ep,
            "source_episode_timestamp": ts,
            "evidence": [evidence.verify(None, ep, quote, text=text).to_dict()]}


def _extracted(ep: str, ts: str, *rels: dict) -> list[dict]:
    return [{"episode_id": ep, "episode_timestamp": ts, "origin": "claude-code",
             "entities": [], "relationships": list(rels)}]


def _page(memory: Path, entity_id: str, name: str, body: str = "## Summary\nA synthetic page.") -> Path:
    """What Stage 5 writes for a promoted name (credited to the promoting episode)."""
    path = memory / "entities" / f"{entity_id}.md"
    markdown_parser.write(path, {"name": name, "type": "person", "status": "active",
                                 "source_episodes": [EP_B]}, body)
    return path


def _claims(memory: Path, entity_id: str) -> list[Claim]:
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{entity_id}.md").body)


def _run(memory: Path, extracted: list[dict], *, now: str, name_to_id: dict | None = None) -> dict:
    return claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory),
                                             now_date=now, name_to_id=name_to_id or {})


def _hear_recommendation(memory: Path) -> tuple[dict, str]:
    """Conversation 1: "Zed Unknown" is parked, has no page, and Stage 1 heard one claim about it."""
    text = _episode(memory, EP_A, TS_A, BODY_A)
    _park(memory, "Zed Unknown")
    rel = _rel("Zed Unknown", "recommends", "Gamma Board", EP_A, TS_A, text, "recommends Gamma Board")
    return _run(memory, _extracted(EP_A, TS_A, rel), now="2026-09-20"), text


def test_a_claim_on_an_unpromoted_name_is_held_with_its_span_and_no_page_is_made(tmp_path):
    memory = _bank(tmp_path)
    result, text = _hear_recommendation(memory)
    assert (result["claims_held"], result["claims_page_less"], result["claims_waiting"]) == (1, 0, 1)
    assert result["subjects_skipped"] == 1 and result["page_less_subjects"] == ["zed-unknown"]
    assert list((memory / "entities").glob("*.md")) == []
    (line,) = pending_store.load(memory)
    assert line.name == "Zed Unknown"
    (held,) = [Claim.from_dict(d) for d in line.held_claims]
    assert (held.subject, held.predicate, held.object) == ("zed-unknown", "recommends", "gamma-board")
    assert (held.observer, held.context, held.source_trust, held.valid_from) == (
        "agent", "general", "agent_extracted", "2026-09-20")
    (ev,) = held.evidence
    assert ev.episode == EP_A and text[ev.start:ev.end] == "recommends Gamma Board"


def test_promotion_writes_the_held_claim_onto_the_new_page_with_its_span_current(tmp_path):
    memory = _bank(tmp_path)
    _hear_recommendation(memory)
    held_id = pending_store.load(memory)[0].held_claims[0]["id"]
    _episode(memory, EP_B, TS_B, BODY_B)
    _page(memory, "zed-unknown", "Zed Unknown")
    result = _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})

    (claim,) = _claims(memory, "zed-unknown")
    assert claim.id == held_id and claim.valid_to is None
    (ev,) = claim.evidence
    text = evidence.source_text(memory, EP_A)
    assert text[ev.start:ev.end] == "recommends Gamma Board"
    assert evidence.span_status(text, end=ev.end, hash=ev.hash) == evidence.SPAN_CURRENT
    fm = markdown_parser.parse(memory / "entities" / "zed-unknown.md").frontmatter
    assert fm["source_episodes"] == [EP_B, EP_A]  # R-HP8: the first conversation credits the page
    assert (result["claims_released"], result["claims_waiting"]) == (1, 0)
    assert pending_store.load(memory) == []


def test_a_held_claim_keeps_its_span_when_the_episode_grew_since(tmp_path):
    memory = _bank(tmp_path)
    _hear_recommendation(memory)
    held = Claim.from_dict(pending_store.load(memory)[0].held_claims[0])
    # A resumed session: the Stop hook appends turns to the same episode (G104).
    _episode(memory, EP_A, TS_A, BODY_A + "\nuser: One more thing.\nassistant: Sure.")
    _page(memory, "zed-unknown", "Zed Unknown")
    _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    (claim,) = _claims(memory, "zed-unknown")
    assert claim.evidence == held.evidence  # never re-located (R-HP7)
    (ev,) = claim.evidence
    assert evidence.span_status(evidence.source_text(memory, EP_A), end=ev.end, hash=ev.hash) == evidence.SPAN_GROWN


def test_a_newer_claim_supersedes_the_released_one_instead_of_asking(tmp_path):
    memory = _bank(tmp_path)
    text_a = _episode(memory, EP_A, TS_A, BODY_A)
    _park(memory, "Zed Unknown")
    _run(memory, _extracted(EP_A, TS_A, _rel("Zed Unknown", "works at", "Alpha Lab", EP_A, TS_A, text_a,
                                             "Zed Unknown works at Alpha Lab")), now="2026-09-20")
    text_b = _episode(memory, EP_B, TS_B, BODY_B)
    _page(memory, "zed-unknown", "Zed Unknown")
    result = _run(memory, _extracted(EP_B, TS_B, _rel("Zed Unknown", "works at", "Beta Lab", EP_B, TS_B, text_b,
                                                      "Zed Unknown works at Beta Lab")),
                  now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    by_object = {c.object: c for c in _claims(memory, "zed-unknown")}
    old, new = by_object["alpha-lab"], by_object["beta-lab"]
    assert (old.valid_to, old.superseded_by, new.valid_to) == ("2026-09-22", new.id, None)
    assert not [n for n in result["nudges"] if n.get("action") == "conflict_nudge"]


def test_a_held_name_stage2_matched_to_an_existing_page_is_released_there(tmp_path):
    memory = _bank(tmp_path)
    _hear_recommendation(memory)
    _page(memory, "zed-example", "Zed Example")
    result = _run(memory, [], now="2026-09-22",
                  name_to_id={"zed example": "zed-example", "zed unknown": "zed-example"})
    (claim,) = _claims(memory, "zed-example")
    assert (claim.subject, claim.object) == ("zed-example", "gamma-board")
    assert not (memory / "entities" / "zed-unknown.md").exists()
    assert result["claims_released"] == 1 and pending_store.load(memory) == []


def test_release_waits_while_the_page_cannot_be_written(tmp_path):
    memory = _bank(tmp_path)
    _hear_recommendation(memory)
    page = _page(memory, "zed-unknown", "Zed Unknown", body=BROKEN)
    before = page.read_text(encoding="utf-8")
    result = _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    assert (result["claims_released"], result["claims_waiting"]) == (0, 1)
    assert page.read_text(encoding="utf-8") == before
    _page(memory, "zed-unknown", "Zed Unknown")  # the page is fixed; no mention needed to release
    result = _run(memory, [], now="2026-09-23")
    assert (result["claims_released"], result["claims_waiting"]) == (1, 0)
    assert len(_claims(memory, "zed-unknown")) == 1


def test_a_held_claim_already_on_its_page_is_not_offered_to_stage3_again(tmp_path):
    """R-HP6's idempotency guard. A release whose page write landed but whose
    store removal did not; since then a newer claim closed the released one on
    the page. Offered to Stage 3 again, the open held copy would meet its own
    successor and ask the person about a value recency already settled."""
    memory = _bank(tmp_path)
    text_a = _episode(memory, EP_A, TS_A, BODY_A)
    _park(memory, "Zed Unknown")
    _run(memory, _extracted(EP_A, TS_A, _rel("Zed Unknown", "works at", "Alpha Lab", EP_A, TS_A, text_a,
                                             "Zed Unknown works at Alpha Lab")), now="2026-09-20")
    held = Claim.from_dict(pending_store.load(memory)[0].held_claims[0])
    newer = Claim(id="clm_2026-09-21_beta0001", text="Zed Unknown works at Beta Lab", subject="zed-unknown",
                  predicate=held.predicate, object="beta-lab", valid_from="2026-09-21", supersedes=held.id)
    closed = Claim.from_dict({**held.to_dict(), "valid_to": "2026-09-21", "superseded_by": newer.id})
    page = _page(memory, "zed-unknown", "Zed Unknown")
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, [closed, newer]))
    result = _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    assert [(c.id, c.valid_to) for c in _claims(memory, "zed-unknown")] == [
        (held.id, "2026-09-21"), (newer.id, None)]
    assert not [n for n in result["nudges"] if n.get("action") == "conflict_nudge"]
    assert pending_store.load(memory) == []


def test_owner_surfaces_events_and_claims_closed_in_their_batch_are_never_held(tmp_path):
    memory = _bank(tmp_path)
    text_a = _episode(memory, EP_A, TS_A, BODY_A)
    text_b = _episode(memory, EP_B, TS_B, BODY_B)
    _park(memory, "Zed Unknown")
    _park(memory, "The User")  # Stage 1 listed the person as an entity; no owner page exists
    extracted = _extracted(
        EP_A, TS_A,
        _rel("the user", "connects to", "Lab Cluster Example", EP_A, TS_A, text_a, "Zed Unknown"),
        _rel("Zed Unknown", "works at", "Alpha Lab", EP_A, TS_A, text_a, "Zed Unknown works at Alpha Lab"),
    ) + _extracted(
        EP_B, TS_B,
        _rel("Zed Unknown", "works at", "Beta Lab", EP_B, TS_B, text_b, "Zed Unknown works at Beta Lab"),
    )
    result = _run(memory, extracted, now="2026-09-22")
    held = {e.name: [d["object"] for d in e.held_claims] for e in pending_store.load(memory)}
    assert held == {"Zed Unknown": ["beta-lab"], "The User": []}  # Alpha was closed by Beta in its own batch
    assert (result["claims_held"], result["claims_page_less"]) == (1, 2)
    event = Claim(id="clm_evt", text="t", subject="zed-unknown", predicate="happened", object="x", status="done")
    assert claim_pipeline.hold_page_less({"zed-unknown": [event]}, memory) == {"zed-unknown": HoldOutcome(0, 0)}


def test_the_cap_holds_fifty_per_name_and_counts_the_rest(tmp_path):
    memory = _bank(tmp_path)
    text_a = _episode(memory, EP_A, TS_A, BODY_A)
    _park(memory, "Zed Unknown")
    rels = [_rel("Zed Unknown", "uses", f"Tool Example {n:02d}", EP_A, TS_A, text_a, "Zed Unknown")
            for n in range(1, pending_store.MAX_HELD_CLAIMS + 3)]
    first = _run(memory, _extracted(EP_A, TS_A, *rels), now="2026-09-20")
    assert (first["claims_held"], first["claims_hold_capped"], first["claims_page_less"]) == (50, 2, 2)
    kept = [d["id"] for d in pending_store.load(memory)[0].held_claims]
    again = _run(memory, _extracted(EP_A, TS_A, *rels), now="2026-09-21")
    assert (again["claims_held"], again["claims_hold_capped"]) == (50, 2)
    assert [d["id"] for d in pending_store.load(memory)[0].held_claims] == kept


def test_the_hold_and_the_release_are_logged_as_counts_never_as_a_name(tmp_path):
    memory = _bank(tmp_path)
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG",
                      filter=lambda r: r["name"] in ("api.services.claim_pipeline", "api.services.pending_store"))
    try:
        _hear_recommendation(memory)
        _page(memory, "zed-unknown", "Zed Unknown")
        _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    finally:
        logger.remove(sink)
    joined = "\n".join(lines)
    assert "1 held for a pending name" in joined and "1 released onto their page" in joined
    for needle in ("Zed Unknown", "zed-unknown", "Gamma Board", "gamma-board"):
        assert needle not in joined


def test_a_pending_store_failure_costs_the_hold_never_the_cycle_claims(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    text_a = _episode(memory, EP_A, TS_A, BODY_A)
    _park(memory, "Zed Unknown")
    _page(memory, "alpha-lab", "Alpha Lab")

    def boom(*_a, **_k):
        raise OSError("store unavailable")

    monkeypatch.setattr(pending_store, "ready", boom)
    monkeypatch.setattr(pending_store, "hold", boom)
    result = _run(memory, _extracted(
        EP_A, TS_A,
        _rel("Alpha Lab", "supports", "Gamma Board", EP_A, TS_A, text_a, "Alpha Lab"),
        _rel("Zed Unknown", "recommends", "Gamma Board", EP_A, TS_A, text_a, "recommends Gamma Board"),
    ), now="2026-09-20")
    assert [c.object for c in _claims(memory, "alpha-lab")] == ["gamma-board"]
    assert (result["claims_held"], result["claims_page_less"]) == (0, 1)


def test_a_released_claim_counts_as_newly_written_for_the_cited_link_attach(tmp_path):
    """R-HP8: G61 phase 2 S1 attaches a link found verbatim in a newly written
    claim's cited span. A released claim is written for the first time too."""
    memory = _bank(tmp_path)
    link = "https://example.com/alpha-lab/team"
    line = f"Zed Unknown works at Alpha Lab; the team page {link} lists them."
    text = _episode(memory, EP_A, TS_A, f"user: {line}\nassistant: Noted.")
    _park(memory, "Zed Unknown")
    _run(memory, _extracted(EP_A, TS_A, _rel("Zed Unknown", "works at", "Alpha Lab", EP_A, TS_A, text, line)),
         now="2026-09-20")
    _page(memory, "zed-unknown", "Zed Unknown")
    _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    assert [(s["ref"], s["predicate"]) for s in fact_sources.list_sources(memory, "zed-unknown")] == [
        (link, "works-at")]
