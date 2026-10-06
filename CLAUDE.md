# CLAUDE.md

Guidance for Claude Code working in this repository.

**This file is the philosophy and the rails.** The backlog and the rulings live in [`docs/goals/`](docs/goals/) —
read it before proposing work — and each subsystem's full description lives in [`docs/architecture/`](docs/architecture/)
(see *Where the detail lives*).

---

## Project

**Cicada** — Author: Rodrigo Sagastegui.

The goal: **capture the human experience seamlessly, and make it something you can hold a
conversation over — with agents that can understand it, contribute to it, and draw their own
relations across it.**

Concretely, Cicada aims to span:

- **Every kind of media ingestion** — links, articles, papers, videos, images, bookmarks, RSS,
  files, saved collections exported from the platforms where they pile up.
- **Every conversation** — the ones with agents (MCP-native clients, plus imported ChatGPT/Claude
  exports), and, as recording becomes part of the workflow, **conversations with other people**:
  meetings ingested the same way, through the same source-agnostic pipeline.
- **The moving parts of a life** — projects, ideas, current interests, the things being decided and
  the things quietly going stale.

The design principle that follows: memory must be **legible to an agent without ceremony**. An
agent should be able to arrive, be told what Cicada is and how to use it, read the graph,
contribute beliefs with provenance, and leave the store better than it found it. The
markdown-and-git substrate, the claim layer, the author/session trailers and the MCP surface all
exist to make that true.

The architecture is biologically inspired: **Awake** = hippocampal encoding (fast, episodic capture,
no processing at capture time), **Sleep** = cortical consolidation (slow, semantic, batch), and
**temporal decay** = synaptic homeostasis (absence of mention is itself a signal). Episodic noise
gets compressed into a structured, versioned knowledge graph rather than accumulating as a
transcript pile.

### Why: the human-to-agent experience port

Cicada is the **port between a human's experience and the agents that will act on it** — the first
step toward capturing everything of a person's experience and their interactions with the world in
a form an agent can understand, so that, eventually, agents, humans and robots coexist on one
legible record of what happened and what it meant. Two papers frame the design, and every backlog
row should be readable against them.

**Silver & Sutton, *Welcome to the Era of Experience* (2025).** Their claim: the next generation of
agents will learn predominantly from *streams* of experience rather than snippets of human data,
grounded in an environment, with rewards from that environment and reasoning not confined to human
terms. Cicada's reading: **the person's life is the environment, and Cicada is the instrument that
turns it into a stream an agent can inhabit.** Four correspondences, each a design constraint:

1. **Streams, not sessions.** A conversation is a snippet; a life is a stream. Awake capture is the
   stream's intake, Sleep is what makes it more than a transcript pile, and decay is the stream's
   own clock — silence is data. Anything that fragments the stream (a resumed conversation
   consolidated twice, G104; capture that depends on a model choosing to call a tool, G105) is a
   defect against this, not a nicety.
2. **Observations *and* actions.** Every capture channel is an observation. Every agent write with
   provenance — a claim, a `Cicada-Author:` trailer, an inbox resolution — is an action on the
   shared record. The port is two-way or it is a diary.
3. **Grounded rewards.** When the person answers a nudge, overrules a claim, keeps or archives an
   entity, that is a reward signal *from the environment*. Cicada should treat these resolutions as
   the signal it learns from, not just as edits to apply (G113).
4. **Reasoning beyond prose.** The claim layer — typed predicates, bi-temporal validity, observer
   and trust — exists so an agent can reason over the record structurally. Prose is for humans;
   claims are the machine-legible half.

**Tang et al., *WikiSkill* (2026, arXiv:2608.27454).** Separating *raw experience* from a
*persistent wiki* from *executable skills* is what makes skill evolution work (the wiki is worth
+15 points to the skill proposer in ablation), and evolved skills **transfer across models and
model families**. Cicada holds the first two layers: `episodes/` is the raw layer, the
entity-plus-claim graph is the wiki. The third — compiling what the graph knows about *how this
person works* into portable, agent-loadable skills — is **G112**. The bar: **a skill compiled from
one person's experience should load into any harness on any plan, with Cicada being nothing more
than its provenance.**

**Portability is the point, not a feature.** The goal is other people running this on their own
plans and harnesses (G50 connections, G76 install, G92 onboarding). A hardcoded owner name, a path
that only exists on the author's machine, a bank that cannot be handed over intact — each is a bug
against the mission, not a polish item.

---

## Branches

- `main`: production/stable branch
- `dev`: active development branch — all work goes here first

PRs open against `dev`. **A release is a PR from `dev` to `main`, and merging it is the release** (TODO ruling 19,
2026-10-06): CI tags `VERSION` at the merge and publishes the GitHub Release. Nothing but a release reaches `main`.

---

## Backlog and handoff (`docs/goals/`)

**Read these before proposing work.** A proposal that duplicates a `G` row or re-opens a settled
ruling is wasted effort. Detail belongs in the backlog; state belongs in TODO.md. After finishing
work, update both.

- **[`memory-evolution.md`](docs/goals/memory-evolution.md) — the backlog.** One row per idea,
  `G<n>`, numbered in the order raised and never renumbered, so a `G` id is a permanent address:
  cite `G74a` in commits and PR bodies the way you would cite a ticket. A row carries the
  *reasoning* — the problem, the evidence (file:line, a measured number, a reproduction), and the
  design constraint any fix must respect. Triaged **APPLY** / **RESEARCH** / **DECIDE**; 💸 marks
  paid LLM spend. When you learn something that changes a row's argument, edit the row — never open
  a second one.
- **[`TODO.md`](docs/goals/TODO.md) — execution view + handoff.** Same work ordered by what to do
  next. Its header is written for an agent picking the project up cold: current state, open PRs,
  the verified live environment, and a "Pick up here" line. Above all it carries the **rulings** —
  decisions that cost real measurement, each with the evidence that settled it. **A ruling is
  binding.** Revisit one only on the trigger its row names, and only after reading why it was made:
  several were reached by disproving the obvious answer, so re-deriving them from first principles
  reliably gets them wrong.
- **[`working-method.md`](docs/goals/working-method.md) — how the work is run.** The bar a change
  clears (plan → critic → per-task implement+review → two-lens final review → verify yourself → PR
  to `dev`), the test baselines that are *not* failures, the rails that override convenience, and
  the paused queue with the reasoning for its order.

**Privacy rule (standing, 2026-09-02).** Nothing personal about the owner or anyone in their life
goes into `docs/goals/`, this file, a plan, a commit message, or a PR body: no names of other
people, employers, clients or companies from the bank; no episode or inbox titles; no quoted
conversation or claim text; no URLs, handles or contact details. The owner's own *thoughts and
ideas* are fine to quote — a row starting "Rodrigo 2026-09-01: …" carrying a design opinion is the
intended voice. When a row needs an example, use placeholders (`<surname-a>`, `alpha-project`,
`bob-example`) and say "real values redacted". **The repo is public; the bank is not, and the line
between them is this rule.**

---

## Repository Structure

`api/` FastAPI backend, `app/` SwiftUI macOS app, `mcp/` the MCP server, `memory/` the runtime bank
(gitignored), `docs/goals/` the backlog. Read the tree with `ls` — it is not duplicated here.

---

## Where the detail lives (read the doc for the area you touch)

This file carries the mission, the working rules and every **rail** in short form. The full, current description of
each subsystem — module names, wire shapes, routes, the app's views — lives in `docs/architecture/`, one file per area:

| Area | Doc |
|---|---|
| Capture (Awake), the Sleep cycle, the drain, entity promotion, temporal decay | [`docs/architecture/capture-and-sleep.md`](docs/architecture/capture-and-sleep.md) |
| Markdown + git storage, the entity schema, decay classes, claims and evidence, sources (G61), pictures and logos, backlogs, `_state.md` and the handshake, the derived indexes, the telemetry ledger, git trailers and commits | [`docs/architecture/storage.md`](docs/architecture/storage.md) |
| The MCP tools, recall, implicit recall, video watch, reading with the person's own agent | [`docs/architecture/mcp.md`](docs/architecture/mcp.md) |
| The companion app: shell, Settings, Home, onboarding, engines, integrations, agents, skills, Sources, Clusters, the Feed, Projects, the Sleep page, the find palette, the demo, brand marks, design direction D, the Reader | [`docs/architecture/app.md`](docs/architecture/app.md) |
| API auth, ETags and their client mappings, endpoint traps | [`docs/architecture/api.md`](docs/architecture/api.md) |
| The graph explorer, the entity card, the unified inbox, the Sleep trigger and schedule, conversation upload | [`docs/architecture/features.md`](docs/architecture/features.md) |
| The three network gates, the remote connector, the ToS rail, credentials, video | [`docs/architecture/network.md`](docs/architecture/network.md) |

**Keeping it this size.** A PR updates the area doc its change makes wrong, in the same PR. It touches this file only
when a *rail* changes (a new invariant, a ruling, a boundary), and then in one or two lines that point at the doc.
`api/tests/test_claude_md_size.py` fails above 60,000 characters and checks every doc linked above exists.

---

## The rails (binding — each is stated in full in its area doc)

### Capture (Awake)

- **No LLM at capture time** — capture is file I/O into `episodes/`; the pipeline is source-agnostic.
- **The app reads `~/Library`, the backend parses bytes.** The launchd backend has no Full Disk Access and never opens
  those paths, never stats a path a request names, never runs git in a declared repo; the app reads (browsers, Notes via
  its own `osascript`, Calendar, Contacts, Chrome tab groups, watched folders, Wispr Flow) and posts bytes. A browser is
  read only after the person turned it on. An unreadable file shows the exact fix in the app.
- **Capture never depends on a model calling a tool (G105).** Claude Code and Codex sessions are captured by the
  harness's own Stop hook; the backend reads a transcript only when it resolves under the harness root as
  `<session_id>.jsonl` within the size cap. Only the person's turns and the agent's final reply are kept, plus each agent
  turn's model and effort. **One episode per session** (G104). Cicada's own `claude -p` / `codex exec` spawns run with
  `CICADA_CAPTURE=off`. Recall is the same move (G149): the SessionStart/UserPromptSubmit hooks inject Cicada's note; a
  recalled note is never captured back as the person's words.
- **Transcripts under `~/.claude/` are never read anywhere else** — the MCP seam and resume only `isfile()` them.
- **One id rule** (`episode_ids`): max-suffix+1 per date, aware UTC timestamps; `processed_by` says who flipped it.
  A new episode never replaces a file (`create_episode`); dedup, edits and Sleep's revision-checked retirement share
  `episode_lock`, and every page write is atomic (audit K01/A01/A02, `capture-and-sleep.md`).
- **Every writer scrubs, every source-keyed writer stages through one module** (`episode_scrub`, `episode_staging`:
  hash over the scrubbed body, edits in place with `processed: false`, deletions tombstoned, never unlinked).
- **Capture never writes into a demo bank** (`demo_guard`, by `_bank.yaml`, never by name): every capture/sources
  POST/PUT answers 409; the Stop hook redirects to the real bank left most recently.

### Sleep

- **Five stages** (extract → resolve/dedup → conflicts/decay → patterns/skills → nudges + commit) plus an
  **engine-independent tail** on every exit path, in a clean-tree-guarded slot, each step committing only its own paths.
- **Consolidate reads everything** (rulings 13, 16): every run — the person's and a scheduled one — is a drain over the
  ids frozen at its start, in committed batches (default 25), so a stop loses at most the batch in progress. Decay and the
  page reads run once per drain. A plan limit is a pause, not a failure. **Ruling 4: a scheduled run never uses a Claude or
  ChatGPT plan**; on a metered engine it spends with no limit Cicada sets, said in words. Continue-after-reset is opt-in,
  off (ruling 15).
- **The write window (G177):** `sleep_cycle.is_writing()` is the one predicate behind every "Sleep is running" refusal,
  read only through `write_admission` (G183): a writer holds it shared through its own commit, Sleep sets its flag then
  waits holders out; order admission → page → git; never held across a model call or a fetch.
- **Entity promotion:** a first mention stays in the index; a page needs 2+ conversations, >3 exchanges, or a link to a
  high-confidence page. Claims about a name with no page yet are held (`pending_store`), never lost.
- **Temporal decay is a signal:** at most one week charged per cycle (ruling 1), paced by how many weeks a page came up
  in (G147); evergreen never decays; an import is not silence. Below 0.2 archived, below 0.4 a decay nudge.
  **Confidence does not rank recall.**

### Storage, claims and provenance

- **The filesystem is the single source of truth**: wikilinked markdown with YAML frontmatter, git-versioned; the API
  and Sleep read and write the same files. No changelog in frontmatter — git holds history.
- **Entity types are a closed set of 10**; Stage 1 never produces `deadline` or `media`. Status: active → decaying →
  archived → dropped.
- **Decay classes (G66):** one resolver; Stage 1 may propose `durable|active|volatile`, **never `evergreen`**, enforced at
  extraction and again in the create branch.
- **Evidence spans, not copies (G118):** offsets into the source's evidence text with a hash; locate is exact →
  whitespace → case-insensitive, **never fuzzy**; an unlocatable quote becomes `reasoning` and **the claim is still
  written — provenance never blocks memory**. Six evidence kinds; every claim on the wire is built by one function.
- **Events (G141):** only `progress.py` writes `happened`/`milestone`; a done happening is born closed; nothing relative is
  stored.
- **Sources (G61) are a living set:** many per fact; an agent changes or removes only what it added; a removal is
  remembered (`sources_removed`) and respected by every automatic writer; a source may link to its own page (`entity:`),
  never creating one. A site is trusted only when the person added or took it, or Cicada's own read confirmed it; a
  destructive verdict needs positive evidence. Agents check sources before a question reaches the person only on sites the
  person allowed, and **a check never settles, reorders or changes a belief** (S3 is shadow).
- **Pictures:** one precedence (the person's choice → Contacts photo → a brand's logo → a media thumbnail → a monogram).
  **A logo comes only from a trusted `website` source — never a domain guessed from a name; a person never gets a logo and
  no service is sent a person's name (G146/G159).** Logos, pictures and repo observations are caches outside every bank.
- **Backlogs (G150):** one markdown file per item, one writer behind every door, never an entity page.
- **`_state.md` is a cursor, never a copy**; it commits ALONE, the read path too (the G85-class smear). **The handshake is
  ≤ 1,800 tokens, and R12 holds: every argument a primer names exists in the tool schema.**
- **Derived indexes are disposable** (vectors, FTS): rebuilt, never an error; never tracked by git; **the query is never
  logged**. The caller always passes the active bank (the split-brain rule).
- **The telemetry ledger is ids and enums only, never text, never in a bank or git.** Nothing learned from it is
  auto-applied.
- **Git:** every Sleep commit is machine-parseable, with three trailer families (`Cicada-Author`, `Cicada-Engine` — omitted
  rather than guessed — `Cicada-Session`). Decay gets its own `cicada` commit (G85). **One git writer per bank**: every
  mutating git command runs under one per-bank lock; git's lock is never deleted. A write that commits commits alone,
  under its true author.

### MCP and agents

- The handshake rides `initialize`; recall fuses vectors, words and claims. **An agent's write carries provenance** (the
  harness as `Cicada-Author`, the session trailer) and an agent withdraws only what it wrote.
- **The remote connector (G135)** is off by default, serves only MCP on its own listener, through a tunnel **the person**
  runs; capability tokens are hashed, scoped (`sources` gates every verbatim word of the person's), expiring and
  revocable; a remote claim is never the person's own words.
- **Reading with the person's own agent (G166):** Cicada never spawns a browser and never signs in; it only asks. Only a
  link the person asked about, or a wall page of a site they allowed, can be recorded. The backend never fetches a
  login-walled page.
- **Video (G162):** Cicada never downloads a video or derives a stream; a video's state is derived, never stored; the
  queue lives outside every bank.

### The app

- **The app is not the primary surface — the chat is.** The app makes the graph observable.
- **Design direction D is binding** (`docs/design/DESIGN_RULES.md`; a UI PR cites the DR ids it applies; a departure needs
  a dated ruling). SF only; the accent in six uses; depth is a ring, not a shadow; painted art never behind data or text;
  Liquid Glass only in the chrome layer; a keyboard action never animates; every duration is spelled in `CicadaMotion` (a sprite's frame timings are data in its sheet, inside `CicadaMotion`'s sprite caps — TODO ruling 18).
- **Copy is provider-neutral** (owner, 2026-09-30): never name a provider or model as the one doing a job — describe the
  step; a name appears only where it shows the person's own current choice.
- **Prices and plan usage show only on the Sleep page's Details and engine menu** (ruling 12), each figure with its basis.
- **Sync:** one Store, hydrated from disk, SSE deltas, **never blank**; writes are optimistic with rollback. **Ship an
  ETag and its client mapping together.** A read that is not a Store domain says so and caches in memory.
- **d3-force stays (G109)**; every custom force multiplies by alpha; the release path never bumps alpha.

### The network

- **Three gates, not one:** `CICADA_ALLOW_CONNECTOR_FETCH` (opt-out) gates every fetch Sleep starts on its own — a click
  the person made never is; `CICADA_ALLOW_FEED_FETCH` (opt-in) gates RSS/ICS; `CICADA_ALLOW_LOGO_FETCH=off` disables logos.
  Every server-side fetch of someone else's URL goes through `net_guard`.
- **Update check (G182):** release builds only, behind Settings → General's *Install updates automatically* (on by
  default; off = only Check for Updates… asks); a download installs only after its sha256 and Ed25519 signature verify.
- **Study room weather (G176):** its own opt-out app gate reads only public city weather while the room is visible and Settings is closed, at 4 s / ≤ 64 KB / no cookies or identifiers; see `docs/architecture/network.md`.
- **The ToS rail — not negotiable.** A fetched page is 4 s / ≤ 512 KB / no cookies / never behind auth. Consent
  interstitials and login walls are classified and retired **without a byte fetched**. **A block is never retried with
  different headers.** No scraping behind authentication, ever.
- **Credentials** live in `~/.cicada/secrets.env` (0600) — never in a bank, never logged.
- **Video:** only a provider's own player URL is loaded; an oEmbed response is read for its fields, never its HTML.

### Rulings

The binding decisions (rulings 1–17 and the dated amendments) live in [`docs/goals/TODO.md`](docs/goals/TODO.md). A ruling
is revisited only on the trigger its row names.

---

## UX Principles

1. **Minimal friction**: responding to a nudge = one tap. Never require "memory maintenance".
2. **Transparency over magic**: the user sees WHY the agent knows something (provenance), WHEN it
   learned it, HOW confident it is.
3. **User authority**: agent proposes, user disposes. Every automated action can be overridden.
4. **Non-intrusive nudging**: available when wanted, not pushed. The inbox is there when you want it.

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Markdown over Neo4j | Same relational expressiveness at personal scale. Zero infrastructure. Portable. The LLM is the query engine. |
| sqlite-vec over LEANN/FAISS | Stored (not recomputed) vectors give single-lookup latency with no cloud dependency; the index is derived and disposable. |
| FTS5 beside sqlite-vec | Type-as-you-go needs words, not meanings: a derived lexical index answers a prefix in ~12.5 ms p95 at 2k entities / 1.5k episodes without an embedding call, and finds aliases, claims and conversation text by what they say. Derived and disposable, like the vectors. |
| Batch over real-time consolidation | Conversations don't have clean endings. Batch sees patterns across a full day. Clean evaluation. |
| Entity promotion over upfront extraction | Avoids polluting the graph with noise from single mentions. |
| Temporal decay as an active signal | Absence of mention is informative. No other system does this. |
| Clarification queue over silent drops | Ask rather than guess or discard. Prevents cascading hallucination. |
| MCP-native + export fallback | MCP for real-time, export for ChatGPT/Claude. Source-agnostic pipeline. |
| SwiftUI + FastAPI | Native macOS feel. Python backend for the LLM/ML ecosystem. |
| d3-force in WKWebView | Best graph-visualization ecosystem. Sufficient at personal scale (G109). |
| Filesystem as single source of truth | No separate database. The API reads/writes the same files as Sleep. |
| Decay class over a bare per-writer rate | A hardcoded float was invisible to the agent, unchangeable by the user, and decayed bookmarks — artifacts that never become less true. |

---

## Installation & Setup

**Testers install a release** with `scripts/install-release.sh` (curl | bash; G182) — releases, the signing key and
the later Developer ID steps are in [`docs/RELEASING.md`](docs/RELEASING.md). From source:
`install.sh` is the source of truth; `install.md` is the paste-into-your-agent path for a fresh Mac
(clone → `./install.sh` → `make install-app` → open the app; G76), and it never loops `make doctor`.
The rest of the paste-prompt install story is G76 in the backlog.
`scripts/install-backend-agent.sh` is the one source of the `com.cicada.backend` plist; `install.sh` step 6 calls it
behind its healthy-skip guard, and the app runs it from Settings → General (G143). `BackendProcess` spawns
`python -m uvicorn`, never the venv's `uvicorn` script. `make login-item` is the old developer path; the app's switch
is the supported one. **A release app (G182) carries its own backend** and every agent, hook and plist runs the
`~/.cicada/bin` launchers it rewrites on launch — never a path inside the app; a developer build is unchanged
(`docs/architecture/app.md`, "The release app").
