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

# G118 slice 1 — the four evidence kinds. `user`/`assistant` are spans into a
# conversation episode, attributed by the turn marker at or before the span
# (R4); `page` is a span into an entity page's prose (a saved link's stored
# description — link recon); `reasoning` is the contributor's own inference
# and carries no offsets. The set is closed on purpose: a viewer renders each
# kind differently, and G100's derived-span class, if it ever ships, will be
# a fifth value rather than a flag on one of these.
EVIDENCE_KINDS = ("user", "assistant", "page", "reasoning")


@dataclass
class Evidence:
    """WHERE a claim came from — offsets into stored text, never a copy (G118).

    ``episode`` is a source-document id (R3): ``ep_*`` resolves to
    ``episodes/<id>.md``; anything else to ``entities/<id>.md`` (a ``page``
    span cites the media entity that holds the description). ``start``/``end``
    are character offsets into that document's evidence text — the body as
    ``markdown_parser.parse`` returns it, with the ```claims fence stripped
    for an entity page (R1) — and ``hash`` is ``sha256[:12]`` of that text
    (R2) so a rewritten source reads as ``stale`` instead of mis-highlighting.
    A ``reasoning`` entry has ``start == end == -1``: the contributor cited
    itself, and nothing in the bank says it in so many words.
    """

    episode: str = ""
    start: int = -1
    end: int = -1
    kind: str = "reasoning"
    hash: str = ""

    def is_span(self) -> bool:
        return self.kind != "reasoning" and 0 <= self.start < self.end

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "Evidence":
        """Forgiving on purpose: provenance must never make a claim unparseable
        (a bad entry degrades to ``reasoning``; strict mode is for the block,
        not for one evidence row)."""
        data = dict(data or {}) if isinstance(data, dict) else {}
        kind = str(data.get("kind") or "reasoning")
        try:
            start = int(data.get("start", -1))
            end = int(data.get("end", -1))
        except (TypeError, ValueError):
            start, end = -1, -1
        if kind not in EVIDENCE_KINDS or kind == "reasoning" or start < 0 or end <= start:
            kind, start, end = "reasoning", -1, -1
        return cls(
            episode=str(data.get("episode") or ""),
            start=start,
            end=end,
            kind=kind,
            hash=str(data.get("hash") or ""),
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
    # PR #20 review fix: the MCP session that wrote this claim (agentic_write's
    # SessionIdentity.session_id), stamped even when `source_episodes` is empty
    # — a direct `cicada_write_claim` against an EXISTING entity never touches
    # that entity's frontmatter `source_episodes`, so without this the write's
    # conversation is undiscoverable and the entity silently drops off that
    # conversation's `GET /conversations` row. `session_stats._group` reads it
    # as a fallback attribution path alongside `source_episodes`.
    #
    # `session_id` stays the FIRST-WRITER scalar (back-compat: every reader
    # written before the round-2 fix below only ever knew this field).
    session_id: str | None = None
    # PR #20 round-2 review fix: when a LATER conversation restates the same
    # fact, `claim_reconciler._reinforce` folds the incoming claim into this
    # one instead of opening a second claim — a scalar `session_id` can only
    # ever remember the first writer, so the later conversation's provenance
    # was silently dropped. `session_ids` is the additive, deduped list of
    # EVERY session that has written or reinforced this claim (first writer
    # included); `session_stats._group` reads this list, falling back to the
    # scalar `session_id` for claims written before this field existed.
    session_ids: list[str] = field(default_factory=list)
    # G85 §2 / Wave-1 1.1: the decay watermark. Decay must be charged exactly
    # once per elapsed interval, not re-charged from `recorded_at`/`valid_from`
    # on every Sleep run. `_decay_claims` measures `days_since` from
    # `max(recorded_at or valid_from, decayed_through)` and stamps this to
    # `today` every time it evaluates an unreferenced subject's claim — the
    # claim-engine mirror of the entity engine's `decayed_through` frontmatter.
    decayed_through: str | None = None
    # G118 slice 1 — evidence spans. Empty on every claim written before the
    # field existed (no backfill, R6); at least one entry on every claim
    # written since, `reasoning` when the writer had no source text.
    evidence: list[Evidence] = field(default_factory=list)

    def all_session_ids(self) -> list[str]:
        """Every session that has written or reinforced this claim, deduped,
        order-preserving. Prefers ``session_ids``; a claim written before that
        field existed falls back to its scalar ``session_id`` alone.
        """
        out: list[str] = []
        seen: set[str] = set()
        for sid in [*(self.session_ids or []), self.session_id]:
            sid = (sid or "").strip()
            if sid and sid not in seen:
                seen.add(sid)
                out.append(sid)
        return out

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # R7: omit an empty evidence list so `write_claims` re-rendering a page
        # never diffs ~2,300 legacy claims for a field they do not have.
        if not data.get("evidence"):
            data.pop("evidence", None)
        return data

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
            session_id=_opt_str(data.get("session_id")),
            session_ids=[str(s) for s in (data.get("session_ids") or []) if str(s).strip()],
            decayed_through=_opt_str(data.get("decayed_through")),
            evidence=[
                Evidence.from_dict(e) for e in (data.get("evidence") or []) if isinstance(e, dict)
            ],
        )


def _opt_str(value: Any) -> str | None:
    """Normalize an optional scalar to ``str`` or ``None`` (YAML may parse dates)."""
    if value is None:
        return None
    return str(value)


class MalformedClaimsBlockError(ValueError):
    """A ```claims block exists but cannot be parsed.

    Raised only by ``parse_claims(..., strict=True)``. Read-modify-write
    callers MUST use strict mode: with the lenient default, a corrupt block
    reads as "no claims" and the subsequent ``write_claims`` replaces the
    block wholesale — silently destroying every claim trapped in the
    unparseable YAML.
    """


def parse_claims(body: str, *, strict: bool = False) -> list[Claim]:
    """Extract the claims from the ` ```claims ` block in ``body``.

    Returns ``[]`` when no block is present (legacy page). When the block is
    present but malformed: with ``strict=False`` (default, for read-only
    paths like the index rebuild) it is logged and degrades to ``[]``; with
    ``strict=True`` (required for every read-modify-write path) it raises
    :class:`MalformedClaimsBlockError` so the caller aborts instead of
    overwriting claims it could not read.
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
        if strict:
            raise MalformedClaimsBlockError(f"YAML error in ```claims block: {exc}") from exc
        logger.warning(f"malformed ```claims block (YAML error), ignoring: {exc}")
        return []
    if loaded is None:
        return []
    if not isinstance(loaded, list):
        if strict:
            raise MalformedClaimsBlockError(
                f"```claims block payload is not a YAML list (got {type(loaded).__name__})"
            )
        logger.warning(
            "```claims block payload is not a YAML list "
            f"(got {type(loaded).__name__}), ignoring"
        )
        return []
    claims: list[Claim] = []
    for item in loaded:
        if not isinstance(item, dict):
            if strict:
                raise MalformedClaimsBlockError(
                    f"```claims block entry is not a mapping (got {type(item).__name__})"
                )
            logger.warning("skipping non-mapping entry in ```claims block")
            continue
        try:
            claims.append(Claim.from_dict(item))
        except (TypeError, ValueError) as exc:
            # A field that fails conversion (e.g. a non-numeric `confidence`)
            # is just as malformed as a non-mapping entry: in strict mode a
            # read-modify-write caller must abort rather than have
            # `write_claims` silently drop this entry when it re-renders the
            # (now truncated) list it read.
            if strict:
                raise MalformedClaimsBlockError(
                    f"```claims block entry could not be parsed: {exc}"
                ) from exc
            logger.warning(f"skipping unparseable entry in ```claims block: {exc}")
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
