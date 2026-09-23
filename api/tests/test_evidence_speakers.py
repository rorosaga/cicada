"""R-N2 — a meeting speaker is never the owner's evidence; R-F2 — an agent-written
file is never the owner's words (R-LS7)."""
from __future__ import annotations

from api.services import evidence, markdown_parser
from api.services.claims import EVIDENCE_KINDS, Evidence

MEETING = "assistant: Summary (written by Wispr Flow)\nWe agreed.\nspeaker:bob-example: I will send the deck\nuser: Thanks"


def _bank(tmp_path, fm_extra=None, body=MEETING):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    # The G118 R-PB4 sidecar the stager writes: an entry only for a turn with a
    # time, so Wispr's own (untimed) summary turn has none.
    fm = {"id": "ep_2026-09-01_001", "timestamp": "2026-09-01T10:00:00+00:00", "processed": False,
          "turns": [{"offset": MEETING.find("speaker:"), "ts": "2026-09-01T10:01:00+00:00",
                     "speaker": "speaker:bob-example"},
                    {"offset": MEETING.find("user:"), "ts": "2026-09-01T10:02:00+00:00", "speaker": "user"}]}
    fm.update(fm_extra or {})
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md", fm, body)
    return memory


def test_speaker_is_a_fifth_kind():
    # G140 Q-R9 appended `media` after it — six kinds, append-only.
    assert EVIDENCE_KINDS == ("user", "assistant", "page", "reasoning", "speaker", "media")
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
    stamps = evidence.turn_stamps({"turns": [
        {"offset": MEETING.find("speaker:"), "ts": "t1", "speaker": "speaker:bob-example"},
        {"offset": MEETING.find("user:"), "ts": "t2", "speaker": "user"}]})
    assert evidence.turn_at(MEETING, MEETING.find("send the deck"), stamps) == {
        "number": 2, "of": 3, "ts": "t1", "speaker": "speaker:bob-example"}
    # An untimed turn has no entry: it is still counted, and its speaker is the
    # marker as written — never an inferred time.
    assert evidence.turn_at(MEETING, MEETING.find("We agreed"), stamps) == {
        "number": 1, "of": 3, "ts": None, "speaker": "assistant"}
    assert evidence.turn_at(MEETING, 5, {}) is None and evidence.turn_at(MEETING, 5, None) is None


def test_the_reader_turns_agree_with_the_span_kind_on_speaker_lines():
    """R-PB3 across the merge: dev's turn parser and `speaker_kind` read one
    grammar, so a meeting utterance is a `speaker` turn, never `user`."""
    spans = evidence.turns(MEETING)
    assert [t.role for t in spans] == ["assistant", "speaker", "user"]
    assert spans[1].marker == "speaker:bob-example"
    assert MEETING[spans[1].content_start:spans[1].end] == "I will send the deck"
    assert evidence.turn_starts(MEETING) == [t.start for t in spans]
    for t in spans:
        for off in range(t.start, t.end):
            assert t.role == evidence.speaker_kind(MEETING, off), (t, off)


def test_an_override_relabels_every_reader_turn():
    spans = evidence.turns("user: quoted in a sweep\nassistant: and more", override="assistant")
    assert {t.role for t in spans} == {"assistant"}
    assert {t.role for t in evidence.turns("user: q", override="bogus")} == {"user"}


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
    assert body["turnTs"] == "2026-09-01T10:01:00+00:00"


# ---------- the merge with G140: one marker grammar, both line families ----------

MIXED = ("user: here is the talk\nVideo: the one I recorded\nspeaker:bob-example: I watched it too\n"
         "video [12:34]: search is one lookup\nassistant: noted\nmedia [1:02:03]: the long one")


def test_one_marker_grammar_reads_speakers_and_timed_video_lines():
    """R-PB3 across the G134 x G140 merge: `speaker:<label>:` is `speaker`, a
    timed `video [m:ss]:` line is `media` with its `t`, an untimed "Video:"
    line stays the person's — and turns, span kinds and `media_time` agree at
    every offset."""
    spans = evidence.turns(MIXED)
    assert [(t.role, t.marker, t.t) for t in spans] == [
        ("user", "user", None), ("speaker", "speaker:bob-example", None), ("media", "video", 754),
        ("assistant", "assistant", None), ("media", "media", 3723)]
    assert evidence.turn_starts(MIXED) == [t.start for t in spans]
    for t in spans:
        for off in range(t.start, t.end):
            assert evidence.speaker_kind(MIXED, off) == t.role, (t, off)
            assert evidence.media_time(MIXED, off) == t.t, (t, off)
            assert evidence.kind_for("ep_2026-09-01_001", MIXED, off) == t.role, (t, off)


def test_an_override_wins_over_both_families_and_drops_the_time():
    """The episode-level `evidence_kind` (R-LS7) still wins before per-line
    markers — a `media` line in a relabelled episode is neither `media` nor
    timed, so `t` and `kind` never disagree."""
    at = MIXED.index("search is one lookup")
    assert evidence.kind_for("ep_2026-09-01_001", MIXED, at, "assistant") == "assistant"
    assert evidence.media_time(MIXED, at, "assistant") is None
    assert evidence.media_time(MIXED, at, "bogus") == 754
    spans = evidence.turns(MIXED, override="user")
    assert {t.role for t in spans} == {"user"} and {t.t for t in spans} == {None}


def test_the_span_endpoint_carries_the_time_and_the_turn_together(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    fm = {"id": "ep_2026-09-01_001", "timestamp": "2026-09-01T10:00:00+00:00", "processed": False,
          "turns": [{"offset": MIXED.find("video ["), "ts": "2026-09-01T10:05:00+00:00", "speaker": "video"}]}
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md", fm, MIXED)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        start = MIXED.find("search is one lookup")
        body = client.get("/episodes/ep_2026-09-01_001/span", params={"start": start, "end": start + 6}).json()
        speaker_at = MIXED.find("I watched")
        other = client.get("/episodes/ep_2026-09-01_001/span",
                           params={"start": speaker_at, "end": speaker_at + 5}).json()
        doc = client.get("/episodes/ep_2026-09-01_001/text").json()
    finally:
        config.get_settings.cache_clear()
    assert (body["kind"], body["t"]) == ("media", 754)
    assert (body["turnNumber"], body["turnCount"], body["turnTs"]) == (3, 5, "2026-09-01T10:05:00+00:00")
    assert (other["kind"], other["t"]) == ("speaker", None)
    assert [(t["role"], t.get("t")) for t in doc["turns"]] == [
        ("user", None), ("speaker", None), ("media", 754), ("assistant", None), ("media", 3723)]
