"""G61 S3-b — websites verified on Cicada's own rail, pictures drawn only from a trusted site.

Synthetic bank (acme-example, widget-example; made-up `.io` hosts, because `example` hosts are never public); git is real; NOTHING reaches a network: every fetch
is an injected fake, and the ones that must never happen assert they did not."""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import date

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank, _entity
from api import config, main
from api.services import (bank_index, conflict_resolver, engine_schemas, entity_extractor, fact_sources, link_enrichment,
                          logo_service, markdown_parser, site_sources, sleep_cycle)
from api.services.link_enrichment import PageIdentity

SUMMARY = ("## Summary\nAcme Example builds inference infrastructure for machine learning models, with managed "
           "clusters and observability dashboards.\n\n## Key Facts\n- Offers serverless deployment pipelines\n")
GOOD = PageIdentity("ok", "https://acme-inference.io/", "Acme Example | Inference infrastructure", "Acme Example",
                    "Managed clusters and observability dashboards for machine learning models.",
                    "Acme Example runs inference infrastructure: serverless deployment pipelines, managed clusters, "
                    "observability dashboards and support for machine learning models. " * 3)
SHOW = PageIdentity("ok", "https://acme-inference.io/", "Acme Example fireworks", "",
                    "Pyrotechnic displays for weddings and festivals",
                    "Acme Example fireworks: book a pyrotechnic display for your wedding, festival or civic event. " * 4)
THIN = PageIdentity("ok", "https://acme-inference.io/", "Acme Example", "Acme Example", "", "Loading")


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _fm(memory, eid="acme-example"):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md").frontmatter


def _site_bank(tmp_path, *, sources=None, links=None, claim_site=None, type_="company"):
    memory = _bank(tmp_path)
    fm = {"type": type_}
    if sources is not None:
        fm["sources"] = sources
    body = SUMMARY + (f"\n## Links\n{links}\n" if links else "")
    if claim_site:
        from api.services.claims import Claim, write_claims

        body = write_claims(body, [Claim(id="clm_w", text="Acme's site", subject="acme-example", predicate="website",
                                         object=claim_site, object_kind="literal", observer="agent",
                                         authored_by="claude-code", origin="mcp")])
    _entity(memory, "acme-example", name="Acme Example", body=body, **fm)
    subprocess.run(["git", "-C", str(memory), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "seed"], check=True, capture_output=True)
    bank_index.invalidate()
    return memory


def _proposed(ref="https://acme-inference.io", by="agent", **extra):
    return {"ref": ref, "kind": "url", "predicate": "website", "added_by": by, "added_at": "2026-09-30", **extra}


class Fetcher:
    def __init__(self, answers=None, default=None):
        self.calls, self.answers, self.default = [], answers or {}, default

    async def __call__(self, url, settings=None):
        self.calls.append(url)
        return self.answers.get(url, self.default or PageIdentity("failed:http_404"))


@pytest.fixture(autouse=True)
def _fresh():
    bank_index.invalidate()
    yield
    bank_index.invalidate()


# ---------- Stage 1: the optional website ----------


@pytest.mark.parametrize("type_,value,kept", [
    ("company", "https://www.acme-inference.io/about?x=1#y", "https://acme-inference.io"),
    ("tool", "http://acme-inference.io", "https://acme-inference.io"),
    ("project", "acme-inference.io", "https://acme-inference.io"),
    ("person", "https://acme-inference.io", None), ("concept", "https://acme-inference.io", None),
    ("skill", "https://acme-inference.io", None), ("location", "https://acme-inference.io", None),
    ("company", "https://github.com/acme/widget", None), ("company", "https://www.linkedin.com/company/acme", None),
    ("company", "https://en.wikipedia.org/wiki/Acme", None), ("company", "https://acme.medium.com", None),
    ("company", "https://192.168.1.5/", None), ("company", "https://intranet/", None),
    ("company", "https://acme-inference.io:8443/", None), ("company", "ftp://acme-inference.io", None),
    ("company", "", None), ("company", 5, None), ("company", None, None),
])
def test_sanitize_website_matrix(type_, value, kept):
    entity = {"name": "Acme", "type": type_, "website": value}
    entity_extractor.sanitize_website(entity)
    assert entity.get("website") == kept and (kept is not None or "website" not in entity)


def test_the_extraction_schema_declares_website_strict_and_not():
    for strict in (True, False):
        props = engine_schemas.extraction_schema(strict=strict)
        props = props["properties"]["entities"]["items"]["properties"]
        assert "website" in props
    strict = engine_schemas.extraction_schema(strict=True)["properties"]["entities"]["items"]
    assert "website" in strict["required"], "strict mode names every property (nullable)"
    assert "website" in entity_extractor.EXTRACTION_SYSTEM_PROMPT and "NEVER" not in entity_extractor.EXTRACTION_SYSTEM_PROMPT.split("WEBSITE")[1].split("EXTRACTION GUIDELINES")[0]


def _create(tmp_path, entity):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    conflict_resolver.apply_changes([{
        "id": "acme-example", "action": "create", "entity": entity, "source_episodes": ["ep_2026-09-30_001"],
        "timestamps": ["2026-09-30"]}], memory)
    return memory


def test_the_create_branch_writes_an_unverified_site_and_nothing_else(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("apply_changes never touches the network")

    monkeypatch.setattr(link_enrichment, "_stream_html", boom)
    entity = {"name": "Acme Example", "type": "company", "summary": "Builds things.", "website": "https://acme-inference.io",
              "confidence": 0.7}
    memory = _create(tmp_path, entity)
    fm = _fm(memory)
    (src,) = fm["sources"]
    assert (src["ref"], src["predicate"], src["kind"], src["added_by"]) == ("https://acme-inference.io", "website", "url", "agent")
    assert "verified" not in src and not fact_sources.trusted(src)
    assert fm["decay_class"] in ("active", "durable", "volatile"), "never evergreen"
    assert logo_service.domain_for(fm, "") is None, "unverified draws no mark"


def test_the_create_branch_ignores_a_site_for_other_types(tmp_path):
    memory = _create(tmp_path, {"name": "Acme Example", "type": "person", "summary": "x", "website": "https://acme-inference.io"})
    assert "sources" not in _fm(memory)


def test_propose_site_never_overrides_a_tombstone_or_an_existing_site():
    fm = {"sources_removed": [{"ref": "https://acme-inference.io", "predicate": "website", "by": "user", "at": "2026-09-01"}]}
    assert fact_sources.propose_site(fm, "https://acme-inference.io") is False
    assert fact_sources.propose_site(fm, "https://www.acme-inference.io/other") is False, "the same site, by host"
    fm = {"sources": [_proposed("https://one.example")]}
    assert fact_sources.propose_site(fm, "https://one.example/") is False
    assert fact_sources.propose_site(fm, "https://two.example") is True and len(fm["sources"]) == 2
    assert fact_sources.propose_site({}, "https://acme-inference.io/x?token=abcdef0123456789abcdef0123456789abcd") is False


# ---------- the engine-free backfill ----------


def test_candidates_come_from_a_website_claim_or_a_links_host_that_is_the_name(tmp_path):
    claim = _site_bank(tmp_path / "a", claim_site="https://www.acme-inference.io/about")
    assert site_sources.candidates(claim) == [("acme-example", "https://acme-inference.io")]
    links = _site_bank(tmp_path / "b", links="- [Docs](https://blog.other-labs.io/post)\n- [Acme](https://acme-example.com/team)")
    assert site_sources.candidates(links) == [("acme-example", "https://acme-example.com")]
    titled = _site_bank(tmp_path / "c", links="- [The official website](https://brand-labs.io/home)\n")
    assert site_sources.candidates(titled) == [("acme-example", "https://brand-labs.io")]


def test_nothing_else_is_a_candidate_never_a_name_guess(tmp_path):
    for i, kw in enumerate((
            {}, {"links": "- [An article](https://news-labs.io/acme-story)"},
            {"links": "- [Acme](https://github.com/acme/acme-example)"},
            {"links": "- [Acme](https://www.linkedin.com/company/acme-example)"},
            {"claim_site": "https://en.wikipedia.org/wiki/Acme"},
            {"claim_site": "https://acme-inference.io", "sources": [_proposed()]},
            {"claim_site": "https://acme-inference.io", "type_": "person"})):
        memory = _site_bank(tmp_path / str(i), **kw)
        assert site_sources.candidates(memory) == [], kw
    archived = _site_bank(tmp_path / "z", claim_site="https://acme-inference.io")
    page = archived / "entities" / "acme-example.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "status": "archived"}, parsed.body)
    bank_index.invalidate()
    assert site_sources.candidates(archived) == []


def test_a_tombstoned_site_is_never_a_candidate(tmp_path):
    memory = _site_bank(tmp_path, claim_site="https://acme-inference.io")
    page = memory / "entities" / "acme-example.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "sources_removed": [
        {"ref": "https://acme-inference.io/old", "predicate": "website", "by": "user", "at": "2026-09-01"}]}, parsed.body)
    bank_index.invalidate()
    assert site_sources.candidates(memory) == []


def test_propose_writes_unverified_cicada_entries_and_skips_dirty_pages(tmp_path):
    memory = _site_bank(tmp_path, claim_site="https://acme-inference.io")
    assert site_sources.propose(memory, frozenset({"entities/acme-example.md"})).paths == []
    report = site_sources.propose(memory)
    assert report.paths == ["entities/acme-example.md"] and report.counts == {"proposed": 1}
    (src,) = _fm(memory)["sources"]
    assert src["added_by"] == "cicada" and "verified" not in src
    assert site_sources.propose(memory).paths == [], "idempotent"


# ---------- judging ----------


def test_judge_needs_the_name_and_two_words_of_its_own_summary():
    fm = {"name": "Acme Example", "type": "company"}
    assert site_sources.judge(fm, SUMMARY, GOOD) == "verified"
    assert site_sources.judge(fm, SUMMARY, SHOW) == "mismatch", "the fireworks-show namesake"
    assert site_sources.judge(fm, SUMMARY, THIN) == "unconfirmed", "a JS shell says nothing either way"
    assert site_sources.judge(fm, SUMMARY, PageIdentity("ok", "https://other-inference.io", "Acme Example", "", "",
                                                        GOOD.excerpt, cross_site=True)) == "mismatch"
    stranger = PageIdentity("ok", "https://acme-inference.io/", "Welcome", "", "", "Something else entirely. " * 20)
    assert site_sources.judge(fm, SUMMARY, stranger) == "mismatch"
    assert site_sources.judge(fm, SUMMARY, PageIdentity("blocked")) == "walled"
    assert site_sources.judge(fm, SUMMARY, PageIdentity("interstitial")) == "walled"
    assert site_sources.judge(fm, SUMMARY, PageIdentity("failed:http_500")) == "unreachable"
    # an alias counts as the name; whole word only ("Go" is not "Google")
    assert site_sources.judge({"name": "Acme Inc", "aliases": ["Acme Example"]}, SUMMARY, GOOD) == "verified"
    google = PageIdentity("ok", "https://go-lang.io/", "Google search", "", "", GOOD.excerpt)
    assert site_sources.judge({"name": "Go", "type": "tool"}, "## Summary\nA programming language for servers.\n", google) != "verified"


# ---------- verification ----------


def test_verify_stamps_a_confirmed_site_and_it_draws_a_mark(tmp_path):
    memory = _site_bank(tmp_path, sources=[_proposed(by="cicada")])
    fetch = Fetcher(default=GOOD)
    report = asyncio.run(site_sources.verify(memory, fetch_fn=fetch))
    assert fetch.calls == ["https://acme-inference.io"] and report.counts["verified"] == 1
    (src,) = _fm(memory)["sources"]
    assert src["verified"]["how"] == "name+content" and src["access"] == "public" and fact_sources.trusted(src)
    assert logo_service.domain_for(_fm(memory), "") == "acme-inference.io"


def test_verify_outcomes_follow_d1(tmp_path):
    def run(identity, **kw):
        memory = _site_bank(tmp_path / f"{identity.status}-{len(identity.excerpt)}-{kw.get('n', 0)}",
                            sources=[_proposed(by="agent", **{k: v for k, v in kw.items() if k != "n"})])
        asyncio.run(site_sources.verify(memory, fetch_fn=Fetcher(default=identity)))
        return _fm(memory)

    gone = run(SHOW)                                   # a namesake: removed and remembered by cicada
    assert "sources" not in gone and gone["sources_removed"][0]["by"] == "cicada"
    assert gone["sources_removed"][0]["reason"] == "mismatch"
    thin = run(THIN)                                   # kept, "not confirmed", one tap trusts it
    (src,) = thin["sources"]
    assert not fact_sources.trusted(src) and src["checked"]["outcome"] == "unconfirmed"
    walled = run(PageIdentity("blocked"), n=1)
    assert "sources" not in walled and walled["sources_removed"][0]["reason"] == "walled"
    down = run(PageIdentity("failed:timeout"), n=2)    # a network failure: tried again, up to three nights
    assert down["sources"][0]["tries"] == 1


def test_a_network_failure_is_tried_three_nights_then_dropped_and_remembered(tmp_path):
    memory = _site_bank(tmp_path, sources=[_proposed()])
    fetch = Fetcher(default=PageIdentity("failed:timeout"))
    for night in (1, 2):
        asyncio.run(site_sources.verify(memory, fetch_fn=fetch))
        assert _fm(memory)["sources"][0]["tries"] == night
    asyncio.run(site_sources.verify(memory, fetch_fn=fetch))
    fm = _fm(memory)
    assert "sources" not in fm and fm["sources_removed"][0]["reason"] == "unreachable"
    assert fetch.calls == ["https://acme-inference.io"] * 3


def test_an_unconfirmed_site_is_not_re_read_for_thirty_days(tmp_path):
    memory = _site_bank(tmp_path, sources=[_proposed()])
    fetch = Fetcher(default=THIN)
    asyncio.run(site_sources.verify(memory, fetch_fn=fetch))
    asyncio.run(site_sources.verify(memory, fetch_fn=fetch))
    assert len(fetch.calls) == 1
    later = date.fromordinal(date.today().toordinal() + 31)
    asyncio.run(site_sources.verify(memory, fetch_fn=fetch, today=later))
    assert len(fetch.calls) == 2


def test_verify_never_requests_a_walled_or_platform_host_and_never_a_trusted_one(tmp_path):
    memory = _bank(tmp_path)
    for i, ref in enumerate(("https://www.linkedin.com/company/acme", "https://github.com/acme/widget",
                             "https://en.wikipedia.org/wiki/Acme", "https://x.com/acme")):
        _entity(memory, f"acme-{i}", name=f"Acme {i}", type="company", body=SUMMARY, sources=[_proposed(ref)])
    _entity(memory, "widget-example", name="Widget Example", type="tool", body=SUMMARY,
            sources=[_proposed("https://widget-tools.io", by="user")])
    bank_index.invalidate()
    fetch = Fetcher(default=GOOD)
    report = asyncio.run(site_sources.verify(memory, fetch_fn=fetch))
    assert fetch.calls == [] and report.counts == {"walled": 4}
    for i in range(4):
        assert "sources" not in _fm(memory, f"acme-{i}")


def test_verify_budget_and_one_fetch_per_site_and_dirty_pages(tmp_path):
    memory = _bank(tmp_path)
    for i in range(6):
        _entity(memory, f"co-{i}", name=f"Co {i}", type="company", body=SUMMARY,
                sources=[_proposed(f"https://site{i % 3}-labs.io/")])
    bank_index.invalidate()
    fetch = Fetcher(default=THIN)
    report = asyncio.run(site_sources.verify(memory, budget=2, fetch_fn=fetch, skip=frozenset({"entities/co-0.md"})))
    assert len(fetch.calls) == 2 and len(set(fetch.calls)) == 2 and report.counts["fetched"] == 2
    assert "entities/co-0.md" not in report.paths
    assert report.counts.get("deferred", 0) >= 1
    fetch2 = Fetcher(default=THIN)
    asyncio.run(site_sources.verify(memory, budget=99, fetch_fn=fetch2))
    assert len(fetch2.calls) == len(set(fetch2.calls)), "one fetch per site per run"


def test_the_rail_refuses_a_walled_host_even_when_called_directly(monkeypatch):
    async def boom(url):
        raise AssertionError("no request may be made")

    monkeypatch.setattr(link_enrichment, "_stream_html", boom)
    for url in ("https://www.linkedin.com/company/acme", "https://x.com/acme", ""):
        assert asyncio.run(link_enrichment.fetch_identity(url)).status == "blocked"


def test_fetch_identity_reads_title_site_name_and_flags_a_cross_site_redirect(monkeypatch):
    html = ('<html><head><title>Acme Example | Home</title><meta property="og:site_name" content="Acme Example">'
            '<meta name="description" content="Managed clusters."></head><body><main>' + "Visible text. " * 20
            + "</main></body></html>")

    async def stream(url):
        return "ok", html, "https://other-inference.io/landing"

    monkeypatch.setattr(link_enrichment, "_stream_html", stream)
    got = asyncio.run(link_enrichment.fetch_identity("https://acme-inference.io"))
    assert (got.title, got.site_name, got.meta_description) == ("Acme Example | Home", "Acme Example", "Managed clusters.")
    assert got.cross_site is True and "Visible text" in got.excerpt

    async def blocked(url):
        return "blocked", "", ""

    monkeypatch.setattr(link_enrichment, "_stream_html", blocked)
    assert asyncio.run(link_enrichment.fetch_identity("https://acme-inference.io")).status == "blocked"


def test_default_fetch_and_fetch_identity_share_one_transport():
    import inspect

    assert "_stream_html" in inspect.getsource(link_enrichment.default_fetch)
    assert "_stream_html" in inspect.getsource(link_enrichment.fetch_identity)
    assert "httpx" not in inspect.getsource(link_enrichment.fetch_identity)


# ---------- the Sleep tail ----------


def test_the_tail_step_is_gated_and_fetches_nothing_when_the_gate_is_off(tmp_path, monkeypatch):
    memory = _site_bank(tmp_path, claim_site="https://acme-inference.io")
    head = _git(memory, "rev-parse", "HEAD")

    async def boom(*a, **k):
        raise AssertionError("the unattended gate is off: no fetch, no proposal")

    monkeypatch.setattr(link_enrichment, "fetch_identity", boom)
    monkeypatch.setattr(link_enrichment, "_stream_html", boom)
    from api.services.connectors import base

    monkeypatch.setattr(base, "network_allowed", lambda allow_fetch=None: False)
    asyncio.run(sleep_cycle._site_sources_safely(memory))
    assert _git(memory, "rev-parse", "HEAD") == head and "sources" not in _fm(memory)


def test_the_tail_step_commits_alone_as_cicada_and_skips_a_dirty_page(tmp_path, monkeypatch):
    memory = _site_bank(tmp_path, claim_site="https://acme-inference.io")
    _entity(memory, "widget-example", name="Widget Example", type="tool", body=SUMMARY, sources=[_proposed("https://widget-tools.io")])
    subprocess.run(["git", "-C", str(memory), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "more"], check=True, capture_output=True)
    dirty = memory / "entities" / "widget-example.md"
    dirty.write_text(dirty.read_text() + "\na person's uncommitted edit\n")
    from api.services.connectors import base

    monkeypatch.setattr(base, "network_allowed", lambda allow_fetch=None: True)
    fetch = Fetcher(default=GOOD)
    monkeypatch.setattr(link_enrichment, "fetch_identity", fetch)
    bank_index.invalidate()
    asyncio.run(sleep_cycle._site_sources_safely(memory))
    msg = _git(memory, "log", "-1", "--format=%B")
    assert msg.startswith("Site check ") and "trigger: sleep/site-check" in msg
    assert "Cicada-Author: cicada" in msg and "Cicada-Engine" not in msg
    assert "acme-inference.io" not in msg, "the manifest names pages, never a host"
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == ["entities/acme-example.md"]
    assert fetch.calls == ["https://acme-inference.io"], "the dirty page's site was not read"
    assert fact_sources.trusted(_fm(memory)["sources"][0])


def test_a_failed_tail_commit_restores_the_pages(tmp_path, monkeypatch):
    memory = _site_bank(tmp_path, claim_site="https://acme-inference.io")
    from api.services import git_service
    from api.services.connectors import base

    monkeypatch.setattr(base, "network_allowed", lambda allow_fetch=None: True)
    monkeypatch.setattr(link_enrichment, "fetch_identity", Fetcher(default=GOOD))

    async def fail(*a, **k):
        raise RuntimeError("index.lock")

    monkeypatch.setattr(git_service, "commit_paths", fail)
    asyncio.run(sleep_cycle._site_sources_safely(memory))
    assert "sources" not in _fm(memory) and _git(memory, "status", "--porcelain").strip() == ""


# ---------- the route ----------


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _site_bank(tmp_path, sources=[_proposed()])
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def test_verify_sites_route_is_the_persons_click_ungated_and_counts_only(client, monkeypatch):
    c, memory = client
    from api.services.connectors import base

    monkeypatch.setattr(base, "network_allowed", lambda allow_fetch=None: False)   # the nightly gate is off: irrelevant
    fetch = Fetcher(default=GOOD)
    monkeypatch.setattr(link_enrichment, "fetch_identity", fetch)
    body = c.post("/maintenance/verify-sites").json()
    assert body["verified"] == 1 and body["fetched"] == 1 and body["pages"] == 1
    assert "acme-inference.io" not in json.dumps(body)
    msg = _git(memory, "log", "-1", "--format=%B")
    assert msg.startswith("Site check ") and "Cicada-Author: cicada" in msg and "trigger: user/companion_app" in msg
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == ["entities/acme-example.md"]


def test_verify_sites_route_waits_for_sleep_and_overlapping_calls(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    assert c.post("/maintenance/verify-sites").status_code == 409
    assert "sources_removed" not in _fm(memory) and "verified" not in _fm(memory)["sources"][0]


# ---------- pictures: only from a trusted site, never a guess ----------


def test_a_page_with_no_trusted_site_makes_no_logo_request_at_all(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _site_bank(tmp_path)
    calls = []

    async def fetcher(url):
        calls.append(url)
        return logo_service.FetchResult(404, b"", "text/html")

    for name in ("acme-example",):
        assert asyncio.run(logo_service.ensure_logo(memory, name, fetcher=fetcher)) is None
    assert calls == [], "a name (Acme -> acme.com) is never a reason to ask a server for an icon"
    page = memory / "entities" / "acme-example.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "sources": [_proposed()]}, parsed.body)
    assert asyncio.run(logo_service.ensure_logo(memory, "acme-example", fetcher=fetcher)) is None
    assert calls == [], "an unverified proposal draws nothing either"


def test_the_graph_offers_a_logo_only_for_a_trusted_site(tmp_path, monkeypatch):
    from api.services import graph_builder

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _site_bank(tmp_path, sources=[_proposed()])
    node = lambda: next(n for n in graph_builder.build_graph(memory).nodes if n.id == "acme-example")
    assert node().picture is None
    page = memory / "entities" / "acme-example.md"
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, {**parsed.frontmatter, "sources": [_proposed(by="user")]}, parsed.body)
    bank_index.invalidate()
    assert (node().picture, node().picture_source) == ("/entities/acme-example/logo", "logo")


# ---------- the wire and the source icon route ----------


def test_the_sources_wire_carries_trust_and_effective_access(client):
    c, memory = client
    fact_sources.add_source(memory, "acme-example", "https://www.linkedin.com/company/acme", predicate="profile",
                            added_by="user")
    rows = {r["ref"]: r for r in c.get("/entities/acme-example/sources").json()["sources"]}
    assert rows["https://acme-inference.io"]["trusted"] is False and rows["https://acme-inference.io"]["effectiveAccess"] == "unknown"
    assert rows["https://www.linkedin.com/company/acme"]["trusted"] is True
    assert rows["https://www.linkedin.com/company/acme"]["effectiveAccess"] == "signed_in"


def test_the_source_icon_route_serves_only_a_trusted_sites_of_this_page(client, monkeypatch, tmp_path):
    c, memory = client
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    asked = []

    async def fake_icon(memory_path, site, domain, *, fetcher=None):
        asked.append((site, domain))
        path = tmp_path / "icon.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        return path

    monkeypatch.setattr(logo_service, "ensure_site_icon", fake_icon)
    assert c.get("/entities/acme-example/sources/icon/acme-inference.io").status_code == 404, "an unverified proposal"
    fact_sources.add_source(memory, "acme-example", "https://team.team-labs.io/page", predicate="profile", added_by="user")
    assert c.get("/entities/acme-example/sources/icon/team-labs.io").status_code == 200
    assert asked == [("team-labs.io", "team-labs.io")], "keyed on the site, no ref or path reaches the icon service"
    assert c.get("/entities/acme-example/sources/icon/other-inference.io").status_code == 404, "not a proxy for any name"
    assert c.get("/entities/nobody/sources/icon/team-labs.io").status_code == 404
    assert c.get("/entities/acme-example/sources/icon/bad..key/").status_code == 404
