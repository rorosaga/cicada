# Code audit 2026-10-05 — the report

The owner's targeted code audit of `dev` at `3d28cd0cd938`, kept as it was reported. Its outcome per finding (the
regression test, the fix and its PR) is in [`STATUS.md`](STATUS.md); every finding below was fixed and merged on
2026-10-05/06. The gaps the fixes' own reviews disclosed are backlog row **G183** (and G21 for the dedup sweep).

**Headline:** the highest-priority improvements are memory integrity and provenance — claim loss and incorrect commit
attribution were reproduced. No repository files were changed by the audit; untracked assets were left alone and no
personal bank was read.

| Priority | Finding and evidence | Improvement |
|---|---|---|
| **P1** | **Merges discard the loser's claims.** A synthetic merge preserved only the winner's claim and deleted the loser's page. Merge code: `api/services/entity_merge.py:106`. | Merge both claim sets, preserve provenance and supersession history, and repoint references before deleting the loser. |
| **P1** | **Concurrent claim writes lose updates.** Two writes both reported `written`; only one claim survived. Atomic replacement protects individual writes, but the read → reconcile → write sequence was unlocked. Write path: `api/services/agentic_write.py:494`. | Add a cross-process transaction lock covering the page update and its commit. |
| **P1** | **Inbox resolutions commit unrelated changes as the user.** A probe committed an unrelated episode with `Cicada-Author: user`; the resolution called the whole-bank commit helper. Resolution commit: `api/services/git_service.py:1405`. | Commit explicit touched paths and protect edits already present on those paths. |
| **P2** | **A partial embedding-model switch corrupts retrieval rankings.** Tables record their own models, but queries selected the global model; rebuilding entities alone made episode search return the wrong conversation. Query model selection: `api/services/vector_index.py:125`. | Select the model per table; group multi-kind searches by model. |
| **P2** | **Dropped entities still surface through semantic recall.** A freshly indexed dropped page was returned and rendered; the vector filter excluded only archived pages from its active tier. Status filter: `api/services/vector_index.py:495`. | Filter dropped pages using the current markdown state before ranking, emitting hints or rendering recall. |
| **P2** | **Older app responses overwrite newer ones.** Using the actual `ProjectsCache` code, the cache changed from `new` back to `old` when requests completed out of order; its epoch protected bank switches but not overlapping refreshes within one bank. `app/CicadaApp/Sources/CicadaApp/Views/Projects/ProjectsCache.swift:72`. | Coalesce refreshes or track request generations per cached resource. |
| **P2** | **Failed app refreshes can remain stale indefinitely on a healthy SSE connection.** Pending domains retried only through version events; the server emits those only when the version changes, and the client ignored heartbeats (statically traced). `app/CicadaApp/Sync/Store.swift:593`, `SyncEngine.swift:95`. | Schedule bounded retries for pending domains while connected. |
| **P2** | **MCP recall embeds the same query twice.** A probe counted separate embeddings for entity and episode retrieval. `api/services/mcp_tools.py:1179` (entities), `:1266` (episodes). | Reuse one query embedding per model across both searches. |
| **P2** | **Version stamps can miss edits.** With one future-dated file, editing another left the maximum-mtime stamp unchanged — graph caches and ETags stay stale after clock changes or timestamp-preserving copies. `api/services/graph_builder.py:696`, `api/services/bank_index.py:148`. | Fingerprint filenames, sizes and nanosecond mtimes using the existing shared directory scan. |

**Release versioning** was left to **G182**: the app hardcoded version `0.2` (`app/CicadaApp/bundle.sh:89`) while the API
declared `0.1.0` (`api/pyproject.toml:3`) — establish one release version source and a distinct build identifier.
(#182's `VERSION` file closed it.)

**Validation as reported:** 84 selected backend tests and 23 selected Swift tests passed, and eight synthetic probes
reproduced the findings. It was a targeted code audit: the full suites were not run and the live app was not inspected.

**Recommended order:** the three P1 defects first — before G180 (the CLI) adds another memory-writing surface — then
model selection and app cache ordering. That is the order the fixes landed in.
