"""Clarification queue — holds entities Cicada couldn't confidently extract.

A clarification is created when an entity is extracted with low confidence and
no existing match. The user (or a later, higher-confidence extraction) resolves
it. Three resolution paths exist:

1. **Organic** — a later sleep cycle extracts the same entity with confidence
   >= 0.6 and the pending clarification is auto-resolved.
2. **Agent-initiated** — Bookworm surfaces the clarification when the current
   query touches it, letting the agent ask in conversation flow.
3. **Manual** — the user answers via the companion app.

Clarifications are stored as markdown files under the unified
``memory/inbox/`` directory (``inbox-NNN.md`` with ``kind: clarification`` or
``kind: merge_suggestion``) so they share one read path with decay/conflict
items and show up in the companion app's single Inbox view.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from loguru import logger
from thefuzz import fuzz

from api.services import markdown_parser
from api.services.id_utils import resolve_entity_file, sanitize_id

CONFIDENCE_THRESHOLD = 0.5
ORGANIC_RESOLUTION_THRESHOLD = 0.6

_CLARIFICATION_KINDS = ("clarification", "merge_suggestion")
_DUPLICATE_PREFIX = "possible duplicate"


class ClarificationManager:
    def __init__(self, memory_path: Path):
        self.memory_path = Path(memory_path)
        self.dir = self.memory_path / "inbox"
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
        heard_in: dict | None = None,
        same_title: list[str] | None = None,
        target_id: str | None = None,
    ) -> str | None:
        """Create a clarification file. Returns its id, or None if duplicate.

        ``same_title`` / ``target_id`` (G227): a mention titled exactly as one or more pages — the candidate's own id
        is the merge target (a name two pages share never resolves to one), and every page sharing the title is kept
        (``same_title``) so the question names each one (`inbox_wording`).

        ``source_episode_timestamp`` is the ISO timestamp of the conversation
        that originally triggered the clarification. Persisting it lets the
        resolution paths (answer, merge) stamp entities with the real source
        conversation date instead of today's date — keeping chronology
        consistent with the resolver/conflict pipeline, which uses the source
        episode timestamps to set ``created`` and ``last_referenced``.
        """
        from api.services.inbox_generator import find_open

        is_duplicate = (uncertainty_type or "").strip().lower().startswith(
            _DUPLICATE_PREFIX
        )
        kind = "merge_suggestion" if is_duplicate else "clarification"
        # §2.2 dedup key: (entity_id, uncertainty_type) for a clarification,
        # the sorted entity pair for a merge suggestion. A collision is a
        # RE-ASK of the same question — bump `updated_date` and write nothing.
        second = (
            (target_id or self._merge_target_hint(uncertainty_type) or "")
            if is_duplicate
            else (uncertainty_type or "")
        )
        # G113 slice 3b (R5) — a pair the user already rejected ("these are NOT
        # the same entity") is never re-proposed. Checked only for a duplicate
        # suggestion: a plain clarification's `second` is the uncertainty type,
        # not an entity, so it is never a pair `merge_rejections` would hold.
        if is_duplicate and second:
            from api.services import merge_rejections

            if merge_rejections.is_rejected(self.memory_path, sanitize_id(entity_name), second):
                logger.info(
                    "clarification: merge pair (%s, %s) was rejected by the user — not re-proposing",
                    entity_name, second,
                )
                return None
            from api.services import pending_store

            key = (entity_name or "").strip().lower()
            if any(line.name.lower() == key and second in line.apart_pages()
                   for line in pending_store.load(self.memory_path)):
                # G227: the person already said the mention held under this name is another one — never asked again.
                return None
        open_path = find_open(self.memory_path, kind, sanitize_id(entity_name), second)
        if open_path is None and is_duplicate and same_title and len(same_title) >= 2:
            # G227 (owner 2026-10-29): one question per mention, never one per pair — a mention already asked about
            # through another of the pages that share its name is the same question.
            open_path = next((p for p in (find_open(self.memory_path, kind, sanitize_id(entity_name), str(pid))
                                          for pid in same_title if str(pid) != second) if p is not None), None)
        if open_path is not None:
            parsed = markdown_parser.parse(open_path)
            parsed.frontmatter["updated_date"] = str(date.today())
            markdown_parser.write(open_path, parsed.frontmatter, parsed.body)
            return None

        clar_id = self._next_id()
        confidence = round(float(suggested_confidence), 2)
        required_input = "merge" if is_duplicate else "freetext"
        frontmatter: dict = {
            "kind": kind,
            "required_input": required_input,
            "status": "pending",
            "priority": confidence,
            "entity_id": sanitize_id(entity_name),
            "entity_name": entity_name,
            # G97: for every non-conflict kind the card renders `entity_name`
            # on line 1 and `title` on line 2 (`InboxCardView.swift:64,69`) —
            # an identical string twice ("<name> / <name>") was the duplicated
            # subtitle. The title is now the question (G115 §1). The merge form
            # names the CANDIDATE as the person wrote it, never
            # `_merge_target_hint`'s slug — that helper returns a file stem
            # (`bob-example`), which is a page id, not copy.
            "title": (
                f"Is {entity_name} the same as {self._duplicate_candidate(uncertainty_type) or 'an existing entity'}?"
                if is_duplicate else f"Who or what is {entity_name}?"
            ),
            "uncertainty_type": uncertainty_type,
            "suggested_classification": suggested_classification,
            "suggested_confidence": confidence,
            "created_date": str(date.today()),
            "source_episode": source_episode,
        }
        # For a possible-duplicate suggestion, pre-fill the merge target slug so
        # the companion app can offer a one-tap merge. The candidate is carried
        # as a display name in ``uncertainty_type`` ("Possible duplicate of X").
        if is_duplicate:
            target_hint = target_id or self._merge_target_hint(uncertainty_type)
            if target_hint:
                frontmatter["merge_target_hint"] = target_hint
            if same_title:
                frontmatter["same_title"] = [str(i) for i in same_title][:6]
                if len(frontmatter["same_title"]) >= 2:
                    # G227 (owner 2026-10-29, pick the page): one question for the mention, answered by picking one
                    # of the pages (`same_name_pick` serves them as options at read) or "none of these".
                    frontmatter["title"] = f"Which {entity_name} is this?"
                elif target_id:
                    # G227: the stored title names the one page its answers act on, by its qualifier — every reader
                    # without the wording layer (an old client, a plain listing) asks the same yes/no question.
                    from api.services import same_name

                    frontmatter["title"] = f"Is this {same_name.label(self.memory_path, target_id, entity_name)}?"
        if source_episode_timestamp:
            frontmatter["source_episode_timestamp"] = str(source_episode_timestamp)
        if is_duplicate and isinstance(heard_in, dict) and heard_in.get("mention") and heard_in.get("page"):
            # Where each side was heard (`entity_resolver._held_alias_questions`): words for the question, never ids.
            frontmatter["heard_in"] = {"mention": str(heard_in["mention"])[:40], "page": str(heard_in["page"])[:40]}
        filepath = self.dir / f"{clar_id}.md"
        markdown_parser.write(filepath, frontmatter, source_context.strip())
        logger.info(f"Clarification created: {clar_id} ({entity_name})")
        return clar_id

    def _duplicate_candidate(self, uncertainty_type: str) -> str | None:
        """The candidate name in "Possible duplicate of X", verbatim.

        The twin of :meth:`_merge_target_hint`, which resolves the same text to
        a page SLUG for `merge_target_hint`. G115 Phase 1 needs the display form
        for the item title — a slug in a question reads as a bug to the person
        answering it.
        """
        text = (uncertainty_type or "").strip()
        if not text.lower().startswith(_DUPLICATE_PREFIX):
            return None
        candidate = text[len(_DUPLICATE_PREFIX):].strip()
        if candidate.lower().startswith("of "):
            candidate = candidate[3:].strip()
        return candidate or None

    def _merge_target_hint(self, uncertainty_type: str) -> str | None:
        """Resolve the candidate name in 'Possible duplicate of X' to a slug."""
        text = (uncertainty_type or "").strip()
        lowered = text.lower()
        if not lowered.startswith(_DUPLICATE_PREFIX):
            return None
        candidate = text[len(_DUPLICATE_PREFIX):].strip()
        if candidate.lower().startswith("of "):
            candidate = candidate[3:].strip()
        if not candidate:
            return None
        target_path = resolve_entity_file(self.memory_path, candidate)
        if target_path is not None:
            return target_path.stem
        return sanitize_id(candidate)

    # ---------- Organic resolution ----------

    def check_organic_resolution(self, entity_name: str, confidence: float, merged_into: str | None = None) -> bool:
        """Remove a pending clarification for ``entity_name`` if confidence is high enough.

        ``merged_into``: the page Stage 2 just matched the name to. A "Possible duplicate" question is answered by that
        only when it is the page the question proposed (G209): a name that matched its own page leaves the question
        "is it the same as that other page?" open, as it was."""
        if confidence < ORGANIC_RESOLUTION_THRESHOLD:
            return False
        existing = self._existing_for(entity_name)
        if not existing:
            return False
        if merged_into is not None:
            try:
                fm = markdown_parser.parse(existing).frontmatter
            except Exception:
                fm = {}
            if fm.get("kind") == "merge_suggestion" and str(fm.get("merge_target_hint") or "") != merged_into:
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
        for filepath in self.dir.glob("inbox-*.md"):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception:
                continue
            # Only clarification/merge_suggestion items are dedup candidates; a
            # decay item about the same entity is not a duplicate clarification.
            if parsed.frontmatter.get("kind") not in _CLARIFICATION_KINDS:
                continue
            mention = str(
                parsed.frontmatter.get("entity_name", "")
                or parsed.frontmatter.get("entity_mention", "")
            ).strip().lower()
            if _same_mention(mention, target):
                return filepath
        return None

    def _next_id(self) -> str:
        max_num = 0
        # A settled question (``inbox/settled/``) keeps its number for its undo.
        for filepath in [*self.dir.glob("inbox-*.md"), *(self.dir / "settled").glob("inbox-*.md")]:
            try:
                max_num = max(max_num, int(filepath.stem.split("-")[-1]))
            except ValueError:
                continue
        return f"inbox-{max_num + 1:03d}"


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
