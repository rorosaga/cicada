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
