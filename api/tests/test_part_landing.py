"""A part lands on a page only after a second reading (2026-11-24, G148, `part_landing`).

The pair judge is a small model reading a one-line summary beside a page; one `part_of` answer used to land the name on
the page for good, and wrote an "includes" claim on it. Now the engine's main model reads the part's own conversations
beside the page first. Synthetic names; both models are fakes; the rest of Stage 2 is real."""
from __future__ import annotations

import asyncio

from api.services import entity_resolver, part_landing
from api.tests.test_sleep_cycle_hold import _bank, _entity, _episode, _settings

EP, TS = "ep_2026-11-10_001", "2026-11-10T10:00:00+00:00"
EP2, TS2 = "ep_2026-11-12_001", "2026-11-12T10:00:00+00:00"


def _resolve(tmp_path, monkeypatch, *, second: str | Exception, judged="related:part_of", also_same=False):
    memory = _bank(tmp_path)
    _episode(memory, EP2, TS2, "user: the shelf is a separate job with its own budget")
    page = {"id": "cedar-canoe", "frontmatter": {"name": "Cedar Canoe", "type": "project", "status": "active",
                                                 "source_episodes": [EP]},
            "body": "## Summary\nA canoe the person is building.\n"}
    part = _entity("Canoe Shelf", "project", EP2, TS2)
    part["summary"] = "A shelf in the garage."
    asked: list[str] = []

    other = {"id": "river-barge", "frontmatter": {"name": "River Barge", "type": "project", "status": "active",
                                                  "source_episodes": [EP]},
             "body": "## Summary\nA barge the person restores.\n"}

    def verdict(name):
        return "same" if also_same and name == "River Barge" else judged

    async def judge(*_a, **k):
        return verdict(k.get("existing_name"))

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return [verdict(e["name"]) for e in entries]

    async def ask(settings, system, prompt):
        asked.append(prompt)
        if isinstance(second, Exception):
            raise second
        return {"verdict": second, "reason": "x"}

    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", batch)
    monkeypatch.setattr(entity_resolver, "_same_name_ask", ask)
    out = asyncio.run(entity_resolver.resolve(
        [{"episode_id": EP2, "entities": [part], "relationships": []}], [page, other] if also_same else [page], _settings(memory)))
    return out, asked


def test_a_part_the_main_model_confirms_lands_on_the_page(tmp_path, monkeypatch):
    out, asked = _resolve(tmp_path, monkeypatch, second="part")
    assert len(asked) == 1
    assert "separate job with its own budget" in asked[0], "the second reading is shown the part's own conversation"
    assert "A canoe the person is building" in asked[0]
    assert [c["id"] for c in out["changes"] if c["action"] == "update"] == ["cedar-canoe"]
    assert not [c for c in out["changes"] if c["action"] == "create"]


def test_a_part_it_does_not_confirm_stays_its_own_name_and_writes_no_relation(tmp_path, monkeypatch):
    out, asked = _resolve(tmp_path, monkeypatch, second="no")
    assert len(asked) == 1
    assert not [c for c in out["changes"] if c["action"] == "update" and c["id"] == "cedar-canoe"]
    assert not out.get("relations"), "a pair the second reading refused is no 'includes' claim either"


def test_an_unreadable_second_reading_lands_nothing(tmp_path, monkeypatch):
    out, _ = _resolve(tmp_path, monkeypatch, second=ValueError("boom"))
    assert not [c for c in out["changes"] if c["action"] == "update" and c["id"] == "cedar-canoe"]


def test_a_name_the_judge_calls_different_costs_no_second_reading(tmp_path, monkeypatch):
    out, asked = _resolve(tmp_path, monkeypatch, second="part", judged="different")
    assert asked == []


def test_only_part_is_a_yes():
    assert part_landing.verdict_of({"verdict": "part"})
    assert part_landing.verdict_of({"verdict": " Part "})
    assert not part_landing.verdict_of({"verdict": "no"})
    assert not part_landing.verdict_of({"verdict": "part of it, maybe not"})
    assert not part_landing.verdict_of(None) and not part_landing.verdict_of("part") and not part_landing.verdict_of({})


def test_the_prompt_names_both_sides_and_cuts_a_long_conversation():
    prompt = part_landing.prompt_for("B name", "B summary", "x" * 50, "A name", "## Summary\nA body\n```claims\n{}\n```")
    assert "B name" in prompt and "B summary" in prompt and "A name" in prompt and "A body" in prompt
    assert "```claims" not in prompt, "the page's claim fence is not read"


def test_a_part_verdict_beside_a_same_match_writes_no_includes_claim_when_refused(tmp_path, monkeypatch):
    """The pair judge called the name a part of one page and the same as another: the name joins the other, and the
    part verdict, were it left in the judge's cache, would write the first page an "includes" claim (`_judged_relations`)
    for a part no second reading confirmed (measured 2026-11-24: a kitchen joined to another kitchen while the flat
    renovation in another city was written to include it)."""
    out, asked = _resolve(tmp_path, monkeypatch, second="no", also_same=True)
    assert len(asked) == 1
    assert [c["id"] for c in out["changes"] if c["action"] == "update"] == ["river-barge"]
    assert not [r for r in out["relations"] if r["source_page"] == "cedar-canoe"]


def test_a_judge_that_reads_the_pair_backwards_is_corrected_by_the_reading(tmp_path, monkeypatch):
    """Measured on a benchmark's key runs (2026-11-24): the small judge answered `has_part` (the page is a part of the
    name) for a trip's flights, so the part was never asked about, stayed its own held line, and the trip's page was
    written "part-of" the flights. The reading is asked the same question once; its "part" lands the name."""
    out, asked = _resolve(tmp_path, monkeypatch, second="part", judged="related:has_part")
    assert len(asked) == 1
    assert [c["id"] for c in out["changes"] if c["action"] == "update"] == ["cedar-canoe"]
    assert not out.get("relations"), "the backwards relation is not written for a name that landed on the page"


def test_a_backwards_verdict_the_reading_refuses_stays_the_judges_relation(tmp_path, monkeypatch):
    """The reading answers one direction only: its "no" is not an overrule of `has_part` (a whole named after its part)."""
    out, asked = _resolve(tmp_path, monkeypatch, second="no", judged="related:has_part")
    assert len(asked) == 1
    assert not [c for c in out["changes"] if c["action"] == "update" and c["id"] == "cedar-canoe"]
    assert [r["label"] for r in out["relations"]] == ["part-of"], "the judge's own relation is kept"


def test_a_backwards_verdict_beside_a_same_match_costs_no_second_reading(tmp_path, monkeypatch):
    out, asked = _resolve(tmp_path, monkeypatch, second="part", judged="related:has_part", also_same=True)
    assert asked == []
