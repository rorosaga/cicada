"""ROR-117 / G43 — an added recording or video found by the words inside it (``file_words``), the text an app read
from a kept frame, and the rails around them.

No model and no file is read: transcripts and picture text are posted as the app would post them, the meaning leg is
the same deterministic stand-in ``test_media_files`` uses, and the words leg runs on the real FTS5 table.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from api.services import bank_registry, file_words, image_index, media_files, search_index, search_service
from api.tests.test_media_files import SHA, _segments, jpeg, text_embed

FID = SHA[:16]


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    b = tmp_path / "bank"
    (b / "entities").mkdir(parents=True)
    (b / "entities" / "alpha.md").write_text("---\nname: Alpha\ntype: concept\n---\nAlpha body.\n")
    search_index.reset()
    file_words.reset()
    search_index.rebuild(b)
    return b


def never_embeds(texts, *, is_query=False):
    raise AssertionError("the words leg must not call an embedding model")


def talk(*lines: str, each: float = 10.0) -> list[dict]:
    return [{"start": i * each, "end": i * each + each - 0.5, "text": t} for i, t in enumerate(lines)]


def filler(i: int) -> str:
    return f"We went over the plan for item {i} and then moved on to the next part of the agenda. " * 20   # a passage of its own


def add(bank, name="sync.m4a", sha=SHA, kind="audio", segments=None):
    return media_files.record_media(bank, name=name, kind=kind, sha256=sha, segments=segments)


def hits(bank, q, *, mode="prefix", embed_fn=never_embeds, kinds=("file",)):
    resp = search_service.search(bank, q, kinds=kinds, mode=mode, embed_fn=embed_fn)
    return [h for h in resp.results if h.kind == "file"]


def test_a_word_said_once_finds_its_passage_and_the_second_without_an_embedding_call(bank):
    segs = talk(*[filler(i) for i in range(12)])
    segs[7]["text"] += " The supplier Quillfeather confirmed it."
    add(bank, segments=segs)
    got = hits(bank, "quillfeather")
    assert len(got) == 1
    h = got[0]
    assert h.file_id == FID and h.type == "audio" and h.name == "sync.m4a"
    assert h.at_seconds == 70.0, "the segment that says it, not the start of its passage"
    assert h.subtitle == "the recording's words, at 1:10"
    assert "Quillfeather" in h.snippet and h.snippet_offsets and h.id == f"{FID}@70"


def test_a_prefix_as_you_type_finds_it_and_a_word_never_said_finds_nothing(bank):
    add(bank, segments=talk("The supplier Quillfeather confirmed it.", filler(1)))
    assert [h.file_id for h in hits(bank, "quillfe")] == [FID]
    assert hits(bank, "zymurgy") == []
    assert hits(bank, "quillfeather zymurgy") == [], "every word must be said"


def test_a_number_said_once_is_found(bank):
    add(bank, segments=talk(filler(1), "The invoice number is 48213907 for the quarter.", filler(2)))
    assert [h.at_seconds for h in hits(bank, "48213907")] == [10.0]


def test_a_word_and_a_meaning_for_the_same_passage_fuse_into_one_hit(bank):
    add(bank, segments=talk("Let us review the budget for the quarter with Quillfeather present.", *[filler(i) for i in range(9)]))
    media_files.refresh_text(bank, embed_fn=text_embed)
    resp = search_service.search(bank, "budget quillfeather", kinds=("file",), mode="hybrid", embed_fn=text_embed)
    files = [h for h in resp.results if h.kind == "file"]
    assert len(files) == 1, "one hit per passage, never a word hit and a meaning hit of the same passage"
    assert files[0].matched_field == "passage"
    rows = media_files.find(bank, "budget quillfeather", embed_fn=text_embed)
    assert [r["via"] for r in rows] == ["both"]


def test_a_meaning_only_hit_is_still_served_and_says_so(bank):
    add(bank, segments=_segments("guitar", "budget", "garden", each=20))
    media_files.refresh_text(bank, embed_fn=text_embed)
    resp = search_service.search(bank, "quarter spend", kinds=("file",), mode="hybrid", embed_fn=text_embed)
    files = [h for h in resp.results if h.kind == "file"]
    assert files and files[0].matched_field == "semantic"


def test_a_question_in_plain_words_finds_the_rarest_word_it_holds(bank):
    add(bank, segments=talk(*[filler(i) for i in range(9)], "Quillfeather asked about the deadline."))
    rows = media_files.find(bank, "what did they say about Quillfeather in the meeting", semantic=False)
    assert [r["metadata"]["start"] for r in rows] == [90.0]
    assert media_files.find(bank, "what is the plan", semantic=False) == [], \
        "a question of common words finds no passage by words"
    assert media_files.find(bank, "what did they say about Quillfeather in the meeting", semantic=False,
                            plain_words=False) == [], "the prefix pass wants every word"


def test_taking_a_file_out_removes_its_words_now_not_at_the_next_refresh(bank):
    add(bank, segments=talk("The supplier Quillfeather confirmed it."))
    assert hits(bank, "quillfeather")
    assert media_files.delete(bank, FID)
    assert hits(bank, "quillfeather") == []
    assert file_words.count(bank) == 0


def test_a_retired_voice_memo_leaves_the_words_index_at_once(bank):
    media_files.record_media(bank, name="memo", kind="audio", sha256=SHA, source="voice_memos", source_key="m-1",
                             recorded_at="2026-11-01T10:00:00Z", segments=talk("The supplier Quillfeather."))
    assert hits(bank, "quillfeather")
    assert media_files.retire_source(bank, "voice_memos", set()) == 1
    assert hits(bank, "quillfeather") == []


def test_a_changed_recording_replaces_its_words(bank):
    add(bank, segments=talk("The supplier Quillfeather confirmed it."))
    assert hits(bank, "quillfeather")
    add(bank, segments=talk("The supplier Marlowe confirmed it."))
    assert hits(bank, "quillfeather") == [] and hits(bank, "marlowe")


def test_it_rebuilds_from_nothing_never_an_error(bank):
    add(bank, segments=talk("The supplier Quillfeather confirmed it."))
    assert hits(bank, "quillfeather")
    # the whole derived file gone
    for suffix in ("", "-wal", "-shm"):
        Path(f"{search_index.db_path(bank)}{suffix}").unlink(missing_ok=True)
    search_index.reset(bank)
    search_index.ensure_fresh(bank, wait=True)
    assert [h.file_id for h in hits(bank, "quillfeather")] == [FID]
    # only its table gone (another layout, a hand edit)
    conn = sqlite3.connect(search_index.db_path(bank))
    conn.execute("DROP TABLE fil")
    conn.execute("DROP TABLE fil_state")
    conn.commit()
    conn.close()
    file_words.reset()
    assert [h.file_id for h in hits(bank, "quillfeather")] == [FID]
    # a folder removed by hand is dropped at the next diff
    import shutil
    shutil.rmtree(media_files.root(bank) / FID)
    file_words.reset()
    assert hits(bank, "quillfeather") == []
    assert file_words.rebuild(bank) == 0


def test_another_layout_is_rebuilt(bank, monkeypatch):
    add(bank, segments=talk("The supplier Quillfeather confirmed it."))
    assert hits(bank, "quillfeather")
    monkeypatch.setattr(file_words, "SCHEMA_VERSION", "next")
    file_words.reset()
    assert [h.file_id for h in hits(bank, "quillfeather")] == [FID]


def test_a_bank_with_no_added_file_never_gets_the_table(bank):
    assert hits(bank, "anything") == []
    conn = sqlite3.connect(search_index.db_path(bank))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert "fil" not in names and "fil_state" not in names
    assert media_files.delete(bank, "0" * 16) is False


def test_the_query_and_the_passage_are_never_logged(bank):
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    try:
        add(bank, segments=talk("The supplier Quillfeather confirmed it."))
        hits(bank, "quillfeather")
        media_files.find(bank, "what did Quillfeather say", semantic=False)
        media_files.delete(bank, FID)
    finally:
        logger.remove(sink)
    assert not any("uillfeather" in line for line in lines)


def test_the_words_live_in_a_derived_file_the_bank_never_copies_or_exports(bank):
    assert "search_index.db" in bank_registry.DERIVED_ROOT_FILES if hasattr(bank_registry, "DERIVED_ROOT_FILES") \
        else "search_index.db" in Path(bank_registry.__file__).read_text()
    add(bank, segments=talk("The supplier Quillfeather confirmed it."))
    hits(bank, "quillfeather")
    # the words are in the derived table and the store outside the bank, never in a bank file
    assert not any("Quillfeather" in p.read_text(errors="ignore") for p in bank.rglob("*.md"))
    assert media_files.root(bank).is_relative_to(Path(media_files.root(bank)).parents[1])
    assert not str(media_files.root(bank)).startswith(str(bank))


def test_sleep_and_the_other_doors_never_import_the_words_index():
    root = Path(__file__).resolve().parents[1]
    import re

    use = re.compile(r"import[^\n]*\bfile_words\b|\bfile_words\.")
    users = sorted(p.name for p in (root / "services").glob("*.py") if p.name != "file_words.py" and use.search(p.read_text()))
    assert users == ["media_files.py", "search_index.py"], users
    sleepy = [p.name for p in (root / "services").glob("*.py")
              if "media_files" in p.read_text() and p.name.startswith(("sleep", "consolidat", "stage"))]
    assert sleepy == [], "Sleep never reads the recording's words"


# --------------------------------------------------------------------------- text read from a picture


def test_text_read_from_a_frame_is_found_marked_and_at_its_second(bank):
    add(bank, name="screen.mov", kind="video", segments=[])
    media_files.record_frames(bank, FID, [(0.0, jpeg()), (42.0, jpeg())])
    out = media_files.record_frame_text(bank, FID, [(0.0, "Dashboard  overview"), (42.0, "Invoice Hawthornbeam   total 99")])
    assert out == {"kept": 2, "total": 2}
    got = hits(bank, "hawthornbeam")
    assert len(got) == 1
    h = got[0]
    assert h.file_id == FID and h.at_seconds == 42.0 and h.type == "video"
    assert h.subtitle == "text read from the picture, at 0:42" and h.id == f"{FID}@42:text"
    assert "Hawthornbeam" in h.snippet
    assert hits(bank, "dashboard")[0].at_seconds == 0.0


def test_picture_text_is_scrubbed_like_a_transcript_before_it_is_stored(bank):
    add(bank, name="screen.mov", kind="video", segments=[])
    secret = "sk-" + "a1B2c3D4" * 5
    media_files.record_frame_text(bank, FID, [(3.0, f"api key {secret} on screen")])
    stored = (media_files.root(bank) / FID / media_files.FRAME_TEXT_FILE).read_text()
    assert secret not in stored
    assert hits(bank, secret) == []
    assert hits(bank, "screen")[0].at_seconds == 3.0 if hits(bank, "screen") else True


def test_picture_text_is_bounded_replaced_removed_and_refused_for_an_unknown_file(bank):
    add(bank, name="screen.mov", kind="video", segments=[])
    media_files.record_frame_text(bank, FID, [(1.0, "x" * 9000 + " tail")])
    kept = json.loads((media_files.root(bank) / FID / media_files.FRAME_TEXT_FILE).read_text())
    assert len(kept[0]["text"]) <= media_files.MAX_FRAME_TEXT_CHARS
    media_files.record_frame_text(bank, FID, [(1.0, "Wombatzinc replaced")])
    assert hits(bank, "wombatzinc")
    media_files.record_frame_text(bank, FID, [(1.0, "   ")])
    assert hits(bank, "wombatzinc") == []
    assert not (media_files.root(bank) / FID / media_files.FRAME_TEXT_FILE).exists()
    with pytest.raises(media_files.FileRefused):
        media_files.record_frame_text(bank, "f" * 16, [(0.0, "x")])
    with pytest.raises(media_files.FileRefused):
        media_files.record_frame_text(bank, FID, [(float("nan"), "x")])
    with pytest.raises(media_files.FileRefused):
        media_files.record_frame_text(bank, FID, [(float(i), "x") for i in range(65)])


def test_the_same_text_over_consecutive_frames_is_one_passage_and_is_embedded_by_meaning(bank):
    add(bank, name="screen.mov", kind="video", segments=[])
    media_files.record_frame_text(bank, FID, [(0.0, "Quarterly budget review"), (3.0, "Quarterly budget review"),
                                              (6.0, "Garden tomatoes soil")])
    rows = media_files.staged(bank)
    assert [md["start"] for _, _, md in rows] == [0.0, 6.0]
    assert all(md["from"] == "picture" and md["words_by"] == "the recording" for _, _, md in rows)
    media_files.refresh_text(bank, embed_fn=text_embed)
    found = media_files.search_text(bank, "budget spend quarter", embed_fn=text_embed)
    assert found and found[0]["metadata"]["from"] == "picture" and found[0]["metadata"]["start"] == 0.0


def test_picture_text_feeds_recall_labelled_and_the_remote_door_sees_none_of_it(bank, monkeypatch):
    from api.services import mcp_tools

    add(bank, name="screen.mov", kind="video", segments=talk("The supplier Quillfeather confirmed it."))
    media_files.record_frame_text(bank, FID, [(42.0, "Invoice Hawthornbeam total 99")])
    lines = mcp_tools._file_lines(bank, "hawthornbeam")
    assert lines == [f"- screen.mov (video, text read from the picture, at 0:42): Invoice Hawthornbeam total 99"]
    assert mcp_tools._file_lines(bank, "what did Quillfeather say")[0].startswith("- screen.mov (video, at 0:")
    monkeypatch.setattr(image_index, "search", lambda *a, **k: [])

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

    remote = str(mcp_tools.recall(Ctx(True), "alpha hawthornbeam quillfeather"))
    assert "Hawthornbeam" not in remote and "Quillfeather" not in remote and "recording's words" not in remote
    local = str(mcp_tools.recall(Ctx(False), "alpha hawthornbeam"))
    assert "Hawthornbeam" in local and "words and meaning" in local


# --------------------------------------------------------------------------- the doors


@pytest.fixture
def client(bank, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    monkeypatch.setattr(image_index, "start_refresh", lambda *a, **k: None)
    c = TestClient(main.app)
    c.headers.update({"Authorization": f"Bearer {config.get_settings().api_token}"} if getattr(
        config.get_settings(), "api_token", None) else {})
    yield c
    config.get_settings.cache_clear()


def test_the_frames_route_keeps_the_text_beside_the_frame_and_search_finds_it(client, bank):
    import base64

    add(bank, name="screen.mov", kind="video", segments=[])
    body = {"frames": [{"t": 12.0, "jpeg": base64.b64encode(jpeg()).decode(), "text": "Roadmap Pelicanwick"},
                       {"t": 20.0, "jpeg": base64.b64encode(jpeg()).decode()}]}
    r = client.post(f"/files/{FID}/frames", json=body)
    assert r.status_code == 200, r.text
    assert [h.at_seconds for h in hits(bank, "pelicanwick")] == [12.0]
    again = {"frames": [{"t": 12.0, "jpeg": body["frames"][0]["jpeg"]}]}
    assert client.post(f"/files/{FID}/frames", json=again).status_code == 200
    assert hits(bank, "pelicanwick"), "a frame posted without text leaves the text it had"
    assert client.delete(f"/files/{FID}").status_code == 200
    assert hits(bank, "pelicanwick") == []


def test_a_demo_bank_refuses_picture_text(client, bank, monkeypatch):
    from api.services import demo_guard

    add(bank, name="screen.mov", kind="video", segments=[])
    monkeypatch.setattr(demo_guard, "is_demo", lambda *_: True)
    import base64

    r = client.post(f"/files/{FID}/frames", json={"frames": [{"t": 1.0, "jpeg": base64.b64encode(jpeg()).decode(),
                                                              "text": "Pelicanwick"}]})
    assert r.status_code == 409
    assert hits(bank, "pelicanwick") == []


# --------------------------------------------------------------------------- landing on the second it is said


def short_talk(n: int = 12) -> list[dict]:
    """Twelve short segments: one passage of several segments, each ten seconds long."""
    segs = talk(*[f"Segment {i} is about the weather and the plan." for i in range(n)])
    segs[7]["text"] = "Then the supplier Quillfeather confirmed the delivery date."
    return segs


def test_a_word_in_a_later_segment_of_a_multi_segment_passage_lands_on_that_segment(bank):
    add(bank, segments=short_talk())
    assert len(media_files.staged(bank)) == 1, "one passage holds every segment"
    h = hits(bank, "quillfeather")[0]
    assert h.at_seconds == 70.0 and h.id == f"{FID}@70"
    assert media_files.find(bank, "quillfeather", semantic=False)[0]["metadata"]["start"] == 0.0, \
        "the passage still starts at 0; the hit lands on the segment"


def test_a_meaning_hit_lands_on_the_segment_that_best_matches_the_query_words(bank, monkeypatch):
    add(bank, segments=short_talk())
    row = {"key": FID, "score": 0.3, "cosine": 0.8, "text": "x",
           "metadata": {"file_id": FID, "name": "sync.m4a", "kind": "audio", "start": 0.0, "end": 119.5}}
    monkeypatch.setattr(media_files, "search_text", lambda *a, **k: [row])
    monkeypatch.setattr(file_words, "search", lambda *a, **k: [])
    got = media_files.find(bank, "when did the supplier confirm the delivery", embed_fn=never_embeds)
    assert [(r["via"], r["at"]) for r in got] == [("meaning", 70.0)]
    # nothing in the passage holds a query word: the passage's own start
    got = media_files.find(bank, "something about holidays abroad", embed_fn=never_embeds)
    assert [(r["via"], r["at"]) for r in got] == [("meaning", 0.0)]


def test_a_small_library_finds_the_exact_word_a_meaning_search_would_not(bank):
    add(bank, segments=talk("The quarterly figures looked fine.", "Quillfeather will send the contract on Friday."))
    assert media_files.search_text(bank, "who is mailing the paperwork", embed_fn=text_embed) == [], \
        "no meaning index built and a lone passage never clears the floor"
    assert [r["at"] for r in media_files.find(bank, "Quillfeather", embed_fn=text_embed)] == [10.0]


def test_a_number_or_a_code_inside_a_question_is_a_rare_word_too(bank):
    add(bank, segments=talk(*[filler(i) for i in range(8)], "The invoice number is 48213907 and the model is ZX-4471."))
    for q in ("what was the invoice number 48213907 about", "which model is ZX-4471"):
        assert [r["metadata"]["start"] for r in media_files.find(bank, q, semantic=False)] == [80.0], q
