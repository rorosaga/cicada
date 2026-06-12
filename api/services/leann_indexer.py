"""LEANN index management for Cicada.

Three indexes live under ``memory_path``:

1. ``leann/entities`` — promoted entity pages. Semantic lookup for Bookworm.
2. ``leann/episodes`` — raw episode text. Lets Bookworm surface the
   conversation excerpts an answer was grounded in.
3. ``leann/pending`` — sub-threshold entities that have not yet been promoted
   to full pages (first mentions waiting for a second mention).

The embedding backend is selected per :class:`api.config.Settings`:

- ``openai`` (default) — ``text-embedding-3-small`` via OpenAI; needs
  ``OPENAI_API_KEY``. Uses the batched build path (see ``_safe_build``).
- ``local`` — ``sentence-transformers/all-MiniLM-L6-v2`` on-device, no API
  key, fully offline. Flows through LEANN's standard single-call build.

When ``openai`` is requested but no key is present the mode auto-degrades to
``local`` (see ``Settings.resolved_embedding_mode``) so a key-less install
still gets semantic search.
"""

from __future__ import annotations

import json
import pickle
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from loguru import logger

from api.services import markdown_parser

ENTITY_INDEX_SUBDIR = "leann/entities"
EPISODE_INDEX_SUBDIR = "leann/episodes"
PENDING_INDEX_SUBDIR = "leann/pending"
PENDING_STORE_FILE = "leann/pending_entities.jsonl"

BACKEND = "hnsw"

# LEANN's non-OpenAI embedding mode token. sentence-transformers models are
# loaded through this branch of LeannBuilder.
_LOCAL_EMBEDDING_MODE = "sentence-transformers"

# Episode-body chunking caps. LEANN's Python API does not chunk — the CLI
# does, but `builder.add_text(text, metadata)` embeds `text` as a single
# passage. OpenAI's embedding endpoint has two hard limits:
#   - 8192 tokens per individual text (text-embedding-3-small)
#   - 300_000 tokens per request (the whole batch)
# A single 10k-character episode is already close to 2500 tokens, and
# LEANN batches everything passed to the builder into one embedding
# request, so with a hundred-plus episodes we were blowing past 300k
# aggregate tokens. The fix is to pre-split episode bodies into LEANN's
# own default passage size (1024 chars ~ 250 tokens) so the batch stays
# comfortably below the cap even with thousands of episodes.
EPISODE_CHUNK_CHARS = 4000  # ~1000 tokens per passage, ~250 passages per 1M chars
EPISODE_CHUNK_OVERLAP = 200  # small overlap to avoid cutting mid-sentence

# --- Embedding batch budget ---
# LEANN's built-in OpenAI path hardcodes a 500-text batch (see
# ``leann.embedding_compute.compute_embeddings_openai``) and ignores any
# ``batch_size`` we pass via ``embedding_options``. A 500-text batch at
# ~1000 tokens per chunk blows straight through OpenAI's 300k-token
# per-request limit, so we bypass LEANN's internal batching entirely:
# we compute embeddings ourselves in small explicit batches and feed them
# back to LEANN via ``builder.build_index_from_embeddings``.
#
# Budget: 100 items * ~1000 tokens/item ≈ 100k tokens per request, leaving
# a 3x safety margin under the 300k cap even if occasional chunks run hot.
EMBEDDING_BATCH_MAX_ITEMS = 100
EMBEDDING_BATCH_MAX_CHARS = 300_000  # ~75k tokens ceiling per batch


@dataclass
class PendingEntity:
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


class LeannIndexer:
    """Thin wrapper around LeannBuilder / LeannSearcher."""

    def __init__(
        self,
        memory_path: Path,
        *,
        embedding_mode: str | None = None,
        embedding_model: str | None = None,
    ):
        self.memory_path = Path(memory_path)
        self.entities_dir = self.memory_path / "entities"
        self.episodes_dir = self.memory_path / "episodes"
        self.entity_index_path = self.memory_path / ENTITY_INDEX_SUBDIR
        self.episode_index_path = self.memory_path / EPISODE_INDEX_SUBDIR
        self.pending_index_path = self.memory_path / PENDING_INDEX_SUBDIR
        self.pending_store = self.memory_path / PENDING_STORE_FILE
        self.pending_store.parent.mkdir(parents=True, exist_ok=True)

        # Resolve the embedding backend from Settings unless explicit args are
        # passed (benchmarks override without touching env). Reading the
        # *resolved* mode applies the openai->local auto-degrade, and we log
        # the degrade warning here at construction time so a key-less install
        # gets a clear, one-time signal that it switched to local embeddings.
        from api.config import get_settings

        settings = get_settings()
        if embedding_mode is None:
            settings.warn_if_degraded()
            self.embedding_mode = settings.resolved_embedding_mode
        else:
            self.embedding_mode = embedding_mode.strip().lower()

        if embedding_model is not None:
            self.embedding_model = embedding_model
        elif embedding_mode is None:
            self.embedding_model = settings.resolved_embedding_model
        else:
            # Explicit mode but no explicit model: pick the matching default.
            self.embedding_model = (
                settings.embedding_model
                if self.embedding_mode == "openai"
                else settings.embedding_model_local
            )

    # ---------- Builder ----------

    def _make_builder(self):
        from leann.api import LeannBuilder

        if self.embedding_mode == "openai":
            return LeannBuilder(
                backend_name=BACKEND,
                embedding_mode="openai",
                embedding_model=self.embedding_model,
            )

        # Local mode: route through LEANN's sentence-transformers branch.
        # sentence-transformers is an optional extra (it pulls torch, ~250MB);
        # surface a clear, actionable error at index time rather than letting
        # an opaque ImportError bubble up from deep inside LEANN.
        self._require_sentence_transformers()
        return LeannBuilder(
            backend_name=BACKEND,
            embedding_mode=_LOCAL_EMBEDDING_MODE,
            embedding_model=self.embedding_model,
        )

    @staticmethod
    def _require_sentence_transformers() -> None:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Local embedding mode (CICADA_EMBEDDING_MODE=local) needs the "
                "optional 'sentence-transformers' dependency, which is not "
                "installed. Install it with:\n"
                "    uv sync --extra local --directory api\n"
                "(downloads ~250MB incl. torch; the all-MiniLM-L6-v2 model is "
                "fetched on first build). Or set CICADA_EMBEDDING_MODE=openai "
                "and provide OPENAI_API_KEY."
            ) from exc

    def _safe_build(self, builder, target: Path, label: str) -> bool:
        """Build a LEANN index, batching embedding requests for the OpenAI path.

        For ``openai`` mode we bypass LEANN's built-in batching (which
        hardcodes 500 texts per request and blows the 300k-token OpenAI
        cap with our episode volume) by computing embeddings in small
        explicit batches and feeding them back via
        ``build_index_from_embeddings``. For other modes we fall through
        to the standard single-call build.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.embedding_mode == "openai":
                self._build_with_batched_embeddings(builder, target, label)
            else:
                # Local (sentence-transformers) runs in-process with no
                # per-request token cap, so the standard single-call build is
                # both correct and simpler than batching.
                builder.build_index(str(target))
            return True
        except Exception as e:
            logger.warning(f"LEANN build failed for {label}: {type(e).__name__}: {e}")
            return False

    def _build_with_batched_embeddings(self, builder, target: Path, label: str) -> None:
        """Compute embeddings in bounded batches, then call build_index_from_embeddings.

        Bypasses LEANN's hardcoded 500-batch so OpenAI's 300k-token
        per-request limit can't be exceeded even when the episode corpus
        grows to thousands of passages. Batch size is capped by both item
        count and total character budget, so a handful of very long
        chunks still get their own request.
        """
        from leann.embedding_compute import compute_embeddings_openai

        chunks = list(getattr(builder, "chunks", []) or [])
        if not chunks:
            raise ValueError(f"No chunks to index for {label}")

        texts = [c["text"] for c in chunks]
        ids = [c["id"] for c in chunks]
        n = len(texts)

        batches: list[tuple[int, int]] = []
        start = 0
        while start < n:
            end = start
            batch_chars = 0
            while end < n and (end - start) < EMBEDDING_BATCH_MAX_ITEMS:
                next_len = len(texts[end])
                if end > start and batch_chars + next_len > EMBEDDING_BATCH_MAX_CHARS:
                    break
                batch_chars += next_len
                end += 1
            if end == start:
                # Single oversize text — still send it on its own so we
                # don't spin forever. OpenAI's per-text cap is 8192 tokens,
                # which LEANN already truncates upstream.
                end = start + 1
            batches.append((start, end))
            start = end

        logger.info(
            f"LEANN {label}: embedding {n} passages in {len(batches)} batch(es) "
            f"(<= {EMBEDDING_BATCH_MAX_ITEMS} items / ~{EMBEDDING_BATCH_MAX_CHARS} chars per request)"
        )

        pieces: list[np.ndarray] = []
        for batch_idx, (lo, hi) in enumerate(batches):
            batch_texts = texts[lo:hi]
            batch_emb = compute_embeddings_openai(
                batch_texts,
                self.embedding_model,
                provider_options=builder.embedding_options or {},
            )
            pieces.append(np.asarray(batch_emb, dtype=np.float32))

        embeddings = np.concatenate(pieces, axis=0) if len(pieces) > 1 else pieces[0]
        if embeddings.shape[0] != n:
            raise RuntimeError(
                f"Embedding count mismatch: expected {n}, got {embeddings.shape[0]}"
            )

        # Set builder.dimensions from the embedding shape so
        # build_index_from_embeddings doesn't try to re-run a "dummy"
        # embedding to infer them.
        if getattr(builder, "dimensions", None) is None:
            builder.dimensions = embeddings.shape[1]

        with tempfile.NamedTemporaryFile(
            suffix=".pkl", prefix=f"leann_{label}_", delete=False
        ) as tmp:
            pickle.dump((ids, embeddings), tmp)
            tmp_path = tmp.name
        try:
            builder.build_index_from_embeddings(str(target), tmp_path)
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    # ---------- Entity index ----------

    def index_entities(self) -> int:
        """Rebuild the entity index from all markdown entity pages."""
        if not self.entities_dir.exists():
            return 0
        builder = self._make_builder()
        count = 0
        for filepath in sorted(self.entities_dir.glob("*.md")):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception:
                continue
            fm = parsed.frontmatter or {}
            # Embed type/tags/aliases alongside name+body so semantic queries
            # like "Python tools" surface tool-type entities whose body never
            # says "tool". Metadata fields are filterable but not embedded.
            header_bits = [str(fm.get("name", filepath.stem))]
            if fm.get("type"):
                header_bits.append(f"({fm['type']})")
            tags = fm.get("tags") or []
            if tags:
                header_bits.append("tags: " + ", ".join(str(t) for t in tags))
            aliases = fm.get("aliases") or []
            if aliases:
                header_bits.append("aka: " + ", ".join(str(a) for a in aliases))
            text_parts = [
                " ".join(header_bits),
                parsed.body,
            ]
            text = "\n".join(str(p) for p in text_parts if p).strip()
            if not text:
                continue
            builder.add_text(
                text,
                metadata={
                    "entity_id": filepath.stem,
                    "entity_name": str(fm.get("name", filepath.stem)),
                    "type": str(fm.get("type", "concept")),
                    "status": str(fm.get("status", "active")),
                    "confidence": float(fm.get("confidence", 0.0) or 0.0),
                    "file_path": str(filepath),
                },
            )
            count += 1
        if count == 0:
            return 0
        if not self._safe_build(builder, self.entity_index_path, "entities"):
            raise RuntimeError(
                f"LEANN entity index rebuild failed for {count} entities"
            )
        logger.info(f"LEANN entity index rebuilt with {count} entities")
        return count

    def search_entities(
        self,
        query: str,
        top_k: int = 5,
        include_archived: bool = False,
    ) -> list[dict]:
        """Semantic search over promoted entity pages."""
        results = self._search(self.entity_index_path, query, top_k)
        if not include_archived:
            results = [
                r for r in results if r.get("metadata", {}).get("status") != "archived"
            ]
        return results

    # ---------- Episode index ----------

    def index_episodes(self) -> int:
        """Rebuild the episode index over all episode files (processed or not).

        Episode bodies are chunked into ~4000-char passages before indexing,
        both to stay under OpenAI's 8192-tokens-per-text cap on individual
        embedding calls and to keep the aggregate batch under the 300k
        tokens-per-request cap that LEANN hits when it fires the full set
        of passages to OpenAI in one go.
        """
        if not self.episodes_dir.exists():
            return 0
        builder = self._make_builder()
        episodes_added = 0
        passages_added = 0
        for filepath in sorted(self.episodes_dir.glob("*.md")):
            try:
                parsed = markdown_parser.parse(filepath)
            except Exception:
                continue
            body = parsed.body.strip()
            if not body:
                continue
            fm = parsed.frontmatter or {}
            base_metadata = {
                "episode_id": str(fm.get("id", filepath.stem)),
                "source": str(fm.get("source", "unknown")),
                "timestamp": str(fm.get("timestamp", "")),
                "title": str(fm.get("title", "")),
                "file_path": str(filepath),
            }
            chunks = _chunk_episode_body(body)
            for chunk_idx, chunk in enumerate(chunks):
                metadata = dict(base_metadata)
                metadata["chunk_index"] = chunk_idx
                metadata["chunk_count"] = len(chunks)
                builder.add_text(chunk, metadata=metadata)
                passages_added += 1
            episodes_added += 1
        if passages_added == 0:
            return 0
        if not self._safe_build(builder, self.episode_index_path, "episodes"):
            # Raise so the caller (sleep_cycle) can thread a non-fatal warning
            # through SleepState instead of silently leaving a stale index.
            raise RuntimeError(
                f"LEANN episode index rebuild failed for {episodes_added} "
                f"episodes / {passages_added} passages"
            )
        logger.info(
            f"LEANN episode index rebuilt with {episodes_added} episodes "
            f"across {passages_added} passages"
        )
        return episodes_added

    def search_episodes(self, query: str, top_k: int = 3) -> list[dict]:
        return self._search(self.episode_index_path, query, top_k)

    # ---------- Pending (sub-threshold) index ----------

    def _load_pending(self) -> list[PendingEntity]:
        if not self.pending_store.exists():
            return []
        entries: list[PendingEntity] = []
        for line in self.pending_store.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(PendingEntity.from_dict(json.loads(line)))
            except Exception:
                continue
        return entries

    def _save_pending(self, entries: list[PendingEntity]) -> None:
        if not entries:
            self.pending_store.write_text("", encoding="utf-8")
            return
        lines = [json.dumps(e.to_dict()) for e in entries]
        self.pending_store.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def index_pending_entity(self, entity: PendingEntity) -> None:
        """Append a sub-threshold entity to the pending store.

        This does NOT rebuild the LEANN pending index — that would be O(N²)
        embedding calls when many entities are added in one sleep cycle. Call
        :meth:`rebuild_pending_index` once after the batch is complete.
        """
        entries = self._load_pending()
        name_lower = entity.name.lower()
        filtered = [e for e in entries if e.name.lower() != name_lower]
        filtered.append(entity)
        self._save_pending(filtered)

    def rebuild_pending_index(self) -> int:
        """Rebuild the pending LEANN index from the current store. Call once per batch."""
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
        """Remove and return an entry from the pending store."""
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
        if not entries:
            return
        builder = self._make_builder()
        for e in entries:
            text = f"{e.name}: {e.description}".strip()
            if not text:
                continue
            builder.add_text(
                text,
                metadata={
                    "entity_name": e.name,
                    "type": e.type,
                    "source_episode": e.source_episode,
                    "confidence": float(e.confidence),
                },
            )
        self._safe_build(builder, self.pending_index_path, "pending")

    def search_pending(self, query: str, top_k: int = 5) -> list[dict]:
        return self._search(self.pending_index_path, query, top_k)

    # ---------- Shared search ----------

    def _search(self, index_path: Path, query: str, top_k: int) -> list[dict]:
        # LEANN writes the index as a set of files sharing ``index_path`` as a
        # prefix (``<prefix>.index``, ``<prefix>.meta.json``, ``<prefix>.ids.txt``,
        # ``<prefix>.passages.jsonl``). The prefix itself is not a file or a
        # directory, so a naive ``index_path.exists()`` check always returned
        # False and the search silently short-circuited to an empty list. We
        # instead check for the meta.json sidecar as the "index is built"
        # marker — it is only written at the end of a successful build.
        meta_marker = index_path.parent / f"{index_path.name}.meta.json"
        if not meta_marker.exists():
            return []
        try:
            from leann.api import LeannSearcher
            searcher = LeannSearcher(str(index_path))
            raw = searcher.search(query, top_k=top_k)
        except Exception as e:
            logger.debug(f"LEANN search failed ({index_path.name}): {e}")
            return []

        results: list[dict] = []
        for r in raw:
            results.append({
                "score": float(getattr(r, "score", 0.0) or 0.0),
                "text": getattr(r, "text", "") or "",
                "metadata": getattr(r, "metadata", {}) or {},
            })
        try:
            searcher.cleanup()
        except Exception:
            pass
        return results


# ---------- Episode chunking ----------


def _chunk_episode_body(body: str) -> list[str]:
    """Split an episode body into overlapping passages for embedding.

    Used so that LEANN's single add_text-per-episode shape doesn't produce
    one passage per multi-thousand-token conversation, which blows past
    OpenAI's per-text and per-request embedding caps in aggregate.
    """
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
            # Prefer breaking at a newline near the boundary so we don't
            # split mid-sentence. Windows back ~300 chars.
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
