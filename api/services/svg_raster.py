"""Draw an SVG site icon as a small PNG, safely (owner ruling 2026-10-20: "yes, we should draw the SVG icon safely").

A site that declares only an SVG icon used to be a monogram (#371): an SVG is a scriptable document that can name
other files and other hosts, and the backend had no way to turn it into pixels without trusting it. This module is
that way, in three walls, and only its PNG ever leaves it — SVG bytes are never stored and never served:

1. **Sanitise** (:func:`sanitize`, pure Python, no renderer involved). The bytes are capped at
   :data:`MAX_SVG_BYTES` and parsed by expat with every DTD refused outright — a ``<!DOCTYPE``, an entity declaration
   or an external entity reference makes the whole icon a miss (no billion laughs, no XXE, no ``file://``). The tree
   is capped in depth and node count, and rebuilt from an allow-list: shapes, paths, groups, gradients, clip paths,
   masks and ``<use>`` of a local ``#id`` only. Everything else is dropped with its subtree — ``script``,
   ``foreignObject``, ``image``, ``text`` (no font file is ever opened), filters, animation, links, ``on*`` handlers,
   any ``href`` that is not a local fragment, any ``url(...)`` that is not ``url(#id)``, any CSS with ``@`` rules,
   escapes or comments. A ``<use>`` may not point at anything that itself holds a ``<use>``, and a mask or clip path
   may not apply another mask or clip path (no exponential expansion; the icon is refused). A viewBox
   must be four finite numbers inside :data:`MAX_COORD`. The output is a fresh document Cicada wrote, sized
   :data:`ICON_PX` square.
2. **Render out of process** (:func:`rasterise`). The sanitised text is drawn by resvg (Rust; no script engine, no
   network code at all) in a child Python started with ``-I`` and an empty environment, in an empty working
   directory. It caps its own CPU seconds (and address space where the OS enforces it: Linux, not macOS — there the
   sanitiser's expansion limits and the wall clock bound memory), reads the SVG, then sets ``RLIMIT_NOFILE`` to 0: no
   new descriptor can be created, so no file and no socket, even after closing one of its own. The parent kills it at
   :data:`RENDER_TIMEOUT_SECONDS`.
3. **Check the answer**: a PNG of exactly :data:`ICON_PX` square that is not fully transparent, or nothing.

Any failure at any wall is ``None`` — the row keeps its monogram, never an error.
"""

from __future__ import annotations

import asyncio
import importlib.util
import math
import os
import re
import struct
import sys
import tempfile
import zlib
from xml.parsers import expat

from loguru import logger

#: The largest SVG this module will look at, before parsing (the brief's cap).
MAX_SVG_BYTES = 64 * 1024
#: Element nesting and element count caps, enforced while parsing (a hostile file never builds a big tree).
MAX_DEPTH = 32
MAX_NODES = 1000
#: How many `<use>` references survive; each points at a subtree with no `<use>` in it, so drawing is bounded.
MAX_USES = 64
#: A viewBox number beyond this (or not finite) is a miss: a "huge viewBox" is no icon.
MAX_COORD = 1e6
#: The PNG's side, in pixels. The app draws site icons at 16–32 pt, so 64 covers 2× without waste.
ICON_PX = 64
#: The child renderer's wall-clock budget; past it the process is killed. Its CPU limit is the same, rounded up.
RENDER_TIMEOUT_SECONDS = 2.0
#: The child's address-space cap where the OS enforces RLIMIT_AS (Linux); macOS ignores it and relies on the CPU cap.
RENDER_MEMORY_BYTES = 1024 * 1024 * 1024
#: Largest PNG accepted back from the child.
MAX_PNG_BYTES = 256 * 1024

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
_SEP = "\x1f"  # expat's namespace separator: "<ns>\x1f<local>"

#: Elements kept (with their allowed attributes). Anything else is dropped together with everything inside it.
_SHAPES = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
_CONTAINERS = {"svg", "g", "defs", "symbol", "clipPath", "mask"}
_GRADIENTS = {"linearGradient", "radialGradient"}
ALLOWED_ELEMENTS = _SHAPES | _CONTAINERS | _GRADIENTS | {"stop", "use", "style"}
#: Wrappers that hold drawable children but carry nothing safe of their own: kept as a plain `<g>`.
_UNWRAP_AS_GROUP = {"a", "switch"}

_PRESENTATION = {
    "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity", "stroke-linecap",
    "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset", "opacity", "clip-path",
    "clip-rule", "mask", "color", "display", "visibility", "stop-color", "stop-opacity", "paint-order",
    "shape-rendering", "vector-effect", "transform", "style", "id", "class",
}
_GEOMETRY = {"d", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy", "fr", "width", "height",
             "points", "pathLength"}
ALLOWED_ATTRIBUTES = _PRESENTATION | _GEOMETRY | {
    "viewBox", "preserveAspectRatio", "offset", "gradientUnits", "gradientTransform", "spreadMethod",
    "clipPathUnits", "maskUnits", "maskContentUnits",
}

_LOCAL_REF = re.compile(r"#[A-Za-z_][\w.\-:]{0,127}")
_URL_RE = re.compile(r"url\s*\(", re.IGNORECASE)
_LOCAL_URL_RE = re.compile(r"""url\(\s*(['"]?)#[A-Za-z_][\w.\-:]{0,127}\1\s*\)""", re.IGNORECASE)
_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_MAX_ATTR_CHARS = 32 * 1024


class _Refused(Exception):
    """The document is not one this module will draw."""


def _safe_value(value: str) -> bool:
    """No `url(...)` but a local `url(#id)`; no CSS escapes, comments or at-rules; no expression()/javascript:; no
    control characters."""
    if len(value) > _MAX_ATTR_CHARS or any(ord(c) < 32 and c not in "\t\n\r" for c in value):
        return False
    lowered = value.lower()
    if any(bad in value for bad in ("\\", "@", "/*", "<")) or "expression" in lowered or "javascript:" in lowered:
        return False
    return len(_URL_RE.findall(value)) == len(_LOCAL_URL_RE.findall(value))


_CSS_FILTER = re.compile(r"filter", re.IGNORECASE)


def _safe_css(value: str) -> bool:
    """A `style` attribute or `<style>` text: `_safe_value`, and no CSS `filter` (the `filter` attribute is not on the
    allow-list; its CSS twin — `blur()`, `drop-shadow()` — cost 1.5 s for 500 shapes in review of #382)."""
    return _safe_value(value) and not _CSS_FILTER.search(value)


def _viewbox(value: str) -> tuple[float, float, float, float] | None:
    nums = _NUMBER_RE.findall(value or "")
    if len(nums) != 4:
        return None
    try:
        x, y, w, h = (float(n) for n in nums)
    except ValueError:
        return None
    if not all(math.isfinite(v) and abs(v) <= MAX_COORD for v in (x, y, w, h)) or w <= 0 or h <= 0:
        return None
    return x, y, w, h


def _length(value: str | None) -> float | None:
    """A root width/height in user units (plain number or px), else None."""
    match = re.fullmatch(r"\s*(\d+\.?\d*|\.\d+)\s*(px)?\s*", value or "")
    if not match:
        return None
    number = float(match.group(1))
    return number if 0 < number <= MAX_COORD else None


class _Node:
    __slots__ = ("tag", "attrs", "children", "text")

    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Node] = []
        self.text: list[str] = []


def _parse(data: bytes) -> _Node:
    """Strict expat parse: no DTD of any kind, depth and node caps while parsing."""
    parser = expat.ParserCreate(namespace_separator=_SEP)
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    root: list[_Node] = []
    stack: list[_Node] = []
    count = 0

    def refuse(*_args):
        raise _Refused("DTD, entity or external reference")

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal count
        count += 1
        if count > MAX_NODES or len(stack) >= MAX_DEPTH:
            raise _Refused("too many or too deeply nested elements")
        node = _Node(name, attrs)
        if stack:
            stack[-1].children.append(node)
        elif root:
            raise _Refused("two roots")
        else:
            root.append(node)
        stack.append(node)

    def end(_name: str) -> None:
        stack.pop()

    def chars(text: str) -> None:
        if stack:
            stack[-1].text.append(text)

    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.UnparsedEntityDeclHandler = refuse
    parser.NotationDeclHandler = refuse
    parser.ExternalEntityRefHandler = refuse
    parser.SkippedEntityHandler = refuse
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise _Refused(f"not well-formed: {exc}") from None
    if not root:
        raise _Refused("empty")
    return root[0]


def _local(name: str) -> tuple[str, str]:
    ns, sep, local = name.rpartition(_SEP)
    return (ns if sep else ""), local


def _clean_attrs(node: _Node) -> dict[str, str]:
    kept: dict[str, str] = {}
    for name, value in node.attrs.items():
        ns, local = _local(name)
        if local == "href" and ns in ("", XLINK_NS):
            if _LOCAL_REF.fullmatch(value.strip()):
                kept["href"] = value.strip()
            continue
        if ns or local not in ALLOWED_ATTRIBUTES or local.lower().startswith("on"):
            continue
        if not (_safe_css(value) if local == "style" else _safe_value(value)):
            continue
        kept[local] = value
    return kept


def _has_use(node: _Node) -> bool:
    return node.tag == "use" or any(_has_use(child) for child in node.children)


def _rebuild(node: _Node, out: list[_Node]) -> None:
    """Copy `node`'s allowed children into `out`, dropping everything else with its subtree."""
    for child in node.children:
        ns, local = _local(child.tag)
        if ns != SVG_NS:
            continue
        if local in _UNWRAP_AS_GROUP:
            group = _Node("g", {})
            _rebuild(child, group.children)
            out.append(group)
            continue
        if local not in ALLOWED_ELEMENTS or local == "svg":  # a nested <svg> is not an icon's business
            continue
        clean = _Node(local, _clean_attrs(child))
        if local == "style":
            css = "".join(child.text)
            if css.strip() and _safe_css(css):
                clean.text = [css]
                out.append(clean)
            continue
        _rebuild(child, clean.children)
        out.append(clean)


def _index(nodes: list[_Node], ids: dict[str, _Node]) -> None:
    for node in nodes:
        if "id" in node.attrs:
            ids.setdefault(node.attrs["id"], node)
        _index(node.children, ids)


def _prune_uses(nodes: list[_Node], drawable: set[str], budget: list[int]) -> None:
    """A `<use>` survives only when it points at a local element that held no `<use>` (judged on the tree before any
    pruning, so dropping one layer never clears the next), and only `MAX_USES` of them."""
    keep: list[_Node] = []
    for node in nodes:
        if node.tag == "use":
            href = node.attrs.get("href", "")
            if href[1:] not in drawable or budget[0] <= 0:
                continue
            budget[0] -= 1
            node.children = []
        else:
            _prune_uses(node.children, drawable, budget)
        keep.append(node)
    nodes[:] = keep


_CLIP_OR_MASK = {"clipPath", "mask"}
_CSS_CLIP_OR_MASK = re.compile(r"(?:^|[;{\s])(?:mask|clip-path)\s*:", re.IGNORECASE)


def _refs_clip_or_mask(node: _Node) -> bool:
    """`node` itself applies a mask or clip path (attribute or inline style)."""
    if "mask" in node.attrs or "clip-path" in node.attrs:
        return True
    return bool(_CSS_CLIP_OR_MASK.search(node.attrs.get("style", "")))


def _subtree(node: _Node):
    yield node
    for child in node.children:
        yield from _subtree(child)


def _nested_clip_or_mask(nodes: list[_Node], ids: dict[str, _Node]) -> bool:
    """True when a mask or clip path (itself or anything inside it, a `<use>` target included) applies another mask or
    clip path — each level multiplies the work by its fan-out (security review of #382: 5 levels × 150 ≈ 1 GB), so
    such an icon is refused. A `<style>` that sets mask/clip-path is refused alongside any mask or clip path, since
    its selectors can reach inside them."""
    every = [n for top in nodes for n in _subtree(top)]
    clips = [n for n in every if n.tag in _CLIP_OR_MASK]
    if not clips:
        return False
    if any(n.tag == "style" and _CSS_CLIP_OR_MASK.search("".join(n.text)) for n in every):
        return True
    for clip in clips:
        for inner in _subtree(clip):
            if _refs_clip_or_mask(inner):
                return True
            if inner.tag == "use":
                target = ids.get(inner.attrs.get("href", "")[1:])
                if target is not None and any(_refs_clip_or_mask(t) or t.tag in _CLIP_OR_MASK
                                              for t in _subtree(target)):
                    return True
    return False


def _escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("\n", "&#10;").replace("\r", "&#13;").replace("\t", "&#9;"))


def _serialize(node: _Node, parts: list[str]) -> None:
    attrs = "".join(f' {("xlink:href" if k == "href" else k)}="{_escape(v)}"' for k, v in node.attrs.items())
    if node.tag == "style":
        parts.append(f"<style{attrs}>{_escape(''.join(node.text))}</style>")
        return
    if not node.children:
        parts.append(f"<{node.tag}{attrs}/>")
        return
    parts.append(f"<{node.tag}{attrs}>")
    for child in node.children:
        _serialize(child, parts)
    parts.append(f"</{node.tag}>")


def sanitize(data: bytes) -> str | None:
    """A fresh, allow-listed SVG document drawn at `ICON_PX` square, or None when `data` is not one this module draws.
    Never raises."""
    if not data or len(data) > MAX_SVG_BYTES:
        return None
    try:
        root = _parse(data)
        ns, local = _local(root.tag)
        if ns != SVG_NS or local != "svg":
            raise _Refused("root is not <svg>")
        box = _viewbox(root.attrs.get("viewBox", ""))
        if root.attrs.get("viewBox") is not None and box is None:
            raise _Refused("viewBox out of range")
        if box is None:
            width, height = _length(root.attrs.get("width")), _length(root.attrs.get("height"))
            if width is None or height is None:
                raise _Refused("no viewBox and no plain width/height")
            box = (0.0, 0.0, width, height)
        children: list[_Node] = []
        _rebuild(root, children)
        ids: dict[str, _Node] = {}
        _index(children, ids)
        drawable = {key for key, target in ids.items() if not _has_use(target)}
        _prune_uses(children, drawable, [MAX_USES])
        if not children:
            raise _Refused("nothing drawable")
        if _nested_clip_or_mask(children, ids):
            raise _Refused("a mask or clip path that applies another")
        out = _Node("svg", {})
        out.attrs = {"xmlns": SVG_NS, "xmlns:xlink": XLINK_NS, "width": str(ICON_PX), "height": str(ICON_PX),
                     "viewBox": " ".join(f"{v:g}" for v in box), "preserveAspectRatio": "xMidYMid meet"}
        for key in ("fill", "stroke", "color", "style"):
            value = root.attrs.get(key)
            if value is not None and (_safe_css(value) if key == "style" else _safe_value(value)):
                out.attrs[key] = value
        out.children = children
        parts: list[str] = []
        _serialize(out, parts)
        return "".join(parts)
    except _Refused as exc:
        logger.debug(f"svg icon refused: {exc}")
        return None
    except RecursionError:
        return None


# --- the renderer, out of process ---------------------------------------------------------------------------------

#: The child's prelude: import the renderer, lower its CPU-seconds cap (and address space where the OS enforces it —
#: Linux, not macOS), read the SVG from stdin, then set RLIMIT_NOFILE to 0: no new descriptor can be created at all, so
#: no file and no socket, even after closing one of its own (a limit of 3 only capped the NUMBER, and close(0) then
#: open() landed on fd 0 — security review of #382). The already-open stdout is still written.
_WORKER_PRELUDE = r"""
import sys, resource
sys.path.append(sys.argv[1])
import resvg_py
cpu, mem = int(sys.argv[2]), int(sys.argv[3])
resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
try:
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
except (ValueError, OSError):
    pass
svg = sys.stdin.buffer.read().decode("utf-8")
resource.setrlimit(resource.RLIMIT_NOFILE, (0, 0))
"""
#: Then draw, with system fonts skipped and no resources directory, and write the PNG to stdout.
_WORKER = _WORKER_PRELUDE + r"""
png = resvg_py.svg_to_bytes(svg_string=svg, skip_system_fonts=True)
sys.stdout.buffer.write(png)
sys.stdout.buffer.flush()
"""


def _renderer_path() -> str | None:
    """The directory the renderer package is imported from in THIS interpreter, handed to the child (which runs `-I`
    and so sees no environment). None when the renderer is not installed: every SVG is then a miss."""
    spec = importlib.util.find_spec("resvg_py")
    if spec is None or not spec.origin:
        return None
    return os.path.dirname(os.path.dirname(os.path.abspath(spec.origin)))


def png_is_icon(png: bytes) -> bool:
    """A PNG of `ICON_PX` × `ICON_PX` with at least one non-zero pixel byte. Filtered scanlines of an all-zero image are
    all zero (and only then), so the check needs only zlib — no image library."""
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > MAX_PNG_BYTES:
        return False
    pos, idat, width, height, bpp = 8, [], 0, 0, 0
    try:
        while pos + 8 <= len(png):
            length, kind = struct.unpack(">I4s", png[pos:pos + 8])
            chunk = png[pos + 8:pos + 8 + length]
            if kind == b"IHDR":
                width, height, depth, color = struct.unpack(">IIBB", chunk[:10])
                channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color, 0)
                bpp = max(1, channels * depth // 8)
            elif kind == b"IDAT":
                idat.append(chunk)
            elif kind == b"IEND":
                break
            pos += 12 + length
        if (width, height) != (ICON_PX, ICON_PX) or not idat:
            return False
        raw = zlib.decompressobj().decompress(b"".join(idat), ICON_PX * (ICON_PX * 8 + 1) * 2)
    except (struct.error, zlib.error):
        return False
    stride = width * bpp + 1
    return any(raw[row * stride + 1:(row + 1) * stride].strip(b"\x00") for row in range(height))


async def rasterise(svg_text: str, *, timeout: float = RENDER_TIMEOUT_SECONDS, worker: str | None = None) -> bytes | None:
    """Draw an already-sanitised SVG in a locked-down child; the PNG, or None. `worker` replaces the child's program
    (tests only)."""
    renderer = _renderer_path()
    if renderer is None:
        logger.debug("svg icon: no renderer installed")
        return None
    with tempfile.TemporaryDirectory(prefix="cicada-svg-") as empty:
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-c", worker or _WORKER, renderer, str(math.ceil(timeout)),
                str(RENDER_MEMORY_BYTES),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                cwd=empty, env={}, start_new_session=True,
            )
        except OSError as exc:
            logger.debug(f"svg icon: renderer did not start: {type(exc).__name__}")
            return None
        try:
            out, _ = await asyncio.wait_for(proc.communicate(svg_text.encode("utf-8")), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            _kill(proc)
            await proc.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            logger.debug("svg icon: renderer ran out of time")
            return None
    if proc.returncode != 0 or not png_is_icon(out):
        return None
    return out


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass


async def svg_to_png(data: bytes) -> bytes | None:
    """Sanitise, then draw: the one door. A PNG of `ICON_PX` square, or None."""
    clean = await asyncio.to_thread(sanitize, data)
    if clean is None:
        return None
    return await rasterise(clean)
