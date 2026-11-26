"""An edited conversation's corrected date meets the claim it corrects under another wording (G104, 2026-11-25).

A claim the first read wrote from one line but dated from another keeps its span on the unchanged line, so the span
test never marks it (`episode_revision.reanchor`); and when the re-read words the same relationship under another
predicate ("is moving to", then "moves to") it is another slot, so the same-slot replacement
(`episode_revision.redated`, ``claim_reconciler._place_claim``'s ``redated``) never meets it. The old date stays current
beside the new one.

Three designs that decided something about the OLD claim from the text were dropped (`capture-and-sleep.md`, "A stale
date beside the corrected one"). This step decides nothing from the text. It acts only where the revision's own re-read
claim meets the old one, and only on a reading:

* **A pair** (:func:`candidates`, before Stage 2, read only): an open claim, on a page or held under a name with no
  page yet (`pending_store`, wherever it waits), that this one edited conversation alone says (`episode_revision._closable`; not a value, a number, an event, a record, the person's own or
  an agent's), and a claim of the same revision's re-read with the same subject, the same object, the same context and
  speaker, ANOTHER predicate, and a start or end the old one does not carry that the changed lines say
  (`episode_revision.says_day`, the test `redated` already uses for the new claim), while no start or end of the old
  one that the new one lacks is still said by the conversation as it now stands (:func:`moved`, 2026-11-26: a text
  that says both days moved neither). Predicates are never compared by spelling or similarity. Cheapest tests first;
  each day is read once per revision (:class:`Said`) and nothing is computed past either cap.
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

**Held claims** (a name with no page yet, `pending_store`, 2026-11-25): the benchmark's edited conversation and most
stored failures sit there. A held claim is paired and read like a page claim, and its verdict remembers the line it
waited on. Where it is when the replacement is applied decides how:

* released onto its page in this same pass (the name got its page tonight): :func:`apply` closes the very claim the
  pass released from that line (``Moved``, by identity, its subject and object re-keyed as the release re-keyed them),
  never a look-alike the page already held, exactly as a page claim is closed;
* still held when the store has settled (release, then hold): :func:`apply_held` drops it from that ONE line only when
  the re-read's claim is held in the same line in its place (`pending_store.replace_held`, under the store's lock, after
  this pass's hold merged any other conversation that also says it). The line keeps no closed claims (a closed claim
  released later could close an open one), so the old claim leaves whole, as the same-slot rule's held claims do
  (``claim_pipeline._move_held``); its record is the ledger's ``revised`` row with ``held`` and the batch's Corrections
  record, neither of which a promotion deletes. Nothing in a held claim is cleared or re-dated, and the claim the line
  then holds is the re-read's, dated as the conversation now says.

An edit undone while the name has no page (A, B, A) needs no rule of its own: the old claim left the line whole, so the
restored wording is a new claim that meets the correction by this rule or the same-slot one.
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
    """A pair both readers called the same relationship: the old claim by id and by what it said when it was judged
    (``old_*``), the re-read's claim by what it says (its id is minted again by Stage 3's projection, so it is matched
    on its content, never guessed). ``held``: the pending line the old claim waited on when it was judged (a name with no
    page yet), ``""`` for a claim on a page."""

    episode: str
    old_id: str
    subject: str
    context: str
    observer: str
    predicate: str
    object: str
    valid_from: str
    expected_end: str
    held: str = ""
    old_subject: str = ""
    old_object: str = ""
    old_from: str = ""
    old_end: str = ""


@dataclass(frozen=True)
class Moved:
    """A held claim this pass released onto a page (`claim_pipeline._releases`): the claim object Stage 3 was handed,
    the line it left, that line's slug and the page it went to."""

    claim: Claim
    line: str
    slug: str
    target: str


@dataclass
class Pair:
    key: str
    rev: er.Revision
    old: Claim
    new: Claim
    days: tuple[str, ...]
    held: str = ""


@dataclass
class Reading:
    verdicts: list[Verdict] = field(default_factory=list)
    pairs: int = 0
    calls: int = 0
    first_same: int = 0
    failed: int = 0
    #: Revisions with dated re-read claims left past :data:`MAX_REVISIONS` (never compared).
    capped: int = 0


def _day(value) -> str:
    return str(value or "")[:10]


def _support(c: Claim) -> set[str]:
    return {e.episode for e in c.evidence} | set(c.source_episodes or [])


def _pairable_old(c: Claim, ep: str) -> bool:
    from api.services import phone_numbers

    return (er._closable(c) and not c.superseded_by and not is_value_claim(c)  # noqa: SLF001 - the one rule
            and not phone_numbers.is_number_claim(c) and _support(c) == {ep})


def won_elsewhere(c: Claim, ep: str, page) -> bool:
    """``c`` has since taken the place of another claim of its page by anything but ``ep``'s own revision: the person's
    pick in the inbox, Sleep's settle, an ordinary update (review 5, 2026-11-26). Such a claim stands on more than this
    conversation's word, though nothing else on it says so (a pick only raises its confidence): the rules of this
    module and the edited-back rule leave it as it is. Read from ``supersedes``, which every close writes on the claim
    that won, and the mark only a revision's close carries (``Claim.closed_by_revision``). A link that names no claim
    of ``page`` (a held line keeps none) says nothing."""
    if not c.supersedes:
        return False
    prev = next((p for p in page if p.id == c.supersedes), None)
    return prev is not None and prev.closed_by_revision != ep


class Said:
    """Which days one revision states, each day read once (2026-11-26, review 4: the reader ran over the whole changed
    text twice for every old and new claim compared). ``changed``: the changed lines say it (`episode_revision.says_day`
    over `_changed_text`, the test `redated` makes of the new claim); ``body``: the conversation as it now stands says
    it anywhere."""

    def __init__(self, rev: er.Revision):
        self.rev = rev
        self._text: str | None = None
        self._changed: dict[str, bool] = {}
        self._body: dict[str, bool] = {}

    def changed(self, day: str) -> bool:
        if day not in self._changed:
            if self._text is None:
                self._text = er._changed_text(self.rev)  # noqa: SLF001 - the changed lines, one definition
            self._changed[day] = er.says_day(self._text, day)
        return self._changed[day]

    def body(self, day: str) -> bool:
        if day not in self._body:
            self._body[day] = er.says_day(self.rev.body, day)
        return self._body[day]


def _places(c: Claim) -> tuple[str, str]:
    return _day(c.valid_from), _day(c.expected_end)


def _new_days(n: Claim, said: Said) -> tuple[str, ...]:
    """The days the re-read's claim carries that the changed lines say (start, end)."""
    return tuple(d for d in _places(n) if d and said.changed(d))


def restates(o: Claim, n: Claim, said: Said, days: tuple[str, ...] | None = None) -> bool:
    """``n`` carries a start or end the changed lines say that ``o`` does not carry in that place. ``days``:
    :func:`_new_days`, when already read."""
    days = _new_days(n, said) if days is None else days
    new_from, new_end = _places(n)
    old_from, old_end = _places(o)
    return any((d == new_from and d != old_from) or (d == new_end and d != old_end) for d in days)


def moved(o: Claim, n: Claim, said: Said, days: tuple[str, ...] | None = None) -> bool:
    """The day moved from ``o`` to ``n`` in this revision's text: ``n`` carries a start or end the changed lines say that
    ``o`` does not carry in that place (:func:`restates`), and no start or end of ``o`` that ``n`` does not carry is
    still said by the conversation as it now stands (2026-11-26, review 4: "8 December (she first planned 5 December)"
    says both days, so neither has moved). A day the reader cannot find is not said (an accepted limit: then the claims
    stay as they are only if the reader does find it). The whole conversation is asked, any line of it: a day's words
    cannot be tied to one relationship (reviews 5 and 6 each broke a narrower test of "this edit"), so this test is
    used only where a refusal leaves things as they were before these rules."""
    if not restates(o, n, said, days):
        return False
    new_from, new_end = _places(n)
    old_from, old_end = _places(o)
    return not any(old and old != new and said.body(old) for old, new in ((old_from, new_from), (old_end, new_end)))


def reworded(o: Claim, n: Claim, episode: str) -> bool:
    """``o`` and ``n`` are the two halves a pair is made of, the text aside: the same things under another predicate,
    ``o`` open and ``episode``'s alone."""
    return _same_things(o, n) and _pairable_old(o, episode)


def _same_things(o: Claim, n: Claim) -> bool:
    from api.services.claim_reconciler import same_object, slot_observer

    return (o.subject == n.subject and o.predicate != n.predicate and o.context == n.context
            and same_object(o, n) and slot_observer(o) == slot_observer(n))


def meets(o: Claim, n: Claim, rev: er.Revision, said: Said | None = None,
          days: tuple[str, ...] | None = None) -> bool:
    """Is ``o`` (on a page) the pair of ``n`` (a claim of ``rev``'s re-read)? See the module: the same things under
    another predicate, ``o`` open and this one conversation's alone, and the day moved from ``o`` to ``n``
    (:func:`moved`). The one test :func:`candidates` and the reconciler's edited-back rule share. Cheapest tests first;
    the text is read only for a pair that passes them, each day once per ``said``."""
    if not reworded(o, n, rev.episode_id):
        return False
    return moved(o, n, said or Said(rev), days)


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


def _held_pool(memory_path: Path, existing: dict[str, list[Claim]]) -> dict[str, list[tuple[Claim, str]]]:
    """The claims waiting under a name with no page yet (`pending_store`), by subject, each with its line's name — as
    the store holds them now, before this pass re-anchors, releases or holds anything. A held claim whose id its
    subject's page already holds is not offered: the page's own is the one a release would leave (`_releases`)."""
    from api.services import pending_store

    out: dict[str, list[tuple[Claim, str]]] = {}
    for line in pending_store.load(memory_path):
        for data in line.held_claims:
            try:
                c = Claim.from_dict(data)
            except (TypeError, ValueError):
                continue
            if any(p.id == c.id for p in existing.get(c.subject, [])):
                continue
            out.setdefault(c.subject, []).append((c, line.name))
    return out


def candidates(memory_path: Path, revisions: dict[str, er.Revision], extracted: list[dict],
               settings=None, cancelled: Callable[[], bool] | None = None) -> list[Pair]:
    """The pairs of this batch's revisions (see the module). Pure reads: the claims on pages and the claims held under
    a name with no page yet (`pending_store`), wherever the old claim waits. At most :data:`MAX_PAIRS` a revision and
    :data:`MAX_REVISIONS` revisions with pairs: nothing past either is computed. ``cancelled`` is asked before each
    re-read claim is compared (a stop never waits for a large page)."""
    return _collect(memory_path, revisions, extracted, settings, cancelled)[0]


def _collect(memory_path: Path, revisions: dict[str, er.Revision], extracted: list[dict], settings,
             cancelled: Callable[[], bool] | None) -> tuple[list[Pair], int]:
    """:func:`candidates`, and how many revisions with dated re-read claims were left past :data:`MAX_REVISIONS`."""
    from api.services.claim_pipeline import _load_existing_claims_by_subject
    from api.services.entity_extractor import entities_to_claims

    memory_path = Path(memory_path)
    news: dict[str, tuple[er.Revision, Said, list[tuple[Claim, tuple[str, ...]]]]] = {}
    for item in extracted:
        ep = str(item.get("episode_id") or "")
        rev = revisions.get(ep)
        if rev is None or not rev.closes or not rev.changed or rev.book or not item.get("relationships"):
            continue
        _rev, said, mine = news.setdefault(ep, (rev, Said(rev), []))
        only_rels = {**item, "entities": [], "values": []}
        for n in entities_to_claims([only_rels], memory_path, resolve_id=_resolver(memory_path, ep, settings)):
            if is_event(n) or is_record(n) or n.valid_to is not None or set(n.source_episodes or []) != {ep}:
                continue
            days = _new_days(n, said)
            if days:
                mine.append((n, days))
    news = {ep: entry for ep, entry in news.items() if entry[2]}
    if not news:
        return [], 0
    existing = _load_existing_claims_by_subject(memory_path)
    held = _held_pool(memory_path, existing)
    out: list[Pair] = []
    with_pairs = 0
    for n_rev, (ep, (rev, said, mine)) in enumerate(news.items()):
        if with_pairs >= MAX_REVISIONS:
            return out, len(news) - n_rev
        found = 0
        for n, days in mine:
            if found >= MAX_PAIRS or (cancelled is not None and cancelled()):
                break
            for o, line in [(o, "") for o in existing.get(n.subject, [])] + held.get(n.subject, []):
                if meets(o, n, rev, said, days) and not won_elsewhere(o, ep, existing.get(n.subject, [])):
                    found += 1
                    out.append(Pair(f"p{found}", rev, o, n, days, held=line))
                    if found >= MAX_PAIRS:
                        break
        with_pairs += bool(found)
    return out, 0


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

    n, o = p.new, p.old
    return Verdict(episode=p.rev.episode_id, old_id=o.id, subject=n.subject, context=n.context,
                   observer=slot_observer(n), predicate=n.predicate, object=_norm_object(n.object),
                   valid_from=_day(n.valid_from), expected_end=_day(n.expected_end), held=p.held,
                   old_subject=o.subject, old_object=_norm_object(o.object), old_from=_day(o.valid_from),
                   old_end=_day(o.expected_end))


def read(memory_path: Path, revisions: dict[str, er.Revision], extracted: list[dict],
         small: Callable[[str], dict] | None, main: Callable[[str], dict] | None, *, settings=None,
         cancelled: Callable[[], bool] | None = None) -> Reading:
    """Both readings for each revision with pairs; the pairs both call the same are returned as verdicts. A missing
    reader, no pair, a failed or unreadable answer: no verdict. Never raises."""
    out = Reading()
    if small is None or main is None or not revisions:
        return out
    try:
        pairs, out.capped = _collect(Path(memory_path), revisions, extracted, settings, cancelled)
    except Exception as exc:  # noqa: BLE001 - a miss is no reading
        logger.warning(f"Revision pairs: candidates unavailable ({type(exc).__name__})")
        return out
    by_ep: dict[str, list[Pair]] = {}
    for p in pairs:
        by_ep.setdefault(p.rev.episode_id, []).append(p)
    for ep, group in by_ep.items():
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


def _carries(c: Claim, v: Verdict, subject: str, obj: str) -> bool:
    """``c`` is the re-read's claim the verdict judged, as it stands now: open, superseding nothing, the same words of
    the relationship, the judged day, this conversation cited, about ``subject`` and ``obj`` (where it went)."""
    from api.services.claim_reconciler import _norm_object, open_, slot_observer

    return (open_(c) and not c.superseded_by and not c.supersedes and not is_record(c) and not is_event(c)
            and c.subject == subject and c.predicate == v.predicate and c.context == v.context
            and slot_observer(c) == v.observer and _norm_object(c.object) == obj
            and _day(c.valid_from) == v.valid_from and _day(c.expected_end) == v.expected_end
            and v.episode in (c.source_episodes or []))


def _was(c: Claim, v: Verdict, subject: str, obj: str) -> bool:
    """``c`` is still the claim the verdict was made on: about ``subject`` and ``obj``, the day it carried when judged,
    open and this conversation's alone (`_pairable_old`; a conversation read since that also says it keeps it)."""
    from api.services.claim_reconciler import _norm_object

    return (c.subject == subject and _norm_object(c.object) == obj and _day(c.valid_from) == v.old_from
            and _day(c.expected_end) == v.old_end and _pairable_old(c, v.episode))


def _where(v: Verdict, moved: Moved | None) -> tuple[str, str, str, str]:
    """Where the old claim and the re-read's claim are now: ``(old subject, old object, new subject, new object)``. A
    claim released from its line this pass was re-keyed onto the page Stage 2 gave the name (`pending_store.repointed`),
    and the re-read's claim of that name went to the same page by the same verdict."""
    from api.services import pending_store
    from api.services.claim_reconciler import _norm_object

    if moved is None:
        return v.old_subject, v.old_object, v.subject, v.object
    slug, target = _norm_object(moved.slug), moved.target
    old_s, old_o = pending_store.repointed(v.old_subject, v.old_object, slug, target)
    return (old_s, _norm_object(old_o), target if v.subject == slug else v.subject,
            _norm_object(target) if v.object == slug else v.object)


def _kept(old: Claim | None, v: Verdict, audit: list[dict]) -> None:
    if old is not None and old.valid_to is None and _support(old) != {v.episode}:
        audit.append({"action": "revision_kept", "kept": old.id, "why": "another_conversation"})


def apply(reconciled: dict[str, list[Claim]], verdicts: list[Verdict], revisions: dict[str, er.Revision],
          audit: list[dict], released: dict[str, Moved] | None = None) -> dict[str, str]:
    """After Stage 3 (and ``episode_revision.settle``): each verdict's re-read claim, as Stage 3 left it, replaces its old
    claim the way the same-slot replacement does, every condition checked again now (see the module). The old claim is
    the one on its page (by id), or, for one judged while it was held, the very claim this pass released from that line
    (``released``: ``{claim id: Moved}``, matched by identity, never a look-alike the page already held); a verdict on a
    claim still held waits for :func:`apply_held`. Returns ``{closed claim id: the revised episode}``. Mutates the claims
    in ``reconciled``."""
    if not verdicts:
        return {}
    from api.services.claim_reconciler import EDITED_BACK, _close_by_revision, same_object

    out: dict[str, str] = {}
    for v in verdicts:
        rev = revisions.get(v.episode)
        if rev is None or not rev.closes:
            continue
        if v.held:
            moved = (released or {}).get(v.old_id)
            if moved is None or moved.line != v.held:
                continue   # still held (or not released from that line): `apply_held`, once the store has settled
            old_s, old_o, new_s, new_o = _where(v, moved)
            slot = reconciled.get(moved.claim.subject) or []
            old = next((c for c in slot if c is moved.claim), None)
        else:
            old_s, old_o, new_s, new_o = _where(v, None)
            slot = reconciled.get(v.subject) or []
            old = next((c for c in slot if c.id == v.old_id), None)
        if old is None or not _was(old, v, old_s, old_o) or won_elsewhere(old, v.episode, slot):
            _kept(old, v, audit)
            continue
        text = er._changed_text(rev)  # noqa: SLF001
        new = next((c for c in slot if c is not old and c.id != old.id and _carries(c, v, new_s, new_o)
                    and same_object(c, old) and any(er.says_day(text, d) for d in (v.valid_from, v.expected_end) if d)),
                   None)
        if new is None:
            continue
        # A date moved earlier closes the old claim on its own first day; the close is marked as this revision's.
        _close_by_revision(old, by=new, episode=v.episode, floor=True)
        # A conversation edited back (`claim_reconciler._edited_back`) says so; any other pair says it was edited.
        audit.append({"action": "revised", "closed": old.id, "by": new.id,
                      "why": EDITED_BACK if getattr(new, "_edited_back", None) else WHY})
        out[old.id] = v.episode
    if out:
        logger.info(f"Revision pairs: {len(out)} claim(s) replaced by the revision's own wording of them")
    return out


def apply_held(memory_path: Path, verdicts: list[Verdict], revisions: dict[str, er.Revision], audit: list[dict],
               done: dict[str, str] | None = None) -> dict[str, str]:
    """After the pending store settled (this pass's release and hold): each verdict on a claim judged while held, whose
    line still holds it, drops it from that ONE line only when the re-read's claim now stands in its place in that same
    line — open, the same subject and object, the judged day, this conversation cited, held (not refused at the line's
    cap, not folded into another claim, not under another name) — and the old claim is still what was judged and still
    this conversation's alone (`pending_store.replace_held` checks under the store's lock, after this pass's hold merged
    any other conversation that says it). Nothing is cleared or re-dated: the old claim leaves the line whole, the new
    one stays as the re-read wrote it. One new claim stands for one old claim. ``done``: what :func:`apply` already
    replaced. Recorded as the page path's replacement is (audit ``revised``, ``held``), never on the line itself, which
    a promotion deletes. Returns ``{dropped claim id: the revised episode}``."""
    from api.services import pending_store
    from api.services.claim_reconciler import same_object

    out: dict[str, str] = {}
    used: set[str] = set()
    for v in verdicts:
        if not v.held or v.old_id in (done or {}):
            continue
        rev = revisions.get(v.episode)
        if rev is None or not rev.closes:
            continue
        text = er._changed_text(rev)  # noqa: SLF001

        def stands(old: Claim, others: list[Claim], v: Verdict = v, text: str = text) -> str | None:
            if not _was(old, v, v.old_subject, v.old_object):
                _kept(old, v, audit)
                return None
            new = next((c for c in others if c.id not in used and c.id != old.id
                        and _carries(c, v, v.subject, v.object) and same_object(c, old)
                        and any(er.says_day(text, d) for d in (v.valid_from, v.expected_end) if d)), None)
            return new.id if new is not None else None

        by = pending_store.replace_held(memory_path, v.held, v.old_id, stands)
        if not by:
            continue
        used.add(by)
        audit.append({"action": "revised", "closed": v.old_id, "by": by, "why": WHY, "held": True})
        out[v.old_id] = v.episode
    if out:
        logger.info(f"Revision pairs: {len(out)} held claim(s) replaced by the revision's own wording of them")
    return out
