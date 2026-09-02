"""The per-bank, one-shot migrations — run for whichever bank becomes active.

Every migration here is marker-guarded, idempotent and never raises, so running
the set again is free. That is what makes it safe to run them from BOTH entry
points into a bank:

- API startup (``main.lifespan``) for the boot-time active bank, and
- ``POST /banks/{name}/activate``, for a bank the user switches to at runtime.

Before this module the set ran only at boot, so switching banks left the new
bank unmigrated — unclassed pages that the Feed and the decay engines then
disagreed about — until the next restart.

Adding a migration: it must be marker-guarded (a dotfile in the bank), never
raise, and be cheap enough to re-run on every bank switch (a marker check is a
single ``stat``).
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from api.services.decay_migration import backfill_decay_classes
from api.services.decay_watermark_migration import backfill_decay_watermarks
from api.services.inbox_migration import dedup_open_items, migrate_to_inbox


def run_bank_migrations(memory_path) -> dict:
    """Run every one-shot migration for one bank. Returns what each one did.

    ``{"moved": int, "deduped": int, "classed": {"media": int, "skills": int,
    "restored": int}, "watermarked": {"entities": int, "claims": int}}``.
    Logs only when something actually changed, so a no-op re-run on every
    bank switch is silent.
    """
    memory_path = Path(memory_path)

    # One-time migration of legacy nudges/clarifications into inbox/.
    moved = migrate_to_inbox(memory_path)
    if moved:
        logger.info(f"Migrated {moved} legacy items into inbox/")

    # G60: one-time collapse of duplicate open questions written before dedup
    # existed.
    deduped = dedup_open_items(memory_path)
    if deduped:
        logger.info(f"Collapsed {deduped} duplicate open inbox item(s)")

    # G66: one-time backfill of `decay_class` for pages written before the
    # class vocabulary existed (media -> evergreen, skills -> durable),
    # authored `cicada`.
    classed = backfill_decay_classes(memory_path)
    if classed["media"] or classed["skills"]:
        logger.info(
            f"Backfilled decay classes: {classed['media']} media -> evergreen, "
            f"{classed['skills']} skills -> durable, "
            f"{classed['restored']} restored to active"
        )

    # G85 §2 / Wave-1 1.8: one-time watermark backfill so the first decay
    # cycle after an outage (Sleep not having run in a while) never charges
    # the whole gap as a cliff — see decay_watermark_migration for why.
    watermarked = backfill_decay_watermarks(memory_path)
    if watermarked["entities"] or watermarked["claims"]:
        logger.info(
            f"Backfilled decay watermarks: {watermarked['entities']} page(s), "
            f"{watermarked['claims']} open claim(s)"
        )

    return {
        "moved": moved,
        "deduped": deduped,
        "classed": classed,
        "watermarked": watermarked,
    }
