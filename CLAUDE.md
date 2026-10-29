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
- **[`feature-status.md`](docs/goals/feature-status.md) — one line per feature, its status and PR; every PR updates its line.**

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
| Headless: the server without the app, its systemd unit, the primary-writer topology (G181) | [`docs/architecture/headless.md`](docs/architecture/headless.md) |

**Keeping it this size.** A PR updates the area doc its change makes wrong, in the same PR. It touches this file only
when a *rail* changes (a new invariant, a ruling, a boundary), and then in one or two lines that point at the doc.
`api/tests/test_claude_md_size.py` fails above 60,000 characters and checks every doc linked above exists.

---

## The rails (binding — each is stated in full in its area doc)

### Capture (Awake)

- **No LLM at capture time** — capture is file I/O into `episodes/`; the pipeline is source-agnostic. **Amended (ruling
  36 D2, 2026-10-22):** a separate quick read after a conversation ends may write provisional claims Sleep confirms or
  drops — never on the capture path, on by default only if measured better, no setting (G207).
- **The app reads `~/Library`, the backend parses bytes.** The launchd backend has no Full Disk Access and never opens
  those paths, never stats a path a request names, never runs git in a declared repo; the app reads (browsers, Notes via
  its own `osascript`, Calendar, Contacts, Chrome tab groups, watched folders, Wispr Flow) and posts bytes. A browser is
  read only after the person turned it on. An unreadable file shows the exact fix in the app. Chrome's history is read
  from a copy, YouTube video pages only; watch history is one episode per day, never a save (G71, `capture-and-sleep.md`);
  it and saves from a platform's saved list are indexed, never read by a model (ruling 30).
- **Two ways in for what the person consumes (ruling 47, owner 2026-10-28):** by default their own browser and Mac,
  through the browser and macOS harnesses (G166, G206, G218 rails unchanged); an official API only for a specific source
  where it gives what the harness cannot (history, metadata, reliability) — the person connects each one (off by default,
  said in words, one-click revoke), read-only, the normal capture path, no private name sent. 47a: Telegram (`network.md`);
  ruling 49: never from the Mac's own store, connected by a QR the phone scans.
- **Capture never depends on a model calling a tool (G105).** Claude Code and Codex sessions are captured by the
  harness's own Stop hook; the backend reads a transcript only when it resolves under the harness root as
  `<session_id>.jsonl` within the size cap. Only the person's turns and the agent's final reply are kept, plus each agent
  turn's model and effort. After scrubbing, the first person message keeps up to 16k characters; later person turns
  keep a 2k head, agent final replies a 2k head+tail including a recorded non-speaker gap (G110 A2).
  Cursor and Gemini CLI hooks post the turn's own words to `/capture/turn` (same writer, caps, scrub and demo rule;
  no transcript read, `capture-and-sleep.md`). **One episode per session** (G104). Cicada's own `claude -p` / `codex exec` spawns run with
  `CICADA_CAPTURE=off` and `CICADA_RECALL=off` (separate switches since 2026-10-23, `mcp.md`). Stop is the trigger; PreCompact and SessionEnd run the same hook as a best-effort, idempotent
  flush, each log line tagged with its event (G110 gate A). Over the session cap the head and the latest turns are kept
  around one marker line (G110 gate B2; its G104 costs in `capture-and-sleep.md`). Recall is the same move (G149): the
  SessionStart/UserPromptSubmit hooks inject Cicada's note; a note the harness records as a separate non-person record
  is never captured, and one that arrives inside the person's own text is kept, counted and disclosed (G110 gate C).
  **Apps with no hook** (claude.ai, ChatGPT, their phone apps) relay each turn through the remote connector's
  `cicada_capture_turns` (ruling 32): one episode per conversation, stored as relayed (`evidence_kind: assistant`),
  never the person's own words until that app's export upgrades it in place (`capture-and-sleep.md`).
- **Transcripts under `~/.claude/` are never read anywhere else** — the MCP seam and resume only `isfile()` them.
  A client of a server elsewhere reads its session there with Cicada's own extractor and posts the capped turns (ruling 28).
  **Agent memory notes (ruling 43):** Claude Code's `projects/*/memory/*.md` are read by its own hook, never the backend
  — the backend's one `~/.claude` read stays the transcript, and it works the same on a client or a headless server —
  posted as bytes, one agent-worded episode per note, one switch, on by default (`capture-and-sleep.md`).
- **One id rule** (`episode_ids`): max-suffix+1 per date — the conversation's local day, never renamed (ruling 34) —
  aware UTC timestamps; `processed_by` says who flipped it. **Both dates (ruling 39):** `timestamp` is the item's own
  date, `received_at` when Cicada received it — stamped once by `create_episode`, never backfilled; a feed item is
  dated when published and is no time signal (`episode_time`, `capture-and-sleep.md`).
  A new episode never replaces a file (`create_episode`); dedup, edits and Sleep's revision-checked retirement share
  `episode_lock`, and every page write is atomic (audit K01/A01/A02, `capture-and-sleep.md`).
- **Every writer scrubs, every source-keyed writer stages through one module** (`episode_scrub`, `episode_staging`:
  hash over the scrubbed body, edits in place with `processed: false`, deletions tombstoned, never unlinked).
- **Capture never writes into a demo bank** (`demo_guard`, by `_bank.yaml`, never by name): every capture/sources
  POST/PUT answers 409; the Stop hook redirects to the real bank left most recently.
- **Messages are read only for conversations the person ticked (G179)**: the app reads them, the backend refuses any
  other; a texted agent's words are its `assistant:` turns and its claims `external:<name>`, never the person's own —
  as are a harness session's or a chat export's assistant's (`external:<harness|app>`, 2026-10-27; relayed apps keep
  their own rail); an explanation is never written as the person's act, and a claim carries its episode's session.

### Sleep

- **Five stages** (extract → resolve/dedup → conflicts/decay → patterns/skills → nudges + commit) plus an
  **engine-independent tail** on every exit path, in a clean-tree-guarded slot, each step committing only its own paths.
- **Consolidate reads everything** (rulings 13, 16): every run — the person's and a scheduled one — is a drain over the
  ids frozen at its start, in committed batches (default 25), so a stop loses at most the batch in progress. Decay and the
  page reads run once per drain. A plan limit is a pause, not a failure. **Ruling 4: a scheduled run uses a Claude or ChatGPT plan only
  through the person's "Scheduled runs may use my plan" switch, on unless they turned it off** (4b 2026-10-16, 4c
  2026-10-19; `SUBSCRIPTION_MODES` the one guard); on a metered engine it spends with no limit Cicada sets, said in words.
  **Plan-first engines (ruling 31, 2026-10-19):** the default is Auto — Claude plan, ChatGPT plan — and never
  a metered key nobody chose: no engine is said in words, and a key (OpenRouter included) reads only when chosen.
  **Ruling 36 D1 (owner, 2026-10-22):** with nothing chosen, Auto uses a signed-in plan (Claude Code, then Codex) and
  says in words what runs; a key secured properly is an equal option; a local model runs only when chosen, never as Auto's rung.
  **The person's own Cursor, OpenCode or Grok (G49/G50, 2026-10-28)** are plans under ruling 4's switch (Grok user-started
  only), headless with no tools or MCP context, on their own sign-in; a key-billed path is refused or stops the run (`cli_engines`).
  **Ruling 46 (owner, 2026-10-28):** Auto is Claude plan → ChatGPT plan → Cursor → OpenCode (subscription model only), each
  read from cached status, an unknown or hung tool skipped in words, never a stall; Grok never on Auto (`capture-and-sleep.md`).
  **46a (owner 2026-10-28):** Auto and schedules run Cursor only on Cursor's own models; a third-party one there is labelled "billed separately at list price", never auto-picked. Continue-after-reset is opt-in,
  off (ruling 15). A scheduled time the Mac slept or was off through runs once, after a short settle, as a scheduled
  run — never over a pause or a running cycle (`sleep_catch_up`, owner 2026-10-19, `features.md`).
- **The write window (G177):** `sleep_cycle.is_writing()` is the one predicate behind every "Sleep is running" refusal,
  read only through `write_admission` (G183): a writer holds it shared through its own commit (async: `run_admitted`),
  Sleep sets its flag then waits holders out — past the bound it pauses, never reads; order admission → page → git;
  never held across a model call or a fetch.
- **Sleep tends the inbox (ruling 29):** after each batch's commit it settles questions the person's own words answer
  (spans in their own turns, never a guess) and, per drain, the small stuff by rule, through the person's own resolvers
  as Sleep's commit (`inbox/<kind>/settled:`), each undoable; never a person's identity without their words (`features.md`).
- **Entity promotion:** a first mention stays in the index; a page needs 2+ conversations, >3 exchanges with the person's
  own words, or a link the person made to a high-confidence page other than the owner's — counted on the conversation,
  never guessed (`promotion`) — or the person's own words naming in full exactly one waiting Contacts card, never the "me"
  card or a relation-only person (owner 2026-10-20; cards wait outside every bank until Contacts stops, `capture-and-sleep.md`).
  **A project is born only from a repository the hook observed or the person's own located words calling it one —
  never from this rule (ruling 36 D4, `project_birth`); an older page is never archived for it.** **Ruling 45: the person, their
  shell or a trusted agent on their ask may create one; only those, folders they named, ones they logged progress on
  and suggestions they took are listed — the rest is suggested, never archived (`project_ownership`, `storage.md`).** One never called a
  project gets, over this rule counted across the spellings the judge joins, one `concept` page a later birth retypes in
  place (owner 2026-10-23, `capture-and-sleep.md`). What is said about a
  name with no page yet is held (`pending_store`), never lost. A page only an import made is quiet — dimmed, never
  asked about — until the person mentions it, derived on read (`quiet_pages`).
  **Ruling 42 (owner 2026-10-27):** one conversation is enough for a specific event, program or application the person
  — or a harness agent, for them — acted on (applied, registered, filled its form), measured on the conversation; the
  application lives on that page, the owner's keeps only the link (`application_page`, `capture-and-sleep.md`).
  A Stage-4 skill needs 2+ conversations too; one is held in its own store, `skill_hold` (G112, owner 2026-10-09).
  A speaker's self-reference ("the user", "me", "yo"…) is the owner's page, never a page of its own (G169).
  A person known only by a relation to the owner is titled by the relation, never the owner's name, and asked their
  name; it is merged only on the person's answer or evidence on the record (`role_people`, `capture-and-sleep.md`).
- **Temporal decay is a signal; age counts from when it was said** (owner 2026-10-09/13, amends G170): what the
  conversations prove silent is charged once, when read; a one-off may archive by age, a page or claim on 2+ dated
  conversations floors at 0.39 and only live silence archives it; ruling 1's one-week cap governs live silence; a
  mention never lowers; a decay question only when live silence crosses 0.4. **Read on time** (2026-10-16): a
  conversation read late counts as read the day it was said — when it is read never changes the result. Evergreen
  never decays; a memory export entry or a watched day is no mention. Below 0.2 archived. **Confidence does not rank recall.**

### Storage, claims and provenance

- **The filesystem is the single source of truth**: wikilinked markdown with YAML frontmatter, git-versioned; the API
  and Sleep read and write the same files. No changelog in frontmatter — git holds history.
- **A page's claims are its fence plus, past 64k characters, its ledger** `entities/<id>.claims.jsonl` (owner page,
  2026-10-14): `markdown_parser` folds it on read and splits on write; a write never drops a ledger line; git commits
  and restores a page with its ledger (`storage.md`).
- **Entity types are a closed set of 10**; Stage 1 never produces `deadline` or `media`; a model's word is mapped into the
  set at extraction and again where a page is born (`entity_types`, 2026-10-17). Status: active → decaying → archived → dropped.
- **Decay classes (G66):** one resolver; Stage 1 may propose `durable|active|volatile`, **never `evergreen`**, enforced at
  extraction and again in the create branch.
- **Evidence spans, not copies (G118):** offsets into the source's evidence text with a hash; locate is exact →
  whitespace → case-insensitive, **never fuzzy**; an unlocatable quote becomes `reasoning` and **the claim is still
  written — provenance never blocks memory**. Six evidence kinds; every claim on the wire is built by one function.
  A record's filing label (a folder, a list, a calendar) is never anyone's words nor a conversation for the 2+ rule
  (owner 2026-10-29, `storage.md`).
- **Events (G141):** only `progress.py` writes `happened`/`milestone`; a done happening is born closed; nothing relative is
  stored.
- **Sources (G61) are a living set:** many per fact; an agent changes or removes only what it added; a removal is
  remembered (`sources_removed`) and respected by every automatic writer; a source may link to its own page (`entity:`),
  never creating one. A site is trusted only when the person added or took it, or Cicada's own read confirmed it; a
  destructive verdict needs positive evidence. Agents check sources before a question reaches the person only on sites the
  person allowed, and **an inbox check never settles, reorders or changes a belief** (S3 is shadow) — **except a question
  about a public thing (ruling 27):** a web lookup settles it with a cited claim (a citation, never a tracked source),
  undoable under "Settled by a check"; never a person's name, their files, projects or life (`mcp.md`); it is the default
  path on every plan run plus a one-off backlog sweep, and Cicada's own settings are never asked (27b, 2026-10-19).
  **Ruling 44 (owner, 2026-10-27) amends 27 and 40:** a public page — a public figure only by the public test (one
  encyclopedia match, no acquaintance on the record; err private), a company, program, tool or place — gets cited, dated
  world facts on plan runs (never a metered key), re-checked by use and volatility, never over the person's own words
  about their own life; a private
  person's name never reaches any service; every page says why it matters to the person, derived on read (`web_context`,
  `page_relevance`, `storage.md`). **A tracked source's
  dated re-check does (ruling 26):** a new dated fact; the newest evidence wins, even over the person's own words; the same
  day or undated asks once; dead = two failed visits a week apart; walled pages only by the person's agent (`storage.md`).
  **Where to check (ruling 36 D5, 2026-10-22):** an agent (`inferred`) or Sleep's engine-free step may PROPOSE a link
  already on the record — never one guessed from a name; a proposal is never trusted, drawn or re-checked until the
  person takes it, one grouped review ("Confirm N links"); Sleep settles one only when the person's own located line
  names that one page and the link's account is its name or alias — co-occurrence is never proof (`storage.md`).
  **An organisation's own site (ruling 40, 2026-10-26):** for a company, tool or public place — never a person (a
  public figure's context is ruling 44's, never a site), a project or a private name — Sleep trusts a site the record ties to the page or ONE unambiguous Wikidata match, only
  when its homepage names it — a site Sleep itself first proposed included (owner 2026-10-28, D) — anything less is a proposal in that review; a removal is never re-added (`org_sites`).
- **Pictures:** one precedence (the person's choice → Contacts photo → the photo a ticked Messages chat shares → a
  person's public-profile photo → a brand's logo → a media thumbnail → a person's monogram; any other page with none draws
  nothing, never a type glyph — owner 2026-10-28). **A logo comes only from a trusted
  `website` source — never a domain guessed from a name; a person never gets a logo and no service is sent a private person's name (G146/G159).** Owner 2026-10-28 (C, E): a public figure ruling 44's full test matched gets that item's encyclopedia portrait, asked by item, never with the name as a query; a project its trusted site's mark or, only when an organisation owns its repository, that organisation's avatar (`storage.md`). Ruling 40's homepage-confirmed find is trusted, and a public place with one draws its mark. A saved link's own site may show its own icon, asked of that site only (or the icon host its homepage declares, 2026-10-20; an SVG icon only sanitised and drawn to a PNG out of process, never served as SVG, 2026-10-20), on the person's view (owner 2026-10-19; `storage.md`); a watched or saved YouTube video its still, from YouTube's own host for that id only, on the same terms (2026-10-19). A person's photo is asked only
  with an identifier already on the page or record and given as their own account — the owner's hashed email, a GitHub,
  X, Instagram or LinkedIn profile link (owner, 2026-10-09; Instagram, D5), never a proposal the person has not taken (`network.md`); a LinkedIn link from the person's connections counts as given
  on a confident match, never an alias-only one (owner 2026-10-17). The photo a chat shares in Messages is its page's
  picture everywhere — ticked chats only, read by the app from a copy, kept outside every bank, linked by the chat's
  correspondent record, gone on untick (owner 2026-10-16, `storage.md`).
  Logos, pictures, media previews (fetched once, then served from the store) and repo observations are caches outside
  every bank.
- **Link views (owner rulings 2026-10-14):** a view is a word in a link's markdown title (`[T](url "bookmark")`), one
  grammar both sides (`link_views`); Sleep writes plain links, the person's switch is a pinned edit, no linked page is
  fetched to draw a card, and the app loads no picture a page names from the web (`storage.md`, `app.md`).
- **Backlogs (G150):** one markdown file per item, one writer behind every door, never an entity page.
- **Site captures (G166, ruling 25):** one append-only dated record per visit, a ≤ 640×400 thumbnail in the bank only
  when the look changed, full images and page text outside every bank (`$CICADA_HOME/captures`); one writer (`site_captures`).
  Depth follows the person's reason through a plan Cicada computes with no model (`explore_plan`); each site's map is
  append-only in the bank beside its captures (`captures/_sites/`, one writer `site_map`; `storage.md`).
- **Activity traces (G218, ruling 38):** off by default; the app alone captures (preflight-only permissions, Touch ID to
  browse screenshots) and the backend keeps them sealed in `$CICADA_HOME/traces/` — outside every bank and git, never on
  the network, a remote door or another device, 30-day timeline / 7-day screenshots, Wipe shreds the key; a trace is not
  a mention; only the person's switches promote (what is watched and read on any site, index-only — 39b generalised,
  2026-10-28; behind "Learn from my day", off, a counted day digest with no title or address, the one thing a model may
  read, removable from memory as one undoable commit) (`storage.md`, `capture-and-sleep.md`).
- **Design references (2026-10-14):** one markdown file plus its screenshot per look, in the bank, one writer
  (`design_refs`), never an entity page; palette and vectors are computed here; since 2026-10-28 the index is the
  `look_vectors` table of the bank's derived `vector_index.db` (git-ignored, never copied or exported; `storage.md`).
  **Owner 2026-10-20:** a look lives on the page of the thing it shows — the record's `entity:` plus a `## Looks` section
  on that page that only `design_refs` writes (never a page invented); the Looks page is gone (`storage.md`, `app.md`).
- **`_state.md` is a cursor, never a copy**; it commits ALONE, the read path too (the G85-class smear). **The handshake is
  ≤ 1,800 tokens, and R12 holds: every argument a primer names exists in the tool schema.**
- **Derived indexes are disposable** (vectors, FTS): rebuilt, never an error; never tracked by git; **the query is never
  logged**. The caller always passes the active bank (the split-brain rule). **Pictures are a kind of the same index
  (2026-10-28):** only pictures already on this Mac, embedded outside Sleep in the picture child, never on a search;
  a search embeds words only; the remote connector never sees picture hits (`image_index`, `storage.md`). So are the
  words and kept frames of a recording or video the person adds — read by the app, posted as derivatives, stored
  outside every bank, the recording's words and never the person's, never read by Sleep (`media_files`).
- **The telemetry ledger is ids and enums only, never text, never in a bank or git.** Nothing learned from it is
  auto-applied.
- **Git:** every Sleep commit is machine-parseable, with three trailer families (`Cicada-Author`, `Cicada-Engine` — omitted
  rather than guessed — `Cicada-Session`). Decay gets its own `cicada` commit (G85). **One git writer per bank**: every
  mutating git command runs under one per-bank lock; git's lock is never deleted. A write that commits commits alone,
  under its true author.

### MCP and agents

- The handshake rides `initialize`; recall fuses vectors, words and claims. **An agent's write carries provenance** (the
  harness as `Cicada-Author`, the session trailer) and an agent withdraws only what it wrote.
- **One tool-call contract on both doors (G199):** a call is checked once against the schema that door advertises; a
  refusal keeps its sentence and answers `isError` with its code; an exception names its class, never its message, in
  any reply (the log gets its file:line, never its message); a read reply is fenced whatever its code, Cicada's own
  directions outside the markers (`tool_contract`, `mcp.md`).
- **Prose is no longer Sleep's alone (G198, owner 2026-10-14):** `cicada_edit_page` changes a page's words or aliases, never
  its claims, with a reason that is the commit message; only a harness on the person's trust list writes at once (Claude Code
  and Codex until the person changes it, owner 2026-10-14; never remote, never `agent`), any other proposes in the inbox; pinned fixes and removed aliases outlive Sleep; blame is read from git (`storage.md`, `mcp.md`).
  A device holding a per-device token the person issued counts as local (ruling 28); a G135 connector never does.
- **Questions come up naturally (owner, 2026-10-14):** an inbox question reaches a conversation only when it is about
  that question's subject (`inbox_ask_gate`), in the agent's own words; an answer the person already gave is recorded
  with their words as evidence, never guessed; the whole inbox only on request (`mcp.md`).
- **The CLI (G180, ruling 21)** is a second door onto the same bodies: in-process from one bootstrap that reads no
  `.env` (the root resolved once, canonical, pinned with the bank; `--bank` asserts, never selects), names from one
  tested CLI↔MCP table (`cli_map`), one JSON envelope, no generic dispatcher (`mcp.md`). **Ruling 21a (owner,
  2026-10-13):** a command on state the running backend owns (Sleep, engine, search model, bank switch, settings, the
  app's page writes) calls the backend's own route with the token and its pinned bank, only after `/healthz` confirms the
  root; with the backend down it refuses. Commands that act as the person refuse from an agent's shell.
- **The remote connector (G135)** is off by default, serves only MCP and the G213 agent API (`/v1`, owner 2026-10-22,
  ruling 36 D3) on its own listener, through a tunnel **the person** runs; capability tokens are hashed, scoped (`sources` gates every verbatim word of the person's), expiring and
  revocable; a remote claim is never the person's own words.
  `/v1` is generated from the remote tool table — one operation per remote tool, the 11 shipped names frozen, new ones
  `cli_map`'s — with `/mcp`'s scopes and G199 contract; no third door (ruling 38, `api.md`); a client library
  speaking only `/v1` with an agent token, like `clients/memory-tool`, is not a door (38a, 2026-10-29).
  Apps sign in through the listener's own OAuth 2.1 server (ruling 32): consent only in the app, by typing the code the
  person's own page shows, never a click or the public page; PKCE S256, single-use codes, rotating refresh tokens, all
  hashed and mapped to connector rows; a self-registered app is never named by its claim (`network.md`).
- **Reading with the person's own agent (G166):** Cicada never spawns a browser and never signs in to a site; it only asks
  (only ruling 47's tier 2 — an official API the person connects — signs in, never as a browser session, `network.md`). Only a
  link the person asked about, or a wall page of a site they allowed, can be recorded — and (owner 2026-10-16, G71) the
  person's YouTube Watch later or history page, a standing ask once they turn that list on, stdio only; their saved list on X, Instagram or LinkedIn the same way, one site at a time, ≤ 10 reads a day, each item an
  indexed save (G206, 2026-10-22, `mcp.md`); one person's
  LinkedIn profile only through the link their page lists, on the person's ask, ≤ 10 a day, stdio only (2026-10-16,
  `mcp.md`). Imported LinkedIn connections enrich existing people only, never mint a page. The backend never fetches a
  login-walled page. **Exploring saved sites (ruling 25):** only the person's click or a trusted local agent they asked
  starts a run; the agent uses their signed-in session unless they turn it off, every capture says which (`mcp.md`).
- **Skills (2026-10-15):** Cicada installs third-party skills only on the person's consent, pinned to what they saw
  (a commit, or a catalog tool's commit); one writer (`skill_store`), never into a bank, never hooks or settings; an
  agent only asks (`cicada_propose_skill`) or drafts a held skill (`api.md`, "Skills").
- **Video (G162):** Cicada never downloads a video or derives a stream; a video's state is derived, never stored; the
  queue lives outside every bank.
- **Continuity (G110, slice 1a/1b):** SessionStart carries a light pointer inside the whole 1,800-token note;
  previous working history is retrieved on demand via `cicada_continue`, from captured episodes over a disposable index;
  workspace state is not checked; the registry outside every bank holds ids, hashes and times only (`mcp.md`).
  D2 permits the hook alone to observe git identity with a bounded fixed read-only pair; the backend only parses
  supplied values, never inspects a declared workspace. Sibling workers never replace the root session's role (`mcp.md`).
  G228 permits the capture hook to observe its own launch chain to name a host app (T3 Code): parent pid and exec path
  only, bounded, in-process, never another process's arguments or environment (`capture-and-sleep.md`).

### The app

- **The app is not the primary surface — the chat is.** The app makes the graph observable. **New features live behind
  the backend API; the app is one client of it** (the CLI and a future browser front end are others, owner 2026-10-13):
  the app keeps only Mac readers that post bytes, per-viewer chrome and presentation.
- **Design direction D is binding** (`docs/design/DESIGN_RULES.md`; a UI PR cites the DR ids it applies; a departure needs
  a dated ruling). SF only; the accent in six uses; depth is a ring, not a shadow; painted art is retired, the pixel study room the one
  illustration and never behind data or text (owner 2026-10-16);
  Liquid Glass only in the chrome layer; a keyboard action never animates; every duration is spelled in `CicadaMotion` (a sprite's frame timings are data in its sheet, inside `CicadaMotion`'s sprite caps — TODO ruling 18).
  **The redesign (ruling 48, owner 2026-10-28):** a page is an article carrying its beliefs as citations, never a stacked
  fold; the Inbox lives on Home and each page, off the rail (DESIGN_RULES §9 2026-10-28, DR-77…DR-81).
- **Bookmarks (G191 v3, 2026-10-15):** the app removes a bookmark from the person's browser only on their click, after
  asking in words — Chrome through Apple Events (the Automation prompt only then), never Safari, never the backend; it
  sees Chrome's bookmark bubble from window bounds alone (no title, no permission), read only in the moment after the
  person's own click in a frontmost Chrome — never on a steady timer (G191 v4) — and posts no answer until a sync confirms the bookmark (`app.md`).
  An answer given is never dropped for a dismissal or a late sync, and a touched panel closes only on the person's act;
  the star on a saved page reads Chrome's front-tab URL only when Automation is already allowed, never prompting (2026-10-19).
- **Copy is provider-neutral** (owner, 2026-09-30): never name a provider or model as the one doing a job — describe the
  step; a name appears only where it shows the person's own current choice.
- **Prices and plan usage show only on the Sleep page's Past reads run detail and engine menu** (ruling 12, surface
  renamed 2026-10-16 when the Feed folded into Sleep), each figure with its basis.
- **Sync:** one Store, hydrated from disk, SSE deltas, **never blank**; writes are optimistic with rollback. **Ship an
  ETag and its client mapping together.** A read that is not a Store domain says so and caches in memory.
- **d3-force stays (G109)**; every custom force multiplies by alpha; the release path never bumps alpha.

### The network

- **Three gates, not one:** `CICADA_ALLOW_CONNECTOR_FETCH` (opt-out) gates every fetch Sleep starts on its own — a click
  the person made never is; `CICADA_ALLOW_FEED_FETCH` (opt-in) gates RSS/ICS; `CICADA_ALLOW_LOGO_FETCH=off` disables
  logos and media previews.
  Every server-side fetch of someone else's URL goes through `net_guard`.
- **Update check (G182):** release builds only, behind Settings → General's *Install updates automatically* (on by
  default; off = only Check for Updates… asks); a download installs only after its sha256 and Ed25519 signature verify.
- **Search model download (2026-10-09):** EmbeddingGemma 2 is fetched only on the person's click or command — one pinned
  revision, every file sha256-checked, into `~/.cicada/models`, never bundled; its image encoder is a second click
  (`network.md`). A model change re-embeds in
  the background, never during Sleep, and recall keeps the old table until the new one commits (`storage.md`).
- **Study room weather (G176):** its own opt-out app gate reads only public city weather while the room is visible and Settings is closed, at 4 s / ≤ 64 KB / no cookies or identifiers; see `docs/architecture/network.md`.
- **The ToS rail — not negotiable.** A fetched page is 4 s / ≤ 512 KB / no cookies / never behind auth. Consent
  interstitials and login walls are classified and retired **without a byte fetched**. **A block is never retried with
  different headers.** No scraping behind authentication, ever. **One dated exception (owner, 2026-10-09):** a person's
  photo through unavatar.io from an X, Instagram or LinkedIn link already on their page, behind its own gate — **on by
  default since ruling 36 D5 (2026-10-22)**, shipped with sources on people (G61); `off` still closes it.
  **Ruling 47 tier 2 (2026-10-28):** an official API or sanctioned connector the person connected, for ingestion, is not
  scraping; an unofficial client that breaks a service's terms or risks a ban never is (WhatsApp stays local, `network.md`).
- **Credentials** live in `~/.cicada/secrets.env` (0600), or the keychain where the app holds them (a connection's
  session too, ruling 47) — never in a bank, a log or the repo.
- **Headless (G181):** a server is its bank's one writer and binds 127.0.0.1 only; reach from another machine is an
  overlay the person runs (never a public port, never funnel — only the G135 listener may be, by the person, ruling 32), and no installer creates or copies a credential (`headless.md`).
  **One click (owner 2026-10-29, amends G132 (c)):** Settings → Devices may run exactly the shown `tailscale serve --bg
  --https=8443 <port>` (tailnet only) or that one mapping's off — argv built by the backend, 10 s, never `funnel` or `up` (`network.md`).
  Another machine is a client (`CICADA_API_BASE`, or the app's `api_base` file, ruling 28) with its own revocable device
  token and no bank of its own; what it posts records `device` (`headless.md`).
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
| Clarification queue over silent drops | Ask rather than guess or discard. Prevents cascading hallucination. **Dated exception (ruling 29, 2026-10-17):** Sleep settles what the person already said in their own located words and assumes the small stuff, each undoable under "Settled by Sleep"; never who a person is without their words. |
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
**Claude Code (owner 2026-10-19): the plugin is the canonical Claude Code door; `install.sh` the canonical machine
install.** `plugins/cicada` (this repo is its marketplace, id `cicada@cicada`) carries the MCP server, the skill and the
capture/recall hooks; only when it is enabled, installed and able to run a Cicada does `install.sh` stop registering
them for Claude Code and remove its older ones — never both, never neither (`docs/architecture/mcp.md`, "The Claude
Code plugin").
**Without the app (G181):** a Linux server installs with one `curl | bash` line (`scripts/install-server.sh`) and any
Homebrew with this repo's tap (`Formula/cicada.rb` + `cicada-setup`); both end in the checkout's own `install.sh`, the
formula has no `service do` (the two service scripts stay the one source), and its tag is a `VERSION` stamp
(`docs/architecture/headless.md`).
