"""G147 — how fast each KIND of page fades, as the person chose it.

Agent proposes, person disposes (UX principle 3). The proposal is derived from
the bank's OWN git history — every decay answer since G113 R1 commits as
``entities/<id>.md: status active|archived (trigger: inbox/decay/resolved:<label>)``
— never from the machine-global telemetry ledger (nothing learned there is
auto-applied, G78/G113), and nothing here applies itself: a suggestion changes
decay only after ``PUT /memory/decay-tuning``.

``<bank>/_decay_tuning.yaml`` lives IN the bank so "let people fade more
slowly" travels with it (portability), and is committed alone as
``Cicada-Author: user`` (``commit_paths``, never ``git add -A``). Plan rulings
R-FD5 … R-FD8.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml

from api.models.schemas import EntityType

FILE = "_decay_tuning.yaml"
WINDOW_DAYS = 180
MIN_ANSWERS = 5
# "At least 80 %" as integers — 5·part >= 4·whole — so 8 of 10 is exactly on
# the line, never a float's guess (R-FD6).
_SHARE_NUM, _SHARE_DEN = 4, 5
SLOWER = 0.5
FASTER = 1.5
MIN_MULTIPLIER = 0.25
MAX_MULTIPLIER = 3.0
_TYPES = frozenset(t.value for t in EntityType)
_HEADER = (
    "# How fast each kind of page fades, as a multiple of its usual pace (G147).\n"
    "# Written by Settings → Memory when you apply a suggestion; 0.5 = half as fast.\n"
)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def load(memory_path) -> dict[str, float]:
    """The bank's per-type pace; a missing, corrupt or hand-mangled file reads as
    none, and an entry outside the rules is dropped rather than trusted."""
    if not memory_path:
        return {}
    try:
        data = yaml.safe_load((Path(memory_path) / FILE).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        # ValueError covers UnicodeDecodeError: a hand edit saved as Latin-1 must
        # read as no tuning, not raise out of Stage 3, every entity read and the
        # /memory routes that would let Reset repair it (R4 final review).
        return {}
    types = data.get("types") if isinstance(data, dict) else None
    out: dict[str, float] = {}
    for etype, value in (types.items() if isinstance(types, dict) else []):
        number = _number(value)
        if str(etype) in _TYPES and number is not None and number != 1.0 \
                and MIN_MULTIPLIER <= number <= MAX_MULTIPLIER:
            out[str(etype)] = number
    return dict(sorted(out.items()))


def merge(current: dict[str, float], changes: dict) -> dict[str, float]:
    """Apply one PUT body (R-FD7). Keys absent from ``changes`` are untouched;
    ``None`` or exactly ``1.0`` clears a type. Raises ``ValueError`` with a plain
    sentence the app can show."""
    out = dict(current)
    for etype, value in (changes or {}).items():
        etype = str(etype)
        if etype not in _TYPES:
            raise ValueError(f"'{etype}' isn't a kind of page Cicada knows")
        number = None if value is None else _number(value)
        if value is None or number == 1.0:
            out.pop(etype, None)
            continue
        if number is None or not MIN_MULTIPLIER <= number <= MAX_MULTIPLIER:
            raise ValueError(
                f"A pace must be between {MIN_MULTIPLIER} and {MAX_MULTIPLIER} times the usual"
            )
        out[etype] = number
    return dict(sorted(out.items()))


def save(memory_path, tuning: dict[str, float]) -> bool:
    """Write the file. ``False`` when nothing would change — including never
    creating a file just to hold ``{}`` — so the caller makes no empty commit."""
    path = Path(memory_path) / FILE
    if not tuning and not path.exists():
        return False
    text = _HEADER + yaml.safe_dump({"types": dict(sorted(tuning.items()))}, sort_keys=False)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    return True


async def answers(memory_path, *, today: date) -> dict[str, dict[str, int]]:
    """``{type: {"kept": n, "archived": n}}`` over the window — ONE vote per page,
    its latest answer (R-FD6), under the page's CURRENT type. Only ids and
    ``type`` are read; a page that no longer exists is skipped."""
    from api.services import decay_policy, git_service, markdown_parser

    verdicts = await git_service.decay_verdicts(
        Path(memory_path), since=today - timedelta(days=WINDOW_DAYS)
    )
    counts: dict[str, dict[str, int]] = {}
    for entity_id, label in verdicts.items():
        path = Path(memory_path) / "entities" / f"{entity_id}.md"
        if not path.is_file():
            continue
        try:
            fm = markdown_parser.parse(path).frontmatter or {}
        except Exception:  # noqa: BLE001 — one unreadable page never hides the rest
            continue
        bucket = counts.setdefault(decay_policy.entity_type(fm), {"kept": 0, "archived": 0})
        bucket["kept" if label == "keep_active" else "archived"] += 1
    return counts


def suggest(counts: dict[str, dict[str, int]], tuning: dict[str, float]) -> list[dict]:
    """A suggestion per type with >= 5 answers and >= 80 % one way, unless that
    pace is already the person's choice. Most-answered first."""
    out: list[dict] = []
    for etype, c in counts.items():
        kept, archived = int(c.get("kept", 0)), int(c.get("archived", 0))
        total = kept + archived
        if total < MIN_ANSWERS:
            continue
        if _SHARE_DEN * kept >= _SHARE_NUM * total:
            direction, multiplier = "slower", SLOWER
        elif _SHARE_DEN * archived >= _SHARE_NUM * total:
            direction, multiplier = "faster", FASTER
        else:
            continue
        if tuning.get(etype) == multiplier:
            continue
        out.append({"type": etype, "direction": direction, "multiplier": multiplier,
                    "kept": kept, "archived": archived, "answers": total})
    out.sort(key=lambda s: (-s["answers"], s["type"]))
    return out


async def overview(memory_path, *, today: date | None = None) -> dict:
    """The one response shape both endpoints return (R-FD7)."""
    today = today or date.today()
    tuning = load(memory_path)
    return {
        "bank": Path(memory_path).name,
        "window_days": WINDOW_DAYS,
        "tuning": tuning,
        "suggestions": suggest(await answers(memory_path, today=today), tuning),
    }
