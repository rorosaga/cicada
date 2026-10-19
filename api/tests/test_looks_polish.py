"""Looks polish (owner, 2026-10-15): type specimens, a capture that waits for the page, and the share rule's inputs.

* the specimen model: one per distinct family the page renders, with the roles and sizes it is used for, at most six;
  the capture's "Aa" pictures are bounded (a transparent PNG of at most 400×120 px), kept through the one writer
  (``design_refs``) beside the screenshot, served from the bank, removed with the look;
* the settle: before the first screenshot the script waits for the web fonts, the first viewport's images, a still
  layout and the viewport's animations, inside a hard cap, and records it when it ran out — on a fake browser (every
  branch, a fake clock) and in a real headless Chrome on a synthetic page with a late web font, a lazy image and a
  1.5 s intro animation (skipped where no Chrome is installed).

Synthetic only: pictures drawn here, a page served from 127.0.0.1, bob-example.org links, placeholder names."""
from __future__ import annotations

import base64
import json
import struct
import threading
import time
import zlib
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from _explore_fixtures import LIGHT, bank_with_sites, enable_reading
from _headless_chrome import chrome_binary, headless_page
from _synthetic_bank import _bank
from api.services import design_index, design_refs, design_tokens, explore_queue, image_decode, mcp_tools, \
    site_captures

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "site-explore" / "explore_capture.py"


def _png(w: int, h: int, *, alpha: bool = True, fill=(0, 0, 0, 255)) -> bytes:
    channels = 4 if alpha else 3
    px = bytes(fill[:channels])
    raw = b"".join(b"\x00" + px * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6 if alpha else 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


#: A page's computed type as the capture printed it: a hashed serif for body and drop cap, a sans for headings and
#: subheadings, a mono caption, links in the body face — three families.
TOKENS = {
    "type": {
        "body": {"family": "__Newsreader_a1b2c3, __Newsreader_Fallback_a1b2c3, serif", "size": "19px", "weight": "400"},
        "heading": {"family": "__Inter_9f8e7d, sans-serif", "size": "56px", "weight": "700"},
        "subheading": {"family": "inter, sans-serif", "size": "28px", "weight": "600"},
        "caption": {"family": "ui-monospace, Menlo, monospace", "size": "12px", "weight": "400"},
        "link": {"family": "__Newsreader_a1b2c3, serif", "size": "19px", "weight": "400"},
        "drop_cap": {"family": "__Newsreader_a1b2c3, serif", "size": "88px", "weight": "400"}},
    "colors": {"ground": "#fafafb", "ink": "#1342ff"},
}


# --------------------------------------------------------------------------- the specimen model


def test_one_specimen_per_family_with_the_roles_and_sizes_it_is_used_for():
    tokens, problems = design_tokens.clean(TOKENS)
    assert problems == []
    specs = design_tokens.specimens(tokens)
    assert [s["family"] for s in specs] == ["Newsreader", "Inter", "Menlo"], "body first; Inter once, any case"
    news = specs[0]
    assert news["generic"] == "serif"
    assert [(r["role"], r["size"], r["weight"]) for r in news["roles"]] == [
        ("body", 19.0, 400), ("link", 19.0, 400), ("drop_cap", 88.0, 400)]
    assert [r["role"] for r in specs[1]["roles"]] == ["heading", "subheading"]
    assert design_tokens.specimens({}) == [] and design_tokens.specimens(None) == []


def test_at_most_six_specimens_and_a_generic_family_is_one_too():
    many = {"type": {role: {"family": f"Face{i}", "size": 10 + i} for i, role in enumerate(design_tokens.TYPE_ROLES)}}
    assert len(design_tokens.specimens(many)) == 6 == design_tokens.MAX_SPECIMENS
    only_generic = design_tokens.clean({"type": {"body": {"family": "system-ui, -apple-system, sans-serif"}}})[0]
    (spec,) = design_tokens.specimens(only_generic)
    assert spec["family"] == "system-ui"


def test_specimen_inputs_are_bounded_and_never_tokens():
    raw = {**TOKENS, "specimens": [
        {"family": "__Newsreader_a1b2c3, serif", "path": "/tmp/a.png"},
        {"family": "Newsreader", "path": "/tmp/again.png"},                 # the same family twice: the first stays
        {"family": "Inter", "base64": "AAAA"},
        {"family": "Nowhere"},                                              # no bytes named
        "not an object",
        *({"family": f"F{i}", "path": f"/tmp/{i}.png"} for i in range(20))]}
    got = design_tokens.specimen_inputs(raw)
    assert got[0] == {"family": "Newsreader", "path": "/tmp/a.png"} and got[1] == {"family": "Inter", "base64": "AAAA"}
    assert len(got) == design_tokens.MAX_SPECIMENS
    big = {**TOKENS, "specimens": [{"family": "Inter", "base64": "A" * 200_000}]}
    tokens, problems = design_tokens.clean(big)
    assert problems == [] and "specimens" not in tokens, "a specimen's bytes never count against the tokens' size"


def test_a_specimen_is_a_small_transparent_png():
    assert design_refs.validate_specimen(_png(240, 120)) == (240, 120)
    for bad in (_png(240, 120, alpha=False), _png(401, 120), _png(240, 121), _png(4, 4), LIGHT, b"", b"\x89PNG\r\n"):
        with pytest.raises(ValueError):
            design_refs.validate_specimen(bad)


@pytest.fixture
def bank(tmp_path):
    return _bank(tmp_path, git=False)


def test_the_writer_keeps_one_specimen_per_named_family_beside_the_screenshot(bank):
    drawn = [{"family": "__Inter_9f8e7d, sans-serif", "data": _png(200, 120)},
             {"family": "Newsreader", "data": _png(180, 120)},
             {"family": "Not On The Page", "data": _png(100, 120)},          # not a family the page renders
             {"family": "Menlo", "data": _png(100, 120, alpha=False)}]       # refused: no transparent ground
    result = design_refs.add_ref(bank, image=LIGHT, url="https://ink.bob-example.org/", computed=TOKENS,
                                 look=([], []), specimens=drawn)
    ref = result["ref"]
    assert [s["family"] for s in ref.specimens] == ["Newsreader", "Inter"], "the model's order, only named families"
    assert ref.specimens[0]["file"] == f"assets/design/{ref.id}.type-1.png" and ref.specimens[0]["width"] == 180
    assert result["paths"] == [ref.path, ref.image_path, ref.specimens[0]["file"], ref.specimens[1]["file"]]
    assert (bank / ref.specimens[1]["file"]).read_bytes() == drawn[0]["data"]
    again = design_refs.get_ref(bank, ref.id)
    assert again.specimens == ref.specimens and "specimens" not in again.extra
    assert design_refs.specimen_file(bank, again, 2) == bank / ref.specimens[1]["file"]
    assert design_refs.specimen_file(bank, again, 3) is None and design_refs.specimen_file(bank, again, 0) is None
    removed = design_refs.remove_ref(bank, ref.id)
    assert set(removed["paths"]) == {ref.path, ref.image_path, *(s["file"] for s in ref.specimens)}
    assert not any((bank / "assets" / "design").glob(f"{ref.id}*"))


def test_a_hand_edited_specimen_path_never_points_elsewhere(bank):
    from api.services import markdown_parser

    ref = design_refs.add_ref(bank, image=LIGHT, computed=TOKENS, look=([], []),
                              specimens=[{"family": "Newsreader", "data": _png(100, 120)}])["ref"]
    parsed = markdown_parser.parse(bank / ref.path)
    fm = dict(parsed.frontmatter)
    fm["specimens"] = [{"family": "Newsreader", "file": "../../secrets.png", "sha256": "x"}]
    markdown_parser.write(bank / ref.path, fm, parsed.body)
    assert design_refs.get_ref(bank, ref.id).specimens == []


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


def test_the_api_serves_each_family_with_its_drawn_aa_or_none(client):
    c, bank = client
    ref = design_refs.add_ref(bank, image=LIGHT, computed=TOKENS, look=([], []),
                              specimens=[{"family": "Inter", "data": _png(200, 120)}])["ref"]
    body = c.get(f"/design/{ref.id}").json()
    specs = body["specimens"]
    assert [s["family"] for s in specs] == ["Newsreader", "Inter", "Menlo"]
    assert specs[0]["image"] is None and specs[0]["generic"] == "serif", "no drawing: the app says it's generic"
    assert [r["role"] for r in specs[0]["roles"]] == ["body", "link", "drop_cap"]
    assert specs[1]["image"]["url"].startswith(f"/design/{ref.id}/type/1?v=") and specs[1]["image"]["width"] == 200
    got = c.get(f"/design/{ref.id}/type/1")
    assert got.status_code == 200 and got.headers["content-type"] == "image/png" and got.content[:4] == b"\x89PNG"
    assert c.get(f"/design/{ref.id}/type/1", headers={"If-None-Match": got.headers["etag"]}).status_code == 304
    assert c.get(f"/design/{ref.id}/type/2").status_code == 404
    assert c.get("/design/2026-01-01-nothing/type/1").status_code == 404


def test_one_hand_broken_specimen_is_skipped_and_the_board_still_reads(client):
    from api.services import markdown_parser

    c, bank = client
    ref = design_refs.add_ref(bank, image=LIGHT, computed=TOKENS, look=([], []),
                              specimens=[{"family": "Newsreader", "data": _png(180, 120)},
                                         {"family": "Inter", "data": _png(200, 120)}])["ref"]
    parsed = markdown_parser.parse(bank / ref.path)
    fm = dict(parsed.frontmatter)
    fm["specimens"] = [{**fm["specimens"][0], "width": "wide"}, fm["specimens"][1]]
    markdown_parser.write(bank / ref.path, fm, parsed.body)
    again = design_refs.get_ref(bank, ref.id)
    assert [s["family"] for s in again.specimens] == ["Inter"], "the broken one is skipped, the other kept"
    for bad in ({"width": None, "height": [1]}, {"width": -4}, {"width": 10 ** 9}, {"width": True}, {"height": 3.5}):
        assert design_refs._stored_specimens(ref.id, [{**fm["specimens"][1], "file": ref.specimens[0]["file"],
                                                       **bad}]) == []
    board = c.get("/design")
    assert board.status_code == 200 and board.json()["refs"][0]["id"] == ref.id
    specs = c.get(f"/design/{ref.id}").json()["specimens"]
    assert specs[0]["family"] == "Newsreader" and specs[0]["image"] is None
    assert specs[1]["image"]["url"].startswith(f"/design/{ref.id}/type/2?v="), "it keeps its own number"
    assert c.get(f"/design/{ref.id}/type/2").status_code == 200
    assert c.get(f"/design/{ref.id}/type/1").status_code == 404, "the skipped one is not served"
    removed = design_refs.remove_ref(bank, ref.id)
    assert not any((bank / "assets" / "design").glob(f"{ref.id}*")), "its file goes with the look all the same"
    assert ref.specimens[0]["file"] in removed["paths"]


def test_the_cap_holds_with_no_frame_grab_past_it(monkeypatch):
    # The layout is still from 8.0 s (quiet at 8.5 s), the pixels never stop, a frame grab costs 0.3 s: a grab at the
    # cap would end past it, so none starts there.
    got, at, ns = _settle_on(monkeypatch, layout_until=7.9, moving_until=999, frame_cost=0.3)
    assert got["timed_out"] is True and got["waiting_on"] == ["motion"]
    assert at <= ns["SETTLE_CAP"] + 0.3, "at most one grab already under way when the cap arrives"
    got, at, ns = _settle_on(monkeypatch, fonts_at=999, frame_cost=5.0)
    assert got["timed_out"] and at <= ns["SETTLE_CAP"] + 0.01, "no frame is grabbed while the DOM is pending"


def _ctx(bank, harness="claude-code", session="s1", **kw):
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id=session, harness=harness, **kw)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _save(tmp_path: Path, name: str, data: bytes) -> str:
    path = tmp_path / "shots" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    return str(path)


def test_a_capture_s_specimens_and_settle_ride_into_the_look_and_the_record(tmp_path, monkeypatch):
    memory, keys = bank_with_sites(tmp_path, 1)
    enable_reading()
    url = "https://site00.bob-example.org/"
    explore_queue.ask(memory, [{"key": keys[0], "site": "bob-example.org"}], asked="look",
                      started_by={"kind": "person"})
    reply = mcp_tools.explore_claim(_ctx(memory))
    token = reply.split("lease_token ")[1].split(" ")[0]
    now = datetime.now(timezone.utc)
    design = {**TOKENS, "specimens": [
        {"family": TOKENS["type"]["body"]["family"], "path": _save(tmp_path, "type-1.png", _png(220, 120))},
        {"family": TOKENS["type"]["heading"]["family"],
         "base64": base64.b64encode(_png(210, 120)).decode()},
        {"family": "ui-monospace, Menlo, monospace", "path": "relative/not-allowed.png"}]}
    out = mcp_tools.record_capture(
        _ctx(memory), url, token, "captured", captured_at=_iso(now - timedelta(seconds=5)), final_url=url,
        http_status=200, shots=[{"kind": "viewport", "path": _save(tmp_path, "v.png", LIGHT)}],
        page={"title": "Site 00", "settle": {"ms": 9012, "timed_out": True, "waiting_on": ["motion", "nonsense"]}},
        signed_in=True, loaded_at=_iso(now - timedelta(seconds=9)), design=design)
    assert "kept as Looks" in out and "before the page settled (still waiting on motion)" in out, out
    (look,) = design_refs.list_refs(memory)
    assert [s["family"] for s in look.specimens] == ["Newsreader", "Inter"]
    (cap,) = site_captures.list_captures(memory, "media-site00")
    assert cap["settle"] == {"ms": 9012, "timed_out": True, "waiting_on": ["motion"]}


def test_the_settle_note_keeps_ids_and_enums_only():
    note = site_captures.settle_note
    assert note({"ms": 1234, "timed_out": False, "motion": "looping"}) == {"ms": 1234, "timed_out": False,
                                                                           "motion": "looping"}
    assert note({"ms": "x"}) is None and note({"ms": -1}) is None and note({"ms": 10 ** 9}) is None
    assert note({"ms": 5, "timed_out": "yes", "waiting_on": ["fonts"], "motion": "<b>"}) == {"ms": 5,
                                                                                           "timed_out": False}
    assert note("nope") is None


# --------------------------------------------------------------------------- the settle, on a fake browser


class FakePage:
    """A page whose state is a function of the fake clock: each condition settles at its own time."""

    def __init__(self, ns: dict, *, fonts_at=0.0, images_at=0.0, layout_until=0.0, finite_until=0.0,
                 infinite=False, moving_until=0.0, unread=False, frame_cost=0.0):
        self.ns, self.t = ns, 0.0
        self.fonts_at, self.images_at, self.layout_until = fonts_at, images_at, layout_until
        self.finite_until, self.infinite, self.moving_until, self.unread = finite_until, infinite, moving_until, unread
        self.frame_cost = frame_cost

    def js(self, expr):
        if expr != self.ns["_SETTLE_JS"]:
            return None
        if self.unread:
            raise RuntimeError("Execution context was destroyed")
        layout = f"{int(self.t * 10)}" if self.t < self.layout_until else "still"
        return json.dumps({"fonts": "loaded" if self.t >= self.fonts_at else "loading",
                           "images": 0 if self.t >= self.images_at else 2, "layout": layout,
                           "finite": 1 if self.t < self.finite_until else 0, "infinite": 1 if self.infinite else 0,
                           "left": max(0, int((self.finite_until - self.t) * 1000)), "ready": "complete"})

    def cdp(self, method, **params):
        if method == "Page.captureScreenshot":
            self.t += self.frame_cost
            frame = f"f{int(self.t * 100)}" if self.t < self.moving_until else "still"
            return {"data": frame}
        return {}

    def sleep(self, seconds):
        self.t += seconds

    def monotonic(self):
        return self.t


def _settle_on(monkeypatch, **state):
    ns: dict = {"__name__": "explore_capture_test"}
    exec(compile(SCRIPT.read_text(), "explore_capture.py", "exec"), ns)
    page = FakePage(ns, **state)
    ns.update(cdp=page.cdp, js=page.js, wait_for_load=lambda *a, **k: True,
              wait_for_network_idle=lambda *a, **k: False, switch_tab=lambda *a, **k: None)
    monkeypatch.setattr(time, "sleep", page.sleep)
    monkeypatch.setattr(time, "monotonic", page.monotonic)
    return ns["_settle"](), page.t, ns


def test_the_shot_waits_for_fonts_images_a_still_layout_and_finished_animations(monkeypatch):
    got, at, ns = _settle_on(monkeypatch, fonts_at=1.2, images_at=1.0, layout_until=1.3, finite_until=1.5)
    assert got["timed_out"] is False and "motion" not in got
    assert 1.5 <= at <= 2.4, "after the last condition and half a second of still layout, not later"
    assert at < ns["SETTLE_CAP"]


def test_motion_no_animation_names_is_waited_out_or_given_its_grace(monkeypatch):
    got, at, ns = _settle_on(monkeypatch, moving_until=1.6)            # a script-driven intro: pixels move to 1.6 s
    assert got == {"ms": got["ms"], "timed_out": False} and 1.6 <= at < ns["SETTLE_MOTION_GRACE"] + 0.5
    got, at, ns = _settle_on(monkeypatch, moving_until=999)            # a carousel that never stops
    assert got["motion"] == "moving" and not got["timed_out"]
    assert ns["SETTLE_MOTION_GRACE"] <= at < ns["SETTLE_MOTION_GRACE"] + 1


def test_an_infinite_animation_gets_the_grace_not_the_cap(monkeypatch):
    got, at, ns = _settle_on(monkeypatch, infinite=True, moving_until=999)
    assert got["motion"] == "looping" and not got["timed_out"]
    assert ns["SETTLE_MOTION_GRACE"] <= at < ns["SETTLE_MOTION_GRACE"] + 1


def test_a_page_that_never_settles_is_captured_at_the_cap_and_says_why(monkeypatch):
    got, at, ns = _settle_on(monkeypatch, fonts_at=999, finite_until=999)
    assert got["timed_out"] is True and got["waiting_on"] == ["fonts", "animations"]
    assert ns["SETTLE_CAP"] <= at <= ns["SETTLE_CAP"] + 0.3, "the cap is hard"
    assert site_captures.settle_note(got)["waiting_on"] == ["fonts", "animations"]


def test_a_page_whose_state_cannot_be_read_is_not_waited_on(monkeypatch):
    got, at, _ = _settle_on(monkeypatch, unread=True)
    assert got["unread"] is True and at == 0.0


# --------------------------------------------------------------------------- the settle, in a real headless Chrome

FONT_CANDIDATES = ("/System/Library/Fonts/Supplemental/Apple Chancery.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Settle test</title><style>
@font-face { font-family: "LateFont"; src: url("/late.ttf") format("truetype"); font-display: swap; }
html, body { margin: 0; background: #ffffff; }
h1 { font: 400 48px "LateFont", serif; margin: 40px; }
#intro { position: absolute; left: 600px; top: 300px; width: 200px; height: 120px; background: rgb(0, 0, 255);
         opacity: 0; }
.go #intro { animation: rise 1.5s ease-out forwards; }
@keyframes rise { from { transform: translateX(-560px); opacity: 0; } to { transform: none; opacity: 1; } }
#scripted { position: absolute; left: 0; top: 500px; width: 120px; height: 120px; background: rgb(0, 160, 0); }
#lazy { position: absolute; left: 1000px; top: 300px; width: 200px; height: 120px; }
</style></head><body>
<p>Body text.</p>
<img id="lazy" loading="lazy" src="/lazy.png" alt="">
<div id="intro"></div><div id="scripted"></div>
<script>
window.addEventListener('load', () => {
  setTimeout(() => {
    document.body.classList.add('go');                      // a 1.5 s CSS intro, from just after the load
    const h = document.createElement('h1'); h.textContent = 'Aa late web font'; document.body.prepend(h);
    const el = document.getElementById('scripted'); const t0 = performance.now();
    const step = now => { const k = Math.min(1, (now - t0) / 1500);   // a 1.5 s script-driven slide
      el.style.left = Math.round(k * 900) + 'px'; if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }, 50);
});
</script></body></html>"""


def _serve(font: bytes, lazy: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body, kind = {"/": (PAGE.encode(), "text/html"), "/late.ttf": (font, "font/ttf"),
                          "/lazy.png": (lazy, "image/png")}.get(self.path.split("?")[0], (b"", "text/plain"))
            if self.path.startswith("/late.ttf"):
                time.sleep(1.2)                                     # the web font arrives late
            if self.path.startswith("/lazy.png"):
                time.sleep(1.0)                                     # and so does the lazy image
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    return server


_STATE_JS = r"""JSON.stringify({fonts: document.fonts.status,
  late: document.fonts.check('48px "LateFont"', 'Aa') && Array.from(document.fonts).some(f => f.family.includes('LateFont') && f.status === 'loaded'),
  lazy: (() => { const i = document.getElementById('lazy'); return i.complete && i.naturalWidth > 0; })(),
  running: document.getAnimations().filter(a => a.playState === 'running').length,
  scripted: parseInt(getComputedStyle(document.getElementById('scripted')).left)})"""


@pytest.mark.skipif(chrome_binary() is None, reason="no Chrome on this machine (set CICADA_CHROME to name one)")
def test_in_a_real_browser_the_shot_is_the_settled_page(tmp_path):
    font_path = next((Path(p) for p in FONT_CANDIDATES if Path(p).is_file()), None)
    if font_path is None:
        pytest.skip("no font file to serve as the late web font")
    lazy = _png(200, 120, alpha=False, fill=(255, 0, 0, 255))
    server = _serve(font_path.read_bytes(), lazy)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        with headless_page(tmp_path / "chrome-profile") as page:
            ns: dict = {"__name__": "explore_capture_chrome"}
            exec(compile(SCRIPT.read_text(), "explore_capture.py", "exec"), ns)
            ns.update(page.helpers())
            ns["_metrics"](ns["VIEW_W"], ns["VIEW_H"], ns["VIEW_DPR"])
            # Too early, as before: the load event alone. The intro is still running, the font and image not in.
            page.cdp("Page.navigate", url=url)
            page.wait_for_load()
            time.sleep(0.2)
            early = json.loads(page.js(_STATE_JS))
            assert early["running"] > 0 or not early["late"] or not early["lazy"], early
            # Now the script's own settle, from a fresh load.
            page.cdp("Page.navigate", url=url)
            started = time.monotonic()
            settled = ns["_settle"]()
            took = time.monotonic() - started
            state = json.loads(page.js(_STATE_JS))
            shot = Path(ns["_shot"](str(tmp_path), "viewport"))
            design = ns["_read_design"](str(tmp_path), "")
    finally:
        server.shutdown()
        server.server_close()
    assert settled["timed_out"] is False, settled
    assert took < ns["SETTLE_CAP"] + 1.5 and took >= 1.2, took
    assert state["fonts"] == "loaded" and state["late"] and state["lazy"], state
    assert state["running"] == 0 and state["scripted"] == 900, "the CSS intro and the scripted slide both finished"
    if image_decode.available():
        rgb = image_decode.decode(shot.read_bytes(), max_side=3000)
        h, w, _ = rgb.shape
        sx, sy = w / 1440, h / 900

        def at(x, y):
            return rgb[int(y * sy), int(x * sx)].astype(int)

        assert np.abs(at(700, 360) - (0, 0, 255)).max() < 40, "the intro block is in its final place, fully shown"
        assert np.abs(at(1100, 360) - (255, 0, 0)).max() < 40, "the lazy image is in"
        assert np.abs(at(960, 560) - (0, 160, 0)).max() < 40, "the scripted slide reached its end"
    # The specimens: "Aa" drawn by the page in each family it renders, the late web font among them.
    specs = (design or {}).get("specimens") or []
    assert specs, design
    for spec in specs:
        data = Path(spec["path"]).read_bytes()
        w, h = design_refs.validate_specimen(data)
        assert w <= 400 and h <= 120
    assert any("LateFont" in str(s["family"]) for s in specs), [s["family"] for s in specs]
