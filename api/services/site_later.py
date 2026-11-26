"""A save noticed on a page that names no post: held by its words until the site's list names it (G221, ruling 77e).

LinkedIn's feed shows a post with no link to it and no id of its own (measured 2026-11-25 and 2026-11-26: the block's
DOM id is a token of the page, the post's address appears only on the post's own page and on the saved list). The app
still sees the person's own click on the save item of that post's menu, and can read the words the block shows. So
the post is named by those words:

* **A post Cicada already holds** (the list was read, or it was saved from its own page) is found by its own first
  words inside what the block showed, and by its author's name when the save keeps one. The click is then about that
  link, and the record decides which way it went (``POST /sources/site-change``).
* **Any other post** was just saved, and has no link yet. Nothing is written into the bank for it: a row with no link
  would be a second row the day the list read brings the post. Instead the moment is held here, outside every bank
  (the block's words, scrubbed and capped, and when), with whatever the person answers the notch. The next read of
  the site's saved list names the post; the answer is then attached to that save as said when it was said, and the
  held words are dropped. A held save the person takes back (the same words clicked again) is dropped at once.

Held entries are few, short-lived (:data:`KEEP`) and never read by a model. Nothing here fetches a page.
"""
from __future__ import annotations

import fcntl
import json
import os
import secrets
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlparse

from api.services import episode_scrub, saved_lists
from api.services.auth import cicada_home

FILENAME = "site_later.json"
#: The sites whose feed names no post: a save there is named by its words.
SITES = frozenset({"linkedin"})
#: What the block showed, as kept: enough to hold the post's first lines beside its header.
WORDS_MAX = 2000
#: How long a held save waits for the list to name it. The list is read daily when the person's agent runs.
KEEP = timedelta(days=30)
#: Held saves per memory; the oldest fall off.
MAX_HELD = 40
#: How many letters and digits of a post's own first words must be found in the block for it to be that post.
MIN_FOLD = 24
#: The same for a post Cicada holds, where a wrong match would mark a save as taken off the list.
MIN_HELD_FOLD = 40
#: The query key of the placeholder address a held save is answered by. Never a post's address.
MARK = "cicada-later"


def path() -> Path:
    return cicada_home() / FILENAME


def fold(text) -> str:
    """Letters and digits only, case folded: what two readings of the same post share, whatever each did with line
    breaks, emoji, hashtags' marks or the page's "more" ellipsis."""
    normal = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(ch for ch in normal if ch.isalnum())


def clean(words) -> str:
    """The block's words as kept: one line per run of text, extra spaces folded, capped, scrubbed."""
    lines = [" ".join(line.split()) for line in str(words or "").splitlines()]
    kept = "\n".join(line for line in lines if line)[:WORDS_MAX]
    return episode_scrub.scrub(kept)[0]


def title_of(words: str, site: str) -> str:
    """What the notch calls the post: its longest line (the post's own words, as a rule), else the site's name."""
    from api.services import site_saves

    longest = max((line for line in words.splitlines()), key=len, default="")
    platform = saved_lists.PLATFORMS.get(site)
    return site_saves.title_for(longest if len(fold(longest)) >= MIN_FOLD else "",
                                f"{platform.name if platform else site} post")


def later_url(site: str, key: str) -> str:
    """The address a held save is answered by: on the site's own host (so muting the site covers it), never a post."""
    platform = saved_lists.PLATFORMS.get(site)
    return f"https://www.{platform.site if platform else site}/?{MARK}={key}"


def key_of(url) -> tuple[str, str] | None:
    """``(site, key)`` when ``url`` is a held save's placeholder address."""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return None
    keys = parse_qs(parsed.query).get(MARK) or []
    host = (parsed.hostname or "").lower()
    if len(keys) != 1 or not keys[0].isalnum() or parsed.path not in ("", "/"):
        return None
    for site in SITES:
        platform = saved_lists.PLATFORMS.get(site)
        if platform is not None and (host == platform.site or host.endswith("." + platform.site)):
            return site, keys[0]
    return None


def _prefix_in(text: str, block: str, least: int) -> int:
    """How many folded characters of ``text``'s start are found in ``block``: the whole of it, else a shorter start
    (a list shows a post cut off, with the page's own word for "more" after the cut), never fewer than ``least``."""
    folded = fold(text)
    for size in (len(folded), 160, 80, 60, least):
        if least <= size <= len(folded) and folded[:size] in block:
            return size
    return 0


def held_url(memory_path: Path, site: str, words: str) -> str | None:
    """The link of a save of ``site`` Cicada holds whose own first words the block showed, or ``None``. When the save
    keeps its author's name, the block must show that too (posts made from a site's template start alike)."""
    from api.services import bank_index, media_ingestor

    block = fold(words)
    if len(block) < MIN_HELD_FOLD:
        return None
    best: tuple[int, str] | None = None
    for row in media_ingestor.load_url_index(memory_path).values():
        url = row.get("url") if isinstance(row, dict) else None
        if not url or saved_lists.canonical(site, url) is None:
            continue
        size = _prefix_in(row.get("title") or "", block, MIN_HELD_FOLD)
        if not size or (best is not None and best[0] >= size):
            continue
        entry = bank_index.file(memory_path, "entities", f"{row.get('media_entity_id')}.md")
        media = entry.frontmatter.get("media") if entry is not None else None
        author = fold(media.get("channel")) if isinstance(media, dict) else ""
        if author and author not in block:
            continue
        best = (size, url)
    return best[1] if best else None


def _load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".site-later-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def _locked() -> Iterator[dict]:
    lock = path().with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            data = _load()
            yield data
            _save(data)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)


def _entries(data: dict, memory_path: Path, now: datetime) -> list[dict]:
    """This memory's held saves, the expired ones dropped."""
    bank = data.setdefault("banks", {}).setdefault(Path(memory_path).name[:64], {})
    held = [e for e in bank.get("held") or [] if isinstance(e, dict)]
    fresh = []
    for entry in held:
        try:
            at = datetime.fromisoformat(str(entry.get("at")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if now - at <= KEEP:
            fresh.append(entry)
    bank["held"] = fresh
    return fresh


def _same_post(a: str, b: str) -> bool:
    """Two readings of one block: one's folded words hold most of the other's start (a count on the post may have
    moved between the two clicks, so they are not compared whole)."""
    x, y = fold(a), fold(b)
    short, long = (x, y) if len(x) <= len(y) else (y, x)
    if len(short) < MIN_HELD_FOLD:
        return False
    size = max(MIN_HELD_FOLD, len(short) // 2)
    return any(short[i:i + size] in long for i in range(0, len(short) - size + 1, max(1, size // 2)))


def hold(memory_path: Path, site: str, words: str, now: datetime | None = None) -> tuple[dict, bool]:
    """Hold a save just made on a post no link names. Returns ``(entry, taken_back)``: when the same post is already
    held, the click took the save back, the held entry is dropped and returned with ``taken_back`` true."""
    moment = _now(now)
    with _locked() as data:
        held = _entries(data, memory_path, moment)
        for entry in held:
            if entry.get("site") == site and _same_post(entry.get("words") or "", words):
                held.remove(entry)
                return entry, True
        entry = {"key": secrets.token_hex(8), "site": site, "words": words, "at": moment.isoformat(), "answers": []}
        held.append(entry)
        del held[:-MAX_HELD]
        return entry, False


def find(memory_path: Path, key: str) -> dict | None:
    return next((e for e in _entries(_load(), memory_path, _now(None)) if e.get("key") == key), None)


def answer(memory_path: Path, key: str, record: dict, replacing: str | None = None) -> list[dict] | None:
    """Keep the person's answer on a held save (``record``: ``saved_why``'s own stored shape). ``replacing`` is the
    ``at`` of an answer it changes. Returns the held answers, or ``None`` when nothing is held under ``key``."""
    with _locked() as data:
        entry = next((e for e in _entries(data, memory_path, _now(None)) if e.get("key") == key), None)
        if entry is None:
            return None
        drop = replacing or record.get("at")
        answers = [a for a in entry.get("answers") or [] if a.get("at") != drop]
        if replacing and len(answers) == len(entry.get("answers") or []):
            return None
        entry["answers"] = sorted(answers + [record], key=lambda a: str(a.get("at") or ""))
        return list(entry["answers"])


def settle(memory_path: Path, site: str, rows) -> list[tuple[str, list[dict]]]:
    """The list was read: ``rows`` is ``(link, words)`` for each post it showed. Every held save one of them names is
    dropped from here and returned as ``(link, answers)`` for the caller to attach; a held save named by no row
    waits. A row names a held save when its own first words are in the words the block showed."""
    rows = [(url, text) for url, text in rows if url and len(fold(text)) >= MIN_FOLD]
    if not rows or not path().is_file():
        return []
    out: list[tuple[str, list[dict]]] = []
    with _locked() as data:
        held = _entries(data, memory_path, _now(None))
        for entry in [e for e in held if e.get("site") == site]:
            block = fold(entry.get("words"))
            sized = [(_prefix_in(text, block, MIN_FOLD), url) for url, text in rows]
            size, url = max(sized, default=(0, ""))
            if not size:
                continue
            held.remove(entry)
            if entry.get("answers"):
                out.append((url, list(entry["answers"])))
    return out

