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

**Seam for the reading branch's "how your agent watches" selection** (skills the
person picked: a browser, a macOS harness, a video skill): ``method_clause`` is
an optional line, and :func:`method_clause` is the one function that will return
it once ``agent_methods`` exists. Until then it returns ``None`` and the prompt is
unchanged. The claim reply reads the same function.
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
#: The seam's line is capped so the prompt's 1,200-character promise holds whatever fills it.
MAX_METHOD_CLAUSE_CHARS = 100


def method_line(method: str | None) -> str | None:
    """The run card's *How* choice as one line; ``auto`` says nothing."""
    return _METHOD_LINES.get(str(method or "auto"))


def method_clause(memory_path: Path | None = None) -> str | None:
    """SEAM: the person's chosen way for their agent to watch (the reading branch's
    ``agent_methods``), as one neutral line, or ``None``. Nothing to return until
    that mechanism lands; the hand-off prompt and the claim reply both call this."""
    return None


def build(count: int, method: str | None = "auto", *, browser_clause: str | None = None,
          method_clause: str | None = None) -> str:
    """The hand-off prompt for ``count`` videos waiting in the person's queue."""
    n = max(0, int(count or 0))
    waiting = "no videos" if n == 0 else ("1 video" if n == 1 else f"{n} videos")
    lines = [
        f"Cicada has {waiting} waiting for you to read or watch.",
        "1. Call cicada_video_claim until it returns nothing: up to 10 links a call, each marked transcript or "
        "watch.",
        "2. Read or watch each with your own tools. A transcript job needs captions or a transcript; a watch job "
        "needs frames, or a model that takes the link. Cicada downloads and watches nothing.",
        "3. Record each with cicada_record_watch(url, summary, excerpts=[{t, quote}], basis, engine, duration): "
        "basis is what you actually used (transcript, frames or both); one paragraph, at most 12 short quotes, "
        "never the transcript.",
        "4. If you can't, hand it back with cicada_video_claim(release=[{url, code, reason}]); use code "
        "needs_login if it needs the person to sign in, and never sign in yourself.",
    ]
    for extra in (method_line(method), (method_clause or "")[:MAX_METHOD_CLAUSE_CHARS] or None, browser_clause):
        if extra:
            lines.append(extra)
    lines.append("If you can run sub-agents, one per video is fine.")
    return "\n".join(lines)
