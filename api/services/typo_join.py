"""Sleep joins a name that is plainly a misspelling of a person's page itself (ruling 74c, owner 2026-11-24).

The owner, on "Are <misspelt> and <name> the same person? They could be one person, and I only join people on your word."
(real values redacted; the two spellings differed by two letters and sounded the same, the first from a dictated
message): "what i still dont get is why it asks me if [a misspelling] is the same as [the name]. I think it can clearly
be seen it was a typo, at least it can be assumed." And: "maybe this is something that needs to be worked at
consolidation time or something". Ruling 74 joined two pages only on two independent kinds of evidence with the name
counting once, so a spelling or sound match, however plain, always became a question.

**Why a model reads, and what it must copy.** Spelling alone is not proof: a one-letter difference can be two siblings
or two colleagues. What the conversations say around the name is. So this follows 74a's mechanism ("a located link, read
twice"), not 74's counted signals: a main-model read is shown the person's own messages that name the misspelt form and
what the record holds about each side, and answers "one" only by copying, word for word, one line about each side that
state the same fact (the same relation to the speaker, event, place, employer, project, plan). The code locates both
lines exactly (`same_name_people._located`, never fuzzy) in the text it showed for that side, and each must say something
beyond the name. A second, differently framed read that looks for a reason they are two must agree on its own located
lines. A name alone, or an answer whose quotes are not there, joins nothing.

**When it is even looked at** (engine-free, every one must hold; anything less is today's question, untouched):

1. An open "Is A the same as B?" between two people (A a page, or a name with no page held on a line in the pending
   store; B a person page) that only the person settles (`inbox_tend.policy`), not a same-name doubt, a question about
   a page's fold, or a first name heard in two places.
2. The names are one name written two ways: the same number of words, every differing word a misspelling of the other
   (`variant`, any script): never a short name in a full one, a nickname, a bare ending, a name that differs only in how
   it ends (Maria / Mario, Анна / Анн), a name of four letters or fewer (Mike / Mika, with the silent-"h" Sara / Sarah the
   one exception) or one vowel for another (Elena / Elina). Those are not candidates here; they are asked as before
   when nothing else says they are two. Never a name that is a relation to the owner, never the owner's page.
3. Nothing else is near: no third person page or held person has a name that is a spelling of A's name (`near`, the
   loose reading, endings and short names included). A spelling near two pages is neither joined nor asked (ruling 74c
   (b), (c): "hold a doubt rather than ask"): it waits apart, quietly, and is read again when the record changes.
4. No conversation either side was heard in names both spellings (naming two together is evidence they are two, ruling
   65c), and the person never called them two, nor Sleep split them, nor either side is held in a same-name doubt, and
   no spelling of one side is an alias the person removed from the other (`aliases_removed`).
5. There is something to read on each side (A's record or the person's own messages naming A; B's sourced record).
6. After a first read says "one", the two copied lines must share something specific (`anchored`): a named thing or a
   rare word that neither is the speaker's name, nor common ground in the bank. Two lines that both say "is a colleague"
   do not; the second read is not made.

**How it joins.** The same writer the person's own "yes" uses (`inbox_tend.apply`, `inbox_service`'s merge resolver) as
Sleep's commit, rule ``typo_one``, listed under "Settled by Sleep": A's page is folded into B (or the held name becomes
one of B's names with what the line held filed there), the misspelling is a name of B (never a second page), and the
reason quotes the line each side stated. **Undo is the person saying they are two** (`inbox_tend.JOINS`): the pair is kept
apart and nothing asks again. If it cannot be told (the model says two, cannot tell, quotes words that are not there,
or the second read disagrees) the question stays exactly as it was.

Engine-free apart from the injected ``judge(system, prompt)`` (the main model's call, `full_name_join.ask_main`). No name
leaves the bank for any service.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import engine_errors, full_name_join, pair_evidence, person_duplicates, text_fold

RULE = "typo_one"
MAX_LOOKS = 6
MAX_TURNS = 5
TURN_CHARS = 900
MAX_EPISODES = 40
MAX_FACTS = 10
FACT_CHARS = 300
REASON_QUOTE_CHARS = 110
MAX_UNREAD_TRIES = 2
#: A person's own messages are shown whole up to this many conversations per side.
SIDE_EPISODES = 12

SYSTEM = ("You decide, from what a person said in their own messages and from what their memory holds, whether two "
          "almost identical names are one real person written two ways, and you answer in JSON.")

SPEAKER = (' The speaker, the person whose conversations these are, appears in the memory as "{speaker}"; what someone '
           "is to the speaker is a fact about that someone like any other.")

PROMPT = """In one person's private conversations, two names that differ only by a letter or two (or by how they sound) appear.{speaker} Names get misspelt, misheard and dictated wrongly, but two different people can also have names that close. Decide, from what the memory holds, whether they are ONE real person.

NAME A: "{a}"
What the memory holds about A:
{a_record}
The person's own messages that name A:
{a_turns}

NAME B: "{b}" (also goes by: {b_names}). What the memory holds about B, conversation by conversation:
{b_record}

Answer with one of:
- "one": you can copy, word for word, one line about A (from the memory about A or from one of the messages) and one line about B (from the memory about B) that state THE SAME fact about the person: the same relation to the speaker, the same event, place, employer, project or plan. "here" is the line about A, "there" the line about B. Two lines that merely both name a person, or both say something possible of anyone, are not the same fact.
- "two": something says they are two people (a different relation to the speaker, a fact that cannot hold of one person, a message that names both), or the lines point at different lives.
- "cannot_tell": anything else.
Rules:
- A wrong join tells the person things about someone that are true of another; a question asked costs little. When anything points to two people, say "two" or "cannot_tell". A name that looks like another is no evidence.
- Decide only from what is written above. What you know about the names (that one is a common spelling of the other) is no evidence.

Answer in JSON only: {{"verdict": "one" | "two" | "cannot_tell", "here": "words copied about A", "there": "words copied about B", "reason": "one short sentence"}}
"""

SKEPTIC = """You are the sceptical reader. Look for any reason these two names are TWO people before you answer: a different relation to the speaker, a fact that cannot hold of one person, lines that are about different things.

""" + PROMPT.replace("Answer with one of:", 'Answer with one of (say "one" only if, having looked for a reason they are two, you find none):')


@dataclass
class Side:
    """One end of the pair: a page, or a held line. ``texts``: what the memory holds about it, as the model is shown it."""

    id: str
    name: str
    names: list[str]
    texts: list[str]
    episodes: list[str]
    page: bool


@dataclass
class Case:
    item_id: str
    a: Side
    b: Side
    turns: list[str]
    fm: dict = field(default_factory=dict)


@dataclass
class Read:
    verdict: str = ""
    here: str = ""
    there: str = ""
    reason: str = ""
    model: str = ""


@dataclass
class Assessment:
    outcome: str
    why: str = ""
    decision: object = None
    reads: int = 0
    case: Case | None = None


@dataclass
class Report:
    looked: int = 0
    joined: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    reads: int = 0
    paths: list[str] = field(default_factory=list)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


# --------------------------------------------------------------------------- the engine-free guards


def _words(text) -> list[str]:
    return pair_evidence._fold(text)


#: A word shorter than this is too short to tell a typo from another name (Mike / Mika, Lena / Lina, John / Joan).
MIN_WORD = 5
#: Letters that spell one sound (the classes `person_duplicates.sound_key` folds together): a single one swapped for
#: another in place is a plausible typo; any other single swap may be a different name.
_SAME_SOUND = ({"c", "k", "q"}, {"s", "z"}, {"i", "y", "j"}, {"v", "w"})


def _common_prefix(x: str, y: str) -> int:
    n = 0
    while n < min(len(x), len(y)) and x[n] == y[n]:
        n += 1
    return n


def _doubled(x: str, y: str) -> bool:
    """One word is the other with one letter repeated (a doubled consonant typed or dropped)."""
    short, long_ = sorted((x, y), key=len)
    if len(long_) != len(short) + 1:
        return False
    return any(long_[:i] + long_[i + 1:] == short and ((i > 0 and long_[i] == long_[i - 1])
                                                      or (i + 1 < len(long_) and long_[i] == long_[i + 1]))
               for i in range(len(long_)))


def _typo_word(x: str, y: str) -> bool:
    """Two folded words that are one name misspelt: the same, or a sound / one-edit spelling of the other, and never a
    pair that only another name could explain (ruling 74c, review 2026-11-24). Letters and positions only, so it reads
    any script alike:

    * **How a name ends says which name it is.** After the shared start the two must still share an end: Maria / Mario,
      Laura / Lauro, Sofia / Sofie, Anne / Anna, Andrea / Andres, Daniel / Danilo, Анна / Анн are refused, whatever the
      letters. One exception, the silent trailing "h" (Sara / Sarah, Hanna / Hannah).
    * **Short names are not told apart by one letter.** Both words need :data:`MIN_WORD` letters (John / Joan, Lena /
      Lina, Mike / Mika are refused); the silent "h" pair needs four.
    * **One letter changed in place is a typo only where the two letters sound alike** (c / k / q, s / z, i / y / j,
      v / w): Marizol / Marisol, Brinhild / Brynhild. A vowel for another vowel (Elena / Elina, Alena / Alina, Nilufar /
      Nilufer) is what two different names look like, so it is never a candidate; so is any in-place swap in a script
      with no such table.

    What it lets through: a doubled or dropped letter inside the name (Kesler / Kessler), the sound-alike swaps above, a
    transposition or inserted letter (Dmitri / Dimitri), a respelling of one sound (Aleksandra / Alexandra). What it
    refuses and costs: a real typo of a name's last letters (Dmitry / Dmitri) or of one vowel, which stay as they were
    before this rule (a question when the two names are not near others), never a join."""
    if x == y:
        return True
    kind = person_duplicates.word_match(x, y)
    if kind == "ending":
        # `word_match` flags a short vowel ending as two names (Mariana / Marina, Daniel / Daniela); one repeated letter
        # (Katia / Kattia, Marcela / Marcella) is the typo it is not.
        if not _doubled(x, y):
            return False
    elif kind not in ("sound", "spelling"):
        return False
    n = _common_prefix(x, y)
    tx, ty = x[n:], y[n:]
    if {tx, ty} == {"h", ""}:   # Sara / Sarah: a silent letter
        return min(len(x), len(y)) >= MIN_WORD - 1
    if min(len(x), len(y)) < MIN_WORD:
        return False
    if not (tx and ty and tx[-1] == ty[-1]):
        return False
    if len(x) == len(y) and sum(1 for p, q in zip(x, y) if p != q) == 1:
        a, b = next((p, q) for p, q in zip(x, y) if p != q)
        return any(a in group and b in group for group in _SAME_SOUND)
    return True


def variant(a: str, b: str) -> bool:
    """One name written two ways: the same number of words, every differing word a misspelling of the other
    (:func:`_typo_word`), at least one differing. Never a short name in a full one, a nickname, a bare ending, a name that
    differs only in how it ends, or a short name."""
    wa, wb = _words(a), _words(b)
    if not wa or len(wa) != len(wb) or wa == wb:
        return False
    return all(_typo_word(x, y) for x, y in zip(wa, wb))


def near(a: str, b: str) -> bool:
    """Is ``b`` a spelling of ``a`` that any rule of this family would look at: the looser reading, endings and short
    names included (:func:`person_duplicates.word_match`). Used where a near name must STOP a join ("nothing else is
    near"), never to start one."""
    wa, wb = _words(a), _words(b)
    if not wa or len(wa) != len(wb) or wa == wb:
        return False
    return all(x == y or person_duplicates.word_match(x, y) is not None for x, y in zip(wa, wb))


def _held_texts(line) -> list[str]:
    facts: list[str] = []
    for text in (line.description, line.summary, *line.key_facts):
        facts.append(full_name_join._trim(text, FACT_CHARS))
    for claim in line.held_claims[:MAX_FACTS]:
        facts.append(full_name_join._trim(claim.get("text"), FACT_CHARS))
    for entry in line.history_entries[:3]:
        if isinstance(entry, dict):
            facts.append(full_name_join._trim(entry.get("event"), FACT_CHARS))
    return [f for f in dict.fromkeys(facts) if f][:MAX_FACTS * 2]


def _page_texts(memory_path: Path, page_id: str) -> list[str]:
    from api.services import same_name_tend

    page = same_name_tend.page_of(Path(memory_path), page_id)
    return [full_name_join._trim(i.text, FACT_CHARS * 2) for i in list(page.items)[-MAX_FACTS:]] if page is not None else []


def _turns(memory_path: Path, episodes: list[str], names: list[str]) -> list[str]:
    out: list[str] = []
    keys = [pair_evidence.spelling(n) for n in names]
    for eid in [e for e in dict.fromkeys(episodes) if e.startswith("ep_")][:SIDE_EPISODES]:
        for turn in full_name_join._user_turns(memory_path, eid):
            if pair_evidence.names_in(keys, turn) and len(turn) <= TURN_CHARS:
                out.append(turn)
                if len(out) >= MAX_TURNS:
                    return out
    return out


def _named_together(memory_path: Path, a: Side, b: Side) -> bool:
    ak = [pair_evidence.spelling(n) for n in a.names]
    bk = [pair_evidence.spelling(n) for n in b.names]
    eps = [e for e in dict.fromkeys([*a.episodes, *b.episodes]) if e.startswith("ep_")]
    if len(eps) > 2 * MAX_EPISODES:
        return True   # too much to look through: never a join on a partial look
    for eid in eps:
        text = pair_evidence._text(memory_path, eid)
        if pair_evidence.names_in(ak, text) and pair_evidence.names_in(bk, text):
            return True
    return False


def _removed_from(fm: dict | None, names: list[str]) -> bool:
    """Is any of ``names`` an alias the person removed from the page whose frontmatter this is."""
    from api.services import page_edits

    removed = page_edits.removed_aliases(fm or {})
    if not removed:
        return False
    folded = {pair_evidence.spelling(r) for r in removed} - {""}
    return any(" ".join(str(n).split()).casefold() in removed or pair_evidence.spelling(n) in folded for n in names)


def guards(memory_path: Path, path: Path | None, fm: dict, *, today: str | None = None) -> tuple[Case | None, str]:
    """``(case, "")`` when every engine-free condition holds for this open question, else ``(None, why it stays)``.
    ``path`` is ``None`` for a held name no question was ever raised about (``fm`` is then the question's shape, never
    written unless the join happens). Reads only."""
    from api.services import (inbox_tend, merge_rejections, pending_store, role_people, same_name_doubts)
    from api.services.id_utils import resolve_entity_file, sanitize_id

    memory_path = Path(memory_path)
    if (str(fm.get("kind") or "") != "merge_suggestion" or str(fm.get("status") or "pending") != "pending"
            or str(fm.get("detected") or "") not in ("", "person_duplicate") or fm.get("fold_page") is True
            or fm.get("same_title") or fm.get("heard_in") or fm.get("tidy")):
        return None, "not_this_question"
    if path is not None:
        decided, why = inbox_tend.policy(memory_path, path, fm, today=today)
        if decided is not None or why != "person":
            return None, f"policy:{why or 'decided'}"
    target_id = str(fm.get("merge_target_hint") or "").strip()
    people = dict(full_name_join._person_pages(memory_path))
    tfm = people.get(target_id)
    if tfm is None:
        return None, "no_page"
    if tfm.get("owner") is True or str(tfm.get("status") or "").lower() in ("archived", "dropped"):
        return None, "owner_or_gone"
    if role_people.parse(str(tfm.get("name") or target_id)) is not None or tfm.get("unnamed"):
        return None, "role_page"
    asked_id = str(fm.get("entity_id") or "").strip()
    asked_name = " ".join(str(fm.get("entity_name") or "").split())
    asked_path = resolve_entity_file(memory_path, asked_id) if asked_id else None
    afm: dict | None = None
    if asked_path is not None:
        asked_id = asked_path.stem
        afm = people.get(asked_id)
        if afm is None or afm.get("owner") is True or str(afm.get("status") or "").lower() in ("archived", "dropped"):
            return None, "not_a_person_page"
        if asked_id == target_id:
            return None, "same_page"
        if role_people.parse(str(afm.get("name") or asked_id)) is not None or afm.get("unnamed"):
            return None, "role_page"
        a_name = str(afm.get("name") or asked_id)
        a_names = full_name_join._names_of(afm)
        a_eps = [str(e) for e in (afm.get("source_episodes") or ()) if e]
        a_texts = _page_texts(memory_path, asked_id)
        a_page = True
        pair_ids = (asked_id, target_id)
    else:
        line = pending_store.held_line(memory_path, asked_name) if asked_name else None
        if (line is None or str(line.type or "").lower() != "person" or line.title or line.held_against
                or line.correspondent):
            return None, "no_held_line"
        if target_id in pending_store.apart_of(memory_path, asked_name) or target_id in line.apart_pages():
            return None, "said_apart"
        a_id = sanitize_id(asked_name)
        if a_id in people:
            return None, "has_a_page"
        a_name, a_names = asked_name, [asked_name, *[x for x in line.aliases if str(x).strip()]]
        a_eps = [e for e in line.episodes() if e.startswith("ep_")]
        a_texts = _held_texts(line)
        a_page, asked_id, pair_ids = False, a_id, (a_id, target_id)
    b_name = str(tfm.get("name") or target_id)
    b_names = full_name_join._names_of(tfm)
    if not variant(a_name, b_name):
        return None, "not_one_name"
    # Nothing else is near: a spelling of A's name that belongs to a third person is neither joined nor asked (ruling 74c).
    for pid, pfm in people.items():
        if pid in (asked_id, target_id):
            continue
        if any(near(a_name, n) or pair_evidence.spelling(n) == pair_evidence.spelling(a_name)
               for n in full_name_join._names_of(pfm)):
            return None, "near_two_pages"
    for other in pending_store.load(memory_path):
        if other.name.strip().lower() == a_name.lower() or str(other.type or "").lower() != "person":
            continue
        if any(near(a_name, n) or pair_evidence.spelling(n) == pair_evidence.spelling(a_name)
               for n in (other.name, *other.aliases)):
            return None, "near_two_pages"
    # A removal holds against every writer (`aliases_removed`): a spelling the person took off one page is never filed back
    # on it by a join, whichever side it comes from, and its held lines never land there.
    if (_removed_from(afm, b_names) or _removed_from(tfm, a_names)):
        return None, "alias_removed"
    if (merge_rejections.is_rejected(memory_path, *pair_ids) or merge_rejections.is_split(memory_path, *pair_ids)
            or inbox_tend._split_apart(memory_path, *pair_ids)):
        return None, "kept_apart"
    flagged_pages, flagged_pairs = same_name_doubts.flagged(memory_path)
    for pid in pair_ids:
        if (same_name_doubts.doubts_of(memory_path, pid) or pid in flagged_pages
                or any(pid in pair for pair in flagged_pairs) or pid in same_name_doubts.one(memory_path)):
            return None, "in_a_doubt"
    b_eps = [str(e) for e in (tfm.get("source_episodes") or ()) if e]
    a_side = Side(asked_id, a_name, a_names, a_texts, a_eps, a_page)
    b_side = Side(target_id, b_name, b_names, _page_texts(memory_path, target_id), b_eps, True)
    if _named_together(memory_path, a_side, b_side):
        return None, "named_together"
    turns = _turns(memory_path, a_eps, a_names)
    if not b_side.texts or not (a_side.texts or turns):
        return None, "nothing_to_read"
    return Case(path.stem if path is not None else f"held-{asked_id}", a_side, b_side, turns, dict(fm)), ""


# --------------------------------------------------------------------------- the reads


def _lines(items: list[str]) -> str:
    return "\n".join(f"- {t}" for t in items) or "- (nothing)"


def build_prompt(case: Case, speaker: str | None, *, skeptic: bool = False) -> str:
    named = " ".join(str(speaker or "").replace('"', "").split())
    turns = "\n".join(f"[{i}] {t}" for i, t in enumerate(case.turns, 1)) or "(none)"
    return (SKEPTIC if skeptic else PROMPT).format(
        speaker=SPEAKER.format(speaker=named) if named else "", a=case.a.name.replace('"', ""),
        b=case.b.name.replace('"', ""), a_record=_lines(case.a.texts), a_turns=turns,
        b_names=", ".join(f"“{n}”" for n in case.b.names if pair_evidence.spelling(n) != pair_evidence.spelling(case.b.name))
        or "no other name", b_record=_lines(case.b.texts))


def located(case: Case, parsed: dict) -> Read:
    """What a reply stands on. ``one`` only when both copied lines are found word for word in the text shown for their
    side and each says something beyond the name; anything else is withdrawn to ``cannot_tell``."""
    from api.services import same_name_people as snp

    verdict = str(parsed.get("verdict") or "").strip().lower().replace(" ", "_")
    reason = full_name_join._trim(parsed.get("reason"), 200)
    model = str(parsed.get("_model") or "")
    if verdict in ("two", "different"):
        return Read("two", reason=reason, model=model)
    if verdict != "one":
        return Read("cannot_tell" if verdict == "cannot_tell" else "", reason=reason, model=model)
    here, there = str(parsed.get("here") or ""), str(parsed.get("there") or "")
    a_texts = [*case.a.texts, *case.turns]
    ok = (snp._located(here, a_texts) and snp._located(there, case.b.texts)
          and snp._says(here, case.a.name) and snp._says(there, case.b.name))
    if not ok:
        return Read("cannot_tell", reason="the lines quoted are not in the record, or say nothing beyond the name", model=model)
    return Read("one", " ".join(here.split()), " ".join(there.split()), reason, model)


#: What two copied lines must share for the code to stand behind "the same fact" (`anchored`). Letters and counts only.
MIN_KEY = 4          # a word shorter than this anchors nothing
STEM = 6             # words compared by their first letters, so "mentor" and "mentors" are one
RARE_PAGES = 3       # on at most this many pages of the bank: rare (`person_duplicates.COMMON_FACT`'s reading)
COMMON_PAGES = 6     # on more pages than this: common ground, never an anchor, however it is written
MIN_BANK_PAGES = 20  # below this a bank cannot tell a rare word from a common one: only a named thing anchors


def _content(line: str, skip: set[str]) -> dict[str, bool]:
    """``{stem: named}`` for the words of a line that say something: not a name of either side or of the speaker, at
    least :data:`MIN_KEY` letters. ``named``: written with a capital inside the line, or carrying a digit (a place, an
    employer, a project, a date) — case and digits, never a word list."""
    out: dict[str, bool] = {}
    for i, token in enumerate(re.findall(r"\w+", str(line or ""), re.UNICODE)):
        word = text_fold.fold(token)
        if len(word) < MIN_KEY or word in skip:
            continue
        key = word[:STEM]
        out[key] = out.get(key, False) or (i > 0 and token[:1].isupper()) or any(c.isdigit() for c in token)
    return out


def _page_counts(memory_path: Path, keys: set[str]) -> dict[str, int] | None:
    """On how many pages of the bank each stem occurs, or ``None`` when the bank is too small to say."""
    from api.services import bank_index

    entries = bank_index.files(Path(memory_path), "entities")
    if len(entries) < MIN_BANK_PAGES:
        return None
    counts = dict.fromkeys(keys, 0)
    for entry in entries:
        try:
            stems = {w[:STEM] for w in text_fold.words(entry.body())}
        except OSError:
            continue
        for key in keys & stems:
            counts[key] += 1
    return counts


def anchored(memory_path: Path, case: Case, read: Read, speaker: str | None = None, *, rare_only: bool = False) -> bool:
    """The code-side floor under "the same fact" (review 2026-11-24): the located lines share at least one word that is
    specific. Shared words leave out both sides' names and the speaker's; of what is left, a word on more than
    :data:`COMMON_PAGES` pages of the bank is common ground ("colleague") and never anchors; a word written with a capital
    or a digit in both lines (a place, an employer, a project) anchors; so does one on at most :data:`RARE_PAGES` pages.
    In a bank under :data:`MIN_BANK_PAGES` pages only the named kind anchors. Two lines that both say "is a colleague" share
    nothing specific, so they are not the same fact however a model reads them. ``rare_only`` (Sleep's second look at a pair
    whose name evidence may be only a first name inside a full name, ruling 82): the capital-in-both branch is off, since a
    shared employer or role is true of many people; only a word on at most :data:`RARE_PAGES` pages anchors, and a bank too
    small to count them anchors nothing. Reads only."""
    skip = {w for n in (*case.a.names, *case.b.names, case.a.name, case.b.name, speaker or "") for w in _words(n)}
    here, there = _content(read.here, skip), _content(read.there, skip)
    shared = set(here) & set(there)
    if not shared:
        return False
    counts = _page_counts(memory_path, shared)
    if rare_only and counts is None:
        return False
    for key in shared:
        if counts is not None and counts[key] > COMMON_PAGES:
            continue
        if ((here[key] and there[key]) and not rare_only) or (counts is not None and counts[key] <= RARE_PAGES):
            return True
    return False


async def _read(case: Case, judge, speaker, *, skeptic: bool) -> Read:
    try:
        parsed = await judge(SYSTEM, build_prompt(case, speaker, skeptic=skeptic))
    except asyncio.CancelledError:
        raise
    except engine_errors.EngineError:
        raise
    except Exception as exc:  # noqa: BLE001 - a read that failed has read nothing
        logger.debug(f"Typo join read failed: {type(exc).__name__}")
        return Read()
    return located(case, parsed) if isinstance(parsed, dict) else Read()


def _reason(read: Read) -> str:
    from api.services import episode_scrub

    here, there = (full_name_join._trim(read.here, REASON_QUOTE_CHARS), full_name_join._trim(read.there, REASON_QUOTE_CHARS))
    return episode_scrub.scrub(f"The same name, written two ways: “{here}” and “{there}” say the same thing about one person.")[0]


def _guard(memory_path: Path, case: Case) -> dict:
    from api.services import inbox_tend, pending_store

    guard = inbox_tend._guard(memory_path, case.a.id if case.a.page else "", case.b.id)
    if not case.a.page:
        store = pending_store.store_path(Path(memory_path))
        guard[store.relative_to(memory_path).as_posix()] = inbox_tend._hash(store)
    return guard


def digest(memory_path: Path, case: Case) -> str:
    h = hashlib.sha256()
    for part in (json.dumps(_guard(memory_path, case), sort_keys=True), json.dumps(case.a.texts), json.dumps(case.b.texts),
                 json.dumps(case.turns), case.a.id, case.b.id):
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()[:20]


async def assess(memory_path: Path, path: Path | None, fm: dict, judge, *, speaker: str | None = None,
                 today: str | None = None) -> Assessment:
    """The guards, then up to two reads. Writes nothing. What the settle re-checks is taken BEFORE the first read."""
    from api.services import inbox_tend

    memory_path = Path(memory_path)
    case, why = guards(memory_path, path, fm, today=today)
    if case is None:
        return Assessment("skip", why)
    fingerprint = path.read_bytes() if path is not None else b""
    guard = _guard(memory_path, case)
    first = await _read(case, judge, speaker, skeptic=False)
    result = Assessment("unread", reads=1, case=case)
    if first.verdict != "one":
        result.outcome = "two" if first.verdict == "two" else "unsure" if first.verdict == "cannot_tell" else "unread"
        return result
    if not await asyncio.to_thread(anchored, memory_path, case, first, speaker):
        result.outcome = "unsure"   # the lines share nothing specific: not the same fact, whatever the model read (no second read)
        return result
    second = await _read(case, judge, speaker, skeptic=True)
    result.reads = 2
    if second.verdict != "one":
        result.outcome = "two" if second.verdict == "two" else "unsure" if second.verdict == "cannot_tell" else "unread"
        return result
    result.outcome = "join"
    model = first.model if first.model and first.model == second.model else None
    result.decision = inbox_tend.Decision(
        case.item_id, "merge_suggestion", RULE, {"action": "merge", "merge_target": case.b.id},
        answer=f"Same as {case.b.name}", model=model, fingerprint=fingerprint, guard=guard, reason=_reason(first))
    return result


def still_holds(memory_path: Path, d) -> bool:
    memory_path = Path(memory_path)
    path = memory_path / "inbox" / f"{d.item_id}.md"
    try:
        from api.services import markdown_parser

        fm = dict(markdown_parser.parse(path).frontmatter)
    except Exception:  # noqa: BLE001
        return False
    case, _why = guards(memory_path, path, fm)
    return case is not None and case.b.id == str((d.request or {}).get("merge_target") or "")


# --------------------------------------------------------------------------- what was read, outside every bank


def _seen_file(memory_path: Path) -> Path:
    from api.services import auth, continuity_sessions

    return auth.cicada_home() / "typo_reads" / f"{continuity_sessions.bank_file_id(Path(memory_path))}.json"


def _seen(memory_path: Path) -> dict[str, str]:
    try:
        data = json.loads(_seen_file(memory_path).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(memory_path: Path, item_id: str, digest_: str) -> None:
    """Ids and a hash only, never a name or a word."""
    try:
        data = _seen(memory_path)
        data[item_id] = digest_
        path = _seen_file(memory_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- the tail step


def candidates(memory_path: Path) -> list[tuple[Path, dict]]:
    """Open questions of the shape (cheap filters only; `guards` decides): a same-as question whose two names are one name
    written two ways."""
    from api.services import bank_index, inbox_tend

    memory_path = Path(memory_path)
    out = []
    for p, fm, _b in inbox_tend.pending(memory_path):
        if (str(fm.get("kind") or "") != "merge_suggestion" or str(fm.get("detected") or "") not in ("", "person_duplicate")
                or fm.get("fold_page") is True or fm.get("same_title") or fm.get("heard_in")):
            continue
        target = bank_index.file(memory_path, "entities", f"{str(fm.get('merge_target_hint') or '').strip()}.md")
        if target is not None and variant(str(fm.get("entity_name") or ""), str((target.frontmatter or {}).get("name") or "")):
            out.append((p, fm))
    return out


def held_candidates(memory_path: Path) -> list[tuple[None, dict]]:
    """Held person names (a line in the pending store, no page, no question ever raised) that are one name written two
    ways beside exactly one person page: the common case of a dictated or mistyped name. ``fm`` is the shape of the
    question the join would answer; nothing is written unless the join happens (:func:`_materialize`)."""
    from api.services import pending_store
    from api.services.id_utils import sanitize_id

    memory_path = Path(memory_path)
    lines = [ln for ln in pending_store.load(memory_path)
             if str(ln.type or "").lower() == "person" and not (ln.title or ln.held_against or ln.correspondent)
             and len(_words(ln.name)) >= 1]
    if not lines:
        return []
    buckets: dict[str, list[tuple[str, str]]] = {}
    for pid, pfm in full_name_join._person_pages(memory_path):
        name = str(pfm.get("name") or pid)
        first = (_words(name) or [""])[0]
        if not first:
            continue
        for key in {first[:1], person_duplicates.sound_key(first)[:1]}:
            buckets.setdefault(key, []).append((pid, name))
    out: list[tuple[None, dict]] = []
    for ln in lines:
        first = (_words(ln.name) or [""])[0]
        near = {pid for key in {first[:1], person_duplicates.sound_key(first)[:1]} for pid, name in buckets.get(key, ())
                if variant(ln.name, name)}
        if len(near) != 1:
            continue
        target = next(iter(near))
        out.append((None, {"kind": "merge_suggestion", "status": "pending", "entity_id": sanitize_id(ln.name),
                           "entity_name": ln.name, "merge_target_hint": target}))
    return out


def page_pair_candidates(memory_path: Path) -> list[tuple[None, dict]]:
    """Two person pages whose names are one name written two ways and that nobody asked about: held in doubt, never
    asked (owner 2026-11-24: "hold a doubt rather than ask"; `person_duplicates.propose` leaves such a pair to this
    step). The less-used page is the one that would fold, as the question would have said."""
    from api.services import bank_index

    memory_path = Path(memory_path)
    out: list[tuple[None, dict]] = []
    for pair in person_duplicates.candidates(memory_path, floor=person_duplicates.ASK_FLOOR):
        if pair.asked or not set(pair.signals) <= {"sound", "spelling"}:
            continue
        fa = bank_index.file(memory_path, "entities", f"{pair.a}.md")
        fb = bank_index.file(memory_path, "entities", f"{pair.b}.md")
        if fa is None or fb is None:
            continue
        name_a, name_b = str(fa.frontmatter.get("name") or pair.a), str(fb.frontmatter.get("name") or pair.b)
        if not variant(name_a, name_b):
            continue
        use_a, use_b = len(fa.frontmatter.get("source_episodes") or ()), len(fb.frontmatter.get("source_episodes") or ())
        (asked, asked_name), (target, _t) = sorted(((pair.a, name_a), (pair.b, name_b)),
                                                  key=lambda x: (use_a if x[0] == pair.a else use_b, x[0]))
        out.append((None, {"kind": "merge_suggestion", "status": "pending", "entity_id": asked, "entity_name": asked_name,
                           "merge_target_hint": target, "detected": "person_duplicate"}))
    return out


def _materialize(memory_path: Path, case: Case) -> Path | None:
    """The question this join answers, for a held name no question was raised about: written only now, answered in the
    same settle (never shown), so the settled list and the undo are the ones every other settle has."""
    from api.services import bank_index, inbox_service, markdown_parser

    inbox = Path(memory_path) / "inbox"
    try:
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / f"inbox-{inbox_service.next_inbox_num(inbox):03d}.md"
        fm = {"kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.5,
              "entity_id": case.a.id, "entity_name": case.a.name, "title": f"Is {case.a.name} the same as {case.b.name}?",
              "uncertainty_type": f"Possible duplicate of {case.b.name}", "suggested_classification": "person",
              "created_date": date.today().isoformat(), "merge_target_hint": case.b.id,
              **({"detected": "person_duplicate"} if case.a.page else {})}
        markdown_parser.write(path, fm, "The same name, written two ways: Sleep reads the record and joins them itself.")
        bank_index.invalidate(Path(memory_path))
        return path
    except OSError:
        return None


def all_candidates(memory_path: Path) -> list[tuple[Path | None, dict]]:
    """Open questions first, then held names, then pages nobody asked about; one entry per asked name."""
    out: list[tuple[Path | None, dict]] = list(candidates(memory_path))
    seen = {str(fm.get("entity_id") or "") for _p, fm in out}
    for path, fm in [*held_candidates(memory_path), *page_pair_candidates(memory_path)]:
        if str(fm.get("entity_id") or "") not in seen:
            seen.add(str(fm.get("entity_id") or ""))
            out.append((path, fm))
    return out


async def tend(memory_path: Path, settings, judge, *, today: date | None = None, max_looks: int = MAX_LOOKS,
               cands: list | None = None) -> Report:
    from api.services import bank_index, inbox_tend

    memory_path = Path(memory_path)
    report = Report()
    seen = _seen(memory_path)
    speaker = None
    for path, fm in (cands if cands is not None else await asyncio.to_thread(all_candidates, memory_path)):
        if report.looked >= max_looks:
            report.skip("max_looks")
            break
        case, why = await asyncio.to_thread(guards, memory_path, path, fm)
        if case is None:
            report.skip(why)
            continue
        mark = await asyncio.to_thread(digest, memory_path, case)
        before = seen.get(case.item_id, "")
        tries = int(before.split("#", 1)[1]) if before.startswith(mark + "#") else 0
        if before == mark or tries >= MAX_UNREAD_TRIES:
            report.skip("read_already")
            continue
        if speaker is None:
            from api.services import same_name_tend

            speaker = await asyncio.to_thread(same_name_tend._speaker, memory_path) or ""
        report.looked += 1
        result = await assess(memory_path, path, fm, judge, speaker=speaker or None,
                              today=(today or date.today()).isoformat())
        report.reads += result.reads
        if result.outcome != "join" or result.decision is None:
            _remember(memory_path, case.item_id, f"{mark}#{tries + 1}" if result.outcome == "unread" else mark)
            report.skip(f"read:{result.outcome}")
            continue
        d = result.decision
        made = None
        if path is None:
            made = _materialize(memory_path, case)
            if made is None:
                report.skip("not_applied")
                continue
            d.item_id, d.fingerprint = made.stem, made.read_bytes()
        try:
            ok = await inbox_tend.apply(memory_path, settings, d)
        except Exception as exc:  # noqa: BLE001 - one join that will not settle never stops the others
            logger.info(f"Typo join not applied: {type(exc).__name__}")
            ok = False
        if made is not None and not ok:
            made.unlink(missing_ok=True)   # a question nobody was shown leaves no trace when its join does not happen
            bank_index.invalidate(memory_path)
        if ok:
            report.joined += 1
            report.paths.append(f"inbox/settled/{d.item_id}.md")
        else:
            _remember(memory_path, case.item_id, f"{mark}#{tries + 1}")
            report.skip("not_applied")
    return report


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, judge=None, today: date | None = None) -> Report:
    """Sleep's tail step, after the full-name join: no engine is resolved unless an open question has the shape. A plan
    limit is a pause, no engine means no read. Never raises."""
    from api.services import same_name_tend

    memory_path = Path(memory_path)
    report = Report()
    try:
        found = await asyncio.to_thread(all_candidates, memory_path)
        if not found:
            return report
        if judge is None:
            strong, why = await same_name_tend.main_engine(settings, user_triggered=user_triggered)
            if strong is None:
                report.skip(why)
                return report

            async def judge(system: str, prompt: str) -> object:
                return await full_name_join.ask_main(strong, system, prompt)

        return await tend(memory_path, settings, judge, today=today, cands=found)
    except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
        report.skip("plan_limit")
    except Exception as exc:  # noqa: BLE001 - the join never fails a Sleep
        logger.warning(f"Typo join stopped: {type(exc).__name__}")
        report.skip("error")
    return report
