"""Two people who share a first name, looked at again after the batch (2026-11-23): `same_name_review` (the pure half),
`same_name_doubts` (the store) and `same_name_tend` (the disk half), with a fake judge on a scratch bank. Names invented."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date
from pathlib import Path

import pytest

from api.services import (bank_index, inbox_service, markdown_parser, merge_rejections, page_join, page_redirects,
                          same_name_doubts, same_name_people as snp, same_name_review as snr, same_name_tend)
from api.services import section_provenance
from api.services.claims import Claim, Evidence, parse_claims, strip_claims_block, write_claims

WORK = "a colleague in the Lyon office where he lives and works as a logistics planner"
COUSIN = "the speaker's cousin, a student in Glasgow who plays football on Saturdays"
NEIGHBOUR = "a neighbour on the second floor who borrows tools and has a small brown dog"
CELLIST = "the speaker's cousin who plays the cello and visits every Christmas"
DAY = date(2026, 11, 23)


def _run(coro):
    return asyncio.run(coro)


def _judge(*answers):
    calls = []
    queue = list(answers)

    async def judge(system, prompt):
        calls.append(prompt)
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    judge.calls = calls
    return judge


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _episode(memory: Path, eid: str, day: str) -> None:
    markdown_parser.write(memory / "episodes" / f"{eid}.md", {"timestamp": f"{day}T10:00:00+00:00", "source": "claude-code"},
                          "## Conversation\nuser: hello\n")


def _page(memory: Path, pid: str, facts: dict[str, list[str]], *, name="Tomas", lead="Tomas is a person.") -> None:
    """A person page whose beliefs and Key Facts each say which conversation they came from."""
    episodes = list(facts)
    claims = [Claim(id=f"clm_{pid}_{n}_{k}".replace("-", "_"), text=text, subject=pid, predicate="note", object=text,
                    object_kind="literal", source_episodes=[ep])
              for n, ep in enumerate(episodes) for k, text in enumerate(facts[ep])]
    key_facts = [f"{text}." for ep in episodes for text in facts[ep]]
    prose = f"## Summary\n{lead}\n\n## Key Facts\n" + "\n".join(f"- {t}" for t in key_facts) + "\n"
    fm = {"name": name, "type": "person", "status": "active", "confidence": 0.8, "source_episodes": episodes}
    body = write_claims(prose, claims)
    scanned = section_provenance.scan(strip_claims_block(body))
    texts = {f"{t}.": ep for ep in episodes for t in facts[ep]}
    records = {}
    for item in scanned.get("key_facts", []):
        ep = texts.get(item.text)
        if ep:
            records.setdefault("key_facts", {})[item.key] = (item.text_hash, [Evidence(episode=ep, hash="0" * 12, kind="reasoning")])
    fm["section_provenance"] = section_provenance.encode(records)
    markdown_parser.write(memory / "entities" / f"{pid}.md", fm, body)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "bank"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    for eid, day in (("ep_a1", "2026-10-04"), ("ep_a2", "2026-10-18"), ("ep_b1", "2026-10-25"), ("ep_b2", "2026-11-08")):
        _episode(memory, eid, day)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "t@example.com")
    _git(memory, "config", "user.name", "T")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "seed")
    bank_index.invalidate()
    page_redirects.invalidate()
    return memory


def _joined(memory: Path) -> None:
    """One page that holds two people: two conversations about a colleague in Lyon, two about a cousin in Glasgow."""
    _page(memory, "tomas", {"ep_a1": [f"Tomas is {WORK}"], "ep_a2": ["Tomas sent the shipping calendar"],
                            "ep_b1": [f"Tomas is {COUSIN}"], "ep_b2": ["Tomas lives in Glasgow and studies law"]},
          lead="Tomas is a colleague and a cousin.")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "joined page")
    bank_index.invalidate()


def _ans(groups, pairs):
    return {"people": [{"conversations": list(g), "reason": "r"} for g in groups],
            "pairs": [{"people": [a, b], "verdict": v, "here": h, "there": t, "reason": "r"} for a, b, v, h, t in pairs]}


# ------------------------------------------------------------------ the pure review


def _page_of(ref, *texts):
    return snr.Page(ref, tuple(snp.Item(t, (f"{ref}{n}",)) for n, t in enumerate(texts)))


def test_a_page_that_holds_two_people_names_the_conversations_that_leave():
    page = _page_of("tomas", f"(2026-10-04) {WORK}", "(2026-10-18) sent the shipping calendar",
                    f"(2026-10-25) {COUSIN}", "(2026-11-08) lives in Glasgow and studies law")
    # letters are newest first: A = the last, B = the cousin one, C = the calendar, D = the Lyon one
    answer = _ans(["AB", "CD"], [(1, 2, "different", "lives in Glasgow and studies law", "works as a logistics planner")])
    split = _run(snr.holds_two("Tomas", page, _judge(answer)))
    assert split.episodes == frozenset({"tomas0", "tomas1"}) or split.episodes == frozenset({"tomas2", "tomas3"})
    assert split.here and split.there and split.called


def test_a_doubt_inside_a_page_is_never_a_split():
    page = _page_of("tomas", f"(2026-10-04) {WORK}", f"(2026-10-25) {COUSIN}")
    answer = _ans(["A", "B"], [(1, 2, "cannot_tell", "a student in Glasgow", "a logistics planner")])
    assert _run(snr.holds_two("Tomas", page, _judge(answer))).episodes == frozenset()


def test_a_page_with_one_conversation_is_not_read_at_all():
    judge = _judge(_ans(["A"], []))
    assert not _run(snr.holds_two("Tomas", _page_of("tomas", "x"), judge)).called and judge.calls == []


@pytest.mark.parametrize("answer,verdict,answered", [
    ({"verdict": "same", "here": "plays the cello", "there": "plays the cello"}, "same", True),
    ({"verdict": "different", "here": "the speaker's cousin", "there": "has a small brown dog"}, "apart", True),
    ({"verdict": "cannot_tell", "here": "", "there": ""}, "doubt", True),
    ({"verdict": "cannot tell"}, "doubt", True),
    # a "contrast" both sides state, the same words twice, or only the name, sets nothing against anything
    ({"verdict": "different", "here": "plays the cello", "there": "has a small brown dog"}, "doubt", False),
    ({"verdict": "different", "here": "has a small brown dog", "there": "has a small brown dog"}, "doubt", False),
    ({"verdict": "different", "here": "Marc is the", "there": "has a small brown dog"}, "doubt", False),
    ({"verdict": "same", "here": "Marc", "there": "Marc"}, "doubt", False),
    ({"verdict": "same", "here": "a fact nobody wrote", "there": "plays the cello"}, "doubt", False),
    ({"verdict": "same"}, "doubt", False), ({"verdict": "maybe"}, "doubt", False), ("text", "doubt", False),
    (None, "doubt", False),
], ids=["same on a located link", "different on a located contrast", "cannot tell", "cannot tell, spaced",
        "a contrast both sides state", "the same words twice", "only the name", "a link that is only the name",
        "unlocated link", "no facts", "unknown verdict", "text", "none"])
def test_a_pair_is_settled_only_on_facts_copied_from_the_descriptions(answer, verdict, answered):
    one = _page_of("marc", f"(2026-09-06) Marc is {CELLIST}")
    two = _page_of("marc-2", f"(2026-10-20) Marc is {NEIGHBOUR} and plays the cello at the weekends")
    found = _run(snr.settle_pair("Marc", one, two, _judge(answer)))
    assert (found.verdict, found.answered) == (verdict, answered)


def test_two_quotes_set_two_groups_apart_only_when_each_is_its_own_groups(tmp_path):
    """`same_name_people.read`: a page read conversation by conversation lists a belief two conversations share under
    both, so a quote found on both sides is routine and is no contrast; nor are the same words twice, or the name."""
    entries = [snp.Entry("A", "(2026-10-04) Tomas works at the Lyon logistics office and likes chess", None, ("e1",)),
               snp.Entry("B", "(2026-10-25) Tomas works at the Lyon logistics office and studies law in Glasgow", None, ("e2",))]

    def relation(here, there, verdict="different"):
        reading = snp.read(_ans(["A", "B"], [(1, 2, verdict, here, there)]), entries, "Tomas")
        return reading.relation

    assert relation("likes chess", "studies law in Glasgow") == {(0, 1): ("apart", "likes chess", "studies law in Glasgow")}
    assert relation("studies law in Glasgow", "likes chess"), "either way round"
    for here, there in (("works at the Lyon logistics office", "works at the Lyon logistics office"),
                        ("works at the Lyon logistics office", "studies law in Glasgow"),
                        ("likes chess", "likes chess"), ("Tomas", "studies law in Glasgow")):
        assert relation(here, there) == {}, (here, there)
        assert relation(here, there, "cannot_tell") == {}, "a doubt needs its two located facts as much as a contrast"


def test_a_failed_pair_judge_leaves_the_doubt_where_it_was():
    one, two = _page_of("a", "x y z"), _page_of("b", "u v w")
    found = _run(snr.settle_pair("Marc", one, two, _judge(RuntimeError("down"))))
    assert (found.verdict, found.answered) == ("doubt", False)


# ------------------------------------------------------------------ the doubts store


def test_the_store_keeps_pairs_flags_and_the_one_question(tmp_path):
    memory = tmp_path
    assert same_name_doubts.add_pairs(memory, [("marc-2", "marc")], today="2026-11-23")
    assert not same_name_doubts.add_pairs(memory, [("marc", "marc-2")]), "only what is new is written"
    assert same_name_doubts.pairs(memory) == {("marc", "marc-2"): {"since": "2026-11-23"}}
    assert same_name_doubts.doubts_of(memory, "marc") == {"marc-2"}
    same_name_doubts.flag(memory, pages=["marc"], pairs_=[("marc-2", "marc")])
    assert same_name_doubts.flagged(memory) == ({"marc"}, {("marc", "marc-2")})
    same_name_doubts.mark_asked(memory, "marc", "marc-2", today="2026-11-24")
    assert same_name_doubts.pairs(memory)[("marc", "marc-2")]["asked"] == "2026-11-24"
    same_name_doubts.clear_flags(memory, pages=["marc"], pairs_=[("marc", "marc-2")])
    assert same_name_doubts.flagged(memory) == (set(), set())
    assert same_name_doubts.remove_pairs(memory, [("marc", "marc-2")])
    assert not (memory / same_name_doubts.FILE).exists(), "an empty store is no file"


# ------------------------------------------------------------------ a page that holds two people, split by Sleep


def test_what_a_page_says_conversation_by_conversation(bank):
    _joined(bank)
    name, said, order = same_name_tend.page_conversations(bank, "tomas")
    assert name == "Tomas" and order == ["ep_a1", "ep_a2", "ep_b1", "ep_b2"]
    assert any("logistics planner" in t for t in said["ep_a1"]) and any("Glasgow" in t for t in said["ep_b2"])
    page = same_name_tend.page_of(bank, "tomas")
    assert [i.episodes for i in page.items] == [("ep_a1",), ("ep_a2",), ("ep_b1",), ("ep_b2",)]
    assert page.items[0].text.startswith("(2026-10-04) ")


def test_what_leaves_is_what_only_the_leaving_conversations_support(bank):
    _joined(bank)
    claims, numbers = same_name_tend.moving(bank, "tomas", frozenset({"ep_b1", "ep_b2"}))
    assert len(claims) == 2
    from api.services import same_name_split

    sentences = {s.n: s.text for s in same_name_split.sentences(markdown_parser.parse(bank / "entities" / "tomas.md").body)}
    assert {sentences[n] for n in numbers} == {f"Tomas is {COUSIN}.", "Tomas lives in Glasgow and studies law."}
    assert not any("Summary" in sentences[n] for n in numbers)


def test_a_located_contrast_splits_the_page_as_one_undoable_commit(bank):
    _joined(bank)
    same_name_doubts.flag(bank, pages=["tomas"])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "flag")
    # newest first: A = ep_b2, B = ep_b1, C = ep_a2, D = ep_a1
    answer = _ans(["AB", "CD"], [(1, 2, "different", "lives in Glasgow and studies law", "works as a logistics planner")])
    report = _run(same_name_tend.tend(bank, _judge(answer), today=DAY))
    assert (report.split, report.looked) == (1, 1)
    old = markdown_parser.parse(bank / "entities" / "tomas.md")
    new = markdown_parser.parse(bank / "entities" / "tomas-2.md")
    assert old.frontmatter["source_episodes"] == ["ep_a1", "ep_a2"] and new.frontmatter["source_episodes"] == ["ep_b1", "ep_b2"]
    assert all("Glasgow" not in c.text for c in parse_claims(old.body)) and len(parse_claims(new.body)) == 2
    assert "logistics planner" in old.body and "Glasgow" in new.body and "Glasgow" not in old.body
    assert merge_rejections.is_split(bank, "tomas", "tomas-2")
    assert same_name_doubts.flagged(bank) == (set(), set()), "the flag is taken"
    assert _git(bank, "status", "--porcelain").strip() == ""
    # two commits: the split alone (what an undo reverses), then what Sleep remembers about having made it
    assert _git(bank, "log", "-1", "--format=%s").startswith("Same-name review")
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == [same_name_doubts.FILE]
    log = _git(bank, "log", "-1", "--format=%s%n%b", "HEAD~1")
    assert log.startswith(page_join.SUBJECT_SPLIT) and "sleep/same-name" in log and "Cicada-Author: cicada" in log
    assert same_name_doubts.FILE not in _git(bank, "show", "--name-only", "--format=", "HEAD~1").split()
    # the person takes it back with one tap
    sha = _git(bank, "log", "-1", "--format=%H", "HEAD~1").strip()
    assert same_name_doubts.splits(bank) == {"tomas": sha}
    page_join.undo(bank, sha)
    assert not (bank / "entities" / "tomas-2.md").exists()
    assert len(parse_claims(markdown_parser.parse(bank / "entities" / "tomas.md").body)) == 4
    # ... and their undo stands: the page is flagged again by a later batch, and Sleep never splits it again
    assert same_name_doubts.flagged(bank) == (set(), set()), "the undo reverses the split, not what Sleep remembers"
    same_name_doubts.flag(bank, pages=["tomas"])
    judge = _judge(answer)
    again = _run(same_name_tend.tend(bank, judge, today=DAY))
    assert (again.split, again.looked) == (0, 0) and judge.calls == [] and again.skipped == {"split_taken_back": 1}
    assert not (bank / "entities" / "tomas-2.md").exists() and "tomas" in same_name_doubts.one(bank)
    assert _git(bank, "status", "--porcelain").strip() == "", "the store is committed even when nothing was read"


def test_a_page_the_person_joined_is_never_split_by_sleep(bank):
    """Two people pages the person merged (their own merge, or their yes to a question) are one person on their word:
    the merge marks the page, and a later located contrast inside it splits nothing."""
    _page(bank, "tomas", {"ep_a1": [f"Tomas is {WORK}"], "ep_a2": ["Tomas sent the shipping calendar"]})
    _page(bank, "tomas-2", {"ep_b1": [f"Tomas is {COUSIN}"], "ep_b2": ["Tomas lives in Glasgow and studies law"]})
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "two pages")
    bank_index.invalidate()
    out = page_join.merge(bank, "tomas-2", "tomas", author="user")
    assert same_name_doubts.FILE in out["paths"] and same_name_doubts.one(bank) == {"tomas"}
    assert _git(bank, "status", "--porcelain").strip() == "", "the mark is in the merge's own commit"
    same_name_doubts.flag(bank, pages=["tomas"])
    judge = _judge(_ans(["AB", "CD"], [(1, 2, "different", "lives in Glasgow and studies law", "works as a logistics planner")]))
    report = _run(same_name_tend.tend(bank, judge, today=DAY))
    assert report.split == 0 and judge.calls == [] and report.skipped == {"joined_by_the_person": 1}
    assert not (bank / "entities" / "tomas-2.md").exists()
    # taking the merge back takes the mark back with it
    page_join.undo(bank, out["commit"])
    assert same_name_doubts.one(bank) == set()


def test_a_merge_says_beforehand_that_it_writes_the_store(bank):
    """`entity_merge.merge_footprint` names every path a merge writes (the dedup sweep puts back anything outside it)."""
    from api.services import entity_merge

    _page(bank, "tomas", {"ep_a1": [f"Tomas is {WORK}"]})
    _page(bank, "tomas-2", {"ep_b1": [f"Tomas is {COUSIN}"]})
    bank_index.invalidate()
    before = entity_merge.merge_footprint(bank, "tomas-2", "tomas")
    assert same_name_doubts.FILE in before and not (bank / same_name_doubts.FILE).exists(), "said, not written"
    wrote = entity_merge.merge_entities(bank, "tomas-2", "tomas")["paths"]
    assert same_name_doubts.FILE in wrote and set(wrote) <= set(before) | {f"entities/tomas-2.md"}
    markdown_parser.write(bank / "entities" / "acme.md", {"name": "Acme", "type": "company"}, "## Summary\nA company.\n")
    markdown_parser.write(bank / "entities" / "acme-inc.md", {"name": "Acme Inc", "type": "company"}, "## Summary\nA company.\n")
    bank_index.invalidate()
    assert same_name_doubts.FILE not in entity_merge.merge_footprint(bank, "acme-inc", "acme"), "people only"
    # Sleep's own dedup join is not the person's word: it writes no mark, so Sleep may still split that page
    _page(bank, "tomas-3", {"ep_b2": ["Tomas lives in Glasgow and studies law"]})
    bank_index.invalidate()
    assert same_name_doubts.FILE not in entity_merge.merge_footprint(bank, "tomas-3", "tomas", by_sleep=True)
    (bank / same_name_doubts.FILE).unlink()
    assert same_name_doubts.FILE not in entity_merge.merge_entities(bank, "tomas-3", "tomas", by_sleep=True)["paths"]
    assert same_name_doubts.one(bank) == set()


def test_a_doubt_or_an_unlocated_contrast_moves_nothing(bank):
    _joined(bank)
    same_name_doubts.flag(bank, pages=["tomas"])
    for answer in (_ans(["AB", "CD"], [(1, 2, "cannot_tell", "lives in Glasgow and studies law", "works as a logistics planner")]),
                   _ans(["AB", "CD"], [(1, 2, "different", "lives in Paris", "works on a farm")]),
                   _ans(["ABCD"], [])):
        same_name_doubts.flag(bank, pages=["tomas"])
        report = _run(same_name_tend.tend(bank, _judge(answer), today=DAY))
        assert report.split == 0 and not (bank / "entities" / "tomas-2.md").exists()
    assert len(parse_claims(markdown_parser.parse(bank / "entities" / "tomas.md").body)) == 4


def test_an_engine_failure_keeps_the_flag_for_the_next_run(bank):
    from api.services import engine_errors

    _joined(bank)
    same_name_doubts.flag(bank, pages=["tomas"])
    with pytest.raises(engine_errors.EngineError):
        _run(same_name_tend.tend(bank, _judge(engine_errors.EngineError("limit")), today=DAY))
    assert same_name_doubts.flagged(bank)[0] == {"tomas"}


# ------------------------------------------------------------------ two people held in doubt


def _doubt_bank(bank: Path) -> None:
    _page(bank, "marc", {"ep_a1": [f"Marc is {CELLIST}"], "ep_a2": ["Marc sent a photo of a new cello"]}, name="Marc",
          lead="Marc is the speaker's cousin who plays the cello.")
    _page(bank, "marc-2", {"ep_b1": [f"Marc is {NEIGHBOUR}"], "ep_b2": ["Marc left a note about the lift"]}, name="Marc",
          lead="Marc is a neighbour on the second floor.")
    same_name_doubts.add_pairs(bank, [("marc", "marc-2")], today="2026-11-01")
    same_name_doubts.flag(bank, pairs_=[("marc", "marc-2")])
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "doubt")
    bank_index.invalidate()


def test_a_doubt_nothing_settles_is_asked_once_in_words_for_a_person(bank):
    _doubt_bank(bank)
    judge = _judge({"verdict": "cannot_tell"})
    report = _run(same_name_tend.tend(bank, judge, today=DAY))
    assert (report.asked, report.merged, report.apart) == (1, 0, 0)
    files = sorted((bank / "inbox").glob("inbox-*.md"))
    assert len(files) == 1
    item = markdown_parser.parse(files[0])
    fm = item.frontmatter
    assert fm["kind"] == "merge_suggestion" and fm["detected"] == "same_name_doubt" and fm["fold_page"] is True
    assert {fm["entity_id"], fm["merge_target_hint"]} == {"marc", "marc-2"}
    assert "cello" in fm["known_for"]["marc"] and "neighbour" in fm["known_for"]["marc-2"]
    assert same_name_doubts.pairs(bank)[("marc", "marc-2")]["asked"] == DAY.isoformat()
    # a second drain, the same doubt flagged again: never a second question
    same_name_doubts.flag(bank, pairs_=[("marc", "marc-2")])
    _run(same_name_tend.tend(bank, judge, today=DAY))
    assert len(list((bank / "inbox").glob("inbox-*.md"))) == 1


def test_the_question_is_worded_by_what_each_is_known_for_with_no_id(bank):
    from api.services import inbox_wording

    _doubt_bank(bank)
    _run(same_name_tend.tend(bank, _judge({"verdict": "cannot_tell"}), today=DAY))
    fm = markdown_parser.parse(next((bank / "inbox").glob("inbox-*.md"))).frontmatter
    said = inbox_wording.spoken(fm, DAY.isoformat(), same={"marc": "cousin", "marc-2": "neighbour"})
    assert said.question.startswith("Are Marc (") and "same person" in said.question
    assert "marc-2" not in said.question + said.reason and "cello" in said.reason and "neighbour" in said.reason
    plain = inbox_wording.spoken(fm, DAY.isoformat())
    assert "Marc" in plain.question and "marc-2" not in plain.question


def test_a_located_link_is_put_to_the_person_and_never_acted_on(bank):
    """Ruling 74: two people pages join on two kinds of evidence code can count. A model's reading of two quotes is not
    one, so the link is said in the one question and the person joins them with a tap."""
    from api.services import inbox_wording

    _doubt_bank(bank)
    answer = {"verdict": "same", "here": "plays the cello", "there": "plays the cello"}
    # the neighbour page also says the cello, so the link is a fact both sides state
    _page(bank, "marc-2", {"ep_b1": [f"Marc is {NEIGHBOUR}"], "ep_b2": ["Marc plays the cello on the second floor"]},
          name="Marc", lead="Marc is a neighbour on the second floor.")
    bank_index.invalidate()
    report = _run(same_name_tend.tend(bank, _judge(answer), today=DAY))
    assert (report.merged, report.asked) == (0, 1)
    assert (bank / "entities" / "marc-2.md").exists() and ("marc", "marc-2") in same_name_doubts.pairs(bank)
    fm = markdown_parser.parse(next((bank / "inbox").glob("inbox-*.md"))).frontmatter
    assert fm["link"] == ["plays the cello", "plays the cello"] and fm["fold_page"] is True
    said = inbox_wording.spoken(fm, DAY.isoformat(), same={"marc": "cousin", "marc-2": "neighbour"})
    assert "plays the cello" in said.reason and "your word" in said.reason


@pytest.mark.parametrize("answer", [{}, {"verdict": "same"}, {"verdict": "same", "here": "zzz yyy xxx", "there": "www vvv"},
                                    {"verdict": "different", "here": "nothing like it", "there": "nor this"},
                                    RuntimeError("down"), "not json"],
                         ids=["empty", "no facts", "unlocated link", "unlocated contrast", "judge failed", "text"])
def test_a_read_that_failed_asks_nothing_and_keeps_the_pairs_one_question(bank, answer):
    """A question is for "everything was read and it does not say". A failed or unreadable read is not that."""
    _doubt_bank(bank)
    report = _run(same_name_tend.tend(bank, _judge(answer), today=DAY))
    assert (report.asked, report.merged, report.apart) == (0, 0, 0) and report.skipped == {"not_read": 1}
    assert not list((bank / "inbox").glob("inbox-*.md"))
    assert same_name_doubts.pairs(bank) == {("marc", "marc-2"): {"since": "2026-11-01"}}, "still in doubt, never asked"
    assert same_name_doubts.flagged(bank) == (set(), set()) and _git(bank, "status", "--porcelain").strip() == ""
    # the next conversation that names the name flags it again, and a real "cannot tell" is then asked, once
    same_name_doubts.flag(bank, pairs_=[("marc", "marc-2")])
    assert _run(same_name_tend.tend(bank, _judge({"verdict": "cannot_tell"}), today=DAY)).asked == 1


def test_a_page_with_nothing_of_its_own_on_record_is_not_asked_about(bank):
    """One side has no conversation-by-conversation account (a page the person wrote): nothing was read, nothing asked."""
    _doubt_bank(bank)
    markdown_parser.write(bank / "entities" / "marc-2.md", {"name": "Marc", "type": "person", "status": "active"},
                          "## Summary\nMarc is a neighbour.\n")
    bank_index.invalidate()
    judge = _judge({"verdict": "cannot_tell"})
    report = _run(same_name_tend.tend(bank, judge, today=DAY))
    assert report.asked == 0 and judge.calls == [] and report.skipped == {"not_read": 1}


def test_a_question_already_open_about_the_two_is_not_asked_again(bank):
    _doubt_bank(bank)
    markdown_parser.write(bank / "inbox" / "inbox-001.md", {
        "kind": "merge_suggestion", "status": "pending", "entity_id": "marc-2", "merge_target_hint": "marc",
        "detected": "person_duplicate"}, "asked by another proposer")
    bank_index.invalidate()
    report = _run(same_name_tend.tend(bank, _judge({"verdict": "cannot_tell"}), today=DAY))
    assert report.asked == 0 and report.skipped == {"question_open": 1}
    assert len(list((bank / "inbox").glob("inbox-*.md"))) == 1


def test_a_located_contrast_makes_the_pair_a_split_for_good_and_asks_nothing(bank):
    _doubt_bank(bank)
    answer = {"verdict": "different", "here": "plays the cello", "there": "has a small brown dog"}
    report = _run(same_name_tend.tend(bank, _judge(answer), today=DAY))
    assert (report.apart, report.asked) == (1, 0) and _git(bank, "status", "--porcelain").strip() == ""
    assert merge_rejections.is_split(bank, "marc", "marc-2") and same_name_doubts.pairs(bank) == {}
    assert (bank / "entities" / "marc-2.md").exists()


def test_a_pair_the_person_already_answered_is_never_asked(bank):
    _doubt_bank(bank)
    merge_rejections.add_rejected(bank, "marc", "marc-2")
    judge = _judge({"verdict": "cannot_tell"})
    report = _run(same_name_tend.tend(bank, judge, today=DAY))
    assert report.asked == 0 and judge.calls == [] and same_name_doubts.pairs(bank) == {}


def test_a_person_held_on_a_line_is_never_asked_about(bank):
    _doubt_bank(bank)
    (bank / "entities" / "marc-2.md").unlink()
    bank_index.invalidate()
    judge = _judge({"verdict": "cannot_tell"})
    report = _run(same_name_tend.tend(bank, judge, today=DAY))
    assert report.asked == 0 and judge.calls == [] and report.skipped.get("a_line") == 1


def test_no_more_questions_than_the_drain_budget(bank):
    _doubt_bank(bank)
    _page(bank, "marc-3", {"ep_a1": ["Marc is a dentist with a clinic by the station"], "ep_b1": ["Marc fixed a molar"]},
          name="Marc", lead="Marc is a dentist.")
    same_name_doubts.add_pairs(bank, [("marc", "marc-3"), ("marc-2", "marc-3")])
    same_name_doubts.flag(bank, pairs_=[("marc", "marc-3"), ("marc-2", "marc-3")])
    bank_index.invalidate()
    report = _run(same_name_tend.tend(bank, _judge({"verdict": "cannot_tell"}), today=DAY, max_questions=1))
    assert report.asked == 1 and report.skipped.get("question_budget", 0) >= 1
    assert same_name_doubts.flagged(bank)[1], "what is over waits for the next drain, never lost"


def test_the_answers_work_yes_folds_and_no_keeps_them_apart_for_good(bank):
    """The question is an ordinary merge_suggestion with `fold_page`: yes merges the less-used page into the other,
    no records the pair as different (never asked or joined again by anything)."""
    _doubt_bank(bank)
    _run(same_name_tend.tend(bank, _judge({"verdict": "cannot_tell"}), today=DAY))
    item = next((bank / "inbox").glob("inbox-*.md"))
    fm = markdown_parser.parse(item).frontmatter
    merge_rejections.add_rejected(bank, fm["entity_id"], fm["merge_target_hint"])   # what a "no" records
    assert merge_rejections.kept_apart(bank) == {("marc", "marc-2")}
    page_join.merge(bank, fm["entity_id"], fm["merge_target_hint"], author="user")   # and the person's own "yes" (merge) clears it
    assert merge_rejections.kept_apart(bank) == set() and same_name_doubts.pairs(bank) == {}
    assert same_name_doubts.one(bank) == {fm["merge_target_hint"]}, "and the page they joined is never split by Sleep"


def test_sleep_never_settles_this_question_by_a_rule_or_a_judge(bank):
    """Ruling 29: a question asked because nothing on record could settle it is only the person's (or their words')."""
    from api.services import inbox_tend

    _doubt_bank(bank)
    _run(same_name_tend.tend(bank, _judge({"verdict": "cannot_tell"}), today=DAY))
    item = next((bank / "inbox").glob("inbox-*.md"))
    fm = markdown_parser.parse(item).frontmatter
    assert inbox_tend._merge_rule(bank, item.stem, fm) == (None, "needs_person")


def test_a_pile_of_open_questions_of_this_kind_waits_for_the_person(bank, monkeypatch):
    _doubt_bank(bank)
    monkeypatch.setattr(same_name_tend, "MAX_OPEN", 0)
    report = _run(same_name_tend.tend(bank, _judge({"verdict": "cannot_tell"}), today=DAY))
    assert report.asked == 0 and report.skipped.get("question_budget") == 1
    assert same_name_doubts.flagged(bank)[1] == {("marc", "marc-2")}


def test_end_to_end_a_later_conversation_clarifies_a_joined_page_and_the_tail_splits_it(bank, monkeypatch):
    """A page that was joined by mistake holds a colleague in Lyon and a cousin in Glasgow. A new conversation about the
    cousin arrives: Stage 2 lands it on the page (the group of the cousin's own conversations is the page's), flags the
    page, and after the batch the tail reads the page again and splits it by conversation: the cousin's beliefs, facts and
    conversations (the new one's too, once Stage 5 has written its beliefs) on a page of their own, as one undoable commit."""
    from types import SimpleNamespace

    from api.services import entity_resolver as er

    class Spy:
        def __init__(self, *_a, **_k):
            self.parked = {}

        def pending_by_name(self, name):
            return self.parked.get(name.lower())

        def index_pending_entity(self, entity):
            self.parked[entity.name.lower()] = entity

        def promote_from_pending(self, name):
            return self.parked.pop(name.lower(), None)

        def rebuild_pending_index(self):
            return len(self.parked)

    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: Spy())
    _joined(bank)
    page = markdown_parser.parse(bank / "entities" / "tomas.md")
    existing = [{"id": "tomas", "frontmatter": dict(page.frontmatter), "body": page.body}]
    new_text = "Tomas, the cousin, passed his law exams in Glasgow and will celebrate with the family on Saturday"
    extracted = [{"episode_id": "ep_c1", "origin": "claude-code",
                  "entities": [{"name": "Tomas", "type": "person", "confidence": 0.8, "summary": new_text,
                                "source_episode": "ep_c1", "source_episode_timestamp": "2026-11-20T00:00:00+00:00"}],
                  "relationships": [], "values": []}]
    stage2 = []

    async def stage2_judge(settings, system, prompt):
        stage2.append(prompt)
        # letters: A this batch's; then the page, newest first: B ep_b2, C ep_b1, D ep_a2, E ep_a1
        return _ans(["ABC", "DE"], [(1, 2, "different", "lives in Glasgow and studies law", "works as a logistics planner")])

    monkeypatch.setattr(er, "_same_name_ask", stage2_judge)
    settings = SimpleNamespace(memory_path=bank, litellm_model="m", litellm_disambiguation_model="m", sleep_promotion_threshold=2)
    out = _run(er.resolve(extracted, existing, settings))
    assert [(c["id"], c["action"]) for c in out["changes"]] == [("tomas", "update")], "it lands on the page, as before"
    assert "[person 1]" in stage2[0] and "logistics planner" in stage2[0] and "Glasgow and studies law" in stage2[0]
    assert same_name_doubts.flagged(bank) == ({"tomas"}, set()), "and the page is flagged for the tail"
    # the tail, once the batch has committed: the page is read again by the main model and split
    answer = _ans(["AB", "CD"], [(1, 2, "different", "lives in Glasgow and studies law", "works as a logistics planner")])
    report = _run(same_name_tend.tend(bank, _judge(answer), today=DAY))
    assert report.split == 1
    assert markdown_parser.parse(bank / "entities" / "tomas-2.md").frontmatter["source_episodes"] == ["ep_b1", "ep_b2"]


def test_what_a_page_is_known_for_is_cut_at_a_clause_never_mid_sentence(bank):
    _page(bank, "marc", {"ep_a1": ["x"]}, name="Marc",
          lead="Marc is a colleague on the banking app usability study who said in October 2026 that his move to the Berlin office is confirmed for 15 March, after which he is remote.")
    said = same_name_tend.known_for(bank, "marc")
    assert said == "Marc is a colleague on the banking app usability study" and len(said) <= 110
