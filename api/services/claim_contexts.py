"""What a claim ``context`` may be, and which ones the graph shows (F1, owner review 2026-09-23).

A claim's ``context`` is the middle term of its ``(observer, context, subject)``
key (d2-architecture-final §2): which part of a life a belief belongs to — the
engineer-self and the family-self hold different beliefs without contradicting
each other. The vocabulary is **open** by design (d2 says "OPEN";
``Claim.context``'s own comment; the MCP schema offers examples, not an enum),
so an agent may coin ``health`` and this module never closes it (R-FX1).

What it pins is the *shape* the graph can show. The owner's live graph served
two satellites per annotated paper, one named after a raw
``folder:<id>:<section>`` value and one ``general``: a paper writer had put a
location into the context field, and the
M5b facet rule (one satellite per context once a subject has two) did the rest.
Two rules close that class for every writer, not only papers:

* **A context is a short lowercase slug** (:func:`is_valid`). Anything else —
  a ``folder:`` id, the inbox's ``as of <date>`` qualifier (G60, which keeps two
  answers apart in the claim key and must keep doing so) — still works as a
  key, but is never a facet, a legend row or an edge colour.
* **``general`` is "no particular context"** (:func:`is_facet`, R-FX2). Every
  deterministic writer says it (Stage 1 ``entity_extractor``,
  ``link_enrichment``, ``link_recon``, ``paper_metadata``, ``claim_seeder``, and
  since F1 ``papers``) and ``Claim.context`` defaults to it — d2 calls it the
  extraction special case. A subject whose claims split between ``general`` and
  one real context has one perspective, not two. It still colours and filters
  as a context, so the legend keeps it.

The Swift twin is ``Models/ClaimContext.swift``; both read
``api/tests/fixtures/claim_contexts.json``.
"""

from __future__ import annotations

import re

NO_CONTEXT = "general"
MAX_LENGTH = 32
_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


def is_valid(context: object) -> bool:
    """A short lowercase slug: ``engineering``, ``machine-learning``, ``q3-planning``."""
    return isinstance(context, str) and 0 < len(context) <= MAX_LENGTH and bool(_SLUG.match(context))


def is_facet(context: object) -> bool:
    """A context the graph may split a subject on: valid, and not ``general``."""
    return is_valid(context) and context != NO_CONTEXT


def display_name(context: str) -> str:
    """``machine-learning`` → ``Machine learning``; a value that is not a context comes back as is."""
    if not is_valid(context):
        return context
    spaced = context.replace("-", " ")
    return spaced[:1].upper() + spaced[1:]
