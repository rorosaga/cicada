"""Two people known only by one first name are two people (2026-11-23, `same_name_people`).

The pure half is tested with a fake judge (no engine, no disk); the resolver half drives `entity_resolver.resolve` with
the judge call replaced and a spy in place of the pending index. Every name is invented.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services import entity_resolver as er
from api.services import pending_store, same_name_people as snp


def _run(coro):
    return asyncio.run(coro)


def _mentions(*pairs):
    return [snp.Mention(episode, text) for episode, text in pairs]


def _judge(answer):
    calls = []

    async def judge(system, prompt):
        calls.append(prompt)
        if isinstance(answer, Exception):
            raise answer
        return answer

    judge.calls = calls
    return judge


FAM_Q, WORK_Q = "a carpenter in a small mountain town", "a colleague on the research team"   # words both texts hold
CARPENTER = "(2026-09-29) the speaker's brother-in-law, a carpenter in a small mountain town who builds furniture and helps with shelves"
COLLEAGUE = "(2026-10-02) a colleague on the research team at the firm who is moving to another office next spring and works remotely"
M = _mentions(("e1", CARPENTER), ("e2", COLLEAGUE), ("e3", COLLEAGUE))


def ans(*groups, pairs=()):
    """The judge's answer: groups of letters, and ``(a, b, verdict, here, there)`` for how two groups stand."""
    return {"people": [{"conversations": list(g), "reason": "r"} for g in groups],
            "pairs": [{"people": [a, b], "verdict": v, "here": h, "there": t, "reason": "r"} for a, b, v, h, t in pairs]}


TWO = ans("A", "BC", pairs=[(1, 2, "different", FAM_Q, WORK_Q)])
DOUBT = ans("A", "BC", pairs=[(1, 2, "cannot_tell", FAM_Q, WORK_Q)])
ONE = ans("ABC")


# ------------------------------------------------------------------ the pure half


def test_two_groups_with_no_one_on_record_the_larger_keeps_the_plain_name():
    result = _run(snp.plan("Marc", M, [], _judge(TWO)))
    assert result.called
    assert result.moves == {"e1": snp.Destination("new", "g0")}
    assert not result.moves["e1"].doubt


def test_a_group_the_judge_cannot_tell_from_the_rest_is_held_in_doubt_not_joined():
    """Doubt is a state: the mention waits on a person of its own, marked as a doubt, and the name is flagged."""
    result = _run(snp.plan("Marc", M, [], _judge(DOUBT)))
    assert result.moves == {"e1": snp.Destination("new", "g0", True)}
    assert result.review and "doubt-held" in result.review_reasons


def test_a_doubt_with_no_located_quotes_is_the_old_behaviour_one_person():
    unlocated = ans("A", "BC", pairs=[(1, 2, "cannot_tell", "a plumber in Oslo", "a baker in Rome")])
    assert _run(snp.plan("Marc", M, [], _judge(unlocated))).moves == {}


def test_a_person_with_a_thin_description_is_never_split_from_a_richer_one():
    """The false split the benchmark found (2026-11-23): an earlier conversation says only that a person put in a word,
    a later one that they are a head of product. A description that says one thing has nothing to contradict."""
    known = [snp.Identity("line", "teo", True, "(2026-10-21) put in a word for the speaker at the firm")]
    later = _mentions(("e9", "(2026-11-13) head of product at the firm after a promotion, two levels above the speaker, "
                             "who also reviews the team's quarterly plans"))
    answer = ans("A", "B", pairs=[(1, 2, "different", "head of product at the firm", "put in a word for the speaker")])
    result = _run(snp.plan("Teo", later, known, _judge(answer)))
    assert result.moves == {} and result.thin == 1 and not result.review


def test_a_thin_new_person_is_kept_with_the_plain_name_too():
    short = _mentions(("e1", "(2026-09-29) a carpenter"), ("e2", COLLEAGUE), ("e3", COLLEAGUE))
    thin = ans("A", "BC", pairs=[(1, 2, "different", "a carpenter", WORK_Q)])
    result = _run(snp.plan("Marc", short, [], _judge(thin)))
    assert result.moves == {} and result.thin == 1


def test_words_are_counted_without_the_date():
    assert snp.words("(2026-09-29) one two three") == 3 and snp.words("") == 0


def test_a_tie_keeps_the_earlier_conversation_plain():
    two = ans("A", "B", pairs=[(1, 2, "different", FAM_Q, WORK_Q)])
    result = _run(snp.plan("Marc", M[:2], [], _judge(two)))
    assert result.moves == {"e2": snp.Destination("new", "g1")}


def test_one_person_in_many_settings_is_one_group_and_nothing_moves():
    assert _run(snp.plan("Marc", M, [], _judge(ONE))).moves == {}


@pytest.mark.parametrize("answer", [
    {}, {"people": []}, {"people": "x"}, None, "text", {"people": [{"conversations": ["Z"]}]}, RuntimeError("down"),
], ids=["empty", "no groups", "not a list", "none", "text", "no such conversation", "judge raised"])
def test_an_answer_that_does_not_line_up_keeps_the_old_behaviour(answer):
    ident = [snp.Identity("page", "marc", True, "a colleague")]
    assert _run(snp.plan("Marc", M, ident, _judge(answer))).moves == {}


def test_a_conversation_the_answer_leaves_out_stays_with_the_name():
    partial = ans("B", pairs=[])
    known = [snp.Identity("page", "marc", True, COLLEAGUE)]
    assert _run(snp.plan("Marc", M, known, _judge(partial))).moves == {}


def test_a_new_conversation_goes_to_the_known_person_in_its_group():
    known = [snp.Identity("page", "marc", True, "a colleague on the research team"),
             snp.Identity("line", "marc-2", False, "a carpenter in a small mountain town")]
    # letters: A B C are this batch's, D is person 1, E person 2
    answer = ans("ADBC", "E", pairs=[(1, 2, "different", WORK_Q, FAM_Q)])
    # the first conversation is in the group with person 1 (D): stays; nothing moves to a line
    assert _run(snp.plan("Marc", M, known, _judge(answer))).moves == {}
    answer = ans("BCD", "AE", pairs=[(1, 2, "different", WORK_Q, FAM_Q)])
    assert _run(snp.plan("Marc", M, known, _judge(answer))).moves == {"e1": snp.Destination("line", "marc-2")}


def test_with_a_plain_person_on_record_a_new_group_is_never_the_plain_one():
    known = [snp.Identity("page", "marc", True, COLLEAGUE)]
    answer = ans("AB", "CD", pairs=[(1, 2, "different", FAM_Q, "a colleague on the research team at the firm")])
    assert _run(snp.plan("Marc", M, known, _judge(answer))).moves == {
        "e1": snp.Destination("new", "g0"), "e2": snp.Destination("new", "g0")}


def test_nothing_to_compare_asks_nothing():
    judge = _judge(TWO)
    assert not _run(snp.plan("Marc", M[:1], [], judge)).called
    assert not _run(snp.plan("Marc", [], [snp.Identity("page", "marc", True, "p")], judge)).called
    assert judge.calls == []


def test_the_bound_one_call_a_name_and_what_is_over_the_cap_stays():
    many = _mentions(*((f"e{i}", f"text {i}") for i in range(30)))
    judge = _judge(ans("ABCDEFGHIJ"))
    result = _run(snp.plan("Marc", many, [], judge))
    assert len(judge.calls) == 1 and result.moves == {}
    assert "(J)" in judge.calls[0] and "(K)" not in judge.calls[0]


def test_a_known_person_is_shown_conversation_by_conversation_newest_first_within_the_cap():
    items = tuple(snp.Item(f"(2026-10-{d:02d}) said {d}", (f"k{d}",)) for d in range(1, 26))
    known = [snp.Identity("page", "marc", True, "blend", frozenset(f"k{d}" for d in range(1, 26)), items)]
    entries = snp.entries_for(_mentions(("e1", "new one")), known)
    assert len(entries) == snp.MAX_ENTRIES and entries[0].identity is None
    assert entries[1].text.endswith("said 25") and entries[1].identity == 0 and entries[1].episodes == ("k25",)
    prompt = snp.build_prompt("Marc", entries, known)
    assert "[person 1]" in prompt and "NEW CONVERSATIONS" in prompt and "(B) (2026-10-25) said 25" in prompt


def test_a_known_person_with_only_a_blended_text_is_one_description():
    known = [snp.Identity("line", "marc", True, COLLEAGUE, frozenset({"e7", "e8"}))]
    entries = snp.entries_for(_mentions(("e1", "x")), known)
    assert [e.episodes for e in entries] == [("e1",), ("e7", "e8")]


def test_the_prompt_names_the_three_answers_and_asks_for_positive_evidence():
    prompt = snp.build_prompt("Marc", snp.entries_for(M, []), [])
    assert "NOT a difference" in prompt and "cannot be true of one person at the same time" in prompt
    assert '"cannot_tell"' in prompt and '"different"' in prompt and "Two groups you give no entry for are the same person" in prompt
    assert f"(A) {CARPENTER}" in prompt


def test_the_prompt_says_a_life_that_changes_is_one_person_and_a_split_names_two_facts_that_cannot_both_hold():
    """2026-11-23: a partner who gets a job and moves, a friend who is promoted, were split from their own page (a
    different employer or town read as a different person). A change since the earlier conversation is the same person;
    a split must quote one fact from each side that cannot both be true at the same time."""
    known = [snp.Identity("page", "idris", True, "Idris is the speaker's partner.")]
    prompt = snp.build_prompt("Idris", snp.entries_for(_mentions(("e1", "(2026-11-03) Got a job at the hospital in Grenoble.")), known), known)
    assert "People change" in prompt and "NOT a different person" in prompt and "headed by its date" in prompt
    assert "copy, word for word" in prompt and "silent about something says nothing" in prompt
    assert "say \"same\"" in prompt and "Dates decide" in prompt


@pytest.mark.parametrize("quotes", [
    ("", ""), ("a colleague on the research team", "a plumber in Oslo"), ("is", "a"), (FAM_Q, FAM_Q), (WORK_Q, ""),
], ids=["missing", "a fact the descriptions never state", "too short to say anything", "both from one side", "one side"])
def test_a_split_without_a_located_contrast_is_no_split(quotes):
    """2026-11-23: the judge answered "another person" while its own reason said the conversation fits the known person
    (the false split of a friend in a benchmark run). A person Sleep would make new is a claim: two facts copied from
    the descriptions, one from each group. Without them the conversations stay."""
    known = [snp.Identity("page", "marc", True, COLLEAGUE)]
    answer = ans("A", "B", pairs=[(1, 2, "different", *quotes)])
    assert _run(snp.plan("Marc", M[:1], known, _judge(answer))).moves == {}


def test_a_split_with_a_located_contrast_in_either_order_stands():
    known = [snp.Identity("page", "marc", True, COLLEAGUE)]
    for here, there in ((FAM_Q, WORK_Q), (WORK_Q, FAM_Q)):
        answer = ans("A", "B", pairs=[(1, 2, "different", here, there)])
        assert _run(snp.plan("Marc", M[:1], known, _judge(answer))).moves == {"e1": snp.Destination("new", "g0")}
    # the words may be quoted with edge quotes, other case, an ellipsis between two pieces
    answer = ans("A", "B", pairs=[(1, 2, "different", f"\"{FAM_Q.upper()}\"", "a colleague ... research team at the firm")])
    assert _run(snp.plan("Marc", M[:1], known, _judge(answer))).moves == {"e1": snp.Destination("new", "g0")}


def test_an_answer_that_joins_two_different_groups_through_a_third_splits_nothing():
    three = ans("A", "B", "C", pairs=[(1, 2, "different", FAM_Q, WORK_Q)])   # 1 and 2 differ, 3 is the same as both
    assert _run(snp.plan("Marc", M, [], _judge(three))).moves == {}


def test_when_the_two_the_judge_calls_different_have_a_doubt_between_them_the_milder_reading_stands():
    both = ans("A", "BC", pairs=[(1, 2, "different", FAM_Q, WORK_Q), (2, 1, "cannot_tell", FAM_Q, WORK_Q)])
    assert _run(snp.plan("Marc", M, [], _judge(both))).moves == {"e1": snp.Destination("new", "g0", True)}


def test_a_page_the_reread_shows_holds_two_people_flags_the_page_and_moves_nothing():
    """Two of a page's own conversations contrast: the page is not touched here (`same_name_tend` acts on it after the
    commit), the new conversation goes where its group's known person is, and the name is flagged."""
    items = (snp.Item("(2026-10-04) " + WORK_Q + " in the Lyon office where he lives and works", ("k1",)),
             snp.Item("(2026-10-25) " + FAM_Q + " who plays football on Saturdays", ("k2",)))
    known = [snp.Identity("page", "marc", True, "blend", frozenset({"k1", "k2"}), items)]
    # letters: A = this batch's, B = the newest of the page (k2), C = k1
    answer = ans("AB", "C", pairs=[(1, 2, "different", FAM_Q, WORK_Q)])
    result = _run(snp.plan("Marc", M[:1], known, _judge(answer)))
    assert result.moves == {} and result.review and result.review_pages == {"marc"}


def test_two_people_in_doubt_that_the_judge_now_puts_in_one_group_flag_the_pair():
    a = snp.Identity("page", "marc", True, WORK_Q, frozenset({"k1"}), (snp.Item("(2026-10-04) " + WORK_Q, ("k1",)),),
                     frozenset({"marc-2"}))
    b = snp.Identity("page", "marc-2", False, FAM_Q, frozenset({"k2"}), (snp.Item("(2026-10-25) " + FAM_Q, ("k2",)),),
                     frozenset({"marc"}))
    result = _run(snp.plan("Marc", M[:1], [a, b], _judge(ans("ABC"))))
    assert result.moves == {}, "one group: nothing is placed apart"
    assert not result.review, "the plan only flags what it sees as two groups; a single group is the old behaviour"
    both = ans("ABC")
    assert snp.read(both, snp.entries_for(M[:1], [a, b])).single


def test_only_a_bare_name_is_for_this_rule():
    assert snp.is_bare("Marc") and snp.is_bare("Léa")
    assert not snp.is_bare("Marc Dupont") and not snp.is_bare("M") and not snp.is_bare("marc2") and not snp.is_bare("")


def test_a_conversation_a_person_already_lists_is_that_person():
    a = snp.Identity("page", "marc", True, "", frozenset({"e1"}))
    b = snp.Identity("line", "marc-2", False, "", frozenset({"e1", "e2"}))
    assert snp.identity_for_episode("e2", [a, b]) is b
    assert snp.identity_for_episode("e1", [a, b]) is None, "two people list it: judged, never guessed"


def test_the_next_free_id():
    assert snp.free_id("marc", {"marc"}) == "marc-2"
    assert snp.free_id("marc", {"marc", "marc-2", "marc-3"}) == "marc-4"


# ------------------------------------------------------------------ the resolver half


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    (memory / ".gitkeep").write_text("")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "t@cicada.local")
    _git(memory, "config", "user.name", "T")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    return memory


class _Spy:
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


def _settings(memory):
    return SimpleNamespace(memory_path=memory, litellm_model="m", litellm_disambiguation_model="m",
                           sleep_promotion_threshold=2)


FAMILY = "my brother-in-law, a carpenter in a small mountain town who builds furniture and helps with shelves"
WORK = "a colleague on the research team at the firm who is moving to another office next spring and works remotely"


def _extraction(episode, text, *, label="works with", target="Nina Example"):
    return {"episode_id": episode, "origin": "chatgpt",
            "entities": [{"name": "Marc", "type": "person", "confidence": 0.8, "summary": text,
                          "source_episode": episode, "source_episode_timestamp": "2026-10-01T00:00:00+00:00"}],
            "relationships": [{"source": "Marc", "target": target, "label": label, "source_episode": episode}],
            "values": [{"entity": "Marc", "attribute": "age", "value": "41", "source_episode": episode}]}


@pytest.fixture
def judged(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: spy)
    box = SimpleNamespace(answer=None, calls=[])

    async def ask(settings, system, prompt):
        box.calls.append(prompt)
        if isinstance(box.answer, Exception):
            raise box.answer
        return box.answer

    monkeypatch.setattr(er, "_same_name_ask", ask)
    box.spy = spy
    return box


def _page(page_id, summary, episodes):
    return {"id": page_id, "frontmatter": {"name": "Marc", "type": "person", "confidence": 0.8,
                                           "source_episodes": episodes}, "body": f"## Summary\n{summary}\n"}


def test_in_one_batch_two_people_of_one_name_are_a_page_and_a_held_line(tmp_path, judged):
    memory = _bank(tmp_path)
    extracted = [_extraction("ep1", FAMILY, target="Alpine Town"), _extraction("ep2", WORK), _extraction("ep3", WORK)]
    judged.answer = TWO
    out = _run(er.resolve(extracted, [], _settings(memory)))
    creates = {c["id"]: c for c in out["changes"] if c["action"] == "create"}
    assert set(creates) == {"marc"} and creates["marc"]["entity"]["summary"] == WORK
    assert set(creates["marc"]["source_episodes"]) == {"ep2", "ep3"}
    line = judged.spy.parked["marc-2"]
    assert line.title == "Marc" and line.type == "person" and line.episodes() == ["ep1"]
    assert "marc" not in judged.spy.parked, "the family line is never the plain name's"
    # The family conversation's edge and value are pinned to its own id; the colleague's are not pinned.
    assert extracted[0]["relationships"][0]["source_page"] == "marc-2"
    assert extracted[0]["values"][0]["source_page"] == "marc-2"
    assert "source_page" not in extracted[1]["relationships"][0]
    assert out["name_to_id"]["marc"] == "marc"
    from api.services import merge_rejections

    assert merge_rejections.load_split(memory) == {("marc", "marc-2")}, "the pair Sleep decided, and only that one"
    assert len(judged.calls) == 1


def test_a_later_conversation_of_the_held_person_gives_them_a_page_of_their_own(tmp_path, judged):
    memory = _bank(tmp_path)
    pending_store.save(memory, [pending_store.PendingEntity(
        name="marc-2", type="person", description="", source_episode="ep1", confidence=0.8, tags=[],
        history_entries=[], summary=FAMILY, heard_in=[{"episode": "ep1"}], title="Marc")])
    colleague = _page("marc", WORK, ["ep2", "ep3"])
    extracted = [_extraction("ep4", "my brother-in-law Marc fixed the roof again", target="Alpine Town"),
                 _extraction("ep5", WORK)]
    # letters: A, B this batch's; C the plain page; D the held line
    judged.answer = ans("AD", "BC", pairs=[(1, 2, "different", "my brother-in-law", "a colleague on the research team")])
    out = _run(er.resolve(extracted, [colleague], _settings(memory)))
    by_id = {c["id"]: c for c in out["changes"]}
    assert by_id["marc-2"]["action"] == "create" and by_id["marc-2"]["entity"]["name"] == "Marc"
    assert {"ep1", "ep4"} <= set(by_id["marc-2"]["source_episodes"])
    assert out["promoted_pending"] == ["marc-2"]
    assert by_id["marc"]["action"] == "update" and "ep5" in by_id["marc"]["source_episodes"]
    assert "marc-2" not in {c["id"] for c in out["changes"] if c["action"] == "update"}


def test_a_new_conversation_about_the_second_person_never_lands_on_the_first_page(tmp_path, judged):
    memory = _bank(tmp_path)
    plain, second = _page("marc", WORK, ["ep2", "ep3"]), _page("marc-2", FAMILY, ["ep1", "ep4"])
    extracted = [_extraction("ep9", "my brother-in-law is a carpenter and built the shelves", target="Alpine Town")]
    # letters: A this batch's; B the plain page; C the second person's page
    judged.answer = ans("AC", "B", pairs=[(1, 2, "different", "a carpenter", "a colleague on the research team")])
    out = _run(er.resolve(extracted, [plain, second], _settings(memory)))
    assert [(c["id"], c["action"]) for c in out["changes"]] == [("marc-2", "update")]
    assert extracted[0]["relationships"][0]["source_page"] == "marc-2"


def test_one_person_in_clearly_different_settings_stays_one_page(tmp_path, judged):
    memory = _bank(tmp_path)
    extracted = [_extraction("ep1", "ran the same race with the person in spring"),
                 _extraction("ep2", "cooked dinner at the person's home"),
                 _extraction("ep3", "joined the trip to the coast")]
    judged.answer = ans("ABC")
    out = _run(er.resolve(extracted, [], _settings(memory)))
    assert {c["id"] for c in out["changes"]} == {"marc"} and judged.spy.parked == {}
    assert all("source_page" not in rel for ex in extracted for rel in ex["relationships"])


def test_a_judge_that_fails_is_the_old_behaviour(tmp_path, judged):
    memory = _bank(tmp_path)
    judged.answer = RuntimeError("boom")
    out = _run(er.resolve([_extraction("ep1", FAMILY), _extraction("ep2", WORK)], [], _settings(memory)))
    assert {c["id"] for c in out["changes"]} == {"marc"}


def test_nothing_is_asked_when_there_is_nothing_to_compare(tmp_path, judged):
    memory = _bank(tmp_path)
    full = _extraction("ep1", FAMILY)
    full["entities"].append({"name": "Nina Example", "type": "person", "confidence": 0.8, "summary": "x",
                             "source_episode": "ep1"})
    _run(er.resolve([full], [], _settings(memory)))
    assert judged.calls == [], "one conversation, nobody on record, and a full name: no call"


def test_a_conversation_a_page_already_lists_is_not_judged_again(tmp_path, judged):
    memory = _bank(tmp_path)
    plain, second = _page("marc", WORK, ["ep2"]), _page("marc-2", FAMILY, ["ep1"])
    out = _run(er.resolve([_extraction("ep1", FAMILY, target="Alpine Town")], [plain, second], _settings(memory)))
    assert judged.calls == [] and [(c["id"], c["action"]) for c in out["changes"]] == [("marc-2", "update")]


def test_a_second_person_below_the_bar_waits_and_never_joins_the_plain_line(tmp_path, judged):
    memory = _bank(tmp_path)
    pending_store.save(memory, [pending_store.PendingEntity(
        name="Marc", type="person", description="", source_episode="ep1", confidence=0.8, tags=[],
        history_entries=[], summary=FAMILY, heard_in=[{"episode": "ep1"}])])
    judged.answer = ans("A", "B", pairs=[(1, 2, "different", "a colleague on the research team", FAM_Q)])
    out = _run(er.resolve([_extraction("ep2", WORK)], [], _settings(memory)))
    assert out["changes"] == [] and set(judged.spy.parked) == {"marc-2"}
    assert judged.spy.parked["marc-2"].episodes() == ["ep2"] and judged.spy.parked["marc-2"].title == "Marc"
    from api.services import merge_rejections

    assert merge_rejections.load_split(memory) == {("marc", "marc-2")}, "kept apart before the line is ever a page"


def test_a_cancelled_batch_records_no_pair(tmp_path, judged):
    from api.services import merge_rejections

    memory = _bank(tmp_path)
    polls = {"n": 0}

    def cancel():
        polls["n"] += 1
        return polls["n"] > 1   # the plan's poll passes; the loop's first poll cancels

    judged.answer = TWO
    _run(er.resolve([_extraction("ep1", FAMILY), _extraction("ep2", WORK), _extraction("ep3", WORK)], [],
                    _settings(memory), cancel_check=cancel))
    assert merge_rejections.load_split(memory) == set() and not (memory / merge_rejections.FILE).exists()
    assert judged.spy.parked == {}


def test_a_later_conversation_of_a_known_person_records_nothing_new(tmp_path, judged):
    from api.services import merge_rejections

    memory = _bank(tmp_path)
    merge_rejections.add_split(memory, "marc", "marc-2")
    before = (memory / merge_rejections.FILE).read_text()
    plain, second = _page("marc", WORK, ["ep2", "ep3"]), _page("marc-2", FAMILY, ["ep1", "ep4"])
    judged.answer = ans("AC", "B", pairs=[(1, 2, "different", "a carpenter", "a colleague on the research team")])
    _run(er.resolve([_extraction("ep9", "my brother-in-law is a carpenter and built the shelves", target="Alpine Town")],
                    [plain, second], _settings(memory)))
    assert (memory / merge_rejections.FILE).read_text() == before


def test_a_doubt_is_held_apart_like_a_split_but_recorded_as_a_doubt_never_as_a_split(tmp_path, judged):
    """2026-11-23: the record shows two kinds of person and nothing that says both cannot be one. The mention waits on a
    person of its own (never blended into the other's page), the pair is a doubt `same_name_tend` looks at again, and
    nothing is recorded as kept apart for good."""
    from api.services import merge_rejections, same_name_doubts

    memory = _bank(tmp_path)
    extracted = [_extraction("ep1", FAMILY, target="Alpine Town"), _extraction("ep2", WORK), _extraction("ep3", WORK)]
    judged.answer = ans("A", "BC", pairs=[(1, 2, "cannot_tell", FAM_Q, WORK_Q)])
    out = _run(er.resolve(extracted, [], _settings(memory)))
    creates = {c["id"]: c for c in out["changes"] if c["action"] == "create"}
    assert set(creates) == {"marc"} and set(creates["marc"]["source_episodes"]) == {"ep2", "ep3"}
    assert judged.spy.parked["marc-2"].episodes() == ["ep1"]
    assert extracted[0]["relationships"][0]["source_page"] == "marc-2"
    assert merge_rejections.load_split(memory) == set() and not (memory / merge_rejections.FILE).exists()
    assert set(same_name_doubts.pairs(memory)) == {("marc", "marc-2")}
    assert same_name_doubts.flagged(memory) == (set(), {("marc", "marc-2")})


def test_a_cancelled_batch_records_no_doubt_either(tmp_path, judged):
    from api.services import same_name_doubts

    memory = _bank(tmp_path)
    polls = {"n": 0}

    def cancel():
        polls["n"] += 1
        return polls["n"] > 1

    judged.answer = ans("A", "BC", pairs=[(1, 2, "cannot_tell", FAM_Q, WORK_Q)])
    _run(er.resolve([_extraction("ep1", FAMILY), _extraction("ep2", WORK), _extraction("ep3", WORK)], [],
                    _settings(memory), cancel_check=cancel))
    assert same_name_doubts.pairs(memory) == {} and not (memory / same_name_doubts.FILE).exists()


def test_the_judge_is_shown_a_known_page_conversation_by_conversation(tmp_path, judged):
    from api.services import markdown_parser
    from api.services.claims import Claim, write_claims

    memory = _bank(tmp_path)
    claims = [Claim(id="clm_1", text="Marc works in the Lyon office", subject="marc", predicate="works-at", object="Lyon",
                    source_episodes=["ep2"]),
              Claim(id="clm_2", text="Marc is the speaker's cousin in Glasgow", subject="marc", predicate="is", object="cousin",
                    source_episodes=["ep3"])]
    markdown_parser.write(memory / "entities" / "marc.md", {"name": "Marc", "type": "person", "status": "active",
                                                            "source_episodes": ["ep2", "ep3"]},
                          write_claims("## Summary\nMarc is a colleague and a cousin.\n", claims))
    page = {"id": "marc", "frontmatter": {"name": "Marc", "type": "person", "source_episodes": ["ep2", "ep3"]},
            "body": "## Summary\nMarc is a colleague and a cousin.\n"}
    judged.answer = ans("ABC")
    _run(er.resolve([_extraction("ep9", "a runner who joined the race")], [page], _settings(memory)))
    prompt = judged.calls[0]
    assert "[person 1]" in prompt and "Marc works in the Lyon office" in prompt and "the speaker's cousin in Glasgow" in prompt
