"""An edited conversation's corrected date meets the claim it corrects under another wording (G104, 2026-11-25).

A claim the first read wrote from one line but dated from another keeps its span on the unchanged line, so the span
test never marks it (`episode_revision.reanchor`); and when the re-read words the same relationship under another
predicate ("is moving to", then "moves to") it is another slot, so the same-slot replacement
(`episode_revision.redated`, ``claim_reconciler._place_claim``'s ``redated``) never meets it. The old date stays current
beside the new one.

Three designs that decided something about the OLD claim from the text were dropped (`capture-and-sleep.md`, "A stale
date beside the corrected one"). This step decides nothing from the text. It acts only where the revision's own re-read
claim meets the old one, and only on a reading:

* **A pair** (:func:`candidates`, before Stage 2, pages read only): an open claim on a page that this one edited
  conversation alone says (`episode_revision._closable`; not a value, a number, an event, a record, the person's own or
  an agent's), and a claim of the same revision's re-read with the same subject, the same object, the same context and
  speaker, ANOTHER predicate, and a start or end the old one does not carry that the changed lines say
  (`episode_revision.says_day`, the test `redated` already uses for the new claim). Predicates are never compared by
  spelling or similarity.
* **Two readings** (:func:`read`): Sleep's small judge, then the cycle's main model on what the first called the same,
  are asked whether the two word the SAME relationship (the same move, the same job) or two different ones (a visit
  beside a move). Only "same" from both counts; a "different", an unreadable answer or a failed call leaves the pair as
  it was. One call per reader per revision with pairs (at most :data:`MAX_PAIRS` pairs a revision,
  :data:`MAX_REVISIONS` revisions a batch); no call when there is no pair. Made before Stage 2 opens the write window,
  metered under :data:`STAGE`.
* **The replacement** (:func:`apply`, after Stage 3 and ``episode_revision.settle``): the re-read's claim, as Stage 3
  left it, takes the old one's place the way the same-slot replacement does (``claim_reconciler._close``: the old claim
  closed and ``superseded_by`` the new, the new ``supersedes`` it, audit ``revised``), re-checked then: the old claim
  still open and still this conversation's alone (a conversation read the same night that also says it keeps it open),
  the new claim open on the same page, not closed, not merged into a closed claim, not superseding anything else, citing
  this conversation and carrying the judged day. One new claim replaces at most one old claim (it then supersedes one). Nothing is cleared,
  re-dated or written that the re-read did not write.

**The worst a wrong reading costs** (both readers always "same"): one claim of this conversation is superseded by
another claim of this conversation about the same two things, carrying a day the conversation now states: a move closed
beside a visit to the same city that the edit put in. Never another object, another subject, another conversation's
fact, the person's own claim, an agent's, an event, a record, a value, a number or a capped transcript.

**Held claims** (a name with no page yet, `pending_store`) are left exactly as before: only page claims are paired.
No word list of any language is used here.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import episode_revision as er
from api.services.claims import Claim, is_event, is_record, is_value_claim

#: The label every call here is metered under (`sleep_spend.LINE_STAGES`).
STAGE = "revision_pair"
#: Pairs one revision's reading carries (past it the rest stay as they are), and revisions read per batch.
MAX_PAIRS = 8
MAX_REVISIONS = 12
#: What a reading is shown: the edit, the conversation as it now stands, and each fact's own words, capped.
MAX_EDIT_CHARS = 3000
MAX_BODY_CHARS = 6000
MAX_WORDS_CHARS = 240
#: The audit's reason for a replacement made here (an enum: the ledger never holds words).
WHY = "edited_same_relationship"

PROMPT = """[Edited conversation: same relationship?] A conversation was edited after facts were recorded from it. \
Each PAIR below is two facts about the same two things, both recorded from that one conversation: EARLIER was recorded \
from it before the edit; NOW was read from it as it now stands, and carries a date the edited lines state. Each fact \
shows the words it was recorded from.

For each pair, answer "same" when EARLIER and NOW state the SAME relationship between the two things (the same move, \
the same job, the same trip), worded or dated differently, so that NOW replaces EARLIER. Answer "different" when they \
are two relationships that can both hold (a visit beside a move, the start of one thing beside the end of another), \
or when you cannot tell.

WHAT THE EDIT TOOK OUT:
{removed}

WHAT THE EDIT PUT IN:
{added}

THE CONVERSATION AS IT NOW STANDS:
{body}

PAIRS:
{pairs}

Reply with JSON only, one answer per pair: {{"pairs": [{{"pair": "<pair id>", "answer": "same" or "different"}}]}}"""


@dataclass(frozen=True)
class Verdict:
    """A pair both readers called the same relationship: the old claim by id, the re-read's claim by what it says
    (its id is minted again by Stage 3's projection, so it is matched on its content, never guessed)."""

    episode: str
    old_id: str
    subject: str
    context: str
    observer: str
    predicate: str
    object: str
    valid_from: str
    expected_end: str


@dataclass
class Pair:
    key: str
    rev: er.Revision
    old: Claim
    new: Claim
    days: tuple[str, ...]


@dataclass
class Reading:
    verdicts: list[Verdict] = field(default_factory=list)
    pairs: int = 0
    calls: int = 0
    first_same: int = 0
    failed: int = 0
    capped: int = 0


def _day(value) -> str:
    return str(value or "")[:10]


def _support(c: Claim) -> set[str]:
    return {e.episode for e in c.evidence} | set(c.source_episodes or [])


def _pairable_old(c: Claim, ep: str) -> bool:
    from api.services import phone_numbers

    return (er._closable(c) and not c.superseded_by and not is_value_claim(c)  # noqa: SLF001 - the one rule
            and not phone_numbers.is_number_claim(c) and _support(c) == {ep})


def _new_days(n: Claim, rev: er.Revision) -> tuple[str, ...]:
    """The days the re-read's claim carries that the changed lines say (start, end)."""
    text = er._changed_text(rev)  # noqa: SLF001 - the changed lines, one definition
    return tuple(d for d in (_day(n.valid_from), _day(n.expected_end)) if d and er.says_day(text, d))


def _differs(o: Claim, n: Claim, days: tuple[str, ...]) -> bool:
    """A start or end of ``n`` the changed lines say, which ``o`` does not carry in that place."""
    return any((d == _day(n.valid_from) and d != _day(o.valid_from))
               or (d == _day(n.expected_end) and d != _day(o.expected_end)) for d in days)


def _same_things(o: Claim, n: Claim) -> bool:
    from api.services.claim_reconciler import same_object, slot_observer

    return (o.subject == n.subject and same_object(o, n) and o.context == n.context
            and slot_observer(o) == slot_observer(n) and o.predicate != n.predicate)


def meets(o: Claim, n: Claim, rev: er.Revision) -> bool:
    """Is ``o`` (on a page) the pair of ``n`` (a claim of ``rev``'s re-read)? See the module: ``o`` open and this one
    conversation's alone, the same things under another predicate, and a day of ``n`` the changed lines say that ``o``
    does not carry. The one test :func:`candidates` and the reconciler's edited-back rule share."""
    days = _new_days(n, rev)
    return bool(days) and _pairable_old(o, rev.episode_id) and _same_things(o, n) and _differs(o, n, days)


def _resolver(memory_path: Path, ep: str, settings) -> Callable[[str], str]:
    """Names to page ids before Stage 2: a name or alias of exactly one page the first read of ``ep`` produced, else
    the id Stage 1's projection would give it. Only a candidate filter: :func:`apply` matches what Stage 3 holds."""
    from api.services import bank_index, owner_identity
    from api.services.claim_pipeline import subject_resolver

    table: dict[str, set[str]] = {}
    for entry in bank_index.files(memory_path, "entities"):
        fm = entry.frontmatter or {}
        if ep not in (fm.get("source_episodes") or []):
            continue
        for name in (fm.get("name"), *(fm.get("aliases") or [])):
            if isinstance(name, str) and name.strip():
                table.setdefault(name.strip().lower(), set()).add(Path(entry.path).stem)
    try:
        owner = owner_identity.owner_page_id(None, memory_path, settings)
    except Exception:  # noqa: BLE001 - no owner page: the owner's claims are not paired
        owner = None
    return subject_resolver({k: next(iter(v)) for k, v in table.items() if len(v) == 1}, owner)


def candidates(memory_path: Path, revisions: dict[str, er.Revision], extracted: list[dict],
               settings=None) -> list[Pair]:
    """The pairs of this batch's revisions (see the module). Pure reads; pages only."""
    from api.services.claim_pipeline import _load_existing_claims_by_subject
    from api.services.entity_extractor import entities_to_claims

    memory_path = Path(memory_path)
    news: list[tuple[er.Revision, Claim, tuple[str, ...]]] = []
    for item in extracted:
        ep = str(item.get("episode_id") or "")
        rev = revisions.get(ep)
        if rev is None or not rev.closes or not rev.changed or rev.book or not item.get("relationships"):
            continue
        only_rels = {**item, "entities": [], "values": []}
        for n in entities_to_claims([only_rels], memory_path, resolve_id=_resolver(memory_path, ep, settings)):
            if is_event(n) or is_record(n) or n.valid_to is not None or set(n.source_episodes or []) != {ep}:
                continue
            days = _new_days(n, rev)
            if days:
                news.append((rev, n, days))
    if not news:
        return []
    existing = _load_existing_claims_by_subject(memory_path)
    out: list[Pair] = []
    per_rev: dict[str, int] = {}
    for rev, n, days in news:
        for o in existing.get(n.subject, []):
            if not meets(o, n, rev):
                continue
            count = per_rev.get(rev.episode_id, 0)
            per_rev[rev.episode_id] = count + 1
            if count < MAX_PAIRS:
                out.append(Pair("", rev, o, n, days))
    for ep in per_rev:
        for i, p in enumerate((p for p in out if p.rev.episode_id == ep), 1):
            p.key = f"p{i}"
    return out


def _words(c: Claim, rev: er.Revision) -> str:
    quotes = []
    for e in c.evidence:
        if e.episode != rev.episode_id or not e.is_span():
            continue
        text = rev.body if e.hash == rev.hash else rev.prior if e.hash == rev.prior_hash else ""
        if e.end <= len(text):
            quotes.append(" ".join(text[e.start:e.end].split()))
    return " / ".join(q for q in quotes if q)[:MAX_WORDS_CHARS]


def _fact(c: Claim, rev: er.Revision) -> str:
    dates = [f"{label} {d}" for label, d in (("from", _day(c.valid_from)), ("until", _day(c.expected_end))) if d]
    words = _words(c, rev)
    return (c.text or f"{c.subject} {c.predicate} {c.object}") + (f" ({'; '.join(dates)})" if dates else "") + \
        (f' — recorded from: "{words}"' if words else "")


def prompt(rev: er.Revision, pairs: list[Pair]) -> str:
    removed = "\n".join(rev.prior[lo:hi] for lo, hi in rev.removed)[:MAX_EDIT_CHARS] or "(nothing)"
    added = er._changed_text(rev)[:MAX_EDIT_CHARS] or "(nothing)"  # noqa: SLF001
    body = rev.body if len(rev.body) <= MAX_BODY_CHARS else rev.body[:MAX_BODY_CHARS] + "\n[...]"
    lines = [f"{p.key}\n  EARLIER: {_fact(p.old, rev)}\n  NOW: {_fact(p.new, rev)}" for p in pairs]
    return PROMPT.format(removed=removed, added=added, body=body, pairs="\n".join(lines))


def same_keys(reply) -> set[str]:
    """The pair ids a reply calls the same relationship: exactly the answer ``"same"``; anything else is not."""
    rows = reply.get("pairs") if isinstance(reply, dict) else None
    out: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if (isinstance(row, dict) and isinstance(row.get("pair"), str) and isinstance(row.get("answer"), str)
                and row["answer"].strip().lower() == "same"):
            out.add(row["pair"].strip())
    return out


def _verdict(p: Pair) -> Verdict:
    from api.services.claim_reconciler import _norm_object, slot_observer

    n = p.new
    return Verdict(episode=p.rev.episode_id, old_id=p.old.id, subject=n.subject, context=n.context,
                   observer=slot_observer(n), predicate=n.predicate, object=_norm_object(n.object),
                   valid_from=_day(n.valid_from), expected_end=_day(n.expected_end))


def read(memory_path: Path, revisions: dict[str, er.Revision], extracted: list[dict],
         small: Callable[[str], dict] | None, main: Callable[[str], dict] | None, *, settings=None,
         cancelled: Callable[[], bool] | None = None) -> Reading:
    """Both readings for each revision with pairs; the pairs both call the same are returned as verdicts. A missing
    reader, no pair, a failed or unreadable answer: no verdict. Never raises."""
    out = Reading()
    if small is None or main is None or not revisions:
        return out
    try:
        pairs = candidates(Path(memory_path), revisions, extracted, settings)
    except Exception as exc:  # noqa: BLE001 - a miss is no reading
        logger.warning(f"Revision pairs: candidates unavailable ({type(exc).__name__})")
        return out
    by_ep: dict[str, list[Pair]] = {}
    for p in pairs:
        by_ep.setdefault(p.rev.episode_id, []).append(p)
    for n_rev, (ep, group) in enumerate(by_ep.items()):
        if n_rev >= MAX_REVISIONS:
            out.capped += len(group)
            continue
        if cancelled is not None and cancelled():
            break
        out.pairs += len(group)
        rev = group[0].rev
        try:
            out.calls += 1
            first = same_keys(small(prompt(rev, group)))
            chosen = [p for p in group if p.key in first]
            out.first_same += len(chosen)
            if not chosen:
                continue
            out.calls += 1
            second = same_keys(main(prompt(rev, chosen)))
        except Exception as exc:  # noqa: BLE001 - a failed call settles nothing
            out.failed += 1
            logger.info(f"Revision pairs: a reading failed ({type(exc).__name__}); its claims stay")
            continue
        out.verdicts.extend(_verdict(p) for p in chosen if p.key in second)
    if out.calls:
        logger.info(f"Revision pairs: {out.pairs} pair(s) in {len(by_ep)} revision(s), {out.calls} call(s), "
                    f"{out.first_same} same at the first reading, {len(out.verdicts)} at both, {out.failed} failed")
    return out


def _carries(c: Claim, v: Verdict) -> bool:
    from api.services.claim_reconciler import _norm_object, open_, slot_observer

    return (open_(c) and not c.superseded_by and not c.supersedes and not is_record(c) and not is_event(c)
            and c.subject == v.subject and c.predicate == v.predicate and c.context == v.context
            and slot_observer(c) == v.observer and _norm_object(c.object) == v.object
            and _day(c.valid_from) == v.valid_from and _day(c.expected_end) == v.expected_end
            and v.episode in (c.source_episodes or []))


def apply(reconciled: dict[str, list[Claim]], verdicts: list[Verdict], revisions: dict[str, er.Revision],
          audit: list[dict]) -> dict[str, str]:
    """After Stage 3 (and ``episode_revision.settle``): each verdict's re-read claim, as Stage 3 left it, replaces its old
    claim the way the same-slot replacement does, every condition checked again now (see the module). Returns
    ``{closed claim id: the revised episode}``. Mutates the claims in ``reconciled``."""
    if not verdicts:
        return {}
    from api.services.claim_reconciler import _close, _date_key, same_object

    out: dict[str, str] = {}
    for v in verdicts:
        rev = revisions.get(v.episode)
        slot = reconciled.get(v.subject) or []
        old = next((c for c in slot if c.id == v.old_id), None)
        if rev is None or not rev.closes or old is None or not _pairable_old(old, v.episode):
            if old is not None and old.valid_to is None and _support(old) != {v.episode}:
                audit.append({"action": "revision_kept", "kept": old.id, "why": "another_conversation"})
            continue
        text = er._changed_text(rev)  # noqa: SLF001
        new = next((c for c in slot if c is not old and c.id != old.id and _carries(c, v)
                    and same_object(c, old) and any(er.says_day(text, d) for d in (v.valid_from, v.expected_end) if d)),
                   None)
        if new is None:
            continue
        _close(old, by=new)
        if old.valid_from and _date_key(old.valid_to) < _date_key(old.valid_from):
            old.valid_to = old.valid_from   # a date moved earlier closes the old claim on its own first day
        # A conversation edited back (`claim_reconciler._edited_back`) says so; any other pair says it was edited.
        from api.services.claim_reconciler import EDITED_BACK

        audit.append({"action": "revised", "closed": old.id, "by": new.id,
                      "why": EDITED_BACK if getattr(new, "_edited_back", None) else WHY})
        out[old.id] = v.episode
    if out:
        logger.info(f"Revision pairs: {len(out)} claim(s) replaced by the revision's own wording of them")
    return out
