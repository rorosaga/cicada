"""G118 slice 2 / R-PB4 — the chat importer keeps each message's time.

The parsers always read per-message times and `_stage_episodes` threw them
away. They now ride beside the body as `turns: [{offset, ts, speaker}]` — the
exact key and shape the Local-sources track writes — and never enter
`content_hash`, so a re-import of an unchanged thread is still a byte-
identical SKIP. Synthetic exports only.
"""
from __future__ import annotations

import hashlib

from api.routers import conversations as conv
from api.services import bank_index, episode_staging, evidence, markdown_parser


def _claude(uuid: str, messages: list[tuple[str, str]], *, updated: str = "2026-02-24T13:00:00.000000Z",
            times: bool = True) -> list[dict]:
    return [{
        "uuid": uuid, "name": "Planning", "created_at": "2026-02-24T12:39:00.000000Z", "updated_at": updated,
        "chat_messages": [
            {"uuid": f"{uuid}-m{i}", "sender": sender, "text": text, "content": [],
             **({"created_at": f"2026-02-24T12:39:{i:02d}.000000Z"} if times else {})}
            for i, (sender, text) in enumerate(messages)
        ],
    }]


def _only(ep_dir):
    [path] = list(ep_dir.glob("*.md"))
    return path, markdown_parser.parse(path)


def test_a_claude_import_keeps_each_message_time_beside_the_body(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(
        _claude("u1", [("human", "Does alpha-project use sqlite-vec?"), ("assistant", "Yes.")])), ep_dir)
    _path, parsed = _only(ep_dir)
    turns = parsed.frontmatter["turns"]
    assert turns == [
        {"offset": 0, "ts": "2026-02-24T12:39:00+00:00", "speaker": "user"},
        {"offset": len("user: Does alpha-project use sqlite-vec?") + 1,
         "ts": "2026-02-24T12:39:01+00:00", "speaker": "assistant"},
    ]
    for entry in turns:
        assert set(entry) == {"offset", "ts", "speaker"}  # the coordination contract, exactly
        assert entry["offset"] in evidence.turn_starts(parsed.body)
        assert parsed.body[entry["offset"]:].startswith(f"{entry['speaker']}:")
    assert list(parsed.frontmatter)[-1] == "turns"  # always the last key


def test_a_chatgpt_import_keeps_its_epoch_times(tmp_path):
    data = [{"conversation_id": "conv-1", "title": "Chat", "create_time": 1_700_000_000,
             "update_time": 1_700_000_500, "mapping": {
                 "n1": {"message": {"author": {"role": "user"}, "content": {"parts": ["hello alpha-project"]},
                                    "create_time": 1_700_000_000}},
                 "n2": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["hi"]},
                                    "create_time": 1_700_000_060}},
             }}]
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_chatgpt_json(data), ep_dir)
    _path, parsed = _only(ep_dir)
    assert [(t["ts"], t["speaker"]) for t in parsed.frontmatter["turns"]] == [
        ("2023-11-14T22:13:20+00:00", "user"), ("2023-11-14T22:14:20+00:00", "assistant")]


def test_the_sidecar_never_enters_the_content_hash(tmp_path):
    msgs = [("human", "Q1"), ("assistant", "A1")]
    conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", msgs)), tmp_path / "a" / "episodes")
    conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", msgs, times=False)),
                         tmp_path / "b" / "episodes")
    _pa, a = _only(tmp_path / "a" / "episodes")
    _pb, b = _only(tmp_path / "b" / "episodes")
    assert a.body == b.body
    assert a.frontmatter["content_hash"] == b.frontmatter["content_hash"] \
        == hashlib.sha256(a.body.encode()).hexdigest()[:12]
    assert "turns" in a.frontmatter and "turns" not in b.frontmatter


def test_an_unchanged_reimport_is_a_byte_identical_skip(tmp_path):
    ep_dir = tmp_path / "episodes"
    data = _claude("u1", [("human", "Q1"), ("assistant", "A1")])
    conv._stage_episodes(conv.parse_anthropic_conversations(data), ep_dir)
    path, _ = _only(ep_dir)
    before = path.read_bytes()
    assert conv._stage_episodes(conv.parse_anthropic_conversations(data), ep_dir) == (0, 0, 1)
    assert path.read_bytes() == before


def test_a_skip_never_backfills_times_onto_an_old_import(tmp_path):
    ep_dir = tmp_path / "episodes"
    msgs = [("human", "Q1"), ("assistant", "A1")]
    conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", msgs, times=False)), ep_dir)
    path, _ = _only(ep_dir)
    before = path.read_bytes()
    assert conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", msgs)), ep_dir) == (0, 0, 1)
    assert path.read_bytes() == before  # R-PB4: a SKIP means untouched


def test_a_grown_reimport_rewrites_the_sidecar(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(
        _claude("u1", [("human", "Q1"), ("assistant", "A1")])), ep_dir)
    grown = _claude("u1", [("human", "Q1"), ("assistant", "A1"), ("human", "Q2")],
                    updated="2026-02-25T09:00:00.000000Z")
    assert conv._stage_episodes(conv.parse_anthropic_conversations(grown), ep_dir) == (0, 1, 0)
    _path, parsed = _only(ep_dir)
    assert [t["offset"] for t in parsed.frontmatter["turns"]] == evidence.turn_starts(parsed.body)
    assert parsed.frontmatter["turns"][-1] == {
        "offset": parsed.body.rindex("user: Q2"), "ts": "2026-02-24T12:39:02+00:00", "speaker": "user"}


def test_an_update_that_loses_its_times_drops_the_key(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", [("human", "Q1")])), ep_dir)
    conv._stage_episodes(conv.parse_anthropic_conversations(
        _claude("u1", [("human", "Q1"), ("assistant", "A1")], times=False,
                updated="2026-02-25T09:00:00.000000Z")), ep_dir)
    _path, parsed = _only(ep_dir)
    assert "turns" not in parsed.frontmatter


def test_messages_without_times_write_no_turns_key(tmp_path):
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv._parse_chatgpt_html(
        "<div class='conversation'><p>a message long enough to keep</p></div>"), ep_dir)
    _path, parsed = _only(ep_dir)
    assert "turns" not in parsed.frontmatter


def test_the_sidecar_is_capped_head_stable(tmp_path, monkeypatch):
    # The cap moved with the stager (R-PB4's own hand-off: "if that track moves
    # `_stage_episodes`, `MAX_TURN_STAMPS` moves with it").
    monkeypatch.setattr(episode_staging, "MAX_TURN_STAMPS", 2)
    ep_dir = tmp_path / "episodes"
    conv._stage_episodes(conv.parse_anthropic_conversations(
        _claude("u1", [("human", "Q1"), ("assistant", "A1"), ("human", "Q2")])), ep_dir)
    _path, parsed = _only(ep_dir)
    assert [t["ts"] for t in parsed.frontmatter["turns"]] == [
        "2026-02-24T12:39:00+00:00", "2026-02-24T12:39:01+00:00"]


def test_a_body_that_is_not_the_messages_own_rendering_gets_no_sidecar(tmp_path):
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir()
    (episode,) = conv.parse_anthropic_conversations(_claude("u1", [("human", "Q"), ("assistant", "A")]))
    path = conv._write_new_episode(episode, ep_dir, "user: Q", "abc124", {})
    assert "turns" not in markdown_parser.parse(path).frontmatter


def test_bank_index_reads_times_as_strings(tmp_path):
    conv._stage_episodes(conv.parse_anthropic_conversations(_claude("u1", [("human", "Q1")])),
                         tmp_path / "episodes")
    bank_index.invalidate()
    [f] = bank_index.files(tmp_path, "episodes")
    assert isinstance(f.frontmatter["turns"][0]["ts"], str)
