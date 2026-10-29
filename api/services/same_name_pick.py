"""Pick the page: one question per mention said as a title several pages share (G227, owner 2026-10-29).

Owner ruling: "a mention that could be any of several same-named pages asks one question with one option per
candidate page plus 'none of these'; picking one merges the held mention into that page by id; 'none of these' lets
Sleep make a new page." Stage 2 keeps the candidates on the question as ``same_title`` (ids, `clarification_manager`);
this module turns them into the question's options **at read** — the labels carry each page's qualifier, which is
derived and would go stale if stored — and turns a picked key back into the inbox's own verbs:

- ``page:<id>`` → ``merge`` into that page (the merge branch of `inbox_service._resolve_clarification`, which already
  folds a held mention — G209 — into the page it is given);
- ``none`` → ``reject`` against EVERY candidate (`merge_rejections`), so the next Sleep neither joins nor asks about
  any of them, and the mention, once over the promotion bar, gets a page of its own (a clean title and a distinct
  id — `entity_resolver._another_id`).

A key for a page that is no longer a candidate (dropped, merged away) is refused, never guessed. Pure apart from the
page lookups it is handed; engine-free.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

#: Bumped into `GET /inbox`'s ETag: same-title questions gained derived ``question``/``options`` (and options their
#: additive ``pageId``/``pageName``/``qualifier``).
SHAPE = "pick-1"
NONE_KEY = "none"
PAGE_PREFIX = "page:"
NONE_LABEL = "None of these"
NONE_LABEL_ONE = "No, another one"

Lookup = Callable[[str], "dict | None"]


def applies(fm: dict) -> bool:
    """A duplicate question Stage 2 raised about a name pages share (it carries ``same_title``)."""
    return str((fm or {}).get("kind") or "") == "merge_suggestion" and bool(_stored(fm))


def _stored(fm: dict) -> list[str]:
    raw = (fm or {}).get("same_title")
    return [str(p) for p in raw if isinstance(p, str) and p.strip()] if isinstance(raw, list) else []


def bank_lookup(memory_path) -> Lookup:
    """A page's frontmatter by id from `bank_index` (one cached header read), or None when it is gone."""
    from api.services import bank_index

    def lookup(pid: str) -> dict | None:
        found = bank_index.file(Path(memory_path), "entities", f"{pid}.md")
        return dict(found.frontmatter or {}) if found is not None else None

    return lookup


def candidates(fm: dict, lookup: Lookup) -> list[tuple[str, dict]]:
    """``[(id, frontmatter)]`` — the stored candidates still on disk and not dropped, in the stored order."""
    out: list[tuple[str, dict]] = []
    for pid in dict.fromkeys(_stored(fm)):
        page = lookup(pid)
        if page is not None and str(page.get("status") or "") != "dropped":
            out.append((pid, page))
    return out


def _name(fm: dict) -> str:
    return " ".join(str(fm.get("entity_name") or fm.get("entity_mention") or fm.get("entity_id") or "").split())


def options(memory_path, fm: dict, lookup: Lookup | None = None) -> list[dict]:
    """The options a same-title question is served with: one per candidate page — ``{key: "page:<id>", label:
    "<name> (<qualifier>)", page_id, page_name, qualifier}`` — then ``none``. The label carries the qualifier in text
    for every reader without the tag (an agent, an older app); the app draws ``page_name`` with ``qualifier`` as its
    tag. A candidate whose title is its own (the mention's only same-titled page) is qualified by its type word.
    Empty when the item is not one of these or no candidate is left."""
    from api.services import same_name

    if not applies(fm):
        return []
    lookup = lookup or bank_lookup(memory_path)
    pages = candidates(fm, lookup)
    if not pages:
        return []
    shared = same_name.qualifiers(memory_path) if memory_path is not None else {}
    out = []
    for pid, page in pages:
        name = " ".join(str(page.get("name") or pid).split())
        kind = str(page.get("type") or "").strip().lower()
        qualifier = shared.get(pid) or same_name.TYPE_WORDS.get(kind) or None
        out.append({"key": f"{PAGE_PREFIX}{pid}", "label": same_name.display(name, qualifier),
                    "page_id": pid, "page_name": name, "qualifier": qualifier})
    out.append({"key": NONE_KEY, "label": NONE_LABEL if len(pages) > 1 else NONE_LABEL_ONE})
    return out


def question(fm: dict, count: int) -> str:
    """The question in words: "Which <name> is this?" over two or more pages; over one, "Is this <name>?"."""
    name = _name(fm) or "this"
    return f"Which {name} is this?" if count > 1 else f"Is this the {name} you already have?"


def picked(fm: dict, key: str | None, lookup: Lookup) -> tuple[str, str] | None:
    """A served key as the inbox's verb: ``("merge", <id>)``, ``("none", "")``, or None when the key is not one of
    this question's (the caller refuses it). A ``page:`` key must name a candidate still on disk."""
    key = str(key or "").strip()
    if not applies(fm) or not key:
        return None
    if key == NONE_KEY:
        return "none", ""
    if key.startswith(PAGE_PREFIX):
        pid = key[len(PAGE_PREFIX):]
        if any(pid == cid for cid, _ in candidates(fm, lookup)):
            return "merge", pid
    return None


def rejected_ids(fm: dict) -> list[str]:
    """Every page "none of these" keeps the mention apart from: all stored candidates (one gone since is harmless)."""
    return list(dict.fromkeys(_stored(fm)))
