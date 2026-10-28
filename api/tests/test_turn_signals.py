"""Replies, reactions, forwards and unsends reach Stage 1 (`turn_signals`, owner 2026-10-28), and group chats are read
under G179's rails — every name, handle and line here is synthetic."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from _imessage_fixtures import apple_ns, utc
from api.config import Settings
from api.models.schemas import MessagesSyncRequest
from api.services import claims as claims_mod
from api.services import (bank_index, entity_extractor, evidence, markdown_parser, messages_source, promotion,
                          sleep_cycle, turn_signals)

CID = "c" * 24
GROUP = "d" * 24
A, B, C = "a1" * 8, "b2" * 8, "c3" * 8      # participant keys: the app's hashes, never a handle


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "bank"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def _row(n, at, text, *, me=False, sender=None, reply=None, react=None, target=None, emoji=None):
    row = {"rowid": n, "guid": f"G-{n:04d}", "date": apple_ns(at), "isFromMe": me, "text": text,
           "associatedMessageType": react or 0}
    if sender and not me:
        row["sender"] = sender
    if reply:
        row["threadOriginatorGuid"] = f"G-{reply:04d}"
    if target:
        row["associatedMessageGuid"] = f"p:0/G-{target:04d}"
    if emoji:
        row["associatedMessageEmoji"] = emoji
    return row


def _sync(memory, cid, rows, *, group=False, members=(), name="Agent Example"):
    conversation = {"id": cid, "name": name, "service": "iMessage", "group": group,
                    "members": [dict(m) for m in members]}
    body = MessagesSyncRequest.model_validate({"conversation": conversation, "messages": rows})
    out = messages_source.ingest(memory, body.model_dump(by_alias=False))
    bank_index.invalidate()
    return out


def _tick(memory, cid, **extra):
    messages_source.update_settings(memory, conversation={"id": cid, "ticked": True, **extra})


def _episodes(memory):
    return [markdown_parser.parse(p) for p in sorted((memory / "episodes").glob("*.md"))]


# --- the signals, read from what is stored -----------------------------------------------------------------------------


def _one_to_one(memory):
    _tick(memory, CID, actor={"kind": "agent"})
    day1 = [_row(1, utc(2026, 9, 1, 9), "Shall we take the 9pm train or the 11pm one?", sender=None),
            _row(2, utc(2026, 9, 1, 9, 1), "Let me check the timetable", me=True)]
    day3 = [_row(3, utc(2026, 9, 3, 18), "Also the hotel is booked for Friday"),
            _row(4, utc(2026, 9, 3, 18, 5), "yes", me=True, reply=1),               # two days later, another sitting
            _row(5, utc(2026, 9, 3, 18, 6), "Plan: leave Friday at 9pm, back Sunday"),
            _row(6, utc(2026, 9, 3, 18, 7), "Liked", me=True, react=2001, target=5),  # the person's 👍 on the plan
            _row(7, utc(2026, 9, 3, 18, 8), "ok", me=True, reply=3),                  # replies two lines up
            _row(8, utc(2026, 9, 3, 18, 9), "ok", me=True, reply=7)]                  # replies to the line above
    _sync(memory, CID, day1)
    _sync(memory, CID, day3)


def test_every_stored_signal_is_noted_and_spans_still_locate(bank):
    _one_to_one(bank)
    episodes = sleep_cycle._get_unprocessed_episodes(bank)
    later = next(e for e in episodes if "yes" in e["content"])
    lines = [s.line for s in later["signals"]]
    # The two-day-old question is found in the earlier sitting, with its day.
    assert any('user "yes" replies to assistant in an earlier sitting (2026-09-01): "Shall we take the 9pm' in line
               for line in lines)
    # The person's like is the person's signal on the agent's plan.
    assert any('user liked assistant "Plan: leave Friday at 9pm, back Sunday"' in line for line in lines)
    assert any('user "ok" replies to assistant "Also the hotel is booked for Friday"' in line for line in lines)
    # A reply to the line directly above needs no note.
    assert sum("replies to" in line for line in lines) == 2
    # Nothing in the body moved: each signal's window is a real line of the stored body.
    body = later["content"]
    for s in later["signals"]:
        if s.window:
            assert body[s.window[0]:s.window[1]].split(": ", 1)[0] in ("user", "assistant")


def test_a_reply_whose_target_cicada_does_not_hold_says_so():
    fm = {"turn_extras": [{"offset": 0, "reply_to": {"ref": "0123456789ab"}}]}
    (s,) = turn_signals.signals(fm, "user: that one", lookup=lambda ref: None)
    assert "replies to a message Cicada does not hold; what it answers is unknown, never guess it" in s.line


def test_forwards_and_unsends_say_whose_words_and_that_words_are_gone():
    body = "speaker:bob-example: the venue changed to alpha-hall\nuser: thanks"
    fm = {"turn_extras": [{"offset": 0, "forwarded_from": "Carol Example"}],
          "unsent_turns": [{"at": body.index("user:"), "speaker": "user"}]}
    lines = [s.line for s in turn_signals.signals(fm, body)]
    assert any("was forwarded from Carol Example: Carol Example's words, not speaker:bob-example's" in l for l in lines)
    assert any('user unsent a message before user "thanks"; its words are gone, never guess them' in l for l in lines)


def test_the_note_sits_with_the_chunk_it_belongs_to_and_is_small(bank):
    _one_to_one(bank)
    later = next(e for e in sleep_cycle._get_unprocessed_episodes(bank) if "yes" in e["content"])
    note = turn_signals.chunk_note(later["signals"], 0, len(later["content"]))
    assert note.startswith(turn_signals.NOTE_PREFIX) and note.endswith("]\n\n")
    assert turn_signals.chunk_note(later["signals"], len(later["content"]) + 1, len(later["content"]) + 9) is None
    # ~4 characters a token: three signals stay well under 250 tokens, the legend included.
    assert len(note) / 4 < 250


def test_a_tagged_short_quote_lands_on_its_own_line():
    body = "user: yes I mean the first one\nassistant: Dinner at alpha-place or beta-place?\nuser: yes"
    fm = {"turn_extras": [{"offset": body.rindex("user: yes"), "reply_to": 0}]}
    items = turn_signals.signals(fm, body)
    rel = {"evidence_quote": "yes", "signal": items[0].label}
    window, _ = turn_signals.anchor(rel, items, body, (0, len(body)))
    ev = evidence.verify(None, "ep_2026-09-01_001", rel["evidence_quote"], text=body, window=window)
    assert ev.start == body.rindex("yes") and "signal" not in rel
    # Untagged, the same quote would have landed on the first "yes".
    assert evidence.verify(None, "ep_2026-09-01_001", "yes", text=body, window=(0, len(body))).start == 6


# --- Stage 1 with a fake engine: the note is given, the person's reaction is the person's ---------------------------


def test_stage_one_is_told_the_signals_and_a_reaction_claim_is_the_persons(bank, monkeypatch):
    _one_to_one(bank)
    later = next(e for e in sleep_cycle._get_unprocessed_episodes(bank) if "yes" in e["content"])
    react = next(s for s in later["signals"] if s.kind == "reaction")
    reply = next(s for s in later["signals"] if "earlier sitting" in s.line)
    answer = {"entities": [{"name": "Friday trip", "type": "event", "confidence": 0.8, "summary": "A trip."}],
              "relationships": [
                  {"source": "Friday trip", "target": "9pm train", "label": "departs on",
                   "evidence_quote": "Plan: leave Friday at 9pm", "signal": react.label},
                  {"source": "Friday trip", "target": "9pm train", "label": "chosen",
                   "evidence_quote": "yes", "signal": reply.label},
                  {"source": "Friday trip", "target": "hotel", "label": "booked",
                   "evidence_quote": "the hotel is booked for Friday"}]}
    prompts = []

    async def fake(**kw):
        prompts.append(kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake)
    (out,) = asyncio.run(entity_extractor.extract([later], Settings(litellm_model="fake-engine", memory_path=bank)))
    (prompt,) = prompts
    assert prompt.index(turn_signals.NOTE_PREFIX) < prompt.index("assistant: Also the hotel")
    departs, chosen, booked = out["relationships"]
    # The person's 👍 moves the confidence and is recorded; whose claim it is never moves (#499 review).
    assert departs["observer"] == "external:agent-example"
    assert departs["reactions"][0]["stance"] == "agree" and departs["reactions"][0]["kind"] == "like"
    assert later["content"][departs["reactions"][0]["turn"]:].startswith("assistant: Plan: leave Friday")
    assert booked["observer"] == "external:agent-example"        # the agent's words alone are the agent's
    assert "reactions" not in booked
    body = later["content"]
    (ev,) = chosen["evidence"]
    assert body[ev["start"]:ev["end"]] == "yes" and ev["kind"] == "user"
    assert all("signal" not in r for r in out["relationships"])


# --- group chats -------------------------------------------------------------------------------------------------------


MEMBERS = ({"key": A, "name": "Alice Example"}, {"key": B, "name": "Bob Example"}, {"key": C, "name": "+1 555 000 0003"})


def _group(memory):
    _tick(memory, GROUP, name="Weekend crew")
    rows = [_row(1, utc(2026, 9, 5, 10), "I think alpha-hall is too small", sender=A),
            _row(2, utc(2026, 9, 5, 10, 1), "beta-hall then?", sender=B),
            _row(3, utc(2026, 9, 5, 10, 2), "I booked gamma-hall already", me=True),
            _row(4, utc(2026, 9, 5, 10, 3), "Loved", react=2000, target=3, sender=C),
            _row(5, utc(2026, 9, 5, 10, 4), "fine by me", sender=A, reply=2)]
    return _sync(memory, GROUP, rows, group=True, members=MEMBERS, name="Weekend crew")


def test_an_unticked_group_is_refused(bank):
    with pytest.raises(messages_source.NotSelected):
        _sync(bank, GROUP, [_row(1, utc(2026, 9, 5), "hi", sender=A)], group=True, members=MEMBERS)
    assert _episodes(bank) == []


def test_each_member_speaks_under_their_own_marker_and_no_handle_is_kept(bank):
    out = _group(bank)
    assert out["group"] is True
    (ep,) = _episodes(bank)
    assert ep.body.split("\n") == ["speaker:alice-example: I think alpha-hall is too small",
                                   "speaker:bob-example: beta-hall then?",
                                   "user: I booked gamma-hall already",
                                   "speaker:alice-example: fine by me"]
    fm = ep.frontmatter
    assert fm["group"] is True and "correspondent" not in fm
    by_key = {p["key"]: p for p in fm["participants"]}
    assert by_key[C]["marker"] == f"speaker:member-{C[:6]}" and "name" not in by_key[C]   # a phone number is no name
    assert "555" not in markdown_parser.parse(next((bank / "episodes").glob("*.md"))).body
    extras = {e["offset"]: e for e in fm["turn_extras"]}
    mine = ep.body.index("user:")
    assert extras[mine]["reactions"] == [{"by": f"speaker:member-{C[:6]}", "kind": "love", "emoji": "❤️"}]
    assert extras[ep.body.index("speaker:alice-example: fine")]["reply_to"] == ep.body.index("speaker:bob-example")


def test_a_later_pass_naming_nobody_keeps_every_marker(bank):
    _group(bank)
    _sync(bank, GROUP, [_row(6, utc(2026, 9, 5, 10, 9), "see you there", sender=B)], group=True, members=())
    (ep,) = _episodes(bank)
    assert ep.body.endswith("speaker:bob-example: see you there")
    assert ep.body.startswith("speaker:alice-example: I think")
    assert ep.frontmatter["turn_extras"][0]["offset"] >= 0


def test_a_member_is_an_agent_only_through_their_own_marked_chat(bank):
    direct = "e" * 24
    _tick(bank, direct, actor={"kind": "agent"})
    _tick(bank, GROUP)
    members = ({"key": A, "name": "Alice Example"}, {"key": B, "name": "Helper Bot", "direct": direct})
    _sync(bank, GROUP, [_row(1, utc(2026, 9, 6), "hi all", sender=A), _row(2, utc(2026, 9, 6, 0, 1), "hello", sender=B)],
          group=True, members=members)
    (ep,) = _episodes(bank)
    assert ep.body.split("\n") == ["speaker:alice-example: hi all", "assistant: hello"]


def test_group_claims_are_each_members_own_and_only_the_persons_lines_promote(bank, monkeypatch):
    _group(bank)
    (episode,) = sleep_cycle._get_unprocessed_episodes(bank)
    assert episode["group"] is True
    answer = {"entities": [{"name": "alpha-hall", "type": "place", "confidence": 0.8, "summary": "A hall."},
                           {"name": "gamma-hall", "type": "place", "confidence": 0.8, "summary": "A hall."}],
              "relationships": [
                  {"source": "Alice Example", "target": "alpha-hall", "label": "thinks too small",
                   "evidence_quote": "alpha-hall is too small"},
                  {"source": "owner", "target": "gamma-hall", "label": "booked",
                   "evidence_quote": "I booked gamma-hall already"},
                  {"source": "group", "target": "beta-hall", "label": "considered",
                   "evidence_quote": "beta-hall then?"}]}
    prompts = []

    async def fake(**kw):
        prompts.append(kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake)
    (out,) = asyncio.run(entity_extractor.extract([episode], Settings(litellm_model="fake-engine", memory_path=bank)))
    (prompt,) = prompts
    assert '"speaker:alice-example:" is Alice Example' in prompt and "a group chat" in prompt
    assert "replies to speaker:bob-example" in prompt and "loved user" in prompt
    alice, mine, bob = out["relationships"]
    assert alice["observer"] == "external:alice-example"
    assert "observer" not in mine and mine["evidence"][0]["kind"] == "user"
    assert bob["observer"] == "external:bob-example"
    assert not promotion.person_said(alice) and promotion.person_said(mine)
    alpha = next(e for e in out["entities"] if e["name"] == "alpha-hall")
    gamma = next(e for e in out["entities"] if e["name"] == "gamma-hall")
    assert alpha["named_by_person"] is False                 # only a member said it
    assert gamma["named_by_person"] is True


def test_an_agents_routine_tapback_is_not_noted_but_its_doubt_is():
    body = "user: we leave at 9\nassistant: noted"
    fm = {"turn_extras": [{"offset": 0, "reactions": [{"by": "assistant", "kind": "like"}]}]}
    assert turn_signals.signals(fm, body) == []
    fm = {"turn_extras": [{"offset": 0, "reactions": [{"by": "assistant", "kind": "question"}]}]}
    (s,) = turn_signals.signals(fm, body)
    assert s.line == 's1: assistant questioned user "we leave at 9"'


def test_the_persons_reaction_moves_confidence_never_the_observer():
    body = "assistant: Plan: ship alpha-project on Monday\nassistant: Or wait for beta-review"
    second = body.index("assistant: Or")
    fm = {"turn_extras": [{"offset": 0, "reactions": [{"by": "user", "kind": "like"}]},
                          {"offset": second, "reactions": [{"by": "user", "kind": "emoji", "emoji": "🤔"}]}]}
    plan = {"evidence": [{"kind": "assistant", "start": 11, "end": 20}], "confidence": 0.8}
    wait = {"evidence": [{"kind": "assistant", "start": second + 14, "end": second + 20}], "confidence": 0.8}
    episode = dict(fm, signals=turn_signals.signals(fm, body))
    entity_extractor._weigh_reaction(plan, episode, body, "ep_2026-09-04_001")
    entity_extractor._weigh_reaction(wait, episode, body, "ep_2026-09-04_001")
    assert plan["confidence"] == 0.9 and wait["confidence"] == 0.4
    assert plan["reactions"] == [{"by": "user", "stance": "agree", "kind": "like", "turn": 0,
                                  "episode": "ep_2026-09-04_001"}]
    assert wait["reactions"][0]["stance"] == "doubt" and wait["reactions"][0]["turn"] == second
    assert entity_extractor._observer_for(plan, "external:helper", [], body) == "external:helper"
    assert entity_extractor._observer_for(wait, "external:helper", [], body) == "external:helper"
    # The reaction rides onto the stored claim, and survives a round trip.
    extracted = [{"episode_id": "ep_2026-09-04_001", "origin": "imessage", "relationships": [
        dict(plan, source="alpha-project", target="monday", label="ships on", observer="external:helper",
             source_episode="ep_2026-09-04_001")]}]
    (claim,) = entity_extractor.entities_to_claims(extracted, None)
    assert claim.observer == "external:helper" and claim.reactions == plan["reactions"]
    assert claims_mod.Claim.from_dict(claim.to_dict()).reactions == plan["reactions"]
    assert "reactions" not in claims_mod.Claim(id="x", text="y").to_dict()
    # A reaction by anyone else is never the person's stance.
    other = {"turn_extras": [{"offset": 0, "reactions": [{"by": "speaker:bob-example", "kind": "like"}]}]}
    assert turn_signals.person_stance(other, body, {"evidence": [{"kind": "assistant", "start": 11, "end": 20}]}) is None


def test_a_tag_alone_grants_no_signal():
    # #499 review: the person's 👍 is on plan A; a claim quoting plan B, tagged with that reaction, rests on nothing.
    body = "user: should we pick plan A or B?\nassistant: plan A is cheaper\nassistant: plan B ships Friday"
    fm = {"turn_extras": [{"offset": body.index("assistant: plan A"), "reactions": [{"by": "user", "kind": "like"}]}]}
    items = turn_signals.signals(fm, body)
    (s1,) = items
    rel = {"evidence_quote": "plan B ships Friday", "signal": s1.label, "confidence": 0.7}
    window, signal = turn_signals.anchor(rel, items, body, (0, len(body)))
    assert window == (0, len(body)) and signal is None
    rel["evidence"] = [evidence.verify(None, "ep_2026-09-04_001", rel.pop("evidence_quote"), text=body).to_dict()]
    entity_extractor._weigh_reaction(rel, dict(fm, signals=items), body, "ep_2026-09-04_001")
    assert rel["confidence"] == 0.7 and "reactions" not in rel
    assert entity_extractor._observer_for(rel, "external:helper", [], body) == "external:helper"


GROUP_BODY = "speaker:bob-example: Carol Example is coming\nuser: great"


def _group_episode(bank, body=GROUP_BODY):
    path = bank / "episodes" / "ep_2026-09-05_001.md"
    markdown_parser.write(path, {"id": "ep_2026-09-05_001", "origin": "imessage", "source": "imessage", "group": True,
                                 "participants": [{"key": B, "marker": "speaker:bob-example", "name": "Bob Example",
                                                   "kind": "person"}]}, body)
    bank_index.invalidate()
    return path


def test_a_members_line_never_promotes_a_waiting_contacts_card(bank):
    from api.services import entity_resolver

    _group_episode(bank)
    card = {"given_name": "Carol", "family_name": "Example"}
    assert entity_resolver._said_in_person_turn(bank, "ep_2026-09-05_001", card) is False
    _group_episode(bank, "speaker:bob-example: hi\nuser: Carol Example is coming")
    assert entity_resolver._said_in_person_turn(bank, "ep_2026-09-05_001", card) is True


def test_a_members_line_never_ties_a_project_conversation():
    import re

    from api.services import project_conversations

    pattern = re.compile(r"\balpha-project\b", re.I)
    text = "speaker:bob-example: alpha-project ships soon\nuser: ok"
    assert project_conversations.person_named(text, pattern, {"group": True}) is False
    assert project_conversations.person_named(text, pattern, {}) is True          # a meeting's speaker still counts


def test_someone_elses_claim_is_never_the_persons_words_on_a_page():
    from api.services import page_relevance, quiet_pages, web_context

    span = claims_mod.Evidence(episode="ep_2026-09-05_001", start=0, end=10, kind="speaker", hash="0" * 12)
    member = claims_mod.Claim(id="c1", text="Carol is coming", observer="external:bob-example", evidence=[span])
    meeting = claims_mod.Claim(id="c2", text="Carol is coming", observer="agent", evidence=[span])
    assert not promotion.claim_cites_person(member) and promotion.claim_cites_person(meeting)
    assert not web_context._cites_the_person(member) and web_context._cites_the_person(meeting)
    assert not page_relevance._cites_person(member) and page_relevance._cites_person(meeting)
    kind_of = lambda e: quiet_pages.IMPORT  # noqa: E731 - every episode an import's
    fm = {"source_episodes": ["ep_2026-09-01_001"]}
    assert quiet_pages.is_quiet(fm, [member], kind_of) is True
    assert quiet_pages.is_quiet(fm, [meeting], kind_of) is False


TWO_MEMBERS = ("user: who is coming?\nspeaker:alice-example: Carol works at alpha-corp\n"
               "speaker:bob-example: yes alpha-corp hired Carol")
MEMBERS_AB = [{"marker": "speaker:alice-example", "name": "Alice Example", "kind": "person"},
              {"marker": "speaker:bob-example", "name": "Bob Example", "kind": "person"}]


def _spans(body, *quotes):
    return [evidence.verify(None, "ep_2026-09-05_001", q, text=body).to_dict() for q in quotes]


def test_a_group_claim_on_several_members_lines_is_the_groups_never_the_persons():
    rel = {"source": "Carol", "target": "alpha-corp", "label": "works at",
           "evidence": _spans(TWO_MEMBERS, "Carol works at alpha-corp", "alpha-corp hired Carol")}
    rel["observer"] = entity_extractor._observer_for(rel, None, MEMBERS_AB, TWO_MEMBERS)
    assert rel["observer"] == entity_extractor.GROUP_OBSERVER == "external:group"
    assert not promotion.person_said(rel)
    # The person's own line among them: it rests on their words too, the default reading.
    mixed = {"evidence": _spans(TWO_MEMBERS, "who is coming?", "Carol works at alpha-corp")}
    assert entity_extractor._observer_for(mixed, None, MEMBERS_AB, TWO_MEMBERS) is None
    # A member Cicada cannot name is never the person either.
    unnamed = {"evidence": _spans("speaker:member: alpha-corp is hiring\nuser: ok", "alpha-corp is hiring")}
    assert entity_extractor._observer_for(unnamed, None, MEMBERS_AB, "speaker:member: alpha-corp is hiring\nuser: ok") \
        == "external:group"


def test_a_group_claim_never_links_a_first_mention_to_a_page():
    from api.services import entity_resolver

    existing = {"alpha-corp": {"id": "alpha-corp", "frontmatter": {"confidence": 0.9}}}
    rel = {"source": "Carol", "target": "alpha-corp", "label": "works at", "observer": "external:group",
           "evidence": _spans(TWO_MEMBERS, "Carol works at alpha-corp", "alpha-corp hired Carol")}
    assert entity_resolver._is_linked_to_existing("Carol", [rel], existing) is False
    assert entity_resolver._is_linked_to_existing("Carol", [dict(rel, observer="agent")], existing) is True


def test_page_repair_never_counts_a_group_claim_as_the_persons_link(bank):
    from api.services import page_quality_repair

    _group_episode(bank, TWO_MEMBERS)
    spans = [claims_mod.Evidence.from_dict(e) for e in _spans(TWO_MEMBERS, "Carol works at alpha-corp")]
    fm = {"name": "Carol", "type": "person", "source_episodes": ["ep_2026-09-05_001"]}
    pages = {"alpha-corp": {"confidence": 0.9}}

    def body(observer):
        claim = claims_mod.Claim(id="c1", text="Carol works at alpha-corp", subject="carol", predicate="works-at",
                                 object="alpha-corp", observer=observer, evidence=spans)
        return claims_mod.write_claims("## Summary\nCarol.\n", [claim])

    assert page_quality_repair._clears_bar(bank, fm, body("external:group"), set(), pages) == (None, True)
    assert page_quality_repair._clears_bar(bank, fm, body("agent"), set(), pages) == ("link", True)


def test_a_meeting_still_counts_every_speaker():
    text = "speaker:alice-example: alpha-hall is lovely\nuser: ok"
    assert promotion.exchanges(text)[0][0] == "alpha-hall is lovely"
    assert promotion.exchanges(text, persons=promotion.person_kinds({"group": True}))[0][0] == ""
