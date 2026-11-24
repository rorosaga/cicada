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
* **is the person's own statement that they are one thing, decided by the code on the ONE sentence that holds the pair**
  (`linked`; review of 2026-11-24 with a judge rigged to answer "same": single function words such as "the", "a", "for",
  "as", "it" are no identity words, and only the words between the names used to be read): no question, negation, doubt,
  condition, contrast or plural subject anywhere in the sentence (not, n't, no, never, if, whether, think, maybe, "are
  both", and the Spanish, French and German words); only nothing or an opener ("I call it") before the first name; between
  the names exactly one phrase of identity from a closed list (:data:`PHRASES`: "also called", "known as", "aka", "short
  for", "is the same as", "is just", "llamado"...), or a bracket or an equals sign with no words, or a bare "<A> is <B>"
  only as the whole sentence; after the second name no possessive, no "of/de/for/to/and", no noun running on from it ("<A>
  is <B>'s backend", "<A> is a <B>", "<A> is for <B>", "tools like <A> (<B>)" are all refused). Every other sentence of the
  person's own turns that holds both names must be one as well, so a turn that also says "<A> is not <B>" leaves the
  question. A sentence that relates them any other way never counts, however a model reads it. When in doubt the answer is
  "not linked": the question stays open, which is always allowed;
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
generic undo: the question returns and is the person's. It closes only on two reads that agree on "different" with a line located (never fuzzy) in a turn of the person's own or a
named speaker's that says the name (never the held line's own text, the page's text or an assistant's turn: Sleep wrote the
first two and an agent repeats them), and never when a sentence of ANY such turn could be PRESENTING the two as one thing
(`_presented_as_one`: the names adjacent, or joined only by a marker of equivalence, :data:`MARKERS`: "I mean", "or", "/", "=", "aka",
"i.e.", "that is", "also called", "known as", "short for", "o sea", "es decir", a bracket straight after the first name; a name
the page shares with another page counts as the page's for this check). A sentence that names both with anything else
between them, a preposition, a verb, a possessive, other nouns ("the <A> for <B>", "<A> in <B>", "<B>'s <A>", "<A> is part of
<B>"), says they are two and holds nothing back: a part of a project is named with its project in one sentence, nearly always.
Never a person (who someone is stays the person's).

**A turn too long to show.** The whole turn is kept for locating a quote and for every check the code makes (the join's sentence
checks and the close's block read every sentence of it); the reader is shown the sentences that hold either name, each with the
sentence before and after, in order, a cut mark between pieces (`cut_ranges`, `question_revisit.Turn`), up to the same cap, and
a line the reader was not shown is never the located one. Past the cap the question is left, ``turn_too_long``. The two-pages
path (`question_revisit`) is unchanged: it still refuses a turn that long.

**A page that has faded.** A question whose page was archived since, about a name not said after the page's last mention
(each conversation by its own date against `last_referenced`; `said_after`), is retired with no read under ``target_faded``
(:func:`faded_decision`): nothing is written to any page, the held lines stay held, undoable. A name said after is read like
any other, but a "same" is never landed: the person's own yes bumps the page's `last_referenced` and leaves its status, so
the lines would sit on an archived page nobody sees. A dropped page, a missing page and the owner's page keep their own
reasons (``target_dropped``, ``target_missing``, ``owner_page``).

**A label nobody said.** Measured on the same bank (real values redacted): in 107 of the 185 the asked name appears in no text of the
conversation its question was raised from ("<Feature> redesign", "<Project> extraction worker": a label Stage 1 coined for a
thing), in 64 only outside the person's own turns, in 15 in the person's own turn; 83 of the 115 questions the second look read
and left "unsure" were of the first kind, and no line can ever be located for a name nobody said, so each was read again every
time a page changed and could never close. Such a question is retired with no read under ``name_not_said``
(:func:`unsaid`, :func:`unsaid_decision`): the name is located (`evidence.locate`: exact, then whitespace, then case-insensitive;
and, only to say MORE was said, the folded-words check of `question_revisit._hits`, so a hyphen, an accent or a case never makes a
name unsaid; never fuzzy) in NO text, whoever's turn, of the conversation the question was raised from or any conversation the
held lines cite (their `heard_in`, their held claims' evidence), the conversation's frontmatter included (a title or a source is
text a label may come from). A rewording is "not said"; a name differing only in case or spacing is said. Nothing is written to
any page, the held lines stay held exactly as they are (nothing renamed, merged or dropped: ruling 73), undoable. **Guards:** a
conversation the check should read that is missing or cannot be read leaves the question (``conversation_missing``, counted); a
question with no conversation to read is not retired; a person (the held name or the page a person) is never retired this way (a
name may come from a field the text lacks: an attendee list, a sender, a Contacts card, and a coined role for a person is
`role_people`'s lane); a question the person undid or put off never reaches here (`inbox_tend.policy`, before). The same check
at Stage 2's raise site is :func:`coined_label` (the question is not raised; the held line is written as today).

A name of the page that another live page also answers to is no name of it here, nor is a one-word alias the conversation
itself uses straight after a determiner ("the scheduler": a common noun there); the turns that say such a name next to the
asked name still stop a close.

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
#: A question about a page that has since faded (archived), the name not said since the page's last mention: retired with
#: nothing written (`inbox_tend._retire`), the held lines staying held under their own name.
RULE_FADED = "target_faded"
#: A question about a label nobody said (:func:`unsaid`): retired the same way, with no read.
RULE_UNSAID = "name_not_said"
#: The kind a name-with-no-page question is counted and traced under (the question's own kind is ``merge_suggestion``).
KIND = "name_no_page"
#: Names of one page read in one call (one prompt holds the page once). A bigger pile is read in turns.
GROUP_MAX = 5
MAX_NAME_TURNS = 3

#: The words that say, between two names, that they are one thing (`linked`), as folded word tuples (lower case, accents off):
#: the person's own phrases of identity in English and Spanish and a little French and German, never a single function word
#: ("is the", "for", "like", "also", "a") and never a verb that relates two things. A closed list in the safe direction: a
#: phrase it lacks only means the name stays a question.
PHRASES = frozenset({
    ("also", "called"), ("also", "known", "as"), ("also", "named"), ("known", "as"), ("aka",), ("a", "k", "a"), ("short", "for"),
    ("stands", "for"), ("is", "short", "for"), ("is", "called"), ("is", "also", "called"), ("is", "also", "known", "as"),
    ("is", "known", "as"), ("is", "aka"), ("is", "the", "same", "as"), ("is", "same", "as"), ("is", "just"),
    ("is", "just", "another", "name", "for"), ("is", "another", "name", "for"), ("formerly", "called"), ("formerly", "known", "as"),
    ("previously", "called"), ("previously", "known", "as"), ("now", "called"), ("now", "known", "as"), ("is", "now", "called"),
    ("which", "i", "also", "call"), ("which", "i", "call"), ("which", "we", "call"), ("i", "also", "call"),
    ("which", "is", "also", "called"), ("which", "is", "called"), ("which", "is", "also", "known", "as"),
    ("which", "is", "known", "as"), ("which", "is", "short", "for"),
    ("tambien", "llamado"), ("tambien", "llamada"), ("llamado", "tambien"), ("llamada", "tambien"), ("conocido", "como"),
    ("conocida", "como"), ("tambien", "conocido", "como"), ("tambien", "conocida", "como"), ("es", "lo", "mismo", "que"),
    ("es", "el", "mismo", "que"), ("es", "la", "misma", "que"), ("es", "solo"), ("es", "simplemente"), ("abreviatura", "de"),
    ("abreviado", "de"), ("es", "otro", "nombre", "de"), ("es", "otro", "nombre", "para"), ("o", "sea"), ("es", "tambien", "llamado"),
    ("es", "conocido", "como"), ("es", "llamado"), ("al", "que", "llamo"), ("al", "que", "llamamos"), ("que", "tambien", "llamo"),
    ("aussi", "appele"), ("est", "aussi", "appele"), ("connu", "sous", "le", "nom", "de"), ("auch", "genannt"), ("ist", "auch", "genannt"),
    ("auch", "bekannt", "als"), ("bekannt", "als"),
    # a bare "called" / "I call" / "alias" also reads as a verb ("I called Quartzline"): only after a comma
    ("called",), ("llamado",), ("llamada",), ("alias",), ("i", "call"), ("we", "call"), ("que", "llamo"), ("que", "llamamos"),
    ("appele",), ("dit",), ("genannt",),
})
#: The phrases that need a comma before them (see above).
NEEDS_COMMA = frozenset({("called",), ("llamado",), ("llamada",), ("alias",), ("i", "call"), ("we", "call"), ("que", "llamo"),
                         ("que", "llamamos"), ("appele",), ("dit",), ("genannt",)})
#: A bare "<A> is <B>" (and "<A> es <B>") is one thing only when the sentence ends right after the second name.
BARE = frozenset({("is",), ("es",)})
#: What may come before the first name: nothing, or one of these openers.
PREFIXES = frozenset({
    (), ("so",), ("and",), ("well",), ("ok",), ("okay",), ("yes",), ("yeah",), ("oh",), ("btw",), ("anyway",), ("also",),
    ("i", "call", "it"), ("we", "call", "it"), ("i", "call", "this"), ("we", "call", "this"), ("they", "call", "it"),
    ("y",), ("pues",), ("bueno",), ("o", "sea"), ("le", "digo"), ("yo", "le", "digo"), ("lo", "llamo"), ("lo", "llamamos"),
})
#: A word straight after the second name that may continue the sentence about the one thing.
CONTINUES = frozenset("is was es era which that who que has tiene cual quien".split())
#: A word that opens what follows the second name and makes it a part, a member or a list.
NOT_AFTER = frozenset("""and or y o e ni but with of de del for to plus as like como both too also tambien para por con sin
without except""".split())
#: Anywhere in the sentence: a doubt, a denial, a condition, a contrast. The sentence is not the person saying they are one.
HEDGES = frozenset("""not no never if whether think thinks thought doubt doubts maybe perhaps probably possibly might could guess
suppose supposed unsure unclear wonder wondering seems seem apparently supposedly allegedly but unless however although though
except instead rather than versus vs nor neither either nunca jamas si quiza quizas creo cree pienso dudo duda supongo acaso
pero aunque sino excepto salvo tampoco ni pas ne jamais mais pense crois nicht nie kein keine wenn ob vielleicht aber glaube
denke""".split())
HEDGE_PHRASES = (" tal vez ", " a lo mejor ", " peut etre ", " kind of ", " sort of ")
#: Anywhere in the sentence: more than one thing is the subject ("are both", "son ambos"), so it is a list or a pair.
PLURALS = frozenset("are were both all together these those son ambos ambas todos todas juntos juntas sont beide alle".split())
#: With no words between them, the two names are one thing only inside a bracket or after an equals sign.
OPENERS = frozenset("(=")
#: Punctuation that may stand between them; a full stop, a semicolon, a slash, an ampersand, a plus or a line break may not.
LINK_PUNCT = frozenset(",()\"'“”‘’—–-=:*_`[]<>")
_CLOSERS = frozenset(".!)\"”'’…")
#: What may stand between two names that a sentence could be PRESENTING as one thing (`_presented_as_one`, the close's block): the
#: phrases of identity of :data:`PHRASES` and the looser ones a person says in passing. Only these withhold a close; any other
#: word between the names (a preposition, a verb, a possessive, another noun) relates them as two.
MARKERS = PHRASES | frozenset({
    ("i", "mean"), ("or",), ("i", "e"), ("that", "is"), ("also", "known", "as"), ("known", "as"), ("short", "for"),
    ("o",), ("o", "sea"), ("es", "decir"), ("tambien", "llamado"), ("tambien", "llamada"), ("tambien", "conocido", "como"),
    ("alias",), ("aka",), ("a", "k", "a"), ("or", "rather"), ("o", "mejor", "dicho"),
})
#: An article straight before the second name ("known as the <Page>") is no word between two things.
_ARTICLES = frozenset("the a an my our el la los las un una mi".split())
#: Words that open a phrase and carry no name.
_FUNCTION = frozenset("""the a an of for and or with to in on at by from de del la el los las y o con para por en un una""".split())

#: A sentence ends at ! ? … or a full stop after a word of three letters or more (so "e.g." and "vs." never split a line and
#: a short word's full stop runs two sentences into one, which only makes the checks below stricter). A semicolon, a colon and
#: a line break never end one: what a person says in the same breath is one sentence here.
_SENTENCE = re.compile(r"(?<=[!?…])\s+|(?<=[^\W\d_]{3}[.])\s+|(?<=\d[.])\s+")


# --------------------------------------------------------------------------- the code's reading of a line


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+|[^\w\s]|_", str(text or ""))


def sentences(text: str) -> list[str]:
    """The sentences of a turn, as the checks here read them (see :data:`_SENTENCE`)."""
    return [x.strip() for x in _SENTENCE.split(str(text or "")) if x and x.strip()]


def _occurrences(words: list[str], parts: list[str]) -> list[tuple[int, int]]:
    n = len(parts)
    return [(i, i + n) for i in range(len(words) - n + 1) if words[i:i + n] == parts] if n else []


def _hedged(sentence: str, folded_words: list[str]) -> bool:
    """A question, a denial, a doubt, a condition or a plural subject anywhere in the sentence."""
    if "?" in sentence or "¿" in sentence or re.search(r"n['’]t\b", sentence.lower()):
        return True
    padded = " " + " ".join(folded_words) + " "
    return any(w in HEDGES or w in PLURALS for w in folded_words) or any(p in padded for p in HEDGE_PHRASES)


def _linked_sentence(sentence: str, a_names: list[str], b_names: list[str]) -> bool:
    """Does this ONE sentence say, in the person's own words of identity, that the asked name and the page's name are one thing?

    Every one of these must hold, and a doubt on any is "not linked" (the question then stays open, which is always allowed):
    no question, denial, doubt, condition, contrast or plural subject anywhere in it; one whole span of each name, neither
    inside the other (a name inside a longer span of the other side is that other name's word, not itself); only an opener
    (:data:`PREFIXES`) before the first; between them exactly one phrase of identity (:data:`PHRASES`), a bare "is" only when
    the sentence ends right after the second name, or a bracket or an equals sign with no words; and after the second name
    nothing that makes it a part, a member or a list: no possessive, no word that opens a conjunction or a preposition, no noun
    running on from the name."""
    toks = [(t, text_fold.fold(t)) for t in _tokens(sentence)]
    word_at = [i for i, (t, _f) in enumerate(toks) if re.match(r"\w", t)]
    folded = [toks[i][1] for i in word_at]
    if _hedged(sentence, folded):
        return False
    occ: dict[str, set[tuple[int, int]]] = {"a": set(), "b": set()}
    for side, names in (("a", a_names), ("b", b_names)):
        for name in names:
            occ[side].update(_occurrences(folded, qr._key(name).split()))
    if occ["a"] & occ["b"]:
        return False                        # the same words are both names: nothing says which is which
    every = occ["a"] | occ["b"]
    for side in occ:
        occ[side] = {s for s in occ[side] if not any(o != s and o[0] <= s[0] and s[1] <= o[1] for o in every)}
    if len(occ["a"]) != 1 or len(occ["b"]) != 1:
        return False
    (a0, a1), (b0, b1) = next(iter(occ["a"])), next(iter(occ["b"]))
    if a0 < b1 and b0 < a1:
        return False
    first, second = ((a0, a1), (b0, b1)) if a1 <= b0 else ((b0, b1), (a0, a1))
    head = toks[:word_at[first[0]]]
    between = toks[word_at[first[1] - 1] + 1:word_at[second[0]]]
    tail = toks[word_at[second[1] - 1] + 1:]

    def split(group):
        return ([f for t, f in group if re.match(r"\w", t)], [t for t, _f in group if not re.match(r"\w", t)])

    head_words, head_punct = split(head)
    mid_words, mid_punct = split(between)
    tail_words, tail_punct = split(tail)
    if tuple(head_words) not in PREFIXES or not all(p in LINK_PUNCT for p in head_punct):
        return False
    if not all(p in LINK_PUNCT for p in mid_punct):
        return False
    if tuple(mid_words) in BARE:
        # "<A> is <B>." and nothing else: no opener, no mark between, nothing after but the end of the sentence.
        return not head_words and not mid_punct and not tail_words and all(p in _CLOSERS for p in tail_punct)
    if mid_words:
        if tuple(mid_words) not in PHRASES or (tuple(mid_words) in NEEDS_COMMA and "," not in mid_punct):
            return False
    elif not any(p in OPENERS for p in mid_punct):   # "A, B" alone is a list; "A (B)" and "A = B" are not
        return False
    rest = list(tail)
    if "(" in mid_punct:
        if not rest or rest[0][0] != ")":
            return False
        rest = rest[1:]
    if not rest:
        return True
    nxt = rest[0][0]
    if re.match(r"\w", nxt):
        return rest[0][1] in CONTINUES                       # "Quartzline is ...", never "Quartzline backend" or "Quartzline runs"
    if nxt in ("'", "’"):
        return False                                           # "Quartzline's backend": a part
    following = next((f for t, f in rest if re.match(r"\w", t)), "")
    return following not in NOT_AFTER


def _spans(sentence: str, a_names: list[str], b_names: list[str]):
    """``(toks, word_at, a spans, b spans)`` of one sentence: whole-word occurrences of each side's names as ranges of word
    indices, one inside a longer span of the other side (or the same words) dropped."""
    toks = [(t, text_fold.fold(t)) for t in _tokens(sentence)]
    word_at = [i for i, (t, _f) in enumerate(toks) if re.match(r"\w", t)]
    folded = [toks[i][1] for i in word_at]
    occ: dict[str, set[tuple[int, int]]] = {"a": set(), "b": set()}
    for side, names in (("a", a_names), ("b", b_names)):
        for name in names:
            occ[side].update(_occurrences(folded, qr._key(name).split()))
    every, same = occ["a"] | occ["b"], occ["a"] & occ["b"]
    kept = {side: sorted(s for s in occ[side] if s not in same and not any(o != s and o[0] <= s[0] and s[1] <= o[1] for o in every))
            for side in occ}
    return toks, word_at, kept["a"], kept["b"]


def _presented_as_one(sentence: str, a_names: list[str], b_names: list[str]) -> bool:
    """Could this ONE sentence be presenting the two names as one thing? Only when some occurrence of each stands next to the
    other (no word between them: "A, B", "A (B)", "A / B", "A = B") or has only a marker of equivalence between (:data:`MARKERS`:
    "I mean", "or", "aka", "i.e.", "that is", "also called", "known as", "short for", "o sea", "es decir"...; an article before the
    second name is no word; a bare "is", "is a", "is the" only when the sentence ends with the second name). Anything else between them, a
    preposition, a verb, a possessive, another noun ("<A> for <B>", "<A> in <B>", "<B>'s <A>", "<A> is part of <B>"), relates them
    as two and holds nothing back. Reads the words and nothing else; a doubt here only withholds a close, which is always allowed."""
    toks, word_at, a_spans, b_spans = _spans(sentence, a_names, b_names)
    for a in a_spans:
        for b in b_spans:
            if a[0] < b[1] and b[0] < a[1]:
                continue
            first, second = (a, b) if a[1] <= b[0] else (b, a)
            between = toks[word_at[first[1] - 1] + 1:word_at[second[0]]]
            words = [f for t, f in between if re.match(r"\w", t)]
            punct = [t for t, _f in between if not re.match(r"\w", t)]
            if not words:
                return True
            said = tuple(words[:-1] if words[-1] in _ARTICLES else words)
            if tuple(words) in MARKERS or said in MARKERS or (said == () and "(" in punct):
                return True
            if said in BARE:
                tail = toks[word_at[second[1] - 1] + 1:]
                if not [f for t, f in tail if re.match(r"\w", t)] and all(t in _CLOSERS for t, _f in tail):
                    return True
    return False


def cut_ranges(text: str, a_names: list[str], b_names: list[str], cap: int | None = None) -> list[tuple[int, int]] | None:
    """What of a long turn the reader is shown (the held-name path only): every sentence that holds either name with the
    sentence before and the one after, in order, as character ranges of ``text`` (neighbours that touch are one piece; a
    cut between pieces, or at either end, is marked on display). ``None`` when no sentence holds a name or the shown part, marks
    included, is still over the cap: the question is then left with the same reason as a turn that cannot be shown. The turn
    itself stays whole for every check the code makes; a line the reader was not shown is never the located one."""
    cap = qr.TURN_CHARS if cap is None else cap
    rs, pos = [], 0
    for m in _SENTENCE.finditer(text):
        rs.append((pos, m.start()))
        pos = m.end()
    rs.append((pos, len(text)))
    rs = [(s, e) for s, e in rs if text[s:e].strip()]
    keep: set[int] = set()
    for i, (s, e) in enumerate(rs):
        if any(qr._hits(a_names, b_names, text[s:e])):
            keep.update((i - 1, i, i + 1))
    idx = sorted(k for k in keep if 0 <= k < len(rs))
    if not idx:
        return None
    pieces: list[tuple[int, int]] = []
    for n, k in enumerate(idx):
        s, e = rs[k]
        if n and k == idx[n - 1] + 1:
            pieces[-1] = (pieces[-1][0], e)
        else:
            pieces.append((s, e))
    marks = len(pieces) - 1 + (pieces[0][0] > 0 and text[:pieces[0][0]].strip() != "") + (pieces[-1][1] < len(text.rstrip()))
    if sum(e - s for s, e in pieces) + marks * (len(qr.CUT_MARK) + 2) > cap:
        return None
    return pieces


def pair_sentences(text: str, a_names: list[str], b_names: list[str]) -> list[str]:
    """The sentences of ``text`` that hold both names (`question_revisit._names_both`: the longer spelling first)."""
    return [s for s in sentences(text) if qr._names_both(a_names, b_names, s)]


def linked(text: str, a_names: list[str], b_names: list[str]) -> bool:
    """Does the text say the two are one thing: at least one sentence holds both names and EVERY sentence that holds both is
    the person's own statement of identity (`_linked_sentence`)? Reads the words and nothing else."""
    held = pair_sentences(text, a_names, b_names)
    return bool(held) and all(_linked_sentence(s, a_names, b_names) for s in held)


def _stem(word: str) -> str:
    """A plural is its singular ("backends" is "backend"); a hyphen is already a word break in `_key`."""
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _word_keys(name: str) -> list[str]:
    return [_stem(w) for w in qr._key(name).split()]


def shape(a_names: list[str], b_names: list[str]) -> str:
    """The relation of the names themselves: ``nested`` (one's words are a run inside the other's: the part shape),
    ``shares`` (a word in common that is not a function word, of any length and a number too: "<Brand> 11" and "<Brand> 12"
    are siblings: the sibling shape), else ``apart``. Plurals are the singular. Reads the words and nothing else."""
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
            if any(w not in _FUNCTION for w in set(wa) & set(wb)):
                shared = True
    return "shares" if shared else "apart"


def _own_turns(case: "NameCase"):
    return [t for t in case.turns if t.role in qr._OWN_WORDS]


def _names_together(case: "NameCase") -> bool:
    """Does a sentence of a turn of the person's own or a named speaker's, shown for this name, hold both names in a way that
    could present them as one thing (`_presented_as_one`)? Then the person may have related them, and a model's "different" is
    not Sleep's to close. A sentence that names both with anything else between them (a part, a place, a possessive) says they are
    two and holds nothing back. Reads every sentence of the whole turn, shown or not."""
    names = [*case.b.names, *case.page_names]
    return any(_presented_as_one(s, case.a.names, names)
               for t in _own_turns(case) for s in pair_sentences(t.text, case.a.names, names))


def _all_linked(case: "NameCase") -> bool:
    """Is every sentence of the person's own turns that holds both names their statement of identity? One that is not (a
    part, a list, a denial, a doubt) leaves the pair a question: a person who says both things has not settled it."""
    return all(_linked_sentence(s, case.a.names, case.b.names)
               for t in _own_turns(case) for s in pair_sentences(t.text, case.a.names, case.b.names))


def _quote_says_one(case: "NameCase", quote: str) -> bool:
    """The located words are in a turn of the person's own, and every sentence of that turn holding both names is a statement
    of identity (`linked`), and so is every such sentence of the person's other turns."""
    from api.services import evidence

    turn = next((t for t in _own_turns(case)
                 if (hit := evidence.locate(t.text, quote)) is not None and t.shows(*hit)), None)
    return turn is not None and linked(turn.text, case.a.names, case.b.names) and _all_linked(case)


def _relates(memory_path: Path, line, tfm: dict, target_id: str, name: str, target_names: list[str]) -> bool:
    """Does the record already relate the name and the page as two things: a held claim of the name whose object is the page, a
    claim of the page whose object is the name, in any predicate (`part-of`, `uses`, `is-a`...) and open or closed (a relation
    that ended still showed them as two), or a held link that names the page? Never an identity (the record has no such
    predicate)."""
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
                if getattr(c, "object_kind", "node") == "node" and qr._key(c.object) == key:
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
    #: The page it asked about has faded (archived) and the name was said after the page's last mention: it is read, but a
    #: "same" is never landed (the person's own "yes" would leave the lines on a page nobody sees).
    faded: bool = False
    #: Every name the page answers to, shared ones too: a turn that says the asked name and ANY of them related them (the close check).
    page_names: list = field(default_factory=list)


def _held_texts(line) -> list[str]:
    from api.services import typo_join

    return typo_join._held_texts(line) if line is not None else []


#: Words that make the next word a common noun ("the scheduler", "my backend", "el servicio"): a one-word alias used so in the
#: conversation is a description there, no name. A handful of function words, never a list of nouns.
_DETERMINERS = frozenset("""the a an my our your this that these those its their el la los las un una mi mis nuestro nuestra su
este esta ese esa le les der die das""".split())


def _names_of_page(memory_path: Path, target_id: str, tfm: dict) -> list[str]:
    """The names the page answers to FOR THIS PURPOSE: every one of its names that no other live page also answers to. A name
    two pages answer to (a generic alias both carry) says nothing about which one it means (`answered_questions`)."""
    from api.services import answered_questions

    return [n for n in full_name_join._names_of(tfm)
            if answered_questions._pages_answering(memory_path, answered_questions._key(n)) in ([target_id], [])]


def _common_nouns(tfm: dict, names: list[str], turns: list) -> set[str]:
    """The one-word aliases of the page (never its title) that a turn shown uses straight after a determiner: in this
    conversation the word is a common noun, so a line saying it says nothing about the page. Said by how it is used, with no
    word list."""
    title = qr._key(str(tfm.get("name") or ""))
    out: set[str] = set()
    for name in names:
        key = qr._key(name)
        if len(key.split()) != 1 or key == title:
            continue
        for t in turns:
            words = [text_fold.fold(w) for w in re.findall(r"[^\W_]+", t.text)]
            if any(w == key and i and words[i - 1] in _DETERMINERS for i, w in enumerate(words)):
                out.add(name)
                break
    return out


def said_after(memory_path: Path, fm: dict, line, tfm: dict) -> bool | None:
    """Was the asked name said in any conversation dated AFTER the page's last mention? The held line's conversations and the
    question's own, each by its own date (`pair_evidence.episode_timestamp`: the item's date, never when Cicada received it),
    against the page's `last_referenced`. ``None`` when either cannot be dated: it is then neither retired nor read."""
    last = str(tfm.get("last_referenced") or "")[:10]
    episodes = [e for e in dict.fromkeys([*(line.episodes() if line is not None else []), str(fm.get("source_episode") or "")])
                if e.startswith("ep_")]
    days = [qr._episode_day(memory_path, e) for e in episodes]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", last) or not days or not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in days):
        return None
    return any(d > last for d in days)


def _held_episodes(line) -> list[str]:
    """Every conversation a held line cites: where it heard the name (`episodes`) and where its held claims' evidence is."""
    out = list(line.episodes()) if line is not None else []
    for claim in (line.held_claims if line is not None else []):
        if not isinstance(claim, dict):
            continue
        cited = [*[str(e) for e in (claim.get("source_episodes") or [])],
                 *[str(ev.get("episode") or "") for ev in (claim.get("evidence") or []) if isinstance(ev, dict)]]
        out.extend(e for e in cited if e.startswith("ep_") and e not in out)
    return out


def unsaid(memory_path: Path, names: list[str], episodes: list[str]) -> str:
    """Was the name SAID in any of these conversations? ``""``: it was (or there is nothing to check: no conversation named), so
    the question is not this rule's. ``"name_not_said"``: every conversation was read and none holds it, in any turn, whoever's,
    nor in its frontmatter. ``"conversation_missing"``: it is in none that could be read and one could not be (missing, locked, not
    a conversation): the question is left. Located as the evidence spans are (`evidence.locate`: exact, whitespace, case-insensitive;
    never fuzzy); the folded-words check only ever says MORE was said (a hyphen, an accent). Reads only."""
    from api.services import evidence

    names = [n for n in dict.fromkeys(" ".join(str(n or "").split()) for n in names) if n]
    episodes = [e for e in dict.fromkeys(str(e or "").strip() for e in episodes) if e]
    if not names or not episodes:
        return ""
    missing = False
    for ep in episodes:
        doc = evidence.source_document(Path(memory_path), ep) if ep.startswith("ep_") else None
        if doc is None:
            missing = True
            continue
        fm, body = doc
        for text in (body, json.dumps(fm, default=str, ensure_ascii=False)):
            if any(evidence.locate(text, n) is not None or qr._hits([n], [], text)[0] for n in names):
                return ""
    return "conversation_missing" if missing else RULE_UNSAID


def _unsaid_names(fm: dict, line, name: str) -> list[str]:
    return [name, str(fm.get("entity_mention") or ""), str(fm.get("entity_name") or ""),
            *[str(a) for a in (line.aliases if line is not None else [])]]


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
    if not name:
        return None, "no_name"
    if target is None:
        return None, "target_missing"
    target_id, tfm = target[0].stem, dict(target[1])
    if inbox_tend._is_owner_page(tfm):
        return None, "owner_page"
    if str(tfm.get("status") or "").lower() == "dropped":
        return None, "target_dropped"
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
    faded = str(tfm.get("status") or "").lower() == "archived"
    if faded:
        said = said_after(memory_path, fm, line, tfm)
        if said is None:
            return None, "target_faded_undated"
        if not said:
            return None, "target_faded"
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
    if not person:
        # A label nobody said (:func:`unsaid`): no line can ever be located for it, so no read could close it.
        said = unsaid(memory_path, _unsaid_names(fm, line, name),
                      [str(fm.get("source_episode") or ""), *_held_episodes(line)])
        if said:
            return None, said
    target_names = _names_of_page(memory_path, target_id, tfm)
    if not target_names:
        return None, "page_name_shared"
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
    b.all_names = [n for n in b.all_names if n in target_names] if not person else b.all_names
    episodes, why = qr._conversations(memory_path, fm, a, b)
    if why:
        return None, why
    turns, why = qr._turns_for(memory_path, episodes, a, b, cut=cut_ranges)
    if why:
        return None, why
    generic = _common_nouns(tfm, b_names, turns)
    if generic:
        # A one-word alias of the page that the conversation itself uses as a common noun ("the scheduler") is no name of it.
        b_names = [n for n in b_names if n not in generic]
        if not b_names:
            return None, "page_name_shared"
        b = qr._side(memory_path, target_id, tfm, b_names)
        b.all_names = [n for n in b.all_names if n not in generic]
        turns, why = qr._turns_for(memory_path, episodes, a, b, cut=cut_ranges)
        if why:
            return None, why
    every = full_name_join._names_of(tfm)
    if not person and set(every) != set(b_names):
        # What the person said with a name the page shares or a common noun is still the person relating the name to the page:
        # those turns are shown and they stop a close (never a join: they hold no name of the page for this purpose).
        extra, why = qr._turns_for(memory_path, episodes, a, qr._side(memory_path, target_id, tfm, every), cut=cut_ranges)
        if why:
            return None, why
        known = {(t.episode, t.text) for t in turns}
        turns = [*turns, *[t for t in extra if t.both and (t.episode, t.text) not in known]]
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
                    shape="person" if person else shape(a_names, b_names), target_type=target_type, faded=faded,
                    page_names=full_name_join._names_of(tfm),
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
- "different": it is something else: a PART, feature or component of the page's thing; a version of it; a SIBLING (another thing of the same family, maker or kind); or unrelated though it shares a word. Give "relation": "part", "sibling", "unrelated" or "other", and "line": one line copied word for word from one of that NAME's own turns (a turn of the person's own or a named speaker's, never the memory text or an assistant's turn), saying the NAME and what it is.
- "cannot_tell": anything else.
Rules:
- A wrong "same" puts one thing's facts on another thing's page; a question left costs little. Sharing a word, a family, a maker or a project is NOT being the same thing. A part of a page's thing is not the thing. When in doubt: "cannot_tell".
- Both names in one turn is not one thing: the words must say they are one thing. A turn that lists them, compares them, or says one belongs to, uses, replaces or runs on the other says they are TWO.
- Only the person's own turns and a named speaker's turns can say it: what an assistant said, a note an agent saved and text relayed from an app are never the words that present two names as one thing.
- A "[…]" in a long turn marks where part of it was left out: never copy across one, and a line must be copied from the shown words.
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
            return "\n".join(f"[{t.n}] ({t.day or 'undated'}, {t.role}) {t.display()}" for t in group) or "(none)"

        blocks.append(f"NAME {k}: \"{case.a.name.replace(chr(34), '')}\"\nWhat the memory holds about it:\n{qr._lines(case.a.texts)}\n"
                      f"Its turns naming it AND the page:\n{shown(both)}\nIts turns naming only it:\n{shown(one)}")
    prompt = PROMPT.format(
        page=head.name.replace('"', ""), page_names=", ".join(f"“{n}”" for n in head.all_names if qr._key(n) != qr._key(head.name))
        or "no other name", record=qr._lines(head.texts), speaker=SPEAKER.format(speaker=named) if named else "",
        blocks="\n\n".join(blocks))
    return {"same": SCEPTIC_SAME, "different": SCEPTIC_DIFF}.get(mode, "") + prompt


def _locate_line(memory_path: Path, case: NameCase, line: str) -> dict | None:
    """The copied line of a "different", located (exact, whitespace, case: never fuzzy) in ONE turn of the person's own or of a
    named speaker's that says the name: ``{"episode", "start", "end", "kind"}``, else ``None``. A line found only in the held
    line's own text, the page's text or an assistant's turn is no evidence: Sleep wrote the first two and an agent repeats them,
    so a model could close a question by quoting what Sleep already said."""
    text = " ".join(str(line or "").split())
    if (len(re.sub(r"\W+", "", text)) < qr.MIN_QUOTE_CHARS or "…" in text or "..." in text
            or not pair_evidence.names_in([qr._key(case.a.name)], text)):
        return None
    found = qr._quote_span(memory_path, case, text)
    return found[2] if found is not None else None


def _same_result(memory_path: Path, case: NameCase, item: dict, speaker: str | None, model: str) -> Result:
    parsed = {**item, "verdict": "one"}
    parsed.pop("_model", None)
    read = qr.located(memory_path, case, parsed, speaker)
    read.model = model
    if "said" in read.kinds and not _quote_says_one(case, read.quote):
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
        return Result("cannot_tell", model=model, reason="the line said is not in the person's own words")
    return Result("different", relation=relation, line=str(item.get("line") or ""), span=span,
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
    if result.verdict != "same" or case.related or case.faded or "said" not in kinds or not _all_linked(case):
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
                 json.dumps([(t.episode, t.text) for t in case.turns]), json.dumps([case.a.names, case.b.names]), case.a.id, case.b.id,
                 case.shape, str(case.faded)):
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
    same = [i for i, r in enumerate(first) if r.verdict == "same" and enough_same(cases[i], r)]   # never one onto a faded page
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
        if r2.verdict != "different" or _names_together(case):
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


def coined_label(clarifier, entity: dict, candidate: dict) -> bool:
    """At Stage 2's raise site (`entity_resolver._create_duplicate_clarification`): is the mention's name a label nobody said, so the
    "same as?" question about it would be one no read could ever close? True only when :func:`unsaid` says so on the conversation
    the mention came from and the ones its held line already cites; never for a person (the mention or the page); a conversation
    that cannot be read, or none named, is False (the question is raised as before). The held line is written either way."""
    memory_path = getattr(clarifier, "memory_path", None)
    if not isinstance(memory_path, Path) or not isinstance(entity, dict):
        return False
    try:
        from api.services import entity_resolver, pending_store

        name = " ".join(str(entity.get("name") or "").split())
        if (not name or str(entity.get("type") or "").lower() == "person"
                or entity_resolver._candidate_type(candidate) == "person"):
            return False
        line = pending_store.held_line(memory_path, name)
        return unsaid(memory_path, [name, *[str(a) for a in (line.aliases if line is not None else [])]],
                      [str(entity.get("source_episode") or ""), *_held_episodes(line)]) == RULE_UNSAID
    except Exception as exc:  # noqa: BLE001 - a guard that cannot decide never stops a question being raised
        logger.debug(f"coined_label undecided: {type(exc).__name__}")
        return False


def retire_decision(memory_path: Path, path: Path, fm: dict, rule: str) -> inbox_tend.Decision:
    """The engine-free retirement of a question with nothing to read (:data:`RULE_FADED`, :data:`RULE_UNSAID`): nothing is written to
    any page, the held lines stay held under their own name (ruling 73: no value is lost), the question leaves the inbox through the
    tending's own path and its undo puts it back."""
    from api.services import pending_store

    memory_path = Path(memory_path)
    target_id = str(fm.get("merge_target_hint") or "").strip()
    guard = inbox_tend._guard(memory_path, target_id)
    store = pending_store.store_path(memory_path)
    guard[store.relative_to(memory_path).as_posix()] = inbox_tend._hash(store)
    reason = ("The page it asked about has faded out of memory, and nothing was said about the name after the page's last "
              "mention; the lines held about the name are still held under its own name." if rule == RULE_FADED else
              "The name is a label Cicada made up for something, not words anyone said in the conversations it came from; "
              "nothing was changed and the lines held about it are still held under its own name.")
    return inbox_tend.Decision(path.stem, "merge_suggestion", rule, None, answer="Retired", fingerprint=path.read_bytes(),
                               guard=guard, reason=reason)


def faded_decision(memory_path: Path, path: Path, fm: dict) -> inbox_tend.Decision:
    """The retirement of a question whose page has faded (archived) and about whose name nothing was said after the page's last
    mention (`name_case` answered ``target_faded``). Engine-free: no read is made (`retire_decision`)."""
    return retire_decision(memory_path, path, fm, RULE_FADED)


def unsaid_decision(memory_path: Path, path: Path, fm: dict) -> inbox_tend.Decision:
    """The retirement of a question about a label nobody said (`name_case` answered ``name_not_said``). Engine-free."""
    return retire_decision(memory_path, path, fm, RULE_UNSAID)


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
    case, why = name_case(memory_path, path, fm)
    if d.rule in (RULE_FADED, RULE_UNSAID):
        return case is None and why == ("target_faded" if d.rule == RULE_FADED else "name_not_said")
    if case is None or case.b.id != str((d.request or {}).get("merge_target") or ""):
        return False
    if d.rule == RULE_SAME:
        return not case.related and not case.faded and case.shape != "nested" and _all_linked(case)
    return not _names_together(case)


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


async def _retire(ctx: Context, path: Path, fm: dict, rule: str) -> None:
    """The engine-free retirement of a question with nothing to read (`retire_decision`): counted, listed, undoable."""
    report = ctx.report
    decision = await asyncio.to_thread(retire_decision, ctx.memory_path, path, fm, rule)
    if ctx.dry_run:
        report.settled += 1
        ctx.note(path.stem, KIND, "would_retire", rule)
        return
    try:
        ok = await inbox_tend.apply(ctx.memory_path, ctx.settings, decision)
    except Exception as exc:  # noqa: BLE001 - one that will not settle never stops the others
        logger.info(f"Name revisit not applied: {type(exc).__name__}")
        ok = False
    if ok:
        report.settled += 1
        report.paths.append(f"inbox/settled/{path.stem}.md")
        ctx.note(path.stem, KIND, "retired", rule)
    else:
        ctx.note(path.stem, KIND, "left:not_applied")


async def look(ctx: Context, path: Path, fm: dict, rest: list[tuple[Path, dict]], done: set[str]) -> None:
    """One open question about a name with no page, and the others about the same page that are due, together."""
    memory_path, report = ctx.memory_path, ctx.report
    item_id = path.stem
    case, why = await asyncio.to_thread(name_case, memory_path, path, fm, today=ctx.today.isoformat())
    if case is None and why in ("target_faded", RULE_UNSAID):
        await _retire(ctx, path, fm, RULE_FADED if why == "target_faded" else RULE_UNSAID)
        return
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
