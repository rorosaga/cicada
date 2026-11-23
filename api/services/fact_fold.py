"""A fact a page already states in full is not added again (G148 / G194, owner report 2026-11-23).

Stage 1 reads each conversation alone, so one fact arrives worded a new way every time: "Favourite artist of X", "X's
favourite artist is Y", "Is X's favorite artist, noted in the gift guide". The page-merge call was cut to the Summary and
the new History lines (2026-10-24) and every other section is carried by code, which drops a fact only when it EQUALS one
already there after trivial normalisation (`fact_policy.restates`) or says it word for word and then more
(`fact_policy.extends`). So each conversation's wording was appended for good: one artist's page held 16 bullets stating 3
facts, and 3,073 Key Facts on 708 pages of the owner's bank restate an earlier bullet.

Ruling 23 (binding) forbids a word rule that guesses: rule-based folds lost information. What it left open
(`fact_policy`: "revisit the fold only with a measured loss-free paraphrase rule") is closed here the way a value said
again is (`value_alignment`, #783): Sleep's small judge reads the page's facts, in any language, and a code check it
cannot talk past decides whether what it proposed may happen.

1. **Ask** (`prompt`, `proposals`): after the links are written under the page's own name (`link_names`) and before the
   page's article or summary call, a page whose update brings a fact that no existing bullet equals or extends gets ONE
   call. It lists the new facts and the existing bullets most like them (shared words, names, numbers — a bound on the
   prompt, never a decision) and asks, per line, which other line already says it in full.
2. **Guard** (`covers`): every proposal must pass code. The dropped fact's numbers and dates, its months and weekdays,
   its negation and tense words, and every name it carries (a capitalised word, a link's target) must all be there in
   the line that holds it; the page's own names, the owner's name and the other names a linked page is known by are
   allowed. **Who a line means is read in the page's own neighbourhood** (`People`): a name — linked or plain, and the
   form "<owner>'s <alias>" — that is the name or an alias of exactly ONE page this page relates to counts as that
   page, in the guard and in what the judge and the checker are told ("Pip's", "<owner>'s girlfriend's" and
   `[[Girlfriend]]` are one person on a page that relates to her). Never bank-wide: "girlfriend" is read among the
   handful of pages this page relates to, two of them sharing an alias make it no one's, and a line that means a
   different related page, or names one the other does not, is refused. A fold also never loses a link: when the
   dropped line links a page the holder does not, the direction is flipped if the linked line can hold the other
   under the guard, and otherwise there is no fold (the link draws the graph edge and the page chip). A proposal the
   guard refuses is never put to the second reader.
3. **Check** (`checks`): one more call per page lists, for each surviving pair, everything the dropped fact says that
   the other does not; a fold needs the list empty and `same` true (and the guard again). A false fold is as bad as a
   miss, and a lost date or number is worse than either.

What a fold does: the incoming fact is not added (`entity['key_facts']` loses it); an existing bullet a longer, new
one says in full is replaced by it (never on a page a person edited, never a pinned correction); and
``entity[section_provenance.FOLDS]`` records ``{dropped text: the text that holds it}`` so the dropped fact's G118 source
rows move onto the holder — the page still shows every conversation that said it. Nothing else changes; the judge never
edits a line.

**Calls:** none for a page that gains no fact no bullet equals or extends. Otherwise one ask and at most one check per
page, at most `MAX_ASKS` pages a batch (the pages gaining most first), `MAX_NEW` new facts and `MAX_LINES` lines each,
`MAX_PAIRS` pairs checked. Past a cap, or on any failed or unreadable call, the page keeps what Stage 3 and the writer
did before this step. Small tier on the engine the cycle resolved, the same bill as Stage 2's judge (`judge_for`);
refused past a metered key's spending line (`sleep_spend.LINE_STAGES`). Never on the capture path. History lines and Open
Questions are not read by this step (see `docs/architecture/capture-and-sleep.md`).

Pure apart from the injected judge.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

from loguru import logger

from api.services import fact_policy, link_names
from api.services.text_fold import fold

STAGE = "fact_fold"
#: Pages asked per batch; new facts and lines per page; pairs checked per page. A page past a cap keeps what the writer
#: did before this step.
MAX_ASKS = 24
MAX_NEW = 12
MAX_LINES = 40
MAX_PAIRS = 24
MAX_LINE_CHARS = 400
#: Existing bullets shown per new fact (the best-overlapping), and the newest bullets shown for a fact nothing overlaps.
PER_NEW = 8
NEWEST = 6

PROMPT = """One person's memory page for ONE thing lists facts, one line each, in any language. Lines marked NEW were just \
read; the others are already on the page. Conversations word the same fact many ways.

For each line, name the OTHER line, if any, that already says it IN FULL: every date, number, name, amount, qualifier, \
reason and relation the line carries is in the other line too, so that deleting the line loses nothing. The other line \
may say more; it may not say less, nor something different. Reworded, shortened or translated counts. These are NOT the \
same: a different relation (a favourite artist is not a favourite album), a different or an added number or date, a \
negation, a plan against something done, a different person or thing, a reason or place only one of them gives. When \
unsure, answer null. Answer for every line marked NEW first (null when no other line says it in full); an older \
line may also name a NEW line that says it in full. A second reader checks every answer.

THING: {name}
{names}LINES:
{lines}

Reply with JSON only, one answer per line you can name: {{"answers": [{{"line": <line number>, "in_full_by": <the other \
line's number>}}]}}"""

CHECK = """A page about ONE thing ({thing}) may delete a line (DROP) only if another line (KEEP) already says everything \
it says. Every line is about {thing}: a line that names it and a line that leaves its name out say the same.

For each pair, list what DROP says that KEEP does not: each date, number, name, amount, qualifier, reason, relation, \
tense or negation. Write [] when there is nothing. {names}
{pairs}

Reply with JSON only: {{"pairs": [{{"pair": <pair number>, "missing": [<each thing, short>], "same": true or false}}]}}"""


@dataclass
class Line:
    n: int
    text: str
    new: bool
    held: bool = False    # an existing bullet that is pinned: it may hold a fold, never fold into one


@dataclass
class Ask:
    page_id: str
    name: str
    lines: list[Line]
    names: dict[str, list[str]] = field(default_factory=dict)   # a linked page's name -> the other names it goes by
    own: frozenset[str] = frozenset()                            # words the page's and the owner's names allow
    heal: bool = True                                            # an existing bullet may fold (a machine page)
    people: "People | None" = None                               # the pages this page relates to, by every name
    paths: dict[str, str] = field(default_factory=dict)          # dropped text -> which guard path allowed it


# --------------------------------------------------------------------------- the guard

_MONTHS = """
january enero janvier januar janeiro gennaio
february febrero fevrier februar fevereiro febbraio
march marzo mars marz marco
april abril avril aprile
may mayo mai maggio maio
june junio juin juni junho giugno
july julio juillet juli julho luglio
august agosto aout agost
september septiembre septembre septiembre setembro settembre
october octubre octobre oktober outubro ottobre
november noviembre novembre novembro
december diciembre decembre dezember dezembro dicembre
"""
_WEEKDAYS = """
monday lunes lundi montag segunda lunedi
tuesday martes mardi dienstag terca martedi
wednesday miercoles mercredi mittwoch quarta mercoledi
thursday jueves jeudi donnerstag quinta giovedi
friday viernes vendredi freitag sexta venerdi
saturday sabado samedi samstag sabato
sunday domingo dimanche sonntag domenica
"""


def _table(raw: str, kind: str) -> dict[str, str]:
    return {word: f"{kind}{i}" for i, row in enumerate(raw.strip().splitlines()) for word in row.split()}


_CALENDAR = {**_table(_MONTHS, "m"), **_table(_WEEKDAYS, "d")}
_TOKEN = re.compile(r"[^\W_][\w'’.@+-]*", re.UNICODE)
_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _plain(text: str) -> str:
    return _LINK.sub(lambda m: m.group(2) or m.group(1), str(text or ""))


_POSSESSIVE = frozenset("his her my our their the a an".split())


def _key(text: str) -> str:
    return " ".join(fold(str(text or "").replace("\u2019", "'")).split())


class People:
    """Who a page's lines mean, read among the pages THIS page relates to (never bank-wide).

    ``pages`` is ``{page id: (name, [aliases])}`` for those pages (the owner's and the written page's own excluded: their
    names are always allowed words). A spelling — a page's name, an alias, "<owner>'s <alias>" — that exactly one of them
    answers to is that page; one two of them answer to is no one's. ``canon`` rewrites every such mention in a line, linked
    or plain, to the page's name and says which pages it found; the guard compares lines in that form."""

    def __init__(self, pages: dict[str, tuple[str, list[str]]], owner: str | None = None) -> None:
        self.names = {pid: name for pid, (name, _) in pages.items()}
        self.aliases = {pid: [a for a in aliases if _key(a) != _key(name)] for pid, (name, aliases) in pages.items()}
        possessors = []
        if owner and owner.strip():
            possessors = [owner.strip(), owner.strip().split()[0]]
        holders: dict[str, set[str]] = {}
        self.spellings: dict[str, list[str]] = {}
        for pid, (name, aliases) in pages.items():
            forms = [name, pid.replace("-", " "), *self.aliases[pid]]
            # "<owner>'s girlfriend": an alias takes the owner's possessive, unless it already is one ("his girlfriend")
            forms += [f"{who}'s {alias}" for who in dict.fromkeys(possessors) for alias in self.aliases[pid]
                      if alias.split()[0].lower() not in _POSSESSIVE
                      and _key(who) not in _key(alias)]
            self.spellings[pid] = list(dict.fromkeys(f for f in forms if len(_key(f)) > 1))
            for form in self.spellings[pid]:
                holders.setdefault(_key(form), set()).add(pid)
        self._by_key = {k: next(iter(v)) for k, v in holders.items() if len(v) == 1}
        forms = sorted({f for pid in pages for f in self.spellings[pid] if _key(f) in self._by_key}, key=len, reverse=True)
        self._pattern = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(f.replace("\u2019", "'")) for f in forms) + r")(?![\w])",
                                   re.IGNORECASE) if forms else None

    def __bool__(self) -> bool:
        return bool(self._by_key)

    def id_of(self, spelling: str) -> str | None:
        return self._by_key.get(_key(spelling))

    def canon(self, text: str) -> tuple[str, frozenset[str]]:
        """``text`` with each mention of a neighbour written as its page's name, and the pages found."""
        found: set[str] = set()
        text = str(text or "")

        def link(m: re.Match) -> str:
            pid = self.id_of(m.group(1))
            if pid is None:
                return m.group(0)
            found.add(pid)
            return self.names[pid]

        text = _LINK.sub(link, text)
        if self._pattern is not None:
            def plain(m: re.Match) -> str:
                pid = self._by_key.get(_key(m.group(0)))
                if pid is None:
                    return m.group(0)
                found.add(pid)
                return self.names[pid]

            text = self._pattern.sub(plain, text.replace("\u2019", "'"))
        return text, frozenset(found)

    def mentioned(self, texts) -> list[str]:
        return sorted({pid for t in texts for pid in self.canon(t)[1]})

    def link_ids(self, text: str) -> frozenset[str]:
        """What a line's explicit links point at: a neighbour's id (whatever name the link uses), else the link's own key."""
        return frozenset(self.id_of(m.group(1)) or _key(m.group(1)) for m in _LINK.finditer(str(text or "")))


def ask_from_pair(pair: dict) -> Ask:
    """A fixture pair as a two-line ask (``keep`` the page's bullet, ``drop`` the new fact), for the tests and the dry run.
    ``related`` (name -> aliases) and ``owner`` declare the page's neighbourhood (`People`), ``names`` / ``own`` the
    linked pages' other names and the allowed words."""
    lines = [Line(1, pair["keep"], False), Line(2, pair["drop"], True)]
    related = pair.get("related") or {}
    pages = {re.sub(r"\W+", "-", name.lower()).strip("-"): (name, list(aliases)) for name, aliases in related.items()}
    people = People(pages, pair.get("owner")) if pages else None
    people = people if people else None
    also = dict(pair.get("names") or {})
    if people is not None:
        for pid in people.mentioned(line.text for line in lines):
            also[people.names[pid]] = [f for f in people.spellings[pid] if _key(f) != _key(people.names[pid])][:10]
    return Ask("page-example", "Page Example", lines, also, _held_words(pair.get("own") or []), True, people)


def _link_ids(text: str, people: "People | None") -> frozenset[str]:
    if people is not None:
        return people.link_ids(text)
    return frozenset(_key(m.group(1)) for m in _LINK.finditer(str(text or "")))


def _stem(word: str) -> str:
    return fact_policy._stem(fold(word).strip(".,;:!?'\"()[]")).strip(".'’")


def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in (_stem(t) for t in _TOKEN.findall(_plain(text))) if w)


def _calendar(text: str) -> frozenset[str]:
    return frozenset(_CALENDAR[w] for w in (fold(t).strip(".,;:!?'\"()[]") for t in _TOKEN.findall(_plain(text)))
                     if w in _CALENDAR)


@lru_cache(maxsize=65536)
def anchors(text: str) -> frozenset[str]:
    """The named things a fact carries: each capitalised word after the first (a month and a weekday aside, one letter
    aside) and every word of a link's target, stemmed and folded."""
    found: set[str] = set()
    for m in _LINK.finditer(str(text or "")):
        found |= {_stem(t) for t in _TOKEN.findall(m.group(1))}
    for i, token in enumerate(_TOKEN.findall(_plain(text))):
        if i and token[:1].isupper() and len(token) > 1 and fold(token) not in _CALENDAR:
            found.add(_stem(token))
    return frozenset(w for w in found if w)


#: Present-tense copulas and auxiliaries add no tense a bare noun phrase lacks ("Is X's favourite artist" says what
#: "Favourite artist of X" does); every other status word (was, planned, until, no longer, will ...) must be in both.
_NEUTRAL = frozenset("is are am has have do does".split())


def _compatible(drop: str, keep: str) -> bool:
    """``drop`` adds no number, no negation and no tense or status word that ``keep`` lacks (`fact_policy._profile`)."""
    d_words, d_numbers, d_negated = fact_policy._profile(drop)
    k_words, k_numbers, k_negated = fact_policy._profile(keep)
    return (d_negated == k_negated and d_numbers <= k_numbers
            and ((d_words & fact_policy._STATUS) - _NEUTRAL) <= (k_words & fact_policy._STATUS))


def covers(keep: str, drop: str, *, allowed=frozenset(), people: "People | None" = None) -> bool:
    """True when nothing in ``drop`` that a number, a date, a negation, a tense word or a name can carry is missing from
    ``keep`` — the floor under the judge's word that ``keep`` says all of ``drop``. ``allowed``: words that may be
    absent (the page's own names, the owner's, the other names of a page ``keep`` links). Never true on a guess: a miss
    here keeps a fact, and the model's opinion cannot override it.

    ``people`` (`People`): the pages this page relates to. Every mention of one, linked or plain, is first read as that
    page's name, and a neighbour the drop means must be one the keep means too.

    Last, the keeper must use most of the dropped line's own words (``MIN_SHARED``): the reader's word that two lines
    say the same is not taken when they share only their names and numbers. A translated repeat is therefore kept.

    Language-bound where a word list is: negation and tense words are English and Spanish (`fact_policy`), months and
    weekdays six languages; the digits and the names hold in every language."""
    if people:
        keep, kept = people.canon(keep)
        drop, dropped = people.canon(drop)
        if not dropped <= kept:
            return False
    if not _compatible(drop, keep):
        return False
    if not _calendar(drop) <= _calendar(keep):
        return False
    if not anchors(drop) <= (_words(keep) | frozenset(allowed)):
        return False
    return _shared(drop, keep, frozenset(allowed)) >= MIN_SHARED


#: The least share of a dropped line's own words its keeper must also use. Read on real pages (2026-11-24): the folds
#: that lost something shared 0.38 and 0.50 (a line saying ALL of a set was of one kind, folded into a count of that
#: kind; a run's name dropped), every sound one 0.67 or more. A reworded line shares most of its words; a line that
#: shares few is another fact about the same names and numbers, or a translation, and both are kept.
MIN_SHARED = 0.6
MIN_WORDS = 4


def _shared(drop: str, keep: str, allowed: frozenset[str]) -> float:
    """The share of ``drop``'s content words (`fact_policy._profile`) that ``keep`` uses too, the allowed names aside."""
    mine = {w for w in fact_policy._profile(drop)[0] if len(w) > 2} - allowed
    if len(mine) < MIN_WORDS:
        return 1.0    # a line of two or three words is one synonym away from any floor; its names and numbers guard it
    theirs = fact_policy._profile(keep)[0] | _words(keep)
    return len(mine & theirs) / len(mine)


# --------------------------------------------------------------------------- what to ask


def _held_words(page_names) -> frozenset[str]:
    out: set[str] = set()
    for name in page_names:
        out |= {w for w in (_stem(t) for t in _TOKEN.findall(_plain(str(name)))) if w}
    return frozenset(out)


def _overlap(a_text: str, b_text: str) -> int:
    """How alike two lines are in the words that survive translation (names, numbers) and in the words they share."""
    return (3 * len(anchors(a_text) & anchors(b_text)) + 3 * len(_numbers(a_text) & _numbers(b_text))
            + len(fact_policy._profile(a_text)[0] & fact_policy._profile(b_text)[0]))


def _numbers(text: str) -> frozenset[str]:
    return fact_policy._profile(text)[1]


def _says_already(fact: str, existing: list[str]) -> bool:
    return any(fact_policy.restates(fact, e) or fact_policy.extends(e, fact) or fact_policy.extends(fact, e)
               for e in existing)


def neighbourhood(page_id: str, names: "link_names.Names | None", lines=(), owner: str | None = None) -> "People | None":
    """The pages ``page_id`` relates to (`link_names.Names.relations`, plus any page its own lines link under that page's
    own name), as `People`; ``None`` when there are none. The owner's page and the written page itself are left out."""
    if names is None:
        return None
    ids = set(names.relations(page_id))
    for text in lines:
        for m in _LINK.finditer(str(text or "")):
            if (own := names.own_page(m.group(1))) is not None:
                ids.add(own)
    ids.discard(page_id)
    pages = {pid: (names.names[pid], list(names.aliases.get(pid, ()))) for pid in sorted(ids)
             if pid in names.names and not (owner and _key(names.names[pid]) == _key(owner))}
    people = People(pages, owner)
    return people if people else None


def build(page_id: str, name: str, existing: list[str], incoming: list[str], *, heal: bool = True,
          pinned=frozenset(), names: "link_names.Names | None" = None, own=(), owner: str | None = None) -> Ask | None:
    """One page's question, or ``None`` when the update brings no fact that no bullet equals or extends."""
    seen: list[str] = []
    fresh: list[str] = []
    for fact in incoming:
        text = str(fact).strip()
        if text and len(text) <= MAX_LINE_CHARS and not _says_already(text, existing) and not any(fact_policy.restates(text, s) for s in seen):
            seen.append(text)
            fresh.append(text)
    if not fresh:
        return None
    fresh = fresh[:MAX_NEW]
    existing = [e if len(e.strip()) <= MAX_LINE_CHARS else "" for e in existing]   # a paragraph is never shown
    chosen: dict[int, int] = {}   # existing index -> best score
    for fact in fresh:
        scored = sorted(((_overlap(fact, e), i) for i, e in enumerate(existing) if e), reverse=True)
        top = [(s, i) for s, i in scored if s > 0][:PER_NEW]
        if not top:   # nothing shares a word, a name or a number (another language): the newest bullets
            top = [(0, i) for i in range(len(existing) - 1, -1, -1) if existing[i]][:NEWEST]
        for s, i in top:
            chosen[i] = max(s, chosen.get(i, -1))
    room = max(0, MAX_LINES - len(fresh))
    kept = sorted(sorted(chosen, key=lambda i: (-chosen[i], -i))[:room])
    lines = [Line(0, existing[i].strip(), False, held=_norm(existing[i]) in pinned) for i in kept]
    lines += [Line(0, f, True) for f in fresh]
    for n, line in enumerate(lines, 1):
        line.n = n
    also: dict[str, list[str]] = {}
    if names is not None:
        for line in lines:
            for m in _LINK.finditer(line.text):
                page = names.resolve(m.group(1))
                if page and names.names[page] not in also and names.aliases.get(page):
                    also[names.names[page]] = names.aliases[page][:6]
    people = neighbourhood(page_id, names, [line.text for line in lines], owner)
    if people is not None:
        # The judge and the checker are told which names are one person here: every neighbour a line mentions.
        for pid in people.mentioned(line.text for line in lines):
            others = [f for f in people.spellings[pid] if _key(f) != _key(people.names[pid])]
            if others:
                also[people.names[pid]] = others[:10]
    allowed = _held_words([name, *own])
    return Ask(page_id, name, lines, also, allowed, heal, people)


def _norm(text: str) -> str:
    return fact_policy.normalized(text)


def prompt(ask: Ask) -> str:
    rows = [f"{line.n}. {'NEW ' if line.new else ''}{line.text}" for line in ask.lines]
    return PROMPT.format(name=ask.name, names=_names_block(ask), lines="\n".join(rows))


def _names_block(ask: Ask) -> str:
    if not ask.names:
        return ""
    rows = [f"- {name} is also called: {', '.join(others)}" for name, others in sorted(ask.names.items())]
    return ("NAMES (a page's other names; on this page each one, linked or plain, means that same person or thing):\n"
            + "\n".join(rows) + "\n")


def _allowed(ask: Ask, keep: str) -> frozenset[str]:
    """What ``keep`` may leave unsaid: the page's and the owner's names, and the other names of every page it links."""
    out = set(ask.own)
    for m in _LINK.finditer(keep):
        for other in ask.names.get(m.group(1).strip(), ()):
            out |= {_stem(t) for t in _TOKEN.findall(other)}
    return frozenset(out)


def proposals(reply, ask: Ask) -> list[tuple[Line, Line]]:
    """The judge's answers as ``(line, the line that says it in full)``: real line numbers only, a line once, never
    itself, never a held (pinned) bullet as the dropped one, never an existing bullet on a page that may not change one;
    and only what the guard allows."""
    by_n = {line.n: line for line in ask.lines}
    raw = reply.get("answers") if isinstance(reply, dict) else None
    out: list[tuple[Line, Line]] = []
    seen: set[int] = set()
    for answer in raw if isinstance(raw, list) else []:
        if not isinstance(answer, dict):
            continue
        try:
            n, m = int(answer.get("line")), int(answer.get("in_full_by"))
        except (TypeError, ValueError):
            continue
        drop, keep = by_n.get(n), by_n.get(m)
        if drop is None or keep is None or drop is keep or n in seen:
            continue
        if not drop.new and (drop.held or not ask.heal):
            continue
        if not covers(keep.text, drop.text, allowed=_allowed(ask, keep.text), people=ask.people):
            continue
        seen.add(n)
        out.append((drop, keep))
    return out[:MAX_PAIRS]


def checks(pairs: list[tuple[Line, Line]], ask: Ask, judge: Callable[[str], dict]) -> list[tuple[Line, Line]]:
    """The pairs a second, narrower reader also lets fold: nothing missing, and the guard again."""
    if not pairs:
        return []
    rows = [f"{i}. DROP: {d.text}\n   KEEP: {k.text}" for i, (d, k) in enumerate(pairs, 1)]
    reply = judge(CHECK.format(thing=ask.name, names=_names_block(ask).replace("\n", " ").strip(),
                                pairs="\n".join(rows)))
    raw = reply.get("pairs") if isinstance(reply, dict) else None
    ok: set[int] = set()
    for answer in raw if isinstance(raw, list) else []:
        if isinstance(answer, dict) and answer.get("same") is True and answer.get("missing") == []:
            try:
                ok.add(int(answer.get("pair")))
            except (TypeError, ValueError):
                pass
    return [pair for i, pair in enumerate(pairs, 1)
            if i in ok and covers(pair[1].text, pair[0].text, allowed=_allowed(ask, pair[1].text), people=ask.people)]


def _droppable(line: Line, ask: Ask) -> bool:
    """A new fact may always go; an existing bullet only on a machine page and never a pinned one."""
    return line.new or (ask.heal and not line.held)


def _loses_no_link(drop: str, keep: str, ask: Ask) -> bool:
    """Everything ``drop`` links, ``keep`` links too (a neighbour by its page, whatever name the link uses): the link draws
    the graph edge and the page chip."""
    return _link_ids(drop, ask.people) <= _link_ids(keep, ask.people)


def _admits(keep: Line, drop: Line, ask: Ask) -> bool:
    return (covers(keep.text, drop.text, allowed=_allowed(ask, keep.text), people=ask.people)
            and _loses_no_link(drop.text, keep.text, ask))


def orient(pairs: list[tuple[Line, Line]], ask: Ask) -> list[tuple[Line, Line]]:
    """Each ``(drop, keep)`` pair that would lose a link is turned round when the linked line can hold the other (it must
    be droppable and the guard must pass the other way: the second reader is asked about THAT direction), and left out
    when it cannot. A pair that loses no link is unchanged."""
    out: list[tuple[Line, Line]] = []
    seen: set[int] = set()
    for drop, keep in pairs:
        if _loses_no_link(drop.text, keep.text, ask):
            pair = (drop, keep)
        elif (_droppable(keep, ask) and covers(drop.text, keep.text, allowed=_allowed(ask, drop.text), people=ask.people)
              and _loses_no_link(keep.text, drop.text, ask)):
            pair = (keep, drop)
            ask.paths[keep.text] = "flipped"
        else:
            continue
        if pair[0].n not in seen:
            seen.add(pair[0].n)
            out.append(pair)
    return out


def folds(pairs: list[tuple[Line, Line]], ask: Ask) -> dict[str, str]:
    """Confirmed pairs as ``{dropped text: the text that holds it}``. A holder must itself be kept: a holder that is
    dropped too is followed to the line that is kept, and the guard (and the link rule) runs on that pair as well. A pair
    that says the same both ways keeps the older bullet (new lines are taken first, then existing from the last)."""
    held_by = {drop.n: keep.n for drop, keep in pairs}
    by_n = {line.n: line for line in ask.lines}
    dropped: dict[int, int] = {}
    for n in sorted(held_by, key=lambda n: (not by_n[n].new, -n)):
        target, hops = held_by[n], 0
        while target in dropped and hops <= len(by_n):
            target, hops = dropped[target], hops + 1
        if target != n:
            dropped[n] = target
    out: dict[str, str] = {}
    for n, target in dropped.items():
        hops = 0
        while target in dropped and hops <= len(by_n):
            target, hops = dropped[target], hops + 1
        if target in dropped or target == n:
            continue
        if _admits(by_n[target], by_n[n], ask):
            out[by_n[n].text] = by_n[target].text
            ask.paths.setdefault(by_n[n].text, _path(by_n[target].text, by_n[n].text, ask))
    return out


def _path(keep: str, drop: str, ask: Ask) -> str:
    """Which guard path let a pair through: ``plain`` (the guard alone, as before), or ``neighbourhood`` (it passes only
    once the page's neighbours' names are read as one person)."""
    return "plain" if covers(keep, drop, allowed=_allowed(ask, keep)) else "neighbourhood"


def decide(ask: Ask, judge: Callable[[str], dict]) -> dict[str, str]:
    """One page: the ask, then the check; ``{dropped text: holder}``. A failed or unreadable call decides nothing."""
    try:
        wanted = orient(proposals(judge(prompt(ask)), ask), ask)
        return folds(checks(wanted, ask, judge), ask)
    except Exception as exc:  # noqa: BLE001 - no judge answer means the page keeps what the writer did before
        logger.info(f"fact fold: a call failed ({type(exc).__name__}); the page keeps its facts as the writer has them")
        return {}


# --------------------------------------------------------------------------- Stage 3's step


def asks(changes: list[dict], existing_by_id: dict[str, dict], *, names: "link_names.Names | None" = None,
         owner: str | None = None) -> list[tuple[dict, Ask]]:
    """The updates this batch needs a call for, the pages gaining the most facts first, at most ``MAX_ASKS``."""
    from api.services import conflict_resolver, entity_body
    from api.services.claims import strip_claims_block

    found: list[tuple[int, str, dict, Ask]] = []
    for change in changes:
        entity = change.get("entity") or {}
        page = existing_by_id.get(change.get("id"))
        if change.get("action") != "update" or not page or not entity.get("key_facts"):
            continue
        fm = page.get("frontmatter") or {}
        sections = entity_body.parse_sections(strip_claims_block(page.get("body", "")))
        existing = entity_body._bullet_lines(sections.get("Key Facts", ""))
        if not existing:
            continue
        pinned = frozenset(_norm(str(r.get("new") or "")) for r in (fm.get("corrections") or []) if isinstance(r, dict))
        ask = build(change["id"], str(fm.get("name") or change["id"]), existing,
                    [str(f) for f in entity["key_facts"] if isinstance(f, str)],
                    heal=not conflict_resolver._is_human_edited(fm, sections), pinned=pinned, names=names,
                    own=[*(str(a) for a in fm.get("aliases") or []), *([owner] if owner else [])], owner=owner)
        if ask is not None:
            found.append((-sum(line.new for line in ask.lines), change["id"], change, ask))
    found.sort(key=lambda t: (t[0], t[1]))
    return [(change, ask) for _, _, change, ask in found[:MAX_ASKS]]


def apply(change: dict, decided: dict[str, str]) -> int:
    """Record one page's folds on its change: the incoming facts a bullet already says are not added, and the rest of
    the map (an existing bullet a new one says in full) rides ``entity[FOLDS]`` to the writer and the provenance rows.
    Returns how many facts were folded."""
    from api.services import section_provenance

    if not decided:
        return 0
    entity = change["entity"]
    entity["key_facts"] = [f for f in entity.get("key_facts") or []
                           if not (isinstance(f, str) and f.strip() in decided)]
    entity[section_provenance.FOLDS] = {**(entity.get(section_provenance.FOLDS) or {}), **decided}
    return len(decided)


def judge_for(settings) -> Callable[[str], dict] | None:
    """Sleep's small judge as a ``prompt -> dict`` call, or ``None`` when no engine can answer: the engine the cycle
    resolved, on its small tier (`in_short.small_tier`) — the same bill as Stage 2's judge, never a metered key the
    person did not choose, and no engine means no call (`value_alignment.judge_for` is the same function)."""
    try:
        from api.services import in_short, providers
        from api.services.engine_select import CLI_MODES

        small = in_short.small_tier(settings)
        if str(getattr(small, "llm_mode", "")).lower() in CLI_MODES:
            llm_fn = providers.resolve_llm_fn(small, stage=STAGE, is_async=False)
        else:
            import litellm

            llm_fn = providers.resolve_llm_fn(small, model=small.litellm_model, completion=litellm.completion,
                                              stage=STAGE)
    except Exception as exc:  # noqa: BLE001 - no engine: facts keep the words Stage 1 gave them
        logger.info(f"fact fold: no engine ({type(exc).__name__})")
        return None

    def judge(text: str) -> dict:
        from api.services import json_parse

        resp = llm_fn(messages=[{"role": "user", "content": text}], response_format={"type": "json_object"})
        try:
            raw = resp.choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            raw = resp.get("choices", [{}])[0].get("message", {}).get("content") if isinstance(resp, dict) else ""
        return json_parse.parse_json_object_or(raw or "", {})

    return judge
