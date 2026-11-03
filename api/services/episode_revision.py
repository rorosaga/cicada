"""A conversation Sleep already read, edited in place and queued again: read as a revision (G104, owner 2026-11-03).

Many sources re-stage an episode Sleep has consolidated: an edited note or meeting transcript, a chat whose window is
re-posted, a re-imported export (`episode_staging` edits in place with ``processed: false``). Read again from scratch,
each edit left the first read's claims open on spans that no longer locate, asked a conflict question when the same
source changed a value, and gave every name in unchanged lines a second chance at a page. Here the edit is a revision
of a conversation the record already holds:

* **The version last consolidated is git's.** The stager's edit-in-place record (``revised``, `episode_staging`, G95)
  names it: ``consolidated_hash`` is the ``content_hash`` of the last body Sleep or an agent consolidated, kept through
  later edits until Sleep reads the episode again (Sleep refreshes it when it retires one, :func:`mark_consolidated`).
  Without that record (a transcript, a writer that does not stage) it is the version committed with ``processed: true,
  processed_by: sleep``. No capture writer commits by default, so the bank's ``HEAD`` holds that version until the next
  Sleep commit; one ``git cat-file --batch`` reads every waiting episode's. With the capture log published (G132 51e),
  a capture commit can be newer: the episode's own history is walked, at most :data:`HISTORY_MAX` commits back. No git,
  no such version, or the same text: nothing to diff, a full read as before.
* **The diff is by line, whitespace ignored.** :func:`diff` matches the two bodies' lines on their words, so a
  re-wrapped or re-spaced line is unchanged. ``changed`` is text the new body has that the read one did not;
  ``removed`` is text the read one had that this one does not.
* **A no-op costs no engine call** (``noop``): only whitespace moved. The spans are re-anchored and the episode retired.
* **Stage 1 reads only what changed** (``windows``): each changed range with :data:`CONTEXT_LINES` lines after it and
  at least that many lines and :data:`CONTEXT_CHARS` characters before it, merged; past :data:`FULL_READ_SHARE` of the
  body the whole body is read. A pure removal reads nothing. Of what the
  model returns, a relationship or value located only in unchanged text, and a name said only there, are the first
  read's (:func:`keep_changed`): never written twice, never a second chance at promotion.
* **Spans are re-anchored, never fuzzily** (:func:`reanchor`): each span minted on the read version is located again
  in the matching lines of this one — exact, then whitespace, then case-insensitive (`evidence.locate`) — with the new
  hash. One that cannot be is the source's removal.
* **A claim only the removed text said is closed, never deleted** (:func:`settle`). In Stage 3 a new value from the
  same revision closes it (``superseded_by`` the new claim, no conflict question: the source corrected itself); with
  none, it is withdrawn by a born-closed ``retracts`` record whose evidence names the revision (its body hash). A claim
  another conversation also says, the person's own (``is_human``), an agent's write (``recorded_ts``), an event, or one
  with any span this module cannot place is never closed. A transcript (``capture_kind: transcript``) drops old turns
  by its session cap, never by revision: its removals close nothing.
* **A revision is the same conversation.** Its id, and so every "2+ conversations" count and every decay credit, is
  the one it always had; a later, different conversation saying something else is still an update or a conflict.

Read-only here except :func:`settle`'s and :func:`reanchor`'s in-memory claims, which the claim pipeline writes with
its own page writes, inside Sleep's write window. Never raises into the cycle: a failure is a full read, as before."""
from __future__ import annotations

import bisect
import difflib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import evidence, markdown_parser
from api.services.claims import Claim, Evidence, is_event, is_record

#: The episode dict key the cycle attaches a :class:`Revision` under.
KEY = "prior_read"
#: The stager's edit-in-place record (`episode_staging.REVISED_KEY`, G95) and its field naming the consolidated body.
REVISED_KEY = "revised"
CONSOLIDATED_KEY = "consolidated_hash"
#: Unchanged text Stage 1 sees around a change, for what a pronoun, "it" or "the second option" refers to: at least
#: this many lines on each side, and before it at least :data:`CONTEXT_CHARS` characters (whole lines).
CONTEXT_LINES = 2
CONTEXT_CHARS = 4000
#: Past this share of the body, the windows are the whole body (a rewrite; nothing to save by slicing).
FULL_READ_SHARE = 0.6
#: How far back an episode's own history is walked for the version Sleep read, when HEAD holds a newer capture.
HISTORY_MAX = 20
#: Told to the model before each window of a revision (the model sees the window, never the frontmatter).
REVISION_NOTE = ("[Revision: this conversation was edited after it was read. This excerpt is the part that changed, "
                 "with a few unchanged lines around it for context. Extract what the changed lines say.]\n\n")
#: The withdrawal record's words: the source said it, then stopped saying it.
WITHDRAW_REASON = "The conversation this came from was edited and no longer says it."
#: Who closes a claim on a revision: Cicada's own rule, no model's judgement.
AUTHOR = "cicada"

Range = tuple[int, int]


@dataclass
class Revision:
    episode_id: str
    prior: str
    body: str
    noop: bool
    changed: tuple[Range, ...]
    removed: tuple[Range, ...]
    windows: tuple[Range, ...]
    #: ``(i1, i2, j1, j2)`` per line block, as char offsets into ``prior`` and ``body``; ``equal`` blocks match line
    #: for line on their words.
    blocks: tuple[tuple[str, int, int, int, int], ...]
    #: Whether a removal may close a claim (never for a capped transcript).
    closes: bool = True
    override: str | None = None
    gaps: tuple = ()
    _hashes: dict = field(default_factory=dict, repr=False)

    @property
    def prior_hash(self) -> str:
        return self._hashes.setdefault("prior", evidence.body_hash(self.prior))

    @property
    def hash(self) -> str:
        return self._hashes.setdefault("body", evidence.body_hash(self.body))


def _norm(text: str) -> str:
    return " ".join(text.split())


def _starts(lines: list[str]) -> list[int]:
    out, pos = [], 0
    for line in lines:
        out.append(pos)
        pos += len(line)
    out.append(pos)
    return out


def diff(prior: str, body: str) -> tuple[tuple[Range, ...], tuple[Range, ...], tuple]:
    """``(changed ranges in body, removed ranges in prior, line blocks)``, lines matched on their words."""
    a, b = prior.splitlines(keepends=True), body.splitlines(keepends=True)
    sa, sb = _starts(a), _starts(b)
    matcher = difflib.SequenceMatcher(None, [_norm(x) for x in a], [_norm(x) for x in b], autojunk=False)
    changed: list[Range] = []
    removed: list[Range] = []
    blocks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        blocks.append((tag, sa[i1], sa[i2], sb[j1], sb[j2]))
        if tag in ("replace", "insert") and body[sb[j1]:sb[j2]].strip():
            changed.append((sb[j1], sb[j2]))
        if tag in ("replace", "delete") and prior[sa[i1]:sa[i2]].strip():
            removed.append((sa[i1], sa[i2]))
    return tuple(changed), tuple(removed), tuple(blocks)


def _windows(body: str, changed: tuple[Range, ...]) -> tuple[Range, ...]:
    if not changed:
        return ()
    starts = _starts(body.splitlines(keepends=True))

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    merged: list[list[int]] = []
    for s, e in changed:
        first = max(0, line_of(s) - CONTEXT_LINES)
        while first > 0 and s - starts[first] < CONTEXT_CHARS:
            first -= 1
        last = min(len(starts) - 1, line_of(max(s, e - 1)) + 1 + CONTEXT_LINES)
        lo, hi = starts[first], starts[last]
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    if sum(hi - lo for lo, hi in merged) > FULL_READ_SHARE * max(1, len(body)):
        return ((0, len(body)),)
    return tuple((lo, hi) for lo, hi in merged)


def build(episode: dict, prior: str) -> Revision | None:
    """A :class:`Revision` of ``episode`` (Sleep's dict) against the body Sleep last read, or ``None`` when there is
    nothing to diff (the same text)."""
    body = str(episode.get("content") or "")
    if prior == body:
        return None
    changed, removed, blocks = diff(prior, body)
    noop = not changed and not removed and _norm(prior) == _norm(body)
    if not changed and not removed and not noop:
        return None   # only line breaks moved inside words: read it whole, as before
    from api.services import authorship

    return Revision(
        episode_id=str(episode["id"]), prior=prior, body=body, noop=noop, changed=changed, removed=removed,
        windows=() if noop else _windows(body, changed), blocks=blocks,
        closes=str(episode.get("capture_kind") or "") != "transcript",
        override=authorship.of_episode(episode), gaps=tuple(episode.get("gaps") or ()))


# --------------------------------------------------------------------------- #
# the version Sleep read, from git
# --------------------------------------------------------------------------- #


def _read_by_sleep(fm: dict) -> bool:
    return fm.get("processed") is True and str(fm.get("processed_by") or "") == "sleep"


def consolidated_hash(fm: dict | None) -> str | None:
    """The ``content_hash`` the stager's ``revised`` record names as the body last consolidated, or ``None``."""
    record = (fm or {}).get(REVISED_KEY)
    value = record.get(CONSOLIDATED_KEY) if isinstance(record, dict) else None
    return str(value) if value else None


def _is_prior(fm: dict, wanted: str | None) -> bool:
    """The version to diff against: the one the ``revised`` record names, else (no record) the one Sleep read."""
    if wanted:
        return str(fm.get("content_hash") or "") == wanted and fm.get("processed") is True
    return _read_by_sleep(fm)


def mark_consolidated(fm: dict) -> None:
    """Sleep read this body: its ``revised`` record now names it (G95's field, refreshed in place). An episode never
    edited in place carries no record, and none is started here — the stager writes it on the first edit."""
    record = fm.get(REVISED_KEY)
    if isinstance(record, dict) and fm.get("content_hash"):
        fm[REVISED_KEY] = {**record, CONSOLIDATED_KEY: str(fm["content_hash"])}


def _blobs(memory_path: Path, specs: list[str]) -> list[bytes | None]:
    """One ``git cat-file --batch`` over ``<rev>:<path>`` specs; ``None`` for one git does not hold. A read."""
    if not specs:
        return []
    proc = subprocess.run(["git", "cat-file", "--batch"], cwd=str(memory_path), capture_output=True, timeout=60,
                          input="".join(f"{s}\n" for s in specs).encode("utf-8"))
    if proc.returncode != 0:
        return [None] * len(specs)
    out, pos, got = proc.stdout, 0, []
    for _ in specs:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        pos = nl + 1
        if len(header) < 3 or header[1] != b"blob":
            got.append(None)
            continue
        size = int(header[2])
        got.append(out[pos:pos + size])
        pos += size + 1
    return got


def _split(blob: bytes | None) -> tuple[dict, str] | None:
    if blob is None:
        return None
    try:
        text = blob.decode("utf-8")
        fm, _ = markdown_parser.header_of(text)
        split = markdown_parser.split_frontmatter(text)
    except Exception:  # noqa: BLE001 - an unreadable old version is no version
        return None
    if not isinstance(fm, dict) or split is None:
        return None
    return fm, split[1].strip()


def _from_history(memory_path: Path, rel: str, wanted: str | None) -> str | None:
    proc = subprocess.run(["git", "log", f"-n{HISTORY_MAX}", "--format=%H", "--end-of-options", "HEAD", "--", rel],
                          cwd=str(memory_path), capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        return None
    commits = proc.stdout.split()
    for blob in _blobs(memory_path, [f"{c}:{rel}" for c in commits]):
        got = _split(blob)
        if got is not None and _is_prior(got[0], wanted):
            return got[1]
    return None


def prior_bodies(memory_path: Path, episodes: list[dict]) -> dict[str, str]:
    """``{episode id: the body Sleep last read}`` for each waiting episode git holds a read version of."""
    memory_path = Path(memory_path)
    if not (memory_path / ".git").exists() or not episodes:
        return {}
    rels = [f"episodes/{Path(str(ep.get('filepath') or '')).name or str(ep['id']) + '.md'}" for ep in episodes]
    out: dict[str, str] = {}
    try:
        heads = _blobs(memory_path, [f"HEAD:{r}" for r in rels])
        for ep, rel, blob in zip(episodes, rels, heads):
            got = _split(blob)
            if got is None:
                continue
            fm, body = got
            wanted = consolidated_hash({REVISED_KEY: ep.get(REVISED_KEY)})
            if _is_prior(fm, wanted):
                out[str(ep["id"])] = body
            elif fm.get("processed") is False or wanted:
                older = _from_history(memory_path, rel, wanted)   # a capture commit is newer (G132 51e)
                if older is not None:
                    out[str(ep["id"])] = older
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning(f"Revisions: the versions Sleep read could not be loaded ({type(exc).__name__}); read whole")
        return {}
    return out


def attach(memory_path: Path, episodes: list[dict]) -> dict[str, Revision]:
    """Mark each waiting episode Sleep read before as a :class:`Revision` (``episode[KEY]``). Never raises."""
    try:
        priors = prior_bodies(memory_path, [ep for ep in episodes if ep.get("content")])
        revisions: dict[str, Revision] = {}
        for ep in episodes:
            prior = priors.get(str(ep["id"]))
            if prior is None:
                continue
            rev = build(ep, prior)
            if rev is not None:
                ep[KEY] = rev
                revisions[rev.episode_id] = rev
        if revisions:
            noop = sum(1 for r in revisions.values() if r.noop)
            logger.info(f"Revisions: {len(revisions)} conversation(s) read before were edited ({noop} only in "
                        "whitespace); reading what changed")
        return revisions
    except Exception as exc:  # noqa: BLE001 - a revision is an optimisation of a full read, never a failure
        logger.warning(f"Revisions skipped: {type(exc).__name__}")
        return {}


# --------------------------------------------------------------------------- #
# Stage 1: what the model is given, and what of its answer is new
# --------------------------------------------------------------------------- #


def _overlaps(s: int, e: int, ranges) -> bool:
    return any(s < hi and lo < e for lo, hi in ranges)


def keep_changed(rev: Revision, entities: list, relationships: list, values: list) -> tuple[list, list, list, int]:
    """What the revision says that the read version did not: a relationship or value with a span only in unchanged
    text is the first read's; one with no span (an unlocatable quote) is kept — provenance never blocks memory. A
    name is kept when a changed line names it or a kept relationship or value does. Returns the kept lists and how
    many items were left as the first read's."""
    def new(item: dict) -> bool:
        spans = [Evidence.from_dict(e) for e in item.get("evidence") or [] if isinstance(e, dict)]
        spans = [s for s in spans if s.is_span()]
        return not spans or any(_overlaps(s.start, s.end, rev.changed) for s in spans)

    rels = [r for r in relationships if new(r)]
    vals = [v for v in values if new(v)]
    said = " ".join(rev.body[lo:hi] for lo, hi in rev.changed).casefold()
    ends = {str(x).strip().casefold() for r in rels for x in (r.get("source"), r.get("target")) if x}
    ends |= {str(v.get("entity") or "").strip().casefold() for v in vals}

    def named(entity: dict) -> bool:
        names = [entity.get("name"), *(entity.get("aliases") or [])]
        names = [str(n).strip().casefold() for n in names if isinstance(n, str) and n.strip()]
        return any(n in ends or n in said for n in names)

    ents = [e for e in entities if isinstance(e, dict) and named(e)]
    left = (len(relationships) - len(rels)) + (len(values) - len(vals)) + (len(entities) - len(ents))
    return ents, rels, vals, left


# --------------------------------------------------------------------------- #
# Stage 3: re-anchor, then close what only the removed text said
# --------------------------------------------------------------------------- #


def _map_window(rev: Revision, start: int, end: int) -> Range | None:
    """Where ``prior[start:end]`` sits in ``body``: the matching lines of an unchanged block, the replacing lines of a
    changed one. ``None`` when the text was only deleted."""
    lo = hi = None
    for tag, i1, i2, j1, j2 in rev.blocks:
        if i2 <= start or i1 >= end or i1 == i2:
            continue
        if tag == "equal":
            # Equal blocks match line for line (on their words): the span's lines here are those lines there.
            sa = _starts(rev.prior[i1:i2].splitlines(keepends=True))
            sb = _starts(rev.body[j1:j2].splitlines(keepends=True))
            first = bisect.bisect_right(sa, max(start, i1) - i1) - 1
            last = bisect.bisect_right(sa, min(end, i2) - 1 - i1) - 1
            w = (j1 + sb[min(first, len(sb) - 1)], j1 + sb[min(last + 1, len(sb) - 1)])
        elif tag == "replace":
            w = (j1, j2)
        else:
            continue
        lo = w[0] if lo is None else min(lo, w[0])
        hi = w[1] if hi is None else max(hi, w[1])
    return None if lo is None or hi <= lo else (lo, hi)


def _on_prior(rev: Revision, ev: Evidence) -> bool:
    """Offsets minted on the version Sleep read (or on a prefix of it, a conversation that grew)."""
    if not ev.is_span() or ev.end > len(rev.prior):
        return False
    return ev.hash == rev.prior_hash or evidence.span_status(rev.prior, end=ev.end, hash=ev.hash) == evidence.SPAN_GROWN


def _relocate(rev: Revision, ev: Evidence) -> Evidence | None:
    window = _map_window(rev, ev.start, ev.end)
    if window is None:
        return None
    lo, hi = window
    hit = evidence.locate(rev.body[lo:hi], rev.prior[ev.start:ev.end])
    if hit is None:
        return None
    start, end = lo + hit[0], lo + hit[1]
    kind = evidence.kind_for(rev.episode_id, rev.body, start, rev.override, rev.gaps)
    if kind == evidence.GAP_KIND or evidence.touches_gap(start, end, rev.gaps):
        return None
    return Evidence(episode=rev.episode_id, start=start, end=end, kind=kind, hash=rev.hash)


@dataclass
class Plan:
    #: claim id -> the revised episode only whose removed text said it.
    revised_out: dict[str, str] = field(default_factory=dict)
    reanchored: int = 0
    stale: int = 0


def _closable(c: Claim) -> bool:
    from api.services.claim_reconciler import is_human

    return (c.valid_to is None and not is_human(c) and not c.recorded_ts and not is_event(c) and not is_record(c))


def reanchor(claims_by_subject: dict[str, list[Claim]], revisions: dict[str, Revision]) -> Plan:
    """Move every span into a revised episode onto its new body where the cited words are still there; mark each open
    claim only removed text said (:class:`Plan`). Mutates the claims in place."""
    plan = Plan()
    if not revisions:
        return plan
    for claims in claims_by_subject.values():
        for c in claims:
            if not any(ev.episode in revisions for ev in c.evidence):
                continue
            gone: set[str] = set()
            kept: set[str] = set()
            unplaced = False
            new_evidence: list[Evidence] = []
            for ev in c.evidence:
                rev = revisions.get(ev.episode)
                if rev is None:
                    new_evidence.append(ev)
                    continue
                if ev.is_span() and ev.hash == rev.hash:
                    kept.add(ev.episode)          # already on this body
                    new_evidence.append(ev)
                    continue
                if not _on_prior(rev, ev):
                    unplaced = True               # a reasoning entry, or a span on some older body: cannot be placed
                    new_evidence.append(ev)
                    continue
                moved = _relocate(rev, ev)
                if moved is None:
                    gone.add(ev.episode)
                    plan.stale += 1
                    new_evidence.append(ev)   # history: the span the source no longer holds reads `stale`
                else:
                    kept.add(ev.episode)
                    plan.reanchored += 1
                    if moved not in new_evidence:
                        new_evidence.append(moved)
            c.evidence = new_evidence
            only = gone - kept
            if len(only) != 1 or unplaced or kept or not _closable(c):
                continue
            (ep,) = only
            if not revisions[ep].closes:
                continue
            others = {e.episode for e in c.evidence if e.episode != ep} | {s for s in c.source_episodes if s != ep}
            if not others:
                plan.revised_out[c.id] = ep
    return plan


def settle(reconciled: dict[str, list[Claim]], plan: Plan, revisions: dict[str, Revision], today: str,
           audit: list[dict]) -> int:
    """After Stage 3, each marked claim still open is withdrawn by a ``retracts`` record that names the revision —
    unless Stage 3 gave it a reason to stand:

    * another conversation now supports it (read in the same batch: its evidence or ``source_episodes`` cite an
      episode other than the revised one) — no longer the removed text's word alone;
    * the revision said it again (Stage 3's ``revision_restated``, whatever the evidence kind: an unlocatable quote
      is still a restatement — provenance never blocks memory). Its old span gives way to a new one when it has one.

    One the revision's new value closed stays closed. Returns how many were withdrawn."""
    if not plan.revised_out:
        return 0
    from api.services.agentic_write import _withdrawal_record

    restated = {a.get("kept") for a in audit if a.get("action") == "revision_restated"}
    withdrawn = 0
    for slot in reconciled.values():
        records: list[Claim] = []
        for c in slot:
            ep = plan.revised_out.get(c.id)
            if ep is None or c.valid_to is not None:
                continue
            rev = revisions[ep]
            if any(e.episode != ep for e in c.evidence) or any(s != ep for s in c.source_episodes or []):
                audit.append({"action": "revision_kept", "kept": c.id, "why": "another_conversation"})
                continue
            if c.id in restated:
                if any(e.episode == ep and e.is_span() and e.hash == rev.hash for e in c.evidence):
                    # A reworded or moved line, located: the old span gives way to the new one.
                    c.evidence = [e for e in c.evidence
                                  if not (e.episode == ep and e.hash != rev.hash and e.is_span())]
                audit.append({"action": "revision_kept", "kept": c.id, "why": "restated"})
                continue
            record = _withdrawal_record(c, [*slot, *records], reason=WITHDRAW_REASON, author=AUTHOR,
                                        origin=c.origin, session_id=c.session_id,
                                        spans=[evidence.reasoning(ep, hash=rev.hash)], day=today)
            c.valid_to = today
            c.superseded_by = record.id
            records.append(record)
            audit.append({"action": "revision_withdrew", "closed": c.id, "by": record.id})
            withdrawn += 1
        slot.extend(records)
    return withdrawn
