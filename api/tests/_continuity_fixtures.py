"""Synthetic Stop-hook episodes in capture's exact shape, for the G110 tests.

Built with capture's own helpers (`_body`, `_turn_sidecar`, `capture_meta`),
so the body, the G118 sidecar and the continuity metadata are byte for byte
what `transcript_capture` writes. Placeholders only: `alpha-project`,
`/home/example/...`."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.services import markdown_parser
from api.services import transcript_capture as tc
from api.services.transcript_extract import Conversation, Turn

CWD = "/home/example/alpha-project"
#: Relative to now, so a fixture never falls out of the registry's 30-day window.
T0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=3)


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


def sid(n: int) -> str:
    return f"{n:08d}-2222-4333-8444-555555555555"


def write_session(memory: Path, n: int, turns, *, session: str | None = None, cwd: str = CWD,
                  start: float = 0.0, step: float = 1.0, harness: str = "claude-code", processed: bool = False,
                  processed_by: str | None = None, extra_meta: dict | None = None, untimed: bool = False) -> Path:
    """Episode ``ep_2026-09-03_<n>`` for one session whose turns start at
    ``at(start)`` and are ``step`` minutes apart."""
    conv_turns = [Turn(role=r, text=t, ts=None if untimed else at(start + i * step)) for i, (r, t) in enumerate(turns)]
    conv = Conversation(harness=harness, session_id=session or sid(n), cwd=cwd, started_at=None, ended_at=None,
                        turns=conv_turns, summary={"kept": {"user": 0, "assistant": 0}})
    body = "\n".join(f"{t.role}: {t.text}" for t in conv_turns)
    ep_id = f"ep_2026-09-03_{n:03d}"
    fm = {
        "id": ep_id, "timestamp": at(start), "source": harness, "origin": harness,
        "title": turns[0][1].splitlines()[0][:72] if turns else "session", "processed": processed,
        "content_hash": hashlib.sha256(body.encode()).hexdigest()[:12], "session_id": session or sid(n),
        "harness": harness, "capture_kind": "transcript",
        "captured_at": at(start + max(0, len(turns) - 1) * step), "project_dir": cwd,
    }
    if processed_by:
        fm["processed_by"] = processed_by
    fm.update(tc.capture_meta(conv, body))
    if extra_meta:
        fm.update(extra_meta)
    sidecar = tc._turn_sidecar(conv, body)
    if sidecar:
        fm["turns"] = sidecar
    path = memory / "episodes" / f"{ep_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, fm, body)
    return path


def write_other_episode(memory: Path, n: int) -> Path:
    """A non-session episode (an MCP save) — never a continuity candidate."""
    path = memory / "episodes" / f"ep_2026-09-04_{n:04d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, {"id": path.stem, "timestamp": at(0), "source": "mcp", "processed": False,
                                 "title": "a saved note"}, "a note about something else")
    return path
