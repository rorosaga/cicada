"""Sleep joins a name that is plainly a misspelling of a person's page itself (ruling 74c, 2026-11-24, `typo_join`).

A scripted judge on a scratch bank with real git. Names invented (Marisol Quinn / Marizol Quinn, Ines Varga the speaker);
no engine, no network. Every guard has a test that the judge is never called, and the join's undo."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.services import (bank_index, inbox_tend, markdown_parser, merge_rejections, pending_store, predicates,
                          typo_join)
from api.services.claims import Claim, parse_claims, write_claims

PAGE_LINE = "Marisol Quinn is travelling to Lisbon with me in June"
HELD_LINE = "Marizol Quinn is coming on the Lisbon trip in June, I booked her flight"


def run(coro):
    return asyncio.run(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _commit(memory: Path, msg: str = "seed") -> None:
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", msg)
    bank_index.invalidate(memory)


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.llm_mode = "byok"


def _page(memory: Path, eid: str, name: str, *, claims=(), episodes=(), **fm) -> None:
    meta = {"name": name, "type": "person", "status": "active", "confidence": 0.8, "created": "2026-10-01",
            "last_referenced": "2026-10-20", "source_episodes": list(episodes), "related": [], "version": 1}
    meta.update(fm)
    body = f"## Summary\n{name}, synthetic.\n"
    markdown_parser.write(memory / "entities" / f"{eid}.md", meta, write_claims(body, list(claims)) if claims else body)


def _episode(memory: Path, eid: str, body: str) -> None:
    markdown_parser.write(memory / "episodes" / f"{eid}.md", {"id": eid, "timestamp": f"{eid[3:13]}T09:00:00+00:00",
                                                              "processed": True, "title": "chat", "source": "claude-code"}, body)


def _claim(cid: str, subject: str, text: str, episode: str, predicate: str = "travels-with",
           object_: str = "ines-varga") -> Claim:
    return Claim(id=cid, text=text, subject=subject, predicate=predicate, object=object_, object_kind="node",
                 source_episodes=[episode])


def _hold(memory: Path, name: str, episode: str, text: str) -> None:
    claim = _claim("clm_2026-11-14_aaaa1111", name.lower().replace(" ", "-"), text, episode)
    pending_store.upsert(memory, pending_store.PendingEntity(
        name=name, type="person", description="", source_episode=episode, confidence=0.9, tags=[],
        history_entries=[{"date": "2026-11-14", "event": "Booked a flight."}], held_claims=[claim.to_dict()], aliases=[]))


def _world(memory: Path, *, page_a: bool = False, asked: bool = True) -> Path | None:
    """B: the page "Marisol Quinn" (one conversation says she travels to Lisbon in June). A: "Marizol Quinn", from a later
    dictated conversation that says the same trip, held on a line (or, ``page_a``, a page of its own)."""
    _episode(memory, "ep_2026-10-22_001", f"user: {PAGE_LINE}.\nassistant: Lovely.\n")
    _episode(memory, "ep_2026-11-14_001", f"user: {HELD_LINE}.\nassistant: Great.\n")
    _page(memory, "marisol-quinn", "Marisol Quinn", episodes=["ep_2026-10-22_001", "ep_2026-10-25_001"] if page_a else ["ep_2026-10-22_001"],
          claims=[_claim("clm_2026-10-22_bbbb2222", "marisol-quinn", PAGE_LINE, "ep_2026-10-22_001")])
    if page_a:
        _episode(memory, "ep_2026-10-25_001", "user: Nothing about her here.\nassistant: Ok.\n")
        _page(memory, "marizol-quinn", "Marizol Quinn", episodes=["ep_2026-11-14_001"],
              claims=[_claim("clm_2026-11-14_cccc3333", "marizol-quinn", HELD_LINE, "ep_2026-11-14_001",
                             "books-flight-for", "lisbon-trip")])    # no belief shared with B: ruling 74's two signals do not apply
        q = memory / "inbox" / "inbox-001.md"
        markdown_parser.write(q if asked else memory / "inbox" / "x.tmp", {"kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.4,
                                  "entity_id": "marizol-quinn", "entity_name": "Marizol Quinn",
                                  "title": "Is Marizol Quinn the same as Marisol Quinn?", "created_date": "2026-11-15",
                                  "merge_target_hint": "marisol-quinn", "detected": "person_duplicate"},
                              "They may be one person; asked, never joined: only your answer joins them.")
    else:
        q = None
        _hold(memory, "Marizol Quinn", "ep_2026-11-14_001", HELD_LINE)
    _commit(memory, "world")
    return q


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    _page(m, "ines-varga", "Ines Varga", owner=True)
    _commit(m)
    return m


def _judge(*answers):
    queue = list(answers)
    calls: list[str] = []

    async def judge(system, prompt):
        calls.append(prompt)
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer(prompt) if callable(answer) else answer

    judge.calls = calls
    return judge


def _one(here: str = HELD_LINE, there: str = PAGE_LINE) -> dict:
    return {"verdict": "one", "here": here, "there": there, "reason": "r"}


def _tend(memory: Path, judge) -> typo_join.Report:
    return run(typo_join.tend(memory, _Settings(memory), judge))


def _open(memory: Path) -> list[str]:
    return sorted(p.stem for p in (memory / "inbox").glob("inbox-*.md"))


# --------------------------------------------------------------------------- what a name is


@pytest.mark.parametrize("a,b", [("Marizol Quinn", "Marisol Quinn"), ("Texim", "Tikzim"), ("Sarah", "Sara")])
def test_one_name_written_two_ways(a, b):
    assert typo_join.variant(a, b) and typo_join.variant(b, a)


@pytest.mark.parametrize("a,b", [("Mari", "Marisol Quinn"), ("Daniel Smith", "Daniela Smith"), ("Marisol", "Marisol"),
                                 ("Marisol Quinn", "Marisol Lowe"), ("Teo", "Teodor Brandt"), ("Alex", "Max")])
def test_a_nickname_a_bare_ending_a_different_surname_is_not_one_name(a, b):
    assert not typo_join.variant(a, b)


# --------------------------------------------------------------------------- the join


def test_a_held_misspelling_joins_the_page_as_one_undoable_settle_with_no_question(memory):
    _world(memory)
    judge = _judge(_one())
    report = _tend(memory, judge)
    assert report.joined == 1 and len(judge.calls) == 2           # read twice
    assert _open(memory) == []                                    # the question existed only inside the settle
    page = markdown_parser.parse(memory / "entities" / "marisol-quinn.md")
    assert "Marizol Quinn" in (page.frontmatter.get("aliases") or [])
    assert not (memory / "entities" / "marizol-quinn.md").exists()  # never a second page
    assert pending_store.held_line(memory, "Marizol Quinn") is None
    # what was said about it is filed on the page: the same fact gains its second conversation, the prose lands too
    assert any("ep_2026-11-14_001" in c.source_episodes for c in parse_claims(page.body))
    assert "Booked a flight" in page.body
    rec = markdown_parser.parse(next((memory / "inbox" / "settled").glob("inbox-*.md"))).frontmatter["settled"]
    assert rec["rule"] == "typo_one" and HELD_LINE[:30] in rec["reason"]
    assert _git(memory, "status", "--porcelain").strip() == ""


def test_undoing_the_join_is_the_person_saying_they_are_two(memory):
    _world(memory)
    _tend(memory, _judge(_one()))
    item = next((memory / "inbox" / "settled").glob("inbox-*.md")).stem
    restored, paths, lines, rec = inbox_tend.undo(memory, item)
    assert rec["rule"] == "typo_one" and not (memory / "inbox" / f"{restored}.md").exists()   # no question comes back
    bank_index.invalidate(memory)
    assert pending_store.held_line(memory, "Marizol Quinn") is not None
    assert "Marizol Quinn" not in (markdown_parser.parse(memory / "entities" / "marisol-quinn.md").frontmatter.get("aliases") or [])
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []   # kept apart for good: never read again


def test_two_pages_nobody_asked_about_are_read_and_joined_with_no_question_at_all(memory):
    _world(memory, page_a=True, asked=False)
    (memory / "inbox" / "x.tmp").unlink()
    _commit(memory, "no question")
    assert _open(memory) == []
    report = _tend(memory, _judge(_one()))
    assert report.joined == 1 and _open(memory) == []
    assert not (memory / "entities" / "marizol-quinn.md").exists()


def test_two_pages_nobody_asked_about_that_the_model_cannot_tell_wait_apart_with_no_question(memory):
    _world(memory, page_a=True, asked=False)
    (memory / "inbox" / "x.tmp").unlink()
    _commit(memory, "no question")
    assert _tend(memory, _judge({"verdict": "cannot_tell"})).joined == 0
    assert _open(memory) == [] and (memory / "entities" / "marizol-quinn.md").exists()


def test_two_pages_one_misspelt_join_through_the_person_duplicate_question(memory):
    _world(memory, page_a=True)
    report = _tend(memory, _judge(_one()))
    assert report.joined == 1 and _open(memory) == []
    assert (memory / "entities" / "marisol-quinn.md").exists() and not (memory / "entities" / "marizol-quinn.md").exists()
    aliases = markdown_parser.parse(memory / "entities" / "marisol-quinn.md").frontmatter.get("aliases") or []
    assert "Marizol Quinn" in aliases


# --------------------------------------------------------------------------- when the record cannot tell


@pytest.mark.parametrize("first", [
    {"verdict": "two", "reason": "different"},
    {"verdict": "cannot_tell", "reason": "?"},
    {"verdict": "one", "here": "Marizol Quinn is a person I know well", "there": PAGE_LINE},      # not in the record
    {"verdict": "one", "here": HELD_LINE, "there": "Marisol Quinn works on the Lisbon trip"},       # not in the record
    {"verdict": "one", "here": "Marizol Quinn", "there": "Marisol Quinn"},                           # a name states nothing
    "not json",
])
def test_a_first_read_that_is_not_one_on_located_lines_joins_nothing(memory, first):
    _world(memory)
    report = _tend(memory, _judge(first))
    assert report.joined == 0 and pending_store.held_line(memory, "Marizol Quinn") is not None
    assert not list((memory / "inbox" / "settled").glob("*.md")) if (memory / "inbox" / "settled").exists() else True
    assert _open(memory) == []                                    # and no question was left behind


def test_a_second_read_that_looks_for_two_people_and_disagrees_joins_nothing(memory):
    _world(memory)
    judge = _judge(_one(), {"verdict": "two", "reason": "a sister"})
    assert _tend(memory, judge).joined == 0 and len(judge.calls) == 2
    assert "sceptical" in judge.calls[1] and "sceptical" not in judge.calls[0]


def test_two_real_people_with_near_names_are_not_joined_when_the_model_says_two(memory):
    _world(memory)
    assert _tend(memory, _judge({"verdict": "two", "reason": "sisters"})).joined == 0


def test_a_failed_read_is_read_again_and_a_standing_one_is_not(memory):
    _world(memory)
    judge = _judge({"verdict": "cannot_tell"})
    _tend(memory, judge)
    _tend(memory, judge)
    assert len(judge.calls) == 1                                  # read, and nothing changed: not read again


# --------------------------------------------------------------------------- the guards: the judge is never called


def test_a_spelling_near_two_pages_is_a_question_whichever_the_model_would_pick(memory):
    _world(memory)
    _page(memory, "marisola-quinn", "Marisola Quinn")
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_a_held_name_near_a_second_held_name_is_not_read(memory):
    _world(memory)
    _hold(memory, "Marisola Quinn", "ep_2026-11-14_001", HELD_LINE)
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_two_names_the_record_names_together_are_never_read(memory):
    _world(memory)
    _episode(memory, "ep_2026-11-20_001", "user: Marisol Quinn and Marizol Quinn both came to dinner.\nassistant: Nice.\n")
    _page(memory, "marisol-quinn", "Marisol Quinn", episodes=["ep_2026-10-22_001", "ep_2026-11-20_001"],
          claims=[_claim("clm_2026-10-22_bbbb2222", "marisol-quinn", PAGE_LINE, "ep_2026-10-22_001")])
    pending_store.upsert(memory, pending_store.PendingEntity(
        name="Marizol Quinn", type="person", description="", source_episode="ep_2026-11-14_001", confidence=0.9, tags=[],
        history_entries=[{"date": "2026-11-14", "event": "Booked."}], held_claims=[], aliases=[],
        heard_in=[{"episode": "ep_2026-11-20_001"}]))
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_a_pair_the_person_called_two_is_never_read(memory):
    _world(memory, page_a=True)
    merge_rejections.add_rejected(memory, "marizol-quinn", "marisol-quinn")
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_the_owners_page_is_never_the_target(memory):
    _page(memory, "ines-varga", "Ines Varga", owner=True)
    _hold(memory, "Ines Varga", "ep_2026-11-14_001", "Ines Varga flew to Lisbon in June")
    _hold(memory, "Inez Varga", "ep_2026-11-14_001", "Inez Varga flew to Lisbon in June")
    _commit(memory)
    judge = _judge(_one("Inez Varga flew to Lisbon in June", "Ines Varga flew to Lisbon in June"))
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_a_relation_titled_page_is_never_a_target(memory):
    _page(memory, "marisol-partner", "Marisol's Partner", roles=["partner"], unnamed=True)
    _hold(memory, "Marizol's Partner", "ep_2026-11-14_001", HELD_LINE)
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_a_nickname_is_not_one_name_and_asks_nothing_here(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn")
    _hold(memory, "Mari", "ep_2026-11-14_001", HELD_LINE)
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).looked == 0 and judge.calls == []


def test_nothing_of_the_shape_open_resolves_no_engine(memory, monkeypatch):
    from api.services import same_name_tend

    async def boom(*_a, **_k):
        raise AssertionError("an engine was resolved")

    monkeypatch.setattr(same_name_tend, "main_engine", boom)
    report = run(typo_join.run_tail(memory, _Settings(memory), user_triggered=True))
    assert report.looked == 0


def test_a_change_between_the_reads_and_the_settle_leaves_things_as_they_were(memory):
    _world(memory)

    async def judge(system, prompt):
        _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marisol Q"],
              claims=[_claim("clm_2026-10-22_bbbb2222", "marisol-quinn", PAGE_LINE + " again", "ep_2026-10-22_001")])
        return _one()

    report = _tend(memory, judge)
    assert report.joined == 0 and pending_store.held_line(memory, "Marizol Quinn") is not None and _open(memory) == []
