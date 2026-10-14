"""`cicada_ask` reads what is on the pages (owner, 2026-10-14) — two reproductions at hub scale, values redacted.

(a) "What is the owner's full name?" was answered "only a first name is recorded", the summary "truncated at 'R'":
    the owner's page (~178 KB, a 4.5 MB claims ledger, 6,008 claims, 11 aliases) put 3,000 characters of claims in
    front of the model and `body[:remaining]` of its prose — one character — and never sent its aliases.
(b) "Who is helping the owner create <project>?" missed the people recorded on the project's page and on a page that
    links to it: the context never followed a link.

Synthetic bank only (pat-owner, alpha-project, alice-example, bob-example); retrieval and the model are injected,
so no embedding, no network. The model is a stub that records the prompt it was shown.
"""
from __future__ import annotations

import json

import pytest

from api.services import ask_service, bank_index, markdown_parser
from api.services.claims import Claim, write_claims

FULL_NAME = "Patricia Quinn Example-Owner"


def _filler_claims(subject: str, n: int, start: int = 0) -> list[Claim]:
    return [Claim(id=f"clm_{subject}_{i:05d}", text=f"{subject} logged routine note number {i} about the weekly "
                  "schedule and the grocery list and other unrelated chores", subject=subject,
                  predicate="noted", object=f"note-{i}", object_kind="literal", valid_from="2026-05-01",
                  recorded_at="2026-05-01")
            for i in range(start, start + n)]


def _article(paragraphs: int, word: str) -> str:
    return "\n\n".join(f"{word} paragraph {i}: " + "an ordinary sentence about daily life. " * 12
                       for i in range(paragraphs))


@pytest.fixture
def hub(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    # (a) The owner's page at hub scale: a long article, 6,008 claims (the ledger takes most), eleven aliases.
    aliases = ["Pat", "P. Example", "Patty", FULL_NAME, "Patricia Example-Owner", "P. Q. Example-Owner",
               "Patricia Q. Example-Owner", "pat-owner", "Pat E.", "Patricia", "PQEO"]
    body = (f"## Summary\nPat is the person this memory belongs to; Patricia Quinn Example-Owner builds small tools "
            f"and runs a reading group.\n\n## Article\n\n" + _article(380, "Life"))
    body = write_claims(body, _filler_claims("pat-owner", 6008))
    markdown_parser.write(memory / "entities" / "pat-owner.md",
                          {"name": "Pat", "type": "person", "status": "active", "owner": True, "aliases": aliases,
                           "related": ["alpha-project", "alice-example", "bob-example"]}, body)
    # (b) A project hub: thousands of unrelated claims fill the claims budget; Bob is in a paragraph deep in its
    # article and in its `related`; Alice is recorded only on her own page, which links back to the project.
    project_body = ("## Summary\nAlpha Project is a small field robot.\n\n## Article\n\n" + _article(60, "Build")
                    + "\n\nFor the arm, [[bob-example]] reviews every build and signs off the wiring.\n\n"
                    + _article(20, "Later"))
    project_body = write_claims(project_body, _filler_claims("alpha-project", 3000))
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "status": "active", "aliases": ["Alpha"],
                           "related": ["bob-example"]}, project_body)
    alice_body = write_claims("## Summary\nAlice Example is an engineer.\n",
                              [Claim(id="clm_alice_1", text="Alice Example builds the Alpha Project prototype with Pat.",
                                     subject="alice-example", predicate="works-on", object="alpha-project",
                                     valid_from="2026-08-01", recorded_at="2026-08-01")])
    markdown_parser.write(memory / "entities" / "alice-example.md",
                          {"name": "Alice Example", "type": "person", "status": "active", "aliases": ["Ali"],
                           "related": ["alpha-project"]}, alice_body)
    markdown_parser.write(memory / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "status": "active", "related": []},
                          "## Summary\nBob Example is an electrician.\n")
    markdown_parser.write(memory / "entities" / "carol-example.md",
                          {"name": "Carol Example", "type": "person", "status": "active", "related": []},
                          "## Summary\nCarol Example is unrelated to the project.\n")
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def _hit(entity_id: str, score: float = 0.7) -> dict:
    return {"score": score, "text": "", "metadata": {"entity_id": entity_id, "entity_name": entity_id,
                                                      "type": "concept", "status": "active", "file_path": ""}}


class _Model:
    def __init__(self, used: list[str]):
        self.prompts: list[str] = []
        self.used = used

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps({"answer": "stub", "confidence": 0.8, "used_entities": self.used, "gaps": []})


def test_the_fixture_is_hub_scale(hub):
    page = (hub / "entities" / "pat-owner.md")
    assert page.stat().st_size > 60_000 and (hub / "entities" / "pat-owner.claims.jsonl").stat().st_size > 1_000_000


def test_a_full_name_recorded_as_an_alias_reaches_the_model(hub):
    """(a): the owner's page is read with its other names and an untruncated lead, even though retrieval ranked
    something else first — the question is about the person themselves."""
    model = _Model(["pat-owner"])
    out = ask_service.answer_query(hub, "What is the owner's full name?", retrieve_fn=lambda q, k: [_hit("carol-example")],
                                   llm_fn=model)
    [prompt] = model.prompts
    assert "### entity_id: pat-owner" in prompt, "a question about the owner reads the owner's page"
    assert prompt.index("pat-owner") < prompt.index("carol-example"), "the owner's page first"
    assert FULL_NAME in prompt and "also called:" in prompt
    assert "this is the page of the person this memory belongs to" in prompt
    assert "summary: Pat is the person this memory belongs to; Patricia Quinn Example-Owner builds small tools" \
        in prompt, "the lead is whole, never cut at its first letter"
    assert out["used_entities"] == ["pat-owner"]


def test_a_hub_page_gets_prose_as_well_as_claims(hub):
    model = _Model(["pat-owner"])
    ask_service.answer_query(hub, "What reading group does the owner run?", retrieve_fn=lambda q, k: [_hit("pat-owner")],
                             llm_fn=model)
    [prompt] = model.prompts
    block = prompt.split("### entity_id: pat-owner", 1)[1].split("### entity_id:", 1)[0]
    assert block.count("claim: ") >= 5
    assert "unversioned background" in block and "Life paragraph 0" in block
    assert len(block) < 9_000, "bounded: a 178 KB page is not pasted whole"


def test_the_people_linked_to_a_project_reach_the_model(hub):
    """(b): Bob is wikilinked deep in the project's article (past any fixed prose cut) and listed in its `related`;
    Alice is recorded only on her own page, which links back. Both reach the model, citable; an unrelated person
    and the owner (who links to everyone) do not appear as helpers."""
    model = _Model(["alpha-project", "alice-example", "bob-example"])
    out = ask_service.answer_query(hub, "Who is helping the owner create Alpha Project?",
                                   retrieve_fn=lambda q, k: [_hit("alpha-project")], llm_fn=model)
    [prompt] = model.prompts
    people = prompt.split("LINKED PEOPLE", 1)[1]
    assert "### entity_id: alice-example" in people and "Alice Example builds the Alpha Project prototype" in people
    assert "### entity_id: bob-example" in people and "reviews every build" in people
    assert "carol-example" not in prompt
    assert "### entity_id: pat-owner" in prompt.split("LINKED PEOPLE", 1)[0], "the owner is read as the asker"
    assert "### entity_id: pat-owner" not in people, "the owner is never listed as a helper"
    assert set(out["used_entities"]) == {"alpha-project", "alice-example", "bob-example"}, "linked people are citable"
    assert {c["entity_id"] for c in out["citations"]} >= {"alice-example", "bob-example"}


def test_linked_people_are_capped(hub):
    for n in range(12):
        markdown_parser.write(hub / "entities" / f"helper-{n}.md",
                              {"name": f"Helper Number{n}", "type": "person", "status": "active",
                               "related": ["alpha-project"]}, "## Summary\nA helper.\n")
    bank_index.invalidate()
    model = _Model([])
    ask_service.answer_query(hub, "Who works on Alpha Project?", retrieve_fn=lambda q, k: [_hit("alpha-project")],
                             llm_fn=model)
    people = model.prompts[0].split("LINKED PEOPLE", 1)[1]
    assert people.count("### entity_id:") == ask_service._MAX_LINKED_PEOPLE
