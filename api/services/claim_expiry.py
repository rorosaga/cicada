"""Facts with a stated end stop being current at that end (G140 Q-R6/Q-R7, R3 P8).

Supermemory expires temporary facts; Instinct keeps "exams this weekend"
until a model decides to remove it; Cicada's volatile class (G66) fades it
over weeks. A fact that STATES its end should close at that end. Two stated
ends exist, both explicit — nothing here reads prose, and no LLM runs:

* ``Claim.expected_end`` — written by an agent through ``cicada_write_claim``;
* a G17 ``due`` claim's own ISO-date object.

``expire`` closes every open claim whose end is strictly before today (an end
is inclusive — "until Friday" is current on Friday): ``valid_to`` = the end,
never earlier than ``valid_from``; no ``superseded_by``, because nothing
replaced it; nothing deleted. A person's own claim closes too — the end is
their own statement, so this is not an agent closing a human claim (Q-R7).

Sleep's engine-free tail calls it on every exit path, idle nights included
(an end is a date, not an episode), in the guarded branch, and commits the
result alone as ``cicada`` (the G85 shape). The subject is ``Expiry <date>``,
never ``Sleep cycle …``: the Sleep page's history rows are consolidations.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import git_service, markdown_parser
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims

TRIGGER = "sleep/expiry"
AUTHOR = "cicada"
# A page with neither string cannot hold a stated end: skip it without a
# parse (most of a bank, every night).
_NEEDLES = ("expected_end:", "predicate: due")


def stated_end(claim: Claim) -> str | None:
    """The claim's own end as ``YYYY-MM-DD``, or ``None``. A ``due`` object
    that is not a date ("next-friday") is not an end — derived here at
    expiry time, never stamped onto the claim (Q-R6)."""
    candidates = (claim.expected_end, claim.object if claim.predicate == "due" else None)
    for raw in candidates:
        if not raw:
            continue
        try:
            return date.fromisoformat(str(raw).strip()[:10]).isoformat()
        except ValueError:
            continue
    return None


@dataclass
class Report:
    paths: list[str] = field(default_factory=list)                 # memory-relative pages written
    claims: list[tuple[str, str]] = field(default_factory=list)    # (entity id, claim id) closed


def expire(memory_path: Path, today: date) -> Report:
    """Close every open claim whose stated end has passed. Never raises on a
    normal bank; a page whose claims block is unreadable is skipped, never
    rewritten (the strict-parse rule every read-modify-write path follows)."""
    report = Report()
    entities = Path(memory_path) / "entities"
    if not entities.is_dir():
        return report
    day = today.isoformat()
    for path in sorted(entities.glob("*.md")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not any(needle in raw for needle in _NEEDLES):
            continue
        try:
            parsed = markdown_parser.parse(path)
            claims = parse_claims(parsed.body, strict=True)
        except MalformedClaimsBlockError as exc:
            logger.warning(f"expiry skipped {path.name}: unreadable claims block ({type(exc).__name__})")
            continue
        except Exception as exc:  # noqa: BLE001 — one bad page never stops the night
            logger.warning(f"expiry skipped {path.name}: {type(exc).__name__}")
            continue
        closed: list[str] = []
        for claim in claims:
            if claim.valid_to is not None or claim.superseded_by:
                continue
            end = stated_end(claim)
            if end is None or end >= day:
                continue
            # Never a window that closes before it opens. `valid_from` is only
            # trusted when it IS a date: a hand-edited "undated" would win a
            # string `max` and land in `valid_to`.
            try:
                began = date.fromisoformat(str(claim.valid_from or "")[:10]).isoformat()
            except ValueError:
                began = end
            claim.valid_to = max(end, began)
            closed.append(claim.id)
        if not closed:
            continue
        markdown_parser.write(path, parsed.frontmatter, write_claims(parsed.body, claims))
        report.paths.append(f"entities/{path.name}")
        report.claims.extend((path.stem, cid) for cid in closed)
    return report


def commit_message(report: Report, today: date) -> str:
    """``Expiry <date>``, one ``expired`` line per page, ``Cicada-Author:
    cicada`` and no engine trailer — no LLM ran (Q-R7, the G85 shape)."""
    return git_service.build_commit_message(
        f"Expiry {today.isoformat()}",
        [f"{p}: expired (source: n/a, trigger: {TRIGGER})" for p in report.paths],
        authors=[AUTHOR],
    )


def restore(memory_path: Path, paths: list[str]) -> None:
    """Put pages back as HEAD has them after a failed expiry commit (Q-R7).
    The expiry is re-derived tomorrow; a page left dirty would be stamped by
    the next ``git add -A`` writer under the wrong author — the G85 smear."""
    if not paths or not (Path(memory_path) / ".git").exists():
        return
    try:
        subprocess.run(["git", "checkout", "--", *paths], cwd=str(memory_path),
                       capture_output=True, timeout=10, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning(f"expiry restore failed: {type(exc).__name__}")
