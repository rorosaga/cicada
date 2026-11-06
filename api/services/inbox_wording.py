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


# --------------------------------------------------------------------------- the options, said at read

#: The wording's shape on the wire. It rides the inbox ETag (`routers/inbox.py`): a release that words the same stored
#: question differently must make every client take one fresh 200, not keep the old words on a 304.
SHAPE = "question-words-1"

_SYNTHETIC = ("neither", "both")
#: A bookkeeping lead the contradiction check's prompt once put in an option's description ("Existing description,
#: last mentioned …", "New record: …"): the check's own working words, never the person's.
_BOOKKEEPING = re.compile(
    r"^(?:from\s+(?:the\s+)?)?(?:existing|new|older|newer|current)(?:\s+undated)?\s+"
    r"(?:description|record|note|notes|article|claim|page|text|summary)\b"
    r"(?:\s*[,:]\s*|\s*$|\s+(?=(?:from|undated|dated|says?|saying|stating|calls?|describes?|on|recorded)\b))",
    re.IGNORECASE)
_PAGE_ASOF = re.compile(r"^described on the page as of\b.*$", re.IGNORECASE)
_EXTRACTED = re.compile(r"extracted from (ep_[\w-]+)")
_PAGE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def episode_of(option: dict) -> str | None:
    """The conversation an option's value came from: its own ``source_episode``, else the one an older writer put in
    its description (``extracted from ep_…``). Read before the description is rewritten, so the id is never lost."""
    ep = str(option.get("source_episode") or "").strip()
    if ep:
        return ep
    found = _EXTRACTED.search(str(option.get("description") or ""))
    return found.group(1) if found else None


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _opening(name: str) -> str:
    """A page's name at the start of a sentence: "your partner" takes a capital, a name keeps its own ("iPhone")."""
    return _cap(name) if name.startswith("your ") else name


def _clean_description(text) -> str | None:
    """An option's description with the check's bookkeeping lead dropped, or None when nothing else is left."""
    text = " ".join(str(text or "").split())
    if _PAGE_ASOF.match(text):
        return None
    text = _BOOKKEEPING.sub("", text).strip()
    return _cap(text) if text else None


def _said_side(option: dict, by_id: dict, untimed) -> tuple[str | None, list[str]]:
    """``(the day this side was last said, its conversations)``. A claim on the page: its own said day and
    conversations. A claim not on the page (the usual second value): the day of the conversation the option names.
    Neither: undated. ``valid_from`` is when it became true and ``observed_at`` when the question was raised: never a
    stand-in for when it was said."""
    from api.services import decay_policy, source_refresh
    from api.services.claim_reconciler import _said_refs

    claim = by_id.get(str(option.get("claim_id") or ""))
    if claim is not None:
        return source_refresh.said_on(claim, untimed), _said_refs(claim)
    ep = episode_of(option)
    if ep:
        return decay_policy.latest_said([ep], untimed=untimed), [ep]
    return None, []


def present_options(fm: dict, today: str, *, claims=None, page_name=None, untimed=frozenset()) -> list[dict]:
    """The options of one inbox item as a person reads them: copies, never the stored ones (pure and idempotent).

    Only a conflict's options are touched, and only what is about the dates and the words:

    * a claim-backed side is dated by when it was last SAID (:func:`_said_side`), on both ``observed_at`` and
      ``last_referenced``, and its description is rebuilt as ``Last mentioned <day> · <age>`` when it was one of
      ``claim_reconciler._claim_option``'s (no frozen age, no conversation id); another writer's prose stays;
    * a claim-less description side holds only the day the question was raised: no date, and the check's
      bookkeeping lead ("Existing description, …") dropped from its words;
    * on a relation predicate, a label that is exactly a page's id is that page's name (``page_name(id)``).

    Keys, claim ids and the stored file are never changed. A copy remembers its conversations (``_said_in``) for the
    reason, and that it was presented (``_presented``): presenting twice is presenting once."""
    options = inbox_questions.normalize_options(fm.get("options"))
    kind = str(fm.get("kind") or "")
    if kind == "page_edit" and _wrong_alias(fm):
        return [{**o, "label": _ALIAS_ANSWERS.get(str(o.get("key")), o.get("label"))} for o in options]
    if kind != "conflict":
        return [dict(o) for o in options]
    predicate = str(fm.get("predicate") or "") or "description"
    prose = predicate == "description"
    relation = not prose and not predicate.startswith("value-of-")
    by_id = {str(c.id): c for c in (claims or [])}
    out: list[dict] = []
    for option in options:
        o = dict(option)
        if o.get("_presented") or str(o.get("key")) in _SYNTHETIC:
            out.append(o)
            continue
        o["_presented"] = True
        episode = episode_of(o)
        desc = str(o.get("description") or "")
        if o.get("claim_id"):
            day, episodes = _said_side(o, by_id, untimed)
            o["observed_at"] = o["last_referenced"] = day
            o["_said_in"] = episodes
            if desc.startswith("Last mentioned ") or desc.startswith("Last mention unknown"):
                o["description"] = (f"Last mentioned {day} · {inbox_questions.humanize_age(day, today)}" if day
                                    else "Last mention unknown")
            elif prose and desc:
                o["description"] = _clean_description(desc)
        else:
            o["_said_in"] = [episode] if episode else []
            if prose:
                o["observed_at"] = o["last_referenced"] = None
                if desc:
                    o["description"] = _clean_description(desc)
        if episode and not o.get("source_episode"):
            o["source_episode"] = episode
        label = str(o.get("label") or "")
        if relation and page_name is not None and _PAGE_ID.match(label):
            named = page_name(label)
            if named:
                o["label"] = str(named)
        out.append(o)
    # With three or more answers "both" can't be the word. The key stays, and so does what answering it does.
    if sum(str(o.get("key")) not in _SYNTHETIC for o in out) >= 3:
        for o in out:
            if str(o.get("key")) == "both":
                o["label"] = "All of these are true (different contexts)"
                o["description"] = "Keep them all, each tagged with its context"
    return out


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
           titled: list[dict] | None = None, claims=None, page_name=None, owner_name: str | None = None,
           untimed=frozenset()) -> Spoken:
    """The human question and its reason for one item. ``fm`` is the item as the readers serve it (decay and
    follow-up already synthesised); ``page_fm`` its page's frontmatter, ``other_fm`` a duplicate pair's other page;
    ``group`` the names when several duplicate questions are one person (:mod:`inbox_catchup`).

    G227: ``same`` is the bank's qualifier map (`same_name.qualifiers`) and ``titled`` the pages sharing a mention's
    title (``{id, name, type, qualifier}``, the item's ``same_title``): a page is spoken of with its qualifier, and a
    mention said exactly as a page's title is asked about the one page its answers act on ("Is this the <name> IDE?"),
    the others counted in the reason.

    A conflict is spoken from its options as :func:`present_options` serves them (``claims``: the page's claims;
    ``page_name``: an id → its page's name, or None; ``untimed``: the episodes that say nothing about when), so no
    caller can reach a raw date. ``owner_name`` is the owner page's own name, for a stored question that names them."""
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
    if kind == "conflict":
        fm = {**fm, "options": present_options(fm, today, claims=claims, page_name=page_name, untimed=untimed)}
        if str(fm.get("asks") or "") == "still":
            return _still(fm, today, name, page_fm, own=own)
        return _conflict(fm, today, name, own=own, page_type=page_type, owner_name=owner_name)
    if kind == "page_edit":
        return _page_edit(fm, name)
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
        reason = (f"{_opening(name)} came up {when}, and it may be {other}; I'd rather ask than join them by mistake."
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
        said = f"{_opening(name)} came up {when}" if when else f"{_opening(name)} came up"
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
    said = f"{_opening(name)} came up {when}" if when else f"{_opening(name)} came up"
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


# --------------------------------------------------------------------------- the voice of a stored question

_YOU = re.compile(r"\b(?:you|your|yours|yourself|you're|you've|you'd|you'll)\b", re.IGNORECASE)
_FIRST = re.compile(r"\b(?:I'm|I've|I'd|I'll|I|me|[Mm]y|myself)\b")
#: "Phase I", "Series I": a capitalised word before a bare "I" that no question opens with. The question stays as written.
_NUMERAL_I = re.compile(r"\b(?!(?:Am|Was|Were|Have|Had|Did|Do|Should|Can|Could|Would|Will|Is|Has|When|Where|What|Why|How|"
                        r"Which|Who|If|And|But|Or|So|Then|Now)\b)[A-Z][\w-]* I\b(?!['’])")
#: Ordered: the frames whose verb turns with the pronoun first, then the bare words.
_TURNS = (
    (re.compile(r"\b(Am|am) I\b"), lambda m: ("Are" if m.group(1) == "Am" else "are") + " you"),
    (re.compile(r"\b(Was|was) I\b"), lambda m: ("Were" if m.group(1) == "Was" else "were") + " you"),
    (re.compile(r"\bI am\b"), lambda m: "you are"),
    (re.compile(r"\bI was\b"), lambda m: "you were"),
    (re.compile(r"\bI'm\b"), lambda m: "you're"),
    (re.compile(r"\bI've\b"), lambda m: "you've"),
    (re.compile(r"\bI'd\b"), lambda m: "you'd"),
    (re.compile(r"\bI'll\b"), lambda m: "you'll"),
    (re.compile(r"\bI\b"), lambda m: "you"),
    (re.compile(r"\bmyself\b"), lambda m: "yourself"),
    (re.compile(r"\b[Mm]y\b"), lambda m: "your"),
    (re.compile(r"\bme\b"), lambda m: "you"),
)
_QUOTES = "\"“”‘’"
_OWNER_FRAMES = {"Did": "Did you", "Will": "Will you", "Can": "Can you", "Should": "Should you", "Would": "Would you",
                 "Could": "Could you", "Does": "Do you", "Is": "Are you", "Has": "Have you"}


_STILL_THEM = re.compile(r"\b(?:he|she|him|her|hers|his|himself|herself)\b", re.IGNORECASE)


def _open_capital(text: str) -> str:
    """A sentence that now opens with the pronoun opens with a capital."""
    return re.sub(r"(^|[.?!]\s+)(you|your)\b", lambda m: m.group(1) + _cap(m.group(2)), text)


def _second_person(text: str) -> str:
    """Every first-person word of a stored question said to the person, or the question unchanged when it quotes
    words (a first-person word inside quotation marks is somebody's, not the question's) — all or none: a
    half-turned sentence is worse than the stored one."""
    if not _FIRST.search(text):
        return text
    # "mine" may be a noun, and turning the rest around it would leave half a sentence turned.
    # So does a question in Spanish, where "me" is another word.
    if any(q in text for q in _QUOTES) or _NUMERAL_I.search(text) or re.search(r"\bmine\b", text) or "¿" in text:
        return text
    for pattern, repl in _TURNS:
        text = pattern.sub(repl, text)
    return _open_capital(text)


def _owner_voice(text: str, names: list[str]) -> str:
    """The owner named in a stored question ("Did <owner> …", "<owner>'s …") said to them. Only a safe verb frame
    turns; any other position of the name leaves the question as written."""
    names = [n for n in dict.fromkeys(n.strip() for n in names) if n]
    if not names:
        return text
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    frame = re.compile(rf"\b({'|'.join(_OWNER_FRAMES)})\s+(?i:{alt})\b")
    possessive = re.compile(rf"(?i:\b(?:{alt}))'s\b")
    bare = re.compile(rf"(?i:\b(?:{alt})\b)")
    turned = possessive.sub("your", text)
    turned = frame.sub(lambda m: _OWNER_FRAMES[m.group(1)], turned)
    # "Did <name> attend, or is he applying": the second clause is still about them, and half a sentence turned is worse.
    return text if bare.search(turned) or _STILL_THEM.search(turned) else _open_capital(turned)


def stored_in_your_voice(question: str, *, owner_names: list[str] | None = None) -> str:
    """A stored question said to the person it is about (A6). A question that already says "you" is left alone."""
    if not question or _YOU.search(question):
        return question
    turned = _second_person(question)
    return _owner_voice(turned, owner_names or [])


def _owner_names(own: bool, page_type: str, owner_name: str | None, entity_name: str) -> list[str]:
    """What the stored question may call the owner, for THIS subject: never a constant, always the bank's own name.
    The owner's page: their full name, its first word, "the owner", "the user". A page that is not a person: the
    owner page's exact name, "the owner", "the user". Another person's page: nothing, because there the name may
    be that other person's."""
    if own:
        full = str(owner_name or entity_name or "").strip()
        first = full.split()[0] if len(full.split()) > 1 else ""
        return [n for n in (full, first, "the owner", "the user") if n]
    if page_type == "person":
        return []
    return [n for n in (str(owner_name or "").strip(), "the owner", "the user") if n]


_DO_VERBS = frozenset({"lives-in", "reports-to"})
_THIRD = {"do": "does", "are": "is"}


#: ``predicates._GENERIC_QUESTION`` as stored: "Which is true about <name> (<predicate>)?" — a slug in a question.
_GENERIC = re.compile(r"^Which is true about .+ \([\w-]+\)\?$")


def _slug_noun(predicate: str) -> str:
    """``value-of-team-size`` → "team size": the noun a bare-value question is about."""
    return predicate[len("value-of-"):].replace("-", " ").replace("_", " ").strip()


def _possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _conflict(fm: dict, today: str, name: str, *, own: bool, page_type: str = "", owner_name: str | None = None) -> Spoken:
    predicate = str(fm.get("predicate") or "")
    stored = str(fm.get("question") or fm.get("title") or "")
    options = [o for o in inbox_questions.normalize_options(fm.get("options")) if str(o.get("key")) not in _SYNTHETIC]
    labels = [_clip(o.get("label"), MAX_LABEL) for o in options]
    clipped = any(label.endswith("…") for label in labels)
    # The question names the answers only when it can name all of them, whole; the choices say the rest.
    answers = f": {labels[0]} or {labels[1]}" if len(labels) == 2 and not clipped else ""
    days = [(o.get("last_referenced") or o.get("observed_at")) for o in options]
    sides = [f"{label} ({_ago(day, today)})" if _ago(day, today) else label for label, day in zip(labels, days)]
    noun = _slug_noun(predicate) if predicate.startswith("value-of-") else ""
    if own and predicate in OWN_CONFLICT:
        question = _ask(OWN_CONFLICT[predicate])
    elif (not stored or _GENERIC.match(stored)) and len(labels) >= 2:
        if noun:
            whose = "your" if own else _possessive(name)
            question = _ask(f"Which is right for {whose} {noun}{answers}")
        else:
            question = _ask(f"Which is right about {'you' if own else name}{answers}")
    else:
        spoken_stored = stored_in_your_voice(
            stored, owner_names=_owner_names(own, page_type, owner_name, name)) if stored else ""
        question = _ask(spoken_stored or f"What is true about {name}")

    # Only a side with a claim behind it (or a date of its own) says anything about WHEN; a description's two sides
    # hold the day the question was raised, which is no date at all (`present_options`).
    real_at = [i for i, (o, d) in enumerate(zip(options, days)) if o.get("claim_id") or d]
    real = [(options[i], days[i]) for i in real_at]
    who = "you" if own else name
    if len(real) < 2:
        count = "Two things" if len(options) <= 2 else "Several things"
        return Spoken(question, f"{count} I have about {who} disagree, and I can't tell which is right.")
    episodes = [list(o.get("_said_in") or ([e] if (e := episode_of(o)) else [])) for o, _ in real]
    dated = [str(d)[:10] for _, d in real if d]
    whole = len(real) == len(options)   # "same conversation" and "same day" must be true of every answer offered
    if whole and all(len(e) == 1 for e in episodes) and len({e[0] for e in episodes}) == 1:
        reason = ("Both came up in the same conversation, so I can't tell whether one replaces the other."
                  if len(real) == 2 else
                  "They all came up in the same conversation, so I can't tell whether one replaces the other.")
    elif whole and len(dated) == len(real) and len(set(dated)) == 1:
        ago = _ago(dated[0], today)
        day = f"the same day ({ago})" if ago else "the same day"
        reason = (f"Both were said {day}, so I can't tell which is current." if len(real) == 2 else
                  f"They were all said {day}, so I can't tell which is current.")
    elif len(real) >= 3 or clipped:
        latest = _ago(max(dated), today) if dated else None
        reason = (f"I have {len(real)} different answers, the latest {latest}, and I can't tell which is current."
                  if latest else f"I have {len(real)} different answers, and I can't tell which is current.")
    else:
        reason = f"I have both {sides[real_at[0]]} and {sides[real_at[1]]}, and I can't tell which is current."
    return Spoken(question, reason)


#: What the two answers to the wrong-name question mean, said as answers to it. The keys stay.
_ALIAS_ANSWERS = {"apply": "Yes, stop using that name", "dismiss": "No, keep the name"}


def _wrong_alias(fm: dict) -> tuple[str, str] | None:
    """The name and the why of the one page edit Cicada proposes itself, removing a name another thing owns
    (`wrong_aliases`), or None for every other page edit."""
    from api.services import wrong_aliases

    edit = fm.get("edit") if isinstance(fm.get("edit"), dict) else {}
    aliases = edit.get("remove_aliases") if isinstance(edit.get("remove_aliases"), list) else []
    if str(fm.get("origin") or "") != wrong_aliases.ORIGIN or len(aliases) != 1:
        return None
    alias = str(aliases[0] or "").strip()
    page = str(fm.get("entity_name") or "").strip()
    reason = " ".join(str(fm.get("reason") or "").split())
    prefix = f"“{alias}” is the name of another thing, not of {page}: "
    if not alias or not page or not reason.startswith(prefix) or not reason[len(prefix):].strip():
        return None
    return alias, reason[len(prefix):].strip()


def _page_edit(fm: dict, name: str) -> Spoken:
    """E1: the wrong-name edit said as a question; every other page edit keeps its stored words (an empty
    :class:`Spoken` means "use the stored ones")."""
    found = _wrong_alias(fm)
    if not found:
        return Spoken("", "")
    alias, why = found
    return Spoken(_ask(f"Should “{_clip(alias, 32)}” stop being another name for {name}"), f"I think so because: {why}")


def _clarification(fm: dict, today: str, name: str, page_type: str) -> Spoken:
    asks = str(fm.get("asks") or "")
    when = _ago(fm.get("source_episode_timestamp") or fm.get("created_date"), today)
    if asks == "name":
        return Spoken(_ask(str(fm.get("question") or f"What's {name}'s name")),
                      "They've come up, but never by name.")
    uncertainty = str(fm.get("uncertainty_type") or "").lower()
    guess = str(fm.get("suggested_classification") or page_type or "").lower()
    why_asked = str(fm.get("why_asked") or "").strip().rstrip(".,;:")   # the model's own clause (G239), as a sentence
    why_asked = f"{why_asked[0].upper()}{why_asked[1:]}." if why_asked else ""
    if "relationship" in uncertainty or guess == "person":
        return Spoken(_ask(f"Who is {name} to you"),
                      why_asked or (f"{_opening(name)} came up {when}, but not how you know them." if when
                                    else f"{_opening(name)} came up, but not how you know them."))
    return Spoken(_ask(str(fm.get("question") or f"Who or what is {name}")),
                  why_asked or (f"{_opening(name)} came up {when}, and I couldn't tell who or what it is." if when
                                else f"{_opening(name)} came up, and I couldn't tell who or what it is."))
