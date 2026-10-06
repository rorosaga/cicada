# Backlog reference context and original owner prompts

**Historical reference, reorganized 2026-10-06.** Read [TODO.md](TODO.md) for current priorities and binding rulings, and [the active backlog](memory-evolution.md) for current scope. Dated descriptions, old file names, “awaiting” answers and old build statuses below are preserved context, not fresh implementation instructions. Current storage is Markdown/git plus disposable sqlite-vec; entity types remain closed; Ask and direct traversal both exist; selective sharing is requested design under G16. The full shipped implementation log is retained in git, with completed scopes indexed in [DONE.md](DONE.md).

## DESIGN — new structures (proposals, pending decisions)


## Media, previews & capture channels (Rodrigo — 2026-07-03)

New backlog captured from two notes on 2026-07-03. Theme: make memory **media-rich and multi-channel** — videos/images as first-class memories with agent-generated summaries grounded in transcripts, an image-rich preview layer in the app (less "Obsidian vault", more interactive), and low-friction capture from the places Rodrigo already saves things (messaging apps, browser bookmarks). Several extend existing items (G2 taxonomy, G3/M4 feed, G9 origin, G11 media preview, G14 mood-boards, R6 connectors) — cross-referenced, not duplicated.


## Context passport domains — app-sync & share-target (2026-07-13)

New backlog from the [`context-passport-roadmap.md`](context-passport-roadmap.md) gap analysis (code-verified two-agent audit against `dev` @ `ca345c9`) plus explicit owner requests. Cicada is a **passport of oneself** — conversations/bookmarks/projects/people/skills/calendar are covered; music, maps/travel, possessions/wishlist, and fitness are absent (❌ in the roadmap's coverage map). All connectors follow the shipped pattern: **keyless/local-first, episodes at capture, no LLM, dedup index, origin tag, Sleep consolidates** (`bookmark_sync.py`, `feed_registry.py`, `calendar_registry.py`, `notes_sync.py` are the four shipped templates).


## Absent passport domains — human-experience research (2026-07-13)

20 additional life domains surveyed beyond what Cicada already scopes, from a feasibility research pass. Opinionated take carried over: the highest-value additions are domains that are (a) already sitting in a local SQLite/XML file with zero API key and zero cloud round-trip, and (b) reflect *deliberate* signal (something the user chose to save/highlight/finish) rather than ambient exhaust (browsing history, screen time, raw transactions). Apple Books highlights and Photos metadata (via `osxphotos`) are the best-ROI connectors found — trivial to build, dense/durable context, fully keyless. Two domains from the research are **not** new line items: **Sleep-tracking** data is already covered by G36 (Apple Health), and most of **family milestones** is already covered by G46 (Contacts birthdays) + the existing calendar backlog (Track B5) — the only novel piece (a non-calendared one-off like "niece born") stays on the manual `/note` verb, no dedicated connector.


**Explored, deliberately deferred** (medium/low priority — kept here so future sessions know they were considered, not missed):

- **Podcasts listened** (medium) — Apple Podcasts local SQLite (`MTLibrary.sqlite`) is queryable, but lower-intentionality interest signal than reading/highlights; not worth a dedicated connector yet.
- **Movies/TV/games watched or played** (medium) — Letterboxd/Trakt CSV export covers movies/TV; games have no cross-platform export (Steam/PlayStation/Xbox all differ) — falls to the manual `/note` verb, not a connector.
- **Food, recipes, restaurants** (medium) — no structured export exists (Apple Maps guides don't export cleanly); reuse the G37 share-sheet save pattern for links, `/note` for offline meals — manual-first.
- **Subscriptions & recurring financial commitments** (medium) — Settings > Subscriptions has no Shortcuts/AppleScript export path; realistic route is manual entry or an on-device OCR pass that extracts only renewal dates and discards the screenshot.
- **Pets** (medium) — no export path exists by definition; pure manual capture via `/note` or a companion-app quick-add.
- **YouTube watch history** (medium) — Google Takeout JSON exists but requires a manual multi-step web flow each time (no automatable keyless route); diluted by autoplay/impulse clicks vs. deliberate saves.
- **Email (Mail.app)** (low) — rich in commitments/relationships, but full-inbox import is a privacy and noise disaster; only viable metadata-scoped-by-default with opt-in full-body capture — the noise-filtering/scoping logic is most of the work.
- **Browsing history & screen time / app usage** (low) — ambient exhaust, not deliberate signal (the opposite of bookmarks/RSS); ingesting reads as self-surveillance. If ever built: weekly aggregate stats only, never per-URL/per-app episodes.
- **Finances — transactions & purchase history** (low) — high-noise, high-sensitivity, mostly redundant with possessions/subscriptions already scoped (G34); poor context-per-privacy-risk ratio. If ever built: monthly category totals only, source CSV never persisted.
- **Documents & identity records** (low) — the metadata (an expiry date) is useful; the document content (a scanned passport number) is a liability with ~zero marginal context. If ever built: on-device Vision OCR extracts only a date, discards the scan.
- **Giving/volunteering & home/vehicle logistics** (low) — real but sparse/low-frequency; no universal export exists across charities/DMV/dealerships — catch-all via `/note`, not a connector.

---

## Repo-link layer (2026-07-13)

Project/directory entities can now declare a `repos:` frontmatter key linking them to local
git checkouts (path, optional device/remote/default_branch, optional declared `worktrees:`
list). `GET/PATCH /entities/{id}/repos` reads/writes only that key; live git context (current
branch, ahead/behind, dirty files, per-worktree state) is resolved **on demand and never
cached** — `git_service` shells out fresh on every call rather than persisting observed state
to disk. Surfaced in the graph as synthetic `repo:<slug>` nodes (one per distinct declared
path, edge "has repo" from the owning entity), and via the `cicada_repo_context` MCP tool.
See root `CLAUDE.md`'s "Repo links" subsection for the full frontmatter shape.

**Amended 2026-09-28 (the `~/Library` rail reaches folders).** The backend no longer runs git
in a declared repo — under launchd macOS named "python3.12" in the Files and Folders prompt.
`GET` serves declarations + `this_device`; the app runs the fixed command list and posts the
outputs to `POST /entities/{id}/repos/observed`, parsed by `repo_context.parse_snapshot`; the
last observation per `(path, device)` is kept in `$CICADA_HOME/repos/<bank>.json` (never in a
bank) and is what `_state.md` shows (stale past 7 days). The MCP tool still probes live, in
the harness's process. **Device-id drift — fixed 2026-09-28.** A declaration's `device:` was
compared as a string with `socket.gethostname()`, so a page written with a friendly name
(`device: Mac`) or under the computer name read as `other_device` forever. Now every reader goes
through `local_refs.is_this_device`: no device or a generic word (`Mac`, `this Mac`, `laptop`…)
is this Mac; otherwise the folded name must be one of this Mac's host, local host or computer
names (`scutil`). `GET` sends `on_this_device` per repo so the app never compares names; folder
registrations match folded too. Still open: a Mac *renamed* since the page was written matches
none of its new names — the same cross-device gap G92 and G132 name. Real values redacted.

---

## Live-conversation provenance & resume (2026-08-20)

Captured from Rodrigo 2026-08-20: memory should know not just *which harness* and *which model* wrote it, but *which specific live conversation* — and let you jump back into that conversation.


---

## Subscription-first portability (2026-08-21)

Captured from Rodrigo 2026-08-21: Cicada should be fully useful with **no API keys** — powered by the Claude or ChatGPT plan the user already pays for, connected into those same sessions. A 15-agent research workflow (repo grounding → Claude-plan/ChatGPT-plan/local-fallback/prior-art research → 5 adversarially verified claims → 3 candidate architectures → judged synthesis) produced [`subscription-first-portability.md`](subscription-first-portability.md).


---

## Connections, consumption dashboard & in-app ask (2026-08-28)

Captured from Rodrigo 2026-08-28. Design spec: [`../specs/2026-08-28-connections-and-consumption-dashboard-design.md`](../specs/2026-08-28-connections-and-consumption-dashboard-design.md); plans: [`provider-connections`](../plans/2026-08-28-provider-connections.md) · [`consumption-dashboard`](../plans/2026-08-28-consumption-dashboard.md). Research grounding (harness connection/usage UX, 2026-08-28): Claude Code `claude auth status --json` exposes `subscriptionType`; Anthropic forbids third-party apps intermediating claude.ai credentials (enforced since Feb 2026) → delegate to the CLI, never read the Keychain, never poll `/api/oauth/usage`; Codex `codex login status` + display-only JWT decode of `~/.codex/auth.json` (`chatgpt_plan_type`) + `codex login --device-auth` for a headless code flow; Claude Code's `~/.claude/stats-cache.json` is the cheap pre-aggregated source behind its `/stats`; LiteLLM's price table is the standard for usage-based cost.


---

## Learnings from Anthropic's Model Hardware Standard (2026-08-29)

Anthropic's MHS research preview (2026-08-27, [announcement](https://www.anthropic.com/news/model-hardware-standard-research-preview)) is a standardized *driver* for physical devices: onboard once (partly by an agent **interviewing** you), auto-generate a natural-language **reference file** with capability tags, make the device **discoverable** in a standard format, expose it over **MCP / CLI / code files**, keep live state in a documented **shared-memory state dictionary** that fresh agent instances coordinate through, enforce **safety limits below the model**, and let the agent **compile what it learned into deterministic scripts** instead of reasoning at every step. It is model-agnostic and will be open-sourced. Structurally this is Cicada pointed at devices instead of a person — a third independent convergence (after gbrain and Basic Memory, now from Anthropic) on "markdown reference files + MCP + progressive disclosure + deterministic layer beneath the model". **Thesis note:** cite as validation of markdown-as-driver, the deterministic-owns-safety split (G10 hybrid decision, trust gate, ambiguity guard, P0 auth = "memory safety limits enforced beneath the model"), and procedural distillation (Stage 4 skills). The four items below are what's worth salvaging.


---

## Inbox quality, entity logos, capture UX & onboarding walkthroughs (Rodrigo — 2026-08-30)

Five items Rodrigo raised after living with the merged sync engine for a day. Numbered in the
order he wants them tackled.



### Reference prompts (G73 founding example)

Rodrigo's raw directive of 2026-08-31 (Claude Code session `1d742a99-90a0-46a2-a0d9-4642052335bf`),
preserved verbatim as the first prompt-library entry — it produced G71, G72, G73 and the
paper-to-memory flow:

> ok i think then lets build to have the ability of receiving a message with a link sent to a
> companion app, which allows to have a message with some reason as to why we are saving this
> (but then w would need to think for a good ui for unified platform saves, (could be also a
> telegram bot, no need for a companion app yet), and for platforms that allow direct
> integration with API lets do it, and also for those that allow bulk data export, we can parse
> those. I'm thinking maybe an imports page, were the user can browse what platforms they can
> either conect directly and allow the app to read and/or, have a button that opens an overlay
> with a video and a link that takes you to the platform or the exact part of the platform where
> you choose to export the data, and you drag and drop or select it from files to the app. And
> parse runs as soon as they upload in that overlayed tile window, so in realtime the user can
> see the amount of videos we detect and what different folders we detect (have a scrollable
> list maybe with the amount of videos/posts/pins/etc in each collecton/board/etc.).
>
> The instructions for the imports can just be written, example: Settings > Accounts Center >
> Your information and permissions > Download your information > Download or transfer > Some of
> your information > Saved > JSON. Something easy to understand for anyone.
>
> Then i want you to document in the backlog this paper's idea of managing agent skills. I want
> you to do a separate UI page that reads from my global claude code, codex and all other
> platform skills so as to manage and help me propose how we can have different skills learned
> for different reasons and ways of doing things. FOr example here i have installed the browser
> harness and the macos harness skills, i use them a lot in claude code so maybe how can this
> stuff transfer and be compacted as the paper proposes? […]/reads/2608.27454v1.pdf . Read the
> paper.
>
> Finally i also come across a lot of ideas like this through a paper or something. I want this
> to be rememebered in the memory, the same way im mentioning it now, i wan this paper to be
> saved and maybe even you get the link to the paper in arxiv and have that as part of source in
> the entity stuff, and not just save it as the number, but as the actual title of the paper, so
> you interpret the contents.
>
> Copy this raw prompt and thinking int the backlog too for reference. And another idea i have
> is to be able to save or reference prompts i've used before like this one that were useful for
> soemthing (in this case the development of cicada), so the raw reference to this exact prompt
> and episode.


**Study room sprites handoff (2026-09-29, G176).** The full prompt Rodrigo hands a fresh session for the
bookworm and study-room sprites lives in
[`docs/specs/2026-09-29-study-room-sprites-handoff-prompt.md`](../specs/2026-09-29-study-room-sprites-handoff-prompt.md)
— kept as a file beside its brief so the two are edited together.

---

## Foundational decision history (historical, not current state)

These are the foundational forks; most of the backlog hangs off them.

- **D1 — Storage backend.** Stay markdown+git+LEANN? Move toward Postgres+pgvector (Honcho/gbrain)? Hybrid (markdown = source of truth, pg = index)? — _awaiting_
- **D2 — Entity model philosophy.** Keep closed 8-type set + promotion gate? Move toward Honcho-style emergent/belief/observer-observed (drop promotion)? Hybrid (entities + per-context dimensions)? — _awaiting_
- **D3 — Retrieval interface.** Add a natural-language `ask`/dialectic endpoint (agent queries memory in NL)? Keep direct file traversal? Both? — _awaiting_
- **D4 — Peers & multi-bank scope.** Build peers (humans/agents/robots equal) + multiple memory banks as a near-term feature, or research-only for now? — _awaiting_

> Answers (2026-06-16):
>
> - **D1 (storage): DECIDED (2026-06-17)** — markdown+git stays the source of truth; **add a derived embedding index, and Rodrigo is willing to go straight to Postgres+pgvector** (rather than sqlite-vec first) so pgvector + derived indexes land directly, then the ask endpoint. Research recommended sqlite-vec-first for a single-user bundle; the Postgres-direct path is viable because the index is *derived/rebuildable* — see dossier §D1 for the tradeoff. LEANN is being replaced either way.
> - **D2 (entity model): research-only** — no commitment yet; R4 + R7 findings inform it. Keep closed types + promotion for now.
> - **D3 (retrieval): BOTH** ✅ — add a natural-language `ask`/dialectic endpoint (answer + git-blame citations + gap analysis) AND keep direct file traversal. → unblocks A5; new design item.
> - **D4 (peers + multi-bank): research-only** — design the peer (observer/observed) model + multi-bank "memory projects", don't build yet. R8 informs it.

**Consequence of D3 = BOTH:** the `ask`/dialectic endpoint is now a committed design item
(not just research). It folds in A5 (gap analysis) and the Honcho/gbrain "answer not pages"
insight. Spec to be written once R1/R7 land. Everything else stays research-gated.

### Reference prompts (G77/G78/G79 — the voice-agent + gbrain + north-star directive)

Rodrigo's raw directive of 2026-09-01 (Claude Code session `1d742a99-90a0-46a2-a0d9-4642052335bf`),
preserved verbatim as the second prompt-library entry. It forwards a public build log by
[@KingBootoshi](https://x.com/KingBootoshi) (quoted inside it) and produced G77, G78 and G79:

> BOOTOSHI 👑
> @KingBootoshi
> I'm working on a very interesting voice agent problem I'd like to share with ya'll -
>
> First, my desire: I want to speak to ONE single consistent agent who handles EVERYTHING for me - this includes keeping track of (the present) + keeping track of projects + delegating work
>
> Stack shown in the image, but I'm basically using Hermes as the agent daemon + custom voice pipeline via Pipecat
>
> Here's the biggest problem: for the voice model to be an intuitive UX (as if I'm speaking to another human) the voice model has to be fast, which means it needs to be small, which means it can't be SUPER intelligent
>
> Now is the small voice model being not-so intelligent a problem? i have to see what PhoneLLM is capable of but my first thought is "yes it is"
>
> The idea is I talk to this voice agent (not so intelligent) who delegates tasks to Hermes agents (which are intelligent, but take a long time)
>
> We want to make sure that our direction we give via voice is NOT lost in translation by the voice model to Hermes - and vice versa. We MUST make sure what is being said by the Hermes agents is being properly vocalized to us, with nothing important lost in translation
>
> GPT-Live solves half of this problem of a fast UX by having the voice agent delegate to Codex agents. Unfortunately we do not have that latest ChatGPT tech, so what can the layman with hardware do?
>
> My current idea is UTILIZING the intelligence of Hermes agents in order to create OUTPUT packets in a conversational manner
>
> Instead of trying to squeeze intelligence and reliability out of the small voice model, we will instead force the output of the intelligent (Hermes) agents to speak in a way the voice agent can make NO mistakes in processing
>
> I actually imagined this voice agent being in a room with a green light that turns on and off
>
> Anytime a Hermes agent finishes work, it outputs a packet of everything we need to know, written in a way an absolute dumbass can understand
>
> Then the voice agent does not need to try to understand technical complex jargon, it just reads the packet to us, and inputs our response back
>
> It's quite a simple solution and I'm excited to implement and try this!
>
> I've gotten the Facetime adapter (that I open-sourced) working well and a daemon running on my mini that answers only calls from MY phone
>
> On the side I am working on a neural net that ONLY recognizes my voice to act as a form of voice authentication when I make the call (it does a great job at filtering background noise too)
>
> By FAR this is one of my favorite builds I've ever attempted, because when I succeed it should accelerate my general workflow 10x
>
> add this as inspiration of things to discuss as a to-do in the backend as there is some stuff here i want to implement. Also add to backlog to search if gbain's approach is actually better for what we try to do, or if there is something he does better that maybe we can learn from. https://github.com/garrytan/gbrain . Important also is to check https://github.com/garrytan/gbrain-evals so as to see if any of that can apply for us. and add to the backlog this thought that the best version of cicada is one that smartly gives and learns from all my experience as a human + the things that i've curated and might be relevant to me.

### Reference prompt (G96 — Ed Honour on vector search vs. the rest of the stack)

Forwarded by Rodrigo 2026-09-01, transcribed from a reel in his feed, preserved verbatim as the
source for G96:

> So vector databases and vector search are an important part of memory systems, but they are by
> far not the most important part. And the reason for this is a vector search is non-deterministic.
> It is very possible that when you do a vector search against your database, you are not going to
> return all of the records or the most important records that you're looking for. So what you want
> to do in a memory system is combine a vector search and a knowledge graph. So the vector search is
> the entry way into the knowledge graph, and then once you're in the knowledge graph, you traverse
> the knowledge graph. Now that is a really important concept, but it is not the only important
> concept. You can also find your way into a knowledge graph through relational databases. So a
> relational database may query a record, and then that is going to drive the traversal of the
> knowledge graph based on the record that you queried. So vector databases are important, but they
> are definitely not the only thing. And if I needed to leave one part out of my memory system, it
> would actually be the vector database. You can't get rid of the relational database, you can't get
> rid of the document database, and you can't get rid of the knowledge graph, but the vector
> database is not necessarily the most important thing, even though because it's new, most people
> focus on it.
