"""Sleep reads "Is <name> the same as <page>?" again when the name has no page (`name_revisit`, ruling 82, 2026-11-24).

Synthetic banks only (invented names, a fake judge, real git). The engine is injected; nothing reaches a network. The bar is
zero wrong landings with a judge rigged to answer "same" to everything: what stops one is in code."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from datetime import date
from pathlib import Path

import pytest

from api.services import (bank_index, inbox_tend, markdown_parser, merge_rejections, name_revisit, pending_store, predicates,
                          question_revisit as qr)
from api.services.claims import Claim, parse_claims, write_claims


def run(coro):
    return asyncio.run(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _commit(memory: Path, msg: str = "seed") -> None:
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "--allow-empty", "-m", msg)
    bank_index.invalidate(memory)


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90
        self.llm_mode = "byok"


def _page(memory: Path, pid: str, name: str, body: str, **fm) -> None:
    meta = {"name": name, "type": "project", "status": "active", "confidence": 0.8, "created": "2026-10-01",
            "last_referenced": "2026-11-14", "source_episodes": [], "related": [], "version": 1, **fm}
    markdown_parser.write(memory / "entities" / f"{pid}.md", meta, body)


def _episode(memory: Path, eid: str, text: str) -> None:
    markdown_parser.write(memory / "episodes" / f"{eid}.md", {"id": eid, "timestamp": f"{eid[3:13]}T10:00:00+00:00", "processed": True,
                                                              "title": "chat", "source": "claude-code"}, text)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(inbox_tend, "_RECORD_READ", {})
    monkeypatch.setattr("api.services.pair_evidence.FRESH_S", 0.0)
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    _page(m, "owner-example", "Owner Example", "## Summary\nThe owner.\n", type="person", owner=True)
    _commit(m)
    return m


FACT = "Quartzline is the scheduling service the team deploys on Fridays."


def _target(memory: Path, **fm) -> None:
    _episode(memory, "ep_2026-10-01_001", f"user: {FACT}\nassistant: Noted.\n")
    _page(memory, "quartzline", "Quartzline", f"## Summary\n{FACT}\n\n## Key Facts\n- {FACT}\n", source_episodes=["ep_2026-10-01_001"], **fm)


def _hold(memory: Path, name: str, episode: str, text: str, *, type_: str = "concept", claims: list | None = None) -> None:
    held = claims if claims is not None else []
    pending_store.upsert(memory, pending_store.PendingEntity(
        name=name, type=type_, description=text, source_episode=episode, confidence=0.4, tags=[],
        history_entries=[{"date": "2026-11-14", "event": text}], held_claims=[c.to_dict() for c in held], aliases=[],
        summary=text, key_facts=[text]))


_NUM = [0]


def _ask(memory: Path, name: str, episode: str, *, target: str = "quartzline", classification: str = "concept") -> Path:
    _NUM[0] += 1
    path = memory / "inbox" / f"inbox-{_NUM[0]:03d}.md"
    markdown_parser.write(path, {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.6, "entity_id": name.lower().replace(" ", "-"),
        "entity_name": name, "title": f"Is {name} the same as Quartzline?", "created_date": "2026-11-01", "merge_target_hint": target,
        "suggested_classification": classification, "source_episode": episode, "held_mention": True},
        "They may be one thing; asked, never joined: only your answer joins them.")
    return path


def _world(memory: Path, name: str, turn: str, *, held: str | None = None, claims: list | None = None) -> Path:
    """The page "Quartzline"; the name ``name`` said once in a conversation (``turn`` is the person's line), held on a line."""
    _target(memory)
    ep = "ep_2026-11-14_001"
    _episode(memory, ep, f"user: {turn}\nassistant: Ok.\n")
    _hold(memory, name, ep, held or f"{name} is mentioned in a planning call.", claims=claims)
    path = _ask(memory, name, ep)
    _commit(memory, "world")
    return path


def _judge(*replies, calls: list | None = None):
    """The engine's blocking call (`question_revisit.tend` takes an ``llm_fn``); a reply may be a function of the prompt."""
    queue = list(replies)

    def fn(messages, **_kw):
        prompt = "\n".join(str(m["content"]) for m in messages)
        if calls is not None:
            calls.append(prompt)
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        reply = reply(prompt) if callable(reply) else reply
        return {"choices": [{"message": {"content": json.dumps(reply)}}], "model": "fake-main"}

    return fn


def _same(said: str, n: int = 1, **more) -> dict:
    return {"answers": [{"name": n, "verdict": "same", "said": said, "reason": "r", **more}]}


def _different(line: str, n: int = 1, relation: str = "part") -> dict:
    return {"answers": [{"name": n, "verdict": "different", "relation": relation, "line": line, "reason": "r"}]}


def _look(memory: Path, judge, *, dry_run: bool = False, max_reads: int = 8):
    rows: list[dict] = []
    report = run(qr.tend(memory, _Settings(memory), judge, today=date(2026, 11, 24), dry_run=dry_run, trace=rows.append, model="fake-main",
                         max_reads=max_reads))
    return report, rows


def _open(memory: Path) -> list[str]:
    return sorted(p.stem for p in (memory / "inbox").glob("inbox-*.md"))


def _aliases(memory: Path) -> list[str]:
    return list(markdown_parser.parse(memory / "entities" / "quartzline.md").frontmatter.get("aliases") or [])


# --------------------------------------------------------------------------- the code's reading of a line


@pytest.mark.parametrize("line", [
    "QL, also called Quartzline, is the one I deploy",
    "Quartzline (QL) is the one I deploy",
    "I call it QL, short for Quartzline",
    "QL is Quartzline",
    "QL, también llamado Quartzline",
])
def test_a_line_that_says_the_two_names_are_one_thing_is_linked(line):
    assert name_revisit.linked(line, ["QL"], ["Quartzline"])


@pytest.mark.parametrize("line", [
    "QL and Quartzline are both on the board",
    "QL deploys with Quartzline every Friday",
    "QL replaced Quartzline last spring",
    "QL, Quartzline, Harbor are the three services",
    "QL uses Quartzline",
    "Quartzline is slow. QL is fine",
    "QL runs inside Quartzline",
    "QL is not Quartzline",
    "QL\nQuartzline",
    "Quartzline backend, Quartzline",
])
def test_a_line_that_relates_them_any_other_way_is_not_linked(line):
    names = (["Quartzline backend"] if "backend" in line else ["QL"], ["Quartzline"])
    assert not name_revisit.linked(line, *names)


def test_the_shape_of_two_names():
    assert name_revisit.shape(["Quartzline backend"], ["Quartzline"]) == "nested"
    assert name_revisit.shape(["Quartzline"], ["Quartzline backend"]) == "nested"
    assert name_revisit.shape(["Quartzline Web"], ["Quartzline API"]) == "shares"
    assert name_revisit.shape(["QL"], ["Quartzline"]) == "apart"


# --------------------------------------------------------------------------- the same thing


def test_a_name_the_person_calls_the_page_joins_it_as_an_undoable_settle_and_what_is_held_lands(memory):
    claim = Claim(id="clm_2026-11-14_aaaa1111", text="QL runs the Friday deploy", subject="ql", predicate="runs", object="friday deploy",
                  object_kind="literal", source_episodes=["ep_2026-11-14_001"])
    path = _world(memory, "QL", "QL, also called Quartzline, is the thing I deploy on Fridays.", claims=[claim])
    calls: list = []
    report, rows = _look(memory, _judge(_same("QL, also called Quartzline, is the thing I deploy on Fridays."), calls=calls))
    assert report.settled == 1 and report.read == 1 and report.calls == 2
    assert len(calls) == 2 and "sceptical reader" in calls[1] and "sceptical reader" not in calls[0]
    assert _open(memory) == [] and "QL" in _aliases(memory)
    assert "Friday deploy" in (memory / "entities" / "quartzline.md").read_text() or "QL runs the Friday deploy" in (memory / "entities" / "quartzline.md").read_text()
    settled = (memory / "inbox" / "settled" / f"{path.stem}.md")
    rec = markdown_parser.parse(settled).frontmatter["settled"]
    assert rec["rule"] == "revisit_same" and rec["evidence_spans"][0]["kind"] == "user"
    assert [r["what"] for r in rows] == ["joined"] and rows[0]["kind"] == "name_no_page" and rows[0]["rule"] == "revisit_same"
    assert "ep_2026-11-14_001" in {s["episode"] for s in rows[0]["evidence"]}
    # Undo is the person saying they are two: the alias goes, what was held is back, and nothing asks or joins again.
    inbox_tend.undo(memory, path.stem)
    assert _aliases(memory) == [] and _open(memory) == []
    back = pending_store.held_line(memory, "QL")
    assert back is not None and back.held_claims and "quartzline" in back.apart_pages()


def test_a_rigged_judge_that_always_says_same_lands_nothing_on_a_part_a_sibling_or_an_unrelated_name(memory):
    # The part: "<Page> backend" (its name holds the page's), the sibling (shares a word), the unrelated (shares a word), and
    # a name no turn of the person's links to the page. Every one's best line for a judge that answers "same" to everything.
    _target(memory)
    cases = {
        "Quartzline backend": "The Quartzline backend deploys with Quartzline on Fridays.",
        "Quartzline Web": "Quartzline Web, Quartzline are the two things we ship.",
        "Quartz Garden": "My Quartz Garden uses Quartzline for its schedule.",
        "Harbor": "Harbor is slow and Quartzline is fine.",
    }
    paths = []
    for i, (name, turn) in enumerate(cases.items(), 1):
        ep = f"ep_2026-11-1{i}_001"
        _episode(memory, ep, f"user: {turn}\nassistant: Ok.\n")
        _hold(memory, name, ep, f"{name} is mentioned in a planning call.")
        paths.append(_ask(memory, name, ep))
    _commit(memory, "world")

    def rigged(prompt: str) -> dict:
        answers = []
        for k, name in enumerate(cases, 1):
            turn = cases[name]
            answers.append({"name": k, "verdict": "same", "said_turn": 1, "said": turn, "here": turn, "there": FACT, "reason": "same"})
        return {"answers": answers}

    report, rows = _look(memory, _judge(rigged))
    assert report.settled == 0 and _aliases(memory) == []
    assert len(_open(memory)) == 4
    assert all(pending_store.held_line(memory, n) is not None for n in cases)
    assert all(not r["what"].startswith(("joined", "closed")) for r in rows)


def test_an_assistants_line_and_an_unlocatable_quote_are_never_the_evidence(memory):
    _target(memory)
    _episode(memory, "ep_2026-11-14_001", "user: Planning call today.\nassistant: QL, also called Quartzline, is the deploy tool.\n")
    _hold(memory, "QL", "ep_2026-11-14_001", "QL is mentioned in a planning call.")
    _ask(memory, "QL", "ep_2026-11-14_001")
    _commit(memory, "world")
    said = "QL, also called Quartzline, is the deploy tool."
    report, _ = _look(memory, _judge(_same(said)))
    assert report.settled == 0 and _aliases(memory) == []
    report, _ = _look(memory, _judge(_same("QL, also known as Quartzline, runs the deploy tool.")))
    assert report.settled == 0 and _aliases(memory) == []


def test_a_sibling_shape_needs_a_shared_fact_besides_the_line(memory):
    # "Quartzline Web" is "also called" Quartzline API by the person: the names share a word, so one located line is not enough.
    _target(memory)
    _page(memory, "quartzline-api", "Quartzline API", "## Summary\nQuartzline API is the scheduling service.\n", source_episodes=["ep_2026-10-01_001"])
    turn = "Quartzline Web, also called Quartzline API, is the thing I deploy."
    _episode(memory, "ep_2026-11-14_001", f"user: {turn}\nassistant: Ok.\n")
    _hold(memory, "Quartzline Web", "ep_2026-11-14_001", "Quartzline Web is mentioned in a planning call.")
    _ask(memory, "Quartzline Web", "ep_2026-11-14_001", target="quartzline-api")
    _commit(memory, "world")
    report, _ = _look(memory, _judge(_same(turn)))
    assert report.settled == 0 and not any("Quartzline Web" in str(a) for a in markdown_parser.parse(
        memory / "entities" / "quartzline-api.md").frontmatter.get("aliases") or [])


def test_a_claim_that_already_relates_them_as_two_blocks_a_join(memory):
    claim = Claim(id="clm_2026-11-14_aaaa1111", text="QL is part of Quartzline", subject="ql", predicate="part-of", object="quartzline",
                  object_kind="node", source_episodes=["ep_2026-11-14_001"])
    turn = "QL, also called Quartzline, is the thing I deploy on Fridays."
    _world(memory, "QL", turn, claims=[claim])
    report, _ = _look(memory, _judge(_same(turn)))
    assert report.settled == 0 and _aliases(memory) == []


@pytest.mark.parametrize("setup,why", [
    ("removed", "alias_removed"),
    ("rejected", "kept_apart"),
    ("apart", "said_apart"),
    ("title", "name_of_a_page"),
    ("alias", "name_of_a_page"),
    ("reference", "not_a_name"),
])
def test_what_the_person_or_the_record_refused_is_never_read(memory, setup, why):
    name = "the ql" if setup == "reference" else "QL"
    path = _world(memory, name, f"{name}, also called Quartzline, is the thing I deploy.")
    if setup == "removed":
        fm = dict(markdown_parser.parse(memory / "entities" / "quartzline.md").frontmatter)
        markdown_parser.write(memory / "entities" / "quartzline.md", {**fm, "aliases_removed": ["QL"]}, "## Summary\n" + FACT + "\n")
    elif setup == "rejected":
        merge_rejections.add_rejected(memory, "ql", "quartzline")
    elif setup == "apart":
        pending_store.mark_apart(memory, name, ["quartzline"], [])
    elif setup == "title":
        _page(memory, "ql-tool", "QL", "## Summary\nA different QL.\n")
    elif setup == "alias":
        _page(memory, "other-thing", "Other Thing", "## Summary\nx\n", aliases=["QL"], type="concept")
    _commit(memory, "setup")
    fm = dict(markdown_parser.parse(path).frontmatter)
    case, got = name_revisit.name_case(memory, path, fm)
    assert case is None and got == why


# --------------------------------------------------------------------------- not the same thing


def test_a_part_is_closed_as_the_persons_no_would_close_it_and_nothing_lands(memory):
    claim = Claim(id="clm_2026-11-14_aaaa1111", text="The backend uses Redis", subject="quartzline-backend", predicate="uses",
                  object="redis", object_kind="literal", source_episodes=["ep_2026-11-14_001"])
    line = "The Quartzline backend is the Python service behind the dashboard."
    path = _world(memory, "Quartzline backend", line, claims=[claim])
    report, rows = _look(memory, _judge(_different(line)))
    assert report.settled == 1 and report.calls == 2
    assert _open(memory) == [] and _aliases(memory) == []
    held = pending_store.held_line(memory, "Quartzline backend")
    assert held is not None and held.held_claims and "quartzline" in held.apart_pages()   # held under its own name, kept apart
    assert "Redis" not in (memory / "entities" / "quartzline.md").read_text()
    rec = markdown_parser.parse(memory / "inbox" / "settled" / f"{path.stem}.md").frontmatter["settled"]
    assert rec["rule"] == "revisit_apart" and rec["answer"] == "Not the same as Quartzline"
    assert [r["what"] for r in rows] == ["closed_apart"]
    # The same question is not raised again for those conversations, and taking the close back reopens it for the person.
    assert "quartzline" in pending_store.apart_of(memory, "Quartzline backend")
    inbox_tend.undo(memory, path.stem)
    assert _open(memory) == [path.stem]
    assert not pending_store.held_line(memory, "Quartzline backend").apart_pages()


def test_a_name_is_never_closed_apart_when_the_persons_own_line_presents_them_as_one(memory):
    turn = "QL, also called Quartzline, is the thing I deploy on Fridays."
    _world(memory, "QL", turn)
    report, _ = _look(memory, _judge(_different("QL, also called Quartzline, is the thing I deploy on Fridays.")))
    assert report.settled == 0 and len(_open(memory)) == 1


def test_a_difference_the_second_read_does_not_confirm_stays_open(memory):
    line = "The Quartzline backend is the Python service behind the dashboard."
    _world(memory, "Quartzline backend", line)
    report, _ = _look(memory, _judge(_different(line), {"answers": [{"name": 1, "verdict": "cannot_tell", "reason": "r"}]}))
    assert report.settled == 0 and len(_open(memory)) == 1


def test_a_line_that_is_not_in_the_record_closes_nothing(memory):
    _world(memory, "Quartzline backend", "The Quartzline backend is the Python service behind the dashboard.")
    report, _ = _look(memory, _judge(_different("The Quartzline backend is a Rust service somewhere else.")))
    assert report.settled == 0 and len(_open(memory)) == 1


# --------------------------------------------------------------------------- a person, one page, many questions


def test_a_person_is_read_under_the_person_rules_and_a_short_name_another_could_be_is_left(memory):
    _episode(memory, "ep_2026-10-01_001", "user: Teodor Brandt starts on Monday.\nassistant: Noted.\n")
    _page(memory, "teodor-brandt", "Teodor Brandt", "## Summary\nTeodor Brandt starts on the platform team.\n", type="person",
          source_episodes=["ep_2026-10-01_001"])
    _page(memory, "teo-vance", "Teo Vance", "## Summary\nTeo Vance, a neighbour.\n", type="person")
    turn = "Teo, called Teodor Brandt, starts on the platform team."
    _episode(memory, "ep_2026-11-14_001", f"user: {turn}\nassistant: Ok.\n")
    _hold(memory, "Teo", "ep_2026-11-14_001", "Teo starts on the platform team.", type_="person")
    path = _ask(memory, "Teo", "ep_2026-11-14_001", target="teodor-brandt", classification="person")
    _commit(memory, "world")
    case, why = name_revisit.name_case(memory, path, dict(markdown_parser.parse(path).frontmatter))
    assert case is None and why == "short_name_not_alone"


def test_a_person_and_a_thing_is_left(memory):
    _world(memory, "QL", "QL, also called Quartzline, is the thing I deploy.")
    path = next((memory / "inbox").glob("inbox-*.md"))
    fm = {**markdown_parser.parse(path).frontmatter, "suggested_classification": "person"}
    markdown_parser.write(path, fm, "x")
    pending = pending_store.load(memory)
    pending[0].type = "person"
    pending_store.save(memory, pending)
    case, why = name_revisit.name_case(memory, path, dict(fm))
    assert case is None and why == "person_and_a_thing"


def test_a_pile_on_one_page_is_read_in_one_call_pair_and_each_answer_stays_with_its_own_name(memory):
    _target(memory)
    names = {"QL": "QL, also called Quartzline, is the thing I deploy on Fridays.",
             "Quartzline backend": "The Quartzline backend is the Python service behind the dashboard.",
             "Harbor": "Harbor is the nightly export job I wrote."}
    for i, (name, turn) in enumerate(names.items(), 1):
        ep = f"ep_2026-11-1{i}_001"
        _episode(memory, ep, f"user: {turn}\nassistant: Ok.\n")
        _hold(memory, name, ep, f"{name} is mentioned in a planning call.")
        _ask(memory, name, ep)
    _commit(memory, "world")
    calls: list = []

    def reply(prompt: str) -> dict:
        # The first read shows all three; the sceptic reads show only the names the first settled, renumbered. The reader answers
        # for whichever it is shown: "same" for QL, a part for the backend, an unrelated name for Harbor.
        says = {"QL": {"verdict": "same", "said": names["QL"]},
                "Quartzline backend": {"verdict": "different", "relation": "part", "line": names["Quartzline backend"]},
                "Harbor": {"verdict": "different", "relation": "unrelated", "line": names["Harbor"]}}
        found = [(int(k), n) for k, n in re.findall(r'NAME (\d+): "([^"]+)"', prompt)]
        return {"answers": [{"name": k, "reason": "r", **says[n]} for k, n in found]}

    report, rows = _look(memory, _judge(reply, calls=calls))
    assert len(calls) == 3 and report.calls == 3          # one call for the three, one for the same, one for the two different
    assert report.read == 3 and report.settled == 3
    assert _open(memory) == [] and _aliases(memory) == ["QL"]
    assert sorted(r["what"] for r in rows) == ["closed_apart", "closed_apart", "joined"]


def test_an_answer_about_another_number_or_with_another_names_line_settles_nothing(memory):
    _target(memory)
    ql = "QL, also called Quartzline, is the thing I deploy on Fridays."
    for i, name in enumerate(("QL", "Harbor"), 1):
        ep = f"ep_2026-11-1{i}_001"
        _episode(memory, ep, f"user: {ql if name == 'QL' else 'Harbor is the nightly export job I wrote.'}\nassistant: Ok.\n")
        _hold(memory, name, ep, f"{name} is mentioned in a planning call.")
        _ask(memory, name, ep)
    _commit(memory, "world")

    def borrowed(prompt: str) -> dict:
        k = 1 if 'NAME 1: "Harbor"' in prompt else 2     # Harbor claims QL's line as its own
        return {"answers": [{"name": k, "verdict": "same", "said": ql, "reason": "r"}]}

    report, _ = _look(memory, _judge(borrowed))
    assert report.settled == 0 and _aliases(memory) == []


# --------------------------------------------------------------------------- the step's bounds


def test_a_question_read_is_remembered_and_not_read_again_until_something_changes(memory):
    line = "The Quartzline backend is the Python service behind the dashboard."
    _world(memory, "Quartzline backend", line)
    calls: list = []
    judge = _judge({"answers": [{"name": 1, "verdict": "cannot_tell", "reason": "r"}]}, calls=calls)
    _look(memory, judge)
    assert len(calls) == 1
    report, rows = _look(memory, judge)
    assert len(calls) == 1 and [r["what"] for r in rows] == ["left:read_already"]


def test_the_dry_run_lists_what_it_would_do_and_writes_nothing(memory):
    turn = "QL, also called Quartzline, is the thing I deploy on Fridays."
    _world(memory, "QL", turn)
    head = _git(memory, "rev-parse", "HEAD")
    report, rows = _look(memory, _judge(_same(turn)), dry_run=True)
    assert [r["what"] for r in rows] == ["would_join"] and rows[0]["rule"] == "revisit_same"
    assert report.settled == 1 and _git(memory, "rev-parse", "HEAD") == head and len(_open(memory)) == 1
    _, rows = _look(memory, None, dry_run=True)
    assert [r["what"] for r in rows] == ["would_read"]


def test_a_question_the_person_undid_or_put_off_is_theirs(memory):
    turn = "QL, also called Quartzline, is the thing I deploy on Fridays."
    path = _world(memory, "QL", turn)
    fm = dict(markdown_parser.parse(path).frontmatter)
    markdown_parser.write(path, {**fm, inbox_tend.UNDONE_KEY: "undone"}, "x")
    _commit(memory, "undone")
    calls: list = []
    report, rows = _look(memory, _judge(_same(turn), calls=calls))
    assert calls == [] and rows == []
