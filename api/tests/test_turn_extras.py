"""Conversations keep what made them conversations (owner 2026-10-20): reactions, replies, attachments, edits, unsends.

Synthetic data only: a synthetic ``chat.db`` (``_imessage_fixtures``) with each shape Messages writes — a classic
tapback and its removal, an emoji tapback, a placed sticker, an inline reply inside the sitting and across sittings,
a sticker attachment, an edit, an unsend (``date_edited`` and ``date_retracted``) — and ChatGPT / Claude export
fixtures with uploads, a generated image, a code run and a model per reply. What must hold: extras sit beside the
words, never in them (every evidence span stays ``current``, the body hash never moves, a reaction never re-queues
Sleep), a reaction is never a turn, an unsent message's words are never kept, every extra is scrubbed, and the
Reader's ``/episodes/{id}/text`` carries them by turn index."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from _imessage_fixtures import ChatDB, payload, read_rows, utc
from api.models.schemas import MessagesSyncRequest
from api.routers import conversations as conv
from api.services import (bank_index, episode_staging, evidence, markdown_parser, messages_source, provenance,
                          turn_extras)

AGENT = "+15550000001"     # placeholder handle
CADENCE = {"from_me": 10, "from_them": 40}


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    bank_index.invalidate()
    return memory


@pytest.fixture
def db(tmp_path):
    chat = ChatDB(tmp_path / "chat.db")
    chat.agent = chat.chat(AGENT)
    yield chat
    chat.close()


def _tick(bank, db):
    messages_source.update_settings(bank, conversation={"id": payload(db.chat_guid(db.agent), [])["conversation"]["id"],
                                                        "name": "Instinct", "ticked": True})


def _sync(bank, db, *, after=0, changed=0):
    rows = read_rows(db.path, db.agent, after_rowid=after, changed_after=changed)
    body = payload(db.chat_guid(db.agent), rows, **CADENCE)
    out = messages_source.ingest(bank, MessagesSyncRequest.model_validate(body).model_dump(by_alias=False),
                                 bank=bank.name)
    bank_index.invalidate()
    return out, (max(r["rowid"] for r in rows) if rows else after)


def _docs(bank):
    bank_index.invalidate()
    out = []
    for path in sorted((bank / "episodes").glob("ep_*.md")):
        parsed = markdown_parser.parse(path)
        if not parsed.frontmatter.get("source_deleted_at"):
            out.append(SimpleNamespace(path=path, frontmatter=parsed.frontmatter, body=parsed.body))
    return out


def _text(bank, doc):
    return provenance.episode_document(bank, doc.frontmatter["id"])


# --- Messages ------------------------------------------------------------------------------------------------------


def _seed(db):
    """One sitting: the person asks, the agent answers twice, then the person replies inline to the first answer."""
    a = db.message(db.agent, utc(2026, 9, 3, 10, 0), from_me=True, text="Can you plan the alpha-project launch?")
    b = db.message(db.agent, utc(2026, 9, 3, 10, 1), from_me=False, text="Sure, here is a draft.",
                   attachments=[{"name": "draft.pdf", "mime": "application/pdf", "bytes": 2048}])
    c = db.message(db.agent, utc(2026, 9, 3, 10, 2), from_me=False, text="Step one: list the open tasks.")
    d = db.message(db.agent, utc(2026, 9, 3, 10, 3), from_me=True, text="Love this", reply_to=db.guid(b))
    return a, b, c, d


def test_a_tapback_lands_on_its_message_and_is_never_a_turn(bank, db):
    _tick(bank, db)
    a, b, c, d = _seed(db)
    db.message(db.agent, utc(2026, 9, 3, 10, 4), from_me=True, associated_type=2000,
               associated_guid=f"p:0/{db.guid(c)}", text="Loved “Step one: list the open tasks.”")
    db.message(db.agent, utc(2026, 9, 3, 10, 5), from_me=False, associated_type=2006, emoji="🎉",
               associated_guid=f"p:0/{db.guid(a)}", text="Reacted 🎉 to “Can you plan…”")
    out, _ = _sync(bank, db)
    assert (out["reactions"], out["reactions_kept"], out["replies"]) == (2, 2, 1)
    (doc,) = _docs(bank)
    lines = doc.body.split("\n")
    assert len(lines) == 4 and not any("Loved" in line or "Reacted" in line for line in lines)
    extras = turn_extras.by_offset(doc.frontmatter)
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)
    assert extras[starts[2]]["reactions"] == [{"by": "user", "kind": "love", "emoji": "❤️"}]
    assert extras[starts[0]]["reactions"] == [{"by": "assistant", "kind": "emoji", "emoji": "🎉"}]
    assert extras[starts[3]]["reply_to"] == starts[1]
    assert extras[starts[1]]["attachments"] == [{"kind": "file", "name": "draft.pdf", "size": 2048,
                                                  "mime": "application/pdf"}]
    assert list(doc.frontmatter)[-1] == "turns"   # R-PB4: the sidecar stays last


def test_a_later_reaction_changes_only_frontmatter_never_the_words_or_the_queue(bank, db):
    _tick(bank, db)
    _, _, c, _ = _seed(db)
    _, cursor = _sync(bank, db)
    (doc,) = _docs(bank)
    fm = dict(doc.frontmatter, processed=True, processed_by="sleep")
    markdown_parser.write(Path(doc.path), fm, doc.body)
    bank_index.invalidate()
    text = evidence.source_text(bank, fm["id"])
    start = text.index("list the open tasks")
    end = start + len("list the open tasks")
    span_hash = evidence.body_hash(text)

    db.message(db.agent, utc(2026, 9, 4, 9, 0), from_me=True, associated_type=2001,
               associated_guid=f"p:0/{db.guid(c)}", text="Liked “Step one…”")
    out, cursor = _sync(bank, db, after=cursor)
    assert (out["created"], out["updated"], out["reactions_kept"]) == (0, 0, 1)
    (after,) = _docs(bank)
    assert after.body == doc.body and after.frontmatter["content_hash"] == doc.frontmatter["content_hash"]
    assert after.frontmatter["processed"] is True, "a reaction never re-queues a conversation for Sleep"
    assert evidence.source_text(bank, fm["id"])[start:end] == "list the open tasks"
    assert evidence.span_status(evidence.source_text(bank, fm["id"]), end=end, hash=span_hash) == evidence.SPAN_CURRENT
    doc_text = _text(bank, after)
    liked = [t for t in doc_text.turns if t.extras and t.extras.reactions]
    assert [(t.index, t.extras.reactions[0].kind) for t in liked] == [(3, "like")]

    # Taking it back removes it, again frontmatter only.
    db.message(db.agent, utc(2026, 9, 4, 9, 1), from_me=True, associated_type=3001,
               associated_guid=f"p:0/{db.guid(c)}", text="Removed a like from “Step one…”")
    _sync(bank, db, after=cursor)
    (last,) = _docs(bank)
    assert not any(e.get("reactions") for e in turn_extras.by_offset(last.frontmatter).values())
    assert last.body == doc.body and last.frontmatter["processed"] is True


def test_a_new_tapback_replaces_the_reactors_old_one_and_an_orphan_is_dropped(bank, db):
    _tick(bank, db)
    _, _, c, _ = _seed(db)
    db.message(db.agent, utc(2026, 9, 3, 10, 4), from_me=True, associated_type=2000,
               associated_guid=f"p:0/{db.guid(c)}", text="Loved …")
    db.message(db.agent, utc(2026, 9, 3, 10, 5), from_me=True, associated_type=2003,
               associated_guid=f"bp:{db.guid(c)}", text="Laughed at …")
    db.message(db.agent, utc(2026, 9, 3, 10, 6), from_me=False, associated_type=2000,
               associated_guid="p:0/SYNTH-NOT-STORED", text="Loved …")
    out, _ = _sync(bank, db)
    assert (out["reactions_kept"], out["reactions_orphaned"]) == (2, 1)
    doc = _text(bank, _docs(bank)[0])
    assert [(r.by, r.kind) for r in doc.turns[2].extras.reactions] == [("user", "laugh")]


def test_a_reply_to_another_sitting_points_elsewhere_and_a_sticker_is_a_sticker(bank, db):
    _tick(bank, db)
    a, *_ = _seed(db)
    db.message(db.agent, utc(2026, 9, 4, 12, 0), from_me=False, text="About your first question:",
               reply_to=db.guid(a))
    db.message(db.agent, utc(2026, 9, 4, 12, 1), from_me=True,
               attachments=[{"name": "sticker.heic", "mime": "image/heic", "uti": "public.heic", "sticker": 1}])
    _sync(bank, db)
    first, second = _docs(bank)
    doc = _text(bank, second)
    assert doc.turns[0].extras.reply_elsewhere and doc.turns[0].extras.reply_to is None
    assert doc.turns[1].extras.attachments[0].kind == "sticker"
    assert second.body.split("\n")[1] == "user: [image: sticker.heic]"   # the words are as they always were
    assert all("Library/Messages" not in str(d.frontmatter) for d in (first, second))


def test_an_unsent_message_stays_as_where_it_was_never_its_words(bank, db):
    _tick(bank, db)
    a, b, c, d = _seed(db)
    _, cursor = _sync(bank, db)
    (before,) = _docs(bank)
    db.unsend(c, utc(2026, 9, 3, 10, 30))
    out, _ = _sync(bank, db, after=cursor)
    assert out["unsent"] == 1
    (doc,) = _docs(bank)
    raw = Path(doc.path).read_text(encoding="utf-8")
    assert "Step one" not in raw, "an unsent message's words are never kept"
    assert doc.frontmatter["message_count"] == 3
    gone = turn_extras.unsent(doc.frontmatter)
    assert [(g["speaker"], g["ts"]) for g in gone] == [("assistant", "2026-09-03T10:02:00+00:00")]
    text = _text(bank, doc)
    assert [(u.before, u.speaker) for u in text.unsent] == [(3, "assistant")]   # turn indices count from 1
    # The reply to an earlier message still finds its target; the placeholder survives the next pass's rebuild.
    assert text.turns[2].extras.reply_to == text.turns[1].index
    db.message(db.agent, utc(2026, 9, 3, 10, 40), from_me=True, text="Thanks.")
    _sync(bank, db, after=cursor)
    (again,) = _docs(bank)
    assert [u.before for u in _text(bank, again).unsent] == [3]
    assert again.frontmatter["id"] == before.frontmatter["id"]


def test_a_retracted_message_is_unsent_too(bank, db):
    _tick(bank, db)
    _, _, c, _ = _seed(db)
    db.retract(c, utc(2026, 9, 3, 10, 30))
    _sync(bank, db)
    (doc,) = _docs(bank)
    assert "Step one" not in Path(doc.path).read_text(encoding="utf-8")
    assert len(_text(bank, doc).unsent) == 1


def test_an_edit_is_marked_and_the_mark_survives_later_passes(bank, db):
    _tick(bank, db)
    _, _, c, _ = _seed(db)
    _, cursor = _sync(bank, db)
    db.edit(c, "Step one: list the open tasks and owners.", utc(2026, 9, 3, 10, 9))
    _sync(bank, db, after=cursor)
    assert _text(bank, _docs(bank)[0]).turns[2].extras.edited
    db.message(db.agent, utc(2026, 9, 3, 10, 50), from_me=True, text="Good.")
    _sync(bank, db, after=cursor)
    turns = _text(bank, _docs(bank)[0]).turns
    assert turns[2].extras.edited and not (turns[4].extras and turns[4].extras.edited)


def test_marking_the_chat_re_renders_who_reacted(bank, db):
    _tick(bank, db)
    _, _, c, _ = _seed(db)
    db.message(db.agent, utc(2026, 9, 3, 10, 4), from_me=False, associated_type=2000,
               associated_guid=f"p:0/{db.guid(c)}", text="Loved …")
    _sync(bank, db)
    cid = payload(db.chat_guid(db.agent), [])["conversation"]["id"]
    messages_source.update_settings(bank, conversation={"id": cid, "actor": {"kind": "person", "label": "Sam"}})
    messages_source.reattribute(bank, cid, bank=bank.name)
    bank_index.invalidate()
    doc = _text(bank, _docs(bank)[0])
    assert doc.turns[2].extras.reactions[0].by == "speaker:sam"


def test_extras_are_scrubbed_like_the_words(bank, db):
    _tick(bank, db)
    secret = "sk-ant-api03-" + "A" * 40
    db.message(db.agent, utc(2026, 9, 3, 10, 0), from_me=True, text="see file",
               attachments=[{"name": f"{secret}.txt", "mime": "text/plain"}])
    _sync(bank, db)
    raw = Path(_docs(bank)[0].path).read_text(encoding="utf-8")
    assert secret not in raw


# --- The stager (source-neutral) ------------------------------------------------------------------------------------


def test_extras_never_shift_an_offset_the_evidence_layer_indexes(bank):
    turns = [episode_staging.Turn("hello there", "user", "2026-09-03T10:00:00+00:00"),
             episode_staging.Turn("hi", "assistant", "2026-09-03T10:01:00+00:00")]
    plain = episode_staging.EpisodeDraft(title="t", source_id="x:1", source="test", turns=turns)
    body, stamps, _ = episode_staging.render(plain)
    rich_turns = [episode_staging.Turn(t.text, t.speaker, t.ts, extras={"reactions": [
        {"by": "assistant", "kind": "like", "emoji": "👍"}], "reply_to": 1}) for t in turns]
    rich = episode_staging.EpisodeDraft(title="t", source_id="x:1", source="test", turns=rich_turns,
                                        unsent=[{"before": 1, "speaker": "assistant", "ts": "2026-09-03T10:00:30Z"}])
    rich_body, rich_stamps, _ = episode_staging.render(rich)
    assert (rich_body, rich_stamps) == (body, stamps)
    assert episode_staging.content_hash(rich_body) == episode_staging.content_hash(body)
    extras = episode_staging.render_extras(rich)
    assert [e["offset"] for e in extras["turn_extras"]] == [t.start for t in evidence.turns(body)]
    assert extras["turn_extras"][0]["reply_to"] == evidence.turns(body)[1].start
    assert extras["unsent_turns"] == [{"at": evidence.turns(body)[1].start, "speaker": "assistant",
                                       "ts": "2026-09-03T10:00:30Z"}]
    assert "reply_to" not in extras["turn_extras"][1], "a turn never replies to itself"


def test_a_malformed_extra_is_dropped_never_raised():
    assert turn_extras.clean({"reactions": [{"by": "nobody", "kind": "love"}, {"by": "user", "kind": "boo"}],
                              "reply_to": 99, "attachments": "nope", "edited": "yes", "code_runs": -1},
                             index=0, count=2) == {}
    assert turn_extras.by_offset({"turn_extras": ["x", {"offset": "a"}, {"offset": 3, "edited": True}]}) == {
        3: {"edited": True}}


# --- Exports -------------------------------------------------------------------------------------------------------


def _chatgpt_export():
    def node(nid, role, t, parts=None, *, content_type="text", meta=None, name=None, text=None):
        content = {"content_type": content_type}
        if parts is not None:
            content["parts"] = parts
        if text is not None:
            content["text"] = text
        author = {"role": role, **({"name": name} if name else {})}
        return nid, {"id": nid, "message": {"id": nid, "author": author, "create_time": t, "content": content,
                                            "metadata": meta or {}}}
    mapping = dict([
        node("u1", "user", 1_790_000_000, ["Chart these numbers", {"content_type": "image_asset_pointer"}],
             content_type="multimodal_text",
             meta={"attachments": [{"name": "numbers.csv", "size": 512, "mime_type": "text/csv"}]}),
        node("t1", "tool", 1_790_000_010, content_type="execution_output", text="[chart]", name="python"),
        node("t2", "tool", 1_790_000_011, [{"content_type": "image_asset_pointer"}], content_type="multimodal_text",
             name="dalle.text2im"),
        node("a1", "assistant", 1_790_000_020, ["Here is the chart."], meta={"model_slug": "model-alpha"}),
    ])
    return [{"title": "Charting", "create_time": 1_790_000_000, "update_time": 1_790_000_020,
             "conversation_id": "conv-synth-1", "mapping": mapping}]


def test_chatgpt_export_keeps_uploads_generated_images_code_runs_and_the_model(bank):
    (ep,) = conv.parse_chatgpt_json(_chatgpt_export())
    assert [m["role"] for m in ep["messages"]] == ["user", "assistant"], "a tool result is never a turn"
    conv._stage_episodes([ep], bank / "episodes")
    (doc,) = _docs(bank)
    assert doc.body == "user: Chart these numbers\nassistant: Here is the chart."
    text = _text(bank, doc)
    user, reply = text.turns
    assert [(a.kind, a.name, a.size) for a in user.extras.attachments] == [("file", "numbers.csv", 512)]
    assert reply.extras.code_runs == 1 and reply.extras.attachments[0].generated
    assert reply.model == "model-alpha"


def test_claude_export_keeps_attached_files_beside_the_words(bank):
    data = [{"uuid": "conv-synth-2", "name": "Files", "created_at": "2026-09-03T10:00:00Z",
             "updated_at": "2026-09-03T10:05:00Z", "chat_messages": [
                 {"sender": "human", "text": "Read this", "created_at": "2026-09-03T10:00:00Z",
                  "attachments": [{"file_name": "notes.txt", "file_size": 300, "file_type": "text/plain",
                                   "extracted_content": "line one"}],
                  "files": [{"file_name": "photo.png"}]},
                 {"sender": "assistant", "text": "Done.", "created_at": "2026-09-03T10:01:00Z"}]}]
    (ep,) = conv.parse_anthropic_conversations(data)
    conv._stage_episodes([ep], bank / "episodes")
    text = _text(bank, _docs(bank)[0])
    assert [(a.kind, a.name) for a in text.turns[0].extras.attachments] == [("file", "notes.txt"),
                                                                            ("image", "photo.png")]


def test_re_importing_an_older_export_adds_extras_without_requeueing(bank):
    (ep,) = conv.parse_chatgpt_json(_chatgpt_export())
    bare = {**ep, "messages": [{k: v for k, v in m.items() if k != "extras"} for m in ep["messages"]]}
    conv._stage_episodes([bare], bank / "episodes")
    (doc,) = _docs(bank)
    markdown_parser.write(Path(doc.path), dict(doc.frontmatter, processed=True, processed_by="sleep"), doc.body)
    bank_index.invalidate()
    assert conv._stage_episodes([ep], bank / "episodes") == (0, 0, 1)
    (again,) = _docs(bank)
    assert again.body == doc.body and again.frontmatter["processed"] is True
    assert turn_extras.by_offset(again.frontmatter)
