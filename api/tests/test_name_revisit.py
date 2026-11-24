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


# --------------------------------------------------------------------------- review round: lines that are not a statement of identity

#: Lines that hold the two names and are NOT the person saying they are one thing (a part, a denial, a doubt, a question, a
#: member of a list, a kind). Invented names; `{N}` is the asked name.
NOT_ONE = [
    "{N} is Quartzline's backend.",
    "{N} is Quartzline? No. {N} is not Quartzline.",
    "I don't think {N} is Quartzline.",
    "Is {N} also Quartzline?",
    "If {N} is Quartzline then we ship.",
    "{N} is a Quartzline.",
    "{N} is for Quartzline.",
    "{N} es como Quartzline.",
    "{N}, also Quartzline, are both due Friday.",
    "{N} is the Quartzline.",
    "{N} is my Quartzline.",
    "Tools like {N} (Quartzline) are common.",
    "{N} is Quartzline backend.",
    "{N} is Quartzline, maybe.",
    "Creo que {N} es Quartzline.",
    "{N}, aka Quartzline and Harbor, ship on Fridays.",
    "{N}, also called Quartzline of the north, ships on Fridays.",
]
ONE = [
    "{N} is Quartzline.",
    "{N}, also called Quartzline, is the thing I deploy on Fridays.",
    "{N} aka Quartzline",
    "{N} is just Quartzline",
    "Quartzline (aka {N}) is the thing I deploy",
    "{N}, short for Quartzline, runs the Friday deploys.",
    "{N}, también llamado Quartzline",
    "I call it {N}, short for Quartzline",
]


@pytest.mark.parametrize("line", NOT_ONE)
def test_the_code_refuses_every_line_that_is_not_a_statement_of_identity(line):
    assert not name_revisit.linked(line.format(N="Kestrel"), ["Kestrel"], ["Quartzline"])
    assert not name_revisit.linked(line.format(N="Kestrel"), ["Quartzline"], ["Kestrel"])


@pytest.mark.parametrize("line", ONE)
def test_a_plain_statement_of_identity_is_linked(line):
    assert name_revisit.linked(line.format(N="Kestrel"), ["Kestrel"], ["Quartzline"])


def test_a_denial_or_a_list_in_another_sentence_of_the_turn_blocks_the_line_that_says_one():
    both = "Kestrel, also called Quartzline, is the thing I deploy. Kestrel and Quartzline are not the same."
    assert not name_revisit.linked(both, ["Kestrel"], ["Quartzline"])
    assert name_revisit.linked("Kestrel, also called Quartzline, is the thing I deploy. It runs on Fridays.", ["Kestrel"], ["Quartzline"])


@pytest.mark.parametrize("line", NOT_ONE)
def test_a_judge_that_always_says_same_joins_nothing_on_the_reviewers_lines(memory, line):
    turn = line.format(N="Kestrel")
    _world(memory, "Kestrel", turn)
    report, _ = _look(memory, _judge(_same(turn)))
    assert report.settled == 0 and _aliases(memory) == [] and len(_open(memory)) == 1
    assert pending_store.held_line(memory, "Kestrel") is not None


def test_another_turn_that_relates_them_as_two_blocks_a_join_the_first_turn_would_allow(memory):
    _target(memory)
    for i, turn in enumerate(("Kestrel, also called Quartzline, is the thing I deploy.", "Kestrel deploys with Quartzline on Fridays."), 1):
        _episode(memory, f"ep_2026-11-1{i}_001", f"user: {turn}\nassistant: Ok.\n")
    _hold(memory, "Kestrel", "ep_2026-11-11_001", "Kestrel came up in a planning call.")
    _ask(memory, "Kestrel", "ep_2026-11-11_001")
    _commit(memory, "world")
    report, _ = _look(memory, _judge(_same("Kestrel, also called Quartzline, is the thing I deploy.")))
    assert report.settled == 0 and _aliases(memory) == []


# --------------------------------------------------------------------------- review round: a "different" close is never on the model's say-so


def test_a_different_quoting_only_the_held_text_closes_nothing_and_a_turn_with_both_names_blocks_the_close(memory):
    turn = "Swift, I mean Quartzline, is the thing we deploy on Fridays."
    _world(memory, "Swift", turn, held="Swift is mentioned in a planning call.")
    report, _ = _look(memory, _judge(_different("Swift is mentioned in a planning call.", relation="unrelated")))
    assert report.settled == 0 and len(_open(memory)) == 1               # the held line's own text is no evidence
    report, _ = _look(memory, _judge(_different(turn, relation="unrelated")))
    assert report.settled == 0 and len(_open(memory)) == 1               # the person put both names in one sentence


def test_a_line_an_assistant_said_is_not_a_located_difference(memory):
    _target(memory)
    _episode(memory, "ep_2026-11-14_001", "user: Planning call today.\nassistant: Harbor is the nightly export job the user wrote.\n")
    _hold(memory, "Harbor", "ep_2026-11-14_001", "Harbor is mentioned in a planning call.")
    _ask(memory, "Harbor", "ep_2026-11-14_001")
    _commit(memory, "world")
    report, _ = _look(memory, _judge(_different("Harbor is the nightly export job the user wrote.", relation="unrelated")))
    assert report.settled == 0 and len(_open(memory)) == 1


# --------------------------------------------------------------------------- review round: names a page shares, common nouns, shapes


def test_a_name_two_pages_answer_to_is_no_name_of_the_page(memory):
    _target(memory, aliases=["scheduler"])
    _page(memory, "harbor-cron", "Harbor Cron", "## Summary\nA cron wrapper.\n", aliases=["scheduler"], type="tool")
    turn = "Teal, also called scheduler, is the thing I deploy on Fridays."
    _episode(memory, "ep_2026-11-14_001", f"user: {turn}\nassistant: Ok.\n")
    _hold(memory, "Teal", "ep_2026-11-14_001", "Teal came up in a planning call.")
    _ask(memory, "Teal", "ep_2026-11-14_001")
    _commit(memory, "world")
    report, _ = _look(memory, _judge(_same(turn)))
    assert report.settled == 0 and "Teal" not in _aliases(memory)
    # The same line about a name only this page answers to is read (and joins).
    _page(memory, "harbor-cron", "Harbor Cron", "## Summary\nA cron wrapper.\n", aliases=[], type="tool")
    _commit(memory, "one page")
    report, _ = _look(memory, _judge(_same(turn)))
    assert report.settled == 1 and "Teal" in _aliases(memory)


def test_a_one_word_alias_the_conversation_uses_as_a_common_noun_is_no_name_of_the_page(memory):
    turn = "Teal, also called the scheduler, is the thing I deploy on Fridays."
    path = _world(memory, "Teal", turn)
    _target(memory, aliases=["scheduler"])
    _commit(memory, "alias")
    fm = dict(markdown_parser.parse(path).frontmatter)
    case, _why = name_revisit.name_case(memory, path, fm)
    assert case is not None and "scheduler" not in case.b.names and "Quartzline" in case.b.names
    report, _ = _look(memory, _judge(_same(turn)))
    assert report.settled == 0 and _aliases(memory) == ["scheduler"]


def test_the_shape_ignores_length_and_plurals():
    assert name_revisit.shape(["Ox 11"], ["Ox 12"]) == "shares"
    assert name_revisit.shape(["Phone 11"], ["Tablet 11"]) == "shares"
    assert name_revisit.shape(["Quartzline Tools"], ["Quartzline Tool"]) == "nested"
    assert name_revisit.shape(["Tern-4"], ["Tern 5"]) == "shares"
    assert name_revisit.shape(["Quartzline"], ["Harbor Lights"]) == "apart"


# --------------------------------------------------------------------------- review round: a page that has faded


def test_a_question_about_an_archived_page_the_name_was_not_said_after_is_retired_with_nothing_written(memory):
    path = _world(memory, "QL", "QL, also called Quartzline, is the thing I deploy on Fridays.")
    _page(memory, "quartzline", "Quartzline", f"## Summary\n{FACT}\n", status="archived", confidence=0.0, last_referenced="2026-11-20",
          source_episodes=["ep_2026-10-01_001"])
    _commit(memory, "faded")
    page = (memory / "entities" / "quartzline.md").read_bytes()
    calls: list = []
    report, rows = _look(memory, _judge(_same("x"), calls=calls))
    assert calls == [] and report.settled == 1 and report.calls == 0           # no model read
    assert (memory / "entities" / "quartzline.md").read_bytes() == page and _open(memory) == []
    held = pending_store.held_line(memory, "QL")
    assert held is not None and not held.apart_pages()                          # still held, under its own name
    rec = markdown_parser.parse(memory / "inbox" / "settled" / f"{path.stem}.md").frontmatter["settled"]
    assert rec["rule"] == "target_faded" and [r["what"] for r in rows] == ["retired"]
    inbox_tend.undo(memory, path.stem)
    assert _open(memory) == [path.stem]


def test_the_dry_run_counts_a_retirement_and_writes_nothing(memory):
    _world(memory, "QL", "QL, also called Quartzline, is the thing I deploy on Fridays.")
    _page(memory, "quartzline", "Quartzline", f"## Summary\n{FACT}\n", status="archived", last_referenced="2026-11-20")
    _commit(memory, "faded")
    head = _git(memory, "rev-parse", "HEAD")
    _, rows = _look(memory, None, dry_run=True)
    assert [(r["what"], r["rule"]) for r in rows] == [("would_retire", "target_faded")]
    assert _git(memory, "rev-parse", "HEAD") == head and len(_open(memory)) == 1


def test_a_name_said_after_an_archived_pages_last_mention_is_read_but_never_landed_on_it(memory):
    turn = "QL, also called Quartzline, is the thing I deploy on Fridays."
    path = _world(memory, "QL", turn)
    _page(memory, "quartzline", "Quartzline", f"## Summary\n{FACT}\n", status="archived", confidence=0.0, last_referenced="2026-11-05",
          source_episodes=["ep_2026-10-01_001"])
    _commit(memory, "faded")
    case, why = name_revisit.name_case(memory, path, dict(markdown_parser.parse(path).frontmatter))
    assert case is not None and case.faded and why == ""
    calls: list = []
    report, rows = _look(memory, _judge(_same(turn), calls=calls))
    assert len(calls) == 1 and report.settled == 0 and _aliases(memory) == [] and len(_open(memory)) == 1   # read, never joined
    assert [r["what"] for r in rows] == ["read:unsure"]


def test_a_part_of_an_archived_page_said_after_its_last_mention_can_still_be_closed(memory):
    line = "The Quartzline backend is the Python service behind the dashboard."
    _world(memory, "Quartzline backend", line)
    _page(memory, "quartzline", "Quartzline", f"## Summary\n{FACT}\n", status="archived", last_referenced="2026-11-05",
          source_episodes=["ep_2026-10-01_001"])
    _commit(memory, "faded")
    report, _ = _look(memory, _judge(_different(line)))
    assert report.settled == 1 and _open(memory) == []


@pytest.mark.parametrize("status,owner,why", [("dropped", False, "target_dropped"), ("active", True, "owner_page")])
def test_a_dropped_page_and_the_owners_page_keep_their_own_reasons(memory, status, owner, why):
    path = _world(memory, "QL", "QL, also called Quartzline, is the thing I deploy on Fridays.")
    if owner:
        fm = dict(markdown_parser.parse(path).frontmatter)
        markdown_parser.write(path, {**fm, "merge_target_hint": "owner-example"}, "x")
    else:
        _page(memory, "quartzline", "Quartzline", f"## Summary\n{FACT}\n", status=status)
    _commit(memory, "setup")
    case, got = name_revisit.name_case(memory, path, dict(markdown_parser.parse(path).frontmatter))
    assert case is None and got == why


def test_a_missing_page_and_a_nameless_question_say_which_it_was(memory):
    path = _world(memory, "QL", "QL, also called Quartzline, is the thing I deploy on Fridays.")
    fm = dict(markdown_parser.parse(path).frontmatter)
    assert name_revisit.name_case(memory, path, {**fm, "merge_target_hint": "no-such-page"})[1] == "target_missing"
    assert name_revisit.name_case(memory, path, {**fm, "entity_name": "", "entity_mention": ""})[1] == "no_name"


def test_a_turn_relating_the_name_to_a_name_the_page_shares_still_stops_a_close(memory):
    _target(memory, aliases=["scheduler"])
    _page(memory, "harbor-cron", "Harbor Cron", "## Summary\nA cron wrapper.\n", aliases=["scheduler"], type="tool")
    turn = "Teal, also called scheduler, is the thing I deploy on Fridays."
    _episode(memory, "ep_2026-11-14_001", f"user: {turn}\nassistant: Ok.\n")
    _hold(memory, "Teal", "ep_2026-11-14_001", "Teal came up in a planning call.")
    _ask(memory, "Teal", "ep_2026-11-14_001")
    _commit(memory, "world")
    report, _ = _look(memory, _judge(_different(turn, relation="unrelated")))
    assert report.settled == 0 and len(_open(memory)) == 1


# --------------------------------------------------------------------------- round 2: the close's block is narrow


#: A sentence of the person's that could be PRESENTING the two as one thing (adjacent, or joined only by a marker): it withholds a close.
PRESENTED = [
    "Swift, I mean Quartzline, is the thing we deploy on Fridays.",
    "Swift or Quartzline, whichever you call it, ships on Fridays.",
    "Swift / Quartzline ships on Fridays.",
    "Swift = Quartzline in the deploy notes.",
    "Swift aka Quartzline ships on Fridays.",
    "Swift, i.e. Quartzline, ships on Fridays.",
    "Swift, that is Quartzline, ships on Fridays.",
    "Swift (Quartzline) ships on Fridays.",
    "Swift, also called Quartzline, ships on Fridays.",
    "Swift, also known as Quartzline, ships on Fridays.",
    "Swift is known as Quartzline.",
    "Swift is short for Quartzline.",
    "Swift, o sea Quartzline, sale los viernes.",
    "Swift, es decir Quartzline, sale los viernes.",
    "Swift o Quartzline, da igual, sale los viernes.",
    "Swift, también llamado Quartzline, sale los viernes.",
    "Swift alias Quartzline sale los viernes.",
    "Quartzline, I mean Swift, ships on Fridays.",
    "Swift, I mean the Quartzline, ships on Fridays.",
    "Swift is Quartzline.",
]
#: A sentence that names both with anything else between them relates them as two: it holds nothing back.
RELATED_AS_TWO = [
    "The Swift module for Quartzline ships on Fridays.",
    "Swift in Quartzline broke again yesterday.",
    "Quartzline's Swift is the new retry thing.",
    "Swift is part of Quartzline and ships with it.",
    "I wired Swift into Quartzline last week.",
    "Swift is not Quartzline, it only runs beside it.",
    "Swift talks to Quartzline over a queue.",
]


@pytest.mark.parametrize("line", PRESENTED)
def test_a_sentence_that_could_present_the_two_as_one_is_seen_as_such(line):
    assert name_revisit._presented_as_one(line, ["Swift"], ["Quartzline"])


@pytest.mark.parametrize("line", RELATED_AS_TWO)
def test_a_sentence_that_names_both_with_anything_between_holds_nothing_back(line):
    assert not name_revisit._presented_as_one(line, ["Swift"], ["Quartzline"])


@pytest.mark.parametrize("line", PRESENTED)
def test_a_judge_that_always_says_different_closes_nothing_when_a_sentence_could_present_them_as_one(memory, line):
    _world(memory, "Swift", line, held="Swift is mentioned in a planning call.")
    report, _ = _look(memory, _judge(_different(line, relation="unrelated")))
    assert report.settled == 0 and len(_open(memory)) == 1


@pytest.mark.parametrize("line", RELATED_AS_TWO)
def test_a_part_of_the_project_named_in_one_sentence_with_the_page_is_closed(memory, line):
    _world(memory, "Swift", line, held="Swift is mentioned in a planning call.")
    report, rows = _look(memory, _judge(_different(line, relation="part")))
    assert report.settled == 1 and _open(memory) == [] and _aliases(memory) == []
    assert [r["what"] for r in rows] == ["closed_apart"]
    assert "quartzline" in pending_store.apart_of(memory, "Swift")


@pytest.mark.parametrize("line", RELATED_AS_TWO)
def test_a_judge_that_always_says_same_joins_nothing_on_a_sentence_that_relates_them_as_two(memory, line):
    _world(memory, "Swift", line, held="Swift is mentioned in a planning call.")
    report, _ = _look(memory, _judge(_same(line)))
    held = pending_store.held_line(memory, "Swift")
    assert report.settled == 0 and _aliases(memory) == [] and held is not None and not held.apart_pages() and len(_open(memory)) == 1


def test_the_evidence_for_a_close_is_still_the_persons_own_turn_and_two_reads_must_agree(memory):
    line = "The Swift module for Quartzline ships on Fridays."
    _target(memory)
    _episode(memory, "ep_2026-11-14_001", f"user: Planning call today.\nassistant: {line}\n")
    _hold(memory, "Swift", "ep_2026-11-14_001", "Swift is mentioned in a planning call.")
    _ask(memory, "Swift", "ep_2026-11-14_001")
    _commit(memory, "world")
    assert _look(memory, _judge(_different(line, relation="part")))[0].settled == 0      # an assistant's turn is no evidence


def test_a_close_needs_both_reads_to_say_different(memory):
    line = "Swift talks to Quartzline over a queue."
    _world(memory, "Swift", line, held="Swift is mentioned in a planning call.")
    unsure = {"answers": [{"name": 1, "verdict": "cannot_tell", "reason": "r"}]}
    assert _look(memory, _judge(_different(line, relation="part"), unsure))[0].settled == 0


# --------------------------------------------------------------------------- round 2: a long turn is shown in pieces


def _filler(n: int, tag: str = "f") -> str:
    return " ".join(f"Filler sentence {tag}{i} is only about lunch and the weather today." for i in range(n))


def _long_world(memory: Path, before: int, middle: str, after: int, name: str = "Swift") -> Path:
    turn = f"{_filler(before, 'b')} {middle} {_filler(after, 'a')}"
    assert len(turn) > qr.TURN_CHARS
    return _world(memory, name, turn, held=f"{name} is mentioned in a planning call.")


def test_a_long_pasted_turn_with_the_name_in_the_middle_is_read_in_pieces_and_a_part_is_closed(memory):
    middle = "The Swift module for Quartzline ships on Fridays."
    _long_world(memory, 20, middle, 20)
    calls: list[str] = []
    report, rows = _look(memory, _judge(_different(middle, relation="part"), calls=calls))
    assert report.settled == 1 and [r["what"] for r in rows] == ["closed_apart"]
    prompt = calls[0]
    assert middle in prompt and qr.CUT_MARK in prompt
    assert "Filler sentence b0 " not in prompt and "Filler sentence a19 " not in prompt     # the far parts are not shown
    assert "Filler sentence b19 " in prompt and "Filler sentence a0 " in prompt                # one sentence each side is


def test_a_denial_far_from_the_first_mention_is_still_shown_and_both_ends_are_marked(memory):
    first = "Swift came up in the standup."
    denial = "Swift is not Quartzline, it only talks to it."
    turn = f"{first} {_filler(15, 'm')} {denial} {_filler(15, 'z')}"
    assert len(turn) > qr.TURN_CHARS
    _world(memory, "Swift", turn, held="Swift is mentioned in a planning call.")
    calls: list[str] = []
    _look(memory, _judge({"answers": [{"name": 1, "verdict": "cannot_tell", "reason": "r"}]}, calls=calls))
    prompt = calls[0]
    assert first in prompt and denial in prompt and prompt.count(qr.CUT_MARK) >= 2
    assert "Filler sentence m7 " not in prompt


@pytest.mark.parametrize("crosses_the_cut,settled", [(True, 0), (False, 1)])
def test_a_quote_from_a_part_that_was_cut_is_refused(memory, crosses_the_cut, settled):
    middle = "The Swift module for Quartzline ships on Fridays."
    _long_world(memory, 20, middle, 20)
    line = f"Filler sentence b19 is only about lunch and the weather today. {middle}"
    if crosses_the_cut:
        line = f"Filler sentence b18 is only about lunch and the weather today. {line}"    # b18 was never shown to the reader
    report, _ = _look(memory, _judge(_different(line, relation="part")))
    assert report.settled == settled and len(_open(memory)) == 1 - settled


def test_the_cut_never_hides_what_the_code_checks(memory):
    middle = "Swift, I mean Quartzline, is the thing we deploy."
    _long_world(memory, 20, middle, 20)
    report, _ = _look(memory, _judge(_different(middle, relation="part")))
    assert report.settled == 0 and len(_open(memory)) == 1       # the whole turn is read for the block, shown or not


def test_a_turn_that_is_too_long_even_in_pieces_leaves_the_question_with_the_same_reason(memory):
    many = " ".join(f"Swift runs job {i} next to Quartzline for the nightly batch of work." for i in range(40))
    path = _world(memory, "Swift", many)
    case, why = name_revisit.name_case(memory, path, dict(markdown_parser.parse(path).frontmatter))
    assert case is None and why == "turn_too_long"


def test_cut_ranges_keep_each_naming_sentence_with_its_neighbours_in_order():
    text = " ".join(["Aaa one is here."] * 3 + ["Swift is here."] + ["Bbb two is here."] * 6 + ["Quartzline is here too."] + ["Ccc end is here."] * 3)
    ranges = name_revisit.cut_ranges(text, ["Swift"], ["Quartzline"], cap=10_000)
    pieces = [text[s:e] for s, e in ranges]
    assert len(pieces) == 2 and "Swift is here." in pieces[0] and "Quartzline is here too." in pieces[1]
    turn = qr.Turn(1, "ep", "2026-11-14", "person", text, True, ranges)
    assert turn.display().count(qr.CUT_MARK) == 3 and not turn.shows(0, 5) and turn.shows(*ranges[0])


def test_the_two_pages_path_still_refuses_a_turn_that_is_too_long(memory):
    long_turn = f"{_filler(30)} Swift and Quartzline came up. {_filler(30, 'a')}"
    _episode(memory, "ep_2026-11-14_001", f"user: {long_turn}\nassistant: Ok.\n")
    a = qr.Side("swift", "Swift", ["Swift"], [], [])
    b = qr.Side("quartzline", "Quartzline", ["Quartzline"], [], [])
    assert qr._turns_for(memory, ["ep_2026-11-14_001"], a, b) == ([], "turn_too_long")


# --------------------------------------------------------------------------- a label nobody said (ruling 82 (e), G98)

NOT_SAID = "We rebuilt the scheduling dashboard this week and shipped it on Friday."


def _coined(memory: Path, name: str = "Harbor revamp", turn: str = NOT_SAID, assistant: str = "Ok.") -> Path:
    """A name Stage 1 coined for something: held on a line and asked about, said in no turn of the conversation."""
    _target(memory)
    ep = "ep_2026-11-14_001"
    _episode(memory, ep, f"user: {turn}\nassistant: {assistant}\n")
    _hold(memory, name, ep, f"{name} is mentioned in a planning call.")
    path = _ask(memory, name, ep)
    _commit(memory, "world")
    return path


def test_a_label_nobody_said_is_retired_with_no_read_nothing_written_and_undoable(memory):
    path = _coined(memory)
    page, store = (memory / "entities" / "quartzline.md").read_bytes(), pending_store.store_path(memory).read_bytes()
    calls: list = []
    report, rows = _look(memory, _judge(_same("x"), calls=calls))
    assert calls == [] and report.settled == 1 and report.calls == 0                       # no model read
    assert (memory / "entities" / "quartzline.md").read_bytes() == page and _open(memory) == []
    assert pending_store.store_path(memory).read_bytes() == store                           # the held lines are exactly as they were
    assert pending_store.held_line(memory, "Harbor revamp") is not None and _aliases(memory) == []
    rec = markdown_parser.parse(memory / "inbox" / "settled" / f"{path.stem}.md").frontmatter["settled"]
    assert rec["rule"] == "name_not_said" and [(r["what"], r["rule"]) for r in rows] == [("retired", "name_not_said")]
    assert "label Cicada made up" in inbox_tend.RULES["name_not_said"]
    inbox_tend.undo(memory, path.stem)
    assert _open(memory) == [path.stem]


def test_the_dry_run_prints_which_rule_would_retire_each_and_writes_nothing(memory):
    _coined(memory)
    head = _git(memory, "rev-parse", "HEAD")
    calls: list = []
    _, rows = _look(memory, _judge(_same("x"), calls=calls), dry_run=True)
    assert [(r["what"], r["rule"]) for r in rows] == [("would_retire", "name_not_said")] and calls == []
    assert _git(memory, "rev-parse", "HEAD") == head and len(_open(memory)) == 1


def test_the_same_label_with_a_cited_conversation_missing_is_left_with_a_counted_reason(memory):
    path = _coined(memory)
    line = pending_store.held_line(memory, "Harbor revamp")
    line.heard_in = [{"episode": "ep_2026-11-10_001"}]                                      # a conversation the bank no longer has
    pending_store.upsert(memory, line)
    _commit(memory, "cited")
    calls: list = []
    report, rows = _look(memory, _judge(_same("x"), calls=calls))
    assert calls == [] and report.settled == 0 and len(_open(memory)) == 1
    assert [r["what"] for r in rows] == ["left:conversation_missing"] and report.skipped.get("conversation_missing") == 1
    case, why = name_revisit.name_case(memory, path, dict(markdown_parser.parse(path).frontmatter))
    assert case is None and why == "conversation_missing"


def test_a_label_said_in_a_second_cited_conversation_is_not_retired(memory):
    _coined(memory)
    _episode(memory, "ep_2026-11-12_001", "user: The Harbor revamp is next on the board.\nassistant: Ok.\n")
    line = pending_store.held_line(memory, "Harbor revamp")
    line.heard_in = [{"episode": "ep_2026-11-12_001"}]
    pending_store.upsert(memory, line)
    _commit(memory, "cited")
    calls: list = []
    _, rows = _look(memory, _judge({"answers": []}, calls=calls))
    assert len(calls) == 1 and [r["what"] for r in rows] == ["read:unread"]               # said: it is read like any other


def test_a_name_said_only_by_an_assistant_was_said_and_is_not_retired_by_this_rule(memory):
    _coined(memory, assistant="The Harbor revamp looks done to me.")
    calls: list = []
    report, rows = _look(memory, _judge({"answers": [{"name": 1, "verdict": "cannot_tell", "reason": "r"}]}, calls=calls))
    assert len(calls) == 1 and report.settled == 0 and [r["what"] for r in rows] == ["read:unsure"]


@pytest.mark.parametrize("name,said", [
    ("Harbor revamp", "The HARBOR REVAMP is on the board."),            # case
    ("Harbor revamp", "The Harbor   revamp is\non the board."),         # spacing
    ("Tern-4", "We moved to Tern 4 on Friday."),                         # a hyphen
    ("Café plan", "The Cafe plan is done."),                             # an accent
])
def test_a_name_differing_only_by_case_spacing_or_punctuation_was_said(memory, name, said):
    _coined(memory, name=name, turn=said)
    calls: list = []
    report, rows = _look(memory, _judge({"answers": [{"name": 1, "verdict": "cannot_tell", "reason": "r"}]}, calls=calls))
    assert len(calls) == 1 and report.settled == 0 and [r["what"] for r in rows] == ["read:unsure"]


def test_a_rewording_is_not_said(memory):
    _coined(memory, name="Harbor revamp", turn="The harbour revamp, redone, is on the board.")
    calls: list = []
    report, rows = _look(memory, _judge({"answers": []}, calls=calls))
    assert calls == [] and [r["what"] for r in rows] == ["retired"]            # "harbour" is a different word: never fuzzy


def test_a_person_is_never_retired_by_this_rule(memory):
    _target(memory, type="person")
    ep = "ep_2026-11-14_001"
    _episode(memory, ep, f"user: {NOT_SAID}\nassistant: Ok.\n")
    _hold(memory, "Dana Example", ep, "Dana Example came up in a planning call.", type_="person")
    path = _ask(memory, "Dana Example", ep, classification="person")
    _commit(memory, "world")
    case, why = name_revisit.name_case(memory, path, dict(markdown_parser.parse(path).frontmatter))
    assert why != "name_not_said"


def test_a_question_with_no_conversation_to_read_is_not_retired(memory):
    path = _coined(memory)
    fm = dict(markdown_parser.parse(path).frontmatter)
    assert name_revisit.unsaid(memory, ["Harbor revamp"], []) == ""
    assert name_revisit.unsaid(memory, ["Harbor revamp"], [fm["source_episode"]]) == "name_not_said"
    assert name_revisit.unsaid(memory, ["Harbor revamp"], ["ep_2099-01-01_001"]) == "conversation_missing"


def test_a_label_asked_apart_or_undone_is_the_persons_and_never_retired(memory):
    path = _coined(memory)
    fm = dict(markdown_parser.parse(path).frontmatter)
    markdown_parser.write(path, {**fm, inbox_tend.UNDONE_KEY: "undone"}, "x")
    _commit(memory, "undone")
    report, rows = _look(memory, _judge(_same("x")))
    assert report.settled == 0 and rows == [] and len(_open(memory)) == 1


def test_a_retirement_is_undone_by_the_guard_when_the_name_is_said_since(memory):
    path = _coined(memory)
    fm = dict(markdown_parser.parse(path).frontmatter)
    decision = name_revisit.unsaid_decision(memory, path, fm)
    _episode(memory, "ep_2026-11-14_001", "user: The Harbor revamp is on the board.\nassistant: Ok.\n")
    _commit(memory, "said")
    assert name_revisit.still_holds(memory, decision) is False
