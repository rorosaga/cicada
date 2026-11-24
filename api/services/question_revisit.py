"""Sleep looks at open questions again and closes the ones the record now answers (ruling 81, owner 2026-11-24).

The owner, on a card asking whether two people pages were one person when each page's own first sentence said so:
"questions with obvious answers [...] sleep could make sure to see open questions and close them with new information or
with a better agent that can find things out looking at other relevant conversations to close the question". Rulings 29
and 74 left a person's identity to the person's own words; this lets Sleep close an evident one itself.

**The gap.** Every lane that settles a question reads it once, on what one conversation or one pair of pages shows, with
the engine's small model or none: `inbox_tend` (moves 1 to 3), `person_duplicates.joins`, `full_name_join`, `typo_join`,
`same_name_tend`. Nothing looked at a question again after it was asked unless one of those happened to fire, and the
engine's main model reading both pages and the conversations that bear on a question had never been asked. This is that
second look, run at the end of Sleep after those lanes (a question one of them settled is gone; one that is theirs to hold
or to ask is not read here), and never a parallel lane: it settles through `inbox_tend.apply`, the one writer.

**What is read, per kind** (an unlisted kind is left as it is, and the dry run says so):

* ``merge_suggestion`` between two **person pages** (the owner's card): the new work, below.
* ``conflict`` / ``clarification`` / ``followup``: `inbox_tend.read_record_answer` (move 3) with the main model in place of
  the small one and a persistent memory in place of its in-process one — the person's own newest words, located in their
  own turn (``kind: user``), after every side of a conflict, the option those words state — and a second read, framed to
  find the other answer or none, that must name the same option. A value is never dropped (ruling 73): the resolver keeps
  the other.
* ``decay``: a later mention is itself the answer, and `inbox_tend` already closes that engine-free (``not_fading``);
  nothing else about a fading page is Sleep's. ``page_edit`` / ``sensitive`` are the person's or a trusted agent's.
* a ``merge_suggestion`` about a name with no page, and a same-name doubt: their own lanes (`full_name_join`,
  `same_name_tend`); not read here.

**Two people, one person** (`pair_case`, `assess`). The code finds and checks; the model only reads and copies.

1. Guards (engine-free): both ends person pages, neither the owner's, archived, a relation's or unnamed; never a pair the
   person called two, split or undid; never a page in a same-name doubt; no other person could be whom a short name
   means; no spelling in common; and `inbox_tend.policy` still says only the person settles it.
2. The evidence is **located** and each piece has a **kind**, counted as ruling 74 counts them (the name, an alias
   included, is one kind however it shows): ``name`` and ``contact`` are the code's (`person_duplicates`); ``belief`` is two
   lines the model copies, one about each side, found word for word in the text shown for their side (never fuzzy), each
   saying more than the name, sharing a specific word the bank does not hold on many pages (`typo_join.anchored`);
   ``said`` is one line, in ONE turn of ONE conversation (whoever's turn: its kind is recorded), located with
   `evidence.verify`, that itself carries both names and presents them as one person.
3. A pair closes only when a located ``said`` line holds, or when two kinds beyond that hold. A page's own prose that says
   so counts for nothing by itself: Sleep wrote it, and a quote must be in a conversation or a page's claim lines shown.
4. **Named together is not named as two** (the owner's card was blocked by "named together in 2 conversations"): every
   turn that names both is shown to the reader, whole, and a turn that names two people ("<A> and <B> both came") makes
   it "two". No word list decides that; the model reads each turn in its context, and a second read, framed to look
   for a reason they are two, never sees the first. Any "two", any unlocatable quote, any unusable reply and any error is
   "not answered": the question stays exactly as it is (ruling 73).
5. The join is one `inbox_tend.apply` (rule ``revisit_one``): the same resolver the person's tap uses, Sleep's commit,
   listed under "Settled by Sleep" with the reason in words and the spans; an undo is the person saying they are two
   (`inbox_tend.JOINS`).

**What was read is remembered outside every bank** (`question_revisits/<bank>.json`: ids, a digest and the reader's
model, never a word): a question is not read again until a page or conversation it read changed, a conversation about it
arrived, or the main model is a stronger one than the reader was (`stronger`).

**Order and bound.** `question_order.ranked`; at most :data:`MAX_READS` questions read per run (each is one to four model
calls); at most :data:`MAX_LOOKS` looked at; a question looked at recently goes behind those not. A scheduled run reaches a
plan only through ruling 4's switch, a metered key is held to the spending limit (calls go out under the ``inbox_tend``
stage, in `sleep_spend.LINE_STAGES`), a plan limit is a pause, a demo bank is never read. The only network reach is the
engine itself: no fetch, nothing here names a private person to any service.

Engine-free apart from the injected ``judge(system, prompt)`` and ``llm_fn``, the main model's calls.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import engine_errors, full_name_join, inbox_tend, pair_evidence, text_fold

RULE = "revisit_one"
#: Questions one run reads with a model (a pair is two to four calls, a record question one to three), and questions it
#: looks at (a look costs file reads and one index query, no model).
MAX_READS = 8
MAX_LOOKS = 120
#: A question looked at in the last this many days goes behind the ones that were not (so a drain reaches the whole inbox).
LOOK_AGAIN_DAYS = 3
#: What a pair's read shows: every turn that names both (more is no read: a counted skip), and some context turns.
MAX_BOTH_TURNS = 6
MAX_CONTEXT_TURNS = 4
TURN_CHARS = 1500
MAX_CONVERSATIONS = 24
MAX_FACTS = 8
FACT_CHARS = 260
REASON_QUOTE_CHARS = 110
MIN_QUOTE_CHARS = 12
#: A read that could not be made (no JSON, an exception) is tried this many times with the record unchanged.
MAX_UNREAD_TRIES = 2

SYSTEM = ("You decide, from what a person's memory and their conversations hold, whether two names are one real person "
          "or two, and you answer in JSON.")

SPEAKER = (' The speaker, the person whose conversations these are, appears in the memory as "{speaker}"; what someone '
           "is to the speaker is a fact about that someone like any other.")

PROMPT = """A person's memory holds two pages that may be ONE real person known by two names, or two different people.{speaker} Their conversations are below. Decide whether the record shows they are ONE person.

PERSON A: "{a}" (also written: {a_names}). What the memory holds about A:
{a_record}

PERSON B: "{b}" (also written: {b_names}). What the memory holds about B:
{b_record}

TURNS OF CONVERSATIONS, numbered, each with its day and who said it. The first group names BOTH; the second names one of them:
{turns}

Answer with one of:
- "one": the record presents the two names as the same person. Give EITHER "said": the number of one turn and, copied word for word and without gaps, the words of that turn that present the two names as one person (an apposition, "called", "also known as", "short for", a parenthesis, a nickname, in any language; the words must carry both names); OR "here" and "there": one line about A and one about B, each copied word for word from the memory shown for that side or from a turn that names it, that state the SAME specific fact about one individual (the same role, event, plan, place of residence, relation to the speaker). Sharing an employer, a school, a city, a team or a hobby is NOT the same fact: many people share those. You may give both.
- "two": the record has them as two different people: a turn names them together as two (a list, "A and B", one told apart from the other, one the relative or colleague of the other), or something in the memory cannot be true of one person.
- "cannot_tell": anything else.
Rules:
- A wrong join tells the person things about someone that are true of another; a question left costs little. When any turn or anything in the memory points to two people, say "two" or "cannot_tell".
- Both names in one turn is not one person: the words must present them as one, or as the same person across the record. A turn that names both in one breath as two people ("Teo and Teodor came") is evidence they are two; a turn that uses both names for the same person is not.
- Decide only from the memory and the turns shown. What you know about the names themselves (that one is usually short for the other) is no evidence.

Answer in JSON only: {{"verdict": "one" | "two" | "cannot_tell", "said_turn": <number or null>, "said": "words copied from that turn" | null, "here": "words copied about A" | null, "there": "words copied about B" | null, "reason": "one short sentence"}}
"""

SKEPTIC = """You are the sceptical reader. Your job is to look for any reason these two names are TWO people, or that the record does not show them as one, before you answer.

""" + PROMPT.replace("Answer with one of:", 'Answer with one of (say "one" only if, having looked for a reason they are two, you find none):')

CONFIRM = """A person wrote this line in one of their own conversations:

"{line}"

Open question about their memory: {question}
Options:
{options}
Proposed answer: {key}

Read the line in its own words, looking for the reason the proposed answer would be WRONG: it may be about someone or something else, an earlier time, a plan and not what happened, or it may not say which option holds. Which option does the line, by itself, plainly state? Reply JSON {{"option": "<key>" | "none", "reason": "<one short sentence>"}}."""


# --------------------------------------------------------------------------- shapes


@dataclass
class Side:
    id: str
    name: str
    names: list[str]
    texts: list[str]
    episodes: list[str]
    fm: dict = field(default_factory=dict)


@dataclass
class Turn:
    n: int
    episode: str
    day: str
    role: str       # person | assistant | speaker
    text: str
    both: bool


@dataclass
class Case:
    item_id: str
    a: Side
    b: Side
    turns: list[Turn]
    kinds: list[str]      # the code's kinds: name, contact
    fm: dict = field(default_factory=dict)


@dataclass
class Read:
    """One reply, after the code's checks: ``verdict`` ``one`` | ``two`` | ``cannot_tell`` | ``""`` (nothing usable).
    ``kinds``: the kinds of evidence the located words add (``said``, ``belief``); ``spans``: where they were found."""
    verdict: str = ""
    kinds: list[str] = field(default_factory=list)
    spans: list[dict] = field(default_factory=list)
    quote: str = ""
    here: str = ""
    there: str = ""
    reason: str = ""
    model: str = ""


@dataclass
class Assessment:
    """``outcome``: ``join`` | ``two`` | ``unsure`` | ``unread`` | ``skip`` (a guard; ``why``). ``reads``: model calls made."""
    outcome: str
    why: str = ""
    decision: object = None
    reads: int = 0
    case: Case | None = None
    digest: str = ""


@dataclass
class Report:
    looked: int = 0
    read: int = 0
    settled: int = 0
    calls: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)
    #: ``{kind: {outcome: n}}`` — counts only, never an id.
    by_kind: dict[str, dict[str, int]] = field(default_factory=dict)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def count(self, kind: str, outcome: str) -> None:
        row = self.by_kind.setdefault(kind or "unknown", {})
        row[outcome] = row.get(outcome, 0) + 1


# --------------------------------------------------------------------------- what the code knows of a pair


def _key(text) -> str:
    return pair_evidence.spelling(text)


def _plain(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word) if not unicodedata.combining(c))


def _surfaces(names: list[str]) -> frozenset[str]:
    """A one-word name as the record writes it (accents off, case kept): "Will" the page is not "will" the verb."""
    return frozenset(_plain(n.strip()) for n in names if len(_key(n).split()) == 1)


def _hits(a_names: list[str], b_names: list[str], text: str) -> tuple[bool, bool]:
    """``(names A, names B)`` as whole words, with a longer spelling's words taken out first: the short name inside the
    full name ("Teo" in "Teo Brandt") says nothing about the page called "Teo"."""
    words = [(text_fold.fold(w), _plain(w)) for w in re.findall(r"[^\W_]+", str(text or ""))]
    folded = [f for f, _p in words]
    taken = [False] * len(words)
    found = {"a": False, "b": False}
    multi = sorted(((side, k.split()) for side, names in (("a", a_names), ("b", b_names)) for k in map(_key, names)
                    if len(k.split()) > 1), key=lambda t: -len(t[1]))
    for side, parts in multi:
        for at in range(len(words) - len(parts) + 1):
            if folded[at:at + len(parts)] == parts and not any(taken[at:at + len(parts)]):
                taken[at:at + len(parts)] = [True] * len(parts)
                found[side] = True
    for side, names in (("a", a_names), ("b", b_names)):
        surfaces = _surfaces(names)
        for (_f, plain), gone in zip(words, taken):
            if not gone and plain in surfaces:
                found[side] = True
    return found["a"], found["b"]


def _names_both(a_names: list[str], b_names: list[str], text: str) -> bool:
    a, b = _hits(a_names, b_names, text)
    return a and b


def _page_pairs(memory_path: Path) -> dict[tuple[str, str], list[str]]:
    """What the code's own machinery says about each pair of people pages: the kinds of evidence the pages carry
    (``person_duplicates.candidates`` at floor 0: names, an alias, a shared account). One read per run."""
    from api.services import person_duplicates

    out: dict[tuple[str, str], list[str]] = {}
    for pair in person_duplicates.candidates(Path(memory_path), floor=0.0):
        kinds = [k for k in person_duplicates.kinds_of(pair.signals) if k in ("name", "contact")]
        out[tuple(sorted((pair.a, pair.b)))] = kinds
    return out


def _removed_from(fm: dict | None, names: list[str]) -> bool:
    from api.services import typo_join

    return typo_join._removed_from(fm, names)


def _turn_rows(memory_path: Path, episode_id: str) -> list[tuple[str, str]]:
    """``[(role, text)]`` of one conversation: every turn that is someone's words (never Cicada's gap line, a page or a
    media marker), the role as `evidence.turns` says it (``user`` → ``person``)."""
    from api.services import authorship, evidence

    doc = evidence.source_document(Path(memory_path), episode_id)
    if doc is None:
        return []
    ep_fm, text = doc
    out = []
    for t in evidence.turns(text, override=authorship.of(ep_fm), gaps=evidence.gap_ranges(ep_fm, text)):
        if t.role not in ("user", "assistant", "speaker"):
            continue
        body = text[t.content_start:t.end].strip()
        if body:
            out.append(("person" if t.role == "user" else t.role, body))
    return out


def _episode_day(memory_path: Path, episode: str) -> str:
    return str(pair_evidence.episode_timestamp(memory_path, episode) or "")[:10]


def _conversations(memory_path: Path, fm: dict, a: Side, b: Side) -> list[str]:
    """The conversations that bear on the pair, never a scan: the question's own, each page's own, and what the lexical
    index finds holding a spelling of each side."""
    from api.services import search_index

    named = [str(fm.get("source_episode") or ""), *a.episodes[-12:][::-1], *b.episodes[-12:][::-1]]
    keys_a, keys_b = [_key(n) for n in a.names][:4], [_key(n) for n in b.names][:4]
    try:
        pair_evidence.fresh_index(memory_path)
        both = search_index.episodes_naming_each(Path(memory_path), (keys_a, keys_b), 12)
        # What was said about either side since: the newest conversations first, so new information is always seen.
        one = [e for names in (keys_a, keys_b) for e in pair_evidence._search(Path(memory_path), names, fresh=False)][:12]
    except Exception:  # noqa: BLE001 - a derived index only finds less
        both, one = [], []
    found = [e for e in dict.fromkeys([*named, *both, *one]) if e.startswith("ep_")]
    return found[:MAX_CONVERSATIONS]


def _turns_for(memory_path: Path, episodes: list[str], a: Side, b: Side) -> tuple[list[Turn], str]:
    """``(turns, "")`` — every turn naming both, then a few naming one — or ``([], why)``: a turn naming both that is too
    long, or more of them than are shown, is no read (never a silent cut that could hide the turn that says two)."""
    both: list[Turn] = []
    context: list[Turn] = []
    for eid in episodes:
        day = _episode_day(memory_path, eid)
        for role, text in _turn_rows(memory_path, eid):
            on_a, on_b = _hits(a.names, b.names, text)
            if on_a and on_b:
                if len(text) > TURN_CHARS:
                    return [], "turn_too_long"
                both.append(Turn(0, eid, day, role, text, True))
            elif (on_a or on_b) and len(text) <= TURN_CHARS:
                context.append(Turn(0, eid, day, role, text, False))
        if len(both) > MAX_BOTH_TURNS:
            return [], "too_many_turns"
    # What was said since is what a read must see: the newest few of the turns that name one side only.
    context = sorted(context, key=lambda t: (t.day, t.episode), reverse=True)[:MAX_CONTEXT_TURNS]
    both.sort(key=lambda t: (t.day, t.episode))
    turns = [*both, *context]
    for i, t in enumerate(turns, 1):
        t.n = i
    return turns, ""


def _page_lines(memory_path: Path, pid: str) -> list[str]:
    """What the memory holds about one page, as the reader is shown it: a description per conversation
    (`same_name_tend.page_of`, the page's sourced prose) and, past those, the page's own lines and the claims on it — each
    one a text a quote may be found in. Bounded; the page's own prose says what Sleep wrote, never a conversation."""
    from api.services import typo_join
    from api.services.claims import parse_claims, strip_claims_block

    out = list(typo_join._page_texts(memory_path, pid))
    page = inbox_tend._page(memory_path, pid)
    if page is not None:
        try:
            out += [_trim(c.text, FACT_CHARS) for c in parse_claims(page[2]) if getattr(c, "text", "") and c.valid_to is None]
        except Exception:  # noqa: BLE001 - claims unreadable: the prose still reads
            pass
        out += [_trim(re.sub(r"^[-*#\s]+", "", ln), FACT_CHARS) for ln in strip_claims_block(page[2]).splitlines()
                if re.sub(r"^[-*#\s]+", "", ln).strip() and not ln.lstrip().startswith("#")]
    return [t for t in dict.fromkeys(t for t in out if t)][:MAX_FACTS]


def _side(memory_path: Path, pid: str, fm: dict) -> Side:
    return Side(pid, str(fm.get("name") or pid), full_name_join._names_of(fm), _page_lines(memory_path, pid),
                [str(e) for e in (fm.get("source_episodes") or ()) if e], dict(fm))


def pair_case(memory_path: Path, path: Path, fm: dict, pairs: dict[tuple[str, str], list[str]] | None = None,
              *, today: str | None = None) -> tuple[Case | None, str]:
    """``(case, "")`` when every engine-free condition holds for this open question (the module's list, 1), else
    ``(None, why it is left)``. Reads only."""
    from api.services import merge_rejections, role_people, same_name_doubts
    from api.services.id_utils import resolve_entity_file

    memory_path = Path(memory_path)
    if (str(fm.get("kind") or "") != "merge_suggestion" or str(fm.get("status") or "pending") != "pending"
            or str(fm.get("detected") or "") not in ("", "person_duplicate") or fm.get("same_title")
            or fm.get("heard_in") or fm.get("tidy")):
        return None, "not_this_question"
    people = dict(full_name_join._person_pages(memory_path))
    asked = resolve_entity_file(memory_path, str(fm.get("entity_id") or "")) if fm.get("entity_id") else None
    target_id = str(fm.get("merge_target_hint") or "").strip()
    if asked is None or not target_id:
        return None, "not_two_pages"
    a_id = asked.stem
    afm, tfm = people.get(a_id), people.get(target_id)
    if afm is None or tfm is None:
        return None, "not_two_people_pages"
    if a_id == target_id:
        return None, "same_page"
    # The cheap shape first; the rule that decides engine-free (a search among them) only for a pair of this shape.
    decided, why = inbox_tend.policy(memory_path, path, fm, today=today)
    if decided is not None or why != "person":
        return None, f"policy:{why or 'decided'}"
    for pid, pfm in ((a_id, afm), (target_id, tfm)):
        if pfm.get("owner") is True or str(pfm.get("status") or "").lower() in ("archived", "dropped"):
            return None, "owner_or_gone"
        if role_people.parse(str(pfm.get("name") or pid)) is not None or pfm.get("unnamed"):
            return None, "role_page"
    a_names, b_names = full_name_join._names_of(afm), full_name_join._names_of(tfm)
    if {_key(n) for n in a_names} & {_key(n) for n in b_names}:
        return None, "one_spelling"
    if _removed_from(afm, b_names) or _removed_from(tfm, a_names):
        return None, "alias_removed"
    if (merge_rejections.is_rejected(memory_path, a_id, target_id) or merge_rejections.is_split(memory_path, a_id, target_id)
            or inbox_tend._split_apart(memory_path, a_id, target_id)):
        return None, "kept_apart"
    flagged_pages, flagged_pairs = same_name_doubts.flagged(memory_path)
    for pid in (a_id, target_id):
        if (same_name_doubts.doubts_of(memory_path, pid) or pid in flagged_pages
                or any(pid in pair for pair in flagged_pairs) or pid in same_name_doubts.one(memory_path)):
            return None, "in_a_doubt"
    # A short name that could be someone else is no join for Sleep: a page that could be either waits for the person.
    mine = {a_id, target_id}
    for names in (a_names, b_names):
        for short in {_key(n) for n in names if len(_key(n).split()) == 1}:
            for pid, pfm in people.items():
                if pid not in mine and full_name_join._could_mean(short, full_name_join._names_of(pfm)):
                    return None, "short_name_not_alone"
    a, b = _side(memory_path, a_id, afm), _side(memory_path, target_id, tfm)
    pairs = pairs if pairs is not None else _page_pairs(memory_path)
    kinds = list(pairs.get(tuple(sorted((a_id, target_id))), []))
    turns, why = _turns_for(memory_path, _conversations(memory_path, fm, a, b), a, b)
    if why:
        return None, why
    if not any(t.both for t in turns) and not kinds:
        return None, "nothing_ties_them"   # neither a turn that could present them as one nor a kind of evidence of the code's
    if not b.texts and not a.texts:
        return None, "nothing_to_read"
    return Case(path.stem, a, b, turns, kinds, dict(fm)), ""


# --------------------------------------------------------------------------- the reads


def _trim(text, limit: int = FACT_CHARS) -> str:
    return full_name_join._trim(text, limit)


def _lines(items: list[str]) -> str:
    return "\n".join(f"- {t}" for t in items) or "- (nothing)"


def build_prompt(case: Case, speaker: str | None, *, skeptic: bool = False) -> str:
    named = " ".join(str(speaker or "").replace('"', "").split())

    def others(side: Side) -> str:
        return ", ".join(f"“{n}”" for n in side.names if _key(n) != _key(side.name)) or "no other name"

    def shown(group: list[Turn]) -> str:
        return "\n".join(f"[{t.n}] ({t.day or 'undated'}, {t.role}) {t.text}" for t in group) or "(none)"

    both = [t for t in case.turns if t.both]
    one = [t for t in case.turns if not t.both]
    turns = f"NAMING BOTH:\n{shown(both)}\n\nNAMING ONE:\n{shown(one)}"
    return (SKEPTIC if skeptic else PROMPT).format(
        speaker=SPEAKER.format(speaker=named) if named else "", a=case.a.name.replace('"', ""),
        b=case.b.name.replace('"', ""), a_names=others(case.a), b_names=others(case.b),
        a_record=_lines(case.a.texts), b_record=_lines(case.b.texts), turns=turns)


def _quote_span(memory_path: Path, case: Case, quote: str) -> tuple[Turn, str, dict] | None:
    """The quote located (`evidence.verify`: exact, whitespace, case; never fuzzy) inside ONE turn shown, with whose words
    they are recorded: ``(turn, the words as located, span)``. ``None`` when it is in no turn, is longer than the
    evidence cap, touches a line the speaker quoted from someone else (a ``>`` block), or is not someone's own words."""
    from api.services import evidence

    if len(quote) > evidence.MAX_QUOTE_CHARS:
        return None
    for turn in case.turns:
        hit = evidence.locate(turn.text, quote)
        if hit is None:
            continue
        start, end = hit
        first = turn.text.rfind("\n", 0, start) + 1
        if any(line.lstrip().startswith(">") for line in turn.text[first:end].split("\n")):
            return None
        words = turn.text[start:end]
        ev = evidence.verify(Path(memory_path), turn.episode, words)
        if not ev.is_span() or ev.kind not in ("user", "assistant", "speaker"):
            return None
        return turn, words, {"episode": ev.episode, "start": ev.start, "end": ev.end, "kind": ev.kind}
    return None


def _anchored(memory_path: Path, case: Case, here: str, there: str, speaker: str | None) -> bool:
    from api.services import typo_join

    shim = typo_join.Case(case.item_id,
                          typo_join.Side(case.a.id, case.a.name, case.a.names, case.a.texts, case.a.episodes, True),
                          typo_join.Side(case.b.id, case.b.name, case.b.names, case.b.texts, case.b.episodes, True), [])
    return typo_join.anchored(memory_path, shim, typo_join.Read(here=here, there=there), speaker)


def located(memory_path: Path, case: Case, parsed: dict, speaker: str | None = None) -> Read:
    """What a reply stands on. ``one`` only when the words it copied are found where it says (a turn shown; the memory
    shown for the side), say what they must, and add a kind of evidence; anything else is withdrawn."""
    from api.services import same_name_people as snp

    verdict = str(parsed.get("verdict") or "").strip().lower().replace(" ", "_")
    reason = _trim(parsed.get("reason"), 200)
    model = str(parsed.get("_model") or "")
    if verdict in ("two", "different"):
        return Read("two", reason=reason, model=model)
    if verdict != "one":
        return Read("cannot_tell" if verdict == "cannot_tell" else "", reason=reason, model=model)
    kinds: list[str] = []
    spans: list[dict] = []
    said = " ".join(str(parsed.get("said") or "").split())
    quote = ""
    if said and said.lower() != "null":
        found = (None if len(re.sub(r"\W+", "", said)) < MIN_QUOTE_CHARS or "…" in said or "..." in said
                 else _quote_span(memory_path, case, said))
        if found is not None and _names_both(case.a.names, case.b.names, found[1]):
            kinds.append("said")
            spans.append(found[2])
            quote = found[1]
    here, there = " ".join(str(parsed.get("here") or "").split()), " ".join(str(parsed.get("there") or "").split())
    if here and there and here.lower() != "null" and there.lower() != "null":
        a_texts = [*case.a.texts, *[t.text for t in case.turns if _hits(case.a.names, case.b.names, t.text)[0]]]
        b_texts = [*case.b.texts, *[t.text for t in case.turns if _hits(case.a.names, case.b.names, t.text)[1]]]
        flipped = snp._located(here, b_texts) and snp._located(there, a_texts) and not snp._located(here, a_texts)
        ours, theirs = (case.b, case.a) if flipped else (case.a, case.b)
        if (snp._squash(here) != snp._squash(there)
                and snp._located(here, b_texts if flipped else a_texts) and snp._located(there, a_texts if flipped else b_texts)
                and snp._says(here, ours.name) and snp._says(there, theirs.name)
                and _anchored(memory_path, case, here, there, speaker)):
            kinds.append("belief")
    if not kinds:
        return Read("cannot_tell", reason="the words quoted are not in the record, or add nothing", model=model)
    return Read("one", kinds, spans, quote, here, there, reason, model)


def enough(case_kinds: list[str], read: Read) -> bool:
    """Ruling 74's bar, on located evidence: a located line that says they are one, or two independent kinds."""
    if "said" in read.kinds:
        return True
    return len(set(case_kinds) | set(read.kinds)) >= 2


async def _read(memory_path: Path, case: Case, judge, speaker, *, skeptic: bool) -> Read:
    try:
        parsed = await judge(SYSTEM, build_prompt(case, speaker, skeptic=skeptic))
    except asyncio.CancelledError:
        raise
    except engine_errors.EngineError:
        raise
    except Exception as exc:  # noqa: BLE001 - a read that failed has read nothing
        logger.debug(f"Question revisit read failed: {type(exc).__name__}")
        return Read()
    return located(memory_path, case, parsed, speaker) if isinstance(parsed, dict) else Read()


def _reason(case: Case, read: Read) -> str:
    from api.services import episode_scrub

    if "said" in read.kinds:
        text = f"A conversation presents them as one person: “{_trim(read.quote, REASON_QUOTE_CHARS)}”"
    else:
        text = (f"Their names, and “{_trim(read.here, REASON_QUOTE_CHARS)}” and “{_trim(read.there, REASON_QUOTE_CHARS)}”, "
                "say the same thing about one person.")
    return episode_scrub.scrub(text)[0]


def _guard(memory_path: Path, case: Case) -> dict:
    return inbox_tend._guard(memory_path, case.a.id, case.b.id)


def digest(memory_path: Path, case: Case) -> str:
    """What a read stood on, so the same question is not read again until something it read changed."""
    h = hashlib.sha256()
    for part in (json.dumps(_guard(memory_path, case), sort_keys=True), json.dumps(case.kinds),
                 json.dumps([(t.episode, t.text) for t in case.turns]), case.a.id, case.b.id):
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()[:20]


async def assess(memory_path: Path, path: Path, fm: dict, judge, *, speaker: str | None = None, today: str | None = None,
                 pairs: dict | None = None, case: Case | None = None) -> Assessment:
    """The guards, then up to two reads. Writes nothing. What the settle re-checks (the question's bytes, the pages'
    hashes) is taken BEFORE the first read, so a change while the model reads leaves the question. An engine failure is
    the caller's (a plan limit is a pause)."""
    memory_path = Path(memory_path)
    why = ""
    if case is None:
        case, why = await asyncio.to_thread(pair_case, memory_path, path, fm, pairs, today=today)
    if case is None:
        return Assessment("skip", why)
    fingerprint = path.read_bytes()
    guard = _guard(memory_path, case)
    mark = digest(memory_path, case)
    result = Assessment("unread", reads=0, case=case, digest=mark)
    first = await _read(memory_path, case, judge, speaker, skeptic=False)
    result.reads = 1
    if first.verdict == "two":
        result.outcome = "two"
        return result
    if first.verdict != "one":
        result.outcome = "unsure" if first.verdict == "cannot_tell" else "unread"
        return result
    if not enough(case.kinds, first):
        result.outcome = "unsure"
        return result
    second = await _read(memory_path, case, judge, speaker, skeptic=True)
    result.reads = 2
    if second.verdict != "one":
        result.outcome = "two" if second.verdict == "two" else "unsure" if second.verdict == "cannot_tell" else "unread"
        return result
    if not enough(case.kinds, second):
        result.outcome = "unsure"
        return result
    result.outcome = "join"
    model = first.model if first.model and first.model == second.model else None
    spans = [*first.spans]
    user = next((s for s in spans if s.get("kind") == "user"), None)
    quote = None
    if user is not None:
        quote = {"episode": user["episode"], "quote": first.quote}
    result.decision = inbox_tend.Decision(
        case.item_id, "merge_suggestion", RULE, {"action": "merge", "merge_target": case.b.id},
        answer=f"Same as {case.b.name}", quote=quote, model=model, fingerprint=fingerprint, guard=guard,
        reason=_reason(case, first), spans=spans)
    return result


def still_holds(memory_path: Path, d) -> bool:
    """Inside the settle (`inbox_tend.still_holds`): the engine-free conditions are still met for the very question and the
    very pages the reads were about."""
    memory_path = Path(memory_path)
    path = memory_path / "inbox" / f"{d.item_id}.md"
    try:
        from api.services import markdown_parser

        fm = dict(markdown_parser.parse(path).frontmatter)
    except Exception:  # noqa: BLE001
        return False
    case, _why = pair_case(memory_path, path, fm)
    return case is not None and case.b.id == str((d.request or {}).get("merge_target") or "")


# --------------------------------------------------------------------------- what was read, outside every bank


def _seen_file(memory_path: Path) -> Path:
    from api.services import auth, continuity_sessions

    return auth.cicada_home() / "question_revisits" / f"{continuity_sessions.bank_file_id(Path(memory_path))}.json"


def _seen(memory_path: Path) -> dict[str, dict]:
    try:
        data = json.loads(_seen_file(memory_path).read_text(encoding="utf-8"))
        return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_seen(memory_path: Path, data: dict[str, dict]) -> None:
    """Ids, a digest, a model name and a day only, never a name or a word; a file that cannot be written only means a
    question is read again."""
    try:
        path = _seen_file(memory_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


#: A model's rank among those of one family, the names the engines report (a name that is none of these is only
#: "different"). Used for one question: is the main model now a stronger one than the reader was.
_RANKS = (("haiku", 1), ("sonnet", 2), ("opus", 3), ("fable", 4))


def _rank(model: str) -> int:
    low = str(model or "").lower()
    return next((r for name, r in _RANKS if name in low), 0)


def stronger(now: str, before: str) -> bool:
    """Is ``now`` a stronger reader than ``before``? Two known families by rank; otherwise a model that is no longer the
    one that read (a change the person made) counts once."""
    if not before or not now:
        return False
    if _rank(now) and _rank(before):
        return _rank(now) > _rank(before)
    return now != before


def fresh_read(entry: dict | None, mark: str, model: str) -> bool:
    """Has this question to be read? Yes when it never was, when something it read changed (``mark``), or when the main
    model is now a stronger one than the reader was."""
    if not entry or entry.get("d") != mark:
        return True
    return stronger(model, str(entry.get("m") or ""))


# --------------------------------------------------------------------------- the record kinds


async def confirm_option(memory_path: Path, llm_fn, fm: dict, d) -> bool:
    """The second read of a conflict's or follow-up's answer from the person's words: it sees only the line, the question
    and the options, is framed to find why the answer is wrong, and must name the same option."""
    from api.services import inbox_questions

    if d.quote is None or str((d.request or {}).get("action") or "") != "resolve":
        return True
    key = str(d.request.get("option_key") or "")
    if str(fm.get("kind") or "") == "followup":
        options, question, _heard = inbox_tend._followup_choices(Path(memory_path), fm)
    else:
        options = {str(o.get("key")): str(o.get("label") or "") for o in inbox_questions.normalize_options(fm.get("options"))
                   if str(o.get("key")) not in inbox_tend._GENERIC_KEYS}
        question = str(fm.get("question") or fm.get("title") or "")
    options = options or {key: d.answer}
    prompt = CONFIRM.format(line=d.quote["quote"], question=question or str(fm.get("title") or ""),
                            options="\n".join(f"- {k}: {v}" for k, v in options.items()), key=key)
    reply, _model = await inbox_tend._ask(llm_fn, prompt)
    return str(reply.get("option") or "").strip() == key


def record_material(memory_path: Path, fm: dict) -> tuple[list, str]:
    """``(lines, digest)``: the person's own lines the whole record holds that bear on the question and came after it
    (`inbox_tend.record_lines`: the pages' own conversations and what the lexical index finds, never a scan) and a digest
    of them with the page they are read against. No lines: nothing is read and nothing is sent."""
    lines = inbox_tend.record_lines(Path(memory_path), fm)
    if not lines:
        return [], ""
    h = hashlib.sha256("\n".join([str(fm.get("kind") or ""), str(fm.get("question") or ""),
                                  *[f"{tag}|{eid}|{line}" for tag, eid, line in lines]]).encode("utf-8"))
    h.update(json.dumps(inbox_tend._guard(Path(memory_path), str(fm.get("entity_id") or "")), sort_keys=True).encode("utf-8"))
    return lines, h.hexdigest()[:20]


# --------------------------------------------------------------------------- the tail step


def _eligible(memory_path: Path, today: str) -> list[tuple[Path, dict]]:
    """Open questions of a kind this step reads, ordered as the inbox serves them (`question_order`, ruling 70)."""
    from api.services import question_order

    rows = []
    for path, fm, _body in inbox_tend.pending(Path(memory_path)):
        if inbox_tend._blocked(fm, today):
            continue
        kind = str(fm.get("kind") or "")
        if kind == "merge_suggestion":
            if str(fm.get("detected") or "") == "same_name_doubt":
                continue
        elif kind not in inbox_tend.RECORD_KINDS or str(fm.get("asks") or "") in ("speaker", "sources", "still"):
            continue
        rows.append((path, fm))
    if len(rows) > 1:
        order = question_order.ranked(Path(memory_path), [(p.stem, fm) for p, fm in rows])
        pos = {item: i for i, item in enumerate(order)}
        rows.sort(key=lambda r: pos.get(r[0].stem, len(pos)))
    return rows


def _recently(entry: dict | None, today: date) -> bool:
    try:
        return bool(entry) and (today - date.fromisoformat(str(entry.get("at") or ""))).days < LOOK_AGAIN_DAYS
    except ValueError:
        return False


def candidates(memory_path: Path, *, today: date | None = None) -> list[tuple[Path, dict]]:
    """What a run walks: the eligible questions in order, those not looked at lately first (so a bound walks the whole
    inbox over a few nights, never the same top of it every night)."""
    today = today or date.today()
    rows = _eligible(memory_path, today.isoformat())
    seen = _seen(memory_path)
    fresh = [r for r in rows if not _recently(seen.get(r[0].stem), today)]
    return [*fresh, *[r for r in rows if r not in fresh]]


def _judge_from(llm_fn):
    """``judge(system, prompt)`` over the engine's blocking call (stage ``inbox_tend``: a metered key is held to the
    spending limit, a plan to ruling 4's switch), JSON back with the model that answered."""
    from api.services import json_parse

    async def judge(system: str, prompt: str) -> object:
        resp = await asyncio.to_thread(llm_fn, messages=[{"role": "system", "content": system},
                                                         {"role": "user", "content": prompt}],
                                       response_format={"type": "json_object"})
        parsed = json_parse.parse_json_object_or(inbox_tend._content(resp), {})
        model = inbox_tend._model_of(resp)
        return {**parsed, "_model": model} if model and isinstance(parsed, dict) else parsed

    return judge


async def tend(memory_path: Path, settings, llm_fn, *, today: date | None = None, max_reads: int = MAX_READS,
               max_looks: int = MAX_LOOKS, dry_run: bool = False, trace=None, model: str = "") -> Report:
    """Look at the open questions in order and settle the ones the record answers. The model runs outside any write; each
    settle is one `inbox_tend.apply` (Sleep's window is held by the caller). Never raises but for an engine failure,
    which stops the step (the questions are read again next drain). ``dry_run``: reads and counts, writes nothing, and
    remembers nothing. ``trace(row)`` is handed one row per question looked at: ids and enums only."""
    memory_path = Path(memory_path)
    today = today or date.today()
    report = Report()
    seen = _seen(memory_path)
    judge = _judge_from(llm_fn) if llm_fn is not None else None
    speaker: str | None = None
    pairs: dict | None = None

    def note(item_id: str, kind: str, what: str, rule: str = "", evidence: list | None = None) -> None:
        report.count(kind, what)
        if trace is not None:
            trace({"id": item_id, "kind": kind, "what": what, "rule": rule, "evidence": evidence or []})

    def remember(item_id: str, mark: str, outcome: str, tries: int = 0) -> None:
        if not dry_run:
            seen[item_id] = {"d": mark, "m": model, "o": outcome, "at": today.isoformat(), "t": tries}

    try:
        for path, fm in await asyncio.to_thread(candidates, memory_path, today=today):
            if report.read >= max_reads:
                report.skip("max_reads")
                break
            if report.looked >= max_looks:
                report.skip("max_looks")
                break
            report.looked += 1
            item_id, kind = path.stem, str(fm.get("kind") or "")
            entry = seen.get(item_id)
            if kind == "merge_suggestion":
                if pairs is None:
                    pairs = await asyncio.to_thread(_page_pairs, memory_path)
                case, why = await asyncio.to_thread(pair_case, memory_path, path, fm, pairs, today=today.isoformat())
                if case is None:
                    report.skip(why)
                    note(item_id, kind, f"left:{why}")
                    continue
                mark = await asyncio.to_thread(digest, memory_path, case)
                tried = bool(entry and entry.get("d") == mark and entry.get("o") == "unread"
                             and int(entry.get("t") or 0) >= MAX_UNREAD_TRIES and not stronger(model, str(entry.get("m") or "")))
                if not fresh_read(entry, mark, model) or tried:
                    report.skip("read_already")
                    note(item_id, kind, "left:read_already")
                    continue
                if judge is None:
                    note(item_id, kind, "would_read", RULE)
                    continue
                if speaker is None:
                    from api.services import same_name_tend

                    speaker = await asyncio.to_thread(same_name_tend._speaker, memory_path) or ""
                result = await assess(memory_path, path, fm, judge, speaker=speaker or None, today=today.isoformat(), pairs=pairs,
                                      case=case)
                report.read += 1
                report.calls += result.reads
                if result.outcome != "join" or result.decision is None:
                    tries = int(entry.get("t") or 0) + 1 if entry and entry.get("d") == mark else 1
                    remember(item_id, mark, result.outcome, tries if result.outcome == "unread" else 0)
                    note(item_id, kind, f"read:{result.outcome}")
                    continue
                d = result.decision
                if dry_run:
                    report.settled += 1
                    note(item_id, kind, "would_join", RULE, d.spans)
                    continue
                try:
                    ok = await inbox_tend.apply(memory_path, settings, d)
                except Exception as exc:  # noqa: BLE001 - one join that will not settle never stops the others
                    logger.info(f"Question revisit not applied: {type(exc).__name__}")
                    ok = False
                if ok:
                    report.settled += 1
                    report.paths.append(f"inbox/settled/{d.item_id}.md")
                    seen.pop(item_id, None)
                    note(item_id, kind, "joined", RULE, d.spans)
                else:
                    remember(item_id, mark, "not_applied", 1)
                    note(item_id, kind, "left:not_applied")
                continue
            # conflict / clarification / followup: the person's own newest words, anywhere in the record.
            decided, why = await asyncio.to_thread(inbox_tend.policy, memory_path, path, fm, today=today.isoformat())
            if decided is not None or why in inbox_tend._RECORD_SKIP:
                report.skip(f"policy:{why or 'decided'}")
                note(item_id, kind, f"left:policy:{why or 'decided'}")
                continue
            lines, mark = await asyncio.to_thread(record_material, memory_path, fm)
            if not lines:
                remember(item_id, "", "idle")
                note(item_id, kind, "left:not_on_record")
                continue
            if not fresh_read(entry, mark, model):
                report.skip("read_already")
                note(item_id, kind, "left:read_already")
                continue
            if llm_fn is None:
                note(item_id, kind, "would_read", "said_on_record")
                continue
            fingerprint = path.read_bytes()
            d, why = await inbox_tend.read_record_answer(memory_path, path, fm, llm_fn, lines=lines, memory=None)
            report.read += 1
            report.calls += 2 if d is not None else 1
            if d is not None and not await confirm_option(memory_path, llm_fn, fm, d):
                d, why = None, "not_confirmed"
                report.calls += 1
            if d is None:
                remember(item_id, mark, why)
                note(item_id, kind, f"read:{why}")
                continue
            d.fingerprint = fingerprint
            if dry_run:
                report.settled += 1
                note(item_id, kind, "would_settle", d.rule, [{"episode": d.quote["episode"]}] if d.quote else [])
                continue
            try:
                ok = await inbox_tend.apply(memory_path, settings, d)
            except Exception as exc:  # noqa: BLE001
                logger.info(f"Question revisit not applied: {type(exc).__name__}")
                ok = False
            if ok:
                report.settled += 1
                report.paths.append(f"inbox/settled/{d.item_id}.md")
                seen.pop(item_id, None)
                note(item_id, kind, "settled", d.rule)
            else:
                remember(item_id, mark, "not_applied")
                note(item_id, kind, "left:not_applied")
    finally:
        if not dry_run:
            _save_seen(memory_path, seen)    # what was read before an engine stopped the step is still remembered
    return report


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, llm_fn=None, today: date | None = None,
                   model: str = "") -> Report:
    """Sleep's tail step (after the join lanes, inside the run's window): no engine is resolved and nothing is sent unless
    an open question is of a kind read here. A scheduled run reaches a plan only through the person's switch (ruling 4b), a
    plan limit is a pause (the questions stay), no engine means no read, a demo bank is never read. Never raises."""
    from api.services import demo_guard, engine_select, same_name_tend

    memory_path = Path(memory_path)
    report = Report()
    try:
        if demo_guard.is_demo(memory_path):
            report.skip("demo")
            return report
        if not await asyncio.to_thread(candidates, memory_path, today=today):
            return report
        if llm_fn is None:
            strong, why = await same_name_tend.main_engine(settings, user_triggered=user_triggered)
            if strong is None:
                report.skip(why)
                return report
            llm_fn = inbox_tend.default_llm_fn(strong)
            model = model or engine_select.shown_model(strong)
        return await tend(memory_path, settings, llm_fn, today=today, model=model)
    except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
        report.skip("plan_limit")
    except Exception as exc:  # noqa: BLE001 - the revisit never fails a Sleep
        logger.warning(f"Question revisit stopped: {type(exc).__name__}")
        report.skip("error")
    return report
