"""G61 S3-a — sources as a living set (owner, 2026-09-30: "sources … could be multiple, not just one. An agent
can store/change/delete sources depending on whether they are relevant for information update. Sources
themselves can be linked to their own memory node").

Synthetic bank (alpha-project, bob-example, example.com); git is real; nothing reaches a network."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _stdio_server import stdio_server
from _synthetic_bank import _bank, _entity
from api import config, main
from api.remote import catalog
from api.remote import tools as remote_tools
from api.remote.runtime import RemoteRuntime
from api.services import (bank_index, entity_merge, fact_sources, graph_builder, markdown_parser, mcp_tools,
                          source_links, source_check)

TEAM = "https://example.com/staff-directory"
PROFILE = "https://example.com/in/bob"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _fm(memory, eid="bob-example"):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter


def _sources(memory, eid="bob-example"):
    return fact_sources.list_sources(memory, eid)


@pytest.fixture(autouse=True)
def _fresh():
    bank_index.invalidate()
    yield
    bank_index.invalidate()


@pytest.fixture
def server(tmp_path, monkeypatch):
    srv = stdio_server()
    memory = _bank(tmp_path)
    monkeypatch.setattr(srv, "get_memory_path", lambda: memory)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_2026-09-23_c0ffee00", "claude-code", None))
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    return srv, memory


def _connector(cid="ab12cd34", app="claude"):
    return catalog.Connector(id=cid, label="Phone", app=app, scopes=frozenset(catalog.DEFAULT_SCOPES),
                             created_at="2026-09-01T00:00:00+00:00", last_client="claude-ai")


@pytest.fixture
def remote(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield RemoteRuntime(post=lambda p, d: {}, sleep_running=lambda: False), memory
    config.get_settings.cache_clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


# ---------- many per fact, caps, rank ----------


def test_many_sources_per_predicate_and_caps(tmp_path):
    memory = _bank(tmp_path)
    for i in range(3):
        fact_sources.add_source(memory, "bob-example", f"https://example.com/w{i}", predicate="website",
                                added_by="claude-code")
    fact_sources.add_source(memory, "bob-example", "https://example.com/a", predicate="works-at", added_by="claude-code")
    fact_sources.add_source(memory, "bob-example", "https://example.com/b", predicate="works-at", added_by="claude-code")
    assert len(_sources(memory)) == 5
    # the 9th for one predicate is refused an agent, in words; the person is never refused for size
    for i in range(3, 8):
        fact_sources.add_source(memory, "bob-example", f"https://example.com/w{i}", predicate="website",
                                added_by="claude-code")
    with pytest.raises(fact_sources.SourceCapReached, match="remove one that is no longer relevant"):
        fact_sources.add_source(memory, "bob-example", "https://example.com/w9", predicate="website",
                                added_by="claude-code")
    assert fact_sources.add_source(memory, "bob-example", "https://example.com/w9", predicate="website",
                                   added_by="user") is not None
    # the page-wide cap
    for i in range(40):
        try:
            fact_sources.add_source(memory, "bob-example", f"https://example.com/p{i}", predicate=f"fact-{i}",
                                    added_by="claude-code")
        except fact_sources.SourceCapReached:
            break
    assert len(_sources(memory)) == fact_sources.MAX_SOURCES
    with pytest.raises(fact_sources.SourceCapReached):
        fact_sources.add_source(memory, "bob-example", "https://example.com/one-more", predicate="other",
                                added_by="claude-code")


def test_rank_trusted_then_cicada_then_agent_and_owner_page_is_person_only():
    entries = [
        {"ref": "https://example.com/1", "predicate": "works-at", "added_by": "claude-code"},
        {"ref": "https://example.com/2", "predicate": "works-at", "added_by": "cicada"},
        {"ref": "https://example.com/3", "predicate": "works-at", "added_by": "claude-code", "accepted": True},
        {"ref": "https://example.com/4", "predicate": "works-at", "added_by": "user"},
        {"ref": "https://example.com/5", "predicate": "lives-in", "added_by": "user"},
        {"ref": "note", "predicate": "works-at", "added_by": "user", "only_me": True, "kind": "note"},
    ]
    assert [e["ref"][-1] for e in fact_sources.rank(entries, "works-at")] == ["4", "3", "2", "1"]
    assert [e["ref"][-1] for e in fact_sources.rank(entries, "works-at", person_only=True)] == ["4", "3"]
    assert fact_sources.rank(entries, None) == []
    # the check's targets use the same function
    targets = source_check.targets_for(entries, "works-at", person_only=False)
    assert [t.ref[-1] for t in targets] == ["4", "3", "2"]


def test_owns_source_matrix():
    own = {"ref": "r", "added_by": "claude-code"}
    assert fact_sources.owns_source(own, author="claude-code")
    assert not fact_sources.owns_source(own, author="codex")
    assert not fact_sources.owns_source({**own, "added_by": "user"}, author="user")
    assert not fact_sources.owns_source({**own, "accepted": True}, author="claude-code")
    assert not fact_sources.owns_source({**own, "only_me": True}, author="claude-code")
    assert not fact_sources.owns_source({**own, "added_by": "cicada"}, author="cicada")
    # a Sleep model's entry and the unidentified label own nothing
    assert not fact_sources.owns_source({**own, "added_by": "gpt-5.4-mini"}, author="claude-code")
    assert not fact_sources.owns_source({**own, "added_by": "agent"}, author="agent")
    remote_entry = {"ref": "r", "added_by": "claude-web", "origin": "remote:ab12cd34"}
    assert fact_sources.owns_source(remote_entry, author="claude-web", origin="remote:ab12cd34")
    assert not fact_sources.owns_source(remote_entry, author="claude-web", origin="remote:zzzzzzzz")
    assert not fact_sources.owns_source(remote_entry, author="claude-web")          # a local agent
    assert not fact_sources.owns_source(own, author="claude-web", origin="remote:ab12cd34")  # a remote app


# ---------- the writer ----------


def test_change_source_update_replace_remove(tmp_path):
    memory = _bank(tmp_path)
    added = fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="claude-code",
                                    added_at="2026-09-01")
    # in place
    r = fact_sources.change_source(memory, "bob-example", TEAM, "works-at", actor="claude-code", access="public")
    assert r.action == "updated" and _sources(memory)[0]["access"] == "public"
    # replace keeps credit and date, and is one entry
    r = fact_sources.change_source(memory, "bob-example", TEAM, "works-at", actor="claude-code",
                                   new_ref=PROFILE, new_predicate="profile")
    assert r.action == "replaced"
    (only,) = _sources(memory)
    assert (only["ref"], only["predicate"], only["added_by"], only["added_at"]) == (
        PROFILE, "profile", "claude-code", "2026-09-01") and added["ref"] == TEAM
    # not found / not yours write nothing
    before = (memory / "entities" / "bob-example.md").read_text()
    assert fact_sources.change_source(memory, "bob-example", "https://example.com/none", None,
                                      actor="claude-code").action == "not_found"
    assert fact_sources.change_source(memory, "bob-example", PROFILE, "profile", actor="codex",
                                      access="signed_in").action == "not_yours"
    assert (memory / "entities" / "bob-example.md").read_text() == before
    # a remove needs a reason from an agent, leaves a tombstone, drops the key with the last entry
    assert fact_sources.change_source(memory, "bob-example", PROFILE, "profile", actor="claude-code",
                                      action="remove").action == "refused"
    r = fact_sources.change_source(memory, "bob-example", PROFILE, "profile", actor="claude-code",
                                   action="remove", reason="the profile shows a new employer")
    fm = _fm(memory)
    assert r.action == "removed" and "sources" not in fm
    # the replace tombstoned the old key; the removal the new one, with its reason
    assert [(r["ref"], r.get("reason")) for r in fm["sources_removed"]] == [
        (TEAM, None), (PROFILE, "the profile shows a new employer")]


def test_the_person_may_change_any_entry_and_takes_an_agents(tmp_path):
    memory = _bank(tmp_path)
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="claude-code")
    r = fact_sources.change_source(memory, "bob-example", TEAM, "works-at", actor="user", accepted=True,
                                   access="signed_in")
    assert r.action == "updated" and _sources(memory)[0]["accepted"] is True
    # now it is the person's to keep: no agent may touch it
    assert fact_sources.change_source(memory, "bob-example", TEAM, "works-at", actor="claude-code",
                                      action="remove", reason="x").action == "not_yours"


def test_a_secret_in_a_ref_is_refused_never_stored_redacted(tmp_path):
    memory = _bank(tmp_path)
    secret = "https://example.com/x?token=abcdef0123456789abcdef0123456789abcd"
    with pytest.raises(fact_sources.InvalidSource, match="secret"):
        fact_sources.add_source(memory, "bob-example", secret, added_by="claude-code")
    assert _sources(memory) == []
    fact_sources.add_source(memory, "bob-example", TEAM, added_by="claude-code")
    r = fact_sources.change_source(memory, "bob-example", TEAM, None, actor="claude-code", new_ref=secret)
    assert r.action == "refused" and _sources(memory)[0]["ref"] == TEAM


def test_an_agent_url_loses_its_fragment(tmp_path):
    memory = _bank(tmp_path)
    fact_sources.add_source(memory, "bob-example", TEAM + "#team", added_by="claude-code")
    assert _sources(memory)[0]["ref"] == TEAM


# ---------- the tombstone ----------


def test_removal_tombstone_blocks_machine_writers_and_the_person_clears_it(tmp_path):
    memory = _bank(tmp_path)
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="website", added_by="claude-code")
    fact_sources.change_source(memory, "bob-example", TEAM, "website", actor="claude-code", action="remove",
                               reason="not his site")
    fm = _fm(memory)
    # a machine writer (Stage 1's proposal, the backfill, a cited link) is refused the key, and the same site
    for who in ("cicada", "gpt-5.4-mini", "agent"):
        with pytest.raises(fact_sources.SourceRemoved, match="not his site"):
            fact_sources.add_source(memory, "bob-example", TEAM, predicate="website", added_by=who)
    with pytest.raises(fact_sources.SourceRemoved):
        fact_sources.add_source(memory, "bob-example", "https://example.com/other-page", predicate="website",
                                added_by="cicada")
    assert fact_sources.is_tombstoned(fm, TEAM, "website")
    assert not fact_sources.is_tombstoned(fm, TEAM, "works-at"), "another fact is another key"
    # an agent's own removal does not block an agent (D6) ...
    assert fact_sources.add_source(memory, "bob-example", TEAM, predicate="website", added_by="codex",
                                   via_agent=True) is not None
    # ... but the person's does, for every agent, until the person adds it back
    fact_sources.change_source(memory, "bob-example", TEAM, "website", actor="user", action="remove")
    with pytest.raises(fact_sources.SourceRemoved, match="the person"):
        fact_sources.add_source(memory, "bob-example", TEAM, predicate="website", added_by="codex", via_agent=True)
    assert fact_sources.add_source(memory, "bob-example", TEAM, predicate="website", added_by="user") is not None
    assert "sources_removed" not in _fm(memory)


def test_tombstones_keep_the_newest_twenty(tmp_path):
    memory = _bank(tmp_path)
    for i in range(25):
        fact_sources.add_source(memory, "bob-example", f"https://example.com/{i}", predicate=f"f-{i}", added_by="claude-code")
        fact_sources.change_source(memory, "bob-example", f"https://example.com/{i}", f"f-{i}",
                                   actor="claude-code", action="remove", reason="gone")
    rows = _fm(memory)["sources_removed"]
    assert len(rows) == fact_sources.MAX_TOMBSTONES and rows[-1]["ref"] == "https://example.com/24"
    assert rows[0]["ref"] == "https://example.com/5"


def test_cited_link_attach_and_write_claim_sources_respect_a_tombstone(tmp_path):
    from test_extraction_source_attach import EP, LINK, _bank as _cited_bank, _run, _span

    line = f"bob-example moved to company-b; the team page {LINK} lists him."
    memory, text = _cited_bank(tmp_path, line)
    fact_sources.add_source(memory, "bob-example", LINK, predicate="works-at", added_by="claude-code")
    fact_sources.change_source(memory, "bob-example", LINK, "works-at", actor="user", action="remove")
    rel = {"source": "bob-example", "target": "company-b", "label": "works at", "evidence": [_span(text, line)]}
    _run(memory, [rel])
    assert _sources(memory) == [], "Stage 5.56's cited-link attach never puts back what was removed"
    assert "works-at" in (memory / "entities" / "bob-example.md").read_text(), "the claim beside it is still written"
    # cicada_write_claim(sources=) — the claim lands, the source is dropped
    from api.services import agentic_write

    result = agentic_write.write_claim(memory, "bob-example", "works-at", "company-b", observer="agent",
                                       authored_by="claude-code", sources=[LINK])
    assert result["claim_id"] and _sources(memory) == []


# ---------- entity links ----------


def test_source_entity_link_validation_and_never_creates_a_page(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "media-alpha-profile", type="media")
    _entity(memory, "old-page", status="dropped")
    ok = fact_sources.add_source(memory, "bob-example", PROFILE, predicate="profile", entity="media-alpha-profile")
    assert ok["entity"] == "media-alpha-profile"
    for bad, why in (("nobody-page", "no page"), ("bob-example", "itself"), ("old-page", "dropped")):
        with pytest.raises(fact_sources.InvalidSource):
            fact_sources.add_source(memory, "bob-example", f"https://example.com/{bad}", entity=bad)
    assert not (memory / "entities" / "nobody-page.md").exists(), "a source never mints a page"
    # a stale id reads as no link
    (memory / "entities" / "media-alpha-profile.md").unlink()
    assert fact_sources.linked_entity(memory, _sources(memory)[0], self_id="bob-example") is None
    # link and unlink through the writer
    _entity(memory, "alpha-page")
    fact_sources.change_source(memory, "bob-example", PROFILE, "profile", actor="user", entity="alpha-page")
    assert _sources(memory)[0]["entity"] == "alpha-page"
    fact_sources.change_source(memory, "bob-example", PROFILE, "profile", actor="user", entity=None)
    assert "entity" not in _sources(memory)[0]


def test_an_agent_with_a_bad_link_still_lands_the_source_and_is_told(server):
    srv, memory = server
    out = srv.handle_add_source("bob-example", PROFILE, "profile", None, None, "nobody-page")
    assert out.startswith("Added ") and "link to a page was left out" in out
    assert "entity" not in _sources(memory)[0]
    _entity(memory, "media-alpha-profile", type="media")
    assert srv.handle_add_source("bob-example", TEAM, "works-at", None, None, "media-alpha-profile").startswith("Added ")
    assert [s.get("entity") for s in _sources(memory)] == [None, "media-alpha-profile"]


def test_entity_link_exact_match_backfill(tmp_path):
    from api.services import media_ingestor

    memory = _bank(tmp_path)
    _entity(memory, "media-alpha-profile", type="media")
    _entity(memory, "notes-folder", type="directory", path="~/notes/alpha")
    (memory / "sources").mkdir()
    (memory / "sources" / "url_index.json").write_text(json.dumps({
        media_ingestor.url_hash(PROFILE): {"media_entity_id": "media-alpha-profile", "url": PROFILE}}))
    other = "https://example.com/in/bobby"
    for ref, kind in ((PROFILE, "url"), (PROFILE + "/", "url"), (other, "url"), ("~/notes/alpha", "path"),
                      ("~/notes/alpha2", "path")):
        fact_sources.add_source(memory, "bob-example", ref, kind=kind, predicate=f"p-{len(_sources(memory))}",
                                added_by="user")
    # a link somebody set is never overwritten
    _entity(memory, "elsewhere")
    fact_sources.change_source(memory, "bob-example", PROFILE + "/", "p-1", actor="user", entity="elsewhere")
    report = source_links.backfill(memory)
    links = {s["ref"]: s.get("entity") for s in _sources(memory)}
    assert links[PROFILE] == "media-alpha-profile"           # a saved page's own URL
    assert links["~/notes/alpha"] == "notes-folder"          # a directory page's own path
    assert links[other] is None and links["~/notes/alpha2"] is None, "near matches never link"
    assert links[PROFILE + "/"] == "elsewhere", "an existing link is never overwritten"
    assert report.linked == 2 and report.paths == ["entities/bob-example.md"]
    assert source_links.backfill(memory).linked == 0


def test_link_sources_route_commits_alone_as_cicada(client):
    from api.services import media_ingestor

    c, memory = client
    _entity(memory, "media-alpha-profile", type="media")
    (memory / "sources").mkdir()
    (memory / "sources" / "url_index.json").write_text(json.dumps({
        media_ingestor.url_hash(PROFILE): {"media_entity_id": "media-alpha-profile", "url": PROFILE}}))
    fact_sources.add_source(memory, "bob-example", PROFILE, predicate="profile", added_by="user")
    subprocess.run(["git", "-C", str(memory), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "seed"], check=True, capture_output=True)
    body = c.post("/maintenance/link-sources").json()
    assert body == {"linked": 1, "pages": 1}
    msg = _git(memory, "log", "-1", "--format=%B")
    assert msg.startswith("Source links ") and "Cicada-Author: cicada" in msg and "Cicada-Engine" not in msg
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == ["entities/bob-example.md"]


# ---------- the graph ----------


def test_graph_source_edges(tmp_path):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    _entity(memory, "bob-example", type="person",
            sources=[{"ref": PROFILE, "kind": "url", "predicate": "profile", "added_by": "user", "entity": "media-p"},
                     {"ref": TEAM, "kind": "url", "predicate": "works-at", "added_by": "user", "entity": "gone-page"},
                     {"ref": "https://example.com/x", "kind": "url", "added_by": "user", "entity": "media-p"},
                     {"ref": "https://example.com/y", "kind": "url", "added_by": "user", "entity": "media-p"}])
    _entity(memory, "media-p", type="media")
    (memory / "graph_edges.yaml").write_text("edges: []\n")
    before = graph_builder.build_graph(memory)
    links = {(l.source, l.target, l.label) for l in before.links}
    assert ("bob-example", "media-p", "profile") in links
    assert ("bob-example", "media-p", "source") in links
    assert not any(l.target == "gone-page" for l in before.links), "a dangling link is dropped"
    assert sum(1 for l in before.links if l.label == "source") == 1, "no duplicate pair + label"
    node = next(n for n in before.nodes if n.id == "bob-example")
    assert node.degree == 0, "source edges are derived at read and never change a node"
    assert {l.kind for l in before.links if l.label in ("profile", "source")} == {"source"}, "a source edge says so"
    from api.routers.graph import NODE_SHAPE

    assert NODE_SHAPE.endswith("+source-links")


# ---------- merge ----------


def test_entity_merge_carries_sources_and_repoints_entity(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "bob-e", type="person",
            sources=[{"ref": TEAM, "kind": "url", "predicate": "works-at", "added_by": "user", "entity": "alpha-project"},
                     {"ref": PROFILE, "kind": "url", "predicate": "profile", "added_by": "user", "entity": "bob-e"}],
            sources_removed=[{"ref": "https://example.com/old", "by": "user", "at": "2026-09-01"}])
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="claude-code")
    fact_sources.add_source(memory, "bob-example", "https://example.com/other", added_by="claude-code")
    _entity(memory, "carol-example", type="person",
            sources=[{"ref": "https://example.com/c", "kind": "url", "added_by": "user", "entity": "bob-e"}])
    entity_merge.merge_entities(memory, "bob-e", "bob-example")
    rows = {(s["ref"], s.get("predicate")): s for s in _sources(memory)}
    assert len(rows) == 3
    assert rows[(TEAM, "works-at")]["added_by"] == "claude-code", "the winner's entry wins on a key"
    assert rows[(PROFILE, "profile")].get("entity") is None, "a link to the page itself is dropped"
    assert _fm(memory)["sources_removed"][0]["ref"] == "https://example.com/old"
    assert _sources(memory, "carol-example")[0]["entity"] == "bob-example", "another page's link follows the merge"


# ---------- MCP ----------


def test_change_source_tool_commits_alone_under_the_harness_and_keeps_ref_out_of_the_manifest(server):
    srv, memory = server
    srv.handle_add_source("bob-example", TEAM, "works-at")
    (memory / "notes.md").write_text("an unrelated dirty file\n")
    out = srv.handle_change_source("bob-example", TEAM, "works-at", "remove", "the page shows a new employer")
    assert out.startswith("Removed ") and "cicada_" not in out
    body = _git(memory, "log", "-1", "--format=%B")
    assert body.startswith("Agent write ") and "entities/bob-example.md: updated (trigger: mcp/claude-code)" in body
    assert "Cicada-Author: claude-code" in body and "Cicada-Engine" not in body
    assert TEAM not in body and "new employer" not in body, "the ref and the reason are in the diff, not the manifest"
    assert "new employer" in _git(memory, "show", "HEAD")
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == ["entities/bob-example.md"]
    assert "notes.md" in _git(memory, "status", "--porcelain")
    assert _sources(memory) == [] and _fm(memory)["sources_removed"][0]["by"] == "claude-code"


def test_change_source_tool_refusals(server, monkeypatch):
    srv, memory = server
    srv.handle_add_source("bob-example", TEAM, "works-at")
    head = _git(memory, "rev-parse", "HEAD")
    page = (memory / "entities" / "bob-example.md").read_text()

    def refused(out):
        assert out.startswith(("Nothing changed", "No page named")), out
        assert (memory / "entities" / "bob-example.md").read_text() == page and _git(memory, "rev-parse", "HEAD") == head

    refused(srv.handle_change_source("bob-example", TEAM, "works-at", "remove", None))            # no reason
    refused(srv.handle_change_source("bob-example", TEAM, "works-at", "delete", "x"))            # bad action
    refused(srv.handle_change_source("nobody-example", TEAM, "works-at", "remove", "x"))         # no page
    refused(srv.handle_change_source("bob-example", "https://example.com/none", "works-at", "remove", "x"))
    refused(srv.handle_change_source("bob-example", TEAM, "lives-in", "remove", "x"))            # key is the pair
    refused(srv.handle_change_source("bob-example", TEAM, "works-at", "update", None, "https://example.com/x?token=abcdef0123456789abcdef0123456789abcd"))
    # someone else's: the person's, a taken one
    fact_sources.add_source(memory, "bob-example", PROFILE, predicate="profile", added_by="user")
    page = (memory / "entities" / "bob-example.md").read_text(); head = _git(memory, "rev-parse", "HEAD")
    out = srv.handle_change_source("bob-example", PROFILE, "profile", "remove", "x")
    assert "was not added by this agent" in out
    assert (memory / "entities" / "bob-example.md").read_text() == page
    # Sleep running
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: True)
    assert "consolidating memory right now" in srv.handle_change_source("bob-example", TEAM, "works-at", "remove", "x")
    assert len(_sources(memory)) == 2


def test_change_source_is_refused_in_a_demo_bank(server):
    srv, memory = server
    srv.handle_add_source("bob-example", TEAM, "works-at")
    (memory / "_bank.yaml").write_text("kind: demo\n")
    from api.services import demo_guard

    assert demo_guard.is_demo(memory)
    assert srv.handle_change_source("bob-example", TEAM, "works-at", "remove", "x") == demo_guard.AGENT_REFUSAL
    assert len(_sources(memory)) == 1


def test_cicada_add_source_says_who_removed_it_and_refuses_the_persons_removal(server):
    srv, memory = server
    srv.handle_add_source("bob-example", TEAM, "works-at")
    srv.handle_change_source("bob-example", TEAM, "works-at", "remove", "wrong company")
    out = srv.handle_add_source("bob-example", TEAM, "works-at")
    assert out.startswith("Added ") and "It was put back: that source was removed" in out and "wrong company" in out
    fact_sources.change_source(memory, "bob-example", TEAM, "works-at", actor="user", action="remove")
    out = srv.handle_add_source("bob-example", TEAM, "works-at")
    assert out.startswith("Nothing added") and "removed on" in out and "the person" in out
    assert _sources(memory) == []


def test_remote_owns_only_its_own_entries_and_never_a_path(remote):
    runtime, memory = remote
    a, b = _connector("aaaaaaaa"), _connector("bbbbbbbb")
    text, status = runtime.call(a, "cicada_add_source", {"subject": "bob-example", "ref": TEAM, "predicate": "works-at"})
    assert status == "ok" and _sources(memory)[0]["origin"] == "remote:aaaaaaaa"
    text, _ = runtime.call(b, "cicada_change_source", {"subject": "bob-example", "ref": TEAM, "predicate": "works-at",
                                                       "action": "remove", "reason": "x"})
    assert "was not added by this agent" in text and len(_sources(memory)) == 1
    text, _ = runtime.call(a, "cicada_change_source", {"subject": "bob-example", "ref": TEAM, "predicate": "works-at",
                                                       "action": "update", "new_ref": "~/Documents/cv.pdf"})
    assert "can't name a file or folder" in text and _sources(memory)[0]["ref"] == TEAM
    text, _ = runtime.call(a, "cicada_change_source", {"subject": "bob-example", "ref": TEAM, "predicate": "works-at",
                                                       "action": "remove", "reason": "moved on"})
    assert text.startswith("Removed ") and _sources(memory) == []
    body = _git(memory, "log", "-1", "--format=%B")
    assert body.startswith("Remote write ") and "trigger: remote/claude-web" in body


def test_the_tool_is_record_scoped_a_write_and_the_remote_schema_names_no_other_tool():
    assert catalog.TOOL_SCOPE["cicada_change_source"] == "record"
    assert "cicada_change_source" in catalog.WRITE_TOOLS
    assert "cicada_change_source" in catalog.tool_names_for({"record"})
    assert "cicada_change_source" not in catalog.tool_names_for({"read"})
    d = remote_tools.REMOTE_TOOLS["cicada_change_source"]
    assert "cicada_" not in d["description"] and "local" not in d["inputSchema"]["properties"]["access"]["enum"]
    assert d["inputSchema"]["required"] == ["subject", "ref", "action"]
    stdio = {t["name"]: t for t in stdio_server().TOOLS}
    assert stdio["cicada_change_source"]["inputSchema"]["required"] == ["subject", "ref", "action"]
    assert set(stdio["cicada_add_source"]["inputSchema"]["properties"]) >= {"entity"}


def test_source_write_telemetry_is_ids_and_enums_only(server, monkeypatch):
    srv, memory = server
    rows = []
    from api.services import telemetry

    monkeypatch.setattr(telemetry, "record", lambda ev: rows.append(ev))
    srv.handle_add_source("bob-example", TEAM, "works-at")
    srv.handle_change_source("bob-example", TEAM, "works-at", "remove", "the page shows a new employer")
    assert [r.refs["action"] for r in rows] == ["source_added", "source_removed"]
    blob = json.dumps([r.refs for r in rows], default=str)
    assert TEAM not in blob and "employer" not in blob and "example.com" not in blob


# ---------- REST ----------


def test_change_route_shapes_and_commits_as_the_person(client):
    c, memory = client
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="claude-code")
    _entity(memory, "alpha-page")
    subprocess.run(["git", "-C", str(memory), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "seed"], check=True, capture_output=True)
    url = "/entities/bob-example/sources/change"
    assert c.post("/entities/nobody/sources/change", json={"ref": TEAM}).status_code == 404
    assert c.post(url, json={"ref": "https://example.com/none"}).status_code == 404
    assert c.post(url, json={"ref": TEAM, "predicate": "works-at", "entity": "nobody-page"}).status_code == 400
    r = c.post(url, json={"ref": TEAM, "predicate": "works-at", "entity": "alpha-page", "accepted": True})
    assert r.status_code == 200
    (row,) = r.json()["sources"]
    assert row["entity"] == "alpha-page" and row["accepted"] is True
    msg = _git(memory, "log", "-1", "--format=%B")
    assert "Cicada-Author: user" in msg and "trigger: user/companion_app" in msg
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == ["entities/bob-example.md"]
    # an explicit null clears the link; an absent key leaves it
    assert c.post(url, json={"ref": TEAM, "predicate": "works-at", "access": "public"}).json()["sources"][0]["entity"] == "alpha-page"
    assert c.post(url, json={"ref": TEAM, "predicate": "works-at", "entity": None}).json()["sources"][0]["entity"] is None
    # the person removes any entry; it is remembered by `user`
    r = c.post(url, json={"ref": TEAM, "predicate": "works-at", "action": "remove"})
    assert r.json()["sources"] == []
    assert _fm(memory)["sources_removed"][0]["by"] == "user"
    assert "Remove fact source" in _git(memory, "log", "-1", "--format=%B")
    # the person adds it back: the tombstone clears
    assert c.post("/entities/bob-example/sources", json={"ref": TEAM, "predicate": "works-at"}).status_code == 200
    assert "sources_removed" not in _fm(memory)


def test_a_stale_link_is_served_as_no_link(client):
    c, memory = client
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="user")
    page = memory / "entities" / "bob-example.md"
    fm = markdown_parser.parse(page).frontmatter
    fm["sources"][0]["entity"] = "gone-page"
    markdown_parser.write(page, fm, markdown_parser.parse(page).body)
    assert c.get("/entities/bob-example/sources").json()["sources"][0]["entity"] is None


def test_the_index_delete_route_still_works_and_tombstones(client):
    c, memory = client
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="claude-code")
    assert c.delete("/entities/bob-example/sources/0").json()["sources"] == []
    assert _fm(memory)["sources_removed"][0] == {"ref": TEAM, "predicate": "works-at", "by": "user",
                                                 "at": _fm(memory)["sources_removed"][0]["at"]}
    with pytest.raises(fact_sources.SourceRemoved):
        fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="cicada")


def test_the_person_adds_with_a_link(client):
    c, memory = client
    _entity(memory, "alpha-page")
    r = c.post("/entities/bob-example/sources", json={"ref": PROFILE, "predicate": "profile", "entity": "alpha-page"})
    assert r.json()["sources"][0]["entity"] == "alpha-page"
    assert c.post("/entities/bob-example/sources", json={"ref": TEAM, "entity": "bob-example"}).status_code == 400


# ---------- the primer (R12) ----------


def test_the_primer_names_the_source_tools_and_every_argument_is_in_the_schema():
    from api.services import handshake

    schemas = {t["name"]: set(t["inputSchema"].get("properties", {})) for t in stdio_server().TOOLS}
    for variant in handshake.VARIANTS:
        text = handshake.build(None, variant=variant, bank="memory")
        assert "`cicada_add_source` for one the person names; `cicada_change_source` to fix or drop your own" in text
        assert {"subject", "ref", "predicate", "action", "reason"} <= schemas["cicada_change_source"]
        assert {"subject", "ref", "predicate"} <= schemas["cicada_add_source"]
        assert len(text) // 4 <= handshake.MAX_TOKENS
    from itertools import combinations

    for n in range(1, len(catalog.SCOPES) + 1):
        for scopes in combinations(catalog.SCOPES, n):
            tools = frozenset(catalog.tool_names_for(set(scopes)))
            text = handshake.build_remote(None, tools=tools, bank="memory")
            for name in ("cicada_add_source", "cicada_change_source"):
                assert (name in text) == (name in tools and "cicada_add_source" in tools), (scopes, name)
            if "cicada_change_source" in text:
                assert "cicada_add_source" in tools and "cicada_change_source" in tools


def test_the_new_tools_name_no_provider():
    import re

    banned = re.compile(r"ollama|claude|chatgpt|haiku|\bopus\b|sonnet|gpt-|gemini|openrouter|anthropic|openai|codex",
                        re.IGNORECASE)
    stdio = {t["name"]: t for t in stdio_server().TOOLS}["cicada_change_source"]
    texts = [stdio["description"], remote_tools.REMOTE_TOOLS["cicada_change_source"]["description"]]
    for tool in (stdio, remote_tools.REMOTE_TOOLS["cicada_change_source"]):
        texts += [p.get("description", "") for p in tool["inputSchema"]["properties"].values()]
    assert not [t for t in texts if banned.search(t)]


# ---------- the Sleep tail ----------


def test_the_tail_step_links_in_its_own_cicada_commit_and_skips_a_dirty_page(tmp_path):
    import asyncio

    from api.services import media_ingestor, sleep_cycle

    memory = _bank(tmp_path)
    _entity(memory, "media-alpha-profile", type="media")
    (memory / "sources").mkdir()
    (memory / "sources" / "url_index.json").write_text(json.dumps({
        media_ingestor.url_hash(PROFILE): {"media_entity_id": "media-alpha-profile", "url": PROFILE}}))
    fact_sources.add_source(memory, "bob-example", PROFILE, predicate="profile", added_by="user")
    fact_sources.add_source(memory, "alpha-project", PROFILE, predicate="profile", added_by="user")
    subprocess.run(["git", "-C", str(memory), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "seed"], check=True, capture_output=True)
    page = memory / "entities" / "alpha-project.md"
    page.write_text(page.read_text() + "\na person's uncommitted edit\n")
    asyncio.run(sleep_cycle._link_sources_safely(memory))
    msg = _git(memory, "log", "-1", "--format=%B")
    assert msg.startswith("Source links ") and "trigger: sleep/source-links" in msg
    assert "Cicada-Author: cicada" in msg and "Cicada-Engine" not in msg
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == ["entities/bob-example.md"]
    assert _sources(memory, "bob-example")[0]["entity"] == "media-alpha-profile"
    assert "entity" not in _sources(memory, "alpha-project")[0], "a page dirty before the run is left alone"


# ---------- the review's fixes ----------


def test_an_unlink_stays_unlinked_through_the_backfill_until_a_later_link(tmp_path):
    from api.services import media_ingestor

    memory = _bank(tmp_path)
    _entity(memory, "media-alpha-profile", type="media")
    (memory / "sources").mkdir()
    (memory / "sources" / "url_index.json").write_text(json.dumps({
        media_ingestor.url_hash(PROFILE): {"media_entity_id": "media-alpha-profile", "url": PROFILE}}))
    fact_sources.add_source(memory, "bob-example", PROFILE, predicate="profile", added_by="user")
    assert source_links.backfill(memory).linked == 1
    fact_sources.change_source(memory, "bob-example", PROFILE, "profile", actor="user", entity=None)
    assert _sources(memory)[0].get("entity_unlinked") is True
    assert source_links.backfill(memory).linked == 0 and "entity" not in _sources(memory)[0]
    fact_sources.change_source(memory, "bob-example", PROFILE, "profile", actor="user", entity="media-alpha-profile")
    row = _sources(memory)[0]
    assert row["entity"] == "media-alpha-profile" and "entity_unlinked" not in row


def test_a_replace_tombstones_the_old_key_so_a_cited_link_cannot_bring_it_back(tmp_path):
    from test_extraction_source_attach import LINK, _bank as _cited_bank, _run, _span

    line = f"bob-example moved to company-b; the team page {LINK} lists him."
    memory, text = _cited_bank(tmp_path, line)
    fact_sources.add_source(memory, "bob-example", LINK, predicate="works-at", added_by="claude-code")
    fact_sources.change_source(memory, "bob-example", LINK, "works-at", actor="claude-code",
                               new_ref="https://example.com/company-b/people")
    assert fact_sources.is_tombstoned(_fm(memory, "bob-example"), LINK, "works-at")
    rel = {"source": "bob-example", "target": "company-b", "label": "works at", "evidence": [_span(text, line)]}
    _run(memory, [rel])
    assert [s["ref"] for s in _sources(memory)] == ["https://example.com/company-b/people"]


def test_the_persons_source_routes_wait_for_sleep(client, monkeypatch):
    from api.services import sleep_cycle

    c, memory = client
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="user")
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    for r in (c.post("/entities/bob-example/sources", json={"ref": PROFILE}),
              c.post("/entities/bob-example/sources/change", json={"ref": TEAM, "predicate": "works-at",
                                                                 "action": "remove"}),
              c.delete("/entities/bob-example/sources/0")):
        assert r.status_code == 409 and "Sleep is updating your memory" in r.json()["detail"]
    assert len(_sources(memory)) == 1


def test_a_merge_keeps_the_persons_entries_first_and_honours_the_caps(tmp_path):
    memory = _bank(tmp_path)
    winner = [{"ref": f"https://example.com/w{i}", "kind": "url", "predicate": "website", "added_by": "claude-code"}
              for i in range(8)]
    loser = [{"ref": f"https://example.com/l{i}", "kind": "url", "predicate": "website", "added_by": "user"}
             for i in range(3)] + [{"ref": "https://example.com/x", "kind": "url", "predicate": "website",
                                    "added_by": "claude-code"}]
    _entity(memory, "bob-e", type="person", sources=loser)
    page = memory / "entities" / "bob-example.md"
    fm = markdown_parser.parse(page)
    markdown_parser.write(page, {**fm.frontmatter, "sources": winner}, fm.body)
    entity_merge.merge_entities(memory, "bob-e", "bob-example")
    rows = _sources(memory)
    assert all(any(r["ref"].endswith(f"/l{i}") for r in rows) for i in range(3)), "the person's entries survive"
    assert len(rows) == fact_sources.MAX_PER_PREDICATE and sum(1 for r in rows if r["added_by"] == "user") == 3


def test_source_writes_do_not_count_as_claim_writes(monkeypatch):
    import asyncio
    from datetime import date

    from api.services import consumption_stats, telemetry

    events = [telemetry.UsageEvent(kind="agentic_write", refs={"action": a})
              for a in ("written", "source_added", "source_changed", "source_removed")]

    async def no_days(_):
        return {}

    monkeypatch.setattr(consumption_stats, "_events_in", lambda r, t: events)
    monkeypatch.setattr(consumption_stats, "memory_write_days", no_days)
    out = asyncio.run(consumption_stats.summary(Path("."), range_="all", today=date(2026, 9, 30)))
    assert out["agentic_writes"] == 1


def test_add_source_waits_for_sleep_and_writes_nothing(server, monkeypatch):
    srv, memory = server
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: True)
    head = _git(memory, "rev-parse", "HEAD")
    out = srv.handle_add_source("bob-example", TEAM, "works-at")
    assert out.startswith("Nothing added") and "consolidating memory" in out
    assert _sources(memory) == [] and _git(memory, "rev-parse", "HEAD") == head
