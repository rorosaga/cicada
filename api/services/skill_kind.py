"""What kind of skill this is — ``about-you``, ``generic`` or ``unknown`` (TODO ruling 35 §5, G201 slice (a)).

Ruling 35 splits skills by how fast a model absorbs them: an **about-you** skill carries what Cicada is uniquely
placed to know — the person's preferences, people, projects, their own workflows — and never expires by age; a
**generic** one (a how-to-code correction) is what models absorb fastest, so it must keep re-proving itself. This
module only *tags*; nothing here retires anything (that is slices (b)–(d)).

**The rule, no model call:**

- A skill from a plugin, a GitHub repo, `npx skills`, the catalog or a tool — third-party text, written for everyone —
  is ``generic``. So are Cicada's own bundles (they teach any agent how to use Cicada, not who the person is).
- A candidate (a skill Sleep noticed — held or a page — an agent's draft, or a published draft) is ``about-you`` when
  its own links reach the person's world: Stage 4's evidence pages (a page's ``related``, a held skill's
  ``evidence_ids``) or the ``[[wikilinks]]`` in a draft's text name a ``person`` or ``project`` page, or the owner's
  page. Those links are what the pattern was *seen with* (``skill_grounding``: the entities that came up together in
  the conversations it grounds on), so a skill drawn on the person's own projects and people is about how they work.
  ``company`` is left out on purpose: a skill drawn on a vendor ("deploy to <vendor>") is as often generic.
- Anything else is ``unknown``: a candidate drawn only on tools and concepts may be a generic correction or the
  person's own workflow, and telling those apart needs a reading this rule does not do. A local skill folder of
  unknown origin is ``unknown`` too — it may well be the person's own.

**The person decides.** Their choice (``skill_store.set_kind``, one small file outside every bank) wins over the rule,
per key; clearing it returns the rule's answer.
"""
from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

ABOUT_YOU = "about-you"
GENERIC = "generic"
UNKNOWN = "unknown"
KINDS = (ABOUT_YOU, GENERIC, UNKNOWN)
#: Page types that make a candidate about the person (owner's page counts too).
PERSONAL_TYPES = frozenset({"person", "project"})
#: Where a skill came from, as `skill_inventory` names it: third-party text, written for everyone.
GENERIC_ORIGINS = frozenset({"github", "npx", "catalog", "tool", "cicada", "plugin"})
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


def key(group: str, name: str) -> str:
    """The stable key a person's choice is stored under: ``installed:<name>``, ``plugin:<id>/<skill>``,
    ``draft:<name>`` or ``noticed:<id>``."""
    return f"{group}:{name}"


class Personal:
    """The bank's personal page ids (``person``/``project`` pages and the owner's), read once per snapshot."""

    def __init__(self, bank: Path | None):
        self.ids: frozenset[str] = frozenset()
        if bank is None:
            return
        try:
            from api.services import bank_index

            self.ids = frozenset(
                f.stem for f in bank_index.files(bank, "entities")
                if str(f.frontmatter.get("type") or "") in PERSONAL_TYPES or f.frontmatter.get("owner") is True)
        except Exception as exc:  # noqa: BLE001 — a bank problem tags nothing about-you; it never empties the page
            logger.warning(f"skill_kind: personal pages unread ({type(exc).__name__})")

    def touches(self, refs) -> bool:
        return any(str(r or "").strip() in self.ids for r in refs or [])


def links(text: str) -> list[str]:
    return [m.strip() for m in _WIKILINK.findall(text or "")]


def by_origin(origin: str) -> str:
    """An installed skill's kind from where it came from; a draft's is decided from its text instead."""
    return GENERIC if origin in GENERIC_ORIGINS else UNKNOWN


def candidate(refs, personal: Personal) -> str:
    return ABOUT_YOU if personal.touches(refs) else UNKNOWN


def resolve(rule: str, override: str | None) -> tuple[str, str]:
    """``(kind, by)`` — the person's choice when there is one, else the rule's."""
    if override in KINDS:
        return override, "person"
    return rule, "cicada"
