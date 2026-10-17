"""Sleep tends the inbox (ruling 29, owner 2026-10-17).

"a single consolidation also should take care of cleaning up the inbox … as conversations come through, questions get
answered. There are also many things that maybe can be assumed."

Synthetic banks only (tool-a, tool-b, bob-example, alice-example, example-film, <owner>); the engine is a fake; git is
real; nothing reaches a network or a paid API."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from api.services import (
    bank_index,
    consumption_stats,
    git_service,
    inbox_actor,
    inbox_tend,
    markdown_parser,
    predicates,
    sleep_cycle,
    web_settle,
)
from api.services.claims import Claim, Evidence, parse_claims, write_claims

TODAY = date.today().isoformat()


def run(coro):
    return asyncio.run(coro)


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _commit(memory: Path, msg: str = "seed") -> None:
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", msg)
    bank_index.invalidate()


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90
        self.llm_mode = "byok"


def _entity(memory: Path, eid: str, *, body: str | None = None, **fm) -> None:
    base = {"name": eid.replace("-", " ").title(), "type": "concept", "status": "decaying", "confidence": 0.35,
            "created": "2026-01-01", "last_referenced": "2026-05-01", "source_episodes": [], "tags": [],
            "related": [], "version": 1}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", base, body or f"## Summary\n{base['name']} line.\n")


def _item(memory: Path, item_id: str, body: str = "Context.", **fm) -> Path:
    base = {"status": "pending", "priority": 0.5, "created_date": "2026-09-01"}
    base.update(fm)
    path = memory / "inbox" / f"{item_id}.md"
    markdown_parser.write(path, base, body)
    return path


def _episode(memory: Path, eid: str, body: str, **fm) -> dict:
    meta = {"id": eid, "timestamp": f"{eid[3:13]}T09:00:00+00:00", "processed": True, "title": "chat"}
    meta.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", meta, body)
    return {"id": eid, "content": markdown_parser.parse(memory / "episodes" / f"{eid}.md").body}


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    _entity(m, "owner-example", type="person", owner=True, name="Owner Example", status="active")
    _commit(m)
    return m


def _decide(memory: Path, item_id: str):
    path = memory / "inbox" / f"{item_id}.md"
    return inbox_tend.policy(memory, path, markdown_parser.parse(path).frontmatter)


def _settle(memory: Path, d) -> bool:
    d.fingerprint = (memory / "inbox" / f"{d.item_id}.md").read_bytes()
    return run(inbox_tend.apply(memory, _Settings(memory), d))


def _head_message(memory: Path) -> str:
    """The newest settle's commit message (a tend refreshes `_state.md` in its own commit after)."""
    return _git(memory, "log", "-1", "--fixed-strings", "--grep=Inbox settled by Sleep", "--format=%B")


# --------------------------------------------------------------------------- the policy table


def test_merge_same_spelling_settles_and_a_person_never_does(memory):
    _entity(memory, "tool-a", type="tool", name="Tool A", aliases=["ToolA"])
    _entity(memory, "tool-a-2", type="tool", name="tool-A")
    _item(memory, "inbox-001", kind="merge_suggestion", entity_id="tool-a-2", entity_name="tool-A",
          merge_target_hint="tool-a", suggested_classification="tool — could refer to the same entity as Tool A")
    _entity(memory, "bob-example", type="person", name="Bob Example")
    _entity(memory, "bob-example-2", type="person", name="Bob example")
    _item(memory, "inbox-002", kind="merge_suggestion", entity_id="bob-example-2", entity_name="Bob example",
          merge_target_hint="bob-example", suggested_classification="person — could refer to Bob Example")
    _entity(memory, "tool-b", type="tool", name="Tool B")
    _entity(memory, "tool-bee", type="tool", name="Tool Bee")
    _item(memory, "inbox-003", kind="merge_suggestion", entity_id="tool-bee", entity_name="Tool Bee",
          merge_target_hint="tool-b", suggested_classification="tool")
    _entity(memory, "tool-c", type="tool", name="Tool C")
    _entity(memory, "tool-c-place", type="location", name="Tool C")
    _item(memory, "inbox-004", kind="merge_suggestion", entity_id="tool-c-place", entity_name="Tool C",
          merge_target_hint="tool-c", suggested_classification="location")

    d, _ = _decide(memory, "inbox-001")
    assert d.rule == "same_spelling" and d.request == {"action": "merge", "merge_target": "tool-a"}
    assert _decide(memory, "inbox-002") == (None, "person")      # who someone is: only their own words
    assert _decide(memory, "inbox-003") == (None, "needs_judge")
    assert _decide(memory, "inbox-004") == (None, "judgement")   # not the same kind of thing


def test_normalization_spelling_only(memory):
    _entity(memory, "tool-a", type="tool")
    _item(memory, "inbox-001", kind="normalization", entity_id="tool-a", raw_predicate="Built With",
          canonical_predicate="built-with", claim_id="clm_x")
    _item(memory, "inbox-002", kind="normalization", entity_id="tool-a", raw_predicate="powered by",
          canonical_predicate="uses", claim_id="clm_y")
    assert _decide(memory, "inbox-001")[0].rule == "spelling_fold"
    assert _decide(memory, "inbox-002") == (None, "needs_judge")   # a meaning, not a spelling: only the judge


def test_decay_one_off_only(memory):
    _entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001"])
    _entity(memory, "bob-example", type="person", source_episodes=["ep_2026-05-01_001"])
    _entity(memory, "two-talks", type="concept", source_episodes=["ep_2026-05-01_001", "ep_2026-06-01_001"])
    kept = write_claims("## Summary\nKept.\n", [Claim(
        id="clm_u", text="x", subject="said-once", predicate="description", object="a thing", observer="owner-example",
        source_trust="user_stated", origin="clarification", valid_from="2026-05-01", recorded_at="2026-05-01")])
    _entity(memory, "said-once", type="concept", source_episodes=["ep_2026-05-01_001"], body=kept)
    for n, eid in enumerate(("example-gadget", "bob-example", "two-talks", "said-once"), start=1):
        _item(memory, f"inbox-00{n}", kind="decay", entity_id=eid, entity_name=eid)
    assert _decide(memory, "inbox-001")[0].request == {"action": "archive"}
    assert _decide(memory, "inbox-002") == (None, "judgement")    # a person: never assumed
    assert _decide(memory, "inbox-003") == (None, "needs_judge")  # two conversations: only the judge
    assert _decide(memory, "inbox-004") == (None, "needs_judge")  # the person's own words rest on it


def _conflict_page(memory: Path, *, older_human: bool = False, same_day: bool = False) -> None:
    older = Claim(id="clm_old", text="Tool A runs on alpha-os", subject="tool-a", predicate="runs-on",
                  object="alpha-os", valid_from="2026-05-01", recorded_at="2026-05-01",
                  evidence=[Evidence(episode="ep_2026-05-01_001", kind="user")])
    if older_human:
        older.source_trust, older.origin = "user_stated", "clarification"
    newer = Claim(id="clm_new", text="Tool A runs on beta-os", subject="tool-a", predicate="runs-on",
                  object="beta-os", valid_from="2026-05-01", recorded_at="2026-05-01",
                  evidence=[Evidence(episode="ep_2026-05-01_002" if same_day else "ep_2026-08-03_001", kind="user")])
    _entity(memory, "tool-a", type="tool", status="active", body=write_claims("## Summary\nA tool.\n", [older, newer]))
    _item(memory, "inbox-001", kind="conflict", entity_id="tool-a", entity_name="Tool A", predicate="runs-on",
          question="What does Tool A run on?",
          options=[{"key": "a", "label": "alpha-os", "claim_id": "clm_old"},
                   {"key": "b", "label": "beta-os", "claim_id": "clm_new"},
                   {"key": "both", "label": "Both"}])


def test_conflict_newest_dated_statement(memory):
    _conflict_page(memory)
    d, _ = _decide(memory, "inbox-001")
    assert d.rule == "newest_evidence" and d.request["option_key"] == "b"


def test_conflict_same_day_or_over_a_human_stays(memory):
    _conflict_page(memory, same_day=True)
    assert _decide(memory, "inbox-001") == (None, "needs_judge")
    _conflict_page(memory, older_human=True)
    assert _decide(memory, "inbox-001") == (None, "needs_judge")   # never by rule; the judge may only keep theirs


def test_gone_undone_deferred_and_edits(memory):
    _item(memory, "inbox-001", kind="conflict", entity_id="merged-away", entity_name="Merged Away")
    _entity(memory, "tool-a", type="tool")
    _item(memory, "inbox-002", kind="decay", entity_id="tool-a", sleep_settle="undone")
    later = (date.today() + timedelta(days=5)).isoformat()
    _item(memory, "inbox-003", kind="decay", entity_id="tool-a", remind_after=later)
    _item(memory, "inbox-004", kind="page_edit", entity_id="tool-a")
    _item(memory, "inbox-005", kind="clarification", entity_id="tool-a", entity_name="Tool A")
    assert _decide(memory, "inbox-001")[0].rule == "subject_gone"
    assert _decide(memory, "inbox-002") == (None, "undone")
    assert _decide(memory, "inbox-003") == (None, "deferred")
    assert _decide(memory, "inbox-004") == (None, "person_only")
    assert _decide(memory, "inbox-005") == (None, "needs_person")


# --------------------------------------------------------------------------- the one writer, and its undo


def test_decay_settle_is_sleeps_commit_and_undo_takes_it_back(memory):
    _entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001"])
    _item(memory, "inbox-001", kind="decay", entity_id="example-gadget", entity_name="Example Gadget")
    _commit(memory)
    d, _ = _decide(memory, "inbox-001")
    assert _settle(memory, d)
    page = markdown_parser.parse(memory / "entities" / "example-gadget.md").frontmatter
    assert page["status"] == "archived"
    assert not (memory / "inbox" / "inbox-001.md").exists()
    message = _head_message(memory)
    assert message.startswith(f"Inbox settled by Sleep (decay) {TODAY}")
    assert "trigger: inbox/decay/settled:archive" in message and "resolved:" not in message
    assert "Cicada-Author: cicada" in message and "Cicada-Author: user" not in message
    assert "inbox/settled/inbox-001.md: created" in message
    assert not _git(memory, "status", "--porcelain").strip()   # the record rode in the same commit
    # G147's reader of the person's decay answers never sees Sleep's.
    assert run(git_service.decay_verdicts(memory, since=date.today() - timedelta(days=1))) == {}
    rows = web_settle.list_settled(memory)
    assert [(r["group"], r["rule"], r["entity_id"]) for r in rows] == [("sleep", "one_off", "example-gadget")]
    assert rows[0]["reason"] == inbox_tend.RULES["one_off"]

    restored, paths, lines, rec = inbox_tend.undo(memory, "inbox-001")
    web_settle.commit_sync(memory, web_settle.commit_message("Sleep's settle undone", lines, authors=["user"]), paths)
    assert restored == "inbox-001"
    assert markdown_parser.parse(memory / "entities" / "example-gadget.md").frontmatter["status"] == "decaying"
    back = markdown_parser.parse(memory / "inbox" / "inbox-001.md").frontmatter
    assert back["sleep_settle"] == "undone" and back["kind"] == "decay"
    assert _decide(memory, "inbox-001") == (None, "undone")     # never settled by Sleep again
    assert web_settle.list_settled(memory) == []
    assert not _git(memory, "status", "--porcelain").strip()
    assert rec["rule"] == "one_off"


def test_undo_keeps_a_later_edit_elsewhere_and_refuses_an_overlapping_one(memory):
    body = "## Summary\nTool A line.\n\n## Notes\nfirst\nsecond\nthird\nfourth\nfifth\nsixth\n"
    _entity(memory, "tool-a", type="tool", name="Tool A", body=body, status="active")
    _entity(memory, "tool-a-2", type="tool", name="tool a")
    _item(memory, "inbox-001", kind="merge_suggestion", entity_id="tool-a-2", entity_name="tool a",
          merge_target_hint="tool-a", suggested_classification="tool")
    _commit(memory)
    d, _ = _decide(memory, "inbox-001")
    assert _settle(memory, d)
    target = memory / "entities" / "tool-a.md"
    assert "Resolved ambiguous mention" in target.read_text()
    # A later, unrelated edit near the top of the page survives the undo.
    target.write_text(target.read_text().replace("first\n", "first, edited later\n"))
    _commit(memory, "a later edit")
    _restored, paths, lines, _rec = inbox_tend.undo(memory, "inbox-001")
    text = target.read_text()
    assert "Resolved ambiguous mention" not in text and "first, edited later" in text
    web_settle.commit_sync(memory, web_settle.commit_message("Sleep's settle undone", lines, authors=["user"]), paths)

    # Settle again (a fresh question), then edit the very lines the settle wrote: the undo refuses, writing nothing.
    _item(memory, "inbox-002", kind="merge_suggestion", entity_id="tool-a-2", entity_name="tool a",
          merge_target_hint="tool-a", suggested_classification="tool")
    _commit(memory)
    d, _ = _decide(memory, "inbox-002")
    assert _settle(memory, d)
    target.write_text(target.read_text().replace("_Resolved ambiguous mention", "_Changed by hand: mention"))
    _commit(memory, "overlapping edit")
    before = target.read_bytes()
    with pytest.raises(inbox_tend.NotUndoable):
        inbox_tend.undo(memory, "inbox-002")
    assert target.read_bytes() == before
    assert (memory / "inbox" / "settled" / "inbox-002.md").exists()


def test_conflict_settle_closes_through_the_persons_writer_as_sleep(memory):
    _conflict_page(memory)
    _commit(memory)
    d, _ = _decide(memory, "inbox-001")
    assert _settle(memory, d)
    claims = {c.id: c for c in parse_claims((memory / "entities" / "tool-a.md").read_text())}
    assert claims["clm_old"].valid_to == TODAY and claims["clm_new"].valid_to is None
    text = (memory / "entities" / "tool-a.md").read_text()
    assert "confirmed by Sleep" in text and "confirmed by user" not in text
    assert "inbox/conflict/settled:pick:b" in _head_message(memory)


def test_retire_a_dead_question(memory):
    _item(memory, "inbox-001", kind="conflict", entity_id="merged-away", entity_name="Merged Away")
    _commit(memory)
    d, _ = _decide(memory, "inbox-001")
    assert _settle(memory, d)
    assert not (memory / "inbox" / "inbox-001.md").exists()
    assert (memory / "inbox" / "settled" / "inbox-001.md").exists()
    assert _head_message(memory).startswith("Inbox settled by Sleep (conflict)")
    assert not _git(memory, "status", "--porcelain").strip()
    restored, _paths, _lines, _rec = inbox_tend.undo(memory, "inbox-001")
    assert (memory / "inbox" / f"{restored}.md").exists()


def test_a_changed_question_is_left_alone(memory):
    _entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001"])
    path = _item(memory, "inbox-001", kind="decay", entity_id="example-gadget")
    _commit(memory)
    d, _ = _decide(memory, "inbox-001")
    d.fingerprint = path.read_bytes()
    path.write_text(path.read_text() + "\nedited\n")
    assert not run(inbox_tend.apply(memory, _Settings(memory), d))
    assert path.exists() and not (memory / "inbox" / "settled" / "inbox-001.md").exists()


def test_the_ledger_keeps_sleep_apart_from_the_persons_verdict(memory, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    _entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001"])
    _item(memory, "inbox-001", kind="decay", entity_id="example-gadget")
    _commit(memory)
    d, _ = _decide(memory, "inbox-001")
    assert _settle(memory, d)
    _restored, _p, _l, rec = inbox_tend.undo(memory, "inbox-001")
    inbox_tend.record_undo(memory, "inbox-001", rec)
    data = run(consumption_stats.feedback(memory, range_="all", today=date.today()))
    assert data["resolutions"] == 0                     # neither row is the person's verdict on the extractor
    assert data["sleep_settles"]["settled"] == 1 and data["sleep_settles"]["undone"] == 1
    assert data["sleep_settles"]["by_rule"]["one_off"] == {"settled": 1, "undone": 1}


def test_actor_unset_leaves_the_persons_answer_unchanged():
    assert inbox_actor.trigger("inbox/decay/resolved:archive") == "inbox/decay/resolved:archive"
    assert inbox_actor.claim_author() == "user" and inbox_actor.ledger_refs() == {}


# --------------------------------------------------------------------------- move 1: answered in conversation


def _fake(reply: dict, calls: list | None = None, model: str = "fake-model"):
    def fn(messages, **_kw):
        if calls is not None:
            calls.append(messages[0]["content"])
        import json

        return {"choices": [{"message": {"content": json.dumps(reply)}}], "model": model}
    return fn


def _tool_conflict(memory: Path) -> None:
    claims = [Claim(id="clm_h", text="Tool A is an agent harness", subject="tool-a", predicate="description",
                    object="agent harness", valid_from="2026-05-01", recorded_at="2026-05-01",
                    evidence=[Evidence(episode="ep_2026-05-01_001", kind="user")]),
              Claim(id="clm_g", text="Tool A is an AI agent", subject="tool-a", predicate="description",
                    object="AI agent", valid_from="2026-05-01", recorded_at="2026-05-01",
                    evidence=[Evidence(episode="ep_2026-05-01_001", kind="user")])]
    _entity(memory, "tool-a", type="tool", name="Tool A", status="active",
            body=write_claims("## Summary\nA tool.\n", claims))
    _item(memory, "inbox-001", kind="conflict", entity_id="tool-a", entity_name="Tool A", predicate="description",
          question="Is Tool A an agent harness or an AI agent?", source_episode="ep_2026-05-01_001",
          options=[{"key": "a", "label": "agent harness", "claim_id": "clm_h"},
                   {"key": "b", "label": "AI agent", "claim_id": "clm_g"}])


def test_the_persons_own_words_answer_a_question(memory):
    _tool_conflict(memory)
    ep = _episode(memory, "ep_2026-10-01_001",
                  "user: For the record, Tool A is an agent harness, not an agent itself.\n\n"
                  "assistant: Noted.")
    _commit(memory)
    calls: list = []
    fn = _fake({"answered": True, "option": "a", "quote": "Tool A is an agent harness, not an agent itself"}, calls)
    report = run(inbox_tend.tend(memory, _Settings(memory), episodes=[ep], run_policy=False, llm_fn=fn))
    assert report.settled == 1 and report.read == 1
    assert "Noted." not in calls[0]          # only the person's turns reach the prompt
    claims = {c.id: c for c in parse_claims((memory / "entities" / "tool-a.md").read_text())}
    assert claims["clm_g"].valid_to == TODAY
    spans = [e for e in claims["clm_h"].evidence if e.episode == "ep_2026-10-01_001"]
    assert spans and spans[0].kind == "user" and spans[0].is_span()
    message = _head_message(memory)
    assert "Cicada-Author: fake-model" in message and "settled:pick:a" in message
    row = web_settle.list_settled(memory)[0]
    assert row["rule"] == "said_in_conversation" and row["episode"] == "ep_2026-10-01_001"
    assert row["quote"] == "Tool A is an agent harness, not an agent itself"
    rec = markdown_parser.parse(memory / "inbox" / "settled" / "inbox-001.md").frontmatter["settled"]
    assert "quote" not in rec and rec["evidence"]["episode"] == "ep_2026-10-01_001"   # a span, never a copy


def test_words_not_the_persons_never_settle(memory):
    _tool_conflict(memory)
    ep = _episode(memory, "ep_2026-10-01_001",
                  "user: What is Tool A again? Is it an agent harness?\n\n"
                  "assistant: Tool A is an agent harness, according to its docs.")
    _commit(memory)
    fn = _fake({"answered": True, "option": "a", "quote": "Tool A is an agent harness, according to its docs"})
    report = run(inbox_tend.tend(memory, _Settings(memory), episodes=[ep], run_policy=False, llm_fn=fn))
    assert report.settled == 0
    assert (memory / "inbox" / "inbox-001.md").exists()
    assert report.by_kind["conflict"] == {"conversation:quote_not_found": 1}


def test_the_conversation_that_raised_a_question_never_answers_it(memory):
    _tool_conflict(memory)
    ep = _episode(memory, "ep_2026-05-01_001", "user: Tool A is an agent harness, I think, or an AI agent.")
    _commit(memory)
    calls: list = []
    report = run(inbox_tend.tend(memory, _Settings(memory), episodes=[ep], run_policy=False,
                                 llm_fn=_fake({"answered": True, "option": "a", "quote": "x"}, calls)))
    assert calls == [] and report.read == 0


def test_a_merge_of_two_people_needs_the_persons_words(memory):
    _entity(memory, "bob-example", type="person", name="Bob Example", status="active")
    _entity(memory, "robert-example", type="person", name="Robert Example", status="active")
    _item(memory, "inbox-001", kind="merge_suggestion", entity_id="robert-example", entity_name="Robert Example",
          merge_target_hint="bob-example", suggested_classification="person")
    ep = _episode(memory, "ep_2026-10-02_001", "user: Robert Example is Bob, same guy, we call him Bob Example.")
    _commit(memory)
    assert _decide(memory, "inbox-001") == (None, "person")
    fn = _fake({"answered": True, "option": "merge", "quote": "Robert Example is Bob, same guy"})
    report = run(inbox_tend.tend(memory, _Settings(memory), episodes=[ep], run_policy=True, llm_fn=fn))
    assert report.settled == 1
    assert "Resolved ambiguous mention" in (memory / "entities" / "bob-example.md").read_text()


# --------------------------------------------------------------------------- the judge, the tidy, Sleep's hook


def test_the_judge_merges_only_what_it_is_sure_of(memory):
    _entity(memory, "tool-b", type="tool", name="Tool B")
    _entity(memory, "tool-bee", type="tool", name="Tool Bee")
    _item(memory, "inbox-001", kind="merge_suggestion", entity_id="tool-bee", entity_name="Tool Bee",
          merge_target_hint="tool-b", suggested_classification="tool")
    _entity(memory, "tool-c", type="tool", name="Tool C")
    _entity(memory, "tool-cee", type="tool", name="Tool Cee")
    _item(memory, "inbox-002", kind="merge_suggestion", entity_id="tool-cee", entity_name="Tool Cee",
          merge_target_hint="tool-c", suggested_classification="tool")
    _commit(memory)
    replies = iter([{"verdict": "different", "confidence": 0.95}, {"verdict": "same", "confidence": 0.6}])

    def fn(messages, **_kw):
        import json

        return {"choices": [{"message": {"content": json.dumps(next(replies))}}], "model": "fake-judge"}

    report = run(inbox_tend.tend(memory, _Settings(memory), episodes=[], run_policy=True, llm_fn=fn))
    assert report.judged == 2 and report.settled == 1
    assert (memory / "inbox" / "inbox-002.md").exists()                  # unsure stays for the person
    rejected = (memory / "_merge_rejected.yaml").read_text()
    assert "tool-b" in rejected and "tool-bee" in rejected               # "different" keeps them apart


def test_tidy_dry_run_writes_nothing_and_says_only_counts(memory):
    _entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001"])
    _item(memory, "inbox-001", kind="decay", entity_id="example-gadget", entity_name="Example Gadget")
    _item(memory, "inbox-002", kind="clarification", entity_id="alice-example", entity_name="Alice Example")
    _item(memory, "inbox-003", kind="conflict", entity_id="merged-away")
    _commit(memory)
    head = _git(memory, "rev-parse", "HEAD")
    out = run(inbox_tend.tidy(memory, _Settings(memory), dry_run=True))
    assert out["dry_run"] is True and out["settled"] == 2 and out["asked"] == 1
    assert out["by_kind"] == {"clarification": {"ask:needs_person": 1}, "conflict": {"subject_gone": 1},
                              "decay": {"one_off": 1}}
    assert "Alice" not in str(out) and "Gadget" not in str(out)
    assert _git(memory, "rev-parse", "HEAD") == head and not _git(memory, "status", "--porcelain").strip()


def test_tidy_applies_under_admission_one_commit_each(memory):
    _entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001"])
    _item(memory, "inbox-001", kind="decay", entity_id="example-gadget")
    _item(memory, "inbox-002", kind="conflict", entity_id="merged-away")
    _commit(memory)
    out = run(inbox_tend.tidy(memory, _Settings(memory), dry_run=False))
    assert out["settled"] == 2
    log = _git(memory, "log", "--format=%s")
    assert log.count("Inbox settled by Sleep") == 2
    assert not list((memory / "inbox").glob("inbox-*.md"))


def test_tidy_stops_when_sleep_holds_the_pages(memory, monkeypatch):
    _item(memory, "inbox-001", kind="conflict", entity_id="merged-away")
    _commit(memory)
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    out = run(inbox_tend.tidy(memory, _Settings(memory), dry_run=False))
    assert out["stopped"] == "sleep_running" and out["settled"] == 0
    assert (memory / "inbox" / "inbox-001.md").exists()


def test_sleeps_hook_counts_and_never_raises(memory, monkeypatch):
    _item(memory, "inbox-001", kind="conflict", entity_id="merged-away")
    _commit(memory)
    monkeypatch.setattr(inbox_tend, "default_llm_fn", lambda settings, **_kw: None)
    run(sleep_cycle._tend_inbox_safely(memory, _Settings(memory), [], run_policy=True, engine=None))
    assert sleep_cycle.get_sleep_state().inbox_settled == 1

    async def boom(*_a, **_k):
        raise RuntimeError("x")

    monkeypatch.setattr(inbox_tend, "tend", boom)
    run(sleep_cycle._tend_inbox_safely(memory, _Settings(memory), [], run_policy=True, engine=None))


def test_the_inbox_routes_list_and_undo_sleeps_settles(memory):
    from api.routers import inbox as inbox_router

    _entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001"])
    _item(memory, "inbox-001", kind="decay", entity_id="example-gadget")
    _commit(memory)
    d, _ = _decide(memory, "inbox-001")
    assert _settle(memory, d)
    rows = run(inbox_router.list_settled(settings=_Settings(memory)))
    assert [(r.group, r.rule) for r in rows] == [("sleep", "one_off")]
    out = run(inbox_router.undo_settled("inbox-001", settings=_Settings(memory)))
    assert out == {"status": "reopened", "id": "inbox-001"}
    assert "Sleep's settle undone" in _git(memory, "log", "--format=%s")
    assert markdown_parser.parse(memory / "entities" / "example-gadget.md").frontmatter["status"] == "decaying"


def test_every_batch_tends_and_the_policy_runs_once_per_drain(tmp_path, monkeypatch):
    import drain_harness

    drain_harness.install(monkeypatch)
    root = tmp_path / "drain"
    root.mkdir()
    bank = drain_harness.seed_bank(root, drain_harness.episode_ids(5))
    seen: list[tuple[list[str], bool]] = []

    async def recorder(memory_path, settings, *, episodes, run_policy, llm_fn=None, engine=None):
        seen.append(([e["id"] for e in episodes], run_policy))
        return inbox_tend.Report()

    monkeypatch.setattr(inbox_tend, "tend", recorder)
    state = sleep_cycle.get_sleep_state()
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
    run(sleep_cycle.run(drain_harness.settings(bank, sleep_max_episodes_per_cycle=2), "sleep_tend_0",
                        user_triggered=True, drain=True))
    assert [len(ids) for ids, _ in seen] == [2, 2, 1]          # each batch's own conversations
    assert [policy for _, policy in seen] == [False, False, True]   # the small stuff once, with decay
    state.status, state.drain, state.drain_run = "idle", None, False


def test_a_clarification_answered_in_conversation_is_sleeps_reading_not_the_persons_inbox_answer(memory):
    from api.services.claim_reconciler import is_human

    _entity(memory, "example-gadget", type="tool", name="Example Gadget", status="active")
    _item(memory, "inbox-001", kind="clarification", entity_id="example-gadget", entity_name="Example Gadget",
          title="Who or what is Example Gadget?", source_episode="ep_2026-09-01_001")
    ep = _episode(memory, "ep_2026-10-03_001", "user: Example Gadget is the soldering station on my desk.")
    _commit(memory)
    fn = _fake({"answered": True, "answer": "a soldering station",
                "quote": "Example Gadget is the soldering station on my desk"})
    report = run(inbox_tend.tend(memory, _Settings(memory), episodes=[ep], run_policy=False, llm_fn=fn))
    assert report.settled == 1
    claim = [c for c in parse_claims((memory / "entities" / "example-gadget.md").read_text())
             if c.object == "a soldering station"][0]
    assert claim.authored_by == "fake-model" and claim.origin == "inbox-tend"
    assert not is_human(claim), "Sleep's reading stands where an extraction would, never as the person's inbox answer"
    assert claim.evidence and claim.evidence[0].kind == "user" and claim.evidence[0].is_span()


# --------------------------------------------------------------------------- review blockers (2026-10-17)


def _judge_fn(*replies, model: str = "fake-judge", before=None):
    """A fake engine answering ``replies`` in turn; ``before(prompt)`` runs first (a change landing mid-judge)."""
    import json

    queue = list(replies)

    def fn(messages, **_kw):
        if before is not None:
            before(messages[0]["content"])
        return {"choices": [{"message": {"content": json.dumps(queue.pop(0))}}], "model": model}
    return fn


def _big_claims(eid: str, n: int = 170) -> str:
    claims = [Claim(id=f"clm_{eid}_{i:03d}", text=f"{eid} note {i} " + "x" * 380, subject=eid, predicate="mentions",
                    object=f"thing-{i}", valid_from="2026-05-01", recorded_at="2026-05-01") for i in range(n)]
    return write_claims("## Summary\nA tool.\n", claims)


def test_a_judged_same_really_merges_the_two_pages_and_undo_brings_the_duplicate_back(memory):
    _entity(memory, "tool-b", type="tool", name="Tool B", status="active")
    _entity(memory, "tool-bee", type="tool", name="Tool Bee", status="active", body=_big_claims("tool-bee"))
    ledger = memory / "entities" / "tool-bee.claims.jsonl"
    assert ledger.exists(), "the fixture page spills its claims to a ledger"
    _item(memory, "inbox-001", kind="merge_suggestion", entity_id="tool-bee", entity_name="Tool Bee",
          merge_target_hint="tool-b", suggested_classification="tool")
    _commit(memory)
    before = {p: (memory / p).read_bytes() for p in ("entities/tool-b.md", "entities/tool-bee.md",
                                                       "entities/tool-bee.claims.jsonl")}
    report = run(inbox_tend.tend(memory, _Settings(memory), episodes=[], run_policy=True,
                                 llm_fn=_judge_fn({"verdict": "same", "confidence": 0.97, "reason": "one tool"})))
    assert report.settled == 1
    assert not (memory / "entities" / "tool-bee.md").exists() and not ledger.exists(), "the duplicate page is gone"
    merged = parse_claims(markdown_parser.parse(memory / "entities" / "tool-b.md").body)
    assert any(c.id.startswith("clm_tool-bee_") for c in merged), "its claims followed it"
    assert web_settle.list_settled(memory)[0]["reason"] == "one tool"
    assert not _git(memory, "status", "--porcelain").strip()

    _r, paths, lines, _rec = inbox_tend.undo(memory, "inbox-001")
    web_settle.commit_sync(memory, web_settle.commit_message("Sleep's settle undone", lines, authors=["user"]), paths)
    assert {p: (memory / p).read_bytes() for p in before} == before, "both pages and the ledger, byte for byte"
    assert not _git(memory, "status", "--porcelain").strip()


def test_a_page_that_changed_since_the_decision_is_never_settled_on_the_stale_read(memory):
    _entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001"])
    path = _item(memory, "inbox-001", kind="decay", entity_id="example-gadget")
    _commit(memory)
    d, _ = _decide(memory, "inbox-001")
    assert d.rule == "one_off"
    page = memory / "entities" / "example-gadget.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter,
                                 "source_episodes": ["ep_2026-05-01_001", "ep_2026-10-01_001"]}, parsed.body)
    _commit(memory, "a second conversation")
    d.fingerprint = path.read_bytes()
    assert not run(inbox_tend.apply(memory, _Settings(memory), d))
    assert markdown_parser.parse(page).frontmatter["status"] == "decaying"
    assert path.exists()


def test_the_tidy_settles_each_question_right_after_judging_it_and_never_on_a_page_edited_meanwhile(memory):
    _entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001", "ep_2026-06-01_001"])
    _item(memory, "inbox-001", kind="decay", entity_id="example-gadget")
    _commit(memory)
    page = memory / "entities" / "example-gadget.md"

    def person_edits(_prompt):   # the person's edit lands while the judge reads
        page.write_text(page.read_text() + "\nStill using it daily.\n")

    out = run(inbox_tend.tidy(memory, _Settings(memory), dry_run=False, judge=True,
                              llm_fn=_judge_fn({"verdict": "archive", "confidence": 0.95}, before=person_edits)))
    assert out["settled"] == 0 and out["by_kind"]["decay"] == {"left:changed": 1}
    assert markdown_parser.parse(page).frontmatter["status"] == "decaying"


def test_the_tidy_stops_before_a_judge_call_once_sleep_holds_the_pages(memory, monkeypatch):
    for n in (1, 2):
        _entity(memory, f"gadget-{n}", type="tool", source_episodes=["ep_2026-05-01_001", "ep_2026-06-01_001"])
        _item(memory, f"inbox-00{n}", kind="decay", entity_id=f"gadget-{n}")
    _commit(memory)
    calls: list = []

    def sleep_starts(_prompt):
        calls.append(1)
        monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)

    out = run(inbox_tend.tidy(memory, _Settings(memory), dry_run=False, judge=True,
                              llm_fn=_judge_fn({"verdict": "archive", "confidence": 0.95},
                                               {"verdict": "archive", "confidence": 0.95}, before=sleep_starts)))
    assert out["stopped"] == "sleep_running" and out["settled"] == 0 and len(calls) == 1


def test_two_quick_tidies_never_run_at_once(memory):

    async def go():
        assert inbox_tend.start_tidy(memory, _Settings(memory))
        assert not inbox_tend.start_tidy(memory, _Settings(memory))
        await inbox_tend._TIDY["task"]
        assert not inbox_tend.tidy_status()["running"]
    run(go())


def test_a_deferred_question_is_never_answered_from_a_conversation(memory):
    _tool_conflict(memory)
    path = memory / "inbox" / "inbox-001.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter,
                                 "remind_after": (date.today() + timedelta(days=9)).isoformat()}, parsed.body)
    ep = _episode(memory, "ep_2026-10-01_001", "user: Tool A is an agent harness, not an agent itself.")
    _commit(memory)
    calls: list = []
    report = run(inbox_tend.tend(memory, _Settings(memory), episodes=[ep], run_policy=False,
                                 llm_fn=_fake({"answered": True, "option": "a", "quote": "x"}, calls)))
    assert calls == [] and report.read == 0


def test_undoing_a_kept_apart_pair_leaves_a_later_pair_alone(memory):
    for a, b in (("tool-b", "tool-bee"), ("tool-c", "tool-cee")):
        _entity(memory, a, type="tool", name=a.title())
        _entity(memory, b, type="tool", name=b.title())
    _item(memory, "inbox-001", kind="merge_suggestion", entity_id="tool-bee", entity_name="Tool Bee",
          merge_target_hint="tool-b", suggested_classification="tool")
    _item(memory, "inbox-002", kind="merge_suggestion", entity_id="tool-cee", entity_name="Tool Cee",
          merge_target_hint="tool-c", suggested_classification="tool")
    _commit(memory)
    report = run(inbox_tend.tend(memory, _Settings(memory), episodes=[], run_policy=True,
                                 llm_fn=_judge_fn({"verdict": "different", "confidence": 0.95},
                                                  {"verdict": "different", "confidence": 0.95})))
    assert report.settled == 2
    _r, paths, lines, _rec = inbox_tend.undo(memory, "inbox-001")
    from api.services import merge_rejections

    assert merge_rejections.load_rejected(memory) == {("tool-c", "tool-cee")}


# --------------------------------------------------------------------------- the judges (owner, 2026-10-17)


def test_the_conflict_judge_settles_a_clear_answer_with_its_reason(memory):
    _conflict_page(memory, same_day=True)
    _commit(memory)
    out = run(inbox_tend.tidy(memory, _Settings(memory), dry_run=False, judge=True,
                              llm_fn=_judge_fn({"verdict": "b", "confidence": 0.93, "reason": "moved to beta-os"})))
    assert out["by_kind"]["conflict"] == {"judged_conflict": 1}
    row = web_settle.list_settled(memory)[0]
    assert (row["rule"], row["answer"], row["reason"]) == ("judged_conflict", "beta-os", "moved to beta-os")


def test_the_conflict_judge_never_lets_a_machine_claim_overrule_the_persons_own(memory):
    _conflict_page(memory, older_human=True)
    _commit(memory)
    out = run(inbox_tend.tidy(memory, _Settings(memory), dry_run=True, judge=True,
                              llm_fn=_judge_fn({"verdict": "b", "confidence": 0.99})))
    assert out["by_kind"]["conflict"] == {"ask:person": 1}


def test_a_multi_valued_conflict_keeps_every_value_without_a_judge(memory):
    claims = [Claim(id=f"clm_{k}", text="x", subject="tool-a", predicate="uses", object=k, valid_from="2026-05-01",
                    recorded_at="2026-05-01") for k in ("alpha-lib", "beta-lib")]
    _entity(memory, "tool-a", type="tool", status="active", body=write_claims("## Summary\nA.\n", claims))
    _item(memory, "inbox-001", kind="conflict", entity_id="tool-a", predicate="uses",
          options=[{"key": "a", "label": "alpha-lib", "claim_id": "clm_alpha-lib"},
                   {"key": "b", "label": "beta-lib", "claim_id": "clm_beta-lib"}])
    _commit(memory)
    d, _ = _decide(memory, "inbox-001")
    assert d.rule == "multi_valued"
    assert _settle(memory, d)
    after = parse_claims((memory / "entities" / "tool-a.md").read_text())
    assert all(c.valid_to is None for c in after), "nothing closed"


def test_the_fold_judge_folds_a_same_meaning_and_leaves_a_changed_one(memory):
    _entity(memory, "tool-a", type="tool")
    _item(memory, "inbox-001", kind="normalization", entity_id="tool-a", raw_predicate="powered by",
          canonical_predicate="uses", claim_id="clm_x")
    _item(memory, "inbox-002", kind="normalization", entity_id="tool-a", raw_predicate="competes with",
          canonical_predicate="related-to", claim_id="clm_y")
    _commit(memory)
    out = run(inbox_tend.tidy(memory, _Settings(memory), dry_run=False, judge=True,
                              llm_fn=_judge_fn({"verdict": "same", "confidence": 0.95, "reason": "same relation"},
                                               {"verdict": "different", "confidence": 0.95})))
    assert out["by_kind"]["normalization"] == {"judged_fold": 1, "ask:meaning_changes": 1}
    assert (memory / "inbox" / "inbox-002.md").exists()


def test_the_decay_judge_keeps_a_live_page_without_calling_it_the_persons_keep(memory):
    from api.services import decay_policy

    _entity(memory, "example-gadget", type="tool", source_episodes=["ep_2026-05-01_001", "ep_2026-06-01_001"])
    _item(memory, "inbox-001", kind="decay", entity_id="example-gadget")
    _entity(memory, "alpha-project", type="project", source_episodes=["ep_2026-05-01_001"])
    _item(memory, "inbox-002", kind="decay", entity_id="alpha-project")
    _commit(memory)
    calls: list = []
    out = run(inbox_tend.tidy(memory, _Settings(memory), dry_run=False, judge=True,
                              llm_fn=_judge_fn({"verdict": "keep", "confidence": 0.95, "reason": "still in use"},
                                               before=calls.append)))
    assert out["by_kind"] == {"decay": {"judged_keep": 1, "ask:judgement": 1}}
    assert len(calls) == 1, "the person's project is never judged"
    fm = markdown_parser.parse(memory / "entities" / "example-gadget.md").frontmatter
    assert fm["status"] == "active" and not decay_policy.kept_dates(fm)


def test_the_judges_never_see_the_owners_page_or_a_persons_identity(memory):
    claims = [Claim(id=f"clm_{k}", text="x", subject="owner-example", predicate="lives-in", object=k,
                    valid_from="2026-05-01", recorded_at="2026-05-01") for k in ("town-a", "town-b")]
    _entity(memory, "owner-example", type="person", owner=True, status="active",
            body=write_claims("## Summary\nO.\n", claims))
    _item(memory, "inbox-001", kind="conflict", entity_id="owner-example", predicate="lives-in",
          options=[{"key": "a", "label": "town-a", "claim_id": "clm_town-a"},
                   {"key": "b", "label": "town-b", "claim_id": "clm_town-b"}])
    _commit(memory)
    calls: list = []
    out = run(inbox_tend.tidy(memory, _Settings(memory), dry_run=True, judge=True,
                              llm_fn=_judge_fn({"verdict": "a", "confidence": 0.99}, before=calls.append)))
    assert calls == [] and out["by_kind"] == {"conflict": {"ask:person": 1}}
