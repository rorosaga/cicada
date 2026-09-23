# Local sources: folders, papers, note-takers (Track L) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two new kinds of Awake capture, both read by the app and parsed by the backend. (1) A
**watched folder of notes** lives in Cicada: every markdown file becomes one episode that updates
in place when the file is edited, keeps its identity when the file is renamed, and is stamped (never
removed) when the file is deleted; files an agent wrote are kept but never credited to the person.
Reference lists and bare arXiv/DOI mentions in those files become **paper pages** — `media` pages
with `media.kind: paper` — whose card leads with *why the paper is in your memory* (the person's own
annotation, the project that cites it, the section it is filed under, each a span you can open) and
puts the abstract underneath as a dated cache fetched from the official arXiv and Crossref APIs.
(2) **Wispr Flow** meetings and Scratchpad notes arrive on their own, with every utterance keeping
its speaker, so a colleague's sentence is never recorded as the owner's words; dictation history
comes in only when the person turns it on. Underneath both: one G20 stager every source shares,
per-turn chronology beside the body, and one secret/one-time-code scrub on **every** episode writer.

**Architecture:** One seam first — the G20 stager moves out of `api/routers/conversations.py` into
`api/services/episode_staging.py` and gains an `EpisodeDraft` shape, a `turn_index` sidecar,
rename-by-content and tombstones, with the chat importers calling it through their old names so
their behaviour is byte-identical. Each new source is then a pure backend parser that produces
drafts (`folder_source.py`, `papers.py`, `wispr_flow.py`), a small router
(`api/routers/local_sources.py`), and an app-side reader that owns the disk (`FolderScanner` +
`FSEventsWatch` and `WisprFlowReader`, driven by one `LocalSourceWatcher`) and posts bytes or a
whitelisted projection. **The backend never opens the folder
or `~/Library`.** No LLM runs anywhere in this track's capture path; paper metadata is a gated,
rate-limited HTTP read of two official APIs, and the one LLM step that touches papers is the
existing G102 `link_recon` over the stored abstract on the Sleep tail. No new ETag component, no new
Store domain, no `VersionVector` change.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic (`api/`), SwiftUI + XCTest + SQLite3 + CoreServices
FSEvents + CryptoKit (`app/CicadaApp`), markdown + git bank.

**Spec:** `docs/superpowers/specs/2026-09-23-round3-meadow-reach-provenance-design.md` — Decisions
**9** and **10** and Wave-1 rulings **R-F1 … R-F3** (Track F) and **R-N1 … R-N4** (Track N), which
this track delivers together. Research (session scratchpad, not committed): R7 §3 (folder + papers +
why-it-matters + re-sync), §4 (note-takers, the Wispr Flow schema, the `EpisodeDraft` seam), §5.1
(per-turn chronology); R3 §4 P3 (scrub on every writer). Backlog rows this track files: **G133**
(watched folder + papers) and **G134** (note-takers, Wispr Flow first), with cross-references on
**G2, G20, G43, G95, G121**. Standing rulings that bind: TODO.md rulings 3 (markdown+git is the only
source of truth) and 4 (scheduled cycles never spend plan quota — nothing here calls a model), the
2026-09-03 no-prices-no-tokens ruling, ETag ship-together, the privacy rule, portability, and the
ToS rail in CLAUDE.md "Reaching the outside world".

`<worktree>` below is the track's git worktree (`.worktrees/l` under the repo root, branch
`feat/local-sources`, based on `dev` @ `f2d31ef`). `<scratch>` is any directory OUTSIDE the repo
(the session scratchpad) — it holds the two helper files Tasks 7 and 8 extract from this plan,
which are never committed. `<plan>` is this file,
`<worktree>/docs/superpowers/plans/2026-09-23-local-sources.md`.

**This plan was dry-run end to end before hand-off** (critic pass, 2026-09-23): every code block of
Tasks 1–7 was applied to a scratch copy of `f2d31ef` exactly as written (plus the fixes folded in
below), and the result reached backend **2317 passed + 5 failed = 2322**, the 5 being
`test_logo_manifest.py` cases that read the app tree the scratch copy did not have (they pass in the
worktree), and Swift **1039 executed, 0 failures** (with `api/tests/fixtures/video_urls.json`, which
`VideoRefTests` reads from the repo root, copied in). No new warning in any new or touched Swift
file. Task 8's script ran clean against copies of the three docs. A failure you hit is therefore
drift or a typo, not a design gap — read the cited code before changing the design.

---

## What the code actually does today (verified against `f2d31ef`)

**The G20 stager lives in a router.**
- `api/routers/conversations.py:746-853` `_stage_episodes(episodes, episodes_dir)` — pre-scans every
  episode with `markdown_parser.parse` (`:779-791`, a full YAML parse of the whole directory per
  call), renders the body as `f"{msg['role']}: {msg['text']}"` lines (`:799-801`), hashes
  `sha256(body)[:12]` (`:803`), then create / skip / update-in-place. `:856-868`
  `_normalise_import_timestamp`, `:871-921` `_write_new_episode`, `:924-943`
  `_update_episode_in_place` (which never pops a stale `processed_by` — G114 R6 says it is written
  only beside `processed: true`; `transcript_capture.py:286` does pop it).
- Per-message timestamps are parsed (`:284-288`) and then **discarded**: the body keeps only
  `role: text`, so a span can say *where* in an episode but never *when* or *which turn*.
- Callers: `api/routers/conversations.py:74` and `api/routers/banks.py:28,232`; tests call
  `conv._stage_episodes` and `conv._write_new_episode` directly (`api/tests/test_conversations.py:106-318`).
- **`turns:` is already taken.** `api/services/transcript_capture.py:261,284` writes
  `turns: <int>` on every hook-captured episode; `api/tests/test_capture_transcript.py:132,164` pin it.

**The scrub runs in one writer of eight.** `api/services/transcript_extract.py:49` (`REDACTED`),
`:80-93` (`_SECRET_RES`, `_BASE64_RUN_RE`), `:127-145` (`scrub_secrets`), called only at `:219`. No
one-time-code rule exists. The other writers — every module that mints an episode id
(`grep -rn "next_episode_id(\|max_suffix_by_date(" api mcp`) — store text as given:
`api/routers/conversations.py:778` (the stager), `api/services/telegram_capture.py:515` (writes
`:528`, hashes `:506`), `api/services/media_ingestor.py:1514` (body `:1522-1525`, writes `:1558`),
`api/services/notes_sync.py:228` (body `:234`, writes `:250`), `api/services/calendar_registry.py:351`
(body `:356` — an ICS description is exactly where meeting passcodes live — writes `:372`),
`api/services/demo_bank.py:156` (writes `:186`), `mcp/server.py:2037` (`handle_save_episode`, hashes
`:2039`, writes `:2071`, fallback `:2078`), and `api/services/transcript_capture.py:248` (scrubbed
inside the extractor).

**Evidence credits every unmarked line to the owner.** `api/services/evidence.py:64` `_TURN_RE`
knows `user|human|assistant|ai|system|unknown`; `:166-186` `speaker_kind` returns `user` for any
line with no marker ("every marker-less writer captures the person's own input", `:57-63`). A
`speaker:2: …` line from a meeting, or an agent-written research file, would therefore be credited
to the person. `:195-224` `verify(..., text=None)` has no way to be told otherwise;
`:255-267` `attach_relationship_evidence` is what Stage 1 calls (`api/services/entity_extractor.py:374`,
from the episode dicts built at `api/services/sleep_cycle.py:1338-1355`). `api/services/claims.py:59`
`EVIDENCE_KINDS = ("user", "assistant", "page", "reasoning")`, pinned by
`api/tests/test_claims_evidence.py:12`. `api/routers/episodes.py:43-59` derives `kind` for
`GET /episodes/{id}/span` the same way.

**Nothing ingests a folder or a paper.** `media_ingestor.parse_upload` rejects `.md` and reads a
`.txt` as a URL list (`:1169-1275`); `write_media_entity` (`:1604-1680`) has no paper metadata;
`link_enrichment.default_fetch` (`:559-611`) would fetch `arxiv.org/abs/*` like any page, with no
per-host crawl delay, through the §2b tier of `scan_backfill` (`:650-703`) and the in-cycle
`_candidates` (`:199-226`) — arXiv's robots file asks for 15 s between hits and its API terms forbid
scraping. `url_index.json` entries are `{media_entity_id, episode_id, url, title, media_type,
thumbnail, saved_at}` (`media_ingestor.py:1764-1781`) and `GET /sources` lists one Feed row per entry
(`api/routers/sources.py:508-601`).

**Channels are a fixed list.** `api/services/channel_registry.py:34-49` `CHANNEL_IDS` (13 ids) is
pinned verbatim by `api/tests/test_source_channels.py:244-250,315-324` and mirrored in
`app/…/Views/Capture/ChannelMarks.swift:19-23`,
`app/…/Tests/CicadaAppTests/IntegrationsViewTests.swift:23-35` and
`SourceChannelTests.swift:71-78` (every id needs a `+` tile). `build_channels` returns
`[channels[cid] for cid in CHANNEL_IDS]` (`:293`). `source_overview.py:27` `KIND_ORDER`,
`:81-102` `CATALOG`, `:139-155` `source_key`, `:158-178` `_new_state`, `:181-293` `build_overview`.
`sync_service.components` (`:137-194`) folds `url_index.json`, `feeds.yaml`, `calendars.yaml` and
`sync_state.json` into `sources` (`:159-165`); `bank_index.dir_stamp` counts only `.md` files, so a
new JSON registry under `sources/` is invisible to every ETag unless folded in there.

**App side.** `Services/BrowserWatch.swift:140-352` `BrowserWatcher` — per-directory
`DispatchSource` watches, size+mtime `BrowserFileSignature`, 1.2 s debounce, 5 s floor, `catchUp` on
launch, `states`/`errors` read by four views through `state(for:)`/`error(for:)` (`:236-237`;
`SourceCardGrid.swift:155-161`, `ChannelSourceView.swift:15,69`, `SourceDetailView.swift:21,39`,
`ConnectedChannelRow.swift:36,116`). `Services/BrowserFiles.swift:11-43` `BrowserFile` +
`:58-93` `BrowserFileError` (the Full Disk Access fix, rendered by `FullDiskAccessHint`,
`Views/Capture/Sheets/BrowserImportPanels.swift:48-60`). `CicadaApp.swift:47,103,138` owns and starts
the watcher. `Models/IntegrationCategory.swift` has six categories with no home for notes or
meetings; `Views/Settings/IntegrationsView.swift:97-108,139-172` renders them.
`Views/Capture/OriginIconography.swift` is the one mark map (installed app icon → bundled PNG → SF
Symbol, `:179-220`). The app is **unsandboxed** (`Views/Common/VideoPlayerView.swift:57-62`); no
SQLite, FSEvents or CryptoKit use exists yet. Feed search matches title, site and tags only
(`ViewModels/FeedViewModel.swift:60-68`); `FeedRow` shows `item.mediaType` as its pill
(`Views/Feed/FeedView.swift:297-304`). `EntityDetailCard.contentTab` renders `MediaPreview` for any
media entity (`Views/Graph/EntityDetailCard.swift:333-340`). **The Meadow tokens (`quoteFont`,
`displayFont`, `CicadaMotion`, `hoverLift`, `iconHover`, `liquidGlass`) are not on this branch.**

**Baselines on this base:** backend **2225 passed**, Swift **1012 executed, 0 failures**, graph JS
green.

---

## Global Constraints

- Work ONLY in `<worktree>/`. Every shell command is `cd <worktree> && <cmd>` with the absolute path
  (zoxide hijacks relative `cd`; ignore its stderr warning). Never an unquoted `--include=*.ext`
  (zsh globs it) — quote it or use `rg`.
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari`, `~/.claude/projects`, the
  owner's research folder or his Wispr Flow data directory. The shapes this plan builds against
  (R7 §3.1 and §4.3) are the only description of them any agent gets. **Fixtures are synthetic
  only:** an `alpha-project` folder, `https://arxiv.org/abs/2401.00001`-style ids, `10.1234/…` DOIs,
  a `bob-example` meeting, `example.com`. The orchestrator ingests the real folder after merge.
- Python: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full
  `api/tests` suite must report **0 failures** (2225 passed on this base).
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
  order-dependent and pre-existing — if it is the ONLY red, re-run it alone and report both results.
- Swift: `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and
  `swift test 2>&1 | tail -20` must report **0 failures** (1012 executed on this base). Graph JS:
  `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js`. SourceKit diagnostics naming
  OTHER worktrees are noise. NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill
  the Cicada app or the launchd backend — the owner's installed app is live.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`, `.claude/`,
  `api/.venv`, or `*-report.md`. No push, no new branches or worktrees, no subagents. Ignore
  Devin/PR comments.
- **No LLM at capture time.** Nothing in `episode_staging`, `episode_scrub`, `folder_source`,
  `papers`, `paper_metadata` or `wispr_flow` calls a model, and none of them imports `litellm`,
  `engine_select` or an extractor at module level. The one deliberate exception is a *function-local*
  `from api.services import entity_resolver` in `folder_source.ensure_project` and
  `papers._concept_matcher`, for its two pure helpers `existing_by_name` and
  `_find_direct_candidate_match` (thefuzz only). `entity_resolver` itself imports `litellm` at module
  level (`entity_resolver.py:7`), so the import is kept local and nothing reachable from those two
  helpers touches an engine (R-LS13, R-LS16). Do not import `match_existing` or `resolve`.
- **The backend never opens the folder path or anything under `~/Library`.** The registry stores
  the folder's absolute path for display and relink only.
- **Network** only through `paper_metadata` (arXiv API + Crossref REST), 4 s / ≤ 512 KB, no cookies,
  one connection, never `arxiv.org/abs|pdf|html`, never a PDF stored, never behind auth; unattended
  calls gated by `CICADA_ALLOW_CONNECTOR_FETCH` (`connectors.base.network_allowed()`); the suite
  runs with that gate off and injects `fetch_fn`.
- **Fonts / numbers / tokens:** every new font through `CicadaTheme.font(size:weight:design:)`
  (`FontLiteralLintTests`), every padding and stack spacing through the spacing tokens, every count
  a person reads through `UsageFormat.count` (`CountLiteralLintTests` enforces it in `Views/Sources/`,
  `Models/SourceOverview.swift` and `Models/IntegrationCategory.swift`). Tile and popover sizes
  follow their neighbours in the same file — `IntegrationsView`'s own rows use `platformTile(…,
  size: 28)` and `VStack(spacing: 2)`, and no lint covers dimensions. Colours only through theme
  tokens (`ThemeTokenTests`). No price, no token count, no `/consumption/*` read on any surface.
- **Decode tolerance:** every new Swift wire field is optional-with-default and asserted against a
  payload that omits it.
- **Privacy:** no owner name, no author-machine path, no bank contents in code, plans, commits or PR
  bodies. The one project URL that appears (`USER_AGENT`) names the software, as
  `logos.manifest.json`'s `userAgent` already does.
- Docstrings explain **why**, citing the G-row / spec ruling / this plan's `R-LS` ruling that
  motivated the rule. Match the density of the files touched.
- Line numbers above are from `f2d31ef` and drift as tasks land — read the cited code before editing.
- **Merge note for the orchestrator:** Track O adds a `media` evidence kind and Track I reworks
  `/conversations/upload`. Both touch what Task 1 touches (`claims.EVIDENCE_KINDS`, the
  conversations router). Take the **union** of kinds; Track I should call
  `episode_staging.stage(...)` directly rather than the compat names.

---

## Rulings (binding)

The spec's **R-F1 … R-F3** and **R-N1 … R-N4** hold as written, with two exceptions and one reading,
each stated with its evidence and each listed under the open questions at the end:

1. **R-LS27** ships R-N4's "real marks" as the installed apps' own icons rather than a PNG fetched
   through `scripts/fetch-logos.sh`, because nothing Commons offers would either render or carry the
   vendor's own licence.
2. **R-LS18** uses Crossref's *public* pool where R-F3 says "polite pool". The polite pool is entered
   by sending a contact email with every request, and Cicada never sends the person's email off the
   machine; at personal scale (≤ 30 DOIs per cycle, ≥ 1 s apart, only DOIs with no arXiv twin) the
   public pool is enough.
3. **R-LS20** is how R-F1's "a deletion asks through the inbox like a bookmark removal" is read. A
   deleted file's *episode* is stamped, never removed, and never asked about — an episode is history,
   and a G129 `removal` item archives an *entity*, which an episode is not. What the inbox asks about
   is what the file alone put in memory as a page: a paper no remaining file cites.

Everything below is a decision this
plan takes where the brief left a choice (or where the brief's wording collides with the code),
with the reason, so no task re-opens it. Prefix **R-LS** (Local Sources) because round 2's Track L
already owns `R-L1 … R-L8` (brand marks) in CLAUDE.md.

**The seam (Task 1)**

- **R-LS1 — the per-turn sidecar is `turn_index`, not `turns`.** The brief names it `turns:`, but
  `turns:` is already an integer count on every hook-captured episode (`transcript_capture.py:261,284`,
  pinned by `test_capture_transcript.py:132,164`). One key with two shapes is the bug a reader gets
  wrong. The transcript writer is left alone.
- **R-LS2 — rows are `[offset, ts, speaker]` lists, written only on new or changed episodes, and
  omitted above 4,000 rows.** Lists, not dicts: every row is parsed by `bank_index` on a cold scan,
  and a dict row costs three more YAML scalars for its keys. Omitted, never truncated, above
  `MAX_TURN_INDEX_ROWS`: a truncated index would attribute every later offset to the last kept turn
  — absent beats wrong. No backfill: an unchanged re-import skips, so existing episodes never
  rewrite for a sidecar (git noise, and a `processed: false` flip, for nothing).
- **R-LS3 — the stager's pre-scan reads `bank_index`'s cached frontmatter.** The old pre-scan
  re-parsed every episode on every call (`conversations.py:779-791`); a watched folder stages on
  every save, which made that a second or more per keystroke-save on a real bank. `bank_index`
  already decides what changed with one `scandir` (`bank_index.py:1-7`).
- **R-LS4 — the content hash describes the stored (scrubbed) body; a match on the unscrubbed render
  counts as unchanged.** Otherwise the day the scrub learns a rule, every legacy episode that held a
  secret re-imports as "updated" (a re-queue — 💸 on a key) and every id-less format forks a second
  copy. Scrubbing what is already stored is a separate, disclosed migration, not this track.
- **R-LS5 — the one-time-code rule is connector-anchored, not a character window.** R3 P3 proposed
  "a keyword within ~24 characters of 4–8 digits"; that also redacts years in prose ("wrote code in
  2019"). The rule is keyword + optional `is|was` + optional `:=#-` + digits, or digits + `is
  your|the` + up to two words + keyword. Only the digits are replaced.
- **R-LS6 — one scrub module, and a lint that finds writers by what makes them writers.**
  `api/services/episode_scrub.py` owns the rules; `transcript_extract.scrub_secrets` becomes a
  name for `episode_scrub.scrub`. A source lint fails when any module under `api/` or `mcp/` that
  mints an episode id (`next_episode_id(` / `max_suffix_by_date(`) does not reference
  `episode_scrub` — minting an id is G114's own definition of an episode writer, so a ninth writer
  cannot arrive unscrubbed. `transcript_capture.py` is the one delegate (it scrubs inside the
  extractor) and the lint checks the extractor instead.
- **R-LS7 — `speaker` is a fifth evidence kind; `evidence_kind` overrides markers; `user` for a
  meeting speaker is opt-in by name.** A `speaker:<label>:` line is someone other than the owner
  (R-N2), so it cannot be `user`, and `assistant` would call a colleague a model. The episode-level
  `evidence_kind` accepts only `user` and `assistant` (folder authorship, R-F2) and beats markers
  (a markdown file quoting a chat is still the file author's words). A speaker is rendered `user:`
  only when their name is one the person listed as theirs (R-LS22).

**The folder source (Task 2)**

- **R-LS8 — JSON with base64 content, not multipart.** Every existing app-reads-bytes route
  (`/sources/sync-bookmarks`, `/sources/sync-safari-tabs`) is JSON with inline data, a batch of N
  files with per-file metadata is one validated Pydantic model in JSON (multipart needs a manifest
  part matched to N file parts by name), and the backend re-hashes the decoded bytes to verify the
  app's `sha256`. The app batches at ≤ 100 files / ≤ 6 MB; the backend refuses > 200 files / > 8 MB.
- **R-LS9 — the backend stamps the device, and folder ids are readable.** `device` is
  `local_refs.current_device_id()` at registration (the app and backend share a Mac until G132);
  the app never sends one. Ids are `<label-slug≤40>-<sha1(device,path)[:6]>`, so a registry file
  and a `source_id` are legible to a person reading the bank in Obsidian. Re-registering the same
  path on the same device returns the same record (upsert).
- **R-LS10 — agent-written files are stored, searchable, and never queued for Sleep.** They are
  `processed: true, processed_by: "parser"` with `evidence_kind: assistant`. Research sweeps are the
  bulk of a research folder (R7 §3.1 measured ~1.5 of ~2.2 MB, ~130 of ~190 Stage-1 passes), their
  first-class output — the papers they cite — is extracted deterministically, and consolidating an
  agent's prose into the person's graph is exactly what R-F2 forbids crediting. Changing a glob to
  `user` in Manage and syncing again re-queues those episodes (the stager's metadata-only path).
- **R-LS11 — no "reference list" exception.** R7 §3.3 kept a references file out of Stage 1 to save
  ~29 passes; this plan does not. The person's own file is the person's words, its non-paper links
  and annotations are only ever learned by Sleep reading it, and the H2 split (R-LS12) already bounds
  an edit to one section's re-read. The preview says how many passes Sleep will spend before anything
  is staged.
- **R-LS12 — split on H2 only past 4 × Stage-1's chunk size (48,000 chars).** Sections get
  `source_id = <file id>#<heading-slug>` (`intro` for text before the first H2, `-2`, `-3` for
  repeats). Rename matching is on `(content_sha, #fragment)` so a renamed split file repoints section
  by section instead of pouring every section into the first.
- **R-LS13 — the folder names its project on the person's say-so.** Registration carries a project
  name (the app pre-fills the folder's name). It resolves with the zero-LLM half of Stage 2's
  matcher (`entity_resolver._find_direct_candidate_match`, strict then fuzzy > 85) against `project`
  pages only; with no match, a `project` page is created **because the person typed the name**
  (`Cicada-Author: user`, trigger `user/companion_app`) — the same authority `PUT /settings/owner`
  uses to create the owner page. The page carries `paths: [{path, device}]` (a new optional key,
  G27-shaped). This is what `cited-in` claims point at. **The say-so is "Start watching", not "Look
  inside":** the add sheet registers with `projectName: ""` to get the folder id its preview needs,
  and sends the project name only when the person starts watching (the same `POST /sources/folders`,
  an upsert by R-LS9) — so looking inside and cancelling never leaves a new `project` page behind.

**Papers (Tasks 3–4)**

- **R-LS14 — paper pages have id-based ids and are never duplicated.** `media-arxiv-<id>` /
  `media-doi-<sha1[:10]>`, so identity does not depend on which title arrived first. Before
  creating, the parser looks for the paper among existing saves (any `url_index.json` entry whose URL
  names the same arXiv id or DOI — a bookmark of `arxiv.org/pdf/<id>v2` included) and upgrades that
  page in place (`media.kind: paper`, a `paper:` block, the tag). The second canonical URL is an
  `alias_of` entry in `url_index.json`; `GET /sources` and the `files` channel count skip aliases,
  so one paper is one Feed row.
- **R-LS15 — paper claims have their own deterministic writer, not `agentic_write.write_claim`.**
  `write_claim` re-reads the owner file, globs `entities/` and reconciles per call
  (`agentic_write.py:306`, `:153-164`, `:417`); a references file re-parses hundreds of papers on every
  save. `papers.apply_claims` does one parse + one write per page per episode, with claim ids
  derived from `(paper, predicate, object, observer, context)`, **this file's spans replaced rather
  than appended** (`_reinforce` would otherwise stack a stale span per edit), and a claim the file no
  longer supports **closed with `valid_to`**, never deleted. Precedent: `link_recon` and
  `link_enrichment` already write claims directly.
- **R-LS16 — `about` uses the zero-LLM half of `match_existing`.** The brief says "via
  `match_existing`"; its second half is an LLM judge (`entity_resolver.py:394-422`), which cannot run
  at capture. The direct matcher runs against `concept|tool|skill|project` pages; an unmatched section
  is kept in `paper.sections` and as a tag, never a page, never a pending candidate (that would load
  the embedding model at capture). The LLM relating of a paper to the graph is `link_recon` over the
  stored abstract, which already runs on the Sleep tail (G102 R6).
- **R-LS17 — paper writes wait while a Sleep cycle runs.** Episodes are always staged (every capture
  writer does that during a cycle); the entity writes are not, because Stage 5 may be rewriting the
  same pages. The folder is flagged `papers_pending`; the next folder sync or the Sleep tail
  re-parses the folder's live episodes (idempotent by R-LS15).
- **R-LS18 — metadata comes from two APIs, paced and bounded.** arXiv: `export.arxiv.org/api/query`,
  ≤ 50 ids per request, ≥ 3 s between requests, one at a time. Crossref: `api.crossref.org/works/{doi}`,
  public pool (no `mailto`, no email ever sent), ≥ 1 s between requests. Only DOIs without an arXiv
  twin go to Crossref. 403/429 or a transport failure stops that API for the run; a missing record
  backs off 30 days. User-triggered: the folder sync's `?resolve=true` schedules one background run
  behind a process lock (a second trigger is a no-op, not a 409 — nothing was asked of the person).
  Unattended: the Sleep tail, behind `CICADA_ALLOW_CONNECTOR_FETCH`, capped at 200 arXiv ids and 30
  DOIs per cycle.
- **R-LS19 — the abstract is a world-tier cache.** It is the page's `## Description` plus one
  `describes` claim: `source_trust: external`, `observer: external:arxiv|external:crossref`,
  `authored_by: cicada`, `recorded_at` = fetch date, a `page` span over the description. Shown as
  "Context (from arXiv, as of <date>)" under the personal tier (G121). `link_enrichment` never
  fetches a paper page: `scan_backfill` and `_candidates` skip `media.kind: paper`.
- **R-LS20 — a paper the folder created and no file cites any more gets a `removal` item.** The G129
  shape exactly (`keep`/`remove`, no free text, `remove` archives), so R-F1's "a deletion asks through
  the inbox like a bookmark removal" is met without a new kind. A paper that was saved another way
  first (its page `origin` is not `folder`) is never proposed. The file's episode itself is only
  stamped (R-F1).

**Wispr Flow (Tasks 5–6)**

- **R-LS21 — two whitelists, one per side, and a forbidden list both sides test.** The app selects
  only whitelisted columns that exist (`PRAGMA table_info`), never `SELECT *`, and filters deleted,
  demo and unfinalized meetings in SQL so they never leave the file; the backend reads only the same
  whitelisted keys from what arrives and re-applies the filters. `audio`, `builtInAudio`,
  `screenshot`, `axText`, `axHTML`, `textboxContents`, `pastedText`, `url` and `asrText` are named in
  a `forbidden` list that tests prove is disjoint from every whitelist and absent from every payload.
- **R-LS22 — the note-taker's words are `assistant:`; a speaker is `speaker:<label>:`; `user:` is by
  name only.** Summary, notes and to-dos are written by Wispr Flow's model, so they render under an
  `assistant:` line — under-crediting the owner is the safe direction, over-crediting is what R-N2
  forbids. An utterance's label is the speaker's name slug, else their numeric id; it is `user:` only
  when the name matches one of `owner_speaker_names`, a list the person fills in themselves (the app
  pre-fills nothing into it). Emails are dropped from names and participants.
- **R-LS23 — dictation is opt-in, per UTC day, merged server-side.** The app reads `History` only
  when `include_dictation` is on and posts incrementally (cursor on the raw `timestamp`); the backend
  rebuilds the stored day from its own `turn_index` and merges, so one day stays one episode however
  many posts it took. Dictation into a password manager (a fixed bundle-id deny list) is dropped. With
  the opt-in off, the backend refuses history rows even if an app sends them.
- **R-LS24 — to-dos become `committed-to` claims on the owner page; "to-dos in the Inbox" is
  deferred.** The claims are `observer: agent`, confidence 0.5 (Wispr's model extracted them, and a
  to-do may be someone else's), with a span on the to-do line. There is no `todo` inbox kind, and
  adding one touches `inbox_service.resolve` and the inbox card (G60/G113 surfaces) — out of this
  track. No toggle ships for it, so no control does nothing.

**Surfaces (Tasks 2, 5, 6, 7)**

- **R-LS25 — local-source channels are dynamic.** `folder:<id>` rows are appended for registered
  folders and `wispr-flow` only once it is turned on, after the fixed `CHANNEL_IDS`, so the four
  mirrors of that list and the `+`-tile test do not move. Integrations gains **Notes & files** (Apple
  Notes moves there from Files & imports, with every folder and an "Add a folder" row) and **Voice &
  meetings**; the Sources grid gains a `voice` kind titled **VOICE & MEETINGS**; folders sit under
  FILES & IMPORTS.
- **R-LS26 — watch lights ride `BrowserWatcher`.** The new `LocalSourceWatcher` publishes its
  `BrowserWatchState` per channel through `BrowserWatcher.publish(_:error:for:)`, so the four views
  that already call `state(for:)`/`error(for:)` light up with no edit and `SourceLiveness` reads
  "Watching". `BrowserStatusLight` gains a `channelId` so its help text stops talking about bookmarks
  on a folder card.
- **R-LS27 — marks: the installed app's own icon, no bundled PNG in this track, no Granola row
  (refines R-N4).** Wispr Flow resolves through `com.electron.wispr-flow` and Obsidian through
  `md.obsidian` — the first rung of the Track L precedence (R-L1: Cicada only offers the row because
  it reads that app's files, or, for Obsidian, only shows the row when the app is installed), so the
  row always wears the vendor's real, current mark, and the SF Symbol (`waveform`, `doc.text`) is the
  honest fallback once an app is removed. Commons was checked on 2026-09-23 instead of assumed:
  Obsidian has a CC BY 4.0 SVG (`2023 Obsidian logo.svg`), but its row never renders without the app,
  whose icon outranks a bundled PNG — so the file would be the dead bytes `LogoAssetTests` T2 exists
  to keep out; Wispr Flow has only a third-party raster (`Wispr Flow Logo.png`, CC BY-SA 4.0 claimed
  by an uploader who is not the vendor), which the SVG-only `fetch-logos.sh` cannot take and whose
  licence line would not be the vendor's grant. The manifest and `LOGOS.md` do not change. Trigger to
  revisit: Wispr Flow publishes an SVG under a free licence, or a surface appears that draws either
  mark while the app is absent. Granola has no adapter in this track (Wispr Flow's own Granola import covers a migrated person), and a row with
  nothing to connect is what G126 removed — so no row and no mark.
- **R-LS28 — no Meadow tokens on this branch.** Provenance quotes use
  `CicadaTheme.font(size: 13, design: .serif).italic()`; the M2 pass swaps it for `quoteFont`.
- **R-LS29 — ETags: `folders.json` and `wispr_flow.json` fold into the existing `sources`
  component.** Every consumer of channel state (`/sources/channels`, `/sources/overview`) already
  hashes `sources`, and `VersionVector.mapping["sources"]` already refreshes `.channels` and
  `.sourcesOverview`. No new component, no new `extra`, no mapping change — pinned by the existing
  recipe tests.
- **R-LS30 — commit authorship.** A folder or Wispr sync is the person's own material entering
  memory: `Cicada-Author: user`, triggers `folder/sync` / `wispr-flow/sync`. Metadata and deferred
  paper parses on the tail have no person and no model in the loop: `Cicada-Author: cicada`,
  triggers `papers/metadata` / `folder/papers`. Every commit is `git_service.commit_paths` over the
  exact paths written, never `git add -A`.

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `api/services/episode_scrub.py` (new) | 1 | secrets + one-time codes; `scrub`, `scrub_body`, `record` |
| `api/services/episode_staging.py` (new) | 1 | `Turn`, `EpisodeDraft`, `StageResult`, `scan`, `render`, `stage`, `draft_from_export` |
| `api/routers/conversations.py` | 1 | stager removed; `_stage_episodes`/`_write_new_episode`/`_update_episode_in_place`/`_normalise_import_timestamp` become compat wrappers |
| `api/services/transcript_extract.py` | 1 | rules moved out; `scrub_secrets` = `episode_scrub.scrub` |
| `api/services/{telegram_capture,media_ingestor,notes_sync,calendar_registry,demo_bank}.py`, `mcp/server.py` | 1 | `episode_scrub.scrub_body` before hash/write |
| `api/services/evidence.py`, `api/services/claims.py` | 1 | `speaker` kind, `_SPEAKER_RE`, `source_document`, `kind_for`, `turn_at`, `kind_override` |
| `api/services/entity_extractor.py`, `api/services/sleep_cycle.py` | 1 | pass `evidence_kind` into Stage-1 evidence |
| `api/routers/episodes.py`, `api/models/schemas.py` (`EpisodeSpan`) | 1 | span kind via `kind_for`; `turnNumber/turnCount/turnTs/turnSpeaker` |
| `api/services/folder_source.py` (new) | 2, 3 | registry, globs, relpath safety, H2 split, drafts, sync, project anchor, commit |
| `api/routers/local_sources.py` (new), `api/main.py` | 2, 3, 4, 5 | `/sources/folders*`, `/capture/local-source/wispr-flow*` |
| `api/services/channel_registry.py` | 2, 4, 5 | `_local_channel`, dynamic folder/wispr rows, alias-free `files` count |
| `api/services/source_overview.py` | 2, 5 | `folder:<id>` rows, `wispr-flow` catalog row, `voice` kind |
| `api/services/sync_service.py` | 2, 5 | `sources` component folds `folders.json` + `wispr_flow.json` |
| `api/services/papers.py` (new) | 3, 4 | parse, pages, aliases, claims, removals, reconcile, detail |
| `api/services/paper_metadata.py` (new) | 4 | arXiv/Crossref fetch, parse, apply, resolve, background run |
| `api/services/link_enrichment.py` | 4 | papers skipped by `_candidates` and `scan_backfill` |
| `api/routers/sources.py`, `api/routers/entities.py` | 4 | alias skip + `kind`/`paper` on Feed rows; `media.kind`; `GET /entities/{id}/paper` |
| `api/services/wispr_flow.py` (new) | 5 | settings, whitelists, drafts (meetings/notes/dictation), to-do claims, ingest |
| `app/…/Models/LocalSources.swift` (new) | 6 | folder and Wispr Flow wire models |
| `app/…/Services/LocalSources/{FolderGlob,FolderScanner,FSEventsWatch,WisprFlowReader,LocalSourceWatcher}.swift` (new) | 6 | the readers |
| `app/…/Services/BrowserWatch.swift`, `BrowserFiles.swift`, `APIClient.swift`, `CicadaApp.swift` | 6 | `publish`, `.wisprFlowDatabase`, endpoints, start |
| `app/…/Models/IntegrationCategory.swift`, `Views/Settings/IntegrationsView.swift`, `Views/Settings/LocalSourceRows.swift` (new) | 7 | Notes & files, Voice & meetings, add-folder sheet, Wispr panel |
| `app/…/Views/Capture/OriginIconography.swift`, `ConnectedChannelRow.swift`, `Views/Sources/{SourceDisplayName,SourceBlurb,BrowserStatusLight,SourceCardGrid,SourceHeaderCard,ChannelSourceView}.swift`, `Models/SourceOverview.swift` | 7 | marks, names, `voice`, light copy |
| `app/…/Models/Paper.swift` (new), `Views/Graph/PaperCard.swift` (new), `EntityDetailCard.swift`, `Models/Entity.swift`, `Services/APIClient.swift` (`MediaFeedItem`, `fetchPaperDetail`), `Views/Feed/FeedView.swift`, `ViewModels/FeedViewModel.swift` | 7 | the paper card, Feed badge + search |
| `docs/goals/memory-evolution.md`, `docs/goals/TODO.md`, `CLAUDE.md` | 8 | G133, G134, cross-refs, rails |
| Tests (Python) | 1–5 | `test_episode_staging.py`, `test_episode_scrub.py`, `test_episode_writers_scrub.py`, `test_evidence_speakers.py`, `test_folder_source.py`, `test_papers.py`, `test_paper_metadata.py`, `test_wispr_flow.py` (new); `test_claims_evidence.py:12`, `test_source_channels.py` (edits) |
| Tests (Swift) | 6–7 | `FolderGlobTests`, `FolderScannerTests`, `WisprFlowReaderTests`, `LocalSourceWatcherTests`, `LocalSourcesSurfaceTests`, `PaperCardTests` (new); `IntegrationsViewTests` (edit) |

---

### Task 1: The seam — one stager, one scrub, speaker-aware evidence

The branch stays shippable: every existing caller keeps its function names and behaviour; the
only visible changes are that stored text is scrubbed on every writer and that a `speaker:` line is
no longer credited to the owner.

**Files:**
- Create: `api/services/episode_scrub.py`, `api/services/episode_staging.py`
- Modify: `api/routers/conversations.py:1-13` (imports), `:743-943` (stager → compat wrappers)
- Modify: `api/services/transcript_extract.py:37`, `:49`, `:75-93`, `:127-145`
- Modify: `api/services/telegram_capture.py:506`, `api/services/media_ingestor.py:1522-1525`,
  `api/services/notes_sync.py:234`, `api/services/calendar_registry.py:356`,
  `api/services/demo_bank.py:185`, `mcp/server.py:2023-2039`
- Modify: `api/services/claims.py:59`, `api/services/evidence.py:39-43,57-65,94-105,166-186,195-224,255-267`
- Modify: `api/services/entity_extractor.py:374`, `api/services/sleep_cycle.py:1338-1355`
- Modify: `api/routers/episodes.py:43-59`, `api/models/schemas.py:689-706` (`EpisodeSpan`)
- Test: `api/tests/test_episode_scrub.py`, `api/tests/test_episode_staging.py`,
  `api/tests/test_episode_writers_scrub.py`, `api/tests/test_evidence_speakers.py` (new);
  `api/tests/test_claims_evidence.py:12-13` (edit)

**Interfaces:**
- Produces `episode_scrub.REDACTED`, `WRITERS`, `scrub(text) -> (str, int)`,
  `record(writer, count, *, bank)`, `scrub_body(text, *, writer, bank=None) -> str`.
- Produces `episode_staging.Turn`, `EpisodeDraft`, `StageResult`, `IndexEntry`, `TURN_INDEX_COLUMNS`,
  `MAX_TURN_INDEX_ROWS`, `PARSED_ONLY`, `normalise_timestamp`, `draft_from_export`, `render`,
  `content_hash`, `scan(episodes_dir)`, `write_new(...)`, `update_in_place(...)`,
  `stage(drafts, episodes_dir, *, deleted_source_ids=(), bank=None) -> StageResult`.
- Produces `evidence.OVERRIDE_KINDS`, `source_document(memory_path, doc_id) -> (text|None, fm)`,
  `kind_for(doc_id, text, start, override=None)`, `turn_at(turn_index, start) -> dict|None`;
  `verify(..., kind_override=None)`, `attach_relationship_evidence(..., kind_override=None)`.
- Consumes `bank_index.files`, `episode_ids.max_suffix_by_date/utc_now_iso/to_utc_iso`,
  `markdown_parser.parse/write`, `telemetry.UsageEvent/record`.

- [ ] **Step 1: Failing tests.**

`api/tests/test_episode_scrub.py`:

```python
"""R-N3 / R3 P3 — one scrub for every episode writer (R-LS5, R-LS6)."""
from __future__ import annotations

import pytest

from api.services import episode_scrub, telemetry
from api.services import transcript_extract as tx


@pytest.mark.parametrize("text, digits", [
    ("Your verification code is 482913", "482913"),
    ("PIN: 1234", "1234"),
    ("Passcode: 998877", "998877"),
    ("482913 is your login code", "482913"),
    ("otp=55501234", "55501234"),
])
def test_a_one_time_code_loses_its_digits_and_keeps_its_sentence(text, digits):
    out, n = episode_scrub.scrub(text)
    assert digits not in out and episode_scrub.REDACTED in out and n == 1
    assert out.split(episode_scrub.REDACTED)[0] == text.split(digits)[0]


@pytest.mark.parametrize("text", [
    "In 2019 I wrote code for alpha-project",
    "error code 404",
    "Meeting ID: 845 1234 5678",
    "The PIN pad has 12 keys",
])
def test_ordinary_numbers_survive(text):
    assert episode_scrub.scrub(text) == (text, 0)


def test_the_transcript_extractor_uses_the_same_rules():
    secret = "sk-" + "A" * 24
    text = f"key {secret} and code: 424242"
    assert tx.scrub_secrets(text) == episode_scrub.scrub(text)
    assert tx.REDACTED == episode_scrub.REDACTED


def test_scrub_body_records_a_count_and_a_writer_never_the_text(monkeypatch):
    seen = []
    monkeypatch.setattr(telemetry, "record", seen.append)
    out = episode_scrub.scrub_body("bearer " + "x" * 20, writer="calendar", bank="alpha")
    assert "x" * 20 not in out
    (event,) = seen
    assert event.kind == "capture" and event.invocations == 0 and event.bank == "alpha"
    assert event.refs == {"writer": "calendar", "status": "scrubbed", "scrubbed": 1}
    seen.clear()
    episode_scrub.scrub_body("nothing to hide", writer="calendar")
    assert seen == []
```

`api/tests/test_episode_staging.py`:

```python
"""The G20 stager as a service (R-F1 seam; R-LS1 … R-LS4, R-LS10)."""
from __future__ import annotations

from api.routers import conversations as conv
from api.services import episode_staging as st
from api.services import markdown_parser


def _draft(sid, text, *, sha=None, extra=None, queue=True, ts="2026-09-01T10:00:00+00:00"):
    return st.EpisodeDraft(
        title="alpha-project › notes.md", source_id=sid, source_updated_at=ts, timestamp=ts,
        original_date=ts[:10], source="folder", origin="folder", body=text,
        extra=dict(extra or {}), queue_for_sleep=queue, content_sha=sha, writer="folder",
    )


def _only(ep_dir):
    (path,) = sorted(ep_dir.glob("ep_*.md"))
    return path, markdown_parser.parse(path)


def test_turns_render_the_g20_body_and_index_every_turn(tmp_path):
    ep_dir = tmp_path / "episodes"
    draft = st.EpisodeDraft(title="T", source_id="uuid-1", timestamp="2026-09-01T10:00:00+00:00",
                            original_date="2026-09-01", turns=[
                                st.Turn("First question", "user", "2026-09-01T10:00:00Z"),
                                st.Turn("An answer", "assistant", "2026-09-01T10:00:05Z"),
                                st.Turn("Thanks", "speaker:2", None)])
    assert st.stage([draft], ep_dir).as_tuple() == (1, 0, 0)
    _, parsed = _only(ep_dir)
    assert parsed.body == "user: First question\nassistant: An answer\nspeaker:2: Thanks"
    rows = parsed.frontmatter["turn_index"]
    assert rows == [[0, "2026-09-01T10:00:00Z", "user"],
                    [21, "2026-09-01T10:00:05Z", "assistant"],
                    [42, None, "speaker:2"]]
    for offset, _, speaker in rows:
        assert parsed.body[offset:].startswith(f"{speaker}: ")
    assert "turns" not in parsed.frontmatter  # R-LS1


def test_the_index_is_omitted_not_truncated_past_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "MAX_TURN_INDEX_ROWS", 2)
    draft = st.EpisodeDraft(title="T", source_id="s", original_date="2026-09-01",
                            turns=[st.Turn(str(i), "user") for i in range(3)])
    st.stage([draft], tmp_path / "episodes")
    assert "turn_index" not in _only(tmp_path / "episodes")[1].frontmatter


def test_every_turn_is_scrubbed_before_its_offset_is_taken(tmp_path):
    key = "sk-" + "A" * 24
    draft = st.EpisodeDraft(title="T", source_id="s-1", original_date="2026-09-01", turns=[
        st.Turn(f"my key is {key}", "user"), st.Turn("Your verification code is 482913", "assistant")])
    result = st.stage([draft], tmp_path / "episodes")
    _, parsed = _only(tmp_path / "episodes")
    assert key not in parsed.body and "482913" not in parsed.body and result.scrubbed == 2
    for offset, _, speaker in parsed.frontmatter["turn_index"]:
        assert parsed.body[offset:].startswith(f"{speaker}: ")


def test_a_legacy_unscrubbed_hash_counts_as_unchanged(tmp_path):
    ep_dir = tmp_path / "episodes"
    ep_dir.mkdir()
    key = "sk-" + "B" * 24
    raw = f"user: here is {key}"
    markdown_parser.write(ep_dir / "ep_2026-09-01_001.md", {
        "id": "ep_2026-09-01_001", "timestamp": "2026-09-01T10:00:00+00:00", "source": "claude",
        "title": "T", "processed": True, "content_hash": st.content_hash(raw),
        "source_id": "uuid-9", "source_updated_at": "x"}, raw)
    draft = st.EpisodeDraft(title="T", source_id="uuid-9", original_date="2026-09-01",
                            turns=[st.Turn(f"here is {key}", "user")])
    assert st.stage([draft], ep_dir).as_tuple() == (0, 0, 1)  # R-LS4


def test_a_tombstone_and_a_new_id_with_the_same_sha_repoint_the_episode(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:a.md", "# A\nbody", sha="s1", extra={"relpath": "a.md"})], ep_dir)
    path, before = _only(ep_dir)
    result = st.stage([_draft("folder:f1:docs/a.md", "# A\nbody", sha="s1",
                              extra={"relpath": "docs/a.md"})],
                      ep_dir, deleted_source_ids=["folder:f1:a.md"])
    assert (result.renamed, result.created, result.tombstoned) == (1, 0, 0)
    path2, after = _only(ep_dir)
    assert path2 == path and after.frontmatter["id"] == before.frontmatter["id"]
    assert after.frontmatter["source_id"] == "folder:f1:docs/a.md"
    assert after.frontmatter["previous_source_ids"] == ["folder:f1:a.md"]
    assert after.frontmatter["relpath"] == "docs/a.md"
    assert result.renamed_sources == [("folder:f1:a.md", "folder:f1:docs/a.md")]


def test_a_rename_matches_section_by_section(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:a.md#intro", "one", sha="s1"),
              _draft("folder:f1:a.md#two", "two", sha="s1")], ep_dir)
    result = st.stage([_draft("folder:f1:b.md#intro", "one", sha="s1"),
                       _draft("folder:f1:b.md#two", "two", sha="s1")], ep_dir,
                      deleted_source_ids=["folder:f1:a.md#intro", "folder:f1:a.md#two"])
    assert result.renamed == 2 and result.created == 0 and result.tombstoned == 0
    by_sid = {markdown_parser.parse(p).frontmatter["source_id"]: markdown_parser.parse(p).body
              for p in ep_dir.glob("ep_*.md")}
    assert by_sid == {"folder:f1:b.md#intro": "one", "folder:f1:b.md#two": "two"}


def test_an_unchanged_section_of_an_edited_file_is_restamped_not_requeued(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:a.md#one", "one", sha="s1")], ep_dir)
    path, parsed = _only(ep_dir)
    markdown_parser.write(path, dict(parsed.frontmatter, processed=True, processed_by="sleep"), parsed.body)
    result = st.stage([_draft("folder:f1:a.md#one", "one", sha="s2")], ep_dir)
    assert (result.skipped, result.restamped, result.updated) == (1, 1, 0)
    fm = _only(ep_dir)[1].frontmatter
    assert fm["content_sha"] == "s2" and fm["processed"] is True and fm["processed_by"] == "sleep"


def test_a_deleted_source_is_stamped_never_removed_and_comes_back_clean(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:a.md", "text", sha="s1")], ep_dir)
    gone = st.stage([], ep_dir, deleted_source_ids=["folder:f1:a.md"])
    assert gone.tombstoned == 1 and list(gone.tombstoned_sources) == ["folder:f1:a.md"]
    _, parsed = _only(ep_dir)
    assert parsed.frontmatter["source_deleted_at"] and parsed.body == "text"
    back = st.stage([_draft("folder:f1:a.md", "text", sha="s1")], ep_dir)
    assert back.updated == 1
    assert "source_deleted_at" not in _only(ep_dir)[1].frontmatter


def test_a_draft_not_queued_is_parser_only_and_a_flip_requeues_it(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:archive/x.md", "sweep", sha="s1",
                     extra={"evidence_kind": "assistant"}, queue=False)], ep_dir)
    fm = _only(ep_dir)[1].frontmatter
    assert fm["processed"] is True and fm["processed_by"] == st.PARSED_ONLY  # R-LS10
    st.stage([_draft("folder:f1:archive/x.md", "sweep", sha="s1",
                     extra={"evidence_kind": "user"})], ep_dir)
    fm = _only(ep_dir)[1].frontmatter
    assert fm["processed"] is False and "processed_by" not in fm and fm["evidence_kind"] == "user"


def test_a_requeued_update_drops_a_stale_processed_by(tmp_path):
    ep_dir = tmp_path / "episodes"
    st.stage([_draft("folder:f1:a.md", "v1", sha="s1")], ep_dir)
    path, parsed = _only(ep_dir)
    fm = dict(parsed.frontmatter, processed=True, processed_by="sleep")
    markdown_parser.write(path, fm, parsed.body)
    st.stage([_draft("folder:f1:a.md", "v2", sha="s2")], ep_dir)
    fm = _only(ep_dir)[1].frontmatter
    assert fm["processed"] is False and "processed_by" not in fm  # G114 R6


def test_the_router_names_are_compat_wrappers_over_the_service(tmp_path):
    eps = [{"title": "T", "source": "claude", "timestamp": "2026-02-24T13:00:00Z",
            "original_date": "2026-02-24", "source_id": "u-1", "source_updated_at": "a",
            "messages": [{"role": "user", "text": "Q", "timestamp": "2026-02-24T13:00:00Z"}]}]
    assert conv._stage_episodes(eps, tmp_path / "episodes") == (1, 0, 0)
    fm = _only(tmp_path / "episodes")[1].frontmatter
    assert fm["turn_index"] == [[0, "2026-02-24T13:00:00Z", "user"]]
    assert conv._stage_episodes(eps, tmp_path / "episodes") == (0, 0, 1)
```

`api/tests/test_episode_writers_scrub.py`:

```python
"""R-LS6 — every module that mints an episode id scrubs what it writes."""
from __future__ import annotations

import asyncio
import importlib
import os
from pathlib import Path

import pytest

from api.services import calendar_registry, markdown_parser, media_ingestor, telegram_capture

REPO = Path(__file__).resolve().parents[2]
MINTERS = ("next_episode_id(", "max_suffix_by_date(")
# transcript_capture mints the id but its text is scrubbed inside the extractor
# (transcript_extract._Builder._add), so the lint reads the extractor for it.
DELEGATES = {"transcript_capture.py": "transcript_extract.py"}
SECRET = "sk-" + "Z" * 24


def _python_files():
    for root in (REPO / "api", REPO / "mcp"):
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in {".venv", "tests", "__pycache__"}]
            for name in filenames:
                if name.endswith(".py") and name != "episode_ids.py":
                    yield Path(dirpath) / name


def test_every_module_that_mints_an_episode_id_references_episode_scrub():
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if not any(m in text for m in MINTERS):
            continue
        target = DELEGATES.get(path.name)
        source = (path.parent / target).read_text(encoding="utf-8") if target else text
        if "episode_scrub" not in source:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], f"episode writers that never scrub: {offenders}"


def test_the_lint_found_the_writers_it_exists_for():
    minted = {p.name for p in _python_files() if any(m in p.read_text(encoding="utf-8") for m in MINTERS)}
    assert {"episode_staging.py", "telegram_capture.py", "media_ingestor.py", "notes_sync.py",
            "calendar_registry.py", "demo_bank.py", "server.py", "transcript_capture.py"} <= minted


def test_telegram_writer_scrubs_before_hashing(tmp_path):
    memory = tmp_path / "memory"
    telegram_capture._default_save_episode(memory, f"note {SECRET} code: 123456")
    (path,) = (memory / "episodes").glob("*.md")
    body = markdown_parser.parse(path).body
    assert SECRET not in body and "123456" not in body


def test_calendar_writer_scrubs_a_meeting_passcode(tmp_path):
    event = calendar_registry.ICSEvent(
        uid="evt-1", summary="alpha-project sync", dtstart_iso="2026-07-14T10:00:00+00:00",
        dtend_iso=None, all_day=False, location=None,
        description="Join https://example.com/j/1 Passcode: 998877", sequence=0, recurring=False)
    ep_id = calendar_registry._write_calendar_episode(tmp_path / "episodes", event, "https://example.com/c.ics")
    body = markdown_parser.parse(tmp_path / "episodes" / f"{ep_id}.md").body
    assert "998877" not in body and "Passcode: [redacted]" in body


def test_media_writer_scrubs_a_saved_reason(tmp_path):
    item = media_ingestor.RawItem(url="https://example.com/a", reason=f"it has {SECRET}")
    meta = media_ingestor.MediaMeta(title="A")
    ep_id = media_ingestor.write_media_episode(tmp_path / "episodes", item, meta, "media-a")
    assert SECRET not in markdown_parser.parse(tmp_path / "episodes" / f"{ep_id}.md").body


def test_mcp_save_episode_scrubs(tmp_path, monkeypatch):
    server = importlib.import_module("mcp.server")
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    assert "Episode saved" in server.handle_save_episode(f"deploy key {SECRET}", "T")
    (path,) = (memory / "episodes").glob("*.md")
    assert SECRET not in markdown_parser.parse(path).body
```

`api/tests/test_evidence_speakers.py`:

```python
"""R-N2 — a meeting speaker is never the owner's evidence; R-F2 — an agent-written
file is never the owner's words (R-LS7)."""
from __future__ import annotations

from api.services import evidence, markdown_parser
from api.services.claims import EVIDENCE_KINDS, Evidence

MEETING = "assistant: Summary (written by Wispr Flow)\nWe agreed.\nspeaker:bob-example: I will send the deck\nuser: Thanks"


def _bank(tmp_path, fm_extra=None, body=MEETING):
    memory = tmp_path / "memory"
    (memory / "episodes").mkdir(parents=True)
    fm = {"id": "ep_2026-09-01_001", "timestamp": "2026-09-01T10:00:00+00:00", "processed": False,
          "turn_index": [[0, None, "assistant"],
                         [MEETING.find("speaker:"), "2026-09-01T10:01:00Z", "speaker:bob-example"],
                         [MEETING.find("user:"), "2026-09-01T10:02:00Z", "user"]]}
    fm.update(fm_extra or {})
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md", fm, body)
    return memory


def test_speaker_is_a_fifth_kind():
    assert EVIDENCE_KINDS == ("user", "assistant", "page", "reasoning", "speaker")
    assert Evidence.from_dict({"episode": "ep_x", "start": 1, "end": 3, "kind": "speaker"}).kind == "speaker"


def test_a_speaker_line_is_never_user():
    assert evidence.speaker_kind(MEETING, MEETING.find("send the deck")) == "speaker"
    assert evidence.speaker_kind(MEETING, MEETING.find("We agreed")) == "assistant"
    assert evidence.speaker_kind(MEETING, MEETING.find("Thanks")) == "user"


def test_an_episode_override_beats_the_markers(tmp_path):
    memory = _bank(tmp_path, {"evidence_kind": "assistant"}, body="user: quoted in a sweep")
    assert evidence.verify(memory, "ep_2026-09-01_001", "quoted in a sweep").kind == "assistant"
    assert evidence.kind_for("ep_2026-09-01_001", "user: x", 6, "assistant") == "assistant"
    assert evidence.kind_for("ep_2026-09-01_001", "user: x", 6, "bogus") == "user"
    assert evidence.kind_for("media-a", "anything", 0, "user") == "page"


def test_stage1_passes_the_override_through():
    rel = {"evidence_quote": "quoted"}
    evidence.attach_relationship_evidence(rel, "ep_1", "user: quoted", kind_override="assistant")
    assert rel["evidence"][0]["kind"] == "assistant"


def test_turn_at_names_the_turn_a_span_starts_in():
    rows = [[0, None, "assistant"], [55, "t1", "speaker:bob-example"], [100, "t2", "user"]]
    assert evidence.turn_at(rows, 60) == {"number": 2, "of": 3, "ts": "t1", "speaker": "speaker:bob-example"}
    assert evidence.turn_at(rows, 0)["number"] == 1
    assert evidence.turn_at([], 5) is None and evidence.turn_at(None, 5) is None


def test_the_span_endpoint_reports_the_speaker_and_the_turn(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    start = MEETING.find("I will send")
    body = TestClient(main.app).get(
        "/episodes/ep_2026-09-01_001/span", params={"start": start, "end": start + 6}).json()
    config.get_settings.cache_clear()
    assert body["kind"] == "speaker"
    assert (body["turnNumber"], body["turnCount"], body["turnSpeaker"]) == (2, 3, "speaker:bob-example")
    assert body["turnTs"] == "2026-09-01T10:01:00Z"
```

The `turn_index` offsets are computed with `MEETING.find(...)` (54 and 96) rather than written as
literals, so the fixture cannot drift from the body it indexes. `PyYAML` quotes an ISO-looking
string on dump, so the `ts` column round-trips as a string, not a `datetime`.

`api/tests/test_claims_evidence.py:12-13` becomes:

```python
def test_evidence_kinds_are_the_g118_four_plus_speaker():
    # R-N2 / R-LS7: a meeting utterance by someone else is its own kind.
    assert EVIDENCE_KINDS == ("user", "assistant", "page", "reasoning", "speaker")
```

Run them: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_episode_scrub.py
api/tests/test_episode_staging.py api/tests/test_episode_writers_scrub.py
api/tests/test_evidence_speakers.py api/tests/test_claims_evidence.py -q -p no:cacheprovider` —
all fail (import errors / assertion errors).

- [ ] **Step 2: `api/services/episode_scrub.py`.**

```python
"""One scrub for every episode writer (R-N3 · R3 P3 · extends G114).

Until this module the secret scrub ran in exactly one place —
``transcript_extract._Builder._add`` (G105 R6) — so a key pasted into a chat
export, a passcode in a calendar invite, or a one-time code dictated into a
note-taker reached the bank verbatim through every OTHER writer. G114 made
"one rule for every writer" the house shape for ids and clocks; this is the
same move for the one thing that must never be stored.

Two families, applied in order:

* **Secrets** — the G105 R6 rules, moved here verbatim from
  ``transcript_extract`` (API keys, bearer tokens, vendor prefixes, JWTs, PEM
  blocks, ``key=value`` credentials, long hex/base64 runs).
  ``transcript_extract.scrub_secrets`` is now :func:`scrub`, so the Stop-hook
  path and every other writer cannot drift apart.
* **One-time codes** (R-LS5) — a 4–8 digit number joined to a code keyword by
  a short connector (``is``/``was``, ``:``, ``=``, ``#``, ``-`` or plain
  whitespace), in either order: "code: 482913", "482913 is your verification
  code". Only the digits are replaced, so the sentence still says a code was
  sent. The connector grammar replaces R3's "within ~24 characters" window on
  purpose: a raw window also ate years in ordinary prose ("wrote code in 2019").

Pure and engine-free. :func:`record` adds one ``capture`` ledger row when
something was replaced — a writer enum and a count, never what was replaced
(the transcript path records its own count in ``transcript_capture._record``).
"""

from __future__ import annotations

import re

REDACTED = "[redacted]"

#: The writer enums a ``capture`` row may carry — ids and enums only (R-LS6).
WRITERS = frozenset({
    "import", "folder", "wispr-flow", "telegram", "media", "apple-notes",
    "calendar", "mcp", "demo",
})

# Secret shapes (G105 R6), moved verbatim from transcript_extract. Ordered
# longest-context first so a PEM block is taken whole before its base64 body
# is chewed up piecemeal. The hex and base64 runs are deliberately long
# (32 / 64) so a short git SHA or an ordinary word survives; a base64
# candidate with three or more ``/`` is a path, not a token, and is kept.
_SECRET_RES: tuple[re.Pattern[str], ...] = tuple(re.compile(p, f) for p, f in (
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    (r"\bsk-[A-Za-z0-9_-]{16,}", 0),
    (r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}", 0),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", 0),
    (r"\bxox[abopr]s?-[A-Za-z0-9-]{10,}", 0),
    (r"\bAKIA[0-9A-Z]{16}\b", 0),
    (r"\bAIza[0-9A-Za-z_-]{30,}", 0),
    (r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", 0),
    (r"\bbearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    (r"\b(?:api[_-]?key|access[_-]?token|secret[_-]?key|client[_-]?secret|password|passwd|token)\b\s*[=:]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    (r"\b[0-9a-fA-F]{32,}\b", 0),
))
_BASE64_RUN_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{64,}={0,2}(?![A-Za-z0-9+/])")

_OTP_KEYWORD = (
    r"(?:one[- ]time\s+(?:pass)?code|verification\s+code|security\s+code|login\s+code"
    r"|sign[- ]in\s+code|auth(?:entication)?\s+code|confirmation\s+code"
    r"|2fa(?:\s+code)?|otp|passcode|pin|code)"
)
_OTP_FORWARD_RE = re.compile(
    rf"\b{_OTP_KEYWORD}(?:\s+(?:is|was))?\s*[:=#-]?\s*(?P<digits>\d{{4,8}})\b", re.IGNORECASE)
_OTP_REVERSE_RE = re.compile(
    rf"\b(?P<digits>\d{{4,8}})\s+is\s+(?:your|the)\s+(?:[A-Za-z]+\s+){{0,2}}{_OTP_KEYWORD}\b",
    re.IGNORECASE)


def _scrub_base64(m: re.Match[str]) -> str:
    return m.group(0) if m.group(0).count("/") >= 3 else REDACTED


def _redact_digits(m: re.Match[str]) -> str:
    start, end = m.span("digits")
    whole, base = m.group(0), m.start()
    return whole[: start - base] + REDACTED + whole[end - base:]


def scrub(text: str) -> tuple[str, int]:
    """Redact secrets, then one-time codes. Returns ``(text, replacements)`` —
    a count for the ledger, never what was replaced."""
    text = text or ""
    count = 0
    for rx in _SECRET_RES:
        text, n = rx.subn(REDACTED, text)
        count += n
    # The base64 pass keeps path-like runs (three or more ``/``), so count
    # only the matches that were actually replaced — ``subn`` would count
    # every match, kept or not.
    count += sum(1 for m in _BASE64_RUN_RE.finditer(text) if m.group(0).count("/") < 3)
    text = _BASE64_RUN_RE.sub(_scrub_base64, text)
    for rx in (_OTP_FORWARD_RE, _OTP_REVERSE_RE):
        text, n = rx.subn(_redact_digits, text)
        count += n
    return text, count


def record(writer: str, count: int, *, bank: str | None = None) -> None:
    """One ``capture`` ledger row for a write that replaced something. Never
    raises: the ledger must not fail a capture (``telemetry.record`` already
    swallows its own I/O errors; the import guard covers a stripped install)."""
    if count <= 0:
        return
    try:
        from api.services import telemetry

        telemetry.record(telemetry.UsageEvent(
            kind="capture", stage="capture", bank=bank, billing="free", invocations=0,
            refs={"writer": writer if writer in WRITERS else "other", "status": "scrubbed",
                  "scrubbed": int(count)},
        ))
    except Exception:  # noqa: BLE001
        pass


def scrub_body(text: str, *, writer: str, bank: str | None = None) -> str:
    """:func:`scrub` + :func:`record`, for a writer that holds one body."""
    cleaned, n = scrub(text)
    record(writer, n, bank=bank)
    return cleaned
```

- [ ] **Step 3: `transcript_extract.py` delegates.** Delete `:49` `REDACTED = "[redacted]"` (keep
  `CODE_OMITTED` at `:50`) and add, after `from typing import Iterable` (`:37`),
  `from api.services.episode_scrub import REDACTED, scrub as _scrub  # R-LS6: one rule set` —
  `REDACTED` stays importable from this module under the same name. Delete `:75-93` (the
  `# Secret shapes (R6)…` comment, `_SECRET_RES`, `_BASE64_RUN_RE`) and `:127-128` (`_scrub_base64`,
  plus the blank lines after it). Nothing outside the module names the three deleted symbols
  (`grep -rn "_SECRET_RES\|_BASE64_RUN_RE\|_scrub_base64" api mcp` → only this file). Replace
  `:131-145` with:

```python
def scrub_secrets(text: str) -> tuple[str, int]:
    """The extractor's name for :func:`api.services.episode_scrub.scrub` (R-LS6).

    The rules moved out so every episode writer — not only this Stop-hook path —
    scrubs with the same list (R-N3); the one-time-code family arrived with the
    move, so a code pasted into a session is now redacted here too."""
    return _scrub(text)
```

  `_Builder._add` (`:219`) is unchanged. Confirm nothing else in the module still names the deleted
  symbols: `rg -n "_SECRET_RES|_BASE64_RUN_RE|_scrub_base64" api/services/transcript_extract.py` → no output.

- [ ] **Step 4: `api/services/episode_staging.py`.**

```python
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
* ``turn_index`` — per-turn chronology as a frontmatter sidecar, rows of
  ``[offset, ts, speaker]`` into the stored body (R7 §5.1). OUTSIDE the content
  hash on purpose: timestamps in the body would change every export's hash and
  re-queue the whole corpus on the next import (💸). Not ``turns`` — that key is
  already an integer count on every hook-captured episode (R-LS1). Omitted, never
  truncated, above ``MAX_TURN_INDEX_ROWS`` (R-LS2).
* Rename by content — a tombstoned ``source_id`` and a brand-new one in the same
  batch with the same ``content_sha`` and ``#fragment`` repoint the existing
  episode instead of forking a copy (R-F1, R-LS12).
* Tombstones — ``deleted_source_ids`` stamp ``source_deleted_at`` and keep the
  file; a source that comes back clears the stamp (R-F1: the history is the history).
* Scrub — every turn and body goes through ``episode_scrub`` before it is hashed
  or written (R-N3). The hash describes the stored text; a match on the
  unscrubbed render counts as unchanged so a new scrub rule never re-queues or
  forks a legacy episode (R-LS4).
* ``queue_for_sleep=False`` — an episode a deterministic parser consolidated and
  Sleep never will (``processed_by: parser``, R-LS10).

The pre-scan reads ``bank_index``'s cached frontmatter instead of re-parsing
every episode per call (R-LS3): a watched folder stages on every save.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from api.services import bank_index, episode_ids, episode_scrub, markdown_parser

#: Column order of one ``turn_index`` row (R-LS2).
TURN_INDEX_COLUMNS = ("offset", "ts", "speaker")
#: Above this many turns the sidecar is omitted, never truncated (R-LS2).
MAX_TURN_INDEX_ROWS = 4000
#: ``processed_by`` of an episode a deterministic parser consolidated (R-LS10).
PARSED_ONLY = "parser"


@dataclass
class Turn:
    text: str
    speaker: str = "user"
    ts: str | None = None


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
    content_sha: str | None = None
    writer: str = "import"


@dataclass
class StageResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    renamed: int = 0
    tombstoned: int = 0
    #: unchanged bodies whose file hash moved (counted in ``skipped`` too).
    restamped: int = 0
    scrubbed: int = 0
    #: source_id -> episode id, for every draft with an id (skips included).
    episode_ids: dict[str, str] = field(default_factory=dict)
    #: source_id -> episode id for created, updated and renamed episodes only.
    touched: dict[str, str] = field(default_factory=dict)
    #: source_id -> episode id for episodes stamped deleted this call.
    tombstoned_sources: dict[str, str] = field(default_factory=dict)
    renamed_sources: list[tuple[str, str]] = field(default_factory=list)
    #: bank-relative paths written, for a scoped ``commit_paths``.
    paths: list[str] = field(default_factory=list)

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
    """The chat importers' dict shape as a draft (G20 callers unchanged)."""
    return EpisodeDraft(
        title=episode.get("title") or "",
        source_id=episode.get("source_id"),
        source_updated_at=episode.get("source_updated_at"),
        timestamp=episode.get("timestamp"),
        original_date=episode.get("original_date"),
        source=episode.get("source", "unknown"),
        origin=episode.get("origin"),
        turns=[Turn(text=m["text"], speaker=m["role"], ts=m.get("timestamp"))
               for m in episode.get("messages", [])],
        writer="import",
    )


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def render(draft: EpisodeDraft) -> tuple[str, list[list], int]:
    """``(body, turn_index rows, replacements)``. Each turn is scrubbed BEFORE
    its offset is taken, so every offset points into the text that is stored."""
    if draft.body is not None:
        body, n = episode_scrub.scrub(draft.body)
        return body, [], n
    lines: list[str] = []
    rows: list[list] = []
    offset = total = 0
    for turn in draft.turns:
        text, n = episode_scrub.scrub(turn.text)
        total += n
        line = f"{turn.speaker}: {text}"
        rows.append([offset, turn.ts, turn.speaker])
        lines.append(line)
        offset += len(line) + 1
    return "\n".join(lines), rows, total


def _raw_render(draft: EpisodeDraft) -> str:
    if draft.body is not None:
        return draft.body
    return "\n".join(f"{t.speaker}: {t.text}" for t in draft.turns)


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


def _apply_common(fm: dict, draft: EpisodeDraft, rows: list[list]) -> None:
    fm.update(draft.extra)
    if draft.content_sha:
        fm["content_sha"] = draft.content_sha
    if rows and len(rows) <= MAX_TURN_INDEX_ROWS:
        fm["turn_index"] = rows
    else:
        fm.pop("turn_index", None)
    if draft.queue_for_sleep:
        fm["processed"] = False
        # G114 R6: `processed_by` is written only beside `processed: true`.
        fm.pop("processed_by", None)
    else:
        fm["processed"] = True
        fm["processed_by"] = PARSED_ONLY


def write_new(draft: EpisodeDraft, episodes_dir: Path, body: str, digest: str,
              rows: list[list], date_counts: dict[str, int]) -> Path:
    """A fresh episode with a chronological id (G114 R1: ``date_counts`` holds the
    highest suffix per date, seeded from ``max_suffix_by_date``)."""
    ep_date = draft.original_date or datetime.now().strftime("%Y-%m-%d")
    date_counts[ep_date] = date_counts.get(ep_date, 0) + 1
    episode_id = f"ep_{ep_date}_{date_counts[ep_date]:03d}"
    fm = {
        "id": episode_id,
        "timestamp": normalise_timestamp(draft.timestamp) or episode_ids.utc_now_iso(),
        "source": draft.source,
        "title": draft.title or "Untitled",
        "processed": False,
        "content_hash": digest,
    }
    if draft.origin:
        fm["origin"] = draft.origin
    if draft.source_id is not None:
        fm["source_id"] = draft.source_id
        fm["source_updated_at"] = draft.source_updated_at
    _apply_common(fm, draft, rows)
    path = episodes_dir / f"{episode_id}.md"
    markdown_parser.write(path, fm, body)
    return path


def update_in_place(path: Path, draft: EpisodeDraft, body: str, digest: str, rows: list[list]) -> None:
    """Same file, same id, same original timestamp; new body, re-queued (G20)."""
    fm = dict(markdown_parser.parse(path).frontmatter)
    fm["title"] = draft.title or fm.get("title", "Untitled")
    fm["content_hash"] = digest
    fm["source_updated_at"] = draft.source_updated_at
    fm["source_id"] = draft.source_id
    if draft.origin:
        fm["origin"] = draft.origin
    fm.pop("source_deleted_at", None)
    _apply_common(fm, draft, rows)
    markdown_parser.write(path, fm, body)


def _refresh(path: Path, draft: EpisodeDraft) -> None:
    """Same body, changed metadata (an authorship flip, a returning file). A
    parser-only episode that is now owner-authored is queued; a queued one that
    is now agent-authored is parked. An episode Sleep already consolidated is
    never un-processed — its claims exist either way."""
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    was_parser_only = fm.get("processed_by") == PARSED_ONLY
    fm.pop("source_deleted_at", None)
    fm.update(draft.extra)
    if draft.content_sha:
        fm["content_sha"] = draft.content_sha
    if draft.source_updated_at:
        fm["source_updated_at"] = draft.source_updated_at
    if draft.queue_for_sleep and was_parser_only:
        fm["processed"] = False
        fm.pop("processed_by", None)
    elif not draft.queue_for_sleep and not fm.get("processed"):
        fm["processed"] = True
        fm["processed_by"] = PARSED_ONLY
    markdown_parser.write(path, fm, parsed.body)


def _restamp(path: Path, draft: EpisodeDraft) -> None:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["content_sha"] = draft.content_sha
    if draft.source_updated_at:
        fm["source_updated_at"] = draft.source_updated_at
    markdown_parser.write(path, fm, parsed.body)


def _repoint(path: Path, draft: EpisodeDraft, old_sid: str) -> None:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    previous = [s for s in (fm.get("previous_source_ids") or []) if s]
    if old_sid not in previous:
        previous.append(old_sid)
    fm["previous_source_ids"] = previous
    fm["source_id"] = draft.source_id
    fm["source_updated_at"] = draft.source_updated_at
    if draft.title:
        fm["title"] = draft.title
    fm.pop("source_deleted_at", None)
    fm.update(draft.extra)
    markdown_parser.write(path, fm, parsed.body)


def _tombstone(path: Path, at: str) -> None:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["source_deleted_at"] = at
    markdown_parser.write(path, fm, parsed.body)


def _mark(result: StageResult, verb: str, sid: str, entry: IndexEntry, episodes_dir: Path) -> None:
    setattr(result, verb, getattr(result, verb) + 1)
    result.episode_ids[sid] = entry.id
    result.touched[sid] = entry.id
    result.paths.append(_rel(entry.path, episodes_dir))


def stage(drafts: Iterable[EpisodeDraft], episodes_dir: Path, *,
          deleted_source_ids: Iterable[str] = (), bank: str | None = None) -> StageResult:
    """Create / skip / update / rename / tombstone, delta-aware by ``source_id``.

    A draft WITHOUT a ``source_id`` keeps the pre-G20 content-hash behaviour
    exactly (create or skip, never update)."""
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
    for draft in drafts:
        writer = draft.writer
        body, rows, n = render(draft)
        result.scrubbed += n
        digest = content_hash(body)
        legacy = content_hash(_raw_render(draft))
        sid = draft.source_id
        if sid:
            entry = index.get(sid)
            if entry is None and draft.content_sha:
                old = renames.pop((draft.content_sha, _fragment(sid)), None)
                if old is not None and old in index:
                    entry = index.pop(old)
                    deleted.remove(old)
                    _repoint(entry.path, draft, old)
                    entry.fm.update(source_id=sid)
                    entry.fm.pop("source_deleted_at", None)
                    index[sid] = entry
                    result.renamed_sources.append((old, sid))
                    _mark(result, "renamed", sid, entry, episodes_dir)
                    continue
            if entry is None:
                path = write_new(draft, episodes_dir, body, digest, rows, date_counts)
                known_hashes.add(digest)
                entry = IndexEntry(path=path, id=path.stem, fm={
                    "content_hash": digest, "content_sha": draft.content_sha,
                    "evidence_kind": draft.extra.get("evidence_kind")})
                index[sid] = entry
                _mark(result, "created", sid, entry, episodes_dir)
                continue
            same_body = entry.fm.get("content_hash") in (digest, legacy)
            same_meta = (entry.fm.get("evidence_kind") == draft.extra.get("evidence_kind")
                         and not entry.fm.get("source_deleted_at"))
            if same_body and same_meta:
                if draft.content_sha and entry.fm.get("content_sha") != draft.content_sha:
                    # An unchanged H2 section of an edited file: its words did not
                    # move, but the file's hash did. Restamp it (no re-queue) or a
                    # later rename could not match it by (sha, fragment) (R-LS12).
                    _restamp(entry.path, draft)
                    entry.fm["content_sha"] = draft.content_sha
                    result.restamped += 1
                    result.paths.append(_rel(entry.path, episodes_dir))
                result.skipped += 1
                result.episode_ids[sid] = entry.id
                continue
            if same_body:
                _refresh(entry.path, draft)
            else:
                update_in_place(entry.path, draft, body, digest, rows)
                known_hashes.add(digest)
                entry.fm["content_hash"] = digest
            entry.fm["evidence_kind"] = draft.extra.get("evidence_kind")
            entry.fm.pop("source_deleted_at", None)
            _mark(result, "updated", sid, entry, episodes_dir)
            continue
        if digest in known_hashes or legacy in known_hashes:
            result.skipped += 1
            continue
        path = write_new(draft, episodes_dir, body, digest, rows, date_counts)
        known_hashes.add(digest)
        result.created += 1
        result.paths.append(_rel(path, episodes_dir))

    for sid in deleted:
        entry = index.get(sid)
        if entry is None or entry.fm.get("source_deleted_at"):
            continue
        _tombstone(entry.path, now)
        entry.fm["source_deleted_at"] = now
        result.tombstoned += 1
        result.tombstoned_sources[sid] = entry.id
        result.paths.append(_rel(entry.path, episodes_dir))
    episode_scrub.record(writer, result.scrubbed, bank=bank)
    return result
```

- [ ] **Step 5: `conversations.py` keeps its names.** Delete `:743-943` (the `# --- Staging ---`
  block through `_update_episode_in_place`) and put in their place:

```python
# --- Staging (G20) — the service owns it now (R-F1 seam) ---------------------
#
# These four names stay because `api/routers/banks.py:28,232` and
# `api/tests/test_conversations.py` call them; each is a thin wrapper over
# `api.services.episode_staging`, so the chat importers stage exactly as before
# (and now scrub, and now write a `turn_index` sidecar on new/changed threads).


def _stage_episodes(episodes: list[dict], episodes_dir: Path) -> tuple[int, int, int]:
    drafts = [episode_staging.draft_from_export(e) for e in episodes]
    return episode_staging.stage(drafts, episodes_dir, bank=episodes_dir.parent.name).as_tuple()


def _normalise_import_timestamp(ts) -> str | None:
    return episode_staging.normalise_timestamp(ts)


def _write_new_episode(episode: dict, episodes_dir: Path, content_str: str, content_hash: str,
                       date_counts: dict[str, int]) -> Path:
    return episode_staging.write_new(episode_staging.draft_from_export(episode), episodes_dir,
                                     content_str, content_hash, [], date_counts)


def _update_episode_in_place(path: Path, episode: dict, content_str: str, content_hash: str) -> None:
    episode_staging.update_in_place(path, episode_staging.draft_from_export(episode),
                                    content_str, content_hash, [])
```

  Change `:13` to `from api.services import episode_ids, episode_staging, markdown_parser, session_stats, sync_service`.
  Then `rg -n "hashlib\." api/routers/conversations.py` — if nothing remains, delete `import hashlib` (`:1`).

- [ ] **Step 6: every other writer scrubs** (one line each; `bank` is the bank directory's name):
  - `api/services/telegram_capture.py` — first line of `_default_save_episode`'s body after
    `episodes_dir.mkdir(...)` (`:504`), BEFORE the hash at `:506`:
    `text = episode_scrub.scrub_body(text, writer="telegram", bank=memory_path.name)`; add
    `episode_scrub` to the module's `from api.services import …` line.
  - `api/services/media_ingestor.py:1522-1525` — wrap the `_episode_body(...)` call so it reads
    exactly:

```python
    body = episode_scrub.scrub_body(_episode_body(
        meta, item.url, saved_date, item.note, folder=item.folder, reason=item.reason,
        content_saved_at=validated_added,
    ), writer="media", bank=episodes_dir.parent.name)
```

    and add `episode_scrub` to the module's `from api.services import …` line (`:30`).
  - `api/services/notes_sync.py:234` — `body = episode_scrub.scrub_body(_episode_body(note), writer="apple-notes", bank=episodes_dir.parent.name)`.
  - `api/services/calendar_registry.py:356` — `body = episode_scrub.scrub_body(_episode_body(event, calendar_url), writer="calendar", bank=episodes_dir.parent.name)`.
  - `api/services/demo_bank.py:185` — `body = episode_scrub.scrub_body(f"user: {sentence}", writer="demo", bank=episodes_dir.parent.name)`
    (synthetic text, so a no-op — it is here because the lint defines a writer by what it does).
  - `mcp/server.py` `handle_save_episode` — before `content_hash = …` (`:2039`):
    `content = episode_scrub.scrub_body(content, writer="mcp", bank=memory_path.name)`; add
    `episode_scrub` beside the module's existing `episode_ids` import.
  Each import is `from api.services import episode_scrub` (or added to the existing grouped import).

- [ ] **Step 7: evidence learns `speaker` and the override.**
  - `api/services/claims.py:59` → `EVIDENCE_KINDS = ("user", "assistant", "page", "reasoning", "speaker")`
    with the comment `# R-N2 / R-LS7: \`speaker\` is a meeting utterance by someone other than the owner.`
  - `api/services/evidence.py`: add `"source_document", "kind_for", "turn_at", "OVERRIDE_KINDS"` to
    `__all__`; after `_ASSISTANT_ROLES` (`:65`) add:

```python
# R-N2 / R-LS7: a meeting utterance is written `speaker:<label>: text` by the
# note-taker adapters (`wispr_flow.speaker_marker`). It is someone other than
# the owner — never `user`, and not `assistant` either (a colleague is not a model).
_SPEAKER_RE = re.compile(r"^speaker:[^:\n]{1,64}:")
# R-F2 / R-LS7: an episode may declare whose words it holds (a folder file's
# authorship). Only these two values are honoured; anything else falls back to markers.
OVERRIDE_KINDS = frozenset({"user", "assistant"})
```

    Replace `source_text` (`:94-105`) with:

```python
def source_document(memory_path: Path | None, doc_id: str) -> tuple[str | None, dict]:
    """``(evidence text, frontmatter)`` of a document (R1), or ``(None, {})``. The
    frontmatter is what carries an episode's ``evidence_kind`` and ``turn_index``."""
    path = source_path(memory_path, doc_id)
    if path is None:
        return None, {}
    try:
        parsed = markdown_parser.parse(path)
    except Exception:
        return None, {}
    body = parsed.body if is_episode_id(doc_id) else strip_claims_block(parsed.body)
    return body, dict(parsed.frontmatter or {})


def source_text(memory_path: Path | None, doc_id: str) -> str | None:
    """The evidence text of a document (R1): the parsed body for an episode;
    for an entity page, the body with the claims fence stripped — so the
    claim that cites a page never stales its own span by being written."""
    return source_document(memory_path, doc_id)[0]
```

    In `speaker_kind` (`:182-185`) the loop becomes:

```python
    for line in head.splitlines():
        if _SPEAKER_RE.match(line):
            kind = "speaker"
            continue
        m = _TURN_RE.match(line)
        if m:
            kind = "assistant" if m.group(1).lower() in _ASSISTANT_ROLES else "user"
```

    Add after `speaker_kind`:

```python
def kind_for(doc_id: str, text: str, start: int, override: str | None = None) -> str:
    """The one evidence-kind decision (R-LS7): ``page`` for an entity document;
    for an episode, its declared ``evidence_kind`` when it is one of
    :data:`OVERRIDE_KINDS`, else the turn marker at ``start``."""
    if not is_episode_id(doc_id):
        return "page"
    if override in OVERRIDE_KINDS:
        return override
    return speaker_kind(text, start)


def turn_at(turn_index, start: int) -> dict | None:
    """Which turn a span starts in, from an episode's ``turn_index`` sidecar
    (``episode_staging``, R-LS2): ``{number, of, ts, speaker}`` or ``None`` when
    the episode has no index. Computed at read, never stored on a claim."""
    rows = [r for r in (turn_index or [])
            if isinstance(r, (list, tuple)) and len(r) == 3 and isinstance(r[0], int)]
    hit, number = None, 0
    for i, row in enumerate(rows):
        if row[0] > start:
            break
        hit, number = row, i + 1
    if hit is None:
        return None
    return {"number": number, "of": len(rows), "ts": hit[1], "speaker": hit[2]}
```

    `verify` gains `kind_override: str | None = None` (keyword-only, after `whole_word`); its
    `if text is None:` block becomes

```python
    if text is None:
        text, fm = source_document(memory_path, doc_id)
        if kind_override is None:
            kind_override = str(fm.get("evidence_kind") or "") or None
```

    and `kind = speaker_kind(text, start) if is_episode_id(doc_id) else "page"` becomes
    `kind = kind_for(doc_id, text, start, kind_override)`. Add one sentence to its docstring:
    "``kind_override`` (R-LS7) is the episode's ``evidence_kind`` when the caller already holds the
    text (Stage 1); without ``text`` it is read from the document's own frontmatter."
    `attach_relationship_evidence` gains `kind_override: str | None = None` and passes it to `verify`.
  - `api/services/sleep_cycle.py` `_get_unprocessed_episodes` (the dict at `:1338-1355`): add
    `"evidence_kind": str(fm.get("evidence_kind") or "") or None,` after `"source_id"`, commented
    `# R-F2 / R-LS7: whose words a folder file holds, for Stage-1 evidence.`
  - `api/services/entity_extractor.py:374` →
    `evidence.attach_relationship_evidence(rel, ep_id, content, window=spans[ci], kind_override=episode.get("evidence_kind"))`.

- [ ] **Step 8: the span endpoint.** `api/models/schemas.py` `EpisodeSpan` gains, after `kind`:

```python
    # R-LS2 — which turn the span starts in, from the episode's `turn_index`
    # sidecar; all four absent for an episode written before the sidecar existed.
    turn_number: Optional[int] = None
    turn_count: Optional[int] = None
    turn_ts: Optional[str] = None
    turn_speaker: Optional[str] = None
```

  In `api/routers/episodes.py`, everything from `text = evidence.source_text(…)` (`:43`) to the end
  of the function (`:59`) becomes:

```python
    text, fm = evidence.source_document(settings.memory_path, episode_id)
    if text is None:
        raise HTTPException(404, f"No stored document {episode_id!r}")
    if end <= start or end > len(text):
        raise HTTPException(422, f"span [{start}, {end}) is outside the document (length {len(text)})")
    current = evidence.body_hash(text)
    override = str(fm.get("evidence_kind") or "") or None
    turn = evidence.turn_at(fm.get("turn_index"), start) if evidence.is_episode_id(episode_id) else None
    return EpisodeSpan(
        episode=episode_id,
        text=text[start:end],
        before=text[max(0, start - context):start],
        after=text[end:end + context],
        start=start,
        end=end,
        length=len(text),
        stale=bool(hash) and hash != current,
        kind=evidence.kind_for(episode_id, text, start, override),
        turn_number=turn["number"] if turn else None,
        turn_count=turn["of"] if turn else None,
        turn_ts=turn["ts"] if turn else None,
        turn_speaker=turn["speaker"] if turn else None,
    )
```

- [ ] **Step 9: Verify.** The five test files above → green. Then
  `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_conversations.py api/tests/test_capture_transcript.py api/tests/test_transcript_extract.py api/tests/test_evidence.py api/tests/test_telegram_capture.py api/tests/test_calendar_registry.py api/tests/test_session_identity.py api/tests/test_banks.py -q -p no:cacheprovider`
  (the callers whose behaviour must not move), then the full `api/tests` → 0 failures.
- [ ] **Step 10: Commit** — stage the two new services, the four new test files and every modified
  file named above; message:
  `feat(G133/G134): one episode stager, one scrub on every writer, speaker-aware evidence (R-F1, R-N2, R-N3)`.

---

### Task 2: The watched folder, backend half (R-F1, R-F2)

A folder can be registered and synced by any client that posts bytes; nothing renders it yet
except the channel row and the Sources card the existing app already draws for any channel.

**Files:**
- Create: `api/services/folder_source.py`, `api/routers/local_sources.py`
- Modify: `api/main.py:13-39,175-180` (import + `include_router`)
- Modify: `api/models/schemas.py` (new models after `SourceChannelsResponse`)
- Modify: `api/services/channel_registry.py:1-30` (docstring + import), `:293` (dynamic rows)
- Modify: `api/services/source_overview.py:139-293`
- Modify: `api/services/sync_service.py:159-165`
- Test: `api/tests/test_folder_source.py` (new)

**Interfaces:**
- Produces `folder_source.FOLDERS_FILENAME`, `ORIGIN`, `CHANNEL_PREFIX`, `DEFAULT_INCLUDE`,
  `DEFAULT_EXCLUDE`, `DEFAULT_AUTHORSHIP`, `SPLIT_CHARS`, `MAX_FILE_BYTES`, `MAX_BATCH_FILES`,
  `MAX_BATCH_BYTES`, `IncomingFile`, `list_folders`, `get_folder`, `channel_id`, `register`,
  `update`, `remove`, `set_flags`, `glob_match`, `is_included`, `authorship_for`, `clean_relpath`,
  `split_sections`, `drafts_for_file`, `stage1_passes`, `live_file_count`, `sync`,
  `ensure_project`, `commit_paths_for`.
- Produces routes `GET/POST /sources/folders`, `PUT/DELETE /sources/folders/{id}`,
  `POST /sources/folders/{id}/sync?preview=`.
- Produces `channel_registry._local_channel(channel_id, label, state, noun)` (reused in Task 5).
- Consumes Task 1's `episode_staging.stage/scan/EpisodeDraft`, `local_refs.current_device_id`,
  `entity_resolver.existing_by_name/_find_direct_candidate_match`, `sync_state.record_sync/record_error`,
  `git_service.build_commit_message/commit_paths`.

- [ ] **Step 1: Failing tests** — `api/tests/test_folder_source.py`:

```python
"""G133 — a watched folder, backend half (R-F1, R-F2, R-LS8 … R-LS13, R-LS25, R-LS29)."""
from __future__ import annotations

import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_registry, entity_extractor, folder_source as fs
from api.services import markdown_parser, source_overview, sync_service

GLOB_TABLE = [
    # (pattern, relpath, matches) — Task 6's FolderGlobTests runs this SAME table.
    ("**/*.md", "README.md", True),
    ("**/*.md", "research/plan.md", True),
    ("**/*.md", "notes.txt", False),
    ("*.md", "research/plan.md", False),
    ("archive/**", "archive/2026-01/sweep.md", True),
    ("archive/**", "research/archive/x.md", False),
    ("**/.git/**", ".git/HEAD", True),
    ("**/.git/**", "sub/.git/config", True),
    ("**/node_modules/**", "web/node_modules/a/b.md", True),
    ("docs/?.md", "docs/a.md", True),
    ("docs/?.md", "docs/ab.md", False),
]


def _file(rel, text, mtime=1_756_000_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(relpath=rel, mtime=mtime, sha256=hashlib.sha256(raw).hexdigest(),
                           content_b64=base64.b64encode(raw).decode())


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    return memory


def _folder(bank):
    return fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1")


def _episodes(bank):
    bank_index.invalidate()
    return {markdown_parser.parse(p).frontmatter.get("source_id"): markdown_parser.parse(p)
            for p in (bank / "episodes").glob("ep_*.md")}


@pytest.mark.parametrize("pattern, rel, expected", GLOB_TABLE)
def test_globs(pattern, rel, expected):
    assert fs.glob_match(pattern, rel) is expected


@pytest.mark.parametrize("raw", ["/etc/passwd", "../up.md", "a/../b.md", "a//b.md", "", "a\x00b.md"])
def test_unsafe_relpaths_are_refused(raw):
    assert fs.clean_relpath(raw) is None


def test_the_split_threshold_is_four_stage1_chunks():
    assert fs.STAGE1_CHUNK == entity_extractor.CHUNK_SIZE
    assert fs.STAGE1_OVERLAP == entity_extractor.CHUNK_OVERLAP
    assert fs.SPLIT_CHARS == 4 * entity_extractor.CHUNK_SIZE


def test_register_is_an_upsert_with_a_readable_id_and_default_rules(bank):
    a = _folder(bank)
    b = fs.register(bank, label="renamed", path="/Users/example/alpha-project", device="mac-1")
    assert a["id"] == b["id"] and a["id"].startswith("alpha-project-") and b["label"] == "renamed"
    assert b["authorship"] == [{"glob": "archive/**", "authorship": "agent"}]
    assert [f["id"] for f in fs.list_folders(bank)] == [a["id"]]


def test_one_episode_per_file_with_authorship_and_mtime(bank):
    folder = _folder(bank)
    out = fs.sync(bank, folder, [_file("README.md", "# alpha-project\nOur plan."),
                                 _file("archive/2026-01/sweep.md", "An agent's sweep.")], [])
    assert (out["created"], out["files_new"], out["agent_files"]) == (2, 2, 1)
    eps = _episodes(bank)
    mine = eps[f"folder:{folder['id']}:README.md"].frontmatter
    theirs = eps[f"folder:{folder['id']}:archive/2026-01/sweep.md"].frontmatter
    assert (mine["processed"], mine["evidence_kind"], mine["authorship"]) == (False, "user", "user")
    assert (theirs["processed"], theirs["processed_by"], theirs["evidence_kind"]) == (True, "parser", "assistant")
    assert mine["timestamp"].startswith("2025-08-") and mine["origin"] == "folder"
    assert mine["relpath"] == "README.md" and mine["folder_id"] == folder["id"]


def test_resync_of_the_same_bytes_writes_nothing(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("README.md", "v1")], [])
    before = {p.name: p.stat().st_mtime_ns for p in (bank / "episodes").glob("*.md")}
    out = fs.sync(bank, folder, [_file("README.md", "v1")], [])
    assert out["files_unchanged"] == 1 and out["created"] == out["updated"] == 0
    assert {p.name: p.stat().st_mtime_ns for p in (bank / "episodes").glob("*.md")} == before


def test_an_edit_rewrites_in_place_and_requeues(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("README.md", "v1")], [])
    ep_id = _episodes(bank)[f"folder:{folder['id']}:README.md"].frontmatter["id"]
    out = fs.sync(bank, folder, [_file("README.md", "v2", mtime=1_756_100_000.0)], [])
    assert out["updated"] == 1
    fm = _episodes(bank)[f"folder:{folder['id']}:README.md"].frontmatter
    assert fm["id"] == ep_id and fm["processed"] is False


def test_a_rename_keeps_identity_and_a_delete_only_stamps(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("a.md", "same bytes"), _file("b.md", "other")], [])
    out = fs.sync(bank, folder, [_file("docs/a.md", "same bytes")], ["a.md", "b.md"])
    assert (out["renamed"], out["tombstoned"], out["created"]) == (1, 1, 0)
    eps = _episodes(bank)
    assert eps[f"folder:{folder['id']}:docs/a.md"].frontmatter["relpath"] == "docs/a.md"
    gone = eps[f"folder:{folder['id']}:b.md"]
    assert gone.frontmatter["source_deleted_at"] and gone.body == "other"
    assert fs.live_file_count(bank, folder["id"]) == 1


def test_a_long_file_splits_on_h2_and_an_edit_touches_one_section(bank):
    folder = _folder(bank)
    pad = "word " * (fs.SPLIT_CHARS // 10)
    text = f"Intro line.\n\n## Retrieval\n{pad}\n\n## Evaluation\n{pad}\n"
    fs.sync(bank, folder, [_file("REFERENCES.md", text)], [])
    base = f"folder:{folder['id']}:REFERENCES.md"
    assert set(_episodes(bank)) == {f"{base}#intro", f"{base}#retrieval", f"{base}#evaluation"}
    edited = text.replace("## Evaluation\n", "## Evaluation\nOne more line.\n")
    out = fs.sync(bank, folder, [_file("REFERENCES.md", edited, mtime=1_756_200_000.0)], [])
    assert (out["updated"], out["created"]) == (1, 0)


def test_preview_counts_and_writes_nothing(bank):
    folder = _folder(bank)
    out = fs.sync(bank, folder, [_file("README.md", "x" * 30_000), _file("archive/s.md", "y")], [],
                  preview=True)
    assert out["preview"] is True and out["files_new"] == 2 and out["agent_files"] == 1
    assert out["stage1_passes"] == 3  # ceil(30000 / 11500) for the one owner file
    assert list((bank / "episodes").glob("*.md")) == []


def test_bad_files_are_reported_not_staged(bank):
    folder = _folder(bank)
    bad_sha = fs.IncomingFile("a.md", 1.0, "0" * 64, base64.b64encode(b"x").decode())
    out = fs.sync(bank, folder, [bad_sha, _file(".git/config", "x"), _file("../up.md", "x")], [])
    assert sorted(e["reason"] for e in out["errors"]) == ["checksum mismatch", "excluded", "unsafe path"]
    assert out["created"] == 0


def test_flipping_a_glob_to_user_requeues_the_parser_only_files(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("archive/s.md", "sweep")], [])
    folder = fs.update(bank, folder["id"], authorship=[])
    out = fs.sync(bank, folder, [_file("archive/s.md", "sweep")], [])
    assert out["updated"] == 1
    fm = _episodes(bank)[f"folder:{folder['id']}:archive/s.md"].frontmatter
    assert fm["processed"] is False and fm["evidence_kind"] == "user"


def test_ensure_project_matches_by_name_or_creates_with_paths(bank):
    markdown_parser.write(bank / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project"}, "## Summary\nx")
    assert fs.ensure_project(bank, "Alpha Project", path="/p", device="mac-1") == ("alpha-project", False)
    eid, created = fs.ensure_project(bank, "beta-notes", path="/Users/example/beta", device="mac-1")
    fm = markdown_parser.parse(bank / "entities" / f"{eid}.md").frontmatter
    assert created and fm["type"] == "project"
    assert fm["paths"] == [{"path": "/Users/example/beta", "device": "mac-1"}]


def test_the_channel_row_and_the_sources_card(bank):
    folder = _folder(bank)
    fs.sync(bank, folder, [_file("README.md", "hello")], [])
    from api.services import sync_state
    sync_state.record_sync(bank, fs.channel_id(folder["id"]), count=fs.live_file_count(bank, folder["id"]))
    rows = channel_registry.build_channels(bank, telegram_enabled=False)
    fixed = [r["id"] for r in rows][: len(channel_registry.CHANNEL_IDS)]
    assert fixed == list(channel_registry.CHANNEL_IDS)  # R-LS25: the fixed list never moves
    row = rows[-1]
    assert row["id"] == f"folder:{folder['id']}" and row["label"] == "alpha-project"
    assert row["actions"] == ["sync", "manage"] and row["count"] == 1 and row["count_noun"] == "note"
    bank_index.invalidate()
    card = next(r for r in source_overview.build_overview(bank, channels=rows)
                if r["id"] == f"folder:{folder['id']}")
    assert (card["label"], card["kind"], card["mark"], card["episodes"]) == ("alpha-project", "import", "folder", 1)


def test_registering_moves_the_sources_component(bank):
    before = sync_service.components(bank)["sources"]
    _folder(bank)
    assert sync_service.components(bank)["sources"] != before  # R-LS29


@pytest.fixture
def client(bank, monkeypatch, tmp_path):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), bank
    config.get_settings.cache_clear()


def test_the_routes(client):
    c, bank = client
    r = c.post("/sources/folders", json={"label": "alpha-project", "path": "/Users/example/alpha-project",
                                         "projectName": ""})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    assert r.json()["device"] and r.json()["channelId"] == f"folder:{fid}"
    body = {"files": [{"relpath": f.relpath, "mtime": f.mtime, "sha256": f.sha256, "contentB64": f.content_b64}
                      for f in [_file("README.md", "hello")]], "deleted": []}
    pre = c.post(f"/sources/folders/{fid}/sync", params={"preview": "true"}, json=body).json()
    assert pre["preview"] is True and pre["filesNew"] == 1
    done = c.post(f"/sources/folders/{fid}/sync", json=body).json()
    assert done["created"] == 1
    assert any(ch["id"] == f"folder:{fid}" for ch in c.get("/sources/channels").json()["channels"])
    assert c.get("/sources/folders").json()["folders"][0]["lastSync"]
    assert c.post("/sources/folders/nope/sync", json=body).status_code == 404
    too_many = {"files": body["files"] * (fs.MAX_BATCH_FILES + 1), "deleted": []}
    assert c.post(f"/sources/folders/{fid}/sync", json=too_many).status_code == 413
    assert c.delete(f"/sources/folders/{fid}").json() == {"removed": True}
    assert list((bank / "episodes").glob("*.md")), "removing a folder never deletes its episodes"
```

Run: `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_folder_source.py -q -p no:cacheprovider` → fails (no module).

- [ ] **Step 2: `api/services/folder_source.py`.**

```python
"""A watched folder of notes as a memory source (G133 · R-F1 · R-F2).

The APP owns the folder: it holds a bookmark to it, runs a recursive FSEvents
watch, and posts the bytes of changed files with their relative paths. The
backend never opens the folder path — the rail CLAUDE.md states for
``~/Library`` applies to ``~/Documents``, ``~/Desktop`` and ``~/Downloads`` too
(TCC-gated; the launchd backend has no grant). The absolute path is stored per
device only to display it and to relink a moved folder (the G27 shape).

One episode per file through the G20 stager (``episode_staging``): the same
bytes skip, an edit rewrites the file's episode in place and re-queues it, a
rename keeps identity by content hash, a deletion stamps ``source_deleted_at``
and keeps the episode. A file past ``SPLIT_CHARS`` (4 × Stage 1's chunk) is one
episode per H2 section, so an edit re-reads one section (R-LS12).

Authorship (R-F2): a per-folder glob list decides whose words a file holds.
``archive/**`` defaults to ``agent`` — dated research sweeps an agent wrote. An
agent-written file is stored and searchable but never credited to the person
(``evidence_kind: assistant``) and never queued for Sleep (R-LS10).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from loguru import logger

from api.services import bank_index, decay_policy, episode_ids, episode_staging, markdown_parser
from api.services.id_utils import sanitize_id

FOLDERS_FILENAME = "folders.json"
ORIGIN = "folder"
CHANNEL_PREFIX = "folder:"
DEFAULT_INCLUDE = ("**/*.md", "**/*.markdown", "**/*.txt")
DEFAULT_EXCLUDE = ("**/.git/**", "**/node_modules/**", "**/.obsidian/**", "**/.trash/**")
DEFAULT_AUTHORSHIP = ({"glob": "archive/**", "authorship": "agent"},)
AUTHORSHIPS = ("user", "agent")
# Stage 1's chunking, mirrored rather than imported: `entity_extractor` pulls the
# LLM stack, and this module is a capture path (no LLM at capture time). The
# test suite pins both numbers to `entity_extractor.CHUNK_SIZE`/`CHUNK_OVERLAP`.
STAGE1_CHUNK = 12_000
STAGE1_OVERLAP = 500
SPLIT_CHARS = STAGE1_CHUNK * 4
MAX_FILE_BYTES = 2_000_000
MAX_BATCH_FILES = 200
MAX_BATCH_BYTES = 8_000_000
_MAX_RELPATH = 512
_H2 = re.compile(r"^##[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^[ \t]*(`{3}|~{3})")


@dataclass
class IncomingFile:
    relpath: str
    mtime: float
    sha256: str
    content_b64: str


# --- Registry ---------------------------------------------------------------


def registry_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / FOLDERS_FILENAME


def list_folders(memory_path: Path) -> list[dict]:
    """Every registered folder; a missing or corrupt registry is an empty list,
    never an error (the `feed_registry` convention)."""
    try:
        data = json.loads(registry_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    folders = data.get("folders") if isinstance(data, dict) else None
    return [f for f in (folders or []) if isinstance(f, dict) and f.get("id")]


def _save(memory_path: Path, folders: list[dict]) -> None:
    path = registry_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"folders": folders}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def get_folder(memory_path: Path, folder_id: str) -> dict | None:
    return next((f for f in list_folders(memory_path) if f.get("id") == folder_id), None)


def channel_id(folder_id: str) -> str:
    return f"{CHANNEL_PREFIX}{folder_id}"


def _clean_rules(rules) -> list[dict]:
    out: list[dict] = []
    for rule in rules or []:
        rule = rule if isinstance(rule, dict) else {}
        glob = str(rule.get("glob") or "").strip()
        who = str(rule.get("authorship") or "").strip()
        if glob and who in AUTHORSHIPS and len(glob) <= 200:
            out.append({"glob": glob, "authorship": who})
    return out


def register(memory_path: Path, *, label: str, path: str, include=None, exclude=None,
             authorship=None, project_id: str | None = None, device: str | None = None) -> dict:
    """Create or update the folder at ``(device, path)`` (R-LS9: an upsert, so a
    re-pick of the same folder keeps its id, its episodes and its history)."""
    from api.services import local_refs

    device = device or local_refs.current_device_id()
    folders = list_folders(memory_path)
    existing = next((f for f in folders if f.get("device") == device and f.get("path") == path), None)
    key = hashlib.sha1(f"{device}\x00{path}".encode()).hexdigest()[:6]
    slug = (sanitize_id(label) or "folder")[:40].strip("-") or "folder"
    record = existing if existing is not None else {"id": f"{slug}-{key}", "created_at": episode_ids.utc_now_iso()}
    record.update({
        "label": (label or "").strip() or Path(path).name or "Folder",
        "path": path,
        "device": device,
        "include": list(include) if include else list(DEFAULT_INCLUDE),
        "exclude": list(exclude) if exclude else list(DEFAULT_EXCLUDE),
        "authorship": _clean_rules(authorship) if authorship is not None
        else [dict(r) for r in DEFAULT_AUTHORSHIP],
        "project_id": project_id or record.get("project_id"),
    })
    if existing is None:
        folders.append(record)
    _save(memory_path, folders)
    return record


def update(memory_path: Path, folder_id: str, *, label: str | None = None, authorship=None) -> dict | None:
    folders = list_folders(memory_path)
    record = next((f for f in folders if f.get("id") == folder_id), None)
    if record is None:
        return None
    if label is not None and label.strip():
        record["label"] = label.strip()
    if authorship is not None:
        record["authorship"] = _clean_rules(authorship)
    _save(memory_path, folders)
    return record


def remove(memory_path: Path, folder_id: str) -> bool:
    """Forget the registration. Episodes stay — the history is the history (R-F1)."""
    folders = list_folders(memory_path)
    kept = [f for f in folders if f.get("id") != folder_id]
    if len(kept) == len(folders):
        return False
    _save(memory_path, kept)
    return True


def set_flags(memory_path: Path, folder_id: str, **fields) -> None:
    folders = list_folders(memory_path)
    for f in folders:
        if f.get("id") == folder_id:
            f.update(fields)
            _save(memory_path, folders)
            return


# --- Paths and globs --------------------------------------------------------


@lru_cache(maxsize=512)
def _glob_re(pattern: str) -> re.Pattern[str]:
    """``**/`` = any number of directories (zero included), ``**`` = anything,
    ``*`` = anything but ``/``, ``?`` = one character but ``/``. Python's
    ``fnmatch`` lets ``*`` cross ``/`` and gives ``**`` no meaning, which would
    make ``*.md`` match a nested file and ``**/*.md`` miss a root one."""
    i, out = 0, []
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def glob_match(pattern: str, relpath: str) -> bool:
    return _glob_re(pattern).fullmatch(relpath) is not None


def is_included(relpath: str, include, exclude) -> bool:
    return (any(glob_match(p, relpath) for p in include)
            and not any(glob_match(p, relpath) for p in exclude))


def authorship_for(relpath: str, rules) -> str:
    """First matching rule wins; no match is the person's own words."""
    for rule in rules or []:
        if glob_match(str(rule.get("glob") or ""), relpath):
            return str(rule.get("authorship") or "user")
    return "user"


def clean_relpath(raw) -> str | None:
    """A relative path inside the folder, or ``None``: no absolute paths, no
    ``..``, no empty segments, no NUL — the app sends paths it computed, but the
    backend never trusts a path it is about to key an episode on."""
    rel = str(raw or "").replace("\\", "/").strip()
    if not rel or rel.startswith("/") or "\x00" in rel or len(rel) > _MAX_RELPATH:
        return None
    if any(part in ("", ".", "..") for part in rel.split("/")):
        return None
    return rel


# --- Drafts -----------------------------------------------------------------


def split_sections(text: str) -> list[tuple[str, str, str]]:
    """``[(slug, heading, section_text)]`` split on H2 lines outside code fences
    (R-LS12). Text before the first H2 is the ``intro`` section when not blank;
    repeated headings get ``-2``, ``-3``."""
    sections: list[tuple[str | None, str]] = []
    heading: str | None = None
    buf: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _H2.match(line.rstrip("\r\n"))
        if m:
            sections.append((heading, "".join(buf)))
            heading, buf = m.group(1).strip(), [line]
        else:
            buf.append(line)
    sections.append((heading, "".join(buf)))
    out: list[tuple[str, str, str]] = []
    seen: dict[str, int] = {}
    for head, body in sections:
        if head is None:
            if not body.strip():
                continue
            slug, title = "intro", ""
        else:
            slug = (sanitize_id(head) or "section")[:60].strip("-") or "section"
            title = head
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug = f"{slug}-{seen[slug]}"
        out.append((slug, title, body))
    return out


def drafts_for_file(folder: dict, relpath: str, text: str, *, mtime_iso: str, sha: str) -> list[episode_staging.EpisodeDraft]:
    authorship = authorship_for(relpath, folder.get("authorship") or [])
    base = f"{channel_id(folder['id'])}:{relpath}"
    extra = {"folder_id": folder["id"], "relpath": relpath, "authorship": authorship,
             "evidence_kind": "user" if authorship == "user" else "assistant"}
    label = folder.get("label") or "Folder"
    parts = split_sections(text) if len(text) > SPLIT_CHARS else [("", "", text)]
    return [
        episode_staging.EpisodeDraft(
            title=f"{label} › {relpath}" + (f" › {heading}" if heading else ""),
            source_id=base if not slug else f"{base}#{slug}",
            source_updated_at=mtime_iso, timestamp=mtime_iso, original_date=mtime_iso[:10],
            source=ORIGIN, origin=ORIGIN, body=section, extra=dict(extra),
            queue_for_sleep=authorship == "user", content_sha=sha, writer="folder",
        )
        for slug, heading, section in parts
    ]


def stage1_passes(text: str) -> int:
    """How many Stage-1 calls Sleep will spend on ``text`` — shown as a count,
    never a price (the 2026-09-03 ruling)."""
    return math.ceil(len(text) / (STAGE1_CHUNK - STAGE1_OVERLAP)) if text.strip() else 0


def _by_relpath(index: dict, folder_id: str) -> dict[str, list[tuple[str, episode_staging.IndexEntry]]]:
    out: dict[str, list[tuple[str, episode_staging.IndexEntry]]] = {}
    for sid, entry in index.items():
        if entry.fm.get("folder_id") == folder_id and entry.fm.get("relpath"):
            out.setdefault(str(entry.fm["relpath"]), []).append((sid, entry))
    return out


def live_file_count(memory_path: Path, folder_id: str) -> int:
    index, _ = episode_staging.scan(Path(memory_path) / "episodes")
    return sum(1 for entries in _by_relpath(index, folder_id).values()
               if any(not e.fm.get("source_deleted_at") for _, e in entries))


# --- Sync -------------------------------------------------------------------


def sync(memory_path: Path, folder: dict, files: list[IncomingFile], deleted: list[str], *,
         preview: bool = False) -> dict:
    """Stage (or, with ``preview``, only count) one posted batch. Never opens
    the folder; decodes and re-hashes what the app sent. Returns the counts the
    route serialises, plus ``_staged`` (the ``StageResult``) and ``_texts``
    (relpath -> decoded text) for the paper step (Task 3)."""
    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    index, _ = episode_staging.scan(episodes_dir)
    mine = _by_relpath(index, folder["id"])
    include = folder.get("include") or DEFAULT_INCLUDE
    exclude = folder.get("exclude") or DEFAULT_EXCLUDE
    rules = folder.get("authorship") or []
    out = {"preview": preview, "files_new": 0, "files_changed": 0, "files_unchanged": 0,
           "files_deleted": 0, "agent_files": 0, "stage1_passes": 0, "errors": [],
           "created": 0, "updated": 0, "renamed": 0, "tombstoned": 0}
    drafts: list[episode_staging.EpisodeDraft] = []
    deleted_sids: list[str] = []
    texts: dict[str, str] = {}
    for f in files:
        rel = clean_relpath(f.relpath)
        if rel is None:
            out["errors"].append({"relpath": str(f.relpath)[:200], "reason": "unsafe path"})
            continue
        if not is_included(rel, include, exclude):
            out["errors"].append({"relpath": rel, "reason": "excluded"})
            continue
        try:
            raw = base64.b64decode(f.content_b64, validate=True)
        except (binascii.Error, ValueError):
            out["errors"].append({"relpath": rel, "reason": "bad encoding"})
            continue
        if len(raw) > MAX_FILE_BYTES:
            out["errors"].append({"relpath": rel, "reason": "too large"})
            continue
        sha = hashlib.sha256(raw).hexdigest()
        if sha != (f.sha256 or "").strip().lower():
            out["errors"].append({"relpath": rel, "reason": "checksum mismatch"})
            continue
        who = authorship_for(rel, rules)
        kind = "user" if who == "user" else "assistant"
        existing = mine.get(rel, [])
        live = [e for _, e in existing if not e.fm.get("source_deleted_at")]
        # Idempotent on (relpath, sha256) AND the authorship the rules give it now
        # — a glob flip must re-stage the same bytes (R-LS10).
        if live and all(e.fm.get("content_sha") == sha and e.fm.get("evidence_kind") == kind for e in live):
            out["files_unchanged"] += 1
            continue
        text = raw.decode("utf-8", errors="replace").lstrip("﻿")
        texts[rel] = text
        out["files_changed" if existing else "files_new"] += 1
        if who == "agent":
            out["agent_files"] += 1
        else:
            out["stage1_passes"] += stage1_passes(text)
        new = drafts_for_file(folder, rel, text, mtime_iso=episode_ids.to_utc_iso(float(f.mtime)), sha=sha)
        drafts.extend(new)
        new_sids = {d.source_id for d in new}
        deleted_sids += [sid for sid, e in existing if sid not in new_sids and not e.fm.get("source_deleted_at")]
    for raw_rel in deleted:
        rel = clean_relpath(raw_rel)
        if rel is None:
            continue
        gone = [sid for sid, e in mine.get(rel, []) if not e.fm.get("source_deleted_at")]
        if gone:
            out["files_deleted"] += 1
            deleted_sids += gone
    out["_texts"] = texts
    if preview:
        out["_staged"] = None
        return out
    staged = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=deleted_sids, bank=memory_path.name)
    out.update(created=staged.created, updated=staged.updated, renamed=staged.renamed,
               tombstoned=staged.tombstoned)
    out["_staged"] = staged
    set_flags(memory_path, folder["id"], last_sync=episode_ids.utc_now_iso())
    return out


# --- The project anchor (R-LS13) --------------------------------------------


def ensure_project(memory_path: Path, name: str, *, path: str, device: str) -> tuple[str, bool]:
    """``(project entity id, created)`` for the name the person gave the folder.
    Zero-LLM match against ``project`` pages (Stage 2's direct matcher only);
    otherwise a new ``project`` page, because the person typed the name. Either
    way the page learns ``paths: [{path, device}]``."""
    from api.services import entity_resolver

    memory_path = Path(memory_path)
    name = " ".join((name or "").split())
    if not name:
        return "", False
    projects = [{"id": f.stem, "frontmatter": f.frontmatter} for f in bank_index.files(memory_path, "entities")
                if (f.frontmatter or {}).get("type") == "project"]
    match = entity_resolver._find_direct_candidate_match(
        {"name": name}, entity_resolver.existing_by_name(projects), {})
    entry = {"path": path, "device": device}
    if match is not None:
        eid = match["candidate"]["id"]
        page = memory_path / "entities" / f"{eid}.md"
        parsed = markdown_parser.parse(page)
        fm = dict(parsed.frontmatter)
        paths = [p for p in (fm.get("paths") or []) if isinstance(p, dict)]
        if entry not in paths:
            fm["paths"] = paths + [entry]
            markdown_parser.write(page, fm, parsed.body)
        return eid, False
    eid = sanitize_id(name)
    page = memory_path / "entities" / f"{eid}.md"
    if page.exists():
        eid = f"{eid}-{hashlib.sha1(name.encode()).hexdigest()[:4]}"
        page = memory_path / "entities" / f"{eid}.md"
    today = date.today().isoformat()
    fm = {
        "name": name, "type": "project", "status": "active", "confidence": 0.8,
        "created": today, "last_referenced": today,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for("project")),
        "source_episodes": [], "tags": ["folder"], "related": [], "version": 1,
        "paths": [entry],
    }
    page.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(page, fm, f"## Summary\n{name} — a folder of notes Cicada keeps in memory.")
    return eid, True


# --- Commits (R-LS30) -------------------------------------------------------


async def commit_paths_for(memory_path: Path, paths: list[str], *, subject: str, trigger: str,
                           author: str = "user") -> None:
    """A commit scoped to exactly ``paths`` — never ``git add -A``. Best effort:
    a bank that is not a git repo (most unit tests) must not fail a sync."""
    from api.services import git_service

    rels = sorted({p for p in paths if p})
    if not rels:
        return
    lines = [f"{p}: updated (trigger: {trigger})" for p in rels[:200]]
    if len(rels) > 200:
        lines.append(f"… and {len(rels) - 200} more (trigger: {trigger})")
    message = git_service.build_commit_message(subject, lines, authors=[author])
    try:
        await git_service.commit_paths(Path(memory_path), message, rels)
    except Exception as e:  # pragma: no cover - non-git workspace
        logger.warning(f"folder commit failed: {type(e).__name__}: {e}")
```

- [ ] **Step 3: schemas** — in `api/models/schemas.py`, after `SourceChannelsResponse`:

```python
class FolderAuthorshipRule(CamelModel):
    """G133 / R-F2 — whose words the files under ``glob`` are: ``user`` or ``agent``."""

    glob: str
    authorship: str


class FolderRecord(CamelModel):
    """One watched folder (``<bank>/sources/folders.json``). ``path`` is display
    and relink only — the backend never opens it (R-F1)."""

    id: str
    label: str
    path: str
    device: str
    include: list[str] = []
    exclude: list[str] = []
    authorship: list[FolderAuthorshipRule] = []
    project_id: Optional[str] = None
    created_at: Optional[str] = None
    last_sync: Optional[str] = None
    papers_pending: bool = False
    channel_id: str = ""


class FolderListResponse(CamelModel):
    folders: list[FolderRecord] = []


class FolderRegisterRequest(CamelModel):
    label: str
    path: str
    include: Optional[list[str]] = None
    exclude: Optional[list[str]] = None
    authorship: Optional[list[FolderAuthorshipRule]] = None
    # R-LS13 — the app pre-fills the folder's name; "" means "no project".
    project_name: Optional[str] = None


class FolderUpdateRequest(CamelModel):
    label: Optional[str] = None
    authorship: Optional[list[FolderAuthorshipRule]] = None


class FolderFileIn(CamelModel):
    """R-LS8 — one file the app read: bytes as base64, re-hashed server-side."""

    relpath: str
    mtime: float
    sha256: str
    content_b64: str


class FolderSyncRequest(CamelModel):
    files: list[FolderFileIn] = []
    deleted: list[str] = []


class FolderSyncError(CamelModel):
    relpath: str
    reason: str


class FolderSyncResponse(CamelModel):
    preview: bool = False
    files_new: int = 0
    files_changed: int = 0
    files_unchanged: int = 0
    files_deleted: int = 0
    agent_files: int = 0
    stage1_passes: int = 0
    papers_found: int = 0
    created: int = 0
    updated: int = 0
    renamed: int = 0
    tombstoned: int = 0
    papers_created: int = 0
    removals_proposed: int = 0
    papers_pending: bool = False
    errors: list[FolderSyncError] = []


class FolderRemoveResponse(CamelModel):
    removed: bool
```

- [ ] **Step 4: `api/routers/local_sources.py`.**

```python
"""Local sources the APP reads and the backend parses (G133 folders, G134 note-takers).

The app owns the disk — a folder bookmark, another app's SQLite under
``~/Library`` — and posts bytes or a whitelisted projection here; the backend
never opens either (R-F1, R-N1). Every route is bearer-gated like the rest of
the API; none is on the Telegram / OAuth-callback exemption list.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from api.config import Settings, get_settings
from api.models.schemas import (
    FolderListResponse,
    FolderRecord,
    FolderRegisterRequest,
    FolderRemoveResponse,
    FolderSyncRequest,
    FolderSyncResponse,
    FolderUpdateRequest,
)
from api.services import folder_source, local_refs, sync_state

router = APIRouter()


def _record(folder: dict) -> FolderRecord:
    return FolderRecord(**folder, channel_id=folder_source.channel_id(folder["id"]))


@router.get("/sources/folders", response_model=FolderListResponse)
async def list_folders(settings: Settings = Depends(get_settings)):
    return FolderListResponse(folders=[_record(f) for f in folder_source.list_folders(settings.memory_path)])


@router.post("/sources/folders", response_model=FolderRecord)
async def register_folder(req: FolderRegisterRequest, settings: Settings = Depends(get_settings)):
    memory_path = settings.memory_path
    device = local_refs.current_device_id()
    name = req.label if req.project_name is None else req.project_name
    project_id, created = await run_in_threadpool(
        folder_source.ensure_project, memory_path, name, path=req.path, device=device)
    folder = folder_source.register(
        memory_path, label=req.label, path=req.path, include=req.include, exclude=req.exclude,
        authorship=[r.model_dump() for r in req.authorship] if req.authorship is not None else None,
        project_id=project_id or None, device=device)
    paths = [f"sources/{folder_source.FOLDERS_FILENAME}"]
    if project_id:
        paths.append(f"entities/{project_id}.md")
    await folder_source.commit_paths_for(
        memory_path, paths, subject=f"Folder added ({folder['label']})", trigger="user/companion_app")
    return _record(folder)


@router.put("/sources/folders/{folder_id}", response_model=FolderRecord)
async def update_folder(folder_id: str, req: FolderUpdateRequest, settings: Settings = Depends(get_settings)):
    folder = folder_source.update(
        settings.memory_path, folder_id, label=req.label,
        authorship=[r.model_dump() for r in req.authorship] if req.authorship is not None else None)
    if folder is None:
        raise HTTPException(404, f"No folder {folder_id!r}")
    await folder_source.commit_paths_for(
        settings.memory_path, [f"sources/{folder_source.FOLDERS_FILENAME}"],
        subject=f"Folder settings ({folder['label']})", trigger="user/companion_app")
    return _record(folder)


@router.delete("/sources/folders/{folder_id}", response_model=FolderRemoveResponse)
async def remove_folder(folder_id: str, settings: Settings = Depends(get_settings)):
    if not folder_source.remove(settings.memory_path, folder_id):
        raise HTTPException(404, f"No folder {folder_id!r}")
    await folder_source.commit_paths_for(
        settings.memory_path, [f"sources/{folder_source.FOLDERS_FILENAME}"],
        subject="Folder removed", trigger="user/companion_app")
    return FolderRemoveResponse(removed=True)


@router.post("/sources/folders/{folder_id}/sync", response_model=FolderSyncResponse)
async def sync_folder(
    folder_id: str,
    req: FolderSyncRequest,
    preview: bool = Query(False),
    settings: Settings = Depends(get_settings),
):
    """Stage one batch of files the app read (R-F1). ``?preview=true`` counts
    and writes nothing — the add-folder sheet shows it before anything lands."""
    memory_path = settings.memory_path
    folder = folder_source.get_folder(memory_path, folder_id)
    if folder is None:
        raise HTTPException(404, f"No folder {folder_id!r}")
    if len(req.files) > folder_source.MAX_BATCH_FILES:
        raise HTTPException(413, f"at most {folder_source.MAX_BATCH_FILES} files per request")
    if sum(len(f.content_b64) for f in req.files) * 3 // 4 > folder_source.MAX_BATCH_BYTES:
        raise HTTPException(413, "batch too large — send fewer files per request")
    files = [folder_source.IncomingFile(f.relpath, f.mtime, f.sha256, f.content_b64) for f in req.files]
    out = await run_in_threadpool(folder_source.sync, memory_path, folder, files, req.deleted, preview=preview)
    staged = out.pop("_staged")
    out.pop("_texts")
    if not preview:
        attempted = len(files)
        if attempted and len(out["errors"]) == attempted:
            sync_state.record_error(memory_path, folder_source.channel_id(folder_id),
                                    f"{attempted} file(s) could not be read")
        else:
            sync_state.record_sync(memory_path, folder_source.channel_id(folder_id),
                                   count=folder_source.live_file_count(memory_path, folder_id))
        await folder_source.commit_paths_for(
            memory_path, (staged.paths if staged else []) + [f"sources/{folder_source.FOLDERS_FILENAME}"],
            subject=f"Folder sync ({folder['label']})", trigger="folder/sync")
    return FolderSyncResponse(**out)
```

  `api/main.py`: add `local_sources,` to the router import list (alphabetical, after `local_refs`)
  and `app.include_router(local_sources.router, tags=["local-sources"])` after the `local_refs` line
  (`:174`).

- [ ] **Step 5: the channel row.** In `api/services/channel_registry.py`: add
  `folder_source` to the `from api.services import (...)` block; extend the module docstring's
  bullet list with ``* ``folder:<id>`` -> one row per registered folder (G133), appended after the
  fixed ids (R-LS25)``; add before `build_channels`:

```python
def _local_channel(channel_id: str, label: str, state: dict, noun: str) -> dict:
    """A source the APP reads and posts (G133 folders, G134 note-takers).

    `_sync_channel`'s shape with two differences: the row can be managed
    (`manage` opens its settings in Settings → Integrations), and a recorded
    failure wins the detail line (`_connector_channel`'s rule —
    `record_sync` replaces the entry, so an error present is newer than the
    last success). Appended after `CHANNEL_IDS` rather than listed in it
    (R-LS25): the fixed list and its four mirrors stay what they are.
    """
    entry = state.get(channel_id) or {}
    last = entry.get("last_sync") or None
    error = entry.get("last_error") or None
    connected = bool(last)
    if error:
        detail = f"Last sync failed · {error}"
    elif connected:
        detail = f"synced {_short_date(last)}"
    else:
        detail = "Not synced yet"
    return {
        "id": channel_id,
        "label": label,
        "connected": connected,
        "count": int(entry.get("count") or 0),
        "last_sync": last,
        "last_error": error,
        "detail": detail,
        "count_noun": noun if connected and not error else None,
        "count_is_delta": False,
        "actions": ["sync", "manage"],
    }
```

  and replace the last line of `build_channels` (`:293`) with:

```python
    rows = [channels[cid] for cid in CHANNEL_IDS]
    for folder in folder_source.list_folders(memory_path):
        rows.append(_local_channel(folder_source.channel_id(folder["id"]),
                                   str(folder.get("label") or "Folder"), state, "note"))
    return rows
```

- [ ] **Step 6: the Sources card.** In `api/services/source_overview.py`: import `folder_source`
  (`from api.services import bank_index, folder_source`). In `source_key` (`:139-155`), before the
  `if not origin:` line:

```python
    # G133: one card per watched folder, not one "folder" card for all of them.
    if origin == folder_source.ORIGIN and fm.get("folder_id"):
        return folder_source.channel_id(str(fm["folder_id"]))
```

  `_new_state(key)` becomes `_new_state(key, labels=None)` and gains, before the final `else:`:

```python
    elif key.startswith(folder_source.CHANNEL_PREFIX):
        known = (labels or {})
        label, kind, mark, origins, channel = (
            known.get(key, "Folder (removed)"), "import", "folder", [folder_source.ORIGIN],
            key if key in known else None)
        harness = None
```

  In `build_overview`, compute once at the top
  `labels = {folder_source.channel_id(f["id"]): str(f.get("label") or "Folder") for f in folder_source.list_folders(memory_path)}`,
  pass `labels` to every `_new_state(...)` call, and change the channel loop's head to:

```python
    for channel in channels:
        cid = channel["id"]
        spec = _BY_ID.get(cid)
        if spec is None and cid not in labels:
            continue
        state = states.setdefault(cid, _new_state(cid, labels))
        if spec is not None and spec.id == "files":
```

  (the body below it is unchanged; its `else:` branch now also serves folder rows).

- [ ] **Step 7: the ETag input (R-LS29).** `api/services/sync_service.py` — import
  `from api.services.folder_source import FOLDERS_FILENAME` and add one line to the `sources`
  component after the `url_index.json` term (`:161`):
  `f":{file_mtime(mp / 'sources' / FOLDERS_FILENAME):.6f}"`, and one sentence to the comment above
  it: "`sources/folders.json` (G133) rides it too: registering or renaming a folder adds or relabels
  a channel row without touching any other component."

- [ ] **Step 8: Verify** — `test_folder_source.py` green; then
  `api/.venv/bin/python -m pytest api/tests/test_source_channels.py api/tests/test_source_overview.py api/tests/test_sync.py -q -p no:cacheprovider`
  (the pinned channel list and both ETag recipes must be untouched), then the full suite.
- [ ] **Step 9: Commit** — `feat(G133): a watched folder is a source — one episode per file, renames keep identity, deletions only stamp (R-F1, R-F2)`.

---

### Task 3: Papers from the folder — pages, "why it matters", removals (R-F3, no network)

Everything here is deterministic and offline. After this task a synced folder produces paper
pages with personal-tier claims; the abstracts arrive in Task 4.

**Files:**
- Create: `api/services/papers.py`
- Modify: `api/routers/local_sources.py` (`sync_folder`: preview count + the paper step)
- Test: `api/tests/test_papers.py` (new)

**Interfaces:**
- Produces `papers.KIND`, `ORIGIN`, `CITATIONS_FILENAME`, `WHY_PREDICATES`, `ARXIV_URL_RE`,
  `DOI_URL_RE`, `PaperKey`, `Citation`, `normalise_arxiv`, `normalise_doi`, `key_for_doi`,
  `key_from_url`, `parse`, `count_papers`, `is_paper`, `page_path`, `index_aliases`, `ensure_page`,
  `claim_id`, `desired_claims`, `apply_claims`, `propose_removals`, `reconcile`, `reparse_folder`,
  `reconcile_pending`.
- Consumes `episode_staging.scan` + `StageResult.touched/tombstoned_sources/renamed_sources`,
  `evidence.source_document/verify`, `media_ingestor.load_url_index/save_url_index/url_hash`,
  `entity_resolver.existing_by_name/_find_direct_candidate_match`, `owner_identity.resolve_observer`,
  `inbox_generator.find_open`, `inbox_service.next_inbox_num`, `folder_source.list_folders/set_flags`.

- [ ] **Step 1: Failing tests** — `api/tests/test_papers.py`:

```python
"""G133 / R-F3 — papers parsed with no LLM; why they matter, as spans (R-LS14 … R-LS17, R-LS20)."""
from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, evidence, folder_source as fs, markdown_parser, media_ingestor, papers
from api.services.claims import parse_claims

REFERENCES = """# References

## Retrieval

- [Paper Alpha](https://arxiv.org/abs/2401.00001v2) — the architecture alpha-project builds on
- [Paper Beta](https://doi.org/10.1234/Example.5678) — why we cite it
- [A tool](https://github.com/example/tool) — not a paper

## Evaluation

- [Paper Alpha](https://arxiv.org/abs/2401.00001) — reused for the eval baseline
"""
PLAN = "# Plan\n\nWe follow arXiv:2401.00001 and doi:10.1234/example.5678 for alpha-project.\n"
BETA = papers.PaperKey(doi="10.1234/example.5678").entity_id


def _file(rel, text, mtime=1_756_000_000.0):
    raw = text.encode("utf-8")
    return fs.IncomingFile(rel, mtime, hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode())


def _body(files):
    return {"files": [{"relpath": f.relpath, "mtime": f.mtime, "sha256": f.sha256, "contentB64": f.content_b64}
                      for f in files], "deleted": []}


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    return memory


def _folder(bank):
    project_id, _ = fs.ensure_project(bank, "alpha-project", path="/Users/example/alpha-project", device="mac-1")
    return fs.register(bank, label="alpha-project", path="/Users/example/alpha-project", device="mac-1",
                       project_id=project_id)


def _sync(bank, folder, files, deleted=()):
    bank_index.invalidate()
    out = fs.sync(bank, folder, files, list(deleted))
    staged = out["_staged"]
    return papers.reconcile(bank, fs.get_folder(bank, folder["id"]), touched=staged.touched,
                            tombstoned=staged.tombstoned_sources, renamed=staged.renamed_sources)


def _claims(bank, entity_id):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{entity_id}.md").body)


def _claim(bank, entity_id, predicate):
    (claim,) = [c for c in _claims(bank, entity_id) if c.predicate == predicate]
    return claim


def test_parse_reads_bullets_sections_and_bare_mentions():
    bullets = [c for c in papers.parse(REFERENCES) if c.kind == "bullet"]
    assert [(c.key.arxiv_id or c.key.doi, c.section) for c in bullets] == [
        ("2401.00001", "Retrieval"), ("10.1234/example.5678", "Retrieval"), ("2401.00001", "Evaluation")]
    first = bullets[0]
    assert REFERENCES[first.line_start:first.line_end].startswith("- [Paper Alpha]")
    assert first.note == "the architecture alpha-project builds on" and first.title == "Paper Alpha"
    assert REFERENCES[first.heading_start:first.heading_end] == "Retrieval"
    assert {(c.kind, c.key.arxiv_id or c.key.doi) for c in papers.parse(PLAN)} == {
        ("mention", "2401.00001"), ("mention", "10.1234/example.5678")}
    fence = "`" * 3
    assert papers.parse(f"{fence}\n- [X](https://arxiv.org/abs/2401.00003)\n{fence}\n") == []
    assert papers.count_papers([REFERENCES, PLAN]) == 2


def test_keys_normalise():
    assert papers.key_from_url("https://arxiv.org/pdf/2401.00001v3.pdf") == papers.PaperKey(arxiv_id="2401.00001")
    assert papers.key_for_doi("10.48550/arXiv.2401.00001") == papers.PaperKey(arxiv_id="2401.00001")
    assert papers.key_for_doi("10.1234/ABC.9).") == papers.PaperKey(doi="10.1234/abc.9")
    assert papers.PaperKey(arxiv_id="2401.00001").entity_id == "media-arxiv-2401-00001"
    assert papers.key_from_url("https://example.com/x") is None


def test_a_references_file_makes_paper_pages_with_why_claims(bank):
    markdown_parser.write(bank / "entities" / "retrieval.md", {"name": "Retrieval", "type": "concept"}, "## Summary\nx")
    folder = _folder(bank)
    report = _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    assert (report["papers_created"], report["papers_found"]) == (2, 2)
    page = markdown_parser.parse(bank / "entities" / "media-arxiv-2401-00001.md")
    fm = page.frontmatter
    assert (fm["type"], fm["media"]["kind"], fm["decay_class"], fm["origin"]) == ("media", "paper", "evergreen", "folder")
    assert fm["enrichment_attempted"] is True and fm["name"] == "Paper Alpha"
    assert fm["paper"]["arxiv_id"] == "2401.00001" and set(fm["paper"]["sections"]) == {"Retrieval", "Evaluation"}
    assert [s["ref"] for s in fm["sources"]] == ["https://arxiv.org/abs/2401.00001"]
    saved = [c for c in parse_claims(page.body) if c.predicate == "saved-because"]
    assert {c.object for c in saved} == {"the architecture alpha-project builds on", "reused for the eval baseline"}
    body = markdown_parser.parse(next((bank / "episodes").glob("ep_*.md"))).body
    for claim in saved:
        (ev,) = claim.evidence
        assert (claim.source_trust, claim.observer, ev.kind) == ("user_stated", "owner", "user")
        assert body[ev.start:ev.end] == claim.object
    assert _claim(bank, "media-arxiv-2401-00001", "cited-in").object == folder["project_id"]
    assert _claim(bank, "media-arxiv-2401-00001", "about").object == "retrieval"  # R-LS16: by name only
    idx = media_ingestor.load_url_index(bank)
    rows = [e for e in idx.values() if e["media_entity_id"] == "media-arxiv-2401-00001"]
    assert len(rows) == 1 and rows[0]["kind"] == "paper" and "alias_of" not in rows[0]


def test_a_plan_that_cites_the_paper_adds_its_own_span_to_cited_in(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES), _file("PLAN.md", PLAN)])
    cited = _claim(bank, "media-arxiv-2401-00001", "cited-in")
    assert len({e.episode for e in cited.evidence}) == 2


def test_an_edited_annotation_supersedes_the_old_saved_because(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    edited = REFERENCES.replace("the architecture alpha-project builds on", "the backbone of alpha-project")
    _sync(bank, folder, [_file("REFERENCES.md", edited, mtime=1_756_100_000.0)])
    saved = {c.object: c for c in _claims(bank, "media-arxiv-2401-00001") if c.predicate == "saved-because"}
    old, new = saved["the architecture alpha-project builds on"], saved["the backbone of alpha-project"]
    assert old.valid_to and old.superseded_by == new.id and new.valid_to is None
    assert saved["reused for the eval baseline"].valid_to is None


def test_re_parsing_a_file_replaces_its_span_rather_than_stacking_it(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])
    _sync(bank, folder, [_file("REFERENCES.md", "Intro.\n\n" + REFERENCES, mtime=1_756_100_000.0)])
    (ev,) = _claim(bank, "media-arxiv-2401-00001", "cited-in").evidence
    assert ev.hash == evidence.body_hash(evidence.source_text(bank, ev.episode))


def test_a_paper_no_file_cites_any_more_asks_through_the_inbox(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("REFERENCES.md", REFERENCES), _file("PLAN.md", PLAN)])
    without_beta = REFERENCES.replace("- [Paper Beta](https://doi.org/10.1234/Example.5678) — why we cite it\n", "")
    assert _sync(bank, folder, [_file("REFERENCES.md", without_beta, mtime=1_756_100_000.0)])["removals_proposed"] == 0
    assert _sync(bank, folder, [], deleted=["PLAN.md"])["removals_proposed"] == 1
    (item,) = (bank / "inbox").glob("inbox-*.md")
    fm = markdown_parser.parse(item).frontmatter
    assert (fm["kind"], fm["entity_id"], fm["channel"]) == ("removal", BETA, f"folder:{folder['id']}")
    assert [o["key"] for o in fm["options"]] == ["keep", "remove"] and fm["allow_other"] is False
    assert _claim(bank, BETA, "cited-in").valid_to
    assert _sync(bank, folder, [], deleted=["PLAN.md"])["removals_proposed"] == 0  # asked once


def test_a_paper_saved_as_a_bookmark_first_is_upgraded_not_duplicated(bank):
    url = "https://arxiv.org/pdf/2401.00001v2"
    media_ingestor.save_url_index(bank, {media_ingestor.url_hash(url): {
        "media_entity_id": "media-paper-alpha", "episode_id": "ep_2026-01-01_001", "url": url,
        "title": "Paper Alpha", "media_type": "url", "thumbnail": None, "saved_at": "2026-01-01T00:00:00+00:00"}})
    markdown_parser.write(bank / "entities" / "media-paper-alpha.md", {
        "name": "Paper Alpha", "type": "media", "origin": "chrome-bookmark",
        "media": {"url": url, "media_type": "url"}, "tags": ["url"], "source_episodes": ["ep_2026-01-01_001"]},
        "## Summary\nSaved url.")
    folder = _folder(bank)
    assert _sync(bank, folder, [_file("REFERENCES.md", REFERENCES)])["papers_created"] == 1  # Beta only
    assert not (bank / "entities" / "media-arxiv-2401-00001.md").exists()
    fm = markdown_parser.parse(bank / "entities" / "media-paper-alpha.md").frontmatter
    assert fm["media"]["kind"] == "paper" and fm["paper"]["arxiv_id"] == "2401.00001" and "paper" in fm["tags"]
    alias = media_ingestor.load_url_index(bank)[media_ingestor.url_hash("https://arxiv.org/abs/2401.00001")]
    assert alias["alias_of"] == media_ingestor.url_hash(url)
    assert _sync(bank, folder, [], deleted=["REFERENCES.md"])["removals_proposed"] == 1  # Beta, never Alpha


def test_a_sweep_only_citation_is_the_agents_word(bank):
    folder = _folder(bank)
    _sync(bank, folder, [_file("archive/2026-01/sweep.md", "See arXiv:2401.00009 for more.")])
    cited = _claim(bank, "media-arxiv-2401-00009", "cited-in")
    assert (cited.observer, cited.source_trust, cited.evidence[0].kind) == ("agent", "agent_reflected", "assistant")


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), bank
    config.get_settings.cache_clear()


def test_the_route_previews_papers_and_waits_for_a_running_sleep(client, monkeypatch):
    from api.services import sleep_cycle

    c, bank = client
    fid = c.post("/sources/folders", json={"label": "alpha-project", "path": "/Users/example/alpha-project"}).json()["id"]
    pre = c.post(f"/sources/folders/{fid}/sync", params={"preview": "true"},
                 json=_body([_file("REFERENCES.md", REFERENCES)])).json()
    assert pre["papersFound"] == 2 and not list((bank / "entities").glob("media-*.md"))
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    r = c.post(f"/sources/folders/{fid}/sync", json=_body([_file("REFERENCES.md", REFERENCES)])).json()
    assert r["papersPending"] is True and r["created"] == 1
    assert not (bank / "entities" / "media-arxiv-2401-00001.md").exists()  # R-LS17
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="idle"))
    r = c.post(f"/sources/folders/{fid}/sync", json=_body([])).json()
    assert r["papersCreated"] == 2 and (bank / "entities" / "media-arxiv-2401-00001.md").exists()
    assert fs.get_folder(bank, fid)["papers_pending"] is False
```

Run → fails (no module).

- [ ] **Step 2: `api/services/papers.py`.**

```python
"""Papers in a watched folder, parsed with no LLM (G133 · R-F3 · G121).

A folder's reference list — ``- [Title](https://arxiv.org/abs/<id>) — why``
bullets under H2 sections — is the cheapest possible input for a paper page:
every entry already has a title, a canonical id and a one-line reason in the
person's (or their agent's) words. So this module never asks a model:

* **Pages.** A paper is a ``media`` page with ``media.kind: paper`` (the G2
  closure: no new entity type) and a ``paper:`` block, evergreen, keyed by the
  normalised arXiv id or the lowercased DOI. Both canonical URLs sit in
  ``url_index.json`` — the second as an ``alias_of`` entry — so a DOI link and
  an arXiv link never fork one paper, and a paper already saved some other way
  is upgraded in place, never duplicated (R-LS14).
* **Why it matters to you** (G121, anchored on the owner). Personal-tier
  claims, each with a G118 span into the folder file's episode:
  ``saved-because`` (the bullet's annotation), ``cited-in`` (the folder's
  project), ``about`` (the section's concept, when one exists by name —
  R-LS16). Whose words they are follows the file's authorship (R-F2): the
  person's own (``user_stated``, observer = owner) or an agent's sweep
  (``agent_reflected``, observer ``agent``, ``assistant`` spans).
* **World tier** comes later and separately: ``paper_metadata`` stores the
  abstract as a dated cache (R-LS19).

Claims are written by :func:`apply_claims`, not ``agentic_write.write_claim``
(R-LS15): a references file re-parses hundreds of papers per save, and one parse
+ one write per page — deterministic ids, this file's spans replaced rather
than appended, claims the file no longer supports closed with ``valid_to``
(never deleted) — is what keeps a watched folder cheap and its history honest.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import (
    bank_index,
    decay_policy,
    episode_ids,
    episode_staging,
    evidence,
    folder_source,
    markdown_parser,
    media_ingestor,
)
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, write_claims
from api.services.id_utils import sanitize_id

KIND = "paper"
ORIGIN = folder_source.ORIGIN
CITATIONS_FILENAME = "folder_citations.json"
WHY_PREDICATES = ("saved-because", "cited-in", "about")
_CONCEPT_TYPES = frozenset({"concept", "tool", "skill", "project"})
_CONFIDENCE = {
    "user": {"saved-because": 0.9, "cited-in": 0.8, "about": 0.6},
    "agent": {"saved-because": 0.6, "cited-in": 0.5, "about": 0.4},
}

_NEW_ID = r"\d{4}\.\d{4,5}"
_OLD_ID = r"[a-z][a-z.\-]*/\d{7}"
_ID = rf"(?P<id>{_NEW_ID}|{_OLD_ID})(?:v\d+)?"
ARXIV_URL_RE = re.compile(rf"https?://(?:www\.|export\.)?arxiv\.org/(?:abs|pdf|html)/{_ID}(?:\.pdf)?", re.IGNORECASE)
ARXIV_TAG_RE = re.compile(rf"\barxiv:\s?{_ID}", re.IGNORECASE)
_DOI = r"(?P<doi>10\.\d{4,9}/[^\s\"'<>\]]+)"
DOI_URL_RE = re.compile(rf"https?://(?:dx\.)?doi\.org/{_DOI}", re.IGNORECASE)
DOI_TAG_RE = re.compile(rf"\bdoi:\s?{_DOI}", re.IGNORECASE)
BULLET_RE = re.compile(
    r"^[ \t]*[-*+][ \t]+\[(?P<title>[^\]\n]+)\]\((?P<url>[^)\s]+)\)[ \t]*"
    r"(?:(?:—|–|--|-|:)[ \t]*(?P<note>\S.*?))?[ \t]*$")
H2_RE = re.compile(r"^##[ \t]+(?P<h>.+?)[ \t]*#*[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]*(`{3}|~{3})")
# arXiv mints DOIs of the form 10.48550/arXiv.<id>; those ARE the arXiv paper.
_ARXIV_DOI_PREFIX = "10.48550/arxiv."
_TRAILING = ".,;:)]}>'\""


def normalise_arxiv(raw: str) -> str:
    return re.sub(r"v\d+$", "", (raw or "").strip().lower())


def normalise_doi(raw: str) -> str:
    return (raw or "").strip().rstrip(_TRAILING).lower()


@dataclass(frozen=True)
class PaperKey:
    arxiv_id: str | None = None
    doi: str | None = None

    @property
    def abs_url(self) -> str | None:
        return f"https://arxiv.org/abs/{self.arxiv_id}" if self.arxiv_id else None

    @property
    def doi_url(self) -> str | None:
        return f"https://doi.org/{self.doi}" if self.doi else None

    @property
    def canonical_url(self) -> str:
        return self.abs_url or self.doi_url or ""

    @property
    def entity_id(self) -> str:
        """Id-based, so identity never depends on which title arrived first (R-LS14)."""
        if self.arxiv_id:
            return "media-arxiv-" + re.sub(r"[^a-z0-9]+", "-", self.arxiv_id).strip("-")
        return "media-doi-" + hashlib.sha1((self.doi or "").encode()).hexdigest()[:10]


def key_for_doi(raw: str) -> PaperKey:
    doi = normalise_doi(raw)
    if doi.startswith(_ARXIV_DOI_PREFIX):
        return PaperKey(arxiv_id=normalise_arxiv(doi[len(_ARXIV_DOI_PREFIX):]))
    return PaperKey(doi=doi)


def key_from_url(url: str) -> PaperKey | None:
    m = ARXIV_URL_RE.search(url or "")
    if m:
        return PaperKey(arxiv_id=normalise_arxiv(m.group("id")))
    m = DOI_URL_RE.search(url or "")
    if m:
        return key_for_doi(m.group("doi"))
    return None


@dataclass
class Citation:
    key: PaperKey
    kind: str  # "bullet" | "mention"
    line_start: int
    line_end: int
    quote: str  # the words a cited-in span points at
    title: str | None = None
    note: str | None = None
    section: str | None = None
    heading_start: int | None = None
    heading_end: int | None = None


def parse(text: str) -> list[Citation]:
    """Every paper a document cites, with offsets into ``text`` — which is the
    stored episode body, so the offsets are evidence offsets. Reference bullets
    carry a title and the annotation; any other arXiv/DOI URL or ``arXiv:`` /
    ``doi:`` tag is a bare mention. Code fences are skipped."""
    out: list[Citation] = []
    section: str | None = None
    h_start = h_end = None
    in_fence = False
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        line = raw.rstrip("\r\n")
        start, end = offset, offset + len(line)
        offset += len(raw)
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = H2_RE.match(line)
        if h:
            section = h.group("h").strip()
            h_start, h_end = start + h.start("h"), start + h.end("h")
            continue
        b = BULLET_RE.match(line)
        if b:
            key = key_from_url(b.group("url"))
            if key is not None:
                title = b.group("title").strip()
                out.append(Citation(key=key, kind="bullet", line_start=start, line_end=end, quote=title,
                                    title=title, note=(b.group("note") or "").strip() or None,
                                    section=section, heading_start=h_start, heading_end=h_end))
                continue
        seen: set[PaperKey] = set()
        for rx, is_doi in ((ARXIV_URL_RE, False), (ARXIV_TAG_RE, False), (DOI_URL_RE, True), (DOI_TAG_RE, True)):
            for m in rx.finditer(line):
                key = key_for_doi(m.group("doi")) if is_doi else PaperKey(arxiv_id=normalise_arxiv(m.group("id")))
                if key in seen:
                    continue
                seen.add(key)
                out.append(Citation(key=key, kind="mention", line_start=start, line_end=end,
                                    quote=line.strip()[: evidence.MAX_QUOTE_CHARS], section=section,
                                    heading_start=h_start, heading_end=h_end))
    return out


def count_papers(texts: list[str]) -> int:
    return len({c.key for t in texts for c in parse(t)})


def is_paper(fm: dict) -> bool:
    media = fm.get("media") if isinstance(fm, dict) else None
    return isinstance(media, dict) and media.get("kind") == KIND


def page_path(memory_path: Path, entity_id: str) -> Path:
    return Path(memory_path) / "entities" / f"{entity_id}.md"


# --- Pages ------------------------------------------------------------------


def _known_papers(idx: dict) -> dict[PaperKey, str]:
    """PaperKey -> media entity id for every saved URL that names a paper — a
    bookmark of ``arxiv.org/pdf/<id>v2`` included (R-LS14)."""
    out: dict[PaperKey, str] = {}
    for entry in idx.values():
        if not isinstance(entry, dict):
            continue
        key = key_from_url(str(entry.get("url") or ""))
        eid = str(entry.get("media_entity_id") or "")
        if key and eid:
            out.setdefault(key, eid)
    return out


def index_aliases(idx: dict, key: PaperKey, entity_id: str, *, title: str | None,
                  episode_id: str | None = None) -> bool:
    """Both canonical URLs into ``url_index.json`` (R-LS14). The first entry the
    page owns is its Feed row; every other is ``alias_of`` that row, so a DOI
    link and an arXiv link to one paper dedup against each other and still
    render as ONE row."""
    primary = next((h for h, e in idx.items() if isinstance(e, dict)
                    and e.get("media_entity_id") == entity_id and not e.get("alias_of")), None)
    changed = False
    for url in (key.abs_url, key.doi_url):
        if not url:
            continue
        h = media_ingestor.url_hash(url)
        if h in idx:
            continue
        if primary is None:
            idx[h] = {"media_entity_id": entity_id, "episode_id": episode_id or "", "url": url,
                      "title": title or "", "media_type": "url", "kind": KIND, "thumbnail": None,
                      "saved_at": episode_ids.utc_now_iso(), "origin": ORIGIN}
            primary = h
        else:
            idx[h] = {"media_entity_id": entity_id, "url": url, "alias_of": primary, "kind": KIND}
        changed = True
    return changed


def _placeholder(key: PaperKey) -> str:
    return f"arXiv {key.arxiv_id}" if key.arxiv_id else f"DOI {key.doi}"


def _upgrade(path: Path, key: PaperKey, section: str | None, episode_id: str) -> bool:
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    before = json.dumps(fm, sort_keys=True, default=str)
    fm["media"] = {**(fm.get("media") or {}), "kind": KIND}
    paper = dict(fm.get("paper") or {})
    if key.arxiv_id and not paper.get("arxiv_id"):
        paper["arxiv_id"] = key.arxiv_id
    if key.doi and not paper.get("doi"):
        paper["doi"] = key.doi
    sections = list(paper.get("sections") or [])
    if section and section not in sections:
        sections.append(section)
    paper["sections"] = sections
    paper.setdefault("title_from", "page")
    fm["paper"] = paper
    fm["tags"] = sorted(set(fm.get("tags") or []) | {KIND} | ({sanitize_id(section)} if section else set()))
    episodes = list(fm.get("source_episodes") or [])
    if episode_id not in episodes:
        episodes.append(episode_id)
    fm["source_episodes"] = episodes
    # A paper page is the arXiv/Crossref APIs' to describe, never a scrape (R-LS19).
    fm["enrichment_attempted"] = True
    if json.dumps(fm, sort_keys=True, default=str) == before:
        return False
    markdown_parser.write(path, fm, parsed.body)
    return True


def ensure_page(memory_path: Path, key: PaperKey, *, title: str | None, section: str | None,
                episode_id: str, idx: dict, known: dict, today: str) -> tuple[str, bool, bool, bool]:
    """``(entity_id, created, page_changed, index_changed)``."""
    entity_id = known.get(key)
    if entity_id is None and page_path(memory_path, key.entity_id).exists():
        entity_id = key.entity_id
    if entity_id is not None and page_path(memory_path, entity_id).exists():
        changed = _upgrade(page_path(memory_path, entity_id), key, section, episode_id)
        return entity_id, False, changed, index_aliases(idx, key, entity_id, title=None, episode_id=episode_id)
    entity_id = key.entity_id
    name = (title or "").strip() or _placeholder(key)
    fm = {
        "name": name, "type": "media", "status": "active", "confidence": 0.8,
        "created": today, "last_referenced": today,
        **decay_policy.frontmatter_fields(decay_policy.default_class_for("media", source="media")),
        "source_episodes": [episode_id],
        "tags": sorted({KIND} | ({sanitize_id(section)} if section else set())),
        "related": [], "version": 1, "origin": ORIGIN,
        "enrichment_attempted": True,
        "media": {"url": key.canonical_url, "media_type": "url", "kind": KIND,
                  "site": "arxiv.org" if key.arxiv_id else "doi.org", "channel": None, "thumbnail": None,
                  "saved_at": episode_ids.utc_now_iso(), "url_hash": media_ingestor.url_hash(key.canonical_url)},
        "paper": {"arxiv_id": key.arxiv_id, "doi": key.doi, "title": None, "authors": [],
                  "published": None, "updated": None, "primary_category": None, "journal_ref": None,
                  "venue": None, "sections": [section] if section else [],
                  "title_from": "bullet" if title else "placeholder"},
        "sources": [{"ref": u, "kind": "url", "added_by": "cicada", "added_at": today}
                    for u in (key.abs_url, key.doi_url) if u],
    }
    path = page_path(memory_path, entity_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, fm, f"## Summary\nSaved paper — {name}.")
    index_aliases(idx, key, entity_id, title=name, episode_id=episode_id)
    return entity_id, True, True, True


# --- Claims (R-LS15) --------------------------------------------------------


def claim_id(*parts: str) -> str:
    return "clm_paper_" + hashlib.sha1("\x00".join(parts).encode()).hexdigest()[:10]


def desired_claims(*, entity_id: str, citations: list[Citation], episode_id: str, text: str,
                   authorship: str, owner: str, folder_id: str, project_id: str | None,
                   project_name: str | None, concept_for, today: str, valid_from: str) -> list[Claim]:
    """What ``episode_id`` says about this paper now, as claims."""
    who = "user" if authorship == "user" else "agent"
    observer = owner if who == "user" else "agent"
    trust = "user_stated" if who == "user" else "agent_reflected"
    kind = "user" if who == "user" else "assistant"
    out: dict[str, Claim] = {}

    def claim(predicate: str, obj: str, *, literal: bool, context: str, text_: str, quote: str,
              window: tuple[int, int]) -> None:
        cid = claim_id(entity_id, predicate, obj, observer, context)
        if cid in out:
            return
        out[cid] = Claim(
            id=cid, text=text_, subject=entity_id, predicate=predicate, object=obj,
            object_kind="literal" if literal else "node", observer=observer, context=context,
            epistemic="explicit", source_trust=trust, confidence=_CONFIDENCE[who][predicate],
            valid_from=valid_from, recorded_at=today, source_episodes=[episode_id],
            authored_by="user" if who == "user" else None, origin=ORIGIN,
            evidence=[evidence.verify(None, episode_id, quote, text=text, window=window, kind_override=kind)],
        )

    for c in citations:
        if c.note:
            section = sanitize_id(c.section) if c.section else "top"
            claim("saved-because", c.note, literal=True, context=f"folder:{folder_id}:{section}",
                  text_=c.note, quote=c.note, window=(c.line_start, c.line_end))
        if project_id:
            claim("cited-in", project_id, literal=False, context="general",
                  text_=f"Cited in {project_name or project_id}.", quote=c.quote,
                  window=(c.line_start, c.line_end))
        concept = concept_for(c.section) if c.section else None
        if concept and c.heading_start is not None:
            claim("about", concept, literal=False, context="general", text_=f"Filed under {c.section}.",
                  quote=c.section, window=(c.heading_start, c.heading_end))
    return list(out.values())


def apply_claims(page: Path, episode_id: str, desired: list[Claim], today: str) -> bool:
    """Make this page's folder claims from ``episode_id`` equal ``desired``.

    A wanted claim that exists gets THIS episode's span replaced (not appended —
    ``claim_reconciler._reinforce`` would stack a stale span per edit) and is
    reopened if it had been closed. A folder claim this episode supported and no
    longer does loses this episode's span; if that was its last span it is
    closed with ``valid_to`` (and ``superseded_by`` its successor in the same
    predicate + context, e.g. an edited annotation). Nothing is deleted."""
    if not page.exists():
        return False
    parsed = markdown_parser.parse(page)
    try:
        claims = parse_claims(parsed.body, strict=True)
    except MalformedClaimsBlockError as exc:
        logger.error(f"corrupt claims block on {page.name}, paper claims skipped: {exc}")
        return False
    by_id = {c.id: c for c in claims}
    wanted = {c.id for c in desired}
    for new in desired:
        old = by_id.get(new.id)
        if old is None:
            claims.append(new)
            by_id[new.id] = new
            continue
        old.evidence = [e for e in old.evidence if e.episode != episode_id] + list(new.evidence)
        if episode_id not in old.source_episodes:
            old.source_episodes.append(episode_id)
        if old.valid_to:
            old.valid_to = None
            old.superseded_by = None
    for c in claims:
        if c.origin != ORIGIN or c.valid_to or c.id in wanted:
            continue
        if not any(e.episode == episode_id for e in c.evidence):
            continue
        others = [e for e in c.evidence if e.episode != episode_id]
        if others:
            c.evidence = others
            continue
        c.valid_to = today
        c.superseded_by = next((d.id for d in desired
                                if d.predicate == c.predicate and d.context == c.context), None)
    new_body = write_claims(parsed.body, claims)
    if new_body == parsed.body:
        return False
    markdown_parser.write(page, parsed.frontmatter, new_body)
    return True


# --- Removals (R-LS20) ------------------------------------------------------


def propose_removals(memory_path: Path, entity_ids: list[str], folder: dict) -> list[str]:
    """One G129-shaped ``removal`` item per paper the folder created that no file
    cites any more. A paper saved some other way first (``origin`` is not
    ``folder``) is never proposed; a pending item is never duplicated."""
    from api.services import inbox_generator, inbox_service

    inbox_dir = Path(memory_path) / "inbox"
    label = str(folder.get("label") or "a folder")
    written: list[str] = []
    next_num: int | None = None
    for eid in entity_ids:
        path = page_path(memory_path, eid)
        if not path.exists():
            continue
        fm = markdown_parser.parse(path).frontmatter
        if fm.get("origin") != ORIGIN or not is_paper(fm):
            continue
        if str(fm.get("status") or "active") in ("archived", "dropped"):
            continue
        if inbox_generator.find_open(Path(memory_path), "removal", eid) is not None:
            continue
        inbox_dir.mkdir(parents=True, exist_ok=True)
        if next_num is None:
            next_num = inbox_service.next_inbox_num(inbox_dir)
        item_id = f"inbox-{next_num:03d}"
        next_num += 1
        name = str(fm.get("name") or eid)
        markdown_parser.write(inbox_dir / f"{item_id}.md", {
            "kind": "removal", "required_input": "choice", "status": "pending", "priority": 0.4,
            "entity_id": eid, "entity_name": name, "title": f"Still keep {name}?",
            "created_date": date.today().isoformat(),
            "question": f"It isn't cited anywhere in {label} any more.",
            # keep first — QuestionSelection's no-recommendation fallback highlights index 0.
            "options": [{"key": "keep", "label": "Keep"}, {"key": "remove", "label": "Remove"}],
            "allow_other": False, "allow_defer": True,
            # `browser` is the key `inbox_context.cause_for` reads for a removal's
            # "Removed from <where>" excerpt (G129 slice 2); here it names the folder.
            "channel": folder_source.channel_id(folder["id"]), "browser": label,
            "url": str((fm.get("media") or {}).get("url") or ""), "synced_at": episode_ids.utc_now_iso(),
            "hint": None, "trigger": "sync/folder_removal",
        }, f"{name} is no longer cited in {label}.")
        written.append(f"inbox/{item_id}.md")
    return written


# --- Reconcile --------------------------------------------------------------


def _citations_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / CITATIONS_FILENAME


def load_citations(memory_path: Path) -> dict[str, list[str]]:
    """``source_id -> [paper entity ids]`` — the previous set a re-parse diffs
    against (the ``bookmark_seen.json`` pattern, G129)."""
    try:
        data = json.loads(_citations_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): [str(x) for x in v] for k, v in data.items() if isinstance(v, list)} if isinstance(data, dict) else {}


def save_citations(memory_path: Path, cites: dict[str, list[str]]) -> None:
    path = _citations_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cites, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _owner(memory_path: Path) -> str:
    from api.config import get_settings
    from api.services import owner_identity

    return owner_identity.resolve_observer(memory_path, get_settings())


def _name_of(memory_path: Path, entity_id: str | None) -> str | None:
    if not entity_id or not page_path(memory_path, entity_id).exists():
        return None
    return str(markdown_parser.parse(page_path(memory_path, entity_id)).frontmatter.get("name") or entity_id)


def _concept_matcher(memory_path: Path):
    """Section heading -> an existing concept/tool/skill/project id, by the
    zero-LLM half of Stage 2's matcher (R-LS16)."""
    from api.services import entity_resolver

    pool = [{"id": f.stem, "frontmatter": f.frontmatter} for f in bank_index.files(Path(memory_path), "entities")
            if (f.frontmatter or {}).get("type") in _CONCEPT_TYPES]
    by_name = entity_resolver.existing_by_name(pool)
    cache: dict[str, str | None] = {}

    def match(section: str | None) -> str | None:
        key = (section or "").strip()
        if not key:
            return None
        if key not in cache:
            hit = entity_resolver._find_direct_candidate_match({"name": key}, by_name, {})
            cache[key] = hit["candidate"]["id"] if hit else None
        return cache[key]

    return match


def reconcile(memory_path: Path, folder: dict, *, touched: dict[str, str], tombstoned: dict[str, str],
              renamed=()) -> dict:
    """Re-parse the episodes a sync touched and bring paper pages, claims and
    removal proposals in line. Idempotent: running it twice changes nothing."""
    memory_path = Path(memory_path)
    today = date.today().isoformat()
    cites = load_citations(memory_path)
    for old, new in renamed:
        if old in cites:
            cites[new] = cites.pop(old)
    idx = media_ingestor.load_url_index(memory_path)
    known = _known_papers(idx)
    owner = _owner(memory_path)
    concept_for = _concept_matcher(memory_path)
    project_id = str(folder.get("project_id") or "") or None
    project_name = _name_of(memory_path, project_id)
    report = {"papers_found": 0, "papers_created": 0, "claims_changed": 0, "removals_proposed": 0}
    paths: set[str] = set()
    idx_changed = False
    revisit: set[str] = set()
    for sid, ep_id in touched.items():
        text, fm = evidence.source_document(memory_path, ep_id)
        if text is None:
            continue
        by_page: dict[str, list[Citation]] = {}
        for c in parse(text):
            eid, created, page_changed, index_changed = ensure_page(
                memory_path, c.key, title=c.title, section=c.section, episode_id=ep_id,
                idx=idx, known=known, today=today)
            known.setdefault(c.key, eid)
            idx_changed |= index_changed
            report["papers_created"] += int(created)
            if page_changed:
                paths.add(f"entities/{eid}.md")
            by_page.setdefault(eid, []).append(c)
        previous = set(cites.get(sid, []))
        authorship = str(fm.get("authorship") or "user")
        valid_from = str(fm.get("timestamp") or "")[:10] or today
        for eid in sorted(previous | set(by_page)):
            desired = desired_claims(
                entity_id=eid, citations=by_page.get(eid, []), episode_id=ep_id, text=text,
                authorship=authorship, owner=owner, folder_id=folder["id"], project_id=project_id,
                project_name=project_name, concept_for=concept_for, today=today, valid_from=valid_from)
            if apply_claims(page_path(memory_path, eid), ep_id, desired, today):
                report["claims_changed"] += 1
                paths.add(f"entities/{eid}.md")
        cites[sid] = sorted(by_page)
        revisit |= previous - set(by_page)
        report["papers_found"] += len(by_page)
    for sid, ep_id in tombstoned.items():
        previous = set(cites.pop(sid, []))
        for eid in sorted(previous):
            if apply_claims(page_path(memory_path, eid), ep_id, [], today):
                report["claims_changed"] += 1
                paths.add(f"entities/{eid}.md")
        revisit |= previous
    cited_now = {eid for ids in cites.values() for eid in ids}
    written = propose_removals(memory_path, sorted(revisit - cited_now), folder)
    report["removals_proposed"] = len(written)
    paths.update(written)
    if idx_changed:
        media_ingestor.save_url_index(memory_path, idx)
        paths.add("sources/url_index.json")
    save_citations(memory_path, cites)
    paths.add(f"sources/{CITATIONS_FILENAME}")
    report["paths"] = sorted(paths)
    return report


def reparse_folder(memory_path: Path, folder: dict, *, tombstoned: dict[str, str] | None = None) -> dict:
    """Every live episode of the folder — the deferred path (R-LS17)."""
    index, _ = episode_staging.scan(Path(memory_path) / "episodes")
    touched = {sid: e.id for sid, e in index.items()
               if e.fm.get("folder_id") == folder["id"] and not e.fm.get("source_deleted_at")}
    return reconcile(memory_path, folder, touched=touched, tombstoned=tombstoned or {})


def reconcile_pending(memory_path: Path) -> dict:
    """The Sleep tail's deterministic half: re-parse folders a running cycle
    deferred. Returns ``{"folders": n, "paths": [...]}``."""
    paths: set[str] = set()
    done = 0
    for folder in folder_source.list_folders(memory_path):
        if not folder.get("papers_pending"):
            continue
        report = reparse_folder(memory_path, folder)
        folder_source.set_flags(memory_path, folder["id"], papers_pending=False)
        paths.update(report["paths"])
        done += 1
    if done:
        paths.add(f"sources/{folder_source.FOLDERS_FILENAME}")
    return {"folders": done, "paths": sorted(paths)}
```

- [ ] **Step 3: the route runs the paper step.** In `api/routers/local_sources.py` import
  `papers` beside `folder_source`, and replace the body of `sync_folder` from
  `out = await run_in_threadpool(folder_source.sync, …)` to the end with:

```python
    out = await run_in_threadpool(folder_source.sync, memory_path, folder, files, req.deleted, preview=preview)
    staged = out.pop("_staged")
    texts = out.pop("_texts")
    if preview:
        out["papers_found"] = await run_in_threadpool(papers.count_papers, list(texts.values()))
        return FolderSyncResponse(**out)
    attempted = len(files)
    if attempted and len(out["errors"]) == attempted:
        sync_state.record_error(memory_path, folder_source.channel_id(folder_id),
                                f"{attempted} file(s) could not be read")
    else:
        sync_state.record_sync(memory_path, folder_source.channel_id(folder_id),
                               count=folder_source.live_file_count(memory_path, folder_id))
    paths = list(staged.paths) + [f"sources/{folder_source.FOLDERS_FILENAME}"]
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        # R-LS17: Stage 5 may be rewriting the same pages; the episodes are
        # staged, the paper step waits for the next sync or the Sleep tail.
        folder_source.set_flags(memory_path, folder_id, papers_pending=True)
        out["papers_pending"] = True
    else:
        if folder.get("papers_pending"):
            report = await run_in_threadpool(
                papers.reparse_folder, memory_path, folder, tombstoned=staged.tombstoned_sources)
            folder_source.set_flags(memory_path, folder_id, papers_pending=False)
        else:
            report = await run_in_threadpool(
                papers.reconcile, memory_path, folder, touched=staged.touched,
                tombstoned=staged.tombstoned_sources, renamed=staged.renamed_sources)
        out.update(papers_found=report["papers_found"], papers_created=report["papers_created"],
                   removals_proposed=report["removals_proposed"])
        paths += report["paths"]
    await folder_source.commit_paths_for(
        memory_path, paths, subject=f"Folder sync ({folder['label']})", trigger="folder/sync")
    return FolderSyncResponse(**out)
```

- [ ] **Step 4: Verify** — `test_papers.py` and `test_folder_source.py` green; full suite.
- [ ] **Step 5: Commit** — `feat(G133): reference lists become paper pages with why-it-matters spans, no LLM (R-F3)`.

---

### Task 4: Paper details from arXiv and Crossref; the read surfaces; the Sleep tail (R-F3, R-LS18, R-LS19)

**Files:**
- Create: `api/services/paper_metadata.py`
- Create: `api/tests/fixtures/papers/arxiv_query.atom`, `api/tests/fixtures/papers/crossref_work.json`
- Modify: `api/services/papers.py` (append `detail`), `api/routers/local_sources.py` (`?resolve=`)
- Modify: `api/services/sleep_cycle.py` (`_resolve_papers_safely` + one call in the guarded branch, `:727-733`)
- Modify: `api/services/link_enrichment.py:199-226` (`_candidates`), `:650-703` (`scan_backfill`)
- Modify: `api/routers/sources.py:489-621` (`list_sources`), `api/services/channel_registry.py` (`files` count)
- Modify: `api/routers/entities.py:163-204` (`_build_media_block`) + a new route; `api/models/schemas.py`
  (`EntityMedia.kind`, `MediaSourceItem.kind/paper`, `PaperSummary`, `PaperWhyItem`, `PaperDetailResponse`)
- Test: `api/tests/test_paper_metadata.py` (new)

**Interfaces:**
- Produces `paper_metadata.ARXIV_API`, `CROSSREF_API`, `ARXIV_SPACING_S`, `CROSSREF_SPACING_S`,
  `ARXIV_BATCH`, `RETRY_DAYS`, `TAIL_ARXIV_IDS`, `TAIL_CROSSREF_DOIS`, `USER_AGENT`, `Response`,
  `default_fetch`, `parse_arxiv_atom`, `parse_crossref`, `has_pending`, `resolve`, `record`,
  `run_locked`, `resolve_in_background`; `papers.detail(memory_path, entity_id)`.
- Produces `GET /entities/{id}/paper` → `PaperDetailResponse`; `POST /sources/folders/{id}/sync?resolve=true`.
- Consumes `connectors.base.network_allowed`, `link_enrichment._upsert_description`,
  `fact_sources.add_source`, `sync_state.record_sync/record_error/record_skip`,
  `folder_source.commit_paths_for`.

- [ ] **Step 1: Fixtures.** `api/tests/fixtures/papers/arxiv_query.atom` — shaped like a real
  `export.arxiv.org/api/query` response (synthetic content; one of the two requested ids is absent,
  which is how the API answers an unknown id):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <link href="http://arxiv.org/api/query?id_list=2401.00001,2401.00009" rel="self" type="application/atom+xml"/>
  <title type="html">ArXiv Query: id_list=2401.00001,2401.00009</title>
  <id>http://arxiv.org/api/synthetic-fixture</id>
  <updated>2026-09-23T00:00:00-04:00</updated>
  <opensearch:totalResults>1</opensearch:totalResults>
  <opensearch:startIndex>0</opensearch:startIndex>
  <opensearch:itemsPerPage>2</opensearch:itemsPerPage>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v2</id>
    <updated>2024-02-01T10:00:00Z</updated>
    <published>2024-01-02T10:00:00Z</published>
    <title>Paper Alpha: A Synthetic
  Study</title>
    <summary>  We study a synthetic problem for alpha-project. The method works well.
    </summary>
    <author><name>Ada Example</name></author>
    <author><name>Bob Example</name></author>
    <arxiv:doi>10.9999/alpha.2024</arxiv:doi>
    <arxiv:journal_ref>Journal of Examples 1 (2024)</arxiv:journal_ref>
    <link href="http://arxiv.org/abs/2401.00001v2" rel="alternate" type="text/html"/>
    <arxiv:primary_category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
```

  `api/tests/fixtures/papers/crossref_work.json`:

```json
{"status": "ok", "message-type": "work", "message": {"DOI": "10.1234/example.5678", "title": ["Paper Beta: Examples at Scale"], "author": [{"given": "Carol", "family": "Example"}], "published": {"date-parts": [[2023, 5, 17]]}, "container-title": ["Journal of Synthetic Results"], "abstract": "<jats:p>We report synthetic results.</jats:p>"}}
```

- [ ] **Step 2: Failing tests** — `api/tests/test_paper_metadata.py`:

```python
"""R-F3 / R-LS18 / R-LS19 — paper details from the official APIs only, paced, gated."""
from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (
    bank_index, channel_registry, folder_source as fs, link_enrichment, markdown_parser, media_ingestor,
    paper_metadata as pm, papers, sleep_cycle, sync_state,
)
from api.services.claims import parse_claims

FIX = Path(__file__).parent / "fixtures" / "papers"
ATOM = (FIX / "arxiv_query.atom").read_bytes()
CROSSREF = (FIX / "crossref_work.json").read_bytes()
REFERENCES = """# References

## Retrieval

- [Paper Alpha](https://arxiv.org/abs/2401.00001) — the architecture alpha-project builds on
- [Paper Beta](https://doi.org/10.1234/example.5678) — why we cite it
"""
SWEEP = "An agent found arXiv:2401.00009 while reading."
ALPHA, NINE = "media-arxiv-2401-00001", "media-arxiv-2401-00009"
BETA = papers.PaperKey(doi="10.1234/example.5678").entity_id


def _file(rel, text):
    raw = text.encode()
    return fs.IncomingFile(rel, 1_756_000_000.0, hashlib.sha256(raw).hexdigest(), base64.b64encode(raw).decode())


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    project_id, _ = fs.ensure_project(memory, "alpha-project", path="/Users/example/alpha-project", device="mac-1")
    folder = fs.register(memory, label="alpha-project", path="/Users/example/alpha-project", device="mac-1",
                         project_id=project_id)
    out = fs.sync(memory, folder, [_file("REFERENCES.md", REFERENCES), _file("archive/sweep.md", SWEEP)], [])
    staged = out["_staged"]
    papers.reconcile(memory, folder, touched=staged.touched, tombstoned={}, renamed=[])
    bank_index.invalidate()
    return memory


class _Clock:
    def __init__(self):
        self.t, self.waits = 0.0, []

    def now(self):
        return self.t

    async def sleep(self, s):
        self.waits.append(round(s, 3))
        self.t += s


def _fetcher(calls, *, arxiv=(200, "application/atom+xml", ATOM), crossref=(200, "application/json", CROSSREF)):
    async def fetch(url, params):
        calls.append((url, dict(params)))
        status, ctype, body = arxiv if url == pm.ARXIV_API else crossref
        return pm.Response(status, ctype, body)
    return fetch


def test_parse_arxiv_atom():
    meta = pm.parse_arxiv_atom(ATOM)
    assert list(meta) == ["2401.00001"]
    a = meta["2401.00001"]
    assert a["title"] == "Paper Alpha: A Synthetic Study" and a["authors"] == ["Ada Example", "Bob Example"]
    assert (a["published"], a["updated"], a["primary_category"]) == ("2024-01-02", "2024-02-01", "cs.LG")
    assert a["doi"] == "10.9999/alpha.2024" and a["abstract"].startswith("We study a synthetic problem")
    assert pm.parse_arxiv_atom(b"<not xml") == {}


def test_parse_crossref():
    b = pm.parse_crossref(CROSSREF)
    assert b == {"title": "Paper Beta: Examples at Scale", "authors": ["Carol Example"], "published": "2023-05-17",
                 "abstract": "We report synthetic results.", "venue": "Journal of Synthetic Results",
                 "doi": "10.1234/example.5678"}


def test_resolve_fills_pages_paced_and_backs_off(bank):
    calls, clock = [], _Clock()
    report = asyncio.run(pm.resolve(bank, fetch_fn=_fetcher(calls), clock=clock.now, sleep=clock.sleep))
    assert [c[0] for c in calls] == [pm.ARXIV_API, pm.CROSSREF_API + "10.1234/example.5678"]
    assert calls[0][1] == {"id_list": "2401.00001,2401.00009", "max_results": "2"}
    assert (report["resolved"], report["failed"], report["remaining"]) == (2, 1, 0)
    page = markdown_parser.parse(bank / "entities" / f"{ALPHA}.md")
    paper = page.frontmatter["paper"]
    assert page.frontmatter["name"] == "Paper Alpha"  # the person's title stays the page name
    assert (paper["title"], paper["doi"], paper["metadata_source"]) == (
        "Paper Alpha: A Synthetic Study", "10.9999/alpha.2024", "arxiv")
    assert paper["metadata_at"] == date.today().isoformat()
    assert link_enrichment._extract_description_section(page.body).startswith("We study a synthetic problem")
    (describes,) = [c for c in parse_claims(page.body) if c.predicate == "describes"]
    assert (describes.source_trust, describes.observer, describes.authored_by) == ("external", "external:arxiv", "cicada")
    assert describes.evidence[0].kind == "page" and describes.recorded_at == date.today().isoformat()
    idx = media_ingestor.load_url_index(bank)
    assert idx[media_ingestor.url_hash("https://doi.org/10.9999/alpha.2024")]["alias_of"]
    nine = markdown_parser.parse(bank / "entities" / f"{NINE}.md").frontmatter["paper"]
    assert nine["metadata_status"] == "not_found" and nine["metadata_attempted_at"] == date.today().isoformat()
    beta = markdown_parser.parse(bank / "entities" / f"{BETA}.md").frontmatter["paper"]
    assert beta["venue"] == "Journal of Synthetic Results" and beta["metadata_source"] == "crossref"
    calls.clear()
    bank_index.invalidate()
    asyncio.run(pm.resolve(bank, fetch_fn=_fetcher(calls), clock=clock.now, sleep=clock.sleep))
    assert calls == []  # nothing pending; the missing id is backing off (R-LS18)


def test_arxiv_requests_are_three_seconds_apart(bank, monkeypatch):
    monkeypatch.setattr(pm, "ARXIV_BATCH", 1)
    calls, clock = [], _Clock()
    asyncio.run(pm.resolve(bank, fetch_fn=_fetcher(calls), clock=clock.now, sleep=clock.sleep))
    assert [c[0] for c in calls].count(pm.ARXIV_API) == 2
    assert clock.waits == [pm.ARXIV_SPACING_S]


def test_a_429_stops_arxiv_but_not_crossref_and_marks_nothing(bank):
    calls = []
    report = asyncio.run(pm.resolve(bank, fetch_fn=_fetcher(calls, arxiv=(429, "text/plain", b"")),
                                    clock=_Clock().now, sleep=_Clock().sleep))
    assert report["error"] == "arXiv HTTP 429" and report["resolved"] == 1
    assert "metadata_status" not in markdown_parser.parse(bank / "entities" / f"{ALPHA}.md").frontmatter["paper"]


def test_the_sleep_tail_is_gated_and_finishes_deferred_folders(bank, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("no network with the gate off")

    monkeypatch.setattr(pm, "resolve", boom)
    (folder,) = fs.list_folders(bank)
    fs.set_flags(bank, folder["id"], papers_pending=True)
    (bank / "entities" / f"{BETA}.md").unlink()
    asyncio.run(sleep_cycle._resolve_papers_safely(bank))
    assert (bank / "entities" / f"{BETA}.md").exists()  # the deterministic half ran
    assert sync_state.read_sync_state(bank)["papers"]["last_skip_reason"] == "network fetch disabled"


def test_link_enrichment_never_fetches_a_paper_page(bank):
    scan = link_enrichment.scan_backfill(bank, config.Settings())
    assert not any(c.media_id.startswith("media-arxiv-") or c.media_id.startswith("media-doi-")
                   for c in scan.fetch + scan.reuse)
    assert not any(p.stem.startswith(("media-arxiv-", "media-doi-")) for p in link_enrichment._candidates(bank, 50))


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_feed_shows_one_row_per_paper_with_its_byline(bank, client):
    asyncio.run(pm.resolve(bank, fetch_fn=_fetcher([]), clock=_Clock().now, sleep=_Clock().sleep))
    bank_index.invalidate()
    items = client.get("/sources").json()["items"]
    alpha = [i for i in items if i["mediaEntityId"] == ALPHA]
    assert len(alpha) == 1 and alpha[0]["kind"] == "paper"  # the DOI alias is not a second row
    assert alpha[0]["paper"] == {"authors": ["Ada Example", "Bob Example"], "arxivId": "2401.00001",
                                 "doi": "10.9999/alpha.2024", "published": "2024-01-02",
                                 "venue": "Journal of Examples 1 (2024)"}
    files = channel_registry.build_channels(bank, telegram_enabled=False)
    idx = media_ingestor.load_url_index(bank)
    assert next(r for r in files if r["id"] == "files")["count"] == sum(1 for e in idx.values() if not e.get("alias_of"))
    assert client.get(f"/entities/{ALPHA}").json()["media"]["kind"] == "paper"


def test_the_paper_endpoint_leads_with_why_then_context(bank, client):
    asyncio.run(pm.resolve(bank, fetch_fn=_fetcher([]), clock=_Clock().now, sleep=_Clock().sleep))
    bank_index.invalidate()
    body = client.get(f"/entities/{ALPHA}/paper").json()
    assert [w["predicate"] for w in body["why"]] == ["saved-because", "cited-in"]
    saved = body["why"][0]
    assert (saved["file"], saved["heading"], saved["kind"], saved["text"]) == (
        "REFERENCES.md", "Retrieval", "user", "the architecture alpha-project builds on")
    assert saved["snippet"][saved["highlightStart"]:saved["highlightEnd"]] == saved["text"]
    assert body["agentOnly"] is False
    assert body["context"].startswith("We study") and body["contextSource"] == "arxiv"
    assert body["absUrl"] == "https://arxiv.org/abs/2401.00001" and body["doiUrl"] == "https://doi.org/10.9999/alpha.2024"
    assert client.get(f"/entities/{NINE}/paper").json()["agentOnly"] is True
    assert client.get("/entities/alpha-project/paper").status_code == 404
    assert client.get("/entities/..%2Fsecrets/paper").status_code == 404


def test_a_user_triggered_sync_schedules_one_background_run(bank, client, monkeypatch):
    seen = []

    async def fake(memory_path):
        seen.append(Path(memory_path))

    monkeypatch.setattr(pm, "resolve_in_background", fake)
    (folder,) = fs.list_folders(bank)
    r = client.post(f"/sources/folders/{folder['id']}/sync", params={"resolve": "true"},
                    json={"files": [], "deleted": []})
    assert r.status_code == 200 and seen == [bank]
```

Run → fails (no module).

- [ ] **Step 3: `api/services/paper_metadata.py`.**

```python
"""Paper details from the official APIs, and nothing else (R-F3 · R-LS18 · R-LS19).

arXiv and Crossref both publish machine interfaces with written terms, and
Cicada uses exactly those: ``export.arxiv.org/api/query`` (Atom; "no more than
one request every three seconds … a single connection at a time"; metadata is
CC0; "must not store and serve arXiv e-prints") and ``api.crossref.org/works``
(JSON; the public pool — the polite pool wants a contact email, and Cicada
never sends the person's email). Never ``arxiv.org/abs|pdf|html`` (its
robots file asks for 15 s and forbids indiscriminate downloads), never a PDF,
never behind auth; 4 s and ≤ 512 KB per response, like every other fetch
under the ToS rail.

What a response becomes is a WORLD-tier cache (G121): the abstract as the
page's ``## Description`` and one ``describes`` claim with
``source_trust: external``, an ``external:arxiv|crossref`` observer, ``cicada``
as author and the fetch date as ``recorded_at``. The personal tier — why the
paper is in the person's memory — is ``papers``' and never touched here.

Two callers: the folder sync's ``?resolve=true`` (the person asked; runs in the
background, one run per process) and the Sleep tail (unattended; behind
``CICADA_ALLOW_CONNECTOR_FETCH`` and capped per cycle).
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from api.services import bank_index, evidence, fact_sources, folder_source, markdown_parser, media_ingestor, papers
from api.services.claims import Claim, MalformedClaimsBlockError, parse_claims, strip_claims_block, write_claims

ARXIV_API = "https://export.arxiv.org/api/query"
CROSSREF_API = "https://api.crossref.org/works/"
TIMEOUT_S = 4.0
MAX_BYTES = 512_000
ARXIV_SPACING_S = 3.0
CROSSREF_SPACING_S = 1.0
ARXIV_BATCH = 50
RETRY_DAYS = 30
TAIL_ARXIV_IDS = 200
TAIL_CROSSREF_DOIS = 30
# Names the software, as `logos.manifest.json`'s `userAgent` already does — never a person.
USER_AGENT = "CicadaPaperMetadata/1.0 (+https://github.com/rorosaga/cicada)"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"
_TAG_RE = re.compile(r"<[^>]+>")
_run_lock = threading.Lock()
#: Monotonic start of each API's last request, ACROSS runs: arXiv's "one request every three
#: seconds" does not reset because a run ended (a second "Sync now" right after a first). Only the
#: real clock shares it; a test's injected clock gets a fresh pacer.
_LAST_START: dict[str, float] = {}


@dataclass
class Response:
    status: int
    content_type: str = ""
    body: bytes = b""
    error: str | None = None


FetchFn = Callable[[str, dict], Awaitable[Response]]


async def default_fetch(url: str, params: dict) -> Response:
    """One GET under the ToS rail: 4 s, ≤ 512 KB read, no cookies (a fresh client
    per call), no proxy env, Cicada's own User-Agent, ≤ 3 redirects. Never
    raises; a transport failure is ``status 0`` carrying the exception's name."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True, max_redirects=3,
                                     headers={"User-Agent": USER_AGENT}, trust_env=False) as client:
            async with client.stream("GET", url, params=params or None) as resp:
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= MAX_BYTES:
                        break
                return Response(resp.status_code, (resp.headers.get("content-type") or "").lower(),
                                b"".join(chunks)[:MAX_BYTES])
    except Exception as e:  # noqa: BLE001 - recorded, never raised
        return Response(0, error=type(e).__name__)


class _Pacer:
    """``spacing`` seconds between the starts of consecutive requests, one at a
    time (the caller awaits each fetch before asking again). ``_run_lock`` keeps
    two runs from interleaving in one process, and ``_LAST_START`` carries the
    spacing from one run into the next (R-LS18)."""

    def __init__(self, spacing: float, *, clock, sleep, api: str):
        self.spacing, self._clock, self._sleep = spacing, clock, sleep
        self._key = api if clock is time.monotonic else None
        self._last: float | None = _LAST_START.get(self._key) if self._key else None

    async def wait(self) -> None:
        if self._last is not None:
            gap = self.spacing - (self._clock() - self._last)
            if gap > 0:
                await self._sleep(gap)
        self._last = self._clock()
        if self._key:
            _LAST_START[self._key] = self._last


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def parse_arxiv_atom(body: bytes) -> dict[str, dict]:
    """``arxiv id -> metadata`` from an API response. An id the API does not
    know is simply absent (arXiv answers with fewer entries, or an ``Error``
    entry whose id is not an abs URL)."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return {}
    out: dict[str, dict] = {}
    for entry in root.findall(f"{_ATOM}entry"):
        m = papers.ARXIV_URL_RE.search(entry.findtext(f"{_ATOM}id") or "")
        if not m:
            continue
        category = entry.find(f"{_ARXIV}primary_category")
        out[papers.normalise_arxiv(m.group("id"))] = {
            "title": _clean(entry.findtext(f"{_ATOM}title")) or None,
            "abstract": _clean(entry.findtext(f"{_ATOM}summary")) or None,
            "authors": [n for n in (_clean(a.findtext(f"{_ATOM}name")) for a in entry.findall(f"{_ATOM}author")) if n],
            "published": (entry.findtext(f"{_ATOM}published") or "")[:10] or None,
            "updated": (entry.findtext(f"{_ATOM}updated") or "")[:10] or None,
            "primary_category": category.get("term") if category is not None else None,
            "doi": papers.normalise_doi(entry.findtext(f"{_ARXIV}doi") or "") or None,
            "journal_ref": _clean(entry.findtext(f"{_ARXIV}journal_ref")) or None,
        }
    return out


def parse_crossref(body: bytes) -> dict | None:
    try:
        msg = json.loads(body.decode("utf-8", errors="replace")).get("message") or {}
    except (ValueError, AttributeError):
        return None
    authors = []
    for a in msg.get("author") or []:
        name = _clean(" ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name"))
        if name:
            authors.append(name)
    parts: list = []
    for key in ("published", "published-print", "published-online", "issued"):
        candidate = ((msg.get(key) or {}).get("date-parts") or [[]])[0]
        if candidate and candidate[0]:
            parts = candidate
            break
    published = "-".join(f"{int(p):04d}" if i == 0 else f"{int(p):02d}" for i, p in enumerate(parts) if p) or None
    return {
        "title": _clean((msg.get("title") or [None])[0]) or None,
        "authors": authors,
        "published": published,
        "abstract": _clean(_TAG_RE.sub(" ", msg.get("abstract") or "")) or None,
        "venue": _clean((msg.get("container-title") or [None])[0]) or None,
        "doi": papers.normalise_doi(msg.get("DOI") or "") or None,
    }


def _pending(memory_path: Path, today: date) -> list[tuple[str, str | None, str | None]]:
    out = []
    for f in bank_index.files(Path(memory_path), "entities"):
        fm = f.frontmatter or {}
        if not papers.is_paper(fm):
            continue
        paper = fm.get("paper") or {}
        if paper.get("metadata_at"):
            continue
        attempted = str(paper.get("metadata_attempted_at") or "")
        if attempted:
            try:
                if (today - date.fromisoformat(attempted[:10])).days < RETRY_DAYS:
                    continue
            except ValueError:
                pass
        out.append((f.stem, paper.get("arxiv_id"), paper.get("doi")))
    return sorted(out)


def has_pending(memory_path: Path) -> bool:
    return bool(_pending(memory_path, date.today()))


def _mark_failed(memory_path: Path, entity_id: str, status: str, today: str) -> None:
    path = papers.page_path(memory_path, entity_id)
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    fm["paper"] = {**(fm.get("paper") or {}), "metadata_status": status, "metadata_attempted_at": today}
    markdown_parser.write(path, fm, parsed.body)


def _apply(memory_path: Path, entity_id: str, meta: dict, *, source: str, today: str, idx: dict) -> str | None:
    """Write one response onto its page; returns a DOI learned from arXiv, if any."""
    from api.services.link_enrichment import _upsert_description

    path = papers.page_path(memory_path, entity_id)
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    paper = dict(fm.get("paper") or {})
    for key in ("title", "authors", "published", "updated", "primary_category", "journal_ref", "venue"):
        if meta.get(key):
            paper[key] = meta[key]
    learned = None
    if meta.get("doi") and not paper.get("doi"):
        paper["doi"] = learned = meta["doi"]
    paper.update(metadata_source=source, metadata_at=today)
    paper.pop("metadata_status", None)
    paper.pop("metadata_attempted_at", None)
    if paper.get("title_from") == "placeholder" and meta.get("title"):
        fm["name"] = meta["title"]
        paper["title_from"] = source
        for entry in idx.values():
            if isinstance(entry, dict) and entry.get("media_entity_id") == entity_id and not entry.get("alias_of"):
                entry["title"] = meta["title"]
    fm["paper"] = paper
    body = parsed.body
    abstract = meta.get("abstract")
    if abstract:
        body = _upsert_description(body, abstract)
        try:
            claims = parse_claims(body, strict=True)
        except MalformedClaimsBlockError:
            claims = None
        if claims is not None:
            cid = papers.claim_id(entity_id, "describes", source)
            span = evidence.verify(None, entity_id, abstract, text=strip_claims_block(body))
            claims = [c for c in claims if c.id != cid] + [Claim(
                id=cid, text=abstract, subject=entity_id, predicate="describes", object=abstract,
                object_kind="literal", observer=f"external:{source}", context="general",
                epistemic="explicit", source_trust="external", confidence=0.9,
                valid_from=paper.get("published") or today, recorded_at=today, source_episodes=[],
                authored_by="cicada", origin=f"papers/{source}", evidence=[span])]
            body = write_claims(body, claims)
    markdown_parser.write(path, fm, body)
    if learned:
        papers.index_aliases(idx, papers.PaperKey(arxiv_id=paper.get("arxiv_id"), doi=learned), entity_id, title=None)
        fact_sources.add_source(memory_path, entity_id, f"https://doi.org/{learned}", kind="url", added_by="cicada")
    return learned


async def resolve(memory_path: Path, *, fetch_fn: FetchFn | None = None, max_arxiv: int | None = None,
                  max_crossref: int | None = None, clock=time.monotonic, sleep=asyncio.sleep) -> dict:
    """Fetch details for every paper page that has none. Stops an API at its
    first refusal or failure (R-LS18); a record the API does not have backs off
    ``RETRY_DAYS``. Returns counts plus the bank paths written."""
    memory_path = Path(memory_path)
    fetch = fetch_fn or default_fetch
    today_d = date.today()
    today = today_d.isoformat()
    pending = _pending(memory_path, today_d)
    arxiv = [(e, a) for e, a, _ in pending if a][:max_arxiv]
    dois = [(e, d) for e, a, d in pending if not a and d][:max_crossref]
    report = {"arxiv_requests": 0, "crossref_requests": 0, "resolved": 0, "failed": 0, "remaining": 0, "error": None}
    paths: set[str] = set()
    idx = media_ingestor.load_url_index(memory_path)
    idx_before = json.dumps(idx, sort_keys=True)
    pacer = _Pacer(ARXIV_SPACING_S, clock=clock, sleep=sleep, api="arxiv")
    for i in range(0, len(arxiv), ARXIV_BATCH):
        chunk = arxiv[i:i + ARXIV_BATCH]
        await pacer.wait()
        resp = await fetch(ARXIV_API, {"id_list": ",".join(a for _, a in chunk), "max_results": str(len(chunk))})
        report["arxiv_requests"] += 1
        if resp.status != 200 or "xml" not in resp.content_type:
            report["error"] = f"arXiv {resp.error or f'HTTP {resp.status}'}"
            break
        found = parse_arxiv_atom(resp.body)
        for entity_id, arxiv_id in chunk:
            if found.get(arxiv_id):
                _apply(memory_path, entity_id, found[arxiv_id], source="arxiv", today=today, idx=idx)
                report["resolved"] += 1
            else:
                _mark_failed(memory_path, entity_id, "not_found", today)
                report["failed"] += 1
            paths.add(f"entities/{entity_id}.md")
    pacer = _Pacer(CROSSREF_SPACING_S, clock=clock, sleep=sleep, api="crossref")
    for entity_id, doi in dois:
        await pacer.wait()
        resp = await fetch(CROSSREF_API + urllib.parse.quote(doi, safe="/"), {})
        report["crossref_requests"] += 1
        if resp.status == 404:
            _mark_failed(memory_path, entity_id, "not_found", today)
            report["failed"] += 1
            paths.add(f"entities/{entity_id}.md")
            continue
        if resp.status != 200 or "json" not in resp.content_type:
            report["error"] = report["error"] or f"Crossref {resp.error or f'HTTP {resp.status}'}"
            break
        meta = parse_crossref(resp.body)
        if meta is None:
            _mark_failed(memory_path, entity_id, "unreadable", today)
            report["failed"] += 1
        else:
            _apply(memory_path, entity_id, meta, source="crossref", today=today, idx=idx)
            report["resolved"] += 1
        paths.add(f"entities/{entity_id}.md")
    if json.dumps(idx, sort_keys=True) != idx_before:
        media_ingestor.save_url_index(memory_path, idx)
        paths.add("sources/url_index.json")
    report["remaining"] = len(_pending(memory_path, today_d))
    report["paths"] = sorted(paths)
    return report


def record(memory_path: Path, report: dict) -> None:
    """The run's outcome under the ``papers`` key of ``sync_state.json`` —
    not a channel row, a place the next reader can see why details are missing."""
    from api.services import sync_state

    if report.get("error"):
        sync_state.record_error(memory_path, "papers", str(report["error"]))
    else:
        sync_state.record_sync(memory_path, "papers", count=int(report.get("resolved") or 0))


async def run_locked(memory_path: Path, **kwargs) -> dict | None:
    """One run per process: ``None`` when another is in flight (never a 409 —
    nothing was asked of the person that this would refuse)."""
    if not _run_lock.acquire(blocking=False):
        return None
    try:
        report = await resolve(memory_path, **kwargs)
        record(memory_path, report)
        await folder_source.commit_paths_for(memory_path, report["paths"], subject="Paper details",
                                             trigger="papers/metadata", author="cicada")
        return report
    finally:
        _run_lock.release()


async def resolve_in_background(memory_path: Path) -> None:
    """The user-triggered run, scheduled by ``POST /sources/folders/{id}/sync?resolve=true``.
    Skipped while a Sleep cycle runs — its tail runs this anyway (R-LS17)."""
    try:
        from api.services import sleep_cycle

        if sleep_cycle.get_sleep_state().status == "running":
            return
        await run_locked(memory_path)
    except Exception as e:  # noqa: BLE001 - a background run never surfaces as a 500
        logger.warning(f"paper details failed: {type(e).__name__}: {e}")
```

  `arxiv[:None]` is the whole list, which is what an uncapped user-triggered run wants.

- [ ] **Step 4: `papers.detail`** — append to `api/services/papers.py`:

```python
# --- The card (read path, engine-free) --------------------------------------

_DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_HEADING_RE = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_WHY_ORDER = {p: i for i, p in enumerate(WHY_PREDICATES)}


def _heading_above(text: str, start: int) -> str | None:
    heading = None
    for m in _HEADING_RE.finditer(text):
        if m.start() > start:
            break
        heading = m.group(1).strip()
    return heading


def _snippet(text: str, start: int, end: int, pad: int = 120) -> tuple[str, int, int]:
    """±``pad`` characters around a span, cut on word boundaries, newlines shown
    as spaces (same length, so the highlight offsets stay exact)."""
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    if lo > 0:
        space = text.find(" ", lo, start)
        lo = space + 1 if space != -1 else lo
    if hi < len(text):
        space = text.rfind(" ", end, hi)
        hi = space if space != -1 else hi
    prefix, suffix = ("…" if lo > 0 else ""), ("…" if hi < len(text) else "")
    first = len(prefix) + (start - lo)
    return prefix + text[lo:hi].replace("\n", " ") + suffix, first, first + (end - start)


def detail(memory_path: Path, entity_id: str) -> dict | None:
    """The paper card's two tiers (G121), resolved at read: every open personal
    claim's span as a snippet with the file, the heading above it and the
    file's date — then the world-tier ``describes`` context. ``None`` for an
    id that is not a paper page (or not a bare id at all)."""
    if not _DOC_ID_RE.match(entity_id or ""):
        return None
    path = page_path(memory_path, entity_id)
    if not path.exists():
        return None
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter or {}
    if not is_paper(fm):
        return None
    paper = fm.get("paper") or {}
    claims = parse_claims(parsed.body)
    docs: dict[str, tuple[str | None, dict]] = {}
    names: dict[str, str] = {}
    why: list[dict] = []
    open_why = sorted((c for c in claims if c.predicate in WHY_PREDICATES and not c.valid_to),
                      key=lambda c: (_WHY_ORDER[c.predicate], c.id))
    for c in open_why:
        for ev in c.evidence:
            if ev.kind == "reasoning" or ev.start < 0:
                continue
            if ev.episode not in docs:
                docs[ev.episode] = evidence.source_document(memory_path, ev.episode)
            text, efm = docs[ev.episode]
            if text is None or ev.end > len(text):
                continue
            snippet, first, last = _snippet(text, ev.start, ev.end)
            target = None
            if c.object_kind == "node":
                names.setdefault(c.object, _name_of(memory_path, c.object) or c.object)
                target = names[c.object]
            why.append({
                "predicate": c.predicate, "text": c.object if c.object_kind == "literal" else None,
                "target": target, "snippet": snippet, "highlight_start": first, "highlight_end": last,
                "file": efm.get("relpath"), "heading": _heading_above(text, ev.start),
                "edited": str(efm.get("source_updated_at") or efm.get("timestamp") or "")[:10] or None,
                "kind": ev.kind, "episode": ev.episode, "start": ev.start, "end": ev.end,
                "stale": bool(ev.hash) and ev.hash != evidence.body_hash(text),
            })
    describes = next((c for c in claims if c.predicate == "describes" and c.source_trust == "external"
                      and not c.valid_to), None)
    return {
        "entity_id": entity_id,
        "title": str(paper.get("title") or fm.get("name") or entity_id),
        "authors": [str(a) for a in paper.get("authors") or []],
        "venue": paper.get("venue") or paper.get("journal_ref"),
        "published": paper.get("published"),
        "arxiv_id": paper.get("arxiv_id"),
        "doi": paper.get("doi"),
        "abs_url": f"https://arxiv.org/abs/{paper['arxiv_id']}" if paper.get("arxiv_id") else None,
        "doi_url": f"https://doi.org/{paper['doi']}" if paper.get("doi") else None,
        "sections": [str(s) for s in paper.get("sections") or []],
        "why": why,
        "agent_only": bool(why) and not any(w["kind"] == "user" for w in why),
        "context": describes.object if describes else None,
        "context_source": paper.get("metadata_source") if describes else None,
        "context_as_of": describes.recorded_at if describes else None,
    }
```

- [ ] **Step 5: schemas.** `EntityMedia` (`schemas.py:398`) gains `kind: Optional[str] = None` after
  `duration_s` (comment: "G133 — `paper` for a paper page (`papers.KIND`); absent for every other
  media page."). Directly after `class EntityResponse` (`:430`) add the three models below — that is
  well above `MediaSourceItem` (`:1550`), so `PaperSummary` is defined before its first use. Then
  `MediaSourceItem` gains `kind: Optional[str] = None` and `paper: Optional[PaperSummary] = None`
  after its `duration_s`:

```python
class PaperSummary(CamelModel):
    """G133 — what a Feed row needs to show a paper's byline and to search by
    author, arXiv id or DOI (R7 §5.2). Read from the page's `paper:` block."""

    authors: list[str] = []
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    published: Optional[str] = None
    venue: Optional[str] = None


class PaperWhyItem(CamelModel):
    """One personal-tier reason, as a span into the person's own file (G118/G121)."""

    predicate: str
    text: Optional[str] = None
    target: Optional[str] = None
    snippet: str
    highlight_start: int
    highlight_end: int
    file: Optional[str] = None
    heading: Optional[str] = None
    edited: Optional[str] = None
    kind: str
    episode: str
    start: int
    end: int
    stale: bool = False


class PaperDetailResponse(CamelModel):
    entity_id: str
    title: str
    authors: list[str] = []
    venue: Optional[str] = None
    published: Optional[str] = None
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    abs_url: Optional[str] = None
    doi_url: Optional[str] = None
    sections: list[str] = []
    why: list[PaperWhyItem] = []
    agent_only: bool = False
    context: Optional[str] = None
    context_source: Optional[str] = None
    context_as_of: Optional[str] = None
```

  (`PaperSummary` must be defined before `MediaSourceItem`; after `EntityResponse` satisfies that.)

- [ ] **Step 6: read paths.**
  - `api/routers/entities.py` `_build_media_block`: add `kind=media.get("kind") or None,` to the
    `EntityMedia(...)` call. Add the route after `GET /entities/{entity_id}/sources`:

```python
@router.get("/entities/{entity_id}/paper", response_model=PaperDetailResponse)
async def get_entity_paper(entity_id: str, settings: Settings = Depends(get_settings)):
    """G133 / G121 — a paper page's two tiers, resolved at read (engine-free):
    "why it's in your memory" as spans into the person's own files, then the
    dated world-tier context. 404 for anything that is not a paper page."""
    from api.services import papers

    detail = await asyncio.to_thread(papers.detail, settings.memory_path, entity_id)
    if detail is None:
        raise HTTPException(404, f"{entity_id!r} is not a paper")
    return PaperDetailResponse(**detail)
```

    and import `PaperDetailResponse` in the schemas import block.
  - `api/routers/sources.py` `list_sources`: at the top of the `for entry in idx.values():` loop add

```python
        # R-LS14: a paper's second canonical URL is an alias of its first; one
        # paper is one Feed row.
        if isinstance(entry, dict) and entry.get("alias_of"):
            continue
```

    add `kind: str | None = None` and `paper: PaperSummary | None = None` beside the other locals;
    inside `if isinstance(media, dict):` add

```python
                    k = media.get("kind")
                    kind = k if isinstance(k, str) and k else None
                    pp = fm.get("paper")
                    if kind == "paper" and isinstance(pp, dict):
                        paper = PaperSummary(
                            authors=[str(a) for a in (pp.get("authors") or [])][:8],
                            arxiv_id=pp.get("arxiv_id"), doi=pp.get("doi"),
                            published=pp.get("published"), venue=pp.get("venue") or pp.get("journal_ref"))
```

    pass `kind=kind, paper=paper` to `MediaSourceItem(...)`, and import `PaperSummary`.
  - `api/services/channel_registry.py` `build_channels`: `saved_count = len(url_index)` becomes
    `saved_count = sum(1 for e in url_index.values() if not (isinstance(e, dict) and e.get("alias_of")))`
    with the comment `# R-LS14: an alias entry is the same paper under its other URL.`
  - `api/services/link_enrichment.py`: in `_candidates` after the `enrichment_attempted` check and
    in `scan_backfill` after the `junk` check add

```python
        # R-LS19: a paper page is described by the arXiv/Crossref APIs
        # (`paper_metadata`), never by a page fetch of arxiv.org.
        from api.services.papers import is_paper

        if is_paper(fm):
            continue
```

    (`scan_recon` is deliberately untouched: recon over a stored abstract is how a paper gets
    related to the graph — R-LS16.)

- [ ] **Step 7: the folder sync can ask for details.** In `api/routers/local_sources.py` import
  `BackgroundTasks` and `paper_metadata`; `sync_folder` gains `background: BackgroundTasks` and
  `resolve: bool = Query(False)`; just before the final `return FolderSyncResponse(**out)` of the
  non-preview path add

```python
    if resolve:
        # R-LS18: the person asked (first add, or "Sync now") — fetch details
        # after the response, one run per process, skipped while Sleep runs.
        background.add_task(paper_metadata.resolve_in_background, memory_path)
```

- [ ] **Step 8: the Sleep tail.** In `api/services/sleep_cycle.py` add after `_backfill_links_safely`:

```python
async def _resolve_papers_safely(memory_path: Path) -> None:
    """G133: finish the paper parses a running cycle deferred (R-LS17), then fetch
    paper details from the arXiv and Crossref APIs (R-LS18).

    Same contract as its neighbours: bounded (``TAIL_ARXIV_IDS`` /
    ``TAIL_CROSSREF_DOIS`` per cycle), never fatal, and in the clean-tree-guarded
    branch — both halves write entity pages, and on a half-written cycle those
    would ride the next ``git add -A``. The deterministic half runs regardless of
    the network gate; the fetch is the "unattended background call"
    ``CICADA_ALLOW_CONNECTOR_FETCH`` exists to gate, and a gated skip is recorded
    (``record_skip``) so it never reads as "nothing to fetch". No LLM, so no
    engine is resolved (TODO.md ruling 4 is untouched)."""
    try:
        from api.services import folder_source, paper_metadata, papers, sync_state
        from api.services.connectors.base import network_allowed

        deferred = await asyncio.to_thread(papers.reconcile_pending, memory_path)
        if deferred["folders"]:
            await folder_source.commit_paths_for(memory_path, deferred["paths"], subject="Folder papers",
                                                 trigger="folder/papers", author="cicada")
        if not paper_metadata.has_pending(memory_path):
            return
        if not network_allowed():
            sync_state.record_skip(memory_path, "papers", "network fetch disabled")
            logger.info("Paper details skipped: CICADA_ALLOW_CONNECTOR_FETCH is off")
            return
        report = await paper_metadata.run_locked(
            memory_path, max_arxiv=paper_metadata.TAIL_ARXIV_IDS, max_crossref=paper_metadata.TAIL_CROSSREF_DOIS)
        if report:
            logger.info(f"Paper details: {report['resolved']} resolved, {report['failed']} not found, "
                        f"{report['remaining']} remaining")
    except Exception as e:
        logger.warning(f"Paper details failed: {type(e).__name__}: {e}")
```

  In `_run_engine_independent_tail`, inside the guarded branch after
  `await _backfill_links_safely(...)`, add `await _resolve_papers_safely(memory_path)`; add
  "paper details" to the `else:` branch's warning text; and add one paragraph to the function's
  docstring: "G133: ``_resolve_papers_safely`` shares this branch — it writes paper pages (scoped
  commits), and the fetch half is gated by ``CICADA_ALLOW_CONNECTOR_FETCH``."

- [ ] **Step 9: Verify** — `test_paper_metadata.py`, `test_papers.py`, `test_folder_source.py`,
  then `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_link_enrichment.py api/tests/test_source_channels.py api/tests/test_sleep_feed_poll.py api/tests/test_sleep_engine_state.py api/tests/test_sleep_link_backfill.py api/tests/test_state_wiring.py -q -p no:cacheprovider`
  (the enrichment scans and every existing test that drives `_run_engine_independent_tail`), then
  the full suite.
- [ ] **Step 10: Commit** — `feat(G133): paper details from the arXiv and Crossref APIs as a dated cache; the paper card's endpoint; one Feed row per paper (R-F3)`.

---

### Task 5: Wispr Flow, backend half (R-N1 … R-N3)

**Files:**
- Create: `api/services/wispr_flow.py`
- Modify: `api/routers/local_sources.py` (three routes), `api/models/schemas.py` (`from typing import
  Any, Literal, Optional`; four models)
- Modify: `api/services/channel_registry.py` (`wispr-flow` row), `api/services/source_overview.py`
  (`KIND_ORDER`, `CATALOG`), `api/services/sync_service.py` (`sources` component)
- Test: `api/tests/test_wispr_flow.py` (new)

**Interfaces:**
- Produces `wispr_flow.SETTINGS_FILENAME`, `ORIGIN`, `CHANNEL_ID`, `MEETING_COLUMNS`, `NOTE_COLUMNS`,
  `TODO_COLUMNS`, `HISTORY_COLUMNS`, `UTTERANCE_KEYS`, `FORBIDDEN_COLUMNS`, `DICTATION_APP_DENYLIST`,
  `MAX_MEETINGS`, `MAX_HISTORY`, `load_settings`, `save_settings`, `speaker_marker`, `meeting_draft`,
  `note_draft`, `dictation_drafts`, `write_todo_claims`, `ingest`.
- Produces `GET/PUT /capture/local-source/wispr-flow/settings`, `POST /capture/local-source/wispr-flow`.
- Consumes Task 1's stager/scrub/evidence, `agentic_write.write_claim`, `owner_identity.resolve_observer`,
  `folder_source.commit_paths_for`, `channel_registry._local_channel`.

- [ ] **Step 1: Failing tests** — `api/tests/test_wispr_flow.py`:

```python
"""G134 — Wispr Flow, backend half (R-N1 … R-N3; R-LS21 … R-LS24)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_registry, evidence, markdown_parser, source_overview, sync_service
from api.services import wispr_flow as wf
from api.services.claims import parse_claims

CANARIES = {c: f"CANARY-{c}" for c in wf.FORBIDDEN_COLUMNS}


def _meeting(mid="m-1", **row):
    base = {"id": mid, "title": "alpha-project sync", "createdAt": "2026-09-01T10:00:00Z",
            "modifiedAt": "2026-09-01T11:00:00Z", "endedAt": "2026-09-01T10:45:00Z", "isDeleted": 0,
            "finalized": 1, "isTourDemo": 0, "transcriptDeletedAt": None,
            "participantNames": json.dumps(["Ada Example", "bob-example", "carol@example.com"]),
            "speakerMap": json.dumps({"1": "bob-example", "2": "Ada Example"}),
            "notes": "<p>Decided to ship the draft.</p>", "summary": "We agreed to ship on Friday.", **CANARIES}
    base.update(row)
    return {"row": base, "utterances": [
        {"timestamp": "2026-09-01T10:01:00Z", "text": "I will send the deck",
         "speaker": {"id": 1, "name": None, "source": "system"}, "audioOffset": "CANARY-nd"},
        {"timestamp": "2026-09-01T10:02:00Z", "text": "Thanks, the code is 482913",
         "speaker": {"id": 2, "name": "Ada Example"}},
    ]}


def _payload(**overrides):
    base = {"meetings": [_meeting()],
            "notes": [{"id": "n-1", "title": "Idea", "content": "Try a folder source.", "createdAt": 1756717200000,
                       "modifiedAt": 1756717300000, "isDeleted": 0, **CANARIES}],
            "todos": [{"meetingId": "m-1", "title": "Send the deck", "status": "open", "isDeleted": 0},
                      {"meetingId": "m-1", "title": "Old task", "status": "done", "isDeleted": 0}],
            "history": None, "deleted_meeting_ids": [], "deleted_note_ids": []}
    base.update(overrides)
    return base


@pytest.fixture
def bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    return memory


def _by_source(bank):
    bank_index.invalidate()
    out = {}
    for p in (bank / "episodes").glob("ep_*.md"):
        parsed = markdown_parser.parse(p)
        out[parsed.frontmatter["source_id"]] = parsed
    return out


def _settings(**kw):
    return {"enabled": True, "include_dictation": False, "owner_speaker_names": [], **kw}


def test_the_whitelists_never_name_a_forbidden_column():
    allowed = set(wf.MEETING_COLUMNS + wf.NOTE_COLUMNS + wf.TODO_COLUMNS + wf.HISTORY_COLUMNS + wf.UTTERANCE_KEYS)
    assert not allowed & set(wf.FORBIDDEN_COLUMNS)


def test_a_meeting_keeps_its_speakers_and_only_its_whitelisted_words(bank):
    wf.ingest(bank, _payload(), _settings(owner_speaker_names=["Ada Example"]))
    meeting = _by_source(bank)["wispr:meeting:m-1"]
    body, fm = meeting.body, meeting.frontmatter
    assert body.startswith("assistant: Summary (written by Wispr Flow)\nWe agreed to ship on Friday.")
    assert "speaker:bob-example: I will send the deck" in body       # R-N2: a colleague is never `user`
    assert "user: Thanks, the code is [redacted]" in body            # R-LS22 by name; R-N3 scrub
    assert "- Send the deck" in body and "Old task" not in body
    assert (fm["origin"], fm["consent"], fm["wispr_kind"]) == ("wispr-flow", "unknown", "meeting")
    assert fm["participants"] == ["Ada Example", "bob-example"]       # the email is dropped
    assert [row[2] for row in fm["turn_index"]] == ["assistant", "assistant", "assistant", "speaker:bob-example", "user"]
    assert evidence.speaker_kind(body, body.index("I will send")) == "speaker"
    assert evidence.speaker_kind(body, body.index("Thanks")) == "user"
    everything = "".join(p.read_text() for p in (bank / "episodes").glob("*.md"))
    assert "CANARY" not in everything and "carol@example.com" not in everything


def test_without_a_listed_name_nobody_in_a_meeting_is_the_owner(bank):
    wf.ingest(bank, _payload(), _settings())
    body = _by_source(bank)["wispr:meeting:m-1"].body
    assert "speaker:ada-example: Thanks" in body and "\nuser:" not in body


@pytest.mark.parametrize("row", [{"isDeleted": 1}, {"isTourDemo": 1}, {"finalized": 0}])
def test_deleted_demo_and_unfinished_meetings_are_never_memory(bank, row):
    wf.ingest(bank, _payload(meetings=[_meeting(**row)]), _settings())
    assert "wispr:meeting:m-1" not in _by_source(bank)


def test_an_edited_meeting_updates_in_place_and_a_deleted_one_is_stamped(bank):
    wf.ingest(bank, _payload(), _settings())
    first = _by_source(bank)["wispr:meeting:m-1"].frontmatter["id"]
    report = wf.ingest(bank, _payload(meetings=[_meeting(summary="We moved it to Monday.",
                                                         modifiedAt="2026-09-02T09:00:00Z")]), _settings())
    assert report["updated"] == 1
    again = _by_source(bank)["wispr:meeting:m-1"]
    assert again.frontmatter["id"] == first and again.frontmatter["processed"] is False
    wf.ingest(bank, _payload(meetings=[], notes=[], deleted_meeting_ids=["m-1"]), _settings())
    assert _by_source(bank)["wispr:meeting:m-1"].frontmatter["source_deleted_at"]


def test_a_scratchpad_note_is_the_owners_words_with_its_own_date(bank):
    wf.ingest(bank, _payload(meetings=[]), _settings())
    note = _by_source(bank)["wispr:note:n-1"]
    assert note.body == "Try a folder source." and note.frontmatter["timestamp"] == "2025-09-01T09:00:00+00:00"
    assert evidence.speaker_kind(note.body, 0) == "user"


def test_dictation_is_refused_unless_opted_in_then_one_episode_per_day(bank):
    rows = [{"timestamp": "2026-09-01T09:00:00Z", "formattedText": "Hello", "editedText": "Hello there.",
             "app": "com.apple.mail", "numWords": 2, **CANARIES},
            {"timestamp": "2026-09-01T09:05:00Z", "formattedText": "My vault code is 123456",
             "app": "com.1password.1password", "numWords": 5},
            {"timestamp": "2026-09-01T09:10:00Z", "formattedText": "Second thought.", "app": "com.apple.Notes",
             "numWords": 2},
            {"timestamp": "2026-09-02T08:00:00Z", "formattedText": "Next day", "app": "com.apple.Notes", "numWords": 2}]
    assert wf.ingest(bank, _payload(meetings=[], notes=[], history=rows), _settings())["dictation_refused"] == 4
    assert not any(k.startswith("wispr:dictation:") for k in _by_source(bank))
    wf.ingest(bank, _payload(meetings=[], notes=[], history=rows[:1]), _settings(include_dictation=True))
    wf.ingest(bank, _payload(meetings=[], notes=[], history=rows[1:]), _settings(include_dictation=True))
    days = _by_source(bank)
    first = days["wispr:dictation:2026-09-01"]
    # R-LS23: the second post merged into the day the first post created (one episode, rebuilt
    # from its own turn_index); the password-manager line was dropped.
    assert first.body == "user: Hello there.\nuser: Second thought."
    assert first.frontmatter["dictation_apps"] == ["com.apple.Notes", "com.apple.mail"]
    assert len([k for k in days if k.startswith("wispr:dictation:")]) == 2
    assert days["wispr:dictation:2026-09-02"].body == "user: Next day"
    assert "CANARY" not in "".join(p.read_text() for p in (bank / "episodes").glob("*.md"))


def test_open_todos_become_committed_to_claims_on_the_owner_page_only(bank):
    assert wf.ingest(bank, _payload(), _settings())["todos_skipped_no_owner"] == 1
    markdown_parser.write(bank / "entities" / "owner.md", {"name": "Owner", "type": "person", "owner": True},
                          "## Summary\nx")
    wf.ingest(bank, _payload(meetings=[_meeting(modifiedAt="2026-09-03T09:00:00Z", summary="Changed.")]), _settings())
    (claim,) = [c for c in parse_claims(markdown_parser.parse(bank / "entities" / "owner.md").body)
                if c.predicate == "committed-to"]
    assert (claim.object, claim.observer, claim.source_trust, claim.origin) == (
        "Send the deck", "agent", "agent_extracted", "wispr-flow")
    assert claim.evidence[0].kind == "assistant"


def test_the_channel_row_and_the_voice_card(bank):
    wf.save_settings(bank, enabled=True, include_dictation=False, owner_speaker_names=[])
    wf.ingest(bank, _payload(), _settings())
    from api.services import sync_state
    sync_state.record_sync(bank, wf.CHANNEL_ID, count=2)
    rows = channel_registry.build_channels(bank, telegram_enabled=False)
    row = next(r for r in rows if r["id"] == "wispr-flow")
    assert row["actions"] == ["sync", "manage"] and row["count_noun"] == "capture"
    bank_index.invalidate()
    card = next(r for r in source_overview.build_overview(bank, channels=rows) if r["id"] == "wispr-flow")
    assert (card["kind"], card["mark"], card["episodes"]) == ("voice", "wispr-flow", 2)


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_routes(client, bank):
    assert client.get("/capture/local-source/wispr-flow/settings").json() == {
        "enabled": False, "includeDictation": False, "ownerSpeakerNames": []}
    body = {"meetings": [_meeting()], "notes": [], "todos": [], "deletedMeetingIds": [], "deletedNoteIds": []}
    assert client.post("/capture/local-source/wispr-flow", json=body).status_code == 409
    before = sync_service.components(bank)["sources"]
    saved = client.put("/capture/local-source/wispr-flow/settings",
                       json={"enabled": True, "includeDictation": False, "ownerSpeakerNames": ["Ada Example", "x@example.com"]}).json()
    assert saved["ownerSpeakerNames"] == ["Ada Example"]
    assert sync_service.components(bank)["sources"] != before  # R-LS29
    r = client.post("/capture/local-source/wispr-flow", json=body).json()
    assert r["created"] == 1 and r["meetingsSeen"] == 1
    assert any(ch["id"] == "wispr-flow" for ch in client.get("/sources/channels").json()["channels"])
    # The wire is camelCase; `ingest` reads snake_case keys — a deletion must reach the stager
    # (a bare `req.model_dump()` in the route drops it silently: CamelModel dumps by alias).
    gone = dict(body, meetings=[], deletedMeetingIds=["m-1"])
    assert client.post("/capture/local-source/wispr-flow", json=gone).json()["tombstoned"] == 1
```

Run → fails.

- [ ] **Step 2: `api/services/wispr_flow.py`.**

```python
"""Wispr Flow meetings, notes and (opt-in) dictation (G134 · R-N1 · R-N2 · R-N3).

Wispr Flow keeps everything in a local SQLite database under
``~/Library/Application Support/Wispr Flow`` plus one ``refined.ndjson`` of
diarized utterances per meeting. The APP opens both read-only and posts a
whitelisted projection (R-N1, R-LS21); this module is the one parser — pure,
fixture-tested — and it re-applies the same whitelist and the same filters
(deleted, demo and unfinished meetings never become memory) to whatever
arrives, so a newer or buggier app cannot widen what is stored.

Speakers (R-N2, R-LS22): an utterance is ``speaker:<label>: text`` — the
speaker's name slug, else their numeric id — and ``user:`` only when the name is
one the person listed as theirs (``owner_speaker_names``). Wispr Flow's own
summary, notes and to-dos are its model's words and sit under an ``assistant:``
line. Every meeting is ``consent: unknown`` until the person says otherwise
(G95's rail). Emails never enter a name or a participant list.

Dictation (R-LS23) is off by default — dictated text goes into every app,
passwords included. When on, only ``timestamp``, ``formattedText``/``editedText``,
``app`` and ``numWords`` are read, one episode per UTC day, merged across posts
through the day's own ``turn_index``; password-manager apps are dropped. Every
body is scrubbed by the stager (R-N3).
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

from api.services import episode_ids, episode_scrub, episode_staging, markdown_parser
from api.services.episode_staging import EpisodeDraft, Turn
from api.services.id_utils import sanitize_id

SETTINGS_FILENAME = "wispr_flow.json"
ORIGIN = "wispr-flow"
CHANNEL_ID = "wispr-flow"
MEETING_COLUMNS = ("id", "title", "createdAt", "modifiedAt", "endedAt", "isDeleted", "finalized",
                   "isTourDemo", "transcriptDeletedAt", "participantNames", "speakerMap", "notes", "summary")
NOTE_COLUMNS = ("id", "title", "content", "createdAt", "modifiedAt", "isDeleted")
TODO_COLUMNS = ("meetingId", "title", "status", "isDeleted")
HISTORY_COLUMNS = ("timestamp", "formattedText", "editedText", "app", "numWords")
UTTERANCE_KEYS = ("timestamp", "text", "speaker")
#: Never read on either side, whatever a future Wispr Flow schema adds (R-LS21).
FORBIDDEN_COLUMNS = ("audio", "builtInAudio", "screenshot", "axText", "axHTML", "textboxContents",
                     "pastedText", "url", "asrText")
DONE_STATUSES = frozenset({"done", "completed", "complete", "cancelled", "canceled", "archived"})
DICTATION_APP_DENYLIST = frozenset({
    "com.1password.1password", "com.agilebits.onepassword7", "com.agilebits.onepassword-osx",
    "com.apple.keychainaccess", "com.apple.Passwords", "com.bitwarden.desktop",
    "com.lastpass.LastPass", "com.dashlane.dashlanephonefinal", "org.keepassxc.keepassxc",
})
MAX_MEETINGS = 200
MAX_HISTORY = 5000
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


# --- Settings ---------------------------------------------------------------


def settings_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / SETTINGS_FILENAME


def _clean_names(value) -> list[str]:
    out: list[str] = []
    for raw in value if isinstance(value, list) else []:
        name = " ".join(str(raw or "").split())[:80]
        if name and not _EMAIL_RE.search(name) and name not in out:
            out.append(name)
    return out[:10]


def load_settings(memory_path: Path) -> dict:
    try:
        data = json.loads(settings_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {"enabled": bool(data.get("enabled", False)),
            "include_dictation": bool(data.get("include_dictation", False)),
            "owner_speaker_names": _clean_names(data.get("owner_speaker_names"))}


def save_settings(memory_path: Path, *, enabled: bool, include_dictation: bool, owner_speaker_names) -> dict:
    data = {"enabled": bool(enabled), "include_dictation": bool(include_dictation),
            "owner_speaker_names": _clean_names(owner_speaker_names)}
    path = settings_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


# --- Field helpers ----------------------------------------------------------


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _ts(value) -> str | None:
    """Any timestamp shape Wispr Flow might store — ISO text, epoch seconds or
    epoch milliseconds — as aware UTC (G114 R2), or ``None``."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        try:
            return episode_ids.to_utc_iso(float(seconds))
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return _ts(float(text))
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return episode_ids.to_utc_iso(dt)


def _turn_ts(value) -> str | None:
    """An utterance time: aware UTC when it is a date, else the raw offset
    ("00:23:41") — informational only, it lives in ``turn_index``."""
    parsed = _ts(value)
    if parsed or value in (None, ""):
        return parsed
    return str(value).strip()[:32] or None


def _json_or(value, default):
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str) and value.strip()[:1] in ("[", "{"):
        try:
            return json.loads(value)
        except ValueError:
            return default
    return default


def _one_name(item) -> str | None:
    raw = item.get("name") if isinstance(item, dict) else item
    name = " ".join(str(raw or "").split())[:80]
    return name if name and not _EMAIL_RE.search(name) else None


def _names(value) -> list[str]:
    raw = _json_or(value, None)
    if raw is None:
        raw = str(value or "").split(",")
    out: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        name = _one_name(item)
        if name and name not in out:
            out.append(name)
    return out


def _speaker_map(value) -> dict[str, str]:
    raw = _json_or(value, {})
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, item in raw.items():
            name = _one_name(item)
            if name:
                out[str(key)] = name
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("id") is not None:
                name = _one_name(item)
                if name:
                    out[str(item["id"])] = name
    return out


def _plain(value) -> str:
    text = str(value or "")
    if "<" in text and ">" in text:
        text = html.unescape(_HTML_TAG_RE.sub("\n", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def speaker_marker(speaker, speaker_map: dict[str, str], owner_names: set[str]) -> str:
    """``user`` for a name the person listed as theirs, else ``speaker:<label>``
    (R-N2 / R-LS22). The label is a slug, never containing ``:``, so
    ``evidence._SPEAKER_RE`` reads it back."""
    speaker = speaker if isinstance(speaker, dict) else {}
    raw_id = speaker.get("id")
    sid = re.sub(r"[^A-Za-z0-9_-]", "", "" if raw_id is None else str(raw_id))[:32]
    name = _one_name(speaker) or speaker_map.get(sid) or ""
    if name and name.casefold() in owner_names:
        return "user"
    label = sanitize_id(name)[:48].strip("-") if name else ""
    if label and label != "unnamed":
        return f"speaker:{label}"
    return f"speaker:{sid or 'unknown'}"


# --- Drafts -----------------------------------------------------------------


def meeting_draft(item: dict, todos: list[dict], owner_names: set[str]) -> tuple[EpisodeDraft | None, list[str]]:
    """One finalized meeting as one episode, and its open to-do titles."""
    row = {k: (item.get("row") or {}).get(k) for k in MEETING_COLUMNS}
    meeting_id = str(row["id"] or "").strip()
    if (not meeting_id or _truthy(row["isDeleted"]) or _truthy(row["isTourDemo"])
            or not _truthy(row["finalized"])):
        return None, []
    speaker_map = _speaker_map(row["speakerMap"])
    turns: list[Turn] = []
    summary = _plain(row["summary"])
    if summary:
        turns.append(Turn(f"Summary (written by Wispr Flow)\n{summary}", "assistant"))
    notes = _plain(row["notes"])
    if notes:
        turns.append(Turn(f"Notes (Wispr Flow)\n{notes}", "assistant"))
    open_todos: list[str] = []
    for todo in todos:
        todo = {k: todo.get(k) for k in TODO_COLUMNS}
        title = " ".join(str(todo["title"] or "").split())
        if (title and not _truthy(todo["isDeleted"]) and title not in open_todos
                and str(todo["status"] or "").strip().lower() not in DONE_STATUSES):
            open_todos.append(title)
    if open_todos:
        turns.append(Turn("To-dos (from Wispr Flow)\n" + "\n".join(f"- {t}" for t in open_todos), "assistant"))
    if not row["transcriptDeletedAt"]:
        for utterance in item.get("utterances") or []:
            if not isinstance(utterance, dict):
                continue
            u = {k: utterance.get(k) for k in UTTERANCE_KEYS}
            text = " ".join(str(u["text"] or "").split())
            if text:
                turns.append(Turn(text, speaker_marker(u["speaker"], speaker_map, owner_names), _turn_ts(u["timestamp"])))
    if not turns:
        return None, []
    created = _ts(row["createdAt"])
    return EpisodeDraft(
        title=" ".join(str(row["title"] or "").split()) or "Meeting",
        source_id=f"wispr:meeting:{meeting_id}",
        source_updated_at=_ts(row["modifiedAt"]) or created, timestamp=created,
        original_date=created[:10] if created else None, source=ORIGIN, origin=ORIGIN, turns=turns,
        extra={"wispr_kind": "meeting",
               "participants": _names(row["participantNames"]) or sorted(set(speaker_map.values())),
               "consent": "unknown", "meeting_ended_at": _ts(row["endedAt"])},
        writer="wispr-flow",
    ), open_todos


def note_draft(raw: dict) -> EpisodeDraft | None:
    row = {k: raw.get(k) for k in NOTE_COLUMNS}
    note_id = str(row["id"] or "").strip()
    body = _plain(row["content"])
    if not note_id or _truthy(row["isDeleted"]) or not body:
        return None
    created = _ts(row["createdAt"])
    return EpisodeDraft(
        title=" ".join(str(row["title"] or "").split()) or "Wispr Flow note",
        source_id=f"wispr:note:{note_id}", source_updated_at=_ts(row["modifiedAt"]) or created,
        timestamp=created, original_date=created[:10] if created else None, source=ORIGIN, origin=ORIGIN,
        body=body, extra={"wispr_kind": "note"}, writer="wispr-flow",
    )


def _stored_dictation(entry) -> list[tuple[str, str]]:
    """``(ts, text)`` rows of a stored dictation day, rebuilt from its own
    ``turn_index`` (R-LS23) — the app posts only what is new, so a day is merged
    here rather than replaced."""
    if entry is None:
        return []
    body = markdown_parser.parse(entry.path).body
    rows = [r for r in (entry.fm.get("turn_index") or []) if isinstance(r, (list, tuple)) and len(r) == 3]
    out: list[tuple[str, str]] = []
    for i, (offset, ts, speaker) in enumerate(rows):
        end = int(rows[i + 1][0]) - 1 if i + 1 < len(rows) else len(body)
        line = body[int(offset):end]
        prefix = f"{speaker}: "
        out.append((str(ts or ""), line[len(prefix):] if line.startswith(prefix) else line))
    return out


def dictation_drafts(rows: list[dict], index: dict) -> list[EpisodeDraft]:
    by_day: dict[str, dict] = {}
    for raw in rows:
        r = {k: (raw or {}).get(k) for k in HISTORY_COLUMNS}
        app = str(r["app"] or "").strip()
        if app in DICTATION_APP_DENYLIST:
            continue
        text = " ".join(str(r["editedText"] or r["formattedText"] or "").split())
        ts = _ts(r["timestamp"])
        if not text or not ts:
            continue
        day = by_day.setdefault(ts[:10], {"rows": {}, "apps": set()})
        day["rows"][(ts, episode_scrub.scrub(text)[0])] = True
        if app:
            day["apps"].add(app)
    drafts: list[EpisodeDraft] = []
    for day, data in sorted(by_day.items()):
        sid = f"wispr:dictation:{day}"
        entry = index.get(sid)
        merged = dict.fromkeys(_stored_dictation(entry))
        merged.update(data["rows"])
        ordered = sorted(merged)
        apps = sorted(set((entry.fm.get("dictation_apps") or []) if entry else []) | data["apps"])
        drafts.append(EpisodeDraft(
            title=f"Dictation · {day}", source_id=sid, source_updated_at=ordered[-1][0],
            timestamp=ordered[0][0], original_date=day, source=ORIGIN, origin=ORIGIN,
            turns=[Turn(text, "user", ts) for ts, text in ordered],
            extra={"wispr_kind": "dictation", "dictation_apps": apps}, writer="wispr-flow",
        ))
    return drafts


# --- To-dos (R-LS24) --------------------------------------------------------


def write_todo_claims(memory_path: Path, staged, meeting_todos: dict[str, list[str]]) -> dict:
    """Each open to-do of a new or changed meeting as a ``committed-to`` claim on
    the owner's page: ``observer: agent`` at 0.5 (Wispr Flow's model extracted
    it, and a to-do may be someone else's), with a span on the to-do line. No
    owner page, no claims — never a guessed subject."""
    from api.config import get_settings
    from api.services import agentic_write, owner_identity

    out = {"written": 0, "skipped_no_owner": 0, "paths": []}
    touched = {sid: ep for sid, ep in staged.touched.items() if sid in meeting_todos}
    if not touched:
        return out
    owner = owner_identity.resolve_observer(memory_path, get_settings())
    if not (Path(memory_path) / "entities" / f"{owner}.md").exists():
        out["skipped_no_owner"] = sum(len(meeting_todos[s]) for s in touched)
        return out
    for sid, ep_id in touched.items():
        for title in meeting_todos[sid]:
            result = agentic_write.write_claim(
                memory_path, owner, "committed-to", title, observer="agent", object_kind="literal",
                confidence=0.5, source_episode=ep_id, origin=ORIGIN,
                evidence=[{"episode": ep_id, "quote": f"- {title}"}])
            if result.get("action") not in {"error", "ambiguous_subject", "corrupt_claims_block"}:
                out["written"] += 1
    if out["written"]:
        out["paths"].append(f"entities/{owner}.md")
    return out


# --- Ingest -----------------------------------------------------------------


def ingest(memory_path: Path, payload: dict, settings: dict) -> dict:
    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    owner_names = {n.casefold() for n in settings.get("owner_speaker_names") or []}
    todos: dict[str, list[dict]] = {}
    for todo in payload.get("todos") or []:
        if isinstance(todo, dict):
            todos.setdefault(str(todo.get("meetingId") or ""), []).append(todo)
    counts = {"meetings_seen": 0, "notes_seen": 0, "dictation_days": 0, "dictation_refused": 0}
    drafts: list[EpisodeDraft] = []
    meeting_todos: dict[str, list[str]] = {}
    for item in (payload.get("meetings") or [])[:MAX_MEETINGS]:
        if not isinstance(item, dict):
            continue
        meeting_id = str((item.get("row") or {}).get("id") or "")
        draft, open_todos = meeting_draft(item, todos.get(meeting_id, []), owner_names)
        if draft is None:
            continue
        drafts.append(draft)
        counts["meetings_seen"] += 1
        if open_todos:
            meeting_todos[draft.source_id] = open_todos
    for raw in payload.get("notes") or []:
        draft = note_draft(raw) if isinstance(raw, dict) else None
        if draft is not None:
            drafts.append(draft)
            counts["notes_seen"] += 1
    history = payload.get("history") or []
    if history:
        if settings.get("include_dictation"):
            index, _ = episode_staging.scan(episodes_dir)
            days = dictation_drafts(history[:MAX_HISTORY], index)
            drafts += days
            counts["dictation_days"] = len(days)
        else:
            counts["dictation_refused"] = len(history)  # R-LS23: opted out, never stored
    deleted = ([f"wispr:meeting:{i}" for i in payload.get("deleted_meeting_ids") or [] if str(i).strip()]
               + [f"wispr:note:{i}" for i in payload.get("deleted_note_ids") or [] if str(i).strip()])
    staged = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=deleted, bank=memory_path.name)
    claims = write_todo_claims(memory_path, staged, meeting_todos)
    index, _ = episode_staging.scan(episodes_dir)
    live = sum(1 for sid, e in index.items()
               if sid.startswith(("wispr:meeting:", "wispr:note:")) and not e.fm.get("source_deleted_at"))
    return {**counts, "created": staged.created, "updated": staged.updated, "skipped": staged.skipped,
            "tombstoned": staged.tombstoned, "todo_claims": claims["written"],
            "todos_skipped_no_owner": claims["skipped_no_owner"], "live": live,
            "paths": staged.paths + claims["paths"]}
```

- [ ] **Step 3: schemas** (after the folder models; add `Any` to `from typing import …`):

```python
class WisprFlowSettings(CamelModel):
    """G134 — per bank. Dictation is opt-in (R-LS23); `owner_speaker_names` is the
    only way a meeting speaker is ever the owner (R-LS22)."""

    enabled: bool = False
    include_dictation: bool = False
    owner_speaker_names: list[str] = []


class WisprMeetingIn(CamelModel):
    row: dict[str, Any] = {}
    utterances: list[dict[str, Any]] = []


class WisprFlowPayload(CamelModel):
    """The app's whitelisted projection (R-LS21). The backend re-reads only the
    whitelisted keys from each dict, whatever else arrives."""

    meetings: list[WisprMeetingIn] = []
    notes: list[dict[str, Any]] = []
    todos: list[dict[str, Any]] = []
    history: Optional[list[dict[str, Any]]] = None
    deleted_meeting_ids: list[str] = []
    deleted_note_ids: list[str] = []


class WisprFlowCaptureResponse(CamelModel):
    meetings_seen: int = 0
    notes_seen: int = 0
    dictation_days: int = 0
    dictation_refused: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    tombstoned: int = 0
    todo_claims: int = 0
    todos_skipped_no_owner: int = 0
```

- [ ] **Step 4: routes** — append to `api/routers/local_sources.py` (import `wispr_flow` and the four
  models):

```python
@router.get("/capture/local-source/wispr-flow/settings", response_model=WisprFlowSettings)
async def get_wispr_settings(settings: Settings = Depends(get_settings)):
    return WisprFlowSettings(**wispr_flow.load_settings(settings.memory_path))


@router.put("/capture/local-source/wispr-flow/settings", response_model=WisprFlowSettings)
async def put_wispr_settings(req: WisprFlowSettings, settings: Settings = Depends(get_settings)):
    saved = wispr_flow.save_settings(settings.memory_path, enabled=req.enabled,
                                     include_dictation=req.include_dictation,
                                     owner_speaker_names=req.owner_speaker_names)
    await folder_source.commit_paths_for(
        settings.memory_path, [f"sources/{wispr_flow.SETTINGS_FILENAME}"],
        subject="Wispr Flow settings", trigger="user/companion_app")
    return WisprFlowSettings(**saved)


@router.post("/capture/local-source/wispr-flow", response_model=WisprFlowCaptureResponse)
async def capture_wispr_flow(req: WisprFlowPayload, settings: Settings = Depends(get_settings)):
    """Stage what the app read from Wispr Flow (R-N1). 409 while the source is off
    for this memory — the app only posts when it is on, so a 409 means the two
    disagree, and staging would ignore the person's choice."""
    memory_path = settings.memory_path
    current = wispr_flow.load_settings(memory_path)
    if not current["enabled"]:
        raise HTTPException(409, "Wispr Flow is turned off for this memory — turn it on in Settings → Integrations.")
    if len(req.meetings) > wispr_flow.MAX_MEETINGS or len(req.history or []) > wispr_flow.MAX_HISTORY:
        raise HTTPException(413, "too many rows in one request — send them in smaller batches")
    # `by_alias=False` is load-bearing: `CamelModel` sets `serialize_by_alias=True`, so a bare
    # `model_dump()` returns `deletedMeetingIds`/`deletedNoteIds` and `ingest` (which reads the
    # snake_case keys) would silently never tombstone anything. `test_the_routes` pins it.
    report = await run_in_threadpool(wispr_flow.ingest, memory_path, req.model_dump(by_alias=False), current)
    sync_state.record_sync(memory_path, wispr_flow.CHANNEL_ID, count=report.pop("live"))
    await folder_source.commit_paths_for(memory_path, report.pop("paths"), subject="Wispr Flow sync",
                                         trigger="wispr-flow/sync")
    return WisprFlowCaptureResponse(**report)
```

- [ ] **Step 5: rows, card, ETag input.**
  - `channel_registry.py`: import `wispr_flow`; before `return rows` in `build_channels`:

```python
    # G134: shown once the person turned it on (or it has ever synced), so an
    # unused note-taker is not a disconnected row on every install (R-LS25).
    if wispr_flow.load_settings(memory_path)["enabled"] or state.get(wispr_flow.CHANNEL_ID):
        rows.append(_local_channel(wispr_flow.CHANNEL_ID, "Wispr Flow", state, "capture"))
```

  - `source_overview.py`: `KIND_ORDER = ("harness", "browser", "social", "feed", "messaging", "voice", "import")`
    (comment: `# G134: meetings and dictation are their own section, VOICE & MEETINGS (R-LS25).`) and a
    `CATALOG` row after `telegram`:
    `SourceSpec("wispr-flow", "Wispr Flow", "voice", "wispr-flow", ("wispr-flow",), "wispr-flow"),`
  - `sync_service.py`: `from api.services.wispr_flow import SETTINGS_FILENAME as WISPR_SETTINGS_FILENAME`
    and one more term in `sources`: `f":{file_mtime(mp / 'sources' / WISPR_SETTINGS_FILENAME):.6f}"` —
    turning the source on adds a channel row without touching any other component (R-LS29).

- [ ] **Step 6: Verify** — `test_wispr_flow.py`, `test_folder_source.py`, `test_source_channels.py`,
  `test_source_overview.py`, then the full suite.
- [ ] **Step 7: Commit** — `feat(G134): Wispr Flow meetings and notes with their speakers; dictation only when asked (R-N1, R-N2, R-N3)`.

---

### Task 6: The readers — the app watches the folder and reads Wispr Flow (R-F1, R-N1)

App-side only. After this task the app watches every registered folder of the active memory and,
when Wispr Flow is turned on, reads its store — but nothing in the UI registers a folder or turns
Wispr Flow on until Task 7, so the branch ships with the readers idle.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/LocalSources.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Services/LocalSources/FolderGlob.swift`, `FolderScanner.swift`,
  `FSEventsWatch.swift`, `WisprFlowReader.swift`, `LocalSourceWatcher.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/BrowserWatch.swift:236-237`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/BrowserFiles.swift:11-43,78-93`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` (endpoints before `// MARK: - RSS feed
  subscriptions (G9)`, `postData` beside `post`, the conformance at the end of the file)
- Modify: `app/CicadaApp/Sources/CicadaApp/CicadaApp.swift:47,78,103,111,138,227`
- Test: `app/CicadaApp/Tests/CicadaAppTests/FolderGlobTests.swift`, `FolderScannerTests.swift`,
  `WisprFlowReaderTests.swift`, `LocalSourceWatcherTests.swift` (new)

**Interfaces:**
- Produces `FolderAuthorshipRule`, `FolderRegistration` (`channelId`, `agentGlobs`), `FolderSyncResult`
  (`add(_:)`), `FolderSyncError`, `WisprFlowSettings`, `WisprFlowSyncResult`; `FolderGlob`,
  `CompiledFolderRules`; `FolderFileStat`, `FolderFileSignature`, `FolderUpload`, `FolderReadResult`,
  `FolderScanner`, `FolderManifestStore`, `FolderBookmarks`; `FSEventsWatch`; `WisprFlowColumns`,
  `SQLiteCursor`, `WisprFlowCursor`, `SQLiteReadOnly`, `WisprFlowPass`, `WisprFlowReader`;
  `LocalSourcesAPI`, `FolderWatchError`, `LocalSourceCopy`, `LocalSourceWatcher` (`start`, `reload`,
  `syncFolder`, `syncNow`, `addFolder`, `preview`, `startWatching`, `removeFolder`, `updateAgentGlobs`,
  `setWispr`, `syncWispr`, `syncWisprNow`, `isOnThisMac`, `wisprInstalled`, `wisprChannel`);
  `BrowserWatcher.publish(_:error:for:)`; `BrowserFile.wisprFlowDatabase`; the eight `APIClient`
  methods and `extension APIClient: LocalSourcesAPI`.
- Consumes the Task 2/5 routes, `BrowserWatchPolicy.debounce/minimumInterval`, `BrowserFileError.classify`,
  `AddSourceSheet.friendlyError`, `Store.bank/refresh(_:)`.

- [ ] **Step 1: Failing tests.**

`app/CicadaApp/Tests/CicadaAppTests/FolderGlobTests.swift` — the same table as Task 2's `GLOB_TABLE`:

```swift
import XCTest
@testable import CicadaApp

/// G133 — the app's glob matcher runs the SAME table as
/// `api/tests/test_folder_source.py::GLOB_TABLE`. Change one, change both.
final class FolderGlobTests: XCTestCase {
    static let table: [(String, String, Bool)] = [
        ("**/*.md", "README.md", true),
        ("**/*.md", "research/plan.md", true),
        ("**/*.md", "notes.txt", false),
        ("*.md", "research/plan.md", false),
        ("archive/**", "archive/2026-01/sweep.md", true),
        ("archive/**", "research/archive/x.md", false),
        ("**/.git/**", ".git/HEAD", true),
        ("**/.git/**", "sub/.git/config", true),
        ("**/node_modules/**", "web/node_modules/a/b.md", true),
        ("docs/?.md", "docs/a.md", true),
        ("docs/?.md", "docs/ab.md", false),
    ]

    func testTheSharedTable() {
        for (pattern, relpath, expected) in Self.table {
            XCTAssertEqual(FolderGlob.matches(pattern, relpath), expected, "\(pattern) vs \(relpath)")
        }
    }

    func testCompiledRulesIncludeExcludeAndAuthorship() {
        let rules = CompiledFolderRules(include: ["**/*.md"], exclude: ["**/node_modules/**"],
                                        authorship: [FolderAuthorshipRule(glob: "archive/**", authorship: "agent")])
        XCTAssertTrue(rules.included("README.md"))
        XCTAssertFalse(rules.included("web/node_modules/x.md"))
        XCTAssertTrue(rules.excludesDirectory("web/node_modules"))
        XCTAssertFalse(rules.excludesDirectory("research"))
        XCTAssertEqual(rules.authorship("archive/2026/sweep.md"), "agent")
        XCTAssertEqual(rules.authorship("README.md"), "user")
    }

    func testRegistrationsDecodeFromAnOlderOrNewerBackend() throws {
        let json = #"{"id": "alpha-project-1a2b3c", "label": "alpha-project", "somethingNew": 1}"#
        let folder = try JSONDecoder().decode(FolderRegistration.self, from: Data(json.utf8))
        XCTAssertEqual(folder.channelId, "folder:alpha-project-1a2b3c")
        XCTAssertEqual(folder.include, [])
        XCTAssertFalse(folder.papersPending)
        let empty = try JSONDecoder().decode(FolderSyncResult.self, from: Data("{}".utf8))
        XCTAssertEqual(empty, FolderSyncResult())
        let settings = try JSONDecoder().decode(WisprFlowSettings.self, from: Data("{}".utf8))
        XCTAssertEqual(settings, WisprFlowSettings())
    }
}
```

`app/CicadaApp/Tests/CicadaAppTests/FolderScannerTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G133 — the walk, the change decision, and the batches (R-F1, R-LS8).
final class FolderScannerTests: XCTestCase {
    private var root: URL!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("FolderScannerTests-\(UUID().uuidString)")
        for (rel, text) in ["README.md": "# alpha-project", "research/plan.md": "plan",
                            "web/node_modules/pkg/readme.md": "vendored", ".git/HEAD": "ref", "notes.txt": "x"] {
            let url = root.appendingPathComponent(rel)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try text.write(to: url, atomically: true, encoding: .utf8)
        }
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent("outside.md"),
                                                   withDestinationURL: URL(fileURLWithPath: "/etc/hosts"))
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: root) }

    private var rules: CompiledFolderRules {
        CompiledFolderRules(include: ["**/*.md"], exclude: ["**/.git/**", "**/node_modules/**"], authorship: [])
    }

    func testTheWalkKeepsIncludedFilesAndNeverFollowsASymlink() {
        XCTAssertEqual(Set(FolderScanner.walk(root: root, rules: rules).keys), ["README.md", "research/plan.md"])
    }

    func testOnlyAMovedStatIsReadAndOnlyChangedBytesAreUploaded() throws {
        let current = FolderScanner.walk(root: root, rules: rules)
        let first = FolderScanner.candidates(current: current, manifest: [:])
        XCTAssertEqual(first.changed, ["README.md", "research/plan.md"])
        let read = FolderScanner.readUploads(root: root, changed: first.changed, current: current, manifest: [:])
        XCTAssertEqual(read.uploads.map(\.relpath), ["README.md", "research/plan.md"])
        var manifest: [String: FolderFileSignature] = [:]
        for u in read.uploads { manifest[u.relpath] = FolderFileSignature(size: u.size, modified: u.mtime, sha256: u.sha256) }
        XCTAssertEqual(FolderScanner.candidates(current: current, manifest: manifest).changed, [])

        // Same bytes, new mtime: read and hashed, never uploaded.
        try FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSinceNow: 60)],
                                              ofItemAtPath: root.appendingPathComponent("README.md").path)
        let touched = FolderScanner.walk(root: root, rules: rules)
        let again = FolderScanner.candidates(current: touched, manifest: manifest)
        XCTAssertEqual(again.changed, ["README.md"])
        let reread = FolderScanner.readUploads(root: root, changed: again.changed, current: touched, manifest: manifest)
        XCTAssertTrue(reread.uploads.isEmpty)
        XCTAssertEqual(Array(reread.touched.keys), ["README.md"])

        try FileManager.default.removeItem(at: root.appendingPathComponent("research/plan.md"))
        XCTAssertEqual(FolderScanner.candidates(current: FolderScanner.walk(root: root, rules: rules),
                                                manifest: manifest).deleted, ["research/plan.md"])
    }

    func testSha256AndBatches() {
        XCTAssertEqual(FolderScanner.sha256(Data("abc".utf8)),
                       "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        let big = FolderUpload(relpath: "a", size: 4_000_000, mtime: 0, sha256: "", data: Data(count: 4_000_000))
        let small = FolderUpload(relpath: "b", size: 1, mtime: 0, sha256: "", data: Data(count: 1))
        XCTAssertEqual(FolderScanner.batches([big, big, small]).map { $0.map(\.relpath) }, [["a"], ["a", "b"]])
        let many = (0..<(FolderScanner.maxBatchFiles + 1)).map {
            FolderUpload(relpath: "\($0)", size: 1, mtime: 0, sha256: "", data: Data(count: 1))
        }
        XCTAssertEqual(FolderScanner.batches(many).map(\.count), [FolderScanner.maxBatchFiles, 1])
    }
}
```

`app/CicadaApp/Tests/CicadaAppTests/WisprFlowReaderTests.swift` — a synthetic `flow.sqlite` with every
forbidden column present and full of canaries:

```swift
import SQLite3
import XCTest
@testable import CicadaApp

/// G134 / R-N1 / R-LS21 — a synthetic `flow.sqlite` with every forbidden column
/// present and full of canaries. Nothing forbidden, deleted, demo or unfinished
/// may appear in what the reader would post.
final class WisprFlowReaderTests: XCTestCase {
    private var root: URL!

    private static let schema = """
    CREATE TABLE Meetings (id TEXT, title TEXT, createdAt TEXT, modifiedAt TEXT, endedAt TEXT, isDeleted INTEGER,
      finalized INTEGER, isTourDemo INTEGER, transcriptDeletedAt TEXT, participantNames TEXT, speakerMap TEXT,
      notes TEXT, summary TEXT, audio BLOB, screenshot BLOB, url TEXT);
    INSERT INTO Meetings VALUES ('m-1','alpha-project sync','2026-09-01T10:00:00Z','2026-09-01T11:00:00Z',NULL,0,1,0,
      NULL,'["bob-example"]','{"1":"bob-example"}','notes','summary','CANARY-audio','CANARY-screenshot','CANARY-url');
    INSERT INTO Meetings VALUES ('m-2','deleted','2026-09-02T10:00:00Z','2026-09-02T11:00:00Z',NULL,1,1,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
    INSERT INTO Meetings VALUES ('m-3','demo','2026-09-03T10:00:00Z','2026-09-03T11:00:00Z',NULL,0,1,1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
    INSERT INTO Meetings VALUES ('m-4','draft','2026-09-04T10:00:00Z','2026-09-04T11:00:00Z',NULL,0,0,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
    CREATE TABLE Notes (id TEXT, title TEXT, content TEXT, createdAt INTEGER, modifiedAt INTEGER, isDeleted INTEGER, axText TEXT);
    INSERT INTO Notes VALUES ('n-1','Idea','Try a folder source.',1756717200000,1756717300000,0,'CANARY-axText');
    CREATE TABLE Todos (meetingId TEXT, title TEXT, status TEXT, isDeleted INTEGER);
    INSERT INTO Todos VALUES ('m-1','Send the deck','open',0);
    INSERT INTO Todos VALUES ('m-9','Another meeting','open',0);
    CREATE TABLE History (timestamp TEXT, formattedText TEXT, editedText TEXT, app TEXT, numWords INTEGER, asrText TEXT,
      audio BLOB, screenshot BLOB, builtInAudio BLOB, axText TEXT, axHTML TEXT, textboxContents TEXT, pastedText TEXT, url TEXT);
    INSERT INTO History VALUES ('2026-09-01T09:00:00Z','Hello there','Hello there.','com.apple.mail',2,'CANARY-asrText',
      'CANARY-audio','CANARY-screenshot','CANARY-builtInAudio','CANARY-axText','CANARY-axHTML','CANARY-textbox',
      'CANARY-pasted','CANARY-url');
    """

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("WisprFlowReaderTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root.appendingPathComponent("meetings/m-1"), withIntermediateDirectories: true)
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(root.appendingPathComponent("flow.sqlite").path, &db), SQLITE_OK)
        defer { sqlite3_close(db) }
        XCTAssertEqual(sqlite3_exec(db, Self.schema, nil, nil, nil), SQLITE_OK)
        let ndjson = """
        {"id":"u1","timestamp":"2026-09-01T10:01:00Z","text":"I will send the deck","speaker":{"id":1,"source":"system","name":null},"audioOffset":"CANARY-nd"}
        {"id":"u2","timestamp":"2026-09-01T10:02:00Z","text":"Thanks","speaker":{"id":2,"source":"mic","name":"Ada Example"}}
        """
        try ndjson.write(to: root.appendingPathComponent("meetings/m-1/refined.ndjson"), atomically: true, encoding: .utf8)
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: root) }

    private func object(_ pass: WisprFlowPass) throws -> [String: Any] {
        try XCTUnwrap(JSONSerialization.jsonObject(with: pass.json) as? [String: Any])
    }

    func testTheWhitelistsNeverNameAForbiddenColumn() {
        let allowed = Set(WisprFlowColumns.meetings + WisprFlowColumns.notes + WisprFlowColumns.todos + WisprFlowColumns.history)
        XCTAssertTrue(allowed.isDisjoint(with: WisprFlowColumns.forbidden))
    }

    func testAFirstPassProjectsOnlyFinishedMeetingsNotesAndTheirTodos() throws {
        let pass = try WisprFlowReader(root: root).read(since: WisprFlowCursor(), includeDictation: false)
        let text = String(decoding: pass.json, as: UTF8.self)
        XCTAssertFalse(text.contains("CANARY"), "a forbidden column or ndjson key crossed")
        let body = try object(pass)
        let meetings = try XCTUnwrap(body["meetings"] as? [[String: Any]])
        XCTAssertEqual(meetings.compactMap { ($0["row"] as? [String: Any])?["id"] as? String }, ["m-1"])
        let utterances = try XCTUnwrap(meetings[0]["utterances"] as? [[String: Any]])
        XCTAssertEqual(utterances.count, 2)
        XCTAssertEqual(Set(utterances[1].keys), ["timestamp", "text", "speaker"])
        XCTAssertEqual((body["todos"] as? [[String: Any]])?.compactMap { $0["title"] as? String }, ["Send the deck"])
        XCTAssertEqual((body["notes"] as? [[String: Any]])?.count, 1)
        XCTAssertNil(body["history"], "dictation is opt-in (R-LS23)")
        XCTAssertEqual(pass.cursor.meetings, .text("2026-09-01T11:00:00Z"))
        XCTAssertEqual(pass.cursor.notes, .int(1_756_717_300_000))
        XCTAssertFalse(pass.hasMore)
    }

    func testDictationOnlyWhenAskedAndOnlyItsFiveColumns() throws {
        let pass = try WisprFlowReader(root: root).read(since: WisprFlowCursor(), includeDictation: true)
        let history = try XCTUnwrap(try object(pass)["history"] as? [[String: Any]])
        XCTAssertEqual(Set(history[0].keys), Set(WisprFlowColumns.history))
        XCTAssertFalse(String(decoding: pass.json, as: UTF8.self).contains("CANARY"))
    }

    func testALaterPassReadsPastTheCursorAndReportsDeletions() throws {
        let reader = WisprFlowReader(root: root)
        let first = try reader.read(since: WisprFlowCursor(), includeDictation: false)
        let second = try reader.read(since: first.cursor, includeDictation: false)
        let body = try object(second)
        XCTAssertEqual((body["meetings"] as? [[String: Any]])?.count, 0)
        XCTAssertEqual(body["deletedMeetingIds"] as? [String], ["m-2"])
        XCTAssertFalse(second.isEmpty)
    }

    func testAMissingStoreSaysSoWithTheWisprFlowFile() {
        let reader = WisprFlowReader(root: root.appendingPathComponent("nope"))
        XCTAssertThrowsError(try reader.read(since: WisprFlowCursor(), includeDictation: false)) { error in
            guard case BrowserFileError.missing(let file, _) = error else { return XCTFail("\(error)") }
            XCTAssertEqual(file, .wisprFlowDatabase)
        }
    }
}
```

`app/CicadaApp/Tests/CicadaAppTests/LocalSourceWatcherTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// A backend stand-in: records every call, answers with defaults.
actor FakeLocalSourcesAPI: LocalSourcesAPI {
    struct SyncCall: Equatable { let files: [String]; let deleted: [String]; let preview: Bool; let resolve: Bool }
    var folders: [FolderRegistration]
    var settings = WisprFlowSettings()
    private(set) var syncCalls: [SyncCall] = []
    private(set) var wisprPosts = 0
    /// How many `fetchFolders` calls fail before one succeeds — a backend still starting.
    private var failingFetches: Int

    init(folders: [FolderRegistration], failingFetches: Int = 0) {
        self.folders = folders
        self.failingFetches = failingFetches
    }

    func fetchFolders() async throws -> [FolderRegistration] {
        if failingFetches > 0 {
            failingFetches -= 1
            throw URLError(.cannotConnectToHost)
        }
        return folders
    }
    func registerFolder(label: String, path: String, projectName: String,
                        authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration {
        let folder = FolderRegistration(id: "new-1", label: label, path: path, include: ["**/*.md"], authorship: authorship)
        folders.append(folder)
        return folder
    }
    func updateFolder(id: String, authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration {
        guard let i = folders.firstIndex(where: { $0.id == id }) else { throw URLError(.badURL) }
        folders[i].authorship = authorship
        return folders[i]
    }
    func removeFolder(id: String) async throws { folders.removeAll { $0.id == id } }
    func syncFolder(id: String, files: [FolderUpload], deleted: [String], preview: Bool,
                    resolve: Bool) async throws -> FolderSyncResult {
        syncCalls.append(SyncCall(files: files.map(\.relpath).sorted(), deleted: deleted, preview: preview, resolve: resolve))
        var result = FolderSyncResult()
        result.preview = preview
        result.filesNew = files.count
        return result
    }
    func fetchWisprSettings() async throws -> WisprFlowSettings { settings }
    func saveWisprSettings(_ settings: WisprFlowSettings) async throws -> WisprFlowSettings {
        self.settings = settings
        return settings
    }
    func postWisprFlow(_ json: Data) async throws -> WisprFlowSyncResult {
        wisprPosts += 1
        return WisprFlowSyncResult()
    }
}

/// G133 — the watcher posts what moved, tombstones what went, and lights the
/// card through `BrowserWatcher` (R-F1, R-LS26).
@MainActor
final class LocalSourceWatcherTests: XCTestCase {
    private var root: URL!
    private var defaults: UserDefaults!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("LocalSourceWatcherTests-\(UUID().uuidString)")
        for (rel, text) in ["README.md": "v1", "notes/idea.md": "an idea", ".git/HEAD": "ref"] {
            let url = root.appendingPathComponent(rel)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try text.write(to: url, atomically: true, encoding: .utf8)
        }
        defaults = UserDefaults(suiteName: "LocalSourceWatcherTests-\(UUID().uuidString)")
    }

    override func tearDownWithError() throws { try? FileManager.default.removeItem(at: root) }

    private func make(_ api: FakeLocalSourcesAPI, lights: BrowserWatcher,
                      retryDelay: Duration = .seconds(2)) -> LocalSourceWatcher {
        let root = self.root!
        return LocalSourceWatcher(
            lights: lights, api: api, defaults: defaults,
            manifests: FolderManifestStore(directory: root.appendingPathComponent(".manifests")),
            wisprRoot: root.appendingPathComponent("no-wispr"),
            debounce: .seconds(60), minimumInterval: .zero, retryDelay: retryDelay, resolveRoot: { _ in root })
    }

    func testAFolderPostsOnlyWhatChangedAndTombstonesWhatWentAway() async throws {
        let folder = FolderRegistration(id: "alpha-1", label: "alpha-project", path: root.path,
                                        include: ["**/*.md"], exclude: ["**/.git/**", "**/.manifests/**"])
        let api = FakeLocalSourcesAPI(folders: [folder])
        let lights = BrowserWatcher(defaults: defaults, channels: [])
        let watcher = make(api, lights: lights)

        await watcher.reload()
        var calls = await api.syncCalls
        XCTAssertEqual(calls, [.init(files: ["README.md", "notes/idea.md"], deleted: [], preview: false, resolve: false)])
        XCTAssertEqual(lights.state(for: "folder:alpha-1"), .watching)

        await watcher.syncFolder(watcher.folders[0], resolve: false)
        calls = await api.syncCalls
        XCTAssertEqual(calls.count, 1, "an unchanged folder posts nothing")

        try "v2, longer".write(to: root.appendingPathComponent("README.md"), atomically: true, encoding: .utf8)
        try FileManager.default.removeItem(at: root.appendingPathComponent("notes/idea.md"))
        await watcher.syncFolder(watcher.folders[0], resolve: false)
        calls = await api.syncCalls
        XCTAssertEqual(calls.last, .init(files: ["README.md"], deleted: ["notes/idea.md"], preview: false, resolve: false))
    }

    func testSyncNowAsksForPaperDetailsEvenWithNothingNew() async throws {
        let folder = FolderRegistration(id: "alpha-1", label: "alpha-project", path: root.path,
                                        include: ["**/*.md"], exclude: ["**/.manifests/**"])
        let api = FakeLocalSourcesAPI(folders: [folder])
        let watcher = make(api, lights: BrowserWatcher(defaults: defaults, channels: []))
        await watcher.reload()
        await watcher.syncNow(watcher.folders[0])
        let last = await api.syncCalls.last
        XCTAssertEqual(last, .init(files: [], deleted: [], preview: false, resolve: true))
    }

    func testAPreviewPostsEveryIncludedFileWithPreviewSet() async throws {
        let api = FakeLocalSourcesAPI(folders: [])
        let watcher = make(api, lights: BrowserWatcher(defaults: defaults, channels: []))
        let folder = try await watcher.addFolder(url: root, label: "alpha-project", projectName: "alpha-project",
                                                 agentGlobs: ["archive/**"])
        let result = try await watcher.preview(folder, root: root)
        XCTAssertTrue(result.preview)
        XCTAssertEqual(result.filesNew, 2)
        let calls = await api.syncCalls
        XCTAssertEqual(calls.map(\.preview), [true])
    }

    /// A spawned backend takes seconds to boot, and the app starts this watcher
    /// at launch: a folder list it could not fetch yet must be asked for again,
    /// not left empty (and every folder unwatched) until the next bank switch.
    func testAFolderListTheBackendCouldNotServeYetIsAskedForAgain() async throws {
        let folder = FolderRegistration(id: "alpha-1", label: "alpha-project", path: root.path,
                                        include: ["**/*.md"], exclude: ["**/.git/**", "**/.manifests/**"])
        let api = FakeLocalSourcesAPI(folders: [folder], failingFetches: 1)
        let watcher = make(api, lights: BrowserWatcher(defaults: defaults, channels: []), retryDelay: .milliseconds(20))
        await watcher.reload()
        XCTAssertTrue(watcher.folders.isEmpty, "the backend was not up yet")
        for _ in 0..<150 {
            if await !api.syncCalls.isEmpty { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTAssertEqual(watcher.folders.map(\.id), ["alpha-1"])
        let calls = await api.syncCalls
        XCTAssertEqual(calls.first?.files, ["README.md", "notes/idea.md"], "the retry watched and synced the folder")
    }

    func testPublishedLightsReachTheExistingLookups() {
        let lights = BrowserWatcher(defaults: defaults, channels: [])
        lights.publish(.blocked, error: .notReadable(.wisprFlowDatabase, "/x"), for: "wispr-flow")
        XCTAssertEqual(lights.state(for: "wispr-flow"), .blocked)
        XCTAssertEqual(lights.error(for: "wispr-flow"), .notReadable(.wisprFlowDatabase, "/x"))
        lights.publish(nil, error: nil, for: "wispr-flow")
        XCTAssertNil(lights.state(for: "wispr-flow"))
    }
}
```

Run: `cd <worktree>/app/CicadaApp && swift build --build-tests 2>&1 | tail -5` → fails (unknown types).

- [ ] **Step 2: the models** — `app/CicadaApp/Sources/CicadaApp/Models/LocalSources.swift`:

```swift
import Foundation

/// G133 / R-F2 — whose words the files under `glob` are: `"user"` or `"agent"`.
struct FolderAuthorshipRule: Codable, Equatable, Hashable, Sendable {
    var glob: String
    var authorship: String
}

/// G133 — one watched folder, as `GET /sources/folders` returns it. The backend
/// stamps `device` (R-LS9); the app never sends one. Every field but `id`
/// decodes with a default, so an older or newer backend still yields a row.
struct FolderRegistration: Codable, Identifiable, Equatable, Sendable {
    let id: String
    var label: String
    var path: String
    var device: String
    var include: [String]
    var exclude: [String]
    var authorship: [FolderAuthorshipRule]
    var projectId: String?
    var lastSync: String?
    var papersPending: Bool

    var channelId: String { "folder:\(id)" }

    /// The globs the person marked "written by an agent" (R-F2), for the Manage field.
    var agentGlobs: [String] { authorship.filter { $0.authorship == "agent" }.map(\.glob) }

    enum CodingKeys: String, CodingKey {
        case id, label, path, device, include, exclude, authorship, projectId, lastSync, papersPending
    }

    init(id: String, label: String, path: String, device: String = "", include: [String] = [],
         exclude: [String] = [], authorship: [FolderAuthorshipRule] = [], projectId: String? = nil,
         lastSync: String? = nil, papersPending: Bool = false) {
        self.id = id; self.label = label; self.path = path; self.device = device
        self.include = include; self.exclude = exclude; self.authorship = authorship
        self.projectId = projectId; self.lastSync = lastSync; self.papersPending = papersPending
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? id
        path = try c.decodeIfPresent(String.self, forKey: .path) ?? ""
        device = try c.decodeIfPresent(String.self, forKey: .device) ?? ""
        include = try c.decodeIfPresent([String].self, forKey: .include) ?? []
        exclude = try c.decodeIfPresent([String].self, forKey: .exclude) ?? []
        authorship = try c.decodeIfPresent([FolderAuthorshipRule].self, forKey: .authorship) ?? []
        projectId = try c.decodeIfPresent(String.self, forKey: .projectId)
        lastSync = try c.decodeIfPresent(String.self, forKey: .lastSync)
        papersPending = try c.decodeIfPresent(Bool.self, forKey: .papersPending) ?? false
    }
}

struct FolderListResponse: Decodable {
    let folders: [FolderRegistration]
}

struct FolderSyncError: Decodable, Equatable, Sendable {
    let relpath: String
    let reason: String
}

/// `POST /sources/folders/{id}/sync` — every count defaults to zero, so a
/// preview and a real sync decode through one type and batches can be summed.
struct FolderSyncResult: Decodable, Equatable, Sendable {
    var preview = false
    var filesNew = 0
    var filesChanged = 0
    var filesUnchanged = 0
    var filesDeleted = 0
    var agentFiles = 0
    var stage1Passes = 0
    var papersFound = 0
    var created = 0
    var updated = 0
    var renamed = 0
    var tombstoned = 0
    var papersCreated = 0
    var removalsProposed = 0
    var papersPending = false
    var errors: [FolderSyncError] = []

    enum CodingKeys: String, CodingKey {
        case preview, filesNew, filesChanged, filesUnchanged, filesDeleted, agentFiles, stage1Passes
        case papersFound, created, updated, renamed, tombstoned, papersCreated, removalsProposed
        case papersPending, errors
    }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func int(_ key: CodingKeys) throws -> Int { try c.decodeIfPresent(Int.self, forKey: key) ?? 0 }
        preview = try c.decodeIfPresent(Bool.self, forKey: .preview) ?? false
        filesNew = try int(.filesNew); filesChanged = try int(.filesChanged)
        filesUnchanged = try int(.filesUnchanged); filesDeleted = try int(.filesDeleted)
        agentFiles = try int(.agentFiles); stage1Passes = try int(.stage1Passes)
        papersFound = try int(.papersFound); created = try int(.created); updated = try int(.updated)
        renamed = try int(.renamed); tombstoned = try int(.tombstoned)
        papersCreated = try int(.papersCreated); removalsProposed = try int(.removalsProposed)
        papersPending = try c.decodeIfPresent(Bool.self, forKey: .papersPending) ?? false
        errors = try c.decodeIfPresent([FolderSyncError].self, forKey: .errors) ?? []
    }

    /// A preview posted in batches is still one answer to "what is in this folder".
    mutating func add(_ other: FolderSyncResult) {
        filesNew += other.filesNew; filesChanged += other.filesChanged
        filesUnchanged += other.filesUnchanged; filesDeleted += other.filesDeleted
        agentFiles += other.agentFiles; stage1Passes += other.stage1Passes
        papersFound += other.papersFound; created += other.created; updated += other.updated
        renamed += other.renamed; tombstoned += other.tombstoned
        papersCreated += other.papersCreated; removalsProposed += other.removalsProposed
        papersPending = papersPending || other.papersPending
        errors += other.errors
    }
}

/// G134 — per memory. Dictation is opt-in (R-LS23); `ownerSpeakerNames` is the
/// only way a meeting speaker is ever the owner (R-LS22).
struct WisprFlowSettings: Codable, Equatable, Sendable {
    var enabled = false
    var includeDictation = false
    var ownerSpeakerNames: [String] = []

    enum CodingKeys: String, CodingKey { case enabled, includeDictation, ownerSpeakerNames }

    init(enabled: Bool = false, includeDictation: Bool = false, ownerSpeakerNames: [String] = []) {
        self.enabled = enabled; self.includeDictation = includeDictation; self.ownerSpeakerNames = ownerSpeakerNames
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? false
        includeDictation = try c.decodeIfPresent(Bool.self, forKey: .includeDictation) ?? false
        ownerSpeakerNames = try c.decodeIfPresent([String].self, forKey: .ownerSpeakerNames) ?? []
    }
}

struct WisprFlowSyncResult: Decodable, Equatable, Sendable {
    var created = 0
    var updated = 0
    var skipped = 0
    var tombstoned = 0
    var dictationRefused = 0
    var todoClaims = 0

    enum CodingKeys: String, CodingKey { case created, updated, skipped, tombstoned, dictationRefused, todoClaims }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        created = try c.decodeIfPresent(Int.self, forKey: .created) ?? 0
        updated = try c.decodeIfPresent(Int.self, forKey: .updated) ?? 0
        skipped = try c.decodeIfPresent(Int.self, forKey: .skipped) ?? 0
        tombstoned = try c.decodeIfPresent(Int.self, forKey: .tombstoned) ?? 0
        dictationRefused = try c.decodeIfPresent(Int.self, forKey: .dictationRefused) ?? 0
        todoClaims = try c.decodeIfPresent(Int.self, forKey: .todoClaims) ?? 0
    }
}
```

- [ ] **Step 3: the folder reader** — `Services/LocalSources/FolderGlob.swift`:

```swift
import Foundation

/// G133 — the app-side twin of `folder_source.glob_match` / `is_included` /
/// `authorship_for`. Two implementations of one matcher is the drift risk, so
/// `FolderGlobTests` runs the SAME table `api/tests/test_folder_source.py`'s
/// `GLOB_TABLE` runs: change one, change both.
enum FolderGlob {
    /// `**/` = any number of directories (none included), `**` = anything,
    /// `*` = anything but `/`, `?` = one character but `/`, anchored.
    static func regexSource(_ pattern: String) -> String {
        let chars = Array(pattern)
        var out = ""
        var i = 0
        while i < chars.count {
            if chars[i] == "*", i + 1 < chars.count, chars[i + 1] == "*" {
                if i + 2 < chars.count, chars[i + 2] == "/" {
                    out += "(?:.*/)?"
                    i += 3
                } else {
                    out += ".*"
                    i += 2
                }
            } else if chars[i] == "*" {
                out += "[^/]*"
                i += 1
            } else if chars[i] == "?" {
                out += "[^/]"
                i += 1
            } else {
                out += NSRegularExpression.escapedPattern(for: String(chars[i]))
                i += 1
            }
        }
        return "^" + out + "$"
    }

    static func compile(_ pattern: String) -> NSRegularExpression? {
        try? NSRegularExpression(pattern: regexSource(pattern))
    }

    static func matches(_ pattern: String, _ relpath: String) -> Bool {
        guard let rx = compile(pattern) else { return false }
        return CompiledFolderRules.hit(rx, relpath)
    }
}

/// One folder's include / exclude / authorship rules, compiled once per scan.
/// `@unchecked Sendable`: `NSRegularExpression` matching is thread-safe, and a
/// scan runs off the main actor.
struct CompiledFolderRules: @unchecked Sendable {
    private let include: [NSRegularExpression]
    private let exclude: [NSRegularExpression]
    private let rules: [(NSRegularExpression, String)]

    init(include: [String], exclude: [String], authorship: [FolderAuthorshipRule]) {
        self.include = include.compactMap(FolderGlob.compile)
        self.exclude = exclude.compactMap(FolderGlob.compile)
        self.rules = authorship.compactMap { rule in FolderGlob.compile(rule.glob).map { ($0, rule.authorship) } }
    }

    init(_ folder: FolderRegistration) {
        self.init(include: folder.include, exclude: folder.exclude, authorship: folder.authorship)
    }

    static func hit(_ rx: NSRegularExpression, _ text: String) -> Bool {
        rx.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) != nil
    }

    func included(_ relpath: String) -> Bool {
        include.contains { Self.hit($0, relpath) } && !exclude.contains { Self.hit($0, relpath) }
    }

    /// A directory whose every descendant is excluded — the walk skips it rather
    /// than descending into a `node_modules` it would then discard file by file.
    func excludesDirectory(_ relpath: String) -> Bool {
        exclude.contains { Self.hit($0, relpath + "/_") }
    }

    /// First matching rule wins; no match is the person's own words.
    func authorship(_ relpath: String) -> String {
        rules.first { Self.hit($0.0, relpath) }?.1 ?? "user"
    }
}
```

`Services/LocalSources/FolderScanner.swift`:

```swift
import CryptoKit
import Foundation

/// G133 — what the APP does with a watched folder: walk it, decide which files
/// moved since the last successful sync, read those bytes, and hand them to the
/// backend in bounded batches (R-F1). The backend never opens the folder.
///
/// Change detection is `BrowserWatchPolicy`'s idea, per file: size + mtime
/// first (a `stat` is free), then a SHA-256 of the bytes only for a file whose
/// size or mtime moved — so a `touch` or a re-save of the same text costs a
/// hash, never a request.
struct FolderFileStat: Equatable, Sendable {
    let size: Int64
    let modified: Double
}

struct FolderFileSignature: Codable, Equatable, Sendable {
    let size: Int64
    let modified: Double
    let sha256: String
}

struct FolderUpload: Equatable, Sendable {
    let relpath: String
    let size: Int64
    let mtime: Double
    let sha256: String
    let data: Data
}

struct FolderReadResult: Sendable {
    var uploads: [FolderUpload] = []
    /// Files whose stat moved but whose bytes did not: the manifest learns the
    /// new stat, nothing is posted.
    var touched: [String: FolderFileSignature] = [:]
    var unreadable: [String] = []
    var tooLarge: [String] = []
    /// Any read refused by the system (the Files & Folders grant), which is the
    /// one failure with a fix to show.
    var permissionDenied = false
}

enum FolderScanner {
    /// Mirrors `folder_source.MAX_FILE_BYTES`; a bigger file is skipped app-side.
    static let maxFileBytes: Int64 = 2_000_000
    /// Under the backend's 200 files / 8 MB (R-LS8), leaving room for base64.
    static let maxBatchFiles = 100
    static let maxBatchBytes = 6_000_000

    /// Every included regular file under `root`, by relative path. Symlinks are
    /// skipped (never followed out of the folder the person picked), and an
    /// excluded directory is not descended into.
    static func walk(root: URL, rules: CompiledFolderRules) -> [String: FolderFileStat] {
        let keys: [URLResourceKey] = [.isRegularFileKey, .isDirectoryKey, .isSymbolicLinkKey,
                                      .fileSizeKey, .contentModificationDateKey]
        let base = root.resolvingSymlinksInPath().path
        let prefix = base.hasSuffix("/") ? base : base + "/"
        guard let walker = FileManager.default.enumerator(
            at: root, includingPropertiesForKeys: keys, options: [], errorHandler: { _, _ in true }
        ) else { return [:] }
        var out: [String: FolderFileStat] = [:]
        while let url = walker.nextObject() as? URL {
            guard let values = try? url.resourceValues(forKeys: Set(keys)) else { continue }
            if values.isSymbolicLink == true { continue }
            let path = url.resolvingSymlinksInPath().path
            guard path.hasPrefix(prefix) else { continue }
            let rel = String(path.dropFirst(prefix.count))
            if values.isDirectory == true {
                if rules.excludesDirectory(rel) { walker.skipDescendants() }
                continue
            }
            guard values.isRegularFile == true, rules.included(rel) else { continue }
            out[rel] = FolderFileStat(size: Int64(values.fileSize ?? 0),
                                      modified: values.contentModificationDate?.timeIntervalSince1970 ?? 0)
        }
        return out
    }

    /// Pure: which files need their bytes read, and which are gone.
    static func candidates(current: [String: FolderFileStat],
                           manifest: [String: FolderFileSignature]) -> (changed: [String], deleted: [String]) {
        let changed = current.keys.filter { rel in
            guard let known = manifest[rel], let now = current[rel] else { return true }
            return known.size != now.size || known.modified != now.modified
        }.sorted()
        let deleted = manifest.keys.filter { current[$0] == nil }.sorted()
        return (changed, deleted)
    }

    static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func readUploads(root: URL, changed: [String], current: [String: FolderFileStat],
                            manifest: [String: FolderFileSignature]) -> FolderReadResult {
        var result = FolderReadResult()
        for rel in changed {
            guard let stat = current[rel] else { continue }
            if stat.size > maxFileBytes {
                result.tooLarge.append(rel)
                continue
            }
            do {
                let data = try Data(contentsOf: root.appendingPathComponent(rel), options: [.uncached])
                let digest = sha256(data)
                if manifest[rel]?.sha256 == digest {
                    result.touched[rel] = FolderFileSignature(size: stat.size, modified: stat.modified, sha256: digest)
                    continue
                }
                result.uploads.append(FolderUpload(relpath: rel, size: stat.size, mtime: stat.modified,
                                                   sha256: digest, data: data))
            } catch {
                let ns = error as NSError
                if (ns.domain == NSCocoaErrorDomain && ns.code == NSFileReadNoPermissionError)
                    || (ns.domain == NSPOSIXErrorDomain && ns.code == Int(EPERM)) {
                    result.permissionDenied = true
                }
                result.unreadable.append(rel)
            }
        }
        return result
    }

    static func batches(_ uploads: [FolderUpload]) -> [[FolderUpload]] {
        var out: [[FolderUpload]] = []
        var current: [FolderUpload] = []
        var bytes = 0
        for upload in uploads {
            if !current.isEmpty && (current.count >= maxBatchFiles || bytes + upload.data.count > maxBatchBytes) {
                out.append(current)
                current = []
                bytes = 0
            }
            current.append(upload)
            bytes += upload.data.count
        }
        if !current.isEmpty { out.append(current) }
        return out
    }
}

/// The last-synced signature of every file, per bank and folder, in the app's
/// own Application Support — never the bank (it is this Mac's view of the
/// folder, not memory). Keyed by bank too: the same folder registered in two
/// banks must reach both.
struct FolderManifestStore: Sendable {
    let directory: URL

    static var standard: FolderManifestStore {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return FolderManifestStore(directory: base.appendingPathComponent("Cicada/FolderWatch", isDirectory: true))
    }

    private func file(_ key: String) -> URL { directory.appendingPathComponent("\(key).json") }

    func load(_ key: String) -> [String: FolderFileSignature] {
        guard let data = try? Data(contentsOf: file(key)) else { return [:] }
        return (try? JSONDecoder().decode([String: FolderFileSignature].self, from: data)) ?? [:]
    }

    func save(_ manifest: [String: FolderFileSignature], for key: String) {
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        if let data = try? JSONEncoder().encode(manifest) { try? data.write(to: file(key), options: .atomic) }
    }

    func remove(_ key: String) { try? FileManager.default.removeItem(at: file(key)) }
}

/// Where each folder is on THIS Mac. A security-scoped bookmark when the system
/// grants one (a sandboxed build); the app is unsandboxed today
/// (`VideoPlayerView.state(for:)`'s note), where a plain bookmark is what is
/// available — both survive a rename or move of the folder.
struct FolderBookmarks {
    let defaults: UserDefaults

    private func key(_ id: String) -> String { "cicada.folderWatch.bookmark.\(id)" }

    func save(_ url: URL, for id: String) {
        let data = (try? url.bookmarkData(options: .withSecurityScope, includingResourceValuesForKeys: nil, relativeTo: nil))
            ?? (try? url.bookmarkData(options: [], includingResourceValuesForKeys: nil, relativeTo: nil))
        if let data { defaults.set(data, forKey: key(id)) }
    }

    func resolve(_ id: String) -> URL? {
        guard let data = defaults.data(forKey: key(id)) else { return nil }
        var stale = false
        let url = (try? URL(resolvingBookmarkData: data, options: .withSecurityScope, relativeTo: nil,
                            bookmarkDataIsStale: &stale))
            ?? (try? URL(resolvingBookmarkData: data, options: [], relativeTo: nil, bookmarkDataIsStale: &stale))
        if let url, stale { save(url, for: id) }
        return url
    }

    func remove(_ id: String) { defaults.removeObject(forKey: key(id)) }
}
```

`Services/LocalSources/FSEventsWatch.swift`:

```swift
import CoreServices
import Foundation

/// A recursive, file-level FSEvents watch on one directory (G133, G134).
///
/// `BrowserWatch`'s `DispatchSource` is one vnode per directory and does not
/// see files changing inside subfolders — right for one bookmarks file, wrong
/// for a folder of notes or an app that writes a SQLite WAL (a WAL append
/// changes no directory entry at all). FSEvents with file events covers both.
/// Events are delivered on the main queue; the handler is expected to debounce.
final class FSEventsWatch {
    private var stream: FSEventStreamRef?
    private let handler: @MainActor () -> Void

    init?(path: String, latency: TimeInterval = 1.0, handler: @escaping @MainActor () -> Void) {
        self.handler = handler
        var context = FSEventStreamContext(version: 0, info: nil, retain: nil, release: nil, copyDescription: nil)
        context.info = Unmanaged.passUnretained(self).toOpaque()
        let callback: FSEventStreamCallback = { _, info, _, _, _, _ in
            guard let info else { return }
            let watch = Unmanaged<FSEventsWatch>.fromOpaque(info).takeUnretainedValue()
            MainActor.assumeIsolated { watch.handler() }
        }
        let flags = FSEventStreamCreateFlags(kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagNoDefer)
        guard let stream = FSEventStreamCreate(kCFAllocatorDefault, callback, &context, [path] as CFArray,
                                               FSEventStreamEventId(kFSEventStreamEventIdSinceNow), latency, flags)
        else { return nil }
        self.stream = stream
        FSEventStreamSetDispatchQueue(stream, DispatchQueue.main)
        FSEventStreamStart(stream)
    }

    func stop() {
        guard let stream else { return }
        FSEventStreamStop(stream)
        FSEventStreamInvalidate(stream)
        FSEventStreamRelease(stream)
        self.stream = nil
    }

    deinit { stop() }
}
```

- [ ] **Step 4: the Wispr Flow reader** — `Services/LocalSources/WisprFlowReader.swift`:

```swift
import Foundation
import SQLite3

/// G134 — the columns the app may read from Wispr Flow's database, and the ones
/// it must never read, named once (R-N1, R-LS21). `wispr_flow.py` holds the
/// same lists; `WisprFlowReaderTests` proves `forbidden` is disjoint from every
/// whitelist and absent from every payload.
enum WisprFlowColumns {
    static let meetings = ["id", "title", "createdAt", "modifiedAt", "endedAt", "isDeleted", "finalized",
                           "isTourDemo", "transcriptDeletedAt", "participantNames", "speakerMap", "notes", "summary"]
    static let notes = ["id", "title", "content", "createdAt", "modifiedAt", "isDeleted"]
    static let todos = ["meetingId", "title", "status", "isDeleted"]
    static let history = ["timestamp", "formattedText", "editedText", "app", "numWords"]
    static let forbidden = ["audio", "builtInAudio", "screenshot", "axText", "axHTML", "textboxContents",
                            "pastedText", "url", "asrText"]
}

/// A cursor column's raw value, bound back as the same SQLite type — Wispr
/// Flow's timestamp columns may be ISO text or epoch numbers, and `>` only
/// compares meaningfully within one type.
enum SQLiteCursor: Codable, Equatable, Sendable {
    case int(Int64), real(Double), text(String)

    init?(any value: Any?) {
        if let number = value as? NSNumber {
            if CFNumberIsFloatType(number as CFNumber) { self = .real(number.doubleValue) } else { self = .int(number.int64Value) }
        } else if let text = value as? String {
            self = .text(text)
        } else {
            return nil
        }
    }
}

struct WisprFlowCursor: Codable, Equatable, Sendable {
    var meetings: SQLiteCursor?
    var notes: SQLiteCursor?
    var history: SQLiteCursor?
}

enum SQLiteReadError: Error, LocalizedError {
    case open(String), query(String)
    var errorDescription: String? {
        switch self {
        case .open(let m): "Couldn't open Wispr Flow's data: \(m)"
        case .query(let m): "Couldn't read Wispr Flow's data: \(m)"
        }
    }
}

/// A read-only connection to someone else's database (R-N1): `mode=ro` through
/// a URI — never `immutable`, which would read past a live WAL — a 2 s busy
/// timeout, and the caller wraps one pass in a single read transaction so the
/// projection is a consistent snapshot while Wispr Flow keeps writing.
final class SQLiteReadOnly {
    private var db: OpaquePointer?
    private static let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    init(url: URL) throws {
        let encoded = url.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? url.path
        let rc = sqlite3_open_v2("file:\(encoded)?mode=ro", &db,
                                 SQLITE_OPEN_READONLY | SQLITE_OPEN_URI | SQLITE_OPEN_NOMUTEX, nil)
        guard rc == SQLITE_OK else {
            let message = db.flatMap { sqlite3_errmsg($0) }.map { String(cString: $0) } ?? "code \(rc)"
            sqlite3_close(db)
            db = nil
            throw SQLiteReadError.open(message)
        }
        sqlite3_busy_timeout(db, 2000)
    }

    func close() {
        if let db { sqlite3_close(db) }
        db = nil
    }

    deinit { close() }

    private var lastError: String { sqlite3_errmsg(db).map { String(cString: $0) } ?? "unknown error" }

    func exec(_ sql: String) throws {
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else { throw SQLiteReadError.query(lastError) }
    }

    /// The whitelisted columns this table actually has, in whitelist order —
    /// never `SELECT *`, so a column Wispr Flow adds tomorrow is not read (R-LS21).
    func columns(of table: String, whitelist: [String]) -> [String] {
        guard let rows = try? query("PRAGMA table_info(\(table))", bind: nil) else { return [] }
        let present = Set(rows.compactMap { $0["name"] as? String })
        return whitelist.filter(present.contains)
    }

    func query(_ sql: String, bind cursor: SQLiteCursor?) throws -> [[String: Any]] {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { throw SQLiteReadError.query(lastError) }
        defer { sqlite3_finalize(stmt) }
        if sql.contains("?1") {
            switch cursor {
            case .int(let v): sqlite3_bind_int64(stmt, 1, v)
            case .real(let v): sqlite3_bind_double(stmt, 1, v)
            case .text(let v): sqlite3_bind_text(stmt, 1, v, -1, Self.transient)
            case nil: sqlite3_bind_null(stmt, 1)
            }
        }
        var rows: [[String: Any]] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            var row: [String: Any] = [:]
            for i in 0..<sqlite3_column_count(stmt) {
                guard let name = sqlite3_column_name(stmt, i).map({ String(cString: $0) }) else { continue }
                switch sqlite3_column_type(stmt, i) {
                case SQLITE_INTEGER: row[name] = NSNumber(value: sqlite3_column_int64(stmt, i))
                case SQLITE_FLOAT: row[name] = NSNumber(value: sqlite3_column_double(stmt, i))
                case SQLITE_TEXT: row[name] = sqlite3_column_text(stmt, i).map { String(cString: $0) } ?? ""
                case SQLITE_NULL: row[name] = NSNull()
                default: continue  // a BLOB is never projected, whatever column holds it (R-LS21)
                }
            }
            rows.append(row)
        }
        return rows
    }
}

/// One pass over Wispr Flow's store, ready to post. Built and serialised off
/// the main actor; only `Sendable` values leave the task.
struct WisprFlowPass: Sendable {
    var json: Data
    var cursor: WisprFlowCursor
    var isEmpty: Bool
    var hasMore: Bool
}

/// G134 — reads Wispr Flow's local store the way R-N1 allows: the APP opens it
/// (the launchd backend has no Full Disk Access and never touches `~/Library`),
/// read-only, projecting only whitelisted columns of finalized, non-deleted,
/// non-demo meetings, Scratchpad notes, their to-dos, and — only when the
/// person opted in — dictation history. Audio, screenshots, accessibility text,
/// pasted text and URLs never leave the file (R-LS21). Incremental: each table
/// is read past a cursor on its own modification column, `batchLimit` rows at a
/// time.
struct WisprFlowReader: Sendable {
    let root: URL
    var batchLimit = 150
    var historyLimit = 5000
    /// A `refined.ndjson` larger than this is not read (a runaway file, not a meeting).
    var maxTranscriptBytes = 20_000_000

    static var standardRoot: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Wispr Flow", isDirectory: true)
    }

    var database: URL { root.appendingPathComponent("flow.sqlite") }

    func read(since cursor: WisprFlowCursor, includeDictation: Bool) throws -> WisprFlowPass {
        // Permission first, with the exact fix (R9): opening the file classifies
        // EPERM as `.notReadable` (Full Disk Access) and ENOENT as `.missing`.
        do {
            let handle = try FileHandle(forReadingFrom: database)
            try handle.close()
        } catch {
            // `FileHandle` reports an absent file as Cocoa code 4 (NSFileNoSuchFileError),
            // which `BrowserFileError.classify` (written for `Data(contentsOf:)`'s 260)
            // would call a permission problem — and send the person to a setting
            // that fixes nothing.
            let ns = error as NSError
            if ns.domain == NSCocoaErrorDomain && ns.code == NSFileNoSuchFileError {
                throw BrowserFileError.missing(.wisprFlowDatabase, [database.path])
            }
            throw BrowserFileError.classify(error, file: .wisprFlowDatabase, path: database.path)
        }
        let db = try SQLiteReadOnly(url: database)
        defer { db.close() }
        try db.exec("BEGIN")
        defer { try? db.exec("COMMIT") }

        var next = cursor
        var meetings: [[String: Any]] = []
        var notes: [[String: Any]] = []
        var todos: [[String: Any]] = []
        var history: [[String: Any]]? = nil
        var deletedMeetings: [String] = []
        var deletedNotes: [String] = []
        var hasMore = false

        let mcols = db.columns(of: "Meetings", whitelist: WisprFlowColumns.meetings)
        if mcols.contains("id") && mcols.contains("modifiedAt") {
            var filters = ["(?1 IS NULL OR modifiedAt > ?1)"]
            if mcols.contains("isDeleted") { filters.append("COALESCE(isDeleted, 0) = 0") }
            if mcols.contains("isTourDemo") { filters.append("COALESCE(isTourDemo, 0) = 0") }
            if mcols.contains("finalized") { filters.append("COALESCE(finalized, 0) = 1") }
            let rows = try db.query("SELECT \(mcols.joined(separator: ", ")) FROM Meetings WHERE "
                                    + filters.joined(separator: " AND ") + " ORDER BY modifiedAt LIMIT \(batchLimit)",
                                    bind: cursor.meetings)
            hasMore = hasMore || rows.count == batchLimit
            for row in rows {
                meetings.append(["row": row, "utterances": utterances(meetingId: Self.text(row["id"]))])
            }
            if let last = SQLiteCursor(any: rows.last?["modifiedAt"]) { next.meetings = last }
            if cursor.meetings != nil, mcols.contains("isDeleted") {
                deletedMeetings = try db.query("SELECT id FROM Meetings WHERE isDeleted = 1 AND modifiedAt > ?1",
                                               bind: cursor.meetings).map { Self.text($0["id"]) }
            }
            let tcols = db.columns(of: "Todos", whitelist: WisprFlowColumns.todos)
            let ids = Set(meetings.compactMap { ($0["row"] as? [String: Any]).map { Self.text($0["id"]) } })
            if tcols.contains("meetingId"), !ids.isEmpty {
                todos = try db.query("SELECT \(tcols.joined(separator: ", ")) FROM Todos", bind: nil)
                    .filter { ids.contains(Self.text($0["meetingId"])) }
            }
        }

        let ncols = db.columns(of: "Notes", whitelist: WisprFlowColumns.notes)
        if ncols.contains("id") && ncols.contains("modifiedAt") {
            var filters = ["(?1 IS NULL OR modifiedAt > ?1)"]
            if ncols.contains("isDeleted") { filters.append("COALESCE(isDeleted, 0) = 0") }
            notes = try db.query("SELECT \(ncols.joined(separator: ", ")) FROM Notes WHERE "
                                 + filters.joined(separator: " AND ") + " ORDER BY modifiedAt LIMIT \(batchLimit)",
                                 bind: cursor.notes)
            hasMore = hasMore || notes.count == batchLimit
            if let last = SQLiteCursor(any: notes.last?["modifiedAt"]) { next.notes = last }
            if cursor.notes != nil, ncols.contains("isDeleted") {
                deletedNotes = try db.query("SELECT id FROM Notes WHERE isDeleted = 1 AND modifiedAt > ?1",
                                            bind: cursor.notes).map { Self.text($0["id"]) }
            }
        }

        if includeDictation {
            let hcols = db.columns(of: "History", whitelist: WisprFlowColumns.history)
            if hcols.contains("timestamp") {
                let rows = try db.query("SELECT \(hcols.joined(separator: ", ")) FROM History WHERE "
                                        + "(?1 IS NULL OR timestamp > ?1) ORDER BY timestamp LIMIT \(historyLimit)",
                                        bind: cursor.history)
                history = rows
                hasMore = hasMore || rows.count == historyLimit
                if let last = SQLiteCursor(any: rows.last?["timestamp"]) { next.history = last }
            }
        }

        var body: [String: Any] = ["meetings": meetings, "notes": notes, "todos": todos,
                                   "deletedMeetingIds": deletedMeetings, "deletedNoteIds": deletedNotes]
        if let history { body["history"] = history }
        let isEmpty = meetings.isEmpty && notes.isEmpty && (history ?? []).isEmpty
            && deletedMeetings.isEmpty && deletedNotes.isEmpty
        return WisprFlowPass(json: try JSONSerialization.data(withJSONObject: body), cursor: next,
                             isEmpty: isEmpty, hasMore: hasMore)
    }

    /// A meeting's diarized utterances, projected to `timestamp`, `text` and
    /// `speaker{id, name, source}` — nothing else in the line crosses (R-LS21).
    func utterances(meetingId: String) -> [[String: Any]] {
        let safe = meetingId.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
        guard !safe.isEmpty, safe == meetingId else { return [] }
        let file = root.appendingPathComponent("meetings/\(safe)/refined.ndjson")
        guard let size = (try? FileManager.default.attributesOfItem(atPath: file.path))?[.size] as? NSNumber,
              size.intValue <= maxTranscriptBytes,
              let text = try? String(contentsOf: file, encoding: .utf8) else { return [] }
        return text.split(separator: "\n").compactMap { line -> [String: Any]? in
            guard let object = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else { return nil }
            var out: [String: Any] = [:]
            if let ts = object["timestamp"], !(ts is NSNull) { out["timestamp"] = ts }
            if let words = object["text"] as? String { out["text"] = words }
            if let speaker = object["speaker"] as? [String: Any] {
                var kept: [String: Any] = [:]
                for key in ["id", "name", "source"] {
                    if let value = speaker[key], !(value is NSNull) { kept[key] = value }
                }
                out["speaker"] = kept
            }
            return out["text"] == nil ? nil : out
        }
    }

    private static func text(_ value: Any?) -> String {
        switch value {
        case let s as String: s
        case let n as NSNumber: n.stringValue
        default: ""
        }
    }
}
```

- [ ] **Step 5: the watcher** — `Services/LocalSources/LocalSourceWatcher.swift`:

```swift
import Foundation

/// The backend calls a local source makes — `APIClient` in the app, a fake in
/// tests (the same injection `BrowserWatcher.performSync` uses).
protocol LocalSourcesAPI: Sendable {
    func fetchFolders() async throws -> [FolderRegistration]
    func registerFolder(label: String, path: String, projectName: String,
                        authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration
    func updateFolder(id: String, authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration
    func removeFolder(id: String) async throws
    func syncFolder(id: String, files: [FolderUpload], deleted: [String], preview: Bool,
                    resolve: Bool) async throws -> FolderSyncResult
    func fetchWisprSettings() async throws -> WisprFlowSettings
    func saveWisprSettings(_ settings: WisprFlowSettings) async throws -> WisprFlowSettings
    func postWisprFlow(_ json: Data) async throws -> WisprFlowSyncResult
}

enum FolderWatchError: Error, LocalizedError, Equatable {
    case permissionDenied
    var errorDescription: String? { LocalSourceCopy.folderPermissionFix }
}

/// Plain, friendly copy for the two local sources (no jargon, no numbers baked in).
enum LocalSourceCopy {
    static let folderPermissionFix =
        "Cicada can't read this folder. Allow it under System Settings → Privacy & Security → Files and Folders, then try again."
    static let folderMissing = "This folder isn't on this Mac — it may live on another computer, or it moved."
}

/// G133 / G134 — the local sources the APP reads (R-F1, R-N1): every watched
/// folder of the active memory and, when turned on, Wispr Flow.
///
/// Watches are FSEvents streams (recursive, file-level — `FSEventsWatch`),
/// debounced like `BrowserWatchPolicy` and floored per source so an app that
/// writes constantly (Wispr Flow's WAL during dictation) cannot become a
/// request loop. On launch and on every bank switch `reload()` catches up: a
/// folder posts only what moved since its manifest; Wispr Flow reads past its
/// cursors. Lights are published through `BrowserWatcher.publish` (R-LS26), so
/// the Sources cards, the channel page and Integrations read "Watching" through
/// the lookups they already make.
@MainActor
@Observable
final class LocalSourceWatcher {
    static let wisprChannel = "wispr-flow"

    private(set) var folders: [FolderRegistration] = []
    /// The folder's last failure, in words the person can act on.
    private(set) var folderErrors: [String: String] = [:]
    private(set) var wisprSettings = WisprFlowSettings()
    private(set) var wisprError: BrowserFileError?
    private(set) var syncing: Set<String> = []

    private let lights: BrowserWatcher
    private let api: any LocalSourcesAPI
    private let defaults: UserDefaults
    private let manifests: FolderManifestStore
    private let bookmarks: FolderBookmarks
    private let wisprRoot: URL
    private let debounce: Duration
    private let minimumInterval: Duration
    private let wisprDebounce: Duration
    private let wisprMinimumInterval: Duration
    private let resolveRoot: (String) -> URL?
    private var store: Store?
    private var bank = "default"
    private var streams: [String: FSEventsWatch] = [:]
    private var wisprStream: FSEventsWatch?
    private var pending: [String: Task<Void, Never>] = [:]
    private var lastStarted: [String: ContinuousClock.Instant] = [:]
    private let retryBase: Duration
    private var retryDelay: Duration
    private var reloadRetry: Task<Void, Never>?

    init(lights: BrowserWatcher,
         api: any LocalSourcesAPI = APIClient.shared,
         defaults: UserDefaults = .standard,
         manifests: FolderManifestStore = .standard,
         wisprRoot: URL = WisprFlowReader.standardRoot,
         debounce: Duration = BrowserWatchPolicy.debounce,
         minimumInterval: Duration = BrowserWatchPolicy.minimumInterval,
         wisprDebounce: Duration = .seconds(30),
         wisprMinimumInterval: Duration = .seconds(300),
         retryDelay: Duration = .seconds(2),
         resolveRoot: ((String) -> URL?)? = nil) {
        self.lights = lights
        self.api = api
        self.defaults = defaults
        self.manifests = manifests
        let bookmarks = FolderBookmarks(defaults: defaults)
        self.bookmarks = bookmarks
        self.wisprRoot = wisprRoot
        self.debounce = debounce
        self.minimumInterval = minimumInterval
        self.wisprDebounce = wisprDebounce
        self.wisprMinimumInterval = wisprMinimumInterval
        self.retryBase = retryDelay
        self.retryDelay = retryDelay
        self.resolveRoot = resolveRoot ?? { bookmarks.resolve($0) }
    }

    /// Wispr Flow is on this Mac — the Integrations row only offers what exists.
    var wisprInstalled: Bool { FileManager.default.fileExists(atPath: WisprFlowReader(root: wisprRoot).database.path) }

    /// Whether a registered folder can be reached from this Mac at all.
    func isOnThisMac(_ folder: FolderRegistration) -> Bool { resolveRoot(folder.id) != nil }

    // MARK: Lifecycle

    func start(store: Store) {
        self.store = store
        Task { await reload() }
    }

    /// Re-read the active memory's folders and Wispr Flow settings, re-arm every
    /// watch, and catch up on anything that changed while the app was closed.
    func reload() async {
        bank = store?.bank ?? bank
        do {
            folders = try await api.fetchFolders()
            retryDelay = retryBase
        } catch {
            // The backend may still be starting (a spawned child takes seconds) or be
            // briefly down: ask again, backing off to a minute, instead of leaving every
            // folder unwatched until the next bank switch.
            scheduleReload()
        }
        wisprSettings = (try? await api.fetchWisprSettings()) ?? wisprSettings
        arm()
        for folder in folders { await syncFolder(folder, resolve: false) }
        if wisprSettings.enabled { await syncWispr() }
    }

    private func scheduleReload() {
        reloadRetry?.cancel()
        let delay = retryDelay
        retryDelay = min(retryDelay * 2, .seconds(60))
        reloadRetry = Task { [weak self] in
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled else { return }
            await self?.reload()
        }
    }

    private func arm() {
        for (id, stream) in streams where !folders.contains(where: { $0.id == id }) {
            stream.stop()
            streams[id] = nil
        }
        for folder in folders where streams[folder.id] == nil {
            guard let root = resolveRoot(folder.id) else {
                lights.publish(nil, error: nil, for: folder.channelId)
                continue
            }
            // Held for the process: a watch needs its folder for as long as it runs.
            _ = root.startAccessingSecurityScopedResource()
            let id = folder.id
            streams[id] = FSEventsWatch(path: root.path) { [weak self] in self?.folderChanged(id) }
            lights.publish(.watching, error: nil, for: folder.channelId)
        }
        if wisprSettings.enabled, wisprStream == nil, FileManager.default.fileExists(atPath: wisprRoot.path) {
            wisprStream = FSEventsWatch(path: wisprRoot.path) { [weak self] in self?.wisprChanged() }
        } else if !wisprSettings.enabled {
            wisprStream?.stop()
            wisprStream = nil
            lights.publish(nil, error: nil, for: Self.wisprChannel)
        }
    }

    private func folderChanged(_ id: String) {
        pending[id]?.cancel()
        pending[id] = Task { [weak self] in
            try? await Task.sleep(for: self?.debounce ?? .seconds(1))
            guard !Task.isCancelled, let self, let folder = self.folders.first(where: { $0.id == id }) else { return }
            await self.syncFolder(folder, resolve: false)
        }
    }

    private func wisprChanged() {
        pending[Self.wisprChannel]?.cancel()
        pending[Self.wisprChannel] = Task { [weak self] in
            try? await Task.sleep(for: self?.wisprDebounce ?? .seconds(30))
            guard !Task.isCancelled, let self else { return }
            await self.syncWispr()
        }
    }

    /// Inside the floor, the change is not dropped: it is re-tried when the floor
    /// ends (a save burst must not leave a file stale until the next edit).
    private func tooSoon(_ channel: String, floor: Duration, retry: @escaping @MainActor () async -> Void) -> Bool {
        guard let started = lastStarted[channel], ContinuousClock.now - started < floor else { return false }
        let wait = floor - (ContinuousClock.now - started)
        pending[channel]?.cancel()
        pending[channel] = Task {
            try? await Task.sleep(for: wait)
            guard !Task.isCancelled else { return }
            await retry()
        }
        return true
    }

    // MARK: Folders (G133)

    func syncFolder(_ folder: FolderRegistration, resolve: Bool) async {
        let channel = folder.channelId
        guard !syncing.contains(channel), let root = resolveRoot(folder.id) else { return }
        if tooSoon(channel, floor: minimumInterval, retry: { [weak self] in await self?.syncFolder(folder, resolve: resolve) }) {
            return
        }
        syncing.insert(channel)
        lastStarted[channel] = .now
        lights.publish(.syncing, error: nil, for: channel)
        defer { syncing.remove(channel) }

        let key = "\(bank)-\(folder.id)"
        let manifest = manifests.load(key)
        let rules = CompiledFolderRules(folder)
        let (read, deleted) = await Task.detached(priority: .utility) { () -> (FolderReadResult, [String]) in
            let current = FolderScanner.walk(root: root, rules: rules)
            let plan = FolderScanner.candidates(current: current, manifest: manifest)
            return (FolderScanner.readUploads(root: root, changed: plan.changed, current: current, manifest: manifest),
                    plan.deleted)
        }.value
        if read.permissionDenied {
            folderErrors[folder.id] = LocalSourceCopy.folderPermissionFix
            lights.publish(.failed, error: nil, for: channel)
            return
        }
        var next = manifest
        for (rel, signature) in read.touched { next[rel] = signature }
        do {
            let batches = FolderScanner.batches(read.uploads)
            if batches.isEmpty, !deleted.isEmpty || resolve {
                _ = try await api.syncFolder(id: folder.id, files: [], deleted: deleted, preview: false, resolve: resolve)
            }
            for (i, batch) in batches.enumerated() {
                _ = try await api.syncFolder(id: folder.id, files: batch, deleted: i == 0 ? deleted : [],
                                             preview: false, resolve: resolve && i == batches.count - 1)
                for upload in batch {
                    next[upload.relpath] = FolderFileSignature(size: upload.size, modified: upload.mtime, sha256: upload.sha256)
                }
                manifests.save(next, for: key)
            }
            for rel in deleted { next.removeValue(forKey: rel) }
            manifests.save(next, for: key)
            folderErrors[folder.id] = nil
            lights.publish(.watching, error: nil, for: channel)
            if !read.uploads.isEmpty || !deleted.isEmpty {
                await store?.refresh([.channels, .sourcesOverview, .sources, .status, .inbox])
            }
        } catch {
            folderErrors[folder.id] = AddSourceSheet.friendlyError(error)
            lights.publish(.failed, error: nil, for: channel)
        }
    }

    /// "Sync now": skip the floor, and ask the backend for paper details (R-LS18).
    func syncNow(_ folder: FolderRegistration) async {
        lastStarted[folder.channelId] = nil
        await syncFolder(folder, resolve: true)
    }

    /// Register a folder the person picked, and remember where it is on this Mac.
    func addFolder(url: URL, label: String, projectName: String, agentGlobs: [String]) async throws -> FolderRegistration {
        let rules = agentGlobs.map { FolderAuthorshipRule(glob: $0, authorship: "agent") }
        let folder = try await api.registerFolder(label: label, path: url.path, projectName: projectName,
                                                  authorship: rules)
        bookmarks.save(url, for: folder.id)
        folders = (try? await api.fetchFolders()) ?? (folders.filter { $0.id != folder.id } + [folder])
        return folder
    }

    /// What a first sync would stage — every included file, posted with `preview`.
    func preview(_ folder: FolderRegistration, root: URL) async throws -> FolderSyncResult {
        let rules = CompiledFolderRules(folder)
        let read = await Task.detached(priority: .userInitiated) { () -> FolderReadResult in
            let current = FolderScanner.walk(root: root, rules: rules)
            return FolderScanner.readUploads(root: root, changed: current.keys.sorted(), current: current, manifest: [:])
        }.value
        if read.permissionDenied { throw FolderWatchError.permissionDenied }
        var total = FolderSyncResult()
        total.preview = true
        for batch in FolderScanner.batches(read.uploads) {
            total.add(try await api.syncFolder(id: folder.id, files: batch, deleted: [], preview: true, resolve: false))
        }
        return total
    }

    /// Arm the new folder's watch and run its first real sync, details included.
    func startWatching(_ folder: FolderRegistration) async {
        arm()
        await syncFolder(folder, resolve: true)
    }

    func removeFolder(_ folder: FolderRegistration) async throws {
        try await api.removeFolder(id: folder.id)
        streams[folder.id]?.stop()
        streams[folder.id] = nil
        bookmarks.remove(folder.id)
        manifests.remove("\(bank)-\(folder.id)")
        lights.publish(nil, error: nil, for: folder.channelId)
        folders.removeAll { $0.id == folder.id }
        folderErrors[folder.id] = nil
        await store?.refresh([.channels, .sourcesOverview])
    }

    /// A changed "written by an agent" rule re-posts every file, so the backend can
    /// re-attribute them (R-LS10): the manifest is dropped, nothing else.
    func updateAgentGlobs(_ folder: FolderRegistration, globs: [String]) async throws {
        let updated = try await api.updateFolder(
            id: folder.id, authorship: globs.map { FolderAuthorshipRule(glob: $0, authorship: "agent") })
        if let i = folders.firstIndex(where: { $0.id == folder.id }) { folders[i] = updated }
        manifests.remove("\(bank)-\(folder.id)")
        lastStarted[folder.channelId] = nil
        await syncFolder(updated, resolve: false)
    }

    // MARK: Wispr Flow (G134)

    private var cursorKey: String { "cicada.wisprFlow.cursor.\(bank)" }

    private func loadCursor() -> WisprFlowCursor {
        guard let data = defaults.data(forKey: cursorKey) else { return WisprFlowCursor() }
        return (try? JSONDecoder().decode(WisprFlowCursor.self, from: data)) ?? WisprFlowCursor()
    }

    private func saveCursor(_ cursor: WisprFlowCursor) {
        if let data = try? JSONEncoder().encode(cursor) { defaults.set(data, forKey: cursorKey) }
    }

    /// Turn the source on or off, or change what it reads. A new "your name in
    /// meetings" list re-reads every meeting so past transcripts credit the
    /// person too (a one-time re-read, disclosed in G134).
    func setWispr(_ settings: WisprFlowSettings) async throws {
        let previous = wisprSettings
        wisprSettings = try await api.saveWisprSettings(settings)
        if wisprSettings.ownerSpeakerNames != previous.ownerSpeakerNames {
            var cursor = loadCursor()
            cursor.meetings = nil
            saveCursor(cursor)
        }
        arm()
        if wisprSettings.enabled {
            lastStarted[Self.wisprChannel] = nil
            await syncWispr()
        }
        await store?.refresh([.channels, .sourcesOverview])
    }

    /// "Sync now" on the Wispr Flow row: skip the floor.
    func syncWisprNow() async {
        lastStarted[Self.wisprChannel] = nil
        await syncWispr()
    }

    func syncWispr() async {
        let channel = Self.wisprChannel
        guard wisprSettings.enabled, !syncing.contains(channel) else { return }
        if tooSoon(channel, floor: wisprMinimumInterval, retry: { [weak self] in await self?.syncWispr() }) { return }
        syncing.insert(channel)
        lastStarted[channel] = .now
        lights.publish(.syncing, error: nil, for: channel)
        defer { syncing.remove(channel) }
        let reader = WisprFlowReader(root: wisprRoot)
        let includeDictation = wisprSettings.includeDictation
        var cursor = loadCursor()
        do {
            var posted = false
            for _ in 0..<20 {  // bounded catch-up: at most 20 batches per pass
                let since = cursor
                let pass = try await Task.detached(priority: .utility) {
                    try reader.read(since: since, includeDictation: includeDictation)
                }.value
                if pass.isEmpty { break }
                _ = try await api.postWisprFlow(pass.json)
                cursor = pass.cursor
                saveCursor(cursor)
                posted = true
                if !pass.hasMore { break }
            }
            wisprError = nil
            lights.publish(.watching, error: nil, for: channel)
            if posted { await store?.refresh([.channels, .sourcesOverview, .status]) }
        } catch let error as BrowserFileError {
            wisprError = error
            if case .notReadable = error {
                lights.publish(.blocked, error: error, for: channel)
            } else {
                lights.publish(.failed, error: error, for: channel)
            }
        } catch {
            lights.publish(.failed, error: nil, for: channel)
        }
    }
}
```

- [ ] **Step 6: the seams it plugs into.**
  - `Services/BrowserWatch.swift:236-237` — replace the two lookups with:

```swift
    func state(for channel: String) -> BrowserWatchState? { states[channel] ?? externalStates[channel] }
    func error(for channel: String) -> BrowserFileError? { errors[channel] ?? externalErrors[channel] }

    /// R-LS26 — a local source the app reads (a watched folder, Wispr Flow;
    /// `LocalSourceWatcher`) lights the same four views through the same two
    /// lookups above, instead of every view learning a second watcher. `nil`
    /// clears the light (a folder that is not on this Mac shows none).
    private(set) var externalStates: [String: BrowserWatchState] = [:]
    private var externalErrors: [String: BrowserFileError] = [:]

    func publish(_ state: BrowserWatchState?, error: BrowserFileError?, for channel: String) {
        externalStates[channel] = state
        externalErrors[channel] = error
    }
```

  - `Services/BrowserFiles.swift` — add the case (after `case safariTabsDb, …, chromeBookmarks`):

```swift
    /// G134 — Wispr Flow's local store. Same seam: the app reads it, the backend
    /// parses what the app projects (R-N1), and a refused read shows the fix.
    case wisprFlowDatabase
```

    and one arm in each of the three switches: `candidatePaths` →
    `case .wisprFlowDatabase: return [WisprFlowReader.standardRoot.appendingPathComponent("flow.sqlite")]`;
    `displayName` → `case .wisprFlowDatabase: "Wispr Flow"`; `userMessage`'s `.missing` switch →
    `case .wisprFlowDatabase: return "Wispr Flow isn't on this Mac yet, or hasn't recorded anything."`
  - `Services/APIClient.swift` — insert before `    // MARK: - RSS feed subscriptions (G9)` (`:1709`,
    the indented one inside `actor APIClient` — not the top-level `(G9 — feeds.yaml registry)` mark at `:395`):

```swift
    // MARK: - Local sources (G133 / G134)

    /// `GET /sources/folders` — the active memory's watched folders.
    func fetchFolders() async throws -> [FolderRegistration] {
        let response: FolderListResponse = try await get("/sources/folders")
        return response.folders
    }

    /// `POST /sources/folders` — register (or re-pick) a folder; the backend
    /// stamps the device and anchors the project by name (R-LS9, R-LS13).
    func registerFolder(label: String, path: String, projectName: String,
                        authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration {
        try await post("/sources/folders", body: [
            "label": label, "path": path, "projectName": projectName,
            "authorship": authorship.map { ["glob": $0.glob, "authorship": $0.authorship] },
        ])
    }

    func updateFolder(id: String, authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration {
        try await put("/sources/folders/\(encodedID(id))", body: [
            "authorship": authorship.map { ["glob": $0.glob, "authorship": $0.authorship] },
        ])
    }

    func removeFolder(id: String) async throws {
        _ = try await delete("/sources/folders/\(encodedID(id))")
    }

    /// `POST /sources/folders/{id}/sync` — file bytes as base64 (R-LS8).
    func syncFolder(id: String, files: [FolderUpload], deleted: [String], preview: Bool,
                    resolve: Bool) async throws -> FolderSyncResult {
        let body: [String: Any] = [
            "files": files.map { ["relpath": $0.relpath, "mtime": $0.mtime, "sha256": $0.sha256,
                                  "contentB64": $0.data.base64EncodedString()] },
            "deleted": deleted,
        ]
        return try await post("/sources/folders/\(encodedID(id))/sync?preview=\(preview)&resolve=\(resolve)", body: body)
    }

    func fetchWisprSettings() async throws -> WisprFlowSettings {
        try await get("/capture/local-source/wispr-flow/settings")
    }

    func saveWisprSettings(_ settings: WisprFlowSettings) async throws -> WisprFlowSettings {
        try await put("/capture/local-source/wispr-flow/settings", body: [
            "enabled": settings.enabled, "includeDictation": settings.includeDictation,
            "ownerSpeakerNames": settings.ownerSpeakerNames,
        ])
    }

    /// `POST /capture/local-source/wispr-flow` — a projection already serialised
    /// off the main actor by `WisprFlowReader`, so only `Data` crosses into the actor.
    func postWisprFlow(_ json: Data) async throws -> WisprFlowSyncResult {
        try await postData("/capture/local-source/wispr-flow", json: json)
    }

```

    add, directly above `@discardableResult private func post(_ path: String, body: [String: Any]? = nil) async throws -> Data`:

```swift
    private func postData<T: Decodable>(_ path: String, json: Data) async throws -> T {
        var request = makeRequest(path, method: "POST")
        request.httpBody = json
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.serverUnreachable
        }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { Self.invalidateToken() }
            let msg = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.httpError(http.statusCode, msg)
        }
        return try decoder.decode(T.self, from: data)
    }

```

    and at the very end of the file:

```swift
/// G133 / G134 — `LocalSourceWatcher` talks to the backend through this seam.
extension APIClient: LocalSourcesAPI {}
```

  - `CicadaApp.swift` — `:47` becomes

```swift
    @State private var browserWatcher: BrowserWatcher
    /// G133 / G134: watched folders and Wispr Flow, read by the app (the backend
    /// never opens them). Lights ride `browserWatcher` (R-LS26).
    @State private var localSources: LocalSourceWatcher
```

    in `init()`, right after `_store = State(initialValue: store)`:

```swift
        let lights = BrowserWatcher()
        _browserWatcher = State(initialValue: lights)
        _localSources = State(initialValue: LocalSourceWatcher(lights: lights))
```

    after `.environment(browserWatcher)` (`:103`) add `.environment(localSources)`; after the
    `.onChange(of: colorSchemeRaw) { … }` block add

```swift
                // G133 / G134: folders and Wispr Flow settings are per memory, so a
                // bank switch re-reads them and re-arms the watches.
                .onChange(of: store.bank) { _, _ in
                    Task { await localSources.reload() }
                }
```

    after `browserWatcher.start(store: store)` (`:138`) add `localSources.start(store: store)`; and in the
    `Settings {` scene add `.environment(localSources)` directly under `SettingsScene()` (`:227`), so the
    Integrations page Task 7 builds reads the same watcher the window does.

- [ ] **Step 7: Verify** — `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` (no warnings from the
  new files), `swift test --filter "FolderGlobTests|FolderScannerTests|WisprFlowReaderTests|LocalSourceWatcherTests" 2>&1 | tail -20`,
  then the full `swift test 2>&1 | tail -20` → 0 failures.
- [ ] **Step 8: Commit** — `feat(G133/G134): the app watches folders and reads Wispr Flow — bytes and a whitelisted projection, never more (R-F1, R-N1)`.

---

### Task 7: The surfaces — Notes & files, Voice & meetings, the paper card, the Feed (R-LS25 … R-LS28)

After this task a person can add a folder (or an Obsidian vault) and turn on Wispr Flow from
Settings → Integrations, sees each as a card that says "Watching", and opens a paper to read why it
is in their memory above the dated abstract.

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/Paper.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Graph/PaperCard.swift`
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Settings/LocalSourceRows.swift`
- Modify: `Models/IntegrationCategory.swift`, `Models/SourceOverview.swift`, `Models/Entity.swift`
  (`MediaBlock`), `ViewModels/FeedViewModel.swift`, `Views/Capture/OriginIconography.swift`,
  `Views/Capture/ConnectedChannelRow.swift`, `Views/Sources/{SourceDisplayName,SourceBlurb,
  BrowserStatusLight,SourceCardGrid,SourceHeaderCard,ChannelSourceView}.swift`,
  `Views/Settings/IntegrationsView.swift`, `Views/Graph/EntityDetailCard.swift`,
  `Views/Feed/FeedView.swift`, `Services/APIClient.swift` (`MediaFeedItem`, `fetchPaperDetail`)
- Test: `app/CicadaApp/Tests/CicadaAppTests/LocalSourcesSurfaceTests.swift`, `PaperCardTests.swift` (new);
  `IntegrationsViewTests.swift:27` (edit)

**Interfaces:**
- Produces `PaperSummary`, `PaperWhyItem`, `PaperDetail`; `PaperCardText` (`byline`, `feedLine`,
  `label`, `whereLine`, `contextHeading`, `agentOnly`, `noWhy`, `noContext`), `PaperCard`;
  `LocalSourceRowText` (`folderLine`, `wisprLine`, `previewSummary`, `sleepLine`, `list`),
  `PickedFolder`, `FolderChannelRow`, `AddFolderRow` (`.folder`, `.obsidian`, `obsidianInstalled`),
  `AddFolderSheet`, `FolderManagePanel`, `WisprFlowRow`, `WisprFlowPanel`;
  `IntegrationCategory.notesAndFiles/.voiceAndMeetings`; `SourceKind.voice`;
  `BrowserStatusLight.channelId` + `explanation(for:channelId:)`; `MediaFeedItem.kind/paper/isPaper`;
  `MediaBlock.kind/isPaper`; `FeedViewModel.matches(_:query:)`; `APIClient.fetchPaperDetail(id:)`.
- Consumes Task 6's `LocalSourceWatcher`, Task 4's `GET /entities/{id}/paper` and the Feed rows'
  `kind`/`paper`, Task 5's `voice` kind, `UsageFormat.count(_:locale:)`, `LogoImage.platformTile`,
  `FullDiskAccessHint`, `CicadaTheme.font(size:…)`.

- [ ] **Step 1: Failing tests.**

`app/CicadaApp/Tests/CicadaAppTests/LocalSourcesSurfaceTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G133 / G134 surfaces — categories, marks, names, kinds, light copy and the
/// rows' sentences (R-LS25 … R-LS27).
final class LocalSourcesSurfaceTests: XCTestCase {
    private let en = Locale(identifier: "en_US")

    func testFoldersAndNotesLiveUnderNotesAndFilesAndWisprUnderVoice() {
        XCTAssertEqual(IntegrationCategory.of(channelId: "folder:alpha-project-1a2b3c"), .notesAndFiles)
        XCTAssertEqual(IntegrationCategory.of(channelId: "notes"), .notesAndFiles)
        XCTAssertEqual(IntegrationCategory.of(channelId: "wispr-flow"), .voiceAndMeetings)
        XCTAssertEqual(IntegrationCategory.of(channelId: "files"), .filesAndImports)
        XCTAssertEqual(IntegrationCategory.notesAndFiles.title, "Notes & files")
        XCTAssertEqual(IntegrationCategory.voiceAndMeetings.title, "Voice & meetings")
    }

    func testMarksResolveThroughTheInstalledAppFirst() {
        XCTAssertEqual(OriginIconography.appBundleId(for: "wispr-flow"), "com.electron.wispr-flow")
        XCTAssertEqual(OriginIconography.appBundleId(for: "obsidian"), "md.obsidian")
        XCTAssertEqual(OriginIconography.label(for: "wispr-flow"), "Wispr Flow")
        XCTAssertEqual(OriginIconography.symbol(for: "wispr-flow"), "waveform")
        XCTAssertEqual(OriginIconography.symbol(for: "folder"), "folder")
        XCTAssertTrue(OriginIconography.allKnownOrigins.contains("folder"))
        XCTAssertTrue(OriginIconography.allKnownOrigins.contains("wispr-flow"))
        XCTAssertEqual(ConnectedChannelRow.origin(forChannel: "folder:alpha-project-1a2b3c"), "folder")
        XCTAssertEqual(ConnectedChannelRow.icon(for: "folder:alpha-project-1a2b3c"), "folder")
        XCTAssertEqual(ConnectedChannelRow.icon(for: "wispr-flow"), "waveform")
    }

    func testAFolderCardIsNamedByThePersonAndWisprByItsBrand() {
        let folder = SourceOverview(id: "folder:alpha-project-1a2b3c", label: "alpha-project", kind: .import)
        XCTAssertEqual(SourceDisplayName.of(folder), "alpha-project")
        XCTAssertEqual(SourceDisplayName.of(id: "wispr-flow"), "Wispr Flow")
        XCTAssertEqual(SourceBlurb.text(for: folder), "Notes in alpha-project, kept in step as you edit them.")
    }

    func testTheVoiceKindDecodesAndHasItsOwnSection() throws {
        let json = #"{"id": "wispr-flow", "label": "Wispr Flow", "kind": "voice", "episodes": 2}"#
        let row = try JSONDecoder().decode(SourceOverview.self, from: Data(json.utf8))
        XCTAssertEqual(row.kind, .voice)
        XCTAssertEqual(SourceSections.group([row]).first?.title, "VOICE & MEETINGS")
        XCTAssertEqual(SourceKind.order.firstIndex(of: .voice), SourceKind.order.firstIndex(of: .import).map { $0 - 1 })
    }

    func testLocalLightsExplainThemselvesInTheirOwnWords() {
        let browser = BrowserStatusLight.explanation(for: .watching)
        let folder = BrowserStatusLight.explanation(for: .watching, channelId: "folder:alpha-1")
        let wispr = BrowserStatusLight.explanation(for: .watching, channelId: "wispr-flow")
        XCTAssertNotEqual(folder, browser)
        XCTAssertNotEqual(wispr, browser)
        XCTAssertFalse(folder.contains("bookmark"))
        XCTAssertEqual(BrowserStatusLight.explanation(for: .stale, channelId: nil), BrowserStatusLight.explanation(for: .stale))
    }

    func testTheAddFolderSheetSaysCountsInPlainWords() {
        var r = FolderSyncResult()
        r.filesNew = 12
        r.agentFiles = 3
        r.papersFound = 1_200
        r.stage1Passes = 7
        // Synthetic counts; 1,200 also proves the number is grouped for the reader's locale.
        XCTAssertEqual(LocalSourceRowText.previewSummary(r, locale: en), "Found 12 notes · 3 written by an agent · 1,200 papers")
        XCTAssertEqual(LocalSourceRowText.sleepLine(r, locale: en), "Sleep will read your own notes in about 7 steps.")
        var one = FolderSyncResult()
        one.filesNew = 1
        XCTAssertEqual(LocalSourceRowText.previewSummary(one, locale: en), "Found 1 note")
        XCTAssertTrue(LocalSourceRowText.sleepLine(one, locale: en).hasPrefix("Nothing here for Sleep"))
        XCTAssertEqual(LocalSourceRowText.list("archive/**, drafts/**\nold/**"), ["archive/**", "drafts/**", "old/**"])
    }

    func testTheWisprLineBeforeAndAfterItIsOn() {
        XCTAssertEqual(LocalSourceRowText.wisprLine(nil, settings: WisprFlowSettings()),
                       "Your meetings and notes from Wispr Flow on this Mac.")
        XCTAssertEqual(LocalSourceRowText.wisprLine(nil, settings: WisprFlowSettings(enabled: true)),
                       "On — the first sync is on its way")
    }
}
```

`app/CicadaApp/Tests/CicadaAppTests/PaperCardTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G133 / G121 — the paper card's sentences, the Feed row's byline and search,
/// and the wire shapes they decode from (R7 §5.2).
final class PaperCardTests: XCTestCase {
    private func item(_ extra: String = "") throws -> MediaFeedItem {
        let json = """
        {"mediaEntityId": "media-arxiv-2401-00001", "url": "https://arxiv.org/abs/2401.00001",
         "title": "Paper Alpha", "mediaType": "url", "savedAt": "2026-09-01T00:00:00+00:00" \(extra)}
        """
        return try JSONDecoder().decode(MediaFeedItem.self, from: Data(json.utf8))
    }

    func testBylines() {
        XCTAssertEqual(PaperCardText.byline(authors: ["Ada Example", "Bob Example"], venue: "Journal of Examples",
                                            published: "2024-01-02"),
                       "Ada Example, Bob Example · Journal of Examples · 2024")
        XCTAssertEqual(PaperCardText.byline(authors: ["A", "B", "C", "D"], venue: nil, published: nil), "A, B, C et al.")
        XCTAssertEqual(PaperCardText.feedLine(PaperSummary(authors: ["Ada Example", "Bob Example"], published: "2024-01-02")),
                       "Ada Example et al. · 2024")
        XCTAssertNil(PaperCardText.feedLine(PaperSummary()))
    }

    func testWhyItemsSayWhereTheWordsAre() {
        let why = PaperWhyItem(predicate: "cited-in", text: nil, target: "alpha-project", snippet: "x", highlightStart: 0,
                               highlightEnd: 1, file: "REFERENCES.md", heading: "Retrieval", edited: "2026-09-01",
                               kind: "assistant", episode: "ep_1", start: 0, end: 1, stale: false)
        XCTAssertEqual(PaperCardText.label(why), "Cited in alpha-project")
        XCTAssertEqual(PaperCardText.whereLine(why), "REFERENCES.md › Retrieval · edited 2026-09-01 · written by an agent")
        XCTAssertEqual(PaperCardText.contextHeading(source: "arxiv", asOf: "2026-09-23"), "Context (from arXiv, as of 2026-09-23)")
        XCTAssertEqual(PaperCardText.contextHeading(source: "crossref", asOf: nil), "Context (from Crossref)")
    }

    func testAPaperRowDecodesAndIsFoundByAuthorArxivIdAndDoi() throws {
        let paper = try item(#", "kind": "paper", "paper": {"authors": ["Ada Example"], "arxivId": "2401.00001", "doi": "10.9999/alpha.2024"}"#)
        XCTAssertTrue(paper.isPaper)
        XCTAssertTrue(FeedViewModel.matches(paper, query: "ada"))
        XCTAssertTrue(FeedViewModel.matches(paper, query: "2401.00001"))
        XCTAssertTrue(FeedViewModel.matches(paper, query: "10.9999"))
        XCTAssertFalse(FeedViewModel.matches(paper, query: "zebra"))
        let plain = try item()
        XCTAssertFalse(plain.isPaper)
        XCTAssertNil(plain.paper)
        XCTAssertTrue(FeedViewModel.matches(plain, query: "alpha"))
    }

    func testTheDetailAndTheMediaBlockDecode() throws {
        let json = """
        {"entityId": "media-arxiv-2401-00001", "title": "Paper Alpha", "authors": ["Ada Example"], "sections": ["Retrieval"],
         "why": [{"predicate": "saved-because", "text": "the architecture", "snippet": "- [Paper Alpha] — the architecture",
                  "highlightStart": 18, "highlightEnd": 34, "file": "REFERENCES.md", "heading": "Retrieval",
                  "edited": "2026-09-01", "kind": "user", "episode": "ep_2026-09-01_001", "start": 40, "end": 56,
                  "stale": false}],
         "agentOnly": false, "context": "We study.", "contextSource": "arxiv", "contextAsOf": "2026-09-23",
         "absUrl": "https://arxiv.org/abs/2401.00001"}
        """
        let detail = try JSONDecoder().decode(PaperDetail.self, from: Data(json.utf8))
        XCTAssertEqual(detail.why.first?.id, "saved-because|ep_2026-09-01_001|40")
        let block = try JSONDecoder().decode(MediaBlock.self, from: Data(#"{"url": "https://arxiv.org/abs/2401.00001", "mediaType": "url", "kind": "paper"}"#.utf8))
        XCTAssertTrue(block.isPaper)
        let older = try JSONDecoder().decode(MediaBlock.self, from: Data(#"{"url": "https://example.com", "mediaType": "url"}"#.utf8))
        XCTAssertFalse(older.isPaper)
    }
}
```

and in `IntegrationsViewTests.swift` the `("notes", .filesAndImports)` pair becomes `.notesAndFiles`
(it is in the patch in Step 4). Run: `cd <worktree>/app/CicadaApp && swift build --build-tests 2>&1 | tail -5`
→ fails (unknown types).

- [ ] **Step 2: the paper models and card.** `Sources/CicadaApp/Models/Paper.swift`:

```swift
import Foundation

/// G133 — what a Feed row needs to show a paper's byline and to be found by
/// author, arXiv id or DOI (R7 §5.2). Optional everywhere: a non-paper row and
/// an older backend carry none of it.
struct PaperSummary: Codable, Equatable, Hashable {
    var authors: [String]
    var arxivId: String?
    var doi: String?
    var published: String?
    var venue: String?

    enum CodingKeys: String, CodingKey { case authors, arxivId, doi, published, venue }

    init(authors: [String] = [], arxivId: String? = nil, doi: String? = nil, published: String? = nil,
         venue: String? = nil) {
        self.authors = authors; self.arxivId = arxivId; self.doi = doi; self.published = published; self.venue = venue
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        authors = try c.decodeIfPresent([String].self, forKey: .authors) ?? []
        arxivId = try c.decodeIfPresent(String.self, forKey: .arxivId)
        doi = try c.decodeIfPresent(String.self, forKey: .doi)
        published = try c.decodeIfPresent(String.self, forKey: .published)
        venue = try c.decodeIfPresent(String.self, forKey: .venue)
    }
}

/// One personal-tier reason a paper is in memory, as a span into the person's
/// own file (G118 / G121): the snippet, where the words sit in it, the file,
/// the heading above, and the file's date.
struct PaperWhyItem: Codable, Equatable, Identifiable {
    var predicate: String
    var text: String?
    var target: String?
    var snippet: String
    var highlightStart: Int
    var highlightEnd: Int
    var file: String?
    var heading: String?
    var edited: String?
    var kind: String
    var episode: String
    var start: Int
    var end: Int
    var stale: Bool

    var id: String { "\(predicate)|\(episode)|\(start)" }
}

/// `GET /entities/{id}/paper` — the card's two tiers (G121): why, then context.
struct PaperDetail: Codable, Equatable {
    var entityId: String
    var title: String
    var authors: [String]
    var venue: String?
    var published: String?
    var arxivId: String?
    var doi: String?
    var absUrl: String?
    var doiUrl: String?
    var sections: [String]
    var why: [PaperWhyItem]
    var agentOnly: Bool
    var context: String?
    var contextSource: String?
    var contextAsOf: String?
}
```

`Sources/CicadaApp/Views/Graph/PaperCard.swift` — R-LS28: the quote is
`CicadaTheme.font(size: 13, design: .serif).italic()` until M2 brings `quoteFont`:

```swift
import AppKit
import SwiftUI

/// Every sentence the paper card and the Feed row say, as pure functions — so a
/// reviewer reads the rule, and `PaperCardTests` pins it.
enum PaperCardText {
    /// "Ada Example, Bob Example · Journal of Examples · 2024" — three authors
    /// at most, then "et al.".
    static func byline(authors: [String], venue: String?, published: String?) -> String {
        var parts: [String] = []
        if !authors.isEmpty {
            parts.append(authors.count > 3 ? authors.prefix(3).joined(separator: ", ") + " et al."
                                           : authors.joined(separator: ", "))
        }
        if let venue, !venue.isEmpty { parts.append(venue) }
        if let year = published?.prefix(4), year.count == 4 { parts.append(String(year)) }
        return parts.joined(separator: " · ")
    }

    /// The Feed row's short form: "Ada Example et al. · 2024".
    static func feedLine(_ paper: PaperSummary) -> String? {
        var parts: [String] = []
        if let first = paper.authors.first { parts.append(paper.authors.count > 1 ? "\(first) et al." : first) }
        if let year = paper.published?.prefix(4), year.count == 4 { parts.append(String(year)) }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// "Why you saved it", "Cited in alpha-project", "Filed under Retrieval".
    static func label(_ item: PaperWhyItem) -> String {
        switch item.predicate {
        case "saved-because": "Why you saved it"
        case "cited-in": "Cited in \(item.target ?? "your project")"
        case "about": "Filed under \(item.target ?? item.heading ?? "a topic")"
        default: item.predicate
        }
    }

    /// "REFERENCES.md › Retrieval · edited 2026-09-01" — file, heading, date.
    static func whereLine(_ item: PaperWhyItem) -> String {
        var place = item.file ?? "a note"
        if let heading = item.heading, !heading.isEmpty { place += " › \(heading)" }
        if let edited = item.edited { place += " · edited \(edited)" }
        if item.kind == "assistant" { place += " · written by an agent" }
        return place
    }

    static func contextHeading(source: String?, asOf: String?) -> String {
        let from = source == "crossref" ? "Crossref" : "arXiv"
        guard let asOf else { return "Context (from \(from))" }
        return "Context (from \(from), as of \(asOf))"
    }

    static let agentOnly = "Found by an agent's research sweep — not cited in your own notes."
    static let noWhy = "Nothing you wrote cites this paper right now."
    static let noContext = "Details from arXiv haven't been fetched yet — they arrive with the next sync."
}

/// G133 / G121 — a paper page leads with why it is in the person's memory,
/// each reason a quote from their own file with where it sits, and puts the
/// fetched abstract underneath as dated context. Replaces the link preview
/// for a paper: the card never loads arxiv.org itself (R-LS19).
struct PaperCard: View {
    let detail: PaperDetail

    /// R-LS28 — New York italic for a provenance quote; the Meadow `quoteFont`
    /// replaces this when M1 lands (the M2 pass).
    private var quote: Font { CicadaTheme.font(size: 13, design: .serif).italic() }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            let byline = PaperCardText.byline(authors: detail.authors, venue: detail.venue, published: detail.published)
            if !byline.isEmpty {
                Text(byline)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                if let abs = detail.absUrl, let url = URL(string: abs) {
                    Button("Open on arXiv") { NSWorkspace.shared.open(url) }.buttonStyle(.bordered)
                }
                if let doi = detail.doiUrl, let url = URL(string: doi) {
                    Button("Open DOI") { NSWorkspace.shared.open(url) }.buttonStyle(.bordered)
                }
            }

            Text("Why it's in your memory")
                .font(CicadaTheme.font(size: 13, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            if detail.agentOnly {
                Text(PaperCardText.agentOnly)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.warning)
            }
            if detail.why.isEmpty {
                Text(PaperCardText.noWhy)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            ForEach(detail.why) { item in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(PaperCardText.label(item))
                        .font(CicadaTheme.font(size: 11, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textSecondary)
                    Text(highlighted(item))
                        .font(quote)
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(PaperCardText.whereLine(item))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                .padding(CicadaTheme.spacingSM)
                .background(RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.surface))
            }

            Divider().background(CicadaTheme.border)
            Text(PaperCardText.contextHeading(source: detail.contextSource, asOf: detail.contextAsOf))
                .font(CicadaTheme.font(size: 13, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(detail.context ?? PaperCardText.noContext)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(detail.context == nil ? CicadaTheme.textTertiary : CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// The cited words bold inside their sentence; a stale span shows the
    /// sentence plainly rather than highlighting words that may have moved (G118 R2).
    private func highlighted(_ item: PaperWhyItem) -> AttributedString {
        var text = AttributedString(item.snippet)
        // The server's offsets count Unicode scalars (Python `str` indices), so
        // the highlight is placed on the scalar view, not on grapheme clusters.
        let scalars = text.unicodeScalars
        guard !item.stale, item.highlightStart >= 0, item.highlightStart < item.highlightEnd,
              item.highlightEnd <= scalars.count else { return text }
        let lower = scalars.index(scalars.startIndex, offsetBy: item.highlightStart)
        let upper = scalars.index(scalars.startIndex, offsetBy: item.highlightEnd)
        text[lower..<upper].inlinePresentationIntent = .stronglyEmphasized
        return text
    }
}
```

In `Services/APIClient.swift`, `MediaFeedItem` gains two fields — after `let durationS: Int?`:

```swift
    /// G133 — `paper` for a paper page, with its byline; `nil` on every other
    /// row and from an older backend.
    let kind: String?
    let paper: PaperSummary?
```

its `CodingKeys` gain `case kind, paper` (after `case provider, durationS`), its `init(from:)` ends with

```swift
        kind = try c.decodeIfPresent(String.self, forKey: .kind)
        paper = try c.decodeIfPresent(PaperSummary.self, forKey: .paper)
    }

    var isPaper: Bool { kind == "paper" }
```

and, directly after Task 6's `postWisprFlow`:

```swift
    /// `GET /entities/{id}/paper` — the paper card's two tiers (G133 / G121).
    func fetchPaperDetail(id: String) async throws -> PaperDetail {
        try await get("/entities/\(encodedID(id))/paper")
    }
```

- [ ] **Step 3: the Integrations rows.** `Sources/CicadaApp/Views/Settings/LocalSourceRows.swift`:

```swift
import AppKit
import SwiftUI

/// Every sentence the local-source rows say, as pure functions (`LocalSourcesSurfaceTests`).
/// Plain and friendly (the owner's rule for app copy): no jargon, no prices,
/// every number through `UsageFormat.count`.
enum LocalSourceRowText {
    static func folderLine(_ channel: SourceChannel, onThisMac: Bool) -> String {
        onThisMac ? IntegrationRowState.line(channel) : LocalSourceCopy.folderMissing
    }

    static func wisprLine(_ channel: SourceChannel?, settings: WisprFlowSettings) -> String {
        guard settings.enabled else { return "Your meetings and notes from Wispr Flow on this Mac." }
        guard let channel else { return "On — the first sync is on its way" }
        return IntegrationRowState.line(channel)
    }

    /// "Found 12 notes · 3 written by an agent · 1,200 papers".
    static func previewSummary(_ r: FolderSyncResult, locale: Locale = .autoupdatingCurrent) -> String {
        let files = r.filesNew + r.filesChanged + r.filesUnchanged
        var parts = ["\(UsageFormat.count(files, locale: locale)) \(files == 1 ? "note" : "notes")"]
        if r.agentFiles > 0 { parts.append("\(UsageFormat.count(r.agentFiles, locale: locale)) written by an agent") }
        if r.papersFound > 0 {
            parts.append("\(UsageFormat.count(r.papersFound, locale: locale)) \(r.papersFound == 1 ? "paper" : "papers")")
        }
        return "Found " + parts.joined(separator: " · ")
    }

    /// How much of it Sleep will read — a count, never a price (the 2026-09-03 ruling).
    static func sleepLine(_ r: FolderSyncResult, locale: Locale = .autoupdatingCurrent) -> String {
        guard r.stage1Passes > 0 else { return "Nothing here for Sleep to read yet — an agent's notes are kept, not read." }
        let n = UsageFormat.count(r.stage1Passes, locale: locale)
        return "Sleep will read your own notes in about \(n) \(r.stage1Passes == 1 ? "step" : "steps")."
    }

    /// "archive/**, drafts/**" or one per line → a clean list.
    static func list(_ text: String) -> [String] {
        text.split(whereSeparator: { $0 == "," || $0 == "\n" })
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }
}

/// A folder the person picked, waiting for the add sheet.
struct PickedFolder: Identifiable {
    let url: URL
    var id: String { url.path }
}

/// G133 — one watched folder in Settings → Integrations → Notes & files.
struct FolderChannelRow: View {
    let channel: SourceChannel
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var showManage = false

    private var folder: FolderRegistration? { localSources.folders.first { $0.channelId == channel.id } }

    var body: some View {
        let onThisMac = folder.map { localSources.isOnThisMac($0) } ?? false
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: CicadaTheme.spacingMD) {
                LogoImage.platformTile(name: "", size: 28, systemFallback: OriginIconography.symbol(for: "folder"))
                VStack(alignment: .leading, spacing: 2) {
                    Text(channel.label)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(LocalSourceRowText.folderLine(channel, onThisMac: onThisMac))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(channel.lastError != nil ? CicadaTheme.danger : CicadaTheme.textSecondary)
                }
                Spacer()
                if let folder {
                    Button("Sync now") { Task { await localSources.syncNow(folder) } }
                        .buttonStyle(.bordered)
                        .disabled(!onThisMac || localSources.syncing.contains(channel.id))
                    Button("Manage") { showManage = true }
                        .buttonStyle(.bordered)
                }
            }
            .popover(isPresented: $showManage, arrowEdge: .trailing) {
                if let folder {
                    FolderManagePanel(folder: folder)
                        .padding(CicadaTheme.spacingLG)
                        .frame(width: 340)
                }
            }
            if let folder, let error = localSources.folderErrors[folder.id] {
                Text(error)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
    }
}

/// "Add a folder" and "Obsidian vault" — the same flow: pick, name, look inside, watch.
struct AddFolderRow: View {
    let title: String
    let blurb: String
    let bundleId: String?
    let symbol: String
    let panelMessage: String
    @State private var picked: PickedFolder?

    static let obsidianBundleId = "md.obsidian"
    static var obsidianInstalled: Bool {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: obsidianBundleId) != nil
    }

    static var folder: AddFolderRow {
        AddFolderRow(title: "Add a folder of notes",
                     blurb: "Markdown notes, plans, reading lists — edits reach your memory on their own.",
                     bundleId: nil, symbol: "folder.badge.plus", panelMessage: "Choose a folder of notes to keep in memory")
    }

    static var obsidian: AddFolderRow {
        AddFolderRow(title: "Obsidian vault",
                     blurb: "A vault is a folder of notes — pick it and Cicada keeps up with your edits.",
                     bundleId: obsidianBundleId, symbol: OriginIconography.symbol(for: "obsidian"),
                     panelMessage: "Choose your Obsidian vault")
    }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            LogoImage.platformTile(name: "", bundleId: bundleId, size: 28, systemFallback: symbol)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(CicadaTheme.font(size: 13, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(blurb)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            Spacer()
            Button("Choose…") { pick() }
                .buttonStyle(.bordered)
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
        .sheet(item: $picked) { picked in
            AddFolderSheet(url: picked.url) { self.picked = nil }
        }
    }

    private func pick() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = panelMessage
        panel.prompt = "Choose"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        picked = PickedFolder(url: url)
    }
}

/// Name it, say which project it is, say which parts an agent wrote, look
/// inside (counts only), then start watching.
struct AddFolderSheet: View {
    let url: URL
    let onDone: () -> Void
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var label: String
    @State private var projectName: String
    @State private var agentGlobs = "archive/**"
    @State private var folder: FolderRegistration?
    @State private var preview: FolderSyncResult?
    @State private var busy = false
    @State private var message: String?

    init(url: URL, onDone: @escaping () -> Void) {
        self.url = url
        self.onDone = onDone
        _label = State(initialValue: url.lastPathComponent)
        _projectName = State(initialValue: url.lastPathComponent)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("Add a folder")
                .font(CicadaTheme.font(size: 17, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(url.path)
                .font(CicadaTheme.font(size: 11, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.middle)
            TextField("Name", text: $label)
            TextField("Which project is this?", text: $projectName)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                TextField("Parts written by an agent", text: $agentGlobs)
                Text("Research an agent wrote for you is kept and searchable, but never counted as your own words.")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .disabled(folder != nil)
            if let preview {
                Text(LocalSourceRowText.previewSummary(preview))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(LocalSourceRowText.sleepLine(preview))
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            if let message {
                Text(message)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.danger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Button("Cancel") { Task { await cancel() } }
                Spacer()
                if preview == nil {
                    Button("Look inside") { Task { await look() } }
                        .buttonStyle(.borderedProminent)
                } else {
                    Button("Start watching") { Task { await start() } }
                        .buttonStyle(.borderedProminent)
                }
            }
        }
        .textFieldStyle(.roundedBorder)
        .padding(CicadaTheme.spacingXL)
        .frame(width: 440)
        .disabled(busy)
    }

    /// Registers WITHOUT a project name (`projectName: ""`): the preview needs a
    /// folder id, but a person who looks inside and then cancels must not leave
    /// a new `project` page behind (R-LS13 creates one only on their say-so).
    private func look() async {
        busy = true
        defer { busy = false }
        do {
            let registered = try await localSources.addFolder(
                url: url, label: label, projectName: "", agentGlobs: LocalSourceRowText.list(agentGlobs))
            folder = registered
            preview = try await localSources.preview(registered, root: url)
            message = nil
        } catch {
            message = AddSourceSheet.friendlyError(error)
        }
    }

    /// "Start watching" is the say-so: the same `POST /sources/folders` again is
    /// an upsert on (device, path) (R-LS9) — same id — that now anchors the
    /// project by name (R-LS13) and takes any edit to the name fields.
    private func start() async {
        guard folder != nil else { return }
        busy = true
        defer { busy = false }
        do {
            let anchored = try await localSources.addFolder(
                url: url, label: label, projectName: projectName, agentGlobs: LocalSourceRowText.list(agentGlobs))
            await localSources.startWatching(anchored)
            onDone()
        } catch {
            message = AddSourceSheet.friendlyError(error)
        }
    }

    private func cancel() async {
        if let folder { try? await localSources.removeFolder(folder) }
        onDone()
    }
}

/// Which parts an agent wrote, and "Stop watching" (which keeps what was learned).
struct FolderManagePanel: View {
    let folder: FolderRegistration
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var globs: String
    @State private var confirmStop = false
    @State private var busy = false
    @State private var message: String?

    init(folder: FolderRegistration) {
        self.folder = folder
        _globs = State(initialValue: folder.agentGlobs.joined(separator: ", "))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(folder.label)
                .font(CicadaTheme.font(size: 15, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text(folder.path)
                .font(CicadaTheme.font(size: 11, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.middle)
            TextField("Parts written by an agent", text: $globs)
                .textFieldStyle(.roundedBorder)
            Text("Changing this re-reads the folder so every file is credited to the right author.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let message {
                Text(message).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            }
            HStack {
                Button("Stop watching", role: .destructive) { confirmStop = true }
                Spacer()
                Button("Save") {
                    Task {
                        busy = true
                        defer { busy = false }
                        do {
                            try await localSources.updateAgentGlobs(folder, globs: LocalSourceRowText.list(globs))
                            message = nil
                        } catch {
                            message = AddSourceSheet.friendlyError(error)
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .disabled(busy)
        .confirmationDialog("Stop watching \(folder.label)?", isPresented: $confirmStop) {
            Button("Stop watching", role: .destructive) {
                Task { try? await localSources.removeFolder(folder) }
            }
        } message: {
            Text("Everything Cicada already learned from this folder stays in your memory.")
        }
    }
}

/// G134 — Wispr Flow in Settings → Integrations → Voice & meetings.
struct WisprFlowRow: View {
    let channel: SourceChannel?
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var showPanel = false

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: CicadaTheme.spacingMD) {
                LogoImage.platformTile(name: OriginIconography.logoName(for: "wispr-flow") ?? "",
                                       bundleId: OriginIconography.appBundleId(for: "wispr-flow"),
                                       size: 28, systemFallback: OriginIconography.symbol(for: "wispr-flow"))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Wispr Flow")
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                    Text(LocalSourceRowText.wisprLine(channel, settings: localSources.wisprSettings))
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(channel?.lastError != nil ? CicadaTheme.danger : CicadaTheme.textSecondary)
                }
                Spacer()
                if localSources.wisprSettings.enabled {
                    Button("Sync now") { Task { await localSources.syncWisprNow() } }
                        .buttonStyle(.bordered)
                        .disabled(localSources.syncing.contains(LocalSourceWatcher.wisprChannel))
                    Button("Manage") { showPanel = true }
                        .buttonStyle(.bordered)
                } else {
                    Button("Connect") { showPanel = true }
                        .buttonStyle(.bordered)
                }
            }
            .popover(isPresented: $showPanel, arrowEdge: .trailing) {
                WisprFlowPanel()
                    .padding(CicadaTheme.spacingLG)
                    .frame(width: 340)
            }
            if let error = localSources.wisprError, case .notReadable = error {
                FullDiskAccessHint(error: error)
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
    }
}

/// Turn Wispr Flow on or off; dictation is opt-in; "your name in meetings" is
/// the only way a speaker is ever counted as the person (R-LS22, R-LS23).
struct WisprFlowPanel: View {
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var includeDictation = false
    @State private var names = ""
    @State private var busy = false
    @State private var message: String?

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("Wispr Flow")
                .font(CicadaTheme.font(size: 15, weight: .semibold))
                .foregroundStyle(CicadaTheme.textPrimary)
            Text("Your meetings — with who said what — and your Scratchpad notes come in on their own.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Toggle("Also include my dictation history", isOn: $includeDictation)
            Text("Everything you've dictated into other apps, one entry per day. Password managers are always left out.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            TextField("Your name in meetings", text: $names)
                .textFieldStyle(.roundedBorder)
            Text("So your own words are credited to you — everyone else's stay theirs.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let message {
                Text(message).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
            }
            HStack {
                if localSources.wisprSettings.enabled {
                    Button("Turn off", role: .destructive) { save(enabled: false) }
                }
                Spacer()
                Button(localSources.wisprSettings.enabled ? "Save" : "Turn on") { save(enabled: true) }
                    .buttonStyle(.borderedProminent)
            }
        }
        .disabled(busy)
        .onAppear {
            includeDictation = localSources.wisprSettings.includeDictation
            names = localSources.wisprSettings.ownerSpeakerNames.joined(separator: ", ")
        }
    }

    private func save(enabled: Bool) {
        Task {
            busy = true
            defer { busy = false }
            do {
                try await localSources.setWispr(WisprFlowSettings(
                    enabled: enabled, includeDictation: includeDictation,
                    ownerSpeakerNames: LocalSourceRowText.list(names)))
                message = nil
            } catch {
                message = AddSourceSheet.friendlyError(error)
            }
        }
    }
}
```

- [ ] **Step 4: the edits to existing files.** The patch below applies cleanly to `f2d31ef` both
  before and after Task 6 (checked with `git apply --check`); it touches no file Task 6 edits.
  Extract it (it is the plan's only ```` ```diff ```` block) and apply:
  `cd <worktree> && awk '/^```diff$/{f=1;next} f&&/^```$/{exit} f' <plan> > <scratch>/t7.patch && git apply --check <scratch>/t7.patch && git apply <scratch>/t7.patch`.
  If a hunk no longer applies, make the same change by hand — every hunk is small and self-describing:

```diff
diff --git a/app/CicadaApp/Sources/CicadaApp/Models/IntegrationCategory.swift b/app/CicadaApp/Sources/CicadaApp/Models/IntegrationCategory.swift
--- a/app/CicadaApp/Sources/CicadaApp/Models/IntegrationCategory.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Models/IntegrationCategory.swift
@@ -17,7 +17,7 @@ import Foundation
 /// a newer backend degrades to "somewhere on the page" instead of taking
 /// the app down.
 enum IntegrationCategory: String, CaseIterable, Identifiable {
-    case chatAndAgents, browsers, socialAndSaved, feedsAndCalendars, messaging, filesAndImports
+    case chatAndAgents, browsers, socialAndSaved, feedsAndCalendars, messaging, notesAndFiles, voiceAndMeetings, filesAndImports
 
     var id: String { rawValue }
 
@@ -32,6 +32,9 @@ enum IntegrationCategory: String, CaseIterable, Identifiable {
         case .socialAndSaved: "Social & saved"
         case .feedsAndCalendars: "Feeds & calendars"
         case .messaging: "Messaging"
+        // G133 / G134 (R-LS25): where notes live and where voices are captured.
+        case .notesAndFiles: "Notes & files"
+        case .voiceAndMeetings: "Voice & meetings"
         case .filesAndImports: "Files & imports"
         }
     }
@@ -48,10 +51,16 @@ enum IntegrationCategory: String, CaseIterable, Identifiable {
             return .feedsAndCalendars
         case "telegram":
             return .messaging
-        case "notes", "files":
+        // R-LS25: Apple Notes moves beside the watched folders — both are notes.
+        case "notes":
+            return .notesAndFiles
+        case LocalSourceWatcher.wisprChannel:
+            return .voiceAndMeetings
+        case "files":
             return .filesAndImports
         default:
-            return .filesAndImports
+            // `folder:<id>` rows are dynamic (one per watched folder, G133).
+            return channelId.hasPrefix("folder:") ? .notesAndFiles : .filesAndImports
         }
     }
 }
diff --git a/app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift b/app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift
--- a/app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Models/SourceOverview.swift
@@ -3,10 +3,11 @@ import Foundation
 /// The kinds `api/services/source_overview.KIND_ORDER` declares, plus a
 /// fallback so an unknown kind from a newer backend never drops the grid.
 enum SourceKind: String, Codable, CaseIterable {
-    case harness, browser, social, feed, messaging, `import`, unknown
+    case harness, browser, social, feed, messaging, voice, `import`, unknown
 
-    /// Grid order = the backend's `KIND_ORDER`; `unknown` sorts last.
-    static let order: [SourceKind] = [.harness, .browser, .social, .feed, .messaging, .import, .unknown]
+    /// Grid order = the backend's `KIND_ORDER`; `unknown` sorts last. `voice`
+    /// (G134) holds note-takers: meetings and dictation.
+    static let order: [SourceKind] = [.harness, .browser, .social, .feed, .messaging, .voice, .import, .unknown]
 }
 
 /// Mirror of `api/models/schemas.py::SourceOverview` (G124). Every field but
@@ -277,6 +278,7 @@ enum SourceSections {
         .social: "SOCIAL & SAVED",
         .feed: "FEEDS & CALENDARS",
         .messaging: "MESSAGING",
+        .voice: "VOICE & MEETINGS",
         .import: "FILES & IMPORTS",
         .unknown: "OTHER",
     ]
diff --git a/app/CicadaApp/Sources/CicadaApp/Models/Entity.swift b/app/CicadaApp/Sources/CicadaApp/Models/Entity.swift
--- a/app/CicadaApp/Sources/CicadaApp/Models/Entity.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Models/Entity.swift
@@ -565,6 +565,8 @@ struct MediaBlock: Codable, Equatable {
     /// page's `media:` block) can see which provider answered. Never trusted
     /// over the url: `mediaType` taught that lesson (R-V1).
     var provider: String?
+    /// G133 — `paper` for a paper page (`papers.KIND`); nil for every other media page.
+    var kind: String?
     /// The clip's length in seconds, as the provider's oEmbed reported it.
     /// **The one thing a url cannot tell you**, which is why it is stored at
     /// all. Absent means absent — nothing renders, never an estimate (R17).
@@ -572,14 +574,14 @@ struct MediaBlock: Codable, Equatable {
 
     enum CodingKeys: String, CodingKey {
         case url, mediaType, site, channel, thumbnail, savedAt, urlHash
-        case provider, durationS
+        case provider, durationS, kind
     }
 
     init(
         url: String, mediaType: String, site: String? = nil,
         channel: String? = nil, thumbnail: String? = nil,
         savedAt: String? = nil, urlHash: String? = nil,
-        provider: String? = nil, durationS: Int? = nil
+        provider: String? = nil, durationS: Int? = nil, kind: String? = nil
     ) {
         self.url = url
         self.mediaType = mediaType
@@ -590,6 +592,7 @@ struct MediaBlock: Codable, Equatable {
         self.urlHash = urlHash
         self.provider = provider
         self.durationS = durationS
+        self.kind = kind
     }
 
     init(from decoder: Decoder) throws {
@@ -607,8 +610,11 @@ struct MediaBlock: Codable, Equatable {
         // without either key.
         provider = try c.decodeIfPresent(String.self, forKey: .provider)
         durationS = try c.decodeIfPresent(Int.self, forKey: .durationS)
+        kind = try c.decodeIfPresent(String.self, forKey: .kind)
     }
 
+    var isPaper: Bool { kind == "paper" }
+
     /// True when there's a real url to preview. A media entity whose frontmatter
     /// couldn't be parsed (empty url) shouldn't render a broken preview.
     var hasURL: Bool { !url.isEmpty }
diff --git a/app/CicadaApp/Sources/CicadaApp/ViewModels/FeedViewModel.swift b/app/CicadaApp/Sources/CicadaApp/ViewModels/FeedViewModel.swift
--- a/app/CicadaApp/Sources/CicadaApp/ViewModels/FeedViewModel.swift
+++ b/app/CicadaApp/Sources/CicadaApp/ViewModels/FeedViewModel.swift
@@ -59,12 +59,21 @@ final class FeedViewModel {
 
     var filteredItems: [MediaFeedItem] {
         guard !searchText.isEmpty else { return items }
-        let q = searchText.lowercased()
-        return items.filter {
-            $0.title.lowercased().contains(q)
-                || ($0.site?.lowercased().contains(q) ?? false)
-                || $0.tags.contains(where: { $0.lowercased().contains(q) })
+        return items.filter { Self.matches($0, query: searchText) }
+    }
+
+    /// Title, site and tags — and for a paper its authors, arXiv id and DOI
+    /// (G133, R7 §5.2): a substring over the snapshot, so still no network.
+    nonisolated static func matches(_ item: MediaFeedItem, query: String) -> Bool {
+        let q = query.lowercased()
+        if item.title.lowercased().contains(q) || (item.site?.lowercased().contains(q) ?? false)
+            || item.tags.contains(where: { $0.lowercased().contains(q) }) {
+            return true
         }
+        guard let paper = item.paper else { return false }
+        return paper.authors.contains { $0.lowercased().contains(q) }
+            || (paper.arxivId?.lowercased().contains(q) ?? false)
+            || (paper.doi?.lowercased().contains(q) ?? false)
     }
 
     func load() async {
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginIconography.swift b/app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginIconography.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginIconography.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Capture/OriginIconography.swift
@@ -35,6 +35,8 @@ enum OriginIconography {
         "telegram", "rss", "calendar", "share-sheet", "bookmark", "saved-link",
         "instagram-saved", "youtube-playlist", "pinterest", "reddit-saved", "reddit",
         "x-bookmarks", "x", "linkedin-saved", "tiktok-saved", "tiktok-history", "unknown",
+        // G133 / G134 — a watched folder's episodes and Wispr Flow's.
+        "folder", "wispr-flow",
     ]
 
     static func label(for origin: String) -> String {
@@ -87,6 +89,11 @@ enum OriginIconography {
         // spelled once, above: a second copy here was unreachable (Swift takes
         // the first match) and told the next editor a lie about where to edit.
         case "gemini-cli": "Gemini CLI"
+        case "folder": "Folder"
+        case "wispr-flow": "Wispr Flow"
+        // Not an origin a writer stamps: the mark of the "Obsidian vault" row
+        // (a vault is a folder, so its episodes are `folder`).
+        case "obsidian": "Obsidian"
         case "unknown": "Unknown"
         // Defensive aliases only — see the type doc above.
         case "reddit": "Reddit"
@@ -122,6 +129,9 @@ enum OriginIconography {
         // shadowed, and `terminal` is its live answer — narrowing the case,
         // not deleting it, is what keeps that true.
         case "gemini-cli": "terminal"
+        case "folder": "folder"
+        case "wispr-flow": "waveform"
+        case "obsidian": "doc.text"
         case "unknown": "questionmark.circle"
         default: "tray"
         }
@@ -215,6 +225,10 @@ enum OriginIconography {
         case "safari-bookmark", "safari-tab": "com.apple.Safari"
         case "chrome-bookmark": "com.google.Chrome"
         case "apple-notes": "com.apple.Notes"
+        // R-LS27 — Cicada reads Wispr Flow's own files (so the app is here) and
+        // offers the Obsidian row only when Obsidian is installed.
+        case "wispr-flow": "com.electron.wispr-flow"
+        case "obsidian": "md.obsidian"
         default: nil
         }
     }
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Capture/ConnectedChannelRow.swift b/app/CicadaApp/Sources/CicadaApp/Views/Capture/ConnectedChannelRow.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Capture/ConnectedChannelRow.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Capture/ConnectedChannelRow.swift
@@ -116,7 +116,7 @@ struct ConnectedChannelRow: View {
                             if let watchState = watcher.state(for: channel.id) {
                                 BrowserStatusLight(state: watchState,
                                                    error: watcher.error(for: channel.id),
-                                                   compact: true)
+                                                   compact: true, channelId: channel.id)
                             }
                         }
                             .lineLimit(1)
@@ -200,7 +200,8 @@ struct ConnectedChannelRow: View {
     /// routing them through the origin map would silently change `files` from
     /// `link` to `bookmark.fill` for no gain.
     static func icon(for id: String) -> String {
-        switch id {
+        if id.hasPrefix("folder:") { return "folder" }
+        return switch id {
         case "rss": "dot.radiowaves.up.forward"
         case "calendar": "calendar"
         case "chrome-bookmarks": "globe"
@@ -212,6 +213,7 @@ struct ConnectedChannelRow: View {
         case "pinterest": "pin.fill"
         case "reddit": "bubble.left.and.text.bubble.right.fill"
         case "x": "x.circle"
+        case "wispr-flow": "waveform"
         default: "tray"
         }
     }
@@ -245,7 +247,9 @@ struct ConnectedChannelRow: View {
     /// `ChannelMarkTests.testNoChannelFallsThroughToTheGenericTray` is what
     /// makes the missing row loud instead of silent.
     static func origin(forChannel id: String) -> String {
-        switch id {
+        // G133: every `folder:<id>` row's episodes carry the one `folder` origin.
+        if id.hasPrefix("folder:") { return "folder" }
+        return switch id {
         case "chat-export:claude": "claude-export"
         case "chat-export:chatgpt": "chatgpt-export"
         case "chrome-bookmarks": "chrome-bookmark"
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceDisplayName.swift b/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceDisplayName.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceDisplayName.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceDisplayName.swift
@@ -56,6 +56,7 @@ enum SourceDisplayName {
         "telegram": "Telegram",
         "notes": "Apple Notes",
         "files": "Files & links",
+        "wispr-flow": "Wispr Flow",
         // The open families a live bank produces (A2/A4).
         "origin:unknown": "Unattributed",
         "origin:bookmark": "Saved links",
@@ -68,7 +69,11 @@ enum SourceDisplayName {
     /// because `String.capitalized` has no idea "rss" is not a word.
     private static let acronyms: Set<String> = ["rss", "url", "mcp", "api", "id", "ics", "pdf", "csv"]
 
-    static func of(_ source: SourceOverview) -> String { of(id: source.id) }
+    /// A watched folder's name is the person's own label for it (G133) — the id
+    /// is a slug plus a hash, never a name to show.
+    static func of(_ source: SourceOverview) -> String {
+        source.id.hasPrefix("folder:") ? source.label : of(id: source.id)
+    }
 
     static func of(id: String) -> String {
         if let pinned = table[id] { return pinned }
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceBlurb.swift b/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceBlurb.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceBlurb.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceBlurb.swift
@@ -10,7 +10,9 @@ import Foundation
 /// sentence rather than a generic placeholder.
 enum SourceBlurb {
     static func text(for source: SourceOverview) -> String {
-        byId[source.id] ?? fallback(kind: source.kind, label: source.label)
+        // G133: one row per watched folder, named by the person.
+        if source.id.hasPrefix("folder:") { return "Notes in \(source.label), kept in step as you edit them." }
+        return byId[source.id] ?? fallback(kind: source.kind, label: source.label)
     }
 
     private static func fallback(kind: SourceKind, label: String) -> String {
@@ -25,6 +27,8 @@ enum SourceBlurb {
             return "New items from \(label), the feeds and calendars you subscribed to."
         case .messaging:
             return "Messages you send to \(label), as notes."
+        case .voice:
+            return "Meetings and notes from \(label), with who said what."
         case .import, .unknown:
             return "Links or files you added through \(label)."
         }
@@ -56,5 +60,6 @@ enum SourceBlurb {
         "telegram": "Messages you send the bot, as notes.",
         "notes": "Notes you write in Apple Notes.",
         "files": "Links you pasted or files you dropped.",
+        "wispr-flow": "Your Wispr Flow meetings — with who said what — and Scratchpad notes.",
     ]
 }
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Sources/BrowserStatusLight.swift b/app/CicadaApp/Sources/CicadaApp/Views/Sources/BrowserStatusLight.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Sources/BrowserStatusLight.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Sources/BrowserStatusLight.swift
@@ -13,6 +13,10 @@ struct BrowserStatusLight: View {
     let error: BrowserFileError?
     /// Compact hides the sentence and keeps the dot — for a dense list row.
     var compact: Bool = false
+    /// R-LS26 — which channel wears the light, so a watched folder or Wispr Flow
+    /// explains itself in its own words instead of a browser's. `nil` keeps the
+    /// browser sentences.
+    var channelId: String? = nil
 
     var body: some View {
         VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
@@ -28,7 +32,7 @@ struct BrowserStatusLight: View {
                 }
             }
             if !compact {
-                Text(Self.explanation(for: state))
+                Text(Self.explanation(for: state, channelId: channelId))
                     .font(CicadaTheme.captionFont)
                     .foregroundStyle(CicadaTheme.textSecondary)
                     .fixedSize(horizontal: false, vertical: true)
@@ -38,8 +42,8 @@ struct BrowserStatusLight: View {
             }
         }
         .accessibilityElement(children: .combine)
-        .accessibilityLabel("\(Self.title(for: state)). \(Self.explanation(for: state))")
-        .help(Self.explanation(for: state))
+        .accessibilityLabel("\(Self.title(for: state)). \(Self.explanation(for: state, channelId: channelId))")
+        .help(Self.explanation(for: state, channelId: channelId))
     }
 
     static func color(for state: BrowserWatchState) -> Color {
@@ -80,4 +84,30 @@ struct BrowserStatusLight: View {
             "This browser isn't installed on this Mac, or has no bookmarks yet."
         }
     }
+
+    /// The local sources' own sentences (G133 / G134); every other channel keeps
+    /// the browser's.
+    static func explanation(for state: BrowserWatchState, channelId: String?) -> String {
+        if let channelId, channelId.hasPrefix("folder:") {
+            switch state {
+            case .watching: return "Edits in this folder reach the Sleep queue within a few seconds."
+            case .syncing: return "Reading what changed."
+            case .stale: return "This folder changed and Cicada hasn't caught up. Sync now."
+            case .blocked: return "Cicada isn't allowed to read this folder."
+            case .failed: return "The last sync didn't finish. Try Sync now."
+            case .absent: return "This folder isn't on this Mac."
+            }
+        }
+        if channelId == LocalSourceWatcher.wisprChannel {
+            switch state {
+            case .watching: return "New meetings and notes arrive within a few minutes."
+            case .syncing: return "Reading what's new in Wispr Flow."
+            case .stale: return "Wispr Flow has something new that Cicada hasn't read yet."
+            case .blocked: return "Cicada isn't allowed to read Wispr Flow's data."
+            case .failed: return "The last sync didn't finish. Try Sync now."
+            case .absent: return "Wispr Flow isn't on this Mac."
+            }
+        }
+        return explanation(for: state)
+    }
 }
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceCardGrid.swift b/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceCardGrid.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceCardGrid.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceCardGrid.swift
@@ -306,7 +306,7 @@ struct SourceCard: View {
             // the liveness tone, never by `connected` — "has ever fed memory"
             // is why the row exists (G124 R2), not what it is doing.
             if let watchState {
-                BrowserStatusLight(state: watchState, error: watchError, compact: true)
+                BrowserStatusLight(state: watchState, error: watchError, compact: true, channelId: source.channelId)
             } else {
                 Circle().fill(liveness.tone.color).frame(width: 7, height: 7)
             }
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceHeaderCard.swift b/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceHeaderCard.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceHeaderCard.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Sources/SourceHeaderCard.swift
@@ -78,7 +78,7 @@ struct SourceHeaderCard: View {
                 // identical fix panels one screen apart is the second encoding
                 // R-S12 rules out.
                 if let watchState {
-                    BrowserStatusLight(state: watchState, error: nil, compact: true)
+                    BrowserStatusLight(state: watchState, error: nil, compact: true, channelId: source.channelId)
                 } else {
                     Circle().fill(liveness.tone.color).frame(width: 7, height: 7)
                 }
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelSourceView.swift b/app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelSourceView.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelSourceView.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Sources/ChannelSourceView.swift
@@ -67,7 +67,7 @@ struct ChannelSourceView: View {
                 // channel with no watch keeps the plain connected/not line,
                 // because a light nobody updates is worse than no light.
                 if let watchState = watcher.state(for: channel.id) {
-                    BrowserStatusLight(state: watchState, error: watcher.error(for: channel.id))
+                    BrowserStatusLight(state: watchState, error: watcher.error(for: channel.id), channelId: channel.id)
                 } else {
                     Text(channel.connected ? "Connected" : "Not connected")
                         .font(CicadaTheme.headingFont).foregroundStyle(CicadaTheme.textPrimary)
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Settings/IntegrationsView.swift b/app/CicadaApp/Sources/CicadaApp/Views/Settings/IntegrationsView.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Settings/IntegrationsView.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Settings/IntegrationsView.swift
@@ -19,6 +19,7 @@ struct IntegrationsView: View {
 
     @Environment(Store.self) private var store
     @Environment(AppRouter.self) private var router
+    @Environment(LocalSourceWatcher.self) private var localSources
 
     /// One row per export-only social platform: no persisted backend
     /// channel exists for these (`AddSourceTile.channelIds` is `[]` for all
@@ -97,8 +98,7 @@ struct IntegrationsView: View {
                 case .loaded:
                     ForEach(IntegrationCategory.allCases) { category in
                         let rows = channels.filter { IntegrationCategory.of(channelId: $0.id) == category }
-                        let extraRows = category == .chatAndAgents ? harnessRows.count
-                            : category == .socialAndSaved ? Self.exportOnlyTiles.count : 0
+                        let extraRows = extraRowCount(category, rows: rows)
                         // A section renders only when it has evidence (mirrors
                         // `SourceSections.group`'s own rule) — an empty category
                         // reads as a broken page, not a completeness signal.
@@ -113,6 +113,23 @@ struct IntegrationsView: View {
         .background(CicadaTheme.background)
     }
 
+    /// Rows a category renders beyond its channels — the informational harness
+    /// rows, the export-only platforms, the "Add a folder" rows (G133) and the
+    /// Wispr Flow row once Wispr Flow is on this Mac (G134).
+    private func extraRowCount(_ category: IntegrationCategory, rows: [SourceChannel]) -> Int {
+        switch category {
+        case .chatAndAgents: harnessRows.count
+        case .socialAndSaved: Self.exportOnlyTiles.count
+        case .notesAndFiles: 1
+        case .voiceAndMeetings: showsWispr(rows) ? 1 : 0
+        default: 0
+        }
+    }
+
+    private func showsWispr(_ rows: [SourceChannel]) -> Bool {
+        localSources.wisprInstalled || rows.contains { $0.id == LocalSourceWatcher.wisprChannel }
+    }
+
     /// Three grey rows under a spinner rather than a bare spinner: the page's
     /// own shape, so the layout does not jump when the real categories land.
     private var loadingPlaceholder: some View {
@@ -155,7 +172,18 @@ struct IntegrationsView: View {
                     }
                 }
                 ForEach(rows) { channel in
-                    IntegrationChannelRow(channel: channel)
+                    if channel.id.hasPrefix("folder:") {
+                        FolderChannelRow(channel: channel)
+                    } else if channel.id != LocalSourceWatcher.wisprChannel {
+                        IntegrationChannelRow(channel: channel)
+                    }
+                }
+                if category == .notesAndFiles {
+                    AddFolderRow.folder
+                    if AddFolderRow.obsidianInstalled { AddFolderRow.obsidian }
+                }
+                if category == .voiceAndMeetings, showsWispr(rows) {
+                    WisprFlowRow(channel: rows.first { $0.id == LocalSourceWatcher.wisprChannel })
                 }
                 if category == .socialAndSaved {
                     ForEach(Self.exportOnlyTiles) { tile in
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift b/app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift
@@ -48,6 +48,8 @@ struct EntityDetailCard: View {
     // Fact sources (G61) — "where to look this fact up" refresh references.
     // Loaded on every entity (unlike repos/location, not gated by entity type).
     @State private var sources: [EntitySource] = []
+    /// G133 — a paper page's two tiers, fetched once per open.
+    @State private var paperDetail: PaperDetail?
     @State private var newSourceRef = ""
 
     // History tab (G68 §2.10). `entity.history` is empty BOTH before the full
@@ -329,8 +331,13 @@ struct EntityDetailCard: View {
                 .help("Copy markdown")
             }
 
-            // G11: rich media preview above the body for `media`-type entities.
-            if entity.type == .media, let media = entity.media, media.hasURL {
+            // G133: a paper leads with why it is in memory, then the dated
+            // abstract — and never loads arxiv.org in a preview (R-LS19).
+            if let paperDetail {
+                PaperCard(detail: paperDetail)
+                Divider().background(CicadaTheme.border)
+            } else if entity.type == .media, let media = entity.media, media.hasURL, !media.isPaper {
+                // G11: rich media preview above the body for `media`-type entities.
                 MediaPreview(model: MediaPreviewModel(
                     block: media,
                     title: entity.name,
@@ -373,6 +380,7 @@ struct EntityDetailCard: View {
             locationListing = nil
             repoContexts = []
             sources = []
+            paperDetail = nil
             newSourceRef = ""
             pendingDecayClass = nil
             activeEntityId = entity.id
@@ -381,6 +389,9 @@ struct EntityDetailCard: View {
             loadingCommits = []
             diffErrors = []
             sources = (try? await APIClient.shared.fetchEntitySources(entityId: entity.id)) ?? []
+            if entity.media?.isPaper == true {
+                paperDetail = try? await APIClient.shared.fetchPaperDetail(id: entity.id)
+            }
             // §5.7 — the card opened on the graph-node stub, whose
             // `markdownContent` is the server's short `summary` (already
             // rendered above, so there is never an empty card). Upgrade it to
diff --git a/app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift b/app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift
--- a/app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift
+++ b/app/CicadaApp/Sources/CicadaApp/Views/Feed/FeedView.swift
@@ -293,7 +293,9 @@ struct FeedRow: View {
                         .lineLimit(1)
 
                     HStack(spacing: CicadaTheme.spacingSM) {
-                        Text(item.mediaType)
+                        // G133: a paper says so, and shows its byline where a
+                        // link shows its site.
+                        Text(item.isPaper ? "paper" : item.mediaType)
                             .font(CicadaTheme.font(size: 10, design: .monospaced))
                             .foregroundStyle(CicadaTheme.mediaPink)
                             .padding(.horizontal, 6)
@@ -315,7 +317,12 @@ struct FeedRow: View {
                                 .clipShape(Capsule())
                         }
 
-                        if let site = item.site, !site.isEmpty {
+                        if let byline = item.paper.flatMap(PaperCardText.feedLine) {
+                            Text(byline)
+                                .font(CicadaTheme.font(size: 10))
+                                .foregroundStyle(CicadaTheme.textTertiary)
+                                .lineLimit(1)
+                        } else if let site = item.site, !site.isEmpty {
                             Text(site)
                                 .font(CicadaTheme.font(size: 10))
                                 .foregroundStyle(CicadaTheme.textTertiary)
diff --git a/app/CicadaApp/Tests/CicadaAppTests/IntegrationsViewTests.swift b/app/CicadaApp/Tests/CicadaAppTests/IntegrationsViewTests.swift
--- a/app/CicadaApp/Tests/CicadaAppTests/IntegrationsViewTests.swift
+++ b/app/CicadaApp/Tests/CicadaAppTests/IntegrationsViewTests.swift
@@ -24,7 +24,8 @@ final class IntegrationsViewTests: XCTestCase {
         let ids: [(String, IntegrationCategory)] = [
             ("chat-export:claude", .chatAndAgents), ("chat-export:chatgpt", .chatAndAgents),
             ("chrome-bookmarks", .browsers), ("safari-bookmarks", .browsers), ("safari-tabs", .browsers),
-            ("notes", .filesAndImports),
+            // R-LS25: Apple Notes sits beside the watched folders now.
+            ("notes", .notesAndFiles),
             ("rss", .feedsAndCalendars), ("calendar", .feedsAndCalendars),
             ("pinterest", .socialAndSaved), ("reddit", .socialAndSaved), ("x", .socialAndSaved),
             ("telegram", .messaging), ("files", .filesAndImports),
```

  What it does, so a reviewer can check intent against diff:
  - `IntegrationCategory`: two cases, `notes` → Notes & files, `wispr-flow` → Voice & meetings,
    `folder:<id>` → Notes & files (R-LS25).
  - `SourceKind.voice` sorts before `import`, titled VOICE & MEETINGS (mirrors Task 5's `KIND_ORDER`).
  - `MediaBlock.kind` + `isPaper`; the Feed row reads "paper" and shows `PaperCardText.feedLine`
    where a link shows its site; `FeedViewModel.matches` also searches a paper's authors, arXiv id
    and DOI (`nonisolated static`, so tests call it off the main actor).
  - `OriginIconography`: `folder` and `wispr-flow` are known origins; labels, symbols, and the
    installed-app bundle ids for `wispr-flow` and `obsidian` (R-LS27). `ConnectedChannelRow.icon/origin`
    check the `folder:` prefix first, then `return switch id {` (a bare `if … return` before an
    implicit-return `switch` compiles to an unused-literal warning and the wrong value).
  - `SourceDisplayName.of(_:)` names a folder card by its label; `SourceBlurb` gains the `.voice`
    fallback (the switch must stay exhaustive), the folder sentence and the `wispr-flow` blurb.
  - `BrowserStatusLight.channelId` + `explanation(for:channelId:)`; the four light call sites pass it
    (R-LS26).
  - `IntegrationsView`: `extraRowCount` (Notes & files always has its "Add a folder" row, Voice &
    meetings shows only when Wispr Flow is installed or already connected), folder rows render as
    `FolderChannelRow`, the generic `wispr-flow` row is replaced by `WisprFlowRow`.
  - `EntityDetailCard`: a paper renders `PaperCard` instead of `MediaPreview` — never an arxiv.org
    web preview (R-LS19) — fetched in the existing `.task(id: entity.id)` after the reset.

- [ ] **Step 5: marks (R-LS27).** No PNG, no manifest or `LOGOS.md` change. Confirm the ledger is
  untouched and still consistent: `cd <worktree> && scripts/fetch-logos.sh --check` (offline, read-only)
  and `cd <worktree> && api/.venv/bin/python -m pytest api/tests/test_logo_manifest.py -q -p no:cacheprovider` → pass; and
  `cd <worktree>/app/CicadaApp && swift test --filter LogoAssetTests` → pass (no orphaned asset, nothing new to claim).
- [ ] **Step 6: Verify** — `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` (no new warnings),
  `swift test --filter "LocalSourcesSurfaceTests|PaperCardTests|IntegrationsViewTests|FontLiteralLintTests|CountLiteralLintTests|LogoAssetTests" 2>&1 | tail -20`,
  the full `swift test 2>&1 | tail -20` → **≥ 1039 executed, 0 failures**, and the graph net
  `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js 2>&1 | tail -8` → 0 failures.
- [ ] **Step 7: Commit** — `feat(G133/G134): Notes & files and Voice & meetings in Integrations; the paper card leads with why it is yours (R-LS25 … R-LS28)`.

---

### Task 8: Docs — G133, G134, the cross-references, the rails where the next reader looks

**Files:**
- Modify: `docs/goals/memory-evolution.md` — two new rows after `G132` (`:694`); one dated sentence
  appended to the body cell of `G2` (`:470`), `G20` (`:488`), `G43` (`:532`), `G95` (`:657`),
  `G121` (`:683`)
- Modify: `docs/goals/TODO.md` — "Where things stand" (after `:40`), Shipped → Capture & connectors
  (`:205`), Wave D item 16 (`:443`)
- Modify: `CLAUDE.md` — the Awake rails (`:147`, after the G114 bullet), the evidence-kind sentence
  (`:278-279`), optional frontmatter keys (after the `owner: true` bullet), the Integrations
  paragraph (`:467-468`), the router count (`:536`), Reaching the outside world (before the ToS rail)

**Interfaces:** none — prose only. **Privacy rule:** placeholders only; the two owner quotes are his
own ideas (the intended voice); no folder name, paper title, meeting title, speaker name or count
read from the owner's data appears anywhere.

- [ ] **Step 1: apply the edits.** Every anchor is asserted to match exactly once, so a drifted line
  fails loudly instead of landing in the wrong place. Extract the script below and run it from the
  worktree root (it prints `docs updated`):
  `cd <worktree> && awk '/^"""Task 8 docs edits/{f=1} f&&/^```$/{exit} f' <plan> > <scratch>/t8_docs.py && python3 <scratch>/t8_docs.py`

```python
"""Task 8 docs edits (G133/G134). Run once from the worktree root; every anchor must match exactly once."""
import pathlib

BACKLOG = pathlib.Path("docs/goals/memory-evolution.md")
TODO = pathlib.Path("docs/goals/TODO.md")
CLAUDE = pathlib.Path("CLAUDE.md")


def once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, (old[:90], text.count(old))
    return text.replace(old, new)


def row_index(lines: list[str], gid: str) -> int:
    hits = [i for i, line in enumerate(lines) if line.startswith(f"| {gid} |")]
    assert len(hits) == 1, (gid, hits)
    return hits[0]


def append_to_row(lines: list[str], gid: str, sentence: str) -> None:
    """Add a sentence to the end of a row's body cell, before its status cell."""
    i = row_index(lines, gid)
    head, sep, status = lines[i].rpartition(" | ")
    assert sep and status.endswith("|"), gid
    lines[i] = f"{head} {sentence}{sep}{status}"


G133 = (
    "| G133 | **A watched folder, and papers with why they matter to you** (Rodrigo 2026-09-23: \"in this "
    "project i have a bunch of md files explaining ideas, referencing papers, etc. I'd like for this to just "
    "live in cicada as well. with papers with summaries and why they are relevant to me\") | **The gap.** A "
    "folder of the owner's own markdown — ideas, plans, reading lists — had no way in except pasting it into "
    "a chat, and a paper reached memory only as a bare bookmark with a web preview: no authors, no abstract, "
    "nothing saying why it was kept. **What shipped (round 3 Track L; plan "
    "`docs/superpowers/plans/2026-09-23-local-sources.md`, rulings R-LS1 … R-LS30).** (1) *One stager for "
    "every source-keyed writer:* the G20 stager moved to `api/services/episode_staging.py` — an "
    "`EpisodeDraft` keyed by `source_id`, the hash over the scrubbed body, an edit rewritten in place with "
    "`processed: false`, a rename kept by content hash, a deletion tombstoned (`source_deleted_at`), never "
    "unlinked; a multi-turn source records `turn_index: [[offset, ts, speaker], …]` (that name because "
    "`turns:` is already the transcript's integer count). (2) *The app reads the folder, the backend parses "
    "bytes:* a security-scoped bookmark, FSEvents and an mtime+size+sha manifest post only what changed, "
    "with relative paths; the backend never opens the folder. One episode per file, split on H2 only past "
    "48,000 characters. Files under an agent glob (`archive/**`) land `processed: true, processed_by: "
    "parser`, `evidence_kind: assistant` — an agent's research sweep is never the owner's words (R-F2) — "
    "and flipping a glob re-queues them. The folder anchors a `project` page by name, which learns "
    "`paths: [{path, device}]`. (3) *Papers with no LLM:* arXiv ids and DOIs are parsed deterministically "
    "into `media` pages with `media.kind: paper` — no new type, the G2 closure held — keyed "
    "`media-arxiv-<id>` / `media-doi-<hash>`, an existing bookmark upgraded in place. The owner's own line "
    "about a paper becomes a `saved-because` claim with a span into his file, and its section an `about` "
    "link through the zero-LLM matcher: that span *is* the why-it-matters. Details come from the arXiv API "
    "(≤ 50 ids a request, ≥ 3 s apart) and Crossref (public pool, no email sent), never from arxiv.org "
    "pages, under the ToS rail; the abstract is a world-tier `describes` claim (`external`, authored by "
    "`cicada`) shown *under* the personal tier (G121). A paper no file cites any more gets a G129-shaped "
    "`removal` item, never a silent delete. Built and tested on synthetic fixtures only; the owner's folder "
    "is ingested after merge and its counts are not recorded here (privacy rule). **Open:** per-folder "
    "filtering of the source detail page (every folder row shares the `folder` origin); no backfill of "
    "`turn_index` on older episodes (readers accept its absence). | ✅ round 3 |"
)

G134 = (
    "| G134 | **Note-takers as a source, Wispr Flow first — meetings keep their speakers, dictation only when "
    "asked** (Rodrigo 2026-09-23: \"make sure to support note taker apps like wisprflow or others.\") | "
    "**The gap.** G95 named meetings the one intake class the pipeline was not built for: every episode was "
    "single-observer, so a pasted transcript would have credited every line to the owner. **What shipped "
    "(round 3 Track L, R-LS21 … R-LS24).** The app opens Wispr Flow's local SQLite read-only (one "
    "transaction, a busy timeout) through a column whitelist held on **both** sides — audio, screenshots, "
    "accessibility text, pasted text and raw ASR are never selected, and the tests plant canaries in every "
    "one — and posts a projection; the backend parses. Meetings and notes by default; dictation history is "
    "opt-in, grouped per UTC day and merged server-side through `turn_index`, with password-manager apps "
    "denied. An utterance is a `speaker:<label>:` line and a new evidence kind, `speaker`; it is `user` "
    "evidence **only** when its label is one of the owner's listed names. Wispr's own summary, notes and "
    "to-dos are `assistant:` lines (a model wrote them), and a to-do becomes a `committed-to` claim on the "
    "owner page at `observer: agent`, 0.5. Secrets and one-time codes are scrubbed on **every** episode "
    "writer by one module, `episode_scrub.py`, pinned by a test that fails for any writer minting an id "
    "without it (R-N3). Settings → Integrations gains **Voice & meetings** and the Sources grid VOICE & "
    "MEETINGS. **Open, on purpose:** to-dos into the Inbox (needs a `todo` inbox kind — the G60/G113 "
    "surfaces); Granola, Fireflies, Otter and Notion adapters (they reuse the `speaker:` seam; Wispr Flow's "
    "own Granola import covers a migrated person today); a consent surface for recording other people "
    "(G95). | ✅ round 3 |"
)

lines = BACKLOG.read_text().split("\n")
append_to_row(lines, "G2", "**2026-09-23 (G133):** papers arrived as `media` pages with `media.kind: paper` "
              "and claims, not a new type — the closed set held again.")
append_to_row(lines, "G20", "**2026-09-23 (G133/G134):** the stager moved to `api/services/episode_staging.py` "
              "(`EpisodeDraft`, `stage`) and every source-keyed writer now uses it — folder files, Wispr Flow "
              "meetings and notes; `conversations._stage_episodes` is a compatibility wrapper.")
append_to_row(lines, "G43", "**2026-09-23:** still open — G134 shipped note-takers (Wispr Flow) through the "
              "shared stager and the VOICE & MEETINGS section a voice memo would join; transcription stays here.")
append_to_row(lines, "G95", "**2026-09-23 (G134):** the first multi-party intake shipped — Wispr Flow meetings "
              "as `speaker:<label>:` turns with a per-turn `turn_index`, evidence kind `speaker`, `user` only "
              "by the owner's listed names; consent and the other note-takers remain here.")
append_to_row(lines, "G121", "**2026-09-23 (G133):** the paper card is the first surface with both tiers — "
              "\"Why it's in your memory\" (spans in the owner's own notes) above \"Context (from arXiv, as of "
              "<date>)\" (an `external` `describes` claim authored by `cicada`).")
i = row_index(lines, "G132")
lines[i + 1:i + 1] = [G133, G134]
BACKLOG.write_text("\n".join(lines))

todo = TODO.read_text()
todo = once(
    todo,
    "green. (`working-method.md` carries the standing notes on the order-dependent case.)\n",
    "green. (`working-method.md` carries the standing notes on the order-dependent case.)\n\n"
    "**Round 3 · Track L — local sources (G133 + G134).** A watched folder the app reads and the backend\n"
    "parses (one episode per file through the shared `episode_staging` stager; agent-written globs never\n"
    "credited to the owner), papers as `media` pages with `media.kind: paper` (arXiv/Crossref details under\n"
    "the connector gate, why-it-matters from the owner's own spans, the abstract a dated world-tier cache),\n"
    "and Wispr Flow meetings and notes with their speakers (dictation opt-in). One scrub on every episode\n"
    "writer. Baselines with it: backend **≥ 2322 passed**, Swift **≥ 1039 executed** — replace these with\n"
    "the measured numbers when the PR merges.\n",
)
todo = once(
    todo,
    "16. **G95** meetings & human↔human conversations — M/L\n",
    "16. **G95** meetings & human↔human conversations — M/L — *first slice shipped as G134 (Wispr Flow\n"
    "    meetings with speakers); a consent surface and the other note-takers remain*\n",
)
todo = once(
    todo,
    "updated in place, Sleep-queue source marks (`OriginMark`)\n",
    "updated in place, Sleep-queue source marks (`OriginMark`) · **G133 watched folders + papers** and\n"
    "**G134 Wispr Flow** (round 3 Track L)\n",
)
TODO.write_text(todo)

doc = CLAUDE.read_text()
doc = once(doc, "Four rails hold across all of them:", "Six rails hold across all of them:")
doc = once(
    doc,
    "  consolidation.\n\n**Conversation identity (G48).**",
    "  consolidation.\n"
    "- **Every writer scrubs, and every source-keyed writer stages through one module** (G133/G134,\n"
    "  R-N3). `api/services/episode_scrub.py` — secrets, long base64 runs, one-time codes anchored on a\n"
    "  connector word — runs before every writer's hash and write, and `test_episode_writers_scrub.py`\n"
    "  fails for any module that mints an episode id without it. `api/services/episode_staging.py` is the\n"
    "  G20 stager they share: an `EpisodeDraft` keyed by `source_id`, the hash over the scrubbed body, an\n"
    "  edit rewritten in place with `processed: false`, a rename kept by content hash, a deletion\n"
    "  tombstoned (`source_deleted_at`) and never unlinked. A multi-turn source records\n"
    "  `turn_index: [[offset, ts, speaker], …]` (omitted above 4,000 rows; `turns:` stays the transcript's\n"
    "  integer count).\n"
    "- **A local source is read by the app and parsed by the backend** (G133/G134). A watched folder:\n"
    "  security-scoped bookmark, FSEvents, an mtime+size+sha manifest, bytes posted with relative paths to\n"
    "  `POST /sources/folders/{id}/sync`; files under an agent glob land as `evidence_kind: assistant`,\n"
    "  already processed, so an agent's sweep is never the owner's words. Wispr Flow: its SQLite opened\n"
    "  read-only by the app through a column whitelist (never audio, screenshots, accessibility or pasted\n"
    "  text); meetings and notes by default, dictation only when the person turns it on. A meeting line is\n"
    "  `speaker:<label>:` and counts as `user` evidence only when its label is one of the owner's listed\n"
    "  names.\n"
    "\n**Conversation identity (G48).**",
)
doc = once(
    doc,
    "`kind` is\n`user` | `assistant` | `page` | `reasoning` (the contributor's own inference: `start == end == -1`,\n"
    "never a faked span). One module, `api/services/evidence.py`, does the work for every writer: locate",
    "`kind` is\n`user` | `assistant` | `page` | `speaker` (a meeting participant who is not the owner, G134) |\n"
    "`reasoning` (the contributor's own inference: `start == end == -1`, never a faked span); an episode's\n"
    "`evidence_kind: user|assistant` (a folder's authorship rule, R-F2) overrides the line markers.\n"
    "One module, `api/services/evidence.py`, does the work for every writer: locate",
)
doc = once(
    doc,
    "  field is that resolved value.\n",
    "  field is that resolved value.\n"
    "- `paths:` (G133) — on a `project` page a watched folder anchors: `[{path, device}]`, where that\n"
    "  folder lives on which Mac. For display and relink only; the backend never opens it.\n"
    "- `media.kind: paper` + `paper:` (G133) — a paper page: `arxiv_id`, `doi`, `authors`, `published`,\n"
    "  `venue`, `sections`, and `metadata_status` once a lookup failed. The ids are the identity\n"
    "  (`media-arxiv-<id>` / `media-doi-<hash>`); the abstract is a `describes` claim from\n"
    "  `external:arxiv` or `external:crossref`, a dated cache shown under the personal tier (G121).\n"
    "- On an episode (G133/G134): `turn_index`, `evidence_kind`, `source_deleted_at`, and a section's\n"
    "  `content_sha` — see the Awake rails.\n",
)
doc = once(
    doc,
    "behind the Feed's `+`. Both read the same `channel_registry`, so a channel never drifts between the\n"
    "two surfaces.",
    "behind the Feed's `+`. Both read the same `channel_registry`, so a channel never drifts between the\n"
    "two surfaces. Round 3 added **Notes & files** (Apple Notes, every watched folder, *Add a folder* and,\n"
    "when Obsidian is installed, *Obsidian vault*) and **Voice & meetings** (Wispr Flow once it is on this\n"
    "Mac) — both standing connections, so both live here; their marks are the installed apps' own icons.",
)
doc = once(doc, "20 routers mounted in `api/main.py`", "26 routers mounted in `api/main.py`")
doc = once(
    doc,
    "**The ToS rail — this one is not negotiable.**",
    "**Paper details (G133) ride the first gate, not a fourth.** The unattended Sleep-tail lookup is behind\n"
    "`CICADA_ALLOW_CONNECTOR_FETCH`; a folder sync the person asked for (`?resolve=true`) is not. Only two\n"
    "APIs are ever called — `export.arxiv.org/api/query` (≤ 50 ids a request, ≥ 3 s apart) and\n"
    "`api.crossref.org/works/{doi}` (public pool; no email is ever sent) — at the rail's 4 s / ≤ 512 KB;\n"
    "arxiv.org pages and PDFs are never fetched, and a 403/429 stops that API for the run.\n\n"
    "**The ToS rail — this one is not negotiable.**",
)
CLAUDE.write_text(doc)
print("docs updated")
```

- [ ] **Step 2: read the result, not the script.** `cd <worktree> && git diff --stat` shows exactly the
  three files. `git diff CLAUDE.md` reads as prose in the file's own voice (the Awake list now says
  *Six rails*); the two new backlog rows render as table rows (no raw `|` outside the four cell
  separators — `grep -c '^| G13[34] |' docs/goals/memory-evolution.md` → 2); and
  `grep -nE 'alpha-project|bob-example' CLAUDE.md docs/goals/*.md` → nothing (fixture names stay in
  tests).
- [ ] **Step 3: the router count is true.** `cd <worktree> && grep -c "include_router" api/main.py` → 26
  (25 on this base plus `local_sources`; the old "20" was already stale).
- [ ] **Step 4: Commit** — `docs(G133/G134): local sources — the rows, the cross-references, the rails in CLAUDE.md`.

---

## Not in scope

Named so a reviewer does not read an absence as an oversight. Each is an explicit exclusion in the
brief or a ruling above.

- **Granola, Fireflies, Otter and Notion adapters** — G134's row names them; they reuse the
  `speaker:` seam and the stager. **Voice Memos** (G43) and any transcription. **OCR** of PDFs or
  images in a folder (binary files are skipped by the reader's globs).
- **Any LLM at capture time** — nothing in the new modules imports an engine; `about` uses only the
  zero-LLM matcher (R-LS16), and the LLM relating of a paper to the graph stays with `link_recon` on
  the Sleep tail.
- **Reading the owner's real folder or real Wispr Flow data** by code, tests or agents. The
  orchestrator ingests them after merge.
- **To-dos into the Inbox** (R-LS24) — no `todo` inbox kind, no toggle; **a consent surface** for
  recording other people (G95).
- **A backfill** of `turn_index` or `evidence_kind` onto existing episodes, and **a re-scrub** of
  episodes written before this track — readers accept their absence; a re-scrub rewrites history
  the owner has not asked to rewrite.
- **`notes_sync` update-in-place** through the new stager — it gains the scrub only (R-LS6); moving
  Apple Notes onto `episode_staging.stage` is its own change with its own dedup migration.
- **`+`-sheet tiles** for a folder or Wispr Flow — both are standing connections, so they live in
  Integrations (the G126 rule); the Feed's `+` stays one-shot imports.
- **A Wispr Flow MCP pull** or any cloud API — only the local store the app reads.
- **A Crossref polite-pool `mailto`** — it would send an address off the machine; the public pool
  is enough at personal scale (R-LS18).
- **Per-folder filtering of a source's item list** — every folder row shares the `folder` origin,
  so the detail page lists all folders' episodes together (disclosed in G133's row).
- **A bundled PNG for Wispr Flow or Obsidian** (R-LS27) and **Meadow tokens** (`quoteFont` and the
  M2 swaps, R-LS28) — the Meadow track owns them.
- **G132 multi-device** — `paths: [{path, device}]` and the device-stamped folder ids leave room
  for it, and nothing here syncs across machines.

---

## Verification the orchestrator runs at the end

1. `cd <worktree> && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → **0
   failures**, **≥ 2322 passed** (2225 on this base + 97 new). If
   `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
   the only red, re-run it alone and report both results.
2. `cd <worktree>/app/CicadaApp && swift build 2>&1 | tail -5` → success with no new warnings;
   `swift test 2>&1 | tail -20` → **≥ 1039 executed, 0 failures** (1012 + 27 new);
   `cd <worktree> && node --test app/CicadaApp/Tests/graph/*.test.js` → 0 failures.
3. **Two guards that must be seen to fail.** (a) Add a throwaway `api/services/zz_writer.py` whose
   body is `from api.services.episode_ids import next_episode_id` plus a call to `next_episode_id(`
   → `pytest api/tests/test_episode_writers_scrub.py` must FAIL naming it; delete the file, green
   again. (b) Add `"audio"` to `WisprFlowColumns.meetings` → `swift test --filter WisprFlowReaderTests`
   must FAIL (`testTheWhitelistsNeverNameAForbiddenColumn` and the canary assertions); revert, green
   again. A guard that has never failed is not known to work.
4. **Live, synthetic first** (the orchestrator installs the app; never `swift run`): make a scratch
   folder with three notes (one under `archive/`), one citing `arXiv:2401.00001` and a
   `10.1234/example` DOI; Settings → Integrations → Notes & files → *Add a folder* → *Look inside*
   shows "Found 3 notes · 1 written by an agent · 2 papers" and the Sleep-steps line (first try
   *Cancel* once: no new `project` page and no folder row may remain — R-LS13); *Start
   watching* → the project page exists with `paths:`, and the Sources grid card says **Watching**; edit a note → the queue shows one
   updated episode within a few seconds, not a new one; rename it → still one; delete it → a
   tombstone, and a paper only it cited raises a `removal` item in the Inbox. Check dark and light,
   at 1.0× and 1.4×.
5. **The paper card:** open the paper's page — "Why it's in your memory" (the owner's own line,
   highlighted) sits above "Context (from arXiv, as of …)"; no arxiv.org web preview loads; before
   the details arrive the Context section says "Details from arXiv haven't been fetched yet …"
   instead of guessing. The Feed row reads "paper"
   with its byline, and the Feed search finds it by an author's surname, by the arXiv id and by the
   DOI.
6. **Then the real folder**, by the orchestrator only: register it, confirm the preview's agent
   count matches the globs chosen, start watching, and record **counts only** in the PR body.
7. **Wispr Flow, counts only, by the orchestrator:** with Wispr Flow installed, Voice & meetings
   shows its row wearing the installed app's icon; turning it on imports meetings and notes and
   **no dictation** (the dictation toggle is off by default); a meeting episode's utterances are
   `speaker:` lines except the owner's listed name; each `meetings/<uuid>` transcript folder name
   equals a `Meetings.id`, and timestamps land as aware UTC. With Full Disk Access denied, the row
   shows the Full Disk Access fix instead of a silent failure.
8. **Wire and surfaces:** `/sources/channels` and `/sources/overview` ETag recipe tests are
   unchanged (folders and Wispr settings fold into the existing `sources` component — R-LS29); no
   price, token count or `/consumption/*` read appears on any surface this PR touches.
9. **PR body must state:** the merge note in Global Constraints (Track O's `media` evidence kind —
   take the union; Track I calls `episode_staging.stage`), the three open questions (R-LS27 marks,
   R-LS18 Crossref public pool, R-LS20's reading of R-F1's deletion clause), and that every commit in
   the diff stages named files (no `git add -A`).

---

## Open questions (the owner's call; the plan proceeds on each default)

- **R-N4 asked for marks fetched through `scripts/fetch-logos.sh`; this plan ships the installed
  apps' own icons instead** (R-LS27). Obsidian's Commons SVG (CC BY 4.0) exists but its row never
  renders without the app, whose icon outranks a bundled PNG; Wispr Flow has only a third-party
  raster on Commons, which the SVG-only pipeline cannot take and whose licence is not the vendor's.
  Default: no PNG. The alternative, if the owner wants the fallback anyway, is one manifest entry for
  Obsidian (`commonsFile: "2023 Obsidian logo.svg"`, run `scripts/fetch-logos.sh --only obsidian`,
  map `logoName(for: "obsidian")`) — about fifteen minutes, no code risk.
- **R-F3 names Crossref's polite pool; this plan uses the public pool** (R-LS18). The polite pool is
  entered by sending a contact email on every request, and Cicada never sends the person's email
  off the machine. Default: public pool, ≤ 30 DOIs per Sleep cycle, ≥ 1 s apart. The alternative,
  if the owner wants the polite pool, is a `mailto` he supplies himself in Settings and stores in
  `~/.cicada/` (never the bank) — a small follow-up, not this track.
- **R-F1's "a deletion asks through the inbox"** is read as R-LS20 (a deleted file's episode is
  stamped and kept; the inbox asks about a *paper* no remaining file cites). Default: no inbox item
  per deleted file — an episode is history, and a `removal` item archives an entity, which an
  episode is not. The alternative (a "this note was deleted — forget what it taught?" item) needs a
  new inbox kind and an answer that retracts claims by episode, which is Track Q's retract work.
