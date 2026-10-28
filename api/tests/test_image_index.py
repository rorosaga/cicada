"""Pictures in the one meaning index (vision item 3, 2026-10-28): ``image_index`` — what is indexed, how a refresh
diffs, how a text query meets pictures, the picture child, and the doors that may (and may not) see them.

No model runs: pictures embed through a deterministic stand-in (a picture's bytes name its colour), queries through a
matching text stand-in, so "a red thing" lands near the red pictures exactly as the real encoder's shared space would.
The real encoder's numbers are ``benchmarks.perf.image_index_build``'s.
"""
from __future__ import annotations

import json
import zlib
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from api.services import embed_worker, image_index, search_service

DIM = 16
WORDS = {"red": 0, "blue": 1, "green": 2, "yellow": 3, "tax": 4, "form": 5}
TEXT_AXIS, IMAGE_AXIS = 15, 14


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def text_embed(texts, *, is_query=False):
    rows = []
    for t in texts:
        v = np.zeros(DIM, dtype=np.float32)
        v[TEXT_AXIS] = 1.2
        for w in t.lower().split():
            if w in WORDS:
                v[WORDS[w]] += 1.0
        rows.append(_unit(v))
    return np.stack(rows)


def picture_vec(data: bytes) -> np.ndarray:
    colour, _, salt = data.decode().partition(":")
    rng = np.random.default_rng(zlib.crc32(salt.encode()))
    v = rng.standard_normal(DIM).astype(np.float32) * 0.02
    v[IMAGE_AXIS] += 1.0
    if colour in WORDS:
        v[WORDS[colour]] += 0.6
    return _unit(v)


CALLS: list[int] = []


def picture_embed(blobs):
    CALLS.append(len(blobs))
    return embed_worker.picture_rows(lambda b: (_ for _ in ()).throw(ValueError("bad")) if b.startswith(b"bad")
                                     else picture_vec(b))(blobs)


EMBEDDER = (picture_embed, "test/pictures:16")


def _pictures(folder: Path, spec: dict[str, bytes]) -> list[image_index.Picture]:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for key, data in spec.items():
        path = folder / f"{key.replace(':', '_')}.jpg"
        path.write_bytes(data)
        out.append(image_index.Picture(key, key.split(":")[0], path, title=f"picture {key}", entity_id=key.split(":")[1],
                                       thumb=f"/entities/{key.split(':')[1]}/preview"))
    return out


@pytest.fixture
def bank(tmp_path, monkeypatch):
    b = tmp_path / "bank"
    (b / "entities").mkdir(parents=True)
    CALLS.clear()
    # The one picture stamp is `vision_embedder.fingerprint` (the real decoder on a reference picture); held fixed
    # here so the tests read the diff, not `sips`. `test_the_stamp_is_the_vision_fingerprint` checks the wiring.
    monkeypatch.setattr(image_index, "recipe", lambda: "fp-test")
    return b


def test_the_stamp_is_the_vision_fingerprint(monkeypatch):
    from api.services import vision_embedder

    monkeypatch.setattr(vision_embedder, "fingerprint", lambda *a, **k: "abc123abc123")
    assert image_index.recipe() == "abc123abc123", "one stamp for both picture stores"

    def broken(*a, **k):
        raise RuntimeError("no decoder")

    monkeypatch.setattr(vision_embedder, "fingerprint", broken)
    assert image_index.recipe() is None


def _board(tmp_path) -> dict[str, bytes]:
    spec = {}
    for colour in ("red", "blue", "green", "yellow"):
        for i in range(3):
            spec[f"preview:{colour}-{i}"] = f"{colour}:{i}".encode()
    return spec


def test_a_refresh_embeds_what_is_new_reuses_what_is_not_and_drops_what_is_gone(bank, tmp_path):
    pics = _pictures(tmp_path / "pics", _board(tmp_path))
    first = image_index.refresh(bank, EMBEDDER, pictures=pics)
    assert first["embedded"] == 12 and first["total"] == 12
    again = image_index.refresh(bank, EMBEDDER, pictures=pics)
    assert again["embedded"] == 0 and again["reused"] == 12, "nothing changed, nothing embedded"
    pics[0].path.write_bytes(b"blue:changed")
    changed = image_index.refresh(bank, EMBEDDER, pictures=pics[:-1])
    assert (changed["embedded"], changed["removed"], changed["total"]) == (1, 1, 11)


def test_the_picture_table_writes_only_its_own_stamps(bank, tmp_path):
    conn = sqlite3.connect(bank / "vector_index.db")
    conn.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany("INSERT INTO index_meta VALUES (?, ?)", [("model", "text-model"), ("dim", "384")])
    conn.commit()
    conn.close()
    image_index.refresh(bank, EMBEDDER, pictures=_pictures(tmp_path / "pics", _board(tmp_path)))
    stamps = dict(sqlite3.connect(bank / "vector_index.db").execute("SELECT key, value FROM index_meta").fetchall())
    assert stamps["model"] == "text-model" and stamps["dim"] == "384", "the text tables' build model is untouched"
    assert stamps["model:images"] == "test/pictures:16" and stamps["recipe:images"] == "fp-test"


def test_a_new_recipe_or_model_rebuilds_the_table(bank, tmp_path, monkeypatch):
    pics = _pictures(tmp_path / "pics", _board(tmp_path))
    image_index.refresh(bank, EMBEDDER, pictures=pics)
    monkeypatch.setattr(image_index, "recipe", lambda: "fp-other")
    got = image_index.refresh(bank, EMBEDDER, pictures=pics)
    assert got["embedded"] == 12 and got["rebuilding"] == 0 and got["total"] == 12
    got = image_index.refresh(bank, (picture_embed, "other:16"), pictures=pics)
    assert got["embedded"] == 12 and image_index.status(bank)["model"] == "other:16"
    tables = {r[0] for r in sqlite3.connect(bank / "vector_index.db").execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'meta_images%'")}
    assert len(tables) == 1, "the finished generation replaced the old one"


def test_search_keeps_the_old_pictures_until_the_rebuild_commits(bank, tmp_path, monkeypatch):
    """Review of #506: a new model or preprocessing never empties picture search — the old generation answers until
    the new one holds every picture, even across a stop for Sleep."""
    monkeypatch.setattr(image_index, "STEP", 4)
    pics = _pictures(tmp_path / "pics", _board(tmp_path))
    image_index.refresh(bank, EMBEDDER, pictures=pics)
    before = [h["key"] for h in image_index.search(bank, "red", top_k=5, embed_fn=text_embed)]
    assert len(before) == 3
    monkeypatch.setattr(image_index, "recipe", lambda: "fp-new")
    asked = iter([False, True])
    with pytest.raises(image_index.RefreshStopped):
        image_index.refresh(bank, EMBEDDER, pictures=pics, should_stop=lambda: next(asked))
    during = [h["key"] for h in image_index.search(bank, "red", top_k=5, embed_fn=text_embed)]
    assert during == before and image_index.status(bank)["pictures"] == 12, "search still reads the old pictures"
    got = image_index.refresh(bank, EMBEDDER, pictures=pics)
    assert got["embedded"] == 8, "the stopped build resumed: only what it hadn't written"
    stamps = dict(sqlite3.connect(bank / "vector_index.db").execute("SELECT key, value FROM index_meta").fetchall())
    serving = stamps["serving:images"]
    assert stamps[f"recipe:{serving}"] == "fp-new"
    assert [h["key"] for h in image_index.search(bank, "red", top_k=5, embed_fn=text_embed)] == before


def test_a_picture_deleted_during_a_rebuild_leaves_what_search_reads_at_once(bank, tmp_path, monkeypatch):
    """Review of #506: a deletion reaches the serving generation even when the rebuild stops before any embed."""
    pics = _pictures(tmp_path / "pics", _board(tmp_path))
    image_index.refresh(bank, EMBEDDER, pictures=pics)
    monkeypatch.setattr(image_index, "recipe", lambda: "fp-new")
    kept = [p for p in pics if not p.key.startswith("preview:red")]
    with pytest.raises(image_index.RefreshStopped):
        image_index.refresh(bank, EMBEDDER, pictures=kept, should_stop=lambda: True)
    assert image_index.search(bank, "red", top_k=5, embed_fn=text_embed) == []
    assert image_index.status(bank)["pictures"] == 9
    assert len(image_index.search(bank, "blue", top_k=5, embed_fn=text_embed)) == 3, "the rest still answer"


@pytest.mark.parametrize("case", ["no pictures left", "every picture fails"])
def test_a_rebuild_with_nothing_to_embed_still_swaps(bank, tmp_path, monkeypatch, case):
    pics = _pictures(tmp_path / "pics", _board(tmp_path))
    image_index.refresh(bank, EMBEDDER, pictures=pics)
    monkeypatch.setattr(image_index, "recipe", lambda: "fp-new")
    if case == "no pictures left":
        got = image_index.refresh(bank, EMBEDDER, pictures=[])
    else:
        for p in pics:
            p.path.write_bytes(b"bad picture " + p.key.encode())
        got = image_index.refresh(bank, EMBEDDER, pictures=pics)
    assert got["rebuilding"] == 0 and got["total"] == 0
    assert image_index.search(bank, "red", top_k=5, embed_fn=text_embed) == [], "no deleted picture outlives it"
    stamps = dict(sqlite3.connect(bank / "vector_index.db").execute("SELECT key, value FROM index_meta").fetchall())
    assert not any(k.startswith("recipe:") and v != "fp-new" for k, v in stamps.items()), "the old generation is gone"


def test_a_limited_rebuild_never_swaps_in_half_a_table(bank, tmp_path, monkeypatch):
    pics = _pictures(tmp_path / "pics", _board(tmp_path))
    image_index.refresh(bank, EMBEDDER, pictures=pics)
    monkeypatch.setattr(image_index, "recipe", lambda: "fp-new")
    got = image_index.refresh(bank, EMBEDDER, pictures=pics, limit=5)
    assert got["rebuilding"] == 1 and got["total"] == 12
    assert len(image_index.search(bank, "blue", top_k=5, embed_fn=text_embed)) == 3


def test_with_no_decoder_nothing_is_embedded_and_nothing_is_dropped_for_it(bank, tmp_path, monkeypatch):
    pics = _pictures(tmp_path / "pics", _board(tmp_path))
    image_index.refresh(bank, EMBEDDER, pictures=pics)
    monkeypatch.setattr(image_index, "recipe", lambda: None)
    got = image_index.refresh(bank, EMBEDDER, pictures=pics)
    assert (got["embedded"], got["rebuilding"], got["total"]) == (0, 0, 12)


def test_a_picture_that_fails_is_counted_and_never_stops_the_rest(bank, tmp_path):
    spec = _board(tmp_path)
    spec["preview:broken"] = b"bad bytes"
    got = image_index.refresh(bank, EMBEDDER, pictures=_pictures(tmp_path / "pics", spec))
    assert got["embedded"] == 12 and got["failed"] == 1


def test_a_refresh_gives_way_between_steps_and_keeps_what_it_wrote(bank, tmp_path, monkeypatch):
    monkeypatch.setattr(image_index, "STEP", 4)
    pics = _pictures(tmp_path / "pics", _board(tmp_path))
    asked = iter([False, False, True])
    with pytest.raises(image_index.RefreshStopped):
        image_index.refresh(bank, EMBEDDER, pictures=pics, should_stop=lambda: next(asked))
    assert image_index.status(bank)["pictures"] == 8, "two steps written, the third gave way"
    assert image_index.refresh(bank, EMBEDDER, pictures=pics)["embedded"] == 4


def test_with_no_image_encoder_a_refresh_only_drops_what_is_gone(bank, tmp_path):
    pics = _pictures(tmp_path / "pics", _board(tmp_path))
    image_index.refresh(bank, EMBEDDER, pictures=pics)
    got = image_index.refresh(bank, None, pictures=pics[:10])
    assert (got["embedded"], got["removed"], got["total"]) == (0, 2, 10)


# --------------------------------------------------------------------------- search


def test_a_query_finds_the_pictures_it_describes_and_none_for_nothing_pictured(bank, tmp_path):
    image_index.refresh(bank, EMBEDDER, pictures=_pictures(tmp_path / "pics", _board(tmp_path)))
    hits = image_index.search(bank, "red", top_k=5, embed_fn=text_embed)
    assert [h["key"].split(":")[1].split("-")[0] for h in hits] == ["red"] * 3
    assert all(h["score"] >= image_index.LIFT_MIN for h in hits)
    assert hits[0]["metadata"]["thumb"].startswith("/entities/") and hits[0]["metadata"]["source"] == "preview"
    assert image_index.search(bank, "tax form", top_k=5, embed_fn=text_embed) == [], \
        "a query about nothing pictured is answered with nothing, not its nearest picture"


def test_the_stored_mean_gives_a_querys_exact_mean_cosine(bank, tmp_path):
    pics = _pictures(tmp_path / "pics", _board(tmp_path))
    image_index.refresh(bank, EMBEDDER, pictures=pics)
    conn = image_index._connect(bank)
    try:
        _n, mu = image_index._read_moments(conn, bank)
        x = image_index._all_vectors(conn)
    finally:
        conn.close()
    q = text_embed(["red"])[0]
    assert float(q @ mu) == pytest.approx(float((x @ q).mean()), abs=1e-5)


def test_search_never_loads_the_image_encoder(bank, tmp_path, monkeypatch):
    from api.services import vision_embedder

    image_index.refresh(bank, EMBEDDER, pictures=_pictures(tmp_path / "pics", _board(tmp_path)))

    def boom(*a, **k):
        raise AssertionError("the image encoder was loaded to search")

    monkeypatch.setattr(vision_embedder, "get", boom)
    monkeypatch.setattr(vision_embedder.VisionEmbedder, "_load", boom)
    assert image_index.search(bank, "blue", embed_fn=text_embed)


def test_no_table_no_hits(bank):
    assert image_index.search(bank, "red", embed_fn=text_embed) == []
    assert image_index.status(bank) == {"pictures": 0}


def test_the_text_reembed_never_counts_the_picture_table(bank, tmp_path, monkeypatch):
    from api.services import embedding_models
    from api.services.vector_index import SqliteVecIndexer

    image_index.refresh(bank, EMBEDDER, pictures=_pictures(tmp_path / "pics", _board(tmp_path)))
    assert "images" in SqliteVecIndexer(bank).table_models()
    monkeypatch.setattr(embedding_models, "build_model", lambda *a, **k: "some/text-model")
    monkeypatch.setattr(embedding_models, "is_available", lambda *a, **k: True)
    assert embedding_models.pending_switch(bank, settings=None) is None, \
        "the picture table is EmbeddingGemma 2's by construction, never a text model switch still to do"


# --------------------------------------------------------------------------- the doors


def test_search_route_serves_image_hits_in_hybrid_only(bank, tmp_path, monkeypatch):
    image_index.refresh(bank, EMBEDDER, pictures=_pictures(tmp_path / "pics", _board(tmp_path)))
    resp = search_service.search(bank, "green", kinds=search_service.parse_kinds("pictures"), mode="hybrid",
                                 embed_fn=text_embed)
    images = [h for h in resp.results if h.kind == "image"]
    assert len(images) == 3 and images[0].type == "image" and images[0].image_source == "preview"
    assert images[0].thumbnail and images[0].subject_id.startswith("green")
    dumped = images[0].model_dump(by_alias=True)
    assert {"thumbnail", "imageSource"} <= set(dumped), "additive camelCase fields"

    def boom(*a, **k):
        raise AssertionError("the prefix pass reached the picture index")

    monkeypatch.setattr(image_index, "search", boom)
    assert search_service.search(bank, "green", kinds=("image",), mode="prefix").results == []


def test_the_default_search_kinds_never_include_pictures():
    assert "image" not in search_service.parse_kinds(None)
    assert search_service.parse_kinds("entities,images") == ["entity", "image"]


def test_recall_shows_pictures_on_a_local_door_and_never_on_the_remote_one(bank, tmp_path, monkeypatch):
    from api.services import mcp_tools

    rows = [{"key": "still:abcdefghijk", "score": 0.2, "cosine": 0.5, "z": 3.0,
             "metadata": {"source": "still", "title": "A video", "episode_id": "ep_2026-10-01_001",
                          "day": "2026-10-01", "video_id": "abcdefghijk",
                          "thumb": "/sources/watch-history/days/ep_2026-10-01_001/videos/abcdefghijk/thumbnail"}}]
    monkeypatch.setattr(image_index, "search", lambda *a, **k: rows)
    lines = mcp_tools._picture_lines(bank, "a video", None)
    assert len(lines) == 1 and "watched on 2026-10-01 (ep_2026-10-01_001)" in lines[0]
    assert "/sources/watch-history/days/" in lines[0]

    seen = []
    monkeypatch.setattr(mcp_tools, "_picture_lines", lambda *a, **k: seen.append(1) or ["- a picture"])
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

    remote = str(mcp_tools.recall(Ctx(True), "alpha"))
    assert seen == [] and "Pictures that match" not in remote
    local = str(mcp_tools.recall(Ctx(False), "alpha"))
    assert seen == [1] and "Pictures that match" in local


# --------------------------------------------------------------------------- the picture child


@pytest.fixture
def picture_child(tmp_path, monkeypatch):
    monkeypatch.setenv(embed_worker.ENV, "on")
    monkeypatch.setattr(embed_worker, "VISION_FACTORY", "api.tests.embed_worker_stub:make_vision")
    pidfile = tmp_path / "pids"
    monkeypatch.setenv("EMBED_STUB_PIDFILE", str(pidfile))
    embed_worker.shutdown()
    yield pidfile
    embed_worker.shutdown()


def _pids(pidfile):
    return [int(line.split()[0]) for line in pidfile.read_text().splitlines()]


def test_pictures_embed_in_a_child_with_a_nan_row_for_a_bad_one(picture_child, monkeypatch):
    import os

    from api.tests.embed_worker_stub import picture_vector

    monkeypatch.setattr(embed_worker, "IMAGE_BATCH", 3)
    blobs = [b"red:1", b"bad", b"blue:2", b"green:3"]
    out = embed_worker.images("google/embeddinggemma-2")(blobs)
    assert out.shape == (4, 768)
    assert np.allclose(out[0], picture_vector(b"red:1")) and np.isnan(out[1]).all()
    assert os.getpid() not in _pids(picture_child), "never in the backend's own process"
    assert [int(line.split()[1]) for line in picture_child.read_text().splitlines()] == [3, 1]


def test_a_picture_child_over_its_memory_ceiling_exits_and_the_next_call_starts_another(picture_child, monkeypatch):
    monkeypatch.setattr(embed_worker, "VISION_MEMORY_MB", 1)   # any child is over 1 MB: it exits after each request
    embed = embed_worker.images("google/embeddinggemma-2")
    embed([b"red:1"])
    embed([b"blue:2"])
    pids = _pids(picture_child)
    assert len(pids) == 2 and pids[0] != pids[1], "the ceiling replaced the child between requests"


def test_the_design_board_embeds_its_pictures_in_the_child(monkeypatch):
    from api.services import design_index, onnx_embedder, vision_embedder

    class FakeVision:
        model_id = onnx_embedder.PREFERRED_ID

        def embed(self, data):
            raise AssertionError("embedded in the backend")

        def embed_text(self, texts, is_query=True):
            return np.zeros((len(texts), 4))

    asked = []
    monkeypatch.setattr(vision_embedder, "get", lambda environ=None: FakeVision())
    monkeypatch.setattr(embed_worker, "enabled", lambda environ=None: True)
    monkeypatch.setattr(embed_worker, "images", lambda model: (lambda blobs: asked.append(model) or np.ones((1, 4))))
    emb = design_index.default_embedders({})
    assert np.allclose(emb.image(b"png"), np.ones(4)) and asked == [onnx_embedder.PREFERRED_ID]


# --------------------------------------------------------------------------- what is indexed


def test_sources_finds_previews_watched_stills_and_capture_thumbnails(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CICADA_HOME", str(home))
    bank = tmp_path / "bank"
    (bank / "entities").mkdir(parents=True)
    (bank / "episodes").mkdir()
    previews = home / "previews" / "bank"
    (previews / "watched").mkdir(parents=True)
    # A saved link's stored preview.
    (bank / "entities" / "saved-page.md").write_text(
        "---\nname: Saved page\ntype: media\nurl: https://example.com/a\n---\nBody.\n")
    (previews / "saved-page.jpg").write_bytes(b"red:preview")
    (previews / "saved-page.json").write_text(json.dumps({"hit": {"key": "k", "ext": "jpg"}}))
    # A watched day whose still was stored when the person opened it; a day with no stored still adds nothing.
    vid = "abcdefghijk"
    (bank / "episodes" / "ep_2026-10-01_001.md").write_text(
        "---\nid: ep_2026-10-01_001\norigin: youtube-history\nsource: watch-history\nwatched_on: '2026-10-01'\n"
        f"watched:\n- url: https://www.youtube.com/watch?v={vid}\n  title: A video\n"
        "- url: https://www.youtube.com/watch?v=zzzzzzzzzzz\n  title: Never opened\n---\nDay.\n")
    (previews / "watched" / f"{vid}.jpg").write_bytes(b"blue:still")
    (previews / "watched" / f"{vid}.json").write_text(json.dumps({"hit": {"key": "k", "ext": "jpg"}}))
    # A saved site's newest capture with an in-bank thumbnail.
    thumb = bank / "assets" / "captures" / "0123456789abcdef.jpg"
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(b"green:thumb")
    (bank / "captures" / "site-page").mkdir(parents=True)
    (bank / "captures" / "site-page" / "20261001T100000Z-abc123.md").write_text(
        "---\ncaptured_at: '2026-10-01T10:00:00Z'\ntitle: Site\nthumb:\n  file: assets/captures/0123456789abcdef.jpg\n"
        "  sha256: 0123456789abcdef0123\n---\nCapture.\n")
    got = {p.key: p for p in image_index.sources(bank)}
    assert set(got) == {"preview:saved-page", f"still:{vid}", "capture:site-page"}
    assert got[f"still:{vid}"].episode_id == "ep_2026-10-01_001" and got[f"still:{vid}"].day == "2026-10-01"
    assert got["capture:site-page"].thumb == "/explore/captures/site-page/20261001T100000Z-abc123/thumb"
    assert got["preview:saved-page"].thumb.startswith("/entities/saved-page/preview")


def test_start_refresh_does_nothing_without_the_image_encoder(tmp_path, monkeypatch):
    from api.services import vision_embedder

    monkeypatch.setattr(vision_embedder, "folder", lambda environ=None: None)
    assert image_index.start_refresh(tmp_path) is False


def test_the_prompt_hook_never_reaches_the_picture_index(tmp_path, monkeypatch):
    """The hook's 300 ms: its legs are its own (`hook_recall`), and no picture search is among them."""
    import inspect

    from api.services import hook_recall

    assert "image_index" not in inspect.getsource(hook_recall)
