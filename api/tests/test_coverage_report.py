"""Vision items 1-2 (2026-10-28): the picture and sources coverage reports — one rung or one reason per page, one
writer per source, ids and enums only, nothing fetched, nothing written. Synthetic pages and placeholder sites."""
from __future__ import annotations

import json

import pytest

from _synthetic_bank import _entity
from api.services import bank_index, coverage_report, fact_sources, logo_service

TODAY = "2026-10-28"


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_FETCH", "on")
    monkeypatch.setenv("CICADA_ALLOW_PERSON_PHOTO_PROXY", "on")
    memory = tmp_path / "banks" / "b"
    (memory / "entities").mkdir(parents=True)
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def site(ref: str, **extra) -> dict:
    return {"ref": ref, "kind": "url", "predicate": "website", "added_at": TODAY, **extra}


def _pages(memory):
    _entity(memory, "acme", type="company", sources=[site("https://acme.example", added_by="user")])
    _entity(memory, "widget", type="tool", sources=[site("https://widget.example", added_by="cicada",
                                                          proposed=True, evidence={"page": True})])
    _entity(memory, "gizmo", type="tool", sources=[site("https://gizmo.example", added_by="agent")])
    _entity(memory, "codehost-thing", type="tool", sources=[site("https://github.com/acme/thing", added_by="user")])
    _entity(memory, "plain-co", type="company")
    _entity(memory, "north-campus", type="location")
    _entity(memory, "bob-example", type="person", sources=[
        {"ref": "https://github.com/bob-example", "kind": "url", "predicate": "github", "added_by": "user"}])
    _entity(memory, "carol-example", type="person", sources=[
        {"ref": "https://x.com/carol_example", "kind": "url", "predicate": "x", "added_by": "cicada",
         "proposed": True, "evidence": {"page": True}}])
    _entity(memory, "dave-example", type="person")
    _entity(memory, "an-idea", type="concept")
    _entity(memory, "alpha-project", type="project",
            sources=[{"ref": "https://github.com/acme/alpha", "kind": "repo", "added_by": "user"}])
    _entity(memory, "a-video", type="media", media={"url": "https://www.youtube.com/watch?v=abcdefghijk"})
    _entity(memory, "a-post", type="media", media={"url": "https://blog.example/post"})
    _entity(memory, "a-paper", type="media", media={"kind": "paper", "url": "https://arxiv.org/abs/2601.00001"})
    _entity(memory, "walled-post", type="media", media={"url": "https://www.linkedin.com/feed/update/1"})
    _entity(memory, "gone", type="company", status="archived")


def test_every_page_gets_one_rung_or_one_reason(bank):
    _pages(bank)
    report = coverage_report.pictures(bank)
    assert report["pages"] == 15, "an archived page is left out unless asked"
    t = report["by_type"]
    assert t["company"]["rungs"] == {"logo:offered": 1} and t["company"]["none"] == {"no_site": 1}
    assert t["tool"]["none"] == {"site_platform": 1, "site_proposed": 1, "site_unconfirmed": 1}
    assert t["location"]["none"] == {"no_site": 1}
    assert t["person"]["rungs"] == {"profile:offered": 1}
    assert t["person"]["none"] == {"identifier_proposed": 1, "no_identifier": 1}
    assert t["concept"]["none"] == {"type_has_no_rung": 1}
    # Owner 2026-10-28 (E): a project with a repository the person gave is offered its owner's mark.
    assert t["project"]["rungs"] == {"logo:offered": 1}
    assert t["media"]["rungs"] == {"thumbnail:offered": 1}
    assert t["media"]["none"] == {"no_preview_declared": 1, "paper": 1, "walled": 1}
    assert report["with_picture"] == sum(r["with_picture"] for r in t.values()) == 4
    assert sum(report["reasons"].values()) + report["with_picture"] == report["pages"]
    assert report["opportunities"] == {}
    assert coverage_report.pictures(bank, include_archived=True)["pages"] == 16


def test_the_persons_choice_of_initials_is_its_own_reason(bank):
    _entity(bank, "eve-example", type="person", picture={"kind": "initials", "added": TODAY})
    report = coverage_report.pictures(bank)
    assert report["reasons"] == {"chose_initials": 1} and report["with_picture"] == 0


def test_a_gate_turned_off_is_the_reason_not_a_picture(bank, monkeypatch):
    _pages(bank)
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    report = coverage_report.pictures(bank)
    assert report["gates"]["logo"] is False and report["reasons"]["gate_off"] == 4   # 2 logos, profile, thumbnail
    assert report["with_picture"] == 0


def test_a_stored_logo_counts_as_drawn_and_its_size_is_bucketed(bank):
    _pages(bank)
    png = (b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" + (32).to_bytes(4, "big") * 2
           + b"\x08\x06\x00\x00\x00" + b"\x00" * 8)
    directory = logo_service.logos_dir("b")
    (directory / "acme.png").write_bytes(png)
    logo_service.write_meta("b", {"acme": {"fetched_at": "2099-01-01T00:00:00+00:00", "domain": "acme.example",
                                           "miss": False, "ext": "png"}})
    report = coverage_report.pictures(bank)
    assert report["by_type"]["company"]["rungs"] == {"logo:stored": 1}
    assert report["logo_sizes"] == {"32_63": 1}


def test_the_report_names_nothing_but_ids_and_only_when_asked(bank):
    _pages(bank)
    plain = json.dumps(coverage_report.pictures(bank)) + json.dumps(coverage_report.sources(bank))
    for leak in ("acme.example", "github.com", "Bob Example", "carol_example", "blog.example"):
        assert leak not in plain
    asked = coverage_report.pictures(bank, ids=True)["ids"]
    assert asked["person/no_identifier"] == ["dave-example"]
    assert all(len(v) <= coverage_report.MAX_IDS for v in asked.values())


@pytest.mark.parametrize("source, writer", [
    ({"added_by": "user"}, "person"),
    ({}, "person"),
    ({"added_by": "claude-code"}, "agent_tool"),
    ({"added_by": "claude-code", "proposed": True, "evidence": {"page": True}}, "agent_proposal"),
    ({"added_by": "claude-web", "origin": "remote:abc"}, "remote_agent"),
    ({"added_by": "agent", "predicate": "website"}, "sleep_stage1_site"),
    ({"added_by": "cicada", "predicate": "website"}, "sleep_site_backfill"),
    ({"added_by": "cicada", "predicate": "website", "verified": {"how": "name+content"}}, "sleep_site_backfill"),
    ({"added_by": "cicada", "predicate": "website", "verified": {"how": "wikidata+name"}}, "sleep_org_site"),
    ({"added_by": "cicada", "predicate": "website", "proposed": True, "evidence": {"page": True}}, "sleep_proposal"),
    ({"added_by": "cicada", "predicate": "linkedin", "accepted": True, "evidence": {"page": True}},
     "sleep_proposal"),
    ({"added_by": "cicada", "predicate": "linkedin", "match": "name"}, "linkedin_import"),
    ({"added_by": "cicada", "ref": "addressbook://card-1", "predicate": "email", "kind": "app"}, "contacts"),
    ({"added_by": "cicada", "ref": "https://doi.org/10.1000/xyz"}, "paper_metadata"),
    ({"added_by": "cicada", "ref": "https://skills.example/one"}, "cicada_other"),
    ({"added_by": "claude-haiku-4-5", "predicate": "located-in"}, "sleep_cited_url"),
])
def test_each_writer_is_told_apart_by_the_fields_it_stamps(source, writer):
    entry = {"ref": "https://example.org/x", "kind": "url", **source}
    assert coverage_report.writer_of(entry) == writer
    assert writer in coverage_report.WRITERS


def test_sources_by_writer_state_role_and_the_pages_with_none(bank):
    _pages(bank)
    _entity(bank, "linked-co", type="company", sources=[
        site("https://linked.example", added_by="cicada", verified={"at": TODAY, "how": "record+name"},
             refresh={"at": TODAY, "outcome": "same"}),
        {"ref": "https://example.org/fact", "kind": "url", "predicate": "located-in", "added_by": "claude-haiku-4-5"}])
    report = coverage_report.sources(bank)
    assert report["by_writer"]["person"] == {"pages": 4, "trusted": 4}
    assert report["by_writer"]["sleep_proposal"] == {"pages": 2, "proposed": 2}
    assert report["by_writer"]["sleep_stage1_site"] == {"pages": 1, "unconfirmed": 1}
    assert report["by_writer"]["sleep_org_site"] == {"pages": 1, "trusted": 1}
    assert report["by_writer"]["sleep_cited_url"] == {"pages": 1, "unconfirmed": 1}
    assert report["recheck"] == {"tracked": 1}
    assert report["without_sources"] == {"media": 4, "company": 1, "concept": 1, "location": 1, "person": 1}
    assert report["by_type"]["company"]["with_trusted"] == 2
    assert set(report["citations"]) == set(coverage_report.CITATION_ORIGINS)


def test_a_web_citation_is_counted_as_a_claim_never_as_a_source(bank):
    body = ("## Summary\nA company.\n\n```claims\n"
            '- {"id": "c1", "text": "Acme is in Lisbon", "subject": "acme", "predicate": "located-in", '
            '"object": "Lisbon", "origin": "web-context", "observer": "external:web"}\n```\n')
    _entity(bank, "acme", type="company", body=body)
    report = coverage_report.sources(bank)
    assert report["citations"]["web-context"] == 1 and report["sources"] == 0
    assert not fact_sources.as_sources(None)
