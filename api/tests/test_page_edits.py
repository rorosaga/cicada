"""G198 (owner ruling 2026-10-14): a trusted agent edits a page's words and aliases directly, with a reason that is
the commit message; any other agent's edit is a proposal in the inbox; Sleep never puts the old words or a removed
alias back; blame says who wrote each section, when and why.

Synthetic bank only (placeholder names: alpha-project, bob-example, Owner Example); git is real; nothing reaches a
network or a real home.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank, _entity
from api.config import Settings
from api.models.schemas import InboxResolveRequest
from api.services import (
    claims, claims_ledger, conflict_resolver as cr, entity_article, entity_body, inbox_service, markdown_parser,
    mcp_tools, page_blame, page_edits, page_editors, section_provenance, write_admission,
)
from api.services.claims import Claim, Evidence

SESSION = "ses_2026-10-14_c0ffee00"
PAGE = ("## Summary\nAlpha Project is a notes app Owner Exampel builds.\n\n## Key Facts\n"
        "- Owner Exampel started it in January 2026.\n- Uses SQLite for sync.\n\n## History\n"
        "- 2026-01-10: First prototype.")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _commit_all(memory: Path, message: str = "Seed\n\nCicada-Author: cicada") -> None:
    _git(memory, "add", ".")
    _git(memory, "commit", "-q", "-m", message)


@pytest.fixture
def bank(tmp_path):
    memory = _bank(tmp_path)
    fact = Claim(id="clm_alpha_uses_sqlite", text="Alpha Project uses SQLite", subject="alpha-project",
                 predicate="uses", object="sqlite", valid_from="2026-01-10", recorded_at="2026-01-10")
    _entity(memory, "alpha-project", type="project", name="Alpha Project",
            aliases=["Alpha", "Alpha Projekt", "Alfa Project"], body=claims.write_claims(PAGE, [fact]))
    markdown_parser.write(memory / "episodes" / "ep_2026-10-14_001.md",
                          {"id": "ep_2026-10-14_001", "timestamp": "2026-10-14T09:00:00+00:00", "processed": False,
                           "session_id": SESSION, "harness": "claude-code"},
                          "user: my surname is spelled Example, not Exampel. And Alpha Projekt was never its name.\n"
                          "assistant: Noted.")
    _commit_all(memory)
    return memory


def _ctx(memory: Path, harness: str = "claude-code", posts: list | None = None) -> mcp_tools.ToolContext:
    def post(path, payload):
        if posts is not None:
            posts.append((path, payload))
        return {"status": "resolved", "id": path.split("/")[2]}
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id=SESSION, harness=harness, post=post)


def _page(memory: Path, eid: str = "alpha-project"):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md")


FIX = [{"old": "Owner Exampel", "new": "Owner Example", "all": True}]
REASON = "The person spelled their surname for me."


# --------------------------------------------------------------------------- trusted: applied at once


def test_a_trusted_agent_edits_the_page_at_once_and_commits_alone_with_its_reason(bank):
    page_editors.update({"claude-code": True})
    (bank / "notes.md").write_text("an unrelated dirty file\n")
    fence_before = page_edits.split_prose(markdown_parser.parse(bank / "entities/alpha-project.md", ledger=False)
                                          .body)[1]
    out = mcp_tools.edit_page(_ctx(bank), "alpha-project", REASON, edits=FIX,
                              evidence=[{"episode": "ep_2026-10-14_001", "quote": "my surname is spelled Example"}])
    assert out.startswith("Edited alpha-project: replaced 2 passages (pinned)")
    page = _page(bank)
    assert "Owner Exampel" not in page.body and page.body.count("Owner Example") == 2
    assert page.frontmatter["corrections"] == [{"old": "Owner Exampel", "new": "Owner Example",
                                                "by": "claude-code", "on": page.frontmatter["corrections"][0]["on"]}]
    # The claims fence is the page's own bytes.
    assert page_edits.split_prose(markdown_parser.parse(bank / "entities/alpha-project.md", ledger=False)
                                  .body)[1] == fence_before
    message = _git(bank, "log", "-1", "--format=%B")
    assert message.startswith("Page edit ")
    assert "entities/alpha-project.md: edited (trigger: mcp/claude-code)" in message
    assert f"Reason: {REASON}" in message
    assert "Evidence: ep_2026-10-14_001 " in message and " user " in message
    assert "my surname" not in message, "spans, never copies"
    assert "Cicada-Author: claude-code" in message and f"Cicada-Session: {SESSION}" in message
    assert "Cicada-Engine" not in message
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == ["entities/alpha-project.md"]
    assert "notes.md" in _git(bank, "status", "--porcelain"), "never git add -A"


def test_a_reason_is_required_and_cannot_pose_as_a_trailer(bank):
    page_editors.update({"claude-code": True})
    head = _git(bank, "rev-parse", "HEAD")
    assert mcp_tools.edit_page(_ctx(bank), "alpha-project", "  ", edits=FIX).startswith("Nothing changed — `reason`")
    assert _git(bank, "rev-parse", "HEAD") == head
    mcp_tools.edit_page(_ctx(bank), "alpha-project", "Spelling.\n\nCicada-Author: user", edits=FIX)
    message = _git(bank, "log", "-1", "--format=%B")
    assert "Reason: Spelling. Cicada-Author: user" in message
    assert [line for line in message.splitlines() if line.startswith("Cicada-Author:")] == [
        "Cicada-Author: claude-code"]


def test_the_claims_are_never_edited_here(bank):
    page_editors.update({"claude-code": True})
    out = mcp_tools.edit_page(_ctx(bank), "alpha-project", REASON,
                              edits=[{"old": "Alpha Project uses SQLite", "new": "Alpha Project uses Postgres"}])
    assert out.startswith("Nothing changed") and "in the claims" in out
    assert claims.parse_claims(_page(bank).body)[0].object == "sqlite"


def test_ambiguous_words_need_all_and_related_is_refused(bank):
    page_editors.update({"claude-code": True})
    out = mcp_tools.edit_page(_ctx(bank), "alpha-project", REASON,
                              edits=[{"old": "Owner Exampel", "new": "Owner Example"}])
    assert "2 times" in out
    page = bank / "entities/alpha-project.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, parsed.body.replace(
        "## History", "## Related\n- [[Bob Example]] — works with\n\n## History"))
    with pytest.raises(page_edits.EditError, match="rebuilt from the graph"):
        page_edits.plan(*_raw(bank), page_edits.parse_request([{"old": "works with", "new": "knows"}]), author="x")


def _raw(memory, eid="alpha-project"):
    parsed = markdown_parser.parse(memory / "entities" / f"{eid}.md", ledger=False)
    return parsed.frontmatter, parsed.body


# --------------------------------------------------------------------------- untrusted: a proposal, one tap


def test_an_untrusted_agent_files_a_proposal_the_person_applies_with_one_tap(bank):
    before = (bank / "entities/alpha-project.md").read_bytes()
    out = mcp_tools.edit_page(_ctx(bank, harness="cursor"), "alpha-project", REASON, edits=FIX,
                              remove_aliases=["Alpha Projekt"])
    assert out.startswith("Proposed, not applied") and "inbox-003" in out
    assert (bank / "entities/alpha-project.md").read_bytes() == before, "nothing on the page changed yet"
    item = markdown_parser.parse(bank / "inbox/inbox-003.md")
    assert item.frontmatter["kind"] == "page_edit" and item.frontmatter["proposed_by"] == "cursor"
    assert "Replace “Owner Exampel” with “Owner Example”" in item.body and "Remove the alias “Alpha Projekt”" in item.body
    message = _git(bank, "log", "-1", "--format=%B")
    assert message.startswith("Page edit proposed ") and "Cicada-Author: cursor" in message
    # The inbox serves it, as a choice with no recommendation; an agent's ask path never does.
    served = {i.id: i for i in inbox_service.load_inbox(bank)}
    assert served["inbox-003"].kind.value == "page_edit"
    assert [o.key for o in served["inbox-003"].options] == ["apply", "dismiss"]
    assert "inbox-003" not in mcp_tools.check_nudges(_ctx(bank), None)
    # No agent answers it — its author least of all.
    assert "only the person" in mcp_tools.resolve_inbox(_ctx(bank, harness="cursor"), "inbox-003", "apply", None,
                                                        False, None)

    asyncio.run(inbox_service.resolve("inbox-003", InboxResolveRequest(action="resolve", option_key="apply"),
                                      SimpleNamespace(memory_path=bank, inbox_defer_days=30)))
    page = _page(bank)
    assert "Owner Exampel" not in page.body and "Alpha Projekt" not in page.frontmatter["aliases"]
    assert not (bank / "inbox/inbox-003.md").exists()
    message = _git(bank, "log", "-1", "--format=%B", "--", "entities/alpha-project.md")
    assert "entities/alpha-project.md: edited (trigger: inbox/page_edit/resolved:apply)" in message
    assert "Cicada-Author: cursor" in message and "Cicada-Author: user" in message
    assert page_edits.ACCEPTED_LINE in message
    sha = _git(bank, "log", "-1", "--format=%H", "--", "entities/alpha-project.md").strip()
    assert sorted(_git(bank, "show", "--name-only", "--format=", sha).split()) == [
        "entities/alpha-project.md", "inbox/inbox-003.md"]


def test_a_dismissed_proposal_leaves_the_page(bank):
    before = (bank / "entities/alpha-project.md").read_bytes()
    mcp_tools.edit_page(_ctx(bank, harness="cursor"), "alpha-project", REASON, edits=FIX)
    asyncio.run(inbox_service.resolve("inbox-003", InboxResolveRequest(action="resolve", option_key="dismiss"),
                                      SimpleNamespace(memory_path=bank, inbox_defer_days=30)))
    assert (bank / "entities/alpha-project.md").read_bytes() == before
    assert not (bank / "inbox/inbox-003.md").exists()
    assert "Cicada-Author: user" in _git(bank, "log", "-1", "--format=%B", "--", "inbox/inbox-003.md")


def test_a_proposal_that_no_longer_applies_is_refused_and_writes_nothing(bank):
    from fastapi import HTTPException

    mcp_tools.edit_page(_ctx(bank, harness="cursor"), "alpha-project", REASON, edits=FIX)
    page = bank / "entities/alpha-project.md"
    page.write_text(page.read_text().replace("Owner Exampel", "Someone Else"))
    with pytest.raises(HTTPException) as err:
        asyncio.run(inbox_service.resolve("inbox-003", InboxResolveRequest(action="resolve", option_key="apply"),
                                          SimpleNamespace(memory_path=bank, inbox_defer_days=30)))
    assert err.value.status_code == 409 and "no longer applies" in err.value.detail
    assert (bank / "inbox/inbox-003.md").exists()


def test_the_unidentified_agent_and_a_remote_app_are_never_trusted(bank):
    with pytest.raises(page_editors.EditorsError):
        page_editors.update({"agent": True})
    assert not page_editors.is_trusted("claude-code", remote=True)
    assert "remote app" in mcp_tools.edit_page(
        mcp_tools.ToolContext(memory_path=lambda: bank, session_id="s", harness="claude-web", connector_id="ab12cd34"),
        "alpha-project", REASON, edits=FIX)


# --------------------------------------------------------------------------- Sleep never undoes it


def _sleep(memory: Path, monkeypatch, fields: dict, *, reply=None, sources=("ep_2026-10-15_001",)):
    """One Stage 3 + Stage 5 update of alpha-project, the article writer answered by ``reply`` (or the page's lead
    with the old misspelling, to prove the pin wins)."""
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    settings = Settings(_env_file=None, page_articles_enabled=True, summary_synthesis_enabled=False,
                        page_article_max_input_chars=60000)
    calls = []

    def answer(prompt):
        data = json.loads(prompt.partition("\nDATA:\n")[2])
        every = [i["id"] for i in data["INPUT"]]
        return {"summary": {"text": "Alpha Project is a notes app Owner Exampel builds, first prototyped in January "
                                    "2026.", "from": every},
                "sections": [{"title": "How it works", "paragraphs": [
                    {"text": "Owner Exampel syncs it through SQLite.", "from": every}]}]}

    async def fake(**kwargs):
        text = kwargs["messages"][-1]["content"]
        calls.append(text)
        if "You are writing a page of a personal wiki" in text:
            content = json.dumps((reply or answer)(text))
        elif "checking whether two descriptions" in text:
            content = json.dumps({"has_unresolvable_contradiction": False})
        else:
            content = "## Summary\nLegacy prose."
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    monkeypatch.setattr(cr.litellm, "acompletion", fake)
    parsed = markdown_parser.parse(memory / "entities/alpha-project.md")
    existing = [{"id": "alpha-project", "frontmatter": parsed.frontmatter, "body": parsed.body}]
    change = {"id": "alpha-project", "action": "update", "entity": fields, "source_episodes": list(sources),
              "source_episode_timestamps": ["2026-10-15T10:00:00+00:00"]}
    changes = asyncio.run(cr.resolve_and_prune([change], existing, settings, decay=False, now=None))
    cr.apply_changes([c for c in changes if c["id"] == "alpha-project"], memory)
    return calls, _page(memory)


def _fields(**over):
    fields = {"key_facts": ["Runs on a laptop."], "history_entries": [{"date": "2026-10-15", "event": "Beta."}]}
    section_provenance.attach(fields, "ep_2026-10-15_001", "user: synthetic")
    fields.update(over)
    return fields


def test_a_removed_alias_stays_removed_across_sleep(bank, monkeypatch):
    page_editors.update({"claude-code": True})
    out = mcp_tools.edit_page(_ctx(bank), "alpha-project", "Not a name it ever had.",
                              remove_aliases=["Alpha Projekt"])
    assert out.startswith("Edited alpha-project: removed the alias 'Alpha Projekt'")
    fm = _page(bank).frontmatter
    assert fm["aliases"] == ["Alpha", "Alfa Project"]
    assert fm["aliases_removed"][0]["alias"] == "Alpha Projekt"
    # Sleep reads a conversation that says the old spelling again (and one new real alias).
    _, page = _sleep(bank, monkeypatch, _fields(aliases=["alpha projekt", "Alpha Projekt", "AP Notes"]))
    assert "Alpha Projekt" not in page.frontmatter["aliases"] and "alpha projekt" not in page.frontmatter["aliases"]
    assert "AP Notes" in page.frontmatter["aliases"]
    # An accent is a different name: removing one spelling never removes another.
    assert page_edits.keep_aliases(page.frontmatter, ["Alpha Prójekt"]) == ["Alpha Prójekt"]
    # Adding it back by an edit lifts the mark.
    mcp_tools.edit_page(_ctx(bank), "alpha-project", "It was its name after all.", add_aliases=["Alpha Projekt"])
    assert "aliases_removed" not in _page(bank).frontmatter


def test_a_pinned_fix_survives_the_article_rewrite(bank, monkeypatch):
    page = bank / "entities/alpha-project.md"
    parsed = markdown_parser.parse(page)
    parsed.frontmatter["source_episodes"] = ["ep_2026-01-10_001", "ep_2026-02-10_001"]
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    calls, first = _sleep(bank, monkeypatch, _fields())
    assert sum("You are writing a page" in c for c in calls) == 1
    assert "Owner Exampel builds" in first.body          # the writer's own article, with the misspelling
    _commit_all(bank, "Sleep cycle 2026-10-15\n\nCicada-Author: test-model")

    page_editors.update({"claude-code": True})
    mcp_tools.edit_page(_ctx(bank), "alpha-project", REASON, edits=FIX)
    edited = _page(bank)
    assert entity_article.stamped(edited.frontmatter, entity_body.parse_sections(
        claims.strip_claims_block(edited.body))), "a word-level fix keeps the article the writer's"

    # The next rewrite is handed the corrections, and whatever it writes, the old words do not come back.
    calls, after = _sleep(bank, monkeypatch, _fields(key_facts=["Owner Exampel ships it on Fridays."]),
                          sources=("ep_2026-10-16_001",))
    article_prompts = [c for c in calls if "You are writing a page" in c]
    assert len(article_prompts) == 1, "the page is still rewritten: the fix did not freeze it"
    assert '"replaced": "Owner Exampel"' in article_prompts[0] and "CORRECTIONS lists" in article_prompts[0]
    assert "Owner Exampel" not in claims.strip_claims_block(after.body)
    assert "Owner Example builds" in after.body and "Owner Example ships it on Fridays." in after.body
    assert claims.parse_claims(after.body)[0].id == "clm_alpha_uses_sqlite"



def test_a_rewritten_lead_is_the_editors_from_then_on(bank, monkeypatch):
    page_editors.update({"claude-code": True})
    out = mcp_tools.edit_page(_ctx(bank), "alpha-project", "The lead was out of date.", section="Summary",
                              text="Alpha Project is the notes app Owner Example builds and ships.")
    assert "rewrote the Summary section" in out
    assert _page(bank).frontmatter["human_edited"] is True
    calls, after = _sleep(bank, monkeypatch, _fields())
    assert not any("You are writing a page" in c for c in calls)
    assert "the notes app Owner Example builds and ships" in after.body


def test_the_writers_payload_is_corrected_with_its_records_so_a_paragraph_keeps_its_evidence():
    fm = {"corrections": [{"old": "Owner Exampel", "new": "Owner Example", "by": "claude-code", "on": "2026-10-14"}]}
    ev = {"episode": "ep_2026-10-14_001", "start": 0, "end": 10, "kind": "user", "hash": "abcdefabcdef"}
    article = {"lead": "Owner Exampel builds it.", "markdown": "### How\nOwner Exampel ships it.",
               "records": [{"field": "summary", "text": "Owner Exampel builds it.", "evidence": [ev]},
                           {"field": "article", "text": "Owner Exampel ships it.", "evidence": [ev]}],
               "retain": ["Owner Exampel likes it."], "dropped": {}}
    fixed = page_edits.correct_article(fm, article)
    assert fixed["lead"] == "Owner Example builds it." and "Owner Example ships it." in fixed["markdown"]
    assert [r["text"] for r in fixed["records"]] == ["Owner Example builds it.", "Owner Example ships it."]
    assert fixed["retain"] == ["Owner Example likes it."] and article["lead"] == "Owner Exampel builds it."
    assert page_edits.correct_article({}, article) is article


def test_corrections_are_whole_word_and_idempotent():
    rows = [{"old": "Jon", "new": "Jon Example"}]
    once, n = page_edits.correct_text("Jon met Jonas. Jon Example too.", rows)
    assert once == "Jon Example met Jonas. Jon Example too." and n == 1
    assert page_edits.correct_text(once, rows) == (once, 0)


# --------------------------------------------------------------------------- blame


def test_blame_says_who_wrote_each_section_when_and_why(bank):
    page_editors.update({"claude-code": True})
    mcp_tools.edit_page(_ctx(bank), "alpha-project", REASON,
                        edits=[{"old": "Uses SQLite for sync.", "new": "Uses SQLite for sync on every device."}])
    (bank / "entities/alpha-project.md").write_text(
        (bank / "entities/alpha-project.md").read_text().replace("First prototype.", "First prototype, by hand."))
    result = asyncio.run(page_blame.blame(bank, "alpha-project", with_lines=True))
    sections = {s["title"]: s for s in result["sections"]}
    assert set(sections) >= {"Summary", "Key Facts", "History"}
    facts = {c["author"]: c for c in sections["Key Facts"]["contributors"]}
    assert facts["claude-code"]["lines"] == 1 and facts["claude-code"]["author_kind"] == "harness"
    assert facts["cicada"]["lines"] == 1
    edit = next(c for c in result["commits"] if c["author"] == "claude-code")
    assert edit["reason"] == REASON and edit["trigger"] == "mcp/claude-code" and edit["accepted_by"] is None
    assert [c["author"] for c in sections["History"]["contributors"]] == ["uncommitted"]
    assert result["uncommitted_lines"] == 1
    assert all(line["line"] > 1 for line in result["lines"])                 # frontmatter left out
    assert not any("clm_alpha" in str(line) for line in result["lines"])     # the claims fence too


def test_the_blame_route_serves_it(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        body = client.get("/entities/alpha-project/blame").json()
        assert body["entityId"] == "alpha-project" and body["sections"][0]["contributors"][0]["author"] == "cicada"
        assert "lines" not in body
        assert client.get("/entities/no-such-page/blame").status_code == 404
        assert client.put("/settings/editors", json={"trusted": {"claude-code": True}}).json()["trusted"][0][
            "harness"] == "claude-code"
        assert client.put("/settings/editors", json={"trusted": {"agent": True}}).status_code == 400
        assert any(c["harness"] == "cursor" for c in client.get("/settings/editors").json()["candidates"])
    finally:
        config.get_settings.cache_clear()


# --------------------------------------------------------------------------- the inbox


def _clarification(memory: Path) -> None:
    markdown_parser.write(memory / "inbox/inbox-003.md", {
        "kind": "clarification", "status": "pending", "entity_id": "alpha-project", "entity_name": "Alpha Project",
        "title": "Is Alpha Projekt another name for Alpha Project?", "created_date": "2026-10-01"}, "ctx")


def test_an_edit_answers_the_inbox_item_it_settles_with_the_persons_words(bank):
    page_editors.update({"claude-code": True})
    _clarification(bank)
    posts: list = []
    out = mcp_tools.edit_page(
        _ctx(bank, posts=posts), "alpha-project", "Not a name it ever had.", remove_aliases=["Alpha Projekt"],
        evidence=[{"episode": "ep_2026-10-14_001", "quote": "Alpha Projekt was never its name"}],
        resolves=[{"id": "inbox-003", "answer": "No — it was never its name."}])
    # The person's located words go with the answer as the relayed quote (merge with natural questions, G115).
    assert posts == [("/inbox/inbox-003/resolve", {"action": "resolve", "answer": "No — it was never its name.",
                                                   "quote": "Alpha Projekt was never its name",
                                                   "relayedBy": "claude-code", "sessionId": SESSION,
                                                   "via": "agent"})]
    assert "Inbox item inbox-003: resolved." in out


def test_without_the_persons_words_no_item_is_answered(bank):
    page_editors.update({"claude-code": True})
    _clarification(bank)
    posts: list = []
    out = mcp_tools.edit_page(
        _ctx(bank, posts=posts), "alpha-project", "Not a name it ever had.", remove_aliases=["Alpha Projekt"],
        evidence=[{"episode": "ep_2026-10-14_001", "quote": "Noted."}],          # the assistant's words
        resolves=[{"id": "inbox-003", "answer": "No."}])
    assert posts == [] and "nothing was answered" in out
    assert "Alpha Projekt" not in _page(bank).frontmatter["aliases"], "the edit itself still stands"


# --------------------------------------------------------------------------- the ledger and the write window


def test_a_ledger_page_keeps_its_ledger_and_fence_byte_for_byte(tmp_path):
    memory = _bank(tmp_path)
    rows = [Claim(id=f"clm_{i:05d}", text=f"Owner Example asked about topic {i} at some length to fill the fence",
                  subject="owner-example", predicate="asked-about", object=f"topic-{i}",
                  valid_from="2026-01-01", recorded_at="2026-01-01",
                  evidence=[Evidence(episode="ep_2026-01-01_001", start=i, end=i + 9, kind="user",
                                     hash="abcdefabcdef")]) for i in range(900)]
    prose = "## Summary\nOwner Example is the person this bank belongs to; Owner Exampel in one place.\n"
    page = memory / "entities/owner-example.md"
    markdown_parser.write(page, {"name": "Owner Example", "type": "person", "status": "active",
                                 "aliases": ["Owner"]}, claims.write_claims(prose, rows))
    ledger = claims_ledger.path_for(page)
    assert ledger.exists()
    _commit_all(memory)
    ledger_before = ledger.read_bytes()
    text_before = page.read_text()
    # The fence block itself, to its closing line (the file's final newline is the renderer's, on every writer).
    fence_before = text_before[claims.claims_block_start(text_before):].rstrip("\n")
    page_editors.update({"claude-code": True})
    out = mcp_tools.edit_page(_ctx(memory), "owner-example", REASON,
                              edits=[{"old": "Owner Exampel", "new": "Owner Example"}])
    assert out.startswith("Edited owner-example")
    text_after = page.read_text()
    assert ledger.read_bytes() == ledger_before
    assert text_after[claims.claims_block_start(text_after):].rstrip("\n") == fence_before
    assert "Owner Exampel" not in text_after
    assert len(claims.parse_claims(markdown_parser.parse(page).body)) == 900
    assert _git(memory, "status", "--porcelain").strip() == ""


def test_an_edit_is_refused_while_sleep_holds_the_pages(bank, monkeypatch):
    page_editors.update({"claude-code": True})
    seen = []
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running",
                        lambda url, headers: seen.append(write_admission.holders(bank)) or True)
    before = (bank / "entities/alpha-project.md").read_bytes()
    head = _git(bank, "rev-parse", "HEAD")
    for harness in ("claude-code", "cursor"):        # the direct edit and the proposal alike
        assert mcp_tools.edit_page(_ctx(bank, harness=harness), "alpha-project", REASON,
                                   edits=FIX) == mcp_tools.EDIT_SLEEPING
    assert seen == [1, 1], "asked inside the bank's write admission"
    assert write_admission.holders(bank) == 0
    assert (bank / "entities/alpha-project.md").read_bytes() == before
    assert _git(bank, "rev-parse", "HEAD") == head and not (bank / "inbox/inbox-003.md").exists()


def test_the_stdio_tool_and_the_demo_bank(bank, monkeypatch):
    srv = stdio_server()
    monkeypatch.setattr(srv, "get_memory_path", lambda: bank)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity(SESSION, "claude-code", None))
    page_editors.update({"claude-code": True})
    out = srv.handle_tool("cicada_edit_page", {"subject": "Alpha Project", "reason": REASON, "edits": FIX})
    assert out.startswith("Edited alpha-project")
    from api.services import demo_guard

    demo_guard.manifest_path(bank).write_text(f"kind: {demo_guard.DEMO_KIND}\n")
    assert demo_guard.is_demo(bank)
    assert mcp_tools.edit_page(_ctx(bank), "alpha-project", REASON, edits=FIX) == demo_guard.AGENT_REFUSAL


# --------------------------------------------------------------------------- review round 1


def _proposal(bank) -> None:
    mcp_tools.edit_page(_ctx(bank, harness="cursor"), "alpha-project", REASON, edits=FIX)
    assert (bank / "inbox/inbox-003.md").exists()


@pytest.mark.parametrize("item_id", ["INBOX-003", "inbox-00%33", "Inbox-003", "../inbox/inbox-003", "inbox-003.md"])
def test_b1_an_agent_cannot_reach_its_proposal_under_another_spelling(bank, item_id):
    _proposal(bank)
    posts: list = []
    before = (bank / "entities/alpha-project.md").read_bytes()
    out = mcp_tools.resolve_inbox(_ctx(bank, harness="cursor", posts=posts), item_id, "apply", None, False, None)
    assert out == "Error: id must look like 'inbox-001'." and posts == []
    assert (bank / "entities/alpha-project.md").read_bytes() == before


@pytest.mark.parametrize("item_id", ["INBOX-003", "Inbox-003", "inbox-00%33", "inbox-003 ", "../inbox/inbox-003",
                                     "inbox-003.md"])
def test_b1_the_backend_refuses_any_other_id_shape(bank, item_id):
    from fastapi import HTTPException

    _proposal(bank)
    with pytest.raises(HTTPException) as err:
        asyncio.run(inbox_service.resolve(item_id, InboxResolveRequest(action="resolve", option_key="apply"),
                                          SimpleNamespace(memory_path=bank, inbox_defer_days=30)))
    assert err.value.status_code == 400
    assert (bank / "inbox/inbox-003.md").exists() and "Owner Exampel" in _page(bank).body


def test_b1_the_backend_refuses_an_agent_answer_to_a_proposal_whatever_door(bank):
    from fastapi import HTTPException

    _proposal(bank)
    head = _git(bank, "rev-parse", "HEAD")
    for action, key in (("resolve", "apply"), ("resolve", "dismiss"), ("defer", None)):
        with pytest.raises(HTTPException) as err:
            asyncio.run(inbox_service.resolve("inbox-003", InboxResolveRequest(action=action, option_key=key,
                                                                               via="agent"),
                                              SimpleNamespace(memory_path=bank, inbox_defer_days=30)))
        assert err.value.status_code == 403
    assert _git(bank, "rev-parse", "HEAD") == head and (bank / "inbox/inbox-003.md").exists()
    # The tool says it is an agent on every answer it posts.
    posts: list = []
    mcp_tools.resolve_inbox(_ctx(bank, posts=posts), "inbox-001", "keep", None, False, None)
    assert posts[0][1]["via"] == "agent"


def test_b1_the_route_refuses_a_case_variant_id(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    _proposal(bank)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        assert client.post("/inbox/INBOX-003/resolve", json={"action": "resolve", "optionKey": "apply"}
                           ).status_code == 400
        assert client.post("/inbox/inbox-003/resolve", json={"action": "resolve", "optionKey": "apply",
                                                             "via": "agent"}).status_code == 403
        assert "Owner Exampel" in _page(bank).body
    finally:
        config.get_settings.cache_clear()


def _prose_page(memory: Path, prose: str) -> tuple[dict, str]:
    fact = Claim(id="clm_alpha_uses_sqlite", text="Alpha Project uses SQLite", subject="alpha-project",
                 predicate="uses", object="sqlite", valid_from="2026-01-10", recorded_at="2026-01-10")
    _entity(memory, "alpha-project", type="project", name="Alpha Project", body=claims.write_claims(prose, [fact]))
    return _raw(memory)


def test_b2_words_that_only_together_make_a_claims_opener_are_refused(bank):
    fm, body = _prose_page(bank, "## Summary\nAlpha Project.\n\n## Key Facts\n- Marked.\n\n``x marks it.")
    for edit in ({"old": "x marks", "new": "`claims marks"}, {"old": "x", "new": "`claims", "all": True, "pin": True}):
        with pytest.raises(page_edits.EditError, match="sections or its claims block"):
            page_edits.plan(fm, body, page_edits.parse_request([edit]), author="claude-code")


def test_b2_an_edit_never_renames_or_adds_a_section_heading(bank):
    fm, body = _raw(bank)
    for edit in ({"old": "Summary", "new": "Overview", "all": True},
                 {"old": "Uses SQLite for sync.", "new": "Uses SQLite.\n\n# Uses"}):
        with pytest.raises(page_edits.EditError):
            page_edits.plan(fm, body, page_edits.parse_request([edit]), author="claude-code")
    with pytest.raises(page_edits.EditError):
        # a heading line is refused in the request itself
        page_edits.parse_request([{"old": "Uses SQLite for sync.", "new": "x\n## New"}])


def test_b2_a_pinned_fix_never_touches_a_heading_or_assembles_a_fence():
    rows = [{"old": "Summary", "new": "Overview"}]
    text = "## Summary\nThe Summary of it.\n\n### Summary notes\nMore."
    fixed, n = page_edits.correct_text(text, rows)
    assert fixed == "## Summary\nThe Overview of it.\n\n### Summary notes\nMore." and n == 1
    fence = [{"old": "x", "new": "`claims"}]
    assert page_edits.correct_text("Some text.\n``x here.\n", fence) == ("Some text.\n``x here.\n", 0)
    body = "## Summary\nSome text.\n``x here.\n\n```claims\n[]\n```"
    assert page_edits.apply_corrections({"corrections": fence}, body) == (body, 0)
    assert page_edits.shape(body) == page_edits.shape(page_edits.apply_corrections(
        {"corrections": rows}, "## Summary\nThe Summary.\n\n```claims\n[]\n```")[0])


def _blame_bank(tmp_path):
    memory = _bank(tmp_path)
    return memory


def test_b3_blame_is_kept_per_the_pages_own_newest_commit(tmp_path, monkeypatch):
    memory = _blame_bank(tmp_path)
    page_blame._CACHE.clear()
    calls: list[str] = []
    real = page_blame._git

    async def counting(memory_path, *args, **kw):
        calls.append(args[0])
        return await real(memory_path, *args, **kw)

    monkeypatch.setattr(page_blame, "_git", counting)
    first = asyncio.run(page_blame.blame(memory, "alpha-project"))
    assert first["pending"] is False and calls.count("blame") == 1
    # A commit elsewhere in the bank does not empty it.
    (memory / "entities/bob-example.md").write_text((memory / "entities/bob-example.md").read_text() + "\nMore.\n")
    _commit_all(memory, "Elsewhere\n\nCicada-Author: cicada")
    assert asyncio.run(page_blame.blame(memory, "alpha-project")) == first
    assert calls.count("blame") == 1
    # A commit to the page does.
    page = memory / "entities/alpha-project.md"
    page.write_text(page.read_text().replace("synthetic fixture", "synthetic fixture page"))
    _commit_all(memory, "Here\n\nCicada-Author: cicada")
    asyncio.run(page_blame.blame(memory, "alpha-project"))
    assert calls.count("blame") == 2


def test_b3_a_slow_blame_answers_pending_runs_once_and_is_served_when_done(tmp_path, monkeypatch):
    memory = _blame_bank(tmp_path)
    page_blame._CACHE.clear()
    real = page_blame._git
    blames: list[int] = []

    async def slow(memory_path, *args, **kw):
        if args[0] == "blame":
            blames.append(1)
            await asyncio.sleep(0.4)
        return await real(memory_path, *args, **kw)

    monkeypatch.setattr(page_blame, "_git", slow)

    async def scenario():
        a, b = await asyncio.gather(page_blame.blame(memory, "alpha-project", wait=0.05),
                                    page_blame.blame(memory, "alpha-project", wait=0.05))
        assert a["pending"] and b["pending"] and a["sections"] == []
        await asyncio.sleep(0.6)
        return await page_blame.blame(memory, "alpha-project", wait=0.05)

    done = asyncio.run(scenario())
    assert done["pending"] is False and done["sections"] and len(blames) == 1


def test_b3_every_git_call_has_a_deadline_and_a_failure_is_never_cached(tmp_path, monkeypatch):
    memory = _blame_bank(tmp_path)
    page_blame._CACHE.clear()
    with pytest.raises(page_blame._Unavailable):
        asyncio.run(page_blame._git(memory, "log", "--all", "-p", timeout=0.0001))
    monkeypatch.setattr(page_blame, "GIT_TIMEOUT_S", 0.0001)
    assert asyncio.run(page_blame.blame(memory, "alpha-project"))["pending"] is True
    assert page_blame._CACHE == {}
