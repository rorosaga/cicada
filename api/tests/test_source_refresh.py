"""G61, ruling 26 — tracked sources keep facts current: dated re-checks, dead sites, and the newest evidence wins.

Owner, 2026-10-14: "If I have the LinkedIn of a person … and I'm tracking their positions … being able to update these
things through consolidation would be nice", and the same evening: "it can override something I said if it has
evidence, there is no problem with that." Synthetic bank only (bob-example, team-labs.io, beta-example); the network is
a fixture; LinkedIn appears only as a URL Cicada must never fetch."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from _reading_fixtures import enable, reading  # noqa: F401 — `reading` is a fixture
from api import config, main
from api.services import (bank_index, fact_sources, hook_recall, link_enrichment, markdown_parser, page_sources,
                          reading_hosts, recall_text, source_refresh)
from api.services.claims import Claim, parse_claims, write_claims

TEAM = "https://team-labs.io/people/bob"
PROFILE = "https://www.linkedin.com/in/bob-example"
TODAY = date.today()
T = TODAY.isoformat()

PAGE_WITH_ROLE = """<html><head><title>Bob Example - Team Labs</title>
<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Person", "name": "Bob Example",
 "jobTitle": "Staff Engineer", "worksFor": {"@type": "Organization", "name": "Team Labs"}}</script>
</head><body><h1>Bob Example</h1><p>Bob builds the indexing service at Team Labs.</p></body></html>"""


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True, text=True).stdout


def _commit(memory):
    _git(memory, "add", ".")
    _git(memory, "commit", "-qm", "seed")
    bank_index.invalidate()


def _claims(memory, eid="bob-example"):
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)


def _seed_claim(memory, *, obj="Engineer", predicate="role", eid="bob-example", **kw):
    """A belief already on the page. Default: extracted from a conversation said on 2026-09-01."""
    path = memory / "entities" / f"{eid}.md"
    parsed = markdown_parser.parse(path)
    claims = parse_claims(parsed.body)
    fields = dict(id=f"clm_{eid}_{predicate}_seed{len(claims)}", text=f"Bob Example {predicate} {obj}",
                  subject=eid, predicate=predicate, object=obj, object_kind="literal", valid_from="2026-09-01",
                  recorded_at="2026-09-02", source_episodes=["ep_2026-09-01_001"])
    fields.update(kw)
    claim = Claim(**fields)
    markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims + [claim]))
    return claim.id


def _single_valued(memory, predicate="role"):
    """The bank's vocabulary says ``predicate`` holds ONE current value (only then may a re-check close an older one)."""
    import yaml

    path = memory / "_predicates.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["single_valued"] = sorted(set(data.get("single_valued") or []) | {predicate})
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _source(memory, ref=TEAM, predicate="role", **extra):
    fact_sources.add_source(memory, "bob-example", ref, predicate=predicate, added_by="user", kind="url")
    if extra:
        path = memory / "entities" / "bob-example.md"
        parsed = markdown_parser.parse(path)
        for s in parsed.frontmatter["sources"]:
            if s["ref"] == ref:
                s.update(extra)
        markdown_parser.write(path, parsed.frontmatter, parsed.body)
    bank_index.invalidate()


def _stream(html=PAGE_WITH_ROLE, status="ok", final=TEAM, calls=None):
    async def fn(url):
        if calls is not None:
            calls.append(url)
        return (status, html if status == "ok" else "", final if status == "ok" else "")
    return fn


def _read(value, captured, *, quote=None, ended=None):
    return source_refresh.Observation("read", values=[value] if value else [], ended=ended or [],
                                      quotes=[quote or f"Current role: {value}"], captured_on=captured)


def _apply(memory, obs, ref=TEAM, predicate="role", today=TODAY):
    return source_refresh.apply(memory, entity_id="bob-example", ref=ref, predicate=predicate, obs=obs,
                                checker_kind="agent", label="claude-code", author="claude-code",
                                trigger="mcp/claude-code", session_id="ses_fixed", today=today)


@pytest.fixture
def no_network(monkeypatch):
    """Any real fetch or model call fails the test."""
    async def boom(*a, **k):
        raise AssertionError("the backend must not fetch here")

    monkeypatch.setattr(link_enrichment, "_stream_html", boom)
    import litellm

    def spend(*a, **k):
        raise AssertionError("no model may run here")

    monkeypatch.setattr(litellm, "completion", spend)
    monkeypatch.setattr(litellm, "acompletion", spend)


# ---------- the due list costs nothing ----------


def test_the_due_list_is_a_frontmatter_read_with_no_fetch_and_no_model(reading, no_network):
    server, memory = reading
    _source(memory)                                                        # never checked -> due
    _source(memory, PROFILE, "works-at")                                   # walled -> the person's agent
    fact_sources.add_source(memory, "bob-example", "https://bob-blog.example.org", predicate="lives-in",
                            added_by="claude-code", kind="url")            # an agent's proposal: not tracked
    _source(memory, "https://bob-example.dev/cv", "studied-at",
            refresh={"at": (TODAY - timedelta(days=3)).isoformat(), "outcome": "read"})   # checked 3 days ago
    _source(memory, "https://old-team.example.net", "employed-by", recheck_days=7,
            refresh={"at": (TODAY - timedelta(days=8)).isoformat(), "outcome": "read"})  # its own 7-day cadence
    items = source_refresh.due(memory, today=TODAY)
    got = {(d.ref, d.checker, d.reason) for d in items}
    assert got == {(TEAM, "cicada", "never"), (PROFILE, "agent", "never"),
                   ("https://old-team.example.net", "cicada", "cadence")}
    assert source_refresh.tracked_count(memory)["tracked"] == 4


# ---------- a public re-check: a new dated fact, the old one closed ----------


def test_a_public_recheck_writes_a_dated_claim_and_closes_the_old_one(reading):
    server, memory = reading
    _single_valued(memory)
    old = _seed_claim(memory)
    _source(memory)
    _commit(memory)
    calls: list[str] = []
    report = asyncio.run(source_refresh.run_tail(memory, stream_fn=_stream(calls=calls), today=TODAY))
    assert calls == [TEAM]
    claims = {c.id: c for c in _claims(memory)}
    new = next(c for c in claims.values() if c.origin == source_refresh.ORIGIN)
    assert (new.object, new.valid_from, new.valid_to, new.observer, new.source_trust) == (
        "Staff Engineer", T, None, "cicada", "external")
    assert f"updated {T} from team-labs.io" in new.text and "was Engineer" in new.text
    assert claims[old].valid_to == T and claims[old].superseded_by == new.id, "closed, kept as history"
    # Evidence: a span into the re-check's own episode, the page's words (never the person's).
    (ev,) = new.evidence
    assert ev.kind == "page" and ev.is_span() and ev.episode == new.source_episodes[0]
    ep = markdown_parser.parse(memory / "episodes" / f"{ev.episode}.md")
    assert ep.frontmatter["source"] == "source-refresh" and ep.frontmatter["processed"] is True
    assert ep.body[ev.start:ev.end] == "jobTitle: Staff Engineer"
    st = fact_sources.list_sources(memory, "bob-example")[0]["refresh"]
    assert st["at"] == st["good"] == T and st["episode"] == ev.episode
    # The page says what changed, from where, and when.
    ov = page_sources.overview(memory, memory / "entities" / "bob-example.md")
    (u,) = ov.updates
    assert (u.value, u.was, u.at, u.site, u.current) == ("Staff Engineer", "Engineer", T, "team-labs.io",
                                                         True)
    # One `cicada` commit, a manifest line per file, no engine trailer.
    asyncio.run(source_refresh.git_service.commit_paths(
        memory, source_refresh.commit_message(report, TODAY), report.paths))
    msg = _git(memory, "log", "-1", "--format=%B")
    assert msg.startswith(f"Source refresh {T}") and "Cicada-Author: cicada" in msg
    assert "trigger: sleep/source-refresh" in msg and "Cicada-Engine" not in msg
    # Re-run the same day: the source is not due again, nothing is fetched.
    calls.clear()
    asyncio.run(source_refresh.run_tail(memory, stream_fn=_stream(calls=calls), today=TODAY))
    assert calls == []


def test_a_page_stating_the_same_value_confirms_and_writes_no_claim(reading):
    server, memory = reading
    _seed_claim(memory, obj="Staff Engineer")
    _source(memory)
    before = len(_claims(memory))
    report = asyncio.run(source_refresh.run_tail(memory, stream_fn=_stream(), today=TODAY))
    assert report.counts.get("confirmed") == 1 and len(_claims(memory)) == before


def test_a_node_about_someone_else_is_not_read_as_this_pages_fact(reading):
    server, memory = reading
    _source(memory)
    other = PAGE_WITH_ROLE.replace('"name": "Bob Example"', '"name": "Carol Example"')
    report = asyncio.run(source_refresh.run_tail(memory, stream_fn=_stream(html=other), today=TODAY))
    assert report.counts.get("checked") == 1 and not [c for c in _claims(memory) if c.origin == "source-refresh"]


# ---------- the newest evidence wins, even over the person's own words ----------


def test_a_newer_recheck_supersedes_the_persons_older_statement(reading):
    server, memory = reading
    _single_valued(memory)
    mine = _seed_claim(memory, source_episodes=[], origin="manual_edit", source_trust="user_stated",
                       observer="owner-example", recorded_at=(TODAY - timedelta(days=13)).isoformat(),
                       valid_from=(TODAY - timedelta(days=13)).isoformat())
    _source(memory)
    applied = _apply(memory, _read("Staff Engineer", TODAY))
    assert applied.action == "updated"
    claims = {c.id: c for c in _claims(memory)}
    assert claims[mine].valid_to == T, "the person's statement stays as history, closed"
    (new,) = [c for c in claims.values() if c.origin == source_refresh.ORIGIN]
    assert new.valid_to is None and claims[mine].superseded_by == new.id
    assert not list((memory / "inbox").glob("inbox-0[1-9]*.md")), "a clear order asks nothing"


def test_a_statement_dated_after_the_capture_stands(reading):
    server, memory = reading
    _single_valued(memory)
    mine = _seed_claim(memory, source_episodes=[], origin="manual_edit", source_trust="user_stated",
                       recorded_at=(TODAY + timedelta(days=2)).isoformat(),
                       valid_from=(TODAY + timedelta(days=2)).isoformat())
    _source(memory)
    applied = _apply(memory, _read("Staff Engineer", TODAY), today=TODAY + timedelta(days=3))
    assert applied.action == "kept"
    claims = _claims(memory)
    assert [c.id for c in claims if c.valid_to is None] == [mine]
    assert not [c for c in claims if c.origin == source_refresh.ORIGIN], "the page gains nothing; the episode keeps it"
    assert applied.episode_id and (memory / "episodes" / f"{applied.episode_id}.md").exists()


def test_a_same_day_clash_makes_exactly_one_inbox_question_with_both_dates(reading):
    server, memory = reading
    _single_valued(memory)
    mine = _seed_claim(memory, source_episodes=[], origin="manual_edit", source_trust="user_stated",
                       recorded_at=T, valid_from=T)
    _source(memory)
    first = _apply(memory, _read("Staff Engineer", TODAY))
    assert first.action == "asked" and first.item
    item = markdown_parser.parse(memory / first.item)
    fm = item.frontmatter
    assert fm["kind"] == "divergence" and fm["existing_claim_id"] == mine and fm["trigger"] == source_refresh.TRIGGER
    assert T in fm["options"][0] and T in fm["options"][1]
    assert "Engineer" in item.body and "Staff Engineer" in item.body and "team-labs.io" in item.body
    claims = {c.id: c for c in _claims(memory)}
    assert claims[mine].valid_to is None, "nothing closes on a clash"
    # The same reading again (another agent, the same day) adds no second question.
    again = _apply(memory, _read("Staff Engineer", TODAY, quote="Role: Staff Engineer"))
    assert again.item is None
    pending = [p for p in (memory / "inbox").glob("inbox-*.md")
               if markdown_parser.parse(p).frontmatter.get("trigger") == source_refresh.TRIGGER]
    assert len(pending) == 1


def test_an_undated_belief_clashes_and_a_multi_valued_place_ends_only_on_evidence(reading):
    server, memory = reading
    # works-at is multi-valued: a new place is added beside the old; the old ends only when the page says so.
    old_place = _seed_claim(memory, obj="Alpha Example", predicate="works-at")
    _source(memory, PROFILE, "works-at")
    added = _apply(memory, _read("Team Labs", TODAY), ref=PROFILE, predicate="works-at")
    assert added.action == "added"
    assert {c.object for c in _claims(memory) if c.valid_to is None and c.predicate == "works-at"} == {
        "Alpha Example", "Team Labs"}
    ended = _apply(memory, _read(None, TODAY + timedelta(days=1), quote="Alpha Example · 2024 - Oct 2026",
                                 ended=[{"value": "Alpha Example", "on": T}]),
                   ref=PROFILE, predicate="works-at", today=TODAY + timedelta(days=1))
    assert ended.action == "updated"
    assert {c.id: c for c in _claims(memory)}[old_place].valid_to == T


# ---------- dead sites: two failed visits a week apart ----------


def test_two_failed_visits_a_week_apart_mark_a_source_dead_and_keep_its_last_good_capture(reading):
    server, memory = reading
    _source(memory, refresh={"at": "2026-10-01", "outcome": "read", "good": "2026-10-01", "episode": "ep_2026-10-01_009"})
    miss = source_refresh.Observation
    first = _apply(memory, miss("not_found", captured_on=date(2026, 11, 1)), today=date(2026, 11, 1))
    assert first.action == "miss"
    soon = _apply(memory, miss("gone", captured_on=date(2026, 11, 4)), today=date(2026, 11, 4))
    assert soon.action == "miss", "two strikes inside a week are not enough"
    final = _apply(memory, miss("parked", captured_on=date(2026, 11, 9)), today=date(2026, 11, 9))
    assert final.action == "dead"
    st = fact_sources.list_sources(memory, "bob-example")[0]["refresh"]
    assert st["dead"] == {"since": "2026-11-01", "at": "2026-11-09", "outcome": "parked"}
    assert st["good"] == "2026-10-01" and st["episode"] == "ep_2026-10-01_009", "the last good capture is kept"
    assert source_refresh.due(memory, today=date(2026, 12, 30)) == [], "a dead source is not re-checked by itself"
    # A good visit (the person asked) clears the strikes.
    _apply(memory, source_refresh.Observation("read", captured_on=date(2026, 12, 30)), today=date(2026, 12, 30))
    st = fact_sources.list_sources(memory, "bob-example")[0]["refresh"]
    assert "dead" not in st and "misses" not in st


def test_the_fetchers_status_maps_to_the_dead_outcomes():
    assert source_refresh.classify(TEAM, "failed:http_404", "", "") == "not_found"
    assert source_refresh.classify(TEAM, "failed:http_410", "", "") == "not_found"
    assert source_refresh.classify(TEAM, "failed:ConnectError", "", "") == "gone"
    assert source_refresh.classify(TEAM, "ok", "<title>This domain is for sale</title>", TEAM) == "parked"
    assert source_refresh.classify(TEAM, "ok", "<title>Hi</title>", "https://sedoparking.com/x") == "parked"
    assert source_refresh.classify(TEAM, "ok", "<title>Hi</title>", "https://elsewhere.example.com/") == "moved"
    assert source_refresh.classify(TEAM, "failed:ReadTimeout", "", "") == "failed", "a timeout is no strike"
    assert source_refresh.classify(TEAM, "blocked", "", "") == "blocked"


# ---------- login-walled sources are never fetched by the backend ----------


def test_a_login_walled_source_is_never_fetched_by_the_backend(reading, monkeypatch):
    server, memory = reading
    _source(memory, PROFILE, "works-at")
    _commit(memory)
    calls: list[str] = []
    report = asyncio.run(source_refresh.run_tail(memory, stream_fn=_stream(calls=calls), today=TODAY))
    assert calls == [] and report.paths == []
    obs = asyncio.run(source_refresh.observe(PROFILE, "works-at", ["Bob Example"], stream_fn=_stream(calls=calls)))
    assert obs.outcome == "blocked" and calls == []
    (d,) = source_refresh.due(memory, today=TODAY)
    assert d.checker == "agent"
    # The person's "check now" on it marks it asked for their agent; still no fetch.
    async def boom(*a, **k):
        raise AssertionError("the backend fetched a login-walled page")

    monkeypatch.setattr(link_enrichment, "_stream_html", boom)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        r = TestClient(main.app).post("/entities/bob-example/sources/refresh",
                                      json={"ref": PROFILE, "predicate": "works-at"})
    finally:
        config.get_settings.cache_clear()
    assert r.status_code == 200, r.text
    (row,) = r.json()["sources"]
    assert row["refreshChecker"] == "agent" and row["refreshDue"] == "asked"


def test_the_persons_agent_leases_reads_and_records_a_walled_source(reading):
    server, memory = reading
    _seed_claim(memory, obj="Engineer")
    _source(memory, PROFILE, "role")
    _commit(memory)
    out = server.handle_tool("cicada_refresh_claim", {})
    assert "No tracked source is due" in out, "a walled site the person never turned on is not listed"
    enable(sites=(reading_hosts.site_of(PROFILE),))
    out = server.handle_tool("cicada_refresh_claim", {})
    token = out.split("lease_token `")[1].split("`")[0]
    assert "memory holds now: Engineer" in out
    wrong = server.handle_tool("cicada_record_refresh", {"entity_id": "bob-example", "source": PROFILE,
                                                         "predicate": "role", "lease_token": "0" * 32,
                                                         "outcome": "read", "value": "Staff Engineer",
                                                         "quotes": [{"quote": "Staff Engineer at Team Labs"}]})
    assert wrong.startswith("Not recorded")
    noquote = server.handle_tool("cicada_record_refresh", {"entity_id": "bob-example", "source": PROFILE,
                                                           "predicate": "role", "lease_token": token,
                                                           "outcome": "read", "value": "Staff Engineer"})
    assert noquote.startswith("Not recorded") and "quote" in noquote
    ok = server.handle_tool("cicada_record_refresh", {"entity_id": "bob-example", "source": PROFILE,
                                                      "predicate": "role", "lease_token": token, "outcome": "read",
                                                      "value": "Staff Engineer",
                                                      "quotes": [{"quote": "Staff Engineer at Team Labs"}]})
    assert ok.startswith("Recorded."), ok
    new = next(c for c in _claims(memory) if c.origin == source_refresh.ORIGIN)
    assert new.object == "Staff Engineer" and new.observer == "agent" and new.authored_by == "claude-code"
    msg = _git(memory, "log", "-1", "--format=%B")
    assert msg.startswith("Agent write") and "Cicada-Author: claude-code" in msg
    assert source_refresh.agent_due(memory) == [], "checked: no longer due"
    again = server.handle_tool("cicada_record_refresh", {"entity_id": "bob-example", "source": PROFILE,
                                                         "predicate": "role", "lease_token": token,
                                                         "outcome": "read", "value": "Staff Engineer",
                                                         "quotes": [{"quote": "Staff Engineer at Team Labs"}]})
    assert again.startswith("Not recorded"), "the lease is spent"


def test_a_wall_hands_the_site_back_and_pauses_it_for_a_week(reading):
    server, memory = reading
    _source(memory, PROFILE, "role")
    _commit(memory)
    enable(sites=(reading_hosts.site_of(PROFILE),))
    out = server.handle_tool("cicada_refresh_claim", {})
    token = out.split("lease_token `")[1].split("`")[0]
    back = server.handle_tool("cicada_refresh_claim", {"release": [
        {"source": PROFILE, "entity_id": "bob-example", "predicate": "role", "lease_token": token,
         "code": "needs_login"}]})
    assert "paused for a week" in back
    assert "No tracked source is due" in server.handle_tool("cicada_refresh_claim", {})


# ---------- the demo bank refuses ----------


def test_a_demo_bank_refuses_every_refresh_door(reading):
    server, memory = reading
    _source(memory, PROFILE, "role")
    (memory / "_bank.yaml").write_text("kind: demo\n", encoding="utf-8")
    enable(sites=(reading_hosts.site_of(PROFILE),))
    for tool, args in (("cicada_refresh_claim", {}),
                       ("cicada_record_refresh", {"entity_id": "bob-example", "source": PROFILE,
                                                  "lease_token": "x", "outcome": "read"})):
        out = server.handle_tool(tool, args)
        assert "demo" in out.lower(), out
    import os

    os.environ["CICADA_MEMORY_PATH"] = str(memory)
    config.get_settings.cache_clear()
    try:
        r = TestClient(main.app).post("/entities/bob-example/sources/refresh",
                                      json={"ref": PROFILE, "predicate": "role"})
    finally:
        os.environ.pop("CICADA_MEMORY_PATH", None)
        config.get_settings.cache_clear()
    assert r.status_code == 409


# ---------- the hook's one line ----------


def test_the_hook_says_how_many_tracked_sources_wait_for_the_persons_agent(reading):
    server, memory = reading
    _source(memory, PROFILE, "role")
    _commit(memory)
    bank_index.files(memory, "entities")   # the hook counts only from a warm cache
    assert hook_recall.refresh_line_for(memory) is None, "a site the person never turned on: nothing to say"
    enable(sites=(reading_hosts.site_of(PROFILE),))
    line = hook_recall.refresh_line_for(memory)
    assert line == recall_text.refresh_line(1)
    assert line.startswith("1 tracked source is due for a check")
    # R12: every tool the line names exists in the stdio schema.
    names = {t["name"] for t in server.TOOLS}
    assert {"cicada_refresh_claim", "cicada_record_refresh"} <= names
    assert "cicada_refresh_claim" in line and "cicada_record_refresh" in line
    # It rides the SessionStart note.
    note = hook_recall.session_start_note(memory, harness="claude-code", session_id="ses_hook", cwd=None,
                                          source=None, bank_paths=[memory], deadline=10 ** 9)
    assert "1 tracked source is due for a check" in note.text


def test_due_route_lists_who_works_each_without_fetching(reading, no_network, monkeypatch):
    server, memory = reading
    _source(memory)
    _source(memory, PROFILE, "works-at")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        body = TestClient(main.app).get("/sources/due").json()
    finally:
        config.get_settings.cache_clear()
    assert body["counts"] == {"tracked": 2, "dead": 0, "due": 2, "cicada": 1, "agent": 1, "agentReady": 0}
    agent_row = next(r for r in body["items"] if r["checker"] == "agent")
    assert "Reading in your browser" in agent_row["waitingFor"]


def test_the_sleep_tail_step_is_behind_the_connector_gate_and_commits_alone(reading, monkeypatch):
    server, memory = reading
    from api.services import sleep_cycle
    from api.services.connectors import base

    _seed_claim(memory)
    _source(memory)
    _commit(memory)
    calls: list[str] = []

    async def stream(url):
        calls.append(url)
        return ("ok", PAGE_WITH_ROLE, TEAM)

    monkeypatch.setattr(link_enrichment, "_stream_html", stream)
    monkeypatch.setattr(base, "network_allowed", lambda allow_fetch=None: False)
    asyncio.run(sleep_cycle._source_refresh_safely(memory))
    assert calls == [], "unattended fetches off: nothing read"
    monkeypatch.setattr(base, "network_allowed", lambda allow_fetch=None: True)
    asyncio.run(sleep_cycle._source_refresh_safely(memory))
    assert calls == [TEAM]
    assert _git(memory, "status", "--porcelain").strip() == "", "committed, path-scoped"
    msg = _git(memory, "log", "-1", "--format=%B")
    assert msg.startswith("Source refresh ") and "Cicada-Author: cicada" in msg


def test_a_public_page_that_changed_without_a_readable_fact_goes_to_the_persons_agent_but_a_site_never_does(reading):
    server, memory = reading
    _source(memory)                                                     # role, at the team page
    _source(memory, "https://bob-example.dev", "website")                # the official site: liveness only
    plain = "<html><title>Bob</title><body><p>Bob builds the indexing service.</p></body></html>"
    later = TODAY + timedelta(days=31)

    async def stream(url, html=plain):
        return ("ok", html, url)

    asyncio.run(source_refresh.run_tail(memory, stream_fn=stream, today=TODAY, budget=5))
    assert source_refresh.due(memory, today=TODAY) == []

    async def changed(url):
        return ("ok", plain.replace("indexing service", "billing platform"), url)

    asyncio.run(source_refresh.run_tail(memory, stream_fn=changed, today=later, budget=5))
    due = {d.ref: (d.checker, d.reason) for d in source_refresh.due(memory, today=later)}
    assert due == {TEAM: ("agent", "changed")}, "the site's own words changing is no fact to read"


# ---------- review B1: an unknown cardinality coexists; only the page's own `ended` closes a value ----------


def test_a_page_listing_two_alumni_closes_neither_and_adds_the_missing_one(reading):
    server, memory = reading
    beta = _seed_claim(memory, obj="Beta Institute", predicate="studied-at")
    _source(memory, predicate="studied-at")
    html = PAGE_WITH_ROLE.replace('"jobTitle": "Staff Engineer"',
                                  '"alumniOf": [{"@type": "Organization", "name": "Alpha University"}, '
                                  '{"@type": "Organization", "name": "Beta Institute"}]')
    asyncio.run(source_refresh.run_tail(memory, stream_fn=_stream(html=html), today=TODAY))
    claims = {c.id: c for c in _claims(memory)}
    assert claims[beta].valid_to is None, "the page still lists it: nothing closes"
    assert {c.object for c in claims.values() if c.valid_to is None and c.predicate == "studied-at"} == {
        "Beta Institute", "Alpha University"}


def test_one_job_title_never_closes_a_second_current_role_of_unknown_cardinality(reading):
    server, memory = reading
    first = _seed_claim(memory, obj="Engineer")
    second = _seed_claim(memory, obj="Advisor")
    _source(memory)
    asyncio.run(source_refresh.run_tail(memory, stream_fn=_stream(), today=TODAY))
    claims = {c.id: c for c in _claims(memory)}
    assert claims[first].valid_to is None and claims[second].valid_to is None
    assert {c.object for c in claims.values() if c.valid_to is None and c.predicate == "role"} == {
        "Engineer", "Advisor", "Staff Engineer"}
    # ...and when the vocabulary knows a role is ONE value, the newer reading does close both.
    _single_valued(memory)
    obs = _read("Principal Engineer", TODAY + timedelta(days=1))
    _apply(memory, obs, today=TODAY + timedelta(days=1))
    current = {c.object for c in _claims(memory) if c.valid_to is None and c.predicate == "role"}
    assert current == {"Principal Engineer"}
