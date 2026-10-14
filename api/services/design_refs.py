"""Design taste (owner, 2026-10-14): the looks the person likes are memory — one markdown file per reference, and
this module is the ONE reader and writer of them.

"Extracting the design/views/aesthetics of websites i like with screenshots and snippets and other stuff." A design
reference is the person saying *I like how this looks*: a screenshot of what they were looking at, the page it came
from, what they liked in their own words, and what the look is made of — its colours (read from the pixels here,
``design_palette``), its type and spacing (read from HTML/CSS they selected), and the snippets themselves. Each one is

* ``<bank>/design/<id>.md`` — frontmatter for what a board needs (url, site, the image's hash and size, the palette,
  the palette's words, the tokens, who added it and how) and a body an agent or Obsidian reads as it is: the
  screenshot embedded, ``## What I liked``, ``## Snippets`` as fenced code;
* ``<bank>/assets/design/<id>.<png|jpg>`` — the screenshot, **in the bank, committed with it**, like a picture the
  person uploaded (``entity_picture``): it is their own capture of something that may not look the same tomorrow, so
  it cannot be a cache that is fetched again. The bank handed over intact carries its looks.

**Never an entity page** (the closed set of 10 types stays closed): Stage 1 never reads ``design/``, nothing here
writes ``entities/``, and a reference never decays — a look the person liked does not become less true. A reference
may name a page it is about (``entity:``, a site's company or tool page) but never creates one. Vectors are not here:
``design_index`` keeps them outside the bank, derived and disposable.

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

from api.services import design_palette, entity_picture, episode_scrub, image_decode, markdown_parser

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
LIKED_HEAD = "## What I liked"
SNIPPETS_HEAD = "## Snippets"
NO_NOTE = "_No note yet._"
SHAPE = "design-1"
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]{0,60}$")
_FENCE = re.compile(r"^```([A-Za-z0-9_+-]*)[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
_HEADING = re.compile(r"(?m)^#{1,3}(?=[ \t])")


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
    tags: list[str] = field(default_factory=list)
    entity: str | None = None
    region: dict | None = None
    note: str = ""
    snippets: list[dict] = field(default_factory=list)   # [{lang, code}]
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
    if note == NO_NOTE:
        note = ""
    snippets = [{"lang": (m.group(1) or "text").lower(), "code": m.group(2).rstrip("\n")}
                for m in _FENCE.finditer(_section(parsed.body, SNIPPETS_HEAD))]
    known = {"title", "url", "site", "captured", "added_by", "session", "via", "image", "palette", "look", "tokens",
             "tags", "entity", "region"}
    image = fm.get("image") if isinstance(fm.get("image"), dict) else {}
    return Reference(
        id=rid, title=str(fm.get("title") or ""), url=fm.get("url") or None, site=fm.get("site") or None,
        captured=str(fm.get("captured") or ""), added_by=str(fm.get("added_by") or USER),
        session=fm.get("session") or None, via=str(fm.get("via") or "drop"), image=dict(image or {}),
        palette=[c for c in (fm.get("palette") or []) if isinstance(c, dict) and c.get("hex")],
        look=[str(w) for w in (fm.get("look") or [])], tokens=dict(fm.get("tokens") or {}),
        tags=[str(t) for t in (fm.get("tags") or [])], entity=fm.get("entity") or None,
        region=fm.get("region") if isinstance(fm.get("region"), dict) else None, note=note, snippets=snippets,
        extra={k: v for k, v in fm.items() if k not in known})


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
    parts += [LIKED_HEAD, "", _HEADING.sub(lambda m: "#" * 4, ref.note) if ref.note else NO_NOTE, ""]
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
    if ref.tags:
        fm["tags"] = ref.tags
    if ref.entity:
        fm["entity"] = ref.entity
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


def read_look(data: bytes) -> tuple[list[dict], list[str]]:
    """The screenshot's palette and its words — ``([], [])`` when this host can't decode it (the save stands)."""
    try:
        rgb = image_decode.decode(data, max_side=design_palette.SAMPLE_SIDE)
    except image_decode.DecodeError:
        return [], []
    colours = design_palette.palette(rgb)
    return colours, design_palette.describe(colours)


def add_ref(memory_path, *, image: bytes, url: str | None = None, title: str | None = None, note: str | None = None,
            snippets=None, tags=None, region=None, entity: str | None = None, via: str = "drop",
            author: str = USER, session: str | None = None, now: datetime | None = None,
            look: tuple[list[dict], list[str]] | None = None, explored: dict | None = None) -> dict:
    """File one reference: ``{"action": "added", "ref", "paths"}``, or a refusal that wrote nothing.

    ``look`` is the palette and its words when the caller already read them (a route reads them before it takes
    the write admission, so Sleep never waits on a decode). ``explored`` is an explore visit's provenance for a Look
    kept automatically (G166 slice 2): ``{site, captured_at, capture, entity, page_kind}`` — the site and the date the
    picture is of, and the dated capture record it came from."""
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
    colours, words = look if look is not None else read_look(image)
    captured = _stamp(now)
    day = captured[:10]
    base = f"{day}-{slug(site or title_kept or 'look')}"
    entity_id = str(entity or "").strip() or None
    if entity_id and not (Path(memory_path) / "entities" / f"{entity_id}.md").is_file():
        entity_id = None   # a reference may point at a page; it never creates one
    ref = Reference(
        id=base, title=title_kept, url=url_kept, site=site, captured=captured, added_by=(author or USER).strip(),
        session=session or None, via=via if via in VIAS else "drop", palette=colours, look=words, tokens=tokens,
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
        try:
            markdown_parser.write_new(root / f"{ref.id}.md", _frontmatter(ref), _body(ref))
        except FileExistsError:
            continue
        break
    else:
        return _error("Cicada couldn't find a free name for this reference.")
    target = assets / f"{ref.id}.{ext}"
    try:
        tmp = target.with_name(f".{target.name}.partial")
        tmp.write_bytes(image)
        os.replace(tmp, target)
    except OSError as exc:
        (root / f"{ref.id}.md").unlink(missing_ok=True)
        return _error(f"The screenshot couldn't be saved ({type(exc).__name__}).")
    return {"action": "added", "ref": ref, "paths": [ref.path, ref.image_path]}


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
    (Path(memory_path) / ref.path).unlink(missing_ok=True)
    return {"action": "removed", "ref": ref, "paths": paths}


def commit_message(paths: list[str], *, action: str, subject: str, trigger: str, day: str, author: str = USER,
                   session: str | None = None) -> str:
    """The house commit for a design write: one manifest line per file, the author, the conversation if any."""
    from api.services import git_service

    return git_service.build_commit_message(
        f"{subject} {day}", [f"{p}: {action} (source: n/a, trigger: {trigger})" for p in dict.fromkeys(paths)],
        authors=[author], sessions=[session] if session else None)


def words(ref: Reference) -> str:
    """Everything a word search reads for one reference, lowercased."""
    tokens = ref.tokens or {}
    bits = [ref.title, ref.site or "", ref.url or "", ref.note, " ".join(ref.look), " ".join(ref.tags),
            " ".join(tokens.get("fonts") or []), " ".join(tokens.get("generic") or []),
            " ".join(c["hex"] for c in ref.palette)]
    return " ".join(b for b in bits if b).lower()


def describe_for_embedding(ref: Reference) -> str:
    """The text a reference's note vector is built from: what the person said, then what the look is made of."""
    tokens = ref.tokens or {}
    parts = [ref.title, ref.note, ("Looks " + ", ".join(ref.look)) if ref.look else "",
             ("Fonts: " + ", ".join(tokens.get("fonts") or [])) if tokens.get("fonts") else "",
             (f"From {ref.site}") if ref.site else ""]
    return ". ".join(p.strip() for p in parts if p and p.strip())
