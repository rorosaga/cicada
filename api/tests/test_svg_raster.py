"""Owner 2026-10-20: "yes, we should draw the SVG icon safely."

`svg_raster` turns a site's SVG icon into a 64×64 PNG: a strict parse with every DTD refused, an allow-list rebuild, and
a render in a locked-down child process. These tests feed it hostile SVGs (script, external image, file:// hrefs,
billion laughs, external entities, huge viewBox, deep nesting, foreignObject, CSS url()/@import, exponential <use>,
oversize) and benign ones, and check the child really cannot open a file. Nothing here touches the network."""
from __future__ import annotations

import asyncio
import time

import pytest

from api.services import svg_raster as r

NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'


def svg(body: str, box: str = "0 0 24 24") -> bytes:
    return f'<svg {NS} viewBox="{box}">{body}</svg>'.encode()


def draw(data: bytes) -> bytes | None:
    return asyncio.run(r.svg_to_png(data))


DOT = '<circle cx="12" cy="12" r="10" fill="#c33"/>'


# --- benign -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("data", [
    svg(DOT),
    svg('<defs><linearGradient id="g"><stop offset="0" stop-color="#f00"/><stop offset="1" stop-color="#00f"/>'
        '</linearGradient></defs><rect width="24" height="24" rx="4" fill="url(#g)"/>'),
    svg('<style>.a{fill:#0a0}</style><g transform="translate(2 2) scale(0.8)"><path class="a" d="M0 0h20v20H0z"/></g>'),
    svg('<defs><symbol id="s"><circle cx="6" cy="6" r="5"/></symbol></defs><use xlink:href="#s"/><use href="#s" x="10"/>'),
    svg('<clipPath id="c"><circle cx="12" cy="12" r="8"/></clipPath><rect width="24" height="24" clip-path="url(#c)"/>'),
    f'<svg {NS} width="32" height="16"><rect width="32" height="16" fill="#123"/></svg>'.encode(),  # no viewBox
    svg('<switch><foreignObject><p xmlns="http://www.w3.org/1999/xhtml">x</p></foreignObject>' + DOT + '</switch>'),
])
def test_a_benign_icon_becomes_a_64px_png(data):
    png = draw(data)
    assert png is not None and png.startswith(b"\x89PNG") and r.png_is_icon(png)


def test_a_wide_icon_is_letterboxed_into_the_square():
    png = draw(svg('<rect width="200" height="100" fill="#00f"/>', box="0 0 200 100"))
    assert png is not None and r.png_is_icon(png), "drawn 64×64, aspect kept"


def test_nothing_visible_is_a_miss_not_a_blank_icon():
    assert draw(svg('<rect width="24" height="24" fill="none"/>')) is None
    assert draw(svg('<script>x()</script>')) is None, "a script-only icon has nothing left to draw"


# --- hostile: the sanitiser ---------------------------------------------------------------------------------------


def test_script_handlers_and_foreign_object_are_dropped():
    clean = r.sanitize(svg('<script>fetch("https://evil.example/")</script>'
                           '<circle cx="12" cy="12" r="10" onload="x()" onclick="y()"/>'
                           '<foreignObject width="24" height="24"><iframe xmlns="http://www.w3.org/1999/xhtml" '
                           'src="https://evil.example/"/></foreignObject>'
                           '<a xlink:href="javascript:alert(1)">' + DOT + '</a>'
                           '<animate attributeName="fill" to="red"/><set attributeName="href" to="x"/>'))
    assert clean is not None
    for bad in ("script", "onload", "onclick", "foreignObject", "iframe", "javascript", "evil", "animate", "<set"):
        assert bad not in clean
    assert draw(svg('<script>x()</script>' + DOT)) is not None, "the drawing survives without its script"


def test_external_images_and_file_hrefs_never_survive():
    hostile = svg('<image href="https://evil.example/track.png" width="24" height="24"/>'
                  '<image xlink:href="file:///etc/passwd" width="24" height="24"/>'
                  '<image xlink:href="/etc/hosts" width="24" height="24"/>'
                  '<use xlink:href="file:///etc/passwd#x"/><use href="https://evil.example/s.svg#a"/>'
                  '<linearGradient id="g" xlink:href="https://evil.example/g.svg#g"/>'
                  + DOT)
    clean = r.sanitize(hostile)
    assert clean is not None
    for bad in ("<image", "file:", "/etc/", "evil", "<use"):
        assert bad not in clean
    assert draw(hostile) is not None


def test_css_that_reaches_outside_is_dropped():
    clean = r.sanitize(svg('<style>@import url(https://evil.example/a.css); .a{fill:red}</style>'
                           '<style>.b{fill:url(https://evil.example/p.svg#p)}</style>'
                           '<style>.c{background:\\75rl(https://evil.example/)}</style>'
                           '<circle cx="1" cy="1" r="1" style="fill:url(https://evil.example/x)"/>'
                           '<circle cx="2" cy="2" r="1" fill="url(file:///etc/passwd)"/>'
                           '<circle cx="3" cy="3" r="1" fill="url(#ok)" style="fill:#fff;stroke:url(#ok)"/>' + DOT))
    assert clean is not None and "evil" not in clean and "file:" not in clean and "@import" not in clean
    assert "\\75" not in clean
    assert 'fill="url(#ok)"' in clean and "stroke:url(#ok)" in clean, "a local url(#id) is kept"


@pytest.mark.parametrize("data", [
    # Billion laughs: an internal entity bomb.
    b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
    b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;"><!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">]>'
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><desc>&d;</desc><rect width="1" height="1"/></svg>',
    # XXE: an external entity naming a local file.
    b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><desc>&x;</desc><rect width="1" height="1"/></svg>',
    # An external DTD alone.
    b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>',
    # A parameter entity.
    b'<!DOCTYPE svg [<!ENTITY % p SYSTEM "https://evil.example/p.dtd"> %p;]>'
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><rect width="1" height="1"/></svg>',
])
def test_any_dtd_or_entity_refuses_the_whole_icon(data):
    started = time.monotonic()
    assert r.sanitize(data) is None
    assert time.monotonic() - started < 0.5, "refused before any expansion"


@pytest.mark.parametrize("box", ["0 0 1e30 1e30", "0 0 1e7 10", "0 0 0 24", "0 0 -5 24", "0 0 nan 24", "0 0 inf 24",
                                 "1 2 3"])
def test_a_huge_or_broken_viewbox_is_a_miss(box):
    assert r.sanitize(svg(DOT, box=box)) is None


def test_deep_nesting_and_too_many_nodes_are_refused_while_parsing():
    deep = svg("<g>" * (r.MAX_DEPTH + 5) + DOT + "</g>" * (r.MAX_DEPTH + 5))
    assert r.sanitize(deep) is None
    very_deep = svg("<g>" * 5000 + "</g>" * 5000)
    assert r.sanitize(very_deep) is None
    many = svg('<rect width="1" height="1"/>' * (r.MAX_NODES + 1))
    assert len(many) < r.MAX_SVG_BYTES and r.sanitize(many) is None


def test_oversize_and_non_svg_input_are_misses():
    assert r.sanitize(svg(DOT + "<!--" + "x" * r.MAX_SVG_BYTES + "-->")) is None
    assert r.sanitize(b"") is None
    assert r.sanitize(b"<html><body>hi</body></html>") is None
    assert r.sanitize(b'<svg viewBox="0 0 1 1"><rect width="1" height="1"/></svg>') is None, "no SVG namespace"
    assert r.sanitize(b"\x89PNG\r\n\x1a\nnot svg") is None
    assert r.sanitize(svg(DOT)[:-3]) is None, "not well-formed"


def test_use_cannot_expand_exponentially_or_point_outside():
    # The <use> bomb: each layer references the one below ten times.
    layers = ['<g id="l0">' + DOT + "</g>"]
    for i in range(1, 8):
        layers.append(f'<g id="l{i}">' + "".join(f'<use href="#l{i - 1}"/>' for _ in range(10)) + "</g>")
    clean = r.sanitize(svg("<defs>" + "".join(layers) + '</defs><use href="#l7"/>'))
    assert clean is None or clean.count("<use") <= 10, "a use pointing at something that holds a use is dropped"
    self_ref = r.sanitize(svg('<g id="a"><use href="#a"/>' + DOT + "</g>"))
    assert self_ref is not None and "<use" not in self_ref
    many = r.sanitize(svg('<circle id="c" r="1"/>' + '<use href="#c"/>' * (r.MAX_USES + 20)))
    assert many is not None and many.count("<use") == r.MAX_USES


def _nested(tag: str, attr: str, levels: int, fan: int) -> bytes:
    out = []
    for k in range(levels):
        ref = f' {attr}="url(#n{k + 1})"' if k + 1 < levels else ""
        out.append(f'<{tag} id="n{k}">' + f'<rect width="24" height="24" fill="#fff"{ref}/>' * fan + f"</{tag}>")
    return svg("".join(out) + f'<rect width="24" height="24" {attr}="url(#n0)"/>')


@pytest.mark.parametrize("data", [
    _nested("mask", "mask", 5, 150),
    _nested("mask", "mask", 2, 2),
    _nested("clipPath", "clip-path", 6, 100),
    _nested("clipPath", "clip-path", 2, 1),
    # Through an inline style, on the mask element itself, across kinds, and through a <use> target.
    svg('<mask id="a"><rect width="9" height="9" style="fill:#fff;mask:url(#b)"/></mask><mask id="b">' + DOT + "</mask>"
        '<rect width="24" height="24" mask="url(#a)"/>'),
    svg('<mask id="a" mask="url(#b)">' + DOT + '</mask><mask id="b">' + DOT + '</mask><rect width="9" height="9" '
        'mask="url(#a)"/>'),
    svg('<clipPath id="c"><rect width="9" height="9" mask="url(#m)"/></clipPath><mask id="m">' + DOT + "</mask>"
        '<rect width="24" height="24" clip-path="url(#c)"/>'),
    svg('<defs><g id="g"><rect width="9" height="9" clip-path="url(#c2)"/></g></defs><clipPath id="c1"><use href="#g"/>'
        '</clipPath><clipPath id="c2">' + DOT + '</clipPath><rect width="24" height="24" clip-path="url(#c1)"/>'),
    # A <style> that sets a mask or clip path, beside any mask or clip path: its selectors reach inside.
    svg('<style>rect{mask:url(#m)}</style><mask id="m"><rect width="9" height="9" fill="#fff"/></mask>' + DOT),
])
def test_a_mask_or_clip_path_that_applies_another_is_refused(data):
    started = time.monotonic()
    assert r.sanitize(data) is None
    assert time.monotonic() - started < 1


def test_one_level_of_mask_and_clip_path_still_draws():
    data = svg('<mask id="m"><rect width="24" height="24" fill="#fff"/></mask><clipPath id="c"><circle cx="12" '
               'cy="12" r="9"/></clipPath><g clip-path="url(#c)"><rect width="24" height="24" fill="#c33" '
               'mask="url(#m)"/></g><style>.a{fill:#123}</style>')
    assert draw(data) is not None


def test_a_css_comment_cannot_hide_a_url():
    clean = r.sanitize(svg('<style>.a{fill:url/**/(https://evil.example/p#a)}</style>'
                           '<circle class="a" cx="12" cy="12" r="9" style="fill:url/* */(https://evil.example/q)"/>'
                           + DOT))
    assert clean is not None and "evil" not in clean and "/*" not in clean


def test_css_filters_never_reach_the_renderer():
    clean = r.sanitize(svg('<style>.a{filter:blur(9)}</style>' + '<rect width="24" height="24" '
                           'style="fill:#000;filter:blur(1000) drop-shadow(5 5 1000 red)"/>' * 3 + DOT))
    assert clean is not None and "filter" not in clean and "blur" not in clean


def test_text_and_filters_never_reach_the_renderer():
    clean = r.sanitize(svg('<text x="2" y="20" font-family="Evil">A</text><filter id="f"><feGaussianBlur '
                           'stdDeviation="99999"/></filter><rect width="24" height="24" filter="url(#f)"/>'))
    assert clean is not None and "<text" not in clean and "<filter" not in clean and "filter=" not in clean


def test_the_output_is_a_fresh_document_cicada_wrote():
    clean = r.sanitize(svg(DOT).replace(b"<svg ", b'<svg onload="x()" width="99999" height="99999" '))
    assert clean.startswith(f'<svg xmlns="{r.SVG_NS}"') and 'width="64" height="64"' in clean
    assert "onload" not in clean and "99999" not in clean


# --- hostile: the renderer ----------------------------------------------------------------------------------------


_RENDER = "\npng = resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)\nsys.stdout.buffer.write(png)\n"
_ESCAPES = (
    "open('/etc/hosts').read()",
    "import os\nos.close(0)\nopen('/etc/hosts').read()",  # reuse a closed descriptor's number (review of #382)
    "import os\nos.close(0)\nfd = os.open('/etc/hosts', os.O_RDONLY)\nos.read(fd, 10)",
    "import socket\nsocket.socket()",
    "import os, socket\nos.close(0)\nos.close(2)\nsocket.socket(socket.AF_INET, socket.SOCK_DGRAM)",
)


@pytest.mark.parametrize("attempt", _ESCAPES)
def test_the_child_cannot_open_a_file_or_a_socket(attempt):
    # The worker tries to escape, THEN renders for real: a PNG back means the escape worked, so None can only mean
    # the descriptor limit refused it.
    clean = r.sanitize(svg(DOT))
    assert asyncio.run(r.rasterise(clean, worker=r._WORKER_PRELUDE + attempt + _RENDER)) is None
    # The same worker without the limit does get its PNG back — the test above is not passing for another reason.
    limit = "resource.setrlimit(resource.RLIMIT_NOFILE, (0, 0))"
    assert limit in r._WORKER_PRELUDE
    unlimited = r._WORKER_PRELUDE.replace(limit, "pass")
    assert asyncio.run(r.rasterise(clean, worker=unlimited + attempt + _RENDER)) is not None
    assert asyncio.run(r.rasterise(clean)) is not None, "and the real worker still draws under the limit"


def test_a_slow_render_is_killed_at_its_time_cap():
    worker = r._WORKER_PRELUDE + "import time\ntime.sleep(30)\n"
    started = time.monotonic()
    assert asyncio.run(r.rasterise(r.sanitize(svg(DOT)), timeout=0.5, worker=worker)) is None
    assert time.monotonic() - started < 3


def test_a_cpu_spin_is_stopped_by_the_child_cpu_limit():
    worker = r._WORKER_PRELUDE + "while True:\n    pass\n"
    started = time.monotonic()
    assert asyncio.run(r.rasterise(r.sanitize(svg(DOT)), timeout=1.0, worker=worker)) is None
    assert time.monotonic() - started < 4


def test_whatever_the_child_prints_must_be_a_64px_png():
    for out in ("b'<svg/>'", "b'\\x89PNG\\r\\n\\x1a\\n' + b'0' * 40", "b''"):
        worker = r._WORKER_PRELUDE + f"sys.stdout.buffer.write({out})\n"
        assert asyncio.run(r.rasterise(r.sanitize(svg(DOT)), worker=worker)) is None


def test_no_renderer_installed_is_a_miss(monkeypatch):
    monkeypatch.setattr(r, "_renderer_path", lambda: None)
    assert draw(svg(DOT)) is None
