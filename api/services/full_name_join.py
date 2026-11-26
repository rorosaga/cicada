"""Sleep joins a name held in full to its short-name page itself, on the person's own words (ruling 74b, 2026-11-24).

The question the person is asked most is "Is <Full Name> the same as <Short>?" (invented: "Is Teodor Brandt the same as
Teo?"): one of their own messages introduced both ("Had lunch with Teo today. Teodor Brandt, my old teammate ..."), the
full name was said once so it waits on a line of its own (`pending_store`), the short name has a page, and Stage 2 raised
the question (`entity_resolver._held_alias_questions`). Nothing settled it: ruling 29 keeps who someone is the person's,
and ruling 74's two signals do not apply to a pair one conversation named. The owner (2026-11-24: "yes the idea is that
sleep can join, split, and whatever") ruled that Sleep may answer it itself when the person's own words name both **as
one**, read twice, as one commit the person can undo.

**What decides, and who.** The code finds the person's own messages (``kind: user`` turns, never an agent's or another
speaker's) that carry both names, and everything that can speak against a join (below). The main model only reads those
messages with what the record holds about each side and, when it says "one", copies the words that show it. The code then
locates those words itself (`evidence.locate`: exact, whitespace, case, never fuzzy) **inside one turn of the person**
(a quote that runs on into an assistant's or another speaker's line is refused), reads the located words back from the
turn, and checks **those** carry both names, never what the model returned; a quote longer than `evidence.MAX_QUOTE_CHARS`
or touching a line the person quoted (a ``>`` block) is refused. A second read, framed to look for a reason they are two,
must agree with its own located words. No list of words of any language decides anything: "my old", an apposition's comma
and a parenthesis are the model's to read.

**When it joins** (every one must hold; anything less is today's question, untouched):

1. The question is an open "Is <A> the same as <B>?" between a name with **no page** and a person page, raised for a
   held name: not a doubt between two same-name people, not a page question (`fold_page`), not one the person put off or
   whose Sleep settle they took back, and `inbox_tend.policy` still says only the person settles it (so the owner's page,
   a pair no conversation names together and the two-signals join keep their own rules).
2. A is held on a line in the pending store (`pending_store`): a person, named in full (two words or more), carrying no
   `title` (the mark of a second person of one name), not held against a page, and the person has not said it is not
   this page (`pending_store.apart_of`); no page answers to A's name or its aliases.
3. B is a person page titled by one word, the short name; not the owner's, not archived or dropped, not titled by a
   relation (`role_people`), not in a same-name doubt, a pair the person called two (`merge_rejections`), or one Sleep
   split; and it carries **no name of two words or more but A's own** (a page that is already someone in full is never a
   join for Sleep, so a second full name never joins a page the first one joined).
4. **Exactly one page, of any type,** answers to B's short name (its name or an alias), and no other person page or held
   person could be whom it means: none has a word that is, or begins with, the short name.
5. At least one of the person's own turns, in a conversation **the held line was heard in** (never the question's source
   when the line was not), names both A (its name or a multi-word alias) and, outside A's words, a short name of B as the
   record writes it (case kept: "Will" the page is not "will" the verb), as whole words. **Every** such turn is shown to
   the model, whole; more than `MAX_TURNS`, a turn over `TURN_CHARS`, or a line heard in more than `MAX_EPISODES`
   conversations is no join (a counted skip), never a silent cut that could hide a denial.
6. The main model, given every such turn with what the record holds about each side (the page's names among it), answers
   "one" and copies words that are located as above; it answers "two" or "cannot tell" for two people named together (a
   relative, two colleagues, a list, "the other one"), for words the person only passes on from someone else, and for
   anything on record that cannot hold of one person.
7. A **second**, differently framed read of the same material answers "one" too, on words located and carrying both
   names.
8. Nothing changed since the reads began: the question's bytes and the hashes of B's page and the pending store are taken
   **before the first read**, and `inbox_tend.apply` re-checks them, and conditions 1 to 4 (`still_holds`), inside the
   settle. A settle that cannot apply is tried again, twice at most, like a read that could not be made.

**How it joins.** Through the one writer the person's own answer uses (`inbox_tend.apply`, `inbox_service`'s merge
resolver) with Sleep as the actor: the held line's claims land on B's page with their evidence, **and its own words**
(summary as a Key Fact, key facts, history, links, open questions: `inbox_service._land_held_prose`, through the one page
writer `conflict_resolver.apply_changes`, deterministic, additive on a page a person edited, never over a pinned passage,
each item with the source rows the line kept; the person's own tap does the same), A becomes a name of B, and the commit
is Sleep's, listed under "Settled by Sleep" with rule ``full_name_one`` and a reason that quotes the person's words; its
author is the model the engine's replies say answered (both reads the same), else ``cicada``.

**Undoing it is the person saying they are two** (74a's rule). `inbox_tend.undo` restores the pages and the store byte for
byte and does not bring the question back: the pair is kept apart by the writer the person's own "No, different" uses
(`inbox_service.reject_effects`: the held mention's pending line marked apart, else the pair in `_merge_rejected.yaml`), in
the same one commit, so no question is raised or settled again (`entity_resolver._said_different`). Other rules' undo is
unchanged.

Engine-free apart from the injected ``judge(system, prompt)``, the main model's call (`same_name_tend.main_tier`).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import engine_errors, pair_evidence, text_fold

RULE = "full_name_one"
#: Questions one tail step reads (each is up to two main-model calls); the rest wait for the next drain.
MAX_LOOKS = 6
#: The person's messages one call shows, and how much of each.
#: Every one of the person's messages that names both is shown; more than this and Sleep does not join (a counted skip),
#: never a silent cut that could hide the one that says they are two. A message longer than ``TURN_CHARS`` is shown whole or
#: not at all (skip), a held line heard in more than ``MAX_EPISODES`` conversations the same.
MAX_TURNS = 6
TURN_CHARS = 2500
MAX_EPISODES = 40
#: What the call shows of each side of the pair.
MAX_FACTS = 6
FACT_CHARS = 220
#: The reason on the settled list quotes this much of the person's words.
REASON_QUOTE_CHARS = 110
#: A question whose read could not be made is tried this many times with the record unchanged.
MAX_UNREAD_TRIES = 2
#: Letters a quote needs: a few characters occur anywhere.
MIN_QUOTE_CHARS = 12

SYSTEM = ("You decide, from what a person said in their own messages and from what their memory holds, whether two names "
          "are one real person, and you answer in JSON.")

SPEAKER = (' The speaker, the person whose conversations these are, appears in the memory as "{speaker}"; what someone '
           "is to the speaker is a fact about that someone like any other.")

PROMPT = """In one person's private conversations, a full name and a short name appear together in their own messages.{speaker} Their memory holds the full name on a line of its own (no page yet) and the short name on a page. Decide, from what they said, whether the two names are ONE real person called two ways.

FULL NAME: "{full}"
What the memory holds about it:
{held}

SHORT NAME: "{short}" (the page "{page_name}", which also goes by: {page_names}). What that page holds, conversation by conversation:
{page}

THE PERSON'S OWN MESSAGES that carry both names, numbered:
{turns}

Answer with one of:
- "one": the person's own words in ONE of the messages present the two names as the same person: one name given beside or after the other as who they are (an apposition, a nickname, "short for", a parenthesis, a dash, "also called", in any language). Give that message's number as "turn" and copy, word for word and without gaps, the words of that message that show it as "quote": the quote must carry both names.
- "two": the words name two different people (a relative of the other, two colleagues, a list, a namesake or "the other one", a person merely mentioned beside another), or something in the memory cannot be true of one person.
- "cannot_tell": anything else.
Rules:
- A wrong join tells the person things about someone that are true of another; a question asked costs little. When any message, or anything in the memory, points to two people, say "two" or "cannot_tell". Two names in one sentence are not one person: the words must present them as one.
- Words the person passes on from someone else (a message they forward or quote, an email, a document) are not their own account of who someone is: say "cannot_tell".
- Decide only from what the person said and what the memory holds. What you know about the names themselves (that one is usually short for the other) is no evidence.
- Several messages: if any of them names two different people, say "two".

Answer in JSON only: {{"verdict": "one" | "two" | "cannot_tell", "turn": <number>, "quote": "words copied from that message", "reason": "one short sentence"}}
"""

#: The second read: the same material, asked to look for the reason they are two first.
SKEPTIC = """You are the sceptical reader. Your job is to look for any reason these two names are TWO people, or that the person's words do not present them as one, before you answer.

""" + PROMPT.replace('Answer with one of:', 'Answer with one of (say "one" only if, having looked for a reason they are two, you find none):')


@dataclass(frozen=True)
class Turn:
    """One of the person's own messages that carries both names."""

    n: int
    episode: str
    day: str
    text: str


@dataclass
class Case:
    """Everything the guards found: the question, the two sides and the person's messages."""

    item_id: str
    full: str
    page_id: str
    page_name: str
    short: str
    full_names: list[str]
    short_names: list[str]
    turns: list[Turn]
    fm: dict = field(default_factory=dict)
    surfaces: frozenset = frozenset()
    page_names: list = field(default_factory=list)


@dataclass
class Read:
    """One model read: ``verdict`` ``one`` | ``two`` | ``cannot_tell`` | ``""`` (nothing readable); ``episode``/``quote``
    the located words for ``one``."""

    verdict: str = ""
    episode: str = ""
    quote: str = ""
    reason: str = ""
    model: str = ""   # the model the engine's reply said answered, "" when it did not say


@dataclass
class Assessment:
    """``outcome``: ``join`` (decision set), ``two``, ``unsure``, ``unread`` (a read that could not be stood on) or
    ``skip`` (a guard; ``why`` says which). ``reads``: model calls made."""

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


def _key(text) -> str:
    return pair_evidence.spelling(text)


def _words(text) -> list[str]:
    return text_fold.words(str(text or ""))


def _person_pages(memory_path: Path) -> list[tuple[str, dict]]:
    from api.services import bank_index

    out = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        if str(fm.get("type") or "").strip().lower() == "person" or fm.get("owner") is True:
            out.append((f.stem, fm))
    return out


def _all_pages(memory_path: Path) -> list[tuple[str, dict]]:
    from api.services import bank_index

    return [(f.stem, f.frontmatter or {}) for f in bank_index.files(Path(memory_path), "entities")]


def _names_of(fm: dict, stem: str = "") -> list[str]:
    removed = {_key(a) for a in (fm.get("aliases_removed") or []) if isinstance(a, str)}
    raw = [fm.get("name"), *[a for a in (fm.get("aliases") or []) if isinstance(a, str) and _key(a) not in removed]]
    return [str(n) for n in raw if str(n or "").strip()]


def _could_mean(short_key: str, names: list[str]) -> bool:
    """Could one of ``names`` be whom the short name means: a word of it is, or begins with, the short name."""
    return any(w == short_key or (len(short_key) >= 2 and w.startswith(short_key))
               for n in names for w in _words(n))


def _plain(word: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", word) if not unicodedata.combining(c))


def names_both(fulls: list[str], shorts: list[str], text: str | None, surfaces: frozenset[str] | None = None) -> bool:
    """Does ``text`` say a full name AND, somewhere else, a short name (whole words)? The short name inside the full one
    ("Ola" in "Ola Petrov") says nothing: each full name's words are taken out before the short name is looked for.
    ``surfaces``: the short name as the record writes it (accents off, case kept). When given, the short name must be
    written so, exactly: "Will" the page never matches "will" in "I will see Will Marsh". Language-free: a script with no
    case is unaffected, and a person who types everything in lower case only misses a join."""
    words = [(w, text_fold.fold(w), _plain(w)) for w in re.findall(r"[^\W_]+", str(text or ""))]
    folded = [f for _w, f, _p in words]
    taken = [False] * len(words)
    found = False
    for full in sorted((f for f in fulls if f), key=lambda f: -len(f.split())):
        parts = full.split()
        for at in range(len(words) - len(parts) + 1):
            if folded[at:at + len(parts)] == parts and not any(taken[at:at + len(parts)]):
                taken[at:at + len(parts)] = [True] * len(parts)
                found = True
    if not found:
        return False
    for (_w, f, plain), gone in zip(words, taken):
        if gone:
            continue
        if surfaces is not None:
            if plain in surfaces:
                return True
        elif f in shorts:
            return True
    return False


def _episode_day(memory_path: Path, episode: str) -> str:
    return str(pair_evidence.episode_timestamp(memory_path, episode) or "")[:10]


def _user_turns(memory_path: Path, episode_id: str) -> list[str]:
    """The person's own turns of one conversation (``kind: user``), as `pair_evidence.self_named` reads them."""
    from api.services import authorship, evidence, inbox_tend

    doc = evidence.source_document(Path(memory_path), episode_id)
    if doc is None:
        return []
    ep_fm, text = doc
    return inbox_tend.person_turns({"content": text, authorship.KEY: authorship.of(ep_fm),
                                    "gaps": evidence.gap_ranges(ep_fm, text), "source": ep_fm.get("source")})


def _turns_naming_both(memory_path: Path, episodes: list[str], full_names: list[str], short_names: list[str],
                       surfaces: frozenset[str]) -> tuple[list[Turn], str]:
    """``(the person's messages that name both, "")`` or ``([], why Sleep does not read them)``: every one is shown, so
    one that says they are two is never cut away."""
    out: list[Turn] = []
    fulls, shorts = [_key(n) for n in full_names], [_key(n) for n in short_names]
    if len(episodes) > MAX_EPISODES:
        return [], "too_many_conversations"
    for eid in episodes:
        for turn in _user_turns(memory_path, eid):
            if names_both(fulls, shorts, turn, surfaces):
                if len(turn) > TURN_CHARS:
                    return [], "turn_too_long"
                out.append(Turn(len(out) + 1, eid, _episode_day(memory_path, eid), turn))
                if len(out) > MAX_TURNS:
                    return [], "too_many_turns"
    return out, ""


def short_name_is_alone(memory_path: Path, short_keys: set[str], own_ids: set[str], *, people: list[tuple[str, dict]] | None = None,
                        held_skip: set[str] = frozenset()) -> bool:
    """Is every thing the short names could mean one of ``own_ids``? No page of ANY type (a company, a pet, a tool called
    the same) answers to one of them besides those, no other person page has a name one of them begins, and no person held
    in ``pending_store`` (a name with no page yet) could be whom they mean; ``held_skip``: held lines (lower-cased names)
    that are the very names being joined. One reading for the two joins that start from a short name: `guards` here and
    `question_revisit.pair_case`."""
    from api.services import pending_store

    memory_path = Path(memory_path)
    if any(pid not in own_ids and short_keys & {_key(n) for n in _names_of(pfm)} for pid, pfm in _all_pages(memory_path)):
        return False
    for pid, pfm in (people if people is not None else _person_pages(memory_path)):
        if pid not in own_ids and any(_could_mean(k, _names_of(pfm)) for k in short_keys):
            return False
    for other in pending_store.load(memory_path):
        if other.name.strip().lower() in held_skip or str(other.type or "").lower() != "person":
            continue
        names = [other.name, other.title, *other.aliases]
        if any(_could_mean(k, names) for k in short_keys):
            return False
    return True


def guards(memory_path: Path, path: Path, fm: dict, *, today: str | None = None) -> tuple[Case | None, str]:
    """``(case, "")`` when every engine-free condition (1 to 5 of the module's list) holds for this open question, else
    ``(None, why it stays)``. Reads only."""
    from api.services import (inbox_tend, merge_rejections, pending_store, role_people, same_name_doubts, which_one_file)
    from api.services.id_utils import resolve_entity_file, sanitize_id

    memory_path = Path(memory_path)
    if (str(fm.get("kind") or "") != "merge_suggestion" or str(fm.get("status") or "pending") != "pending"
            or str(fm.get("detected") or "") or fm.get("fold_page") is True or fm.get("same_title")
            or fm.get("heard_in") or fm.get("tidy")):
        return None, "not_this_question"
    decided, why = inbox_tend.policy(memory_path, path, fm, today=today)
    if decided is not None or why != "person":
        return None, f"policy:{why or 'decided'}"
    full = " ".join(str(fm.get("entity_name") or "").split())
    target_id = str(fm.get("merge_target_hint") or "").strip()
    if len(_words(full)) < 2 or not target_id:
        return None, "not_a_full_name"
    line = pending_store.held_line(memory_path, full)
    if (line is None or str(line.type or "").lower() != "person" or line.title or line.held_against
            or line.correspondent):
        return None, "no_held_line"
    if (target_id in pending_store.apart_of(memory_path, full) or target_id in line.apart_pages()
            or which_one_file.blocked(line, target_id)):   # ruling 83: a per-conversation "someone else" holds too
        return None, "said_apart"
    own_id = sanitize_id(full)
    if resolve_entity_file(memory_path, own_id) is not None:
        return None, "has_a_page"
    full_names = [full, *[a for a in line.aliases if len(_words(a)) >= 2]]
    full_keys = {_key(n) for n in full_names}
    people = _person_pages(memory_path)
    target_fm = dict(next((f for i, f in people if i == target_id), None) or {})
    if not target_fm:
        return None, "no_page"
    if target_fm.get("owner") is True:
        return None, "owner"
    if str(target_fm.get("status") or "").lower() in ("archived", "dropped"):
        return None, "page_gone"
    for _pid, pfm in people:
        if full_keys & {_key(n) for n in _names_of(pfm)}:
            return None, "has_a_page"
    page_name = str(target_fm.get("name") or target_id)
    if len(_words(page_name)) != 1:
        return None, "page_not_short"
    if role_people.parse(page_name) is not None or target_fm.get("unnamed"):
        return None, "role_page"
    short_names = [n for n in _names_of(target_fm) if len(_words(n)) == 1]
    short_keys = {_key(n) for n in short_names}
    if _key(page_name) not in short_keys:
        return None, "page_not_short"
    # A page that already carries another full name (two words or more) is someone in full: never a join for Sleep. A's
    # own spellings (its name, its multi-word aliases) are the only ones it may carry beside the short name.
    if any(len(_words(n)) >= 2 and _key(n) not in full_keys for n in _names_of(target_fm)):
        return None, "page_is_someone_in_full"
    # Exactly ONE page (of any type: a company or a pet called the same) answers to the short name, and no other person
    # (a page, or a held line) could be whom it means.
    if not short_name_is_alone(memory_path, short_keys, {target_id}, people=people, held_skip={full.lower()}):
        return None, "short_name_not_alone"
    if (merge_rejections.is_rejected(memory_path, own_id, target_id) or merge_rejections.is_split(memory_path, own_id,
                                                                                                    target_id)
            or inbox_tend._split_apart(memory_path, own_id, target_id)):
        return None, "kept_apart"
    flagged_pages, flagged_pairs = same_name_doubts.flagged(memory_path)
    if (same_name_doubts.doubts_of(memory_path, target_id) or target_id in flagged_pages
            or any(target_id in pair for pair in flagged_pairs) or target_id in same_name_doubts.one(memory_path)):
        return None, "in_a_doubt"
    # Only conversations the held line was heard in (never the question's own source when the line was not heard there).
    episodes = [e for e in dict.fromkeys(line.episodes()) if e.startswith("ep_")]
    surfaces = frozenset(_plain(n) for n in short_names)
    turns, why = _turns_naming_both(memory_path, episodes, full_names, short_names, surfaces)
    if why:
        return None, why
    if not turns:
        return None, "no_turn_names_both"
    return Case(path.stem, full, target_id, page_name, page_name, full_names, short_names, turns, dict(fm), surfaces,
                _names_of(target_fm)), ""


# --------------------------------------------------------------------------- the reads


def _trim(text, limit: int = FACT_CHARS) -> str:
    return " ".join(str(text or "").split())[:limit]


def _held_text(memory_path: Path, case: Case) -> str:
    from api.services import pending_store

    line = pending_store.held_line(Path(memory_path), case.full)
    if line is None:
        return "- (nothing)"
    facts: list[str] = []
    for text in (line.description, line.summary, *line.key_facts):
        if _trim(text):
            facts.append(_trim(text))
    for claim in line.held_claims[:MAX_FACTS]:
        if _trim(claim.get("text")):
            facts.append(_trim(claim.get("text")))
    for entry in line.history_entries[:3]:
        if isinstance(entry, dict) and _trim(entry.get("event")):
            facts.append(f"({str(entry.get('date') or '')[:10]}) {_trim(entry.get('event'))}".replace("() ", ""))
    facts = list(dict.fromkeys(facts))[:MAX_FACTS * 2]
    return "\n".join(f"- {f}" for f in facts) or "- (nothing)"


def _page_text(memory_path: Path, case: Case) -> str:
    from api.services import same_name_tend

    page = same_name_tend.page_of(Path(memory_path), case.page_id)
    items = list(page.items)[-MAX_FACTS * 2:] if page is not None else []
    lines = [f"- {_trim(i.text, 300)}" for i in items]
    if not lines:
        known = same_name_tend.known_for(Path(memory_path), case.page_id)
        lines = [f"- {known}"] if known else ["- (nothing recorded)"]
    return "\n".join(lines)


def build_prompt(memory_path: Path, case: Case, speaker: str | None, *, skeptic: bool = False) -> str:
    named = " ".join(str(speaker or "").replace('"', "").split())
    turns = "\n".join(f"[{t.n}] ({t.day or 'undated'}) {t.text}" for t in case.turns)
    return (SKEPTIC if skeptic else PROMPT).format(
        speaker=SPEAKER.format(speaker=named) if named else "", full=case.full.replace('"', ""),
        short=case.short.replace('"', ""), page_name=case.page_name.replace('"', ""),
        page_names=", ".join(f"“{n}”" for n in case.page_names if _key(n) != _key(case.page_name)) or "no other name",
        held=_held_text(memory_path, case), page=_page_text(memory_path, case), turns=turns)


def _span_in_turn(case: Case, quote: str) -> tuple[Turn, str] | None:
    """The quote located (`evidence.locate`: exact, whitespace, case; never fuzzy) inside ONE of the person's own turns,
    and the words it located read back from that turn: ``(turn, those words)``. ``None`` when it is in no turn, is longer
    than the evidence cap (only its first 240 characters would be located), or touches a line the person quoted from
    someone else (a markdown ``>`` block)."""
    from api.services import evidence

    if len(quote) > evidence.MAX_QUOTE_CHARS:
        return None
    for turn in case.turns:
        hit = evidence.locate(turn.text, quote)
        if hit is None:
            continue
        start, end = hit
        first = turn.text.rfind("\n", 0, start) + 1
        block = turn.text[first:end]
        if any(line.lstrip().startswith(">") for line in block.split("\n")):
            return None
        return turn, turn.text[start:end]
    return None


def located(memory_path: Path, case: Case, parsed: dict) -> Read:
    """What a model's reply stands on: a verdict, and for ``one`` words found exactly inside one of the person's own turns
    of a conversation the held line was heard in, and carrying a spelling of each side **in the words as located**, read
    back from the turn (never in what the model returned). Anything else is ``one`` withdrawn: ``cannot_tell``."""
    from api.services import inbox_tend

    verdict = str(parsed.get("verdict") or "").strip().lower().replace(" ", "_")
    reason = _trim(parsed.get("reason"), 200)
    model = str(parsed.get("_model") or "")
    if verdict in ("two", "different"):
        return Read("two", reason=reason, model=model)
    if verdict != "one":
        return Read("cannot_tell" if verdict == "cannot_tell" else "", reason=reason, model=model)
    quote = " ".join(str(parsed.get("quote") or "").split())
    if len(re.sub(r"\W+", "", quote)) < MIN_QUOTE_CHARS or "…" in quote or "..." in quote:
        return Read("cannot_tell", reason="the words quoted are too short or have gaps", model=model)
    found = _span_in_turn(case, quote)
    if found is None:
        return Read("cannot_tell", reason="the words quoted are not inside one of the person's own turns, as written", model=model)
    turn, words = found
    fulls, shorts = [_key(n) for n in case.full_names], [_key(n) for n in case.short_names]
    if not names_both(fulls, shorts, words, case.surfaces):
        return Read("cannot_tell", reason="the words located do not carry both names", model=model)
    if inbox_tend.persons_span(Path(memory_path), turn.episode, words) is None:
        return Read("cannot_tell", reason="the words are not the person's own where the record first has them", model=model)
    return Read("one", turn.episode, words, reason, model)


async def _read(memory_path: Path, case: Case, judge, speaker, *, skeptic: bool) -> Read:
    try:
        parsed = await judge(SYSTEM, build_prompt(memory_path, case, speaker, skeptic=skeptic))
    except asyncio.CancelledError:
        raise
    except engine_errors.EngineError:
        raise
    except Exception as exc:  # noqa: BLE001 - a read that failed has read nothing
        logger.debug(f"Full-name join read failed: {type(exc).__name__}")
        return Read()
    return located(memory_path, case, parsed) if isinstance(parsed, dict) else Read()


def _reason(read: Read) -> str:
    from api.services import episode_scrub

    quote = _trim(read.quote, REASON_QUOTE_CHARS)
    text = f"Your own words name them as one person: “{quote}”"
    return episode_scrub.scrub(text)[0]


def _guard(memory_path: Path, case: Case) -> dict:
    from api.services import inbox_tend, pending_store

    guard = inbox_tend._guard(memory_path, case.page_id)
    store = pending_store.store_path(Path(memory_path))
    guard[store.relative_to(memory_path).as_posix()] = inbox_tend._hash(store)
    return guard


def digest(memory_path: Path, case: Case) -> str:
    """What a read stood on, so the same question is not read again until something it read changed."""
    from api.services import inbox_tend, pending_store

    line = pending_store.held_line(Path(memory_path), case.full)
    h = hashlib.sha256()
    for part in (json.dumps(inbox_tend._guard(memory_path, case.page_id), sort_keys=True),
                 json.dumps(line.to_dict() if line is not None else {}, sort_keys=True),
                 json.dumps([(t.episode, t.text) for t in case.turns]), case.page_id, case.full):
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()[:20]


async def assess(memory_path: Path, path: Path, fm: dict, judge, *, speaker: str | None = None,
                 today: str | None = None) -> Assessment:
    """The guards, then up to two reads. Writes nothing. What the settle will re-check (the question's bytes, the pages'
    hashes, the pending store's) is taken BEFORE the first read, so a change while the model reads leaves the question.
    An engine failure is the caller's (a plan limit is a pause)."""
    from api.services import inbox_tend

    memory_path = Path(memory_path)
    case, why = guards(memory_path, path, fm, today=today)
    if case is None:
        return Assessment("skip", why)
    fingerprint = path.read_bytes()
    guard = _guard(memory_path, case)
    first = await _read(memory_path, case, judge, speaker, skeptic=False)
    result = Assessment("unread", reads=1, case=case)
    if first.verdict == "two":
        result.outcome = "two"
        return result
    if first.verdict != "one":
        result.outcome = "unsure" if first.verdict == "cannot_tell" else "unread"
        return result
    second = await _read(memory_path, case, judge, speaker, skeptic=True)
    result.reads = 2
    if second.verdict != "one":
        result.outcome = "two" if second.verdict == "two" else "unsure" if second.verdict == "cannot_tell" else "unread"
        return result
    result.outcome = "join"
    # The judging model, when the engine's replies say which one answered (both reads the same); otherwise `cicada`.
    model = first.model if first.model and first.model == second.model else None
    result.decision = inbox_tend.Decision(
        case.item_id, "merge_suggestion", RULE, {"action": "merge", "merge_target": case.page_id},
        answer=f"Same as {case.page_name}", quote={"episode": first.episode, "quote": first.quote},
        model=model, fingerprint=fingerprint, guard=guard, reason=_reason(first))
    return result


def still_holds(memory_path: Path, d) -> bool:
    """Inside the settle (`inbox_tend.still_holds`): the engine-free conditions are still met for the very question and
    the very page the reads were about."""
    memory_path = Path(memory_path)
    path = memory_path / "inbox" / f"{d.item_id}.md"
    try:
        from api.services import markdown_parser

        fm = dict(markdown_parser.parse(path).frontmatter)
    except Exception:  # noqa: BLE001
        return False
    case, _why = guards(memory_path, path, fm)
    return case is not None and case.page_id == str((d.request or {}).get("merge_target") or "")


# --------------------------------------------------------------------------- what was read, outside every bank


def _seen_file(memory_path: Path) -> Path:
    from api.services import auth, continuity_sessions

    return auth.cicada_home() / "full_name_reads" / f"{continuity_sessions.bank_file_id(Path(memory_path))}.json"


def _seen(memory_path: Path) -> dict[str, str]:
    try:
        data = json.loads(_seen_file(memory_path).read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(memory_path: Path, item_id: str, digest_: str) -> None:
    """Ids and a hash only, never a name or a word; a file that cannot be written only means a question is read again."""
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
    """Open questions of the shape the guards read (cheap filters only; `guards` decides)."""
    from api.services import inbox_tend

    return [(p, fm) for p, fm, _b in inbox_tend.pending(Path(memory_path))
            if str(fm.get("kind") or "") == "merge_suggestion" and not fm.get("detected")
            and fm.get("fold_page") is not True and str(fm.get("merge_target_hint") or "").strip()
            and len(_words(fm.get("entity_name"))) >= 2]


async def tend(memory_path: Path, settings, judge, *, today: date | None = None, max_looks: int = MAX_LOOKS) -> Report:
    """Look at every open question of the shape, and join the ones the person's own words and two reads support. The
    judge runs outside any write; each join is one `inbox_tend.apply` (Sleep's window is held by the caller). Never
    raises but for an engine failure, which stops the step (the questions are read again next drain)."""
    from api.services import inbox_tend, markdown_parser

    memory_path = Path(memory_path)
    report = Report()
    seen = _seen(memory_path)
    speaker = None
    for path, fm in candidates(memory_path):
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
            # A read that stood (two, cannot tell) is not repeated until something it read changes; one that could not be
            # read at all (a reply that was no JSON, a call that failed) is tried again, twice at most, then the same.
            _remember(memory_path, case.item_id, f"{mark}#{tries + 1}" if result.outcome == "unread" else mark)
            report.skip(f"read:{result.outcome}")
            continue
        d = result.decision
        try:
            ok = await inbox_tend.apply(memory_path, settings, d)
        except Exception as exc:  # noqa: BLE001 - one join that will not settle never stops the others
            logger.info(f"Full-name join not applied: {type(exc).__name__}")
            ok = False
        if ok:
            report.joined += 1
            report.paths.append(f"inbox/settled/{d.item_id}.md")
        else:
            # A settle that cannot apply is tried again like a read that could not be made, twice, not every drain.
            _remember(memory_path, case.item_id, f"{mark}#{tries + 1}")
            report.skip("not_applied")
    return report


async def ask_main(strong, system: str, prompt: str) -> object:
    """The main model's one call, JSON back. On a plan (a CLI engine) it is a plain call that asks for JSON in words, as
    the inbox's own judges do (`inbox_tend.default_llm_fn`), and its reply says which model answered, so the settle can
    carry it as author. (It was written when a plan forced the pair judge's answer shape on every call labelled
    "disambiguation"; since 2026-11-24 a label picks no shape, `engine_schemas.SHAPES`, and this call is kept for the
    model it reports.) A key goes through `_same_name_ask` as the same-name review's does."""
    from api.services import engine_select, entity_resolver, inbox_tend, json_parse, providers

    if str(getattr(strong, "llm_mode", "") or "").strip().lower() not in engine_select.CLI_MODES:
        return await entity_resolver._same_name_ask(strong, system, prompt)
    fn = providers.resolve_llm_fn(strong, stage=inbox_tend.STAGE, is_async=False)
    resp = await asyncio.to_thread(fn, messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                                   response_format={"type": "json_object"})
    parsed = json_parse.parse_json_object_or(inbox_tend._content(resp), {})
    model = inbox_tend._model_of(resp)
    return {**parsed, "_model": model} if model and isinstance(parsed, dict) else parsed


async def run_tail(memory_path: Path, settings, *, user_triggered: bool, judge=None, today: date | None = None) -> Report:
    """Sleep's tail step (after the same-name review, inside the run's window): no engine is resolved and nothing is sent
    unless an open question has the shape. A scheduled run reaches a plan only through the person's switch (ruling 4b),
    a plan limit is a pause (the questions stay), no engine means no read. Never raises."""
    from api.services import same_name_tend

    memory_path = Path(memory_path)
    report = Report()
    try:
        if not await asyncio.to_thread(candidates, memory_path):
            return report
        if judge is None:
            strong, why = await same_name_tend.main_engine(settings, user_triggered=user_triggered)
            if strong is None:
                report.skip(why)
                return report

            async def judge(system: str, prompt: str) -> object:
                return await ask_main(strong, system, prompt)

        return await tend(memory_path, settings, judge, today=today)
    except (engine_errors.EngineThrottled, engine_errors.EngineExhausted, engine_errors.EngineOverage):
        report.skip("plan_limit")
    except Exception as exc:  # noqa: BLE001 - the join never fails a Sleep
        logger.warning(f"Full-name join stopped: {type(exc).__name__}")
        report.skip("error")
    return report
