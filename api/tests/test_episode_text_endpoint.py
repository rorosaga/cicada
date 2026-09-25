"""G118 slice 2 — `GET /episodes/{id}/text`: the whole document for the Reader.

The Reader scrolls to a span inside the WHOLE conversation, so the server
returns the evidence text with its turn structure (one parser — the marker
lines `speaker_kind` reads), per-turn times only where the episode stores
them, and an optional asserted or derived focus. Engine-free, bank text only,
nothing written. Fixtures are synthetic.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import conversations as conv
from api.services import bank_index, evidence, markdown_parser, provenance
from api.services.claims import Claim, write_claims

SID = "44444444-5555-4666-8777-888888888888"
HOOK = (
    "user: Should alpha-project move to sqlite-vec?\n"
    "assistant: Yes — bob-example agreed last week.\n"
    "user: Then ship it."
)
LEGACY = "A note about alpha-project with no speaker lines."
MEDIA = "## Summary\nSaved.\n\n## Description\nA guide to alpha-project."
URL = "/episodes/ep_2026-09-03_001/text"


@pytest.fixture
def memory(tmp_path: Path, monkeypatch) -> Path:
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    (memory / "entities").mkdir()
    markdown_parser.write(memory / "episodes" / "ep_2026-09-03_001.md", {
        "id": "ep_2026-09-03_001", "timestamp": "2026-09-03T10:00:00+00:00", "source": "claude-code",
        "origin": "claude-code", "title": "Sync race", "session_id": SID, "harness": "claude-code",
        "capture_kind": "transcript", "turns": 3, "project_dir": "/home/example/alpha-project"}, HOOK)
    markdown_parser.write(memory / "episodes" / "ep_2026-08-01_001.md",
                          {"id": "ep_2026-08-01_001", "title": "A note"}, LEGACY)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "decay_class": "active"}, "# Alpha Project\n")
    markdown_parser.write(memory / "entities" / "media-example-org.md",
                          {"name": "Example guide", "type": "media", "decay_class": "evergreen"},
                          write_claims(MEDIA, [Claim(id="c", text="t")]))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield memory
    config.get_settings.cache_clear()


def test_the_whole_text_comes_back_with_its_turns(memory):
    with TestClient(main.app) as client:
        r = client.get(URL)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["text"] == HOOK and data["length"] == len(HOOK) and data["hash"] == evidence.body_hash(HOOK)
    assert data["kind"] == "episode" and data["truncated"] is False
    assert [t["index"] for t in data["turns"]] == [1, 2, 3]
    assert [t["role"] for t in data["turns"]] == ["user", "assistant", "user"]
    assert [HOOK[t["contentStart"]:t["end"]] for t in data["turns"]] == [
        "Should alpha-project move to sqlite-vec?", "Yes — bob-example agreed last week.", "Then ship it."]
    assert all(t["ts"] is None for t in data["turns"])  # the hook's `turns: 3` is a count, not a sidecar
    for t in data["turns"]:
        assert evidence.speaker_kind(HOOK, t["start"]) == t["role"]


def test_the_header_names_the_conversation_and_never_its_project_dir(memory):
    with TestClient(main.app) as client:
        r = client.get(URL)
    data = r.json()
    assert (data["title"], data["harness"], data["origin"]) == ("Sync race", "claude-code", "claude-code")
    assert data["conversationId"] == SID and data["captureKind"] == "transcript"
    assert data["timestamp"] == "2026-09-03T10:00:00+00:00"
    assert "projectDir" not in data and "resumable" not in data  # R-PB5
    assert "/home/example" not in r.text


def test_per_turn_times_come_only_from_the_import_sidecar(memory):
    export = [{"uuid": "uuid-times", "name": "Planning", "created_at": "2026-02-24T12:39:00.000000Z",
               "updated_at": "2026-02-24T13:00:00.000000Z",
               "chat_messages": [
                   {"uuid": "m0", "sender": "human", "text": "Does alpha-project use sqlite-vec?", "content": [],
                    "created_at": "2026-02-24T12:39:00.000000Z"},
                   {"uuid": "m1", "sender": "assistant", "text": "Yes.", "content": [],
                    "created_at": "2026-02-24T12:39:01.000000Z"}]}]
    conv._stage_episodes(conv.parse_anthropic_conversations(export), memory / "episodes")
    [path] = [p for p in (memory / "episodes").glob("*.md")
              if markdown_parser.parse(p).frontmatter.get("source_id") == "uuid-times"]
    with TestClient(main.app) as client:
        data = client.get(f"/episodes/{path.stem}/text").json()
    assert [t["ts"] for t in data["turns"]] == ["2026-02-24T12:39:00+00:00", "2026-02-24T12:39:01+00:00"]
    assert [t["speaker"] for t in data["turns"]] == ["user", "assistant"]
    assert data["conversationId"] == "uuid-times"


def test_a_legacy_episode_without_markers_is_one_block(memory):
    with TestClient(main.app) as client:
        data = client.get("/episodes/ep_2026-08-01_001/text").json()
    assert data["turns"] == [{"index": 1, "start": 0, "contentStart": 0, "end": len(LEGACY),
                              "role": "user", "marker": None, "speaker": None, "ts": None,
                              # G140 Q-R9: additive, set only on a timed video turn.
                              "t": None,
                              # Round 4 C4: additive, set only on an agent turn the capture labelled.
                              "model": None, "effort": None}]


def test_a_page_is_one_page_block_with_the_claims_fence_excluded(memory):
    with TestClient(main.app) as client:
        data = client.get("/episodes/media-example-org/text").json()
    assert data["kind"] == "page" and data["title"] == "Example guide"
    assert data["text"] == evidence.source_text(memory, "media-example-org") and "claims" not in data["text"]
    assert [t["role"] for t in data["turns"]] == ["page"]


def test_an_asserted_focus_reports_its_kind_and_freshness(memory):
    s = HOOK.index("bob-example agreed")
    e = s + len("bob-example agreed")
    with TestClient(main.app) as client:
        ok = client.get(URL, params={"start": s, "end": e, "hash": evidence.body_hash(HOOK)}).json()["focus"]
        stale = client.get(URL, params={"start": s, "end": e, "hash": "deadbeefcafe"}).json()["focus"]
    assert ok == {"start": s, "end": e, "kind": "assistant", "derived": False, "stale": False, "grown": False}
    assert stale["stale"] is True and stale["start"] is None and stale["end"] is None  # R-PB2


def test_a_derived_focus_finds_the_entity_by_name_and_says_so(memory):
    with TestClient(main.app) as client:
        focus = client.get(URL, params={"focus": "alpha-project"}).json()["focus"]
        unknown = client.get(URL, params={"focus": "no-such-entity"}).json()["focus"]
    assert focus["derived"] is True and focus["kind"] == "derived"
    assert HOOK[focus["start"]:focus["end"]] == "alpha-project"
    assert unknown is None  # R-PB5: the document exists; the hint simply found nothing


def test_a_derived_focus_is_never_written_back(memory):
    with TestClient(main.app) as client:
        client.get(URL)  # the app's own startup work is done before the snapshot
        before = {p: p.read_bytes() for sub in ("episodes", "entities") for p in (memory / sub).rglob("*.md")}
        client.get(URL, params={"focus": "alpha-project"})
        after = {p: p.read_bytes() for sub in ("episodes", "entities") for p in (memory / sub).rglob("*.md")}
    assert after == before


def test_the_cap_truncates_text_and_turns_but_not_length_or_hash(memory, monkeypatch):
    monkeypatch.setattr(provenance, "MAX_TEXT_CHARS", 60)
    with TestClient(main.app) as client:
        data = client.get(URL).json()
    assert data["truncated"] is True and data["text"] == HOOK[:60]
    assert data["length"] == len(HOOK) and data["hash"] == evidence.body_hash(HOOK)
    assert [t["index"] for t in data["turns"]] == [1, 2]
    assert all(t["start"] < 60 and t["end"] <= 60 and t["contentStart"] <= 60 for t in data["turns"])


def test_bad_ids_and_ranges_are_refused(memory):
    with TestClient(main.app) as client:
        assert client.get("/episodes/ep_2026-01-01_999/text").status_code == 404
        assert client.get("/episodes/..%2Fepisodes%2Fep_2026-09-03_001/text").status_code in (404, 422)
        for params in ({"start": 0}, {"end": 5}, {"start": 5, "end": 5}, {"start": 0, "end": len(HOOK) + 1},
                       {"start": -1, "end": 3}):
            assert client.get(URL, params=params).status_code == 422, params


def test_the_etag_304s_and_moves_when_the_episode_changes(memory):
    path = memory / "episodes" / "ep_2026-09-03_001.md"
    with TestClient(main.app) as client:
        etag = client.get(URL).headers["etag"]
        assert client.get(URL, headers={"If-None-Match": etag}).status_code == 304
        parsed = markdown_parser.parse(path)
        markdown_parser.write(path, parsed.frontmatter, parsed.body + "\nassistant: Shipped.")
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        again = client.get(URL, headers={"If-None-Match": etag})
    assert again.status_code == 200 and again.headers["etag"] != etag


def test_the_text_endpoint_is_bearer_gated(memory, monkeypatch):
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.setenv("CICADA_API_TOKEN", "secret-token")
    with TestClient(main.app) as client:
        assert client.get(URL).status_code == 401
        assert client.get(URL, headers={"Authorization": "Bearer secret-token"}).status_code == 200


# ---------- pure helpers ----------


def test_turns_agree_with_speaker_kind_at_every_offset():
    text = "preamble\nuser: a\nb\nASSISTANT:  c\nsystem: d\nunknown: e\nAI: f"
    spans = evidence.turns(text)
    assert [(t.role, t.marker) for t in spans] == [
        ("user", None), ("user", "user"), ("assistant", "assistant"), ("user", "system"),
        ("user", "unknown"), ("assistant", "ai")]
    for t in spans:
        for off in range(t.start, t.end):
            assert evidence.speaker_kind(text, off) == t.role, (t, off)


def test_turn_stamps_ignores_the_hooks_count_and_malformed_entries():
    assert evidence.turn_stamps({"turns": 3}) == {}
    assert evidence.turn_stamps({}) == {}
    assert evidence.turn_stamps({"turns": [
        {"offset": "x"}, "junk", {"offset": -1, "ts": "t"},
        {"offset": 4, "ts": "2026-02-24T12:39:00+00:00", "speaker": "user"},
        {"offset": 4, "ts": "duplicate"},
        {"offset": 9, "speaker": "Speaker 2"},
    ]}) == {4: {"ts": "2026-02-24T12:39:00+00:00", "speaker": "user"}, 9: {"ts": None, "speaker": "Speaker 2"}}


def test_the_provenance_module_is_engine_free():
    """G80 / the transcript rail: no LLM, no vector index, and nothing that
    touches `~/.claude` may be imported by the read paths this module serves."""
    tree = ast.parse(Path(provenance.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names |= {f"{node.module}.{a.name}" for a in node.names}
    forbidden = ("litellm", "agent_engine", "providers", "vector_index", "ask_service", "engine_select",
                 "session_stats", "transcript_capture", "transcript_extract")
    assert not [n for n in names if any(f in n for f in forbidden)], names


def test_a_focus_that_names_a_file_outside_entities_is_refused(memory):
    """`focus` is a free query string and `resolve_entity_file` joins it onto
    `entities/` as given, so `../outside` would reach a file the bank never
    stored as a page. Only a page inside `entities/` may name a mention."""
    markdown_parser.write(memory / "outside.md", {"name": "alpha-project"}, "not a page")
    with TestClient(main.app) as client:
        focus = client.get(URL, params={"focus": "../outside"}).json()["focus"]
    assert focus is None
