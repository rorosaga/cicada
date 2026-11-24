"""G245 (arrival join, Route H, ruling 79 (c)): a first name still HELD below the promotion bar, born as the full name of the
person who newly appeared the same week. It ships deciding and reporting only (`arrival_birth.LIVE` false, separate from the
page route's); the write and its undo are built whole and tested here with the constant forced on IN THE TEST ONLY.

What must be true, each a test below: with the constant false nothing is written and the name stays held exactly as before, while
the night's report (outside every bank) says what it WOULD have done as a birth, by ids, days, hashes and counts, never a name;
forced on, the page is born under the full name with the said form as an alias, the arrival attached only PROPOSED, the held
claims landed, the line gone, in one commit; "Not them" archives the page undoably, puts the line back as it was, and refuses the
pair for every later joiner; the model reads of the two-read veto share ONE bound and ONE cache across both routes. Names invented."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (arrival_birth as ab, arrival_join as aj, arrival_join_write as w, bank_index, contacts_local, fact_sources,
                          linkedin_people, markdown_parser, merge_rejections, page_history, pending_store, person_photo, sleep_cycle)
from api.services.claims import parse_claims
from benchmarks.consolidation import arrival_join_battery as battery

CONNECTED = battery.d(2)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60


class World:
    def __init__(self, tmp_path, monkeypatch, scene: battery.Scene, *, live: bool = True):
        monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
        monkeypatch.setattr(ab, "LIVE", live)            # forced on in the test only: it ships false
        monkeypatch.setattr(aj, "LIVE", False)           # the page route's own switch, left as shipped
        self.mp = monkeypatch
        self.mem = battery.build(tmp_path, scene)
        self.set_judge("fits", "fits")
        self.calls = 0

    def set_judge(self, *answers):
        seq = list(answers)

        async def judge(system, prompt):
            self.calls += 1
            return {"verdict": seq.pop(0) if seq else "unsure", "quote": "", "reason": "x"}

        async def engine(settings, *, user_triggered):
            return judge, ""

        self.mp.setattr(aj, "_engine_judge", engine)

    def git(self, *args) -> str:
        return subprocess.run(["git", "-C", str(self.mem), *args], capture_output=True, text=True).stdout

    def subjects(self) -> list[str]:
        return self.git("log", "--format=%s").splitlines()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def page(self, eid="sam-okafor"):
        return markdown_parser.parse(self.mem / "entities" / f"{eid}.md")

    def line(self, name="Sam"):
        return pending_store.held_line(self.mem, name)

    def night(self, *, judge=("fits", "fits")):
        """The tail's own steps, in the tail's order: refusals, the join step, both rematches, the record."""
        self.set_judge(*judge)
        bank_index.invalidate(self.mem)

        async def go():
            await sleep_cycle._arrival_refusals_safely(self.mem)
            await sleep_cycle._arrival_join_safely(self.mem, None, user_triggered=False, no_model=False)
            await sleep_cycle._rematch_linkedin_safely(self.mem)
            await sleep_cycle._rematch_contacts_safely(self.mem)
            await sleep_cycle._arrival_record_safely(self.mem)

        asyncio.run(go())
        bank_index.invalidate(self.mem)

    def status(self) -> str:
        return self.git("status", "--porcelain")


def scene(**kw) -> battery.Scene:
    base = dict(held=True, holder_claims=[("works-at", "Alpha Robotics"), ("lives-in", "Lisbon")],
                conns=[battery.conn("Sam", "Okafor", CONNECTED, company="Alpha Robotics", position="Founder", headline="Founder")])
    base.update(kw)
    return battery.Scene(**base)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, scene())


@pytest.fixture
def off(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch, scene(), live=False)


# --- it ships deciding and reporting only ------------------------------------------------------------------------------


def test_it_ships_off_and_apart_from_the_page_routes_switch():
    assert ab.LIVE is False and aj.LIVE is False
    assert "LIVE" in vars(ab) and "LIVE" in vars(aj)                  # two names in two modules: two one-line edits flip them


def test_with_the_switch_false_nothing_is_written_and_the_name_stays_held_exactly_as_it_was(off):
    store = (off.mem / "pending_entities.jsonl").read_bytes()
    head = off.head()
    off.night()
    off.night()
    assert off.head() == head and off.status() == ""
    assert (off.mem / "pending_entities.jsonl").read_bytes() == store
    assert not (off.mem / "entities" / "sam-okafor.md").exists() and off.line() is not None


def test_the_report_says_what_it_would_have_done_as_a_birth_and_names_nobody(off):
    off.night()
    report = aj.load_report(off.mem.name)
    item = next(i for i in report["items"] if i["route"] == "birth")
    assert item["decision"] == "would_birth" and item["reason"] == "ok" and item["veto"] == ["fits", "fits"]
    assert item["holder_day"] == battery.d(0) and item["arrival_day"] == CONNECTED and item["gap"] == 2
    assert item["day_from"] == "conversation" and item["fresh"]["connection"]
    assert [n["role"] for n in item["namesakes"]] == ["arrival"]
    assert report["reasons"] == {"would_birth": 1} and report["held_with_namesake"] == 1 and report["birth_live"] is False
    assert item["page"].startswith("held-") and re.fullmatch(r"held-[0-9a-f]{16}", item["page"])
    text = json.dumps(report).lower()
    for secret in ("sam", "okafor", "alpha", "founder", "linkedin", "lisbon"):
        assert not re.search(rf"\b{secret}", text), secret       # a held name is a hash, a row is a hash, nothing is a word


def test_the_report_command_reads_a_birth_apart_from_a_join_and_can_name_the_hash_on_the_terminal_only(off, capsys):
    from api.scripts import arrival_join_report as cmd

    off.night()
    assert cmd.main(["--bank", str(off.mem)]) == 0
    out = capsys.readouterr().out
    assert "WOULD BE BORN" in out and "held first name" in out
    assert cmd.main(["--bank", str(off.mem), "--names"]) == 0
    named = capsys.readouterr().out
    assert "Sam Okafor" in named and "Sam Okafor" not in json.dumps(aj.load_report(off.mem.name))


def test_the_two_switches_are_apart(off, monkeypatch):
    """The page route live and the birth route not: nothing joins; the other way round, the birth is handed back to be written."""
    async def run(**kw):
        off.set_judge("fits", "fits")
        return await aj.run_tail(off.mem, None, user_triggered=False, **kw)

    shut = asyncio.run(run(live=True, birth_live=False))
    assert shut.joins == [] and shut.would_birth == 1
    opened = asyncio.run(run(live=False, birth_live=True))
    assert len(opened.joins) == 1 and opened.joins[0][1].holder.held and opened.would_birth == 0


# --- what blocks it (the decision function's own rules, applied to a held line) ----------------------------------------


@pytest.mark.parametrize("trap_id", [
    "held-two-connections-same-week", "held-stale-directory", "held-company-conflict", "held-same-name-doubt", "held-split-pair",
    "held-agents-reply", "held-untimed-source", "held-tab-group", "held-second-of-a-name", "held-owner-given-name",
    "held-relation-word", "held-known-full-name-page", "held-second-held-person", "held-a-page-of-the-word", "held-day-8",
    "held-fuzzy-namesake-overlaps", "held-namesake-20-days", "held-old-note-edited-this-week", "held-locked-note",
    "held-note-with-no-creation-day", "held-own-words-a-month-apart", "held-held-against-a-page", "held-said-apart", "held-feed-item", "held-calendar-entry", "held-a-save"])
def test_every_block_the_page_route_applies_holds_for_a_held_name(trap_id):
    traps = {t.id: t for t in battery.traps()}
    trap = traps[trap_id]
    outcome, reason = battery.decide_scene(trap.scene)
    assert outcome == "skip" and reason == trap.expect, (trap_id, outcome, reason)


@pytest.mark.parametrize("what", [
    dict(holder_body="user: tell me about the event\nassistant: Sam was there too\n"),                     # an agent's reply
    dict(holder_source="tab-group"), dict(holder_source="agent_relay"),                                      # a filing label, a relay
    dict(conns=[battery.conn("Sam", "Okafor", CONNECTED), battery.conn("Sam", "Adeyemi", battery.d(4))]),   # two namesakes
    dict(connections_read=battery.d(5)),                                                                     # a stale directory
    dict(doubt=True), dict(refused_arrivals=[("sam", "sam okafor")]),                                        # a doubt, a split
    dict(holder="Partner", conns=[battery.conn("Partner", "Okafor", CONNECTED)]),                            # a relation word
    dict(owner="Sam Owner"),                                                                                 # the owner's own name
    dict(conns=[battery.conn("Sam", "Okafor", CONNECTED, company="Beta Logistics")])])                       # a conflict
def test_through_the_real_night_with_the_switch_on_a_blocked_name_writes_nothing_and_stays_held(tmp_path, monkeypatch, what):
    w2 = World(tmp_path, monkeypatch, scene(**what))
    store, head = (w2.mem / "pending_entities.jsonl").read_bytes(), w2.head()
    w2.night()
    assert w2.head() == head and w2.status() == "" and (w2.mem / "pending_entities.jsonl").read_bytes() == store
    assert sorted(p.name for p in (w2.mem / "entities").glob("*.md")) == sorted(
        p.name for p in (w2.mem / "entities").glob("*.md") if "okafor" not in p.name)


def test_a_veto_that_doubts_or_cannot_be_read_is_no_birth(tmp_path, monkeypatch):
    for answers in (("fits", "conflict"), ("unsure", "fits"), ("fits", "unread")):
        w2 = World(tmp_path / "-".join(answers), monkeypatch, scene())
        w2.night(judge=answers)
        assert not (w2.mem / "entities" / "sam-okafor.md").exists() and w2.line() is not None, answers
        assert aj.load_report(w2.mem.name)["items"][0]["reason"] == "veto"


# --- the birth ---------------------------------------------------------------------------------------------------------


def test_the_held_name_is_born_as_the_full_name_with_the_said_form_kept_one_commit(world):
    head = world.head()
    world.night()
    subjects = world.subjects()
    # the connection was attached IN the birth: the LinkedIn rematch that follows has nothing left to write
    assert [s.rsplit(" ", 1)[0] for s in subjects[:2]] == ["Arrival join recorded", "Arrival join"]
    birth = next(line.split()[0] for line in world.git("log", "--format=%h %s").splitlines() if " Arrival join 20" in line)
    changed = world.git("show", "--name-only", "--format=", birth).split()
    assert "entities/sam-okafor.md" in changed and "pending_entities.jsonl" in changed
    assert not any(p.startswith(("entities/sam.md", "inbox/")) for p in changed)
    page = world.page()
    fm = page.frontmatter
    assert fm["name"] == "Sam Okafor" and fm["type"] == "person" and fm["aliases"] == ["Sam"] and fm["status"] == "active"
    assert fm["created"] == battery.d(0) and fm["source_episodes"] == ["ep_%s_001" % battery.d(0)]
    assert not (world.mem / "entities" / "sam.md").exists()
    message = world.git("show", "--format=%B", "-s", birth)
    assert "Cicada-Author: cicada" in message and "trigger: sleep/arrival-join" in message and "2 days apart" in message
    assert "entities/sam-okafor.md: created" in message
    for row_word in ("Alpha Robotics", "Founder", "linkedin"):
        assert row_word not in message
    assert head != world.head()


def test_the_held_line_leaves_and_its_claims_land_on_the_new_page_with_their_evidence(world):
    before = world.line()
    assert {c["id"] for c in before.held_claims} == {"clm_sam_0", "clm_sam_1"}
    world.night()
    assert world.line() is None
    claims = {c.id: c for c in parse_claims(world.page().body)}
    assert {"clm_sam_0", "clm_sam_1"} <= set(claims)
    assert all(c.subject == "sam-okafor" and c.source_episodes for c in (claims["clm_sam_0"], claims["clm_sam_1"]))
    assert "Sam, met at an event." in world.page().body


def test_the_connection_attaches_in_the_same_write_only_as_a_proposal_that_asks_for_no_photo(world):
    world.night()
    sources = [s for s in fact_sources.as_sources(world.page().frontmatter["sources"]) if s["predicate"] == "linkedin"]
    assert len(sources) == 1 and (sources[0]["added_by"], sources[0]["match"]) == ("cicada", "alias")
    assert person_photo.is_own_account(sources[0]) is False and not fact_sources.trusted(sources[0])
    claims = {c.predicate: c for c in parse_claims(world.page().body) if c.observer == linkedin_people.OBSERVER}
    assert claims["works-at"].object == "Alpha Robotics" and claims["connected-on"].valid_from == CONNECTED
    # born WITH it: the birth commit carries the link, not a later rematch
    birth = next(line.split()[0] for line in world.git("log", "--format=%h %s").splitlines() if " Arrival join 20" in line)
    assert "linkedin.com" in world.git("show", f"{birth}:entities/sam-okafor.md")


def test_the_record_names_the_commits_the_claims_and_a_hash_of_each_link_never_a_name(world):
    world.night()
    fm = world.page().frontmatter
    record = w.latest(fm, w.JOINED)
    assert record["birth"] is True and record["state"] == "joined" and "pre" not in record
    assert record["days"] == {"holder": battery.d(0), "arrival": CONNECTED} and record["delta"] == 2
    assert len(record["commits"]) >= 1 and record["commits"][0] == world.git("rev-list", "--reverse", "HEAD", "--", "entities/sam-okafor.md").split()[0]
    assert len(record["claims"]) == 3 and len(record["sources"]) == 1
    text = json.dumps({**record, "claims": []})        # a claim id carries its page's id, which a born page makes of the full name
    for secret in ("Okafor", "Alpha", "Founder", "linkedin.com", "sam-okafor"):
        assert secret not in text, secret
    assert w.name_of(fm, record) == "Sam Okafor"
    assert w.joined_for(world.mem)[record["refs"][0]]["page"] == "sam-okafor"


def test_a_contacts_card_arrival_is_born_and_the_card_attaches_through_its_own_rematch(tmp_path, monkeypatch):
    import base64

    w2 = World(tmp_path, monkeypatch, scene(conns=[], cards=[("Sam", "Okafor", CONNECTED)]))
    contacts_local.save_waiting(w2.mem.name, [{"id": "card-0", "given_name": "Sam", "family_name": "Okafor", "has_organization": True,
                                               "has_email": True, "photo_b64": base64.b64encode(JPEG).decode()}])
    w2.night()
    fm = w2.page().frontmatter
    assert fm["name"] == "Sam Okafor" and fm["aliases"] == ["Sam"]
    refs = {(s["ref"], s["predicate"]) for s in fact_sources.as_sources(fm["sources"])}
    assert ("addressbook://card-0", "works-at") in refs and fm["contacts_photo"]["ext"] == "jpg"
    assert not [s for s in fact_sources.as_sources(fm["sources"]) if s["predicate"] == "linkedin"]
    assert w.latest(fm, w.JOINED)["contacts"] is True


def test_a_second_night_and_a_third_write_nothing(world):
    world.night()
    head = world.head()
    world.night()
    world.night()
    assert world.head() == head and world.status() == ""
    assert aj.load_report(world.mem.name)["items"] == [] or all(i["route"] != "birth" or i["decision"] != "birth" for i in
                                                               aj.load_report(world.mem.name)["items"])


def test_the_birth_is_refused_when_anything_changed_since_the_decision(world):
    bank_index.invalidate(world.mem)
    case = next(c for c in aj.gather(world.mem).cases if c.holder.held)
    decision = aj.decide(case, aj.Veto(("fits", "fits")))
    assert decision.joins
    assert ab.apply_birth(world.mem, aj.Decision(**{**decision.__dict__, "alias_key": "0" * 16}), case) is None      # the name differs
    assert ab.apply_birth(world.mem, decision, case, skip=frozenset({"pending_entities.jsonl"})) is None             # a dirty store
    assert ab.apply_birth(world.mem, decision, case, skip=frozenset({"entities/sam-okafor.md"})) is None
    (world.mem / "entities" / "sam-okafor.md").write_text("---\nname: Sam Okafor\ntype: person\n---\n")                # a page of that id
    assert ab.apply_birth(world.mem, decision, case) is None
    (world.mem / "entities" / "sam-okafor.md").unlink()
    (world.mem / "entities" / "okafor-sam.md").write_text("---\nname: Okafor Sam\ntype: person\naliases: [Sam Okafor]\n---\n")
    bank_index.invalidate(world.mem)
    assert ab.apply_birth(world.mem, decision, case) is None                                                          # the name is another's
    (world.mem / "entities" / "okafor-sam.md").unlink()
    bank_index.invalidate(world.mem)
    pending_store.release(world.mem, ["Sam"])                                                                          # the line is gone
    assert ab.apply_birth(world.mem, decision, case) is None
    assert not (world.mem / "entities" / "sam-okafor.md").exists()


def test_a_name_in_the_persons_own_note_is_born_too(tmp_path, monkeypatch):
    note = {"origin": "apple-notes", "created_at": f"{battery.d(0)}T08:00:00+00:00"}
    w2 = World(tmp_path, monkeypatch, scene(holder_source="apple-notes", holder_extra_fm=note, holder_body="Met Sam at the event\n"))
    w2.night()
    assert w2.page().frontmatter["name"] == "Sam Okafor" and aj.load_report(w2.mem.name)["items"][0]["day_from"] == "note"


# --- the veto's bound and cache are shared across both routes ------------------------------------------------------------


def test_the_nights_model_reads_are_bounded_across_both_routes_and_answered_ones_are_not_read_again(tmp_path, monkeypatch):
    """More candidates than one night's bound: some held names, some pages. The reads stop at the bound together; a second night
    reads only what is left; a third nothing."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(aj, "LIVE", False)
    monkeypatch.setattr(ab, "LIVE", False)
    names = ["Alfa", "Bravo", "Cleo", "Dara", "Elio", "Faye", "Gale", "Hana"]
    monkeypatch.setattr(aj, "MAX_VETOES", 3)
    mem = _many(tmp_path, names)
    reads = []

    async def judge(system, prompt):
        reads.append(1)
        return {"verdict": "fits", "quote": "", "reason": "x"}

    async def night():
        before = len(reads)
        r = await aj.run_tail(mem, None, user_triggered=False, judge=judge)
        return r, (len(reads) - before) // 2

    first, n1 = asyncio.run(night())
    assert first.candidates == len(names) and n1 == 3 and first.skipped == "max_vetoes"
    assert {i["route"] for i in aj.load_report(mem.name)["items"]} == {"birth", "page"}      # both routes were in the one list
    _second, n2 = asyncio.run(night())
    _third, n3 = asyncio.run(night())
    _fourth, n4 = asyncio.run(night())
    assert (n2, n3, n4) == (3, 2, 0)                                                         # cached answers are never read again


def _many(tmp_path, names):
    """One bank, several first names each with one same-week arrival: the first half HELD names, the rest PAGES."""
    from api.services import people_directory
    from api.services.id_utils import sanitize_id

    scenes = battery.Scene(held=True, holder=names[0], conns=[battery.conn(names[0], "Okafor", CONNECTED)])
    mem = battery.build(tmp_path, scenes)
    for i, n in enumerate(names[1:], start=1):
        day = battery.d(0)
        eid = f"ep_{day}_{100 + i}"
        markdown_parser.write(mem / "episodes" / f"{eid}.md", {"id": eid, "timestamp": f"{day}T12:00:00+00:00", "processed": True,
                                                              "harness": "claude-code"}, f"user: I met {n} at the event\n")
        if i % 2:      # a held name
            pending_store.upsert(mem, pending_store.PendingEntity(
                name=n, type="person", description="", source_episode=eid, confidence=0.5, tags=[], history_entries=[],
                heard_in=[{"episode": eid, "timestamp": f"{day}T12:00:00+00:00", "day": day}]))
        else:          # a page
            markdown_parser.write(mem / "entities" / f"{sanitize_id(n)}.md", {
                "name": n, "type": "person", "status": "active", "confidence": 0.8, "created": "2026-10-01",
                "last_referenced": "2026-11-14", "source_episodes": [eid], "related": [], "version": 1}, "## Summary\nA person.\n")
    rows = [linkedin_people.Connection(n, "Okafor", f"{battery.LI}/{n.lower()}-okafor", "", "", CONNECTED, "", "day") for n in names]
    linkedin_people.save_directory(mem.name, rows, "2026-11-24")
    bank_index.invalidate(mem)
    return mem


# --- "Not them" --------------------------------------------------------------------------------------------------------


def test_not_them_archives_the_page_undoably_puts_the_line_back_as_it_was_and_refuses_the_pair(world):
    store_before = (world.mem / "pending_entities.jsonl").read_text()
    world.night()
    assert world.line() is None
    out = w.undo(world.mem, "sam-okafor", before=None)
    fm = world.page().frontmatter
    assert fm["status"] == "archived" and fm["archived_by"]["reason"] == "arrival_birth" and fm["archived_by"]["prior_status"] == "active"
    assert fm["removed_at"] and "aliases" not in fm and fm["name"] == "Sam Okafor"
    assert [r["alias"] for r in fm["aliases_removed"]] == ["Sam"]
    assert not [s for s in fm.get("sources") or [] if s.get("predicate") == "linkedin"]
    assert fact_sources.is_tombstoned(fm, "https://www.linkedin.com/in/sam-okafor", "linkedin")
    assert [c for c in parse_claims(world.page().body) if c.observer == linkedin_people.OBSERVER and not c.valid_to] == []
    record = w.records(fm)[-1]
    assert record["state"] == "undone" and record["undone_on"]
    # the held line is back, byte for byte as the commit before the birth held it
    assert (world.mem / "pending_entities.jsonl").read_text() == store_before
    assert world.line().held_claims and world.line().name == "Sam"
    assert merge_rejections.is_rejected(world.mem, "sam", "sam-okafor")
    message = world.git("log", "-1", "--format=%B")
    assert message.startswith("Undid an arrival join") and "Cicada-Author: user" in message
    for sha in record["commits"]:
        assert f"Undoes: {sha}" in message
    assert out["commit"] == world.head() and "Alpha" not in message


def test_after_not_them_the_name_never_reaches_that_page_and_no_night_births_it_again(world):
    world.night()
    w.undo(world.mem, "sam-okafor", before=None)
    head = world.head()
    world.night()
    world.night()
    assert world.head() == head and world.status() == ""
    assert world.line() is not None and world.page().frontmatter["status"] == "archived"
    from api.services import entity_resolver as er

    assert er._said_different(world.mem, "Sam", "sam-okafor")           # Stage 2 will not join a later "Sam" to the page
    assert aj.load_report(world.mem.name)["items"][0]["decision"] in ("skip",)


def test_a_different_person_of_that_name_can_still_be_born_after_not_them(tmp_path, monkeypatch):
    """The refusal is the PAIR, not the first name: a later arrival of another full name is judged on its own."""
    w2 = World(tmp_path, monkeypatch, scene())
    w2.night()
    w.undo(w2.mem, "sam-okafor", before=None)
    rows = [linkedin_people.Connection("Sam", "Okafor", f"{battery.LI}/sam-okafor", "", "", CONNECTED, "", "day"),
            linkedin_people.Connection("Sam", "Berg", f"{battery.LI}/sam-berg", "", "", battery.d(3), "", "day")]
    linkedin_people.save_directory(w2.mem.name, rows, "2026-11-24")
    w2.night()
    # two arrivals now: exactly-one fails, and the refused one is no arrival; nothing is born
    assert not (w2.mem / "entities" / "sam-berg.md").exists()


def test_if_the_person_took_the_link_or_renamed_the_page_or_it_heard_more_since_the_undo_writes_nothing(world):
    world.night()
    snapshot = (world.mem / "entities" / "sam-okafor.md").read_text()
    head = world.head()
    page = world.page()

    def edit(**changes):
        fm = {**page.frontmatter, **changes}
        markdown_parser.write(world.mem / "entities" / "sam-okafor.md", fm, page.body)

    edit(sources=[{**s, "accepted": True} if s.get("predicate") == "linkedin" else s for s in page.frontmatter["sources"]])
    with pytest.raises(w.UndoError) as took:
        w.undo(world.mem, "sam-okafor", before=None)
    assert took.value.status == 409 and "Nothing was undone" in str(took.value) and "Okafor" not in str(took.value)
    edit(name="Samuel Okafor")
    with pytest.raises(w.UndoError) as renamed:
        w.undo(world.mem, "sam-okafor", before=None)
    assert "the name was changed by you" in str(renamed.value)
    edit(source_episodes=[*page.frontmatter["source_episodes"], "ep_2026-11-20_009"])
    with pytest.raises(w.UndoError) as heard:
        w.undo(world.mem, "sam-okafor", before=None)
    assert "ep_2026-11-20_009" in str(heard.value)
    edit(aliases=["Sammy"])
    with pytest.raises(w.UndoError) as alias:
        w.undo(world.mem, "sam-okafor", before=None)
    assert "taken off by you" in str(alias.value)
    assert world.head() == head
    markdown_parser.write(world.mem / "entities" / "sam-okafor.md", page.frontmatter, page.body)
    assert (world.mem / "entities" / "sam-okafor.md").read_text() == snapshot      # the page as the birth left it can be undone again
    w.undo(world.mem, "sam-okafor", before=None)
    assert world.page().frontmatter["status"] == "archived"


def test_an_undo_twice_or_of_a_name_nobody_born_says_so_and_writes_nothing(world):
    with pytest.raises(w.UndoError) as none:
        w.undo(world.mem, "sam-okafor", before=None)
    assert none.value.status == 404
    world.night()
    w.undo(world.mem, "sam-okafor", before=None)
    head = world.head()
    with pytest.raises(w.UndoError) as again:
        w.undo(world.mem, "sam-okafor", before=None)
    assert again.value.status == 409 and "already" in str(again.value) and world.head() == head


def test_without_the_banks_history_the_undo_writes_nothing_rather_than_losing_the_held_name(world):
    world.night()
    subprocess.run(["rm", "-rf", str(world.mem / ".git")], check=True)
    snapshot = (world.mem / "entities" / "sam-okafor.md").read_text()
    with pytest.raises(w.UndoError) as refused:
        w.undo(world.mem, "sam-okafor", before=None)
    assert "could not be read back" in str(refused.value)
    assert (world.mem / "entities" / "sam-okafor.md").read_text() == snapshot


def test_the_history_marks_the_birth_undoable_until_it_is_taken_back(world):
    world.night()
    rows, _ = asyncio.run(page_history.page("sam-okafor", world.mem))
    joins = [r for r in rows if r.join == "arrival"]
    assert len(joins) == 1 and joins[0].undoable and joins[0].trigger == "sleep/arrival-join"
    assert joins[0].joined_as == "Sam Okafor"
    w.undo(world.mem, "sam-okafor", before=None)
    rows, _ = asyncio.run(page_history.page("sam-okafor", world.mem))
    assert next(r for r in rows if r.join == "arrival").undoable is False and any(r.join == "undo" for r in rows)


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(world.mem))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_same_route_says_not_them_for_a_born_page(world, client):
    world.night()
    ok = client.post("/entities/sam-okafor/arrival-join/undo")
    assert ok.status_code == 200, ok.text
    assert ok.json()["kind"] == "arrival-undo" and ok.json()["commit"] == world.head()
    assert client.post("/entities/sam-okafor/arrival-join/undo").status_code == 409
    assert world.line() is not None


def test_the_connections_list_shows_the_page_a_birth_stands_on(world, client):
    world.night()
    row = client.get("/sources/linkedin-connections/list").json()["rows"][0]
    assert row["page"] == "sam-okafor" and row["joined"]["page"] == "sam-okafor" and row["joined"]["delta"] == 2


# --- the step's place in the tail ----------------------------------------------------------------------------------------


def test_the_tail_step_hands_a_held_name_to_the_birth_and_nothing_else_writes():
    import inspect

    source = inspect.getsource(sleep_cycle._arrival_join_safely)
    assert "arrival_birth.apply_birth" in source and "case.holder.held" in source and "report.joins" in source


def test_a_failed_birth_commit_is_taken_back_whole(world, monkeypatch):
    from api.services import git_service

    async def boom(*a, **k):
        raise RuntimeError("no commit")

    monkeypatch.setattr(git_service, "commit_paths", boom)
    store = (world.mem / "pending_entities.jsonl").read_text()
    world.night()
    assert not (world.mem / "entities" / "sam-okafor.md").exists()
    assert (world.mem / "pending_entities.jsonl").read_text() == store and world.status() == ""
