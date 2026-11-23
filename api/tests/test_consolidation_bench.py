"""G148: the consolidation benchmark's scorer reads a bank the way its README says. No model, no Sleep."""
from __future__ import annotations

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
