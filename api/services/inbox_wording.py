"""Inbox questions said the way a person would ask them, each with its reason (vision item 10, S4 and S6).

The owner (2026-10-28): the agent "asks questions in more human concrete format, like 'is <nick-a> and <nick-b> the
same person?'", "'are you still interested in learning about <topic>? You mentioned it one time like 2 months ago,
and I don't want to push you on that'", and for a role nobody has mentioned whose profile looks old, "the agent has
to come with a reason … like say 'your LinkedIn seems a bit stale' and then 'so I was not sure if you still are'".

This module is that voice, **at read and never written**: :func:`spoken` turns one inbox item (its frontmatter as
the readers already hold it, plus its page's frontmatter) into a :class:`Spoken` — one question, and the human
reason for asking it now. Nothing here changes a stored question, an option, a key or a label (Hyrum: an agent, the
app and the resolvers all key on those); the same answer keys resolve it. Template-only, no model, no network: the
reason is drawn from what the record already says — how many conversations named the page and when the last one
was (age counts from when it was said, the decay rail), the two sides of a conflict with their ages, and, for a
role, the state of a tracked source's last re-check (ruling 26's ``refresh`` state — never a new fetch; a walled
profile is only ever read by the person's own agent, so "stale" means "not re-read lately", never "Cicada looked").

The person's own page is spoken to as "you"; anyone else by name. Every question ends in ``?`` and stays within the
G115 card rule (160 characters), names clipped first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from api.services import inbox_questions

MAX_QUESTION = 160
MAX_NAME = 48
MAX_LABEL = 40
#: A decay question on a page said within this many days is "fading", never "not since".
RECENT_DAYS = 30


@dataclass(frozen=True)
class Spoken:
    question: str
    reason: str

    def to_dict(self) -> dict:
        return {"question": self.question, "reason": self.reason}


def _clip(text, limit: int = MAX_NAME) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ask(text: str) -> str:
    text = " ".join(text.split()).rstrip(" .")
    if not text.endswith("?"):
        text += "?"
    return text if len(text) <= MAX_QUESTION else text[: MAX_QUESTION - 2].rstrip() + "…?"


def _ago(day, today: str) -> str | None:
    """``"about two months ago"``-style, or None when the day is unknown."""
    phrase = inbox_questions.humanize_age(day, today)
    if phrase == "unknown":
        return None
    return phrase if phrase in ("today", "yesterday") else f"about {phrase}"


def _for(day, today: str) -> str | None:
    """``"in seven months"``-style ("You haven't mentioned it in …"), or None."""
    phrase = inbox_questions.humanize_age(day, today)
    if phrase in ("unknown", "today", "yesterday"):
        return None
    return "in " + phrase.removesuffix(" ago")


def _conversations(fm: dict | None) -> int:
    raw = (fm or {}).get("source_episodes") or []
    return len({str(e) for e in raw if str(e).strip()}) if isinstance(raw, list) else 0


def _list(names: list[str]) -> str:
    names = [_clip(n, 32) for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


# --------------------------------------------------------------------------- the source cue (S6)

#: A source re-read within its own cadence is fresh: it speaks for the fact, so a "still?" question is not asked.
FRESH, STALE, DEAD = "fresh", "stale", "dead"


def source_cue(page_fm: dict | None, predicate: str | None, today: date, *, own: bool,
               name: str = "") -> tuple[str | None, str | None]:
    """``(state, phrase)`` for the page's tracked source that speaks to ``predicate`` — the one tied to it, else a
    profile on a walled site (a LinkedIn-style page about the person as a whole). ``state`` is :data:`FRESH`,
    :data:`STALE`, :data:`DEAD` or None (no tracked source); ``phrase`` is the human half ("your LinkedIn seems a bit
    stale"), None when fresh or absent. Derived from the stored ``refresh`` state alone: no fetch, ever."""
    from api.services import fact_sources, reading_hosts, source_refresh

    sources = [s for s in fact_sources.as_sources((page_fm or {}).get("sources")) if source_refresh.tracked(s)]
    if not sources:
        return None, None
    tied = [s for s in sources if fact_sources.same_predicate(s.get("predicate"), predicate)]
    pool = tied or [s for s in sources if not s.get("predicate") and source_refresh.walled(str(s.get("ref") or ""))]
    if not pool:
        return None, None
    whose = "your" if own else f"{_clip(name, 32)}'s"
    best: tuple[str, str | None] | None = None
    for s in pool:
        site = reading_hosts.site_label(reading_hosts.site_of(str(s.get("ref") or ""))) or "profile"
        st = source_refresh.state(s)
        if source_refresh.dead(s):
            cand = (DEAD, f"{whose} {site} link stopped working")
        else:
            last = source_refresh._day(st.get("good") or (st.get("at") if st.get("outcome") == "read" else None))
            if last is not None and (today - last).days < source_refresh.every_days(s):
                return FRESH, None          # one fresh source is enough: it keeps the fact current (ruling 26)
            cand = (STALE, f"{whose} {site} seems a bit stale")
        if best is None or (best[0] == DEAD and cand[0] == STALE):
            best = cand
    return best if best else (None, None)


# --------------------------------------------------------------------------- per kind

#: The "still?" families (``asks: still``, `still_questions`). Keyed by predicate; ``{obj}`` the object's name.
STILL_OWN = {
    "works-at": "Are you still working at {obj}?",
    "employed-by": "Are you still working at {obj}?",
    "studies-at": "Are you still studying at {obj}?",
    "lives-in": "Do you still live in {obj}?",
    "reports-to": "Do you still report to {obj}?",
    "is-interested-in": "Are you still interested in {obj}?",
    "interested-in": "Are you still interested in {obj}?",
    "wants-to-learn": "Are you still interested in learning about {obj}?",
    "is-learning": "Are you still interested in learning about {obj}?",
    "learning": "Are you still interested in learning about {obj}?",
    "studies": "Are you still studying {obj}?",
}
STILL_OTHER = {
    "works-at": "Is {name} still working at {obj}?",
    "employed-by": "Is {name} still working at {obj}?",
    "studies-at": "Is {name} still studying at {obj}?",
    "lives-in": "Does {name} still live in {obj}?",
    "reports-to": "Does {name} still report to {obj}?",
}
INTEREST_PREDICATES = frozenset({"is-interested-in", "interested-in", "wants-to-learn", "is-learning", "learning",
                                 "studies"})

#: Decay, by the page's type: what "still tracking?" means for that kind of thing.
DECAY_QUESTIONS = {
    "concept": "Are you still interested in {name}?",
    "skill": "Are you still working on {name}?",
    "project": "Are you still working on {name}?",
    "person": "Are you still in touch with {name}?",
    "tool": "Do you still use {name}?",
    "company": "Is {name} still part of what you're doing?",
    "location": "Does {name} still matter to you?",
    "directory": "Do you still work in {name}?",
}
_DECAY_DEFAULT = "Is {name} still something you care about?"

#: The person's own page, said to them: the conflict templates of ``predicates.PREDICATE_QUESTIONS``, second person.
OWN_CONFLICT = {
    "works-at": "Where do you work now?",
    "works-on": "What are you working on now?",
    "works-with": "Who do you work with now?",
    "located-in": "Where are you based now?",
    "lives-in": "Where do you live now?",
    "uses": "What do you use now?",
    "prefers": "What do you prefer now?",
    "studies-at": "Where do you study now?",
}

_NOUNS = {"person": "person", "company": "company", "project": "project", "tool": "tool", "location": "place",
          "skill": "skill", "directory": "folder"}


def spoken(fm: dict, today: str, *, page_fm: dict | None = None, other_fm: dict | None = None,
           owner_id: str | None = None, group: list[str] | None = None, same: dict[str, str] | None = None,
           titled: list[dict] | None = None) -> Spoken:
    """The human question and its reason for one item. ``fm`` is the item as the readers serve it (decay and
    follow-up already synthesised); ``page_fm`` its page's frontmatter, ``other_fm`` a duplicate pair's other page;
    ``group`` the names when several duplicate questions are one person (:mod:`inbox_catchup`).

    G227: ``same`` is the bank's qualifier map (`same_name.qualifiers`) and ``titled`` the pages sharing a mention's
    title (``{id, name, type, qualifier}``, the item's ``same_title``): a page is spoken of with its qualifier, and a
    mention said exactly as a page's title is asked about the one page its answers act on ("Is this the <name> IDE?"),
    the others counted in the reason."""
    kind = str(fm.get("kind") or "")
    entity_id = str(fm.get("entity_id") or "")
    own = bool(owner_id) and entity_id == owner_id
    name = _clip(speakable(fm.get("entity_name") or (page_fm or {}).get("name") or entity_id, page_fm))
    page_type = str((page_fm or {}).get("type") or "")
    if group and len(group) >= 2:
        return _group(group, page_type)
    if kind == "merge_suggestion":
        if (said := _same_name(fm, today, name, other_fm, same or {}, titled or [])) is not None:
            return said
        return _pair(fm, today, name, page_fm, other_fm)
    if same and (q := same.get(entity_id)):
        # G227: a page whose title another page shares is asked about by its qualifier ("<name-a> (IDE)").
        name = f"{name} ({q})"
    if kind == "decay":
        return _decay(name, page_type, page_fm, today)
    if kind == "conflict" and str(fm.get("asks") or "") == "still":
        return _still(fm, today, name, page_fm, own=own)
    if kind == "conflict":
        return _conflict(fm, today, name, own=own)
    if kind == "clarification":
        return _clarification(fm, today, name, page_type)
    if kind == "followup":
        dated = str(fm.get("predicate") or "") in ("milestone", "due")
        return Spoken(_ask(str(fm.get("question") or fm.get("title") or f"How did {name} go?")),
                      "Its date has passed, and nothing has said how it went." if dated
                      else "It has gone quiet, and I'd rather ask than let it fade.")
    return Spoken(_ask(str(fm.get("question") or fm.get("title") or f"Anything to add about {name}?")),
                  "It is still open in your inbox.")


def _group(names: list[str], page_type: str) -> Spoken:
    noun = _NOUNS.get(page_type or "person", "thing")
    return Spoken(_ask(f"Are {_list(names)} the same {noun}"),
                  "These names come up the way one name would, and I only join people on your word.")


_UNNAMED_SUFFIX = " (unnamed)"


def speakable(name, page_fm: dict | None = None) -> str:
    """A page's name as a person says it: a relation-titled page with no name yet is "your <relation>", never its
    title ("Partner"); Stage 1's "<x> (unnamed)" is just "<x>". Everything else is the name as written."""
    text = " ".join(str(name or "").split())
    fm = page_fm or {}
    if text.lower().endswith(_UNNAMED_SUFFIX):
        text = text[: -len(_UNNAMED_SUFFIX)].strip()
    roles = fm.get("owner_roles")
    if fm.get("unnamed") and not fm.get("nickname_title") and isinstance(roles, list) and roles:
        return f"your {str(roles[0]).strip().lower()}"
    return text


def _pair(fm: dict, today: str, name: str, page_fm: dict | None, other_fm: dict | None) -> Spoken:
    other = _clip(speakable((other_fm or {}).get("name") or _candidate(fm) or fm.get("merge_target_hint")
                            or "another page", other_fm))
    kind_of = str((other_fm or {}).get("type") or (page_fm or {}).get("type") or fm.get("suggested_classification")
                  or "")
    noun = _NOUNS.get(kind_of, "thing")
    heard = fm.get("heard_in") if isinstance(fm.get("heard_in"), dict) else None
    if noun == "person" and heard and heard.get("mention") and heard.get("page"):
        # One person across sources (owner 2026-10-28): "Is the <name> in your group chat the same <name> you talked
        # to Claude about?" — the mention's own word on both sides; who the page is stays in the reason.
        said = _clip(re.sub(r"\s*\([^()]*\)\s*$", "", speakable(fm.get("entity_name") or name)).strip() or name)
        where = str(heard["mention"])
        return Spoken(_ask(f"Is the {said} {heard['page']} the same {said} {where}"),
                      f"{other} is in your chats; {said} came up elsewhere. A shared first name is not enough, so "
                      "I only join them on your word.")
    question = _ask(f"Are {name} and {other} the same {noun}")
    if noun == "person":
        reason = "They could be one person, and I only join people on your word."
    else:
        when = _ago(fm.get("source_episode_timestamp") or fm.get("created_date"), today)
        reason = (f"You mentioned {name} {when}, and it may be {other}; I'd rather ask than join them by mistake."
                  if when else "I'd rather ask than join them by mistake.")
    return Spoken(question, reason)


def _fold(text) -> str:
    return " ".join(str(text or "").casefold().split())


def _is_site(word: str) -> bool:
    """A saved link's qualifier is its site ("example.com", "example.com/docs"): said "saved from", not as a noun."""
    head = word.split("/", 1)[0]
    return "." in head and " " not in word


def _thing_word(page: dict) -> str:
    """What a page is, said in a word: its qualifier when its title is shared, else its type (`same_name`)."""
    from api.services.same_name import TYPE_WORDS

    return str(page.get("qualifier") or TYPE_WORDS.get(str(page.get("type") or ""), "") or "one")


def _thing(name: str, page: dict) -> str:
    """"the <name-a> IDE" / "the <name-a> saved from example.com" — one page said by what it is."""
    word = _clip(_thing_word(page), MAX_LABEL)
    return f"the {name} saved from {word}" if _is_site(word) else f"the {name} {word}"


def _which(page: dict) -> str:
    """One page among several with a name, said by what it is: "the IDE", "the one saved from example.com"."""
    word = _clip(_thing_word(page), MAX_LABEL)
    return f"the one saved from {word}" if _is_site(word) else f"the {word}"


def _same_name(fm: dict, today: str, name: str, other_fm: dict | None, same: dict[str, str],
               titled: list[dict]) -> Spoken | None:
    """G227: a mention said exactly as a page's title, or None when the names differ.

    Two or more pages with the name (owner 2026-10-29, "pick the page"): ONE question for the mention — "Which
    <name-a> is this: the IDE or the program?" — answered by picking the page or "Another one" (the options
    `same_name_pick` serves). One page: "Is this the <name-a> IDE?", its options that page or "another one"."""
    target = str(fm.get("merge_target_hint") or "")
    pages = list(titled)
    if len(pages) >= 2 and all(_fold(p.get("name")) == _fold(name) for p in pages):
        things = [_which(p) for p in pages]
        question = _ask(f"Which {name} is this: {', '.join(things[:-1])} or {things[-1]}")
        if len(question) >= MAX_QUESTION:
            question = _ask(f"Which {name} is this")
        when = _ago(fm.get("source_episode_timestamp") or fm.get("created_date"), today)
        said = f"You mentioned {name} {when}" if when else f"You mentioned {name}"
        reason = (f"{said}, and {len(pages)} things are called {name}; if it's another one, say so and I'll keep it "
                  "as its own.")
        return Spoken(question, reason)
    if not pages and other_fm and _fold(speakable(other_fm.get("name"), other_fm)) == _fold(name):
        pages = [{"id": target, "name": str(other_fm.get("name") or name), "type": str(other_fm.get("type") or ""),
                  "qualifier": same.get(target)}]
    page = next((p for p in pages if p.get("id") == target), None)
    if page is None or _fold(page.get("name")) != _fold(name):
        return None
    question = _ask(f"Is this {_thing(name, page)}")
    when = _ago(fm.get("source_episode_timestamp") or fm.get("created_date"), today)
    said = f"You mentioned {name} {when}" if when else f"You mentioned {name}"
    others = len({str(p.get("id")) for p in pages}) - 1
    if others >= 1:
        reason = (f"{said}, and {others + 1} things are called {name}; if it's not this one, say no and I'll keep it "
                  "apart.")
    else:
        reason = f"{said}, and a page already has that name; if it's another one, say no and I'll keep it apart."
    return Spoken(question, reason)


def _candidate(fm: dict) -> str | None:
    text = str(fm.get("uncertainty_type") or "").strip()
    if not text.lower().startswith("possible duplicate"):
        return None
    rest = text[len("possible duplicate"):].strip()
    return (rest[3:] if rest.lower().startswith("of ") else rest).strip() or None


def _decay(name: str, page_type: str, page_fm: dict | None, today: str) -> Spoken:
    question = _ask(DECAY_QUESTIONS.get(page_type, _DECAY_DEFAULT).format(name=name))
    said = (page_fm or {}).get("last_referenced")
    n = _conversations(page_fm)
    when = _ago(said, today)
    gentle = page_type in ("concept", "skill")
    days = inbox_questions.age_days(said, today)
    if when and days is not None and days < RECENT_DAYS:
        reason = f"It last came up {when}, but it has been fading, so I'm checking it's still worth keeping."
    elif n <= 1 and when:
        reason = (f"You mentioned it once, {when}, and I don't want to push you on it." if gentle
                  else f"It came up once, {when}, and not since.")
    elif when:
        reason = f"It came up in {n} conversations, the last {when}, and not since."
    else:
        reason = "It has gone quiet, and I'd rather ask than let it fade."
    return Spoken(question, reason)


def _still(fm: dict, today: str, name: str, page_fm: dict | None, *, own: bool) -> Spoken:
    predicate = str(fm.get("predicate") or "")
    options = [o for o in inbox_questions.normalize_options(fm.get("options"))
               if str(o.get("key")) not in ("neither", "both")]
    obj = _clip(options[0].get("label") if options else fm.get("object") or "it", MAX_LABEL)
    templates = STILL_OWN if own else STILL_OTHER
    template = templates.get(predicate)
    question = _ask(template.format(obj=obj, name=name)) if template else _ask(str(fm.get("question") or ""))
    said = fm.get("last_said")
    n = int(fm.get("said_in") or 0)
    if predicate in INTEREST_PREDICATES:
        when = _ago(said, today)
        if n <= 1 and when:
            reason = f"You mentioned it once, {when}, and I don't want to push you on it."
        elif when:
            reason = f"You mentioned it {n} times, the last {when}, and I don't want to push you on it."
        else:
            reason = "It has gone quiet, and I don't want to push you on it."
        return Spoken(question, reason)
    quiet = _for(said, today)
    try:
        day = date.fromisoformat(str(today)[:10])
    except ValueError:
        day = date.today()
    _state, cue = source_cue(page_fm, predicate, day, own=own, name=name)
    if quiet:
        lead = f"You haven't mentioned it {quiet}" if own else f"Nobody has mentioned it {quiet}"
    else:
        lead = "Nothing new has come up about it"
    verb = "do" if predicate in _DO_VERBS else "are"
    tail = f"so I wasn't sure you still {verb}" if own else f"so I wasn't sure {name} still {_THIRD[verb]}"
    reason = f"{lead}, and {cue}, {tail}." if cue else f"{lead}, {tail}."
    return Spoken(question, reason)


_DO_VERBS = frozenset({"lives-in", "reports-to"})
_THIRD = {"do": "does", "are": "is"}


#: ``predicates._GENERIC_QUESTION`` as stored: "Which is true about <name> (<predicate>)?" — a slug in a question.
_GENERIC = re.compile(r"^Which is true about .+ \([\w-]+\)\?$")


def _conflict(fm: dict, today: str, name: str, *, own: bool) -> Spoken:
    predicate = str(fm.get("predicate") or "")
    stored = str(fm.get("question") or fm.get("title") or "")
    sides, labels = [], []
    for o in inbox_questions.normalize_options(fm.get("options")):
        if str(o.get("key")) in ("neither", "both"):
            continue
        when = _ago(o.get("last_referenced") or o.get("observed_at"), today)
        label = _clip(o.get("label"), MAX_LABEL)
        labels.append(label)
        sides.append(f"{label} ({when})" if when else label)
    if own and predicate in OWN_CONFLICT:
        question = _ask(OWN_CONFLICT[predicate])
    elif (not stored or _GENERIC.match(stored)) and len(labels) >= 2:
        question = _ask(f"Which is right about {'you' if own else name}: {labels[0]} or {labels[1]}")
    else:
        question = _ask(stored or f"What is true about {name}")
    if len(sides) >= 2:
        reason = f"I have both {sides[0]} and {sides[1]}, and I can't tell which is current."
    else:
        reason = "Two things I have disagree, and I can't tell which is current."
    return Spoken(question, reason)


def _clarification(fm: dict, today: str, name: str, page_type: str) -> Spoken:
    asks = str(fm.get("asks") or "")
    when = _ago(fm.get("source_episode_timestamp") or fm.get("created_date"), today)
    if asks == "name":
        return Spoken(_ask(str(fm.get("question") or f"What's {name}'s name")),
                      "You've mentioned them, but never by name.")
    uncertainty = str(fm.get("uncertainty_type") or "").lower()
    guess = str(fm.get("suggested_classification") or page_type or "").lower()
    if "relationship" in uncertainty or guess == "person":
        return Spoken(_ask(f"Who is {name} to you"),
                      f"You mentioned {name} {when}, but not how you know them." if when
                      else f"You mentioned {name}, but not how you know them.")
    return Spoken(_ask(str(fm.get("question") or f"Who or what is {name}")),
                  f"You mentioned {name} {when}, and I couldn't tell who or what it is." if when
                  else f"You mentioned {name}, and I couldn't tell who or what it is.")
