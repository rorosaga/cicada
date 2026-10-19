"""Synthetic inbox items in the shapes measured on a real inbox (owner brief, 2026-10-19; real values redacted) —
never collected by pytest (underscore prefix). Every name is a placeholder by default; a measurement may pass its own
public names through ``names``. Nothing here reads a real bank, ``~/.cicada`` or the network.

The shapes: "Who or what is <X>?" clarifications Stage 1 raised with too little context (a dataset, a part number, a
paper by its id, a studio, a film), the person-shaped ones that always stay ("Unknown relationship details", "Unnamed
person"), type conflicts about tools, a concept, a company and a work ("Is <tool> an AI code editor or an AI agent?"),
a question about Cicada's own settings, a repo-state question and a conflict about a person.
"""
from __future__ import annotations

from pathlib import Path

from _synthetic_bank import _entity
from api.services import markdown_parser, pending_store
from api.services.id_utils import sanitize_id

#: Placeholder subjects; a measurement may map each key to a real public name.
NAMES = {
    "dataset": "dataset-example-1k", "part": "PX-4410-example", "paper": "2401.00002", "studio": "Studio Example",
    "film": "Example Film Two", "bare": "Example Thing", "own_dataset": "own-dataset-example",
    "his": "dataset-example-2", "editor": "Editor Example", "harness": "Harness Example",
    "concept": "Concept Example", "company": "Company Example", "work": "Work Example",
}

#: What the census must say about each item (``web_settle.classify``'s enum) — the expectation the tests pin.
EXPECTED = {
    "inbox-501": "public", "inbox-502": "public", "inbox-503": "public", "inbox-504": "public",
    "inbox-505": "public", "inbox-506": "public", "inbox-507": "person_context", "inbox-508": "person_context",
    "inbox-509": "person", "inbox-510": "kind",
    "inbox-521": "public", "inbox-522": "public", "inbox-523": "public", "inbox-524": "public",
    "inbox-525": "public", "inbox-526": "own_settings", "inbox-527": "repo_state", "inbox-528": "person",
}


def _item(memory: Path, item_id: str, **fm) -> None:
    body = fm.pop("body", "Context.")
    base = {"status": "pending", "priority": 0.5, "created_date": "2026-09-01", "allow_other": True,
            "allow_defer": True}
    base.update(fm)
    markdown_parser.write(memory / "inbox" / f"{item_id}.md", base, body)


def _held(memory: Path, name: str, etype: str, description: str) -> None:
    pending_store.upsert(memory, pending_store.PendingEntity(
        name=name, type=etype, description=description, source_episode="ep_2026-09-01_001", confidence=0.3,
        tags=[], history_entries=[]))


def _clarification(memory: Path, item_id: str, name: str, etype: str, description: str, *,
                   uncertainty: str = "Insufficient context to classify", **extra) -> None:
    _held(memory, name, etype, description)
    _item(memory, item_id, kind="clarification", required_input="freetext", entity_id=sanitize_id(name),
          entity_name=name, title=f"Who or what is {name}?", uncertainty_type=uncertainty,
          suggested_classification=f"{etype} — {description}", body=description, **extra)


def _type_conflict(memory: Path, item_id: str, eid: str, name: str, etype: str, question: str, a: str, b: str, *,
                   predicate: str = "description") -> None:
    _entity(memory, eid, type=etype, name=name, body=f"## Summary\n{name} came up in a conversation.\n")
    _item(memory, item_id, kind="conflict", required_input="choice", entity_id=eid, entity_name=name,
          predicate=predicate, question=question, title=question, priority=0.8,
          options=[{"key": "a", "label": a, "claim_id": None}, {"key": "b", "label": b, "claim_id": None},
                   {"key": "both", "label": "Both are true (different contexts)", "claim_id": None}])


def build(memory: Path, names: dict[str, str] | None = None) -> dict[str, str]:
    """Write the shapes into ``memory`` (an existing synthetic bank with ``entities/`` and ``inbox/``); returns the
    item id → the name it asks about."""
    n = {**NAMES, **(names or {})}
    _entity(memory, "owner-example", type="person", owner=True, name="Owner Example")
    _entity(memory, "alice-example", type="person", name="Alice Example")
    # Clarifications Stage 1 raised with too little context ("Insufficient context to classify").
    _clarification(memory, "inbox-501", n["dataset"], "concept", "A dataset the user mentioned")
    _clarification(memory, "inbox-502", n["part"], "tool", "Part number the user asked about")
    _clarification(memory, "inbox-503", n["paper"], "concept", "A paper the person referenced by its arXiv id")
    _clarification(memory, "inbox-504", n["studio"], "company", "An animation studio")
    _clarification(memory, "inbox-505", n["film"], "concept", "A film the user watched")
    _clarification(memory, "inbox-506", n["bare"], "concept", "")
    # The speaker's own thing, and a description that says "his": they stay home.
    _clarification(memory, "inbox-507", n["own_dataset"], "concept", "A dataset built by the user for a class")
    _clarification(memory, "inbox-508", n["his"], "concept", "Used in his experiments")
    # Person-shaped: always the person's.
    _clarification(memory, "inbox-509", "Example Colleague", "person", "Someone from work",
                   uncertainty="Unknown relationship details")
    _item(memory, "inbox-510", kind="clarification", required_input="freetext", entity_id="partner-example",
          entity_name="Partner", title="What is your partner's name?", uncertainty_type="Unnamed person",
          asks="name", suggested_classification="person — a relation")
    # Conflicts about what a public thing is.
    _type_conflict(memory, "inbox-521", sanitize_id(n["editor"]), n["editor"], "tool",
                   f"Is {n['editor']} an AI code editor or an AI agent?", "AI code editor", "AI agent")
    _type_conflict(memory, "inbox-522", sanitize_id(n["harness"]), n["harness"], "tool",
                   f"Is {n['harness']} an agent harness or an AI agent itself?", "agent harness", "AI agent itself",
                   predicate="is-a")
    _type_conflict(memory, "inbox-523", sanitize_id(n["concept"]), n["concept"], "concept",
                   f"Is {n['concept']} a technique or a product?", "a technique", "a product")
    _type_conflict(memory, "inbox-524", sanitize_id(n["company"]), n["company"], "company",
                   f"Is {n['company']} a game studio or a hardware maker?", "game studio", "hardware maker")
    _type_conflict(memory, "inbox-525", sanitize_id(n["work"]), n["work"], "media",
                   f"Is {n['work']} a film or a novel?", "a film", "a novel")
    # Cicada's own settings: the system knows them.
    _entity(memory, "cicada", type="project", name="Cicada", body="## Summary\nThe memory system.\n")
    _item(memory, "inbox-526", kind="conflict", required_input="choice", entity_id="cicada", entity_name="Cicada",
          predicate="description", question="Are scheduled Sleep runs still going through provider-a?",
          title="Are scheduled Sleep runs still going through provider-a?",
          options=[{"key": "a", "label": "provider-a", "claim_id": None},
                   {"key": "b", "label": "the plan", "claim_id": None}])
    # Repo state: a trusted local agent answers it from the history.
    _item(memory, "inbox-527", kind="clarification", entity_id="beta-project", entity_name="Beta Project",
          title="Did PR #42 merge?", question="Did PR #42 merge?", suggested_classification="project — x")
    # A conflict about a person: never searched.
    _item(memory, "inbox-528", kind="conflict", required_input="choice", entity_id="alice-example",
          entity_name="Alice Example", predicate="description", question="Is Alice Example a designer or a writer?",
          options=[{"key": "a", "label": "designer"}, {"key": "b", "label": "writer"}])
    return {"inbox-501": n["dataset"], "inbox-502": n["part"], "inbox-503": n["paper"], "inbox-504": n["studio"],
            "inbox-505": n["film"], "inbox-506": n["bare"], "inbox-521": n["editor"], "inbox-522": n["harness"],
            "inbox-523": n["concept"], "inbox-524": n["company"], "inbox-525": n["work"]}
