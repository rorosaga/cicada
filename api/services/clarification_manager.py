"""Clarification queue — holds entities Cicada couldn't confidently extract.

A clarification is created when an entity is extracted with low confidence and
no existing match. The user (or a later, higher-confidence extraction) resolves
it. Three resolution paths exist:

1. **Organic** — a later sleep cycle extracts the same entity with confidence
   >= 0.6 and the pending clarification is auto-resolved.
2. **Agent-initiated** — Bookworm surfaces the clarification when the current
   query touches it, letting the agent ask in conversation flow.
3. **Manual** — the user answers via the companion app.

Clarifications are stored as markdown files under ``memory/clarifications/`` so
they show up in the existing FastAPI router and companion app without schema
changes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from loguru import logger
from thefuzz import fuzz

from api.services import markdown_parser

CONFIDENCE_THRESHOLD = 0.5
ORGANIC_RESOLUTION_THRESHOLD = 0.6


class ClarificationManager:
    def __init__(self, memory_path: Path):
        self.memory_path = Path(memory_path)
        self.dir = self.memory_path / "clarifications"
        self.dir.mkdir(parents=True, exist_ok=True)

    # ---------- Creation ----------

    def create(
        self,
        entity_name: str,
        source_episode: str,
        uncertainty_type: str,
        suggested_classification: str,
        suggested_confidence: float,
        source_context: str,
        source_episode_timestamp: str | None = None,
    ) -> str | None:
        """Create a clarification file. Returns its id, or None if duplicate.

        ``source_episode_timestamp`` is the ISO timestamp of the conversation
        that originally triggered the clarification. Persisting it lets the
        resolution paths (answer, merge) stamp entities with the real source
        conversation date instead of today's date — keeping chronology
        consistent with the resolver/conflict pipeline, which uses the source
        episode timestamps to set ``created`` and ``last_referenced``.
        """
        if self._existing_for(entity_name):
            return None

        clar_id = self._next_id()
        frontmatter: dict = {
            "entity_mention": entity_name,
            "uncertainty_type": uncertainty_type,
            "suggested_classification": suggested_classification,
            "suggested_confidence": round(float(suggested_confidence), 2),
            "created_date": str(date.today()),
            "source_episode": source_episode,
        }
        if source_episode_timestamp:
            frontmatter["source_episode_timestamp"] = str(source_episode_timestamp)
        filepath = self.dir / f"{clar_id}.md"
        markdown_parser.write(filepath, frontmatter, source_context.strip())
        logger.info(f"Clarification created: {clar_id} ({entity_name})")
        return clar_id

    # ---------- Organic resolution ----------

    def check_organic_resolution(self, entity_name: str, confidence: float) -> bool:
        """Remove a pending clarification for ``entity_name`` if confidence is high enough."""
        if confidence < ORGANIC_RESOLUTION_THRESHOLD:
            return False
        existing = self._existing_for(entity_name)
        if not existing:
            return False
        try:
            existing.unlink()
            logger.info(
                f"Clarification resolved organically: {existing.stem} ({entity_name})"
            )
            return True
        except OSError as e:
            logger.debug(f"Failed to remove clarification {existing}: {e}")
            return False

    # ---------- Internals ----------

    def _existing_for(self, entity_name: str) -> Path | None:
        target = entity_name.strip().lower()
        for filepath in self.dir.glob("*.md"):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception:
                continue
            mention = str(parsed.frontmatter.get("entity_mention", "")).strip().lower()
            if _same_mention(mention, target):
                return filepath
        return None

    def _next_id(self) -> str:
        existing = sorted(self.dir.glob("clar-*.md"))
        max_num = 0
        for filepath in existing:
            stem = filepath.stem  # clar-001
            try:
                max_num = max(max_num, int(stem.split("-")[-1]))
            except ValueError:
                continue
        return f"clar-{max_num + 1:03d}"


def _same_mention(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    if fuzz.ratio(left, right) > 85:
        return True
    left_tokens = _mention_tokens(left)
    right_tokens = _mention_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    return left_tokens <= right_tokens or right_tokens <= left_tokens


def _mention_tokens(text: str) -> set[str]:
    import re

    stopwords = {"the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "at", "de", "del", "la", "el"}
    tokens = re.findall(r"[\w'-]+", text.lower())
    return {token for token in tokens if token not in stopwords and len(token) >= 2}
