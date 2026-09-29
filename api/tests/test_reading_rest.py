"""G166 — the app's reading routes: settings and the acknowledgement, "Ask an
agent" (which saves an unsaved link without a fetch, as the person), the asks and
their ETag, cancel, the hand-off prompt, and the `read` block on `GET /sources`."""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from _reading_fixtures import PUBLIC, WALLED, enable, git_log, porcelain, record, reading, stdio_server  # noqa: F401
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


def test_settings_start_off_with_the_five_switches_described(api):
    client, _ = api
    body = client.get("/reading/settings").json()
    assert (body["agentEnabled"], body["agentHosts"], body["ackedAt"], body["ackCurrent"]) == (False, [], None, False)
    assert [s["key"] for s in body["hostSwitches"]] == ["linkedin", "x", "facebook", "instagram", "tiktok"]
    x = next(s for s in body["hostSwitches"] if s["key"] == "x")
    assert x["label"] == "X" and x["domains"] == ["x.com", "twitter.com"]
    assert "video" in next(s for s in body["hostSwitches"] if s["key"] == "tiktok")["note"].lower()
    assert body["lastAgentRead"] is None and body["ackVersion"] == reading_settings.ACK_VERSION


def test_settings_etag_and_304(api):
    client, _ = api
    first = client.get("/reading/settings")
    assert client.get("/reading/settings", headers={"If-None-Match": first.headers["ETag"]}).status_code == 304
    client.put("/reading/settings", json={"agentHosts": ["x"]})
    changed = client.get("/reading/settings", headers={"If-None-Match": first.headers["ETag"]})
    assert changed.status_code == 200 and changed.json()["agentHosts"] == ["x"]


def test_turning_on_without_the_acknowledgement_is_a_422_with_a_sentence(api):
    client, _ = api
    r = client.put("/reading/settings", json={"agentEnabled": True})
    assert r.status_code == 422 and "I understand" in r.json()["detail"]
    assert client.get("/reading/settings").json()["agentEnabled"] is False


def test_the_sheet_turns_it_on_with_its_sites_in_one_call(api):
    client, _ = api
    r = client.put("/reading/settings", json={"agentEnabled": True, "acknowledge": True, "agentHosts": ["linkedin"]})
    body = r.json()
    assert r.status_code == 200 and body["agentEnabled"] and body["ackCurrent"] and body["agentHosts"] == ["linkedin"]
    assert body["ackedAt"]


def test_an_unknown_site_is_a_422(api):
    client, _ = api
    r = client.put("/reading/settings", json={"agentHosts": ["x", "reddit"]})
    assert r.status_code == 422 and "reddit" in r.json()["detail"]


def test_the_last_agent_read_shows_only_once_one_has_been_recorded(api, monkeypatch, tmp_path):
    client, memory = api
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
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


def test_a_walled_site_that_is_switched_off_is_a_409_naming_the_switch(api):
    client, _ = api
    enable(hosts=())
    r = client.post("/reading/asks", json={"url": WALLED})
    assert r.status_code == 409 and "X is not turned on" in r.json()["detail"]


@pytest.mark.parametrize("url, needle", [
    ("https://vimeo.com/123456789", "cicada_record_watch"),
    ("https://arxiv.org/abs/2401.00001", "paper"),
    ("https://blog.bob-example.org/a?token=abc", "secret"),
    ("http://localhost/a", "this Mac"),
    ("https://www.reddit.com/r/alpha", "never offers"),
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
