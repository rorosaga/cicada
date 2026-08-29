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
