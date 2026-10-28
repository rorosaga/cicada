"""Ruling 48 (8) — the in-app catch-up chat (``catchup_chat``): one turn on the person's chosen engine that answers like
a person would, a reading applied only when it rests on the person's own words, identity never applied from a reading,
the chat kept as one episode per session; and the plain question and reason served on ``GET /inbox`` (ruling 48 (1)).
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


def test_a_reading_on_the_persons_own_words_is_offered_and_nothing_is_written(bank):
    still = still_item(bank)
    before = (bank / "inbox" / f"{still}.md").read_text()
    llm, seen = fake({"reply": "Got it, still there.", "move": "next",
                      "reading": {"option_key": "a", "answer": None, "quote": "still there"}})
    out = catchup_chat.turn(bank, still, "Yes, still there!", [{"who": "cicada", "text": "Still at Org Gamma?"}], [],
                            llm)
    assert out["reply"] == "Got it, still there." and out["move"] == "next" and out["engine"] is True
    assert out["reading"] == {"optionKey": "a", "answer": None, "quote": "still there", "confirm": False}
    assert (bank / "inbox" / f"{still}.md").read_text() == before
    # The model is handed the question, its answers by key, what Cicada has on the page and the chat so far.
    assert "Are you still working at Org Gamma?" in seen["prompt"] and '"key": "a"' in seen["prompt"]
    assert "Owner Example: person" in seen["prompt"] and "cicada: Still at Org Gamma?" in seen["prompt"]
    assert "never guess who someone is" in seen["system"]


@pytest.mark.parametrize("reading", [
    {"option_key": "a", "quote": "I never said this"},          # the quote is not in their words
    {"option_key": "zz", "quote": "still there"},               # not one of the question's keys
    {"option_key": None, "answer": "Org Delta", "quote": "still there"},   # an answer they never typed
    {"option_key": None, "answer": None, "quote": "still there"},          # nothing to apply
])
def test_a_reading_that_does_not_rest_on_their_words_is_dropped_and_the_reply_stands(bank, reading):
    still = still_item(bank)
    llm, _ = fake({"reply": "Tell me more?", "move": "stay", "reading": reading})
    out = catchup_chat.turn(bank, still, "Yes, still there", [], [], llm)
    assert out["reading"] is None and out["reply"] == "Tell me more?"


def test_a_free_answer_must_be_their_own_characters_found_never_fuzzy(bank):
    still = still_item(bank)
    llm, _ = fake({"reply": "Noted.", "move": "next",
                   "reading": {"option_key": "neither", "answer": "org delta", "quote": "moved to Org Delta"}})
    out = catchup_chat.turn(bank, still, "No — I moved to Org Delta in May", [], [], llm)
    # Case-insensitive locate, but the person's own characters are what is applied.
    assert out["reading"]["answer"] == "Org Delta" and out["reading"]["optionKey"] == "neither"


def test_a_same_person_reading_is_never_applied_only_offered_for_their_tap(bank):
    page(bank, "person-a", name="Sam Example", type_="person", convs=5)
    page(bank, "person-b", name="Samantha Example", type_="person", convs=5)
    pair = item(bank, 1, kind="merge_suggestion", entity_id="person-a", entity_name="Sam Example",
                merge_target_hint="person-b", title="t", required_input="merge")
    llm, seen = fake({"reply": "So they're one person?", "move": "stay",
                      "reading": {"option_key": "same", "quote": "same person"}})
    out = catchup_chat.turn(bank, pair, "Yes, same person", [], [], llm)
    assert out["reading"]["optionKey"] == "same" and out["reading"]["confirm"] is True
    assert '"key": "same"' in seen["prompt"] and '"key": "different"' in seen["prompt"]


def test_a_reply_may_move_to_a_related_question_but_only_one_it_was_offered(bank):
    still = still_item(bank)
    page(bank, "tool-beta", name="Tool Beta", type_="tool", said=-40)
    other = item(bank, 2, kind="decay", entity_id="tool-beta", entity_name="Tool Beta", title="t")
    llm, seen = fake({"reply": "And Tool Beta?", "move": "next", "next_id": other, "reading": None})
    assert catchup_chat.turn(bank, still, "yes", [], [other], llm)["nextId"] == other
    assert "Do you still use Tool Beta?" in seen["prompt"]
    llm, _ = fake({"reply": "And?", "move": "next", "next_id": "inbox-999", "reading": None})
    assert catchup_chat.turn(bank, still, "yes", [], [other], llm)["nextId"] is None


def test_an_unusable_answer_keeps_the_question_open_and_a_gone_question_is_refused(bank):
    still = still_item(bank)
    out = catchup_chat.turn(bank, still, "hmm", [], [], lambda s, p: "not json at all")
    assert out == {"reply": None, "reading": None, "move": "stay", "nextId": None, "engine": True}
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
            msg = type("M", (), {"content": json.dumps({"reply": "Noted.", "move": "next", "reading": {
                "option_key": "a", "quote": "still"}})})
            return type("R", (), {"choices": [type("C", (), {"message": msg})]})

        return call

    monkeypatch.setattr(engine_select, "resolve_settings", resolve)
    monkeypatch.setattr(engine_readiness, "key_missing", lambda _s: False)
    monkeypatch.setattr("api.services.providers.resolve_llm_fn", resolve_llm_fn)
    r = client.post("/inbox/catchup/turn", json={"itemId": still, "message": "still"})
    assert r.status_code == 200, r.text
    assert r.json()["reading"]["optionKey"] == "a" and asked["user_triggered"] is True and asked["stage"] == "catchup"
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
