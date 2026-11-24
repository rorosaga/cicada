"""One conversation names two people of one first name (2026-11-24, `same_name_people`, `entity_resolver`).

"Marc from work finally met my cousin Marc" reaches Stage 2 as two entities ("Marc (colleague)", "Marc (cousin)") of one
conversation. They are two people because the conversation says so; each is matched, by what is said of it, to who is
already on record; the bare name stays the plain person's. The pure half uses a fake judge; the resolver half drives
`entity_resolver.resolve` as `test_same_name_people` does. Every name is invented.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api.services import entity_resolver as er
from api.services import pending_store, same_name_people as snp
from api.tests.test_same_name_people import _Spy, _bank, _judge, _page, _run, _settings, ans

COLLEAGUE = "(2026-10-02) a colleague on the research team at the firm who is moving to another office next spring and works remotely"
COUSIN = "(2026-10-02) the speaker's cousin, a carpenter in a small mountain town who builds furniture and helps with the shelves"
SK = snp.mention_key("e1", "Marc (colleague)")
CK = snp.mention_key("e1", "Marc (cousin)")


def _two(*, bare_cousin=False):
    cousin = snp.Mention("e1" if bare_cousin else CK, COUSIN, "e1", not bare_cousin, False)
    return [snp.Mention(SK, COLLEAGUE, "e1", True, bare_cousin), cousin]


# ------------------------------------------------------------------ the pure half


@pytest.mark.parametrize("name,stem", [("Marc (cousin)", ("Marc", "cousin")), ("Marc  ( the  colleague )", ("Marc", "the colleague")),
                                       ("Carla (compañera de oficina)", ("Carla", "compañera de oficina"))])
def test_a_bare_name_with_a_qualifier_is_a_stem_and_what_tells_it_apart(name, stem):
    assert snp.stem_of(name) == stem


@pytest.mark.parametrize("name", ["Marc", "Marc Dupont", "Marc Dupont (cousin)", "Marc (cousin) (colleague)", "Marc (cousin", "Marc ()", "(Marc)", "Marc (cousin) Dupont"])
def test_anything_else_is_not_a_qualified_name(name):
    assert snp.stem_of(name) is None


def test_the_key_of_a_bare_mention_is_its_conversation_and_a_qualified_one_adds_the_name():
    assert snp.mention_key("e1", "Marc") == "e1"
    assert snp.split_key(snp.mention_key("e1", "Marc (Cousin)")) == ("e1", "marc (cousin)")


def test_two_people_one_conversation_names_with_nobody_on_record_need_no_judge():
    judge = _judge(Exception("never asked"))
    plan = _run(snp.plan("Marc", _two(), [], judge))
    assert judge.calls == [] and not plan.called
    assert plan.moves[SK] == snp.Destination("plain", "")          # the first is the bare name's person
    assert plan.moves[CK].kind == "new" and not plan.moves[CK].doubt   # the other is a person of its own, apart for good
    assert plan.review is False


def test_a_qualified_person_never_takes_the_bare_name_when_its_conversation_also_names_the_bare_name():
    plan = _run(snp.plan("Marc", _two(bare_cousin=True), [], _judge(Exception("never asked"))))
    assert "e1" not in plan.moves                                # the bare mention is the plain person
    assert plan.moves[SK].kind == "new" and plan.moves[SK].doubt   # a bare name beside a qualified one is a doubt, not "apart"


def test_a_thin_description_does_not_stop_two_people_one_conversation_named():
    thin = [snp.Mention(SK, "(2026-10-02) a colleague", "e1", True), snp.Mention(CK, "(2026-10-02) a cousin", "e1", True)]
    plan = _run(snp.plan("Marc", thin, [], _judge(None)))
    assert plan.moves[CK].kind == "new" and plan.thin == 0


PAGE_TEXT = "a colleague on the research team at the firm who runs the Monday standup and is moving to another office next spring"


def _page_identity():
    return snp.Identity("page", "marc", True, PAGE_TEXT, frozenset({"k1", "k2"}),
                        (snp.Item("(2026-09-01) " + PAGE_TEXT, ("k1",)), snp.Item("(2026-09-20) " + PAGE_TEXT, ("k2",))))


def test_each_of_the_two_goes_where_its_words_fit_and_the_plain_page_is_named_not_left_to_the_default():
    judge = _judge(ans("AC", "B"))   # A: the colleague, with the page's first conversation; B: the cousin, alone
    plan = _run(snp.plan("Marc", _two(), [_page_identity()], judge))
    assert plan.moves[SK] == snp.Destination("page", "marc"), "a qualified name is never left on under the qualified name"
    assert plan.moves[CK].kind == "new" and not plan.moves[CK].doubt, "apart: the conversation itself named both"
    assert "ONE conversation" in judge.calls[0] and "(A) and (B)" in judge.calls[0]


def test_an_answer_that_puts_the_two_of_one_conversation_together_is_split_not_trusted():
    """Neither of the two is the person on record because the answer called them one: both wait (the order of the mentions
    used to decide which kept the page; `test_when_the_judge_puts_both_with_the_person_on_record_or_fails...`)."""
    plan = _run(snp.plan("Marc", _two(), [_page_identity()], _judge(ans("ABC"))))
    assert plan.moves[SK].kind == "new" and plan.moves[CK].kind == "new" and plan.moves[SK].ref != plan.moves[CK].ref


def test_a_conversation_the_answer_leaves_out_is_still_a_person_of_its_own():
    plan = _run(snp.plan("Marc", _two(), [_page_identity()], _judge(ans("AC"))))
    assert plan.moves[SK].kind == "page" and plan.moves[CK].kind == "new"


def test_a_judge_that_fails_keeps_both_waiting_in_doubt_not_asked():
    plan = _run(snp.plan("Marc", _two(), [_page_identity()], _judge(RuntimeError("down"))))
    assert plan.moves[SK].kind == "new" and plan.moves[SK].doubt
    assert plan.moves[CK].kind == "new" and plan.moves[CK].doubt
    assert plan.review is True


def test_one_qualified_person_the_judge_calls_the_plain_page_goes_to_that_page():
    one = [snp.Mention(SK, COLLEAGUE, "e1", True)]
    plan = _run(snp.plan("Marc", one, [_page_identity()], _judge(ans("ABC"))))
    assert plan.moves == {SK: snp.Destination("page", "marc")}


def test_a_bare_mention_the_judge_calls_one_person_still_has_no_move():
    plan = _run(snp.plan("Marc", [snp.Mention("e5", COLLEAGUE)], [_page_identity()], _judge(ans("AB"))))
    assert plan.moves == {}


# ------------------------------------------------------------------ the resolver half


def _both(episode, *, qualified=("Marc (colleague)", "Marc (cousin)"), edges=True):
    a, b = qualified
    entities = [{"name": a, "type": "person", "confidence": 0.8, "summary": COLLEAGUE[13:],
                 "source_episode": episode, "source_episode_timestamp": "2026-10-02T00:00:00+00:00"},
                {"name": b, "type": "person", "confidence": 0.8, "summary": COUSIN[13:],
                 "source_episode": episode, "source_episode_timestamp": "2026-10-02T00:00:00+00:00"}]
    return {"episode_id": episode, "origin": "chatgpt", "entities": entities,
            "relationships": [{"source": a, "target": "Nina Example", "label": "works with", "source_episode": episode},
                              {"source": b, "target": "Nina Example", "label": "cousin of", "source_episode": episode}] if edges else [],
            "values": [{"entity": b, "attribute": "age", "value": "19", "source_episode": episode}]}


@pytest.fixture
def judged(monkeypatch):
    spy = _Spy()
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: spy)
    box = SimpleNamespace(answer=None, calls=[])

    async def ask(settings, system, prompt):
        box.calls.append(prompt)
        if isinstance(box.answer, Exception):
            raise box.answer
        return box.answer

    monkeypatch.setattr(er, "_same_name_ask", ask)
    box.spy = spy
    return box


def test_two_people_one_conversation_names_become_the_plain_person_and_a_second_person_never_a_qualified_name(tmp_path, judged):
    memory = _bank(tmp_path)
    extracted = [_both("e1")]
    _run(er.resolve(extracted, [], _settings(memory)))
    names = set(judged.spy.parked)
    assert names == {"marc", "marc-2"}, names                      # no line titled "Marc (colleague)"
    assert judged.spy.parked["marc"].aliases and "Marc (colleague)" in judged.spy.parked["marc"].aliases
    second = judged.spy.parked["marc-2"]
    assert second.title == "Marc" and "Marc (cousin)" in second.aliases
    # The cousin's edge and value are pinned to its own id; the colleague's follow the bare name.
    assert extracted[0]["relationships"][1]["source_page"] == "marc-2"
    assert extracted[0]["values"][0]["source_page"] == "marc-2"
    assert extracted[0]["relationships"][0]["source"] == "Marc" and "source_page" not in extracted[0]["relationships"][0]
    from api.services import merge_rejections

    assert ("marc", "marc-2") in merge_rejections.load_split(memory)
    assert judged.calls == [], "nothing on record: nothing to ask"


def test_a_known_page_takes_its_own_person_of_the_conversation_and_the_other_is_a_second_person(tmp_path, judged):
    memory = _bank(tmp_path)
    colleague = _page("marc", PAGE_TEXT, ["k1", "k2"])
    judged.answer = ans("AC", "B")
    out = _run(er.resolve([_both("e1")], [colleague], _settings(memory)))
    updates = {c["id"]: c for c in out["changes"] if c["action"] == "update"}
    assert "marc" in updates and "Marc (colleague)" in (updates["marc"]["entity"].get("aliases") or [])
    assert set(judged.spy.parked) == {"marc-2"}, judged.spy.parked
    assert judged.spy.parked["marc-2"].title == "Marc"
    assert len(judged.calls) == 1


def test_a_person_with_a_qualifier_and_nobody_to_compare_is_the_bare_names(tmp_path, judged):
    memory = _bank(tmp_path)
    extracted = [{"episode_id": "e1", "origin": "chatgpt", "entities": [
        {"name": "Marc (colleague)", "type": "person", "confidence": 0.8, "summary": COLLEAGUE[13:], "source_episode": "e1",
         "source_episode_timestamp": "2026-10-02T00:00:00+00:00"}],
        "relationships": [{"source": "Marc (colleague)", "target": "Nina Example", "label": "works with", "source_episode": "e1"}],
        "values": []}]
    _run(er.resolve(extracted, [], _settings(memory)))
    assert set(judged.spy.parked) == {"marc"}
    assert extracted[0]["relationships"][0]["source"] == "Marc"
    assert judged.calls == []


@pytest.mark.parametrize("entity", [
    {"name": "Mercury (planet)", "type": "concept"},          # not a person
    {"name": "Marc Dupont (colleague)", "type": "person"},     # a real two-word name
    {"name": "mdupont (Marc Dupont)", "type": "person"},       # a handle the record paired
])
def test_a_parenthesis_that_is_not_a_qualifier_of_a_bare_person_name_is_untouched(tmp_path, judged, entity):
    memory = _bank(tmp_path)
    extracted = [{"episode_id": "e1", "origin": "chatgpt", "entities": [
        {**entity, "confidence": 0.8, "summary": COLLEAGUE[13:], "source_episode": "e1",
         "source_episode_timestamp": "2026-10-02T00:00:00+00:00"}], "relationships": [], "values": []}]
    moves, compared, _ = _run(er._plan_same_name_people(extracted, [], {}, _settings(memory), refs=SimpleNamespace(
        is_speaker=lambda *a, **k: False), owner_page_id=None))
    assert moves == {} and compared == {}


def test_two_groups_the_conversation_told_apart_that_both_hold_the_same_page_leave_one_of_them_a_person_of_its_own():
    """The judge puts a page's slides conversation with the finance Marc and its other conversations with the cousin: the
    page holds both people (flagged for the tail), and the conversation that names both must not put both on the page."""
    page = snp.Identity("page", "marc", True, "x", frozenset({"k1", "k2", "k3"}),
                        (snp.Item("(2026-09-01) " + PAGE_TEXT, ("k1",)), snp.Item("(2026-09-20) " + PAGE_TEXT, ("k2",)),
                         snp.Item("(2026-10-03) slides for the budget review will be sent this evening to the speaker by Marc", ("k3",))))
    # letters: A = colleague (qualified), B = cousin (qualified); then the page's items newest first: C = k3, D = k2, E = k1
    plan = _run(snp.plan("Marc", _two(), [page], _judge(ans("BDE", "AC"))))
    assert plan.moves[CK] == snp.Destination("page", "marc")
    assert plan.moves[SK].kind == "new" and not plan.moves[SK].doubt, plan.moves
    assert "marc" in plan.review_pages


def test_stage_1_is_told_how_to_write_two_people_of_one_name_in_one_conversation():
    from api.services.entity_extractor import EXTRACTION_SYSTEM_PROMPT as prompt

    assert "share a name" in prompt and "(what tells them apart)" in prompt
    assert "never with it in front of the name or after it" in prompt


# ------------------------------------------------------------------ what an independent review found (2026-11-24, second pass)

THIN_COUSIN = "(2026-10-02) the speaker's cousin"


def _sibling_moves(plan, mentions):
    return [plan.moves.get(m.episode) for m in mentions]


@pytest.mark.parametrize("order", ["colleague-first", "cousin-first"])
@pytest.mark.parametrize("answer", [ans("ABC"), ans("ABCD"), ans("ABCDE"), None, {"nonsense": 1}, RuntimeError("down")],
                         ids=["abc", "abcd", "abcde", "none", "unreadable", "failure"])
def test_when_the_judge_puts_both_with_the_person_on_record_or_fails_neither_takes_the_page_by_order(order, answer):
    """Defect 1: which of the two the page keeps was mention order. Nothing says which one is the person on record, so
    neither is: each waits as a person of its own, in doubt against the page, and the two stay apart from each other."""
    mentions = _two() if order == "colleague-first" else list(reversed(_two()))
    plan = _run(snp.plan("Marc", mentions, [_page_identity()], _judge(answer)))
    moves = _sibling_moves(plan, mentions)
    assert all(d is not None and d.kind == "new" and d.doubt for d in moves), plan.moves
    assert moves[0].ref != moves[1].ref, "the two of one conversation are two people of their own"
    assert plan.review


def _both_in(first, second, episode="e1"):
    """The conversation of ``_both`` with its two people listed in the other order when ``first`` is "cousin"."""
    base = _both(episode)
    if first == "cousin":
        base["entities"].reverse()
        base["relationships"].reverse()
    return base


@pytest.mark.parametrize("first", ["colleague", "cousin"])
@pytest.mark.parametrize("answer", [ans("ABC"), None, RuntimeError("down")], ids=["one-person", "unreadable", "failure"])
def test_the_page_on_record_never_takes_a_sibling_by_order_in_a_real_run(tmp_path, judged, first, answer):
    from api.services import merge_rejections, same_name_doubts

    memory = _bank(tmp_path)
    judged.answer = answer
    extracted = [_both_in(first, "x")]
    out = _run(er.resolve(extracted, [_page("marc", PAGE_TEXT, ["k1", "k2"])], _settings(memory)))
    updates = {c["id"]: c for c in out["changes"] if c["action"] == "update"}
    assert "marc" not in updates or not any(w in str(updates["marc"]) for w in ("cousin", "carpenter", "furniture")), updates
    assert set(judged.spy.parked) == {"marc-2", "marc-3"}, judged.spy.parked
    for r in extracted[0]["relationships"]:   # both people's edges follow their own page, neither the colleague page by order
        assert r.get("source_page") in {"marc-2", "marc-3"}, r
    assert extracted[0]["values"][0]["source_page"] in {"marc-2", "marc-3"}
    assert ("marc-2", "marc-3") in merge_rejections.load_split(memory), "told apart by the conversation that named both"
    doubts = same_name_doubts.pairs(memory)
    assert ("marc", "marc-2") in doubts and ("marc", "marc-3") in doubts, doubts


def test_a_thin_qualified_mention_the_judge_calls_different_is_a_person_in_doubt_never_left_under_its_written_name():
    """Defect 2: a qualified person with a thin description became a held line titled "Marc (cousin)"."""
    thin = [snp.Mention(CK, THIN_COUSIN, "e1", True)]
    plan = _run(snp.plan("Marc", thin, [_page_identity()], _judge(ans("A", "BC", pairs=[(1, 2, "different", "the speaker's cousin", "runs the Monday standup")]))))
    move = plan.moves[CK]
    assert move.kind == "new" and move.doubt, "thin is cannot-tell: a person of its own, held in doubt, never joined to the page"


def test_a_thin_bare_mention_the_judge_calls_different_still_goes_back_to_the_plain_name():
    plan = _run(snp.plan("Marc", [snp.Mention("e9", "(2026-10-02) a cousin")], [_page_identity()],
                         _judge(ans("A", "BC", pairs=[(1, 2, "different", "a cousin", "runs the Monday standup")]))))
    assert plan.moves == {} and plan.thin == 1


def test_a_thin_qualified_mention_in_a_real_run_is_never_a_line_or_page_titled_with_its_qualifier(tmp_path, judged):
    memory = _bank(tmp_path)
    judged.answer = ans("A", "BC", pairs=[(1, 2, "different", "the speaker's cousin", "runs the Monday standup")])
    extracted = [{"episode_id": "e1", "origin": "chatgpt", "entities": [
        {"name": "Marc (cousin)", "type": "person", "confidence": 0.8, "summary": "the speaker's cousin",
         "source_episode": "e1", "source_episode_timestamp": "2026-10-02T00:00:00+00:00"}],
        "relationships": [{"source": "Marc (cousin)", "target": "Nina Example", "label": "cousin of", "source_episode": "e1"}],
        "values": []}]
    out = _run(er.resolve(extracted, [_page("marc", PAGE_TEXT, ["k1", "k2"])], _settings(memory)))
    assert set(judged.spy.parked) == {"marc-2"}, judged.spy.parked
    assert extracted[0]["relationships"][0]["source_page"] == "marc-2"
    assert not [c for c in out["changes"] if "(" in str(c.get("id")) or "(" in str((c.get("entity") or {}).get("name"))]


def _titled_with_a_qualifier(out, spy):
    names = [str(c.get("id")) for c in out["changes"]] + [str((c.get("entity") or {}).get("name")) for c in out["changes"]]
    names += list(spy.parked) + [str(getattr(e, "title", "") or e.name) for e in spy.parked.values()]
    return [n for n in names if "(" in n]


def _cousin(episode="e1", summary="the speaker's cousin, a carpenter in a small mountain town who builds furniture and helps with the shelves"):
    return {"episode_id": episode, "origin": "chatgpt", "entities": [
        {"name": "Marc (cousin)", "type": "person", "confidence": 0.8, "summary": summary, "source_episode": episode,
         "source_episode_timestamp": "2026-10-02T00:00:00+00:00"}],
        "relationships": [{"source": "Marc (cousin)", "target": "Nina Example", "label": "cousin of", "source_episode": episode}],
        "values": []}


@pytest.mark.parametrize("scenario", ["judge-fails-with-a-page", "judge-calls-one-person", "thin-different", "undescribed",
                                      "nobody-on-record", "over-the-mention-cap", "cancelled", "over-the-name-cap"])
def test_no_page_or_line_is_ever_titled_with_a_qualifier_on_any_exit_of_the_placement(tmp_path, judged, monkeypatch, scenario):
    """Every way out of `plan` / `_place` / the resolver's own routing: the written name "Marc (cousin)" is the person's
    qualifier, never a title (2026-11-24)."""
    memory = _bank(tmp_path)
    existing = [_page("marc", PAGE_TEXT, ["k1", "k2"])]
    extracted = [_cousin()]
    cancel = None
    judged.answer = ans("A", "BC", pairs=[(1, 2, "different", "carpenter in a small mountain town", "runs the Monday standup")])
    if scenario == "judge-fails-with-a-page":
        judged.answer = RuntimeError("down")
    elif scenario == "judge-calls-one-person":
        judged.answer = ans("ABC")
    elif scenario == "thin-different":
        extracted = [_cousin(summary="the speaker's cousin")]
        judged.answer = ans("A", "BC", pairs=[(1, 2, "different", "the speaker's cousin", "runs the Monday standup")])
    elif scenario == "undescribed":
        extracted = [_cousin(summary="")]
    elif scenario == "nobody-on-record":
        existing = []
    elif scenario == "over-the-mention-cap":
        monkeypatch.setattr(snp, "MAX_MENTIONS", 1)
        extracted = [_cousin(f"e{n}") for n in range(1, 4)]
    elif scenario == "cancelled":
        cancel = lambda: True   # noqa: E731
    elif scenario == "over-the-name-cap":
        monkeypatch.setattr(snp, "MAX_NAMES", 0)
    out = _run(er.resolve(extracted, existing, _settings(memory), **({"cancel_check": cancel} if cancel else {})))
    assert _titled_with_a_qualifier(out, judged.spy) == []
    for extraction in extracted:   # and what the conversation's edges name is a page id or the bare name, never the qualified one
        for rel in extraction["relationships"]:
            assert rel.get("source_page") or "(" not in str(rel["source"]), rel


# Defect 3: two spellings are not "apart for good". Stage 1 writes the qualifier for both people of a conversation that names
# two (every one of 66 replayed two-person conversations: both qualified, never a bare name beside a qualified one;
# `~/cicada-bench/fable/both/s1-final-raw.jsonl`), and one person it described twice it wrote as ONE entity (12 of 12
# controls). So two qualified is the conversation telling them apart; a bare name beside a qualified one is a shape Stage 1
# did not produce in either kind of replay, and it is held in doubt, never decided.

NEAR_A = "(2026-10-02) the finance lead on the research team at the firm, who runs the Monday standup and is moving to another office"
NEAR_B = "(2026-10-02) the speaker's colleague on the research team at the firm, who runs the Monday standup and is moving to another office"


def test_a_bare_name_beside_a_qualified_one_in_one_conversation_is_held_in_doubt_never_apart():
    bare, qualified = snp.Mention("e1", COLLEAGUE, "e1", False, False), snp.Mention(CK, COUSIN, "e1", True, True)
    for mentions in ([bare, qualified], [qualified, bare]):
        plan = _run(snp.plan("Marc", mentions, [], _judge(Exception("never asked"))))
        news = [d for d in plan.moves.values() if d.kind == "new"]
        assert len(news) == 1 and news[0].doubt, plan.moves
        assert plan.review


def test_two_qualified_people_with_near_identical_summaries_are_still_two_people_the_conversation_named_both():
    mentions = [snp.Mention(snp.mention_key("e1", "Marc (finance lead)"), NEAR_A, "e1", True),
                snp.Mention(snp.mention_key("e1", "Marc (my colleague)"), NEAR_B, "e1", True)]
    plan = _run(snp.plan("Marc", mentions, [], _judge(Exception("never asked"))))
    new = [d for d in plan.moves.values() if d.kind == "new"]
    assert len(new) == 1 and not new[0].doubt


def test_a_bare_name_beside_a_qualified_one_leaves_a_doubt_not_a_split_in_a_real_run(tmp_path, judged):
    from api.services import merge_rejections, same_name_doubts

    memory = _bank(tmp_path)
    extracted = [_both("e1", qualified=("Marc", "Marc (cousin)"))]
    _run(er.resolve(extracted, [], _settings(memory)))
    assert set(judged.spy.parked) == {"marc", "marc-2"}
    assert merge_rejections.load_split(memory) == set()
    assert ("marc", "marc-2") in same_name_doubts.pairs(memory)
    assert extracted[0]["relationships"][1]["source_page"] == "marc-2"


def test_two_qualified_people_one_conversation_named_are_split_for_good_in_a_real_run(tmp_path, judged):
    from api.services import merge_rejections, same_name_doubts

    memory = _bank(tmp_path)
    _run(er.resolve([_both("e1")], [], _settings(memory)))
    assert ("marc", "marc-2") in merge_rejections.load_split(memory)
    assert same_name_doubts.pairs(memory) == {}


# Defect 4: a conversation a person already lists is that person on a re-read, whatever the judge says.


def _filed_page(page_id, alias, episodes):
    return {"id": page_id, "frontmatter": {"name": "Marc", "type": "person", "confidence": 0.8, "source_episodes": episodes,
                                           "aliases": [alias]}, "body": f"## Summary\n{COLLEAGUE[13:]}\n"}


@pytest.mark.parametrize("answer", [None, {"nonsense": 1}, RuntimeError("down")], ids=["none", "unreadable", "failure"])
@pytest.mark.parametrize("first", ["colleague", "cousin"])
def test_a_conversation_already_filed_on_two_people_goes_back_to_them_on_a_re_read_and_mints_no_third(tmp_path, judged, answer, first):
    memory = _bank(tmp_path)
    judged.answer = answer
    pages = [_filed_page("marc", "Marc (colleague)", ["e1", "k1"]), _filed_page("marc-2", "Marc (cousin)", ["e1"])]
    extracted = [_both_in(first, "x", "e1")]
    out = _run(er.resolve(extracted, pages, _settings(memory)))
    assert judged.spy.parked == {}, "no third person"
    updates = {c["id"] for c in out["changes"] if c["action"] == "update"}
    assert updates <= {"marc", "marc-2"} and not [c for c in out["changes"] if c["action"] == "create"]
    pins = {r["label"]: r.get("source_page") for r in extracted[0]["relationships"]}
    assert pins["cousin of"] == "marc-2", pins
    assert judged.calls == [], "matched by the alias the first read wrote, no judge"


def test_a_conversation_filed_on_one_person_is_still_judged_when_it_names_two():
    from api.services import entity_resolver as r   # noqa: F401  (the rule's one-holder case stays as it was)

    holders = [snp.Identity("page", "marc", True, "x", frozenset({"e1"}))]
    assert snp.identity_for_episode("e1", holders).ref == "marc"


# Defect 5: the qualifier is what the conversation says tells them apart; the judge reads it.


def test_the_qualifier_reaches_the_judge_and_counts_toward_a_description():
    text = snp.describe({"name": "Marc (cousin)", "summary": "met at the party", "source_episode_timestamp": "2026-10-02T00:00:00+00:00"})
    assert "cousin" in text
    assert "cousin" in snp.describe({"name": "Marc (cousin)", "summary": "", "source_episode_timestamp": "2026-10-02T00:00:00+00:00"})
    assert snp.describe({"name": "Marc", "summary": "met at the party"}) == "met at the party"


def test_a_name_a_nickname_page_bears_is_not_for_this_rule_and_its_qualified_mention_is_left_as_it_was(tmp_path, judged):
    """The name is a nickname many answer to (`role_people`): the same-name step never reaches it, so the safety net that
    keeps a qualified person off its written name does not either."""
    memory = _bank(tmp_path)
    page = _page("marc", PAGE_TEXT, ["k1", "k2"])
    page["frontmatter"]["nickname_title"] = True
    _run(er.resolve([_cousin()], [page], _settings(memory)))
    assert judged.calls == [] and "marc-2" not in judged.spy.parked


def test_a_second_reading_that_leaves_the_person_on_records_conversations_out_does_not_replace_the_first():
    """A real run (2026-11-24): the main model's second look grouped only this batch's two people and left the page's three
    conversations out, so the cousin who is on the page became a third person. An answer that accounts for fewer descriptions
    than it was shown is no answer to replace the first with."""
    page = snp.Identity("page", "marc", True, PAGE_TEXT, frozenset({"k1", "k2", "k3"}),
                        tuple(snp.Item(f"(2026-09-0{n}) " + PAGE_TEXT, (f"k{n}",)) for n in (1, 2, 3)))
    small = ans("ACDE", "B", pairs=[(1, 2, "different", "runs the Monday standup", "carpenter in a small mountain town")])
    strong = ans("A", "B", pairs=[(1, 2, "different", "a colleague on the research team", "carpenter in a small mountain town")])
    plan = _run(snp.plan("Marc", _two(), [page], _judge(small), _judge(strong)))
    assert plan.second
    assert plan.moves[SK] == snp.Destination("page", "marc"), plan.moves
    assert plan.moves[CK].kind == "new"
