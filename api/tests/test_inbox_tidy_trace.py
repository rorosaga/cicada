"""The coordinator's inbox trace and its vetted apply (owner rule 2026-10-20: read every proposed answer before any
bulk write).

Synthetic banks only (tool-a, tool-b, example-gadget, alice-example); the engine is a fake; git is real; nothing
reaches a network, a plan or a paid API."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from api.scripts import inbox_tidy_trace
from api.services import bank_index, inbox_tend, markdown_parser, predicates, web_settle

DERIVED = ("search_index.db", "search_index.db-wal", "search_index.db-shm", "vector_index.db")


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


def _entity(memory: Path, eid: str, **fm) -> None:
    base = {"name": eid.replace("-", " ").title(), "type": "concept", "status": "decaying", "confidence": 0.35,
            "created": "2026-01-01", "last_referenced": "2026-05-01", "source_episodes": [], "tags": [],
            "related": [], "version": 1}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", base, f"## Summary\n{base['name']} line.\n")


def _item(memory: Path, item_id: str, **fm) -> Path:
    base = {"status": "pending", "priority": 0.5, "created_date": "2026-09-01"}
    base.update(fm)
    path = memory / "inbox" / f"{item_id}.md"
    markdown_parser.write(path, base, "Context.")
    return path


def _judge(*replies):
    queue = list(replies)
    calls: list = []

    def fn(messages, **_kw):
        calls.append(messages[0]["content"])
        return {"choices": [{"message": {"content": json.dumps(queue.pop(0))}}], "model": "claude-haiku-5-5"}

    fn.calls = calls
    return fn


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(inbox_tend, "_RECORD_READ", {})
    monkeypatch.setattr(inbox_tend, "_TIDY", {"running": False, "report": None, "task": None, "bank": None,
                                              "started_at": None})
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    _entity(m, "owner-example", type="person", owner=True, name="Owner Example", status="active")
    # Two duplicate questions the judge reads, two fading one-offs the rules settle, one question the person keeps.
    _entity(m, "tool-b", type="tool", name="Tool B", status="active")
    _entity(m, "tool-bee", type="tool", name="Tool Bee", status="active")
    _item(m, "inbox-001", kind="merge_suggestion", entity_id="tool-bee", entity_name="Tool Bee",
          merge_target_hint="tool-b", suggested_classification="tool")
    _entity(m, "tool-c", type="tool", name="Tool C", status="active")
    _entity(m, "tool-cee", type="tool", name="Tool Cee", status="active")
    _item(m, "inbox-002", kind="merge_suggestion", entity_id="tool-cee", entity_name="Tool Cee",
          merge_target_hint="tool-c", suggested_classification="tool")
    for n in (3, 4):
        _entity(m, f"gadget-{n}", type="tool", source_episodes=["ep_2026-05-01_001"])
        _item(m, f"inbox-00{n}", kind="decay", entity_id=f"gadget-{n}", entity_name=f"Gadget {n}")
    _item(m, "inbox-005", kind="clarification", entity_id="alice-example", entity_name="Alice Example")
    _commit(m)
    return m


def _bank_files(memory: Path) -> dict[str, bytes]:
    return {p.relative_to(memory).as_posix(): p.read_bytes() for p in sorted(memory.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(memory).parts and p.name not in DERIVED}


def _trace(memory: Path, out: Path, fn, **kw) -> dict:
    return inbox_tidy_trace.run_trace(memory, out, engine="plan", model="haiku", kinds=kw.get("kinds"),
                                      limit=kw.get("limit"), judge=True, settings=_Settings(memory), llm_fn=fn,
                                      engine_label="claude-cli")


def _rows(out: Path) -> dict[str, dict]:
    return {r["id"]: r for r in map(json.loads, out.read_text().splitlines())}


# --------------------------------------------------------------------------- the trace


def test_the_trace_writes_nothing_to_the_bank_and_says_each_answer_in_a_0600_file(memory, tmp_path):
    before, head = _bank_files(memory), _git(memory, "rev-parse", "HEAD")
    out = tmp_path / "trace.jsonl"
    fn = _judge({"verdict": "same", "confidence": 0.97, "reason": "one tool, two spellings"},
                {"verdict": "unsure", "confidence": 0.55, "reason": "too little on either page"})
    counts = _trace(memory, out, fn)

    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    rows = _rows(out)
    assert set(rows) == {"inbox-001", "inbox-002", "inbox-003", "inbox-004", "inbox-005"}
    merge = rows["inbox-001"]
    assert merge["kind"] == "merge_suggestion" and merge["names"] == ["Tool Bee", "Tool B"]
    assert merge["decision"] == "merge" and merge["confidence"] == 0.97 and merge["judged"] is True
    assert merge["reason"] == "one tool, two spellings" and merge["apply"]["rule"] == "judged_same"
    unsure = rows["inbox-002"]
    assert unsure["decision"] == "leave" and unsure["confidence"] == 0.55 and "apply" not in unsure
    assert unsure["reason"] == "too little on either page"
    fading = rows["inbox-003"]
    assert fading["decision"] == "settle" and fading["rule"] == "one_off" and fading["confidence"] is None
    assert fading["reason"] == inbox_tend.RULES["one_off"] and fading["names"] == ["Gadget 3"]
    assert rows["inbox-005"]["decision"] == "leave"
    assert counts["trace_rows"] == 5 and counts["dry_run"] is True

    # Nothing written: no page, no question, no commit, no settled record, no saved tidy counts, no stdout text.
    assert _bank_files(memory) == before
    assert _git(memory, "rev-parse", "HEAD") == head and not _git(memory, "status", "--porcelain").strip()
    assert not (tmp_path / "home" / inbox_tend.TIDY_DIR).exists()
    assert "Tool" not in json.dumps(counts) and "Gadget" not in json.dumps(counts)


def test_kind_and_limit_narrow_the_trace_and_the_judge_reads_only_those(memory, tmp_path):
    out = tmp_path / "trace.jsonl"
    fn = _judge({"verdict": "different", "confidence": 0.93, "reason": "two tools"})
    _trace(memory, out, fn, kinds=frozenset({"merge_suggestion"}), limit=1)
    rows = _rows(out)
    assert list(rows) == ["inbox-001"] and rows["inbox-001"]["decision"] == "keep_apart"
    assert len(fn.calls) == 1


def test_the_trace_file_is_0600_even_over_an_open_file_and_never_inside_a_bank(memory, tmp_path, monkeypatch):
    out = tmp_path / "old.jsonl"
    out.write_text("stale\n")
    os.chmod(out, 0o644)
    inbox_tidy_trace.TraceFile(out).close()
    assert stat.S_IMODE(out.stat().st_mode) == 0o600 and out.read_text() == ""

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "root"))
    inside = memory / "trace.jsonl"
    code = inbox_tidy_trace.main(["trace", "--bank", str(memory), "--out", str(inside), "--no-judge"])
    assert code == 2 and not inside.exists()
    (tmp_path / "root" / "other-bank").mkdir(parents=True)
    in_root = tmp_path / "root" / "other-bank" / "trace.jsonl"
    code = inbox_tidy_trace.main(["trace", "--bank", str(memory), "--out", str(in_root), "--no-judge"])
    assert code == 2 and not in_root.exists()


def test_engine_plan_judges_on_the_plan_with_haiku_and_never_the_configured_engine(memory, tmp_path, monkeypatch):
    import litellm

    from api.config import Settings
    from api.services import agent_engine, engine_select, telemetry

    def never(*_a, **_k):
        raise AssertionError("the configured engine was used")

    async def never_async(*_a, **_k):
        raise AssertionError("the configured engine was resolved")

    monkeypatch.setattr(litellm, "completion", never)
    monkeypatch.setattr(engine_select, "resolve_settings", never_async)
    monkeypatch.setattr(telemetry, "record", never)   # and nothing reaches the ledger
    seen: list = []

    def plan_call(*, messages, model, stage, **_kw):
        seen.append((model, stage))
        return {"result": json.dumps({"verdict": "same", "confidence": 0.95, "reason": "one tool"}),
                "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr(agent_engine, "complete", plan_call)
    metered = Settings().model_copy(update={"memory_path": memory, "llm_mode": "byok",
                                            "litellm_model": "openrouter/example/metered"})
    out = tmp_path / "trace.jsonl"
    inbox_tidy_trace.run_trace(memory, out, engine="plan", model="haiku", kinds=frozenset({"merge_suggestion"}),
                               limit=1, judge=True, settings=metered)
    assert seen == [("haiku", inbox_tend.STAGE)]
    row = _rows(out)["inbox-001"]
    assert row["decision"] == "merge" and row["apply"]["engine"] == "claude-cli"


# --------------------------------------------------------------------------- the vetted apply


def test_apply_settles_only_the_listed_ids_each_as_sleeps_undoable_commit(memory, tmp_path):
    out = tmp_path / "trace.jsonl"
    _trace(memory, out, _judge({"verdict": "same", "confidence": 0.97, "reason": "one tool"},
                               {"verdict": "unsure", "confidence": 0.5}))
    rows = _rows(out)
    kept = [rows["inbox-001"], rows["inbox-003"]]          # the coordinator deleted inbox-004's line
    head = _git(memory, "rev-parse", "HEAD").strip()

    result = run(inbox_tend.apply_vetted(memory, _Settings(memory), kept))
    assert [(r["id"], r["outcome"]) for r in result["results"]] == [("inbox-001", "settled"),
                                                                   ("inbox-003", "settled")]
    inbox = {p.stem for p in (memory / "inbox").glob("inbox-*.md")}
    assert inbox == {"inbox-002", "inbox-004", "inbox-005"}, "only the listed ids moved"
    assert not (memory / "entities" / "tool-bee.md").exists(), "the vetted merge folded the duplicate"
    assert markdown_parser.parse(memory / "entities" / "gadget-4.md").frontmatter["status"] == "decaying"
    log = _git(memory, "log", "--format=%s", f"{head}..HEAD")
    assert log.count("Inbox settled by Sleep") == 2
    settled = {s["id"]: s for s in web_settle.list_settled(memory)}
    assert settled["inbox-001"]["reason"] == "one tool"
    assert not _git(memory, "status", "--porcelain").strip()

    _r, paths, lines, _rec = inbox_tend.undo(memory, "inbox-003")   # Sleep's commit, taken back like any other
    web_settle.commit_sync(memory, web_settle.commit_message("Sleep's settle undone", lines, authors=["user"]), paths)
    assert (memory / "inbox" / "inbox-003.md").exists()


def test_apply_never_settles_a_row_that_moved_or_asks_for_more_than_the_trace_said(memory, tmp_path):
    out = tmp_path / "trace.jsonl"
    _trace(memory, out, _judge({"verdict": "same", "confidence": 0.97}, {"verdict": "unsure", "confidence": 0.5}))
    rows = _rows(out)
    other_target = json.loads(json.dumps(rows["inbox-001"]))
    other_target["apply"]["request"]["merge_target"] = "tool-c"            # an edit that names another page
    page = memory / "entities" / "gadget-3.md"
    page.write_text(page.read_text() + "\nStill in use.\n")                 # a page the decision read, changed
    _commit(memory, "the person's edit")
    question = memory / "inbox" / "inbox-004.md"
    question.write_text(question.read_text() + "\nMore context.\n")         # the question itself, changed
    _commit(memory, "the question moved")
    undecided = rows["inbox-002"]                                           # a "leave" row has nothing to apply

    result = run(inbox_tend.apply_vetted(memory, _Settings(memory),
                                         [other_target, rows["inbox-003"], rows["inbox-004"], undecided]))
    outcomes = {r["id"]: (r["outcome"], r.get("why")) for r in result["results"]}
    assert outcomes == {"inbox-001": ("refused", "other_target"), "inbox-003": ("refused", "changed"),
                        "inbox-004": ("refused", "changed"), "inbox-002": ("refused", "not_decided")}
    assert result["settled"] == 0
    assert {p.stem for p in (memory / "inbox").glob("inbox-*.md")} == {f"inbox-00{n}" for n in range(1, 6)}
    assert (memory / "entities" / "tool-bee.md").exists()
    assert "Inbox settled by Sleep" not in _git(memory, "log", "--format=%s")


def _forged(memory: Path, item_id: str, kind: str, **plan) -> dict:
    """A row nobody traced: the question file's own hash (so only the server's own checks stand in the way)."""
    raw = (memory / "inbox" / f"{item_id}.md").read_bytes()
    return {"id": item_id, "kind": kind, "apply": {"item_sha256": inbox_tend._sha256(raw), "guard": {}, **plan}}


def test_apply_refuses_a_forged_merge_of_two_people(memory):
    """Review of #393 (a): two person pages the policy leaves to the person (``person``), merged by a row that says
    ``judged_same`` with an empty guard."""
    _entity(memory, "bob-example", type="person", name="Bob Example", status="active")
    _entity(memory, "bob-example-2", type="person", name="Bob example", status="active")
    _item(memory, "inbox-009", kind="merge_suggestion", entity_id="bob-example-2", entity_name="Bob example",
          merge_target_hint="bob-example", suggested_classification="person")
    _commit(memory)
    row = _forged(memory, "inbox-009", "merge_suggestion", rule="judged_same",
                  request={"action": "merge", "merge_target": "bob-example"}, model="claude-haiku-5-5",
                  engine="claude-cli")
    full_guard = {**row, "apply": {**row["apply"], "guard": inbox_tend._guard(memory, "bob-example-2", "bob-example")}}
    result = run(inbox_tend.apply_vetted(memory, _Settings(memory), [row]))
    assert result["results"] == [{"id": "inbox-009", "outcome": "refused", "why": "not_judged"}]
    result = run(inbox_tend.apply_vetted(memory, _Settings(memory), [full_guard]))
    assert result["results"][0]["why"] == "not_judged", "a full guard changes nothing: who someone is stays theirs"
    assert (memory / "entities" / "bob-example-2.md").exists() and (memory / "inbox" / "inbox-009.md").exists()


def test_apply_refuses_a_forged_answer_to_a_name_question(memory):
    """Review of #393 (b): a relation-titled person's name question answered by a row claiming ``judged_conflict``
    with a free ``answer`` and no quote — never; and not even as ``said_on_record`` without the person's own words."""
    from api.services import role_people

    _entity(memory, "partner", type="person", name="Partner", status="active", **{role_people.UNNAMED_KEY: True})
    _item(memory, "inbox-010", kind="clarification", asks="name", entity_id="partner", entity_name="Partner",
          question="What's the name of your partner?", options=[{"key": "decline", "label": "Rather not say"}])
    _commit(memory)
    page = (memory / "entities" / "partner.md").read_bytes()
    forged = [
        _forged(memory, "inbox-010", "clarification", rule="judged_conflict",
                request={"action": "resolve", "option_key": "decline", "answer": "Alex Example"}),
        _forged(memory, "inbox-010", "clarification", rule="said_on_record",
                request={"action": "answer", "answer": "Alex Example"}, guard=inbox_tend._guard(memory, "partner")),
        _forged(memory, "inbox-010", "clarification", rule="said_on_record",
                request={"action": "answer", "answer": "Alex Example"}, guard=inbox_tend._guard(memory, "partner"),
                quote={"episode": "ep_2026-10-01_001", "quote": "my partner is Alex Example"}),
    ]
    whys = []
    for row in forged:
        result = run(inbox_tend.apply_vetted(memory, _Settings(memory), [row]))
        assert result["results"][0]["outcome"] == "refused"
        whys.append(result["results"][0]["why"])
    assert whys == ["bad_rule", "bad_quote", "not_the_persons_words"]
    assert (memory / "entities" / "partner.md").read_bytes() == page and (memory / "inbox" / "inbox-010.md").exists()


def test_apply_refuses_a_traced_judgement_whose_guard_was_emptied_and_authors_a_rule_as_sleep(memory, tmp_path):
    out = tmp_path / "trace.jsonl"
    _trace(memory, out, _judge({"verdict": "same", "confidence": 0.97}, {"verdict": "unsure", "confidence": 0.5}))
    rows = _rows(out)
    emptied = json.loads(json.dumps(rows["inbox-001"]))
    emptied["apply"]["guard"] = {}
    bad_author = json.loads(json.dumps(rows["inbox-001"]))
    bad_author["apply"]["model"] = "Someone Else <x@example.com>"
    rule_row = json.loads(json.dumps(rows["inbox-003"]))
    rule_row["apply"].update(model="claude-haiku-5-5", engine="claude-cli")   # an engine-free rule naming a model
    result = run(inbox_tend.apply_vetted(memory, _Settings(memory), [emptied, bad_author, rule_row]))
    assert [(r["id"], r["outcome"], r.get("why")) for r in result["results"]] == [
        ("inbox-001", "refused", "thin_guard"), ("inbox-001", "refused", "duplicate"), ("inbox-003", "settled", None)]
    message = _git(memory, "log", "-1", "--fixed-strings", "--grep=Inbox settled by Sleep", "--format=%B")
    assert "claude-haiku" not in message, "an engine-free settle is Sleep's own, whatever the row says"
    result = run(inbox_tend.apply_vetted(memory, _Settings(memory), [bad_author]))
    assert result["results"][0]["why"] == "bad_model"
    assert (memory / "entities" / "tool-bee.md").exists()


def test_the_apply_route_settles_the_vetted_rows_and_refuses_while_a_tidy_runs(memory, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    out = tmp_path / "trace.jsonl"
    _trace(memory, out, _judge({"verdict": "unsure", "confidence": 0.5}, {"verdict": "unsure", "confidence": 0.5}))
    vetted = tmp_path / "vetted.jsonl"
    vetted.write_text("\n".join(line for line in out.read_text().splitlines() if '"inbox-004"' in line) + "\n")
    rows, skipped = inbox_tidy_trace.vetted_rows(vetted)
    assert [r["id"] for r in rows] == ["inbox-004"] and skipped == 0

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    monkeypatch.setitem(inbox_tend._TIDY, "running", True)
    assert client.post("/inbox/tidy/apply", json={"decisions": rows}).status_code == 409
    monkeypatch.setitem(inbox_tend._TIDY, "running", False)
    assert client.post("/inbox/tidy/apply", json={"decisions": []}).status_code == 422
    body = client.post("/inbox/tidy/apply", json={"decisions": rows}).json()
    assert body["results"] == [{"id": "inbox-004", "outcome": "settled"}] and body["settled"] == 1
    assert not (memory / "inbox" / "inbox-004.md").exists() and (memory / "inbox" / "inbox-003.md").exists()
    assert not inbox_tend.tidy_running()
    config.get_settings.cache_clear()


def test_the_apply_command_sends_only_the_kept_rows_to_the_backend_route(tmp_path, monkeypatch, capsys):
    import contextvars
    from types import SimpleNamespace

    from api import cli, cli_app

    vetted = tmp_path / "vetted.jsonl"
    vetted.write_text("\n".join(json.dumps(r) for r in (
        {"id": "inbox-001", "kind": "decay", "names": ["Gadget 1"], "decision": "settle", "apply": {"rule": "one_off"}},
        {"id": "inbox-002", "kind": "merge_suggestion", "decision": "leave"},
    )) + "\n")
    sent: list = []
    boot = SimpleNamespace(client=False, pin=SimpleNamespace(name="default"), ctx=contextvars.copy_context(),
                           probe={})
    monkeypatch.setattr(cli, "bootstrap", lambda: boot)

    def call(b, method, path, *, body=None, timeout=None, **_kw):
        assert b.probe == {"state": "unverified"}, "the memory root is confirmed before the write"
        sent.append((method, path, body))
        return {"settled": 1, "results": [{"id": "inbox-001", "outcome": "settled"}]}

    monkeypatch.setattr(cli_app, "call", call)
    assert inbox_tidy_trace.main(["apply", "--vetted", str(vetted), "--bank", "default"]) == 0
    assert sent == [("POST", "/inbox/tidy/apply",
                     {"decisions": [{"id": "inbox-001", "kind": "decay", "apply": {"rule": "one_off"}}]})]
    printed = json.loads(capsys.readouterr().out)
    assert printed["skipped"] == 1 and "Gadget" not in json.dumps(printed)
    assert inbox_tidy_trace.main(["apply", "--vetted", str(vetted), "--bank", "other"]) == 1   # asserts, never selects
    assert len(sent) == 1


def _person_turn(memory: Path, eid: str, line: str) -> None:
    markdown_parser.write(memory / "episodes" / f"{eid}.md",
                          {"id": eid, "timestamp": f"{eid[3:13]}T09:00:00+00:00", "processed": True, "title": "chat"},
                          f"user: {line}\n\nassistant: Noted.")


def test_apply_refuses_the_persons_words_that_do_not_say_the_name(memory):
    """Review of #393 (re-review): a located quote that says nothing about who the person is — a run in the morning —
    never names a relation-titled page, and the engine's own reading (`_answer_decision`) agrees."""
    from api.services import role_people

    _entity(memory, "sister", type="person", name="Sister", status="active", **{role_people.UNNAMED_KEY: True})
    _entity(memory, "carol-example", type="person", name="Carol Example", status="active")
    _item(memory, "inbox-011", kind="clarification", asks="name", entity_id="sister", entity_name="Sister",
          question="What's the name of your sister?", options=[{"key": "decline", "label": "Rather not say"}])
    _person_turn(memory, "ep_2026-10-02_001", "I went running this morning and then made coffee")
    _person_turn(memory, "ep_2026-10-03_001", "my sister is Carol Example, she visits next week")
    _commit(memory)
    assert inbox_tend.persons_span(memory, "ep_2026-10-02_001", "I went running this morning") is not None

    def row(quote_episode, quote):
        return _forged(memory, "inbox-011", "clarification", rule="said_on_record",
                       request={"action": "answer", "answer": "Carol Example"}, guard=inbox_tend._guard(memory, "sister"),
                       quote={"episode": quote_episode, "quote": quote})

    pages = sorted(p.name for p in (memory / "entities").iterdir())
    result = run(inbox_tend.apply_vetted(memory, _Settings(memory), [row("ep_2026-10-02_001",
                                                                         "I went running this morning")]))
    assert result["results"] == [{"id": "inbox-011", "outcome": "refused", "why": "quote_says_otherwise"}]
    assert sorted(p.name for p in (memory / "entities").iterdir()) == pages and (memory / "inbox/inbox-011.md").exists()
    d, _engine = inbox_tend.vetted_decision(memory, row("ep_2026-10-03_001", "my sister is Carol Example"))
    assert d.request == {"action": "answer", "answer": "Carol Example"}, "words that say the name still settle"

    path = memory / "inbox" / "inbox-011.md"
    fm = markdown_parser.parse(path).frontmatter
    reply = {"answered": True, "answer": "Carol Example", "quote": "I went running this morning"}
    assert inbox_tend._answer_decision(memory, path, fm, reply, {}, "ep_2026-10-02_001", "m", "said_on_record") == (
        None, "quote_says_otherwise")


def test_apply_refuses_a_conflict_side_the_quoted_words_do_not_state(memory):
    from api.services.claims import Claim, write_claims

    claims = [Claim(id="clm_h", text="Tool A is an agent harness", subject="tool-a", predicate="description",
                    object="agent harness", valid_from="2026-05-01"),
              Claim(id="clm_g", text="Tool A is an AI agent", subject="tool-a", predicate="description",
                    object="AI agent", valid_from="2026-05-01")]
    _entity(memory, "tool-a", type="tool", name="Tool A", status="active")
    page = memory / "entities" / "tool-a.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, claims))
    _item(memory, "inbox-012", kind="conflict", entity_id="tool-a", entity_name="Tool A", predicate="description",
          options=[{"key": "a", "label": "agent harness", "claim_id": "clm_h"},
                   {"key": "b", "label": "AI agent", "claim_id": "clm_g"}])
    _person_turn(memory, "ep_2026-06-01_001", "I went running this morning and then made coffee")
    _person_turn(memory, "ep_2026-06-02_001", "these days Tool A is really an agent harness for me")
    _commit(memory)

    def row(episode, quote):
        return _forged(memory, "inbox-012", "conflict", rule="said_on_record",
                       request={"action": "resolve", "option_key": "a"}, guard=inbox_tend._guard(memory, "tool-a"),
                       quote={"episode": episode, "quote": quote})

    result = run(inbox_tend.apply_vetted(memory, _Settings(memory), [row("ep_2026-06-01_001",
                                                                         "I went running this morning")]))
    assert result["results"] == [{"id": "inbox-012", "outcome": "refused", "why": "quote_says_otherwise"}]
    assert (memory / "inbox" / "inbox-012.md").exists()
    d, _engine = inbox_tend.vetted_decision(memory, row("ep_2026-06-02_001", "Tool A is really an agent harness"))
    assert d.request == {"action": "resolve", "option_key": "a"}


def test_apply_refuses_an_answer_made_only_of_filler_words(memory):
    """Re-review of #393: "the" is in every quote — a name or a free answer of fillers alone says nothing."""
    from api.services import role_people

    _entity(memory, "sister", type="person", name="Sister", status="active", **{role_people.UNNAMED_KEY: True})
    _item(memory, "inbox-013", kind="clarification", asks="name", entity_id="sister", entity_name="Sister",
          question="What's the name of your sister?", options=[{"key": "decline", "label": "Rather not say"}])
    _entity(memory, "example-gadget", type="tool", name="Example Gadget", status="active")
    _item(memory, "inbox-014", kind="clarification", entity_id="example-gadget", entity_name="Example Gadget",
          question="What is Example Gadget?")
    _person_turn(memory, "ep_2026-10-02_001", "I went to the gym this morning")
    _commit(memory)
    quote = {"episode": "ep_2026-10-02_001", "quote": "I went to the gym this morning"}
    rows = [_forged(memory, "inbox-013", "clarification", rule="said_on_record", quote=quote,
                    request={"action": "answer", "answer": "the"}, guard=inbox_tend._guard(memory, "sister")),
            _forged(memory, "inbox-014", "clarification", rule="said_on_record", quote=quote,
                    request={"action": "answer", "answer": "the a of"},
                    guard=inbox_tend._guard(memory, "example-gadget"))]
    pages = sorted(p.name for p in (memory / "entities").iterdir())
    result = run(inbox_tend.apply_vetted(memory, _Settings(memory), rows))
    assert [(r["id"], r["outcome"], r.get("why")) for r in result["results"]] == [
        ("inbox-013", "refused", "quote_says_otherwise"), ("inbox-014", "refused", "quote_says_otherwise")]
    assert sorted(p.name for p in (memory / "entities").iterdir()) == pages
    path = memory / "inbox" / "inbox-013.md"
    reply = {"answered": True, "answer": "the", "quote": "I went to the gym this morning"}
    assert inbox_tend._answer_decision(memory, path, markdown_parser.parse(path).frontmatter, reply, {},
                                       "ep_2026-10-02_001", "m", "said_on_record") == (None, "quote_says_otherwise")
