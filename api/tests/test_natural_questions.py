"""Questions come up naturally (owner, 2026-10-14).

An open inbox question reaches the conversation only when the conversation is about that question's own subject
(the ask gate, ``inbox_ask_gate``); an answer the person already gave is recorded with their words as evidence,
without asking; and the whole inbox is listed only when they ask for it. Synthetic bank only (alpha-project,
bob-example); no real bank, no ~/.cicada, no model, no network.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from api.models.schemas import InboxResolveRequest
from api.services import bank_index, inbox_ask_gate, inbox_service, markdown_parser, mcp_tools
from api.services.claims import parse_claims

POLICY = {
    "kind": "conflict", "status": "pending", "priority": 0.8, "entity_id": "alpha-project",
    "entity_name": "Alpha Project", "predicate": "targets-policy",
    "question": "Which policy is Alpha Project actually targeting, strict or lenient?",
    "title": "Which policy is Alpha Project actually targeting, strict or lenient?",
    "allow_other": True, "allow_defer": True, "created_date": "2026-09-20",
    "options": [{"key": "a", "label": "strict", "claim_id": "clm_strict"},
                {"key": "b", "label": "lenient", "claim_id": "clm_lenient"},
                {"key": "both", "label": "Both are true (different contexts)"}],
}
WHO = {"kind": "clarification", "status": "pending", "entity_id": "bob-example", "entity_name": "Bob Example",
       "entity_mention": "Bob", "question": "Who is Bob?", "created_date": "2026-09-20",
       "options": [{"key": "a", "label": "A designer"}]}
DECAY = {"kind": "decay", "status": "pending", "entity_id": "alpha-project", "entity_name": "Alpha Project",
         "title": "No recent mentions of Alpha Project", "created_date": "2026-09-20"}

ENTITY_BODY = """## Summary
Alpha Project is a synthetic fixture.

```claims
- id: clm_strict
  text: Alpha Project targets the strict policy
  subject: alpha-project
  predicate: targets-policy
  object: strict
  object_kind: literal
  observer: agent
  context: general
  source_trust: agent_extracted
  confidence: 0.6
  valid_from: '2026-08-01'
  recorded_at: '2026-08-01'
- id: clm_lenient
  text: Alpha Project targets the lenient policy
  subject: alpha-project
  predicate: targets-policy
  object: lenient
  object_kind: literal
  observer: agent
  context: general
  source_trust: agent_extracted
  confidence: 0.6
  valid_from: '2026-09-01'
  recorded_at: '2026-09-01'
```
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.8,
                           "aliases": ["Alpha"], "source_episodes": [], "related": [], "version": 1},
                          ENTITY_BODY)
    markdown_parser.write(memory / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "status": "active", "confidence": 0.7},
                          "## Summary\nBob Example is a synthetic person.\n")
    markdown_parser.write(memory / "inbox" / "inbox-001.md", dict(POLICY), "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-002.md", dict(WHO), "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-003.md", dict(DECAY), "ctx")
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def _ctx(memory, **kw):
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="unknown", **kw)


# --- the relevance gate --------------------------------------------------------------------------------------------


def test_naming_the_page_is_not_enough_the_conversation_must_be_about_the_question():
    """The reproduction (values redacted): the person asked who helps on the project; the project's open question is
    about its policy. Recall touched the page, so the old contract asked it anyway."""
    assert inbox_ask_gate.relevant(POLICY, "Who helps on the Alpha Project?", ["alpha-project"]) == (
        False, "other_subject")
    assert inbox_ask_gate.relevant({**POLICY, "aliases": ["Alpha"]}, "What policy should Alpha target next quarter?")[0]
    assert inbox_ask_gate.relevant(POLICY, "we went lenient for the alpha project in the end")[0], (
        "an option's own word")
    assert not inbox_ask_gate.relevant(POLICY, "are both contexts fine for alpha project?")[0], (
        "the card's generic 'both' wording is not the subject")


def test_recall_ids_bring_the_page_into_scope_but_never_the_subject():
    assert inbox_ask_gate.relevant(POLICY, "which policy are we on?", ["alpha-project"])[0]
    assert not inbox_ask_gate.relevant(POLICY, "which policy are we on?", ["bob-example"])[0], "another page"
    assert not inbox_ask_gate.relevant(POLICY, "", ["alpha-project"])[0], "no conversation, no question"


def test_an_identity_question_needs_the_name_said_and_decay_never_comes_up():
    assert inbox_ask_gate.relevant(WHO, "can Bob review the designs?")[0]
    assert not inbox_ask_gate.relevant(WHO, "can he review the designs?", ["bob-example"])[0]
    assert inbox_ask_gate.relevant(DECAY, "is Alpha Project still on?", ["alpha-project"]) == (
        False, "never_asked:decay")
    assert not inbox_ask_gate.relevant({**POLICY, "kind": "normalization"}, "alpha policy")[0]


def test_ask_mode_returns_only_the_question_on_the_subject(bank):
    ctx = _ctx(bank)
    off = mcp_tools.check_nudges(ctx, "Who helps on the Alpha Project?", ["alpha-project"], "ask")
    assert "inbox-" not in off and "ask nothing" in off
    on = mcp_tools.check_nudges(ctx, "Which policy is alpha on now?", ["alpha-project"], "ask")
    assert "`inbox-001`" in on and "inbox-002" not in on and "inbox-003" not in on
    assert "Question: Which policy is Alpha Project actually targeting" in on
    assert "strict (option_key=a)" in on and "lenient (option_key=b)" in on


def test_ask_mode_reads_as_something_to_weave_in_not_a_banner(bank):
    on = mcp_tools.check_nudges(_ctx(bank), "Which policy is alpha on now?", ["alpha-project"], "ask")
    assert "in your own words" in on and "no banner" in on
    assert "Cause:" not in on and "(Recommended)" not in on and "a) strict" not in on
    assert 'quote="<their exact words>"' in on and "no need to ask" in on


def test_ask_mode_without_the_persons_words_returns_no_question(bank):
    out = mcp_tools.check_nudges(_ctx(bank), None, ["alpha-project"], "ask")
    assert out == mcp_tools.ASK_NEEDS_TOPIC and "inbox-" not in out


def test_ask_mode_honours_a_skip(bank):
    ctx = _ctx(bank)
    ctx.skipped_inbox_ids.add("inbox-001")
    assert "inbox-001" not in mcp_tools.check_nudges(ctx, "which policy is alpha on", ["alpha-project"], "ask")


def test_recall_brings_a_question_only_when_the_query_is_about_it(bank):
    """Recall's proactive block was a body-text token match: any query naming the project surfaced every question
    about it, decay included."""
    off = mcp_tools._relevant_inbox(bank, "who helps on alpha project")
    assert off == []
    [on] = mcp_tools._relevant_inbox(bank, "alpha project policy")
    assert "Which policy is Alpha Project actually targeting" in on
    assert mcp_tools._relevant_inbox(bank, "alpha project policy", skipped=frozenset({"inbox-001"})) == []


# --- listed on request -------------------------------------------------------------------------------------------


def test_list_mode_lists_every_pending_question_plainly(bank):
    """'What is in my inbox / what conflicts do I have?' — no gate: every visible question, as before."""
    out = mcp_tools.check_nudges(_ctx(bank), None, None, "list")
    assert "Found 3 pending inbox items" in out
    assert "inbox-001" in out and "inbox-002" in out and "inbox-003" in out
    assert out == mcp_tools.check_nudges(_ctx(bank), None, None), "list is the default"
    assert "Error" in mcp_tools.check_nudges(_ctx(bank), None, None, "everything")


def test_the_tool_schema_carries_mode_and_quote():
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("cicada_mcp_server_nq", root / "mcp" / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    tools = {t["name"]: t for t in server.TOOLS}
    assert tools["cicada_check_nudges"]["inputSchema"]["properties"]["mode"]["enum"] == ["ask", "list"]
    assert "quote" in tools["cicada_resolve_inbox"]["inputSchema"]["properties"]


# --- answered naturally ------------------------------------------------------------------------------------------


def test_the_tool_sends_the_persons_words_and_a_remote_app_never_does(bank):
    sent = []

    def post(path, payload):
        sent.append((path, payload))
        return {"status": "resolved", "quoteEpisode": "ep_2026-10-14_001"}

    out = mcp_tools.resolve_inbox(_ctx(bank, post=post), "inbox-001", "b", None, False, None,
                                  quote='  "We switched alpha to the lenient policy last week."  ')
    assert sent == [("/inbox/inbox-001/resolve", {"action": "resolve", "optionKey": "b",
                                                  "quote": "We switched alpha to the lenient policy last week."})]
    assert "ep_2026-10-14_001" in out and "one short line" in out
    sent.clear()
    mcp_tools.resolve_inbox(_ctx(bank, post=post, connector_id="ab12cd34"), "inbox-001", "b", None, False, None,
                            quote="made up words")
    assert sent and "quote" not in sent[0][1], "R-R22: a remote app never records the person's own words"


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.litellm_disambiguation_model = ""
        self.consolidation_model = ""
        self.llm_mode = "byok"

    @property
    def effective_consolidation_model(self) -> str:
        return self.litellm_model


@pytest.fixture
def ledger():
    """The resolution rows an answer emitted (the telemetry ledger: ids and enums only)."""
    return []


@pytest.fixture
def repo(bank, ledger, monkeypatch):
    _git(bank, "init", "-q")
    _git(bank, "config", "user.email", "test@cicada.local")
    _git(bank, "config", "user.name", "Cicada Test")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "seed")

    async def _fake(**kwargs):
        return f"{kwargs['new_description']}"

    monkeypatch.setattr("api.services.conflict_resolver._synthesize_entity_update", _fake)
    monkeypatch.setattr(inbox_service.telemetry, "record", lambda event: ledger.append(event))
    return bank


WORDS = "We switched alpha to the lenient policy last week."


def _claims(memory: Path) -> dict:
    return {c.id: c for c in parse_claims(markdown_parser.parse(memory / "entities" / "alpha-project.md").body)}


def test_an_answer_from_the_conversation_keeps_the_persons_words_as_evidence(repo, ledger):
    out = asyncio.run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", optionKey="b", quote=WORDS), _Settings(repo)))
    assert out["status"] == "resolved" and out["quoteEpisode"]
    ep = out["quoteEpisode"]
    episode = markdown_parser.parse(repo / "episodes" / f"{ep}.md")
    assert WORDS in episode.body and episode.frontmatter["processed_by"] == "user"
    assert episode.frontmatter["source"] == "mcp" and episode.frontmatter["origin"] == "inbox"
    winner = _claims(repo)["clm_lenient"]
    assert winner.valid_to is None and any(e.episode == ep and e.is_span() for e in winner.evidence), (
        "the claim the person picked cites their own words")
    log = _git(repo, "log", "--format=%B")
    assert f"episodes/{ep}.md: created (source: inbox-001, trigger: inbox/conflict/resolved)" in log
    assert "Cicada-Author: user" in log
    assert _git(repo, "status", "--porcelain", "--", "episodes") == "", "the words are committed with the answer"
    [row] = [e for e in ledger if e.kind == "resolution"]
    assert row.refs["answered_in"] == "conversation" and WORDS not in str(row.refs), "ids and enums only"


def test_a_free_text_answer_writes_a_user_claim_citing_the_words(repo):
    asyncio.run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", optionKey="neither", answer="a staged policy",
                                         quote="Honestly neither, alpha is on a staged policy now."),
        _Settings(repo)))
    [mine] = [c for c in _claims(repo).values() if c.source_trust == "user_stated"]
    assert mine.object == "a staged policy" and mine.evidence and mine.evidence[0].is_span()


def test_an_answer_without_words_writes_no_episode(repo, ledger):
    before = sorted(p.name for p in (repo / "episodes").glob("*.md"))
    out = asyncio.run(inbox_service.resolve(
        "inbox-001", InboxResolveRequest(action="resolve", optionKey="b"), _Settings(repo)))
    assert "quoteEpisode" not in out and sorted(p.name for p in (repo / "episodes").glob("*.md")) == before
    [row] = [e for e in ledger if e.kind == "resolution"]
    assert row.refs.get("answered_in") is None


def test_a_refused_answer_leaves_no_orphan_episode(repo):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        asyncio.run(inbox_service.resolve(
            "inbox-001", InboxResolveRequest(action="resolve", optionKey="zz", quote=WORDS), _Settings(repo)))
    assert list((repo / "episodes").glob("*.md")) == []
    assert (repo / "inbox" / "inbox-001.md").exists()
