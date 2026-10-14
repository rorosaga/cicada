"""What a look is made of, read locally and deterministically (design taste, 2026-10-14) — no model, no network.

* :func:`palette` — a screenshot's colours: pixels (``image_decode``, ≤ 256 px a side) binned at 5 bits a channel,
  the bins merged greedily in order of size into colours at most ``MERGE`` apart, then every colour that covers at
  least 1 % of the picture, largest first, as ``{hex, share}``. Same bytes, same palette.
* :func:`describe` — the words a palette earns for the word leg of search: ``dark``/``light`` from the largest
  colour's luminance, ``muted``/``vivid`` from the saturation of what is not near-grey, and the hue names present
  (``blue``, ``orange``…). A person typing "dark minimal" finds dark screenshots even with no image model here.
* :func:`css_tokens` — from HTML/CSS the person (or their agent) selected: font families, colours, font sizes,
  spacing and radii, most frequent first. Read with regular expressions over the text as given; nothing is fetched
  and nothing is executed.

Prior art for per-type units and an exact-word boost: DigUp (github.com/ARahim3/DigUp, MIT) — ideas borrowed, no code.
"""
from __future__ import annotations

import colorsys
import re
from collections import Counter

import numpy as np

SAMPLE_SIDE = 256
MERGE = 28.0          # RGB distance under which two bins are one colour
MIN_SHARE = 0.01
MAX_COLOURS = 8

_HUES = ((10, "red"), (45, "orange"), (70, "yellow"), (160, "green"), (195, "teal"), (255, "blue"),
         (290, "purple"), (335, "pink"), (360, "red"))


def palette(rgb: np.ndarray, *, max_colours: int = MAX_COLOURS) -> list[dict]:
    """The picture's main colours, largest first: ``[{"hex": "#1f2430", "share": 0.62}, …]``."""
    px = np.asarray(rgb, dtype=np.uint8).reshape(-1, 3)
    if px.size == 0:
        return []
    q = (px >> 3).astype(np.int32)
    keys = (q[:, 0] << 10) | (q[:, 1] << 5) | q[:, 2]
    counts = np.bincount(keys, minlength=1 << 15)
    sums = np.stack([np.bincount(keys, weights=px[:, c].astype(np.float64), minlength=1 << 15) for c in range(3)],
                    axis=1)
    # Bins under 0.05 % of the picture can't move a colour that covers 1 %: they are left out of the merge.
    floor = max(1.0, len(px) * 0.0005)
    order = [int(k) for k in np.argsort(-counts, kind="stable") if counts[k] >= floor]
    centres = np.zeros((0, 3))
    clusters: list[list[float]] = []   # [r_sum, g_sum, b_sum, n]
    for key in order:
        n = float(counts[key])
        mean = sums[key] / n
        if len(clusters):
            d = np.linalg.norm(centres - mean, axis=1)
            i = int(np.argmin(d))
            if d[i] < MERGE:
                c = clusters[i]
                c[0] += sums[key][0]
                c[1] += sums[key][1]
                c[2] += sums[key][2]
                c[3] += n
                centres[i] = np.array(c[:3]) / c[3]
                continue
        if len(clusters) >= 48:
            continue
        clusters.append([*sums[key], n])
        centres = np.vstack([centres, mean])
    total = float(len(px))
    out = []
    for c in sorted(clusters, key=lambda c: -c[3]):
        share = c[3] / total
        if share < MIN_SHARE:
            continue
        r, g, b = (int(round(v / c[3])) for v in c[:3])
        out.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "share": round(share, 3)})
        if len(out) >= max_colours:
            break
    return out


def _rgb(hex_value: str) -> tuple[float, float, float]:
    h = hex_value.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def hue_name(hex_value: str) -> str | None:
    r, g, b = _rgb(hex_value)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.25 or l < 0.12 or l > 0.95:
        return None
    deg = h * 360
    return next(name for top, name in _HUES if deg <= top)


def describe(colours: list[dict]) -> list[str]:
    """Words for a palette (see the module docstring), stable order."""
    if not colours:
        return []
    words: list[str] = []
    r, g, b = _rgb(colours[0]["hex"])
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    words.append("dark" if luminance < 0.4 else "light")
    chroma = [colorsys.rgb_to_hls(*_rgb(c["hex"]))[2] for c in colours if hue_name(c["hex"])]
    words.append("vivid" if chroma and max(chroma) > 0.6 else "muted")
    for c in colours:
        name = hue_name(c["hex"])
        if name and name not in words:
            words.append(name)
    return words


# --------------------------------------------------------------------------- the person's CSS

_FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;{}\"<>]+(?:\"[^\"]*\"[^;{}<>]*)*)", re.I)
_FONT_SIZE = re.compile(r"font-size\s*:\s*([0-9.]+(?:px|rem|em|pt|%))", re.I)
_SPACING = re.compile(r"(?:^|[;{\s\"'])(?:padding|margin|gap|row-gap|column-gap)(?:-[a-z]+)?\s*:\s*([^;{}\"<>]+)",
                      re.I)
_RADIUS = re.compile(r"border-radius\s*:\s*([^;{}\"<>]+)", re.I)
_LENGTH = re.compile(r"-?[0-9.]+(?:px|rem|em)\b")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
_RGB = re.compile(r"rgba?\(\s*([0-9.]+)[\s,]+([0-9.]+)[\s,]+([0-9.]+)", re.I)
_GENERIC = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-sans-serif", "ui-serif",
            "ui-monospace", "ui-rounded", "inherit", "initial", "unset", "-apple-system", "blinkmacsystemfont",
            "emoji", "math", "fangsong"}
_VAR = re.compile(r"var\([^)]*\)")


def _hex6(token: str) -> str | None:
    h = token.lstrip("#").lower()
    if len(h) in (3, 4):
        h = "".join(ch * 2 for ch in h[:3])
    elif len(h) == 8:
        h = h[:6]
    return f"#{h}" if len(h) == 6 else None


def css_tokens(text: str, *, limit: int = 8) -> dict:
    """``{fonts, generic, colors, font_sizes, spacing, radii}`` from HTML/CSS text, most frequent first."""
    text = text or ""
    fonts: Counter[str] = Counter()
    generic: Counter[str] = Counter()
    for m in _FONT_FAMILY.finditer(text):
        for part in _VAR.sub("", m.group(1)).split(","):
            name = part.strip().strip("'\"").strip()
            if not name or len(name) > 60:
                continue
            (generic if name.lower() in _GENERIC else fonts)[name] += 1
    colors: Counter[str] = Counter()
    for m in _HEX.finditer(text):
        h = _hex6(m.group(0))
        if h:
            colors[h] += 1
    for m in _RGB.finditer(text):
        try:
            r, g, b = (max(0, min(255, int(float(v)))) for v in m.groups())
        except ValueError:
            continue
        colors[f"#{r:02x}{g:02x}{b:02x}"] += 1
    sizes = Counter(m.group(1) for m in _FONT_SIZE.finditer(text))
    spacing: Counter[str] = Counter()
    for m in _SPACING.finditer(text):
        for v in _LENGTH.findall(m.group(1)):
            if v.lstrip("-") not in ("0px", "0rem", "0em"):
                spacing[v] += 1
    radii: Counter[str] = Counter()
    for m in _RADIUS.finditer(text):
        for v in _LENGTH.findall(m.group(1)):
            radii[v] += 1

    def top(c: Counter) -> list[str]:
        return [k for k, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]

    return {"fonts": top(fonts), "generic": top(generic), "colors": top(colors), "font_sizes": top(sizes),
            "spacing": top(spacing), "radii": top(radii)}
