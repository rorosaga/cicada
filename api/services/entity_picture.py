"""G146 / G159 slice 1 — an entity's picture: one precedence, and the person's own upload (round-4 contract C11).

**The precedence** lives in ONE pure function, `resolve`, and the app runs its twin (`EntityPictureResolver.swift`);
both are held to `api/tests/fixtures/entity_picture.json`, so a rung added on one side only turns the other red (the
`timeline_state.json` precedent). Each type reaches only the rungs that mean something for it (plan R-PE3):

1. **the person's own choice** — a picture they uploaded, or "use initials" — on any page (round-4 decision 9: "the
   ability to add a picture like upload it manually maybe as a pfp");
2. **a Contacts photo**, `person` pages only (G154). T-Sources writes the optional `contacts_photo: {sha}` key and the
   bytes under `$CICADA_HOME/contacts/<bank>/`; until it lands no page carries the key and the rung never fires (R-PE7);
3. **the domain logo** (G59's ladder), never for a `person` or a `media` page: eligible for `company`/`tool` or a page
   whose own `logo:` names a domain, available when cached or not yet known to miss (R-PE9);
4. **the saved thumbnail**, `media` pages only, never a paper's (G133 fetches no arXiv page);
5. **nothing** — the app draws a ring monogram, never a solid fill.

A person gets rungs 1–2 only: a surname is not a domain (G59), and no service is ever sent a person's name (G159).

`resolve` does no I/O. `resolve_page` gathers one page's inputs from its frontmatter and the machine-global logo index,
read-only — `GET /graph` still never fetches, and `GET /entities/{id}/logo` is still the only place a logo is fetched.
"""
from __future__ import annotations

import hashlib
import os
import re
import struct
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from urllib.parse import quote

from loguru import logger

from api.services import logo_service, markdown_parser

#: R-PE1 — the person's pictures live in the bank, beside the pages that name them, so a handed-over bank keeps them.
PICTURES_DIR = ("assets", "pictures")
UPLOAD_EXTS = ("jpg", "png")
MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png"}
#: G59's brand types: the only ones whose logo is looked for without the page naming a domain (R-PE9).
LOGO_TYPES = frozenset(logo_service.GUESSABLE_TYPES)
#: R-PE7 — T-Sources' Contacts thumbnails: `$CICADA_HOME/contacts/<bank>/<id>.jpg`, outside every bank.
CONTACTS_DIR_NAME = "contacts"
#: `papers.KIND`, spelled here so `graph_builder`'s import of this module stays light; a test pins the two equal.
PAPER_KIND = "paper"
SOURCES = ("upload", "initials", "contacts", "logo", "thumbnail")
_SHA_RE = re.compile(r"[0-9a-f]{12}")
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MAX_URL = 2048


@dataclass(frozen=True)
class PictureInputs:
    """Everything `resolve` reads — and, on the wire as `pictureInputs`, what the app's twin re-resolves from to paint
    a removal before the server answers (R-PE10). `logo` is already eligibility AND availability, decided here."""

    type: str
    choice: str | None = None
    upload_sha: str | None = None
    contacts_sha: str | None = None
    logo: bool = False
    thumbnail: str | None = None

    @classmethod
    def from_wire(cls, raw: dict) -> "PictureInputs":
        return cls(type=str(raw.get("type") or "concept"), choice=raw.get("choice"), upload_sha=raw.get("uploadSha"),
                   contacts_sha=raw.get("contactsSha"), logo=bool(raw.get("logo")), thumbnail=raw.get("thumbnail"))

    def to_wire(self) -> dict:
        return {"type": self.type, "choice": self.choice, "uploadSha": self.upload_sha,
                "contactsSha": self.contacts_sha, "logo": self.logo, "thumbnail": self.thumbnail}

    def to_fields(self) -> dict:
        """Keyword arguments for `schemas.PictureInputsModel`."""
        return {"type": self.type, "choice": self.choice, "upload_sha": self.upload_sha,
                "contacts_sha": self.contacts_sha, "logo": self.logo, "thumbnail": self.thumbnail}


@dataclass(frozen=True)
class Resolved:
    """The precedence's answer: which rung (`None` = nothing) and the URL the app loads (`None` for initials)."""

    source: str | None = None
    url: str | None = None


NOTHING = Resolved()


def _sha(value) -> bool:
    return isinstance(value, str) and _SHA_RE.fullmatch(value) is not None


def _https(value) -> bool:
    """R-PE6 — only a provider's https URL is ever offered as a thumbnail; the app loads it without the bearer."""
    return (isinstance(value, str) and value.startswith("https://") and len(value) <= _MAX_URL
            and not any(ch.isspace() for ch in value))


def resolve(entity_id: str, inputs: PictureInputs) -> Resolved:
    """The precedence, and nothing else — no I/O, so the Swift twin can agree byte for byte (R-PE3)."""
    path = f"/entities/{quote(entity_id, safe='')}"
    if inputs.choice == "upload" and _sha(inputs.upload_sha):
        return Resolved("upload", f"{path}/picture?v={inputs.upload_sha}")
    if inputs.choice == "initials":
        return Resolved("initials", None)
    if inputs.type == "person":
        if _sha(inputs.contacts_sha):
            return Resolved("contacts", f"{path}/picture?v={inputs.contacts_sha}")
        return NOTHING
    if inputs.type == "media":
        return Resolved("thumbnail", inputs.thumbnail) if _https(inputs.thumbnail) else NOTHING
    if inputs.logo:
        return Resolved("logo", f"{path}/logo")
    return NOTHING


def detected(entity_id: str, inputs: PictureInputs) -> Resolved:
    """What shows once the person's own choice is gone — DELETE's answer, which the app paints early (R-PE10)."""
    return resolve(entity_id, replace(inputs, choice=None, upload_sha=None))


def logo_eligible(fm: dict) -> bool:
    """R-PE9 — a brand (`company`/`tool`), or any page whose own `logo:` names a domain; never a person or a media
    page (R-PE3)."""
    kind = str((fm or {}).get("type") or "concept").strip().lower()
    if kind in ("person", "media"):
        return False
    explicit = (fm or {}).get("logo")
    return kind in LOGO_TYPES or (isinstance(explicit, str) and bool(explicit.strip()))


def inputs_for(fm: dict, *, logo_available: bool = False) -> PictureInputs:
    """One page's inputs from its frontmatter. Nothing a hand edit invented counts: a `picture:` that is not the shape
    the upload endpoint writes (R-PE1) is ignored, not guessed at."""
    fm = fm or {}
    kind = str(fm.get("type") or "concept").strip().lower() or "concept"
    choice = upload_sha = None
    picture = fm.get("picture")
    if isinstance(picture, dict):
        if picture.get("kind") == "upload" and _sha(picture.get("sha")) and picture.get("ext") in UPLOAD_EXTS:
            choice, upload_sha = "upload", picture["sha"]
        elif picture.get("kind") == "initials":
            choice = "initials"
    contacts = fm.get("contacts_photo")
    contacts_sha = contacts["sha"] if isinstance(contacts, dict) and _sha(contacts.get("sha")) else None
    thumbnail = None
    media = fm.get("media")
    if kind == "media" and isinstance(media, dict) and media.get("kind") != PAPER_KIND and _https(media.get("thumbnail")):
        thumbnail = media["thumbnail"]
    return PictureInputs(type=kind, choice=choice, upload_sha=upload_sha, contacts_sha=contacts_sha,
                         logo=bool(logo_available) and logo_eligible(fm), thumbnail=thumbnail)


def logo_available(entity_id: str, fm: dict, body: str, *, cached: set[str], missed: dict[str, float],
                   page_mtime: float) -> bool:
    """R-PE9 — a fresh cached hit, or no fresh miss since the page last changed and a domain to fetch. The second half
    keeps G59's on-demand fetch alive (a company card still asks `/logo` once) without offering a favicon the ladder
    already failed to find."""
    if not logo_eligible(fm):
        return False
    if entity_id in cached:
        return True
    missed_at = missed.get(entity_id)
    if missed_at is not None and page_mtime <= missed_at:
        return False
    return logo_service.domain_for(fm, body) is not None


def resolve_page(memory_path, entity_id: str, fm: dict, body: str, *, page_mtime: float,
                 cached: set[str] | None = None, missed: dict[str, float] | None = None) -> tuple[Resolved, PictureInputs]:
    """The wire's two answers for one page: what to draw, and the inputs the app's twin re-resolves from. The graph
    builder passes the bank's logo sets once; a single-page caller lets this read them."""
    if cached is None or missed is None:
        bank = logo_service.bank_name(Path(memory_path))
        cached = logo_service.cached_ids(bank) if cached is None else cached
        missed = logo_service.missed_ids(bank) if missed is None else missed
    available = logo_available(entity_id, fm, body, cached=cached, missed=missed, page_mtime=page_mtime)
    inputs = inputs_for(fm, logo_available=available)
    return resolve(entity_id, inputs), inputs


def day(raw) -> str | None:
    """A page's `last_referenced` as `YYYY-MM-DD`, or None — the node's `lastReferenced` (R-PE13)."""
    text = str(raw or "").strip()[:10]
    return text if _DAY_RE.fullmatch(text) else None


def sha12(data: bytes) -> str:
    """sha256[:12] of the bytes — the `v=` that busts every cache, computed the same way by the app (R-PE10)."""
    return hashlib.sha256(data).hexdigest()[:12]


def sniff(data: bytes) -> str | None:
    """`png` or `jpg` from the magic bytes, else None — the only formats the server stores or serves (R-PE2)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    return None


def dimensions(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a PNG's IHDR or a JPEG's first SOFn marker — read from the header, never decoded
    (`logo_service.min_dimension`'s walk, returning both sides)."""
    kind = sniff(data)
    if kind == "png":
        if len(data) < 24:
            return None
        width, height = struct.unpack(">II", data[16:24])
        return width, height
    if kind == "jpg":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return width, height
            i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def upload_rel(entity_id: str, ext: str) -> str:
    """The upload's bank-relative path, as a commit names it."""
    return "/".join((*PICTURES_DIR, f"{entity_id}.{ext}"))


def upload_path(memory_path, entity_id: str, ext: str) -> Path | None:
    """R-PE1 — derived from the id and a known extension, never read from the page; None for anything that would land
    outside `assets/pictures/`."""
    if ext not in UPLOAD_EXTS:
        return None
    base = Path(memory_path).joinpath(*PICTURES_DIR).resolve()
    path = (base / f"{entity_id}.{ext}").resolve()
    return path if path.parent == base else None


def contacts_path(bank: str, entity_id: str) -> Path | None:
    """R-PE7 — where T-Sources keeps this page's Contacts thumbnail. Never creates anything: `auth.cicada_home` mkdirs,
    and a read must not conjure a folder (`logo_service.meta_path`'s rule)."""
    raw = os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")
    base = (Path(raw).expanduser() / CONTACTS_DIR_NAME / (bank or "default")).resolve()
    path = (base / f"{entity_id}.jpg").resolve()
    return path if path.parent == base else None


# --- the person's own picture (R-PE1, R-PE2, R-PE4, R-PE8) --------------------------------------------------------

#: R-PE2 — the logo cache's own bounds: 512 KiB, and nothing under 16 px a side. The app sends ≤ 512 px.
MAX_UPLOAD_BYTES = logo_service.MAX_BYTES
MIN_SIDE = logo_service.MIN_PIXELS
MAX_SIDE = 1024
TRIGGER = "user/companion_app"


class InvalidPicture(ValueError):
    """An upload the server will not keep. The message is a sentence for the person — the app shows it as written —
    and `status` the HTTP answer (413 only for size)."""

    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


def validate_upload(data: bytes) -> str:
    """R-PE2 — the server never resizes (no Pillow; `logo_service`'s rule): it keeps a PNG or JPEG within the bounds,
    by its header, and refuses everything else. Returns the extension to store it under."""
    if not data:
        raise InvalidPicture("That file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidPicture("That picture is too large — Cicada keeps pictures under 512 KB.", status=413)
    if logo_service.looks_like_svg(data):
        raise InvalidPicture("Cicada keeps PNG or JPEG pictures, not SVG drawings.")
    ext = sniff(data)
    if ext is None:
        raise InvalidPicture("Cicada keeps PNG or JPEG pictures.")
    size = dimensions(data)
    if size is None:
        raise InvalidPicture("Cicada couldn't read that picture's size.")
    if min(size) < MIN_SIDE:
        raise InvalidPicture("That picture is too small to show.")
    if max(size) > MAX_SIDE:
        raise InvalidPicture("That picture is bigger than Cicada keeps — the app shrinks pictures first, so try again from the app.")
    return ext


@dataclass(frozen=True)
class PictureWrite:
    """What one write touched, for its commit (R-PE8)."""

    page: str
    subject: str
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()


def _page(memory_path, entity_id: str) -> Path:
    return Path(memory_path) / "entities" / f"{entity_id}.md"


def _drop_uploads(memory_path, entity_id: str, *, keep: str | None = None) -> tuple[str, ...]:
    """Remove every stored upload of this page but `keep`'s format; returns their bank-relative paths for the commit."""
    removed = []
    for ext in UPLOAD_EXTS:
        if ext == keep:
            continue
        path = upload_path(memory_path, entity_id, ext)
        if path is not None and path.is_file():
            path.unlink()
            removed.append(upload_rel(entity_id, ext))
    return tuple(removed)


def write_upload(memory_path, entity_id: str, data: bytes, ext: str, *, today: date) -> PictureWrite:
    """Store the bytes (atomically), drop the other format, and mark the page (R-PE1). The caller validated them."""
    path = upload_path(memory_path, entity_id, ext)
    if path is None:
        raise InvalidPicture("This page can't hold a picture.")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    removed = _drop_uploads(memory_path, entity_id, keep=ext)
    page = _page(memory_path, entity_id)
    parsed = markdown_parser.parse(page)
    parsed.frontmatter["picture"] = {"kind": "upload", "sha": sha12(data), "ext": ext, "added": today.isoformat()}
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    return PictureWrite(page=f"entities/{entity_id}.md", subject="Set picture",
                        added=(upload_rel(entity_id, ext),), removed=removed)


def write_initials(memory_path, entity_id: str, *, today: date) -> PictureWrite:
    """R-PE4 — "Use initials instead" is the person's choice, kept like an upload; any upload goes with it."""
    removed = _drop_uploads(memory_path, entity_id)
    page = _page(memory_path, entity_id)
    parsed = markdown_parser.parse(page)
    parsed.frontmatter["picture"] = {"kind": "initials", "added": today.isoformat()}
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    return PictureWrite(page=f"entities/{entity_id}.md", subject="Use initials", removed=removed)


def write_clear(memory_path, entity_id: str) -> PictureWrite | None:
    """R-PE4 — back to what was detected: the choice and its file go. None when there was nothing to clear."""
    page = _page(memory_path, entity_id)
    parsed = markdown_parser.parse(page)
    removed = _drop_uploads(memory_path, entity_id)
    if "picture" not in parsed.frontmatter and not removed:
        return None
    parsed.frontmatter.pop("picture", None)
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    return PictureWrite(page=f"entities/{entity_id}.md", subject="Remove picture", removed=removed)


def picture_file(memory_path, entity_id: str, fm: dict) -> tuple[Path, str] | None:
    """What `GET /entities/{id}/picture` serves: the person's upload, else the Contacts photo — at a path derived from
    the id, never one the page names (R-PE1), within the bound, and only if it sniffs as PNG or JPEG."""
    resolved = resolve(entity_id, inputs_for(fm))
    if resolved.source == "upload":
        path = upload_path(memory_path, entity_id, fm["picture"]["ext"])
    elif resolved.source == "contacts":
        path = contacts_path(logo_service.bank_name(Path(memory_path)), entity_id)
    else:
        return None
    if path is None or not path.is_file() or path.stat().st_size > MAX_UPLOAD_BYTES:
        return None
    ext = sniff(path.read_bytes()[:16])
    return (path, MEDIA_TYPES[ext]) if ext else None


async def commit(memory_path, write: PictureWrite) -> None:
    """R-PE8 — alone, as the person: the page, the new file, and any removed file git tracks (`git add` refuses a
    pathspec that matches nothing, so an untracked leftover is simply gone). A failed commit is logged and the write
    stands — `projects._commit`'s precedent."""
    from api.services import git_service   # the graph builder imports this module; git_service stays off that path

    removed = [p for p in write.removed if await git_service.is_tracked(Path(memory_path), p)]
    lines = [f"{write.page}: updated (trigger: {TRIGGER})"]
    lines += [f"{p}: added (trigger: {TRIGGER})" for p in write.added]
    lines += [f"{p}: removed (trigger: {TRIGGER})" for p in removed]
    message = git_service.build_commit_message(f"{write.subject} {date.today().isoformat()}", lines, authors=["user"])
    try:
        await git_service.commit_paths(Path(memory_path), message, [write.page, *write.added, *removed])
    except Exception as exc:  # noqa: BLE001 — the write stands; a later writer's commit picks it up
        logger.warning(f"picture commit skipped: {type(exc).__name__}")
