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
from pathlib import Path
from typing import Callable

import numpy as np
from loguru import logger

from api.services import markdown_parser

# An embed function takes texts and a query/document flag (EmbeddingGemma and
# other instruction-aware models embed queries and documents differently).
EmbedFn = Callable[..., np.ndarray]

INDEX_DB_FILE = "vector_index.db"


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
