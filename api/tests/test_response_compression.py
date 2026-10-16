"""API responses are gzipped (level 1) only for a client on another machine (2026-10-16 perf, owner decision 3).

On one Mac the bytes cross loopback and compressing them saves nothing; a headless server's client crosses a network,
where the owner-scale `/graph` goes from 10.5 MB to ~0.9 MB. ETags and 304s are unaffected.
"""
from __future__ import annotations

import gzip

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from api import config, main
from api.services import markdown_parser, response_compression

BIG = {"nodes": [{"id": f"alpha-{i:04d}", "name": f"Alpha {i}", "type": "project"} for i in range(400)]}
REMOTE = ("100.64.0.7", 52000)     # a tailnet address
LOCAL = ("127.0.0.1", 52000)


def _app() -> Starlette:
    async def big(request):
        return JSONResponse(BIG, headers={"ETag": '"abc"'})

    async def small(request):
        return JSONResponse({"ok": True})

    async def image(request):
        return Response(b"\x89PNG" + b"\0" * 5000, media_type="image/png")

    async def events(request):
        async def stream():
            yield "event: ping\ndata: {}\n\n" * 200
        return StreamingResponse(stream(), media_type="text/event-stream")

    app = Starlette(routes=[Route("/big", big), Route("/small", small), Route("/image", image),
                            Route("/events", events)])
    app.add_middleware(response_compression.RemoteGZipMiddleware)
    return app


def _get(path, *, client=LOCAL, headers=None):
    return TestClient(_app(), client=client).get(path, headers={"Accept-Encoding": "gzip", **(headers or {})})


def test_a_loopback_client_is_answered_exactly_as_before():
    r = _get("/big")
    assert "content-encoding" not in r.headers
    assert r.json() == BIG
    assert "accept-encoding" not in r.headers.get("vary", "").lower()


@pytest.mark.parametrize("client,headers", [
    (REMOTE, {}),                                            # reached directly on an overlay address
    (LOCAL, {"X-Forwarded-For": "100.64.0.7"}),              # `tailscale serve` in front of 127.0.0.1
    (LOCAL, {"Tailscale-User-Login": "alice-example@example.com"}),
    (LOCAL, {"Forwarded": "for=100.64.0.7"}),
    (LOCAL, {"Authorization": "Bearer cic_dev_abc123_secret"}),   # a device token: an SSH tunnel from a client
    (("::ffff:100.64.0.7", 1), {}),
])
def test_another_machine_gets_gzip_level_one_with_the_same_etag(client, headers):
    r = _get("/big", client=client, headers=headers)
    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["etag"] == '"abc"'
    assert "accept-encoding" in r.headers["vary"].lower()
    assert r.json() == BIG   # the client decodes it


def test_level_one_is_used(monkeypatch):
    levels = []
    real = gzip.GzipFile.__init__

    def spy(self, *args, **kwargs):
        levels.append(kwargs.get("compresslevel"))
        real(self, *args, **kwargs)

    monkeypatch.setattr(gzip.GzipFile, "__init__", spy)
    _get("/big", client=REMOTE)
    assert levels == [1]


@pytest.mark.parametrize("client", [("127.0.0.1", 1), ("::1", 1), ("::ffff:127.0.0.1", 1), ("localhost", 1)])
def test_every_loopback_spelling_is_local(client):
    assert "content-encoding" not in _get("/big", client=client).headers


def test_the_master_token_on_loopback_is_local():
    r = _get("/big", headers={"Authorization": "Bearer some-master-token"})
    assert "content-encoding" not in r.headers


def test_nothing_is_compressed_for_a_client_that_did_not_ask():
    r = TestClient(_app(), client=REMOTE).get("/big", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in r.headers


def test_small_bodies_compressed_bodies_and_the_event_stream_pass_through():
    for path in ("/small", "/image", "/events"):
        r = _get(path, client=REMOTE)
        assert "content-encoding" not in r.headers, path
    assert _get("/image", client=REMOTE).content.startswith(b"\x89PNG")


@pytest.fixture
def server(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    for i in range(60):
        markdown_parser.write(memory / "entities" / f"alpha-{i:04d}.md",
                              {"name": f"Alpha {i:04d}", "type": "project", "confidence": 0.8},
                              f"## Summary\nalpha-{i:04d} is a synthetic page about synthetic things.")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


def test_the_app_compresses_graph_for_a_remote_client_and_its_304_is_unchanged(server):
    local = TestClient(main.app, client=LOCAL).get("/graph", headers={"Accept-Encoding": "gzip"})
    remote = TestClient(main.app, client=REMOTE).get("/graph", headers={"Accept-Encoding": "gzip"})
    assert local.status_code == remote.status_code == 200
    assert "content-encoding" not in local.headers
    assert remote.headers["content-encoding"] == "gzip"
    assert int(remote.headers["content-length"]) < len(local.content) / 3
    assert remote.json() == local.json()
    etag = local.headers["etag"]
    assert remote.headers["etag"] == etag
    again = TestClient(main.app, client=REMOTE).get("/graph", headers={"Accept-Encoding": "gzip",
                                                                       "If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == etag
