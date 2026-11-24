"""What a Sleep run really did to one page: the classification every count and list uses, and the structured change
the app renders (owner 2026-11-24, after the Sleep page redesign: "the pages should render normally, not as raw markdown
… and I don't get why <a page> was modified there, what influenced this change?").

The measured problem: one run's main commit touched 1,939 entity files, 1,930 of which changed **only** claim
bookkeeping (``decayed_through`` moved on 5,225 claims, ``confidence`` also on 812 of them: silence), 3 only frontmatter
dates and counters, and about 5 in substance. A count of "files git says changed" said "1,864 pages updated", and the
diff of one of them was two JSON lines that differ in a key far off to the right.

**One classification** (:func:`classify` / :func:`fast_verdict`), used by the opened card's lists, the closed card's
counts and the page's own change route, from the patch of the commit (git, never a model):

* ``bookkeeping`` — a decay stamp, a last-referenced date, a version counter, an enrichment marker, the ledger's stamp
  and the like. **Not a change**: neither counted nor listed.
* ``fade`` — a fact (or the page) lost or regained confidence from silence alone (``confidence`` / ``faded_by_age``
  beside the bookkeeping, a page moving between ``active`` and ``decaying``). Its own quiet entry, never "updated".
* ``substance`` — a fact added, withdrawn or changed in a meaningful field; prose; a frontmatter key a person reads
  (status, name, type, aliases, tags, sources…).

``created`` / ``removed`` are the file's own add and delete. The claim set of a page is its fenced block **plus** its
ledger file (``claims_ledger``): both are read, and a claim moving from one to the other is no change at all.

**The fast path** reads the unified patch (``-U0``) line by line: a claim line is JSON (``{"id": …``), a frontmatter line
is ``key: value``; when every changed line is one of those, no page is parsed. Anything else — prose, a YAML list, a
fence marker, an unreadable line — sends that one page to :func:`compare`, which parses both versions in full. The two
agree on every page they both can read (a test pins it).

**The change route** (:func:`change`) is :func:`compare` on one page's two versions, shaped for the app: facts as the
one claim wire (``transclusion_resolver.claim_to_model``) with the meaningful fields that changed, prose as blocks of the
page's own markdown (added / removed / edited with its words, the heading they sit under, a little context), and the few
non-bookkeeping frontmatter changes in words-ready form. No bookkeeping key, no id, no frontmatter dump leaves here.
"""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from dataclasses import dataclass, field

from api.services import claims as claims_mod
from api.services import claims_ledger, markdown_parser

# --------------------------------------------------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------------------------------------------------

BOOKKEEPING, FADE, SUBSTANCE = "bookkeeping", "fade", "substance"

#: Frontmatter keys that move without the page's meaning moving: dates and counters Sleep stamps, enrichment markers,
#: the ledger's pointer. A page whose only changes are these is not "updated".
FM_BOOKKEEPING = frozenset({
    "last_referenced", "learned_on", "decayed_through", "version", "enrichment_attempted", "enrichment_status",
    "read_late", "claims_ledger",
})
#: What silence moves: the page's (and a fact's) confidence, and the day its own age took it below the question line.
FM_FADE = frozenset({"confidence", "faded_by_age"})
#: A claim's bookkeeping: the decay watermark, the restatement ledgers, timestamps of the write, who wrote it, how a
#: date was decided. None of them is the belief.
CLAIM_BOOKKEEPING = frozenset({
    "decayed_through", "read_late", "recorded_ts", "recorded_at", "session_id", "session_ids", "recovered_from",
    "recovered_by", "authored_by", "origin", "premises", "date_basis", "participants", "id",
})
CLAIM_FADE = frozenset({"confidence", "faded_by_age"})
#: Every other claim key is a meaningful field with its own word; ``sources`` is the set of conversations behind it.
CLAIM_FIELDS = ("text", "subject", "predicate", "object", "valid_from", "valid_to", "expected_end", "superseded_by",
                "supersedes", "status", "target", "context", "source_trust", "observer", "epistemic", "confidence",
                "sources", "details")
#: Page-level frontmatter that is a cause (which conversation fed it), a stamp or derived plumbing, never a "change" to
#: show. Decided key by key, never by omission: ``source_episodes`` / ``source_episode`` are the cause (a conversation
#: ADDED is :attr:`Delta.fed`, one REMOVED is :attr:`Delta.unfed`, both substance); ``created`` and ``id`` never move;
#: ``archived_by`` rides with the ``status`` move that is shown; ``decay_rate`` is derived from ``decay_class``
#: (``decay_policy``) and so moves only with it (a class change is shown). What a person or a cascade DECIDED is a
#: change and is NOT here: ``related`` (a link on the record), ``sources_removed``, ``aliases_removed`` and
#: ``aliases_kept`` — a change to any of them is counted in ``details``.
FM_NOT_SHOWN = FM_BOOKKEEPING | FM_FADE | frozenset({
    "source_episodes", "source_episode", "created", "decay_rate", "archived_by", "id",
})
#: The page changes the app has a sentence for; any other changed key is counted in ``details``, never named.
OTHER_FIELDS = ("status", "name", "type", "aliases", "tags", "decay_class", "sources")

#: What changed a page, when no conversation of the run did. Closed: the app turns each into words.
STEPS = ("reading", "decay", "conflict", "settled", "join", "source_check", "link_enrichment", "summary", "web",
         "expiry", "import", "other")

#: A Sleep batch's manifest line carries the trigger that changed each file (``sleep_cycle._finalize``).
_TRIGGER_STEP = (
    ("sleep/decay", "decay"), ("decay", "decay"), ("sleep/conflict_resolution", "conflict"),
    ("sleep/dedup", "join"), ("sleep/correspondent", "join"), ("sleep/extraction", "reading"),
    ("sleep/promotion", "reading"), ("sleep/phone_number", "reading"),
)
#: The engine-free tail's own commits (their subjects), by what each one does to a page already on the record. A
#: commit by the person (``Cicada-Author: user``) is never one of these, whatever its subject says.
_SUBJECT_STEP = (
    ("Inbox settled by Sleep", "settled"), ("Titled by a nickname by Sleep", "settled"),
    ("Same-name review", "join"), ("Arrival join", "join"), ("Merged pages", "join"), ("Split a page", "join"),
    ("Dedup sweep", "join"),
    ("Source refresh", "source_check"), ("Site check", "source_check"), ("Where to check", "source_check"),
    ("Source links", "source_check"),
    ("Link enrichment", "link_enrichment"), ("In short", "summary"), ("Recording notes", "summary"),
    ("Web check", "web"), ("Web context", "web"),
    ("Expiry", "expiry"), ("Follow-ups", "expiry"),
    ("LinkedIn connections", "import"), ("Contacts", "import"), ("Followed accounts", "import"),
)


def step_for_trigger(trigger: str | None) -> str:
    """The step a manifest ``trigger:`` names, ``other`` for one Cicada cannot name honestly (never a guess)."""
    t = (trigger or "").strip()
    for prefix, step in _TRIGGER_STEP:
        if t == prefix or t.startswith(prefix + "/"):
            return step
    return "other"


def step_for_subject(subject: str | None) -> str | None:
    """The tail step a commit's subject names, or ``None`` when it is not one of the steps that change pages."""
    s = (subject or "").strip()
    for prefix, step in _SUBJECT_STEP:
        if s.startswith(prefix):
            return step
    return None


# --------------------------------------------------------------------------------------------------------------------
# The unified patch: one page's changed lines
# --------------------------------------------------------------------------------------------------------------------

def page_of(path: str) -> tuple[str, bool] | None:
    """``(page id, is its ledger)`` for ``entities/<id>.md`` or ``entities/<id>.claims.jsonl``, else ``None``."""
    if not path.startswith("entities/") or path.count("/") != 1:
        return None
    if path.endswith(claims_ledger.SUFFIX):
        return path[len("entities/"):-len(claims_ledger.SUFFIX)], True
    if path.endswith(".md"):
        return path[len("entities/"):-3], False
    return None


@dataclass
class PagePatch:
    """Every changed line of one page across its two files: ``(sign, text, in_ledger)`` in patch order.

    ``numbers`` is each line's own line number in the file it belongs to (the old file for ``-``, the new for ``+``).
    ``fence`` is the line number of each side's closing frontmatter ``---`` (``{"-": n, "+": n}``), set by the caller
    that read it: a ``key: value`` line is the page's frontmatter only when it sits above that line — a paragraph of
    prose that happens to read ``version: 1 of the plan`` is prose."""
    lines: list[tuple[str, str, bool]] = field(default_factory=list)
    ledger: bool = False   # the ledger file is in this patch
    numbers: list[int] = field(default_factory=list)
    fence: dict[str, int] = field(default_factory=dict)


def parse_patch(text: str) -> dict[str, PagePatch]:
    """``{page id: PagePatch}`` from ``git diff-tree -p -U0`` output over ``entities/``. A header line (``--- a/…``,
    ``+++ b/…``) is told from a changed line that happens to begin ``--``/``++`` by where it sits: before a file's first
    hunk."""
    out: dict[str, PagePatch] = {}
    current: PagePatch | None = None
    ledger = False
    in_hunk = False
    old_no = new_no = 0
    for raw in text.split("\n"):
        if raw.startswith("diff --git "):
            in_hunk = False
            current = None
            path = raw.rsplit(" b/", 1)[-1].strip().strip('"')
            found = page_of(path)
            if found is not None:
                current = out.setdefault(found[0], PagePatch())
                ledger = found[1]
                current.ledger = current.ledger or ledger
            continue
        if current is None:
            continue
        if raw.startswith("@@"):
            in_hunk = True
            m = _HUNK.match(raw)
            old_no, new_no = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
            continue
        if not in_hunk or not raw or raw[0] not in "+-":
            continue
        current.lines.append((raw[0], raw[1:], ledger))
        if raw[0] == "-":
            current.numbers.append(old_no)
            old_no += 1
        else:
            current.numbers.append(new_no)
            new_no += 1
    return out


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def frontmatter_end(text: str | None) -> int | None:
    """The 1-based line number of the ``---`` that closes ``text``'s frontmatter, ``None`` when it has none."""
    if not text or not text.startswith("---"):
        return None
    first = text.split("\n", 1)[0].rstrip()
    if first != "---":
        return None
    at = 0
    while (at := text.find("\n---", at)) >= 0:
        end = text.find("\n", at + 1)
        if text[at + 1:end if end >= 0 else len(text)].rstrip() == "---":
            return text.count("\n", 0, at + 1) + 1
        at += 1
    return None


# --------------------------------------------------------------------------------------------------------------------
# Claims: pairing and what changed in each pair
# --------------------------------------------------------------------------------------------------------------------


def _canon(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, ensure_ascii=False, default=str)


def pair_claims(removed: list[dict], added: list[dict], *, cancel: bool = True
                ) -> tuple[list[dict], list[dict], list[tuple[dict, dict]]]:
    """``(withdrawn, new, pairs)`` from the claim lines a change removed and added. A line in both (a claim that moved
    between the fence and its ledger, or only changed place) cancels (``cancel=False``: the caller already cancelled
    byte-identical lines); the rest pair by id in order — ids come from the fact, so a withdrawn claim and its
    restatement can share one, and then they are a change of that fact."""
    gone, came = list(removed), list(added)
    if cancel:
        same = Counter(_canon(d) for d in removed) & Counter(_canon(d) for d in added)
        gone, came = [], []
        spare = Counter(same)
        for d in removed:
            k = _canon(d)
            if spare.get(k):
                spare[k] -= 1
            else:
                gone.append(d)
        spare = Counter(same)
        for d in added:
            k = _canon(d)
            if spare.get(k):
                spare[k] -= 1
            else:
                came.append(d)
    by_id: dict[str, list[dict]] = {}
    for d in gone:
        by_id.setdefault(str(d.get("id") or ""), []).append(d)
    pairs: list[tuple[dict, dict]] = []
    new: list[dict] = []
    for d in came:
        queue = by_id.get(str(d.get("id") or ""))
        if queue:
            pairs.append((queue.pop(0), d))
        else:
            new.append(d)
    withdrawn = [d for queue in by_id.values() for d in queue]
    return withdrawn, new, pairs


def _norm(value):
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _norm(v) for k, v in value.items()}
    return str(value)


def _episodes(entry: dict) -> list[str]:
    seen = [str(e) for e in (entry.get("source_episodes") or []) if e]
    for ev in entry.get("evidence") or []:
        if isinstance(ev, dict) and ev.get("episode"):
            seen.append(str(ev["episode"]))
    return sorted(set(seen))


def claim_diff(before: dict, after: dict) -> tuple[dict[str, tuple], dict[str, tuple]]:
    """``(meaningful, fade)`` for one claim: the fields a person would read that changed (``field -> (before, after)``,
    one of :data:`CLAIM_FIELDS`), and the silence-only ones. Bookkeeping keys never appear; evidence offsets moving
    inside the same conversations are no change; an unknown key is ``details`` (named by no word)."""
    meaningful: dict[str, tuple] = {}
    fade: dict[str, tuple] = {}
    for key in sorted(set(before) | set(after)):
        if key in CLAIM_BOOKKEEPING or key in ("evidence", "source_episodes"):
            continue
        b, a = _norm(before.get(key)), _norm(after.get(key))
        if b == a:
            continue
        if key in CLAIM_FADE:
            fade[key] = (before.get(key), after.get(key))
        elif key in CLAIM_FIELDS:
            meaningful[key] = (before.get(key), after.get(key))
        elif key == "object_kind":
            meaningful.setdefault("object", (before.get("object"), after.get("object")))
        else:
            meaningful["details"] = (None, None)
    b_eps, a_eps = _episodes(before), _episodes(after)
    if b_eps != a_eps:
        meaningful["sources"] = (b_eps, a_eps)
    return meaningful, fade


# --------------------------------------------------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------------------------------------------------


@dataclass
class Verdict:
    """One page's change in one commit: ``kind`` (:data:`BOOKKEEPING`, :data:`FADE`, :data:`SUBSTANCE`) and its
    ``status`` move ``(before, after)`` when the ``status:`` line changed."""
    kind: str
    status: tuple[str, str] | None = None


_FM_LINE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(?P<value>.*))?$")
_STAMP_LINE = re.compile(r"^[ \t]+(?:claims|hash|read):[ \t]*\S*$")
_FM_FAST = FM_BOOKKEEPING | FM_FADE | {"status"}
_QUOTES = "\"' \t"


def _status_verdict(old: str | None, new: str | None) -> tuple[bool, bool, tuple[str, str] | None]:
    """``(substance, fade, move)`` of a ``status:`` change: a move between ``active`` and ``decaying`` is silence
    working; every other move (archived, restored, dropped) is a change."""
    if old == new:
        return False, False, None
    move = (old or "", new or "")
    if {old, new} <= {"active", "decaying"}:
        return False, True, move
    return True, False, move


def _kind(substance: bool, fade: bool) -> str:
    return SUBSTANCE if substance else FADE if fade else BOOKKEEPING


def _frontmatter_line(patch: PagePatch, at: int) -> bool:
    """Whether changed line ``at`` of the patch sits in its file's frontmatter (above the closing ``---``, below the
    opening one). ``False`` when the fence is not known: the caller then leaves the page to :func:`compare`."""
    sign = patch.lines[at][0]
    end = patch.fence.get(sign)
    return end is not None and at < len(patch.numbers) and 1 < patch.numbers[at] < end


def wants_fence(patch: PagePatch) -> bool:
    """Whether :func:`fast_verdict` would need to know where the frontmatter ends: a changed line that reads like a
    stamp or a ``status``. Pages whose patch is claim lines alone never do."""
    for sign, text, in_ledger in patch.lines:
        s = text.rstrip("\r")
        if not s.strip() or s.startswith("{") or in_ledger:
            continue
        m = _FM_LINE.match(s)
        if (m and m.group("key") in _FM_FAST) or (patch.ledger and _STAMP_LINE.match(s)):
            return True
    return False


def fast_verdict(patch: PagePatch) -> Verdict | None:
    """The verdict from the patch alone, or ``None`` when some changed line is not a claim line or a frontmatter line
    this module can read (prose, a list item, a fence marker, a line that is not JSON, a ``key: value`` line not known
    to sit in the frontmatter, :attr:`PagePatch.fence`): then :func:`compare` decides."""
    removed_raw: list[str] = []
    added_raw: list[str] = []
    status: dict[str, str] = {}
    fade = False
    for at, (sign, text, in_ledger) in enumerate(patch.lines):
        s = text.rstrip("\r")
        if not s.strip():
            continue
        if s.startswith("{"):
            (removed_raw if sign == "-" else added_raw).append(s)
            continue
        if in_ledger:
            return None
        m = _FM_LINE.match(s)
        if m and m.group("key") in _FM_FAST:
            if not _frontmatter_line(patch, at):
                return None
            key, value = m.group("key"), (m.group("value") or "").strip(_QUOTES)
            if key == "status":
                if sign in status:
                    return None
                status[sign] = value
            elif key in FM_FADE:
                fade = True
            continue
        if patch.ledger and _STAMP_LINE.match(s):
            if not _frontmatter_line(patch, at):
                return None
            continue
        return None
    old, new = status.get("-"), status.get("+")
    if ("-" in status) != ("+" in status):
        return None
    move_substance, move_fade, move = _status_verdict(old, new)
    # A line both removed and added (a claim that moved between the fence and its ledger) is no change: cancelled
    # byte for byte before any of it is parsed.
    same = Counter(removed_raw) & Counter(added_raw)
    removed, added = [], []
    try:
        for raws, into in ((removed_raw, removed), (added_raw, added)):
            spare = Counter(same)
            for raw in raws:
                if spare.get(raw):
                    spare[raw] -= 1
                    continue
                entry = json.loads(raw)
                if not isinstance(entry, dict):
                    return None
                into.append(entry)
    except ValueError:
        return None
    withdrawn, came, pairs = pair_claims(removed, added, cancel=False)
    substance = bool(withdrawn or came) or move_substance
    for before, after in pairs:
        meaningful, faded = claim_diff(before, after)
        if meaningful:
            substance = True
        elif faded:
            fade = True
    return Verdict(_kind(substance, fade or move_fade), move)


# --------------------------------------------------------------------------------------------------------------------
# A page's two versions, compared in full
# --------------------------------------------------------------------------------------------------------------------


@dataclass
class Version:
    """One version of a page: its frontmatter, its prose (the claims fence removed, the page as it renders), and its
    claims as raw entries (the fence and the ledger folded)."""
    frontmatter: dict = field(default_factory=dict)
    prose: str = ""
    claims: list[dict] = field(default_factory=list)
    present: bool = True


def read_version(text: str | None, ledger: str | None = None) -> Version:
    if text is None:
        return Version(present=False)
    try:
        fm, _turns = markdown_parser.header_of(text)
    except Exception:  # noqa: BLE001 - a page that will not parse is read as having no header, never an error
        fm = {}
    split = markdown_parser.split_frontmatter(text)
    body = (split[1] if split is not None else text).strip()
    lines = [line for line in (ledger or "").split("\n") if line.strip()]
    if lines:
        body = claims_ledger.merged(body, lines)
    try:
        entries = claims_mod.loose_claim_entries(body) or []
    except Exception:  # noqa: BLE001
        entries = []
    prose = claims_mod.served_prose(body)[0]
    return Version(frontmatter=fm if isinstance(fm, dict) else {}, prose=prose, claims=entries)


def _fm_norm(value):
    return _norm(value)


def _alias_list(value) -> list[str]:
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else ([str(value)] if value else [])


def _source_refs(value) -> list[str]:
    return [str(s.get("ref")) for s in value if isinstance(s, dict) and s.get("ref")] if isinstance(value, list) else []


@dataclass
class OtherChange:
    """One frontmatter change a person reads. ``field`` is one of :data:`OTHER_FIELDS`; ``before``/``after`` for a
    scalar, ``added``/``removed`` for a list."""
    field: str
    before: str | None = None
    after: str | None = None
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def other_changes(old: dict, new: dict) -> tuple[list[OtherChange], int]:
    """The non-bookkeeping frontmatter changes in words-ready form, and how many further keys changed that the app has
    no sentence for (counted, never named)."""
    out: list[OtherChange] = []
    details = 0
    for key in sorted(set(old) | set(new)):
        if key in FM_NOT_SHOWN:
            continue
        b, a = old.get(key), new.get(key)
        if _fm_norm(b) == _fm_norm(a):
            continue
        if key in ("aliases", "tags"):
            bs, as_ = _alias_list(b), _alias_list(a)
            out.append(OtherChange(key, added=[x for x in as_ if x not in bs], removed=[x for x in bs if x not in as_]))
        elif key == "sources":
            bs, as_ = _source_refs(b), _source_refs(a)
            added, removed = [x for x in as_ if x not in bs], [x for x in bs if x not in as_]
            if added or removed:
                out.append(OtherChange(key, added=added, removed=removed))
            else:
                details += 1
        elif key in ("status", "name", "type", "decay_class"):
            out.append(OtherChange(key, before=None if b is None else str(b), after=None if a is None else str(a)))
        else:
            details += 1
    return out, details


@dataclass
class Delta:
    """Two versions of a page, compared."""
    withdrawn: list[dict] = field(default_factory=list)
    new: list[dict] = field(default_factory=list)
    changed: list[tuple[dict, dict, dict[str, tuple]]] = field(default_factory=list)   # (before, after, meaningful)
    faded: list[tuple[dict, dict]] = field(default_factory=list)
    other: list[OtherChange] = field(default_factory=list)
    details: int = 0
    prose_changed: bool = False
    status: tuple[str, str] | None = None
    fade_page: bool = False
    #: Conversations the page now names that it did not: a conversation fed it (the cause, not a sentence).
    fed: list[str] = field(default_factory=list)
    #: Conversations the page no longer names (a revision cascade, a merge): counted in ``details``, never a sentence.
    unfed: list[str] = field(default_factory=list)


def _prose_key(text: str) -> list[str]:
    return [line.rstrip() for line in (text or "").splitlines() if line.strip()]


def compare(old: Version, new: Version) -> Delta:
    """The full comparison the fast path summarises."""
    d = Delta()
    withdrawn, came, pairs = pair_claims(old.claims, new.claims)
    d.withdrawn, d.new = withdrawn, came
    for before, after in pairs:
        meaningful, faded = claim_diff(before, after)
        if meaningful:
            d.changed.append((before, after, {**meaningful, **({"confidence": faded["confidence"]}
                                                                 if "confidence" in faded else {})}))
        elif faded:
            d.faded.append((before, after))
    d.other, d.details = other_changes(old.frontmatter, new.frontmatter)
    before_eps = set(_sources(old.frontmatter))
    after_eps = set(_sources(new.frontmatter))
    d.fed = [e for e in _sources(new.frontmatter) if e not in before_eps]
    d.unfed = [e for e in _sources(old.frontmatter) if e not in after_eps]
    if d.unfed:
        d.details += 1   # a page that lost a conversation changed: the card counts it, no sentence
    d.prose_changed = _prose_key(old.prose) != _prose_key(new.prose)
    b_status, a_status = old.frontmatter.get("status"), new.frontmatter.get("status")
    _sub, fade, d.status = _status_verdict(None if b_status is None else str(b_status),
                                           None if a_status is None else str(a_status))
    d.fade_page = fade or any(k in FM_FADE and _fm_norm(old.frontmatter.get(k)) != _fm_norm(new.frontmatter.get(k))
                              for k in FM_FADE)
    if d.status is not None and {d.status[0], d.status[1]} <= {"active", "decaying"}:
        d.other = [o for o in d.other if o.field != "status"]
    return d


def _step_key(entry: dict) -> str:
    return str(entry.get("id") or "") or _canon(entry)


@dataclass
class _Track:
    first: dict | None      # the fact before the run's first change to it (``None``: the run made it)
    last: dict | None       # the fact after the run's last change to it (``None``: the run withdrew it)
    made: dict | None = None            # what the run first wrote, for a fact the run made and later withdrew
    step: tuple | None = None           # the first meaningful step ``(before, after, meaningful)``, for a fact put back


def _compose_facts(deltas: list[Delta], out: Delta) -> None:
    tracks: dict[str, _Track] = {}
    order: list[str] = []

    def track(key: str, first: dict | None) -> _Track:
        if key not in tracks:
            tracks[key] = _Track(first=first, last=first)
            order.append(key)
        return tracks[key]

    for d in deltas:
        for entry in d.new:
            k = _step_key(entry)
            t = tracks.get(k)
            if t is None:
                t = track(k, None)
                t.made = entry
            t.last = entry
        for entry in d.withdrawn:
            t = tracks.get(_step_key(entry))
            if t is None:
                track(_step_key(entry), entry).last = None
            else:
                t.last = None
        for before, after, meaningful in d.changed:
            t = track(_step_key(after), before)
            t.last = after
            if t.step is None:
                t.step = (before, after, meaningful)
        for before, after in d.faded:
            track(_step_key(after), before).last = after
    for k in order:
        t = tracks[k]
        if t.first is None and t.last is not None:
            out.new.append(t.last)
        elif t.first is None:                          # made and withdrawn inside the run: it did both
            out.new.append(t.made)
            out.withdrawn.append(t.made)
        elif t.last is None:
            out.withdrawn.append(t.first)
        else:
            meaningful, faded = claim_diff(t.first, t.last)
            if meaningful:
                out.changed.append((t.first, t.last, {**meaningful, **({"confidence": faded["confidence"]}
                                                                        if "confidence" in faded else {})}))
            elif faded:
                out.faded.append((t.first, t.last))
            elif t.step is not None:                   # changed and put back inside the run: the run did change it
                out.changed.append(t.step)


_SCALAR_FIELDS = frozenset({"status", "name", "type", "decay_class"})


def _compose_other(deltas: list[Delta]) -> list[OtherChange]:
    steps: dict[str, list[OtherChange]] = {}
    for d in deltas:
        for o in d.other:
            steps.setdefault(o.field, []).append(o)
    out: list[OtherChange] = []
    for name, rows in steps.items():
        if name in _SCALAR_FIELDS:
            net = OtherChange(name, before=rows[0].before, after=rows[-1].after)
            out.append(net if net.before != net.after else rows[0])
            continue
        added: list[str] = []
        removed: list[str] = []
        for o in rows:
            for x in o.added:
                if x in removed:
                    removed.remove(x)
                elif x not in added:
                    added.append(x)
            for x in o.removed:
                if x in added:
                    added.remove(x)
                elif x not in removed:
                    removed.append(x)
        out.append(OtherChange(name, added=added, removed=removed) if added or removed else rows[0])
    return out


def compose(deltas: list[Delta]) -> Delta:
    """One page's change across the commits of a run, from each commit's own :func:`compare` (oldest first) — never
    from the page's first and last versions, which would carry whatever another writer did in between. A fact the run
    changed and the run changed back, or made and withdrew, is still what the run did: it is listed, so a page a list
    calls updated never opens as nothing."""
    out = Delta()
    _compose_facts(deltas, out)
    out.other = _compose_other(deltas)
    out.details = sum(d.details for d in deltas)
    out.prose_changed = any(d.prose_changed for d in deltas)
    out.fed = list(dict.fromkeys(e for d in deltas for e in d.fed))
    out.unfed = list(dict.fromkeys(e for d in deltas for e in d.unfed))
    moves = [d.status for d in deltas if d.status is not None]
    if moves:
        out.status = (moves[0][0], moves[-1][1]) if moves[0][0] != moves[-1][1] else moves[0]
    out.fade_page = any(d.fade_page for d in deltas)
    return out


def _sources(fm: dict) -> list[str]:
    """The conversations a page's header says fed it (``source_episodes``, the last one merged too)."""
    ids = [str(e) for e in (fm.get("source_episodes") or []) if e]
    last = str(fm.get("source_episode") or "")
    return list(dict.fromkeys(ids + ([last] if last else [])))


def delta_verdict(d: Delta) -> Verdict:
    substance = bool(d.withdrawn or d.new or d.changed or d.other or d.details or d.prose_changed or d.fed or d.unfed)
    return Verdict(_kind(substance, bool(d.faded) or d.fade_page), d.status)


def classify(old_text: str | None, new_text: str | None, old_ledger: str | None = None,
             new_ledger: str | None = None) -> Verdict:
    """The verdict of a page whose two versions are in hand (the slow path of a commit's classification)."""
    return delta_verdict(compare(read_version(old_text, old_ledger), read_version(new_text, new_ledger)))


# --------------------------------------------------------------------------------------------------------------------
# Prose as blocks of the page's own markdown
# --------------------------------------------------------------------------------------------------------------------

BLOCK_CHARS = 2000
MAX_BLOCKS = 60
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])[ \t]+")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


@dataclass
class Block:
    text: str
    heading: str | None = None
    level: int = 0   # a heading block's own level; 0 for any other block


def blocks_of(prose: str) -> list[Block]:
    """The prose as blocks: a heading, a paragraph, one top-level list item with its continuation, a code fence. Each
    carries the heading it sits under."""
    out: list[Block] = []
    heading: str | None = None
    current: list[str] = []
    fence: str | None = None

    def flush() -> None:
        if current:
            out.append(Block("\n".join(current).strip("\n"), heading))
            current.clear()

    for line in (prose or "").split("\n"):
        line = line.rstrip("\r")
        marker = _FENCE.match(line)
        if fence is not None:
            current.append(line)
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) \
                    and not line.strip().lstrip(fence[0]):
                fence = None
                flush()
            continue
        if marker:
            flush()
            fence = marker.group(1)
            current.append(line)
            continue
        if not line.strip():
            flush()
            continue
        m = _HEADING.match(line)
        if m:
            flush()
            heading = m.group(2).strip()
            out.append(Block(line.strip(), heading, len(m.group(1))))
            continue
        if _ITEM.match(line) and not line.startswith((" ", "\t")):
            flush()
        current.append(line)
    flush()
    return out


_TOKEN = re.compile(r"\[\[[^\]]*\]\]|\[[^\]]*\]\([^)]*\)|\s+|[\w'\u2019-]+|[^\w\s]")


def segments(before: str, after: str) -> list[dict]:
    """The words that changed inside one paragraph: ``[{op: equal|added|removed, text}]``. A link (``[text](url)``,
    ``[[page]]``) is one token, so it is never cut in two; the concatenation of ``equal`` and ``removed`` reads as the
    old paragraph, ``equal`` and ``added`` as the new."""
    a, b = _TOKEN.findall(before), _TOKEN.findall(after)
    out: list[dict] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"op": "equal", "text": "".join(a[i1:i2])})
            continue
        if i2 > i1:
            out.append({"op": "removed", "text": "".join(a[i1:i2])})
        if j2 > j1:
            out.append({"op": "added", "text": "".join(b[j1:j2])})
    merged: list[dict] = []
    for seg in out:
        if merged and merged[-1]["op"] == seg["op"]:
            merged[-1]["text"] += seg["text"]
        else:
            merged.append(dict(seg))
    return merged


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()


def _clip(text: str) -> tuple[str, bool]:
    return (text, False) if len(text) <= BLOCK_CHARS else (text[:BLOCK_CHARS].rstrip() + "…", True)


def prose_blocks(old_prose: str, new_prose: str) -> dict:
    """What changed in the prose, as ``{blocks, counts, truncated}`` in the page's own order. A block is ``{op:
    added|removed|edited|context, markdown, before, after, segments, heading, level}``: ``markdown`` is the block as the
    page writes it (``context`` is one unchanged block either side of a change, so it reads in place), ``edited`` has
    ``before``/``after`` and the inline ``segments``. Bounded by :data:`MAX_BLOCKS` changed blocks and
    :data:`BLOCK_CHARS` a block; ``truncated`` says when either cut."""
    old, new = blocks_of(old_prose), blocks_of(new_prose)
    ot, nt = [b.text for b in old], [b.text for b in new]
    rows: list[dict] = []   # every row of the new page's order, change or equal; `equal` rows are thinned after

    def row(op: str, block: Block, **more) -> dict:
        r = {"op": op, "markdown": block.text, "heading": block.heading if block.level == 0 else None,
             "level": block.level, **more}
        return r

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ot, nt, autojunk=False).get_opcodes():
        if tag == "equal":
            rows.extend(row("equal", new[j]) for j in range(j1, j2))
            continue
        o, n = list(range(i1, i2)), list(range(j1, j2))
        at = 0
        for i in o:
            best, score = None, 0.0
            for k in range(at, len(n)):
                r = _similar(old[i].text, new[n[k]].text)
                if r > score:
                    best, score = k, r
            if best is not None and score >= 0.5 and old[i].level == new[n[best]].level:
                for k in range(at, best):
                    rows.append(row("added", new[n[k]]))
                nb = new[n[best]]
                rows.append(row("edited", nb, before=old[i].text, after=nb.text,
                                segments=segments(old[i].text, nb.text)))
                at = best + 1
            else:
                rows.append(row("removed", old[i]))
        for k in range(at, len(n)):
            rows.append(row("added", new[n[k]]))
    # Thin the equal rows to one either side of a change; a heading is context only when it is that neighbour.
    keep = [r["op"] != "equal" for r in rows]
    for i, r in enumerate(rows):
        if r["op"] != "equal":
            for j in (i - 1, i + 1):
                if 0 <= j < len(rows) and rows[j]["op"] == "equal":
                    keep[j] = True
    out: list[dict] = []
    counts = {"added": 0, "removed": 0, "edited": 0}
    truncated = False
    changed_seen = 0
    for i, r in enumerate(rows):
        if not keep[i]:
            continue
        if r["op"] == "equal":
            r = {**r, "op": "context"}
        else:
            counts[r["op"]] += 1
            changed_seen += 1
            if changed_seen > MAX_BLOCKS:
                truncated = True
                continue
        for key in ("markdown", "before", "after"):
            if key in r:
                r[key], cut = _clip(r[key])
                truncated = truncated or cut
        r.setdefault("before", None)
        r.setdefault("after", None)
        r.setdefault("segments", [])
        out.append(r)
    return {"blocks": out, "counts": counts, "truncated": truncated}
