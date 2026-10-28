"""Ruling 40 — an organisation's own website, found during consolidation, trusted only when Cicada is sure.

Synthetic bank (made-up ``.edu`` / ``.io`` hosts and Wikidata ids; the real services are never asked: every Wikidata
call goes to :class:`FakeWikidata`, every homepage read to :class:`Pages`)."""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import date

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank, _entity
from api import config, main
from api.services import (bank_index, entity_picture, fact_sources, link_enrichment, logo_service, markdown_parser,
                          org_sites, site_sources, source_proposals)
from api.services.link_enrichment import PageIdentity

UNI_BODY = ("## Summary\nNorthwind Example University is a private research university with campuses in Lisbon, "
            "offering engineering, robotics and business programmes.\n\n## Key Facts\n- Located in Portugal\n")
UNI_HOME = PageIdentity("ok", "https://northwind-univ.edu/", "Northwind Example University | Home", "Northwind",
                        "A private research university in Lisbon: engineering, robotics and business programmes.",
                        "Northwind Example University offers engineering, robotics and business programmes. " * 3)


class FakeWikidata:
    """``items``: qid -> {label, description, P31, P856, P17, P625}; ``classes``: qid -> P279 parents; ``labels``: qid ->
    {en: label}; ``search``: query -> [qids]. Every call is recorded."""

    def __init__(self, items=None, search=None, classes=None, labels=None):
        self.items, self.search_map = items or {}, search or {}
        self.classes = {"Q3918": ["Q43229"], "Q7397": [], "Q43229": [], "Q515": ["Q2221906"], **(classes or {})}
        self.labels = labels or {}
        self.calls: list[dict] = []

    async def __call__(self, params):
        self.calls.append(dict(params))
        action = params["action"]
        if action == "wbsearchentities":
            hits = []
            for qid in self.search_map.get(params["search"], []):
                item = self.items[qid]
                hits.append({"id": qid, "label": item["label"], "description": item.get("description", ""),
                             "match": {"type": "label", "text": item["label"]}})
            return {"search": hits}
        if action == "wbgetclaims":
            qid, prop = params["entity"], params["property"]
            if prop == "P279":
                values = self.classes.get(qid, [])
            else:
                values = self.items.get(qid, {}).get(prop, [])
            snaks = [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": v} if v.startswith("Q") else v}}}
                     for v in values]
            return {"claims": {prop: snaks} if snaks else {}}
        if action == "wbgetentities":
            return {"entities": {q: {"labels": {"en": {"value": self.labels.get(q, q)}}}
                                 for q in params["ids"].split("|")}}
        return None

    def searched(self) -> list[str]:
        return [c["search"] for c in self.calls if c["action"] == "wbsearchentities"]


class Pages:
    def __init__(self, answers=None):
        self.answers, self.calls = answers or {}, []

    async def __call__(self, url):
        self.calls.append(url)
        return self.answers.get(url, PageIdentity("failed:http_404"))


def _uni_wikidata(**extra) -> FakeWikidata:
    items = {"Q900001": {"label": "Northwind Example University", "description": "private university in Portugal",
                         "P31": ["Q3918"], "P856": ["https://www.northwind-univ.edu/es/"], "P17": ["Q29"]}}
    items.update(extra.pop("items", {}))
    return FakeWikidata(items=items, search=extra.pop("search", {"Northwind Example University": ["Q900001"]}),
                        labels={"Q29": "Portugal", "Q30": "United States of America"}, **extra)


@pytest.fixture(autouse=True)
def _fresh():
    bank_index.invalidate()
    yield
    bank_index.invalidate()


def _uni_bank(tmp_path, **fm):
    memory = _bank(tmp_path)
    page = {"name": "Northwind Example University", "type": "company", "aliases": ["Northwind"], "body": UNI_BODY}
    page.update(fm)
    _entity(memory, "northwind-example-university", **page)
    subprocess.run(["git", "-C", str(memory), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "seed"], check=True, capture_output=True)
    bank_index.invalidate()
    return memory


def _fm(memory, eid="northwind-example-university"):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter


def _websites(fm):
    return [s for s in fact_sources.as_sources(fm.get("sources")) if s.get("predicate") == "website"]


def _run(memory, wiki, pages, **kw):
    report = site_sources.Report()
    asyncio.run(org_sites.run(memory, report=report, get=wiki, fetch_identity=pages, **kw))
    return report


# ---------- the lookup: trusted only when sure ----------


def test_unique_typed_match_with_a_homepage_that_names_it_is_trusted_and_draws_the_logo(tmp_path):
    memory = _uni_bank(tmp_path)
    wiki, pages = _uni_wikidata(), Pages({"https://northwind-univ.edu": UNI_HOME})
    report = _run(memory, wiki, pages)
    [site] = _websites(_fm(memory))
    assert site["ref"] == "https://northwind-univ.edu" and site["added_by"] == "cicada"
    assert fact_sources.trusted(site) and not fact_sources.is_proposed(site)
    assert site["verified"]["how"] == "wikidata+name" and site["verified"]["item"] == "Q900001"
    assert site["verified"]["why"].startswith("Found by Cicada: official site listed on Wikidata")
    assert logo_service.domain_for(_fm(memory)) == "northwind-univ.edu"
    assert report.paths == ["entities/northwind-example-university.md"] and report.counts["org_trusted"] == 1
    # Only the page's name (and its proper aliases) is ever sent.
    assert set(wiki.searched()) <= {"Northwind Example University", "Northwind"}


def test_ambiguous_match_is_only_a_proposal_in_the_review(tmp_path):
    memory = _uni_bank(tmp_path)
    wiki = _uni_wikidata(items={"Q900002": {"label": "Northwind Example University", "description": "a university",
                                            "P31": ["Q3918"], "P856": ["https://northwind.ac.uk"], "P17": ["Q29"]}},
                         search={"Northwind Example University": ["Q900001", "Q900002"]})
    pages = Pages({"https://northwind-univ.edu": UNI_HOME})
    _run(memory, wiki, pages)
    sites = _websites(_fm(memory))
    assert sites and all(fact_sources.is_proposed(s) and not fact_sources.trusted(s) for s in sites)
    assert {s["evidence"]["reason"] for s in sites} == {"ambiguous"}
    assert logo_service.domain_for(_fm(memory)) is None, "a proposal never draws a picture"
    # …and it joins the one grouped "Confirm N links" review.
    report = source_proposals.propose(memory)
    items = [markdown_parser.parse(memory / p).frontmatter for p in report.paths if p.startswith("inbox/")]
    assert any(i.get("asks") == "sources" and any(r["page"] == "northwind-example-university" for r in i["rows"])
               for i in items)


def test_a_country_the_page_names_that_is_not_the_items_is_a_conflict_and_only_a_proposal(tmp_path):
    memory = _uni_bank(tmp_path)
    wiki = _uni_wikidata()
    wiki.items["Q900001"]["P17"] = ["Q30"]
    _run(memory, wiki, Pages({"https://northwind-univ.edu": UNI_HOME}))
    [site] = _websites(_fm(memory))
    assert fact_sources.is_proposed(site) and site["evidence"]["reason"] == "country_conflict"


def test_a_homepage_that_does_not_name_the_entity_leaves_a_proposal(tmp_path):
    memory = _uni_bank(tmp_path)
    other = PageIdentity("ok", "https://northwind-univ.edu/", "Domain for sale", "", "", "This domain is for sale.")
    _run(memory, _uni_wikidata(), Pages({"https://northwind-univ.edu": other}))
    [site] = _websites(_fm(memory))
    assert fact_sources.is_proposed(site) and site["evidence"]["reason"] == "homepage_unconfirmed"


def test_a_namesake_found_only_through_an_alias_is_nothing(tmp_path):
    memory = _uni_bank(tmp_path)
    wiki = FakeWikidata(items={"Q900009": {"label": "Northwind", "description": "hotel chain in Finland",
                                           "P31": ["Q43229"], "P856": ["https://northwind-hotels.no"]}},
                        search={"Northwind": ["Q900009"]})
    hotel = PageIdentity("ok", "https://northwind-hotels.no/", "Northwind hotels", "Northwind", "Book a room",
                         "Book hotel rooms across Finland. " * 5)
    _run(memory, wiki, Pages({"https://northwind-hotels.no": hotel}))
    assert _websites(_fm(memory)) == []


def test_a_human_or_a_thing_of_another_kind_is_never_matched(tmp_path):
    memory = _uni_bank(tmp_path)
    wiki = FakeWikidata(items={"Q1": {"label": "Northwind Example University", "P31": ["Q5"],
                                      "P856": ["https://northwind-univ.edu"]},
                               "Q2": {"label": "Northwind Example University", "P31": ["Q7397"],
                                      "P856": ["https://northwind-app.io"]}},
                        search={"Northwind Example University": ["Q1", "Q2"]})
    _run(memory, wiki, Pages({"https://northwind-univ.edu": UNI_HOME}))
    assert _websites(_fm(memory)) == []


# ---------- never a person, never removed twice ----------


def test_a_person_page_is_never_looked_up(tmp_path):
    memory = _uni_bank(tmp_path)
    wiki = _uni_wikidata(search={"Bob Example": ["Q900001"], "Northwind Example University": []})
    _run(memory, wiki, Pages())
    assert "Bob Example" not in wiki.searched()
    assert org_sites.skip_reason(_fm(memory, "bob-example"), org_sites.bank_names(memory)) == "type"
    assert "sources" not in _fm(memory, "bob-example")


def test_an_organisation_named_after_a_person_is_never_sent(tmp_path):
    memory = _uni_bank(tmp_path)
    _entity(memory, "bob-example-labs", name="Bob Example Labs", type="company")
    bank_index.invalidate()
    wiki = _uni_wikidata()
    _run(memory, wiki, Pages({"https://northwind-univ.edu": UNI_HOME}))
    assert not any("Bob" in q for q in wiki.searched())
    assert org_sites.skip_reason(_fm(memory, "bob-example-labs"), org_sites.bank_names(memory)) == "person_name"


def test_projects_the_owner_and_private_names_are_out_of_scope(tmp_path):
    memory = _uni_bank(tmp_path)
    bank = org_sites.bank_names(memory)
    assert org_sites.skip_reason({"type": "project", "name": "Alpha Project"}, bank) == "type"
    assert org_sites.skip_reason({"type": "company", "name": "Acme", "owner": True}, bank) == "owner"
    assert org_sites.skip_reason({"type": "location", "name": "university robotics lab"}, bank) == "private_name"
    assert org_sites.skip_reason({"type": "company", "name": "the uni"}, bank) == "private_name"
    assert org_sites.skip_reason({"type": "company", "name": "Alpha's Lab"}, bank) == "private_name"
    assert org_sites.skip_reason({"type": "company", "name": "Acme",
                                  "description": "the user's startup"}, bank) == "own_thing"


def test_a_removed_site_is_never_added_back(tmp_path):
    memory = _uni_bank(tmp_path, sources_removed=[{"ref": "https://northwind-univ.edu", "predicate": "website",
                                                   "by": "user", "at": "2026-10-20"}])
    _run(memory, _uni_wikidata(), Pages({"https://northwind-univ.edu": UNI_HOME}))
    assert _websites(_fm(memory)) == []


def test_the_person_removing_an_auto_trusted_site_is_remembered(tmp_path):
    memory = _uni_bank(tmp_path)
    _run(memory, _uni_wikidata(), Pages({"https://northwind-univ.edu": UNI_HOME}))
    [site] = _websites(_fm(memory))
    fact_sources.change_source(memory, "northwind-example-university", site["ref"], "website",
                               action="remove", actor=fact_sources.USER)
    bank_index.invalidate()
    assert org_sites.has_trusted_site(_fm(memory)) is False
    assert fact_sources.is_tombstoned(_fm(memory), "https://northwind-univ.edu", "website")
    _run(memory, _uni_wikidata(), Pages({"https://northwind-univ.edu": UNI_HOME}), today=date(2027, 1, 1))
    assert _websites(_fm(memory)) == []


# ---------- the record ----------


def test_a_domain_the_page_already_carries_is_trusted_without_a_lookup(tmp_path):
    # The site's own label is the page's name or alias ("<org>.edu" for "<Org>"), as a real university's often is.
    memory = _uni_bank(tmp_path, aliases=["Northwind", "northwind.edu"])
    wiki = _uni_wikidata()
    _run(memory, wiki, Pages({"https://northwind.edu": UNI_HOME}))
    [site] = _websites(_fm(memory))
    assert site["ref"] == "https://northwind.edu"
    assert fact_sources.trusted(site) and site["verified"]["how"] == "record+name"
    assert wiki.calls == [], "the record answered; nothing was sent"


def test_code_and_other_pages_wikilinks_are_not_the_pages_site(tmp_path):
    body = UNI_BODY + "\n## Key Facts\n- Domain: see [[northwind.io]] and `northwind.id` and northwindApp.io\n"
    memory = _uni_bank(tmp_path, body=body)
    assert org_sites.record_candidates(memory, _fm(memory), body) == []


def test_the_persons_own_line_is_enough_when_the_site_blocks_bots(tmp_path):
    memory = _uni_bank(tmp_path, source_episodes=["ep_2026-10-01_001"])
    markdown_parser.write(memory / "episodes" / "ep_2026-10-01_001.md",
                          {"id": "ep_2026-10-01_001", "timestamp": "2026-10-01T09:00:00+00:00", "processed": True},
                          "user: Northwind Example University is at https://www.northwind.edu/apply\n"
                          "assistant: noted")
    bank_index.invalidate()
    wiki = _uni_wikidata()
    _run(memory, wiki, Pages({"https://northwind.edu": PageIdentity("blocked")}))
    [site] = _websites(_fm(memory))
    assert fact_sources.trusted(site) and site["evidence"]["episode"] == "ep_2026-10-01_001"
    assert "your own words" in site["verified"]["why"] and wiki.calls == []


# ---------- the step itself ----------


def test_a_looked_up_page_is_not_asked_again_until_it_is_due(tmp_path):
    memory = _uni_bank(tmp_path)
    wiki = _uni_wikidata(search={})
    _run(memory, wiki, Pages())
    first = len(wiki.calls)
    assert first > 0
    _run(memory, wiki, Pages())
    assert len(wiki.calls) == first, "the cache outside the bank holds the day it was looked up"
    _run(memory, wiki, Pages(), today=date.today().replace(year=date.today().year + 1))
    assert len(wiki.calls) > first


def test_the_lookup_budget_bounds_a_run(tmp_path):
    memory = _uni_bank(tmp_path)
    for i in range(5):
        _entity(memory, f"acme-tool-{i}", name=f"Acme Tool {i}", type="tool")
    bank_index.invalidate()
    wiki = FakeWikidata()
    report = _run(memory, wiki, Pages(), lookup_budget=2)
    assert len(wiki.searched()) <= 2 * (1 + org_sites.MAX_ALIAS_QUERIES)
    assert report.counts.get("org_deferred", 0) >= 3


def test_a_failing_lookup_never_raises(tmp_path):
    memory = _uni_bank(tmp_path)

    async def boom(params):
        raise RuntimeError("down")

    report = _run(memory, boom, Pages())
    assert report.counts.get("org_failed") == 1 and report.paths == []


def test_site_check_never_trusts_a_proposal_behind_the_person(tmp_path):
    memory = _uni_bank(tmp_path, sources=[{"ref": "https://northwind-univ.edu", "kind": "url", "predicate": "website",
                                           "added_by": "cicada", "proposed": True, "evidence": {"page": True}}])

    async def fetch(url, settings=None):
        return UNI_HOME

    report = asyncio.run(site_sources.verify(memory, fetch_fn=fetch))
    assert report.counts.get("fetched", 0) == 0
    assert fact_sources.is_proposed(_websites(_fm(memory))[0])


def test_a_place_draws_its_logo_only_once_it_has_a_trusted_site():
    bare = {"type": "location", "name": "Northwind Campus"}
    assert not logo_service.draws_logo(bare) and not entity_picture.logo_eligible(bare)
    sited = dict(bare, sources=[{"ref": "https://northwind-univ.edu", "kind": "url", "predicate": "website",
                                 "added_by": "cicada", "verified": {"at": "2026-10-26", "how": "wikidata+name"}}])
    assert logo_service.draws_logo(sited) and entity_picture.logo_eligible(sited)
    assert logo_service.domain_for(sited) == "northwind-univ.edu"
    assert not logo_service.draws_logo({"type": "person", "sources": sited["sources"]})


def test_the_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    from api.scripts import org_sites_dry_run

    memory = _uni_bank(tmp_path)
    before = {p: p.read_bytes() for p in memory.rglob("*.md")}
    monkeypatch.setattr(org_sites, "wikidata_get", _uni_wikidata())

    async def identity(url, settings=None):
        return UNI_HOME

    monkeypatch.setattr(link_enrichment, "fetch_identity", identity)
    assert org_sites_dry_run.main(["--bank", str(memory), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    [row] = [r for r in out["rows"] if r["id"] == "northwind-example-university"]
    assert row["outcome"] == "trusted" and row["basis"] == "lookup" and row["logo_domain"] == "northwind-univ.edu"
    assert {p: p.read_bytes() for p in memory.rglob("*.md")} == before


def test_the_dry_run_reports_what_the_step_leaves_alone_and_what_the_site_check_would_trust(tmp_path, monkeypatch,
                                                                                              capsys):
    from api.scripts import org_sites_dry_run

    entry = {"ref": "https://northwind-univ.edu", "kind": "url", "predicate": "website", "added_by": "claude-code",
             "added_at": "2026-10-01"}
    memory = _uni_bank(tmp_path, sources=[entry])
    before = {p: p.read_bytes() for p in memory.rglob("*.md")}
    monkeypatch.setattr(org_sites, "wikidata_get", _uni_wikidata())

    async def identity(url, settings=None):
        return UNI_HOME

    monkeypatch.setattr(link_enrichment, "fetch_identity", identity)
    assert org_sites_dry_run.main(["--bank", str(memory), "--json"]) == 0
    [row] = [r for r in json.loads(capsys.readouterr().out)["rows"] if r["id"] == "northwind-example-university"]
    assert row["finding"] == "trusted" and row["outcome"] == "left_alone" and row["logo_domain"] is None
    assert org_sites_dry_run.main(["--bank", str(memory), "--json", "--site-check"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdicts"] == {"verified": 1} and out["due_tonight"] == {"verified": 1}
    assert {p: p.read_bytes() for p in memory.rglob("*.md")} == before


def test_the_persons_click_runs_the_step_and_commits_as_cicada(tmp_path, monkeypatch):
    memory = _uni_bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    monkeypatch.setattr(org_sites, "wikidata_get", _uni_wikidata())

    async def identity(url, settings=None):
        return UNI_HOME if "northwind-univ.edu" in url else PageIdentity("failed:http_404")

    monkeypatch.setattr(link_enrichment, "fetch_identity", identity)
    try:
        body = TestClient(main.app).post("/maintenance/verify-sites").json()
    finally:
        config.get_settings.cache_clear()
    assert body["org_trusted"] == 1 and "northwind" not in json.dumps(body)
    msg = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], check=True, capture_output=True,
                         text=True).stdout
    assert msg.startswith("Site check ") and "Cicada-Author: cicada" in msg


def test_a_malformed_port_in_pasted_code_is_no_site_and_no_crash():
    # Found on a real bank copy: a person's turn carried "http://localhost:9000`" — urlparse's .port raised.
    assert site_sources.origin_of("http://northwind.edu:9000`") is None
    assert org_sites.site_origin("https://northwind.edu:9000`/x") is None


def test_sleeps_own_proposal_is_trusted_when_a_later_night_finds_the_homepage_names_it(tmp_path):
    # Owner 2026-10-28 (D, amends the review of #476): night 1 the homepage does not answer -> a proposal in the
    # review; a later night it answers and names the page -> ruling 40 trusts the site Sleep itself first proposed, in
    # place (evidence kept, the proposal flag gone), and the review no longer lists it.
    memory = _uni_bank(tmp_path)
    _run(memory, _uni_wikidata(), Pages({"https://northwind-univ.edu": PageIdentity("failed:http_503")}))
    [site] = _websites(_fm(memory))
    assert fact_sources.is_proposed(site) and site["evidence"]["reason"] == "homepage_unconfirmed"
    later = date.today().replace(year=date.today().year + 1)
    _run(memory, _uni_wikidata(), Pages({"https://northwind-univ.edu": UNI_HOME}), today=later)
    [site] = _websites(_fm(memory))
    assert fact_sources.trusted(site) and not fact_sources.is_proposed(site) and "proposed" not in site
    assert site["evidence"]["reason"] == "homepage_unconfirmed" and site["added_by"] == "cicada"
    assert logo_service.domain_for(_fm(memory)) == "northwind-univ.edu"


def test_a_proposal_held_for_another_doubt_still_waits_for_the_person(tmp_path):
    # D settles only the homepage's doubt: a proposal Sleep held because it matched only through an alias (or the
    # record named another site, a namesake, a country conflict) is never trusted behind the person (ruling 36 D5).
    for reason in ("matched_by_alias", "record_names_another_site", "country_conflict", "content_unconfirmed"):
        entry = {"ref": "https://northwind.edu", "kind": "url", "predicate": "website", "added_by": "cicada",
                 "added_at": "2026-10-01", "proposed": True, "evidence": {"page": True, "reason": reason}}
        assert not org_sites.sleeps_own_site(entry), reason
        fm = {"name": "Northwind Example University", "type": "company", "sources": [dict(entry)]}
        finding = org_sites.Finding("northwind-example-university", "Northwind Example University", "company")
        finding.site, finding.trusted, finding.basis, finding.why = "https://northwind.edu", True, "record", "x"
        assert org_sites.apply(fm, finding, "2026-10-28") == 0 and fm["sources"] == [entry], reason


def test_stage_ones_site_is_trusted_in_place_once_its_homepage_names_the_page(tmp_path):
    # Owner 2026-10-28 (D): Stage 1's official site (`propose_site`, added_by agent) is a site Sleep itself first
    # proposed; ruling 40 confirms it in place when the homepage names the page — and never on a homepage that does not.
    entry = {"ref": "https://northwind-univ.edu", "kind": "url", "predicate": "website", "added_by": "agent",
             "added_at": "2026-10-01"}
    memory = _uni_bank(tmp_path, sources=[dict(entry)])
    _run(memory, _uni_wikidata(), Pages({"https://northwind-univ.edu": UNI_HOME}))
    [site] = _websites(_fm(memory))
    assert fact_sources.trusted(site) and site["added_by"] == "agent" and site["ref"] == entry["ref"]
    other = PageIdentity("ok", "https://northwind-univ.edu/", "Domain for sale", "", "", "For sale.")
    memory2 = _uni_bank(tmp_path / "b", sources=[dict(entry)])
    _run(memory2, _uni_wikidata(), Pages({"https://northwind-univ.edu": other}))
    assert _websites(_fm(memory2)) == [entry]


def test_an_identified_agents_or_the_persons_entry_is_never_upgraded_or_marked(tmp_path):
    for i, extra in enumerate(({"added_by": "claude-code"}, {"added_by": "agent", "access": "public"},
                               {"added_by": "cicada", "origin": "remote/app"})):
        entry = {"ref": "https://northwind-univ.edu", "kind": "url", "predicate": "website",
                 "added_at": "2026-10-01", **extra}
        memory = _uni_bank(tmp_path / str(i), sources=[dict(entry)])
        _run(memory, _uni_wikidata(), Pages({"https://northwind-univ.edu": UNI_HOME}))
        assert _websites(_fm(memory)) == [entry], "another writer's entry stays as that writer put it"


def test_cicadas_own_unconfirmed_entry_is_upgraded_in_place(tmp_path):
    entry = {"ref": "https://northwind-univ.edu", "kind": "url", "predicate": "website", "added_by": "cicada",
             "added_at": "2026-10-01", "checked": {"at": "2026-10-02", "outcome": "unconfirmed"}}
    memory = _uni_bank(tmp_path, sources=[dict(entry)])
    _run(memory, _uni_wikidata(), Pages({"https://northwind-univ.edu": UNI_HOME}))
    [site] = _websites(_fm(memory))
    assert fact_sources.trusted(site) and "checked" not in site and site["verified"]["how"] == "wikidata+name"


def test_a_match_only_through_an_alias_is_never_trusted(tmp_path):
    # Measured on a real bank copy: a page whose aliases conflate it with a bigger product got that product's site.
    memory = _uni_bank(tmp_path)
    wiki = FakeWikidata(items={"Q900010": {"label": "Northwind", "description": "private research university, Lisbon",
                                           "P31": ["Q3918"], "P856": ["https://northwind-univ.edu"]}},
                        search={"Northwind": ["Q900010"]})
    _run(memory, wiki, Pages({"https://northwind-univ.edu": UNI_HOME}))
    [site] = _websites(_fm(memory))
    assert fact_sources.is_proposed(site) and site["evidence"]["reason"] == "matched_by_alias"


def test_writing_a_found_site_keeps_the_pages_section_provenance(tmp_path):
    """G118: the site writer touches ``sources`` only, so a page's item links (``section_provenance``) and the body
    they point into come back byte for byte — the disposition `section_writer_inventory.json` declares for it."""
    from api.services import evidence, section_provenance as sp
    from api.services.claims import Evidence

    memory = _uni_bank(tmp_path)
    path = memory / "entities" / "northwind-example-university.md"
    parsed = markdown_parser.parse(path)
    [fact] = sp.scan(parsed.body)["key_facts"]
    ev = Evidence(episode="ep_2026-10-07_001", hash=evidence.body_hash("user: synthetic"), start=0, end=6,
                  kind="user")
    parsed.frontmatter[sp.FIELD] = sp.encode({"key_facts": {fact.key: (fact.text_hash, [ev])}})
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    before = markdown_parser.parse(path)
    assert sp.matched(before.frontmatter, before.body)["key_facts"], "the fixture page carries a matched item link"

    finding = org_sites.Finding("northwind-example-university", "Northwind Example University", "company",
                                site="https://northwind-univ.edu", basis="record", trusted=True,
                                why="Found by Cicada: the page's own record carries it")
    assert org_sites._write_page_locked(memory, "northwind-example-university", finding, "2026-10-26",
                                        site_sources.Report()) == 1
    after = markdown_parser.parse(path)
    assert _websites(after.frontmatter), "the site was written"
    assert after.body == before.body
    assert after.frontmatter[sp.FIELD] == before.frontmatter[sp.FIELD]
    assert sp.matched(after.frontmatter, after.body) == sp.matched(before.frontmatter, before.body)


# ---------- vision item 2 (2026-10-28): what is "on the page itself" ----------


def test_a_domain_in_the_pages_prose_is_on_the_page_itself(tmp_path):
    body = UNI_BODY + "\n## Summary\nA private university; its admissions office answers at northwind.edu.\n"
    memory = _uni_bank(tmp_path, body=body)
    wiki = _uni_wikidata()
    _run(memory, wiki, Pages({"https://northwind.edu": UNI_HOME}))
    [site] = _websites(_fm(memory))
    assert site["ref"] == "https://northwind.edu" and site["verified"]["how"] == "record+name"
    assert wiki.calls == [], "the page's own words answered; nothing was sent"


def test_cicadas_own_unconfirmed_site_named_like_the_page_is_confirmed_from_the_record(tmp_path):
    entry = {"ref": "https://northwind.edu", "kind": "url", "predicate": "website", "added_by": "cicada",
             "added_at": "2026-10-01", "checked": {"at": "2026-10-02", "outcome": "unconfirmed"}}
    memory = _uni_bank(tmp_path, sources=[dict(entry)])
    wiki = _uni_wikidata()
    _run(memory, wiki, Pages({"https://northwind.edu": UNI_HOME}))
    [site] = _websites(_fm(memory))
    assert fact_sources.trusted(site) and site["verified"]["how"] == "record+name" and "checked" not in site
    assert wiki.calls == []


def test_stage_ones_entry_is_a_record_candidate_and_a_named_agents_is_not(tmp_path):
    # Owner 2026-10-28 (D): Stage 1's site is Sleep's own proposal, "on the page itself"; an identified agent's is not.
    for who, expected in (("agent", ["https://northwind.edu"]), ("claude-code", [])):
        entry = {"ref": "https://northwind.edu", "kind": "url", "predicate": "website", "added_by": who,
                 "added_at": "2026-10-01"}
        memory = _uni_bank(tmp_path / who, sources=[entry])
        assert [c.origin for c in org_sites.record_candidates(None, _fm(memory), UNI_BODY)] == expected, who
