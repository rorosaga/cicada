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


def _says(line, same_as):
    return {"answers": [{"line": line, "same_as": same_as, "why": "test"}]}


YES, NO = {"same_attribute": True}, {"same_attribute": False}


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


def test_a_new_attribute_with_something_to_join_is_one_call_for_the_page_and_one_check_per_join():
    old, new = _old_and_new()
    judge = _Judge(_says(1, 2), YES)
    audit = value_alignment.align([new], {"shop-example": [old]}, judge)
    assert len(judge.prompts) == 2          # the page, then the one join it proposed
    assert "NEW" in judge.prompts[0] and "price per card: 4 euros" in judge.prompts[0]
    assert "prix des tirages: 5 euros" in judge.prompts[0]
    assert "EARLIER: shop-example price per card: 4 euros" in judge.prompts[1]
    assert new.predicate == old.predicate and old.predicate == "value-of-price-per-card"
    assert audit == [{"action": "value_aligned", "claim": "c_new", "from": "value-of-prix-des-tirages",
                      "to": "value-of-price-per-card"}]


def test_the_newer_value_then_closes_the_older_and_nothing_is_deleted(tmp_path):
    old, new = _old_and_new()
    value_alignment.align([new], {"shop-example": [old]}, _Judge(_says(1, 2), YES))
    predicates.install_predicate_map(tmp_path)
    reconciled, _nudges, _audit = reconcile_stage3([new], {"shop-example": [old]}, _Settings(tmp_path),
                                                   cardinality_fn=lambda _p: False, now_date="2026-11-23", decay=False)
    by_id = {c.id: c for c in reconciled["shop-example"]}
    assert by_id["c_old"].valid_to == "2026-11-01" and by_id["c_old"].superseded_by == "c_new"
    assert by_id["c_new"].valid_to is None


def test_two_real_attributes_stay_two_when_the_judge_says_different(tmp_path):
    old, new = _old_and_new()
    judge = _Judge({"answers": [{"line": 1, "same_as": None, "why": "a print is not a card"}]})
    assert value_alignment.align([new], {"shop-example": [old]}, judge) == []
    assert new.predicate == "value-of-prix-des-tirages" and len(judge.prompts) == 1
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
    judge = _Judge(_says(1, 2), YES)
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


def test_only_new_claims_are_renamed_and_a_line_that_is_not_new_is_never_asked_about():
    a = _value("c_a", "price per card", "4 euros", "2026-09-26", "ep_2026-09-26_001")
    b = _value("c_b", "card cost", "4 euros", "2026-09-27", "ep_2026-09-27_001")
    new = _value("c_new", "prix des tirages", "5 euros", "2026-11-01", "ep_2026-11-01_001")
    # lines: 1 = the new one, then the old ones newest first (2 = card cost, 3 = price per card)
    judge = _Judge({"answers": [{"line": 2, "same_as": 3}, {"line": 1, "same_as": 2}]}, YES)
    value_alignment.align([new], {"shop-example": [a, b]}, judge)
    assert a.predicate == "value-of-price-per-card" and b.predicate == "value-of-card-cost"
    assert new.predicate == "value-of-card-cost" and len(judge.prompts) == 2


def test_new_values_of_one_batch_join_each_other_the_earliest_staying_put():
    first = _value("c_1", "price per card", "4 euros", "2026-09-26", "ep_2026-09-26_001")
    second = _value("c_2", "prix des cartes", "5 euros", "2026-11-01", "ep_2026-11-01_001")
    judge = _Judge({"answers": [{"line": 2, "same_as": 1}]}, YES)
    value_alignment.align([second, first], {"shop-example": []}, judge)
    assert second.predicate == first.predicate == "value-of-price-per-card"


def test_a_join_the_second_opinion_refuses_is_never_made():
    """A study's start date once joined its readout date on one wrong answer: both must agree."""
    old = _value("c_old", "start date", "2026-10-07", "2026-10-02", "ep_2026-10-02_001", subject="study-example")
    new = _value("c_new", "readout date", "2026-11", "2026-10-14", "ep_2026-10-14_001", subject="study-example")
    judge = _Judge(_says(1, 2), NO)
    assert value_alignment.align([new], {"study-example": [old]}, judge) == []
    assert new.predicate == "value-of-readout-date" and len(judge.prompts) == 2


def test_a_check_that_is_not_a_plain_yes_refuses_the_join():
    old, new = _old_and_new()
    for answer in ({}, {"same_attribute": "yes"}, {"same_attribute": None}, {"other": True}):
        assert value_alignment.align([new], {"shop-example": [old]}, _Judge(_says(1, 2), answer)) == []
        assert new.predicate == "value-of-prix-des-tirages"


def test_a_confused_answer_changes_nothing_and_costs_no_check():
    old, new = _old_and_new()
    for reply in ({"answers": [{"line": 1, "same_as": 9}]}, {"answers": [{"line": 1, "same_as": 1}]},
                  {"answers": [{"line": 2, "same_as": 1}]},   # line 2 is the old one: only a NEW line is ever renamed
                  {"answers": [{"line": "a", "same_as": "b"}]}, {"answers": "yes"}, {"answers": [3]}, {}, {"same": [[1, 2]]}):
        judge = _Judge(reply)
        assert value_alignment.align([new], {"shop-example": [old]}, judge) == []
        assert new.predicate == "value-of-prix-des-tirages" and len(judge.prompts) == 1


def test_a_line_answered_twice_keeps_only_its_first_answer():
    a = _value("c_a", "price per card", "4 euros", "2026-09-26", "ep_2026-09-26_001")
    n1 = _value("c_n1", "prix des tirages", "5 euros", "2026-11-01", "ep_2026-11-01_001")
    ask = value_alignment.questions([n1], {"shop-example": [a]})[0]
    got = value_alignment.proposals({"answers": [{"line": 1, "same_as": 2}, {"line": 1, "same_as": 2}]}, ask)
    assert len(got) == 1


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
    for phrase in ("A second reader checks every answer", "what it includes", "THING: shop example", "1. NEW"):
        assert phrase in text
    check = value_alignment.CHECK
    for phrase in ("When unsure, they are different", "can both be true at once", "what it includes"):
        assert phrase in check


# ---- the person's own words behind a value (2026-11-23) ----------------------------------------------------------------

def _said(tmp_path, cid, attribute, value, day, line, *, speaker="user", subject="shop-example"):
    """A value whose span is a real one: the conversation is written into ``tmp_path`` and the quote located in it."""
    from api.services import evidence

    ep = f"ep_{day}_{cid[-1:]}01"
    (tmp_path / "episodes").mkdir(exist_ok=True)
    (tmp_path / "episodes" / f"{ep}.md").write_text(
        f"---\nid: {ep}\ntimestamp: '{day}T10:00:00+00:00'\nsource: import\nprocessed: true\n---\n\n"
        f"{speaker}: {line}\n", encoding="utf-8")
    claim = _value(cid, attribute, value, day, ep, subject=subject)
    claim.evidence = [evidence.verify(tmp_path, ep, line)]
    return claim


def test_the_prompt_and_the_check_carry_the_persons_own_words_for_each_value(tmp_path):
    old = _said(tmp_path, "c_old", "price per card", "4 euros", "2026-09-26", "I sell my cards at 4 euros each.")
    new = _said(tmp_path, "c_new", "prix des tirages", "5 euros", "2026-11-01", "J'ai monté le prix à 5 euros.")
    judge = _Judge(_says(1, 2), YES)
    value_alignment.align([new], {"shop-example": [old]}, judge, tmp_path)
    assert 'they said: "J\'ai monté le prix à 5 euros."' in judge.prompts[0]
    assert 'they said: "I sell my cards at 4 euros each."' in judge.prompts[0]
    assert 'they said: "I sell my cards at 4 euros each."' in judge.prompts[1].split("LATER:")[0]
    assert 'they said: "J\'ai monté le prix à 5 euros."' in judge.prompts[1].split("LATER:")[1]
    assert new.predicate == old.predicate


def test_only_the_persons_own_located_words_are_ever_shown(tmp_path):
    assistant = _said(tmp_path, "c_a", "price per card", "4 euros", "2026-09-26", "Cards cost 4 euros.", speaker="assistant")
    unlocated = _value("c_u", "card cost", "4 euros", "2026-09-27", "ep_2026-09-27_001")   # kind reasoning, offsets -1
    secret = _said(tmp_path, "c_s", "price per card", "4 euros", "2026-09-28", "my password is Tr0ub4dor&3xyz and the card costs 4 euros")
    words = value_alignment.Words(tmp_path)
    assert words.of(assistant) == "" and words.of(unlocated) == ""
    assert words.of(_said(tmp_path, "c_b", "x", "1", "2026-10-01", "I charge 4 euros.")) == "I charge 4 euros."
    assert secret.evidence[0].is_span() and words.of(secret) == ""      # what the detector is sure of is never shown
    # a span the stored text no longer holds is never read back (a changed conversation, a hash that moved)
    changed = _said(tmp_path, "c_c", "x", "1", "2026-10-02", "I charge 4 euros.")
    changed.evidence[0].hash = "000000000000"
    assert words.of(changed) == ""


def test_words_are_cut_to_the_bound_and_absent_without_a_bank(tmp_path):
    long_line = "I raised the price of my cards " + "and then some more words " * 30 + "to 5 euros."
    claim = _said(tmp_path, "c_l", "price per card", "5 euros", "2026-09-26", long_line)
    shown = value_alignment.Words(tmp_path).of(claim)
    assert shown.startswith("I raised the price") and len(shown) <= value_alignment.MAX_WORDS_CHARS + 1
    assert value_alignment.Words(None).of(claim) == ""
    old, new = _old_and_new()
    judge = _Judge(_says(1, 2), YES)
    value_alignment.align([new], {"shop-example": [old]}, judge)          # no bank: the sentences alone, as before
    assert "they said" not in judge.prompts[0] and new.predicate == old.predicate


def test_words_never_decide_a_join_two_changes_said_alike_stay_two(tmp_path):
    old = _said(tmp_path, "c_old", "monthly rent", "900 euros", "2026-09-26", "I raised the rent to 900 euros.")
    new = _said(tmp_path, "c_new", "deposit", "1900 euros", "2026-11-01", "I raised the deposit to 1900 euros.")
    judge = _Judge(_says(1, 2), NO)
    assert value_alignment.align([new], {"shop-example": [old]}, judge, tmp_path) == []
    assert new.predicate == "value-of-deposit" and len(judge.prompts) == 2
    assert "never make two lines one attribute" in judge.prompts[0]
    assert "never make two values one attribute" in judge.prompts[1]


def test_without_words_the_prompts_are_exactly_what_they_were():
    """A claim with no located span (an inference, an assistant's turn) gets the prompts of before: the note about the
    person's words is added only when a line carries some, so the judge is never told to look for what is not there."""
    old, new = _old_and_new()
    ask = value_alignment.questions([new], {"shop-example": [old]})[0]
    text = value_alignment.prompt(ask)
    assert "own words" not in text and "{note}" not in text and "they said" not in text
    judge = _Judge(_says(1, 2), YES)
    value_alignment.align([new], {"shop-example": [old]}, judge)
    assert "own words" not in judge.prompts[1] and "{note}" not in judge.prompts[1]
