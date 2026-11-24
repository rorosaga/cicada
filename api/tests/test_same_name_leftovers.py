"""What a same-name split leaves on the old page (2026-11-24): the unsourced prose (Summary, History, tags) that still states
the person who left, found by the main model, kept only when located, moved in the split's own commit. Names invented."""
from __future__ import annotations

import asyncio

import pytest

from api.services import markdown_parser, page_join, same_name_doubts, same_name_leftovers as leftovers, same_name_tend
from api.tests.test_same_name_tend import COUSIN, WORK, DAY, _ans, _git, _joined, _judge, _run, bank  # noqa: F401

LEAVES = "a student in Glasgow who plays football on Saturdays"
SPLIT = _ans(["AB", "CD"], [(1, 2, "different", "lives in Glasgow and studies law", "works as a logistics planner")])
LEAD = "Tomas works in the Lyon office as a logistics planner. Tomas is a student in Glasgow who plays football on Saturdays."
HISTORY = "- 2026-10-25: Tomas plays football on Saturdays in Glasgow.\n- 2026-10-04: Tomas started at the Lyon office."


def _blend(memory, *, lead=LEAD, history=HISTORY, tags=("cousin", "logistics")):
    """The joined page as Sleep's writer leaves it: a Summary written from both people, History bullets and tags with no
    per-sentence source."""
    _joined(memory)
    path = memory / "entities" / "tomas.md"
    parsed = markdown_parser.parse(path)
    body = parsed.body.replace("Tomas is a colleague and a cousin.", lead)
    body = body.replace("\n```claims", f"\n## History\n{history}\n\n```claims", 1) if "```claims" in body else body + f"\n## History\n{history}\n"
    fm = dict(parsed.frontmatter)
    fm["tags"] = list(tags)
    markdown_parser.write(path, fm, body)
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "blended page")


def _plan(memory, answer, leaving=frozenset({"ep_b1", "ep_b2"})):
    judge = _judge(answer)
    return _run(leftovers.plan(memory, "tomas", leaving, judge)), judge


def _row(n, about, text="", proof=LEAVES):
    return {"n": n, "about": about, "leave_text": text, "from": proof}


def test_the_unsourced_lines_that_state_the_leaving_person_are_found_when_the_judge_points_at_the_record(bank):
    _blend(bank)
    cuts, judge = _plan(bank, {"lines": [_row(1, "stays", proof=""), _row(2, "leaves"), _row(3, "leaves"),
                                         _row(5, "leaves", proof="Tomas lives in Glasgow and studies law")]})
    assert [(c.section, c.text) for c in cuts] == [
        ("Summary", "Tomas is a student in Glasgow who plays football on Saturdays."),
        ("History", "2026-10-25: Tomas plays football on Saturdays in Glasgow."),
        ("tags", "cousin")]
    prompt = judge.calls[0]
    assert "[Summary] Tomas works in the Lyon office" in prompt and "3. [History]" in prompt and "5. [tags] cousin" in prompt
    assert WORK in prompt and COUSIN in prompt


@pytest.mark.parametrize("row", [
    _row(2, "leaves", proof="a student in Mars"),                              # copied from nowhere
    _row(2, "leaves", proof="Tomas sent the shipping calendar"),               # the staying person's words
    _row(2, "leaves", proof="Tomas is"),                                       # only the name
    _row(2, "mixed", "Tomas is a student in Glasgow who plays", LEAVES),       # not a clause: the line would be torn
    _row(2, "mixed", "words that are not on the line"),
    _row(2, "stays"),
    {"n": "x"}, "nonsense"])
def test_a_line_is_moved_only_on_words_the_record_has(bank, row):
    _blend(bank)
    cuts, _ = _plan(bank, {"lines": [row]})
    assert cuts == []


def test_a_fact_the_staying_conversations_say_too_is_never_moved(bank):
    _blend(bank, lead="Tomas is a person. Tomas lives in Glasgow and studies law.")
    # only the leaving side says it: moved
    cuts, _ = _plan(bank, {"lines": [_row(2, "leaves", proof="Tomas lives in Glasgow and studies law")]})
    assert [c.text for c in cuts] == ["Tomas lives in Glasgow and studies law."]
    # the staying side's own words are no proof of the leaving person
    cuts, _ = _plan(bank, {"lines": [_row(2, "leaves", proof="Tomas sent the shipping calendar")]})
    assert cuts == []


def test_a_mixed_sentence_gives_up_only_its_own_clause(bank):
    _blend(bank, lead="Tomas works in the Lyon office as a logistics planner; he is a student in Glasgow who plays football on Saturdays.")
    cuts, _ = _plan(bank, {"lines": [_row(1, "mixed", "he is a student in Glasgow who plays football on Saturdays.")]})
    assert [c.text for c in cuts] == ["he is a student in Glasgow who plays football on Saturdays."]


def test_a_line_a_page_edit_wrote_is_never_offered(bank):
    _blend(bank)
    path = bank / "entities" / "tomas.md"
    parsed = markdown_parser.parse(path)
    body = parsed.body.replace("2026-10-25: Tomas plays football", "2026-10-25: Tomas plays five-a-side football")
    markdown_parser.write(path, parsed.frontmatter, body)
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "Page edit")
    cuts, judge = _plan(bank, {"lines": [_row(3, "leaves")]})
    assert "five-a-side" not in judge.calls[0] and all("five-a-side" not in c.text for c in cuts)


def test_a_judge_that_fails_or_cannot_be_read_cuts_nothing(bank):
    _blend(bank)
    assert _plan(bank, {"lines": "no"})[0] == [] and _plan(bank, RuntimeError("down"))[0] == []
    assert _plan(bank, {"lines": [_row(2, "leaves")]}, leaving=frozenset())[0] == [], "nobody leaves: nothing is read"


def test_the_split_moves_the_cuts_in_its_own_commit_and_the_undo_takes_them_back_byte_for_byte(bank):
    _blend(bank)
    same_name_doubts.flag(bank, pages=["tomas"])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "flag")
    before = {p.name: p.read_bytes() for p in (bank / "entities").glob("*.md")}
    lines = {"lines": [_row(2, "leaves"), _row(3, "leaves"), _row(5, "leaves", proof="Tomas lives in Glasgow and studies law")]}

    async def judge(system, prompt):
        return lines if "STAYS" in prompt else SPLIT

    report = _run(same_name_tend.tend(bank, judge, today=DAY))
    assert report.split == 1
    old = (bank / "entities" / "tomas.md").read_text()
    new = (bank / "entities" / "tomas-2.md").read_text()
    assert "football" not in old and "cousin" not in markdown_parser.parse(bank / "entities" / "tomas.md").frontmatter["tags"]
    assert "Tomas works in the Lyon office as a logistics planner." in old and "2026-10-04: Tomas started at the Lyon office." in old
    assert "Tomas is a student in Glasgow who plays football on Saturdays." in new and "2026-10-25: Tomas plays football" in new
    assert "cousin" in markdown_parser.parse(bank / "entities" / "tomas-2.md").frontmatter["tags"]
    assert _git(bank, "status", "--porcelain").strip() == ""
    sha = _git(bank, "log", "-1", "--format=%H", "HEAD~1").strip()
    assert _git(bank, "log", "-1", "--format=%s", "HEAD~1").startswith(page_join.SUBJECT_SPLIT)
    page_join.undo(bank, sha)
    after = {p.name: p.read_bytes() for p in (bank / "entities").glob("*.md")}
    assert after == before, "the undo of the split puts both pages, summary and tags included, back byte for byte"


def test_a_split_with_nothing_for_the_judge_to_move_is_the_split_as_before(bank):
    _joined(bank)
    same_name_doubts.flag(bank, pages=["tomas"])
    judge = _judge(SPLIT)   # answers the split; the leftovers question gets the same JSON and no lines
    report = _run(same_name_tend.tend(bank, judge, today=DAY))
    assert report.split == 1
    assert "Tomas is a colleague and a cousin." in (bank / "entities" / "tomas.md").read_text()


def test_a_short_sourced_line_of_the_leaving_person_moves_too(bank):
    """The sentence numbering skips anything under 25 characters, so a short Key Fact the leaving conversation alone
    supports would have stayed behind as the other person's fact."""
    from api.services import same_name_split

    assert same_name_split.MIN_CHARS == 25
    facts = {"ep_a1": [f"Tomas is {WORK}"], "ep_a2": ["Tomas sent the shipping calendar"],
             "ep_b1": ["Tomas is retired"], "ep_b2": ["Tomas lives in Glasgow and studies law"]}
    from api.tests.test_same_name_tend import _page

    _page(bank, "tomas", facts, lead="Tomas is a colleague and a cousin.")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "short fact")
    assert same_name_tend.short_leaving(bank, "tomas", frozenset({"ep_b1", "ep_b2"})) == [("Key Facts", "Tomas is retired.")]
    same_name_doubts.flag(bank, pages=["tomas"])
    report = _run(same_name_tend.tend(bank, _judge(_ans(["AB", "CD"], [(1, 2, "different", "Tomas lives in Glasgow and studies law",
                                                                             "works as a logistics planner")])), today=DAY))
    assert report.split == 1
    assert "retired" not in (bank / "entities" / "tomas.md").read_text()
    assert "Tomas is retired" in (bank / "entities" / "tomas-2.md").read_text()


def test_the_pages_only_the_leaving_person_links_go_with_them(bank):
    from api.services.claims import Claim, parse_claims, write_claims

    _blend(bank)
    path = bank / "entities" / "tomas.md"
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["related"] = ["lyon-office", "glasgow-fc", "mira"]
    body = parsed.body.replace("2026-10-25: Tomas plays football on Saturdays in Glasgow.",
                               "2026-10-25: Tomas plays football on Saturdays for [[Glasgow FC]].")
    body = body.replace("Tomas works in the Lyon office", "Tomas works at the [[Lyon office]] with [[Mira]]")
    body = body.replace("Tomas is a student in Glasgow", "Tomas is a student in Glasgow and knows [[Mira]]")
    markdown_parser.write(path, fm, body)
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "links")
    same_name_doubts.flag(bank, pages=["tomas"])
    lines = {"lines": [_row(2, "leaves"), _row(3, "leaves")]}

    async def judge(system, prompt):
        return lines if "STAYS" in prompt else SPLIT

    assert _run(same_name_tend.tend(bank, judge, today=DAY)).split == 1
    assert markdown_parser.parse(bank / "entities" / "tomas.md").frontmatter["related"] == ["lyon-office", "mira"]
    assert markdown_parser.parse(bank / "entities" / "tomas-2.md").frontmatter["related"] == ["glasgow-fc"]


def test_the_new_page_reads_in_the_writers_order_with_its_lists_as_bullets(bank):
    _blend(bank)
    same_name_doubts.flag(bank, pages=["tomas"])
    lines = {"lines": [_row(2, "leaves"), _row(3, "leaves")]}

    async def judge(system, prompt):
        return lines if "STAYS" in prompt else SPLIT

    _run(same_name_tend.tend(bank, judge, today=DAY))
    new = markdown_parser.parse(bank / "entities" / "tomas-2.md").body
    assert new.index("## Summary") < new.index("## Key Facts") < new.index("## History")
    assert "## Summary\nTomas is a student in Glasgow who plays football on Saturdays." in new
    assert "\n- 2026-10-25: Tomas plays football on Saturdays in Glasgow." in new


# ------------------------------------------------------------------ review of 2026-11-24: three defects, tests first


def test_a_line_moves_only_when_its_own_words_are_tied_to_the_leaving_conversations(bank):
    """A wrong or off-by-one number must never move the staying person's sentence or tag: the judge's proof is about the
    leaving person, but lines 1 (the staying person's summary sentence) and 6 (the staying person's tag) state nothing of it."""
    _blend(bank)
    cuts, judge = _plan(bank, {"lines": [_row(1, "leaves"), _row(6, "leaves")]})
    assert "1. [Summary] Tomas works in the Lyon office" in judge.calls[0] and "6. [tags] logistics" in judge.calls[0]
    assert cuts == [], [(c.section, c.text) for c in cuts]
    # the right numbers, same proof: the leaving person's own sentence and tag do move
    cuts, _ = _plan(bank, {"lines": [_row(2, "leaves"), _row(5, "leaves")]})
    assert [(c.section, c.text) for c in cuts] == [
        ("Summary", "Tomas is a student in Glasgow who plays football on Saturdays."), ("tags", "cousin")]


def test_a_line_that_paraphrases_the_record_stays_where_it_is(bank):
    """The tie is words the record has, word for word: a paraphrase shares no located stretch, so it is left (the safe side)."""
    _blend(bank, lead="Tomas works in the Lyon office as a logistics planner. Tomas does a degree up north and kicks a ball at weekends.")
    cuts, _ = _plan(bank, {"lines": [_row(2, "leaves")]})
    assert cuts == []


def test_a_cut_is_applied_where_it_was_validated_not_at_the_first_matching_text():
    prose = ("## Summary\nTomas hates being retired. Tomas, retired, plays football on Saturdays in Glasgow. "
             "Tomas works in Lyon.\n\n## Key Facts\n- Tomas is retired and plays chess.\n")
    second = "Tomas, retired, plays football on Saturdays in Glasgow."
    kept, moved = page_join._apply_cuts(prose, [("Summary", "retired", second, second.find("retired"))])
    assert "Tomas hates being retired." in kept, "the first sentence is not the one the judge saw"
    assert "Tomas, plays football on Saturdays in Glasgow." in kept and moved == [("Summary", "retired")]
    assert "Tomas is retired and plays chess." in kept, "another section is never touched"


def test_a_cut_that_cannot_be_placed_exactly_once_is_not_applied():
    sentence = "Tomas plays football on Saturdays in Glasgow."
    prose = f"## Summary\n{sentence} {sentence}\n\n## History\n- {sentence}\n"
    kept, moved = page_join._apply_cuts(prose, [("Summary", sentence, sentence, 0)])
    assert moved == [] and kept == prose.strip(), "the same sentence twice in the section: which one the judge saw is unknowable"
    # two lines of one section holding the sentence
    prose = f"## Key Facts\n- {sentence}\n- {sentence}\n"
    assert page_join._apply_cuts(prose, [("Key Facts", sentence, sentence, 0)]) == (prose.strip(), [])
    # the line changed since it was read: the offset no longer lands on the text
    prose = "## Summary\nTomas, a retiree, plays football on Saturdays in Glasgow.\n"
    assert page_join._apply_cuts(prose, [("Summary", "retired", "Tomas, retired, plays football on Saturdays in Glasgow.", 7)]) == (prose.strip(), [])


def test_a_short_sourced_cut_matches_a_whole_line_exactly_once():
    prose = "## Summary\nTomas is retired. He lives in Lyon.\n\n## Key Facts\n- Tomas is retired.\n"
    kept, moved = page_join._apply_cuts(prose, [("Key Facts", "Tomas is retired.")])
    assert moved == [("Key Facts", "Tomas is retired.")] and "Tomas is retired. He lives in Lyon." in kept
    twice = "## Key Facts\n- Tomas is retired.\n- Tomas is retired.\n"
    assert page_join._apply_cuts(twice, [("Key Facts", "Tomas is retired.")]) == (twice.strip(), [])


def test_the_split_revalidates_its_cuts_against_the_page_as_it_is_then(bank):
    """Between the plan and the lock a person's edit made the sentence theirs: the cut is not applied."""
    _blend(bank)
    cuts, _ = _plan(bank, {"lines": [_row(2, "leaves")]})
    assert [c.text for c in cuts] == ["Tomas is a student in Glasgow who plays football on Saturdays."]
    path = bank / "entities" / "tomas.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body.replace("who plays football on Saturdays.", "who plays football on Saturdays and Sundays.", 1))
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "Page edit")
    out = same_name_tend.split_page(bank, "tomas", frozenset({"ep_b1", "ep_b2"}), snr_split(), cuts=cuts)
    assert out is not None
    assert "Tomas is a student in Glasgow who plays football on Saturdays and Sundays." in path.read_text(), "the person's own words stay"


def snr_split():
    from api.services import same_name_review as snr

    return snr.Split("tomas", frozenset({"ep_b1", "ep_b2"}), "lives in Glasgow", "works as a logistics planner", True)


@pytest.mark.parametrize("line,text,ok", [
    ("Tomas is a semi-retired student in Glasgow.", "retired student in Glasgow.", False),       # a hyphen inside a word
    ("Tomas is a semi-retired student in Glasgow.", "Tomas is a semi", False),
    ("Tomas works in Lyon - he is a student in Glasgow.", "he is a student in Glasgow.", True),    # a spaced dash is an edge
    ("Tomas works in Lyon, he is a student in Glasgow.", "he is a student in Glasgow.", True),
    ("Tomas studies at [Glasgow Uni, Law School](https://example.com/law) and plays football.", "Law School](https://example.com/law) and plays football.", False),
    ("Tomas studies at [Glasgow Uni, Law School](https://example.com/law) and plays football.", "Tomas studies at [Glasgow Uni", False),
    ("Tomas knows [[Glasgow, FC]] well, he plays football.", "FC]] well, he plays football.", False),
    ("Tomas knows Mira (a friend, in Glasgow), he plays football.", "in Glasgow), he plays football.", False),
    ("Tomas knows Mira (a friend, in Glasgow), he plays football.", "he plays football.", True),
    ("Tomas earns 1,000 a month, he plays football.", "000 a month, he plays football.", False),   # a comma inside a number
])
def test_a_dash_inside_a_word_a_comma_inside_a_link_and_a_number_are_no_clause_edge(line, text, ok):
    at = line.find(text)
    assert page_join.cut_edges_clean(line, at, at + len(text)) is ok


def test_a_hyphen_inside_a_word_never_makes_a_cut_through_plan(bank):
    _blend(bank, lead="Tomas works in the Lyon office as a logistics planner. Tomas is a semi-retired student in Glasgow who plays football on Saturdays.")
    cuts, _ = _plan(bank, {"lines": [_row(2, "mixed", "retired student in Glasgow who plays football on Saturdays.")]})
    assert cuts == []


def test_a_cut_inside_a_link_is_not_applied_and_the_sentence_stays_whole():
    sentence = "Tomas studies at [Glasgow Uni, Law School](https://example.com/law) and plays football."
    prose = f"## Summary\n{sentence}\n"
    at = sentence.find(", Law School") + 2
    kept, moved = page_join._apply_cuts(prose, [("Summary", sentence[at:], sentence, at)])
    assert moved == [] and kept == prose.strip()


def test_a_cut_mends_what_is_left_with_no_dangling_punctuation_and_no_hyphen_eaten():
    sentence = "Tomas works in Lyon, a semi-retired planner, and is a student in Glasgow."
    prose = f"## Summary\n{sentence}\n"
    text = "and is a student in Glasgow."
    kept, moved = page_join._apply_cuts(prose, [("Summary", text, sentence, sentence.find(text))])
    assert moved == [("Summary", text)] and kept == "## Summary\nTomas works in Lyon, a semi-retired planner."


def test_a_clause_cut_inside_a_history_bullet_is_never_made(bank):
    """History is never rewritten by a split: a bullet moves whole or stays."""
    bullet = "2026-10-04: Tomas started at the Lyon office; Tomas plays football on Saturdays in Glasgow."
    prose = f"## History\n- {bullet}\n"
    text = "Tomas plays football on Saturdays in Glasgow."
    assert page_join._apply_cuts(prose, [("History", text, bullet, bullet.find(text))]) == (prose.strip(), [])
    kept, moved = page_join._apply_cuts(prose, [("History", bullet, bullet, 0)])
    assert moved == [("History", bullet)] and "History" not in kept


# ------------------------------------------------------------------ the mixed path


def test_a_mixed_sentence_gives_up_one_clause_and_keeps_the_rest_of_the_line(bank):
    _blend(bank, lead="Tomas works in the Lyon office as a logistics planner; he is a student in Glasgow who plays football on Saturdays.")
    same_name_doubts.flag(bank, pages=["tomas"])
    before = {p.name: p.read_bytes() for p in (bank / "entities").glob("*.md")}
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "flag")
    clause = "he is a student in Glasgow who plays football on Saturdays."

    async def judge(system, prompt):
        return {"lines": [_row(1, "mixed", clause)]} if "STAYS" in prompt else SPLIT

    assert _run(same_name_tend.tend(bank, judge, today=DAY)).split == 1
    old = (bank / "entities" / "tomas.md").read_text()
    assert "Tomas works in the Lyon office as a logistics planner." in old and "he is a student" not in old and "; " not in old.split("## Summary")[1].split("\n\n")[0]
    assert "## Summary\nHe is a student in Glasgow who plays football on Saturdays." in markdown_parser.parse(bank / "entities" / "tomas-2.md").body or \
        clause in (bank / "entities" / "tomas-2.md").read_text()
    sha = _git(bank, "log", "-1", "--format=%H", "HEAD~1").strip()
    page_join.undo(bank, sha)
    assert {p.name: p.read_bytes() for p in (bank / "entities").glob("*.md")} == before


def test_a_pinned_line_and_a_hand_written_summary_are_never_cut(bank):
    _blend(bank)
    path = bank / "entities" / "tomas.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body.replace("Tomas is a student in Glasgow who plays", "Tomas is a student in Glasgow, he plays"))
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "Page edit")
    cuts, judge = _plan(bank, {"lines": [_row(1, "leaves"), _row(2, "leaves"), _row(3, "leaves")]})
    assert "student in Glasgow, he plays" not in judge.calls[0], "a hand-written Summary is not offered at all"
    assert all(c.section != "Summary" for c in cuts)


def test_a_proof_for_another_fact_of_the_line_still_moves_it_and_a_shared_name_never_blocks_it(bank):
    """Found on the measure: the judge copies the proof of ONE fact of a line that states several, and the staying person's
    conversations name the same other people. The line's own words are what is tied, and a name both carry is no conflict."""
    from api.tests.test_same_name_tend import _page

    facts = {"ep_a1": ["Tomas asked Mira Kolar for the facade options by Friday"], "ep_a2": ["Tomas approved the timber facade"],
             "ep_b1": ["Tomas makes quince jam every autumn from her sister's tree"], "ep_b2": ["Tomas lives downstairs from Mira Kolar"]}
    _page(bank, "tomas", facts, lead="Tomas is Mira Kolar's retired downstairs neighbour who makes quince jam every autumn. "
                                      "Tomas asked Mira Kolar for the facade options by Friday.")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "facts")
    cuts, _ = _plan(bank, {"lines": [_row(1, "leaves", proof="Tomas lives downstairs from Mira Kolar"),
                                     _row(2, "leaves", proof="Tomas lives downstairs from Mira Kolar")]})
    assert [c.text for c in cuts] == ["Tomas is Mira Kolar's retired downstairs neighbour who makes quince jam every autumn."]


def test_a_related_bullet_is_tied_by_a_page_only_the_leaving_conversations_name(bank):
    from api.tests.test_same_name_tend import _page

    facts = {"ep_a1": ["Tomas asked Mira Kolar for the facade options by Friday"], "ep_a2": ["Tomas approved the timber facade"],
             "ep_b1": ["Tomas works at Grupo Aldana in Porto"], "ep_b2": ["Tomas lives downstairs from Mira Kolar"]}
    _page(bank, "tomas", facts, lead="Tomas works on a facade.")
    path = bank / "entities" / "tomas.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body.replace("\n```claims", "\n## Related\n- [[Grupo Aldana]] — works at\n- [[Mira Kolar]] — asked for the facade\n\n```claims", 1))
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "related")
    cuts, judge = _plan(bank, {"lines": [_row(2, "leaves", proof="Tomas works at Grupo Aldana in Porto"),
                                         _row(3, "leaves", proof="Tomas works at Grupo Aldana in Porto")]})
    assert "[Related] [[Grupo Aldana]]" in judge.calls[0]
    assert [c.text for c in cuts] == ["[[Grupo Aldana]] — works at"], "a name both carry ties nothing"
