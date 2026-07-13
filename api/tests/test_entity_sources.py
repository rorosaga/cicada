from pathlib import Path
import json
from api.services.entity_sources import gather_entity_sources


def _setup(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    eps = tmp_path / "episodes"; eps.mkdir()
    (ents / "diego.md").write_text(
        "---\nname: Diego\ntype: person\nstatus: active\nconfidence: 0.9\n"
        "source_episodes:\n- ep_1\n---\n\n## Summary\nfounder\n")
    (eps / "ep_1.md").write_text(
        "---\nid: ep_1\nsource: claude\nsource_id: conv-abc\n---\n\nuser: hi\nassistant: hello\n")
    return tmp_path


def test_chunks_mode_returns_episode_body(tmp_path):
    m = _setup(tmp_path)
    out = gather_entity_sources(m, "diego", mode="chunks")
    assert out["episodes"][0]["id"] == "ep_1"
    assert "hello" in out["episodes"][0]["chunk"]
    assert out["episodes"][0]["conversation"] is None


def test_full_mode_resolves_conversation_from_corpus(tmp_path):
    m = _setup(tmp_path)
    corpus = tmp_path / "corpus"; (corpus / "chat-exports" / "claude").mkdir(parents=True)
    (corpus / "chat-exports" / "claude" / "conversations.json").write_text(json.dumps([
        {"uuid": "conv-abc", "name": "The chat", "chat_messages": [{"text": "full context"}]}
    ]))
    out = gather_entity_sources(m, "diego", mode="full", corpus_path=corpus)
    assert out["episodes"][0]["conversation"]["name"] == "The chat"
    assert out["degraded"] is False
