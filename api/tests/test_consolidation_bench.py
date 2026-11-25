"""G148: the consolidation benchmark's scorer reads a bank the way its README says. No model, no Sleep."""
from __future__ import annotations

import json
from datetime import date

from benchmarks.consolidation import run as bench

CLOCK = date(2026, 11, 23)


def _claim(text, *, page="ines-varga", observer="ines-varga", valid_to=None, superseded_by=None, valid_from=None,
           start=0, end=10):
    return {"page": page, "id": f"c{abs(hash(text)) % 10_000}", "text": text, "subject": page, "predicate": "",
            "object": "", "observer": observer, "valid_from": valid_from, "valid_to": valid_to,
            "superseded_by": superseded_by, "source_episodes": ["ep_2026-10-01_001"],
            "evidence": [{"episode": "ep_2026-10-01_001", "kind": "user", "start": start, "end": end}]}


def _page(pid, name, aliases=(), owner=False, type_="person"):
    return {"id": pid, "name": name, "aliases": list(aliases), "owner": owner, "type": type_, "decay_class": "durable",
            "prose": ""}


def test_fixture_renders_every_day_token_and_spells_dates():
    fx = bench.load_fixture()
    for conv in fx["conversations"]:
        assert all("{day:" not in t for t in bench.render_turns(conv, CLOCK))
    spanish = next(c for c in fx["conversations"] if c["id"] == "c05" and c.get("edit"))
    assert "12 de diciembre" in bench.render_turns(spanish, CLOCK)[2]
    assert bench.matches("lucia moves on 2026-12-12", bench.expand_groups([["lucía"], "{date:+19}"], CLOCK))


def test_scorer_tells_a_clean_update_from_a_stale_one_and_catches_a_declined_suggestion(tmp_path):
    fx = bench.load_fixture()
    claims = [
        _claim("Ines works at Kestrel Robotics as a senior data engineer"),
        _claim("Ines works at Halvard Analytics as a data engineer", valid_to="2026-11-03"),
        _claim("Half marathon goal under 1:45"),
        _claim("Half marathon goal under 1:50"),                       # never closed: both current
        _claim("Loomwright is written in Rust"),
        _claim("Passed the AWS data engineering certification", valid_from="2026-10-09"),
    ]
    pages = [_page("ines-varga", "Ines Varga", owner=True), _page("teodor-brandt", "Teodor Brandt", ["Teo"]),
             _page("sam-okafor", "Sam Okafor"), _page("pell", "Dr. Pell")]
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "x.md").write_text("nothing secret here")
    snap = {"model": "t", "clock": CLOCK.isoformat(), "claims": claims, "pages": pages, "questions": [],
            "phases": [], "episodes_unprocessed": 0}
    s = bench.score(snap, tmp_path, fx)
    verdict = {u["id"]: u["verdict"] for u in s["updates"]}
    assert verdict["U1"] == "correct" and verdict["U2"] == "both_current" and verdict["U3"] == "missing"
    assert next(f for f in s["forbid"] if f["id"] == "F1")["ok"] is False
    assert next(d for d in s["dated"] if d["id"] == "D1")["ok"] is True
    assert all(p["ok"] for p in s["people"])
    assert next(n for n in s["pages"]["not_expected"] if n["term"] == "pell")["ok"] is False
    assert s["integrity"]["secret_leaked_to"] == [] and s["integrity"]["span_rate"] == 1.0


def test_a_meeting_is_staged_by_the_real_parser_and_only_you_lines_are_the_persons():
    meeting = next(c for c in bench.load_fixture("noor")["conversations"] if c.get("kind") == "meeting")
    (draft,) = bench._drafts([meeting], CLOCK)
    speakers = [t.speaker for t in draft.turns]
    assert "user" in speakers and any(s.startswith("speaker:") for s in speakers)
    assert all(s in ("user", "assistant") or s.startswith("speaker:") for s in speakers)


def test_a_number_matches_whole_and_dates_follow_the_conversations_language():
    assert not bench.matches("valid from 2026-09-26", [["20"]])
    assert bench.matches("cards sold: 20", [["20"]])
    french = next(c for c in bench.load_fixture("noor")["conversations"] if c["id"] == "n02")
    assert bench._lang(bench.render_turns(french, CLOCK)) == "fr"


def test_two_people_one_page_holds_is_caught_by_what_is_said_of_each(tmp_path):
    fx = bench.load_fixture("noor")
    claims = [_claim("Marc moves to Berlin", page="marc"), _claim("Marc works in Annecy as a carpenter", page="marc")]
    for c in claims:
        c["subject"] = "marc"
    (tmp_path / "entities").mkdir()
    snap = {"model": "t", "clock": CLOCK.isoformat(), "claims": claims,
            "pages": [_page("noor-haddad", "Noor Haddad", owner=True), _page("marc", "Marc")],
            "questions": [], "phases": [], "episodes_unprocessed": 0}
    merged = next(p for p in bench.score(snap, tmp_path, fx)["people"] if p["id"] == "M2")
    assert merged["ok"] is False and merged["pages"] == ["marc"]


def test_planted_errors_are_plausible_and_compare_reads_folders(tmp_path):
    claims = [_claim("Loomwright beta users: 120", page="loomwright"),
              _claim("Lucía move date: 2026-12-12", page="lucía"),
              {**_claim("Ines works at Halvard", page="ines-varga"), "object": "halvard"}]
    pages = [_page("ines-varga", "Ines Varga", owner=True), {**_page("halvard", "Halvard"), "type": "company"},
             {**_page("kestrel", "Kestrel"), "type": "company"}, _page("tomas", "Tomas")]
    planted = {p["kind"]: p["text"] for p in bench._plant(claims, pages, 3)}
    assert planted == {"date": "Lucía move date: 2026-12-13", "number": "Loomwright beta users: 144",
                       "swap": "Ines works at Kestrel"}, "a company only ever swaps for a company"
    for name, value in (("key-sonnet-r1", 30), ("key-sonnet-r2", 31), ("key-haiku-r1", 22)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "score.json").write_text(
            '{"summary": {"points_claim": %d}, "people": {}}' % value)
    out = bench.compare(tmp_path, "key-sonnet", "key-haiku")
    assert "| points_claim | 30.5 | 22 | yes |" in out


def test_a_role_must_read_true_as_written(tmp_path):
    """"My landlord Mr Duarte": the owner as the landlord of him, or him as having the owner for a landlord, is wrong."""
    fx = bench.load_fixture()
    pages = [_page("ines-varga", "Ines Varga", owner=True), _page("mr-duarte", "Mr. Duarte")]

    def relation(subject, predicate, obj, **kw):
        return {**_claim(f"{subject} {predicate} {obj}", page=subject, **kw), "predicate": predicate, "object": obj}

    def verdict(*claims):
        (tmp_path / "entities").mkdir(exist_ok=True)
        snap = {"model": "t", "clock": CLOCK.isoformat(), "claims": list(claims), "pages": pages, "questions": [],
                "phases": [], "episodes_unprocessed": 0}
        return next(r for r in bench.score(snap, tmp_path, fx)["roles"] if r["id"] == "R2")["ok"]

    assert verdict(relation("mr-duarte", "landlord-of", "ines-varga"))
    assert verdict(relation("ines-varga", "has-landlord", "mr-duarte"))
    assert verdict(relation("ines-varga", "tenant-of", "mr-duarte"))
    assert not verdict(relation("ines-varga", "landlord-of", "mr-duarte"))
    assert not verdict(relation("mr-duarte", "has-landlord", "ines-varga"))
    assert verdict(relation("ines-varga", "landlord-of", "mr-duarte", valid_to="2026-11-01"))   # closed: not held


# --- does the right thing fade? (decay class; benchmarks/consolidation/fading.py) --------------------------------------

def _bank_page(bank, pid, *, cls, confidence, status="active", type_="person", last="2026-11-14", eps=3):
    from api.services import markdown_parser

    (bank / "entities").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(bank / "entities" / f"{pid}.md", {
        "name": pid.title(), "type": type_, "status": status, "confidence": confidence, "created": "2026-10-01",
        "last_referenced": last, "decayed_through": "2026-11-23", "learned_on": "2026-11-23", "decay_class": cls,
        "decay_rate": {"volatile": 0.15, "active": 0.05, "durable": 0.02}[cls],
        "source_episodes": [f"ep_2026-10-{day:02d}_001" for day in (1, 9, 20)][:eps], "aliases": []}, f"# {pid}\n")


def test_fading_gold_is_about_roles_and_every_fixture_carries_it():
    for person in bench.PEOPLE:
        gold = bench.load_fixture(person)["gold"]["fading"]
        assert gold["keeps"] and gold["lasting"], person
        assert not any(isinstance(v, (int, float)) for row in gold.get("outranks", []) for v in row.values())


def test_fading_order_and_keeps_read_the_stored_state(tmp_path):
    from benchmarks.consolidation import fading

    pages = [_page("ines-varga", "Ines Varga", owner=True), _page("kestrel", "Kestrel", type_="company"),
             _page("halvard", "Halvard", type_="company"), _page("ribeira", "Ribeira", type_="location")]
    fm = {"kestrel": {"status": "decaying", "confidence": 0.39, "decay_class": "volatile"},
          "halvard": {"status": "active", "confidence": 0.59, "decay_class": "active"},
          "ribeira": {"status": "active", "confidence": 0.3}}
    gold = {"keeps": ["kestrel", "tomas"], "outranks": [{"above": "kestrel", "below": "halvard"},
                                                          {"above": "kestrel", "below": "ribeira"},
                                                          {"above": "tomas", "below": "ribeira"}]}
    state = fading.score_state(pages, [], fm, gold)
    assert [k["ok"] for k in state["keeps"]] == [False, False]   # kestrel is under the line; tomas has no page
    assert [o["ok"] for o in state["order"]] == [False, True, False]   # the held job under the left one; no upper page


def test_two_pages_with_one_name_are_told_apart_by_what_each_says(tmp_path):
    from benchmarks.consolidation import fading

    pages = [{**_page("marc", "Marc"), "prose": "Colleague, moving to Berlin."},
             {**_page("marc-2", "Marc"), "prose": "Carpenter in Annecy."}]
    assert [p["id"] for p in fading.find(pages, [], {"name": "marc", "about": "berlin"})] == ["marc"]
    assert [p["id"] for p in fading.find(pages, [], {"name": "marc", "about": ["carpenter"]})] == ["marc-2"]


def test_silence_probe_ages_a_copy_and_a_volatile_person_is_asked_before_an_active_one(tmp_path):
    from benchmarks.consolidation import fading

    bank = tmp_path / "bank"
    _bank_page(bank, "sister", cls="volatile", confidence=0.7)
    _bank_page(bank, "employer", cls="active", confidence=0.7, type_="company")
    before = {p.name: p.read_text() for p in (bank / "entities").glob("*.md")}
    out = fading.probe_silence(bank, CLOCK)
    assert {p.name: p.read_text() for p in (bank / "entities").glob("*.md")} == before   # the bank is never touched
    six_weeks = out["42"]
    assert "sister" in six_weeks["below_line"] and "employer" not in six_weeks["below_line"]
    assert "sister" in set(six_weeks["asked"]) | set(six_weeks["archived"])


def test_a_current_claim_that_says_the_old_value_was_replaced_is_not_holding_it(tmp_path):
    """U3 in a key run: the join closed the old value, and the new claim's own words ("..., replacing Python") made the
    stale test see the old value as current. A claim that says the old value ended is the change itself."""
    fx = bench.load_fixture()
    pages = [_page("ines-varga", "Ines Varga", owner=True)]
    (tmp_path / "entities").mkdir(exist_ok=True)

    def verdict(*texts):
        snap = {"model": "t", "clock": CLOCK.isoformat(), "claims": [_claim(t) for t in texts], "pages": pages,
                "questions": [], "phases": [], "episodes_unprocessed": 0}
        return next(u["verdict"] for u in bench.score(snap, tmp_path, fx)["updates"] if u["id"] == "U3")

    assert verdict("Loomwright core language: TypeScript (browser), replacing Python") == "correct"
    assert verdict("Loomwright now runs in TypeScript, and the Python version was dropped entirely") == "correct"
    assert verdict("Loomwright core language: TypeScript", "Loomwright implementation language: Python") == "both_current"
    # a claim that merely holds the old value beside something it replaced is still the old value
    assert verdict("Loomwright core language: TypeScript", "Loomwright uses Python, replacing Perl") == "both_current"


def test_one_person_must_stay_one_a_second_page_or_a_held_titled_line_is_a_false_split(tmp_path):
    fx = {"people": {"one": [{"id": "O4", "names": ["idris"], "why": "x"}]}}
    gold = {"people": {"same": [], "apart": [], "one": fx["people"]["one"]}}

    def check(pages, lines):
        (tmp_path / "pending_entities.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
        snap = {"model": "t", "clock": CLOCK.isoformat(), "claims": [], "pages": pages, "questions": [], "phases": [],
                "episodes_unprocessed": 0}
        fixture = {**bench.load_fixture("noor"), "gold": {**bench.load_fixture("noor")["gold"], "people": gold["people"]}}
        return next(r for r in bench.score(snap, tmp_path, fixture)["one_person"] if r["id"] == "O4")

    owner = _page("noor-haddad", "Noor Haddad", owner=True)
    assert check([owner, _page("idris", "Idris")], [])["ok"] is True
    # a held line below the promotion bar that carries a title is a second person nobody sees (the stored `idris-2`)
    split_line = {"name": "idris-2", "type": "person", "title": "Idris"}
    held = check([owner, _page("idris", "Idris")], [split_line, {"name": "Fujifilm", "type": "tool"}])
    assert held["ok"] is False and held["held_lines"] == ["idris-2"]
    two_pages = check([owner, _page("idris", "Idris"), _page("idris-2", "Idris")], [])
    assert two_pages["ok"] is False and two_pages["pages"] == ["idris", "idris-2"]
    # a plain held line (no title) is the one person, held; a project of the same name is no person
    assert check([owner], [{"name": "idris", "type": "person"}])["ok"] is True
    assert check([owner, _page("idris", "Idris"), _page("idris-2", "Idris", type_="project")], [])["ok"] is True


def test_a_claim_held_under_a_waiting_name_is_not_on_a_page_but_is_not_lost(tmp_path):
    """Sam Reyes is one conversation: below the promotion bar, so what Stage 1 wrote of him waits in the pending store.
    The scorer keeps ``claim`` as "on a page" and reports the held one apart, never as prose."""
    fx = bench.load_fixture()
    held = {"name": "Sam Reyes", "type": "person", "held_claims": [
        {"id": "clm_1", "text": "Sam Reyes cousin of Ines Varga", "subject": "sam-reyes", "predicate": "cousin-of",
         "object": "ines-varga", "object_kind": "node"}]}
    (tmp_path / "pending_entities.jsonl").write_text(json.dumps(held) + "\n")
    (tmp_path / "entities").mkdir()
    snap = {"model": "t", "clock": CLOCK.isoformat(), "claims": [_claim("Ines works at Kestrel Robotics")],
            "pages": [_page("ines-varga", "Ines Varga", owner=True)], "questions": [], "phases": [],
            "episodes_unprocessed": 0}
    s = bench.score(snap, tmp_path, fx)
    p22 = next(p for p in s["points"] if p["id"] == "P22")
    assert (p22["claim"], p22["held_waiting"]) == (False, True) and "cousin" in p22["matched"][0]
    assert s["summary"]["points_held"] == 1 and s["summary"]["points_claim"] == 0
    # a claim on a page is never also counted as held
    snap["claims"].append(_claim("Sam Reyes cousin of Ines Varga"))
    p22 = next(p for p in bench.score(snap, tmp_path, fx)["points"] if p["id"] == "P22")
    assert (p22["claim"], p22["held_waiting"]) == (True, False)


def _claim_on(subject, text, *, observer="ines-varga"):
    c = _claim(text, page=subject, observer=observer)
    c["subject"] = subject
    return c


def test_an_owner_update_ignores_a_colleagues_claim_naming_the_same_employer(tmp_path):
    """U1 is the owner's job change: a colleague's own true "works at <the old employer>" is neither value."""
    fx = bench.load_fixture()
    assert next(u for u in fx["gold"]["updates"] if u["id"] == "U1").get("on_owner") is True
    (tmp_path / "entities").mkdir()
    claims = [_claim_on("ines-varga", "Ines works at Kestrel Robotics as a senior data engineer"),
              _claim_on("ines-varga", "Ines works at Halvard Analytics", ) | {"valid_to": "2026-11-03"},
              _claim_on("priya", "Priya works at Halvard Analytics")]
    pages = [_page("ines-varga", "Ines Varga", owner=True), _page("priya", "Priya")]
    snap = {"model": "t", "clock": CLOCK.isoformat(), "claims": claims, "pages": pages, "questions": [], "phases": [],
            "episodes_unprocessed": 0}
    u1 = next(u for u in bench.score(snap, tmp_path, fx)["updates"] if u["id"] == "U1")
    assert u1["verdict"] == "correct" and u1["stale_current"] == []
    # the owner's own old job, still open, is still caught
    claims[1] = _claim_on("ines-varga", "Ines works at Halvard Analytics")
    u1 = next(u for u in bench.score(snap, tmp_path, fx)["updates"] if u["id"] == "U1")
    assert u1["verdict"] == "both_current"


def test_a_claim_that_records_a_refusal_with_a_bare_no_is_not_a_violation(tmp_path):
    fx = bench.load_fixture()
    (tmp_path / "entities").mkdir()
    refused = _claim_on("half-marathon", "Half marathon racing shoes: no carbon-plated shoes")
    taken = _claim_on("half-marathon", "Half marathon racing shoes: carbon-plated shoes")
    snap = {"model": "t", "clock": CLOCK.isoformat(), "claims": [refused], "pages": [_page("ines-varga", "Ines", owner=True)],
            "questions": [], "phases": [], "episodes_unprocessed": 0}
    f6 = lambda: next(f for f in bench.score(snap, tmp_path, fx)["forbid"] if f["id"] == "F6")  # noqa: E731
    assert f6()["ok"] is True
    snap["claims"] = [taken]
    assert f6()["ok"] is False


def test_stage_ones_standing_facts_rule_covers_what_the_user_says_of_someone_else():
    from api.services.entity_extractor import EXTRACTION_SYSTEM_PROMPT as prompt

    assert "about themselves or about someone else" in prompt
    assert "only when they said it of" not in prompt   # the sentence the model read as "the owner's facts alone"


def test_a_relative_date_held_under_a_waiting_name_is_right_and_said_so(tmp_path):
    """A one-off thing named once ("the vet visit is in ten days", the visit its own entity) is below the promotion bar,
    so the claim that dates it waits in the pending store. The day is resolved all the same: ``ok``, with
    ``held_waiting`` saying it is not on a page. A wrong day held is still wrong; a page's right day is never "held"."""
    fx = bench.load_fixture()
    fx["gold"]["dated"] = [{"id": "X1", "why": "invented: a day ahead", "says": ["vet"], "date": -3},
                           {"id": "X2", "why": "invented: a month", "says": ["vendange"], "month_of": 9}]
    held = {"name": "Vet visit", "type": "concept", "held_claims": [
        {"id": "clm_v", "text": "Vet visit date: 2026-11-20", "subject": "vet-visit", "predicate": "value-of-date",
         "object": "2026-11-20", "object_kind": "literal", "valid_from": "2026-11-10"},
        {"id": "clm_w", "text": "Vendange trip month: septembre", "subject": "vendange-trip", "predicate": "value-of-month",
         "object": "septembre", "object_kind": "literal", "valid_from": "2026-08-01"}]}
    (tmp_path / "pending_entities.jsonl").write_text(json.dumps(held) + "\n")
    (tmp_path / "entities").mkdir()
    snap = {"model": "t", "clock": CLOCK.isoformat(), "claims": [_claim("Ines works at Kestrel Robotics")],
            "pages": [_page("ines-varga", "Ines Varga", owner=True)], "questions": [], "phases": [],
            "episodes_unprocessed": 0}
    s = bench.score(snap, tmp_path, fx)
    x1, x2 = (next(d for d in s["dated"] if d["id"] == i) for i in ("X1", "X2"))
    assert (x1["ok"], x1["on_page"], x1["held_waiting"], x1["want"]) == (True, False, True, "2026-11-20")
    assert (x2["ok"], x2["held_waiting"]) == (True, True)
    assert s["summary"]["dated_ok"] == 2 and s["summary"]["dated_held"] == 2
    # the wrong day held stays wrong
    held["held_claims"][0].update(object="2026-11-26", text="Vet visit date: 2026-11-26")
    (tmp_path / "pending_entities.jsonl").write_text(json.dumps(held) + "\n")
    x1 = next(d for d in bench.score(snap, tmp_path, fx)["dated"] if d["id"] == "X1")
    assert (x1["ok"], x1["held_days"]) == (False, ["2026-11-10", "2026-11-26"])
    # the right day on a page is on the page, never counted as held
    snap["claims"].append({**_claim("Vet visit date: 2026-11-20", page="ines-varga"), "object": "2026-11-20"})
    x1 = next(d for d in bench.score(snap, tmp_path, fx)["dated"] if d["id"] == "X1")
    assert (x1["ok"], x1["on_page"], x1["held_waiting"]) == (True, True, False)
