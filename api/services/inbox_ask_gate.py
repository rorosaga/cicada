"""The in-conversation ask gate: is an open inbox question about what the person is talking about NOW?

Owner, 2026-10-14: questions should be "only relevant to the current conversation", come up naturally and be
answered naturally; the inbox is listed whole only when the person asks for it. Before this, an agent was told to
call ``cicada_check_nudges(entity_ids=<recall ids>)`` after every recall and ask what came back, so any question
about a page recall merely TOUCHED was asked at the end of the turn — a conflict about a project's policy, appended
to an answer about who helps on that project.

The rule, in two layers (G115 item 6 named this module; this is its relevance half):

* **The server decides what MAY come up** (this module, pure, engine-free). An item passes only when the
  conversation is about the question's own subject, which is more than its page:

  - its page is in scope: the caller's ``entity_ids`` hold it, or the conversation names it (name, mention, id or
    alias, whole words);
  - and the conversation shares a word with what the question is ABOUT — its predicate, its options, the words of
    the question itself — beyond the page's own name. "Who helps on alpha?" names alpha; it says nothing about
    alpha's policy, so the policy question stays in the inbox.
  - an identity question (``clarification``, ``merge_suggestion``) is about the name itself, so the conversation
    must NAME it; an id handed over by recall is not enough.
  - ``decay`` never passes: a conversation about the page is itself the answer (capture records the mention, and a
    mention lifts decay), and one that is not about it has no business asking. ``normalization`` is app-only.

* **The agent decides whether it FITS** (the contract's words): it asks one in its own words only where it fits
  the turn, never as a banner, and records an answer the person already gave without asking.

Nothing here reads a file, a model or the clock.
"""
from __future__ import annotations

import re

from api.services import text_fold

#: Kinds that never come up in conversation on their own (see the module note).
#: G198: a `page_edit` proposal is the person's to apply in the app — never raised in a conversation either.
NEVER_ASKED = frozenset({"decay", "normalization", "page_edit"})
#: Kinds whose subject is a name: the conversation must say it.
IDENTITY_KINDS = frozenset({"clarification", "merge_suggestion"})

#: Options every card of a kind carries; their labels say nothing about the question's subject.
_GENERIC_KEYS = frozenset({"both", "neither", "other", "remind_later"})

stem = text_fold.stem
terms = text_fold.subject_terms


def names(fm: dict) -> list[str]:
    """Every spelling of the item's page: its name, the mention that raised it, its id with spaces, its aliases."""
    out: list[str] = []
    entity_id = str(fm.get("entity_id") or "")
    for raw in (fm.get("entity_name"), fm.get("entity_mention"), entity_id.replace("-", " ").replace("_", " "),
                *(fm.get("aliases") or [])):
        name = " ".join(text_fold.words(str(raw or "")))
        if len(name) >= 2 and name not in out:
            out.append(name)
    return out


def with_page_names(memory_path, fm: dict) -> dict:
    """``fm`` plus its page's aliases (the item carries only the name it was raised under), read from the cached
    frontmatter scan — so "alpha" names the page whose alias is "Alpha". The item itself is never rewritten."""
    from pathlib import Path

    from api.services import bank_index

    entity_id = str(fm.get("entity_id") or "")
    if not entity_id or memory_path is None:
        return fm
    entry = bank_index.file(Path(memory_path), "entities", f"{entity_id}.md")
    aliases = [str(a) for a in ((entry.frontmatter or {}).get("aliases") or [])] if entry is not None else []
    return {**fm, "aliases": [*(fm.get("aliases") or []), *aliases]} if aliases else fm


def named_in(fm: dict, conversation: str | None) -> bool:
    """Does the conversation say the item's page by one of its spellings, as whole words?"""
    folded = " " + " ".join(text_fold.words(conversation)) + " "
    return any(f" {name} " in folded for name in names(fm))


def subject_terms(fm: dict) -> set[str]:
    """What the question is ABOUT, without its page's own name: the predicate, the options and the question."""
    parts = [str(fm.get("predicate") or "").replace("-", " ").replace("_", " "), str(fm.get("question") or "")]
    for option in fm.get("options") or []:
        if isinstance(option, dict):
            if str(option.get("key") or "") in _GENERIC_KEYS:
                continue   # "Both are true (different contexts)" is the card's wording, not the question's subject
            parts += [str(option.get("label") or ""), str(option.get("value") or "")]
        else:
            parts.append(str(option))
    about = terms(" ".join(parts))
    own = set()
    for name in names(fm):
        own |= terms(name)
    return about - own


#: Subject words an item on an everyday page must share with the conversation (`everyday_names`): its page's name is in
#: a third of the person's conversations, so one shared word ("conversation", "session") is chance, not a topic.
EVERYDAY_TERMS = 2


def relevant(fm: dict, conversation: str | None, entity_ids=(), *, everyday: bool = False) -> tuple[bool, str]:
    """``(passes, reason)`` for one item against what the person is talking about now.

    ``conversation`` is the person's own words this turn (or what the conversation is about now);
    ``entity_ids`` the pages recall returned for it. ``everyday``: the item's page is one the person names in nearly
    every conversation (the owner's own page, their main project; :func:`everyday`) — naming it, or recall handing it
    over, puts nothing in scope, so the conversation must share :data:`EVERYDAY_TERMS` subject words with the question
    (2026-10-27). ``reason`` is an enum, for tests and counts."""
    kind = str(fm.get("kind") or fm.get("type") or "")
    if kind in NEVER_ASKED:
        return False, f"never_asked:{kind}"
    if not (conversation or "").strip():
        return False, "no_conversation"
    said = named_in(fm, conversation)
    if kind in IDENTITY_KINDS:
        return (True, "named") if said else (False, "not_named")
    wanted = {str(e).strip() for e in (entity_ids or []) if str(e).strip()}
    if not (said or str(fm.get("entity_id") or "") in wanted):
        return False, "other_page"
    about = subject_terms(fm)
    if not about:
        # Nothing to compare: a question with no predicate, options or words of its own beyond its page's name.
        return False, "no_subject"
    shared = about & terms(conversation)
    if everyday:
        return (True, "same_subject") if len(shared) >= EVERYDAY_TERMS else (False, "everyday_page")
    return ((True, "same_subject") if shared else (False, "other_subject"))


def everyday(memory_path, fm: dict) -> bool:
    """Is the item's page one the person names in nearly every conversation (`everyday_names`), from the bank alone?
    Measured on the page's own name, never its aliases: one loose alias ("code" on an editor's page) would make any
    page everyday."""
    from api.services import everyday_names

    entity_id = str(fm.get("entity_id") or "")
    own = [" ".join(text_fold.words(str(fm.get("entity_name") or ""))) or entity_id.replace("-", " ")]
    return everyday_names.is_everyday(memory_path, entity_id, own, owner_id=everyday_names.owner_id(memory_path))


_WS = re.compile(r"\s+")


def clean_quote(quote: str | None, limit: int = 500) -> str:
    """The person's words as an agent relays them: one line, outer quotes dropped, at most ``limit`` characters."""
    text = _WS.sub(" ", str(quote or "")).strip().strip("\"'“”‘’").strip()
    return text[:limit]
