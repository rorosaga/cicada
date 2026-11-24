"""Sleep joins a name held in full to its short-name page itself (ruling 74b, 2026-11-24, `full_name_join`).

A scripted judge on a scratch bank with real git; every guard has a test that the judge is never called (or its answer
never joins), and the join's undo. Names invented (Teodor Brandt / Teo, Ines Varga the speaker); no engine, no network."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.services import (bank_index, full_name_join, inbox_tend, markdown_parser, merge_rejections, pending_store,
                          predicates, same_name_doubts)
from api.services.claims import Claim, Evidence, parse_claims, write_claims

APPOSITION = "Had lunch with Teo today. Teodor Brandt, my old teammate from university. He's a product manager at Kestrel Robotics now."
TWO = "Teo's father, Teodor Brandt, picked us up at the station."


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


def _page(memory: Path, eid: str, name: str, *, type_="person", body: str | None = None, **fm) -> None:
    meta = {"name": name, "type": type_, "status": "active", "confidence": 0.8, "created": "2026-10-01",
            "last_referenced": "2026-10-20", "source_episodes": [], "related": [], "version": 1}
    meta.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", meta, body or f"## Summary\n{name}, synthetic.\n")


def _episode(memory: Path, eid: str, body: str, **fm) -> None:
    meta = {"id": eid, "timestamp": f"{eid[3:13]}T09:00:00+00:00", "processed": True, "title": "chat",
            "source": "claude-code"}
    meta.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", meta, body)


def _held(memory: Path, name: str, episode: str, turn: str, *, aliases=("Teo",), **extra) -> None:
    start = turn.find(name)
    claim = Claim(id=f"clm_{episode[3:13]}_aaaa1111", text=f"{name} former teammate of Ines Varga", subject=name.lower().replace(" ", "-"),
                  predicate="former-teammate-of", object="ines-varga", object_kind="node", source_episodes=[episode],
                  evidence=[Evidence(episode=episode, start=len("user: ") + start, end=len("user: ") + start + len(name),
                                     kind="user", hash="0" * 12)])
    pending_store.upsert(memory, pending_store.PendingEntity(
        name=name, type="person", description="", source_episode=episode, confidence=0.9, tags=[],
        history_entries=[{"date": "2026-10-03", "event": "Had lunch."}], held_claims=[claim.to_dict()],
        aliases=list(aliases), **extra))


def _question(memory: Path, number: int, name: str, target: str, target_name: str, episode: str, **fm) -> Path:
    path = memory / "inbox" / f"inbox-{number:03d}.md"
    meta = {"kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.6,
            "entity_id": name.lower().replace(" ", "-"), "entity_name": name, "title": f"Is {name} the same as {target_name}?",
            "uncertainty_type": f"Possible duplicate of {target_name}", "suggested_confidence": 0.6,
            "created_date": "2026-11-24", "source_episode": episode, "merge_target_hint": target}
    meta.update(fm)
    markdown_parser.write(path, meta, f"A conversation also called {name} “{target_name}”, the name {target_name}'s page carries.")
    return path


def _world(memory: Path, turn: str = APPOSITION, *, assistant: str = "Nice to reconnect!") -> Path:
    """The owner, a page "Teo" that two later conversations promoted, the full name held from the one conversation that
    said both, and the question Stage 2 raised."""
    _episode(memory, "ep_2026-10-03_001", f"user: {turn}\nassistant: {assistant}\nuser: Warehouse robots.\n")
    _episode(memory, "ep_2026-10-22_001", "user: Teo put in a word for me at Kestrel.\nassistant: Good.\n")
    _episode(memory, "ep_2026-11-14_001", "user: Teo got promoted to head of product at Kestrel.\nassistant: Nice.\n")
    claim = Claim(id="clm_2026-11-14_bbbb2222", text="Teo works at Kestrel", subject="teo", predicate="works-at",
                  object="kestrel-robotics", object_kind="node", source_episodes=["ep_2026-11-14_001"])
    _page(memory, "teo", "Teo", source_episodes=["ep_2026-10-22_001", "ep_2026-11-14_001"],
          body=write_claims("## Summary\nTeo works at Kestrel Robotics.\n\n## Key Facts\n- Teo works at Kestrel.\n", [claim]))
    _held(memory, "Teodor Brandt", "ep_2026-10-03_001", turn)
    path = _question(memory, 1, "Teodor Brandt", "teo", "Teo", "ep_2026-10-03_001")
    _commit(memory, "world")
    return path


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
    """Answers in order (the last repeats); a callable answer sees the prompt."""
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


def _one(quote: str = "Had lunch with Teo today. Teodor Brandt, my old teammate from university.") -> dict:
    return {"verdict": "one", "turn": 1, "quote": quote, "reason": "r"}


def _tend(memory: Path, judge) -> full_name_join.Report:
    return run(full_name_join.tend(memory, _Settings(memory), judge))


def _open(memory: Path) -> list[str]:
    return sorted(p.stem for p in (memory / "inbox").glob("inbox-*.md"))


# --------------------------------------------------------------------------- the join


def test_two_reads_that_agree_join_the_held_name_through_the_one_writer(memory):
    _world(memory)
    judge = _judge(_one())
    report = _tend(memory, judge)
    assert (report.joined, report.reads, len(judge.calls)) == (1, 2, 2)
    assert _open(memory) == [] and (memory / "inbox" / "settled" / "inbox-001.md").is_file()
    page = markdown_parser.parse(memory / "entities" / "teo.md")
    assert "Teodor Brandt" in page.frontmatter["aliases"]
    claims = parse_claims(page.body)
    held = [c for c in claims if c.text == "Teodor Brandt former teammate of Ines Varga"]
    assert held and held[0].subject == "teo" and held[0].evidence and held[0].evidence[0].episode == "ep_2026-10-03_001"
    assert "ep_2026-10-03_001" in page.frontmatter["source_episodes"]
    assert not any(line.name == "Teodor Brandt" for line in pending_store.load(memory))
    # one commit, Sleep's, its rule and a reason that quotes the person's own words
    message = _git(memory, "log", "-1", "--format=%B")
    assert "Inbox settled by Sleep" in message and "trigger: sleep/inbox-tend:full_name_one" in message
    assert "Cicada-Author: cicada" in message
    record = markdown_parser.parse(memory / "inbox" / "settled" / "inbox-001.md").frontmatter["settled"]
    assert record["rule"] == "full_name_one" and record["by_kind"] == "sleep"
    assert "Teodor Brandt, my old teammate" in record["reason"] and record["evidence"]["episode"] == "ep_2026-10-03_001"
    assert _git(memory, "status", "--porcelain").strip() == ""


def test_the_second_read_is_framed_to_look_for_two_people(memory):
    _world(memory)
    judge = _judge(_one())
    _tend(memory, judge)
    assert "sceptical reader" not in judge.calls[0] and "sceptical reader" in judge.calls[1]
    for prompt in judge.calls:
        assert "Teodor Brandt" in prompt and "my old teammate" in prompt and "Teo works at Kestrel" in prompt


def _stage2_asks(memory: Path) -> list:
    """What Stage 2's held-name route would raise now (`_held_alias_questions`), engine-free."""
    from api.services import clarification_manager, entity_resolver

    existing = []
    for page in (memory / "entities").glob("*.md"):
        parsed = markdown_parser.parse(page)
        existing.append({"id": page.stem, "frontmatter": dict(parsed.frontmatter), "body": parsed.body})
    return entity_resolver._held_alias_questions([], existing, {}, clarification_manager.ClarificationManager(memory), memory)


@pytest.mark.parametrize("held_mention", [False, True])
def test_undoing_the_join_is_the_person_saying_they_are_two(memory, held_mention):
    """Ruling 74b: the pages and the held line come back as they were; the pair is kept apart by the writer the person's
    own "No, different" uses; no question comes back, and nothing asks or joins them again."""
    path = _world(memory)
    if held_mention:   # the shape Stage 2 marks a question about a held mention with (`entity_resolver.HELD_MENTION_KEY`)
        page = markdown_parser.parse(path)
        markdown_parser.write(path, {**page.frontmatter, "held_mention": True}, page.body)
        _commit(memory, "marked")
    assert len(_stage2_asks(memory)) == 1, "before: Stage 2's held-name route would raise this pair"
    before = (memory / "entities" / "teo.md").read_bytes()
    store_before = (memory / "pending_entities.jsonl").read_bytes()
    assert _tend(memory, _judge(_one())).joined == 1
    commits = len(_git(memory, "log", "--format=%h").split())
    restored, paths, lines, rec = inbox_tend.undo(memory, "inbox-001")
    _commit(memory, "undo")
    assert rec["rule"] == "full_name_one" and restored == "inbox-001"
    assert (memory / "entities" / "teo.md").read_bytes() == before
    assert not (memory / "inbox" / "inbox-001.md").exists() and not (memory / "inbox" / "settled" / "inbox-001.md").exists()
    line = pending_store.held_line(memory, "Teodor Brandt")
    assert line is not None and line.held_claims, "the held line is back with its claims"
    if held_mention:
        assert "teo" in pending_store.apart_of(memory, "Teodor Brandt")
    else:
        assert merge_rejections.is_rejected(memory, "teodor-brandt", "teo")
        assert (memory / "pending_entities.jsonl").read_bytes() == store_before
    assert len(_git(memory, "log", "--format=%h").split()) == commits + 1, "one commit for the undo"
    # nothing asks and nothing joins, from either side
    assert _stage2_asks(memory) == []
    judge = _judge(_one())
    report = _tend(memory, judge)
    assert report.joined == 0 and judge.calls == [] and _open(memory) == []


def test_the_undo_route_says_the_pair_is_kept_apart_and_other_rules_still_reopen(memory):
    from api.routers import inbox as inbox_router

    _world(memory)
    assert _tend(memory, _judge(_one())).joined == 1
    out = run(inbox_router.undo_settled("inbox-001", settings=_Settings(memory)))
    assert out == {"status": "kept_apart", "id": "inbox-001"}
    sha = _git(memory, "log", "--grep=Sleep's settle undone", "-1", "--format=%h").strip()
    assert sha, "one commit, the person's"
    touched = _git(memory, "show", "--name-only", "--format=", sha).split()
    assert "entities/teo.md" in touched and "_merge_rejected.yaml" in touched and "inbox/settled/inbox-001.md" in touched
    assert _git(memory, "status", "--porcelain").strip() == ""


# --------------------------------------------------------------------------- the reads must both stand


@pytest.mark.parametrize("first", [{"verdict": "two", "reason": "r"}, {"verdict": "cannot_tell", "reason": "r"},
                                   {"verdict": "one", "turn": 1, "quote": "Teo and Teodor Brandt", "reason": "r"},
                                   {"verdict": "one", "turn": 1, "quote": "Had lunch with Teo today.", "reason": "r"},
                                   {"verdict": "one", "turn": 1, "quote": "Had lunch with Teo today. Teodor Brandt, my old friend", "reason": "r"},
                                   {"verdict": "one", "turn": 1, "quote": "Teo today ... Teodor Brandt, my old teammate", "reason": "r"},
                                   {"verdict": "one"}, "not json", {}])
def test_a_first_read_that_is_not_one_on_located_words_joins_nothing(memory, first):
    _world(memory)
    judge = _judge(first)
    report = _tend(memory, judge)
    assert report.joined == 0 and (memory / "inbox" / "inbox-001.md").is_file()
    assert len(judge.calls) == 1


@pytest.mark.parametrize("second", [{"verdict": "two", "reason": "r"}, {"verdict": "cannot_tell"},
                                    {"verdict": "one", "turn": 1, "quote": "Teodor Brandt, my old teammate", "reason": "r"}])
def test_a_second_read_that_disagrees_or_has_no_located_words_joins_nothing(memory, second):
    _world(memory)
    judge = _judge(_one(), second)
    report = _tend(memory, judge)
    assert report.joined == 0 and (memory / "inbox" / "inbox-001.md").is_file() and len(judge.calls) == 2


def test_words_that_exist_only_in_the_assistants_turn_are_no_evidence(memory):
    # Both names are in the person's turn too, but the quote is the assistant's reply: not located in a user turn.
    _world(memory, assistant="Teo is short for Teodor Brandt, I believe, and he sounds lovely.")
    judge = _judge({"verdict": "one", "turn": 1, "quote": "Teo is short for Teodor Brandt, I believe", "reason": "r"})
    assert _tend(memory, judge).joined == 0 and (memory / "inbox" / "inbox-001.md").is_file()


def test_both_names_only_in_the_assistants_words_is_never_read(memory):
    _world(memory, turn="Had lunch with a university friend today.", assistant="Teo is short for Teodor Brandt, I believe.")
    judge = _judge(_one())
    report = _tend(memory, judge)
    assert report.joined == 0 and judge.calls == [] and report.skipped.get("no_turn_names_both") == 1


def test_a_model_that_says_two_for_a_father_and_son_leaves_the_question(memory):
    _world(memory, turn=TWO)
    judge = _judge({"verdict": "two", "reason": "the father"})
    report = _tend(memory, judge)
    assert report.joined == 0 and len(judge.calls) == 1 and (memory / "inbox" / "inbox-001.md").is_file()


def test_an_engine_failure_stops_the_step_and_a_failed_read_is_read_again_next_drain(memory):
    from api.services import engine_errors

    _world(memory)
    with pytest.raises(engine_errors.EngineThrottled):
        _tend(memory, _judge(engine_errors.EngineThrottled("limit")))
    assert (memory / "inbox" / "inbox-001.md").is_file()
    broken = _judge(RuntimeError("boom"))
    assert _tend(memory, broken).joined == 0 and len(broken.calls) == 1
    # a read that stood is not repeated until something it read changes; one that could not be made is tried twice
    assert _tend(memory, broken).looked == 1 and len(broken.calls) == 2
    assert _tend(memory, broken).looked == 0 and len(broken.calls) == 2


def test_a_read_that_stood_is_not_repeated_until_the_record_changes(memory):
    _world(memory, turn=TWO)
    judge = _judge({"verdict": "two", "reason": "r"})
    assert _tend(memory, judge).looked == 1
    assert _tend(memory, judge).looked == 0 and len(judge.calls) == 1
    page = markdown_parser.parse(memory / "entities" / "teo.md")
    markdown_parser.write(memory / "entities" / "teo.md", page.frontmatter, page.body + "\n- A new line.\n")
    assert _tend(memory, judge).looked == 1 and len(judge.calls) == 2


# --------------------------------------------------------------------------- the guards: the judge is never asked


def _blocked(memory: Path, why: str) -> None:
    judge = _judge(_one())
    report = _tend(memory, judge)
    assert report.joined == 0 and judge.calls == [] and report.skipped.get(why) == 1, report.skipped
    assert (memory / "inbox" / "inbox-001.md").is_file()


def test_a_second_page_answering_to_the_short_name_blocks(memory):
    _world(memory)
    _page(memory, "teo-2", "Teo", aliases=["Teo"])
    _commit(memory)
    _blocked(memory, "short_name_not_alone")


def test_another_person_who_the_short_name_could_mean_blocks(memory):
    _world(memory)
    _page(memory, "teodoro-ruiz", "Teodoro Ruiz")
    _commit(memory)
    _blocked(memory, "short_name_not_alone")


def test_another_held_person_who_the_short_name_could_mean_blocks(memory):
    _world(memory)
    pending_store.upsert(memory, pending_store.PendingEntity(
        name="Teo Marchetti", type="person", description="", source_episode="ep_2026-10-22_001", confidence=0.7,
        tags=[], history_entries=[]))
    _commit(memory)
    _blocked(memory, "short_name_not_alone")


def test_a_page_in_a_same_name_doubt_blocks(memory):
    _world(memory)
    _page(memory, "teo-2", "Teo", status="active")
    same_name_doubts.add_pairs(memory, [("teo", "teo-2")])
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_the_owners_page_is_never_the_target(memory):
    _world(memory)
    page = markdown_parser.parse(memory / "entities" / "teo.md")
    markdown_parser.write(memory / "entities" / "teo.md", {**page.frontmatter, "owner": True}, page.body)
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_a_page_the_person_said_is_not_this_one_blocks(memory):
    _world(memory)
    merge_rejections.add_rejected(memory, "teodor-brandt", "teo")
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []
    # and a held line the person marked apart from the page
    memory2 = memory
    pending_store.mark_apart(memory2, "Teodor Brandt", ["teo"])
    _commit(memory2)
    assert _tend(memory2, judge).joined == 0 and judge.calls == []


def test_a_name_with_a_page_of_its_own_is_not_held_and_never_joined(memory):
    _world(memory)
    _page(memory, "teodor-brandt", "Teodor Brandt")
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_a_second_person_of_one_name_line_titled_apart_is_not_joined(memory):
    _world(memory)
    pending_store.upsert(memory, pending_store.PendingEntity(
        name="Teodor Brandt", type="person", description="", source_episode="ep_2026-10-03_001", confidence=0.9,
        tags=[], history_entries=[], aliases=["Teo"], title="Teodor"))
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_a_short_name_held_against_a_full_name_page_is_out_of_scope(memory):
    """"Is Sam the same as Sam Okafor?": the held name is the short one, a page holds the full name."""
    _episode(memory, "ep_2026-10-03_001", "user: Sam Okafor, who everyone calls Sam, called.\nassistant: ok\n")
    _page(memory, "sam-okafor", "Sam Okafor")
    pending_store.upsert(memory, pending_store.PendingEntity(
        name="Sam", type="person", description="", source_episode="ep_2026-10-03_001", confidence=0.9, tags=[],
        history_entries=[], aliases=["Sam Okafor"]))
    _question(memory, 1, "Sam", "sam-okafor", "Sam Okafor", "ep_2026-10-03_001")
    _commit(memory)
    judge = _judge(_one("Sam Okafor, who everyone calls Sam"))
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_two_existing_pages_are_out_of_scope(memory):
    _episode(memory, "ep_2026-10-03_001", "user: Teodor Brandt, who everyone calls Teo, called.\nassistant: ok\n")
    _page(memory, "teo", "Teo")
    _page(memory, "teodor-brandt", "Teodor Brandt")
    _question(memory, 1, "Teodor Brandt", "teo", "Teo", "ep_2026-10-03_001")
    _commit(memory)
    judge = _judge(_one("Teodor Brandt, who everyone calls Teo"))
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_a_question_the_person_took_back_or_put_off_is_not_touched(memory):
    path = _world(memory)
    page = markdown_parser.parse(path)
    markdown_parser.write(path, {**page.frontmatter, "remind_after": "2099-01-01"}, page.body)
    _commit(memory)
    judge = _judge(_one())
    assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_a_question_that_asks_about_a_doubt_or_a_page_is_not_this_one(memory):
    path = _world(memory)
    page = markdown_parser.parse(path)
    for extra in ({"detected": "same_name_doubt"}, {"fold_page": True}):
        markdown_parser.write(path, {**page.frontmatter, **extra}, page.body)
        bank_index.invalidate(memory)
        judge = _judge(_one())
        assert _tend(memory, judge).joined == 0 and judge.calls == []


def test_a_page_changed_between_the_reads_and_the_settle_leaves_the_question(memory):
    _world(memory)

    async def go():
        path = memory / "inbox" / "inbox-001.md"
        fm = dict(markdown_parser.parse(path).frontmatter)
        result = await full_name_join.assess(memory, path, fm, _judge(_one()))
        assert result.outcome == "join"
        page = markdown_parser.parse(memory / "entities" / "teo.md")
        markdown_parser.write(memory / "entities" / "teo.md", page.frontmatter, page.body + "\n- Edited since.\n")
        d = result.decision
        d.fingerprint = path.read_bytes()
        return await inbox_tend.apply(memory, _Settings(memory), d)

    assert run(go()) is False and (memory / "inbox" / "inbox-001.md").is_file()


def test_a_missing_judge_or_a_scheduled_run_without_the_plan_switch_reads_nothing(memory, monkeypatch):
    from api.services import same_name_tend

    _world(memory)

    async def none(settings, *, user_triggered):
        return None, "scheduled_plan"

    monkeypatch.setattr(same_name_tend, "main_engine", none)
    report = run(full_name_join.run_tail(memory, _Settings(memory), user_triggered=False))
    assert report.joined == 0 and report.skipped == {"scheduled_plan": 1}


def test_nothing_of_the_shape_open_resolves_no_engine(memory, monkeypatch):
    from api.services import same_name_tend

    async def boom(settings, *, user_triggered):
        raise AssertionError("no engine may be resolved")

    monkeypatch.setattr(same_name_tend, "main_engine", boom)
    assert run(full_name_join.run_tail(memory, _Settings(memory), user_triggered=True)).looked == 0


def test_the_short_name_inside_the_full_name_is_not_a_second_mention(memory):
    """"I mentor Ola Petrov": "Ola" is a word of the full name, not a short name said beside it (a stored benchmark bank)."""
    _episode(memory, "ep_2026-10-03_001", "user: Five of us. My manager there is Odile Brandt, and I mentor Ola Petrov, who joined this spring.\nassistant: ok\n")
    _episode(memory, "ep_2026-10-22_001", "user: Ola asked me about the rota.\nassistant: ok\n")
    _page(memory, "ola", "Ola", source_episodes=["ep_2026-10-22_001"])
    _held(memory, "Ola Petrov", "ep_2026-10-03_001", "Five of us. My manager there is Odile Brandt, and I mentor Ola Petrov, who joined this spring.", aliases=("Ola",))
    _question(memory, 1, "Ola Petrov", "ola", "Ola", "ep_2026-10-03_001")
    _commit(memory)
    judge = _judge(_one("I mentor Ola Petrov, who joined this spring"))
    report = _tend(memory, judge)
    assert report.joined == 0 and judge.calls == [] and report.skipped.get("no_turn_names_both") == 1


def test_names_both_needs_the_short_name_outside_the_full_one():
    f, s = ["teodor brandt"], ["teo"]
    assert full_name_join.names_both(f, s, "Teodor Brandt, who everyone calls Teo")
    assert full_name_join.names_both(["sam okafor"], ["sam"], "Sam Okafor came, and Sam stayed")
    assert not full_name_join.names_both(["sam okafor"], ["sam"], "Sam Okafor came")
    assert not full_name_join.names_both(f, s, "Teodor Brandt came") and not full_name_join.names_both(f, s, "Teo came")


# --------------------------------------------------------------------------- the held line's own words reach the page


def _give_the_line_prose(memory: Path) -> None:
    from api.services import section_provenance

    line = pending_store.held_line(memory, "Teodor Brandt")
    line.summary = "Old teammate of Ines Varga from university, now a product manager at Kestrel Robotics."
    line.key_facts = ["Teodor Brandt told Ines Varga that Kestrel Robotics is hiring designers."]
    line.history_entries = [{"date": "2026-10-03", "event": "Had lunch with Ines Varga."}]
    line.item_inputs = [{"field": "summary", "text": line.summary, "evidence": [
                            {"episode": "ep_2026-10-03_001", "start": -1, "end": -1, "kind": "reasoning", "hash": "a" * 12}]},
                        {"field": "key_facts", "text": line.key_facts[0], "evidence": [
                            {"episode": "ep_2026-10-03_001", "start": -1, "end": -1, "kind": "reasoning", "hash": "a" * 12}]}]
    pending_store.upsert(memory, line)
    _commit(memory, "line prose")


def _sections(memory: Path, page: str = "teo") -> dict:
    from api.services import entity_body
    from api.services.claims import strip_claims_block

    return entity_body.parse_sections(strip_claims_block(markdown_parser.parse(memory / "entities" / f"{page}.md").body))


def test_the_join_carries_the_held_lines_own_words_to_the_page_with_their_source_rows(memory):
    from api.services import section_provenance

    _world(memory)
    _give_the_line_prose(memory)
    summary_before = _sections(memory)["Summary"]
    assert _tend(memory, _judge(_one())).joined == 1
    sections = _sections(memory)
    assert sections["Summary"] == summary_before, "a page that has a Summary keeps it"
    page_text = "\n".join(sections.values())
    assert "hiring designers" in page_text and "product manager at Kestrel Robotics" in page_text
    assert "2026-10-03: Had lunch with Ines Varga." in sections["History"]
    parsed = markdown_parser.parse(memory / "entities" / "teo.md")
    rows = section_provenance.matched(parsed.frontmatter, parsed.body)
    sources = {ev.episode for per in rows.values() for _guard, evs in per.values() for ev in evs}
    assert "ep_2026-10-03_001" in sources, "the facts the line brought keep their source rows (G118)"
    assert pending_store.held_line(memory, "Teodor Brandt") is None


def test_the_persons_own_tap_carries_it_too(memory):
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service

    _world(memory)
    _give_the_line_prose(memory)
    run(inbox_service._resolve_admitted("inbox-001", InboxResolveRequest(action="merge", merge_target="teo"),
                                        _Settings(memory), None))
    assert "hiring designers" in "\n".join(_sections(memory).values())
    assert "Teodor Brandt" in markdown_parser.parse(memory / "entities" / "teo.md").frontmatter["aliases"]


def test_an_undo_of_sleeps_join_puts_the_page_back_byte_for_byte_prose_included(memory):
    _world(memory)
    _give_the_line_prose(memory)
    before = (memory / "entities" / "teo.md").read_bytes()
    assert _tend(memory, _judge(_one())).joined == 1
    assert (memory / "entities" / "teo.md").read_bytes() != before
    inbox_tend.undo(memory, "inbox-001")
    assert (memory / "entities" / "teo.md").read_bytes() == before


def test_a_page_the_person_edited_keeps_every_passage_of_theirs_when_a_held_line_joins_it(memory):
    _world(memory)
    page = markdown_parser.parse(memory / "entities" / "teo.md")
    body = page.body.replace("## Summary\nTeo works at Kestrel Robotics.", "## Summary\nTeo is my favourite person at Kestrel.\n\n## My notes\nSent him a card.")
    markdown_parser.write(memory / "entities" / "teo.md", {**page.frontmatter, "human_edited": True}, body)
    _commit(memory, "edited")
    _give_the_line_prose(memory)
    assert _tend(memory, _judge(_one())).joined == 1
    sections = _sections(memory)
    assert sections["Summary"].startswith("Teo is my favourite person at Kestrel.")
    assert sections["My notes"] == "Sent him a card."
    assert "hiring designers" in "\n".join(sections.values())


def test_a_line_with_no_prose_changes_nothing_beyond_what_the_claims_did(memory):
    _world(memory)
    from api.services import inbox_service

    entries = pending_store.load(memory)
    for entry in entries:
        entry.history_entries = []
    pending_store.save(memory, entries)
    assert inbox_service._land_held_prose(memory, "Teodor Brandt", "teo") == []
    assert inbox_service._land_held_prose(memory, "Nobody Here", "teo") == []


# --------------------------------------------------------------------------- the reviewer's attacks (2026-11-24)


def _joined_with(memory: Path, turn: str, quote: str, *, assistant: str = "ok") -> int:
    _world(memory, turn, assistant=assistant)
    return _tend(memory, _judge(_one(quote))).joined


def test_a_quote_that_runs_from_the_persons_turn_into_the_assistants_is_no_join(memory):
    turn = "Teodor Brandt called. Also Teo was there."
    quote = "Also Teo was there.\nassistant: Teodor Brandt, who is Teo, is a lovely name"
    assert _joined_with(memory, turn, quote, assistant="Teodor Brandt, who is Teo, is a lovely name") == 0
    assert (memory / "inbox" / "inbox-001.md").is_file()


def test_a_quote_that_runs_into_another_speakers_line_of_a_meeting_is_no_join(memory):
    _world(memory, "Teodor Brandt rang, and so did Teo.")
    _episode(memory, "ep_2026-10-03_001", "user: Teodor Brandt rang, and so did Teo.\nspeaker:Odile: Teodor Brandt is Teo's father, you know.\n")
    _commit(memory, "meeting")
    judge = _judge(_one("and so did Teo.\nspeaker:Odile: Teodor Brandt is Teo's father"))
    assert _tend(memory, judge).joined == 0


def test_the_words_that_carry_both_names_are_the_words_that_were_located(memory):
    real = ("Teo and I talked for a long time about everything under the sun, from football to robots to the weather, "
            "and the long road trip we took last summer through the mountains, the rivers, the lakes and the villages. ")
    assert len(real) > 200
    turn = real + "Then I met Teodor Brandt's wife at the bar."
    # the quote's first 240 characters are real; an invented tail carries the full name beside the short one
    assert _joined_with(memory, turn, real + " Teodor Brandt, my old teammate, is the same as Teo.") == 0


def test_a_quote_longer_than_the_evidence_cap_is_refused_even_when_every_word_is_there(memory):
    from api.services import evidence

    turn = "Teodor Brandt, " + "who everybody calls Teo, " * 12 + "is leaving the team."
    assert len(turn) > evidence.MAX_QUOTE_CHARS
    assert _joined_with(memory, turn, turn) == 0


def test_a_page_that_already_carries_another_full_name_is_not_a_join_for_sleep(memory):
    _world(memory)
    page = markdown_parser.parse(memory / "entities" / "teo.md")
    markdown_parser.write(memory / "entities" / "teo.md", {**page.frontmatter, "aliases": ["Teodor Marchetti"]}, page.body)
    _commit(memory, "alias")
    judge = _judge(_one())
    report = _tend(memory, judge)
    assert report.joined == 0 and judge.calls == [] and report.skipped.get("page_is_someone_in_full") == 1


def test_a_second_full_name_never_joins_the_page_the_first_one_joined(memory):
    _world(memory)
    _episode(memory, "ep_2026-10-05_001", "user: Saw Teo again. Matteo Rossi, my cousin, is visiting.\nassistant: ok\n")
    _held(memory, "Matteo Rossi", "ep_2026-10-05_001", "Saw Teo again. Matteo Rossi, my cousin, is visiting.", aliases=("Matt",))
    _question(memory, 2, "Matteo Rossi", "teo", "Teo", "ep_2026-10-05_001")
    _commit(memory, "second")

    def answer(prompt):
        mine = "Matteo Rossi" in prompt.split("FULL NAME:")[1][:30]
        return _one("Saw Teo again. Matteo Rossi, my cousin, is visiting." if mine else
                    "Had lunch with Teo today. Teodor Brandt, my old teammate from university.")

    report = _tend(memory, _judge(answer))
    assert report.joined == 1 and report.skipped.get("page_is_someone_in_full") == 1
    assert markdown_parser.parse(memory / "entities" / "teo.md").frontmatter["aliases"] == ["Teodor Brandt"]
    assert (memory / "inbox" / "inbox-002.md").is_file()


def test_the_prompt_shows_every_name_the_page_goes_by(memory):
    _world(memory)
    page = markdown_parser.parse(memory / "entities" / "teo.md")
    markdown_parser.write(memory / "entities" / "teo.md", {**page.frontmatter, "aliases": ["Teddy"]}, page.body)
    _commit(memory, "alias")
    judge = _judge({"verdict": "two"})
    _tend(memory, judge)
    assert "Teddy" in judge.calls[0]


def test_every_turn_naming_both_is_shown_and_more_than_the_bound_is_no_join(memory):
    _world(memory)
    line = pending_store.held_line(memory, "Teodor Brandt")
    eps = []
    for n in range(2, 9):
        eid = f"ep_2026-10-0{n}_00{n}"
        eps.append(eid)
        body = ("user: Teodor Brandt, also called Teo, mailed me again.\\nassistant: ok\\n" if n < 6 else
                "user: Careful: Teodor Brandt is NOT Teo. Teodor Brandt is Teo's uncle, a different man.\\nassistant: noted\\n")
        _episode(memory, eid, body.replace("\\\\n", "\\n"))
    line.heard_in = [{"episode": e, "timestamp": "2026-10-05T09:00:00+00:00", "day": "2026-10-05"} for e in ["ep_2026-10-03_001", *eps]]
    pending_store.upsert(memory, line)
    _commit(memory, "many turns")
    judge = _judge(_one())
    report = _tend(memory, judge)
    assert report.joined == 0 and judge.calls == [] and report.skipped.get("too_many_turns") == 1
    # within the bound every one is shown, the denial included
    for eid in eps[:2]:
        (memory / "episodes" / f"{eid}.md").unlink()
    line = pending_store.held_line(memory, "Teodor Brandt")
    line.heard_in = [{"episode": e, "timestamp": "2026-10-05T09:00:00+00:00", "day": "2026-10-05"} for e in ["ep_2026-10-03_001", *eps[2:]]]
    pending_store.upsert(memory, line)
    _commit(memory, "fewer")
    judge = _judge({"verdict": "two"})
    _tend(memory, judge)
    assert judge.calls and "NOT Teo" in judge.calls[0]


def test_a_change_while_the_model_reads_leaves_the_question(memory):
    _world(memory)
    state = {"n": 0}

    async def judge(system, prompt):
        state["n"] += 1
        if state["n"] == 2:
            page = markdown_parser.parse(memory / "entities" / "teo.md")
            markdown_parser.write(memory / "entities" / "teo.md", page.frontmatter, page.body + "\n- Teo is Odile Brandt's son.\n")
            bank_index.invalidate(memory)
        return _one()

    assert _tend(memory, judge).joined == 0 and (memory / "inbox" / "inbox-001.md").is_file()


def test_a_conversation_the_held_line_was_not_heard_in_is_never_read(memory):
    _world(memory, turn="Teodor Brandt wrote to me.")
    _episode(memory, "ep_2026-11-20_001", f"user: {APPOSITION}\nassistant: ok\n")
    path = memory / "inbox" / "inbox-001.md"
    page = markdown_parser.parse(path)
    markdown_parser.write(path, {**page.frontmatter, "source_episode": "ep_2026-11-20_001"}, page.body)
    _commit(memory, "source")
    judge = _judge(_one())
    report = _tend(memory, judge)
    assert report.joined == 0 and judge.calls == [] and report.skipped.get("no_turn_names_both") == 1


def test_a_settle_that_cannot_apply_is_tried_twice_not_every_drain(memory, monkeypatch):
    _world(memory)

    async def refuse(memory_path, settings, d, **kw):
        return False

    monkeypatch.setattr(inbox_tend, "apply", refuse)
    judge = _judge(_one())
    for _ in range(4):
        _tend(memory, judge)
    assert len(judge.calls) == 4, "two drains of two reads, then nothing"


def test_a_page_of_any_type_called_the_short_name_blocks(memory):
    _world(memory)
    _page(memory, "teo-s-pizza", "Teo's Pizza", type_="company", aliases=["Teo"])
    _commit(memory)
    _blocked(memory, "short_name_not_alone")


def test_the_judging_model_is_the_author_when_the_engine_says_which_answered_and_cicada_otherwise(memory):
    _world(memory)
    answer = {**_one(), "_model": "claude-sonnet-5-5"}
    assert _tend(memory, _judge(answer)).joined == 1
    assert "Cicada-Author: claude-sonnet-5-5" in _git(memory, "log", "-1", "--format=%B")


def test_a_line_the_person_quoted_from_someone_else_is_no_join(memory):
    turn = "Look what Odile forwarded me:\n> Hi all, Teodor Brandt, who everybody calls Teo, is leaving the team.\nWhat do I reply?"
    assert _joined_with(memory, turn, "Teodor Brandt, who everybody calls Teo, is leaving the team.") == 0


def test_a_short_name_that_is_a_common_word_must_be_written_as_the_record_writes_it(memory):
    """"Will" the page against "will" the verb in "I will see Will Marsh tomorrow": the short name has to appear as the page
    spells it (case kept), outside the full name; no model is asked when only the verb does."""
    _episode(memory, "ep_2026-10-03_001", "user: I will see Will Marsh tomorrow.\nassistant: ok\n")
    _episode(memory, "ep_2026-10-22_001", "user: Will asked about the rota.\nassistant: ok\n")
    _page(memory, "will", "Will", source_episodes=["ep_2026-10-22_001"])
    _held(memory, "Will Marsh", "ep_2026-10-03_001", "I will see Will Marsh tomorrow.", aliases=("Will",))
    _question(memory, 1, "Will Marsh", "will", "Will", "ep_2026-10-03_001")
    _commit(memory, "will")
    judge = _judge(_one("I will see Will Marsh tomorrow."))
    report = _tend(memory, judge)
    assert report.joined == 0 and judge.calls == [] and report.skipped.get("no_turn_names_both") == 1
    assert full_name_join.names_both(["teodor brandt"], ["teo"], "Teodor Brandt (Téo)", frozenset({"Teo"}))
    assert not full_name_join.names_both(["teodor brandt"], ["teo"], "Teodor Brandt (TEO)", frozenset({"Teo"}))


def test_nothing_holds_the_page_lock_or_the_write_admission_across_a_model_call(memory):
    """The rail: never held across a model call. The reads run with the page lock and the admission both free (the tail
    runs inside Sleep's own window, which is its flag, not a hold of this step)."""
    from api.services import page_lock, write_admission

    _world(memory)
    seen: list[tuple[bool, bool]] = []

    async def judge(system, prompt):
        seen.append((page_lock.held(memory), write_admission._bank(write_admission._key(memory)).holders > 0))
        return _one()

    assert _tend(memory, judge).joined == 1
    assert seen == [(False, False), (False, False)]
