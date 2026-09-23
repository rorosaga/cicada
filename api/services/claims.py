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
# The libyaml scanner, the `markdown_parser._SAFE_LOADER` precedent: same
# SafeConstructor, same output as `safe_load`, only the scanner differs. G141
# PJ-1's bench (R-PJB9) measured a 4-claim page at ~7 ms in pure Python, so a
# project read that opens ~200 pages spent ~1.5 s in the scanner alone.
_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

_CLAIMS_BLOCK_RE = re.compile(
    r"^```claims[ \t]*\r?\n(?P<payload>.*?)^```[ \t]*\r?$\r?\n?",
    re.DOTALL | re.MULTILINE,
)

# G118 slice 1 — the evidence kinds, six since G140. `user`/`assistant` are
# spans into a conversation episode, attributed by the turn marker at or before
# the span (R4) or by the episode's declared `evidence_kind` (R-LS7); `speaker`
# (G134, R-N2 / R-LS7) is a meeting utterance by someone other than the owner,
# marked `speaker:<label>:`; `media` (G140 Q-R9) is what a video said — a watch
# record's cited excerpt, a timed `video [m:ss]:` line; `page` is a span into an
# entity page's prose (a saved link's stored description — link recon);
# `reasoning` is the contributor's own inference and carries no offsets. The set
# is closed on purpose: a viewer renders each kind differently, and G100's
# derived-span class, if it ever ships, will be a seventh value rather than a
# flag on one of these. Append-only: an older reader degrades an unknown kind to
# `reasoning`.
EVIDENCE_KINDS = ("user", "assistant", "page", "reasoning", "speaker", "media")


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
    # G140 Q-R6 (R3 P8) — a STATED end: the date the fact itself says it stops
    # being true ("exams this weekend" → the Sunday; "until Friday"). NOT
    # `valid_to`, which thirteen readers take to mean CLOSED — a future date
    # there would hide the fact the day it was written. `claim_expiry` copies
    # it into `valid_to` once it has passed. Omitted from the YAML when unset
    # (G118 R7's reason: re-rendering a page must never diff every legacy
    # claim for a field it lacks).
    expected_end: str | None = None
    # G141 §4.1 — event fields, omitted from the YAML when empty (R7's reason):
    # `status` is the state AS OF `valid_from` (a new state is a new claim,
    # R-PJ4); `target` a milestone's planned date (expiry never reads it);
    # `participants` `[{role, surface?, entity?, url?}]` over a closed role set;
    # `date_basis` how `valid_from` was decided (`when.resolve`).
    status: str | None = None
    target: str | None = None
    participants: list[dict] = field(default_factory=list)
    date_basis: str | None = None

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
        # G140 Q-R6: same rule for a stated end — absent unless one was stated.
        if data.get("expected_end") is None:
            data.pop("expected_end", None)
        # G141 §4.1: the four event fields, absent on every non-event claim.
        for key in ("status", "target", "date_basis"):
            if data.get(key) is None:
                data.pop(key, None)
        # Cleaned on the way OUT too, so a writer that built the list by hand
        # can never put an unknown role or key into the fence.
        data["participants"] = clean_participants(data.get("participants"))
        if not data["participants"]:
            data.pop("participants", None)
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
            expected_end=_opt_str(data.get("expected_end")),
            status=_opt_str(data.get("status")),
            target=_opt_str(data.get("target")),
            participants=clean_participants(data.get("participants")),
            date_basis=_opt_str(data.get("date_basis")),
        )


# G140 Q-R5 — the predicate of a withdrawal record. `cicada_retract_claim`
# closes the withdrawn claim and appends one of these beside it: the agent's
# reason as `text`, the withdrawn claim's id as `object`. It lives here, not in
# `agentic_write`, because every READER of a claims fence must drop it — and a
# reader should not import the write path to learn what to skip.
RETRACT_PREDICATE = "retracts"


def is_record(claim: Claim) -> bool:
    """Is ``claim`` a withdrawal record rather than a belief? (G140 Q-R5)

    A record is bookkeeping ABOUT a claim, never a belief of its own. Served
    as one, it read as a belief named with the agent's reason: a ``/search``
    claim hit under "Beliefs", and a struck-through "No longer current" row in
    an episode's citations (final review). Every surface that lists claims —
    MCP history, the claim endpoints, the search index, episode citations —
    filters through this one test, so a new surface has one thing to call.
    """
    return claim.predicate == RETRACT_PREDICATE


# G141 R-PJ1 — happenings and milestones are claims: they inherit observer,
# trust, G118 spans, sessions, supersede and withdrawal, the FTS index and the
# remote scopes instead of regrowing them. `status` is the state AS OF
# `valid_from`; a new state is a new claim (R-PJ4). Only `progress.py` writes
# these predicates (§5.1): `agentic_write.write_claim` refuses them and
# `claim_pipeline` relabels a stray Stage-1 label.
HAPPENED = "happened"
MILESTONE = "milestone"
EVENT_PREDICATES = frozenset({HAPPENED, MILESTONE})
EVENT_STATUSES = {HAPPENED: ("ongoing", "done", "dropped"), MILESTONE: ("planned", "done", "missed", "dropped")}
PARTICIPANT_ROLES = ("owner", "from", "with", "for", "about", "used", "document", "project")
PARTICIPANT_KEYS = ("role", "surface", "entity", "url")
DATE_BASES = ("stated", "turn", "episode", "person", "written")


def is_event(claim) -> bool:
    """The one test the history readers call (R-PJ3), like `is_record`. An
    event is NOT a record: it stays in FTS and in citations, where it reads as
    a dated happening — never as a belief that is "no longer current"."""
    return getattr(claim, "predicate", "") in EVENT_PREDICATES


PERSONS_WORDS_ORIGINS = frozenset({"companion_app", "clarification"})


def is_persons_words(claim) -> bool:
    """R-PJ23's one test: is this claim's `text` the person's own sentence?
    A Log entry (`companion_app`) and a follow-up answered in free text
    (`clarification`) both are, so a remote reader without `sources` is shown
    neither (G141 final review — the inbox note path had leaked). Over-hiding
    a "Still going" that restated an extractor's sentence is the safe side."""
    return (getattr(claim, "origin", None) or "") in PERSONS_WORDS_ORIGINS


def event_cardinality(predicate: str) -> str | None:
    """R-PJ5: `multi` for the event predicates, in CODE — an existing bank's
    `_predicates.yaml` is stale and `build_cardinality_fn` reads only it. The
    one-head-per-slug rule lives in `claim_reconciler.reconcile_events`."""
    return "multi" if (predicate or "").strip().lower() in EVENT_PREDICATES else None


def clean_participants(raw) -> list[dict]:
    """Forgiving, like `Evidence.from_dict`: an entry with an unknown role or no
    role is dropped, unknown keys are dropped, empty values are omitted — a
    hand-edited fence must never make its claim unparseable."""
    out: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict) or item.get("role") not in PARTICIPANT_ROLES:
            continue
        out.append({k: str(item[k]) for k in PARTICIPANT_KEYS if item.get(k) not in (None, "")})
    return out


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
        loaded = yaml.load(payload, Loader=_SAFE_LOADER)  # noqa: S506 — a SAFE loader
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
