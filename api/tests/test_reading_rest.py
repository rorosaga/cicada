"""G166 — the app's reading routes: settings, the acknowledgement and the per-site permission
patch, "Ask an agent" (which saves an unsaved link without a fetch, as the person), the asks
and their ETag, cancel, the hand-off prompt, and the `read` block on `GET /sources`."""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from _reading_fixtures import PUBLIC, WALLED, enable, git_log, porcelain, record, reading, save, stdio_server  # noqa: F401
from _synthetic_bank import _bank
from api import config, main
from api.services import media_ingestor, reading_asks, reading_prompt, reading_settings


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    (memory / "sources").mkdir(exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


# --- settings ---------------------------------------------------------------------


def test_get_settings_has_no_agent_hosts_or_host_switches(api):
    client, _ = api
    body = client.get("/reading/settings").json()
    assert (body["agentEnabled"], body["allowedSites"], body["ackedAt"], body["ackCurrent"]) == (False, {}, None, False)
    assert "agentHosts" not in body and "hostSwitches" not in body, "no pre-picked list of sites"
    assert body["lastAgentRead"] is None and body["ackVersion"] == reading_settings.ACK_VERSION == 2
    assert body["shape"] == "reading-2"


def test_settings_etag_and_304(api):
    client, memory = api
    save(memory, "https://www.linkedin.com/in/alpha")
    first = client.get("/reading/settings")
    assert client.get("/reading/settings", headers={"If-None-Match": first.headers["ETag"]}).status_code == 304
    client.put("/reading/settings", json={"agentEnabled": True, "acknowledge": True, "sites": {"linkedin": True}})
    changed = client.get("/reading/settings", headers={"If-None-Match": first.headers["ETag"]})
    assert changed.status_code == 200 and list(changed.json()["allowedSites"]) == ["linkedin"]


def test_turning_on_without_the_acknowledgement_is_a_422_with_a_sentence(api):
    client, _ = api
    r = client.put("/reading/settings", json={"agentEnabled": True})
    assert r.status_code == 422 and "I understand" in r.json()["detail"]
    assert client.get("/reading/settings").json()["agentEnabled"] is False


def test_put_sites_patch_round_trip_and_422_sentences(api):
    client, memory = api
    save(memory, "https://www.linkedin.com/in/alpha")
    # the sheet: one call turns the switch on, acknowledges, and allows the site
    r = client.put("/reading/settings", json={"agentEnabled": True, "acknowledge": True, "sites": {"linkedin": True}})
    body = r.json()
    assert r.status_code == 200 and body["agentEnabled"] and body["ackCurrent"] and list(body["allowedSites"]) == ["linkedin"]
    assert body["ackedAt"]
    # taking it back
    off = client.put("/reading/settings", json={"sites": {"linkedin": False}}).json()
    assert off["allowedSites"] == {} and off["agentEnabled"] is True
    # a malformed key, and a site Cicada has not needed the browser for, are 422s with sentences
    bad = client.put("/reading/settings", json={"sites": {"Not A Site": True}})
    assert bad.status_code == 422 and "Not A Site" in bad.json()["detail"]
    never = client.put("/reading/settings", json={"sites": {"paperfold.io": True}})
    assert never.status_code == 422 and "nothing to allow" in never.json()["detail"]
    # a grant with no current acknowledgement needs the sheet
    (memory.parent / "home" / "reading.json").unlink()
    needs_sheet = client.put("/reading/settings", json={"sites": {"linkedin": True}})
    assert needs_sheet.status_code == 422 and "I understand" in needs_sheet.json()["detail"]


def test_the_last_agent_read_shows_only_once_one_has_been_recorded(api, monkeypatch, tmp_path):
    client, memory = api
    enable()
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    from api.services import mcp_tools

    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    assert client.get("/reading/settings").json()["lastAgentRead"] is None
    ask = client.post("/reading/asks", json={"url": PUBLIC})
    assert ask.status_code == 200
    record(server, outcome="failed")
    assert client.get("/reading/settings").json()["lastAgentRead"] is None, "only a read counts"
    record(server)
    assert client.get("/reading/settings").json()["lastAgentRead"] is not None
    assert (tmp_path / "home" / reading_settings.LAST_READ_FILENAME).exists(), "the day is kept, not re-derived"


def test_a_read_episode_says_it_is_a_page_read_on_both_provenance_wires(api, monkeypatch):
    """The app labels a page-read quote "From the page, as <agent> read it", never bare
    "From the page": Cicada never had the page, so the wire carries the episode's source."""
    from _reading_fixtures import ids

    client, memory = api
    enable()
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    from api.services import mcp_tools

    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: False)
    assert client.post("/reading/asks", json={"url": PUBLIC}).status_code == 200
    eid, ep, _cid = ids(record(server))
    text = client.get(f"/episodes/{ep}/text").json()
    assert text["source"] == "page-read"
    rows = client.get(f"/entities/{eid}/provenance").json()["conversations"]
    assert rows and rows[0]["source"] == "page-read"


def test_the_prompt_is_generic_and_names_no_url(api):
    client, _ = api
    body = client.get("/reading/prompt").json()
    assert body == {"prompt": reading_prompt.queue_prompt()}
    assert "http" not in body["prompt"]


# --- asks -------------------------------------------------------------------------


def test_an_ask_with_reading_off_is_a_409_and_writes_nothing(api):
    client, memory = api
    r = client.post("/reading/asks", json={"url": PUBLIC})
    assert r.status_code == 409 and "Agent reading is off" in r.json()["detail"]
    assert not (reading_asks.path_for(memory)).exists() and media_ingestor.load_url_index(memory) == {}


def test_a_walled_link_is_askable_whenever_the_master_switch_is_on(api):
    """The per-site 409 is gone: 'Ask an agent' on one page is the person's own consent for it."""
    client, _ = api
    enable(sites=())
    r = client.post("/reading/asks", json={"url": WALLED})
    assert r.status_code == 200 and r.json()["ask"]["host_class"] == "walled"


@pytest.mark.parametrize("url, needle", [
    ("https://vimeo.com/123456789", "cicada_record_watch"),
    ("https://arxiv.org/abs/2401.00001", "paper"),
    ("https://blog.bob-example.org/a?token=abc", "secret"),
    ("http://localhost/a", "this Mac"),
    ("https://t.co/abc", "redirector"),
    ("ftp://x", "web address"),
])
def test_a_denied_link_is_a_422_with_a_plain_sentence(api, url, needle):
    client, memory = api
    enable()
    r = client.post("/reading/asks", json={"url": url})
    assert r.status_code == 422 and needle in r.json()["detail"]
    assert media_ingestor.load_url_index(memory) == {}


def test_asking_saves_an_unsaved_link_without_a_fetch_as_the_person(api, monkeypatch):
    client, memory = api
    enable()

    async def spy(*a, **k):
        raise AssertionError("asking fetched a page")

    monkeypatch.setattr(media_ingestor, "enrich", spy)
    r = client.post("/reading/asks", json={"url": PUBLIC})
    body = r.json()
    assert r.status_code == 200 and body["saved"] is True
    assert body["ask"]["state"] == "waiting" and "http" not in str(body["ask"])
    assert body["prompt"].startswith(f"Start with {PUBLIC}. ")
    assert body["mediaEntityId"] and (memory / "entities" / f"{body['mediaEntityId']}.md").exists()
    log = git_log(memory)
    assert "Cicada-Author: user" in log and "trigger: user/media_save" in log and porcelain(memory) == ""


def test_asking_again_resets_and_never_saves_twice(api):
    client, memory = api
    enable()
    first = client.post("/reading/asks", json={"url": PUBLIC}).json()
    reading_asks.record_outcome(memory, media_ingestor.url_hash(PUBLIC), "needs_login")
    again = client.post("/reading/asks", json={"url": PUBLIC}).json()
    assert again["saved"] is False and again["mediaEntityId"] == first["mediaEntityId"]
    (row,) = client.get("/reading/asks").json()["asks"]
    assert row["state"] == "waiting" and row["outcomeAt"] is None


def test_the_asks_list_counts_and_etags_on_the_reading_component(api):
    client, memory = api
    enable()
    client.post("/reading/asks", json={"url": PUBLIC})
    first = client.get("/reading/asks")
    body = first.json()
    assert body["counts"]["waiting"] == 1 and body["expiresAfterDays"] == reading_asks.EXPIRES_AFTER_DAYS
    (row,) = body["asks"]
    assert set(row) >= {"urlHash", "mediaEntityId", "host", "state", "askedAt", "outcomeAt", "via", "harness"}
    assert row["host"] == "blog.bob-example.org" and row["urlHash"] == media_ingestor.url_hash(PUBLIC)
    assert client.get("/reading/asks", headers={"If-None-Match": first.headers["ETag"]}).status_code == 304
    reading_asks.record_outcome(memory, media_ingestor.url_hash(PUBLIC), "needs_login", via="a tool")
    import os

    os.utime(reading_asks.path_for(memory), ns=(0, reading_asks.path_for(memory).stat().st_mtime_ns + 9_000_000))
    second = client.get("/reading/asks", headers={"If-None-Match": first.headers["ETag"]})
    assert second.status_code == 200 and second.json()["asks"][0]["state"] == "needs_login"
    assert second.json()["asks"][0]["via"] == "a tool"


def test_cancelling_an_ask_removes_it(api):
    client, memory = api
    enable()
    client.post("/reading/asks", json={"url": PUBLIC})
    h = media_ingestor.url_hash(PUBLIC)
    assert client.delete(f"/reading/asks/{h}").json() == {"removed": True}
    assert client.delete(f"/reading/asks/{h}").json() == {"removed": False}
    assert client.get("/reading/asks").json()["asks"] == []


# --- the read block on /sources -----------------------------------------------------


def test_sources_carries_askability_for_a_saved_link_and_none_for_a_video(api):
    client, memory = api
    import asyncio

    for url in (PUBLIC, "https://vimeo.com/123456789"):
        item = media_ingestor.RawItem(url=url, origin="saved-link", defer_enrich=True)
        idx = media_ingestor.load_url_index(memory)
        asyncio.run(media_ingestor.ingest_one(item, memory, None, idx))
        media_ingestor.save_url_index(memory, idx)
    by_url = {i["url"]: i for i in client.get("/sources").json()["items"]}
    off = by_url[PUBLIC]["read"]
    assert off["status"] == "none" and off["askable"] is False and "Agent reading is off" in off["reason"]
    assert by_url["https://vimeo.com/123456789"]["read"] is None, "a video is not a page to read"
    enable()
    on = {i["url"]: i for i in client.get("/sources").json()["items"]}[PUBLIC]["read"]
    assert on["askable"] is True and on["reason"] is None and on["host"] == "blog.bob-example.org"


def test_sources_shows_a_successful_read_from_the_page_stamp(reading):
    server, memory = reading
    import asyncio

    from api.services import reading_service

    asyncio.run(reading_service.ask(memory, PUBLIC))
    record(server, via="browser-harness")
    reading_asks.drop(memory, media_ingestor.url_hash(PUBLIC))
    from fastapi.testclient import TestClient as TC

    import os

    os.environ["CICADA_MEMORY_PATH"] = str(memory)
    config.get_settings.cache_clear()
    try:
        (item,) = TC(main.app).get("/sources").json()["items"]
    finally:
        os.environ.pop("CICADA_MEMORY_PATH", None)
        config.get_settings.cache_clear()
    read = item["read"]
    assert (read["status"], read["by"], read["tier"], read["via"], read["harness"]) == (
        "ok", "agent", "agent", "browser-harness", "claude-code")
    assert read["at"]
