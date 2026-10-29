"""Two things that are related are not one thing (owner 2026-10-29, G21/G209).

The owner, looking at Home's "Possible duplicates": "there are some really dumb questions again like is <product-a> the
same as <product-a> Code?" Most of those pairs were RELATIONS — a part and its whole, a product and its maker, an
alternative and the original, a version and the line it belongs to — asked as "same?". This module is the one
vocabulary for them:

* :data:`RELATIONS` — what the Stage 2 judge (``entity_resolver``) and the web check (``web_settle``) may answer
  besides same / different / unsure, each the relation of entry **B** (the name asked about) to entry **A** (the page
  it was weighed against), and the predicate the claim takes ON A's PAGE. A always has a page, so the claim always
  lands on a page (never held on a pending line, where :func:`known` could not see it); B is its object, by id when B
  has a page and by its slug otherwise. The predicates are the vocabulary's own (``predicates-seed.yaml``): most are
  multi-valued; ``part-of`` is single-valued there (a part belongs to one whole) and ``made-by`` in neither list, so a
  second whole or maker meets Stage 3 like any other claim.
* :func:`known` — the record already holds a current claim relating the two pages: no "same?" question is raised about
  the pair, and an alias lead between them makes no judge call. The relation on the record IS the memory that the two
  are two things; take the claim back (undo) and the pair may be asked again.

A relation the judge names writes a claim through the ordinary claim pipeline (observer ``agent``, origin ``sleep``,
evidence the conversation the name was heard in, as ``reasoning`` — the judge read descriptions, nothing in the bank
says it in so many words, and provenance never blocks memory, G118). A relation the web check finds writes a cited
claim through ``web_settle.settle``, undoable under "Settled by a check".
"""
from __future__ import annotations

from pathlib import Path

#: relation of B to A -> the predicate of the claim on A's page, with B as its object.
RELATIONS: dict[str, str] = {
    "part_of": "includes",                # B is a part / feature / module / stage / PR of A: A includes B
    "has_part": "part-of",                # A is a part of B
    "made_by": "creates",                 # B is a product made, sold or run by A: A creates B
    "makes": "made-by",                   # A is made by B
    "alternative_to": "alternative-to",   # two products doing the same job (a fork, a reimplementation)
    "version_of": "has-version",          # B is a version / model / edition / release / unit of A
    "has_version": "is-a",                # A is a version of B
}
#: Two different things with no relation Cicada keeps — written only by a cited check (a judge's ``different`` writes
#: nothing: it is the ordinary verdict).
DIFFERENT = "different"
DIFFERENT_PREDICATE = "contrasts-with"

#: How each relation reads in a sentence about B and A (an answer line, a dry run): "{b} is part of {a}".
PHRASES: dict[str, str] = {
    "part_of": "{b} is part of {a}",
    "has_part": "{a} is part of {b}",
    "made_by": "{b} is made by {a}",
    "makes": "{a} is made by {b}",
    "alternative_to": "{b} is an alternative to {a}",
    "version_of": "{b} is a version of {a}",
    "has_version": "{a} is a version of {b}",
    DIFFERENT: "{b} and {a} are different things",
}

#: The prompts' words for the relations, in one place (the judge's and the web check's).
PROMPT_LINES = (
    '- "part_of": B is a part, feature, component, module, screen, stage, task, pull request or commit of A.\n'
    '- "has_part": A is a part, feature, component, module, screen, stage, task, pull request or commit of B.\n'
    '- "made_by": B is a product, model, service, API or plan made, sold or run by A.\n'
    '- "makes": A is a product, model, service, API or plan made, sold or run by B.\n'
    '- "alternative_to": A and B are different products that do the same job (a fork, a compatible '
    'reimplementation, a competitor, a successor).\n'
    '- "version_of": B is one specific version, model, edition, release, year, unit or installation of A.\n'
    '- "has_version": A is one specific version, model, edition, release, year, unit or installation of B.\n'
)

#: Predicates that say, on the record, that two pages are two things. Never ``relates-to`` (too weak to tell).
RECORD_PREDICATES = frozenset({
    *RELATIONS.values(), DIFFERENT_PREDICATE, "contains", "uses", "runs-on", "depends-on", "integrates-with",
    "implements", "hosts",
})

#: A verdict string for a relation, as the judge's cache and callers carry it: ``related:<relation>``.
PREFIX = "related:"


def verdict(relation: str) -> str:
    return f"{PREFIX}{relation}"


def relation_of(decision: str | None) -> str | None:
    """The relation a ``related:<relation>`` verdict names, else ``None``."""
    text = str(decision or "")
    if not text.startswith(PREFIX):
        return None
    rel = text[len(PREFIX):]
    return rel if rel in RELATIONS else None


def clean(relation) -> str:
    return str(relation or "").strip().lower().replace("-", "_").replace(" ", "_")


def parse(decision, relation) -> str | None:
    """A judge's ``related`` answer as a verdict: ``related:<relation>`` for a relation in the vocabulary, else
    ``different`` (it said two things, and named no relation Cicada keeps). ``None`` when it did not say related."""
    if str(decision or "").strip().lower() != "related":
        return None
    rel = clean(relation)
    return verdict(rel) if rel in RELATIONS else DIFFERENT


def predicate_for(relation: str) -> str:
    return DIFFERENT_PREDICATE if relation == DIFFERENT else RELATIONS[relation]


def phrase(relation: str, b_name: str, a_name: str) -> str:
    return PHRASES.get(relation, "{b} and {a} are related").format(b=b_name, a=a_name)


def relationship(relation: str, b_name: str, a_name: str, *, a_id: str, b_id: str, episode: str = "",
                 timestamp: str | None = None) -> dict:
    """The Stage-1-shaped relationship a judge's relation becomes (``entity_extractor.entities_to_claims``): one claim
    on A's page (pinned by id), B its object (pinned by id or slug — never a held endpoint), observer ``agent``, its
    evidence the conversation the name was heard in, as ``reasoning``."""
    out = {"source": a_name, "target": b_name, "label": predicate_for(relation), "confidence": 0.6,
           "source_page": a_id, "target_page": b_id,
           "evidence": [{"episode": episode, "kind": "reasoning"}] if episode else []}
    if episode:
        out["source_episode"] = episode
    if timestamp:
        out["source_episode_timestamp"] = timestamp
    return out


def _page_claims(memory_path: Path, page_id: str) -> list:
    from api.services import markdown_parser
    from api.services.claims import parse_claims

    path = Path(memory_path) / "entities" / f"{page_id}.md"
    if not page_id or not path.is_file():
        return []
    try:
        return parse_claims(markdown_parser.parse(path).body)
    except Exception:  # noqa: BLE001 — an unreadable page says nothing
        return []


def known(memory_path: Path | None, a_id: str, b_id: str) -> bool:
    """Does the record already hold a current claim relating these two (:data:`RECORD_PREDICATES`, on either page,
    either direction)? Engine-free; reads the two pages only. ``b_id`` may be a name's slug with no page."""
    from api.services.id_utils import sanitize_id

    if memory_path is None or not a_id or not b_id or a_id == b_id:
        return False
    for subject, other in ((a_id, b_id), (b_id, a_id)):
        for claim in _page_claims(Path(memory_path), subject):
            if claim.valid_to is not None or str(claim.predicate or "").lower() not in RECORD_PREDICATES:
                continue
            if str(claim.object or "") == other or sanitize_id(str(claim.object or "")) == other:
                return True
    return False
