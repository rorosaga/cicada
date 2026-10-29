"""#501's same-person chains served on ``GET /inbox`` (the app asks them once, answers them pair by pair; ruling 41 —
serving the question joins no one). Synthetic bank, placeholder names."""
from api.services import inbox_service
from api.tests.test_inbox_catchup import bank, item, page  # noqa: F401 — the shared fixture


def test_a_chain_of_same_person_questions_is_served_as_one_question_with_its_pairs(bank):
    for pid, name in (("sam-example", "Sam Example"), ("samantha-example", "Samantha Example"),
                      ("sammy-example", "Sammy Example")):
        page(bank, pid, name=name, type_="person", convs=3)
    first = item(bank, 1, kind="merge_suggestion", entity_id="sam-example", entity_name="Sam Example",
                 merge_target_hint="samantha-example", title="t", required_input="merge")
    second = item(bank, 2, kind="merge_suggestion", entity_id="sammy-example", entity_name="Sammy Example",
                  merge_target_hint="samantha-example", title="t", required_input="merge")
    page(bank, "tool-a", name="Tool A", type_="tool")
    page(bank, "tool-b", name="Tool B", type_="tool")
    other = item(bank, 3, kind="merge_suggestion", entity_id="tool-a", entity_name="Tool A",
                 merge_target_hint="tool-b", title="t", required_input="merge")
    served = {i.id: i for i in inbox_service.load_inbox(bank)}
    a, b = served[first], served[second]
    assert a.chain == b.chain and set(a.chain) == {first, second}
    assert a.chain_question == b.chain_question
    assert all(n in a.chain_question for n in ("Sam Example", "Samantha Example", "Sammy Example"))
    assert a.chain_question.endswith("the same person?")
    assert {p["id"] for p in a.chain_pairs} == {first, second}
    assert served[other].chain is None, "only people chain; a tool pair stays its own question"
    # Serving the question joins no one.
    assert (bank / "entities" / "sam-example.md").exists() and (bank / "entities" / "sammy-example.md").exists()
    assert "chainQuestion" in a.model_dump(by_alias=True)


def test_a_lone_pair_is_never_a_chain(bank):
    page(bank, "sam-example", name="Sam Example", type_="person")
    page(bank, "samantha-example", name="Samantha Example", type_="person")
    one = item(bank, 1, kind="merge_suggestion", entity_id="sam-example", entity_name="Sam Example",
               merge_target_hint="samantha-example", title="t", required_input="merge")
    assert next(i for i in inbox_service.load_inbox(bank) if i.id == one).chain is None
