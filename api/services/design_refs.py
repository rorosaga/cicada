"""Design taste (owner, 2026-10-14): the looks the person likes are memory — one markdown file per reference, and
this module is the ONE reader and writer of them.

"Extracting the design/views/aesthetics of websites i like with screenshots and snippets and other stuff." A design
reference is the person saying *I like how this looks*: a screenshot of what they were looking at, the page it came
from, what they liked in their own words, and what the look is made of — its colours (read from the pixels here,
``design_palette``), its type and spacing (read from HTML/CSS they selected), and the snippets themselves. Each one is

* ``<bank>/design/<id>.md`` — frontmatter for what a board needs (url, site, the image's hash and size, the palette,
  the palette's words, the tokens, the computed type and colour roles, who added it, who wrote its note, and how) and a
  body an agent or Obsidian reads as it is: the screenshot embedded, the note under ``## What I liked`` when it is the
  person's own words or ``## Noted by <agent>`` when an agent wrote it (looks v2: an agent's note is never shown as
  the person's), ``## Snippets`` as fenced code;
* ``<bank>/assets/design/<id>.<png|jpg>`` — the screenshot, **in the bank, committed with it**, like a picture the
  person uploaded (``entity_picture``): it is their own capture of something that may not look the same tomorrow, so
  it cannot be a cache that is fetched again. The bank handed over intact carries its looks.
* ``<bank>/assets/design/<id>.type-<n>.png`` — at most six type specimens (looks polish, 2026-10-15): "Aa" drawn by
  the page itself in each family it renders, a transparent PNG of at most 400×120 px, from the agent's capture. The
  page's web fonts cannot be fetched by the app (it loads nothing a page names from the web), so the specimen is the
  page's own pixels, kept with the look like the screenshot.

**Never an entity page** (the closed set of 10 types stays closed): Stage 1 never reads ``design/`` and a reference
never decays — a look the person liked does not become less true. **A look lives on the page of the thing it shows**
(owner 2026-10-20): the record's ``entity:`` names that page (it never creates one), and the page's markdown carries a
``## Looks`` section this module alone writes — one line per look linking the record, its screenshot embedded — so
the page reads whole in git, Obsidian or an agent's recall. The only thing written under ``entities/`` here is that
section. Vectors are not here: ``design_index`` keeps them outside the bank, derived and disposable.

Every door goes through here — REST (``routers/design.py``), MCP (``mcp_tools.save_design``), the demo generator — so
the id rule, the scrub and the bounds cannot drift. Callers pass the ACTIVE bank (the split-brain rule) and commit the
memory-relative ``paths`` a write returns, each under its own author. Nothing here commits, and nothing raises on a
normal input: a refusal is a dict whose ``action`` is ``error`` or ``duplicate`` with one ``error`` sentence, and it
wrote nothing (the ``backlog`` contract).
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from loguru import logger

from api.services import design_palette, design_tokens, entity_picture, episode_scrub, image_decode, markdown_parser

DESIGN_DIR = "design"
ASSETS = ("assets", "design")
#: The bank keeps the screenshot, so it is bounded: the app shrinks a capture to ``APP_MAX_SIDE`` before it leaves.
MAX_IMAGE_BYTES = 4 * 1024 * 1024
APP_MAX_SIDE = 2560
MIN_SIDE = 32
MAX_SIDE = 8192
IMAGE_EXTS = ("png", "jpg")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg"}
TITLE_CHARS = 200
NOTE_CHARS = 8_000
SNIPPET_CHARS = 20_000
MAX_SNIPPETS = 12
MAX_TAGS = 12
URL_CHARS = 2_000
USER = "user"
#: ``explore``: kept automatically from an explore visit whose reason was the design (G166 slice 2).
VIAS = ("app_capture", "drop", "paste", "agent", "import", "demo", "explore")
SNIPPET_LANGS = ("html", "css", "js", "jsx", "tsx", "svg", "swift", "text")
#: Type specimens (looks polish): at most ``design_tokens.MAX_SPECIMENS`` per look, each a transparent PNG this small.
SPECIMEN_MAX_W, SPECIMEN_MAX_H = 400, 120
SPECIMEN_MIN_SIDE = 8
MAX_SPECIMEN_BYTES = 96 * 1024
LIKED_HEAD = "## What I liked"
NOTED_PREFIX = "## Noted by "
AGENT = "agent"
SNIPPETS_HEAD = "## Snippets"
NO_NOTE = "_No note yet._"
SHAPE = "design-2"
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]{0,60}$")
_FENCE = re.compile(r"^```([A-Za-z0-9_+-]*)[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
_HEADING = re.compile(r"(?m)^#{1,3}(?=[ \t])")
_NOTED = re.compile(r"(?m)^## Noted by [^\n]{1,80}$")


@dataclass
class Reference:
    id: str
    title: str = ""
    url: str | None = None
    site: str | None = None
    captured: str = ""
    added_by: str = USER
    session: str | None = None
    via: str = "drop"
    image: dict = field(default_factory=dict)      # {file, sha256, width, height, bytes}
    palette: list[dict] = field(default_factory=list)
    look: list[str] = field(default_factory=list)
    tokens: dict = field(default_factory=dict)
    computed: dict = field(default_factory=dict)   # design_tokens: the type and colour roles the page renders
    note_by: str = USER                             # who wrote the note: the person, or the agent that saved it
    tags: list[str] = field(default_factory=list)
    entity: str | None = None
    region: dict | None = None
    note: str = ""
    snippets: list[dict] = field(default_factory=list)   # [{lang, code}]
    specimens: list[dict] = field(default_factory=list)  # [{family, file, sha256, width, height}]
    extra: dict = field(default_factory=dict)

    @property
    def path(self) -> str:
        return f"{DESIGN_DIR}/{self.id}.md"

    @property
    def image_path(self) -> str | None:
        return self.image.get("file") if self.image else None

    @property
    def day(self) -> str:
        return (self.captured or "")[:10]


def _error(message: str, **extra) -> dict:
    return {"action": "error", "error": message, **extra}


def _scrub(text: str, bank: str | None) -> str:
    cleaned, n = episode_scrub.scrub(text or "")
    episode_scrub.record("design", n, bank=bank)
    return cleaned


def _clean_line(text: str, cap: int) -> str:
    return " ".join(str(text or "").split())[:cap]


def site_of(url: str | None) -> str | None:
    try:
        host = (urlsplit(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return None
    return host[4:] if host.startswith("www.") else (host or None)


def clean_url(url: str | None) -> str | None:
    """An ``http(s)`` URL with no credentials, or None (nothing else is kept)."""
    raw = str(url or "").strip()
    if not raw or len(raw) > URL_CHARS:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return None
    return raw


def slug(text: str, cap: int = 40) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:cap].strip("-")
    return s or "look"


def _stamp(now: datetime | None) -> str:
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- reading


def _root(memory_path) -> Path:
    return Path(memory_path) / DESIGN_DIR


def _section(body: str, head: str) -> str:
    """The text under a ``## `` heading of its own line (a demoted ``#### `` in a note never matches), to the next."""
    m = re.search(rf"(?m)^{re.escape(head)}[ \t]*$", body)
    if m is None:
        return ""
    rest = body[m.end():]
    nxt = re.search(r"(?m)^## ", rest)
    return (rest[: nxt.start()] if nxt else rest).strip()


def _from_file(path: Path) -> Reference | None:
    try:
        parsed = markdown_parser.parse(path)
    except Exception as exc:  # noqa: BLE001 — a hand-broken file is skipped, never fatal
        logger.debug(f"design_refs: unreadable {path.name}: {type(exc).__name__}")
        return None
    fm = dict(parsed.frontmatter or {})
    rid = str(fm.pop("id", "") or path.stem)
    if rid != path.stem:
        rid = path.stem
    note = _section(parsed.body, LIKED_HEAD)
    if not note and (m := _NOTED.search(parsed.body)) is not None:
        note = _section(parsed.body, m.group(0))
    if note == NO_NOTE:
        note = ""
    snippets = [{"lang": (m.group(1) or "text").lower(), "code": m.group(2).rstrip("\n")}
                for m in _FENCE.finditer(_section(parsed.body, SNIPPETS_HEAD))]
    known = {"title", "url", "site", "captured", "added_by", "session", "via", "image", "palette", "look", "tokens",
             "tags", "entity", "region", "computed", "note_by", "specimens"}
    image = fm.get("image") if isinstance(fm.get("image"), dict) else {}
    return Reference(
        id=rid, title=str(fm.get("title") or ""), url=fm.get("url") or None, site=fm.get("site") or None,
        captured=str(fm.get("captured") or ""), added_by=str(fm.get("added_by") or USER),
        session=fm.get("session") or None, via=str(fm.get("via") or "drop"), image=dict(image or {}),
        palette=[c for c in (fm.get("palette") or []) if isinstance(c, dict) and c.get("hex")],
        look=[str(w) for w in (fm.get("look") or [])], tokens=dict(fm.get("tokens") or {}),
        computed=design_tokens.clean(fm.get("computed"))[0] if isinstance(fm.get("computed"), dict) else {},
        note_by=_note_by(fm),
        tags=[str(t) for t in (fm.get("tags") or [])], entity=fm.get("entity") or None,
        region=fm.get("region") if isinstance(fm.get("region"), dict) else None, note=note, snippets=snippets,
        specimens=_stored_specimens(rid, fm.get("specimens")),
        extra={k: v for k, v in fm.items() if k not in known})


def specimen_rel(ref_id: str, n: int) -> str:
    """A specimen's bank-relative file: ``assets/design/<id>.type-<n>.png``, ``n`` from 1."""
    return f"{'/'.join(ASSETS)}/{ref_id}.type-{n}.png"


def _side(value, cap: int) -> int | None:
    """A specimen's side as written, or None when it is not a whole number in ``0..cap`` (a hand edit)."""
    if isinstance(value, bool):
        return None
    if value is None:
        return 0
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and value.strip().isdigit():
        n = int(value.strip())
    else:
        return None
    return n if 0 <= n <= cap else None


def _stored_specimens(ref_id: str, raw) -> list[dict]:
    """The frontmatter's specimens: entry ``n`` (from 1) only at its own name ``…type-<n>.png`` (a hand-edited path
    never points elsewhere), and one with a hand-broken field is skipped — never a failed read of the board."""
    out: list[dict] = []
    for n, item in enumerate(list(raw or [])[: design_tokens.MAX_SPECIMENS] if isinstance(raw, list) else [], 1):
        if not isinstance(item, dict) or not isinstance(item.get("family"), str):
            continue
        if item.get("file") != specimen_rel(ref_id, n):
            continue
        width, height = _side(item.get("width"), SPECIMEN_MAX_W), _side(item.get("height"), SPECIMEN_MAX_H)
        if width is None or height is None:
            continue
        out.append({"family": item["family"][: design_tokens.MAX_FAMILY], "file": item["file"],
                    "sha256": str(item.get("sha256") or "")[:64], "width": width, "height": height})
    return out


def specimen_number(ref_id: str, entry: dict) -> int | None:
    """Which ``n`` a stored specimen is (its file's own number), or None."""
    for n in range(1, design_tokens.MAX_SPECIMENS + 1):
        if entry.get("file") == specimen_rel(ref_id, n):
            return n
    return None


def _note_by(fm: dict) -> str:
    """Who wrote a reference's note. Written since looks v2; before it, inferred: a look kept from an explore visit
    carries the person's own words about the save; one saved through an agent door is the agent's, whatever author
    the door stamped (the REST door stamped ``user`` for an agent until looks v2)."""
    given = str(fm.get("note_by") or "").strip()
    if given:
        return given
    added_by, via = str(fm.get("added_by") or USER), str(fm.get("via") or "drop")
    if via == "explore":
        return USER
    if added_by != USER:
        return added_by
    return AGENT if via == "agent" else USER


def note_heading(ref: "Reference") -> str:
    """The body's heading over the note: the person's words, or the agent that wrote it, by its name."""
    if ref.note_by == USER:
        return LIKED_HEAD
    return NOTED_PREFIX + _clean_line(agent_label(ref.note_by), 60)


def agent_label(author: str) -> str:
    """An agent's name as the person reads it (the Sources page's one harness table)."""
    from api.services.source_overview import HARNESS_LABELS

    if author in (AGENT, "unknown", ""):
        return "an agent"
    return HARNESS_LABELS.get(author) or author


def list_refs(memory_path) -> list[Reference]:
    """Every reference, newest capture first (id breaks a tie)."""
    root = _root(memory_path)
    if not root.is_dir():
        return []
    refs = [r for p in root.glob("*.md") if ID_RE.match(p.stem) and (r := _from_file(p)) is not None]
    return sorted(refs, key=lambda r: (r.captured, r.id), reverse=True)


def get_ref(memory_path, ref_id: str) -> Reference | None:
    if not ID_RE.match(str(ref_id or "")):
        return None
    path = _root(memory_path) / f"{ref_id}.md"
    return _from_file(path) if path.is_file() else None


def image_file(memory_path, ref: Reference) -> tuple[Path, str] | None:
    """The screenshot's path and media type, only inside the bank's own ``assets/design/``."""
    rel = ref.image_path or ""
    ext = rel.rsplit(".", 1)[-1] if "." in rel else ""
    if ext not in IMAGE_EXTS or rel != f"{'/'.join(ASSETS)}/{ref.id}.{ext}":
        return None
    path = Path(memory_path) / rel
    return (path, MEDIA_TYPES[ext]) if path.is_file() else None


def specimen_file(memory_path, ref: Reference, n: int) -> Path | None:
    """Specimen ``n`` (from 1)'s path, only inside the bank's own ``assets/design/`` and only when it is there."""
    if not isinstance(n, int) or not 1 <= n <= design_tokens.MAX_SPECIMENS:
        return None
    rel = specimen_rel(ref.id, n)
    if not any(s.get("file") == rel for s in ref.specimens):
        return None
    path = Path(memory_path) / rel
    return path if path.is_file() else None


def stamp(memory_path) -> str:
    """``sync_service``'s ``design`` component: every reference file's name, size and mtime (a stat walk, no parse)."""
    from api.services import bank_index

    return bank_index.dir_fingerprint(_root(memory_path))


# --------------------------------------------------------------------------- writing


def validate_image(data: bytes) -> str:
    """The extension to keep a screenshot under, or ValueError with a sentence the person reads."""
    if not data:
        raise ValueError("That image is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("That screenshot is too large — Cicada keeps screenshots under 4 MB. "
                         "The app shrinks one first; an agent can send a smaller PNG or JPEG.")
    ext = entity_picture.sniff(data)
    if ext is None:
        raise ValueError("Cicada keeps screenshots as PNG or JPEG.")
    size = entity_picture.dimensions(data)
    if size is None:
        raise ValueError("Cicada couldn't read that screenshot's size.")
    if min(size) < MIN_SIDE:
        raise ValueError("That image is too small to be a screenshot.")
    if max(size) > MAX_SIDE:
        raise ValueError("That screenshot is bigger than Cicada keeps.")
    return ext


def validate_specimen(data: bytes) -> tuple[int, int]:
    """A specimen's ``(width, height)``, or ValueError: a PNG with an alpha channel (the app tints it to the text
    colour of either appearance), at most 400×120 px and 96 KB."""
    if not data or len(data) > MAX_SPECIMEN_BYTES:
        raise ValueError("a type specimen is a small PNG")
    if entity_picture.sniff(data) != "png" or len(data) < 26 or data[12:16] != b"IHDR":
        raise ValueError("a type specimen is a PNG")
    if data[25] not in (4, 6):   # IHDR colour type: grey or truecolour WITH alpha
        raise ValueError("a type specimen has a transparent ground")
    size = entity_picture.dimensions(data)
    if size is None:
        raise ValueError("a type specimen's size can't be read")
    w, h = size
    if w > SPECIMEN_MAX_W or h > SPECIMEN_MAX_H or min(w, h) < SPECIMEN_MIN_SIDE:
        raise ValueError("a type specimen is at most 400 by 120 pixels")
    return int(w), int(h)


def _specimens(raw, computed: dict) -> tuple[list[dict], list[bytes]]:
    """``(entries, bytes)`` for the specimens a save handed over (``[{family, data}]``): only a family the page's
    computed type names, once each, in the specimen model's order, each validated; the rest are dropped (a bad
    specimen never stops a save — provenance never blocks memory)."""
    wanted = [s["family"] for s in design_tokens.specimens(computed)]
    given: dict[str, bytes] = {}
    for item in list(raw or [])[: design_tokens.MAX_SPECIMENS * 2]:
        if not isinstance(item, dict) or not isinstance(item.get("data"), (bytes, bytearray)):
            continue
        family, _ = design_tokens.family_of(item.get("family"))
        if family and family.lower() not in given:
            given[family.lower()] = bytes(item["data"])
    entries: list[dict] = []
    blobs: list[bytes] = []
    for family in wanted:
        data = given.get(family.lower())
        if data is None:
            continue
        try:
            w, h = validate_specimen(data)
        except ValueError:
            continue
        entries.append({"family": family, "sha256": hashlib.sha256(data).hexdigest(), "width": w, "height": h})
        blobs.append(data)
    return entries, blobs


def _snippets(raw, bank: str | None) -> list[dict]:
    out = []
    for item in list(raw or [])[:MAX_SNIPPETS]:
        if isinstance(item, str):
            item = {"lang": "text", "code": item}
        if not isinstance(item, dict):
            continue
        code = _scrub(str(item.get("code") or ""), bank).replace("```", "``​`")[:SNIPPET_CHARS].rstrip()
        if not code.strip():
            continue
        lang = str(item.get("lang") or "text").strip().lower()
        out.append({"lang": lang if lang in SNIPPET_LANGS else "text", "code": code})
    return out


def _body(ref: Reference) -> str:
    title = ref.title or ref.site or "A look I liked"
    parts = [f"# {title}", ""]
    if ref.image_path:
        parts += [f"![Screenshot](../{ref.image_path})", ""]
    if ref.url:
        parts += [f"From <{ref.url}>", ""]
    explored = ref.extra.get("explored") if isinstance(ref.extra.get("explored"), dict) else None
    if explored:
        parts += [f"Kept while exploring {explored.get('site') or 'the site'} on "
                  f"{str(explored.get('captured_at') or '')[:10]} — the {explored.get('page_kind') or 'home'} page, "
                  f"capture {explored.get('capture')}.", ""]
    parts += [note_heading(ref), "", _HEADING.sub(lambda m: "#" * 4, ref.note) if ref.note else NO_NOTE, ""]
    if ref.snippets:
        parts += [SNIPPETS_HEAD, ""]
        for s in ref.snippets:
            parts += [f"```{s['lang']}", s["code"], "```", ""]
    return "\n".join(parts).rstrip() + "\n"


def _frontmatter(ref: Reference) -> dict:
    fm: dict = {"id": ref.id, "title": ref.title}
    if ref.url:
        fm["url"] = ref.url
    if ref.site:
        fm["site"] = ref.site
    fm.update({"captured": ref.captured, "added_by": ref.added_by})
    if ref.session:
        fm["session"] = ref.session
    fm["via"] = ref.via
    if ref.image:
        fm["image"] = ref.image
    if ref.region:
        fm["region"] = ref.region
    if ref.palette:
        fm["palette"] = ref.palette
    if ref.look:
        fm["look"] = ref.look
    if ref.tokens:
        fm["tokens"] = ref.tokens
    if ref.computed:
        fm["computed"] = ref.computed
    if ref.note_by != USER:
        fm["note_by"] = ref.note_by
    if ref.tags:
        fm["tags"] = ref.tags
    if ref.entity:
        fm["entity"] = ref.entity
    if ref.specimens:
        fm["specimens"] = ref.specimens
    fm.update(ref.extra)
    return fm


def _region(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    try:
        out = {k: int(raw[k]) for k in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    return out if out["width"] > 0 and out["height"] > 0 else None


def read_look(data: bytes, declared=None) -> tuple[list[dict], list[str]]:
    """The screenshot's palette and its words — ``([], [])`` when this host can't decode it (the save stands).
    ``declared`` are the colours the page's CSS or computed tokens name (:func:`declared_colours`), merged in."""
    try:
        rgb = image_decode.decode(data, max_side=design_palette.SAMPLE_SIDE)
    except image_decode.DecodeError:
        return [], []
    colours = design_palette.palette(rgb, declared=declared)
    return colours, design_palette.describe(colours)


def declared_colours(snippets=None, computed: dict | None = None) -> list[str]:
    """The colours a save declares: the computed colour roles and most-used colours first, then the snippets' CSS."""
    out = list(design_tokens.declared(computed))
    codes = [str(s.get("code") or "") if isinstance(s, dict) else str(s) for s in list(snippets or [])[:MAX_SNIPPETS]]
    if any(codes):
        for c in design_palette.css_tokens("\n".join(codes)).get("colors") or []:
            if c not in out:
                out.append(c)
    return out[:16]


def resolve_author(author: str | None, via: str | None) -> str:
    """The author a write is stamped with: an agent door (``via=agent``) never writes as the person — with no agent
    named it is the generic ``agent``."""
    name = str(author or "").strip() or USER
    if via == "agent" and name == USER:
        return AGENT
    return name


def fonts(ref: "Reference") -> list[str]:
    """The families a look is set in: what the page renders (computed, body first), then what the snippets named."""
    out = design_tokens.fonts(ref.computed)
    for name in (ref.tokens or {}).get("fonts") or []:
        if name not in out:
            out.append(name)
    return out


def add_ref(memory_path, *, image: bytes, url: str | None = None, title: str | None = None, note: str | None = None,
            snippets=None, tags=None, region=None, entity: str | None = None, via: str = "drop",
            author: str = USER, session: str | None = None, now: datetime | None = None,
            look: tuple[list[dict], list[str]] | None = None, explored: dict | None = None,
            computed=None, note_by: str | None = None, specimens=None, attach_auto: bool = True) -> dict:
    """File one reference: ``{"action": "added", "ref", "paths"}``, or a refusal that wrote nothing.

    ``look`` is the palette and its words when the caller already read them (a route reads them before it takes
    the write admission, so Sleep never waits on a decode). ``explored`` is an explore visit's provenance for a Look
    kept automatically (G166 slice 2): ``{site, captured_at, capture, entity, page_kind}`` — the site and the date the
    picture is of, and the dated capture record it came from.

    ``computed`` is the page's computed type and colour roles (``design_tokens``, validated here). ``note_by`` is who
    wrote the note: by default the author — an agent's note is the agent's — and the person (``user``) only where the
    words are theirs and Cicada itself read them (an explore Look's note is their saved reason).

    ``specimens`` are the capture's type specimens, ``[{family, data}]`` (looks polish): kept beside the screenshot,
    one per family the computed type names, at most six, each a transparent PNG of at most 400×120 px.

    ``entity`` is the page the look shows (owner 2026-10-20): a page that exists, never one created. With none given
    (and ``attach_auto``), :func:`subject_for` finds it — the one page whose trusted site is the look's, else the saved
    link's own page — or leaves the look unattached. An attached look's page gets its ``## Looks`` line in the same
    write (under the page lock); ``paths`` then carries the page, and ``attached`` says how (``given``, ``site``,
    ``link``) or is None."""
    bank = Path(memory_path).name
    try:
        ext = validate_image(image)
    except ValueError as exc:
        return _error(str(exc))
    sha = hashlib.sha256(image).hexdigest()
    for existing in list_refs(memory_path):
        if (existing.image or {}).get("sha256") == sha:
            return {"action": "duplicate", "error": "That screenshot is already on your board.", "id": existing.id,
                    "ref": existing}
    width, height = entity_picture.dimensions(image) or (0, 0)
    url_kept = clean_url(url)
    if url and url_kept is None:
        return _error("That link isn't one Cicada keeps — an http or https address without a password.")
    site = site_of(url_kept)
    title_kept = _clean_line(_scrub(title or "", bank), TITLE_CHARS)
    note_kept = _scrub(str(note or ""), bank).strip()[:NOTE_CHARS]
    kept_snippets = _snippets(snippets, bank)
    tokens = design_palette.css_tokens("\n".join(s["code"] for s in kept_snippets)) if kept_snippets else {}
    tokens = {k: v for k, v in tokens.items() if v}
    computed_kept, _ = design_tokens.clean(computed)
    colours, words = look if look is not None else read_look(image, declared_colours(kept_snippets, computed_kept))
    specimen_entries, specimen_blobs = _specimens(specimens, computed_kept)
    author = resolve_author(author, via)
    captured = _stamp(now)
    day = captured[:10]
    base = f"{day}-{slug(site or title_kept or 'look')}"
    entity_id = str(entity or "").strip() or None
    how: str | None = "given" if entity_id else None
    if entity_id and not page_exists(memory_path, entity_id):
        entity_id, how = None, None   # a reference may point at a page; it never creates one
    if entity_id is None and attach_auto:
        entity_id, found = subject_for(memory_path, url_kept)
        how = found if entity_id else None
    ref = Reference(
        id=base, title=title_kept, url=url_kept, site=site, captured=captured, added_by=(author or USER).strip(),
        session=session or None, via=via if via in VIAS else "drop", palette=colours, look=words, tokens=tokens,
        computed=computed_kept, note_by=(str(note_by or "").strip() or author),
        tags=[_clean_line(t, 40) for t in list(tags or [])[:MAX_TAGS] if _clean_line(t, 40)],
        entity=entity_id, region=_region(region), note=note_kept, snippets=kept_snippets)
    if isinstance(explored, dict):
        ref.extra["explored"] = {k: _clean_line(str(explored[k]), 200) for k in
                                 ("site", "captured_at", "capture", "entity", "page_kind", "page_url")
                                 if explored.get(k)}
    root = _root(memory_path)
    root.mkdir(parents=True, exist_ok=True)
    assets = Path(memory_path).joinpath(*ASSETS)
    assets.mkdir(parents=True, exist_ok=True)
    for n in range(1, 200):
        ref.id = base if n == 1 else f"{base}-{n}"
        ref.image = {"file": f"{'/'.join(ASSETS)}/{ref.id}.{ext}", "sha256": sha, "width": int(width),
                     "height": int(height), "bytes": len(image)}
        ref.specimens = [{**e, "file": specimen_rel(ref.id, i)} for i, e in enumerate(specimen_entries, 1)]
        try:
            markdown_parser.write_new(root / f"{ref.id}.md", _frontmatter(ref), _body(ref))
        except FileExistsError:
            continue
        break
    else:
        return _error("Cicada couldn't find a free name for this reference.")
    files = [(assets / f"{ref.id}.{ext}", image)]
    files += [(Path(memory_path) / s["file"], blob) for s, blob in zip(ref.specimens, specimen_blobs)]
    written: list[Path] = []
    try:
        for target, data in files:
            tmp = target.with_name(f".{target.name}.partial")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            written.append(target)
    except OSError as exc:
        for target in written:
            target.unlink(missing_ok=True)
        (root / f"{ref.id}.md").unlink(missing_ok=True)
        return _error(f"The screenshot couldn't be saved ({type(exc).__name__}).")
    paths = [ref.path, ref.image_path, *(s["file"] for s in ref.specimens)]
    if ref.entity:
        from api.services import page_lock

        with page_lock.page_lock(memory_path):
            if (page := sync_page(memory_path, ref.entity)) is not None:
                paths.append(page)
    return {"action": "added", "ref": ref, "paths": paths, "attached": how if ref.entity else None}


_UNSET = object()


def update_ref(memory_path, ref_id: str, *, title=_UNSET, url=_UNSET, note=_UNSET) -> dict:
    """The person's own words on a look (owner 2026-10-20: the look's sheet edits what they liked, its name and its
    link): ``{"action": "updated" | "unchanged", "ref", "paths"}`` or a refusal that wrote nothing. Every text is
    scrubbed; a note written here is the person's (``note_by: user``, under "What I liked"); the record's body is
    rendered again from the record, and the page it is on gets its ``## Looks`` line again (a new name). The person's
    door only — an agent's words go through a new save. The caller holds the admission and the page lock and commits."""
    ref = get_ref(memory_path, ref_id)
    if ref is None:
        return {"action": "not_found", "error": "No such look."}
    bank = Path(memory_path).name
    changed = False
    if title is not _UNSET:
        kept = _clean_line(_scrub(str(title or ""), bank), TITLE_CHARS)
        changed |= kept != ref.title
        ref.title = kept
    if url is not _UNSET:
        raw = str(url or "").strip()
        kept_url = clean_url(raw) if raw else None
        if raw and kept_url is None:
            return _error("That link isn't one Cicada keeps — an http or https address without a password.")
        changed |= kept_url != ref.url
        ref.url, ref.site = kept_url, site_of(kept_url)
    if note is not _UNSET:
        kept_note = _scrub(str(note or ""), bank).strip()[:NOTE_CHARS]
        changed |= kept_note != ref.note or ref.note_by != USER
        ref.note, ref.note_by = kept_note, USER
    if not changed:
        return {"action": "unchanged", "ref": ref, "paths": []}
    path = _root(memory_path) / f"{ref.id}.md"
    markdown_parser.write(path, _frontmatter(ref), _body(ref))   # every other key rides in `ref.extra`
    paths = [ref.path]
    if ref.entity and (page := sync_page(memory_path, ref.entity)) is not None:
        paths.append(page)
    return {"action": "updated", "ref": ref, "paths": paths}


def remove_ref(memory_path, ref_id: str, *, author: str = USER) -> dict:
    """Remove a reference and its screenshot: ``{"action": "removed", "paths"}``. An agent removes only what it
    added (the rail for every agent write); the person removes anything."""
    ref = get_ref(memory_path, ref_id)
    if ref is None:
        return {"action": "not_found", "error": "No such reference on your board."}
    if author != USER and ref.added_by != author:
        return _error("An agent removes only the references it added.")
    paths = [ref.path]
    found = image_file(memory_path, ref)
    if found is not None:
        found[0].unlink(missing_ok=True)
        paths.append(ref.image_path)
    for n in range(1, design_tokens.MAX_SPECIMENS + 1):
        spec = Path(memory_path) / specimen_rel(ref.id, n)   # a skipped (hand-broken) entry's file goes too
        if spec.is_file():
            spec.unlink(missing_ok=True)
            paths.append(specimen_rel(ref.id, n))
    (Path(memory_path) / ref.path).unlink(missing_ok=True)
    if ref.entity:
        from api.services import page_lock

        with page_lock.page_lock(memory_path):
            if (page := sync_page(memory_path, ref.entity)) is not None:
                paths.append(page)
    return {"action": "removed", "ref": ref, "paths": paths}


def commit_message(paths: list[str], *, action: str, subject: str, trigger: str, day: str, author: str = USER,
                   session: str | None = None) -> str:
    """The house commit for a design write: one manifest line per file, the author, the conversation if any."""
    from api.services import git_service

    return git_service.build_commit_message(
        f"{subject} {day}",
        # A page the look is on only had its `## Looks` section written: it is updated, whatever the look was.
        [f"{p}: {'updated' if p.startswith('entities/') else action} (source: n/a, trigger: {trigger})"
         for p in dict.fromkeys(paths)],
        authors=[author], sessions=[session] if session else None)


def words(ref: Reference) -> str:
    """Everything a word search reads for one reference, lowercased."""
    tokens = ref.tokens or {}
    generic = [str((t or {}).get("generic") or "") for t in ((ref.computed or {}).get("type") or {}).values()]
    bits = [ref.title, ref.site or "", ref.url or "", ref.note, " ".join(ref.look), " ".join(ref.tags),
            " ".join(fonts(ref)), " ".join(tokens.get("generic") or []), " ".join(g for g in generic if g),
            " ".join(c["hex"] for c in ref.palette)]
    return " ".join(b for b in bits if b).lower()


def describe_for_embedding(ref: Reference) -> str:
    """The text a reference's note vector is built from: what the person said, then what the look is made of."""
    names = fonts(ref)
    parts = [ref.title, ref.note, ("Looks " + ", ".join(ref.look)) if ref.look else "",
             ("Fonts: " + ", ".join(names)) if names else "",
             (f"From {ref.site}") if ref.site else ""]
    return ". ".join(p.strip() for p in parts if p and p.strip())


# --------------------------------------------------------------------------- the page a look shows (owner 2026-10-20)
#
# "This should be ingrained in the markdown of a specific thing." A look belongs to the page of the thing it shows —
# a website, a product, a project — and that page's markdown says so in its own ``## Looks`` section. The record stays
# here, one file per look (its palette, tokens, specimens, note and history are the look's, and a page's prose rewrite
# can never lose them); the record's ``entity:`` is the attachment, and the page's section is its rendering: one bullet
# per look, newest first, a link to the record and its screenshot embedded, so git, GitHub, Obsidian and an agent
# reading the page all see it. This module is the section's ONE writer; Sleep's writers carry it as a canonical
# record section (``entity_body.CANONICAL_SECTIONS``) and never write one (the article writer's titles refuse it).

LOOKS_SECTION = "Looks"
#: Anchored to the whole line: a hand-written "## Looks and feel" is the person's section, never this one.
_LOOKS_HEAD = re.compile(r"(?m)^## Looks[ \t]*$\n?")
_H1_H2 = re.compile(r"(?m)^#{1,2}[ \t]")
_BRACKETS = re.compile(r"[\[\]]")
#: A subject is a real page id, never a path (the same shape ``fact_sources`` and the routes accept).
ENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def _page(memory_path, entity_id: str | None) -> Path | None:
    eid = str(entity_id or "").strip()
    if not eid or not ENTITY_RE.match(eid) or eid.startswith("."):
        return None
    path = Path(memory_path) / "entities" / f"{eid}.md"
    return path if path.is_file() else None


def page_exists(memory_path, entity_id: str | None) -> bool:
    return _page(memory_path, entity_id) is not None


def refs_for(memory_path, entity_id: str, refs: list[Reference] | None = None) -> list[Reference]:
    """The looks attached to one page, newest first."""
    return [r for r in (refs if refs is not None else list_refs(memory_path)) if r.entity == entity_id]


def section_line(ref: Reference) -> str:
    """One look on its page: the record linked by its title (site · day after it), the screenshot embedded below."""
    title = _BRACKETS.sub("", ref.title or ref.site or "A look") or "A look"
    bits = [f"- [{title}](../{ref.path})"]
    if ref.site:
        bits.append(ref.site)
    if ref.day:
        bits.append(ref.day)
    line = " · ".join(bits)
    if ref.image_path:
        line += f"\n  ![{title}](../{ref.image_path})"
    return line


def page_section(refs: list[Reference]) -> str:
    """The ``## Looks`` section's content for these looks (empty when there are none)."""
    return "\n".join(section_line(r) for r in refs)


def _section_span(prose: str) -> tuple[int, int] | None:
    """Where the page's ``## Looks`` section runs in its prose (heading included), or None."""
    m = _LOOKS_HEAD.search(prose)
    if m is None:
        return None
    nxt = _H1_H2.search(prose, m.end())
    return m.start(), (nxt.start() if nxt else len(prose))


def with_section(prose: str, content: str) -> str:
    """``prose`` with its ``## Looks`` section set to ``content`` — replaced in place, inserted in its canonical place
    (before ``## Open Questions`` or any section after it) when absent, removed when ``content`` is empty. Nothing
    else in the prose moves: this is a surgical edit, never a re-render of the page."""
    from api.services import entity_body

    block = f"## {LOOKS_SECTION}\n{content.strip()}\n\n" if content.strip() else ""
    span = _section_span(prose)
    if span is not None:
        start, end = span
        out = prose[:start] + block + prose[end:].lstrip("\n")
    elif not block:
        return prose
    else:
        order = entity_body.CANONICAL_SECTIONS
        before = set(order[: order.index(LOOKS_SECTION)])
        at = None
        for m in re.finditer(r"(?m)^##[ \t]+(.+?)[ \t]*$", prose):
            if m.group(1).strip() not in before:
                at = m.start()
                break
        if at is None:
            out = prose.rstrip() + ("\n\n" if prose.strip() else "") + block
        else:
            out = prose[:at] + block + prose[at:]
    return out.rstrip() + "\n"


def sync_page(memory_path, entity_id: str, refs: list[Reference] | None = None) -> str | None:
    """Write the page's ``## Looks`` section from the looks attached to it: the page's memory-relative path when it
    changed, None when it was already right (or there is no such page). The prose before the claims fence is edited;
    the fence and everything after it are put back byte for byte, and the claims ledger is never opened (the
    ``page_edits`` rule). The caller holds the page lock and commits the path."""
    from api.services import page_edits

    page = _page(memory_path, entity_id)
    if page is None:
        return None
    parsed = markdown_parser.parse(page, ledger=False)
    prose, rest = page_edits.split_prose(parsed.body)
    new_prose = with_section(prose, page_section(refs_for(memory_path, entity_id, refs)))
    if new_prose.rstrip() == prose.rstrip():
        return None
    body = new_prose + ("\n" + rest if rest else "")
    markdown_parser.write(page, dict(parsed.frontmatter or {}), body)
    return f"entities/{page.name}"


def _set_entity(memory_path, ref: Reference, entity_id: str | None) -> None:
    """The record's ``entity:`` and nothing else: its body (the note, the snippets) is left exactly as it is."""
    path = _root(memory_path) / f"{ref.id}.md"
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter or {})
    if entity_id:
        fm["entity"] = entity_id
    else:
        fm.pop("entity", None)
    markdown_parser.write(path, fm, parsed.body)
    ref.entity = entity_id


def attach(memory_path, ref_id: str, entity_id: str | None, *, author: str = USER) -> dict:
    """Put a look on a page (or take it off one, ``entity_id`` None): ``{"action": "attached" | "detached" |
    "unchanged", "ref", "paths"}`` — the record and both pages' sections — or a refusal that wrote nothing. A look is
    attached only to a page that exists (it never creates one). An agent moves only a look it added. The caller holds
    the write admission and the page lock, and commits ``paths``."""
    ref = get_ref(memory_path, ref_id)
    if ref is None:
        return {"action": "not_found", "error": "No such look."}
    if author != USER and ref.added_by != author:
        return _error("An agent moves only the looks it added.")
    target = str(entity_id or "").strip() or None
    if target is not None and not page_exists(memory_path, target):
        return _error("That page isn't in memory, so the look can't go on it.")
    before = ref.entity if page_exists(memory_path, ref.entity) else None
    if ref.entity == target:
        paths = [p for p in [sync_page(memory_path, target)] if p] if target else []
        return {"action": "unchanged", "ref": ref, "paths": paths}
    _set_entity(memory_path, ref, target)
    refs = list_refs(memory_path)
    paths = [ref.path]
    for eid in dict.fromkeys(e for e in (before, target) if e):
        if (p := sync_page(memory_path, eid, refs)) is not None:
            paths.append(p)
    return {"action": "attached" if target else "detached", "ref": ref, "paths": paths}


def repoint(memory_path, old_id: str, new_id: str) -> list[str]:
    """A page merge (``entity_merge``): every look on ``old_id`` moves to ``new_id``, whose section is written again.
    The memory-relative paths written (the records, and the winner's page when its section changed)."""
    moved = [r for r in list_refs(memory_path) if r.entity == old_id]
    paths: list[str] = []
    for ref in moved:
        _set_entity(memory_path, ref, new_id)
        paths.append(ref.path)
    if moved and (p := sync_page(memory_path, new_id)) is not None:
        paths.append(p)
    return paths


def repoint_footprint(memory_path, old_id: str, new_id: str) -> list[str]:
    """What :func:`repoint` would write, without writing (a merge's manifest, G183(e))."""
    moved = [r.path for r in list_refs(memory_path) if r.entity == old_id]
    return moved + ([f"entities/{new_id}.md"] if moved else [])


def _site_key(host: str | None) -> str | None:
    host = (host or "").strip().lower()
    return (host[4:] if host.startswith("www.") else host) or None


def subject_for(memory_path, url: str | None, *, pages=None) -> tuple[str | None, str]:
    """The page a look of ``url`` shows — ``(entity_id, how)``, deterministic, no model, never a page invented:

    * ``site`` — exactly one page whose trusted ``website`` source (the one a page's mark is drawn from,
      ``logo_service``) is the look's site; two or more is ``ambiguous`` and attaches nothing;
    * ``link`` — else the saved link's own page, when the person saved exactly this URL (``url_index``);
    * ``none`` — else nothing: the look stays unattached until the person puts it on a page.

    ``pages`` is ``[(stem, frontmatter)]`` when the caller already read them (the migration reads them once)."""
    from api.services import bank_index, logo_service, media_ingestor

    site = _site_key(site_of(url))
    if not site:
        return None, "none"
    if pages is None:
        pages = [(f.stem, f.frontmatter or {}) for f in bank_index.files(Path(memory_path), "entities")]
    hits = []
    for stem, fm in pages:
        if str(fm.get("type") or "").lower() == "media" or str(fm.get("status") or "") == "dropped":
            continue
        if _site_key(logo_service._trusted_website_host(fm)) == site:
            hits.append(stem)
    if len(hits) == 1:
        return hits[0], "site"
    if len(hits) > 1:
        return None, "ambiguous"
    try:
        index = media_ingestor.load_url_index(Path(memory_path))
        entry = index.get(media_ingestor._primary(index, media_ingestor.url_hash(str(url))))
    except Exception:  # noqa: BLE001 — an unreadable index answers nothing, never a failed save
        entry = None
    eid = str((entry or {}).get("media_entity_id") or "") if isinstance(entry, dict) else ""
    if eid and page_exists(memory_path, eid):
        return eid, "link"
    return None, "none"
