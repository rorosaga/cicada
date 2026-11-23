"""A link in new text is written under the page's own name (G148 / G194, owner report 2026-11-23).

Stage 1 reads each conversation alone, so it writes ``[[Girlfriend]]`` in one summary, ``[[<nickname>]]`` in the next and
``[[<owner>'s girlfriend]]`` in a third. Stage 2 resolves every one of them to the one page that holds those names, but
the text kept the spelling. One page then read as four people: equal facts stopped being equal (`fact_policy.restates`
compares the words), the graph drew no ``mentions`` edge for a link that names an alias (`wikilink_resolver` indexes
names and ids), and the article writer narrated each spelling as a separate person.

**Rewritten, not piped.** A link's target is rewritten to the page's name (``[[Girlfriend]]`` -> ``[[Alice Example]]``)
rather than piped (``[[Alice Example|Girlfriend]]``). Every reader unwraps a piped link to its display text
(`fact_policy.normalized`, the app's ``linkifyWikilinks``), so the piped form keeps the four spellings the equality check
and the article writer read, while the rewritten form is one string to all of them and to the graph. Nothing is lost
with the word: the person's own words are the conversation's, the evidence spans point there (G118), and the alias stays
on the page's ``aliases``. A link the writer piped on purpose (``[[Girlfriend|she]]``) keeps its display text; only its
target is rewritten.

**Only a resolution that is certain.** A spelling is rewritten when exactly one page answers to it (a name, an alias, an
id) and the page's own name resolves back to that page and no other — the same test `id_utils.link_targets` applies
(G227: two people who share a name are two pages, and a link to the shared name means neither) — AND the spelling is
*scoped* to that page (`Scope`, review 2026-11-23): a page carries generic aliases ("girlfriend", "partner", even "she")
that mean a different person in another conversation, and Stage 2 may have declined to resolve the very same word
(`role_people`: a relation-only person is merged only on the person's answer or evidence on the record). So a bank-wide
match alone never rewrites. It does when (a) Stage 2 resolved that spelling to the page in this same batch (an
extraction on the page's change was named so, or listed it among its aliases), (b) the spelling is the page's own name
or id in another case or spacing (never an alias), or (c) the page being written already relates to the target (its
`related`, its ``## Related`` block, a link under the target's own name, a claim naming it), so the alias is read inside
that page's own neighbourhood. An ambiguous, unknown or unscoped spelling stays as written; nothing is guessed from
similarity, no page is renamed or merged, and a plain mention with no brackets ("<owner>'s partner") is never touched. Only text Sleep is about to add is rewritten (never a passage already
on a page, never a person's or an agent's words), so no existing bullet's source rows (G118) change.

Pure and engine-free.
"""
from __future__ import annotations

import re
import unicodedata

#: ``[[target]]`` or ``[[target|display]]``; a target never spans lines.
_LINK = re.compile(r"\[\[([^\[\]|\n]+?)(\|[^\[\]\n]*)?\]\]")
_UNSAFE = re.compile(r"[\[\]|\n]")


def _key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", str(text or "")).casefold().split())


#: Transient key on a merged extraction: every name its inputs were extracted under (`entity_resolver._merge_entity_payload`
#: keeps only the preferred name, so a spelling Stage 2 resolved onto a page would otherwise be lost). Never serialized.
SAID_AS = "_said_as"


class Names:
    """Every page's names, from the pages as Stage 3 reads them: ``resolve`` answers the one page a spelling means."""

    def __init__(self, pages=()) -> None:
        self._holders: dict[str, set[str]] = {}
        self._own: dict[str, set[str]] = {}
        self._pages: dict[str, dict] = {}
        self._relations: dict[str, frozenset[str]] = {}
        self.names: dict[str, str] = {}
        self.aliases: dict[str, list[str]] = {}   # a page's other names, as the page lists them
        for page in pages or ():
            fm = page.get("frontmatter") or {}
            page_id = str(page.get("id") or "").strip()
            if not page_id or str(fm.get("status") or "") == "dropped":
                continue
            name = str(fm.get("name") or "").strip() or page_id.replace("-", " ").title()
            self.names[page_id] = name
            self._pages[page_id] = page
            for spelling in (name, page_id, page_id.replace("-", " ")):
                if _key(spelling):
                    self._own.setdefault(_key(spelling), set()).add(page_id)
            aliases = fm.get("aliases") if isinstance(fm.get("aliases"), list) else []
            self.aliases[page_id] = [str(a) for a in aliases if a and _key(str(a)) != _key(name)]
            for spelling in (name, page_id, page_id.replace("-", " "), *(str(a) for a in aliases if a)):
                if _key(spelling):
                    self._holders.setdefault(_key(spelling), set()).add(page_id)

    def resolve(self, spelling: str) -> str | None:
        """The id of the one page ``spelling`` means, or ``None`` (unknown, or two or more pages answer to it)."""
        held = self._holders.get(_key(spelling)) or set()
        return next(iter(held)) if len(held) == 1 else None

    def is_own(self, spelling: str, page_id: str) -> bool:
        """``spelling`` is the page's name or id (any case or spacing), not one of its aliases."""
        return page_id in (self._own.get(_key(spelling)) or ())

    def relations(self, page_id: str) -> frozenset[str]:
        """The ids of the pages this page already relates to: its ``related`` slugs, a link in its body written under
        a page's own name (its ``## Related`` block included), a claim whose object is a page."""
        if page_id in self._relations:
            return self._relations[page_id]
        page = self._pages.get(page_id) or {}
        found: set[str] = set()
        for slug in (page.get("frontmatter") or {}).get("related") or []:
            if str(slug).strip() in self._pages:
                found.add(str(slug).strip())
            elif (held := self._own.get(_key(slug))) and len(held) == 1:
                found |= held
        body = str(page.get("body") or "")
        for match in _LINK.finditer(body):
            held = self._own.get(_key(match.group(1)))
            if held and len(held) == 1:
                found |= held
        try:
            from api.services.claims import parse_claims

            found |= {c.object for c in parse_claims(body) if c.object_kind == "node" and c.object in self._pages}
        except Exception:  # noqa: BLE001 - an unreadable fence costs the relation, never the write
            pass
        found.discard(page_id)
        self._relations[page_id] = frozenset(found)
        return self._relations[page_id]

    def scope(self, page_id: str | None, said=()) -> "Scope":
        """The scope for the page being written (``page_id``) and the spellings Stage 2 resolved in this batch."""
        return Scope(self, page_id, said)

    def canonical(self, spelling: str, scope: "Scope | None" = None) -> str | None:
        """The name of the one page ``spelling`` means, when that name is safe to write in a link and resolves back to
        that page alone — and, given a ``scope``, the spelling is read as that page inside it; else ``None``."""
        page_id = self.resolve(spelling)
        if page_id is None:
            return None
        if scope is not None and not scope.allows(spelling, page_id):
            return None
        name = self.names[page_id]
        if _UNSAFE.search(name) or self.resolve(name) != page_id:
            return None
        return name


class Scope:
    """Where a spelling may be read as a page: the page being written, and the spellings Stage 2 resolved this batch
    (``said``: lowercased keys, from the extractions of the target page's own change). ``Names.canonical`` consults it."""

    def __init__(self, names: Names, page_id: str | None, said=()) -> None:
        self.names = names
        self.page_id = page_id
        self.said = said if isinstance(said, dict) else {}   # target id -> {spelling keys}

    def canonical(self, spelling: str) -> str | None:
        """`Names.canonical` read inside this scope (the same call, so a caller takes either)."""
        return self.names.canonical(spelling, self)

    def allows(self, spelling: str, target: str) -> bool:
        if self.names.is_own(spelling, target):                       # (b)
            return True
        if _key(spelling) in (self.said.get(target) or ()):          # (a)
            return True
        return bool(self.page_id) and target in self.names.relations(self.page_id)   # (c)


def rewrite(text: str, names: Names, scope: "Scope | None" = None) -> tuple[str, list[tuple[str, str]]]:
    """``text`` with each ``[[link]]`` whose target is another spelling of one page rewritten to the page's name; the
    ``(was, now)`` pairs. A link already spelled as the page's name is left exactly as it is."""
    changes: list[tuple[str, str]] = []

    def swap(match: re.Match) -> str:
        target, display = match.group(1), match.group(2) or ""
        spelled = target.strip()
        name = names.canonical(spelled, scope)
        if name is None or name == spelled:
            return match.group(0)
        changes.append((spelled, name))
        return f"[[{name}{display}]]"

    if "[[" not in str(text or ""):
        return text, changes
    return _LINK.sub(swap, text), changes


#: What each extraction field carries: a list of strings, a string, or dated lines with an ``event``.
_TEXT_FIELDS = ("summary", "description")
_LIST_FIELDS = ("key_facts", "open_questions")


def rewrite_entity(entity: dict, names: Names, scope: "Scope | None" = None) -> int:
    """Rewrite the links in one extraction's Summary, Key Facts, History lines and Open Questions in place, and the
    source rows (`section_provenance.INPUTS`) that carry the same text, so each rewritten item keeps its evidence.
    Returns how many links were rewritten."""
    from api.services import section_provenance

    count = 0
    renamed: dict[str, str] = {}

    def one(text):
        nonlocal count
        if not isinstance(text, str):
            return text
        new, done = rewrite(text, names, scope)
        if done:
            count += len(done)
            renamed[text.strip()] = new.strip()
        return new

    for field in _TEXT_FIELDS:
        if isinstance(entity.get(field), str):
            entity[field] = one(entity[field])
    for field in _LIST_FIELDS:
        if isinstance(entity.get(field), list):
            entity[field] = [one(item) for item in entity[field]]
    if isinstance(entity.get("history_entries"), list):
        for entry in entity["history_entries"]:
            if isinstance(entry, dict) and isinstance(entry.get("event"), str):
                entry["event"] = one(entry["event"])
    if renamed:
        for record in entity.get(section_provenance.INPUTS) or []:
            if isinstance(record, dict) and str(record.get("text") or "").strip() in renamed:
                record["text"] = renamed[str(record["text"]).strip()]
    return count


def batch_said(changes: list[dict]) -> dict[str, set[str]]:
    """``target id -> spelling keys``: every name or alias an extraction on that page's create/update was written under,
    including the names of inputs merged into it (`SAID_AS`) — what Stage 2 resolved onto the page in this batch."""
    said: dict[str, set[str]] = {}
    for change in changes:
        entity = change.get("entity")
        if change.get("action") not in ("create", "update") or not isinstance(entity, dict) or not change.get("id"):
            continue
        held = said.setdefault(str(change["id"]), set())
        for spelling in (entity.get("name"), *(entity.get("aliases") or []), *(entity.get(SAID_AS) or [])):
            if isinstance(spelling, str) and _key(spelling):
                held.add(_key(spelling))
    return said


def rewrite_changes(changes: list[dict], names: Names) -> int:
    """Stage 3's step: every create and update's extraction, against the pages that exist, each scoped to the page it
    is written to (`Scope`). Returns links rewritten."""
    said = batch_said(changes)
    total = 0
    for change in changes:
        if change.get("action") in ("create", "update") and isinstance(change.get("entity"), dict):
            total += rewrite_entity(change["entity"], names, names.scope(str(change.get("id") or "") or None, said))
    return total
