"""In-page claim schema + the ` ```claims ` block parser/writer (M5a).

Per the D2 final-architecture ADDENDUM (2026-06-17, authoritative): the
**editable entity page is the source of truth**, and claims live *inside* it as
a fenced ` ```claims ` YAML list — a machine layer co-located with the
human-readable prose. The claim *index* (in ``vector_index.py``) is **derived**
by parsing these blocks; it is disposable and rebuilt from markdown.

This module is the foundation only (M5a): the schema + the in-page block
parser/writer. It is deliberately NOT wired into ``/ask``, MCP, or the Sleep
cycle yet — those are later milestones.

Block format (chosen here, load-bearing for round-trip):

    ```claims
    - id: clm_2026-05-05_009
      text: "Cicada's semantic index is built on sqlite-vec."
      subject: cicada
      predicate: uses
      object: sqlite-vec
      observer: agent
      context: engineering
      ...
    ```

The YAML payload is a **list** of mappings, each a serialized :class:`Claim`.
An empty claims list still emits the fence with an empty list (``[]``) so the
machine layer is visibly present and round-trips. All prose surrounding the
fence is preserved verbatim by :func:`write_claims`.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml
from loguru import logger

# The fence label that marks the in-page machine claim block.
CLAIMS_FENCE_LANG = "claims"

# Matches a fenced ```claims ... ``` block (the language tag on the opening
# fence, then everything up to the closing fence). DOTALL so the body spans
# lines; non-greedy so we stop at the first closing fence.
_CLAIMS_BLOCK_RE = re.compile(
    r"^```claims[ \t]*\r?\n(?P<payload>.*?)^```[ \t]*\r?$\r?\n?",
    re.DOTALL | re.MULTILINE,
)


@dataclass
class Claim:
    """A single perspectival, bi-temporal belief.

    ``(observer, context, subject)`` is the conceptual primary key. Defaults are
    chosen so a minimal ``Claim(id=..., text=...)`` is valid and represents the
    common "agent extracted a generally-valid explicit fact" case.
    """

    id: str
    text: str
    subject: str = ""
    predicate: str = ""
    object: str = ""
    object_kind: str = "node"  # node | literal
    observer: str = "agent"  # agent | rodrigo | external:<name>
    context: str = "general"  # engineering|family|...|cross|general (open)
    epistemic: str = "explicit"  # explicit|deductive|inductive|abductive
    source_trust: str = "agent_extracted"  # user_stated|agent_extracted|agent_reflected|external
    confidence: float = 0.5  # 0..1, ORTHOGONAL to source_trust
    valid_from: str | None = None  # true-in-world start (date string)
    valid_to: str | None = None  # None = currently valid; a date = closed
    superseded_by: str | None = None  # claim id that replaced this one
    supersedes: str | None = None  # claim id this one closed
    recorded_at: str | None = None  # learned-by-system date
    source_episodes: list[str] = field(default_factory=list)
    premises: list[str] = field(default_factory=list)  # claim-ids derived from
    authored_by: str | None = None  # → Cicada-Author trailer; or `user`
    origin: str | None = None  # G9 harness provenance: claude-code|codex|...

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Claim":
        data = dict(data or {})
        return cls(
            id=str(data.get("id", "")),
            text=str(data.get("text", "")),
            subject=str(data.get("subject", "") or ""),
            predicate=str(data.get("predicate", "") or ""),
            object=str(data.get("object", "") or ""),
            object_kind=str(data.get("object_kind", "node") or "node"),
            observer=str(data.get("observer", "agent") or "agent"),
            context=str(data.get("context", "general") or "general"),
            epistemic=str(data.get("epistemic", "explicit") or "explicit"),
            source_trust=str(data.get("source_trust", "agent_extracted") or "agent_extracted"),
            confidence=float(data.get("confidence", 0.5) if data.get("confidence") is not None else 0.5),
            valid_from=_opt_str(data.get("valid_from")),
            valid_to=_opt_str(data.get("valid_to")),
            superseded_by=_opt_str(data.get("superseded_by")),
            supersedes=_opt_str(data.get("supersedes")),
            recorded_at=_opt_str(data.get("recorded_at")),
            source_episodes=[str(e) for e in (data.get("source_episodes") or [])],
            premises=[str(p) for p in (data.get("premises") or [])],
            authored_by=_opt_str(data.get("authored_by")),
            origin=_opt_str(data.get("origin")),
        )


def _opt_str(value: Any) -> str | None:
    """Normalize an optional scalar to ``str`` or ``None`` (YAML may parse dates)."""
    if value is None:
        return None
    return str(value)


def parse_claims(body: str) -> list[Claim]:
    """Extract the claims from the ` ```claims ` block in ``body``.

    Returns ``[]`` when no block is present (legacy page) or when the block is
    malformed (logged as a warning, never raised) — so a bad block degrades to
    "no claims" rather than crashing the index rebuild.
    """
    if not body:
        return []
    match = _CLAIMS_BLOCK_RE.search(body)
    if not match:
        return []
    payload = match.group("payload")
    try:
        loaded = yaml.safe_load(payload)
    except yaml.YAMLError as exc:
        logger.warning(f"malformed ```claims block (YAML error), ignoring: {exc}")
        return []
    if loaded is None:
        return []
    if not isinstance(loaded, list):
        logger.warning(
            "```claims block payload is not a YAML list "
            f"(got {type(loaded).__name__}), ignoring"
        )
        return []
    claims: list[Claim] = []
    for item in loaded:
        if not isinstance(item, dict):
            logger.warning("skipping non-mapping entry in ```claims block")
            continue
        claims.append(Claim.from_dict(item))
    return claims


def _render_claims_block(claims: list[Claim]) -> str:
    """Render the fenced ```claims block for ``claims`` (no trailing newline)."""
    payload = [c.to_dict() for c in claims]
    yaml_str = yaml.dump(
        payload,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    if not yaml_str or yaml_str == "[]":
        yaml_str = "[]"
    return f"```{CLAIMS_FENCE_LANG}\n{yaml_str}\n```"


def write_claims(body: str, claims: list[Claim]) -> str:
    """Insert/replace the ` ```claims ` block in ``body``, preserving all prose.

    If a block already exists it is replaced in place; otherwise the block is
    appended at the end. All other body content (the human-readable prose and
    sections) is preserved verbatim — this is load-bearing: the page stays an
    editable Wikipedia-like document and the claims block is the machine layer.

    Round-trip invariant: ``parse_claims(write_claims(body, claims)) == claims``.
    """
    block = _render_claims_block(claims)
    body = body or ""

    if _CLAIMS_BLOCK_RE.search(body):
        # Replace the FIRST block in place (preserving its position in the
        # prose), then strip any further stale ```claims fences so the page
        # ends with exactly one — a hand-edited / double-appended page must not
        # leave an orphan block behind. lambda avoids backreference
        # interpretation of the replacement string.
        replaced = _CLAIMS_BLOCK_RE.sub(lambda _m: block + "\n", body, count=1)
        # `count=1` above already consumed the first block; remove the rest.
        seen = {"first": False}

        def _strip_extra(_m: "re.Match[str]") -> str:
            if not seen["first"]:
                seen["first"] = True
                return _m.group(0)  # keep the one we just wrote
            return ""

        return _CLAIMS_BLOCK_RE.sub(_strip_extra, replaced)

    # Append, with a clean blank-line separator from existing prose.
    stripped = body.rstrip()
    if stripped:
        return f"{stripped}\n\n{block}\n"
    return f"{block}\n"


def strip_claims_block(body: str) -> str:
    """Return body with the ```claims fenced block removed (trailing ws trimmed)."""
    return _CLAIMS_BLOCK_RE.sub("", body or "").strip()
