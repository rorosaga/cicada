"""An alias that names a different thing (session-1 follow-ups of #545; `wrong_aliases`, G21/G209/G198).

A tool page that lists a related product's name among the names it goes by brings the two pages to the judge — and,
before #545, to the person as "same?" — on every batch. Once the record holds them as two things, the alias is the
cause: Cicada proposes removing it (the person applies or leaves it, nothing removed silently), Sleep never adds such
an alias again, and the person's own agent can settle a public pair with a relation through the writer Sleep's tail
uses. Synthetic names only; the judge is a fake; git is real."""
from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from _synthetic_bank import _bank as _synthetic, _entity as _page
from api.models.schemas import InboxResolveRequest
from api.services import (bank_index, conflict_resolver, entity_resolver, inbox_service, markdown_parser,
                          merge_rejections, page_edits, web_settle, wrong_aliases)
from api.services.claims import Claim, parse_claims, write_claims
from api.tests.test_sleep_cycle_hold import _bank, _entity, _settings

EP, TS = "ep_2026-10-28_001", "2026-10-28T10:00:00+00:00"
DOCS = "https://docs.tool-example.dev/example-db-cloud"


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _tool(memory, eid, name, aliases=(), body=None):
    fm = {"name": name, "type": "tool", "status": "active", "confidence": 0.8,
          **({"aliases": list(aliases)} if aliases else {})}
    body = body or f"## Summary\n{name} is a synthetic tool."
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, body)
    return {"id": eid, "frontmatter": fm, "body": body}


def _proposals(memory):
    out = []
    for p in sorted((memory / "inbox").glob("inbox-*.md")):
        fm = markdown_parser.parse(p).frontmatter
        if fm.get("kind") == "page_edit":
            out.append((p.stem, fm))
    return out


def _resolve(memory, pages, monkeypatch, verdict):
    async def judge(*_a, **_k):
        return verdict

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return [verdict for _ in entries]
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", batch)
    entity_resolver._LEAD_VERDICTS.clear()
    mention = _entity("Example DB", "tool", EP, TS)
    return asyncio.run(entity_resolver.resolve([{"episode_id": EP, "entities": [mention], "relationships": []}],
                                               pages, _settings(memory)))


def _lead_bank(tmp_path):
    memory = _bank(tmp_path)
    pages = [_tool(memory, "example-db", "Example DB"),
             _tool(memory, "example-db-cloud", "Example DB Cloud", aliases=["Example DB", "EDC"])]
    return memory, pages


# ---------- the cure: Cicada proposes removing the alias ----------


@pytest.mark.parametrize("verdict, proposed", [("related:makes", True), ("different", True), ("unsure", False),
                                               ("same", False)])
def test_an_alias_lead_judged_two_things_proposes_removing_the_alias(tmp_path, monkeypatch, verdict, proposed):
    memory, pages = _lead_bank(tmp_path)
    _resolve(memory, pages, monkeypatch, verdict)
    found = _proposals(memory)
    assert bool(found) is proposed
    if proposed:
        (_, fm), = found
        assert (fm["entity_id"], fm["edit"], fm["origin"], fm["proposed_by"]) == (
            "example-db-cloud", {"remove_aliases": ["Example DB"]}, wrong_aliases.ORIGIN, wrong_aliases.AUTHOR)
        assert fm["question"].startswith("Cicada suggests a change to Example DB Cloud:")
        assert [o["key"] for o in fm["options"]] == ["apply", "dismiss"]
        # The page itself is untouched until the person applies it.
        assert markdown_parser.parse(memory / "entities" / "example-db-cloud.md").frontmatter["aliases"] == [
            "Example DB", "EDC"]


def test_a_second_batch_proposes_nothing_new(tmp_path, monkeypatch):
    memory, pages = _lead_bank(tmp_path)
    _resolve(memory, pages, monkeypatch, "related:makes")
    _resolve(memory, pages, monkeypatch, "related:makes")
    assert len(_proposals(memory)) == 1


def test_nothing_is_proposed_for_an_alias_already_removed_or_kept(tmp_path):
    memory, _pages = _lead_bank(tmp_path)
    page = memory / "entities" / "example-db-cloud.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, wrong_aliases.KEPT: ["example db"]}, parsed.body)
    assert wrong_aliases.propose(memory, "example-db-cloud", "Example DB", "why.") is None
    markdown_parser.write(page, {**parsed.frontmatter, page_edits.ALIASES_REMOVED: [{"alias": "Example DB"}]},
                          parsed.body)
    assert wrong_aliases.propose(memory, "example-db-cloud", "Example DB", "why.") is None
    assert wrong_aliases.propose(memory, "example-db-cloud", "Unlisted Name", "why.") is None
    assert _proposals(memory) == []


@pytest.fixture
def gitbank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    memory = _synthetic(tmp_path)
    for p in (memory / "inbox").glob("inbox-*.md"):
        p.unlink()
    _page(memory, "owner-example", type="person", owner=True, name="Owner Example")
    _page(memory, "example-db", type="tool", name="Example DB", body="## Summary\nA document database.\n")
    _page(memory, "example-db-cloud", type="tool", name="Example DB Cloud", aliases=["Example DB", "EDC"],
          body="## Summary\nA hosted database.\n")
    markdown_parser.write(memory / "inbox" / "inbox-301.md", {
        "kind": "merge_suggestion", "status": "pending", "priority": 0.8, "required_input": "merge",
        "entity_id": "example-db-cloud", "entity_name": "Example DB Cloud", "merge_target_hint": "example-db",
        "title": "Is Example DB Cloud the same as example-db?", "uncertainty_type": "Possible duplicate of example-db",
        "suggested_classification": "tool — could refer to the same entity as example-db",
        "created_date": "2026-10-28", "source_episode": EP}, "Context.")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "seed")
    bank_index.invalidate()
    return memory


def _answer(memory, item_id, key):
    asyncio.run(inbox_service.resolve(item_id, InboxResolveRequest(action="resolve", option_key=key),
                                      SimpleNamespace(memory_path=memory, inbox_defer_days=30)))


def test_applying_the_proposal_removes_the_alias_for_good(gitbank):
    rel = wrong_aliases.propose(gitbank, "example-db-cloud", "Example DB", "Example DB Cloud is made by Example DB.")
    _git(gitbank, "add", "-A")
    _git(gitbank, "commit", "-qm", "proposal")
    _answer(gitbank, rel.split("/")[1][:-3], "apply")
    fm = markdown_parser.parse(gitbank / "entities" / "example-db-cloud.md").frontmatter
    assert fm["aliases"] == ["EDC"] and "example db" in page_edits.removed_aliases(fm)
    # …so Sleep's alias writer never adds it back, and nothing is proposed again.
    assert page_edits.keep_aliases(fm, ["Example DB"]) == []
    assert wrong_aliases.propose(gitbank, "example-db-cloud", "Example DB", "why.") is None
    log = _git(gitbank, "log", "-1", "--format=%B", "--", "entities/example-db-cloud.md")
    assert "Cicada-Author: cicada" in log and "Cicada-Author: user" in log


def test_leaving_the_proposal_keeps_the_alias_and_it_is_never_proposed_again(gitbank):
    rel = wrong_aliases.propose(gitbank, "example-db-cloud", "Example DB", "why.")
    _git(gitbank, "add", "-A")
    _git(gitbank, "commit", "-qm", "proposal")
    _answer(gitbank, rel.split("/")[1][:-3], "dismiss")
    fm = markdown_parser.parse(gitbank / "entities" / "example-db-cloud.md").frontmatter
    assert fm["aliases"] == ["Example DB", "EDC"] and fm[wrong_aliases.KEPT] == ["Example DB"]
    assert wrong_aliases.propose(gitbank, "example-db-cloud", "Example DB", "why.") is None
    sha = _git(gitbank, "log", "-1", "--format=%H", "--", "entities/example-db-cloud.md").strip()
    assert sorted(_git(gitbank, "show", "--name-only", "--format=", sha).split()) == [
        "entities/example-db-cloud.md", rel]


def test_an_agent_proposal_left_by_the_person_writes_no_mark(gitbank):
    rel = page_edits.write_proposal(gitbank, entity_id="example-db-cloud", name="Example DB Cloud",
                                    request=page_edits.Request(remove_aliases=["EDC"]), reason="why", author="cursor",
                                    session=None)
    _git(gitbank, "add", "-A")
    _git(gitbank, "commit", "-qm", "proposal")
    _answer(gitbank, rel.split("/")[1][:-3], "dismiss")
    assert wrong_aliases.KEPT not in markdown_parser.parse(gitbank / "entities" / "example-db-cloud.md").frontmatter


# ---------- a check that settles a pair proposes it too, and its undo takes it back ----------


def test_a_settled_pair_proposes_the_alias_removal_and_undo_takes_it_back(gitbank):
    done = web_settle.settle_pair(gitbank, "inbox-301", ref=DOCS, quote="Example DB Cloud is run by the makers of "
                                  "Example DB.", relation="made_by", checker="cicada", checker_kind="sleep")
    (item_id, fm), = _proposals(gitbank)
    assert f"inbox/{item_id}.md" in done.paths and fm["edit"] == {"remove_aliases": ["Example DB"]}
    assert "Example DB Cloud is made by Example DB" in fm["reason"]
    web_settle.undo(gitbank, "inbox-301")
    assert _proposals(gitbank) == []


# ---------- the prevention: Sleep never adds the name of a thing the record holds as another ----------


def test_sleep_never_adds_the_name_of_a_related_or_rejected_page_as_an_alias(tmp_path):
    memory = _bank(tmp_path)
    _tool(memory, "example-db", "Example DB")
    _tool(memory, "other-tool", "Other Tool")
    body = write_claims("## Summary\nHosted.\n", [Claim(
        id="clm_rel", text="x", subject="example-db-cloud", predicate="made-by", object="example-db",
        valid_from="2026-10-01", recorded_at="2026-10-01")])
    _tool(memory, "example-db-cloud", "Example DB Cloud", body=body)
    merge_rejections.add_rejected(memory, "other-tool", "example-db-cloud")
    kept = conflict_resolver._new_aliases(memory, "example-db-cloud",
                                          ["Example DB", "Other Tool", "EDC", "the database"])
    assert kept == ["EDC"]
    # A name with no page, or a page the record does not hold apart, is an ordinary alias.
    assert conflict_resolver._new_aliases(memory, "example-db", ["Other Tool", "Mongo"]) == ["Other Tool", "Mongo"]
    # The relation is seen from either page.
    assert conflict_resolver._new_aliases(memory, "example-db", ["Example DB Cloud"]) == []


def test_the_extraction_prompt_says_a_related_name_is_no_alias():
    from api.services import entity_extractor

    prompt = " ".join(entity_extractor.EXTRACTION_SYSTEM_PROMPT.split())
    assert "nor of the larger thing it belongs to, its maker or an alternative to it" in prompt


# ---------- the person's own agent settles a public pair with a relation ----------


@pytest.fixture
def server(gitbank, monkeypatch):
    from _stdio_server import stdio_server
    from api.services import mcp_tools

    srv = stdio_server()
    monkeypatch.setattr(srv, "get_memory_path", lambda: gitbank)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_pair_fixed", "claude-code", None))
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    mcp_tools._SETTLES_BY_SESSION.clear()
    return srv


QUOTE = [{"quote": "Example DB Cloud is the hosted service run by the makers of Example DB."}]


def test_an_agent_settles_a_public_pair_with_a_relation(server, gitbank):
    out = server.handle_tool("cicada_record_check", {
        "item_id": "inbox-301", "source": DOCS, "outcome": "settles", "proposed_value": "made_by", "quotes": QUOTE})
    assert out.startswith("Settled inbox-301"), out
    claims = parse_claims(markdown_parser.parse(gitbank / "entities" / "example-db.md").body)
    assert [(c.subject, c.predicate, c.object, c.authored_by) for c in claims] == [
        ("example-db", "creates", "example-db-cloud", "claude-code")]
    (row,) = web_settle.list_settled(gitbank)
    assert (row["settled_by"], row["settled_by_kind"]) == ("claude-code", "agent")
    log = _git(gitbank, "log", "-1", "--format=%B", "--", "entities/example-db.md")
    assert "Cicada-Author: claude-code" in log and "Cicada-Session: ses_pair_fixed" in log
    ((item_id, _fm),) = _proposals(gitbank)
    assert _git(gitbank, "status", "--porcelain", "--", f"inbox/{item_id}.md") == ""


@pytest.mark.parametrize("value", ["same", "a database", ""])
def test_an_agent_never_merges_or_answers_a_pair_in_words(server, gitbank, value):
    out = server.handle_tool("cicada_record_check", {
        "item_id": "inbox-301", "source": DOCS, "outcome": "settles", "proposed_value": value, "quotes": QUOTE})
    assert out.startswith("Not recorded"), out
    assert (gitbank / "inbox" / "inbox-301.md").exists() and _proposals(gitbank) == []


def test_the_nudge_line_names_the_relations_for_a_public_pair(server, gitbank):
    from api.services import mcp_tools

    (line,) = mcp_tools._settle_lines(SimpleNamespace(author="claude-code", is_remote=False), gitbank, "inbox-301")
    assert "Public pair" in line and "made_by" in line and "\"Example DB Cloud\" and \"Example DB\"" in line
