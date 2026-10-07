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


#: G166: the header of a note that only says links are waiting for an agent to
#: read. Same prefix as every other note, so capture counts it when it arrives
#: inside the person's own text (``note_like_turns``, G110 T2b).
READING_HEADER = INJECTION_PREFIX + " by Cicada's hook, not typed by them) — a reading request:"


def reading_line(waiting: int, *, record: bool = True) -> str:
    """One sentence, per request and never stored: how many links are waiting in
    Cicada's reading queue for an agent to read — ones the person asked about, and
    pages from sites they allowed. A statement, not a command (see the module's
    note on hook wording). ``record`` false leaves out ``cicada_record_read`` for a
    remote connection that does not hold it (R12)."""
    noun = "link" if waiting == 1 else "links"
    tail = (" and `cicada_record_read(url, outcome, summary)` records what was read" if record else "")
    return (f"{waiting} {noun} {'is' if waiting == 1 else 'are'} waiting in Cicada's reading queue for an agent "
            "to read (ones the person asked about, and pages from sites they allowed). Once their own request is "
            f"done (or if it is about those links), `cicada_reading_queue(limit)` lists what is waiting{tail}.")


#: G110: what the SessionStart note says when even the primer cannot fit — a
#: pointer to the tool that serves it whole. R12: the tool takes no argument.
PRIMER_FALLBACK = "Cicada's primer did not fit here; `cicada_handshake` returns it."


def compose_note(header: str, primer: str, *, block_for=None, reading: str | None = None,
                 max_tokens: int) -> tuple[str, str, bool]:
    """The whole SessionStart ``additionalContext`` (G110 slice 1a, plan C4),
    measured as the FINAL string by the chars/4 proxy (handshake R10).

    Parts, in order: ``header``, ``primer``, the continuity block, the reading
    sentence, joined by blank lines. ``block_for(max_chars)`` returns a light
    history pointer that fits (``(text, rendering)``; ``("", "none")`` when
    none does). Preserve that pointer: defer the reading sentence first,
    then replace an oversized primer with :data:`PRIMER_FALLBACK`. Spare
    room never expands the pointer into unsolicited history.

    Returns ``(text, rendering, reading_kept)``."""
    limit = max_tokens * 4 + 3          # len // 4 <= max_tokens

    def join(*parts):
        return "\n\n".join(p for p in parts if p)

    for fitted_primer, fitted_reading in ((primer, reading), (primer, None), (PRIMER_FALLBACK, None)):
        base = join(header, fitted_primer)
        room = limit - len(join(base, fitted_reading)) - 2
        text, rendering = ("", "none")
        if block_for is not None and room > 0:
            text, rendering = block_for(room)
        note = join(base, text, fitted_reading)
        if len(note) <= limit and (block_for is None or text):
            return note, rendering if text else "none", bool(fitted_reading)
    return join(header, PRIMER_FALLBACK), "none", False
