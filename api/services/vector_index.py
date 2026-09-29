"""sqlite-vec derived vector index — Cicada's retrieval index.

Replaces the LEANN wrapper (``leann_indexer.py``). The design contract,
established in ``docs/goals/improvement-dossier.md`` §2.1:

- **markdown+git stays the source of truth.** This index is *derived and
  disposable* — it is rebuilt from the entity/episode markdown by the Sleep
  cycle and can be deleted and regenerated at any time.
- Embeddings are *stored*, not recomputed at query time (LEANN's tradeoff),
  so search is a single in-process ANN lookup with no latency tax — which is
  what the interactive ``ask_memory`` endpoint and live graph search need.

Embedding is decoupled from indexing via an injected ``embed_fn`` so the
index can be tested offline with a deterministic embedder; production resolves
the OpenAI / local sentence-transformers backend from :class:`api.config.Settings`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Callable

import numpy as np
from loguru import logger

from api.services import markdown_parser
from api.services import pending_store as _store
# G141 PJ-0b (R-HP1): the pending store is its own module now. These two names
# stay importable from here — entity_resolver, link_recon and the tests use them.
from api.services.pending_store import PENDING_STORE_FILE, PendingEntity  # noqa: F401

# An embed function takes texts and a query/document flag (EmbeddingGemma and
# other instruction-aware models embed queries and documents differently).
EmbedFn = Callable[..., np.ndarray]

INDEX_DB_FILE = "vector_index.db"

# "log once" for a WAL-enable failure (Devin PR #24 finding 4) — _connect()
# runs on every search call; a persistently-locked file must not spam a
# warning on every single one.
_warned_wal_failure = False

# Episode bodies are split into overlapping passages before embedding so a
# single multi-thousand-token conversation isn't embedded as one vector.
EPISODE_CHUNK_CHARS = 4000
EPISODE_CHUNK_OVERLAP = 200


def _try_enable_wal(conn: sqlite3.Connection) -> None:
    """Best-effort ``journal_mode=WAL`` + ``synchronous=NORMAL`` (Wave-1 1.4).

    Devin PR #24 round 1, finding 4: the PRAGMA itself can raise
    ``sqlite3.OperationalError`` (e.g. a concurrent writer holding a lock the
    mode switch can't acquire) — and this runs inside ``_connect()``, i.e.
    BEFORE the caller's own graceful ``except sqlite3.OperationalError``
    around the query, so an unguarded PRAGMA here would turn a lock into an
    unhandled 500 instead of a degraded response. Never propagates: on
    failure the connection just continues on whatever journal mode the file
    already has, logged once per process so a persistently-locked file
    doesn't spam a warning on every single search call.
    """
    global _warned_wal_failure
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError as exc:
        if not _warned_wal_failure:
            _warned_wal_failure = True
            logger.warning(
                f"vector_index: could not enable WAL journal mode ({exc}); "
                "continuing on the existing journal mode. The index must "
                "never be the reason a request 500s."
            )


class SqliteVecIndexer:
    """Stored-embedding vector index over the markdown knowledge graph."""

    def __init__(
        self,
        memory_path: Path,
        *,
        embed_fn: EmbedFn | None = None,
        model_name: str | None = None,
        db_path: Path | None = None,
    ):
        self.memory_path = Path(memory_path)
        self.entities_dir = self.memory_path / "entities"
        self.episodes_dir = self.memory_path / "episodes"
        self.db_path = Path(db_path) if db_path else self.memory_path / INDEX_DB_FILE
        self.pending_store = self.memory_path / PENDING_STORE_FILE
        self._embed_fn = embed_fn
        # Recorded next to the vectors so a reindex knows what it built and can
        # detect a model swap (different model => different dim => full rebuild).
        self.model_name = model_name or ("unknown" if embed_fn else None)
        # What the last `index_*` call of each kind did: embedded / reused /
        # removed / rebuilt counts (Sleep's report and the tests read it).
        self.last_sync: dict[str, dict[str, int]] = {}

    # ---------- embedding ----------

    def _ensure_embed_fn(self) -> None:
        if self._embed_fn is None:
            self._embed_fn, resolved_model = _resolve_embed_fn()
            if self.model_name is None:
                self.model_name = resolved_model

    def _query_embed_fn(self) -> EmbedFn:
        """The embed_fn used for SEARCH queries.

        Per-bank embeddings: when this indexer wasn't handed an explicit
        ``embed_fn`` and the on-disk index records the model it was BUILT with
        (``index_meta.model``), embed the query with THAT model — not the global
        ``Settings`` mode — so a bank built on embeddinggemma keeps querying with
        embeddinggemma while a bank built on gemini-embedding-2 queries with
        gemini, both correct at once. Falls back to the global ``embed_fn``
        (``_ensure_embed_fn``) when an explicit fn was injected or the index is
        unbuilt (no recorded model).
        """
        if self._embed_fn is not None:
            return self._embed_fn
        recorded = (self.index_info() or {}).get("model")
        if recorded and recorded != "unknown":
            from api.services.providers import resolve_embed_fn_for_model

            embed_fn, _model = resolve_embed_fn_for_model(recorded)
            return embed_fn
        self._ensure_embed_fn()
        return self._embed_fn

    def _ensure_or_global(self) -> EmbedFn:
        """The build/document-side embed_fn (injected fn, else global config).

        Unchanged from prior behavior — indexing always uses the globally
        configured model so a *fresh* bank is built with whatever
        ``CICADA_EMBEDDING_MODE`` says.
        """
        self._ensure_embed_fn()
        return self._embed_fn

    def _embed(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        embed_fn = self._query_embed_fn() if is_query else self._ensure_or_global()
        vectors = np.asarray(embed_fn(texts, is_query=is_query), dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(texts):
            raise ValueError(
                f"embed_fn returned shape {vectors.shape} for {len(texts)} texts"
            )
        return vectors

    # ---------- connection ----------

    def _connect(self) -> sqlite3.Connection:
        import sqlite_vec

        conn = sqlite3.connect(str(self.db_path))
        # Wave-1 1.4: this index runs `journal_mode=delete` (sqlite3's default)
        # with NO pragma set at all, so a nightly Sleep rebuild (`_rebuild_table`
        # DROPs + re-creates + writes thousands of rows inside one transaction)
        # locks the whole db file against concurrent API + MCP readers for the
        # duration. WAL lets readers proceed against the last-committed snapshot
        # while a writer holds the file; NORMAL is WAL's recommended durability
        # tradeoff (safe against app crashes, not full OS/power loss) for a
        # derived, disposable, rebuild-from-markdown-anytime index.
        _try_enable_wal(conn)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn

    def _rebuild_table(
        self,
        conn: sqlite3.Connection,
        kind: str,
        rows: list[tuple[np.ndarray, str, dict]],
        keys: list[str] | None = None,
    ) -> None:
        """(Re)create the vec + metadata tables for ``kind`` and load ``rows``.

        ``rows`` is a list of ``(embedding, text, metadata)``. rowid is the
        1-based position so the vec row and meta row line up. Each meta row
        also carries the document's stable ``key`` (default: its position) and
        the ``hash`` of the text that was embedded — what :meth:`_sync_kind`
        diffs against so the next cycle embeds only what changed.
        """
        import sqlite_vec

        dim = int(rows[0][0].shape[0])
        vec_table = f"vec_{kind}"
        meta_table = f"meta_{kind}"
        conn.execute(f"DROP TABLE IF EXISTS {vec_table}")
        conn.execute(f"DROP TABLE IF EXISTS {meta_table}")
        conn.execute(
            f"CREATE VIRTUAL TABLE {vec_table} USING vec0("
            f"embedding float[{dim}] distance_metric=cosine)"
        )
        conn.execute(
            f"CREATE TABLE {meta_table} ("
            f"rowid INTEGER PRIMARY KEY, text TEXT, metadata TEXT, "
            f"key TEXT, hash TEXT)"
        )
        for i, (embedding, text, metadata) in enumerate(rows, start=1):
            conn.execute(
                f"INSERT INTO {vec_table}(rowid, embedding) VALUES (?, ?)",
                (i, sqlite_vec.serialize_float32([float(x) for x in embedding])),
            )
            conn.execute(
                f"INSERT INTO {meta_table}(rowid, text, metadata, key, hash) "
                f"VALUES (?, ?, ?, ?, ?)",
                (i, text, json.dumps(metadata),
                 keys[i - 1] if keys is not None else str(i), _text_hash(text)),
            )
        self._write_index_meta(conn, model=self.model_name or "unknown", dim=dim, kind=kind)
        conn.commit()

    # ---------- incremental sync ----------

    def _existing_rows(
        self, conn: sqlite3.Connection, kind: str
    ) -> tuple[dict[str, tuple[int, str, str]], int] | None:
        """``({key: (rowid, hash, metadata_json)}, dim)`` of what ``kind`` holds,
        or ``None`` when it cannot be diffed and must be rebuilt in full: no
        table, an older schema without ``key``/``hash``, or vectors built with
        a different model (a model swap changes the dim and the meaning of every
        vector). The model is recorded per kind because the kinds are rebuilt
        one after another — a global stamp would say "current" after the first.
        """
        try:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info(meta_{kind})")}
            if not {"key", "hash"} <= cols:
                return None
            kv = dict(conn.execute("SELECT key, value FROM index_meta").fetchall())
            if kv.get(f"model:{kind}") != (self.model_name or "unknown"):
                return None
            dim = int(kv.get(f"dim:{kind}", 0) or 0)
            rows = {
                key: (rowid, hash_, metadata)
                for rowid, key, hash_, metadata in conn.execute(
                    f"SELECT rowid, key, hash, metadata FROM meta_{kind}"
                )
            }
            return rows, dim
        except sqlite3.OperationalError:
            return None

    def _sync_kind(self, kind: str, staged: list[tuple[str, str, dict]]) -> dict[str, int]:
        """Bring ``kind``'s table in line with ``staged`` ``(key, text, metadata)``
        rows, embedding only the texts whose content hash is new or changed.

        Unchanged documents keep their stored vector (their metadata is
        refreshed in place — a page's status moves without its text moving),
        deleted documents are removed, and a schema, model or dimension change
        rebuilds the whole table. The embed happens BEFORE anything is written,
        so a failed embed leaves the previous index exactly as it was. The
        index stays derived and disposable: dropping the file just costs one
        full build. Returns ``{"embedded", "reused", "removed", "rebuilt"}``.
        """
        import sqlite_vec

        # Resolves `model_name` for a production embedder before the diff.
        self._ensure_or_global()
        unique_keys: list[str] = []
        seen: dict[str, int] = {}
        for key, _text, _meta in staged:
            n = seen.get(key, 0)
            seen[key] = n + 1
            unique_keys.append(key if n == 0 else f"{key}~{n}")
        hashes = [_text_hash(text) for _k, text, _m in staged]
        stats = {"embedded": 0, "reused": 0, "removed": 0, "rebuilt": 0}

        conn = self._connect()
        try:
            existing = self._existing_rows(conn, kind)
            if not staged:
                if existing is not None:
                    conn.execute(f"DROP TABLE IF EXISTS vec_{kind}")
                    conn.execute(f"DROP TABLE IF EXISTS meta_{kind}")
                    conn.commit()
                    stats["removed"] = len(existing[0])
                return stats

            def full() -> dict[str, int]:
                embeddings = self._embed([t for _k, t, _m in staged])
                rows = [(embeddings[i], staged[i][1], staged[i][2]) for i in range(len(staged))]
                self._rebuild_table(conn, kind, rows, keys=unique_keys)
                stats.update(embedded=len(rows), rebuilt=1)
                return stats

            if existing is None:
                return full()
            rows_by_key, dim = existing
            todo = [i for i, k in enumerate(unique_keys)
                    if k not in rows_by_key or rows_by_key[k][1] != hashes[i]]
            wanted = set(unique_keys)
            gone = [k for k in rows_by_key if k not in wanted]
            meta_json = [json.dumps(m) for _k, _t, m in staged]
            meta_moved = [i for i, k in enumerate(unique_keys)
                          if k in rows_by_key and rows_by_key[k][1] == hashes[i]
                          and rows_by_key[k][2] != meta_json[i]]
            stats["reused"] = len(staged) - len(todo)
            if not todo and not gone and not meta_moved:
                return stats
            embeddings = self._embed([staged[i][1] for i in todo]) if todo else None
            if embeddings is not None and dim and int(embeddings.shape[1]) != dim:
                return full()  # same model name, different width: nothing is reusable

            vec_table, meta_table = f"vec_{kind}", f"meta_{kind}"
            next_rowid = max((r for r, _h, _m in rows_by_key.values()), default=0) + 1
            try:
                for k in gone:
                    conn.execute(f"DELETE FROM {vec_table} WHERE rowid = ?", (rows_by_key[k][0],))
                    conn.execute(f"DELETE FROM {meta_table} WHERE rowid = ?", (rows_by_key[k][0],))
                for j, i in enumerate(todo):
                    key = unique_keys[i]
                    if key in rows_by_key:  # changed text: same slot, new vector
                        rowid = rows_by_key[key][0]
                        conn.execute(f"DELETE FROM {vec_table} WHERE rowid = ?", (rowid,))
                        conn.execute(f"DELETE FROM {meta_table} WHERE rowid = ?", (rowid,))
                    else:
                        rowid, next_rowid = next_rowid, next_rowid + 1
                    conn.execute(
                        f"INSERT INTO {vec_table}(rowid, embedding) VALUES (?, ?)",
                        (rowid, sqlite_vec.serialize_float32([float(x) for x in embeddings[j]])),
                    )
                    conn.execute(
                        f"INSERT INTO {meta_table}(rowid, text, metadata, key, hash) "
                        f"VALUES (?, ?, ?, ?, ?)",
                        (rowid, staged[i][1], meta_json[i], key, hashes[i]),
                    )
                for i in meta_moved:
                    conn.execute(f"UPDATE {meta_table} SET metadata = ? WHERE rowid = ?",
                                 (meta_json[i], rows_by_key[unique_keys[i]][0]))
                self._write_index_meta(
                    conn, model=self.model_name or "unknown",
                    dim=int(embeddings.shape[1]) if embeddings is not None else dim, kind=kind,
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            stats.update(embedded=len(todo), removed=len(gone))
            return stats
        finally:
            conn.close()

    def _write_index_meta(
        self, conn: sqlite3.Connection, *, model: str, dim: int, kind: str | None = None
    ) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        if kind is not None:
            conn.execute(
                "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
                (f"model:{kind}", model),
            )
            conn.execute(
                "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?, ?)",
                (f"dim:{kind}", str(dim)),
            )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta(key, value) VALUES ('model', ?)", (model,)
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta(key, value) VALUES ('dim', ?)", (str(dim),)
        )

    def index_info(self) -> dict:
        """Return ``{model, dim}`` recorded at build time, or ``{}`` if unbuilt."""
        if not self.db_path.exists():
            return {}
        conn = self._connect()
        try:
            cur = conn.execute("SELECT key, value FROM index_meta")
            kv = dict(cur.fetchall())
        except sqlite3.OperationalError as exc:
            # Wave-1 1.4: a lock (or any other operational failure) must not
            # read as "index has no metadata yet" — that's indistinguishable
            # from "the agent has no memory" at the call site.
            logger.warning(f"vector_index.index_info: query failed ({exc}); degrading to {{}}")
            return {}
        finally:
            conn.close()
        info: dict = {}
        if "model" in kv:
            info["model"] = kv["model"]
        if "dim" in kv:
            info["dim"] = int(kv["dim"])
        return info

    def _knn(
        self,
        conn: sqlite3.Connection,
        kind: str,
        query: str,
        top_k: int,
        *,
        qvec: np.ndarray | None = None,
    ) -> list[dict]:
        import sqlite_vec

        vec_table = f"vec_{kind}"
        meta_table = f"meta_{kind}"
        if qvec is None:
            try:
                qvec = self._embed([query], is_query=True)[0]
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"vector search embed failed ({kind}): {exc}")
                return []
        cur = conn.execute(
            f"SELECT v.rowid, v.distance, m.text, m.metadata "
            f"FROM {vec_table} v JOIN {meta_table} m ON m.rowid = v.rowid "
            f"WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (sqlite_vec.serialize_float32([float(x) for x in qvec]), int(top_k)),
        )
        results: list[dict] = []
        for _rowid, distance, text, metadata_json in cur.fetchall():
            results.append(
                {
                    # cosine distance -> similarity score in [0, 1]-ish
                    "score": float(1.0 - distance),
                    "text": text or "",
                    "metadata": json.loads(metadata_json) if metadata_json else {},
                }
            )
        return results

    # ---------- entity index ----------

    def index_entities(self) -> int:
        """Sync the entity index with the markdown entity pages.

        Incremental by content hash of the embedded text (:meth:`_sync_kind`):
        a page whose text did not change keeps its vector; only new and edited
        pages are embedded and deleted pages are removed.
        """
        if not self.entities_dir.exists():
            return 0
        staged: list[tuple[str, str, dict]] = []
        for filepath in sorted(self.entities_dir.glob("*.md")):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception:
                continue
            fm = parsed.frontmatter or {}
            text = _entity_embed_text(fm, parsed.body, filepath.stem)
            if not text:
                continue
            staged.append((
                filepath.stem,
                text,
                {
                    "entity_id": filepath.stem,
                    "entity_name": str(fm.get("name", filepath.stem)),
                    "type": str(fm.get("type", "concept")),
                    "status": str(fm.get("status", "active")),
                    "confidence": float(fm.get("confidence", 0.0) or 0.0),
                    "file_path": str(filepath),
                },
            ))
        stats = self._sync_kind("entities", staged)
        self.last_sync["entities"] = stats
        logger.info(
            f"Vector entity index synced: {len(staged)} entities "
            f"({stats['embedded']} embedded, {stats['reused']} reused, {stats['removed']} removed)"
        )
        return len(staged)

    def search_entities(
        self, query: str, top_k: int = 5, include_archived: bool = False
    ) -> list[dict]:
        """Semantic search over promoted entity pages.

        When ``include_archived`` is False (default), active entities are
        preferred, but if fewer than ``top_k`` active hits exist, archived hits
        are appended as a *fallback tier* (ranked last, status preserved) so a
        paraphrased query can still reach a decayed page (e.g. a rejected
        application). ``include_archived=True`` returns the raw ranking.
        """
        if not self.db_path.exists():
            return []
        conn = self._connect()
        try:
            fetch_k = top_k * 3 if not include_archived else top_k
            results = self._knn(conn, "entities", query, fetch_k)
        except sqlite3.OperationalError as exc:
            logger.warning(f"vector_index.search_entities: query failed ({exc}); degrading to []")
            return []
        finally:
            conn.close()
        if include_archived:
            return results[:top_k]
        active = [r for r in results if r.get("metadata", {}).get("status") != "archived"]
        if len(active) >= top_k:
            return active[:top_k]
        archived = [r for r in results if r.get("metadata", {}).get("status") == "archived"]
        return (active + archived)[:top_k]

    def search_kinds(self, query: str, top_k_by_kind: dict[str, int]) -> dict[str, list[dict]]:
        """KNN over several kinds with ONE query embedding (G136).

        ``/search``'s hybrid mode wants the entity, claim and episode legs of
        one query at once; three ``search_*`` calls embed the same text three
        times, and the embed is the dominant cost of a warm search (G58). Same
        graceful degrade as :meth:`_search_kind`: a missing db, a missing
        table or a failed embed gives empty lists, never a raise. No
        archived-tier or superseded filtering happens here — the caller ranks.
        """
        out: dict[str, list[dict]] = {kind: [] for kind in top_k_by_kind}
        if not top_k_by_kind or not self.db_path.exists():
            return out
        try:
            qvec = self._embed([query], is_query=True)[0]
        except Exception as exc:  # noqa: BLE001
            # The exception class only: a provider's error can echo its input,
            # and the input is the person's query (K9).
            logger.debug(f"vector search embed failed (search_kinds): {type(exc).__name__}")
            return out
        conn = self._connect()
        try:
            for kind, top_k in top_k_by_kind.items():
                try:
                    out[kind] = self._knn(conn, kind, query, top_k, qvec=qvec)
                except sqlite3.OperationalError as exc:
                    logger.warning(
                        f"vector_index.search_kinds({kind!r}): query failed ({exc}); degrading to []"
                    )
        finally:
            conn.close()
        return out

    def _search_kind(self, kind: str, query: str, top_k: int) -> list[dict]:
        """Shared search helper: returns [] for a missing db or missing table."""
        if not self.db_path.exists():
            return []
        conn = self._connect()
        try:
            return self._knn(conn, kind, query, top_k)
        except sqlite3.OperationalError as exc:
            logger.warning(f"vector_index._search_kind({kind!r}): query failed ({exc}); degrading to []")
            return []
        finally:
            conn.close()

    # ---------- episode index ----------

    def index_episodes(self) -> int:
        """Sync the episode index over all episode files (chunked).

        Incremental: an episode whose passages hash the same keeps its vectors,
        so a nightly cycle embeds the new and grown conversations only, not the
        whole history (:meth:`_sync_kind`).
        """
        if not self.episodes_dir.exists():
            return 0
        staged: list[tuple[str, str, dict]] = []
        episodes_added = 0
        for filepath in sorted(self.episodes_dir.glob("*.md")):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception:
                continue
            body = parsed.body.strip()
            if not body:
                continue
            fm = parsed.frontmatter or {}
            base_meta = {
                "episode_id": str(fm.get("id", filepath.stem)),
                "source": str(fm.get("source", "unknown")),
                "timestamp": str(fm.get("timestamp", "")),
                "title": str(fm.get("title", "")),
                "file_path": str(filepath),
            }
            chunks = _chunk_episode_body(body)
            for chunk_idx, chunk in enumerate(chunks):
                meta = dict(base_meta)
                meta["chunk_index"] = chunk_idx
                meta["chunk_count"] = len(chunks)
                staged.append((f"{filepath.stem}#{chunk_idx}", chunk, meta))
            episodes_added += 1
        stats = self._sync_kind("episodes", staged)
        self.last_sync["episodes"] = stats
        logger.info(
            f"Vector episode index synced: {episodes_added} episodes / {len(staged)} passages "
            f"({stats['embedded']} embedded, {stats['reused']} reused, {stats['removed']} removed)"
        )
        return episodes_added

    def search_episodes(self, query: str, top_k: int = 3) -> list[dict]:
        return self._search_kind("episodes", query, top_k)

    # ---------- pending (sub-threshold) index ----------
    #
    # The file is `pending_store`'s (G141 PJ-0b, R-HP1): these methods keep
    # their names and contracts for Stage 2 and link recon and delegate every
    # read and write to that one module. The vectors below stay here.

    def _load_pending(self) -> list[PendingEntity]:
        return _store.load(self.memory_path)

    def _save_pending(self, entries: list[PendingEntity]) -> None:
        _store.save(self.memory_path, entries)

    def index_pending_entity(self, entity: PendingEntity) -> None:
        """Append/replace a sub-threshold entity in the store (no vec rebuild).

        Rebuilding the vec table per add would be O(N^2) embedding calls in a
        single sleep batch; call :meth:`rebuild_pending_index` once afterward.
        A replaced line's held claims are carried, never dropped
        (``pending_store.upsert``, G141 PJ-0b R-HP4).
        """
        _store.upsert(self.memory_path, entity)

    def rebuild_pending_index(self) -> int:
        entries = self._load_pending()
        if not entries:
            return 0
        self._rebuild_pending_index(entries)
        return len(entries)

    def list_pending(self) -> list[PendingEntity]:
        return self._load_pending()

    def pending_by_name(self, name: str) -> PendingEntity | None:
        name_lower = name.lower()
        for e in self._load_pending():
            if e.name.lower() == name_lower:
                return e
        return None

    def promote_from_pending(self, entity_name: str) -> PendingEntity | None:
        """Remove and return an entry from the pending store, rebuild the index.

        G141 PJ-0b (R-HP4): an entry that still holds claims is returned but
        STAYS — it leaves through ``pending_store.release`` once Stage 5.56 has
        written its claims onto the new page — and nothing is rebuilt for it,
        since nothing left the store.
        """
        promoted, removed = _store.take(self.memory_path, entity_name)
        if removed:
            self._rebuild_pending_index(self._load_pending())
        return promoted

    def _rebuild_pending_index(self, entries: list[PendingEntity]) -> None:
        texts = [f"{e.name}: {e.description}".strip() for e in entries]
        rows_meta = [
            {
                "entity_name": e.name,
                "type": e.type,
                "source_episode": e.source_episode,
                "confidence": float(e.confidence),
            }
            for e in entries
        ]
        keep = [i for i, t in enumerate(texts) if t]
        if not keep:
            return
        texts = [texts[i] for i in keep]
        rows_meta = [rows_meta[i] for i in keep]
        embeddings = self._embed(texts)
        rows = [(embeddings[i], texts[i], rows_meta[i]) for i in range(len(texts))]
        conn = self._connect()
        try:
            self._rebuild_table(conn, "pending", rows)
        finally:
            conn.close()

    def search_pending(self, query: str, top_k: int = 5) -> list[dict]:
        return self._search_kind("pending", query, top_k)

    # ---------- claims index (derived from in-page ```claims blocks) ----------

    def index_claims(self) -> int:
        """Sync the claims index with the ` ```claims ` blocks in entity pages.

        Incremental by content hash like the other kinds (:meth:`_sync_kind`).

        Source of truth is the editable markdown page; this index is derived and
        disposable (D2 ADDENDUM). Only **currently-valid** claims are indexed
        (``valid_to is None``) — invalidated/closed claims live on in the page
        and in git for audit, but are excluded from retrieval. The embedded
        string is ``claim.text``; ``observer``/``context`` are stored as
        post-filter/pivot axes (mirrors the ``claims``-kind metadata in the D2
        index spec).
        """
        from api.services.claims import parse_claims

        if not self.entities_dir.exists():
            return 0
        staged: list[tuple[str, str, dict]] = []
        for filepath in sorted(self.entities_dir.glob("*.md")):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception:
                continue
            for claim in parse_claims(parsed.body):
                if claim.valid_to is not None:
                    continue  # only currently-valid claims are indexed
                text = (claim.text or "").strip()
                if not text:
                    continue
                staged.append((
                    f"{filepath.stem}:{claim.id}",
                    text,
                    {
                        "claim_id": claim.id,
                        "subject": claim.subject,
                        "predicate": claim.predicate,
                        "object": claim.object,
                        "observer": claim.observer,
                        "context": claim.context,
                        "epistemic": claim.epistemic,
                        "source_trust": claim.source_trust,
                        "confidence": float(claim.confidence),
                        "valid_from": claim.valid_from,
                        "superseded_by": claim.superseded_by,
                        "origin": claim.origin,
                        "file_path": str(filepath),
                    },
                ))
        stats = self._sync_kind("claims", staged)
        self.last_sync["claims"] = stats
        logger.info(
            f"Vector claims index synced: {len(staged)} valid claims "
            f"({stats['embedded']} embedded, {stats['reused']} reused, {stats['removed']} removed)"
        )
        return len(staged)

    def search_claims(
        self,
        query: str,
        top_k: int = 5,
        *,
        observer: str | None = None,
        context: str | None = None,
    ) -> list[dict]:
        """KNN over currently-valid claims, with optional perspective filters.

        ``observer`` / ``context`` are SQL-free post-filters applied to the
        ``claims``-kind metadata. A claim carrying a ``superseded_by`` marker
        is never returned. G140 Q-R3 removed ``include_superseded``: this index
        holds only claims with no ``valid_to`` (``index_claims``) and
        ``claim_reconciler._close`` always stamps both fields, so the flag
        could only surface a marker-only claim no writer produces. History is
        the page's (MCP recall, ``cicada_get_perspective(history=true)``) and
        the FTS index's (G136 R10). Returns ``[]`` gracefully on a missing db
        or a missing ``claims`` table.
        """
        if not self.db_path.exists():
            return []
        conn = self._connect()
        try:
            # over-fetch so post-filtering doesn't starve the result set
            results = self._knn(conn, "claims", query, top_k * 3)
        except sqlite3.OperationalError as exc:
            logger.warning(f"vector_index.search_claims: query failed ({exc}); degrading to []")
            return []
        finally:
            conn.close()
        filtered: list[dict] = []
        for r in results:
            meta = r.get("metadata", {})
            if observer is not None and meta.get("observer") != observer:
                continue
            if context is not None and meta.get("context") != context:
                continue
            if meta.get("superseded_by"):
                continue
            filtered.append(r)
        return filtered[:top_k]


def _text_hash(text: str) -> str:
    """The identity of an embedded text: what a sync compares to decide whether
    a stored vector is still the right one."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _chunk_episode_body(body: str) -> list[str]:
    """Split an episode body into overlapping passages for embedding."""
    body = body.strip()
    if not body:
        return []
    if len(body) <= EPISODE_CHUNK_CHARS:
        return [body]
    chunks: list[str] = []
    start = 0
    while start < len(body):
        end = start + EPISODE_CHUNK_CHARS
        if end < len(body):
            newline_pos = body.rfind("\n", max(start + 1, end - 300), end)
            if newline_pos > start:
                end = newline_pos + 1
        chunk = body[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(body):
            break
        start = max(end - EPISODE_CHUNK_OVERLAP, start + 1)
    return chunks


def _entity_embed_text(fm: dict, body: str, stem: str) -> str:
    """Compose the text embedded for an entity.

    We embed **name + type + aliases + body** but deliberately exclude the
    free-form ``tags``: tags are highly repetitive across the graph (many
    nodes share ``career``/``robotics``/…), so embedding them injects a shared
    direction that dilutes discrimination between otherwise-distinct nodes.
    Tags remain available as filterable metadata. ``type`` is low-cardinality
    and genuinely informative ("FastAPI is a tool"), so it stays. This choice
    is a tunable knob — the index is derived, so changing it is just a reindex.
    """
    header = [str(fm.get("name", stem))]
    if fm.get("type"):
        header.append(f"({fm['type']})")
    aliases = fm.get("aliases") or []
    if aliases:
        header.append("aka: " + ", ".join(str(a) for a in aliases))
    return "\n".join(str(p) for p in [" ".join(header), body] if p).strip()


def _resolve_embed_fn() -> tuple[EmbedFn, str]:
    """Build the production embedding fn + its model name from Settings.

    Thin shim: the resolution logic now lives in
    :func:`api.services.providers.resolve_embed_fn` (openai / openrouter / local),
    which preserves the ``(embed_fn, model_name)`` contract and the
    ``embed_fn(texts, *, is_query=False) -> np.ndarray`` shape this index relies
    on. Kept here so callers (``_ensure_embed_fn``) don't have to move.

    Not exercised by unit tests (needs a key or a gated model download); the
    unit tests inject ``embed_fn`` directly. Covered by ``test_providers.py``
    (hermetic) and integration runs.
    """
    from api.services.providers import resolve_embed_fn

    return resolve_embed_fn()
