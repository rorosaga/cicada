"""Recordings and videos the person adds (meaning index 2, G195 stage 2): the store outside every bank, the words in
the one meaning index as the recording's (never the person's), the frames as pictures, and the doors.

No model and no file is read: the app's derivatives are posted as the app would post them, the words embed through a
deterministic stand-in where topic words name directions, so "budget review" lands on the passage about the budget.
"""
from __future__ import annotations

import base64
import json
import struct
import zlib

import numpy as np
import pytest

from api.services import image_index, media_files, search_service

DIM = 32
TOPICS = {"budget": 0, "quarter": 0, "spend": 0, "guitar": 1, "chords": 1, "song": 1,
          "garden": 2, "tomatoes": 2, "soil": 2, "tax": 3, "invoice": 3}


def text_embed(texts, *, is_query=False):
    rows = []
    for t in texts:
        v = np.zeros(DIM, dtype=np.float32)
        v[DIM - 1] = 1.0                                  # every text shares a direction, as real ones do
        rng = np.random.default_rng(zlib.crc32(t.encode()))
        v[8:DIM - 1] = rng.standard_normal(DIM - 9) * 0.02
        for w in t.lower().replace(".", " ").split():
            if w in TOPICS:
                v[TOPICS[w]] += 1.0
        rows.append(v / np.linalg.norm(v))
    return np.stack(rows)


def jpeg(width=640, height=360) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, height, width) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


SHA = "ab" * 32


def _segments(*topics: str, each: int = 6) -> list[dict]:
    out, t = [], 0.0
    for topic in topics:
        for i in range(each):
            out.append({"start": t, "end": t + 9.5,
                        "text": f"We talked about the {topic} again, part {i}. " + "and so on " * 25})
            t += 10.0
    return out


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    b = tmp_path / "bank"
    (b / "entities").mkdir(parents=True)
    return b


def test_the_words_are_kept_outside_the_bank_scrubbed_and_as_the_recordings(bank, tmp_path):
    segs = _segments("budget") + [{"start": 70, "end": 75, "text": "my key is sk-ant-api03-" + "A" * 40}]
    out = media_files.record_media(bank, name="team sync.m4a", kind="audio", sha256=SHA, size=1234,
                                   duration_s=80, segments=segs)
    assert out == {"action": "added", "id": SHA[:16]}
    folder = media_files.root(bank) / SHA[:16]
    assert bank not in folder.parents and (tmp_path / "home") in folder.parents
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["words_by"] == "the recording" and meta["segments"] == 7
    assert "sk-ant" not in (folder / "transcript.json").read_text(), "every writer scrubs"
    again = media_files.record_media(bank, name="team sync.m4a", kind="audio", sha256=SHA, segments=segs[:2])
    assert again["action"] == "updated" and media_files.get(bank, SHA[:16])["segments"] == 2


@pytest.mark.parametrize("bad", [
    {"kind": "pdf"}, {"sha256": "nope"}, {"segments": [{"start": -1, "text": "x"}]},
    {"segments": [{"start": "soon", "text": "x"}]}, {"duration_s": float("inf")},
])
def test_anything_out_of_shape_is_refused_and_nothing_is_written(bank, bad):
    args = {"name": "a.m4a", "kind": "audio", "sha256": SHA, "segments": _segments("budget"), **bad}
    with pytest.raises(media_files.FileRefused):
        media_files.record_media(bank, **args)
    assert media_files.list_files(bank) == []


def test_frames_are_small_jpegs_of_a_video_only(bank):
    media_files.record_media(bank, name="talk.mov", kind="video", sha256=SHA, segments=_segments("guitar"))
    fid = SHA[:16]
    assert media_files.record_frames(bank, fid, [(0.0, jpeg()), (3.0, jpeg())]) == {"kept": 2, "total": 2}
    assert media_files.frame_file(bank, fid, 3000) is not None
    assert media_files.frame_file(bank, fid, 6000) is None, "only a frame its own list names"
    with pytest.raises(media_files.FileRefused):
        media_files.record_frames(bank, fid, [(6.0, jpeg(1280, 720))])
    with pytest.raises(media_files.FileRefused):
        media_files.record_frames(bank, fid, [(6.0, b"\x89PNG\r\n\x1a\nnot a jpeg")])
    media_files.record_media(bank, name="memo.m4a", kind="audio", sha256="cd" * 32, segments=_segments("tax"))
    with pytest.raises(media_files.FileRefused):
        media_files.record_frames(bank, ("cd" * 32)[:16], [(0.0, jpeg())])


def test_passages_keep_their_times_and_whole_segments():
    meta = {"id": SHA[:16], "name": "n", "kind": "audio"}
    segs = [{"start": i * 10.0, "end": i * 10.0 + 9, "text": "w" * 300} for i in range(12)]
    rows = media_files.passages(meta, segs)
    assert len(rows) >= 3 and all(len(t) <= media_files.PASSAGE_CHARS for _k, t, _m in rows)
    assert rows[0][2]["start"] == 0.0 and rows[1][2]["start"] > rows[0][2]["end"] - 10
    assert rows[-1][2]["end"] == 119.0 and rows[0][2]["words_by"] == "the recording"


def test_a_query_finds_the_passage_and_its_time_and_nothing_for_an_absent_topic(bank):
    media_files.record_media(bank, name="team sync.m4a", kind="audio", sha256=SHA,
                             segments=_segments("guitar", "budget", "garden", each=20))
    stats = media_files.refresh_text(bank, embed_fn=text_embed)
    assert stats["embedded"] >= 3
    hits = media_files.search_text(bank, "the budget for the quarter", embed_fn=text_embed)
    assert hits and "budget" in hits[0]["text"] and hits[0]["metadata"]["start"] >= 200
    assert all(h["score"] >= media_files.TEXT_LIFT_MIN for h in hits)
    assert media_files.search_text(bank, "invoice tax", embed_fn=text_embed) == []
    again = media_files.refresh_text(bank, embed_fn=text_embed)
    assert again["embedded"] == 0, "nothing changed, nothing embedded"


def test_with_only_a_few_passages_the_right_one_still_clears_the_floor(bank):
    """Found driving the app (2026-10-29): with two passages the plain lift halves the gap, so the right passage
    never cleared the floor. The lift is over the other passages' mean (`image_index.loo_lift`)."""
    media_files.record_media(bank, name="a.m4a", kind="audio", sha256=SHA, segments=_segments("budget", each=6))
    media_files.record_media(bank, name="b.m4a", kind="audio", sha256="cd" * 32, segments=_segments("garden", each=6))
    media_files.refresh_text(bank, embed_fn=text_embed)
    hits = media_files.search_text(bank, "budget quarter", embed_fn=text_embed)
    assert hits and {h["metadata"]["name"] for h in hits} == {"a.m4a"}


def test_a_lone_item_is_never_shown_for_free():
    """Review of #529: a lone item (or an unknown count) used to clear the floor for every query. Now it needs an
    absolute cosine calibrated for its model, and with none it isn't shown at all."""
    from api.services import image_index

    assert image_index.loo_lift(0.4, 0.4, 1) is None and image_index.loo_lift(0.4, 0.4, 0) is None
    assert image_index.loo_lift(0.7, 0.5, 2) == pytest.approx(0.4), "0.7 against the other's 0.3"
    assert image_index.clears(0.99, 0.99, 1, lift_min=0.12, lone_min=None) is None, "no calibrated floor: never"
    assert image_index.clears(0.60, 0.60, 1, lift_min=0.12, lone_min=0.68) is None, "an unrelated query"
    assert image_index.clears(0.75, 0.75, 1, lift_min=0.12, lone_min=0.68) == 0.75, "a related one, by its cosine"
    assert image_index.clears(0.75, 0.75, 0, lift_min=0.12, lone_min=0.68) == 0.75, "an unknown count is lone"
    assert image_index.calibrated("google/embeddinggemma-2:768") and not image_index.calibrated("intfloat/e5:384")


def test_one_recording_answers_only_what_it_says(bank, monkeypatch):
    """The reviewer's repro: one recording about the budget, then "garden roses" — it used to come back (0.498)."""
    from api.services import image_index

    media_files.record_media(bank, name="a.m4a", kind="audio", sha256=SHA, segments=_segments("budget", each=3))
    media_files.refresh_text(bank, embed_fn=text_embed)
    assert media_files.search_text(bank, "garden roses", embed_fn=text_embed) == []
    assert media_files.search_text(bank, "budget quarter", embed_fn=text_embed) == [], \
        "the stand-in model has no calibrated floor: a lone passage is never shown"
    monkeypatch.setattr(image_index, "calibrated", lambda model: True)   # as if EmbeddingGemma 2
    monkeypatch.setattr(image_index, "LONE_TEXT_COSINE_MIN", 0.8)
    assert media_files.search_text(bank, "garden roses", embed_fn=text_embed) == []
    hits = media_files.search_text(bank, "budget quarter", embed_fn=text_embed)
    assert hits and hits[0]["score"] == hits[0]["cosine"] >= 0.8


def test_a_missing_count_never_turns_the_floor_off(bank):
    """Stats written without `n` (an older or damaged row) read as n = 0: lone, never "every passage clears"."""
    import sqlite3

    media_files.record_media(bank, name="a.m4a", kind="audio", sha256=SHA,
                             segments=_segments("guitar", "budget", "garden", each=20))
    media_files.refresh_text(bank, embed_fn=text_embed)
    conn = sqlite3.connect(bank / "vector_index.db")
    conn.execute(f"DELETE FROM stats_{media_files.TEXT_KIND} WHERE name = 'n'")
    conn.commit()
    conn.close()
    assert media_files.search_text(bank, "invoice tax", embed_fn=text_embed) == []
    assert media_files.search_text(bank, "budget quarter", embed_fn=text_embed) == [], \
        "with no calibrated floor for the stand-in model, an unknown count shows nothing"


def test_deleting_a_file_takes_its_words_out_of_search(bank):
    media_files.record_media(bank, name="a.m4a", kind="audio", sha256=SHA, segments=_segments("budget", "garden"))
    media_files.refresh_text(bank, embed_fn=text_embed)
    assert media_files.delete(bank, SHA[:16])
    media_files.refresh_text(bank, embed_fn=text_embed)
    assert media_files.search_text(bank, "budget", embed_fn=text_embed) == []


def test_the_search_route_serves_file_hits_by_name_only(bank, monkeypatch):
    media_files.record_media(bank, name="team sync.m4a", kind="audio", sha256=SHA,
                             segments=_segments("guitar", "budget", "garden", each=20))
    media_files.refresh_text(bank, embed_fn=text_embed)
    resp = search_service.search(bank, "budget quarter", kinds=search_service.parse_kinds("recordings"),
                                 mode="hybrid", embed_fn=text_embed)
    files = [h for h in resp.results if h.kind == "file"]
    assert files and files[0].file_id == SHA[:16] and files[0].at_seconds is not None
    assert files[0].subtitle.startswith("the recording's words"), "never the person's own"
    assert "file" not in search_service.KINDS, "never part of every kind (`cicada find`'s default)"
    dumped = files[0].model_dump(by_alias=True)
    assert {"fileId", "atSeconds", "endSeconds"} <= set(dumped)


def test_frames_become_pictures_with_their_time(bank):
    media_files.record_media(bank, name="talk.mov", kind="video", sha256=SHA, segments=[])
    media_files.record_frames(bank, SHA[:16], [(0.0, jpeg()), (63.0, jpeg())])
    pics = {p.key: p for p in media_files.pictures(bank)}
    p = pics[f"frame:{SHA[:16]}@63000"]
    assert p.source == "frame" and p.at == 63.0 and p.title == "talk.mov at 1:03"
    assert p.meta()["file_id"] == SHA[:16] and p.meta()["at"] == 63.0
    assert p.thumb == f"/files/{SHA[:16]}/frames/63000"
    assert f"frame:{SHA[:16]}@0" in {q.key for q in image_index.sources(bank)}


def test_recall_lists_the_recordings_words_on_a_local_door_only(bank, monkeypatch):
    from api.services import mcp_tools

    rows = [{"key": SHA[:16], "score": 0.3, "cosine": 0.8, "text": "We talked about the budget again.",
             "metadata": {"file_id": SHA[:16], "name": "team sync.m4a", "kind": "audio", "start": 125.0}}]
    monkeypatch.setattr(media_files, "search_text", lambda *a, **k: rows)
    lines = mcp_tools._file_lines(bank, "budget")
    assert lines == ["- team sync.m4a (audio, at 2:05): We talked about the budget again."]
    monkeypatch.setattr(image_index, "search", lambda *a, **k: [])
    (bank / "entities" / "alpha.md").write_text("---\nname: Alpha\ntype: concept\n---\nAlpha body.\n")

    class Ctx:
        raw_excerpts = False
        skipped_inbox_ids = ()
        state_hint_sent = True
        is_cli = False
        read_surface = "test"

        def __init__(self, remote):
            self.is_remote = remote

        def memory_path(self):
            return bank

        def can(self, _name):
            return True

    assert "recording's words" not in str(mcp_tools.recall(Ctx(True), "alpha"))
    assert "From recordings and videos you added (the recording's words, not yours" in \
        str(mcp_tools.recall(Ctx(False), "alpha"))


# --------------------------------------------------------------------------- the routes


@pytest.fixture
def client(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    started = []
    monkeypatch.setattr(image_index, "start_refresh", lambda mp, **kw: started.append(kw) or True)
    with TestClient(main.app) as c:
        c.started = started
        yield c
    config.get_settings.cache_clear()


def test_the_routes_keep_derivatives_and_never_embed_on_a_request(client, bank):
    body = {"name": "talk.mov", "kind": "video", "sha256": SHA, "size": 10, "durationS": 120,
            "segments": [{"start": 0, "end": 5, "text": "Hello and welcome."}]}
    r = client.post("/files/media", json=body)
    assert r.status_code == 200 and r.json()["id"] == SHA[:16]
    r = client.post(f"/files/{SHA[:16]}/frames",
                    json={"frames": [{"t": 3, "jpeg": base64.b64encode(jpeg()).decode()}]})
    assert r.status_code == 200 and r.json() == {"kept": 1, "total": 1}
    assert client.get(f"/files/{SHA[:16]}/frames/3000").status_code == 200
    assert client.get(f"/files/{SHA[:16]}/frames/9000").status_code == 404
    listed = client.get("/files").json()["files"]
    assert listed[0]["name"] == "talk.mov" and "sha256" not in listed[0] and listed[0]["frames"] == 1
    assert client.post("/files/media", json={**body, "kind": "pdf"}).status_code == 422
    assert all(kw.get("delay_s") for kw in client.started), "the refresh runs later, in the background"
    assert client.delete(f"/files/{SHA[:16]}").status_code == 200
    assert client.get("/files").json()["files"] == []


def test_a_demo_bank_refuses_added_files(client, bank, monkeypatch):
    from api.services import demo_guard

    monkeypatch.setattr(demo_guard, "is_demo", lambda p: True)
    body = {"name": "a.m4a", "kind": "audio", "sha256": SHA, "segments": []}
    assert client.post("/files/media", json=body).status_code == 409
