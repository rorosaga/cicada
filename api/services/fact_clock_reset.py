"""The one-time reset of facts' clocks by real age (ROR-129, owner 2026-11-06; ``api/scripts/reset_fact_clocks.py``).

A fact has its own relevance apart from its page. Until now an evergreen page (the owner's, a pinned one) skipped the claim
decay pass whole, so its facts were never charged the silence their conversations prove, and their clocks sit at the day
Cicada read them, however old they are. Now they fade by their own class (`decay_policy.fact_multiplier`: an evergreen page
that is not media lends ``active``), and without this reset a 2022 balance would fade from the day it was read.

For one open, non-event fact on an evergreen, non-media page: the silence its conversations prove runs from its latest
dated conversation (``claim_reconciler._said``) to ``recorded_at``, the day Cicada read it, charged at the fact's own pace
(``age_recompute._recompute_claims``, the same charge the 2026-10-09 recompute made for everything else) — confidence
lowered, ``faded_by_age`` set when that takes it under the question line (so it never asks), the watermark no earlier than
the read day. One-offs fall, repeats floor at 0.39. A fact with no dated conversation (a memory export entry) has no age to
count and is left alone; the dry run counts them.

**Dry run by default, never applied by Sleep or any request.** ``apply`` is one ``cicada`` commit (trigger
``maintenance/fact-clocks``), refused while Sleep runs or holds the pages; a page carries ``fact_clocks_reset: <day>`` after
it, so a second run changes nothing. Counts only — never a page name or a word of the bank.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import (
    age_recompute, claims, claims_ledger, decay_policy, decay_tuning, episode_time, git_service, markdown_parser, page_lock,
    write_admission,
)

TRIGGER = "maintenance/fact-clocks"
MARK = "fact_clocks_reset"
SleepRunning = age_recompute.SleepRunning


def survey(memory_path, *, today: date | None = None, settings=None) -> age_recompute.Survey:
    """What :func:`apply` would change. Read-only."""
    memory_path = Path(memory_path)
    today = today or date.today()
    result = age_recompute.Survey()
    untimed = episode_time.untimed_ids(memory_path)
    subject = decay_policy.subject_lookup(memory_path, tuning=decay_tuning.load(memory_path))
    dirty: frozenset[str] = frozenset()
    if (memory_path / ".git").exists():
        try:
            dirty = git_service.dirty_paths_sync(memory_path, "entities")
        except git_service.GitError:
            dirty = frozenset()
    for path in sorted((memory_path / "entities").glob("*.md")):
        result.pages += 1
        try:
            text = path.read_text(encoding="utf-8")
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 — a malformed page is skipped, never fatal
            continue
        fm = dict(parsed.frontmatter or {})
        about = subject(path.stem)
        page_class = decay_policy.resolve(fm)[0]
        if page_class is not decay_policy.DecayClass.evergreen or about.entity_type == "media":
            continue   # every other page was charged by the claim pass all along
        result.eligible += 1
        if fm.get(MARK):
            result.already_by_age += 1
            continue
        if f"entities/{path.name}" in dirty:
            result.dirty += 1
            continue
        body = age_recompute._recompute_claims(
            parsed.body, about, 0.0, untimed, result,
            per_claim=lambda c, _a=about, _p=page_class: decay_policy.fact_multiplier(c.decay_class, c.class_by, _p, _a.entity_type))
        if body != parsed.body:
            fm[MARK] = today.isoformat()
            result.lowered += 1
            result._todo[path] = (text, fm, body)
    return result


def apply(memory_path, *, sleep_running: Callable[[], bool], today: date | None = None, settings=None) -> age_recompute.Survey:
    """Write the survey's changes and commit them in ONE commit authored ``cicada``. Raises :class:`SleepRunning`
    before writing anything when Sleep holds the pages or a run is in progress."""
    memory_path = Path(memory_path)
    written: list[Path] = []
    with write_admission.admitted(memory_path, refuse=lambda: SleepRunning("Sleep is holding this bank's pages")):
        if sleep_running():
            raise SleepRunning("a Sleep run is in progress; reset after it ends")
        with page_lock.page_lock(memory_path):
            result = survey(memory_path, today=today, settings=settings)
            for path, (surveyed, fm, body) in result._todo.items():
                if path.read_text(encoding="utf-8") != surveyed:   # written since the survey: its writer's to commit
                    result.dirty += 1
                    continue
                markdown_parser.write(path, fm, body)
                written.append(path)
            rels = claims_ledger.with_ledgers(memory_path, [f"entities/{p.name}" for p in written], existing_only=True)
            result.written = len(written)
            if rels and (memory_path / ".git").exists():
                message = git_service.build_commit_message(
                    f"Fact clocks by real age: {len(written)} page(s)",
                    [f"{rel}: decay (trigger: {TRIGGER})" for rel in rels], authors=["cicada"])
                git_service.commit_paths_sync(memory_path, message, rels)
                result.committed = True
    if written:
        logger.info(f"fact-clock reset: {len(written)} page(s)")
    return result
