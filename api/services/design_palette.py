"""What a look is made of, read locally and deterministically (design taste, 2026-10-14; looks v2, 2026-10-15) — no
model, no network.

* :func:`palette` — a screenshot's colours: pixels (``image_decode``, ≤ :data:`SAMPLE_SIDE` px a side) binned at 5 bits
  a channel, the bins merged greedily in order of size into colours at most ``MERGE`` apart. The largest colour is the
  **ground**; every other is ranked by **salience** — how saturated it is and how far it stands from the ground, times
  a presence term that saturates at :data:`FULL_PRESENCE` of the picture — never by area. Area made a cobalt-ink page
  read as "off-white 90 %, pale blue 4 %, grey 2 %": the one colour that *is* the look covered 0.4 %. So a thin
  saturated line colour surfaces, a blend of an accent into the ground (antialiasing) is folded away unless it is a
  real surface (a wash, ≥ 1 %), and each colour carries a **role**: ``ground``, ``ink`` (low chroma, readable on the
  ground), ``accent`` (saturated) or ``wash`` (a tint close to the ground). Colours the page's CSS declares
  (``declared``) are merged in: a pixel colour near one is marked ``declared``, one the pixels never show is added
  with ``share: 0``. Same bytes, same palette.
* :func:`describe` — the words a palette earns for the word leg of search: ``dark``/``light`` from the ground's
  luminance, ``muted``/``vivid`` from the saturation of what is not near-grey, and the hue names present
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

#: The side the palette reads at. 256 px averaged a 1 px rule of a 1440 px page into the ground; at 1600 a rule keeps
#: most of its own pixels (a 2× capture's rule is 2 px).
SAMPLE_SIDE = 1600
MERGE = 28.0          # RGB distance under which two bins are one colour
MIN_SHARE = 0.01      # a colour this large stays whatever its salience (a surface)
MAX_COLOURS = 8
#: Bins under this share of the picture are noise (antialiasing specks), never a colour.
FLOOR_SHARE = 0.0002
#: A colour under :data:`MIN_SHARE` stays only when it is at least this salient (a thin line of ink or accent).
SALIENT_MIN = 0.12
#: A colour's presence counts fully from this share of the picture (a few rules and a headline).
FULL_PRESENCE = 0.004
#: Chroma (0–1, max − min of RGB) from which a colour is an accent rather than an ink or a wash.
ACCENT_CHROMA = 0.3
#: WCAG contrast against the ground from which a low-chroma colour is an ink (text) rather than a wash.
INK_CONTRAST = 3.0
#: A colour this close to the line between a stronger colour and the ground is a blend of the two.
BLEND_DISTANCE = 18.0
#: A declared colour within this RGB distance of a pixel colour is that colour.
DECLARED_MATCH = 40.0
ROLES = ("ground", "ink", "accent", "wash")

_HUES = ((10, "red"), (45, "orange"), (70, "yellow"), (160, "green"), (195, "teal"), (255, "blue"),
         (290, "purple"), (335, "pink"), (360, "red"))


def _clusters(rgb: np.ndarray) -> tuple[list[tuple[np.ndarray, float]], float]:
    """``([(mean RGB, pixel count)], total pixels)``, largest first — the greedy 5-bit merge."""
    px = np.asarray(rgb, dtype=np.uint8).reshape(-1, 3)
    if px.size == 0:
        return [], 0.0
    q = (px >> 3).astype(np.int32)
    keys = (q[:, 0] << 10) | (q[:, 1] << 5) | q[:, 2]
    counts = np.bincount(keys, minlength=1 << 15)
    sums = np.stack([np.bincount(keys, weights=px[:, c].astype(np.float64), minlength=1 << 15) for c in range(3)],
                    axis=1)
    floor = max(2.0, len(px) * FLOOR_SHARE)
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
        if len(clusters) >= 64:
            continue
        clusters.append([*sums[key], n])
        centres = np.vstack([centres, mean])
    out = [(np.array(c[:3]) / c[3], c[3]) for c in clusters]
    out.sort(key=lambda pair: -pair[1])
    return out, float(len(px))


def _hex(rgb) -> str:
    r, g, b = (int(round(float(v))) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _vec(hex_value: str) -> np.ndarray:
    h = hex_value.lstrip("#")
    return np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], dtype=np.float64)


def chroma(hex_value: str) -> float:
    """Colourfulness 0–1: max − min of the channels (HSV chroma). Grey, black and white are 0."""
    v = _vec(hex_value)
    return float((v.max() - v.min()) / 255.0)


def luminance(hex_value: str) -> float:
    """WCAG relative luminance."""
    def lin(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(float(c)) for c in _vec(hex_value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio, 1–21."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def role_of(hex_value: str, ground: str) -> str:
    """``accent`` when saturated, else ``ink`` when readable on the ground, else ``wash``."""
    if chroma(hex_value) >= ACCENT_CHROMA:
        return "accent"
    return "ink" if contrast(hex_value, ground) >= INK_CONTRAST else "wash"


def salience(hex_value: str, share: float, ground: str) -> float:
    """How much a colour stands out of the look, 0–1: saturation and contrast against the ground, times presence."""
    k = min(1.0, max(0.0, (contrast(hex_value, ground) - 1.0) / 20.0))
    presence = min(1.0, max(0.0, share) / FULL_PRESENCE) ** 0.5
    return (0.65 * chroma(hex_value) + 0.35 * k) * presence


def _blend_of(c: np.ndarray, a: np.ndarray, ground: np.ndarray) -> bool:
    """Whether ``c`` lies on the segment from ``a`` to the ground (an antialiased edge or a transparent tint)."""
    seg = a - ground
    span = float(seg @ seg)
    if span < 1.0:
        return False
    t = float((c - ground) @ seg) / span
    if t <= 0.02 or t >= 0.98:
        return False
    return float(np.linalg.norm(ground + t * seg - c)) < BLEND_DISTANCE


def rank(colours: list[dict], *, declared=None, max_colours: int = MAX_COLOURS) -> list[dict]:
    """The palette from candidate colours (``[{hex, share}]``, any order; the largest share is the ground): ground
    first, then by salience; blends folded away, declared colours merged in, each with its role."""
    cands = [{"hex": str(c["hex"]).lower(), "share": float(c.get("share") or 0)} for c in colours
             if isinstance(c, dict) and re.fullmatch(r"#[0-9a-fA-F]{6}", str(c.get("hex") or ""))]
    wanted = []
    for d in declared or []:
        h = _hex6(str(d)) if isinstance(d, str) else None
        if h and h not in wanted:
            wanted.append(h)
    if not cands:
        if not wanted:
            return []
        cands = [{"hex": wanted[0], "share": 0.0}]
    cands.sort(key=lambda c: -c["share"])
    ground = cands[0]["hex"]
    gvec = _vec(ground)
    for c in cands[1:]:
        c["salience"] = salience(c["hex"], c["share"], ground)
    for h in wanted:
        hv = _vec(h)
        near = min(cands, key=lambda c: float(np.linalg.norm(_vec(c["hex"]) - hv)))
        if float(np.linalg.norm(_vec(near["hex"]) - hv)) < DECLARED_MATCH:
            near["declared"] = True
        else:
            cands.append({"hex": h, "share": 0.0, "declared": True,
                          "salience": (0.65 * chroma(h) + 0.35 * min(1.0, (contrast(h, ground) - 1) / 20)) * 0.5})
    rest = sorted(cands[1:], key=lambda c: (-(c["salience"] + (0.05 if c.get("declared") else 0.0)), -c["share"],
                                            c["hex"]))
    kept: list[dict] = []
    for c in rest:
        if c["share"] < MIN_SHARE and c["salience"] < SALIENT_MIN and not c.get("declared"):
            continue
        cv = _vec(c["hex"])
        blend = not c.get("declared") and \
            any(_blend_of(cv, _vec(k["hex"]), gvec) for k in kept if k["salience"] > c["salience"])
        if blend and c["share"] < MIN_SHARE:
            continue   # an antialiased edge of a stronger colour, not a colour of its own
        c["blend"] = blend
        kept.append(c)
    out = [{"hex": ground, "share": round(cands[0]["share"], 3), "role": "ground",
            **({"declared": True} if cands[0].get("declared") else {})}]
    for c in kept[: max(0, max_colours - 1)]:
        entry = {"hex": c["hex"], "share": round(c["share"], 4 if c["share"] < 0.01 else 3),
                 "role": "wash" if c.get("blend") else role_of(c["hex"], ground)}
        if c.get("declared"):
            entry["declared"] = True
        out.append(entry)
    return out


def palette(rgb: np.ndarray, *, max_colours: int = MAX_COLOURS, declared=None) -> list[dict]:
    """The picture's palette: the ground, then the accents by salience —
    ``[{"hex": "#fafafb", "share": 0.9, "role": "ground"}, {"hex": "#1342ff", "share": 0.004, "role": "accent"}, …]``."""
    clusters, total = _clusters(rgb)
    if not total:
        return rank([], declared=declared, max_colours=max_colours)
    cands = [{"hex": _hex(mean), "share": n / total} for mean, n in clusters]
    return rank(cands, declared=declared, max_colours=max_colours)


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
