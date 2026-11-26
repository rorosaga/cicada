"""Context decides which one was meant, and only then is anyone asked (ruling 83, first half; owner 2026-11-25/26).

The owner, twice in two days: "if its not implied in the context then a better question is 'were you talking about your brother
or <Full Name>?' like a human would", and "my biggest thing is stuff that surges in questions that can clearly be resolved by
reading context from different sources ... if you ask a claude code session with the same context it would figure it out
easy". `which_one` built the question's form; this is what comes BEFORE it: a mention that could be two or more known pages is
filed under the one its own conversation points to, and nobody is asked. On the owner's memory the case that started this was a
nickname two people answer to: in each conversation the words around it said which one ("my brother" beside it in one, a full
name and "my teammate" in another).

**Where it runs.** A Sleep tail step, after the lanes that raise or rewrite the question (Stage 2 and the clarifier raise it in
this form from the start, `ClarificationManager.create`; `which_one.tend` rewrites what was stored pairwise), over the open
which-one questions, in the inbox's own order (`question_order`), a few a run. It is the same reader shape as `described_landing`
and `question_revisit`: code before, the engine's main model reads twice, code after. Leaving the question is always allowed;
filing under the wrong person is the harm.

**Before the read (code).** The question is about a held mention with no page of its own (a mention that shares its id with a page
is `inbox_tend.apply`'s 409: "the fold is the person's call"), something is held under it, two or more candidates are left after
what the person already said (`which_one.usable`: never the owner's page, never a pair they refused, never one this mention was
kept apart from), and every candidate that is a person passes the person guards (`question_revisit.person_guards`) EXCEPT the
one this reader exists to resolve, several pages answering to the short name. Every conversation the held line holds (at most
:data:`MAX_CONVERSATIONS`) is readable and has the mention in a turn of the person's own or of a named speaker's: a filing is
what a tap does, and a tap lifts the whole line, so a line is filed only when every conversation it holds was read. A mention an
assistant, an agent's saved note or relayed text said is never read.

**The read.** The model is shown the turn(s) holding the mention, the turns just before and after (bounded) and each candidate
with its name, what the record tells it apart by (a relation to the owner, a full name, the things it is linked to that no other
candidate is) and a one-line summary. It answers which ONE candidate the mention is THERE, or none, or cannot tell, and copies
the sentence that shows it. Twice: the second time with the candidates in the other order, told to look for the reason it is
another candidate. A conversation is decided only when both reads name the same candidate.

**After the read (code).** For each conversation, for each of the two reads: the copied sentence is located (`evidence.locate`:
exact, whitespace, case; never fuzzy) in a turn of the person's own or of a named speaker's inside the shown window, and those
words, that very span, are the person's (`evidence.verify` kind ``user`` or ``speaker``); and the copied sentence ITSELF ties the
mention to the picked candidate (`which_one_tie`): every whole-word occurrence of the mention in it is attached, by form (a full
name holding it, a relation word right beside it, a linked thing "from"/"at"/"of" it), to something the record holds for that
candidate and for no other. A tell in another sentence or turn, or in words the reader was not shown, never counts; a question, a
negation or contrast, or a sentence that names another candidate's tell is refused. A pick that rests on nothing the record tells
them apart by stays a question. Every conversation must name the same candidate.

**The filing is what a tap on that choice does** (`inbox_tend.apply`, the resolver's own ``merge``, Sleep's commit, undoable,
listed under "Settled by Sleep" with the sentence): what is held under the mention lands on the picked page, the name is never
made its alias (`which_one`: a pick is the mention's answer and nothing more). "None of them" and "cannot tell" leave the
question exactly as it is; what was read is remembered outside every bank (ids, a digest, the model, a count; never a word) and
is not read again until a page or conversation it read changed or the main model is a stronger one; a settle the person undoes
is remembered the same way, so it is never filed again.

Engine-free apart from the injected ``ask(system, prompt)``, the main model's call. Plan only through ruling 4's switch, a metered
key inside the spending limit, a plan limit is a pause, a demo bank is never read, nothing is fetched and nothing is logged but
counts.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import (bank_index, described_landing as dl, engine_errors, evidence, git_service, inbox_tend,
                          markdown_parser, pending_store, question_revisit as qr, same_name, which_one, which_one_file as wf,
                          which_one_tie as tie_of)
from api.services.id_utils import resolve_entity_file, sanitize_id
from api.services.which_one_tie import Tell

RULE = "which_one_read"
#: Questions read per run, and looked at (a look that fails a code guard makes no call).
MAX_READS = 6
MAX_LOOKS = 80
#: Conversations one question may read: a filing lifts the whole held line, so a line past this is left, counted.
MAX_CONVERSATIONS = 3
#: Turns holding the mention that are shown (the first ones), then the bounded turns around them (`dl.window_for`).
MAX_MENTION_TURNS = 3
LETTERS = "ABCDEF"
MIN_TELL = 3
#: Page types a "thing the record links to it" may be: an employer, a project, a tool, a place.
LINK_TYPES = frozenset({"company", "project", "tool", "place"})
SUMMARY_CHARS = 240
UNSETTLED = ("unusable_reply", "sentence_not_located")

SYSTEM = ("You read part of a conversation a person had and decide which one of several known people or things a name in it "
          "meant, from the words you are given only, and answer in JSON.")

PROMPT = """A person's memory holds {n} known pages that the name "{mention}" could be. In the conversation below, the person (or a named speaker) said "{mention}". Decide which ONE of the candidates they meant THERE, from what the conversation itself says around it. If you agree, what Sleep held about that name is filed on that candidate's page; a wrong answer files it under the wrong person or thing for good, and "cannot tell" costs little (the question stays open and the person is asked).

The conversation (turns are numbered; "..." marks turns left out; the turns that say the name are marked):
{window}

Candidates (known pages the name could be):
{candidates}
{second}
Answer with ONE letter when the words around the name point to that candidate: a relation the person gives ("my brother", "mi hermano"), a full name, a thing only that candidate is tied to (its company, its project). Answer "none" when it is a different person or thing than every candidate, and "cannot_tell" when:
- nothing in the conversation says which of them it was (a common name alone says nothing), or two candidates would fit equally;
- the only clue is a word that fits more than one candidate;
- the person says it is not that candidate;
- you are not sure. A wrong guess is worse than "cannot_tell".
Also copy, exactly as written and without changing a character, the ONE sentence (at most {max_chars} characters) from a turn of the PERSON (or named speaker), not the assistant, in which the name "{mention}" and the clue stand together, the clue right beside the name: "my brother {mention}", "{mention}, my brother", a full name, "{mention} from <its company>". If no single sentence has both the name and the clue (the clue is in another sentence or another turn), answer "cannot_tell". A sentence that is a question, denies something ("not", "no", "the other one") or names more than one of the candidates does not show it either. Never copy from an assistant turn, and never write words of your own in "sentence".

Respond with JSON only: {{"answer": "A" | "B" | ... | "none" | "cannot_tell", "sentence": "copied words", "reason": "<one short sentence>"}}
"""

SKEPTIC = """
Be a skeptic. A first reading proposed an answer; do not assume it was right. Before you answer, look for the reason the name meant a DIFFERENT candidate than the obvious one, or none of them: a clue that belongs to another candidate, two people named in one sentence, a person the clue is about who is not the one named, a name that is only the same by coincidence. Answer a candidate only when you cannot find one. The candidates are listed in a different order from before: read each name.
"""


# --------------------------------------------------------------------------- what the record tells the candidates apart by


@dataclass
class Cand:
    id: str
    name: str
    type: str
    fm: dict
    summary: str
    tells: list[Tell] = field(default_factory=list)

    def described(self) -> str:
        bits = []
        roles = [t.words for t in self.tells if t.kind == "role"]
        if roles:
            bits.append(f"the person's {roles[0]}")
        linked = [t.words for t in self.tells if t.kind == "linked"][:3]
        if linked:
            bits.append("tied to " + ", ".join(linked))
        return "; ".join(bits)


def _words_of(fm: dict, pid: str) -> list[str]:
    return [str(n) for n in (fm.get("name") or pid.replace("-", " "), *(a for a in (fm.get("aliases") or []) if isinstance(a, str)))
            if str(n).strip()]


def _linked_words(fm: dict, pid: str) -> list[str]:
    """What a linked page may be said as: its title, and an alias only when it is a proper name (more than one word, or capitalised).
    An alias that is one lowercase word ("home") is a common word the person says about anything, so it is never a tell."""
    out = []
    title = " ".join(str(fm.get("name") or "").split())
    if title:
        out.append(title)
    for a in fm.get("aliases") or []:
        alias = " ".join(a.split()) if isinstance(a, str) else ""
        if alias and (len(alias.split()) >= 2 or alias[0].isupper()):
            out.append(alias)
    return out


def _linked_things(memory_path: Path, body: str) -> dict[str, dict]:
    """``{page id: its frontmatter}`` of the employers, projects, tools and places a page links to: a wikilink in its prose or an
    open claim whose object is a page. Headers only."""
    from api.services.claims import parse_claims, strip_claims_block

    ids: set[str] = set()
    for m in re.finditer(r"\[\[([^\]|#]+)", strip_claims_block(body or "")):
        ids.add(sanitize_id(m.group(1)))
    try:
        for c in parse_claims(body or ""):
            if c.object_kind != "literal" and c.object and not c.valid_to and not c.superseded_by:
                ids.add(sanitize_id(str(c.object)))
    except Exception:  # noqa: BLE001 — a page whose claims will not read ties nothing by its links
        pass
    out: dict[str, dict] = {}
    for pid in sorted(ids):
        entry = bank_index.file(memory_path, "entities", f"{pid}.md")
        fm = dict(entry.frontmatter or {}) if entry is not None else {}
        if fm and str(fm.get("type") or "").lower() in LINK_TYPES and not fm.get("owner") \
                and str(fm.get("status") or "") not in ("dropped", "archived"):
            out[pid] = fm
    return out


def candidates_of(memory_path: Path, ids: list[str], mention: str) -> list[Cand]:
    """Each candidate with what the record tells it apart by, decided from the record alone: a relation to the owner nobody else of
    these holds, its full name, a linked thing no other of these is linked to. Never a word the mention itself is."""
    memory_path = Path(memory_path)
    out: list[Cand] = []
    raw: dict[str, list[Tell]] = {}
    key = same_name.fold(mention)
    for pid in ids:
        got = dl._page_text(memory_path, pid)
        try:
            parsed = markdown_parser.parse(memory_path / "entities" / f"{pid}.md")
        except Exception:  # noqa: BLE001
            continue
        if got is None:
            continue
        fm = dict(parsed.frontmatter or {})
        cand = Cand(pid, got[0], str(fm.get("type") or "").lower(), fm, got[1])
        out.append(cand)
        tells = [Tell("role", r) for r in which_one.roles_of(fm) if len(r) >= MIN_TELL]
        tells += [Tell("full_name", n) for n in _words_of(fm, pid) if len(same_name.fold(n).split()) >= 2]
        for tid, tfm in _linked_things(memory_path, parsed.body or "").items():
            tells += [Tell("linked", n) for n in _linked_words(tfm, tid) if len(n) >= MIN_TELL and same_name.fold(n) != key]
        raw[pid] = list(dict.fromkeys(tells))
    holders: dict[tuple[str, str], set[str]] = {}
    for pid, tells in raw.items():
        for t in tells:
            holders.setdefault((t.kind, same_name.fold(t.words)), set()).add(pid)
    for c in out:
        others = {same_name.fold(n) for o in out if o.id != c.id for n in _words_of(o.fm, o.id)}
        c.tells = [t for t in raw[c.id] if holders[(t.kind, same_name.fold(t.words))] == {c.id} and same_name.fold(t.words) not in others]
    return out


def ties(cands: list[Cand], pick: str, mention: str, quote: str, context: str) -> list[str]:
    """The kinds that tie ``mention`` to ``pick`` inside the copied ``quote`` (``context``: the sentence it is in), or ``[]``
    (`which_one_tie.tie`: nothing the record holds for the pick is attached to the mention there, or the sentence is a question, a
    negation or a contrast, or names something the record holds for another candidate)."""
    mine = next((c.tells for c in cands if c.id == pick), [])
    return tie_of.tie(mention, quote, context, mine, [c.tells for c in cands if c.id != pick])


# --------------------------------------------------------------------------- the case


@dataclass
class Case:
    item_id: str
    mention: str
    episodes: list[str]
    ids: list[str]
    fm: dict
    line_name: str = ""
    #: conversations whose filing the person undid: the reader never files them again
    undone: frozenset = frozenset()


def _held_episodes(line: pending_store.PendingEntity) -> list[str]:
    """The conversations the line still holds something of that nobody filed or answered "someone else" about (`which_one_file.unfiled`)."""
    return wf.unfiled(line)


def is_eligible(fm: dict, today: str) -> bool:
    return (str(fm.get("kind") or "") == "merge_suggestion" and str(fm.get("status") or "pending") == "pending"
            and str(fm.get("detected") or "") == which_one.DETECTED and not fm.get("fold_page") and not fm.get("heard_in")
            and not inbox_tend._blocked(fm, today))


def case_for(memory_path: Path, path: Path, fm: dict, *, today: str | None = None) -> Case | str:
    """The question as the reader takes it, or ``why it is left`` (every condition that needs no model). Reads only."""
    from api.services import full_name_join

    memory_path = Path(memory_path)
    day = today or date.today().isoformat()
    if not is_eligible(fm, day):
        return "not_this_question"
    mention = " ".join(str(fm.get("entity_name") or "").split())
    mention_id = sanitize_id(str(fm.get("entity_id") or mention))
    if not mention:
        return "not_this_question"
    if resolve_entity_file(memory_path, mention_id) is not None:
        return "subject_has_page"   # Sleep never settles a mention that shares its id with a page (`inbox_tend.apply`)
    line = pending_store.held_line(memory_path, mention)
    if line is None or not (line.held_claims or line.summary or line.description or line.key_facts or line.history_entries
                            or line.links):
        return "nothing_held"
    ids = which_one.usable(memory_path, mention, [str(p) for p in (fm.get("same_title") or []) if isinstance(p, str)])
    if len(ids) < 2:
        return "one_candidate"
    people = dict(full_name_join._person_pages(memory_path))
    afm = {"name": mention, "type": "person", "aliases": [str(a) for a in line.aliases if str(a).strip()]}
    for pid in ids:
        pfm = people.get(pid)
        if pfm is None:
            continue
        guarded = qr.person_guards(memory_path, mention_id, afm, pid, pfm, people, held_skip=frozenset({mention.lower()}))
        # Several pages answering to the short name is exactly what this reader resolves: that one guard is waived.
        if isinstance(guarded, str) and guarded != "short_name_not_alone":
            return f"guard:{guarded}"
    episodes = _held_episodes(line)
    if not episodes:
        if wf.stranded(line):
            return "stranded"   # nothing left to read: the person is asked about the claim two conversations cite (`which_one_file.asking`)
        return "all_filed" if wf.filed(line) else "conversation_unreadable"
    if len(episodes) > MAX_CONVERSATIONS:
        return "too_many_conversations"
    return Case(path.stem, mention, episodes, ids, dict(fm), line.name, frozenset(wf.undone_of(fm)))


# --------------------------------------------------------------------------- the reads


@dataclass
class _Focus:
    turn_index: int
    start: int
    end: int


def mention_turns(conv: dl.Conv, mention: str) -> list[_Focus]:
    """The turns of the person's own (or a named speaker's) that say the mention, whole word, located (never fuzzy)."""
    out: list[_Focus] = []
    for i in range(len(conv.turns)):
        if not conv.is_person(i):
            continue
        a, b = conv.content(i)
        hit = evidence.locate(conv.text[a:b], mention, whole_word=True)
        if hit is not None:
            out.append(_Focus(i, a + hit[0], a + hit[1]))
    return out[:MAX_MENTION_TURNS]


def window_text(conv: dl.Conv, shown: list[dl.Shown], focus: list[_Focus]) -> str:
    marked = {f.turn_index for f in focus}
    out, last = [], None
    for s in shown:
        if last is not None and s.index != last + 1:
            out.append("...")
        role = conv.turns[s.index].marker or conv.turns[s.index].role
        flag = "  <- says the name" if s.index in marked else ""
        out.append(f"[{s.index + 1}] {role}: {conv.text[s.a:s.b].strip()}{flag}")
        last = s.index
    return "\n".join(out)


def prompt_for(mention: str, window: str, cands: list[Cand], *, second: bool = False) -> str:
    rows = []
    for i, c in enumerate(cands):
        tail = c.described()
        rows.append(f"{LETTERS[i]}. {c.name}" + (f" ({tail})" if tail else "") + f" — {c.summary}")
    return PROMPT.format(n=len(cands), mention=mention, window=window, candidates="\n".join(rows),
                         second=SKEPTIC if second else "", max_chars=evidence.MAX_QUOTE_CHARS)


@dataclass
class Reading:
    page: str | None
    why: str = ""            # for no page: none | cannot_tell | unusable_reply | sentence_not_located
    start: int = 0
    end: int = 0
    turn: int = -1
    #: the part of that turn the reader was shown (a sentence is read only inside it)
    lo: int = 0
    hi: int = 0


async def _one_read(mention: str, conv: dl.Conv, shown: list[dl.Shown], focus: list[_Focus], cands: list[Cand], ask: Callable, *,
                    second: bool) -> Reading:
    parsed = await ask(SYSTEM, prompt_for(mention, window_text(conv, shown, focus), cands, second=second))
    if not isinstance(parsed, dict):
        return Reading(None, "unusable_reply")
    answer = str(parsed.get("answer") or "").strip().upper().rstrip(".")
    if answer in ("NONE",):
        return Reading(None, "none")
    if answer in ("CANNOT_TELL", "CANNOT TELL", "UNSURE"):
        return Reading(None, "cannot_tell")
    ids = {LETTERS[i]: cands[i].id for i in range(len(cands))}
    page = ids.get(answer)
    if page is None:
        return Reading(None, "unusable_reply")
    hit = dl.locate_sentence(conv, shown, parsed.get("sentence"))
    if hit is None:
        return Reading(page, "sentence_not_located")
    seen = next((x for x in shown if x.index == hit[2]), None)
    return Reading(page, "", hit[0], hit[1], hit[2], seen.a if seen else hit[0], seen.b if seen else hit[1])


@dataclass
class ConvRead:
    episode: str
    page: str | None = None
    why: str = ""
    calls: int = 0
    start: int = 0
    end: int = 0
    kind: str = ""
    tied: list[str] = field(default_factory=list)
    #: what a dry run shows the owner and nothing stores: the sentence as located
    sentence: str = ""


def _tied(conv: dl.Conv, cands: list[Cand], mention: str, r: Reading) -> list[str]:
    """What ties the mention to the pick in the copied sentence alone, judged over the sentence it is in and no more than the reader
    was shown. Never the turn, never another turn."""
    context = tie_of.enclosing(conv.text, r.start, r.end, r.lo, r.hi)
    return ties(cands, r.page or "", mention, conv.text[r.start:r.end], context)


def _verified(memory_path: Path, conv: dl.Conv, r: Reading) -> str:
    """The kind (``user`` / ``speaker``) of the located words, or ``""`` when they are not the person's own or a named
    speaker's (an assistant's turn, an agent's note, text relayed from an app)."""
    ev = evidence.verify(Path(memory_path), conv.episode, conv.text[r.start:r.end], window=(r.start, r.end))
    # the words located here are the ones that count: a verdict about the same words said somewhere else is no verdict
    return ev.kind if ev is not None and ev.is_span() and ev.start == r.start and ev.kind in ("user", "speaker") else ""


async def read_conversation(memory_path: Path, case: Case, conv: dl.Conv, cands: list[Cand], ask: Callable) -> ConvRead:
    """Two reads of one conversation, and the code's checks on each. An engine failure propagates (a pause)."""
    out = ConvRead(conv.episode)
    focus = mention_turns(conv, case.mention)
    if not focus:
        out.why = "mention_not_in_the_persons_turns"
        return out
    shown = dl.window_for(conv, focus)   # type: ignore[arg-type] — `_Focus` carries the three fields it reads

    async def read(order: list[Cand], second: bool) -> Reading | None:
        try:
            r = await _one_read(case.mention, conv, shown, focus, order, ask, second=second)
        except engine_errors.EngineError:
            raise
        except Exception as exc:  # noqa: BLE001 — a read that failed has read nothing
            logger.debug(f"Which-one read failed: {type(exc).__name__}")
            return None
        out.calls += 1
        return r

    first = await read(cands, False)
    if first is None:
        out.why = "unusable_reply"
        return out
    if first.page is None or first.why:
        out.why = f"first_read_{first.why}"
        return out
    kind1 = _verified(memory_path, conv, first)
    if not kind1:
        out.why = "first_read_not_the_persons_words"
        return out
    tied1 = _tied(conv, cands, case.mention, first)
    if not tied1:
        out.why = "nothing_tells_them_apart"   # code: the record holds nothing for the pick that the words say (or says it of another)
        return out
    second = await read(list(reversed(cands)), True)
    if second is None:
        out.why = "unusable_reply"
        return out
    if second.page is None or second.why:
        out.why = f"second_read_{second.why}"
        return out
    if second.page != first.page:
        out.why = "reads_disagree"
        return out
    if not _verified(memory_path, conv, second) or not _tied(conv, cands, case.mention, second):
        out.why = "second_read_nothing_tells_them_apart"
        return out
    out.page, out.start, out.end, out.kind, out.tied = first.page, first.start, first.end, kind1, tied1
    out.sentence = " ".join(conv.text[first.start:first.end].split())
    return out


@dataclass
class Assessment:
    """``outcome``: ``file`` (every conversation named the one page: the whole line, as a tap does) | ``file_parts`` (conversations
    named pages, not all the same one, or not all of them: each goes to its own) | ``left`` | ``unread``. ``why``: the enum.
    ``reads``: the conversations' reads, in order. ``parts``: ``{page: its conversations' reads}``."""
    outcome: str
    why: str = ""
    decision: object = None
    calls: int = 0
    reads: list[ConvRead] = field(default_factory=list)
    case: Case | None = None
    digest: str = ""
    cands: list[Cand] = field(default_factory=list)
    parts: dict[str, list[ConvRead]] = field(default_factory=dict)
    fingerprint: bytes = b""
    guard: dict = field(default_factory=dict)


def digest(memory_path: Path, case: Case, docs: dl.Docs) -> str:
    """What a read stood on: the candidates' pages, the conversations' words and the question's own candidates."""
    h = hashlib.sha256()
    parts = [json.dumps(inbox_tend._guard(Path(memory_path), *case.ids), sort_keys=True), case.mention, json.dumps(case.ids)]
    for ep in case.episodes:
        doc = docs.get(ep)
        parts.append(f"{ep}|{hashlib.sha256((doc[1] if doc else '').encode('utf-8', 'replace')).hexdigest()}")
    for part in parts:
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()[:20]


def _reason(name: str, sentence: str) -> str:
    from api.services import episode_scrub

    text = f"Read where you said it: “{qr._trim(sentence, qr.REASON_QUOTE_CHARS)}” points to {name}."
    return episode_scrub.scrub(text)[0]


async def assess(memory_path: Path, path: Path, fm: dict, ask: Callable, *, case: Case | None = None, docs: dl.Docs | None = None,
                 today: str | None = None, model: str = "") -> Assessment:
    """The guards, then up to two reads a conversation. Writes nothing. What the settle re-checks (the question's bytes, the pages'
    hashes) is taken BEFORE the first read, so a change while the model reads leaves the question."""
    memory_path = Path(memory_path)
    if case is None:
        found = await asyncio.to_thread(case_for, memory_path, path, fm, today=today)
        if isinstance(found, str):
            return Assessment("left", found)
        case = found
    docs = docs or dl.Docs(memory_path)
    fingerprint = path.read_bytes()
    guard = inbox_tend._guard(memory_path, *case.ids)
    result = Assessment("left", case=case, digest=await asyncio.to_thread(digest, memory_path, case, docs))
    result.cands = await asyncio.to_thread(candidates_of, memory_path, case.ids, case.mention)
    if len(result.cands) < 2:
        result.why = "one_candidate"
        return result
    result.fingerprint, result.guard = fingerprint, guard
    for ep in case.episodes:
        if ep in case.undone:
            result.reads.append(ConvRead(ep, why="undone"))   # the person took its filing back: asked, never filed by the reader
            continue
        conv = await asyncio.to_thread(docs.conv, ep)
        if conv is None:
            result.reads.append(ConvRead(ep, why="conversation_unreadable"))
            continue
        read = await read_conversation(memory_path, case, conv, result.cands, ask)
        result.reads.append(read)
        result.calls += read.calls
    decided = [r for r in result.reads if r.page is not None]
    if not decided:
        # Nothing was decided: the question is exactly as it was (a reply that said nothing is read again, `unread`).
        first = result.reads[0]
        result.why = first.why
        if any(r.why in UNSETTLED or r.why.endswith(UNSETTLED) for r in result.reads):
            result.outcome = "unread"
        return result
    picks = {r.page for r in decided}
    if len(decided) == len(result.reads) and len(picks) == 1:
        pick = next(iter(picks))
        cand = next(c for c in result.cands if c.id == pick)
        first = result.reads[0]
        spans = [{"episode": r.episode, "start": r.start, "end": r.end, "kind": r.kind} for r in result.reads]
        quote = ({"episode": first.episode, "quote": first.sentence} if first.kind == "user" else None)
        label = which_one.label(pick, cand.fm)
        result.outcome = "file"
        result.decision = inbox_tend.Decision(
            case.item_id, "merge_suggestion", RULE, {"action": "merge", "merge_target": pick},
            answer=label, quote=quote, model=model or None, fingerprint=fingerprint, guard=guard,
            reason=_reason(cand.name, first.sentence), spans=spans)
        return result
    # Conversations that named different pages, or only some of them did: each goes to the page its own reading named.
    for r in decided:
        result.parts.setdefault(r.page, []).append(r)
    result.outcome = "file_parts"
    return result


def still_holds(memory_path: Path, d) -> bool:
    """Inside the settle (`inbox_tend.still_holds`): the very question is still raised, still has no page of its own, still holds
    the same conversations and the picked page is still one of its candidates."""
    memory_path = Path(memory_path)
    path = memory_path / "inbox" / f"{d.item_id}.md"
    try:
        fm = dict(markdown_parser.parse(path).frontmatter)
    except Exception:  # noqa: BLE001
        return False
    case = case_for(memory_path, path, fm)
    return (isinstance(case, Case) and str((d.request or {}).get("merge_target") or "") in case.ids
            and {str(s.get("episode") or "") for s in d.spans or []} == set(case.episodes))


# --------------------------------------------------------------------------- what was read, outside every bank


def _seen_file(memory_path: Path) -> Path:
    from api.services import auth, continuity_sessions

    return auth.cicada_home() / "which_one_reads" / f"{continuity_sessions.bank_file_id(Path(memory_path))}.json"


def _seen(memory_path: Path) -> dict[str, dict]:
    try:
        data = json.loads(_seen_file(memory_path).read_text(encoding="utf-8"))
        return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_seen(memory_path: Path, data: dict[str, dict]) -> None:
    """Ids, a digest, a model name and a day only, never a name or a word; a file that cannot be written only means a question is
    read again."""
    try:
        path = _seen_file(memory_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- a filing that did not commit leaves nothing behind


def put_back(memory_path: Path, before: dict[str, bytes | None]) -> None:
    """Undo a filing that did not commit: every path that is uncommitted now and was not before the filing goes back to what the last
    commit holds (a new file is removed, its staging with it), and a path that was already uncommitted gets its own bytes back
    (``before`` is `git_service.snapshot_dirty_sync`). The resolver writes the pages, the held line, the settled record and removes
    the question before its commit; one that then fails must not leave the question gone and the pages changed. Never raises."""
    memory_path = Path(memory_path)
    try:
        dirty = git_service.dirty_paths_sync(memory_path)
    except git_service.GitError:
        return
    for rel in sorted(dirty):
        target = memory_path / rel
        try:
            if rel in before:
                if before[rel] is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(before[rel])
                continue
            git_service.run_git_write_sync(memory_path, "reset", "-q", "HEAD", "--", rel)
            try:
                git_service.run_git_write_sync(memory_path, "checkout", "--", rel)
            except git_service.GitError:
                target.unlink(missing_ok=True)   # never committed: it was this filing's own file
        except (OSError, git_service.GitError):
            logger.debug("Which-one filing: a path could not be put back")
    bank_index.invalidate(memory_path)
    markdown_parser.invalidate_pages(os.path.realpath(memory_path))


# --------------------------------------------------------------------------- the tail step


@dataclass
class Report:
    looked: int = 0
    read: int = 0
    settled: int = 0
    calls: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def eligible(memory_path: Path, today: str) -> list[tuple[Path, dict]]:
    """Open which-one questions, ordered as the inbox serves them (`question_order`, ruling 70)."""
    from api.services import question_order

    rows = [(p, fm) for p, fm, _b in inbox_tend.pending(Path(memory_path)) if is_eligible(fm, today)]
    if len(rows) > 1:
        order = question_order.ranked(Path(memory_path), [(p.stem, fm) for p, fm in rows])
        pos = {item: i for i, item in enumerate(order)}
        rows.sort(key=lambda r: pos.get(r[0].stem, len(pos)))
    return rows


async def _file_parts(memory_path: Path, path: Path, case: Case, result: Assessment, names: dict[str, str], report: Report, note,
                      remember, mark: str, *, today: date, settings, dry_run: bool, model: str, engine: str | None) -> None:
    """Each conversation's words to the page its own reading named (`which_one_file`): one landing, one record and one Sleep commit
    per page; a conversation nobody could tell stays on the line and the question is about it alone. A landing that does not commit
    puts every path back."""
    from api.services import web_settle

    item_id, ids = case.item_id, case.ids
    undecided = [r.episode for r in result.reads if r.page is None]
    if dry_run:
        for page, reads in result.parts.items():
            note(item_id, f"would_file:{page}", ids=ids, rule=wf.RULE,
                 eyes={"mention": case.mention, "page": names.get(page, ""), "conversations": [r.episode for r in reads]})
        for ep in undecided:
            note(item_id, "would_ask", episode=ep, ids=ids)
        return
    guard, fingerprint = result.guard, result.fingerprint
    filed = failed = 0
    for page, reads in result.parts.items():
        line = pending_store.held_line(memory_path, case.mention)
        probe = inbox_tend.Decision(item_id, "merge_suggestion", wf.RULE, None, guard=guard)
        if line is None or not path.is_file() or path.read_bytes() != fingerprint or not inbox_tend.guard_holds(memory_path, probe):
            note(item_id, "left:changed", ids=ids)   # the question or a page changed while the model read: read again next time
            continue
        before = await asyncio.to_thread(git_service.snapshot_dirty_sync, memory_path)
        # Every conversation decided in this run and every one filed before: a claim or a fact two conversations cite is split by them.
        verdict = {**wf.filed(line), **{r.episode: r.page for r in result.reads if r.page}}
        part = wf.plan(line, verdict, {r.episode for r in result.reads if r.page}).get(page)
        if before is None or part is None:
            note(item_id, "left:not_applied" if before is None else "left:nothing_to_file", ids=ids)
            continue
        try:
            done = await asyncio.to_thread(wf.land, memory_path, path, page, part, {r.episode: r for r in reads}, by=model or "cicada",
                                           engine=engine, mention=case.mention, today=today.isoformat())
            if done is not None:
                message = web_settle.commit_message("Facts about a mention filed", done.lines,
                                                    authors=[model] if model else ["cicada"], engine=engine)
                await asyncio.to_thread(web_settle.commit_sync, memory_path, message, done.paths)
        except Exception as exc:  # noqa: BLE001 - one page never stops the others
            logger.info(f"Which-one filing not applied: {type(exc).__name__}")
            await asyncio.to_thread(put_back, memory_path, before)
            note(item_id, "left:not_applied", ids=ids)
            failed += 1
            continue
        if done is None:
            await asyncio.to_thread(put_back, memory_path, before)
            note(item_id, "left:nothing_to_write", ids=ids)
            continue
        filed += 1
        report.settled += 1
        report.paths += done.paths
        fingerprint = path.read_bytes() if path.is_file() else b""
        guard = inbox_tend._guard(memory_path, *case.ids)
        for r in reads:
            note(item_id, f"filed:{page}", episode=r.episode, ids=ids, rule=wf.RULE)
    # What the question is about now: the conversations nobody has filed. A pick is then about one of them.
    after = "gone"
    if path.is_file():
        after = await asyncio.to_thread(case_for, memory_path, path, dict(markdown_parser.parse(path).frontmatter),
                                        today=today.isoformat())
    if isinstance(after, str):
        if filed and after == "all_filed" and path.is_file():
            await _close_answered(memory_path, path, settings, model, engine)
        elif after == "stranded" and path.is_file():
            await _narrow(memory_path, path, case.mention, report)   # a claim two conversations cite: asked about those
        remember(item_id, mark, "filed" if filed else "left")
        return
    if not filed and not failed:
        await _narrow(memory_path, path, after.mention, report)
    remember(item_id, await asyncio.to_thread(digest, memory_path, after, dl.Docs(memory_path)), "left")
    for ep in after.episodes:
        note(item_id, "asks", episode=ep, ids=ids)


async def _narrow(memory_path: Path, path: Path, mention: str, report: Report) -> None:
    """What the line still holds to be asked is two or more conversations (nobody could tell them), or a claim two conversations cite
    that were filed to two pages: the question is about that, and the person's pick files only that (`which_one_file.asking`). One
    Sleep commit of the question's own file; a failed commit puts it back."""
    from api.services import web_settle

    line = pending_store.held_line(memory_path, mention) if path.is_file() else None
    if len(wf.asking(line)[0]) < 2 or not path.is_file():
        return
    rel = path.relative_to(memory_path).as_posix()
    prior = path.read_bytes()
    try:
        if wf.rewrite_question(path, line):
            message = web_settle.commit_message("Which one: about one conversation",
                                                [f"{rel}: updated (source: {path.stem}, trigger: sleep/which-one-scoped)"],
                                                authors=["cicada"])
            await asyncio.to_thread(web_settle.commit_sync, memory_path, message, [rel])
            report.paths.append(rel)
    except Exception as exc:  # noqa: BLE001 - a question left as it was is never wrong
        logger.info(f"Which-one question not narrowed: {type(exc).__name__}")
        path.write_bytes(prior)
        bank_index.invalidate(memory_path)


async def _close_answered(memory_path: Path, path: Path, settings, model: str, engine: str | None) -> None:
    """Every conversation of the question was filed and only what carries no conversation is left on the line (history, links,
    questions): nothing is asked any more. The question closes as Sleep closes any it settled (undoable, `inbox_tend._retire`)."""
    d = inbox_tend.Decision(path.stem, "merge_suggestion", wf.ANSWERED, None, answer="Each conversation was filed under the one it meant",
                            model=model or None, fingerprint=path.read_bytes(), reason=wf.REASON)
    try:
        await inbox_tend.apply(memory_path, settings, d, engine=engine)
    except Exception as exc:  # noqa: BLE001 - a question left open is never wrong
        logger.info(f"Which-one question not closed: {type(exc).__name__}")


async def tend(memory_path: Path, settings, ask: Callable | None, *, today: date | None = None, max_reads: int = MAX_READS,
               max_looks: int = MAX_LOOKS, dry_run: bool = False, trace: Callable | None = None, model: str = "",
               rows: list[tuple[Path, dict]] | None = None, engine: str | None = None) -> Report:
    """Look at the open which-one questions in order and file the ones the conversation decides. The model runs outside any write;
    each filing is one `inbox_tend.apply` (Sleep's window is held by the caller). ``ask`` None: the code's guards only (a dry run
    that makes no call). ``dry_run``: reads, writes nothing and remembers nothing. ``trace(row)`` is handed one row per
    question and conversation: ids and enums only, and under ``row["eyes"]`` the words (a dry run for the owner's eyes). ``rows``:
    the questions to walk instead of the open which-one ones (the dry run adds the pairwise ones tonight's rewrite would convert)."""
    memory_path = Path(memory_path)
    today = today or date.today()
    report = Report()
    seen = _seen(memory_path)
    docs = dl.Docs(memory_path)

    def note(item_id: str, what: str, *, episode: str = "-", ids: list[str] | None = None, rule: str = "", eyes: dict | None = None) -> None:
        if trace is not None:
            trace({"id": item_id, "episode": episode, "candidates": ids or [], "what": what, "rule": rule, **({"eyes": eyes} if eyes else {})})

    def remember(item_id: str, mark: str, outcome: str, tries: int = 0) -> None:
        if not dry_run:
            seen[item_id] = {"d": mark, "m": model, "o": outcome, "at": today.isoformat(), "t": tries}

    try:
        walk = rows if rows is not None else await asyncio.to_thread(eligible, memory_path, today.isoformat())
        for path, fm in walk:
            if report.read >= max_reads:
                report.skip("max_reads")
                break
            if report.looked >= max_looks:
                report.skip("max_looks")
                break
            report.looked += 1
            item_id = path.stem
            found = await asyncio.to_thread(case_for, memory_path, path, fm, today=today.isoformat())
            if isinstance(found, str):
                report.skip(found)
                note(item_id, f"left:{found}", ids=[str(p) for p in fm.get("same_title") or []])
                if found == "stranded" and not dry_run:   # every conversation was filed; a claim they split is what the person is asked
                    await _narrow(memory_path, path, " ".join(str(fm.get("entity_name") or "").split()), report)
                continue
            case = found
            mark = await asyncio.to_thread(digest, memory_path, case, docs)
            entry = seen.get(item_id)
            if not dry_run and not qr.due(entry, mark, model):   # a dry run reads again: it remembers nothing
                report.skip("read_already")
                for ep in case.episodes:
                    note(item_id, "left:read_already", episode=ep, ids=case.ids)
                continue
            if ask is None:
                for ep in case.episodes:
                    note(item_id, "would_read", episode=ep, ids=case.ids, rule=RULE)
                continue
            result = await assess(memory_path, path, fm, ask, case=case, docs=docs, today=today.isoformat(), model=model)
            report.read += 1
            report.calls += result.calls
            names = {c.id: c.name for c in result.cands}
            for r in result.reads:
                eyes = {"mention": case.mention, "sentence": r.sentence, "page": names.get(r.page or "", ""), "tied_by": r.tied}
                note(item_id, f"named:{r.page}" if r.page else f"left:{r.why}", episode=r.episode, ids=case.ids, eyes=eyes)
            if result.outcome == "file_parts":
                await _file_parts(memory_path, path, case, result, names, report, note, remember, mark, today=today,
                                  settings=settings, dry_run=dry_run, model=model, engine=engine)
                continue
            if result.outcome == "left" and result.reads and not dry_run:
                await _narrow(memory_path, path, case.mention, report)   # nobody could tell: asked about one conversation at a time
            if result.outcome != "file" or result.decision is None:
                same = bool(entry and entry.get("d") == mark and entry.get("m") == model)
                tries = int(entry.get("t") or 0) + 1 if same else 1
                remember(item_id, mark, result.outcome if result.outcome == "unread" else "left", tries if result.outcome == "unread" else 0)
                note(item_id, f"read:left:{result.why}", ids=case.ids)
                continue
            d = result.decision
            pick = str(d.request.get("merge_target"))
            if dry_run:
                report.settled += 1
                note(item_id, f"would_file:{pick}", ids=case.ids, rule=RULE, eyes={"mention": case.mention, "page": names.get(pick, "")})
                continue
            before = await asyncio.to_thread(git_service.snapshot_dirty_sync, memory_path)
            if before is None:
                remember(item_id, mark, "not_applied", 1)   # the tree cannot be read: a failed filing could not be put back
                note(item_id, "left:not_applied", ids=case.ids)
                continue
            try:
                ok = await inbox_tend.apply(memory_path, settings, d)
            except Exception as exc:  # noqa: BLE001 - one filing that will not settle never stops the others
                logger.info(f"Which-one read not applied: {type(exc).__name__}")
                ok = False
            if not ok:
                await asyncio.to_thread(put_back, memory_path, before)
            if ok:
                report.settled += 1
                report.paths.append(f"inbox/settled/{d.item_id}.md")
                remember(item_id, mark, "filed")   # kept: a settle the person undoes is never filed again until a read page changes
                note(item_id, f"filed:{pick}", ids=case.ids, rule=RULE)
            else:
                remember(item_id, mark, "not_applied", 1)
                note(item_id, "left:not_applied", ids=case.ids)
    finally:
        if not dry_run:
            _save_seen(memory_path, seen)
    return report


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, ask: Callable | None = None, today: date | None = None,
                   model: str = "") -> Report:
    """Sleep's tail step: no engine is resolved and nothing is sent unless an open which-one question passes the code's guards. A
    scheduled run reaches a plan only through the person's switch (ruling 4b), a plan limit is a pause (the questions stay), no
    engine means no read, a demo bank is never read. Never raises."""
    from api.services import demo_guard, engine_select, full_name_join, same_name_tend

    memory_path = Path(memory_path)
    report = Report()
    try:
        if demo_guard.is_demo(memory_path):
            report.skip("demo")
            return report
        today = today or date.today()
        rows = await asyncio.to_thread(eligible, memory_path, today.isoformat())
        if not any(not isinstance(await asyncio.to_thread(case_for, memory_path, p, fm, today=today.isoformat()), str)
                   for p, fm in rows[:MAX_LOOKS]):
            return report
        if ask is None:
            strong, why = await same_name_tend.main_engine(settings, user_triggered=user_triggered)
            if strong is None:
                report.skip(why)
                return report
            model = model or engine_select.shown_model(strong)
            engine = str(getattr(strong, "llm_mode", "") or "") or None

            async def ask(system: str, prompt: str) -> object:
                return await full_name_join.ask_main(strong, system, prompt)

        return await tend(memory_path, settings, ask, today=today, model=model, engine=engine)
    except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
        report.skip("plan_limit")
    except Exception as exc:  # noqa: BLE001 - the reader never fails a Sleep
        logger.warning(f"Which-one read stopped: {type(exc).__name__}")
        report.skip("error")
    return report
