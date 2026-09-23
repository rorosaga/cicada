"""G140 Q-R10/Q-R11 (R5 §2 defects 1, 2, 4) — a note given for an already-saved
link is kept and citable, both save replies name the episode, an agent's note
is never the person's words, and the librarian's `external:<name>` is a value
the schema accepts. Synthetic; no network (enrich is faked, the backend is
unreachable so the stdio tool takes its direct path)."""
from __future__ import annotations

import re
import urllib.request

import pytest

from _stdio_server import stdio_server
from api.services import evidence, markdown_parser, media_ingestor, owner_identity
from api.services.media_ingestor import IngestResult, MediaMeta, RawItem

URL = "https://vimeo.com/123456789"


async def _meta(url, client, from_bookmark_file=False):
    return MediaMeta(title="A clip", site="vimeo.com", media_type="url", provider="vimeo")


@pytest.fixture
def srv(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "sources"):
        (memory / sub).mkdir(parents=True)
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: memory)
    monkeypatch.setattr(media_ingestor, "enrich", _meta)

    def _offline(*a, **k):
        raise OSError("no backend in this test")

    monkeypatch.setattr(urllib.request, "urlopen", _offline)
    return server, memory


def test_both_replies_name_the_episode_and_a_duplicates_note_is_kept(srv):
    server, memory = srv
    first = server.handle_tool("cicada_save_url", {"url": URL})
    entity, episode = re.search(r"\(entity (\S+), episode (ep_[0-9_-]+)\)", first).groups()
    again = server.handle_tool("cicada_save_url", {"url": URL, "note": "It explains\nalpha indexing."})
    assert again.startswith(f'Already saved: "A clip" (entity {entity}, episode {episode}).')
    note_ep = re.search(r"Your note was kept as episode (ep_[0-9_-]+)", again).group(1)
    parsed = markdown_parser.parse(memory / "episodes" / f"{note_ep}.md")
    assert parsed.frontmatter["media_entity_id"] == entity and parsed.frontmatter["processed"] is False
    assert parsed.body.endswith("## Note\nassistant: It explains alpha indexing.")
    assert evidence.verify(memory, note_ep, "explains alpha indexing").kind == "assistant", \
        "an agent's summary is never the person's words"
    repeat = server.handle_tool("cicada_save_url", {"url": URL, "note": "It explains\nalpha indexing."})
    assert f"kept as episode {note_ep}" in repeat, "one episode per (page, note)"


def test_no_note_writes_no_episode(srv):
    server, memory = srv
    server.handle_tool("cicada_save_url", {"url": URL})
    count = len(list((memory / "episodes").glob("*.md")))
    assert "Your note was kept" not in server.handle_tool("cicada_save_url", {"url": URL})
    assert len(list((memory / "episodes").glob("*.md"))) == count


def test_the_persons_note_stays_theirs_and_an_agents_new_save_is_marked(tmp_path):
    existing = IngestResult(status="duplicate", media_entity_id="media-a-clip", episode_id="ep_2026-09-01_001",
                            title="A clip", media_type="url", url=URL)
    ep, created = media_ingestor.write_note_episode(tmp_path, RawItem(url=URL, note="Save this for the talk."),
                                                    existing)
    assert created and markdown_parser.parse(tmp_path / "episodes" / f"{ep}.md").body.endswith(
        "## Note\nSave this for the talk.")
    assert evidence.verify(tmp_path, ep, "Save this").kind == "user"
    assert media_ingestor.write_note_episode(tmp_path, RawItem(url=URL, note="   "), existing) is None
    agent = RawItem(url="https://example.com/a", note="Summary by the agent.", session_id="ses_x")
    ep2 = media_ingestor.write_media_episode(tmp_path / "episodes", agent,
                                             MediaMeta(title="A", site="example.com"), "media-a")
    body = markdown_parser.parse(tmp_path / "episodes" / f"{ep2}.md").body
    assert "## Note\nassistant: Summary by the agent." in body and "## User note" not in body


def test_the_save_route_keeps_the_persons_note_on_a_duplicate(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setattr(media_ingestor, "enrich", _meta)
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        first = client.post("/sources/save", json={"url": URL}).json()
        again = client.post("/sources/save", json={"url": URL, "note": "Watch the indexing part."}).json()
        assert again["status"] == "duplicate" and again["episodeId"] == first["episodeId"]
        assert again["noteEpisodeId"] and again["message"] == "Already saved — your note was kept"
        body = markdown_parser.parse(memory / "episodes" / f"{again['noteEpisodeId']}.md").body
        assert body.endswith("## Note\nWatch the indexing part."), "the app's note is the person's"
        assert client.post("/sources/save", json={"url": URL}).json()["noteEpisodeId"] is None
    finally:
        config.get_settings.cache_clear()


def test_the_librarians_external_name_is_a_value_the_schema_accepts(srv):
    server, memory = srv
    prop = {t["name"]: t for t in server.TOOLS}["cicada_write_claim"]["inputSchema"]["properties"]["observer"]
    assert "enum" not in prop, "JSON Schema ANDs an enum with a pattern"
    pattern = re.compile(prop["pattern"])
    for ok in ("owner", "agent", "external", "external:bob-example", owner_identity.LEGACY_OBSERVER):
        assert pattern.fullmatch(ok), ok
    for bad in ("External", "external:", "external:Bob Example", "user", "external:" + "x" * 65):
        assert not pattern.fullmatch(bad), bad
    assert "external:<name>" in prop["description"]
