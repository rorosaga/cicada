"""Ruling 48 (8) — the in-app catch-up chat (``catchup_chat``): one turn on the person's chosen engine that answers like
a person would, readings kept only when they rest on the person's own words and applied by the app at once (owner
2026-11-05), several parts of one message each on its own question, the chat kept as one episode per session; and the plain question and reason served on ``GET /inbox`` (ruling 48 (1)).
Synthetic bank, placeholder names."""
import json

import pytest
import yaml
from fastapi.testclient import TestClient

from api import config, main
from api.services import catchup_chat, demo_guard, engine_readiness, engine_select, inbox_service, markdown_parser
from api.services import mcp_tools
from api.tests.test_inbox_catchup import OWNER, bank, ctx, item, page  # noqa: F401 — the shared fixture

STILL = [{"key": "a", "label": "Org Gamma"}, {"key": "neither", "label": "Not anymore"}]


def still_item(bank, num=1, **kw):
    page(bank, "org-gamma", name="Org Gamma", type_="company", convs=3, said=-200)
    return item(bank, num, entity_id=OWNER, entity_name="Owner Example", predicate="works-at", asks="still",
                question="Do you still work at Org Gamma?", title="t", options=STILL, allow_other=True, **kw)


def fake(reply: dict):
    seen = {}

    def llm(system, prompt):
        seen["system"], seen["prompt"] = system, prompt
        return json.dumps(reply)

    return llm, seen


# --------------------------------------------------------------------------- the served words


def test_the_inbox_serves_each_question_in_plain_words_with_its_reason(bank):
    still = still_item(bank)
    page(bank, "tool-beta", name="Tool Beta", type_="tool", said=-40)
    decay = item(bank, 2, kind="decay", entity_id="tool-beta", entity_name="Tool Beta", title="t")
    item(bank, 3, kind="removal", entity_id="tool-beta", entity_name="Tool Beta", title="Remove a bookmark",
         required_input="none")
    served = {i.id: i for i in inbox_service.load_inbox(bank)}
    assert served[still].spoken_question == "Are you still working at Org Gamma?"
    assert served[still].spoken_reason
    assert served[decay].spoken_question == "Do you still use Tool Beta?"
    # The person's own housekeeping keeps its stored words.
    assert served["inbox-003"].spoken_question is None
    wire = served[still].model_dump(by_alias=True)
    assert "spokenQuestion" in wire and "spokenReason" in wire


# --------------------------------------------------------------------------- one turn


def test_a_reading_on_the_persons_own_words_comes_back_to_apply_and_this_call_writes_nothing(bank):
    still = still_item(bank)
    before = (bank / "inbox" / f"{still}.md").read_text()
    llm, seen = fake({"reply": "", "move": "next",
                      "readings": [{"item_id": still, "option_key": "a", "answer": None, "quote": "still there"}]})
    out = catchup_chat.turn(bank, still, "Yes, still there!", [{"who": "cicada", "text": "Still at Org Gamma?"}], [],
                            llm)
    assert out["reply"] is None and out["move"] == "next" and out["engine"] is True
    assert out["readings"] == [{"itemId": still, "optionKey": "a", "answer": None, "quote": "still there",
                                "mergeTarget": None, "targetName": None}]
    assert (bank / "inbox" / f"{still}.md").read_text() == before
    # The model is handed the question, its answers by key, what Cicada has on the page and the chat so far.
    assert "Are you still working at Org Gamma?" in seen["prompt"] and '"key": "a"' in seen["prompt"]
    assert "Owner Example: person" in seen["prompt"] and "cicada: Still at Org Gamma?" in seen["prompt"]
    assert "never guess who someone is" in seen["system"]
    # Owner 2026-11-05: no asking back; the model judges clarity, a hedge about their own life is their answer.
    assert "never ask them to confirm" in seen["system"] and "still their answer" in seen["system"]


@pytest.mark.parametrize("reading", [
    {"option_key": "a", "quote": "I never said this"},          # the quote is not in their words
    {"option_key": "zz", "quote": "still there"},               # not one of the question's keys
    {"option_key": None, "answer": "Org Delta", "quote": "still there"},   # an answer they never typed
    {"option_key": None, "answer": None, "quote": "still there"},          # nothing to apply
    {"item_id": "inbox-999", "option_key": "a", "quote": "still there"},   # a question it was not offered
])
def test_a_reading_that_does_not_rest_on_their_words_is_dropped_and_the_reply_stands(bank, reading):
    still = still_item(bank)
    llm, _ = fake({"reply": "Tell me more?", "move": "stay", "readings": [reading]})
    out = catchup_chat.turn(bank, still, "Yes, still there", [], [], llm)
    assert out["readings"] == [] and out["reply"] == "Tell me more?"


def test_a_free_answer_must_be_their_own_characters_found_never_fuzzy(bank):
    still = still_item(bank)
    llm, _ = fake({"reply": "", "move": "next",
                   "readings": [{"option_key": "neither", "answer": "org delta", "quote": "moved to Org Delta"}]})
    out = catchup_chat.turn(bank, still, "No — I moved to Org Delta in May", [], [], llm)
    # Case-insensitive locate, but the person's own characters are what is applied.
    assert out["readings"][0]["answer"] == "Org Delta" and out["readings"][0]["optionKey"] == "neither"


def people(bank, *names):
    for slug, name in names:
        page(bank, slug, name=name, type_="person", convs=5)


def pair(bank, num, a, a_name, b):
    return item(bank, num, kind="merge_suggestion", entity_id=a, entity_name=a_name, merge_target_hint=b, title="t",
                required_input="merge")


def test_a_same_person_answer_in_their_own_words_is_returned_like_any_other(bank):
    people(bank, ("person-a", "Sam Example"), ("person-b", "Samantha Example"))
    one = pair(bank, 1, "person-a", "Sam Example", "person-b")
    llm, seen = fake({"reply": "", "move": "next", "readings": [{"option_key": "same", "quote": "same person"}]})
    out = catchup_chat.turn(bank, one, "Yes, same person", [], [], llm)
    assert out["readings"][0]["optionKey"] == "same" and out["readings"][0]["itemId"] == one
    assert '"key": "same"' in seen["prompt"] and '"key": "different"' in seen["prompt"]


TWO_PARTS = "handle-a i believe is Person Bee. I am Owner Example, nothing to do with her."


def trio(bank):
    people(bank, ("handle-a", "handle-a"), ("owner-x", "Owner Example"), ("person-b", "Person Bee"))


def test_two_answers_in_one_message_each_resolve_their_own_pair(bank):
    # The owner's case, 2026-11-05 (real names redacted): both pairs are settled by one message, each on its own words.
    trio(bank)
    first = pair(bank, 1, "handle-a", "handle-a", "owner-x")
    second = pair(bank, 2, "person-b", "Person Bee", "handle-a")
    llm, seen = fake({"reply": "", "move": "next", "readings": [
        {"item_id": second, "option_key": "same", "quote": "handle-a i believe is Person Bee"},
        {"item_id": first, "option_key": "different", "quote": "I am Owner Example, nothing to do with her"}]})
    out = catchup_chat.turn(bank, first, TWO_PARTS, [], [], llm)
    assert {r["itemId"]: r["optionKey"] for r in out["readings"]} == {second: "same", first: "different"}
    assert out["unjoined"] == []
    assert f'"id": "{second}"' in seen["prompt"], "the chain's pairs are on the table"


def test_a_join_no_pair_holds_goes_through_a_pair_the_same_message_parted(bank):
    trio(bank)
    first = pair(bank, 1, "handle-a", "handle-a", "owner-x")
    second = pair(bank, 2, "person-b", "Person Bee", "owner-x")
    llm, _ = fake({"reply": "", "move": "next", "readings": [
        {"join": ["handle-a", "Person Bee"], "quote": "handle-a i believe is Person Bee"},
        {"item_id": first, "option_key": "different", "quote": "nothing to do with her"},
        {"item_id": second, "option_key": "different", "quote": "nothing to do with her"}]})
    out = catchup_chat.turn(bank, first, TWO_PARTS, [], [], llm)
    by_id = {r["itemId"]: r for r in out["readings"]}
    # The parted pair's subject joins the person they named; the other pair stays apart.
    assert by_id[first]["optionKey"] == "same" and by_id[first]["mergeTarget"] == "person-b"
    assert by_id[first]["targetName"] == "Person Bee" and by_id[first]["quote"] == "handle-a i believe is Person Bee"
    assert by_id[second]["optionKey"] == "different" and by_id[second]["mergeTarget"] is None


def test_the_resolver_carries_a_join_on_a_parted_pair_and_the_quote_is_kept(client, bank):
    # The app's own request for that reading: the pair's subject merges into the person named, not the pair's other side.
    trio(bank)
    first = pair(bank, 1, "handle-a", "handle-a", "owner-x")
    owner_before = (bank / "entities" / "owner-x.md").read_text()
    r = client.post(f"/inbox/{first}/resolve", json={
        "action": "merge", "mergeTarget": "person-b", "mergeSurvivor": "person-b",
        "quote": "handle-a i believe is Person Bee", "relayedBy": "cicada-catchup"})
    assert r.status_code == 200, r.text
    # The same merge a pair's own target gets: the question closes, the person's verdict lands on the page they named.
    assert not (bank / "inbox" / f"{first}.md").exists()
    assert owner_before == (bank / "entities" / "owner-x.md").read_text(), "the pair's other side is not touched"
    assert "handle-a" in (bank / "entities" / "person-b.md").read_text()


def test_a_same_on_the_owners_page_is_never_applied_from_typed_words(bank, monkeypatch):
    """Review of #637: the quote is real, but "I am <owner>" does not say the handle is the owner."""
    from api.services import owner_identity

    trio(bank)
    monkeypatch.setattr(owner_identity, "owner_page_id", lambda *a, **k: "owner-x")
    first = pair(bank, 1, "handle-a", "handle-a", "owner-x")
    llm, _ = fake({"reply": "", "move": "next", "readings": [
        {"item_id": first, "option_key": "same", "quote": "nothing to do with her"}]})
    out = catchup_chat.turn(bank, first, TWO_PARTS, [], [], llm)
    assert out["readings"] == []
    assert [u["a"] for u in out["unjoined"]] == ["handle-a"], "the page's name, for the chat's line"


def test_a_join_no_question_can_carry_is_named_and_closes_nothing(bank):
    # Both pairs have the owner as their subject, and a question they did not answer is never closed to carry it.
    trio(bank)
    first = pair(bank, 1, "owner-x", "Owner Example", "handle-a")
    second = pair(bank, 2, "owner-x", "Owner Example", "person-b")
    llm, _ = fake({"reply": "", "move": "next", "readings": [
        {"join": ["handle-a", "Person Bee"], "quote": "handle-a i believe is Person Bee"},
        {"item_id": first, "option_key": "different", "quote": "nothing to do with her"},
        {"item_id": second, "option_key": "different", "quote": "nothing to do with her"}]})
    out = catchup_chat.turn(bank, first, TWO_PARTS, [], [], llm)
    assert out["unjoined"] == [{"a": "handle-a", "b": "Person Bee"}]
    assert {r["optionKey"] for r in out["readings"]} == {"different"}


def test_one_message_may_answer_the_question_and_an_upcoming_one(bank):
    still = still_item(bank)
    page(bank, "tool-beta", name="Tool Beta", type_="tool", said=-40)
    other = item(bank, 2, entity_id="tool-beta", entity_name="Tool Beta", title="t", question="Still using Tool Beta?",
                 options=[{"key": "keep", "label": "Yes"}, {"key": "drop", "label": "No"}])
    llm, seen = fake({"reply": "", "move": "next", "readings": [
        {"item_id": still, "option_key": "a", "quote": "still at Org Gamma"},
        {"item_id": other, "option_key": "drop", "quote": "dropped Tool Beta"}]})
    out = catchup_chat.turn(bank, still, "I'm still at Org Gamma, and I dropped Tool Beta", [], [other], llm)
    assert {r["itemId"] for r in out["readings"]} == {still, other}
    assert '"key": "drop"' in seen["prompt"], "an upcoming question's answers are offered too"


def test_two_different_answers_to_one_question_hold_neither_and_the_reply_says_why(bank):
    still = still_item(bank)
    llm, _ = fake({"reply": "Both? Tell me which still holds.", "move": "stay", "readings": [
        {"option_key": "a", "quote": "still there"}, {"option_key": "neither", "quote": "not anymore"}]})
    out = catchup_chat.turn(bank, still, "still there, well, not anymore", [], [], llm)
    assert out["readings"] == [] and out["reply"].startswith("Both?")


def test_a_clear_reading_needs_no_words_but_nothing_usable_keeps_the_question(bank):
    still = still_item(bank)
    llm, _ = fake({"reply": "", "move": "stay", "readings": []})
    assert catchup_chat.turn(bank, still, "hmm", [], [], llm)["reply"] is None
    llm, _ = fake({"reply": "", "move": "later", "readings": []})
    assert catchup_chat.turn(bank, still, "another day", [], [], llm)["move"] == "later"


def test_a_reply_may_move_to_a_related_question_but_only_one_it_was_offered(bank):
    still = still_item(bank)
    page(bank, "tool-beta", name="Tool Beta", type_="tool", said=-40)
    other = item(bank, 2, kind="decay", entity_id="tool-beta", entity_name="Tool Beta", title="t")
    llm, seen = fake({"reply": "And Tool Beta?", "move": "next", "next_id": other, "readings": []})
    assert catchup_chat.turn(bank, still, "yes", [], [other], llm)["nextId"] == other
    assert "Do you still use Tool Beta?" in seen["prompt"]
    llm, _ = fake({"reply": "And?", "move": "next", "next_id": "inbox-999", "readings": []})
    assert catchup_chat.turn(bank, still, "yes", [], [other], llm)["nextId"] is None


def test_an_unusable_answer_keeps_the_question_open_and_a_gone_question_is_refused(bank):
    still = still_item(bank)
    out = catchup_chat.turn(bank, still, "hmm", [], [], lambda s, p: "not json at all")
    assert out == {"reply": None, "readings": [], "unjoined": [], "move": "stay", "nextId": None, "engine": True}
    with pytest.raises(LookupError):
        catchup_chat.turn(bank, "inbox-404", "hi", [], [], lambda s, p: "{}")
    with pytest.raises(LookupError):
        catchup_chat.turn(bank, "../entities/x", "hi", [], [], lambda s, p: "{}")
    with pytest.raises(ValueError):
        catchup_chat.turn(bank, still, "   ", [], [], lambda s, p: "{}")


# --------------------------------------------------------------------------- the record


def test_the_chat_is_one_episode_per_session_the_persons_turns_their_own(bank):
    turns = [{"who": "cicada", "text": "Still at Org Gamma?", "at": "2026-10-28T10:00:00Z"},
             {"who": "you", "text": "Yes, still there", "at": "2026-10-28T10:00:20Z"}]
    first = catchup_chat.record(bank, "catchup-session-1", turns)
    assert first["status"] == "created" and first["episodeId"]
    path = next((bank / "episodes").glob(f"{first['episodeId']}.md"))
    parsed = markdown_parser.parse(path)
    assert "user: Yes, still there" in parsed.body and "assistant: Still at Org Gamma?" in parsed.body
    assert parsed.frontmatter.get("processed") is False
    again = catchup_chat.record(bank, "catchup-session-1",
                                turns + [{"who": "you", "text": "and I started learning Topic Alpha"}])
    assert again["episodeId"] == first["episodeId"] and again["status"] == "updated"
    assert len(list((bank / "episodes").glob("*.md"))) == 1
    assert catchup_chat.record(bank, "catchup-session-2", turns[:1])["status"] == "empty"
    with pytest.raises(ValueError):
        catchup_chat.record(bank, "../x", turns)


def test_nothing_is_recorded_into_a_demo_bank(bank):
    demo_guard.manifest_path(bank).write_text(yaml.safe_dump({"kind": "demo"}))
    assert catchup_chat.record(bank, "catchup-session-1", [{"who": "you", "text": "hi"}])["status"] == "demo"
    assert not list((bank / "episodes").glob("*.md"))


# --------------------------------------------------------------------------- the routes and the other door


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_with_no_engine_the_turn_says_so_and_spends_nothing(client, bank, monkeypatch):
    still = still_item(bank)

    async def resolve(settings, **_k):
        return settings, "nothing signed in"

    monkeypatch.setattr(engine_select, "resolve_settings", resolve)
    monkeypatch.setattr(engine_readiness, "key_missing", lambda _s: True)
    r = client.post("/inbox/catchup/turn", json={"itemId": still, "message": "yes"})
    assert r.status_code == 200 and r.json()["engine"] is False and r.json()["reply"] is None


def test_the_turn_route_runs_on_the_resolved_engine_as_a_person_present(client, bank, monkeypatch):
    still = still_item(bank)
    asked = {}

    async def resolve(settings, **k):
        asked.update(k)
        return settings, "plan"

    def resolve_llm_fn(settings, **k):
        asked["stage"] = k.get("stage")

        def call(**_kw):
            msg = type("M", (), {"content": json.dumps({"reply": "Noted.", "move": "next", "readings": [{
                "option_key": "a", "quote": "still"}]})})
            return type("R", (), {"choices": [type("C", (), {"message": msg})]})

        return call

    monkeypatch.setattr(engine_select, "resolve_settings", resolve)
    monkeypatch.setattr(engine_readiness, "key_missing", lambda _s: False)
    monkeypatch.setattr("api.services.providers.resolve_llm_fn", resolve_llm_fn)
    r = client.post("/inbox/catchup/turn", json={"itemId": still, "message": "still"})
    assert r.status_code == 200, r.text
    assert r.json()["readings"][0]["optionKey"] == "a" and asked["user_triggered"] is True and asked["stage"] == "catchup"
    assert client.post("/inbox/catchup/turn", json={"itemId": "inbox-404", "message": "x"}).status_code == 404


def test_the_record_route_keeps_the_chat(client, bank):
    r = client.post("/inbox/catchup/record", json={"sessionId": "catchup-session-9",
                                                    "turns": [{"who": "you", "text": "yes"}]})
    assert r.status_code == 200 and r.json()["status"] == "created"
    assert client.post("/inbox/catchup/record", json={"sessionId": "x", "turns": []}).status_code == 400


def test_the_harness_door_converses_from_the_same_facts(bank):
    still_item(bank)
    out = mcp_tools.check_nudges(ctx(bank), None, None, "catchup")
    assert "What Cicada has on it" in out and "Owner Example: person" in out
    assert "a conversation, not a quiz" in out


def test_the_inbox_tag_moves_with_the_day_so_a_relative_age_is_never_kept_overnight(client, bank, monkeypatch):
    from api.routers import inbox as inbox_router

    still_item(bank)
    monkeypatch.setattr(inbox_router, "_served_day", lambda: "2026-10-28")
    first = client.get("/inbox")
    tag = first.headers["etag"]
    assert client.get("/inbox", headers={"If-None-Match": tag}).status_code == 304
    monkeypatch.setattr(inbox_router, "_served_day", lambda: "2026-10-29")
    again = client.get("/inbox", headers={"If-None-Match": tag})
    assert again.status_code == 200 and again.headers["etag"] != tag
