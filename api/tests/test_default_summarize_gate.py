"""G61 phase 2 S0 — Stage 5.57's page read rides the ToS rail and the gate.

Spec §2 (the fetch defect) and plan R-AC18: the in-cycle link summarizer read
pages with no `CICADA_ALLOW_CONNECTOR_FETCH` gate, on a 5 s timeout, with the
default proxy environment, no blocked-status handling and `resp.text[:1.5 MB]`
(the whole body downloaded first). It now goes through `default_fetch` — the
rail's own transport — and the gate decides whether Sleep may call it at all.
Hermetic: every client is a MockTransport; conftest resolves every host to a
public address and sets the gate off.
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import httpx

from api.services import link_enrichment, markdown_parser, sleep_cycle

CHUNK = 64 * 1024


def _client(monkeypatch, handler, built: list | None = None):
    real = httpx.AsyncClient

    def client(**kw):
        if built is not None:
            built.append(kw)
        return real(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(httpx, "AsyncClient", client)


def _boom(*a, **k):
    raise AssertionError("no client may be built")


async def _never(*a, **k):
    raise AssertionError("no summary for a page that was not read")


def test_the_gate_off_means_stage_5_57_gets_no_summarizer(monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    assert sleep_cycle._link_summarizer() is None


def test_the_gate_on_hands_stage_5_57_the_rail_summarizer(monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    assert sleep_cycle._link_summarizer() is link_enrichment.default_summarize


def test_stage_5_57_asks_the_gate_and_never_names_the_summarizer_itself():
    src = inspect.getsource(sleep_cycle._run_stages)
    assert "summarize_fn=_link_summarizer()" in src
    assert "default_summarize" not in src


def test_with_the_gate_off_a_thin_page_is_never_fetched(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    monkeypatch.setattr(httpx, "AsyncClient", _boom)
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    markdown_parser.write(
        memory / "entities" / "media-alpha-notes.md",
        {"name": "Alpha notes", "type": "media", "status": "active",
         "source_episodes": ["ep_2026-09-01_001"],
         "media": {"url": "https://example.com/alpha", "media_type": "website"}},
        "## Summary\nA saved link.",
    )
    settings = SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini", link_enrich_enabled=True,
                               link_enrich_max_per_cycle=20, link_enrich_min_desc_len=120,
                               link_enrich_excerpt_chars=2000)
    n = asyncio.run(link_enrichment.enrich_media_links(
        memory, [], settings, summarize_fn=sleep_cycle._link_summarizer()))
    assert n == 0


def test_the_summarizer_reads_at_most_the_rails_byte_cap_on_the_rails_client(monkeypatch):
    pulled: list[int] = []

    async def body():
        yield b"<html><head><title>Alpha</title></head><body><main>"
        for _ in range(32):  # 2 MiB on offer
            pulled.append(CHUNK)
            yield b"<p>" + b"alpha project notes " * (CHUNK // 20) + b"</p>\n"

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=body())

    built: list[dict] = []
    _client(monkeypatch, handler, built)
    seen: list[str] = []

    async def summary(title, excerpt, url, settings):
        seen.append(excerpt)
        return "A synthetic page about alpha-project."

    monkeypatch.setattr(link_enrichment, "_summarize_excerpt", summary)
    out = asyncio.run(link_enrichment.default_summarize("Alpha", "https://example.com/alpha", settings=None))
    assert out == "A synthetic page about alpha-project."
    assert sum(pulled) <= link_enrichment.FETCH_MAX_BYTES + CHUNK, "the download is cut, not sliced"
    assert built[0]["timeout"] == link_enrichment.FETCH_TIMEOUT_S
    assert built[0]["trust_env"] is False
    assert seen and len(seen[0]) <= 2000


def test_a_blocked_page_is_never_summarized_or_retried(monkeypatch):
    requested: list[str] = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(403, headers={"content-type": "text/html"}, text="no")

    _client(monkeypatch, handler)
    monkeypatch.setattr(link_enrichment, "_summarize_excerpt", _never)
    out = asyncio.run(link_enrichment.default_summarize("Alpha", "https://example.com/alpha", settings=None))
    assert out is None and requested == ["https://example.com/alpha"]
