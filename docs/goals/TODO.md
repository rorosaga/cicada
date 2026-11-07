# Cicada — priorities and handoff

**Updated 2026-10-06. Today’s delivery priority:** G182 — make GitHub releases work today, automatically keep the released version/`main`/website links aligned, and complete the per-integration post-consolidation read/contribute checks. Release work must clear applicable integrity/packaging checks and report blocked or unsupported integrations honestly. [Release requirements](../specs/2026-10-06-release-and-integration-acceptance.md).

**Memory-quality pickup:** fix the relevant G183/G177 write-integrity gaps, repair G185’s reported test regression, then use [the first-memory-trial runbook](2026-10-06-first-memory-trial.md). Do a small trial before a full user-started drain. The immediate product question is whether asking ordinary questions about your life feels useful and trustworthy.

[Feature status: one line per feature](feature-status.md) · [Implementation review: every G ID](BACKLOG_IMPLEMENTATION_REVIEW.md) · [Active reasoning by priority](memory-evolution.md) · [Completed work](DONE.md) · [Reference context / original prompts](BACKLOG_CONTEXT.md) · [Working method](working-method.md) · [Cognition comparison](../research/2026-10-06-agent-memory-repo.md) · [Source/video gaps](../research/2026-10-06-source-refresh-and-video-gaps.md) · [Provider/source modularity](../specs/2026-10-06-provider-and-ingestion-modularity.md) · [Benchmark rebuild](../specs/2026-10-06-system-benchmark-rebuild.md)

**Pick up here (2026-10-22, redesign):** read ruling 36 (the owner's answers D1–D6 to the redesign proposal), then [`feature-status.md`](feature-status.md) for what is building. Branches in flight: `feat/awake-read` (G207), `fix/people-dedup` (G209), `feat/update-sources` (G61); queued: connection model and providers (G217, G50), agent API (G213), app (G217's pages, needs a Mac). **Decided after review (2026-10-22, in ruling 36):** a new install's Auto uses a signed-in plan, a key offered as an equal option; ruling 4c stays and the quick read follows it; G213's API rides the G135 listener; "Where to check" as one grouped inbox review; `rich` + `questionary` approved. Nothing waits on the owner from this ruling. **Ruling 38 (2026-10-23)** decides the follow-ups: `/v1` from the tool table (G213), a capture-only phone (G91), one-way syncs (G219), traces with screenshots (G218).

**Inbox order (2026-11-06, ruling 70, G113/G115):** `GET /inbox`, the catch-up and `mode="ask"`/`"list"`, recall's question block, the recall hook's pointer and a web lookup's order are ordered by `question_order` (the expected change in what gets read, lowered for a fact said long ago), fed by `page_use` and the new read counter `page_reads` (not the ledger); read ruling 70 before touching the order, its constants or the counter. In flight: #673.

**Browser-read sources (2026-11-05, ROR-114, G206/G228/G232):** Instagram, TikTok, Reddit and Pinterest (with X and LinkedIn) have one "Read through your browser" switch; a source read that way has its own colour and words (not the green of a connection), a "Signed out" state with Try again, and the person's handle and profile link on its page; YouTube's and Substack's lists show the same states, without a handle. Why the switches were missing: the app's set stayed at three lists after #596 and Instagram's switch sat beside a refused site grant (`app.md`, DESIGN_RULES §9 2026-11-05). Freshness limit (by design): signed out is learned only when an agent tries the page. T3 Code is no source row. Mac tests are for the owner's shell: `swift build --build-tests` only here.

**RSS by feed (2026-11-05, ROR-108, G89):** the RSS page lists its feeds, each opening in place; polls stamp an item's feed and keep a failed result as a code. Live items gain their stamp on the next poll; until then they file by host or under *Other*.

**Chats (2026-10-28, G179):** WhatsApp live chats in their PR (`feat/chats-live-whatsapp-telegram`; the source-agnostic `chat_live` engine). Telegram under ruling 47a is its own PR (`feat/telegram-live`), one-to-one chats only with the person's per-chat confirmation of the other side's consent (the owner, 2026-10-28, after Telegram's AI terms). 2026-10-29: the connect sheets go one step at a time with a country picker (`feat/connect-sheets-modern`, DESIGN_RULES §9 2026-10-29).

## Current state and evidence

- **2026-11-06 — question settling (G98, ROR-31; branch `question-settle`, PR 2 of the question audit).** The dry run's decisions 1–8 taken as recommended (ruling 73). Built, nothing applied to any bank: `same_value`, `moved_on`, `own_bookkeeping`, `already_described`, `not_fading` (all vetted); `same_conversation` dropped; rivals written closed on a pick and when a later value wins; no page line when no value changed; a new contradiction opens its own question; "Is X your partner?". Left alone: the 37 piled-up questions (splits), fading (ROR-129; 31 decay questions held), the 16 same-spelling merges. The next drain after merge applies the rules to existing questions (a bulk write): regenerate the dry-run hashes on a fresh clone and use the vetted apply first.
- **2026-11-06 — Ask finds what a new memory holds (G148, G76; branch `prod/ask-small-bank`).** A word in over half the conversations ranked nothing, so a one-conversation bank had no words at all and Ask said nothing matches while recall found the turn. `COMMON_FLOOR` (5 conversations) stops that; a bank past ten conversations reads as before, the benchmarks' banks included. Found walking a stranger's path before the first Sleep.
- **2026-11-06 — Ask says why it failed (G148; branch `prod/ask-words`).** `ask_failure`: a model call that raised is worded from Sleep's classifiers (plan window or week, overage, key limit or refusal, sign-out, timeout, dropped connection) with its fix and a reset time only when the vendor gave one; additive `failure`/`resetsAt` on `/ask`; the app shows the sentence, keeps it out of Recent and waits 600 s; the MCP direct path resolves Auto (before: "no engine" for a signed-in plan) and a slow backend is no longer answered twice. **Pick up here:** try a real plan limit in a scratch app (only stand-in failures were run). No ruling changed.
- **2026-11-06 — a stranger's first engine and first file (G76, G92; branch `prod/first-engine`).** A Mac without Claude Code
  showed "Use my Claude plan · Not connected" with no button and no words: the plan rows (Settings, onboarding's
  Intelligence step), the engine cards and the Sleep pre-flight now give the vendor's own installer line (a stranger has no
  npm; `connections/install_hints.py` is the one place, a gate test fails on any other spelling), and the row changes on
  return to the app without quitting. A bad file is named with what is wrong and which file to drop (never the parser's
  message); a large export no longer ends "The request timed out." while the import runs (measured: a synthetic 150 MB
  export sniffs in 110 s and imports in ~3.5 min on a busy Mac, almost all of it the secret scrub); a watched folder says
  which files it left out. **Pick up here:** `swift test --filter FirstEngineAndFileTests`; drop a truncated `.json` and a
  broken `.zip` in a scratch app. Not shown in a verify run: the plan row at "Not installed" (`plan-claude` always answers
  for the Claude plan) — proved by view-state tests. No ruling changed.
- **2026-11-06 — Sleep's start and the engine pickers fail in words (G92; branch `prod/sleep-words`).** `TriggerSleep` shows a 409's own sentence (this memory is moving) instead of one fixed line; the engine card and chooser no longer print a transport error and had no way to retry short of leaving the page. Run `--filter '(MutationTests|EngineQuickMenuTests|StoreTests|Lint)'`.
- **2026-11-06 — a conflict answer writes the value only the question held (G98, ROR-31; branch `conflict-off-page-value`).**
  "Both", a pick of the off-page value, "both" on a description question and a multi-valued dismissal each dropped a value;
  each now writes it. No bank write. (The rival a later value drops is closed by the question-settling entry above.)
- **2026-11-06 — a backend that stops answering (production blocker; G182, G92; branch `prod/backend-watch`).** Measured: SIGTERM to the app's own backend left nothing listening, nothing restarting it and pages reading the silence as an empty memory. `BackendProcess` restarts a child the app started (5 tries, 2/5/15/30/60 s, count begun again after a 60 s run; never over a held port, never launchd's); `BackendWatch` looks at `/healthz` only while the event stream is closed and the shell's one line says not answering / port held / key refused, clearing by itself; a slow answer is judged by `BackendSilence` (ruling 66's bound, reused); `Store.couldNotRead` is the one predicate Graph, Inbox, Sleep's away-sync lines and the entity card's beliefs ask before saying empty. **Pick up here:** the live app check (kill the child, screenshot Graph/Sleep/Home) is in the PR; a hung backend shows only after ruling 66's two hours by design. No ruling changed.
- **2026-11-06 — Goodreads and Spotify through the person's own browser (ROR-128, G233, G232; branch `goodreads/agent-read`, stacked on `books/choose`).** Ruling 72. Both join the saved lists (`saved_lists.PLATFORMS`, `reading_settings.SAVED_LISTS`, off until the person turns one on); Goodreads' books wait in `goodreads_waiting` for the pick list, Spotify's are index-only saves. **Pick up here:** merge #666 first (this branch sits on it); then open Sources → Goodreads in a scratch app with a stdio agent, turn the switch on, have the agent record books, pick some. Not run: the full suites, the Swift tests, a real Goodreads or Spotify page (the item shape each page gives is the agent's to read).
- **2026-11-06 — choose what goes in (G233, G39; branch `books/choose`).** Goodreads preview lists the books and the import takes `ids`; Apple Books holds never-accepted books for the person's tick (declined ones remembered, accepted ones kept current). A scan stays one explicit add. Each row shows its cover thumbnail (Apple Books' cache; a Goodreads ISBN through `choice_covers`, no cover = no picture). **Pick up here:** Swift filter `AppleBooksReaderTests`; open both doors in a scratch app. No ruling changed; piece 3 (descriptions, relevance at linking) waits on the owner's DECIDE.
- **2026-11-06 — question words (G115; branch `question-words`).** Part 1 of the question-quality audit, all at read: `inbox_wording.present_options` (served list, catch-up, MCP readers) dates a conflict's sides by when each was said and drops the check's working words; the voice, the bare-value noun, "X came up", the decay answers and the alias-removal question; `SHAPE` on the inbox ETag; forward writers (`refresh_open_questions` bump, `_claim_option`, both contradiction prompts). No sweep, no setting, nothing stored changes but an option's `source_episode`. **Next:** measure on a read-only clone of the live bank before merging; parts 2+ (reconciler respellings, the description pile-up writer, `both` minting) are not started. `question_order` (ROR-125) untouched.
- **2026-11-05 — the book scanner (G233; branch `books-scanner`).** Scan opens a camera window over the app: the book outlined, the barcode marked on its own corners, the number taken by itself (3 analysed frames in a row), the window left open for the next book. **Pick up here:** Swift filters `BookScanMathTests`, `Lint`, `CicadaMotionTests`; the owner tries it with a real camera (the live frame rate and highlight placement are theirs to judge).
- **2026-11-05 — a scanned book's page is worth opening (G233; branch `books-page`).** Lookup merges the edition, the work and Google Books (authors, a 700-character description with its source and day, publisher, subjects); a v1 cached lookup is asked again once; no placeholder line anywhere; the page leads with the cover and facts; the Add shows the book and opens its page; a scan is one label with its day and in no list or search. **Pick up here:** run Swift filters `BookAddTests`, `Lint`; open a scanned book in a scratch app. No ruling changed.
- **2026-11-05 — added files are found by the words inside them (ROR-117, G43; branch `ror117-words`).** `file_words`: an FTS5 table in the derived search index, fused per passage with the meaning leg; the palette's prefix pass asks `file` too; a hit lands on the segment that says the word; the Mac reads the text in kept frames (on-device) and posts it with the frame (`record_frame_text`, the function a photo item calls). Words leg p50 0.7 ms, +1.1 ms p95 on the palette at 25,000 passages (`storage.md`). **Pick up here:** run the Swift filters `MediaFileIndexerTests`, `FindPaletteFilesTests`, `FindServerTests`, `Lint` (not run in a worktree agent); a photo door should call `record_frame_text`. No ruling changed.
- **2026-11-05 — multimodality scorecard and Voice Memos as a source (G43, G195; branch `multimodal-g43`).** Owner: rate every
  kind to a 10; later: play and show everything in the app, each item an entity with a markdown body (summary, why it matters,
  the transcription, the transcribing model as contributor). [`multimodal-scorecard.md`](multimodal-scorecard.md) scores YouTube,
  screen recording, video file, image, audio file and Voice Memos on what exists (today the added-file kinds open in the default
  app, have no page and no lexical leg). Built: Voice Memos through the `media_files` store (`storage.md`); ROR-117 feature 1, play and see it in the app (`MediaSheet`: a hit plays at its second, a photo is an added-file kind with a viewer, File → Added Files…; `app.md`). Run `--filter MediaViewerTests` too. **ROR-117 3a (ruling 68, branch `ror117-page`):** every added item has its own `media` page (`media_pages`), the words outside the bank, the transcriber a contributor; run `--filter MediaPageModelTests --filter WikiArticleTests --filter ProvenanceSummaryTests`; **ROR-117 3b (ruling 68 (e), branch `ror117-read`):** Sleep's tail and `Read it now` write the Summary and Why it matters (`media_read`); run `--filter MediaPageModelTests`. **Pick up here:**
  run the Swift filter below; open the tile once against a scratch `HOME` holding a synthetic store; check the real
  `CloudRecordings.db` columns by hand (never in development). **Owner decisions, undecided:** may Sleep read memos and as
  whose words (a page per added file and naming the transcriber are decided: ruling 68). YouTube extraction stays out (G162).
- **2026-11-05 — no source asks for a secret (ROR-113, G219, G232; branch `notion-oauth-no-token-forms`).** The owner: "Any one that you ask for a token fucking find a way to sync it properly, either direct integration, syncing some other type of way, or browser as last resort." Notion signs in through its hosted MCP (OAuth + PKCE, read-only tool allow-list) with a Connect button; the Reddit, X and Pinterest forms, GitHub's token field and the Telegram bot tile (unless a bot is already set up) are gone from every app surface; a connector already connected keeps its row and Disconnect; a Swift lint fails on a secret field in a source surface. Notion's page says in one line that the sign-in acts as the person. Binding until the owner rules otherwise.
- **2026-11-05 — Linear is a source, and none of its text is the person's own words (ROR-115, G242; branch `ror115-linear-source`).** Signed in by browser (hosted MCP, read-only endpoint, three read tools), issues and comments as episodes through the normal capture path. Agents write Linear under the owner's own account and Linear's read API cannot tell that from the owner typing, so a comment under his account is `assistant:` (claims `external:linear`), never `user:`; another user's is `speaker:<label>`. Revisit only on the DECIDE in G242 (a switch, or a positive signal). Not verified against a real workspace: the sign-in and the real response shapes.
- **2026-11-05 — agents can look into what Sleep has not read (ROR-29, G207; branch `ror29-ask-unread`).** Ask reads an
  unread conversation or note whole when short, else by its matching passages, in one 4,000-character budget per question,
  labelled "not yet read by Sleep"; Citations are what the answer rests on (an empty `used_entities` no longer means every
  retrieved page); `cicada_pending(query)` uses recall's two legs and leads with the newest; the primer says so (+~31 tokens).
  Index-only records and locked notes are still never read; no setting. **Not run:** an `answer_eval` comparison on haiku
  (needs the scratch-home harness). **Pick up here:** decide whether to run it. Detail: `memory-evolution.md` G207, `mcp.md`.
- **2026-11-05 — a citation opens its source on its words, one standard (ROR-16, G118; branch `ror16-evidence-spans`).** One
  judge and wire shape (`source_spans`), one drawing (`SourceSpansView`), `GET /episodes/{id}/spans` by page; the demo gains
  a note, a meeting and a book, plus one stale and one held. **Pick up here:** the click proof in the scratch app and
  `swift test` were refused by guards in the worker's shell (`HOME=`, sourcing `harness.sh`, overlays over the window), so
  they wait for the coordinator; then ROR-15 as the thin use `app.md` describes.

- **2026-11-05 — an Apple Note reads as the note (ROR-15 part 1, G161; PR #638, branch `ror15-notes-formatted-view`).** The Reader shows
  the stored text, then the note's `body` from Notes (one note, on view, locked filter inside Notes, memory only, never posted)
  as native blocks tied to the stored offsets; any mismatch or failure stays plain with nothing said; Notes closed stays plain
  (never launched). Not yet seen on a real note: the HTML shapes come from Notes' dictionary and knowledge, not from reading
  the owner's notes. **Pick up here:** first open of a real note with Notes running, then part 2 (pinned notes).
- **2026-11-05 — a pinned Apple Note (ROR-15 part 2, G161; branch `ror15b-notes-pin`).** The app reads `ZISPINNED` (pinned, unlocked,
  `Z_PK` alone) from a copy of Notes' store only with Full Disk Access already held and posts `pinnedNoteIds`; the note's episode
  carries `pinned: true` outside the hash and the queue, its row lists first under "Pinned", and Stage 1's source note says the
  person pinned it — the model judges, no score. Not yet seen on a real store: the `p<Z_PK>` id mapping is Apple's documented
  Core Data format, not measured on the owner's file. **Pick up here:** with Full Disk Access on, sync Notes and check that the
  owner's nine pinned notes list under "Pinned"; checklist ticks stay the owner's decision.
- **2026-11-05 — open a source's item where it lives (ROR-111, G161; PR #630, branch `ror-111-open-in-place`).** One control on the
  item row: Notes by its own id, GitHub, saved links, feed items, saved videos. A list says only the kind; the place is
  read on the click. Not yet seen in the real app: the first press against a real note is the person's. Which sources
  have it and why the others do not is on G161.
- **2026-11-05 — A chat over Messages reads as a chat (ROR-109, G179; PR #628).** The Other agents list filtered on an empty `harness` field while its card counted by `source_key`; both now read `source_overview.row_key`. Reproduced on synthetic data. **Pick up here:** on the live install, `GET /conversations/recent?harness=unknown&limit=200` should return exactly the card's one conversation.
- **2026-11-05 — Sleep asks only what the person alone can answer (G239; PR #623, branch `noisy-questions`).** A run read 53
  conversations and raised 25 questions; the causes were proxies standing in for the model's judgement. Stage 1 now says what
  rests on a question, the judge is told what UNSURE costs and reads the lines naming both, Stage 4 asks for how the person
  works. Two real Sleeps a side on invented notes: questions 7, 6 to 4, 3, noise 5, 4 to 1, 1, phrase `skill` pages 3, 2 to 0, 0,
  the question that matters 0 of 2 to 2 of 2. Nothing has run on the real bank. **Decided (ruling 65, owner 2026-11-05):** questions on the model's stake, a thing in motion counting; any skill on 2+ conversations.
  **Within it, for him to rule on:** a public thing that gets `ask_person` stays with the person and is never looked up (`web_settle.py`, `person_context`), a narrow exception to ruling 27. A question asked on purpose is closed only by the person's answer or their own located words (ruling 29), never by a later confident mention.
  Two notes ground a skill; no new tidy rule for existing person questions (`passing_rule`, `_merge_rule` keep them; a new bank is planned).
- **2026-11-05 — the Stage 2 stall (G238, PR #620).** A scheduled Sleep held the event loop about 7 minutes at 8,500
  pages: a parse of the whole pending store per project page per project name with no page. Fixed and moved off the
  loop. **For the owner:** the auto-updater reads a timed-out `/sleep/status` as nothing running, so a stall past 2 s lets
  an install stop the backend during a run (G238, open item a). Left as it is, pinned by a test, pending a ruling.
- **2026-11-05 — the Sources root is a grid of apps (ROR-7, G217, G161; branch `ror7-sources-grid`).** Needs you, Connected,
  Suggested, then categories by what a source is; a search with no network and no model; one click opens the standard
  source page. A company is a search word, never a group (the reasoning is on G217). The Connected section is exactly what
  the eyebrow counts, so the row #619 left reading Connected for a borrowed reader keeps its dot in its own category.
  No new route: everything is derived from what the page already held.

- **2026-11-04 — phone numbers on the right page, ruling 55, decided 2026-11-05 (G81; PR #603, branch `g81-phone-numbers`).** Owner: he texted
  an agent two people's numbers and expected memory to map and follow them. Built OFF (the switch file `numbers_switch.json`), never
  run on real data: a token in the bank, the digits in a vault on this Mac, shown on the person's page and in the Reader.
  Proved through real Sleeps at haiku on scratch state, with a restatement, a change, a held name and a question.
  2026-11-05: cut down to what is explicit after four review rounds: a phone word, an add/save with a capital at 9+, a change with a phone word, or 9+ the vault holds; "Ana N" stays in clear (ruling 55). **Owner 2026-11-05: yes**, amended: a number on a Contacts card is that card's by value, and a `+` number is kept (branch `g81-contacts`). **Pick up:** the sub-answers; whether a one-time recovery of blanked numbers is wanted.
- **2026-11-05 — integration-test defects (ROR-41; branch `ror41-integration-defects`, PR #619).** The embedding children are
  all capped (ONNX text child 677 % to 344 % CPU, synthetic bank); Apple Books' refusal names its fix; a gated feed's
  line names the switch that turns it on; a reader counts once in the Sources eyebrow; `install_app.sh` signals by path;
  Grok's install line is the command; OpenCode's Electron path is found; a measured quantity that moves is no contradiction, an agreed price in dispute still can be (G98).
  **Owner's call, left alone:** a backend the app spawns runs with `CICADA_ALLOW_FEED_FETCH` off (`network.md`).
  **Pick up here:** two rows still read Connected for one reader, the count is the only thing that dedupes; same-day
  value claims still ask (`claim_reconciler.trust_decision`).

- **2026-11-05 — the Inbox's rebuild back under budget; five test-health fixes (G209; branch `devhealth-flakes`).** The
  bench failure written off as a flake was real: since 6a410524 (G209, a same-person question rests on a conversation
  naming both) each person question with no pairing conversation on hand ran four searches on every rebuild of the list.
  At 4,700 pages / 913 items, 221 of them such cards: 0.19 s CPU before; 10.6–15.9 s with no index yet (each search walked
  every page's frontmatter though it asked only for conversations, and started the build, whose CPU the read also
  paid); 0.52 s with one. Now one query a card over one connection and no build: 0.23 s and 0.24 s (`features.md`).
  Test fixes: Stage 3's two
  calls run at once (order never pinned, each answer still on its own page), Ask's tree hash leaves out derived files,
  a missing Pillow skips, real-git identity tests allow a loaded machine more than the hook's 0.1 s (unchanged), and
  `test_the_command` no longer asks this Mac's real backend for `/healthz` (its "flake" was that backend not answering). The
  stale proposed ruling 54 is gone; the decided row now carries the local agent's test it pointed at.
- **2026-11-04 — waiting on Reddit, not the owner.** Reddit API access was requested 2026-11-04. When Reddit approves,
  register the installed app per `network.md` ("Registering Cicada's Reddit app") and set `reddit.CLIENT_ID`.
- **2026-11-04 — hookless apps relay as they talk; exports are one-time (rulings 57, 58, below; G105, G197; branch
  `ruling-57-58-relay-and-one-time-exports`, PR #604).** The Claude desktop app's local connection is offered and asked for
  `cicada_capture_turns` by exact client name; a hook-captured harness never is, whatever it calls itself. #592's weekly
  nudge and Downloads pickup are gone; it never reached a release. claude.ai on web and phone and ChatGPT reach the
  relay only through a public address: ruling 59's one click, whose first real run is the owner's. A chat that goes on after its import keeps its later turns, marked as relayed, in the same episode
  (ruling 58, amended the same day).
- **2026-11-04 — Sleep on a Claude key through the official SDK (G237, ruling 63; branch `g237-claude-key-parity`).** Owner:
  "having cicada work the same or as good as through Claude code is crucial and priority." The audit found a Claude key
  could not have run Sleep through LiteLLM at all. `anthropic_engine` serves it now, with `direct_engines` as the seam the
  next provider's SDK slots into. Caching, the key's own model list, tiers, retired ids moved forward in words, prices with
  their basis, a 429 as a pause. Proved on stand-ins at the HTTP layer, the real SDK in between; the plan leg ran for real
  on Haiku 5.5. The review's four blockers are fixed; a run on a key now stops at the person's spending limit (ROR-102,
  ruling 63 (g), suggested $5 a run), about one read past it plus filing, and only runs are covered. **Pick up here:** the owner enters a key and runs G237's one command (a cap of 40,000
  uncached tokens, expected about $0.02), checking the SDK's Bearer header first. Nothing has reached the real API yet.
  **The owner decides:** the plan-only steps, the web lookup a key now runs by default (ruling 63 (i)), and whether a
  scheduled run at its limit should wait for a click, as built.
- **2026-11-04 — what may be sensitive: held back or reported, one review, Remove (G235, ROR-94, ruling 60; branch
  `g235-sensitive-flags`, PR #611).** Owner: "surface anything that may be sensitive… so the person knows if it passed
  through a provider"; "Yes hold them back"; "remove any sensitive data". Numbers, measured kinds and what stays open are
  on the row. Real bank: 16 conversations of 9,478 hold a hit; **precision on real data is unknown, since nobody read a
  value.** **Pick up here:** the owner's "remove any sensitive data" is applied with `scripts/sensitive_removal.py`:
  read its dry run, then `--apply --plan <its stamp>`. It commits the older version first, then removes from memory only: a password stays in the Notes app or chat that holds it,
  and any real one among these should be changed, because what an engine read cannot be unread.
- **2026-11-05 — what the person marked in a book: word for word, read for its themes, lights the page (ruling 64, ROR-95,
  G39; branch `ror95-book-highlights`).** `book_marks` is the one writer; `marks` is a new page block (`blocks-4`, the app's
  `PageMarks`). Private-use characters stripped from what Apple Books posts. Not exercised: the app's reader against the real
  stores, and `PageMarks` on screen. Pages already made keep a private-use character in their author until that book changes.
- **2026-11-04 — a save with no reason gets a lean pass; a batch is bounded by what it holds (ruling 62, G236; branch
  `feat/g236-lean-pass`).** Owner: "a leaner initial pass … on those things who have no reason/user intent attached, but
  enough info so that it can come up in a relevant conversation and an agent can look further into it." A bare save is
  `history_index.kind` `saved`: indexed with no engine, found by recall, Ask and the hook (`saved_lookup`), read once when
  the person talks about it (`saved_mentions`). 25 bookmarks: 57 calls and 272k input tokens before, 0 after; recall 12/12
  both, the hook 3/12 to 12/12. A batch also stops at 60,000 bytes, so the owner's 22-item shape commits after 11 calls, not
  54. **Pick up here:** the real bank's first run retires what waits (`history_index_dry_run` counts it first); the Swift
  suites and the two app lines want the coordinator's shell (the harness refused a scratch `HOME`); the 180-call run's split
  is in its ledger. Review: a sync no longer takes back a woken group's read; Ask shows a tab group only with `sources`.
- **2026-11-04 — books: a chat changes a status, covers (ruling 61, ROR-95; branch `ror95-books-status-covers`).** Stage 1's
  `reading_status` mark, checked on the record (`book_said`), through `books.set_status` and `progress.py`; held on the episode
  when no page is clear; *Not right* on the book's page. Covers: Apple Books' own from the app, else Open Library by id or
  ISBN, never a title. *Book scans* on Sources. Highlights quality is untouched (under separate test). Verified end to end on
  scratch state at haiku (`capture-and-sleep.md`). **Not yet seen on screen:** the app builds, its tests and a look at the
  cover and status line wait on the coordinator's run (a scratch `HOME` and the harness are refused in this worktree).
- **2026-11-04 — rulings 54, 54a: the settling step works like an agent; what leaves is held in code; a page's own
  sources come first (G209, G61; branch `g209-ruling-54`).** A model with no tool reads anything in memory through a table
  Cicada runs; `name_guard` checks every query and link; a separate search hand holds only cleared queries; Cicada opens
  pages on the link rail. On by default on the Claude plan, off everywhere else. 6 searches, 6 pages, 8 turns a question; 3
  handles and 5 questions a drain. `contacts_book`'s names (#602) are guarded too. Owner decisions are in the ruling's row and the PR.
- **2026-11-04 — one click to a public address for the connector (ruling 59, G135, G132's D6′; branch
  `feat/g135-funnel-one-click`).** Owner: yes to D6′, since claude.ai and the phone apps can only reach a public address
  and `/remote/status` on the live install reported no listener and no funnel. Built and proved on a stand-in binary and a
  scratch listener; **no real funnel has run**, that is the owner's click. Read-only `tailscale status --json` on this Mac
  (key names only): HTTPS certificates and the `funnel` attribute are not yet granted, so the first click meets the
  tailnet step and shows Tailscale's link. Waiting on the owner: that first click and a request from a device off the tailnet.
- **2026-11-04 — the Contacts page shows every card (G154, G161; branch `g154-contacts-grid`, PR #602).** Owner: "only 6
  contacts synced". Coordinator's numbers: 370 cards waiting, 6 matched, and the page listed the 6; one-part names were
  kept nowhere (196 + 139 raw records across two account sources, which overlap). `contacts_book` keeps every card's names
  and thumbnail for the grid alone; ruling 33's match rules are untouched. Thumbnails: few is true of the book, at most
  6 of 969 raw records (count-only query of the store files; size and format not measured, because no shell here has a
  Contacts grant). The grid reads it: a card with a page opens it, the rest are quiet discs that are not controls.
  Review of #602 caught the page going blank for someone already connected (no sync due, so no book posted): the book's
  own state now decides when it is posted, and the page draws a skeleton while it is on its way.
  Detail: `capture-and-sleep.md`, `app.md`. **Known residue:** `UserDefaults(suiteName:)` in Swift tests lands in the real
  `~/Library/Preferences` whatever `HOME` says (cfprefsd ignores it): 5,621 `contacts-<uuid>.plist` files since 2026-09-24,
  test values only. These two suites now empty theirs, leaving a 42-byte file; the class is not fixed.
- **2026-11-04 — Wispr Flow off the offer for now (G134; branch `wispr-hide-from-sources`, #613).** Owner: "remove
  wisprflow also from sources for now." `SourceCatalog.wisprOffered = false` is the one line that brings it back. Gone from
  Sources, onboarding, the notch and Settings' list of Noes; a Getting started row that ticked it drops. The Permissions
  step and the find palette never offered it (⌘K lists a source only with evidence, and that row opens what came in, with
  no Refresh). **The reader stops for everyone, connected or not**, because a row that is gone cannot explain a reader
  still running; the setting and cursor stay, so it resumes where it stopped. Nothing captured is deleted or retired.
  **Kept on purpose:** the routes, the channel row and `source_overview.CATALOG` (it names old episodes' origin, and a row
  there needs evidence, so it offers nothing), so an older app keeps working. Wispr's own hosted connector stays among the
  recommended skills: it is not a source Cicada reads, and the owner's words were about sources.

- **2026-11-04 — three owner reports: a tool inside its app, a plan that is back, one inbox (G50, ROR-52, ROR-96, ROR-46;
  branch `fix/g50-bundled-tool-detection`).** OpenCode.app's `opencode-cli` is found; an app without the tool Sleep needs
  says *Not ready* and the line to run, on the cards and in Auto's skip sentence (`Status.not_ready`). The real bundled
  tool (1.3.3, scratch home) has no `--pure`, so on the owner's Mac it reads too old until the app is updated or the tool
  installed; rail 3 is never loosened to make it run. A message after `--file` was read as a second file on it, so the
  message now comes first. A paused run past its reset says the plan is back and to continue, on its own at that moment
  (`nextClockEdge`), no past time anywhere on the page; Continue resumes the same run, proved with the route and the real
  run on a reset an hour and a half gone. Ruling 15 stands: a weekly pause still waits for the click. Sources wears `tray`,
  the Inbox page `tray.full`, ⌘K's word for it. **Pick up here:** a signed-in call through a bundled tool, and a spawn from
  the launchd agent, are unverified (G50's row); Grok's install line points at an address that answered 404.

- **2026-11-04 — This Mac source pages: accounts → collections → items (G161, G154, G95; branch `this-mac-sources`,
  PR #599, on the standard layout #593).** Owner: Apple Notes, Reminders, Contacts and Calendar "should
  have a better user experience and UI". One browser fills the standard page's content slot (`ThisMacSourceContent`):
  accounts by real provider with their own marks → folders/calendars/lists → items, one search, the Reader as the item
  view; Contacts as faces (photo, else monogram); recorders as recorder → folder → meetings (day · length). Backend:
  `GET /sources/channels/{id}/collections`, `items?collection=`, Notes' account beside the dump (`noteAccounts`), the
  calendars and lists holding an item kept in `sync_state`. Root causes fixed as classes: Contacts read Off until a
  sync (the catalogue needed the bank's recorded sync, not the reader's own switch — every reader this Mac runs now
  reads Connected while allowed and on); Wispr Flow's bundled mark was never claimed; app removal was read from its
  database, which outlives the app (now LaunchServices, *Off · not installed*); Hex's folder posted every file twice
  before a meeting showed (now *Connect Hex* reads Hex's folder once, on the click, 0.9 s to the list on a scratch run; opening the page never touches the folder).
  Calendar's "Google account" was a standing *Add a Google account* line, retired. **Not reproduced:** Hex's "no
  conversations" (dev with Hex-format files lists them; the owner's real folder's shapes match the parser, checked by
  structure only). *Connect Hex* and the not-installed state sit in the standard connect area. Found re-verifying on
  the layout, fixed: Esc closed the whole page from any level, because the focused detail column takes it ahead of a back
  button (`SourcePageBack`, drills too); an unticked list's items fell under "Other", because each sync replaced the
  names kept for the last one (`source_collections.after_sync`). Calendar's Google way row from #593 is gone too, so
  Cicada no longer links to Internet Accounts: a Google calendar still comes in through macOS.
- **2026-11-04 — locked Apple Notes are never read (G234; branch `g234-locked-notes`).** Owner (ROR-93): locked notes
  must be unavailable to read, and the app should show it detects them. The reader asks only through `whose password
  protected is false`; the backend drops a flagged body and retires what it kept; Sleep retires text-less stubs before
  it freezes; only a count stays, one line on the Notes page. **Measured on a throwaway note:** `password protected` stays
  true while a locked note is open, `plaintext` asked directly then returns its text, and the filter returns only the id;
  locking changes a note's id, so a follow-up (owner yes, 2026-11-05) finds what was kept by a hash of the name, made in
  the app, never stored; a note this read saw unlocked never matches. Name alone, not the proposed name and dates: a note
  edited before its lock has no matching date, and a stored date depends on the locale and time zone of its read.
  Remove reaches the kept file by value (by suffix), `residue` counts it, and a row waiting at retirement survives on the
  empty record; name keys go only with a complete read.
  **Retired text leaves `episodes/`** for `sources/locked_notes/`, so every reader finds an empty record, with no check
  per caller. **The owner decides:** what Sleep already derived from such a note, the kept file, and git history.
- **2026-11-04 — books: scan an ISBN, Apple Books, a Goodreads export (G233, G39; branch `books-g39` + cicada-app `feat/scan-a-book`).** Owner: "integrate ISBN codes to include books I'm reading … iBooks too, to track progress … save books I want to read (maybe including Goodreads)"; then "be able to consolidate highlights and such is important", not started as its own status, the scanner in the phone app. `POST /capture/isbn` is the phone's contract (`{isbn, status?, id?}`, keep it stable); the home resolves the number behind the connector gate; `books.apply_pending` makes one `media` page per work with dated `reading-status` claims and happenings (`progress.py`). Apple Books is read by the app after Connect; Goodreads only by its export (no API keys since 2020); both on the standard source page (`BooksSlots.swift`). Highlights are read by Sleep, revision-read as they grow. Verified on scratch state with a synthetic library, a sample export and a capture-only phone (`feature-status.md`). **Owner's steps:** the four decisions on the G233 row; a real-iPhone camera test once the Apple Developer Program signup is done.
- **2026-11-04 — a question about two people rests on a conversation naming both; never the owner without their own
  words (G209; branch `fix/person-dedup-evidence`).** Owner: "why tf would <handle> be me?" about "Is <handle> the same
  as <owner>?" (guess 0.90, evidence a chat naming neither). Cause: a post BY the handle linked on the owner's page read
  as the owner's account, raised whenever any mention matched the owner's page, with that mention's conversation and
  extraction confidence. Now (`pair_evidence`): no owner pair without self-reference; a person pair only on a
  conversation naming both (it becomes the card's evidence); the guess is the pair's, ≤ 0.8; Sleep retires the open
  ones that should never have been asked (`owner_unsaid`, `no_pair_evidence`, undoable). Copy of the owner's bank, 210
  open duplicate questions: 1 owner pair, 148 on a conversation not naming both, 20 between people → 4 retired, 16
  left, all 16 cards on a conversation naming both (10 before). Ruling 54 (decided the same day, see its row) settles a
  public handle; 1 of the 20 qualified under the proposed test.
- **2026-11-04 — one layout for every source page; GitHub syncs on connect (G161, G230; branch
  `sources-standard-layout`, PR #593).** Owner, from screenshots: "so much text", the export drop showing "the logos of
  AI companies instead of the logo of Spotify", "standardize the layout for all the sources pages". Every source page is
  `SourcePageLayout` — head and one status line, a connect area (one primary, at most one line, ways in as option rows
  with their own icons), the source's own sections, a quiet footer; spec in `app.md` ("The standard source page"), rule
  in DESIGN_RULES §9 2026-11-04. GitHub's live `lastSync: null` after a code sign-in: nothing started a sync (the poll
  only stamped credentials; the scheduler's first run is 6 h after start); the completed sign-in now starts it. Telegram
  chats is *Telegram*. **Pick up here:** the This Mac pages' content (Notes, Reminders, Contacts, Calendar, Hex, Wispr
  Flow, transcripts) is another worker's, in the layout's `content` slot; Telegram's missing chat pictures are the chat
  images worker's (backend data, not the page layout).

- **2026-11-04 — ways in for Spotify, Reddit, Pinterest, TikTok and Instagram (G232; branch `feat/g232-ways-in`).**
  Owner: "is there no way to do similar to GitHub … offer the website connection through browser harness, just like a
  toggle switch, and then also the file export". Researched against each service's docs and terms (table in
  `network.md`, "Ways in, per source"): only Reddit has an official sign-in a desktop app can use with no secret and no
  server (an installed app); Spotify stays file-only (ruling 47's 2026-10-29 amendment re-checked: its User Guidelines
  also bar automated access and AI ingestion, so no browser toggle either; Development Mode is 5 users since
  2026-02-11); Pinterest needs a secret and blocks new apps from personal boards since 2026-09-14; TikTok and Instagram
  APIs return no saves for a personal account. Built: Connect Reddit (installed app, saved + upvoted + joined
  communities, revoke on Disconnect), browser lists for Reddit, Pinterest and TikTok (off by default until the app
  shows their switches — review of #596), Reddit's votes and communities
  and Spotify's playlists from their downloads, `GET /sources/ways-in` for #593's connect area. **Owner's step:**
  request Reddit API access (Responsible Builder Policy), register an *installed app* with redirect
  `http://127.0.0.1:8000/sources/connectors/reddit/callback`, put its id in `reddit.CLIENT_ID` (`network.md`,
  "Registering Cicada's Reddit app"). **Pick up:** the app side on #593's `SourceConnectArea` (follow-up PR).
- **2026-11-05 — WhatsApp's picker: Archived group and pictures (ROR-110, G179; branch `ror110-whatsapp-picker`).** Owner asked for both directly; before a tick a picture and the flag stay in the app's memory, never posted or on disk (`capture-and-sleep.md`). Synthetic store only. **Still open:** a counts-only shape check of the real store, since why the owner saw no pictures is not yet measured (`@lid` sessions remain the likely gap).
- **2026-11-04 — chat images and Telegram faces (G179; branch `feat/chat-panel-images`).** Owner: "I don't see images appearing when I open the chat inside the app" and "I don't know why the profile pictures don't appear in the chats" (Telegram). Attachments of WhatsApp, Messages and Telegram chats now show as the files in the chat
  panel and the Reader, resolved by the app at view time for ticked chats only (Telegram's through the backend's
  own connection), thumbnails outside every bank, gone on untick; nothing new is stored in the bank, so chats
  already synced show their pictures as they are. Telegram's root cause: a ticked chat's photo was asked only in
  the tick's own request, never again — now on every start and sign-in. **Owner's check:** open the own WhatsApp
  chat on the Sources page; on Telegram, restart the backend once so the photos are asked.
- **2026-11-04 — ruling 56 recorded; suggestions go, a project starts only on the person's ask, things link by context
  (G141, G222; branch `ruling-56-projects-by-ask`).** Owner: "yes, hide the project suggestions." Live count: 0 listed of
  711, so a start now adopts the page that holds the name, the note keeps recent pages said to be what they are, and an
  agent may offer once. Nothing marks pages in bulk. Sleep writes a concept with the signal, never a project. **For the
  owner:** the Projects page is empty until they start something; New project with an existing name is the way in.
- **2026-11-04 — New project is a page; an empty Projects list says nothing (G222; branch `feat/projects-new-page`).** Owner: "remove the text that appears when no projects" and "more like claude desktop app, and not two input text lines". New project opens as the detail column: the name as the H1, a large editor for the person's own paragraphs (kept as written, ≤ 4,000 characters, the page's lead; Sleep never writes it), and a picker over every page in memory by kind with each page's picture or its source's mark. Create is one `POST /projects` with `pages` (checked first, one person commit; a repository joins `repositories:` under ruling 53); `POST /projects/{id}/pages` routes a repository the same way, and the day the person started a project counts as activity, so a new one sits in Current. Verified on a scratch app (light and dark). **For the owner:** the live install suggests 750 projects; by construction that is every project page with no `mine` mark (the ~700 pre-D4 pages, `whyKind: none`) plus fallback concepts and repository births — whether legacy `none` pages are suggested at all is a ruling-45 call (G222's row).
- **2026-11-04 — SUPERSEDED by rulings 57 and 58 the same day: what follows was built in #592 and removed, its DECIDE
  list answered.** Claude chats: the export picked up from Downloads, and a weekly nudge (G197 layer c, G105; branch
  `claude-desktop-capture`). Owner: "I don't see conversations I have on Claude chats or claude.ai being captured."
  Diagnosis, from the live install's numbers: one relayed episode ever, and every Claude chat in the bank from one
  October export. The remote connector was off, so claude.ai had no way in. The desktop app's only Cicada server is
  stdio, which never serves `cicada_capture_turns`, and its primer asks for no relay. Of the four ways in
  (`capture-and-sleep.md`, "Hookless chat apps"): the desktop app keeps no chat history on disk for a claude.ai account
  (counts only, no content read); reading claude.ai through the person's browser by an agent is the "automated or
  non-human means" Anthropic's Consumer Terms §3 bar; the official export is the one path with no model in it; relay
  stays ruling 32's model-dependent exception. Built (app only): while an export wait is open, the vendor's zip in
  Downloads, identified by its central directory's member names, opens the one intake's preview; *Every week* in every
  *Remind me* menu nudges the person to ask for a fresh export. The review of #592 found four blockers, all fixed, each
  with a test that failed on the pre-fix sources: a crafted zip64 offset trapped; Downloads stayed watched past a
  wait's expiry; a busy intake toasted every retry; a refused weekly reminder said it was on. Also fixed: arming only
  after an in-run tap, a stop during a look being undone, an open preview being replaced, an arrival notice after a
  refusal, the nudge's memory, and a line for a refused Downloads. Tests: `ExportArrivalsTests` 22, `ExportWaitsTests`
  7, `IntakeRouterTests` 35, `FeedGuardTests` 10, `CopyConstantsTests` 13, and `--filter Lint` 85, all green. **Needs the owner (DECIDE):**
  (1) the remote stdio relay: should the local stdio server serve `cicada_capture_turns` to the Claude desktop app
  (`clientInfo` `claude-ai`) with the desktop primer asking for it? That would amend ruling 32's "through the remote
  connector" for an app that has no hook on stdio either. **Recommended yes**, as a layer under the export, never
  instead of it. (2) Reading the person's claude.ai list through their own browser by their agent: **recommended no**
  under the ToS rail, unless Anthropic explicitly permits it. (3) D6′ (one-click Funnel for the connector) is already
  waiting (2026-11-03); **recommended yes**, since it is what makes the phone's claude.ai reachable at all. (4) Listing
  `~/Downloads` (names, sizes, dates; a zip's member names) while an export wait is open, which may raise macOS's one
  Files and Folders prompt after *Remind me*: **recommended yes**, as built. Open: the export carries no schedule or
  API, so the person still clicks Export and the email's link once a week. For the owner's own hands: turn the
  connector on and add it on claude.ai, and turn *Every week* on for Claude.
- **2026-11-04 — Substack through the person's own agent (G89; branch `g89-substack`).** Owner: "a direct app
  integration is best to see history of read stuff, saved stuff, etc." Researched against current sources: Substack has
  no reader API or OAuth app programme (its OAuth serves only its own MCP connector — publisher analytics for an admin of
  a Bestseller publication, no profile data), no reader export (a privacy request by email only), no Mac app, and terms
  that forbid scraping; the only "direct" route to history and saved posts is the private reader API with the person's
  cookie — scraping behind authentication, so not built. Built instead, on G166/G206's rails: `cicada_record_substack_list`
  (stdio only) — Saved as indexed saves (`substack-saved`), History as one index-only reading day per day
  (`reading-history:substack:<day>`, the page's day or first-seen, said so), Subscriptions as followed public feeds
  (tag `substack`; `feeds.yaml` remembers an unfollow and no automatic writer undoes it); off until the person turns a
  list on in Sources → Substack; one site's list at a time and the shared 10 reads a day; `needs_login` pauses all three
  and asks for a sign-in (its "I signed in" now lifts a saved list's pause too). Feeds: every item names its
  publication; a paid post's stub is dropped as a body. **DECIDE for the owner (G89 row):** A (built, recommended) the
  agent-read path; B also take Substack's personal-data copy as an import once a real file shows its format; C let
  activity traces file substack.com post reads into the same record; D the private reader API — ruled out by the ToS
  rail. Verified on scratch state with fixtures only (never the owner's account).
- **2026-11-03 — GitHub connects with a code; your repositories are pages; a project lists its repositories (ruling
  53, G230; branch `feat/g230-oauth-sync`).** Owner: "why are you asking for a token for github? cant we just do oauth?"
  and "always sync and make their initial markdowns … a project might reference several repos". Connect GitHub shows
  a code for github.com/login/device (GitHub's device flow for Cicada's read-only GitHub App; no secret, no server),
  then offers *Install on GitHub* until the app is on the person's account (a GitHub App user token sees an account's
  repositories only there). Every owned repository is a `media` page on sync with its first markdown (README summary
  read once); the paste field and per-row Add are gone. A project's `repositories:` list (the person's or a trusted
  agent's link from either page, or the hook's D2a origin hash) with back-links; `cicada_project` and
  `cicada_repo_context` list them. **Owner's step (once):** register the app from `github_auth.register_url()` (the
  link in `network.md`, "Connecting GitHub"), tick "Enable Device Flow", and put its client id and slug in
  `github_auth.CLIENT_ID` / `APP_SLUG`; until then the token is the fallback behind "Use a token instead".
  **Done 2026-11-04:** the app is registered (`github.com/apps/cicada-memory`, Device Flow on, no secret or key) and
  its client id and slug ship in `github_auth`; a real device-code request returned a code. **Owner's step left:** make
  the app public on GitHub, or only the owner's account can install it.
- **2026-11-04 — the door carrier stays TCP (ruling 51f, owner 2026-11-04; G132).** Ruling 51f gains: the door's carrier
  stays TCP (owner 2026-11-04: "if you find TCP working better than UDP, then let's go for TCP"); a UDP door is parked
  in #590 (draft) after three security-review rounds each found a new availability bug in its hand-rolled reliable
  channel — unbounded reassembly memory, quadratic CPU from tiny pieces, then a session deadlock once its held-piece cap
  was reached — while the TCP door passed three rounds clean, and on real Wi-Fi the throughput difference does not
  matter. Revisit with slice 3 (the hole punch needs UDP), with a vetted transport (QUIC behind the authenticated gate,
  or a maintained library), never a hand-rolled channel. Asked on 2026-11-03 "keep the door on TCP until hole punching,
  or UDP?", the owner had leaned UDP ("If we can work on tcp and udp directly probably best to do udp, no?") for silence
  and for the punch; the reviews, not the measurements, decided it. What #590 keeps for slice 3: the silence and
  hello-memory design, WireGuard-style roaming, a lossy UDP test forwarder, and the macOS finding that a UDP door's LAN
  answers need the Local Network privilege (TN3179: sending UDP to the LAN does, accepting TCP does not). Nothing in
  `dev` speaks UDP: the door is #586's TCP listener and the app's Bonjour is #573's `_cicada._tcp`.
- **2026-11-03 — routes, not a relay (ruling 51f, G132 phase 3b slice 1; branch `feat/g132-routes`, #586 (includes
  #572's one-transport work)).** Owner: "yes i think we should copy t3 code … if we can make it all run nicely and for free awesome"; the
  phone, for now, a capture device. Each device's ordered route list (the home's door on the LAN → on a tailnet if
  present → the configured address → the relay only under Advanced → queue; re-checked each minute and on a network
  change, moved back); the door (sealed frames on the pairing keys, never the HTTP API or a token, silent to anything
  unproven, private peers only, rate-limited, fuzzed); a capture-only phone paired in the same room over the door with
  the QR's one-time secret; an unsent outbox item never expires; route enums in the ledger. Measured on loopback (three
  backends, a phone-shaped client, 5 runs beside a full gate run): door handshake p50 1.28 ms; a commit reaches a copy
  over the door p50 384 ms (n=25); after a network switch the copy found the home at its new address and had the 5
  commits it missed in p50 315 ms over ~5.3 KB (a full copy ~15.9 KB), nothing re-paired; moved back to the door in
  p50 0.91 s after the app's word; the phone's three queued captures landed in 18–40 ms once the home answered, each
  once; a dead LAN route costs 1.0 s once a minute; idle, a copy on the door costs less than on `/sync/events` (home
  0.39–0.46 vs 0.50–0.83 s, copy 0.30–0.33 vs 0.54–0.70 s of CPU per 120 s). Slice 2 (router port, IPv6, the DHT
  record) is planned in [the plan](../plans/2026-11-03-g132-routes.md), not built; hole punching design notes only.
  **Security review of #572/#586 (2026-11-03), fixed on the branch:** the door bound wildcard addresses, so a
  server with a public address would have listened on it — it now binds loopback and its own private and tailnet
  addresses only, one socket each, rebound on a network change; also the pairing tag in constant time, a door
  pairing redeems only its own code, a revoke closes the device's sessions and watch at once, a failed request
  leaves no spill, IPv6 sources share their /64's bucket, and the never-expiring outbox is capped at 256 MB as well
  as 5,000 entries, a full queue said in words. The re-check found carrier-grade NAT counted as a tailnet (both live
  in 100.64.0.0/10): a 100.64/10 address now counts only on Tailscale's own interface (`utun*`, `tailscale*`, read
  with `getifaddrs`) holding its 100.x and `fd7a:` pair, and only when that 100.x is not the default route's IPv4
  source (a stray router advertisement's `fd7a:` address on Wi-Fi fooled the first fix); otherwise it is public —
  never bound, its carrier's other subscribers never let in; an exit node is not recognised (the accepted fail-safe). **Pick up here:** #586 lands on `dev` alone,
  carrying #572 (closed as landed through it); the app's half follows (#573: Relay under Advanced, the Local Network and firewall step at first share, Bonjour and the
  network hint).
- **2026-11-03 — the app's half of ruling 51f slice 1 (#573, merged with dev after #586).** Settings → Devices: the relay
  under *Advanced*, folded, off (D9); one first-share step (D4) — Local Network's row from the Permissions step, the
  firewall line only when the firewall is on — before the person's first share, keep-a-copy or pair; nothing is asked
  before that click, and the door binds the LAN only after the app reports a yes. The app's Bonjour advertises the
  door's port and posts found doors; `NWPathMonitor` and the app's return post `/sync/network` (2 s settle, a return at
  most every 30 s). Route state in words — the home's rows "Same network · 23 seconds ago" (a door request now stamps
  `how`), a copy's "Same network · reached just now" / "Queued", and "Queue full" (`tx_outbox.counts`' `full`: the last
  write was not kept and nothing left since). Verified on two scratch backends and two scratch apps; the Allow click
  itself (a real TCC prompt) was not pressed in the verify run, so the granted path is covered by tests only.
- **2026-10-30 — one transport, direct first, the relay as fallback (ruling 51c, G132 phase 3b; branches
  `feat/g132-direct-first`, backend — lands in #586 (includes #572's one-transport work) — and
  `feat/g132-direct-first-app`, Settings → Devices' Relay, #573).** Owner: "cant we just
  connect between devices". Every device-to-device request goes through `sync_transport`: direct to the configured
  address (unset relay = phases 1–2 exactly), the relay when direct does not answer in 2 s or dies mid-request; the home
  pushes commits to the mailbox, a write is a sealed transaction applied once whichever path carried it, the home moves
  and a first copy is made over the relay alone; pairing over the relay (QR v2, six digits) and revoke rotating the
  group. Discovery is the app's (TN3179), checked by a signed hello; no LAN listener. No relay is hosted or deployed.
  Measured on a synthetic owner-scale bank (8,000 pages, 9,000 episodes, 470 inbox items; loopback, this Mac at nice 10, a relay in process): a home commit reaches the copy in p50 365 / p95 412 ms direct and p50 473 / p95 518 ms over the relay alone (n=20 each, interleaved); a write made right after direct fails lands at the home in ~0.55 s (refused, or forwarded with its answer dropped: resent over the relay under the same key, applied once); a copy that starts with the home asleep and 10 commits waiting is caught up 0.17 s after its backend is up (from the mailbox alone; 61 s before a sleeping home's reads were made short); a first copy over the relay (pairing confirmed → HEAD equal, its restart included) 8.1 s against 7.2 s direct; idle, a relay set costs the home +0.27–0.38 s and the copy +0.06–0.14 s of CPU per 120 s (two alternating rounds).
  Report: `reports/g132-phase3b.md`.
- **2026-11-03 — repositories on the graph (G230; branch `feat/github-repos`, PR #583).** The owner asked for a
  repository's name, link and a README preview, and a sync of his own and starred repositories. GitHub is a tier-2 token
  connector (ruling 47: off until a token is pasted, said in words, Disconnect forgets the token, its cursor and every
  README; only `GET`s to `api.github.com`, 4 s / ≤ 512 KB through `net_guard`). Starred repositories are indexed saves
  (ruling 30): a quiet `media` page each (`media.kind: repository`), an index-only episode. Owned ones are index-only
  records offered on the Sources row, never a page or a project by a sync (ruling 36 D4 / 45); the project each already
  is is derived on read — a trusted `repo` source, the hook's D2a salted origin hash, or a same-name suggestion — and
  the person links or makes one in one click. A pasted link or `owner/name` adds any repository (a public one with no
  connection). The README is read through the API only on the person's add or a page open (behind
  `CICADA_ALLOW_LOGO_FETCH`), words only, outside every bank. A re-sync rewrites in place and deletes nothing (an
  unstar keeps the page and says so; a gone owned repository is tombstoned). The repository link is a trusted source
  with `kept_by: github`, so `source_refresh` never sends Cicada's fetcher to github.com for it. Verified on scratch
  state against a fake GitHub API (never the owner's token). **Follow-up (owner 2026-11-03, PR #587):** "i'd rather it
  said 'Add as a project', no?" — one of the person's own repositories (a row, a pasted link to it, its card) has one
  action, *Add as a project* or *Link to <project>*; *Add* (a repository page) stays for starred and anyone else's.
- **2026-11-03 — the notch offers to connect the app in front (G231; branch `feat/notch-connect-suggest`).** Owner:
  "when you enter an app they support a connection for, they suggest from the notch to connect to it … with our own
  aesthetic". Bringing WhatsApp, Telegram, Messages, Notes, Calendar, Reminders, Contacts, a browser Cicada reads,
  Wispr Flow, Notion or Hex (offered until its own meeting folder is connected) to the front, when its Sources entry reads Off in the active
  memory, drops the ask-why notch's second voice: worm + the app's icon, "Connect Notes to Cicada?", what is read, two
  or three things Cicada does with it, No · Not now · Yes. Once per source; Not now (or untouched for 12 s, or leaving
  the app) once more after ≥ 14 days, then never; No never, undone in Settings → General; ≤ 1 a day; never in an app's
  or Cicada's first minute, over the ask-why panel, in a demo, or before setup ran or was skipped; on by default; never
  takes the keyboard. Websites in the front tab are deliberately not a trigger (the star-click prefill is the only
  permission-free tab read, owner 2026-10-19). Seen on a scratch app copy: Notes brought forward → the panel in ≈ 1.5–2 s,
  12 s untouched → recorded Not now, Yes → Sources on Apple Notes. Found live and fixed: a Yes over the Welcome opened
  the source behind it, so nothing is offered before setup. Waiting on the owner: nothing.
- **2026-11-03 — an edited conversation is read as a revision (G104; PR #581).** The owner asked whether updates should be told from new material at consolidation. Measured on a scratch bank (Claude plan, haiku; four synthetic notes consolidated, then edited in place: a changed value, an added line, a removed line, whitespace only): the second Sleep re-read all four whole (8 calls), left the removed line's claim open, read every old span `stale`, doubled 5 claims' spans, asked a conflict question for the whitespace edit and gave four once-said names pages. Now `episode_revision` diffs against the version Sleep read (git), reads only what changed, re-anchors spans, closes what only the removed text said (superseded by the same revision's value with no question, else a Sleep `retracts` record), and keeps a different conversation's word an update or conflict: the same run took 5 calls, 0 questions, 0 new pages, 1 withdrawn. Left: prose regeneration from corrected claims (G104 row).
- **2026-11-04 — a page's prose follows the revision (G104 slice 2; PR #589).** Owner 2026-11-03: regenerate prose from the corrected claims, only on the pages a revision touched. `revision_prose` (Stage 5.58) finds the pages by a closed claim or by a passage whose `section_provenance` row cites the version Sleep read and says a word the revision took away (the extractor often makes no claim of the changed value), and rewrites or removes only those passages in one call a page — only passages whose rows prove they came from that conversation alone (review: a passage with no rows, or citing another conversation still saying the word, is never rewritten); History is never rewritten and gains the change, dated; a passage the person or an agent wrote or pinned becomes one `page_edit` question a page; a contradiction whose old side only the edited conversation said is not filed; section rows and held spans move onto the new body. Measured (haiku, #581's four notes plus a pinned one, provenance-only rule): every passage with rows corrected, the pinned Key Fact kept with one question, three dated History lines, no conflict question, 1 extra call (2.1k in / 1.2k out); one Friday and one Linux Key Fact remained, cut off a summary (Stage 2's losing summary, Stage 5's bounded Summary) with no rows; both cuts now carry the summary's rows, and an edit that extends a Sleep fact no longer inherits them. Rerun: nothing outside History says Friday, Linux or Lisbon but the pinned fact, asked once. Facts written before 2026-11-04 have no rows and stay untouched. Left: folding two same-batch passages saying the current value in different words; the 40-page cap's overflow.
- **2026-11-03 — meeting recorders on Sources: Hex, Wispr Flow, a folder of transcripts (G95, ruling 52; branch
  `feat/meeting-recorders`).** Hex (anoma.ly/hex, 3.3.0, MIT) writes one Markdown file per meeting to the Hex
  meetings folder (Hex's `meetings.output_folder` setting, else its default) with a title, Date/Duration bullets, an
  optional model-written Summary block and a `You`/`Them` transcript with offsets; a per-meeting `audio/` bundle sits
  beside it. A meeting folder is a G133 watched folder of `kind: meetings` (`meeting_transcripts`, one episode per
  file, edited in place, its own start date, consolidated by Sleep); `You`/`Me` lines are the person's (52a). An edit in
  place now says it is one for every stager (`revised: {count, at, previous_hash, consolidated_hash?}`, owner
  2026-11-03: "re-ingested items are updates, not new") — the record the Sleep side reads; a calendar's attendees sit in
  the `meeting` record, never G179's `participants`. Built and verified on scratch state with made-up transcripts only;
  the owner's folder was looked at for names, layout and counts, never text. **Next:** the coordinator confirms 52a
  with the owner; the Sleep side consumes `revised`; the owner adds the Hex meetings folder. **Review of #579
  (2026-11-03), three blockers fixed:** every summary line is quoted (`> `) so none opens a `user:` turn; what comes
  before any of the person's turns is no exchange (`promotion.exchanges`, for every source — a summary naming a project
  had made 3 exchanges 4 and promoted it); a folder's kind never flips (a pre-G95 folder is notes, a re-add as the other
  kind is a 409). A zone name that is a directory no longer fails a sync. Wispr Flow's summary and notes were stored
  unquoted the same way (`wispr_flow`) and are now quoted through the same helper (coordinator 2026-11-03: fix the
  class; the bank holds one Wispr meeting, so the re-render costs one plan read).
- **2026-11-03 — one onboarding Permissions step (G92; branch `onboarding-permissions-step`).** Owner ask: one step for every permission, drag-to-allow where macOS has no prompt. Inventory grepped from the app: Full Disk Access (Messages, Safari, WhatsApp), Contacts, Calendars, Reminders, Automation for Chrome and Notes, Notifications, and Accessibility + Screen Recording only while traces are on — 9 rows, 7 by default. Left out on purpose: Speech Recognition (asked only on a dropped recording), Automation for Terminal/Ghostty (the click that opens one), Input Monitoring and Local Network (not used). Every state is a preflight; a prompt appears only on its row's click; the drag rows open the exact list with the helper at once. The same rows are Settings → Privacy & data → Permissions. Verified on a scratch app copy, light and dark. Caveat: `cv app launch` runs the binary directly, so TCC answers for the launching terminal (Automation read Allowed on a fresh bundle id); a LaunchServices launch is a fresh identity. Same day, on the owner's screenshot: the drag helper is ONE banner holding the app's icon as the drag source, one line in the app's name, at most one action, and a two-hop arrival through `CicadaMotion.helperBounce` (nothing under Reduce Motion; DESIGN_RULES §9 2026-11-03).
- **2026-11-03 — Sources and chat pages, the owner's pass (G179, G161, G223; branch `sources-page-owner-feedback`).**
  Eight items, one PR. *What Cicada reads* left every source page; the chat pickers' standing paragraphs are gone (a
  missing permission still shows its fix). The page's top right keeps only *Import chats or files* while no source is
  open; *Reading in your browser* sits on the account and YouTube pages, *Explore saved sites* on a browser's. Each
  section lists what is set up first (stable). A chat source's page is its chats: pinned first (right-click; `pinned`
  in the chat's settings file, backend state), then the newest stored message; green *Last synced* / grey *Not
  syncing*; a click opens the stored conversation in the trailing panel through the backend's sittings route, which
  now lists none for an unticked chat (`ticked: false`). Decided: the page and the picker stay two things (the page
  is what Cicada holds, readable on a client or replica; the picker is the consent act reading this Mac). Faces: the
  person's own chat draws the owner's page picture, a one-to-one chat its correspondent's page by the one precedence.
  The "9026" date: WhatsApp keeps a pinned chat's `ZLASTMESSAGEDATE` thousands of years ahead (measured: +6,000 and
  +7,000 years exactly on a live store's two such chats, numbers only); the reader now lists by the newest message's
  own date and every picker drops a date more than a day ahead. Readwise removed (adapter, fixtures, catalogue,
  copy). Verified on scratch runs of `origin/dev` and the branch, light and dark (synthetic chats only). Cost: a chat
  list now resolves each chat's page and picture — synthetic 300 chats / 3,000 sittings / 500 pages, uncached,
  median 19 → 35 ms (an indexed `correspondents.page_finder` and the shared picture inputs read once; folding every
  page per chat had cost ~400 ms); a repeat is a 304.
- **2026-11-03 — the study room ends in a hard edge (G176; PR #582).** Owner, on onboarding's
  room: "remove that fade effect from everywhere." The floor fade (a mask over the room's bottom five cells on the Sleep
  page and in onboarding) is removed and its type deleted; no ring is added (the room sits on the page ground out of
  its card, DESIGN_RULES §9 2026-11-03). Seen on a scratch app copy in light and dark.
- **2026-11-03 — "are we also syncing WhatsApp?" (G179; branch `fix/whatsapp-live-stale`).** Not a stopped reader:
  read on a read-only copy of the live store (counts, ids, times only), the one ticked chat (the person's own) holds
  24 messages, its newest 6 days old and exactly the reader's cursor; 0 rows past it, 0 in the 48 h window; the 1,670
  messages since were all in 43 unticked chats. The row's "synced" four days back was the recheck window's last
  re-post of that newest message (7 s before it left the window). The backend's `last_sync` moves only when a pass
  posts, for Messages and Telegram too, so a quiet chat read as a dead reader. The app's WhatsApp and Messages
  readers now keep their last successful pass and the newest message in the ticked chats (`ChatCheck`); the page says
  "Connected · checked 2 min. ago · newest message Friday" and the list row counts the check. Telegram is a backend
  listener (no pass to report) and keeps "last item". Found while verifying: the WhatsApp reader heard its own APFS
  clone of the store as a change (FSEvents `ItemCloned`), so it ran a pass every 15 s forever, re-posting the 48 h
  window; a change now runs a pass only when the store or its `-wal` moved (size or mtime). Waiting on the owner:
  whether more chats should be ticked.
- **2026-11-03 — a Sleep run the network left waits for it (G163; branch `fix/sleep-offline-transient`).** Live: a
  scheduled 3 AM run on a laptop slept ~3 h mid-read; on wake four `claude -p` calls answered "Request timed out"
  (`api_error`, no status) before the network was back, and the run stopped as "The engine needs a look", told the
  person to check the sign-in, badged 4 conversations *could not be read* and drew Sort ✗. Now the transport's own
  timeouts are a lost connection; `machine_state` reads machine sleep (two monotonic clocks) and a route (UDP
  connect, nothing sent); an offline failure is never the conversation's, and the drain waits within the run (no route:
  poll to 10 min awake, settle 15 s; dropping connection: 30 s / 2 min / 5 min; ≤ 3 waits in a row; the person's Pause
  honoured) and reads the same batch again; a network that never returns pauses as `engine_kind: offline` in words about
  the network. Stage 1's total failure now leaves the strip on Read. Not ruling 15: nothing is armed past the run.
- **2026-11-03 — the app says when it is syncing after it was closed (G229; branch `feat/g229-away-sync`).** The
  app's readers report to `PUT /sources/catch-up` (in memory, `reader_catch_up`); `GET /devices/status` carries each
  machine's `catchUp` with what came in while the app was closed and since it opened, counted from the bank. Shown
  under the Sleep page's machines strip and as a row in Home's Today: "Syncing Messages and Notes — 14 new
  conversations so far. 9 conversations came in while you were away." → "Synced …", a source that could not be read
  in its warning clause with its fix. Verified on scratch state (`verify-cicada`, run `g229-away-sync`): three harness
  captures made while the app was closed read "3 conversations came in while you were away"; a second device's report
  showed reading, a failed source with its fix, and done with its new count. Open: a CLI line; an SSE push for other
  viewers.
- **2026-11-03 — Safari bookmarks "never appeared" (G129; branch `fix/safari-bookmarks-catchup`).** Not a missed
  read: Safari keeps every bookmark and the Reading List in `~/Library/Safari/Bookmarks.plist` (all profiles), written
  by Safari and, Safari closed, by iCloud's sync agent; the owner's file had not moved in five days, Safari.app had not
  run on the Mac, and Cicada had read all 512 leaves one second after its last write. The page now says what "up to
  date" is measured against and how another device's bookmarks arrive (`BrowserFreshness`); the launch catch-up no
  longer reads the whole file for the placeholder memory before the roster loads. Waiting on the owner: where the
  missing bookmarks were saved (phone or Mac), and whether they show in Safari on the Mac.

- **2026-11-03 — sync with nothing rented: make the home reachable, else queue (G132, ruling 51c; branch `docs/g132-no-rent-transport`, docs only, #574).** [Research](../research/2026-11-03-sync-without-a-rented-relay.md) §12 after the owner's answers (cloud mailboxes out, Developer Program later, "why hold off" on direct): routes in order — LAN frame socket; the home's router port mapping or IPv6 for that one socket; its address as a signed, encrypted Mainline DHT record; a measured DHT-signalled punch; else queue (no mailbox; never-delivered outbox items never expire). T3 Code's "from anywhere" is rented (a managed Cloudflare tunnel per machine); Tailscale and Syncthing map ports the same way. The connector: one click drives `tailscale funnel` for the G135 port only. #572: a route list, heartbeat only live, QR `relay` optional, frame socket not a pinned-cert listener, the outbox rule; #573: Relay under Advanced. **Waits on the owner: D1′, D3, D-new-1…4, D6′, D9′** (§12.8). Nothing built.
- **2026-10-29 — the home moves (ruling 51a, G132 phase 2; branches `feat/g132-move-home`, backend, and
  `feat/g132-move-home-app`, the Sleep page's strip).** The Sleep page names the device that runs consolidation and
  every other device's lag; picking one and confirming (or `cicada home move <device>`) closes the home, parks Sleep,
  carries what is uncommitted, commits a signed `_home.json` alone as its last commit; the target promotes, the old
  home follows it, other replicas re-point from the record (an offline one asks the group). The device registry is
  shared with every full device (token hashes, public signing keys, addresses; outside every bank) so the new home
  accepts every device. Take-over only on a copy whose home does not answer, on the person's OK on the lag shown; a
  returning old home sets its later commits aside (a ref, never merged) and offers them back as calls and episodes,
  counted in words. Rail (1) of ruling 51 takes effect (CLAUDE.md, Headless). Three-machine test: the move, a queued
  transaction re-targeting, a crash on each side mid-hand-off, a take-over, the old home's return. Hand-off p50 6.0 s / p95 6.6 s; write downtime p50 8.7 s / p95 10.5 s (owner-scale synthetic bank, loopback).
  Report: `reports/g132-phase2.md`.
- **2026-10-29 — the relay is built and tested on localhost, not deployed (ruling 51c, G132 phase 3a; branch
  `feat/g132-relay`).** `relay/` is one Python websocket relay with a SQLite mailbox per bank and one non-root
  container; the backend's `sync_relay_crypto` / `_pairing` / `_client` are the end-to-end layer (per-epoch group
  key sealed to each device, sender-signed padded frames, counters against replay and reorder, revoke rotates and
  the relay drops the device, QR-pinned or typed-code-with-digits pairing). Nothing imports it at startup; no
  host, account or domain. Measured on a synthetic owner-scale bank: a capture commit's bundle 1.1 KB p50, a day
  18.5 MB live / 11.2 MB coalesced, the bootstrap 53 MB (bound raised to 256 MiB; the real `.git` is 147 MB); a
  Sleep drain's decay commit rewrites thousands of pages (~10 MB), so the home coalesces (`supersede`). Relay
  ~69 KB RAM per idle socket. **Owner 2026-10-30: direct first** (LAN, tailnet, hole-punched), the relay only
  the fallback, the sleeping home's mailbox and the connector's address; hosting waits. Next: phase 3b
  wires it after phase 2 merges, with the direct transport (network.md lists what direct needs).
- **2026-10-29 — a computer keeps a copy (ruling 51a/d/e2, G132 phase 1 PR B; branch `feat/g132-replica`).**
  Replica mode (`CICADA_REPLICA_OF` / `$CICADA_HOME/replica_of`, set by `PUT /sync/replica` with the home's pairing
  code; client wins when both are set): a read-only copy fast-forwarded from the home's pack (ancestry checked here,
  files written atomically, indexes caught up), every bank writer refused but the apply, writes as outbox
  transactions (MCP/CLI/hooks through cli_map's `replica` column, the app through a hand-written route table), reads
  local, the home's Sleep frame at the copy's seq. Rail (2) of ruling 51 takes effect (CLAUDE.md, Headless). The
  app's two switches are their own PR. Numbers in `reports/g132-phase1-b.md` and the PR body.
- **2026-10-29 — the home publishes its log, off by default (ruling 51a/d/e, G132 phase 1 PR A; branch
  `feat/g132-home-publishes`).** `CICADA_SYNC_PUBLISH=on` or `PUT /sync/publish` (the server's own token) turns on
  `/sync/log` (seq = first-parent position; a hand rewrite freezes it until "publish from here"), `/sync/pack` (a
  read-only bundle), `/sync/status` (the SSE `sleep` payload from one builder, plus schedule, waiting/parked ids, an
  engine label, the home's name), the capture commit (51e1: only the bytes the capture writers recorded, settled 10 s,
  ≤ 1 a minute per bank) and `seq` on `/tools/call` replies; mutating tool calls take an `Idempotency-Key` (8 days).
  Off, nothing changes (`test_sync_off_unchanged.py`). Measured on a synthetic bank: tool write p95 unchanged off
  (93.7 → 90.0 ms, interleaved), 92.9 ms on and keyed. Next: PR B, the replica (headless.md).
- **2026-10-29 — dev suite after #556–#562, and the source page's list at the cost of its own source (G161; branch
  `fix/dev-suite-5-speed`).** Full suites: backend 3 failures, one real — `test_mcp_stdio_golden` pinned recall before
  #560's rare-word excerpt leg (fixture re-recorded), and `test_cli_reads`' CLI-equals-MCP recall raced the words
  index #560's leg reads (now built inline; the CLI's dropped "read one whole" pointer stripped); two wall-clock tests
  failed only under the parallel Swift build and pass alone. Swift 4,291 tests, 0 failures. `GET /sources/channels/{id}/items` no longer walks every episode:
  empty source 86 → 1.4 ms p95, largest 97 → 8.4, Sources page open 399 → 90 (owner's bank copy, stream open).
- **2026-10-29 — one memory on every device is decided, not built (ruling 51, G132 phase 0; branch
  `docs/g132-phase0`, docs only).** The owner's sync-engine decisions are binding: one home applies every write and
  runs Sleep, every computer may hold a fast-forward-only replica, other devices' writes are idempotency-keyed
  transactions through the same tool bodies, the home moves from the Sleep page, the phone becomes a full device
  (reverses ruling 38 §2), and devices meet at an end-to-end-encrypted relay (hosting, account, domain and spend wait on
  the owner). Plan: [`docs/plans/2026-10-29-g132-sync-engine.md`](../plans/2026-10-29-g132-sync-engine.md); phases 1–5
  and their open gates are on the G132 row; `headless.md` and `network.md` carry "Decided, not built". Nothing in
  today's code changes.
- **2026-10-29 — a repository keeps its identity across rename, move and re-clone (ruling 22 D2a, G110/G141; branch
  `feat/project-remote-identity`).** The hook adds a hashed, per-install-salted `remote.origin.url` to its D2
  observation; continuity, project birth and project activity read it beside the path keys; a moved Claude Code notes
  folder keeps its episodes (rename by content), a copied one adds none. Scratch-repo measurement: pointer found 0/3 →
  3/3, moved repository (same name) duplicate project 1 → 0 (a renamed one goes to the judge, told they share an origin), moved notes folder 2 new + 2 tombstoned → 0 + 0 (2 repointed).
- **2026-10-29 — recall nobody asked for (G149, G207, G105/ruling 43; branch `feat/recall-unasked`, Supermemory's
  lessons (d)1–3).** A prompt that names no page gets up to three current claims its rare words find, ending with
  `cicada_recall(query)` (labelled set 0/23 → 22/23, 0 unrelated lines, 0/16 coding asks noted; owner-bank copy: no
  new note on 20 coding asks, hook p50 +7 ms); recall's word leg finds today's conversation by a plain-words question
  (2/5 → 4/5 phrasings, first hit ~1.3 s after capture); `feedback`/`user` agent notes join *How to work with me* as
  the agent's words (≤ 2 rows, primer 1,690 tokens).
- **2026-10-29 — an agent's saved note is the agent's words (ruling 50, G118; branch `fix/agent-saved-words`).**
  `authorship.of` reads a `cicada_save_episode` note (stdio, remote, an agent's shell) as `evidence.AGENT_KIND`:
  `assistant` spans, no promotion exchange, its session's one conversation, claims `external:<harness>`. The ad-hoc
  `AGENT_SOURCES` / `_agent_note` checks in Ask and the inbox tend are gone into the one rule. Search index schema 9.
- **2026-10-29 — chats feel like the apps, chat-specific half (G179, owner's live test; branch `feat/chats-ux-v2`).**
  Telegram's QR step waits on the status's `version` (long-poll) instead of reading once a second; a WhatsApp chat
  with yourself is your notes (`self_chat`: no correspondent, no card) and one oversized field no longer refuses a whole
  batch (422 → clipped/dropped), with errors that say what failed and what to do; chat pictures from WhatsApp's own
  data and Telegram's API (picker, and a ticked one-to-one chat's is its page's picture); pickers search by name or
  number; `/sources/channels/{whatsapp|telegram-chats}/items` serves one row per chat for the shared source-page
  design another worker builds (the "what came in" UI is theirs).
- **2026-10-29 — Claude's memory tool backed by Cicada, as a client of `/v1` (ruling 38a, G213; branch
  `feat/memory-tool-adapter`).** `clients/memory-tool` (Python, stdlib core + an SDK `BetaAbstractMemoryTool`; a
  TypeScript twin for `betaMemoryTool`) maps `/memories` onto `/v1`: `README.md`, `recent.md`, `hubs/`, `search/`,
  `pages/`, `sources/` read-only by scope; `notes/` the agent's own, saved through `save_note`; delete and rename
  refused with a sentence. No backend change. On a scratch backend after a haiku Sleep: a fixed 8-question set
  answered 8/8 with a `search`+`read` token, 0/8 record-only, 0/8 with no adapter (an empty memory directory);
  writes refused for read-only. The SDKs' own tool runners drove it end to end with the Messages API mocked — no
  metered call was made (`reports/memory-tool-adapter.md`, outside the repo).
- **2026-10-29 — one source page for every source (G161, owner; branch `feat/source-page-v3`).** Status line
  (*Connected · last item today*), *What Cicada reads* one tap away, one search (backend `q`, the words index
  included), the list in the source's unit with *All N* and groups opening in the column, settings last; the duplicate
  *What came in* fold is gone for every source row. WhatsApp and Telegram list one row per chat (picture, message count, newest day, a Group tag) on #559's rows.

- **2026-10-29 — the picture is the control (G146, owner; branch `feat/picture-click`).** The blue *Add a picture…* /
  *Use initials instead* / *Remove picture* words and the "Picture you added" caption under a page's name are gone; a click on the picture offers them
  (the picker at once when it is the only choice), a page with no picture adds one from its ••• menu.
- **2026-10-29 — any join can be undone: merge, split, undo (G227 follow-up; branch `feat/merge-split-pages`, after
  #546).** Owner: "the separation of entities should mainly happen by talking to an agent" — the agent shows a
  plain-text proposal, splits on the person's yes, merges on "those are the same", undoes on "undo that"
  (`cicada_split_page` / `cicada_merge_pages` / `cicada_undo_join`, named in the handshake and skill); the page menu
  keeps a light Merge and a *Separate with your agent…* hand-off. Untrusted agents and remote apps propose in the inbox. Each is one commit undone from the page's History; a retired id keeps resolving
  (`_redirects.yaml`, every merge and rename); a split pair is never re-joined by Sleep. Verified on a read-only copy of
  the owner's bank: the same-name page split, undone, split, merged back, both undone — byte-identical.

- **2026-10-29 — Telegram connects by a QR (ruling 49, G179; branch `feat/telegram-qr-connect`).** Connect… opens on a
  sign-in QR the person scans in Telegram on their phone (Settings → Devices → Link Desktop Device); the backend
  refreshes it as Telegram expires it (~30 s, 10 rounds) and the app follows the status; number → code is the
  fallback. Typed fields 2–3 → 0–1 (a two-step password only); app switches to read a code 1 → 0. Stopping a sign-in
  half way no longer "logs out" a session that never existed. **The real friction left is the app id:** no
  `CICADA_TELEGRAM_API_ID` is set on the repo, so a release build has none and every person would have to make their
  own at my.telegram.org — the owner sets it once (`docs/RELEASING.md`).
- **2026-10-29 — capture answers in time (G105, ruling 7; branch `fix/capture-post-latency`).** The Stop hook's
  `error: TimeoutError` lines (32 of the owner's last ~340 firings) were captures that landed late: a new session's
  first Stop read all ~8,700 episodes under the capture lock, serialised across sessions. Now an index finds the
  episode, `/capture/transcript` and `/capture/session` answer within 2 s (`202 accepted` past it, the write finishing
  on its own), and a local post with no answer logs `no answer`, waits in the spool and is sent by a later firing.
  Reproduced on a scratch copy under load: route p99 10.96 s → 2.01 s, hook firing p95 3.12 s → 0.88 s, timeouts
  22/126 → 0/147.
- **2026-10-29 — session-1 follow-ups (G209/G21, G228, G212; branch `feat/session1-followups`).** The alias behind a
  "same as?" lead is the cause: when the record holds a pair as two things, Cicada proposes removing that alias as a
  `page_edit` (the person applies or leaves it; a kept alias is never proposed again), Sleep never adds a page-held-apart
  name as an alias, and Stage 1's prompt says so (21 of 160 open "same?" were org/tool alias leads, 14 of them judged two
  things). The person's own agent settles a public pair with a relation through Sleep's own writer. The Agents page draws
  way notes (T3 Code's managed Codex sign-in: not captured) and T3 Code's own mark. **Owner ruling 2026-10-29 "Yes, one
  click":** Settings → Devices runs exactly the shown tailnet `tailscale serve` (and that mapping's off), never funnel/up.
- **2026-10-29 — seamless, secure devices (G212; branch `feat/seamless-devices`, cicada-app `feat/seamless-devices`).**
  Settings → Devices guides the Mac onto the person's own tailnet (the next step and the command to copy; Cicada never
  runs it) and checks the served address the way a phone would; a phone's token is bound to a Secure-Enclave key
  (DPoP-style; a copied token alone is a 401), already-paired phones bind themselves, a phone pairs capture-only and can
  only narrow its code. Proof verify p95 0.06 ms; hot paths within noise. Waits on the owner: whether a click may run
  `tailscale serve`, and the on-phone checks. Numbers on the G212 row.
- **2026-10-29 — T3 Code (G228; PR #543).** T3 Code drives the Claude Code, Codex and Cursor on the
  machine with their own settings, so Cicada's existing hooks, plugin and MCP server already run in its threads; one
  thread on one harness is that harness's one episode. New: the hook names the host from its own launch chain (exec paths only)
  and the episode is labelled `host: t3code` (its own Sources row, an Agents-page umbrella whose connect steps are the agents
  it drives, seen via the new `hook` sighting); what T3 Code writes into a turn (a provider switch's replay, its ACP
  instructions) is not kept as the person's words — only under that host, on its full shape. Nothing read from T3
  Code's database; `npx t3` goes unlabelled. T3 Chat documents no MCP
  connector, so it is not listed. Stop firing p95 within spread (57.3 → 57.7 ms). Unverified against a live T3 Code; Codex under T3
  Code's managed sign-in is not captured (Needs the owner on the G228 row).
- **2026-10-29 — live class guards (G194, G169, G118; branch `feat/bank-repair-apply`).** The owner dropped the
  bespoke repair tooling ("apply fixes that make them generalizable"); the six vetted classes are closed in the live
  path instead: a belief that held and ended is never reopened by an older mention (`claim_reconciler._ended_span`);
  a filing label is `page` and no mention (`evidence.LABEL_FIELDS`, `promotion.label_only`); every alias writer asks
  `alias_policy.admits` and Sleep adds no other page's name; an in-flight application on record takes the owner's lines about it from
  any conversation (`application_page.standing`); the inbox dedup asks `distinct_names`. Saved-link words (#515) and
  the near-name join (#491) were already closed on dev. Nothing applied to the bank.
- **2026-10-29 — chat exports findable (CIC8, G64; branch `feat/chat-exports-obvious`).** Every door to a chat export
  opens the one intake (Sources' header *Import chats or files* and its Chat exports entry, Agents' *Import its chat
  export*, a ⇧⌘I palette action Home's field finds by "chatgpt"/"chat export", the walkthrough's *I have the file…*);
  the picker opens in Downloads. Fixed the Agents→Sources loop (a tile no entry owned) and the hand-off tile left staged
  for Sleep. Relay gap unmeasurable on this bank: 0 relayed episodes vs 1,519 exported conversations (G64 row).
  Noticing an export in Downloads waits on the owner (a grant and a new visual pattern). Round 3: the import is ⌘K's
  top hit for "chatgpt"/"claude"/"export"/"zip" (never over an exact title); a source's "connected · <when>" reads its
  receipt (`episode_time.delivered_at`, ruling 39), not an import's backdated chats — list p95 unchanged.
- **2026-10-29 — every "All N" opens at once (G115; branch `fix/inbox-all-freeze`).** Home's *All 465 questions*
  froze the app for seconds: app-side, not the backend (`load_inbox` p95 52 ms on a bank copy, off the event loop). The
  Inbox page rebuilt its derived lists on every read, each sort building two `DateFormatter`s per comparison, and laid
  out every row. Now the lists are kept per Store revision, the day parsed once, and every "All N" list is lazy (⌘Z on a
  keeper outside the rows, R-DI4). Debug build at 465 questions: 2.4 s derivations + 1.5 s layout → 30 + 30 ms;
  budgets at 2,000 rows in `InboxAllListBenchTests`. In a verify copy of the app with 540 questions: click to list
  17–18 s → 0.85 s. Numbers on the G115 row and in `app.md`.
- **2026-10-29 — Cicada ships with hoff (G220, CIC2; branch `feat/ship-with-hoff`).** The owner's show-me cursor is a
  reviewed catalog suggestion (rank 13), copied at a pinned commit with every file hashed and without hoff's hooks (the
  skills rail); a copied suggestion now installs only its reviewed bytes (`check_reviewed`). Traces context is not built:
  hoff keeps no walkthrough record and its marks cache carries titles and page text — the recommended event line waits
  on the owner, as does `sharingType = .none` in hoff's own repo. Numbers on the G220 and G138 rows.
- **2026-10-29 — G227 follow-ups (branch `feat/same-name-tag`; owner rulings recorded on the G227 row).** A mention several same-named pages could be is one question: which page, or "Another one" (owner: "none should probably just mean another one"). A pick merges by id. "Another" keeps THAT mention apart on its own pending line, never name-wide (#546 review: a name-keyed rejection kept later mentions of the page from joining it; "No, different" fixed the same way). Once the unchanged promotion rule allows, Sleep makes it a page with the clean title under a distinct id (no stored "(another)"). The app shows the qualifier as a `Tag` beside the plain name (DESIGN_RULES §9 2026-10-29); agent doors keep it in text. The IDE-page split is a per-sentence dry-run plan that waits for the owner's OK; nothing is applied.
- **2026-10-29 — related is not the same (G21, G209; branch `fix/duplicate-questions-relations`).** Home's "Possible
  duplicates" held 160 questions on the owner's bank, most of them a part and its whole, a product and its maker, an
  alternative and the original or a version and its line. The judge now answers `related` with the relation; a
  relation is a claim on the page, never a question; a project name with no birth judged a part of a page lands on it
  (owner 2026-10-23's canoe rule); an organisation/tool alias lead meets the judge before it is asked; a pair the record
  relates is never proposed; a public pair is looked up (each name alone) and settled with a cited relation, undoable
  under "Settled by a check" — never merged. The backlog is a per-item dry run in the workspace; applying it waits on
  the owner. Numbers on the G21 row.
- **2026-10-29 — same name, different things (G227; branch `feat/same-name-qualifier`).** A title two pages share is
  shown "<name> (<qualifier>)" everywhere — the app, the API, recall, Ask, the CLI and `/v1` — from one derived function
  (`same_name`); links resolve by id; Stage 2 no longer joins an exact title of another kind on the name alone (the
  owner's IDE page held 10 program-shaped sentences on the bank copy) and asks when its judge cannot tell — yes/no
  about one page; picking among several waits on the owner (G227 follow-up). Haiku
  replay 60/60 on three synthetic cases; hot-path p95 within run-to-run spread except `/graph`'s cold build (+0.14–0.29 s
  once per write). Numbers and the measurement on the G227 row.
- **2026-10-29 — the full suites green again (branch `fix/dev-suite-2`).** `test_continuity_route_latency`'s
  warm SessionStart call failed only in the full backend suite: one gen-2 collection of the ~4.5M objects the earlier
  tests leave (~234 ms) landed inside a 15 ms timed call. `_bench.Timer` now freezes the heap like `measure()` (#530),
  budgets unchanged; the route itself is unchanged since before #518 (cold p50 ~101 ms, warm ~11 ms). Sources'
  `spotify-listening` card is "Spotify history" (16-character name rule, like YouTube's and TikTok's).
- **2026-10-29 — Speed + quality round 4 (branch `fix/speed-quality-4`).** Watched rows out of the cached headers for new days,
  a start-up `gc.freeze()`, `/projects` remembered (G115 row). **Waits on the owner:** the move of the existing watched days
  (2,541 on the owner's bank; cold scan −1.25 s once done) is opt-in — in your own terminal, `cicada maintenance
  move-watched-rows` (dry run: counts and a few day ids), then the same with `--apply` (one `cicada` commit). Report:
  `speed-quality-4`.
- **2026-10-29 — G32 built: Spotify's own download imported (branch `feat/spotify-export-import`).** Both downloads
  (Extended streaming history, Account data) through the one file import: plays as one index-only listening day each
  (ruling 30), never doubled between the two files; the library as index-only saved items, never fetched. Sources
  gains a Spotify row that says where to ask Spotify for the file.
- **2026-10-29 — one person across sources (G209, G179; branch `feat/one-person-across-sources`, PR #527).** A
  chat participant's ONE address-book card (by Contacts id, never a handle) rides on the sitting's records; Stage 2
  joins the participant to that card's page before any name, a waiting card only once the usual rules promote. A
  first name heard outside a chat is asked about in plain words, never joined. Read-only counts on a bank copy:
  282 person pages; 33 already appear in 2+ kinds of source on one page; 13 likely splits across kinds of source (3 a one-word page beside a full-name page, 9 an alias that is another page's name, 1 a held one-word name), 2 of them involving a chat; 0 chat participants with a card today (the bank's one ticked chat is with an agent), so 0 faces gained on this bank until a person chat is ticked.
- **2026-10-29 — Spotify is export-only (ruling 47's path table amended; G223, G32; branch `docs/spotify-export-only`).**
  Spotify's Developer Terms (v10) bar ingesting Spotify Content into an AI model (§IV.2(b)(i)) and storing or
  compiling it (§IV.3(a)), so the ToS rail rules out an API connector. The way in is the person's own Extended
  streaming history download through G32's import (not built yet). Capturing what is playing through the harness waits
  on the owner's ruling.
- **2026-10-29 — files in the app (G195; branch `feat/files-in-the-app`).** The coordinator chose (owner asleep, "go
  with the recommendations"): the find palette gets a **Files** group, and the File menu gets **Add Recording or
  Video…**. In the group, a recording reads "the recording's words, at m:ss" and a video frame shows its own thumbnail or
  no mark (#512). Both use existing row patterns only (DR-48, DR-44, DR-12, DR-81). The menu item uses the intake's open
  panel and the drop's door, so Speech Recognition is asked only inside the person's own act. Driving the app found two
  defects, both fixed. First, the lift is now taken over the other items' mean: with two files, the right one never
  cleared the floor. Second, a frame's thumbnail never loaded, because an empty view's `.task` never runs.
- **2026-10-29 — Speed + quality round 3 (branch `fix/speed-quality-3`).** Projects list, recall and `/status` cut;
  the owner's id hashed in the `inbox` sync component (G115 row). Report: `speed-quality-3`.
- **2026-10-28 — Messages interactions reach Sleep; group chats are read (G179, G29, G113; branch
  `feat/messages-replies-groups`, PR #499).** Replies, reactions, forwards and unsends stored in `turn_extras` reach
  Stage 1 as one note per chunk (`turn_signals`), source-agnostic; the person's own reaction moves that claim's
  confidence, never its observer, on that
  turn. Group chats (`chat.style` 43) are ticked and read: one participant key per member, never a handle; a member's
  claims are theirs; only the person's lines promote in a group. Owner's bank, read-only counts: 828 reply turns
  (87 into an earlier sitting, 0 unfound), 195 reactions; ~194 note tokens per sitting (~+3.5 % per call). WhatsApp
  live (Desktop's local store, the Messages model) is planned on G179; Telegram is ruling 47a (G29), built by
  `feat/chats-live-whatsapp-telegram`.
- **2026-10-29 — git's commit-graph kept current by Sleep's tail (G217 follow-up; branch `perf/commit-graph`).** The
  last tail step rewrites `.git/objects/info/commit-graph` with changed-path filters under the bank's git lock — a
  derived git file, never a commit. On an owner-scale bank copy: History tab p95 224 → 128 ms, a page's history p95
  203 → 105 ms, the provenance strip p95 174 → 75 ms; the first write 423 ms, a nightly rewrite with nothing new
  24 ms. The person's own history rows now wear the owner page's picture (G146's ladder).

- **2026-10-29 — pages v2, part B: History, maps, In short (ruling 48 parts 5, 6 and 14; DR-77; G217, G121; branch
  `feat/pages-v2-b`).** The card open reads no git any more (on an owner-scale bank copy, 13 pages × 12 opens:
  p95 260 → 58 ms); the History tab reads 30 rows with who, what changed and when from one `git log -p` when it opens
  (p95 229 ms, of which the bare git walk is 174 ms; 142 ms with a commit-graph's changed-path filters — not written,
  a follow-up). Places store coordinates once: the app's own Apple geocoder on first open or a five-place pass, a
  private place (address, home word, the person's own thing, a person's name) only on the person's click; the card
  draws a cached `MKMapSnapshotter` still with nearby places and a live native map on click. In short: Sleep's tail on
  the engine's small tier, ≤ 10 pages a run; on the copy 32 pages qualify, ~4.2k tokens in and 80–600 out per page on
  haiku, 2.6–4.5 s each.

- **2026-10-29 — ruling 47 tier 2 built: the connector framework, Readwise and Notion live (G223, G219; branch
  `feat/connectors-tier2`).** `api/services/connectors/tier2.py` is the one framework: the person's own token in
  `secrets.env`, checked with the service on Save (a refused or unchecked token is never written), what it reads said in
  words on the status (`reads`, `tokenHelp`), one-click Disconnect that forgets the token and every bank's cursor; a
  sync stages one episode per natural unit through `episode_staging` (scrubbed, edits in place, deletions tombstoned)
  and commits only its paths as `user`, inside one admitted transaction (refused while Sleep holds the pages; nothing
  written, the cursor kept); its own scheduler job every 6 h behind `CICADA_ALLOW_CONNECTOR_FETCH`, skipped before any
  request while Sleep writes; Sleep's tail never runs one. Readwise: a document episode plus one per highlight day
  (quotes as `page` evidence, the person's notes as `user`), linked to an existing page only on an exact URL or a
  unique exact title, never a page made. Notion: an internal connection only (a personal token is refused at Save),
  pages keyed `notion:<id>` like the export, in place on edit, trash tombstoned; a page is the person's words only when
  Notion names the connection's owner and that user created it (else `assistant`), and a unit stored as someone
  else's is never moved back to the person's; the first sync walks the whole history before the mark moves. Engine
  children, the embedding worker and the PDF reader also lose the master API token and the Telegram bot secrets. Connector tokens are stripped from every engine child. Doors: the API and `cicada
  connector list|connect|disconnect|sync` (token from stdin only); no remote door. p95 on a copy of the owner's bank
  (8.5k episodes, fake servers): 6.2 ms per Readwise unit, 22 ms per Notion page per incremental sync.
- **2026-10-29 — Pages v2, part A (ruling 48 (3), (4), (7), (16), (17); DR-78…DR-81; G217; branch `feat/pages-v2`).**
  The entity page reads top to bottom with no folds: In short, Where to check as one box of mention rows with their
  state and proposals as one Review line, the brand block above the article on pages about their look, Ongoing on
  any page, the article carrying its beliefs as citation markers with a lazy popover, References closing the page.
  The markers number the page's write-time line provenance (`page_citations`; nothing matched by similarity), cached
  per page; `cicada_recall_detail(include=["citations"])` words the same. Card open reads one page (no `/sources`,
  `/provenance` or fact claims on open; Clusters and the card share one read). The article writer marks an inferred
  claim and words it as one (prompt v2). **Next:** part B — the history line, maps, In short.
- **2026-10-29 — Speed + quality round 2 (branch `fix/speed-quality-2`).** Requests answer from the SSE walk's
  listings behind a watcher + local-writes gate; the inbox ETag covers the files beside the inbox and the claims
  ledgers; recall, `/status`, `/origins` and the owner's card cut (G115 row); bench budgets also cap wall p95 at 4×;
  the app's Swift lint tests run on every PR into dev (`swift-lint`, hosted macOS 26). Report: `speed-quality-2`.
- **2026-10-29 — Speed + quality (branch `fix/speed-quality-1`).** dev's full-suite failures sorted: the writer
  inventory gained the twelve writers #492, #500, #501 and #508 added (each with its disposition); the four bench budgets
  that failed at load 30–55 pass at load 8–20 on the same commit (no regression from #496–#503) and now measure CPU time;
  the hung-tool engine test injects the runner's timeout answer; the shared stdio server starts every test with no client.
  `GET /inbox` warm p95 529 → 69 ms at the owner's scale (G115 row). Report: `speed-quality-1`.
- **2026-10-28 — Projects v3 (G141, G222; decisions 9, 10, 17; branch `feat/projects-v3`).** The project page has no
  folds: Pulse (counted, no model, one fixture for Python and Swift), In motion, Coming up and Timeline open and capped
  with "All N"; Pages in this project with Add / Not part of it (`entities_added`/`entities_removed`, frontmatter, one
  writer) and `cicada_link_entity` on every door (trusted ties, others propose); Suggested as one line; a lighter head
  (one standing line, the meta in `.help`). Bench p95 on the 2,500-page synthetic in the PR.
- **2026-10-29 — a saved item's fetched text is never the person's words (G118; branch `fix/saved-link-words`).**
  `authorship.of(fm)` is the one `override` every evidence reader passes: a save (by its record) is `page` except its
  reason and note sections. On a read-only copy of the owner's bank, 347 current claims on 89 pages carry a `user`
  span inside fetched text and at most 36 one-conversation pages rested only on them; nothing is rewritten — the
  repair is a per-item dry run awaiting the owner. Hot path unchanged (turns + exchanges p95 0.173 ms per episode
  before and after, 8,546 episodes).
- **2026-10-28 — pictures v2: public figures, Sleep's own sites, projects (G159, G146, G61; rulings 40 and 44 amended,
  owner C/D/E; branch `feat/pictures-v2`).** A public figure the full ruling-44 test called public gets the matched
  item's encyclopedia portrait, asked by item and file name only; ruling 40 trusts a site Sleep itself first proposed
  once its homepage names the page; a project draws its trusted site's mark or, when an organisation owns its
  repository, that organisation's avatar. On a copy of the owner's bank: 3,690 → 3,729 of 5,684 live pages can show a
  picture (people 2 → 7, brands +23, projects 0 → 11). The biggest face lever left needs no ruling: the Contacts rung
  — 87 of the 132 face-less people carry a full name a card could match, 0 can be counted until the app has synced
  Contacts for this bank; the one ticked Messages chat is a texted agent's. Card-open and logo-serve p95 unchanged
  within noise.
- **2026-10-28 — engine picker v2 (ruling 48 part 11; G122, G49; branch `feat/engine-picker-v2`, stacked on #505).**
  The quick menu lists a card's models as a filterable second column (families, newest first, *Show N older*, New,
  freshness with a click-only Refresh). Research on "Grok and Cursor are now one": one subscription since 2026-10-12,
  still two tools and sign-ins; Cursor's third-party models bill at list price from top-ups. Ruled the same day
  (ruling 46a): Auto and schedules run Cursor only on Cursor's own models, also when the mode is pinned in the env.
- **2026-10-28 — questions on Home, the catch-up chat in the app (ruling 48 (1), (2), (8), (17); vision item 10, app
  half; branch `feat/home-inbox-catchup`).** The Inbox left the rail (⌘6 unused, the count on Home); Home leads with
  *Catch me up* as its own block, then one row per page with a question — the page's picture, the plain question
  (`spokenQuestion` on `GET /inbox`), its reason and the page as a link — and *All N questions* opens the full list as
  Home's sub-view, its kind groups never folded. Each page has its questions strip ("1 of N"). *Catch me up* is a chat
  with the worm's head as Cicada's face: taps are the inbox's held answers; the person's own words go to `POST
  /inbox/catchup/turn` (one turn on their chosen engine, Ask's resolution; a reading only when found in their words, and
  then only proposed — applied on the person's *Yes*; **owner 2026-11-05 overrides: "if the agent is going to ask for
  confirmation on everything eventhough i just told him then thats bad user experience" — a clear reading applies at once
  under Undo, every part of one message, the tap row gone**) and the chat is kept as one episode per session (`POST /inbox/catchup/record`). The
  harness door's catch-up carries the same page context and asks for a conversation (skill, prompt). Speed and what is
  next for `load_inbox` in the PR body.

- **2026-10-29 — meaning index 2: recordings, video frames and the design board in the one index (G195 stage 2;
  branch `feat/meaning-index-2`).** Audio and video were decided by the owner, through the coordinator: **"owner said go
  with the recommendation, 2026-10-28"**. That means speech is transcribed on the Mac by Apple's on-device recogniser
  and then embedded (no 561 MB audio model), and a picked video's frames go into the picture kind. A dropped recording
  or video is read by the app (`MediaFileIndexer`), which posts only its words and kept frames to `/files`. They are
  stored outside every bank as the recording's words, never the person's. Words: the `files` kind; frames: `source:
  frame` pictures. Both are opt-in in `/search` and appear in recall on local doors only. The design board's store is
  now the `look_vectors` table of `vector_index.db`; its old file is folded in once and deleted. A rebuild now removes
  deleted pictures from the generation being served at once, and swaps when nothing is left to embed (follow-up to
  #506's review). An hour of speech embeds cold in 7.6 s.
- **2026-10-28 — ruling 48 recorded; the redesign accepted (docs only; branch `docs/redesign-rulings-2026-10-28`).**
  The owner answered the redesign's decisions: entity pages read as articles that carry their beliefs (citation
  markers, References, no beliefs list), Home leads its questions with their pages and Catch me up stands apart as a
  conversation with the worm, the Inbox leaves the rail, no page stacks folds, Projects redrawn (its header to be
  lightened and mocked first), native MapKit, the filterable model picker, traces with one switch, a per-day view and
  no YouTube special case. The binding text is DESIGN_RULES §9 2026-10-28 (parts 1–17) and DR-77…DR-81; the mocks are
  in `docs/design/redesign-2026-10-28/`. Builders cite the part numbers.

- **2026-10-28 — two #493 verification defects fixed (G194, G141; branch `fix/event-object-project-past`).** An act on
  an event (signed up, registered, applied) is no longer pinned on its venue or organiser (`act_object`, Stage 1
  prompt + a guard reading the located sentence; replay on haiku 5/5 → 0/5). A project heard from within its rhythm
  is in motion even when Sleep's decay marked the page decaying or archived (`ProjectState`, both twins, one
  fixture), and a conversation tied without a claim yet counts as activity (`_tied_days`); list p95 stays ≤ 58 ms on
  the 2,500-page bench. The second amends DESIGN_RULES 2026-10-19 (1)'s "resting — a decaying or archived page" —
  awaiting the owner's yes.
- **2026-10-28 — traces redesign (G218; branch `feat/traces-v2`).** "Learn from my day" is one switch, off, with the exact counted digest previewed (no title, address or screenshot text; project time only through the person's own projects' folders, repositories and tied addresses) and "Remove from memory" as one undoable commit; "What you watch and read" on any site replaces the YouTube-only switch (index-only reading days); the Traces page manages days as cards (each item or day deletable); screenshots cover every connected screen behind consent sheet 2, at 5 min on change / 15 min steady. Ruling 39b amended the same day (owner): on by default when traces are on, any site; H accepted.
- **2026-10-28 — pictures in the one meaning index (vision item 3, G195, G162, ruling 30; branch
  `feat/vision-meaning-index`).** Looks, the newest capture thumbnail per saved site, saved links' previews and saved
  or watched YouTube stills already on this Mac are a fifth kind of `vector_index.db` (`image_index`), embedded in the
  background outside Sleep by a picture child (nice 10, 4 threads, 2 GB ceiling; the design board's pictures too),
  found by text through `/search?kinds=image` and recall's "Pictures that match" on local doors only. Scored by lift
  over the kind's mean (RRF and z-score measured and rejected, `storage.md`). Cold build 6.7 pictures/s, child peak
  872 MB. Audio and local-video frames: spikes with recommendations, not built (needs the owner).
- **2026-10-28 — ruling 47 recorded; two ways in for what the person consumes (G166, G206, G218, G223, G179, G29, G32,
  G94; branch `docs/ruling-47-ingestion-connectors`, docs only).** Tier 1, the default: their own browser and Mac,
  through the browser and macOS harnesses, G166/G206/G218 rails unchanged. Tier 2: an official API for a specific
  high-value source where it gives what the harness cannot (history, metadata, reliability) — the person connects
  each one, off by default, read-only, credentials 0600, the normal capture path. "Cicada never signs in" is amended
  for tier 2 only. Paths chosen: Telegram (47a), Notion, Readwise → API; Spotify → export only (2026-10-29: its
  Developer Terms §IV.2(b)(i) and §IV.3(a) bar storing or AI ingestion of API data); YouTube, Letterboxd → harness (plus
  Letterboxd's RSS); WhatsApp → local database; Google Calendar → Mac reader (`network.md`).
- **2026-10-28 — vision PR 1: measure pictures and sources, better logos, logo freshness, an image-vector stamp (G159,
  G61, G217, G195; branch `feat/vision-measure-pictures`).** `cicada coverage pictures|sources` and
  `GET /diagnostics/coverage/{report}` (ids and enums only). On a copy of the owner's bank: 65 % of 5,683 live pages can
  show a picture (media 88 %, brands 33 %, people 2 of 134); 5 % list a source, none from the person or an agent tool.
  The logo ladder keeps the largest mark (≥ 64 px stops; square `og:image` only as a fallback); ruling 40's record reads
  the page's prose and Cicada's own unconfirmed site (+1 trusted, +1 proposal); logo freshness is a weekly read-only
  report (2 visible redraws wait on the owner); image vectors re-embed only when the preprocessing really changed.
  Needs the owner: a person's own site as a face, project avatars, Gravatar from Contacts, Wikidata P18, Stage 1's
  site upgraded by ruling 40, the two redrawn marks (`G159`).
- **2026-10-28 — saved links feed the pages they are about (vision item 1; G61, G166, G191; branch `feat/vision-sources-reason`).** The person's reason for a save rides the reading queue (their words: remote with `sources` only), steers link summaries and earns a page described before it one more read (`read_for`); a saved link is a proposed where-to-check source on the project, company, concept, tool or place page its claims are about; `cicada_record_read(facts=…)` lands a read's specifics on their pages with page spans. Dry run on a copy of the owner's bank: 133 proposals on 113 pages, all in the one review; 9 haiku re-reads, the reason answered on 6 of 8 (2 before). Stage 1's prompt is unchanged (a note measured no gain). Coordinator calls: saves with no reason join the review; a read's facts never land on a person's page. **Next:** research citations as proposals (rulings 27/44) waits for the owner.
- **2026-11-06 — ruling 70 amended: what has come up lately lifts a question (owner; G113).** A question on a page said this
  week outranks one on a quiet page; a merge between pages said lately has `recency` (#691) and still never fades. `lift` in
  `question_order`, from `page_use.lately`; table in `features.md`. Age stays from when it was said.
- **2026-11-06 — the inbox is ordered by the expected change in what gets read (ruling 70; G113, G115; branch
  `feat/question-impact`).** `question_order` replaces `page_use.rank` for `GET /inbox`, the catch-up and `mode="ask"`;
  `page_reads` is the small per-memory read counter beside it (not the ledger); `orderIndex` goes to the app. Constants
  are judgment on two recorded answers; `impact` on each `resolution` row is how they get checked. Round 2 (same day,
  owner): staleness lowers impact (age from when it was said, relief from reads) and every queue uses the one order,
  with a gate test. The production code was run on the owner's bank (kept outside the repo, aggregates in
  `features.md`). The owner judged that top ten the same day: at most one question of a type in a row (limit measured,
  `features.md`), the owner's page never dilutes the facts an answer changes, merges and name questions do not fade,
  "still?" does; timeless facts fading is accepted until ROR-129. **Next:** the climb's `HomeQuestions` / `HomeSections`
  follow `orderIndex`; the app's `surface: "inbox"` is a follow-up.
- **2026-10-28 — the catch-up chat, backend and agent half (vision item 10; G115, G113, G209; branch
  `feat/vision-inbox-catchup`).** `cicada_check_nudges(mode="catchup")` serves three questions at a time, the pages the
  person uses most first (`page_use`, derived from the record, not the ledger), each in plain words with its reason,
  never repeating in a session; the `catch_up` MCP prompt and the skill section start it. `load_inbox` and ask mode
  use the same order. Sleep raises "are you still …?" on quiet roles and interests of the owner's page and nickname
  pairs, 3 new a drain. "Still interested?" questions are claim-level (an open interest claim 60–365 days silent),
  not decay questions, and rest on the owner's 2026-10-28 item-10 request. No rail or ruling changed. **Next:** the owner tunes the weights and N, and decides remote
  access, third-party roles and where the inbox sits in the app (report `vision-pr3-inbox-catchup`).
- **2026-10-28 — page blocks and the model catalogue (vision items 5 and 4; G121, G122; branch
  `feat/vision-page-contract-models`).** `GET /entities/{id}` serves `blocks` (`page_blocks`) and an ETag of stats
  only (the app's `EntityCardCache`), history rows `trigger`/`via`, and the card one "why it matters" line;
  `cicada_recall_detail(include=…)` words the same blocks (never per-page history remotely). Every engine card
  carries a `catalogue` (harness-reported only; the Claude plan list follows `claude --help`; drift said in words, a
  fixture per harness). Waits on the owner: a public vendor model list, key-provider listing, the page layout (D).
- **2026-10-28 — ruling 46 recorded; Auto reaches Cursor and OpenCode after the two plans (G49, G50; branch
  `feat/auto-ladder-46`).** Auto: Claude plan → ChatGPT plan → Cursor → OpenCode on a subscription model; Grok is in
  neither Auto nor scheduled runs until a live sign-in shows what a subscription call reports. Read from #494's cached
  tool status, a cycle waits at most 9 s and the Sleep page never; an unknown or hung tool is skipped, said in words.
  Tested with stub tools only (no live call); the app's one-line Auto rule updated (`Copy.EngineHeadline.rule`).
- **2026-10-27 — ruling 43 recorded; an agent's own memory notes are captured (G105, G110; branch
  `feat/agent-memory-notes`).** The Claude Code hook reads `projects/*/memory/*.md` where they live and posts their
  bytes; one agent-worded episode per note (edit in place, delete tombstoned, scrubbed, demo 409, dated by the note,
  no mention, `origin_session_id` → the session's episode); the first firing back-fills; one Privacy switch, on.
  On this Mac, read-only: 204 notes (15 of them indexes) in 22 of 71 project folders, 1.1 MB. Codex's
  `~/.codex/memories/` is comparable and not read yet (`capture-and-sleep.md`).
- **2026-10-26 — saved lists on by default, TikTok's export read again, Google Calendar on the Mac (G71, G206, G142;
  ruling 39 dated line; branch `feat/sources-defaults-calendar`).** Onboarding asks once, pre-ticked, whether the
  person's own agent keeps their saved lists current (the answer is the consent); offs are remembered; an older
  install's lists turn on for accounts its memory shows. TikTok's current `user_data_tiktok.json` keeps favourites and
  likes under "Likes and Favorites" and watch history under "Your Activity" → "Watch History": the reader returned
  "Your Activity" alone and refused the file — fixed and tested on today's layout. Every Import a file row says where
  the file comes from. The Calendar row lists the accounts it read and opens Internet Accounts to add Google's (no
  prompt); Google's secret iCal address through the feed path is not offered, because a subscription is stored in the
  bank's `calendars.yaml`, which would put a credential in the bank. Needs the owner: the detail-pane screenshots.
- **2026-10-27 — ruling 45 recorded; the Projects list is the person's (G141, G222; branch `feat/projects-v2`).**
  Backend and wire (PR 1): `mine` / `not_mine`, the person's description and rename, Suggested with its reasons,
  every conversation tied with why (FTS-backed, `partial` while the index builds), influences, three agent tools
  (`cicada_create_project`, `cicada_link_conversation`, `cicada_add_influence`) on every door, Claude export projects,
  ChatGPT project ids and the relay's `project`; wire `g141-7`. The SwiftUI page is PR 2 (needs a Mac). **Next:** the
  acting owner confirms `CLAUDE_EXPORT_MINE` with the owner.
- **2026-10-27 — ruling 44 recorded; light web context and "why it matters to you" (G121, branch
  `feat/web-context`).** Public pages get cited, dated world facts on plan runs, kept current by use and volatility,
  undoable; a private person's name never leaves; every page's relevance derived on read. Dry run on a copy of the
  owner's bank: 9 of 281 people public, 39 lookups, 76 adds and 1 replacement; the stale-employer page now closes its
  old employer. **Next:** the owner checks the people
  list in the report; the app should show the relevance line and a "go deeper" button (needs a Mac).
- **2026-10-27 — ruling 41 recorded; one person as several People cards (G209, PR #483).** Resolve weighs a new
  name's own aliases, close spellings and names said together; an alias is never another entry's of the same
  conversation; one exclusive relation held twice asks; nicknames titled and kept per ruling 41. The bank's repair is
  left to the owner on a per-item dry run.
- **2026-10-26 — ruling 40 recorded; an organisation's own website found during consolidation (G61, G146; branch
  `feat/org-website-sources`).** `org_sites` in Sleep's site-check step: the record, then one Wikidata match, trusted
  only when the homepage names the entity, otherwise a proposal in the "Confirm N links" review; a public place with a
  trusted site draws its logo. Dry run on a copy of the owner's bank: 55 trusted, 114 proposals, 29 left to another writer's entry or a waiting proposal, 285 nothing. **Next:**
  the owner reads the dry run's rows before anything touches the real bank (nothing was applied); the app should show
  `verified.why` ("Found by Cicada: …") on the source row (needs a Mac).
- **2026-10-24 — ruling 39 recorded; both dates on every episode (G218, G71; branch `feat/both-dates`).** Every new
  episode records `received_at` beside `timestamp` (the item's own date), stamped by `create_episode`; a feed item is
  dated by its publisher and is no time signal, so a back catalogue is neither activity nor a charge; the Reader, the
  Sources rows and recall show the received day only when it is days later. Trace watch history stays on (39b); app
  wording goes to the coordinator (39c). No backfill: older episodes read as unknown.

- **2026-10-23 — the new user, fourth pass (G148, G112; branch `fix/newuser-memory-4`).** A switch said for a project
  is written on the project (Stage 1's prompt; the seed's `uses` endings read `replaced`/`replaces`/`switched from`) —
  the owner's decision below keeps endings same-subject; a Stage 4 skill whose summary rests on a belief that closed
  after it leaves the handshake's *How to work with me* (`skill_staleness`, W6, no model call); Stage 1 stores a stated
  last day as an absolute date (`ends`) and a manager said with the job's organisation closes with the job
  (`premises`, seed `dependents`, W7); from a live test, a newer value under another wording closes the older
  (seed `value_attributes`) and "moved from A to B" ends A's uses. Drop replays (haiku): 18/20 on the project
  before, 20/20 after. newuser: 24.5/25
  by hand in each of four Sleeps (baseline 24). Evidence: `~/cicada-verify-evidence/m4-*`.

- **2026-10-23 — the notch, second version (G191 v7, G221, a note on G219; branch `feat/save-notch-v2`).** The ask-why field grows to five lines then scrolls (eases 0.12 s, none under Reduce Motion; DESIGN_RULES ruling 2026-10-23: a field growing with typed words is not a DR-60 keyboard command). The four reasons stay the fixed row; a 38-reason bank (`saved_why.MORE`, `more` on the options) feeds three to six suggested chips ranked on the Mac with no generative model (site, the link's words, the person's past picks, EmbeddingGemma's similarity only when installed via the read-only `POST /sources/saved-why/suggest`). Documented, not built: saves in other apps (**G221**, recommended: a Chrome extension seeing the person's own save click, G206/G71 lists confirming — five owner decisions), the v2 classifier option (Foundation Models or the image encoder over a screenshot; needs a ruling against "No LLM at capture time"), and the Composio note on G219 (native first; Composio only as an optional entry the person's own agent uses). **Open for the owner:** G221's decisions; whether bank reasons should deepen site exploration; whether typed line breaks should be kept when stored.

- **2026-10-23 — ruling 38 recorded; `/v1` generated from the remote tool table (G213; branch
  `feat/v1-from-tool-table`).** The owner answered the four follow-up decisions (ruling 38: API, phone, syncs, traces
  with screenshots). Built here: `agent_api.OPS` is generated from `REMOTE_TOOLS` minus `EXCLUDED` (only the
  handshake), named by `cli_map` (`Row.operation`; an `api_op` column for the 11 frozen names) — 11 → 27 operations,
  `capture_turns` relayed as `evidence_kind: assistant`; pinning tests for the set, the frozen names, scopes and
  `openapi.json`. G91, G218 and G219 carry the ruling as their decision lines; their code is their own PRs.

- **2026-10-23 — the owner's five follow-ups recorded (docs only; branch `docs/followups-2026-10-23`).** Phone
  sources extend **G91** (stays capture-only; next a device build, `/capture/file`, App Intents, on-device voice);
  tools over an API extend **G213** (`/v1` generated from the remote tool table, names in `cli_map`, 11 → 27
  operations, one G199 contract, no third door); activity traces are **G218** (DECIDE: off by default, outside every
  bank, encrypted, never on the network, screenshots a separate opt-in); syncs are **G219** (Apple Reminders through
  EventKit, then Notion export and API, one-way, never write-back; pointers on G13 and G142); the "show me" skill is
  **G220** (the owner builds it; pointer on G138). Each row ends in its owner decisions with a recommended answer. The
  proposal, with prior-art sources, is kept outside the repo with the redesign research
  (`followups-2026-10-23.md`). **Decided:** ruling 38 (2026-10-23) answers G91, G213, G218 and G219; G220 is the owner's.

- **2026-10-23 — the new user, third pass (G148, G209; PR #442, branch `fix/newuser-memory-3`).** A drop ends the project's
  qualified and related uses of the tool, not only a plain `uses` (seed `endings.uses.also_ends`,
  `EndingFn.ended_by`); a held full name whose given name is one person page's whole title asks "same person?"
  (`entity_resolver._given_name_pages`, W1's cap and `merge_rejections`); `## Related` names each link by the newest
  open claim behind it, not the first edge ever extracted (`conflict_resolver.related_edges`, refreshed by the claim
  pass). newuser: 24, 23.5, 24 of 25 by hand over three Sleeps (baseline 24). **Answered (owner, 2026-10-23):** one Sleep in five
  put the drop on the person's page, so the project's uses stayed current — the rule stays same-subject and the fix is
  at extraction (ruling 37, dated line C; fourth pass). Evidence: `~/cicada-verify-evidence/nu3-*`.

- **2026-10-23 — something never called a project gets a page (G141; D4 amendment in ruling 36; PR #441,
  branch `fix/project-fallback-page`).** The judge joins the spellings of one thing with no birth; over the promotion bar
  read across them, one `concept` page marked `proposed_type: project`; a later birth retypes it in place with `born`.
  newuser: the canoe has one page; 24/25 by hand ×3, as the baseline.
- **2026-10-22 — the new user, second pass (G148, G209, G141; ruling 37; branch `fix/new-user-memory-2`).** Ruling 37
  (owner): a fold from the shipped seed settles by rule and a follow-up names its thread; a new save is dated when it
  was saved. Also from the newuser write-ups: a held full name whose alias is exactly one person page asks "same
  person?" (W1, never a merge); a project mention whose alias names one project page brings it to the judge (W2); "New project
  with X: name" counts as the person's words (W3); the D4 gate reads the type a create writes (W4). Numbers on the
  G148 row and in the PR.
- **2026-10-22 — the new-user benchmark and what it fixed (G148; branch `fix/new-user-memory`).** `benchmarks/newuser`
  loads an invented person through the real doors onto a verify-cicada scratch backend, sleeps once (plan, haiku) and
  asks 25 questions over MCP stdio; rerun it before each release (its README). Branch base 23.0/25 → 24.0/25 (three
  repeats each, no spread). Fixed: calendar events dated the day they happened (`calendar_local`), "worked with" /
  "dropped" endings (seed), skills grounded only on conversations (`skill_grounding`, `inbox_tend.record_origin`),
  created pages counted (`change_timeline`, `git_service.CREATED_ACTIONS`), recent conversations without calendar
  entries (`state_dictionary`). The written-up findings (G209, G141, G21, G112) are on the G148 row.
- **2026-10-22 — projects born from a repository or the person's words (G141, ruling 36 D4; branch `feat/projects-v2`).** Stage 2 mints a project page only on a birth record Stage 1 computed with no model: a harness session the hook observed in a checkout of that folder name, or one clause of the person's own turn calling it a project; `born:` is written once; six standard sections and the people involved ride the timeline wire (g141-5); `api.scripts.project_origins_dry_run` lists every existing project page as repo / words / neither, read only. The hook reads no git remote (G110 D2), so the folder name stands in — disclosed on the row (since ruling 22 D2a, 2026-10-29, it also sends the remote's salted hash, and a renamed or moved repository keeps its page). **Next:** the acting owner runs the dry run on the real bank and asks the owner before any review list; the SwiftUI page is specced in `app.md` (needs a Mac).
- **2026-10-22 — the redesign's decisions recorded (ruling 36; branch `docs/redesign-2026-10-22`).** The owner's answers D1–D6 are ruling 36: a key secured properly or the person's own Claude Code / Codex, never a local default (amends ruling 31); a quick read after each conversation, on by default only if measured better (amends the capture rail); the agent tiers plus an HTTP API for agents without MCP, served on the G135 listener; projects from a repository or the person's words; the person's-photo gate on with sources on people; Settings in six. Backlog: new G205–G207, G209, G210, G212, G213, G216 (done, #418) and G217 (the connection model — the briefs' "G204" was taken); G208, G211, G214, G215 fold into G61, G141, G91 + G135, G50 as redirects. `feature-status.md` tracks each line.
- **2026-10-22 — the MCP error and argument contract (branch `mcp-error-contract`; G199, G200 A7/A9, Hyrum audit
  A1/A4/A6).** Both doors check a call against the schema they advertise, once, before a body runs
  (`tool_contract.check`): a bad argument answers `isError: true` with ``Invalid arguments: `<field>` …`` naming every
  problem; `since` must be a date or a number of days, `cicada_project`'s `tz` a real zone. A refusal keeps its
  sentence and answers `isError: true` with `structuredContent: {code, data, message}`, from the command line's own
  `REFUSAL_CODES` (now also `invalid_arguments`, `out_of_range`, `error`), so a code means the same thing to the CLI and
  to an agent; ~140 refusal sentences in `mcp_tools` carry codes. An exception names its class only (stdio, the tool
  door, remote). Every read reply is fenced as reference data on both doors; a write's provider lines are marked the
  same way on both. The primer (contract 19) names no HTTP route and picks its variant by exact client name, with a
  `desktop` variant for `claude-ai`. Recall's state cursor says `pending_as_of` / `refresh_with`; confidence shows two
  places; `cicada_recall_detail` drops five bookkeeping keys and never ends a part inside a fence it can avoid. The
  golden fixture now pins whole `tools/call` results. **The leniency shipped in 0.7.0 only and ended in 0.7.1
  (#445):** a digit, decimal or `"true"`/`"false"` string where the schema says a number or boolean
  is refused on both doors like any other wrong type (`invalid_arguments`, the sentence saying to send it without
  quotes); the lenient branches in `tool_contract._value` and the dating test are gone. Review fix round: a
  read reply is fenced whatever its code, with Cicada's own directions outside the markers (`Reply.framed`); a recall
  with stored words is never `empty_graph`; enums match without case; tolerated values (`engine`, `basis`, shot kinds,
  roles) have no enum; a release batch keeps its good rows; every door logs the failing file:line, no message; the
  writers' catch-alls no longer leak exception text. Tool and argument names are unchanged (G180 names no rename yet); `cicada_resolve_inbox`
  also takes `item_id`, unlisted. Left out: the claims fence rendered through the one wire builder (A6), and fencing
  the command line's text.
- **2026-10-22 — ready for background agents: every verify recipe driven, the plan token only in the engine's child,
  CI on `dev`, a neutral bank identity (G203; branch `agent-ready-ci`).** The 19 recipes in
  `.claude/skills/verify-cicada/features/` that had never run were driven with `cv` on scratch banks: 4 worked as
  written, 11 were wrong (request shapes, selectors, a CLI step that is person-only, Ask needing `--search-model`) and
  are fixed, and 4 now say which part cannot be driven and give the nearest check (the video lease lifecycle, a site
  exploration, the remote listener and OAuth, the bank menu without focus). One product defect found: G204 (`cicada_write_claim` names an
  id that is not on the page when it folds into Sleep's claim). `cv` no longer puts `CLAUDE_CODE_OAUTH_TOKEN` in the
  scratch backend's env: a 0600 file in the run dir, read into the engine's `claude` child by `plan-claude`, deleted and
  masked at cleanup (`cv selftest` 87/87; `cv` also drops it from its own env, so no child of `cv` inherits it). `.github/workflows/dev-ci.yml` runs the backend crucial tier on pushes and
  PRs to `dev` (260 passed on `ubuntu-latest`). A bank fills only the half of its git identity nobody configured with
  `Cicada` / `cicada@localhost`, at startup and at every runtime switch, instead of the account's guessed name and host. Evidence:
  `~/cicada-harness-run-2026-10-22/round2-agents/`.
- **2026-10-22 — Settings in eleven sections (Hyrum audit B1, with B11, B12, B23; G139; branch `settings-regroup`).**
  Memory's one card joined Search & files (now *Search & memory*), From anywhere joined Devices (now *Devices &
  access*), Plans & keys closes Engines. Each moved page is a group under its old header anchor (`page:memory`,
  `page:remote`, `page:plansAndKeys`); `SettingsSection.retired` opens a saved selection, the old `agentsMode` and a ⌘K
  recent on the new home, never General. General has one *Getting started* card; the command-line tool is on Agents;
  Reading folds its method pickers while off. Every "Settings → <old section>" in app copy, backend sentences and docs
  says the new path; `SettingsAnchorsTests` fails if an entry, deep link, retired value or pointer stops resolving.
  Found on the way: a query with a bare "&" ("Plans & keys", "Privacy & data") matched nothing (`QuickMatch.tokens`
  drops a punctuation-only word beside a real one; alone, or an emoji, it stays a token), and a landing below
  late-loading cards stopped short (the row lands again on each move inside a 3 s window, never animated, until the
  person scrolls). Review round: a saved old section lands on its group; folds open on a landing without storing it. Presentation only. Not done: B5 (shared step renderer). Pass 2's "B1 is the owner's
  call" stands as the merge gate. Detail: `app.md` (Settings), the audit's *B1 as built*.
- **2026-10-22 — a recall stays under the harness's result cap whatever the bank holds (branch `fix/recall-size`).**
  On the live install a recall for a person's handle returned 221,719 characters (1,782 lines); Claude Code refuses an
  MCP result over its cap, so the agent got only an error. Cause: the owner page's ~2,300 `related` ids printed on one
  `Related:` line and Key Facts always kept whole. Now: `RECALL_BUDGET` 40,000 characters (20,000 remote, under its
  24,000 cap), the `Related:` line at 12 names plus "… and N more" with the page-read call, Summary and Key Facts
  cut at whole lines within the per-entity budget ("- … and N more on the full page"), the inbox block at 5 questions,
  the cold-start hub list at 8,000, and a whole-result guard that leaves out the lowest-ranked pages first and names
  them. Line shapes and headings unchanged; under the budget a reply is byte for byte what it was (golden passes).
  Synthetic bank over MCP stdio: 149,058 characters before, 14,087 after (`cv mcp call cicada_recall`).
- **2026-10-22 — the 0.6.0 release build type-checks on the runner (branch `fix/release-typecheck`).** Release run
  39714438472 failed: `SaveWhyPanel.swift:394` "unable to type-check this expression in reasonable time" on the
  macos-26 runner (it built on the dev Mac). A release build with `-warn-long-expression-type-checking=150` and
  `-warn-long-function-bodies=300` listed 15 warnings in 10 functions; each was split with typed locals, smaller modifier chains or extracted
  helpers, no behaviour or layout change (`SaveWhyChipRows`, `PersonBeliefs.newestFirst`, `fetchConsumption`, the
  `CicadaApp` scene body, `ContentView.body`, `ConnectionsView.body`, `SleepView.lifecycle`, `NeutralButton`,
  `InboxQuestionList`, `ReadingWebView`). Worst before: one expression 2,112 ms, a body 11,770 ms; after: no expression
  over 75 ms, no body over 249 ms (same Mac, release build). `Package.swift` now warns on any expression over 150 ms
  (`working-method.md`).
- **2026-10-22 — four Swift test classes no longer depend on the machine (branch `fix/tests-environment`).**
  `AskConversationsTests`, `BookmarksV4Tests` and `ProjectsListTests` asserted US dates through formatters that read
  the runner's locale; `AskConversationRow.day`, `Copy.Bookmarks.noLongerIn`/`shortDay` and
  `ProjectsModel.accessibilityLabel` now take `locale:` (default `.autoupdatingCurrent`, so a Mac in Spain still reads
  "2 Oct"), and each test pins `en_US` and asserts `en_GB` too. `PileRenderTests` compared exact pixels from an
  `ImageRenderer.cgImage` that turned 16-bit PQ when an installed app's icon was in the scene (one red step off on the
  chat spine); it now draws into a pinned 8-bit sRGB context. Sweep of the other Swift date, time, number and pixel
  assertions: all already pass a locale or format with `en_US_POSIX`, and no other exact-pixel test draws an installed
  app's icon. Rule in `working-method.md` (test baselines).
- **2026-10-22 — Sleep dates a conversation by its local day; relayed turns take ChatGPT's zone (ruling 34 follow-up;
  branch `fix/sleep-local-day`).** One reading rule, `episode_ids.local_day` (any stored stamp → the day it was said in
  this machine's zone; `ask_sources.local_day` and `change_timeline` now call it). Sleep's day attribution goes through
  it: `source_dates.episode_day` (the Stage 1 date note, `source_episode_day`, prose repair), a claim's `valid_from`
  (`entity_extractor._claim_date`, papers), a page's `created`/`last_referenced`/new-mention day
  (`conflict_resolver._said_day_string`) and the two repairs that date episodes. No decay arithmetic changed. Found on the
  way: `link_enrichment` dated a `recommends` claim `ep_YYYY-MM` (the episode id's first ten characters), now the day
  it was said; and four writers still minted ids from a UTC stamp (Messages, Wispr meetings and notes, watched folders,
  `watch_record`), now `id_day`. Relay: ChatGPT sends `_meta["openai/userLocation"].timezone` with every tool call; the
  listener reads only that IANA name (never the city or coordinates; nothing stored or logged) and passes the offset to
  `cicada_capture_turns` — no tool argument added, no schema change. claude.ai sends no zone, and a model is never asked
  to guess one, so its relayed ids take the server's zone. Left, with reasons (`capture-and-sleep.md`): the id-day
  readers inside decay (`latest_said`, `mention_weeks`, `inbox_tend._said`), Wispr dictation's UTC-day source key,
  Messages' titles, and every `[:10]` on a stored day field, telemetry (UTC by design) or git dates. Review of #406:
  a claim id hashes `valid_from`, so a re-read of a midnight-window conversation minted a new id and Stage 3, which knew
  a re-read only by id, reopened a closed claim as an open copy and recorded an ending twice; `_reread_twin` now also
  matches a closed, non-withdrawn claim by slot and object when every conversation it was heard in is already cited.
  Tests: `test_sleep_local_day.py`.
- **2026-10-22 — the video queue's lease findings fixed as ruling 34 decided (G162; branch `fix/video-lease`).**
  F1 + F5: `cicada_video_claim` mints a 128-bit `lease_token` per leased video and prints it on the video's line; a
  hand-back, and a `cicada_record_watch` with no basis, end a lease only with that token (anything else is
  `not_yours` / `left`, and the lease lapses on its own; the session id only refreshes). F2: every queue writer reads
  the saved videos under the lock (the writers lost their `saved` argument). F4: a refresh never carries a lease past
  `MAX_LEASE_PERIODS` = 3 lease periods from its claim. F3 accepted (xfail reasons cite the ruling and its trigger).
  Contract (Hyrum Mode A): `lease_token` added to the stdio and remote schemas of both tools, the CLI's
  `video record`, both primers (contract 18, remote 13), the claim reply and the librarian skill; the old
  `{url, code, reason}` release still parses and answers with what to pass; the person's hand-off prompt names no
  token (ruling 12) and points at the claim reply. Model: `code-*` checks run the fixed code; each finding's check
  runs it with that one fix removed and still fails; three new breaks (`release_ignores_token`, `no_lease_cap`,
  `record_ignores_token`) are caught by `able_to_fail.py` (12 of 12). `run.sh`: 33 of 33 as expected; `--only
  code-churn` (P2, no lost row, on the fixed code) passes at 97,464,544 states in 21 minutes with four workers.
- **2026-10-22 — one primary and its clients: the two-device test's defects fixed (G202 D1–D3, D5–D7; branch
  `fix/sync-clients`).** The test ran the Mac and a Linux server both ways on scratch banks: one writer with clients
  works (captures, saves, claims, edits, offline spool, concurrent writers); two primaries are UNBUILT (G132). Fixed:
  a hook spool entry names the server and bank it was captured for and goes only there (a resend carries `bank_id`,
  the capture routes refuse a bank id foreign to their memory with 409 `bank_mismatch` and answer `bankId`; a
  refused entry is held apart and never blocks later turns — review of #408); the app's outbox does the same
  per post and sends `X-Cicada-Bank-Id` on a server; `cicada status` and Settings → Devices count both spools by server,
  and a successful MCP call or command flushes what waits for its server; Sleep's search warning says "this server" off a
  Mac; the handshake names the roster's bank (`default`, not the folder) and `on <host>` on a client; a running MCP
  session says once when its memory moved. Left open: D4 (device on claims and commits, G181), D8 (queued MCP/CLI
  writes), G132. Tests: `test_sync_clients.py` (D1 reproduced with two loopback servers), `HeadlessAppTests`,
  `OutboxLanesTests`.
- **2026-10-22 — the dev auto-update runs on a Linux server too (G181; branch `feat/linux-dev-autoupdate`).**
  `scripts/dev/install-auto-update.sh` branches on `uname`: on Linux it writes a systemd user timer
  (`cicada-dev-autoupdate.timer`, `OnCalendar=*:0/5`, `Persistent=true`) and its oneshot service; `--uninstall` removes
  either platform's job. `auto-update.sh` on Linux keeps every guard (on `dev`, clean, ff-only, waits out Sleep, the
  installed stamp), restarts `cicada-backend.service` (`CICADA_BACKEND_UNIT`) when runtime code moved, re-syncs a server
  venv through `sync-server-env.sh` (a full venv with `uv sync`), and has no app to build. macOS unchanged.
  `api/tests/test_dev_auto_update.py` stubs `uname` (CI runs on Linux) and covers both.
  Follow-up (review of #400): on Linux the stamp moves only when the sync and the restart both worked (a failure
  retries next tick), and the Sleep check asks the port and home the backend unit names. the dev server runs it
  (`cicada-dev-autoupdate.timer`, first run 2026-10-22 moved the stamp to d25ba62).
- **2026-10-22 — the Skills inventory sees Claude Code's plugins and tags every skill's kind (G201 slice (a), TODO
  ruling 35; branch `feat/skills-see-plugins`).** `skill_plugins` reads Claude Code's installed plugins read-only from
  its own files (`installed_plugins.json` v2 and the older shapes, the user `enabledPlugins`, each plugin's manifest and
  its skills' SKILL.md frontmatter, `disable-model-invocation` included); missing or corrupt files are an empty answer,
  an install path outside `.claude/plugins` or a manifest path out of the plugin is never followed, a project-scoped
  switch is null (its project's settings are never opened), and nothing toggles a plugin (`canToggle: false`).
  `skill_kind` tags every skill without a model: third-party and plugin skills `generic`, a candidate (noticed, held,
  drafted, published draft) `about-you` when its evidence pages or `[[links]]` name a person or project page or the
  owner's, else `unknown`; the person's flip is `PUT /skills/kinds`, stored by `skill_store.set_kind` in
  `$CICADA_HOME/skills/kinds.json`. `GET /skills` and `cicada_skills` gain `plugins`, `kind*` and `weight` (additive;
  per agent the skills loaded and an estimate of description tokens, characters/4, no cap enforced). The Skills page
  shows a Kind column, the Plugins group and one weight line (DR-59's dated exception, ruling 35 §6). Tests:
  `test_skill_plugins.py`, `SkillsPageTests`. Pick up: slice (b), the Stop hook keeping the names of invoked skills.
- **2026-10-22 — MCP hygiene from the Hyrum audit (branch `fix/mcp-hygiene`; G199's two integrity cases, G200 A8,
  A10, A11, ruling 34's episode-id day).** `cicada_write_claim` refuses an `observer` outside its pattern and
  `cicada_save_episode` refuses empty `content`, in the tool bodies, so stdio, `/tools/call`, the remote connector and
  the command line refuse alike (`code: refused`, nothing written). The advertised `observer` pattern no longer names
  the legacy observer value; the body still accepts it. Stdio answers `ping`, `-32700` and `-32602`, and annotates its
  read tools from `catalog.READ_TOOLS`. `SKILL.md` (and the plugin copy) and the type-hub blurb no longer teach a stale
  layout, "never edit" or a file path. Ruling 34: the two hook writers mint the local day (`episode_ids.id_day`); a client
  posts its own `utc_offset_minutes` (additive on `/capture/session` and `/capture/turn`); `ask_sources.said_day` and
  `benchmarks/hard_questions` read the stamp in the person's zone; ids are never renamed. The golden fixture did not
  change. Left for G199 proper: `isError` for refusals, `structuredContent`, validating every argument. Found, not in
  scope: Sleep's `source_dates.episode_day` still dates a conversation by its UTC stamp's first ten characters.
- **2026-10-22 — Settings defaults, pass 2: Engines opens on Auto (G139, ruling 31; branch `feat/settings-defaults-2`).**
  Settings → Engines leads with what Auto uses now and why, in words: "Using your Claude plan — you're signed in", or
  "Nothing to read with yet" with a link to Plans & keys. The other five engines sit under *Use a different engine*
  (DR-39, per viewer `cicada.engines.othersOpen`; a search hit opens it). A stored choice that isn't Auto is shown by its
  card's name, with *Back to Auto* (`PUT /sleep/engine {mode: auto}`, never sent while the environment fixes the engine).
  Onboarding's Who reads keeps the full row of cards. Engines and Plans & keys stay two sections: merging them adds no
  step saving, because sign-in, sign-out and key removal would sit below an open chooser (B1 is still the owner's call).
  Plans & keys' status lines are in words (`ConnectionsView.howLine`/`unconnectedDetail`: no CLI, local address, key
  path or variable; `cicada engine list` keeps the backend's sentences). The fixed engine (Engines), the fixed server
  (Devices) and the usage ledger (Privacy) each link `docs/settings-outside-the-app.md`, which names what to change.
  **B-model fixed:** a fresh bank in a checkout with no bundled model reported `model` = the larger default, and the
  app read that as "set up for the larger version on another Mac". `GET /embeddings` now sends `recorded` (null when
  nothing is built yet), and the row offers the sharper version instead (an older backend reads as before). Also
  fixed: Auto with no engine said "Your key sends what it reads to its provider" (`LeavesMacNote`), which is false.
  Pick up: review.
- **2026-10-22 — Settings works toward good defaults (owner: "Remove all those environment variables and stuff in the
  settings page. Let's just work towards the good defaults"; G139; branch `feat/settings-defaults`).** No Settings page
  shows an environment variable, a settings file, a home path, a raw model id or a maintenance button. Cut: Advanced
  (whole section; a saved selection opens General), Engines' model picker and model-id fields (each engine's default;
  a model already chosen keeps running; the Sleep page's menu still switches a listed model), the model id in Settings'
  preview lines, Search & files' Advanced (version picker, account sheet, rebuild), Memory's *Fetch link previews*
  (Sleep's tail does it every run) and Agents' `make install` card. Folded: unsaved API key cards under *Use an API key
  instead*. Said in words: the memory folder, where keys and tokens live, the pinned engine, the server pin, and
  `engine_cause`'s unknown-model fix. Every stored value is still honoured; routes, `/status` and the `cicada` commands
  are unchanged. Every data, privacy, consent and trust control stays drawn and searchable
  (`SettingsDefaultsTests`). Detail: `app.md` (Settings), the Hyrum audit's B rows. B-model's "built elsewhere"
  inference is fixed in pass 2 (above).
- **2026-10-21 — the seven backend failures on dev before 0.6.0 (branch `fix/suite-0.6`).** The full suite on
  `24a419a7` gave 7 failed, 10,864 passed. Two were code: the entity card opened the claims ledger through
  `quiet_pages.page_is_quiet` (#391) because `bank_index.file` parsed with the ledger fold — it now reads the header
  exactly as `bank_index.files` does, so no `bank_index.file` caller opens a ledger or carries the fold's read mark;
  and `handshake.claude_skill` (#364) named Claude Code's skills folder itself — the path now comes from
  `skill_folders.has_skill` (read-only), so `skill_store` stays the only module that names that folder and writes. The
  plugin got `.claude-plugin/icon.png` (the app icon), since the installed `claude plugin validate` now warns
  `ICON_MISSING`. Four tests were stale: the scheduled billing preview follows ruling 4c (a plan unless the person's
  switch is off, #360), the writer inventory names #391's `_write_page`, and the video tests take ruling 32's remote
  contract 12 and `cicada_capture_turns`' exemption from the bank write gate (#359).
- **2026-10-21 — The inbox tidy as a trace the coordinator reads, then a vetted apply (owner rule 2026-10-20;
  branch `feat/tidy-trace`).** A counts-only dry run once let 8 wrong conflict settles through. `api/scripts/
  inbox_tidy_trace.py trace --bank <path> --out <file> --engine plan --model haiku [--kind merge_suggestion]` runs the
  tidy's dry run in process and writes one 0600 JSONL row per question (id, kind, the two names, merge / keep_apart /
  settle / leave, the judge's confidence, a one-line reason) outside every bank; `--engine plan` never resolves or
  calls the bank's configured engine. `… apply --vetted <file>` sends the kept rows to `POST /inbox/tidy/apply`, which
  settles each exactly as traced as Sleep's undoable commit, only while the question and its pages are unchanged.
  Detail: `features.md`, "The coordinator's trace and vetted apply". Tests: `test_inbox_tidy_trace.py`. Pick up: the
  coordinator traces the owner's "Possible duplicate" questions (#389's empty-description cause) and reads every row.
- **2026-10-21 — a merge or rename keeps what the person gave the page (G147, G146; branch `feat/next-row`).**
  `entity_merge.merge_entities` unions both pages' `kept_on` (`decay_policy.merged_keeps`), so a keep answered on the
  absorbed page still slows the merged page's fade; it carries the person's picture choice when the winner has none
  (the upload's file moves to the winner's id) and removes a loser upload the winner's own choice outranks;
  `rename_references` moves an upload's file with its page. The footprints name the picture files
  (`entity_picture._merge_plan`, `rename_footprint`), so the dedup sweep's transaction and the placeholder repair's
  dirty check cover them. Every merge door is driven (`test_merge_edges.DOORS`). Tests:
  `test_merge_keeps_person_marks.py`. Pick up: review and merge; tonight's inbox tidy merges then keep both.
- **2026-10-20 — Contacts as a seed; imported-only pages stay quiet (ruling 33, G154; branch `feat/people-seed`).**
  Unmatched address-book cards wait in `$CICADA_HOME/people/<bank>/contacts.json` (`people_directory`, shared with
  LinkedIn; 0600); a person's first conversation mention naming exactly one waiting card promotes on its own and the
  page is born with the card's name, sources and photo (`entity_resolver._card_for`, `contacts_local.seed_page`);
  Sleep's tail rematches the rest (`_rematch_contacts_safely`). The app marks the "me" card (`isMe`, that card only),
  which goes to the owner's page. `quiet_pages` derives *quiet* (an imported page not mentioned yet): `GraphNode.quiet`
  (`NODE_SHAPE` `+quiet`), `GET /entities/{id}`'s `quiet`, hidden from every inbox reader; the app dims quiet nodes
  (faint fill, type-hue ring) and Clusters rows. Tests: `test_people_seed.py`, `QuietPagesTests`. Pick up: the owner
  connects Contacts on his bank (0 of 273 people matched today) and reads one night's Sleep log for the promoted count.
- **2026-10-20 — Sleep asks about half the model calls per conversation (branch `perf/sleep-calls`).** A
  14-conversation haiku night made 574 calls (disambiguation 268, merge 116, conflict 110, extraction 48). Stage 2's
  judge now weighs up to 6 of a name's candidates in one call and Stage 3 checks up to 5 pages for contradictions in
  one call (a lone one keeps the old prompt); and the judge now reads the extraction's `summary` — it was reading
  `description`, which Stage 1 almost never fills, so first-name mentions became "Possible duplicate" questions.
  Synthetic night (`benchmarks/scale/sleep_calls.py`, 8 conversations, plan + haiku, replayed prompts): 16.0 → 11.4
  calls a conversation, pages identical under batching alone; projected ~280–320 calls for the owner's night.
  Detail: `capture-and-sleep.md`, *Fewer calls per conversation*. Tests: `test_sleep_call_batching.py`,
  `test_entity_resolver_concurrency.py`, `test_conflict_resolver_concurrency.py`. Pick up: the coordinator reads the
  next scheduled night's `llm_call` counts by stage and the inbox's new "Possible duplicate" count.
- **2026-10-20 — Ask infers implied facts and reads Spanish conversations for an English question (G148; branch
  `feat/ask-gaps`).** A fact-worded question the record only implies (a state or country from a city, a holiday, a
  described thing's name, a yes or no about someone, an age, a preference) gets a stricter note: a stated line wins,
  else "probably …, because …", a loose link still declines. An English question whose nearest conversations are in
  Spanish goes by meaning (the record's language decides, never missing words). The meaning leg ranks turns without
  the speakers' names, from two passages a conversation. On haiku, 3 runs: implied facts 4.67 → 12 of 15 (better,
  p = 0.016; adversarial 2/3 both sides); English over Spanish, behind a per-model score floor so a never-said
  question reads as on dev (review): 7 → 11 of 14, abstentions 7/7 both sides (p = 0.125, small set). Fixture
  `benchmarks/public/fixtures/locomo-es-turns.json` (`--turns`). Pick up: the coordinator's `--compare` on the
  owner's two sets — every Spanish prompt changed. Detail: `docs/research/2026-10-17-memory-benchmarks.md`.
- **2026-10-20 — Ask reasons a judgement from the record and answers Spanish by meaning (G148; branch
  `feat/ask-infer-es`).** A judgement question ("would <name> likely …", "¿es probable que …?") gets a note to answer
  "probably …, because …" from the record; a recorded fact still declines. A Spanish question goes by meaning: the
  search model's nearest passages and ranked claims/items reach the prompt (Spanish answer turns 8 → 33 of 74 on
  LoCoMo; English 38). On haiku: open-domain judgement questions 17 → 26 of 42, LoCoMo in Spanish 50.0 → 67.5,
  Spanish adversarial 10 → 9 of 10 (an honest decline judged wrong); every other English prompt byte-identical.
  `--questions benchmarks/public/fixtures/locomo-es.json` runs the Spanish set. Pick up: the coordinator's `--compare`
  on the owner's two sets with haiku. Detail: `docs/research/2026-10-17-memory-benchmarks.md`.
- **2026-10-20 — the owner's answer eval runs each question several times and judges a change on majorities (G148;
  branch `feat/eval-repeats`).** Four runs of the owner's 60 questions on near-identical code scored 46, 44, 42, 42 with
  13 questions flipping, so one run cannot judge an Ask change (#365 read −2; its revert did not restore the number).
  `benchmarks/answer_eval.py --repeats N` (default 3) answers and judges every question N times into one `--out`,
  resumable per (question, run), failed pairs re-asked; the summary gives each measure's mean and min–max across runs,
  overall and per tag, and always right / always wrong / flips (ids only). `--compare A.jsonl B.jsonl` (no calls) is
  the accept rule: B differs only when the exact sign test on questions whose majority verdict changed gives p < 0.05,
  Δ mean correct exceeds the wider min–max of either file, **and** both move the same way; a file is never resumed
  under other run settings, and `--fresh` starts it over. `claude -p` has no temperature/top-p/seed; the model
  the plan reported, the CLI version and `--effort` (opt-in pin; drops an inherited `CLAUDE_CODE_EFFORT_LEVEL`) are
  recorded and compare flags any mismatch. Tests: `test_answer_eval_repeats.py`, `test_public_benchmark.py`. Pick up:
  the coordinator re-runs the owner's eval with `--repeats 3` on dev as the baseline file every Ask change compares to.
- **2026-10-19 — plan-first engines; the inbox stops asking what a web search can answer (rulings 4c, 27b, 31; branch
  `feat/plan-first-inbox`).** Scheduled runs use the plan unless the person turned it off; Auto (the new default) never
  falls to a metered key; the web lookup runs on every plan run and the backlog gets a one-off sweep
  (`POST /inbox/web-check`); Cicada's own settings are never asked (`own_settings`). Tests: `test_plan_first_inbox.py`,
  `test_engine_select.py`, `test_server_readers.py`. Pick up: the coordinator runs the sweep's dry run on the owner's
  bank (`api/.venv/bin/python -m api.scripts.web_check_dry_run --bank <path> --census`, then `--limit 20`), reports the
  counts, then `POST /inbox/web-check?dryRun=false` on the running backend; checks the owner's own engine choice still
  says what he meant (an explicit OpenRouter pick stays OpenRouter).
- **2026-10-19 — Cicada as a Claude Code plugin (owner 2026-10-19; G49's plugin half, G105, G149; branch
  `feat/claude-code-plugin`).** Rule recorded in CLAUDE.md: the plugin is the canonical Claude Code door, `install.sh`
  the canonical machine install. The repo is its own marketplace (`.claude-plugin/marketplace.json`, plugin
  `./plugins/cicada`, id `cicada@cicada`): the MCP server, the `cicada` skill (a byte copy of `SKILL.md`), and the
  Stop/PreCompact/SessionEnd capture and SessionStart/UserPromptSubmit recall hooks, all through two POSIX scripts that
  exec the app's `~/.cicada/bin` launchers or a checkout named in the plugin's `cicada_repo` setting. Only when the
  plugin is enabled, installed and able to run a Cicada does `install.sh` stop registering Claude Code's hooks and MCP
  entry and remove its older ones (an enabled plugin that would run nothing keeps them, with a warning; a recall-off
  choice is carried into the plugin's setting); `make doctor` and
  `GET /agents/wiring` (`capabilities.via = "plugin"`) say which door is active. Detail: `mcp.md`, "The Claude Code
  plugin". Tests: `test_claude_code_plugin.py`. Pick up: review and merge; the owner installs it with `/plugin
  marketplace add ~/code/cicada` (dev) or `rorosaga/cicada` after the next release, sets `cicada_repo` if he runs a
  source build, then re-runs `./install.sh` once.
- **2026-10-19 — sign-in for the remote connector, and real-time capture through it (ruling 32, G135, G105; branch
  `feat/remote-oauth`).** `api/remote/oauth.py`: an OAuth 2.1 authorization server on the G135 listener (DCR + CIMD,
  S256 only, consent only in the app, single-use 120 s codes, hour-long access and rotating refresh tokens mapped to
  connector rows, RFC 9207 `iss`, RFC 7009 revocation, rate limits, everything hashed at rest); the 401 now carries
  `resource_metadata`. `cicada_capture_turns` (`record`, remote only) relays each turn through `turn_capture`'s writer
  as a `relay` episode with `evidence_kind: assistant`; `episode_staging` upgrades it in place when the app's export
  arrives. App: *Waiting for your yes* on From anywhere. What the person runs: `docs/connect-remote-apps.md`. Tests:
  `test_remote_oauth.py`, `test_relay_capture.py`, `RemoteConnectorTests`. Pick up: the owner runs a funnel on 8765 and
  adds the connector in claude.ai (web, then phone) and ChatGPT — unverified against the live apps until then.
- **2026-10-18 — Ask over watch-history ranges (ruling 30 follow-up, G71, G94, G118; branch `feat/history-ask`).**
  `watch_history.asked_span` + `summarize`: this/last year, a named year, since/between, the last N days, ever, "the
  most", first/last watch of a named channel — counted from the watched days with no model into one bounded table.
  Only a question with a watch verb, a platform or a channel the record holds reads it (never a bare "video"/"channel").
  The WATCH HISTORY block is headed as computed now and current only through its last watched day; synthesis rule 10
  keeps an earlier note about the system's own state from being repeated as current, never the person's later words. Citations name at most 5 grounding episodes plus `source_episodes_more`.
  `test_sync_watch.py`'s flake was the tests' timing, not the watcher: FSEvents reports the setup's own writes up to
  ~2 s late, and any report seconds late under contention; the tests now wait for an uncounted marker (events arrive in
  order) and drive the ticker's clock instead of sleeping. 5 runs in a row and 15 runs five-at-once green. Tests: `test_ask_watch_ranges.py`. Pick up: review and merge.
- **2026-10-20 — broad public benchmark on the production setup (G148; branch `bench/broad-2026-10-20`).** All 10
  LoCoMo conversations (382 Qs, Sleep `haiku`, EmbeddingGemma 2, answers/judge `sonnet` on the plan): `cicada_ask` J
  74.9 (single-hop 91, temporal 90, multi-hop 65, open-domain 49); full-context control 88.9 vs Ask 77.8 on the same five
  conversations. LongMemEval_S, 100 Qs without Sleep (search leg only), 3 repeats: 66.7 (66–67); multi-session 12.
  Honest: 73 % of misses name the gap, ≈ 2–3.5 % contradict, 1 of 14 abstentions answered. Misses track whether the
  answer turn reached the prompt (J 84 vs 44). 2,349 plan calls. Harness: `--sleep-schedule none`, `--gate`, prompt /
  context-ms / answer-turn fields. Details: `docs/research/2026-10-17-memory-benchmarks.md`, "Broad sample 2026-10-20".
- **2026-10-18 — watch history and export saves are indexed, not consolidated (ruling 30, G71, G94; branch
  `feat/history-index`, not merged).** `history_index` (the one predicate, the dry-run count, the retirement),
  `watch_history.rollup` (a month's summary, no model), `watch_history.lookup` (Ask's read of the record),
  `watch_history.channel_line` (a channel page's derived line), `sleep_cycle._index_without_model_safely` (before the
  freeze) and `_embed_indexed_episodes_safely` (the tail's vector sync). Tests: `test_history_index.py`. Pick up: the
  coordinator runs `api/.venv/bin/python -m api.scripts.history_index_dry_run --bank <path>` on the owner's bank (counts
  only), then the next Sleep run retires the queued days and saves; the first vector sync of ~5.7k episodes runs in
  that run's tail.
- **2026-10-17 — are the answers good? Public benchmarks through Cicada on the plan, and the owner's own eval (G148; branch `feat/memory-bench`).** Survey and recommendation: `docs/research/2026-10-17-memory-benchmarks.md` (LoCoMo with Mem0's J judge first, LongMemEval by type second). `python -m benchmarks.public.run prepare|run|report` runs LoCoMo/LongMemEval end to end (stager → drain → `cicada_ask` → published judge, full-context control, resumable, throwaway marked banks, `claude -p` only). `python -m benchmarks.answer_eval --bank … --questions benchmarks/answer_eval.local.yaml` grades Ask on the owner's bank against facts he writes. First slices: LoCoMo Ask J 52.5 vs full-context 95.0 (40 Qs); LongMemEval oracle 70 vs 85 (20 Qs) — honest gaps, lost detail. Tests: `test_public_benchmark.py`. Pick up: review and merge; the owner writes `benchmarks/answer_eval.local.yaml` and runs it; then the evidence-span Ask experiment on the same checkpointed banks.
- **2026-10-17 — small backend fixes and the LinkedIn photo decision (branch `fix/api-small`).** (1) The closed type
  set: a plain-JSON engine is held only by the prompt's type list, and nothing between extraction and the create branch
  checked the type, so a model's `organization`/`product`/`program` reached pages (3 on the owner's bank).
  `entity_types.producible` now maps it at extraction and again where a page is born (Sleep create branch, inbox
  answer); the person repairs an older bank with `python -m api.scripts.repair_entity_types --bank <path>` (dry run;
  `--list`, `--as <id>=<type>`, `--apply`). (2) `install_predicate_map` reads the runtime map through
  `_read_runtime_map`, the one reader. (3) Parked defects re-checked, all already fixed on dev with tests: media save
  dates (G99d `saved_at`/`content_saved_at`), same-title media pages (`_media_entity_id` URL-hash suffix), and the
  `<name>.com` logo guess (removed in G61 S3-b; `GUESSABLE_TYPES` is now only "types whose own site draws a mark").
  (4) The LinkedIn photo amendment below. Tests: `test_entity_types.py`, `test_predicates_map_cache.py`,
  `test_linkedin_people.py`.
- **2026-10-17 — Sleep tends the inbox, part 3: passing names and label conflicts (ruling 29; branch
  `feat/inbox-sleep-3`, not merged).** `inbox_tend.passing_rule` (`in_passing`: a page-less name said once in passing,
  or a code identifier, closes through the person's own dismiss; never tied to the person's life — relation words,
  first-person lines about people/places/companies, the owner's page, Messages) and `newest_words` / `label_lines`
  (a label-only conflict settled by the person's newest plain statement of one side, located in their own turn,
  dated that day; the conflict judge reads those lines when it is not mechanical). The lexical index is read fresh
  inline (`ensure_fresh(wait=True, max_age_s=0)`) so a just-committed conversation counts. Synthetic backlog (27
  passing names, 15 that must stay, 10 label conflicts): before 0 settled / 52 asked; after 33 settled / 19 asked
  (27 `in_passing`, 6 `newest_words`; stays: 8 a person in the person's own words, 4 named again, 3 Messages, 4 label
  conflicts for the judge). Review fixes (B1, B2): a person said in the person's own turn never closes; company/place
  checks read the turn and its neighbours; the mechanical label path needs the subject in the stating sentence and no
  negation/modal/avoidance on the raw text. Re-review: a relation counts only when a possessive ties it to someone,
  links and metadata lines are never words, a saved item's title/link/byline is never the person's own words, and the
  mechanical label path needs a plain placement right before the label (allowlist; the blocklist stays a second
  guard). Tests: `test_inbox_tend.py` (part 3 block). Pick up: the owner's `inbox_tidy_dry_run --judge`.
- **2026-10-17 — Sleep tends the inbox, part 2 (ruling 29; branch `feat/inbox-sleep-2`, not merged).** What the
  first pass could not reach (owner's judged dry run: 55 conflicts never reached the judge, 69 clarifications never
  tried): label-only conflicts judged through the claims their labels are tied to (`label_matches`, folded words,
  never fuzzy); a page-bound question whose name resolves to no file retires, an unreadable page stays
  (`ask:unreadable_page`); **move 3 — answered already, anywhere in the record** for clarifications, follow-ups and
  conflicts (`said_on_record`, 4 per drain in Sleep, every one in the tidy with `judge=true`); follow-ups settle
  through `progress` as Sleep's, dated the day the person said it. Tests: `test_inbox_tend.py` (part 2 block).
  Pick up: the owner's `inbox_tidy_dry_run --judge` on his bank; if `ask:unreadable_page` shows up in conflicts,
  that is where the 5 "page gone" ones were (a synthetic bank could not reproduce a missing page that dev's
  `_subject_gone` did not already retire).
- **2026-10-17 — Sleep tends the inbox (ruling 29, G21, G113; branch `feat/inbox-sleep`, merged #332).** `inbox_tend`
  (the policy table, the answered-in-conversation read, the duplicate judge, the one writer and its undo), `inbox_actor`
  (who answered: the person's resolvers commit as Sleep's while it is set), `sleep_cycle._tend_inbox_safely` after each
  batch's commit, `POST/GET /inbox/tidy` (dry run by default; counts only) and `api/scripts/inbox_tidy_dry_run.py`, the
  "Settled by Sleep" group beside "Settled by a check" (same list and undo routes, `group: sleep`), `inbox_settled` on
  the Sleep status, `sleepSettles` in the feedback ledger. Tests: `test_inbox_tend.py`, `SettledChecksTests`. Pick up:
  review; run the dry run on the owner's bank (without, then with `--judge`), read the counts per kind and decision,
  then `POST /inbox/tidy?dryRun=false&judge=true` once and read "Settled by Sleep".
- **2026-10-16 — server and readers: the owner's decisions after headless QA and the hunts (G181, ruling 4b; branch
  `feat/server-readers`, not merged).** Ruling 4b (above): scheduled runs may use the person's plan — Claude or
  ChatGPT — behind an off-by-default switch (Settings → Sleep, `cicada sleep schedule --use-plan`), and
  `cicada engine connect claude-plan|chatgpt-plan` signs a plan in on a server through its own CLI. A schedule with no
  engine it may use warns (schedule, `engine list`, `ask`), plan first. `/healthz` without a token says only status,
  version and bank ids. A client install makes no memory folder. Bookmarks keep what was synced per memory and catch up
  on a bank switch (never the demo); the app's outbox flushes lane by lane, so another memory's refused post never
  blocks the active one's. From the backend hunt: raw watch instants per day (merge order never matters), agent writes
  commit someone else's uncommitted edit apart, long path ids are 404, the session and Messages-photo bodies are bounded
  before parsing, one stuck spool session never blocks turns, Watch later duplicates save `url_index`, a timed-out tool
  write says it may have written; from headless QA: duplicate device names warn, the doctor hint names `doctor.sh`
  where there is no `make`, `sleep status` names the running stage once. Tests: `test_server_readers.py`,
  `test_headless_server.py`, `ServerReadersTests.swift`. Pick up: review and merge; on the home server run
  `cicada engine connect claude-plan`, `cicada sleep engine --mode agent`, `cicada sleep schedule --use-plan on`.
- **2026-10-16 — people from LinkedIn connections: the export enriches who is already in memory, and a skill for the
  rest (G154's pattern, G71, G166; branch `feat/linkedin-people`, not merged).** Owner: "extracting people profiles from
  my LinkedIn connections (maybe could be a skill) would be nice". `linkedin_people.py` reads `Connections.csv` (or the
  export zip; notes preamble, credentials after a comma, the email column never read) behind
  `POST /sources/linkedin-connections/preview|import` (demo 409, admitted, one `user` commit); exactly one existing
  `person` page per connection — never a new page — gains the profile link as a source and dated `external:linkedin`
  `works-at`/`role`/`connected-on` claims, newest wins; removal respected; re-import a no-op. The directory waits at
  `$CICADA_HOME/people/<bank>/` and Sleep's tail (`_rematch_linkedin_safely`, own `cicada` commit) matches later pages.
  Skill `skills/linkedin-people` (own bundle) + stdio-only `cicada_record_profile` (the one listed link, reading on,
  ≤ 10/day, episode with `page` spans). App: the LinkedIn tile's **Connections** (`LinkedInConnectionsPanel`).
  Tests: `test_linkedin_people.py`, `LinkedInConnectionsTests`. Pick up: review and merge; the owner drops his
  Connections.csv in the tile, reads the preview counts, and asks an agent "what does <a known person> do now?".
  **Amendment (owner, 2026-10-17) — the photo:** a person page matched from the connections may use that profile link
  for its photo right away, without the person taking the source — "If it's because I'm connected, unless the agent
  says 'Oh I'm not sure,' then we don't." The link records how it matched (`match`): the page's own name or a link the
  person or an identified agent already listed as their account is confident and drives the photo rung at once (the proxy gate's rules unchanged,
  off by default); an alias-only match is not sure and waits for the person to take it; an ambiguous one writes
  nothing, as before (`linkedin_people.CONFIDENT_MATCHES`, `person_photo.is_own_account`).
- **2026-10-16 — Messages follow-ups: a chat's shared photo is its page's picture, and a mark always reaches Sleep
  (G179; branch `fix/messages-followups`, not merged).** The app reads each ticked chat's shared Messages photo (at most
  hourly, from a copy) and posts changes to `PUT /sources/messages/photos` (409 unticked or demo, 422 bad bytes);
  `messages_photos` keeps them at `$CICADA_HOME/pictures/<bank>/messages/` by conversation, never in a bank or git, and
  links each to its page at read time through the correspondent record; untick deletes it. New rung 2a on both
  resolvers (choice → Contacts → shared Messages photo → profile/logo → monogram), `person` and `tool` pages; it rides
  the `photos` sync component. `messages_source._stage` records the `correspondent`/title on a sitting the stager
  skipped (frontmatter only via `episode_staging.reattribute`, no re-queue of a read sitting). Tests:
  `test_messages_photos.py`, the reproduction in `test_messages_source.py`, Swift watcher and resolver twins. Pick up:
  merge; the owner ticks the agent's chat and checks its page shows the photo.
- **2026-10-16 — on a plan, a run says how much of the plan it used, not dollars (ruling 12's two homes; branch
  `feat/plan-usage-share`, not merged).** Owner: "For Claude plans could you see how much usage was used from the plan
  instead of money?" The backend derives `planShare` per window at read (`cycle_usage.plan_share`): measured when the
  window's reading moved, "under 1%" when it did not (never 0 %), estimated from the run's list-price size against the
  rate earlier cycles moved that window (≥ 2 points each, ≥ 2 cycles, 35 days machine-wide), always with its basis; no
  new ledger field. The app leads Past reads' rows, Last cycle, an opened run and the engine menu's last line with it;
  the dollar figure becomes "would have cost about $X on an API key" (a secondary line or the help). Metered runs keep
  dollars. Tests: `test_plan_share.py`, `PlanShareTextTests`. Pick up: review; the owner's next plan run should read
  "under 1% of your weekly limit · reading unchanged" (or an estimate once two earlier runs moved the window). Not done: Past
  nights' folded run row (no whole-run usage on the history wire; its opened detail shows the share).
- **2026-10-16 — install anywhere: one curl line on Linux, a Homebrew tap in this repo (G181, G76; branch
  `feat/install-anywhere`, not merged).** Owner: "how I can install it with a `curl` command on a Linux machine … can I
  use Brew for that? If not make it so". `scripts/install-server.sh` (curl | bash: prerequisites named together, the
  newest `vX.Y.Z` tag or `CICADA_REF`, `~/.local/share/cicada`, then the checkout's own `install.sh --cli`; re-run is a
  no-op, a new ref restarts the unit, `--uninstall` keeps the memory). `Formula/cicada.rb` (`brew tap rorosaga/cicada
  https://github.com/rorosaga/cicada`; backend + CLI + MCP in a venv on `python@3.12`; `cicada-setup` = `install.sh`
  on the opt path; no `service do`, no cask until notarization). Both build the venv with `scripts/sync-server-env.sh`
  (the lock minus sentence-transformers' subtree: no torch/CUDA; 338 MB on Linux arm64). The formula's tag is a
  version stamp (`check_version.py`, `release.sh bump`). Proven in Docker: `scripts/dev/test-install-linux.sh`
  (ubuntu 24.04 + fedora 41, real systemd) and `scripts/dev/test-install-brew.sh` (Linuxbrew: style, audit --new
  --strict, install, test, setup, upgrade, uninstall). Live from the next release (main has neither file); testers use
  the `dev` URLs in `headless.md`. Pick up: review; after the release, run the curl line on a real server; the website's
  `install.sh` should hand Linux to `install-server.sh` (RELEASING.md).
- **2026-10-16 — headless server, phase 3: the Mac app as a server's client, and Settings → Devices (G181, branch
  `feat/headless-app`, not merged).** Settings → General → *Where your memory lives* (on Settings → Devices since the settings audit, 2026-10-22): This Mac or a server (address +
  device token, checked before anything is written; `$CICADA_HOME/api_base` + `device_token`, used from the next
  launch, and the hooks/MCP/CLI on the Mac follow the same file). On a server the app starts no backend, keeps its
  caches and reader cursors per connection, queues reader posts in `$CICADA_HOME/spool/app` and flushes them when the
  event stream reconnects, and refuses the demo. Settings → Devices shows where the memory lives (reachable, as of
  when), the person's devices (added, last seen; add/revoke on This Mac). New episodes a device posts record `device`
  (`device_context`), shown as "from <device>" on Saved rows, the Reader and the entity card's conversations. Tests:
  `test_headless_app.py`, `HeadlessAppTests` (incl. two real loopback listeners). Pick up: review; the owner tries
  A server against a test server over his overlay.
- **2026-10-16 — headless server, phase 2: every client can talk to a backend on another machine (G181, branch
  `feat/headless-clients`, not merged; ruling 28).** `CICADA_API_BASE` (+ a device token) makes the hooks, the stdio
  MCP server and the CLI clients of a server: the Stop hook reads the session locally and posts turns to
  `/capture/session` (spooled under `$CICADA_HOME/spool/capture` while the server is away), every MCP tool runs on the
  server through `POST /tools/call` (the same bodies), the CLI pins the server's bank by name and id. Per-device tokens
  (`cicada device add|list|revoke`, `/devices`, master only); bank ids in `banks.yaml` (`/healthz` `bankIds`,
  `X-Cicada-Bank-Id`). Proven with two real backends on two loopback ports (`test_headless_two_machines.py`). Unset,
  nothing changes. Pick up: phase 3, the app's server setting (Swift).
- **2026-10-16 — YouTube Watch later and watch history (G71 follow-up, G94, G166; branch `feat/youtube-sync`, not
  merged).** Owner: "my watch later videos from youtube and maybe also sync history" (Takeout once plus Chrome's history
  live), then "the agent being able to go to youtube using the browser … like for youtube watch later/history". Three
  doors, one record: Watch later is a save (`url_index`, one identity across Takeout, bookmarks and the agent); history
  is one episode per platform per day (`watch_history`), never Saved. Built: Takeout's `watch-history.html` read as
  history (it was parsed as bookmarks before), **Include watch history** on the drop and the YouTube tile, the app's
  Chrome History reader (a copy, YouTube video pages only, its own switch under Chrome), `POST
  /sources/watch-history/sync`, and `cicada_record_youtube_list` with Reading the web's two YouTube list switches (the
  reading queue offers a due list; `needs_login` pauses a week). Pick up: review; the owner turns the Chrome switch on
  and checks a day's episode; a real Takeout of a non-English account is not recognised by name yet.
- **2026-10-16 — a web lookup settles questions about public things (ruling 27, G61; branch `feat/web-settles`, not
  merged).** `web_settle` (the filter, the pinned query, the one settle/undo writer, `inbox/settled/`), `web_lookup` (the
  Sleep-tail step: plan search on a run the person started, a metered provider's search at its price, the pinned-query
  check, 8 a run, a 30-day memo outside the bank), `cicada_record_check(outcome="settles")` for the person's own agent
  (repo-state questions from a commit, trusted local agents only), `GET /inbox/settled` + `POST
  /inbox/settled/{id}/undo`, the `web_check` ledger kind, and the Inbox's "Settled by a check" list with Undo and Track
  this source. The answer is a citation on its claim only, never a tracked source. Tests: `test_web_settle.py`,
  `SettledChecksTests`. Pick up: review; then a person-started run on a copy of the real bank, reading the settled list
  and the `web_check` counts (ids only) before merging.
- **2026-10-16 — the web lookup reads local context (ruling 27a, G61; branch `fix/web-lookup-context`, not merged).** The
  first real run settled 0 of 8 (all unsure: an ambiguous name, a wrong category word). The prompt now carries
  `web_settle.local_context` (≤ 600 characters: Cicada's description, up to two mention lines, scrubbed, no one's name,
  no path) to pick the right result; the query is the name plus at most one category word from the description (none on
  a type question); clarifications first, conflicts with a mention line next. `api/scripts/web_check_dry_run.py --bank
  <path> --limit N [--include-recent]` runs the real engine and prints counts only, writing nothing. Pick up: the
  coordinator runs the dry run on the owner's bank (with `--include-recent` to re-measure the first eight) before
  merging.
- **2026-10-16 — the Sleep page redesigned, the Feed folded into it (branch `feat/sleep-redesign`, not merged; owner
  approval 2026-10-16, ⌘ map A).** The "Sleep Cycle" title is gone (an eyebrow: "Sleep · 42 waiting · last read 2 h
  ago"); the room left its card and draws at a whole 5/4/3 pt per cell by the column's width; Details became the tabs
  Waiting · Saved · Videos · Past reads, sticky once the room scrolls away. The Feed page retired: Saved and Videos are
  its list, View menu (sort, kind), detail column, watch run and ⌘N; Connected lives on Sources, export waits head Saved.
  Skills took the Feed's ⌘4 (nothing else moved), with a one-time hint the first time ⌘4 lands there. Ruling 12's
  surface is renamed "the Sleep page's Past reads run detail". DESIGN_RULES §9 carries the dated ruling. Pick up:
  review on the owner's Mac (the worker never launches the app); phase 2 (Clusters into Graph, then ⌘ map B) is not
  part of this branch.

- **2026-10-16 — the key defaults and the price table (G122, branch `fix/byok-default`, not merged).**
  `test_byok_providers` failed on dev because `import litellm` fetched its price table from GitHub at every start
  (ungated), and upstream had dropped the OpenRouter default's alias (today it lists no `openrouter/` row at all). Now
  `api/__init__.py` pins the table to the one litellm ships (`LITELLM_LOCAL_MODEL_COST_MAP`, a control key for the CLI and
  the settings file); defaults moved to listed, priced models with structured output — OpenRouter
  `openrouter/openai/gpt-oss-120b`, xAI `xai/grok-4-1-fast-reasoning-latest`; a saved pref keeping an old id still runs,
  with its cost unknown. The Usage aggregates now say `null`, never `0.0`, for a bucket no call priced.
- **2026-10-15 — Messages conversations, Instinct first, on branch `feat/imessage-instinct` (not merged; G179, G188's
  minimal slice).** Settings → Integrations → Messages: tick a one-to-one conversation, mark who it is with (detector
  registry, Instinct first; the person's mark wins). The app reads only ticked rows past a ROWID cursor; the backend
  decodes `attributedBody`, stages one episode per 3 h sitting, keeps a texted agent's words as `assistant:` turns and
  their claims as `external:<name>`. Bubbles on the Sleep page's What's waiting and Home. Pick up: the coordinator
  ticks the real conversation on the owner's Mac and runs consolidation.
- **2026-10-16 — a texted agent gets its own page (G179, branch `fix/agent-identity`, not merged).** The real run put
  the agent on an archived same-name `concept` page (Stage 2 resolved it by name). Now the episode's decided
  `correspondent` is marked in Stage 1, typed (`tool` agent / `person`) and resolved to its own page in Stage 2
  (`correspondents`; a new page is `<id>-agent` / `<id>-person`), its own claims pinned there; below the unchanged
  promotion bar it is held under that key in the pending store, never on the same-name page. Repair:
  `api.scripts.repair_correspondent_pages --bank <path>` (dry run counts; `--apply` one `cicada` commit) takes a
  conversation's part off a page that absorbed it, moving nothing else. Pick up: review, then the coordinator runs the repair on
  the real bank.
- **2026-10-14 (night) — tracked sources re-checked, on branch `feat/source-refresh` (not merged; ruling 26).** A
  trusted source is re-checked monthly (or on the person's ask) and what it says now is a new dated fact; the newest
  evidence wins, even over the person's words; same-day/undated asks once; two failed visits a week apart mark it dead.
  Public pages: the Sleep tail (`source_refresh.run_tail`, connector gate). Login-walled: only the person's agent
  (`cicada_refresh_claim` / `cicada_record_refresh`, stdio). `GET /sources/due`, `POST /entities/{id}/sources/refresh`,
  the SessionStart line. Not built: the app's rendering of `updates` / due state (the API serves them).
- **2026-10-14 (late evening) — exploring, slice 2, merged as #286.** Depth follows the
  person's reason (G191 ids, their words, their conversations) through a deterministic plan (`explore_plan`; no model),
  a site map per explored site in the bank (`captures/_sites/<site>.md`, append-only, `cicada_site_map`,
  `GET /explore/sites`), and auto-Looks for a design reason (G166, G196). The catalog pins `site-explore` to the dev
  squash commit of #286 (`2a9b5990`; `scripts/verify-skills.sh` passes), as #283 did.
- **2026-10-14 (evening) — exploring saved sites, slice 1, on branch `feat/explore-sites` (not merged).** The owner
  ruled D1–D6 (ruling 25). Built: the explore queue, dated captures with thumbnails in the bank and full images in
  `~/.cicada/captures/`, four stdio MCP tools (`cicada_explore_claim`, `cicada_record_capture`, `cicada_explore_queue`,
  `cicada_explore_start`), `/explore/*` routes, the pinned `skills/site-explore` capture script, the Sources sheet and run
  card, the signed-in switch and Never explore in Settings. The catalog pins `site-explore` to its dev squash commit
  (#283; `scripts/verify-skills.sh` passes). Slices 2 and 3 are open on G166.
- **2026-10-14 (acting-owner session, afternoon) — pick up here.** Merged to dev after the overnight entry below:
  - **#273:** docs for the overnight state.
  - **#274, every agent:** a paste-able setup prompt for Cursor and for "another agent" (G76); Cursor and Gemini CLI conversations are captured through their prompt/reply hooks, built from the documented payloads and not yet seen in the real apps (G197, with a capture matrix in `capture-and-sleep.md`); the owner's ruling on file search (G195).
  - **This PR, agents as contributors:**
    - trusted agents edit a page's text and aliases directly, with blame from git (G198);
    - an untrusted agent's edit becomes a one-tap inbox proposal;
    - inbox questions come up only when the conversation is about them, and an answer the person already gave is relayed with attribution (G115);
    - `cicada_ask` reads a hub page's aliases, summary and linked people.
  - **Found:** an MCP server process started before an update keeps running old code. One refused an owner-page write after the claims-ledger change; it refused safely, without corrupting the page. Opening a new session fixes it. A server that notices a code change and restarts is not built yet.
  - **Owner, open:**
    - whether to turn on the SessionStart/UserPromptSubmit recall hooks in Claude Code and Codex (only the Stop capture hook is installed);
    - which agents go on the page-edit trust list;
    - Cursor capture is the owner's click (Agents → Cursor).
- **2026-10-14 (acting-owner session, overnight) — previous state.** Merged to dev, in three themed PRs per the owner's "fewer, bigger contributions":
  - **#270 memory quality:** a very large page's older claims go to a claims ledger beside it; unnamed people get relation titles and a "What's the name of your partner?" question; `works-at` holds several places at once and ends only on evidence; a project name typed in another case finds its page.
  - **#271:** "Where this comes from" on every page (G61), and the Looks board (G196).
  - **#272:** merges and renames keep every edge whole (a placeholder merge on the real bank had stripped 14,298 claim-backed edges; reverted the same night, nothing lost); hub Related at most 60 lines by meaning; the owner card opens in ~0.1 s; session titles in the person's words.
  - **Owner bank:** the hub split, the works-at reopen (4 places), the placeholder repair (1 merged, 5 asked), an article for the owner page and the episode retitle are all applied, each as its own revertible bank commit.
  - **Tested end to end:** Claude Desktop connects and reads, writes and consolidates, but does not capture its chats (G197). A fresh Claude Code session resumed the project unprompted. The Cursor install dialog awaits the owner's click.
  - **Owner decisions:** G195 (5 questions), G196 (spec questions), G159/G154 Gravatar for contacts.
  - **No Codex** from 2026-10-14: the subscription has ended.
- **2026-10-13 (acting-owner session) — previous state.** Merged to dev: #261 links, videos and PDFs get their own picture (G159 rung 5, PDF page 1 in the backend); #262 platform data exports bring in what the person saved (G71: Instagram, TikTok, YouTube Takeout, LinkedIn, X archive, Reddit; one reader, three doors); #263 pages as articles and #264 one bad answer never aborts the rebuild (G194); #265 a person's photo from their public profile (G159; the ToS rail's one dated exception); #266 the CLI does what the app does (G180, ruling 21a); #267 the backend reads `api/.env` on purpose and `/status` shows what is in effect (it already did, through litellm's import-time dotenv walk — a `python -c` probe cannot see that); #268 age counts from when it was said (G170 amended). Owner bank: 1,050 pages rebuilt as articles (record lossless), then the age recompute — 570 active, 821 faded, 2,241 archived, one question. Rulings: 24 below. Open: Contacts email hash for Gravatar (DECIDE, G154/G159); the X and Pinterest connectors store the post's own text as the person's note (bug, parked); `test_byok_providers` fails on dev (a default model id unknown to the installed litellm); the web-readiness follow-ups listed on G180; the owner page has no article (over the writer's input budget); 222 aliases equal to another page's name; G118 1b; G148.
- **2026-10-09 (acting-owner session) — previous state.** Merged to dev: #249 a recorded alias brings its page to the Stage 2 judge (context, never a decision); #250 the Sleep page answers during a run (G163); #251/#252 skill pages carry their conversations, a skill needs two (G112, ruling 23); #253 EmbeddingGemma 2 is the search model where it runs, #255 its pin file ships; #254 the entity card opens on its wiki page (dated DESIGN_RULES ruling); #256 page quality (G194: promotion measured on the transcript, pending lines keep facts, only an equal fact folds); #257 long embeds run in a child process (coremltools' predict holds the GIL — capture POSTs timed out during a re-embed); #258 Stage 3's page calls overlap; #259 a fresh-process recall reads only what moved (2.15 s → 0.42 s, synthetic). The owner bank was re-embedded with EmbeddingGemma 2 (391 s) and repaired by `repair_page_quality --apply` (544 pages, lossless, checked on a clone first). Engine: Claude plan, Haiku 5.5 for extraction and disambiguation, `CICADA_AGENT_MAX_CONCURRENCY=10`, `CICADA_SLEEP_RESOLVE_CONCURRENCY=10`; summary synthesis on (ruling 23). Superseded 2026-10-13 by ruling 24's age rule: 222 aliases equal to another page's name (merge candidates); G118 1b; G148 Haiku-vs-Sonnet and real-bank embedding comparison.
- **2026-10-08 (acting-owner session) — pick up here.** Merged to dev since the 2026-10-07 entry: #223 docs, #224 engine-timeout pauses (G163/G171), #225/#229/#232/#234/#237 G110 slice 1b (index privacy, light pointer + on-demand context, 16k first message + reply head/tail + `State:` guidance, worktree/subfolder project identity, Cursor startup), #226/#239 dev auto-updater waits out Sleep, #227 no claims fence in any page-body prompt, #228 G169 self-references are the owner, #230 G194 dated writing + *last mentioned* header, #231/#235/#238 G180 CLI slice 1 (eight commands, Settings install, skill), #233 Claude-engine environment never becomes memory, #236 G118 section-provenance records. **Approved, waiting to merge after the clean run:** G118 slice 1b (app *Supporting passages*). **The owner's clean consolidation** is running on a fresh bank of his ChatGPT + Claude exports (1,519 conversations; ChatGPT plan · GPT Luna; batch 25; continue-after-reset off; user-started). The trial bank was stopped and is throwaway; the recovery/reopen work for its lost claims was dropped (owner: old banks are test runs). **Owner direction 2026-10-07:** less review process — one cross-vendor review per change, blockers only; priority is a working memory he can test. **Next:** when the run ends — a quick page-quality pass, merge G118 1b, the owner's live tests (real questions; G110 acceptance: a fresh Claude Code/Codex/Cursor session asked "what was the last thing we were working on?"), then the VERIFY rows. **Open owner decisions:** real-cost measurement vs the input-size proxy for the 16k first-message retention before a release; G118 1a-ii (💸 prompt change + pilot); G179 FDA.
- **2026-10-07 (later, acting-owner session).** Merged to dev since the handoff below: #213 write admission (G183/G177), #214 G98 fold dedup/migration, #215 a prose rewrite never drops a page's claims, #216 closed claims are history on every read path, #217 recovery of dropped claims as closed history (dry run first), #218 G191, #219 G110 rulings A/B/C, #220 rail corner variant A, #221 G192/G193, #222 G148 benchmark harness. In review or build: engine-timeout pauses (a timeout or an unnamed engine-wide failure pauses instead of ending the run or parking the queue; approved, gating), reopen mode for recovered claims (fail-closed admission, round 3), the contradiction-prompt claims fence (G148 follow-up), G180 CLI plan (owner rulings in ruling 21), G110 slice 1b cross-harness plan (owner rulings in ruling 22; revision 2), and a qmd research comparison (two independent reports). The G10 trial drain continues on `trial-2026-10-06` (batch 12 of 89 at writing); external backend restarts pause it and it is resumed at batch boundaries. Owner kept the G105 capture rule when offered tool-call capture; the idea is parked on G112 for research. New trial findings: the owner appears as both a generic `user` page and a named page (owner-entity resolution, G98-class); clean batches of 10 take ~5–10 min (~10 model calls per conversation), and each external backend restart loses the batch in progress (cause under investigation).
- **2026-10-07 handoff (acting-owner session).** Merged to dev: #198 backlog review + ruling 19, #199 G189(a), #200 G185, #201 G183(b,c), #202 G182 release-on-merge, #204 G183(a,e)/G21 guards, #205 installer UTF-8 hotfix, #206 0.3.1 bump, #208 Home scroll + rail corner, #209 G177/G183(d) bank pin, #210 G110 slice 1a, #211 G98 slug-fold core. Releases **v0.3.0** and **v0.3.1** are published from `main`; install acceptance passes on v0.3.1. Backend suite is fully green (G185 fixed). In review: write-admission lock (G183/G177), G98 fold dedup/migration, G148 system-bench runner (found and fixed a Stage-5 claim-loss bug — under opus review), cicada-website #18 (live download button).
- **G10 trial in progress** on a new named bank (`trial-2026-10-06`, ChatGPT plan, gpt-6-luna, user-started drain, batch 10, continue-after-reset off): 1,519 episodes imported via the app (ChatGPT 1,116 + Claude 345 + 5 project notes + 53 memories; count gaps = empty conversations). Findings so far (generic): onboarding has no import step and the import card offers only "read everything"; Claude memory titles show raw paths; the file picker imports a whole folder when nothing is selected; an `api/.env` model pin overrode the engine menu's model for one stage (owner's local config corrected; the mismatch is a product bug); imported episodes swept into Sleep's first commit (G183); the predicate-fold inbox flood (G98, core fixed).
- **Pending owner decisions:** G179 FDA; G110 slice 1b's remaining DECIDE items (after revision 2); reopen counts on a non-trial bank before any write there; GitHub settings for `main` (required Release PR check, PR-only).


- Reviewed merged `dev` at `02979949`; during the review it advanced to `3efba432` with the inbox count fix (#196). This was a code-path/scope audit of 186 original G addresses; subsequent requirements at `ba7a4957` add G188 and amend provider/source/benchmark/release priorities. No live-memory run or full-suite rerun is claimed. Preserve other staged/unstaged work in the shared checkout.
- Import/delta capture, Stop hooks, implicit recall, claims/provenance, Sleep drain, lexical/vector recall, remote MCP, onboarding and release/update infrastructure exist. Completion of the first public release and real-client acceptance are separate open tasks.
- GitHub release listing returned no releases on 2026-10-06. G182’s **built** status must not be read as **published**. Follow [RELEASING.md](../RELEASING.md) for the current mechanism; G182 now requests release-scoped automatic promotion/synchronization as an explicit owner amendment when implemented; implementation PRs target `dev`.
- The [October 5 audit status](audit-2026-10-05/STATUS.md) reports 6,016 backend passes, one G185 usage-join failure and one skip on `4264e297`; Swift 2,957 passes and graph 9/9. These are dated reported results, not checks rerun here. The earlier eight calendar failures are not the current baseline.
- Served-inbox counting code/tests merged during this review as #196 (`3efba432`). Read-side subject/defer filtering and visible-count parity are implemented. G98 retains upstream question-generation/entity-resolution cleanup; it does not ask for the count fix again.
- G169–G172 and G149 implementations are in current merged code. Historical “PR open/not merged” labels in their detailed reasoning are stale. Their live acceptance belongs in the first trial or a named subsequent check.
- No private bank/transcript was inspected; no consolidation, release, upload or skill installation was performed.

## Execution order

| Order | Outcome | Permanent work IDs | Completion condition |
|---|---|---|---|
| Today · urgent | Working GitHub release, main/website sync and every integration | G182/G76/G10; website G158 | Due 2026-10-06: real downloadable artifact, fresh install/update acceptance, released tag/version/manifest/main synchronized by an explicit release workflow, working website link. Test every catalog harness and supported desktop/web/mobile route after actual consolidation for grounded reads and attributed contributions; blocked/unsupported is explicit. Later add tested CLI/server install commands and harness access guides when G180/G181/G187 ship. [Requirements](../specs/2026-10-06-release-and-integration-acceptance.md). Applicable integrity checks remain release dependencies. |
| Today · quick | Painted Home banner off | G189 (a) | One `HomeBandLayout.showsBand = false` gate around `HomeHeroBand()`; existing Home/scene tests keep passing; dated DESIGN_RULES ruling and the app.md Home paragraph in the same PR; checked by eye in the running app, light and dark. |
| Next · owner 2026-10-26 | Sources, Traces and Projects as the owner asked, then a clean retest before testers | G218 own page and G61 quick add (built, `feat/traces-sources-projects`); G141's page hidden; G222 Projects redesign (another worker); G224 Inbox density (another worker); G223 any source by URL (Spotify, Letterboxd; G32); then G225 | In this order: the built three land; G222 and G224 land; G223's agent visit, under "Reading with the person's own agent"; then **G225 last, before anyone else gets a build** — one fresh-bank re-consolidation of the owner's exports on current `dev` and a full retest, with a written list of what is wrong. |
| 1 · P0 | Protect current truth and commits | G183/G177; G104; G21 if live dedup is used | Repair applicable page-lock, owned-path, author and bank-switch defects. Reproduce revised-source retention with synthetic episodes, then fix the demonstrated semantic gap before a full re-consolidation. Dedup must commit its own merges. App controls must use the writing window. |
| 2 · P0 | Reproduce the known regression | G185 | Diagnose and fix the reported usage-join assertion without weakening it. Release gate; consolidation gate only if it exposes drain correctness. |
| 3 · P1 | First useful memory, including actual source/video cases | G10, G169–G172; G61/G166, G22/G162 | Small fresh/delta ChatGPT/Claude export trial first. Ask ordinary dated/current questions, correct a claim and repeat in a fresh session. Then demonstrate permitted source lookup/recording and an actual watched-video → Sleep → grounded recall. Build the missing general source-check seam; separate watch success from processing/answer quality. |
| 3b · P1 | Automatic continuity when a session is full or the agent changes | G110/G48/G53/G75/G76/G149; Cursor G50; remote G135 | Fresh Claude Code/Codex session continues the active project before Sleep without a handoff prompt or recap. Then prove Claude Code → Cursor/Codex and permitted Grok/remote continuation. Recover goal, decisions, current changes, verified results, blockers and next step; detect stale workspace/ambiguous tasks, preserve lineage and disclose unavailable context. See [required behavior](../specs/2026-10-06-project-continuity.md). |
| 3c · P1 research | Efficient continuation-aware consolidation | G104 with G110/G118/G163 | Compare full-thread rereads with new turns plus bounded prior context, stable unit reuse and targeted reprocessing. Measure repeated input/calls/time and useful recall; preserve corrections, evidence and commit-safe checkpoints. Investigate capture-cap loss. [Research brief](../research/2026-10-06-incremental-consolidation.md). Existing revision correctness stays P0; optimization does not gate the small baseline trial. |
| 3d · P1 | Rebuild whole-system benchmarks from scratch | G148; G10/G104/G171/G183 | New isolated subscription-capable harness: intake → real five-stage Sleep/tail/owned commits/indexes → held-out answers, continued/revised sources, temporal changes, failure/resume and scale. Measure quality/integrity plus runtime, throughput, CPU/peak memory, calls/reported tokens and service latency. Synthetic cases then one LoCoMo conversation/30 questions; Luna pin for every generative stage. Legacy scores are not acceptance evidence. [Requirements](../specs/2026-10-06-system-benchmark-rebuild.md). Full harness does not gate a small hands-on trial. |
| 4 · P1 | Repair the failures that make answers untrustworthy | G98/G118/G147/G103; G93/G53/G113/G115/G141 as indicated | Canonical/retired question subjects, preserved keep feedback on merge, intelligible observer and evidence navigation. Trigger/rationale trace slices and cross-stream relevance follow observed trial failures. Do not rebuild already-implemented state/Ask/Reader components. |
| 4b · P1 | Selected iMessage conversations, optional Instinct recognition | G179; minimum G188 seam; G95/G134 attribution | App reads selected permitted bytes; backend parses scrubbed attributed drafts. Verify continuation/revision/deletion/date/source semantics through actual Sleep and useful answers. Optional separate Instinct detector supports uncertainty/user overrides and never broadens capture. [Requirements](../specs/2026-10-06-provider-and-ingestion-modularity.md). Other messenger exports follow later. |
| 5 · P2 | Shell agents use a lean governed surface | G180; G157 redirects | Packaged CLI, structured output/error/discovery contracts and portable usage skill; measure schema/task overhead. Keep scoped MCP for clients without a shell. |
| 6 · P2 | App-free server package | G181/G187/G135/G92; Cursor engine G50/G49/G122 | Supported Linux/macOS install/service/upgrade path with one primary bank writer and client/remote smoke checks. Evaluate Windows native versus WSL separately. An existing Python backend is not a supported headless package. **2026-10-15:** phase 1 (Linux install + systemd user unit, commits with no git identity) on `feat/headless-server`; the plan and the owner decisions for phase 2 are in G181 and `docs/research/2026-10-15-headless-server.md`. **2026-10-16:** the packages — one curl line on Linux (`scripts/install-server.sh`) and a Homebrew tap in this repo (`Formula/cicada.rb`), both proven end to end in Docker (`feat/install-anywhere`). |
| 7 · P2 | Modular providers and ingestion in frontend/backend | G50/G49/G122; G188/G190/G126/G161; Cursor G76/G110 | Registered capabilities/small adapters drive setup/status/engine controls and source intake. Add/remove a fixture provider/source without unrelated core/view changes; preserve unavailable saved selections/history. Verify Cursor client versus engine capabilities separately. iMessage uses a minimal source/detector seam earlier; broader migration follows. [Requirements](../specs/2026-10-06-provider-and-ingestion-modularity.md). |
| 8 · P2 | Start prompts and portable skills | G73/G118/G113, G138/G178, G112/G55; G186 after CLI | Save/find/adapt reusable objective briefs with candidate status, original/variant provenance, project inputs and outcome evidence; copy/export across harnesses without requiring Sleep or skill compilation. See [start prompts](../specs/2026-10-06-start-prompts.md). Then verify catalog/BYO install, ground existing skills and compile standalone bundles; demonstrate schema-aware SQL reuse with R2 governance. Generate AMR export separately; external AMR import remains research. |
| 8b · P2 | Home revamp | G189 (b); G110/G137/G125 | **2026-10-14:** owner picked "Graduate + Needs you first" (built on `feat/home-front-door`; retake Home's screenshots on the demo bank, light/dark, first-week/returning/empty). Still open: projects in flight and what changed since the last visit, from 2–3 direction-D mockups. Do not rebuild the Ask field or inbox counts. |
| 9 · P3 | Design identity and personal mascot | G70/G151, G127, G175/G176; G73 supplies creation templates | Start with own-repo/image tokens, cited structured design read/UI, then vision/video/style bundles. Add Cicada skin, copyable neutral creation prompt and validated sprite import/preview. Remaining app/Reader work follows the explicit ledger; profile G184 before energy changes. |
| 10 · P4 | Multi-server/device sync and selective contributors | G132/G1/G181, G16/G103/G116/G92 | Many clients of one writer first; backup separate from replication. Specify node/project scopes, contributor routing, evidence exposure, revocation and conflict verdicts before offline replication or multi-person writes. |
| Triggered only | Additional channels and model/browser research | Later/Research IDs; G167/G168 | Dedicated adapters are not implemented by generic ingestion. Work from a named use case/failure/trigger; keep declined parallel reading and relational-tier decisions out of the automatic build queue. |

**How to use this order:** a small trial does not wait for every P1 enhancement. Correctness fixes relevant to its writes come first; a full drain must wait on demonstrated revision/commit defects. G104’s incremental strategy is P1 research rather than a prerequisite performance rewrite; its P0 correctness slice remains separate. Alongside today’s explicit release deadline, automatic session/project continuity and source/video quality remain P1 because the owner wants useful conversations. Cursor’s provider adapter is an explicit P2 integration remainder under G50; its capture/startup behavior supports P1 G110. G182 is the owner’s explicit delivery priority for today, with applicable release checks. G148 whole-system benchmark replacement and selected iMessage/Instinct capture are P1; full harness completion and an embedding upgrade do not gate a small hands-on trial. Broader provider/source modularity and CLI/headless packaging are P2. The [187-ID review](BACKLOG_IMPLEMENTATION_REVIEW.md) spells out implementation versus missing slices. Older “built” labels apply only to the named slice; G1/G23 were restored from DONE.

## Client trial matrix — support must be demonstrated

| Client | Trial path | What to establish |
|---|---|---|
| Claude Code | Existing local MCP/Stop/recall hooks; CLI once built | Automatic capture, fresh-session retrieval, provenance, correction and reusable procedure. |
| Codex | Existing local MCP/Stop/recall hooks; CLI once built | Same behavior, with session/model attribution limits disclosed. |
| Cursor | Existing agent catalog/MCP setup; complete G50/G76 capture/recall and supported engine integration | Fresh-session and cross-agent project continuation without a handoff prompt; verify actual capture, model/session attribution and available engine functions. |
| Grok | Scoped G135 connector with selected project/task | Automatically recover permitted working context on a new conversation where supported; disclose missing workspace/source access. |
| ChatGPT Desktop | Check current supported remote-connector setup via G135 | Read/write/source scopes and continuity if supported; connection does not establish automatic capture. |
| Claude Desktop | Local MCP registration or supported remote connector | Recall and attributed contributions; no Stop-hook capture claim for this app. |
| Claude web (claude.ai) | Supported remote MCP route via G135 | Post-Sleep grounded recall and attributed contribution; source scopes and current account availability. |
| ChatGPT web | Supported remote connector via G135 | Same post-Sleep read/contribute check; distinguish connector availability from automatic capture. |
| OpenCode | Catalog setup prompt; verify current supported MCP/config path | Fresh-session grounded recall, attributed contribution and persistence; capture/continuity checked separately. |
| Hermes | Catalog setup prompt; verify current supported MCP/config path | Same read/contribute/persistence check; report actual supported setup and capture limits. |
| OpenClaw | Catalog setup prompt; verify current supported MCP/config path | Same read/contribute/persistence check, including source scopes and active-bank isolation. |
| Gemini CLI | Existing catalog/setup path | Same read/contribute/persistence check; verify attribution and automatic capture/recall support separately. |
| iPhone AI apps | Verify current connector availability per app/account | Test an authenticated remote connection only where supported; otherwise record unavailable plus export/manual capture fallback. |

For **every row**, use a fresh session after actual consolidation: recall and correctly use a synthetic memory, write a permitted attributed contribution, retrieve it from another fresh session/client, and verify its persistence/evidence/commit. Record read, contribution, source scope, capture and continuity separately. Enumerate each tested iPhone app rather than claiming one mobile check covers all apps. Record availability/date and PASS/FAIL/BLOCKED/UNSUPPORTED plus the exact supported setup, build/account/platform and generic evidence; registration or connection is not a pass. No personal question text or retrieved private facts belongs here. [Full protocol](../specs/2026-10-06-release-and-integration-acceptance.md).

## Embeddings: EmbeddingGemma 2 where it runs (owner 2026-10-09)

Markdown, evidence and git hold memory. Embeddings provide semantic recall and candidates for entity resolution/dedup; they are not the authoritative record. `search_service.py` fuses lexical, vector and claim results and can fall back when vectors fail. `entity_resolver.py` still reads/writes the pending entity index, so full consolidation is not established as an index-free mode.

**Ruling (owner 2026-10-09, after the spike: "cant we just run everything with embedding gemma 2?").** EmbeddingGemma 2 on the Neural Engine (`google/embeddinggemma-2:768`, Core ML, macOS 15+ on Apple silicon) is the embedder wherever it runs: Sleep's index builds, recall from MCP and the CLI, the release app. It is downloaded once on the person's request (Settings, `make embedding-model-gemma2`, `install.sh`), never bundled; the release keeps `intfloat/multilingual-e5-small` (384) bundled as the floor for macOS 14, a download not finished yet or a failed load, and search never errors. A bank recording one of Cicada's former defaults moves to it in a **background re-embed** that never runs during Sleep and never blocks recall (the old table answers until its replacement commits); a model the person chose or set explicitly is kept. This replaces "keep the present choice for the first trial": the evidence is the spike (parity ≥ 0.9998 with the reference model; cross-language EN↔ES page retrieval +0.11 MRR over e5 on a 3k-page set; a query 2.8 ms) and the build's own measurements (`docs/architecture/storage.md`, sqlite-vec). Revisit only if the owner's real-bank comparison (G148) shows meaning-based recall worse than e5's on literal or paraphrased questions. Check the active bank's actual selection, `reindex` state and index health through `GET /embeddings` at execution time; do not assume it from the build type. If meaning-based recall fails but lexical recall succeeds, record that failure for G148.

## Consolidation boundaries

Use a separate named real test bank or an explicitly chosen existing bank, with a recoverable committed baseline. New exports are imported normally; do not wipe the bank or mark every episode unprocessed to force a rerun. Inspect the import preview, preserve dates/speakers, then run a small batch with the selected engine. An API-funded run needs a budget; a user-started plan engine respects its plan limits and pause behavior. Scheduled plan use needs the person's switch (ruling 4b). Runbook details: [G10 trial](2026-10-06-first-memory-trial.md).

## Unstructured follow-ups retained from the old handoff

These are attached to permanent rows instead of becoming a second queue. Older disclosures require a current-code reproduction before implementation; do not re-open an audit fix from historical prose.

- **G106/G19:** confirm remaining client/backend ID sanitizer parity and wikilink navigation outside a WindowGroup.
- **G109:** graph physics phases/visual fit check; re-check historical WKWebView remount claims against the merged audit fixes.
- **G162 (model check 2026-10-22; ruling 34):** F1, F2, F4 and F5 are fixed (a per-claim lease token, the saved set read under the lock, a three-period lease cap); F3 is accepted and keeps its xfail-strict repros in `api/tests/test_video_queue_formal.py` until its trigger (a lease seen ending on an older record). The `--deep` minimums for `fixed-churn` and `deep-safety` are 0 until someone records them on the ruling-34 model. Any change to `video_queue.py`, `video_state.py`, the record or claim tools or how a caller gets its session id runs `.claude/skills/verify-video-queue/run.sh`.
- **G162:** `/live/<id>` normalization changes need URL-index migration; unprobed player providers stay unverified; do not assemble third-party widget HTML or bypass an origin restriction. **G11:** verify the disclosed duplicate direct-file preview/hero player.
- **G135/G177/G183:** current remote/local write races and fail-open commit probes; check scope isolation, timeout behavior and source permissions. **G61:** source entry identity, check-date/predicate invalidation and save-time fetch limits against the current common fetch guard.
- **G130/G137/G184:** zoom/sidebar clamp, pixel-size alignment and active-run animation energy. Nightcap/time-of-day absence are superseded by shipped G176 art. DS-3c card Esc and Settings folder popover seams remain current-code checks.
- **G146:** `lastReferenced` in graph shape/hash and Clusters age. **G161/G118:** source item’s saving episode for “Show in conversation.” **G118/G141:** recently learned claims with evidence spans from history, without claim text in commits.
- **G133:** reproduce garbled imported-paper titles with synthetic files. **G103:** humanize raw-predicate fallback. **G76:** distinguish capture enabled from recall connected. **G145/G173:** versioning untouched generated demo data, if the stale-demo trigger persists.
- **G7:** centrality premise remains unproved; no tracked measurement was found, so it is not archived as done.
- **G92/G19:** old bank-history size is historical, not permission to rewrite git history. No destructive cleanup is implied.

## Open on the remote listener's public face (review of #607, 2026-11-04)

- **A stranger can hold `/register` at its limit** (`oauth.Limits.register`: one global bucket, 10 then 2 a minute), which
  blocks a real app's sign-in by registration while it lasts. Pre-existing, and now one click from public. A metadata
  document client is not affected. Not fixed in #607: a per-source bucket needs its own look, since a tunnel's forwarded
  source is what the limit would rest on. Row growth from `/authorize` itself is fixed there.
- **Nothing pushes "another program is public" to a person who never opens the page.** The log and `cicada funnel status`
  say it too. A Home notice would need its own design.
- **A notice on Home for an address left open (G135, ruling 59). Required before the one-click address goes beyond the
  owner and testers.** The mapping is the daemon's and survives a crash, a reboot or a read that couldn't check it at the
  moment the switch went off (`funnelNote`, seen once). With the connector down, only the page, the log and
  `cicada funnel status` say so today.
  Home should say it, read from Tailscale, with the off, whenever an address is open and the listener isn't up.

## Known flaky tests

A test here is not fixed and not skipped: each line says what was seen and on what basis. Look here before chasing a
failure; add to the counts when one comes back.

None known (2026-11-05).


## Maintaining this queue

A whole row moves to DONE only after its remaining implementation and required acceptance are complete. If only one slice ships, name the remaining slice and keep the G ID active. Update this file and the reasoning row together; never renumber or silently discard an unresolved seam. Use [working-method.md](working-method.md) for the implementation bar and [BACKLOG_CONTEXT.md](BACKLOG_CONTEXT.md) for original prompts rather than loading old execution logs as current instructions.

## Rulings that cost real work to derive — do not re-litigate without reading them

1. **Decay charges once, and never for an outage.** Decay used to re-subtract the whole elapsed
   interval every run (proven: `octo.md` 0.85 → 0.4714 → 0.0928 in three commits *on one day*).
   Fixed with a `decayed_through` watermark + a per-cycle cap, plus a one-shot migration because
   the first cycle after the 75-day engine outage would have **archived 1,536 of 1,882 pages**.
   The principle: *an engine outage is a system failure, not user silence.* Migration has run;
   first-cycle archive count is now **0**, verified with a negative control.
2. **No relational tier** (G99). Measured, not assumed — three of four "SQL would fix this"
   arguments collapsed. Revisit only on the named triggers in that row.
3. **Markdown+git is the only source of truth.** A `.db` may exist only if deleting it costs CPU
   and never a fact, and **no derived artifact is ever tracked in a bank's git** (the 35 MB index
   was tracked and would have committed ~11 GB/yr once Sleep resumed).
4. **Scheduled cycles cannot spend plan quota — Claude or ChatGPT.** `user_triggered` is threaded
   through; a scheduled cycle returns `byok` before the registry is touched, and a Settings-chosen
   `agent` **or `codex`** is demoted to `byok` on a schedule by one tuple,
   `engine_select.SUBSCRIPTION_MODES`, so a third plan engine cannot forget the guard (Track E,
   2026-09-23). Only an explicit `CICADA_LLM_MODE` in `api/.env` runs a plan on the schedule. The UI
   copy says "never on the nightly schedule" and that is literally true for both plans.
   **4b — amended (owner, 2026-10-16): "The server should be allowed to use plans too. Just have to set them up
   somehow."** and, on the ChatGPT plan, the same day: **"Yeah chat too."** A machine may let **scheduled** runs use
   the person's plan behind an explicit switch, **off by default**: "Scheduled runs may use my plan" in Settings → Sleep,
   `cicada sleep schedule --use-plan on|off`, stored machine-wide as `sleep_run_prefs.scheduled_use_plan`; where it is
   turned on it says once that nightly runs then count against the plan's limits. With it on, a scheduled run resolves
   exactly as one the person starts would — the Claude or the ChatGPT plan, each only when it is the engine the person's
   own choice resolves to and it is signed in (`engine_select.SCHEDULE_PLAN_MODES`). `SUBSCRIPTION_MODES` stays the one
   guard; the switch is its only door besides an explicit `CICADA_LLM_MODE`. Such a run drains like any scheduled run
   (the dotfile pin keeps ruling 16's one batch); a plan limit pauses it, Past reads shows the plan share (#317), and the
   schedule replaces its `plan_window`/`plan_weekly` pause once the limit has reset (the vendor's `resets_at`, else after
   six hours) since on a server nobody presses Continue; extra usage stays the person's and ruling 15's continue never
   arms from a scheduled run. The scheduled web lookup (ruling 27) may use the Claude plan's search under the switch too.
   **Setting a plan up headless:** `cicada engine connect claude-plan` (Claude Code's own `claude auth login
   --claudeai`; where it cannot finish, `claude setup-token` elsewhere and `CLAUDE_CODE_OAUTH_TOKEN` in the unit's own
   environment, which reads as `oauth_token`, a plan) and `cicada engine connect chatgpt-plan` (the Codex CLI's own
   `codex login --device-auth`, in Cicada's own `CODEX_HOME`): in the person's own terminal on the server, through the
   CLI's own sign-in; Cicada never sees, prints or stores the token. **Owner decision 2, same day:** a schedule with no
   engine it may use says so — when it is turned on (`/sleep/schedule`'s `warning`), in `engine list` ("no key"), and
   `ask` says it has no engine — each offering to connect a plan first. Revisit if a scheduled run is found to have
   spent a plan without the switch on, or if the switch's disclosure is found missing where it is turned on.
   **4c — the switch is on by default (owner, 2026-10-19): "Make scheduled runs run on the plan by default."** A machine
   that never set it (a new install, a bank that never chose) reads as ON; only the person's explicit off stops it, and
   an off is now stored as `false` so it outlives the default (`sleep_run_prefs._switch`; a hand-edited non-boolean
   reads as off). Every surface that said "off by default" says so no more (Settings → Sleep's detail line, the CLI,
   the docs). `SUBSCRIPTION_MODES` stays the one guard and the switch its door. An off set before 2026-10-19 was stored
   as an absent key and reads as on now — that state was indistinguishable from never set. Revisit if a person is
   found surprised by a nightly run on their plan they never agreed to, or if the plan share of scheduled runs crowds
   out the runs they start.
5. **Raw storage does not replace Sleep** (G101). Text cannot decay — only a belief can go stale or
   be contradicted — so "time as a signal" needs a belief object.
6. **Capture is agent-judgment and that is a measured problem** (G105): 0 MCP invocations in 12
   days; 4 episodes from one very long session. **Answered by the G105 hook (2026-09-03):** capture
   is now a property of the harness's Stop hook, not of a model's tool call — the MCP
   `cicada_save_episode` path stays as the deliberate, agent-chosen episode.
7. **The Stop hook, not SessionEnd, is the capture trigger** (G105 R1) — SessionEnd never fires for
   a closed window or a killed process and shares a 1.5 s budget; the endpoint's content-hash
   short-circuit makes per-turn firing idempotent. Revisit only if `capture.log` starts showing
   timeout `error:` lines (the hook's 3 s budget, `TIMEOUT_S` in `api/hooks/capture.py`) on the live
   bank — the hook logs no timing, so a blown budget surfaces as an `error:` line, not a latency figure.
   **Trigger fired and answered (2026-10-29, `fix/capture-post-latency`):** 32 of the last ~340 Stop
   firings logged `error: TimeoutError`; the cause was the backend's answer, not the trigger — every new
   session's first Stop read every episode under the capture lock, and a long transcript read while other
   sessions, a notes sweep or Sleep shared the process ran past 3 s. The route now answers within 2 s
   (`202 accepted` when the write runs longer; it finishes on its own) and finds a session's episode from an
   index; under the reproduced load the hook went from 22/126 timeouts (p95 3.12 s) to 0/147 (p95 0.88 s).
   Stop stays the trigger. The signal is now a Stop `no answer` line (spooled, sent by a later firing) and
   the `in <n>ms` on every answered line — a latency figure at last.
8. **The Sleep page shows the ACTIVE stage, and there is one translation** (Track Z R-Z14). The
   wire's `stage` counts completed stages (`sleep_cycle.py` sets 1 only after Stage 1 returns);
   three derivations clamped it without adding one, so the worm, the bracket line and VoiceOver
   said "stage 1" while Sort ran. `activeStage(completed:)` is the only way any view turns the
   wire number into a stage. Revisit only if the backend starts reporting the stage in flight.
9. **Pixel art beside the worm is checked against the real worm, per weather** (Track Z
   Z-P13). A hand-approximated worm passed two window clouds the real frames hide (the head's
   shake uncovers a column); `WindowSpritesTests` masks with every look of every mood that shows
   that weather. Any new art near the worm gets the same test.
10. **The Sleep page's sky band is off** (Track Z Z-B16, spec decision 16). Built behind one
    constant, `SkyBand.ships`; gated in the build by `SkyBandTests` (a band's top composited over
    the page stays within 1.35:1 of it and keeps text ≥ 7:1, both modes, every sky) and decided
    by eye from the day/dusk/night × light/dark composites against a no-band control: every gate
    passed, yet the light-mode night and dusk bands read as a neutral grey haze pressing on the
    title — a smudge, not a sky — the dark night band was invisible and dark day a lighter slate
    strip; only light day read as a tint, and a band that works in one of six cases is not a
    feature. Measured tint / title ratios (: 1): light day 1.04 / 14.8, dusk 1.26 / 12.2, night
    1.29 / 11.9; dark day 1.29 / 12.4, dusk 1.02 / 15.7, night 1.00 / 16.0 — so the gates alone
    cannot decide it. Revisit only with new composites — flip the constant and re-run
    `CICADA_WRITE_COMPOSITES=1 swift test --filter SkyBandTests`.
11. **An agent's model and reasoning effort are recorded per turn — G49's reservation is lifted
    for harness writes (owner, 2026-09-24).** The owner asked that every memory write an agent
    makes be traceable to its harness, model and reasoning effort.

    Checked on a live transcript before building:
    - Claude Code's assistant lines carry `message.model` and a top-level `effort`.
    - The Stop hook's stdin carries `effort.level`.
    - Codex rollouts carry `turn_context.payload.model` and `.effort`.

    So the capture path (G105's one permitted transcript read) keeps exactly those keys on agent
    turns, and nothing else of the line: no thinking or reasoning text. A write through MCP is
    joined AT READ, by its session id and `recorded_ts`, to the turn it happened in
    (`turn_authorship.py`). It is never self-reported: an agent asked for its model can only
    guess, and a guess in provenance is worse than a blank. `Cicada-Author:` stays the harness
    label.

    Revisit when one of these happens:
    - A harness starts telling MCP servers its own model. Prefer that; it needs no join.
    - The transcript keys move. The extractor then reads null, never a wrong value.
    - A claim is ever shown with a model its turn did not use. The second-precision join rule is
      then wrong; read `turn_authorship.turn_at` first.
12. **Plan usage and model prices show on the Sleep page's Past reads run detail and its engine menu — and
    nowhere else yet (owner, 2026-09-28; surface renamed 2026-10-16, when the Sleep redesign turned Details into the
    page's tabs: Details' Last cycle and Past nights are the Past reads tab, so the figures live where they lived —
    `PriceLintTests` still holds them to `SleepDetails.swift`, `CycleUsageText` and the engine menu).** This supersedes the 2026-09-03 "prices and token usage are not
    shown anywhere in the app" ruling for those two surfaces only; ruling 4 (a scheduled cycle never
    spends plan quota) is untouched, and so is the no-cost-tiles, no-cost-per-day-chart half of the
    old ruling.

    What is shown, and why it is honest:
    - **Every figure carries its basis in words.** "Charged" is the provider's own bill (API key,
      OpenRouter). "At list price" is an estimate from the public price table or the Claude CLI's
      metering, never a charge. A plan cycle is its window's before → after.
    - **On a plan, the share leads, not dollars (owner, 2026-10-16).** A plan run says how much of each window it
      used — measured (the reading moved), "under 1%" (it did not; never 0 %), or estimated from the run's list-price
      size against earlier cycles' observed rate, each basis said, an estimate never shown as a reading. Its list-price
      figure stays only as the secondary "would have cost about $X on an API key". Metered runs keep dollars.
    - **A plan's percentage is the whole plan's.** The change across a cycle can include anything else
      the person used meanwhile; the UI says so. Claude reports a window only after a call, so its
      "before" is the reading after the cycle's first call, not a pre-cycle one.
    - **Unknown is never zero.** A ChatGPT plan call reports no tokens and no cost, so it reads
      "tokens not reported". A cycle from before this shipped, an aborted or idle one (no `sleep_run`),
      and an inbox or decay commit have no usage; the first three read "Usage not recorded" and the
      commits say nothing.
    - **Only consolidation is counted.** Calls are tagged from the cycle's own scope; the
      engine-independent tail (link backfill and the like) runs outside it and is not in a cycle's cost.
    - **The ledger stays ids, enums and numbers.** `refs.cycle_id` on `llm_call` and a `plan` block
      on `sleep_run`; never text.

    Revisit (widen it beyond the Sleep page) only when the owner asks for a second surface.

13. **Consolidate reads everything — a person-started run drains the whole queue, in batches (owner,
    2026-09-29); a scheduled one reads one batch — amended 2026-09-30 by ruling 16: it reads everything too.** The owner: "i dont want to cap the max episodes per
    sleep, why would we cap them? its just progress that cicada has to go through." This amends **G125
    R10** ("one trigger, one cycle") and **reverses the v5 spec's V5-15 / Q7** (a no-body trigger is one
    batch; a drain only from a sheet): Consolidate *is* the drain, no sheet, no `/sleep/run/continue`.
    Ruling 4 is untouched.

    - **Shape.** `POST /sleep/trigger` runs `run(drain=True)`: freeze the waiting ids, resolve the engine once,
      read them in batches of `sleep_max_episodes_per_cycle` (default 25, now "how often progress is saved"), each
      batch filed and committed by Stage 5, so a cancel or a plan stop loses at most the batch in progress.
    - ~~**Scheduled = one batch.**~~ *Amended 2026-09-30 (ruling 16):* a scheduled run drains the queue too, on the
      scheduled engine (`user_triggered=False`, so never a plan — ruling 4 unchanged). The original reason — an
      unattended run on an API key reading everything is real money — is now said in words in the engine menu and
      Details instead of being prevented.
    - **Once per drain:** decay (both engines; ruling 1 — charged once, not once per batch) and Stage 5.57's page
      reads, in the batch that empties the queue. **Once per run:** the engine-independent tail. Everything else per
      batch, so each commit is self-consistent.
    - **A plan limit is a pause, not a failure,** with the vendor's own sentence and reset time. *Since built
      (2026-09-30, Sleep page v5):* Continue / End this run on a paused record, the opt-in continue-after-reset
      (ruling 15), the "leave room in my plan" reserve, run-level Past nights. **Still not built:** a journal of paid
      answers (a cancel or a hard rejection before Stage 5 still discards the batch in progress), parallel reading
      ("Read faster" — the owner declined it for now, G163).
    - **Cost accepted:** bank switching, export and delete are refused for the whole run (the drain is pinned to its
      bank) — by name, and the app shows the sentence. Every other guard and the MCP write probe follow **G177**'s
      write window (`sleep_cycle.is_writing()`), so an agent's claim between batches commits alone under its own author.

    Revisit only on the trigger G163's row names (the journal slice; the reserve and Continue are built), or if a drain's plan volume
    hurts a real owner's coding budget.

14. **Reading with the person's own agent — Cicada asks, the agent reads, the backend holds no session
    (owner, 2026-09-29: "i want the agent using browser harness … or the native computer/browser harnesses from the
    chatgpt app and claude app, which uses the logged in sessions and swiftly surfaces 'needs login'… I want this built
    now"; G166, spec `2026-09-29-reading-the-web-design.md`).** Four of the spec's proposed rulings are now binding; the
    rest (R-RW1–3 the Reader's identity and metadata tier, R-RW6–7 and R-RW12 chat links, R-RW10–11 robots and backoff)
    stay with the Reader slices.
    - **Amended 2026-09-30 — no pre-picked site list; sites are surfaced from the reader's own failures (owner: "limiting the
      amount of sites makes no sense to me, because we will never know which sites this will happen").** The five per-site
      switches are gone. A saved page Cicada's own reader could not read — a sign-in, a consent wall, a refusal, or a host the
      backend never requests — is a *wall page* (`reading_walls`, from stamps the fetchers already write, and only while it
      holds no words); wall pages group by site (`reading_hosts.site_of`); Settings → Reading the web lists those sites with
      measured counts and a per-site switch, off until the person turns it on (`reading.agent_sites`, a grant refused for a
      site nothing has surfaced). Surfacing follows the reader's failures *wherever they happen* — save time, the in-cycle
      pass, the backfill — so the backfill's throughput never bounds it. The master switch, the versioned acknowledgement
      (now v2, without the site picker) and per-page "Ask an agent" stay. Copy across the branch is provider-neutral: it
      describes the step ("summarized by the engine you chose for Sleep"), and names a provider or model only where it
      shows the person's own current choice. **Amended clauses:** R-RW8's "per link, for a site the person switched on" is
      "per link, or per site the person turned on after a page from it could not be read"; "Reddit and `t.co` are never
      offered; the other five are five per-site switches" is "`t.co` is never offered; Reddit surfaces like any site"; and
      Track P R5 (a retired interstitial or login wall stays out of the Feed) now lets a page through **only** when it is such
      a wall an agent can be asked to read, or an agent already read it. **Review 2026-09-30:** a row an agent's own outcome wrote
      (`origin: site`) is no consent of its own — it authorizes a record only while the site is still allowed and the
      page is still a wall page, so switching a site off revokes recording as it dequeues; a connector whose saved item
      *is* the post (X bookmarks: the text in `## Notes`) holds words, while a Reddit or Pinterest save is a link out
      whose title or pin description is not the linked page, and surfaces on purpose.
    - **A site switch is a standing permission, derived not fanned out (2026-09-30).** The queue is the person's asks plus
      wall pages of allowed sites, computed at read (`reading_queue`): a switch writes one line, a new wall page joins with
      no write, turning it off (or the master) dequeues at once. An agent's `needs_login` pauses that site's derived entries
      until the row expires (7 days), the person asks again on a page, or switches the site on again ("try again"): an agent
      that is not signed in is asked again at most weekly. Pacing is one entry per site per call. Grants are machine-wide
      (`reading.json`); the pause is per bank (the ask store is).
    - **The Feed shows a wall without being opened (review, 2026-09-30).** The row's second line says "Needs sign-in" and a
      toast announces a link that just hit a wall (not on the first look after launch); the text is the text ladder plus a
      neutral glyph, not `warning` (DR-7 is unchanged). A quote from `cicada_record_read` is labelled "From the page, as
      <agent> read it", never bare "From the page" (spec §8.5).
    - **R-RW8 — the ruling that keeps this from eroding the rail.** The standing rail ("no scraping behind
      authentication", 4 s / ≤ 512 KB / no cookies / a block never retried with different headers) governs *Cicada's own
      fetcher* and is unchanged. Agent reading is person-driven and never scheduled; Cicada only *asks* — per link, or per
      site the person turned on after a page from it could not be read, after a versioned first-use acknowledgement — and
      promises nothing about what the
      agent does in its own browser. The backend never holds a session, a cookie or a profile. No Cicada text says
      "read-only" or "never posts"; contract item 9 and the hand-off prompt are *instructions*, not promises.
    - **R-RW4 — one closed set of login-walled hosts, and the backend's page readers never fetch one.** X, Facebook, LinkedIn,
      Instagram, TikTok, Reddit and `t.co` (dot-boundary match: `lnkd.in` and `fb.watch` in, `notx.com` out). This closes
      the X gap (X fell through to the OpenGraph fetch). TikTok keeps its provider oEmbed branch, which never loads the
      page, and the Reddit and X connectors still call their own APIs; the rule covers the *page* fetch of
      `media_ingestor.enrich` and the `link_enrichment` backfill. `t.co` is never offered to an agent. There is no pre-picked list of sites: a site is *surfaced* when Cicada's own
      reader cannot read one of its pages (a sign-in, a consent wall, a refusal, or a host the backend never requests) and
      the person turns it on, per site, on Settings → Reading the web. Site icons come from the icon service only, and a walled
      site is never contacted for its favicon either.
      `link_enrichment._excluded_media` is shared with `fact_sources.is_refused_host` and `link_recon`, so a source on
      such a host now reads as needing the person's login there too.
    - **R-RW5 — a link that carries a secret or a side effect is never offered** (a token-like query key, an
      unsubscribe/verify/reset/logout/oauth path segment, a signed URL, a private-workspace host, a userinfo or non-web
      port), nor is a local or reserved host, an AI vendor's own page, a video (the video path owns it) or a paper.
    - **R-RW9 — `--chrome` is in no argv** (`test_reading_never_spawns_browser.py`). Measured: it overrides
      `--safe-mode`, `--strict-mcp-config` and `--tools ""`.
    - **Only a link the person asked about, or a wall page of a site they allowed, can be recorded (review, 2026-09-29;
      amended 2026-09-30).** `cicada_record_read` refuses every outcome, `read` included, for any other URL, whether or not
      the link is saved (a saved public page with no wall too), and `reading_asks.record_outcome` creates a row only for the
      site case (`origin: site`) — otherwise it writes nothing without a live row. **Exposure, stated:** with a site grant the
      person consented to a *site*, not to a page, so any agent holding `record` can then record a wall page of that site;
      the structural denials (R-RW5), the master switch, ask-store-only outcomes and `page`-kind spans bound it. Before this a saved link with no ask took any outcome
      (a rewritten description, a planted `needs_login`), which is what a page steering an agent would use.
    - **The outcome is stored where it can be shown at once.** `needs_login`, `blocked`, `not_found` and `failed` live
      only in the machine-wide ask store (no bank write, no commit, no Sleep gate) and move the `reading` sync component;
      only a successful `read` is memory. Chosen over writing the page because a page write needs a commit, is refused
      remotely while Sleep runs, and does not exist for a link that was never saved.
    - **An ask's URL is visible to any connection holding `read`** (this departs from the spec's §8.4, which hid a
      `role: user` row's URL without `sources`). Cause: the person's explicit "Ask an agent" *is* the consent to hand that
      one URL to an agent (and, amended 2026-09-30, their grant for a site is the consent for that site's wall pages — a
      site entry from a channel that is the person's own words, such as Telegram, an agent's save or a chat export, needs
      `sources`; only saved-content channels are served to `read`), and the default scopes are search/read/record, so applying the old rule would leave the ChatGPT
      and Claude apps unable to read any ask. `sources` still gates every verbatim word of the person's conversations, an
      inbox `Cause:` quote and any chat-harvested URL (not built yet). No `why` or note text is served remotely.
    - **How the agent reads is a selection, and an instruction (2026-09-30; owner: "i want to use the macos-harness, the
      browser-harness and claude-video … as selections in settings, amongst the other default options models can use through
      their harnesses").** "Let my agent choose" (default), the agent's own tools, or a catalog skill whose `roles` list the
      job; stored on this Mac (`agent_methods.json`), passed to the person's own agent as a sentence in the hand-off prompt,
      the stdio queue reply and one primer line — never to a remote connection, never authority. A skill the person picks
      gets a `type: skill` page tagged `agent-skill` in the graph, written only on that selection. `macos-harness` states
      plainly that it can control the whole Mac. **Extended to watching (2026-09-30, ruling 17):** the same mechanism has
      a second job, `watching` ("How your agent watches", Settings → Reading the web, under "How your agent reads"), with
      its own choice — one per job. It offers "Let my agent choose", the agent's own tools, and `watch` (claude-video),
      `browser-harness` and `macos-harness`. Backlog: **G178** (people add or import their own skills).
    Revisit when the owner asks for Route B (a Cicada-spawned browse call, spike-gated) or a per-category refuse list
    (adult, financial, health hosts: not buildable as an honest closed list, so every site the reader could not read stays
    off until the person turns it on, and every other page is an explicit ask).

15. **Continue after a plan reset — an opt-in switch, a narrow amendment to ruling 4 (owner, 2026-09-30).** The
    owner asked for it and chose the shape: a switch in *Reading options*, **off by default**, that lets **a run the
    person started** continue itself after its own plan window resets. Ruling 4 stands for everything else: a
    scheduled run never uses a plan, and a plan is never spent without the person's own start.
    **The rule.** A run the person started may continue itself after its plan window resets if the person switched that
    on for the runs they start. It never crosses a weekly reset, never arms from a scheduled run, and never changes
    engine. The switch is snapshotted into the run when it starts, so flipping it on later never arms an old run;
    turning it off withdraws an armed one.
    **The bounds** (proposed in the Sleep page v5 plan, Q-B; **confirmed by the owner 2026-09-30, "as built"**; each is a constant in
    `sleep_autocontinue.py` and a row of `test_sleep_autocontinue.py`'s table): at most **2** automatic continues per
    run; only within **36 hours** of the pause and only when the vendor **gave a reset time** (an absent one is never
    guessed); only for a **5-hour** window, the reserve line on a 5-hour window, or extra usage that then resets — a
    weekly or an unrecognised limit never arms (`agent_engine.limit_kind_of`); only while the engine the run started on
    is still what the person's own choice resolves to (label and model). The job is a one-shot `DateTrigger` at the
    reset plus a minute, recorded in the run's sidecar so a restart re-arms it, and every guard is checked again at fire
    time; a guard that fails leaves the run paused and `autoContinue.blocked` says why. If the Mac slept through the
    reset it fires on wake while still inside the 36 hours; keeping the Mac awake is G243 (a run on power holds an assertion when the person's switch is on; no wake, no closed lid).
    **The rail.** `run(continue_from=…)` is called from exactly two places, the Continue route and
    `sleep_autocontinue` (`test_only_the_continue_route_and_this_module_may_pass_continue_from`); the scheduler never.
    **The honest limits.** The plan's percentage covers all use of the plan, not only Cicada's; a reset the person
    slept through is still one automatic continue spent. Revisit the bounds on the owner's word, or the switch's default
    only with a ruling of its own.

16. **A scheduled cycle reads everything waiting too — ruling 4 untouched (owner, 2026-09-30).** This amends
    ruling 13's "scheduled = one batch". `sleep_scheduler` passes `drain=True` from both entry points (the daily/interval
    cron and the after-import probe); `user_triggered=False` still keeps every plan engine out, so an unattended run
    reads on the scheduled engine — a key, OpenRouter or Ollama — and **on a metered engine it spends until the queue is
    empty, with no limit Cicada sets** (amended by ruling 63 (g), 2026-11-04: up to the person's spending limit). That is said in words where the person chooses it (the engine menu's Scheduled
    row and Past reads' Last cycle, never a price outside them — ruling 12) rather than prevented. Consequences built with
    it: a scheduled drain pins its bank for hours and holds the same 409 on switch/export/delete as any run (disclosed,
    not fixed); a scheduled run that stops leaves a paused record and **the scheduler then starts nothing until the
    person continues or ends it** (`sleep_paused.exists`, both entry points), or a Pause would be undone within five
    minutes; the after-import probe counts *readable* conversations (waiting minus parked), so a queue of only parked ones
    never fires an empty run every five minutes; only the person's Continue can resume a scheduled run, on the manual
    engine, which can be a plan (the button names the engine). **Not built:** a spending cap or a batch cap for scheduled
    runs (owner, 2026-09-30: "no cap for now"), and "keep the Mac awake" (built as G243, a switch, 2026-11-06) — revisit on the first real bill an unattended drain produces.
    *Refined 2026-09-30 (final review):* the "starts nothing" rule protects a pause **a person chose or can act on**;
    a scheduled run's pause nobody chose — the process went away (`restart`, every app quit without the launchd agent)
    or the scheduled engine failed (`engine`, once at least 6 hours old so an absent engine costs one call every few
    hours) — is ended and replaced by the next scheduled run (`sleep_paused.schedule_may_replace`), otherwise one quit
    would stop scheduled reading for good. **The dotfile exception:** an explicit `CICADA_LLM_MODE=agent|codex` pin
    still resolves a scheduled run to that plan (unchanged since before G122), so under that pin the scheduler reads
    **one batch**, never a whole queue unattended on a plan (`engine_select.scheduled_plan_pin`).

    **Two amendments recorded with rulings 15 and 16 (Sleep page v5, 2026-09-30).** *G125 R10 ("one trigger, one cycle")*:
    the Sleep page gains **Pause / Continue / End this run** and a parked row's **Retry** beside its one Consolidate
    trigger (Home's and the intake card's *Read now* stay narrow amendments; every door that meets a paused run routes to the
    Sleep page instead of starting one). *P15 / R-A8*: **a stage carries a fill only when it counts something that
    finished** — Read, Sort and Decide fill from finished work; Notice and File carry no number.

17. **Video: the watch run is the person's own agent's work, the queue lives outside the bank, and copy names no
    provider (owner, 2026-09-29 and 2026-09-30, G162).** The owner approved the boards ("I also like the watch video
    designs, apply them") and, in three sentences, changed the design: no cap on a batch (ruling 13's reasoning),
    "Ollama and the rest are literally just providers. So don't assume or make the choice for the user", and "limiting
    the amount of sites makes no sense … we will never know which sites this will happen". Rulings R-VU1…R-VU10 of the
    spec stand as written except R-VU10; the three new ones are R-VU11…R-VU13
    ([`2026-09-29-video-understanding-design.md`](../specs/2026-09-29-video-understanding-design.md) §3 and §13).

    - **State is about the event, not the belief (R-VU1/2).** A video is *read* when a `video-watch` episode with a stated
      `basis` exists; the union of its episodes' facts gives `none | transcript | watched | watched_and_transcript |
      recorded`. `basis` is the agent's word and Cicada says "an agent recorded that it watched", never "Cicada
      watched"; a record with no basis is `recorded` ("method not given"), never `watched`. Nothing is stored.
    - **The queue is outside the bank (R-VU3, P4).** `$CICADA_HOME/video_queue/<bank>.json`, keys only (no URL, no
      title), flock and atomic replace, expiry in memory. Nothing in its lifecycle dirties a bank, so no route or claim
      answers 409 while Sleep runs; `cicada_video_claim` is in `WRITE_TOOLS` (the demo gate, the write lock) but
      `_writes_bank` is false for it. A lapsed lease is judged only when Sleep is not holding the pages, so a long
      drain cannot burn a video's three attempts. The `videoQueue` component carries how many leases and expiries have
      come due, because a lapse writes nothing.
    - **R-VU10, amended.** Cicada's *default* prompt never steers an agent into the person's logged-in browser for a
      video. When the person turns on the single reading permission, the prompt carries it as an instruction (their
      consent, R-RW8), never a promise, for every host: no site list, no `agent_hosts`. Owner line: 2026-09-30, above.
    - **R-VU11 — provider-neutral copy.** Nothing a video surface, the prompt, a tool description, the contract clause or
      the bridge line writes names a provider or model as the one doing the job (`test_video_copy_provider_neutral.py`).
      Names appear only as data (a harness label an agent sent).
    - **R-VU12 — no batch cap.** The queue file's ceiling is 2,000 rows, a file-safety limit with a sentence.
    - **R-VU13 — no site list for video.** An agent hands back what it cannot get with a code; the app surfaces it.

    - **How the agent watches is the same selection (2026-09-30; owner: "for now i want to use the macos-harness, the
      browser-harness and claude-video to watch videos, as selections in settings, amongst the other default options
      models can use through their harnesses").** `agent_methods` gained the `watching` job (ruling 14's skill
      paragraph). The choice — Let my agent choose (default), the agent's own tools, or one of `watch`,
      `browser-harness`, `macos-harness` — rides in the video hand-off prompt (`video_prompt.method_clause`, capped at
      130 characters so the prompt's 1,200 holds), in the stdio `cicada_video_claim` reply for a local catalog agent (a
      skill) or any local client (the agent's own tools), and in one primer line (`Watching videos`); never to a remote
      connection, never authority, and the skill is named only as catalog data (the neutral-copy lint scans templates).
      The primer budget stayed at 1,525: both method lines defer to items 3 and 9 for the tool names instead of
      restating them. Naming a browser skill here does not reopen R-VU10: the default text still names no browser
      route, and a chosen skill is the person's own instruction, carried the way the browser permission is.
      `macos-harness` says it can control the whole Mac in the picker.

    Revisit R-VU10 only if a real run shows the clause steering an agent somewhere the person did not allow; revisit
    R-VU12 only if a bank's queue file ever nears its ceiling.

18. **The study room is animated pixel art on the owner's own bookworm — state art may move, and it still shows only
    real state (owner, 2026-10-01; G176, G107, G125).** The owner: "I've already done here the base model of the
    bookworm i want. Can you iterate with codex sol 6.1 extra high effort all the sprites with the animations? and
    generate the assets like the lamp, extra books, window, environment behind window animated too. Little fly (pixel
    size almost), moving around turned on lamp. Have environemnts for sunny, night, windy, rainy... all animated. You
    will find the bookworm png and 5 emotion states here app/assets/. Make sure to generate everything, have codex
    implement it using computer use in aseprite and add it to the app." The binding spec is
    [`2026-10-01-bookworm-sprites-spec.md`](../specs/2026-10-01-bookworm-sprites-spec.md). This amends Track Z's R-Z1
    (its persist list: the held book at room scale in every state, shut eyes when sleeping, black X eyes and the drop on
    error; the nightcap retires; the stage dots persist only in the 18 × 18 set), R-Z4, R-Z11 (titles, motion and
    palette: `palette.json`, not `DeskPalette`) and R-Z12, G125 v3's R-A13 and P14, the 2026-09-02 mascot plan's R1
    (nine colours), R3 (the 24-cell grid) and R8 (250–800 ms), and the sprites brief's §4, §5 and §9 where named below.
    R-Z2, R-Z3, R-Z5, R-Z7, R-Z8, R-Z9, R-Z10, R-Z13, R-Z14, P10, P11, P12, P13 and rulings 8–10 and 12 are untouched.
    - **R-BW1 — the worm is the owner's reference.** `app/CicadaApp/Art/sprites/bookworm-2026-10-01/reference/` (the
      base model, five emotions and the menu-bar design) is the approved design: a green bookworm, charcoal-grey
      glasses, a blue book, no antennae. It closes G176 Step 1 (the round-1 directions are superseded) and replaces
      "orange glasses" (brief §4, §9). The book is the character's own in every room-scale state; P10 is about props,
      not the worm. The 18 × 18 set follows the owner's menu-bar design (head, glasses and neck in two colours) and
      shows a book only in `reading`. The nightcap retires (P14), and the room worm drops the stage dots: the stage
      strip, the sentence and VoiceOver carry the stage; the 18 × 18 set keeps them.
    - **R-BW2 — sprites are sheets, not strings.** Sources and Lua generators live in
      `app/CicadaApp/Art/sprites/bookworm-2026-10-01/`; exported PNG sheets + Aseprite JSON (tags, per-frame
      durations, slices) live in `Resources/sprites/` with `sprites.manifest.json` (generator, script, source, date,
      licence, sha256) and a test that checks every hash and that each JSON's tags are exactly the ones the app asks
      for. Sheets load only through `Bundle.cicadaResource`. One `palette.json` is read by the scripts and the tests.
      G127's seam stands: a character is a set of sheets with the same tags.
    - **R-BW3 — frame animation (the Track Z lint amendment brief §4 asked for).** Motion is sprite frames with
      per-frame durations from the sheet, on whole pixels of the one lattice, drawn nearest-neighbour. R-Z4's
      no-transform lint stays for the worm and widens to every room sprite. "≤ 3 frames × 0.12 s" becomes: a beat
      settles within 800 ms (the perk within 400 ms); a transition within 1.6 s; no frame is shorter than 40 ms or
      longer than 4 s; a loop runs 0.4–30 s — `CicadaMotion`'s sprite caps, checked against every sheet. The renderer
      key bound (≤ 256 per size) becomes a bound on frame rects and decoded pixels.
    - **R-BW4 — state art may move (R-Z12 and R-A13 amended).** A state's art may loop — breathing, blinks, page
      flips, z → zz → zzz, the weather's own loop, the fly — because the loop shows a state that is already true. It
      never adds a fact and never speeds up, densifies or brightens with a count, an age or a stage (R-Z3). A mood
      change may play one transition (a yawn into sleep, a stretch out of it) besides the cheer and the weather
      crossfade; a hydrate or a refresh never does (DR-65). Glances, sways, tail flicks and nod-offs inside a state's
      idle loop, and cloud drift inside a weather's loop, are state art (R-Z12's "no glance, no drift" is amended for
      them). Still refused: any flash or strobe (the storm flash), weather driven by a count, motion with
      no state behind it (mug steam, plant sway), and duration estimates.
    - **R-BW5 — scenery separates environment and Sleep (owner amendment, 2026-10-02; R-Z11).** The time follows
      `SceneClock`'s day · dusk · night through `SceneStore` unless Choose pins it. The five base weathers are sunny,
      cloudy, windy, rainy and curtains. Local weather (default) reads the time zone's principal city, falling back to
      How Sleep is doing when unavailable; How Sleep is doing maps the mood; Choose fixes the time and base. Running
      adds calm mist; digesting adds a rainbow by day/dusk or a shooting star at night in every mode. The legend, help
      and VoiceOver share the same time/base/source and moment text. Ruling 9 applies to every weather frame and every
      reachable worm frame in each lighting set. Pixels on the lattice only, never Meadow paintings (DR-13).
    - **R-BW6 — the room is dark iff night or rainy (owner amendment, 2026-10-02; R-A13).** Lighting is a pure
      function of time, base weather and lamp: the dark room has only faint window light and, when scheduled, the lamp.
      Dusk keeps the day-lit room. Props select `night-dark`/`night-lit`; all eight room states use matching night sheets,
      including beats and both sleeping transitions, with identical tags/frame counts/timings to day. The complete art
      layer crossfades with the pane using the existing 0.4 s token; Reduce Motion swaps instantly. The menu bar stays
      independent of room lighting. The worm's mood remains Sleep's at any hour and in any weather.
    - **R-BW7 — the five emotions map to states, once.** happy → `.happy`, `.digesting` and the cheer; tired →
      `.hungry`; worried (sweat drop and black X eyes) → `.error`; sad → the shake beat; the base model → `.awake` and
      `.reading`; mad is drawn but unused. Never random, never the clock. The menu bar gets an 18 × 18 set drawn from
      the owner's menu-bar design, with the count badge and stage dots drawn on it in code (G107 R2), and its own
      precedence unchanged.
    - **R-BW8 — the lamp and its fly.** The lamp is redrawn and still means exactly the schedule (R-A3, P11; it never
      previews). The fly is the lit lamp's art: present only while lit, inert, never in the glass or the pile column,
      resting on the shade under Reduce Motion.
    - **R-BW9 — books (P10 holds).** The worm's own book has three covers that change as he picks up the next one;
      the real pile's spines gain a pixel texture by kind (a second cue beside colour; `fitPile` unchanged). No other
      book is drawn: a shelf, cart or bookcase needs a real count and its own design round.
    - **R-BW10 — interaction is unchanged.** The hotspots stay the worm, the lamp and the window; the plant, mug, bean
      bag, wall, rug, cord, scenery, wall clock and fly stay inert (R-Z2). No click on art starts, cancels or schedules work (R-Z9).
    - **R-BW11 — Reduce Motion, Low Power, unseen.** Under Reduce Motion every sprite shows its key frame (G107 R7)
      and the yawn and stretch do not play; under Low Power every frame plays at half speed; a sprite rests while its
      window cannot be seen or a host pauses it (R-HO7's reader and policy). Each animated layer redraws only at its
      own frame boundaries. **Budget:** the room's summed sprite redraws stay ≤ 1,800 per minute in every steady
      environment/mood/lamp combination, computed from the sheets (sprite boundaries plus the clock's 60 ticks ≤ 1,800 per
      minute, tested in `SpriteClipTests`); mean CPU with the room frontmost stays ≤ 3 % of one core and within 2
      points of `dev`, measured by the owner on the demo bank before merge.
      **Player amendment (2026-10-05, measured):** moving frames swap a layer's `contents` on a timer armed at each
      boundary (`SpriteLayerPlayer`); no sprite plays through a `TimelineView`. On macOS 26 a `TimelineView` with
      entries under ~0.3 s apart drives the whole window's layout at the display rate (240 host layouts a second
      for 4 ticks a second in an isolated test; 120 renders a second on the Sleep page), so the boundary budget held
      while the page still cost 12% of a core. After the change: 2.54% visible, 2.6 renders a second, 0.83% hidden
      (the menu-bar worm). A 1 s timeline still re-renders the whole window once a second, so the wall clock's second
      hand is a layer too and the leaf redraws once a minute: 1.03% visible with the graph resting, 0 renders in 10 s.
      **Wall-clock amendment (owner, 2026-10-02):** `room-clock` is state art selected from `Date()` and
      `TimeZone.current`, not a sprite loop. Hour = `(hour mod 12) × 5 + minute / 12`, minute/second = their
      integer values. Its own visible-only `TimelineView(.everyMinute)` moves hours and minutes, and a layer
      (`SpriteLayerPlayer`) moves the second hand on every whole second (2026-10-05); no room-wide timer.
      Black hour/minute hands and a thin red second hand use dark variants in a dark room. Reduce Motion removes
      only the second hand; hour/minute keep time. Help and VoiceOver say “Wall clock, <system short time>”,
      after the window. The inert clock at `(94,34)`, 15 × 15, z1 clears every worm frame, the window, shade and pile;
      the art verifier rechecks night sheets. The manifest is 36 pairs; motion sidecars exclude the clock.
    - **R-BW12 — how it was made, and the gate.** The owner chose the tool and the model for this job: Codex
      (gpt-6.1-sol, extra-high effort) with computer use in Aseprite. This overrides brief §5's "Computer use in the GUI
      is not needed and is worse" and the handoff's model split for this job only; the small-models rule is otherwise
      unchanged. Parts are hand-correctable in the GUI; every sheet is rebuilt and exported headless so the manifest's
      hashes are reproducible. PR to `dev`; no merge until the owner has reviewed `preview.html` and the composites.
    - **Dated owner amendment, 2026-10-01 — black X eyes and one menu sheet.** Error retains its worried brows and
      drop, with the exact black diagonal Xs in both lenses; red pupils retire. `errorLensL = (10,17,5,6)` records the
      error state's widened inner left rim; common rest-registration slices remain unchanged. The 18 × 18 sheet keeps
      its dark outlines on both menu-bar appearances; no dark-bar variant.
    - **Dated owner amendment, 2026-10-02 — Settings and the weather gate.** Settings → Sleep → The scenery offers
      Local weather · How Sleep is doing · Choose, with per-viewer source/time/base preferences. Choose exposes labelled,
      keyboard- and VoiceOver-accessible key-frame thumbnails for three times and five base weathers and a small live
      room preview. Local weather discloses the public city read. The app's own weather gate is Local weather AND the
      study room visible: one HTTPS host, four seconds, at most 64 KiB, no cookies or identifiers, no redirects/auth,
      at most one attempt per half hour including failures, memory cache only; selecting another source turns it off.
      It reads public city coordinates from `TimeZoneCoordinates`, never location permission or a bank. The binding
      [`2026-10-02-study-room-scenery.md`](../specs/2026-10-02-study-room-scenery.md) supersedes the old seven skies and
      no-clock refusal. A lightning flash stays refused. Count props, the queue as a room, G175 marks and Q1 remain open.
    - **Dated timing amendment, 2026-10-02 — retain R-BW11's cap.** Independent leaves cost 1,908 boundaries/minute
      for rainy-night + digesting + lamp lit: rain 749, fly 520, worm 340, shooting star 239, clock 60. Rain's holds
      move from 80 to 100 ms in day/dusk/night, keeping all 48 original pixels/frames and every seamless motion step.
      The amended rain costs 599/minute; the measured maximum over all 240 combinations is **1,758/minute**. The
      art verifier pins 100 ms exactly and still checks the historical day-pixel hash. No cap was raised. Hidden
      rooms and Settings explicitly pass the pause to the sprite leaves as well as the clock and weather reader.
    - **Dated mascot amendment, owner 2026-10-02:** “work on the selector for the mascot in settings. Name this one
      bookworm.” The Mascot group beside The scenery uses registry entries (id, display name, room prefix, menu
      sheet, art folder), with exactly **Bookworm** today. Selection is a per-viewer preference, default/fallback
      `bookworm`; shared art readers, cover/transition timing and the menu cache resolve that entry. Tiles show
      room/menu key frames, a checkmark, keyboard focus and a selected VoiceOver label. Another character will have
      its own base and the same pipeline/tag/canvas contract, plus one entry and manifest files; no state change.
    - **Integration review correction, 2026-10-02:** room layers keep the appearance crossfade; the worm is its
      sibling, keyed only by day/dark-lit/dark-unlit lighting. Mood/overlay edges and day-time lamp toggles start
      their new frames fully visible when the lighting set stays the same. **Re-review follow-up:** an active
      transition or beat also suppresses the worm's lighting-swap animation, so error → sleeping's day/dusk
      rainy/dark → sunny/day yawn starts fully visible in Sleep-driven scenery or Local weather fallback. Room
      layers still crossfade; passive worm lighting changes retain their fade. The wall clock ticks on whole seconds (whole minutes without seconds under
      Reduce Motion). Weather sends no viewer language/region; an empty language field suppresses CFNetwork's
      default, fixed headers accompany the coordinate/condition query, and the disclosure includes the network
      address. Backwards time makes the next attempt due; stale readings remain only for an eligible visible
      refresh or an in-flight refresh, and failures/cancellation/zone changes cannot retain expired weather.
      Night book/glasses/lid/z/question/X/drop marks and fly shade occlusion are checked from the real sheets.
      Partial builds refresh saved-parts predecessors and all night exports/manifest/full verification; repeated
      night/fx builders replace prior output. Static family provenance removes the Codex CLI rebuild dependency.
    Revisit R-BW4 or R-BW11 if either half of R-BW11's budget is exceeded or a viewer reports motion discomfort;
    R-BW5–R-BW9 on the owner's word.

19. **A release is a merge to `main`, and a merge to `main` is a release (owner, 2026-10-06; G182).** This replaces
    the manual-promotion rail for releases only. Owner, verbatim: "from now on yes we merge by default to dev, but for
    releases we merge to main and automatically should be a GitHub release. So versioning should be setup properly."
    **The rule.** Every feature/fix PR still targets `dev`. A release is a PR from `dev` to `main`, opened only for a
    release and carrying the version bump; merging it is the release. CI on `main` then tags `vX.Y.Z` at the merged
    commit, builds, verifies and publishes the GitHub Release — nobody tags by hand, and nothing else reaches `main`.
    **Versioning.** `VERSION` (semver) is the one source; the app bundle, `pyproject`, the tag, the release title and
    `latest.json` must all equal it, and CI rejects any disagreement. A merge whose `VERSION` already has a tag
    publishes nothing (idempotent); a `VERSION` not greater than the latest tag fails loudly. A failed build,
    verification or publication advertises nothing (no tag, no `latest`), never force-pushes, never overwrites a
    released asset. The website's download link resolves through a stable latest-release asset, so no later release
    needs a website edit.
    **Why.** The owner's delivery priority for 2026-10-06 (G182): releases must exist, and the released version,
    `main` and the website must never drift. Before this, 0.3.0 was built and dry-run four times but never published,
    and `main` trailed `dev` by 88 commits.
    Revisit on the owner's word (e.g. a release-candidate channel or an older-line hotfix branch).

20. **G110 continuity rulings (owner, 2026-10-07): A — flush yes; B — head and tail; C — strip only what the harness marks.**
    Recorded with the build that implements them (feat/g110-gates).
    **A — amends ruling 7.** Stop stays the capture trigger; PreCompact and SessionEnd ALSO run the same deterministic
    capture as a best-effort, idempotent flush, so a turn the person interrupted before a `/clear` or a compaction is not
    lost. Every capture log line is tagged with its event (Stop / PreCompact / SessionEnd), so ruling 7's revisit signal
    (timeout `error:` lines) stays visible per event. SessionEnd posts within Claude Code's 1.5 s budget.
    **B — the capture cap keeps the head and the tail.** Over the 100k-character session cap, capture keeps the first
    60k and the last 40k (the tail advancing in blocks of whole turns) with an explicit gap marker that is never a
    speaker's words. Costs accepted knowingly (G104): a long active session is re-extracted as its tail moves; quotes in
    turns that slide out degrade to `reasoning`; the person's words that slide out of the tail leave the bank. Revisit
    if re-extraction cost on long sessions is measured as a problem (G104/G148).
    **C — clarifies G149.** A Cicada note is dropped from capture only when the harness marks it as injected (whole
    non-person records / harness envelopes). Text the person typed or pasted — even one starting with Cicada's header — is
    kept as the person's words and counted/disclosed (`note_like_turns`). G105 R5's tool-output and system-reminder
    rules are unchanged.

21. **G180 CLI rulings (owner, 2026-10-07).** **Transport:** the `cicada` CLI runs Cicada's services in-process, the
    stdio MCP's own model, under the same locks (write admission, page, git), the bank pin and `demo_guard`; before a
    write it cross-checks the backend's `/healthz` `memory_root` and refuses on a mismatch (the split-brain guard). It
    works with the app closed and in network-off sandboxes. **PATH:** an app Settings button links `~/.local/bin/cicada`
    without admin; the skill falls back to `~/.cicada/bin/cicada`. **Session:** a write from a shell with no harness
    session id omits `session_id` and the `Cicada-Session` trailer, never a per-command minted id (it would fragment the
    stream, G104). **Names:** short grouped commands (`cicada recall`, `cicada save`, `cicada claim add`, `cicada inbox`,
    `cicada sleep status`); MCP tools keep the `cicada_` prefix, and grouping them is the lean-MCP slice, decided on
    measured schema numbers with old names kept as aliases. No generic `call <tool>` door.
    **Why.** Over HTTP nothing works with the backend down and sandboxed shells cannot even read; in-process is the
    MCP's proven model, and the root check closes its one gap.
    Revisit if the CLI and the backend are measured to disagree on a bank in practice, or for a server package (G181).

22. **G110 slice 1b rulings (owner, 2026-10-07).** **D1:** capture keeps up to ~16k characters of the person's FIRST
    message in a session (other turns keep the 2k clip), inside the session budget and with the same scrub, so a long role
    or objective can be continued; the Sleep cost is measured before shipping. **D2:** amends slice 1a's "no `.git`
    reading anywhere" for the hook alone: a bounded, read-only, fixed-command git identity observer may run harness-side
    and send plain values (repository root, worktree list); the backend never reads the person's folders and only parses
    what is supplied (amended by D2a below).
    **Requirement restated:** no handoff prompts; a fresh session in Claude Code, Codex, Cursor or another
    harness continues the role and the work (G110 row).
    **Why.** The owner's acceptance example is an orchestrator whose role came from a long first instruction and whose
    workers run in sibling worktrees; the 2k clip and exact-folder matching each break it.
    Revisit if the first-message exception is measured as a Sleep-cost or privacy problem.
    **D2a — a repository is recognised by its git remote, stored only as a hash (owner, 2026-10-29: "Yes, hashed
    only"; amends D2).** The hook — and only the hook — may add one read to D2's fixed pair:
    `git -c core.fsmonitor=false config --get remote.origin.url`, inside the pair's one 100 ms deadline, ≤ 4 KB, no
    shell, global/system config off. It normalises the URL (scheme, user, port, `.git`, case, ssh vs https: every
    spelling of one repository reads `host/org/repo`) and sends only `sha256(salt ∥ url)[:16]`, the salt 32 random hex
    characters made once per install (`$CICADA_HOME/remote-salt`, 0600, never followed through a symlink; no salt, no
    hash — never unsalted). The URL is never stored, logged, sent or shown; the hint cache keeps only the cwd hash and
    time; the backend never runs git and only validates the hash. It is the key wherever a repository's identity
    matters — as evidence of the same *repository*, never by itself of the same *project* or checkout (review of
    #558: a template cloned under a new name, an upstream-as-origin fork, two live clones). Continuity adopts another
    checkout at the same place in the remote only when this one began after it went quiet (renamed, moved, cloned
    again); clones active together are related choices. Only a repository's current remote counts (the one on its
    latest session). Project birth (`born.repo.remote`) joins the page with no judge only when the page points at
    that remote now and the folder name is the same; a different name or a remote the page only once had brings the
    page to the judge, told they share an origin, and "different" stands (coordinator's call on #558); activity and
    ties never follow a remote by itself, only the page's family and names (a judged rename adds its alias). Records written
    before keep matching by their path keys; no
    bank rewrite. Ruling 43's notes are recognised by their own bytes, not the remote: Claude Code names their folder
    after the checkout's path, so a moved notes folder is repointed in place and a copied one is no second episode.
    **Why.** Measured on scratch repositories (rename, move, re-clone under another URL spelling): before, the startup
    pointer found the earlier session 0/3 times and a renamed repository minted a second project page; after, 3/3 and
    one page. Hook p95 stays far inside the 100 ms bound (#558). A remote can be private, hence hash-only and salted.
    **Revisit** if a hash is ever found to identify a repository off this install, or the third read is measured
    pushing the hook past its deadline.

23. **Memory-quality rulings (owner, 2026-10-09).** **Engine:** Sleep runs on the owner's Claude plan with Haiku 5.5 for extraction and disambiguation, at concurrency 10 (Sonnet measured ~15 min per 25-conversation batch, Haiku ~9). **Skills (G112):** a Stage 4 skill needs two or more conversations, a one-conversation skill is held in `skill_hold`; skill pages whose sources cannot be traced are archived (44 on the owner bank); no contradiction check on skill updates; possessive aliases ("my mom") are kept, a reference phrase is never an alias. **Pages (G194):** summary synthesis is on for the owner's install — one bounded summary per page and paraphrase folding, its calls overlapped (#258); the rule-based fact fold drops a fact only when it **equals** one already kept after trivial normalization — never containment, never stopword or preposition stripping. **Search:** EmbeddingGemma 2 is downloaded only when the person asks, never automatically.
    **Why.** Two review rounds showed every containment rule dropped a fact that said something different ("works at X" inside "works at X's competitor", a from/to swap, "1,200" vs "200"); a duplicate is cheaper than a lost fact. Synthesis-on costs ~1,000–1,500 calls per full run (clean run: 742 page updates) and is the only place paraphrases fold. An automatic 585 MB download would be a new automatic network behaviour.
    Revisit the fold only with a measured loss-free paraphrase rule; synthesis if its call count per run is measured as a plan-limit problem.
24. **Pages, age, pictures and the CLI (owner, 2026-10-09 to 2026-10-13).** **Pages are articles (G194):** a lead and prose sections with no length cap, written for pages on 2+ conversations (amended 2026-10-17, owner: "uncap what the agents can write to" — also for a page on one conversation, a new page included, whose record holds `CICADA_PAGE_ARTICLE_MIN_MATERIAL` inputs; a stub below that stays the merge), over a record (Key Facts, History, Links, Open Questions, claims) that is unioned and never shortened; provenance per paragraph; an edited article is the person's. **Age counts from when it was said (G170 amended):** what the conversations prove silent is charged once, when read; a one-off may archive by age; a page or claim on 2+ dated conversations floors at 0.39 and only live silence archives it; a mention never lowers; a decay question only when live silence crosses 0.4. **Pictures (G159/G162):** Gravatar (the owner's hashed email) and GitHub for people, X and LinkedIn through unavatar.io behind their own default-off gate as the ToS rail's one exception — only from a link given as the person's own account; link-card icons only from the page's own tags; a YouTube still from its id when oEmbed gives none. **CLI (ruling 21a):** commands on state the backend owns go through its routes after `/healthz` confirms the root; person-only commands refuse from an agent's shell. **Web:** keep the door open — new features live behind the backend API, no browser front end yet.
    **Why.** Pages: rich pages had a median 26 facts and a 36-word summary because the merge prompt capped summaries at 1–3 sentences; the owner pointed at gbrain and Cognition's agent-memory repo — free prose, git as the safety net. Age: the owner's own reading ("if we track the time where i did that work, then it would be irrelevant now"); a straight age rule archived 79% of the bank (601/664 projects) in a dry run, so repeats floor. Pictures: the owner's own chain from another app, minus guessing. CLI: one implementation for the app, the CLI and a future browser front end; no second Sleep.
    Revisit articles if G148 measures a recall loss or the plan limit bites; the age floor if the owner reports losing things he needed (count revivals first); the unavatar exception if the provider changes terms or starts scraping behind a login for X.
    **Amended 2026-10-16 (owner: "Yes I agree with read on time then") — read on time.** A conversation read late (a newly connected source's history, an export imported later) counts as if Cicada had read it the day it was said: when a conversation is read never changes where a page or claim ends, only when it was said does. Before, one dated before a page's watermark added its source and week and moved nothing, so a page decay had lowered stayed faded although a newly connected chat had mentioned it three days ago. Now the decay pass places it (`read_late` → `conflict_resolver._revive_on_time`, `claim_reconciler._place_on_time`, one `decay_policy.on_time`): revived on its day (a page to 0.6, a claim to its restatement's confidence), less proven silence (repeat floor) up to the day the page's previous mention was read and live silence after it, through the watermark plus at most one pass (ruling 1); only raises; a lift left below 0.4 and heard late is `faded_by_age`. To keep it order-independent a live mention now raises any settled page to `max(current, 0.6)`, active pages included (G66 §1.6 had raised only decaying/archived ones), and a settled claim restated after its watermark but read days later is placed on the day it was said instead of restarting the day it was read. Existing banks: `api/scripts/recompute_read_on_time.py` (dry run by type, `--apply` one `cicada` commit). Revisit if the owner reports pages coming back he considers stale (count lifts by age of the mention first).
25. **Exploring saved sites (owner, 2026-10-14; G166, G196 open question 2).** **D1 storage (b):** one thumbnail per
    changed look in the bank, full images in `~/.cicada/captures/` outside git, kept and exportable with the bank;
    deliberate Looks keep their full image in the bank. **D2 browser context, amended by the owner:** "My signed-in
    sessions by default, but I can choose to disable this in Settings" — agents explore in the person's everyday
    signed-in Chrome session and every capture taken signed in is marked `signed_in: true`; the Settings switch (Reading
    the web) turns it off, and off is a private, cookie-less browser context (`Target.createBrowserContext`, verified
    drivable through browser-harness in a test Chrome; an agent that cannot open one hands the site back, never falls
    back to the signed-in session). Still binding: private workspaces excluded; walls and captchas recorded
    `needs_login`/`blocked`, never retried with different headers; consent banners never clicked or hidden; one agent per
    site, ≥ 8 s between pages. **D3 consent (a):** the reading acknowledgement is v3 with an exploring paragraph saying
    plainly that exploring uses the signed-in session by default and the person's accounts carry the terms-of-service
    risk, plus a per-site *Never explore*. **D4 depth (a):** a scripted capture of the viewport and metadata by default;
    Sleep's recon finds the relations; full page, mobile, dark and second pages only where the person's why (G191) asks.
    **D5 who starts (b):** the person's click, or a trusted local agent they asked in chat, stamped with who started it,
    shown at once and stoppable in one tap; never remote, never from an agent's shell. **D6 change detection (a):**
    Cicada's own fetcher may check an explored public page at most monthly on the Sleep tail, under the connector gate
    and the ToS rail, and only marks "may have changed" — slice 3.
    **Why.** The design (2026-10-14) measured ~1 GB of images a first pass of 1,000 sites, which in git would grow
    forever (ruling 3's failure); the owner wants his logged-in view of the sites he saved, accepting the account risk
    in words he signs.
    Revisit D2's default if a capture taken signed in is found to have kept another person's private data in a bank; D1
    if exported banks are measured to miss the full images people want.
26. **Tracked sources: update, dated; the newest evidence wins (owner, 2026-10-14 evening; G61, amends the S3 rail).**
    Owner: "Marking a dead site and being able to recheck a website after a certain time to see any updates … If I have
    the LinkedIn of a person … I know that through LinkedIn I'm going to get it … being able to update these things
    through consolidation would be nice." **What is re-checked:** a source the person added or took, or one Cicada's
    own read confirmed (the existing trust rule), monthly by default (a per-source cadence) or when the person asks.
    **What a re-check produces:** a new dated fact with the page and the capture date as evidence; the old fact's
    validity closes (bi-temporal, nothing deleted); provenance is the agent or Cicada, the source, the date. **The newest
    evidence wins, even over the person's own words** (owner amendment, same evening: "it can override something I
    said if it has evidence, there is no problem with that"): a re-check dated after the person's statement supersedes
    it and the statement stays as history; a statement dated after the capture stands; only a clash with no clear order
    (the same day, or an undated statement) becomes one inbox question with both sides and their dates; nothing changes
    silently (the page and the timeline say what changed, from where and when; git reverts it). **Dead:** "gone" needs
    two failed visits a week apart (not found, gone, parked, moved); marked dead with the date, the last good capture
    kept. **Who checks:** public pages, Cicada's own fetcher on the Sleep tail under the connector gate and the ToS rail;
    login-walled sources only the person's own agent, through an explore-style queue, in the signed-in session per
    ruling 25 D2 and its switch — Cicada never fetches them. **Ruling 4 holds:** due checks are only listed; the agent
    works them when the person asks or when the hook's one line ("N tracked sources are due for a check") leads them to.
    The inbox check (G61 S3) is unchanged: it still settles nothing.
    **Why.** The owner tracks facts that change at their source (positions, roles) and wants memory to follow them
    without maintenance; the S3 rail had been written for a check proposing an answer to an open question, where a
    planted source could steer a belief — a dated re-check of a source the person chose is evidence he accepts.
    Revisit if a re-check is found to have overwritten a statement the person had to restore (count the divergence
    answers and `git revert`s of `Source refresh` / re-check commits first), or if a site's terms change for the walled
    family.
27. **A web lookup settles questions about public things (owner, 2026-10-16; G61, amends the S3 rail).** Owner: "A web
    lookup answers 'what is X' for public things and closes the question. The answer is saved with its link and quote,
    and you can undo it from a 'Settled by a check' list. Never searched: people's names, your own files, your projects,
    your life. Runs from your Claude plan in runs you start; a scheduled metered run costs a few cents more." Refinement,
    same day: the answer carries a citation (the URL and the short quote, shown where the claim's evidence shows) but is
    **not** a tracked source — it never joins the page's re-check set, never makes a site trusted, never drives a logo;
    the person may promote it with one tap. **What:** a pending conflict or clarification about a work, product, tool,
    company, public concept or paper; never a person (typed, an untyped name whose description says so, a person's name
    or alias), the owner's page, a file or path, a project, anything only the conversations know; when in doubt, the
    question stays. **What leaves the machine:** the subject's name plus generic category words — never conversation
    text, never another name from the bank, never the person's name. **Who:** Sleep's tail on a run the person started,
    with the Claude plan's own search as the call's one tool (ruling 4: a scheduled run never uses a plan); a metered
    engine's own search at its price, priced in Past reads (ruling 12); `CICADA_ALLOW_CONNECTOR_FETCH` gates it; the
    person's own agent through `cicada_record_check(outcome="settles")`; questions about whether a PR or a G row merged
    are answered from the commit by a trusted local agent, never searched. **Settling:** a claim (observer the agent,
    the citation as its evidence), the question resolved and listed under "Settled by a check" with one-tap undo that
    takes back only what the check wrote (and marks the question so no check settles it again). The S3 rule stays true
    for everything else: an inbox check on any other question still settles nothing. **What a thing is** (owner, same
    day, his own example "Is <tool-a> an agent harness or an AI agent itself?"): a type/`is-a` conflict is eligible
    though `is-a` is multi-valued; it settles on one option only when the cited page rules the others out, on the
    item's own "both" option when the page supports both, and never on an option Cicada invents.
    **Why.** About 60 of 126 open conflicts and clarifications on the owner's bank (2026-10-16) asked about public
    things a lookup answers, and the person was asked to look them up by hand.
    Revisit if an undo count on `web_check` rows (ids only) shows settles being taken back often, or if a settle is
    found to have searched or written something personal.
    **27a — local context (owner, 2026-10-16: "Yes, use local context").** The model may read what Cicada already
    knows about the subject — its page's one-line description and up to two lines where it was mentioned (the item's
    conversation, its option claims' evidence), ≤ 600 characters, scrubbed as every writer scrubs, people's names,
    links, addresses, handles and paths taken out (`web_settle.local_context`) — **to judge which search result is the
    right one**. The search query stays the subject's name plus at most ONE generic category word, checked word for
    word (any other query settles nothing); the word comes from Cicada's own description, never from the page's type
    alone, never on a question about what the thing is, never one an option label carries — a bare name when unsure.
    Clarifications are looked up before conflicts; conflicts with a mention line before those without. **Why.** The
    first person-started run looked up 8 questions: 8 searched the pinned query, 0 settled, all unsure; a replay with no
    writes found 69 eligible (31 type conflicts, 1 other conflict, 37 clarifications), three clarifications replayed
    all unsure. The model saw only a name that also belongs to a restaurant, a town or a product, often with a wrong
    category word, and was right to be unsure; only the person's context says which thing was meant. The same engine
    already reads those conversations during Sleep, so the prompt sends nothing new anywhere and what reaches the
    search provider is unchanged. Measure with `api/scripts/web_check_dry_run.py` (counts only, writes nothing).
    Revisit if the dry run on the owner's bank still settles none, or if a prompt is found to have carried a person's
    name or a path.
    **27b — the inbox is not for what a search answers (owner, 2026-10-19): "Questions like 'Is <a public tool> an AI
    agent or an AI code editor?' can be solved by an internet search. That's not what the inbox is for."** The lookup is
    the default path for a clarification or conflict about a public thing in every Sleep run on a plan — the person's
    and, with 4c, the scheduled one — and the backlog already open gets a one-off sweep the person starts
    (`POST /inbox/web-check`, dry run by default; `api/scripts/web_check_dry_run.py` for counts with no write): same
    eligibility, pinned query, local context, citation and "Settled by a check" undo; each settle under the bank's write
    admission with its own commit; a plan limit stops it. A search that cannot settle a question confidently leaves it
    exactly as it was. Stage 1's way of naming the speaker ("the user mentioned it") no longer reads as a person cue,
    and a description saying the subject is the speaker's own (built by the user, the user's project) now keeps it home.
    **Cicada's own settings are never asked:** a conflict or clarification on Cicada's own page (exact id) about its
    runtime settings — which engine its Sleep runs read with (a plan, an API key, a local model), whether scheduled runs
    use the plan, the schedule's time — is retired by rule, nothing else touched (`inbox_tend`'s `own_settings`, undoable under
    "Settled by Sleep") and never searched — the system knows its settings and Settings shows them, and a conversation
    that mentioned them stated that day's configuration, not a fact for the person to referee (never "answered from the
    system": writing today's config as a claim would date a past statement wrongly). Narrow on purpose (review of #360):
    the owner's project IS Cicada, so its design questions (a hosting provider, a page's layout, the search or graph
    engine, whether Sleep runs nightly) stay his; and the speaker's own thing in the active voice ("an app the person
    is building", "the company where the person works") stays home too. Revisit if the sweep's dry run on
    the owner's bank settles under a quarter of what it looks up, or if an own-settings dismissal is undone.
28. **Headless clients (owner, 2026-10-16; G181 phase 2, amends the transcript rail and ruling 21a).** **1 — Per-device
    tokens.** A second device never gets the server's master token: each gets its own named, hashed, revocable token
    (`device_tokens`, the G135 store's shape kept apart). Issuing one is an act of the person — `cicada device add` on
    the server or `POST /devices` with the master token — never automatic, never by an installer, never by a device
    token. **2 — The transcript rail, amended.** A harness session is read on the machine where it lives, by Cicada's
    own extractor, and posted as scrubbed, capped turns (`POST /capture/session`); ids are minted on the server under
    its lock, so one episode per session (G104) holds. The backend still never opens a path a remote client names;
    same scrub, caps, G110 markers and demo rule, re-checked on arrival. **3 — A tailnet device counts as local for
    the G198 trust list.** A trusted harness (Claude Code by default) on a device holding a token the person issued
    edits pages at once, exactly as on the same machine; the G135 remote connector and the `agent` author stay off the
    list. **How the server knows (worker's decision, 2026-10-16):** from the token alone — `auth.require_token` looks
    the bearer up and records the device on `request.state.device`; the tool door runs the call as a local stdio call
    (no `connector_id`), and the device id is written as `device:` on what it writes. Nothing a client puts in a header
    or body can claim a device, because a claim is not evidence and the token already is. **21a, amended:** the CLI
    compares a bank identity (an `id` per bank in `banks.yaml`, minted by the backend), not a path; a client pins the
    server's bank by name and id and names both on every write.
    **Why.** The owner wants a home server holding the bank with Sleep running uninterrupted and the Mac as a client
    (research `2026-10-15-headless-server.md`, option C); a copied master token could not be revoked per device, a
    path posted across machines cannot be opened, and a path compared across machines means nothing.
    Revisit 2 if a client's extractor is found to have sent something the server-side extractor would not keep (the
    `turn_over_cap` refusals in the capture ledger are the signal); 3 if a device token is found in the hands of
    anything but the person's own machine.
    **Phase 3 (worker's decisions, 2026-10-16):** a device token may READ `GET /devices` (ids, names, times, and
    `current` for the asker) so the app on any of the person's devices can show them; issuing and revoking stay the
    master token's (1 unchanged). The device a request came from is bound for the request (`device_context`) and
    stamped on every new episode it causes, except Sleep's run, which clears it. The app's server setting is a file the
    hooks read too (`$CICADA_HOME/api_base`), so one switch moves the whole Mac; `CICADA_API_BASE` still wins.
    Review (2026-10-16): the click writes `api_base.next`, moved into place at the next launch, so the agents never
    switch before the app; a background service is stopped on a server (plist kept); a reader's newer post never
    overtakes a waiting one on its route; provenance and Reader ETags carry `device1`.
29. **Sleep tends the inbox: questions get answered as conversations come in, the small stuff is assumed (owner,
    2026-10-17; amends G21, G113 and the "Clarification queue over silent drops" decision).** Owner: "a single
    consolidation also should take care of cleaning up the inbox. … I think it was part of my thesis also that sleep
    would also take into account the inbox so that, as conversations come through, questions get answered. There are
    also many things that maybe can be assumed, like they don't have to be explicit, and I think a lot of cleanup can
    happen in the inbox for actually necessary stuff for the user. There are little things that are honestly not that
    big of a deal." And: "We can do everything with my Claude plan." **1 — Answered in conversation.** Every batch, for
    the open conflicts, clarifications and duplicate questions its conversations are about (the ask gate's rule, over
    the person's own turns), the engine reads the person's lines and copies the words that answer one; a question is
    settled only when those words are found exactly in one of the person's own turns (spans, never a guess, never an
    agent's words); the conversation that raised a question never answers it. **2 — The small stuff is assumed**, once
    per drain and by the one-time tidy: a question whose subject is gone; a duplicate with the same name once spelling
    is folded, or one the judge reads as the same (≥ 0.9, both pages, same type) or as different; a predicate fold
    that only respells a label; a decay question on a one-off nobody would miss (a concept, tool, media or company page
    on one conversation, never kept, no words of the person's on it); a conflict the newest dated statement settles
    (never a machine claim over the person's own); a conflict on a multi-valued predicate (every value already kept).
    **The judges (owner, same day, after the first dry run on his bank: "the inbox keeps only what genuinely needs the
    person"):** behind `judge=true` / once per drain, the person's chosen engine (plan included) also reads conflicts
    (each option's dates and evidence lines; one clearly better supported or newer, never a machine claim over the
    person's own), label folds (same meaning folds; a changed meaning stays) and fading concept/tool/media/company pages
    (still live → only marked active: no mention dated today, no claim reopened, no confidence lifted; clearly passing →
    archived); each judged settle shows the
    judge's one-line reason. **Never assumed:** who a person is or merging two people (only the
    person's own words on the record), a proposed page edit, a follow-up (only the person's own words, part 2), anything a rule cannot read — those stay.
    **One writer:** the person's own resolvers, committed as Sleep's (`Inbox settled by Sleep`, `inbox/<kind>/settled:`,
    never `resolved:`), each undoable under "Settled by Sleep" (the reverse of its commit, three-way, refused whole when
    something since overlaps); an undone question is never settled by Sleep again. The G113 ledger keeps Sleep's settles
    and the person's undos apart from the person's verdicts (`sleepSettles`). **Engine:** the batch's own (ruling 4
    unchanged); the tidy uses the person's chosen engine, their Claude plan included; a plan limit pauses, never fails.
    **Review (same day):** a "same" on two existing pages folds the duplicate's page into the target (undo brings it
    back); each question is decided and settled at once and only while every page it read is unchanged, under the page
    lock. Re-review: a claim resting on the person's own words (their inbox answer or a span in their own turn) is closed
    only by one that does too or by a tracked source's dated re-check (ruling 26).
    **Part 2 (owner, same day: "a lot of cleanup can happen in the inbox for actually necessary stuff for the user"):**
    a label-only conflict (no option carries a claim) is judged through the page's open claims its labels are tied to by
    folded words (never fuzzy; a side nothing on the record states is never picked; the owner's-words rail holds over
    the tied claims). A page-bound question whose page is gone retires (`subject_gone`); one whose page cannot be parsed
    never does. **Move 3 — answered already, anywhere in the record:** a clarification, follow-up or conflict still
    open is looked for across the whole bank (the page's own pointers plus the lexical index by its spellings), settled
    only on the person's own words located exactly in one of their turns (kind `user`, never an agent's, never fuzzy),
    recorded as the evidence span; a conflict only by words said after every side of it, a follow-up only after its
    thread was last heard and only done/still/stopped (or done/missed/dropped), dated the day it was said. Sleep: 4 per
    drain; the tidy: all, behind `judge=true`.
    **Part 3 (owner, same day: "little things that are honestly not that big of a deal"):** a clarification about a
    name with no page, said in one conversation and only in passing there (≤ 2 exchanges name it), with nothing tying
    it to the person's life, closes as mentioned in passing (`in_passing`: the person's own dismiss; nothing written
    about who it is; it may be asked again when another conversation names it); a code identifier however often it is
    named. Never a relation question, a project/skill/deadline, a person said in any of the person's own turns
    (review: a relation a sentence away, a dropped Spanish pronoun, or none at all — their words mean the person may
    be in their life), a relation word or (for a company or place) first-person words in the naming turn or the turns
    beside it, a name on the owner's page or from a Messages chat. A label-only
    conflict is settled by the person's newest words (`newest_words`): their newest plain statement of one side (the
    sentence names the subject; no negation, modal or avoidance, read on the raw text), newer
    than any line or belief for another side and with an older one on record, located exactly in their own turn,
    dated that day; when not mechanical the conflict judge reads those lines and may rest its pick on one, under the
    same guards. Measured (owner's bank after #338, counts only): 59 of 69 clarifications asked with nothing on the
    record, almost all names said once in passing; 40 of 58 conflicts `labels_not_on_record`.
    **Why.** On the owner's bank (2026-10-17, counts only): 913 pending question files and 0 answered — 661 duplicate
    questions, 70 conflicts, 69 clarifications, 63 decay, 46 predicate folds, 3 proposed edits, 1 follow-up — served as
    239 rows after grouping, over 4,693 pages (2,221 archived, 823 decaying, 1,649 active). The first engine-free dry
    run (no judge): 692 of 913 settled (660 dead duplicate questions), 221 still asked — the judges are for those. UX principle 1, "never
    require memory maintenance", was broken by the inbox itself. Measure with `api/scripts/inbox_tidy_dry_run.py --bank
    <path> [--judge]` (counts only, writes nothing). Revisit a rule if `GET /consumption/feedback`'s `sleepSettles`
    shows the person undoing it often, or at once if a settle is found to have decided who a person is without their
    own words.
30. **Watch history and export saves are indexed, not consolidated (owner, 2026-10-18; G71, G94).** Owner: "maybe
    overanalyzing the watch history is too much … Maybe just have it there and then maybe the metadata has it as
    embeddings or something." **1 — A record to look up.** A watched day, a month's summary of them and a save from a
    platform's saved list (a Takeout playlist and Watch later through any door, Instagram saves and likes, TikTok likes
    and favourites, an X archive's likes and bookmarks, Reddit's and LinkedIn's export CSVs) are never read by a model:
    captured already read (`processed_by: index`), retired by Sleep before a drain freezes when an older bank queued
    them, and excluded from every "waiting for Sleep" count (`history_index.waits_for_model`). They stay files — saves
    in Saved with their metadata — found through the lexical and vector indexes, recall's excerpts, Ask's read of the
    record and the timeline's count. A browser bookmark, a single URL save, a connector poll and any save carrying
    the person's own note are read by Sleep as before. **2 — The signal is counted, not read:** one summary per
    platform per month (the channels watched most, the ones come back to across weeks, the videos watched on more than
    one day, each day's count), deterministic and order-free. **3 — A watched day is not a mention:** history never
    writes a page (no claim, no source episode, no date, no lift, no page minted, no inbox question) and never touches
    decay — a watch is a record the platform kept, not the person's words (the memory-export precedent), often autoplay,
    and at 45k watches would hold every same-named page at the repeat floor for good; a page named like a channel gets
    one derived line at read instead. **Proposed, not built:** a playlist the person named themselves (not Watch later,
    not Liked videos) as a light interest signal — its name and size in the month summary or one line on the owner's
    page, still with no per-video model read. **Why.** On the owner's bank (counts only): 45,879 watches → 2,532 day
    episodes, 3,156 playlist saves (31 playlists; Watch later 1,415), 2,444 → 5,094 episode files, 5,692 queued for a
    full Stage-1 read each. Measure with `api/.venv/bin/python -m api.scripts.history_index_dry_run --bank <path>`
    (counts only, writes nothing). Revisit if the person asks for a playlist or a stretch of history to be read, or if
    the month summaries prove too thin to answer "what was I into then" — then a bounded, opt-in read of a summary,
    never of every day.
31. **Plan-first engines: never a metered key by itself (owner, 2026-10-19): "OpenRouter, eliminate it as the default.
    Just have it as an option but the defaults now are either the Claude plan or the Codex/ChatGPT plan."** The shipped
    `llm_mode` is `auto`: the Claude plan, else the ChatGPT plan, else a running local model — and **no engine** rather
    than an API key nobody chose (`engine_select.NO_ENGINE`; a resolved copy carries `no_engine_reason`, and every call
    built from it refuses before anything is sent, `providers.resolve_llm_fn`; so does a call from an Auto nobody
    resolved, whose engine label reads `auto`, never the metered engine). A run with no engine stops before Stage 1
    and says so with the fix; Ask says it has no engine; a schedule says so (`no_engine`). An API key (OpenRouter or any
    other) reads only when the person chose it — `CICADA_LLM_MODE=byok` or the picker — and stays one tap away. A plan
    the person chose, on a schedule their switch closes, has no engine rather than falling to the key. No install script,
    onboarding step or Auto rung picks a metered key. **Why.** The owner's scheduled runs had been reading on a metered
    model he never meant as the default while his plan sat idle, and their web lookups were skipped for it.
    Revisit if a person with only a key is found stuck because nothing told them to choose it.
32. **Phone and web apps sign in, and conversations there are captured as they happen (owner, 2026-10-19; G135,
    amends G105 for hookless apps and the headless "never funnel" line).** **1 — Sign-in.** claude.ai (web, desktop and
    its iOS/Android apps) and ChatGPT add Cicada as a custom connector through OAuth: the G135 listener is its own
    authorization server (DCR or a Client ID Metadata Document, PKCE S256, short-lived access and rotating refresh
    tokens that map to the existing hashed, scoped, expiring, revocable connector rows). The person runs a public
    tunnel with a stable hostname (Tailscale Funnel or ngrok) **to the G135 listener only** — its port serves MCP and
    sign-in and nothing else; the backend's own port is never funnelled, and Cicada never starts a tunnel. **Consent
    happens in the Cicada app on the Mac** (or the local API on a server), never by a password on the public page: the
    public page shows a short code and waits, and the person approves by **typing that code** — never by clicking a
    listed request, and a self-registered app is never named or branded by what it claims (security review of #359:
    the flow's initiator collects the result, so a click-to-approve list let a stranger's look-alike through). The secret-link door keeps working; the docs steer to sign-in, because a
    link is a credential in a URL. **2 — Real-time capture is the usual; exports are a starter seed.** Owner: "Exports
    should only be a starter seed for users; the usual should always be real-time captures." For apps with no hook,
    the connector's contract asks the app's model to call `cicada_capture_turns` every turn with the person's message
    verbatim and its own previous reply — the one capture that depends on a model calling a tool, taken knowingly
    because those apps offer no hook. **Default until the owner says otherwise (coordinator, 2026-10-19):** relayed
    words are that conversation's episode with its channel disclosed (`relay`), but are **not** counted as the person's
    own words — not for promotion's own-words rung, not for ruling 29's settling — because a model can paraphrase; a
    later export import of the same conversation de-duplicates against it and upgrades it in place. **Revisit** when
    the owner rules on whether relayed words may count as his (trigger: a measured paraphrase rate on real relays), or
    when an app ships a hook or a conversation id Cicada can key on instead of the first message.
33. **Contacts as a seed, and imported-only pages that stay quiet (owner, 2026-10-20; G154, amends the promotion rail).**
    **1 — Cards wait, and a card is matched on mention.** Never one page per card. Every card that matches no page waits
    outside every bank, in the people directory LinkedIn connections already use (`$CICADA_HOME/people/<bank>/`,
    `people_directory`), with only what G154 posts (names, which facts the card holds, a thumbnail); every sync
    rewrites the set, deletions included, and the bank gets nothing for a waiting card. The first time a conversation
    names that person in full (given + family, either order, folded) or by an alias, and exactly one card carries the
    name, that alone promotes the mention, and the page is born with the card's name, photo and G61 sources. Never a
    one-part name, a name two cards or two pages share, a relation-only person (`role_people`), or the person's own
    card: the "me" card belongs to the owner's page (G169) and never waits. Sleep's tail matches the cards still
    waiting against pages born later, as LinkedIn does. **2 — Pages that exist only because of an import (saved
    videos, playlists, saved links) are dimmed until the person mentions them.** The first mention lights the page; a
    quiet page is never asked about in the inbox. The rule chosen (`quiet_pages`): import evidence on the page itself
    (its `media:` block, or a save or watch among its own episodes) and no conversation evidence (no other episode
    among its own or its claims', no claim citing a person's own words); Cicada's own checks count for neither; the
    owner's page never. Derived on every read, never stored, so the first mention ends it with nothing to write. Demo
    bank: 74 pages, 7 with import evidence, 6 quiet (the seventh is the saved guide the demo person talked about).
    Decay is unchanged (classes, rulings 1 and 30). **3 — The notes field: not now.** Nothing new is read from a card
    beyond what G154 reads. **Revisit** the quiet rule if a measured bank shows imported pages the person did talk
    about staying quiet (the trigger: a page whose conversation Sleep read but did not credit to the page).
34. **The video queue's lease findings, and which day an episode id carries (acting owner under the owner's standing
    go, 2026-10-22; G162, the 2026-10-22 Hyrum audit A5).** #399 model-checked the lease lifecycle and left four
    findings with strict-xfail repros (`api/tests/test_video_queue_formal.py`) and the decisions to the owner. Taken
    as recommended: **F1 — a per-claim lease token.** `cicada_video_claim` hands each leased row a token; a release or
    record ends a lease only with that row's token. Comparing session ids was model-checked and rejected (`F1s-*`): a
    shared id lets one conversation release another's lease, and a caller with no stable id (the CLI, remote
    connectors, other stdio harnesses) or a new id after a restart could never hand back its own (P13). A tokenless
    release answers `not_yours` and the lease lapses on its own clock. This also closes **F5** (two remote
    conversations sharing one session id). It changes the release contract, so the tool description and `mcp.md` say
    it in the same PR. **F2 — a bug; fix it.** A stale saved snapshot must never drop a queued row (it is data loss,
    however narrow the window). **F3 — accept.** A record written in the 0.1–3 s before the person queued the same
    video does meet the request; take the microsecond `requested_at` only if a lease is ever seen ending because of it.
    **F4 — cap a lease at three lease periods from its first claim.** A session that keeps calling no longer holds a
    video forever; the cap is a constant beside `LEASE_MINUTES`. **A5 — an episode id carries the conversation's
    local day** (the person's zone at the conversation's first turn), the rule every writer but the two hook writers
    (`transcript_capture`, `telegram_capture`) already follows. Why: ruling "read on time" (2026-10-16) counts a
    conversation as read the day it was said, and the person says days in their own zone; a UTC id dated words said on
    the local 22nd as the 21st. Existing ids are never renamed; the two readers that take the day from the id
    (`ask_sources`, `benchmarks/hard_questions`) read the episode's `timestamp` in the person's zone instead.
    **Revisit** F3 if a lease is seen ending on an older record; A5 if a person who travels across zones finds a day
    split wrong (the trigger for storing the zone on the episode). **Follow-up (#403, 2026-10-22):** the ids and the two
    id readers follow this; Sleep's own dating still takes a conversation's day from the first ten characters of its UTC
    timestamp (`source_dates.episode_day`, used by `entity_extractor`), so words said just after local midnight are
    still dated a day early there — the same rule applies to it — and the remote connector's relay
    (`cicada_capture_turns`) posts no offset, so its ids take the server's zone. **Done (2026-10-22, `fix/sleep-local-day`):**
    Sleep dates through `source_dates.episode_day` / `episode_ids.local_day`; a relayed turn from ChatGPT takes the
    `timezone` its `_meta` hint carries; claude.ai sends none, so its relayed ids keep the server's zone.
35. **The skill lifecycle: candidates in Cicada, a small proven set in the harness, retired when the model catches up
    (owner question 2026-10-22, decided by the acting owner under the standing go; G112, G201).** The owner's worry:
    "as Claude Code and the models improve, a skill that once patched a gap starts pulling agents back to outdated
    behavior … the model absorbs what the harness used to patch, and the patch should then be deleted." The proposed
    shape is adopted with five amendments. **1 — Three stages.** *Candidate*: lives only in Cicada (`skill_hold`, skill
    pages, agent drafts) with the conversations it came from; never in a harness folder. *Promoted*: in the owner's
    skills repo with an `evals/` folder (skill-creator's layout, runnable with `claude plugin eval`), installed through
    the Skills page pinned to a commit (the existing consent rail). *Retired*: uninstalled from every harness; it stays
    in the repo's history and in Cicada with the evidence that retired it, never deleted. **2 — The promotion gate**
    is the skill's evals beating the no-skill baseline on the model the harness runs today, by more than the
    run-to-run spread over at least three runs each — the owner eval moved ±4 of 60 between identical runs (#370), so
    one run proves nothing. **3 — Proven-on.** Each promoted skill records the model id and Claude Code version it was
    proven on in a sidecar beside its evals (`evals/proven.json`), not in `SKILL.md`, which stays portable. When
    either changes, Cicada reruns that skill's evals with and without it (scheduled, on the plan per ruling 4c, one
    batch per change); if the baseline is now within the spread of the skill, the inbox asks to retire it, one tap,
    undoable. Never retired without the person. **4 — The usage signal** comes from the harness, not the model (amends the capture rail and ruling 11; the
    implementing PR adds the rail line to CLAUDE.md): the Stop hook already keeps each agent turn's model and effort
    (ruling 11); it also keeps the names of skills that
    turn invoked — names only, no arguments or output — and the telemetry ledger counts fires (ids and enums only). A
    promoted skill unfired for 8 weeks gets a retire suggestion; a "keep" answer counts like a decay keep (`kept_on`),
    so a rarely needed but critical skill (a release procedure) is asked once, not every week. **5 — Two kinds.**
    Sleep tags a candidate `about-you` (the person's preferences, people, projects, their own workflows — what Cicada
    is uniquely placed to know) or `generic` (how-to-code corrections, which models absorb fastest); the person can flip
    it. A generic skill expires by default: it must re-pass its gate at each model change, and is proposed for
    retirement 90 days after its last proof. About-you skills never expire by age; only usage or the person retires
    them. **6 — A small installed set.** The Skills page shows the installed set's weight (descriptions' tokens loaded
    every session) and asks before a promotion that takes the set past 12 per harness; by Hyrum's Law every installed
    skill becomes behaviour agents lean on. **Also:** Cicada's skills inventory must see Claude Code plugins (their
    skills and versions, read-only from the plugins' own manifests) before it can reason about the real harness —
    the first slice of G201. **Revisit** the 8-week and 90-day figures after the first two model changes with the
    sidecar in place; the cap of 12 if the owner's proven set outgrows it with evals still winning.
36. **The redesign: three nouns, the person's own engine, a quick read after each conversation, more doors for agents
    (owner, 2026-10-22; answers D1–D6 to the acting owner's redesign proposal, plus extra answers; amends ruling 31, the
    capture rail "No LLM at capture time", the default of the 2026-10-09 person's-photo exception, and the G135
    listener's "serves only MCP"; G217, G50, G61,
    G91, G135, G139, G141, G166, G205–G213, G216).** The proposal (kept outside the repo, with its six research
    reports: plans and keys, harnesses, the app inventory, memory quality, agents/API/phone, Supermemory) organised
    everything that connects to Cicada as three nouns — **Sources** feed it, **Intelligence** consolidates it,
    **Agents** read and write it — and put six decisions first. The owner answered each; the answers are binding as
    below. Measurements quoted here were taken read-only on the owner's bank or on scratch and demo banks, and each
    row named carries its own basis. **Ids:** the redesign's worker briefs cited G204 for the connection model, but
    G204 was already taken on `dev` (#416's `cicada_write_claim` finding), so the connection model is **G217**;
    G208, G211, G214 and G215 fold into the rows that already held them (G61, G141, G91 + G135, G50) and stay as
    redirects, so every id the briefs cite resolves.
    **D1 — Intelligence: a key secured properly, or the person's own Claude Code or Codex, their choice; a local model
    is never a default (amends ruling 31).** Owner: "local ai is unrealistic for most people. Lets be realistic. Yes
    bringing your own key would work and we can give that option and we have to secure it properly, but also lets let
    them use claude code and codex if they want. Also if possible look into grok subscriptions (spacexai)." And:
    "stop pushing Ollama … maybe later try a super small one and measure." **What changes:** ruling 31's Auto ladder
    ends at "a running local model"; that rung goes — a local model runs only when the person picks it. An API key is a
    first-class path, equal to a plan in onboarding and Settings → Intelligence, verified before it is saved, and held
    "properly" (today a 0600 `~/.cicada/secrets.env`; the secure store is G50's open item). Added keys: the OpenAI
    platform key, and Gemini or Google Vertex once the difference is verified (G50). **What stays:** ruling 31's core —
    no metered key nobody chose; a key reads only when chosen; `engine_select.SUBSCRIPTION_MODES` the one guard.
    **What a new install starts on (owner, 2026-10-22, answering the review of #420):** with nothing chosen, Auto uses
    the person's plan if they are signed in — Claude Code, then Codex — so ruling 31's plan-first Auto stays, minus the
    local rung; onboarding offers an API key as an equal option, and because Anthropic's terms leave the plan a grey
    zone, that step says in words what will run. **Ruling 4c stays** (owner, same answer): scheduled runs may use the
    plan, on by default for new installs too. **Why a plan is offered, and said in words.** Anthropic's legal and compliance page (code.claude.com/docs/en/legal-and-compliance, fetched
    2026-10-22) says developers building products "should use API key authentication" and may not "route requests
    through Free, Pro, or Max plan credentials on behalf of their users", and also that nothing prevents "an end user
    from signing in to the unmodified Claude Code binary with their own Claude subscription". Cicada spawns the
    person's own unmodified `claude`, never sees or stores its token, and bills the person's own limits — between the
    two sentences; saying in words what runs, beside an equally easy key, means the person knows the choice and a
    block strands nobody. OpenAI documents "Sign in with ChatGPT" for Codex and access tokens "for trusted scripts,
    schedulers", so the Codex path is the friendlier of the two. **Grok (xAI) subscriptions:** RESEARCH — nothing is
    built until a documented way for a person's own subscription to run an unattended job exists. Revisit if Anthropic
    or OpenAI changes those terms, or if a person with only a plan is blocked.
    **D2 — A quick read right after a conversation ends; on by default when it measures better, no setting (amends
    the capture rail "No LLM at capture time").** Owner: "i agree with recommended but that opt-in should be the
    default if provides better performance and no need to have this as something that can be changed on settings."
    **Capture stays file I/O:** the hook, `/capture/*` and every capture writer keep calling no model and return as
    fast as today. **Step 0 (no rail change):** a new conversation is searchable and recallable as soon as it lands —
    its vectors embedded off the capture path through the existing worker (never during Sleep), its words already in
    the FTS index, its excerpts in recall labelled "not yet read by Sleep". Measured: recall's excerpt leg is
    vector-only and a new episode has 0 vector chunks before Sleep, so recall cannot see today's conversations at all
    (`mcp_tools._leann_search_episodes`, `sleep_cycle.py:2299`). **Step 1 (the amendment):** a separate job, after a
    conversation ends, reads it once with a small model and writes **provisional** claims that Sleep later confirms or
    drops; nothing it writes is the person's own words or settles an inbox question. It ships **on by default only if
    it measures better** than Sleep alone on the bar G207 sets (recall and Ask on the verify banks, and Sleep's confirm
    rate of the provisional claims); if it does not, it does not ship — there is no switch either way. Cost basis: Sleep
    makes about 15 model calls per conversation (measured 2026-10-21); the quick read is one call, about 6k tokens in
    and 1k out under Cicada's caps — about 1¢ per conversation on a key at $1/$5 per million (an assumed small-model
    price, to be checked), and plan usage on a plan. **On a plan it follows ruling 4c's switch** like a scheduled run,
    since nobody started it (owner, 2026-10-22, answering the review of #420).
    **D3 — Agents: the featured nine, the popular second tier, the personal agents, and an HTTP API for agents that
    cannot use MCP.** Owner: "yes go with recommended but also keep the actual popular ones. There is a lot of movement
    in the personal agent space like muse, grokbot, instinct, dots (openai), i would lean into these too." With a
    screenshot of a texted agent answering that it cannot plug into MCP directly but could work with an API or a web
    app: "so maybe a call to work on the api. Also the cli setup should be cool, kind of those like the vercel ones."
    **Tier 1** (logo, setup prompt, live detection) stays the existing nine (`agent_live.FEATURED`). **Tier 2** (logo,
    the generic setup prompt, detection by `clientInfo`): VS Code/Copilot, Gemini/Antigravity CLI, Zed, Cline, Goose,
    Windsurf (now Devin Desktop), Kiro, Warp, Amp. **Personal agents** reach Cicada through three doors, never one
    integration each: the G135 connector (Grok Bot, Poke, the Claude, ChatGPT and Gemini apps, Meta's Muse by URL, OpenAI's Dots through the ChatGPT connector),
    the HTTP API (agents that only speak HTTP), and Messages (a texted agent, G179). Product facts for these are
    reported by press and vendor blogs, not first-party docs, and are re-checked before any copy ships. **The HTTP
    API (G213)** is a thin mirror of the bodies `/tools/call` already runs, with OpenAPI and an `llms.txt`, authorised
    by a G135 connector token with its scopes and provenance (a remote claim is never the person's own words). **It rides
    the G135 listener, behind the same tokens** (owner, 2026-10-22, answering the review of #420) — this amends the
    remote-connector rail's "serves only MCP": cloud agents reach only a public URL, and the listener is the one door
    the person may make public. The G213 PR changes that rail line in CLAUDE.md. **The CLI** gains a Vercel-style
    `cicada setup` (detect, confirm, a checklist, a non-TTY path) with `rich` and `questionary` as dependencies,
    approved by the owner the same day (G213).
    **D4 — A project is born from a repository, or from the person's own words.** Owner: "agree with the recommended.
    Projects tho can as you say be started from just me talking to claude about something that spans outside software
    only, so its able to track knowledge on it over the different conversations and stuff. … Design stuff can be
    exposed in these markdowns as well and what changes a bit is also the interface, of what is exposed, timeline,
    what has been done, what is expected and sections that can be standard throughout projects in general. People that
    somehow can be involved to projects will be linked to them and such." A project page is born from a repository the
    person works in with an agent (the git remote the hook already observes, G110 D2) or when the person says, in any
    conversation, software or not, that something is a project. Consolidation alone never mints one. Every project
    carries the same standard sections (timeline, done, expected, design, people involved — each person linked).
    Existing projects with neither origin go to one review list after a dry run the owner reads (G141).
    **D4 amendment (owner, 2026-10-23) — something never called a project falls back to a concept page.** Owner:
    something the person never calls a project should fall back to another page type, so it shows in the app; a
    *project* page still needs a repo or the person's own words, and D4 stays as written for projects. **Why:** on
    `benchmarks/newuser` the persona builds a cedar-strip canoe over five conversations and never says "project"; the
    canoe had no page at all, its facts held under five project-typed spellings ("Cedar-strip canoe", "Canoe", "Boat
    hull build", "Hull build project", "Boat hull"), and Ask answered from the conversations while the app showed
    nothing. **The rule:** a project mention with no birth is weighed by the judge (never an alias alone, 2026-10-08)
    against the project and fallback pages and the other such names; the spellings judged the same are one group and
    the ordinary promotion rule is read over the group (2+ conversations between them, or one substantive or linked);
    over it, ONE page typed `concept` (the closed set's general type; no 11th type) and marked
    `proposed_type: project`; below it, held as before. A later birth — the person's own words or a repository —
    makes that same page the project with `born` (`project_birth.retype_on_birth`); a project page, or a page born with
    any other type, is never retyped or archived by this; held births keep working as before
    (`capture-and-sleep.md`, "The fallback page"). **Revisit** if the fallback pages turn out to be mostly things the
    person would not want a page for (the inbox's dismissals of them), or if the judge joins two different things.
    **D5 — People's photos from X and LinkedIn: the gate turns on, shipped with sources on people (amends the
    2026-10-09 exception's "off by default").** Owner: "yes go with recommended, but also i think this update sources
    (maybe come up with a better name), is of extreme importance, so any agent and cicada as well can provide/have a
    heads up as to where to check the info, and the user through the app too. We need to keep it generalizable as well
    bc it might as well be a personal website, a google scholar account or anything literally that will escape my
    knowledge…" `CICADA_ALLOW_PERSON_PHOTO_PROXY` defaults on; every other term of the exception is unchanged (only
    from an X or LinkedIn link already on the page and given as the person's own account, through unavatar.io, no
    service sent a name, the person can still turn it off). It ships together with sources on people, because alone
    it fetches nothing: measured, 0 of 277 person pages carry a source and 276 show initials. Agents and Cicada may
    propose a source by inference, with the evidence that names it; a proposal is not trusted — no picture, no
    refresh — until the person takes it or their own located words name the account (ruling 29). Contacts count as a
    source ("Sources also should include contacts, run tests for that too"). **The name is "Where to check"** (owner,
    2026-10-22); the agent-facing definition is G61's. Proposals arrive as **one grouped inbox review** ("Confirm N
    links"), never one question per page — a dry run on the owner's bank would have added 36 questions to an inbox of
    218 (owner, same answer).
    **D6 — Settings in six; Sources and Agents become pages; Devices shows what is connected.** Owner: "yeah that makes
    sense and adding status stuff like to see if my server or other box is connected that's great. Also the connection
    has to be clear, it must be setup easily enough like claude does it in their apps. … something like that with just
    going to a link or detecting cicada over tailscale would be cool. Also refer to the mac not as my mac but as its
    name in the app (the machine's own name)." Settings: General · You · Intelligence · Sleep · Devices · Privacy &
    data, under 400 words of copy (today 11 sections, 107 controls, about 2,030 words with folds closed — measured on
    the demo bank after #417). Sources and Agents are sidebar pages. Devices lists each machine by **the machine's own
    name**, never "this Mac", with a connected dot and how (Tailscale, SSH, local), and pairs another machine by a link
    or a code, finding Cicada over Tailscale where it can (G212, G217).
    **Extra answers.** Logos come from each vendor's own brand page or repository, never redrawn; one umbrella per
    provider (Anthropic: Claude Code and Claude; OpenAI: Codex and ChatGPT) with the ways to connect beneath it;
    Instagram joins the sources (G217). A person's own links (socials, contact) may show as a row at the top of their
    page in the link-view grammar — the owner left it to the acting owner; proposed yes in G61. Phones: the Claude,
    ChatGPT and Gemini apps reach Cicada through the G135 connector, added on the web and synced to the phone, which
    needs a public URL (Funnel, not Serve) (G135); a minimal capture app in a new repository, `cicada-app` (share a
    link or post, attach a note, pair the phone as a device), is started (G91). Every feature's status is tracked in
    [`feature-status.md`](feature-status.md), one line per row. **Revisit** D1 on a change in either vendor's terms;
    D2's default if a later measurement reverses the first; D5 if a fetched photo is ever shown on the wrong person.
37. **The new user's inbox and saved items (owner, 2026-10-22; answers to the benchmarks/newuser report, W5 and W8;
    amends ruling 29's fold rule and the G99d dating of saves).** **A — a fold Cicada ships settles by rule.** A
    "Confirm a predicate fold" question whose fold is listed in the shipped predicate seed (`synonyms`) is curated, like
    an ending: Sleep settles it (`seed_fold`, engine-free, undoable under "Settled by Sleep"); only a fold the bank
    learned still reaches the judge or the person. A follow-up card's body names its thread: the page, the claim's own
    words and why it is asked now. **B — a saved item is dated when it was saved.** A NEW save's or import's episode
    takes the save's own instant (`added_at`), else noon UTC of its day (`saved_at`), never later than now, as its
    `timestamp` and id day — as a calendar event takes its start (#435); a save with no recorded date keeps the day
    Cicada took it in; existing episodes are never renamed (ruling 34). **Why.** On the synthetic new user (counts only,
    `benchmarks/newuser`): the first inbox was three or four fold questions about the seed's own synonyms and one
    unexplained "How did it go?"; bookmarks saved in August read as saved on the import day. **Revisit** A if the
    person undoes `seed_fold` settles often (`GET /consumption/feedback`'s `sleepSettles`); B if a source's recorded
    save date proves unreliable.
    **C — an ending closes only its own subject's claims (owner, 2026-10-23).** Only an ending said about the project
    closes the project's claims; "the person dropped X" never closes a project's use of X by rule. When the person's own
    words say they dropped or switched X for a project (the project named, or plainly the subject of that turn), Stage 1
    writes the ending on the project as its subject. **Why.** #442's one Sleep in five that put the drop on the person's
    page; a cross-subject rule would let a remark about the person end beliefs about everything they touch.
    **Revisit** if the drop replays fall below 19/20 on the project.
38. **The follow-ups: one API generated from the tool table, a capture-only phone, one-way syncs, traces with
    screenshots (owner, 2026-10-23; answers to the four decisions in the follow-ups proposal, `followups-2026-10-23.md`,
    kept outside the repo with the redesign research, recorded as rows by #451; G213, G91, G219, G218).**
    **1 — API.** `/v1` is generated from the remote tool table: every `REMOTE_TOOLS` entry is one operation unless an
    exclusion set names it with its reason (only `cicada_handshake`, carried by `GET /v1/me` and `llms.txt`), taking it
    from 11 to 27 operations. The 11 shipped names are frozen byte for byte (Hyrum: existing callers keep working);
    new operations are named from `cli_map`'s command (its `api_op` column holds only the frozen names). One G199
    contract on every door — the same schema check, refusal sentences, `isError` codes and fencing as `/mcp`; every
    token scope is enforced exactly as on `/mcp`, `sources` gating every verbatim word. `capture_turns` is on `/v1`
    under `record`, stored as relayed (`evidence_kind: assistant`), never the person's own words. **No third door:**
    MCP clients use `/mcp`; everything else `/v1` plus `/v1/openapi.json`, and no OpenAI-format tool list. Local-only
    tools (`cicada_continue`, anything that reads `~/.claude`, the stdio-only set) stay off `/v1` as they are off
    remote. A test pins the operation list to the remote tool table, so a tool added to one and not the other fails CI.
    **2 — Phone.** Stays capture-only. It adds photos and files from the share sheet through one new capture route, and
    voice notes are transcribed on the phone and sent as text (no audio leaves the phone; no model on the capture
    path). Reading memory on the phone goes through the Claude and ChatGPT apps over the G135 connector, or a Shortcut
    calling `/v1` with an agent token. The device build is signed with the owner's Apple team first; Android comes
    later. **3 — Syncs.** Reminders first (the lists the person ticks; incomplete reminders and those completed in the
    last 90 days), then Notion (its export first, then its API with a token scoped to the pages the person shares).
    Both are one-way into Cicada and never write back. Then Obsidian, then Todoist. **4 — Activity traces (G218).** The
    owner chose to include screenshots from the start, not as a later tier. It ships off by default, outside every
    bank, encrypted at rest, never on the network, with one-click wipe and retention limits; the details are in the
    G218 row and the traces PR. **Why.** The proposal measured two doors with one token giving different powers (11 of
    28 remote tools on `/v1`), names that were not `cli_map`'s and no test pinning either set; the phone's read tab
    would have put a wider token on the device most easily lost; a two-way sync is a second source of truth.
    **Revisit** 1 if an operation ever has to differ between `/mcp` and `/v1`; 2 if the AI apps' connector reads prove
    unusable on the phone; 3's order on a new user's measured intake; 4 only through the G218 row's own triggers.
    **38a — a client library over `/v1` is not a door (owner, 2026-10-29: "Yes, as a client of /v1"; G213; branch
    `feat/memory-tool-adapter`).** A package that runs in an agent's own process and speaks only `POST /v1/<op>` /
    `GET /v1/me` with a scoped agent token adds no route, no listener and no power: the token's scopes, expiry and
    revoke, the G199 contract, the Sleep and demo gates and every provenance rule are Cicada's, checked on each call.
    The first is `clients/memory-tool` — Claude's API memory tool (`memory_20250818`) answered from `/v1`: reads are
    Cicada's replies (fence kept), writes go only to the agent's `notes/` through `save_note` (the agent's words, never
    the person's), nothing is deleted or renamed, every path is checked before a byte is sent. **Revisit** if a client
    ever needs something `/v1` does not offer — that is a `/v1` operation (and its remote tool), never a client-side
    reach into the bank.
39. **Both dates recorded for everything; trace watch history stays on; app wording to the coordinator (owner,
    2026-10-24; the trigger was the connectors report's open question "RSS items dated when polled", `connectors.md`,
    kept outside the repo with the redesign research; G218; branch `feat/both-dates`).** The owner's words: "have both
    dates recorded for everything when available." **(a) Both dates.** Every new episode keeps `timestamp` as the
    item's own date where its source gives one (published, created, sent, saved, happened — as before) and records
    `received_at`, when Cicada received it, aware UTC. `episode_ids.create_episode`, the one door every new episode
    goes through, stamps it (the stager writes it in `write_new`); it is set once — an edit in place, a re-date
    (`redated_from` keeps the moved `timestamp`, never the receipt), a rename, a relay upgrade and a tombstone leave it.
    A live hook's two dates are the same moment and both are written. Existing episodes are never renamed (ruling 34)
    and get no backfill: a missing `received_at` reads as unknown, never guessed from the id, the file or
    `redated_from`. A test fails when a module that mints an episode id creates one without it. **Feeds:** an RSS/Atom
    item is dated by when it was published (`pubDate`, `published` else `updated`, `dc:date`; never after now) for its
    `timestamp` and id day, records it as `published_at`, and is **no time signal** (`episode_time.is_feed_item`, the
    "facts yes, activity no" rule of the memory export, keyed on `published_at` or `origin: rss`). What decay reads is
    unchanged: a page's `last_referenced` / `decayed_through` / `learned_on` and, for pace and the repeat floor, the
    dated ids among its `source_episodes`; a feed id is not among them — no mention week, no last-said day, no
    conversation. So a new subscription's back catalogue is no burst of activity (the old poll-day dating made it one),
    a page a feed item creates starts its silence clock the day Cicada learned it (no `last_referenced`), and a page it
    touches keeps its last mention and its clock. Stage 1 is told the item was published on its day and is the
    publisher's text, not the person's words. A feed's summary is the page's description (`preview`), no longer filed
    under `## User note` as the person's. Subscribed ICS events already followed Calendar (their start once begun,
    ruling of 2026-10-16) and gain `received_at`; they stay a time signal, as the Calendar app's events are.
    **Surfaces:** the received day is shown only when it is at least two days after the item's own (`received_shown`):
    the Reader's meta line ("May 1, 2023 · added Oct 24, 2026"), a Sources list row's help and spoken label, recall's
    episode excerpt label; otherwise one date, as before. **(b) Watch history from activity traces stays on by
    default** — "turned on by default, same as having agents check your accounts and stuff (mainly read access, to
    update stuff)". Traces themselves stay off by default (ruling 38 §4); this is what a trace watch does once they
    are on (G218). **(c) App wording calls are delegated** to the coordinator's recommendation, with "avoid
    repetition"; another PR applies them. **Why.** Dating a feed by its poll day made a back catalogue look like a day
    of activity; dating it by its publisher alone would have started pages' clocks years ago. Keeping both, and
    treating what a feed published as no mention by the person, answers both. **Revisit** (a)'s feed rule only if a
    feed proves to carry the person's own words (a feed of their own posts), and its surface threshold on the owner's
    word; (b) through the G218 row's triggers.
    **39b amended (owner, 2026-10-28; ruling 48's direction): what you watch and read, on any site.** With activity
    traces on, one switch, **"What you watch and read"**, on by default as 39b was. A video page of a platform Cicada's
    watch history knows joins the watch history (`via: traces`, with dwell); any other page an allowed browser had in
    front for 30 seconds or more that day joins that day's reading record (`reading-history:<day>`): its cleaned
    address (no query but content keys), its title where kept, its site, when first seen and for how long. Both are
    index-only (ruling 30): looked up, never read by a model, never a mention. Excluded sites and private windows never
    reach them. A model reads traces only through "Learn from my day" (off by default). **Revisit** if a reading day
    carries something the person considers private despite the exclusions, or on the owner's word. **With it
    (2026-10-28, branch `feat/traces-v2`):** the redesign's H is accepted as recommended — `daily_summary` and
    `learn_from_summary` become the one "Learn from my day" switch (off by default; the old keys stay read aliases);
    and, per ruling 45, a repository-born project counts for time attribution only once the person has claimed it.
    **Dated line (owner, 2026-10-26; G71, G206; branch `feat/sources-defaults-calendar`) — saved lists on by default,
    as item (b) says of agents checking the person's accounts.** Owner: "By default the user should have them all on.
    Re-reading my saved stuff should be the default. Maybe when first onboarding you ask the user 'Do you want an agent
    to go through your saved posts?'" **(1)** Onboarding gains one step after Sources, *Saved lists*: every list the
    person's own agent can read (YouTube Watch later and history, X Bookmarks, Instagram Saved, LinkedIn Saved posts)
    pre-ticked, one line that their own agent reads them in their own signed-in browser and that the sites' terms
    discourage automated access, and one button. That answer is the consent: the ticked lists turn on with agent reading
    and its first-use acknowledgement in one call, the unticked are recorded off. Skip writes nothing. **(2)** An off
    is now remembered (`reading.json`'s `youtube_lists_off` / `saved_lists_off`): nothing automatic turns it on again.
    **(3)** An install from before this line gets the default only for an account its memory already shows (an
    export's, a watched day's, an earlier read's origin: `list_defaults`), only once agent reading counts (its sheet
    acknowledged, the master switch not off), applied once when the Sources page reads its settings; a list an agent
    read before that holds no switch now was turned off by the person, so it is recorded off. **Unchanged:** at most 10
    recorded reads a day across X, Instagram and LinkedIn, one site at a time, stdio only, never a site grant, every
    item indexed and never read by a model (ruling 30), a sign-in wall pauses that list for a week. **Revisit** if a
    default-on list produces sign-in requests for accounts the person does not have, or on the owner's word.
40. **An organisation's own website is found during consolidation, and trusted when Cicada is sure (owner, 2026-10-26;
    G61, G146; amends ruling 36 D5 and the pictures rail for organisations; branch `feat/org-website-sources`).** The
    owner's words: "A lot of entity pages, like universities and stuff, don't have a picture. For me this is too
    important because it means that we are not even inferring some things, like the sources where things can be updated
    for that entity page. For example a university has a website. Why wasn't this detected? When consolidated it should
    be part of a source that's used to update and from it we also infer the picture if we are 100% sure." **Scope:**
    `company` (universities and institutions included), `tool` and public `location` pages with no trusted `website` —
    never a person, the owner, the person's own projects (ruling 27's line), a name that is not a public proper name, a
    name carrying a person's or a project's name, or a page its description calls the person's own. **"100% sure"** (the
    coordinator's definition, implemented as written): the record already ties the site to the page (an origin whose
    label is the page's name, alias or acronym, in the person's own located line or on the page itself), or ONE
    Wikidata item whose label IS the page's name, whose class agrees with the page type, that is no human or country,
    whose country does not conflict with the page's, listing one official site (P856) — and, either way, the site's own
    homepage names the entity (a lookup also needs two of the page's distinctive words in the item's description or the
    homepage's head). A search engine's hit is never enough. Anything short of that is a proposal in the one "Confirm N
    links" review (D5), never trusted until the person takes it; a removal is remembered and never re-added. Once
    trusted, the logo is drawn from it (a public place too) and it is re-checked under ruling 26. It runs in Sleep's
    site-check step behind `CICADA_ALLOW_CONNECTOR_FETCH` (≤ 40 pages, ≤ 20 Wikidata lookups a night; the person's
    `verify-sites` click is ungated), sends only the organisation's name and at most two proper aliases, spends no model
    call, and never fails Sleep (`org_sites`, `storage.md`). **Why — the cause, measured on a copy of the owner's bank
    (real values redacted):** the bank did hold 370 `website` sources (the brief's "zero" counted `kind: website`; the
    role is `predicate: website`), 193 verified; but a site reached a page only from Stage 1's optional field when the
    page was CREATED (`conflict_resolver.py:780`, company/tool/project only, "only when certain"), or from the backfill's
    `website` claim / own-name `## Links` host whose label had to be 3+ letters (`site_sources.py:123,155`) — so a page
    made before G61 S3-b, a `location` (`site_sources.py:42`, `logo_service.py:81`) or a short-named one (the owner's
    university, `<org>.edu` with a two-letter label, on 77 conversations) never got one; 120 Stage-1 proposals sat
    "not confirmed" for want of two summary words on the homepage (`site_sources.py:309`), outside the D5 review; and the
    D5 step proposes only profile links and repositories (`source_proposals.py:218,223`). The dry run
    (`api.scripts.org_sites_dry_run`) over the copy examined 483 live in-scope pages: **55 trusted** (18 from the record,
    37 from Wikidata; 50 draw a logo), **114 proposals**, 29 left alone (a proposal already waiting, or another
    writer's entry for the same site, which keeps the nightly site check — that check, read only, would trust 4 of
    its 80 untrusted entries), 285 nothing; 1,020 skipped (762 archived, 142 already with a
    trusted site, 56 private names, 52 projects, 8 carrying a person's name). A hand check of every trusted row found
    3 of 79 wrong on the first pass (two common-word namesakes, one alias the page conflated); the content check was
    narrowed to curated text and alias-only matches made proposals, and the second pass trusts none of the three.
    **Revisit** if a trusted auto-site is removed by the person (count `sources_removed` rows by `user` on entries with
    `verified.how` `wikidata+name` / `record*`), or if a fetched logo is ever shown on the wrong organisation.
    **Amended (owner, 2026-10-28, D and E; vision item 2, branch `feat/pictures-v2`; G146, G159, G61).** **D — a site
    Sleep itself first proposed is trusted once its homepage names the page:** Stage 1's official site
    (`propose_site`, `added_by: agent`), the backfill's unconfirmed entry, and Sleep's own "Confirm N links" proposal held
    only because the homepage had not answered or not named it are "on the page itself"; ruling 40 confirms one in place
    (evidence kept, the proposal flag gone) on exactly its usual bar — the site's label is the page's name, alias or
    acronym AND its homepage names the entity (`org_sites.sleeps_own_site`). Amends D5's "never trusted until the
    person takes it" for these three kinds only: the person's entry, an identified agent's, a remote app's, and a
    proposal held for any other doubt (only an alias matched, the record names another site, a country conflict, a
    namesake, content that did not agree) still wait for the person. **E — a project gets a mark:** its trusted
    website's logo, else its repository owner's avatar only when GitHub's public account record says an
    `Organization` owns the repository (`logo_service.fetch_org_avatar`); a personal account's avatar is never asked, a
    repository proposal is never drawn (D5), and ruling 40 still never looks a project up. **Measured** on a copy of
    the owner's bank (record only, homepages fetched, Wikidata not asked): ruling 40 trusts 24 sites instead of 11, and
    picture coverage moves from 3,690 to 3,729 of 5,684 live pages (brands +23, projects +11 from a trusted site, 0 from
    a repository: all 19 repository links are proposals). **Revisit** with D's own trigger above, or if a project ever
    shows a personal account's face.
41. **Nicknames count as nicknames, unless there is no name — then a nickname is the name until a name is found
    (owner, 2026-10-27; G209; branch `fix/people-duplicates`).** The owner's words: "Nicknames should count as nicknames
    unless there is no name, then it's a name until a name is found", and it "should work at scale with many many
    nicknames". **As built:** a nickname the person uses is always kept as an alias of that person's page, even one
    other people share or one that is another page's name (Sleep no longer drops an alias for being another page's; only
    a name or nickname of ANOTHER entry of the same conversation is dropped, unless the two list each other or it starts
    a word of this entry's own name). A page with no name is titled by the nickname (`nickname_title: true` with
    `unnamed: true`), never "X (unnamed)" or the role; its name question stays open. A ruling-29 settle that finds only a
    nickname (lowercase where a quote has capitals, or the reader marks it a nickname) titles the page and keeps the
    question; a name — the person's inbox answer, or a settle that passes `written_as_name` — takes the title, keeps the
    nickname as an alias, and is never asked. **At scale:** a nickname never joins on its own — a page titled by one, or
    a name two or more other people answer to, goes to the judge; more than five pages answering to one name make it
    common (`MAX_NAME_HOLDERS`): its alias holders are not each judged, but the mention's own aliases, a name said with
    it and the page titled exactly by it still are; a name never creates over a page it did not join (held and asked,
    then "<name> (another)" once the person says someone else), and a held name's edges and claims never land on the
    page that shares it (its claims, both ways, wait on its pending line until Stage 2 decides); lookups go through one
    index per run (`NameIndex`): 2.3 ms a name on a synthetic 2,500-page bank with ~20k aliases. **Revisit** if a
    nickname-titled page is renamed by the person to its nickname again, or a held common-nickname mention is later
    found to have been someone's only name.
42. **An event, program or application the person acted on gets its own page from one conversation, and the
    application lives there (owner, 2026-10-27; G194, G141; branch `fix/facts-keep-context`).** The owner's words: "I
    think it will be useful to have them as pages, maybe for a specific event/program/etc, and in it info about the
    application. Like seeing info about 'Rodrigo applied to this and this' on my page makes it so my page is huge, and
    full of stale information. If smth goes stale it should be the specific event." **As built (`application_page`):**
    a named exception to the 2-conversation promotion rule — one conversation is enough when Stage 1 marks a specific
    event, program, hackathon, fellowship, course or opening with an `application` (status drafted / filled / sent /
    registered / accepted / rejected / attended) AND the conversation shows the act: one sentence of the person's own turn
    names it and says it was done (applied, registered, signed up, submitted, filled in, requested to join…), with no
    question, plan, wish or negation in it, or — in a harness transcript only — one sentence of the agent's own line
    does ("the X form is filled in"). Never a person, tool, skill, place or folder; never a bookmark, a save, a
    mention, a plan, a question ("Should I register for X?") or a texted agent explaining how to apply. An agent's
    status and the person's later one are one belief: the agent's `external:<harness>` shares Cicada's own slot
    (`claim_reconciler.slot_observer`), so the newer closes the older — except that an agent-only status never closes
    the person's own words (the owner's-words rail asks instead). The page holds the application: a dated fact
    with who acted (the agent and the first 8 characters of its session, from the episode's own record), the open step
    as an open question, and the status as a value claim a later status replaces (observed `external:<agent>` when the
    agent acted, with the session). Stage 1 moves what the owner's extraction says about the thing (key facts, summary
    sentences, history) onto it; the owner keeps the relationship claim — the link — and nothing else. A thing the model
    typed a project without a D4 birth is written as the fallback `concept`, never a project. Decay and staleness are
    the event page's own. **Dry run (owner bank copy, 2026-10-27):** 39 owner-page lines carry an act word; a reading
    picks 12 about 6 events, and the gate (re-checked on each event's own conversations) passes 3: 8 lines move to
    Exponential Community, Arctic Express and Antigravity; Cambridge MLMI ("applying", never "applied"), a YC hackathon
    and a design talk (attended, but no sentence of the person's says so) stay; owner page 481,809 → 480,954 bytes — stale "applied to" lines are a small part of
    its size (report `facts-keep-context.md`). The repair of existing pages waits for the owner's approval of that list. A "did you send
    it?" nudge is a follow-up (it must go through the inbox and ask-gate rails). **Revisit** if a one-conversation
    event page is archived unread by the person more often than not, or a real application is missed because the person's
    words name it only by a pronoun.
43. **Cicada may read an agent's own memory notes (owner, 2026-10-27; G105, G110; amends the capture rails; branch
    `feat/agent-memory-notes`).** The owner's words: "yes 100% cicada can read claude memory notes." **Scope:** Claude
    Code's auto-memory notes, `~/.claude/projects/<project>/memory/*.md`, and their `MEMORY.md` index — every project
    folder, not just the current one. **Not** the transcripts: their rail is unchanged. **Why:** in a real session the
    agent's own note held the cleanest record of something Cicada had blurred — which event it was, that a form was
    filled and its submission left to the person, and the session that did it (`originSessionId`) — and Cicada never saw
    it (real values redacted). **As built:** the harness's own hook reads the notes on the machine where they live and
    posts their bytes (`api/hooks/memory_notes.py` → `POST /capture/agent-memory`); the backend parses bytes and opens
    no path for this source, so its one read under `~/.claude` stays the transcript read, and a client of a server
    elsewhere (ruling 28) or a headless server with no app works the same way. One episode per note through
    `episode_staging` (an edit in place, re-queued; a note gone from a complete post tombstoned; scrubbed; a demo bank
    409s), `evidence_kind: assistant` (the ruling-32 precedent: read by Sleep, never the person's own words), dated by
    the note's `modified` (ruling 39), no mention for decay (`episode_time.UNTIMED_SOURCES`, like a chat export's memory
    entry), told to Sleep as an older lower-trust summary, `origin_session_id` and `origin_episode` naming the session.
    One switch per memory, on by default (Settings → Privacy, "Your agents' notes"). Promotion's and a skill's "2+
    conversations" count conversations, not episodes (`promotion.conversation_keys`): a note is its session's, and a
    note with no session counts as none — a session and its notes, two notes of one session, or a note and its index
    never make two (review of #487). **Revisit** if a note-derived claim ever closes one resting on the person's own
    words.
44. **The internet adds context to public things, and every page says why it matters to the person (owner,
    2026-10-27; G121; amends rulings 27 and 40; branch `feat/web-context`).** The owner's words: "looking up public
    figures not only them but companies, programs, anything really i think internet can add a lot of useful context,
    but depends on the request. Can start small or be bigger, memory should always state why it is/was/will be
    relevant to me and also be up to date." **What still holds:** a private person's name is never sent to any
    service (friends, family, anyone known only from the person's life); the person's own files, projects and life are
    never sent; a removal is never re-added; telemetry is ids and enums. **The public test (`web_context`), err
    private:** a company, tool or place on ruling 27's local test; a concept or a person only when, after a local test
    that sends nothing, Wikidata has exactly ONE item that IS the name, of the right kind (a human for a person), with a
    Wikipedia article. A person's local test: a full name, not relation-shaped or role-only; no acquaintance with the
    owner on the record — met, talked or messaged, friend, family, partner, colleague or classmate, a contact, invited
    by, interviewed by, taught or supervised — in a relation or a sentence naming the owner (being inspired by, reading,
    watching, quoting, citing, following or admiring their work is not acquaintance; coordinator, 2026-10-27); no
    conversation from a personal channel; a public cue on the page (a public role, or public work: a talk, a tweet, a
    book, a video, a role at a company). **As built:** Sleep's tail (plan
    runs only — a metered key is skipped in words; behind `CICADA_ALLOW_CONNECTOR_FETCH`; `web_context_per_run` = 6
    lookups and ≤ 20 Wikidata tests a run) looks up public pages that are new or due, depth by use (a line, more for a
    page the person comes back to, dates and deadlines for a commitment), every search one of the pinned queries;
    cited, dated world claims (a citation, never a tracked source); the newest replaces an older world fact with history
    kept, never a claim on the person's own words about their own life (what they said about a public figure's
    employer is a dated world fact like any other); a fact the results say is over with nothing in its place is closed,
    not rewritten; each lookup undoable under "Settled by a check", a value taken back
    never written again. Re-checks weigh volatility (30 / 180 days / never) by use (conversations, stated relations,
    a recent mention); a page silent 180 days only on request (`POST /entities/{id}/web-context`, "go deeper").
    "Why it matters to you" is derived on read from stated relations and the person's own words (`page_relevance`),
    tense from the claim, "No personal relation on the record" when there is none. **Measured** on a copy of the owner's
    bank (real values redacted; full rows in the worker's report, outside the repo): of 281 person pages, **9 public**
    after the acquaintance rule (5 before it; the figure whose stale employer raised this ruling was among those it
    wrongly kept private) — all with one encyclopedia match; 106 single names, 48 an acquaintance relation, 56 the owner
    named with an acquaintance word, 16 no public cue, 28 Wikidata zero, several or no article, 18 a name shape,
    role-only page, personal channel or the owner. Of 1,190 live candidates, 565 public (39 concepts stayed private when
    Wikidata requests were refused mid-run — err private; an error body is now never cached as an answer). On that
    figure's page one lookup closes the stale "works at" as ended in the source's year, with nothing invented in its
    place. 39 haiku
    lookups on the plan (cap 40, one smoke call): 35 with facts, 2 unsure, 2 none; 76 facts would be added and 1
    replaced (a tool's description), 0 protected; every person verdict is listed for the owner to check. **Not used:**
    the telemetry ledger's reads, though the brief asked for them — CLAUDE.md says nothing learned from the ledger is
    auto-applied; the owner decides. **Revisit** if the person undoes a context lookup on a page the test called public
    (count `context_undo` rows), or a person the test called public turns out to be someone they know.
    **Amended (owner, 2026-10-28, C; vision item 2, branch `feat/pictures-v2`; G159, G146).** **A public figure's face
    is their encyclopedia portrait:** a person the full public test called public (the local test, then exactly ONE
    human with an encyclopedia article) gets that item's image (Wikidata P18), drawn from Wikimedia Commons. The memo
    outside every bank now keeps the matched item, so the portrait is asked by item and file name only — the person's
    name is never sent again as a query (the Commons file name P18 holds may contain it), and a private person's never
    at all (the local test still sends nothing). The local test runs once more just before the ask (err private), and
    again for every held match on each Sleep run before any gate; a match not passed within 14 days draws nothing, and
    a page that fails leaves the memo and its portrait with it (review of #510). In the people ladder after the GitHub avatar and before the proxy (no proxy budget, nothing the
    test did not already ask); never the owner's page or a demo bank; behind `CICADA_ALLOW_LOGO_FETCH` and the people
    gate, on the ToS rail (`person_photo`). **Measured** on the copy: of 132 people with no picture, 22 pass the local
    test, 5 match one encyclopedia item, all 5 have a portrait (people with a picture: 2 → 7 of 134).
45. **The Projects list is the person's; everything detected is suggested, never archived (owner, 2026-10-27; G141,
    G222; amends ruling 36 D4; branch `feat/projects-v2`).** The owner's words (2026-10-26): "some projects there are
    detected and are not even mine." **Q1 (yes):** the list shows only the person's own projects — created in the app
    or from their own shell (`cicada projects new`; refused from an agent's shell, ruling 21a), created by a trusted
    agent on their ask, a watched folder they named, or a suggestion they accepted. Everything else (a repository birth,
    a words birth, a fallback concept, another client's proposal, a ChatGPT grouping with no page) waits under
    **Suggested** with its reason, strongest first, and is never archived, deleted, renamed or retyped. "Not mine" keeps
    the page as it is (`not_mine: {day}`, on the page, so it travels with a merge) behind "N dismissed". **Q2 (yes):** a
    project the person already logged progress on in the app (a claim with `origin: companion_app`) is theirs on day
    one — derived on read, never written, so no write runs over a bank. **Q3:** a harness on the person's G198 trust list
    (Claude Code and Codex by default) lands `cicada_create_project` in the list; any other client, a remote app
    always, leaves a suggestion labelled as its proposal. **Q4:** a words birth ("my X project") is suggested, showing
    the located sentence, one tap to accept (it cannot tell "helping with <bob-example>'s mural project" from the
    person's own). **Q5:** the person's `description` (with `description_by`) is the header, written only by their
    doors (the app's PATCH, a trusted agent's `cicada_edit_page(name=, description=)`, others proposing in the inbox),
    never by Sleep; Sleep's article stays below as the Overview. **Q6:** the dated list is called "Timeline". **Q7
    (yes):** the project detail is a card plus a "project knowledge" side panel, Claude-desktop style (DESIGN_RULES §9
    dated row); at narrow widths the panel folds under the card. **Q8:** a conversation is tied by its repository, the
    person naming the project in their own turn, Sleep's claims citing it, or a tie by hand — never co-occurrence — plus
    (addendum) the provider's own project id and the relaying app's word; an untie by the person overrides all and no
    signal re-adds it; an agent unties only what it tied. **Q9:** "something new" as an influence is a plain-text claim
    object and never mints a page. **Handshake:** Option A — the primer names no new tool; the skill carries
    `cicada_create_project`. **Addendum (owner, 2026-10-27): projects already made in Claude and ChatGPT.** A Claude
    export's `projects.json` makes or matches one page per non-starter project (`born: {origin: created, via:
    claude-export}`, `mine: {via: import}` while `project_ownership.CLAUDE_EXPORT_MINE` holds — one constant the acting
    owner may flip to make them suggestions); its description seeds the person's only when empty; its instructions are
    shown by span into the imported episode and its documents by name (their contents are never read); a project id
    seen once is kept in the bank's `project_groupings.yaml`, so a page the person deleted or marked not theirs is never
    re-created. Claude's `conversations.json` links no conversation to a project. A ChatGPT `g-p-` id
    (`conversation_template_id` or `gizmo_id`; a custom GPT's `g-` id is not a project) rides on the episode as
    `provider_project` — frontmatter only, never re-queued — and is a conversation signal ("In your ChatGPT project");
    with no page it is one page-less suggestion ("A ChatGPT project, N conversations") the person names on accept. The
    relay's optional `project` (`cicada_capture_turns`) is the app's word, kept as `relay.project`, labelled "the app
    said". Sleep is told either as context, never as a claim. **Measured** on R-PJB9's 2,500-page synthetic bench: the
    conversations read p95 13 ms, the detail with its count 39 ms (budget 150 ms), the list 45 ms
    (budget 80 ms), on an idle Mac (`make test-bench`). **Revisit** if the person dismisses
    most of what a trusted agent creates (Q3), or accepts most words births as they come (Q4).
46. **Auto's ladder reaches Cursor and OpenCode after the two plans; Grok stays out (owner, 2026-10-28; G49, G50;
    amends rulings 31 and 36 D1; branch `feat/auto-ladder-46`).** #494 added Cursor, OpenCode and Grok as engines on
    the person's own sign-in, choosable but not on Auto, and asked the owner two questions: should Auto reach them, and
    should scheduled runs? The owner answered **yes** to both. The acting owner's guard, accepted with that answer:
    **Grok stays out of Auto and out of scheduled runs** until a live sign-in shows what a subscription call reports
    (a key set in Grok's own settings for a built-in model cannot be told apart before the call). So Auto is the Claude
    plan → the ChatGPT plan → Cursor → OpenCode (`engine_select._AUTO_LADDER`, `cli_engines.AUTO_SPECS`). A tool is a
    rung only when installed and signed in, and OpenCode only with a GitHub Copilot or OpenCode Go model listed;
    otherwise Auto skips it, never errors on it and never falls to a key. A tool that is not installed is passed over
    silently; one installed but unusable (signed out, only key-backed models, no answer in time) is named in the
    no-engine sentence. Scheduled runs reach Cursor and OpenCode through ruling 4b's "Scheduled runs may use my plan"
    switch, which already covered them when chosen (`SCHEDULE_PLAN_MODES`). **Said in words:** a landing names what
    runs on the Sleep page's line and in the run's detail (`engine_select.run_detail`), and Cursor's comes with its
    billing note (usage past the included amount bills only if the person turned that on in their Cursor account).
    **Never a stall:** the ladder reads #494's cached tool status (8 s per command, background refresh); a cycle waits
    at most `cli_engines.LADDER_WAIT_S` (9 s) for a status that is not fresh, both tools at once, and the Sleep page
    never waits (`cli_wait=0`, its cards warm the cache first); an unknown or hung tool is skipped for that run, said
    in words. The handshake's Now line and the cards' POWERS read the cache only (`cli_engines.cached_connected`).
    Measured on stub tools on a scratch PATH: each ladder position, the switch on and off, a hung tool (skipped in
    under 4 s with a 0.5 s budget, the next rung reading), and the page returning in under 1 s with a tool hung.
    **Revisit** Grok's exclusion only when a live Grok sign-in shows how a subscription call reports cost.
46a. **Cursor on Auto and on a schedule runs only Cursor's own models (owner, 2026-10-28: "Yes, own models only";
    amends ruling 46; G49, G122; PR #507).** The research for the engine picker (report `engine-picker-v2`, sources on
    G49) found that since 2026-10-12 *The X Subscription* sells Grok, Cursor and X Premium as one plan, with one
    weekly pool for Cursor's own models (the Grok line, Composer and Cursor's own `auto` router), shared by Cursor's
    editor, its CLI and the Grok apps, while a third-party model in Cursor (Claude, GPT, Gemini) is billed separately
    at API list prices from top-ups. Auto or a schedule landing on Cursor with such a model would have spent credit
    nobody chose (rail 2). **Ruled:** (1) Auto and scheduled runs use Cursor only with Cursor's own models
    (`cli_engines.cursor_own_model`): Auto landing on Cursor runs `auto` unless the stored model is already Cursor's
    own, never the tool's own config default (`engine_select._cursor_own_models_only`). (2) A third-party model
    chosen inside Cursor is labelled "billed separately at list price" before it is chosen (`billingNote` on the
    catalogue row, the picker's row, and the Cursor card's note), and is never picked by Auto or a schedule: a run the
    person starts on it reads; a scheduled run on it is never swapped onto another model — it has no engine, said in
    words (`SCHEDULE_CURSOR_THIRD_PARTY`). (3) The Grok CLI stays off Auto (ruling 46's guard stands). (4) The Grok and
    Cursor cards stay separate, each with its own mark: they share a subscription, not a tool or a sign-in. **It holds
    whatever set the mode** (review of #507): a `CICADA_LLM_MODE` pin in the environment (a headless server's .env) is
    read the same way — `auto` pinned is Auto (Cursor runs its own `auto`), `cursor` pinned is the operator's explicit
    choice (a run the person starts keeps the pinned model; a scheduled run on a third-party one has no engine).
    **Revisit** when Cursor's model listing marks which models its plan covers (then read that, not the prefixes), or
    when a live Grok sign-in shows what a subscription call reports.
47. **Two ways in for what the person consumes: their own browser and Mac by default, an official API for specific
    high-value sources (owner, 2026-10-28; G166, G206, G218, G223, G179, G29, G32, G94; amends "Cicada never signs in"
    for tier 2 only, and "exports only for walled services").** The owner's words: "change the philosophy too, that
    connecting to outside sources through api or third parties is good if mainly for ingestion, you know? Like a direct
    access to the info we are consuming", then, clarifying: "Yeah I mean for a lot of stuff we can accept consumption
    over browser and macOS harness, that's what I think. But for some specific things if we can do api integration that
    is awesome." **Tier 1, the broad default — consumption through the person's own browser and Mac.** What they read,
    watch and use is captured as they consume it, seen by the browser harness and the macOS harness: reading with the
    person's own agent (G166), the saved-list reads (G206), activity traces (G218, ruling 38, off by default — trace
    consolidation is part of this same story, the vision map's item 7) and the app's Mac readers (browsers, Notes,
    Calendar, Contacts, Messages, watched folders). Their rails are unchanged: the person's own signed-in session,
    Cicada never signs in on their behalf there, ticked or allowed sites only, the read limits, no backend scraping.
    **Tier 2 — an official API integration for a specific high-value source where one exists.** The first is Telegram
    (47a); candidates Spotify, Notion, Readwise, Google, YouTube, Letterboxd. **The choosing rule:** pick each source's
    path on purpose — an API when it gives clean, complete, structured data the harness cannot (history, metadata,
    reliability); otherwise harness consumption is the default. An export stays a way in either way. **Applied to the
    candidates (2026-10-28):** Telegram → API (47a: the full chat history and live updates, which no harness sees);
    Spotify → **export only (amended 2026-10-29, coordinator on the ToS rail):** the person's own "Extended
    streaming history" download through G32's import, no API connector — Spotify's Developer Terms (v10, 15 May 2025) forbid an API
    connector: §IV.2(b)(i) bars "using the Spotify Platform or any Spotify Content to train a machine learning or AI model or otherwise ingesting Spotify Content into a machine learning or AI model", and §IV.3(a) says "you may not store, aggregate or create compilations or databases of Spotify Content" and "Do not store Spotify Content indefinitely"; capturing what plays through the macOS harness waits on the owner's ruling (G223); Notion → API (a workspace's pages as structured blocks; a harness sees one page at a
    time); Readwise → API (highlights with their sources, complete); Google → Calendar stays on the Mac reader, an API
    only for a Google source the person asks for that the Mac cannot read (Drive, Docs); YouTube → harness (watch
    history comes from the browser's history, G71, and Watch later through the person's agent; the official API does
    not return watch history), an API only if a list the person wants is out of the harness's reach; Letterboxd →
    harness and its public per-diary RSS through the feed gate (its API is granted by request; adopt it only if
    granted); WhatsApp → its local database through the Mac app (no sanctioned personal-account API — an unofficial
    client risks a ban); Pocket → export only (the service closed in 2025). **Tier 2's guardrails:** (1) **the ToS rail
    stands** — official APIs or a service's own sanctioned connector only; never scraping behind a login, never an
    unofficial client that breaks terms or risks the person's account; (2) **the person connects each one** — off by
    default, what it reads said in plain words, disconnect and revoke one click each, disconnect forgets the credential
    (`base.forget()`); (3) **read-only scopes wherever offered**, writing back a separate, explicit ask; (4)
    **credentials** in `~/.cicada/secrets.env` (0600) or the keychain where the app holds them — never in a bank, a log
    or the repo; (5) **the normal capture path** — no model at capture, staged through `episode_staging`, scrubbed,
    with provenance, other people's words stay theirs (`external:<name>`, G179); (6) **ruling 44's guard** — a private
    person's name is never sent to a service for a lookup; ingesting the person's own account data is fine, looking
    people up is not; (7) **rulings 4, 31 and 36 on spend** apply — a per-call bill is said with its basis, never on a
    metered key nobody chose; a scheduled sync sits behind `CICADA_ALLOW_CONNECTOR_FETCH`.
    **47a — Telegram live sync, the first tier-2 case (owner yes, 2026-10-28).** Telegram's own client API (MTProto,
    an official client library) with the person's own login, so the chats they tick sync live like Messages, plus
    their history when they ask. The session secret lives in `~/.cicada/secrets.env` (0600) or a 0600 file beside it in
    `~/.cicada`, never in a bank; the connect step says in plain words that Cicada keeps a signed-in session to their
    account and how to end it (Disconnect in Cicada, or Telegram's own Settings → Devices); off until connected; only
    ticked chats are read (G179's rail); the bot channel (G29) is unchanged. Built on
    `feat/telegram-live`, which cites 47a. **47a amended — one-to-one chats only, each with the other person's consent (owner, 2026-10-28).** Telegram's terms, read the same day: API Terms §1.5 — "you are prohibited from using, accessing or aggregating data obtained from the Telegram platform to train … or otherwise engage in the development, enhancement or deployment of artificial intelligence, machine learning models" — and telegram.org/tos/content-licensing, "Large Language Models and AI": "Telegram firmly prohibits the scraping, indexing, harvesting, aggregation or use of data obtained from its platform to train, fine-tune, validate or otherwise engage in the development, enhancement, benchmarking or deployment of artificial intelligence, machine learning models and similar technologies. Exceptions may be granted in instances where all relevant users individually provide explicit, informed, affirmative and continued consent that is strictly limited to the specific content and chat, channel, or non-global context window for which it was requested." Sleep reads a sitting with a model, so the owner chose "1:1 with consent": group chats and channels are never offered and the backend refuses them; ticking a one-to-one chat needs the person to confirm, per chat and in plain words, that the other person agreed — explicitly, knowing what it means, for that chat only — said to be the person's responsibility, which Cicada cannot verify; the confirmation is kept with its date outside every bank (`$CICADA_HOME/telegram/consents.json`, 0600, a chat id and a time); unticking withdraws it and stops the reading. **Revisit** if Telegram grants Cicada an exception or changes those terms. **Revisit** a candidate's path when the harness proves unable
    to read it reliably (tier 1 → 2) or its API's terms or access change (tier 2 → 1); the ruling itself if a
    connection is ever wanted for anything but ingestion, or a person's account is restricted for a connection Cicada
    made. **47a amended — Saved Messages (coordinator on the owner's behalf, 2026-10-29, G179 `feat/chats-ux-v2`):** the
    consent rule protects the other participants; the person's chat with themselves has none, so their tick is the
    whole consent — no question asked, decided from Telegram's own dialog (`is_self`), recorded `self` in
    `consents.json`, staged as their own notes (`self_chat`).
48. **The redesign is accepted; the rulings live in DESIGN_RULES (owner, 2026-10-28; amends rulings 38 and 39b in
    direction only).** The owner answered the redesign proposal's decisions item by item; every accepted change is a
    numbered part of the dated ruling in `docs/design/DESIGN_RULES.md` §9 (2026-10-28) and new rows DR-77…DR-81, with
    the synthetic mocks in `docs/design/redesign-2026-10-28/`. In short: an entity page is an article that carries its
    beliefs (DR-80); no page stacks folds (DR-81); Home's questions lead with their page, Catch me up is a conversation
    (the questions may change, follow-ups are the person's words) in the worm's voice and on every harness door; the
    Inbox leaves the rail; Ongoing and In short on pages (In short triggered by bank facts, never page views — the
    telemetry rail holds); places on native MapKit with coordinates from the Mac's own geocoder, never a public one
    for a private place (ruling 44); the filterable model picker (ruling 46 unchanged until the shared-owner engines
    are researched); the history line. **Traces (direction, not yet design):** ruling 39b's YouTube special case —
    trace YouTube views promoted into the watch history — is to become one general rule for what the person watches
    and reads on **any** site; the traces PR brings the design and the amendment's exact text (what counts as a watch
    or a read, where it lands, which switch), and until it merges 39b stands as written. The same PR brings the per-day
    view, every connected display and a low screenshot frequency under ruling 38's rails. New trace signals are
    "not yet". **Revisit** a part when its build shows a measured cost the mock hid (a p95 regression, a rail it
    cannot keep), on that part only.
49. **Telegram is never read from the Mac's own store; connecting is "link a device" (owner, 2026-10-29; G179,
    amends nothing in 47a).** The question was whether a local reader — Telegram for macOS's encrypted Postbox store,
    decrypted with the app's default key — could replace the sign-in. The owner ran the read-only probe on his own
    store (numbers only, nothing named): **59 one-to-one chats, a median of 1 message each, none older than a year** —
    the Mac holds a cache, not the history (the probe's pre-registered criterion C failed). A local reader would add a
    decrypt-another-app's-store posture, a macOS prompt, a native SQLCipher and a reverse-engineered format, and still
    not remove Telegram's AI clause or the per-chat consent. Owner: *"With telegram sure lets keep whatever is less
    friction for the user. If it can be done with a similar connect through browser that kind of lets cicada read your
    telegram then awesome."* So: **no local reader**; 47a's official API stays the one Telegram path, and its connect
    is a **QR the person scans in Telegram on their phone** (Settings → Devices → Link Desktop Device;
    `auth.exportLoginToken`), number → code kept as the fallback, a two-step password typed once either way — every
    47a rail unchanged (one-to-one only, per-chat consent, the session 0600 outside every bank, one-click log-out,
    nothing read before a tick). **Revisit** if Telegram ships an official local export or API for personal archives,
    or if Telegram withdraws QR login for third-party apps.
50. **An agent's saved note is the agent's words, not the person's (owner, 2026-10-29: "yes" to the recommendation in
    #548's report; G118, G105; amends nothing; branch `fix/agent-saved-words`).** A note an agent writes through
    `cicada_save_episode` — over stdio (`source: mcp`), the remote connector (`mcp-remote`) or `cicada save` from an
    agent's shell (`cli` with a harness or session on record) — carries no turn marker, so R4's default read it as the
    person's own writing: each paragraph an exchange "in the person's own words" (promotion), its spans `user`
    evidence, and one note could mint a page. #548 found agent notes had created event pages that way. **Now:** such a
    note is known by its own record (`authorship.agent_saved`) and read as `evidence.AGENT_KIND` on every reader that
    passes `authorship.of` (Stage 1, promotion, project birth, ruling 42, the Contacts-card rule, ruling 29's own-words
    settle and `persons_span`, Ask, the Reader, search hits): a span the markers would give the person is `assistant`;
    a `speaker:`, timed video or `attachment` line keeps its kind. Stage 1 is told whose note it is and gives a claim
    resting on it `external:<harness>`; promotion's "2+ conversations" counts it as its session (none without one, as
    ruling 43's memory notes). The other agent-authored saves already were the agent's (`cicada_save_url` notes and
    `cicada_record_check`/`record_profile`/source re-checks under `assistant:`, `cicada_record_watch`/`record_read` as
    saved items, an inbox quote as a relay episode, `cicada_note_progress` and backlog notes write no episode). The
    person's own words keep theirs: hook transcripts, chat exports, the app's notes, a typed reason on a save, and
    `cicada save` in their own terminal. **Exception (G118):** an agent's quote of the person, located in a captured
    conversation (`cicada_write_claim` evidence), still points at that conversation's own `user` span. Derived on read,
    never stored, so the fresh re-consolidation reads the existing notes right; no bank repair (owner). **Measured** on
    a read-only copy of the active bank: 18 agent-saved notes of 8,914 episodes (7 sessions, none with a turn marker);
    71 pages cite one, 6 rest on them alone, 14 lose the "2+ conversations" rung under the new count; 114 of 18,645
    located claims rest only on them and 130 carry a stored `user` span inside one. **Revisit** if an agent gets a way
    to mark a line as the person's verbatim words that Cicada can verify.
51. **One memory on every device: one home orders every write, every computer holds a replica, the phone is a full
    device, and the devices meet at an end-to-end-encrypted relay (owner, 2026-10-29: every decision in §6–§7 of
    [`docs/plans/2026-10-29-g132-sync-engine.md`](../plans/2026-10-29-g132-sync-engine.md); G132, amends G181's
    headless rail, ruling 28's "no bank of its own", ruling 32's tunnel line and ruling 38 §2; phase 0 records it,
    nothing is built).** Owner: *"Changing the 'main machine' should be easy and all machines should have the same copy
    of memory … for avg user that wants to just download the cicada app, also downloading tailscale might be friction …
    My phone should be another device in the network, not one that independently syncs to [each computer]
    separately."* **a — The home and its replicas.** Every computer may hold a full replica of the bank and answers
    reads from it. **Exactly one replica, the home, applies writes, mints ids, commits and runs Sleep**; its history
    only grows (no rebase, no force). Every other device's write is a **transaction** — `{idempotency key, device,
    bank_id, base_seq, tool, args}` — kept in that device's outbox and applied by the home **through the same tool body
    it runs today** (`/tools/call`), so the id rule, write admission, scrub and staging, the demo guard and authorship
    hold by construction; a transaction is a tool call, never a file diff. A transaction that no longer applies is
    rejected with a reason. A replica only fast-forwards and never commits; **nothing is ever merged by git or a file
    syncer.** The home is switched from **the Sleep page**, which names the device that consolidates now, with every
    other device's lag and whether it is online (and `cicada home move <device>`): a signed hand-off record is the old
    home's last commit. **Take-over from a lost home needs the person's confirmation, with the replication lag shown
    first**; an old home that returns becomes a replica and its later commits are offered back as transactions, never
    merged. "Who consolidates" and "who orders writes" are one concept and are never split. Ruling 4 is untouched: Sleep
    runs only on the home, scheduled runs under the person's switch as today. **Unset/off, nothing changes:** a
    single-machine install has no relay, no replica mode and no new process. **b — The phone is a full device (reverses
    ruling 38 §2).** It holds a partial replica, answers the inbox and holds conversations — first through the Claude and
    ChatGPT apps over the G135 connector, then optionally a chat in the Cicada app on the person's own plan — every
    write a transaction like a computer's. Its token stays bound to its Secure-Enclave key (G212's `device_proof`), now
    with a full device's scope; **revoking any device removes it from the device group and rotates the device-group
    key.** **c — The relay (amends the G181 rail).** Every device dials **out**; nothing on a device listens on a public
    port. The relay is **end-to-end encrypted**: it sees only ciphertext, sizes, timing and device ids — never a page, a
    transcript or a token — and it cannot read or forge memory. Its mailbox stores and forwards, bounded and expiring,
    for a home that is asleep and a phone that was off. Devices talk directly on a LAN or tailnet when they can;
    Tailscale stays supported and optional. The relay is **hosted by default and self-hostable** (one container on a
    machine with a public address, its URL pasted in Settings). **Choosing a host, an account, a domain or any spend is
    the owner's decision, and nothing goes live without the owner's OK.** The G135 connector's public address may live
    at the relay, forwarded to the person's devices over their outbound connection; the relay stays blind there by
    **TLS passthrough** (it routes on the server name; the certificate and decryption live on the device), **never by
    terminating TLS**. **d — The bank's state is the bank's.** The consolidation queue (the replica's `processed: false`
    episodes), the inbox and Sleep's status (running, stage, last run, schedule — a status frame the home publishes) are
    the same on every device at the same sequence; "Sleep now" pressed anywhere is a transaction to the home. What is
    still on its way (this device's outbox, the relay mailbox's count per sending device) is shown beside the queue,
    never mixed into it. **e — What phase 1 needs (acting owner, 2026-10-29, on the read-only phase-1 planner's
    findings).** **e1 — Capture commits on the home.** Today the session, turn and relay capture paths
    (`transcript_capture`, `turn_capture`, `relay_capture`) write the episode file without committing; Sleep's batch
    `add -A` or a poll's sweep commits it later. A replica follows commits, so the queue would differ between devices
    and break d. So, **while the home publishes its log**, a debounced background step commits **only the episodes the
    capture writers themselves wrote** (`transcript_capture`, `turn_capture`, `relay_capture`): each writer records the
    path and the content hash it wrote, and the step commits a path, settled ≥ 10 s, only while its hash still matches —
    as `cicada` with trigger `sync/capture`. Any other dirty `ep_*.md` (the person's own hand edit, which Sleep
    supports, or another writer's) keeps its edit uncommitted, or is set apart the way `agent_commits` does it
    ("Uncommitted edit kept apart") — never committed as `cicada`, so a write still commits alone under its true
    author. It holds write admission shared and is skipped while Sleep is writing; it never sweeps another path and
    never commits `_state.md`. With
    publishing off, nothing changes. This amends nothing in the capture rail: no model, and the capture path itself
    still makes no commit. **e2 — Replica mode is a third runtime mode**, beside local and client: read-only, never
    runs Sleep or a schedule, never commits on its own; a backstop guard refuses every bank writer there. Reads on a
    replica write nothing, so `GET /state`'s refresh-and-commit is a no-op on a replica and refreshes at the home.
    **e3 — The history only grows.** If the home's published history is ever rewritten (a hand amend or reset in the
    bank), publishing freezes and says so in words; the person chooses "publish from here" and the replicas re-copy —
    never automatic. **A demo bank is never published or replicated.** **e4 — A copy's saves commit at the home
    (acting owner, 2026-10-29, pending the owner's confirmation; G132 phase 1 B, #566).** A save a copy sends — an
    episode `cicada_save_episode` or `cicada_save_url` writes through the tool door, a transaction carrying `base_seq`
    while the home publishes — commits alone at the home under its harness, as a remote save does (R-R11 widened to a
    copy's writes), so the copy that sent it can read it back from its replica. A save made on the home itself (its
    stdio MCP, its own command line) is unchanged: uncommitted until Sleep, byte for byte (G135's ruling). Rodrigo can
    overrule it. **Rails amended, old words → new (each takes effect when the phase that builds it ships;
    until then the old words describe the code):** (1) CLAUDE.md, Headless: *"a server is its bank's one writer"* →
    the bank's **home** is its one writer (a server or any computer), and every other computer may hold a read-only
    replica it fast-forwards. (2) *"Another machine is a client (`CICADA_API_BASE`, or the app's `api_base` file, ruling
    28) with its own revocable device token and no bank of its own"* → another machine keeps its own revocable device
    token and may run in **replica mode** (e2: read-only, no Sleep, no commit of its own) holding **a replica** of
    the bank; its writes are transactions to the home; it never has a second
    writable bank of the same memory. (3) *"reach from another machine is an overlay the person runs (never a public
    port, never funnel — only the G135 listener may be, by the person, ruling 32)"* → reach is the end-to-end-encrypted
    relay every device dials out to, or directly on a LAN or tailnet the person runs; still **no device listens on a
    public port**, and the G135 listener's public address may be the relay's, by TLS passthrough — the person's own
    funnel (ruling 32: *"The person runs a public tunnel with a stable hostname (Tailscale Funnel or ngrok) **to the
    G135 listener only**"*) stays an option, never a requirement. (4) Ruling 38 §2: *"**2 — Phone.** Stays
    capture-only."* and *"Reading memory on the phone goes through the Claude and ChatGPT apps over the G135 connector,
    or a Shortcut calling `/v1` with an agent token."* → the phone is a full device with a partial replica; it reads
    and writes like a computer, and the AI apps over G135 are its first conversation path. **Open, decided in the
    build, never assumed (G132's phase gates):** how a device gets a TLS certificate for a relay-issued hostname under
    TLS passthrough; the mailbox's bounds and expiry; how the device-group key is distributed at pairing and rotated on
    revoke; the phone's partial-replica scope; the relay's stack (measured in phase 3); what happens to a transaction the
    home rejects while its device is offline. **Why.** In practice the owner ran two unrelated banks — two inboxes, two
    queues, two graphs that nothing converges (G202 row 6) — because a client of G181's single primary loses its memory
    whenever the primary sleeps, and reaching it needs a VPN on every device, the phone included. Linear's sync engine
    keeps one orderer and moves everything else to the edges; Cicada's invariants (the id rule, write admission, Sleep's
    single mind, "contradictory facts can merge cleanly") all assume one orderer, so the plan keeps it and makes it
    movable. **Revisit** a if a measured workload needs two devices to apply writes while partitioned; b if a lost phone's
    replica is found readable by anyone but the person; c if the relay is ever found to see plaintext or to need TLS
    termination to work.
    **f — Routes, not a relay; nothing rented (owner, 2026-11-03, on the research of #574 §12; amends c).** Owner:
    *"yes i think we should copy t3 code or any other better way done by any other software … if we can make it all
    run nicely and for free awesome"*; *"if the option where you tell me we can avoid using tailscale works well then
    lets just do that … most people … will not have an always on server, so only phone and their mac, and i want that
    to work perfectly, and macs are not always on most of the time."* **f1 — The route list (T3 Code's model).** Each
    device keeps an ordered list of routes; the first that answers wins; routes learned from a connected peer are
    saved; earlier routes are re-checked on a network change, when the app returns and every minute, and the device
    moves back as soon as one works. T3's listener rule: a connection closes unless the peer address is loopback,
    private or tailnet. **f2 — No rented infrastructure, no cloud mailbox, no Tailscale requirement.** Tailscale, when
    already present, is one more route (its stable address), never required. The relay is optional and moves under
    Advanced, never a default. **f3 — D1, no mailbox:** *"we sync when a machine is on."* An outbox item that was never
    delivered never expires (amends the 7-day expiry), so no write is ever lost. **f4 — D3, a home-network door:** yes,
    with *"encryption and security above all"*: a sealed-frame endpoint only — never the HTTP API, never a token over
    it — off until a memory is shared; unauthenticated first packets dropped silently, so a scanner sees nothing;
    rate-limited; a small, fuzzed parser. **f5 — Away from home:** the router port (UPnP-IGD / NAT-PMP / PCP), IPv6, and
    the home's signed, encrypted address record in the public Mainline DHT are accepted in principle as the no-account
    way to reach the home away from home, behind a **"Reach my memory away from home"** switch, off until the person
    turns it on. **f6 — Identity is the pairing keys, not addresses:** switching Wi-Fi never means pairing or syncing
    again; a network change re-runs the route checks and fast-forwards only what was missed. **f7 — The phone, for
    now, is a capture device** (owner, the same day: *"for now, the phone i mainly want it as a way to capture, so
    wether im outside, same wifi or wherever, i can send stuff to the same queue to get digested … right now i want
    this simple approach."*): its captures reach the home's episode queue through the same route list, wait in a
    durable outbox on the phone while the home is asleep or unreachable, never expire, and apply exactly once by
    `Idempotency-Key`, under its capture-only token scope (`auth.CAPTURE_ROUTES`) and the existing capture routes. The
    full-device phone of b (ruling 38 §2's reversal) is **deferred**; a computer's copy (phase 1 B) stays as built.
    **Built in slice 1 (2026-11-03; lands in #586, which includes #572's one-transport work):** the route list (`sync_routes`), the door (`sync_door`, TCP,
    a handshake on the P-256 pairing keys, pairing a phone in the same room with the QR's one-time secret), the outbox
    rule, Tailscale as a route, the `sync_route` telemetry enums, the network-change re-check
    ([plan](../plans/2026-11-03-g132-routes.md); `network.md`, "The route list and the home-network door"). Slice 2
    (f5) is planned, not built. **Revisit** f4 if the door is ever found to answer a byte before a device proved its
    key; f3 if an outbox entry is ever found applied twice; f7 when the owner asks for the phone as a full device.
52. **Meetings are consolidated in memory (owner, 2026-11-03: "Meetings ofc should also be consolidated in memory";
    G95, G134; branch `feat/meeting-recorders`).** A meeting transcript a recorder writes — Hex's Markdown folder, any
    folder of transcripts — is an episode Sleep reads and consolidates like any conversation: one per meeting, its own
    date, through the folder stager (`meeting_transcripts`). It is **not** a `media_files` derivative: a recording or
    video the person adds keeps its words outside every bank and is never read by Sleep; a recorder's transcript is a
    conversation. **52a — speaker attribution (decided 2026-11-03 under this ruling, from the owner's facts about Hex
    relayed by the coordinator; the coordinator confirms with the owner):** a line the recorder labels `You` (Hex's
    microphone track, its Transcript reads "You 00:00") is the person's own words — `user`, counted for promotion's
    exchanges; `Them` and every other labelled speaker is someone else's, never the person's (`speaker:<label>`); the
    recorder's model-written Summary is `assistant`, never the person's words and never an exchange. A folder of
    transcripts follows the same convention, `Me` included (`meeting_transcripts.OWN_LABELS`); no name is ever guessed
    to be the person. Wispr Flow keeps its shipped rule (a label in the person's own listed names is `user`, R-LS22).
    One meeting is one episode, keyed on Hex's own file (never renamed by Hex), its timestamp the meeting's start
    (ruling 39). **Revisit** 52a if the owner says otherwise (flipping a label re-renders the existing meeting episodes
    in place, body changed, re-queued), or if a recorder is found whose `You`/`Me` is not its own microphone; 52 itself
    only if a meeting's words are found to leave the bank or to be credited to the person without a recorder's mark.
53. **GitHub connects with a code, and every repository the person owns is a page on sync; a project lists its
    repositories (owner, 2026-11-03: "there shouldn't be added manually, always sync and make their initial markdowns,
    and develop them if needed. Also a project might reference several repos so take that into account." and "why are
    you asking for a token for github? cant we just do oauth? like a connect?"; G230; amends ruling 36 D4 and ruling 45
    for repositories; branch `feat/g230-oauth-sync`).** **Connecting:** GitHub's device flow for Cicada's own GitHub App
    — a short code entered at github.com/login/device, no client secret, no server of Cicada's; the client id is public
    and ships in the build; the token (8 h, refreshed with the client id alone for a device-flow token, a 6-month
    refresh token) is kept in `secrets.env` like every connector credential, never in a bank; Disconnect forgets all of
    it and says where GitHub's own grant is removed. **A GitHub App, not an OAuth App,** because its permissions are
    read-only (Metadata and Contents read on repositories, Starring read on the account) where an OAuth App reaches a
    private repository only through `repo`, full read and write; the cost is a second step — the app must be installed
    on the person's account to see their repositories (GitHub: "The app can only access resources in an account where
    it is installed"); stars need no install. Until the owner registers the app (one link,
    `github_auth.register_url()`, plus "Enable Device Flow"), the pasted token stays as a fallback behind "Use a token
    instead", never the default (registered 2026-11-04: the build ships its client id; the fallback stays behind its
    disclosure). **Repositories:** every repository the person owns gets a `media` page
    (`media.kind: repository`, `github.owned: true`) on each sync, with a first markdown — description, a summary from
    its README (read once, when the page is born), link, language, topics — that Sleep develops like any page; never by
    hand: the paste-a-link add and every per-row "Add" are removed (no strong reason to keep one for anyone else's: a
    star brings it in). Starred repositories keep their quiet pages. A repository page is not a project page.
    **Projects:** a project lists its repositories (`repositories: [{entity, url, how, by, day}]`, `github_repos` the one
    writer; each repository page names its projects back in `github.projects`); a link is made by the person's act or a
    trusted agent's (`cicada_link_entity` on a repository page) from either page, or by Cicada when the hook's D2a salted
    origin hash of the ONE project's own checkout is the repository's (`how: origin`, Cicada's own commit) — never by a
    name alone (a suggestion). The person's unlink is remembered (`repositories_removed`) and nothing automatic puts it
    back. `repos:` keeps its meaning (local checkouts). **Existing banks:** each own-repository row with no page gets
    its page on the next sync — one page and one index-only save episode each, in the sync's commit; a page the person
    merged follows its redirect and one they removed is never made again. **Revisit** if a GitHub App user token stops
    needing an installation for the account's own repositories (the install step goes), or if the person unlinks most
    of what the origin rule links.

55. **DECIDED, owner 2026-11-05 (coordinator's proposal from the owner's message of 2026-11-04; G81, G154, G179): a
    number the person gives for someone consolidates onto that person's page as a token; the digits stay in a vault on
    this Mac, outside every bank.** The owner texted an agent the numbers of two people and expected memory to map each
    to the right page and follow a change. Today it cannot be relied on: the chat scrub destroys a `+` number before
    storage, a bare digit run reaches the bank and the engine in clear, and a model already writes `phone` claims with no
    rule. Measured on the live bank by the coordinator (counts only): 86 Messages episodes hold 13 `[redacted]`; the one
    processed episode naming those people holds one bare run and no `+` form, so whether it worked depended on how the
    person typed it; 5 of 299 person pages carry a `phone` claim; 365 of 370 waiting cards have a number the backend
    never sees.

    **The real options.**

    | | Claim in the bank | Outside every bank, nothing on the page | Hashed for matching only | **Token in the bank, digits in a vault (built)** |
    |---|---|---|---|---|
    | Page knows the number, and that it changed | yes | no | that one exists, not what | **yes** |
    | The app can show it | yes | yes | no | **yes** |
    | Git history holds it for good | **yes** | no | no | no |
    | A model reads it | **every engine, every read** | no | no | no |
    | A handed-over bank or a replica carries it | **yes** | no | no | no (a cost, below) |
    | `/v1`, the remote connector, recall | each needs its own filter, for good | nothing to serve | nothing to serve | **closed by construction** |
    | Evidence and supersession through the claim layer | yes | no | partly | **yes** |
    | An unsalted hash is brute-forced from the bank (about 10^10 phone numbers) | n/a | n/a | **yes, unless keyed outside** | no: the key is in the vault |

    **Recommended and built: the token.** It is the only option that keeps the claim layer's whole value (a page, located
    evidence, validity, supersession, held names, questions) while no door has to remember a rule: a door can only leak
    what the bank holds. The cost is real and is question (d): a handed-over bank carries "a number", not the number,
    which CLAUDE.md's portability rule counts against it.

    **The switch and where a yes lives.** One file, `$CICADA_HOME/numbers_switch.json` (`{on, at, by}`, 0600), which every
    process on the Mac reads, so a stdio MCP server and the backend can never disagree. Never an environment variable: only
    `api/main.py` loads `api/.env`, and no install path puts one in the plist. `cicada numbers switch --state on` (refuses
    from an agent's shell) or `PUT /people/numbers/switch` writes it; nobody hand-edits a file. **The record says `by: api-token`,
    never "person": the route can't tell the person from anything else holding this Mac's API token, which can flip the switch
    or call `new-vault` the same way.** **The owner's yes is recorded there on his
    Mac and as this ruling's status here.** A release stays off for testers until he says otherwise: a Settings row is the
    follow-up that would make it theirs to choose.

    **What counts as a number (cut down to what is explicit, acting owner 2026-11-05: four reviews each found a new
    digit run beside a word wrongly read as a phone, and exception lists can't win that).** A token replaces the
    digits in the stored words for good, so a miss costs digits in clear, which is today, and a wrong match is a
    person's words rewritten (`_spans`). In the person's own line: (a) a phone word tied to the digits by a verb of
    being and nothing else ("her number is N", "su teléfono es N", "mi celular N", "phone: N", "número de teléfono N",
    "mi número de contacto es N"); a bare number word needs an owner (`_WHOSE`: my, her, su, a capitalised "Ana's"),
    and `número de <any other word>` is nothing, "el número de Ana" included; (b) "add" or "save" (`_ADD_BEFORE`), up
    to two words, then a capitalised word right before nine digits or more that end the clause ("add Ana, N", "guarda
    a Ana N"); (c) a change said with a phone word ("changed her number to N", "su número cambió a N", "from N to M");
    (d) a run of nine digits or more the vault holds (`_known_runs`), standing alone, outside a link. A `+` or
    bracketed shape counts only inside (a) or (b); elsewhere the chat scrub blanks it, as it always has. In anyone
    else's line only (a) with a phone word somebody owns (`_OWNED_RE`), and (d); never a name, a pronoun, an unowned
    phone word or (c). `_NOT_A_PHONE` stays as a veto and never makes a number; a date with a real year, an IP
    address, a year list, a time range or a price shape never counts (`_plausible`). Nothing reads the bank's pages.
    Shorter runs never match by value, so an agent's echo of a 7- or 8-digit number stays in clear. The vault holds
    what the person gave, what a model took as a phone from the person's own line (`take`), an agent's phone-labelled
    claim on a person's page or a new one (`claim_value`; its sentence never adds, `clean_prose(keep=False)`; any
    other page's digits are not this rule's), and what `clean_page` found in a person page's text by this same rule;
    never a number Stage 1 read only in an agent's or another speaker's line. **Given up:** "Ana N" with no add and no
    phone word stays in clear, as do "she's on N", "call Ana at N" and "the old one was N"; such a number is filed
    only if the model reading the conversation calls it a phone, as a token, the line untouched (one real Sleep: it
    did not). **Still a wrong match:** "add Tesla N", "vendí mi celular 1500000", from someone else "tu número es
    1500000". The vault keeps the digits with no way to remove one entry from a healthy vault, and on anyone else's
    line a wrong match is a redaction with no copy. **Stays in clear, on purpose, as today:** the above; a line that
    is only digits; 7 or 8 digits after "add" or "save"; two long numbers with only a space between them (a pair of 15
    digits or fewer reads as one number, one token); anyone's line with no owned phone word and no run of 9+ the vault
    holds; a body stored before the switch; a harness session's or a note's body.

    **A stored line never moves** (`_is_stored_line`): the comparison never re-runs the rule, it retokens the posted
    line by value against only the stored line's own tokens (`_retoken_any(only=)`), so nothing that changes after a
    line was stored can move it: the bank's pages, the vault learning a run beside it, the switch, a lost vault (then
    the line's shape decides). **A copied bank with no switch file** is a true no-op: a line this rule redacted comes
    back with digits on a re-post when the conversation holds no token.

    **One number, one fact, no loss.** The token is an HMAC of the last nine digits under the vault's key, so a number
    written two ways is one token. Two numbers sharing their last nine digits (two country codes) get two tokens, keyed on
    all their digits, and the vault keeps every written form of each.

    **How it reaches the page.** In the person's own new lines of a ticked chat, the number becomes `[number:<ten letters>]`
    before the stager (`phone_numbers.tokenise_batch`). Stage 1 is told what a token is only when the conversation holds
    one, and files it in `values`; `take` keeps an entry only on the person's own located line, whatever the model quoted
    (measured at haiku: it copied the ten letters without their brackets, so entries are read against the tokens the
    conversation holds). A phone-labelled value in digits from a writer with no chat scrub becomes a token too; "membership
    number" or "order number" stays what it is (`is_phone_label`, every word must be a phone word or only qualify one).
    A number with no page is held (`pending_store`), never a page on that alone. **A person's page goes through one check at
    `markdown_parser.write`, while on**: a token this vault minted and a number leave its prose (kept in the vault, said as
    "a number"), the claims fence and a link's target untouched. Any other page, and every page while off, is byte for byte.

    **What "changed" means (`read_line`, `claim_reconciler._place_number`, no model). Prefer wrongly asking over wrongly
    closing.** Each number is read from its own clause, and the word must be said of the number word, next to it:
    "her new number is", "changed her number", "her number is now" close the one it replaces (the one the line names, else
    the only one held; with several and none named it asks); "her work number", "also has" sit beside it; "her old number
    was", "changed from … to" are history; "I was talking to Ana, her number is", "new job, her desk line is" and "Ana now
    uses" say nothing, so they ask. The same token reinforces, so a restatement can never make two current numbers. An asked
    number waits closed on the page (`context: number_asked`), so nothing reads it as current and saying it again does not
    ask twice. The question recommends nothing, because it asks when the line did not say; the answer is the two-claim path
    (`kind: divergence`), and one given after the old number was itself replaced stays history. A number the person
    confirmed is closed only by the person. A drain's order is handled: an older change read late is history on arrival.

    **An edited conversation (G104).** Rewording a line keeps its number (Stage 3's `revision_restated`). Fixing a typo in a
    number supersedes in place with no question, because the source corrected itself: never no open number. Another
    conversation's different number still asks.

    **Who counts.** Only the person's own lines. An agent's reply is redacted only for a phone word somebody owns or a run of 9+ the
    vault holds, and is never filed: its echo is not evidence. **A
    correspondent's "my new number is X" is redacted too and never reaches a page**: it is not the person's
    word, it is exactly the shape of the "hi, it's me, new number" fraud, and the person who believes it can say so in
    one line. A forwarded message is someone else's words. **An agent's write** may add a page's first number, as a token,
    with its own provenance, and is refused in words when the page holds a different one: an agent's word changes no number.
    Its label may be `contact`, `reachable_at`, `sms` or `signal` too, its `text` is cleaned and adds nothing to the vault, and a
    new write (`write_new`) is checked the same way: no bypass. On a page that is no person neither is touched: not this rule's.
    **The owner's own number** ("my number is…") lands on the owner's page like any other from their own line, never from
    another speaker's, never in the handshake, and never a duplicate signal. **A first-name-only page asks**, unless the
    page carries a card that holds this number; a relation's page does not (`role_people`). A number on a card another
    page carries asks. A page that is no person takes none.

    **Contacts, used for identity, never for a claim.** The app hashes a card's numbers on this Mac with the vault's key
    and posts only the hashes, to a file beside the vault: R-SR8 holds, no digit crosses the wire, and a value not shaped
    like a hash is refused. It settles a one-word name and flags a number on another page's card. It never writes or
    closes a claim, because the person did not say it. **Stopping Contacts wipes the hashes** with the waiting cards, the
    forget marker included; a client Mac's sync with no key never empties the file. **A chat's own handle is not used**, for
    now: the app already resolves a handle to one card and shows it, so a hash of it would add a fact the person did not say
    to every ticked chat for little more than a chat with no card. **G209 hears it:** two person pages holding one current
    number raise one "is A the same as B?", the record raising it as `role_people` does, so `pair_evidence` exempts it.
    Never a merge (a household shares a line), never the owner's page.

    **A vault that can't be used is never replaced.** Damaged, unreadable, or gone while the bank holds tokens:
    `VaultUnavailable`, in words (`phone_numbers.problem`, on the page and in the reveal's answer), the file kept, no new key.
    A new number is redacted as it is today; an agent's digit claim is refused in words; a number already on a page still
    reads as itself, because tokens compare without the vault. The way out is the person's: restore the file, or
    `POST /people/numbers/new-vault` (`cicada numbers new-vault`, the button on the person's Phone row), which sets the old
    file aside whole and answers 409 on a healthy one. Only real tokens count as a bank holding some (`bank_token_ids`), never
    a page or session that quotes the shape. **Trashing a bank moves its vault beside it in
    the trash, decided because trash is not deletion**: every word of the bank waits there, a bank restored by hand gets its
    numbers back (`_restore_parked`: stamped for exactly this name and holding this bank's tokens, so a new bank reusing the
    name inherits nothing), and emptying the trash removes both. A rule that deleted the digits at once would leave a restored bank
    with tokens nothing can read and refuse new numbers.

    **No mass re-read, off after on, and what is already gone.** A stored sitting is rebuilt from its own body, so a stored
    line never passes through the tokeniser; a line posted again keeps its stored words when they are what the old scrub or
    this rule made of it, with the switch on, off after on (the switch file exists, `_ever_switched`), or the vault lost. Proved through both real ingests (WhatsApp's and
    Messages' real reader): switching on and re-posting every message updates 0 episodes, no byte moves, nothing is
    re-queued; a new message on an old sitting tokens only itself; a real edit is a revision. **The 13 `[redacted]` stay
    gone**: the app could re-post them, but this code deliberately keeps the stored line, so that takes a person-started
    read. Recommended: leave them; the person can say a number again.

    **The doors.**

    | Door | What it can give | State | How it is shown |
    |---|---|---|---|
    | A ticked chat's episode body | the token; a redaction on anyone else's line | closed for what the rule calls a number; see the last rows | digit scan of every bank file and `git log -p` after real Sleeps; `test_no_digit_of_a_chats_number…` |
    | A claim, the pending store, an inbox question, `_state.md`, a commit message | the token; a question carries no token | closed | same scan; `test_the_question_carries_no_number…`, `test_item_7_an_agents_phone_claim…` |
    | Page prose | nothing on a person's page, while on: `markdown_parser._person_page_body` runs `clean_page`, whoever wrote it, the claims fence and a link's target untouched; only a token this vault minted is rewritten, so a page quoting the shape keeps it. Any other page (a company's public phone) and every page while off is not touched | closed for person pages | `test_item_7_a_pages_prose…`, `test_round_3_…`; no token in any page after the real runs. `write_document` (G148's byte-exact recovery) does not pass through it |
    | Model prompts (Stage 1, `cicada_ask`, every later stage) | the token | closed for chat bodies; a harness session's body still holds what it holds | `test_the_engine_is_given_the_token…`; `cicada_ask` on the scratch run |
    | Handshake, `cicada_recall`, `cicada_recall_detail`, `cicada_sources`, timeline, perspective, the CLI, `GET /entities`, `GET /inbox`, `GET /graph` | the token at most | closed | each called on the scratch run, digit-scanned; `test_the_handshake…`, `test_the_agent_tools…` |
    | Remote connector, `/v1` | the same tool bodies, so the token; the `sources` scope still gates the words | closed | they serve what the bank holds; the reveal route is not on the listener (`test_the_reveal_is_on_the_mac_only…`) |
    | Bank export, hand-over, replicas, the sync log, a home move | the token; **the vault does not travel** | closed, at a cost | outside the bank by construction; the replica refuses the routes (`test_item_12_the_vault_routes…`). The cost is question (d) |
    | Derived indexes, telemetry, logs, web lookups | no digit from a chat's number | closed | digit scan of `$CICADA_HOME` and the logs found only the vault; `test_a_writer_never_logs_a_number` |
    | `POST /people/numbers/reveal` | **the digits** | the one door, this Mac: refuses every device token, on no remote listener. **Anything holding this Mac's API token can call it, an agent's shell included** | `test_the_reveal_route…` |
    | `PUT /people/numbers/switch`, `POST /people/numbers/new-vault` | turns the feature on or off; starts a new vault | same refusal. **Anything holding this Mac's API token can call them.** `set_enabled` records `by: api-token`, never "person", because the route can't tell. The CLI (`cicada numbers switch`, `cicada numbers new-vault`) refuses from an agent's shell; a process calling the route is not stopped. `new-vault` on a healthy file answers 409 and changes nothing | `test_round_3_…`, scratch run 2026-11-05 |
    | `GET /people/numbers/match-key` | the vault's key, for the app to hash cards | same refusal; nothing while off or with no usable vault | `test_the_match_key…` |
    | The vault, `$CICADA_HOME/people/<bank>/numbers.json` | the digits and the key | 0600, outside the bank and git. **Any process running as this user can read it; a Time Machine backup of the home folder holds it.** It is private to the user, not locked to the app | `test_the_vault_is_private…` |
    | The trash | the vault waits beside the trashed bank, `.trash/<bank>-<stamp>.numbers.json` | gone when the trash is emptied, back if the bank is restored by hand | `test_item_8_the_trash…` |
    | The app | digits on the person's page, in the Reader and in a quote, from memory, never stored; a token it can't answer reads "a number". The page's row is drawn, and `/claims` fetched, only when `rawMarkdown` holds `[number:` | Ask's answer and search snippets still show the token. **A page whose raw is omitted (`raw_omitted`: past 256 KB, a ledger, or a fence past 16k characters, like the owner's) shows no row, on or off; the claim is kept** | `NumberTokensTests`, scratch app, both states screenshotted 2026-11-05 |
    | A harness session's or a note's body | **digits, exactly as today** | not closed, not widened; its claim holds the token | sub-question (c) |
    | A bare number in a chat with none of the rule's signals: "Ana N", a pronoun, a line that is only digits, 7 or 8 digits after an add, two numbers with only a space between them, somebody else's line with no owned phone word and no run of 9+ the vault holds | **digits, exactly as today**, in the body and the prompt | not closed: a miss over a rewritten line; a model's `phone` value for it still becomes a token | `test_these_are_not`, `test_no_line_changes_in_anyones_words`, `test_a_bare_line_stays_in_clear…`; on the last scratch Sleep those lines were the only digit runs left in a body |
    | A body stored before the switch | **digits, exactly as today** | never moved: a stored line is not re-read, on, off, or with the vault lost | `test_round_3_old_bare_lines…` |
    | The 5 `phone` claims already in clear | **digits, in git for good** | not touched; a page's clear value becomes the token when the person restates it | `same_number` |

    **Not built, on purpose:** a local agent's read as a tool (b), tokens in harness sessions (c), carrying the vault on a
    home move (d), a one-time re-read of old chats, the code in Ask's answers and search results shown as digits, and a
    Settings row for the switch.

    **The question for the owner:**

    > When you tell an agent someone's number, should Cicada keep it like this?
    >
    > **What it does.** When you give a number in a chat you ticked, and your line says it is a phone, the digits go in a private file on this Mac and your memory holds a stand-in code. Your memory's git history, other devices, a memory you hand over, the models that read your memory, and agents reading it through its tools get the code. In the app you see the digits on that person's page, in the conversation, and in a question about the number. A new number on a clear line ("her new number is …") replaces the old one; an unclear one asks you first. A number in somebody else's line or an agent's reply is never filed.
    >
    > **What counts as a number in your own line.**
    > - A phone word tied to the digits: "her number is 2025550143", "su teléfono es 2025550143", "mi celular 2025550143", "phone: 2025550143".
    > - "add" or "save", a capitalised name, then 9 digits or more that end the clause: "add Ana, 2025550143", "guarda a Ana 2025550143".
    > - A change said with a phone word: "changed her number to 2025550143".
    > - 9 digits or more, standing alone, that the private file already holds.
    >
    > **In someone else's line or an agent's reply** only two things count, and they blank the digits: a phone word somebody owns ("my number is 2025550143"), and 9 digits or more that the file holds. So an agent repeating a long number you gave is blanked.
    >
    > The file holds what you gave, what a model took as a phone from your own line, what an agent saved as a phone on a person's page or a new one, and numbers a person page's text calls a phone. An agent's sentence adds nothing to it.
    >
    > **What this gives up.** "Ana 2025550143" with no "add" and no phone word stays in clear, in git and read by models. A number said that way is not filed unless the model reading the chat takes it as her phone; in one test with made-up numbers it did not. The same goes for "she's on 2025550143", "call Ana at 2025550143", "el número de Ana es 2025550143", and a name in somebody else's line. Four reviews each found a new everyday line this kind of rule rewrote wrongly, so these were cut.
    >
    > "Order 123456789", "Tu número de confirmación es 202555015", "$1500000", a link and a date stay as they are.
    >
    > **A wrong match costs more than hidden digits, and it can still happen:** "add Tesla 2025550143", "vendí mi celular 1500000", or from someone else, "tu número es 1500000". In your own line the digits move to the file for good. Models are told a code is a phone number, so a model could file the first as the number of someone called Tesla. In someone else's line a wrong match is blanked for good, with no copy kept. You can't delete one wrong entry from a working file.
    >
    > **Counted on your memory, changing nothing:** this rule would have turned 0 digit runs in your own chat lines into codes and left 55 as they are, and blanked 0 lines from other people or agents.
    >
    > **Where digits stay as they are today, in git and read by models:**
    > - everything under "What this gives up", even if that person is in your memory;
    > - a chat line that is only digits, and "the old one was 2025550143";
    > - 7 or 8 digits after "add" or "save";
    > - two long numbers with only a space between them, after any of these (two short ones, 15 digits or fewer together, read as one number);
    > - someone else's line or an agent's reply with no owned phone word, unless the file holds that number at 9 digits or more. So an agent repeating a 7 or 8 digit number you gave stays in digits, and so does a correspondent's "Ana 2025550143" or "changed my number to 2025550143";
    > - anything you type to Claude Code or put in a note (a fact on the page holds the code, the conversation keeps the digits);
    > - a number in a person page's text with no phone word and not in the file;
    > - every chat already stored before you turn this on. Nothing old is read again, and turning this off puts nothing back;
    > - the 5 person pages that already hold a number in clear (counted on your memory on 2026-11-04). They stay in git for good. A page's current value becomes the code when you say that number again.
    >
    > A number starting with "+" or written with brackets, in a chat, with none of the above is blanked, exactly as today, with no copy. The 13 numbers already blanked in your Messages stay blanked. You would have to say them again.
    >
    > **What else it does not do:**
    > - Ask's answers and search results show the code, not the digits, for now.
    > - A page with very many facts, like your own, shows no Phone row at the top. The number is still kept.
    > - That file is private to your user account, not locked. Anything running as you on this Mac can read it.
    > - Anything holding this Mac's API token can ask for the digits the way the app does, turn this on or off, or start a new file when the old one can't be read. The record then says the token did it, not you. An agent's own shell is stopped at the `cicada` command, not at the API.
    > - A Time Machine backup of your home folder includes the file. A memory you hand over or move does not.
    > - If the file is lost, pages say "a number" and new numbers are blanked until you restore it or start a new one, and a backup is the only way to get those digits back.
    >
    > It has only ever run on made-up numbers on throwaway copies, never on your memory.
    >
    > (a) **Turn it on?** It is off now. Recommended: yes. To record it, run `cicada numbers switch --state on` in your own terminal.
    > (b) **Should an agent be allowed to ask for a number on purpose**, for instance to text someone, instead of only seeing the code? Recommended: yes, as one local-only tool, on your ask, as a follow-up.
    > (c) **Should numbers you type to Claude Code or a note become codes too?** Recommended: yes, as a follow-up.
    > (d) **If you hand this memory to someone or move it to another computer, the private file stays behind**, so the page says "a number" and a number said again reads as a new one. Is that right? Recommended: yes for a hand-over; carry it sealed when your own home moves, as a follow-up.

    **Decided, owner 2026-11-05: yes.** The feature still runs only with its switch on. **Amendment, same day (the owner's
    real message, invented here as `+1 202-555-0143`, `+1 202-555-0177`, then a line about an invite: no phone word, no name).**
    The owner: "From having contacts synced you can see who I'm referring to. Even if saved under a nickname. Names sometimes
    have hints as to where u know the person from example: Ricky (ie). That would be my friend I know from uni for example."
    With the switch on, in the person's own line of a ticked chat: (1) a number whose keyed hash a Contacts card holds is that
    card's number, whatever the line says, by value, however it is written (last nine digits; a digit run reads as a number only
    when it IS a contact's). It becomes a token. (2) A `+` number with no card is kept as a token where the scrub used to blank it
    with no copy; other speakers' lines are as they were. (3) A token that matched one card is linked to it: Sleep files the
    number on that card's page, and the person giving the number counts as naming that one waiting card, so its page is born by
    the Contacts promotion rail, a one-part nickname's too. The card's whole name reaches the model as a hint it judges. The owner's
    correction, same day: 'The "(ie)" might not be ie btw, can be something like Johnny Cerrajero.' So any word of the name may say
    where they know the person, a trade given as a surname included: no rule reads a suffix or takes a last word for a surname, and no
    word of it becomes a stated fact or a title beyond what the model reasons. An unmatched token stays a token and Stage 1 decides. Two cards on one number:
    never a guess, one question in the existing form, on a page; with no page yet it is held on a name and asks when that page
    exists. (4) The faces store is not read: the hashes and the waiting cards only. Off stays a true no-op, a stored line never
    moves, and numbers already blanked in old chats stay blanked (`storage.md`, "A number on a Contacts card").
    **Recorded, not built (owner 2026-11-05):** a local-only tool for an agent to ask for a number on the person's ask; numbers
    typed to Claude Code or in a note also becoming codes, "as long as it doesn't hurt the UX or the performance"; the file
    travelling sealed when a person's own home moves, documented, "not to work on yet".

    **Revisit** on each sub-answer (its own follow-up), or on a measured case of a number on the wrong page, of a
    wrong close, or of questions asked where the line plainly said (the word lists are `read_line`'s).
56. **A project starts only from the person or an agent on their ask; things link to the projects that exist by context
    (owner, 2026-11-04; G141, G222; amends ruling 36 D4 and ruling 45; branch `ruling-56-projects-by-ask`).** The owner's
    words: "yes, hide the project suggestions. Ask an agent to start a project or manually though the app are the better
    ways imo. then things can have a link/relation to existing projects, which can be done based on context and
    proactively by the agent." **Why:** the live install's `/projects` suggested 750 pages (705 with no reason, 39
    fallback, 5 words, 1 repository; coordinator's count, 2026-11-04), and a list nobody can clear teaches nothing.
    **Measured on the live bank, count only (coordinator, 2026-11-04):** 711 live project pages, **0 listed**
    (`mine_via` None on all), 39 fallback concepts; 14 observed sessions, 3 with a remote hash. So hiding suggestions
    leaves an empty page on day one, and that is accepted (#595: an empty list says nothing), but it decided two parts
    below. **Nothing here marks a page as the owner's in bulk:** that is a bulk bank write, the owner's to decide on
    per-item answers, and it is not built.
    **Sleep:** it never makes a project. What `project_birth` read (a repository the hook observed, the person's own
    located words) is a signal: a mention with no page goes the one way unborn names always went, a held mention below
    the promotion bar, one `concept` page marked `proposed_type: project` over it, with the signal recorded as `born`.
    The person's own words clear the bar, because they are the person's act and a held line nobody can see would lose it
    (Q4's reason stands: they cannot tell "helping with <bob-example>'s mural project" from their own, so they make a page and
    never a project). A repository alone never clears it: a checkout opened once is no page, and ruling 53 already gives
    every owned repository its own page. Stage 5 turns any `project` create into the concept, whatever a merged payload
    says. **The person's words reach an agent as an offer, not a list:** `cicada_recall_detail` and `cicada_project`, on a
    page not started, tell the agent it may offer once, in its own words, when the person is plainly working on it. That
    line is Cicada's own direction, so it stays outside the reference markers (G199), and it never becomes an inbox
    question. **Starting:** New project, `cicada projects new`, *New project from this repository* and
    `cicada_create_project` all **adopt** a page that already answers to the name (id, alias): same id, words, claims and
    history, a `concept` or `tool` retyped in place, a signal Sleep recorded kept as `born` so its sessions still tie. On
    this bank that is the only way anything gets listed, so a duplicate would be the worst failure. A person, company,
    place, repository page or the owner's own is refused by name; two pages that could be it are refused, never picked
    by listing order. An agent's create needs the ask on record (`reason` or `evidence`), or nothing changes. A harness
    on the G198 trust list starts it at once; any other client, remote always, files one `page_edit` inbox question
    (`start_project`) and only the person's yes starts it. An agent never starts a page the person took out; the person
    can. A start is a mention: it revives a faded or archived page, or the page would be listed and missing from what an
    agent is told. Remove gives a retyped page back as it was (`started_from`). **Reachable:** nothing is archived, deleted or
    retyped in bulk. The other pages stay reachable by search, the
    graph, recall and `cicada_project`; a page not started shows *Add to my projects* on its own detail, and a listed one
    *Remove from my projects* in its menu, the only new doors and each replaces a larger one. `/accept` and `/dismiss`
    stay. `GET /projects` sends only listed rows and an always empty `suggested` / `dismissed`, kept one release for a
    client built against g141-7..9 (remove after 0.9). A ChatGPT grouping with no page is no longer offered; its id stays
    on the episodes, so a later door can use it. **Follow-ups (owner, 2026-11-04: "Yeah only projects I started."):** one
    is raised only on a project the person started. One already pending on a page not in their list (never started, or started and removed) is retired on
    Sleep's next tending pass (`not_started`, nothing written, listed under "Settled by Sleep", undoable, and once undone
    never retired again), never just deleted, and holds no slot of the three. **Imported Claude projects (owner, 2026-11-04:
    "Yes imported Claude projects are mine."):** they stay listed; that settles the addendum's open question to ruling 45,
    and `CLAUDE_EXPORT_MINE` is no longer the acting owner's to flip.
    **What an arriving agent is told (coordinator's correction, 2026-11-04):** the handshake's "Current projects" holds
    what the person started, then "Recent project pages, not started as projects" up to the same 7 rows. Matching the
    list literally would have told every agent on this bank nothing on arrival; calling those pages the person's would
    be untrue. The `projects` hub stays a map of the page type for the same reason.
    A start, accept or removal in the app, or a repository link, refreshes `_state.md` right after its own commit, so the
    next session has it; a trusted agent's `cicada_create_project` runs in the MCP process, which never writes the
    projection (R4), and shows from the next refresh.
    **Links, automatic or proposed:**
    | Link | By, on what | Which | Why |
    |---|---|---|---|
    | A session in a repository the person or a trusted agent named on the project, its checkout pointing there now | Cicada, on the hook's salted origin hash | Automatic, derived on read | A fact, and they named the repository, which is why D2a's "a shared remote ties nothing" does not apply. Cicada's own `how: origin` link names nothing and ties nothing this way. A remote the checkout has left ties nothing |
    | A session in the page's own checkout family, or a folder named for it | Cicada, on the hook's observation | Automatic, derived on read | Ruling 45 Q8, unchanged |
    | A repository whose origin is the one project's own checkout | Cicada (`how: origin`) | Automatic, only on a project the person started | Ruling 53; a page not started gets nothing it never asked for, and adopting one links it next sync |
    | A conversation or page, by an agent on the trust list, in the conversation it is in | That agent, with its one-sentence reason | Automatic, at once | G198; the agent read the conversation, and the row shows who and why |
    | The same, by a remote or untrusted agent | That agent, with its reason | Proposed, on the project's page, never counted until taken | G198 and D5; `conversations_added` gains `proposed` as pages had it. No inbox question: the inbox holds 582 |
    | The person's own words naming the project | Sleep's read, located, their turns only | Automatic, derived on read; a one-word name needs 2 mentions | Q8, guarded: below |
    | A claim on the project naming a page, an event's participant | Sleep's explicit claim | Automatic, derived on read | Decision 10, unchanged |
    | A mere co-mention | Nobody | Never | Ruling 45 Q8, D5; the owner's "based on context" means an agent's judgement, stated |
    Every agent's row carries `by` and `reason` (scrubbed, shown on hover), every link comes off in one act ("Not part of
    it", "Not about this project", Unlink), and a removal holds against every writer (`conversations_removed`,
    `entities_removed`, `repositories_removed`). **The one-word guard:** a one-word name is also an ordinary word, so it
    needs two mentions in the person's own turns; never by case, because the person may type in lowercase. **Measured,
    synthetic only:** a corpus and labels written for this (470 conversations, 190 labelled as about a project;
    `tie_reasons`, seed 56), so the rates describe that mix and show the mechanism, not any real bank. One ordinary word,
    one mention tying: precision 0.36, recall 1.00; two mentions: 0.84, 0.80. Several words, unchanged: 0.80, 1.00 (a
    passing mention still ties). Listed repository: 30 of 30 tied, 0 of 40 decoys in a re-pointed checkout. Real precision
    cannot be measured until something is listed. The recall cost is real: a short conversation saying a one-word name
    once no longer ties, which the agent in it can fix. **The primer** names the three tools in one sentence (ruling 45's
    Option A is amended) and pays for it with phrases each tool's schema already holds, so the state block keeps its
    room; contract 25, remote 16.
    **Revisit** when the person has listed 3 or more projects (measure the `named` rows they untie, and whether the guard
    misses what they re-tie); if they turn down most of a harness's links (the trust list is wrong for links); or if they
    ask to mark pages in bulk, which needs per-item answers first.
66. **A slow answer is busy; a hung backend still updates (owner, 2026-11-05; G182).** The owner's words: yes, a slow
    answer is busy, and "the problem you describe... should be taken into account and resolved". The updater read a
    `/sleep/status` timeout as nothing running, so a slow answer during Sleep let an update stop the backend mid-batch (a
    review measured 2.22 s against a 2 s limit, after the stall fix). A test deliberately kept a hung backend updatable,
    since an update may be its fix, and both must hold. **Decision:** only nothing listening is idle. Hung
    (`BackendSilence`) takes three looks at least ten minutes apart with no real answer, two hours from the first to now,
    and no drain's `running` record touched in those two hours; the looks are on disk, so they outlast a quit. **Why these:**
    two hours is about seven of the longest batch measured (about 17 minutes), and being wrong costs at most that batch,
    while waiting costs a late update. The record is the drain's own progress; CPU was rejected because a drain waiting
    on a model looks idle. The person's click may go past Sleep on one line naming the cost; an automatic install never
    does. **Revisit** if a batch is measured past two hours, or a hung backend is seen holding an update.
68. **An item the person added is a page; its words stay outside every bank (owner, 2026-11-05; G43, ROR-117).**
   The owner: "being able to play videos, audios, see photos, etc all possible in the app, which all as entities have a
   markdown attached to it which can have the summary, why its relevant, if there is a transcription available anywhere
   (which we have to put the model that transcribed it as the contributor)." (a) Amends ruling 62 and "never read by
   Sleep": a file the person added, or a recording from a source they turned on, is not a save with no reason, so it has
   a `media` page (`media.kind: file`, `media_pages` its one writer) made by file and git work alone, never at capture and
   never by Stage 1, quiet until a conversation names it, evergreen, never a project (ruling 56). (b) The page holds title,
   kind, its own date (`recorded_at`, ruling 39), the file id, length, language, who transcribed it, and two empty sections
   a later change fills. **The transcript is not in the bank or git** — an hour of speech committed could never be
   forgotten and would break the delete promise; the page draws it at view time from the store
   (`GET /files/{id}/transcript`), and it stays the recording's words, never the person's own. (c) Naming the transcriber
   as a contributor is provenance, the owner's exception to the provider-neutral copy rail, said only when a transcript
   and a name exist. (d) Delete and a store's tombstone retire the page in one commit (the person's name for their delete,
   Cicada's otherwise); git history keeps the page's earlier versions, never the words. (e) **Amended (ROR-117 3b, branch `ror117-read`):** Sleep, or the
   person's `Read it now`, reads an added item's words once per version of them, in one bounded call (the first 30,000
   characters, the Summary saying "Read from the first N minutes" when it did not reach the end), for prose only: the
   Summary and a Why it matters that code keeps only if it names a page the words found. No claim, question, page, link,
   mention or episode; a section the person or an agent wrote or pinned is never overwritten and, when both are theirs,
   no read runs; a failed read is retried at most 3 times, 12 hours apart; an item with no words gets no action
   (describing a picture needs an engine that takes images, undecided; so does whether a voice memo counts as the
   person's own words). **Trigger to revisit (b):** the owner asks for the words in the
   page's markdown, knowing a committed transcript cannot be forgotten.

70. **The inbox is ordered by the expected change in what gets read, on real reads (owner, 2026-11-06; G113, G115).**
   The owner: "the questions should have in order the impact they might have on current accesses knowledge, and things
   that might have big impact." and, asking for the work: "focuses on doing the PR for the impact score and all that stuff
   that you're recommending. Maybe it can come up with a better formulation to estimate impact." Home was about to show
   one lead question, so whatever ranks first is the only one seen. **Second request, same day (staleness and one order):**
   "the questions in regards to the amounts of <a-payment> are extremely old and in this case shouldn't they
   be lower impact? The impact formulation should apply to the question queues in all entities." (a) **The order** is `question_order.Tables.score` =
   p × stake ÷ effort × (floor + exposure) × √seen, derived on read, one function for `load_inbox`, `inbox_catchup.select`
   and `mode="ask"`; the stored `priority` stays on disk and on the wire and no longer moves the order (the app used to
   re-sort `GET /inbox` by it, so the old server-side use-weighted order was never seen). Four formulations (old; additive;
   product without visibility; this) were run on twelve argued pairs (eight, then four on staleness), each with its reason in `test_question_order.py`;
   this one passes all twelve, the old one one, the additive two, the product-without-visibility eight (measured table in
   `features.md`). (b) **Every
   constant is judgment**: the person's own recorded answers number two across all banks, so nothing is fitted. The
   `impact` bucket on every `resolution` row (G113) is how a human checks them later; nothing learned from it is
   auto-applied. (c) **Staleness lowers impact** (replaces the earlier "stale-escalated conflict is p .5"): `score` × `freshness`, where
   `fade = max(.05, ½^(age ÷ half-life))` and `freshness = relief + (1 − relief) × fade`. Age counts from when the thing
   was SAID (a conflict's freshest option: `source_refresh.said_on` of a claim on the page, the conversation an option
   names for a claim only it holds, the question's `source_episode` for an option with no claim; a divergence,
   clarification or follow-up: its `source_episode`'s date), never `last_referenced`, `created_date` or `updated_date`,
   which a re-reference or a re-asked question bumps, and never a claim-less option's `observed_at`, which is the raise
   date (120 of 153 on one bank). A memory export entry or feed item is only "no later than". The half-life is the page's decay
   rate through `decay_policy.resolve` (durable ≈ 243 days, active ≈ 97, volatile ≈ 32); an evergreen page never fades
   **except the owner's, which fades at the `active` rate** (its class means "never archived", not "every fact stays
   true"); relief = the largest `reads_fraction × visibility(N)` over the question's pages, so an old fact in daily use on
   a small page stays fresh and a huge hub opened daily does not rescue every old fact on it. Not faded: who someone is
   (a pair, `asks: name`, a held-name release), `decay`, and anything that is not a fact someone said (removal,
   normalization, page edit, sources review, `sensitive`). A timeless fact on the owner's page fades; with the counter
   off or empty relief is 0. Judgment like the rest. **One order everywhere:** every place that sorts or picks questions
   goes through `question_order` or `orderIndex` (`features.md`, "One order everywhere"), and
   `test_question_order_gate.py` fails on a new sort by raw priority. (d) **The read counter is not the telemetry
   ledger** (`page_reads`, `$CICADA_HOME/page-reads/<bank id>.db`, outside every bank): the ledger's rail ("nothing learned
   from it is auto-applied") would be broken by an order learned from it. No query, no text, a day's largest weight once a
   page a day (opened 1.0, shown .25, half-life 30 days, saturating), **today's reads count from tomorrow** so the order
   cannot move in a session or feed back the same day. Not counted: the hook's automatic injection (picked by the person's
   words, which `page_use` already credits), `cicada_backlog`, Sleep, Cicada's own spawns (`CICADA_CAPTURE=off` /
   `CICADA_RECALL=off`), a demo bank, a replica. **(e) Telemetry coupling, decided:** `telemetry.enabled()` false makes the
   counter a no-op (nothing written, table empty) and the order runs on `page_use` alone; no new setting (`CICADA_TELEMETRY`
   is an environment variable, not a person-facing switch; a disagreement between processes can only undercount). (f) Per
   memory, named by the bank id; never served by any route, tool, `/v1`, export, sync or replica; the remote door's own
   order is computed without it; a missing, wiped or corrupt file is an empty table; deleting a bank deletes its file with
   its `-wal` and `-shm`. (g) **Wire:** `orderIndex` on every `GET /inbox` item; the app sorts by it when every question
   has it, else by priority then newest, decided for the whole list (a per-pair rule is not transitive). **Not built:**
   the app's `surface: "inbox"` (a card opened from a question must not count: the next-day delay and one count a page a day
   are the guard), the climb's `HomeQuestions` / `HomeSections` comments. *Why:* a question that changes dozens of facts
   on a page nobody reads, and one that changes two on a page read daily, tied under "priority + 0.5 × use". **Trigger to
   revisit (a, b):** the `impact` buckets show the person answers the low ones as readily as the high ones over a few
   hundred answers, or the person reports the first question is wrong; **(d, e):** a request to count with recording off.
72. **A site's terms do not decide whether the person's own agent reads their own list in their own browser (owner, 2026-11-06; ROR-128).**
   The owner: "i still dont get the connections like import a file for goodreads. why? no one is going to do it like
   this." and "don't care so much about if good reads terms or any other websites terms allow for it. Because in the end
   it's just a browser harness that we're running... in my personal browser." and "for good reads I think the browser
   should be there before exporting a file." (a) **Amends ruling 47 and G232:** the browser path no longer waits on a site's
   terms. The limits that stay are the existing ones: the person starts it (the switch, off until they turn it on),
   it is their own signed-in session, reads stay low-rate (one site's list at a time, ≤ 10 reads a UTC day), the page says
   it reads through their browser, nothing is clicked that changes the list. (b) **Lifts Spotify's "never"** (ruling 47's
   2026-10-29 row, G232): Spotify's library is a saved list (`saved_lists.PLATFORMS["spotify"]`, origin `spotify-saved`,
   index-only, ruling 30) like the rest. Its Developer Terms still rule out an API *connector*, which stays unbuilt.
   (c) **Browser first, the file after it** on a source that has both: Goodreads' page leads with *Read through your
   browser*; the export stays a quiet fallback. (d) **The backend's ToS rail is unchanged:** it never fetches a page
   behind authentication and never signs in; this ruling is about the person's own agent and browser, never Cicada's
   server. (e) **Goodreads is books, so it is chosen:** the agent's read is held outside the bank (`goodreads_waiting`)
   and the person picks with #666's pick list before anything is staged; a book left out is never asked about again. Both
   doors write one episode per book (`goodreads:<Book Id>`). *Why:* the owner's test of a connection is whether a person
   would do it; nobody exports a CSV to connect a library. **Trigger to revisit:** a site actively detects the person's own
   browser session and restricts their account for it (measured, not assumed).
   **File-first sources still to move to the browser (listed 2026-11-06, none built here):** Letterboxd (diary and
   watchlist; its RSS stays), Goodreads' *shelves with highlights* beyond the first pass, Amazon/Kindle highlights, Apple
   Podcasts and Pocket-style read-later (Pocket closed in 2025, so a file only), Notion's and Google's exports where the
   API is not offered, Facebook and Threads saved items, Strava/Fitbit-style activity exports, and chat exports (their own
   row, ROR-126). Each needs its page, its item shape and its own "never click" line before it joins; none is assumed.

69. **A rename at the source renames the thing in Cicada, for every source (owner, 2026-11-05; ROR-122).**
   The owner: "I think these two-way updates should be in all sources. So if a voice memo changes the name and stuff,
   like I think this stuff should be synced and they should change names, don't you think?" (a) The newest name a
   source reports wins and the old name stays as an alias, so old mentions and searches still find it. (b) A name the
   person set in Cicada wins and stays until they change it; the marks are `name_by` (the app's and the agent door's
   rename) and a `name` that is no longer the one a source wrote (`name_source`: a hand edit). A page with no mark is the
   source's. (c) Source into Cicada only: nothing is written back to any app. (d) Two doors for one thing: a door counts
   only when its name CHANGES against what that door reported last (`names_seen`), so the door that last changed wins and
   a door repeating itself never flips the page; a door's first word on a page is a baseline, not a rename. Amends "the
   first real title stays" in `books.ensure_page`; ruling 67 stands (a rename neither splits nor joins pages). A rename is
   no mention (no claim, no promotion, no decay reset, no question, dates unchanged); the id and file name never change;
   a removed alias is never re-added. It applies on the source's next sync that reports a changed name, one commit per
   sync at most, as `cicada`, never over a first pass of a whole bank. *Why:* a first real title stayed forever, and a
   Voice Memos recording renamed in its app was never seen again. **Not built (listed in the PR):** Apple Notes, Calendar,
   Reminders, Linear, Notion and chat names are episode titles, which now follow a title-only change
   (`episode_staging`); the table is in `capture-and-sleep.md` ("A rename at the source").
   **Trigger to revisit:** a person's name overwritten by a source (a mark missed), or a rename flip-flopping between doors.

71. **A book the person added may be read for what it is, and found by its title (owner, 2026-11-06; G233, G39; amends 61, 62, 64).** The
    owner's words: "I think the ruling change should be applied for books because reading the description of a added book is
    important for memory. Like it's the bare minimum in terms of relevance for why it's there in the first place. And to be able
    to surface it in the future." and "if we only get the title from Apple Books, for example, or the ISBN, we should be able to
    link it the same way we search with an ISBN the book and have a description and stuff." **(a) The description is the book's
    bare relevance.** Sleep may read the public description of a book the person added, once, bounded, so the page says what the
    book is and why it may matter and recall, Ask and linking can find it. It does not allow: reading the book's text; making
    anything the person's own words (a description is `external`, cited, never their opinion or a sign they read it); a
    question about it (a quiet page stays quiet until mentioned); a link from co-mention; a metered key nobody chose (ruling 31).
    Marks work as ruling 64 says. **Built here:** the description reaches the page (G233) and is found by recall and Ask by
    words and meaning with no model; **also built (`book_why`):** one bounded Sleep read per described book, once (`book.why_at`), the
    description cut at 700 characters, 20 books a run, one call of about 253 input and 45 output tokens (counted by
    characters / 4, not yet billed on a live run; the owner reads the figure before any backfill), one sentence on
    `book.why` that "not this book" also removes; a cover from a title match is drawn by the catalogue's cover id, never a title. **(b) What relevance can do at linking:** nothing by itself. Under ruling 56 a link
    needs a recorded fact or an agent's stated reason; the description is what makes either findable and checkable (an agent that
    recalls the book by its topic can cite its words as the reason), never a link made because two things sit near each other.
    **(c) A title can find the book** (amends 61's "never a title", which gave two reasons): the second ("sends the reading list
    out") is answered by the owner's decision — a book the person chose to add, from a door of their own (Apple Books,
    Goodreads), with no ISBN and an author, sends its title and its first author to the same keyless Open Library search
    behind the same gate, paced at one request a second, cached outside every bank under a hash, no identity sent. The first
    ("a guess at a work") is answered by a confidence rule with no fuzzy step: the page's title (or title and subtitle) equals a
    result's once case, accents and punctuation are set aside, AND every one of the page's authors is among the result's, AND the
    results name exactly one work (several editions of one work are one match, the least valid ISBN-13 taken); two works, no
    author, no ISBN or anything less leaves the book with no description and no question. The match gives description,
    year, pages, publisher, subjects and a cover id; the page's title, authors and ISBNs never change, so a match never joins two
    pages. `book.title_match` marks it; **"Not this book"** (`POST /entities/{id}/book/not-this-book`, a button in the box) takes
    the description back and the page is never matched by title again. A title never leaves for a book the person did not add
    (a scan has an ISBN; a placeholder, an author-less entry and a conversation's mention are never searched). **(d) The box:**
    the description is a small settled summary under the head with its source named (DESIGN_RULES §9, 2026-11-06). **(e) Existing
    books** are not backfilled: `GET /sources/books/backfill-plan` is a counts-only dry run; the owner reads it before any run.
    **Measured** (Open Library, live, 40 well-known public titles with Apple-style variants, 2026-11-06): 17 matched, 14
    ambiguous (Open Library holds duplicate work records for the classics; held back by design), 9 none (surname-only authors,
    "Dune: Deluxe Edition", two invented titles: none expected to match); 0 of the 17 matches named the wrong work by title and
    author. An import of N books with no ISBN costs about 5 s each (1 search + 3-4 ISBN requests) and no model.
    Revisit on: the owner overruling the confidence rule, or measured wrong matches.
74. **Sleep joins two people pages when two independent signals agree (owner, 2026-11-07; ROR-136, amends rulings 29 and 41's "a question only").**
   The owner agreed to Sleep joining pairs he would spot at a glance, and warned: "I remember you mentioned some pairs that
   I'm pretty sure have nothing to do with each other." (a) The signals are kinds of evidence, counted once each
   (`person_duplicates.INDEPENDENT`): the **name** (sound, spelling, a short name inside a full one — all one, so two names
   that merely sound alike never join), one page **listing the other's name** as its own, the same **contact** (an account or
   link both pages carry), a shared **rare belief**. Two different kinds are needed. (b) The pair must also be clean: never
   named together in a conversation (ruling 65 c), no conversation naming both raised it, neither page titled by a relation
   to the owner, neither page in any other candidate pair (a page that could be either waits for the person), score ≥ 0.6,
   not the owner's page, nothing the person called two people or split. (c) The join is the question's own settle
   (`inbox_tend`, rule `two_signals`): the same resolver the person's one-tap merge uses, Sleep's commit, listed under
   "Settled by Sleep", undone with one tap and then never settled again. (d) What does not qualify stays an ordinary
   question. *Why:* a dry run on a copy of the owner's bank listed 12 candidate pairs; 2 qualify, and the ones he named as
   surely two people (a given name that sounds like another's, with nothing else in common) are one signal. **Trigger to
   revisit:** a wrong join the person undoes, measured.

73. **Questions Sleep may assume, and none loses a value (owner, 2026-11-06; G98, ROR-31).** The owner's words on the dry run: "Take the recommendations in dry-run.md for decisions 1 to 8. The four 'part of' items (1830, 1831, 2343, 2346) are moves: the latest stays current, older ones close. Items 1898 and 2267 stay open as questions. Drop the same_conversation rule. … A new contradiction opens its own question, if that stays small. Leave the 37 existing piled-up questions alone and don't touch fading." So: the same value said two ways is one value; a `part-of` said on different days is a move; the value a question alone held is written closed, never as the person's act, whenever the question ends; Sleep adds no page line when no value changed; two values from one conversation are not assumed compatible. Evidence: the dry run (real text, outside the repo): 11 of 11 respellings right, 6 of 9 same-conversation settles wrong. Revisit on: a measured wrong settle from one of these rules. A note: this reverses #672's test that a pick writes nothing for the other value — the other is now written closed.

67. **One book is one page whichever door it came in by; the Mac adds books by number or camera (owner, 2026-11-05; G233, ROR-116).**
   The owner: "yes ofc i want books on the mac and it has to have some overlap with potential books from ibooks." (a) Amends
   review-of-#600 B1: after an identifier (ISBN, work id, a source's id) fails, **exactly the same** title (or title +
   subtitle, or a source's own spelling) and author set, with case, accents and punctuation set aside, joins a record to the
   one page that holds both — never a prefix, an article, a series note or a likeness, so "Dune" and "Dune: House Atreides"
   stay two. More than one page, or an author a side lacks or only partly shares, never joins: the record keeps its page and
   the inbox asks "same book?" per candidate (≤ 3, answered by folding, never silent). The same title by other authors asks
   nothing. A join only adds identifiers, aliases and the source's id: marks, status records and history stay. Both orders
   and editions are one page. *Why:* an Apple Books entry rarely has an ISBN (1 of 284 on the owner's Mac), so identifiers
   alone made a second page for the one book held in both. (b) The Mac adds a book through the phone's own
   `POST /capture/isbn`; the camera opens only on the click, shows its feed, takes the first valid book barcode with no
   shutter and stops; frames are never stored or sent. (c) A book's page names its doors only when it has more than one.
   (d) A Books tab on Clusters is not done: tabs are keyed by entity type (a closed set of 10) across the grid, rows and
   menu. **Trigger to revisit (a):** a real wrong join measured, or the same-book question asked often enough to be noise.

65. **A question rests on the model's stated stake; any skill takes 2+ conversations (owner, 2026-11-05; G239, PR #623).**
   The owner: "I don't think that with stuff like this there is any benefit of answering when nothing really depends on it.
   Tho there are some questions like an ongoing project that may not be relevant right now, but will be in the future, maybe
   these are important to resolve." (a) Stage 1 says what rests on a question (`ask_person`); a low confidence asks nothing;
   a thing still in motion that will matter later is a stake, a list of names with nothing depending on them is not. A stake
   on an existing page raises its question there, one open per name. (b) Any skill needs 2+ conversations, and two notes count
   as two. (c) Naming two people together is evidence they are two: the judge's UNSURE on names sharing nothing asks only on
   a line naming both that the judge reads as one person (`pair_evidence.names_tied`). A one-way alias with no such line asks
   nothing and goes on by the usual rule. (d) No new tidy rule for older person questions: the owner plans a new consolidation
   bank. Trigger to revisit: a real run where a stake that mattered went unasked, measured.

64. **What the person marked in a book is their own record: kept word for word, read for what it shares, and it lights the
    page (owner, 2026-11-04; G39, G233, ROR-95; amends the quiet rule of 2026-10-20).** The owner tested Apple Books on their
    real library and said yes to three changes. **(a) Word for word, no model.** Each highlight and note is a claim on the
    book's page (`highlighted`, `noted`; `book_marks`, the one writer, at the door in `books.apply_pending`) with a span of
    the episode: `page` for a passage, `user` for a note. A removed highlight closes (`valid_to`), never deleted, and comes
    back if marked again; one the person took back is never rewritten. The words are gated like the person's own
    (`is_persons_words`): a remote caller without `sources` is told how many, never what, on every tool. What the sensitive
    detector flags is its typed mark; the person's own section of a saved record is now read by it (it skipped them, a hole
    in ruling 60 for any save with a reason). The page draws them as a `marks` block from the claims, derived on read: no
    prose section, so no merge copies them, and no model reads them when it rewrites a page, in code at each reader (the
    article's inputs and its material, the orientation, a revision's removed passage). **(b) What they share.** Stage 1
    reads a marked book's record for its themes, told so in a source note: a passage is the book's words and never a fact
    about the person, a concept of one to three words per theme, an `explores-theme` link with a passage as evidence. A theme
    page comes from the existing 2+ rule, two books naming it. The status lines are blanked before it reads (offsets kept);
    a read keeps no entry for the book itself and none for the owner, and what reaches the owner's page is only a link or a
    value located in a `user` span of the person's own note, in code, because haiku ignored the same words in the note. Any
    name that could be theirs counts as the owner outside a note, a first name included (owner, 2026-11-05); in a note only
    the full name or an alias lands on their page, a bare first name or surname stays as written, since it may be a friend. Books are read one at a time, each told the themes so far: read at
    once, five themes across three books never met. **(c) Cost.** One Stage 1 call per marked book, one chunk (12,000
    characters of notes first, then passages spread across the book); an unmarked entry costs none. **(d) Quiet.** A record
    holding a highlight or a note counts as a conversation (`quiet_pages.marked_record`), so the book and a theme page drawn
    from it are lit; an unmarked entry stays quiet; a record whose marks were all removed goes back. **Why it does not
    contradict ruling 62:** 62 makes a save *with no reason* index-only, and names "a book's record" among what is read as
    before. A highlight is the reason: the person chose those words, and a library entry with nothing marked stays
    index-only exactly as 62 says. "Consolidate reads everything" holds: every marked record is read in its run, past the
    chunk as a spread, because its words are already kept verbatim. **Measured** on the G39 row. **Revisit** if a theme page's
    fading at birth bothers the owner (below), if a real library's themes do not converge, or if the sequential read is too
    slow on a large first run. **Open for the owner:** a theme drawn from highlights months old is born `decaying` at 0.39
    (the age rule, unchanged: 2+ dated conversations floor there, only live silence archives it, no question asked).
62. **A save with no reason gets a lean pass: indexed, findable, read once when the person talks about it (owner, 2026-11-04;
    G236; amends rulings 13, 16 and 30 and G102).** Owner: "For chrome bookmarks, and the rest of things I told you we can do a
    leaner initial pass for consolidation on those things who have no reason/user intent attached, but enough info so that it
    can come up in a relevant conversation and an agent can look further into it." **1 — What is lean:** a bare save, by its
    own record (`history_index.kind` `saved`): a bookmark, tab group, saved link, feed item, connector poll, with no note and no
    reason. Ruling 30's "a browser bookmark, a single URL save, a connector poll … are read by Sleep as before" is replaced; a
    save carrying a reason or an agent's note, a book's record, an agent's report and a conversation are read as before. **2 —
    What it does:** captured read (`processed_by: index`); no model call, no engine needed, no claim, no page minted, no
    question, and no link backfill or recon on its page (`lean_page`, narrowing G102 to saves someone said something about). It
    keeps its title, link, site, date and any description already held, found through recall, Ask and the hook's note
    (`saved_lookup`). **3 — The way back:** read once, normally, when the person's own words name its link or whole title, when a
    conversation lights its page, or when they give a reason (`saved_mentions`, `read_asked`). A retrieval hit never does, and
    nothing on a read path writes. An agent's `cicada_record_read` is its own read. A save's text stays `page`, never the
    person's words. **4 — "Consolidate reads everything" still holds:** a lean read is a read; everything waiting when a run
    starts is consolidated by its end, the lean part with no model. **5 — Existing items:** the first run retires what waits in
    its existing `cicada` commits, before ids freeze, nothing else touched; a save a model already read keeps what it made and
    is never treated as lean. **6 — A batch is bounded by what it holds too:** the person's count and 60,000 bytes of episode
    files (`sleep_drain.BATCH_BYTES`), never fewer than one episode. Rulings 13 and 16 say a stop loses at most the batch in
    progress, and by count alone 22 items were one batch, so a plan limit lost 180 calls' work. **Why.** Measured on scratch banks, Claude plan at haiku: 25 bookmarks cost 56 to 57 calls and about 270k input tokens to restate their titles, and recall found the same links without any of it (12/12 words, 3/3 meaning, before and after); the hook's note went from 3/12 to 12/12 because a saved page never reached it. The owner's 22-item run committed nothing because it was one batch: on the same shape the first commit comes after 54 to 66 calls by count alone, after 11 to 21 bounded. Numbers on the G236 row. **Revisit** if the
    person asks why something they saved was never read and a wake rule should have caught it; if `read_asked` wakes prove too
    few or too many on a real bank (count them); if a saved item the person wanted does not come up (the retrieval check is
    `test_lean_pass.py` and the G236 row's numbers); or when G163's journal of paid answers lands, which may let the bound grow.
61. **A chat can change a book's status, and books have covers (owner, 2026-11-04; G233, G39, ROR-95).** The owner's words:
    "Yes, change the book status in that case. But it has to be in the context, we can always go back and correct that's what
    cicada is about." and "I want the book covers, yes." **(a)** Reverses G233's recommendation to keep status to the person's
    explicit acts: the person saying "I finished X" changes it, **judged by Stage 1's model in context, never by keywords**
    (the owner relies on the model as consolidation's intelligence), as a dated `reading-status` claim with a located span of
    their own turn. Only a `user` turn counts; "my friend finished X", "I'd love to finish X", an agent's "you finished X" and
    the film of the name do not (measured on haiku, `capture-and-sleep.md`). It lands only on one clear book page (title or
    alias, then the title without its subtitle, then Stage 2's own join); two pages is unclear and nothing is written. A first
    mention stays under the promotion rules and ruling 42 is not extended: the mark is held on the episode and applied when
    a door makes the page, dated as said. Dated by the conversation or the day it states, so a late read never overrides a
    newer status; one day's clash goes to the status further along, and the person's word saying less than a record asks
    once (the existing conflict path). No second writer: `books.set_status`, and `progress.py` alone for happenings.
    *Not right* takes it back, the status before and the reading thread its finish settled reopen, and that conversation never
    writes it again, whatever day or wording a re-read gives. Said again later with nothing different between: only its episode
    joins the record as evidence. **(b)** A book's picture: the person's own
    copy's cover from Apple Books' cache (the app reads, the backend keeps it outside every bank; 1 of 283 assets on the owner's
    Mac carries an ISBN, 285 cover folders, counts only), else Open Library's by cover id or ISBN behind
    `CICADA_ALLOW_LOGO_FETCH`, under their limits. **What leaves the Mac:** a book's ISBN-13 or cover id and the address, on a
    view of that book, Goodreads books included; a cover id redirects through `archive.org` to `ia*.us.archive.org`, so the
    Internet Archive sees it too. A 403's `Retry-After` is honoured per book (at least an hour, a week at most), and the 90
    asks per 5 minutes is this process's count, starting again on a restart. **No lookup by title**: not a private name, but it reveals reading beyond
    what a scan does and answers with a guess at a work (B1). None: nothing drawn. **Revisit** (a) if the person's *Not right*
    rate on chat-set statuses shows the model misjudging (`resolution` events, `kind: book-status`); (b) a title lookup if
    Goodreads rows with no ISBN are common and the owner wants them drawn.
54. **The settling step: a question worked the way an agent would, with what leaves held in code (owner, decided
    2026-11-04; G209; amends ruling 44's public test and ruling 27 for this one question; branch `g209-ruling-54`).** The
    owner, on "is <handle> the same as <person>?": "could've been resolved from a search, like how claude code would solve
    it if i ask it rn." Proposed that day as two pinned searches behind an off switch; approved and **widened** the same
    day, then corrected: "the settling step works like an agent does now", reading is allowed ("that stays between Cicada
    and the plan's model"), and "the one limit is on what leaves in a web search".
    **What widened:** on by default on plan runs (`CICADA_PUBLIC_HANDLE_LOOKUP=off` still closes it; no new setting); no
    pinned queries, no two-search cap; the model may read chats and contacts. **What stayed:** a cited claim, undoable
    under "Settled by a check", never a merge, never the owner's page, plan runs only.
    **The limit (`name_guard`), enforced in code on every query and every link:** no query may contain the name of someone
    known only from the person's record. A **tie** blocks always, and public content never clears it: a Contacts card (the
    waiting set, the contacts book, a page carrying a card), a LinkedIn connection and its slug, a chat's correspondent,
    a group member, a speaker label in a chat or meeting, a page the record says the person knows, a person page or held
    name public content never says, the owner's names; an owner's project as a whole phrase. A **mention** (words said
    anywhere that is not public content) blocks unless the same words are also said in public content, so a public figure
    the person also talked about passes and a neighbour does not. **A mention is a name, not any words someone used:** a
    query's words are asked only when name-shaped (capitalised in the query, written as a name in the record, a handle's
    shape, or a pair said in a chat, where names are typed in lower case); generic words alone are never asked. **Public
    content is a positive decision per writer and section, defaulting to private** (`name_guard.WRITERS`): a saved link's
    description and, when the page was really read, its title, never its note, reason, folder or a line the writer does not
    name; an agent's quotes from a page or a video; a watched, listened or Substack day's rows. A LinkedIn or Instagram save, a
    tab group, a day read across every site, the person's own repositories and any unknown source are private. A real name is
    held in every word order, through initials, squeezed forms and full transliteration. A blocked query is dropped, counted
    against the budget, never rewritten; two blocks stop the question. If a store that exists cannot be read or holds an
    unexpected shape, nothing leaves; one malformed episode is read as private text and stops nothing. A link leaves too: only
    a link a search returned or the page's own tracked source may be opened, exact to the character. A returned link is held to
    ties only, since the model did not choose it, and a blocked one never counts toward the stop.
    **How it runs (`settling_agent`).** The plan's own web tool cannot be intercepted: hooks are off in the pinned
    `--safe-mode`, a permission tool needs MCP, and a query reaches the provider before the stream reports it. So the model
    that reads holds no tool (`--tools ""`, the unchanged pinned argv, `CICADA_CAPTURE=off`, `CICADA_RECALL=off`); each turn
    it names calls from a table this process runs (`recall`, `page`, `conversation`, `where_to_check`, `contacts`, `open`,
    `search`), with no writing call to ask for. `ask` is left out: it is a model call over the same reads. A cleared query
    goes to a separate search hand, `claude -p` with `WebSearch` alone. It holds its prompt, the cleared queries and what the
    CLI attaches to every spawn (the account's email, its scratch working directory, the platform and shell; no flag
    removes the email), nothing from the person's record. Nothing mechanical stops a hand that disobeys from typing that
    email into a query: it is told not to, and what it reports is audited, so a search that differs voids the round and
    stops the question. The scan behind the guard runs off the event loop, from `bank_index`'s cached headers into one
    in-memory index, and never under write admission. Pages are opened by Cicada on the link rail (`_stream_html`: 4 s, ≤ 512 KB, no cookies,
    `net_guard`, a block never retried, walls retired without a byte), never by the plan's web fetch, which holds none of
    those limits. **Every other engine does not run the step** (`metered_only`, or `engine_for`'s reason): a metered key,
    the ChatGPT plan, a local model, Cursor, OpenCode, Grok.
    **Budget, one question:** 6 searches (the tool's own `searchCount`, a dropped query included), 6 pages, 12 reads, 8 model
    turns, 2 sends-back. **Per drain or sweep:** 3 handle questions, 5 questions worked in all, 5 changed-source reads,
    inside `web_check_per_run`. A question left open waits 30 days. Worst case one question is 14 spawns.
    **What settles is the model's judgement (owner, 2026-11-04):** "One site is enough to settle a question, let the agent do
    this work don't tell it how to do it. That why we depend on Claude code as the intelligence for consolidation, because
    if I asked you now you'd resolve it." So there is no list of what counts, no two-source rule, and no parody or namesake
    rule: the prompt gives the goal and what is at stake, and the model answers whether it is sure, with a confidence and a
    citation. **The one code check** (`public_handle.cited`): the citation is real, a page Cicada opened with all of the
    quote on it (exact, whitespace, case; never fuzzy; 12 characters at least), since a model can invent one, and it is the
    page's own text that is stored. A confidence of 0 or not a number is no answer. One that is not real is sent back at most
    twice. A signed-in page is never opened, so it cannot be cited. Parody, a namesake, a stale handle are the model's to judge;
    the person's undo is the floor under it.
    **The person's own local agent** (`cicada_record_check`, on their ask, `proposed_value="same"`) keeps the stricter test
    proposed that day and its two searches: Cicada cannot see that agent's queries, so the limit there can only be who is
    offered. The test: both sides are person pages, one a handle and the other a full name; neither is the owner, a role-only
    page, on the person's address book or LinkedIn import, or known personally on the record (ruling 44's local checks); no
    chat (Messages, WhatsApp, Telegram chats, e-mail, LinkedIn, a profile read on request) says either name outside a link
    to public content, in its title or as its correspondent; each name is said in public content the person read or saved.
    The two searches are pinned, each alone: the handle with the one platform word the record links it on (or "@handle"),
    and the full name. Only a quote with its link that names both settles it, and Cicada checks that the quote names both.
    Measured that day on a copy of the owner's bank: of 20 open person pairs, 1 qualifies; 11 are not a handle against a
    name, 1 is a held mention, 1 the owner's page.
    **Measured** on synthetic banks with one widely known public figure, on the plan with haiku; the shipped tier
    (`web_check_agent_model`) was not run. A real Sleep settled it on one site at the model's own confidence (0.95): 1 search, 2 pages opened, no
    query or link blocked, 6 reads, 5 turns, 34.7 s; undo put the question back. One question measured apart, with its plan usage
    (`equiv_cost_usd`): 1 search, 2 pages, 5 spawns, 26.1 s, 17,644 input tokens, 1,403 output, $0.0146. The guard's scan on a
    synthetic bank of the live shape (9,478 episodes, 62 MB): 12.5 s off the event loop, most of it inside SQLite, then
    about a millisecond a query. A private friend in the same bank got no model call. Wikipedia answered 403 to Cicada's `User-Agent` in every run (never retried), so its encyclopedia
    route did not fire. **Disclosed deviation (2026-11-04):** while the text was only proposed, an earlier worker ran
    four lookups for one pair on a copy of the owner's bank, sending a real full name to the plan's web search; each
    answered "not sure" and nothing was written. No lookup has touched that bank since.
    **Revisit** if a settled handle is undone by the person, if a name the guard cleared turns out to be someone they know,
    or if the CLI offers a way to intercept a query before it leaves (the hand could go).
    **54a (owner, 2026-11-04): "for a private person, the way to learn and update facts is not a search engine but the
    page's Where to check sources".** The settling step opens a page's tracked sources first, by code, before the model's
    first turn; a search comes only for a public handle or public thing, when no source answered; a private person's name
    never reaches one. It also answers an open conflict on any page, a private person's included, from those sources alone.
    **Which rule writes:** ruling 26. A tracked source's reading is a dated citation, the newest evidence wins, and the same
    day or undated stays the one question it already is; only a predicate the vocabulary knows is single-valued closes
    another value, so every unknown predicate is not settled this way (ruling 26's own fold adds its values). **`works-at`
    is no conflict at all (owner, 2026-11-04: "Works at really doesn't matter … And I can be working in different things at
    the same time"):** checked, and nothing needed changing. It has been multi-valued in the seed since 2026-10-14, the seed
    wins over a stale bank map (`build_cardinality_fn`, `cardinality`), the nudge writer drops a conflict on it, Sleep's tending
    dismisses an open card as `multi_valued`, and a re-check adds its value. Pinned by a test. "Are you still working at
    <org>?" (`still_questions`, owner 2026-10-28) is a different question and stays. **The one new dated exception to the S3 rail:** that reading may also close the question it answers, undoable
    under "Settled by a check". `check_record` stays shadow. **The update path is ruling 26's, unchanged, with one gap
    filled:** a tracked public page that changed with no machine-readable fact waited for the person's agent; on a plan run
    the model now reads it first, through `source_refresh.apply`, and what it cannot read keeps waiting.
    `web_context` reads a public page's tracked sources before its pinned search. `org_sites` and `source_proposals` are
    unchanged. No second refresher.
    **Walled:** a tracked walled source is never requested. It is already on ruling 26's listing (`agent_due`), gated by the
    person's Reading switches, so Sleep queues nothing and the question stays open.
    **Imported LinkedIn links (owner, 2026-11-04):** "maybe for LinkedIn only when asked or limit it to the most frequently
    talked about people, and do save the links as resources to check." Saving already existed (`linkedin_people`, existing
    people only, never minting a page, a removal remembered). A link on a confident match now counts as given as a place to
    check, the photo rung's own rule (`from_connections`); an alias-only one stays what it was, a guess saved with `match:
    alias` that counts for nothing until the person takes it; `cicada_record_profile` refuses it, saying so, and writes no
    `works-at` or `role` from it until then. A confident link is deliberately NOT `trusted`: that would make it a tracked
    source, which ruling 26 lists for a visit on a cadence. **Reading one stays on the person's ask** (`cicada_record_profile`,
    ≤ 10 a day, stdio only, their own agent and browser). A standing read of the most talked-about people is a small later
    switch, not built: automated visits risk the person's LinkedIn account.
    **First names (owner, 2026-11-04: "Yeah leave it allowed"):** a first name said only in chats does not block a full name
    public content says. A name known only from chats or contacts stays blocked.
    **Finding a source:** the model may propose a link literally in a conversation it names, on a page of the question;
    it lands as a proposal in the one grouped review (ruling 36 D5), never opened, trusted or re-checked until taken. Never
    guessed from a name; `sources_removed` holds. A sweep writes no proposals; Sleep does.
57. **Capture for apps without hooks defaults to the tool their model calls as they talk (owner, 2026-11-04; amends ruling 32
    and G105 for those apps only; G197).** `cicada_capture_turns` on the Claude desktop app's local connection and on the
    remote connector, and the primer asks for it. Hook capture is exactly as it was for Claude Code, Codex, Cursor, Gemini
    CLI and the rest. **The evidence that made it worth a model's cooperation:** #592's diagnosis of the owner's bank, one
    relayed episode ever and every Claude chat from one export; the desktop app keeps no history on disk for a claude.ai
    account, and reading claude.ai through a browser is what its terms bar. **What it binds:** a client is told apart by one
    predicate (`relay_capture.local_relay_allowed`): the exact self-reported name, no session a harness named, not
    `CICADA_CAPTURE=off`; anything else is not offered and not asked, so a hook-captured turn is never captured twice (Claude Code
    calling itself `claude-ai` is refused by the session id it injects). Stored as relayed, never the person's own words;
    one episode per conversation by a handle the tool mints where the call arrives; an app's two connections keep one copy.
    **Disclosed trade-off (2026-11-04):** a person's message repeated exactly, as the first message of a new chat on the app's
    other connection, within 10 minutes of saying it there, is read as the same conversation, and the new chat is not kept.
    The person is told in
    words: the tool's description, the app's own first-use ask, one line when it connects, one sentence in the conversation.
    No new setting. **Disclosed limit:** a harness with a hook that calls itself `claude-ai` and injects no session would keep
    a second, relayed copy. **Revisit** if a client is seen doing that, or if the desktop app gains a hook or a readable store.
58. **Exports are one-time (owner, 2026-11-04, verbatim: "never really agreed with the path of the weekly exports; exports
    should only exist for starting a brand new memory bank or importing data from AI providers like OpenAI and Anthropic.").**
    #592's weekly nudge and Downloads pickup are removed; a one-time import, its upgrade in place and the one-off *Remind
    me* stay (that reminder predates #592 and exists because an export comes by email hours later). **Amended (owner,
    2026-11-04: "Yes I like that alternative you mention for exported chats that continue. That makes sense."):** a chat that
    goes on after its import keeps its later turns in the same episode, marked as relayed, with the imported part still the
    person's own words; a relay into an upgraded conversation no longer writes nothing (ruling 32's sentence). One conversation for every
    count (G104), each part its own provenance by a `relayed [<app>]:` marker the one marker grammar reads as the model's, the
    imported part's offsets untouched, Sleep reading only what grew, another import upgrading the turns it holds without a
    duplicate (`capture-and-sleep.md`, "A chat that goes on after its import"). **Revisit** only if the owner asks for a repeating import.
    **58b, a narrow amendment (owner idea 2026-11-06, ROR-126, verbatim: "Once an agent is connected and has the browser
    skill, Cicada offers to have it request the export from each provider, in the person's own signed-in browser. The
    person says yes, one provider at a time." and "The little worm on Home shows 'waiting on your data export', per
    provider. A reminder is the fallback"; "No email watching in this version"):** the wait the person starts is the
    same one-off the *Remind me* was: one provider, one yes, started by the person, gone when the export is imported,
    when they stop waiting, or after 14 days. The new part is who asks the provider: the person's own agent, in their
    own signed-in browser, through the request queue (`export_requests`, outside every bank, ids and enums only,
    `cicada_export_requests`, stdio only). It is **not** a repeat: a request is never made on a schedule, never again
    after an import, and nothing looks in Downloads or Mail for the result. The agent never signs in for the person;
    a sign-in, captcha or changed page is reported as `manual` and that provider stays on its walkthrough. A provider's
    terms do not block it: it is the person's own agent in their own browser (owner 2026-11-06). **Choosing what to
    bring in:** after an upload and before anything becomes an episode, the person picks a start date and may untick
    chats (Consolidate reads everything it was given, rulings 13 and 16); unticked chats are remembered per memory
    (`import_choices`, keys only, never a title) so a later, grown export does not offer them as new. The start date is
    not remembered. **Revisit** the email watch (Apple Mail only) as a separate version, and the remembered start date
    if a repeating import is ever asked for.
59. **One click may open the connector's own port to the internet (owner, 2026-11-04: "YES to one-click Tailscale Funnel
    for the claude.ai and phone connector"; G135, G132's D6′; amends G132 (c), the headless rail's "never `funnel`" and the
    2026-10-29 one-click rail; branch `feat/g135-funnel-one-click`).** Why: claude.ai and the phone apps relay through the
    remote connector (ruling 32, 57) and can only reach it at a public address. **The rule:** the person's click, or
    their own shell, may run exactly the shown `tailscale funnel --bg --https=<443|10000> <the connector's port>`, or that
    one mapping's off (`tailscale funnel --https=<its port> --set-path=/ off`). Off until clicked; never at install, on
    start, by an agent, or from an agent's shell. No port or argv from a request; the API's port and the door's refused;
    never `up`, a login or `reset`; a port holding anything is never used; 8443 (the backend's tailnet mapping) is never a
    candidate; nothing about it is stored, every answer is read back from Tailscale. What is exposed stays MCP and `/v1` on
    that listener with its tokens and OAuth as they are, consent only in the app by typing the code. **Evidence that decides
    the code, read from Tailscale's CLI source (v1.104, `serve_v2.go`), not its docs:** a funnel on a held port replaces
    its `/` without asking and opens every other path on it; an off with no `--set-path` deletes every handler on the port;
    with Funnel not allowed it prints a link and waits, or exits 0 having changed nothing, so the return code never decides.
    The obvious `tailscale funnel --bg 8765` from our own docs fights `headless.md`'s example serve of the API on 443: it
    would have silently taken that serve away and made the connector public there, and made public anything mounted on
    another path of that port, an API included. Details: `network.md`. **Revisit** if embedded `tsnet` (D6′'s "later") is built, if
    Tailscale changes those behaviours, or if an app refuses the 10000 address. **In the same PR, the same class on this
    seam:** `/remote/status`'s `funnelCommand` no longer offers the bare command that took over a held 443 (the port the
    click would use, or a harmless shell comment when none is safe); `cicada setup` says `cicada funnel on`; *Stop serving*
    and the copy-only unfunnel now name `--set-path=/`, since without it the CLI deletes every handler on the port (the
    2026-10-29 rail's shown command changes with them); and what enabling HTTPS publishes, for good, is said before the
    click. The off keeps its confirmation, as *Stop serving* does (coordinator 2026-11-04; the owner can overrule). **Review
    of #607, the mapping outlives the listener:** the switch now closes the connector's address in the same act (amends "the
    switch never touches Tailscale"); a down listener's port is asked, never assumed free; other public mappings are shown
    with their off to copy and never run, since Cicada keeps no record of what it opened; a clean quit still leaves it open,
    because only a click may reopen it (`network.md`).
63. **A Claude key is served by Anthropic's own SDK, and the next provider's SDK slots in the same way (owner, 2026-11-04;
    G237; amends the G50 note that every key goes through LiteLLM).** Owner: "Well having cicada work the same or as good
    as through Claude code is crucial and priority." And: "have all official sdk's integrated where possible." **The
    finding that decided it:** with a stub client on LiteLLM 1.83.4, a Claude key could not have run Sleep. `extra_body`
    reached the API as a literal top-level field on every extraction and judge call (the API refuses unknown fields),
    `response_format` was dropped, every model its table does not list got `max_tokens: 4096` while thinking counts
    toward it, `temperature` went out (a 400 on current models), no `cache_control` was ever sent, and no current model
    had a price. **What is binding:**
    (a) `direct_engines` is the seam: a key whose provider has a row there is served by that provider's own SDK, behind
    the plan's own semaphore, breaker, drain retry and ledger, and raises only `engine_errors`. Every other key stays on
    LiteLLM. `openrouter/anthropic/…` is OpenRouter's. The wire's engine id stays `litellm` (to the app it means "the API
    key engine"); the ledger and `Cicada-Engine` say `anthropic-api`.
    (b) Caching: one breakpoint at the end of the system prompt, 1-hour TTL, the first call on a prefix goes first. All
    three are measured or documented: `claude -p` writes 1-hour entries and reads them after 5.5 minutes; three parallel
    calls read nothing and write three times (2026-11-04, Haiku 5.5, 19,338-character extraction prompt).
    (c) The model list is the key's own (Models API: `line`, `lifecycle`, limits, capabilities), read on a save, on
    Refresh and once a day at a run's start, never on a page view. Tiers follow the vendor's lines; a saved `anthropic/sonnet`
    is the plan's alias. A retired or refused id moves to its line's newest, said in words. With no key, a documented floor.
    (d) A key reads every stage on its own provider: another provider's `CICADA_CONSOLIDATION_MODEL` is set aside and the
    judge is the small tier, as on the plan.
    (e) Prices live in `price_supplement` with their basis and read date (the API gives none); a model newer than the table
    reads unknown with its tokens shown, never a guess.
    (f) A key's rate limit is a pause with the provider-neutral words, `limit: key_limit`, never the person's plan; the SDK
    rides out `retry-after` first (4 retries), and a limit lifting within 2 minutes is waited out by the batch's later
    stages so what was already read is filed.
    (g) **The spending limit (ROR-102; owner, 2026-11-04: "from cicada you can put a limit on spending"; amends ruling 4's
    and ruling 16's "no limit Cicada sets").** A run on a metered engine stops at the person's figure, set on one line of
    the engine menu or `cicada sleep options --spend-limit`: suggested $5 a run, on unless they turn it off. It is the
    reserve's soft stop (`sleep_spend`, reason `reserve`, `limit: spend`, pause reason `spend`): reads stop going out, what
    was read is filed, the rest wait. **The bound, in words (2026-11-04, the #614 review measured "a little past" as three
    times the figure):** one read past it when reads cost about the same; if a read costs far more than any before it, every read then out, at most 3 on a Claude key and 10 on another; plus filing what was read. Each read is checked again after it holds its permit, the run's first call goes alone to
    learn the price, and a batch is sized to the allowance left (recent spend per conversation; before that the most one
    read may write). Filing is never refused, since otherwise the reads already paid for are lost. Stub drain on Opus 5.5
    at 64k tokens a read, one script before and after: $5 on a batch of 25, $14.32 to $5.27; $1 on a batch of 25, $13.03 to
    $1.36; $5 on a batch of 50 holding 6 conversations, $7.84 with no stop to $5.27 with a stop. Per run: a Continue is the
    person's click and a new allowance. A scheduled run that reaches it waits for that click; the schedule never replaces
    it. A scheduled run that paused on `restart`, `engine` or `busy` is replaced (`SCHEDULE_REPLACEABLE`) with a fresh
    allowance. **Only runs are covered:** Ask, the inbox's tidy and catch-up, a click's web sweep, repairs and the quick read
    are not limited, and are in the ledger at what they cost. The figure is the ledger's, each call's list price with a
    failed call's spend included; a charged call whose cost cannot be read stops the run, like no price. **A model with no known price stops the run, before any read when it is known up front, else at the first
    unpriced call; tokens are not counted against a dollar figure and no price is guessed.** Choosing that was the point
    of the review: a limit that silently stops holding on a new model is worse than a pause that says why.
    (h) **A failed call is still a paid one.** A call that failed after the provider started answering (cut off, refused,
    the connection lost mid-stream) reaches the ledger with what it reported (`_paid`), and Past reads and the limit read
    that; a request refused before an answer costs nothing. A connection lost inside an open stream is the engine's,
    never the conversation's; a stream that closes before the model finished is never an answer; only a status is ever
    called a refused request (the #614 review measured a cut parking a conversation).
    (i) **Disclosed, the owner has not ruled:** the price rows turn on the web lookup for a Claude key (ruling 27's own
    `metered` path), up to `web_check_per_run` (8) questions a run, scheduled runs included, about 1¢ a search plus its
    tokens, counted against the limit. It stays allowed under ruling 27. One click's sweep on a metered key is now capped
    at the same 8 (`capped_at`); a plan's stays as it was. A run past its limit skips these paid steps, a run with nothing
    left to read included, and each call is checked (`LINE_STAGES`; link backfill's spend now counts as the run's).
    (j) **The SDK is pinned to 2.1.0** (2026-10-21; 2.5.0 was published the day this was reviewed). Every 2.x sends API
    version `2026-10-21` and the key as `Authorization: Bearer`, never `x-api-key`, which the vendor documents and a test
    pins on the stand-in. **Check that first on the owner's capped run**, since nothing here has reached the real API.
    **Decided against, for now:** the Message Batches API (50% off, but 29-day retention and no zero-retention option for
    a person's words, up to 24 hours a stage, and no pause; worth cents a batch on Haiku 5.5. **Revisit** for a large first
    import on Sonnet, on the owner's word). **Plan-only steps stay plan-only, on the owner's ruling:** ruling 44's web
    context (`web_context.py`, the `metered_only` branch) and proposed ruling 54's handle settling (`web_lookup.py`'s
    `why != "plan"`); each is a one-line change, costed in G237. Changed-source reads need no engine at all (`source_refresh`).
    **Not yet proved:** no call has reached the real API; G237 names the one small run that does. **Revisit** if that run
    differs from the plan's own spread on pages, claims or spans, or if the first real 429 does not read as designed.
60. **A confident sensitive hit is held back from the engine; an unsure one is reported (owner 2026-11-04, G235).** Asked
    "hold back confident hits and only report unsure ones", the owner: "Yes hold them back." Before any engine read,
    `sensitive_text` finds likely credentials, card and bank numbers and ID numbers with no model. Confident
    (`Hit.sure`: a number that passed its own checksum, a vendor shape, a value in a connection URL or a secret's env line,
    a password with letters and digits together, digits someone claimed; a weak word like "clave" or "pass" only with the
    system it belongs to): every engine Cicada runs, on every job, reads a
    typed mark wherever that value stands (one door, `sensitive_hold`, Ask's own model included); the stored body and every
    offset stay. An agent the person talks to reads the record as stored until they remove it: their own agent, on their own
    ask. Unsure (letters only, digits no one claimed, an account or ID number nothing can check): read,
    and the person is told. No setting. Either way the value is taken back out of what the model answered, and a flag never
    repeats it, nor a hash of it. **Why not hold back everything:** a held-back wrong alarm costs a word the record may
    need, and the detector's precision on real data is unmeasured; unsure is where that risk sits. The owner also ruled that
    git history stays as it is, since it is local only. **A wrong alarm never rewrites something unrelated:** only a confident,
    distinctive value rare in the bank (three other conversations, six other files) leaves more than its own conversation
    and the lines speaking of a secret in what cites it, and a token more than a few conversations hold is not masked by value
    at the door. **Revisit** on the Remove and Leave it answers (G113): if Leave it
    dominates a confident class, that class moves to unsure.
