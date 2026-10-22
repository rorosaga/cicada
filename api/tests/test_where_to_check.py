"""G61 "Where to check" (G208, ruling 36 D5, 2026-10-22): links already on the record proposed as sources, one
question per page, Sleep settling only on the person's own located words, the person's answer driving the picture
ladder and ruling 26's re-check, the agent's inferred add, and the card's chip-row wire. Synthetic bank (every name a
placeholder); git is real; nothing reaches a network."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank, _entity
from api.models.schemas import InboxResolveRequest
from api.services import (
    fact_sources, inbox_service, inbox_tend, markdown_parser, person_photo, sleep_cycle, source_proposals,
    source_refresh,
)

GH = "https://github.com/bob-example"
X = "https://x.com/bob_example"
IG = "https://www.instagram.com/bob.example"
EP = "ep_2026-09-05_001"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _commit_all(memory):
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "seed", "--allow-empty")


def _fm(memory, eid="bob-example") -> dict:
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter


def _person(memory, body: str, **fm):
    _entity(memory, "bob-example", type="person", name="Bob Example", body=body, **fm)


def _episode(memory, eid: str, body: str):
    markdown_parser.write(memory / "episodes" / f"{eid}.md",
                          {"id": eid, "timestamp": f"{eid[3:13]}T09:00:00+00:00", "processed": True,
                           "title": "chat"}, body)


def _questions(memory) -> list[Path]:
    out = []
    for p in sorted((memory / "inbox").glob("inbox-*.md")):
        if markdown_parser.parse(p).frontmatter.get("asks") == source_proposals.ASKS:
            out.append(p)
    return out


async def _load(memory):
    return inbox_service.load_inbox(memory)


def _resolve(memory, item: str, **request) -> dict:
    return asyncio.run(inbox_service.resolve(item, InboxResolveRequest(**request),
                                             SimpleNamespace(memory_path=memory)))


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    return _bank(tmp_path)


# ---------- what a link is ----------


@pytest.mark.parametrize("ref,kind,canonical", [
    ("https://github.com/bob-example/", "github", GH),
    ("https://twitter.com/bob_example", "x", X),
    ("https://instagram.com/bob.example/", "instagram", IG),
    ("https://linkedin.com/in/bob-example", "linkedin", "https://www.linkedin.com/in/bob-example"),
    ("https://scholar.google.com/citations?user=AbCdEf123&hl=en", "scholar",
     "https://scholar.google.com/citations?user=AbCdEf123"),
    ("https://orcid.org/0000-0002-1825-0097", "orcid", "https://orcid.org/0000-0002-1825-0097"),
])
def test_a_profile_link_has_one_canonical_form(ref, kind, canonical):
    assert source_proposals.profile_of(ref)[:2] == (kind, canonical)


@pytest.mark.parametrize("ref", [
    "https://github.com/bob-example/alpha", "https://x.com/bob_example/status/1", "https://www.instagram.com/p/abc",
    "https://www.linkedin.com/company/alpha", "https://example.com/bob-example", "https://github.com/settings",
    "https://www.instagram.com/explore",
])
def test_a_post_a_repo_or_a_site_page_is_no_profile(ref):
    assert source_proposals.profile_of(ref) is None


def test_the_chip_says_what_every_kind_of_source_is():
    kind = source_proposals.link_kind
    assert kind({"ref": GH, "kind": "url"}) == ("github", "@bob-example")
    assert kind({"ref": "https://github.com/bob-example/alpha", "kind": "url"}) == ("repo", "bob-example/alpha")
    assert kind({"ref": "addressbook://ABC-123", "kind": "app"}) == ("contacts", "Contacts")
    assert kind({"ref": "https://example.com/team", "kind": "url"}) == ("website", "example.com")
    assert kind({"ref": "ask me — I announce job changes", "kind": "note"})[0] == "note"
    assert kind({"ref": "~/src/alpha", "kind": "path"}) == ("path", "alpha")


# ---------- Sleep's proposal ----------


def test_a_profile_in_the_pages_own_text_is_proposed_untrusted_with_one_question_and_no_face(memory):
    _person(memory, f"## Summary\nBob Example builds tools.\n\n## Links\n- [GitHub]({GH}/)\n")
    report = source_proposals.propose(memory, today="2026-09-10")
    assert report.proposed == 1 and report.questions == 1
    [entry] = fact_sources.list_sources(memory, "bob-example")
    assert entry["ref"] == GH and entry["predicate"] == "github" and entry["added_by"] == "cicada"
    assert entry["proposed"] is True and entry["evidence"] == {"page": True}
    assert not fact_sources.trusted(entry) and not person_photo.is_own_account(entry)
    assert not source_refresh.tracked(entry), "a proposal is never re-checked"
    assert person_photo.candidates(_fm(memory), owner={}, proxy=True) == [], "never a face from a proposal"
    [q] = _questions(memory)
    qfm = markdown_parser.parse(q).frontmatter
    assert qfm["kind"] == "clarification" and qfm["review"] is True and "entity_id" not in qfm
    assert [(r["page"], r["ref"], r["link_kind"]) for r in qfm["rows"]] == [("bob-example", GH, "github")]
    assert [o["key"] for o in qfm["options"]] == ["yes", "no"] and qfm["required_input"] == "choice"
    again = source_proposals.propose(memory, today="2026-09-10")
    assert (again.paths, again.proposed) == ([], 0), "idempotent"


def test_a_removed_or_already_listed_link_is_never_proposed(memory):
    _person(memory, f"## Links\n- {GH}\n- {X}\n",
            sources=[{"ref": X, "kind": "url", "predicate": "x", "added_by": "user"}],
            sources_removed=[{"ref": GH, "predicate": "profile", "by": "user", "at": "2026-09-01"}])
    assert source_proposals.propose(memory).proposed == 0
    assert _questions(memory) == []


def test_nothing_is_proposed_from_a_name(memory):
    _person(memory, "## Summary\nBob Example, known as bob_example online.\n")
    assert source_proposals.propose(memory).proposed == 0


def test_a_projects_own_repo_is_proposed_and_another_repo_is_not(memory):
    _entity(memory, "alpha-project", type="project", name="Alpha Project",
            body="## Links\n- https://github.com/bob-example/alpha-project\n- https://github.com/bob-example/other\n")
    source_proposals.propose(memory)
    [entry] = fact_sources.list_sources(memory, "alpha-project")
    assert entry["ref"] == "https://github.com/bob-example/alpha-project" and entry["predicate"] == "repo"


def test_the_persons_own_line_naming_the_page_carries_a_span_and_settles_by_rule_29(memory):
    _person(memory, "## Summary\nA builder.\n", source_episodes=[EP])
    _episode(memory, EP, f"user: Bob Example's github is {GH} by the way\n\nassistant: Noted.")
    _commit_all(memory)
    source_proposals.propose(memory)
    [entry] = fact_sources.list_sources(memory, "bob-example")
    ev = entry["evidence"]
    assert ev["episode"] == EP and "start" in ev and "quote" not in ev, "a span, never a copy"
    [q] = _questions(memory)
    qfm = markdown_parser.parse(q).frontmatter
    assert not qfm.get("review") and qfm["entity_id"] == "bob-example" and len(qfm["rows"]) == 1, \
        "a link Sleep may settle waits in a one-row item of its own, never in the review"
    d, why = inbox_tend.policy(memory, q, qfm)
    assert why == "" and d.rule == "named_account" and d.request == {"action": "resolve", "option_key": "yes"}


@pytest.mark.parametrize("line", [
    # The review of #422's repro: the person's own line names Bob and carries Carol's account.
    "Bob Example told me to follow https://github.com/carol-example for the new release",
    # One line naming two pages: whose account it is, only the person says.
    f"Bob Example and Carl Example share {GH} for the demo",
    # The handle is not the page's name (a LinkedIn slug with a suffix, an id-only profile).
    "Bob Example is https://www.linkedin.com/in/bob-example-4a1b2c on LinkedIn",
    "Bob Example's papers: https://orcid.org/0000-0002-1825-0097",
], ids=["someone-elses-account", "two-pages-one-line", "handle-not-the-name", "id-only-profile"])
def test_co_occurrence_is_never_proof_the_person_decides(memory, line):
    _person(memory, "## Summary\nA builder.\n", source_episodes=[EP])
    _entity(memory, "carl-example", type="person", name="Carl Example")
    _episode(memory, EP, f"user: {line}\n\nassistant: Noted.")
    source_proposals.propose(memory)
    [q] = _questions(memory)
    qfm = markdown_parser.parse(q).frontmatter
    assert qfm["review"] is True, "it waits in the review"
    d, why = inbox_tend.policy(memory, q, qfm)
    assert d is None and why == "person_only", "never a person's identity from co-occurrence (ruling 29)"
    page = _fm(memory)
    assert all(not person_photo.is_own_account(s) for s in fact_sources.as_sources(page.get("sources")))


def test_an_alias_handle_settles_and_a_name_the_line_shares_with_the_page_is_no_second_page(memory):
    _person(memory, "## Summary\nA builder.\n", source_episodes=[EP], aliases=["bobex"])
    _episode(memory, EP, "user: Bob Example posts as https://x.com/bobex these days\n\nassistant: ok")
    source_proposals.propose(memory)
    [q] = _questions(memory)
    d, why = inbox_tend.policy(memory, q, markdown_parser.parse(q).frontmatter)
    assert d is not None and d.rule == "named_account", why


@pytest.mark.parametrize("body", [
    f"assistant: Bob Example's github is {GH}\n\nuser: thanks",    # the agent's words, not the person's
    f"user: someone's github is {GH}\n\nassistant: ok",            # the person's line does not name the page
], ids=["agents-words", "line-without-the-name"])
def test_without_the_persons_own_words_naming_it_nothing_is_settled(memory, body):
    _person(memory, f"## Links\n- {GH}\n", source_episodes=[EP])
    _episode(memory, EP, body)
    source_proposals.propose(memory)
    [q] = _questions(memory)
    d, why = inbox_tend.policy(memory, q, markdown_parser.parse(q).frontmatter)
    assert d is None and why == "person_only", "never a person's identity without their words (ruling 29)"


def test_no_other_rule_or_trace_may_settle_a_where_to_check_question(memory):
    _person(memory, f"## Links\n- {GH}\n")
    source_proposals.propose(memory)
    [q] = _questions(memory)
    assert inbox_tend.touched(memory, [{"id": EP, "content": f"user: Bob Example {GH}"}],
                              [(q, markdown_parser.parse(q).frontmatter, "")]) == []
    row = {"id": q.stem, "kind": "clarification",
           "apply": {"rule": "said_on_record", "item_sha256": inbox_tend._sha256(q.read_bytes()),
                     "request": {"action": "resolve", "option_key": "yes"}}}
    with pytest.raises(inbox_tend.Unvetted):
        inbox_tend.vetted_decision(memory, row)


# ---------- the person's answer ----------


def test_yes_takes_them_draws_the_face_and_makes_them_due_for_the_recheck(memory):
    _person(memory, f"## Links\n- {GH}\n- {X}\n- {IG}\n")
    _commit_all(memory)
    source_proposals.propose(memory)
    _commit_all(memory)
    [q] = _questions(memory)
    assert _resolve(memory, q.stem, action="resolve", option_key="yes")["status"] == "resolved"
    entries = fact_sources.list_sources(memory, "bob-example")
    assert all(e["accepted"] and "proposed" not in e for e in entries)
    assert all(person_photo.is_own_account(e) and source_refresh.tracked(e) for e in entries)
    assert source_refresh.checker(next(e for e in entries if e["ref"] == X)) == source_refresh.AGENT, \
        "a walled site is re-checked only by the person's agent"
    found = person_photo.candidates(_fm(memory), owner={}, proxy=True)
    assert [c.provider for c in found] == ["github", "x", "instagram"]
    assert person_photo.provider_url(found[2]) == "https://unavatar.io/instagram/bob.example?fallback=false"
    assert [c.provider for c in person_photo.candidates(_fm(memory), owner={}, proxy=False)] == ["github"], \
        "the proxy's off switch still works"
    assert not q.exists() and _questions(memory) == []
    msg = _git(memory, "log", "-5", "--format=%B", "--grep", "inbox/clarification/resolved")
    assert "Cicada-Author: user" in msg and "entities/bob-example.md" in msg
    assert source_proposals.propose(memory).paths == [], "nothing asked again"


def test_one_review_for_every_page_answered_row_by_row(memory):
    _person(memory, f"## Links\n- {GH}\n- {X}\n")
    _entity(memory, "carl-example", type="person", name="Carl Example", body=f"## Links\n- {IG}\n")
    _commit_all(memory)
    source_proposals.propose(memory)
    _commit_all(memory)
    [q] = _questions(memory)
    rows = markdown_parser.parse(q).frontmatter["rows"]
    assert sorted((r["page"], r["ref"]) for r in rows) == [("bob-example", GH), ("bob-example", X),
                                                           ("carl-example", IG)]
    item = next(i for i in asyncio.run(_load(memory)) if i.id == q.stem)
    assert item.review and [r.link_kind for r in item.rows] == [r["link_kind"] for r in rows], "the app's wire"
    gh_row = next(r["id"] for r in rows if r["ref"] == GH)
    _resolve(memory, q.stem, action="resolve", option_key="yes", row=gh_row)
    left = markdown_parser.parse(q).frontmatter
    assert len(left["rows"]) == 2 and left["title"] == "Confirm 2 links", "the other rows still wait"
    bob = {e["ref"]: e for e in fact_sources.list_sources(memory, "bob-example")}
    assert bob[GH]["accepted"] and bob[X]["proposed"], "exactly the answered row"
    ig_row = next(r["id"] for r in left["rows"] if r["ref"] == IG)
    _resolve(memory, q.stem, action="resolve", option_key="no", row=ig_row)
    assert _fm(memory, "carl-example")["sources_removed"][0]["ref"] == IG
    _resolve(memory, q.stem, action="resolve", option_key="yes")
    assert not q.exists() and fact_sources.list_sources(memory, "bob-example")[1]["accepted"]
    with pytest.raises(Exception):
        _resolve(memory, q.stem, action="resolve", option_key="yes", row=gh_row)
    assert source_proposals.propose(memory).paths == [], "nothing asked again"


def test_an_undone_settle_stays_the_persons_one_row_question(memory):
    _person(memory, "## Summary\nA builder.\n", source_episodes=[EP])
    _episode(memory, EP, f"user: Bob Example's github is {GH} by the way\n\nassistant: Noted.")
    _commit_all(memory)
    source_proposals.propose(memory)
    _commit_all(memory)
    report = inbox_tend.Report()
    asyncio.run(inbox_tend.policy_pass(memory, SimpleNamespace(memory_path=memory), report, record_cap=0))
    assert report.settled == 1 and fact_sources.list_sources(memory, "bob-example")[0]["accepted"]
    [settled] = list((memory / "inbox" / "settled").glob("inbox-*.md"))
    restored, paths, _lines, _rec = inbox_tend.undo(memory, settled.stem)
    _commit_all(memory)
    assert fact_sources.list_sources(memory, "bob-example")[0]["proposed"] is True, "the link waits again"
    source_proposals.propose(memory)
    [q] = _questions(memory)
    qfm = markdown_parser.parse(q).frontmatter
    assert q.stem == restored and qfm["sleep_settle"] == "undone" and not qfm.get("review"), \
        "it stays the person's own question: never re-settled, never folded into the review"
    assert inbox_tend.policy(memory, q, qfm)[0] is None


def test_no_removes_them_and_they_are_never_proposed_again(memory):
    _person(memory, f"## Links\n- {GH}\n")
    _commit_all(memory)
    source_proposals.propose(memory)
    _commit_all(memory)
    [q] = _questions(memory)
    _resolve(memory, q.stem, action="resolve", option_key="no")
    fm = _fm(memory)
    assert "sources" not in fm and fm["sources_removed"][0]["ref"] == GH and fm["sources_removed"][0]["by"] == "user"
    assert source_proposals.propose(memory).proposed == 0 and _questions(memory) == []


def test_a_link_taken_on_the_card_retires_the_question_on_the_next_run(memory):
    _person(memory, f"## Links\n- {GH}\n")
    source_proposals.propose(memory)
    fact_sources.change_source(memory, "bob-example", GH, "github", actor="user", accepted=True)
    assert "proposed" not in fact_sources.list_sources(memory, "bob-example")[0]
    report = source_proposals.propose(memory)
    assert _questions(memory) == [] and any(p.startswith("inbox/") for p in report.paths)


def test_the_sleep_step_commits_alone_as_cicada_and_skips_a_dirty_page(memory):
    _person(memory, f"## Links\n- {GH}\n")
    _entity(memory, "carl-example", type="person", name="Carl Example", body=f"## Links\n- {X}\n")
    _commit_all(memory)
    carl = memory / "entities" / "carl-example.md"
    carl.write_text(carl.read_text() + "\nan uncommitted edit\n")
    asyncio.run(sleep_cycle._where_to_check_safely(memory))
    msg = _git(memory, "log", "-1", "--format=%B")
    assert msg.startswith("Where to check ") and "trigger: sleep/where-to-check" in msg
    assert "Cicada-Author: cicada" in msg and "Cicada-Engine" not in msg
    changed = _git(memory, "show", "--name-only", "--format=", "HEAD").split()
    assert "entities/bob-example.md" in changed and "entities/carl-example.md" not in changed
    assert any(p.startswith("inbox/inbox-") for p in changed)
    assert any(line.startswith("inbox/inbox-") and ": created (trigger: sleep/where-to-check)" in line
               for line in msg.splitlines()), "a new question is created, not updated"
    assert "sources" not in _fm(memory, "carl-example")


# ---------- an agent's inferred add ----------


@pytest.fixture
def server(memory, monkeypatch):
    srv = stdio_server()
    monkeypatch.setattr(srv, "get_memory_path", lambda: memory)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_2026-09-23_c0ffee00", "claude-code", None))
    return srv


def test_an_inferred_add_is_a_proposal_with_located_evidence(server, memory):
    _episode(memory, EP, f"user: Bob Example posts at {X}\n\nassistant: ok")
    _commit_all(memory)
    out = server.handle_add_source("bob-example", "https://twitter.com/bob_example", inferred=True,
                                   evidence=[{"episode": EP, "quote": f"Bob Example posts at {X}"},
                                             {"episode": "ep_9999-01-01_001", "quote": "nothing"}])
    assert out.startswith("Proposed ") and "waits for the person's yes" in out
    [entry] = fact_sources.list_sources(memory, "bob-example")
    assert entry["ref"] == X and entry["predicate"] == "x" and entry["added_by"] == "claude-code"
    assert entry["proposed"] is True and entry["evidence"]["episode"] == EP and entry["evidence"]["kind"] == "user"
    assert not person_photo.is_own_account(entry), "an agent's inference never draws a face"
    assert source_proposals.propose(memory).questions == 1, "it joins the page's one question"


def test_a_direct_add_is_unchanged(server, memory):
    out = server.handle_add_source("bob-example", GH, "github")
    assert out.startswith("Added ")
    [entry] = fact_sources.list_sources(memory, "bob-example")
    assert "proposed" not in entry and person_photo.is_own_account(entry)


def test_an_inferred_add_of_a_removed_link_is_refused(server, memory):
    _person(memory, "## Summary\nA builder.\n",
            sources_removed=[{"ref": GH, "predicate": "github", "by": "user", "at": "2026-09-01"}])
    _commit_all(memory)
    out = server.handle_add_source("bob-example", GH, inferred=True)
    assert out.startswith("Nothing added") and fact_sources.list_sources(memory, "bob-example") == []


# ---------- the card's chip row ----------


def test_the_sources_route_draws_the_chip_row(memory, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config
    from api.main import app

    _person(memory, f"## Links\n- {GH}\n", sources=[
        {"ref": "addressbook://ABC-123", "kind": "app", "predicate": "phone", "added_by": "cicada"}])
    _entity(memory, "alpha-project", type="project", name="Alpha Project",
            sources=[{"ref": "https://alpha-studio.dev", "kind": "url", "predicate": "website", "added_by": "user"}])
    source_proposals.propose(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        c = TestClient(app)
        rows = c.get("/entities/bob-example/sources").json()["sources"]
        site = c.get("/entities/alpha-project/sources").json()["sources"][0]
    finally:
        config.get_settings.cache_clear()
    contacts, gh = rows
    assert (contacts["linkKind"], contacts["label"], contacts["proposed"]) == ("contacts", "Contacts", False)
    assert (gh["linkKind"], gh["label"], gh["proposed"], gh["trusted"]) == ("github", "@bob-example", True, False)
    assert gh["evidence"] == {"page": True}
    assert contacts["iconSite"] is None and gh["iconSite"] is None, "a person's page draws no site mark (G159)"
    assert (site["linkKind"], site["iconSite"]) == ("website", "alpha-studio.dev")
