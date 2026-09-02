# Provider Connections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user connect a Claude plan, a ChatGPT plan, usage-based API keys, and a local Ollama to Cicada — see plan + price, connect, disconnect — without Cicada ever holding a vendor token.

**Architecture:** A `ConnectionAdapter` protocol with one file per provider under `api/services/connections/`; subscription adapters delegate entirely to the vendor CLI (`claude auth …`, `codex login …`) and only *probe* login state; BYOK keys live in `~/.cicada/secrets.env` hot-loaded into `os.environ`; a registry + `/connections` router expose it; a SwiftUI Connections page renders cards. Bearer-token auth on `localhost:8000` is Task 1 because a key-writing endpoint must not ship without it.

**Tech Stack:** Python 3.12 / FastAPI / pydantic v2 (`CamelModel`) / asyncio subprocess; SwiftUI (macOS 14) / `@Observable`; pytest (`api/.venv/bin/python -m pytest`), `swift build` (`app/CicadaApp`).

**Spec:** `docs/superpowers/specs/2026-08-28-connections-and-consumption-dashboard-design.md` (§2, §3, §5, §7, §8)

## Global Constraints

- Never read the macOS Keychain item `Claude Code-credentials`, never call `api.anthropic.com/api/oauth/usage` or `chatgpt.com/backend-api/wham/usage`, never persist a vendor token, email, or plan snapshot to disk (spec §2, §5.3).
- Child processes get an env with `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY` removed (spec §5.2).
- Machine-global state lives under `CICADA_HOME` (default `~/.cicada`, mode 0700); files are mode 0600 (spec §3.3–3.4).
- `GET /healthz` stays auth-free; every other route requires `Authorization: Bearer <token>` unless `CICADA_API_AUTH=off` (spec §5.5).
- All API wire keys are camelCase via `CamelModel` (`api/models/schemas.py:8`).
- Swift decoding stays tolerant (`decodeIfPresent … ?? default`), matching `Contributor` in `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift:163`.
- Run Python tests from the repo root: `api/.venv/bin/python -m pytest api/tests/<file> -v`. Build the app with `cd app/CicadaApp && swift build`.
- Commit after every task; commit messages end with the `Co-Authored-By: Claude …` trailer used in this repo.

---

## File structure

| File | Responsibility |
|---|---|
| `api/services/auth.py` (new) | `cicada_home()`, token file, `require_token` dependency |
| `api/tests/conftest.py` (new) | autouse fixture: `CICADA_API_AUTH=off` for the existing suite |
| `api/services/connections/__init__.py` (new) | package marker |
| `api/services/connections/base.py` (new) | `CliResult`, `run_cli`, `ConnectionAdapter` protocol, `SCRUBBED_ENV_KEYS` |
| `api/services/connections/secrets.py` (new) | `secrets.env` read/write, `os.environ` sync |
| `api/services/connections/claude_cli.py` (new) | Claude plan adapter |
| `api/services/connections/codex_cli.py` (new) | ChatGPT plan adapter + device-code login sessions |
| `api/services/connections/byok.py` (new) | per-provider API-key adapters |
| `api/services/connections/ollama.py` (new) | local Ollama adapter |
| `api/services/connections/registry.py` (new) | adapter list, prefs file, 30 s status cache |
| `api/services/pricing.py` (new) | subscription price table + `price_for` |
| `api/models/schemas.py` (modify) | `ConnectionKind`, `LoginHint`, `ConnectionStatus`, `LoginSession`, `ConnectionsResponse`, `StatusConnections` |
| `api/routers/connections.py` (new) | `/connections` endpoints |
| `api/routers/status.py`, `api/main.py` (modify) | `connections` block on `/status`; auth dependency; secrets load; router mount |
| `mcp/server.py` (modify) | send bearer token when proxying to the backend |
| `scripts/doctor.sh`, `install.sh` (modify) | token-aware health check; no behaviour change otherwise |
| `app/…/Models/Connection.swift` (new) | Swift models |
| `app/…/Services/APIClient.swift` (modify) | bearer header; connection endpoints |
| `app/…/ViewModels/ConnectionsViewModel.swift` (new) | state + polling |
| `app/…/Views/Connections/ConnectionsView.swift` (new) | cards, Terminal hand-off, device-code sheet, key entry |
| `app/…/Views/Sidebar/SidebarView.swift`, `app/…/ContentView.swift` (modify) | new tab |

---

### Task 1: Bearer-token auth for the local API (G49 P0)

**Files:**
- Create: `api/services/auth.py`
- Create: `api/tests/conftest.py`
- Create: `api/tests/test_auth.py`
- Modify: `api/main.py` (the `FastAPI(...)` constructor line, currently `app = FastAPI(title="Cicada API", version="0.1.0", lifespan=lifespan)`)
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift:1108-1213` (generic helpers) and the two upload helpers (`uploadMultipart` ~line 982, conversations upload ~line 1075)
- Modify: `mcp/server.py` (the three backend calls at lines ~423, ~499, ~517)
- Modify: `scripts/doctor.sh` (the `/healthz` curl stays; add a `/status` check with the token)

**Interfaces:**
- Produces: `auth.cicada_home() -> Path`, `auth.get_token() -> str`, `auth.auth_enabled() -> bool`, `auth.require_token` (FastAPI dependency). `CICADA_HOME`, `CICADA_API_TOKEN`, `CICADA_API_AUTH` env vars.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_auth.py
"""Bearer-token auth on the local API (G49 P0 launch blocker)."""
from __future__ import annotations

import os
import stat

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import auth


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    config.get_settings.cache_clear()
    yield tmp_path / "home"
    config.get_settings.cache_clear()


def test_cicada_home_is_created_private(home):
    path = auth.cicada_home()
    assert path == home
    assert path.is_dir()
    assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_get_token_generates_once_and_persists(home):
    first = auth.get_token()
    second = auth.get_token()
    assert first == second and len(first) >= 32
    token_file = home / auth.TOKEN_FILE_NAME
    assert token_file.read_text().strip() == first
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_env_token_overrides_file(home, monkeypatch):
    monkeypatch.setenv("CICADA_API_TOKEN", "from-env")
    assert auth.get_token() == "from-env"


def test_healthz_is_open_but_status_requires_token(home):
    client = TestClient(main.app)
    assert client.get("/healthz").status_code == 200
    assert client.get("/status").status_code == 401
    ok = client.get("/status", headers={"Authorization": f"Bearer {auth.get_token()}"})
    assert ok.status_code == 200, ok.text


def test_wrong_token_rejected(home):
    client = TestClient(main.app)
    resp = client.get("/status", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_auth_off_switch_disables_check(home, monkeypatch):
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    client = TestClient(main.app)
    assert client.get("/status").status_code == 200
```

```python
# api/tests/conftest.py
"""Suite-wide fixtures.

The local API now requires a bearer token (api/services/auth.py). The existing
tests hit ``TestClient(main.app)`` without headers, so auth is switched off for
every test by default; ``test_auth.py`` re-enables it explicitly.
"""
import pytest


@pytest.fixture(autouse=True)
def _disable_api_auth(monkeypatch):
    monkeypatch.setenv("CICADA_API_AUTH", "off")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.services.auth'`

- [ ] **Step 3: Implement `auth.py`**

```python
# api/services/auth.py
"""Bearer-token auth for the localhost API.

Cicada's backend will start holding provider API keys (connections layer) and
writing files on the user's behalf, so an unauthenticated port 8000 is not
acceptable (claude-mem's port-37777 audit is the cautionary tale). The token
is generated once into ``$CICADA_HOME/api_token`` (0600); the companion app,
the MCP server and ``doctor.sh`` read the same file. ``CICADA_API_TOKEN``
overrides the file; ``CICADA_API_AUTH=off`` disables the check (tests/dev only
— logged loudly at startup).
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException, Request
from loguru import logger

TOKEN_FILE_NAME = "api_token"
_OPEN_PATHS = frozenset({"/healthz"})


def cicada_home() -> Path:
    """Machine-global Cicada state dir (``~/.cicada`` or ``$CICADA_HOME``), 0700."""
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    home = Path(raw).expanduser()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    return home


def auth_enabled() -> bool:
    return os.environ.get("CICADA_API_AUTH", "on").strip().lower() not in {"off", "0", "false"}


def get_token() -> str:
    env = (os.environ.get("CICADA_API_TOKEN") or "").strip()
    if env:
        return env
    path = cicada_home() / TOKEN_FILE_NAME
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    logger.info(f"Generated API token at {path}")
    return token


async def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """App-wide dependency: 401 unless the bearer token matches."""
    if not auth_enabled() or request.url.path in _OPEN_PATHS:
        return
    supplied = ""
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not secrets.compare_digest(supplied, get_token()):
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")
```

In `api/main.py` replace the constructor line with:

```python
from fastapi import Depends
from api.services.auth import auth_enabled, get_token, require_token

app = FastAPI(
    title="Cicada API",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(require_token)],
)
```

and add at the top of `lifespan` (after `settings = get_settings()`):

```python
    if auth_enabled():
        get_token()  # generate the token file on first boot so clients can read it
    else:
        logger.warning("CICADA_API_AUTH=off — the local API is UNAUTHENTICATED (dev/test only)")
```

- [ ] **Step 4: Run tests to verify they pass, then the whole suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_auth.py -v`
Expected: 6 PASS
Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: all green (the conftest switches auth off for legacy tests)

- [ ] **Step 5: Send the token from the app**

In `APIClient.swift`, add inside `actor APIClient` (below `private let decoder`):

```swift
    /// Bearer token generated by the backend at `$CICADA_HOME/api_token`
    /// (see api/services/auth.py). Read per request: on first launch the file
    /// appears a moment after the backend boots, so caching a miss would strand
    /// the app in 401s until restart.
    private static func loadToken() -> String? {
        let env = ProcessInfo.processInfo.environment
        if let t = env["CICADA_API_TOKEN"], !t.isEmpty { return t }
        let home = env["CICADA_HOME"].map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".cicada")
        let file = home.appendingPathComponent("api_token")
        guard let raw = try? String(contentsOf: file, encoding: .utf8) else { return nil }
        let token = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }

    private func makeRequest(_ path: String, method: String, json: Bool = true) -> URLRequest {
        var request = URLRequest(url: URL(string: "\(baseURL)\(path)")!)
        request.httpMethod = method
        if json { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let token = Self.loadToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }
```

Rewrite the `get` helper to use it (the other helpers change the same two lines — `let url = …` + `var request = URLRequest(url: url)` / `request.httpMethod = …` / `setValue("application/json"…)` collapse into one `makeRequest` call):

```swift
    private func get<T: Decodable>(_ path: String) async throws -> T {
        let request = makeRequest(path, method: "GET", json: false)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decodingError("\(error)")
        }
    }
```

Apply the same replacement in `post<T>`, `post -> Data`, `delete`, `put` (`makeRequest(path, method: "POST"/"DELETE"/"PUT")`), and in `uploadMultipart` / the conversations upload (`makeRequest(path, method: "POST", json: false)` then keep their own multipart `Content-Type` line).

Run: `cd app/CicadaApp && swift build`
Expected: `Build complete!`

- [ ] **Step 6: Send the token from the MCP server and doctor**

In `mcp/server.py` add near the other helpers (above the first backend call):

```python
def _backend_headers() -> dict[str, str]:
    """Bearer token for the local backend (api/services/auth.py)."""
    token = (os.environ.get("CICADA_API_TOKEN") or "").strip()
    if not token:
        home = Path(os.environ.get("CICADA_HOME") or Path.home() / ".cicada").expanduser()
        try:
            token = (home / "api_token").read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
```

and pass `headers=_backend_headers()` to the `urllib.request.Request(...)` calls at ~423 and ~499 (replacing their existing `headers={"Content-Type": "application/json"}`), and to the `httpx.AsyncClient()` call at ~529 as `client.post(..., headers=_backend_headers())`.

In `scripts/doctor.sh`, after the existing `/healthz` check add:

```bash
TOKEN_FILE="${CICADA_HOME:-$HOME/.cicada}/api_token"
if [[ -r "$TOKEN_FILE" ]]; then
  if curl -fsS -H "Authorization: Bearer $(cat "$TOKEN_FILE")" "http://127.0.0.1:${PORT}/status" >/dev/null; then
    ok "API auth: token accepted"
  else
    fail "API auth: /status rejected the token in $TOKEN_FILE"
  fi
else
  warn "API auth: no token file yet at $TOKEN_FILE (backend not started once?)"
fi
```

(`ok`/`fail`/`warn` are the helper functions doctor.sh already defines.)

- [ ] **Step 7: Commit**

```bash
git add api/services/auth.py api/tests/conftest.py api/tests/test_auth.py api/main.py \
  app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift mcp/server.py scripts/doctor.sh
git commit -m "feat(api): bearer-token auth on the local API (G49 P0)"
```

---

### Task 2: Secrets store for BYOK keys

**Files:**
- Create: `api/services/connections/__init__.py` (empty)
- Create: `api/services/connections/secrets.py`
- Create: `api/tests/test_connection_secrets.py`
- Modify: `api/main.py` (`lifespan`: load secrets right after the token line)

**Interfaces:**
- Consumes: `auth.cicada_home()`
- Produces: `secrets.secrets_path() -> Path`, `load_secrets(*, override: bool = False) -> dict[str, str]`, `set_secret(name: str, value: str) -> None`, `remove_secret(name: str) -> None`, `has_secret(name: str) -> bool`, `SECRETS_FILE_NAME = "secrets.env"`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_connection_secrets.py
from __future__ import annotations

import os
import stat

import pytest

from api.services.connections import secrets as sec


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_set_secret_writes_0600_and_exports(home):
    sec.set_secret("OPENAI_API_KEY", "sk-test")
    path = home / sec.SECRETS_FILE_NAME
    assert path.read_text() == "OPENAI_API_KEY=sk-test\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.environ["OPENAI_API_KEY"] == "sk-test"
    assert sec.has_secret("OPENAI_API_KEY")


def test_set_secret_replaces_existing_line(home):
    sec.set_secret("OPENAI_API_KEY", "one")
    sec.set_secret("ANTHROPIC_API_KEY", "two")
    sec.set_secret("OPENAI_API_KEY", "three")
    assert sec.load_secrets() == {"OPENAI_API_KEY": "three", "ANTHROPIC_API_KEY": "two"}
    assert os.environ["OPENAI_API_KEY"] == "three"


def test_remove_secret_drops_line_and_env(home):
    sec.set_secret("OPENAI_API_KEY", "one")
    sec.remove_secret("OPENAI_API_KEY")
    assert sec.load_secrets() == {}
    assert "OPENAI_API_KEY" not in os.environ
    assert not sec.has_secret("OPENAI_API_KEY")


def test_load_does_not_override_shell_export(home, monkeypatch):
    (home / sec.SECRETS_FILE_NAME).write_text("OPENAI_API_KEY=from-file\n")
    monkeypatch.setenv("OPENAI_API_KEY", "from-shell")
    sec.load_secrets()
    assert os.environ["OPENAI_API_KEY"] == "from-shell"
    sec.load_secrets(override=True)
    assert os.environ["OPENAI_API_KEY"] == "from-file"


def test_rejects_bad_names_and_newlines(home):
    with pytest.raises(ValueError):
        sec.set_secret("bad name", "x")
    with pytest.raises(ValueError):
        sec.set_secret("OPENAI_API_KEY", "x\ny")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_connection_secrets.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `secrets.py`**

```python
# api/services/connections/secrets.py
"""``$CICADA_HOME/secrets.env`` — the only place Cicada writes API keys.

Keys entered in the companion app land here (0600), never in ``api/.env``,
never in the memory repo. On backend boot and after every write the file is
projected into ``os.environ`` (shell exports win unless ``override=True``),
which is all litellm needs — no settings reload, no restart.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from api.services.auth import cicada_home

SECRETS_FILE_NAME = "secrets.env"
_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def secrets_path() -> Path:
    return cicada_home() / SECRETS_FILE_NAME


def _read() -> dict[str, str]:
    path = secrets_path()
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        out[name.strip()] = value.strip()
    return out


def _write(values: dict[str, str]) -> None:
    path = secrets_path()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".secrets-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for name, value in values.items():
            fh.write(f"{name}={value}\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_secrets(*, override: bool = False) -> dict[str, str]:
    values = _read()
    for name, value in values.items():
        if override or not os.environ.get(name):
            os.environ[name] = value
    return values


def set_secret(name: str, value: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid secret name: {name!r}")
    if "\n" in value or "\r" in value or not value.strip():
        raise ValueError("secret value must be a single non-empty line")
    values = _read()
    values[name] = value.strip()
    _write(values)
    os.environ[name] = value.strip()


def remove_secret(name: str) -> None:
    values = _read()
    values.pop(name, None)
    _write(values)
    os.environ.pop(name, None)


def has_secret(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())
```

In `api/main.py` `lifespan`, right after the token block:

```python
    from api.services.connections import secrets as connection_secrets

    loaded = connection_secrets.load_secrets()
    if loaded:
        logger.info(f"Loaded {len(loaded)} provider key(s) from {connection_secrets.secrets_path()}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_connection_secrets.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/connections api/tests/test_connection_secrets.py api/main.py
git commit -m "feat(connections): secrets.env store for BYOK keys, hot-loaded into the environment"
```

---

### Task 3: Subscription pricing table

**Files:**
- Create: `api/services/pricing.py`
- Create: `api/tests/test_pricing.py`

**Interfaces:**
- Produces: `pricing.SUBSCRIPTION_PRICES: dict[str, dict[str, float]]`, `pricing.PRICES_VERIFIED = "2026-08-28"`, `pricing.TIERED: dict[tuple[str, str], tuple[str, ...]]`, `pricing.price_for(connection_id: str, plan: str | None, tier: str | None = None) -> tuple[float | None, str]`, `pricing.plan_label(connection_id, plan, tier) -> str | None`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_pricing.py
from api.services import pricing


def test_flat_plan_price():
    usd, note = pricing.price_for("claude-plan", "pro")
    assert usd == 20.0
    assert "2026-08-28" in note


def test_tiered_plan_needs_tier():
    usd, note = pricing.price_for("claude-plan", "max")
    assert usd is None
    assert "5x" in note and "20x" in note


def test_tiered_plan_with_tier():
    assert pricing.price_for("claude-plan", "max", "20x")[0] == 200.0
    assert pricing.price_for("chatgpt-plan", "pro", "5x")[0] == 100.0


def test_unknown_plan():
    usd, note = pricing.price_for("chatgpt-plan", "enterprise")
    assert usd is None and "enterprise" in note


def test_none_plan():
    assert pricing.price_for("claude-plan", None) == (None, "not connected")


def test_labels():
    assert pricing.plan_label("claude-plan", "max", "20x") == "Claude Max 20x"
    assert pricing.plan_label("claude-plan", "max", None) == "Claude Max"
    assert pricing.plan_label("chatgpt-plan", "plus", None) == "ChatGPT Plus"
    assert pricing.plan_label("chatgpt-plan", None, None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_pricing.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `pricing.py`**

```python
# api/services/pricing.py
"""Subscription prices (USD/month) for the connections + usage surfaces.

Hand-verified against the vendors' pricing pages on ``PRICES_VERIFIED``; the
date is surfaced in the UI so a stale table is visible, not silent. Usage-based
(per-token) pricing lives in litellm and is added by the consumption plan.
"""
from __future__ import annotations

PRICES_VERIFIED = "2026-08-28"

SUBSCRIPTION_PRICES: dict[str, dict[str, float]] = {
    "claude-plan": {"pro": 20.0, "max-5x": 100.0, "max-20x": 200.0},
    "chatgpt-plan": {"go": 8.0, "plus": 20.0, "pro-5x": 100.0, "pro-20x": 200.0},
    "gemini-plan": {"pro": 19.99, "ultra-5x": 99.99, "ultra-20x": 199.99},
    "copilot-plan": {"pro": 10.0, "pro-plus": 39.0, "max": 100.0},
}

# (connection, plan) -> tiers the user must choose between.
TIERED: dict[tuple[str, str], tuple[str, ...]] = {
    ("claude-plan", "max"): ("5x", "20x"),
    ("chatgpt-plan", "pro"): ("5x", "20x"),
    ("gemini-plan", "ultra"): ("5x", "20x"),
}

_BRAND = {"claude-plan": "Claude", "chatgpt-plan": "ChatGPT", "gemini-plan": "Google AI", "copilot-plan": "Copilot"}


def price_for(connection_id: str, plan: str | None, tier: str | None = None) -> tuple[float | None, str]:
    if not plan:
        return None, "not connected"
    table = SUBSCRIPTION_PRICES.get(connection_id, {})
    plan = plan.lower()
    tiers = TIERED.get((connection_id, plan))
    if tiers:
        if tier in tiers:
            return table[f"{plan}-{tier}"], f"verified {PRICES_VERIFIED}"
        options = " or ".join(f"${table[f'{plan}-{t}']:.0f} ({t})" for t in tiers)
        return None, f"{plan.capitalize()} is {options} — pick your tier"
    if plan in table:
        return table[plan], f"verified {PRICES_VERIFIED}"
    return None, f"price unknown for '{plan}'"


def plan_label(connection_id: str, plan: str | None, tier: str | None) -> str | None:
    if not plan:
        return None
    brand = _BRAND.get(connection_id, connection_id)
    label = f"{brand} {plan.replace('-', ' ').title()}"
    if tier and TIERED.get((connection_id, plan.lower())):
        label += f" {tier}"
    return label
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_pricing.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/pricing.py api/tests/test_pricing.py
git commit -m "feat(pricing): subscription price table + price_for/plan_label"
```

---

### Task 4: Connection models, adapter protocol, scrubbed CLI runner

**Files:**
- Modify: `api/models/schemas.py` (append at the end)
- Create: `api/services/connections/base.py`
- Create: `api/tests/test_connections_base.py`

**Interfaces:**
- Produces (schemas): `ConnectionKind(str, Enum)`: `subscription|usage|local`; `LoginHint(CamelModel)`: `mode: str` (`terminal|device-code|key|none`), `command: str | None`; `ConnectionStatus(CamelModel)`: fields per spec §5.1; `LoginSession(CamelModel)`: `session_id: str`, `connection_id: str`, `mode: str`, `state: str` (`pending|done|failed`), `command: str | None`, `code: str | None`, `url: str | None`, `raw_output: str`, `detail: str | None`; `ConnectionsResponse(CamelModel)`: `connections: list[ConnectionStatus]`.
- Produces (base): `SCRUBBED_ENV_KEYS`, `CliResult(rc, stdout, stderr)`, `Runner = Callable[[list[str]], Awaitable[CliResult]]`, `scrubbed_env() -> dict[str, str]`, `run_cli(argv, *, timeout=15.0) -> CliResult`, `class ConnectionAdapter(Protocol)`.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_connections_base.py
"""Uses ``asyncio.run`` — pytest-asyncio is not a project dependency (same
convention as ``test_llm_seam_adoption.py``)."""
from __future__ import annotations

import asyncio
import os
import sys

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginHint
from api.services.connections import base


def test_scrubbed_env_drops_provider_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "b")
    monkeypatch.setenv("PATH", os.environ["PATH"])
    env = base.scrubbed_env()
    assert "ANTHROPIC_API_KEY" not in env and "OPENAI_API_KEY" not in env
    assert env["PATH"] == os.environ["PATH"]


def test_run_cli_captures_output():
    res = asyncio.run(base.run_cli([sys.executable, "-c", "import sys; print('hi'); sys.exit(3)"]))
    assert res.rc == 3 and res.stdout.strip() == "hi"


def test_run_cli_missing_binary_is_not_an_exception():
    res = asyncio.run(base.run_cli(["definitely-not-a-binary-xyz"]))
    assert res.rc == 127 and "not found" in res.stderr


def test_run_cli_timeout():
    res = asyncio.run(base.run_cli([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2))
    assert res.rc == 124 and "timed out" in res.stderr


def test_status_serialises_camel_case():
    s = ConnectionStatus(
        id="claude-plan", label="Claude plan", kind=ConnectionKind.subscription,
        available=True, connected=False, billing="subscription",
        login=LoginHint(mode="terminal", command="claude auth login"),
    )
    d = s.model_dump()
    assert d["priceUsdMonth"] is None and d["login"]["command"] == "claude auth login"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_connections_base.py -v`
Expected: FAIL with `ImportError: cannot import name 'ConnectionKind'`

- [ ] **Step 3: Add the schemas**

Append to `api/models/schemas.py`:

```python
# --- Provider connections (G50) ---


class ConnectionKind(str, Enum):
    subscription = "subscription"
    usage = "usage"
    local = "local"


class LoginHint(CamelModel):
    mode: str  # terminal | device-code | key | none
    command: Optional[str] = None


class ConnectionStatus(CamelModel):
    id: str
    label: str
    kind: ConnectionKind
    available: bool = False
    connected: bool = False
    plan: Optional[str] = None
    plan_label: Optional[str] = None
    tier: Optional[str] = None
    account: Optional[str] = None
    price_usd_month: Optional[float] = None
    price_note: Optional[str] = None
    billing: str = "usage"  # subscription | usage | free
    engine_role: Optional[str] = None
    detail: Optional[str] = None
    login: Optional[LoginHint] = None


class LoginSession(CamelModel):
    session_id: str
    connection_id: str
    mode: str
    state: str = "pending"  # pending | done | failed
    command: Optional[str] = None
    code: Optional[str] = None
    url: Optional[str] = None
    raw_output: str = ""
    detail: Optional[str] = None


class ConnectionsResponse(CamelModel):
    connections: list[ConnectionStatus]


class StatusConnections(CamelModel):
    connected: list[str] = []
    engine: Optional[str] = None
```

- [ ] **Step 4: Implement `base.py`**

```python
# api/services/connections/base.py
"""Shared pieces for provider connection adapters.

An adapter *probes* a vendor CLI's login state and can start/stop that CLI's
own login flow. It never holds a vendor token. All subprocesses run with the
provider API keys stripped from the environment so ``claude`` reports its
OAuth state rather than an API-key override, and so a child can never inherit
a key it should not see.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginSession

SCRUBBED_ENV_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY")


@dataclass
class CliResult:
    rc: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], Awaitable[CliResult]]


def scrubbed_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in SCRUBBED_ENV_KEYS}


async def run_cli(argv: list[str], *, timeout: float = 15.0) -> CliResult:
    """Run ``argv`` with a scrubbed env. Never raises: missing binary -> rc 127,
    timeout -> rc 124, so adapters can degrade to ``available=False``."""
    if shutil.which(argv[0]) is None and not os.path.exists(argv[0]):
        return CliResult(127, "", f"{argv[0]}: not found")
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=scrubbed_env(),
        )
    except OSError as exc:
        return CliResult(127, "", str(exc))
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return CliResult(124, "", f"{argv[0]} timed out after {timeout}s")
    return CliResult(proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


class ConnectionAdapter(Protocol):
    id: str
    label: str
    kind: ConnectionKind

    def available(self) -> bool: ...
    async def status(self) -> ConnectionStatus: ...
    async def begin_login(self) -> LoginSession: ...
    async def logout(self) -> None: ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_connections_base.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add api/models/schemas.py api/services/connections/base.py api/tests/test_connections_base.py
git commit -m "feat(connections): schemas, adapter protocol, scrubbed CLI runner"
```

---

### Task 5: Claude plan adapter

**Files:**
- Create: `api/services/connections/claude_cli.py`
- Create: `api/tests/test_connection_claude.py`

**Interfaces:**
- Consumes: `base.run_cli`, `base.CliResult`, `pricing.price_for`, `pricing.plan_label`
- Produces: `ClaudePlanAdapter(runner: Runner | None = None, tier: str | None = None)` with `id = "claude-plan"`, `status()`, `begin_login()`, `logout()`; `parse_auth_status(stdout: str) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_connection_claude.py
from __future__ import annotations

import asyncio
import json

from api.services.connections import claude_cli
from api.services.connections.base import CliResult


def _runner(rc=0, stdout="", stderr=""):
    calls: list[list[str]] = []

    async def run(argv):
        calls.append(argv)
        return CliResult(rc, stdout, stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


LOGGED_IN = json.dumps({
    "loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
    "email": "r@example.com", "orgName": "Personal", "subscriptionType": "max",
})


def test_status_connected_max_without_tier(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    run = _runner(stdout=LOGGED_IN)
    adapter = claude_cli.ClaudePlanAdapter(runner=run)
    s = asyncio.run(adapter.status())
    assert run.calls == [["claude", "auth", "status", "--json"]]
    assert s.available and s.connected
    assert s.plan == "max" and s.plan_label == "Claude Max"
    assert s.account == "r@example.com"
    assert s.price_usd_month is None and "pick your tier" in s.price_note
    assert s.billing == "subscription" and s.engine_role == "subscription-cli"


def test_status_connected_max_with_tier(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_runner(stdout=LOGGED_IN), tier="20x")
    s = asyncio.run(adapter.status())
    assert s.price_usd_month == 200.0 and s.plan_label == "Claude Max 20x" and s.tier == "20x"


def test_status_logged_out(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_runner(stdout='{"loggedIn": false}'))
    s = asyncio.run(adapter.status())
    assert s.available and not s.connected and s.plan is None
    assert s.login.mode == "terminal" and s.login.command == "claude auth login"


def test_status_not_installed(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: None)
    adapter = claude_cli.ClaudePlanAdapter(runner=_runner(rc=127))
    s = asyncio.run(adapter.status())
    assert not s.available and not s.connected and "install" in s.detail.lower()


def test_status_garbage_output_degrades(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    adapter = claude_cli.ClaudePlanAdapter(runner=_runner(stdout="not json"))
    s = asyncio.run(adapter.status())
    assert s.available and not s.connected and "could not parse" in s.detail


def test_api_key_auth_is_not_a_plan_connection(monkeypatch):
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _: "/usr/local/bin/claude")
    out = json.dumps({"loggedIn": True, "authMethod": "apiKey", "apiProvider": "firstParty"})
    s = asyncio.run(claude_cli.ClaudePlanAdapter(runner=_runner(stdout=out)).status())
    assert not s.connected and "API key" in s.detail


def test_logout_runs_cli():
    run = _runner()
    asyncio.run(claude_cli.ClaudePlanAdapter(runner=run).logout())
    assert run.calls == [["claude", "auth", "logout"]]


def test_begin_login_is_terminal_handoff():
    sess = asyncio.run(claude_cli.ClaudePlanAdapter(runner=_runner()).begin_login())
    assert sess.mode == "terminal" and sess.command == "claude auth login" and sess.state == "pending"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_connection_claude.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `claude_cli.py`**

```python
# api/services/connections/claude_cli.py
"""Claude plan connection — delegates 100% to the unmodified ``claude`` binary.

Anthropic's compliance page forbids third parties from intermediating
claude.ai credentials, so this adapter only *asks Claude Code* about its own
login state (``claude auth status --json``) and starts/stops Claude Code's
own flows (``claude auth login`` in a Terminal the app opens; ``claude auth
logout``). The Max tier (5x/20x) is not exposed by the status command and is
a user preference (registry prefs), never read from the Keychain.
"""
from __future__ import annotations

import json
import shutil
import uuid

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginHint, LoginSession
from api.services import pricing
from api.services.connections.base import Runner, run_cli

LOGIN_COMMAND = "claude auth login"
_INSTALL_HINT = "Install Claude Code (npm i -g @anthropic-ai/claude-code) and run `claude` once to sign in."


def parse_auth_status(stdout: str) -> dict:
    return json.loads(stdout.strip() or "{}")


class ClaudePlanAdapter:
    id = "claude-plan"
    label = "Claude plan"
    kind = ConnectionKind.subscription

    def __init__(self, runner: Runner | None = None, tier: str | None = None):
        self._run = runner or run_cli
        self._tier = tier

    def available(self) -> bool:
        return shutil.which("claude") is not None

    def _base(self, **kw) -> ConnectionStatus:
        return ConnectionStatus(
            id=self.id, label=self.label, kind=self.kind, billing="subscription",
            engine_role="subscription-cli", tier=self._tier,
            login=LoginHint(mode="terminal", command=LOGIN_COMMAND), **kw,
        )

    async def status(self) -> ConnectionStatus:
        if not self.available():
            return self._base(available=False, detail=_INSTALL_HINT)
        res = await self._run(["claude", "auth", "status", "--json"])
        if res.rc == 127:
            return self._base(available=False, detail=_INSTALL_HINT)
        try:
            info = parse_auth_status(res.stdout)
        except ValueError:
            return self._base(available=True, detail=f"could not parse `claude auth status` output: {res.stderr.strip() or res.stdout[:80]!r}")
        if not info.get("loggedIn"):
            return self._base(available=True, detail="Not signed in — Connect opens Terminal with `claude auth login`.")
        if info.get("authMethod") not in (None, "claude.ai"):
            return self._base(available=True, detail="Claude Code is using an API key, not a plan. Use the OpenAI/Anthropic API-key connection for usage-based billing.")
        plan = (info.get("subscriptionType") or "").lower() or None
        usd, note = pricing.price_for(self.id, plan, self._tier)
        return self._base(
            available=True, connected=True, plan=plan,
            plan_label=pricing.plan_label(self.id, plan, self._tier),
            account=info.get("email"), price_usd_month=usd, price_note=note,
            detail=info.get("orgName"),
        )

    async def begin_login(self) -> LoginSession:
        return LoginSession(session_id=uuid.uuid4().hex, connection_id=self.id, mode="terminal", command=LOGIN_COMMAND)

    async def logout(self) -> None:
        await self._run(["claude", "auth", "logout"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_connection_claude.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/connections/claude_cli.py api/tests/test_connection_claude.py
git commit -m "feat(connections): Claude plan adapter via claude auth status/login/logout"
```

---

### Task 6: ChatGPT plan adapter (Codex CLI) with device-code login

**Files:**
- Create: `api/services/connections/codex_cli.py`
- Create: `api/tests/test_connection_codex.py`

**Interfaces:**
- Consumes: `base.run_cli`, `pricing`
- Produces: `CodexPlanAdapter(runner=None, tier=None, codex_home: Path | None = None, spawn=None)` with `id = "chatgpt-plan"`; `decode_jwt_claims(token: str) -> dict`; `read_plan_from_auth_json(path: Path) -> tuple[str | None, str | None]` (plan, email); `parse_device_output(text: str) -> tuple[str | None, str | None]` (code, url); module-level `login_sessions: dict[str, LoginSession]`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_connection_codex.py
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from api.services.connections import codex_cli
from api.services.connections.base import CliResult


def _jwt(claims: dict) -> str:
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'none'})}.{b64(claims)}.sig"


def _auth_json(tmp_path: Path, plan="plus", email="r@example.com") -> Path:
    claims = {"email": email, "https://api.openai.com/auth": {"chatgpt_plan_type": plan}}
    (tmp_path / "auth.json").write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"id_token": _jwt(claims), "access_token": "x", "refresh_token": "y"},
    }))
    return tmp_path


def _runner(rc=0, stdout="", stderr=""):
    calls: list[list[str]] = []

    async def run(argv):
        calls.append(argv)
        return CliResult(rc, stdout, stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_decode_jwt_claims_handles_missing_padding():
    claims = codex_cli.decode_jwt_claims(_jwt({"a": 1, "email": "e"}))
    assert claims == {"a": 1, "email": "e"}


def test_read_plan_from_auth_json(tmp_path):
    home = _auth_json(tmp_path, plan="pro")
    assert codex_cli.read_plan_from_auth_json(home / "auth.json") == ("pro", "r@example.com")


def test_read_plan_missing_file(tmp_path):
    assert codex_cli.read_plan_from_auth_json(tmp_path / "nope.json") == (None, None)


def test_status_connected(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    home = _auth_json(tmp_path, plan="plus")
    run = _runner(stdout="Logged in using ChatGPT")
    s = asyncio.run(codex_cli.CodexPlanAdapter(runner=run, codex_home=home).status())
    assert run.calls == [["codex", "login", "status"]]
    assert s.connected and s.plan == "plus" and s.plan_label == "ChatGPT Plus"
    assert s.price_usd_month == 20.0 and s.account == "r@example.com"
    assert s.login.mode == "device-code"


def test_status_logged_out(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    s = asyncio.run(codex_cli.CodexPlanAdapter(runner=_runner(rc=1, stderr="Not logged in"), codex_home=tmp_path).status())
    assert s.available and not s.connected and s.plan is None


def test_status_api_key_mode_is_not_a_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    (tmp_path / "auth.json").write_text(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk"}))
    s = asyncio.run(codex_cli.CodexPlanAdapter(runner=_runner(stdout="Logged in using API key"), codex_home=tmp_path).status())
    assert not s.connected and "API key" in s.detail


def test_parse_device_output():
    text = "Enter this code at https://auth.openai.com/device\n\n    ABCD-EFGH\n"
    assert codex_cli.parse_device_output(text) == ("ABCD-EFGH", "https://auth.openai.com/device")
    assert codex_cli.parse_device_output("nothing here") == (None, None)


def test_begin_login_spawns_device_auth_and_tracks_session(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_cli.shutil, "which", lambda _: "/usr/local/bin/codex")
    spawned: list[list[str]] = []

    class _Proc:
        returncode = None

        def __init__(self):
            self.lines = [b"Visit https://auth.openai.com/device and enter WXYZ-1234\n"]
            self.stdout = self

        async def readline(self):
            return self.lines.pop(0) if self.lines else b""

        async def wait(self):
            self.returncode = 0
            return 0

    async def spawn(argv):
        spawned.append(argv)
        return _Proc()

    adapter = codex_cli.CodexPlanAdapter(runner=_runner(), codex_home=tmp_path, spawn=spawn)

    async def go():
        sess = await adapter.begin_login()
        await asyncio.sleep(0.05)  # let the watcher drain the fake process
        return sess

    sess = asyncio.run(go())
    assert spawned == [["codex", "login", "--device-auth"]]
    assert sess.mode == "device-code"
    tracked = codex_cli.login_sessions[sess.session_id]
    assert tracked.code == "WXYZ-1234" and tracked.url == "https://auth.openai.com/device"
    assert tracked.state == "done"


def test_logout_runs_cli(tmp_path):
    run = _runner()
    asyncio.run(codex_cli.CodexPlanAdapter(runner=run, codex_home=tmp_path).logout())
    assert run.calls == [["codex", "logout"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_connection_codex.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `codex_cli.py`**

```python
# api/services/connections/codex_cli.py
"""ChatGPT plan connection — delegates to the ``codex`` CLI.

Login state comes from ``codex login status`` (exit 0 = logged in). The plan
and email are decoded **display-only** from the ``id_token`` JWT in
``$CODEX_HOME/auth.json`` (payload base64 only, no signature check, no token
ever leaves this process or is written anywhere). Login uses
``codex login --device-auth`` which prints a one-time code + URL — the app
shows them; a watcher task flips the session to ``done`` when the process
exits 0. Logout is ``codex logout``.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginHint, LoginSession
from api.services import pricing
from api.services.connections.base import Runner, run_cli, scrubbed_env

_AUTH_CLAIM = "https://api.openai.com/auth"
_URL_RE = re.compile(r"https?://\S+")
_CODE_RE = re.compile(r"\b[A-Z0-9]{4,}-[A-Z0-9]{4,}\b")
_INSTALL_HINT = "Install Codex CLI (npm i -g @openai/codex) and run `codex login` once."

login_sessions: dict[str, LoginSession] = {}


def codex_home_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def decode_jwt_claims(token: str) -> dict:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode()).decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return {}


def read_plan_from_auth_json(path: Path) -> tuple[str | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if data.get("auth_mode") not in (None, "chatgpt"):
        return None, None
    claims = decode_jwt_claims(((data.get("tokens") or {}).get("id_token")) or "")
    plan = ((claims.get(_AUTH_CLAIM) or {}).get("chatgpt_plan_type") or "").lower() or None
    return plan, claims.get("email")


def parse_device_output(text: str) -> tuple[str | None, str | None]:
    url = _URL_RE.search(text)
    code = _CODE_RE.search(text)
    return (code.group(0) if code else None), (url.group(0).rstrip(".,") if url else None)


class CodexPlanAdapter:
    id = "chatgpt-plan"
    label = "ChatGPT plan"
    kind = ConnectionKind.subscription

    def __init__(self, runner: Runner | None = None, tier: str | None = None,
                 codex_home: Path | None = None, spawn: Callable[[list[str]], Awaitable] | None = None):
        self._run = runner or run_cli
        self._tier = tier
        self._home = codex_home or codex_home_dir()
        self._spawn = spawn or self._default_spawn

    @staticmethod
    async def _default_spawn(argv: list[str]):
        return await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, env=scrubbed_env(),
        )

    def available(self) -> bool:
        return shutil.which("codex") is not None

    def _base(self, **kw) -> ConnectionStatus:
        return ConnectionStatus(
            id=self.id, label=self.label, kind=self.kind, billing="subscription",
            engine_role="subscription-cli", tier=self._tier,
            login=LoginHint(mode="device-code", command="codex login --device-auth"), **kw,
        )

    async def status(self) -> ConnectionStatus:
        if not self.available():
            return self._base(available=False, detail=_INSTALL_HINT)
        res = await self._run(["codex", "login", "status"])
        if res.rc == 127:
            return self._base(available=False, detail=_INSTALL_HINT)
        if res.rc != 0:
            return self._base(available=True, detail="Not signed in — Connect shows a one-time code for your ChatGPT account.")
        plan, email = read_plan_from_auth_json(self._home / "auth.json")
        if plan is None and "api key" in (res.stdout + res.stderr).lower():
            return self._base(available=True, detail="Codex is using an API key, not a ChatGPT plan. Use the OpenAI API-key connection for usage-based billing.")
        usd, note = pricing.price_for(self.id, plan, self._tier)
        return self._base(
            available=True, connected=True, plan=plan,
            plan_label=pricing.plan_label(self.id, plan, self._tier),
            account=email, price_usd_month=usd, price_note=note,
        )

    async def begin_login(self) -> LoginSession:
        sess = LoginSession(session_id=uuid.uuid4().hex, connection_id=self.id, mode="device-code",
                            command="codex login --device-auth")
        login_sessions[sess.session_id] = sess
        proc = await self._spawn(["codex", "login", "--device-auth"])
        asyncio.get_running_loop().create_task(self._watch(sess, proc))
        return sess

    async def _watch(self, sess: LoginSession, proc) -> None:
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace")
                sess.raw_output += text
                code, url = parse_device_output(sess.raw_output)
                sess.code, sess.url = sess.code or code, sess.url or url
            rc = await proc.wait()
            sess.state = "done" if rc == 0 else "failed"
            if rc != 0:
                sess.detail = f"codex login exited {rc}"
        except Exception as exc:  # never let a watcher crash the loop
            logger.warning(f"codex login watcher failed: {exc}")
            sess.state, sess.detail = "failed", str(exc)

    async def logout(self) -> None:
        await self._run(["codex", "logout"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_connection_codex.py -v`
Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/connections/codex_cli.py api/tests/test_connection_codex.py
git commit -m "feat(connections): ChatGPT plan adapter via codex login status/device-auth/logout"
```

---

### Task 7: BYOK and Ollama adapters

**Files:**
- Create: `api/services/connections/byok.py`
- Create: `api/services/connections/ollama.py`
- Create: `api/tests/test_connection_byok_ollama.py`

**Interfaces:**
- Consumes: `secrets.has_secret/set_secret/remove_secret`, `Settings.ollama_model/ollama_base_url`
- Produces: `BYOK_PROVIDERS: dict[str, tuple[str, str]]` (`provider -> (env var, label)`), `ByokAdapter(provider: str)` with `id = f"byok-{provider}"`, `set_key(value: str) -> None`, `remove_key() -> None`; `OllamaAdapter(settings, fetch_tags: Callable[[str], Awaitable[list[str]]] | None = None)` with `id = "ollama-local"`

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_connection_byok_ollama.py
from __future__ import annotations

import asyncio
import os

import pytest

from api.config import Settings
from api.services.connections import byok, ollama


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_byok_ids_and_labels():
    ids = {byok.ByokAdapter(p).id for p in byok.BYOK_PROVIDERS}
    assert ids == {"byok-openai", "byok-anthropic", "byok-openrouter", "byok-gemini"}
    assert byok.ByokAdapter("openai").label == "OpenAI API key"


def test_byok_disconnected_then_connected(home):
    a = byok.ByokAdapter("openai")
    s = asyncio.run(a.status())
    assert s.available and not s.connected and s.billing == "usage" and s.login.mode == "key"
    a.set_key("sk-live")
    s = asyncio.run(a.status())
    assert s.connected and s.engine_role == "byok" and s.price_usd_month is None
    assert os.environ["OPENAI_API_KEY"] == "sk-live"
    a.remove_key()
    assert not asyncio.run(a.status()).connected


def test_byok_logout_removes_key(home):
    a = byok.ByokAdapter("anthropic")
    a.set_key("sk-ant")
    asyncio.run(a.logout())
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_byok_unknown_provider():
    with pytest.raises(ValueError):
        byok.ByokAdapter("mystery")


def test_ollama_connected_when_model_present():
    async def tags(_url):
        return ["qwen3:8b", "llama3.1:latest"]

    a = ollama.OllamaAdapter(Settings(ollama_model="qwen3:8b"), fetch_tags=tags)
    s = asyncio.run(a.status())
    assert s.available and s.connected and s.billing == "free" and s.plan_label == "qwen3:8b"


def test_ollama_model_missing():
    async def tags(_url):
        return ["llama3.1:latest"]

    s = asyncio.run(ollama.OllamaAdapter(Settings(ollama_model="qwen3:8b"), fetch_tags=tags).status())
    assert s.available and not s.connected and "ollama pull qwen3:8b" in s.detail


def test_ollama_unreachable():
    async def tags(_url):
        raise ConnectionError("refused")

    s = asyncio.run(ollama.OllamaAdapter(Settings(), fetch_tags=tags).status())
    assert not s.available and not s.connected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_connection_byok_ollama.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `byok.py` and `ollama.py`**

```python
# api/services/connections/byok.py
"""Usage-based (bring-your-own-key) connections — one adapter per provider."""
from __future__ import annotations

import uuid

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginHint, LoginSession
from api.services.connections import secrets

BYOK_PROVIDERS: dict[str, tuple[str, str]] = {
    "openai": ("OPENAI_API_KEY", "OpenAI API key"),
    "anthropic": ("ANTHROPIC_API_KEY", "Anthropic API key"),
    "openrouter": ("OPENROUTER_API_KEY", "OpenRouter API key"),
    "gemini": ("GEMINI_API_KEY", "Gemini API key"),
}


class ByokAdapter:
    kind = ConnectionKind.usage

    def __init__(self, provider: str):
        if provider not in BYOK_PROVIDERS:
            raise ValueError(f"unknown BYOK provider: {provider}")
        self.provider = provider
        self.env_var, self.label = BYOK_PROVIDERS[provider]
        self.id = f"byok-{provider}"

    def available(self) -> bool:
        return True

    async def status(self) -> ConnectionStatus:
        connected = secrets.has_secret(self.env_var)
        return ConnectionStatus(
            id=self.id, label=self.label, kind=self.kind, available=True, connected=connected,
            billing="usage", engine_role="byok" if connected else None,
            plan_label="usage-based" if connected else None,
            detail=None if connected else f"Paste a key; it is stored in {secrets.secrets_path()} (0600) and exported as {self.env_var}.",
            login=LoginHint(mode="key"),
        )

    def set_key(self, value: str) -> None:
        secrets.set_secret(self.env_var, value)

    def remove_key(self) -> None:
        secrets.remove_secret(self.env_var)

    async def begin_login(self) -> LoginSession:
        return LoginSession(session_id=uuid.uuid4().hex, connection_id=self.id, mode="key",
                            detail=f"PUT /connections/{self.id}/key with {{\"key\": ...}}")

    async def logout(self) -> None:
        self.remove_key()
```

```python
# api/services/connections/ollama.py
"""Local Ollama connection — free, on-device; 'connected' = model pulled."""
from __future__ import annotations

import uuid
from typing import Awaitable, Callable

from api.config import Settings
from api.models.schemas import ConnectionKind, ConnectionStatus, LoginHint, LoginSession


async def _http_tags(base_url: str) -> list[str]:
    import httpx

    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
        resp.raise_for_status()
        return [m.get("name", "") for m in resp.json().get("models", [])]


class OllamaAdapter:
    id = "ollama-local"
    label = "Ollama (local)"
    kind = ConnectionKind.local

    def __init__(self, settings: Settings, fetch_tags: Callable[[str], Awaitable[list[str]]] | None = None):
        self._settings = settings
        self._tags = fetch_tags or _http_tags

    def available(self) -> bool:
        return True  # decided live in status()

    async def status(self) -> ConnectionStatus:
        model = self._settings.ollama_model
        base = ConnectionStatus(id=self.id, label=self.label, kind=self.kind, billing="free",
                                login=LoginHint(mode="none"))
        try:
            names = await self._tags(self._settings.ollama_base_url)
        except Exception as exc:
            base.available, base.detail = False, f"Ollama not reachable at {self._settings.ollama_base_url} ({exc}). Install from ollama.com and start it."
            return base
        base.available = True
        if model in names or any(n.split(":")[0] == model for n in names):
            base.connected, base.engine_role, base.plan_label = True, "local", model
        else:
            base.detail = f"Model not pulled — run `ollama pull {model}`"
        return base

    async def begin_login(self) -> LoginSession:
        return LoginSession(session_id=uuid.uuid4().hex, connection_id=self.id, mode="none",
                            command=f"ollama pull {self._settings.ollama_model}")

    async def logout(self) -> None:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `api/.venv/bin/python -m pytest api/tests/test_connection_byok_ollama.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/connections/byok.py api/services/connections/ollama.py api/tests/test_connection_byok_ollama.py
git commit -m "feat(connections): BYOK per-provider adapters + local Ollama adapter"
```

---

### Task 8: Registry, prefs, `/connections` router, `/status` block

**Files:**
- Create: `api/services/connections/registry.py`
- Create: `api/routers/connections.py`
- Create: `api/tests/test_connections_api.py`
- Modify: `api/main.py` (import + `app.include_router(connections.router, tags=["connections"])`)
- Modify: `api/routers/status.py` (`get_status`) and `api/models/schemas.py` (`StatusResponse.connections: Optional[StatusConnections] = None`)

**Interfaces:**
- Produces: `registry.Registry(settings)` with `adapters() -> list[ConnectionAdapter]`, `get(id) -> ConnectionAdapter`, `async statuses(fresh=False) -> list[ConnectionStatus]`, `async status(id, fresh=False) -> ConnectionStatus`, `invalidate()`, `prefs() -> dict`, `set_pref(id, key, value)`; `registry.get_registry(settings) -> Registry` (module singleton keyed by `CICADA_HOME`); `PREFS_FILE_NAME = "connections.json"`, `STATUS_TTL_SECONDS = 30`.
- Endpoints per spec §5.4.

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_connections_api.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services.connections import base, registry
from api.services.connections.base import CliResult


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    config.get_settings.cache_clear()
    registry.reset_registry()

    async def fake_run(argv):
        if argv[:3] == ["claude", "auth", "status"]:
            return CliResult(0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                            "email": "r@example.com", "subscriptionType": "max"}), "")
        if argv[:3] == ["codex", "login", "status"]:
            return CliResult(1, "", "Not logged in")
        return CliResult(0, "", "")

    monkeypatch.setattr(base, "run_cli", fake_run)
    monkeypatch.setattr(registry.shutil, "which", lambda name: f"/usr/local/bin/{name}")

    async def no_tags(_url):
        raise ConnectionError("no ollama in tests")

    monkeypatch.setattr(registry, "_ollama_fetch_tags", no_tags)
    yield TestClient(main.app)
    registry.reset_registry()
    config.get_settings.cache_clear()


def test_list_connections(client):
    body = client.get("/connections").json()
    ids = [c["id"] for c in body["connections"]]
    assert ids[:2] == ["claude-plan", "chatgpt-plan"]
    assert {"byok-openai", "byok-anthropic", "byok-openrouter", "byok-gemini", "ollama-local"} <= set(ids)
    claude = next(c for c in body["connections"] if c["id"] == "claude-plan")
    assert claude["connected"] and claude["plan"] == "max" and claude["priceUsdMonth"] is None


def test_set_tier_pref_prices_the_plan(client, tmp_path):
    resp = client.put("/connections/claude-plan/prefs", json={"tier": "20x"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["priceUsdMonth"] == 200.0 and resp.json()["planLabel"] == "Claude Max 20x"
    prefs = json.loads((tmp_path / "home" / registry.PREFS_FILE_NAME).read_text())
    assert prefs["claude-plan"]["tier"] == "20x"


def test_reject_bad_tier(client):
    assert client.put("/connections/claude-plan/prefs", json={"tier": "99x"}).status_code == 422


def test_byok_key_roundtrip(client, tmp_path):
    resp = client.put("/connections/byok-openai/key", json={"key": "sk-abc"})
    assert resp.status_code == 200 and resp.json()["connected"] is True
    assert "OPENAI_API_KEY=sk-abc" in (tmp_path / "home" / "secrets.env").read_text()
    resp = client.delete("/connections/byok-openai/key")
    assert resp.status_code == 200 and resp.json()["connected"] is False


def test_key_endpoint_rejects_non_byok(client):
    assert client.put("/connections/claude-plan/key", json={"key": "x"}).status_code == 400


def test_login_claude_is_terminal_handoff(client):
    resp = client.post("/connections/claude-plan/login")
    assert resp.status_code == 200
    assert resp.json()["mode"] == "terminal" and resp.json()["command"] == "claude auth login"


def test_logout_claude(client):
    assert client.post("/connections/claude-plan/logout").status_code == 200


def test_unknown_connection_404(client):
    assert client.get("/connections/nope").status_code == 404


def test_status_has_connections_block(client):
    body = client.get("/status").json()
    assert body["connections"]["connected"] == ["claude-plan"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `api/.venv/bin/python -m pytest api/tests/test_connections_api.py -v`
Expected: FAIL with `ModuleNotFoundError: … registry`

- [ ] **Step 3: Implement `registry.py`**

```python
# api/services/connections/registry.py
"""Adapter list + machine-global preferences + a short status cache.

Prefs (``$CICADA_HOME/connections.json``, 0600) hold *user choices only*
(tier override, enabled flag). Live status is re-probed with a 30 s TTL —
never persisted — so no plan/email snapshot ever touches disk.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from api.config import Settings
from api.models.schemas import ConnectionStatus
from api.services.auth import cicada_home
from api.services.connections import base, byok, claude_cli, codex_cli, ollama

PREFS_FILE_NAME = "connections.json"
STATUS_TTL_SECONDS = 30
VALID_TIERS = ("5x", "20x")

_ollama_fetch_tags = ollama._http_tags  # patched in tests


class Registry:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache: dict[str, tuple[float, ConnectionStatus]] = {}

    # --- prefs -------------------------------------------------------------
    def _prefs_path(self) -> Path:
        return cicada_home() / PREFS_FILE_NAME

    def prefs(self) -> dict:
        try:
            return json.loads(self._prefs_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def set_pref(self, connection_id: str, key: str, value) -> None:
        prefs = self.prefs()
        entry = prefs.setdefault(connection_id, {})
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
        path = self._prefs_path()
        path.write_text(json.dumps(prefs, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)
        self.invalidate()

    # --- adapters ----------------------------------------------------------
    def adapters(self) -> list:
        prefs = self.prefs()
        runner = base.run_cli
        return [
            claude_cli.ClaudePlanAdapter(runner=runner, tier=prefs.get("claude-plan", {}).get("tier")),
            codex_cli.CodexPlanAdapter(runner=runner, tier=prefs.get("chatgpt-plan", {}).get("tier")),
            *[byok.ByokAdapter(p) for p in byok.BYOK_PROVIDERS],
            ollama.OllamaAdapter(self._settings, fetch_tags=_ollama_fetch_tags),
        ]

    def get(self, connection_id: str):
        for adapter in self.adapters():
            if adapter.id == connection_id:
                return adapter
        raise KeyError(connection_id)

    # --- status (cached) ---------------------------------------------------
    def invalidate(self) -> None:
        self._cache.clear()

    async def status(self, connection_id: str, fresh: bool = False) -> ConnectionStatus:
        now = time.monotonic()
        hit = self._cache.get(connection_id)
        if hit and not fresh and now - hit[0] < STATUS_TTL_SECONDS:
            return hit[1]
        status = await self.get(connection_id).status()
        self._cache[connection_id] = (now, status)
        return status

    async def statuses(self, fresh: bool = False) -> list[ConnectionStatus]:
        return [await self.status(a.id, fresh=fresh) for a in self.adapters()]


_registry: Registry | None = None
_registry_home: str | None = None


def get_registry(settings: Settings) -> Registry:
    global _registry, _registry_home
    home = str(cicada_home())
    if _registry is None or _registry_home != home:
        _registry, _registry_home = Registry(settings), home
    return _registry


def reset_registry() -> None:
    global _registry, _registry_home
    _registry, _registry_home = None, None
```

Note `registry.shutil` is imported so tests can patch `which` in one place; the adapters call `shutil.which` through their own module import, so ALSO patch there if a test needs it — the API test patches `base.run_cli` and `registry.shutil`, and the adapters import `run_cli` by name at construction via `base.run_cli`, which is why `adapters()` reads `base.run_cli` at call time (not at import).

- [ ] **Step 4: Implement the router and `/status` block**

```python
# api/routers/connections.py
"""Provider connections (G50): probe, connect, disconnect, keys, prefs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.config import Settings, get_settings
from api.models.schemas import ConnectionsResponse, ConnectionStatus, LoginSession
from api.services.connections import byok, codex_cli
from api.services.connections.registry import VALID_TIERS, Registry, get_registry

router = APIRouter(prefix="/connections")


class KeyBody(BaseModel):
    key: str


class PrefsBody(BaseModel):
    tier: str | None = None
    enabled: bool | None = None


def _registry(settings: Settings = Depends(get_settings)) -> Registry:
    return get_registry(settings)


def _adapter(reg: Registry, connection_id: str):
    try:
        return reg.get(connection_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown connection '{connection_id}'")


@router.get("", response_model=ConnectionsResponse)
async def list_connections(fresh: bool = False, reg: Registry = Depends(_registry)):
    return ConnectionsResponse(connections=await reg.statuses(fresh=fresh))


@router.get("/{connection_id}", response_model=ConnectionStatus)
async def get_connection(connection_id: str, fresh: bool = False, reg: Registry = Depends(_registry)):
    _adapter(reg, connection_id)
    return await reg.status(connection_id, fresh=fresh)


@router.post("/{connection_id}/login", response_model=LoginSession)
async def login(connection_id: str, reg: Registry = Depends(_registry)):
    adapter = _adapter(reg, connection_id)
    reg.invalidate()
    return await adapter.begin_login()


@router.get("/{connection_id}/login/{session_id}", response_model=LoginSession)
async def login_state(connection_id: str, session_id: str, reg: Registry = Depends(_registry)):
    _adapter(reg, connection_id)
    sess = codex_cli.login_sessions.get(session_id)
    if sess is None or sess.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="unknown login session")
    if sess.state == "done":
        reg.invalidate()
    return sess


@router.post("/{connection_id}/logout", response_model=ConnectionStatus)
async def logout(connection_id: str, reg: Registry = Depends(_registry)):
    adapter = _adapter(reg, connection_id)
    await adapter.logout()
    reg.invalidate()
    return await reg.status(connection_id, fresh=True)


@router.put("/{connection_id}/key", response_model=ConnectionStatus)
async def set_key(connection_id: str, body: KeyBody, reg: Registry = Depends(_registry)):
    adapter = _adapter(reg, connection_id)
    if not isinstance(adapter, byok.ByokAdapter):
        raise HTTPException(status_code=400, detail="only API-key connections accept a key")
    try:
        adapter.set_key(body.key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    reg.invalidate()
    return await reg.status(connection_id, fresh=True)


@router.delete("/{connection_id}/key", response_model=ConnectionStatus)
async def delete_key(connection_id: str, reg: Registry = Depends(_registry)):
    adapter = _adapter(reg, connection_id)
    if not isinstance(adapter, byok.ByokAdapter):
        raise HTTPException(status_code=400, detail="only API-key connections hold a key")
    adapter.remove_key()
    reg.invalidate()
    return await reg.status(connection_id, fresh=True)


@router.put("/{connection_id}/prefs", response_model=ConnectionStatus)
async def set_prefs(connection_id: str, body: PrefsBody, reg: Registry = Depends(_registry)):
    _adapter(reg, connection_id)
    if body.tier is not None and body.tier not in VALID_TIERS:
        raise HTTPException(status_code=422, detail=f"tier must be one of {VALID_TIERS}")
    if "tier" in body.model_fields_set:
        reg.set_pref(connection_id, "tier", body.tier)
    if body.enabled is not None:
        reg.set_pref(connection_id, "enabled", body.enabled)
    return await reg.status(connection_id, fresh=True)
```

`api/main.py`: add `connections` to the `from api.routers import (...)` list and `app.include_router(connections.router, tags=["connections"])` after `maintenance`.

`api/models/schemas.py`: add `connections: Optional[StatusConnections] = None` to `StatusResponse`.

`api/routers/status.py` — in `get_status`, before `return StatusResponse(`:

```python
    from api.services.connections.registry import get_registry

    conn_statuses = await get_registry(settings).statuses()
    connected_ids = [c.id for c in conn_statuses if c.connected]
    engine = next((c.engine_role for c in conn_statuses if c.connected), None)
```

and pass `connections=StatusConnections(connected=connected_ids, engine=engine)` (import `StatusConnections` from schemas).

- [ ] **Step 5: Run tests to verify they pass, then the full suite**

Run: `api/.venv/bin/python -m pytest api/tests/test_connections_api.py -v`
Expected: 9 PASS
Run: `api/.venv/bin/python -m pytest api/tests -q`
Expected: all green

- [ ] **Step 6: Commit**

```bash
git add api/services/connections/registry.py api/routers/connections.py api/tests/test_connections_api.py \
  api/main.py api/routers/status.py api/models/schemas.py
git commit -m "feat(api): /connections endpoints + registry/prefs + /status connections block"
```

---

### Task 9: Swift models, API client methods, view model

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/Connection.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` (new `// MARK: - Connections` section next to Contributors)
- Create: `app/CicadaApp/Sources/CicadaApp/ViewModels/ConnectionsViewModel.swift`

**Interfaces:**
- Produces: `struct ConnectionStatus: Identifiable, Codable`, `struct LoginHint: Codable`, `struct LoginSession: Codable`, `struct ConnectionsResponse: Codable`; `APIClient.fetchConnections(fresh:)`, `beginLogin(_:)`, `loginState(_:sessionId:)`, `logout(_:)`, `setKey(_:key:)`, `removeKey(_:)`, `setTier(_:tier:)`; `@Observable final class ConnectionsViewModel`.

- [ ] **Step 1: Models**

```swift
// app/CicadaApp/Sources/CicadaApp/Models/Connection.swift
import Foundation

/// Mirror of api/models/schemas.py::ConnectionStatus (G50). Tolerant decoding:
/// every field but `id`/`label` is optional so an older backend still decodes.
struct ConnectionStatus: Identifiable, Codable, Hashable {
    let id: String
    let label: String
    let kind: String            // subscription | usage | local
    let available: Bool
    let connected: Bool
    let plan: String?
    let planLabel: String?
    let tier: String?
    let account: String?
    let priceUsdMonth: Double?
    let priceNote: String?
    let billing: String         // subscription | usage | free
    let engineRole: String?
    let detail: String?
    let login: LoginHint?

    enum CodingKeys: String, CodingKey {
        case id, label, kind, available, connected, plan, planLabel, tier, account
        case priceUsdMonth, priceNote, billing, engineRole, detail, login
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "usage"
        available = try c.decodeIfPresent(Bool.self, forKey: .available) ?? false
        connected = try c.decodeIfPresent(Bool.self, forKey: .connected) ?? false
        plan = try c.decodeIfPresent(String.self, forKey: .plan)
        planLabel = try c.decodeIfPresent(String.self, forKey: .planLabel)
        tier = try c.decodeIfPresent(String.self, forKey: .tier)
        account = try c.decodeIfPresent(String.self, forKey: .account)
        priceUsdMonth = try c.decodeIfPresent(Double.self, forKey: .priceUsdMonth)
        priceNote = try c.decodeIfPresent(String.self, forKey: .priceNote)
        billing = try c.decodeIfPresent(String.self, forKey: .billing) ?? "usage"
        engineRole = try c.decodeIfPresent(String.self, forKey: .engineRole)
        detail = try c.decodeIfPresent(String.self, forKey: .detail)
        login = try c.decodeIfPresent(LoginHint.self, forKey: .login)
    }

    var isSubscription: Bool { billing == "subscription" }
    var isKeyBased: Bool { login?.mode == "key" }

    /// "Claude Max 20x · $200/mo", "OpenAI API key · usage-based", "Ollama · free, local".
    var priceLine: String {
        switch billing {
        case "subscription":
            if let usd = priceUsdMonth { return "\(planLabel ?? label) · $\(Int(usd))/mo" }
            return planLabel ?? label
        case "free": return "\(planLabel ?? label) · free, local"
        default: return connected ? "\(label) · usage-based" : label
        }
    }
}

struct LoginHint: Codable, Hashable {
    let mode: String   // terminal | device-code | key | none
    let command: String?
}

struct LoginSession: Codable, Hashable {
    let sessionId: String
    let connectionId: String
    let mode: String
    let state: String  // pending | done | failed
    let command: String?
    let code: String?
    let url: String?
    let rawOutput: String
    let detail: String?

    enum CodingKeys: String, CodingKey {
        case sessionId, connectionId, mode, state, command, code, url, rawOutput, detail
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sessionId = try c.decode(String.self, forKey: .sessionId)
        connectionId = try c.decode(String.self, forKey: .connectionId)
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "none"
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? "pending"
        command = try c.decodeIfPresent(String.self, forKey: .command)
        code = try c.decodeIfPresent(String.self, forKey: .code)
        url = try c.decodeIfPresent(String.self, forKey: .url)
        rawOutput = try c.decodeIfPresent(String.self, forKey: .rawOutput) ?? ""
        detail = try c.decodeIfPresent(String.self, forKey: .detail)
    }
}

struct ConnectionsResponse: Codable {
    let connections: [ConnectionStatus]
}
```

- [ ] **Step 2: API client methods** (add after the Contributors section in `APIClient.swift`)

```swift
    // MARK: - Connections (G50)

    func fetchConnections(fresh: Bool = false) async throws -> [ConnectionStatus] {
        let resp: ConnectionsResponse = try await get("/connections\(fresh ? "?fresh=true" : "")")
        return resp.connections
    }

    func beginLogin(_ id: String) async throws -> LoginSession {
        try await post("/connections/\(id)/login")
    }

    func loginState(_ id: String, sessionId: String) async throws -> LoginSession {
        try await get("/connections/\(id)/login/\(sessionId)")
    }

    func logout(_ id: String) async throws -> ConnectionStatus {
        try await post("/connections/\(id)/logout")
    }

    func setKey(_ id: String, key: String) async throws -> ConnectionStatus {
        try await put("/connections/\(id)/key", body: ["key": key])
    }

    func removeKey(_ id: String) async throws -> ConnectionStatus {
        let data = try await delete("/connections/\(id)/key")
        return try decoder.decode(ConnectionStatus.self, from: data)
    }

    func setTier(_ id: String, tier: String?) async throws -> ConnectionStatus {
        try await put("/connections/\(id)/prefs", body: ["tier": tier ?? NSNull()])
    }
```

- [ ] **Step 3: View model**

```swift
// app/CicadaApp/Sources/CicadaApp/ViewModels/ConnectionsViewModel.swift
import Foundation
import Observation

// G50: provider connections — probe/connect/disconnect through the vendor CLIs.
@Observable
@MainActor
final class ConnectionsViewModel {
    var connections: [ConnectionStatus] = []
    var isLoading = false
    var errorMessage: String?
    /// Active device-code login (ChatGPT/Codex) being polled.
    var pendingLogin: LoginSession?
    /// Connection id whose Terminal hand-off is in progress (Claude).
    var awaitingTerminal: String?

    private var pollTask: Task<Void, Never>?

    func load(fresh: Bool = false) async {
        isLoading = connections.isEmpty
        defer { isLoading = false }
        errorMessage = nil
        do {
            connections = try await APIClient.shared.fetchConnections(fresh: fresh)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Refresh every 30 s while the page is visible (matches the backend TTL).
    func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                await self?.load()
            }
        }
    }

    func stopPolling() { pollTask?.cancel(); pollTask = nil }

    func beginLogin(_ id: String) async -> LoginSession? {
        do {
            let session = try await APIClient.shared.beginLogin(id)
            switch session.mode {
            case "device-code":
                pendingLogin = session
                Task { await pollDeviceLogin(session) }
            case "terminal":
                awaitingTerminal = id
                Task { await pollUntilConnected(id) }
            default: break
            }
            return session
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    private func pollDeviceLogin(_ session: LoginSession) async {
        for _ in 0..<150 { // 5 minutes at 2 s
            try? await Task.sleep(for: .seconds(2))
            guard let latest = try? await APIClient.shared.loginState(session.connectionId, sessionId: session.sessionId) else { continue }
            pendingLogin = latest
            if latest.state != "pending" {
                await load(fresh: true)
                if latest.state == "done" { pendingLogin = nil }
                return
            }
        }
    }

    private func pollUntilConnected(_ id: String) async {
        for _ in 0..<100 { // ~5 minutes at 3 s
            try? await Task.sleep(for: .seconds(3))
            await load(fresh: true)
            if connections.first(where: { $0.id == id })?.connected == true {
                awaitingTerminal = nil
                return
            }
        }
        awaitingTerminal = nil
    }

    func logout(_ id: String) async {
        do { _ = try await APIClient.shared.logout(id); await load(fresh: true) }
        catch { errorMessage = error.localizedDescription }
    }

    func saveKey(_ id: String, key: String) async {
        do { _ = try await APIClient.shared.setKey(id, key: key); await load(fresh: true) }
        catch { errorMessage = error.localizedDescription }
    }

    func removeKey(_ id: String) async {
        do { _ = try await APIClient.shared.removeKey(id); await load(fresh: true) }
        catch { errorMessage = error.localizedDescription }
    }

    func setTier(_ id: String, tier: String?) async {
        do { _ = try await APIClient.shared.setTier(id, tier: tier); await load(fresh: true) }
        catch { errorMessage = error.localizedDescription }
    }
}
```

- [ ] **Step 4: Build**

Run: `cd app/CicadaApp && swift build`
Expected: `Build complete!`

- [ ] **Step 5: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Models/Connection.swift \
  app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift \
  app/CicadaApp/Sources/CicadaApp/ViewModels/ConnectionsViewModel.swift
git commit -m "feat(app): connection models, API client methods, ConnectionsViewModel"
```

---

### Task 10: Connections page + navigation

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Connections/ConnectionsView.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Sidebar/SidebarView.swift:3-45` (add `connections` case, icon, section)
- Modify: `app/CicadaApp/Sources/CicadaApp/ContentView.swift:67-82` (switch arm)

**Interfaces:**
- Consumes: `ConnectionsViewModel`, `CicadaTheme`, `glassCard()`, `PageHeader`, `CommandBox`, logos in `Resources/logos/` (`claude-code.png`, `codex.png`)

- [ ] **Step 1: Navigation**

In `SidebarView.swift` add `case connections = "Connections"` after `case contributors`, icon `case .connections: "person.crop.circle.badge.checkmark"`, and change the setup section to `case .setup: [.connections, .connect]`. In `ContentView.swift` add `case .connections: ConnectionsView()` to the switch.

- [ ] **Step 2: The view**

```swift
// app/CicadaApp/Sources/CicadaApp/Views/Connections/ConnectionsView.swift
import AppKit
import SwiftUI

/// G50 — one card per provider connection. Subscriptions are probed through the
/// vendor CLI (Cicada never holds a token); API keys go to ~/.cicada/secrets.env.
struct ConnectionsView: View {
    @State private var viewModel = ConnectionsViewModel()
    @State private var keyDrafts: [String: String] = [:]
    @State private var confirmDisconnect: ConnectionStatus?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
            PageHeader(title: "Connections",
                       subtitle: "Which plan or key powers Cicada. Subscriptions sign in through their own CLI — Cicada never sees the token.") {
                Button { Task { await viewModel.load(fresh: true) } } label: { Image(systemName: "arrow.clockwise") }
            }

            if let err = viewModel.errorMessage {
                Text(err).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.statusColor(for: .decaying))
            }

            if viewModel.isLoading {
                ProgressView().frame(maxWidth: .infinity, alignment: .center)
            } else {
                ScrollView {
                    VStack(spacing: CicadaTheme.spacingMD) {
                        ForEach(viewModel.connections) { c in
                            ConnectionCard(
                                connection: c,
                                keyDraft: Binding(get: { keyDrafts[c.id, default: ""] }, set: { keyDrafts[c.id] = $0 }),
                                pendingLogin: viewModel.pendingLogin?.connectionId == c.id ? viewModel.pendingLogin : nil,
                                awaitingTerminal: viewModel.awaitingTerminal == c.id,
                                onConnect: { Task { await connect(c) } },
                                onDisconnect: { confirmDisconnect = c },
                                onSaveKey: { Task { await viewModel.saveKey(c.id, key: keyDrafts[c.id, default: ""]); keyDrafts[c.id] = "" } },
                                onTier: { tier in Task { await viewModel.setTier(c.id, tier: tier) } }
                            )
                        }
                    }
                }
            }
            Spacer()
        }
        .padding(CicadaTheme.spacingLG)
        .task { await viewModel.load(); viewModel.startPolling() }
        .onDisappear { viewModel.stopPolling() }
        .confirmationDialog("Disconnect \(confirmDisconnect?.label ?? "")?",
                            isPresented: Binding(get: { confirmDisconnect != nil }, set: { if !$0 { confirmDisconnect = nil } }),
                            presenting: confirmDisconnect) { c in
            Button("Disconnect", role: .destructive) { Task { await viewModel.logout(c.id) } }
        } message: { c in
            Text(c.id == "claude-plan"
                 ? "Runs `claude auth logout`. Claude Code will ask you to sign in again next time you open it."
                 : c.id == "chatgpt-plan" ? "Runs `codex logout`." : "Removes the key from ~/.cicada/secrets.env.")
        }
    }

    private func connect(_ c: ConnectionStatus) async {
        guard let session = await viewModel.beginLogin(c.id) else { return }
        if session.mode == "terminal", let cmd = session.command {
            openInTerminal(cmd)
        }
    }

    /// Hand the interactive browser-OAuth login to Terminal (Claude Code needs a TTY).
    private func openInTerminal(_ command: String) {
        let script = "tell application \"Terminal\"\nactivate\ndo script \"\(command)\"\nend tell"
        if let apple = NSAppleScript(source: script) {
            var err: NSDictionary?
            apple.executeAndReturnError(&err)
            if err != nil {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(command, forType: .string)
            }
        }
    }
}

private struct ConnectionCard: View {
    let connection: ConnectionStatus
    @Binding var keyDraft: String
    let pendingLogin: LoginSession?
    let awaitingTerminal: Bool
    let onConnect: () -> Void
    let onDisconnect: () -> Void
    let onSaveKey: () -> Void
    let onTier: (String?) -> Void

    private var logo: String? {
        switch connection.id {
        case "claude-plan": "claude-code"
        case "chatgpt-plan": "codex"
        default: nil
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingMD) {
                if let logo, let url = Bundle.module.url(forResource: logo, withExtension: "png", subdirectory: "Resources/logos"),
                   let img = NSImage(contentsOf: url) {
                    Image(nsImage: img).resizable().frame(width: 28, height: 28).cornerRadius(6)
                } else {
                    Image(systemName: connection.isKeyBased ? "key.fill" : "cpu").frame(width: 28, height: 28)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(connection.label).font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
                    Text(connection.priceLine).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                }
                Spacer()
                statusPill
            }

            if let account = connection.account, connection.connected {
                Text(account).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if let note = connection.priceNote, connection.connected, connection.priceUsdMonth == nil {
                Text(note).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            if let detail = connection.detail, !connection.connected {
                Text(detail).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }

            if connection.connected, connection.plan == "max" || connection.plan == "pro", connection.isSubscription,
               connection.id == "claude-plan" || (connection.id == "chatgpt-plan" && connection.plan == "pro") {
                Picker("Tier", selection: Binding(get: { connection.tier ?? "" }, set: { onTier($0.isEmpty ? nil : $0) })) {
                    Text("Pick tier…").tag("")
                    Text("5x").tag("5x")
                    Text("20x").tag("20x")
                }
                .pickerStyle(.segmented).frame(maxWidth: 260)
            }

            actions
        }
        .padding(CicadaTheme.spacingMD)
        .glassCard()
    }

    private var statusPill: some View {
        let (text, color): (String, Color) = !connection.available
            ? ("Not installed", CicadaTheme.textTertiary)
            : connection.connected ? ("Connected", CicadaTheme.statusColor(for: .active))
            : ("Not connected", CicadaTheme.textSecondary)
        return Text(text).font(CicadaTheme.captionFont).foregroundStyle(color)
            .padding(.horizontal, CicadaTheme.spacingSM).padding(.vertical, 2)
            .background(color.opacity(0.12)).cornerRadius(CicadaTheme.cornerRadiusSmall)
    }

    @ViewBuilder
    private var actions: some View {
        if connection.isKeyBased {
            HStack(spacing: CicadaTheme.spacingSM) {
                if connection.connected {
                    Button("Remove key", role: .destructive, action: onDisconnect)
                } else {
                    SecureField("Paste API key", text: $keyDraft).textFieldStyle(.roundedBorder).frame(maxWidth: 360)
                    Button("Save", action: onSaveKey).disabled(keyDraft.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        } else if connection.billing == "free" {
            if !connection.connected, let cmd = connection.login?.command { CommandBox(command: cmd) }
        } else if connection.connected {
            Button("Disconnect", role: .destructive, action: onDisconnect)
        } else if !connection.available {
            EmptyView()
        } else if let pending = pendingLogin {
            deviceCode(pending)
        } else if awaitingTerminal, let cmd = connection.login?.command {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text("Finish signing in in the Terminal window, then this card updates itself.")
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                CommandBox(command: cmd)
            }
        } else {
            Button("Connect", action: onConnect).buttonStyle(.borderedProminent)
        }
    }

    private func deviceCode(_ s: LoginSession) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if s.state == "failed" {
                Text(s.detail ?? "Sign-in failed").foregroundStyle(CicadaTheme.statusColor(for: .decaying))
            } else if let code = s.code {
                Text("Enter this code in your browser:").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                HStack(spacing: CicadaTheme.spacingMD) {
                    Text(code).font(CicadaTheme.monoFont.weight(.bold)).textSelection(.enabled)
                    if let url = s.url.flatMap(URL.init(string:)) { Link("Open sign-in page", destination: url) }
                }
                ProgressView().controlSize(.small)
            } else {
                HStack { ProgressView().controlSize(.small); Text("Starting `codex login --device-auth`…").font(CicadaTheme.captionFont) }
                if !s.rawOutput.isEmpty { Text(s.rawOutput).font(CicadaTheme.monoFont).foregroundStyle(CicadaTheme.textTertiary) }
            }
        }
    }
}
```

`CommandBox`'s initializer is `CommandBox(command:)` in `Views/Common/CommandBox.swift` — check its exact label and adjust the two call sites if it differs.

- [ ] **Step 3: Build and smoke-run**

Run: `cd app/CicadaApp && swift build && ./bundle.sh --run`
Expected: builds; the sidebar shows **Connections** under Setup; with the backend running, cards render for Claude plan, ChatGPT plan, four API keys and Ollama; "Connect" on Claude opens Terminal with `claude auth login`.

- [ ] **Step 4: Commit**

```bash
git add app/CicadaApp/Sources/CicadaApp/Views/Connections/ConnectionsView.swift \
  app/CicadaApp/Sources/CicadaApp/Views/Sidebar/SidebarView.swift app/CicadaApp/Sources/CicadaApp/ContentView.swift
git commit -m "feat(app): Connections page — plan/price cards, connect/disconnect, device-code + Terminal hand-off"
```

---

### Task 11: Docs + install/doctor alignment

**Files:**
- Modify: `CLAUDE.md` (API Design list: add the `/connections` lines and the auth note)
- Modify: `install.sh` (print the token-file path in the final summary; no key prompt changes here — that is G49 P0's keyless rewrite)
- Modify: `docs/goals/memory-evolution.md` (G50 status → 🛠️ / ✅ with commit hashes)

- [ ] **Step 1: CLAUDE.md** — add under the API Design block:

```
GET  /connections, GET /connections/{id}   → provider connections (plan, price, connected) — probed via vendor CLIs
POST /connections/{id}/login|logout        → start the vendor CLI's own login flow / sign out
GET  /connections/{id}/login/{sid}         → device-code login progress (ChatGPT/Codex)
PUT/DELETE /connections/{id}/key           → BYOK key into ~/.cicada/secrets.env (0600)
PUT  /connections/{id}/prefs               → tier override (Claude Max 5x/20x), enabled flag
```

and, above the list: *"Every endpoint except `GET /healthz` requires `Authorization: Bearer <token>` — the token lives at `~/.cicada/api_token` (`CICADA_API_TOKEN` overrides; `CICADA_API_AUTH=off` for tests)."*

- [ ] **Step 2: install.sh** — in the final "next steps" echo block add: `echo "  API token: ${CICADA_HOME:-$HOME/.cicada}/api_token (the app and MCP server read it automatically)"`.

- [ ] **Step 3: Full verification**

Run: `api/.venv/bin/python -m pytest api/tests -q && (cd app/CicadaApp && swift build)`
Expected: all tests green, build complete.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md install.sh docs/goals/memory-evolution.md
git commit -m "docs: connections endpoints + API token in CLAUDE.md/install.sh; G50 status"
```

---

## Self-review

- **Spec coverage:** §2 compliance → Tasks 5/6 (CLI delegation, no Keychain, no usage endpoints); §5.1 model → Task 4; §5.2 adapters → Tasks 5–7; §5.3 registry/prefs/secrets → Tasks 2, 8; §5.4 API → Task 8; §5.5 auth → Task 1; §5.6 page → Tasks 9–10; §7 error handling → adapters never raise (Tasks 5–7), `run_cli` rc 124/127 (Task 4); §8 tests → every Python task; Swift build-verified (no logic worth a unit test here — the dashboard plan adds the test target).
- **Not covered on purpose:** Gemini/Copilot adapters (spec §3.10 — hidden until built; adding one = one file implementing `ConnectionAdapter` + one line in `Registry.adapters()`); optional `?validate=true` key validation (spec §5.2 — deferred, off by default anyway).
- **Type consistency:** `ConnectionStatus.engine_role` values `subscription-cli|byok|local` used by `/status.connections.engine`; `LoginSession.mode` ∈ `terminal|device-code|key|none` in both Python and Swift; `VALID_TIERS` matches `pricing.TIERED` tiers.

## Execution handoff

Plan complete. Two execution options: **Subagent-Driven** (fresh subagent per task with review between tasks — recommended) via `superpowers:subagent-driven-development`, or **Inline** via `superpowers:executing-plans`. Task 1 must land first; Tasks 2–7 are independent of each other after that; Task 8 needs 2–7; Tasks 9–10 need 8.
