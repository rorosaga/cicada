"""ChatGPT plan connection — delegates to the ``codex`` CLI, in Cicada's own home.

Every ``codex`` child runs with ``CODEX_HOME = $CICADA_HOME/codex``
(``base.scrubbed_env``, spec Decision 2): Cicada's sign-in is its own,
separate from Codex in the person's terminal. Login state comes from ``codex
login status`` (exit 0 = logged in). Plan, email and account type come from
the read-only ``codex app-server`` (``codex_app_server.snapshot``) — Cicada
never opens ``auth.json`` (R-E8). Login is ``codex login --device-auth``: the
app shows the one-time code and opens the link; a watcher flips the session
to ``done`` when the process exits 0 (R-E28). Logout is ``codex logout``.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import HTTPException
from loguru import logger

from api.models.schemas import ConnectionKind, ConnectionStatus, LoginHint, LoginSession
from api.services import codex_app_server, pricing
from api.services.connections.base import (
    Runner, codex_home, override_note, resolve_binary, run_cli, scrubbed_env,
)

_URL_RE = re.compile(r"https?://\S+")
_CODE_RE = re.compile(r"\b[A-Z0-9]{4,}-[A-Z0-9]{4,}\b")
_INSTALL_HINT = "Install Codex CLI (npm i -g @openai/codex), then Sign in with ChatGPT here."
# R-E28: the sign-in is in-app now, so no line tells a person to open a
# terminal — and "Connect" was never the button's name.
_SIGNED_OUT = "Not signed in — “Sign in with ChatGPT” shows a one-time code to enter on the ChatGPT website."
# An API-key login in Cicada's home would bill per token behind a card that
# says "plan" — refuse to call it connected and say how to fix it.
_API_KEY = ("Cicada's Codex sign-in is using an API key, not a ChatGPT plan — that bills per token. "
            "Sign out, then Sign in with ChatGPT.")
# R-E24: conditional — the card is connected whether or not Sleep runs on it;
# the POWERS line says which, this line says whose sign-in and through what.
_HOW = ("Signed in to ChatGPT with Cicada's own Codex sign-in on this Mac — separate from Codex in "
        "your terminal. When Sleep or Ask runs on your ChatGPT plan it goes through `codex exec`; "
        "Cicada never sees your token.")

login_sessions: dict[str, LoginSession] = {}
_watchers: set[asyncio.Task] = set()
# Most-recent live (pending or just-finished) session per connection id, paired
# with its subprocess — lets a repeated Connect kill a still-running prior
# ``codex login --device-auth`` instead of leaking it.
_live: dict[str, tuple[LoginSession, asyncio.subprocess.Process]] = {}
RAW_OUTPUT_CAP = 4096


def codex_home_dir() -> Path:
    """Cicada's own Codex home — ``base.codex_home()`` (R-E7). The inherited
    ``CODEX_HOME`` (the person's own ~/.codex) is never read here any more."""
    return codex_home()


def parse_device_output(text: str) -> tuple[str | None, str | None]:
    url = _URL_RE.search(text)
    code = _CODE_RE.search(text)
    return (code.group(0) if code else None), (url.group(0).rstrip(".,") if url else None)


class CodexPlanAdapter:
    id = "chatgpt-plan"
    label = "ChatGPT plan"
    kind = ConnectionKind.subscription

    def __init__(self, runner: Runner | None = None, tier: str | None = None,
                 spawn: Callable[[list[str]], Awaitable] | None = None,
                 snapshot: Callable[..., Awaitable] | None = None):
        self._run = runner or run_cli
        self._tier = tier
        self._spawn = spawn or self._default_spawn
        # Bound per adapter: `Registry.adapters()` builds fresh adapters on
        # every call, so a monkeypatched `codex_app_server.snapshot` is
        # honoured by the next registry read (R-E8/R-E18).
        self._snapshot = snapshot or codex_app_server.snapshot

    @staticmethod
    async def _default_spawn(argv: list[str]):
        # R-E28: resolved like every other spawn (a launchd PATH may not
        # carry the install dir), and in Cicada's own Codex home.
        binary = resolve_binary(argv[0])
        if binary is None:
            raise FileNotFoundError(argv[0])
        return await asyncio.create_subprocess_exec(
            binary, *argv[1:], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, env=scrubbed_env(argv[0]),
        )

    def available(self) -> bool:
        return resolve_binary("codex") is not None

    def _base(self, **kw) -> ConnectionStatus:
        kw.setdefault("engine_role", None)
        return ConnectionStatus(
            id=self.id, label=self.label, kind=self.kind, billing="subscription",
            tier=self._tier,
            login=LoginHint(mode="device-code", command="codex login --device-auth"), **kw,
        )

    async def status(self) -> ConnectionStatus:
        if not self.available():
            return self._base(available=False, detail=_INSTALL_HINT)
        res = await self._run(["codex", "login", "status"])
        if res.rc == 127:
            return self._base(available=False, detail=_INSTALL_HINT)
        if res.rc != 0:
            return self._base(available=True, detail=_SIGNED_OUT)
        # R-E8/R-E18: the app-server (30 s cached, read-only, no quota) answers
        # plan, email and account type with Codex reading its own file. `None`
        # (unavailable) keeps the card connected on `codex login status` alone
        # and only the plan name goes missing; the CLI's own wording is the
        # API-key fallback then.
        snap = await self._snapshot()
        api_key_login = "api key" in (res.stdout + res.stderr).lower()
        if (snap is not None and snap.signed_in and snap.account_type not in (None, "chatgpt")) or (
                snap is None and api_key_login):
            return self._base(available=True, detail=_API_KEY)
        plan = snap.plan if snap else None
        usd, price_note = (None, "plan not detected") if plan is None else pricing.price_for(self.id, plan, self._tier)
        # `override`, never `note`: `price_note` above is the price note (R-E6).
        override = override_note("codex")
        return self._base(
            available=True, connected=True, plan=plan, engine_role="subscription-cli",
            plan_label=pricing.plan_label(self.id, plan, self._tier),
            account=snap.email if snap else None, price_usd_month=usd, price_note=price_note,
            how=f"{_HOW} {override}" if override else _HOW,
        )

    async def begin_login(self) -> LoginSession:
        prior = _live.get(self.id)
        if prior is not None:
            prior_sess, prior_proc = prior
            if prior_sess.state == "pending":
                try:
                    prior_proc.kill()
                except ProcessLookupError:
                    pass
                prior_sess.state = "failed"
                prior_sess.detail = "superseded"
                self._prune_terminal_sessions(keep_session_id=prior_sess.session_id)

        sess = LoginSession(session_id=uuid.uuid4().hex, connection_id=self.id, mode="device-code",
                            command="codex login --device-auth")
        # Spawn FIRST, register after. Registering a "pending" session before
        # the process exists left an orphan in `login_sessions` — never pruned
        # (pruning only touches terminal sessions), polled forever by the app —
        # whenever the binary vanished between `available()` and here.
        try:
            proc = await self._spawn(["codex", "login", "--device-auth"])
        except Exception as exc:
            logger.warning(f"codex login spawn failed: {type(exc).__name__}: {exc}")
            raise HTTPException(
                status_code=502,
                detail=f"Could not start `codex login --device-auth`: {exc}. {_INSTALL_HINT}",
            ) from exc
        login_sessions[sess.session_id] = sess
        _live[self.id] = (sess, proc)
        task = asyncio.get_running_loop().create_task(self._watch(sess, proc))
        _watchers.add(task)
        task.add_done_callback(_watchers.discard)
        return sess

    def _prune_terminal_sessions(self, keep_session_id: str) -> None:
        """Drop other terminal (``done``/``failed``) sessions for this
        connection, keeping ``keep_session_id`` retrievable (the app is still
        polling it) so ``login_sessions`` doesn't grow forever."""
        for sid, s in list(login_sessions.items()):
            if s.connection_id == self.id and sid != keep_session_id and s.state in ("done", "failed"):
                del login_sessions[sid]

    async def _watch(self, sess: LoginSession, proc) -> None:
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace")
                sess.raw_output += text
                if len(sess.raw_output) > RAW_OUTPUT_CAP:
                    sess.raw_output = sess.raw_output[-RAW_OUTPUT_CAP:]
                code, url = parse_device_output(sess.raw_output)
                sess.code, sess.url = sess.code or code, sess.url or url
            rc = await proc.wait()
            sess.state = "done" if rc == 0 else "failed"
            if rc != 0:
                # R-E28: the Plans & keys card shows this line to a person.
                sess.detail = f"Sign-in didn't finish (codex exited {rc})."
            else:
                # A fresh sign-in changes plan/email — never serve the
                # signed-out snapshot for the rest of its 30 s.
                codex_app_server.invalidate()
        except Exception as exc:  # never let a watcher crash the loop
            logger.warning(f"codex login watcher failed: {exc}")
            sess.state, sess.detail = "failed", str(exc)
        finally:
            # Only prune on an actual terminal transition — a cancelled watch
            # (e.g. event-loop shutdown) must not prune the *other* sessions
            # for this connection while this one is still "pending".
            if sess.state in ("done", "failed"):
                self._prune_terminal_sessions(keep_session_id=sess.session_id)

    async def logout(self) -> None:
        # `run_cli` runs every `codex` child in Cicada's own home (R-E7), so
        # this signs out Cicada's sign-in only — never Codex in the terminal.
        await self._run(["codex", "logout"])
        codex_app_server.invalidate()
