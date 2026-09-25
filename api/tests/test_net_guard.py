"""G135 R-R10 — no server-side fetch of a URL someone else chose may reach this
Mac's loopback, its LAN, a tailnet peer or a metadata address."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from api.services import link_enrichment, logo_service, media_ingestor, net_guard

PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:4040/api/tunnels",       # the ngrok inspector
    "http://127.0.0.1:8000/connections",       # the backend itself
    "http://10.0.0.1/", "http://192.168.1.1/admin", "http://172.16.0.9/",
    "http://169.254.169.254/latest/meta-data",  # cloud metadata
    "http://100.100.100.100/",                  # tailnet (CGNAT) — neither private nor global
    "http://100.64.0.7:8765/mcp",
    "http://[::1]:8000/", "http://[fd7a:115c:a1e0::1]/", "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/", "file:///etc/hosts", "ftp://example.com/x", "http://", "not a url",
])
def test_private_and_odd_urls_are_refused(url):
    assert net_guard.is_fetchable_url(url, resolver=PUBLIC) is False


def test_a_public_name_and_a_public_literal_are_allowed():
    assert net_guard.is_fetchable_url("https://example.com/post", resolver=PUBLIC)
    assert net_guard.is_fetchable_url("http://93.184.216.34/")


def test_a_name_that_resolves_inward_is_refused():
    assert not net_guard.is_fetchable_url("http://localhost/", resolver=lambda h: ["127.0.0.1"])
    assert not net_guard.is_fetchable_url("http://mixed.example/", resolver=lambda h: ["93.184.216.34", "10.0.0.2"])
    assert not net_guard.is_fetchable_url("http://nowhere.example/", resolver=lambda h: [])


def test_the_logo_ladder_now_refuses_tailnet_addresses_too():
    assert logo_service._is_public_ip("100.100.100.100") is False
    assert logo_service._is_public_ip("93.184.216.34") is True


def test_the_httpx_hook_refuses_every_hop():
    with pytest.raises(net_guard.UnsafeURL):
        asyncio.run(net_guard.httpx_request_guard(httpx.Request("GET", "http://127.0.0.1:9/")))
    asyncio.run(net_guard.httpx_request_guard(httpx.Request("GET", "http://93.184.216.34/")))


def test_the_async_check_never_resolves_on_the_event_loop(monkeypatch):
    # getaddrinfo blocks; the backend serves every route from one loop.
    import threading

    seen = []
    monkeypatch.setattr(net_guard, "_resolve_host",
                        lambda host: seen.append(threading.current_thread()) or ["93.184.216.34"])
    assert asyncio.run(net_guard.is_fetchable_url_async("https://example.com/")) is True
    assert seen and seen[0] is not threading.main_thread()


class _Resp:
    def __init__(self, status=200, headers=None, text=""):
        self.status_code = status
        self.headers = headers if headers is not None else {"content-type": "text/html"}
        self.text = text

    def raise_for_status(self):
        return None


class _SeqClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        return self.responses.pop(0)


def _fallback():
    return media_ingestor.MediaMeta(title="fallback", description="", site=None, media_type="url")


def test_opengraph_refuses_a_private_url_before_any_request():
    client, fb = _SeqClient(), _fallback()
    meta = asyncio.run(media_ingestor._enrich_opengraph("http://192.168.1.1/admin", client, fb))
    assert meta is fb and client.calls == []


def test_opengraph_stops_at_a_redirect_into_the_lan():
    client, fb = _SeqClient(_Resp(302, {"location": "http://10.0.0.5/secret"})), _fallback()
    meta = asyncio.run(media_ingestor._enrich_opengraph("https://example.com/a", client, fb))
    assert meta is fb and client.calls == ["https://example.com/a"]


def test_opengraph_follows_a_public_redirect_and_reads_the_page():
    page = "<html><head><meta property='og:title' content='Landed'></head></html>"
    client = _SeqClient(_Resp(301, {"location": "/b"}), _Resp(200, {"content-type": "text/html"}, page))
    meta = asyncio.run(media_ingestor._enrich_opengraph("https://example.com/a", client, _fallback()))
    assert meta.title == "Landed"
    assert client.calls == ["https://example.com/a", "https://example.com/b"]


def test_the_backfill_fetch_never_opens_a_client_for_a_private_url(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no client for a private URL")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    result = asyncio.run(link_enrichment.default_fetch("http://127.0.0.1:9/x", settings=None))
    assert result.status == "failed:private_host"


def test_the_summarizer_never_fetches_a_private_url(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no client for a private URL")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    assert asyncio.run(link_enrichment.default_summarize("t", "http://10.1.2.3/", settings=None)) is None


def test_the_backfill_fetch_stops_at_a_redirect_into_the_lan(monkeypatch):
    # The pre-check passes a public URL; the httpx request hook must then
    # refuse the inward hop, and the fetcher must file it as private_host.
    requested: list[str] = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://10.0.0.5/secret"})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    result = asyncio.run(link_enrichment.default_fetch("https://example.com/a", settings=None))
    assert result.status == "failed:private_host"
    assert requested == ["https://example.com/a"]
