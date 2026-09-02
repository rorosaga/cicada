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
        kw.setdefault("engine_role", None)
        return ConnectionStatus(
            id=self.id, label=self.label, kind=self.kind, billing="subscription",
            tier=self._tier,
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
        if plan is None:
            usd, note = None, "plan not detected — run the CLI once to refresh"
        else:
            usd, note = pricing.price_for(self.id, plan, self._tier)
        account = info.get("email")
        who = f"as `{account}`" if account else "on your Claude account"
        return self._base(
            available=True, connected=True, plan=plan, engine_role="subscription-cli",
            plan_label=pricing.plan_label(self.id, plan, self._tier),
            account=account, price_usd_month=usd, price_note=note,
            detail=info.get("orgName"),
            how=(
                f"Signed in to Claude Code on this Mac {who}. Cicada runs its "
                "memory work through the `claude` CLI on your plan — it never "
                "sees your token."
            ),
        )

    async def begin_login(self) -> LoginSession:
        return LoginSession(session_id=uuid.uuid4().hex, connection_id=self.id, mode="terminal", command=LOGIN_COMMAND)

    async def logout(self) -> None:
        await self._run(["claude", "auth", "logout"])
