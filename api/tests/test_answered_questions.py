"""A question the record already answers is closed, never left saying "asked, never joined" (ruling 74c, 2026-11-24).

Synthetic bank only (Marisol Quinn, Ines Varga the owner); real git, no engine, no network."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.services import (answered_questions, bank_index, inbox_tend, markdown_parser, merge_closes, merge_rejections,
                          page_join, page_redirects, pending_store, predicates)


def run(coro):
    return asyncio.run(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _commit(memory: Path, msg: str = "seed") -> None:
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", msg)
    bank_index.invalidate(memory)
    page_redirects.invalidate()


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.llm_mode = "byok"


def _page(memory: Path, eid: str, name: str, *, type_="person", **fm) -> None:
    meta = {"name": name, "type": type_, "status": "active", "confidence": 0.8, "created": "2026-10-01",
            "last_referenced": "2026-10-20", "source_episodes": [], "related": [], "version": 1}
    meta.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", meta, f"## Summary\n{name}, synthetic.\n")


def _question(memory: Path, number: int, entity_id: str, name: str, target: str, **fm) -> Path:
    path = memory / "inbox" / f"inbox-{number:03d}.md"
    meta = {"kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.5,
            "entity_id": entity_id, "entity_name": name, "title": f"Is {name} the same as {target}?",
            "created_date": "2026-11-10", "merge_target_hint": target}
    meta.update(fm)
    markdown_parser.write(path, meta, "Asked, never joined: only your answer joins them.")
    return path


def _fm(path: Path) -> dict:
    return dict(markdown_parser.parse(path).frontmatter)


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


def _open(memory: Path) -> list[str]:
    return sorted(p.stem for p in (memory / "inbox").glob("inbox-*.md"))


# --------------------------------------------------------------------------- both ends are one page


def test_both_ends_resolving_to_one_page_through_redirects_is_answered(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn")
    page_redirects.add(memory, "marizol-quinn", "marisol-quinn")
    page_redirects.add(memory, "marisol-q", "marisol-quinn")
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-q")
    _commit(memory)
    d, why = inbox_tend.policy(memory, q, _fm(q))
    assert (d.rule, d.request, why) == ("already_one_page", None, "")


def test_a_pair_of_two_pages_is_not_answered(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn")
    _page(memory, "marizol-quinn", "Marizol Quinn")
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn")
    _commit(memory)
    assert answered_questions.pair_answer(memory, _fm(q)) is None


def test_a_which_one_question_over_several_pages_is_never_answered_here(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn")
    page_redirects.add(memory, "marizol-quinn", "marisol-quinn")
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn", same_title=["marisol-quinn", "x"])
    _commit(memory)
    assert answered_questions.pair_answer(memory, _fm(q)) is None


# --------------------------------------------------------------------------- the asked name is already the page's


def _hold(memory: Path, name: str) -> None:
    pending_store.upsert(memory, pending_store.PendingEntity(
        name=name, type="person", description="", source_episode="ep_2026-11-01_001", confidence=0.9, tags=[],
        history_entries=[{"date": "2026-11-01", "event": "Mentioned."}], held_claims=[], aliases=[]))


def test_a_name_already_filed_under_the_page_with_a_line_still_held_lands_it_through_the_resolver(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"])
    _hold(memory, "Marizol Quinn")
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn")
    _commit(memory)
    d, _ = inbox_tend.policy(memory, q, _fm(q))
    assert d.rule == "already_a_name" and d.request == {"action": "merge", "merge_target": "marisol-quinn"}
    d.fingerprint = q.read_bytes()
    assert run(inbox_tend.apply(memory, _Settings(memory), d))
    assert not q.exists() and pending_store.held_line(memory, "Marizol Quinn") is None
    assert (memory / "inbox" / "settled" / "inbox-001.md").exists()


def test_a_name_filed_under_the_page_with_nothing_held_is_the_subject_gone_rule_s(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"])
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn")
    _commit(memory)
    d, _ = inbox_tend.policy(memory, q, _fm(q))
    assert d.rule == "subject_gone"      # nothing waits under the name: already closed by the older rule
    assert answered_questions.pair_answer(memory, _fm(q)).rule == "already_a_name"


def test_a_pair_already_one_page_is_settled_with_one_commit_and_undone(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn")
    page_redirects.add(memory, "marizol-quinn", "marisol-quinn")
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn")
    _commit(memory)
    d, _ = inbox_tend.policy(memory, q, _fm(q))
    assert d.rule == "already_one_page" and d.request is None
    d.fingerprint = q.read_bytes()
    assert run(inbox_tend.apply(memory, _Settings(memory), d))
    assert not q.exists()
    assert (memory / "inbox" / "settled" / "inbox-001.md").exists()
    assert _git(memory, "status", "--porcelain").strip() == ""      # one Sleep commit holds the whole settle
    inbox_tend.undo(memory, "inbox-001")
    assert q.exists()                                               # back, marked so Sleep never settles it again
    assert inbox_tend.policy(memory, q, _fm(q)) == (None, "undone")


def test_the_owners_page_is_never_the_answer(memory):
    _page(memory, "ines-varga", "Ines Varga", owner=True, aliases=["Ines V"])
    _hold(memory, "Ines V")
    q = _question(memory, 1, "ines-v", "Ines V", "ines-varga")
    _commit(memory)
    assert answered_questions.pair_answer(memory, _fm(q)) is None


def test_a_name_two_pages_answer_to_is_not_answered(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Mari"])
    _page(memory, "mari-lowe", "Mari Lowe", aliases=["Mari"])
    q = _question(memory, 1, "mari", "Mari", "marisol-quinn")
    _commit(memory)
    assert answered_questions.pair_answer(memory, _fm(q)) is None


def test_a_pair_the_person_called_two_is_never_read_as_answered(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"])
    merge_rejections.add_rejected(memory, "marizol-quinn", "marisol-quinn")
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn")
    _commit(memory)
    assert answered_questions.pair_answer(memory, _fm(q)) is None


def test_a_name_the_person_removed_from_the_page_is_not_a_name_of_it(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"],
          aliases_removed=[{"alias": "Marizol Quinn", "by": "person"}])
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn")
    _commit(memory)
    assert answered_questions.pair_answer(memory, _fm(q)) is None


def test_a_question_the_person_took_back_is_never_settled_again(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"])
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn", sleep_settle="undone")
    _commit(memory)
    assert inbox_tend.policy(memory, q, _fm(q)) == (None, "undone")


# --------------------------------------------------------------------------- the merge itself closes a chain


def test_a_chain_of_merges_closes_the_question_that_named_the_first_page(memory):
    for eid, name in (("marisol-q", "Marisol Q"), ("marisol-quinn", "Marisol Quinn"), ("marizol-quinn", "Marizol Quinn")):
        _page(memory, eid, name)
    _commit(memory)
    page_join.merge(memory, "marisol-q", "marisol-quinn", author="user")          # A into W
    assert page_redirects.resolve(memory, "marisol-q") == "marisol-quinn"
    _question(memory, 1, "marisol-q", "Marisol Q", "marizol-quinn")               # "A or P?", raised on the old id
    _commit(memory)
    page_join.merge(memory, "marisol-quinn", "marizol-quinn", author="user")      # W into P: closes it
    assert _open(memory) == []


def test_former_ids_are_ends_of_a_page(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn")
    page_redirects.add(memory, "marisol-q", "marisol-quinn")
    assert {"marisol-quinn", "marisol-q"} <= merge_closes._ends(memory, "marisol-quinn")


# --------------------------------------------------------------------------- a conflict whose values are one person


def _conflict(memory: Path, number: int, labels: list[str], **fm) -> Path:
    path = memory / "inbox" / f"inbox-{number:03d}.md"
    meta = {"kind": "conflict", "status": "pending", "entity_id": "ines-varga", "entity_name": "Ines Varga",
            "predicate": "travels-with", "created_date": "2026-11-12",
            "options": [{"key": f"opt{i}", "label": label} for i, label in enumerate(labels)]}
    meta.update(fm)
    markdown_parser.write(path, meta, "Who is travelling with me?")
    return path


def test_labels_that_are_two_names_of_one_page_are_not_a_conflict(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"])
    q = _conflict(memory, 1, ["Marizol Quinn", "Marisol Quinn"])
    _commit(memory)
    found = answered_questions.labels_one_page(memory, _fm(q))
    assert found is not None and found[0] == "marisol-quinn"
    d, _ = inbox_tend.policy(memory, q, _fm(q))
    assert d is not None and d.rule == "names_one_page" and d.request["option_key"] == "opt1"   # the page's own spelling stays


def test_labels_of_two_pages_or_an_unfiled_spelling_stay_a_conflict(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn")
    _page(memory, "mara-quinn", "Mara Quinn")
    both = _conflict(memory, 1, ["Marisol Quinn", "Mara Quinn"])
    unfiled = _conflict(memory, 2, ["Marisol Quinn", "Marizol Quinn"])
    _commit(memory)
    for q in (both, unfiled):
        assert answered_questions.labels_one_page(memory, _fm(q)) is None


# --------------------------------------------------------------------------- the dry run


def test_the_dry_run_lists_ids_and_rules_only_and_writes_nothing(memory):
    import sys

    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"])
    page_redirects.add(memory, "marisol-q", "marisol-quinn")
    _question(memory, 1, "marisol-q", "Marisol Q", "marisol-quinn")                  # already one page
    _question(memory, 2, "marizol-quinn", "Marizol Quinn", "marisol-quinn")          # a name of the page, nothing held
    _page(memory, "other-person", "Other Person")
    _question(memory, 3, "other-person", "Other Person", "marisol-quinn")            # two pages: stays
    _conflict(memory, 4, ["Marisol Quinn", "Marizol Quinn"])
    _commit(memory)
    before = _git(memory, "status", "--porcelain")
    script = Path(__file__).resolve().parents[2] / "scripts" / "answered_questions_dry_run.py"
    out = subprocess.run([sys.executable, str(script), "--memory", str(memory)], capture_output=True, text=True, check=True).stdout
    assert "inbox-001" in out and "already_one_page" in out
    assert "inbox-002" in out and ("subject_gone" in out or "already_a_name" in out)
    assert "inbox-004" in out and "names_one_page" in out
    assert "inbox-003" not in out and "Marisol" not in out and "Quinn" not in out      # ids and rules, never a name
    assert _git(memory, "status", "--porcelain") == before and (memory / "inbox" / "inbox-001.md").exists()


# --------------------------------------------------------------------------- review 2026-11-24: a "No" kept on the held line


def _hold_line(memory: Path, name: str, **kw) -> None:
    pending_store.upsert(memory, pending_store.PendingEntity(
        name=name, type="person", description="", source_episode="ep_2026-11-01_001", confidence=0.9, tags=[],
        history_entries=[{"date": "2026-11-01", "event": "Mentioned."}], held_claims=[], aliases=[], **kw))


def test_a_no_kept_on_the_held_line_is_never_read_as_answered_and_nothing_lands(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"])
    _hold(memory, "Marizol Quinn")
    assert pending_store.mark_apart(memory, "Marizol Quinn", ["marisol-quinn"])    # the person said: not that page
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn")
    _commit(memory)
    assert not merge_rejections.is_rejected(memory, "marizol-quinn", "marisol-quinn")   # it is NOT stored as a rejection
    assert answered_questions.pair_answer(memory, _fm(q)) is None
    d, _ = inbox_tend.policy(memory, q, _fm(q))
    assert d is None or not (d.request or {}).get("merge_target")
    assert pending_store.held_line(memory, "Marizol Quinn") is not None


def test_a_line_held_against_the_page_is_stage_2s_undecided_and_never_landed_by_its_name(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"])
    _hold_line(memory, "Marizol Quinn", held_against="marisol-quinn")
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn")
    _commit(memory)
    assert answered_questions.pair_answer(memory, _fm(q)) is None


def test_a_pair_sleep_split_is_never_read_as_answered(memory):
    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"])
    merge_rejections.add_split(memory, "marizol-quinn", "marisol-quinn")
    q = _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn")
    _commit(memory)
    assert answered_questions.pair_answer(memory, _fm(q)) is None


# --------------------------------------------------------------------------- review 2026-11-24: an id with a page of its own


def test_a_stale_redirect_for_an_id_that_is_a_live_page_again_names_that_page_not_this_one(memory):
    for eid, name in (("marisol-q", "Marisol Q"), ("marisol-quinn", "Marisol Quinn"), ("marizol-quinn", "Marizol Quinn")):
        _page(memory, eid, name)
    _commit(memory)
    page_redirects.add(memory, "marisol-q", "marisol-quinn")           # stale: "marisol-q" has a page of its own again
    q = _question(memory, 1, "marisol-q", "Marisol Q", "marizol-quinn")
    _commit(memory)
    assert "marisol-q" not in merge_closes._ends(memory, "marisol-quinn")
    page_join.merge(memory, "marisol-quinn", "marizol-quinn", author="user")   # W into P
    assert _open(memory) == ["inbox-001"] and q.exists()                      # the live page's own question stays


# --------------------------------------------------------------------------- the dry run lists every join and fold, writing nothing


def test_the_dry_run_lists_every_engine_free_join_with_its_rule_and_writes_nothing(memory, capsys):
    import importlib.util

    _page(memory, "marisol-quinn", "Marisol Quinn", aliases=["Marizol Quinn"])
    _hold(memory, "Marizol Quinn")
    _question(memory, 1, "marizol-quinn", "Marizol Quinn", "marisol-quinn")         # a name already the page's, a line held: lands
    _page(memory, "kattia-moreau", "Kattia Moreau", source_episodes=["ep_2026-10-22_001"])
    _hold(memory, "Katia Moreau")                                                    # a plain misspelling the typo join would read
    _commit(memory)
    before = _git(memory, "status", "--porcelain")
    spec = importlib.util.spec_from_file_location("aq_dry_run", Path(__file__).resolve().parents[2] / "scripts" / "answered_questions_dry_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--memory", str(memory)]) == 0
    out = capsys.readouterr().out
    assert "inbox-001" in out and "JOIN  already_a_name" in out and "would JOIN or FOLD pages: already_a_name (ordinary) 1" in out
    assert "would be READ by the typo join" in out
    assert _git(memory, "status", "--porcelain") == before                          # nothing written
