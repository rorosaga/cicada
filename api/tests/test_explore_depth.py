"""G166 exploring, slice 2 (owner 2026-10-14 evening): depth follows the person's reason, a site map kept in memory.

* the plan from each explicit reason, from the person's free words, and from what they said in conversations — no
  model anywhere (the backend's half of the split);
* the caps and the pace: at most six pages a visit, never past the hour's room, at least 8 seconds apart, the same
  host, never a sign-in page, only pages robots.txt allows as the agent's browser read it;
* the site map: append-only over visits, legible, read over MCP and REST;
* the automatic Look for a design reason, through the one design writer;
* the demo refusal; and the capture script itself, driven against a fake browser (pacing, robots, the cap, a wall).

Synthetic bank, made-up pictures and bob-example.org links only; nothing reads a real bank or the network."""
from __future__ import annotations

import base64
import json
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from _explore_fixtures import DARK, LIGHT, add_site, bank_with_sites, enable_reading
from api.services import (claims, demo_guard, demo_pictures, design_refs, explore_candidates, explore_plan,
                          explore_queue, image_decode, markdown_parser, mcp_tools, media_ingestor, site_captures,
                          site_map)

needs_sips = pytest.mark.skipif(not image_decode.available(), reason="macOS's sips decodes images here")
ROOT = Path(__file__).resolve().parents[2]
GREEN = demo_pictures.website((236, 247, 238), (214, 236, 219), (20, 60, 30), (30, 140, 70), width=1440, height=900,
                              centred=True)
ROBOTS = {"status": 200, "text": "User-agent: *\nDisallow: /docs\n"}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(self, address):
        if isinstance(address, tuple) and address and address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"exploring opened a network connection to {address!r}")
        raise OSError("no network in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def _kinds(plan: dict) -> list[str]:
    return [p["kind"] for p in plan["pages"]]


# --------------------------------------------------------------------------- the plan from the reason


def test_no_reason_is_the_saved_page_alone():
    plan = explore_plan.plan_for(None)
    assert plan["depth"] == "capture" and plan["max_pages"] == 1 and _kinds(plan) == ["saved"]
    assert plan["pages"][0]["shots"] == ["viewport"] and not plan.get("auto_look")
    assert plan["because"] == [{"from": "default", "signal": "minimal"}]


def test_each_explicit_reason_has_its_own_plan():
    design = explore_plan.plan_for({"reasons": ["design"]})
    assert design["depth"] == "look" and design["auto_look"] is True
    assert _kinds(design) == ["saved", "home", "pricing", "docs", "product", "blog"]
    assert all(p["shots"] == ["viewport", "full", "mobile", "dark"] for p in design["pages"])
    product = explore_plan.plan_for({"reasons": ["product"]})
    assert product["depth"] == "product" and product["lift"] is True and not product.get("auto_look")
    assert _kinds(product) == ["saved", "home", "pricing", "about", "docs"]
    assert product["pages"][0]["shots"] == ["viewport", "full"] and product["pages"][1]["shots"] == ["viewport"]
    technique = explore_plan.plan_for({"reasons": ["technique"], "text": "the masonry trick for galleries"})
    assert technique["depth"] == "read" and technique["section"] is True and _kinds(technique) == ["saved"]
    assert "masonry" in technique["focus"] and "galleries" in technique["focus"]
    later = explore_plan.plan_for({"reasons": ["read_later"]})
    assert later["depth"] == "capture" and later["max_pages"] == 1
    project = explore_plan.plan_for({"reasons": [], "project": "alpha-project"})
    assert project["depth"] == "product" and {"from": "reason", "signal": "project"} in project["because"]


def test_several_reasons_merge_to_the_deepest_and_never_pass_six_pages():
    plan = explore_plan.plan_for({"reasons": ["design", "product", "technique"], "text": "every page, the whole site"})
    assert plan["depth"] == "look" and plan["max_pages"] == explore_plan.MAX_PAGES == 6
    assert len(plan["pages"]) == 6 and plan["section"] and plan["auto_look"] and plan["lift"]


# --------------------------------------------------------------------------- the plan from the person's own words


def test_free_words_are_read_through_closed_families():
    loved = explore_plan.plan_for({"reasons": [], "text": "love how every page looks"})
    assert loved["depth"] == "look" and loved["auto_look"] and loved["max_pages"] == 6, "design, across the site"
    (sig,) = [b for b in loved["because"] if b["from"] == "text"]
    assert "design" in sig["signal"] and "wide" in sig["signal"] and "looks" in sig["words"]
    docs = explore_plan.plan_for({"text": "their docs are great"})
    assert _kinds(docs) == ["saved", "docs"] and docs["depth"] == "product", "a page the person named is opened"
    es = explore_plan.plan_for({"text": "me encanta el diseño y la tipografía"})
    assert es["depth"] == "look"
    assert explore_plan.plan_for({"text": "looking for a reason to come back"})["depth"] == "capture", \
        "'looking for' is not the look"
    assert explore_plan.plan_for({"text": "thanks"})["max_pages"] == 1


def test_the_saved_because_words_on_the_episode_count_too(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 0)
    add_site(memory, "tg", n=1)
    ep = memory / "episodes" / "ep_2026-09-21_001.md"
    parsed = markdown_parser.parse(ep)
    markdown_parser.write(ep, parsed.frontmatter, parsed.body + "\n\n## Saved because\nTheir pricing page is so clear")
    enable_reading()
    (site,) = explore_candidates.saved_sites(memory).values()
    plan = explore_plan.for_site(memory, site)
    assert "pricing" in _kinds(plan) and plan["depth"] == "product"


def _claim(cid: str, text: str, *, kind: str = "user", trust: str = "agent_extracted") -> claims.Claim:
    return claims.Claim(id=cid, text=text, subject="media-conv", predicate="about", object="x",
                        source_trust=trust, evidence=[claims.Evidence(episode="ep_2026-09-01_001", start=0, end=10,
                                                                      kind=kind, hash="abc")])


def test_what_the_person_said_in_conversations_steers_the_plan_and_an_agent_s_reading_does_not(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 0)
    add_site(memory, "conv", n=1)
    page = memory / "entities" / "media-conv.md"
    parsed = markdown_parser.parse(page)
    body = claims.write_claims(parsed.body, [
        _claim("c1", "The person loves the typography on this site"),
        _claim("c2", "The site sells a pricing calculator", kind="reasoning"),
        _claim("c3", "The person wants to learn how they do the scroll animation", kind="assistant",
               trust="user_stated")])
    markdown_parser.write(page, parsed.frontmatter, body)
    said = explore_plan.said_in_conversations(memory, "media-conv")
    assert said == ["The person loves the typography on this site",
                    "The person wants to learn how they do the scroll animation"]
    enable_reading()
    (site,) = explore_candidates.saved_sites(memory).values()
    plan = explore_plan.for_site(memory, site)
    assert plan["depth"] == "look" and plan["section"], "design and technique, from the conversations"
    assert {b["from"] for b in plan["because"]} == {"conversation"}
    assert "pricing" not in [b.get("signal") for b in plan["because"]], "an agent's own reasoning is not the person"


def test_the_queue_depth_reads_the_words_too(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 0)
    add_site(memory, "words", why={"reasons": [], "text": "gorgeous landing page"}, n=1)
    enable_reading()
    (site,) = explore_candidates.saved_sites(memory).values()
    assert site.depth == "look"


# --------------------------------------------------------------------------- caps, pace, robots, host


T0 = datetime(2026, 10, 14, 14, 0, 0, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _vet(pages, plan=None, parser="default", **kw):
    plan = plan or explore_plan.plan_for({"reasons": ["design"]})
    parser = explore_plan.robots(**{"status": ROBOTS["status"], "text": ROBOTS["text"]}) if parser == "default" \
        else parser
    return explore_plan.vet(pages, plan=plan, landing_url="https://alpha.bob-example.org/",
                            landing_loaded_at=_iso(T0), robots_parser=parser, window_start=T0 - timedelta(seconds=5),
                            now=T0 + timedelta(minutes=2), **kw)


def _p(path: str, seconds: float, **kw) -> dict:
    return {"url": f"https://alpha.bob-example.org{path}", "loaded_at": _iso(T0 + timedelta(seconds=seconds)), **kw}


def test_vet_keeps_only_paced_same_host_allowed_pages_within_the_cap():
    kept, dropped = _vet([
        _p("/pricing", 9, kind="pricing"),
        _p("/features?utm=x#top", 12),                        # 3 s after the page before: too soon
        _p("/docs/start", 30, kind="docs"),                   # robots.txt disallows /docs
        _p("/login", 40),                                     # a sign-in page is never kept
        {"url": "https://other.bob-example.net/", "loaded_at": _iso(T0 + timedelta(seconds=50))},
        _p("/blog/one", 60, kind="blog"),
        _p("/pricing", 70),                                   # the same page twice
        _p("/", 80),                                          # the saved page itself
    ])
    assert [(k["url"], k["kind"]) for k in kept] == [("https://alpha.bob-example.org/pricing", "pricing"),
                                                     ("https://alpha.bob-example.org/blog/one", "blog")]
    assert dropped == {"pace": 1, "robots": 1, "account": 1, "host": 1, "repeat": 2}


def test_vet_caps_pages_by_the_plan_and_drops_loads_outside_the_lease():
    plan = explore_plan.capped(explore_plan.plan_for({"reasons": ["design"]}), 3)
    assert plan["max_pages"] == 3 and plan["capped_by"] == "hour" and _kinds(plan) == ["saved", "home", "pricing"]
    kept, dropped = _vet([_p(f"/p{i}", 9 * i) for i in range(1, 6)] + [_p("/late", 600)], plan=plan)
    assert len(kept) == 2 and dropped == {"cap": 3, "time": 1}
    minimal = explore_plan.plan_for(None)
    kept, dropped = _vet([_p("/pricing", 20)], plan=minimal)
    assert kept == [] and dropped == {"cap": 1}, "no reason: no page past the saved one, whatever the agent sends"


def test_without_robots_txt_no_further_page_is_kept_and_its_statuses_read_the_usual_way():
    kept, dropped = _vet([_p("/pricing", 20)], parser=None)
    assert kept == [] and dropped == {"robots": 1}
    assert explore_plan.allowed(explore_plan.robots(404, ""), "https://a.bob-example.org/x")
    assert not explore_plan.allowed(explore_plan.robots(403, ""), "https://a.bob-example.org/x")
    assert not explore_plan.allowed(explore_plan.robots(503, ""), "https://a.bob-example.org/x")
    assert explore_plan.robots(None, "User-agent: *") is None


def test_a_page_walled_before_is_never_kept_again():
    plan = explore_plan.plan_for({"reasons": ["design"]}, walled=["https://alpha.bob-example.org/pricing"])
    kept, dropped = _vet([_p("/pricing", 20)], plan=plan)
    assert kept == [] and dropped == {"walled": 1}


def test_the_hour_s_room_caps_a_deep_plan(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 0)
    rows = [{"key": f"{i:012x}", "site": "bob-example.org"} for i in range(30)]
    explore_queue.start(memory, rows, started_by={"kind": "person"}, now=T0)
    assert explore_queue.room(memory, "bob-example.org", now=T0) == explore_queue.MAX_LOADS_PER_LEASE == 6
    now = T0
    for _ in range(26):
        (row,) = explore_queue.claim(memory, session="s", harness="h", now=now)
        explore_queue.complete(memory, row["key"], row["lease_token"], outcome="captured", session="s", now=now)
        now += timedelta(seconds=explore_queue.PACE_SECONDS + 1)
    assert explore_queue.room(memory, "bob-example.org", now=now) == 4, "30 an hour, never more"


def test_page_kinds_by_path_then_label():
    k = explore_plan.page_kind
    assert k("https://a.bob-example.org/") == "home"
    assert k("https://a.bob-example.org/pricing") == "pricing" and k("https://a.bob-example.org/docs/intro") == "docs"
    assert k("https://a.bob-example.org/x", "Our Blog") == "blog" and k("https://a.bob-example.org/sign-in") == "account"
    assert k("https://a.bob-example.org/careers") == "other"


# --------------------------------------------------------------------------- the site map


def _visit(at: str, capture: str, pages=(), found=(), robots=None) -> dict:
    return {"at": at, "capture": capture, "entity": "media-alpha",
            "landing": {"url": "https://alpha.bob-example.org/", "title": "Alpha", "kind": "home",
                        "outcome": "captured", "dhash": "0" * 16},
            "pages": list(pages), "found": list(found), "robots": robots,
            "robots_parser": explore_plan.robots(ROBOTS["status"], ROBOTS["text"]) if robots else None}


def test_the_site_map_is_append_only_over_visits(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 0)
    first = _visit("2026-10-01T10:00:00Z", "20261001T100000Z-aaaaaa",
                   pages=[{"url": "https://alpha.bob-example.org/pricing", "title": "Pricing", "kind": "pricing",
                           "outcome": "captured", "dhash": "1" * 16}],
                   found=[{"url": "https://alpha.bob-example.org/docs/a", "label": "Docs"},
                          {"url": "https://alpha.bob-example.org/login", "label": "Sign in"},
                          {"url": "https://alpha.bob-example.org/pricing?ref=nav#x", "label": "Pricing"}],
                   robots={"status": 200, "sha256": "f" * 64})
    rel = site_map.update(memory, "bob-example.org", first)
    assert rel == "captures/_sites/bob-example.org.md"
    one = site_map.read(memory, "bob-example.org")
    urls = {p["url"]: p for p in one["pages"]}
    assert set(urls) == {"https://alpha.bob-example.org/", "https://alpha.bob-example.org/pricing",
                         "https://alpha.bob-example.org/docs/a"}, "no sign-in page, no query, no fragment"
    assert urls["https://alpha.bob-example.org/docs/a"]["robots"] == "disallowed"
    assert urls["https://alpha.bob-example.org/pricing"]["captures"] == ["20261001T100000Z-aaaaaa"]

    second = _visit("2026-10-14T10:00:00Z", "20261014T100000Z-bbbbbb",
                    found=[{"url": "https://alpha.bob-example.org/changelog", "label": "Changelog"}])
    site_map.update(memory, "bob-example.org", second)
    two = site_map.read(memory, "bob-example.org")
    by = {p["url"]: p for p in two["pages"]}
    assert set(urls) < set(by), "a page a later visit no longer finds keeps its row"
    assert by["https://alpha.bob-example.org/pricing"]["first_seen"] == "2026-10-01T10:00:00Z"
    assert by["https://alpha.bob-example.org/pricing"]["last_seen"] == "2026-10-01T10:00:00Z", "not seen again"
    home = by["https://alpha.bob-example.org/"]
    assert home["first_seen"] == "2026-10-01T10:00:00Z" and home["last_seen"] == "2026-10-14T10:00:00Z"
    assert home["captures"] == ["20261001T100000Z-aaaaaa", "20261014T100000Z-bbbbbb"]
    assert [v["capture"] for v in two["visits"]] == ["20261001T100000Z-aaaaaa", "20261014T100000Z-bbbbbb"]
    assert two["first_seen"] == "2026-10-01T10:00:00Z" and two["last_seen"] == "2026-10-14T10:00:00Z"
    assert site_map.known_by_kind(two) == {"pricing": "https://alpha.bob-example.org/pricing"}
    text = (memory / rel).read_text()
    assert "# Site map: bob-example.org" in text and "| Page | Kind | First seen | Last seen | Captures |" in text
    site_map.update(memory, "bob-example.org", second)
    assert len(site_map.read(memory, "bob-example.org")["visits"]) == 2, "the same visit twice is one line"


def test_a_walled_page_is_remembered_and_never_planned_again(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 0)
    site_map.update(memory, "bob-example.org", _visit(
        "2026-10-01T10:00:00Z", "20261001T100000Z-aaaaaa",
        pages=[{"url": "https://alpha.bob-example.org/pricing", "kind": "pricing", "outcome": "needs_login"}]))
    smap = site_map.read(memory, "bob-example.org")
    assert site_map.walled_urls(smap) == ["https://alpha.bob-example.org/pricing"]
    assert site_map.known_by_kind(smap) == {}, "a walled page is never the page to open again"
    assert any("never open it again" in line for line in site_map.summary_lines(smap))


def test_a_full_map_counts_new_pages_instead_of_listing_them(tmp_path, monkeypatch):
    monkeypatch.setattr(site_map, "MAX_PAGES", 3)
    merged = site_map.merge(None, site="bob-example.org", visit=_visit(
        "2026-10-01T10:00:00Z", "20261001T100000Z-aaaaaa",
        found=[{"url": f"https://alpha.bob-example.org/p{i}"} for i in range(5)]))
    assert len(merged["pages"]) == 3 and merged["unlisted"] == 3


def test_site_maps_never_count_as_a_page_s_captures(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 0)
    site_map.update(memory, "bob-example.org", _visit("2026-10-01T10:00:00Z", "20261001T100000Z-aaaaaa"))
    assert explore_candidates.explored_entities(memory) == set()


# --------------------------------------------------------------------------- the full flow: claim, record, map, Looks


@pytest.fixture
def design_bank(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 0)
    add_site(memory, "alpha", why={"reasons": ["design"], "text": "love how every page looks",
                                   "at": "2026-10-14T09:00:00Z"}, n=1)
    enable_reading()
    return memory


def _ctx(bank, harness="claude-code", session="s1", **kw):
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id=session, harness=harness, **kw)


def _save(tmp_path: Path, name: str, data: bytes) -> str:
    path = tmp_path / "shots" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    return str(path)


def _claim_one(bank):
    explore_queue.start(bank, [{"key": s.key, "site": s.site, "depth": s.depth}
                               for s in explore_candidates.select(bank, {"scope": "all"})],
                        started_by={"kind": "person"})
    reply = mcp_tools.explore_claim(_ctx(bank))
    line = next(l for l in reply.splitlines() if l.startswith("1. "))
    url = line[3:].split(" — ")[0]
    token = reply.split("lease_token ")[1].split(" ")[0]
    plan = json.loads(next(l for l in reply.splitlines() if l.strip().startswith("plan: ")).strip()[6:])
    return reply, url, token, plan


def test_the_claim_hands_the_agent_the_plan_and_why(design_bank):
    reply, url, _, plan = _claim_one(design_bank)
    assert "depth look" in reply and "up to 6 page(s)" in reply
    assert "why this deep: their reason: design; their words: design,wide" in reply
    assert "plan=<that site's plan JSON, as given>" in reply and "pages=[url, ...]" in reply
    assert plan["auto_look"] and plan["max_pages"] == 6 and plan["pages"][0]["kind"] == "saved"
    assert "login" in plan["avoid"], "the script is told which pages are never opened"


@needs_sips
def test_a_design_visit_records_its_pages_updates_the_site_map_and_keeps_looks(design_bank, tmp_path):
    bank = design_bank
    _, url, token, _ = _claim_one(bank)
    base = datetime.now(timezone.utc) - timedelta(seconds=100)
    at = lambda s: _iso(base + timedelta(seconds=s))  # noqa: E731
    pages = [
        {"url": "https://alpha.bob-example.org/pricing", "kind": "pricing", "chosen_by": "script", "loaded_at": at(10),
         "http_status": 200, "outcome": "captured", "page": {"title": "Pricing", "outline": [{"level": 1,
                                                                                              "text": "Plans"}]},
         "shots": [{"kind": "viewport", "path": _save(tmp_path, "p1.png", LIGHT)}]},
        {"url": "https://alpha.bob-example.org/docs/start", "kind": "docs", "loaded_at": at(20), "outcome": "captured",
         "shots": [{"kind": "viewport", "path": _save(tmp_path, "p2.png", GREEN)}]},       # robots: disallowed
        {"url": "https://alpha.bob-example.org/features", "kind": "product", "loaded_at": at(24),
         "outcome": "captured", "shots": [{"kind": "viewport", "path": _save(tmp_path, "p3.png", GREEN)}]},  # 4 s: too soon
        {"url": "https://alpha.bob-example.org/blog/one", "kind": "blog", "loaded_at": at(40), "outcome": "captured",
         "page": {"title": "A post"}, "shots": [{"kind": "viewport", "path": _save(tmp_path, "p4.png", DARK)}]},
        {"url": "https://alpha.bob-example.org/about", "kind": "about", "loaded_at": at(50), "outcome": "needs_login"},
    ]
    found = [{"url": "https://alpha.bob-example.org/changelog", "label": "Changelog"},
             {"url": "https://alpha.bob-example.org/account", "label": "Account"}]
    out = mcp_tools.record_capture(
        _ctx(bank), url, token, "captured", captured_at=at(5), final_url=url, http_status=200,
        shots=[{"kind": "viewport", "path": _save(tmp_path, "landing.png", DARK)}],
        page={"title": "Alpha", "outline": [{"level": 1, "text": "Alpha"}]}, signed_in=True, loaded_at=at(0),
        pages=pages, found=found, robots=ROBOTS)
    assert out.startswith("Recorded capture "), out
    assert "3 more page(s) kept: pricing, blog, about" in out
    assert "1 loaded sooner than 8 seconds" in out and "1 disallowed by robots.txt" in out
    (cap,) = site_captures.list_captures(bank, "media-alpha")
    assert [p["kind"] for p in cap["pages"]] == ["pricing", "blog", "about"]
    pricing, blog, about = cap["pages"]
    assert pricing["thumb"]["file"].startswith("assets/captures/") and pricing["palette"]
    assert about["outcome"] == "needs_login" and "images" not in about and "thumb" not in about
    assert cap["plan"]["depth"] == "look" and cap["plan"]["auto_look"] is True
    assert {b["from"] for b in cap["plan"]["because"]} == {"reason", "text"}

    smap = site_map.read(bank, "bob-example.org")
    by = {p["url"]: p for p in smap["pages"]}
    assert by["https://alpha.bob-example.org/pricing"]["captures"] == [cap["id"]]
    assert by["https://alpha.bob-example.org/about"]["outcome"] == "needs_login"
    assert by["https://alpha.bob-example.org/changelog"]["robots"] == "allowed"
    assert "https://alpha.bob-example.org/account" not in by
    assert "https://alpha.bob-example.org/features" not in by, "a page dropped for the pace is not 'opened'"

    looks = [r for r in design_refs.list_refs(bank) if r.via == "explore"]
    assert len(looks) == 2, "the landing page and the pricing page; the blog's look is the landing page's again"
    landing = next(r for r in looks if r.url == url)
    assert landing.extra["explored"] == {"site": "bob-example.org", "captured_at": cap["captured_at"],
                                         "capture": cap["id"], "entity": "media-alpha", "page_kind": "home",
                                         "page_url": url}
    assert landing.note == "love how every page looks" and landing.added_by == "claude-code"
    assert landing.captured == cap["captured_at"].replace("Z", "Z") and landing.entity == "media-alpha"
    assert "explored" in landing.tags

    log = subprocess.run(["git", "-C", str(bank), "show", "--stat", "--format=%B", "HEAD"], capture_output=True,
                         text=True).stdout
    assert "Cicada-Author: claude-code" in log and "captures/_sites/bob-example.org.md" in log and "design/" in log

    read = mcp_tools.site_map_read(_ctx(bank), "https://alpha.bob-example.org/whatever")
    assert "The site map of bob-example.org" in read and "| pricing |" in read
    assert "bob-example.org" in mcp_tools.site_map_read(_ctx(bank))


@needs_sips
def test_without_a_design_reason_no_look_is_kept_and_the_minimal_visit_keeps_no_further_page(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 1)
    enable_reading()
    _, url, token, plan = _claim_one(memory)
    assert plan["max_pages"] == 1
    now = datetime.now(timezone.utc)
    out = mcp_tools.record_capture(
        _ctx(memory), url, token, "captured", final_url=url, signed_in=True,
        shots=[{"kind": "viewport", "path": _save(tmp_path, "v.png", DARK)}], loaded_at=_iso(now - timedelta(seconds=40)),
        pages=[{"url": url + "pricing", "loaded_at": _iso(now - timedelta(seconds=20)), "outcome": "captured",
                "shots": [{"kind": "viewport", "path": _save(tmp_path, "w.png", LIGHT)}]}], robots=ROBOTS)
    assert "1 past the plan's page count" in out
    (cap,) = site_captures.list_captures(memory, "media-site00")
    assert "pages" not in cap and not design_refs.list_refs(memory)
    assert site_map.read(memory, "bob-example.org")["visits"][0]["pages"] == 1


@needs_sips
def test_a_page_showing_the_person_s_account_never_becomes_a_look(design_bank, tmp_path):
    _, url, token, _ = _claim_one(design_bank)
    out = mcp_tools.record_capture(_ctx(design_bank), url, token, "captured", final_url=url, signed_in=True,
                                   account_visible=True,
                                   shots=[{"kind": "viewport", "path": _save(tmp_path, "v.png", DARK)}])
    assert out.startswith("Recorded capture ") and not design_refs.list_refs(design_bank)


def test_the_demo_bank_refuses_and_writes_no_map_or_look(design_bank):
    (design_bank / demo_guard.MANIFEST).write_text("kind: demo\n")
    reply = mcp_tools.record_capture(_ctx(design_bank), "https://alpha.bob-example.org/", "a" * 32, "captured",
                                     pages=[{"url": "https://alpha.bob-example.org/pricing"}], robots=ROBOTS)
    assert reply == demo_guard.AGENT_REFUSAL
    assert not (design_bank / "captures").exists() and not (design_bank / "design").exists()


# --------------------------------------------------------------------------- the REST read


def test_the_site_map_is_served_over_rest(design_bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    site_map.update(design_bank, "bob-example.org", _visit("2026-10-01T10:00:00Z", "20261001T100000Z-aaaaaa"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(design_bank))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as c:
            listing = c.get("/explore/sites").json()
            assert listing["sites"] == [{"site": "bob-example.org", "pages": 1, "visits": 1,
                                         "lastSeen": "2026-10-01T10:00:00Z"}]
            got = c.get("/explore/sites/bob-example.org")
            assert got.status_code == 200 and got.json()["pages"][0]["captures"] == ["20261001T100000Z-aaaaaa"]
            again = c.get("/explore/sites/bob-example.org", headers={"If-None-Match": got.headers["etag"]})
            assert again.status_code == 304
            assert c.get("/explore/sites/never.bob-example.net").status_code == 404
    finally:
        config.get_settings.cache_clear()


# --------------------------------------------------------------------------- the capture script, on a fake browser


class FakeBrowser:
    """Just enough of browser-harness's helpers for the script: pages by URL, a clock that sleeps instantly."""

    def __init__(self, ns: dict, site: dict, robots: dict | None):
        self.ns, self.site, self.robots = ns, site, robots
        self.clock = 1000.0
        self.navigations: list[tuple[str, float]] = []
        self.current = None

    def cdp(self, method, **params):
        if method == "Target.createTarget":
            return {"targetId": "t1"}
        if method == "Page.navigate":
            self.navigations.append((params["url"], self.clock))
            self.current = params["url"]
            return {}
        if method == "Page.captureScreenshot":
            return {"data": base64.b64encode(b"\xff\xd8fake").decode()}
        return {}

    def js(self, expr):
        if expr == self.ns["_PAGE_JS"]:
            page = {"title": "", "outline": [], "found": [], "http_status": 200, "final_url": self.current,
                    **self.site.get(self.current, {})}
            return json.dumps(page)
        if expr == self.ns["_ROBOTS_JS"]:
            return json.dumps(self.robots or {"status": None})
        if "TreeWalker" in expr:
            return json.dumps({"heading": "Masonry layouts", "text": "Use CSS columns for a masonry grid."})
        if "scrollHeight" in expr:
            return 2000
        if "getComputedStyle" in expr:
            return "rgb(255, 255, 255)"
        return None

    def sleep(self, seconds):
        self.clock += seconds

    def monotonic(self):
        return self.clock


def _script(monkeypatch, tmp_path, site: dict, robots: dict | None):
    import time

    ns: dict = {"__name__": "explore_capture_test"}
    exec(compile((ROOT / "skills" / "site-explore" / "explore_capture.py").read_text(), "explore_capture.py", "exec"),
         ns)
    fake = FakeBrowser(ns, site, robots)
    base = datetime.now(timezone.utc) - timedelta(seconds=60)

    class FakeDatetime(datetime):
        """The script's clock follows the fake one, so its load times carry the pace it kept."""

        @classmethod
        def now(cls, tz=None):
            return base + timedelta(seconds=fake.clock - 1000.0)

    ns.update(cdp=fake.cdp, js=fake.js, switch_tab=lambda *a, **k: None, wait_for_load=lambda *a, **k: None,
              wait_for_network_idle=lambda *a, **k: None, datetime=FakeDatetime)
    monkeypatch.setattr(time, "sleep", fake.sleep)
    monkeypatch.setattr(time, "monotonic", fake.monotonic)
    return ns, fake


ROOT_URL = "https://alpha.bob-example.org/"
SITE = {ROOT_URL: {"title": "Alpha", "outline": [{"level": 2, "text": "Masonry layouts"}], "found": [
    {"url": "https://alpha.bob-example.org/pricing", "label": "Pricing"},
    {"url": "https://alpha.bob-example.org/docs/start", "label": "Docs"},
    {"url": "https://alpha.bob-example.org/login", "label": "Sign in"},
    {"url": "https://alpha.bob-example.org/features", "label": "Features"},
    {"url": "https://alpha.bob-example.org/blog/one", "label": "Blog"},
    {"url": "https://other.bob-example.net/pricing", "label": "Pricing elsewhere"}]}}


def test_the_script_follows_the_plan_at_a_person_s_pace_and_robots(monkeypatch, tmp_path):
    ns, fake = _script(monkeypatch, tmp_path, SITE, ROBOTS)
    plan = explore_plan.plan_for({"reasons": ["design"]})
    out = json.loads(ns["explore_capture"](ROOT_URL, plan=json.dumps(plan), out_dir=str(tmp_path / "o")))
    opened = [u for u, _ in fake.navigations]
    assert opened == [ROOT_URL, "https://alpha.bob-example.org/pricing", "https://alpha.bob-example.org/features",
                      "https://alpha.bob-example.org/blog/one"], "no docs (robots), no sign-in, no other host"
    gaps = [b - a for (_, a), (_, b) in zip(fake.navigations, fake.navigations[1:])]
    assert all(g >= explore_plan.PACE_SECONDS for g in gaps), gaps
    assert [p["kind"] for p in out["pages"]] == ["pricing", "product", "blog"] and out["loads"] == 4
    assert out["robots"]["status"] == 200 and len(out["found"]) == 6
    assert {s["kind"] for s in out["pages"][0]["shots"]} == {"viewport", "thumb", "full", "mobile"}
    kept, dropped = explore_plan.vet(out["pages"], plan=plan, landing_url=ROOT_URL, landing_loaded_at=out["loaded_at"],
                                     robots_parser=explore_plan.robots(ROBOTS["status"], ROBOTS["text"]))
    assert len(kept) == 3 and not dropped, "what the script does, the backend keeps"


def test_the_script_opens_nothing_further_without_a_reason_or_without_robots(monkeypatch, tmp_path):
    ns, fake = _script(monkeypatch, tmp_path, SITE, ROBOTS)
    out = json.loads(ns["explore_capture"](ROOT_URL, plan=explore_plan.plan_for(None), out_dir=str(tmp_path / "a"),
                                           pages=["https://alpha.bob-example.org/pricing"]))
    assert [u for u, _ in fake.navigations] == [ROOT_URL] and out.get("pages") == []
    ns, fake = _script(monkeypatch, tmp_path, SITE, None)
    out = json.loads(ns["explore_capture"](ROOT_URL, plan=explore_plan.plan_for({"reasons": ["design"]}),
                                           out_dir=str(tmp_path / "b")))
    assert [u for u, _ in fake.navigations] == [ROOT_URL] and out["robots"] == {"status": None}


def test_a_wall_on_a_further_page_ends_the_visit_without_a_screenshot(monkeypatch, tmp_path):
    site = {**SITE, "https://alpha.bob-example.org/pricing": {"http_status": 401}}
    ns, fake = _script(monkeypatch, tmp_path, site, ROBOTS)
    out = json.loads(ns["explore_capture"](ROOT_URL, plan=explore_plan.plan_for({"reasons": ["design"]}),
                                           out_dir=str(tmp_path / "w")))
    assert [p["outcome"] for p in out["pages"]] == ["needs_login"] and "shots" not in out["pages"][0]
    assert len(fake.navigations) == 2


def test_the_agent_s_own_picks_stay_inside_the_plan_and_the_technique_section_is_found(monkeypatch, tmp_path):
    ns, fake = _script(monkeypatch, tmp_path, SITE, ROBOTS)
    plan = explore_plan.capped(explore_plan.plan_for({"reasons": ["design"]}), 2)
    out = json.loads(ns["explore_capture"](ROOT_URL, plan=plan, out_dir=str(tmp_path / "c"), pages=[
        "https://other.bob-example.net/x", "https://alpha.bob-example.org/docs/a", "https://alpha.bob-example.org/blog/one",
        "https://alpha.bob-example.org/features"]))
    assert [(p["url"], p["chosen_by"]) for p in out["pages"]] == [("https://alpha.bob-example.org/blog/one", "agent")]
    ns, fake = _script(monkeypatch, tmp_path, SITE, ROBOTS)
    tech = explore_plan.plan_for({"reasons": ["technique"], "text": "their masonry trick"})
    out = json.loads(ns["explore_capture"](ROOT_URL, plan=tech, out_dir=str(tmp_path / "d")))
    assert out["section"] == {"heading": "Masonry layouts", "text": "Use CSS columns for a masonry grid.",
                              "chosen_by": "script"}
    assert [u for u, _ in fake.navigations] == [ROOT_URL]


def test_the_harness_tab_marker_never_reaches_a_title():
    """browser-harness prepends 🐴 to the title of every tab it drives; the script strips it and so does the writer
    (verified against a headless Chrome on a local fixture site, 2026-10-14)."""
    assert site_captures._unmarked("\U0001F434 Alpha Example") == "Alpha Example"
    assert site_captures._unmarked("Alpha \U0001F434") == "Alpha \U0001F434"
    assert "replace(/^\\u{1F434}\\s*/u, '')" in (ROOT / "skills" / "site-explore" / "explore_capture.py").read_text()


def test_the_site_map_stays_bounded_over_two_thousand_visits(tmp_path):
    """Review B1: one map per site, so a host with thousands of saved links must not grow a file rewritten and
    committed on every record. Visits roll into a count, each page keeps its newest capture ids, replies are capped."""
    import yaml

    smap = None
    for i in range(2000):
        at = (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
        smap = site_map.merge(smap, site="bob-example.org", visit={
            "at": at, "capture": f"{i:08d}T000000Z-{i % 0xffffff:06x}", "entity": f"media-p{i}", "depth": "look",
            "landing": {"url": "https://alpha.bob-example.org/", "title": "Alpha", "outcome": "captured"},
            "pages": [{"url": "https://alpha.bob-example.org/pricing", "kind": "pricing", "outcome": "captured"}],
            "found": [{"url": f"https://alpha.bob-example.org/post/{i}", "label": "Post"}]})
    assert len(smap["visits"]) == site_map.MAX_VISITS
    assert smap["earlier_visits"] == {"count": 2000 - site_map.MAX_VISITS, "first_at": "2026-01-01T00:00:00Z",
                                      "last_at": smap["earlier_visits"]["last_at"]}
    assert smap["earlier_visits"]["last_at"] < smap["visits"][0]["at"], "the newest lines are the ones listed"
    assert len(smap["visits"]) + smap["earlier_visits"]["count"] == 2000, "every visit is still counted"
    assert len(smap["pages"]) == site_map.MAX_PAGES and smap["unlisted"] == 2000 + 2 - site_map.MAX_PAGES
    home = next(p for p in smap["pages"] if p["url"] == "https://alpha.bob-example.org/")
    assert len(home["captures"]) == site_map.MAX_PAGE_CAPTURES
    assert home["earlier_captures"] == 2000 - site_map.MAX_PAGE_CAPTURES
    size = len(yaml.safe_dump(smap, allow_unicode=True)) + len(site_map.body(smap))
    assert size < 120_000, size

    memory, _ = bank_with_sites(tmp_path, 0)
    path = site_map.path_for(memory, "bob-example.org")
    path.parent.mkdir(parents=True)
    markdown_parser.write(path, smap, site_map.body(smap))
    ctx = mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s1", harness="claude-code")
    reply = mcp_tools.site_map_read(ctx, "bob-example.org")
    assert len(reply) < 40_000 and "more listed in the map file" in reply and "1950 earlier visit(s)" in reply
