"""A look's computed tokens (looks v2, owner 2026-10-15): the ONE definition of what an agent may hand Cicada about a
page's type and colour roles, and the one validator every door runs (REST ``POST /design``, MCP
``cicada_save_design`` and ``cicada_record_capture``, the capture script's output).

Why this exists: a page's real type is not in its CSS text. Next.js ``next/font`` writes ``__Newsreader_a1b2c3`` where
the stylesheet says the family, so reading a snippet found only what the snippet named. What the page *renders* is in
its computed styles, and only a browser has those — so the person's own agent reads them in the page with one bounded
script (``skills/site-explore/explore_capture.py``'s ``_DESIGN_JS``; ruling 25: Cicada never spawns a browser), and
Cicada validates, bounds and keeps them.

The shape (``design-tokens-1``)::

    {"type":   {"body":    {"family": "Newsreader", "generic": "serif", "stack": ["Newsreader", "serif"],
                            "size": 19.0, "weight": 400, "line_height": 30.4, "letter_spacing": 0.0,
                            "color": "#1342ff"},
                "heading": {...}, "subheading": {...}, "caption": {...}, "link": {...}, "drop_cap": {...}},
     "colors": {"ground": "#fafafb", "ink": "#1342ff", "accent": "#1342ff", "wash": "#dde3f8"},
     "used":   ["#1342ff", "#fafafb", "#dde3f8"]}

Every key is optional. Sizes are CSS pixels (a computed style's unit); ``line_height`` is pixels or None (``normal``);
``letter_spacing`` is pixels (``normal`` is 0). Colours are ``#rrggbb``; a transparent one is dropped. Input may use the
browser's own words (``fontFamily``, ``lineHeight``, ``rgb(19, 66, 255)``, ``"18px"``, ``"bold"``) — they are
normalised here. Anything outside the bounds is dropped with a problem line, never an exception: a bad token never
stops a save (provenance never blocks memory).
"""
from __future__ import annotations

import json
import re

SHAPE = "design-tokens-1"
TYPE_ROLES = ("body", "heading", "subheading", "caption", "link", "drop_cap")
COLOR_ROLES = ("ground", "ink", "accent", "wash")
MAX_USED = 12
#: At most this many type specimens per look (looks polish): one per distinct family.
MAX_SPECIMENS = 6
MAX_STACK = 4
MAX_FAMILY = 80
MAX_JSON = 16_000
SIZE_PX = (4.0, 400.0)
LINE_PX = (0.0, 800.0)
SPACING_PX = (-50.0, 50.0)
WEIGHT = (1, 1000)
GENERIC = ("serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
           "ui-monospace", "ui-rounded", "emoji", "math", "fangsong")
_SYSTEM = {"-apple-system": "system-ui", "blinkmacsystemfont": "system-ui"}
_WEIGHT_WORDS = {"normal": 400, "bold": 700, "lighter": 300, "bolder": 700}
_ALIASES = {"fontFamily": "family", "font_family": "family", "fontSize": "size", "font_size": "size",
            "fontWeight": "weight", "font_weight": "weight", "lineHeight": "line_height",
            "letterSpacing": "letter_spacing", "colour": "color"}
#: ``next/font`` (``__Inter_aaf875``, ``__Source_Serif_4_Fallback_1c2d3e``) and CSS-module hashes (``Inter_abc12``).
_NEXT_FONT = re.compile(r"^__(?P<name>.+?)(?P<fallback>_Fallback)?_[0-9a-f]{5,8}$", re.I)
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB = re.compile(r"^rgba?\(\s*([0-9.]+)[\s,]+([0-9.]+)[\s,]+([0-9.]+)(?:\s*[,/]\s*([0-9.]+%?))?\s*\)$", re.I)
#: Linear: one way to match a number (review 2026-10-15 — ``-?[0-9]*\.?[0-9]+`` backtracked quadratically, 5 s on a
#: 16k-character value). Every value is also cut to :data:`MAX_VALUE` before any pattern sees it.
_LENGTH = re.compile(r"^(-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))\s*(px|em|rem)?$", re.I)
#: The longest length or colour value read (``rgba(255, 255, 255, 0.5)`` is 24); anything longer is not one.
MAX_VALUE = 32
#: The longest font stack read before it is split.
MAX_STACK_CHARS = 400


def colour(value) -> str | None:
    """``#rrggbb`` from a hex or an ``rgb()``/``rgba()`` value, or None (transparent, malformed)."""
    raw = str(value or "").strip()
    if len(raw) > MAX_VALUE:
        return None
    if _HEX.match(raw):
        h = raw[1:].lower()
        if len(h) in (3, 4):
            if len(h) == 4 and h[3] == "0":
                return None
            h = "".join(ch * 2 for ch in h[:3])
        elif len(h) == 8:
            if h[6:] == "00":
                return None
            h = h[:6]
        return f"#{h}"
    m = _RGB.match(raw)
    if not m:
        return None
    alpha = m.group(4)
    if alpha is not None:
        a = float(alpha[:-1]) / 100 if alpha.endswith("%") else float(alpha)
        if a <= 0.05:
            return None
    try:
        r, g, b = (max(0, min(255, int(round(float(v))))) for v in m.groups()[:3])
    except ValueError:
        return None
    return f"#{r:02x}{g:02x}{b:02x}"


def family_name(raw: str) -> tuple[str | None, bool]:
    """``(clean name, is a fallback face)`` for one entry of a font stack: quotes stripped, a ``next/font`` hash
    removed (``__Newsreader_a1b2c3`` → ``Newsreader``), a system alias folded into ``system-ui``."""
    name = str(raw or "").strip().strip("'\"").strip()
    if not name or len(name) > MAX_FAMILY * 2 or "(" in name:
        return None, False
    m = _NEXT_FONT.match(name)
    fallback = False
    if m:
        name, fallback = m.group("name").replace("_", " ").strip(), bool(m.group("fallback"))
    elif name.lower().endswith(" fallback"):
        name, fallback = name[: -len(" fallback")].strip(), True
    lower = name.lower()
    if lower in _SYSTEM:
        return _SYSTEM[lower], False
    return (name[:MAX_FAMILY] or None), fallback


def stack(raw) -> list[str]:
    """A computed ``font-family`` as clean names, fallback faces and repeats dropped, at most :data:`MAX_STACK`."""
    parts = raw[: MAX_STACK * 4] if isinstance(raw, list) else str(raw or "")[:MAX_STACK_CHARS].split(",")
    out: list[str] = []
    for part in parts:
        name, fallback = family_name(str(part))
        if name and not fallback and name.lower() not in (n.lower() for n in out):
            out.append(name)
    return out[:MAX_STACK]


def _px(value, size: float | None, bounds: tuple[float, float]) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n, unit = float(value), "px"
    else:
        text = str(value or "").strip()
        if len(text) > MAX_VALUE:
            return None
        m = _LENGTH.match(text)
        if not m:
            return None
        n, unit = float(m.group(1)), (m.group(2) or "px").lower()
    if unit in ("em", "rem"):
        n *= size or 16.0
    return round(n, 2) if bounds[0] <= n <= bounds[1] else None


def _weight(value) -> int | None:
    if isinstance(value, bool):
        return None
    word = str(value or "").strip().lower()
    if word in _WEIGHT_WORDS:
        return _WEIGHT_WORDS[word]
    try:
        n = int(float(word))
    except ValueError:
        return None
    return n if WEIGHT[0] <= n <= WEIGHT[1] else None


def _type_role(raw: dict, role: str, problems: list[str]) -> dict | None:
    item = {_ALIASES.get(k, k): v for k, v in raw.items()}
    out: dict = {}
    names = stack(item.get("family") if item.get("family") is not None else item.get("stack"))
    named = [n for n in names if n.lower() not in GENERIC]
    generic = next((n for n in names if n.lower() in GENERIC), None)
    if isinstance(item.get("generic"), str) and item["generic"].strip().lower() in GENERIC:
        generic = item["generic"].strip().lower()
    if named:
        out["family"] = named[0]
    elif generic:
        out["family"] = generic
    if generic:
        out["generic"] = generic
    if names:
        out["stack"] = names
    size = _px(item.get("size"), None, SIZE_PX)
    if item.get("size") is not None and size is None:
        problems.append(f"{role}: size out of bounds")
    if size is not None:
        out["size"] = size
    if (w := _weight(item.get("weight"))) is not None:
        out["weight"] = w
    lh = item.get("line_height")
    if isinstance(lh, str) and lh.strip().lower() == "normal":
        out["line_height"] = None
    elif lh is not None:
        value = _px(lh, size, LINE_PX)
        if value is not None and isinstance(lh, (int, float)) and value < 5 and size:
            value = round(value * size, 2)   # a unitless ratio (1.6) as the browser would compute it
        if value is None:
            problems.append(f"{role}: line height out of bounds")
        else:
            out["line_height"] = value
    ls = item.get("letter_spacing")
    if isinstance(ls, str) and ls.strip().lower() == "normal":
        out["letter_spacing"] = 0.0
    elif ls is not None:
        value = _px(ls, size, SPACING_PX)
        if value is None:
            problems.append(f"{role}: letter spacing out of bounds")
        else:
            out["letter_spacing"] = value
    if (c := colour(item.get("color"))) is not None:
        out["color"] = c
    return out if out.get("family") or out.get("size") else None


def clean(raw) -> tuple[dict, list[str]]:
    """``(tokens, problems)``: the validated, bounded tokens (``{}`` when nothing usable came) and one short line per
    thing dropped. Accepts a dict or its JSON text."""
    problems: list[str] = []
    if raw is None or raw == "" or raw == {}:
        return {}, problems
    if isinstance(raw, str):
        if len(raw) > MAX_JSON:
            return {}, ["tokens are too large"]
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}, ["tokens are not JSON"]
    if not isinstance(raw, dict):
        return {}, ["tokens are an object"]
    # Specimens are pictures, not tokens: their bytes are read and bounded by the caller (``specimen_inputs``).
    raw = {k: v for k, v in raw.items() if k != "specimens"}
    if len(json.dumps(raw, default=str)) > MAX_JSON:
        return {}, ["tokens are too large"]
    out: dict = {}
    types = raw.get("type") if isinstance(raw.get("type"), dict) else {}
    for key in types:
        if key not in TYPE_ROLES:
            problems.append(f"unknown type role {str(key)[:20]}")
    kept_types = {}
    for role in TYPE_ROLES:
        if isinstance(types.get(role), dict):
            got = _type_role(types[role], role, problems)
            if got:
                kept_types[role] = got
    if kept_types:
        out["type"] = kept_types
    colors = raw.get("colors") if isinstance(raw.get("colors"), dict) else {}
    kept_colors = {}
    for role in COLOR_ROLES:
        if role in colors:
            c = colour(colors[role])
            if c is None:
                problems.append(f"colour {role} is not a colour")
            else:
                kept_colors[role] = c
    if kept_colors:
        out["colors"] = kept_colors
    used: list[str] = []
    for value in list(raw.get("used") or [])[: MAX_USED * 2] if isinstance(raw.get("used"), list) else []:
        c = colour(value)
        if c and c not in used:
            used.append(c)
    if used:
        out["used"] = used[:MAX_USED]
    return out, problems


def fonts(tokens: dict | None) -> list[str]:
    """The named families the page renders, in role order (body first), no generic names, no repeats."""
    out: list[str] = []
    for role in TYPE_ROLES:
        item = ((tokens or {}).get("type") or {}).get(role) or {}
        name = item.get("family")
        if isinstance(name, str) and name.lower() not in GENERIC and name not in out:
            out.append(name)
    return out


def family_of(raw) -> tuple[str | None, str | None]:
    """``(family, generic)`` for one computed ``font-family``: the first named face, else the generic — the same
    reading :func:`clean` gives a type role, so a specimen and a role name one family the same way."""
    names = stack(raw)
    named = [n for n in names if n.lower() not in GENERIC]
    generic = next((n.lower() for n in names if n.lower() in GENERIC), None)
    return (named[0] if named else generic), generic


def specimens(tokens: dict | None) -> list[dict]:
    """One type specimen per distinct family the page renders (looks polish, owner 2026-10-15: "an Aa with the font
    and the name, or fonts if several"): ``[{family, generic, roles: [{role, size, weight}]}]``, in role order (body
    first), families compared without case, at most :data:`MAX_SPECIMENS`."""
    out: list[dict] = []
    by_name: dict[str, dict] = {}
    for role in TYPE_ROLES:
        item = ((tokens or {}).get("type") or {}).get(role)
        if not isinstance(item, dict) or not isinstance(item.get("family"), str) or not item["family"].strip():
            continue
        key = item["family"].strip().lower()
        spec = by_name.get(key)
        if spec is None:
            if len(out) >= MAX_SPECIMENS:
                continue
            spec = {"family": item["family"].strip(), "generic": item.get("generic"), "roles": []}
            by_name[key] = spec
            out.append(spec)
        spec["roles"].append({"role": role, "size": item.get("size"), "weight": item.get("weight")})
        if not spec.get("generic") and item.get("generic"):
            spec["generic"] = item["generic"]
    return out


def specimen_inputs(raw) -> list[dict]:
    """The specimen pictures a capture handed over with its tokens (``design.specimens``): ``[{family, path?,
    base64?}]``, each family read as :func:`family_of` reads a role, repeats dropped, at most :data:`MAX_SPECIMENS`.
    Only where the bytes are is returned; reading and bounding them is the door's (``mcp_tools``) and the writer's
    (``design_refs``) job."""
    if not isinstance(raw, dict) or not isinstance(raw.get("specimens"), list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw["specimens"][: MAX_SPECIMENS * 2]:
        if not isinstance(item, dict):
            continue
        family, _ = family_of(item.get("family") if item.get("family") is not None else item.get("stack"))
        if not family or family.lower() in seen:
            continue
        where = {k: str(item[k]) for k in ("path", "base64") if isinstance(item.get(k), str) and item[k].strip()}
        if not where:
            continue
        seen.add(family.lower())
        out.append({"family": family, **where})
        if len(out) >= MAX_SPECIMENS:
            break
    return out


def declared(tokens: dict | None) -> list[str]:
    """The colours the page declares, for the palette's merge: the roles, then the most used."""
    t = tokens or {}
    out: list[str] = []
    for c in [*(t.get("colors") or {}).values(), *(t.get("used") or [])]:
        if isinstance(c, str) and c not in out:
            out.append(c)
    return out


def _role_schema() -> dict:
    return {"type": "object", "properties": {
        "family": {"type": "string", "description": "The computed font-family, as the browser gives it."},
        "size": {"type": ["number", "string"], "description": "Computed font-size (px)."},
        "weight": {"type": ["integer", "string"]},
        "line_height": {"type": ["number", "string", "null"], "description": "Computed line-height (px) or normal."},
        "letter_spacing": {"type": ["number", "string"], "description": "Computed letter-spacing (px) or normal."},
        "color": {"type": "string", "description": "Computed colour, rgb() or #hex."}}}


#: The token shape as a tool schema — the ONE definition the MCP tools advertise (``cicada_save_design.tokens``,
#: ``cicada_record_capture.design``), so the schema an agent sees cannot drift from what :func:`clean` keeps.
JSON_SCHEMA: dict = {
    "type": "object",
    "description": ("The page's computed styles, read in the page with one bounded script (the site-explore skill's "
                    "capture prints them as `design`): type by role (body, heading, subheading, caption, link, "
                    "drop_cap), colour roles (ground, ink, accent, wash) and the most-used colours. Out-of-bounds "
                    "values are dropped."),
    "properties": {
        "type": {"type": "object", "properties": {role: _role_schema() for role in TYPE_ROLES}},
        "colors": {"type": "object", "properties": {role: {"type": "string"} for role in COLOR_ROLES}},
        "used": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_USED},
        "specimens": {"type": "array", "maxItems": MAX_SPECIMENS, "description": (
            "Optional: one small picture per font family the page renders (the capture script draws \"Aa\" in the "
            "page's own loaded font, a transparent PNG at most 400x120), so the person sees the real type."),
            "items": {"type": "object", "required": ["family"], "properties": {
                "family": {"type": "string", "description": "The computed font-family the picture is set in."},
                "path": {"type": "string", "description": "Absolute path of the PNG the script saved."},
                "base64": {"type": "string", "description": "The PNG itself, base64 (when you have no file)."}}}},
    },
}
