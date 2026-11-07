"""A replaced value leaves Key Facts and stays in History with its dates (owner 2026-11-07). Synthetic values only."""
from api.services import claims as cl, entity_body, replaced_facts
from api.services.claims import Claim

BODY = """## Summary
Alpha is a tool.

## Key Facts
- Alpha shipped version 1.2 with the installer fix.
- Alpha runs on one machine.
- Alpha shipped version 1.2 and then 1.3 the same week.

## History
- 2026-01-02: Started.
"""


def _value(cid, obj, **kw):
    return Claim(id=cid, text=f"Alpha version is {obj}", subject="alpha", predicate="value-of-version",
                 object=obj, object_kind="literal", **kw)


def _page(old_open=True):
    old = _value("clm_old", "1.2", valid_from="2026-02-01")
    new = _value("clm_new", "1.3", valid_from="2026-03-01")
    before = [old]
    closed = _value("clm_old", "1.2", valid_from="2026-02-01", valid_to="2026-03-01", superseded_by="clm_new")
    after = [closed, new]
    return cl.write_claims(BODY, before), before, after


def test_the_bullet_that_says_only_the_old_value_moves_to_history_whole_with_its_dates():
    body, before, after = _page()
    out = replaced_facts.retire({}, cl.write_claims(body, after), before, after)
    sections = entity_body.parse_sections(cl.strip_claims_block(out))
    assert "version 1.2 with the installer fix" not in sections["Key Facts"]
    assert "runs on one machine" in sections["Key Facts"]
    assert "then 1.3 the same week" in sections["Key Facts"]            # it also says the new value: stays
    assert "2026-02-01: Alpha shipped version 1.2 with the installer fix. (until 2026-03-01)" in sections["History"]
    assert "2026-01-02: Started." in sections["History"]
    assert cl.parse_claims(out) == after                                  # the claims block is exactly the new one


def test_nothing_moves_for_a_page_a_person_wrote_or_for_a_value_already_closed():
    body, before, after = _page()
    written = cl.write_claims(body, after)
    assert replaced_facts.retire({"human_edited": True}, written, before, after) == written
    assert replaced_facts.retire({}, written, after, after) == written   # already closed before this change


def test_only_a_value_claim_replaced_by_another_value_counts():
    old = Claim(id="a", text="t", subject="alpha", predicate="part-of", object="beta", object_kind="node",
                valid_to="2026-03-01", superseded_by="b")
    new = Claim(id="b", text="t", subject="alpha", predicate="part-of", object="gamma", object_kind="node")
    assert replaced_facts.newly_replaced([old], [old, new]) == []
    body = cl.write_claims("## Key Facts\n- Alpha is part of beta.\n", [old, new])
    assert replaced_facts.retire({}, body, [], [old, new]) == body
