"""G136 — the derived full-text index: SQLite FTS5 beside the vector index.

Round-3 spec decision 7 and design §3.9 item 3. The vector index answers
"what is this *like*"; nothing answered "where did I *type* this" — the
keyword legs were whole-query substring scans that never read ``aliases``
(R3 P1), the ``/search`` fallback re-parsed every entity file per request
(R6 §4.2), and no path searched claims or conversation text at all. This
module is the lexical half: one SQLite database of FTS5 tables over entity
names + aliases + prose, claims (current AND superseded, so a query can show
"was X until <date>", R3 P4), episode titles + passages with offsets into
the evidence text (G118), media/paper metadata, and inbox questions.

Rails this module enforces rather than documents:

* **Derived and disposable** (TODO ruling 3). Markdown+git is the only
  truth; every row here is recomputed from a file. Deleting
  ``search_index.db`` costs one rebuild (3–6 s of CPU for 2,000 entities and
  1,500 episodes, measured 2026-09-23) and never a fact. A missing, corrupt
  or schema-mismatched file is rebuilt, never an error.
* **Never tracked** (G99a). The file lives in the bank directory beside
  ``vector_index.db`` — the caller passes the ACTIVE bank's path; this
  module never resolves a bank itself (the split-brain rule) — and
  ``bank_registry.ensure_derived_excluded`` writes ``.git/info/exclude``
  before the file is first created, so ``git add -A`` can never sweep it.
* **Engine-free.** No LLM, no embedding: tokenising is SQLite's own
  ``unicode61 remove_diacritics 2``, the same fold ``text_fold`` applies to
  the query side.
* **The query never persists.** Nothing here logs or stores query text (K9).

Freshness (G136 R3): Sleep rebuilds the whole file beside the vector index;
between cycles every read path calls :func:`ensure_fresh`, which compares
``bank_index``'s ``(mtime_ns, size)`` stamps (one ``scandir`` per directory,
~6 ms warm at 3,500 files) with the stamps recorded here and re-indexes only
what moved — throttled to one check per ``STALENESS_TTL_S``. A burst larger
than ``INLINE_REFRESH_LIMIT`` documents goes to a single background worker so
a keystroke never waits on a bulk import.

Row ids (G136 R5): every FTS row's rowid is ``doc_id << 16 | n``, where
``doc_id`` is the ``docs`` row of the file it came from. A document's rows
are therefore one contiguous rowid range (delete is a range scan), a passage
knows its episode without reading a column (``rowid >> 16`` — which is what
makes the distinct-episode count 2 ms instead of 33 ms), and because a
re-indexed document is re-inserted with a fresh, larger ``doc_id``,
``ORDER BY rowid DESC`` is "most recently written first" for free.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import (bank_index, bank_registry, episode_ids, evidence, fact_sources, inbox_questions,
                          markdown_parser, text_fold)
from api.services.claims import is_event, is_record, parse_claims, strip_claims_block
from api.services.graph_builder import summarize

DB_FILE = "search_index.db"
# "2": withdrawal records (G140 Q-R5) are no longer indexed as claims. A bump
# rebuilds every existing index on its next open, so a record indexed under
# "1" stops surfacing without anyone deleting the file (final review).
# "3": G141 — `status` in the claim payload so an event hit renders as a dated
# happening (R-PJB11); the bump rebuilds every index once (TODO ruling 3).
SCHEMA_VERSION = "3"
TOKENIZER = "unicode61 remove_diacritics 2"
# Prefix indexes for 2-, 3- and 4-character prefixes: type-as-you-go queries
# are mostly that short, and a prefix with no index is a range scan over
# every matching term (adding the 4 cut the 4-character p95 from 22 to 16 ms
# in the layout experiment, 2026-09-23).
PREFIX = "2 3 4"
# Passage size for episode text. Short enough that a hit's span highlights a
# paragraph, not a page; long enough that 1,500 episodes stay ~25k rows.
PASSAGE_CHARS = 600
# Prose indexed per entity / media page. A page longer than this is still
# found by its name, aliases, tags and first 8,000 characters.
BODY_CHARS = 8000
STALENESS_TTL_S = 1.0
INLINE_REFRESH_LIMIT = 64
ROW_BITS = 16
MAX_ROWS_PER_DOC = (1 << ROW_BITS) - 1
INDEXED_SUBDIRS = ("entities", "inbox", "episodes")

# Column layout per table. `bm25()` weights are positional over ALL columns,
# UNINDEXED ones included — `WEIGHTS` is the one place they are written, and
# they mirror QuickMatch's field weights ×10 (title 1.0, alias 0.9,
# keyword 0.7, body 0.4; design §1.2).
_FTS_COLUMNS = {
    "ent": "title, aliases, keywords, body",
    "med": "title, aliases, keywords, body",
    "clm": "title, aliases, keywords, payload UNINDEXED",
    "epi": "title, keywords",
    "pas": "body, s UNINDEXED, e UNINDEXED",
    "inb": "title, aliases, keywords, body",
}
WEIGHTS = {
    "ent": "10.0, 9.0, 7.0, 4.0",
    "med": "10.0, 9.0, 7.0, 4.0",
    "clm": "10.0, 9.0, 7.0, 0.0",
    "epi": "10.0, 7.0",
    "pas": "4.0, 0.0, 0.0",
    "inb": "10.0, 9.0, 7.0, 4.0",
}

_FTS5: bool | None = None


def db_path(memory_path: Path) -> Path:
    return Path(memory_path) / DB_FILE


def fts5_available() -> bool:
    """Whether this Python's SQLite was compiled with FTS5 (checked once)."""
    global _FTS5
    if _FTS5 is None:
        try:
            conn = sqlite3.connect(":memory:")
            try:
                conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
                _FTS5 = True
            finally:
                conn.close()
        except sqlite3.Error:
            _FTS5 = False
    return _FTS5


def _schema_tag() -> str:
    # Any change to how rows are cut or tokenised invalidates the file.
    return f"{SCHEMA_VERSION}|{TOKENIZER}|{PREFIX}|{PASSAGE_CHARS}|{BODY_CHARS}"


def match_expression(tokens: list[str]) -> str:
    """FTS5 MATCH text: every token a quoted prefix term, implicit AND.

    Tokens come from ``text_fold.query_tokens`` (alphanumeric only), and the
    quotes make FTS5 read ``AND``/``OR``/``NEAR`` as words, never operators.
    """
    return " ".join(f'"{tok}"*' for tok in tokens)


def passage_spans(body: str, cap: int = PASSAGE_CHARS) -> list[tuple[int, int]]:
    """Contiguous ``(start, end)`` windows that tile ``body`` exactly.

    Offsets are into the episode's evidence text (``parse(...).body``, R1 of
    G118), so ``body[start:end]`` IS the passage and ``/episodes/{id}/span``
    can verify it. A window prefers to end just after a newline in its last
    200 characters (a turn boundary), then after a space, then hard. No
    overlap and no gap: ``"".join(body[s:e] for s, e in spans) == body``,
    which is what lets a semantic chunk be located exactly (search_service).
    """
    spans: list[tuple[int, int]] = []
    start, n = 0, len(body or "")
    while start < n:
        end = min(n, start + cap)
        if end < n:
            cut = body.rfind("\n", max(start + 1, end - 200), end)
            if cut == -1:
                cut = body.rfind(" ", max(start + 1, end - 200), end)
            if cut > start:
                end = cut + 1
        spans.append((start, end))
        start = end
    return spans


def _open(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _discard_files(db: Path) -> None:
    """Remove the db AND its WAL/shm siblings — a fresh file next to a stale
    ``-wal`` is how a SQLite database gets corrupted."""
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(f"{db}{suffix}").unlink()
        except FileNotFoundError:
            pass


# --- per-bank process state ---------------------------------------------------


@dataclass
class _BankState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    # doc_key -> (mtime_ns, size) of what the index holds; None = not loaded
    # (or no usable file). Replaced wholesale, never mutated in place, so a
    # reader iterating it never sees it change underneath.
    stamps: dict[str, tuple[int, int]] | None = None
    checked_at: float = float("-inf")
    worker: threading.Thread | None = None


_STATES: dict[str, _BankState] = {}
_STATES_LOCK = threading.Lock()


def _state(memory_path: Path) -> _BankState:
    with _STATES_LOCK:
        return _STATES.setdefault(str(Path(memory_path)), _BankState())


def reset(memory_path: Path | None = None) -> None:
    """Forget cached process state (tests; never needed in production)."""
    with _STATES_LOCK:
        if memory_path is None:
            _STATES.clear()
        else:
            _STATES.pop(str(Path(memory_path)), None)


def invalidate(memory_path: Path) -> None:
    """A reader hit a broken file: the next ``ensure_fresh`` reloads it, and
    a load that fails rebuilds it."""
    _state(memory_path).stamps = None


# --- scanning -----------------------------------------------------------------


def _scan(memory_path: Path) -> dict[str, bank_index.IndexedFile]:
    out: dict[str, bank_index.IndexedFile] = {}
    for subdir in INDEXED_SUBDIRS:
        for f in bank_index.files(memory_path, subdir):
            if subdir == "inbox" and not f.path.name.startswith("inbox-"):
                continue
            out[f"{subdir}/{f.path.name}"] = f
    return out


def _diff(memory_path: Path, stamps: dict[str, tuple[int, int]]):
    current = _scan(memory_path)
    changed = {k: f for k, f in current.items() if stamps.get(k) != (f.mtime_ns, f.size)}
    removed = [k for k in stamps if k not in current]
    return changed, removed


def _ordered(files: dict[str, bank_index.IndexedFile]) -> list[tuple[str, bank_index.IndexedFile]]:
    """Entities, then inbox, then episodes oldest-first — so a full build
    hands the newest conversation the largest ``doc_id`` and prefix mode's
    ``ORDER BY rowid DESC`` starts from the most recent one."""
    def key(item):
        doc_key, f = item
        subdir = doc_key.split("/", 1)[0]
        ts = episode_ids.timestamp_sort_key(f.frontmatter.get("timestamp")) if subdir == "episodes" else ""
        return (INDEXED_SUBDIRS.index(subdir), ts, doc_key)

    return sorted(files.items(), key=key)


def _load_stamps(db: Path) -> dict[str, tuple[int, int]] | None:
    if not db.exists():
        return None
    try:
        conn = _open(db)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()
            if not row or row[0] != _schema_tag():
                return None
            return {k: (m, s) for k, m, s in conn.execute("SELECT doc_key, mtime_ns, size FROM docs")}
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return None


# --- writing ------------------------------------------------------------------


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE docs (id INTEGER PRIMARY KEY, doc_key TEXT NOT NULL UNIQUE, "
        "kind TEXT NOT NULL, ref TEXT NOT NULL, mtime_ns INTEGER NOT NULL, "
        "size INTEGER NOT NULL, meta TEXT NOT NULL)"
    )
    conn.execute("CREATE INDEX docs_by_ref ON docs(kind, ref)")
    conn.execute("CREATE TABLE claim_ref (claim_id TEXT PRIMARY KEY, row INTEGER NOT NULL)")
    conn.execute("CREATE INDEX claim_ref_by_row ON claim_ref(row)")
    # Every evidence SPAN of every claim (G118), keyed by the episode it
    # points into — design §3.9 item 3's `claims(…, evidence_episode, start,
    # end, kind, hash)`, and what `GET /episodes/{id}/citations` (Track P, P4)
    # reads instead of parsing every page that might cite an episode.
    conn.execute(
        "CREATE TABLE claim_evidence (row INTEGER NOT NULL, episode TEXT NOT NULL, "
        "s INTEGER NOT NULL, e INTEGER NOT NULL, kind TEXT NOT NULL, hash TEXT NOT NULL)"
    )
    conn.execute("CREATE INDEX claim_evidence_by_episode ON claim_evidence(episode)")
    conn.execute("CREATE INDEX claim_evidence_by_row ON claim_evidence(row)")
    for table, columns in _FTS_COLUMNS.items():
        conn.execute(
            f"CREATE VIRTUAL TABLE {table} USING fts5({columns}, "
            f"tokenize='{TOKENIZER}', prefix='{PREFIX}')"
        )


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v or "").strip()]


def _float(value) -> float:
    # A hand-edited `confidence: high` must not cost the page its row.
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _insert_doc(conn, doc_key: str, kind: str, ref: str, f, meta: dict) -> int:
    cur = conn.execute(
        "INSERT INTO docs(doc_key, kind, ref, mtime_ns, size, meta) VALUES (?, ?, ?, ?, ?, ?)",
        (doc_key, kind, ref, f.mtime_ns, f.size, json.dumps(meta, default=str)),
    )
    return int(cur.lastrowid)


def _index_entity(conn, doc_key: str, f, fm: dict, body: str) -> None:
    ref = f.path.stem
    prose = strip_claims_block(body)
    etype = str(fm.get("type", "concept") or "concept")
    name = str(fm.get("name") or ref.replace("-", " ").title())
    aliases = _str_list(fm.get("aliases"))
    tags = _str_list(fm.get("tags"))
    meta = {
        "name": name,
        "type": etype,
        "status": str(fm.get("status", "active") or "active"),
        "confidence": _float(fm.get("confidence")),
        "summary": summarize(prose) or "",
        "aliases": aliases[:8],
        "tags": tags[:8],
    }
    if meta["status"] == "dropped":
        # `dropped` = user-dismissed, never resurfaced (the status lifecycle).
        # The docs row keeps the file's stamp, so the page is not re-read on
        # every freshness check, but no FTS row and no claim is written: it
        # can never match, and never inflates a `totals` count (G136 R7/R11).
        _insert_doc(conn, doc_key, "media" if etype == "media" else "entity", ref, f, meta)
        return
    if etype == "media":
        media = fm.get("media") if isinstance(fm.get("media"), dict) else {}
        # Paper metadata in the shape Track F writes (R7 §4: `paper:
        # {arxiv_id, doi, title, authors[]}`), read tolerantly so a paper
        # page is searchable by author or id the moment it exists.
        paper = fm.get("paper") if isinstance(fm.get("paper"), dict) else {}
        authors = _str_list(paper.get("authors"))
        ids = [str(paper.get(k) or "").strip() for k in ("arxiv_id", "doi")]
        site = str(media.get("site") or "")
        channel = str(media.get("channel") or "")
        meta.update(
            site=site,
            channel=channel,
            media_type=str(media.get("media_type") or ""),
            origin=str(fm.get("origin") or ""),
            saved_at=str(fm.get("saved_at") or media.get("saved_at") or ""),
            authors=authors[:6],
            paper=bool(paper) or str(media.get("kind") or "") == "paper",
        )
        doc_id = _insert_doc(conn, doc_key, "media", ref, f, meta)
        conn.execute(
            "INSERT INTO med(rowid, title, aliases, keywords, body) VALUES (?, ?, ?, ?, ?)",
            (
                doc_id << ROW_BITS,
                name,
                " ".join([*aliases, *authors, *[i for i in ids if i]]),
                " ".join(x for x in [*tags, site, channel, meta["media_type"], str(media.get("provider") or "")] if x),
                prose[:BODY_CHARS],
            ),
        )
    else:
        doc_id = _insert_doc(conn, doc_key, "entity", ref, f, meta)
        conn.execute(
            "INSERT INTO ent(rowid, title, aliases, keywords, body) VALUES (?, ?, ?, ?, ?)",
            (doc_id << ROW_BITS, name, " ".join(aliases), " ".join(tags), prose[:BODY_CHARS]),
        )
    # Claims — every one, superseded included (R3 P4: history is searchable
    # here even though the vector claims index holds current claims only).
    # Every BELIEF, that is: a withdrawal record (G140 Q-R5) is skipped, or a
    # `/search` hit named with the agent's reason rendered under "Beliefs"
    # (final review). The row number stays the fence position, so skipping
    # one never renumbers the claims after it.
    for n, claim in enumerate(parse_claims(body)[:MAX_ROWS_PER_DOC], start=1):
        text = (claim.text or "").strip()
        if not text or is_record(claim):
            continue
        spans = [e for e in claim.evidence if e.is_span()]
        first = spans[0] if spans else (claim.evidence[0] if claim.evidence else None)
        payload = {
            "id": claim.id,
            "predicate": claim.predicate,
            "object": claim.object,
            "confidence": _float(claim.confidence),
            "valid_from": claim.valid_from,
            "valid_to": claim.valid_to,
            "superseded_by": claim.superseded_by,
            "observer": claim.observer,
            "evidence": first.to_dict() if first else None,
            # G141 R-PJB11: an event keeps its state beside its day.
            "status": claim.status if is_event(claim) else None,
        }
        rowid = (doc_id << ROW_BITS) | n
        conn.execute(
            "INSERT INTO clm(rowid, title, aliases, keywords, payload) VALUES (?, ?, ?, ?, ?)",
            (rowid, text, name, f"{claim.predicate} {claim.object}".strip(), json.dumps(payload, default=str)),
        )
        if claim.id:
            conn.execute("INSERT OR REPLACE INTO claim_ref(claim_id, row) VALUES (?, ?)", (claim.id, rowid))
        for ev in spans:
            conn.execute(
                "INSERT INTO claim_evidence(row, episode, s, e, kind, hash) VALUES (?, ?, ?, ?, ?, ?)",
                (rowid, ev.episode, ev.start, ev.end, ev.kind, ev.hash),
            )


def _index_episode(conn, doc_key: str, f, fm: dict, body: str) -> None:
    ref = f.path.stem  # the evidence doc id (G118 R3) — the file stem, not `fm["id"]`
    meta = {
        "title": str(fm.get("title") or "").strip(),
        "harness": str(fm.get("harness") or "").strip(),
        "origin": str(fm.get("origin") or "").strip(),
        # The same identity rule as session_stats._group (G48).
        "conversation_id": (
            str(fm.get("session_id") or "").strip() or str(fm.get("source_id") or "").strip()
        ),
        "timestamp": str(fm.get("timestamp") or ""),
        "hash": evidence.body_hash(body),
        # R-LS7: a folder file's declared authorship, so a hit's kind is the
        # same `evidence.kind_for` answer a stored span carries.
        "evidence_kind": str(fm.get("evidence_kind") or "").strip(),
    }
    doc_id = _insert_doc(conn, doc_key, "episode", ref, f, meta)
    conn.execute(
        "INSERT INTO epi(rowid, title, keywords) VALUES (?, ?, ?)",
        (doc_id << ROW_BITS, meta["title"], " ".join(x for x in (meta["harness"], meta["origin"]) if x)),
    )
    for n, (s, e) in enumerate(passage_spans(body)[:MAX_ROWS_PER_DOC], start=1):
        conn.execute(
            "INSERT INTO pas(rowid, body, s, e) VALUES (?, ?, ?, ?)",
            ((doc_id << ROW_BITS) | n, body[s:e], s, e),
        )


def _index_inbox(conn, doc_key: str, f, fm: dict, body: str) -> None:
    ref = f.path.stem
    kind = str(fm.get("kind", "decay") or "decay")
    entity_id = str(fm.get("entity_id") or "")
    entity_name = str(fm.get("entity_name") or "")
    question = str(fm.get("question") or "").strip()
    if not question and kind == "decay":
        # Decay is SERVED as a question and never written as one (G115 R5);
        # index the served words, from the one function that composes them.
        question = inbox_questions.decay_question(entity_name or entity_id, None, str(date.today()))["question"]
    title = question or str(fm.get("title") or entity_name or "")
    meta = {
        "question": title,
        "kind": kind,
        "entity_id": entity_id,
        "entity_name": entity_name,
        "status": str(fm.get("status", "pending") or "pending"),
        "priority": _float(fm.get("priority")),
        "remind_after": str(fm.get("remind_after") or "") or None,
    }
    # G61 phase 2 S0 (R-AC23): the served hint, derived at index time — only a
    # conflict derives one, so only a conflict reads its subject page (an inbox
    # of thousands of decay items costs no extra parse). A source added later
    # reaches this row at the next rebuild.
    sources = fact_sources.list_sources(f.path.parents[1], entity_id) if kind == "conflict" else None
    hint = fact_sources.served_hint(fm, sources) or ""
    doc_id = _insert_doc(conn, doc_key, "inbox", ref, f, meta)
    conn.execute(
        "INSERT INTO inb(rowid, title, aliases, keywords, body) VALUES (?, ?, ?, ?, ?)",
        (
            doc_id << ROW_BITS,
            title,
            entity_name,
            " ".join(x for x in (kind, str(fm.get("predicate") or "")) if x),
            hint,
        ),
    )


_INDEXERS = {"entities": _index_entity, "episodes": _index_episode, "inbox": _index_inbox}


def _index_doc(conn, doc_key: str, f) -> None:
    """Index one file inside a savepoint: a page that cannot be read or
    indexed is skipped with its partial rows rolled back — one odd file never
    costs the whole build (and never loops a rebuild on every request)."""
    try:
        parsed = markdown_parser.parse(f.path)
    except Exception as exc:
        logger.warning(f"search_index: skipping unreadable {doc_key}: {type(exc).__name__}")
        return
    conn.execute("SAVEPOINT doc")
    try:
        _INDEXERS[doc_key.split("/", 1)[0]](conn, doc_key, f, parsed.frontmatter or {}, parsed.body)
    except Exception as exc:
        conn.execute("ROLLBACK TO doc")
        logger.warning(f"search_index: skipping {doc_key}: {type(exc).__name__}")
    conn.execute("RELEASE doc")


def _delete_doc(conn, doc_key: str) -> None:
    # By doc_key, read inside the transaction — never by a cached id — so two
    # processes refreshing the same file can never leave duplicate rows.
    row = conn.execute("SELECT id FROM docs WHERE doc_key = ?", (doc_key,)).fetchone()
    if row is None:
        return
    lo = int(row[0]) << ROW_BITS
    hi = lo | MAX_ROWS_PER_DOC
    for table in _FTS_COLUMNS:
        conn.execute(f"DELETE FROM {table} WHERE rowid BETWEEN ? AND ?", (lo, hi))
    conn.execute("DELETE FROM claim_ref WHERE row BETWEEN ? AND ?", (lo, hi))
    conn.execute("DELETE FROM claim_evidence WHERE row BETWEEN ? AND ?", (lo, hi))
    conn.execute("DELETE FROM docs WHERE id = ?", (row[0],))


def _write(db: Path, fn) -> None:
    conn = _open(db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            fn(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _full_build(memory_path: Path, state: _BankState) -> int:
    db = db_path(memory_path)
    # Excluded BEFORE the file can exist: the order is the whole rail (G99a).
    bank_registry.ensure_derived_excluded(memory_path)
    files = _scan(memory_path)

    def build(conn):
        for table in (*_FTS_COLUMNS, "claim_ref", "claim_evidence", "docs", "meta"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        _create_schema(conn)
        for doc_key, f in _ordered(files):
            _index_doc(conn, doc_key, f)
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema', ?)", (_schema_tag(),))

    def attempt():
        conn = _open(db)
        try:
            conn.execute("PRAGMA journal_mode=WAL").fetchone()
        finally:
            conn.close()
        _write(db, build)

    try:
        attempt()
    except sqlite3.OperationalError:
        raise  # locked or busy: a real, valid file — never discard it
    except sqlite3.DatabaseError:
        # Not a database, or damaged: disposable means start over.
        _discard_files(db)
        attempt()
    state.stamps = {k: (f.mtime_ns, f.size) for k, f in files.items()}
    state.checked_at = time.monotonic()
    logger.info(f"search_index: rebuilt ({len(files)} documents)")
    return len(files)


def _refresh(memory_path: Path, state: _BankState, changed: dict, removed: list[str]) -> None:
    def apply(conn):
        for doc_key in [*removed, *changed]:
            _delete_doc(conn, doc_key)
        for doc_key, f in _ordered(changed):
            _index_doc(conn, doc_key, f)

    _write(db_path(memory_path), apply)
    stamps = dict(state.stamps or {})
    for doc_key in removed:
        stamps.pop(doc_key, None)
    for doc_key, f in changed.items():
        stamps[doc_key] = (f.mtime_ns, f.size)
    state.stamps = stamps
    state.checked_at = time.monotonic()


# --- freshness ----------------------------------------------------------------


def _is_bank(memory_path: Path) -> bool:
    return (memory_path / "entities").is_dir() or (memory_path / "episodes").is_dir()


def ensure_fresh(memory_path: Path, *, wait: bool = False, max_age_s: float | None = None) -> str:
    """Bring the index up to date with the markdown; return its state.

    ``"ready"`` — the index matches the files (within ``max_age_s``);
    ``"stale"`` — served as-is while a background worker catches up (a bulk
    change, or a builder holds the lock); ``"building"`` — no usable index
    yet, a background build started (callers fall back to ``bank_index``);
    ``"unavailable"`` — no FTS5, not a bank, or an error (logged, never
    raised: the index must never be the reason a request fails).

    ``wait=True`` (Sleep, the background worker, tests) does all the work
    inline instead of deferring any of it.
    """
    memory_path = Path(memory_path)
    if not fts5_available() or not _is_bank(memory_path):
        return "unavailable"
    state = _state(memory_path)
    db = db_path(memory_path)
    ttl = STALENESS_TTL_S if max_age_s is None else max_age_s
    try:
        if not db.exists():
            state.stamps = None
        if state.stamps is None:
            state.stamps = _load_stamps(db)
        if state.stamps is None:
            if not wait:
                _spawn(memory_path, state)
                return "building"
            with state.lock:
                if state.stamps is None or not db.exists():
                    state.stamps = _load_stamps(db)
                    if state.stamps is None:
                        _full_build(memory_path, state)
            return "ready"
        if time.monotonic() - state.checked_at < ttl:
            return "ready"
        changed, removed = _diff(memory_path, state.stamps)
        if not changed and not removed:
            state.checked_at = time.monotonic()
            return "ready"
        if not wait and len(changed) + len(removed) > INLINE_REFRESH_LIMIT:
            _spawn(memory_path, state)
            return "stale"
        # Never queue a keystroke behind a build: a busy lock means "serve
        # what is there" (the builder will leave it fresh).
        if not state.lock.acquire(blocking=wait):
            return "stale"
        try:
            changed, removed = _diff(memory_path, state.stamps)
            if changed or removed:
                _refresh(memory_path, state, changed, removed)
            else:
                state.checked_at = time.monotonic()
        finally:
            state.lock.release()
        return "ready"
    except Exception as exc:
        logger.warning(f"search_index: freshness check failed ({type(exc).__name__}: {exc})")
        return "unavailable"


def rebuild(memory_path: Path) -> int:
    """Full rebuild — Sleep's call, beside the vector index. Raises on
    failure so the cycle can record it as an index warning."""
    memory_path = Path(memory_path)
    if not fts5_available() or not _is_bank(memory_path):
        return 0
    state = _state(memory_path)
    with state.lock:
        return _full_build(memory_path, state)


def _background(memory_path: Path) -> None:
    ensure_fresh(memory_path, wait=True, max_age_s=0)


def _spawn(memory_path: Path, state: _BankState) -> None:
    with _STATES_LOCK:
        if state.worker is not None and state.worker.is_alive():
            return
        worker = threading.Thread(
            target=_background, args=(memory_path,), name="cicada-search-index", daemon=True
        )
        state.worker = worker
    worker.start()


def warm_in_background(memory_path: Path) -> None:
    """Build or catch up off the caller's thread (lifespan, bank switch).
    Never raises, never blocks."""
    memory_path = Path(memory_path)
    if fts5_available() and _is_bank(memory_path):
        _spawn(memory_path, _state(memory_path))


def wait_idle(memory_path: Path, timeout: float = 30.0) -> bool:
    """Join the background worker, if any (tests and Sleep's hand-off)."""
    worker = _state(memory_path).worker
    if worker is not None:
        worker.join(timeout)
        return not worker.is_alive()
    return True


def claims_about(memory_path: Path, names: list[str]) -> list[tuple[str, dict]] | None:
    """`(subject page id, claim payload)` for every indexed claim whose
    `predicate object` column holds one of `names` as a phrase (G141 §6.4's
    reverse claims). A candidate list — the caller resolves the object exactly.
    `None` when no usable index answers, so the caller can fall back and say
    `partial` (§6.6); never raises."""
    state = ensure_fresh(memory_path)
    if state not in ("ready", "stale"):
        return None
    phrases = []
    for name in names:
        toks = [t for t in text_fold.words(name) if t]
        if toks:
            phrases.append('keywords : "' + " ".join(toks) + '"')
    if not phrases:
        return []
    try:
        with Reader(memory_path) as reader:
            rows = reader.conn.execute(
                f"SELECT d.ref, c.payload FROM clm c JOIN docs d ON d.id = (c.rowid >> {ROW_BITS}) "
                "WHERE clm MATCH ? ORDER BY d.ref, c.rowid", (" OR ".join(phrases),)).fetchall()
    except sqlite3.Error:
        return None
    return [(str(ref), json.loads(p or "{}")) for ref, p in rows]


def pages_citing(memory_path: Path, episode_id: str) -> list[str] | None:
    """Pages holding a claim with a SPAN into `episode_id` (R-PJB20), sorted;
    `None` when no usable index answers."""
    if ensure_fresh(memory_path) not in ("ready", "stale"):
        return None
    try:
        with Reader(memory_path) as reader:
            rows = reader.claims_citing(episode_id)
            docs = reader.docs(sorted({doc_id for doc_id, *_ in rows}))
    except sqlite3.Error:
        return None
    return sorted({d.ref for d in docs.values()})


def pages_citing_many(memory_path: Path, episode_ids: list[str]) -> dict[str, list[str]] | None:
    """`pages_citing` for many episodes through ONE reader: `{episode: sorted
    page ids}`, every asked episode present (an uncited one maps to `[]`).
    A project read asks for every moment's episode at once (R-PJB9's bench).
    `None` when no usable index answers."""
    if not episode_ids:
        return {}
    if ensure_fresh(memory_path) not in ("ready", "stale"):
        return None
    out: dict[str, set[str]] = {ep: set() for ep in episode_ids}
    try:
        with Reader(memory_path) as reader:
            for i in range(0, len(episode_ids), 500):        # SQLite's bound-parameter ceiling
                chunk = episode_ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                rows = reader.conn.execute(
                    f"SELECT DISTINCT x.episode, d.ref FROM claim_evidence x "
                    f"JOIN docs d ON d.id = (x.row >> {ROW_BITS}) WHERE x.episode IN ({marks})", chunk)
                for ep, ref in rows:
                    out.setdefault(str(ep), set()).add(str(ref))
    except sqlite3.Error:
        return None
    return {ep: sorted(refs) for ep, refs in out.items()}


# --- reading ------------------------------------------------------------------


@dataclass(frozen=True)
class Doc:
    id: int
    kind: str
    ref: str
    meta: dict


class Reader:
    """One read connection for one search. Every method returns plain rows;
    ranking, fusion and wire shapes live in ``search_service``."""

    def __init__(self, memory_path: Path):
        # `mode=rw`: a reader must never CREATE the file (a plain connect
        # would leave an empty db behind if it vanished since ensure_fresh);
        # a missing file raises here and the caller falls back.
        uri = db_path(memory_path).resolve().as_uri() + "?mode=rw"
        self.conn = sqlite3.connect(uri, uri=True, timeout=2.0, check_same_thread=False)
        self.conn.execute("PRAGMA query_only=ON")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Reader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def ranked(self, table: str, match: str, limit: int, *, recent_first: bool = False) -> list[tuple[int, float]]:
        """``[(doc_id, bm25)]`` best first — bm25 is lower-is-better. With
        ``recent_first`` (prefix mode's passage leg) rows come newest-written
        first and bm25 is not computed at all: 0.4 ms instead of 33 ms for a
        two-letter prefix over 25k passages (measured)."""
        if recent_first:
            sql = f"SELECT rowid >> {ROW_BITS}, 0.0 FROM {table} WHERE {table} MATCH ? ORDER BY rowid DESC LIMIT ?"
        else:
            sql = (
                f"SELECT rowid >> {ROW_BITS}, bm25({table}, {WEIGHTS[table]}) AS r "
                f"FROM {table} WHERE {table} MATCH ? ORDER BY r LIMIT ?"
            )
        return [(int(i), float(r)) for i, r in self.conn.execute(sql, (match, int(limit)))]

    def count(self, table: str, match: str) -> int:
        return int(self.conn.execute(f"SELECT count(*) FROM {table} WHERE {table} MATCH ?", (match,)).fetchone()[0])

    def count_episodes(self, match: str) -> int:
        """Distinct episodes matched by title OR passage — read off rowids,
        never a column (2 ms at a two-letter prefix, measured)."""
        sql = (
            f"SELECT count(*) FROM (SELECT rowid >> {ROW_BITS} FROM pas WHERE pas MATCH ?1 "
            f"UNION SELECT rowid >> {ROW_BITS} FROM epi WHERE epi MATCH ?1)"
        )
        return int(self.conn.execute(sql, (match,)).fetchone()[0])

    def passages(self, match: str, limit: int, *, recent_first: bool) -> list[tuple[int, int, int, int, float]]:
        """``[(rowid, doc_id, start, end, bm25)]`` for matching passages."""
        if recent_first:
            sql = (
                f"SELECT rowid, rowid >> {ROW_BITS}, s, e, 0.0 FROM pas WHERE pas MATCH ? "
                f"ORDER BY rowid DESC LIMIT ?"
            )
        else:
            sql = (
                f"SELECT rowid, rowid >> {ROW_BITS}, s, e, bm25(pas, {WEIGHTS['pas']}) AS r "
                f"FROM pas WHERE pas MATCH ? ORDER BY r LIMIT ?"
            )
        return [(int(a), int(b), int(s), int(e), float(r)) for a, b, s, e, r in self.conn.execute(sql, (match, int(limit)))]

    def claims(self, match: str, limit: int) -> list[tuple[int, int, float, str, dict]]:
        """``[(rowid, doc_id, bm25, text, payload)]`` for matching claims."""
        sql = (
            f"SELECT rowid, rowid >> {ROW_BITS}, bm25(clm, {WEIGHTS['clm']}) AS r, title, payload "
            f"FROM clm WHERE clm MATCH ? ORDER BY r LIMIT ?"
        )
        return [(int(a), int(b), float(r), t, json.loads(p or "{}")) for a, b, r, t, p in self.conn.execute(sql, (match, int(limit)))]

    def claims_by_id(self, claim_ids: list[str]) -> dict[str, tuple[int, str, dict]]:
        """``{claim_id: (doc_id, text, payload)}`` — how a vector claim hit
        gets its evidence span without re-reading the page."""
        if not claim_ids:
            return {}
        marks = ",".join("?" * len(claim_ids))
        sql = (
            f"SELECT r.claim_id, c.rowid >> {ROW_BITS}, c.title, c.payload FROM claim_ref r "
            f"JOIN clm c ON c.rowid = r.row WHERE r.claim_id IN ({marks})"
        )
        return {cid: (int(d), t, json.loads(p or "{}")) for cid, d, t, p in self.conn.execute(sql, claim_ids)}

    def claims_citing(self, episode_id: str) -> list[tuple[int, str, dict, dict]]:
        """``[(doc_id, text, payload, span)]`` — every claim with an evidence
        span into ``episode_id``, with THAT span (not the claim's first one).
        The read Track P's ``GET /episodes/{id}/citations`` needs (P4)."""
        sql = (
            f"SELECT c.rowid >> {ROW_BITS}, c.title, c.payload, x.episode, x.s, x.e, x.kind, x.hash "
            f"FROM claim_evidence x JOIN clm c ON c.rowid = x.row WHERE x.episode = ? ORDER BY x.row, x.s"
        )
        return [
            (int(d), t, json.loads(p or "{}"), {"episode": ep, "start": int(s), "end": int(e), "kind": k, "hash": h})
            for d, t, p, ep, s, e, k, h in self.conn.execute(sql, (episode_id,))
        ]

    def docs(self, ids: list[int]) -> dict[int, Doc]:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(f"SELECT id, kind, ref, meta FROM docs WHERE id IN ({marks})", list(ids))
        return {int(i): Doc(int(i), k, r, json.loads(m or "{}")) for i, k, r, m in rows}

    def docs_by_ref(self, kinds: tuple[str, ...], refs: list[str]) -> dict[str, Doc]:
        if not refs:
            return {}
        kmarks = ",".join("?" * len(kinds))
        rmarks = ",".join("?" * len(refs))
        rows = self.conn.execute(
            f"SELECT id, kind, ref, meta FROM docs WHERE kind IN ({kmarks}) AND ref IN ({rmarks})",
            [*kinds, *refs],
        )
        return {r: Doc(int(i), k, r, json.loads(m or "{}")) for i, k, r, m in rows}

    def column(self, table: str, column: str, doc_ids: list[int]) -> dict[int, str]:
        """One text column of the head row (``n == 0``) of each doc."""
        if not doc_ids:
            return {}
        marks = ",".join("?" * len(doc_ids))
        rows = self.conn.execute(
            f"SELECT rowid >> {ROW_BITS}, {column} FROM {table} WHERE rowid IN ({marks})",
            [d << ROW_BITS for d in doc_ids],
        )
        return {int(d): t or "" for d, t in rows}

    def passage_text(self, rowids: list[int]) -> dict[int, str]:
        if not rowids:
            return {}
        marks = ",".join("?" * len(rowids))
        return {int(r): b or "" for r, b in self.conn.execute(f"SELECT rowid, body FROM pas WHERE rowid IN ({marks})", list(rowids))}

    def episode_passages(self, doc_id: int, *, until: int | None = None) -> list[tuple[int, int, int, str]]:
        """``[(rowid, start, end, text)]`` of one episode in order, up to and
        including rowid ``until`` when given. Passages tile the body from
        offset 0, so the joined texts ARE ``body[:end]`` of the last one."""
        lo = doc_id << ROW_BITS
        hi = lo | MAX_ROWS_PER_DOC if until is None else until
        return [
            (int(r), int(s), int(e), b or "")
            for r, s, e, b in self.conn.execute(
                "SELECT rowid, s, e, body FROM pas WHERE rowid BETWEEN ? AND ? ORDER BY rowid",
                (lo, hi),
            )
        ]
