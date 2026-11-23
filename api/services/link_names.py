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
(G227: two people who share a name are two pages, and a link to the shared name means neither). An ambiguous or unknown
spelling stays as written; nothing is guessed from similarity, no page is renamed or merged, and a plain mention with no
brackets ("<owner>'s partner") is never touched. Only text Sleep is about to add is rewritten (never a passage already
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


class Names:
    """Every page's names, from the pages as Stage 3 reads them: ``resolve`` answers the one page a spelling means."""

    def __init__(self, pages=()) -> None:
        self._holders: dict[str, set[str]] = {}
        self.names: dict[str, str] = {}
        for page in pages or ():
            fm = page.get("frontmatter") or {}
            page_id = str(page.get("id") or "").strip()
            if not page_id or str(fm.get("status") or "") == "dropped":
                continue
            name = str(fm.get("name") or "").strip() or page_id.replace("-", " ").title()
            self.names[page_id] = name
            aliases = fm.get("aliases") if isinstance(fm.get("aliases"), list) else []
            for spelling in (name, page_id, page_id.replace("-", " "), *(str(a) for a in aliases if a)):
                if _key(spelling):
                    self._holders.setdefault(_key(spelling), set()).add(page_id)

    def resolve(self, spelling: str) -> str | None:
        """The id of the one page ``spelling`` means, or ``None`` (unknown, or two or more pages answer to it)."""
        held = self._holders.get(_key(spelling)) or set()
        return next(iter(held)) if len(held) == 1 else None

    def canonical(self, spelling: str) -> str | None:
        """The name of the one page ``spelling`` means, when that name is safe to write in a link and resolves back to
        that page alone; else ``None``."""
        page_id = self.resolve(spelling)
        if page_id is None:
            return None
        name = self.names[page_id]
        if _UNSAFE.search(name) or self.resolve(name) != page_id:
            return None
        return name


def rewrite(text: str, names: Names) -> tuple[str, list[tuple[str, str]]]:
    """``text`` with each ``[[link]]`` whose target is another spelling of one page rewritten to the page's name; the
    ``(was, now)`` pairs. A link already spelled as the page's name is left exactly as it is."""
    changes: list[tuple[str, str]] = []

    def swap(match: re.Match) -> str:
        target, display = match.group(1), match.group(2) or ""
        spelled = target.strip()
        name = names.canonical(spelled)
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


def rewrite_entity(entity: dict, names: Names) -> int:
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
        new, done = rewrite(text, names)
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


def rewrite_changes(changes: list[dict], pages: list[dict]) -> int:
    """Stage 3's step: every create and update's extraction, against the pages that exist. Returns links rewritten."""
    names = Names(pages)
    total = 0
    for change in changes:
        if change.get("action") in ("create", "update") and isinstance(change.get("entity"), dict):
            total += rewrite_entity(change["entity"], names)
    return total
