"""A stand-in for the Claude API at the HTTP layer (G237): the real SDK, its real streaming parser, a fake server.

Answers `POST /v1/messages` with the event stream's recorded shape and `GET /v1/models` with the list's. It models the
one behaviour the design rests on: a cache entry for a marked prefix is readable only once its response has started
(`shared/prompt-caching.md`), so parallel calls on a cold prefix all write and a call after them reads. Token counts are
characters / 3, close enough to read a hit rate; no test relies on the exact number.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import anthropic
import httpx2

MODELS_SHAPE = [
    {"id": "claude-haiku-5-5", "line": "haiku", "lifecycle": "active", "created_at": "2026-09-01T00:00:00Z",
     "display_name": "Claude Haiku 5.5", "max_tokens": 128000, "max_input_tokens": 1000000},
    {"id": "claude-sonnet-5-5", "line": "sonnet", "lifecycle": "active", "created_at": "2026-08-01T00:00:00Z",
     "display_name": "Claude Sonnet 5.5", "max_tokens": 128000, "max_input_tokens": 1000000},
    {"id": "claude-opus-5-5", "line": "opus", "lifecycle": "active", "created_at": "2026-07-01T00:00:00Z",
     "display_name": "Claude Opus 5.5", "max_tokens": 128000, "max_input_tokens": 1000000},
    {"id": "claude-haiku-4-5-20251001", "line": "haiku", "lifecycle": "active", "created_at": "2025-10-01T00:00:00Z",
     "display_name": "Claude Haiku 4.5", "max_tokens": 64000, "max_input_tokens": 200000},
    {"id": "claude-sonnet-4-5-20250929", "line": "sonnet", "lifecycle": "deprecated",
     "created_at": "2025-09-29T00:00:00Z", "display_name": "Claude Sonnet 4.5", "max_tokens": 64000},
    {"id": "claude-opus-4-1-20250805", "line": "opus", "lifecycle": "retired", "created_at": "2025-08-05T00:00:00Z",
     "display_name": "Claude Opus 4.1", "max_tokens": 32000},
]


def _tokens(text: str) -> int:
    return max(1, len(text) // 3)


def _sse(events: list[dict]) -> bytes:
    out = []
    for event in events:
        out.append(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n")
    return "".join(out).encode()


def _message_stream(*, model: str, text: str, usage: dict, stop_reason: str = "end_turn", thinking: bool = True,
                    extra_blocks: list[dict] | None = None, stop_details: dict | None = None) -> bytes:
    """`message_start`, an empty thinking block where the model thinks (display omitted is the default), the text,
    `message_delta` with the stop reason and the output count, `message_stop`."""
    start_usage = {k: usage[k] for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
                                         "cache_creation") if k in usage}
    events: list[dict] = [{"type": "message_start", "message": {
        "id": "msg_stub", "type": "message", "role": "assistant", "model": model, "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": {**start_usage, "output_tokens": 1}}},
        {"type": "ping"}]
    index = 0
    for block in extra_blocks or []:
        events += [{"type": "content_block_start", "index": index, "content_block": block},
                   {"type": "content_block_stop", "index": index}]
        index += 1
    if thinking:
        events += [{"type": "content_block_start", "index": index,
                    "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
                   {"type": "content_block_delta", "index": index,
                    "delta": {"type": "signature_delta", "signature": "sig"}},
                   {"type": "content_block_stop", "index": index}]
        index += 1
    if text:
        events += [{"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
                   {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text}},
                   {"type": "content_block_stop", "index": index}]
    events += [{"type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None, "stop_details": stop_details},
                "usage": {"output_tokens": usage["output_tokens"],
                          **({"server_tool_use": usage["server_tool_use"]} if "server_tool_use" in usage else {})}},
               {"type": "message_stop"}]
    return _sse(events)


@dataclass
class StubAnthropic:
    """``answer(body) -> str`` writes each reply. ``fail`` (a list) pops one scripted failure per call first:
    ``(status, json_body, headers)``. Records every request body; ``latency`` is how long a call takes to start."""

    answer: Callable[[dict], str] = lambda body: "{}"
    fail: list = field(default_factory=list)
    latency: float = 0.0
    models: list = field(default_factory=lambda: list(MODELS_SHAPE))
    stop_reason: str = "end_turn"
    stop_details: dict | None = None
    search_blocks: list | None = None
    refused_models: set = field(default_factory=set)
    requests: list = field(default_factory=list)
    headers_seen: list = field(default_factory=list)
    _readable: set = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.headers_seen.append(dict(request.headers))
        if request.method == "GET" and request.url.path.endswith("/models"):
            return httpx2.Response(200, json={"data": self.models, "has_more": False,
                                              "first_id": None, "last_id": None})
        body = json.loads(request.content)
        with self._lock:
            self.requests.append(body)
            failure = self.fail.pop(0) if self.fail else None
        if failure is not None:
            status, payload, headers = failure
            return httpx2.Response(status, json=payload, headers=headers)
        if body["model"] in self.refused_models:
            return httpx2.Response(404, json={"type": "error", "error": {
                "type": "not_found_error", "message": f"model: {body['model']}"}})
        system = body.get("system") or []
        marked = [b for b in system if isinstance(b, dict) and b.get("cache_control")]
        prefix = (body["model"], json.dumps(system, sort_keys=True))
        sys_tokens = sum(_tokens(b["text"]) for b in system if isinstance(b, dict))
        user_tokens = sum(_tokens(m["content"]) for m in body["messages"] if isinstance(m["content"], str))
        with self._lock:
            hit = bool(marked) and prefix in self._readable
        if self.latency:
            time.sleep(self.latency)
        usage: dict = {"output_tokens": _tokens(reply := self.answer(body))}
        if not marked:
            usage["input_tokens"] = sys_tokens + user_tokens
        elif hit:
            usage |= {"input_tokens": user_tokens, "cache_read_input_tokens": sys_tokens,
                      "cache_creation_input_tokens": 0}
        else:
            usage |= {"input_tokens": user_tokens, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": sys_tokens,
                      "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": sys_tokens}}
        if self.search_blocks:
            usage["server_tool_use"] = {"web_search_requests": 1}
        if marked:
            with self._lock:
                self._readable.add(prefix)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=_message_stream(
            model=body["model"], text=reply, usage=usage, stop_reason=self.stop_reason,
            stop_details=self.stop_details, extra_blocks=self.search_blocks))

    def client(self, key: str, *, max_retries: int = 0) -> anthropic.Anthropic:
        return anthropic.Anthropic(api_key=key, base_url="https://api.anthropic.com", max_retries=max_retries,
                                   http_client=httpx2.Client(transport=httpx2.MockTransport(self.handle)))

    def install(self, monkeypatch, *, key: str = "stub-key-not-real", max_retries: int = 0) -> None:
        """The real ``anthropic_engine`` over this server. ``max_retries`` 0 unless a test is about the SDK's own."""
        from api.services import anthropic_engine

        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
        anthropic_engine.reset_clients()
        monkeypatch.setattr(anthropic_engine, "_build_client", lambda k: self.client(k, max_retries=max_retries))
        monkeypatch.setattr(anthropic_engine, "MAX_RETRIES", max_retries)
        anthropic_engine.reset_prefixes()


def error_body(kind: str, message: str, code: str | None = None) -> dict:
    error: dict = {"type": kind, "message": message}
    if code:
        error["details"] = {"error_code": code}
    return {"type": "error", "error": error, "request_id": "req_stub"}
