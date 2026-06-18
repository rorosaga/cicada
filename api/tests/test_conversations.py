"""Tests for the G20 incremental / delta re-import dedup logic.

These exercise the REAL parsers + ``_stage_episodes`` against a ``tmp_path``
episodes dir. The key behavioural contract:

- brand-new conversation (source_id unseen)            -> CREATE a new episode
- unchanged thread (same source_id, same content)      -> SKIP
- grown/edited thread (same source_id, content changed) -> UPDATE in place
  (same episode id + filename, body rewritten, content_hash + source_updated_at
  refreshed, processed flipped back to False so the next Sleep cycle re-runs it)
- a format with NO stable source id still dedups by content hash (never UPDATE).
"""

from __future__ import annotations

from api.routers import conversations as conv
from api.services import markdown_parser


def _claude_export(uuid: str, updated_at: str, messages: list[tuple[str, str]]):
    """Build a one-conversation Anthropic export with the given messages.

    ``messages`` is a list of (sender, text) where sender is "human"/"assistant".
    """
    chat_messages = []
    for i, (sender, text) in enumerate(messages):
        chat_messages.append({
            "uuid": f"{uuid}-m{i}",
            "sender": sender,
            "text": text,
            "content": [],
            "created_at": f"2026-02-24T12:39:{i:02d}.000000Z",
        })
    return [{
        "uuid": uuid,
        "name": "Thesis planning",
        "created_at": "2026-02-24T12:39:00.000000Z",
        "updated_at": updated_at,
        "chat_messages": chat_messages,
    }]


# --- Parser carries source identity -----------------------------------------


def test_anthropic_parser_carries_source_identity():
    data = _claude_export(
        "uuid-abc",
        "2026-02-24T13:00:00.000000Z",
        [("human", "What is the deadline?"), ("assistant", "June.")],
    )
    eps = conv.parse_anthropic_conversations(data)
    assert len(eps) == 1
    assert eps[0]["source_id"] == "uuid-abc"
    assert eps[0]["source_updated_at"] == "2026-02-24T13:00:00.000000Z"


def test_chatgpt_parser_carries_source_identity():
    data = [{
        "conversation_id": "conv-xyz",
        "title": "Chat",
        "create_time": 1_700_000_000,
        "update_time": 1_700_000_500,
        "mapping": {
            "n1": {"message": {
                "author": {"role": "user"},
                "content": {"parts": ["hello"]},
                "create_time": 1_700_000_000,
            }},
        },
    }]
    eps = conv.parse_chatgpt_json(data)
    assert len(eps) == 1
    assert eps[0]["source_id"] == "conv-xyz"
    # ISO string with trailing Z, same idiom as create_time.
    assert eps[0]["source_updated_at"].endswith("Z")


def test_noid_format_has_no_source_id():
    # parse_anthropic_memories has no stable per-thread id.
    data = [{"conversations_memory": "User likes concise summaries."}]
    eps = conv.parse_anthropic_memories(data)
    assert len(eps) == 1
    assert eps[0].get("source_id") is None
    assert eps[0].get("source_updated_at") is None


# --- (a) first import: created + frontmatter carries identity ---------------


def test_first_import_creates_with_source_identity(tmp_path):
    ep_dir = tmp_path / "episodes"
    data = _claude_export(
        "uuid-1",
        "2026-02-24T13:00:00.000000Z",
        [("human", "Q1"), ("assistant", "A1")],
    )
    eps = conv.parse_anthropic_conversations(data)

    created, updated, skipped = conv._stage_episodes(eps, ep_dir)
    assert (created, updated, skipped) == (1, 0, 0)

    files = list(ep_dir.glob("*.md"))
    assert len(files) == 1
    fm = markdown_parser.parse(files[0]).frontmatter
    assert fm["source_id"] == "uuid-1"
    assert fm["source_updated_at"] == "2026-02-24T13:00:00.000000Z"
    assert fm["processed"] is False


# --- (b) identical re-import: skip, no duplicate ----------------------------


def test_reimport_identical_skips(tmp_path):
    ep_dir = tmp_path / "episodes"
    data = _claude_export(
        "uuid-1",
        "2026-02-24T13:00:00.000000Z",
        [("human", "Q1"), ("assistant", "A1")],
    )
    eps = conv.parse_anthropic_conversations(data)
    conv._stage_episodes(eps, ep_dir)

    eps2 = conv.parse_anthropic_conversations(data)
    created, updated, skipped = conv._stage_episodes(eps2, ep_dir)
    assert (created, updated, skipped) == (0, 0, 1)
    assert len(list(ep_dir.glob("*.md"))) == 1


# --- (c) grown thread: update in place, same id/filename, requeued ----------


def test_reimport_grown_updates_in_place(tmp_path):
    ep_dir = tmp_path / "episodes"
    first = _claude_export(
        "uuid-1",
        "2026-02-24T13:00:00.000000Z",
        [("human", "Q1"), ("assistant", "A1")],
    )
    conv._stage_episodes(conv.parse_anthropic_conversations(first), ep_dir)

    orig_file = next(ep_dir.glob("*.md"))
    orig_stem = orig_file.stem

    # Mark processed=True to prove the update flips it back to False.
    fm = markdown_parser.parse(orig_file).frontmatter
    fm["processed"] = True
    markdown_parser.write(orig_file, fm, markdown_parser.parse(orig_file).body)

    grown = _claude_export(
        "uuid-1",
        "2026-02-25T09:00:00.000000Z",
        [("human", "Q1"), ("assistant", "A1"), ("human", "Q2 follow-up")],
    )
    created, updated, skipped = conv._stage_episodes(
        conv.parse_anthropic_conversations(grown), ep_dir
    )
    assert (created, updated, skipped) == (0, 1, 0)

    files = list(ep_dir.glob("*.md"))
    assert len(files) == 1
    assert files[0].stem == orig_stem  # id + filename unchanged

    parsed = markdown_parser.parse(files[0])
    assert parsed.frontmatter["processed"] is False
    assert parsed.frontmatter["source_updated_at"] == "2026-02-25T09:00:00.000000Z"
    assert "Q2 follow-up" in parsed.body


# --- (d) a different new conversation alongside an existing one -------------


def test_import_new_conversation_alongside_existing(tmp_path):
    ep_dir = tmp_path / "episodes"
    first = _claude_export(
        "uuid-1",
        "2026-02-24T13:00:00.000000Z",
        [("human", "Q1"), ("assistant", "A1")],
    )
    conv._stage_episodes(conv.parse_anthropic_conversations(first), ep_dir)

    second = _claude_export(
        "uuid-2",
        "2026-03-01T10:00:00.000000Z",
        [("human", "Other"), ("assistant", "Reply")],
    )
    created, updated, skipped = conv._stage_episodes(
        conv.parse_anthropic_conversations(second), ep_dir
    )
    assert created == 1
    assert len(list(ep_dir.glob("*.md"))) == 2


# --- (e) no-source_id format still dedups by content hash -------------------


def test_noid_format_dedups_by_hash(tmp_path):
    ep_dir = tmp_path / "episodes"
    data = [{"conversations_memory": "User prefers dark mode and concise replies."}]
    eps = conv.parse_anthropic_memories(data)
    created, updated, skipped = conv._stage_episodes(eps, ep_dir)
    assert created == 1
    assert updated == 0

    eps2 = conv.parse_anthropic_memories(data)
    created2, updated2, skipped2 = conv._stage_episodes(eps2, ep_dir)
    assert created2 == 0
    assert updated2 == 0  # never "updated" for a no-id format
    assert skipped2 == 1
    assert len(list(ep_dir.glob("*.md"))) == 1
