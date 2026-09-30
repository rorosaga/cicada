"""G166 (ruling 14 amended 2026-09-30) — `GET /reading/sites`, the permissions page's data,
and `GET /reading/sites/{site}/icon`. Counts and hosts only; ETag 304 before any scan; the
wire is pinned by `fixtures/reading_sites.json` (the Swift test decodes the same file)."""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _reading_fixtures import put_page, save
from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, media_ingestor, reading_asks, reading_queue, reading_settings, reading_walls, sync_service

FIXTURE = Path(__file__).parent / "fixtures" / "reading_sites.json"
ART = "https://articles.paperfold.io/post/{}"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    (memory / "sources").mkdir(exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    reading_walls.reset_memo()
    bank_index.invalidate()
    reading_queue._snapshots.clear()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _h(url):
    return media_ingestor.url_hash(url)


def _seed(memory):
    """A small, fixed bank: three sites that need the browser, one allowed with a sign-in pause."""
    for i in (1, 2, 3):
        put_page(memory, f"a{i}", ART.format(i), fetch_status="blocked", saved=f"2026-09-0{i}")
    put_page(memory, "c", "https://news.paperfold.io/x", fetch_status="interstitial")
    put_page(memory, "li1", "https://www.linkedin.com/in/alpha", saved="2026-09-01")
    put_page(memory, "li2", "https://www.linkedin.com/in/beta", saved="2026-09-02")
    put_page(memory, "tt", "https://www.tiktok.com/@alpha")
    put_page(memory, "ok", "https://blog.paperfold.io/fine", fetch_status="ok")
    reading_settings.update(agent_enabled_=True, acknowledge=True, today=date(2026, 9, 29))
    reading_settings.update(sites={"linkedin": True}, surfaced={"linkedin"}, today=date(2026, 9, 30))
    reading_asks.record_outcome(memory, _h("https://www.linkedin.com/in/beta"), "needs_login", create=True,
                                origin="site", host="linkedin.com")


def test_sites_list_matches_the_pinned_fixture(api):
    client, memory = api
    _seed(memory)
    body = client.get("/reading/sites").json()
    if os.environ.get("CICADA_UPDATE_FIXTURES") == "1":
        FIXTURE.write_text(json.dumps(body, indent=1) + "\n")
    assert body == json.loads(FIXTURE.read_text())
    assert body["shape"] == "reading-sites-3" and body["enabled"] is True
    assert [r["site"] for r in body["sites"]] == ["linkedin", "paperfold.io", "tiktok"]


def test_counts_only_no_url_title_or_note(api):
    client, memory = api
    _seed(memory)
    raw = client.get("/reading/sites").text
    assert "http" not in raw and "alpha" not in raw and "post/" not in raw
    for row in client.get("/reading/sites").json()["sites"]:
        assert set(row) == {"site", "label", "wall", "allowed", "granted", "since", "waiting", "read", "needsLogin", "note", "iconHost"}


def test_allowed_site_with_no_pages_is_listed(api):
    client, memory = api
    put_page(memory, "li", "https://www.linkedin.com/in/alpha")
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    reading_settings.update(sites={"linkedin": True}, surfaced={"linkedin"})
    os.remove(memory / "entities" / "media-li.md")
    rows = client.get("/reading/sites").json()["sites"]
    assert [(r["site"], r["allowed"], r["waiting"]) for r in rows] == [("linkedin", True, 0)]


def test_listed_with_master_off_and_says_so(api):
    client, memory = api
    put_page(memory, "li", "https://www.linkedin.com/in/alpha")
    body = client.get("/reading/sites").json()
    assert body["enabled"] is False and [r["site"] for r in body["sites"]] == ["linkedin"]
    assert body["waitingNotAllowed"] == 1 == body["waitingTotal"]


def test_a_grant_does_not_count_while_the_master_switch_is_off(api):
    """`allowed` is the permission that counts now; `granted` the stored one. With agent
    reading off nothing is queued, so a granted site's pages are still waiting on the person."""
    client, memory = api
    put_page(memory, "li", "https://www.linkedin.com/in/alpha")
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    reading_settings.update(sites={"linkedin": True}, surfaced={"linkedin"})
    on = client.get("/reading/sites").json()
    assert [(r["allowed"], r["granted"]) for r in on["sites"]] == [(True, True)] and on["waitingNotAllowed"] == 0
    reading_settings.update(agent_enabled_=False)
    off = client.get("/reading/sites").json()
    assert off["enabled"] is False
    assert [(r["allowed"], r["granted"], r["since"] is not None) for r in off["sites"]] == [(False, True, True)]
    assert off["waitingNotAllowed"] == 1 == off["waitingTotal"]


def test_etag_304_before_any_scan_and_moves_on_toggle_and_on_outcome(api, monkeypatch):
    client, memory = api
    _seed(memory)
    first = client.get("/reading/sites")
    etag = first.headers["ETag"]
    calls = []
    real = reading_queue.site_rows
    monkeypatch.setattr(reading_queue, "site_rows", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert client.get("/reading/sites", headers={"If-None-Match": etag}).status_code == 304
    assert calls == [], "a 304 scans nothing"
    r = client.put("/reading/settings", json={"sites": {"linkedin": False}})
    assert r.status_code == 200
    moved = client.get("/reading/sites", headers={"If-None-Match": etag})
    assert moved.status_code == 200 and moved.headers["ETag"] != etag
    etag2 = moved.headers["ETag"]
    reading_asks.record_outcome(memory, _h(ART.format(1)), "blocked", create=True, origin="site", host="paperfold.io")
    os.utime(reading_asks.path_for(memory), ns=(0, reading_asks.path_for(memory).stat().st_mtime_ns + 9_000_000))
    assert client.get("/reading/sites", headers={"If-None-Match": etag2}).status_code == 200


def test_the_list_and_the_feed_agree_on_what_is_waiting(api):
    """Every page the site row counts as waiting has a Feed row the person can open (the junk filter
    lets a wall page through), so the count never names pages nobody can find."""
    client, memory = api
    put_page(memory, "login", "https://wiki.paperfold.io/a", fetch_status="skipped:login_wall",
             enrichment_status="junk", enrichment_attempted=True)
    put_page(memory, "consent", "https://news.paperfold.io/c", fetch_status="skipped:interstitial",
             enrichment_status="junk", enrichment_attempted=True)
    put_page(memory, "gone", "https://blog.paperfold.io/junk", fetch_status="skipped:interstitial",
             enrichment_status="junk", enrichment_attempted=True)  # its own URL is not a wall host: not surfaced
    put_page(memory, "walled", "https://x.com/alpha/status/1")
    rows = {r["site"]: r for r in client.get("/reading/sites").json()["sites"]}
    items = client.get("/sources").json()["items"]
    with_wall = [i for i in items if (i.get("read") or {}).get("wall")]
    for site, row in rows.items():
        assert row["waiting"] == len([i for i in with_wall if i["read"]["siteKey"] == site]), site
    assert {i["read"]["wall"] for i in with_wall} == {"login", "consent", "walled"}


def test_junk_wall_page_has_a_feed_row_with_the_wall_state_and_an_agent_read_page_stays_visible(api):
    client, memory = api
    put_page(memory, "login", "https://wiki.paperfold.io/a", fetch_status="skipped:login_wall",
             enrichment_status="junk", enrichment_attempted=True)
    put_page(memory, "read", "https://wiki.paperfold.io/b", fetch_status="skipped:login_wall",
             enrichment_status="junk", enrichment_attempted=True,
             read={"by": "agent", "tier": "agent", "at": "2026-09-30T00:00:00Z"},
             body="## Description\n\n" + "It says a lot about how the wiki organises its pages and why. " * 3)
    put_page(memory, "retired", "https://blog.paperfold.io/login", fetch_status="skipped:login_wall",
             enrichment_status="junk", enrichment_attempted=True)  # a saved sign-in page: nothing behind it
    ids = {i["mediaEntityId"]: i for i in client.get("/sources").json()["items"]}
    assert set(ids) == {"media-login", "media-read"}, "a retired interstitial with no wall stays hidden"
    assert ids["media-login"]["read"]["wall"] == "login"
    assert ids["media-read"]["read"].get("wall") is None, "words on it: no longer a page the reader could not open"


# --- settings sites patch resumes a pause ----------------------------------------------------------------


def test_switching_a_site_on_again_clears_its_needs_login_pause(api):
    client, memory = api
    _seed(memory)
    assert reading_queue.paused_sites(reading_asks.all_rows(memory)) == {"linkedin"}
    r = client.put("/reading/settings", json={"sites": {"linkedin": True}})  # already on: "try again"
    assert r.status_code == 200
    assert reading_queue.paused_sites(reading_asks.all_rows(memory)) == set()
    assert [e.site for e in reading_queue.entries(memory)] == ["linkedin", "linkedin"]


def test_grant_for_a_never_surfaced_site_is_refused(api):
    client, memory = api
    reading_settings.update(agent_enabled_=True, acknowledge=True)
    r = client.put("/reading/settings", json={"sites": {"paperfold.io": True}})
    assert r.status_code == 422 and "paperfold.io" in r.json()["detail"]


# --- icon route -----------------------------------------------------------------------------------------


def test_icon_route_serves_only_surfaced_sites_and_never_asks_for_others(api, monkeypatch):
    from api.services import logo_service

    client, memory = api
    _seed(memory)
    asked = []

    async def spy(memory_path, site, domain, **k):
        asked.append((site, domain))
        return None

    monkeypatch.setattr(logo_service, "ensure_site_icon", spy)
    assert client.get("/reading/sites/nowhere.example.net/icon").status_code == 404
    assert client.get("/reading/sites/Bad%20Key/icon").status_code == 404
    assert asked == [], "an unknown name is a 404 with no lookup: the route is not a proxy"
    assert client.get("/reading/sites/paperfold.io/icon").status_code == 404
    assert asked == [("paperfold.io", "paperfold.io")]


def test_icon_route_does_not_rescan_per_request(api, monkeypatch):
    from api.services import logo_service

    client, memory = api
    _seed(memory)
    calls = []
    real = reading_queue.site_rows
    monkeypatch.setattr(reading_queue, "site_rows", lambda *a, **k: calls.append(1) or real(*a, **k))

    async def none(*a, **k):
        return None

    monkeypatch.setattr(logo_service, "ensure_site_icon", none)
    for site in ("linkedin", "paperfold.io", "tiktok", "linkedin"):
        client.get(f"/reading/sites/{site}/icon")
    client.get("/reading/sites")
    assert len(calls) == 1, "one scan between changes, shared by the list and the icon route"


def test_icon_route_serves_a_cached_file_with_an_etag_and_a_304(api):
    from api.services import logo_service

    client, memory = api
    _seed(memory)
    bank = logo_service.site_bank(logo_service.bank_name(memory))
    directory = logo_service.logos_dir(bank)
    (directory / "linkedin.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    logo_service.write_meta(bank, {"linkedin": {"fetched_at": __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).isoformat(), "domain": "linkedin.com", "miss": False, "ext": "png"}})
    r = client.get("/reading/sites/linkedin/icon")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "linkedin.com" not in r.headers.get("etag", "") and "max-age" in r.headers["cache-control"]
    assert client.get("/reading/sites/linkedin/icon", headers={"If-None-Match": r.headers["ETag"]}).status_code == 304
