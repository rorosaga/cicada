"""People Cicada knows only by their relation to the owner — "placeholder people".

A conversation often names someone only by role: "my partner", "my dad", "my old roommate". Stage 1 used to
title such a person after the owner ("<owner>'s partner"), which (a) put the owner's name into a page title and id
(a portability bug), (b) split one person across pages as the model's wording drifted ("<owner>'s friend" in one
conversation, "<owner>'s partner" in another), and (c) never asked the one question that settles it: what is
their name?

This module is the one place that knows what a role-only name is and what happens to it:

* :func:`parse` — is this name a relation to the owner, and which one? A closed, language-aware vocabulary
  (:data:`SINGULAR_ROLES`, :data:`PLURAL_ROLES`), never a guess from capitalisation.
* :func:`canonicalize` — Stage 2's pre-pass over a batch: every role-only person is renamed to the ONE page that
  holds that relation, so mentions attach instead of splitting. A named page holds a relation only when the record
  says so (``owner_roles``, written by the person's own answer or by a merge with evidence), and only a singular
  relation (one partner, one father) is ever attached to a named page; otherwise the page is titled by the role
  ("Partner", "Former roommate") and marked ``unnamed: true``.
* :func:`ensure_question` / :func:`ask_after_write` — the inbox question "What's the name of your partner?", one
  per unnamed page, on the existing ``clarification`` kind (``asks: name``), never a second inbox.
* :func:`answer_name` / :func:`decline` — the answer: a name that is exactly an existing person's name (or alias)
  merges the placeholder into that person through the one merge primitive (``entity_merge``); any other name
  renames the page (its claims, edges and every reference follow, ``rename_references``); "I'd rather not say"
  keeps the role title and is never asked again.
* :func:`survey` / :func:`apply` — the repair for an existing bank (``api.scripts.repair_placeholder_people``).

Rails (CLAUDE.md, brief 2026-10-14): two people are merged only on evidence on the record (an open claim or edge
between the owner and exactly one named person whose predicate names the relation, or a relation the person
already confirmed) or on the person's own answer — never on a name's resemblance. Promotion is untouched. Nothing
said about the person is lost on a rename or merge: claims, history and sources move with the page, and git keeps
the old state.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

import yaml
from loguru import logger

from api.services import markdown_parser
from api.services.id_utils import sanitize_id

#: Frontmatter: the owner's relations this person holds, as role keys ("partner", "former roommate"). Written on a
#: placeholder page at its creation, and on a named page only by the person's answer or a merge with evidence.
ROLES_KEY = "owner_roles"
#: Frontmatter: this person page has no name yet — its title is the relation.
UNNAMED_KEY = "unnamed"
#: Frontmatter: the person said "I'd rather not say" — the page keeps its role title and is never asked again.
DECLINED_KEY = "name_declined"
#: Inbox: a clarification that asks for a name carries ``asks: name``.
ASKS = "name"
DECLINE_KEY = "rather_not_say"
DECLINE_LABEL = "I'd rather not say"
UNCERTAINTY = "Unnamed person"
#: Inbox: a possible-duplicate question whose subject was already a page when it was asked (`answer_name`).
FOLD_PAGE_KEY = "fold_page"
TRIGGER = "maintenance/placeholder-people"
MAX_NAME_CHARS = 120

#: One person holds the relation at a time: a role-only mention may attach to the named page the record says holds it.
SINGULAR_ROLES = frozenset({
    "partner", "spouse", "wife", "husband", "boyfriend", "girlfriend", "fiance", "fiancé", "fiancee", "fiancée",
    "father", "mother", "dad", "mom", "mum", "stepfather", "stepmother",
    "pareja", "esposa", "esposo", "novia", "novio", "prometida", "prometido", "padre", "madre", "papá", "mamá",
    "papa", "mama",
})
#: Several people can hold it: a role-only mention never attaches to a named page on the role alone.
PLURAL_ROLES = frozenset({
    "friend", "roommate", "flatmate", "housemate", "teacher", "professor", "tutor", "advisor", "adviser",
    "supervisor", "mentor", "boss", "manager", "colleague", "coworker", "co-worker", "classmate", "brother",
    "sister", "sibling", "son", "daughter", "child", "kid", "cousin", "uncle", "aunt", "grandmother", "grandfather",
    "grandma", "grandpa", "niece", "nephew", "therapist", "doctor", "dentist", "landlord", "landlady", "neighbor",
    "neighbour", "ex", "amigo", "amiga", "hermano", "hermana", "primo", "prima", "tío", "tía", "tio", "tia",
    "abuelo", "abuela", "jefe", "jefa", "profesor", "profesora", "compañero", "compañera", "hijo", "hija",
})
ROLE_WORDS = SINGULAR_ROLES | PLURAL_ROLES
#: A relation that is over: never singular, never attached to the current holder.
PAST_QUALIFIERS = frozenset({"former", "ex", "old", "previous", "late", "antiguo", "antigua", "exnovia", "exnovio"})
QUALIFIERS = PAST_QUALIFIERS | frozenset({
    "new", "current", "replacement", "best", "close", "older", "younger", "elder", "eldest", "oldest", "youngest",
    "little", "big", "first", "second", "childhood", "university", "college", "school", "work", "step", "future",
})
_LINKERS = frozenset({"from", "at", "in", "of", "de", "del", "en"})
#: What a conversation calls the owner in a possessive when it does not use their name.
_GENERIC_OWNERS = ("the user", "user", "the owner", "owner", "the person", "el usuario", "la usuaria", "usuario")
_UNNAMED_SUFFIX = re.compile(r"\s*\((?:unnamed|name unknown|no name|name not given|name not recorded|sin nombre)\)\s*$",
                             re.IGNORECASE)
_UNNAMED_PREFIX = re.compile(r"^(?:unnamed|unknown)\s+", re.IGNORECASE)
#: The suffix :func:`_role_title` gives a second page of the same relation; it reads back as that relation.
_ANOTHER = re.compile(r"\s*\(another(?:\s+\d+)?\)\s*$", re.IGNORECASE)
_ARTICLE = re.compile(r"^(?:the|a|an|el|la|los|las|un|una)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Role:
    """A relation to the owner. ``key`` is the identity ("former roommate"), ``title`` the page title
    ("Former roommate"), ``head`` the role word, ``marked`` whether the name itself said whose relation it is
    (a possessive of the owner, "my", "(unnamed)") rather than being a bare role word."""

    key: str
    title: str
    head: str
    singular: bool
    marked: bool

    def question(self) -> str:
        return f"What's the name of your {self.key}?"


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", str(text or "")).replace("’", "'").replace("‘", "'")
    return " ".join(text.split()).strip(" \"`.,;:!?")


def _base(word: str) -> str:
    w = word.lower()
    for prefix in ("ex-", "step-"):
        if w.startswith(prefix) and w[len(prefix):] in ROLE_WORDS:
            return w[len(prefix):]
    return w


def _phrase(text: str) -> tuple[str, str, str, bool] | None:
    """``(key, title, head, singular)`` when ``text`` is only a relation, else ``None``."""
    if not text or "'s " in text.lower() + " " or "'" in text:
        return None   # "daughter's teacher" is someone else's relation; a quote mark is a name's
    words = text.split()
    head_at = next((i for i, w in enumerate(words) if _base(w) in ROLE_WORDS), None)
    if head_at is None or head_at > 2:
        return None
    before = [w.lower() for w in words[:head_at]]
    if any(w not in QUALIFIERS for w in before):
        return None
    after = words[head_at + 1:]
    if after and (after[0].lower() not in _LINKERS or len(after) > 4):
        return None
    head_word = words[head_at].lower()
    head = _base(head_word)
    lead = " ".join([*before, head_word])
    title_text = " ".join([lead, *after])
    key = title_text.lower()
    title = title_text[:1].upper() + title_text[1:]
    singular = (head in SINGULAR_ROLES and not head_word.startswith("ex-")
                and not any(w in PAST_QUALIFIERS for w in before))
    return key, title, head, singular


def _possessive_re(owner_names: Iterable[str]) -> re.Pattern:
    alts = sorted({_clean(n) for n in (*owner_names, *_GENERIC_OWNERS) if _clean(n)}, key=len, reverse=True)
    names = "|".join(re.escape(a) for a in alts)
    return re.compile(rf"^(?:{names})(?:'s|')\s+(.+)$", re.IGNORECASE)


def _spanish_re(owner_names: Iterable[str]) -> re.Pattern:
    alts = sorted({_clean(n) for n in (*owner_names, *_GENERIC_OWNERS) if _clean(n)}, key=len, reverse=True)
    names = "|".join(re.escape(a) for a in alts)
    return re.compile(rf"^(.+?)\s+de\s+(?:{names})$", re.IGNORECASE)


def parse(name: str, owner_names: Iterable[str] = (), *, bare: bool = False) -> Role | None:
    """The relation ``name`` stands for, or ``None`` when it is a name (or anything else).

    Recognised: "<owner>'s partner", "<owner first name>'s dad", "the user's friend", "my mom", "mi pareja",
    "padre de <owner>", "Replacement roommate (unnamed)", "Unnamed partner". A bare relation ("Partner",
    "Former roommate") is read only with ``bare=True`` — on a page that carries ``unnamed: true``, the titles this
    module writes — because a bare word can be a real name ("Tia", "Mama"): a name is never read as a relation. A name
    after the role ("friend Alice"), someone else's relation ("<owner>'s daughter's teacher") or any word outside
    the vocabulary is not a relation."""
    owner_names = [n for n in owner_names if n]
    text = _clean(name)
    if not text:
        return None
    marked = False
    text = _ANOTHER.sub("", text).strip()
    stripped = _UNNAMED_SUFFIX.sub("", text)
    stripped = _UNNAMED_PREFIX.sub("", stripped)
    if stripped != text:
        marked, text = True, stripped.strip()
    match = _possessive_re(owner_names).match(text)
    if match:
        marked, text = True, match.group(1).strip()
    else:
        lowered = text.lower()
        for prefix in ("my ", "mi ", "mis "):
            if lowered.startswith(prefix):
                marked, text = True, text[len(prefix):].strip()
                break
        else:
            spanish = _spanish_re(owner_names).match(text)
            if spanish:
                marked, text = True, spanish.group(1).strip()
    text = _ARTICLE.sub("", text)
    found = _phrase(text)
    if found is None:
        return None
    key, title, head, singular = found
    if not marked and not bare:
        return None
    return Role(key=key, title=title, head=head, singular=singular, marked=marked)


def owner_names(owner_fm: dict | None) -> list[str]:
    """What a possessive may call the owner: the owner page's name, its first word, and its aliases."""
    fm = owner_fm or {}
    names: list[str] = []
    name = _clean(fm.get("name") or "")
    if name:
        names.append(name)
        first = name.split()[0]
        if len(first) >= 2 and first.lower() != name.lower():
            names.append(first)
    for alias in fm.get("aliases") or []:
        if isinstance(alias, str) and _clean(alias):
            names.append(_clean(alias))
    return names


def owner_frontmatter(memory_path: Path, settings=None) -> dict | None:
    """The bank's ``owner: true`` page frontmatter (the observer's page first, then a scan), or ``None``."""
    from api.services import bank_index, owner_identity

    memory_path = Path(memory_path)
    try:
        first = memory_path / "entities" / f"{owner_identity.resolve_observer(memory_path, settings)}.md"
        if first.is_file():
            fm = markdown_parser.parse(first).frontmatter
            if fm.get("owner") is True:
                return dict(fm)
    except Exception:  # noqa: BLE001 - fall through to the scan
        pass
    owners = sorted((f for f in bank_index.files(memory_path, "entities")
                     if f.path.suffix == ".md" and (f.frontmatter or {}).get("owner") is True),
                    key=lambda f: f.path.name)
    if not owners:
        return None
    winner = owner_identity.owner_page_id([{"id": f.path.stem, "frontmatter": {"owner": True}} for f in owners],
                                          memory_path, settings)
    return dict(next(f for f in owners if f.path.stem == winner).frontmatter)


def roles_of(fm: dict) -> list[str]:
    value = (fm or {}).get(ROLES_KEY) or []
    if isinstance(value, str):
        value = [value]
    return [str(v).strip().lower() for v in value if str(v).strip()]


def _person(fm: dict) -> bool:
    return str((fm or {}).get("type") or "").strip().lower() == "person"


# ---------------------------------------------------------------- Stage 2: one page per role-person


@dataclass
class _Carrier:
    id: str
    name: str
    unnamed: bool


def _carriers(existing: list[dict], names: list[str]) -> dict[str, list[_Carrier]]:
    """``{role key: pages that hold it}`` — by ``owner_roles``, and a page whose title is itself a relation."""
    out: dict[str, list[_Carrier]] = {}
    for page in existing or []:
        fm = (page or {}).get("frontmatter") or {}
        if fm.get("owner") or not _person(fm) or str(fm.get("status") or "") == "dropped":
            continue
        name = str(fm.get("name") or page.get("id") or "")
        # A bare title counts only on a page this module marked; "Tia" the friend is a name.
        titled = parse(name, names, bare=bool(fm.get(UNNAMED_KEY)))
        keys = set(roles_of(fm))
        if titled is not None:
            keys.add(titled.key)
        unnamed = bool(fm.get(UNNAMED_KEY)) or titled is not None
        for key in keys:
            out.setdefault(key, []).append(_Carrier(str(page.get("id")), name, unnamed))
    return out


def _target(role: Role, carriers: dict[str, list[_Carrier]], taken: set[str]) -> tuple[str, bool]:
    """The name a role-only mention takes, and whether it is a new placeholder (no page holds the relation)."""
    holders = carriers.get(role.key, [])
    named = [c for c in holders if not c.unnamed]
    if role.singular and len(named) == 1:
        return named[0].name, False
    unnamed = sorted((c for c in holders if c.unnamed), key=lambda c: (c.name.lower() != role.title.lower(), c.id))
    if unnamed:
        return unnamed[0].name, False
    title = role.title
    if title.lower() in taken:   # another page (a person called "Tia", a company "Partner") already has the title
        title = f"{title} (unnamed)"
    return title, True


def _relink(text: str, renames: dict[str, str]) -> str:
    if not text or "[[" not in text:
        return text

    def sub(match: re.Match) -> str:
        target = match.group(2)
        new = renames.get(_clean(target).lower())
        return f"{match.group(1)}{new}{match.group(3)}" if new else match.group(0)

    return re.sub(r"(\[\[\s*)([^\]|#]+?)(\s*(?:[|#][^\]]*)?\]\])", sub, text)


def canonicalize(extracted: list[dict], existing: list[dict], owner_fm: dict | None) -> dict[str, str]:
    """Stage 2's pre-pass: rename every role-only person in the batch, in place, to the one page for that relation.

    Entities (person-typed, so a company "Partner" keeps its name), relationship endpoints (an endpoint renamed
    above, or one that says whose relation it is — "<owner>'s partner") and wikilinks in the entity's own text.
    A new placeholder carries ``owner_roles`` and ``unnamed`` for its page. Returns ``{old name lower: new name}``.
    Promotion is untouched: the renamed mentions are counted, parked and promoted exactly as any name."""
    names = owner_names(owner_fm)
    carriers = _carriers(existing, names)
    carrier_ids = {c.id for holders in carriers.values() for c in holders}
    taken = {str(((p or {}).get("frontmatter") or {}).get("name") or "").lower() for p in existing or []
             if str((p or {}).get("id")) not in carrier_ids}
    renames: dict[str, str] = {}
    for extraction in extracted or []:
        for entity in extraction.get("entities", []) or []:
            if not _person(entity):
                continue
            role = parse(entity.get("name", ""), names)
            if role is None:
                continue
            target, new = _target(role, carriers, taken)
            renames[_clean(entity["name"]).lower()] = target
            entity["name"] = target
            if new:
                entity[ROLES_KEY] = [role.key]
                entity[UNNAMED_KEY] = True
            if entity.get("aliases"):
                entity["aliases"] = [a for a in entity["aliases"] if parse(str(a), names) is None]
    for extraction in extracted or []:
        for rel in extraction.get("relationships", []) or []:
            for end in ("source", "target"):
                value = str(rel.get(end) or "")
                renamed = renames.get(_clean(value).lower())
                if renamed is None:
                    role = parse(value, names)
                    if role is not None and role.marked:
                        renamed = _target(role, carriers, taken)[0]
                        renames[_clean(value).lower()] = renamed
                if renamed is not None:
                    rel[end] = renamed
    if renames:
        for extraction in extracted or []:
            for entity in extraction.get("entities", []) or []:
                for key in ("summary", "description"):
                    if isinstance(entity.get(key), str):
                        entity[key] = _relink(entity[key], renames)
                for key in ("key_facts", "open_questions"):
                    if isinstance(entity.get(key), list):
                        entity[key] = [_relink(v, renames) if isinstance(v, str) else v for v in entity[key]]
                for entry in entity.get("history_entries") or []:
                    if isinstance(entry, dict) and isinstance(entry.get("event"), str):
                        entry["event"] = _relink(entry["event"], renames)
        logger.info(f"Stage 2: {len(renames)} role-only name(s) titled by their relation to the owner")
    return renames


def create_fields(entity: dict) -> dict:
    """The frontmatter a new placeholder page is born with (``conflict_resolver.apply_changes``)."""
    if not entity.get(UNNAMED_KEY):
        return {}
    return {ROLES_KEY: list(entity.get(ROLES_KEY) or []), UNNAMED_KEY: True}


# ---------------------------------------------------------------- the question


def open_question(memory_path: Path, page_id: str) -> Path | None:
    """The open name question about ``page_id``, if one is on disk."""
    inbox = Path(memory_path) / "inbox"
    if not inbox.is_dir():
        return None
    for path in sorted(inbox.glob("inbox-*.md")):
        try:
            fm = markdown_parser.parse(path).frontmatter
        except Exception:  # noqa: BLE001 - an unreadable item is no question
            continue
        if (fm.get("asks") == ASKS and str(fm.get("entity_id") or "") == page_id
                and str(fm.get("status") or "pending") == "pending"):
            return path
    return None


def _lead(body: str, limit: int = 500) -> str:
    from api.services import entity_body
    from api.services.claims import strip_claims_block

    prose = strip_claims_block(body or "")
    sections = entity_body.parse_sections(prose)
    text = (sections.get("Summary") or sections.get("") or "").strip()
    if not text:
        text = next((v.strip() for t, v in sections.items() if v and v.strip()), "")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _next_item(inbox: Path) -> Path:
    top = 0
    for path in inbox.glob("inbox-*.md"):
        try:
            top = max(top, int(path.stem.split("-")[-1]))
        except ValueError:
            continue
    return inbox / f"inbox-{top + 1:03d}.md"


def ensure_question(memory_path: Path, page_id: str, *, owner_fm: dict | None = None,
                    today: str | None = None) -> Path | None:
    """Write "What's the name of your <relation>?" about an unnamed page, once. Returns the new item's path, or
    ``None`` when the page is not an unnamed person, the person declined, or a question is already open."""
    memory_path = Path(memory_path)
    page = memory_path / "entities" / f"{page_id}.md"
    if not page.is_file():
        return None
    parsed = markdown_parser.parse(page)
    fm = parsed.frontmatter
    if fm.get("owner") or not _person(fm) or fm.get(DECLINED_KEY) or not fm.get(UNNAMED_KEY):
        return None
    if str(fm.get("status") or "") == "dropped" or open_question(memory_path, page_id) is not None:
        return None
    keys = roles_of(fm)
    role = parse(str(fm.get("name") or ""), owner_names(owner_fm), bare=True)
    key = keys[0] if keys else (role.key if role is not None else "")
    if not key:
        return None
    question = f"What's the name of your {key}?"
    episodes = [str(e) for e in fm.get("source_episodes") or [] if e]
    item_fm = {
        "kind": "clarification",
        "asks": ASKS,
        "required_input": "freetext",
        "status": "pending",
        "priority": 0.6,
        "entity_id": page_id,
        "entity_name": str(fm.get("name") or page_id),
        "title": question,
        "question": question,
        "options": [{"key": DECLINE_KEY, "label": DECLINE_LABEL}],
        "allow_other": True,
        "allow_defer": True,
        "owner_role": key,
        "uncertainty_type": UNCERTAINTY,
        "suggested_classification": "person",
        "suggested_confidence": round(float(fm.get("confidence", 0.5) or 0.5), 2),
        "created_date": today or str(date.today()),
    }
    if episodes:
        item_fm["source_episode"] = sorted(episodes)[-1]
    inbox = memory_path / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = _next_item(inbox)
    markdown_parser.write(path, item_fm, _lead(parsed.body) or f"Cicada knows this person only as your {key}.")
    return path


def ask_after_write(memory_path: Path, changes: list[dict], owner_fm: dict | None = None) -> list[str]:
    """Sleep, after Stage 5 wrote the pages: one name question per unnamed person page this batch touched."""
    asked: list[str] = []
    seen: set[str] = set()
    for change in changes or []:
        page_id = str(change.get("id") or "")
        if not page_id or page_id in seen or change.get("action") not in ("create", "update"):
            continue
        seen.add(page_id)
        try:
            path = ensure_question(memory_path, page_id, owner_fm=owner_fm)
        except Exception as exc:  # noqa: BLE001 - a question is never worth a failed cycle
            logger.warning(f"name question skipped: {type(exc).__name__}")
            continue
        if path is not None:
            asked.append(f"inbox/{path.name}")
    return asked


# ---------------------------------------------------------------- the answer


class NotAName(ValueError):
    """The answer reads as a relation or a self-reference, not a person's name."""


def _drop_role_aliases(fm: dict, names: list[str], only: set[str] | None = None) -> None:
    aliases = fm.get("aliases")
    if not isinstance(aliases, list):
        return
    # With ``only`` (a merged placeholder's own title) a bare title is that placeholder's; otherwise only a form that
    # says whose relation it is ("<owner>'s partner") is dropped — a bare word may be a real alias.
    kept = [a for a in aliases if not (isinstance(a, str) and parse(a, names, bare=only is not None) is not None
                                       and (only is None or a.lower() in only))]
    if kept:
        fm["aliases"] = kept
    else:
        fm.pop("aliases", None)


def _add_role(fm: dict, key: str) -> None:
    roles = roles_of(fm)
    if key and key not in roles:
        roles.append(key)
    if roles:
        fm[ROLES_KEY] = roles


def _person_pages(memory_path: Path) -> list[tuple[str, dict]]:
    out = []
    for path in sorted((Path(memory_path) / "entities").glob("*.md")):
        try:
            fm = markdown_parser.parse(path).frontmatter
        except Exception:  # noqa: BLE001
            continue
        if _person(fm) and not fm.get("owner") and str(fm.get("status") or "") != "dropped":
            out.append((path.stem, fm))
    return out


def same_name(memory_path: Path, name: str, exclude: str) -> list[str]:
    """Person pages whose name or an alias is exactly ``name`` (case, accents and spacing aside)."""
    want = _fold(name)
    out = []
    for page_id, fm in _person_pages(memory_path):
        if page_id == exclude or fm.get(UNNAMED_KEY):
            continue
        spellings = [fm.get("name") or ""] + [a for a in fm.get("aliases") or [] if isinstance(a, str)]
        if any(_fold(s) == want for s in spellings):
            out.append(page_id)
    return out


def _part_of(memory_path: Path, name: str, exclude: set[str]) -> list[tuple[str, str]]:
    """Person pages whose name contains the answer's words or is contained in them ("Carl" and "Carl Example") —
    a lead for a question, never a merge. A shared surname alone is not one (a family shares it)."""
    words = set(_fold(name).split())
    out = []
    for page_id, fm in _person_pages(memory_path):
        if page_id in exclude or fm.get(UNNAMED_KEY):
            continue
        other = str(fm.get("name") or "")
        theirs = set(_fold(other).split())
        if words and theirs and words != theirs and (words < theirs or theirs < words):
            out.append((page_id, other))
    return out[:3]


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", _clean(text))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _free_id(entities: Path, name: str, own: str) -> str:
    base = sanitize_id(name)
    candidate, n = base, 2
    while candidate != own and (entities / f"{candidate}.md").exists():
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def check_name(name: str, owner_fm: dict | None, role_key: str = "") -> str:
    from api.services import owner_identity

    text = _clean(name)
    if not text:
        raise NotAName("a name is needed")
    if len(text) > MAX_NAME_CHARS:
        raise NotAName("that is longer than a name")
    # "my girlfriend" or the asked relation itself ("Partner" for the partner) is not a name; a bare word that is
    # also a name ("Tia") is one.
    bare = parse(text, owner_names(owner_fm), bare=True)
    if (parse(text, owner_names(owner_fm)) is not None or owner_identity.is_self_reference(text)
            or (bare is not None and role_key and bare.key == role_key)):
        raise NotAName("that reads as a relation, not a name")
    return text


@dataclass
class Outcome:
    """What an answer did. ``page_id`` is where the person lives now; ``paths`` every memory-relative path written
    or removed (the commit's manifest); ``removed`` the page that went away in a merge or a rename."""

    page_id: str
    action: str   # "merged" | "named" | "declined"
    paths: list[str] = field(default_factory=list)
    removed: str | None = None
    suggested: list[str] = field(default_factory=list)


def _note(memory_path: Path, page_id: str, note: str) -> None:
    from api.services.entity_merge import append_note

    path = Path(memory_path) / "entities" / f"{page_id}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, append_note(parsed.body, note))


def merge_into(memory_path: Path, page_id: str, winner_id: str, role_key: str, owner_fm: dict | None,
               note: str) -> Outcome:
    """Fold the placeholder into the named person (``entity_merge``: claims with provenance, sources, history,
    edges and every reference move) and record the relation on the survivor."""
    from api.services.entity_merge import merge_entities

    memory_path = Path(memory_path)
    loser_name = str(markdown_parser.parse(memory_path / "entities" / f"{page_id}.md").frontmatter.get("name")
                     or page_id)
    result = merge_entities(memory_path, loser_id=page_id, winner_id=winner_id)
    path = memory_path / "entities" / f"{winner_id}.md"
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    _add_role(fm, role_key)
    # The merge keeps the loser's title as an alias; a relation is not this person's name (and an "<owner>'s …"
    # title would carry the owner's name onto the page) — Stage 2 finds them by `owner_roles` instead.
    _drop_role_aliases(fm, owner_names(owner_fm), only={loser_name.lower()})
    markdown_parser.write(path, fm, parsed.body)
    _note(memory_path, winner_id, note)
    return Outcome(winner_id, "merged", list(dict.fromkeys(result["paths"])), removed=f"entities/{page_id}.md")


def rename(memory_path: Path, page_id: str, new_name: str, owner_fm: dict | None, *, named: bool,
           note: str | None) -> Outcome:
    """Retitle a page (a name, or its role title) and move it to the matching id: its own claims, the graph's
    edges and every other page's references follow (``entity_merge.rename_references``). ``named`` drops the
    placeholder marks."""
    from api.services.entity_merge import rename_references

    memory_path = Path(memory_path)
    entities = memory_path / "entities"
    old = entities / f"{page_id}.md"
    parsed = markdown_parser.parse(old)
    fm = dict(parsed.frontmatter)
    old_name = str(fm.get("name") or page_id)
    new_id = _free_id(entities, new_name, page_id)
    fm["name"] = new_name
    _drop_role_aliases(fm, owner_names(owner_fm))
    if named:
        fm.pop(UNNAMED_KEY, None)
        fm.pop(DECLINED_KEY, None)
    fm["version"] = int(fm.get("version", 1) or 1) + 1
    body = parsed.body
    if note:
        from api.services.entity_merge import append_note

        body = append_note(body, note)
    markdown_parser.write(old, fm, body)
    paths = [f"entities/{page_id}.md"]
    removed = None
    if new_id != page_id:
        old.replace(entities / f"{new_id}.md")
        removed = f"entities/{page_id}.md"
        paths += rename_references(memory_path, page_id, old_name, new_id, new_name)
    elif old_name != new_name:
        # Same id (only the spelling moved): no edge names a title, so only other pages' links by name change.
        from api.services.entity_merge import repoint_references

        paths += repoint_references(memory_path, page_id, old_name, page_id, new_name)
    paths.append(f"entities/{new_id}.md")
    return Outcome(new_id, "named" if named else "retitled", list(dict.fromkeys(paths)), removed=removed)


def answer_name(memory_path: Path, page_id: str, role_key: str, answer: str, owner_fm: dict | None) -> Outcome:
    """The person named the placeholder. Exactly one person page already called that (name or alias): the
    placeholder merges into it — the person's own answer is the evidence. Otherwise the page takes the name; a
    person page whose name contains it or is contained in it ("Carl" / "Carl Example"), or several pages of exactly
    that name, get a "Possible duplicate" question each — never a merge."""
    name = check_name(answer, owner_fm, role_key)
    matches = same_name(memory_path, name, exclude=page_id)
    if len(matches) == 1:
        return merge_into(memory_path, page_id, matches[0], role_key, owner_fm,
                          f"\n\n_Named in the inbox: Cicada knew this person only as your {role_key}._")
    outcome = rename(memory_path, page_id, name, owner_fm, named=True,
                     note=f"\n\n_Named in the inbox: Cicada knew this person only as your {role_key}._")
    path = Path(memory_path) / "entities" / f"{outcome.page_id}.md"
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    _add_role(fm, role_key)
    markdown_parser.write(path, fm, parsed.body)
    from api.services.clarification_manager import ClarificationManager

    others = matches or [pid for pid, _ in _part_of(memory_path, name, {outcome.page_id})]
    clarifier = ClarificationManager(Path(memory_path))
    for other in others:
        other_name = str(markdown_parser.parse(Path(memory_path) / "entities" / f"{other}.md").frontmatter.get(
            "name") or other)
        item = clarifier.create(entity_name=name, source_episode="", uncertainty_type=f"Possible duplicate of {other_name}",
                                suggested_classification="person", suggested_confidence=0.5,
                                source_context=f"{name} was named in the inbox; {other_name} is already a person in "
                                               "this memory.")
        if item:
            # The suggestion's subject is the renamed page and its candidate the other page, by id (a name may not
            # round-trip to its id). Answering "merge" folds one page into the other (`_resolve_clarification`).
            item_path = Path(memory_path) / "inbox" / f"{item}.md"
            item_parsed = markdown_parser.parse(item_path)
            item_parsed.frontmatter["entity_id"] = outcome.page_id
            item_parsed.frontmatter["merge_target_hint"] = other
            # The subject was a page when this was asked, and the person is told so: a "merge" folds that page in
            # (`inbox_service._resolve_clarification`). An item without the flag keeps the note-only answer.
            item_parsed.frontmatter[FOLD_PAGE_KEY] = True
            markdown_parser.write(item_path, item_parsed.frontmatter, item_parsed.body)
            outcome.suggested.append(f"inbox/{item}.md")
    return outcome


def decline(memory_path: Path, page_id: str, role_key: str, owner_fm: dict | None) -> Outcome:
    """"I'd rather not say": the page stays a role page, titled by the role (never the owner's name), and is not
    asked about again."""
    memory_path = Path(memory_path)
    path = memory_path / "entities" / f"{page_id}.md"
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    names = owner_names(owner_fm)
    role = parse(str(fm.get("name") or ""), names, bare=True)
    fm[DECLINED_KEY] = True
    fm[UNNAMED_KEY] = True
    _add_role(fm, role_key)
    markdown_parser.write(path, fm, parsed.body)
    if role is not None and role.marked:
        title = _role_title(memory_path, role, page_id)
        return Outcome(**{**rename(memory_path, page_id, title, owner_fm, named=False, note=None).__dict__,
                          "action": "declined"})
    return Outcome(page_id, "declined", [f"entities/{page_id}.md"])


def _role_title(memory_path: Path, role: Role, own: str) -> str:
    """The role title for a page, unique among pages: "Partner", else "Partner (another)" (never a number — a
    title one letter away from another is the same name to Stage 2's fuzzy match)."""
    entities = Path(memory_path) / "entities"
    title, n = role.title, 1
    while True:
        slug = sanitize_id(title)
        if slug == own or not (entities / f"{slug}.md").exists():
            return title
        title = f"{role.title} (another)" if n == 1 else f"{role.title} (another {n})"
        n += 1


# ---------------------------------------------------------------- the repair


class SleepRunning(RuntimeError):
    """Sleep is running or holds the pages: the repair writes nothing."""


@dataclass
class Plan:
    """What the repair finds (dry run) or did (``--apply``). Counts only leave the module."""

    owner_id: str | None = None
    placeholders: int = 0
    merges: list[tuple[str, str, str]] = field(default_factory=list)       # (page, named person, role key)
    retitles: list[tuple[str, str, str]] = field(default_factory=list)     # (page, role title, role key)
    unchanged: list[tuple[str, str]] = field(default_factory=list)         # (page, role key): titled already
    ambiguous: int = 0       # a singular relation more than one named person holds on the record
    declined: int = 0
    already_asked: int = 0
    asked: int = 0
    dirty: int = 0
    written: int = 0
    applied: bool = False
    committed: bool = False

    def counts(self) -> dict:
        done = self.applied
        return {
            "owner_page": self.owner_id is not None,
            "placeholder_pages": self.placeholders,
            ("merged" if done else "would_merge"): len(self.merges),
            ("retitled" if done else "would_retitle"): len(self.retitles),
            "titled_already": len(self.unchanged),
            ("asked" if done else "would_ask"): self.asked,
            "singular_role_ambiguous": self.ambiguous,
            "declined_before": self.declined,
            "questions_open": self.already_asked,
            "skipped_dirty": self.dirty,
            "paths_written": self.written,
            "committed": done,
        }


def _load_pages(memory_path: Path) -> dict[str, tuple[dict, str]]:
    out = {}
    for path in sorted((Path(memory_path) / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 - an unreadable page is left alone
            continue
        out[path.stem] = (dict(parsed.frontmatter), parsed.body)
    return out


def _owner(pages: dict[str, tuple[dict, str]], memory_path: Path, settings=None) -> str | None:
    from api.services import owner_identity

    existing = [{"id": pid, "frontmatter": fm} for pid, (fm, _b) in pages.items()]
    return owner_identity.owner_page_id(existing, memory_path, settings)


def _tokens(label: str) -> list[str]:
    return [t for t in re.split(r"[-_\s]+", str(label or "").lower()) if t]


def _names_role(label: str, head: str, *, from_owner: bool) -> bool:
    """Does a predicate or edge label name exactly this relation? From the person to the owner: "<head>",
    "<head>-of" or "is-<head>-of" — "father-of" does, "father-in-law-of", "step-father-of" and "former-father-of" do
    not. From the owner to the person: "has-<head>", or the same forms for a symmetric relation ("partner-of") —
    "business-partner-of" does not. Any other token makes it another relation, and no evidence."""
    tokens = _tokens(label)
    exact = tokens in ([head], [head, "of"], ["is", head, "of"])
    if from_owner:
        return tokens in (["has", head], ["tiene", head]) or (head in {"partner", "spouse", "pareja"} and exact)
    return exact


def evidence_holders(memory_path: Path, pages: dict[str, tuple[dict, str]], owner_id: str, role: Role,
                     placeholders: set[str]) -> set[str]:
    """Named person pages the record says hold ``role``: ``owner_roles`` (the person said so), an open claim between
    the owner and the page whose predicate names the relation, or an edge in ``graph_edges.yaml`` that does."""
    from api.services.claims import is_event, parse_claims

    named = {pid for pid, (fm, _b) in pages.items()
             if pid != owner_id and pid not in placeholders and _person(fm) and not fm.get(UNNAMED_KEY)
             and str(fm.get("status") or "") != "dropped"}
    holders = {pid for pid in named if role.key in roles_of(pages[pid][0])}

    def consider(subject: str, obj: str, label: str) -> None:
        if subject in named and obj == owner_id and _names_role(label, role.head, from_owner=False):
            holders.add(subject)
        elif subject == owner_id and obj in named and _names_role(label, role.head, from_owner=True):
            holders.add(obj)

    for pid in [owner_id, *sorted(named)]:
        try:
            claims = parse_claims(pages[pid][1])
        except Exception:  # noqa: BLE001 - an unreadable block is no evidence
            continue
        for c in claims:
            # A dated happening is not a relation, and a closed or replaced claim no longer holds one.
            if c.object_kind == "literal" or is_event(c) or c.valid_to or c.superseded_by:
                continue
            consider(str(c.subject or ""), str(c.object or ""), c.predicate)
    edges_file = Path(memory_path) / "graph_edges.yaml"
    if edges_file.is_file():
        try:
            data = yaml.safe_load(edges_file.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            data = {}
        for e in data.get("edges", []) or []:
            if isinstance(e, dict):
                consider(str(e.get("source") or ""), str(e.get("target") or ""), str(e.get("label") or ""))
    return holders


def _rank(item: tuple[str, dict]) -> tuple:
    pid, fm = item
    live = 0 if str(fm.get("status") or "active") == "active" else 1
    return (live, -float(fm.get("confidence", 0) or 0), -len(fm.get("source_episodes") or []), pid)


def survey(memory_path: Path, *, settings=None) -> Plan:
    """What the repair would do, without writing: each placeholder person page merges into the one named person
    the record says holds a singular relation, or is retitled by its relation and asked about."""
    memory_path = Path(memory_path)
    pages = _load_pages(memory_path)
    plan = Plan(owner_id=_owner(pages, memory_path, settings))
    owner_fm = pages[plan.owner_id][0] if plan.owner_id in pages else None
    names = owner_names(owner_fm)
    found: dict[str, Role] = {}
    for pid, (fm, _b) in pages.items():
        if pid == plan.owner_id or fm.get("owner") or not _person(fm) or str(fm.get("status") or "") == "dropped":
            continue
        role = parse(str(fm.get("name") or ""), names, bare=bool(fm.get(UNNAMED_KEY)))
        if role is None and fm.get(UNNAMED_KEY) and roles_of(fm):
            role = parse(roles_of(fm)[0], names, bare=True)
        if role is not None:
            found[pid] = role
    plan.placeholders = len(found)
    placeholder_ids = set(found)
    titles_taken: set[str] = set()
    # A page already at its title's id keeps it; then the live, most-held pages first.
    order = sorted(((p, pages[p][0]) for p in found),
                   key=lambda item: (item[0] != sanitize_id(found[item[0]].title), *_rank(item)))
    for pid, fm in order:
        role = found[pid]
        if role.singular and plan.owner_id:
            holders = evidence_holders(memory_path, pages, plan.owner_id, role, placeholder_ids)
            if len(holders) == 1:
                plan.merges.append((pid, next(iter(holders)), role.key))
                continue
            if len(holders) > 1:
                plan.ambiguous += 1
        title = role.title
        n = 1
        while sanitize_id(title) in titles_taken or (
                sanitize_id(title) != pid and sanitize_id(title) in pages and sanitize_id(title) not in found):
            title = f"{role.title} (another)" if n == 1 else f"{role.title} (another {n})"
            n += 1
        titles_taken.add(sanitize_id(title))
        if str(fm.get("name") or "") == title and fm.get(UNNAMED_KEY) and role.key in roles_of(fm):
            plan.unchanged.append((pid, role.key))
        else:
            plan.retitles.append((pid, title, role.key))
        if fm.get(DECLINED_KEY):
            plan.declined += 1
        elif open_question(memory_path, pid) is not None:
            plan.already_asked += 1
        else:
            plan.asked += 1
    return plan


def _rename_footprint(memory_path: Path, page_id: str, new_name: str) -> list[str]:
    """Every path a retitle would write, before it runs: the page, its new id, ``graph_edges.yaml`` when an edge names
    the page, and each page whose references the shared matcher (``entity_merge._repoint_page``) would move — so a
    page someone else is editing is never swept into the repair's commit."""
    from api.services import entity_merge

    entities = Path(memory_path) / "entities"
    old_name = str(markdown_parser.parse(entities / f"{page_id}.md").frontmatter.get("name") or page_id)
    new_id = sanitize_id(new_name)
    paths = [f"entities/{page_id}.md", f"entities/{new_id}.md"]
    if entity_merge._edges_name(memory_path, page_id):
        paths.append("graph_edges.yaml")
    old = entity_merge._names(page_id, old_name)
    pattern = entity_merge._wikilink_re(page_id, old_name)
    for ep in sorted(entities.glob("*.md")):
        if ep.stem in (page_id, new_id):
            continue
        if entity_merge._repoint_page(ep, old, page_id, new_id, new_name, pattern, warn=False)[0]:
            paths.append(f"entities/{ep.name}")
    return paths


def apply(memory_path: Path, *, sleep_running: Callable[[], bool], settings=None) -> Plan:
    """Write the survey's merges, retitles and questions, and commit them in ONE ``cicada`` commit. Raises
    :class:`SleepRunning` before writing anything while Sleep runs or holds the pages; a page dirty in git (or one
    a merge would touch) is skipped and counted."""
    from api.services import git_service, page_lock, write_admission
    from api.services.entity_merge import merge_footprint

    memory_path = Path(memory_path)
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; repair after it ends")
        with page_lock.page_lock(memory_path):
            plan = survey(memory_path, settings=settings)
            pages = _load_pages(memory_path)
            owner_fm = pages[plan.owner_id][0] if plan.owner_id in pages else None
            has_git = (memory_path / ".git").exists()

            # What someone else left uncommitted, read ONCE before this run writes anything. Asked per step, git
            # would also report this run's own writes (the merge's `graph_edges.yaml`, the pages a retitle
            # repointed) and every later step touching them was skipped as "dirty" — 5 of 6 on a clean tree.
            others_dirty = frozenset(git_service.dirty_paths_sync(memory_path)) if has_git else frozenset()

            def dirty(paths: list[str]) -> bool:
                return bool(others_dirty.intersection(paths))

            written: list[str] = []
            lines: list[str] = []
            done_merges, done_retitles = [], []
            for pid, winner, key in plan.merges:
                footprint = merge_footprint(memory_path, pid, winner)
                if dirty(footprint):
                    plan.dirty += 1
                    continue
                out = merge_into(memory_path, pid, winner, key, owner_fm,
                                 f"\n\n_Merged the page Cicada kept for your {key}: the record names this person "
                                 f"as your {key}._")
                done_merges.append((pid, winner, key))
                written += out.paths
                lines += [f"{p}: removed (merged, trigger: {TRIGGER})" if p == out.removed
                          else f"{p}: updated (trigger: {TRIGGER})" for p in out.paths]
            ask_ids: list[str] = [pid for pid, _k in plan.unchanged]
            for pid, title, key in plan.retitles:
                if dirty(_rename_footprint(memory_path, pid, title)):
                    plan.dirty += 1
                    continue
                page = memory_path / "entities" / f"{pid}.md"
                parsed = markdown_parser.parse(page)
                fm = dict(parsed.frontmatter)
                fm[UNNAMED_KEY] = True
                _add_role(fm, key)
                markdown_parser.write(page, fm, parsed.body)
                if str(fm.get("name") or "") != title:
                    out = rename(memory_path, pid, title, owner_fm, named=False, note=None)
                else:
                    out = Outcome(pid, "retitled", [f"entities/{pid}.md"])
                done_retitles.append((pid, title, key))
                ask_ids.append(out.page_id)
                written += out.paths
                lines += [f"{p}: removed (renamed, trigger: {TRIGGER})" if p == out.removed
                          else f"{p}: updated (trigger: {TRIGGER})" for p in out.paths]
            asked = 0
            for page_id in ask_ids:
                path = ensure_question(memory_path, page_id, owner_fm=owner_fm)
                if path is not None:
                    asked += 1
                    rel = f"inbox/{path.name}"
                    written.append(rel)
                    lines.append(f"{rel}: created (trigger: {TRIGGER})")
            plan.merges, plan.retitles, plan.asked = done_merges, done_retitles, asked
            written = list(dict.fromkeys(written))
            plan.written = len(written)
            plan.applied = True
            if written and has_git:
                message = git_service.build_commit_message(
                    f"Placeholder people: {len(done_merges)} merged, {len(done_retitles)} retitled, {asked} asked",
                    list(dict.fromkeys(lines)), authors=["cicada"])
                git_service.commit_paths_sync(memory_path, message, written)
                plan.committed = True
    if plan.written:
        logger.info(f"placeholder people: {plan.written} path(s) written")
    return plan
