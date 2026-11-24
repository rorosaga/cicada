"""Questions the record already answers (owner 2026-11-24; ruling 29, amended by ruling 74c).

A "Is A the same as B?" question stayed open after the record had answered it, and its text still said "asked, never
joined: only your answer joins them". Measured on a real bank (real values redacted): of 235 open same-as questions, 43
asked about a name that was already a name or alias of the page they asked about, and 10 had both ends resolving to one
page through ``_redirects.yaml``. A merge closes the question between its two pages (``merge_closes``), but a chain of
merges (A into W, W into P) left "A or P?" behind, and a name filed under a page by any of the many writers that add
an alias closed nothing.

This module is the **engine-free reading** of that: given one open question, does the bank already say it? It reads files
only, never a model, never the network, and never writes: the settle is Sleep's own tending (``inbox_tend``, rules
``already_one_page`` / ``already_a_name``, listed under "Settled by Sleep" and undoable like every other), and
``scripts/answered_questions_dry_run.py`` prints what it would settle without writing.

* ``one_page`` — both ends resolve, through redirects, to one page (or the asked name's own id is a redirect to the
  target): there is nothing left to join.
* ``a_name`` — the asked name has no page of its own, exactly one page answers to it (its name or an alias the person has
  not removed), and that page is the one the question asks about. What Sleep still holds on the name's pending line
  (``held``: claims and prose waiting for a page) lands on that page through the question's own resolver, as it would on
  the name's next mention; with nothing held the question is simply closed (``subject_gone`` already does that for a
  name with no line). The pair the person called two (``merge_rejections``), or Sleep split, and the owner's page are
  never read as answered: a name on a page is not an answer to "they are different".

A "which one is this?" question over several pages (``same_title``) is never answered here. Nothing about a conflict or a
clarification is read here, except :func:`labels_one_page`: a conflict whose every value is a name of one page is not a
conflict.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from api.services import text_fold

ONE_PAGE = "already_one_page"
A_NAME = "already_a_name"
LABELS = "names_one_page"
#: The rules this module decides, in the words of the settled list.
WORDS = {
    ONE_PAGE: "The record already answers it: they are one page",
    A_NAME: "The record already answers it: that name is one of this page's names",
    LABELS: "Both values name one person, spelled two ways",
}


@dataclass(frozen=True)
class Answer:
    rule: str
    mention_id: str
    target_id: str
    held: bool = False   # a line in the pending store still holds what was said under the name


def _key(text) -> str:
    return " ".join(text_fold.words(str(text or "")))


def names_of(fm: dict) -> list[str]:
    """A page's name and its aliases, never one the person removed."""
    removed = {_key(a.get("alias") if isinstance(a, dict) else a) for a in (fm.get("aliases_removed") or [])}
    raw = [fm.get("name"), *[a for a in (fm.get("aliases") or []) if isinstance(a, str)]]
    return [str(n) for n in raw if str(n or "").strip() and _key(n) not in removed]


def _pages_answering(memory_path: Path, key: str) -> list[str]:
    from api.services import bank_index

    return [f.stem for f in bank_index.files(Path(memory_path), "entities")
            if key in {_key(n) for n in names_of(f.frontmatter or {})}]


def pair_answer(memory_path: Path, fm: dict) -> Answer | None:
    """The record's answer to one open "same as?" question, or ``None`` (it still needs the person, a conversation or a
    judge). Reads only."""
    from api.services import inbox_tend, merge_rejections, page_redirects, pending_store
    from api.services.id_utils import sanitize_id

    memory_path = Path(memory_path)
    if str(fm.get("kind") or "") != "merge_suggestion" or str(fm.get("status") or "pending") != "pending":
        return None
    if len(fm.get("same_title") or ()) >= 2:
        return None   # "which one is this?" over several pages: the person's pick
    target_hint = str(fm.get("merge_target_hint") or "").strip()
    target = inbox_tend._page(memory_path, target_hint)
    if target is None:
        return None
    if inbox_tend._is_owner_page(target[1]):
        return None   # who the owner is is never read off a name on their page (ruling 29, `pair_evidence`)
    mention_id = str(fm.get("entity_id") or "").strip()
    mention = inbox_tend._page(memory_path, mention_id)
    if mention is not None:
        return Answer(ONE_PAGE, mention[0].stem, target[0].stem) if mention[0] == target[0] else None
    name = " ".join(str(fm.get("entity_name") or fm.get("entity_mention") or "").split())
    if not name:
        return None
    own_id = sanitize_id(name)
    if page_redirects.resolve(memory_path, own_id) == target[0].stem:
        return Answer(ONE_PAGE, own_id, target[0].stem)
    if merge_rejections.is_rejected(memory_path, own_id, target[0].stem) \
            or merge_rejections.is_split(memory_path, own_id, target[0].stem):
        return None
    if _key(name) not in {_key(n) for n in names_of(target[1])}:
        return None
    if _pages_answering(memory_path, _key(name)) != [target[0].stem]:
        return None   # a name two pages answer to says nothing about which one it means
    return Answer(A_NAME, own_id, target[0].stem, held=pending_store.held_line(memory_path, name) is not None)


def labels_one_page(memory_path: Path, fm: dict) -> tuple[str, list[dict]] | None:
    """A conflict whose every value is a name of ONE page (a person written two ways, the second now filed as a name of
    the first): ``(the page's id, the options)``, or ``None``. The caller keeps the option written as the page's own
    name. Reads only."""
    from api.services import inbox_questions

    options = [o for o in inbox_questions.normalize_options(fm.get("options"))
               if str(o.get("key")) not in ("both", "neither", "other", "remind_later") and str(o.get("label") or "").strip()]
    if str(fm.get("kind") or "") != "conflict" or len(options) < 2:
        return None
    keys = {_key(o["label"]) for o in options}
    keys.discard("")
    if len(keys) < 2:
        return None   # one value said twice is `same_value`'s
    pages = None
    for key in keys:
        answering = set(_pages_answering(memory_path, key))
        pages = answering if pages is None else pages & answering
        if not pages:
            return None
    if pages is None or len(pages) != 1:
        return None
    page_id = next(iter(pages))
    # Every value must be a name of that page alone: a label another page also answers to could mean that page.
    if any(_pages_answering(memory_path, key) != [page_id] for key in keys):
        return None
    return page_id, options
