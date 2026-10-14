"""Dated captures of saved sites (G166 exploring, G196 Looks, owner 2026-10-14) — the ONE reader and writer.

An agent the person asked explores a saved site in a browser, runs Cicada's capture script, and records what it saw
(``cicada_record_capture``). This module turns that into memory, under the owner's D1 ruling (b):

* **A capture record per visit, append-only** — ``<bank>/captures/<media-entity-id>/<captured-at>-<tok>.md``: the
  dates (captured, recorded, saved, when the person said why), the outcome, the page's title, outline, components,
  fonts and tokens, the palette Cicada read from the pixels, the hashes, the change since the previous capture, and
  whether it was taken in the person's signed-in session. A re-visit adds a file and never edits one; "changed since"
  is a comparison between dated records.
* **One thumbnail per capture that changed the look** — ``<bank>/assets/captures/<sha256[:16]>.jpg``, at most
  640×400, content-addressed: an unchanged re-visit points at the earlier thumbnail and adds no bytes. "How it looked
  then" survives a bank handed over.
* **Full-resolution images outside every bank and every git repo** — ``$CICADA_HOME/captures/<bank>/<sha256>.<ext>``
  (the viewport at 2×, the full page, mobile, dark), kept, never evicted, exportable with the bank. The record holds
  each file's sha256, size and dimensions, so a missing file reads as "full image not on this Mac".
* **The page's visible text** (≤ 1,500 words) beside them, ``$CICADA_HOME/captures/<bank>/text/<sha256>.txt``: for
  change detection and Sleep's recon, and out of git, so a copy of someone else's page never enters the bank.

Cicada computes the palette (``design_palette``), a 64-bit perceptual hash of the viewport and the text hashes
itself — never from the agent's word. A page that showed the person's own account (``account_visible``) keeps even
its thumbnail outside the bank: the scrub cannot clean pixels. No screenshot of a wall is ever kept: ``needs_login``
and ``blocked`` never reach this module (the queue pauses the site instead).

Callers pass the ACTIVE bank (the split-brain rule), hold the write admission through their commit, refuse a demo bank,
and commit the memory-relative ``paths`` a write returns under the agent's own author. Nothing here commits, and a
refusal is a dict with ``action: "error"`` that wrote nothing in the bank.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from loguru import logger

from api.services import design_palette, episode_scrub, image_decode, markdown_parser, reading_hosts, video_queue
from api.services.auth import cicada_home

CAPTURES_DIR = "captures"
ASSETS = ("assets", "captures")
SHAPE = "capture-1"
THUMB_W, THUMB_H = 640, 400
THUMB_QUALITY = 80
MAX_SHOT_BYTES = 12 * 1024 * 1024
MAX_SIDE = 16384
SHOT_KINDS = ("viewport", "thumb", "full", "mobile", "dark")
#: What a record may say happened. ``needs_login`` and ``blocked`` are not here: a wall is never recorded as memory.
OUTCOMES = ("captured", "unchanged", "not_found", "gone", "parked", "moved", "failed")
DEAD = ("not_found", "gone", "parked")
#: dHash Hamming distance: ≤ SAME is the same look, ≥ NEW a new one (design §3).
SAME, NEW = 5, 12
MAX_TEXT_WORDS = 1500
MAX_OUTLINE = 60
MAX_COMPONENTS = 24
MAX_FONTS = 12
MAX_TOKENS = 40
MAX_JSONLD = 6
#: Slice 2 (owner 2026-10-14 evening): the pages a visit opened past the landing page, and what each keeps.
MAX_EXTRA_PAGES = 5
PAGE_OUTLINE = 20
SECTION_WORDS = 400
EXCERPT_CHARS = 240
TITLE_CHARS = 200
DESC_CHARS = 500
HEADING_CHARS = 160
#: A capture's clock must fall inside its lease window (with this slack), or the server's clock is used and flagged.
CLOCK_SLACK = timedelta(minutes=2)
ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$")
ENTITY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")
_DIGITS = re.compile(r"\d+")


# --------------------------------------------------------------------------- places


def bank_slug(memory_path) -> str:
    return video_queue.bank_slug(Path(memory_path))


def outside_root(memory_path) -> Path:
    """``$CICADA_HOME/captures/<bank>/`` — full images and page text, outside every bank and git repo."""
    return cicada_home() / CAPTURES_DIR / bank_slug(memory_path)


def full_image_path(memory_path, sha256: str, ext: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f]{64}", str(sha256 or "")) or ext not in ("jpg", "png"):
        return None
    return outside_root(memory_path) / f"{sha256}.{ext}"


def _thumb_rel(sha256: str) -> str:
    return f"{'/'.join(ASSETS)}/{sha256[:16]}.jpg"


def thumb_file(memory_path, rel: str | None) -> Path | None:
    """A thumbnail inside the bank's own ``assets/captures/`` only — never another path a record names."""
    rel = str(rel or "")
    if not re.fullmatch(r"assets/captures/[0-9a-f]{16}\.jpg", rel):
        return None
    path = Path(memory_path) / rel
    return path if path.is_file() else None


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- pixels


def dhash(rgb: np.ndarray) -> str:
    """A 64-bit difference hash, hex: 9×8 grayscale, each pixel brighter than its right neighbour is a 1."""
    px = np.asarray(rgb, dtype=np.float32)
    gray = px[..., 0] * 0.299 + px[..., 1] * 0.587 + px[..., 2] * 0.114
    bits = (gray[:, 1:] > gray[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def hamming(a: str | None, b: str | None) -> int | None:
    try:
        return bin(int(str(a), 16) ^ int(str(b), 16)).count("1")
    except (TypeError, ValueError):
        return None


def look_change(distance: int | None) -> str | None:
    if distance is None:
        return None
    return "same" if distance <= SAME else "new" if distance >= NEW else "small"


def image_dhash(data: bytes) -> str | None:
    try:
        return dhash(image_decode.decode(data, size=(9, 8)))
    except image_decode.DecodeError:
        return None


def thumb_size(width: int, height: int) -> tuple[int, int]:
    """Fit inside 640×400, aspect kept, never enlarged."""
    scale = min(1.0, THUMB_W / max(width, 1), THUMB_H / max(height, 1))
    return max(1, round(width * scale)), max(1, round(height * scale))


def make_thumbnail(data: bytes) -> bytes | None:
    """A JPEG at most 640×400 from a screenshot's bytes, made by macOS's ``sips`` in a child process over a temporary
    file of its own (``image_decode``'s pattern). None when this host can't (the record still stands)."""
    size = image_decode.dimensions(data)
    if size is None:
        return None
    w, h = thumb_size(*size)
    try:
        sips = image_decode._sips()
    except image_decode.DecodeError:
        return None
    with tempfile.TemporaryDirectory(prefix="cicada-thumb-") as tmp:
        src, out = Path(tmp) / "in", Path(tmp) / "out.jpg"
        src.write_bytes(data)
        try:
            done = subprocess.run([sips, "-s", "format", "jpeg", "-s", "formatOptions", str(THUMB_QUALITY),
                                   "-z", str(h), str(w), str(src), "--out", str(out)], capture_output=True,
                                  timeout=image_decode.TIMEOUT_S, env={"PATH": "/usr/bin:/bin", "HOME": tmp})
        except (OSError, subprocess.TimeoutExpired):
            return None
        if done.returncode != 0 or not out.is_file():
            return None
        return out.read_bytes()


def validate_shot(data: bytes) -> tuple[str, int, int]:
    """``(ext, width, height)`` for a screenshot Cicada keeps, or ValueError with a sentence."""
    if not data:
        raise ValueError("That picture is empty.")
    if len(data) > MAX_SHOT_BYTES:
        raise ValueError("That picture is over 12 MB.")
    ext = image_decode.sniff(data)
    if ext not in ("jpg", "png"):
        raise ValueError("Cicada keeps captures as JPEG or PNG.")
    size = image_decode.dimensions(data)
    if size is None or min(size) < 16 or max(size) > MAX_SIDE:
        raise ValueError("Cicada couldn't read that picture's size.")
    return ext, int(size[0]), int(size[1])


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return   # content-addressed: the same bytes are already there
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- words


def _scrub(text: str, bank: str) -> str:
    cleaned, n = episode_scrub.scrub(text or "")
    episode_scrub.record("site_captures", n, bank=bank)
    return cleaned


def _line(text, cap: int, bank: str) -> str:
    return " ".join(_scrub(str(text or ""), bank).split())[:cap].rstrip()


def normalize_words(text: str) -> str:
    """Whitespace folded, numbers masked — a footer year or a counter is not a change (design §3)."""
    return _DIGITS.sub("#", " ".join(str(text or "").lower().split()))


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_words(text).encode("utf-8")).hexdigest()


def jaccard_distance(a: list[str], b: list[str]) -> float:
    sa, sb = {normalize_words(x) for x in a if x}, {normalize_words(x) for x in b if x}
    if not sa and not sb:
        return 0.0
    return round(1.0 - len(sa & sb) / max(1, len(sa | sb)), 2)


def _unmarked(title) -> str:
    """A page title without the tab marker browser-harness prepends to the tabs it drives (🐴): the site's own title."""
    return re.sub(r"^\U0001F434\s*", "", str(title or ""))


def _outline(raw, bank: str) -> list[dict]:
    out = []
    for item in list(raw or [])[:MAX_OUTLINE]:
        if isinstance(item, str):
            item = {"level": 2, "text": item}
        if not isinstance(item, dict):
            continue
        text = _line(item.get("text"), HEADING_CHARS, bank)
        try:
            level = max(1, min(int(item.get("level") or 2), 3))
        except (TypeError, ValueError):
            level = 2
        if text:
            out.append({"level": level, "text": text})
    return out


def _box(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    try:
        box = {k: int(round(float(raw[k]))) for k in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    return box if box["width"] > 0 and box["height"] > 0 else None


def _components(raw) -> list[dict]:
    out = []
    for item in list(raw or [])[:MAX_COMPONENTS]:
        if not isinstance(item, dict):
            continue
        name = re.sub(r"[^a-z0-9_-]", "", str(item.get("name") or "").lower())[:40]
        if name:
            comp = {"name": name}
            if (box := _box(item.get("box"))) is not None:
                comp["box"] = box
            out.append(comp)
    return out


def _fonts(raw, bank: str) -> list[str]:
    out: list[str] = []
    for f in list(raw or [])[:MAX_FONTS * 2]:
        name = _line(f.get("family") if isinstance(f, dict) else f, 80, bank)
        if name and name not in out:
            out.append(name)
    return out[:MAX_FONTS]


def _tokens(raw, bank: str) -> dict:
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for i, (k, v) in enumerate(raw.items()):
        if i >= MAX_TOKENS:
            break
        key = re.sub(r"[^A-Za-z0-9_-]", "", str(k))[:60]
        if key and isinstance(v, (str, int, float)) and not isinstance(v, bool):
            out[key] = _line(v, 120, bank)
    return out


def _jsonld(raw, bank: str) -> list[dict]:
    """Only the schema.org fields the design names: type, name, author, publisher, price and currency, sameAs."""
    out = []
    for item in list(raw or [])[:MAX_JSONLD]:
        if not isinstance(item, dict):
            continue
        kept: dict = {}
        kind = item.get("@type") or item.get("type")
        if isinstance(kind, list):
            kind = kind[0] if kind else None
        if isinstance(kind, str):
            kept["type"] = _line(kind, 60, bank)
        for name in ("name", "author", "publisher", "price", "priceCurrency"):
            value = item.get(name)
            if isinstance(value, dict):
                value = value.get("name")
            if isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip():
                kept[name] = _line(value, 120, bank)
        offers = item.get("offers")
        if isinstance(offers, dict):
            for name in ("price", "priceCurrency"):
                if isinstance(offers.get(name), (str, int, float)) and name not in kept:
                    kept[name] = _line(offers[name], 40, bank)
        same = [s for s in (item.get("sameAs") or []) if isinstance(s, str) and s.startswith("http")][:6]
        if same:
            kept["sameAs"] = same
        if kept:
            out.append(kept)
    return out


# --------------------------------------------------------------------------- reading


def _root(memory_path) -> Path:
    return Path(memory_path) / CAPTURES_DIR


def list_captures(memory_path, entity_id: str) -> list[dict]:
    """Every capture of one saved page, newest first: the frontmatter plus ``id`` and ``path``."""
    if not ENTITY_RE.match(str(entity_id or "")):
        return []
    folder = _root(memory_path) / entity_id
    if not folder.is_dir():
        return []
    out = []
    for path in folder.glob("*.md"):
        if not ID_RE.match(path.stem):
            continue
        try:
            fm = dict(markdown_parser.parse(path).frontmatter or {})
        except Exception as exc:  # noqa: BLE001 — a hand-broken record is skipped, never fatal
            logger.debug(f"site_captures: unreadable {path.name}: {type(exc).__name__}")
            continue
        fm["id"], fm["path"] = path.stem, f"{CAPTURES_DIR}/{entity_id}/{path.name}"
        out.append(fm)
    return sorted(out, key=lambda c: (str(c.get("captured_at") or ""), c["id"]), reverse=True)


def latest(memory_path, entity_id: str) -> dict | None:
    caps = list_captures(memory_path, entity_id)
    return caps[0] if caps else None


def get_capture(memory_path, entity_id: str, capture_id: str) -> dict | None:
    if not ID_RE.match(str(capture_id or "")):
        return None
    return next((c for c in list_captures(memory_path, entity_id) if c["id"] == capture_id), None)


def last_look(caps: list[dict]) -> dict | None:
    """The newest capture that holds a viewport hash (an ``unchanged`` record points back, a dead one has none)."""
    return next((c for c in caps if c.get("dhash")), None)


def last_thumb(caps: list[dict]) -> str | None:
    for c in caps:
        rel = (c.get("thumb") or {}).get("file") if isinstance(c.get("thumb"), dict) else None
        if rel:
            return rel
    return None


def stamp(memory_path) -> str:
    """The ``captures`` sync component: every record's name, size and mtime (a stat walk, two levels, no parse)."""
    root = _root(memory_path)
    entries = []
    try:
        for d in sorted(root.iterdir()):
            if d.is_dir():
                for f in sorted(d.glob("*.md")):
                    st = f.stat()
                    entries.append(f"{d.name}/{f.name}:{st.st_size}:{st.st_mtime_ns}")
    except OSError:
        pass
    return hashlib.sha256("\n".join(entries).encode()).hexdigest()[:16] if entries else "0"


# --------------------------------------------------------------------------- writing


def capture_id(captured_at: datetime, lease_token: str) -> str:
    return f"{captured_at.strftime('%Y%m%dT%H%M%SZ')}-{str(lease_token)[:6]}"


def _host(url: str | None) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def _error(message: str) -> dict:
    return {"action": "error", "error": message}


def _clock(captured_at, *, window_start: datetime | None, now: datetime) -> tuple[datetime, bool]:
    """The agent's clock, kept when it falls inside its lease window; else the server's clock, flagged."""
    moment = _parse(captured_at)
    if moment is not None:
        moment = moment.astimezone(timezone.utc).replace(microsecond=0)
        start = (window_start or now - timedelta(hours=1)) - CLOCK_SLACK
        if start <= moment <= now + CLOCK_SLACK:
            return moment, False
    return now, True


def record(memory_path, *, entity_id: str, url: str, lease_token: str, outcome: str, captured_at=None,
           window_start: datetime | None = None, final_url: str | None = None, http_status=None,
           shots: list[tuple[str, bytes]] | None = None, page: dict | None = None, signed_in: bool = True,
           account_visible: bool = False, consent_overlay: bool = False, consent_box=None, depth: str = "capture",
           saved_at: str | None = None, why_at: str | None = None, last_modified: str | None = None,
           author: str = "agent", session: str | None = None, via: str | None = None,
           next_pages=None, pages: list[dict] | None = None, section: dict | None = None,
           plan: dict | None = None, robots: dict | None = None, previous: dict | None = None,
           now: datetime | None = None) -> dict:
    """File one capture. ``{"action": "added" | "duplicate", "id", "capture", "paths"}`` or a refusal.

    ``shots`` are ``(kind, bytes)``: a ``viewport`` is required for ``captured``; ``thumb`` is optional (Cicada makes
    one from the viewport when it can). Images go to the outside store first (content-addressed, so a retry writes
    nothing new); the bank gets the record and, only when the look changed, the thumbnail.

    Slice 2: ``pages`` are the further pages this visit opened, already vetted against the plan by the caller
    (``explore_plan.vet``): ``{url, kind, title, loaded_at, http_status, outcome, chosen_by, page, shots: [(kind,
    bytes)]}``. Each keeps its own images outside the bank and a thumbnail in it when its look changed since the
    site map's ``previous[url]`` (``{dhash, thumb}``). ``section`` is the part of the page the person's words point
    at (``{heading, text}``; the text goes outside the bank, an excerpt of at most 240 characters stays). ``plan`` is
    recorded as why the visit went this deep."""
    bank = Path(memory_path).name
    moment = _now(now)
    outcome = str(outcome or "").strip().lower()
    if outcome not in OUTCOMES:
        return _error(f"outcome must be one of {', '.join(OUTCOMES)}.")
    if not ENTITY_RE.match(str(entity_id or "")):
        return _error("That saved link has no page to keep a capture on.")
    when, flagged = _clock(captured_at, window_start=window_start, now=moment)
    cid = capture_id(when, lease_token)
    folder = _root(memory_path) / entity_id
    rel = f"{CAPTURES_DIR}/{entity_id}/{cid}.md"
    if (folder / f"{cid}.md").is_file():
        existing = get_capture(memory_path, entity_id, cid)
        return {"action": "duplicate", "id": cid, "capture": existing, "paths": []}

    shots = [(str(k), d) for k, d in shots or [] if str(k) in SHOT_KINDS and d]
    by_kind: dict[str, bytes] = {}
    for kind, data in shots:
        by_kind.setdefault(kind, data)
    if outcome == "captured" and "viewport" not in by_kind:
        return _error("A captured site needs its viewport screenshot (shots: kind viewport).")
    if outcome in DEAD and by_kind:
        by_kind = {}   # a dead site is recorded with no images (design §3)
    images: list[dict] = []
    for kind, data in by_kind.items():
        if kind == "thumb":
            continue
        try:
            ext, w, h = validate_shot(data)
        except ValueError as exc:
            return _error(f"The {kind} screenshot: {exc}")
        sha = hashlib.sha256(data).hexdigest()
        target = full_image_path(memory_path, sha, ext)
        try:
            _write_atomic(target, data)
        except OSError as exc:
            return _error(f"The {kind} screenshot couldn't be kept ({type(exc).__name__}).")
        images.append({"kind": kind, "sha256": sha, "ext": ext, "width": w, "height": h, "bytes": len(data)})

    page = page if isinstance(page, dict) else {}
    title = _line(_unmarked(page.get("title")), TITLE_CHARS, bank)
    description = _line(page.get("description"), DESC_CHARS, bank)
    outline = _outline(page.get("outline"), bank)
    words = " ".join(_scrub(str(page.get("text") or ""), bank).split()[:MAX_TEXT_WORDS])
    text_sha = text_hash(words) if words else None
    if words:
        try:
            _write_atomic(outside_root(memory_path) / "text" / f"{hashlib.sha256(words.encode()).hexdigest()}.txt",
                          words.encode("utf-8"))
        except OSError:
            pass   # change detection falls back to the outline; the record stands

    caps = list_captures(memory_path, entity_id)
    prev_look = last_look(caps)
    viewport = by_kind.get("viewport")
    hash_now = image_dhash(viewport) if viewport is not None else None
    palette, look_words = ([], [])
    if viewport is not None:
        from api.services import design_refs

        palette, look_words = design_refs.read_look(viewport)

    change: dict = {}
    if prev_look is not None:
        change["since"] = prev_look["id"]
        if hash_now is not None:
            change["look"] = look_change(hamming(hash_now, prev_look.get("dhash")))
        prev_outline = [h.get("text", "") for h in prev_look.get("outline") or [] if isinstance(h, dict)]
        dist = jaccard_distance([h["text"] for h in outline], prev_outline)
        text_same = text_sha is None or prev_look.get("text_sha256") is None or text_sha == prev_look.get("text_sha256")
        # The outline's Jaccard distance sizes the change; a text-only change counts as a small one.
        change["words"] = "same" if text_same and dist == 0.0 else f"changed({max(dist, 0.05):.2f})"
    saved_host = reading_hosts.site_of(url)
    moved = bool(final_url) and reading_hosts.site_of(final_url) not in ("", saved_host)
    if moved or outcome == "moved":
        change["moved"] = True

    thumb: dict | None = None
    thumb_paths: list[str] = []
    if outcome == "unchanged" or (viewport is not None and change.get("look") == "same"):
        ref = last_thumb(caps)
        if ref:
            thumb = {"file": ref, "reused": True}
    elif viewport is not None:
        small = by_kind.get("thumb")
        made = make_thumbnail(viewport)
        if made is None and small is not None:
            size = image_decode.dimensions(small)
            if size is not None and image_decode.sniff(small) == "jpg" and size[0] <= THUMB_W and size[1] <= THUMB_H:
                made = small
        if made is not None:
            sha = hashlib.sha256(made).hexdigest()
            tw, th = image_decode.dimensions(made) or (0, 0)
            if account_visible:
                # The person's own account showed on the page: the pixels stay outside the bank.
                target = full_image_path(memory_path, sha, "jpg")
                _write_atomic(target, made)
                images.append({"kind": "thumb", "sha256": sha, "ext": "jpg", "width": tw, "height": th,
                               "bytes": len(made)})
            else:
                rel_thumb = _thumb_rel(sha)
                try:
                    _write_atomic(Path(memory_path) / rel_thumb, made)
                except OSError as exc:
                    return _error(f"The thumbnail couldn't be kept ({type(exc).__name__}).")
                thumb = {"file": rel_thumb, "sha256": sha, "width": int(tw), "height": int(th), "bytes": len(made)}
                thumb_paths.append(rel_thumb)

    kept_pages: list[dict] = []
    for raw in list(pages or [])[:MAX_EXTRA_PAGES] if outcome in ("captured", "moved", "unchanged") else []:
        got = _page(memory_path, raw, bank=bank, account_visible=account_visible,
                    previous=(previous or {}).get(str(raw.get("url") or "")))
        if isinstance(got, str):
            return _error(got)
        kept_pages.append(got)
        thumb_paths += [got["thumb"]["file"]] if (got.get("thumb") or {}).get("file") and \
            not got["thumb"].get("reused") and "sha256" in got["thumb"] else []
    kept_section = _section(memory_path, section, bank=bank)

    try:
        status = int(http_status) if http_status is not None and str(http_status).strip() else None
    except (TypeError, ValueError):
        status = None
    fm: dict = {"id": cid, "shape": SHAPE, "url": url, "site": saved_host, "entity": entity_id,
                "captured_at": _iso(when), "recorded_at": _iso(moment)}
    if flagged:
        fm["captured_at_flagged"] = True
    for name, value in (("saved_at", saved_at), ("why_at", why_at), ("last_modified", last_modified)):
        if isinstance(value, str) and value.strip():
            fm[name] = value.strip()[:40]
    fm.update({"outcome": "moved" if moved and outcome == "captured" else outcome,
               "context": "signed_in" if signed_in else "isolated", "signed_in": bool(signed_in)})
    if account_visible:
        fm["account_visible"] = True
    if consent_overlay:
        fm["consent_overlay"] = True
        if (box := _box(consent_box)) is not None:
            fm["consent_box"] = box
    fm.update({"depth": depth, "added_by": author})
    if session:
        fm["session"] = session
    if via:
        fm["via"] = _line(via, 80, bank)
    if final_url and final_url != url:
        fm["final_url"] = str(final_url)[:2000]
    if status is not None:
        fm["http_status"] = status
    if title:
        fm["title"] = title
    if description:
        fm["description"] = description
    if thumb:
        fm["thumb"] = thumb
    if images:
        fm["images"] = images
    if palette:
        fm["palette"] = palette
    if look_words:
        fm["look"] = look_words
    if hash_now:
        fm["dhash"] = hash_now
    if text_sha:
        fm["text_sha256"] = text_sha
    if outline:
        fm["outline"] = outline
        fm["outline_sha256"] = text_hash(" | ".join(h["text"] for h in outline))
    if (comps := _components(page.get("components"))):
        fm["components"] = comps
    if (fonts := _fonts(page.get("fonts"), bank)):
        fm["fonts"] = fonts
    if (tokens := _tokens(page.get("tokens"), bank)):
        fm["tokens"] = tokens
    if (ld := _jsonld(page.get("jsonld"), bank)):
        fm["jsonld"] = ld
    pages = [{"url": str(p.get("url"))[:2000], "label": _line(p.get("label"), 80, bank)}
             for p in list(next_pages or [])[:2] if isinstance(p, dict) and str(p.get("url") or "").startswith("http")
             and _host(p.get("url")) == _host(final_url or url)]
    if pages:
        fm["next_pages"] = pages
    if change:
        fm["change"] = change
    if kept_pages:
        fm["pages"] = kept_pages
    if kept_section:
        fm["section"] = kept_section
    if isinstance(plan, dict) and plan:
        fm["plan"] = _plan_note(plan, bank)
    if isinstance(robots, dict) and robots.get("status") is not None:
        fm["robots"] = {k: robots[k] for k in ("status", "sha256") if robots.get(k) is not None}
    folder.mkdir(parents=True, exist_ok=True)
    try:
        markdown_parser.write_new(folder / f"{cid}.md", fm, _body(fm))
    except FileExistsError:
        return {"action": "duplicate", "id": cid, "capture": get_capture(memory_path, entity_id, cid), "paths": []}
    fm["path"] = rel
    return {"action": "added", "id": cid, "capture": fm, "paths": [rel, *thumb_paths]}


def _thumb_for(memory_path, viewport: bytes, *, account_visible: bool, bank: str) -> tuple[dict | None, dict | None]:
    """``(thumb, outside_image)``: a ≤ 640×400 JPEG of ``viewport`` in the bank, or — when the person's own account
    showed — outside it. ``(None, None)`` when this host cannot make one (the record stands)."""
    made = make_thumbnail(viewport)
    if made is None:
        return None, None
    sha = hashlib.sha256(made).hexdigest()
    tw, th = image_decode.dimensions(made) or (0, 0)
    if account_visible:
        _write_atomic(full_image_path(memory_path, sha, "jpg"), made)
        return None, {"kind": "thumb", "sha256": sha, "ext": "jpg", "width": tw, "height": th, "bytes": len(made)}
    rel = _thumb_rel(sha)
    _write_atomic(Path(memory_path) / rel, made)
    return {"file": rel, "sha256": sha, "width": int(tw), "height": int(th), "bytes": len(made)}, None


def _page(memory_path, raw: dict, *, bank: str, account_visible: bool, previous: dict | None) -> dict | str:
    """One further page of a visit, as its record keeps it — or a sentence when one of its pictures is refused."""
    from api.services import design_refs

    url = str(raw.get("url") or "")[:2000]
    outcome = str(raw.get("outcome") or "captured")
    page = raw.get("page") if isinstance(raw.get("page"), dict) else {}
    out: dict = {"url": url, "kind": str(raw.get("kind") or "other")[:20], "outcome": outcome,
                 "loaded_at": str(raw.get("loaded_at") or "")[:40], "chosen_by": str(raw.get("chosen_by") or "script")}
    if (title := _line(_unmarked(raw.get("title") or page.get("title")), TITLE_CHARS, bank)):
        out["title"] = title
    try:
        if raw.get("http_status") is not None:
            out["http_status"] = int(raw["http_status"])
    except (TypeError, ValueError):
        pass
    if outcome not in ("captured", "moved"):
        return out   # a wall or a dead page: no picture is kept (design §5.3)
    outline = _outline(page.get("outline"), bank)[:PAGE_OUTLINE]
    if outline:
        out["outline"] = outline
    if (fonts := _fonts(page.get("fonts"), bank)):
        out["fonts"] = fonts
    if (comps := _components(page.get("components"))):
        out["components"] = [c["name"] for c in comps]
    images: list[dict] = []
    by_kind: dict[str, bytes] = {}
    for kind, data in raw.get("shots") or []:
        if kind in SHOT_KINDS and kind != "thumb" and data:
            by_kind.setdefault(kind, data)
    for kind, data in list(by_kind.items()):
        try:
            ext, w, h = validate_shot(data)
        except ValueError:
            # A further page's picture Cicada does not keep is left out; the visit and the page stand (provenance
            # never blocks memory). The saved page's own pictures are still held to the refusal above.
            out.setdefault("refused", []).append(kind)
            del by_kind[kind]
            continue
        sha = hashlib.sha256(data).hexdigest()
        try:
            _write_atomic(full_image_path(memory_path, sha, ext), data)
        except OSError as exc:
            return f"The {out['kind']} page's {kind} screenshot couldn't be kept ({type(exc).__name__})."
        images.append({"kind": kind, "sha256": sha, "ext": ext, "width": w, "height": h, "bytes": len(data)})
    viewport = by_kind.get("viewport")
    if viewport is not None:
        out["dhash"] = image_dhash(viewport)
        palette, look_words = design_refs.read_look(viewport)
        if palette:
            out["palette"] = palette[:6]
        if look_words:
            out["look"] = look_words
        prev = previous or {}
        change = look_change(hamming(out.get("dhash"), prev.get("dhash")))
        if change:
            out["change"] = {"look": change}
        same = change == "same"
        if same and prev.get("thumb"):
            out["thumb"] = {"file": prev["thumb"], "reused": True}
        else:
            try:
                thumb, outside = _thumb_for(memory_path, viewport, account_visible=account_visible, bank=bank)
            except OSError as exc:
                return f"The {out['kind']} page's thumbnail couldn't be kept ({type(exc).__name__})."
            if thumb:
                out["thumb"] = thumb
            if outside:
                images.append(outside)
    if images:
        out["images"] = images
    return out


def _section(memory_path, raw, *, bank: str) -> dict | None:
    """The part of the page the person's words point at: its heading and an excerpt in the record (at most 240
    characters, never the whole page), the section's text outside the bank beside the page text."""
    if not isinstance(raw, dict):
        return None
    heading = _line(raw.get("heading"), HEADING_CHARS, bank)
    words = " ".join(_scrub(str(raw.get("text") or ""), bank).split()[:SECTION_WORDS])
    if not heading or not words:
        return None
    sha = hashlib.sha256(words.encode("utf-8")).hexdigest()
    try:
        _write_atomic(outside_root(memory_path) / "text" / f"{sha}.txt", words.encode("utf-8"))
    except OSError:
        pass
    excerpt = words if len(words) <= EXCERPT_CHARS else words[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
    out = {"heading": heading, "excerpt": excerpt, "text_sha256": sha}
    if raw.get("chosen_by") in ("script", "agent"):
        out["chosen_by"] = raw["chosen_by"]
    return out


def _plan_note(plan: dict, bank: str) -> dict:
    """Why the visit went this deep, as the record keeps it: the depth, the cap, the page kinds and the signals."""
    because = []
    for b in list(plan.get("because") or [])[:12]:
        if isinstance(b, dict):
            item = {"from": str(b.get("from") or "")[:20], "signal": str(b.get("signal") or "")[:80]}
            if b.get("words"):
                item["words"] = [_line(w, 40, bank) for w in list(b["words"])[:8]]
            because.append(item)
    return {"depth": str(plan.get("depth") or "capture"), "max_pages": int(plan.get("max_pages") or 1),
            "kinds": [str(p.get("kind")) for p in plan.get("pages") or [] if isinstance(p, dict)][:8],
            "because": because, **({"auto_look": True} if plan.get("auto_look") else {})}


def _body(fm: dict) -> str:
    title = fm.get("title") or fm.get("site") or "A saved site"
    when = str(fm.get("captured_at") or "")
    parts = [f"# {title}", "", f"Captured {when[:10]} {when[11:16]} UTC · {fm.get('outcome')}"
             + (" · in the person's signed-in browser" if fm.get("signed_in") else " · in a private browser context"),
             ""]
    thumb = (fm.get("thumb") or {}).get("file") if isinstance(fm.get("thumb"), dict) else None
    if thumb:
        parts += [f"![How it looked](../../{thumb})", ""]
    parts += [f"From <{fm.get('url')}>", ""]
    if fm.get("description"):
        parts += [str(fm["description"]), ""]
    if fm.get("outline"):
        parts += ["## Outline", ""]
        parts += [f"{'  ' * (int(h['level']) - 1)}- {h['text']}" for h in fm["outline"]]
        parts.append("")
    if fm.get("components"):
        parts += ["## Components", "", ", ".join(c["name"] for c in fm["components"]), ""]
    if fm.get("section"):
        sec = fm["section"]
        parts += ["## The part they meant", "", f"Under \"{sec.get('heading')}\":", "",
                  f"> {sec.get('excerpt')}", ""]
    if fm.get("pages"):
        parts += ["## Pages opened on this visit", ""]
        for page in fm["pages"]:
            name = page.get("title") or page.get("url")
            parts.append(f"- **{page.get('kind')}** — [{name}](<{page.get('url')}>) · {page.get('outcome')}")
            rel = (page.get("thumb") or {}).get("file")
            if rel:
                parts.append(f"  ![{page.get('kind')}](../../{rel})")
        parts.append("")
    if fm.get("plan"):
        plan = fm["plan"]
        why = "; ".join(f"{b.get('from')}: {b.get('signal')}" + (f" ({', '.join(b['words'])})" if b.get("words")
                                                                    else "") for b in plan.get("because") or [])
        parts += ["## Why this deep", "", f"Depth {plan.get('depth')}, up to {plan.get('max_pages')} page(s) — "
                  + (why or "the default"), ""]
    return "\n".join(parts).rstrip() + "\n"


def wire(memory_path, cap: dict) -> dict:
    """One capture as the API serves it (camelCase): the dates, the outcome, the look, the change, and image URLs —
    the thumbnail from the bank, each full image only when it is on this Mac."""
    entity_id, cid = str(cap.get("entity") or ""), str(cap.get("id") or "")
    thumb = cap.get("thumb") if isinstance(cap.get("thumb"), dict) else None
    thumb_out = None
    if thumb and thumb_file(memory_path, thumb.get("file")) is not None:
        thumb_out = {"url": f"/explore/captures/{entity_id}/{cid}/thumb", "width": int(thumb.get("width") or 0),
                     "height": int(thumb.get("height") or 0), "reused": bool(thumb.get("reused"))}
    images = []
    for img in cap.get("images") or []:
        if not isinstance(img, dict):
            continue
        path = full_image_path(memory_path, str(img.get("sha256") or ""), str(img.get("ext") or ""))
        here = path is not None and path.is_file()
        images.append({"kind": img.get("kind"), "width": int(img.get("width") or 0),
                       "height": int(img.get("height") or 0), "bytes": int(img.get("bytes") or 0), "onThisMac": here,
                       "url": f"/explore/captures/{entity_id}/{cid}/image/{img.get('kind')}" if here else None})
    return {
        "id": cid, "entityId": entity_id, "url": cap.get("url"), "site": cap.get("site"),
        "capturedAt": cap.get("captured_at"), "recordedAt": cap.get("recorded_at"),
        "capturedAtFlagged": bool(cap.get("captured_at_flagged")), "savedAt": cap.get("saved_at"),
        "whyAt": cap.get("why_at"), "lastModified": cap.get("last_modified"), "outcome": cap.get("outcome"),
        "context": cap.get("context"), "signedIn": bool(cap.get("signed_in")),
        "accountVisible": bool(cap.get("account_visible")), "consentOverlay": bool(cap.get("consent_overlay")),
        "depth": cap.get("depth"), "addedBy": cap.get("added_by"), "finalUrl": cap.get("final_url"),
        "httpStatus": cap.get("http_status"), "title": cap.get("title"), "description": cap.get("description"),
        "thumb": thumb_out, "images": images, "palette": cap.get("palette") or [], "look": cap.get("look") or [],
        "fonts": cap.get("fonts") or [], "outline": cap.get("outline") or [],
        "components": cap.get("components") or [], "change": cap.get("change") or {}, "shape": SHAPE,
        "pages": [_page_wire(memory_path, entity_id, cid, i, p) for i, p in enumerate(cap.get("pages") or [])
                  if isinstance(p, dict)],
        "section": cap.get("section"), "plan": cap.get("plan"),
    }


def _page_wire(memory_path, entity_id: str, cid: str, index: int, page: dict) -> dict:
    thumb = page.get("thumb") if isinstance(page.get("thumb"), dict) else None
    thumb_url = (f"/explore/captures/{entity_id}/{cid}/pages/{index}/thumb"
                 if thumb and thumb_file(memory_path, thumb.get("file")) is not None else None)
    return {"url": page.get("url"), "kind": page.get("kind"), "title": page.get("title"),
            "outcome": page.get("outcome"), "loadedAt": page.get("loaded_at"), "chosenBy": page.get("chosen_by"),
            "thumbUrl": thumb_url, "look": page.get("look") or [], "palette": page.get("palette") or [],
            "change": page.get("change")}


def page_thumb(memory_path, cap: dict, index: int) -> Path | None:
    """A further page's thumbnail, from the bank only."""
    pages = [p for p in cap.get("pages") or [] if isinstance(p, dict)]
    if not 0 <= index < len(pages):
        return None
    thumb = pages[index].get("thumb") if isinstance(pages[index].get("thumb"), dict) else None
    return thumb_file(memory_path, (thumb or {}).get("file"))


def image_for(memory_path, cap: dict, kind: str) -> tuple[Path, str] | None:
    """A full image of a capture from the outside store, by kind — only a file the record names by its hash."""
    for img in cap.get("images") or []:
        if isinstance(img, dict) and img.get("kind") == kind:
            ext = str(img.get("ext") or "")
            path = full_image_path(memory_path, str(img.get("sha256") or ""), ext)
            if path is not None and path.is_file():
                return path, "image/jpeg" if ext == "jpg" else "image/png"
    return None


def commit_lines(paths: list[str], trigger: str) -> list[str]:
    return [f"{p}: created (source: n/a, trigger: {trigger})" for p in dict.fromkeys(paths)]
