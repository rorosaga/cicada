"""Track I T2 (R-IA6) — each message's time rides beside the body as
``turns: [{offset, ts, speaker}]``, outside ``content_hash`` (the brief's shape,
byte-identical to feat/provenance-viewer 2a5ab0b)."""
from __future__ import annotations

import hashlib

from _intake_fixtures import claude_conversations
from api.routers import conversations as conv
from api.services import markdown_parser


def _only(ep_dir):
    [path] = list(ep_dir.glob("*.md"))
    return markdown_parser.parse(path)


def test_an_import_keeps_each_message_time_as_the_last_key(tmp_path):
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1)), tmp_path / "episodes")
    parsed = _only(tmp_path / "episodes")
    turns = parsed.frontmatter["turns"]
    first = "user: How is alpha-project going? (0)"
    assert turns == [
        {"offset": 0, "ts": "2026-02-01T12:00:00+00:00", "speaker": "user"},
        {"offset": len(first) + 1, "ts": "2026-02-01T12:00:05+00:00", "speaker": "assistant"},
    ]
    assert list(parsed.frontmatter)[-1] == "turns"
    for t in turns:
        assert parsed.body[t["offset"]:].startswith(f"{t['speaker']}:")


def test_the_sidecar_never_enters_the_content_hash(tmp_path):
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1)), tmp_path / "episodes")
    parsed = _only(tmp_path / "episodes")
    assert parsed.frontmatter["content_hash"] == hashlib.sha256(parsed.body.encode()).hexdigest()[:12]


def test_an_unchanged_reimport_is_a_byte_identical_skip(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1)), ep_dir)
    [path] = list(ep_dir.glob("*.md"))
    before = path.read_bytes()
    assert conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1)), ep_dir) == (0, 0, 1)
    assert path.read_bytes() == before


def test_a_grown_reimport_rewrites_the_sidecar(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1)), ep_dir)
    conv._stage_episodes(conv.parse_anthropic_conversations(claude_conversations(1, grown=True)), ep_dir)
    assert len(_only(ep_dir).frontmatter["turns"]) == 3
