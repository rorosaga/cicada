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

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from loguru import logger

from api.services import markdown_parser

# An embed function takes texts and a query/document flag (EmbeddingGemma and
# other instruction-aware models embed queries and documents differently).
EmbedFn = Callable[..., np.ndarray]

INDEX_DB_FILE = "vector_index.db"
PENDING_STORE_FILE = "pending_entities.jsonl"

# Episode bodies are split into overlapping passages before embedding so a
# single multi-thousand-token conversation isn't embedded as one vector.
EPISODE_CHUNK_CHARS = 4000
EPISODE_CHUNK_OVERLAP = 200


@dataclass
class PendingEntity:
    """A sub-threshold entity (first mention) awaiting a promotion trigger."""

    name: str
    type: str
    description: str
    source_episode: str
    confidence: float
    tags: list[str]
    history_entries: list[dict]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "source_episode": self.source_episode,
            "confidence": self.confidence,
            "tags": self.tags or [],
            "history_entries": self.history_entries or [],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PendingEntity":
        return cls(
            name=data.get("name", ""),
            type=data.get("type", "concept"),
            description=data.get("description", ""),
            source_episode=data.get("source_episode", ""),
            confidence=float(data.get("confidence", 0.3)),
            tags=data.get("tags", []) or [],
            history_entries=data.get("history_entries", []) or [],
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

    # ---------- embedding ----------

    def _ensure_embed_fn(self) -> None:
        if self._embed_fn is None:
            self._embed_fn, resolved_model = _resolve_embed_fn()
            if self.model_name is None:
                self.model_name = resolved_model

    def _embed(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        self._ensure_embed_fn()
        vectors = np.asarray(self._embed_fn(texts, is_query=is_query), dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(texts):
            raise ValueError(
                f"embed_fn returned shape {vectors.shape} for {len(texts)} texts"
            )
        return vectors

    # ---------- connection ----------

    def _connect(self) -> sqlite3.Connection:
        import sqlite_vec

        conn = sqlite3.connect(str(self.db_path))
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn

    def _rebuild_table(
        self, conn: sqlite3.Connection, kind: str, rows: list[tuple[np.ndarray, str, dict]]
    ) -> None:
        """(Re)create the vec + metadata tables for ``kind`` and load ``rows``.

        ``rows`` is a list of ``(embedding, text, metadata)``. rowid is the
        1-based position so the vec row and meta row line up.
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
            f"rowid INTEGER PRIMARY KEY, text TEXT, metadata TEXT)"
        )
        for i, (embedding, text, metadata) in enumerate(rows, start=1):
            conn.execute(
                f"INSERT INTO {vec_table}(rowid, embedding) VALUES (?, ?)",
                (i, sqlite_vec.serialize_float32([float(x) for x in embedding])),
            )
            conn.execute(
                f"INSERT INTO {meta_table}(rowid, text, metadata) VALUES (?, ?, ?)",
                (i, text, json.dumps(metadata)),
            )
        self._write_index_meta(conn, model=self.model_name or "unknown", dim=dim)
        conn.commit()

    def _write_index_meta(self, conn: sqlite3.Connection, *, model: str, dim: int) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT)"
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
        except sqlite3.OperationalError:
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
        self, conn: sqlite3.Connection, kind: str, query: str, top_k: int
    ) -> list[dict]:
        import sqlite_vec

        vec_table = f"vec_{kind}"
        meta_table = f"meta_{kind}"
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
        """Rebuild the entity index from all markdown entity pages."""
        if not self.entities_dir.exists():
            return 0
        texts: list[str] = []
        staged: list[tuple[str, dict]] = []
        for filepath in sorted(self.entities_dir.glob("*.md")):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception:
                continue
            fm = parsed.frontmatter or {}
            text = _entity_embed_text(fm, parsed.body, filepath.stem)
            if not text:
                continue
            texts.append(text)
            staged.append(
                (
                    text,
                    {
                        "entity_id": filepath.stem,
                        "entity_name": str(fm.get("name", filepath.stem)),
                        "type": str(fm.get("type", "concept")),
                        "status": str(fm.get("status", "active")),
                        "confidence": float(fm.get("confidence", 0.0) or 0.0),
                        "file_path": str(filepath),
                    },
                )
            )
        if not staged:
            return 0
        embeddings = self._embed(texts)
        rows = [(embeddings[i], staged[i][0], staged[i][1]) for i in range(len(staged))]
        conn = self._connect()
        try:
            self._rebuild_table(conn, "entities", rows)
        finally:
            conn.close()
        logger.info(f"Vector entity index rebuilt with {len(rows)} entities")
        return len(rows)

    def search_entities(
        self, query: str, top_k: int = 5, include_archived: bool = False
    ) -> list[dict]:
        """Semantic search over promoted entity pages."""
        if not self.db_path.exists():
            return []
        conn = self._connect()
        try:
            # over-fetch so archived filtering doesn't starve the result set
            fetch_k = top_k * 3 if not include_archived else top_k
            results = self._knn(conn, "entities", query, fetch_k)
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()
        if not include_archived:
            results = [
                r for r in results if r.get("metadata", {}).get("status") != "archived"
            ]
        return results[:top_k]

    def _search_kind(self, kind: str, query: str, top_k: int) -> list[dict]:
        """Shared search helper: returns [] for a missing db or missing table."""
        if not self.db_path.exists():
            return []
        conn = self._connect()
        try:
            return self._knn(conn, kind, query, top_k)
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    # ---------- episode index ----------

    def index_episodes(self) -> int:
        """Rebuild the episode index over all episode files (chunked)."""
        if not self.episodes_dir.exists():
            return 0
        texts: list[str] = []
        staged: list[tuple[str, dict]] = []
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
                texts.append(chunk)
                staged.append((chunk, meta))
            episodes_added += 1
        if not staged:
            return 0
        embeddings = self._embed(texts)
        rows = [(embeddings[i], staged[i][0], staged[i][1]) for i in range(len(staged))]
        conn = self._connect()
        try:
            self._rebuild_table(conn, "episodes", rows)
        finally:
            conn.close()
        logger.info(
            f"Vector episode index rebuilt: {episodes_added} episodes / {len(rows)} passages"
        )
        return episodes_added

    def search_episodes(self, query: str, top_k: int = 3) -> list[dict]:
        return self._search_kind("episodes", query, top_k)

    # ---------- pending (sub-threshold) index ----------

    def _load_pending(self) -> list[PendingEntity]:
        if not self.pending_store.exists():
            return []
        out: list[PendingEntity] = []
        for line in self.pending_store.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(PendingEntity.from_dict(json.loads(line)))
            except Exception:
                continue
        return out

    def _save_pending(self, entries: list[PendingEntity]) -> None:
        self.pending_store.parent.mkdir(parents=True, exist_ok=True)
        if not entries:
            self.pending_store.write_text("", encoding="utf-8")
            return
        lines = [json.dumps(e.to_dict()) for e in entries]
        self.pending_store.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def index_pending_entity(self, entity: PendingEntity) -> None:
        """Append/replace a sub-threshold entity in the store (no vec rebuild).

        Rebuilding the vec table per add would be O(N^2) embedding calls in a
        single sleep batch; call :meth:`rebuild_pending_index` once afterward.
        """
        entries = self._load_pending()
        name_lower = entity.name.lower()
        kept = [e for e in entries if e.name.lower() != name_lower]
        kept.append(entity)
        self._save_pending(kept)

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
        """Remove and return an entry from the pending store, rebuild the index."""
        entries = self._load_pending()
        name_lower = entity_name.lower()
        kept: list[PendingEntity] = []
        promoted: PendingEntity | None = None
        for e in entries:
            if e.name.lower() == name_lower and promoted is None:
                promoted = e
            else:
                kept.append(e)
        if promoted is None:
            return None
        self._save_pending(kept)
        self._rebuild_pending_index(kept)
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
        """Rebuild the claims index from the ` ```claims ` blocks in entity pages.

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
        texts: list[str] = []
        staged: list[tuple[str, dict]] = []
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
                texts.append(text)
                staged.append(
                    (
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
                    )
                )
        if not staged:
            return 0
        embeddings = self._embed(texts)
        rows = [(embeddings[i], staged[i][0], staged[i][1]) for i in range(len(staged))]
        conn = self._connect()
        try:
            self._rebuild_table(conn, "claims", rows)
        finally:
            conn.close()
        logger.info(f"Vector claims index rebuilt with {len(rows)} valid claims")
        return len(rows)

    def search_claims(
        self,
        query: str,
        top_k: int = 5,
        *,
        observer: str | None = None,
        context: str | None = None,
        include_superseded: bool = False,
    ) -> list[dict]:
        """KNN over currently-valid claims, with optional perspective filters.

        ``observer`` / ``context`` are SQL-free post-filters applied to the
        ``claims``-kind metadata. By default, claims carrying a
        ``superseded_by`` marker are excluded; ``include_superseded=True`` lifts
        that. Returns ``[]`` gracefully on a missing db or missing ``claims``
        table (mirrors :meth:`search_entities` / :meth:`_search_kind`).
        """
        if not self.db_path.exists():
            return []
        conn = self._connect()
        try:
            # over-fetch so post-filtering doesn't starve the result set
            needs_postfilter = (
                observer is not None or context is not None or not include_superseded
            )
            fetch_k = top_k * 3 if needs_postfilter else top_k
            results = self._knn(conn, "claims", query, fetch_k)
        except sqlite3.OperationalError:
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
            if not include_superseded and meta.get("superseded_by"):
                continue
            filtered.append(r)
        return filtered[:top_k]


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

    Returns ``(embed_fn, model_name)``. ``embed_fn(texts, is_query=bool)``
    routes through EmbeddingGemma's asymmetric query/document prompts via
    sentence-transformers' ``encode_query`` / ``encode_document``.

    Not exercised by unit tests (needs a key or a gated model download); the
    unit tests inject ``embed_fn`` directly. Covered by integration runs.
    """
    from api.config import get_settings

    settings = get_settings()
    settings.warn_if_degraded()
    mode = settings.resolved_embedding_mode
    model = settings.resolved_embedding_model

    if mode == "openai":
        from openai import OpenAI

        client = OpenAI()

        def _openai_embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
            # OpenAI's embeddings are symmetric (no query/doc prompts), so
            # is_query is accepted-and-ignored to satisfy the contract.
            out: list[list[float]] = []
            for start in range(0, len(texts), 100):
                batch = texts[start : start + 100]
                resp = client.embeddings.create(model=model, input=batch)
                out.extend(d.embedding for d in resp.data)
            return np.asarray(out, dtype=np.float32)

        return _openai_embed, model

    # Local sentence-transformers (default: google/embeddinggemma-300m).
    from sentence_transformers import SentenceTransformer

    st_model = SentenceTransformer(model)

    def _local_embed(texts: list[str], *, is_query: bool = False) -> np.ndarray:
        encode = st_model.encode_query if is_query else st_model.encode_document
        return np.asarray(encode(texts), dtype=np.float32)

    return _local_embed, model
