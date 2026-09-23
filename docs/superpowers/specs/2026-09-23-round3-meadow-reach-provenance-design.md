# Round 3 (2026-09-23): Meadow, reach, provenance you can read

**Owner brief (Rodrigo 2026-09-23), condensed but in his words where they matter:**

- "improve the design of the cicada app … friendlier towards the general public, and in a sense
  have more that nature and technology futuristic in harmony collaboration look" (reference: a
  landing page with a painted sky, clouds, grass with dandelions at the edges, a serif headline with
  an italic second line, a muted green pill, liquid glass).
- "work on having the OpenAI OAuth working so that I can use my subscription with it, and also the
  Claude SDK, similar to how Hermes is doing it."
- A memory article on how *Instinct* stores memory: "see what and see if we can work on
  implementing."
- "Change the mascot page, make it better and have it be more interactive, keeping the minimal
  vibes."
- "look at the backlog and work on those things missing that set this apart."
- "recommended skills to install", e.g. a skill that lets Claude watch videos: "could match well for
  storing and having info about videos."
- "the whole import your stuff flow could be way friendlier, and … the onboarding. Make it
  seamless." (Reference: memorable.sh's onboarding and its "Claude, without a terminal" connector.)
- "Add animations to the icons as i hover over them. use logos whenever possible when referring to
  services to connect."
- A research project folder of markdown notes and paper references "to just live in cicada as well,
  with papers with summaries and why they are relevant to me."
- "easier and more friendly design to show who contributed to what memory."
- "a good connector working for all ai apps like claude, gemini, etc, ideally for phone too."
- Follow-ups the same day: "quick retrieval fast search bars", "show snippets in contribution of
  provenance in more detail to see where in conversation the memory comes from", "support note taker
  apps like wisprflow or others", and "a good settings page with a search bar like the one in
  claude" (reference: a settings window whose sidebar starts with a Search field, then grouped
  sections with icon rows, and a detail pane with a back breadcrumb).
- He is requesting his chat exports for a fresh, from-scratch consolidation run.
- Permission for this round: "you can use best models with highest effort", and computer use.

**Method.** Nine readers (engines, OpenAI OAuth, the Instinct article, remote connectors +
memorable.sh, skills + video, a whole-app design audit, imports/onboarding/folders/note-takers, the
backlog verified against code, Liquid Glass + a nature palette) wrote reports into the session
scratchpad. Their conclusions that bind are restated here so this spec stands alone.

---

## Decisions taken without the owner (review these first)

Each has a reason; each is reversible on the trigger named.

1. **"The Claude SDK, like Hermes" = Hermes's actual mechanism, not the Agent SDK package.** Hermes's
   "Claude Subscription DirectSDK" plugin spawns the user's unmodified `claude` binary per request
   with stream-json in and out, tools and setting sources off, one turn, and refuses to run when an
   API key or base-URL override is set. The `claude-agent-sdk` Python package is itself a wrapper
   around the same binary (a ~92 MB wheel bundling its own CLI), and Anthropic's docs name "agents
   built on the Claude Agent SDK" among third-party products that may not offer claude.ai login. So
   Cicada keeps **one engine id, `claude-cli`**, hardened the Hermes way (stream-json, rate-limit
   events, env scrub, JSON schema, capped retries). *Trigger to revisit:* Anthropic documents a
   sanctioned SDK path for a personal plan.
2. **ChatGPT plan runs Sleep through `codex exec`, never through a copied token.** Verified live on
   codex-cli 0.154.0: schema-valid Stage-1 JSON in ~17 s with every evidence quote an exact match.
   Direct calls to the ChatGPT backend with Codex's client id are ruled out (Cicada never holds a
   vendor token). **Cicada gets its own Codex home** (`~/.cicada/codex/`) with an in-app "Sign in
   with ChatGPT" device-code flow: it keeps the owner's ~108 skills and personal `AGENTS.md` (7.7k–
   11.6k tokens of hidden context per call) out of every Sleep call and avoids two processes racing
   one refresh token. The track measures the per-call overhead again under the isolated home.
3. **Scheduled cycles never spend plan quota, now for both plans.** `engine_select`'s scheduled
   guard names only `"agent"` today; it must cover `"codex"` in the same commit that makes Codex
   selectable.
4. **A remote connector ships, off by default.** Cloud AI apps (claude.ai web/desktop/mobile,
   ChatGPT developer mode, Perplexity) can only reach a *public* HTTPS URL. G132's rail was
   "loopback unless behind an encrypted overlay"; this adds one new exposure class under stricter
   terms: a **separate listener** (127.0.0.1:8765) serving only MCP, per-connector capability tokens
   (hashed at rest, shown once, scoped, expiring, revocable, last-used), tools outside a connector's
   scopes omitted from `tools/list`, no delete tools, and **Cicada never opens a tunnel itself**: the
   app shows the one Tailscale Funnel / ngrok command and detects the result. The Gemini consumer
   app has no custom MCP; Gemini CLI does.
5. **The mascot stays a bookworm; the page becomes interactive.** G127 (robot) stays DECIDE. The
   owner's "more interactive" amends G107's "no drag, no feeding" and G125's inert room: hover and
   click responses on the worm, a clickable pile and lamp, and **feeding = dropping a file on the
   worm imports it** (the one "feeding mechanic" that is also a real action). Art still encodes
   state, never quantity, and every art bit keeps a text twin. Detailed rulings in Track Z.
6. **Visual system "Meadow".** Liquid Glass only in the chrome layer (sidebar, toolbar, ⌘K panel,
   graph controls, one prominent action per page), gated `#available(macOS 26, *)` with a material
   fallback; warm "day meadow" / blue-green "night meadow" neutrals; nature tokens (sky, meadow,
   dandelion, cloud, bark, soil) for washes and art only, never data; **Instrument Serif** (OFL) for
   display ≥ 22 pt, **New York italic** for provenance quotes, SF for everything else; painted art
   (clouds, grass-and-dandelion edges, an onboarding hero) generated once with Codex image
   generation, bundled with a provenance manifest and `-dark` siblings. Art never appears on the
   graph, lists, grids, forms or anything that carries a number.
7. **Fast search gets a derived full-text index.** An FTS5 table (entities + aliases + claims +
   episodes + sources) lives beside the vector index: derived, disposable, rebuilt from markdown —
   allowed by ruling 3 (deleting it costs CPU, never a fact). ⌘K becomes a *find* palette with Ask
   as a mode, not the other way round.
8. **Recommended skills are proposals, installed by the agent's own installer after consent.** The
   video-watching skill is recommended with its terms note shown (it uses yt-dlp; Cicada itself
   still never derives a stream). Cicada stores watch *excerpts* with timestamps, not whole
   transcripts, under a new `media` evidence kind.
9. **Papers are `media` pages with `kind: paper`** (no new entity type, per the G2 closure), metadata
   from the official arXiv API and Crossref under the ToS rail, a summary, and a "why it matters to
   you" section anchored on the owner (G121). A project folder is a **watched folder source**: the
   app reads the folder and posts bytes (the backend never opens it), one episode per file, edits
   re-sync in place.
10. **Wispr Flow is the first note-taker adapter**; dictation history is opt-in, meetings keep their
    speakers, and secrets/one-time codes are scrubbed on every episode writer (not only the Stop
    hook).
11. **Workflow agents run on opus this round** (the owner's "best models with highest effort"), as
    round 2 did; mechanical steps stay on sonnet.

---

## Tracks and order

| Wave | Track | What | Depends on |
|---|---|---|---|
| 1 | **M1** Meadow foundation | tokens, fonts, motion + hover modifiers, glass modifier, art assets + manifest, sidebar glass, `EmptyStateView` art | — |
| 1 | **E** Engines | `claude-cli` hardened the Hermes way; `codex` engine + isolated sign-in; picker with marks | — |
| 1 | **R** Remote connector | `api/remote/` listener, capability tokens, scopes, provenance, "From anywhere" page | — |
| 1 | **F** Folders + papers | watched folder source, paper pages, why-it-matters | — |
| 1 | **N** Note-takers | Wispr Flow adapter, speaker-aware evidence, scrub on every writer, Voice & meetings category | — |
| 2 | **P** Provenance viewer (G118 s2) | evidence chips, span preview, conversation reader, contributors made legible | M1 |
| 2 | **S** Search everywhere | FTS5 derived index, alias/prefix search, ⌘K find palette | M1 |
| 2 | **O** Settings v3 + skills | Claude-style settings with search; recommended skills; video watch record | M1, R |
| 2 | **I** Imports + onboarding | one import pipeline, drop anywhere, auto-detect, onboarding v2 | M1 |
| 2 | **Z** The mascot page (Sleep v4) | interactive study room | M1 |
| 2 | **Q** Memory quality (Instinct) | standing/current primer, timeline tool, dated facts close, retract with provenance | R |
| 3 | **M2** Meadow pass | every remaining page, logos everywhere, hover everywhere; live check; screenshots | all |

Wave-2 designs are settled by a design panel before their briefs are written; their rulings are
appended below when decided.

---

## Wave 1 rulings

### Track M1: Meadow foundation

- **R-M1.** Neutrals re-tuned (day meadow `#F4F6F1` light background, night meadow `#0D1216` dark);
  data hues untouched (graph.js mirrors them). Every new hex lives in `CicadaTheme.swift` so the
  token lints hold.
- **R-M2.** Nature tokens `sky`, `skyWash`, `meadow`, `meadowWash`, `dandelion`, `dandelionFill`,
  `cloud`, `bark`, `soil`, plus procedural sky gradients (day, dusk, night). Never a data encoding.
- **R-M3.** `displayFont(size:italic:)` = Instrument Serif (bundled, OFL, registered with CoreText
  from `Bundle.cicadaResources`, bare `fonts` directory), ≥ 22 pt only; `quoteFont` = New York
  italic. The font lint extends to ban `.custom(` outside the theme.
- **R-M4.** `CicadaMotion` (nil under Reduce Motion) + `hoverLift()` for things that open something
  + `iconHover()` (wiggle on 15+, bounce on 14, removed under Reduce Motion). No literal `duration:`
  outside `CicadaMotion`/`SleepMotion`.
- **R-M5.** One `liquidGlass(_:in:)` modifier (distinct name from the existing `.cicadaGlass` button
  style), gated on macOS 26 with a material fallback and an opaque surface under Reduce
  Transparency; a lint bans `.glassEffect(` outside that file. Content cards stay a standard
  material. The sidebar stops painting an opaque background on macOS 26.
- **R-M6.** Art ships under `Resources/art/` with `art.manifest.json` (generator, prompt, date,
  licence, sha256) and an `ArtAssetTests` that checks hashes and `-dark` siblings. Clouds drift
  (≤ 8 pt, 60–120 s period, paused under Reduce Motion and in inactive windows); grass never moves.
- **R-M7.** `bundle.sh`'s `LSMinimumSystemVersion` aligns with the package's macOS 14 floor.

### Track E: Engines

- **R-E1.** One `claude-cli` engine, hardened: stream-json output parsed for the result and the
  rate-limit events; env scrub also removes `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` and the
  Bedrock/Vertex/Foundry switches (each outranks the plan and the probe cannot see them);
  `--setting-sources ""` next to the existing capture-off flags; CLI retries capped; Stage 1's
  "reasoning off" mapped to a low effort; an optional Stage-1 `--json-schema` that blocks
  `evergreen` and `deadline` and declares `evidence_quote`.
- **R-E2.** A `codex` engine: one `codex exec` per LLM call with the verified isolation flags,
  strict per-stage output schemas, the same concurrency/throttle/telemetry path as the Claude rung,
  `CODEX_HOME=~/.cicada/codex`. Status comes from a short-lived `codex app-server` probe (plan,
  rate-limit state, models) without spending quota. Non-fatal `item.type:"error"` lines are not
  failures; only `turn.failed` or a top-level error is.
- **R-E3.** Auto order: Claude plan → ChatGPT plan → Ollama → key. The scheduled guard covers both
  plans (decision 3). `CODEX_API_KEY` is scrubbed like the Anthropic keys.
- **R-E4.** The Settings → Sleep picker becomes a card row with marks (Claude, ChatGPT, Ollama, a
  key); the ChatGPT card's copy stops claiming it powers Sleep until it does; Ask follows the
  Settings engine choice instead of reading only `api/.env`. `pricing.py` knows the `prolite` plan
  string. No prices or tokens appear in the app.

### Track R: Remote connector

- **R-R1.** `api/remote/`: a second uvicorn server on `127.0.0.1:8765` started from the backend
  lifespan only when remote access is enabled, serving a Starlette app built on the official `mcp`
  SDK (stateless, JSON responses). None of the FastAPI routers are reachable through it.
- **R-R2.** Tool bodies move from `mcp/server.py` into `api/services/mcp_tools.py` behind a
  `ToolContext`; the stdio server's behaviour stays byte-identical (existing MCP tests are the net).
- **R-R3.** Tokens `cic_rc_<id>_<secret>`, only `sha256(secret)` stored, in
  `~/.cicada/remote/connectors.db` (0600, never in a bank). Scopes fail closed: search, read,
  record by default; raw sources, inbox answers and ask are opt-in; `pending`, `mark_processed` and
  `repo_context` are never remote. Expiry 7/30/90 days. Revoked or expired → 401 with
  `WWW-Authenticate`.
- **R-R4.** Two delivery modes over one verifier: a secret-path link (`/c/<token>/mcp`) for
  claude.ai/ChatGPT/Perplexity, and a bearer header for CLI/IDE clients. OAuth "approve on your Mac"
  is a later slice.
- **R-R5.** Provenance: `harness` is the connector's app label (`claude-web`, `chatgpt`, …); every
  remote write commits immediately with `Cicada-Author: <harness>`, a server-minted conversation
  handle as `Cicada-Session`, trigger `remote/<harness>`, no `Cicada-Engine`; claims carry
  `origin=remote:<id>` and an explicit author so the reconciler never stamps the Sleep model.
- **R-R6.** Fix before exposure: a private-address guard on `save_url`; MCP claim authorship; the
  handshake variant chosen by connector, never by a `claude*` client name; a remote write can never
  create an `observer=owner` claim.
- **R-R7.** The app's Settings → Agents gains "From anywhere": master switch (off), reach card
  (Tailscale / ngrok detection + one copyable command), new-connector sheet (logo grid, scopes in
  plain verbs, expiry), the shown-once screen with per-app steps, and the connectors list with
  "Never used" / "Last used …" and Revoke.

### Track F: Folders + papers

- **R-F1.** A watched folder is a source the *app* reads (security-scoped bookmark, FSEvents, the
  `BrowserWatch` pattern); it posts file bytes with relative paths; the backend never opens the
  folder. One episode per file through the G20 stager: an edit rewrites that file's episode in place
  and flips `processed: false`; a rename keeps identity by content hash; a deletion asks through the
  inbox like a bookmark removal.
- **R-F2.** Files under a folder the owner marks "agent-written" (e.g. research sweeps) carry that
  provenance so their text is never credited to the owner as `user` evidence.
- **R-F3.** Reference lists are parsed with no LLM into `media` pages with `kind: paper`; metadata
  from the arXiv API (≤ 1 request / 3 s) and Crossref (polite pool); never scrape arxiv.org. A paper
  page carries a summary (dated, world-fact cache per G121) and a "Why it matters to you" section
  built from the owner's own annotation and the spans that cite it.

### Track N: Note-takers

- **R-N1.** Wispr Flow first: the app reads its local SQLite with a column whitelist (never audio,
  never screenshots) and posts rows; the backend parses. Dictation history is opt-in; meetings and
  notes are the default.
- **R-N2.** Speaker-aware evidence: a meeting utterance by someone else is never `user` evidence;
  agent-written text is never the owner's words.
- **R-N3.** Secret and one-time-code scrubbing runs on every episode writer, not only the Stop hook.
- **R-N4.** Integrations gains a "Voice & meetings" category with real marks (fetched once through
  `scripts/fetch-logos.sh`, declared in the manifest).

---

## Wave 2 designs (settled by the design panel, 2026-09-23)

Three opus designers proposed the mascot page (companion / calm instrument / meadow window) and a
judge synthesised; two proposed onboarding + intake (guided / found-on-this-Mac) and a judge
synthesised; one designed Settings v3, the ⌘K find palette and the provenance viewer together. The
final documents are binding for their tracks and live beside this spec:

- `2026-09-23-round3-design-mascot-page.md` — Track Z (rulings R-Z1…R-Z14, tasks Z0–Z12).
- `2026-09-23-round3-design-onboarding-intake-home.md` — Track I (tasks T1–T12) and the G108 ruling.
- `2026-09-23-round3-design-settings-search-provenance.md` — Tracks O, S and P (slices O0–O6,
  S1–S6, P1–P6).

**Their owner questions, answered by default (review these):**

12. **Home becomes the front door (G108).** A search-first Home is ⌘1; Graph moves to ⌘2; the
    sidebar is ⌘1–7; relaunch restores the last tab, so nobody who lives in the graph is moved.
13. **One intake everywhere.** Every way a file arrives (window drop, Dock, menu bar, the Sleep
    worm, empty states, Home, File → Import ⌘⇧I) goes sniff → preview → import → a "what happens
    next" card. `UploadOverlay` and the Feed's Upload button retire (the one exception CLAUDE.md
    names disappears with them).
14. **Onboarding is one Welcome, then a Getting started card on Home.** The visible "found on this
    Mac" checklist is the consent; only the person's own intentional acts with no new permission
    prompt are pre-ticked (agent sessions from now on, readable bookmarks), and a line under Start
    says exactly what Start will do. The app may register the MCP server and the Stop hook itself
    after that consent, with the exact commands visible. The engine choice stays visible with each
    option's cost model (G117's 2026-09-04 ruling) and never blocks Start.
15. **Two consent defects ship first:** bookmark watchers import before any consent at first launch,
    and today's import hand-off in the first-run sheet skips the first Sleep.
16. **The mascot page (Sleep v4)** is the room, one serif sentence, one button and one schedule
    line, with everything else under one Details disclosure (closed by default, remembered). The
    worm notices the pointer (three gaze poses), answers a click with true lines (the last rung may
    point to the Inbox), eats a dropped file through the one intake, and cheers when a real cycle
    completes; the window shows weather that follows Sleep state on the room's one pixel lattice,
    with a legend popover as its text twin; the lamp and pile spines are controls. No autonomous
    beats without a fact behind them. The optional sky band above the page ships only if the
    screenshots say calm.
17. **Settings v3** groups: *Cicada* (General, You, Privacy & data, Memory, Sleep), *Customize*
    (Integrations, Agents, From anywhere, Skills), *Engines & keys* (Engines, Plans & keys,
    Advanced), with a sidebar search that also lists individual settings and highlights the row it
    lands on. Deleting a bank moves it to `<root>/.trash/` (reversible). The plan-window percentage
    stays hidden.
18. **⌘K becomes a find palette** (instant local tier + debounced server tier, grouped, keyboard
    first) with Ask as a mode; in-page search fields share one component.
19. **Provenance:** evidence chips with a hover snippet (quote font, a text speaker label — You
    said / Agent replied / From page / Inferred / a meeting speaker), a Reader that opens the whole
    conversation scrolled to the highlighted span with turn, time and harness mark, and "Where this
    came from" on every entity (contributors with marks, the conversations that fed it, coverage
    stated honestly for legacy claims without spans).

## Not in scope this round

G132 device sync (beyond the bearer mode serving it later), G131, G10's paid re-extraction (the
owner's clean run uses the new engines instead), passport connectors G31–G45, G94, G128, G110, G16,
G56, G99, mascot identity G127.
