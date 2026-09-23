"""R-N2 — a meeting speaker is never the owner's evidence; R-F2 — an agent-written
file is never the owner's words (R-LS7)."""
from __future__ import annotations

from api.services import evidence, markdown_parser
from api.services.claims import EVIDENCE_KINDS, Evidence

MEETING = "assistant: Summary (written by Wispr Flow)\nWe agreed.\nspeaker:bob-example: I will send the deck\nuser: Thanks"


def _bank(tmp_path, fm_extra=None, body=MEETING):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    fm = {"id": "ep_2026-09-01_001", "timestamp": "2026-09-01T10:00:00+00:00", "processed": False,
          "turn_index": [[0, None, "assistant"],
                         [MEETING.find("speaker:"), "2026-09-01T10:01:00Z", "speaker:bob-example"],
                         [MEETING.find("user:"), "2026-09-01T10:02:00Z", "user"]]}
    fm.update(fm_extra or {})
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md", fm, body)
    return memory


def test_speaker_is_a_fifth_kind():
    assert EVIDENCE_KINDS == ("user", "assistant", "page", "reasoning", "speaker")
    assert Evidence.from_dict({"episode": "ep_x", "start": 1, "end": 3, "kind": "speaker"}).kind == "speaker"


def test_a_speaker_line_is_never_user():
    assert evidence.speaker_kind(MEETING, MEETING.find("send the deck")) == "speaker"
    assert evidence.speaker_kind(MEETING, MEETING.find("We agreed")) == "assistant"
    assert evidence.speaker_kind(MEETING, MEETING.find("Thanks")) == "user"


def test_an_episode_override_beats_the_markers(tmp_path):
    memory = _bank(tmp_path, {"evidence_kind": "assistant"}, body="user: quoted in a sweep")
    assert evidence.verify(memory, "ep_2026-09-01_001", "quoted in a sweep").kind == "assistant"
    assert evidence.kind_for("ep_2026-09-01_001", "user: x", 6, "assistant") == "assistant"
    assert evidence.kind_for("ep_2026-09-01_001", "user: x", 6, "bogus") == "user"
    assert evidence.kind_for("media-a", "anything", 0, "user") == "page"


def test_stage1_passes_the_override_through():
    rel = {"evidence_quote": "quoted"}
    evidence.attach_relationship_evidence(rel, "ep_1", "user: quoted", kind_override="assistant")
    assert rel["evidence"][0]["kind"] == "assistant"


def test_turn_at_names_the_turn_a_span_starts_in():
    rows = [[0, None, "assistant"], [55, "t1", "speaker:bob-example"], [100, "t2", "user"]]
    assert evidence.turn_at(rows, 60) == {"number": 2, "of": 3, "ts": "t1", "speaker": "speaker:bob-example"}
    assert evidence.turn_at(rows, 0)["number"] == 1
    assert evidence.turn_at([], 5) is None and evidence.turn_at(None, 5) is None


def test_the_span_endpoint_reports_the_speaker_and_the_turn(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    start = MEETING.find("I will send")
    body = TestClient(main.app).get(
        "/episodes/ep_2026-09-01_001/span", params={"start": start, "end": start + 6}).json()
    config.get_settings.cache_clear()
    assert body["kind"] == "speaker"
    assert (body["turnNumber"], body["turnCount"], body["turnSpeaker"]) == (2, 3, "speaker:bob-example")
    assert body["turnTs"] == "2026-09-01T10:01:00Z"
