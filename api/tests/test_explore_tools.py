"""G166 exploring — the MCP tools and the routes end to end: the start (click and trusted agent, D5), the claim, the
record with the signed-in flag (D2 amended), the candidate set's exclusions, the demo refusal, the gates (agent
reading, the skill's pin, no fetch from Cicada), and the captures API the link renderer reads.

Synthetic bank and pictures only; every network connection the backend might open is refused by the test."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from _explore_fixtures import DARK, add_site, bank_with_sites, enable_reading
from api.services import (demo_guard, explore_candidates, explore_queue, explore_skill, image_decode, mcp_tools,
                          media_ingestor, reading_settings, site_captures, skill_catalog, sync_service)

needs_sips = pytest.mark.skipif(not image_decode.available(), reason="macOS's sips decodes images here")
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Exploring never fetches anything from the backend or the MCP server: the agent's browser does the visiting."""
    def refuse(self, address):
        if isinstance(address, tuple) and address and address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"exploring opened a network connection to {address!r}")
        raise OSError("no network in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def bank(tmp_path):
    memory, keys = bank_with_sites(tmp_path, 3)
    enable_reading()
    return memory


def _ctx(bank, harness="claude-code", session="s1", **kw):
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id=session, harness=harness, **kw)


def _shots(tmp_path) -> list[dict]:
    path = tmp_path / "shots" / "viewport.png"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(DARK)
    return [{"kind": "viewport", "path": str(path)}]


def _token(reply: str) -> str:
    return reply.split("lease_token ")[1].split(" ")[0]


def _url(reply: str) -> str:
    line = next(l for l in reply.splitlines() if l.startswith("1. "))
    return line[3:].split(" — ")[0]


# --------------------------------------------------------------------------- the candidate set


def test_exclusions_private_walled_never_and_videos(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 1)
    add_site(memory, "doc", url="https://docs.google.com/document/d/abc/edit", n=2)
    add_site(memory, "li", url="https://www.linkedin.com/company/alpha-example/", n=3)
    add_site(memory, "vid", url="https://www.youtube.com/watch?v=abc123def45", n=4)
    add_site(memory, "never", url="https://never.alpha-example.net/", n=5)
    add_site(memory, "local", url="http://printer.local/", n=6)
    enable_reading(never={"alpha-example.net": "2026-10-14"})
    sites = explore_candidates.saved_sites(memory, include_excluded=True)
    reasons = {s.entity_id: s.excluded for s in sites.values()}
    assert reasons == {"media-site00": None, "media-doc": "private", "media-li": "walled", "media-vid": "video",
                       "media-never": "never", "media-local": "local"}
    enable_reading(never={"alpha-example.net": "2026-10-14"}, sites={"linkedin": "2026-10-14"})
    assert explore_candidates.saved_sites(memory, include_excluded=True)[media_ingestor.url_hash(
        "https://www.linkedin.com/company/alpha-example/")].excluded is None, "a walled site the person turned on"


def test_the_why_steers_the_depth_through_an_optional_field(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 0)
    add_site(memory, "look", why={"reasons": ["design"], "at": "2026-10-01T09:00:00Z"}, n=1)
    add_site(memory, "prod", why={"reasons": ["read_later"], "project": "alpha-project"}, n=2)
    add_site(memory, "none", n=3)
    depths = {s.entity_id: s.depth for s in explore_candidates.saved_sites(memory).values()}
    assert depths == {"media-look": "look", "media-prod": "product", "media-none": "capture"}


def test_the_why_the_merged_g191_writer_stores_steers_the_depth(tmp_path):
    """The real shape (#280): `saved_why.attach` writes `saved_why {reasons, project, text, at}` on the link's episode,
    and `GET /sources` serves it as `savedWhy {reasons, labels, project, text, at, addedAt}`."""
    from api.services import saved_why

    memory, _ = bank_with_sites(tmp_path, 0)
    add_site(memory, "look", url="https://look.bob-example.org/", n=1)
    add_site(memory, "proj", url="https://proj.bob-example.org/", n=2)
    look = saved_why.attach(memory, url="https://look.bob-example.org/", at="2026-10-14T09:00:00Z",
                            answer=saved_why.validate(memory, reasons=["design", "read_later"], project=None,
                                                      text="the type scale"))
    # G191 v3 added `edited_at` (when the person last changed the answer).
    assert set(look["saved_why"]) == {"reasons", "labels", "project", "text", "at", "added_at", "edited_at"}
    saved_why.attach(memory, url="https://proj.bob-example.org/", at="2026-10-14T09:05:00Z",
                     answer=saved_why.validate(memory, reasons=[], project="alpha-project", text=None))
    from api.services import bank_index

    bank_index.invalidate(memory)
    enable_reading()
    sites = {s.entity_id: s for s in explore_candidates.saved_sites(memory).values()}
    assert sites["media-look"].depth == "look" and sites["media-proj"].depth == "product"
    assert sites["media-look"].why == {"reasons": ["design", "read_later"], "text": "the type scale",
                                       "at": "2026-10-14T09:00:00Z"}
    assert sites["media-proj"].why["project"] == "alpha-project"


def test_selection_by_browser_and_never_explored(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 2)
    add_site(memory, "safari", origin="safari-bookmark", n=3)
    enable_reading()
    assert {s.entity_id for s in explore_candidates.select(memory, {"origins": ["safari-bookmark"]})} == \
        {"media-safari"}
    (memory / "captures" / "media-site00").mkdir(parents=True)
    (memory / "captures" / "media-site00" / "20261014T140200Z-aaaaaa.md").write_text("---\nid: x\n---\n")
    picked = {s.entity_id for s in explore_candidates.select(memory, {"scope": "never_explored"})}
    assert picked == {"media-site01", "media-safari"}
    view = explore_candidates.overview(memory)
    assert view["eligible"] == 3 and view["neverExplored"] == 2 and view["estimate"]["size"] == "light"
    assert {o["origin"] for o in view["origins"]} == {"chrome-bookmark", "safari-bookmark"}


# --------------------------------------------------------------------------- the MCP flow


@needs_sips
def test_claim_then_record_writes_a_signed_in_capture_and_commits_it(bank, tmp_path):
    explore_queue.start(bank, [{"key": s.key, "site": s.site, "depth": s.depth}
                               for s in explore_candidates.select(bank, {"scope": "all"})],
                        started_by={"kind": "person"})
    reply = mcp_tools.explore_claim(_ctx(bank))
    assert "Leased 1 site(s)" in reply and "explore_capture.py" in reply and "signed-in Chrome session" in reply
    url, token = _url(reply), _token(reply)
    out = mcp_tools.record_capture(_ctx(bank), url, token, "captured", captured_at=None, final_url=url,
                                   http_status=200, shots=_shots(tmp_path),
                                   page={"title": "Site", "outline": [{"level": 1, "text": "Hello"}]}, signed_in=True)
    assert out.startswith("Recorded capture ") and "signed-in browser" in out
    entity = explore_candidates.saved_sites(bank)[media_ingestor.url_hash(url)].entity_id
    (cap,) = site_captures.list_captures(bank, entity)
    assert cap["signed_in"] is True and cap["context"] == "signed_in" and cap["added_by"] == "claude-code"
    log = __import__("subprocess").run(["git", "-C", str(bank), "log", "-1", "--format=%B"], capture_output=True,
                                       text=True).stdout
    assert "Cicada-Author: claude-code" in log and "captures/" in log
    again = mcp_tools.record_capture(_ctx(bank), url, token, "captured", shots=_shots(tmp_path), signed_in=True)
    assert again.startswith("Already recorded"), "the same record twice writes nothing"
    assert len(site_captures.list_captures(bank, entity)) == 1


@needs_sips
def test_with_signed_in_exploring_off_the_claim_says_private_and_a_signed_in_record_is_refused(bank, tmp_path):
    enable_reading(signed_in=False)
    explore_queue.start(bank, [{"key": s.key, "site": s.site} for s in explore_candidates.select(bank, {})],
                        started_by={"kind": "person"})
    reply = mcp_tools.explore_claim(_ctx(bank))
    assert 'context="isolated"' in reply and "never fall back to the signed-in session" in reply
    url, token = _url(reply), _token(reply)
    refused = mcp_tools.record_capture(_ctx(bank), url, token, "captured", shots=_shots(tmp_path), signed_in=True)
    assert refused.startswith("Not recorded: the person turned off exploring in their signed-in browser")
    ok = mcp_tools.record_capture(_ctx(bank), url, token, "captured", shots=_shots(tmp_path), signed_in=False)
    assert "taken in a private context" in ok


def test_a_wall_pauses_the_site_and_keeps_nothing_in_the_bank(bank):
    explore_queue.start(bank, [{"key": s.key, "site": s.site} for s in explore_candidates.select(bank, {})],
                        started_by={"kind": "person"})
    reply = mcp_tools.explore_claim(_ctx(bank))
    out = mcp_tools.record_capture(_ctx(bank), _url(reply), _token(reply), "needs_login")
    assert "paused" in out and "no screenshot" in out
    assert not (bank / "captures").exists() and not (bank / "assets" / "captures").exists()
    assert explore_queue.batch_view(explore_queue.view(bank))["needsLogin"] == 3, "the whole site pauses"


def test_a_record_without_a_lease_is_refused(bank, tmp_path):
    url = explore_candidates.select(bank, {})[0].url
    assert "not leased to you" in mcp_tools.record_capture(_ctx(bank), url, "f" * 32, "gone")
    assert not (bank / "captures").exists()


def test_every_tool_refuses_a_demo_bank(bank, tmp_path):
    (bank / demo_guard.MANIFEST).write_text("kind: demo\n")
    for reply in (mcp_tools.explore_claim(_ctx(bank)), mcp_tools.explore_start(_ctx(bank)),
                  mcp_tools.record_capture(_ctx(bank), "https://site00.bob-example.org/", "a" * 32, "gone")):
        assert reply == demo_guard.AGENT_REFUSAL
    assert not explore_queue.path_for(bank).exists() and not (bank / "captures").exists()


def test_agent_reading_off_gates_every_write(bank):
    reading_settings.path().write_text(json.dumps({"agent": False}))
    assert mcp_tools.explore_claim(_ctx(bank)).startswith("Exploring is off")
    assert mcp_tools.explore_start(_ctx(bank)).startswith("Exploring is off")
    assert mcp_tools.record_capture(_ctx(bank), "https://site00.bob-example.org/", "a" * 32, "gone").startswith(
        "Exploring is off")


def test_a_trusted_local_agent_may_start_a_run_stamped_with_who_started_it(bank):
    reply = mcp_tools.explore_start(_ctx(bank, harness="claude-code", session="s9"))
    assert reply.startswith("Started exploring 3 saved site(s)")
    batch = explore_queue.batch_view(explore_queue.view(bank))
    assert batch["startedBy"] == {"kind": "agent", "harness": "claude-code", "session": "s9"}


def test_an_untrusted_remote_or_shell_caller_may_not_start_a_run(bank):
    assert mcp_tools.explore_start(_ctx(bank, harness="agent")).startswith("Not started")
    assert mcp_tools.explore_start(_ctx(bank, connector_id="c1")).startswith("Not started")
    assert mcp_tools.explore_start(_ctx(bank, read_surface="cli")).startswith("Not started")
    assert not explore_queue.path_for(bank).exists()


def test_the_four_tools_are_never_remote():
    from api.remote import catalog

    assert {"cicada_explore_queue", "cicada_explore_claim", "cicada_record_capture",
            "cicada_explore_start"} <= catalog.NEVER_REMOTE


# --------------------------------------------------------------------------- the skill's pin


def test_the_skill_files_match_their_reviewed_pin():
    pins = explore_skill.pins()
    assert set(pins) == {"SKILL.md", "explore_capture.py"}
    for name, sha in pins.items():
        assert explore_skill.sha256_of(explore_skill.skill_dir() / name) == sha, \
            f"{name} changed: re-pin it in recommended_skills.json after review"
    assert explore_skill.verified() == (True, "")
    entry = next(e for e in skill_catalog.load()["skills"] if e["id"] == "site-explore")
    assert entry["pin"]["path"] == "skills/site-explore" and entry["detect"]["skillDirs"] == ["site-explore"]


def test_a_tampered_script_is_never_handed_to_an_agent(bank, monkeypatch, tmp_path):
    fake = tmp_path / "skill"
    fake.mkdir()
    (fake / "SKILL.md").write_bytes((explore_skill.skill_dir() / "SKILL.md").read_bytes())
    (fake / "explore_capture.py").write_text("print('not the reviewed script')\n")
    monkeypatch.setattr(explore_skill, "skill_dir", lambda: fake)
    explore_queue.start(bank, [{"key": s.key, "site": s.site} for s in explore_candidates.select(bank, {})],
                        started_by={"kind": "person"})
    reply = mcp_tools.explore_claim(_ctx(bank))
    assert reply.startswith("Nothing was leased") and "does not match the reviewed version" in reply
    assert explore_queue.view(bank)["items"][0]["state"] == "queued"


# --------------------------------------------------------------------------- the routes


@pytest.fixture
def client(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    with TestClient(main.app) as c:
        yield c
    config.get_settings.cache_clear()


def test_the_click_starts_a_run_and_one_tap_stops_it(client, bank):
    cands = client.get("/explore/candidates").json()
    assert cands["eligible"] == 3 and cands["agentEnabled"] and cands["skillVerified"] and cands["exploreSignedIn"]
    started = client.post("/explore/batches", json={"scope": "all"}).json()
    assert started["batch"]["total"] == 3 and "cicada_explore_claim" in started["prompt"]
    assert "signed-in" in started["prompt"] and "never click or hide" in started["prompt"]
    state = client.get("/explore/state").json()
    assert state["batch"]["startedBy"] == {"kind": "person"} and state["batch"]["waiting"] == 3
    assert {i["state"] for i in state["items"]} == {"queued"}
    assert client.get("/explore/prompt").status_code == 200
    stop = client.post("/explore/stop").json()
    assert stop["dropped"] == 3
    assert client.get("/explore/state").json()["batch"]["waiting"] == 0


def test_starting_in_a_demo_bank_or_with_reading_off_is_refused(client, bank):
    reading_settings.path().write_text(json.dumps({"agent": False}))
    assert client.post("/explore/batches", json={"scope": "all"}).status_code == 409
    enable_reading()
    (bank / demo_guard.MANIFEST).write_text("kind: demo\n")
    assert client.post("/explore/batches", json={"scope": "all"}).status_code == 409
    assert not explore_queue.path_for(bank).exists()


def test_the_settings_switch_and_never_explore_ride_the_reading_settings(client, bank):
    body = client.put("/reading/settings", json={"exploreSignedIn": False, "neverExplore": {"bob-example.org": True}}).json()
    assert body["exploreSignedIn"] is False and "bob-example.org" in body["neverExplore"]
    assert explore_candidates.select(bank, {}) == [], "every fixture site is on bob-example.org"
    body = client.put("/reading/settings", json={"exploreSignedIn": True, "neverExplore": {"bob-example.org": False}}).json()
    assert body["exploreSignedIn"] is True and body["neverExplore"] == {}
    assert body["ackVersion"] == 3


@needs_sips
def test_the_captures_api_serves_dates_the_thumbnail_and_full_images(client, bank, tmp_path):
    site = explore_candidates.select(bank, {})[0]
    out = site_captures.record(bank, entity_id=site.entity_id, url=site.url, lease_token="d" * 32,
                               outcome="captured", shots=[("viewport", DARK)], page={"title": "Site"})
    listing = client.get(f"/explore/captures/{site.entity_id}").json()
    (cap,) = listing["captures"]
    assert cap["id"] == out["id"] and cap["capturedAt"] and cap["signedIn"] is True
    thumb = client.get(cap["thumb"]["url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    full = client.get(cap["images"][0]["url"])
    assert full.status_code == 200 and full.content == DARK
    assert client.get(f"/explore/captures/{site.entity_id}/{out['id']}/image/dark").status_code == 404
    state = client.get("/explore/state").json()
    (item,) = [i for i in state["items"] if i["mediaEntityId"] == site.entity_id]
    assert item["latest"]["id"] == out["id"] and item["latest"]["thumbUrl"]


def test_the_sync_components_move_on_a_queue_write_and_a_capture(bank):
    before = sync_service.components(bank)
    explore_queue.start(bank, [{"key": s.key, "site": s.site} for s in explore_candidates.select(bank, {})],
                        started_by={"kind": "person"})
    site_captures.record(bank, entity_id="media-site00", url="https://site00.bob-example.org/", lease_token="e" * 32,
                         outcome="gone")
    after = sync_service.components(bank)
    assert before["exploreQueue"] != after["exploreQueue"] and before["captures"] != after["captures"]


def test_nothing_in_the_explore_path_imports_a_fetcher():
    for rel in ("api/services/explore_queue.py", "api/services/explore_candidates.py", "api/services/site_captures.py",
                "api/services/explore_skill.py", "api/routers/explore.py"):
        text = (ROOT / rel).read_text()
        for fetcher in ("httpx", "urllib.request", "requests", "net_guard", "aiohttp"):
            assert f"import {fetcher}" not in text and f"from {fetcher}" not in text, (rel, fetcher)
