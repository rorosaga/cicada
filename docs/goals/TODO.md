# Cicada — priorities and handoff

**Updated 2026-10-06. Today’s delivery priority:** G182 — make GitHub releases work today, automatically keep the released version/`main`/website links aligned, and complete the per-integration post-consolidation read/contribute checks. Release work must clear applicable integrity/packaging checks and report blocked or unsupported integrations honestly. [Release requirements](../specs/2026-10-06-release-and-integration-acceptance.md).

**Memory-quality pickup:** fix the relevant G183/G177 write-integrity gaps, repair G185’s reported test regression, then use [the first-memory-trial runbook](2026-10-06-first-memory-trial.md). Do a small trial before a full user-started drain. The immediate product question is whether asking ordinary questions about your life feels useful and trustworthy.

[Feature status: one line per feature](feature-status.md) · [Implementation review: every G ID](BACKLOG_IMPLEMENTATION_REVIEW.md) · [Active reasoning by priority](memory-evolution.md) · [Completed work](DONE.md) · [Reference context / original prompts](BACKLOG_CONTEXT.md) · [Working method](working-method.md) · [Cognition comparison](../research/2026-10-06-agent-memory-repo.md) · [Source/video gaps](../research/2026-10-06-source-refresh-and-video-gaps.md) · [Provider/source modularity](../specs/2026-10-06-provider-and-ingestion-modularity.md) · [Benchmark rebuild](../specs/2026-10-06-system-benchmark-rebuild.md)

**Pick up here (2026-10-22, redesign):** read ruling 36 (the owner's answers D1–D6 to the redesign proposal), then [`feature-status.md`](feature-status.md) for what is building. Branches in flight: `feat/awake-read` (G207), `fix/people-dedup` (G209), `feat/update-sources` (G61); queued: connection model and providers (G217, G50), agent API (G213), app (G217's pages, needs a Mac). **Decided after review (2026-10-22, in ruling 36):** a new install's Auto uses a signed-in plan, a key offered as an equal option; ruling 4c stays and the quick read follows it; G213's API rides the G135 listener; "Where to check" as one grouped inbox review; `rich` + `questionary` approved. Nothing waits on the owner from this ruling. **Ruling 38 (2026-10-23)** decides the follow-ups: `/v1` from the tool table (G213), a capture-only phone (G91), one-way syncs (G219), traces with screenshots (G218).

**Chats (2026-10-28, G179):** WhatsApp live chats in their PR (`feat/chats-live-whatsapp-telegram`; the source-agnostic `chat_live` engine). Telegram under ruling 47a is its own PR (`feat/telegram-live`), one-to-one chats only with the person's per-chat confirmation of the other side's consent (the owner, 2026-10-28, after Telegram's AI terms). 2026-10-29: the connect sheets go one step at a time with a country picker (`feat/connect-sheets-modern`, DESIGN_RULES §9 2026-10-29).

## Current state and evidence

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
