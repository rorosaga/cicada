"""What was said about a thing nobody named lands on the page the conversation says it is about (G148, `described_landing`).
Made-up names only.

The labelled set (`benchmarks/consolidation/described_landing_cases.json`) is the contract for the CODE conditions around the
read: every case is a scratch bank of its own, and a reader rigged to always name the same candidate must land NOTHING a case
marks ``by: code`` (an assistant's words, a company, an owner's, an archived or ambiguous page, a label the conversation
said, no page named, a page that is a tool or a concept). What it lands among the ``by: reader`` cases is exactly what rests on the engine's main model, which the
benchmark measures (`benchmarks/consolidation/described_landing.py --judges real`)."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from api.services import described_landing as dl
from api.services import markdown_parser, pending_store, search_index, search_service, web_settle
from api.services.claims import parse_claims
from benchmarks.consolidation import described_landing as bench

SPEC = bench.load_cases()
CASES = {c["id"]: c for c in SPEC["cases"]}
CLAIMS = [(c["id"], k) for c in SPEC["cases"] for k in range(len(c["claims"]))]


def _run(bank: Path, mode: str = "first", ask=None, **kw):
    plan = dl.plan_bank(bank)
    return asyncio.run(dl.tend(bank, None, ask or bench.rigged(mode), plan=plan, **kw))


def _page_claims(bank: Path, page: str):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{page}.md").body)


def _landed_ids(bank: Path) -> set[str]:
    return {c.id for p in (bank / "entities").glob("*.md") for c in _page_claims(bank, p.stem)}


def scripted(first: dict | list, second: dict | list | None = None, calls: list | None = None):
    """A reader that answers from a script: ``{n: {"page": <page NAME>, "sentence": ..., "scope": ...}}`` for the first
    reading, and for the second (the reverse candidate order, told to doubt). The page is given by name, answered as the letter
    the prompt lists it under."""
    reads = [first, second if second is not None else first]

    async def ask(system: str, prompt: str) -> object:
        which = 1 if "Be a skeptic" in prompt else 0
        if calls is not None:
            calls.append(prompt)
        letters = {name: letter for letter, name in re.findall(r"^([A-F])\. (.+?) — ", prompt, re.M)}
        script = reads[which]
        if not isinstance(script, dict):
            return script
        rows = []
        for n, row in script.items():
            page = row.get("page", "none")
            rows.append({"n": n, **row, "page": letters.get(page, "none") if page != "none" else "none"})
        return {"claims": rows}

    return ask


# ---------------------------------------------------------------------------------------------------- the code conditions


@pytest.mark.parametrize("mode", ["first", "last"])
@pytest.mark.parametrize("case_id", [c["id"] for c in SPEC["cases"]])
def test_a_reader_that_always_says_yes_lands_nothing_the_code_must_refuse(tmp_path, case_id, mode):
    case = CASES[case_id]
    bank = bench.build_bank(tmp_path, SPEC, case)
    _run(bank, mode)
    landed = _landed_ids(bank)
    for k, c in enumerate(case["claims"]):
        if case.get("by") == "code" and c["expect"] == "left":
            assert bench.claim_id(case, k) not in landed, case_id


def test_a_reader_that_always_says_none_lands_nothing_and_the_fact_stays_held(tmp_path):
    for case in SPEC["cases"][:7]:
        bank = bench.build_bank(tmp_path / case["id"], SPEC, case)
        report = _run(bank, "none")
        assert report.landed == 0
        assert pending_store.load(bank)[0].held_claims, "the fact stays held"


def test_the_candidates_are_the_live_pages_the_conversation_names_in_the_persons_own_turns(tmp_path):
    def groups(case_id):
        bank = bench.build_bank(tmp_path / case_id, SPEC, CASES[case_id])
        return dl.plan_bank(bank)

    # named one turn earlier, the claim's own sentence names nothing: the page is a candidate
    plan = groups("n1-named-one-turn-earlier")
    assert [g.candidates for g in plan.groups] == [["cedarloop"]]
    # two pages named: both, the nearest the claim's turn first
    plan = groups("n4b-two-pages-fact-about-the-second")
    assert sorted(plan.groups[0].candidates) == ["pebblegrid", "tidewell"]
    # the assistant's words never name a candidate; a company, an archived page, the owner's page, an ambiguous name never are
    for case_id in ("t6-assistants-words", "t7-company", "t8-ambiguous-name", "t9-archived-page", "t10-owners-page"):
        assert not groups(case_id).groups, case_id
    # no page named at all: held, never read
    plan = groups("t1-person-only")
    assert not plan.groups and plan.skipped["no_candidate_page"] == 1


@pytest.mark.parametrize("case_id", ["r3-tool-in-of", "r4-concept", "t3-tool-used-for", "t4-runs-in-tool",
                                     "n11-tool-used-with-earlier-turn", "w1-function-runs-on-a-cloud-tool",
                                     "w2-account-switch-in-a-business-tool", "w3-exercise-query-on-a-concept",
                                     "w4-portfolio-on-an-idea"])
def test_only_a_project_is_a_page_a_fact_lands_on_a_tool_or_a_concept_is_held_by_code_before_any_read(tmp_path, case_id):
    # the dry run on a real bank: a thing built with a tool, an account in it, a specific thing on a general notion's page
    case = CASES[case_id]
    assert case["by"] == "code" and all(c["expect"] == "left" for c in case["claims"])
    bank = bench.build_bank(tmp_path, SPEC, case)
    plan = dl.plan_bank(bank)
    assert not plan.groups and plan.skipped["named_pages_not_projects"] == len(case["claims"]), plan.skipped
    calls: list[str] = []
    report = _run(bank, ask=scripted({1: {"page": "none"}}, calls=calls))
    assert not calls and report.landed == 0, "no model is asked"
    assert report.skipped["named_pages_not_projects"] == len(case["claims"])
    assert pending_store.load(bank)[0].held_claims, "the fact stays held"


def test_a_tool_named_beside_a_project_is_no_candidate_and_the_project_still_is(tmp_path):
    bank = bench.build_bank(tmp_path, SPEC, CASES["w5-project-named-beside-a-tool"])
    plan = dl.plan_bank(bank)
    assert [g.candidates for g in plan.groups] == [["tidewell"]] and not plan.skipped["named_pages_not_projects"]
    # a conversation that names no page at all is still the old reason
    assert dl.plan_bank(bench.build_bank(tmp_path / "none", SPEC, CASES["t1-person-only"])).skipped["no_candidate_page"] == 1


def test_a_label_that_is_the_project_in_other_words_lands_with_the_page_itself_named(tmp_path):
    bank = bench.build_bank(tmp_path, SPEC, CASES["w6-project-description-in-other-words"])
    sentence = "The open-source importer project is written in Rust, and Cedarloop ships it every Friday"
    _run(bank, ask=scripted({1: {"page": "Cedarloop", "scope": "whole", "sentence": sentence}}))
    (c,) = _page_claims(bank, "cedarloop")
    assert c.text.endswith("(about Cedarloop itself)") and "a part of" not in c.text


def test_a_page_the_person_said_the_mention_is_not_is_never_offered(tmp_path):
    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    pending_store.mark_apart(bank, "Cedarloop extraction worker", ["cedarloop"], [bench.EPISODE])
    plan = dl.plan_bank(bank)
    assert not plan.groups and plan.skipped["no_candidate_page"] == 1


def test_a_stale_span_and_a_closed_claim_and_a_label_held_as_the_object_are_left(tmp_path):
    bank = bench.build_bank(tmp_path / "a", SPEC, CASES["r1-of"])
    ep = bank / "episodes" / f"{bench.EPISODE}.md"
    parsed = markdown_parser.parse(ep)
    markdown_parser.write(ep, parsed.frontmatter, "user: Something else entirely, now.\n" + parsed.body)
    plan = dl.plan_bank(bank)
    assert not plan.groups and plan.skipped["span_stale_or_held"] == 1
    bank = bench.build_bank(tmp_path / "b", SPEC, CASES["r1-of"])
    line = pending_store.load(bank)[0]
    line.held_claims[0]["valid_to"] = "2026-11-21"
    pending_store.save(bank, [line])
    assert dl.plan_bank(bank).skipped["nothing_the_label_said_with_words"] == 1
    bank = bench.build_bank(tmp_path / "c", SPEC, CASES["r1-of"])
    line = pending_store.load(bank)[0]
    line.held_claims[0].update(subject="somebody", object=pending_store.sanitize_id(line.name))
    pending_store.save(bank, [line])
    assert dl.plan_bank(bank).skipped["nothing_the_label_said_with_words"] == 1


def test_the_claims_own_other_end_is_never_the_page_it_is_about(tmp_path):
    # "The export step of Tidewell writes everything to Cedarloop": the fact's own object is Cedarloop, so a reader that
    # names Cedarloop is refused in code; Tidewell stays offered
    bank = bench.build_bank(tmp_path, SPEC, CASES["r6-other-endpoint"])
    ask = scripted({1: {"page": "Cedarloop", "scope": "whole", "sentence": "The export step of Tidewell writes everything to Cedarloop every night."}})
    report = _run(bank, ask=ask)
    assert report.landed == 0 and "first_read_names_the_claims_own_object" in report.skipped


# ---------------------------------------------------------------------------------------------------- the reads


def test_a_landing_is_the_claim_of_the_page_with_its_spans_and_no_new_mention(tmp_path):
    case = CASES["r1-of"]
    bank = bench.build_bank(tmp_path, SPEC, case)
    page = bank / "entities" / "cedarloop.md"
    before = markdown_parser.parse(page).frontmatter
    held = pending_store.load(bank)[0].held_claims[0]
    sentence = "The extraction worker of Cedarloop keeps timing out on large files."
    report = _run(bank, ask=scripted({1: {"page": "Cedarloop", "scope": "part", "sentence": sentence}}))
    assert (report.landed, report.pages, report.calls) == (1, 1, 2), "one call a reading, two readings"
    landed = [c for c in _page_claims(bank, "cedarloop") if c.id == held["id"]]
    assert len(landed) == 1
    c = landed[0]
    # a claim of the page: subject re-keyed; everything the held claim carried is as it was
    assert c.subject == "cedarloop" and (c.predicate, c.object, c.valid_from, c.observer) == (
        held["predicate"], held["object"], held["valid_from"], held["observer"])
    assert c.source_episodes == held["source_episodes"]
    # its own span first, as it was; then the sentence the reader copied, located in the conversation
    assert c.evidence[0].to_dict() == held["evidence"][0]
    text = (bank / "episodes" / f"{bench.EPISODE}.md").read_text()
    assert len(c.evidence) == 2 and sentence in markdown_parser.parse(bank / "episodes" / f"{bench.EPISODE}.md").body
    copied = c.evidence[1]
    body = markdown_parser.parse(bank / "episodes" / f"{bench.EPISODE}.md").body
    assert body[copied.start:copied.end] == sentence and copied.kind == "user"
    del text
    # the words are the label's own, marked as a part when both readings said a part; no model wrote them
    assert c.text == "Cedarloop extraction worker keeps timing out on large files (a part of Cedarloop)"
    # the conversation is no new mention: the page's frontmatter is untouched
    assert markdown_parser.parse(page).frontmatter == before
    # the line keeps what did not land and is not closed while it holds anything
    line = pending_store.load(bank)[0]
    assert line.held_claims == [] and line.summary


def test_the_claims_words_follow_what_both_reads_said_the_label_is(tmp_path):
    sentence = "Tidewell's weekly digest email goes out on Fridays now."

    def landed_text(name: str, first: dict, second: dict | None = None) -> str:
        bank = bench.build_bank(tmp_path / name, SPEC, CASES["r2-possessive"])
        _run(bank, ask=scripted({1: {"page": "Tidewell", "sentence": sentence, **first}},
                                None if second is None else {1: {"page": "Tidewell", "sentence": sentence, **second}}))
        (c,) = _page_claims(bank, "tidewell")
        return c.text

    base = "Tidewell weekly digest email goes out on Fridays"
    assert landed_text("part", {"scope": "part"}) == f"{base} (a part of Tidewell)"
    assert landed_text("whole", {"scope": "whole"}) == f"{base} (about Tidewell itself)", "the label is the page in other words"
    # a disagreement, a reader that said nothing on it, or a word it was not asked: the weaker wording, never a refusal
    assert landed_text("split", {"scope": "part"}, {"scope": "whole"}) == base
    assert landed_text("silent", {}) == base
    assert landed_text("odd", {"scope": "mostly"}) == base


def test_a_page_named_two_turns_earlier_is_read_with_the_turns_before_it_and_lands_on_the_sentence_copied(tmp_path):
    case = CASES["n2-named-two-turns-earlier"]
    bank = bench.build_bank(tmp_path, SPEC, case)
    prompts: list[str] = []
    sentence = "The nightly importer rejects files over fifty megabytes."
    report = _run(bank, ask=scripted({1: {"page": "Cedarloop", "scope": "part", "sentence": sentence}}, calls=prompts))
    assert report.landed == 1
    first, second = prompts
    assert "[1] user: Quick update on Cedarloop." in first and "[3] user: The nightly importer rejects" in first
    assert "A. Cedarloop — Cedarloop is something the person works on." in first
    assert "Be a skeptic" in second and "Be a skeptic" not in first, "the second reading is told to doubt"
    assert "Candidates" in second
    (c,) = _page_claims(bank, "cedarloop")
    body = markdown_parser.parse(bank / "episodes" / f"{bench.EPISODE}.md").body
    assert body[c.evidence[-1].start:c.evidence[-1].end] == sentence


def test_a_line_s_claims_from_one_conversation_are_read_in_one_call(tmp_path):
    case = CASES["m1-two-claims-one-about-the-page"]
    bank = bench.build_bank(tmp_path, SPEC, case)
    prompts: list[str] = []
    row = {"page": "Cedarloop", "scope": "whole", "sentence": "The nightly importer rejects files over fifty megabytes."}
    report = _run(bank, ask=scripted({1: row, 2: {"page": "none"}}, calls=prompts))
    assert report.landed == 1 and len(prompts) == 2, "two claims, one call a reading"
    assert "1. " in prompts[0] and "2. " in prompts[0]
    assert "2. " not in prompts[1].split("Facts:")[1].split("For each fact")[0], "only what the first reading named is read again"
    line = pending_store.load(bank)[0]
    assert [c["id"] for c in line.held_claims] == [bench.claim_id(case, 1)]


@pytest.mark.parametrize("name,first,second", [
    ("none", {1: {"page": "none"}}, None),
    ("the second reading says none", {1: {"page": "Cedarloop", "sentence": "The extraction worker of Cedarloop keeps timing out on large files."}},
     {1: {"page": "none"}}),
    ("an unusable reply", "not json at all", None),
    ("no such candidate", {1: {"page": "Z", "sentence": "x"}}, None),
    ("a sentence nobody said", {1: {"page": "Cedarloop", "sentence": "The extraction worker of Cedarloop crashed on small files."}}, None),
    ("a sentence cut from an assistant's turn", {1: {"page": "Cedarloop", "sentence": "Try a smaller batch size."}}, None),
    ("a changed character", {1: {"page": "Cedarloop", "sentence": "The extraction worker of Cedarloop keeps timing out on large file."}}, None),
])
def test_anything_but_two_agreeing_located_readings_leaves_the_fact_held(tmp_path, name, first, second):
    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    report = _run(bank, ask=scripted(first, second))
    assert report.landed == 0, name
    assert pending_store.load(bank)[0].held_claims, "still held"
    assert not _page_claims(bank, "cedarloop")


def test_two_readings_that_name_different_candidates_land_nothing(tmp_path):
    case = CASES["n4b-two-pages-fact-about-the-second"]
    bank = bench.build_bank(tmp_path, SPEC, case)
    s = "Pebblegrid is behind, the signup form times out on slow phones."
    report = _run(bank, ask=scripted({1: {"page": "Pebblegrid", "sentence": s}}, {1: {"page": "Tidewell", "sentence": s}}))
    assert report.landed == 0 and report.skipped["reads_disagree"] == 1
    assert _run(bank, ask=scripted({1: {"page": "Pebblegrid", "sentence": s}})).skipped["read_already"] == 1, "a read stands"
    other = bench.build_bank(tmp_path / "again", SPEC, case)
    report = _run(other, ask=scripted({1: {"page": "Pebblegrid", "sentence": s}}))
    assert report.landed == 1 and _page_claims(other, "pebblegrid") and not _page_claims(other, "tidewell")


def test_a_sentence_outside_the_shown_window_is_never_accepted(tmp_path):
    # six turns after the claim: the window ends two turns after it, so a sentence from further on cannot be copied
    lines = ["user: Quick update on Cedarloop.", "assistant: Go ahead.", "user: The nightly importer rejects files over fifty megabytes."]
    for i in range(6):
        lines += [f"assistant: Noted {i}.", f"user: Unrelated remark number {i} about the weather."]
    case = {**CASES["n2-named-two-turns-earlier"], "conversation": "\n".join(lines)}
    bank = bench.build_bank(tmp_path, SPEC, case)
    far = "Unrelated remark number 5 about the weather."
    report = _run(bank, ask=scripted({1: {"page": "Cedarloop", "sentence": far}}))
    assert report.landed == 0 and report.skipped["first_read_sentence_not_located"] == 1


def test_a_no_stands_until_the_sentence_or_a_page_changes_and_a_failed_call_is_read_again(tmp_path):
    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    calls: list[str] = []
    none = scripted({1: {"page": "none"}}, calls=calls)
    for _ in range(2):
        _run(bank, ask=none)
    assert len(calls) == 1, "the second night reads nothing"
    # the candidate's page changes: read again
    page = bank / "entities" / "cedarloop.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, "Cedarloop is a data importer.\n")
    _run(bank, ask=none)
    assert len(calls) == 2

    other = bench.build_bank(tmp_path / "failed", SPEC, CASES["r1-of"])
    n = {"n": 0}

    async def broken(system, prompt):
        n["n"] += 1
        raise RuntimeError("boom")

    for _ in range(2):
        report = _run(other, ask=broken)
        assert report.landed == 0
    assert n["n"] == 2, "a failed call is not remembered as a no"


def test_a_plan_limit_is_a_pause_nothing_lands_and_nothing_is_forgotten(tmp_path):
    from api.services import engine_errors

    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])

    async def limited(system, prompt):
        raise engine_errors.EngineThrottled("limit")

    report = _run(bank, ask=limited)
    assert report.landed == 0 and report.skipped["plan_limit"] == 1
    assert pending_store.load(bank)[0].held_claims, "still held"
    assert _run(bank).landed == 1, "read again next run, not remembered as a no"


# ---------------------------------------------------------------------------------------------------- landing, record, undo


def test_the_settle_is_recorded_with_the_sentence_and_listed_under_what_sleep_settled(tmp_path):
    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    _run(bank)
    rows = web_settle.list_settled(bank)
    assert len(rows) == 1 and rows[0]["id"] == "land-001" and rows[0]["group"] == "sleep" and rows[0]["rule"] == dl.RULE
    assert rows[0]["entity_id"] == "cedarloop"
    assert rows[0]["quote"].startswith("The extraction worker of Cedarloop keeps timing out")


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
    assert [c["id"] for c in line.held_claims] == [bench.claim_id(CASES["r1-of"], 0)]
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


def test_the_page_order_is_the_pages_read_most_first(tmp_path):
    def group(line, page):
        return dl.Group(line, "ep_x", [], [page])

    groups = [group("a", "low"), group("b", "high"), group("c", "unread")]
    assert [g.line for g in dl.order(groups, {"high": 5.0, "low": 1.0})] == ["b", "a", "c"]


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


# ---------------------------------------------------------------------------------------------------- the dry run


def test_the_dry_run_prints_ids_never_words_and_writes_nothing_to_the_bank(tmp_path, capsys):
    from benchmarks.consolidation import described_landing_bank as dry

    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    before = sorted(p.name for p in bank.rglob("*"))
    assert dry.main(["--bank", str(bank)]) == 0
    shown = capsys.readouterr().out
    assert bench.claim_id(CASES["r1-of"], 0) in shown and "candidates=1" in shown and "user" in shown
    assert "claims that reach the reader 1 in 1 group(s)" in shown and "only tools or concepts, no project: 0 claim(s)" in shown
    for word in ("extraction", "Cedarloop", "timing", "worker"):
        assert word not in shown
    assert sorted(p.name for p in bank.rglob("*")) == before


def test_the_dry_run_counts_what_names_only_tools_or_concepts_and_reads_none_of_it(tmp_path, capsys):
    from benchmarks.consolidation import described_landing_bank as dry

    bank = bench.build_bank(tmp_path, SPEC, CASES["w3-exercise-query-on-a-concept"])
    assert dry.main(["--bank", str(bank)]) == 0
    shown = capsys.readouterr().out
    assert "claims that reach the reader 0 in 0 group(s)" in shown
    assert "only tools or concepts, no project: 1 claim(s)" in shown and "named_pages_not_projects 1" in shown


def test_the_dry_run_reads_resumes_and_writes_the_words_only_to_the_eyes_file(tmp_path, capsys, monkeypatch):
    from benchmarks.consolidation import described_landing_bank as dry

    case = CASES["m2-two-pages-two-claims"]
    bank = bench.build_bank(tmp_path / "b", SPEC, case)
    before = {p: p.read_bytes() for p in bank.rglob("*") if p.is_file()}
    calls: list[str] = []
    ask = scripted({1: {"page": "Tidewell", "scope": "whole", "sentence": "The Tidewell login screen takes four seconds to load."},
                    2: {"page": "Pebblegrid", "scope": "whole", "sentence": "Meanwhile the Pebblegrid billing job fails every Sunday."}},
                   calls=calls)
    monkeypatch.setattr(dry, "make_ask", lambda *_a, **_k: (ask, None))
    eyes = tmp_path / "out" / "eyes.jsonl"
    assert dry.main(["--bank", str(bank), "--eyes", str(eyes), "--read", "--max-reads", "0"]) == 0
    out = capsys.readouterr().out
    assert "still unread 1" in out and not calls, "--max-reads 0 reads nothing and says what is left"
    assert dry.main(["--bank", str(bank), "--eyes", str(eyes), "--read"]) == 0
    out = capsys.readouterr().out
    assert len(calls) == 2 and "model calls made: 2 this run" in out
    would = [l for l in out.splitlines() if l.startswith("would_land")]
    assert len(would) == 2 and all("rule=land_described" in l for l in would)
    for word in ("Tidewell", "Pebblegrid", "login", "billing", "Sunday"):
        assert word not in "\n".join(would)
    rows = [json.loads(l) for l in eyes.read_text().splitlines()]
    assert {r["page"] for r in rows if r["would_land"]} == {"tidewell", "pebblegrid"}
    assert any("four seconds" in r["copied_sentence"] and r["claim_text"] and r["label"] == "status notes" for r in rows)
    # the run is continued from what was kept: nothing is read twice
    assert dry.main(["--bank", str(bank), "--eyes", str(eyes), "--read"]) == 0
    assert len(calls) == 2 and "kept from earlier runs 1" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in bank.rglob("*") if p.is_file()} == before, "nothing was written to the bank"


def test_the_dry_run_refuses_a_file_inside_the_repository(tmp_path, capsys):
    from benchmarks.consolidation import described_landing_bank as dry

    bank = bench.build_bank(tmp_path, SPEC, CASES["r1-of"])
    with pytest.raises(SystemExit):
        dry.main(["--bank", str(bank), "--eyes", str(Path(dry.REPO) / "eyes.jsonl")])
