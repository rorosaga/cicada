"""Suite-wide fixtures.

The local API now requires a bearer token (api/services/auth.py). The existing
tests hit ``TestClient(main.app)`` without headers, so auth is switched off for
every test by default; ``test_auth.py`` re-enables it explicitly.

Logo fetching (G59) is likewise off for the whole suite: no test may reach the
network. The tests that exercise the fetch ladder inject their own fetcher,
which runs regardless of this flag — the same seam ``feed_registry`` uses.

The logo fetch ladder also runs an SSRF host check (G59 round 1) ahead of
every request and redirect hop, resolving each hostname via an injectable
``resolver``. That check runs even when a test injects its own fake
``fetcher`` — the domain still gets resolved — so a default resolver that hit
real DNS would make every ``*.example``/``*.com`` fixture domain in the suite
fail closed (unresolvable in a network-less sandbox = refused). Default it to
a fixed public address instead; the handful of tests that exercise the guard
itself pass their own ``resolver=``, which always wins over this default.
"""
import os
from pathlib import Path

import json
import sys

import pytest

from api.services import logo_service
from api.services import codex_app_server as _codex_app_server
from api.services.connections import base as _conn_base

#: Captured at import, before `_no_real_agent_spawn` replaces it per test —
#: `fake_cli` restores it so a test can drive the genuine subprocess path
#: against a binary that can never reach a vendor.
_REAL_RUN_CLI_SYNC = _conn_base.run_cli_sync
#: The genuine app-server transport, captured before `_no_real_codex_app_server`
#: replaces it per test (R-E18).
_REAL_STDIO_TRANSPORT = _codex_app_server._stdio_transport


@pytest.fixture(scope="session", autouse=True)
def _forget_the_developers_dotenv():
    """Stop `api/.env` leaking into the suite through litellm.

    `litellm/__init__.py` calls `load_dotenv()` at import time, so the first
    test that transitively imports it — anything reaching `api.main` — copies
    the developer's own `api/.env` into `os.environ` for the rest of the
    process. Every later bare `Settings()` then reads that machine's config
    instead of the packaged defaults, which is order-dependent by construction:
    the same test passes alone and fails in the full run, and which tests fail
    depends on collection order and on what the developer happens to have
    configured. It cost this session a false attribution before it was found.

    Import litellm here so its side effect is done deterministically, then drop
    exactly the names `api/.env` defines. A test that wants one of them sets it
    with `monkeypatch.setenv`, which runs after this and still wins.
    """
    try:
        import litellm  # noqa: F401  (imported for its load_dotenv side effect)
    except Exception:
        pass

    dotenv = Path(__file__).resolve().parents[1] / ".env"
    if not dotenv.exists():
        return
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        os.environ.pop(line.split("=", 1)[0].strip(), None)


@pytest.fixture(autouse=True)
def _default_cicada_home(tmp_path, monkeypatch):
    """G117: `owner_identity.resolve_observer` now sits on the observer/
    claim-write hot path (`agentic_write.write_claim`, `telegram_capture`,
    `inbox_service._owner_observer`), so it calls `cicada_home()` — reading
    `~/.cicada/owner.json` — on every claim write those functions make.
    Without a default here, any test exercising those call sites without
    setting `CICADA_HOME` itself would read (and `cicada_home()`'s own
    ``mkdir`` would touch) the developer's REAL ``~/.cicada`` — the same
    class of leak `_disable_connector_fetch` below already guards against
    for `secrets.env`. A test that wants a specific `CICADA_HOME` still
    wins: `monkeypatch.setenv` inside the test body runs after fixture
    setup and simply overwrites this default.
    """
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "_default_cicada_home"))


@pytest.fixture(autouse=True)
def _no_real_agent_home(tmp_path, monkeypatch):
    """G138: the handshake and GET /skills/recommended look for SKILL.md files
    and plugin ids under the agents' home. The suite must never read the
    developer's own `~/.claude` — every test gets an empty tmp home."""
    from api.services import skill_catalog

    home = tmp_path / "_agent_home"
    monkeypatch.setattr(skill_catalog, "agent_home", lambda: home)


@pytest.fixture(autouse=True)
def _no_live_sleep_probe(monkeypatch):
    """G135 final review: a stdio `cicada_write_claim` asks the backend's
    `GET /sleep/status` before committing. Unpinned, every such test would hit
    whatever backend is listening on 127.0.0.1:8000 — the developer's live
    one included — and a cycle running there would change the test's outcome.
    Pinned to "not running"; the test for the gate patches it back."""
    from api.services import mcp_tools

    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda url, headers: False)


@pytest.fixture(autouse=True)
def _disable_api_auth(monkeypatch):
    monkeypatch.setenv("CICADA_API_AUTH", "off")


@pytest.fixture(autouse=True)
def _disable_logo_fetch(monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")


@pytest.fixture(autouse=True)
def _default_public_logo_resolver(monkeypatch):
    monkeypatch.setattr(logo_service, "_resolve_host", lambda host: ["93.184.216.34"])


@pytest.fixture(autouse=True)
def _default_public_net_guard_resolver(monkeypatch):
    """G135 R-R10: `net_guard` resolves every hostname a fetcher is about to
    request, exactly as the logo ladder above does — so the same fixed public
    address stands in for DNS, or every `example.com` fixture would fail closed
    in a network-less run. Tests of the guard itself pass `resolver=`."""
    from api.services import net_guard

    monkeypatch.setattr(net_guard, "_resolve_host", lambda host: ["93.184.216.34"])


@pytest.fixture(autouse=True)
def _disable_telemetry(monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "off")


@pytest.fixture(autouse=True)
def _disable_connector_fetch(monkeypatch):
    """G71: no test may reach Pinterest, Reddit, or X's default transport.

    Connector transports are injected in tests, but the default transport is
    additionally gated on this variable so a developer who has real credentials
    in ``~/.cicada/secrets.env`` — which `cicada_home()` resolves to by default
    — cannot have a shell export turn a test run into live API traffic.

    Final-review H2: the gate flipped from opt-IN to opt-OUT (default ON,
    mirroring ``CICADA_ALLOW_LOGO_FETCH``), so belt-and-braces this explicitly
    to "off" — deleting the var (the old opt-in-era approach) would now leave
    it at its new default of allowed. Every connector test still injects its
    own ``http_fn`` regardless (which bypasses this gate entirely), so this is
    a second, redundant layer, not the only thing standing between the suite
    and the network — same posture as ``_disable_logo_fetch`` above.
    """
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")


@pytest.fixture(autouse=True)
def _no_real_agent_spawn(monkeypatch):
    """G74(a): no test may spawn the real `claude` CLI.

    Every agent-engine test injects a runner; this makes a missed injection
    fail loudly at the seam instead of quietly shelling out (and spending the
    developer's plan quota) on whatever machine runs the suite.
    """
    from api.services.connections import base

    def _boom(*args, **kwargs):  # pragma: no cover - the guard itself
        raise AssertionError(
            "a test reached the real `claude` runner — inject a runner instead"
        )

    monkeypatch.setattr(base, "run_cli_sync", _boom)


@pytest.fixture(autouse=True)
def _no_real_codex_app_server(monkeypatch):
    """R-E18: no test may spawn the real `codex app-server`. The default
    transport degrades to "unavailable" (→ every caller falls back to `codex
    login status`), deterministically; a test that wants a snapshot injects
    one. The cache is cleared around every test."""
    async def _unavailable(*, timeout):
        raise FileNotFoundError("codex app-server is not spawned in tests — inject a transport")

    monkeypatch.setattr(_codex_app_server, "_stdio_transport", _unavailable)
    _codex_app_server.invalidate()
    yield
    _codex_app_server.invalidate()


@pytest.fixture
def real_app_server_transport():
    """The genuine stdio transport, for the one test that drives it against a
    fake `codex app-server` script (never the real binary)."""
    return _REAL_STDIO_TRANSPORT


@pytest.fixture(autouse=True)
def _no_plan_override_env(monkeypatch):
    """R-E6: a developer's shell must not leak an ANTHROPIC_BASE_URL or a
    CODEX_API_KEY into `how` sentences the suite pins verbatim."""
    for key in (*_conn_base.CLAUDE_PLAN_OVERRIDE_ENV, *_conn_base.CODEX_PLAN_OVERRIDE_ENV,
                "CODEX_HOME", "CLAUDE_CODE_RETRY_WATCHDOG"):
        monkeypatch.delenv(key, raising=False)


_FAKE_CLI = r'''#!@PYTHON@
"""A stand-in vendor CLI for hermetic tests: it records what it was given
and prints a recorded stream. It can never reach a vendor."""
import json, os, sys, time
watch = json.loads(os.environ.get("CICADA_FAKE_WATCH") or "[]")
record = {"argv": sys.argv[1:], "env": {k: os.environ.get(k) for k in watch},
          "stdin": sys.stdin.read()}
with open(os.environ["CICADA_FAKE_SEEN"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\n")
with open(os.environ["CICADA_FAKE_STDOUT"], encoding="utf-8") as fh:
    sys.stdout.write(fh.read())
sys.stdout.flush()
time.sleep(float(os.environ.get("CICADA_FAKE_SLEEP") or 0))
sys.exit(int(os.environ.get("CICADA_FAKE_RC") or 0))
'''


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    """Install a fake `claude`/`codex` behind `resolve_binary`'s
    `CICADA_<NAME>_CLI` override and restore the REAL `run_cli_sync`, so the
    genuine argv/env/stdin path runs. Returns
    `install(name, stdout, *, rc=0, sleep=0.0, watch=()) -> read_seen`, where
    `read_seen()` is every invocation's `{argv, env (watched names), stdin}`.
    The `CICADA_FAKE_*` variables pass the scrub by design (not in any list)."""
    monkeypatch.setattr(_conn_base, "run_cli_sync", _REAL_RUN_CLI_SYNC)
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)

    def install(name, stdout, *, rc=0, sleep=0.0, watch=()):
        script = bindir / name
        script.write_text(_FAKE_CLI.replace("@PYTHON@", sys.executable), encoding="utf-8")
        script.chmod(0o755)
        out = tmp_path / f"{name}.stdout"
        out.write_text(stdout, encoding="utf-8")
        seen = tmp_path / f"{name}.seen.jsonl"
        monkeypatch.setenv(f"CICADA_{name.upper()}_CLI", str(script))
        monkeypatch.setenv("CICADA_FAKE_STDOUT", str(out))
        monkeypatch.setenv("CICADA_FAKE_SEEN", str(seen))
        monkeypatch.setenv("CICADA_FAKE_RC", str(rc))
        monkeypatch.setenv("CICADA_FAKE_SLEEP", str(sleep))
        monkeypatch.setenv("CICADA_FAKE_WATCH", json.dumps(list(watch)))

        def read_seen():
            if not seen.exists():
                return []
            return [json.loads(line) for line in seen.read_text(encoding="utf-8").splitlines()
                    if line.strip()]

        return read_seen

    return install


@pytest.fixture(autouse=True)
def _reset_connections_registry():
    """G74(a) fix round 1 (M1): ``sleep_cycle._probe_engine_cheaply`` now
    reads ``connections.registry``'s process-global, 30 s-TTL status cache
    before ever considering a spawn. Reset the singleton around every test
    so a status one test warms (e.g. probing claude-plan) can never leak
    into another's assertions — mirrors ``_reset_agent_engine_state`` below
    for the same class of process-global leak."""
    from api.services.connections import registry as connections_registry

    connections_registry.reset_registry()
    yield
    connections_registry.reset_registry()


@pytest.fixture
def agent_envelopes():
    """Envelopes recorded from `claude` 2.1.252 (spec §9) plus the three
    failure shapes the spec could not produce on demand.

    `success` is the V2b/V1d call: input_tokens 2 with 19,631 cache-creation
    tokens, and a haiku side-call alongside the requested sonnet.
    """
    return {
        "success": {
            "type": "result", "subtype": "success", "is_error": False,
            "result": '{"entities": [], "relationships": []}',
            "stop_reason": "end_turn", "terminal_reason": None,
            "session_id": "ses-fixture", "num_turns": 1,
            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 19631,
                      "cache_read_input_tokens": 0, "output_tokens": 57},
            "modelUsage": {
                "claude-sonnet-5": {"canonicalModel": "claude-sonnet-5", "inputTokens": 2,
                                    "outputTokens": 57, "cacheReadInputTokens": 0,
                                    "cacheCreationInputTokens": 19631,
                                    "costUSD": 0.0917, "costBasis": "list"},
                "claude-haiku-4-5": {"canonicalModel": "claude-haiku-4-5", "inputTokens": 120,
                                     "outputTokens": 8, "costUSD": 0.0003, "costBasis": "list"},
            },
            "total_cost_usd": 0.092, "duration_ms": 1600,
            "api_error_status": None, "permission_denials": [], "uuid": "u-1",
        },
        "structured": {
            "type": "result", "subtype": "success", "is_error": False,
            "result": '{"ok": true}', "structured_output": {"ok": True},
            "stop_reason": "end_turn", "terminal_reason": None,
            "usage": {"input_tokens": 781, "output_tokens": 6},
            "modelUsage": {"claude-haiku-4-5": {"canonicalModel": "claude-haiku-4-5",
                                                "inputTokens": 781, "outputTokens": 6,
                                                "costUSD": 0.0003, "costBasis": "list"}},
            "total_cost_usd": 0.0003, "duration_ms": 900,
        },
        "schema_constrained_success": {
            # Review fix round 1, nit 2: the exact live-verified ground-truth
            # shape for a --json-schema call (spec §9 V1b) — `stop_reason`
            # "tool_use" with `is_error: False`, `subtype: "success"` and
            # `terminal_reason: "completed"`. This is THE specific trap: code
            # that (wrongly) treated `stop_reason == "tool_use"` as a failure
            # would break every structured call.
            "type": "result", "subtype": "success", "is_error": False,
            "result": '{"decision": "same"}', "structured_output": {"decision": "same"},
            "stop_reason": "tool_use", "terminal_reason": "completed",
            "usage": {"input_tokens": 3, "output_tokens": 12},
            "modelUsage": {"claude-haiku-4-5": {"canonicalModel": "claude-haiku-4-5",
                                                "inputTokens": 3, "outputTokens": 12,
                                                "costUSD": 0.0001, "costBasis": "list"}},
            "total_cost_usd": 0.0001, "duration_ms": 500,
        },
        "budget_exhausted": {
            "type": "result", "subtype": "error", "is_error": True,
            "terminal_reason": "budget_exhausted",
            "result": "Budget exhausted for this window.", "stop_reason": None,
        },
        "model_not_found": {
            "type": "result", "subtype": "error", "is_error": True,
            "terminal_reason": "api_error", "api_error_status": 404,
            "result": "model not found: claude-nope", "stop_reason": None,
        },
        "rate_limited": {
            "type": "result", "subtype": "error", "is_error": True,
            "terminal_reason": "api_error", "api_error_status": 429,
            "result": "rate limit exceeded, please retry later", "stop_reason": None,
        },
        "not_logged_in": {
            "type": "result", "subtype": "error", "is_error": True,
            "terminal_reason": "api_error", "api_error_status": None,
            "result": "Not logged in. Run `claude auth login`.", "stop_reason": None,
        },
        "unclassified_error": {
            "type": "result", "subtype": "error", "is_error": True,
            "terminal_reason": "something_new", "result": "unknown failure", "stop_reason": None,
        },
    }


@pytest.fixture
def claude_stream(agent_envelopes):
    """`claude -p --output-format stream-json --verbose` stdout (R-E1).
    `system/init` and `rate_limit_event` are shaped from claude-agent-sdk
    0.2.157's own parser tests (R1 §2.7), `system/api_retry` from
    code.claude.com/docs/en/headless; the `result` line is an
    `agent_envelopes` entry verbatim. `result=None` omits it (a truncated
    stream). The live-recorded twin is fixtures/claude_stream_live.jsonl."""
    def make(result="success", *, rate_limits=(), retries=(), api_key_source="none"):
        lines = [{"type": "system", "subtype": "init", "session_id": "ses-fixture",
                  "model": "claude-sonnet-5", "tools": [], "mcp_servers": [],
                  "permissionMode": "default", "apiKeySource": api_key_source}]
        for retry in retries:
            lines.append({"type": "system", "subtype": "api_retry", "attempt": 1,
                          "max_retries": 2, "retry_delay_ms": 500, **retry})
        for info in rate_limits:
            lines.append({"type": "rate_limit_event", "rate_limit_info": info,
                          "uuid": "u-fixture", "session_id": "ses-fixture"})
        if result is not None:
            lines.append(agent_envelopes[result])
        return "\n".join(json.dumps(line) for line in lines) + "\n"

    return make


@pytest.fixture
def codex_events():
    """`codex exec --json` stdout recorded on codex-cli 0.154.0 (2026-09-23).
    `ok` is R2's trivial structured run (ids replaced); `signed_out` is a real
    signed-out run against an empty isolated home (cf-ray / request ids
    dropped) — note the top-level `error` RETRY NOTICES before `turn.failed`
    (R-E16). `usage_limit` and `reconnected_then_ok` are shaped from those two;
    the exact usage-limit text could not be produced on demand."""
    def lines(*objs):
        return "\n".join(json.dumps(o) for o in objs) + "\n"

    started = ({"type": "thread.started", "thread_id": "t-fixture"}, {"type": "turn.started"})
    warning = {"type": "item.completed", "item": {"id": "item_0", "type": "error", "message":
               "Skill descriptions were shortened to fit the skills context budget. Codex can "
               "still see every skill, but some descriptions are shorter."}}

    def answer(text):
        return {"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": text}}

    done = {"type": "turn.completed", "usage": {"input_tokens": 11589, "cached_input_tokens": 0,
            "cache_write_input_tokens": 0, "output_tokens": 15, "reasoning_output_tokens": 0}}
    unauthorized = ("unexpected status 401 Unauthorized: Missing bearer or basic authentication "
                    "in header, url: https://api.openai.com/v1/responses")
    extraction = {"entities": [{
        "name": "alpha-project", "type": "project", "aliases": [],
        "summary": "A backend project moving from PostgreSQL to SQLite.",
        "key_facts": ["The demo is due on 2026-10-15."], "history_entries": [],
        "links": [{"url": "https://example.com/alpha-project", "title": "alpha-project repository",
                   "note": "Repository for the project."}],
        "open_questions": [], "tags": ["backend"], "confidence": 0.9, "decay_class": "active"}],
        "relationships": [{"source": "alpha-project", "target": "2026-10-15", "label": "due",
                           "evidence_quote": None}]}
    return {
        "ok": lines(*started, warning, answer('{"ok":true}'), done),
        "extraction": lines(*started, answer(json.dumps(extraction)), done),
        "signed_out": lines(
            *started,
            {"type": "error", "message": "Reconnecting... 2/5 (unexpected status 401 Unauthorized: "
             "Missing bearer or basic authentication in header, url: wss://api.openai.com/v1/responses)"},
            {"type": "item.completed", "item": {"id": "item_0", "type": "error", "message":
             "Falling back from WebSockets to HTTPS transport. " + unauthorized.replace("https://", "wss://")}},
            {"type": "error", "message": unauthorized},
            {"type": "turn.failed", "error": {"message": unauthorized}}),
        "usage_limit": lines(*started, {"type": "turn.failed", "error": {
            "message": "You've hit your usage limit. Try again later."}}),
        "reconnected_then_ok": lines(
            *started, {"type": "error", "message": "Reconnecting... 1/5 (stream disconnected before completion)"},
            answer('{"ok":true}'), done),
        "no_answer": lines(*started, done),
    }


@pytest.fixture
def agent_runner():
    """Factory: `agent_runner(envelope_or_result, ...)` -> a recording runner.

    Each positional argument is either a dict (returned as a rc-0 JSON
    envelope) or a ready-made ``CliResult``. The last one repeats once the
    list is exhausted, so a fan-out of N calls needs only one fixture.
    """
    import json as _json

    from api.services.connections.base import CliResult

    def _make(*responses):
        queue = list(responses) or [CliResult(0, "{}", "")]

        class _Runner:
            def __init__(self):
                self.calls: list[dict] = []

            def __call__(self, argv, *, stdin=None, timeout=None, cwd=None, env_overrides=None):
                self.calls.append({"argv": list(argv), "stdin": stdin,
                                   "timeout": timeout, "cwd": cwd,
                                   "env_overrides": env_overrides})
                item = queue[min(len(self.calls) - 1, len(queue) - 1)]
                if isinstance(item, CliResult):
                    return item
                if isinstance(item, BaseException):
                    raise item
                return CliResult(0, _json.dumps(item), "")

        return _Runner()

    return _make


@pytest.fixture(autouse=True)
def _reset_agent_engine_state():
    """The models-used ledger is process-global; a tripped breaker or a
    leftover model leaking into the next test would make it fail-fast (or
    misattribute a commit trailer) for free.

    The breaker is now scoped (Devin PR #25 round 1, finding 1) — `_BREAKER`
    is keyed by whatever scope string a test used, not a single slot — so a
    plain unscoped `reset_breaker()` only clears the DEFAULT bucket. Clearing
    the dict directly catches every scope a test may have tripped (custom
    scope names included), the same blanket guarantee the old single-slot
    reset gave for free.
    """
    from api.services import agent_engine

    agent_engine._BREAKER.clear()
    agent_engine.reset_models_used()
    yield
    agent_engine._BREAKER.clear()
    agent_engine.reset_models_used()
