"""What was said about a thing nobody named lands on the page it was said about (G148, `described_landing`). Made-up names only.

The labelled set (`benchmarks/consolidation/described_landing_cases.json`) is the contract for the code gates: every case is
a scratch bank of its own, and a judge rigged to always say yes must land exactly the cases that expect it, bar the two
marked `semantic` that no words can rule out."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from api.services import described_landing as dl
from api.services import markdown_parser, pending_store, search_index, search_service, web_settle
from api.services.claims import parse_claims
from benchmarks.consolidation import described_landing as bench

SPEC = bench.load_cases()
CASES = {c["id"]: c for c in SPEC["cases"]}


def _run(bank: Path, *, yes: bool = True, **kw):
    ask, part = bench.rigged(yes)
    plan = dl.plan_bank(bank)
    return asyncio.run(dl.tend(bank, None, ask, part_read=part, plan=plan, **kw))


def _page_claims(bank: Path, page: str):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{page}.md").body)


@pytest.mark.parametrize("case_id", [c["id"] for c in SPEC["cases"]])
def test_a_judge_that_always_says_yes_lands_only_what_the_code_gates_let_through(tmp_path, case_id):
    case = CASES[case_id]
    bank = bench.build_bank(tmp_path, SPEC, case)
    _run(bank)
    landed = any(c.id == bench.claim_id(case) for p in (bank / "entities").glob("*.md") for c in _page_claims(bank, p.stem))
    assert landed is (case["expect"] == "land" or bool(case.get("semantic"))), case_id


def test_a_judge_that_always_says_no_lands_nothing(tmp_path):
    for case in SPEC["cases"][:7]:
        bank = bench.build_bank(tmp_path / case["id"], SPEC, case)
        report = _run(bank, yes=False)
        assert report.landed == 0
        assert pending_store.load(bank)[0].held_claims, "the fact stays held"


def test_a_landing_is_the_claim_of_the_page_with_its_span_and_no_new_mention(tmp_path):
    case = CASES["r1-of"]
    bank = bench.build_bank(tmp_path, SPEC, case)
    page = bank / "entities" / "cedarloop.md"
    before = markdown_parser.parse(page).frontmatter
    held = pending_store.load(bank)[0].held_claims[0]
    report = _run(bank)
    assert (report.landed, report.pages) == (1, 1)
    landed = [c for c in _page_claims(bank, "cedarloop") if c.id == held["id"]]
    assert len(landed) == 1
    c = landed[0]
    # a claim of the page: subject re-keyed; everything the held claim carried is as it was
    assert c.subject == "cedarloop" and (c.predicate, c.object, c.valid_from, c.observer) == (
        held["predicate"], held["object"], held["valid_from"], held["observer"])
    assert [e.to_dict() for e in c.evidence] == held["evidence"] and c.source_episodes == held["source_episodes"]
    # the words are the label's own, marked as a part; no model wrote them
    assert c.text == "Cedarloop extraction worker keeps timing out on large files (a part of Cedarloop)"
    # the conversation is no new mention: the page's frontmatter is untouched
    assert markdown_parser.parse(page).frontmatter == before
    # the line keeps what did not land and is not closed while it holds anything
    line = pending_store.load(bank)[0]
    assert line.held_claims == [] and line.summary


def test_the_settle_is_recorded_with_the_sentence_and_listed_under_what_sleep_settled(tmp_path):
    bank = bench.build_bank(tmp_path, SPEC, CASES["r3-tool-in-of"])
    _run(bank)
    rows = web_settle.list_settled(bank)
    assert len(rows) == 1 and rows[0]["id"] == "land-001" and rows[0]["group"] == "sleep" and rows[0]["rule"] == dl.RULE
    assert rows[0]["entity_id"] == "quillnote"
    assert rows[0]["quote"] == "There is a bug in the export step of Quillnote that drops tables"


def test_the_same_fact_is_never_landed_twice_and_a_single_valued_belief_is_never_overwritten(tmp_path):
    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    _run(bank)
    line = pending_store.load(bank)[0]
    again = _run(bank)
    assert again.landed == 0 and len(_page_claims(bank, "cedarloop")) == 1 and not line.held_claims
    # a page that already says it: the fact stays held, nothing is written twice
    other = bench.build_bank(tmp_path / "two", SPEC, CASES["r1-of"])
    held = pending_store.load(other)[0].held_claims[0]
    page = other / "entities" / "cedarloop.md"
    parsed = markdown_parser.parse(page)
    from api.services.claims import Claim, write_claims

    same = Claim.from_dict({**held, "id": "clm_other", "subject": "cedarloop"})
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, [same]))
    assert _run(other).landed == 0
    assert pending_store.load(other)[0].held_claims, "left held, nothing lost"


def test_an_undo_takes_the_facts_back_to_their_line_and_the_page_is_never_offered_again(tmp_path):
    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    _run(bank)
    paths, lines, rec = dl.undo(bank, "land-001")
    assert not _page_claims(bank, "cedarloop")
    line = pending_store.load(bank)[0]
    assert [c["id"] for c in line.held_claims] == [bench.claim_id(CASES["r1-of"])]
    assert line.apart_pages() == {"cedarloop"}
    assert not (bank / "inbox" / "settled" / "land-001.md").exists()
    assert _run(bank).landed == 0, "the person's undo holds"
    with pytest.raises(dl.NotLandable):
        dl.undo(bank, "land-001")


def test_an_undo_is_refused_whole_when_a_landed_fact_was_edited_since(tmp_path):
    from api.services.claims import write_claims

    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    _run(bank)
    page = bank / "entities" / "cedarloop.md"
    parsed = markdown_parser.parse(page)
    claims = parse_claims(parsed.body)
    claims[0].confidence = 0.99
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))
    with pytest.raises(dl.NotLandable):
        dl.undo(bank, "land-001")
    assert _page_claims(bank, "cedarloop"), "nothing was changed"


def test_a_stale_span_and_a_closed_claim_and_a_label_held_as_the_object_are_left(tmp_path):
    bank = bench.build_bank(tmp_path / "a", SPEC, CASES["r1-of"])
    ep = bank / "episodes" / f"{bench.EPISODE}.md"
    parsed = markdown_parser.parse(ep)
    markdown_parser.write(ep, parsed.frontmatter, "user: Something else entirely, now.\n" + parsed.body)
    plan = dl.plan_bank(bank)
    assert not plan.items and plan.skipped["span_stale_or_held"] == 1
    bank = bench.build_bank(tmp_path / "b", SPEC, CASES["r1-of"])
    line = pending_store.load(bank)[0]
    line.held_claims[0]["valid_to"] = "2026-11-21"
    pending_store.save(bank, [line])
    assert dl.plan_bank(bank).skipped["closed_or_event"] == 1
    bank = bench.build_bank(tmp_path / "c", SPEC, CASES["r1-of"])
    line = pending_store.load(bank)[0]
    line.held_claims[0].update(subject="somebody", object=pending_store.sanitize_id(line.name))
    pending_store.save(bank, [line])
    assert dl.plan_bank(bank).skipped["label_not_subject"] == 1


def test_a_page_the_person_said_the_mention_is_not_is_never_offered(tmp_path):
    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    pending_store.mark_apart(bank, "Cedarloop extraction worker", ["cedarloop"], [bench.EPISODE])
    assert dl.plan_bank(bank).skipped["person_said_not_that_page"] == 1


def test_the_page_order_is_the_pages_read_most_first():
    pairs = [("a", "low"), ("b", "high"), ("c", "unread")]
    assert dl.order(pairs, {"high": 5.0, "low": 1.0}) == [("b", "high"), ("a", "low"), ("c", "unread")]


def test_a_no_stands_until_the_sentence_changes(tmp_path):
    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    calls = {"n": 0}
    ask, part = bench.rigged(False)

    async def counted(system, prompt):
        calls["n"] += 1
        return await ask(system, prompt)

    async def part_yes(*_a, **_k):
        return True

    for _ in range(2):
        asyncio.run(dl.tend(bank, None, counted, part_read=part_yes, plan=dl.plan_bank(bank)))
    assert calls["n"] == 1, "the second night reads nothing"


def test_a_thing_said_once_is_still_found_by_its_description_and_its_page_now_answers(tmp_path):
    # ruling 41a: landing never makes a mention invisible — the conversation and the held line stay, and the page gains the fact
    case = CASES["r1-of"]
    bank = bench.build_bank(tmp_path, SPEC, case)
    query = "extraction worker timing out"
    search_index.rebuild(bank)
    before = search_service.claim_subject_hits(bank, query)
    assert "cedarloop" not in {h["entity_id"] for h in before}
    _run(bank)
    search_index.rebuild(bank)
    assert bench.EPISODE in (search_index.episodes_with_words(bank, "extraction worker") or set()), "the conversation is still found"
    line = pending_store.held_line(bank, case["line"])
    assert line is not None and line.summary, "the held line, with its description, stays"
    after = search_service.claim_subject_hits(bank, query)
    assert "cedarloop" in {h["entity_id"] for h in after}, "the page answers a question about the feature"


def test_the_rule_in_words_the_relation_is_containment_or_possession_only():
    words = dl._fold_words
    page = dl.Mention(5, 6, frozenset({"p"}))
    runs = lambda s, w: dl.windows(words(s), w)  # noqa: E731
    sentence = "the extraction worker of the cedarloop keeps going"
    names = dl.Mention(words(sentence).index("cedarloop"), words(sentence).index("cedarloop") + 1, frozenset({"p"}))
    assert dl.states_part(words(sentence), names, runs(sentence, ["extraction", "worker"]))
    for text in ("i use cedarloop for the extraction worker", "the extraction worker uses cedarloop",
                 "the extraction worker away from cedarloop"):
        at = words(text).index("cedarloop")
        assert not dl.states_part(words(text), dl.Mention(at, at + 1, frozenset({"p"})), runs(text, ["extraction", "worker"]))
    del page


def test_the_dry_run_prints_ids_never_words(tmp_path, capsys):
    from benchmarks.consolidation import described_landing_bank as dry

    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    before = sorted(p.name for p in bank.rglob("*"))
    out = tmp_path / "eyes.jsonl"
    assert dry.main(["--bank", str(bank), "--eyes", str(out)]) == 0
    shown = capsys.readouterr().out
    assert bench.claim_id(CASES["r1-of"]) in shown and "cedarloop" in shown and "user" in shown
    assert "extraction" not in shown and "Cedarloop" not in shown and "timing" not in shown
    eyes = [json.loads(l) for l in out.read_text().splitlines()]
    assert eyes and "timing out" in eyes[0]["sentence"] and sorted(p.name for p in bank.rglob("*")) == before
