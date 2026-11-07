"""A page's history as the History tab draws it (ruling 48 part 14, DR-77; vision item 5 part B, 2026-10-29).

The owner, 2026-10-28: "take a little inspiration from GitKraken-like graphs: a line traced through time showing how
the page changed; hover gives the details (who, what changed, when)". Every row of :func:`page` is one commit that
touched ``entities/<id>.md``, newest first, with:

* ``bucket`` — the filter tab it sits under (You · Agents · Sleep · Upkeep), from ONE rule (:func:`bucket`) over the
  page's own manifest trigger, the door it names (``git_service.history_via``) and the author's kind. Upkeep is decay,
  housekeeping and Cicada's own maintenance: Wikipedia's bot flag (research #10), left out of All.
* ``at`` — the commit's time (ISO 8601), so a row and its hover say when to the minute.
* ``summary`` — what changed, counted from the commit's own patch for this file: beliefs added, ended and dropped,
  the frontmatter keys touched, prose lines added and removed, and up to :data:`MAX_LINES` short changed prose lines
  for the row and the hover.

Speed (the card open is a hot path): none of this runs when a card opens. ``GET /entities/{id}`` no longer reads
git; the History tab asks ``GET /entities/{id}/history?limit=30&summary=true`` when it opens, which is ONE ``git log
-p --unified=0`` bounded by ``limit`` — never ``git blame`` (blame stays lazy: the article's citation popovers say who
wrote each sentence, ruling 48 (16)), never one ``git show`` per row.
"""
from __future__ import annotations

import re
from pathlib import Path

from api.models.schemas import EntityHistoryEntry, HistorySummary, HistorySummaryLine
from api.services import git_service, page_join

#: The filter tabs, in the order the app draws them after All.
BUCKETS = ("you", "agents", "sleep", "upkeep")
#: The rows one History request reads by default — a screenful; "Older changes" asks for the next.
DEFAULT_LIMIT = 30
MAX_LIMIT = 200
#: Changed prose lines kept per row (DR-77: "showing up to four of its changes").
MAX_LINES = 4
MAX_LINE_CHARS = 140
MAX_FIELDS = 6
#: Upkeep triggers that are not Sleep's reading of a conversation: the decay pass (G85), the state snapshot, logos,
#: link and source housekeeping. A trigger under one of these prefixes is upkeep whoever authored it.
_UPKEEP_PREFIXES = ("sleep/decay", "sleep/expiry", "sleep/state", "sleep/logo", "sleep/link-sources",
                    "sleep/where-to-check", "sleep/reindex", "sleep/repair", "migration/", "repair/")

_FORMAT = "--format=%x1e%H%x1f%ad%x1f%aI%x1f%s%x1f%b%x1d"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
_CLAIM_ID = re.compile(r'^\{"id":\s*"([^"]+)"')
_ENDED = re.compile(r'"(?:superseded_by|valid_to)":\s*"[^"]|"retracted":\s*true|"status":\s*"(?:ended|done|cancelled|retracted)"')
_FIELD = re.compile(r"^([a-z_][a-z0-9_]*):(?:\s|$)")
_MD_NOISE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]|[*`>#]+|\b_|_\b")
_LIST_VALUE = re.compile(r"^- \S+$")
_UNDOES = re.compile(r"^Undoes: ([0-9a-f]{40})$", re.MULTILINE)


def bucket(trigger: str | None, via: str | None, author: str | None, author_kind: str | None) -> str:
    """Which of :data:`BUCKETS` a change belongs to. Sleep's decay and housekeeping are upkeep, not Sleep's reading;
    the person in the app or answering a question is You; a local agent or a connected app is Agents; Cicada's own
    maintenance (``cicada``, a poll, a migration) is upkeep. A commit with no manifest line falls back on its author:
    ``user`` is You, a harness is Agents, a model is Sleep (a pre-manifest Sleep commit), anything else upkeep."""
    t = str(trigger or "").strip().lower()
    v = str(via or "unknown")
    kind = str(author_kind or "unknown")
    if t.startswith(_UPKEEP_PREFIXES) or kind == "system":
        return "upkeep"
    if v == "sleep":
        return "sleep"
    if v in ("app", "inbox"):
        return "you"
    if v in ("agent", "remote"):
        return "agents"
    if v in ("sync", "cicada"):
        return "upkeep"
    if str(author or "") == git_service.USER_AUTHOR:
        return "you"
    if kind == "harness":
        return "agents"
    if kind == "model":
        return "sleep"
    return "upkeep"


def _plain(text: str) -> str:
    """A changed prose line as words: wikilinks as their label, markdown marks dropped, clipped."""
    out = _MD_NOISE.sub(lambda m: (m.group(2) or m.group(1) or "") if m.group(0).startswith("[[") else "", text)
    out = " ".join(out.split()).lstrip("-• ").strip()
    return out if len(out) <= MAX_LINE_CHARS else out[: MAX_LINE_CHARS - 1].rstrip() + "…"


def _ended(line: str) -> bool:
    """Whether a claim line closes its claim — superseded, given an end, retracted. A pattern over the JSON line, not a
    parse: an owner-sized page's Sleep commit rewrites thousands of claim lines."""
    return _ENDED.search(line) is not None


def summarize(patch: str) -> HistorySummary:
    """What one commit changed in one page, from its ``--unified=0`` patch. A claim line is one of the fence's JSON
    lines (``{"id": "clm_…"``): an id only added is a new belief, only removed a dropped one, on both sides a changed
    one — and ended when the new side closes it (superseded, a ``valid_to``, retracted). A ``key: value`` line or an
    indented list item is frontmatter. Everything else non-blank is prose, the lines a row shows."""
    added: dict[str, str] = {}
    removed: dict[str, str] = {}
    fields: list[str] = []
    prose_added = prose_removed = 0
    lines: list[HistorySummaryLine] = []
    in_hunk = False
    for raw in patch.splitlines():
        if _HUNK.match(raw):
            in_hunk = True
            continue
        if not in_hunk or not raw or raw[0] not in "+-":
            continue   # a file header (`---`/`+++`) comes before the first hunk, so it never reaches here
        sign, text = raw[0], raw[1:]
        claim = _CLAIM_ID.match(text.lstrip())
        if claim is not None:
            (added if sign == "+" else removed)[claim.group(1)] = text
            continue
        field = _FIELD.match(text)
        if field and not text.startswith(" "):
            if field.group(1) not in fields:
                fields.append(field.group(1))
            continue
        stripped = text.strip()
        if not stripped or text.startswith(("  ", "\t")) or stripped.startswith("```") or stripped == "---":
            continue
        if _LIST_VALUE.match(text):
            continue   # a frontmatter list item (`- ep_…`, a tag): one token, never a sentence of prose
        if sign == "+":
            prose_added += 1
        else:
            prose_removed += 1
        if len(lines) < MAX_LINES and not stripped.startswith("#") and (words := _plain(stripped)):
            lines.append(HistorySummaryLine(sign=sign, text=words))
    new_ids = [i for i in added if i not in removed]
    gone_ids = [i for i in removed if i not in added]
    both = [i for i in added if i in removed]
    ended = sum(1 for i in both if _ended(added[i]) and not _ended(removed[i])) \
        + sum(1 for i in new_ids if _ended(added[i]))
    return HistorySummary(plus_claims=sum(1 for i in new_ids if not _ended(added[i])), ended_claims=ended,
                          removed_claims=len(gone_ids), changed_claims=len(both), fields=fields[:MAX_FIELDS],
                          prose_added=prose_added, prose_removed=prose_removed, lines=lines)


async def page(entity_id: str, memory_path: Path, *, limit: int = DEFAULT_LIMIT,
               skip: int = 0) -> tuple[list[EntityHistoryEntry], bool]:
    """``(rows, more)``: up to ``limit`` commits that touched the page after the newest ``skip``, newest first, each
    with its bucket, time and summary; ``more`` when older touching commits exist. ONE ``git log -p``; a bank that is
    not under git, or a page git never saw, is no rows."""
    entity_file = f"entities/{entity_id}.md"
    if not (Path(memory_path) / entity_file).exists():
        return [], False
    limit = max(1, min(int(limit), MAX_LIMIT))
    try:
        out = await git_service._run_git(
            memory_path, "log", f"-n{limit + 1}", f"--skip={max(0, int(skip))}", "-p", "--unified=0", "--no-color",
            "--no-ext-diff", "--first-parent", _FORMAT, "--date=short", "--", entity_file)
    except git_service.GitError:
        return [], False
    records = out.split("\x1e")[1:]
    more = len(records) > limit
    own = re.compile(rf"^[ \t]*(?:entities/{re.escape(entity_id)}\.md:.*|Cicada-[A-Za-z]+:.*|Reason: .*|Undoes: .*)$",
                     re.MULTILINE)
    rows: list[EntityHistoryEntry] = []
    undone: set[str] = set()   # newest first: an undo is read before the join it took back
    for record in records[:limit]:
        head, _, patch = record.partition("\x1d")
        parts = head.split("\x1f", 4)
        if len(parts) < 5:
            continue
        commit, day, at, subject = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3]
        # A decay commit's body names every page in the bank (~2 MB across 30 rows on an owner-scale copy): only this
        # page's manifest line and the trailers are read, found in one C-level regex pass instead of five Python ones.
        body = "\n".join(m.group(0) for m in own.finditer(parts[4]))
        authors = git_service._parse_authors(body)
        author = authors[0] if authors else git_service.UNKNOWN_AUTHOR
        kind, provider = git_service.author_identity(author)
        trigger = git_service._parse_entity_trigger(body, entity_id)
        via = git_service.history_via(trigger)
        join = page_join.kind_of(subject)
        if join == "undo":
            undone.update(m.group(1) for m in _UNDOES.finditer(body))
        rows.append(EntityHistoryEntry(
            join=join, undoable=join in ("merge", "split") and commit not in undone,
            date=day, at=at, change_type=git_service._infer_change_type(subject, body, entity_id),
            description=git_service._build_description(subject, body, entity_id), author=author,
            author_kind=kind, author_provider=provider, commit_hash=commit,
            sessions=git_service._parse_entity_sessions(body, entity_id), trigger=trigger, via=via,
            bucket=bucket(trigger, via, author, kind), summary=summarize(patch)))
    return rows, more
