"""Charge an existing bank's pages and claims the age of what they came from — once, run by the person (owner ruling
2026-10-09, "let age count"; ``api/scripts/recompute_decay_by_age.py``).

Before the ruling, a page Sleep created or referenced from an old conversation kept that date as its last mention
but started its silence clock the day Cicada read it (G170's "an import is not silence"), so a bank built from a
backdated export holds two-year-old one-off topics at the confidence of something said this week. Sleep now charges
that silence itself (``decay_policy.silence``) for everything it reads from here on; this recompute charges it, once,
for what was read before.

For one page: the silence its conversations prove runs from its last mention (``last_referenced``) to the day Cicada
read that mention. That day is not stored on a page written before the ruling, so it is estimated from git — the day
the page was added, or the last mention itself when that is later (a page mentioned again after it was added was
read live). Without git it is the page's watermark (``decayed_through``), and the count says so
(``learned_without_git``). The charge is the page's own pace (``decay_policy.effective``: class x spacing x the
bank's per-type pace) over those weeks; the page gets ``learned_on`` (the estimate) and a watermark no earlier than
it, so the next Sleep pass charges only live silence after it — never this gap again. For one open, non-event claim:
from its latest dated conversation to ``recorded_at``, at its own pace (``claim_reconciler.claim_rate``); only the
changed lines of a JSON Lines fence are rewritten, every other byte kept.

Only lowers: confidence and status (below 0.4 ``decaying``, below 0.2 ``archived`` — the page stays in ``entities/``
and recall still finds it). Never touched: evergreen pages (the owner's page among them), archived and dropped pages,
pages with no dated mention (a memory export entry alone), pages Sleep already charged by age (``learned_on``
present), pages dirty in git or written since the survey. One-offs archive, repeats fade (owner 2026-10-09): a page or
claim resting on 2+ distinct dated conversations is never taken below 0.39, just under the question line, by this
charge (``decay_policy.charge``; ``floored_repeats`` counts the pages that floor held). No inbox item is written; a page
or claim this charge leaves below 0.4 is marked ``faded_by_age`` and Sleep fades and archives it quietly, never
asking — ``would_be_asked`` counts the few left decaying that were read within a week of being said.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from loguru import logger

from api.models.schemas import DecayClass
from api.services import (
    claims, decay_policy, decay_tuning, episode_time, git_service, markdown_parser, page_lock, write_admission,
)
from api.services.claim_reconciler import claim_rate, open_
from api.services.claims import Claim, is_event

TRIGGER = "maintenance/decay-by-age"
ARCHIVE_THRESHOLD = 0.2
NUDGE_THRESHOLD = 0.4
#: Age of the last mention on the run day, in days: the buckets the survey counts by.
AGE_BUCKETS = (("under_3_months", 91), ("3_to_12_months", 366), ("over_1_year", None))


class SleepRunning(RuntimeError):
    """Sleep holds this bank's pages, or a run is in progress: change nothing."""


def _bucket() -> dict[str, int]:
    return {"pages": 0, "lowered": 0, "archive": 0, "decaying": 0}


@dataclass
class Survey:
    """Counts only — never a name, a path or a word of the bank."""

    pages: int = 0
    eligible: int = 0
    already_by_age: int = 0
    lowered: int = 0
    would_archive: int = 0
    would_decay: int = 0
    would_be_asked: int = 0
    floored_repeats: int = 0
    claims_lowered: int = 0
    claims_below_nudge: int = 0
    claims_skipped_legacy_fence: int = 0
    learned_from_git: int = 0
    learned_without_git: int = 0
    dirty: int = 0
    written: int = 0
    committed: bool = False
    by_type: dict[str, dict[str, int]] = field(default_factory=dict)
    by_age: dict[str, dict[str, int]] = field(default_factory=lambda: {name: _bucket() for name, _ in AGE_BUCKETS})
    _todo: dict[Path, tuple[str, dict, str]] = field(default_factory=dict, repr=False)

    def counts(self) -> dict:
        out = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        out["by_type"] = {k: dict(v) for k, v in sorted(self.by_type.items())}
        out["by_age"] = {k: dict(v) for k, v in self.by_age.items()}
        return out


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10]) if value else None
    except ValueError:
        return None


def added_days(memory_path: Path) -> dict[str, date]:
    """``{page file name: the day its latest adding commit was made}``, from one read-only ``git log``; ``{}``
    without git. The newest add wins (``git log`` lists newest first), so a page removed and re-added counts from
    when it came back."""
    if not (memory_path / ".git").exists():
        return {}
    try:
        out = git_service._git_sync(memory_path, "log", "--diff-filter=A", "--no-renames", "--format=@%cs",
                                    "--name-only", "--", "entities")
    except Exception:  # noqa: BLE001 — no history is an estimate without git, never a failure
        return {}
    days: dict[str, date] = {}
    current: date | None = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("@"):
            current = _day(line[1:])
        elif line.startswith("entities/") and current is not None:
            days.setdefault(Path(line).name, current)
    return days


def _age_bucket(said: date, today: date) -> str:
    age = (today - said).days
    for name, limit in AGE_BUCKETS:
        if limit is None or age < limit:
            return name
    return AGE_BUCKETS[-1][0]


def _recompute_claims(body: str, subject_about, multiplier: float, untimed, result: Survey) -> str:
    """The page body with its open claims charged their proven silence; only changed fence lines rewritten."""
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
        if not isinstance(raw, dict) or not open_(claim) or is_event(claim):
            continue
        said, learned = _day(_said(claim, untimed)), _day(claim.recorded_at)
        if said is None or learned is None or learned <= said:
            continue
        rate = claim_rate(claim, subject_about, multiplier, untimed=untimed)
        new_conf = decay_policy.charge(
            claim.confidence, rate, decay_policy.Silence((learned - said).days, 0, learned),
            nudge_threshold=NUDGE_THRESHOLD,
            conversations=decay_policy.conversations(_said_refs(claim), untimed=untimed))
        if new_conf >= claim.confidence:
            continue
        raw["confidence"] = new_conf
        if new_conf < NUDGE_THRESHOLD and decay_policy.heard_late(said, learned) and not raw.get("faded_by_age"):
            raw["faded_by_age"] = learned.isoformat()   # its age took it below the line: Sleep never asks
        # The gap is charged: the next pass measures from no earlier than the day it was read.
        watermark = max([d for d in (_day(claim.decayed_through), learned) if d is not None])
        raw["decayed_through"] = watermark.isoformat()
        lines[i] = claims._jsonl_line(raw)
        changed = True
        result.claims_lowered += 1
        result.claims_below_nudge += new_conf < NUDGE_THRESHOLD
    if not changed:
        return body
    return body[:match.start("payload")] + "\n".join(lines) + body[match.end("payload"):]


def survey(memory_path, *, today: date | None = None, settings=None) -> Survey:
    """What :func:`apply` would change, and how many pages land where. Read-only."""
    memory_path = Path(memory_path)
    today = today or date.today()
    result = Survey()
    dirty: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            dirty = git_service.dirty_paths_sync(memory_path, "entities")
        except git_service.GitError:
            dirty = frozenset()
    added = added_days(memory_path)
    untimed = episode_time.untimed_ids(memory_path)
    tuning = decay_tuning.load(memory_path)
    alpha, floor = decay_policy.spacing_params(settings)
    subject = decay_policy.subject_lookup(memory_path, tuning=tuning)

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
        effective = decay_policy.effective(fm, alpha=alpha, floor=floor, tuning=tuning, untimed=untimed)
        status = str(fm.get("status", "active") or "active")
        said = _day(fm.get("last_referenced"))
        if effective.decay_class is DecayClass.evergreen or fm.get("owner") or said is None:
            continue
        if fm.get("learned_on"):
            result.already_by_age += 1
            continue
        if f"entities/{path.name}" in dirty:
            result.dirty += 1
            continue

        new_fm = dict(fm)
        body = parsed.body
        lowered = False
        if status not in ("archived", "dropped"):
            result.eligible += 1
            kind = decay_policy.entity_type(fm)
            bucket = _age_bucket(said, today)
            for tally in (result.by_type.setdefault(kind, _bucket()), result.by_age[bucket]):
                tally["pages"] += 1
            if path.name in added:
                result.learned_from_git += 1
                learned = max(said, added[path.name])
            else:
                result.learned_without_git += 1
                learned = max([d for d in (said, _day(fm.get("decayed_through"))) if d is not None])
            learned = min(learned, today)
            confidence = float(fm.get("confidence", 0.5) or 0.0)
            heard_in = decay_policy.conversations(fm.get("source_episodes"), untimed=untimed)
            unfloored = max(0.0, confidence - effective.rate * (learned - said).days / 7.0)
            new_conf = decay_policy.charge(
                confidence, effective.rate, decay_policy.Silence((learned - said).days, 0, learned),
                nudge_threshold=NUDGE_THRESHOLD, conversations=heard_in)
            if new_conf < confidence:
                lowered = True
                new_fm["confidence"] = new_conf
                new_fm["learned_on"] = learned.isoformat()
                watermark = max([d for d in (_day(fm.get("decayed_through")), learned) if d is not None])
                new_fm["decayed_through"] = watermark.isoformat()
                result.lowered += 1
                for tally in (result.by_type[kind], result.by_age[bucket]):
                    tally["lowered"] += 1
                quiet = new_conf < NUDGE_THRESHOLD and decay_policy.heard_late(said, learned)
                if quiet:
                    # Its own age took it below the question line: Sleep fades and archives it quietly.
                    new_fm[decay_policy.FADED_BY_AGE_KEY] = learned.isoformat()
                if new_conf < ARCHIVE_THRESHOLD:
                    new_fm["status"] = "archived"
                    result.would_archive += 1
                    for tally in (result.by_type[kind], result.by_age[bucket]):
                        tally["archive"] += 1
                elif new_conf < NUDGE_THRESHOLD:
                    new_fm["status"] = "decaying"
                    for tally in (result.by_type[kind], result.by_age[bucket]):
                        tally["decaying"] += 1
                    result.would_decay += 1
                    # Read within a week of being said: Sleep asks about it as live silence continues
                    # (at most `decay_inbox_cap_per_cycle` new questions a cycle). Never the recompute.
                    result.would_be_asked += not quiet
                    result.floored_repeats += unfloored < new_conf

        about = subject(path.stem)
        new_body = _recompute_claims(body, about, decay_policy.claim_multiplier(about.decay_class), untimed, result)
        if new_body != body and "learned_on" not in new_fm:
            # The page's claims were charged: mark it so a second run never charges them again.
            new_fm["learned_on"] = max(said, added.get(path.name, said)).isoformat()
        if lowered or new_body != body:
            result._todo[path] = (text, new_fm, new_body)
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
                    f"Decay by age: {len(rels)} page(s)",
                    [f"{rel}: decay (trigger: {TRIGGER})" for rel in rels],
                    authors=["cicada"],
                )
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
    if written:
        logger.info(f"decay-by-age recompute: {len(written)} page(s)")
    return result
