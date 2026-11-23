"""A stated value said again in other words replaces the old one (G148, 2026-11-23): the matching logic, no model.

Synthetic names only. The judge is a fake that records its prompts and answers with a fixed JSON object.
"""
from __future__ import annotations

from api.services import predicates, value_alignment
from api.services.claim_reconciler import reconcile_stage3
from api.services.claims import Claim, value_predicate


def _value(cid, attribute, value, day, episode, subject="shop-example", **kw):
    return Claim(id=cid, text=f"{subject} {attribute}: {value}", subject=subject, predicate=value_predicate(attribute),
                 object=value, object_kind="literal", valid_from=day, source_episodes=[episode],
                 source_trust="agent_extracted", origin="benchmark", **kw)


class _Judge:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else {}


class _Settings:
    def __init__(self, memory_path):
        self.memory_path = memory_path
        self.litellm_model = "test-model"
        self.archive_threshold = 0.2
        self.decay_nudge_threshold = 0.4


def _old_and_new():
    old = _value("c_old", "price per card", "4 euros", "2026-09-26", "ep_2026-09-26_001")
    new = _value("c_new", "prix des tirages", "5 euros", "2026-11-01", "ep_2026-11-01_001")
    return old, new


def test_a_new_attribute_with_something_to_join_is_one_call_for_the_page():
    old, new = _old_and_new()
    judge = _Judge({"same": [[1, 2]]})
    audit = value_alignment.align([new], {"shop-example": [old]}, judge)
    assert len(judge.prompts) == 1
    assert "price per card: 4 euros" in judge.prompts[0] and "prix des tirages: 5 euros" in judge.prompts[0]
    assert new.predicate == old.predicate and old.predicate == "value-of-price-per-card"
    assert audit == [{"action": "value_aligned", "claim": "c_new", "from": "value-of-prix-des-tirages",
                      "to": "value-of-price-per-card"}]


def test_the_newer_value_then_closes_the_older_and_nothing_is_deleted(tmp_path):
    old, new = _old_and_new()
    value_alignment.align([new], {"shop-example": [old]}, _Judge({"same": [[1, 2]]}))
    predicates.install_predicate_map(tmp_path)
    reconciled, _nudges, _audit = reconcile_stage3([new], {"shop-example": [old]}, _Settings(tmp_path),
                                                   cardinality_fn=lambda _p: False, now_date="2026-11-23", decay=False)
    by_id = {c.id: c for c in reconciled["shop-example"]}
    assert by_id["c_old"].valid_to == "2026-11-01" and by_id["c_old"].superseded_by == "c_new"
    assert by_id["c_new"].valid_to is None


def test_two_real_attributes_stay_two_when_the_judge_says_different(tmp_path):
    old, new = _old_and_new()
    judge = _Judge({"same": []})
    assert value_alignment.align([new], {"shop-example": [old]}, judge) == []
    assert new.predicate == "value-of-prix-des-tirages"
    predicates.install_predicate_map(tmp_path)
    reconciled, _n, _a = reconcile_stage3([new], {"shop-example": [old]}, _Settings(tmp_path),
                                          cardinality_fn=lambda _p: False, now_date="2026-11-23", decay=False)
    assert all(c.valid_to is None for c in reconciled["shop-example"])


def test_words_that_already_match_are_never_asked():
    old = _value("c_old", "personal best 5k time", "27:12", "2026-05-25", "ep_2026-05-25_001")
    new = _value("c_new", "5k personal best", "25:50", "2026-05-27", "ep_2026-05-27_001")
    judge = _Judge()
    assert value_alignment.align([new], {"shop-example": [old]}, judge) == [] and judge.prompts == []


def test_a_page_with_no_other_value_is_never_asked():
    new = _value("c_new", "prix des tirages", "5 euros", "2026-11-01", "ep_2026-11-01_001")
    judge = _Judge()
    value_alignment.align([new], {"shop-example": []}, judge)
    assert judge.prompts == []


def test_two_values_one_conversation_stated_are_never_one_attribute():
    old = _value("c_old", "price per card", "4 euros", "2026-09-26", "ep_2026-09-26_001")
    new = _value("c_new", "print price", "18 euros", "2026-09-26", "ep_2026-09-26_001")
    judge = _Judge({"same": [[1, 2]]})
    value_alignment.align([new], {"shop-example": [old]}, judge)
    assert judge.prompts == [] and new.predicate == "value-of-print-price"


def test_a_closed_value_and_a_value_of_another_context_are_not_candidates():
    closed = _value("c_old", "price per card", "4 euros", "2026-09-26", "ep_2026-09-26_001")
    closed.valid_to = "2026-10-01"
    other = _value("c_ctx", "unit price", "3 euros", "2026-09-26", "ep_2026-09-26_002", context="family")
    new = _value("c_new", "prix des tirages", "5 euros", "2026-11-01", "ep_2026-11-01_001")
    judge = _Judge()
    value_alignment.align([new], {"shop-example": [closed, other]}, judge)
    assert judge.prompts == []


def test_a_value_read_again_is_the_pages_own_and_never_asked():
    old, new = _old_and_new()
    again = _value("c_old", "prix des tirages", "4 euros", "2026-09-26", "ep_2026-09-26_001")
    judge = _Judge()
    value_alignment.align([again], {"shop-example": [old]}, judge)
    assert judge.prompts == []


def test_only_new_claims_are_renamed_and_a_group_of_old_ones_changes_nothing():
    a = _value("c_a", "price per card", "4 euros", "2026-09-26", "ep_2026-09-26_001")
    b = _value("c_b", "card cost", "4 euros", "2026-09-27", "ep_2026-09-27_001")
    new = _value("c_new", "prix des tirages", "5 euros", "2026-11-01", "ep_2026-11-01_001")
    judge = _Judge({"same": [[1, 2]]})   # lines: 1 = the new one first, 2 and 3 the old ones
    value_alignment.align([new], {"shop-example": [a, b]}, judge)
    assert a.predicate == "value-of-price-per-card" and b.predicate == "value-of-card-cost"
    assert new.predicate in ("value-of-price-per-card", "value-of-card-cost")


def test_new_values_of_one_batch_join_each_other_the_earliest_staying_put():
    first = _value("c_1", "price per card", "4 euros", "2026-09-26", "ep_2026-09-26_001")
    second = _value("c_2", "prix des cartes", "5 euros", "2026-11-01", "ep_2026-11-01_001")
    judge = _Judge({"same": [[1, 2]]})
    value_alignment.align([second, first], {"shop-example": []}, judge)
    assert len(judge.prompts) == 1 and second.predicate == first.predicate == "value-of-price-per-card"


def test_a_confused_answer_changes_nothing():
    old, new = _old_and_new()
    for reply in ({"same": [[1, 9]]}, {"same": [[1]]}, {"same": "yes"}, {"same": [["a", "b"]]}, {}, {"other": 1}):
        assert value_alignment.align([new], {"shop-example": [old]}, _Judge(reply)) == []
        assert new.predicate == "value-of-prix-des-tirages"


def test_a_line_the_judge_puts_in_two_groups_keeps_only_the_first():
    a = _value("c_a", "price per card", "4 euros", "2026-09-26", "ep_2026-09-26_001")
    n1 = _value("c_n1", "prix des tirages", "5 euros", "2026-11-01", "ep_2026-11-01_001")
    n2 = _value("c_n2", "tarif", "6 euros", "2026-11-02", "ep_2026-11-02_001")
    ask = value_alignment.questions([n1, n2], {"shop-example": [a]})[0]
    got = value_alignment.groups({"same": [[1, 3], [3, 2]]}, ask)
    assert [[ln.n for ln in g] for g in got] == [[1, 3]]


def test_a_judge_that_fails_costs_the_alignment_never_the_batch():
    old, new = _old_and_new()

    def broken(_prompt):
        raise RuntimeError("engine down")

    assert value_alignment.align([new], {"shop-example": [old]}, broken) == []
    assert new.predicate == "value-of-prix-des-tirages"
    assert value_alignment.align([new], {"shop-example": [old]}, None) == []


def test_a_page_of_fifty_values_is_one_call_listing_at_most_the_bound():
    existing = [_value(f"c_{i}", f"attribute number {i} kind{i}", f"{i}", f"2026-09-{(i % 27) + 1:02d}",
                       f"ep_2026-09-{(i % 27) + 1:02d}_{i:03d}") for i in range(50)]
    new = _value("c_new", "prix des tirages", "5 euros", "2026-11-01", "ep_2026-11-01_001")
    judge = _Judge()
    value_alignment.align([new], {"shop-example": existing}, judge)
    assert len(judge.prompts) == 1
    listed = [ln for ln in judge.prompts[0].splitlines() if ln[:1].isdigit()]
    assert len(listed) == value_alignment.MAX_LINES


def test_pages_asked_per_batch_are_bounded():
    incoming, existing = [], {}
    for i in range(value_alignment.MAX_ASKS + 7):
        subject = f"thing-{i:02d}"
        existing[subject] = [_value(f"o{i}", "price per card", "4", "2026-09-26", "ep_2026-09-26_001", subject)]
        incoming.append(_value(f"n{i}", "prix des tirages", "5", "2026-11-01", "ep_2026-11-01_001", subject))
    judge = _Judge()
    value_alignment.align(incoming, existing, judge)
    assert len(judge.prompts) == value_alignment.MAX_ASKS


def test_the_prompt_tells_the_judge_to_keep_unlike_things_apart():
    old, new = _old_and_new()
    text = value_alignment.prompt(value_alignment.questions([new], {"shop-example": [old]})[0])
    for phrase in ("When unsure, they are DIFFERENT", "can both be true at once", "what it includes", "THING: shop example"):
        assert phrase in text
