"""One episode-id rule and one clock for every capture writer (G114).

Every Awake writer — the conversation importer, the MCP ``cicada_save_episode``
tool, the media/URL ingestor, the Telegram webhook, the calendar and notes
syncs — mints an ``ep_<YYYY-MM-DD>_<NNN>`` id and stamps a ``timestamp``. Until
this module each carried its own copy of both rules, and the copies disagreed:

- **Id.** Four writers did max-suffix+1 (collision-free); the importer counted
  files per date and added one, which collides — and silently OVERWRITES — the
  moment a same-day episode has been deleted or the sequence has a gap (a
  ``_003`` beside no ``_001``/``_002`` gets clobbered on the second write).
  Ruling R1: the id is ``1 + max(existing suffixes for that date)``, always.
- **Timestamp.** Three writers stamped ``datetime.now().isoformat() + "Z"`` —
  naive LOCAL time falsely labelled UTC, off by the machine's offset — while
  the two newest emitted a real aware-UTC ``+00:00`` stamp. Ruling R2: every
  stamp is what ``datetime.now(timezone.utc).isoformat()`` yields. Existing
  files are NOT migrated; readers already accept both shapes, and
  :func:`timestamp_sort_key` lets a queue order legacy naive-local stamps
  correctly against new UTC ones.

Pure filesystem + ``datetime``; no bank state, no LLM, importable from the MCP
server (which only has ``api.services`` on its path) as freely as from a router.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

# Anchored so the stem `ep_2026-09-01_001` matches and `ep_2026-09-01_x`,
# `sleep_2026-09-01_001` or a stem with its `.md` still attached do not. The
# suffix is `\d+`, not `\d{3}`: zero-padding is a formatting choice on write,
# and a bank that has minted its thousandth same-day episode (`_1000`) must
# keep counting rather than restart at `_001` and overwrite.
EPISODE_ID_RE: re.Pattern[str] = re.compile(r"^ep_(\d{4}-\d{2}-\d{2})_(\d+)$")


def parse_episode_id(stem: str) -> tuple[str, int] | None:
    """``"ep_2026-09-01_005"`` → ``("2026-09-01", 5)``; anything else → ``None``."""
    m = EPISODE_ID_RE.match(stem)
    if m is None:
        return None
    return m.group(1), int(m.group(2))


def max_suffix_by_date(episodes_dir: Path) -> dict[str, int]:
    """Highest existing suffix per date, from ONE ``glob("ep_*.md")``.

    Tolerant of junk: a file whose stem doesn't parse (``ep_2026-09-01_x.md``,
    a stray ``README.md``) is skipped, never raised on — a hand-edited bank
    must not stop every writer from minting ids. A missing directory is an
    empty bank, not an error, so a writer can seed before its first
    ``mkdir``. This is what the importer seeds its per-batch counter from
    (R1) instead of counting files.
    """
    result: dict[str, int] = {}
    if not episodes_dir.is_dir():
        return result
    for filepath in episodes_dir.glob("ep_*.md"):
        parsed = parse_episode_id(filepath.stem)
        if parsed is None:
            continue
        ep_date, num = parsed
        if num > result.get(ep_date, 0):
            result[ep_date] = num
    return result


def next_episode_id(episodes_dir: Path, ep_date: str) -> str:
    """Next ``ep_<ep_date>_NNN`` = 1 + max existing suffix for that date (R1).

    Max-based, never count-based: a count collides after any deletion or gap
    and — because every writer calls ``markdown_parser.write`` unconditionally
    — a collision is a silent overwrite of a real episode. Zero-padded to
    three digits for the common case; a fourth digit simply appears when a
    day runs past 999, and :data:`EPISODE_ID_RE` reads it back fine.
    """
    max_num = 0
    if episodes_dir.is_dir():
        for filepath in episodes_dir.glob(f"ep_{ep_date}_*.md"):
            parsed = parse_episode_id(filepath.stem)
            if parsed is not None and parsed[0] == ep_date:
                max_num = max(max_num, parsed[1])
    return f"ep_{ep_date}_{max_num + 1:03d}"


# --- The one clock (R2) --------------------------------------------------------


def utc_now_iso() -> str:
    """Now, as aware-UTC ISO-8601 with an explicit ``+00:00`` (R2).

    The one shape every new episode ``timestamp`` takes. ``+00:00`` rather than
    ``Z`` because that is what ``datetime.isoformat()`` emits natively — no
    string surgery on either side, and Python 3.11's ``fromisoformat`` reads
    both, so a reader never has to know which writer produced the file.
    """
    return datetime.now(timezone.utc).isoformat()


def to_utc_iso(value: datetime | int | float) -> str:
    """Normalise an epoch or a ``datetime`` to the R2 shape.

    - epoch seconds (``int``/``float``) → ``fromtimestamp(value, timezone.utc)``.
      Never ``fromtimestamp(value)`` alone — that lands in local time, which is
      exactly the bug the ``+ "Z"`` idiom used to bake into imports.
    - a naive ``datetime`` is ASSUMED UTC (the only honest choice for a value
      that arrived without a zone from an export or an API).
    - an aware ``datetime`` is converted with ``astimezone``.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            dt = value.replace(tzinfo=timezone.utc)
        else:
            dt = value.astimezone(timezone.utc)
    else:
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
    return dt.isoformat()


def timestamp_sort_key(raw: str | None) -> str:
    """A normalised UTC ISO key for ORDERING episode timestamps of any shape.

    Banks hold three shapes side by side and always will (R2 forbids a
    migration): legacy naive local (``2026-09-01T10:00:00``), ``Z``-suffixed
    (``…T08:00:00Z``), and the new ``+00:00``. Lexical order across those is
    wrong by the machine's UTC offset, so the Sleep queue sorts on this key
    instead. A NAIVE input is read as LOCAL time — the same reading
    ``sleep_debt._parse_episode_timestamp`` gives it, because that is what
    the writers that produced it meant — and converted to UTC. Anything
    unparseable (``None``, garbage, a non-string) sorts first as ``""`` rather
    than raising: one bad file must not hide the whole queue. That promise
    covers the CONVERSION too, not just the parse — a naive stamp at either
    end of the calendar (``0001-01-01T00:00:00``, ``9999-12-31T23:59:59``)
    parses fine but ``astimezone()`` then walks it out of range and raises
    ``ValueError``/``OverflowError`` (and the platform ``localtime`` behind it
    can raise ``OSError``), which aborted the Sleep cycle and 500'd
    ``GET /sleep/episodes`` for one absurd file.
    """
    if not raw or not isinstance(raw, str):
        return ""
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.astimezone()  # naive → local-aware, matching sleep_debt's reading
        return dt.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return ""
