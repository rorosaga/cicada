"""The `/sources/calendars` and `/sources/feeds` endpoints mirror each other (subscribe, list, unsubscribe, poll with
the feed gate closed), so each check runs once per registry. What only one of them does — a calendar's `webcal://`
normalization, a feed's items — stays in `test_calendar_registry.py` / `test_feed_registry.py`. No network: the
feed gate (`CICADA_ALLOW_FEED_FETCH`) is left closed and enrichment is the URL-only fallback."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import media_ingestor
from api.services.media_ingestor import MediaMeta

CALENDARS = {"route": "/sources/calendars", "poll": "/sources/poll-calendars", "listed": "calendars",
             "per": "per_calendar", "url": "https://a.example.com/cal.ics", "tag": "work",
             "missing": "https://nope.example.com/cal.ics"}
FEEDS = {"route": "/sources/feeds", "poll": "/sources/poll-feeds", "listed": "feeds",
         "per": "per_feed", "url": "https://a.example.com/rss", "tag": "news",
         "missing": "https://nope.example.com/rss"}


@pytest.fixture(params=[CALENDARS, FEEDS], ids=["calendars", "feeds"])
def kind(request):
    return request.param


@pytest.fixture
def client(tmp_path, monkeypatch):
    async def offline(url, client, from_bookmark_file=False):
        return MediaMeta(title=media_ingestor._fallback_title(url), description="",
                         site=media_ingestor._site_of(url),
                         media_type=media_ingestor._classify(url, from_bookmark_file))

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_ALLOW_FEED_FETCH", raising=False)
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_endpoint_subscribe_and_list(client, kind):
    resp = client.post(kind["route"], json={"url": kind["url"], "tags": [kind["tag"]]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"] == kind["url"]

    resp2 = client.get(kind["route"])
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["total"] == 1
    assert body[kind["listed"]][0]["url"] == kind["url"]


def test_endpoint_subscribe_rejects_bad_url(client, kind):
    resp = client.post(kind["route"], json={"url": "not-a-url"})
    assert resp.status_code == 422


def test_endpoint_subscribe_is_idempotent(client, kind):
    client.post(kind["route"], json={"url": kind["url"]})
    client.post(kind["route"], json={"url": kind["url"]})
    assert client.get(kind["route"]).json()["total"] == 1


def test_endpoint_unsubscribe(client, kind):
    client.post(kind["route"], json={"url": kind["url"]})
    resp = client.request("DELETE", kind["route"], json={"url": kind["url"]})
    assert resp.status_code == 200, resp.text
    assert client.get(kind["route"]).json()["total"] == 0


def test_endpoint_unsubscribe_missing_returns_404(client, kind):
    resp = client.request("DELETE", kind["route"], json={"url": kind["missing"]})
    assert resp.status_code == 404


def test_endpoint_poll_makes_no_request_by_default(client, kind):
    client.post(kind["route"], json={"url": kind["url"]})
    resp = client.post(kind["poll"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["polled"] == 0
    assert body["skipped_no_network"] == 1


def test_endpoint_poll_with_no_subscriptions(client, kind):
    resp = client.post(kind["poll"])
    assert resp.status_code == 200
    assert resp.json() == {"polled": 0, "new": 0, kind["per"]: []}
