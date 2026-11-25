"""Ruling 83 (owner 2026-11-25), "make sure this is the behaviour we achieve for everything in cicada": the inventory.

Every kind of inbox question, and every ``asks`` / ``detected`` variant a raiser can write, has here an invented example and
the words a person is asked it in (`inbox_wording`, at read, never stored). A raiser that writes a new kind, ``asks`` or
``detected`` value without adding its example here fails the gate; a form a person would not ask (an id, a bare "Who or
what is X?" with no hint of where, a title in place of a question, a "is X the same as Y?" over a mention that could be
several pages) fails the example.

Housekeeping kinds the person answers with a tap on a plain statement (a removed bookmark, an agent's request, the review of
what may be sensitive, the where-to-check rows) keep their stored words: ``STORED`` names them, each with its example.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from api.models.schemas import InboxKind
from api.services import inbox_wording

TODAY = "2026-11-25"
ROOT = Path(__file__).resolve().parents[1] / "services"

PAGE = {"name": "Zed Example", "type": "person", "last_referenced": "2026-09-01", "source_episodes": ["ep_1", "ep_2"]}
OTHER = {"name": "Zed Marlowe", "type": "person"}
OPTS = [{"key": "a", "label": "Acme Example", "claim_id": "c1"}, {"key": "b", "label": "Initech Example", "claim_id": "c2"}]
TITLED = [{"id": "zed-a", "name": "Zed Example", "type": "person", "qualifier": None, "roles": ["brother"]},
          {"id": "zed-b", "name": "Zed Marlowe", "type": "person", "qualifier": None, "roles": None}]
TOOLS = [{"id": "alpha", "name": "Alpha", "type": "tool", "qualifier": "IDE"},
         {"id": "alpha-2", "name": "Alpha", "type": "project", "qualifier": "program"}]
FIVE = [{"id": f"p{i}", "name": f"Zed Number{i}", "type": "person", "qualifier": None, "roles": None} for i in range(5)]

# (kind, asks, detected) -> (the item, the extra arguments to `spoken`, a fragment the question must hold, the words before ruling 83)
Case = tuple[dict, dict, str, str]
SPOKEN: dict[tuple[str, str, str], Case] = {
    ("decay", "", ""): ({"kind": "decay", "entity_id": "zed", "entity_name": "Zed Example"}, {"page_fm": PAGE},
                        "Zed Example", "(unchanged)"),
    ("conflict", "", ""): ({"kind": "conflict", "entity_id": "zed", "entity_name": "Zed Example", "predicate": "works-at",
                            "options": OPTS}, {"page_fm": PAGE}, "Which is right", "(unchanged)"),
    ("conflict", "still", ""): ({"kind": "conflict", "asks": "still", "entity_id": "zed", "entity_name": "Zed Example",
                                 "predicate": "works-at", "options": [{"key": "yes", "label": "Yes, still there"},
                                                                       {"key": "no", "label": "No, not any more"}]},
                                {"page_fm": PAGE}, "Zed Example", "(unchanged)"),
    ("clarification", "", ""): ({"kind": "clarification", "entity_id": "zed", "entity_name": "Zed", "source_episode": "ep_1"},
                                {"page_fm": None, "where": "Planning notes"}, "from “Planning notes”",
                                "Who or what is Zed?"),
    ("clarification", "name", ""): ({"kind": "clarification", "asks": "name", "entity_id": "zed", "entity_name": "Zed"},
                                    {"page_fm": None}, "name", "(unchanged)"),
    ("clarification", "speaker", ""): ({"kind": "clarification", "asks": "speaker", "entity_id": "speaker-1",
                                        "entity_name": "Speaker 1", "question": "Who was Speaker 1 in Planning notes?"},
                                       {"page_fm": None}, "Who was Speaker 1", "(unchanged)"),
    ("merge_suggestion", "", ""): ({"kind": "merge_suggestion", "entity_id": "zed-a", "entity_name": "Zed Example",
                                    "merge_target_hint": "zed-b", "uncertainty_type": "Possible duplicate of Zed Marlowe"},
                                   {"page_fm": PAGE, "other_fm": OTHER}, "same person",
                                   "Are Zed Example and Zed Marlowe the same person?"),
    ("merge_suggestion", "", "pick"): ({"kind": "merge_suggestion", "entity_id": "zed", "entity_name": "Zed",
                                        "merge_target_hint": "zed-a", "same_title": ["zed-a", "zed-b"]},
                                       {"titled": TITLED}, "Were you talking about your brother or Zed Marlowe?",
                                       "Is Zed the same as Zed Example? (one per candidate)"),
    ("merge_suggestion", "", "pick-things"): ({"kind": "merge_suggestion", "entity_id": "alpha", "entity_name": "Alpha",
                                               "merge_target_hint": "alpha", "same_title": ["alpha", "alpha-2"]},
                                              {"titled": TOOLS}, "Were you talking about the Alpha IDE or the Alpha program?",
                                              "Which Alpha is this: the IDE or the program?"),
    ("merge_suggestion", "", "pick-five"): ({"kind": "merge_suggestion", "entity_id": "zed", "entity_name": "Zed",
                                             "merge_target_hint": "p0", "same_title": [p["id"] for p in FIVE]},
                                            {"titled": FIVE}, "Were you talking about", "(five pairwise questions)"),
    ("merge_suggestion", "", "same_name_doubt"): ({"kind": "merge_suggestion", "detected": "same_name_doubt",
                                                   "entity_id": "zed-a", "entity_name": "Zed Example",
                                                   "merge_target_hint": "zed-b"}, {"page_fm": PAGE, "other_fm": OTHER},
                                                  "same person", "(unchanged)"),
    ("merge_suggestion", "", "which_one"): ({"kind": "merge_suggestion", "detected": "which_one", "entity_id": "zed",
                                             "entity_name": "Zed", "merge_target_hint": "zed-a",
                                             "same_title": ["zed-a", "zed-b"]}, {"titled": TITLED},
                                            "Were you talking about your brother or Zed Marlowe?", "(pairwise)"),
    ("merge_suggestion", "", "person_duplicate"): ({"kind": "merge_suggestion", "detected": "person_duplicate",
                                                    "entity_id": "zed-a", "entity_name": "Zed Example",
                                                    "merge_target_hint": "zed-b"}, {"page_fm": PAGE, "other_fm": OTHER},
                                                   "same person", "(unchanged: two pages, one candidate)"),
    ("merge_suggestion", "", "spelling"): ({"kind": "merge_suggestion", "detected": "spelling", "entity_id": "zed-a",
                                            "entity_name": "Zed Example", "merge_target_hint": "zed-b"},
                                           {"page_fm": PAGE, "other_fm": OTHER}, "same person",
                                           "(unchanged: two pages, one candidate)"),
    ("merge_suggestion", "", "alias_collision"): ({"kind": "merge_suggestion", "detected": "alias_collision",
                                                   "entity_id": "zed-a", "entity_name": "Zed Example",
                                                   "merge_target_hint": "zed-b"}, {"page_fm": PAGE, "other_fm": OTHER},
                                                  "same person", "(unchanged: two pages, one candidate)"),
    ("followup", "", ""): ({"kind": "followup", "entity_id": "zed", "entity_name": "Zed Example", "predicate": "milestone",
                            "question": "How did the launch go?"}, {"page_fm": PAGE}, "How did", "(unchanged)"),
    ("divergence", "", ""): ({"kind": "divergence", "entity_id": "zed", "entity_name": "Zed Example",
                              "title": "I'm reading something different about Zed Example",
                              "options": ["Keep my statement (Acme Example)", "Update to Initech Example",
                                          "Both true — different context"]},
                             {"page_fm": PAGE}, "Which is right about Zed Example?",
                             "I'm reading something different about Zed Example"),
    ("normalization", "", ""): ({"kind": "normalization", "entity_id": "zed", "entity_name": "Zed Example",
                                 "title": "Confirm a predicate fold for Zed Example", "raw_predicate": "is employed by",
                                 "canonical_predicate": "works-at"}, {"page_fm": PAGE}, "did I rightly take it as",
                                "Confirm a predicate fold for Zed Example"),
}
#: Housekeeping: the stored words are the question the person reads; the example is what a raiser writes.
STORED: dict[tuple[str, str, str], dict] = {
    ("clarification", "sources", ""): {"kind": "clarification", "asks": "sources", "title": "Where should I check for Zed Example?"},
    ("removal", "", ""): {"kind": "removal", "title": "Zed Example's bookmark is gone from your browser. Keep it or archive it?"},
    ("page_edit", "", ""): {"kind": "page_edit", "title": "An agent proposes a change to Zed Example's page"},
    ("agent_request", "", ""): {"kind": "agent_request", "title": "Your agent needs you to sign in to a site"},
    ("sensitive", "", ""): {"kind": "sensitive", "title": "A conversation may hold something sensitive"},
}

_BARE = re.compile(r"^Who or what is [^,?]+\?$")
_PAIRWISE = re.compile(r"\b(?:Is|Are) .+ (?:the same|one person)\b|\bsame as\b", re.IGNORECASE)


def _said(case: Case):
    fm, kwargs, _fragment, _before = case
    return inbox_wording.spoken(fm, TODAY, **kwargs)


@pytest.mark.parametrize("key", sorted(SPOKEN))
def test_every_form_is_a_question_a_person_would_ask(key):
    said = _said(SPOKEN[key])
    assert said.question and said.question.endswith("?") and len(said.question) <= inbox_wording.MAX_QUESTION
    assert SPOKEN[key][2] in said.question
    assert said.reason, "every question says why it is asked"
    assert not re.search(r"inbox-\d|ep_\w|\b[a-z]+-[a-z]+-\d\b|_", said.question), "no id, slug or key in a question"
    assert not _BARE.match(said.question), "a name asked about says where it came up"


@pytest.mark.parametrize("key", [k for k in sorted(SPOKEN) if k[2].startswith("pick")])
def test_a_mention_that_could_be_several_pages_is_never_asked_pairwise(key):
    said = _said(SPOKEN[key])
    assert not _PAIRWISE.search(said.question), "the pairwise wording is for exactly one candidate"


def test_five_candidates_fit_the_card():
    said = _said(SPOKEN[("merge_suggestion", "", "pick-five")])
    assert len(said.question) <= inbox_wording.MAX_QUESTION and said.question.endswith("?")
    assert "Number0" in said.question or said.question.startswith("Which one did you mean by Zed")


@pytest.mark.parametrize("key", sorted(STORED))
def test_housekeeping_kinds_keep_their_stored_words_as_a_sentence(key):
    item = STORED[key]
    from api.services import inbox_service

    assert key[0] in {"page_edit", "clarification"} or key[0] not in inbox_service._SPOKEN_KINDS, "it has a spoken form: say so"
    assert item["title"].strip() and not re.search(r"inbox-\d|ep_\w", item["title"])


def test_every_kind_a_raiser_can_write_has_an_example():
    covered = {k[0] for k in (*SPOKEN, *STORED)}
    assert {k.value for k in InboxKind} <= covered, sorted({k.value for k in InboxKind} - covered)


#: Writers of an ``asks`` / ``detected`` KEY that are not a question's raiser, with why (a reader's keyword, an unrelated
#: file format): (module, the source text of the value). An entry no code matches any more fails the gate, so it cannot rot.
NOT_RAISERS = {
    ("reading_asks", "rows"): "the reading-asks file's own list of rows, not a question",
    ("skill_actions", "ob.get('asks')"): "a skill action reading its own field",
    ("inbox_service", "_opt_str(fm.get('asks'))"): "the wire object copying a stored question's value",
    ("list_defaults", "detected(memory_path)"): "a keyword naming the lists detected on this Mac",
}


def _string_constants() -> dict[str, dict[str, str]]:
    """Every module-level ``NAME = "text"`` in the services, by module."""
    out: dict[str, dict[str, str]] = {}
    for path in ROOT.glob("*.py"):
        found = {}
        for node in ast.parse(path.read_text()).body:
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                found.update({t.id: node.value.value for t in node.targets if isinstance(t, ast.Name)})
        out[path.stem] = found
    return out


def raised_values() -> tuple[dict[str, set[str]], set[tuple[str, str]]]:
    """``({"asks": {...}, "detected": {...}}, unresolved)`` from the code itself: every dict literal key, keyword argument
    and subscript assignment named ``asks`` or ``detected`` in a service, its value read as a literal, or as a module
    constant (``DETECTED``, ``alias_collisions.DETECTED``), and every module-level constant named ``DETECTED`` or ending
    ``_DETECTED``. A value the gate cannot read is reported, so a raiser cannot hide behind a variable."""
    constants = _string_constants()
    found: dict[str, set[str]] = {"asks": set(), "detected": set()}
    unresolved: set[tuple[str, str]] = set()
    for module, names in constants.items():
        for name, value in names.items():
            if module != "inbox_wording" and (name == "DETECTED" or name.endswith("_DETECTED")):
                found["detected"].add(value)
    for path in ROOT.glob("*.py"):
        if path.name == "inbox_wording.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            pairs: list[tuple[str, ast.expr]] = []
            if isinstance(node, ast.Dict):
                pairs += [(k.value, v) for k, v in zip(node.keys, node.values)
                          if isinstance(k, ast.Constant) and k.value in found]
            elif isinstance(node, ast.keyword) and node.arg in found:
                pairs.append((node.arg, node.value))
            elif isinstance(node, ast.Assign):
                pairs += [(t.slice.value, node.value) for t in node.targets
                          if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value in found]
            for key, value in pairs:
                if isinstance(value, ast.Constant):
                    if isinstance(value.value, str) and value.value:
                        found[key].add(value.value)
                elif isinstance(value, ast.Name) and value.id in constants[path.stem]:
                    found[key].add(constants[path.stem][value.id])
                elif (isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
                      and value.attr in constants.get(value.value.id, {})):
                    found[key].add(constants[value.value.id][value.attr])
                else:
                    unresolved.add((path.stem, ast.unparse(value)))
    return found, unresolved


def test_every_asks_and_detected_value_in_the_code_has_an_example():
    """A raiser that writes a new ``asks`` or ``detected`` value without a spoken form here fails this — whether it writes
    the literal, a module constant (``"detected": DETECTED``) or a keyword (``asks="x"``)."""
    found, unresolved = raised_values()
    covered_asks = {k[1] for k in (*SPOKEN, *STORED)}
    covered_detected = {k[2] for k in (*SPOKEN, *STORED)}
    assert found["asks"] <= covered_asks, sorted(found["asks"] - covered_asks)
    assert found["detected"] <= covered_detected, sorted(found["detected"] - covered_detected)


def test_a_value_the_gate_cannot_read_is_listed_with_a_reason_or_fails():
    """``{"detected": some_variable}`` would hide a raiser from the gate: it is either made a constant or named here."""
    _found, unresolved = raised_values()
    assert unresolved <= set(NOT_RAISERS), sorted(unresolved - set(NOT_RAISERS))
    assert set(NOT_RAISERS) <= unresolved, f"{sorted(set(NOT_RAISERS) - unresolved)}: no longer written; drop the entry"


def test_the_gate_sees_a_constant_and_a_keyword_a_literal_grep_would_miss():
    found, _ = raised_values()
    # which_one.py writes `"detected": DETECTED`, a literal grep never saw it; person_duplicates passes it as a keyword.
    assert {"which_one", "person_duplicate", "alias_collision", "spelling", "same_name_doubt"} <= found["detected"]
    assert {"still", "sources", "speaker", "name"} <= found["asks"]
