# An agent's edit of a source is a contribution (G244, ruling 76)

Owner 2026-11-23: "if you come and change something in the transcript for example … that 'contribution' should be
documented, with your model, harness, etc. even if it is the raw file directly. this with anything, thats the
provenance value we are building from." Approved design (owner: "go ahead with the hook fix you propose"): a corrected
line stays its speaker's words, marked as corrected by the agent; the agent is named, never trusted less or more.

## The problem

An agent that edits a raw source file (a meeting transcript in a watched folder, a note in a vault folder) is
invisible: the app posts the new bytes, `folder_source` stages them as a revision (`revised`), Sleep reads only what
changed (G104) and the corrected words read as the recorder's. Every write through Cicada's own tools carries the
harness, session and model (trailers, `observer`); a direct file edit carries nothing.

## Rulings

1. **A hook records it, never the agent's memory (G105's rule).** Claude Code's `PostToolUse` on its file tools
   (`Edit|Write|MultiEdit|NotebookEdit`) runs `cicada-hook source-edit`. A shell command's edit is not seen by the hook;
   the agent declares it with `cicada source-edit <file>` from its own shell (the CLI names the calling session,
   `cli_app.caller`). Never a heuristic over mtimes: a wrong attribution is worse than none.
2. **The backend never opens the path.** The hook (the agent's own process) matches the edited file against the
   watched folders the backend lists (`GET /sources/folders`, cached by the hook), hashes the file's bytes (sha256,
   the app's `FolderScanner.sha256` of the same bytes) and posts `{folder_id, relpath, sha256, harness, session_id,
   transcript_path?, tool, at}`. Not the file's words. A file outside every watched folder posts nothing and costs one
   cached lookup.
3. **Matched by content, either order.** The record waits in a small per-bank store outside every bank and git
   (`$CICADA_HOME/…`, like `page_reads`), keyed by `(folder_id, sha256)`, expiring after 7 days. When the folder sync
   stages a file whose sha matches, the episode(s) it writes carry the contribution. When the sync landed first, the
   record attaches at once to the episode(s) whose `content_sha` and folder match (one commit, under the agent as
   `Cicada-Author`, `Cicada-Session` its session). A split note (several episodes from one file) attaches to each
   section whose body changed.
4. **What the episode carries.** Frontmatter `contributions: [{harness, model, effort, session, at, content_hash,
   ranges}]`, newest first, at most 20. `model`/`effort`: the transcript's last agent turn when the hook gave a
   `transcript_path` that `transcript_capture.validate_transcript_path` accepts, else the session's captured episode's
   last agent turn, else omitted — never guessed. `content_hash` is the episode's body hash after the edit; `ranges`
   are the changed character ranges of that body against the body it replaced (`episode_revision.diff`; the replaced
   body is in hand at sync time, from git via the revision's `previous_hash` afterwards). Kept through later edits; not
   part of `content_hash`.
5. **Derived on read, one shape.** `source_spans`: a span of an episode whose current `content_hash` equals a
   contribution's and that overlaps its `ranges` is `corrected_by {harness, model, at}`; when the body moved on since,
   the episode-level "edited by" stays and no span is marked. The wire gains `SourceSpan.corrected_by` (null when
   none), the recall detail one line, the app one note beside the citation: "Corrected by Claude Code · <model>".
   Trust, `evidence_kind` and the speaker are unchanged.
6. **The run says it.** The Corrections record (`corrections_record`) names who edited each revised episode it lists
   (`by: harness`), the commit-body line too (`corrections: revised ep_… (edited by claude-code)`).

## Tasks

- **A — backend** (`api/services/source_edits.py` new; `folder_source`, `episode_staging`, `source_spans`,
  `corrections_record`, `sleep_cycle` commit body, `schemas`, a route `POST /capture/source-edit`, the CLI command
  `cicada source-edit`, tests).
- **B — the door and the surfaces** (`api/hooks/source_edit.py` stdlib, `plugins/cicada/hooks/hooks.json` PostToolUse,
  `plugins/cicada/scripts/cicada-hook` case, `install.sh` registration where it registers hooks without the plugin,
  the skill line, the app's citation note and its decoder, docs: `capture-and-sleep.md`, `storage.md`, `api.md`,
  `mcp.md`, `CLAUDE.md` rail lines, TODO ruling 76, G244 row, feature-status).

## Not in this change

Cursor (`afterFileEdit`), Codex and Gemini hooks: the same post, one follow-up each (G244). An agent's direct edit of
the bank itself (already forbidden by the contract) is not detected here.
