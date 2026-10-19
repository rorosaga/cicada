"""Sleep tends the inbox (ruling 29, owner 2026-10-17; amends G21 and G113).

The owner, 2026-10-17: "a single consolidation also should take care of cleaning up the inbox. … sleep would also
take into account the inbox so that, as conversations come through, questions get answered. There are also many
things that maybe can be assumed, like they don't have to be explicit … There are little things that are honestly
not that big of a deal."

Two moves, one writer.

**1 — Answered in conversation** (:func:`conversation_pass`). For each open question whose subject a batch's
conversations touched (the ask gate's own relevance rule, ``inbox_ask_gate.relevant``, over the person's turns only),
the engine reads the person's lines about it and says whether their own words already answer it, copying the words.
The words must be found, exactly (``evidence.verify``: exact → whitespace → case, never fuzzy), in one of the person's
own turns (``kind: user``) — or nothing is settled. The conversation that raised a question never answers it (its
words are already the question's cause or one option's evidence).

**2 — Small stuff is assumed** (:func:`policy`). Engine-free rules, plus one bounded judge for duplicate pages
(the full table is in ``docs/architecture/features.md``, "Settled by Sleep"):

* any kind but a proposed edit — what it asks about is gone (merged away, archived, dropped): retired;
* ``merge_suggestion`` — the same name once spelling is folded, same type, not a person: merged; else the judge reads
  both pages: ``same`` ≥ 0.9 merges, ``different`` ≥ 0.9 keeps the pair apart; unsure stays;
* ``normalization`` — the two labels differ only in spelling (case, separators, a plural): "Correct fold";
* ``decay`` — a one-off nobody would miss (a concept, tool, media or company page on one conversation, never kept, no
  words of the person's on it): archived;
* ``conflict`` — the newest dated statement settles it (single-valued, one option said strictly later than every
  other, never a machine claim over the person's own);
* ``conflict`` / ``clarification`` about Cicada's OWN runtime settings, on its own page — which engine Sleep runs read
  with, whether scheduled runs use the plan, the schedule's time (``web_settle.own_settings``; owner 2026-10-19) — retired as ``own_settings`` (no claim touched): the system
  knows them and Settings shows them, so they are never asked;
* everything else — a clarification, a follow-up, a proposed edit — stays for the person (move 1 aside).

Never a question about who a person is, or merging two people, without the person's own words on the record (move 1).

**3 — Answered already, anywhere in the record** (:func:`read_record_answer`, part 2, 2026-10-17). A clarification,
a follow-up or a conflict still open after moves 1 and 2 is looked for across the whole bank, not just the batch: the
conversations the subject's page points at (its claims' evidence and ``source_episodes`` — the pointers Ask's source
words follow) plus the bank's conversations that name it (the lexical index, every spelling of the page). Only the
person's own turns that name the subject reach the engine, each tagged with its conversation; the answer settles
only on the person's words located exactly in that conversation's own turn (``kind: user`` span, never fuzzy,
never an agent's words), recorded as the evidence. A conflict is answered only by words said after every side of it,
a follow-up only by words said after its thread was last heard. Inside Sleep a few questions per drain
(:data:`RECORD_CAP`); in the tidy only with ``judge=true``, every eligible question.

**Label-only conflicts** (an older format: every option a label, no ``claim_id``) are judged too: each label is tied
to the page's open claims by folded text (:func:`label_matches` — no model, never fuzzy), and the judge reads the
labels with those claims and their evidence lines. A side with nothing on the record is never picked, and the
owner's-words rail (:func:`may_close`) holds over the tied claims.

**Part 3 (2026-10-17): passing names and label conflicts.** A clarification about a name with no page, said in one
conversation and only in passing there, with nothing tying it to the person's life, closes as mentioned in passing
(:func:`passing_rule`, ``in_passing``: the person's own dismiss, nothing written about who it is). A label-only
conflict is settled by the person's newest plain statement of one side (:func:`newest_words`, ``newest_words``,
engine-free, located exactly in their own turn, dated that day); when that is not mechanical the conflict judge reads
the same lines (:func:`label_lines`) and may rest its pick on one under the same guards.

**One writer.** A settle goes through ``inbox_service``'s own resolver — the one the person's answer uses — with
``inbox_actor`` saying Sleep answered: the commit is Sleep's (``Inbox settled by Sleep``, trigger
``inbox/<kind>/settled:<label>``, the judging model or ``cicada`` as author), the G113 ledger row says ``by: sleep``
and its rule, and the settle's record (``inbox/settled/<id>.md``, ``settled.group: sleep``) rides in that same commit.
:func:`undo` takes back exactly that commit — the reverse of its diff, applied three-way onto each file as it is now,
refused whole if anything since conflicts with it — and puts the question back, marked so Sleep never settles it
again (user authority).
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from loguru import logger

from api.services import bank_index, inbox_actor, inbox_questions, markdown_parser, text_fold

GROUP = "sleep"
SETTLED_DIR = "settled"
#: The restored question remembers the person took Sleep's answer back: Sleep never settles it again.
UNDONE_KEY = "sleep_settle"
STAGE = "inbox_tend"
TRIGGER = "sleep/inbox-tend"

#: The rules, and the words the Inbox shows for each ("Settled by Sleep").
RULES: dict[str, str] = {
    "said_in_conversation": "You answered this in a conversation",
    "subject_gone": "What it asked about is no longer in your memory",
    "same_spelling": "The same name, spelled differently",
    "judged_same": "Both pages describe the same thing",
    "judged_different": "The two pages describe different things",
    "spelling_fold": "The two labels differ only in spelling",
    "one_off": "Mentioned once and nothing else rests on it",
    "newest_evidence": "Your newest dated statement settles it",
    "multi_valued": "Both can be true at once: every value was already kept",
    "judged_conflict": "The record clearly supports one answer",
    "judged_fold": "The two labels mean the same thing",
    "judged_archive": "Nothing suggests it is still live",
    "judged_keep": "It is still live",
    "said_on_record": "You already said this in an earlier conversation",
    "in_passing": "Mentioned once in passing; nothing ties it to your life",
    "newest_words": "Your newest words on it say this",
    "own_settings": "About Cicada's own settings, which Cicada already knows: Settings shows them",
}
#: The rules that read only the bank: re-run inside each settle, which goes ahead only when they still agree.
ENGINE_FREE = frozenset({"subject_gone", "same_spelling", "spelling_fold", "one_off", "newest_evidence",
                         "multi_valued", "in_passing", "newest_words", "own_settings"})
#: The judged kinds (owner, 2026-10-17: the inbox keeps only what genuinely needs the person).
JUDGED_KINDS = frozenset({"merge_suggestion", "conflict", "normalization", "decay"})
MAX_REASON_CHARS = 160
MAX_EVIDENCE_LINES = 2
#: Kinds the person's words in a conversation may answer (decay is answered by the mention itself; a fold and a
#: proposed edit are the app's; a follow-up is progress, written only by `progress.py`).
CONVERSATION_KINDS = frozenset({"conflict", "clarification", "merge_suggestion"})
NEVER = frozenset({"page_edit"})
#: The page types a decay question may be assumed for ("pages nobody would miss").
ONE_OFF_TYPES = frozenset({"concept", "tool", "media", "company"})
JUDGE_THRESHOLD = 0.9
#: Per batch: how many touched questions the engine reads, and how many duplicate pairs the judge reads.
CONVERSATION_CAP = 8
JUDGE_CAP = 6
MAX_LINES = 6
MAX_LINE_CHARS = 400
MAX_PAGE_CHARS = 2000
MAX_ANSWER_CHARS = 120
_GENERIC_KEYS = frozenset({"both", "neither", "other", "remind_later"})
#: Move 3: the kinds the whole record may answer, and how many questions one drain searches it for (the tidy with
#: ``judge=true``: every one).
RECORD_KINDS = frozenset({"clarification", "followup", "conflict"})
RECORD_CAP = 4
#: Move 3's reading: at most this many conversations, the person's lines in each, and all lines in one prompt.
MAX_RECORD_EPISODES = 6
MAX_RECORD_LINES_PER_EPISODE = 2
MAX_RECORD_LINES = 8
#: Per spelling of the subject, how many conversations the lexical index is asked for.
RECORD_SEARCH_PER_NAME = 8
#: The follow-up answers Sleep may take from the person's words: never "that didn't happen" (a withdrawal) and never
#: a moved date — those stay the person's to give.
FOLLOWUP_KEYS = {"happened": ("done", "still", "stopped"), "milestone": ("done", "missed", "dropped"),
                 "due": ("done", "missed", "dropped")}
#: Why move 2 left a question that move 3 may still answer: everything but the person's own hold on it.
_RECORD_SKIP = frozenset({"undone", "deferred", "person_only"})


class NotUndoable(ValueError):
    """The settle cannot be taken back as asked; the reason is said in words and nothing was written."""


@dataclass
class Decision:
    item_id: str
    kind: str
    rule: str
    #: The resolver call: ``{"action": ..., "option_key": ..., "merge_target": ..., "answer": ...}``; ``None`` retires
    #: the question without a resolver, touching nothing else (its subject is gone, or it is Cicada's own settings).
    request: dict | None
    #: What Sleep answered, in words, for the settled list.
    answer: str = ""
    #: The person's own words, ``{"episode", "quote"}`` (move 1 only).
    quote: dict | None = None
    model: str | None = None
    #: The item file's bytes when it was decided: a question changed since is left alone.
    fingerprint: bytes = b""
    #: ``{memory-relative path: sha256}`` of every page the decision read: a page changed since (another
    #: conversation, the person's edit, a Sleep batch) leaves the question for the next look, never settled on a stale
    #: read. ``None`` for a missing page.
    guard: dict = field(default_factory=dict)
    #: The judge's one-line reason, shown in "Settled by Sleep" (the rule's own words otherwise).
    reason: str = ""


@dataclass
class Report:
    settled: int = 0
    asked: int = 0
    judged: int = 0
    read: int = 0
    by_kind: dict[str, dict[str, int]] = field(default_factory=dict)
    stopped: str | None = None
    engine: str | None = None

    def count(self, kind: str, outcome: str) -> None:
        row = self.by_kind.setdefault(kind or "unknown", {})
        row[outcome] = row.get(outcome, 0) + 1

    def as_dict(self) -> dict:
        out = {"settled": self.settled, "asked": self.asked, "judged": self.judged, "read": self.read,
               "by_kind": {k: dict(sorted(v.items())) for k, v in sorted(self.by_kind.items())}}
        if self.stopped:
            out["stopped"] = self.stopped
        if self.engine:
            out["engine"] = self.engine
        return out


# --------------------------------------------------------------------------- reading the inbox


def _inbox(memory_path: Path) -> Path:
    return Path(memory_path) / "inbox"


def pending(memory_path: Path) -> list[tuple[Path, dict, str]]:
    """Every open question on disk, ``(path, frontmatter, body)``, by id. Unreadable files are skipped."""
    out = []
    for path in sorted(_inbox(memory_path).glob("inbox-*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — an unreadable question is never settled
            continue
        out.append((path, dict(parsed.frontmatter), parsed.body))
    return out


def _page(memory_path: Path, entity_id: str) -> tuple[Path, dict, str] | None:
    from api.services.id_utils import resolve_entity_file

    if not entity_id:
        return None
    path = resolve_entity_file(Path(memory_path), entity_id)
    if path is None:
        return None
    try:
        parsed = markdown_parser.parse(path)
    except Exception:  # noqa: BLE001
        return None
    return path, dict(parsed.frontmatter), parsed.body


def _type_of(fm: dict | None, fallback: str = "") -> str:
    raw = str((fm or {}).get("type") or fallback or "").strip().lower()
    return raw.split(" ")[0].split("—")[0].strip()


def _fold_name(text) -> str:
    return " ".join(text_fold.words(str(text or "")))


def _names(fm: dict) -> set[str]:
    out = {_fold_name(fm.get("name"))}
    out |= {_fold_name(a) for a in (fm.get("aliases") or [])}
    return {n for n in out if n}


def _blocked(fm: dict, today: str) -> str | None:
    """Why Sleep never touches this question: the person took a settle back, or put it off."""
    if str(fm.get(UNDONE_KEY) or "") == "undone" or str(fm.get("web_check") or "") == "undone":
        return "undone"
    if inbox_questions.is_deferred(fm, today):
        return "deferred"
    kind = str(fm.get("kind") or "")
    if kind in NEVER:
        return "person_only"
    return None


def _gone(memory_path: Path, fm: dict) -> bool:
    from api.services import inbox_service

    kind = str(fm.get("kind") or "")
    anchor = inbox_service._fold_anchor(memory_path, fm)
    return inbox_service._subject_gone(memory_path, anchor, inbox_service._hiding_kind(kind, fm.get("asks")))


#: The kinds only ever raised FROM an existing page: their page missing means the question is dead (G98). A
#: clarification may be about a page not made yet; a fold is anchored on any live covered page (``_fold_anchor``); a
#: duplicate's mention may have no page.
_PAGE_BOUND = frozenset({"conflict", "decay", "followup"})


def _page_state(memory_path: Path, fm: dict) -> str:
    """``ok`` | ``missing`` | ``unreadable`` for the page a page-bound question asks about (``ok`` for other kinds).
    ``missing`` also covers a name that resolves to no file on disk; ``unreadable`` is a page that is there and cannot
    be parsed — never read as gone."""
    from api.services.id_utils import resolve_entity_file

    entity_id = str(fm.get("entity_id") or "").strip()
    if str(fm.get("kind") or "") not in _PAGE_BOUND or not entity_id:
        return "ok"
    path = resolve_entity_file(Path(memory_path), entity_id)
    if path is None or not path.is_file():
        return "missing"
    try:
        markdown_parser.parse(path)
    except Exception:  # noqa: BLE001
        return "unreadable"
    return "ok"


def _hash(path: Path) -> str | None:
    import hashlib

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _guard(memory_path: Path, *entity_ids: str) -> dict:
    """The pages a decision read, as content hashes (``entities/<id>.md`` and its ledger when it has one)."""
    out: dict = {}
    for eid in entity_ids:
        if not eid:
            continue
        page = _page(memory_path, eid)
        rel_path = page[0] if page is not None else Path(memory_path) / "entities" / f"{eid}.md"
        rel = rel_path.relative_to(memory_path).as_posix()
        out[rel] = _hash(rel_path)
        ledger = rel_path.with_name(f"{rel_path.stem}.claims.jsonl")
        if ledger.exists():
            out[ledger.relative_to(memory_path).as_posix()] = _hash(ledger)
    return out


def guard_holds(memory_path: Path, d: "Decision") -> bool:
    return all(_hash(Path(memory_path) / rel) == digest for rel, digest in (d.guard or {}).items())


def _is_owner_page(fm: dict | None) -> bool:
    return bool((fm or {}).get("owner"))


# --------------------------------------------------------------------------- the policy (engine-free)


def _merge_rule(memory_path: Path, item_id: str, fm: dict) -> tuple[Decision | None, str]:
    target_id = str(fm.get("merge_target_hint") or "").strip()
    target = _page(memory_path, target_id)
    if target is None:
        return None, "no_target"
    mention = _page(memory_path, str(fm.get("entity_id") or ""))
    mention_fm = mention[1] if mention else {}
    mention_type = _type_of(mention_fm, str(fm.get("suggested_classification") or ""))
    target_type = _type_of(target[1])
    if "person" in (mention_type, target_type):
        return None, "person"     # who someone is: only the person's own words settle it (move 1)
    if mention is not None and mention[0] == target[0]:
        return None, "same_page"
    if mention_type and target_type and mention_type != target_type:
        return None, "judgement"
    name = _fold_name(fm.get("entity_name") or fm.get("entity_mention") or mention_fm.get("name"))
    if name and name in _names(target[1]):
        return Decision(item_id, "merge_suggestion", "same_spelling",
                        {"action": "merge", "merge_target": target[0].stem},
                        answer=f"Same as {target[1].get('name') or target[0].stem}",
                        guard=_guard(memory_path, str(fm.get("entity_id") or ""), target[0].stem)), ""
    return None, "needs_judge"


def _spelling(label: str) -> str:
    from api.services import predicates

    s = re.sub(r"[^a-z0-9]", "", predicates._slugify_predicate(label))
    return s.removesuffix("s")


def _normalization_rule(item_id: str, fm: dict) -> tuple[Decision | None, str]:
    raw = str(fm.get("raw_predicate") or "")
    canonical = str(fm.get("canonical_predicate") or "")
    if not raw or not canonical:
        return None, "judgement"
    if _spelling(raw) and _spelling(raw) == _spelling(canonical):
        return Decision(item_id, "normalization", "spelling_fold", {"action": "resolve", "option_key": "0"},
                        answer=f"{raw} is {canonical}"), ""
    return None, "needs_judge"   # the judge folds only a same meaning; a changed meaning stays


def _decay_rule(memory_path: Path, item_id: str, fm: dict) -> tuple[Decision | None, str]:
    from api.services import decay_policy
    from api.services.claims import MalformedClaimsBlockError, parse_claims

    page = _page(memory_path, str(fm.get("entity_id") or ""))
    if page is None:
        return None, "judgement"
    _path, pfm, body = page
    if _type_of(pfm) not in ONE_OFF_TYPES or _is_owner_page(pfm):
        return None, "judgement"   # the person's projects, skills, people and places stay theirs
    cls, _rate = decay_policy.resolve(pfm)
    if cls.value == "evergreen":
        return None, "judgement"
    try:
        claims = parse_claims(body, strict=True)
    except MalformedClaimsBlockError:
        return None, "judgement"
    if (cls.value == "durable" or decay_policy.conversations(pfm.get("source_episodes")) > 1
            or decay_policy.kept_dates(pfm) or any(persons_words(c) for c in claims)):
        return None, "needs_judge"   # the judge reads the page and its last mentions: still live?
    return Decision(item_id, "decay", "one_off", {"action": "archive"}, answer="Archived",
                    guard=_guard(memory_path, _path.stem)), ""


def persons_words(claim) -> bool:
    """Does the claim rest on the person's own words — their inbox answer (``is_human``), or a span in one of their
    own turns (evidence kind ``user``)? Such a claim is closed only by another that does too (review 2026-10-17)."""
    from api.services.claim_reconciler import is_human

    return is_human(claim) or any(getattr(ev, "kind", "") == "user" and ev.is_span() for ev in claim.evidence or [])


def may_close(winner, losers) -> bool:
    """The owner's-words rail: the winner may close the others only when no loser rests on the person's own words,
    or the winner does too, or it is a tracked source's dated re-check (ruling 26: the newest evidence wins)."""
    from api.services import source_refresh

    if persons_words(winner) or str(winner.origin or "") == source_refresh.ORIGIN:
        return True
    return not any(persons_words(c) for c in losers)


def _said(claim) -> str:
    """The latest day a claim was said: its evidence's conversations and its own ``valid_from``."""
    from api.services import episode_ids

    days = [str(claim.valid_from or "")[:10]]
    for ev in claim.evidence or []:
        parsed = episode_ids.parse_episode_id(str(getattr(ev, "episode", "") or ""))
        if parsed is not None:
            days.append(str(parsed[0]))
    return max((d for d in days if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)), default="")


def _phrase_in(needle: str, hay: str) -> bool:
    return bool(needle) and f" {needle} " in f" {hay} "


#: A label carrying one of these says the opposite of the value it names ("No longer on alpha-os"): it ties to a
#: claim only by equality, never by the value appearing inside it.
_NEGATIONS = frozenset("""no not never nor without anymore longer former formerly ex stopped quit left isn doesn didn
wasn weren aren don won hasn haven hadn nunca sin ya""".split())


def label_matches(label: str, claim) -> bool:
    """Is a label-only option about this claim? Matched on folded text (``text_fold.words``: case, accents and
    punctuation folded, whole words) — never fuzzy, no model: the label equals the claim's object or its sentence; or
    the claim's object (four characters or more) is a whole-word run inside the label ("Runs on alpha-os" ↔ object
    ``alpha-os``); or the label (two words or more) is a whole-word run inside the claim's sentence."""
    lab = _fold_name(label)
    if not lab:
        return False
    obj, txt = _fold_name(getattr(claim, "object", "")), _fold_name(getattr(claim, "text", ""))
    if lab in (obj, txt):
        return True
    if set(lab.split()) & _NEGATIONS:
        return False   # "No longer on alpha-os" is not the claim that it runs on alpha-os
    if len(obj) >= 4 and _phrase_in(obj, lab):
        return True
    return len(lab.split()) >= 2 and _phrase_in(lab, txt)


def label_claims(options: list[dict], claims: list, predicate: str = "") -> dict[str, list]:
    """``{option key: [open claims its label is tied to]}`` for a label-only conflict. Only open, non-event claims;
    on the conflict's own predicate unless it is the entity path's literal ``description`` (that path compares whole
    pages, so its labels may be about any belief on it). A claim tied to two labels supports neither."""
    from api.services.claims import is_event

    live = [c for c in claims if c.valid_to is None and not c.superseded_by and not is_event(c)]
    if predicate and predicate != "description":
        live = [c for c in live if c.predicate == predicate]
    tied = {str(o.get("key")): [c for c in live if label_matches(str(o.get("label") or ""), c)] for o in options}
    seen: dict[str, int] = {}
    for found in tied.values():
        for c in found:
            seen[c.id] = seen.get(c.id, 0) + 1
    return {key: [c for c in found if seen[c.id] == 1] for key, found in tied.items()}


def _conflict_rule(memory_path: Path, item_id: str, fm: dict) -> tuple[Decision | None, str]:
    from api.services import predicates
    from api.services.claims import MalformedClaimsBlockError, is_event, parse_claims

    predicate = str(fm.get("predicate") or "description")
    page = _page(memory_path, str(fm.get("entity_id") or ""))
    if page is None:
        return None, "judgement"
    if predicates.cardinality(memory_path, predicate) == "multi":
        # G98: a set, not a contradiction — Stage 3 already kept every value open; the question asks for a winner
        # that does not exist. The resolver's own "informational" dismiss closes nothing.
        return Decision(item_id, "conflict", "multi_valued", {"action": "dismiss"}, answer="Kept every value",
                        guard=_guard(memory_path, page[0].stem)), ""
    if _is_owner_page(page[1]) or (_type_of(page[1]) == "person"
                                   and predicate in ("is-a", "type", "kind", "name", "description")):
        return None, "person"
    try:
        claims = {c.id: c for c in parse_claims(page[2], strict=True)}
    except MalformedClaimsBlockError:
        return None, "judgement"
    options = [o for o in inbox_questions.normalize_options(fm.get("options"))
               if str(o.get("key")) not in _GENERIC_KEYS]
    if len(options) >= 2 and not any(o.get("claim_id") for o in options):
        # An older format: labels only. The person's newest words on it settle it when they are mechanical (part 3);
        # otherwise only the judge reads it, and only when a label is tied to the record or the person's lines say one.
        guard = _guard(memory_path, page[0].stem)   # what the read rests on, as read
        tied = label_claims(options, list(claims.values()), predicate)
        lines = label_lines(memory_path, fm, options)
        d, why = newest_words(memory_path, item_id, options, tied, lines)
        if d is not None:
            d.guard = guard
            return d, ""
        if any(tied.values()) or why == "needs_judge":
            return None, "needs_judge"
        return None, "labels_not_on_record"
    picked = []
    for o in options:
        claim = claims.get(str(o.get("claim_id") or ""))
        if claim is None or claim.valid_to is not None or is_event(claim):
            return None, "judgement"
        picked.append((o, claim, _said(claim)))
    if len(picked) < 2:
        return None, "judgement"
    if any(not said for _, _, said in picked):
        return None, "needs_judge"
    picked.sort(key=lambda row: row[2], reverse=True)
    newest, rest = picked[0], picked[1:]
    if any(said >= newest[2] for _, _, said in rest):
        return None, "needs_judge"
    if not may_close(newest[1], [c for _, c, _ in rest]):
        return None, "needs_judge"    # the judge may still keep the person's own words; nothing closes them
    return Decision(item_id, "conflict", "newest_evidence",
                    {"action": "resolve", "option_key": str(newest[0].get("key"))},
                    answer=str(newest[0].get("label") or ""), guard=_guard(memory_path, page[0].stem)), ""


def policy(memory_path: Path, path: Path, fm: dict, *, today: str | None = None) -> tuple[Decision | None, str]:
    """The engine-free rule for one open question: ``(decision, "")`` or ``(None, why it stays)``. ``needs_judge``
    means a duplicate pair only the judge can read."""
    today = today or date.today().isoformat()
    item_id, kind = path.stem, str(fm.get("kind") or "")
    blocked = _blocked(fm, today)
    if blocked:
        return None, blocked
    page_state = _page_state(memory_path, fm)
    if page_state == "missing" or _gone(memory_path, fm):
        return Decision(item_id, kind, "subject_gone", None, answer="Retired",
                        guard=_guard(memory_path, str(fm.get("entity_id") or ""))), ""
    if page_state == "unreadable":
        return None, "unreadable_page"   # never retired on a read error: the person (or a repair) looks at it
    if kind in ("conflict", "clarification"):
        from api.services import web_settle

        if web_settle.own_settings(fm):
            # Owner 2026-10-19: Cicada's own engine, schedule or plan switch is the system's to know — never asked.
            # Retired like a question whose subject is gone: moved to its record, no claim touched, one Sleep commit.
            return Decision(item_id, kind, "own_settings", None, answer="Cicada's own settings",
                            guard=_guard(memory_path, str(fm.get("entity_id") or ""))), ""
    if kind == "merge_suggestion":
        return _merge_rule(memory_path, item_id, fm)
    if kind == "normalization":
        return _normalization_rule(item_id, fm)
    if kind == "decay":
        return _decay_rule(memory_path, item_id, fm)
    if kind == "conflict":
        return _conflict_rule(memory_path, item_id, fm)
    if kind == "clarification":
        return passing_rule(memory_path, item_id, fm)
    return None, "needs_person"


# --------------------------------------------------------------------------- part 3: names said in passing


#: Part 3 (owner, 2026-10-17: "little things that are honestly not that big of a deal"). "Who or what is <name>?"
#: about a name with no page, said in ONE conversation and only in passing there — at most this many of its exchanges
#: name it (`promotion.exchanges`, the promotion rule's own unit; more than three would have made a page) — closes as
#: mentioned in passing: nothing is written about who or what it is, the name stays where it was (the index, the
#: pending store), and a later conversation that names it again may raise the question anew.
PASSING_EXCHANGES = 2
#: The person's own things whenever they come up: never assumed in passing.
_OWN_TYPES = frozenset({"project", "skill", "deadline"})
#: A person (or a name of no type) said in any of the person's own turns is never assumed in passing: their words
#: about someone mean that someone may be in their life (review B1: "Alice Example came over yesterday. She is my
#: sister.", "Hablé con Alice Example ayer", "Talked to Alice Example today" — a pronoun dropped, a relation one
#: sentence away). Only a person named in an agent's text, or in a document's metadata, may be.
_PERSON_LIKE = frozenset({"person", ""})
#: A company or a place: the relation and first-person checks read the whole turn that names it and the turns beside
#: it, never only the name's own sentence.
_TURN_CHECKED = frozenset({"company", "location"})
#: First-person words, and the Spanish verb forms that carry the person without a pronoun ("tengo cena en …").
_FIRST_PERSON = frozenset("""i me my mine myself we us our ours ourselves yo mi mis conmigo nosotros nosotras nuestro
nuestra nuestros nuestras tengo voy fui estoy estuve hable trabajo trabaje vivo vivi quiero necesito hice tuve sali
comi llegue visite conoci vamos fuimos estamos tenemos""".split())
#: Relation words beyond `role_people.ROLE_WORDS` (which names one relation each): a group of the person's, and the
#: relations the role list does not name (review B1: "your teammate …").
_GROUP_RELATIONS = frozenset("""family familia parents padres relative relatives pariente parientes in-laws
suegro suegra teammate bandmate labmate officemate cofounder buddy pal mate bro sis bestie partner coworker colleague
boss roommate client intern stepbrother stepsister grandparent fiance girlfriend boyfriend colega socio socia
companero companera jefe jefa novio novia amigo amiga primo prima tio tia cunado cunada sobrino sobrina nieto nieta
vecino vecina compa pareja""".split())
#: Episodes the lexical index is asked for, per spelling, to tell one conversation from several.
PASSING_SEARCH = 8


def _relation_words() -> frozenset[str]:
    from api.services import role_people, text_fold

    out = set()
    for word in role_people.ROLE_WORDS | _GROUP_RELATIONS:
        folded = text_fold.words(word)
        if len(folded) == 1:
            out.add(folded[0])
    return frozenset(out)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def _words(text: str) -> list[str]:
    from api.services import text_fold

    return text_fold.words(text)


#: A relation counts only when it is someone's (review, 2026-10-17: "a decades-old family spot" is no relation): a
#: possessive right before it, or one word before ("my older sister", "your teammate", "con mi primo", "X is my …").
_POSSESSIVES = frozenset("""my your our his her their mi mis tu tus su sus nuestro nuestra nuestros nuestras vuestro
vuestra vuestros vuestras""".split())
#: What a saved page carries that is no one's words: links, and its metadata lines (``url: …``, ``folder: …``).
_URL = re.compile(r"(?i)\b(?:https?://|www\.)\S+")
_META_LINE = re.compile(r"(?im)^\s*(?:url|link|links|folder|origin|source|saved|saved_at|added|date|tags?|domain|site|"
                        r"query|search|channel|playlist|id|guid|feed|visited|visit_count|author|byline)\s*:.*$")


def _prose(text: str) -> str:
    """Words someone wrote: links and metadata lines dropped (review: ``…&client=safari`` is no client)."""
    return _URL.sub(" ", _META_LINE.sub(" ", text or ""))


def _relation_in(text: str, own: set[str]) -> bool:
    """A relation word tied to someone by a possessive (right before it, or one word before) — never one of the
    name's own words ("Example Teacher" is no teacher), never a link or a metadata line."""
    rel = _relation_words()
    words = _words(_prose(text))
    for i, w in enumerate(words):
        if w in own or not (w in rel or (w.endswith("s") and w[:-1] in rel)):
            continue
        if (i >= 1 and words[i - 1] in _POSSESSIVES) or (i >= 2 and words[i - 2] in _POSSESSIVES):
            return True
    return False


def _about_self(text: str) -> bool:
    return bool(set(_words(_prose(text))) & _FIRST_PERSON)


#: Where something saved comes from (a bookmark, a saved post, a feed, a watch or web history, a read page): its text
#: is the page's, not the person's — a name in its title, link or byline is never "their own words".
_SAVED_ORIGINS = frozenset({"bookmark", "saved-link", "media", "rss", "pdf", "ingest", "watch-history",
                            "video-watch", "page-read", "profile-read", "web-check", "source-check", "web-history",
                            "safari-tab", "chrome-tab-group", "tab-group"})
_SAVED_SUFFIXES = ("-bookmark", "-bookmarks", "-saved", "-history", "-likes", "-playlist", "-tab", "-tabs")


def _saved_item(ep_fm: dict, spans) -> bool:
    """A saved item, not a conversation: no turn marker anywhere (nothing a person typed as a turn), and it came
    from a saving door (its origin or source) or carries the page's ``url``."""
    if any(getattr(t, "marker", None) is not None for t in spans):
        return False
    from api.services import source_overview

    saved = set(_SAVED_ORIGINS)
    saved |= {o for spec in source_overview.CATALOG if spec.kind in ("browser", "social", "feed") for o in spec.origins}
    tags = {str(ep_fm.get(k) or "").strip().lower() for k in ("origin", "source")} - {""}
    return bool(ep_fm.get("url")) or any(t in saved or t.endswith(_SAVED_SUFFIXES) for t in tags)


_CODE_SHAPE = re.compile(r"\w_\w|::|\(\)|->|^[$@]\w|^--?\w|^`.+`$")


def code_identifier(name: str) -> bool:
    """A name shaped like code — one token with an underscore, ``::``, ``()``, ``->``, a sigil or a flag dash, or
    wrapped in backticks (``<field_id>``, ``parse_rows()``). Never a capitalised brand ("GitHub", "iPhone"): case
    alone is never code."""
    raw = str(name or "").strip()
    return bool(raw) and not any(c.isspace() for c in raw.strip("`")) and bool(_CODE_SHAPE.search(raw))


#: ``realpath → (entities stamp, folded names and aliases of every page)``: one listing per change of the folder.
_PAGE_NAMES: dict[str, tuple[Any, frozenset[str]]] = {}


def _page_names(memory_path: Path) -> frozenset[str]:
    key = os.path.realpath(memory_path)
    stamp = bank_index.dir_stamp(Path(memory_path), "entities")
    hit = _PAGE_NAMES.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    names: set[str] = set()
    for entry in bank_index.files(Path(memory_path), "entities"):
        names |= _names(entry.frontmatter or {})
        names.add(_fold_name(entry.stem.replace("-", " ")))
    out = frozenset(n for n in names if n)
    _PAGE_NAMES[key] = (stamp, out)
    return out


def _owner_pages_name(memory_path: Path, full: dict) -> bool:
    from api.services import inbox_ask_gate

    for entry in bank_index.files(Path(memory_path), "entities"):
        if _is_owner_page(entry.frontmatter):
            try:
                if inbox_ask_gate.named_in(full, entry.body()):
                    return True
            except Exception:  # noqa: BLE001 — an unreadable owner page: nothing is assumed
                return True
    return False


def _from_messages(ep_fm: dict) -> bool:
    from api.services import messages_source

    return messages_source.SOURCE in (str(ep_fm.get("source") or ""), str(ep_fm.get("origin") or ""))


def _search(memory_path: Path, names: list[str], per_name: int) -> list[str] | None:
    """The bank's conversations the lexical index finds by these spellings (words only, no model); ``None`` when the
    index cannot be read."""
    from api.services import search_index, search_service

    try:
        # Read fresh, inline: a conversation this batch just committed counts ("said again" must never be missed).
        search_index.ensure_fresh(memory_path, wait=True, max_age_s=0)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"inbox tend: record index unavailable ({type(exc).__name__})")
    out: list[str] = []
    for name in names[:3]:
        try:
            hits = search_service.search(memory_path, name, kinds=("episode",), mode="prefix",
                                         per_kind=per_name).results
        except Exception as exc:  # noqa: BLE001 — a derived index never fails a settle
            logger.info(f"inbox tend: record search unavailable ({type(exc).__name__})")
            return None
        out += [str(h.episode_id or h.id) for h in hits if str(h.episode_id or h.id or "").startswith("ep_")]
    return out


def _other_conversations(memory_path: Path, full: dict, source: str) -> list[str] | None:
    """The bank's other conversations whose own text names it (each confirmed on its text, whole words); ``None``
    when the index cannot be read — nothing is assumed then."""
    from api.services import evidence, inbox_ask_gate

    found = _search(memory_path, inbox_ask_gate.names(full), PASSING_SEARCH)
    if found is None:
        return None
    out = []
    for eid in dict.fromkeys(found):
        if eid != source and inbox_ask_gate.named_in(full, evidence.source_text(Path(memory_path), eid) or ""):
            out.append(eid)
    return out


def passing_rule(memory_path: Path, item_id: str, fm: dict) -> tuple[Decision | None, str]:
    """``in_passing`` for a clarification about a name said once in passing, or ``(None, why it stays)``. Engine-free:
    the item, the raising conversation's own text, the page names and the lexical index. Never a name with a page,
    one of the person's own things (a project, a skill, a deadline), a relation question ("What's the name of your
    <relation>?"), a person said in any of the person's own turns, a relation word in the turn that names a person,
    company or place or the turns beside it ("your teammate …"), a company or place beside the person's words about
    themselves, a name on the owner's page, or anything from a Messages chat.
    A code identifier (``<field_id>``) is assumed however many conversations name it: who or what it is is the code."""
    from api.services import evidence, inbox_ask_gate, promotion, role_people

    if (str(fm.get("asks") or "") or fm.get("owner_role")
            or str(fm.get("uncertainty_type") or "") == role_people.UNCERTAINTY):
        return None, "needs_person"   # a relation's name: only the person knows it
    name = str(fm.get("entity_name") or fm.get("entity_mention") or "").strip()
    if not name:
        return None, "needs_person"
    typ = _type_of({}, str(fm.get("suggested_classification") or ""))
    if typ in _OWN_TYPES:
        return None, "own_type"
    full = inbox_ask_gate.with_page_names(memory_path, fm)
    entity_id = str(fm.get("entity_id") or "")
    if _page(memory_path, entity_id) is not None or set(inbox_ask_gate.names(full)) & _page_names(memory_path):
        return None, "needs_person"   # a page holds it: what it is belongs to the page (and move 3)
    source = str(fm.get("source_episode") or "")
    doc = evidence.source_document(Path(memory_path), source) if source else None
    if doc is None:
        return None, "unmeasured"     # the conversation that raised it cannot be read: nothing to judge "passing" by
    ep_fm, text = doc
    if _from_messages(ep_fm):
        return None, "messages"
    if not inbox_ask_gate.named_in(full, text):
        return None, "unmeasured"
    gaps = evidence.gap_ranges(ep_fm, text)
    spans = evidence.turns(text, override=ep_fm.get("evidence_kind"), gaps=gaps)
    saved = _saved_item(ep_fm, spans)    # a saved page's title, link or byline is no one's own words
    turns: list[tuple[bool, str]] = []   # (the person's own turn, its words), in order
    for t in spans:
        mine = t.role in promotion.PERSON_KINDS and not _agent_note(ep_fm.get("source"), t) and not saved
        turns.append((mine, text[t.content_start:t.end]))
    named = [i for i, (_mine, words) in enumerate(turns) if inbox_ask_gate.named_in(full, words)]
    code = code_identifier(name) and typ not in _PERSON_LIKE
    if typ in _PERSON_LIKE and any(turns[i][0] for i in named):
        return None, "persons_words"   # someone the person named in their own words may be in their life
    own = {w for n in inbox_ask_gate.names(full) for w in n.split()}
    if typ in _PERSON_LIKE | _TURN_CHECKED:
        window = sorted({j for i in named for j in (i - 1, i, i + 1) if 0 <= j < len(turns)})
        if any(_relation_in(turns[j][1], own) for j in window):
            return None, "relation"
        if typ in _TURN_CHECKED and not code and any(turns[j][0] and _about_self(turns[j][1]) for j in window):
            return None, "about_self"
    elif any(_relation_in(s, own) for i in named for s in _sentences(turns[i][1])
             if inbox_ask_gate.named_in(full, s)):
        return None, "relation"
    if _owner_pages_name(memory_path, full):
        return None, "owners_page"
    if not code:
        units = promotion.exchanges(text, override=ep_fm.get("evidence_kind"), gaps=gaps)
        if sum(1 for _p, whole in units if inbox_ask_gate.named_in(full, whole)) > PASSING_EXCHANGES:
            return None, "said_more"
    others = _other_conversations(memory_path, full, source)
    if others is None:
        return None, "unmeasured"
    if others and not code:
        return None, "named_again"
    for eid in others:
        doc = evidence.source_document(Path(memory_path), eid)
        if doc is not None and _from_messages(doc[0]):
            return None, "messages"
    return Decision(item_id, "clarification", "in_passing", {"action": "dismiss"},
                    answer="Code, mentioned in passing" if code else "Mentioned in passing",
                    guard=_guard(memory_path, entity_id)), ""


# --------------------------------------------------------------------------- part 3: a label conflict's newest words


#: A sentence carrying one of these is not a plain statement of one side ("no longer on …", "from … to …",
#: "should we use … or …"): never read mechanically — the judge may read it.
_HEDGES = _NEGATIONS | frozenset("""instead rather off from than vs versus or either whether maybe might perhaps
considering thinking consider should could would if unless until planning plan""".split())
#: Read on the RAW sentence (``text_fold.words`` splits "can't" into "can t"): a negation, a modal or an avoidance makes
#: a sentence no plain statement of a side (review B2: "Alpha Project can't use cluster-b", "Avoid cluster-b for …").
_RAW_UNCLEAR = re.compile(
    r"(?i)(?<!\w)(?:\w+n't|can|cannot|could|would|should|must|may|might|will|not|never|no longer|no|none|stop\w*|"
    r"avoid\w*|instead of|except|without|unless|nunca|ya no|sin|en vez de|en lugar de|evit\w*|dej\w* de|tampoco)(?!\w)")


def _plain(sentence: str) -> bool:
    return not _RAW_UNCLEAR.search(sentence.replace("\u2019", "'").replace("\u2018", "'"))


#: The plain placements a label may follow for the mechanical path (re-review, 2026-10-17: a blocklist keeps leaking —
#: "dropped", "ditched", "abandoned", "shut down" — so only these say "it is on X now"); anything else is the judge's.
_PLACEMENTS = tuple(tuple(p.split()) for p in (
    "is on", "runs on", "is running on", "uses", "is using", "moved to", "switched to", "migrated to", "now on",
    "lives on", "is at", "corre en", "esta en", "usa", "se movio a", "paso a", "ahora en"))


def _placed(folded: str, phrases: list[str]) -> bool:
    """Does a phrase of the label directly follow a plain placement ("is on cluster-b", "corre en cluster-b")?"""
    words = folded.split()
    for phrase in phrases:
        pw = phrase.split()
        if any(tuple(pw[:len(p)]) == p for p in _PLACEMENTS):
            starts = [i for i in range(len(words) - len(pw) + 1) if words[i:i + len(pw)] == pw]
            if starts:
                return True   # the label says its own placement ("Runs on alpha-os")
        for i in range(len(words) - len(pw) + 1):
            if words[i:i + len(pw)] == pw and any(tuple(words[max(0, i - len(p)):i]) == p for p in _PLACEMENTS):
                return True
    return False


#: How many conversations naming the subject are read for a label conflict, newest first.
MAX_LABEL_EPISODES = 24


@dataclass
class LabelLine:
    day: str
    episode: str
    order: int
    text: str
    keys: frozenset
    clear: bool


def _label_phrases(options: list[dict], subject: set[str]) -> dict[str, list[str]]:
    """``{option key: [folded phrases that state it]}`` — the whole label, and its distinctive run: from its first
    word no other label has (not a stop word, not the subject's own name) through the words after it, three
    characters or more ("Runs on alpha-os" vs "Runs on beta-os" → ``alpha os``)."""
    from api.services import text_fold

    words = {str(o.get("key")): _words(str(o.get("label") or "")) for o in options}
    out: dict[str, list[str]] = {}
    for key, ws in words.items():
        phrases = [" ".join(ws)] if ws else []
        others = set().union(*(set(w) for k, w in words.items() if k != key)) if len(words) > 1 else set()
        start = next((i for i, w in enumerate(ws) if w not in others and w not in text_fold.SUBJECT_STOPWORDS
                      and w not in subject), None)
        if start is not None:
            end = start + 1
            while end < len(ws) and ws[end] not in text_fold.SUBJECT_STOPWORDS:
                end += 1
            core = " ".join(ws[start:end])
            if len(core) >= 3 and core not in phrases:
                phrases.append(core)
        out[key] = [p for p in phrases if p]
    return out


def _phrases_for(subject_names: list[str], options: list[dict]) -> dict[str, list[str]]:
    return _label_phrases(options, {w for n in subject_names for w in n.split()})


def _states(phrases: dict[str, list[str]], folded: str) -> frozenset:
    """The option keys a folded sentence states, by whole-word phrase."""
    return frozenset(k for k, ps in phrases.items() if any(_phrase_in(p, folded) for p in ps))


def label_lines(memory_path: Path, fm: dict, options: list[dict]) -> list[LabelLine]:
    """Every sentence of the person's own (``kind: user`` turns, never an agent's saved note) that states a label of
    this conflict, in a turn that names its subject — across the conversations the page points at, the one that
    raised it and the ones the lexical index finds by the subject's spellings; newest conversation first, at most
    :data:`MAX_LABEL_EPISODES`. Engine-free."""
    from api.services import evidence, inbox_ask_gate

    full = inbox_ask_gate.with_page_names(memory_path, fm)
    subject_names = inbox_ask_gate.names(full)
    phrases = _phrases_for(subject_names, options)
    found = _search(memory_path, subject_names, RECORD_SEARCH_PER_NAME) or []
    candidates = [e for e in dict.fromkeys([str(fm.get("source_episode") or ""), *_pointed(memory_path, fm), *found])
                  if e and _day(e)]
    candidates.sort(key=lambda e: (_day(e), e), reverse=True)
    out: list[LabelLine] = []
    for eid in candidates[:MAX_LABEL_EPISODES]:
        doc = evidence.source_document(Path(memory_path), eid)
        if doc is None:
            continue
        ep_fm, text = doc
        turns = person_turns({"content": text, "evidence_kind": ep_fm.get("evidence_kind"),
                              "gaps": evidence.gap_ranges(ep_fm, text), "source": ep_fm.get("source")})
        order = 0
        for turn in turns:
            if not inbox_ask_gate.named_in(full, turn):
                continue
            for sentence in _sentences(turn):
                order += 1
                folded = " ".join(_words(sentence))
                keys = _states(phrases, folded)
                if not keys:
                    continue
                # Mechanical only when the sentence itself names the subject and says one side plainly (review B2:
                # "Alpha Project is wrapped up. Beta Example moved to cluster-b." never settles Alpha).
                clear = (len(keys) == 1 and not sentence.rstrip().endswith("?")
                         and not set(folded.split()) & _HEDGES and len(sentence) <= MAX_LINE_CHARS
                         and inbox_ask_gate.named_in(full, sentence) and _plain(sentence)
                         and _placed(folded, phrases[next(iter(keys))]))
                out.append(LabelLine(_day(eid), eid, order, sentence, keys, clear))
    return out


def _other_side_days(tied: dict[str, list], key: str) -> list[str]:
    return [_said(c) for k, found in tied.items() if k != key for c in found]


def newest_words(memory_path: Path, item_id: str, options: list[dict], tied: dict[str, list],
                 lines: list[LabelLine]) -> tuple[Decision | None, str]:
    """A label-only conflict settled by the person's newest words (part 3): the newest day any line of theirs states
    a side has only plain statements of ONE side; an older line of theirs (or a belief tied to another label) states
    another side, and nothing for another side is as new; the line is located exactly in their own turn. The winner
    rests on the person's own words, so the owner's-words rail (:func:`may_close`) holds by construction.
    ``needs_judge`` when lines exist but are not mechanical; ``labels_not_on_record`` when none state a side."""
    from api.services import evidence

    if not lines:
        return None, "labels_not_on_record"
    newest = max(ln.day for ln in lines)
    top = sorted((ln for ln in lines if ln.day == newest), key=lambda ln: (ln.episode, ln.order))
    keys = {k for ln in top for k in ln.keys}
    if len(keys) != 1 or not all(ln.clear for ln in top):
        return None, "needs_judge"
    key = next(iter(keys))
    other_days = _other_side_days(tied, key)
    if any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d or "") or d >= newest for d in other_days):
        return None, "needs_judge"   # a belief for another side is as new, or undated: not "newer than every other"
    if not (any(ln.day < newest and ln.keys - {key} for ln in lines) or other_days):
        return None, "needs_judge"   # nothing on the record ever said another side: no change to read
    pick = top[-1]
    quote = pick.text[:evidence.MAX_QUOTE_CHARS]
    if persons_span(memory_path, pick.episode, quote) is None:
        return None, "needs_judge"
    label = next((str(o.get("label") or "") for o in options if str(o.get("key")) == key), "")
    return Decision(item_id, "conflict", "newest_words", {"action": "resolve", "option_key": key}, answer=label,
                    quote={"episode": pick.episode, "quote": quote}), ""


# --------------------------------------------------------------------------- the engine


def _content(resp: Any) -> str:
    try:
        return str(resp["choices"][0]["message"]["content"] or "")
    except (TypeError, KeyError, IndexError):
        pass
    try:
        return str(resp.choices[0].message.content or "")
    except Exception:  # noqa: BLE001
        return ""


def _model_of(resp: Any) -> str | None:
    model = None
    try:
        model = resp["model"]
    except (TypeError, KeyError):
        model = getattr(resp, "model", None)
    return str(model) if model else None


def default_llm_fn(settings, *, sink: Callable[..., None] | None = None) -> Callable[..., Any]:
    """The engine Sleep resolved (or the person's chosen one, for the tidy): a blocking call, run off the loop.
    ``sink`` replaces the usage ledger (a dry run passes a no-op: it writes nothing)."""
    from api.services import providers

    model = (getattr(settings, "litellm_disambiguation_model", "") or None)
    if str(getattr(settings, "llm_mode", "")).lower() in ("agent", "codex"):
        return providers.resolve_llm_fn(settings, stage=STAGE, is_async=False, sink=sink)
    import litellm

    return providers.resolve_llm_fn(settings, model=model, stage=STAGE, completion=litellm.completion, sink=sink)


async def _ask(llm_fn: Callable[..., Any], prompt: str) -> tuple[dict, str | None]:
    from api.services import json_parse

    resp = await asyncio.to_thread(llm_fn, messages=[{"role": "user", "content": prompt}],
                                   response_format={"type": "json_object"})
    return json_parse.parse_json_object_or(_content(resp), {}), _model_of(resp)


def _page_text(page: tuple[Path, dict, str] | None, fallback: str = "") -> str:
    from api.services.claims import strip_claims_block

    if page is None:
        return fallback[:MAX_PAGE_CHARS]
    _path, fm, body = page
    head = f"name: {fm.get('name') or _path.stem}\ntype: {fm.get('type') or ''}\n"
    return (head + strip_claims_block(body))[:MAX_PAGE_CHARS]


async def judge_merge(memory_path: Path, path: Path, fm: dict, body: str, llm_fn) -> tuple[Decision | None, str]:
    """G21's judge, on one duplicate question: both pages' context, same / different / unsure."""
    target = _page(memory_path, str(fm.get("merge_target_hint") or ""))
    if target is None:
        return None, "no_target"
    guard = _guard(memory_path, str(fm.get("entity_id") or ""), target[0].stem)   # what the judge reads, as read
    mention = _page(memory_path, str(fm.get("entity_id") or ""))
    mention_text = _page_text(mention, f"name: {fm.get('entity_name') or ''}\n"
                                       f"type: {fm.get('suggested_classification') or ''}\n{body}")
    prompt = (
        "Two entries in one person's memory may name the SAME real-world thing. Read both and decide. "
        "Say \"same\" only when they are clearly one thing, \"different\" only when they are clearly two, and "
        "\"unsure\" otherwise. Reply JSON {\"verdict\":\"same|different|unsure\",\"confidence\":0..1,"
        "\"reason\":\"<one short line>\"}.\n\n"
        f"ENTRY A:\n{mention_text}\n\nENTRY B:\n{_page_text(target)}"
    )
    verdict, model = await _ask(llm_fn, prompt)
    word = str(verdict.get("verdict") or "").strip().lower()
    try:
        confidence = float(verdict.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < JUDGE_THRESHOLD or word not in ("same", "different"):
        return None, "unsure"
    name = str(target[1].get("name") or target[0].stem)
    reason = _reason(verdict)
    if word == "same":
        return Decision(path.stem, "merge_suggestion", "judged_same",
                        {"action": "merge", "merge_target": target[0].stem}, answer=f"Same as {name}",
                        model=model, guard=guard, reason=reason), ""
    return Decision(path.stem, "merge_suggestion", "judged_different",
                    {"action": "reject", "merge_target": target[0].stem}, answer=f"Not the same as {name}",
                    model=model, guard=guard, reason=reason), ""


def _reason(verdict: dict) -> str:
    from api.services import episode_scrub

    text = " ".join(str(verdict.get("reason") or "").split())[:MAX_REASON_CHARS]
    return episode_scrub.scrub(text)[0] if text else ""


def _verdict(verdict: dict) -> tuple[str, float]:
    word = str(verdict.get("verdict") or "").strip().lower()
    try:
        confidence = float(verdict.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return word, confidence


def _evidence_lines(memory_path: Path, claim, limit: int = MAX_EVIDENCE_LINES) -> list[str]:
    """What a claim rests on, read through its spans (never a copy kept anywhere): at most two short lines."""
    from api.services import evidence

    out = []
    for ev in claim.evidence or []:
        if len(out) >= limit or not ev.is_span():
            continue
        text = evidence.source_text(Path(memory_path), ev.episode) or ""
        line = " ".join(text[ev.start:ev.end].split())[:240]
        if line:
            out.append(f"{ev.kind or 'text'} said: {line}")
    return out


def _mention_lines(memory_path: Path, fm: dict, limit: int = MAX_EVIDENCE_LINES) -> list[tuple[str, str]]:
    """``(day, line)`` for the page's latest conversations that name it, newest first."""
    from api.services import episode_ids, evidence, inbox_ask_gate

    names_fm = {"entity_name": fm.get("name"), "aliases": fm.get("aliases") or []}
    refs = [str(r) for r in (fm.get("source_episodes") or []) if episode_ids.parse_episode_id(str(r))]
    out: list[tuple[str, str]] = []
    for ref in sorted(refs, reverse=True):
        if len(out) >= limit:
            break
        text = evidence.source_text(Path(memory_path), ref) or ""
        line = next((ln for ln in text.splitlines() if inbox_ask_gate.named_in(names_fm, ln)), "")
        if line:
            out.append((episode_ids.parse_episode_id(ref)[0], " ".join(line.split())[:240]))
    return out


async def judge_conflict(memory_path: Path, path: Path, fm: dict, llm_fn) -> tuple[Decision | None, str]:
    """Owner, 2026-10-17: a conflict settles when the record clearly supports one side or one is clearly newer — never
    a machine's reading over the person's own words, never what only the person knows. A label-only conflict (no
    option carries a claim) is read through the claims its labels are tied to (:func:`label_claims`)."""
    from api.services.claims import parse_claims

    page = _page(memory_path, str(fm.get("entity_id") or ""))
    if page is None:
        return None, "judgement"
    guard = _guard(memory_path, page[0].stem)   # what the judge reads, as read
    all_claims = parse_claims(page[2])
    claims = {c.id: c for c in all_claims}
    options = [o for o in inbox_questions.normalize_options(fm.get("options")) if str(o.get("key")) not in _GENERIC_KEYS]
    label_only = len(options) >= 2 and not any(o.get("claim_id") for o in options)
    rows: list[tuple[str, str, list]] = []
    words: list[LabelLine] = []
    tied: dict[str, list] = {}
    if label_only:
        tied = label_claims(options, all_claims, str(fm.get("predicate") or "description"))
        rows = [(str(o.get("key")), str(o.get("label") or ""), tied.get(str(o.get("key")), [])) for o in options]
        words = label_lines(memory_path, fm, options)
        if not any(found for _, _, found in rows) and not words:
            return None, "labels_not_on_record"
    else:
        for o in options:
            claim = claims.get(str(o.get("claim_id") or ""))
            if claim is not None:
                rows.append((str(o.get("key")), str(o.get("label") or ""), [claim]))
    if len(rows) < 2:
        return None, "judgement"
    lines = []
    for key, label, found in rows:
        if not label_only:
            claim = found[0]
            who = "the person's own words" if persons_words(claim) else "read from elsewhere"
            lines.append(f"- option {key}: {label} (first said {claim.valid_from or 'unknown'}, last said "
                         f"{_said(claim) or 'unknown'}; {who})")
            lines += [f"    {ln}" for ln in _evidence_lines(memory_path, claim)]
            continue
        lines.append(f"- option {key}: {label}")
        if not found:
            lines.append("    (no belief on the record states this option)")
        for claim in found[:MAX_EVIDENCE_LINES]:
            who = "the person's own words" if persons_words(claim) else "read from elsewhere"
            lines.append(f"    belief: {' '.join(str(claim.text or claim.object or '').split())[:240]} (first said "
                         f"{claim.valid_from or 'unknown'}, last said {_said(claim) or 'unknown'}; {who})")
            lines += [f"      {ln}" for ln in _evidence_lines(memory_path, claim)]
    tags: dict[str, str] = {}
    said_lines: list[str] = []
    for ln in sorted(words, key=lambda w: (w.day, w.episode, w.order), reverse=True)[:MAX_RECORD_LINES]:
        tag = next((t for t, e in tags.items() if e == ln.episode), None)
        if tag is None:
            tag = f"C{len(tags) + 1}"
            tags[tag] = ln.episode
        said_lines.append(f"[{tag}, {ln.day}] {' '.join(ln.text.split())}")
    said = ("\n\nThe person's own words that name an option (newest first, each tagged with its conversation and "
            "the day it was said):\n" + "\n".join(said_lines)) if said_lines else ""
    reply = ("{\"verdict\":\"<option key>|unsure\",\"confidence\":0..1,\"reason\":\"<one short line>\""
             + (",\"conversation\":\"<the tag of the person's line your pick rests on, or null>\","
                "\"quote\":\"<that line's words, copied character for character, or null>\"" if said_lines else "")
             + "}")
    prompt = (
        "A person's memory holds two or more beliefs that cannot all be true now. Decide which one the record "
        "supports, from the dates and what was said. Pick an option only when it is CLEARLY better supported or "
        "clearly the newer statement of something that changes over time. If the answer depends on something only "
        "the person can know (their plans, feelings, relationships, private life), or the record is thin, say unsure."
        f" Reply JSON {reply}.\n\n"
        f"Subject: {page[1].get('name') or page[0].stem} ({page[1].get('type') or 'unknown'})\n"
        f"Question: {fm.get('question') or fm.get('title') or ''}\n" + "\n".join(lines) + said
    )
    verdict, model = await _ask(llm_fn, prompt)
    word, confidence = _verdict(verdict)
    chosen = next((r for r in rows if r[0] == word), None)
    if chosen is None or confidence < JUDGE_THRESHOLD:
        return None, "unsure"
    quote = _judged_words(memory_path, fm, options, tied, words, tags, verdict, chosen[0]) if said_lines else None
    if not chosen[2] and quote is None:
        return None, "unsure"     # a side nothing on the record states is never picked
    losers = [c for k, _, found in rows if k != chosen[0] for c in found]
    if quote is None and not any(may_close(w, losers) for w in chosen[2]):
        return None, "person"     # nothing but the person's own words overrules the person's own words
    return Decision(path.stem, "conflict", "judged_conflict", {"action": "resolve", "option_key": chosen[0]},
                    answer=chosen[1], quote=quote, model=model, guard=guard, reason=_reason(verdict)), ""


def _judged_words(memory_path: Path, fm: dict, options: list[dict], tied: dict[str, list], words: list[LabelLine],
                  tags: dict[str, str], verdict: dict, key: str) -> dict | None:
    """The person's line a judged label pick rests on, ``{"episode", "quote"}``, or ``None``: the judge named one of
    the tagged conversations, its words are located exactly in one of the person's own turns there, they state the
    picked label, and nothing for another side is as new — no line of theirs stating only another side on that day
    or later, no belief tied to another label said that day or later (or undated)."""
    from api.services import evidence, inbox_ask_gate

    eid = tags.get(str(verdict.get("conversation") or "").strip().strip("[]").split(",")[0].strip(), "")
    quote = inbox_ask_gate.clean_quote(str(verdict.get("quote") or ""), limit=evidence.MAX_QUOTE_CHARS)
    if not eid or not quote or persons_span(memory_path, eid, quote) is None:
        return None
    full = inbox_ask_gate.with_page_names(memory_path, fm)
    if key not in _states(_phrases_for(inbox_ask_gate.names(full), options), " ".join(_words(quote))):
        return None
    day = _day(eid)
    if any(ln.day >= day and key not in ln.keys for ln in words):
        return None
    if any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d or "") or d >= day for d in _other_side_days(tied, key)):
        return None
    return {"episode": eid, "quote": quote}


async def judge_fold(memory_path: Path, path: Path, fm: dict, llm_fn) -> tuple[Decision | None, str]:
    """A predicate fold settles only when the two labels mean the same; a changed meaning stays for the person."""
    from api.services.claims import parse_claims

    raw, canonical = str(fm.get("raw_predicate") or ""), str(fm.get("canonical_predicate") or "")
    guard = _guard(memory_path, str(fm.get("entity_id") or ""))   # what the judge reads, as read
    page = _page(memory_path, str(fm.get("entity_id") or ""))
    example = ""
    if page is not None:
        claim = next((c for c in parse_claims(page[2]) if c.id == str(fm.get("claim_id") or "")), None)
        example = f"\nAn example belief it was used in: {claim.text}" if claim is not None else ""
    prompt = (
        "A memory files relationships under labels. One label was filed under another. Say \"same\" only when the two "
        "labels mean the same relationship, so every belief under the first reads true under the second; "
        "\"different\" when the meaning changes; \"unsure\" otherwise. Reply JSON {\"verdict\":\"same|different|unsure\","
        f"\"confidence\":0..1,\"reason\":\"<one short line>\"}}.\n\nLabel: {raw}\nFiled under: {canonical}{example}"
    )
    verdict, model = await _ask(llm_fn, prompt)
    word, confidence = _verdict(verdict)
    if word != "same" or confidence < JUDGE_THRESHOLD:
        return None, "unsure" if word != "different" else "meaning_changes"
    return Decision(path.stem, "normalization", "judged_fold", {"action": "resolve", "option_key": "0"},
                    answer=f"{raw} is {canonical}", model=model, guard=guard, reason=_reason(verdict)), ""


async def judge_decay(memory_path: Path, path: Path, fm: dict, llm_fn) -> tuple[Decision | None, str]:
    """A fading concept/tool/media/company page: is it still live? Archive or keep; never the person's own
    projects, skills or people (the rule never sends those)."""
    page = _page(memory_path, str(fm.get("entity_id") or ""))
    if page is None:
        return None, "judgement"
    guard = _guard(memory_path, page[0].stem)   # what the judge reads, as read
    mentions = _mention_lines(memory_path, page[1])
    told = "\n".join(f"- {day}: {line}" for day, line in mentions) or "- (no mention lines found)"
    prompt = (
        "A memory page has not come up in a while. From the page and its last mentions, decide whether it is still "
        "live for this person (something they still use, follow or work with) or a passing thing that can be "
        "archived. Archiving is undoable and keeps everything. Say \"keep\" or \"archive\" only when it is clear, "
        "\"unsure\" otherwise. Reply JSON {\"verdict\":\"keep|archive|unsure\",\"confidence\":0..1,"
        f"\"reason\":\"<one short line>\"}}.\n\nToday: {date.today().isoformat()}\nPAGE:\n{_page_text(page)}\n\n"
        f"Last mentions (newest first):\n{told}"
    )
    verdict, model = await _ask(llm_fn, prompt)
    word, confidence = _verdict(verdict)
    if word not in ("keep", "archive") or confidence < JUDGE_THRESHOLD:
        return None, "unsure"
    if word == "archive":
        return Decision(path.stem, "decay", "judged_archive", {"action": "archive"}, answer="Archived",
                        model=model, guard=guard, reason=_reason(verdict)), ""
    return Decision(path.stem, "decay", "judged_keep", {"action": "keep_active"}, answer="Still tracked",
                    model=model, guard=guard, reason=_reason(verdict)), ""


async def judge_item(memory_path: Path, path: Path, fm: dict, body: str, llm_fn) -> tuple[Decision | None, str]:
    kind = str(fm.get("kind") or "")
    if kind == "merge_suggestion":
        return await judge_merge(memory_path, path, fm, body, llm_fn)
    if kind == "conflict":
        return await judge_conflict(memory_path, path, fm, llm_fn)
    if kind == "normalization":
        return await judge_fold(memory_path, path, fm, llm_fn)
    if kind == "decay":
        return await judge_decay(memory_path, path, fm, llm_fn)
    return None, "needs_person"


# --------------------------------------------------------------------------- move 1: answered in conversation


def _agent_note(source, turn) -> bool:
    """An unmarked block of an episode an agent saved through a tool door (``ask_sources.AGENT_SOURCES``): the
    evidence reader calls it the person's (R4), but it is the agent's note — never the person's own words here."""
    from api.services import ask_sources

    return str(source or "") in ask_sources.AGENT_SOURCES and getattr(turn, "marker", None) is None


def person_turns(episode: dict) -> list[str]:
    """The person's own turns of one conversation (``kind: user``), never an agent's, someone else's, or an agent's
    saved note (an unmarked block of an episode a tool door wrote)."""
    from api.services import evidence

    text = str(episode.get("content") or "")
    if not text:
        return []
    out = []
    for t in evidence.turns(text, override=episode.get("evidence_kind"), gaps=episode.get("gaps") or ()):
        if t.role == "user" and not _agent_note(episode.get("source"), t):
            line = text[t.content_start:t.end].strip()
            if line:
                out.append(line)
    return out


def _cited_episodes(memory_path: Path, fm: dict) -> set[str]:
    """The conversations a question already rests on: the one that raised it and each option claim's evidence."""
    from api.services.claims import parse_claims

    out = {str(fm.get("source_episode") or "")}
    ids = {str(o.get("claim_id")) for o in inbox_questions.normalize_options(fm.get("options")) if o.get("claim_id")}
    if ids:
        page = _page(memory_path, str(fm.get("entity_id") or ""))
        if page is not None:
            try:
                for c in parse_claims(page[2]):
                    if c.id in ids:
                        out |= {str(e.episode) for e in c.evidence or []}
            except Exception:  # noqa: BLE001
                pass
    return {e for e in out if e}


def touched(memory_path: Path, episodes: list[dict], items: list[tuple[Path, dict, str]],
            *, today: str | None = None) -> list[tuple[Path, dict, str, list[str]]]:
    """``(item path, frontmatter, episode id, the person's lines about it)`` for each open question one of these
    conversations is about — by the ask gate's rule, over the person's own words."""
    from api.services import inbox_ask_gate

    today = today or date.today().isoformat()
    out = []
    convos = [(str(ep.get("id") or ""), person_turns(ep)) for ep in episodes]
    convos = [(eid, lines) for eid, lines in convos if eid and lines]
    for path, fm, _body in items:
        kind = str(fm.get("kind") or "")
        if kind not in CONVERSATION_KINDS or _blocked(fm, today):
            continue   # taken back, or put off by the person: never touched
        full = inbox_ask_gate.with_page_names(memory_path, fm)
        cited = None
        for eid, lines in convos:
            ok, _why = inbox_ask_gate.relevant(full, "\n".join(lines))
            if not ok:
                continue
            cited = _cited_episodes(memory_path, fm) if cited is None else cited
            if eid in cited:
                continue   # the conversation that raised it never answers it
            about = [ln for ln in lines if inbox_ask_gate.named_in(full, ln)] or lines
            out.append((path, fm, eid, [ln[:MAX_LINE_CHARS] for ln in about[-MAX_LINES:]]))
            break
    return out


def _followup_choices(memory_path: Path, fm: dict) -> tuple[dict[str, str], str, str]:
    """``(choices, question, last heard day)`` for a follow-up, served as the app serves it — only the answers Sleep
    may take (:data:`FOLLOWUP_KEYS`). Empty choices when its claim is gone or settled."""
    from api.services import inbox_service
    from api.services.claims import parse_claims

    page = _page(memory_path, str(fm.get("entity_id") or ""))
    if page is None:
        return {}, "", ""
    try:
        claims = parse_claims(page[2])
        served, _human = inbox_service.followup_synthesis(fm, claims, date.today().isoformat())
    except Exception:  # noqa: BLE001 — a gone claim: nothing to answer
        return {}, "", ""
    allowed = FOLLOWUP_KEYS.get(str(fm.get("predicate") or ""), ())
    choices = {str(o.get("key")): str(o.get("label") or "") for o in served.get("options") or []
               if str(o.get("key")) in allowed}
    claim = next((c for c in claims if c.id == str(fm.get("claim_id") or "")), None)
    return choices, str(served.get("question") or ""), (_said(claim) if claim is not None else "")


def _question_prompt(memory_path: Path, fm: dict, lines: list[str], *,
                     tagged: bool = False) -> tuple[str, dict[str, str]]:
    """The engine's prompt for one question over the person's own lines, and the option keys it may answer with.
    ``tagged``: each line starts with its conversation's tag (``[C1, <day>]``) and the reply names the tag."""
    kind = str(fm.get("kind") or "")
    name = str(fm.get("entity_name") or fm.get("entity_mention") or fm.get("entity_id") or "")
    choices: dict[str, str] = {}
    question = str(fm.get("question") or fm.get("title") or f"About {name}")
    if kind == "conflict":
        for o in inbox_questions.normalize_options(fm.get("options")):
            key = str(o.get("key"))
            if key not in ("neither", "both", "other", "remind_later"):
                choices[key] = str(o.get("label") or "")
        how = ("Pick the option their words state. Options:\n"
               + "\n".join(f"- {k}: {v}" for k, v in choices.items()))
    elif kind == "followup":
        choices, served, _heard = _followup_choices(memory_path, fm)
        question = served or question
        how = ("Pick the option their words state about how it went. Options:\n"
               + "\n".join(f"- {k}: {v}" for k, v in choices.items()))
    elif kind == "merge_suggestion":
        target = _page(memory_path, str(fm.get("merge_target_hint") or ""))
        other = str((target[1].get("name") if target else "") or fm.get("merge_target_hint") or "")
        choices = {"merge": f"{name} is {other}", "different": f"{name} is not {other}"}
        how = "Options:\n" + "\n".join(f"- {k}: {v}" for k, v in choices.items())
    elif str(fm.get("asks") or "") == "name":
        how = "Give only the person's name, exactly as they wrote it, in \"answer\"."
    else:
        how = (f"Give the answer as a short phrase (at most {MAX_ANSWER_CHARS} characters) in their words, "
               "in \"answer\".")
    numbered = "\n".join(lines if tagged else [f"{i + 1}. {ln}" for i, ln in enumerate(lines)])
    where = ("one line per turn, each tagged with its conversation and the day it was said"
             if tagged else "one line per turn")
    reply = ("{\"answered\": true|false, \"option\": \"<key>\"|null, \"answer\": \"<short>\"|null, "
             + ("\"conversation\": \"<the tag of the line you quote, e.g. C1>\", " if tagged else "")
             + "\"quote\": \"<the exact words from one line that answer it, copied character for character, at most "
               "200 characters>\"}")
    prompt = (
        "You read what a person said in their own conversations and decide whether THEIR OWN WORDS already answer "
        "one open question their memory holds. Answer only from their words: never infer, never guess, never use "
        "what you know. If the words do not plainly answer it, say answered=false.\n\n"
        f"Question: {question}\n{how}\n\nThe person's own words ({where}):\n{numbered}\n\n"
        f"Reply JSON {reply}."
    )
    return prompt, choices


def persons_span(memory_path: Path, episode_id: str, quote: str):
    """The person's own words, located: ``evidence.verify`` exact → whitespace → case (never fuzzy), in a ``user``
    turn that is not an agent's saved note. ``None`` otherwise."""
    from api.services import evidence

    if not quote or not episode_id:
        return None
    ev = evidence.verify(memory_path, episode_id, quote)
    if ev is None or not ev.is_span() or ev.kind != "user":
        return None
    doc = evidence.source_document(Path(memory_path), episode_id)
    if doc is None:
        return None
    fm, text = doc
    for t in evidence.turns(text, override=fm.get("evidence_kind"), gaps=evidence.gap_ranges(fm, text)):
        if t.start <= ev.start < t.end:
            return None if _agent_note(fm.get("source"), t) else ev
    return None


def _answer_decision(memory_path: Path, path: Path, fm: dict, reply: dict, choices: dict[str, str],
                     episode_id: str, model: str | None, rule: str) -> tuple[Decision | None, str]:
    """The engine's reply → a decision, only on the person's own words located exactly in ``episode_id``."""
    from api.services import evidence, inbox_ask_gate

    if reply.get("answered") is not True:
        return None, "not_answered"
    quote = inbox_ask_gate.clean_quote(str(reply.get("quote") or ""), limit=evidence.MAX_QUOTE_CHARS)
    if persons_span(memory_path, episode_id, quote) is None:
        return None, "quote_not_found"   # the person's own spans, never a guess, never an agent's note
    kind = str(fm.get("kind") or "")
    words = {"episode": episode_id, "quote": quote}
    if kind in ("conflict", "followup"):
        key = str(reply.get("option") or "").strip()
        if key not in choices:
            return None, "no_option"
        return Decision(path.stem, kind, rule, {"action": "resolve", "option_key": key},
                        answer=choices[key], quote=words, model=model), ""
    if kind == "merge_suggestion":
        key = str(reply.get("option") or "").strip()
        target = str(fm.get("merge_target_hint") or "")
        if key not in choices or not target:
            return None, "no_option"
        request = ({"action": "merge", "merge_target": target} if key == "merge"
                   else {"action": "reject", "merge_target": target})
        return Decision(path.stem, kind, rule, request, answer=choices[key], quote=words, model=model), ""
    answer = " ".join(str(reply.get("answer") or "").split())[:MAX_ANSWER_CHARS]
    if not answer:
        return None, "no_answer"
    return Decision(path.stem, kind, rule, {"action": "answer", "answer": answer},
                    answer=answer, quote=words, model=model), ""


async def read_answer(memory_path: Path, path: Path, fm: dict, episode_id: str, lines: list[str],
                      llm_fn) -> tuple[Decision | None, str]:
    """Ask the engine whether the person's lines answer the question; a decision only on their located words."""
    prompt, choices = _question_prompt(memory_path, fm, lines)
    reply, model = await _ask(llm_fn, prompt)
    return _answer_decision(memory_path, path, fm, reply, choices, episode_id, model, "said_in_conversation")


# --------------------------------------------------------------------------- move 3: answered anywhere in the record


def _day(episode_id: str) -> str:
    from api.services import episode_ids

    parsed = episode_ids.parse_episode_id(str(episode_id or ""))
    return parsed[0] if parsed else ""


def _record_floor(memory_path: Path, fm: dict) -> str | None:
    """The day the answering words must come strictly after: every side of a conflict (its option claims, or the
    claims its labels are tied to; the day it was raised when a side has none), a follow-up's last heard day; ``""``
    for a clarification (who or what something is does not go stale). ``None``: nothing can answer it."""
    from api.services.claims import parse_claims

    kind = str(fm.get("kind") or "")
    if kind == "clarification":
        return ""
    if kind == "followup":
        choices, _q, heard = _followup_choices(memory_path, fm)
        return heard or None if choices else None
    page = _page(memory_path, str(fm.get("entity_id") or ""))
    if page is None:
        return None
    try:
        claims = parse_claims(page[2])
    except Exception:  # noqa: BLE001
        return None
    by_id = {c.id: c for c in claims}
    options = [o for o in inbox_questions.normalize_options(fm.get("options")) if str(o.get("key")) not in _GENERIC_KEYS]
    if len(options) < 2:
        return None
    if any(o.get("claim_id") for o in options):
        sides = [[by_id[str(o.get("claim_id"))]] if str(o.get("claim_id") or "") in by_id else [] for o in options]
    else:
        tied = label_claims(options, claims, str(fm.get("predicate") or "description"))
        sides = [tied.get(str(o.get("key")), []) for o in options]
    def dated(day: str) -> bool:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day or ""))

    days = [_said(c) for side in sides for c in side]
    if any(not side for side in sides):
        days.append(str(fm.get("created_date") or "")[:10])
    if not days or not all(dated(d) for d in days):
        return None   # a side with no date: "newer than every side" cannot be told, so the record never answers it
    return max(days)


def _record_cited(memory_path: Path, fm: dict) -> set[str]:
    """The conversations the question already rests on — the one that raised it, its option claims' evidence, a
    follow-up's thread, a label-only conflict's tied claims: never the answer to it."""
    from api.services.claims import parse_claims

    out = _cited_episodes(memory_path, fm)
    kind = str(fm.get("kind") or "")
    page = _page(memory_path, str(fm.get("entity_id") or "")) if kind in ("followup", "conflict") else None
    if page is None:
        return out
    try:
        claims = parse_claims(page[2])
    except Exception:  # noqa: BLE001
        return out
    if kind == "followup":
        claim = next((c for c in claims if c.id == str(fm.get("claim_id") or "")), None)
        found = [claim] if claim is not None else []
    else:
        options = [o for o in inbox_questions.normalize_options(fm.get("options"))
                   if str(o.get("key")) not in _GENERIC_KEYS]
        if any(o.get("claim_id") for o in options):
            return out   # a claim-backed conflict: its option claims' evidence is already counted above
        found = [c for side in label_claims(options, claims, str(fm.get("predicate") or "")).values() for c in side]
    for c in found:
        out |= {str(e.episode) for e in c.evidence or [] if getattr(e, "episode", "")}
        out |= {str(e) for e in (getattr(c, "source_episodes", None) or [])}
    return {e for e in out if e}


def _record_search(memory_path: Path, names: list[str]) -> list[str]:
    """The bank's conversations that say one of the subject's spellings, through the lexical index (the derived FTS
    index ``search_service`` serves recall and Ask from; words only — no embedding model inside Sleep)."""
    return _search(memory_path, names, RECORD_SEARCH_PER_NAME) or []


def _pointed(memory_path: Path, fm: dict) -> list[str]:
    """The conversations the subject's page points at — its claims' evidence and its ``source_episodes`` (the pointers
    Ask's source words follow, G118)."""
    from api.services.claims import parse_claims

    page = _page(memory_path, str(fm.get("entity_id") or ""))
    if page is None:
        return []
    out = [str(e) for e in (page[1].get("source_episodes") or [])]
    try:
        for c in parse_claims(page[2]):
            out += [str(e.episode) for e in c.evidence or [] if getattr(e, "episode", "")]
    except Exception:  # noqa: BLE001
        pass
    return out


def _served_fm(memory_path: Path, fm: dict) -> dict:
    """The question as the ask gate reads it: a follow-up's question and options are served at read, never stored."""
    if str(fm.get("kind") or "") != "followup":
        return fm
    choices, question, _heard = _followup_choices(memory_path, fm)
    return {**fm, "question": question,
            "options": [{"key": k, "label": v} for k, v in choices.items()]}


def record_lines(memory_path: Path, fm: dict) -> list[tuple[str, str, str]]:
    """``(tag, episode id, line)`` — the person's own lines that name the question's subject, across the whole record,
    newest conversation first; only conversations the ask gate finds about the question (``relevant``), never one the
    question rests on, never one said on or before :func:`_record_floor`. Empty: nothing to read (no engine call)."""
    from api.services import evidence, inbox_ask_gate

    floor = _record_floor(memory_path, fm)
    if floor is None:
        return []
    full = inbox_ask_gate.with_page_names(memory_path, _served_fm(memory_path, fm))
    cited = _record_cited(memory_path, fm)
    candidates = [e for e in dict.fromkeys(_pointed(memory_path, fm)
                                           + _record_search(memory_path, inbox_ask_gate.names(full)))
                  if e and e not in cited and _day(e) and _day(e) > floor]
    candidates.sort(key=lambda e: (_day(e), e), reverse=True)
    out: list[tuple[str, str, str]] = []
    convos = 0
    for eid in candidates:
        if convos >= MAX_RECORD_EPISODES or len(out) >= MAX_RECORD_LINES:
            break
        doc = evidence.source_document(Path(memory_path), eid)
        if doc is None:
            continue
        ep_fm, text = doc
        lines = person_turns({"content": text, "evidence_kind": ep_fm.get("evidence_kind"),
                              "gaps": evidence.gap_ranges(ep_fm, text), "source": ep_fm.get("source")})
        about = [ln for ln in lines if inbox_ask_gate.named_in(full, ln)]
        if not about or not inbox_ask_gate.relevant(full, "\n".join(about))[0]:
            continue
        convos += 1
        tag = f"C{convos}"
        for ln in about[-MAX_RECORD_LINES_PER_EPISODE:]:
            if len(out) < MAX_RECORD_LINES:
                out.append((tag, eid, " ".join(ln.split())[:MAX_LINE_CHARS]))
    return out


#: ``(bank, question) → what move 3 last read for it and found no answer in``: the same lines are never sent to the
#: engine twice, so a drain's few reads move on to questions with something new on the record. In this process only
#: (ids and a hash; a restart reads each once more).
_RECORD_READ: dict[tuple[str, str], str] = {}
_NOT_ANSWERED = frozenset({"not_answered", "quote_not_found", "no_option", "no_answer"})


def _record_key(memory_path: Path, path: Path) -> tuple[str, str]:
    return os.path.realpath(memory_path), path.stem


async def read_record_answer(memory_path: Path, path: Path, fm: dict, llm_fn) -> tuple[Decision | None, str]:
    """Move 3 for one question: the person's own lines about it across the record, one engine call, and a decision
    only on their words located exactly in the conversation the reply names. ``not_on_record``: no engine call
    (nothing names it, or the same lines were already read without an answer)."""
    import hashlib

    guard = _guard(memory_path, str(fm.get("entity_id") or ""))   # the page whose claims and dates it reads, as read
    found = await asyncio.to_thread(record_lines, memory_path, fm)   # file reads and the index, off the loop
    if not found:
        return None, "not_on_record"
    if str(fm.get("kind") or "") == "followup" and not _followup_choices(memory_path, fm)[0]:
        return None, "not_on_record"
    episodes = {tag: eid for tag, eid, _ in found}
    lines = [f"[{tag}, {_day(eid)}] {line}" for tag, eid, line in found]
    seen = hashlib.sha256("\n".join([str(fm.get("kind") or ""), str(fm.get("question") or ""), *lines])
                          .encode("utf-8")).hexdigest()
    key = _record_key(memory_path, path)
    if _RECORD_READ.get(key) == seen:
        return None, "not_on_record"
    prompt, choices = _question_prompt(memory_path, fm, lines, tagged=True)
    reply, model = await _ask(llm_fn, prompt)
    d, why = None, "not_answered"
    if reply.get("answered") is True:
        episode_id = episodes.get(str(reply.get("conversation") or "").strip().strip("[]").split(",")[0].strip(), "")
        d, why = ((None, "quote_not_found") if not episode_id else
                  _answer_decision(memory_path, path, fm, reply, choices, episode_id, model, "said_on_record"))
    if d is not None:
        d.guard = guard
        _RECORD_READ.pop(key, None)
    elif why in _NOT_ANSWERED:
        _RECORD_READ[key] = seen
    return d, why


# --------------------------------------------------------------------------- the one writer


def _head(memory_path: Path) -> str:
    proc = subprocess.run(["git", "-C", str(memory_path), "rev-parse", "-q", "--verify", "HEAD"],
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _record(fm: dict, d: Decision, by: str, evidence_span: dict | None) -> dict:
    rec = {
        "group": GROUP, "at": _now(), "by": by, "by_kind": GROUP, "rule": d.rule,
        "reason": d.reason or RULES.get(d.rule, ""), "answer": d.answer, "entity_id": str(fm.get("entity_id") or ""),
        "entity_name": str(fm.get("entity_name") or fm.get("entity_mention") or ""),
        "predicate": str(fm.get("predicate") or ""),
    }
    if evidence_span:
        rec["evidence"] = evidence_span
    return rec


def _now() -> str:
    from api.services import episode_ids

    return episode_ids.utc_now_iso()


def still_holds(memory_path: Path, d: Decision) -> bool:
    """Is the decision still what the bank says, now? Every page it read is as it was (``guard``), and an engine-free
    rule decides the same again. Asked inside the settle's own hold (Sleep's window or the tidy's admission)."""
    if not guard_holds(memory_path, d):
        return False
    if d.rule not in ENGINE_FREE:
        return True
    path = _inbox(Path(memory_path)) / f"{d.item_id}.md"
    try:
        fm = markdown_parser.parse(path).frontmatter
    except Exception:  # noqa: BLE001
        return False
    again, _why = policy(Path(memory_path), path, fm)
    return again is not None and (again.rule, again.request) == (d.rule, d.request)


async def apply(memory_path: Path, settings, d: Decision, *, engine: str | None = None) -> bool:
    """Settle one question through the person's own resolver, as Sleep. The caller holds the bank (Sleep's window,
    or the tidy's per-item admission). True when it settled and committed; False leaves the question as it was."""
    from api.models.schemas import InboxResolveRequest
    from api.services import evidence, inbox_service

    memory_path = Path(memory_path)
    path = _inbox(memory_path) / f"{d.item_id}.md"
    if not path.exists() or not (memory_path / ".git").exists():
        return False
    raw = path.read_bytes()
    if d.fingerprint and raw != d.fingerprint:
        return False   # the question changed since it was read: it is read again next time
    if not still_holds(memory_path, d):
        return False   # a page it read changed since (a conversation, an edit, a Sleep batch): read again next time
    parsed = markdown_parser.parse(path)
    fm, body = dict(parsed.frontmatter), parsed.body
    span = None
    if d.quote:
        ev = persons_span(memory_path, d.quote["episode"], d.quote["quote"])
        if ev is None:
            return False
        span = {"episode": ev.episode, "start": ev.start, "end": ev.end}
    authors = [d.model] if d.model else ["cicada"]
    record_rel = f"inbox/{SETTLED_DIR}/{d.item_id}.md"
    record_path = memory_path / record_rel
    if record_path.exists():
        return False   # a settled question of this number already waits for its undo
    line = f"{record_rel}: created (source: {d.item_id}, trigger: {TRIGGER}:{d.rule})"
    # The record is written by the commit itself (after the resolver's dirty snapshot), so it rides in that commit.
    # A "same" merge folds the duplicate's page into the target (`fold_pages`): never a question gone, both pages left.
    actor = inbox_actor.Actor(rule=d.rule, authors=authors, engine=engine if d.model else None,
                              extra_paths=[record_rel], extra_lines=[line],
                              record=(record_path, {**fm, "settled": _record(fm, d, authors[0], span)}, body),
                              fold_pages=bool(d.request and d.request.get("action") == "merge"))
    token = inbox_actor.set_actor(actor)
    quote_token = inbox_service._ANSWER_QUOTE.set([d.quote] if d.quote else None)
    try:
        if d.request is None:
            await asyncio.to_thread(_retire, memory_path, path, fm, d, actor)
        elif d.kind == "normalization":
            # Its resolver holds the page lock itself, from re-reading the item through its own commit.
            await inbox_service._resolve_admitted(d.item_id, InboxResolveRequest(**d.request), settings, None)
        else:
            await asyncio.to_thread(_resolve_page_locked, memory_path, d, settings)
    except Exception as exc:  # noqa: BLE001 — one question that will not settle never stops the others
        logger.info(f"inbox tend: {d.item_id} left for the person ({type(exc).__name__})")
        if not actor.committed:
            record_path.unlink(missing_ok=True)
            bank_index.invalidate(memory_path)
        return False
    finally:
        inbox_service._ANSWER_QUOTE.reset(quote_token)
        inbox_actor.reset(token)
    if not actor.committed or path.exists():
        # Skipped by its resolver: nothing of ours may linger for another writer to sweep up.
        if not actor.committed:
            record_path.unlink(missing_ok=True)
            bank_index.invalidate(memory_path)
        return False
    return True   # the resolver committed under Sleep's name (`git_service.commit_resolution_sync`)


def _resolve_page_locked(memory_path: Path, d: Decision, settings) -> None:
    """The resolver, from its first page read through its own commit, under the bank's page lock (as the dedup sweep
    holds it across each merge): an agent's claim write admitted between the tidy's settles waits for it, and a merge
    never overwrites what that write put on either page. Runs in a worker thread with its own loop — the lock is a
    thread's, never held across the event loop's awaits; the actor and the person's words ride in the copied context."""
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service, page_lock

    with page_lock.page_lock(memory_path):
        asyncio.run(inbox_service._resolve_admitted(d.item_id, InboxResolveRequest(**d.request), settings, None))


def _retire(memory_path: Path, path: Path, fm: dict, d: Decision, actor: inbox_actor.Actor) -> None:
    """A question whose subject is gone: moved to its settled record, nothing else touched, one Sleep commit."""
    from api.services import git_service, telemetry

    rel = path.relative_to(memory_path).as_posix()
    before = git_service.snapshot_dirty_sync(memory_path)
    path.unlink()
    inbox_actor.write_record(actor)
    bank_index.invalidate(memory_path)
    lines = [f"{rel}: settled (source: {d.item_id}, trigger: {TRIGGER}:{d.rule})", *actor.extra_lines]
    message = git_service.build_commit_message(
        f"Inbox settled by Sleep ({d.kind}) {date.today().isoformat()}", lines, authors=actor.authors)
    git_service.commit_touched_sync(memory_path, message, [rel, *actor.extra_paths], before=before,
                                    kept_subject=f"Uncommitted edit kept apart {date.today().isoformat()}",
                                    kept_trigger="inbox/kept-apart")
    actor.committed = True
    try:
        telemetry.record(telemetry.UsageEvent(
            kind="resolution", stage="feedback", bank=Path(memory_path).name, invocations=0, billing="free",
            refs={"item_id": d.item_id, "kind": d.kind, "entity_id": str(fm.get("entity_id") or "") or None,
                  "action": "retire", "verdict": "neutral", "by": GROUP, "rule": d.rule}))
    except Exception:  # noqa: BLE001 — a ledger row never fails a settle
        pass


# --------------------------------------------------------------------------- the passes


class _SleepStarted(Exception):
    pass


async def _settle_one(memory_path: Path, settings, d: Decision, report: Report, *, engine: str | None,
                      admitted: bool) -> bool:
    """Settle ``d`` now — right after it was decided — inside Sleep's own window, or (the tidy) under the bank's write
    admission, refused while Sleep holds the pages. False when the pass must stop."""
    from api.services import write_admission

    if admitted:
        try:
            ok = await write_admission.run_admitted(
                memory_path, lambda: apply(memory_path, settings, d, engine=engine), refuse=_SleepStarted)
        except _SleepStarted:
            report.stopped = "sleep_running"
            return False
    else:
        ok = await apply(memory_path, settings, d, engine=engine)
    if ok:
        report.settled += 1
        report.count(d.kind, d.rule)
    else:
        report.asked += 1
        report.count(d.kind, "left:changed")
    return True


def _plan_paused(exc: BaseException) -> str | None:
    """A plan limit (or a sign-out) stops the pass — a pause, never a failure."""
    from api.services import agent_engine

    reason = agent_engine.breaker_reason()
    if reason:
        return "plan_limit"
    name = type(exc).__name__.lower()
    return "plan_limit" if "limit" in name or "throttl" in name else None


def _sleep_holds(admitted: bool) -> bool:
    if not admitted:
        return False   # Sleep itself is the one tending
    from api.services import write_admission

    return write_admission.probe()


async def policy_pass(memory_path: Path, settings, report: Report, *, llm_fn=None, judge_cap: int | None = JUDGE_CAP,
                      limit: int | None = None, dry_run: bool = False, judge: bool = True,
                      admitted: bool = False, engine: str | None = None, record_cap: int | None = 0,
                      progress: Callable[[], None] | None = None) -> None:
    """Move 2 over every open question, one at a time: decide (the engine-free rules, then the judge on up to
    ``judge_cap`` questions — ``None``: no cap) and settle it at once, so nothing decided waits while the bank moves.
    A clarification, follow-up or conflict still open is then looked for across the whole record (move 3) on up to
    ``record_cap`` questions (``None``: no cap; 0: never). ``dry_run`` decides and counts, writing nothing.
    ``admitted`` (the tidy) stops the moment Sleep holds the pages — before an engine call and before a settle."""
    today = date.today().isoformat()
    judged = 0
    searched = 0
    seen = 0
    for path, _fm, _body in pending(memory_path):
        if limit is not None and seen >= limit:
            break
        if report.stopped:
            break
        if _sleep_holds(admitted):
            report.stopped = "sleep_running"
            break
        try:   # read it again now: an earlier settle may have moved it
            fingerprint = path.read_bytes()
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — gone or unreadable: nothing to settle
            continue
        seen += 1
        fm, body = dict(parsed.frontmatter), parsed.body
        kind = str(fm.get("kind") or "")
        d, why = policy(memory_path, path, fm, today=today)
        if d is None and why == "needs_judge" and kind in JUDGED_KINDS:
            if judge and llm_fn is not None and (judge_cap is None or judged < judge_cap):
                judged += 1
                report.judged += 1
                try:
                    d, why = await judge_item(memory_path, path, fm, body, llm_fn)
                except Exception as exc:  # noqa: BLE001
                    paused = _plan_paused(exc)
                    if paused:
                        report.stopped = paused
                    logger.info(f"inbox tend: judge failed ({type(exc).__name__}: {exc})")
                    d, why = None, "judge_failed"
        if (d is None and kind in RECORD_KINDS and why not in _RECORD_SKIP and llm_fn is not None
                and not report.stopped and (record_cap is None or searched < record_cap)):
            if _sleep_holds(admitted):
                report.stopped = "sleep_running"
                break
            try:
                found, rwhy = await read_record_answer(memory_path, path, fm, llm_fn)
            except Exception as exc:  # noqa: BLE001
                paused = _plan_paused(exc)
                if paused:
                    report.stopped = paused
                logger.info(f"inbox tend: record read failed ({type(exc).__name__})")
                found, rwhy = None, "record_failed"
            if rwhy != "not_on_record":
                searched += 1    # an engine call was made (no lines on the record costs nothing)
                report.read += 1
            if found is not None:
                d, why = found, ""
            elif rwhy not in ("not_on_record",):
                why = f"{why}+record:{rwhy}" if why else f"record:{rwhy}"
        if d is None:
            report.asked += 1
            report.count(kind, f"ask:{why}")
            if progress is not None:
                progress()
            continue
        d.fingerprint = fingerprint
        if dry_run:
            report.settled += 1
            report.count(kind, d.rule)
            continue
        ok = await _settle_one(memory_path, settings, d, report, engine=engine, admitted=admitted)
        if progress is not None:
            progress()    # the counts so far survive a restart (the tidy's own file, outside the bank)
        if not ok:
            break


async def conversation_pass(memory_path: Path, settings, episodes: list[dict], report: Report, *, llm_fn,
                            cap: int = CONVERSATION_CAP, engine: str | None = None, dry_run: bool = False) -> None:
    """Move 1: questions the batch's conversations touched, answered only by the person's own located words."""
    if llm_fn is None:
        return
    items = pending(memory_path)
    for path, fm, eid, lines in touched(memory_path, episodes, items)[:max(0, cap)]:
        kind = str(fm.get("kind") or "")
        report.read += 1
        try:
            fingerprint = path.read_bytes()
            d, why = await read_answer(memory_path, path, fm, eid, lines, llm_fn)
        except Exception as exc:  # noqa: BLE001
            paused = _plan_paused(exc)
            if paused:
                report.stopped = paused
                break
            d, why = None, "read_failed"
        if d is None:
            report.count(kind, f"conversation:{why}")
            continue
        d.fingerprint = fingerprint
        if dry_run:
            report.settled += 1
            report.count(kind, d.rule)
        else:
            await _settle_one(memory_path, settings, d, report, engine=engine, admitted=False)


async def tend(memory_path: Path, settings, *, episodes: list[dict], run_policy: bool, llm_fn=None,
               engine: str | None = None) -> Report:
    """One Sleep batch's tending, inside Sleep's own write window, after the batch's commit: move 1 for what its
    conversations touched, and (once per drain) move 2 over the whole inbox. Each settle commits alone; the state
    projection is left to the run's tail."""
    memory_path = Path(memory_path)
    report = Report(engine=engine)
    if not (memory_path / ".git").exists() or not _inbox(memory_path).is_dir():
        return report
    if llm_fn is None:
        try:
            llm_fn = default_llm_fn(settings)
        except Exception as exc:  # noqa: BLE001 — no engine: the engine-free rules still run
            logger.info(f"inbox tend: no engine ({type(exc).__name__}); engine-free rules only")
            llm_fn = None
    await conversation_pass(memory_path, settings, episodes, report, llm_fn=llm_fn, engine=engine)
    if run_policy and not report.stopped:
        await policy_pass(memory_path, settings, report, llm_fn=llm_fn, engine=engine, record_cap=RECORD_CAP)
    # The state projection is refreshed by Sleep's own tail at the end of the run, once.
    return report


# --------------------------------------------------------------------------- the one-time tidy

_TIDY: dict[str, Any] = {"running": False, "report": None, "task": None, "bank": None, "started_at": None}
#: The tidy's counts survive a restart (2026-10-17: an update restarted the backend 285 settles into a real tidy, and
#: ``GET /inbox/tidy`` answered null): one small JSON per bank OUTSIDE every bank — counts and enums only, never an id
#: or a word — written as the run goes. A file still saying ``running`` that no live run owns was cut short:
#: ``interrupted``.
TIDY_DIR = "inbox_tidy"


def _tidy_file(memory_path: Path) -> Path:
    from api.services import auth, continuity_sessions

    return auth.cicada_home() / TIDY_DIR / f"{continuity_sessions.bank_file_id(Path(memory_path))}.json"


def _save_tidy(memory_path: Path, report: Report, *, running: bool, started_at: str | None) -> None:
    import json

    try:
        body = {"running": running, "started_at": started_at, "updated_at": _now(), "report": report.as_dict()}
        path = _tidy_file(memory_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_bytes(path, json.dumps(body, sort_keys=True).encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — the counts are a convenience: never a reason to stop settling
        logger.info(f"inbox tidy: report not saved ({type(exc).__name__})")


def _load_tidy(memory_path: Path) -> dict | None:
    import json

    try:
        body = json.loads(_tidy_file(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def tidy_running() -> bool:
    """Is a real tidy settling questions in this process now? (``/sleep/status`` → ``inboxTidy``: an updater that
    restarts the backend waits for it, as it waits for Sleep.)"""
    return bool(_TIDY.get("running"))


def tidy_status(memory_path: Path | None = None) -> dict:
    """The running (or last) real tidy's counts. With ``memory_path``, a run this process no longer holds is read
    back from its saved counts — ``interrupted: true`` when it was cut short (a restart mid-run)."""
    report = _TIDY.get("report")
    same_bank = memory_path is None or _TIDY.get("bank") in (None, os.path.realpath(memory_path))
    if report is not None and same_bank:
        return {"running": bool(_TIDY.get("running")), "report": report.as_dict(),
                "started_at": _TIDY.get("started_at")}
    if memory_path is not None:
        saved = _load_tidy(memory_path)
        if saved is not None:
            out = {"running": False, "report": saved.get("report"), "started_at": saved.get("started_at"),
                   "updated_at": saved.get("updated_at")}
            if saved.get("running"):
                out["interrupted"] = True
            return out
    return {"running": bool(_TIDY.get("running")), "report": None}


def start_tidy(memory_path: Path, settings, *, limit: int | None = None, judge: bool = False) -> bool:
    """Start a real tidy in the background; False when one is already running. The flag is set here, synchronously,
    so two quick requests can never start two, and the task is kept so it is never collected mid-run."""
    if _TIDY.get("running"):
        return False
    _TIDY["running"] = True
    _TIDY["task"] = asyncio.get_running_loop().create_task(
        tidy(memory_path, settings, dry_run=False, limit=limit, judge=judge))
    return True


async def tidy(memory_path: Path, settings, *, dry_run: bool = True, limit: int | None = None, judge: bool = False,
               llm_fn=None) -> dict:
    """The one-time tidy of the existing backlog: the same policy (move 2) over every open question. ``dry_run``
    writes nothing and prints counts per kind and per decision — never a title, a name or any text. ``judge`` lets
    the judge read duplicates, conflicts, label folds and fading pages with the person's chosen engine (their Claude
    plan included, owner 2026-10-17); a plan limit pauses it (``stopped: plan_limit``) and what it settled stays
    settled. A real run decides and settles one question at a time under the bank's write admission, one commit
    each, and stops the moment Sleep holds the pages."""
    from api.services import engine_select

    memory_path = Path(memory_path)
    report = Report()
    started_at = _now()
    progress = None
    try:
        if not dry_run:
            _TIDY.update(running=True, report=report, bank=os.path.realpath(memory_path), started_at=started_at)
            _save_tidy(memory_path, report, running=True, started_at=started_at)

            def progress() -> None:
                _save_tidy(memory_path, report, running=True, started_at=started_at)
        if not _inbox(memory_path).is_dir():
            return report.as_dict()
        if not dry_run and not (memory_path / ".git").exists():
            report.stopped = "no_git"
            return report.as_dict()
        engine = None
        if judge and llm_fn is None:
            resolved, _why = await engine_select.resolve_settings(settings, user_triggered=True)
            engine = engine_select.engine_label(resolved)
            llm_fn = default_llm_fn(resolved, sink=(lambda _event: None) if dry_run else None)
        report.engine = engine
        from api.services import agent_engine

        with agent_engine.use_scope(f"inbox-tidy:{memory_path.name}"):
            await policy_pass(memory_path, settings, report, llm_fn=llm_fn if judge else None, judge_cap=None,
                              limit=limit, dry_run=dry_run, judge=judge, admitted=True, engine=engine,
                              record_cap=None if judge else 0, progress=progress)
        if report.settled and not dry_run:
            try:
                from api.services import state_dictionary

                await state_dictionary.refresh_and_commit(memory_path, settings)
            except Exception as exc:  # noqa: BLE001 — the projection never fails the tidy
                logger.info(f"state refresh after the tidy skipped: {type(exc).__name__}")
    finally:
        if not dry_run:
            _TIDY["running"] = False
            _save_tidy(memory_path, report, running=False, started_at=started_at)
    out = report.as_dict()
    out["dry_run"] = dry_run
    return out


# --------------------------------------------------------------------------- the list and the undo


def quote_for(memory_path: Path, rec: dict) -> tuple[str, str]:
    """``(quote, episode)`` for a Sleep record that rests on the person's words, read through its span."""
    from api.services import evidence

    span = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else None
    if not span:
        return "", ""
    episode = str(span.get("episode") or "")
    text = evidence.source_text(Path(memory_path), episode) or ""
    try:
        start, end = int(span.get("start")), int(span.get("end"))
    except (TypeError, ValueError):
        return "", episode
    return " ".join(text[start:end].split())[:240], episode


def _git_bytes(memory_path: Path, rev_path: str) -> bytes | None:
    proc = subprocess.run(["git", "-C", str(memory_path), "cat-file", "blob", rev_path], capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


def _commit_of(memory_path: Path, record_rel: str) -> str:
    proc = subprocess.run(["git", "-C", str(memory_path), "log", "-1", "--diff-filter=A", "--format=%H", "--",
                           record_rel], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _changed(memory_path: Path, sha: str) -> list[str]:
    proc = subprocess.run(["git", "-C", str(memory_path), "diff-tree", "-r", "-z", "--no-commit-id", "--name-only",
                           "--no-renames", f"{sha}^", sha], capture_output=True)
    if proc.returncode != 0:
        raise NotUndoable("The settle's commit could not be read; nothing was changed.")
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def _reverse(memory_path: Path, current: bytes, after: bytes, before: bytes) -> bytes | None:
    """``current`` with the change ``before → after`` taken back (three-way; ``None`` on a conflict)."""
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        for name, data in (("current", current), ("after", after), ("before", before)):
            p = os.path.join(tmp, name)
            with open(p, "wb") as fh:
                fh.write(data)
            files.append(p)
        proc = subprocess.run(["git", "merge-file", "-p", "-q", *files], capture_output=True)
    return proc.stdout if proc.returncode == 0 else None


_LIST_FILES = frozenset({"_merge_rejected.yaml", "_predicates.yaml"})


def _reverse_list(rel: str, current: bytes, after: bytes, before: bytes) -> bytes | None:
    """The two bank lists a settle may add to — the pairs kept apart (``_merge_rejected.yaml``, kept sorted, so a
    later pair lands next to ours) and the confirmed label folds (``_predicates.yaml``) — taken back by meaning when
    the lines collide: only the entries this settle added are removed, anything added since stays."""
    import yaml

    try:
        b, a, c = (yaml.safe_load(x.decode("utf-8")) or {} for x in (before, after, current))
    except (yaml.YAMLError, UnicodeDecodeError):
        return None
    if not all(isinstance(x, dict) for x in (b, a, c)):
        return None
    if rel == "_merge_rejected.yaml":
        def pairs(x):
            return [tuple(sorted(map(str, r))) for r in (x.get("rejected") or []) if isinstance(r, (list, tuple))]
        added = set(pairs(a)) - set(pairs(b))
        c["rejected"] = [list(p) for p in sorted(set(pairs(c)) - added)]
        return yaml.safe_dump(c, allow_unicode=True, sort_keys=False).encode("utf-8")
    if rel == "_predicates.yaml":
        bf, af = dict(b.get("confirmed_folds") or {}), dict(a.get("confirmed_folds") or {})
        cf = dict(c.get("confirmed_folds") or {})
        for key, value in af.items():
            if bf.get(key) != value and cf.get(key) == value:
                cf.pop(key)
        c["confirmed_folds"] = cf
        return yaml.safe_dump(c, allow_unicode=True, sort_keys=False).encode("utf-8")
    return None


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def undo(memory_path: Path, item_id: str) -> tuple[str, list[str], list[str], dict]:
    """Take back one of Sleep's settles: the reverse of its commit, applied onto each file as it is now (refused whole
    when anything since conflicts with it), and the question back in the inbox, marked so Sleep never settles it
    again. Returns ``(restored id, paths, manifest lines, the record)``. The caller holds the bank and commits."""
    from api.services import inbox_service

    memory_path = Path(memory_path)
    if not re.fullmatch(r"inbox-\d{3,}", item_id or ""):
        raise NotUndoable("No such settled question.")
    record_rel = f"inbox/{SETTLED_DIR}/{item_id}.md"
    rec_path = memory_path / record_rel
    if not rec_path.exists():
        raise NotUndoable("No such settled question.")
    parsed = markdown_parser.parse(rec_path)
    fm = dict(parsed.frontmatter)
    rec = fm.pop("settled", None)
    if not isinstance(rec, dict) or rec.get("group") != GROUP:
        raise NotUndoable("No such settled question.")
    sha = _commit_of(memory_path, record_rel)
    if not sha:
        raise NotUndoable("The settle's commit could not be found; nothing was changed.")
    writes: list[tuple[str, bytes | None]] = []
    for rel in _changed(memory_path, sha):
        if rel in (f"inbox/{item_id}.md", record_rel):
            continue   # the question and its record are put back below
        before = _git_bytes(memory_path, f"{sha}^:{rel}")
        after = _git_bytes(memory_path, f"{sha}:{rel}")
        target = memory_path / rel
        current = target.read_bytes() if target.is_file() else None
        if current == before:
            continue
        if current == after:
            writes.append((rel, before))
        elif before is None and None not in (current, after) and rel in _LIST_FILES:
            merged = _reverse_list(rel, current, after, b"")
            if merged is None:
                raise NotUndoable("The list of pairs kept apart could not be read; nothing was changed.")
            writes.append((rel, merged))
        elif None not in (current, after, before):
            merged = _reverse(memory_path, current, after, before)
            if merged is None:
                merged = _reverse_list(rel, current, after, before)
            if merged is None:
                what = ("the list of pairs kept apart" if rel == "_merge_rejected.yaml"
                        else "the label map" if rel == "_predicates.yaml" else "the page")
                raise NotUndoable(f"{what[0].upper()}{what[1:]} changed since Sleep settled this, in the same place; "
                                  "nothing was changed. Answer the question in the app instead.")
            writes.append((rel, merged))
        else:
            raise NotUndoable("A page this settle wrote was moved or removed since; nothing was changed.")
    paths, lines = [], []
    for rel, data in writes:
        target = memory_path / rel
        if data is None:
            target.unlink(missing_ok=True)
        else:
            _write_bytes(target, data)
        paths.append(rel)
        lines.append(f"{rel}: updated (source: {item_id}, trigger: inbox/sleep-settle/undone)")
    inbox_dir = _inbox(memory_path)
    restored = item_id
    if (inbox_dir / f"{restored}.md").exists():   # never replace a question that took the number since
        restored = f"inbox-{inbox_service.next_inbox_num(inbox_dir):03d}"
    markdown_parser.write(inbox_dir / f"{restored}.md", {**fm, UNDONE_KEY: "undone"}, parsed.body)
    rec_path.unlink()
    bank_index.invalidate(memory_path)
    markdown_parser.invalidate_pages(os.path.realpath(memory_path))
    paths += [f"inbox/{restored}.md", record_rel]
    lines.append(f"inbox/{restored}.md: reopened (source: {item_id}, trigger: inbox/sleep-settle/undone)")
    return restored, paths, lines, rec


def record_undo(memory_path: Path, item_id: str, rec: dict) -> None:
    """The person took Sleep's assumption back: a grounded reward against that rule (G113), ids and enums only."""
    from api.services import telemetry

    try:
        telemetry.record(telemetry.UsageEvent(
            kind="resolution", stage="feedback", bank=Path(memory_path).name, invocations=0, billing="free",
            refs={"item_id": item_id, "kind": None, "action": "undo", "verdict": "overruled", "by": "person",
                  "settled_by": GROUP, "rule": str(rec.get("rule") or "") or None}))
    except Exception:  # noqa: BLE001
        pass
