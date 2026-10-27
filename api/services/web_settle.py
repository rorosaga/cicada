"""A web lookup settles inbox questions about public things (owner ruling 2026-10-16, G61; amends the S3 rail).

The owner, 2026-10-16: "A web lookup answers 'what is X' for public things and closes the question. The answer is saved
with its link and quote, and you can undo it from a 'Settled by a check' list. Never searched: people's names, your own
files, your projects, your life."

This module is the bank side: which questions may be looked up (:func:`classify`), what may leave the machine
(:func:`query_for` — the subject's name plus at most one generic category word, nothing else), what
the model may read to judge which result is the right one (:func:`local_context`, owner 2026-10-16, never sent to the
search), and the one writer that settles a
question and undoes it (:func:`settle`, :func:`undo`). The engine side — who searches, on which engine, under which
gate — is ``web_lookup``; the person's own agent settles through ``cicada_record_check(outcome="settles")``.

**Two tiers, kept apart (owner refinement, 2026-10-16).** The answer carries a *citation* — the found URL and a short
quote — on THAT claim only: one ``web-check`` episode holds them (``attachment [<host>]: as <checker> read it at
<url>`` and the quote line, so the quote is a ``page``-kind span, G118) and the claim's evidence points into it. It is
never written to the page's ``sources:`` (the cheat sheet agents re-check, ruling 26): it never joins a re-check set,
never makes a site trusted and never drives a logo. The person may promote it with one tap through the existing
person's source route ("Track this source" in the app), never automatically.

**What a settle writes**, in one commit: the episode; the claim (observer ``agent``, ``source_trust: external``,
``origin: web-check``) on the subject's page — or held on its pending line (``pending_store``) when the name has no
page yet, so no page is ever created by a lookup; for a conflict, every other open option claim closed today in its
favour — or, for a type question settled on the item's own "both" option, one cited claim per option and nothing
closed; and the question moved to ``inbox/settled/<id>.md`` with a ``settled:`` block saying exactly what it wrote.
:func:`undo` reads that block and takes back only that: the claim, the closures (only where the claim still reads as
the settle left it) and the record; the question returns under its id, marked so no check settles it again.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import (bank_index, episode_ids, episode_scrub, inbox_questions, markdown_parser, predicates,
                          role_people, text_fold)

SOURCE = "web-check"
SETTLED_DIR = "settled"
ORIGIN = "web-check"
KINDS = ("conflict", "clarification")
#: The types a lookup may answer for: a work, product, tool, company or public concept (``media`` holds films, books,
#: papers, videos). Never ``person``, ``project``, ``directory``, ``location``, ``skill`` or ``deadline``.
PUBLIC_TYPES = frozenset({"company", "concept", "tool", "media"})
#: Predicates whose truth lives in the world rather than in the person's life — for a conflict, beside the vocabulary's
#: ``locus: world | artifact``. Anything else stays for the person.
PUBLIC_PREDICATES = frozenset({
    "description", "is-a", "type", "category", "kind", "genre", "made-by", "created-by", "developed-by", "built-by",
    "published-by", "authored-by", "author", "directed-by", "founded-by", "owned-by", "maintained-by", "released",
    "release-date", "released-in", "founded", "founded-in", "headquartered-in", "based-in", "located-in", "part-of",
    "runs-on", "written-in", "language", "license", "year", "website",
})
#: Generic words that may ride with a name to the search engine — and only these, at most one. Matched against Cicada's
#: own one-line description of the subject (local text; owner, 2026-10-16: never the page's type alone — a mistyped
#: place used to be searched as a "company" — and never on a question about what the thing is).
CATEGORY_WORDS = frozenset({
    "film", "movie", "documentary", "series", "show", "book", "novel", "paper", "article", "essay", "album", "song",
    "podcast", "game", "video", "anime", "manga", "comic", "play", "opera", "painting", "artwork", "magazine",
    "journal", "conference", "software", "library", "framework", "language", "tool", "app", "application", "platform",
    "service", "database", "protocol", "model", "dataset", "benchmark", "algorithm", "standard", "browser", "editor",
    "extension", "plugin", "api", "sdk", "cli", "agent", "harness", "company", "startup", "brand", "product", "robot",
    "robotics", "device", "hardware", "chip", "camera", "car", "theory", "concept", "method", "technique", "law",
    "university", "museum", "band", "studio", "publisher", "website", "newsletter", "blog",
    # Places and organisations (2026-10-19: a restaurant or a startup searched by its bare name found other things).
    "restaurant", "cafe", "bar", "pub", "bakery", "hotel", "hospital", "clinic", "gym", "shop", "cinema",
    "theatre", "theater", "gallery", "festival", "airline", "nonprofit", "foundation", "accelerator", "school",
    "channel", "framework", "organization", "organisation", "agency",
})
#: The same categories in Spanish (folded, accents off), sent as the English word: one vocabulary, either language.
_CATEGORY_SYNONYMS = {
    "restaurante": "restaurant", "cafeteria": "cafe", "clinica": "clinic", "empresa": "company", "pelicula": "film",
    "libro": "book", "banda": "band", "album": "album", "cancion": "song", "aplicacion": "app", "herramienta": "tool",
    "revista": "magazine", "universidad": "university", "museo": "museum", "gimnasio": "gym", "tienda": "shop",
    "serie": "series", "videojuego": "game", "juego": "game", "marca": "brand", "plataforma": "platform",
    "articulo": "article", "documental": "documentary", "escuela": "school", "colegio": "school",
    "fundacion": "foundation", "agencia": "agency", "pasteleria": "bakery", "panaderia": "bakery",
    "cine": "cinema", "teatro": "theatre", "galeria": "gallery", "aerolinea": "airline", "modelo": "model",
    "lenguaje": "language",
}
#: Words that read as verbs right after a name ("did <name> show up", "<name> play") or before it ("book <name> for
#: Friday"): taken from a mention line only after a determiner ("the book <name>", "<name>, a show about …").
_VERBISH_CATEGORIES = frozenset({"show", "play", "film", "book", "park", "fund", "harness", "benchmark", "video",
                                 "shop", "model", "standard", "law", "game", "series", "agent", "editor"})
#: What a thing IS — its type or description (owner, 2026-10-16: "Is <tool-a> an agent harness for running models or an
#: AI agent itself?" is the question a lookup exists for). Eligible even where the vocabulary marks the predicate
#: multi-valued (``is-a``): a page may say the subject is one of the options and rules the others out (that option
#: settles), or that it is all of them at once (the item's own "both" option settles). Never an option of our own.
TYPE_PREDICATES = frozenset({"is-a", "type", "kind", "category", "genre", "description"})
BOTH = "both"
#: The restored question remembers the person undid a check: it is never looked up or settled again (user authority).
UNDONE_KEY = "web_check"
MAX_CATEGORY_WORDS = 1
#: The local context a lookup's prompt carries (owner ruling 2026-10-16, amends ruling 27: "Yes, use local context"):
#: what Cicada already knows about the subject, to judge WHICH search result is the thing the person meant. Bounded,
#: scrubbed, people's names and paths taken out; never part of the query.
MAX_CONTEXT_CHARS = 600
MAX_MENTION_LINES = 2
MAX_LINE_CHARS = 220
MAX_DESCRIPTION_CHARS = 200
MAX_ANSWER_CHARS = 200
MAX_QUOTE_CHARS = 240
MAX_NAME_CHARS = 80

#: Words that say the subject is somebody, or the person's own — any one, in Cicada's own description of an untyped
#: subject or in the question, and the question stays for the person ("when in doubt, don't search").
_PERSON_CUES = re.compile(
    r"\b(he|she|him|his|her|hers|my|our|mine|me|i|we|us|friend|colleague|co-?worker|boss|manager|partner|wife|husband|"
    r"girlfriend|boyfriend|mom|mum|mother|dad|father|brother|sister|son|daughter|cousin|uncle|aunt|grandma|grandpa|"
    r"classmate|roommate|flatmate|teacher|professor|tutor|student|person|someone|somebody|guy|girl|man|woman|"
    r"client|customer|family|relative|neighbou?r|contact|people|team ?mate)\b",
    re.IGNORECASE,
)
#: A file, a path, a handle, an address: the person's own things, never searched.
_PRIVATE_NAME = re.compile(
    r"[/\\~@]|://|^\.|\.(md|txt|py|js|ts|swift|json|yaml|yml|toml|csv|xlsx?|docx?|pptx?|key|pages|numbers|pdf|png|"
    r"jpe?g|gif|heic|mov|mp4|zip|sh|rb|go|rs|java|kt|c|h|cpp|sql|ipynb|log)$",
    re.IGNORECASE,
)
#: "did PR #n merge", "is G<n> shipped": answered from the repo's history by a trusted local agent, never searched.
_REPO_STATE = re.compile(r"\b(?:PR|pull request)\s*#?\s*\d{1,6}\b|\bG\d{1,4}[a-z]?\b|#\d{1,6}\b", re.IGNORECASE)
_COMMIT_REF = re.compile(
    r"^(?:commit:[0-9a-f]{7,40}|https://(?:github\.com|gitlab\.com)/[\w.-]+/[\w.-]+/(?:-/)?(?:commit/[0-9a-f]{7,40}|"
    r"pull/\d{1,6}|merge_requests/\d{1,6}))$",
    re.IGNORECASE,
)


#: Stage 1's way of naming the speaker ("the user mentioned it", "a dataset the person is using"): who SAID it, not
#: who the subject is — taken out before :data:`_PERSON_CUES` reads Cicada's description of a page-less subject
#: (owner 2026-10-19: "Is <a public tool> an AI agent or an AI code editor? can be solved by an internet search").
_SPEAKER = re.compile(r"\bthe (?:person|user|speaker|owner|author)(?:['’]s)?\b", re.IGNORECASE)
#: …unless the description says the subject is the speaker's OWN (their project, file, repo, company): never searched.
_OWN_THING = re.compile(
    r"\b(?:built|created|made|wrote|written|designed|developed|authored|owned|started|founded|named|coined|led|run|"
    r"maintained) by the (?:person|user|speaker|owner)\b|"
    r"\bthe (?:person|user|speaker|owner)['’]s (?:own|project|file|repo|repository|"
    r"company|startup|team|app|work|code|script|document|notes?|side project|thesis|dataset|employer|job|workplace)\b|"
    r"\b(?:their|his|her) own\b|"
    # The active forms (review of #360): "an app the person is building", "the company where the user works".
    r"\b(?:person|user|speaker|owner)\s+(?:(?:is|was|has been|had been|are|were)\s+)?(?:currently\s+)?"
    r"(?:building|built|builds|develop(?:s|ed|ing)?|writ(?:es|ing)|wrote|creat(?:es|ed|ing)|mak(?:es|ing)|made|"
    r"maintain(?:s|ed|ing)?|lead(?:s|ing)?|led|run(?:s|ning)?|ran|work(?:s|ed|ing)? (?:on|at|for)|found(?:s|ed|ing)|"
    r"start(?:s|ed|ing)|own(?:s|ed)?|design(?:s|ed|ing)?)\b|"
    r"\bwhere the (?:person|user|speaker|owner)\s+(?:(?:is|was|has been)\s+)?(?:works?|worked|working|studies|"
    r"studied|studying)\b",
    re.IGNORECASE)
#: Cicada's own runtime settings — the engine a Sleep run reads with, whether scheduled runs use the plan, the
#: schedule's time (owner 2026-10-19: "Are scheduled Sleep runs still going through <provider>?" is the system's to
#: know). Narrow on purpose (review of #360): the owner's project IS Cicada, so its design questions — a hosting
#: provider, a settings page's layout, recall's search engine, the graph engine, whether Sleep runs nightly — stay his.
#: Only Cicada's own page, by its exact id; never a page that merely has the word in its name.
OWN_PAGE_ID = "cicada"
#: A Sleep run, as the question says it.
_OWN_RUNS = re.compile(r"\b(?:sleep|consolidation|scheduled|nightly) (?:runs?|cycles?|reads?)\b|\bscheduled runs?\b",
                       re.IGNORECASE)
#: What a Sleep run reads with: a plan, an API key, a local model — the engine choice itself.
_ENGINE_CHOICE = re.compile(
    r"\b(?:claude|chatgpt|codex) plan\b|\b(?:the|my|your|a) plan\b|\bsubscription\b|\bapi key\b|\blocal model\b|"
    r"\bollama\b|\bopenrouter\b|\blitellm\b|\bmetered\b", re.IGNORECASE)
#: A time of day, as a schedule's option.
_TIME_OF_DAY = re.compile(r"^\s*(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm|h)?\s*$|^\s*\d{1,2}:\d{2}\b", re.IGNORECASE)


def own_settings(fm: dict) -> bool:
    """A question about Cicada's OWN runtime settings, on Cicada's own page (exact id): which engine its Sleep runs read
    with (a run named in the question, an engine choice — a plan, an API key, a local model — among the question or its
    options), or what time the schedule runs (every option a time of day). Never searched and never asked
    (``inbox_tend``'s ``own_settings`` rule): Settings shows them, and a conversation that mentioned them stated that
    day's configuration, not a fact for the person to referee. Anything else about Cicada stays the person's."""
    if str(fm.get("entity_id") or "").strip().lower() != OWN_PAGE_ID:
        return False
    options = inbox_questions.normalize_options(fm.get("options"))
    labels = [str(o.get("label") or "") for o in options if str(o.get("key")) not in (BOTH, "neither")]
    question = " ".join([str(fm.get("question") or ""), str(fm.get("title") or "")])
    if _OWN_RUNS.search(question) and _ENGINE_CHOICE.search(" ".join([question, *labels])):
        return True
    return bool(re.search(r"\bschedul\w*", question, re.IGNORECASE)) and len(labels) >= 2 and all(
        _TIME_OF_DAY.search(label) for label in labels)


def person_context(description: str) -> bool:
    """Cicada's own description of a page-less subject says it is somebody, or the speaker's own thing. The speaker's
    own reference ("the user mentioned it") is not a cue: it says who spoke, not what the subject is."""
    text = description or ""
    if _OWN_THING.search(text):
        return True
    return bool(_PERSON_CUES.search(_SPEAKER.sub(" ", text)))


#: A conflict that asks about the person's own situation (2026-10-20: of nine settled conflicts, eight were the owner's
#: own — "which <accessory> am I using", "the <device> I'm modding", "in <owner>'s thesis", "currently uses …",
#: "planned for <owner's project>"). First and second person, English (the bare "I" and "us" in their own case: "US" is
#: a country) and Spanish (folded).
_FIRST_PERSON_CASED = re.compile(r"(?<![\w'’])(?:I|I['’](?:m|ve|d|ll)|us)(?![\w'’])")
_FIRST_PERSON = re.compile(
    r"\b(?:am i|i['’]m|my|me|mine|myself|we|we['’](?:re|ve|d|ll)|our|ours|ourselves|you|your|yours|yourself|"
    r"yo|mi|mis|mio|mia|mios|mias|conmigo|estoy|estamos|uso|usamos|tengo|tenemos|nuestr[oa]s?|"
    # Spanish second person (review of #368; "estas" — "these" — over-catches, accepted).
    r"tu|tus|tuyo|tuya|tuyos|tuyas|contigo|usted|ustedes|vos|usas|usaste|tienes|estas)\b",
    re.IGNORECASE)
#: Somebody's possessions and doings: who did it need not be named ("he uses", "the one bought last year", "installed
#: on the laptop", "dropped for <tool>").
_DOINGS = (r"bought|purchased|installed|modded|modding|dropped|abandoned|migrated|moved")
#: A state of somebody's life said about the thing: "currently uses", "planned for", "superseded by", "the owner was
#: interested in", "<someone>'s thesis", "he has", "i bought".
_SITUATION = re.compile(
    r"\b(?:currently|still|no longer)\s+(?:use[sd]?|using|run(?:s|ning)?|own(?:s|ed)?|ha(?:ve|s)|work(?:s|ing)?|"
    r"build(?:s|ing)?|develop(?:s|ing)?)\b|"
    r"\bplanned\s+(?:for|in)\b|\bsuperseded\s+by\b|\breplaced\s+by\b|\bswitched\s+to\b|"
    rf"\b(?:{_DOINGS})\b|"
    r"\b(?:i['’]m|i am|am i|we['’]re|are we)\s+(?:\w+\s+)?\w+ing\b|"
    r"\bi\s+(?:use[sd]?|ha(?:ve|d)|own(?:ed)?|got|run|ran|need|want(?:ed)?|tried|mod\w*)\b|"
    r"\b(?:he|she|they)\s+(?:\w+\s+)?(?:use[sd]?|using|ha(?:s|ve|d)|own(?:s|ed)?|bought|got|run|modd\w*)\b|"
    r"\b(?:does|did|do)\s+(?:he|she|they)\s+(?:\w+\s+)?(?:use|have|own|run|mod\w*)\b|"
    r"\b(?:usa|tiene)\s+en\s+su\b|"
    r"\bthe\s+(?:owner|user|person|speaker)\b(?![\s-]+(?:interface|experience|guide|manual|base|story|agent)\b)|"
    r"\bhome\s+(?:lab|server|setup|network)\b|"
    r"\w['’]s\s+(?:own\s+)?(?:code|codebase|thesis|dissertation|project|side project|lab|setup|homework|assignment|"
    r"repo|repository|notes|server|laptop|machine|computer|phone|desk)\b",
    re.IGNORECASE)
#: An option label that states a person's situation rather than what a thing is — never a page's description.
_SITUATION_LABEL = re.compile(
    r"^\s*(?:currently|still|no longer|formerly|previously|superseded|replaced|switched|planned|both|neither|"
    r"dropped|abandoned|uses?|used|migrated|moved|todav[ií]a|actualmente|ambos|ninguno)\b", re.IGNORECASE)
#: Two different things that share a name ("Is <term> the <method> or the <product>?", "Is this entity <A>, or <B>?",
#: "… or a separate <category>", "… or the class called `X`"): a lookup can say which thing the web means by the name,
#: never which one the person meant.
_DIFFERENT_THINGS = re.compile(
    r"\bthis (?:entity|page|thing|term|name)\b|\b(?:a|an|the) (?:separate|different|distinct|unrelated|other)\b|"
    r"\bsomething else\b|\b(?:called|named)\b|\brefers? to\b|\bsame (?:thing|one|entity)\b|"
    r"\bthe\b[^?]*\bor\s+(?:is it\s+)?the\b|\bor\s+(?:rather\s+)?(?:is it\s+)?another\b",
    re.IGNORECASE)
_LEADING_ARTICLE = re.compile(r"^(?:the|a|an|el|la|los|las|un|una)\s+")
#: A project name's first word is its distinctive head ("Alpha" for "Alpha Project") unless it is one of these.
_GENERIC_HEADS = frozenset("""the a an my our new old project projects app apps tool tools side personal open
    data web site home work team test demo""".split())


def _speaks_as_the_person(text: str) -> bool:
    return bool(_FIRST_PERSON_CASED.search(text or "") or _FIRST_PERSON.search(text_fold.fold(text or "")))


def _names_in(text: str, names: frozenset[str]) -> bool:
    """A name from ``names`` (folded) in ``text`` as whole words — 3+ characters, never a part of a word."""
    hay = f" {' '.join(_folded_words(text))} "
    return any(len(n) >= 3 and f" {' '.join(_folded_words(n))} " in hay for n in names)


def _short_alias_in(text: str, aliases: frozenset[str]) -> bool:
    """An owner's alias under 3 characters ("DQ") as a whole token, in its own case — "dq" in prose is not one."""
    return any(re.search(rf"(?<![\w'’]){re.escape(a)}(?![\w'’])", text or "") for a in aliases)


def _str_list(value) -> list[str]:
    return [x for x in value if isinstance(x, str)] if isinstance(value, (list, tuple, set, frozenset)) else []


def subject_names(fm: dict, page: dict | None) -> frozenset[str]:
    """The subject's own names, folded: the item's name, the page's name and aliases, its id read as words."""
    names = {fm.get("entity_name"), str(fm.get("entity_id") or "").replace("-", " ")}
    if isinstance(page, dict):
        names.add(page.get("name"))
        names.update(_str_list(page.get("aliases")))
    return frozenset(n for n in (" ".join(_folded_words(x)) for x in names if isinstance(x, str)) if n)


def names_the_subject(label, names: frozenset[str]) -> bool:
    """An option label that IS the subject's own name or alias (case and accents folded, an article aside)."""
    if not isinstance(label, str):
        return False
    folded = " ".join(_folded_words(_LEADING_ARTICLE.sub("", text_fold.fold(label).strip())))
    return bool(folded) and folded in names


def different_things(fm: dict) -> bool:
    """The conflict asks which of two different things sharing a name the subject is (cases 5–8, 2026-10-20)."""
    question = " ".join([str(fm.get("question") or ""), str(fm.get("title") or "")])
    return bool(_DIFFERENT_THINGS.search(question))


def _persons_own_claims(memory_path: Path | None, entity_id: str, claim_ids: list[str]) -> bool:
    """Every competing claim (2+) came from the person's own words — ``source_trust: user_stated`` or evidence only in
    their own turns: the conflict is about their own thing, whatever the question says (review of #368)."""
    if memory_path is None or len(claim_ids) < 2:
        return False
    from api.services.claims import parse_claims

    try:
        hit = bank_index.file(Path(memory_path), "entities", f"{entity_id}.md")
        claims = {c.id: c for c in parse_claims(hit.body() if hit is not None else "")}
    except Exception:  # noqa: BLE001 — unreadable claims say nothing either way
        return False
    found = [claims[cid] for cid in claim_ids if cid in claims]
    if len(found) < 2:
        return False

    def own(c) -> bool:
        kinds = {str(getattr(e, "kind", "") or "") for e in (c.evidence or [])}
        return c.source_trust == "user_stated" or (bool(kinds) and kinds <= {"user"})

    return all(own(c) for c in found)


def personal_conflict(fm: dict, page: dict | None, facts: "BankFacts", memory_path: Path | None = None) -> str | None:
    """Why a conflict is about the person rather than what a public thing IS — ``personal`` — or ``None``. A conflict is
    lookup-eligible only when nothing in its question, its option labels or the subject page ties it to the person:
    first or second person (English or Spanish), somebody's doings ("he uses", "bought", "dropped for …"), the owner's
    name, alias or any part of it, a person's or a project's page name (or a project's head word), "the owner/user",
    "<someone>'s thesis/code/lab/setup/server", a situation ("currently uses", "planned for", "superseded by"), an
    option label stating a situation, a page whose own description is the person's own or names them or their
    project, or competing claims that all came from the person's own words. Engine-free."""
    options = inbox_questions.normalize_options(fm.get("options"))
    labels = [o.get("label") if isinstance(o.get("label"), str) else "" for o in options
              if str(o.get("key")) not in (BOTH, "neither")]
    question = " ".join(x for x in (fm.get("question"), fm.get("title")) if isinstance(x, str))
    asked = " ".join([question, *labels])
    if _speaks_as_the_person(asked) or _SITUATION.search(asked):
        return "personal"
    if any(_SITUATION_LABEL.search(label) for label in labels):
        return "personal"
    own = subject_names(fm, page)
    own_words = {w for n in own for w in n.split()}
    # A name made only of the subject's own words is the subject talking, not the person ("<surname> Labs").
    tied = {n for n in (facts.owner_names | facts.person_names | facts.project_names) - own
            if not set(_folded_words(n)) <= own_words}
    if _names_in(asked, tied) or _short_alias_in(asked, facts.owner_short_aliases):
        return "personal"
    if isinstance(page, dict):
        described = " ".join(str(page.get(k) or "") for k in ("description", "summary"))
        if _OWN_THING.search(described) or _names_in(described, tied) \
                or _short_alias_in(described, facts.owner_short_aliases):
            return "personal"
    claim_ids = [str(o.get("claim_id")) for o in options if o.get("claim_id")]
    if _persons_own_claims(memory_path, str(fm.get("entity_id") or ""), claim_ids):
        return "personal"
    return None


class NotSettleable(ValueError):
    """The question cannot be settled this way; the reason is said in words and nothing was written."""


@dataclass
class BankFacts:
    """What the filter needs to know about the bank, read once: the owner's page and the names of every person."""

    owner_id: str | None = None
    person_names: frozenset[str] = frozenset()
    pages: dict[str, dict] = field(default_factory=dict)
    pending: frozenset[str] = frozenset()
    #: Sanitized id → the pending line's ``(description, source_episode)``: a page-less name's local context.
    pending_lines: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: The names of people held in the pending store (no page yet): redacted from the local context like any other.
    pending_person_names: frozenset[str] = frozenset()
    #: The owner's name, aliases and each part of them (3+ letters), folded: "<owner>'s thesis" keeps a conflict home.
    owner_names: frozenset[str] = frozenset()
    #: Every project page's name and aliases, and its distinctive head word ("Alpha" for "Alpha Project"), folded: a
    #: conflict that names one is about the person's own work.
    project_names: frozenset[str] = frozenset()
    #: The owner's aliases under 3 characters ("DQ"), in their own case: matched only as a whole token.
    owner_short_aliases: frozenset[str] = frozenset()


@dataclass
class Candidate:
    item_id: str
    kind: str
    scope: str                       # public | repo
    entity_id: str
    name: str
    entity_type: str
    has_page: bool
    predicate: str
    options: list[tuple[str, str]]   # (key, label)
    category: list[str]
    #: A type/description conflict (``TYPE_PREDICATES``): one option settles only when the page rules the others out.
    type_question: bool = False
    #: The item's own "both are true" option key, offered to a type question only — never one Cicada invents.
    both_key: str | None = None
    #: Cicada's own one-line description of the subject (local: the category word is read from it; a clarification's
    #: prompt carries it as context).
    description: str = ""
    #: Where the subject was mentioned, for the local context: the item's own episode, then each option claim's.
    source_episode: str = ""
    claim_ids: list[str] = field(default_factory=list)
    #: Where the category word came from: ``description``, ``context`` (:func:`context_category`) or ``""`` (none).
    category_from: str = ""
    #: Two different things sharing a name (:func:`different_things`): only an option that IS the subject's own name
    #: (``subject_names``) may settle it, never "both" (2026-10-20).
    different_things: bool = False
    subject_names: frozenset[str] = frozenset()


def _norm(text) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def _words(text) -> str:
    return " ".join(re.findall(r"\w+", str(text or "").lower()))


def _names_a_person(text, names: frozenset[str]) -> bool:
    """True when ``text`` carries a person's name or alias (the owner's included) as whole words — the subject and the
    option labels are what reach the engine, so a label like "built by <person> and her team" keeps the question home."""
    hay = f" {_words(text)} "
    for name in names:
        n = _words(name)
        if len(n) >= 3 and f" {n} " in hay:
            return True
    return False


def is_type_predicate(predicate) -> bool:
    return str(predicate or "").strip().lower() in TYPE_PREDICATES


def bank_facts(memory_path: Path) -> BankFacts:
    """Owner page, person names and aliases (and the owner's), page frontmatter, pending names — from the warm
    frontmatter cache. Never raises: an unreadable bank reads as one where nothing may be searched."""
    from api.services import pending_store
    from api.services.id_utils import sanitize_id

    facts = BankFacts()
    try:
        files = bank_index.files(Path(memory_path), "entities")
    except Exception:  # noqa: BLE001
        return facts
    names: set[str] = set()
    owner: set[str] = set()
    projects: set[str] = set()
    short: set[str] = set()
    for f in files:
        fm = f.frontmatter or {}
        facts.pages[f.stem] = fm
        is_owner = fm.get("owner") is True
        if is_owner and facts.owner_id is None:
            facts.owner_id = f.stem
        own_names = [_norm(fm.get("name")), *(_norm(a) for a in (fm.get("aliases") or []) if isinstance(a, str)),
                     _norm(f.stem.replace("-", " "))]
        if is_owner or str(fm.get("type") or "").lower() == "person":
            names.update(own_names)
        if is_owner:
            owner.update(own_names)
            owner.update(w for n in own_names for w in _folded_words(n) if len(w) >= 3)
            short.update(a.strip() for a in [fm.get("name"), *_str_list(fm.get("aliases"))]
                         if isinstance(a, str) and 2 <= len(a.strip()) < 3)
        if str(fm.get("type") or "").lower() == "project":
            projects.update(own_names)
            projects.update(words[0] for words in (_folded_words(n) for n in own_names)
                            if len(words) > 1 and len(words[0]) >= 3 and words[0] not in _GENERIC_HEADS
                            and words[0] not in text_fold.SUBJECT_STOPWORDS)
    names.discard("")
    facts.person_names = frozenset(names)
    facts.owner_names = frozenset(text_fold.fold(n) for n in owner if n)
    facts.project_names = frozenset(text_fold.fold(n) for n in projects if n)
    facts.owner_short_aliases = frozenset(short)
    try:
        lines = pending_store.load(Path(memory_path))
        facts.pending = frozenset(sanitize_id(line.name) for line in lines)
        facts.pending_lines = {sanitize_id(line.name): (str(line.description or ""), str(line.source_episode or ""))
                               for line in lines}
        facts.pending_person_names = frozenset(
            n for n in (_norm(line.name) for line in lines if str(line.type or "").lower() == "person") if n)
    except Exception:  # noqa: BLE001
        pass
    return facts


def _subject_type(fm: dict, page: dict | None) -> str:
    if page is not None:
        return str(page.get("type") or "").strip().lower()
    return str(fm.get("suggested_classification") or "").split(" ")[0].strip().lower()


def _local_description(fm: dict, page: dict | None, body: str) -> str:
    """Cicada's own words about the subject — read HERE to filter and to pick category words, never sent."""
    parts = [str(fm.get("suggested_classification") or ""), body or ""]
    if page is not None:
        parts.append(str(page.get("description") or page.get("summary") or ""))
    return " ".join(parts)


def classify(memory_path: Path, fm: dict, body: str, facts: BankFacts) -> tuple[str | None, str]:
    """``(scope, reason)``: ``public`` (a lookup may answer it), ``repo`` (a trusted local agent may, from the repo's
    history) or ``None`` with the enum that kept it for the person. Engine-free, network-free."""
    kind = str(fm.get("kind") or "")
    if kind not in KINDS:
        return None, "kind"
    if str(fm.get("status") or "pending") != "pending" or str(fm.get("asks") or "") == "name":
        return None, "kind"
    if fm.get(UNDONE_KEY) == "undone":
        return None, "undone"   # the person took a check's answer back: the question is theirs now
    entity_id = str(fm.get("entity_id") or "")
    name = " ".join(str(fm.get("entity_name") or "").split())
    if not entity_id or not name:
        return None, "no_subject"
    if entity_id == facts.owner_id:
        return None, "owner"
    page = facts.pages.get(entity_id)
    if page is not None and page.get("owner") is True:
        return None, "owner"
    options = inbox_questions.normalize_options(fm.get("options"))
    labels = [str(o.get("label") or "") for o in options]
    asked = " ".join([str(fm.get("question") or ""), str(fm.get("title") or ""), name, *labels])
    if _REPO_STATE.search(asked):
        stype = _subject_type(fm, page)
        if stype == "person" or _norm(name) in facts.person_names:
            return None, "person"
        return "repo", "repo_state"
    if own_settings(fm):
        return None, "own_settings"   # the system answers it (Settings), never a search, never the person
    stype = _subject_type(fm, page)
    if stype == "person" or str(fm.get("uncertainty_type") or "").lower().startswith("unknown relationship"):
        return None, "person"
    if _norm(name) in facts.person_names or _names_a_person(name, facts.person_names):
        return None, "person"
    if stype not in PUBLIC_TYPES:
        return None, "private_type"
    if page is not None and (page.get("path") or page.get("repos")):
        return None, "private_file"
    if len(name) > MAX_NAME_CHARS or len(name) < 2 or _PRIVATE_NAME.search(name):
        return None, "private_file"
    if page is None and person_context(_local_description(fm, None, body)):
        return None, "person_context"
    question = " ".join([str(fm.get("question") or ""), str(fm.get("title") or "")])
    if re.search(r"\b(you|your|yours)\b", question, re.IGNORECASE):
        return None, "personal"
    sent_labels = [str(o.get("label") or "") for o in options if str(o.get("key")) not in (BOTH, "neither")]
    if any(_norm(label) in facts.person_names or _names_a_person(label, facts.person_names)
           for label in sent_labels if label):
        return None, "person"
    if any(_PERSON_CUES.search(label) for label in sent_labels if label):
        return None, "personal"   # an option label is sent with the question: "my", "her friend"... stays home
    if kind == "conflict":
        # A lookup answers what a public thing IS, never the person's situation (2026-10-20, rulings 27/27b).
        tie = personal_conflict(fm, page, facts, memory_path)
        if tie:
            return None, tie
        # Two things sharing a name: only an option that IS the subject's own name may settle; with none, it stays.
        if different_things(fm) and not any(names_the_subject(label, subject_names(fm, page))
                                            for label in sent_labels):
            return None, "different_things"
        predicate = str(fm.get("predicate") or "")
        # A multi-valued predicate's values coexist, so there is nothing to settle — except what the thing IS: a page
        # may rule an option out, or say it is both (owner, 2026-10-16).
        if predicates.cardinality(memory_path, predicate) == "multi" and not is_type_predicate(predicate):
            return None, "informational"
        locus = predicates.locus(memory_path, predicate)
        if locus == "person" or (locus == "unknown" and predicate.lower() not in PUBLIC_PREDICATES):
            return None, "private_predicate"
        if len([o for o in options if str(o.get("key")) not in ("both", "neither")]) < 2:
            return None, "no_options"
    if page is None and entity_id not in facts.pending:
        return None, "no_page"
    return "public", "public"


def _one_liner(text, limit: int = MAX_DESCRIPTION_CHARS) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit - 1)
    return text[: cut if cut > 0 else limit - 1].rstrip(" ,;:") + "…"


def _summary_line(body: str) -> str:
    """The first prose line of a page's ``## Summary`` (or of its body, when it has none) — never a heading, a list
    marker's bullet aside, or the claims fence."""
    text = body or ""
    m = re.search(r"^##\s+Summary\s*$", text, re.MULTILINE | re.IGNORECASE)
    if m:
        text = text[m.end():]
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("#", "```", "<!--", "|")):
            if m:
                break   # the Summary section ended without a prose line
            continue
        return line.lstrip("-*• ").strip()
    return ""


def description_for(fm: dict, page: dict | None, page_body: str = "", pending: tuple[str, str] | None = None) -> str:
    """Cicada's own one-line description of the subject: the page's ``description``/``summary``, else its Summary's
    first line; for a page-less name, the item's suggested classification (its words after the type) or the pending
    line's description. Local text — the category word is read from it; it is never the query."""
    if page is not None:
        own = str(page.get("description") or page.get("summary") or "").strip() or _summary_line(page_body)
        return _one_liner(own)
    suggested = str(fm.get("suggested_classification") or "")
    words = re.split(r"\s+[—–-]\s+", suggested, maxsplit=1)
    own = words[1] if len(words) == 2 else ""
    if not own and pending:
        own = pending[0]
    return _one_liner(own)


def category_word(token: str) -> str | None:
    """``token`` as a word of :data:`CATEGORY_WORDS` — itself, its plural, or its Spanish form — else ``None``."""
    t = text_fold.fold(token)
    for form in (t, t[:-1] if t.endswith("s") else "", t[:-2] if t.endswith("es") else ""):
        if not form:
            continue
        if form in CATEGORY_WORDS:
            return form
        if form in _CATEGORY_SYNONYMS:
            return _CATEGORY_SYNONYMS[form]
    return None


def _label_carries(word: str, labels: list[str]) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", text_fold.fold(" ".join(labels))))


#: A description that only guesses ("possibly a software library", "a tool or a film") gives no category word
#: (2026-10-19: Stage 1's guess sent "Frieren software", and the pinned query could only find the wrong thing).
_HEDGE = re.compile(r"\b(?:possibly|perhaps|maybe|might|may be|probably|likely|unclear|unknown|unsure|either|"
                    r"or|seems?|appears?|presumably|posiblemente|quizas?|tal vez|probablemente|o)\b", re.IGNORECASE)
#: Words that say nothing a search can use, however a description puts them: every page is "a concept" to Stage 1.
_EMPTY_CATEGORIES = frozenset({"concept", "theory"})


def _usable(word: str | None, name: str, labels: list[str]) -> bool:
    """A category word may ride with the name: not empty of meaning, not already in the name ("arXiv paper <id>"
    never becomes "… paper"), not a word an option label carries."""
    return bool(word) and word not in _EMPTY_CATEGORIES and word not in _folded_words(name) \
        and not _label_carries(word, labels)


def _category(description: str, *, type_question: bool, labels: list[str], name: str = "") -> list[str]:
    """At most ONE generic word from :data:`CATEGORY_WORDS` found in Cicada's own description; none when unsure — a bare
    name is a valid query. Never from the page's type alone (Sleep's type is what a type conflict doubts), never on a
    question about what the thing IS (the word would answer it), never from a description that only guesses
    (:data:`_HEDGE`), never a word the name already carries or an option label carries."""
    if type_question or _HEDGE.search(description or ""):
        return []
    for token in re.findall(r"\w+", text_fold.fold(description or "")):
        word = category_word(token)
        if word:
            return [word] if _usable(word, name, labels) else []
    return []


_DETERMINERS = r"(?<!\w)(?:a|an|the|this|that|un|una|el|la|al|del|este|esta|ese|esa)"
_COPULA = r"(?:is|was|'s|’s|es|era|fue|are|were|son)"
_NAMING = r"(?:called|named|llamad[oa]s?)"


def context_category(c: "Candidate", context: list[str]) -> list[str]:
    """When Cicada's own description gave no category word, ONE word from the lines where the subject was mentioned
    (2026-10-19: "<a restaurant name>" searched alone found other things while the line said "a restaurant") — a fixed
    vocabulary (:data:`CATEGORY_WORDS`), matched beside the subject's own name, no model: "the restaurant <name>", "a
    startup called <name>", "<name>, a small café", "<name> is a band", "<name> restaurant". The same limits as
    :func:`_category`: none on a question about what the thing IS, none an option label carries, none when unsure.
    Only the vocabulary word can leave the machine; the line never does."""
    if c.type_question:
        return []
    labels = [label for _, label in c.options]
    parts = re.findall(r"\w+", text_fold.fold(c.name))
    if not parts:
        return []
    name = r"(?<!\w)" + r"[\s\-_.'’]+".join(re.escape(p) for p in parts) + r"(?!\w)"
    for line in context:
        if not line.startswith("Mentioned: "):
            continue
        text = text_fold.fold(line[len("Mentioned: "):])
        found: list[str] = []
        # "<name>, a small café" / "<name> is a band" / "<name> (a startup)": the first vocabulary word within four
        # words of the determiner, before any punctuation ends the phrase.
        for m in re.finditer(name + rf"\s*[,(:—–-]?\s*(?:{_COPULA}\s+)?{_DETERMINERS}\s+([\w'’\- ]+)", text):
            for token in m.group(1).split()[:4]:
                word = category_word(token)
                if word:
                    found.append(word)
                    break
        # "the restaurant <name>", "a startup called <name>", "the new app <name>": a determiner within two words.
        before = rf"{_DETERMINERS}\s+(?:(?!{_NAMING}\b)\w+\s+)?(?!{_NAMING}\b)(\w+)\s+(?:{_NAMING}\s+)?"
        for m in re.finditer(before + name, text):
            word = category_word(m.group(1))
            if word:
                found.append(word)
        # "<name> restaurant", "<name> app": the next word, unless it reads as a verb there.
        for m in re.finditer(name + r"\s+(\w+)", text):
            word = category_word(m.group(1))
            if word and word not in _VERBISH_CATEGORIES:
                found.append(word)
        for word in found:
            if _usable(word, c.name, labels):
                return [word]
    return []


def candidate(memory_path: Path, item_path: Path, facts: BankFacts) -> Candidate | None:
    try:
        parsed = markdown_parser.parse(item_path)
    except Exception:  # noqa: BLE001
        return None
    fm = parsed.frontmatter
    scope, _ = classify(memory_path, fm, parsed.body, facts)
    if scope is None:
        return None
    entity_id = str(fm.get("entity_id") or "")
    page = facts.pages.get(entity_id)
    etype = _subject_type(fm, page)
    raw_options = inbox_questions.normalize_options(fm.get("options"))
    options = [(str(o.get("key")), str(o.get("label") or "")) for o in raw_options
               if str(o.get("key")) not in (BOTH, "neither")]
    type_question = fm.get("kind") == "conflict" and is_type_predicate(fm.get("predicate"))
    both_key = BOTH if type_question and any(str(o.get("key")) == BOTH for o in raw_options) else None
    page_body = ""
    if page is not None:
        try:
            hit = bank_index.file(Path(memory_path), "entities", f"{entity_id}.md")
            page_body = hit.body() if hit is not None else ""
        except Exception:  # noqa: BLE001
            page_body = ""
    description = description_for(fm, page, page_body, facts.pending_lines.get(entity_id))
    claim_ids: list[str] = []
    for cid in [o.get("claim_id") for o in raw_options] + [fm.get("claim_id")]:
        cid = str(cid or "").strip()
        if cid and cid not in claim_ids:
            claim_ids.append(cid)
    labels = [label for _, label in options] if fm.get("kind") == "conflict" else []
    name = " ".join(str(fm.get("entity_name") or "").split())
    category = _category(description, type_question=type_question, labels=labels, name=name)
    return Candidate(
        item_id=item_path.stem, kind=str(fm.get("kind")), scope=scope, entity_id=entity_id,
        name=" ".join(str(fm.get("entity_name") or "").split()), entity_type=etype, has_page=page is not None,
        predicate=str(fm.get("predicate") or ("" if fm.get("kind") == "conflict" else "description")),
        options=options if fm.get("kind") == "conflict" else [],
        category=category, type_question=type_question,
        both_key=both_key, description=description, source_episode=str(fm.get("source_episode") or "").strip(),
        claim_ids=claim_ids, category_from="description" if category else "",
        different_things=fm.get("kind") == "conflict" and different_things(fm),
        subject_names=subject_names(fm, page),
    )


#: Clarifications ("what is X") first: the most answerable kind. Conflicts after (owner brief, 2026-10-16: the first
#: run's eight picks were all conflicts and none settled).
KIND_ORDER = {"clarification": 0, "conflict": 1}


def candidates(memory_path: Path, *, scope: str = "public", facts: BankFacts | None = None) -> list[Candidate]:
    """Pending questions of ``scope``: clarifications before conflicts, then highest priority first (then oldest),
    deferred ones left out. ``web_lookup`` refines the conflicts' order by their local context."""
    from api.services import inbox_service

    memory_path = Path(memory_path)
    facts = facts or bank_facts(memory_path)
    visible = {i.id for i in inbox_service.load_inbox(memory_path)}
    out: list[tuple[float, str, Candidate]] = []
    for path in sorted((memory_path / "inbox").glob("inbox-*.md")):
        if path.stem not in visible:
            continue
        c = candidate(memory_path, path, facts)
        if c is not None and c.scope == scope:
            fm = markdown_parser.parse(path).frontmatter
            out.append((-float(fm.get("priority") or 0.0), str(fm.get("created_date") or ""), c))
    out.sort(key=lambda t: (KIND_ORDER.get(t[2].kind, 2), t[0], t[1]))
    return [c for _, _, c in out]


def census(memory_path: Path, facts: BankFacts | None = None) -> dict:
    """What a lookup may answer in the open inbox, counted: per kind, how many are ``public`` (a lookup may answer
    them), ``repo_state`` (a trusted local agent may), or kept for the person and why (:func:`classify`'s enum).
    Counts and enums only — never an id, a name or a word. Engine-free, network-free."""
    from api.services import inbox_service

    memory_path = Path(memory_path)
    facts = facts or bank_facts(memory_path)
    visible = {i.id for i in inbox_service.load_inbox(memory_path)}
    by_kind: dict[str, dict[str, int]] = {}
    other = 0
    for path in sorted((memory_path / "inbox").glob("inbox-*.md")):
        if path.stem not in visible:
            continue
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — an unreadable item is counted, never searched
            by_kind.setdefault("unreadable", {})["unreadable"] = by_kind.get("unreadable", {}).get("unreadable", 0) + 1
            continue
        kind = str(parsed.frontmatter.get("kind") or "")
        if kind not in KINDS:
            other += 1
            continue
        _scope, reason = classify(memory_path, parsed.frontmatter, parsed.body, facts)
        row = by_kind.setdefault(kind, {})
        row[reason] = row.get(reason, 0) + 1
    return {"by_kind": {k: dict(sorted(v.items())) for k, v in sorted(by_kind.items())},
            "public": sum(v.get("public", 0) for v in by_kind.values()),
            "other_kinds": other}


def query_for(c: Candidate) -> str:
    """The ONE thing that leaves the machine for a lookup: the subject's name and generic category words."""
    return " ".join([c.name, *c.category]).strip()


# --------------------------------------------------------------------------- the writer


def _one_line(text, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit].rstrip()


def clean_quote(raw) -> str:
    text, n = episode_scrub.scrub(_one_line(raw, MAX_QUOTE_CHARS).lstrip("> ").strip())
    episode_scrub.record("mcp", n)
    return text


def check_ref(ref: str, scope: str) -> tuple[str, str]:
    """``(ref, host)`` for a citation, or :class:`NotSettleable`. A public answer cites a public web page (never a
    login wall, never a page an agent may not be handed); a repo answer cites a commit or a pull request."""
    from api.services import reading_hosts

    ref = str(ref or "").strip()
    if scope == "repo":
        if not _COMMIT_REF.match(ref):
            raise NotSettleable("A repository answer cites its commit: `commit:<sha>` or the commit or pull "
                                "request's own link.")
        host = reading_hosts.display_host(reading_hosts.host_of(ref)) if "://" in ref else "git"
        return ref, host or "git"
    if not ref.lower().startswith(("https://", "http://")):
        raise NotSettleable("The answer needs the link of the page it came from.")
    verdict = reading_hosts.classify(ref)
    if not verdict.ok or verdict.walled:
        raise NotSettleable("That page is not a public page Cicada may cite. Find the answer on a public page.")
    return ref, reading_hosts.display_host(verdict.host) or "page"


@dataclass
class Settled:
    item_id: str
    entity_id: str
    claim_id: str
    episode_id: str
    paths: list[str]
    lines: list[str]


def _claim_id(entity_id: str, predicate: str, obj: str, today: str) -> str:
    digest = hashlib.sha1(f"{entity_id}\x00{predicate}\x00{obj}\x00web\x00{today}".encode("utf-8")).hexdigest()[:8]
    return f"clm_{today}_web_{digest}"


def _write_episode(memory_path: Path, *, c: Candidate, ref: str, host: str, quote: str, checker_label: str,
                   checker_kind: str, origin: str, session_frontmatter: dict | None) -> str:
    verb = (f"Checked {c.name} in the repository's history." if c.scope == "repo"
            else f"Looked up {c.name} on the web.")
    body = "\n".join([f"assistant: {verb}", "", f"attachment [{host}]: as {checker_label} read it at {ref}",
                      f"> {quote}"])
    content_hash = hashlib.sha256(f"{c.item_id}\x00{ref}\x00{body}".encode("utf-8")).hexdigest()[:12]
    episodes_dir = memory_path / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    fm = {
        "id": episode_ids.next_episode_id(episodes_dir, date.today().isoformat()),
        "timestamp": episode_ids.utc_now_iso(),
        "source": SOURCE,
        "origin": origin,
        "title": f"Web check: {c.name}"[:120],
        "processed": True,
        "processed_by": "agent",
        "content_hash": content_hash,
        "checked_ref": ref,
        "checked_host": host,
        "item_id": c.item_id,
        "entity_id": c.entity_id,
        "checker_kind": checker_kind,
        **(session_frontmatter or {}),
    }
    return episode_ids.create_episode(episodes_dir, fm, body)


def _evidence_for(memory_path: Path, episode_id: str, quote: str):
    from api.services import evidence as ev
    from api.services.claims import Evidence

    text = ev.source_text(memory_path, episode_id) or ""
    hit = ev.locate(text, quote)
    if hit is None:   # provenance never blocks memory (G118): the claim is still written
        return [ev.reasoning(episode_id, hash=ev.body_hash(text))]
    return [Evidence(episode=episode_id, start=hit[0], end=hit[1], kind="page", hash=ev.body_hash(text))]


def settle(
    memory_path: Path, item_id: str, *, ref: str, quote: str, option_key: str | None = None, answer: str | None = None,
    checker: str, checker_kind: str, origin: str = "sleep", scopes: tuple[str, ...] = ("public",),
    engine: str | None = None, session_frontmatter: dict | None = None, facts: BankFacts | None = None,
) -> Settled:
    """Settle one question with a cited answer. The caller holds the bank (Sleep's window, or admission + page lock),
    has checked its gates, and commits ``paths``. Raises :class:`NotSettleable` with nothing written."""
    from api.services import pending_store
    from api.services.claims import Claim, MalformedClaimsBlockError, is_event, parse_claims, write_claims

    memory_path = Path(memory_path)
    item_path = memory_path / "inbox" / f"{item_id}.md"
    if not item_path.exists():
        raise NotSettleable("That question is no longer open.")
    facts = facts or bank_facts(memory_path)
    c = candidate(memory_path, item_path, facts)
    if c is None or c.scope not in scopes:
        raise NotSettleable("That question is not one a lookup may answer: it is about a person, the person's own "
                            "files, projects or life, or something only their conversations know. It stays for them.")
    ref, host = check_ref(ref, c.scope)
    quote = clean_quote(quote)
    if not quote:
        raise NotSettleable("The answer needs a short quote from the page, in its own words.")
    today = date.today().isoformat()
    parsed_item = markdown_parser.parse(item_path)
    fm_item = parsed_item.frontmatter
    option_claim: str | None = None
    both = False
    if c.kind == "conflict":
        key = str(option_key or "").strip()
        if c.different_things:
            chosen = next((label for k, label in c.options if k == key), None)
            if chosen is None or not names_the_subject(chosen, c.subject_names):
                # Another thing that shares the name: its description never goes on this page (2026-10-20).
                raise NotSettleable("The name belongs to different things and the answer is not this page's own "
                                    "name; the question stays for the person.")
        if c.both_key and key == c.both_key:
            # The page says the subject is all of these at once: every option holds, nothing closes.
            both = True
            objs = [_one_line(label, MAX_ANSWER_CHARS) for _, label in c.options]
        else:
            chosen = next(((k, label) for k, label in c.options if k == key), None)
            if chosen is None:
                raise NotSettleable("A conflict is settled by one of its own options: give its key.")
            objs = [_one_line(chosen[1], MAX_ANSWER_CHARS)]
            option_claim = next((str(o.get("claim_id")) for o in inbox_questions.normalize_options(
                fm_item.get("options")) if str(o.get("key")) == key and o.get("claim_id")), None)
    else:
        obj, n = episode_scrub.scrub(_one_line(answer, MAX_ANSWER_CHARS))
        episode_scrub.record("mcp", n)
        if not obj:
            raise NotSettleable("A 'what is it' question is settled by a short answer (at most 200 characters).")
        objs = [obj]
    objs = [o for o in dict.fromkeys(objs) if o]
    if not objs:
        raise NotSettleable("A conflict is settled by one of its own options: give its key.")
    if c.kind == "conflict" and any(_SITUATION_LABEL.search(o) or _speaks_as_the_person(o) or _SITUATION.search(o)
                                    for o in objs):
        # "Currently uses …", "Superseded by …", "Both are true …": a person's situation, never a page's description.
        raise NotSettleable("That option says how things stand for the person, not what the thing is; it stays "
                            "for them.")
    predicate = predicates.load_normalizer(memory_path)(c.predicate) or c.predicate or "description"
    label = checker if checker and checker != "agent" else "an agent"
    episode_id = _write_episode(memory_path, c=c, ref=ref, host=host, quote=quote, checker_label=label,
                                checker_kind=checker_kind, origin=origin, session_frontmatter=session_frontmatter)
    paths = [f"episodes/{episode_id}.md"]
    evidence = _evidence_for(memory_path, episode_id, quote)
    new_claims = [Claim(
        id=_claim_id(c.entity_id, predicate, obj, today), text=predicates.predicate_phrase(predicate, c.name, obj),
        subject=c.entity_id, predicate=predicate, object=obj, object_kind="literal", observer="agent",
        source_trust="external", origin=ORIGIN, authored_by=checker or "agent", confidence=0.8,
        valid_from=today, recorded_at=today, evidence=list(evidence),
    ) for obj in objs]
    claim = new_claims[0]
    closed: list[dict] = []
    held = False
    entity_path = memory_path / "entities" / f"{c.entity_id}.md"
    try:
        if entity_path.exists():
            page = markdown_parser.parse(entity_path)
            try:
                claims = parse_claims(page.body, strict=True)
            except MalformedClaimsBlockError as exc:
                raise NotSettleable("The page's claims could not be read; the question stays for the person.") from exc
            if any(x.id == n.id for x in claims for n in new_claims):
                raise NotSettleable("That answer is already on the page.")
            if c.kind == "conflict" and not both:
                option_ids = {str(o.get("claim_id")) for o in inbox_questions.normalize_options(fm_item.get("options"))
                              if o.get("claim_id")}
                for old in claims:
                    # An event (`happened`/`milestone`) is closed only by `progress.py` (G141): never here.
                    if (old.id in option_ids and old.id != option_claim and old.valid_to is None
                            and not is_event(old)):
                        before = old.to_dict()
                        old.valid_to = today
                        old.superseded_by = claim.id
                        closed.append({"id": old.id, "before": json.dumps(before, sort_keys=True),
                                       "after": json.dumps(old.to_dict(), sort_keys=True)})
            claims.extend(new_claims)
            markdown_parser.write(entity_path, page.frontmatter, write_claims(page.body, claims))
            paths.append(f"entities/{c.entity_id}.md")
        else:
            out = pending_store.hold(memory_path, {c.entity_id: list(new_claims)})
            if not out.get(c.entity_id) or out[c.entity_id].held < 1:
                raise NotSettleable("The name has no page and nothing held for it yet; the question stays.")
            held = True
            paths.append(pending_store.PENDING_STORE_FILE)
    except BaseException:
        (memory_path / "episodes" / f"{episode_id}.md").unlink(missing_ok=True)
        bank_index.invalidate(memory_path)
        raise
    settled_dir = memory_path / "inbox" / SETTLED_DIR
    settled_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "at": episode_ids.utc_now_iso(), "by": checker or "agent", "by_kind": checker_kind, "scope": c.scope,
        "ref": ref, "host": host, "quote": quote, "answer": " and ".join(objs), "predicate": predicate,
        "entity_id": c.entity_id, "entity_name": c.name, "claim_id": claim.id,
        "claim_ids": [n.id for n in new_claims], "episode": episode_id,
        "held": held, "closed": closed,
        **({"option_key": option_key} if c.kind == "conflict" else {}),
        **({"engine": engine} if engine else {}),
    }
    markdown_parser.write(settled_dir / f"{item_id}.md", {**fm_item, "settled": record}, parsed_item.body)
    item_path.unlink()
    bank_index.invalidate(memory_path)
    paths += [f"inbox/{item_id}.md", f"inbox/{SETTLED_DIR}/{item_id}.md"]
    trigger = "sleep/web-check" if origin == "sleep" else f"mcp/{checker or 'agent'}"
    lines = [f"episodes/{episode_id}.md: created (source: {item_id}, trigger: {trigger})",
             (f"entities/{c.entity_id}.md: updated (source: {episode_id}, trigger: {trigger})" if not held
              else f"{pending_store.PENDING_STORE_FILE}: updated (source: {episode_id}, trigger: {trigger})"),
             f"inbox/{item_id}.md: settled (source: {episode_id}, trigger: {trigger})"]
    return Settled(item_id=item_id, entity_id=c.entity_id, claim_id=claim.id, episode_id=episode_id,
                   paths=paths, lines=lines)


# --------------------------------------------------------------------------- the list and the undo


def list_settled(memory_path: Path) -> list[dict]:
    """The settled lists, newest first: "Settled by a check" (``group: check``) — what each check answered, from
    where, and what it wrote — and "Settled by Sleep" (``group: sleep``, ruling 29) — what Sleep answered or assumed
    and by which rule."""
    out: list[dict] = []
    settled_dir = Path(memory_path) / "inbox" / SETTLED_DIR
    # ``ctx-*``: a light-context lookup's record (owner ruling 44, ``web_context``) — undone by ``web_context.undo``.
    for path in [*settled_dir.glob("inbox-*.md"), *settled_dir.glob("ctx-*.md")]:
        try:
            parsed = markdown_parser.parse(path)
        except Exception as exc:  # noqa: BLE001 — one unreadable record never hides the others
            logger.warning(f"settled record skipped: {path.name}: {type(exc).__name__}")
            continue
        fm = parsed.frontmatter
        rec = fm.get("settled") if isinstance(fm.get("settled"), dict) else None
        if rec is None:
            continue
        entity_id = str(rec.get("entity_id") or "")
        group = str(rec.get("group") or "check")
        quote, episode = str(rec.get("quote") or ""), str(rec.get("episode") or "")
        if group == "sleep":
            # Ruling 29: Sleep's settle keeps a span into the person's words, never a copy; read through it here.
            from api.services import inbox_tend

            quote, episode = inbox_tend.quote_for(memory_path, rec)
        out.append({
            "id": path.stem, "kind": str(fm.get("kind") or ""), "question": str(fm.get("question") or fm.get("title")
                                                                                  or ""),
            "entity_id": entity_id, "entity_name": str(rec.get("entity_name") or fm.get("entity_name") or ""),
            "answer": str(rec.get("answer") or ""), "predicate": str(rec.get("predicate") or ""),
            "ref": str(rec.get("ref") or ""), "host": str(rec.get("host") or ""),
            "quote": quote, "settled_at": str(rec.get("at") or ""),
            "settled_by": str(rec.get("by") or ""), "settled_by_kind": str(rec.get("by_kind") or ""),
            "scope": str(rec.get("scope") or "public"), "claim_id": str(rec.get("claim_id") or ""),
            "episode": episode, "held": bool(rec.get("held")),
            "has_page": (Path(memory_path) / "entities" / f"{entity_id}.md").exists(),
            "group": group, "rule": str(rec.get("rule") or ""), "reason": str(rec.get("reason") or ""),
        })
    out.sort(key=lambda r: r["settled_at"], reverse=True)
    return out


def undo(memory_path: Path, item_id: str) -> tuple[str, list[str], list[str]]:
    """Take back one settle: withdraw its claim, reopen what it closed (only a claim still as the settle left it), put
    the question back. Returns ``(restored item id, paths, manifest lines)``; :class:`NotSettleable` when there is
    no such record. The episode stays — it is what the lookup read, and git and the timeline keep it either way."""
    from api.services import inbox_service, pending_store
    from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims

    memory_path = Path(memory_path)
    if not re.fullmatch(r"inbox-\d{3,}", item_id or ""):
        raise NotSettleable("No such settled question.")
    rec_path = memory_path / "inbox" / SETTLED_DIR / f"{item_id}.md"
    if not rec_path.exists():
        raise NotSettleable("No such settled question.")
    parsed = markdown_parser.parse(rec_path)
    fm = dict(parsed.frontmatter)
    rec = fm.pop("settled", None)
    if not isinstance(rec, dict) or rec.get("group") == "sleep":   # Sleep's own settle: `inbox_tend.undo`
        raise NotSettleable("No such settled question.")
    entity_id = str(rec.get("entity_id") or "")
    claim_ids = {str(x) for x in (rec.get("claim_ids") or [rec.get("claim_id")]) if x}
    paths: list[str] = []
    lines: list[str] = []
    entity_path = memory_path / "entities" / f"{entity_id}.md"
    page = claims = None
    if entity_path.exists():
        # Read (and refuse on) the page before anything is written, so a refusal really changed nothing.
        page = markdown_parser.parse(entity_path)
        try:
            claims = parse_claims(page.body, strict=True)
        except MalformedClaimsBlockError as exc:
            raise NotSettleable("The page's claims could not be read; nothing was changed.") from exc
    # A held claim may have reached its page since (the name was promoted): both places are looked at.
    unheld = [cid for cid in sorted(claim_ids) if pending_store.unhold(memory_path, entity_id, cid)]
    if unheld:
        paths.append(pending_store.PENDING_STORE_FILE)
        lines.append(f"{pending_store.PENDING_STORE_FILE}: updated (source: {item_id}, trigger: inbox/web-check/undone)")
    if page is not None and claims is not None:
        kept = [x for x in claims if x.id not in claim_ids]
        changed = len(kept) != len(claims)
        closed = {str(r.get("id")): r for r in (rec.get("closed") or []) if isinstance(r, dict)}
        for i, x in enumerate(kept):
            row = closed.get(x.id)
            if row and json.dumps(x.to_dict(), sort_keys=True) == row.get("after"):
                kept[i] = Claim.from_dict(json.loads(row["before"]))
                changed = True
        if changed:
            markdown_parser.write(entity_path, page.frontmatter, write_claims(page.body, kept))
            paths.append(f"entities/{entity_id}.md")
            lines.append(f"entities/{entity_id}.md: updated (source: {item_id}, trigger: inbox/web-check/undone)")
    inbox_dir = memory_path / "inbox"
    target = item_id
    if (inbox_dir / f"{target}.md").exists():   # never replace a question that took the number since
        target = f"inbox-{inbox_service.next_inbox_num(inbox_dir):03d}"
    # The question comes back as it was, plus one mark: the person took this answer back, so no check settles it again.
    markdown_parser.write(inbox_dir / f"{target}.md", {**fm, UNDONE_KEY: "undone"}, parsed.body)
    rec_path.unlink()
    bank_index.invalidate(memory_path)
    paths += [f"inbox/{target}.md", f"inbox/{SETTLED_DIR}/{item_id}.md"]
    lines += [f"inbox/{target}.md: reopened (source: {item_id}, trigger: inbox/web-check/undone)"]
    return target, paths, lines


def commit_message(subject: str, lines: list[str], *, authors: list[str], engine: str | None = None,
                   sessions: list[str] | None = None) -> str:
    from api.services import git_service

    return git_service.build_commit_message(f"{subject} {date.today().isoformat()}", lines, authors=authors,
                                            sessions=sessions, engine=engine)


def commit_sync(memory_path: Path, message: str, paths: list[str], *,
                before: dict[str, bytes | None] | None = None) -> bool:
    """Commit exactly ``paths`` (a moved item's old path as its removal). False when the bank has no git. ``before``
    (``git_service.snapshot_dirty``): an edit already on one of these paths is committed apart first, never as ours."""
    from api.services import git_service

    if not (Path(memory_path) / ".git").exists():
        return False
    kept = ({"kept_subject": f"Uncommitted edit kept apart {date.today().isoformat()}",
             "kept_trigger": "inbox/kept-apart"} if before is not None else {})
    git_service.commit_touched_sync(memory_path, message, paths, before=before, **kept)
    return True


def record_event(memory_path: Path, *, action: str, item_id: str, entity_id: str | None, by_kind: str,
                 reason: str | None = None, engine: str | None = None, harness: str | None = None) -> None:
    """One ``web_check`` ledger row: ids and enums only — never the query, the link, its host or the quote."""
    from api.services import telemetry

    refs = {"action": action, "item_id": item_id, "entity_id": entity_id, "by": by_kind, "reason": reason,
            "harness": harness}
    try:
        telemetry.record(telemetry.UsageEvent(
            kind=telemetry.WEB_CHECK_KIND, stage="web_check", connection=None, engine=engine, model=None,
            bank=Path(memory_path).name, billing="free", invocations=0,
            refs={k: v for k, v in refs.items() if v is not None},
        ))
    except Exception as exc:  # noqa: BLE001 — a ledger row never fails a settle
        logger.debug(f"web_check ledger row skipped: {type(exc).__name__}")


# --------------------------------------------------------------------------- the local context (owner, 2026-10-16)

_URL_RE = re.compile(r"\b(?:https?|ftp|file)://\S+|\bwww\.\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_HANDLE_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,38}")
#: A path: ``~/…``, ``/a/b``, ``./x``, ``C:\…``, or a bare ``dir/dir/file`` with at least two separators.
_PATH_RE = re.compile(
    r"(?<![\w/])(?:~|\.{1,2})?/[\w.@%+-]+(?:/[\w.@%+-]+)*/?|\b[A-Za-z]:\\\S+|\b[\w.-]+(?:/[\w.-]+){2,}")
_SPEAKER_RE = re.compile(r"^\s*(?:\*\*)?(?:user|assistant|human|agent|me|you)(?:\*\*)?\s*:\s*", re.IGNORECASE)


#: Words a RELATION-SHAPED name may keep in the local context (:func:`relation_shaped`: "his brother <name>", "<name>'s
#: dad", "dad of <name>", "mi hermana <name>") — and only such a name: every other multi-word name is redacted whole
#: and by each part of 3+ letters, as before (re-review of #366, 2026-10-19: an exemption that applied to every name
#: let "Pa Her", "Fred Friend", "Ana Sobrino", "Jane Doctor" or "Tom User" keep a surname). Function words and plain
#: relations only, audited against given names and surnames: NOT "her", "sin", "via", "que", "will", "can", "guy",
#: "nina", "rosa", "mar", "tia", "una", "con", "del", "son", "das", "van", "della", "friend", "doctor", "tutor",
#: "mentor", "partner", "family", "sobrino", "lab", "child", "kid", "baby", "boss", "coach", "nurse", "driver",
#: "barber", "cousin", "person", "speaker", "owner", "papa", "mama", "padre", "primo", "amigo" or "pareja", all of
#: which are someone's name. Folded.
_NEVER_A_NAME = frozenset({
    # English function words
    "the", "and", "for", "his", "hers", "our", "ours", "their", "theirs", "your", "yours", "its", "this", "that",
    "these", "those", "with", "from", "into", "about", "who", "whom", "whose", "what", "which", "she", "him", "them",
    "they", "was", "were", "are", "has", "had", "not", "but",
    # Spanish function words
    "los", "las", "unos", "unas", "mis", "sus", "tus", "nuestro", "nuestra", "nuestros", "nuestras", "por", "para",
    # Plain relations, English
    "dad", "mom", "mum", "mother", "father", "sister", "brother", "sibling", "daughter", "girlfriend", "boyfriend",
    "wife", "husband", "spouse", "fiance", "fiancee", "grandma", "grandpa", "grandmother", "grandfather", "uncle",
    "aunt", "niece", "nephew", "stepfather", "stepmother", "roommate", "flatmate", "housemate", "classmate",
    "colleague", "coworker", "teacher", "professor", "manager", "therapist", "psychologist", "psychiatrist",
    "dentist", "landlord", "landlady", "neighbor", "neighbour", "user",
    # Plain relations, Spanish (folded)
    "madre", "hermana", "hermano", "hija", "hijo", "novia", "novio", "esposa", "esposo", "abuela", "abuelo", "amiga",
    "jefa", "jefe", "profe", "profesor", "profesora", "companero", "companera", "vecina", "vecino", "suegra",
    "suegro", "cunada", "cunado",
})
#: The plain relations among them: a name is relation-shaped only when it carries one.
_RELATIONS = _NEVER_A_NAME - frozenset({
    "the", "and", "for", "his", "hers", "our", "ours", "their", "theirs", "your", "yours", "its", "this", "that",
    "these", "those", "with", "from", "into", "about", "who", "whom", "whose", "what", "which", "she", "him", "them",
    "they", "was", "were", "are", "has", "had", "not", "but", "los", "las", "unos", "unas", "mis", "sus", "tus",
    "nuestro", "nuestra", "nuestros", "nuestras", "por", "para"})
#: A name opening with one of these, with a relation in it, describes somebody by the relation ("the girlfriend …",
#: "his dad", "mi hermana …"); in such a name the opener is structure, never redacted on its own.
_ROLE_OPENERS = frozenset(
    "the a an his her hers my our their your its this that these those el la los las un una unos unas mi mis su sus "
    "tu tus nuestro nuestra nuestros nuestras".split())
#: "dad of <name>", "el hermano de <name>".
_RELATION_LINKS = frozenset({"of", "de", "del"})
#: A lone pronoun is no one's name: Stage 1 has typed "her" as a person, and redacting every "her" garbled each line.
#: The one lone word kept (a two-word name with "Her" in it — a Hmong surname — is still redacted by each part).
_LONE_PRONOUNS = frozenset({"her", "him", "his", "she", "hers", "they", "them"})
_NAME_PARTICLES = frozenset("de del della di da das do dos du van von der den ten ter le la y bin ibn al el".split())
_ROLE_WORDS_FOLDED = frozenset(text_fold.fold(w) for w in role_people.ROLE_WORDS)
#: A part shorter than this is not redacted on its own (the whole name still is).
_MIN_PART_CHARS = 3


def _folded_words(name: str) -> list[str]:
    return re.findall(r"\w+", text_fold.fold(name or ""))


def relation_shaped(name: str) -> bool:
    """A name that describes somebody by a relation: it carries a relation (:data:`_RELATIONS`, ``role_people``'s) and
    either opens
    with an article or possessive ("the girlfriend maria", "mi hermana lucía"), has a possessive ("ana's dad") or links
    the relation to a name with "of"/"de" ("dad of ana"). "Lee Brother" or "Tom User" is not: a relation word inside an
    ordinary name is a surname."""
    words = _folded_words(name)
    if len(words) < 2 or not any(w in _RELATIONS or w in _ROLE_WORDS_FOLDED for w in words):
        return False   # detection reads every relation ("friend" too); only _NEVER_A_NAME words are ever kept
    return (words[0] in _ROLE_OPENERS or bool(re.search(r"\w['’]s\b", name or ""))
            or any(w in _RELATION_LINKS for w in words[1:-1]))


def _exempt(word: str, name_words: list[str], relation: bool) -> bool:
    """Is this part of a name kept when it stands alone? Only in a relation-shaped name, and only a never-a-name word
    or its opening article/possessive."""
    return relation and (word in _NEVER_A_NAME or (word == name_words[0] and word in _ROLE_OPENERS))


def name_shape(name: str) -> str:
    """How a person's name is redacted from the local context: ``split`` (whole, and each part of 3+ letters on its own
    — every name but the two below), ``whole`` (a relation-shaped name with nothing but relation words in it — "his
    dad", "the user": only the phrase) or ``skip`` (a lone pronoun — "her" — is no one's name)."""
    words = _folded_words(name)
    if not words or len(" ".join(words)) < 3:
        return "skip"
    if len(words) == 1:
        return "skip" if words[0] in _LONE_PRONOUNS else "split"
    relation = relation_shaped(name)
    if relation and all(_exempt(w, words, True) or len(w) < _MIN_PART_CHARS for w in words):
        return "whole"
    return "split"


#: Words that say a person-typed name is a thing (a technique, a department), not somebody — the data problem the
#: 2026-10-19 trace found ("<a technique> and <a task>" typed person). Counted by :func:`person_name_census`, never
#: fixed here: the page's type is the person's to correct.
_THING_WORDS = frozenset({
    "algorithm", "localization", "localisation", "mapping", "recommendation", "recommendations", "department", "lab",
    "laboratory", "learning", "network", "networks", "analysis", "system", "systems", "method", "technique",
    "careers", "talents", "office", "committee", "program", "programme", "project", "service", "services", "team",
    "association", "society", "institute", "center", "centre", "faculty", "school", "university", "club",
})


def looks_like_a_thing(name: str) -> bool:
    """A person-typed name that reads as a phrase about a thing: a function word inside it that is not a name
    particle ("simple algorithm for recommendation"), or a word of :data:`_THING_WORDS` / :data:`CATEGORY_WORDS`.
    A detector for the census only — it never changes how a name is redacted."""
    words = _folded_words(name)
    if not words or words[0] in _ROLE_OPENERS or any(w in _ROLE_WORDS_FOLDED for w in words):
        return False   # somebody described by a relation ("the friend of …", "a lab teacher"), not a thing
    if len(words) > 1 and any(w in text_fold.SUBJECT_STOPWORDS and w not in _NAME_PARTICLES for w in words):
        return True
    return any(w in _THING_WORDS or w in CATEGORY_WORDS for w in words)


def person_name_census(facts: "BankFacts") -> dict:
    """Counts only (the dry run's ``--trace``): how each person name or alias is redacted (:func:`name_shape`), how
    many are descriptions of somebody by a relation, and how many read as a thing (:func:`looks_like_a_thing`) — a
    page typed person that is not one. Never a name."""
    out = {"split": 0, "whole": 0, "skip": 0, "relation": 0, "looks_like_a_thing": 0}
    for name in facts.person_names | facts.pending_person_names:
        out[name_shape(name)] += 1
        words = _folded_words(name)
        out["relation"] += int(bool(words) and (words[0] in _ROLE_OPENERS
                                                or any(w in _ROLE_WORDS_FOLDED for w in words)))
        out["looks_like_a_thing"] += int(looks_like_a_thing(name))
    return out


def _sub_folded(text: str, words: tuple[str, ...]) -> tuple[str, int]:
    """``words`` (folded) replaced by "someone" in ``text``, matched accent- and case-blind ("maría" redacts "Maria"
    and "MARÍA"), whole words only; the original text is cut at the matched source offsets."""
    import unicodedata

    folded, at = text_fold.fold_with_map(text)
    pattern = r"(?<!\w)" + r"[\s\-_.'’]+".join(re.escape(w) for w in words) + r"(?!\w)"
    spans = [(m.start(), m.end()) for m in re.finditer(pattern, folded)]
    if not spans:
        return text, 0
    out, last = [], 0
    for a, b in spans:
        start, end = at[a], at[b - 1] + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1   # a decomposed accent belongs to the letter it sits on
        out += [text[last:start], "someone"]
        last = end
    out.append(text[last:])
    return "".join(out), len(spans)


def _redact_people(text: str, names: frozenset[str], keep: frozenset[str] = frozenset(),
                   stats: dict | None = None) -> str:
    """Every person's name or alias in the bank (the owner's too, and a person held without a page) becomes "someone"
    — the line keeps its sense, the prompt carries no one's name (ruling 27: never another name from the bank). Whole
    words, any case, accents folded; the whole name first, then each of its parts of 3+ letters on its own (a person
    is often named by one of them) — except a word of the subject's own name (``keep``: the prompt already carries it)
    and, in a relation-shaped name only (:func:`relation_shaped`: "his brother luis", "ana's dad"), its articles,
    possessives and plain relations (:data:`_NEVER_A_NAME`). A relation phrase with no name in it ("his dad") goes as
    its whole phrase; a lone pronoun ("her") is no name. Over-redaction is the safe failure. ``stats`` (the
    diagnostic) counts the replacements."""
    keep = frozenset(text_fold.fold(w) for w in keep)
    phrases: set[tuple[str, ...]] = set()
    for name in names:
        shape = name_shape(name)
        if shape == "skip":
            continue
        words = tuple(_folded_words(name))
        phrases.add(words)
        if shape == "split" and len(words) > 1:
            relation = relation_shaped(name)
            phrases.update((w,) for w in words
                           if len(w) >= _MIN_PART_CHARS and w not in keep and not _exempt(w, list(words), relation))
            # A joined part ("Su-bin", "O'Brien") also goes as a unit, so a short piece of it never survives.
            phrases.update(tuple(_folded_words(token)) for token in (name or "").split()
                           if len(_folded_words(token)) > 1)
    for words in sorted(phrases, key=lambda w: len(" ".join(w)), reverse=True):
        text, n = _sub_folded(text, words)
        if stats is not None and n:
            stats["people"] = stats.get("people", 0) + n
    return text


def _clean(text: str, facts: BankFacts, keep: frozenset[str] = frozenset(), stats: dict | None = None) -> str:
    """Scrubbed as every writer scrubs (``episode_scrub``: secrets and one-time codes), then links, addresses, handles
    and paths out, people's names out, one line — never cut: a cut comes after, so it cannot leave half a name or a
    secret whose cue it cut off."""
    text, _ = episode_scrub.scrub(str(text or ""))
    text = _URL_RE.sub("[link]", text)
    text = _EMAIL_RE.sub("[address]", text)
    text = _HANDLE_RE.sub("[handle]", text)
    text = _PATH_RE.sub("[path]", text)
    text = _redact_people(text, facts.person_names | facts.pending_person_names, keep, stats)
    return _SPEAKER_RE.sub("", " ".join(text.split()))


def clean_context_line(text: str, facts: BankFacts, *, limit: int = MAX_LINE_CHARS,
                       keep: frozenset[str] = frozenset(), stats: dict | None = None) -> str:
    """One line of local context: cleaned whole (:func:`_clean`), then bounded."""
    return _one_liner(_clean(text, facts, keep, stats), limit)


def subject_words(name: str) -> frozenset[str]:
    return frozenset(w.lower() for w in re.findall(r"\w+", name or ""))


def _mention_line(body: str, span: tuple[int, int], c: Candidate, facts: BankFacts,
                  limit: int = MAX_LINE_CHARS, stats: dict | None = None) -> str:
    """The line holding ``span``, cleaned WHOLE (:func:`_clean`) and only then cut to ±``limit``/2 around the subject's
    mention on word boundaries — so a cut can never leave half a person's name or a secret without its cue."""
    from api.services import inbox_context

    start = body.rfind("\n", 0, span[0]) + 1
    end = body.find("\n", span[1])
    end = len(body) if end < 0 else end
    line = _clean(body[start:end], facts, subject_words(c.name), stats)
    if len(line) <= limit:
        return line
    at = inbox_context.locate_mention(line, c.name, c.entity_id)
    radius = max(40, (limit - ((at[1] - at[0]) if at else 0)) // 2)
    return _one_liner(inbox_context.excerpt_around(line, at, radius=radius).excerpt, limit)


def local_context(memory_path: Path, c: Candidate, facts: BankFacts, *, ctx=None,
                  stats: dict | None = None) -> list[str]:
    """What Cicada already knows about the subject, for the model to judge WHICH search result is the thing the person
    meant (owner ruling 2026-10-16, amends ruling 27: "Yes, use local context"). At most ``MAX_CONTEXT_CHARS``
    characters: Cicada's own one-line description (left out of a question about what the thing IS — it is one of the
    options there) and up to two lines where the subject was mentioned, from the item's own conversation and its option
    claims' evidence (the claim's quoted span when it still holds, else the first mention in that conversation). Every
    line is scrubbed (:func:`clean_context_line`). Never part of the query (:func:`query_for`); engine-free; never raises.
    """
    from api.services import inbox_context

    try:
        ctx = ctx or inbox_context.InboxContext(Path(memory_path), today=date.today().isoformat())
        lines: list[str] = []
        if c.description and not c.type_question:
            desc = clean_context_line(c.description, facts, limit=MAX_DESCRIPTION_CHARS, keep=subject_words(c.name),
                                      stats=stats)
            if desc:
                lines.append(f"Cicada's description: {desc}")
        refs: list[tuple[str, object]] = []
        if c.source_episode:
            refs.append((c.source_episode, None))
        by_id = {cl.id: cl for cl in ctx.claims(c.entity_id)} if c.claim_ids else {}
        for cid in c.claim_ids:
            claim = by_id.get(cid)
            for ep_id in list(getattr(claim, "source_episodes", None) or [])[-1:]:
                refs.append((str(ep_id), claim))
        if not c.has_page and c.entity_id in facts.pending_lines and facts.pending_lines[c.entity_id][1]:
            refs.append((facts.pending_lines[c.entity_id][1], None))
        page = ctx.entity(c.entity_id) if c.has_page else None
        for ep_id in list((page.frontmatter.get("source_episodes") if page is not None else None) or [])[-2:][::-1]:
            refs.append((str(ep_id), None))
        seen: set[str] = set()
        mentions: list[str] = []
        for ep_id, claim in refs:
            if len(mentions) >= MAX_MENTION_LINES:
                break
            ep = ctx.episode(ep_id)
            if ep is None:
                continue
            body = ctx._body(ep)
            span = inbox_context._asserted_span(claim, ep_id, body) if claim is not None else None
            span = span or inbox_context.locate_mention(body, c.name, c.entity_id)
            if span is None:
                continue   # no line names it: nothing to show, never the head of a conversation
            line = _mention_line(body, span, c, facts, stats=stats)
            key = _norm(line)
            if line and key not in seen:
                seen.add(key)
                mentions.append(f"Mentioned: {line}")
        lines += mentions
        out: list[str] = []
        for line in lines:
            room = MAX_CONTEXT_CHARS - len("\n".join(out)) - (1 if out else 0)
            if room < 40:
                break
            out.append(line if len(line) <= room else _one_liner(line, room))
        return out
    except Exception as exc:  # noqa: BLE001 — a lookup without context is still a lookup
        logger.debug(f"web check: no local context ({type(exc).__name__})")
        return []


def has_mentions(context: list[str]) -> bool:
    return any(line.startswith("Mentioned: ") for line in context)
