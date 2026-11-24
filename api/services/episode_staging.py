"""The G20 stager, one seam for every source with a stable identity (R-F1 · G133 · G134).

Moved out of ``api/routers/conversations.py`` — where ``_stage_episodes`` /
``_write_new_episode`` / ``_update_episode_in_place`` lived beside the chat
parsers — because three new sources need exactly its contract (a watched
folder, one episode per file; Wispr Flow meetings and notes; every later
note-taker), and a service must not import from a router. The chat importers
still call it through the router's old names, so their behaviour is
byte-identical: the body is ``role: text`` lines and the hash
``sha256(body)[:12]``.

What the move adds — each additive, each inert to an episode that does not use it:

* ``EpisodeDraft`` — what a parser hands the stager. ``turns`` render to
  ``<marker>: text`` lines; ``body`` is a pre-rendered document (a folder file).
* ``turns`` — per-turn chronology as a frontmatter sidecar, entries of
  ``{offset, ts, speaker}`` into the stored body: G118 slice 2's R-PB4 shape,
  the one ``evidence.turn_stamps`` reads for the Reader. OUTSIDE the content
  hash on purpose: timestamps in the body would change every export's hash and
  re-queue the whole corpus on the next import (💸). An entry only for a turn
  that has a time, always the LAST frontmatter key, capped head-stable at
  ``MAX_TURN_STAMPS``, omitted when no turn has a time. (This track first wrote
  a ``turn_index`` of ``[offset, ts, speaker]`` rows, R-LS1/R-LS2, because the
  Stop hook's ``turns:`` was an integer count (until G141 PJ-4); the merge with
  G118 slice 2 kept ONE key — a pre-PJ-4 hook episode's int reads as "no
  stamps" in ``turn_stamps`` — and turn numbering now comes from the body's
  marker lines, ``evidence.turn_at``.)
* Rename by content — a tombstoned ``source_id`` and a brand-new one in the same
  batch with the same ``content_sha`` and ``#fragment`` repoint the existing
  episode instead of forking a copy (R-F1, R-LS12).
* Tombstones — ``deleted_source_ids`` stamp ``source_deleted_at`` and keep the
  file; a source that comes back clears the stamp (R-F1: the history is the history).
* Scrub — every turn and body goes through ``episode_scrub`` before it is hashed
  or written (R-N3). The hash describes the stored text; a match on the
  unscrubbed render counts as unchanged so a new scrub rule never re-queues or
  forks a legacy episode (R-LS4).
* Both dates (ruling 39, owner 2026-10-24) — a new episode keeps ``timestamp`` as the item's own date where the draft
  gives one and records ``received_at``, when Cicada received it (``episode_ids.create_episode`` stamps it, the one
  door every new episode goes through). It is set once: an edit in place, a re-date (``redated_from`` keeps the moved
  ``timestamp``, never the receipt), a rename, a relay upgrade and a tombstone all leave it as it was.
* ``queue_for_sleep=False`` — an episode a deterministic parser consolidated and
  Sleep never will (``processed_by: parser``, R-LS10).
* Relay upgrade (ruling 32) — a Claude or ChatGPT export's conversation whose
  ``source_id`` is new, and whose first person message matches exactly one episode
  that app's model relayed through the remote connector within two days of it
  (``turn_capture.relay_match_key``), rewrites THAT episode in place with the
  export's words instead of adding a second copy: same file and id, re-queued, the
  relay marked ``upgraded_at`` and its ``evidence_kind: assistant`` dropped — the
  export holds the person's own words. Two candidates, or a first message too short
  to tell conversations apart, upgrade nothing.

The pre-scan reads ``bank_index``'s cached frontmatter instead of re-parsing
every episode per call (R-LS3): a watched folder stages on every save.

One process-wide lock serialises ``stage`` (Track L Task 2 review, round 1):
the scan, the id mint (``max_suffix_by_date``) and the write are a
read-modify-write, and two overlapping callers — the folder watcher plus a
manual Sync, two folder batches, a chat import landing mid-sync — both minted
the same ``ep_<date>_NNN`` and ``markdown_parser.write`` silently overwrote the
first episode. Reproduced with two threads on one date; the lock is here, in
the stager, so every source that stages is covered, not only the folder route.
"""

from __future__ import annotations

import functools
import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from api.services import (agent_turns, bank_index, episode_ids, episode_scrub, evidence, history_index, markdown_parser,
                          sensitive_flags, turn_extras)

#: Keys of one ``turns`` sidecar entry (R-PB4) — the coordination contract, exactly.
#: Round 4 C1 adds ``model``/``effort``: written on an agent turn only, only when the
#: harness recorded them, in this order; every entry carries the first three.
TURN_STAMP_KEYS = ("offset", "ts", "speaker", "model", "effort")
TURN_STAMP_REQUIRED = TURN_STAMP_KEYS[:3]
#: The sidecar's head-stable cap (R-PB4, moved here from the conversations
#: router with the stager): frontmatter is parsed on every cold ``bank_index``
#: scan, so turns past the cap carry no time — the Reader shows a time only when
#: one is stored and never infers one.
MAX_TURN_STAMPS = 500
#: ``processed_by`` of an episode a deterministic parser consolidated (R-LS10).
PARSED_ONLY = "parser"
#: Serialises every ``stage`` call in this process (see the module docstring).
#: Re-entrant so a caller that already holds it (a source that scans, decides and
#: stages under one critical section) can call ``stage`` without deadlocking.
STAGE_LOCK = threading.RLock()


@dataclass
class Turn:
    text: str
    speaker: str = "user"
    ts: str | None = None
    # Round 4 C1: what the harness recorded for an agent turn (R4B-2); ignored
    # on every other speaker, cleaned again by `_stamps` before it is written.
    model: str | None = None
    effort: str | None = None
    # What made the turn part of a conversation beside its words — reactions, a reply's target (an index into the
    # draft's turns, or ``{ref}``), attachments, edited, forwarded-from, code runs (`turn_extras`). Outside the body
    # and its hash: written to the episode's ``turn_extras`` with offsets into the stored body.
    extras: dict | None = None


@dataclass
class EpisodeDraft:
    title: str = ""
    source_id: str | None = None
    source_updated_at: str | None = None
    timestamp: str | None = None
    original_date: str | None = None
    source: str = "unknown"
    origin: str | None = None
    turns: list[Turn] = field(default_factory=list)
    body: str | None = None
    extra: dict = field(default_factory=dict)
    queue_for_sleep: bool = True
    #: Ruling 80 (G246): this draft is a save (a tab group). When it is created, a ``"waiting"`` one is queued for Sleep
    #: tonight and a ``"pile"`` one waits its turn (``history_index``); once it exists a later sync or edit of the record
    #: changes neither ``processed`` nor ``processed_by`` — a group changed after its read is not read again — and never
    #: takes back a read the person's own mention owes. ``None`` (every other writer) is as before.
    save_entry: str | None = None
    content_sha: str | None = None
    writer: str = "import"
    #: Who consolidated an episode that lands already processed (G114 R6). A
    #: parser by default (R-LS10); G141 R-PJ18's companion note is `user` — the
    #: person's own Log words, which Sleep never re-reads.
    processed_by: str = PARSED_ONLY
    #: Messages the sender unsent, by position only — ``[{before: turn index, speaker, ts?, ref?}]`` — never words
    #: (`turn_extras.UNSENT_KEY`).
    unsent: list[dict] = field(default_factory=list)
    #: The draft's ``timestamp`` is authoritative for an episode already staged under its ``source_id``: when the stored
    #: one names another moment, it is moved in place and the episode re-queued (2026-10-23 — a writer whose date
    #: parser had failed stamped the import time). The id is never renamed (ruling 34), so its day may stay the
    #: import's; everything that dates an episode reads ``timestamp``. Off by default: a writer whose first stamp is
    #: deliberate (a future calendar event, dated the day Cicada learned of it) keeps it.
    redate: bool = False
    #: Ruling 39: when Cicada received the item, for a writer whose clock is pinned (the demo); absent, now. Written
    #: only when the episode is created — never by an update, so a receipt is set once.
    received_at: str | None = None
    #: Source ids this draft takes over when its own is new (G104 slice 3): the file that held the episode before a
    #: newer copy of the same meeting replaced it, or the section whose heading was renamed in place. The first one
    #: the bank holds keeps its episode: same id, same file, the source identity moves to the draft's, the old one
    #: joins ``previous_source_ids`` and the body is read as a revision of itself (`episode_revision`) — never a second
    #: episode, never a tombstone. The caller (`folder_source`) decides WHO replaces WHOM; the stager never parses a
    #: name or compares a time.
    replaces: list[str] = field(default_factory=list)
    #: G244 (ruling 76): the agent edits (`source_edits`) behind this draft's bytes — ``[{harness, model?, effort?,
    #: session?, at}]``. Written, when the body changes or the episode is new, as the episode's ``contributions``
    #: (`CONTRIBUTIONS_KEY`); never part of the body, the hash or ``extra``. The caller (`folder_source`) decides
    #: which edits a file's bytes carry, by content; the stager only records them.
    edits: list[dict] = field(default_factory=list)


@dataclass
class StageResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    renamed: int = 0
    tombstoned: int = 0
    #: unchanged bodies whose file hash moved (counted in ``skipped`` too).
    restamped: int = 0
    #: unchanged bodies whose extras moved (a reaction, an unsend) — frontmatter only, never re-queued; counted in
    #: ``skipped`` too.
    extras_updated: int = 0
    scrubbed: int = 0
    #: source_id -> episode id, for every draft with an id (skips included).
    episode_ids: dict[str, str] = field(default_factory=dict)
    #: source_id -> episode id for created, updated and renamed episodes only.
    touched: dict[str, str] = field(default_factory=dict)
    #: source_id -> episode id for episodes stamped deleted this call.
    tombstoned_sources: dict[str, str] = field(default_factory=dict)
    renamed_sources: list[tuple[str, str]] = field(default_factory=list)
    #: ``(old source id, new source id)`` for every episode a draft took over (`EpisodeDraft.replaces`).
    replaced_sources: list[tuple[str, str]] = field(default_factory=list)
    #: bank-relative paths written, for a scoped ``commit_paths``.
    paths: list[str] = field(default_factory=list)
    #: one verb per draft, in order — ``created`` / ``updated`` / ``renamed`` /
    #: ``skipped`` — so ``plan`` can say which draft lands where (Track I T2).
    verdicts: list[str] = field(default_factory=list)

    def as_tuple(self) -> tuple[int, int, int]:
        return self.created, self.updated, self.skipped


@dataclass
class IndexEntry:
    path: Path
    id: str
    fm: dict


def normalise_timestamp(ts) -> str | None:
    """``None`` stays ``None``; an aware ISO string becomes the R2 ``+00:00``
    shape; anything else (naive, unparseable) is returned as ``str(ts)``."""
    if ts is None:
        return None
    text = str(ts)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return text
    if dt.tzinfo is None:
        return text
    return episode_ids.to_utc_iso(dt)


def draft_from_export(episode: dict) -> EpisodeDraft:
    """The chat importers' dict shape as a draft (G20 callers unchanged). A document export (G219: a Notion page)
    carries ``body`` instead of ``messages``, with its own scrub ``writer`` and frontmatter ``extra``."""
    if episode.get("body") is not None:
        return EpisodeDraft(
            title=episode.get("title") or "",
            source_id=episode.get("source_id"),
            source_updated_at=episode.get("source_updated_at"),
            timestamp=episode.get("timestamp"),
            original_date=episode.get("original_date"),
            source=episode.get("source", "unknown"),
            origin=episode.get("origin"),
            body=str(episode["body"]),
            writer=str(episode.get("writer") or "import"),
            extra=dict(episode.get("extra") or {}),
        )
    return EpisodeDraft(
        title=episode.get("title") or "",
        source_id=episode.get("source_id"),
        source_updated_at=episode.get("source_updated_at"),
        timestamp=episode.get("timestamp"),
        original_date=episode.get("original_date"),
        source=episode.get("source", "unknown"),
        origin=episode.get("origin"),
        turns=[Turn(text=m["text"], speaker=m["role"], ts=m.get("timestamp"), model=m.get("model"),
                    extras=m.get("extras") or None)
               for m in episode.get("messages", [])],
        unsent=list(episode.get("unsent") or []),
        writer="import",
        # An importer may declare whose words the episode holds (a Claude memory is
        # the assistant's); absent, the per-line markers decide as before. Ruling 45: a provider's own project
        # grouping rides beside it (``provider_project``), frontmatter only.
        extra={**({"evidence_kind": episode["evidence_kind"]} if episode.get("evidence_kind") else {}),
               **({PROVIDER_PROJECT_KEY: dict(episode["provider_project"])}
                  if isinstance(episode.get("provider_project"), dict) else {})},
    )


#: Ruling 45: a provider's own project grouping on an imported conversation (a ChatGPT ``g-p-`` id), outside the body
#: and its hash; an unchanged conversation that gains it is updated in its frontmatter only, never re-queued.
PROVIDER_PROJECT_KEY = "provider_project"

#: Where a source filed an item (G245): a Notion page's parents and its database. Filing labels, never words — a draft
#: that carries one and an episode that lacks or differs gets it in frontmatter alone, so a page already in the bank
#: learns its place with no word moved and nothing re-queued.
FILING_KEYS = ("notion_database", "notion_path", "notion_path_ids")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _line(turn: Turn, text: str) -> str:
    """One body line — the ONLY place a turn's ``<marker>: text`` shape is
    spelled, so the hashed body and the sidecar's offsets cannot disagree."""
    return f"{turn.speaker}: {text}"


def _stamps(turns: list[Turn], texts: list[str]) -> list[dict]:
    """``[{offset, ts, speaker, model?, effort?}]`` for the body ``texts`` render to (R-PB4, C1).
    ``offset`` is the turn's marker-line start (a turn start ``evidence.turns``
    finds); ``ts`` the turn's own time in the one aware-UTC shape; a turn
    without a time gets no entry (it would only repeat the marker)."""
    out: list[dict] = []
    offset = 0
    for turn, text in zip(turns, texts):
        ts = normalise_timestamp(turn.ts)
        if ts and len(out) < MAX_TURN_STAMPS:
            entry = {"offset": offset, "ts": ts, "speaker": str(turn.speaker)}
            if turn.speaker == "assistant":  # C1: only an agent turn names a model
                if model := agent_turns.clean_model(turn.model):
                    entry["model"] = model
                if effort := agent_turns.clean_effort(turn.effort):
                    entry["effort"] = effort
            out.append(entry)
        offset += len(_line(turn, text)) + 1
    return out


def render(draft: EpisodeDraft) -> tuple[str, list[dict], int]:
    """``(body, turns sidecar, replacements)``. Each turn is scrubbed BEFORE
    its offset is taken, so every offset points into the text that is stored."""
    if draft.body is not None:
        body, n = episode_scrub.scrub_for(draft.body, draft.writer)
        return body, [], n
    texts: list[str] = []
    total = 0
    for turn in draft.turns:
        text, n = episode_scrub.scrub_for(turn.text, draft.writer)
        total += n
        texts.append(text)
    body = "\n".join(_line(t, x) for t, x in zip(draft.turns, texts))
    return body, _stamps(draft.turns, texts), total


def stamps_for(draft: EpisodeDraft, body: str) -> list[dict]:
    """The sidecar for ``body`` when it is exactly ``draft``'s own rendering
    (scrubbed or raw), else ``[]`` — the offsets would vouch for text they do
    not index. For callers that hold a body as given: the router's compat
    wrappers, and the Stop hook's writer (``transcript_capture``, G141 PJ-4),
    whose ``role: text`` body is this module's line shape byte for byte."""
    if draft.body is not None:
        return []
    for texts in ([episode_scrub.scrub_for(t.text, draft.writer)[0] for t in draft.turns], [t.text for t in draft.turns]):
        if "\n".join(_line(t, x) for t, x in zip(draft.turns, texts)) == body:
            return _stamps(draft.turns, texts)
    return []


def render_extras(draft: EpisodeDraft, *, raw: bool = False) -> dict:
    """``{turn_extras?, unsent_turns?}`` for the body ``draft`` renders to — scrubbed, or ``raw`` for an episode whose
    stored body is the legacy unscrubbed render — with every offset a turn start in that body. ``{}`` for a
    pre-rendered body or a draft with no extras (no scrub is run then)."""
    if draft.body is not None or not turn_extras.has_any(draft.turns, draft.unsent):
        return {}
    texts = [t.text if raw else episode_scrub.scrub_for(t.text, draft.writer)[0] for t in draft.turns]
    lengths = [len(_line(t, x)) for t, x in zip(draft.turns, texts)]
    body_length = sum(lengths) + max(len(lengths) - 1, 0)
    return turn_extras.render(draft.turns, lengths, draft.unsent, body_length)


def _extras_matching(draft: EpisodeDraft, body: str) -> dict:
    """:func:`render_extras` for ``body`` when it is ``draft``'s own rendering (scrubbed or raw), else ``{}`` — the
    offsets would point into text they do not index (the rule :func:`stamps_for` keeps for the sidecar)."""
    if draft.body is not None or not turn_extras.has_any(draft.turns, draft.unsent):
        return {}
    for raw in (False, True):
        texts = [t.text if raw else episode_scrub.scrub_for(t.text, draft.writer)[0] for t in draft.turns]
        if "\n".join(_line(t, x) for t, x in zip(draft.turns, texts)) == body:
            return render_extras(draft, raw=raw)
    return {}


def _apply_extras(fm: dict, extras: dict) -> None:
    """`turn_extras.apply`, then the sidecar back to the last key (R-PB4)."""
    turn_extras.apply(fm, extras)
    if "turns" in fm:
        fm["turns"] = fm.pop("turns")


def _raw_render(draft: EpisodeDraft) -> str:
    if draft.body is not None:
        return draft.body
    return "\n".join(_line(t, t.text) for t in draft.turns)


def _fragment(source_id: str) -> str:
    return source_id.partition("#")[2]


def _rel(path: Path, episodes_dir: Path) -> str:
    return f"{episodes_dir.name}/{path.name}"


def scan(episodes_dir: Path) -> tuple[dict[str, IndexEntry], set[str]]:
    """``source_id -> entry`` plus every stored content hash, from ONE cached
    read of the directory (R-LS3). Frontmatter is copied: ``bank_index`` hands
    out its cache and a caller must never mutate it."""
    by_source: dict[str, IndexEntry] = {}
    hashes: set[str] = set()
    for f in bank_index.files(episodes_dir.parent, episodes_dir.name):
        fm = dict(f.frontmatter or {})
        if fm.get("content_hash"):
            hashes.add(str(fm["content_hash"]))
        sid = fm.get("source_id")
        if sid:
            by_source[str(sid)] = IndexEntry(path=f.path, id=str(fm.get("id") or f.stem), fm=fm)
    return by_source, hashes


#: Ruling 32: an export source → the remote connector app whose relayed episodes it may upgrade.
RELAY_UPGRADES = {"claude": "claude", "chatgpt": "chatgpt"}
#: How far apart a relayed conversation's start and the export's may be and still be one conversation.
RELAY_WINDOW_S = 2 * 86400
#: Writer-owned keys of a relayed episode that describe the relayed body, dropped when an export replaces it.
_RELAY_BODY_KEYS = ("evidence_kind", "hook_turns", "capture_gap", "capture_flags", "tail_turns")


def relay_candidates(episodes_dir: Path) -> dict[tuple[str, str], list[IndexEntry]]:
    """Relayed episodes not yet upgraded, by ``(app, match key)`` — one cached read, as :func:`scan`."""
    out: dict[tuple[str, str], list[IndexEntry]] = {}
    for f in bank_index.files(episodes_dir.parent, episodes_dir.name):
        fm = f.frontmatter or {}
        relay = fm.get("relay")
        if not isinstance(relay, dict) or relay.get("upgraded_at") or not relay.get("first") or not relay.get("app"):
            continue
        out.setdefault((str(relay["app"]), str(relay["first"])), []).append(
            IndexEntry(path=f.path, id=str(fm.get("id") or f.stem), fm=dict(fm)))
    return out


def _when(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else None


def relay_for(draft: EpisodeDraft, candidates: dict[tuple[str, str], list[IndexEntry]]) -> IndexEntry | None:
    """The ONE relayed episode this export conversation is (ruling 32), or ``None``."""
    app = RELAY_UPGRADES.get(draft.source)
    first = next((t.text for t in draft.turns if t.speaker == "user" and (t.text or "").strip()), None)
    started = _when(normalise_timestamp(draft.timestamp))
    if app is None or first is None or started is None:
        return None
    from api.services.transcript_extract import clean_turn
    from api.services.turn_capture import relay_match_key

    cleaned, _ = clean_turn("user", first, first=True)
    key = relay_match_key(cleaned.text if cleaned is not None else None)
    if key is None:
        return None
    near = [e for e in candidates.get((app, key), [])
            if (t := _when(e.fm.get("timestamp"))) is not None and abs((t - started).total_seconds()) <= RELAY_WINDOW_S]
    return near[0] if len(near) == 1 else None


def stored_meta(values: dict) -> dict:
    """Writer frontmatter as it is stored: named secret shapes scrubbed from its strings, keys, paths and ids never
    touched (``episode_scrub.scrub_value``; review of #560). A writer that compares what it would write with what is
    on disk compares THIS with it, or a scrubbed value reads as changed on every sync."""
    return episode_scrub.scrub_value(dict(values))[0]


def stored_title(title: str | None) -> str:
    return episode_scrub.scrub_value(title or "", key="title")[0]


def _extra(draft: EpisodeDraft) -> dict:
    """``draft.extra`` as stored (:func:`stored_meta`) — the one way extras reach a file, so no writer's frontmatter
    (a note's description, a chat's title) keeps a named secret its words lost."""
    return stored_meta(draft.extra)


def _title(draft: EpisodeDraft) -> str:
    return stored_title(draft.title)


def _apply_common(fm: dict, draft: EpisodeDraft, stamps: list[dict], body: str | None = None,
                  *, creating: bool = False) -> None:
    fm.update(_extra(draft))
    _apply_extras(fm, _extras_matching(draft, body) if body is not None else {})
    if draft.content_sha:
        fm["content_sha"] = draft.content_sha
    if draft.save_entry is not None and history_index.SAVES_READ:
        if creating:
            if draft.save_entry == "waiting":
                fm["processed"] = False
                fm.pop("processed_by", None)
            else:
                fm["processed"] = True
                fm["processed_by"] = history_index.INDEXED_BY
        # an existing save keeps its state: it is read once, whatever its record says later (ruling 80)
    elif draft.queue_for_sleep or _read_owed(fm, draft):
        fm["processed"] = False
        # G114 R6: `processed_by` is written only beside `processed: true`.
        fm.pop("processed_by", None)
    else:
        fm["processed"] = True
        fm["processed_by"] = draft.processed_by
        if draft.processed_by == history_index.INDEXED_BY:
            # Its one read was of the old words: these are a bare save again, found and woken like any other.
            fm.pop(history_index.WOKEN_KEY, None)
    set_turn_stamps(fm, stamps)


def _read_owed(fm: dict, draft: EpisodeDraft) -> bool:
    """Ruling 62: a lean writer's draft (a tab group, a saved list) says nothing about a read the person's own mention
    or reason queued: a sync before that read leaves it queued, whatever the sync changed."""
    return draft.processed_by == history_index.INDEXED_BY and history_index.owes_a_read(fm)


def set_turn_stamps(fm: dict, stamps: list[dict]) -> None:
    """R-PB4: the new body's times replace the old ones, as the LAST key so the
    episode's identity reads first; a body that lost them drops the key rather
    than keeping stale offsets. The one writer of the key (R-CS7's lint keeps
    it to this module, ``evidence`` and ``transcript_capture``) — a writer that
    builds its own frontmatter, like the demo generator, sets it through here."""
    fm.pop("turns", None)
    if stamps:
        fm["turns"] = stamps


def write_new(draft: EpisodeDraft, episodes_dir: Path, body: str, digest: str,
              stamps: list[dict], date_counts: dict[str, int]) -> Path:
    """A fresh episode with a chronological id (G114 R1: ``date_counts`` holds the
    highest suffix per date, seeded from ``max_suffix_by_date``)."""
    ep_date = draft.original_date or datetime.now().strftime("%Y-%m-%d")
    date_counts[ep_date] = date_counts.get(ep_date, 0) + 1
    episode_id = f"ep_{ep_date}_{date_counts[ep_date]:03d}"
    fm = {
        "id": episode_id,
        "timestamp": normalise_timestamp(draft.timestamp) or episode_ids.utc_now_iso(),
        # Ruling 39: the item's own date above, when Cicada received it here — set once, at creation.
        episode_ids.RECEIVED_KEY: normalise_timestamp(draft.received_at) or episode_ids.utc_now_iso(),
        "source": draft.source,
        "title": _title(draft) or "Untitled",
        "processed": False,
        "content_hash": digest,
    }
    if draft.origin:
        fm["origin"] = draft.origin
    if draft.source_id is not None:
        fm["source_id"] = draft.source_id
        fm["source_updated_at"] = draft.source_updated_at
    if draft.edits:   # G244, before `_apply_common`: the turn sidecar stays the last key
        from api.services import source_edits   # review B1: whole-body ranges only for a file the agent wrote whole
        whole = source_edits.whole_body_is_theirs(e.get("tool") for e in draft.edits)
        with_contributions(fm, contribution_entries(draft.edits, digest, changed_ranges(None, body) if whole else []))
    _apply_common(fm, draft, stamps, body, creating=True)
    # Audit K01: `date_counts` was seeded at the start of the call, and a writer
    # in another process (an MCP server, the Stop hook) may have taken the id
    # since; the create re-mints rather than replace that episode.
    episode_id = episode_ids.create_episode(episodes_dir, fm, body)
    date_counts[ep_date] = max(date_counts[ep_date], episode_ids.parse_episode_id(episode_id)[1])
    return episodes_dir / f"{episode_id}.md"


def _under_episode_lock(fn):
    """Run one read-modify-write of an existing episode under the bank's
    episode lock (audit A01): Sleep's retirement re-reads under the same lock,
    so it sees this edit or retires before it — never flips a body it did not
    read. Per operation, never per import: the Stop hook shares the lock."""
    @functools.wraps(fn)
    def locked(path, *args, **kwargs):
        with episode_ids.episode_lock(Path(path).parent):
            return fn(path, *args, **kwargs)
    return locked


#: An edit in place says it is one (owner 2026-11-03: "re-ingested items are updates, not new"; G95): the record Sleep
#: reads to treat a re-queued episode as a newer revision of what it already filed, never as a new conversation.
#: ``count`` — the body's edits in place so far; ``at`` — when the latest landed (UTC); ``previous_hash`` — the
#: ``content_hash`` of the body this edit replaced; ``consolidated_hash`` — the ``content_hash`` of the last body that was
#: consolidated (processed by Sleep or an agent, never by a parser or the index), kept through later edits until Sleep
#: reads the episode again, absent while no revision was ever consolidated. The earlier body is in git.
REVISED_KEY = "revised"
#: G104 slice 3 — one meeting is one episode, whichever copy of its file is newest. The episode holds the newest file
#: (``source_id``/``relpath``/``content_sha``/``source_updated_at`` are that file's); ``replaced_files`` is the other
#: copies of the same meeting it has seen — ``[{relpath, content_sha, mtime}]`` (``mtime`` UTC ISO, newest first, at
#: most :data:`MAX_REPLACED`) — so a copy posted again never turns the correction back into the words it replaced.
#: ``held_gone_at`` says the held file was deleted while another copy remains: the episode keeps its words (a deleted
#: source keeps what it taught) until the caller posts a remaining copy again. Written by `folder_source` through
#: :func:`set_file_record` and the takeover below, never by a chat importer.
REPLACED_KEY = "replaced_files"
HELD_GONE_KEY = "held_gone_at"
MAX_REPLACED = 20
#: ``processed_by`` values that mean nothing consolidated the body (R-LS10's parser, ``history_index.INDEXED_BY``).
#: ``processed_by`` of an episode whose source was deleted before anything read it (ROR-142 follow-up, ruling 75): it taught
#: nothing, so it leaves every waiting queue and Sleep never consolidates it — the file stays, still marked
#: ``source_deleted_at``. The source posted again re-queues it (`_requeue_for_authorship`).
DELETED_UNREAD = "source-deleted"
_NOT_CONSOLIDATED_BY = frozenset({PARSED_ONLY, history_index.INDEXED_BY, history_index.NO_WORDS_BY, DELETED_UNREAD})


#: G244 (ruling 76): an agent edited the source file this episode holds — ``[{harness, model?, effort?, session?, at,
#: content_hash, ranges}]``, newest first, at most :data:`MAX_CONTRIBUTIONS`. ``content_hash`` is the body's hash after the
#: edit and ``ranges`` the changed ``[start, end]`` character ranges of that body against the one it replaced, so a span
#: is marked corrected only while the body is still the one the edit made (`source_spans`). Outside ``content_hash``
#: (frontmatter), kept by every later edit in place, written by this module only.
CONTRIBUTIONS_KEY = "contributions"
MAX_CONTRIBUTIONS = 20
#: Changed ranges one contribution keeps (frontmatter is parsed on every cold scan); a longer list drops its tail —
#: fewer marked spans, never a wrong one.
MAX_CONTRIBUTION_RANGES = 128


def changed_ranges(prior: str | None, body: str) -> list[list[int]]:
    """The ``[start, end]`` ranges of ``body`` that differ from the ``prior`` body it replaced (``episode_revision.diff``,
    by line, whitespace ignored); the whole body when there is no prior (a new episode). Adjacent ranges are one."""
    from api.services import episode_revision

    body = body.strip()   # the document a span indexes is the parsed body, stripped (`evidence.source_document`)
    if prior is None:
        return [[0, len(body)]] if body else []
    spans: list[list[int]] = []
    for lo, hi in episode_revision.diff(prior, body)[0]:
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])
    return spans[:MAX_CONTRIBUTION_RANGES]


def contribution_entries(edits: list[dict], digest: str, ranges: list[list[int]]) -> list[dict]:
    """``edits`` as stored contributions, newest first, with the body they made (``digest``) and its changed ranges."""
    out = []
    for e in sorted(edits, key=lambda e: episode_ids.timestamp_sort_key(e.get("at")), reverse=True):
        entry = {k: e[k] for k in ("harness", "model", "effort", "session", "at") if e.get(k)}
        entry["content_hash"] = digest
        entry["ranges"] = [list(r) for r in ranges]
        out.append(entry)
    return out


def with_contributions(fm: dict, entries: list[dict]) -> None:
    """``entries`` first in ``fm``'s ``contributions``, an entry already there (same harness, session, time and body)
    kept once, the list capped."""
    if not entries:
        return
    held = [c for c in fm.get(CONTRIBUTIONS_KEY) or [] if isinstance(c, dict)]
    same = lambda a, b: all(a.get(k) == b.get(k) for k in ("harness", "session", "at", "content_hash"))  # noqa: E731
    kept = [c for c in held if not any(same(c, e) for e in entries)]
    fm[CONTRIBUTIONS_KEY] = [*entries, *kept][:MAX_CONTRIBUTIONS]


def revision_record(fm: dict, *, at: str | None = None) -> dict:
    """The ``revised`` record an edit in place writes over ``fm`` (the episode's frontmatter BEFORE the edit)."""
    prior = fm.get(REVISED_KEY) if isinstance(fm.get(REVISED_KEY), dict) else {}
    try:
        count = max(0, int(prior.get("count") or 0))
    except (TypeError, ValueError):
        count = 0
    record: dict = {"count": count + 1, "at": at or episode_ids.utc_now_iso()}
    if fm.get("content_hash"):
        record["previous_hash"] = str(fm["content_hash"])
    consolidated = fm.get("processed") is True and fm.get("processed_by") not in _NOT_CONSOLIDATED_BY
    if consolidated and fm.get("content_hash"):
        record["consolidated_hash"] = str(fm["content_hash"])
    elif prior.get("consolidated_hash"):
        record["consolidated_hash"] = str(prior["consolidated_hash"])
    return record


@_under_episode_lock
def update_in_place(path: Path, draft: EpisodeDraft, body: str, digest: str, stamps: list[dict],
                    previous_sid: str | None = None) -> None:
    """Same file, same id, same original timestamp; new body, re-queued (G20), marked as a revision (``revised``).
    ``previous_sid`` is the source id the episode held before a draft took it over (`EpisodeDraft.replaces`): it joins
    ``previous_source_ids`` and the held-file marker is cleared."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm[REVISED_KEY] = revision_record(fm)
    if draft.edits:   # G244: the prior body is in hand here — the changed ranges are against it
        with_contributions(fm, contribution_entries(draft.edits, digest, changed_ranges(parsed.body, body)))
    if previous_sid and previous_sid != draft.source_id:
        _remember_source(fm, previous_sid)
    fm.pop(HELD_GONE_KEY, None)
    fm["title"] = _title(draft) or fm.get("title", "Untitled")
    fm["content_hash"] = digest
    fm["source_updated_at"] = draft.source_updated_at
    fm["source_id"] = draft.source_id
    if draft.origin:
        fm["origin"] = draft.origin
    fm.pop("source_deleted_at", None)
    _apply_common(fm, draft, stamps, body)
    markdown_parser.write(path, fm, body)


@_under_episode_lock
def relabel_in_place(path: Path, old: str, new: str, *, update: Callable[[dict], None] | None = None) -> int:
    """ROR-142: every turn line ``<old>: …`` becomes ``<new>: …`` — a speaker's marker renamed on the person's answer.
    The turn stamps' offsets move with the text before them; the body is a revision of itself (``revised``),
    re-queued, so Sleep reads only the changed lines (`episode_revision`). ``update`` edits the frontmatter in the same
    write (the meeting record). Returns how many lines changed; 0 writes nothing."""
    parsed = markdown_parser.parse(path)
    fm, body = dict(parsed.frontmatter), parsed.body
    was, now = f"{old}: ", f"{new}: "
    lines, moves, start, shift = [], [], 0, 0   # moves: (old offset of a changed line, total shift after it)
    for line in body.split("\n"):
        length = len(line)
        if line.startswith(was):
            line = now + line[len(was):]
            shift += len(now) - len(was)
            moves.append((start, shift))
        lines.append(line)
        start += length + 1
    if not moves:
        return 0

    def moved(offset: int) -> int:
        before = [s for at, s in moves if at < offset]
        return offset + (before[-1] if before else 0)

    stamps = []
    for entry in fm.get("turns") or []:
        if isinstance(entry, dict) and isinstance(entry.get("offset"), int):
            entry = {**entry, "offset": moved(entry["offset"])}
            if entry.get("speaker") == old:
                entry["speaker"] = new
        stamps.append(entry)
    out = "\n".join(lines)
    fm[REVISED_KEY] = revision_record(fm)
    fm["content_hash"] = content_hash(out)
    fm["processed"] = False
    fm.pop("processed_by", None)
    if update is not None:
        update(fm)
    set_turn_stamps(fm, stamps)
    markdown_parser.write(path, fm, out)
    return len(moves)


@_under_episode_lock
def upgrade_relay(path: Path, draft: EpisodeDraft, body: str, digest: str, stamps: list[dict], at: str) -> None:
    """Ruling 32: the export's words replace a relayed body — same file, same id and original timestamp, re-queued
    for Sleep. The relay record stays, stamped ``upgraded_at``, so the app can say where the episode began."""
    fm = dict(markdown_parser.parse(path).frontmatter)
    for key in _RELAY_BODY_KEYS:
        fm.pop(key, None)
    fm["relay"] = {**(fm.get("relay") or {}), "upgraded_at": at, "upgraded_by": draft.source, "imported_hash": digest}
    fm["source"] = draft.source
    fm["title"] = _title(draft) or fm.get("title", "Untitled")
    fm["content_hash"] = digest
    fm["source_id"] = draft.source_id
    fm["source_updated_at"] = draft.source_updated_at
    if draft.origin:
        fm["origin"] = draft.origin
    _apply_common(fm, draft, stamps, body)
    markdown_parser.write(path, fm, body)


def has_relayed_tail(fm: dict | None) -> bool:
    """Ruling 58: this upgraded episode holds later turns its model relayed after the imported part."""
    relay = (fm or {}).get("relay")
    return isinstance(relay, dict) and isinstance(relay.get("tail_at"), int) and bool(relay.get("imported_hash"))


def append_relayed(path: Path, fm: dict, body: str, rows: list[dict], *, at: str, project: str | None = None) -> str:
    """Ruling 58 (owner, 2026-11-04): a chat continued after its one-time import keeps its later turns in the same episode,
    after the imported part, whose offsets never move. ``rows`` are ``{marker, speaker, text, ts}``, cleaned and scrubbed
    by the caller. Each person's turn carries its own ``relayed [...]:`` marker, so it reads as the relaying model's words
    (`evidence._marker`) beside the imported part's ``user:`` lines; no episode-wide ``evidence_kind`` could say both. Any
    line that would open a turn is quoted. A revision of itself (``revised``), re-queued, so Sleep reads only what grew
    (`episode_revision`). The caller holds the episode lock. Returns the new ``content_hash``."""
    fm = dict(fm)
    relay = dict(fm.get("relay") or {})
    if not has_relayed_tail(fm):
        relay["imported_hash"] = str(fm.get("content_hash") or content_hash(body))     # what is here, a removal included
        relay["tail_at"] = len(body) + 1
    if project:
        relay["project"] = project
    fm[REVISED_KEY] = revision_record(fm)
    stamps = [dict(e) for e in fm.get("turns") or [] if isinstance(e, dict)] if isinstance(fm.get("turns"), list) else []
    out = body
    for row in rows:
        out += "\n"
        if row["ts"] and len(stamps) < MAX_TURN_STAMPS:
            stamps.append({"offset": len(out), "ts": row["ts"], "speaker": row["speaker"]})
        out += f"{row['marker']}: {evidence.quote_markers(row['text'])}"
    digest = content_hash(out)
    fm["relay"] = relay
    fm["content_hash"] = digest
    fm["last_turn_at"] = at
    if isinstance(fm.get("turn_count"), int):
        fm["turn_count"] += len(rows)
    fm["processed"] = False
    fm.pop("processed_by", None)
    set_turn_stamps(fm, stamps)
    markdown_parser.write(path, fm, out)
    return digest


def _turn_key(text: str) -> str:
    """A turn's words, however its door rendered them: the export's and the relay's cleaning differ (code fences, caps)."""
    return "".join(c for c in (text or "").casefold() if c.isalnum())[:400]


def relayed_tail(fm: dict, body: str) -> list[evidence.TurnSpan]:
    """The later relayed turns of an upgraded episode, with offsets into ``body``."""
    if not has_relayed_tail(fm):
        return []
    return [t for t in evidence.turns(body) if t.start >= fm["relay"]["tail_at"] and t.marker]


@_under_episode_lock
def merge_relayed_tail(path: Path, draft: EpisodeDraft, export_body: str, digest: str, stamps: list[dict]) -> str:
    """Ruling 58: another import of a chat that went on. The export's body replaces the imported part, and of the later
    relayed turns only those it does not hold stay after it, unchanged: a turn the export holds is the person's own now,
    never kept twice. In order, so a repeated "yes" is matched to its own place. Returns the new ``content_hash``."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm[REVISED_KEY] = revision_record(fm)
    held = [(t.speaker, _turn_key(t.text)) for t in draft.turns if (t.text or "").strip()]
    at = 0
    kept: list[evidence.TurnSpan] = []
    for turn in relayed_tail(fm, parsed.body):
        speaker = "assistant" if turn.marker in ("assistant", "ai") else "user"
        words = _turn_key(parsed.body[turn.content_start:turn.end])
        found = next((i for i in range(at, len(held)) if held[i] == (speaker, words)), None)
        if found is None:
            kept.append(turn)
        else:
            at = found + 1
    old_stamps = {e.get("offset"): e for e in fm.get("turns") or [] if isinstance(e, dict)} \
        if isinstance(fm.get("turns"), list) else {}
    out = export_body
    all_stamps = list(stamps)
    for turn in kept:
        out += "\n"
        if (stamp := old_stamps.get(turn.start)) is not None and len(all_stamps) < MAX_TURN_STAMPS:
            all_stamps.append({**stamp, "offset": len(out)})
        out += parsed.body[turn.start:turn.end]
    relay = {**(fm.get("relay") or {}), "imported_hash": digest, "upgraded_by": draft.source}
    if kept:
        relay["tail_at"] = len(export_body) + 1
    else:
        relay.pop("tail_at", None)
    merged = content_hash(out)
    fm["relay"] = relay
    fm["title"] = _title(draft) or fm.get("title", "Untitled")
    fm["content_hash"] = merged
    fm["source_updated_at"] = draft.source_updated_at
    _apply_common(fm, draft, all_stamps, export_body)
    markdown_parser.write(path, fm, out)
    return merged


@_under_episode_lock
def _refresh(path: Path, draft: EpisodeDraft) -> None:
    """Same body, changed metadata (an authorship flip, a returning file). A
    parser-only episode that is now owner-authored is queued; a queued one that
    is now agent-authored is parked. An episode Sleep already consolidated is
    never un-processed — its claims exist either way."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm.pop("source_deleted_at", None)
    fm.update(_extra(draft))
    if draft.content_sha:
        fm["content_sha"] = draft.content_sha
    if draft.source_updated_at:
        fm["source_updated_at"] = draft.source_updated_at
    _requeue_for_authorship(fm, draft)
    _apply_extras(fm, _extras_matching(draft, parsed.body))
    markdown_parser.write(path, fm, parsed.body)


def _requeue_for_authorship(fm: dict, draft: EpisodeDraft) -> None:
    """The queue rule for an episode whose BODY is unchanged but whose
    authorship may have moved (R-LS10 / R-F2): a parser-only episode that is now
    the person's own words is queued; an unconsolidated one that is now an
    agent's is parked as parser-only. An episode Sleep already consolidated is
    never un-processed — its claims exist either way.

    Shared by ``_refresh`` (a glob flip) and ``_repoint`` (a rename). Before it
    was shared, a rename across an authorship glob (``notes.md`` →
    ``archive/notes.md``) flipped ``evidence_kind`` but not the queue state, so
    Sleep consolidated agent prose — or never saw the person's words — and the
    folder's idempotence check (``content_sha`` + ``evidence_kind``) then read
    the file as unchanged forever (Track L Task 2 review, round 1)."""
    if draft.save_entry is not None and history_index.SAVES_READ and fm.get("processed_by") != DELETED_UNREAD:
        return   # ruling 80: a save is read once, however its record changes (`EpisodeDraft.save_entry`)
    if fm.get("processed_by") == DELETED_UNREAD and fm.get("source_deleted_at"):
        return   # still deleted: a glob flip or a rule change never brings an unread, deleted file back to the queue
    if fm.get("processed_by") == DELETED_UNREAD and not draft.queue_for_sleep:
        fm["processed_by"] = draft.processed_by   # back from a deletion, but an agent's words: parked as before
    elif draft.queue_for_sleep and fm.get("processed_by") in (PARSED_ONLY, DELETED_UNREAD):
        fm["processed"] = False
        # G114 R6: `processed_by` is written only beside `processed: true`.
        fm.pop("processed_by", None)
    elif not draft.queue_for_sleep and not fm.get("processed") and not _read_owed(fm, draft):
        fm["processed"] = True
        fm["processed_by"] = draft.processed_by


def reattribute(path: Path, *, extra: dict, queue_for_sleep: bool) -> bool:
    """Same body, same hash, new authorship (F2-back R-B6): a folder's rule
    changed, and the episode must say whose words it holds without the app
    re-posting a byte. Frontmatter only — ``content_hash``, ``content_sha``,
    ``source_id``, ``source_deleted_at`` and the body are untouched, so every
    evidence span into it stays ``current`` (G118) and a tombstone stays one.

    The queue follows :func:`_requeue_for_authorship`, the rule ``_refresh``
    and ``_repoint`` already share, so a rule change and a glob flip on re-post
    cannot disagree (R-B7) — for a tombstoned episode too, because an agent's
    words are never queued for Sleep (R-LS10) and a deletion never touched the
    queue. Returns whether the file changed. Runs under ``STAGE_LOCK``."""
    with STAGE_LOCK, episode_ids.episode_lock(Path(path).parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        before = dict(fm)
        fm.update(stored_meta(extra))
        _requeue_for_authorship(fm, EpisodeDraft(queue_for_sleep=queue_for_sleep))
        if fm == before:
            return False
        if "turns" in fm:
            fm["turns"] = fm.pop("turns")  # R-PB4: the sidecar stays the last key
        markdown_parser.write(path, fm, parsed.body)
        return True


def drop_keys(path: Path, keys: tuple[str, ...]) -> bool:
    """Frontmatter keys a writer's new record no longer holds — a staged update merges the draft's keys over the stored
    ones, so a key the record dropped would otherwise outlive it (chats-ux-v2: a sitting re-recorded as the person's
    own notes keeps no ``correspondent``). Body, hashes and the Sleep queue untouched. Returns whether the file
    changed. Runs under ``STAGE_LOCK``."""
    with STAGE_LOCK, episode_ids.episode_lock(Path(path).parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        gone = [k for k in keys if k in fm]
        if not gone:
            return False
        for k in gone:
            fm.pop(k)
        markdown_parser.write(path, fm, parsed.body)
        return True


def amend_frontmatter(path: Path, edit: Callable[[dict], bool]) -> bool:
    """One frontmatter-only change to an episode that exists (G221's folders and the readiness a folder's reason gives
    a save): ``edit(frontmatter)`` mutates a copy of the CURRENT frontmatter, inside the same locks as every in-place
    edit, and returns whether it changed anything. The body, ``content_hash`` and every span are untouched. Whatever
    ``edit`` does to ``processed`` is its own decision (a wake queues the save for Sleep; nothing else does). Returns
    whether the file changed."""
    with STAGE_LOCK, episode_ids.episode_lock(Path(path).parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        before = dict(fm)
        if not edit(fm) or fm == before:
            return False
        if "turns" in fm:
            fm["turns"] = fm.pop("turns")  # R-PB4: the sidecar stays the last key
        markdown_parser.write(path, fm, parsed.body)
        return True


def _section_bounds(body: str, heading: str) -> tuple[int, int] | None:
    """``(start, end)`` of the ``## heading`` section in ``body`` — from its heading line to the next ``## `` heading
    (or the end) — or ``None`` when the body has none. Only a whole line matches."""
    lines = body.splitlines(keepends=True)
    offset = 0
    start = None
    for line in lines:
        bare = line.rstrip("\r\n")
        if start is None and bare == heading:
            start = offset
        elif start is not None and bare.startswith("## "):
            return start, offset
        offset += len(line)
    return (start, len(body)) if start is not None else None


def amend_section(path: Path, heading: str, text: str, *, extra: dict | None = None,
                  writer: str, bank: str | None = None, before: tuple[str, ...] = ()) -> bool:
    """The person added words to an episode that already exists (G191): one ``## `` section, written in place.

    The section is the person's to replace — a second answer rewrites it, never appends a twin — and every other
    byte of the body is kept. The new text is scrubbed (the R-N3 rule every staged turn follows) before it is
    written, ``extra`` lands in the frontmatter, and the episode is queued for Sleep again (``processed: false``):
    the body changed, and it changed with the person's own words, so Sleep must read it — the queue rule an edit in
    place has always followed (G20). The section goes before the first heading named in ``before`` when the body
    has one (so it is never read as part of an agent's ``## Note``), else at the end. Under ``STAGE_LOCK`` and the
    bank's episode lock, so Sleep's revision-checked retirement sees this edit or retires before it (audit A01).
    Returns whether the file changed."""
    return revise_section(path, heading, lambda _fm: (text, dict(extra or {}), ()), writer=writer, bank=bank,
                          before=before)


def revise_section(path: Path, heading: str, build, *, writer: str, bank: str | None = None,
                   before: tuple[str, ...] = ()) -> bool:
    """:func:`amend_section` whose text and frontmatter are computed from the episode's CURRENT frontmatter, inside
    the same locks (G191 v3: a re-save's answer is added to the earlier ones, so the writer must read them and write
    the section in one step, or two answers landing together would each drop the other).

    ``build(frontmatter) -> (text, extra, drop)``: ``text`` is the section's new text (scrubbed here); ``extra`` is
    merged into the frontmatter and every key in ``drop`` removed."""
    with STAGE_LOCK, episode_ids.episode_lock(Path(path).parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        body = parsed.body
        text, extra, drop = build(dict(fm))
        bounds = _section_bounds(body, heading)
        cleaned = episode_scrub.scrub_body(text.strip(), writer=writer, bank=bank)
        section = f"{heading}\n{cleaned}\n"
        if bounds is not None:
            start, end = bounds
            tail = body[end:]
            new_body = body[:start] + section + ("\n" + tail if tail else "")
        else:
            cut = min((b[0] for b in (_section_bounds(body, h) for h in before) if b is not None), default=None)
            if cut is not None:
                new_body = body[:cut] + section + "\n" + body[cut:]
            else:
                new_body = body.rstrip("\n") + "\n\n" + section
        before_fm = dict(fm)
        fm.update(extra or {})
        for key in drop:
            fm.pop(key, None)
        if new_body == body and fm == before_fm:
            return False
        if new_body != body:
            fm["processed"] = False
            # G114 R6: `processed_by` is written only beside `processed: true`.
            fm.pop("processed_by", None)
        if "turns" in fm:
            fm["turns"] = fm.pop("turns")  # R-PB4: the sidecar stays the last key
        markdown_parser.write(path, fm, new_body)
        return True


def _moved(stored, wanted) -> bool:
    """Whether ``wanted`` names another moment than ``stored`` (both readable, aware); never for an unreadable one —
    ``None``, a naive or unparseable string, or any other value answers ``False``.

    A pure comparison of two frontmatter values, so it takes no lock: it reads nothing from disk, and the write it
    gates (:func:`_redate`) takes the episode's own lock. (#447 put ``_under_episode_lock`` here, which locks
    ``Path(<first argument>).parent`` — for a timestamp that is the working directory, and ``None`` raised.)"""
    try:
        old, new = _when(normalise_timestamp(stored)), _when(normalise_timestamp(wanted))
    except Exception:  # noqa: BLE001 — an unreadable stored value is "not moved", never a failed sync
        return False
    return old is not None and new is not None and old != new


@_under_episode_lock
def _redate(path: Path, draft: EpisodeDraft, stamps: list[dict]) -> None:
    """``EpisodeDraft.redate``: the episode's moment moves to the draft's, in place — same file, same id (ruling 34),
    re-queued so Sleep reads it on its true day; the turns' times are the draft's too. The moment it replaced is kept
    as ``redated_from``. Frontmatter only: the body and ``content_hash`` are untouched, so every G118 evidence span
    into this episode stays ``current`` (the ``turns`` sidecar is outside the hash, R-PB4)."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["redated_from"] = fm.get("timestamp")
    fm["timestamp"] = draft.timestamp
    fm["processed"] = False
    fm.pop("processed_by", None)
    set_turn_stamps(fm, stamps)
    markdown_parser.write(path, fm, parsed.body)


@_under_episode_lock
def _restamp(path: Path, draft: EpisodeDraft) -> None:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["content_sha"] = draft.content_sha
    if draft.source_updated_at:
        fm["source_updated_at"] = draft.source_updated_at
    if isinstance(draft.extra.get(SECTION_KEY), dict):
        # An unchanged section of an edited file may sit at another position now; a heading renamed later is matched
        # to this episode by that position (`folder_source`), so it must be the current one.
        fm[SECTION_KEY] = dict(draft.extra[SECTION_KEY])
    markdown_parser.write(path, fm, parsed.body)


#: A section of a split note records its position in the file (``{index}``), the one thing that survives a heading's
#: rename (G104 slice 3, `folder_source.split_sections`).
SECTION_KEY = "section"


@_under_episode_lock
def set_file_record(path: Path, *, replaced: list[dict], held_gone_at: str | None) -> bool:
    """The meeting's file record (:data:`REPLACED_KEY`, :data:`HELD_GONE_KEY`) set to exactly these values, an empty one
    removed. Frontmatter only: the body, its hash, the queue and every span are untouched — the words did not move.
    Returns whether the file changed."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    before = dict(fm)
    for key, value in ((REPLACED_KEY, [dict(r) for r in replaced][:MAX_REPLACED]), (HELD_GONE_KEY, held_gone_at)):
        if value:
            fm[key] = value
        else:
            fm.pop(key, None)
    if fm == before:
        return False
    if "turns" in fm:
        fm["turns"] = fm.pop("turns")  # R-PB4: the sidecar stays the last key
    markdown_parser.write(path, fm, parsed.body)
    return True


#: ROR-15 (owner 2026-11-05): an Apple Note the person pinned in Notes. Sleep's Stage 1 says so in the note's source
#: note and the model judges what it means; it is no signal of its own and no part of the note's words.
PINNED_KEY = "pinned"


@_under_episode_lock
def set_pinned(path: Path, pinned: bool) -> bool:
    """A pin changed in Notes: the one frontmatter key (`PINNED_KEY`), set or removed. The body, ``content_hash``,
    ``processed``, ``revised`` and every span are untouched, because the words did not move — so a pin never re-queues
    a note Sleep read, and a note Sleep has not read yet is read the same as before. Returns whether the file changed."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    if bool(fm.get(PINNED_KEY)) == pinned:
        return False
    if pinned:
        fm[PINNED_KEY] = True
    else:
        fm.pop(PINNED_KEY, None)
    markdown_parser.write(path, fm, parsed.body)
    return True


@_under_episode_lock
def add_contribution(path: Path, entry: dict, *, content_sha: str) -> bool:
    """An agent's edit recorded AFTER the folder sync staged its bytes (`source_edits.attach`): ``entry`` joins the
    episode's ``contributions``. Frontmatter only — the body, its hash, the queue and every span are untouched. Refused
    (``False``) when the episode no longer holds ``content_sha``'s bytes (a later edit moved on: the record would
    describe a body that is gone) and when the entry is already there."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    if fm.get("content_sha") != content_sha or entry.get("content_hash") != fm.get("content_hash"):
        return False
    before = list(fm.get(CONTRIBUTIONS_KEY) or [])
    with_contributions(fm, [entry])
    if fm.get(CONTRIBUTIONS_KEY) == before:
        return False
    if "turns" in fm:
        fm["turns"] = fm.pop("turns")  # R-PB4: the sidecar stays the last key
    markdown_parser.write(path, fm, parsed.body)
    return True


@_under_episode_lock
def adopt_source(path: Path, source_id: str) -> bool:
    """An episode written before its source had a stager identity takes one (Apple Notes, 2026-11-23): the one
    frontmatter key ``source_id``, so the next :func:`stage` of that source finds this episode and edits it in place
    instead of minting another. The body, ``content_hash``, ``processed``, ``revised`` and every span are untouched.
    An episode that already has one keeps it. Returns whether the file changed."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    if fm.get("source_id"):
        return False
    fm["source_id"] = source_id
    markdown_parser.write(path, fm, parsed.body)
    return True


@_under_episode_lock
def _set_extras(path: Path, extras: dict) -> None:
    """Same words, new extras (a reaction, an unsend, a reply's target): frontmatter only — the body, its hash, every
    evidence span and the queue are untouched, because nothing anyone said moved."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    _apply_extras(fm, extras)
    markdown_parser.write(path, fm, parsed.body)


@_under_episode_lock
def _set_meta(path: Path, values: dict) -> None:
    """Same words, new writer-owned frontmatter (a provider's project grouping): the body, its hash, every span and
    the queue are untouched."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm.update(stored_meta(values))
    markdown_parser.write(path, fm, parsed.body)


def _remember_source(fm: dict, old_sid: str) -> None:
    previous = [s for s in (fm.get("previous_source_ids") or []) if s]
    if old_sid not in previous:
        previous.append(old_sid)
    fm["previous_source_ids"] = previous


@_under_episode_lock
def _repoint(path: Path, draft: EpisodeDraft, old_sid: str) -> None:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    _remember_source(fm, old_sid)
    fm["source_id"] = draft.source_id
    fm["source_updated_at"] = draft.source_updated_at
    if draft.content_sha:
        fm["content_sha"] = draft.content_sha     # a rename keeps its bytes; a takeover (`replaces`) brings its own
    if draft.title:
        fm["title"] = _title(draft)
    fm.pop("source_deleted_at", None)
    fm.pop(HELD_GONE_KEY, None)
    fm.update(_extra(draft))
    _requeue_for_authorship(fm, draft)
    _apply_extras(fm, _extras_matching(draft, parsed.body))
    markdown_parser.write(path, fm, parsed.body)


def mark_removed(path: Path, at: str | None) -> bool:
    """The person removed this bookmark in Cicada (G191 v3, ``bookmark_forget``): stamp ``source_deleted_at`` — the
    tombstone every source-keyed writer uses, never an unlink — or, with ``at`` None, clear it (the link was saved
    again). Frontmatter only: the body, its hash and every evidence span stay; the queue is untouched. Returns whether
    the file changed."""
    with STAGE_LOCK, episode_ids.episode_lock(Path(path).parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        if bool(fm.get("source_deleted_at")) == (at is not None):
            return False
        if at is None:
            fm.pop("source_deleted_at", None)
        else:
            fm["source_deleted_at"] = at
        if "turns" in fm:
            fm["turns"] = fm.pop("turns")  # R-PB4: the sidecar stays the last key
        markdown_parser.write(path, fm, parsed.body)
        return True


def keep_turns_last(fm: dict) -> None:
    """R-PB4: the sidecar stays the last key, for a writer that just added one (G235's record)."""
    if "turns" in fm:
        fm["turns"] = fm.pop("turns")


def is_deleted_unread(fm: dict) -> bool:
    """A tombstoned episode no model or agent ever consolidated and that still waits: its source went before it was
    read, so there is nothing to read. An episode consolidated earlier and edited since (``revised.consolidated_hash``)
    already taught Sleep something and is left to the revision rule (ruling 75)."""
    revised = fm.get(REVISED_KEY) if isinstance(fm.get(REVISED_KEY), dict) else {}
    # A read the person's own words owe (a woken save, a reason they gave; ruling 62) is never taken back by a deletion,
    # and neither is the person's own authored note (rulings 13/16): only a meeting, or words that are not the person's.
    own = fm.get("evidence_kind") == "user" and not isinstance(fm.get("meeting"), dict)
    return (bool(fm.get("source_deleted_at")) and not fm.get("processed") and not revised.get("consolidated_hash")
            and not history_index.owes_a_read(fm) and not own)


def _settle_deleted_unread(fm: dict) -> bool:
    if not is_deleted_unread(fm):
        return False
    fm["processed"] = True
    fm["processed_by"] = DELETED_UNREAD
    return True


@_under_episode_lock
def _tombstone(path: Path, at: str) -> None:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["source_deleted_at"] = at
    _settle_deleted_unread(fm)   # deleted before anything read it: nothing to consolidate, nothing waiting
    if "turns" in fm:
        fm["turns"] = fm.pop("turns")  # R-PB4: the sidecar stays the last key
    markdown_parser.write(path, fm, parsed.body)


def settle_deleted_unread(path: Path) -> bool:
    """An episode tombstoned before this rule (still ``processed: false``) leaves the queue the same way. Checked under
    the stage lock (a source posted again runs under it), then written by :func:`_tombstone` with its own stamp kept;
    returns whether the file changed. Frontmatter only — the body, hash and every span stay."""
    with STAGE_LOCK:
        fm = markdown_parser.parse(path).frontmatter
        if not is_deleted_unread(fm):
            return False
        _tombstone(path, str(fm["source_deleted_at"]))
        return True


def _mark(result: StageResult, verb: str, sid: str, entry: IndexEntry, episodes_dir: Path) -> None:
    setattr(result, verb, getattr(result, verb) + 1)
    result.verdicts.append(verb)
    result.episode_ids[sid] = entry.id
    result.touched[sid] = entry.id
    result.paths.append(_rel(entry.path, episodes_dir))


#: Called once per draft, after its verdict is on disk: ``progress(verb)``.
Progress = Callable[[str], None]


def stage(drafts: Iterable[EpisodeDraft], episodes_dir: Path, *,
          deleted_source_ids: Iterable[str] = (), bank: str | None = None,
          progress: Progress | None = None) -> StageResult:
    """Create / skip / update / rename / tombstone, delta-aware by ``source_id``.

    A draft WITHOUT a ``source_id`` keeps the pre-G20 content-hash behaviour
    exactly (create or skip, never update). Runs under ``STAGE_LOCK``.

    ``progress`` is the intake job's counter (Track I T2b): a large import
    stages in ONE call and reports per draft, instead of one call per batch —
    each call scans the bank, and per-batch calls measured 177 s for 1,000
    threads into a 2,000-episode bank against 9.9 s as one call (Track I final
    review, finding 2)."""
    with STAGE_LOCK:
        return _stage_locked(list(drafts), episodes_dir,
                             deleted_source_ids=list(deleted_source_ids), bank=bank,
                             progress=progress)


def plan(drafts: Iterable[EpisodeDraft], episodes_dir: Path) -> StageResult:
    """What ``stage`` WOULD do, writing nothing — the intake preview's
    new · grown · already-here (Track I T2, R-IA5).

    The same loop as ``stage`` with every write skipped, not a mirror of it:
    the branch-local mirror this replaced hashed the RAW body while the stager
    compares the scrubbed digest or the legacy raw one, so any thread a scrub
    rule touched previewed as "grew" and then staged as a skip (Track I final
    review, finding 1). No lock — nothing is minted or written — no directory
    is created and no scrub telemetry is recorded: a sniff runs on every drop."""
    return _stage_locked(list(drafts), episodes_dir, deleted_source_ids=[], bank=None, dry_run=True)


def _stage_locked(drafts: list[EpisodeDraft], episodes_dir: Path, *,
                  deleted_source_ids: list[str], bank: str | None,
                  dry_run: bool = False, progress: Progress | None = None) -> StageResult:
    write = not dry_run
    if write:
        episodes_dir.mkdir(parents=True, exist_ok=True)
    index, known_hashes = scan(episodes_dir)
    date_counts = episode_ids.max_suffix_by_date(episodes_dir)
    result = StageResult()
    now = episode_ids.utc_now_iso()
    deleted = list(dict.fromkeys(s for s in deleted_source_ids if s))
    renames: dict[tuple[str, str], str] = {}
    for sid in deleted:
        entry = index.get(sid)
        sha = entry.fm.get("content_sha") if entry else None
        if sha:
            renames.setdefault((str(sha), _fragment(sid)), sid)

    writer = "import"
    relays: dict[tuple[str, str], list[IndexEntry]] | None = None
    for draft in drafts:
        writer = draft.writer
        # G235: the person took text out of this conversation; a source sending it again never brings it back.
        known = index.get(draft.source_id) if draft.source_id else None
        if known is None and draft.replaces:
            known = next((index[s] for s in draft.replaces if s in index), None)   # the episode it takes over
        if known is not None and sensitive_flags.removed_kinds(known.fm):
            draft = sensitive_flags.reapply_draft(draft, known.fm)
        body, stamps, n = render(draft)
        result.scrubbed += n
        digest = content_hash(body)
        legacy = content_hash(_raw_render(draft))
        sid = draft.source_id
        if sid:
            entry = index.get(sid)
            if draft.replaces:
                held_sid = next((s for s in draft.replaces if s != sid and s in index), None)
                if held_sid is not None:
                    entry = index.pop(held_sid)
                    if held_sid in deleted:
                        deleted.remove(held_sid)   # the episode it was about to tombstone is the one this draft takes
                    same_body = entry.fm.get("content_hash") in (digest, legacy)
                    if write:
                        if same_body:
                            _repoint(entry.path, draft, held_sid)
                        else:
                            update_in_place(entry.path, draft, body, digest, stamps, previous_sid=held_sid)
                    known_hashes.add(digest)
                    entry.fm.update(source_id=sid, source_updated_at=draft.source_updated_at,
                                    evidence_kind=draft.extra.get("evidence_kind"))
                    if not same_body:
                        entry.fm["content_hash"] = digest
                    if draft.content_sha:
                        entry.fm["content_sha"] = draft.content_sha
                    entry.fm.pop("source_deleted_at", None)
                    entry.fm.pop(HELD_GONE_KEY, None)
                    if draft.redate and _moved(entry.fm.get("timestamp"), draft.timestamp):
                        if write:
                            _redate(entry.path, draft, stamps)
                        entry.fm["timestamp"] = draft.timestamp
                    index[sid] = entry
                    result.replaced_sources.append((held_sid, sid))
                    _mark(result, "updated", sid, entry, episodes_dir)
                    _report(progress, "updated")
                    continue
            if entry is None and draft.content_sha:
                old = renames.pop((draft.content_sha, _fragment(sid)), None)
                if old is not None and old in index:
                    entry = index.pop(old)
                    deleted.remove(old)
                    if write:
                        _repoint(entry.path, draft, old)
                    entry.fm.update(source_id=sid, evidence_kind=draft.extra.get("evidence_kind"))
                    entry.fm.pop("source_deleted_at", None)
                    index[sid] = entry
                    result.renamed_sources.append((old, sid))
                    _mark(result, "renamed", sid, entry, episodes_dir)
                    _report(progress, "renamed")
                    continue
            if entry is None and draft.source in RELAY_UPGRADES:
                if relays is None:
                    relays = relay_candidates(episodes_dir)
                relayed = relay_for(draft, relays)
                if relayed is not None:
                    if write:
                        upgrade_relay(relayed.path, draft, body, digest, stamps, now)
                    for bucket in relays.values():
                        if relayed in bucket:
                            bucket.remove(relayed)
                    known_hashes.add(digest)
                    entry = IndexEntry(path=relayed.path, id=relayed.id, fm={"content_hash": digest})
                    index[sid] = entry
                    _mark(result, "updated", sid, entry, episodes_dir)
                    _report(progress, "updated")
                    continue
            if entry is None:
                path = (write_new(draft, episodes_dir, body, digest, stamps, date_counts) if write
                        else _planned_path(episodes_dir, draft, date_counts))
                known_hashes.add(digest)
                entry = IndexEntry(path=path, id=path.stem, fm={
                    "content_hash": digest, "content_sha": draft.content_sha,
                    "evidence_kind": draft.extra.get("evidence_kind")})
                index[sid] = entry
                _mark(result, "created", sid, entry, episodes_dir)
                _report(progress, "created")
                continue
            # Ruling 58: what an export is compared with is what an export wrote, never the later turns after it.
            tail = has_relayed_tail(entry.fm)
            same_body = entry.fm.get("content_hash") in (digest, legacy) or (
                tail and entry.fm["relay"]["imported_hash"] in (digest, legacy))
            same_meta = (entry.fm.get("evidence_kind") == draft.extra.get("evidence_kind")
                         and not entry.fm.get("source_deleted_at"))
            redated = draft.redate and _moved(entry.fm.get("timestamp"), draft.timestamp)
            if same_body and same_meta and not redated:
                if draft.content_sha and entry.fm.get("content_sha") != draft.content_sha:
                    # An unchanged H2 section of an edited file: its words did not
                    # move, but the file's hash did. Restamp it (no re-queue) or a
                    # later rename could not match it by (sha, fragment) (R-LS12).
                    if write:
                        _restamp(entry.path, draft)
                    entry.fm["content_sha"] = draft.content_sha
                    result.restamped += 1
                    result.paths.append(_rel(entry.path, episodes_dir))
                title = _title(draft)
                if title and entry.fm.get("title") and entry.fm.get("title") != title:
                    # ROR-122: the source renamed it and no word moved: the new title shows; nothing is re-queued (the
                    # title is outside the hash), and what the old one said stays in git.
                    if write:
                        _set_meta(entry.path, {"title": title})
                    entry.fm["title"] = title
                    if (rel := _rel(entry.path, episodes_dir)) not in result.paths:
                        result.paths.append(rel)
                grouping = stored_meta({PROVIDER_PROJECT_KEY: draft.extra.get(PROVIDER_PROJECT_KEY)})[
                    PROVIDER_PROJECT_KEY]   # as stored, or a scrubbed name rewrites every sync
                if grouping and entry.fm.get(PROVIDER_PROJECT_KEY) != grouping:
                    # Ruling 45: the provider's project grouping arrived (or moved) and no word did: frontmatter only.
                    if write:
                        _set_meta(entry.path, {PROVIDER_PROJECT_KEY: grouping})
                    entry.fm[PROVIDER_PROJECT_KEY] = grouping
                    if (rel := _rel(entry.path, episodes_dir)) not in result.paths:
                        result.paths.append(rel)
                filing = stored_meta({k: draft.extra[k] for k in FILING_KEYS if draft.extra.get(k)})
                if filing := {k: v for k, v in filing.items() if entry.fm.get(k) != v}:
                    # G245: the source's filing (a Notion page's parents or database) arrived or moved and no word did.
                    if write:
                        _set_meta(entry.path, filing)
                    entry.fm.update(filing)
                    if (rel := _rel(entry.path, episodes_dir)) not in result.paths:
                        result.paths.append(rel)
                extras = render_extras(draft, raw=not tail and entry.fm.get("content_hash") != digest)
                if extras != turn_extras.stored(entry.fm):
                    # A reaction, an unsend or a reply's target moved and no word did (turn_extras): frontmatter only.
                    if write:
                        _set_extras(entry.path, extras)
                    turn_extras.apply(entry.fm, extras)
                    result.extras_updated += 1
                    if (rel := _rel(entry.path, episodes_dir)) not in result.paths:
                        result.paths.append(rel)
                result.skipped += 1
                result.verdicts.append("skipped")
                result.episode_ids[sid] = entry.id
                _report(progress, "skipped")
                continue
            if same_body and write:
                _refresh(entry.path, draft)
            elif not same_body:
                merged = digest
                if write and tail:
                    merged = merge_relayed_tail(entry.path, draft, body, digest, stamps)
                elif write:
                    update_in_place(entry.path, draft, body, digest, stamps)
                known_hashes.add(digest)
                entry.fm["content_hash"] = merged
            if redated:
                if write:
                    _redate(entry.path, draft, stamps)
                entry.fm["timestamp"] = draft.timestamp
            entry.fm["evidence_kind"] = draft.extra.get("evidence_kind")
            entry.fm.pop("source_deleted_at", None)
            _mark(result, "updated", sid, entry, episodes_dir)
            _report(progress, "updated")
            continue
        if digest in known_hashes or legacy in known_hashes:
            result.skipped += 1
            result.verdicts.append("skipped")
            _report(progress, "skipped")
            continue
        path = (write_new(draft, episodes_dir, body, digest, stamps, date_counts) if write
                else _planned_path(episodes_dir, draft, date_counts))
        known_hashes.add(digest)
        result.created += 1
        result.verdicts.append("created")
        result.paths.append(_rel(path, episodes_dir))
        _report(progress, "created")

    for sid in deleted:
        entry = index.get(sid)
        if entry is None or entry.fm.get("source_deleted_at"):
            continue
        if write:
            _tombstone(entry.path, now)
        entry.fm["source_deleted_at"] = now
        _settle_deleted_unread(entry.fm)
        result.tombstoned += 1
        result.tombstoned_sources[sid] = entry.id
        result.paths.append(_rel(entry.path, episodes_dir))
    if write:
        episode_scrub.record(writer, result.scrubbed, bank=bank)
    return result


def _planned_path(episodes_dir: Path, draft: EpisodeDraft, date_counts: dict[str, int]) -> Path:
    """The file ``write_new`` would mint for ``draft`` — ``plan`` bumps the same
    per-date counter so its ``paths`` and ids read like a real run's."""
    ep_date = draft.original_date or datetime.now().strftime("%Y-%m-%d")
    date_counts[ep_date] = date_counts.get(ep_date, 0) + 1
    return episodes_dir / f"ep_{ep_date}_{date_counts[ep_date]:03d}.md"


def _report(progress: Progress | None, verb: str) -> None:
    if progress is not None:
        progress(verb)
