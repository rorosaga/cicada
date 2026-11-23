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


def _judge(answer, check=None):
    """A grouping answer, and the answer the narrow check on a proposed split gets (default: it holds up, quoting the
    first line of each side)."""
    calls = []

    async def judge(system, prompt):
        calls.append(prompt)
        if prompt.startswith("Two descriptions"):
            if check is not None:
                return check
            lines = [ln for ln in prompt.splitlines() if ln and not ln.startswith(("DESCRIPTION", "Two ", "Could", "Answer", "If ", "Different"))]
            return {"verdict": "two_people", "excluding": lines[0][-30:], "with": lines[1][-30:]}
        if isinstance(answer, Exception):
            raise answer
        return answer

    judge.calls = calls
    return judge


TWO = {"people": [
    {"conversations": ["A"], "same_as": None, "reason": "a carpenter in a small town, not a colleague"},
    {"conversations": ["B", "C"], "same_as": None, "reason": "works at the firm and moves to another city"}]}
ONE = {"people": [{"conversations": ["A", "B", "C"], "same_as": None, "reason": "the same person in three settings"}]}
M = _mentions(("e1", "a carpenter in a small town"), ("e2", "a colleague moving offices"), ("e3", "a colleague"))


# ------------------------------------------------------------------ the pure half


def test_two_groups_with_no_one_on_record_the_larger_keeps_the_plain_name():
    result = _run(snp.plan("Marc", M, [], _judge(TWO)))
    assert result.called
    assert result.moves == {"e1": snp.Destination("new", "g0")}


@pytest.mark.parametrize("check", [
    {"verdict": "one_person"}, {}, None, "two_people",
    {"verdict": "two_people", "excluding": "a carpenter in a small town", "with": "never said anywhere at all"},
    {"verdict": "two_people", "excluding": "carpenter", "with": "colleague"},
], ids=["one person", "empty", "none", "text", "a quote that is not there", "quotes too short"])
def test_a_split_the_check_does_not_hold_up_goes_back_to_the_plain_name(check):
    judge = _judge(TWO, check=check if check is not None else {"verdict": None})
    result = _run(snp.plan("Marc", M, [], judge))
    assert result.moves == {} and result.checked == 1
    assert len(judge.calls) == 2, "one grouping call and one check for the one person it would have made new"


def test_a_split_that_quotes_both_sides_stands():
    check = {"verdict": "two_people", "excluding": "a colleague moving offices", "with": "a carpenter in a small town"}
    result = _run(snp.plan("Marc", M, [], _judge(TWO, check=check)))
    assert result.moves == {"e1": snp.Destination("new", "g0")}


def test_a_thin_earlier_description_never_splits_a_later_richer_one():
    """The false split the benchmark found (2026-11-23): one conversation says a person put in a word, a later one that
    they are a head of product. Nothing excludes anything; the check says one person."""
    known = [snp.Identity("line", "teo", True, "(2026-10-21) put in a word for the speaker")]
    later = _mentions(("e9", "(2026-11-13) head of product at the firm after a promotion"))
    answer = {"people": [{"conversations": ["A"], "same_as": None, "reason": "different roles"}]}
    result = _run(snp.plan("Teo", later, known, _judge(answer, check={"verdict": "one_person"})))
    assert result.moves == {}


def test_a_tie_keeps_the_earlier_conversation_plain():
    two = {"people": [{"conversations": ["A"], "same_as": None, "reason": "x"},
                      {"conversations": ["B"], "same_as": None, "reason": "y"}]}
    result = _run(snp.plan("Marc", M[:2], [], _judge(two)))
    assert result.moves == {"e2": snp.Destination("new", "g1")}


def test_one_person_in_many_settings_is_one_group_and_nothing_moves():
    assert _run(snp.plan("Marc", M, [], _judge(ONE))).moves == {}


@pytest.mark.parametrize("answer", [
    {}, {"people": []}, {"people": "x"}, None, "text", {"people": [{"conversations": ["A"], "same_as": None}]},
    {"people": [{"conversations": ["A"], "same_as": 9, "reason": "x"}]}, RuntimeError("down"),
], ids=["empty", "no groups", "not a list", "none", "text", "no reason", "no such person", "judge raised"])
def test_an_answer_that_does_not_line_up_keeps_the_old_behaviour(answer):
    ident = [snp.Identity("page", "marc", True, "a colleague")]
    assert _run(snp.plan("Marc", M, ident, _judge(answer))).moves == {}


def test_a_conversation_the_answer_leaves_out_stays_with_the_name():
    partial = {"people": [{"conversations": ["B"], "same_as": None, "reason": "x"}]}
    known = [snp.Identity("page", "marc", True, "a colleague at the research firm")]
    assert _run(snp.plan("Marc", M, known, _judge(partial))).moves == {
        "e2": snp.Destination("new", "g0")}


def test_known_people_a_conversation_joins_the_one_it_fits():
    known = [snp.Identity("page", "marc", True, "a colleague"), snp.Identity("line", "marc-2", False, "a carpenter")]
    answer = {"people": [{"conversations": ["A"], "same_as": 2}, {"conversations": ["B", "C"], "same_as": 1}]}
    assert _run(snp.plan("Marc", M, known, _judge(answer))).moves == {"e1": snp.Destination("line", "marc-2")}


def test_with_a_plain_person_on_record_a_new_group_is_never_the_plain_one():
    known = [snp.Identity("page", "marc", True, "a colleague")]
    answer = {"people": [{"conversations": ["A", "B"], "same_as": None, "reason": "a carpenter"},
                         {"conversations": ["C"], "same_as": 1}]}
    assert _run(snp.plan("Marc", M, known, _judge(answer))).moves == {
        "e1": snp.Destination("new", "g0"), "e2": snp.Destination("new", "g0")}


def test_nothing_to_compare_asks_nothing():
    judge = _judge(TWO)
    assert not _run(snp.plan("Marc", M[:1], [], judge)).called
    assert not _run(snp.plan("Marc", [], [snp.Identity("page", "marc", True, "p")], judge)).called
    assert judge.calls == []


def test_the_bound_one_call_a_name_and_what_is_over_the_cap_stays():
    many = _mentions(*((f"e{i}", f"text {i}") for i in range(30)))
    judge = _judge({"people": [{"conversations": [chr(65 + i) for i in range(12)], "same_as": None, "reason": "x"}]})
    result = _run(snp.plan("Marc", many, [], judge))
    assert len(judge.calls) == 1 and result.moves == {}
    assert "(L)" in judge.calls[0] and "(M)" not in judge.calls[0]


def test_the_prompt_asks_for_positive_evidence_and_says_a_setting_is_none():
    prompt = snp.build_prompt("Marc", M, [snp.Identity("page", "marc", True, "a colleague")])
    assert "NOT a difference" in prompt and "a different trade or employer" in prompt
    assert "[1] a colleague" in prompt and "(A) a carpenter" in prompt


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


FAMILY = "my brother-in-law, a carpenter in a small town"
WORK = "a colleague at the research firm who is moving offices"


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
        if prompt.startswith("Two descriptions"):
            one = prompt.split("DESCRIPTION 1\n")[1].split("\n\nDESCRIPTION 2")[0]
            two = prompt.split("DESCRIPTION 2\n")[1].split("\n\nCould all")[0]
            return {"verdict": "two_people", "excluding": one.strip()[-25:], "with": two.strip()[-25:]}
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
    assert len(judged.calls) == 2, "one grouping call and one check on the one new person"


def test_a_later_conversation_of_the_held_person_gives_them_a_page_of_their_own(tmp_path, judged):
    memory = _bank(tmp_path)
    pending_store.save(memory, [pending_store.PendingEntity(
        name="marc-2", type="person", description="", source_episode="ep1", confidence=0.8, tags=[],
        history_entries=[], summary=FAMILY, heard_in=[{"episode": "ep1"}], title="Marc")])
    colleague = _page("marc", WORK, ["ep2", "ep3"])
    extracted = [_extraction("ep4", "my brother-in-law Marc fixed the roof again", target="Alpine Town"),
                 _extraction("ep5", WORK)]
    judged.answer = {"people": [{"conversations": ["A"], "same_as": 2}, {"conversations": ["B"], "same_as": 1}]}
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
    judged.answer = {"people": [{"conversations": ["A"], "same_as": 2}]}
    out = _run(er.resolve(extracted, [plain, second], _settings(memory)))
    assert [(c["id"], c["action"]) for c in out["changes"]] == [("marc-2", "update")]
    assert extracted[0]["relationships"][0]["source_page"] == "marc-2"


def test_one_person_in_clearly_different_settings_stays_one_page(tmp_path, judged):
    memory = _bank(tmp_path)
    extracted = [_extraction("ep1", "ran the same race with the person in spring"),
                 _extraction("ep2", "cooked dinner at the person's home"),
                 _extraction("ep3", "joined the trip to the coast")]
    judged.answer = {"people": [{"conversations": ["A", "B", "C"], "same_as": None, "reason": "one friend, three settings"}]}
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
    judged.answer = {"people": [{"conversations": ["A"], "same_as": None, "reason": "a colleague, not a carpenter"}]}
    out = _run(er.resolve([_extraction("ep2", WORK)], [], _settings(memory)))
    assert out["changes"] == [] and set(judged.spy.parked) == {"marc-2"}
    assert judged.spy.parked["marc-2"].episodes() == ["ep2"] and judged.spy.parked["marc-2"].title == "Marc"
