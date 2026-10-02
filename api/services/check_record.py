"""What an agent found when it looked at a source for an inbox question (G61 S3, the ``page_read`` sibling).

Cicada never opens the page and never holds a session. A person's own agent looks at a source — a profile page, a team
page, a company site — in the person's signed-in session, and brings back what it saw. This module records THAT and
nothing more, in SHADOW: **a finding settles nothing, holds nothing and reorders nothing** (S4–S8 wait). It writes:

* one **check episode** (``source: source-check``): ``assistant: <summary>``, then ``attachment [<host>]: as <harness>
  read it`` and one ``> <quote>`` line per quote. The ``attachment [..]:`` marker is what makes ``evidence._marker``
  answer ``page`` for the quotes — text an agent REPORTED from the page, never the person's words (D4: no seventh evidence
  kind; the episode's ``source`` labels it). ``processed: true`` / ``processed_by: agent`` (Sleep never re-reads it raw)
  and no ``evidence_kind`` (a declared ``assistant`` would relabel every span);
* one row in the item's ``checks:`` (newest per source, at most five): who looked, where, what they concluded — and the
  first quote, so the card can show it. A ``proposes`` value is stored there as ``proposed_value`` ONLY: it adds no
  option and writes no claim (a check-time claim would supersede the machine options through the reconciler).

It NEVER writes a claim, never resolves or defers the item and never touches an option. The finding is the agent's
word: the label everywhere is "as <harness> read it". Everything is scrubbed (R-N3) before it is hashed or written.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from api.services import bank_index, episode_ids, episode_scrub, markdown_parser, reading_hosts

SOURCE = "source-check"
MARKER = "attachment"
MAX_SUMMARY_CHARS = 500
MAX_QUOTES = 3
MAX_QUOTE_CHARS = 240
MAX_VALUE_CHARS = 120
MAX_CHECKS = 5
#: Outcomes that are a FINDING (written to the bank). The rest (`needs_login`, `blocked`, `not_found`, `failed`) only
#: pause the source in the machine-wide ask store and write nothing here.
FINDINGS = ("supports", "proposes", "unclear", "contradicts_all")
NOT_FINDINGS = ("needs_login", "blocked", "not_found", "failed")
OUTCOMES = FINDINGS + NOT_FINDINGS
NEEDS_QUOTES = ("supports", "proposes", "contradicts_all")


def _one_line(text) -> str:
    """Folded to one line: a summary or quote with a newline could open a line that reads as a turn marker."""
    return " ".join(str(text or "").split())


def clean_quotes(raw) -> tuple[list[str], int]:
    """At most three quotes of at most 240 characters, scrubbed, one line each; and how many were left out."""
    kept: list[str] = []
    dropped = scrubbed = 0
    for item in raw if isinstance(raw, list) else []:
        quote = item.get("quote") if isinstance(item, dict) else (item if isinstance(item, str) else None)
        text = _one_line(quote).lstrip("> ").strip()[:MAX_QUOTE_CHARS].rstrip()
        if not text or len(kept) >= MAX_QUOTES:
            dropped += 1
            continue
        text, n = episode_scrub.scrub(text)
        scrubbed += n
        kept.append(text)
    episode_scrub.record("mcp", scrubbed)
    return kept, dropped


def record(
    memory_path: Path, *, item_id: str, item_title: str, entity_id: str, predicate: str, ref: str, outcome: str,
    option_key: str | None, proposed_value: str | None, summary: str, quotes: list[str], via: str | None,
    checker: str, checker_kind: str, session_frontmatter: dict | None = None, linked_entity: str | None = None,
) -> dict:
    """Write the check episode and append the item's ``checks:`` row. Returns ``{episode_id, paths}``. The caller has
    authorized the check (``reading_queue.authorizes_check``), validated the outcome and the option, and commits."""
    from api.services import reading_asks

    memory_path = Path(memory_path)
    host = reading_hosts.display_host(reading_hosts.host_of(ref)) or "page"
    summary, n1 = episode_scrub.scrub(_one_line(summary))
    summary = (summary or f"Looked at {host} for this question.")[:MAX_SUMMARY_CHARS].rstrip()
    value, n2 = episode_scrub.scrub(_one_line(proposed_value)[:MAX_VALUE_CHARS])
    episode_scrub.record("mcp", n1 + n2, bank=memory_path.name)
    label = checker if checker and checker != "agent" else "an agent"
    quote_lines = [f"> {q}" for q in quotes]
    head = f"{MARKER} [{host}]: as {label} read it"
    body = "\n".join([f"assistant: {summary}", *(["", head, *quote_lines] if quote_lines else [])])
    content_hash = hashlib.sha256(f"{item_id}\x00{ref}\x00{outcome}\x00{body}".encode("utf-8")).hexdigest()[:12]
    episode_id = next((f.stem for f in bank_index.files(memory_path, "episodes")
                       if f.frontmatter.get("content_hash") == content_hash and f.frontmatter.get("source") == SOURCE),
                      None)
    if episode_id is None:
        episodes_dir = memory_path / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)
        episode_id = episode_ids.next_episode_id(episodes_dir, datetime.now().strftime("%Y-%m-%d"))
        frontmatter = {
            "id": episode_id,
            "timestamp": episode_ids.utc_now_iso(),
            "source": SOURCE,
            "origin": "mcp",
            "title": f"Check: {item_title}"[:120],
            "processed": True,
            "processed_by": "agent",
            "content_hash": content_hash,
            "checked_ref": ref,
            "checked_host": host,
            "item_id": item_id,
            "entity_id": entity_id,
            "outcome": outcome,
            "checker_kind": checker_kind,
            **({"predicate": predicate} if predicate else {}),
            **({"option_key": option_key} if option_key else {}),
            # The source's own memory node, when it has one: the finding is provenance for both pages.
            **({"media_entity_id": linked_entity} if linked_entity else {}),
            **(session_frontmatter or {}),
        }
        markdown_parser.write(episodes_dir / f"{episode_id}.md", frontmatter, body)
    via_clean = reading_asks.clean_via(via)
    row = {"at": episode_ids.utc_now_iso(), "checker": checker or "agent", "checker_kind": checker_kind,
           "ref": ref, "host": host, "outcome": outcome, "episode": episode_id}
    if option_key:
        row["option_key"] = option_key
    if value:
        row["proposed_value"] = value
    if quotes:
        row["quote"] = quotes[0]
    if via_clean:
        row["via"] = via_clean
    item_rel = f"inbox/{item_id}.md"
    append_check(memory_path / item_rel, row)
    return {"episode_id": episode_id, "paths": [f"episodes/{episode_id}.md", item_rel]}


def append_check(path: Path, row: dict) -> None:
    """Add one row to an inbox item's ``checks:`` — newest per source (a later look at the same source replaces the
    earlier one), at most :data:`MAX_CHECKS`. Every other key of the file is kept as it is."""
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    rows = [r for r in (fm.get("checks") or []) if isinstance(r, dict) and r.get("ref") != row.get("ref")]
    # Newest row per source; past the cap the OLDEST BY TIME goes. (A source evicted this way has no row, so it can be
    # listed again sooner than a week — the cap trades that for a bounded item file.)
    fm["checks"] = sorted(rows + [row], key=lambda r: str(r.get("at") or ""))[-MAX_CHECKS:]
    markdown_parser.write(path, fm, parsed.body)
