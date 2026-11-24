"""Sleep's second look at "Is <name> the same as <page>?" when the name has no page (ruling 82, owner 2026-11-24; G98).

`question_revisit` reads a "same as?" question between two PAGES. The largest stale group has only one: a name said in a
conversation that did not earn a page, whose facts wait on a held line (`pending_store`), and a page Stage 2's small model
could not tell it from. Measured on a real bank (real values redacted), 185 of 705 open questions: the page is a project in
84 of 182, a concept in 58, a tool in 18, a person in 11; the two names share a word in 131, the page's name is inside the
asked name in 18 ("<Project> backend"); the same page is the target of 18 questions. Read by hand they are four kinds:
another wording of the same thing, a PART of it, a SIBLING of it, something unrelated that shares a word. Only the first is
a join, and the harm is lopsided: a wrong landing puts one thing's facts on another's page and the owner reads them as true
(G148: "a wrong whole misleads more than a stray page"). So **what stops a wrong landing is in code**, never in the model's
care; the model reads and copies, the code locates, checks and decides.

**One thing (the join).** The name becomes an alias of the page and what is held lands on it, through the settle the
person's own "yes" uses (`inbox_tend.apply`, the resolver's pageless merge, as `already_a_name` lands what is held), as
Sleep's commit under the rule ``revisit_same``, listed under what Sleep settled with the reason and the spans; undo is the
person saying they are two (`inbox_tend.JOINS`). Only one thing counts as showing it, a located line (`evidence.verify`,
never fuzzy) in ONE turn of ONE conversation that is the person's own or a named speaker's (an assistant's turn, an agent's
saved note and text relayed from an app never are: Sleep's own prose comes back as an agent's sentence) and:

* carries the asked name and one of the page's names as two whole, separate spans (the page's name inside the asked name is
  not the page's name said);
* **links them as one thing in the words themselves**: nothing but identity words (also, called, known as, short for, is, the,
  "llamado", "también"...) and punctuation between the two spans (`linked`). "Both names in one sentence" is a list, a
  part and a whole, a successor, a client: the connector must be the person's own statement that they are one, so a sentence
  that relates them any other way ("<A> deploys with <B>", "<A> and <B>") never counts, however a model reads it;
* for names that share a word ("<Family> API", "<Family> Web": the sibling shape) the same pair also needs ruling 82's
  second kind, two copied lines saying one specific fact with a word the bank holds on very few pages
  (`question_revisit.located`'s belief); for a name whose words are the page's name's plus others, or inside it (the part
  shape: "<Project> backend" for "<Project>"), nothing is enough: only the person says a part is its whole.

And **never**, whatever a model says: a held claim, or a claim on the page, that already relates the two as two (a
`part-of`, `uses`, `is-a` between them, either way); an alias the person removed (`aliases_removed`), a "no" (a stored
rejection, a split, the held line kept apart from this page), the name being another page's title or alias
(`alias_collisions`), a line held against another page, a reference or a pronoun (`alias_policy`), a pending doubt.
Read twice: a second read, framed to find why they are TWO, that sees none of the first, must name the same located line
kinds. A person (the 11 of 182 whose page is a person): `question_revisit.person_guards`, the one reading ruling 74 to 74c and
#888 use (short name another person could be, a page that already carries another full name, the owner's page, a no, a split,
a doubt); the held name and the page must both be a person's, and the same located line is the bar.

**Not the same thing (the close).** A part, a sibling or something unrelated is closed as the person's own "No, different"
closes it (`inbox_service.reject_effects`: the held name is kept apart from the page on its own pending line, with the
conversations it holds; a name with nothing held, the pair in `_merge_rejected.yaml`), rule ``revisit_apart``. Why this and
nothing more: the held lines stay held under their own name (a page of its own when the name earns one) and nothing lands on
the page (`pending_store.apart_of`); the same question is not raised again for those conversations; the name never becomes
an alias; and NO relation is written, so a part is never placed (G148's open problem, not this step's). Taking it back is the
generic undo: the question returns and is the person's. It closes only on two reads that agree on "different" with a located
line saying what the name is, and never when a turn of the person's names both in an identity-looking link (a doubt is left
to the person), never a person (who someone is stays the person's).

**Cannot tell.** The question stays exactly as it is, the read remembered outside every bank as `question_revisit` remembers
it (ids, a digest, the reader's model, a count; never a word). Questions about one page are read together
(:data:`GROUP_MAX`): one prompt holds the page's record once and each name's own turns, the code locates each answer in that
name's own turns only, so an answer cannot borrow another's line; the second read is one call for the names the first
settled either way. The bound is `question_revisit`'s (at most :data:`~question_revisit.MAX_READS` questions a run, plan only
through ruling 4's switch, a key inside the spending limit, a demo bank never read); the only network reach is the engine.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from api.services import engine_errors, full_name_join, inbox_tend, pair_evidence, question_revisit as qr, text_fold

RULE_SAME = "revisit_same"
RULE_APART = "revisit_apart"
#: The kind a name-with-no-page question is counted and traced under (the question's own kind is ``merge_suggestion``).
KIND = "name_no_page"
#: Names of one page read in one call (one prompt holds the page once). A bigger pile is read in turns.
GROUP_MAX = 5
MAX_NAME_TURNS = 3

#: What may stand between the two names of a line that says they are one thing (`linked`): the person's own words of
#: identity, in English and Spanish and a little French and German, and nothing that relates two things. A closed list in the
#: safe direction: a language it lacks only means the name stays a question.
LINK_WORDS = frozenset("""also aka called named known as short for stands nickname nicknamed alias dubbed namely formerly
previously now is are was were be that which who this the a an i we you they he she it my our your call calls say said so just
basically essentially literally really simply
llamado llamada llamados conocido conocida conocidos como tambien también es son era eran se le me lo la el los las un una que
cual mi mis nuestro alias apodo apodado dice dicen
dit appele appelé aussi est genannt auch ist""".split())
MAX_LINK_WORDS = 5
#: With no identity word between them, the two names are one thing only inside a bracket or after an equals sign.
OPENERS = frozenset('([=')
#: Punctuation that may stand between them; a full stop, a semicolon, a slash, an ampersand, a plus or a line break may not.
LINK_PUNCT = frozenset(',()"\'“”‘’—–-=:*_`[]<>')
#: Words that open a phrase and carry no name.
_FUNCTION = frozenset("""the a an of for and or with to in on at by from de del la el los las y o con para por en un una""".split())


# --------------------------------------------------------------------------- the code's reading of a line


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+|[^\w\s]|_", str(text or ""))


def _occurrences(words: list[str], parts: list[str]) -> list[tuple[int, int]]:
    n = len(parts)
    return [(i, i + n) for i in range(len(words) - n + 1) if words[i:i + n] == parts] if n else []


def linked(quote: str, a_names: list[str], b_names: list[str]) -> bool:
    """Does the line itself say the two are one thing: some occurrence of a name of A and some occurrence of a name of B,
    neither inside the other, with only identity words (:data:`LINK_WORDS`, at most :data:`MAX_LINK_WORDS`) and
    :data:`LINK_PUNCT` between them, inside one line? Reads the words and nothing else."""
    text = str(quote or "")
    toks = [(t, text_fold.fold(t)) for t in _tokens(text)]
    word_at = [i for i, (t, _f) in enumerate(toks) if re.match(r"\w", t)]
    folded = [toks[i][1] for i in word_at]
    occ: dict[str, list[tuple[int, int]]] = {"a": [], "b": []}
    for side, names in (("a", a_names), ("b", b_names)):
        for name in names:
            occ[side] += _occurrences(folded, qr._key(name).split())
    for a0, a1 in occ["a"]:
        for b0, b1 in occ["b"]:
            if a0 < b1 and b0 < a1:
                continue   # one inside the other (or the same words): not two spans
            first, second = ((a0, a1), (b0, b1)) if a1 <= b0 else ((b0, b1), (a0, a1))
            lo, hi = word_at[first[1] - 1] + 1, word_at[second[0]]
            between = toks[lo:hi]
            if "\n" in text and "\n" in _between_raw(text, toks, lo, hi):
                continue
            words = [f for t, f in between if re.match(r"\w", t)]
            punct = [t for t, _f in between if not re.match(r"\w", t)]
            if (len(words) <= MAX_LINK_WORDS and all(w in LINK_WORDS for w in words) and all(p in LINK_PUNCT for p in punct)
                    and (words or any(p in OPENERS for p in punct))):   # "A, B" alone is a list; "A (B)" and "A = B" are not
                return True
    return False


def _between_raw(text: str, toks: list, lo: int, hi: int) -> str:
    """The raw characters between token ``lo`` and token ``hi`` (so a line break between two names is seen)."""
    pos, start, end = 0, len(text), len(text)
    for i, (t, _f) in enumerate(toks):
        at = text.find(t, pos)
        if at < 0:
            break
        if i == lo:
            start = at
        if i == hi:
            end = at
            break
        pos = at + len(t)
    return text[start:end]


def _word_keys(name: str) -> list[str]:
    return qr._key(name).split()


def shape(a_names: list[str], b_names: list[str]) -> str:
    """The relation of the names themselves: ``nested`` (one's words are a run inside the other's: the part shape),
    ``shares`` (a content word in common: the sibling shape), else ``apart``. Reads the words and nothing else."""
    shared = False
    for a in a_names:
        wa = _word_keys(a)
        for b in b_names:
            wb = _word_keys(b)
            if not wa or not wb:
                continue
            small, big = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
            if any(big[i:i + len(small)] == small for i in range(len(big) - len(small) + 1)):
                return "nested"
            if any(len(w) >= 3 and w not in _FUNCTION for w in set(wa) & set(wb)):
                shared = True
    return "shares" if shared else "apart"


def _identity_line(case: "NameCase") -> bool:
    """Does any turn of the person's own or a named speaker's shown for this name carry both names in an identity link?"""
    return any(t.role in qr._OWN_WORDS and qr._names_both(case.a.names, case.b.names, t.text)
               and linked(t.text, case.a.names, case.b.names) for t in case.turns)


def _relates(memory_path: Path, line, tfm: dict, target_id: str, name: str, target_names: list[str]) -> bool:
    """Does the record already relate the name and the page as two things: a held claim of the name whose object is the page, a
    claim of the page whose object is the name, in any predicate (`part-of`, `uses`, `is-a`...), or a held link that names the
    page? Never an identity (the record has no such predicate)."""
    from api.services.claims import parse_claims
    from api.services.id_utils import sanitize_id

    key, theirs = qr._key(name), {qr._key(n) for n in target_names} | {target_id}
    if line is not None:
        for claim in line.held_claims:
            obj = qr._key(claim.get("object"))
            if str(claim.get("object_kind") or "node") == "node" and obj and (obj in theirs or sanitize_id(obj) == target_id):
                return True
    page = inbox_tend._page(memory_path, target_id)
    if page is not None:
        try:
            for c in parse_claims(page[2]):
                if c.valid_to is None and getattr(c, "object_kind", "node") == "node" and qr._key(c.object) == key:
                    return True
        except Exception:  # noqa: BLE001 - claims unreadable: no relation is read from them
            pass
    return False


# --------------------------------------------------------------------------- what the code knows of a name


@dataclass
class NameCase(qr.Case):
    person: bool = False
    shape: str = "apart"
    held: bool = False
    related: bool = False
    target_type: str = ""


def _held_texts(line) -> list[str]:
    from api.services import typo_join

    return typo_join._held_texts(line) if line is not None else []


def name_case(memory_path: Path, path: Path, fm: dict, *, today: str | None = None) -> tuple[NameCase | None, str]:
    """``(case, "")`` when every engine-free condition holds for this open question about a name with no page, else
    ``(None, why it is left)``. Reads only."""
    from api.services import alias_policy, answered_questions, merge_rejections, pending_store, wrong_aliases
    from api.services.id_utils import resolve_entity_file, sanitize_id

    memory_path = Path(memory_path)
    if (str(fm.get("kind") or "") != "merge_suggestion" or str(fm.get("status") or "pending") != "pending"
            or str(fm.get("detected") or "") not in ("", "person_duplicate") or fm.get("same_title") or fm.get("fold_page") is True
            or fm.get("tidy")):
        return None, "not_this_question"
    entity_id = str(fm.get("entity_id") or "").strip()
    if entity_id and resolve_entity_file(memory_path, entity_id) is not None:
        return None, "has_a_page"
    name = " ".join(str(fm.get("entity_name") or fm.get("entity_mention") or "").split())
    target_id = str(fm.get("merge_target_hint") or "").strip()
    target = inbox_tend._page(memory_path, target_id)
    if not name or target is None:
        return None, "not_a_name_and_a_page"
    target_id, tfm = target[0].stem, dict(target[1])
    if inbox_tend._is_owner_page(tfm) or str(tfm.get("status") or "").lower() in ("archived", "dropped"):
        return None, "owner_or_gone"
    decided, why = inbox_tend.policy(memory_path, path, fm, today=today)
    if decided is not None or why not in ("person", "needs_judge", "judgement"):
        return None, f"policy:{why or 'decided'}"
    own_id = sanitize_id(name)
    line = pending_store.held_line(memory_path, name)
    if line is not None and (line.correspondent or line.title):
        return None, "not_this_name"
    if line is not None and line.held_against:
        return None, "held_against_a_page"
    if target_id in pending_store.apart_of(memory_path, name) or (line is not None and target_id in line.apart_pages()):
        return None, "said_apart"
    if (merge_rejections.is_rejected(memory_path, own_id, target_id) or merge_rejections.is_split(memory_path, own_id, target_id)
            or inbox_tend._split_apart(memory_path, own_id, target_id)):
        return None, "kept_apart"
    asked_type = str(line.type if line is not None else fm.get("suggested_classification") or "").split(" ")[0].lower()
    target_type = inbox_tend._type_of(tfm)
    person = "person" in (asked_type, target_type)
    if person and not (asked_type == "person" and target_type == "person"):
        return None, "person_and_a_thing"
    if not alias_policy.admits(name):
        return None, "not_a_name"
    if qr._removed_from(tfm, [name]):
        return None, "alias_removed"
    if answered_questions._pages_answering(memory_path, answered_questions._key(name)):
        return None, "name_of_a_page"
    if (alias_policy.names_another_page(name, target_id, memory_path / "entities")
            or wrong_aliases.title_of_other_page(memory_path, target_id, name, target_type)):
        return None, "title_of_another_page"
    target_names = full_name_join._names_of(tfm)
    a_names = [name]
    b_names = target_names
    if person:
        people = dict(full_name_join._person_pages(memory_path))
        afm = {"name": name, "type": "person", "aliases": [str(x) for x in (line.aliases if line is not None else []) if str(x).strip()]}
        guarded = qr.person_guards(memory_path, own_id, afm, target_id, tfm, people, held_skip=frozenset({name.lower()}))
        if isinstance(guarded, str):
            return None, guarded
        a_names, b_names = guarded
        a_names = [name]
    a = qr.Side(own_id, name, a_names, _held_texts(line), [e for e in (line.episodes() if line is not None else []) if e.startswith("ep_")],
                {}, [name])
    b = qr._side(memory_path, target_id, tfm, b_names)
    episodes, why = qr._conversations(memory_path, fm, a, b)
    if why:
        return None, why
    turns, why = qr._turns_for(memory_path, episodes, a, b)
    if why:
        return None, why
    if not a.texts and not any(t for t in turns if not t.both or t.role in qr._OWN_WORDS):
        return None, "nothing_to_read"
    if not b.texts:
        return None, "nothing_to_read"
    # Only a few of the turns that name just the asked name are shown (the person's own first): the new information is in them.
    both = [t for t in turns if t.both]
    newest = sorted((t for t in turns if not t.both), key=lambda t: (t.day, t.episode), reverse=True)
    one = sorted(newest, key=lambda t: t.role not in qr._OWN_WORDS)[:MAX_NAME_TURNS]
    turns = [*both, *one]
    for i, t in enumerate(turns, 1):
        t.n = i
    case = NameCase(path.stem, a, b, turns, [], dict(fm), person=person, held=line is not None,
                    shape="person" if person else shape(a_names, b_names), target_type=target_type,
                    related=_relates(memory_path, line, tfm, target_id, name, target_names))
    return case, ""


# --------------------------------------------------------------------------- the reads

SYSTEM = ("You decide, from what a person's memory and their conversations hold, whether a name the memory could not place "
          "is another name for a page of the memory or something else, and you answer in JSON.")

SPEAKER = (' The speaker, the person whose conversations these are, appears in the memory as "{speaker}".')

PROMPT = """A person's memory has a page about "{page}" (also written: {page_names}). What the memory holds about it:
{record}

The memory also heard the names below in the person's conversations and could not tell whether each is just ANOTHER NAME for that very page, or something else.{speaker} For each NAME decide which, from what is written here alone.

{blocks}

For each NAME answer with one of:
- "same": it is another name for that page: the same thing, said another way (an abbreviation, a nickname, an older name, a description in place of the name). Give "said_turn": the number of one of THAT NAME's own turns and "said": the words of that turn, copied word for word and without gaps, in which the person (or a named speaker) says the NAME and the page's name are one and the same thing ("also called", "known as", "short for", "X, the Y", in any language); the words must carry both names. Give "here" and "there" only if you can copy one line about the NAME and one about the page that state the SAME specific fact.
- "different": it is something else: a PART, feature or component of the page's thing; a version of it; a SIBLING (another thing of the same family, maker or kind); or unrelated though it shares a word. Give "relation": "part", "sibling", "unrelated" or "other", and "line": one line copied word for word from the memory shown or from one of that NAME's turns that says what the NAME is.
- "cannot_tell": anything else.
Rules:
- A wrong "same" puts one thing's facts on another thing's page; a question left costs little. Sharing a word, a family, a maker or a project is NOT being the same thing. A part of a page's thing is not the thing. When in doubt: "cannot_tell".
- Both names in one turn is not one thing: the words must say they are one thing. A turn that lists them, compares them, or says one belongs to, uses, replaces or runs on the other says they are TWO.
- Only the person's own turns and a named speaker's turns can say it: what an assistant said, a note an agent saved and text relayed from an app are never the words that present two names as one thing.
- Decide only from what is shown. What you know about the names yourself is no evidence.

Answer in JSON only: {{"answers": [{{"name": <number>, "verdict": "same" | "different" | "cannot_tell", "said_turn": <number or null>, "said": "words copied" | null, "here": "words copied" | null, "there": "words copied" | null, "relation": "part" | "sibling" | "unrelated" | "other" | null, "line": "words copied" | null, "reason": "one short sentence"}}, ...]}}
"""

SCEPTIC_SAME = ("You are the sceptical reader. For each NAME below an earlier reader said it is another name for the page. Your "
                "job is to look for any reason it is TWO things before you answer: a part, version or sibling of the page's thing; "
                "a turn that lists, compares or relates them; a line that is about something else. Say \"same\" only if, having "
                "looked for that reason, you find none, and copy the words again.\n\n")
SCEPTIC_DIFF = ("You are the sceptical reader. For each NAME below an earlier reader said it is something else than the page. Your "
                "job is to look for any reason it is in fact another NAME for the very page (a turn in which the person presents "
                "them as one thing; the memory saying the same of both) before you answer. Say \"different\" only if you find "
                "none, and copy a line that says what the NAME is.\n\n")


@dataclass
class Result:
    verdict: str = ""            # same | different | cannot_tell | "" (nothing usable)
    read: qr.Read = field(default_factory=qr.Read)
    relation: str = ""
    line: str = ""
    span: dict | None = None
    reason: str = ""
    model: str = ""


@dataclass
class Outcome:
    outcome: str                 # join | apart | unsure | unread | skip
    case: NameCase | None = None
    why: str = ""
    decision: object = None
    digest: str = ""
    reads: int = 0
    spans: list = field(default_factory=list)


def build_prompt(cases: list[NameCase], speaker: str | None, mode: str = "first") -> str:
    named = " ".join(str(speaker or "").replace('"', "").split())
    head = cases[0].b
    blocks = []
    for k, case in enumerate(cases, 1):
        both = [t for t in case.turns if t.both]
        one = [t for t in case.turns if not t.both]

        def shown(group):
            return "\n".join(f"[{t.n}] ({t.day or 'undated'}, {t.role}) {t.text}" for t in group) or "(none)"

        blocks.append(f"NAME {k}: \"{case.a.name.replace(chr(34), '')}\"\nWhat the memory holds about it:\n{qr._lines(case.a.texts)}\n"
                      f"Its turns naming it AND the page:\n{shown(both)}\nIts turns naming only it:\n{shown(one)}")
    prompt = PROMPT.format(
        page=head.name.replace('"', ""), page_names=", ".join(f"“{n}”" for n in head.all_names if qr._key(n) != qr._key(head.name))
        or "no other name", record=qr._lines(head.texts), speaker=SPEAKER.format(speaker=named) if named else "",
        blocks="\n\n".join(blocks))
    return {"same": SCEPTIC_SAME, "different": SCEPTIC_DIFF}.get(mode, "") + prompt


def _locate_line(memory_path: Path, case: NameCase, line: str) -> dict | None:
    """The copied line of a "different", located (exact, whitespace, case: never fuzzy) in what was shown for this name,
    saying the name: ``{"episode", "start", "end", "kind"}`` when it is in a person's or speaker's turn, ``{}`` when in the
    memory's text, ``None`` when it is nowhere."""
    from api.services import evidence
    from api.services import same_name_people as snp

    text = " ".join(str(line or "").split())
    if (len(re.sub(r"\W+", "", text)) < qr.MIN_QUOTE_CHARS or "…" in text or "..." in text
            or not pair_evidence.names_in([qr._key(case.a.name)], text)):
        return None
    for turn in case.turns:
        if evidence.locate(turn.text, text) is not None:
            found = qr._quote_span(memory_path, case, text)
            return found[2] if found is not None else {}
    return {} if snp._located(text, [*case.a.texts, *case.b.texts]) else None


def _same_result(memory_path: Path, case: NameCase, item: dict, speaker: str | None, model: str) -> Result:
    parsed = {**item, "verdict": "one"}
    parsed.pop("_model", None)
    read = qr.located(memory_path, case, parsed, speaker)
    read.model = model
    if "said" in read.kinds and not linked(read.quote, case.a.names, case.b.names):
        read.kinds = [k for k in read.kinds if k != "said"]
        read.spans = []
        read.quote = ""
    if not read.kinds:
        return Result("cannot_tell", read, reason=read.reason, model=model)
    return Result("same", read, reason=read.reason, model=model)


def _different_result(memory_path: Path, case: NameCase, item: dict, model: str) -> Result:
    relation = str(item.get("relation") or "").strip().lower()
    if relation not in ("part", "sibling", "unrelated", "other"):
        return Result("cannot_tell", model=model, reason="no kind of difference")
    span = _locate_line(memory_path, case, str(item.get("line") or ""))
    if span is None:
        return Result("cannot_tell", model=model, reason="the line said is not in the record")
    return Result("different", relation=relation, line=str(item.get("line") or ""), span=span or None,
                  reason=qr._trim(item.get("reason"), 200), model=model)


def parse_answers(memory_path: Path, cases: list[NameCase], parsed, speaker: str | None) -> list[Result]:
    """One Result per case, in order, from one reply. An answer missing, malformed or about another number is nothing usable."""
    out = [Result() for _ in cases]
    if not isinstance(parsed, dict):
        return out
    model = str(parsed.get("_model") or "")
    answers = parsed.get("answers")
    if not isinstance(answers, list) and "verdict" in parsed and len(cases) == 1:
        answers = [{**parsed, "name": 1}]
    seen: set[int] = set()
    for item in answers if isinstance(answers, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            k = int(item.get("name"))
        except (TypeError, ValueError):
            continue
        if not 1 <= k <= len(cases) or k in seen:
            continue
        seen.add(k)
        word = str(item.get("verdict") or "").strip().lower().replace(" ", "_")
        case = cases[k - 1]
        if word == "same":
            out[k - 1] = _same_result(memory_path, case, item, speaker, model)
        elif word in ("different", "two"):
            out[k - 1] = _different_result(memory_path, case, item, model)
        elif word == "cannot_tell":
            out[k - 1] = Result("cannot_tell", model=model, reason=qr._trim(item.get("reason"), 200))
    return out


async def _read(memory_path: Path, cases: list[NameCase], judge, speaker, mode: str) -> list[Result]:
    try:
        parsed = await judge(SYSTEM, build_prompt(cases, speaker, mode))
    except asyncio.CancelledError:
        raise
    except engine_errors.EngineError:
        raise
    except Exception as exc:  # noqa: BLE001 - a read that failed has read nothing
        logger.debug(f"Name revisit read failed: {type(exc).__name__}")
        return [Result() for _ in cases]
    return parse_answers(memory_path, cases, parsed, speaker)


def enough_same(case: NameCase, result: Result) -> bool:
    """What a located "same" must show for this name's shape (the module's list). Reads only."""
    kinds = set(result.read.kinds)
    if result.verdict != "same" or case.related or "said" not in kinds:
        return False
    if case.shape == "nested":
        return False                      # the part shape: only the person says a part is its whole
    if case.shape == "shares":
        return "belief" in kinds          # the sibling shape: a located identity line AND a specific shared fact
    return True


def _guard(memory_path: Path, case: NameCase) -> dict:
    from api.services import pending_store

    guard = inbox_tend._guard(memory_path, case.b.id)
    store = pending_store.store_path(Path(memory_path))
    guard[store.relative_to(memory_path).as_posix()] = inbox_tend._hash(store)
    return guard


def digest(memory_path: Path, case: NameCase) -> str:
    h = hashlib.sha256()
    for part in (json.dumps(_guard(memory_path, case), sort_keys=True), json.dumps(case.a.texts), json.dumps(case.b.texts),
                 json.dumps([(t.episode, t.text) for t in case.turns]), case.a.id, case.b.id, case.shape):
        h.update(part.encode("utf-8", "replace"))
        h.update(b"\0")
    return h.hexdigest()[:20]


def _reason_same(result: Result) -> str:
    from api.services import episode_scrub

    read = result.read
    text = f"The person's own words say they are one thing: “{qr._trim(read.quote, qr.REASON_QUOTE_CHARS)}”"
    return episode_scrub.scrub(text)[0]


def _reason_apart(case: NameCase, result: Result) -> str:
    from api.services import episode_scrub

    return episode_scrub.scrub(f"Read against everything on record, it is a different thing ({result.relation}): "
                               f"“{qr._trim(result.line, qr.REASON_QUOTE_CHARS)}”")[0]


async def assess_group(memory_path: Path, cases: list[NameCase], judge, *, speaker: str | None = None) -> tuple[list[Outcome], int]:
    """The reads for names of ONE page, then the code's decision for each. Writes nothing. What the settle re-checks (the
    question's bytes, the page and the pending store's hashes) is taken BEFORE the first read, so a change while the model reads
    leaves the question. Returns ``(one outcome per case, model calls made)``. An engine failure is the caller's (a plan limit
    is a pause)."""
    memory_path = Path(memory_path)
    calls = 0
    prints = [path_bytes(memory_path, c) for c in cases]
    guards = [_guard(memory_path, c) for c in cases]
    outcomes = [Outcome("unread", c, digest=digest(memory_path, c)) for c in cases]
    first = await _read(memory_path, cases, judge, speaker, "first")
    calls += 1
    for o in outcomes:
        o.reads = 1
    same = [i for i, r in enumerate(first) if r.verdict == "same" and enough_same(cases[i], r)]
    diff = [i for i, r in enumerate(first) if r.verdict == "different" and not cases[i].person]
    for i, r in enumerate(first):
        if i not in same and i not in diff and r.verdict:
            outcomes[i].outcome = "unsure"        # a "cannot tell", or an answer the code's checks withdrew
    second_same: dict[int, Result] = {}
    second_diff: dict[int, Result] = {}
    if same:
        for i, r in zip(same, await _read(memory_path, [cases[i] for i in same], judge, speaker, "same")):
            outcomes[i].reads = 2
            second_same[i] = r
        calls += 1
    if diff:
        for i, r in zip(diff, await _read(memory_path, [cases[i] for i in diff], judge, speaker, "different")):
            outcomes[i].reads = 2
            second_diff[i] = r
        calls += 1
    for i in same:
        o, case = outcomes[i], cases[i]
        r2 = second_same[i]
        if not enough_same(case, r2):
            o.outcome = "unsure"
            continue
        r1 = first[i]
        o.outcome = "join"
        model = r1.model if r1.model and r1.model == r2.model else None
        user = next((s for s in r1.read.spans if s.get("kind") == "user"), None)
        quote = {"episode": user["episode"], "quote": r1.read.quote} if user is not None else None
        o.spans = [*r1.read.spans]
        o.decision = inbox_tend.Decision(
            case.item_id, "merge_suggestion", RULE_SAME, {"action": "merge", "merge_target": case.b.id},
            answer=f"Same as {case.b.name}", quote=quote, model=model, fingerprint=prints[i], guard=guards[i],
            reason=_reason_same(r1), spans=o.spans)
    for i in diff:
        o, case = outcomes[i], cases[i]
        r1, r2 = first[i], second_diff[i]
        if r2.verdict != "different" or _identity_line(case):
            o.outcome = "unsure"
            continue
        o.outcome = "apart"
        model = r1.model if r1.model and r1.model == r2.model else None
        span = r1.span or r2.span
        o.spans = [span] if span else []
        o.decision = inbox_tend.Decision(
            case.item_id, "merge_suggestion", RULE_APART, {"action": "reject", "merge_target": case.b.id},
            answer=f"Not the same as {case.b.name}", model=model, fingerprint=prints[i], guard=guards[i],
            reason=_reason_apart(case, r1), spans=o.spans)
    return outcomes, calls


def path_bytes(memory_path: Path, case: NameCase) -> bytes:
    try:
        return (Path(memory_path) / "inbox" / f"{case.item_id}.md").read_bytes()
    except OSError:
        return b""


def still_holds(memory_path: Path, d) -> bool:
    """Inside the settle (`inbox_tend.still_holds`): the engine-free conditions are still met for the very question and the
    very page the reads were about."""
    memory_path = Path(memory_path)
    path = memory_path / "inbox" / f"{d.item_id}.md"
    try:
        from api.services import markdown_parser

        fm = dict(markdown_parser.parse(path).frontmatter)
    except Exception:  # noqa: BLE001
        return False
    case, _why = name_case(memory_path, path, fm)
    if case is None or case.b.id != str((d.request or {}).get("merge_target") or ""):
        return False
    return (not case.related and case.shape != "nested") if d.rule == RULE_SAME else not _identity_line(case)


# --------------------------------------------------------------------------- the step's part


@dataclass
class Context:
    """What `question_revisit.tend` hands this module: its state, so a name and a pair of pages are one step."""
    memory_path: Path
    settings: object
    today: object
    dry_run: bool
    judge: object
    report: object
    seen: dict
    model: str
    note: object
    remember: object
    speaker: object          # async () -> str
    room: int = 0            # how many more questions the run may read


async def look(ctx: Context, path: Path, fm: dict, rest: list[tuple[Path, dict]], done: set[str]) -> None:
    """One open question about a name with no page, and the others about the same page that are due, together."""
    memory_path, report = ctx.memory_path, ctx.report
    item_id = path.stem
    case, why = await asyncio.to_thread(name_case, memory_path, path, fm, today=ctx.today.isoformat())
    if case is None:
        report.skip(why)
        ctx.note(item_id, KIND, f"left:{why}")
        return
    group: list[tuple[Path, dict, NameCase, str]] = []

    async def admit(p: Path, f: dict, c: NameCase) -> bool:
        mark = await asyncio.to_thread(digest, memory_path, c)
        if not qr.due(ctx.seen.get(p.stem), mark, ctx.model):
            report.skip("read_already")
            ctx.note(p.stem, KIND, "left:read_already")
            return False
        group.append((p, f, c, mark))
        return True

    if not await admit(path, fm, case):
        return
    if ctx.judge is not None:
        for p, f in rest:
            if len(group) >= min(GROUP_MAX, max(ctx.room, 1)):
                break
            if p.stem in done or str(f.get("merge_target_hint") or "").strip() != case.b.id:
                continue
            c, _w = await asyncio.to_thread(name_case, memory_path, p, f, today=ctx.today.isoformat())
            if c is None or c.b.id != case.b.id:
                continue
            report.looked += 1
            done.add(p.stem)
            await admit(p, f, c)
    if ctx.judge is None:
        for p, _f, _c, _m in group:
            ctx.note(p.stem, KIND, "would_read", "name_revisit")
        return
    speaker = await ctx.speaker()
    outcomes, calls = await assess_group(memory_path, [g[2] for g in group], ctx.judge, speaker=speaker or None)
    report.calls += calls
    applied = False
    for (p, _f, c, mark), o in zip(group, outcomes):
        report.read += 1
        entry = ctx.seen.get(p.stem)
        if o.decision is None:
            same = bool(entry and entry.get("d") == mark and entry.get("m") == ctx.model)
            tries = int(entry.get("t") or 0) + 1 if same else 1
            ctx.remember(p.stem, mark, o.outcome, tries if o.outcome == "unread" else 0)
            ctx.note(p.stem, KIND, f"read:{o.outcome}")
            continue
        word, rule, done_word = (("would_join", RULE_SAME, "joined") if o.outcome == "join"
                                 else ("would_apart", RULE_APART, "closed_apart"))
        if ctx.dry_run:
            report.settled += 1
            ctx.note(p.stem, KIND, word, rule, o.spans)
            continue
        if applied:
            # The page and the pending store changed by the settle just made, in this one run's own window: what the next one
            # read of them is re-taken (its located lines, its guards and `still_holds` are unchanged).
            o.decision.guard = _guard(memory_path, c)
        try:
            ok = await inbox_tend.apply(memory_path, ctx.settings, o.decision)
        except Exception as exc:  # noqa: BLE001 - one that will not settle never stops the others
            logger.info(f"Name revisit not applied: {type(exc).__name__}")
            ok = False
        if ok:
            applied = True
            report.settled += 1
            report.paths.append(f"inbox/settled/{p.stem}.md")
            ctx.seen.pop(p.stem, None)
            ctx.note(p.stem, KIND, done_word, rule, o.spans)
        else:
            ctx.remember(p.stem, mark, "not_applied", 1)
            ctx.note(p.stem, KIND, "left:not_applied")
