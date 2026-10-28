"""G179 (2026-10-28) — WhatsApp chats posted by the app, staged one episode per sitting through `chat_live`.

Synthetic rows only: placeholder JIDs hashed the way the app hashes them, placeholder names and words. Covers the tick
rail (unticked → 409, live from the tick, history only on ask), the sitting split and its stable key, groups (one
marker per member, the participants record, one assistant at most), quoted replies through ZMETADATA, deletes for
everyone, attachments named never read, contact cards and locations never kept, reactions one per reactor, edits,
the scrub, the demo guard, the routes and the measured cost of one live update."""
from __future__ import annotations

import base64
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (bank_index, chat_live, channel_registry, episode_staging, inbox_tend, markdown_parser,
                          source_overview, turn_extras, whatsapp_source)

SPEC = whatsapp_source.SPEC
CHAT = chat_live.hash_id("15550000002@s.whatsapp.net")         # placeholder JIDs, hashed as the app does
GROUP = chat_live.hash_id("120363000000000000@g.us")
MEMBER_A = chat_live.hash_id("120363000000000000@g.us", "15550000003@s.whatsapp.net")
MEMBER_B = chat_live.hash_id("120363000000000000@g.us", "15550000004@s.whatsapp.net")
APPLE = 978_307_200
T0 = 1_788_000_000          # 2026-08-29, unix — every row is dated after it


def apple(unix: float) -> float:
    return unix - APPLE


def quote_meta(stanza: str) -> str:
    """ZMETADATA carrying a quoted reply: top-level protobuf field 5, length-delimited."""
    raw = stanza.encode("ascii")
    return base64.b64encode(bytes([0x2A, len(raw)]) + raw + b"\x32\x02ab").decode("ascii")


def row(stanza, at, text="", *, me=False, type=0, member=None, metadata=None, media=None):
    return {"stanza": stanza, "date": apple(at), "fromMe": me, "text": text, "type": type, "member": member,
            "metadata": metadata, "media": media}


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    bank_index.invalidate()
    return memory


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def tick(bank, cid=CHAT, *, group=False, at="2026-08-28T00:00:00+00:00", history=False):
    chat_live.update_settings(bank, SPEC, {"id": cid, "name": "Bob Example", "group": group, "ticked": True}, now=at)
    if history:
        chat_live.update_settings(bank, SPEC, {"id": cid, "history": True}, now=at)


def ingest(bank, rows, *, cid=CHAT, group=False, members=(), name="Bob Example", reactions=()):
    payload = {"conversation": {"id": cid, "name": name, "group": group, "members": list(members)},
               "messages": [{k if k != "fromMe" else "from_me": v for k, v in r.items()} for r in rows],
               "reactions": list(reactions)}
    out = whatsapp_source.ingest(bank, payload)
    bank_index.invalidate()
    return out


def episodes(bank):
    index, _ = episode_staging.scan(bank / "episodes")
    return {sid: markdown_parser.parse(e.path) for sid, e in sorted(index.items())
            if not e.fm.get("source_deleted_at")}


def test_an_unticked_chat_is_refused_and_nothing_is_written(bank):
    with pytest.raises(chat_live.NotSelected):
        ingest(bank, [row("AAA1", T0, "hello")])
    assert list((bank / "episodes").iterdir()) == []


def test_a_tick_is_live_from_then_and_history_only_on_the_persons_ask(bank):
    tick(bank, at="2026-09-01T00:00:00+00:00")
    out = ingest(bank, [row("OLD1", T0, "before the tick"), row("NEW1", T0 + 400_000, "after the tick")])
    assert (out["before_start"], out["kept"]) == (1, 1)
    bodies = [p.body for p in episodes(bank).values()]
    assert bodies == ["speaker:bob-example: after the tick"]
    chat_live.update_settings(bank, SPEC, {"id": CHAT, "history": True})
    out = ingest(bank, [row("OLD1", T0, "before the tick")])
    assert out["before_start"] == 0 and len(episodes(bank)) == 2
    log = chat_live.load_settings(bank, SPEC)["conversations"][CHAT]["history"]
    assert [h["kind"] for h in log] == ["ticked", "history"]


def test_history_needs_a_tick_first(bank):
    with pytest.raises(chat_live.NotSelected):
        chat_live.update_settings(bank, SPEC, {"id": CHAT, "history": True})


def test_one_episode_per_sitting_and_the_key_stays_as_it_grows(bank):
    tick(bank)
    ingest(bank, [row("A1", T0, "Are we still on for the alpha-project review?", me=True),
                  row("A2", T0 + 60, "Yes, Thursday works.")])
    first = set(episodes(bank))
    assert len(first) == 1
    ingest(bank, [row("A3", T0 + 120, "Great, I'll book the room.", me=True),
                  row("A4", T0 + 4 * 3600, "Later: did you send the notes?")])
    eps = episodes(bank)
    assert first <= set(eps) and len(eps) == 2
    body = eps[sorted(first)[0]].body
    assert body.splitlines() == ["user: Are we still on for the alpha-project review?",
                                 "speaker:bob-example: Yes, Thursday works.", "user: Great, I'll book the room."]
    fm = eps[sorted(first)[0]].frontmatter
    assert fm["origin"] == "whatsapp" and fm["correspondent"]["name"] == "Bob Example"
    assert fm["message_count"] == 3 and fm["from_person"] == 2


def test_a_group_gives_each_member_their_own_marker_and_records_who_they_are(bank):
    tick(bank, GROUP, group=True)
    members = [{"key": MEMBER_A, "name": "Carol Example"}, {"key": MEMBER_B, "name": "Dave Example"}]
    ingest(bank, [row("G1", T0, "Who's bringing the beta-tool demo?", member=MEMBER_A),
                  row("G2", T0 + 30, "I will.", me=True),
                  row("G3", T0 + 60, "I think Carol believes it's ready.", member=MEMBER_B,
                      metadata=quote_meta("G1"))],
           cid=GROUP, group=True, members=members, name="Weekend crew")
    (ep,) = episodes(bank).values()
    assert ep.body.splitlines() == ["speaker:carol-example: Who's bringing the beta-tool demo?", "user: I will.",
                                    "speaker:dave-example: I think Carol believes it's ready."]
    fm = ep.frontmatter
    assert fm["group"] is True and "correspondent" not in fm
    assert [(p["marker"], p.get("name"), p["kind"]) for p in fm["participants"]] == [
        ("speaker:carol-example", "Carol Example", "person"), ("speaker:dave-example", "Dave Example", "person")]
    assert all("@" not in str(p) and "1555" not in str(p) for p in fm["participants"])
    extras = turn_extras.by_offset(fm)
    reply = [e for e in extras.values() if "reply_to" in e]
    assert reply == [{"reply_to": 0}]          # Dave's line answers Carol's, the first turn
    assert fm["title"].startswith("WhatsApp · Weekend crew · ")


def test_a_member_keeps_their_marker_when_a_later_pass_names_nobody(bank):
    tick(bank, GROUP, group=True)
    ingest(bank, [row("G1", T0, "First.", member=MEMBER_A)], cid=GROUP, group=True,
           members=[{"key": MEMBER_A, "name": "Carol Example"}])
    ingest(bank, [row("G2", T0 + 60, "Second.", member=MEMBER_A)], cid=GROUP, group=True, members=[])
    (ep,) = episodes(bank).values()
    assert ep.body.splitlines() == ["speaker:carol-example: First.", "speaker:carol-example: Second."]


def test_a_delete_for_everyone_keeps_its_place_never_its_words(bank):
    tick(bank)
    ingest(bank, [row("D1", T0, "keep this", me=True), row("D2", T0 + 10, "a secret plan")])
    ingest(bank, [row("D2", T0 + 10, "", type=whatsapp_source.DELETED_TYPE)])
    (ep,) = episodes(bank).values()
    assert ep.body == "user: keep this"
    assert "secret" not in next((bank / "episodes").glob("*.md")).read_text(encoding="utf-8")
    gone = turn_extras.unsent(ep.frontmatter)
    assert len(gone) == 1 and gone[0]["speaker"].startswith("speaker:")


def test_attachments_are_named_never_read_and_cards_and_places_never_kept(bank, tmp_path):
    tick(bank)
    ingest(bank, [row("M1", T0, "", type=1, media={"file": "/Users/x/Media/IMG_0001.jpg", "size": 1234}),
                  row("M2", T0 + 5, "Bob Example +15550000009", type=whatsapp_source.CONTACT_TYPE),
                  row("M3", T0 + 9, "40.4168,-3.7038 Somewhere Street", type=whatsapp_source.LOCATION_TYPE),
                  row("M4", T0 + 12, "joined", type=whatsapp_source.SYSTEM_TYPE)])
    (ep,) = episodes(bank).values()
    assert ep.body.splitlines() == ["speaker:bob-example: [image: IMG_0001.jpg]",
                                    "speaker:bob-example: [contact card]", "speaker:bob-example: [location]"]
    files = [e["attachments"] for e in turn_extras.by_offset(ep.frontmatter).values() if "attachments" in e]
    assert files == [[{"kind": "image", "name": "IMG_0001.jpg", "size": 1234}]]
    text = next((bank / "episodes").glob("*.md")).read_text(encoding="utf-8")
    assert "/Users/" not in text and "40.4168" not in text and "15550000009" not in text


def test_reactions_are_one_per_reactor_and_an_edit_replaces_words_in_place(bank):
    tick(bank, GROUP, group=True)
    members = [{"key": MEMBER_A, "name": "Carol Example"}, {"key": MEMBER_B, "name": "Dave Example"}]
    ingest(bank, [row("R1", T0, "Ship on Friday?", me=True)], cid=GROUP, group=True, members=members,
           reactions=[{"target": "R1", "date": apple(T0 + 5), "member": MEMBER_A, "emoji": "👍"},
                      {"target": "R1", "date": apple(T0 + 6), "member": MEMBER_B, "emoji": "😂"},
                      {"target": "R1", "date": apple(T0 + 7), "member": MEMBER_A, "emoji": "❤️"}])
    (ep,) = episodes(bank).values()
    (extras,) = turn_extras.by_offset(ep.frontmatter).values()
    assert sorted((r["by"], r["kind"]) for r in extras["reactions"]) == [
        ("speaker:carol-example", "love"), ("speaker:dave-example", "laugh")]
    ingest(bank, [{**row("R1", T0, "Ship on Monday?", me=True), "edited": True}], cid=GROUP, group=True)
    (ep,) = episodes(bank).values()
    assert ep.body == "user: Ship on Monday?"
    (extras,) = turn_extras.by_offset(ep.frontmatter).values()
    assert extras["edited"] is True and len(extras["reactions"]) == 2


def test_a_secret_in_a_message_is_scrubbed(bank):
    tick(bank)
    ingest(bank, [row("S1", T0, "my key is sk-ant-abcdefghijklmnopqrstuvwxyz0123456789", me=True)])
    text = next((bank / "episodes").glob("*.md")).read_text(encoding="utf-8")
    assert "sk-ant-abcdefghijklmnop" not in text


def test_a_person_mark_names_the_correspondent_for_stage_two(bank):
    tick(bank)
    chat_live.update_settings(bank, SPEC, {"id": CHAT, "actor": {"kind": "person"}})
    ingest(bank, [row("P1", T0, "Hi")])
    (ep,) = episodes(bank).values()
    assert ep.frontmatter["correspondent"]["kind"] == "person"
    assert ep.frontmatter["correspondent"]["decided_by"] == "person"


def test_the_inbox_reads_whatsapp_as_a_texted_conversation():
    assert inbox_tend._from_messages({"origin": "whatsapp"})
    assert not inbox_tend._from_messages({"origin": "claude-code"})


def test_the_sources_page_lists_whatsapp_once_ticked(bank):
    ids = [r["id"] for r in channel_registry.build_channels(bank, telegram_enabled=False)]
    assert "whatsapp" not in ids
    tick(bank)
    rows = {r["id"]: r for r in channel_registry.build_channels(bank, telegram_enabled=False)}
    assert rows["whatsapp"]["label"] == "WhatsApp"   # connected after a first sync
    assert "whatsapp" in {s.id for s in source_overview.CATALOG}


def test_routes_tick_sync_and_refuse(client, bank):
    r = client.post("/sources/whatsapp/sync", json={"conversation": {"id": CHAT}, "messages": [
        {"stanza": "X1", "date": apple(T0), "text": "hi"}]})
    assert r.status_code == 409
    r = client.put("/sources/whatsapp/settings", json={"conversation": {"id": CHAT, "name": "Bob Example",
                                                                         "ticked": True}})
    assert r.status_code == 200 and r.json()["conversations"][0]["ticked"] is True
    client.put("/sources/whatsapp/settings", json={"conversation": {"id": CHAT, "history": True}})
    r = client.post("/sources/whatsapp/sync", json={"conversation": {"id": CHAT, "name": "Bob Example"}, "messages": [
        {"stanza": "X1", "date": apple(T0), "text": "hi", "fromMe": True}]})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    r = client.post("/sources/whatsapp/conversations", json={"conversations": [{"id": CHAT}, {"id": GROUP}]})
    assert [(c["id"], c["ticked"], c["history"]) for c in r.json()["conversations"]] == [
        (CHAT, True, True), (GROUP, False, False)]
    w = client.get("/sources/whatsapp/waiting").json()
    assert w["messages"] == 1


def test_quoted_stanza_reads_field_five_and_nothing_else():
    assert whatsapp_source.quoted_stanza(quote_meta("3EB0ABCDEF")) == "3EB0ABCDEF"
    assert whatsapp_source.quoted_stanza(base64.b64encode(b"\x0a\x03abc").decode()) is None
    assert whatsapp_source.quoted_stanza("not base64!") is None
    assert whatsapp_source.quoted_stanza(base64.b64encode(b"\x2a\xff").decode()) is None


def test_live_update_cost_p95(bank):
    """File change → episode, backend half: one new message into a chat that already holds 40 sittings."""
    tick(bank, history=True)
    rows = [row(f"H{i}", T0 + i * 4 * 3600, f"message {i}", me=i % 2 == 0) for i in range(40)]
    ingest(bank, rows)
    took = []
    for i in range(30):
        started = time.perf_counter()
        ingest(bank, [row(f"L{i}", T0 + 40 * 4 * 3600 + i * 60, f"live {i}")])
        took.append(time.perf_counter() - started)
    took.sort()
    p95 = took[int(len(took) * 0.95) - 1]
    print(f"whatsapp live update p95 {p95 * 1000:.1f} ms over {len(took)} (bank of {len(episodes(bank))} sittings)")
    assert p95 < 1.0
