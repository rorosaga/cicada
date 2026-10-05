# Audit batch 1 — storage integrity (A02, A01, K01)

Source: [`docs/goals/audit-2026-10-02/README.md`](../goals/audit-2026-10-02/README.md) (revalidated on `dev`
`efd5386e`, 2026-10-05: all three still reproduce with `repros/storage.py`). Branch `fix/audit-storage-integrity`.

## Global constraints

- The filesystem stays the single source of truth; no database, no new tracked file in a bank.
- Capture keeps running during Sleep (no capture refusal, no Sleep-wide lock).
- No LLM, no network, no paid call; synthetic `/tmp` banks only.
- Three separate guarantees, three separate tests: atomic replacement (A02), revision-checked retirement (A01),
  unique id allocation (K01). One does not imply another.

## Rulings

- **R1 (A02).** `markdown_parser.write` renders the whole document into a hidden sibling temp file
  (`.<name>.<random>.tmp` — never matches a `*.md` scan), `fsync`s it, and `os.replace`s it over the destination.
  An existing destination's permission bits are copied to the temp file; a new file gets `0o666 & ~umask`, the mode
  `Path.write_text` gave it. A symlinked destination is replaced at its resolved target, so the link survives as it did
  before. A failed write unlinks the temp file and re-raises. The file is `fsync`ed; the directory is not (the guarantee
  chosen is "never a torn or empty page", not "the rename survives power loss").
- **R2 (K01, allocation).** `markdown_parser.write_new` creates a file *without ever replacing one*: the same staged
  temp file is hard-linked to the destination (`os.link` fails with `FileExistsError` if the name exists — atomic, no
  lock, works across processes), then the temp name is unlinked. Filesystems without hard links fall back to an
  `O_CREAT | O_EXCL` write.
- **R3 (K01, allocation).** `episode_ids.create_episode(episodes_dir, frontmatter, body)` writes a NEW episode under
  `frontmatter["id"]` with `write_new`; on `FileExistsError` it re-mints with `next_episode_id` (the competitor's file
  now exists, so the max moves), updates `frontmatter["id"]` and retries (bounded). Every capture writer that minted with
  `next_episode_id` + `write` calls it: MCP `save_episode`, transcript capture, the stager's `write_new`, notes, calendar,
  page read, Telegram, the media ingestor (both), watch and check records. Demo-bank seeders are single-process writers
  into a bank capture never touches (`demo_guard`) and are left alone.
- **R4 (K01, dedup + read-modify-write).** `episode_ids.episode_lock(episodes_dir)`: an exclusive `fcntl.flock` on the
  episodes **directory's own fd** — cross-process, nothing created in the bank, nothing for git to see — wrapped in a
  per-directory `threading.RLock` so it is re-entrant within a thread. It is held only for one short operation:
  - transcript capture's find-session-or-create (one episode per session, G104, across processes);
  - MCP `save_episode`'s content-hash dedup + create;
  - each stager read-modify-write of an existing episode (`update_in_place`, `_refresh`, `reattribute`, `_restamp`,
    `_repoint`, `_tombstone`) — per operation, never a whole import, so a 10 s import never stalls the Stop hook;
  - Sleep's retirement of one episode (R5).
  Lock order is always process lock (`_lock`, `STAGE_LOCK`) → episode lock; nothing takes them the other way.
- **R5 (A01).** `_get_unprocessed_episodes(with_body=True)` records `revision = sha256(body)` of exactly the text handed
  to extraction. `_mark_episodes_processed` re-reads each file **under the episode lock** and flips `processed: true`
  only when the current body hashes to the selected revision; a changed episode stays `processed: false` (capture already
  set it so) and is logged. A dict without a `revision` (legacy callers) retires as before. The function returns how many
  it retired, and `episodes_processed` reports that number. The revision is content-derived, so legacy files without a
  stored hash need no migration.

## Files

| File | Change |
|---|---|
| `api/services/markdown_parser.py` | `_render`, `_stage`, atomic `write`, new `write_new` |
| `api/services/episode_ids.py` | `episode_lock`, `create_episode`, `body_revision` |
| `api/services/sleep_cycle.py` | `revision` on selection; locked, revision-checked `_mark_episodes_processed` |
| `api/services/transcript_capture.py` | episode lock around find-or-create/update; `create_episode` |
| `api/services/episode_staging.py` | `create_episode` in `write_new`; episode lock per existing-file write |
| `api/services/mcp_tools.py` | dedup + create under the lock; dead fallback writer removed |
| `notes_sync`, `calendar_registry`, `page_read`, `telegram_capture`, `media_ingestor`, `watch_record`, `check_record` | `create_episode` |
| `api/tests/test_storage_integrity.py` | new regression tests (below) |
| `docs/architecture/storage.md`, `capture-and-sleep.md` | the three guarantees |

## Tests (written first; each fails on `efd5386e`)

1. A02: an encode failure mid-write (`\ud800` in the body) raises and leaves the original bytes intact, with no temp
   file left; mode bits survive a rewrite; a new file gets the umask mode; a symlinked page stays a symlink.
2. K01: with `next_episode_id` forced stale (what a concurrent process causes), MCP `save_episode`, transcript capture
   and the stager each write a second file instead of replacing the first; eight spawned processes calling
   `create_episode` for one date produce eight distinct files; `episode_lock` blocks another process.
3. A01: select → capture updates the session episode (real `capture_transcript`) → retire: the episode stays queued
   with the new body; a source-keyed stager edit likewise; an unchanged episode retires once; retirement waits while
   another holder has the episode lock.

## Verification

`api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` with `CICADA_CAPTURE=off`,
`PYTHON_DOTENV_DISABLED=1`, fetch gates off, a `/tmp` home; compare with the known baseline failures.
`repros/storage.py` must print `old_file_preserved: true` and `new_revision_marked_processed: false`.

Not in scope: A04 (its own PR), stale read-modify-write decisions in other writers, directory `fsync`.
