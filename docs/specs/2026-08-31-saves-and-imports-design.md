# Save-with-reason + the Imports page (G71)

**Status:** approved 2026-08-31 (Rodrigo's build directive: Telegram link+reason capture, direct
APIs where allowed, export parsing for the rest, an imports surface with connect-or-export tiles,
written step-paths, and real-time parse preview showing detected collections with counts).
**Grounding:** `docs/goals/saved-content-integrations.md` (G69 research — the per-platform route
matrix is binding: aggregators ruled out; Pinterest/Reddit = direct API; IG/YT/TikTok/LinkedIn =
export files; YT Watch Later = opt-in browser read, OUT of this slice).

## 1. Save a link with a reason (Telegram first, no companion-app messaging yet)

- `/save <url> [reason…]` (and bare-URL messages followed by optional text) already stage media
  episodes. Extend `telegram_capture`: everything after the URL is the **reason**.
- Storage: the reason lands (a) verbatim on the episode body (`Saved because: …`), and (b) as a
  `user_stated` claim `{subject: <media entity>, predicate: saved-because, object: <reason>,
  origin: telegram}` written through the existing claim writer at ingest — so Sleep extraction
  can relate the reason's concepts ("recipe for meal prep" → `cooking`, `meal-prep`) exactly like
  conversation text, and the Feed card can show "why you saved this".
- Bot ACK gains the reason echo: "Saved with note: …".

## 2. Direct API connectors: Pinterest + Reddit (the two sanctioned ones)

Both follow the G50 BYOK pattern — credentials in `~/.cicada/secrets.env` (0600), never in a bank:
- **Pinterest** (`api/services/connectors/pinterest.py`): user supplies their own OAuth app
  (id+secret; guided by a walkthrough tile) → token via the standard authorization-code flow
  (localhost redirect, opened in browser); nightly Sleep tail + on-demand "Sync now" pulls
  boards + pins (`boards:read`, `pins:read`), one media episode per NEW pin, `folder` = board
  name, `origin: pinterest`. Idempotent via the url_index dedup.
- **Reddit** (`connectors/reddit.py`): script-app credentials (client id/secret + username/
  password or refresh token — guided); `GET /user/{me}/saved` with `history` scope, ≤100 QPM,
  newest-first until a seen id; `origin: reddit-saved`; the ~1,000-item listing cap documented —
  the one-time GDPR export (`saved_posts.csv`, a new G47-family parser) backfills beyond it.
- Both appear in `GET /sources/channels` (`pinterest`, `reddit`) with connected state derived
  from stored credentials + last-sync in `sync_state.json`; poll failures surface per-channel.

## 3. New export parsers (G47 family members)

- **LinkedIn saved**: the export's saved-items file (URL + saved date; thin by design — no
  enrichment fetch, per the ToS finding). `origin: linkedin-saved`.
- **TikTok favorites/likes**: `user_data.json` → Favorite Videos + Like List (+ optional
  Browsing History behind a checkbox, default OFF — high noise). `origin: tiktok`.
- Both register in the sniffing logic `media_ingestor.parse_upload` uses.

## 4. The Imports surface

Grow the existing `+` sheet (Feed, ⌘N) into a two-level **Imports** catalog — no new sidebar row:

### 4.1 Platform catalog
One tile per platform (Instagram, YouTube, Pinterest, Reddit, TikTok, LinkedIn, Chrome/Safari
bookmarks, Apple Notes, RSS, Calendar, Telegram, generic file/link), each showing a route badge:
**Connect** (Pinterest, Reddit — opens the credential/OAuth flow inline) or **Import file**
(export platforms — opens the overlay). Connected/last-sync state comes from `/sources/channels`.

### 4.2 The export overlay (per platform)
The existing `WalkthroughPanel` grows into the user's described flow:
- The reserved **video slot** (bundled `Resources/walkthroughs/<vendor>.mp4` when present; G64).
- The **deep-link button** to the exact settings page.
- **Written step-path** — one line, breadcrumb style, per platform, e.g. Instagram:
  `Settings > Accounts Center > Your information and permissions > Download your information >
  Download or transfer > Some of your information > Saved > JSON`. Copy lives in the `Copy`
  constants enum; every platform gets one (YouTube/Takeout, TikTok, LinkedIn, Reddit-GDPR).
- **Drop target / file picker** (existing upload plumbing).

### 4.3 Real-time parse preview (the new core)
- New backend endpoint `POST /sources/upload?preview=true` (multipart, same sniffing as the real
  upload): parses WITHOUT staging anything and returns
  `{recognized: bool, platform, total, collections: [{name, kind, count}], warnings: [str]}` —
  `collections` = IG collections, YT playlists, Pinterest boards (from export), TikTok lists,
  LinkedIn "Saved Items", each with its item count. Runs in the threadpool; large zips stream.
- The overlay parses **immediately on drop**: a scrollable collection list appears live (name +
  count + kind icon), with total ("214 posts across 6 collections"), unrecognized-file and
  partial-parse warnings shown honestly.
- **Confirm import** then runs the real upload (same file, `preview=false`), reusing the parse;
  the overlay ends with the staged-episodes summary and a "processed next Sleep" line. Dedup
  counts ("182 new · 32 already saved") shown.

## 5. Relationship derivation
No new machinery — the G69 finding stands: episodes → Stage 1–2 extraction, Stage 5.55
`inject_media_edges`, Stage 5.57 enrichment. The only addition is §1's `saved-because` claim.

## 6. Out of scope (recorded, not built)
YouTube Watch Later browser read (opt-in surface, later); Google Data Portability keyed refresh;
walkthrough video recordings (G64); companion-app share-sheet capture (the Telegram bot covers
mobile for now).

## 7. Testing
Pytest: reason parsing (`/save` variants) + `saved-because` claim; Pinterest/Reddit connectors
against recorded fixtures (zero network; injectable transports); new parsers on synthetic export
fixtures (never real personal exports in the repo); preview endpoint per platform incl.
unrecognized + partial files; channels rows for the two connectors. Swift: catalog tiles/badges
from channels; overlay state machine (drop → preview list → confirm → summary) over the fake
transport; step-path copy present for every export platform; collection-list rendering with
counts. Live: drop the real IG export (if present on disk) into the overlay and watch counts.
