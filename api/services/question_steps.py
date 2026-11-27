"""Does the tail's question steps have anything to read? (2026-11-27, `sleep_spend.QUESTIONS_SHARE`; G104 family)

A run on a key keeps a part of its spending limit for the question steps, which run in the tail after reading stops: the
same-name review, the full-name and typo joins, the second look at open questions (ruling 82), the described landing (G148)
and the which-one reader (ruling 83). The part is kept only while they have something to read, and the answer is asked at the
moment reading reaches its own line (questions raised during the run count), by each step's own engine-free filter:
`True` means "may have", never "will settle" (each step's guards still decide, and a step with nothing sends nothing).

Engine-free and read-only: no model, no network, no write. A filter that raises counts as no work, so a broken one never
starves reading of the figure.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from loguru import logger


def has_work(memory_path: Path, *, today: date | None = None) -> bool:
    """True when at least one question step's own candidate filter finds something."""
    from api.services import described_landing, full_name_join, question_revisit, same_name_doubts, typo_join, which_one_reader

    memory_path = Path(memory_path)
    day = (today or date.today()).isoformat()

    def flagged() -> bool:
        pages, pairs = same_name_doubts.flagged(memory_path)
        return bool(pages or pairs)

    def which_one() -> bool:
        return any(not isinstance(which_one_reader.case_for(memory_path, p, fm, today=day), str)
                   for p, fm in which_one_reader.eligible(memory_path, day)[:which_one_reader.MAX_LOOKS])

    for name, found in (
        ("same-name review", flagged),
        ("full-name join", lambda: bool(full_name_join.candidates(memory_path))),
        ("typo join", lambda: bool(typo_join.all_candidates(memory_path))),
        ("question revisit", lambda: bool(question_revisit.candidates(memory_path, today=today))),
        ("described landing", lambda: bool(described_landing.plan_bank(memory_path).groups)),
        ("which-one reader", which_one),
    ):
        try:
            if found():
                return True
        except Exception as exc:  # noqa: BLE001 - a filter that cannot answer is no work, never a reason to hold back reading
            logger.debug(f"question steps: {name} filter unreadable ({type(exc).__name__})")
    return False
