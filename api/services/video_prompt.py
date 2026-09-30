"""The video run's hand-off prompt (G162, spec §4.8): plain text the person copies
into an agent they already use.

Pure, ``<= MAX_CHARS`` and provider-neutral (R-VU11): it describes the step, and
names no provider, model or skill as the one that does the job. It names only
tools that exist (R12), carries no video content, and makes no promise about
what the agent does in its own tools — it is an instruction.

**No browser route by default (R-VU10, amended by ruling 17).** The default text
never steers an agent into the person's signed-in browser. When the person
turns on the single permission ("let an agent use your browser to read pages"),
the routes pass :data:`BROWSER_CLAUSE`: their consent, carried as an instruction.
No site is named — the clause and the permission apply to every host (P3).

**How the person's agent watches (ruling 17, G178).** ``method_clause`` is the
person's ``watching`` choice (``agent_methods``: their own agent's tools, or a skill they
picked from the catalog) as one neutral line, or ``None`` for "Let my agent choose". The
hand-off prompt says it in the first person; the claim reply says it in the third and only
to a local catalog agent, and never to a remote connection.
"""
from __future__ import annotations

from pathlib import Path

MAX_CHARS = 1200

#: Provider-neutral; an instruction, not a promise (R-RW8). The person's consent
#: is the single reading permission — Settings → Agents.
BROWSER_CLAUSE = (
    "The person has allowed you to use their signed-in browser. If a video needs a sign-in, open it there. "
    "Do not type credentials, post, comment or change anything. If it still won't open, hand it back with "
    "code needs_login."
)

_METHOD_LINES = {
    "captions": "Preferred method: captions or a transcript are enough; skip frames.",
    "link": "Preferred method: give a model that takes video the link directly.",
}
#: The person's watching clause is capped so the prompt's 1,200-character promise holds whatever
#: fills it (the longest real clause is asserted to fit in ``test_video_prompt``).
MAX_METHOD_CLAUSE_CHARS = 130


def method_line(method: str | None) -> str | None:
    """The run card's *How* choice as one line; ``auto`` says nothing."""
    return _METHOD_LINES.get(str(method or "auto"))


def method_clause(memory_path: Path | None = None, *, reply: bool = False, variant: str | None = None,
                  remote: bool = False) -> str | None:
    """The person's chosen way for their agent to watch, as one neutral line, or ``None``.
    ``reply=True`` is the third-person voice of a tool's reply (nothing for a remote connection;
    a skill only for a catalog agent's ``variant``); the default is the hand-off prompt's."""
    from api.services import agent_methods

    if reply:
        return agent_methods.reply_clause("watching", variant=variant, remote=remote)
    return agent_methods.prompt_clause("watching")


def tools_phrase(clause: str | None, *, reply: bool = False) -> str:
    """What the default text says the video is watched with; a pointer at the choice once one is made,
    so the words never contradict the clause."""
    if not clause:
        return "your own tools"
    return "the tool the person chose" if reply else "the tool I chose"


def build(count: int, method: str | None = "auto", *, browser_clause: str | None = None,
          method_clause: str | None = None) -> str:
    """The hand-off prompt for ``count`` videos waiting in the person's queue."""
    n = max(0, int(count or 0))
    waiting = "no videos" if n == 0 else ("1 video" if n == 1 else f"{n} videos")
    lines = [
        f"Cicada has {waiting} waiting for you to read or watch.",
        "1. Call cicada_video_claim until it returns nothing: up to 10 links a call, each marked transcript or "
        "watch.",
        f"2. Read or watch each with {tools_phrase(method_clause)}. A transcript job needs captions or a transcript; a watch job, "
        "frames or a model that takes the link. Cicada downloads and watches nothing.",
        "3. Record each with cicada_record_watch(url, summary, excerpts=[{t, quote}], basis, engine, duration): "
        "basis is what you used (transcript, frames or both); one paragraph, at most 12 short quotes, "
        "no transcript.",
        "4. If you can't, hand it back with cicada_video_claim(release=[{url, code, reason}]); use code "
        "needs_login if it needs the person to sign in, and never sign in yourself.",
    ]
    for extra in (method_line(method), (method_clause or "")[:MAX_METHOD_CLAUSE_CHARS] or None, browser_clause):
        if extra:
            lines.append(extra)
    lines.append("If you can run sub-agents, one per video is fine.")
    return "\n".join(lines)
