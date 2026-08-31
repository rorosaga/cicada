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
import pytest

from api.services import logo_service


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

            def __call__(self, argv, *, stdin=None, timeout=None, cwd=None):
                self.calls.append({"argv": list(argv), "stdin": stdin,
                                   "timeout": timeout, "cwd": cwd})
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
    """The breaker and the models-used ledger are process-global; a tripped
    breaker leaking into the next test would make it fail-fast for free."""
    from api.services import agent_engine

    agent_engine.reset_breaker()
    agent_engine.reset_models_used()
    yield
    agent_engine.reset_breaker()
    agent_engine.reset_models_used()
