"""G245 (ruling 79 (b), owner 2026-11-24: "Should the accounts you follow be read?" "2. yes"): the accounts the person follows
on X — a directory outside every bank that attaches to a page that already exists and is never the reason one is made.

"a linkedin connection doesnt need a page just for the sake of having a page, the person is what gets a page": a followed
account is treated like a connection. The person's own agent reads their Following list in their own browser, weekly and
whole, with a row cap; the rows are kept outside every bank and git (name, handle, link, first seen, gone); a page that
already exists gains the profile link (only proposed when the name alone says so) and one dated "followed-on" fact; a
page is never made, a mention never counted, decay never refreshed; and a name known only from the list never leaves in a
web query. Synthetic accounts, placeholder links; nothing reads a real bank, `~/.cicada` or the network."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from _reading_fixtures import porcelain, reading  # noqa: F401 — `reading` is a fixture
from _synthetic_bank import _bank, _entity
from api import config, main
from api.remote import catalog
from api.services import (agentic_write, bank_index, conflict_resolver, demo_guard, entity_resolver as er, fact_sources,
                          follows_people, markdown_parser, name_guard, people_directory, reading_settings, replica_routes,
                          same_name_doubts, saved_lists, settling_agent, sleep_cycle, source_streams, web_settle)
from api.services.claims import parse_claims

DAY1, DAY2, DAY3 = "2026-11-24", "2026-12-01", "2026-12-08"
KEY = "x-following"
X = "https://x.com"


def _on():
    reading_settings.update(saved_lists_={KEY: True})


def _acct(name, handle, **extra):
    return {"name": name, "url": f"{X}/{handle}", **extra}


def _record(server, items, outcome="read", **kw):
    args = {"platform": KEY, "outcome": outcome, **kw}
    if items is not None:
        args["items"] = items
    return server.handle_tool("cicada_record_saved_list", args)


def _held(memory):
    return people_directory.load_json(memory.name, "follows-x.json")


def _rows(memory):
    return {r["handle"]: r for r in _held(memory).get("rows", [])}


def _read(memory, handles, day, *, end=True, cont=False, names=None):
    """One call of a read straight into the directory (the tool's own body, without the tool)."""
    items = [_acct((names or {}).get(h, h.title()), h) for h in handles]
    return follows_people.record_read(memory.name, "x", items, day, continues=cont, reached_end=end)


def _page_claims(memory, eid):
    return [c for c in parse_claims(markdown_parser.parse(memory / "entities" / f"{eid}.md").body)
            if c.predicate == follows_people.PREDICATE]


def _sources(memory, eid):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter.get("sources") or []


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], capture_output=True, text=True, check=True).stdout.strip()


def _commit(memory, message="fixtures"):
    subprocess.run(["git", "-C", str(memory), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", message], check=True, capture_output=True)
    bank_index.invalidate()


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    _entity(memory, "erin-example", type="person", name="Erin Example",
            sources=[{"ref": f"{X}/erin_example", "kind": "url", "predicate": "x", "added_by": "user"}])
    _entity(memory, "acme-labs", type="company", name="Acme Labs")
    _entity(memory, "widget-tool", type="tool", name="Widget Tool")
    _entity(memory, "finn-sample", type="person", name="Finn Sample")
    _entity(memory, "owner-page", type="person", name="Pat Owner", owner=True)
    _entity(memory, "alpha-launch", type="project", name="Acme Launch")
    _commit(memory)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    yield memory
    bank_index.invalidate()


# --- the list: off until turned on, an accounts list, weekly, whole, never unattended -----------------------------------------


def test_following_is_an_accounts_list_of_x_off_until_the_person_turns_it_on():
    p = saved_lists.PLATFORMS[KEY]
    likes = saved_lists.PLATFORMS["x-likes"]
    assert (p.base, p.kind, p.origin, p.folder, p.label) == ("x", "accounts", "", "", "Following")
    assert (p.site, p.profile_hosts, p.name) == (likes.site, likes.profile_hosts, likes.name)
    assert p.cadence == timedelta(days=7) and not p.folders and not p.bounded
    assert KEY not in reading_settings.DEFAULT_ON_SAVED_LISTS
    assert tuple(saved_lists.PLATFORMS) == reading_settings.SAVED_LISTS
    assert saved_lists.pause_key(KEY) == "x", "a login wall met reading it pauses every X list, and the reverse"
    assert follows_people.SITES["x"].platform == KEY and follows_people.site_of_platform(KEY).max_rows == 2000


def test_a_read_is_offered_weekly_and_never_to_an_unattended_run(reading):
    server, memory = reading
    _on()
    reading_settings.update(saved_lists_={KEY: True, "x": False})
    now = datetime(2026, 11, 24, 8, tzinfo=timezone.utc)
    assert saved_lists.due(memory, now) == [KEY]
    assert saved_lists.due(memory, now, unattended=True) == [], "an accounts list is never offered to a read nobody watches"
    saved_lists.note(memory, KEY, "read", items=3, new=3, reached_end=True, now=now)
    assert saved_lists.whole(memory, KEY)
    assert saved_lists.due(memory, now, unattended=True) == [], "not even once it has been read to its end"
    assert saved_lists.due(memory, now + timedelta(days=6)) == []
    assert saved_lists.due(memory, now + timedelta(days=7, minutes=1)) == [KEY]
    assert saved_lists.cadence_of(memory, KEY) == timedelta(days=7)
    assert "following" not in server.handle_tool("cicada_reading_queue", {"unattended": True}).lower()


def test_the_queue_words_ask_for_the_whole_list_with_its_caps_and_name_the_clicks_that_are_forbidden(reading):
    server, memory = reading
    _on()
    reading_settings.update(saved_lists_={KEY: True, "x": False})
    saved_lists.note(memory, KEY, "read", items=3, new=3, reached_end=True, handle="alex_example",
                     profile_url=f"{X}/alex_example")
    saved_lists.request_check(memory, KEY)
    out = server.handle_tool("cicada_reading_queue", {})
    site = follows_people.SITES["x"]
    assert f"{X}/alex_example/following" in out
    assert "Read ALL of it, every time" in out and f"{site.max_rows:,} accounts" in out and f"{site.max_screens} screens" in out
    assert "reached_end=true" in out and "nothing is marked as no longer followed" in out
    for forbidden in ("follow, unfollow, mute, block, remove", "bio", "no counts", "no picture"):
        assert forbidden in out, forbidden
    assert 'platform="x-following"' in out and "continues=true" in out
    assert "Who to follow" in out, "the suggestions on the page are said to be left alone"
    assert saved_lists.pass_calls(memory, KEY) == saved_lists.WHOLE_PASS_CALLS, "a list of thousands may take many calls"


def test_the_stdio_tool_schema_takes_the_platform():
    from _stdio_server import stdio_server

    tool = next(t for t in stdio_server().TOOLS if t["name"] == "cicada_record_saved_list")
    assert KEY in tool["inputSchema"]["properties"]["platform"]["enum"]
    assert list(tool["inputSchema"]["properties"]["platform"]["enum"]) == list(reading_settings.SAVED_LISTS)


# --- what is kept, outside every bank --------------------------------------------------------------------------------------


def test_a_read_keeps_a_name_a_handle_a_link_and_a_day_and_nothing_else_outside_the_bank(reading):
    server, memory = reading
    out = _record(server, [_acct("Erin Example", "erin_example")])
    assert "has not asked" in out and not _held(memory), "off until turned on"
    _on()
    head = _git(memory, "rev-parse", "HEAD")
    pages = sorted(p.name for p in (memory / "entities").glob("*"))
    episodes = sorted(p.name for p in (memory / "episodes").glob("*"))
    out = _record(server, [
        _acct("Erin Example", "erin_example", bio="Builds things in public", followers=12000, avatar="https://x.com/a.png",
              follows_back=True),
        _acct("Acme Labs", "acme_labs", text="we are hiring"),
        {"name": "A bare handle", "handle": "@bare_handle"},
        {"name": "A post, not an account", "url": f"{X}/erin_example/status/1000000000000000001"},
        {"name": "A search", "url": f"{X}/search?q=x"},
        {"name": "Another site", "url": "https://example.org/someone"},
        {"name": "Reserved", "url": f"{X}/settings"},
    ], handle="alex_example", profile_url=f"{X}/alex_example", reached_end=True)
    assert "3 new" in out and "4 row(s) were not an account's own profile link" in out, out
    assert "never read" in out and "did not save them" in out and "never makes a page" in out
    rows = _rows(memory)
    assert set(rows) == {"erin_example", "acme_labs", "bare_handle"}
    assert set(rows["erin_example"]) == {"handle", "name", "url", "first_seen", "since", "last_seen"}, "no bio, count or picture"
    assert rows["erin_example"]["url"] == f"{X}/erin_example" and rows["erin_example"]["first_seen"] == datetime.now(timezone.utc).date().isoformat()
    blob = (people_directory.path(memory.name, "follows-x.json")).read_text()
    for secret in ("Builds things", "12000", "avatar", "hiring", "follows_back"):
        assert secret not in blob
    assert oct(people_directory.path(memory.name, "follows-x.json").stat().st_mode & 0o777) == "0o600"
    # nothing in the bank: no page, no episode, no media page, no commit, nothing in git
    assert sorted(p.name for p in (memory / "entities").glob("*")) == pages
    assert sorted(p.name for p in (memory / "episodes").glob("*")) == episodes
    assert not list((memory / "entities").glob("media-*")), "no media page"
    assert _git(memory, "rev-parse", "HEAD") == head and porcelain(memory) == ""
    assert saved_lists.last(memory, KEY)["outcome"] == "read" and saved_lists.last(memory, KEY)["handle"] == "alex_example"


def test_a_read_of_rows_that_are_no_accounts_is_a_failed_read_and_keeps_nothing(reading):
    server, memory = reading
    _on()
    out = _record(server, [{"name": "A post", "url": f"{X}/erin_example/status/1000000000000000001"}])
    assert "the read failed" in out and not _held(memory)
    assert saved_lists.last(memory, KEY)["outcome"] == "failed"


def test_an_empty_following_list_is_a_read_that_found_nothing_and_marks_nobody_gone(reading):
    server, memory = reading
    _on()
    _read(memory, ["erin_example"], DAY1)
    out = _record(server, [])
    assert "is empty" in out and set(_rows(memory)) == {"erin_example"} and not _rows(memory)["erin_example"].get("gone_on")


def test_nothing_but_counts_is_logged_and_the_tool_reply_never_names_an_account(reading):
    server, memory = reading
    _on()
    seen: list[str] = []
    sink = logger.add(lambda message: seen.append(str(message)), level="DEBUG")
    try:
        out = _record(server, [_acct("Zelda Secretname", "zelda_secret")], reached_end=True)
        follows_people.rematch(memory)
        follows_people.list_rows(memory, memory.name)
    finally:
        logger.remove(sink)
    assert "Zelda" not in out and "zelda_secret" not in out
    assert not [line for line in seen if "Zelda" in line or "zelda_secret" in line]


# --- the cap, and when an account is gone ---------------------------------------------------------------------------------


def test_a_list_past_the_row_cap_says_more_than_and_marks_nothing_gone(reading, monkeypatch):
    server, memory = reading
    _on()
    monkeypatch.setitem(follows_people.SITES, "x", dataclasses.replace(follows_people.SITES["x"], max_rows=5))
    _read(memory, [f"acct_{i}" for i in range(5)], DAY1)
    _read(memory, [f"acct_{i}" for i in range(5)], DAY2)       # a trusted whole read: the reference is 5
    items = [_acct(f"Acct {i}", f"acct_{i}") for i in range(8)]
    out = _record(server, items, reached_end=True)
    assert "longer than 5 accounts" in out and "nothing is marked as no longer followed" in out, out
    assert len(_rows(memory)) == 5 and "pass" not in _held(memory), "the pass is over; the cap held"
    assert not [r for r in _rows(memory).values() if r.get("gone_on") or r.get("missed")]
    # a read cut by the cap never counts as the end, whatever the agent said
    assert saved_lists.whole(memory, KEY) is False


def test_a_read_that_stopped_early_marks_nothing_and_an_account_is_gone_only_after_two_whole_reads_agree(bank):
    everyone = ["erin_example", "acme_labs", "widget_tool", "finn_sample", "zoe_1", "zoe_2", "zoe_3", "zoe_4", "zoe_5",
                "zoe_6"]
    first = _read(bank, everyone, DAY1)
    assert first.first_whole and not first.trusted and first.marked_gone == 0, "nothing to compare with: it judges nobody"
    # a read the agent stopped (no end) never marks anything, however many it missed
    cut = _read(bank, everyone[:3], DAY2, end=False)
    assert not cut.finished and cut.marked_gone == 0 and "pass" in _held(bank)
    assert all(not r.get("missed") for r in _rows(bank).values())
    # a whole read that misses one: the first miss only counts
    one = _read(bank, [h for h in everyone if h != "zoe_6"], DAY2)
    assert one.trusted and one.marked_gone == 0 and _rows(bank)["zoe_6"]["missed"] == 1 and not _rows(bank)["zoe_6"].get("gone_on")
    # seen again in a read that stopped early: it is there, so the streak ends
    _read(bank, ["zoe_6"], "2026-12-03", end=False)
    assert "missed" not in _rows(bank)["zoe_6"]
    _read(bank, [h for h in everyone if h != "zoe_6"], "2026-12-04")
    assert _rows(bank)["zoe_6"]["missed"] == 1
    # the second whole read in a row that agrees: gone, on that day
    two = _read(bank, [h for h in everyone if h != "zoe_6"], DAY3)
    assert two.marked_gone == 1 and _rows(bank)["zoe_6"]["gone_on"] == DAY3
    assert status_count(bank) == 9 and follows_people.status(bank.name)["gone"] == 1
    # back again: no longer gone, and the stretch starts over
    _read(bank, everyone, "2026-12-09", end=False)
    assert "gone_on" not in _rows(bank)["zoe_6"] and _rows(bank)["zoe_6"]["since"] == "2026-12-09"
    assert _rows(bank)["zoe_6"]["first_seen"] == DAY1


def status_count(memory):
    return follows_people.following_count(memory.name)


def test_a_whole_read_much_smaller_than_the_last_one_marks_nothing_and_does_not_become_the_reference(bank):
    everyone = [f"acct_{i}" for i in range(20)]
    _read(bank, everyone, DAY1)
    for day in ("2026-12-01", "2026-12-02", "2026-12-03"):
        short = _read(bank, everyone[:10], day)            # a lazy list that stops at half, three reads in a row
        assert short.finished and short.short and not short.trusted and short.marked_gone == 0
    assert not [r for r in _rows(bank).values() if r.get("gone_on") or r.get("missed")]
    assert _held(bank)["whole_count"] == 20, "a short read never replaces the reference"
    ok = _read(bank, everyone[:19], "2026-12-04")           # within 90%: trusted
    assert ok.trusted and _rows(bank)["acct_19"]["missed"] == 1


def test_a_call_that_carries_on_a_read_this_list_never_saw_start_can_never_end_one(bank):
    everyone = [f"acct_{i}" for i in range(10)]
    _read(bank, everyone, DAY1)
    _read(bank, everyone, DAY2)
    stray = _read(bank, everyone[:3], DAY3, cont=True)      # `continues` with no pass open here
    assert stray.partial and not stray.finished and stray.marked_gone == 0
    assert not [r for r in _rows(bank).values() if r.get("missed")]


def test_a_closing_call_that_repeats_only_rows_the_pass_met_still_ends_the_pass_and_judges_it(bank):
    everyone = [f"acct_{i}" for i in range(10)]
    _read(bank, everyone, DAY1)
    _read(bank, everyone[:9], DAY2, end=False)                     # a new read of nine
    closing = _read(bank, everyone[:5], DAY2, end=True, cont=True)   # scrolled on, nothing new: the end, said
    assert closing.finished and closing.trusted and closing.seen == 0 and closing.accounts == 5
    held = _held(bank)
    assert "pass" not in held and held["whole_count"] == 9 and held["whole_on"] == DAY2
    assert _rows(bank)["acct_9"]["missed"] == 1 and not _rows(bank)["acct_0"].get("missed")


def test_a_closing_empty_call_with_the_end_said_ends_the_pass_in_the_tool_and_the_list_status(reading):
    server, memory = reading
    _on()
    everyone = [f"acct_{i}" for i in range(10)]
    _record(server, [_acct(h.title(), h) for h in everyone], reached_end=True)        # the first whole read: the reference
    _record(server, [_acct(h.title(), h) for h in everyone[:9]])                     # a new read of nine, no end yet
    assert "pass" in _held(memory)
    out = _record(server, [], continues=True, reached_end=True)
    assert "is empty" not in out and "The whole list is kept" in out, out
    held = _held(memory)
    assert "pass" not in held and held["whole_count"] == 9 and _rows(memory)["acct_9"]["missed"] == 1
    assert saved_lists.whole(memory, KEY) is True
    # the same closing call again: no pass is open in the directory, so it judges nobody
    again = _record(server, [], continues=True, reached_end=True)
    assert "did not begin here" in again, again
    assert _rows(memory)["acct_9"]["missed"] == 1 and not _rows(memory)["acct_9"].get("gone_on")


def test_a_closing_call_with_repeats_and_a_stray_row_is_no_failed_read(reading):
    server, memory = reading
    _on()
    everyone = [f"acct_{i}" for i in range(10)]
    _record(server, [_acct(h.title(), h) for h in everyone], reached_end=True)
    _record(server, [_acct(h.title(), h) for h in everyone[:9]])
    out = _record(server, [_acct("Acct 1", "acct_1"), {"name": "Reserved", "url": f"{X}/settings"}], continues=True,
                  reached_end=True)
    assert "the read failed" not in out and "The whole list is kept" in out, out
    assert saved_lists.last(memory, KEY)["outcome"] == "read"


def test_a_call_that_says_it_continues_when_no_pass_is_open_is_never_a_whole_read(reading):
    server, memory = reading
    _on()
    everyone = [f"acct_{i}" for i in range(10)]
    _record(server, [_acct(h.title(), h) for h in everyone], reached_end=True)
    out = _record(server, [_acct(h.title(), h) for h in everyone[:3]], continues=True, reached_end=True)
    assert "did not begin here" in out, out
    assert not [r for r in _rows(memory).values() if r.get("missed")] and _held(memory)["whole_count"] == 10


def test_a_read_over_several_calls_is_one_pass_and_a_new_read_drops_the_one_that_stopped(bank):
    everyone = [f"acct_{i}" for i in range(10)]
    _read(bank, everyone, DAY1)
    _read(bank, everyone[:5], DAY2, end=False)
    _read(bank, everyone[5:9], DAY2, end=True, cont=True)       # the whole list in two calls, one account missing
    assert _rows(bank)["acct_9"]["missed"] == 1
    _read(bank, everyone[:4], DAY3, end=False)
    again = _read(bank, everyone[:9], DAY3, end=True)            # a new read (not continued): the stopped one is dropped
    assert again.trusted and _rows(bank)["acct_9"]["gone_on"] == DAY3


def test_a_row_gone_for_half_a_year_is_dropped_and_forget_removes_everything(bank):
    everyone = [f"acct_{i}" for i in range(10)]
    _read(bank, everyone, "2026-01-01")
    for day in ("2026-01-08", "2026-01-15"):
        _read(bank, everyone[:9], day)
    assert _rows(bank)["acct_9"]["gone_on"] == "2026-01-15"
    _read(bank, everyone[:9], "2026-08-01")
    assert "acct_9" not in _rows(bank)
    assert follows_people.forget(bank.name, "x") == 9
    assert not follows_people.directory_path(bank.name, "x").exists() and follows_people.status(bank.name)["following"] == 0


def test_trashing_or_renaming_the_bank_takes_the_directory_along(bank):
    _read(bank, ["erin_example"], DAY1)
    assert follows_people.directory_path(bank.name, "x").exists()
    follows_people.rename(bank.name, "renamed")
    assert not follows_people.directory_path(bank.name, "x").exists() and follows_people.directory_path("renamed", "x").exists()
    follows_people.forget_bank("renamed")
    assert not people_directory.folder("renamed").exists()


# --- attaching to a page that already exists ----------------------------------------------------------------------------


def test_a_page_that_holds_the_accounts_link_gains_one_dated_fact_and_nothing_else(bank):
    _read(bank, ["erin_example"], DAY1, names={"erin_example": "Erin E."})
    before = markdown_parser.parse(bank / "entities" / "erin-example.md").frontmatter
    report = follows_people.rematch(bank)
    assert report.paths == ["entities/erin-example.md"] and report.claims_written == 1 and report.sources_added == 0
    (claim,) = _page_claims(bank, "erin-example")
    assert (claim.object, claim.observer, claim.valid_from, claim.valid_to) == ("X", "external:x", DAY1, None)
    assert claim.origin == "follows/x" and claim.source_trust == "external" and claim.authored_by == "cicada"
    after = markdown_parser.parse(bank / "entities" / "erin-example.md").frontmatter
    assert len(after["sources"]) == 1, "the link was already there: nothing is added twice"
    for held in ("last_referenced", "learned_on", "decayed_through", "confidence", "status", "source_episodes", "created"):
        assert after.get(held) == before.get(held), f"a follow never touches {held}"
    assert follows_people.rematch(bank).paths == [], "idempotent"


def test_a_name_alone_is_only_a_proposed_link_and_no_fact_until_the_person_takes_it(bank):
    _read(bank, ["acme_labs_hq", "widget_tool_app"], DAY1, names={"acme_labs_hq": "Acme Labs", "widget_tool_app": "Widget Tool"})
    report = follows_people.rematch(bank)
    assert sorted(report.paths) == ["entities/acme-labs.md", "entities/widget-tool.md"] and report.proposed == 2
    (link,) = _sources(bank, "acme-labs")
    assert (link["ref"], link["kind"], link["predicate"], link["added_by"], link["match"], link["proposed"]) == (
        f"{X}/acme_labs_hq", "url", "x", "cicada", "name", True)
    assert not _page_claims(bank, "acme-labs") and not _page_claims(bank, "widget-tool")
    assert not fact_sources.trusted(link) and fact_sources.is_proposed(link)
    # the person takes it ("Confirm N links"): the page now holds the account, so the next night writes the fact
    fm = markdown_parser.parse(bank / "entities" / "acme-labs.md")
    for s in fm.frontmatter["sources"]:
        s["accepted"] = True
        s.pop("proposed", None)
    markdown_parser.write(bank / "entities" / "acme-labs.md", fm.frontmatter, fm.body)
    bank_index.invalidate()
    again = follows_people.rematch(bank)
    assert again.paths == ["entities/acme-labs.md"] and [c.valid_from for c in _page_claims(bank, "acme-labs")] == [DAY1]


def test_an_unchanged_proposal_is_never_made_twice_and_an_unaccepted_one_is_no_tie(bank):
    _read(bank, ["acme_labs_hq"], DAY1, names={"acme_labs_hq": "Acme Labs"})
    assert follows_people.rematch(bank).paths == ["entities/acme-labs.md"]
    assert follows_people.rematch(bank).paths == [], "the proposal is already there"
    assert len(_sources(bank, "acme-labs")) == 1 and not _page_claims(bank, "acme-labs")


def test_it_never_makes_a_page_and_never_counts_as_a_mention(bank):
    _read(bank, ["erin_example", "nobody_here", "zed_new"], DAY1, names={"nobody_here": "Nobody Here", "zed_new": "Zed New"})
    before = sorted(p.name for p in (bank / "entities").glob("*.md"))
    stamps = {p.name: markdown_parser.parse(p).frontmatter.get("last_referenced") for p in (bank / "entities").glob("*.md")}
    follows_people.rematch(bank)
    assert sorted(p.name for p in (bank / "entities").glob("*.md")) == before, "a followed account never makes a page"
    assert {p.name: markdown_parser.parse(p).frontmatter.get("last_referenced")
            for p in (bank / "entities").glob("*.md")} == stamps
    assert not list((bank / "episodes").glob("*follow*"))


def test_only_a_person_an_organisation_or_a_tool_page_gains_anything_never_the_owner_or_a_project(bank):
    _read(bank, ["pat_owner", "acme_launch"], DAY1, names={"pat_owner": "Pat Owner", "acme_launch": "Acme Launch"})
    assert follows_people.ATTACH_TYPES == frozenset({"person", "company", "tool"})
    assert follows_people.rematch(bank).paths == [], "the owner's page and a project page gain nothing"


def test_a_first_name_alone_never_matches_a_person_page_and_a_two_part_name_does(bank):
    _entity(bank, "mara", type="person", name="Mara")
    _entity(bank, "mara-quill", type="person", name="Mara Quill")
    _commit(bank)
    _read(bank, ["mara_q", "mara_only"], DAY1, names={"mara_q": "Mara Quill", "mara_only": "Mara"})
    report = follows_people.rematch(bank)
    assert report.paths == ["entities/mara-quill.md"] and not _sources(bank, "mara")
    assert [s["ref"] for s in _sources(bank, "mara-quill")] == [f"{X}/mara_q"]


def test_names_are_free_text_so_two_pages_two_accounts_a_doubt_or_another_profile_refuse_and_are_counted(bank):
    # two pages of one name
    _entity(bank, "finn-sample-two", type="person", name="Finn Sample")
    _commit(bank)
    _read(bank, ["finn_s"], DAY1, names={"finn_s": "Finn Sample"})
    report = follows_people.rematch(bank)
    assert report.paths == [] and report.ambiguous == 1 and not _sources(bank, "finn-sample")
    # two followed accounts of one name
    (bank / "entities" / "finn-sample-two.md").unlink()
    _commit(bank)
    follows_people.forget(bank.name)
    _read(bank, ["finn_a", "finn_b"], DAY1, names={"finn_a": "Finn Sample", "finn_b": "Finn Sample"})
    assert follows_people.rematch(bank).paths == [] and not _sources(bank, "finn-sample")
    # a same-name doubt for that name
    follows_people.forget(bank.name)
    _read(bank, ["finn_s"], DAY1, names={"finn_s": "Finn Sample"})
    _entity(bank, "finn-sample-three", type="person", name="Finn Sample")
    same_name_doubts.add_pairs(bank, [("finn-sample", "finn-sample-three")], today=DAY1)
    _commit(bank)
    report = follows_people.rematch(bank)
    assert report.paths == [] and report.doubted >= 1
    # a page that already names another profile is someone else
    (bank / "entities" / "finn-sample-three.md").unlink()
    _entity(bank, "finn-sample", type="person", name="Finn Sample",
            sources=[{"ref": f"{X}/someone_else", "kind": "url", "predicate": "x", "added_by": "user"}])
    _commit(bank)
    assert follows_people.rematch(bank).paths == []
    # but the link the page itself holds is the page, whatever else shares the name
    follows_people.forget(bank.name)
    _read(bank, ["someone_else"], DAY1, names={"someone_else": "Some Other Name"})
    assert follows_people.rematch(bank).paths == ["entities/finn-sample.md"]


def test_a_removal_by_the_person_is_remembered_and_respected(bank):
    _read(bank, ["acme_labs_hq"], DAY1, names={"acme_labs_hq": "Acme Labs"})
    assert follows_people.rematch(bank).paths == ["entities/acme-labs.md"]
    fm = markdown_parser.parse(bank / "entities" / "acme-labs.md")
    fm.frontmatter["sources"] = []
    fm.frontmatter[fact_sources.REMOVED_KEY] = [{"ref": f"{X}/acme_labs_hq", "predicate": "x", "by": "user", "at": DAY2}]
    markdown_parser.write(bank / "entities" / "acme-labs.md", fm.frontmatter, fm.body)
    bank_index.invalidate()
    assert follows_people.rematch(bank).paths == [], "never re-proposed"
    # the same for the link of a page that held it: removed, then the account is no longer that page's
    fm = markdown_parser.parse(bank / "entities" / "erin-example.md")
    fm.frontmatter["sources"] = []
    fm.frontmatter[fact_sources.REMOVED_KEY] = [{"ref": f"{X}/erin_example", "predicate": "x", "by": "user", "at": DAY2}]
    markdown_parser.write(bank / "entities" / "erin-example.md", fm.frontmatter, fm.body)
    bank_index.invalidate()
    _read(bank, ["erin_example"], DAY2, names={"erin_example": "Erin Example"})
    assert follows_people.rematch(bank).paths == [] and not _page_claims(bank, "erin-example")


def test_the_fact_closes_when_the_account_is_gone_and_only_then(bank):
    everyone = [f"acct_{i}" for i in range(9)] + ["erin_example"]
    _read(bank, everyone, DAY1)
    follows_people.rematch(bank)
    assert [c.valid_to for c in _page_claims(bank, "erin-example")] == [None]
    _read(bank, [h for h in everyone if h != "erin_example"], DAY2, end=False)      # stopped early: still followed
    follows_people.rematch(bank)
    assert [c.valid_to for c in _page_claims(bank, "erin-example")] == [None]
    _read(bank, [h for h in everyone if h != "erin_example"], DAY2)
    follows_people.rematch(bank)
    assert [c.valid_to for c in _page_claims(bank, "erin-example")] == [None], "one whole read is not enough"
    _read(bank, [h for h in everyone if h != "erin_example"], DAY3)
    report = follows_people.rematch(bank)
    assert report.claims_closed == 1 and [c.valid_to for c in _page_claims(bank, "erin-example")] == [DAY3]
    # followed again: a new dated fact, the old one stays closed
    _read(bank, everyone, "2026-12-09")
    follows_people.rematch(bank)
    assert sorted((c.valid_from, c.valid_to) for c in _page_claims(bank, "erin-example")) == [(DAY1, DAY3), ("2026-12-09", None)]


def test_a_demo_bank_takes_in_nothing_and_a_list_never_kept_attaches_nothing(bank):
    assert follows_people.rematch(bank).paths == []
    _read(bank, ["erin_example"], DAY1)
    demo_guard.write_manifest(bank)
    assert follows_people.rematch(bank).paths == []
    fm, body = follows_people.Attacher(bank).attach({"name": "Erin Example", "type": "person"}, "x", "erin-example")
    assert "sources" not in fm


# --- a page's birth --------------------------------------------------------------------------------------------------------


def _fm(name, kind="person", **extra):
    return {"name": name, "type": kind, "status": "active", **extra}


def test_a_page_born_attaches_in_the_write_that_births_it_and_two_of_one_name_refuse(bank):
    _read(bank, ["grace_x", "acme_x"], DAY1, names={"grace_x": "Grace Example", "acme_x": "Acme Inc"})
    attacher = follows_people.Attacher(bank)
    fm, body = attacher.attach(_fm("Grace Example"), "## Summary\nGrace.\n", "grace-example")
    (link,) = fm["sources"]
    assert (link["ref"], link["match"], link["proposed"], link["added_by"]) == (f"{X}/grace_x", "name", True, "cicada")
    assert "followed-on" not in body, "a name alone writes no fact"
    fm2, _ = attacher.attach(_fm("Acme Inc", "company"), "## Summary\nAcme.\n", "acme-inc")
    assert [s["ref"] for s in fm2["sources"]] == [f"{X}/acme_x"]
    fm3, _ = attacher.attach(_fm("Grace Example"), "## Summary\nGrace.\n", "grace-example-2")
    assert "sources" not in fm3 and attacher.report.ambiguous >= 1, "a second page of that name makes both refuse"
    # a page born holding the account's link gets the fact
    fm4, body4 = follows_people.Attacher(bank).attach(
        _fm("Whoever", sources=[{"ref": f"{X}/grace_x", "kind": "url", "predicate": "x", "added_by": "user"}]),
        "## Summary\nWhoever.\n", "whoever")
    assert "followed-on" in body4 and len(fm4["sources"]) == 1


def test_the_owner_a_project_a_dropped_page_and_a_removed_link_attach_nothing_at_birth(bank):
    _read(bank, ["grace_x"], DAY1, names={"grace_x": "Grace Example"})
    a = follows_people.Attacher(bank)
    for fm in (_fm("Grace Example", owner=True), _fm("Grace Example", "project"), _fm("Grace Example", status="dropped"),
               _fm("Grace Example", "concept")):
        out, _ = a.attach(fm, "x", "grace-example")
        assert "sources" not in out
    removed = {fact_sources.REMOVED_KEY: [{"ref": f"{X}/grace_x", "predicate": "x", "by": "user", "at": DAY1}]}
    out, _ = follows_people.Attacher(bank).attach(_fm("Grace Example", **removed), "x", "grace-example")
    assert not out.get("sources")


def test_an_agents_first_claim_about_a_new_person_or_organisation_births_the_page_with_the_account(bank):
    _read(bank, ["grace_x", "acme_x"], DAY1, names={"grace_x": "Grace Example", "acme_x": "Acme Inc"})
    agentic_write.write_claim(bank, "Grace Example", "works-with", "Acme Robotics", observer="agent", confidence=0.6)
    assert [s["ref"] for s in _sources(bank, "grace-example")] == [f"{X}/grace_x"]
    assert markdown_parser.parse(bank / "entities" / "grace-example.md").frontmatter["sources"][0]["proposed"] is True
    agentic_write.write_claim(bank, "Zed Nobody", "works-with", "Acme Robotics", observer="agent", confidence=0.6)
    assert not _sources(bank, "zed-nobody"), "no account, nothing attached"


def test_sleeps_own_stage_five_attaches_at_birth_and_the_tail_has_nothing_left(tmp_path, monkeypatch):
    bank = tmp_path / "birthbank"
    for name in ("entities", "episodes", "inbox"):
        (bank / name).mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)

    async def different(*_a, **_k):
        return "different"

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return ["different" for _ in entries]

    monkeypatch.setattr(er, "_llm_judge_same_entity", different)
    monkeypatch.setattr(er, "_llm_judge_batch", batch)
    for n in (1, 2):
        markdown_parser.write(bank / "episodes" / f"ep_2026-10-01_00{n}.md",
                              {"id": f"ep_2026-10-01_00{n}", "timestamp": "2026-10-01T12:00:00+00:00",
                               "processed": False, "harness": "claude-code"},
                              "user: we talked about Acme Inc today\n\nassistant: noted")
    bank_index.invalidate()
    follows_people.record_read(bank.name, "x", [_acct("Acme Inc", "acme_x"), _acct("Nobody Mentioned", "nobody_x")], DAY1,
                               reached_end=True)
    settings = SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                               sleep_promotion_threshold=2, sleep_resolve_concurrency=1)
    extracted = [{"episode_id": ep, "relationships": [], "entities": [
        {"name": "Acme Inc", "type": "company", "confidence": 0.7, "description": "Acme came up.", "source_episode": ep,
         "source_episode_timestamp": "2026-10-01T12:00:00Z", "named_by_person": True}]}
        for ep in ("ep_2026-10-01_001", "ep_2026-10-01_002")]
    out = asyncio.run(er.resolve(extracted, [], settings))
    (change,) = [c for c in out["changes"] if c.get("action") == "create"]
    conflict_resolver.apply_changes(out["changes"], bank)
    bank_index.invalidate()
    assert [s["ref"] for s in _sources(bank, change["id"])] == [f"{X}/acme_x"]
    assert sorted(p.name for p in (bank / "entities").glob("*.md")) == [f"{change['id']}.md"], "only the mentioned page was made"
    assert follows_people.rematch(bank).paths == [], "nothing left for the night's tail"
    bank_index.invalidate()


# --- Sleep's tail: its own commit -----------------------------------------------------------------------------------------------


def test_the_tail_attaches_in_its_own_commit_under_cicada_and_a_second_night_commits_nothing(bank):
    _read(bank, ["erin_example", "acme_labs_hq"], DAY1, names={"acme_labs_hq": "Acme Labs"})
    asyncio.run(sleep_cycle._rematch_follows_safely(bank))
    log = _git(bank, "log", "-1", "--format=%s%n%b")
    assert log.startswith("Followed accounts") and "Cicada-Author: cicada" in log and "trigger: sleep/follows" in log
    assert "Erin" not in log and "acme_labs_hq" not in log, "a commit message names no one"
    assert _git(bank, "status", "--porcelain") == ""
    head = _git(bank, "rev-parse", "HEAD")
    asyncio.run(sleep_cycle._rematch_follows_safely(bank))
    assert _git(bank, "rev-parse", "HEAD") == head


def test_the_tail_does_nothing_without_a_kept_list_and_skips_a_page_dirty_before_it_ran(bank):
    head = _git(bank, "rev-parse", "HEAD")
    asyncio.run(sleep_cycle._rematch_follows_safely(bank))
    assert _git(bank, "rev-parse", "HEAD") == head
    _read(bank, ["erin_example"], DAY1)
    page = bank / "entities" / "erin-example.md"
    page.write_text(page.read_text() + "\nunsaved edit\n")
    asyncio.run(sleep_cycle._rematch_follows_safely(bank))
    assert not _page_claims(bank, "erin-example") and "unsaved edit" in page.read_text()


def test_the_step_stands_in_the_tail_beside_the_other_rematches():
    import inspect

    source = inspect.getsource(sleep_cycle._run_engine_independent_tail)
    assert source.index("_rematch_contacts_safely(") < source.index("_rematch_follows_safely(") < source.index("_where_to_check_safely(")


# --- names never leave ------------------------------------------------------------------------------------------------------------


def _guard(memory):
    return name_guard.build(memory, web_settle.bank_facts(memory))


def test_a_name_known_only_from_the_follow_list_never_reaches_a_query_and_a_paged_name_keeps_its_own_rule(bank):
    assert name_guard.store_names(bank.name) == []
    _read(bank, ["nora_hidden_x", "acme_labs_hq"], DAY1, names={"nora_hidden_x": "Nora Hidden", "acme_labs_hq": "Acme Labs"})
    assert {"Nora Hidden", "nora_hidden_x"} <= set(name_guard.store_names(bank.name))
    guard = _guard(bank)
    for query in ("Nora Hidden", "nora hidden github", "Hidden Nora", "nora_hidden_x", "norahidden"):
        assert guard.check(query) == "tie", query
    assert guard.clears("Nora Hidden") == "tie"
    # an organisation the bank has a page for is not known only from the list: following is not acquaintance
    assert guard.check("Acme Labs funding") is None


def test_the_agent_that_reads_the_address_book_to_a_model_never_sees_a_follow(bank):
    _read(bank, ["nora_hidden_x"], DAY1, names={"nora_hidden_x": "Nora Hidden"})
    assert "Not in the address book" in settling_agent._read_contacts(bank, "Nora Hidden")
    assert name_guard.store_names(bank.name, include_follows=False) == []


def test_an_unreadable_follow_file_fails_closed(bank):
    people_directory.ensure(bank.name)
    people_directory.path(bank.name, "follows-x.json").write_text("not json")
    with pytest.raises(name_guard.GuardUnreadable):
        name_guard.store_names(bank.name)


# --- the local route, and no other door ----------------------------------------------------------------------------------------


@pytest.fixture
def client(bank):
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_list_route_names_the_accounts_with_their_page_and_answers_not_modified(client, bank):
    _read(bank, ["erin_example", "acme_labs_hq", "zoe_1"], DAY1, names={"acme_labs_hq": "Acme Labs", "zoe_1": "Zoe One"})
    body = client.get("/sources/follows/list").json()
    assert body["total"] == 3 and body["kept"] == 3 and body["site"] == "x" and body["siteName"] == "X"
    rows = {r["handle"]: r for r in body["rows"]}
    assert rows["erin_example"]["page"] == "erin-example" and rows["erin_example"]["proposed"] is False
    assert rows["acme_labs_hq"]["page"] == "acme-labs" and rows["acme_labs_hq"]["proposed"] is True
    assert rows["zoe_1"]["page"] is None and set(rows["zoe_1"]) >= {"id", "name", "handle", "url", "day"}
    assert [r["handle"] for r in client.get("/sources/follows/list?query=zoe").json()["rows"]] == ["zoe_1"]
    assert [r["handle"] for r in client.get("/sources/follows/list?query=ACME%20labs").json()["rows"]] == ["acme_labs_hq"]
    first = client.get("/sources/follows/list")
    again = client.get("/sources/follows/list", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert client.get("/sources/follows/list?site=nowhere").status_code == 404
    assert porcelain(bank) == "", "a read writes nothing"


def test_the_list_route_pages_and_a_demo_bank_refuses(client, bank):
    _read(bank, [f"acct_{i:02d}" for i in range(7)], DAY1)
    page = client.get("/sources/follows/list?limit=3").json()
    assert (len(page["rows"]), page["next"], page["total"]) == (3, 3, 7)
    assert client.get("/sources/follows/list?limit=3&offset=6").json()["next"] is None
    demo_guard.write_manifest(bank)
    assert client.get("/sources/follows/list").status_code == 409


def test_forget_removes_everything_it_holds_and_the_pages_keep_what_they_gained(client, bank):
    _read(bank, ["erin_example"], DAY1)
    follows_people.rematch(bank)
    out = client.delete("/sources/follows/x")
    assert out.status_code == 200 and out.json()["forgotten"] == 1
    assert not follows_people.directory_path(bank.name, "x").exists()
    assert client.get("/sources/follows/list").json()["total"] == 0
    assert [c.valid_from for c in _page_claims(bank, "erin-example")] == [DAY1]
    assert client.delete("/sources/follows/nowhere").status_code == 404


def test_the_routes_are_local_only_and_no_remote_door_carries_them(client):
    assert replica_routes.ROUTES["DELETE /sources/follows/{site}"] == replica_routes.FORWARD
    for path in ("/mcp", "/v1"):
        assert not [r for r in main.app.routes if getattr(r, "path", "").startswith(path) and "follows" in getattr(r, "path", "")]
    remote = json.dumps(sorted(getattr(catalog, "REMOTE_TOOLS", []) or []))
    assert "follows" not in remote and "x-following" not in json.dumps(
        [t for t in getattr(catalog, "TOOLS", [])] if hasattr(catalog, "TOOLS") else [])
    assert "cicada_record_saved_list" in catalog.NEVER_REMOTE, "the record tool is stdio only"


# --- the Sources page's stream --------------------------------------------------------------------------------------------------


def test_the_stream_is_a_following_kind_of_x_counting_the_accounts_followed_now(client, bank):
    reading_settings.update(agent_enabled_=True, acknowledge=True, saved_lists_={KEY: True})
    _read(bank, [f"acct_{i}" for i in range(10)], DAY1)
    _read(bank, [f"acct_{i}" for i in range(9)], DAY2)
    _read(bank, [f"acct_{i}" for i in range(9)], DAY3)       # acct_9 is gone
    assert "following" in source_streams.KINDS
    body = client.get("/sources/streams").json()
    x = next(s for s in body["sources"] if s["id"] == "x")
    stream = next(s for s in x["streams"] if s["id"] == "x.following")
    assert (stream["kind"], stream["how"], stream["state"], stream["count"]) == ("following", "browser", "on", 9)
    assert stream["switch"] == {"setting": "savedLists", "key": KEY} and stream["depth"] == "index"
    assert all(s["kind"] in source_streams.KINDS for s in x["streams"])
