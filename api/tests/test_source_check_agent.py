"""G61 S3 — the agent check on G166's reading queue (shadow: recommend-only).

Owner, 2026-09-30: "give agents a place to look for information to update memory before surfacing it to the user …
where does <person> work, my profile page might be a source for update." A source on a page could answer a pending
question; an agent the person runs looks at it (only on a site the person allowed) and REPORTS. Nothing settles, holds or
reorders (S4–S8 wait). Synthetic bank (bob-example, company-a/b, team-labs.io); git is real; nothing reaches a network."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from _reading_fixtures import enable, git_log, reading  # noqa: F401 — `reading` is a fixture
from _synthetic_bank import _entity
from api import config
from api.remote import catalog
from api.remote import tools as remote_tools
from api.remote.runtime import RemoteRuntime
from api.services import (bank_index, check_record, evidence, fact_sources, inbox_service, markdown_parser, mcp_tools,
                          reading_asks, reading_queue, reading_settings, telemetry)

TEAM = "https://team-labs.io/staff"
PROFILE = "https://www.linkedin.com/in/bob-example"
SITE = "team-labs.io"
ITEM = "inbox-010"
QUOTE = {"quote": "Bob Example joined company-b as a staff engineer"}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _item(memory, item_id=ITEM, *, entity="bob-example", predicate="works-at"):
    markdown_parser.write(memory / "inbox" / f"{item_id}.md", {
        "kind": "conflict", "required_input": "choice", "status": "pending", "priority": 0.8, "entity_id": entity,
        "entity_name": "Bob Example", "title": "Where does Bob Example work now?",
        "question": "Where does Bob Example work now?", "predicate": predicate, "created_date": "2026-09-01",
        "allow_other": True, "allow_defer": True,
        "options": [{"key": "a", "label": "company-a", "last_referenced": "2026-01-01"},
                    {"key": "b", "label": "company-b", "last_referenced": "2026-02-01"}]}, "Conflicting beliefs.")


def _commit(memory):
    subprocess.run(["git", "-C", str(memory), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "seed"], check=True, capture_output=True)
    bank_index.invalidate()


@pytest.fixture
def setup(reading):
    server, memory = reading
    (memory / "inbox").mkdir(exist_ok=True)
    _item(memory)
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="user", kind="url")
    _commit(memory)
    enable(sites=(SITE,))
    return server, memory


def _entries(memory, **kw):
    return reading_queue.check_entries(memory, **kw)


# ---------- which sources are listed ----------


def test_a_users_source_for_a_pending_question_is_a_check_entry_only_on_an_allowed_site(reading):
    server, memory = reading
    (memory / "inbox").mkdir(exist_ok=True)
    _item(memory)
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="user", kind="url")
    _commit(memory)
    enable()
    assert _entries(memory) == [], "a site the person never allowed is never listed"
    assert [e.site for e in _entries(memory, ignore_site=True)] == [SITE], "...but it is what they could allow"
    enable(sites=(SITE,))
    (e,) = _entries(memory)
    assert (e.origin, e.url, e.item_id, e.entity_id, e.predicate, e.site) == (
        "check", TEAM, ITEM, "bob-example", "works-at", SITE)
    reading_settings.update(agent_enabled_=False)
    assert _entries(memory) == [] and reading_queue.entries(memory) == [], "the master switch off dequeues at once"


def test_the_existing_needs_login_pause_and_a_held_link_and_a_recent_check_skip_a_source(setup):
    server, memory = setup
    assert len(_entries(memory)) == 1
    # a recent look is not repeated for a week; an older one is
    recent = datetime.now(timezone.utc).isoformat()
    check_record.append_check(memory / "inbox" / f"{ITEM}.md", {
        "at": recent, "checker": "claude-code", "checker_kind": "agent", "ref": TEAM, "host": SITE,
        "outcome": "unclear", "episode": "ep_x"})
    bank_index.invalidate()
    assert _entries(memory) == []
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    check_record.append_check(memory / "inbox" / f"{ITEM}.md", {
        "at": old, "checker": "claude-code", "checker_kind": "agent", "ref": TEAM, "host": SITE,
        "outcome": "unclear", "episode": "ep_x"})
    bank_index.invalidate()
    assert len(_entries(memory)) == 1
    # a needs_login for the site pauses it (the queue's own rule, shared with reads)
    reading_asks.record_outcome(memory, __import__("api.services.media_ingestor", fromlist=["x"]).url_hash(
        "https://team-labs.io/other"), "needs_login", create=True, origin="site", host=SITE)
    assert _entries(memory) == []


def test_an_agent_added_source_on_the_owners_page_is_a_target_only_after_use_this_source(reading):
    server, memory = reading
    (memory / "inbox").mkdir(exist_ok=True)
    _entity(memory, "owner-example", type="person", owner=True, name="Owner Example")
    _item(memory, entity="owner-example")
    fact_sources.add_source(memory, "owner-example", TEAM, predicate="works-at", added_by="claude-code", kind="url")
    _commit(memory)
    enable(sites=(SITE,))
    assert _entries(memory) == [], "an agent's source on the owner's page is not a check target (D2, R-AC9)"
    fact_sources.add_source(memory, "owner-example", TEAM, predicate="works-at", added_by="user", accepted=True)
    _commit(memory)
    assert [e.url for e in _entries(memory)] == [TEAM]


def test_an_agent_planted_source_on_an_unallowed_site_is_never_listed_nor_recordable(setup):
    server, memory = setup
    planted = "https://evil-labs.io/profile"
    fact_sources.add_source(memory, "bob-example", planted, predicate="works-at", added_by="claude-code", kind="url")
    _commit(memory)
    assert planted not in [e.url for e in _entries(memory)]
    out = server.handle_tool("cicada_record_check", {"item_id": ITEM, "source": planted, "outcome": "supports",
                                                     "option_key": "b", "quotes": [QUOTE]})
    assert out.startswith("Not recorded") and "not on the person's list" in out


def test_a_website_source_answers_a_page_level_question_and_a_verified_one_waives_the_unknown_locus(reading):
    server, memory = reading
    (memory / "inbox").mkdir(exist_ok=True)
    _entity(memory, "company-a", type="company", name="Company A")
    markdown_parser.write(memory / "inbox" / "inbox-020.md", {
        "kind": "conflict", "required_input": "choice", "status": "pending", "priority": 0.5, "entity_id": "company-a",
        "entity_name": "Company A", "title": "What is Company A?", "question": "What is Company A?",
        "created_date": "2026-09-01", "options": [{"key": "a", "label": "a bank"}, {"key": "b", "label": "a shop"}]}, "x")
    fact_sources.add_source(memory, "company-a", "https://company-a-labs.io", predicate="website", added_by="cicada")
    _commit(memory)
    enable(sites=("company-a-labs.io",))
    item = next(i for i in inbox_service.load_inbox(memory) if i.id == "inbox-020")
    assert item.check.state == "needs_source" and item.check.reason == "unknown_locus", "unverified proposals wait"
    page = memory / "entities" / "company-a.md"
    parsed = markdown_parser.parse(page)
    for s in parsed.frontmatter["sources"]:
        s["verified"] = {"at": "2026-10-01", "how": "name+content"}
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    bank_index.invalidate()
    item = next(i for i in inbox_service.load_inbox(memory) if i.id == "inbox-020")
    assert item.check.state == "checkable" and item.check.targets[0].verified is True
    assert [(e.item_id, e.url) for e in _entries(memory)] == [("inbox-020", "https://company-a-labs.io")]


def test_the_least_recently_checked_source_comes_first_within_a_class(setup):
    server, memory = setup
    second = "https://team-labs.io/people"
    fact_sources.add_source(memory, "bob-example", second, predicate="works-at", added_by="user", kind="url")
    _commit(memory)
    first_ref = [e.url for e in _entries(memory)]
    assert first_ref == [TEAM, second]
    check_record.append_check(memory / "inbox" / f"{ITEM}.md", {
        "at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(), "checker": "x", "checker_kind": "agent",
        "ref": TEAM, "host": SITE, "outcome": "unclear", "episode": "ep_x"})
    bank_index.invalidate()
    assert [e.url for e in _entries(memory)] == [second, TEAM], "one never looked at goes before one looked at 30 days ago"
    check_record.append_check(memory / "inbox" / f"{ITEM}.md", {
        "at": (datetime.now(timezone.utc) - timedelta(days=9)).isoformat(), "checker": "x", "checker_kind": "agent",
        "ref": second, "host": SITE, "outcome": "unclear", "episode": "ep_y"})
    bank_index.invalidate()
    assert [e.url for e in _entries(memory)] == [TEAM, second], "the older look goes first"


# ---------- the queue ----------


def test_the_reading_queue_lists_a_check_with_its_question_and_names_the_record_tool_only_when_held(setup):
    server, memory = setup
    out = server.handle_tool("cicada_reading_queue", {})
    assert f"{TEAM} (team-labs.io, a source to check for `{ITEM}`: Where does Bob Example work now?" in out
    assert "cicada_record_check(item_id, source, outcome, option_key, quotes=[...], via)" in out
    assert "settles nothing" in out
    held = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_x", harness="claude-web", connector_id="ab12cd34",
                                 available=frozenset({"cicada_reading_queue"}))
    out = mcp_tools.reading_queue(held)
    assert "cicada_record_check" not in out and "tell the person what it said" in out


def test_one_check_per_site_per_call_like_a_site_entry(setup):
    server, memory = setup
    fact_sources.add_source(memory, "bob-example", "https://team-labs.io/people", predicate="works-at",
                            added_by="user", kind="url")
    _commit(memory)
    out = server.handle_tool("cicada_reading_queue", {})
    assert out.count("a source to check for") == 1 and "1 more link(s) are waiting" in out


def test_the_hook_count_includes_checks(setup):
    server, memory = setup
    asks, derived = reading_queue.counts(memory)
    assert asks == 0 and derived == 1
    assert reading_queue.count_waiting(memory) == 1


def test_a_source_linked_to_its_own_page_names_it_in_the_entry_and_the_episode(setup):
    server, memory = setup
    _entity(memory, "media-team-page", type="media", name="Team page")
    fact_sources.change_source(memory, "bob-example", TEAM, "works-at", actor="user", entity="media-team-page")
    _commit(memory)
    (e,) = _entries(memory)
    assert e.linked_entity == "media-team-page"
    assert "more on it is in page `media-team-page`" in server.handle_tool("cicada_reading_queue", {})
    out = server.handle_tool("cicada_record_check", {"item_id": ITEM, "source": TEAM, "outcome": "supports",
                                                     "option_key": "b", "quotes": [QUOTE]})
    ep = re.search(r"episode `(ep_[^`]+)`", out).group(1)
    assert markdown_parser.parse(memory / "episodes" / f"{ep}.md").frontmatter["media_entity_id"] == "media-team-page"
    # a dangling link is ignored
    (memory / "entities" / "media-team-page.md").unlink()
    bank_index.invalidate()
    assert all(x.linked_entity == "" for x in _entries(memory, ignore_recent=True))


def test_the_permissions_page_lists_a_site_only_sources_reach_with_how_many_questions(reading):
    server, memory = reading
    (memory / "inbox").mkdir(exist_ok=True)
    _item(memory)
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="user", kind="url")
    _commit(memory)
    enable()
    rows = {r["site"]: r for r in reading_queue.site_rows(memory)}
    assert rows[SITE]["checks"] == 1 and rows[SITE]["allowed"] is False and rows[SITE]["waiting"] == 0
    raw = json.dumps(list(rows.values()))
    assert "http" not in raw and "staff" not in raw and "Where does" not in raw, "counts only: no link, path or question"


# ---------- recording ----------


def _record(server, **kw):
    args = {"item_id": ITEM, "source": TEAM, "outcome": "supports", "option_key": "b", "quotes": [QUOTE], **kw}
    return server.handle_tool("cicada_record_check", args)


def test_record_check_writes_one_episode_one_checks_row_and_one_commit_under_the_harness(setup):
    server, memory = setup
    before = {p.name: p.read_text() for p in (memory / "entities").glob("*.md")}
    (memory / "notes.md").write_text("an unrelated dirty file\n")
    out = _record(server, summary="The staff page lists him under company-b.", via="browser tool")
    assert out.startswith("Recorded your check") and "recommended to the person" in out and "settles nothing" in out
    assert "cicada_" not in out.replace("cicada_record", "")
    ep = re.search(r"episode `(ep_[^`]+)`", out).group(1)
    f = markdown_parser.parse(memory / "episodes" / f"{ep}.md")
    assert f.frontmatter["source"] == "source-check" and f.frontmatter["processed"] is True
    assert f.frontmatter["processed_by"] == "agent" and "evidence_kind" not in f.frontmatter
    assert f.frontmatter["checker_kind"] == "agent" and f.frontmatter["item_id"] == ITEM
    assert f.body.startswith("assistant: The staff page lists him under company-b.")
    assert "attachment [team-labs.io]: as claude-code read it" in f.body
    text = evidence.source_text(memory, ep)
    start = text.index(QUOTE["quote"])
    assert evidence.kind_for(ep, text, start) == "page", "a quote is what the page said, as the agent read it (D4)"
    item = markdown_parser.parse(memory / "inbox" / f"{ITEM}.md").frontmatter
    (row,) = item["checks"]
    assert (row["outcome"], row["option_key"], row["ref"], row["host"], row["checker"]) == (
        "supports", "b", TEAM, SITE, "claude-code") and row["quote"] == QUOTE["quote"] and row["via"] == "browser tool"
    msg = _git(memory, "log", "-1", "--format=%B")
    assert f"inbox/{ITEM}.md: updated" in msg and "Cicada-Author: claude-code" in msg and "Cicada-Engine" not in msg
    assert sorted(_git(memory, "show", "--name-only", "--format=", "HEAD").split()) == sorted(
        [f"episodes/{ep}.md", f"inbox/{ITEM}.md"])
    assert "notes.md" in _git(memory, "status", "--porcelain"), "never git add -A"
    assert TEAM not in msg and QUOTE["quote"] not in msg
    # nothing was settled, nothing changed
    assert {p.name: p.read_text() for p in (memory / "entities").glob("*.md")} == before
    (still,) = [i for i in inbox_service.load_inbox(memory) if i.id == ITEM]
    assert still.status == "pending" and [o.key for o in still.options] == ["a", "b"]
    assert [(c.outcome, c.option_key, c.quote) for c in still.checks] == [("supports", "b", QUOTE["quote"])]
    assert still.last_checked_at == still.checks[0].at


def test_a_proposed_value_is_stored_on_the_row_only_and_adds_no_option_and_no_claim(setup):
    server, memory = setup
    out = _record(server, outcome="proposes", option_key=None, proposed_value="company-c")
    assert "noted as what you reported" in out
    item = markdown_parser.parse(memory / "inbox" / f"{ITEM}.md").frontmatter
    assert item["checks"][0]["proposed_value"] == "company-c" and len(item["options"]) == 2
    assert "company-c" not in (memory / "entities" / "bob-example.md").read_text()


def test_checks_keep_the_newest_per_source_at_most_five(setup):
    server, memory = setup
    path = memory / "inbox" / f"{ITEM}.md"
    for i in range(7):
        check_record.append_check(path, {"at": f"2026-09-0{i + 1}T00:00:00+00:00", "checker": "x", "checker_kind": "agent",
                                         "ref": f"https://team-labs.io/p{i}", "host": SITE, "outcome": "unclear",
                                         "episode": "ep_x"})
    check_record.append_check(path, {"at": "2026-09-09T00:00:00+00:00", "checker": "y", "checker_kind": "agent",
                                     "ref": "https://team-labs.io/p6", "host": SITE, "outcome": "supports",
                                     "episode": "ep_z"})
    rows = markdown_parser.parse(path).frontmatter["checks"]
    assert len(rows) == check_record.MAX_CHECKS == 5
    assert [r["ref"][-2:] for r in rows][-1] == "p6" and rows[-1]["outcome"] == "supports"


def test_needs_login_pauses_the_site_writes_nothing_and_commits_nothing(setup):
    server, memory = setup
    head = _git(memory, "rev-parse", "HEAD")
    out = server.handle_tool("cicada_record_check", {"item_id": ITEM, "source": TEAM, "outcome": "needs_login"})
    assert out.startswith("Recorded: the person needs to sign in") and "Do not sign in" in out
    assert _git(memory, "rev-parse", "HEAD") == head and _git(memory, "status", "--porcelain").strip() == ""
    assert "checks" not in markdown_parser.parse(memory / "inbox" / f"{ITEM}.md").frontmatter
    assert reading_queue.paused_sites(reading_queue._live_rows(memory, None)) == {SITE}
    assert _entries(memory) == [] and reading_queue.entries(memory) == []


@pytest.mark.parametrize("outcome,word", [("blocked", "blocked"), ("not_found", "not found"), ("failed", "failed")])
def test_the_other_non_findings_hold_the_source_for_a_week(setup, outcome, word):
    server, memory = setup
    out = server.handle_tool("cicada_record_check", {"item_id": ITEM, "source": TEAM, "outcome": outcome})
    assert "not asked again for a week" in out and word in out
    assert _entries(memory) == []


def test_refusals_come_in_a_fixed_order_and_write_nothing(setup, monkeypatch):
    server, memory = setup
    head = _git(memory, "rev-parse", "HEAD")

    def call(**kw):
        args = {"item_id": ITEM, "source": TEAM, "outcome": "supports", "option_key": "b", "quotes": [QUOTE], **kw}
        return server.handle_tool("cicada_record_check", args)

    assert call(outcome="settled").startswith("Error: outcome must be one of")
    assert call(item_id="inbox-1").startswith("Error: item_id must look like")
    assert call(source="https://team-labs.io/x?token=abcdef0123456789abcdef0123456789").startswith("Not recorded")
    assert "not on the person's list" in call(source="https://team-labs.io/not-listed")
    assert "not on the person's list" in call(item_id="inbox-099")
    assert "needs at least one short quote" in call(quotes=[])
    assert "needs at least one short quote" in call(outcome="contradicts_all", option_key=None, quotes=None)
    assert "`option_key` must be the key" in call(option_key="zz")
    assert "`option_key` must be the key" in call(option_key=None)
    assert "`proposed_value` is what the page says" in call(outcome="proposes", option_key=None)
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: True)
    assert "consolidating memory right now" in call()
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    assert _git(memory, "rev-parse", "HEAD") == head and list((memory / "episodes").glob("ep_*source-check*")) == []
    assert "checks" not in markdown_parser.parse(memory / "inbox" / f"{ITEM}.md").frontmatter
    reading_settings.update(agent_enabled_=False)
    assert call().startswith("Agent reading is off")
    enable(sites=(SITE,))
    (memory / "_bank.yaml").write_text("kind: demo\n")
    from api.services import demo_guard

    assert call() == demo_guard.AGENT_REFUSAL


def test_a_resolved_item_a_removed_source_or_a_revoked_site_revokes_recording_at_once(setup):
    server, memory = setup
    enable()
    assert "not on the person's list" in _record(server)
    enable(sites=(SITE,))
    fact_sources.change_source(memory, "bob-example", TEAM, "works-at", actor="user", action="remove")
    bank_index.invalidate()
    assert "not on the person's list" in _record(server)
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="user", kind="url")
    bank_index.invalidate()
    assert "Recorded your check" in _record(server)
    (memory / "inbox" / f"{ITEM}.md").unlink()
    bank_index.invalidate()
    assert "not on the person's list" in _record(server, source=TEAM)


def test_caps_three_a_question_a_day_and_thirty_a_session(setup, monkeypatch):
    server, memory = setup
    for n in range(3):
        check_record.append_check(memory / "inbox" / f"{ITEM}.md", {
            "at": datetime.now(timezone.utc).isoformat(), "checker": "x", "checker_kind": "agent",
            "ref": f"https://team-labs.io/older-{n}", "host": SITE, "outcome": "unclear", "episode": "ep_x"})
    bank_index.invalidate()
    out = _record(server)
    assert "already checked three times today" in out
    # the session cap: thirty a session, counted per connection and conversation
    mcp_tools._CHECKS_BY_SESSION.clear()
    mcp_tools._CHECKS_BY_SESSION[":ses_read_fixed"] = mcp_tools.MAX_CHECKS_PER_SESSION
    _item(memory, "inbox-011")
    _commit(memory)
    assert "most checks it may" in server.handle_tool("cicada_record_check", {
        "item_id": "inbox-011", "source": TEAM, "outcome": "supports", "option_key": "b", "quotes": [QUOTE]})
    mcp_tools._CHECKS_BY_SESSION.clear()


def test_a_finding_never_writes_a_claim_resolves_or_reorders(setup):
    server, memory = setup
    claims_before = (memory / "entities" / "bob-example.md").read_text()
    order_before = [i.id for i in inbox_service.load_inbox(memory)]
    assert "Recorded your check" in _record(server)
    assert (memory / "entities" / "bob-example.md").read_text() == claims_before
    assert [i.id for i in inbox_service.load_inbox(memory)] == order_before
    assert (memory / "inbox" / f"{ITEM}.md").exists()
    import inspect

    code = inspect.getsource(check_record).split('"""', 2)[2]   # the code, not the docstring that says what it never does
    assert "write_claim" not in code and "resolve" not in code.lower() and "unlink" not in code


def test_the_ledger_row_is_ids_and_enums_only(setup, monkeypatch):
    server, memory = setup
    rows = []
    monkeypatch.setattr(telemetry, "record", lambda ev: rows.append(ev))
    _record(server, summary="He works at company-b now.")
    (row,) = [r for r in rows if r.kind == telemetry.CHECK_AGENT_KIND]
    assert row.refs == {"item_id": ITEM, "entity_id": "bob-example", "outcome": "supports", "host_class": "public",
                        "effect": "recommended", "harness": "claude-code"}
    blob = json.dumps(row.refs)
    assert TEAM not in blob and SITE not in blob and QUOTE["quote"] not in blob and "company-b" not in blob
    assert telemetry.CHECK_AGENT_KIND in telemetry.SIBLING_KINDS and telemetry.CHECK_AGENT_KIND in telemetry.NON_SPEND_KINDS


# ---------- what the question shows an agent, and what a remote connection may see ----------


def test_check_nudges_shows_check_first_then_checked_by_and_hides_the_quote_without_sources(setup):
    server, memory = setup
    out = server.handle_tool("cicada_check_nudges", {})
    assert f"Check first: {TEAM}" in out and f'cicada_record_check(item_id="{ITEM}"' in out
    _record(server)
    bank_index.invalidate()
    out = server.handle_tool("cicada_check_nudges", {})
    assert "Checked by claude-code" in out and QUOTE["quote"] in out and "supports company-b" in out
    assert "(reported, not verified; the person still answers)" in out
    assert f"Check first: {TEAM}" not in out, "a source just looked at is not offered again"
    # a remote connection without `sources` never sees the page's words; one without record never sees Check first
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_r", harness="claude-web", connector_id="ab12cd34",
                                raw_excerpts=False, available=frozenset({"cicada_check_nudges", "cicada_record_check"}))
    out = mcp_tools.check_nudges(ctx, None)
    assert "Checked by claude-web" not in out or QUOTE["quote"] not in out
    assert QUOTE["quote"] not in out
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="ses_r", harness="claude-web", connector_id="ab12cd34",
                                raw_excerpts=True, available=frozenset({"cicada_check_nudges"}))
    assert "Check first:" not in mcp_tools.check_nudges(ctx, None)


def test_the_inbox_wire_serves_the_findings_additively(setup):
    from fastapi.testclient import TestClient

    from api import main

    server, memory = setup
    _record(server)
    bank_index.invalidate()
    import os

    os.environ["CICADA_MEMORY_PATH"] = str(memory)
    config.get_settings.cache_clear()
    try:
        item = next(i for i in TestClient(main.app).get("/inbox").json() if i["id"] == ITEM)
    finally:
        config.get_settings.cache_clear()
        os.environ.pop("CICADA_MEMORY_PATH", None)
    (c,) = item["checks"]
    assert (c["outcome"], c["optionKey"], c["host"], c["checker"], c["checkerKind"]) == ("supports", "b", SITE, "claude-code", "agent")
    assert c["quote"] == QUOTE["quote"] and item["lastCheckedAt"] == c["at"]
    assert item["check"]["targets"][0]["ref"] == TEAM


# ---------- remote ----------


@pytest.fixture
def remote(setup, monkeypatch):
    server, memory = setup
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield RemoteRuntime(post=lambda p, d: {}, sleep_running=lambda: False), memory
    config.get_settings.cache_clear()


def _connector(scopes=catalog.DEFAULT_SCOPES):
    return catalog.Connector(id="ab12cd34", label="Phone", app="claude", scopes=frozenset(scopes),
                             created_at="2026-09-01T00:00:00+00:00", last_client="claude-ai")


def test_the_tool_is_record_scoped_a_write_and_only_a_finding_waits_for_sleep():
    from api.remote import runtime

    assert catalog.TOOL_SCOPE["cicada_record_check"] == "record" and "cicada_record_check" in catalog.WRITE_TOOLS
    assert "cicada_record_check" in catalog.tool_names_for({"record"})
    assert "cicada_record_check" not in catalog.tool_names_for({"read"})
    assert runtime._writes_bank("cicada_record_check", {"outcome": "supports"}) is True
    assert runtime._writes_bank("cicada_record_check", {"outcome": "needs_login"}) is False
    assert runtime._writes_bank("cicada_record_check", {"outcome": "bogus"}) is True
    d = remote_tools.REMOTE_TOOLS["cicada_record_check"]
    assert "cicada_" not in d["description"] and d["inputSchema"]["required"] == ["item_id", "source", "outcome"]
    assert d["annotations"]["read_only_hint"] is False


def test_a_remote_check_is_the_apps_with_its_own_commit_and_kind(remote):
    runtime, memory = remote
    text, status = runtime.call(_connector(), "cicada_record_check",
                                {"item_id": ITEM, "source": TEAM, "outcome": "supports", "option_key": "b",
                                 "quotes": [QUOTE]})
    assert status == "ok" and text.startswith("Recorded your check")
    msg = _git(memory, "log", "-1", "--format=%B")
    assert "Cicada-Author: claude-web" in msg and "trigger: remote/claude-web" in msg
    row = markdown_parser.parse(memory / "inbox" / f"{ITEM}.md").frontmatter["checks"][0]
    assert row["checker_kind"] == "remote" and row["checker"] == "claude-web"
    busy = RemoteRuntime(post=lambda p, d: {}, sleep_running=lambda: True)
    from api.remote.runtime import BUSY_TEXT

    assert busy.call(_connector(), "cicada_record_check", {"item_id": ITEM, "source": TEAM, "outcome": "supports",
                                                          "option_key": "b", "quotes": [QUOTE]})[0] == BUSY_TEXT


def test_the_stdio_schema_names_the_arguments_the_primer_names():
    from _stdio_server import stdio_server

    tool = {t["name"]: t for t in stdio_server().TOOLS}["cicada_record_check"]
    props = set(tool["inputSchema"]["properties"])
    assert {"item_id", "source", "outcome", "option_key", "quotes"} <= props
    assert tool["inputSchema"]["required"] == ["item_id", "source", "outcome"]


def test_the_new_tool_copy_names_no_provider():
    from _stdio_server import stdio_server

    banned = re.compile(r"ollama|claude|chatgpt|haiku|\bopus\b|sonnet|gpt-|gemini|openrouter|anthropic|openai|codex",
                        re.IGNORECASE)
    tool = {t["name"]: t for t in stdio_server().TOOLS}["cicada_record_check"]
    texts = [tool["description"], remote_tools.REMOTE_TOOLS["cicada_record_check"]["description"]]
    for t in (tool, remote_tools.REMOTE_TOOLS["cicada_record_check"]):
        texts += [p.get("description", "") for p in t["inputSchema"]["properties"].values()]
    assert not [t for t in texts if banned.search(t)]


# ---------- the review round ----------


def test_the_same_source_cannot_be_recorded_again_inside_the_week(setup):
    """`append_check` keeps one row per source, so the per-day cap alone never bit: an agent could re-record one page
    without limit (a new episode and commit each time)."""
    server, memory = setup
    assert "Recorded your check" in _record(server)
    head = _git(memory, "rev-parse", "HEAD")
    episodes = sorted(p.name for p in (memory / "episodes").glob("ep_*.md"))
    for _ in range(2):
        out = _record(server)
        assert out.startswith("Not recorded") and "already looked at that source" in out
    assert _git(memory, "rev-parse", "HEAD") == head, "no new commit"
    assert sorted(p.name for p in (memory / "episodes").glob("ep_*.md")) == episodes, "no new episode"
    # a check older than the window may be recorded again
    path = memory / "inbox" / f"{ITEM}.md"
    fm = markdown_parser.parse(path)
    fm.frontmatter["checks"][0]["at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    markdown_parser.write(path, fm.frontmatter, fm.body)
    bank_index.invalidate()
    assert "Recorded your check" in _record(server, quotes=[{"quote": "a different sentence on the page"}])


def test_the_hook_count_never_derives_a_cold_inbox_on_its_own_time(setup, monkeypatch):
    server, memory = setup
    reading_queue._candidate_memo.clear()
    calls = []
    real = inbox_service.load_inbox

    def slow(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(inbox_service, "load_inbox", slow)
    started = []
    monkeypatch.setattr(reading_queue, "_warm_candidates", lambda mp: started.append(mp))
    import time

    bank_index.files(memory, "entities")   # the page cache is warm; only the check candidates are cold
    asks, derived = reading_queue.counts(memory, warm_only=True, deadline=time.monotonic() + 5)
    assert derived == 0 and calls == [] and started, "cold: checks not counted yet, nothing derived, a warm started"
    reading_queue._check_candidates(memory)        # warmed (by the background thread in real life)
    calls.clear()
    asks, derived = reading_queue.counts(memory, warm_only=True, deadline=time.monotonic() + 5)
    assert derived == 1 and calls == [], "warm: counted from the memo, no inbox load"
    # past the deadline: unknown again, never blocked
    asks, derived = reading_queue.counts(memory, warm_only=True, deadline=time.monotonic() - 1)
    assert derived is None


def test_the_candidate_memo_follows_the_inbox_and_the_sources(setup):
    server, memory = setup
    reading_queue._candidate_memo.clear()
    assert len(reading_queue._check_candidates(memory)) == 1
    fact_sources.add_source(memory, "bob-example", "https://team-labs.io/people", predicate="works-at", added_by="user",
                            kind="url")
    bank_index.invalidate()
    assert len(reading_queue._check_candidates(memory)) == 2, "a new source moves the stamp"


def test_a_bank_with_no_question_items_never_loads_the_inbox(reading, monkeypatch):
    server, memory = reading
    (memory / "inbox").mkdir(exist_ok=True)
    for f in (memory / "inbox").glob("*.md"):
        f.unlink()
    markdown_parser.write(memory / "inbox" / "inbox-001.md", {"kind": "decay", "status": "pending",
                                                              "entity_id": "beta-project"}, "x")
    reading_queue._candidate_memo.clear()
    monkeypatch.setattr(inbox_service, "load_inbox", lambda *a, **k: (_ for _ in ()).throw(AssertionError("loaded")))
    bank_index.invalidate()
    assert reading_queue._check_candidates(memory) == []


def test_the_week_is_counted_in_utc_days(setup):
    server, memory = setup
    now = datetime(2026, 10, 10, 23, 30, tzinfo=timezone.utc)
    check_record.append_check(memory / "inbox" / f"{ITEM}.md", {
        "at": "2026-10-02T00:10:00+00:00", "checker": "x", "checker_kind": "agent", "ref": TEAM, "host": SITE,
        "outcome": "unclear", "episode": "ep_x"})
    bank_index.invalidate()
    assert len(_entries(memory, now=now)) == 1, "Oct 2 is 8 UTC days before Oct 10: due again"
    assert _entries(memory, now=datetime(2026, 10, 9, 23, 30, tzinfo=timezone.utc)) == [], "7 days: still held"


def test_the_five_row_cap_evicts_the_oldest_by_time(setup):
    server, memory = setup
    path = memory / "inbox" / f"{ITEM}.md"
    for i, day in enumerate(("05", "01", "03", "02", "04", "06")):
        check_record.append_check(path, {"at": f"2026-09-{day}T00:00:00+00:00", "checker": "x", "checker_kind": "agent",
                                         "ref": f"https://team-labs.io/p{i}", "host": SITE, "outcome": "unclear",
                                         "episode": "ep_x"})
    days = [r["at"][8:10] for r in markdown_parser.parse(path).frontmatter["checks"]]
    assert days == ["02", "03", "04", "05", "06"], "the oldest by time (the 1st) went, whatever the order written"
