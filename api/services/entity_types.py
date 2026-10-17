"""The closed set of entity types, held at every writer that takes a type from a model (2026-10-17).

``EntityType`` is a closed set of 10 and Stage 1 may produce 8 of them (``PRODUCIBLE_ENTITY_TYPES``). The extraction
prompt lists them and a strict-schema engine enforces the enum, but an engine that answers in plain JSON mode (any
LiteLLM model) is held only by the prompt — and a model that writes ``organization``, ``product`` or ``program``
reached the page's frontmatter unchanged: nothing between the extraction and the create branch looked at the type.

:func:`producible` is the one coercion, applied where the type comes in (``entity_extractor.sanitize_entity_type``)
and again where a page is born from it (``conflict_resolver``'s create branch, an inbox answer that creates a page),
the same two-place shape as the decay-class rail (G66). A word the set does not hold maps to the type it plainly
means (``organization`` → ``company``, ``product`` → ``tool``, ``program`` → ``project``); anything else becomes
``concept``. Pure: no I/O, never raises.
"""
from __future__ import annotations

from api.models.schemas import PRODUCIBLE_ENTITY_TYPES, EntityType

ALL_TYPES: frozenset[str] = frozenset(t.value for t in EntityType)
PRODUCIBLE: frozenset[str] = frozenset(t.value for t in PRODUCIBLE_ENTITY_TYPES)
FALLBACK = "concept"

#: Words a model reaches for that the closed set spells differently. Keys are compared lowercased, with spaces,
#: hyphens and underscores folded; the value is always a producible type.
SYNONYMS: dict[str, str] = {
    # company — any organisation, not only a business
    **dict.fromkeys((
        "organization", "organisation", "org", "business", "firm", "corporation", "corp", "enterprise",
        "startup", "employer", "institution", "university", "college", "school", "agency", "nonprofit",
        "non profit", "ngo", "foundation", "brand", "lab", "government", "team", "club", "publisher",
    ), "company"),
    # tool — a thing someone uses
    **dict.fromkeys((
        "product", "app", "application", "software", "service", "library", "framework", "platform", "device",
        "hardware", "api", "sdk", "cli", "package", "website", "web app", "model", "language model", "plugin",
        "extension",
    ), "tool"),
    # project — a thing someone works on over time
    **dict.fromkeys((
        "program", "programme", "initiative", "repository", "repo", "venture", "side project", "task",
        "goal", "plan", "course",
    ), "project"),
    **dict.fromkeys(("people", "human", "individual", "contact", "user", "persona"), "person"),
    **dict.fromkeys(("place", "city", "country", "region", "venue", "address", "building", "office"), "location"),
    **dict.fromkeys(("folder", "path", "file path", "filepath", "dir"), "directory"),
    **dict.fromkeys(("ability", "procedure", "workflow", "preference", "habit"), "skill"),
}


def _key(raw) -> str:
    text = str(raw or "").strip().lower().replace("_", " ").replace("-", " ")
    return " ".join(text.split())


def producible(raw) -> str:
    """The producible type ``raw`` means: itself when it is one, its synonym's type, else ``concept``."""
    key = _key(raw)
    if key in PRODUCIBLE:
        return key
    return SYNONYMS.get(key, FALLBACK)


def known(raw) -> str | None:
    """``raw`` as one of the 10 types (``deadline`` and ``media`` included) when it already is one, else ``None``.
    A reader's check: a page whose type this returns ``None`` for is outside the closed set."""
    key = _key(raw)
    return key if key in ALL_TYPES else None
