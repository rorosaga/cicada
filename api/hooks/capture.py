#!/usr/bin/env python3
"""Cicada session-capture hook (G105 R1, R2, R8, R14).

Registered by ``install.sh`` under ``hooks.Stop`` — and, as a flush,
``hooks.PreCompact`` and ``hooks.SessionEnd`` (G110 gate A) — in
``~/.claude/settings.json`` (and ``~/.codex/hooks.json`` when Codex is installed) as::

    "<venv python>" "<repo>/api/hooks/capture.py" --harness claude-code

The harness pipes its hook JSON to stdin (``session_id``, ``transcript_path``,
``cwd``, ``hook_event_name``); this script POSTs exactly those fields — and,
when the harness sends one, ``effort.level`` as ``effort`` (round 4 C1) — to
``POST /capture/transcript`` and exits 0 — always, within 3 s, printing
nothing to stdout (a Stop hook's stdout is parsed by the harness). It never
opens the transcript: the backend validates the path against the harness
root and does the one read (R2).

Why ``Stop`` and not ``SessionEnd`` (R1): ``SessionEnd`` only fires on a
graceful exit and shares a 1.5 s budget with every other SessionEnd hook; a
closed terminal or a killed process never reaches it. ``Stop`` fires after
every reply, and the endpoint is idempotent by content hash (R3), so the LAST
Stop of a session is the session's end however it ended — volume is cost,
never noise.

G110 gate A (ruling 2026-10-07): the same script is ALSO registered under
``PreCompact`` and ``SessionEnd`` as a best-effort flush. Stop stays the
trigger; a flush is the same idempotent request (``unchanged`` after a Stop
with no new turn), and it is the only capture of a turn the person interrupted
— no Stop fires — before compacting, clearing or quitting. A SessionEnd flush
bounds its REQUEST with :data:`SESSION_END_TIMEOUT_S` (a socket timeout, not a
whole-process deadline). Claude Code's SessionEnd budget is 1.5 s by default
but is raised to the largest per-hook ``timeout`` in the settings files, and
Cicada registers 5 s (``registry.DEFAULT_TIMEOUT_S``) — so a slow exit is
bounded by that request timeout plus interpreter start, not by 1.5 s. A
concurrent or delayed capture never overwrites a newer one: the writer refuses
a read of fewer transcript bytes than the episode stores (``superseded``).
Every log line names its event, so ruling 7's revisit
signal (a Stop ``error:`` line) never mixes with a flush's.

Stdlib only, run by path: a hook has no cwd guarantee and no venv on its
``sys.path``, so nothing here imports ``api.*`` (R14).

``CICADA_CAPTURE=off`` in the environment exits before any request: every
CLI Cicada itself spawns (Sleep's ``claude -p`` engine, doctor probes) runs
under ``connections/base.scrubbed_env()`` which sets it, so Cicada's own
extraction prompts are never captured back into the bank (R8) — without it a
Sleep cycle on a plan engine would fire this hook on its own prompts and
write them back as episodes, a feedback loop.

Gemini CLI (capture-everywhere): registered under ``AfterAgent`` as
``--harness gemini-cli``. Its payload carries the exchange itself — ``prompt``
and ``prompt_response``, plus ``stop_hook_active`` on a retry of the same
prompt — so this script posts those two strings to ``POST /capture/turn``
(``turn_capture``) instead of a transcript path: Gemini CLI does send one, but
documents neither its format nor a confined root, while the two strings already
are what is kept — so the path is never forwarded and the backend opens nothing. Gemini CLI reads a hook's
stdout as JSON, so for it this script prints ``{}``. Unverified against an
installed Gemini CLI; the log line is the verification signal.

Codex (R9): its Stop payload is unverified, so a payload without
``transcript_path`` is logged as ``skipped: no transcript_path`` and exits 0
— nothing breaks, and that log line is the verification signal.

One line per firing goes to ``~/.cicada/logs/capture.log`` (0600): a
timestamp, the harness, the first 8 characters of the session id, the event
(``Stop`` | ``PreCompact`` | ``SessionEnd`` | ``other``), and the outcome — plus, when the demo memory was open, the name of the bank the
session was saved into (G141 capture-side track) — never a path, never
content. The token comes from
``~/.cicada/api_token``, never from an env-embedded key.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from workspace_identity import observe_if_needed, remember  # stdlib sibling, run by path

TIMEOUT_S = 3.0
#: G110 gate A: a SessionEnd flush delays the session's exit, so its request
#: gives up early and says so in the log (the backend finishes the write regardless).
SESSION_END_TIMEOUT_S = 1.2
#: The events this script is registered under; anything else logs as ``other``.
EVENTS = ("Stop", "PreCompact", "SessionEnd", "AfterAgent")
LOG_MAX_BYTES = 1024 * 1024
#: Harnesses whose hook carries the turn's words, posted to ``/capture/turn``.
TURN_HARNESSES = ("gemini-cli",)
#: A turn payload holds the person's prompt and the reply; read at most this much.
TURN_INPUT_BYTES = 1024 * 1024
#: What one turn may post (the backend's ``turn_capture.TEXT_MAX_CHARS``).
TEXT_MAX_CHARS = 256 * 1024


def _post_exchange(payload: dict, *, harness: str, session_id: str, home: Path, environ, post, token: str):
    """Gemini CLI's ``AfterAgent``: the prompt and the final reply, as one exchange."""
    prompt, reply = payload.get("prompt"), payload.get("prompt_response")
    messages = [{"speaker": speaker, "text": text[:TEXT_MAX_CHARS]}
             for speaker, text in (("user", prompt), ("assistant", reply))
             if isinstance(text, str) and text.strip()]
    if not messages:
        return None, "skipped: no prompt"
    body = {"harness": harness, "session_id": session_id, "messages": messages,
            "retry": payload.get("stop_hook_active") is True,
            "cwd": payload.get("cwd") if isinstance(payload.get("cwd"), str) else None,
            "hook_event": payload.get("hook_event_name")}
    port = str(environ.get("CICADA_PORT") or "8000")
    return post(f"http://127.0.0.1:{port}/capture/turn", json.dumps(body).encode("utf-8"), token, TIMEOUT_S), None


def _default_post(url: str, body: bytes, token: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - loopback only
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # A 4xx/5xx is an outcome to log (the endpoint's enum refusal reason
        # rides in ``detail``), not a hook failure.
        return exc.code, exc.read().decode("utf-8", "replace")


def _log(path: Path, message: str) -> None:
    """Append one line, 0600, rotating once past :data:`LOG_MAX_BYTES`.
    A log failure must never become a hook failure — swallow ``OSError``."""
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_suffix(".log.1"))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n".encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass


def _outcome(text: str) -> str:
    try:
        parsed = json.loads(text)
        outcome = parsed.get("status") or parsed.get("detail") or ""
        # A validation error's `detail` is a list that echoes the request — the
        # person's words, for a turn — so only a plain string reason is logged.
        outcome = outcome if isinstance(outcome, str) else "invalid request"
        if parsed.get("redirectedFrom"):
            # R-CS12: the demo bank was open, so the backend saved this
            # session into a real bank — say which (a name, never a path).
            outcome += f" into {parsed.get('bank')} (the demo memory is open)"
        return outcome
    except (ValueError, AttributeError):
        return ""


def main(argv=None, *, stdin=None, stdout=None, environ=None, post=None, log_path=None, token_path=None) -> int:
    """Forward the harness payload; return 0 unconditionally.

    Every collaborator is injectable (``stdin``, ``environ``, ``post``,
    ``log_path``, ``token_path``) so the tests exercise the whole path with no
    network and no real home directory (R14).
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    stdin = sys.stdin if stdin is None else stdin
    post = _default_post if post is None else post
    home = Path(environ.get("CICADA_HOME") or (Path.home() / ".cicada"))
    log_path = log_path or home / "logs" / "capture.log"
    token_path = token_path or home / "api_token"

    harness = "claude-code"
    if "--harness" in argv:
        try:
            harness = argv[argv.index("--harness") + 1]
        except IndexError:
            pass
    tag = f"{harness} ? ?"
    turn_harness = harness in TURN_HARNESSES
    if turn_harness:
        # Gemini CLI parses a hook's stdout as JSON; an empty object changes nothing.
        stdout = sys.stdout if stdout is None else stdout
        try:
            stdout.write("{}\n")
            stdout.flush()
        except (OSError, ValueError):
            pass
    try:
        if str(environ.get("CICADA_CAPTURE", "")).strip().lower() == "off":
            _log(log_path, f"{tag} skipped: CICADA_CAPTURE=off")
            return 0
        try:
            raw = stdin.read(TURN_INPUT_BYTES + 1) if turn_harness else stdin.read()
            if turn_harness and len(raw.encode("utf-8")) > TURN_INPUT_BYTES:
                _log(log_path, f"{tag} skipped: payload too large")
                return 0
            payload = json.loads(raw or "{}")
        except ValueError:
            _log(log_path, f"{tag} skipped: stdin is not JSON")
            return 0
        if not isinstance(payload, dict):
            _log(log_path, f"{tag} skipped: stdin is not an object")
            return 0
        session_id = str(payload.get("session_id") or "")
        event = str(payload.get("hook_event_name") or "")
        event = event if event in EVENTS else "other"
        tag = f"{harness} {session_id[:8] or '?'} {event}"
        transcript_path = payload.get("transcript_path")
        if turn_harness:
            if not session_id or event != "AfterAgent":
                _log(log_path, f"{tag} skipped: not an AfterAgent payload")
                return 0
            try:
                token = token_path.read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
            if not token:
                _log(log_path, f"{tag} skipped: no api_token at {token_path.name}")
                return 0
            answer, skipped = _post_exchange(payload, harness=harness, session_id=session_id, home=home,
                                             environ=environ, post=post, token=token)
            if skipped:
                _log(log_path, f"{tag} {skipped}")
                return 0
            status, text = answer
            _log(log_path, f"{tag} http {status} {_outcome(text)}".rstrip())
            return 0
        if not session_id or not transcript_path:
            _log(log_path, f"{tag} skipped: no transcript_path")
            return 0
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if not token:
            _log(log_path, f"{tag} skipped: no api_token at {token_path.name}")
            return 0
        port = str(environ.get("CICADA_PORT") or "8000")
        url = f"http://127.0.0.1:{port}/capture/transcript"
        fields = {
            "harness": harness,
            "session_id": session_id,
            "transcript_path": str(transcript_path),
            "cwd": payload.get("cwd"),
            "hook_event": payload.get("hook_event_name"),
        }
        effort = payload.get("effort")
        workspace = observe_if_needed(fields["cwd"], home=home, environ=environ, harness=harness,
                                      session_id=session_id)
        if workspace is not None:
            fields["workspace"] = workspace
        level = effort.get("level") if isinstance(effort, dict) else None
        if isinstance(level, str) and level.strip():
            # Round 4 D1 (C1): the reasoning effort of the reply this Stop fired
            # after, so the last turn has it even when its transcript line does
            # not. Only this one field is added; the backend validates it.
            fields["effort"] = level.strip()[:32]
        body = json.dumps(fields).encode("utf-8")
        status, text = post(url, body, token, SESSION_END_TIMEOUT_S if event == "SessionEnd" else TIMEOUT_S)
        if status == 200:
            remember(home, harness, session_id, workspace, environ=environ)
        _log(log_path, f"{tag} http {status} {_outcome(text)}".rstrip())
    except Exception as exc:  # noqa: BLE001 - the harness must never see a failure
        _log(log_path, f"{tag} error: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
