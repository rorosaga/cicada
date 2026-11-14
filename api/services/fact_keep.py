"""The person's "keep this fact" (ROR-129, owner 2026-11-06): one fact marked evergreen as their own word, or let go.

A fact has its own relevance apart from its page. A kept fact never fades and never asks; it does not hold its page up
(the page's status stays honest) and a retrieval never revives the page. Undoing a keep — on one the person made or on an
evergreen the extraction model proposed — lets the fact fade again by its page's class, and the model can no longer
propose it evergreen (``class_by: user`` outranks ``model``, `claim_reconciler._merge_fact_class`).

One writer: the page and its claims ledger as ONE page-lock section, committed alone under the person
(``Cicada-Author: user``), the caller holding the write window (`write_admission`).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from api.services import claims as claims_mod, git_service, markdown_parser, page_lock
from api.services.id_utils import resolve_entity_file

TRIGGER = "user/companion_app"
#: A kept fact stands at least here, so it never reads as faded the moment it is kept.
KEPT_CONFIDENCE = 0.6


class FactNotFound(LookupError):
    """No such page, or no such open fact on it."""


def set_keep(memory_path: Path, entity_id: str, claim_id: str, keep: bool, *, today: str | None = None) -> claims_mod.Claim:
    """Mark ``claim_id`` on ``entity_id`` kept (evergreen, the person's word) or let it fade again; commit alone."""
    memory_path = Path(memory_path)
    day = (today or date.today().isoformat())[:10]
    with page_lock.page_lock(memory_path):
        page = resolve_entity_file(memory_path, entity_id)
        if page is None or not page.is_file():
            raise FactNotFound(f"Entity {entity_id} not found")
        rel = f"entities/{page.name}"
        tracked = (memory_path / ".git").exists()
        before = None
        if tracked:
            before = {rel: page.read_bytes()} if rel in git_service.dirty_paths_sync(memory_path, rel) else {}
        parsed = markdown_parser.parse(page)
        found = claims_mod.parse_claims(parsed.body)
        target = next((c for c in found if c.id == claim_id and c.valid_to is None), None)
        if target is None:
            raise FactNotFound(f"No open fact {claim_id} on {entity_id}")
        if keep:
            target.decay_class, target.class_by = "evergreen", "user"
            target.confidence = max(target.confidence, KEPT_CONFIDENCE)
            target.faded_by_age = None
        else:
            # The person's word that it is not evergreen: back to its page's class, and a model may not argue.
            target.decay_class, target.class_by = None, "user"
        markdown_parser.write(page, parsed.frontmatter, claims_mod.write_claims(parsed.body, found))
        if tracked:
            verb = "kept" if keep else "let fade"
            message = git_service.build_commit_message(
                f"Fact {verb} {day}", [f"{rel}: updated (claim {claim_id} {verb}, trigger: {TRIGGER})"], authors=["user"])
            git_service.commit_touched_sync(memory_path, message, [rel], before=before)
    return target
