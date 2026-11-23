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
