"""Design taste (owner, 2026-10-14): the board of looks the person likes — the store, the palette, the image encoder's
plumbing, the derived index, the routes, the MCP tools and the image model's download.

Synthetic only: made-up pages drawn by `demo_pictures.website`, example.com links, placeholder names. No model is
downloaded: Core ML and the embedders are faked; the one test that runs the real image encoder is opt-in
(`CICADA_REAL_VISION=1`, and the encoder already installed by the person's own click)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zlib
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from _synthetic_bank import _bank
from api.services import (coreml_embedder, demo_guard, demo_pictures, design_index, design_palette, design_refs,
                          image_decode, markdown_parser, model_fetch, vision_embedder)

NOW = datetime(2026, 10, 14, 10, 31, 2, tzinfo=timezone.utc)
SECRET = "sk-" + "A1b2C3d4E5f6G7h8J9k0"
DARK = demo_pictures.website((20, 22, 28), (29, 32, 41), (226, 230, 240), (124, 156, 255))
LIGHT = demo_pictures.website((255, 255, 255), (242, 244, 255), (17, 24, 39), (59, 91, 253), dense=True)
WARM = demo_pictures.website((246, 241, 231), (237, 229, 214), (43, 38, 32), (200, 85, 61), rounded=2)
needs_sips = pytest.mark.skipif(not image_decode.available(), reason="macOS's sips decodes images here")


def _png_mean(data: bytes) -> np.ndarray:
    """Mean RGB of one of our own synthetic PNGs (8-bit RGB, filter 0) — the fakes' decoder, no sips needed."""
    i, width, height, idat = 8, 0, 0, b""
    while i < len(data):
        n = int.from_bytes(data[i:i + 4], "big")
        tag, body = data[i + 4:i + 8], data[i + 8:i + 8 + n]
        if tag == b"IHDR":
            width, height = int.from_bytes(body[:4], "big"), int.from_bytes(body[4:8], "big")
        elif tag == b"IDAT":
            idat += body
        i += 12 + n
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(height, 1 + width * 3)[:, 1:]
    return raw.reshape(height, width, 3).reshape(-1, 3).mean(axis=0) / 255.0


def _fake_embedders(model: str = "fake/eg2:768") -> design_index.Embedders:
    """A two-axis space: how dark, how light — pictures by their mean luminance, words by what they say."""
    def image(data: bytes) -> np.ndarray:
        lum = float(_png_mean(data) @ np.array([0.2126, 0.7152, 0.0722]))
        return np.array([1 - lum, lum, 0.05], dtype=np.float32)

    def text(texts, is_query):
        out = []
        for t in texts:
            t = t.lower()
            dark = sum(w in t for w in ("dark", "night", "black", "moody"))
            light = sum(w in t for w in ("light", "white", "bright", "airy"))
            out.append([dark + 0.01, light + 0.01, 0.3])
        return np.asarray(out, dtype=np.float32)

    return design_index.Embedders(model=model, image=image, text=text)


@pytest.fixture
def bank(tmp_path):
    return _bank(tmp_path, git=False)


def _add(bank, image=DARK, **kw):
    kw.setdefault("url", "https://dashboard.example.com/overview")
    kw.setdefault("note", "Calm dark panels and one soft blue action.")
    kw.setdefault("now", NOW)
    kw.setdefault("look", ([{"hex": "#14161c", "share": 0.7}], ["dark", "muted"]))
    return design_refs.add_ref(bank, image=image, **kw)


# --------------------------------------------------------------------------- the store


def test_a_reference_is_one_markdown_file_and_its_screenshot_in_the_bank(bank):
    before = {p.name: p.read_bytes() for p in (bank / "entities").iterdir()}
    result = _add(bank, title="Quiet dashboard", snippets=[{"lang": "css", "code": "body { font-family: 'Inter', "
                                                            "sans-serif; padding: 12px; color: #1F2430 }"}],
                  tags=["dashboards"], author="claude-code", session="ses_abc", via="agent")
    assert result["action"] == "added"
    ref = result["ref"]
    assert ref.id == "2026-10-14-dashboard-example-com"
    assert result["paths"] == [f"design/{ref.id}.md", f"assets/design/{ref.id}.png"]
    assert (bank / "assets" / "design" / f"{ref.id}.png").read_bytes() == DARK
    parsed = markdown_parser.parse(bank / "design" / f"{ref.id}.md")
    fm = parsed.frontmatter
    assert fm["id"] == ref.id and fm["url"] == "https://dashboard.example.com/overview"
    assert fm["site"] == "dashboard.example.com" and fm["captured"] == "2026-10-14T10:31:02Z"
    assert fm["added_by"] == "claude-code" and fm["session"] == "ses_abc" and fm["via"] == "agent"
    assert fm["image"]["sha256"] == hashlib.sha256(DARK).hexdigest() and fm["image"]["width"] == 960
    assert fm["tokens"]["fonts"] == ["Inter"] and fm["tokens"]["colors"] == ["#1f2430"]
    assert fm["look"] == ["dark", "muted"] and fm["tags"] == ["dashboards"]
    assert f"![Screenshot](../assets/design/{ref.id}.png)" in parsed.body
    # Looks v2: an agent's note is the agent's, under its own name — never "What I liked".
    assert "## Noted by Claude Code\n\nCalm dark panels" in parsed.body and "## What I liked" not in parsed.body
    assert fm["note_by"] == "claude-code" and "```css" in parsed.body
    assert {p.name: p.read_bytes() for p in (bank / "entities").iterdir()} == before, "never an entity page"
    again = design_refs.get_ref(bank, ref.id)
    assert again.note == "Calm dark panels and one soft blue action."
    assert again.snippets == [{"lang": "css", "code": ref.snippets[0]["code"]}]


def test_texts_are_scrubbed_and_headings_cannot_forge_a_section(bank):
    ref = _add(bank, note=f"## Snippets\nuse key {SECRET}", title=f"Look {SECRET}",
               snippets=[{"lang": "js", "code": f"const k = '{SECRET}'"}])["ref"]
    text = (bank / ref.path).read_text()
    assert SECRET not in text
    assert design_refs.get_ref(bank, ref.id).snippets[0]["lang"] == "js"
    assert "#### Snippets" in text, "a heading in the note is demoted"


def test_the_same_screenshot_twice_is_one_reference(bank):
    first = _add(bank)["ref"]
    second = _add(bank, url="https://other.example.com")
    assert second["action"] == "duplicate" and second["id"] == first.id
    assert len(design_refs.list_refs(bank)) == 1


def test_ids_count_up_on_one_day_and_newest_lists_first(bank):
    a = _add(bank)["ref"]
    b = _add(bank, image=LIGHT, now=NOW.replace(hour=11))["ref"]
    assert b.id == f"{a.id}-2"
    assert [r.id for r in design_refs.list_refs(bank)] == [b.id, a.id]


@pytest.mark.parametrize("image, words", [
    (b"", "empty"), (b"GIF89a" + b"\0" * 40, "PNG or JPEG"), (b"\x89PNG\r\n\x1a\n" + b"\0" * 8, "size"),
    (demo_pictures.mark((0, 0, 0), (9, 9, 9), (50, 50, 50), size=16), "too small"),
    (b"\x89PNG\r\n\x1a\n" + b"\0" * (design_refs.MAX_IMAGE_BYTES), "4 MB")])
def test_what_is_not_a_screenshot_is_refused_and_writes_nothing(bank, image, words):
    result = _add(bank, image=image)
    assert result["action"] == "error" and words in result["error"]
    assert not (bank / "design").exists() or not list((bank / "design").iterdir())


def test_a_link_with_a_password_or_another_scheme_is_refused(bank):
    assert _add(bank, url="https://me:pw@example.com")["action"] == "error"
    assert _add(bank, url="file:///etc/hosts")["action"] == "error"
    assert _add(bank, url=None)["ref"].id == "2026-10-14-look"


def test_a_reference_may_point_at_a_page_but_never_makes_one(bank):
    assert _add(bank, entity="alpha-project")["ref"].entity == "alpha-project"
    ref = _add(bank, image=LIGHT, entity="no-such-page")["ref"]
    assert ref.entity is None and not (bank / "entities" / "no-such-page.md").exists()


def test_an_agent_removes_only_what_it_added_and_the_person_anything(bank):
    mine = _add(bank, author="user")["ref"]
    theirs = _add(bank, image=LIGHT, author="claude-code")["ref"]
    assert design_refs.remove_ref(bank, mine.id, author="codex")["action"] == "error"
    assert design_refs.remove_ref(bank, theirs.id, author="claude-code")["action"] == "removed"
    out = design_refs.remove_ref(bank, mine.id, author="user")
    assert out["action"] == "removed" and out["paths"] == [mine.path, mine.image_path]
    assert design_refs.list_refs(bank) == [] and not list((bank / "assets" / "design").iterdir())


def test_a_hand_edited_reference_still_reads(bank):
    ref = _add(bank)["ref"]
    path = bank / ref.path
    path.write_text(path.read_text().replace("Calm dark panels", "Edited by hand: calm panels"))
    assert design_refs.get_ref(bank, ref.id).note.startswith("Edited by hand")
    assert design_refs.get_ref(bank, "../entities/alpha-project") is None


# --------------------------------------------------------------------------- what a look is made of


def test_the_palette_is_deterministic_ground_first_then_by_salience():
    img = np.zeros((120, 200, 3), np.uint8)
    img[:] = (20, 24, 32)
    img[:30] = (250, 250, 250)
    img[60:80, 20:120] = (255, 90, 40)
    first = design_palette.palette(img)
    assert first == design_palette.palette(img.copy())
    # Looks v2: the ground, then salience (saturation and contrast), not area — the orange outranks the larger white.
    assert [c["hex"] for c in first] == ["#141820", "#ff5a28", "#fafafa"]
    assert [c["role"] for c in first] == ["ground", "accent", "ink"]
    assert abs(sum(c["share"] for c in first) - 1.0) < 0.01
    assert design_palette.describe(first)[:2] == ["dark", "vivid"] and "orange" in design_palette.describe(first)


def test_css_tokens_read_fonts_colours_and_spacing_from_what_was_selected():
    tokens = design_palette.css_tokens(
        "<div style=\"font-family: 'Inter', system-ui, sans-serif; padding: 12px 24px; color:#1F2430\">x</div>"
        ".a{font-family:Georgia,serif;font-size:18px;border-radius:8px;gap:1.5rem;background:rgba(255, 90, 40, .9)}"
        ".b{font-family: var(--brand), Georgia}")
    assert tokens["fonts"] == ["Georgia", "Inter"] and "serif" in tokens["generic"]
    assert tokens["colors"] == ["#1f2430", "#ff5a28"] and tokens["font_sizes"] == ["18px"]
    assert set(tokens["spacing"]) == {"12px", "24px", "1.5rem"} and tokens["radii"] == ["8px"]


def test_a_bitmap_parses_in_either_row_order_with_alpha_over_white():
    import struct

    def bmp(width, height, pixels: bytes, bpp: int, top_down: bool, compression=0, masks=b""):
        stride = (width * bpp // 8 + 3) & ~3
        rows = b"".join(pixels[i * width * bpp // 8:(i + 1) * width * bpp // 8].ljust(stride, b"\0")
                        for i in range(height))
        header_size = 40 + len(masks)
        dib = struct.pack("<IiiHHIIiiII", header_size, width, -height if top_down else height, 1, bpp,
                          compression, len(rows), 0, 0, 0, 0) + masks
        offset = 14 + len(dib)
        return b"BM" + struct.pack("<IHHI", offset + len(rows), 0, 0, offset) + dib + rows

    two = bytes([0, 0, 255, 255, 0, 0])            # BGR: red, blue
    px = image_decode.parse_bmp(bmp(2, 1, two, 24, True))
    assert px.tolist() == [[[255, 0, 0], [0, 0, 255]]]
    stacked = image_decode.parse_bmp(bmp(1, 2, bytes([0, 0, 255, 0, 255, 0]), 24, False))
    assert stacked.tolist() == [[[0, 255, 0]], [[255, 0, 0]]], "bottom-up rows are flipped"
    masks = struct.pack("<IIII", 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000) + b"\0" * 52
    half = image_decode.parse_bmp(bmp(1, 1, bytes([0, 0, 255, 128]), 32, True, compression=3, masks=masks))
    assert half.tolist() == [[[255, 127, 127]]]
    with pytest.raises(image_decode.DecodeError):
        image_decode.parse_bmp(b"not a bitmap")


@needs_sips
def test_the_decoder_never_enlarges_and_reads_a_real_png():
    px = image_decode.decode(DARK, max_side=4096)
    assert px.shape == (600, 960, 3)
    small = image_decode.decode(DARK, max_side=96)
    assert small.shape == (60, 96, 3)
    assert image_decode.decode(DARK, size=(48, 96)).shape == (96, 48, 3)
    colours, words = design_refs.read_look(DARK)
    assert int(colours[0]["hex"][1:3], 16) < 40 and colours[0]["share"] > 0.5 and words[0] == "dark"


# --------------------------------------------------------------------------- the image encoder's plumbing


@pytest.mark.parametrize("size", [(960, 600), (1440, 900), (390, 844), (3000, 200), (10, 10)])
def test_a_planned_size_is_in_48_px_steps_within_the_budget(size):
    w, h = vision_embedder.plan_size(*size)
    assert w % 48 == 0 and h % 48 == 0 and w >= 48 and h >= 48
    assert (w // 48) * (h // 48) <= vision_embedder.BUDGET
    assert (w // 16) * (h // 16) <= vision_embedder.FUNCTIONS[vision_embedder.BUDGET]


def test_the_feed_cuts_row_major_patches_with_positions_and_a_3x3_pool():
    w, h = 96, 48                                   # 6 × 3 patches, 2 groups
    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[:, 48:] = 255                              # the right group is white
    table = np.zeros((2, 1024, 768), np.float16)
    table[0, :, 0] = np.arange(1024)               # x lands in column 0
    table[1, :, 1] = np.arange(1024)               # y lands in column 1
    feed, real = vision_embedder.inputs(rgb, table)
    assert real == 2
    assert feed["patches"].shape == (1, 630, 768) and feed["pool"].shape == (70, 630)
    assert feed["valid"][0, :18].all() and not feed["valid"][0, 18:].any()
    assert feed["positions"][0, 7].tolist() == [1, 1] and feed["positions"][0, 18].tolist() == [-1, -1]
    assert feed["position_embeddings"][0, 7, :2].tolist() == [1, 1]
    pooled = feed["pool"] @ feed["patches"][0]
    assert np.allclose(pooled[0], 0) and np.allclose(pooled[1], 1) and np.allclose(pooled[2:], 0)
    assert np.allclose(feed["pool"][:2].sum(axis=1), 1.0), "each token averages its nine patches"


class _FakeText:
    spec = SimpleNamespace(id="google/embeddinggemma-2:768")

    def token_rows(self, ids):
        return np.full((len(ids), 512), 0.0, np.float16)

    def embed_rows(self, rows, *, wait=None):
        v = np.concatenate([np.asarray(rows, np.float32).mean(0), np.zeros(256, np.float32)])
        return v / max(np.linalg.norm(v), 1e-12)

    def __call__(self, texts, *, is_query=False):
        return np.ones((len(texts), 768), np.float32) / np.sqrt(768)


class _FakeVision:
    seen: list = []

    def __init__(self, path, compute_units=None, function_name=""):
        _FakeVision.seen.append((Path(path).name, compute_units, function_name))

    def predict(self, feed):
        _FakeVision.seen.append({k: v.dtype for k, v in feed.items()})
        pooled = feed["pool"].astype(np.float32) @ feed["patches"][0].astype(np.float32)   # [70, 768]
        return {"image_tokens": pooled[None, :, :512]}


@needs_sips
def test_an_image_runs_the_vision_function_on_the_gpu_and_the_text_model_embeds_its_tokens(tmp_path, monkeypatch):
    folder = tmp_path / "embeddinggemma-2"
    (folder / vision_embedder.COMPILED).mkdir(parents=True)
    (folder / vision_embedder.COMPILED / "metadata.json").write_text(json.dumps([{"inputSchema": [
        {"name": "patches", "dataType": "Float16"}, {"name": "positions", "dataType": "Int32"}]}]))
    np.zeros((2, 1024, 768), np.float16).tofile(folder / vision_embedder.POSITIONS)
    monkeypatch.setattr(coreml_embedder, "import_coremltools", lambda: SimpleNamespace(
        ComputeUnit=SimpleNamespace(CPU_AND_GPU="gpu"), models=SimpleNamespace(CompiledMLModel=_FakeVision)))
    _FakeVision.seen = []
    emb = vision_embedder.VisionEmbedder(folder, _FakeText())
    dark, light = emb.embed(DARK), emb.embed(LIGHT)
    assert dark.shape == (768,) and abs(float(np.linalg.norm(dark)) - 1) < 1e-5
    assert _FakeVision.seen[0] == (vision_embedder.COMPILED, "gpu", "vision_70")
    dtypes = _FakeVision.seen[1]
    assert dtypes["patches"] == np.float16 and dtypes["positions"] == np.int32 and dtypes["pool"] == np.float16
    assert float(dark @ light) < 0.999, "two different pages are two different vectors"


# --------------------------------------------------------------------------- the index and search


def test_words_alone_answer_when_no_model_is_here(bank):
    _add(bank, note="Serif headlines on warm paper", title="Essay page", image=WARM,
         look=([], ["light", "muted"]), url="https://journal.example.com")
    _add(bank, image=DARK)
    out = design_index.search(bank, query="serif paper", emb=None)
    assert out["mode"] == "words" and out["missing"] == ["model"]
    assert len(out["results"]) == 1 and out["results"][0]["legs"] == ["words"]
    assert design_refs.get_ref(bank, out["results"][0]["id"]).title == "Essay page"
    assert design_index.search(bank, query="dark", emb=None)["results"][0]["id"] == "2026-10-14-dashboard-example-com"
    assert not design_index.index_path(bank).exists() or design_index.status(bank) == {"images": 0, "notes": 0}


def test_a_sentence_finds_screenshots_through_the_shared_space(bank):
    dark = _add(bank, image=DARK, note="Panels.", look=([], []))["ref"]
    light = _add(bank, image=LIGHT, note="Cards.", look=([], []), url="https://launch.example.com")["ref"]
    out = design_index.search(bank, query="a moody night dashboard", emb=_fake_embedders())
    assert out["results"][0]["id"] == dark.id and "picture" in out["results"][0]["legs"]
    out = design_index.search(bank, query="bright airy", emb=_fake_embedders())
    assert out["results"][0]["id"] == light.id
    assert design_index.status(bank) == {"images": 2, "notes": 2}


def test_a_word_search_never_returns_the_whole_board(bank):
    dark = _add(bank, image=DARK, note="Moody panels.", look=([], []))["ref"]
    light = _add(bank, image=LIGHT, note="Bright cards.", look=([], []), url="https://launch.example.com")["ref"]
    warm = _add(bank, image=WARM, note="Serif headlines.", look=([], []), url="https://journal.example.com")["ref"]
    out = design_index.search(bank, query="night", emb=_fake_embedders())
    ids = [r["id"] for r in out["results"]]
    assert ids[0] == dark.id and light.id not in ids, "a meaning leg keeps only hits close to its best"
    out = design_index.search(bank, query="serif", emb=_fake_embedders())
    assert "words" in out["results"][0]["legs"]
    assert out["results"][0]["id"] == warm.id, "what the words found ranks above what only a meaning leg found"


def test_while_sleep_runs_a_search_embeds_nothing_new(bank):
    _add(bank, image=DARK, note="Moody panels.", look=([], ["dark"]))
    out = design_index.search(bank, query="dark", emb=_fake_embedders(), embed=False)
    assert design_index.status(bank) == {"images": 0, "notes": 0}
    assert out["results"] and out["results"][0]["legs"] == ["words"]


def test_an_example_picture_finds_the_look_like_it(bank):
    dark = _add(bank, image=DARK, look=([], []))["ref"]
    _add(bank, image=LIGHT, look=([], []), url="https://launch.example.com")
    similar = demo_pictures.website((24, 26, 33), (33, 36, 45), (220, 224, 236), (240, 120, 90))
    out = design_index.search(bank, image=similar, emb=_fake_embedders())
    assert out["results"][0]["id"] == dark.id and out["results"][0]["legs"] == ["picture"]
    text_only = design_index.Embedders(model="fake/eg2:768", text=_fake_embedders().text)
    assert "image_model" in design_index.search(bank, image=similar, emb=text_only)["missing"]


def test_the_index_is_a_table_of_the_one_meaning_index_and_follows_the_board(bank, tmp_path):
    """Meaning index 2 (2026-10-28): the board's rows live in the bank's derived `vector_index.db` (git-ignored,
    never copied or exported), and no other file of its own."""
    from api.services import bank_registry

    a = _add(bank, image=DARK, look=([], []))["ref"]
    _add(bank, image=LIGHT, look=([], []), url="https://launch.example.com")
    design_index.refresh(bank, _fake_embedders())
    path = design_index.index_path(bank)
    assert path == bank / "vector_index.db" and path.name in bank_registry.DERIVED_ARTIFACTS
    assert not design_index.legacy_path(bank).exists()
    assert not any(p.suffix in (".sqlite", ".db") for p in bank.rglob("*") if "design" in p.parts)
    design_refs.remove_ref(bank, a.id)
    design_index.refresh(bank, _fake_embedders())
    assert design_index.status(bank) == {"images": 1, "notes": 1}
    counts = design_index.refresh(bank, _fake_embedders(model="fake/eg2-next:768"))
    assert counts == {"images": 1, "notes": 1, "failed": 0}, "a new model re-embeds every row"
    path.write_bytes(b"not a database")
    design_index.refresh(bank, _fake_embedders())
    assert design_index.status(bank)["images"] == 1, "a damaged index is rebuilt, never an error"


def test_the_boards_old_file_is_folded_into_the_one_index_once_and_deleted(bank):
    """Migration (meaning index 2): the rows of `$CICADA_HOME/design-index/<bank-id>.sqlite` move into the one index
    with their stamps, so nothing is re-embedded; the old file goes."""
    import sqlite3

    a = _add(bank, image=DARK, look=([], []))["ref"]
    old = design_index.legacy_path(bank)
    old.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(old)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('schema', ?)", (design_index.SCHEMA,))
    conn.execute("CREATE TABLE vectors (ref TEXT, kind TEXT, hash TEXT, model TEXT, dim INTEGER, vec BLOB, "
                 "PRIMARY KEY (ref, kind))")
    emb = _fake_embedders()
    vec = design_index._unit(emb.image(DARK))
    conn.execute("INSERT INTO vectors VALUES (?, 'image', ?, ?, ?, ?)",
                 (a.id, a.image["sha256"], emb.image_stamp, int(vec.size), vec.tobytes()))
    conn.commit()
    conn.close()
    assert design_index.status(bank) == {"images": 1, "notes": 0}, "moved, not re-embedded"
    assert not old.exists()
    counts = design_index.refresh(bank, emb)
    assert counts["images"] == 0 and counts["notes"] == 1, "the moved picture vector is current; only the note embeds"


def test_one_picture_that_will_not_embed_never_stops_the_rest(bank):
    _add(bank, image=DARK, look=([], []))
    _add(bank, image=LIGHT, look=([], []), url="https://launch.example.com")
    emb = _fake_embedders()
    good = emb.image
    emb.image = lambda data: (_ for _ in ()).throw(RuntimeError("bad")) if data == DARK else good(data)
    assert design_index.refresh(bank, emb) == {"images": 1, "notes": 2, "failed": 1}


def test_the_query_is_never_logged(bank):
    from loguru import logger

    _add(bank, image=DARK, look=([], []))
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(str(m)), level="DEBUG")
    try:
        emb = _fake_embedders()
        emb.text = lambda texts, q: (_ for _ in ()).throw(RuntimeError("down"))
        design_index.search(bank, query="zebra-secret-words", emb=emb)
    finally:
        logger.remove(sink)
    assert seen and not any("zebra-secret-words" in line for line in seen)


# --------------------------------------------------------------------------- the routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    monkeypatch.setattr(design_index, "default_embedders", lambda environ=None: _fake_embedders())
    monkeypatch.setattr(design_index, "refresh_in_background", lambda mp, **kw: False)
    with TestClient(main.app) as c:
        yield c, memory
    config.get_settings.cache_clear()


def _git(bank, *args) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], capture_output=True, text=True, check=True).stdout


def test_the_person_saves_a_look_and_it_is_committed_alone_as_them(client):
    c, bank = client
    r = c.post("/design", files={"image": ("shot.png", DARK, "image/png")},
               data={"url": "https://dashboard.example.com/overview", "note": "The calm panels.",
                     "snippets": json.dumps([{"lang": "css", "code": "body{font-family:Inter}"}]), "via": "drop"})
    assert r.status_code == 200, r.text
    ref = r.json()
    assert ref["site"] == "dashboard.example.com" and ref["note"] == "The calm panels." and ref["fonts"] == ["Inter"]
    assert ref["image"]["url"].startswith(f"/design/{ref['id']}/image?v=") and ref["addedByKind"] == "user"
    head = _git(bank, "log", "-1", "--format=%B")
    assert head.startswith("Design reference ") and "Cicada-Author: user" in head
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == [
        f"assets/design/{ref['id']}.png", f"design/{ref['id']}.md"]
    board = c.get("/design")
    assert board.status_code == 200 and [x["id"] for x in board.json()["refs"]] == [ref["id"]]
    assert "vision" in board.json() and board.json()["vision"]["installed"] is False
    assert c.get("/design", headers={"If-None-Match": board.headers["etag"]}).status_code == 304
    img = c.get(ref["image"]["url"])
    assert img.status_code == 200 and img.content == DARK and img.headers["content-type"] == "image/png"
    assert c.get(f"/design/{ref['id']}").json()["snippets"][0]["code"] == "body{font-family:Inter}"
    assert c.post("/design", files={"image": ("shot.png", DARK, "image/png")}).status_code == 409


def test_search_reranks_the_board_and_delete_commits_the_removal(client):
    c, bank = client
    dark = c.post("/design", files={"image": ("a.png", DARK, "image/png")}, data={"note": "Panels"}).json()
    light = c.post("/design", files={"image": ("b.png", LIGHT, "image/png")}, data={"note": "Cards"}).json()
    r = c.post("/design/search", data={"query": "dark night"})
    assert r.status_code == 200 and r.json()["results"][0]["id"] == dark["id"]
    r = c.post("/design/search", files={"image": ("q.png", LIGHT, "image/png")})
    assert r.json()["results"][0]["id"] == light["id"]
    assert c.post("/design/search", data={}).status_code == 400
    assert c.delete(f"/design/{dark['id']}").status_code == 200
    assert "deleted" in _git(bank, "log", "-1", "--format=%B")
    assert c.get(f"/design/{dark['id']}").status_code == 404
    assert c.delete(f"/design/{dark['id']}").status_code == 404


def test_a_demo_bank_refuses_a_screenshot(client):
    c, bank = client
    demo_guard.write_manifest(bank)
    r = c.post("/design", files={"image": ("shot.png", DARK, "image/png")})
    assert r.status_code == 409 and "demo" in r.json()["detail"]
    assert not (bank / "design").exists()


def test_a_demo_bank_refuses_a_removal_too(client):
    c, bank = client
    ref = c.post("/design", files={"image": ("shot.png", DARK, "image/png")}).json()
    demo_guard.write_manifest(bank)
    r = c.delete(f"/design/{ref['id']}")
    assert r.status_code == 409 and "demo" in r.json()["detail"]
    assert (bank / "design" / f"{ref['id']}.md").is_file()


def test_the_search_route_embeds_nothing_while_sleep_runs(client, monkeypatch):
    from api.services import sleep_cycle

    c, bank = client
    c.post("/design", files={"image": ("a.png", DARK, "image/png")}, data={"note": "dark panels"})
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    r = c.post("/design/search", data={"query": "dark"})
    assert r.status_code == 200 and r.json()["results"]
    assert design_index.status(bank) == {"images": 0, "notes": 0}


def test_a_bad_upload_says_why(client):
    c, _ = client
    r = c.post("/design", files={"image": ("x.gif", b"GIF89a" + b"\0" * 64, "image/gif")})
    assert r.status_code == 400 and "PNG or JPEG" in r.json()["detail"]
    r = c.post("/design", files={"image": ("x.png", DARK, "image/png")}, data={"snippets": "{not json"})
    assert r.status_code == 400


def test_the_image_model_is_its_own_click(client, monkeypatch):
    from api.services import embedding_models

    c, _ = client
    started = []
    monkeypatch.setattr(embedding_models, "neural_engine_supported", lambda: True)
    monkeypatch.setattr(embedding_models, "start_vision_download", lambda environ=os.environ: started.append(1) or True)
    r = c.post("/embeddings/install", json={"model": embedding_models.PREFERRED_ID, "part": "vision"})
    assert r.status_code == 202 and started == [1]
    assert r.json()["vision"]["downloadBytes"] > 300e6, "the text encoder comes first when it isn't here"
    assert c.post("/embeddings/install", json={"model": embedding_models.PREFERRED_ID, "part": "audio"}).status_code == 400


# --------------------------------------------------------------------------- the MCP tools


@pytest.fixture
def server(tmp_path, monkeypatch):
    from _stdio_server import stdio_server

    srv = stdio_server()
    memory = _bank(tmp_path)
    monkeypatch.setattr(srv, "get_memory_path", lambda: memory)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_2026-10-14_c0ffee00", "claude-code", None))
    monkeypatch.setattr(design_index, "default_embedders", lambda environ=None: _fake_embedders())
    return srv, memory


def test_an_agent_saves_a_screenshot_it_took_as_itself(server, tmp_path):
    srv, bank = server
    shot = tmp_path / "shots" / "page.png"
    shot.parent.mkdir()
    shot.write_bytes(DARK)
    out = srv.handle_tool("cicada_save_design", {"image_path": str(shot), "url": "https://dashboard.example.com",
                                                  "note": "The person likes the calm panels."})
    assert out.startswith("Saved 2026-") and "dashboard.example.com" in out
    head = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: claude-code" in head and "Cicada-Session: ses_2026-10-14_c0ffee00" in head
    ref = design_refs.list_refs(bank)[0]
    assert ref.added_by == "claude-code" and ref.via == "agent"
    found = srv.handle_tool("cicada_design_search", {"query": "dark"})
    assert ref.id in found and f"screenshot: {bank / ref.image_path}" in found
    listed = srv.handle_tool("cicada_design_search", {})
    assert "newest first (1 saved)" in listed


def test_the_agent_tool_refuses_what_it_must_not_read(server, tmp_path, monkeypatch):
    srv, bank = server
    home = Path(os.environ["HOME"])
    for where in (home / ".claude" / "projects" / "x.png", bank / "assets" / "y.png"):
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_bytes(DARK)
        out = srv.handle_tool("cicada_save_design", {"image_path": str(where), "note": "n"})
        assert out.startswith("Not saved: Cicada doesn't read pictures from that folder"), where
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    assert "isn't a PNG or JPEG" in srv.handle_tool("cicada_save_design", {"image_path": str(text), "note": "n"})
    assert "absolute path" in srv.handle_tool("cicada_save_design", {"image_path": "rel.png", "note": "n"})
    import base64

    out = srv.handle_tool("cicada_save_design", {"image_base64": base64.b64encode(LIGHT).decode(), "note": "n"})
    assert out.startswith("Saved ")
    demo_guard.write_manifest(bank)
    assert srv.handle_tool("cicada_save_design", {"image_base64": base64.b64encode(DARK).decode(),
                                                  "note": "n"}) == demo_guard.AGENT_REFUSAL


def test_a_remote_caller_never_names_a_path(tmp_path):
    from api.services import mcp_tools

    bank = _bank(tmp_path, git=False)
    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="rc_1", harness="claude-web", connector_id="c1")
    shot = tmp_path / "page.png"
    shot.write_bytes(DARK)
    assert "remote connection sends the picture itself" in mcp_tools.save_design(ctx, note="n", image_path=str(shot))


def test_the_board_tools_are_stdio_only_in_this_slice():
    from api.remote import catalog

    assert {"cicada_save_design", "cicada_design_search"} <= catalog.NEVER_REMOTE
    assert not ({"cicada_save_design", "cicada_design_search"} & set(catalog.TOOL_SCOPE))


# --------------------------------------------------------------------------- the image model's download


def _vision_payload(tmp_path) -> dict[str, bytes]:
    return {"position_embeddings.f16": np.zeros((2, 4, 768), np.float16).tobytes(),
            "EmbeddingGemma2Vision.mlpackage/Manifest.json": b"{}",
            "EmbeddingGemma2Vision.mlpackage/Data/com.apple.CoreML/model.mlmodel": b"mil-vision"}


def _fake_compile(stage: Path, package_name=None, compiled_name=None) -> None:
    import shutil

    package = package_name or coreml_embedder.PACKAGE
    (stage / (compiled_name or coreml_embedder.COMPILED)).mkdir()
    shutil.rmtree(stage / package)


def test_the_image_encoder_grafts_beside_the_text_encoder_verified_and_once(tmp_path, monkeypatch):
    from test_embeddinggemma2 import _Client, _fake_pins, _payload

    text = _payload(tmp_path)
    vision = _vision_payload(tmp_path)
    pins = _fake_pins(tmp_path, monkeypatch, text)
    pins["vision_files"] = [{"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                            for p, b in vision.items()]
    model_fetch.PINS.write_text(json.dumps(pins))
    monkeypatch.setattr(coreml_embedder, "supported", lambda: True)
    client = _Client({**text, **vision})
    out = model_fetch.install_vision(tmp_path / "models", client=client, compile_fn=_fake_compile, warm=False)
    assert (out / model_fetch.VISION_COMPILED).is_dir() and (out / model_fetch.POSITIONS).is_file()
    assert model_fetch.vision_installed(out) and (out / coreml_embedder.COMPILED).is_dir()
    assert not (out / model_fetch.VISION_PACKAGE).exists()
    assert not any(p.name.startswith(".") for p in (tmp_path / "models").iterdir()), "no staging left behind"
    assert sorted(u.rsplit("/abc123/", 1)[1] for u in client.urls) == sorted([*text, *vision])
    again = _Client({**text, **vision})
    model_fetch.install_vision(tmp_path / "models", client=again, compile_fn=_fake_compile, warm=False)
    assert again.urls == []


def test_a_tampered_image_encoder_installs_nothing_and_leaves_the_text_encoder(tmp_path, monkeypatch):
    from test_embeddinggemma2 import _Client, _fake_pins, _payload

    text = _payload(tmp_path)
    vision = _vision_payload(tmp_path)
    pins = _fake_pins(tmp_path, monkeypatch, text)
    pins["vision_files"] = [{"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                            for p, b in vision.items()]
    model_fetch.PINS.write_text(json.dumps(pins))
    monkeypatch.setattr(coreml_embedder, "supported", lambda: True)
    out = model_fetch.install(tmp_path / "models", client=_Client(text), compile_fn=_fake_compile, warm=False)
    bad = dict(vision, **{"position_embeddings.f16": b"\0" * len(vision["position_embeddings.f16"])})
    bad["position_embeddings.f16"] = bad["position_embeddings.f16"][:-1] + b"\1"
    with pytest.raises(model_fetch.FetchError):
        model_fetch.install_vision(tmp_path / "models", client=_Client({**text, **bad}), compile_fn=_fake_compile)
    assert not model_fetch.vision_installed(out) and model_fetch.installed_revision(out) == "abc123"
    assert not (out / model_fetch.POSITIONS).exists()
    assert not any(p.name.startswith(".") for p in (tmp_path / "models").iterdir())


def test_the_real_pins_name_the_image_encoder_apart_and_never_the_audio_one():
    pins = model_fetch.pins()
    vision = [f["path"] for f in pins["vision_files"]]
    assert all("Vision" in p or p == "position_embeddings.f16" for p in vision)
    assert not any("Audio" in f["path"] for f in pins["files"] + pins["vision_files"])
    assert all(len(f["sha256"]) == 64 and int(f["size"]) > 0 for f in pins["vision_files"])
    assert 300e6 < model_fetch.vision_total_bytes(pins) < 320e6


# --------------------------------------------------------------------------- the real encoder (opt-in)


@pytest.mark.skipif(os.environ.get("CICADA_REAL_VISION") != "1",
                    reason="opt-in: CICADA_REAL_VISION=1 with the image encoder installed by the person's click")
def test_real_encoder_puts_pictures_and_words_in_one_space():
    """Runs the installed EmbeddingGemma 2 image encoder on two made-up pages. Never downloads: it reads the real
    `$CICADA_REAL_VISION_HOME` (or `CICADA_HOME`) models folder, and skips when the encoder isn't there."""
    environ = dict(os.environ)
    if os.environ.get("CICADA_REAL_VISION_HOME"):
        environ["CICADA_HOME"] = os.environ["CICADA_REAL_VISION_HOME"]
    emb = vision_embedder.get(environ)
    if emb is None:
        pytest.skip("the image encoder isn't installed on this Mac")
    dark, light = emb.embed(DARK), emb.embed(LIGHT)
    assert dark.shape == (768,) and abs(float(np.linalg.norm(dark)) - 1) < 1e-3
    words = emb.embed_text(["a dark mode dashboard with a black background",
                            "a bright white landing page"], is_query=True)
    assert float(words[0] @ dark) > float(words[0] @ light) or float(words[1] @ light) > float(words[1] @ dark)



# --------------------------------------------------------------------------- the preprocessing stamp (2026-10-28)


def _counting(fp: str | None, model: str = "fake/eg2:768"):
    emb = _fake_embedders(model)
    calls = []
    image = emb.image

    def counted(data):
        calls.append(1)
        return image(data)

    return design_index.Embedders(model=model, image=counted, text=emb.text, image_fingerprint=fp), calls


def test_an_image_vector_re_embeds_only_when_the_preprocessing_really_changed(bank):
    _add(bank, image=DARK, look=([], []))
    emb, calls = _counting("aaaaaaaaaaaa")
    design_index.refresh(bank, emb)
    assert len(calls) == 1
    design_index.refresh(bank, emb)
    assert len(calls) == 1, "the same model and the same preprocessing: nothing re-embeds"
    moved, calls2 = _counting("bbbbbbbbbbbb")
    design_index.refresh(bank, moved)
    assert len(calls2) == 1, "a decoder that draws other pixels re-embeds the picture once"


def test_a_vector_stored_before_the_stamp_is_kept_while_the_pipeline_is_the_one_that_made_it(bank):
    _add(bank, image=DARK, look=([], []))
    design_index.refresh(bank, _fake_embedders())                       # the pre-stamp row: the bare model id
    kept, calls = _counting(vision_embedder.LEGACY_FINGERPRINT)
    design_index.refresh(bank, kept)
    assert calls == [], "adding the stamp re-embeds nothing"
    assert design_index.search(bank, image=DARK, emb=kept)["results"], "and the old vector is still searched"
    changed, calls = _counting("cccccccccccc")
    design_index.refresh(bank, changed)
    assert len(calls) == 1
