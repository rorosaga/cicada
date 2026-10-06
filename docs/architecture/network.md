# Reaching the outside world

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

Three backend gates, and a separate app-side scenery gate below. They do **not** mean the same thing:

- **`CICADA_ALLOW_CONNECTOR_FETCH`** gates the default transport of every fetch Sleep starts on its
  own: the unattended nightly connector poll, **link enrichment's page read** — Stage 5.57's
  in-cycle pass (`sleep_cycle._link_summarizer`, G61 phase 2 S0) and the G102 tail backfill, both
  through `link_enrichment.default_fetch`, the rail's reference transport — **the site check** (G61 S3-b: the Sleep tail's
  `site_sources.verify` reads a proposed official site through `link_enrichment.fetch_identity`, which shares that
  transport's `_stream_html`; a walled or platform host is never requested) — and paper details
  (below). It is **opt-OUT** (on by default; `=off` disables it, which is what the test suite sets).
  A user-initiated `sync_now`, `POST /maintenance/enrich-links`, `POST /maintenance/verify-sites`, every OAuth
  `authorize_url`/`exchange_code` call and OpenRouter's sign-in key exchange (`openrouter.ai/api/v1/auth/keys`,
  R-AG10; the key lands only in `secrets.env`) are **never** gated by it — they always need the network to
  do what the user just asked.
- **`CICADA_ALLOW_FEED_FETCH`** gates RSS/ICS polling and is **opt-IN** (`=1`). A fresh install's
  LaunchAgent plist sets it; `install.sh` never rewrites a plist behind a running backend, so an
  older plist needs the key added by hand.
- **`CICADA_ALLOW_LOGO_FETCH=off`** disables logo fetching entirely. The test suite runs that way
  and injects fetchers instead. It also gates the icons of the sites Settings, Reading the web, lists (G166): those
  come from the icon service only and the login-walled site is never contacted for its favicon (nor, since
  `fetch_logo` skips its first two rungs for a walled host, is a company or tool page's logo domain when it is one).

**The study room's weather has its own app gate (G176, owner 2026-10-02).** It is opt-out through the per-viewer scenery
setting, not any backend environment variable: Settings → Sleep → The scenery → Local weather (default). Choosing
How Sleep is doing or Choose turns the read off. `LocalWeatherReader` runs only while the study room is on screen,
using the same window-visibility/host-pause policy as its sprites; leaving, hiding or occluding it, or opening Settings, cancels the request
and wait. The Settings preview reads the memory cache and never fetches. The room explicitly propagates the Settings-open
pause to its sprite leaves too; the clock uses the same visible-room predicate. Tests inject transport and render
Settings with isolated preferences, without making a weather request. This is not a Store domain and has no ETag.

The app's query sends the time zone's principal city's public latitude/longitude from `TimeZoneCoordinates` plus fixed
current-condition parameters (`weather_code`, `wind_speed_10m`, kilometres per hour, one forecast day). No location
permission, time-zone identifier, viewer id, account or bank content is sent. `LocalWeatherRequest` constructs one
HTTPS endpoint at `api.open-meteo.com/v1/forecast`; the transport refuses other hosts/paths/schemes, all redirects and
HTTP authentication. Its ephemeral session has no cookies, credentials or disk cache, a constant non-identifying
User-Agent, fixed `Accept: application/json` / `Accept-Encoding: identity` and an explicitly empty `Accept-Language`
field that suppresses CFNetwork's viewer-language default. The service also sees the network address, as with any web request.
Both request/resource timeouts are four seconds. Advertised bodies above 64 KiB are refused; streaming
stops before appending a byte beyond 64 KiB. Every attempt, including cancellation and failure, consumes the half-hour
slot; a time-zone switch cannot bypass it. A backwards clock makes the next attempt due and restarts the throttle
from the new time. A cached city never supplies another city's weather. After half an hour, a stale reading remains
only when the visible local-weather room is about to refresh or that city's refresh is in flight. Failures clear it;
cancellation removes the in-flight allowance, and an expired reading cannot survive a throttled retry or hidden room.
A missing city, offline/refused/malformed/oversize response or unknown conditions falls back to
How Sleep is doing, named explicitly in the legend/help/VoiceOver. No alternate headers or immediate retries.

The one-line disclosure is: “Open-Meteo receives your time zone's city every half hour while the study room is open and,
like any web request, your network address. Nothing from your memory is sent.” This names the weather service only as a privacy disclosure. Conditions use the
[public forecast API](https://open-meteo.com/en/docs); transport tests inject responses and capture a real loopback wire request; they never contact the public service.

**The update check has its own app gate (G182 phase 5).** Only a release app checks for updates; a developer build
never does. Settings → General → *Install updates automatically* (on by default) is the gate for every request the app
starts on its own: with it on, the app reads `https://api.github.com/repos/<repo>/releases/latest` and the release's
`latest.json` on launch and every six hours, and downloads a newer zip; with it off, nothing is requested until the
person chooses Cicada → Check for Updates…. The requests carry no cookies, token or identifier beyond a
`Cicada/<version>` user agent; the download is verified by sha256 and an Ed25519 signature against the key built into
the app before anything is unzipped, and nothing reaches the backend. The tester's install line
(`scripts/install-release.sh`) is the person's own command and fetches the same two files with `curl`.

**The remote connector (G135) — the one way in from outside this Mac.** Off by default
(`~/.cicada/remote/settings.json`). When on, a **second listener on `127.0.0.1:8765`**
(`CICADA_REMOTE_PORT`) serves **only MCP** — none of the FastAPI routers — to cloud AI apps
through a tunnel **the person** runs (Tailscale Funnel or ngrok); **Cicada never starts, stops or
reconfigures a tunnel** — `GET /remote/status` only detects one — on PATH or in
the standard install folders, since an older LaunchAgent's PATH is bare (F2-back R-B15). Access is a per-connector
capability token `cic_rc_<id>_<secret>`: shown once, only its sha256 stored in
`~/.cicada/remote/connectors.db` (0600, never in a bank), scoped (`search`/`read`/`record` default;
`sources`/`answer`/`ask` opt-in — `sources` gates every verbatim word of the person's, recall's
episode excerpts and the inbox `Cause:` quote alike; `pending`, `mark_processed` and `repo_context`
never), expiring
(7/30/90 days) and revocable. It arrives as a secret link (`/c/<token>/mcp`) or a bearer header —
one verifier. Tools outside a connector's scopes are absent from `tools/list`; any `Origin` header
is refused; the listener has no access log (a secret link's path IS the token). Every remote write
commits alone as `Cicada-Author: <app harness>`, `Cicada-Session: rc_…`, trigger
`remote/<harness>`, no engine; a remote claim is `origin: remote:<id>` and can never be the
person's own words. Each call leaves one ids-only `remote_call` ledger row, filed beside `read` in
`reads-*.jsonl` so it never ticks the app's consumption domain. Every server-side fetch of someone
else's URL goes through `net_guard` (`is_global`, never `is_private`, because tailnet addresses are
neither; the name lookup runs off the event loop).

**A failed poll is recorded, not raised** (`sync_state.record_error`) and surfaces per-channel as
`lastError`; a gate-skipped poll is recorded distinctly (`record_skip`) so a skip never reads as a
failure or as a stale success.

**Paper details (G133) ride the first gate, not a fourth.** The unattended Sleep-tail lookup is behind
`CICADA_ALLOW_CONNECTOR_FETCH`; a folder sync the person asked for (`?resolve=true`) is not. Only two
APIs are ever called — `export.arxiv.org/api/query` (≤ 50 ids a request, ≥ 3 s apart) and
`api.crossref.org/works/{doi}` (public pool; no email is ever sent) — at the rail's 4 s / ≤ 512 KB;
arxiv.org pages and PDFs are never fetched, and a 403/429 stops that API for the run. That holds for
a paper link saved any other way too (a bookmark, `cicada_save_url`, Telegram): `papers.never_scraped`
keeps arXiv/DOI links and every arxiv.org page out of save-time enrichment and the link backfill.

**Reading with an agent (G166) does not loosen the rail below; it sits beside it.** The rail governs *Cicada's own*
fetcher, and the backend's page readers (`media_ingestor.enrich`, the `link_enrichment` backfill) no longer fetch the
page of a login-walled host (R-RW4, one closed set in `reading_hosts.py`, which also closed the X gap; TikTok's provider
oEmbed call and the Reddit and X connectors' own API calls remain, and none loads the walled page). What the person's own agent does in its own signed-in browser is the person's and the
agent's, not Cicada's: Cicada only *asks*, per link or per site the person turned on after a page from it could not be read, after a
first-use acknowledgement, and promises nothing about what the agent does there. The backend never holds a session, a cookie or a
browser profile. An ask's URL is the person's explicit hand-off to their agent, and a site entry's URL rests on the person's grant for
the site, so a remote connection holding `read` sees them (TODO ruling 14; a site entry from a channel that is the
person's own words needs `sources`); `sources` still gates every verbatim word of the person's conversations and any
chat-harvested URL.

**The ToS rail — this one is not negotiable.** A fetched page is 4 s / ≤ 512 KB / no cookies / never
behind auth. Consent interstitials and login walls are classified and retired as `junk` **without a
byte fetched**. **A block is never retried with different headers.** No scraping behind
authentication, ever.

**Credentials** live in `~/.cicada/secrets.env` (0600) — **never in a bank, never logged**. The
shared `base.forget()` removes them on disconnect, so a fields-vs-stored drift can't orphan a
secret. Where a vendor bills per request (X's "owned reads"), the sync result carries the count so a
cost is stated plainly rather than hidden behind a "connected" checkbox.
Cicada's own Codex sign-in lives in `~/.cicada/codex/` — Codex's files, never opened by Cicada,
never in a bank.

**Video (Track V, 2026-09-05).** Only a provider's own player URL is ever loaded — YouTube
(`youtube-nocookie.com/embed/…`, incl. `videoseries?list=`), Vimeo, TikTok and Loom — and an
oEmbed response is read for its *fields* only, never its `html` blob: the player URL is derived
from the id by `video_urls.resolve` / `VideoRef`, so nothing a provider returns is ever executed.
**A stream is never derived** — no `yt-dlp`, no CDN or `.m3u8` URL lifted out of a page — so a
direct file the app plays is one the *user* saved as a direct URL. Twitch stays external (its
player validates `parent` against the real embedding origin; synthesising one is circumvention),
X and Instagram stay external. The app itself makes **no** network call to classify: oEmbed runs
only on the ingest/enrich path, under the gates that path already has, and the three new
provider calls take the rail's own 4 s / ≤ 512 KB numbers rather than the older, looser `_TIMEOUT`.

---
