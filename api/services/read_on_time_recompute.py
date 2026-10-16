"""Place an existing bank's late-read conversations on the day they were said — once, run by the person (owner ruling
2026-10-16, "read on time"; ``api/scripts/recompute_read_on_time.py``).

Before the ruling, a conversation dated before a page's watermark and read later (a newly connected source's history,
an export imported after the page was known) added its source and its week and moved nothing else: the page stayed
where decay had left it, as if the topic had been silent all along. Sleep now places such a mention on its day
(``conflict_resolver._revive_on_time``, ``claim_reconciler._place_on_time``); this recompute does the same, once, for
what was read before.

Which pages: the old rule leaves one mark. Every other Sleep path that moves a page's last mention also moves
``learned_on`` to the day it was read (on or after the day it was said), so a page whose ``last_referenced`` is LATER
than its ``learned_on`` got its newest mention through the old late-read branch — when that newest mention is one of the
page's own dated conversations. Writers that are no conversation (an agent's progress note, a decay answer, a conflict
resolution) also move ``last_referenced`` and leave ``learned_on`` alone; a page whose newest mention no credited
conversation was said on is theirs, and is left alone (``_page_mention_day``). For such a page the newest mention is placed
on its day exactly as Sleep now would (``decay_policy.on_time`` from ``RECOVERY_CONFIDENCE``, through the watermark
plus at most one pass of live silence). A claim carries the same mark (its latest dated conversation after its
``recorded_at``); the confidence its late restatement carried is not stored, so it is placed from
``RECOVERY_CONFIDENCE`` too — never more than a page's revival. A mention said exactly the day its page was last read
is indistinguishable from an ordinary one and is left alone.

Only raises: confidence and status (to ``decaying`` or ``active``; an archived page lifted below 0.2 stays archived).
A page or claim the placement leaves below 0.4, heard more than a week late, is marked ``faded_by_age`` (never asked);
one it takes to 0.4 or above loses the mark. Never touched: evergreen pages (the owner's page among them), dropped
pages, pages with no dated mention or no ``learned_on``, pages with a placement Sleep still owes (``read_late``),
pages dirty in git or written since the survey. No inbox item is written. A second run changes nothing.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from loguru import logger

from api.models.schemas import DecayClass
from api.services import (
    claims, decay_policy, decay_tuning, episode_time, git_service, markdown_parser, page_lock, write_admission,
)
from api.services.claim_reconciler import MAX_DECAY_DAYS_PER_CYCLE, claim_rate, open_
from api.services.claims import Claim, is_event
from api.services.conflict_resolver import RECOVERY_CONFIDENCE, _revive_on_time

TRIGGER = "maintenance/read-on-time"
ARCHIVE_THRESHOLD = 0.2
NUDGE_THRESHOLD = 0.4


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: change nothing."""


def _bucket() -> dict[str, int]:
    return {"read_late": 0, "lifted": 0, "to_active": 0, "to_decaying": 0, "still_archived": 0, "claims_lifted": 0}


@dataclass
class Survey:
    """Counts only — never a name, a path or a word of the bank."""

    pages: int = 0
    read_late: int = 0          # pages whose newest mention came through the old late-read branch
    lifted: int = 0             # ... that reading it on time lifts
    to_active: int = 0
    to_decaying: int = 0
    still_archived: int = 0     # lifted, but an archived page its age keeps below 0.2
    faded_by_age: int = 0       # lifted pages left below 0.4, heard late: never asked
    claims_read_late: int = 0
    claims_lifted: int = 0
    claims_skipped_legacy_fence: int = 0
    dirty: int = 0
    written: int = 0
    committed: bool = False
    by_type: dict[str, dict[str, int]] = field(default_factory=dict)
    _todo: dict[Path, tuple[str, dict, str]] = field(default_factory=dict, repr=False)

    def counts(self) -> dict:
        out = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        out["by_type"] = {k: dict(v) for k, v in sorted(self.by_type.items())}
        return out


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10]) if value else None
    except ValueError:
        return None


#: A conversation's id carries its day; its stamp may sit one day off it (a local day against a UTC stamp).
_DAY_SLACK = timedelta(days=1)
#: A lift smaller than this is float noise between one charge and the same charge in steps, never a lift.
_EPSILON = 1e-9


def _page_mention_day(fm: dict, untimed) -> str | None:
    """The day of the page's newest mention when that mention is a conversation the page credits, else ``None``.

    ``last_referenced`` is also moved by writers that are no conversation and leave ``learned_on`` alone (an agent's
    progress note, a decay answer, a conflict resolution): those left the same mark as a late read, and reading on time
    never revived a page for them. Only a newest mention one of the page's own dated conversations was said on (within
    a day's slack, the earlier of the two days) is placed."""
    said = _day(fm.get("last_referenced"))
    conv = _day(decay_policy.latest_said(fm.get("source_episodes"), untimed=untimed))
    if said is None or conv is None or conv < said - _DAY_SLACK:
        return None
    return min(said, conv).isoformat()


def _dirty_entities(memory_path: Path) -> frozenset[str]:
    """``entities/`` paths dirty in git — read with git's optional locks off, so a survey never refreshes (writes) the
    index or takes its lock from under a running backend's commit."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-z", "--untracked-files=all", "--", "entities"],
            cwd=str(memory_path), capture_output=True, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except OSError:
        return frozenset()
    if proc.returncode != 0:
        return frozenset()
    return git_service._parse_status_z(proc.stdout.decode(errors="replace"))


def _read_late(said, learned, charged) -> bool:
    """The old rule's mark: the newest mention said after the day Cicada last read the page (or claim), and before
    its watermark."""
    s, r, c = _day(said), _day(learned), _day(charged)
    return s is not None and r is not None and c is not None and r < s < c


def _place_claims(body: str, about, multiplier: float, untimed, today: date, tally: dict, result: Survey) -> str:
    """The page body with its late-read open claims placed on their day; only changed fence lines rewritten."""
    match = claims._CLAIMS_BLOCK_RE.search(body or "")
    if match is None or multiplier <= 0:
        return body
    payload = match.group("payload")
    if not payload.strip() or payload.strip() == "[]":
        return body
    if not claims.is_jsonl_payload(payload):
        result.claims_skipped_legacy_fence += 1   # `migrate_claims_jsonl` converts it; never re-rendered here
        return body
    from api.services.claim_reconciler import _said, _said_refs

    lines = payload.split("\n")
    changed = False
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            claim = Claim.from_dict(raw)
        except (ValueError, TypeError):
            continue   # an unreadable line is kept byte for byte
        if not isinstance(raw, dict) or not open_(claim) or is_event(claim) or claim.read_late:
            continue
        said = _said(claim, untimed)
        if not _read_late(said, claim.recorded_at, claim.decayed_through):
            continue
        result.claims_read_late += 1
        through = decay_policy.through_day(claim.decayed_through, today, MAX_DECAY_DAYS_PER_CYCLE)
        rate = claim_rate(claim, about, multiplier, untimed=untimed)
        lifted = decay_policy.on_time(
            RECOVERY_CONFIDENCE, rate, said, claim.recorded_at, through, nudge_threshold=NUDGE_THRESHOLD,
            conversations=decay_policy.conversations(_said_refs(claim), untimed=untimed))
        if lifted is None or lifted <= claim.confidence + _EPSILON:
            continue
        raw["confidence"] = lifted
        raw["decayed_through"] = through.isoformat()
        if lifted >= NUDGE_THRESHOLD:
            raw.pop("faded_by_age", None)
        elif decay_policy.heard_late(said, today) and not raw.get("faded_by_age"):
            raw["faded_by_age"] = today.isoformat()
        lines[i] = claims._jsonl_line(raw)
        changed = True
        result.claims_lifted += 1
        tally["claims_lifted"] += 1
    if not changed:
        return body
    return body[:match.start("payload")] + "\n".join(lines) + body[match.end("payload"):]


def survey(memory_path, *, today: date | None = None, settings=None) -> Survey:
    """What :func:`apply` would change. Read-only."""
    memory_path = Path(memory_path)
    today = today or date.today()
    result = Survey()
    dirty: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        dirty = _dirty_entities(memory_path)
    untimed = episode_time.untimed_ids(memory_path)
    tuning = decay_tuning.load(memory_path)
    alpha, floor = decay_policy.spacing_params(settings)
    subject = decay_policy.subject_lookup(memory_path, tuning=tuning)
    params = {"today": today.isoformat(), "alpha": alpha, "floor": floor, "tuning": tuning,
              "archive": ARCHIVE_THRESHOLD, "nudge": NUDGE_THRESHOLD}

    for path in sorted((memory_path / "entities").glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — a malformed page is skipped, never fatal
            continue
        fm = parsed.frontmatter
        if not isinstance(fm, dict):
            continue
        result.pages += 1
        if decay_policy.resolve(fm)[0] is DecayClass.evergreen or fm.get("owner"):
            continue
        if str(fm.get("status", "active") or "active") == "dropped" or fm.get(decay_policy.READ_LATE_KEY):
            continue
        if f"entities/{path.name}" in dirty:
            result.dirty += 1
            continue
        kind = decay_policy.entity_type(fm)
        tally = result.by_type.setdefault(kind, _bucket())
        new_fm = dict(fm)
        said = _page_mention_day(fm, untimed)
        if said is not None and _read_late(said, fm.get("learned_on"), fm.get("decayed_through")):
            result.read_late += 1
            tally["read_late"] += 1
            _revive_on_time(new_fm, said, params, untimed)
            if float(new_fm.get("confidence") or 0.0) <= float(fm.get("confidence") or 0.0) + _EPSILON:
                new_fm = dict(fm)   # float noise, not a lift
            if new_fm.get("confidence") != fm.get("confidence"):
                result.lifted += 1
                tally["lifted"] += 1
                landed = str(new_fm.get("status"))
                key = {"active": "to_active", "decaying": "to_decaying"}.get(landed, "still_archived")
                setattr(result, key, getattr(result, key) + 1)
                tally[key] += 1
                result.faded_by_age += bool(new_fm.get(decay_policy.FADED_BY_AGE_KEY)) and landed != "active"
        about = subject(path.stem)
        new_body = _place_claims(parsed.body, about, decay_policy.claim_multiplier(about.decay_class), untimed,
                                 today, tally, result)
        if new_fm != fm or new_body != parsed.body:
            result._todo[path] = (text, new_fm, new_body)
    result.by_type = {k: v for k, v in result.by_type.items() if v["read_late"] or v["claims_lifted"]}
    return result


def apply(memory_path, *, sleep_running: Callable[[], bool], today: date | None = None, settings=None) -> Survey:
    """Write the survey's changes and commit them in ONE commit authored ``cicada``. Raises :class:`SleepRunning`
    before writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    written: list[Path] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; recompute after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path, today=today, settings=settings)
            for path, (surveyed, fm, body) in result._todo.items():
                if path.read_text(encoding="utf-8") != surveyed:   # written since the survey: its writer's to commit
                    result.dirty += 1
                    continue
                markdown_parser.write(path, fm, body)
                written.append(path)
            rels = [f"entities/{p.name}" for p in written]
            result.written = len(rels)
            if rels and (memory_path / ".git").exists():
                message = git_service.build_commit_message(
                    f"Read on time: {len(rels)} page(s)",
                    [f"{rel}: decay (trigger: {TRIGGER})" for rel in rels],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
    if written:
        logger.info(f"read-on-time recompute: {len(written)} page(s)")
    return result
