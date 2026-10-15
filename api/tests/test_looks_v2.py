"""Looks v2 (owner, 2026-10-15): a saved site's look is extracted properly and shown properly.

* the palette names the ground, then the accents by salience (saturation and contrast against the ground, not area),
  merges the colours the page declares, and a thin saturated line colour surfaces;
* the computed-token schema (``design_tokens``): one shape for the backend, the MCP tools and the docs, validated with
  bounds, hashed ``next/font`` names cleaned;
* author attribution: an agent's note is shown as the agent's ("Noted by …"), never as the person's words; the REST
  door takes the author;
* "Save its look": one ask on a saved link queues a design visit (the existing explore queue), and the visit keeps the
  landing picture as a Look with its computed type and colours even when the look has not changed.

Synthetic only: pictures drawn here, bob-example.org and example.com links, placeholder names."""
from __future__ import annotations

import json
import socket
import struct
import subprocess
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from _explore_fixtures import DARK, LIGHT, bank_with_sites, enable_reading
from _synthetic_bank import _bank
from api.services import (demo_pictures, design_index, design_palette, design_refs, design_tokens, explore_plan,
                          explore_queue, image_decode, markdown_parser, mcp_tools)

needs_sips = pytest.mark.skipif(not image_decode.available(), reason="macOS's sips decodes images here")
COBALT = (19, 66, 255)
OFF_WHITE = (250, 250, 251)
WASH = (221, 227, 248)
NEON = (57, 255, 20)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(self, address):
        if isinstance(address, tuple) and address and address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"looks opened a network connection to {address!r}")
        raise OSError("no network in this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def _png(img: np.ndarray) -> bytes:
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _ink_page() -> np.ndarray:
    """An editorial page in one cobalt ink on off-white: 1 px rules, a little ink text, two light-blue washes."""
    img = np.empty((900, 1440, 3), np.uint8)
    img[:] = OFF_WHITE
    img[120:160, 160:1280] = WASH
    img[520:548, :] = WASH
    for y in range(200, 880, 48):
        img[y, 80:1360] = COBALT                    # hairline rules, 1 px
    for x in range(160, 1280, 40):
        img[300:304, x:x + 22] = COBALT             # a few words of ink
    return img


def _neon_page() -> np.ndarray:
    img = np.empty((900, 1440, 3), np.uint8)
    img[:] = (13, 13, 18)
    img[200:226, 100:900] = (226, 226, 230)        # a light headline
    img[300:305, 100:700] = NEON                    # one neon underline, 0.2 % of the page
    return img


def _dist(hex_value: str, rgb) -> float:
    return float(np.linalg.norm(design_palette._vec(hex_value) - np.array(rgb, dtype=float)))


# --------------------------------------------------------------------------- the salience palette


def test_a_thin_saturated_line_surfaces_right_after_the_ground():
    img = _ink_page()
    colours = design_palette.palette(img)
    assert colours[0]["role"] == "ground" and _dist(colours[0]["hex"], OFF_WHITE) < 4 and colours[0]["share"] > 0.9
    assert colours[1]["hex"] == "#1342ff" and colours[1]["role"] == "accent", "the ink that is the look comes first"
    assert colours[1]["share"] < 0.02, "by salience, not area: it covers about 1 % of the page"
    wash = next(c for c in colours if _dist(c["hex"], WASH) < 4)
    assert wash["role"] == "wash"
    assert design_palette.palette(img.copy()) == colours, "same pixels, same palette"


def test_a_dark_page_with_one_neon_accent_puts_the_neon_first():
    colours = design_palette.palette(_neon_page())
    assert colours[0]["role"] == "ground" and colours[0]["hex"] == "#0d0d12"
    assert colours[1]["hex"] == "#39ff14" and colours[1]["role"] == "accent"
    assert next(c for c in colours if c["hex"] == "#e2e2e6")["role"] == "ink"
    assert design_palette.describe(colours)[:2] == ["dark", "vivid"] and "green" in design_palette.describe(colours)


def test_an_antialiased_edge_folds_into_its_colour_and_specks_are_not_colours():
    img = _ink_page()
    for y in (201, 249, 297):
        img[y, 80:1360] = (186, 196, 252)          # the half-covered row under three rules: a blend into the ground
    img[10:12, 10:12] = (255, 0, 0)                 # four red pixels: noise, never a colour
    hexes = [c["hex"] for c in design_palette.palette(img)]
    assert "#1342ff" in hexes[:2] and "#bac4fc" not in hexes and not any(_dist(h, (255, 0, 0)) < 30 for h in hexes)


def test_declared_colours_are_merged_marked_or_added():
    colours = design_palette.palette(_ink_page(), declared=["#1342FF", "rgb(9, 9, 9)", "#ff0066"])
    cobalt = next(c for c in colours if c["hex"] == "#1342ff")
    assert cobalt["declared"] is True and cobalt["share"] > 0
    pink = next(c for c in colours if c["hex"] == "#ff0066")
    assert pink["declared"] is True and pink["share"] == 0.0 and pink["role"] == "accent"
    assert len(colours) <= design_palette.MAX_COLOURS


@needs_sips
def test_through_the_decoder_the_cobalt_rule_still_surfaces():
    colours, words = design_refs.read_look(_png(_ink_page()))
    assert colours[0]["role"] == "ground" and words[0] == "light"
    accents = [c for c in colours if c["role"] == "accent"]
    assert accents and _dist(accents[0]["hex"], COBALT) < 40 and colours.index(accents[0]) == 1
    assert "blue" in words and "vivid" in words


# --------------------------------------------------------------------------- the token schema


NEXT_FONT_TOKENS = {
    "type": {
        "body": {"fontFamily": '"__Newsreader_a1b2c3", "__Newsreader_Fallback_a1b2c3", serif', "fontSize": "19px",
                 "fontWeight": "400", "lineHeight": "30.4px", "letterSpacing": "normal", "color": "rgb(19, 66, 255)"},
        "heading": {"family": "__Source_Serif_4_9f8e7d, Georgia, serif", "size": 56, "weight": "bold",
                    "line_height": "normal", "letter_spacing": "-0.02em", "color": "#1342FF"},
        "drop_cap": {"family": "__Newsreader_a1b2c3", "size": "88px", "color": "rgb(19, 66, 255)"},
        "caption": {"family": "ui-monospace, Menlo, monospace", "size": "2px"},
        "sidebar": {"family": "Inter"},
    },
    "colors": {"ground": "rgb(250, 250, 251)", "ink": "#1342ff", "accent": "rgba(19, 66, 255, 1)",
               "wash": "rgba(0, 0, 0, 0)"},
    "used": ["rgb(19, 66, 255)", "#fafafb", "#dde3f8", "#1342ff", "nonsense"],
}


def test_tokens_clean_hashed_font_names_and_normalise_the_browser_s_words():
    tokens, problems = design_tokens.clean(NEXT_FONT_TOKENS)
    body = tokens["type"]["body"]
    assert body == {"family": "Newsreader", "generic": "serif", "stack": ["Newsreader", "serif"], "size": 19.0,
                    "weight": 400, "line_height": 30.4, "letter_spacing": 0.0, "color": "#1342ff"}
    heading = tokens["type"]["heading"]
    assert heading["family"] == "Source Serif 4" and heading["weight"] == 700 and heading["line_height"] is None
    assert heading["letter_spacing"] == pytest.approx(-1.12) and heading["stack"] == ["Source Serif 4", "Georgia",
                                                                                         "serif"]
    assert tokens["type"]["drop_cap"]["size"] == 88.0
    assert "caption" in tokens["type"] and "size" not in tokens["type"]["caption"], "2 px is out of bounds"
    assert tokens["type"]["caption"]["family"] == "Menlo" and tokens["type"]["caption"]["generic"] == "ui-monospace"
    assert "sidebar" not in tokens["type"]
    assert tokens["colors"] == {"ground": "#fafafb", "ink": "#1342ff", "accent": "#1342ff"}, "transparent is no colour"
    assert tokens["used"] == ["#1342ff", "#fafafb", "#dde3f8"]
    assert any("caption: size" in p for p in problems) and any("sidebar" in p for p in problems)
    assert any("wash" in p for p in problems)
    assert design_tokens.fonts(tokens) == ["Newsreader", "Source Serif 4", "Menlo"]
    assert design_tokens.clean(json.dumps(NEXT_FONT_TOKENS))[0] == tokens, "the JSON text reads the same"


@pytest.mark.parametrize("raw, problem", [("{", "not JSON"), ("[1]", "an object"), ("x" * 20_000, "too large"),
                                          ({"used": ["#000"] * 5000}, "too large")])
def test_tokens_that_are_not_tokens_are_refused_whole(raw, problem):
    tokens, problems = design_tokens.clean(raw)
    assert tokens == {} and problem in problems[0]


def test_one_shape_for_the_validator_the_tool_schemas_and_the_docs():
    schema = design_tokens.JSON_SCHEMA
    assert tuple(schema["properties"]["type"]["properties"]) == design_tokens.TYPE_ROLES
    assert tuple(schema["properties"]["colors"]["properties"]) == design_tokens.COLOR_ROLES
    from _stdio_server import stdio_server

    server = stdio_server()
    tools = {t["name"]: t for t in server.TOOLS}
    assert tools["cicada_save_design"]["inputSchema"]["properties"]["tokens"] is schema
    capture = tools["cicada_record_capture"]["inputSchema"]["properties"]
    assert capture["design"] is schema and capture["pages"]["items"]["properties"]["design"] is schema
    assert "look" in tools["cicada_explore_start"]["inputSchema"]["properties"]
    doc = (Path(__file__).resolve().parents[2] / "docs" / "architecture" / "storage.md").read_text()
    assert design_tokens.SHAPE in doc and all(f"`{r}`" in doc for r in design_tokens.TYPE_ROLES)


# --------------------------------------------------------------------------- whose words


@pytest.fixture
def bank(tmp_path):
    return _bank(tmp_path, git=False)


def test_an_agent_s_note_is_its_own_and_the_person_s_is_what_they_liked(bank):
    agent = design_refs.add_ref(bank, image=DARK, url="https://ink.example.com/", note="Cobalt on off-white.",
                                author="claude-code", via="agent", look=([], []))["ref"]
    assert agent.note_by == "claude-code"
    text = (bank / agent.path).read_text()
    assert "## Noted by Claude Code\n\nCobalt on off-white." in text and "## What I liked" not in text
    again = design_refs.get_ref(bank, agent.id)
    assert again.note == "Cobalt on off-white." and again.note_by == "claude-code"
    mine = design_refs.add_ref(bank, image=LIGHT, note="The calm cards.", look=([], []))["ref"]
    assert "## What I liked\n\nThe calm cards." in (bank / mine.path).read_text() and mine.note_by == "user"
    nameless = design_refs.add_ref(bank, image=_png(_neon_page()), note="Neon.", via="agent", look=([], []))["ref"]
    assert nameless.added_by == "agent" and nameless.note_by == "agent", "an agent door never writes as the person"
    assert "## Noted by an agent" in (bank / nameless.path).read_text()


def test_a_reference_saved_before_looks_v2_by_an_agent_through_rest_reads_as_the_agent_s(bank):
    ref = design_refs.add_ref(bank, image=DARK, note="Noted while browsing.", look=([], []))["ref"]
    path = bank / ref.path
    parsed = markdown_parser.parse(path)
    fm = {**parsed.frontmatter, "via": "agent"}   # the coordinator's 2026-10-15 save: added_by user, via agent
    markdown_parser.write(path, fm, parsed.body)
    old = design_refs.get_ref(bank, ref.id)
    assert old.note == "Noted while browsing." and old.note_by == "agent"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    monkeypatch.setattr(design_index, "refresh_in_background", lambda mp, **kw: False)
    with TestClient(main.app) as c:
        yield c, memory
    config.get_settings.cache_clear()


def _git(bank, *args) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], capture_output=True, text=True, check=True).stdout


def test_the_rest_door_takes_the_agent_s_name_and_its_tokens(client):
    c, bank = client
    r = c.post("/design", files={"image": ("shot.png", DARK, "image/png")},
               data={"url": "https://ink.example.com/", "note": "One cobalt ink.", "via": "agent",
                     "author": "claude-code", "tokens": json.dumps(NEXT_FONT_TOKENS)})
    assert r.status_code == 200, r.text
    ref = r.json()
    assert ref["addedBy"] == "claude-code" and ref["addedByKind"] == "harness"
    assert ref["noteBy"] == "claude-code" and ref["noteByKind"] == "harness"
    assert ref["fonts"][:2] == ["Newsreader", "Source Serif 4"], "what the page renders, body first"
    roles = {t["role"]: t for t in ref["typeRoles"]}
    assert roles["body"]["family"] == "Newsreader" and roles["body"]["size"] == 19.0
    assert roles["body"]["lineHeight"] == 30.4 and roles["drop_cap"]["size"] == 88.0
    colour_roles = {c["role"]: c for c in ref["colourRoles"]}
    assert colour_roles["ink"] == {"role": "ink", "hex": "#1342ff", "source": "page"}
    assert colour_roles["wash"]["source"] == "pixels"
    head = _git(bank, "log", "-1", "--format=%B")
    assert "Cicada-Author: claude-code" in head and "trigger: agent/rest_api" in head
    assert c.get(f"/design/{ref['id']}").json()["computed"]["type"]["body"]["family"] == "Newsreader"
    board = c.get("/design").json()["refs"][0]
    assert board["noteBy"] == "claude-code" and board["palette"][0]["role"] == "ground"


def test_the_rest_door_never_writes_an_agent_as_the_person_and_refuses_free_text_authors(client):
    c, bank = client
    r = c.post("/design", files={"image": ("a.png", DARK, "image/png")}, data={"note": "x", "via": "agent"})
    assert r.status_code == 200 and r.json()["addedBy"] == "agent" and r.json()["noteBy"] == "agent"
    assert "Cicada-Author: agent" in _git(bank, "log", "-1", "--format=%B")
    bad = c.post("/design", files={"image": ("b.png", LIGHT, "image/png")}, data={"author": "Somebody Else"})
    assert bad.status_code == 400
    broken = c.post("/design", files={"image": ("b.png", LIGHT, "image/png")}, data={"tokens": "{"})
    assert broken.status_code == 400 and "tokens" in broken.json()["detail"]
    mine = c.post("/design", files={"image": ("b.png", LIGHT, "image/png")}, data={"note": "mine"}).json()
    assert mine["noteBy"] == "user" and mine["noteByKind"] == "user" and mine["addedBy"] == "user"


# --------------------------------------------------------------------------- "Save its look"


def _ctx(bank, harness="claude-code", session="s1", **kw):
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id=session, harness=harness, **kw)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _save(tmp_path: Path, name: str, data: bytes) -> str:
    path = tmp_path / "shots" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    return str(path)


def test_the_ask_queues_a_design_visit_without_replacing_the_run(tmp_path):
    memory, keys = bank_with_sites(tmp_path, 3)
    enable_reading()
    run = explore_queue.start(memory, [{"key": keys[0], "site": "bob-example.org"}], started_by={"kind": "person"})
    out = explore_queue.ask(memory, [{"key": keys[1], "site": "bob-example.org"}], asked="look",
                            started_by={"kind": "person"})
    assert out["joined"] is True and out["id"] == run["id"] and out["total"] == 2
    rows = {r["key"]: r for r in explore_queue.view(memory)["items"]}
    assert rows[keys[1]]["asked"] == "look" and rows[keys[1]]["depth"] == "look" and "asked" not in rows[keys[0]]
    explore_queue.stop(memory)
    alone = explore_queue.ask(memory, [{"key": keys[2], "site": "bob-example.org"}], asked="look",
                              started_by={"kind": "agent", "harness": "claude-code"})
    assert alone["joined"] is False and alone["total"] == 1 and alone["startedBy"]["kind"] == "agent"
    with pytest.raises(explore_queue.QueueError):
        explore_queue.ask(memory, [{"key": keys[2], "site": "bob-example.org"}], asked="everything",
                          started_by={"kind": "person"})


def test_the_ask_is_a_design_reason_that_keeps_the_landing_look():
    plan = explore_plan.plan_for(None, asked="look")
    assert plan["depth"] == "look" and plan["auto_look"] is True and plan["save_look"] is True
    assert plan["because"][0] == {"from": "ask", "signal": "look"}
    assert not explore_plan.plan_for(None).get("save_look")


def test_the_click_route_queues_it_and_hands_back_the_prompt(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory, keys = bank_with_sites(tmp_path, 2)
    enable_reading()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    try:
        with TestClient(main.app) as c:
            r = c.post("/explore/look", json={"entityId": "media-site01", "url": "https://site01.bob-example.org/"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["mediaEntityId"] == "media-site01" and body["key"] == keys[1]
            assert "cicada_explore_claim" in body["prompt"] and "design" in body["prompt"]
            state = c.get("/explore/state").json()
            assert state["batch"]["startedBy"] == {"kind": "person"} and state["batch"]["total"] == 1
            assert c.post("/explore/look", json={"url": "https://not-saved.bob-example.org/"}).status_code == 422
    finally:
        config.get_settings.cache_clear()


@needs_sips
def test_a_save_look_visit_keeps_the_look_with_its_tokens_even_when_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(explore_queue, "PACE_SECONDS", 0)   # the second visit follows at once in this test
    memory, keys = bank_with_sites(tmp_path, 1)
    enable_reading()
    url = "https://site00.bob-example.org/"

    def visit(name: str, picture: bytes = LIGHT) -> str:
        reply = mcp_tools.explore_claim(_ctx(memory))
        assert "they asked to save its look" in reply and '"save_look":true' in reply, reply
        token = reply.split("lease_token ")[1].split(" ")[0]
        now = datetime.now(timezone.utc)
        return mcp_tools.record_capture(
            _ctx(memory), url, token, "captured", captured_at=_iso(now - timedelta(seconds=5)), final_url=url,
            http_status=200, shots=[{"kind": "viewport", "path": _save(tmp_path, name, picture)}],
            page={"title": "Site 00"}, signed_in=True, loaded_at=_iso(now - timedelta(seconds=9)),
            design=NEXT_FONT_TOKENS)

    explore_queue.ask(memory, [{"key": keys[0], "site": "bob-example.org"}], asked="look",
                      started_by={"kind": "person"})
    first = visit("one.png")
    assert "kept as Looks" in first, first
    (look,) = design_refs.list_refs(memory)
    assert look.via == "explore" and look.computed["type"]["body"]["family"] == "Newsreader"
    assert look.note == "" and design_refs.fonts(look)[0] == "Newsreader"
    assert any(c.get("declared") for c in look.palette), "the page's declared colours are merged into the palette"
    # The same look again: a design reason alone keeps nothing new, but the person asked to save it.
    explore_queue.ask(memory, [{"key": keys[0], "site": "bob-example.org"}], asked="look",
                      started_by={"kind": "person"})
    # A new screenshot of the same look (one pixel differs): the capture says "same look", and still a Look is kept.
    same_look = demo_pictures.website((255, 255, 255), (242, 244, 255), (17, 24, 39), (59, 92, 253), width=1440,
                                      height=900, dense=True)
    assert same_look != LIGHT
    second = visit("two.png", same_look)
    assert "look since" in second and "same" in second and "kept as Looks" in second, second
    assert len(design_refs.list_refs(memory)) == 2


def test_an_agent_the_person_asked_queues_it_through_explore_start(tmp_path):
    memory, keys = bank_with_sites(tmp_path, 2)
    enable_reading()
    out = mcp_tools.explore_start(_ctx(memory), look=["https://site01.bob-example.org/", "https://nope.example.org/"])
    assert out.startswith("Queued 1 saved link(s) to keep their look") and "1 link(s) are not saved" in out
    (row,) = explore_queue.view(memory)["items"]
    assert row["key"] == keys[1] and row["asked"] == "look"
    assert explore_queue.batch_view(explore_queue.view(memory))["startedBy"]["kind"] == "agent"
    remote = mcp_tools.explore_start(_ctx(memory, connector_id="c1"), look=["https://site00.bob-example.org/"])
    assert remote.startswith("Not started")



#: What the capture script's ``_DESIGN_JS`` printed in a headless Chrome for a synthetic editorial page (a hashed
#: ``next/font`` serif with a drop cap, one cobalt ink on off-white, a light-blue wash), recorded 2026-10-15.
CHROME_PRINTED = {
    "type": {
        "body": {"family": "__Newsreader_a1b2c3, __Newsreader_Fallback_a1b2c3, serif", "size": "19px",
                 "weight": "400", "line_height": "30.4px", "letter_spacing": "normal", "color": "rgb(19, 66, 255)"},
        "heading": {"family": "__Inter_9f8e7d, sans-serif", "size": "56px", "weight": "700",
                    "line_height": "89.6px", "letter_spacing": "-1.12px", "color": "rgb(19, 66, 255)"},
        "caption": {"family": "ui-monospace, Menlo, monospace", "size": "12px", "weight": "400",
                    "line_height": "19.2px", "letter_spacing": "normal", "color": "rgb(19, 66, 255)"},
        "drop_cap": {"family": "__Newsreader_a1b2c3, __Newsreader_Fallback_a1b2c3, serif", "size": "88px",
                     "weight": "400", "line_height": "88px", "letter_spacing": "normal",
                     "color": "rgb(19, 66, 255)"}},
    "colors": {"ground": "#fafafb", "ink": "#1342ff", "accent": "#1342ff", "wash": "#dde3f8"},
    "used": ["#1342ff", "#dde3f8"],
}


def test_what_the_capture_script_prints_is_what_the_schema_keeps():
    tokens, problems = design_tokens.clean(CHROME_PRINTED)
    assert problems == []
    assert tokens["type"]["body"]["family"] == "Newsreader" and tokens["type"]["body"]["generic"] == "serif"
    assert tokens["type"]["heading"]["family"] == "Inter" and tokens["type"]["heading"]["letter_spacing"] == -1.12
    assert tokens["type"]["drop_cap"]["size"] == 88.0
    assert tokens["colors"] == {"ground": "#fafafb", "ink": "#1342ff", "accent": "#1342ff", "wash": "#dde3f8"}
    script = (Path(__file__).resolve().parents[2] / "skills" / "site-explore" / "explore_capture.py").read_text()
    for key in ("family", "size", "weight", "line_height", "letter_spacing", "color", "drop_cap", "ground", "wash"):
        assert key in script, f"the script prints {key}"
