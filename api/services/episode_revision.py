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
* **A date said on another line than its evidence is a correction too** (G104 slice 3, review): a relationship's start
  or end (``starts``, ``ends``) is often said a line or two from the words that carry its span ("She moves to X." ...
  "On the 5th, when her contract ends"). When the model re-reads the revision and returns such a relationship with its
  span only in unchanged text but a day the CHANGED lines say (:func:`says_day`, deterministic, no model), it is new
  (:func:`keep_changed`); in Stage 3 it replaces the claim the first read made for the same relationship and that only
  this conversation said, as a same-revision new value does (:func:`redated`, ``superseded_by``, no question).
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
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import evidence, markdown_parser
from api.services.claims import Claim, Evidence, is_event, is_mark, is_record

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
    #: A book's record (ruling 64): a highlight taken out of it is no removed fact and never goes to a page's writer.
    book: bool = False
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
    from api.services import authorship, book_marks, sensitive_flags

    # G235: the person took flagged text out. A transcript's revision closes nothing because its cap slides turns out;
    # this one is the person's act. And when that is ALL that changed, nothing needs reading.
    removal = sensitive_flags.removal_pending({sensitive_flags.KEY: episode.get(sensitive_flags.KEY)})
    only_removal = removal and sensitive_flags.same_after_removal(prior, body, episode)
    return Revision(
        episode_id=str(episode["id"]), prior=prior, body=body, noop=noop, changed=changed, removed=removed,
        windows=() if noop or only_removal else _windows(body, changed), blocks=blocks,
        closes=removal or str(episode.get("capture_kind") or "") != "transcript",
        override=authorship.of_episode(episode), gaps=tuple(episode.get("gaps") or ()),
        book=book_marks.is_book_record(episode))


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


# --------------------------------------------------------------------------- #
# what a person is shown (the Sleep page's Waiting list and the Reader)
# --------------------------------------------------------------------------- #

#: A waiting episode's state for the person (owner 2026-11-23: "a small marker … to signify that it was updated … for
#: a new note then just green, for a deleted one maybe just red").
NEW, UPDATED, REMOVED = "new", "updated", "removed"
#: How much of what an edit took out the Reader is handed: a glance, never the whole old version.
MAX_REMOVED, MAX_REMOVED_CHARS = 12, 400


def waiting_state(fm: dict | None) -> str | None:
    """How a WAITING episode differs from what Sleep knows: ``removed`` when its source deleted it, ``updated`` when
    a version of it was read before and it changed since (the stager's ``revised`` record names that version), else
    ``new``. None for an episode that is not waiting. Pure over the cached header."""
    fm = fm or {}
    if fm.get("processed"):
        return None
    if fm.get("source_deleted_at"):
        return REMOVED
    return UPDATED if consolidated_hash(fm) else NEW


def since_read(memory_path: Path, episode_id: str, fm: dict, text: str) -> dict | None:
    """What changed in a waiting episode since Sleep last read it, for the Reader: ``{state, changed, removed,
    at}`` — ``changed`` are ``(start, end)`` offsets into ``text`` (the evidence text the Reader draws), ``removed``
    the words the edit took out (capped; never for a transcript, whose cap slides old turns out without anyone
    removing them), ``at`` when it was last edited. None for an episode that is not waiting. An updated episode whose
    read version git no longer holds answers its state with no ranges: the marker stays true, nothing is guessed."""
    state = waiting_state(fm)
    if state is None:
        return None
    record = fm.get(REVISED_KEY) if isinstance(fm.get(REVISED_KEY), dict) else {}
    out = {"state": state, "changed": [], "removed": [], "at": str(record.get("at") or "") or None}
    if state != UPDATED:
        return out
    prior = prior_bodies(memory_path, [{"id": episode_id, "filepath": f"{episode_id}.md",
                                        REVISED_KEY: fm.get(REVISED_KEY)}]).get(episode_id)
    if prior is None:
        return out
    changed, removed, _ = diff(prior, text)
    out["changed"] = [[s, e] for s, e in changed]
    if str(fm.get("capture_kind") or "") != "transcript":
        gone = [" ".join(prior[s:e].split()) for s, e in removed]
        out["removed"] = [g[:MAX_REMOVED_CHARS] for g in gone if g][:MAX_REMOVED]
    return out


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
        # An episode emptied by an edit (a section the note lost, G104 slice 3) has no content but IS a revision: its
        # ``revised`` record says it was edited, and every claim only the removed words said settles as withdrawn.
        priors = prior_bodies(memory_path, [ep for ep in episodes
                                            if ep.get("content") or isinstance(ep.get(REVISED_KEY), dict)])
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


#: The first three letters of a month's name in the languages Cicada reads, by month number (accents folded).
_MONTHS: dict[int, frozenset[str]] = {
    1: frozenset({"jan", "ene", "gen"}), 2: frozenset({"feb", "fev"}), 3: frozenset({"mar"}),
    4: frozenset({"apr", "abr", "avr"}), 5: frozenset({"may", "mai", "mag"}), 6: frozenset({"jun", "giu"}),
    7: frozenset({"jul", "lug"}), 8: frozenset({"aug", "ago", "aou"}), 9: frozenset({"sep", "set"}),
    10: frozenset({"oct", "okt", "ott", "out"}), 11: frozenset({"nov"}), 12: frozenset({"dec", "dic", "dez"}),
}
_TOKEN = re.compile(r"\d+|[^\W\d_]+", re.UNICODE)
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def _fold(word: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", word.casefold()) if not unicodedata.combining(ch))


def says_day(text: str, day: str | None) -> bool:
    """Whether ``text`` states the ISO day ``day``: the ISO form itself, or its day of the month beside its month
    (a month's name in English, Spanish, French, German, Italian or Portuguese, or its number: "12 de diciembre",
    "December 12th", "12/12"). Words only; no model. A relative date ("next Friday") states no day here."""
    day = str(day or "")[:10]
    if not _ISO.fullmatch(day):
        return False
    if day in text:
        return True
    month, dom = int(day[5:7]), int(day[8:10])
    tokens = [_fold(t) for t in _TOKEN.findall(text)]
    for i, tok in enumerate(tokens):
        if not (tok.isdigit() and int(tok) == dom and len(tok) <= 2):
            continue
        for near in tokens[max(0, i - 2):i] + tokens[i + 1:i + 3]:
            if near.isdigit():
                if int(near) == month and len(near) <= 2:
                    return True
            elif len(near) >= 3 and near[:3] in _MONTHS[month]:
                return True
    return False


def _stated_days(item: dict) -> list[str]:
    return [str(item.get(k)) for k in ("starts", "ends") if item.get(k)]


def _changed_text(rev: Revision) -> str:
    return "\n".join(rev.body[lo:hi] for lo, hi in rev.changed)


def _bare_key(name) -> str:
    """A name's bare form (`entity_resolver._bare`: no trailing note), case, accents and spacing folded."""
    from api.services import entity_resolver

    return " ".join(_fold(entity_resolver._bare(str(name or ""))).split())  # noqa: SLF001 - the one definition of "bare"


def first_read_names(memory_path, episode_id: str) -> dict[str, set[str]]:
    """Bare form -> the own names of the entities the FIRST READ of ``episode_id`` produced: a page whose
    ``source_episodes`` has it, a pending line whose ``heard_in`` (or own episode) has it. A name or an alias of either
    counts; the value is the entity's own name (a page's title, a line's name)."""
    from api.services import bank_index, pending_store

    own: dict[str, set[str]] = {}

    def add(title, aliases) -> None:
        title = str(title or "").strip()
        if not title:
            return
        for name in (title, *(a for a in aliases or [] if isinstance(a, str))):
            if key := _bare_key(name):
                own.setdefault(key, set()).add(title)

    for entry in bank_index.files(memory_path, "entities"):
        fm = entry.frontmatter or {}
        if episode_id in (fm.get("source_episodes") or []):
            add(fm.get("name"), fm.get("aliases"))
    for line in pending_store.load(memory_path):
        if episode_id in line.episodes():
            add(line.name, line.aliases)
    return own


def canonical_names(memory_path, rev: Revision, entities: list, relationships: list, values: list) -> int:
    """A revision is the same conversation (G104 slice 3): a name its re-read gave with only the model's trailing note
    changed ("Lucía (sister)" for "Lucía") is the entity the first read made. Before resolution, an entity name, and
    every relationship endpoint and value entity naming it, whose bare form (:func:`_bare_key`) is that of exactly ONE
    entity the first read produced is rewritten to that entity's own name; none, or several, is left alone (never a
    guess). Deterministic, no model; touches only the lists given, in place. Returns how many names were rewritten."""
    if not memory_path:
        return 0
    try:
        own = first_read_names(Path(memory_path), rev.episode_id)
    except Exception as exc:  # noqa: BLE001 - a miss is a re-read under its own names, as before
        logger.info(f"revision {rev.episode_id}: first-read names unavailable ({type(exc).__name__})")
        return 0
    if not own:
        return 0

    def canon(name):
        if not isinstance(name, str) or not name.strip():
            return None
        titles = own.get(_bare_key(name))
        if not titles or len(titles) != 1:
            return None
        (title,) = titles
        return title if title != name else None

    changed = 0
    for item, keys in [(e, ("name",)) for e in entities if isinstance(e, dict)] + \
            [(r, ("source", "target")) for r in relationships if isinstance(r, dict)] + \
            [(v, ("entity",)) for v in values if isinstance(v, dict)]:
        for key in keys:
            if (title := canon(item.get(key))) is not None:
                item[key] = title
                changed += 1
    return changed


def keep_changed(rev: Revision, entities: list, relationships: list, values: list) -> tuple[list, list, list, int]:
    """What the revision says that the read version did not: a relationship or value with a span only in unchanged
    text is the first read's; one with no span (an unlocatable quote) is kept — provenance never blocks memory. A
    name is kept when a changed line names it or a kept relationship or value does. Returns the kept lists and how
    many items were left as the first read's.

    One exception (G104 slice 3, review): a relationship with its span only in unchanged text whose stated start or
    end (``starts``, ``ends``) is a day the changed lines say — the date was corrected on another line than the
    words it dates. Stage 3 decides whether it replaces the first read's claim (:func:`redated`); a date the first read
    already had meets its own claim again there, and never gives a name a second chance at a page."""
    changed_text = _changed_text(rev)

    def new(item: dict) -> bool:
        spans = [Evidence.from_dict(e) for e in item.get("evidence") or [] if isinstance(e, dict)]
        spans = [s for s in spans if s.is_span()]
        return not spans or any(_overlaps(s.start, s.end, rev.changed) for s in spans)

    def dated_here(item: dict) -> bool:
        return rev.closes and any(says_day(changed_text, d) for d in _stated_days(item))

    rels = [r for r in relationships if new(r)]
    dated = [r for r in relationships if not any(r is k for k in rels) and dated_here(r)]
    vals = [v for v in values if new(v)]
    said = changed_text.casefold()
    ends = {str(x).strip().casefold() for r in rels for x in (r.get("source"), r.get("target")) if x}
    ends |= {str(v.get("entity") or "").strip().casefold() for v in vals}

    def named(entity: dict) -> bool:
        names = [entity.get("name"), *(entity.get("aliases") or [])]
        names = [str(n).strip().casefold() for n in names if isinstance(n, str) and n.strip()]
        return any(n in ends or n in said for n in names)

    ents = [e for e in entities if isinstance(e, dict) and named(e)]
    left = (len(relationships) - len(rels) - len(dated)) + (len(values) - len(vals)) + (len(entities) - len(ents))
    return ents, [r for r in relationships if any(r is k for k in rels + dated)], vals, left


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


def provenance_row(rev: Revision, ev: Evidence) -> Evidence | None:
    """A `section_provenance` row into ``rev``'s conversation on the version Sleep read, moved onto the new body: a
    span located again as a claim's is (:func:`_relocate`, never fuzzily), a whole-conversation row (``reasoning``)
    stamped with the new hash. ``None`` leaves the row as it is: already current, on some older body, or its words gone
    (`revision_prose` decides which passages still rest on the old version)."""
    if ev.episode != rev.episode_id or ev.hash == rev.hash:
        return None
    if ev.kind == "reasoning" or ev.start < 0:
        if ev.hash != rev.prior_hash:
            return None
        return Evidence(episode=rev.episode_id, start=-1, end=-1, kind="reasoning", hash=rev.hash)
    if not _on_prior(rev, ev):
        return None
    return _relocate(rev, ev)


@dataclass
class Plan:
    #: claim id -> the revised episode only whose removed text said it.
    revised_out: dict[str, str] = field(default_factory=dict)
    reanchored: int = 0
    stale: int = 0


def _closable(c: Claim) -> bool:
    from api.services.claim_reconciler import is_human

    # A book's mark has its own writer, which reads the record itself (`book_marks.apply`).
    return (c.valid_to is None and not is_human(c) and not c.recorded_ts and not is_event(c) and not is_record(c)
            and not is_mark(c))


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


def redated(pool, news, revisions: dict[str, Revision]) -> dict[str, str]:
    """``{old claim id: the revised episode}`` for each open claim in ``pool`` that a revision's re-read of the same
    relationship dates differently (G104 slice 3, review): ``news`` are the revision's incoming claims; one meets a claim
    of the same slot and object that only that conversation said (nothing another conversation, the person, an agent or
    an event holds is touched), with a start or end the claim does not carry and the CHANGED lines say
    (:func:`says_day`). The old claim's span is unchanged text, so :func:`reanchor` cannot mark it; Stage 3 replaces it
    with the new one (``claim_reconciler``'s ``redated``). A date said nowhere in the changed text moves nothing."""
    if not revisions:
        return {}
    from api.services.claim_reconciler import K, open_, same_object

    out: dict[str, str] = {}
    pool = list(pool)
    for n in news:
        eps = set(n.source_episodes or [])
        if len(eps) != 1 or n.valid_to is not None or is_event(n):
            continue
        (ep,) = eps
        rev = revisions.get(ep)
        if rev is None or not rev.closes or not rev.changed:
            continue
        text = _changed_text(rev)
        if not any(d and says_day(text, d) for d in (n.valid_from, n.expected_end)):
            continue
        for o in pool:
            if o is n or o.id in out or not open_(o) or not _closable(o) or K(o) != K(n) or not same_object(o, n):
                continue
            if {e.episode for e in o.evidence} | set(o.source_episodes or []) != {ep}:
                continue
            if (str(o.valid_from or "")[:10], str(o.expected_end or "")[:10]) == (
                    str(n.valid_from or "")[:10], str(n.expected_end or "")[:10]):
                continue
            out[o.id] = ep
            break
    return out


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
            c.closed_by_revision = ep   # this revision's own close, written last (`claims.Claim.closed_by_revision`)
            records.append(record)
            audit.append({"action": "revision_withdrew", "closed": c.id, "by": record.id})
            withdrawn += 1
        slot.extend(records)
    return withdrawn
