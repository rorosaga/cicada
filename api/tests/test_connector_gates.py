"""What the three saved-list connectors (G71 §2) share, once per connector: a sync with nothing stored is skipped
before any request, and with credentials but no `http_fn` the closed connector-fetch gate (conftest sets
CICADA_ALLOW_CONNECTOR_FETCH=off) refuses the default transport. Each connector's own behaviour stays in its
`test_connector_<name>.py`. ZERO NETWORK; every value is a placeholder."""
from __future__ import annotations

import asyncio
import os

import pytest

from api.services import media_ingestor
from api.services.connections import secrets
from api.services.connectors import pinterest, reddit, x

_NAMES = {
    pinterest: (pinterest.APP_ID_ENV, pinterest.APP_SECRET_ENV, pinterest.TOKEN_ENV),
    reddit: (reddit.CLIENT_ID_ENV, reddit.CLIENT_SECRET_ENV, reddit.USERNAME_ENV, reddit.PASSWORD_ENV),
    x: (x.CLIENT_ID_ENV, x.TOKEN_ENV, x.REFRESH_TOKEN_ENV, x.USER_ID_ENV),
}
#: What "connected" takes: a token for the two OAuth connectors, every field for Reddit.
_CONNECT = {
    pinterest: {pinterest.TOKEN_ENV: "tok-abc"},
    reddit: {reddit.CLIENT_ID_ENV: "client-id-placeholder", reddit.CLIENT_SECRET_ENV: "client-secret-placeholder",
             reddit.USERNAME_ENV: "example_user", reddit.PASSWORD_ENV: "password-placeholder"},
    x: {x.TOKEN_ENV: "tok-abc"},
}
CONNECTORS = pytest.mark.parametrize("adapter", list(_NAMES), ids=lambda a: a.CHANNEL_ID)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Credentials go to a throwaway $CICADA_HOME. `secrets.set_secret` also exports into `os.environ`, outside
    monkeypatch's reach, so every connector's names are popped on teardown too."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    names = [n for group in _NAMES.values() for n in group]
    for name in names:
        monkeypatch.delenv(name, raising=False)
    yield
    for name in names:
        os.environ.pop(name, None)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)

    async def offline(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(title=media_ingestor._fallback_title(url), description="",
                                        site=media_ingestor._site_of(url), media_type="url")

    async def no_commit(memory_path, count, paths=None):
        return None

    monkeypatch.setattr(media_ingestor, "enrich", offline)
    monkeypatch.setattr(media_ingestor, "_commit_media", no_commit)
    return memory


async def _never(method, url, **kwargs):
    raise AssertionError(f"no request may be made: {method} {url}")


@CONNECTORS
def test_sync_is_skipped_without_credentials(memory, adapter):
    result = asyncio.run(adapter.sync(memory, http_fn=_never))
    assert result["status"] == "skipped"
    assert result["reason"] == "not connected"
    assert list((memory / "episodes").glob("*.md")) == []


@CONNECTORS
def test_sync_refuses_the_default_transport_when_the_gate_is_closed(memory, adapter):
    for name, value in _CONNECT[adapter].items():
        secrets.set_secret(name, value)
    result = asyncio.run(adapter.sync(memory))  # no http_fn, gate closed by conftest
    assert result["status"] == "skipped"
    assert result["reason"] == "network disabled"
