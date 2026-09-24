"""The words Cicada's recall hook puts in front of a model (G149).

Three places must agree on them, so they live in one small module with no
service imports: the composer (``hook_recall``), the contract item that tells
an agent what they are (``handshake._CONTRACT`` item 8), and the capture filter
that keeps them out of an episode (``transcript_extract``). A note Cicada
recalled, captured back as "the person said", would hand Sleep its own memory
as new evidence (R-H12).

Written as statements, never commands. Claude Code's hook reference (read
2026-09-24, "Add context for Claude") warns that text framed as out-of-band
system instructions can trip the model's prompt-injection defences, so each
header says where the note came from and what it is.
"""
from __future__ import annotations

#: Every note opens with this; ``is_injection`` and the contract key on it.
INJECTION_PREFIX = "From Cicada (the person's memory; added"
RECALL_HEADER = INJECTION_PREFIX + " by Cicada's hook, not typed by them) — what it holds about names in this message:"
PRIMER_HEADER = (INJECTION_PREFIX + " at session start by Cicada's hook) — the primer its MCP server also sends "
                 "when it connects.")
RECALL_FOOTER = "More on any page: `cicada_recall_detail(entity_id)`."


def is_injection(text: str | None) -> bool:
    """True when ``text`` is one of Cicada's own notes (either header)."""
    return (text or "").lstrip().startswith(INJECTION_PREFIX)


def question_line(name: str, item_id: str, entity_id: str, question: str) -> str:
    """The one inbox pointer a note may carry (R-H5): the question's words when
    the item stores them, never its options or its cause. Those stay behind
    ``cicada_check_nudges``, which also knows whether the agent skipped it."""
    what = f": {question}" if question else " (a follow-up)"
    return (f"Open question for the person about {name} (`{item_id}`){what} — it can wait until their request "
            f"is done; `cicada_check_nudges(entity_ids=[\"{entity_id}\"])` shows the choices.")
