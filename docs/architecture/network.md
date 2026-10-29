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
  transport's `_stream_html`; a walled or platform host is never requested) — **the organisation-site lookup** (TODO
  ruling 40, `org_sites`, in the same step: Wikidata's API `www.wikidata.org/w/api.php` — `wbsearchentities` with only an
  organisation's, tool's or public place's own name and at most two proper-looking aliases, never a person's name, a
  project's or a private one, then `wbgetclaims` for item and class ids — spaced 0.2 s, 4 s / ≤ 512 KB, no cookies, no
  proxy env, `net_guard` on every hop, User-Agent `Cicada/1 (<repo URL>) httpx`, a 429 waited out once, ≤ 20 pages a
  night; and each candidate's homepage through `fetch_identity`) — **the source refresh** (G61, TODO ruling
  26: `source_refresh.run_tail` re-reads the due tracked PUBLIC sources through `_stream_html`, at most 20 a night, one
  per site, a walled or refused host never requested; it states only what the page says in schema.org JSON-LD, and a
  404/410, a name or connection failure, a parking host or "for sale" title, or a landing on another site is a strike —
  two a week apart mark the source dead) — **the web check** (TODO ruling 27: `web_lookup.run_tail` sends no request of
  its own; the engine's search does, so the gate is asked before any engine call, and what reaches the search is only a
  public subject's name plus at most one generic category word, every reported search held to it (the prompt's
  local context, ruling 27a, is never searched) — `capture-and-sleep.md`; on every plan run, scheduled ones included
  since the plan switch is on by default, ruling 27b) — **light web context** (TODO ruling 44: `web_context.run_tail`
  decides the engine before reading any page — plan search only, a metered key never — then asks Wikidata, through
  `org_sites.wikidata_get`, only for a name that passed the local public test (≤ 20 a run), and the engine's search only
  with the pinned queries; ≤ `web_context_per_run` lookups a run; `storage.md`) — and
  paper details (below). It is **opt-OUT** (on by default; `=off` disables it, which is what the test suite sets).
  The backlog's one-off web-check sweep (`POST /inbox/web-check`, ruling 27b) is the person's start, so the gate is
  reported in its counts, never applied — the same pinned query and nothing else leaves.
  A user-initiated `sync_now`, `POST /maintenance/enrich-links`, `POST /maintenance/verify-sites`, the person's
  "check now" on one source (`POST /entities/{id}/sources/refresh`; a login-walled source is only marked asked for
  their agent, never fetched), every OAuth
  `authorize_url`/`exchange_code` call and OpenRouter's sign-in key exchange (`openrouter.ai/api/v1/auth/keys`,
  R-AG10; the key lands only in `secrets.env`) are **never** gated by it — they always need the network to
  do what the user just asked.
- **`CICADA_ALLOW_FEED_FETCH`** gates RSS/ICS polling and is **opt-IN** (`=1`). A fresh install's
  LaunchAgent plist sets it; `install.sh` never rewrites a plist behind a running backend, so an
  older plist needs the key added by hand. While it is off a subscribed feed's Sources row is not connected and says
  why (`channel_registry.FEED_FETCH_OFF`, 2026-10-23) — it read Connected over a poll that never ran. The feed poll,
  the ICS poll and `POST /sources/rss`'s `feedUrl` fetch go through `net_guard` on every hop since 2026-10-23 (they
  used a bare client, so a subscribed URL or a redirect could reach loopback, the LAN or a tailnet peer).
- **`CICADA_ALLOW_LOGO_FETCH=off`** disables logo fetching entirely, and media previews with it (below). The test suite runs that way
  and injects fetchers instead. It also gates the icons of the sites Reading in your browser (the Sources page) lists (G166): those
  come from the icon service only and the login-walled site is never contacted for its favicon (nor, since
  `fetch_logo` skips its first two rungs for a walled host, is a company or tool page's logo domain when it is one).
  It also gates a saved link's own site icon (owner ruling 2026-10-19; everywhere a saved link is drawn, 2026-10-20):
  a saved row asks the backend (`GET /sources/saved/{id}/site-icon`, or `/sources/saved/episodes/{id}/site-icon` for a
  Waiting row with no page yet; rows ask as they appear, at most four at a time), which asks the link's own registrable domain and **never an icon service**, so
  no third party learns what was saved — only when the person opens that list, never from the Sleep cycle. **Amended (owner
  2026-10-20: "when I open the website I can clearly see a favicon in the Chrome tab"):** discovery goes the way a
  browser does — the homepage (its www. host when the bare domain has no address; redirects on the same registrable
  domain, or — owner direction 2026-10-20, "a picture specific to the site, not a letter" — to the public, non-walled
  domain a renamed site moved to, each hop through the SSRF guard and never a hop the redirect-to-wall rule catches:
  a `consent.` host, a sign-in host or a sign-in path, refused before a byte is fetched), its `<link rel>` icon declarations, best raster first (≤ 3 asked), then `/apple-touch-icon.png` and
  `/favicon.ico`. An icon URL the page itself declares may sit on another host (a CDN): https only, every hop through
  the SSRF guard and kept on that host's or the site's domain, accepted only when it says `image/*` and its bytes sniff
  as a raster. 4 s for the whole discovery, ≤ 512 KB per response streamed, no cookies, a block (401/403/407/451) from
  the site stops it and is never retried; a base64 raster `data:` icon is decoded, capped at 512 KB. **SVG (owner
  ruling 2026-10-20: "yes, we should draw the SVG icon safely"):** only when no raster answered, at most two declared
  SVG icons (served or `data:`) are asked under the same declared-icon rules, ≤ 64 KB, sanitised (no DTD or entities,
  an allow-list of shapes/paths/gradients/transforms, no script, `foreignObject`, image, text, external `href` or
  `url()`, no CSS comments or filters, no mask or clip path applying another) and drawn to a 64×64 PNG by
  `svg_raster` in a child process whose descriptor limit is 0 (it can create no file or socket descriptor) and which is
  killed at 2 s; the release build draws one real icon this way before it ships; only the PNG is cached and served, SVG never is. The drawing makes no request of its own. Hits and misses
  cached under `logos/<bank>/sites/own/` (a miss from an older discovery is asked once more; `storage.md`).
  It also gates a watched video's still (owner direction 2026-10-19, Sources v4): a day the person opened in Sources ›
  YouTube history asks `GET /sources/watch-history/days/{episode}/videos/{id}/thumbnail`, which asks YouTube's own
  thumbnail host for that id only, and only for an id that day records; the media-preview rail, cached under
  `previews/<bank>/watched/` (`storage.md`). The same still for a saved YouTube video's row in a list the person
  opened (`GET /sources/saved/{id}/still`, marks-2): the id that page's own URL names, the same store.
  It also covers a person's public-profile photo, which has a second, narrower gate of its own:
- **`CICADA_ALLOW_PERSON_PHOTO_FETCH=off`** (G159 amendment, owner 2026-10-09; on by default, off for the test suite)
  stops every public-profile photo lookup for people while logos keep working. `person_photo` asks only when the app
  loads `GET /entities/{id}/photo` for a `person` page whose picture would be that rung — never from `/graph`, never
  from Sleep (a later warm-up would also sit behind `CICADA_ALLOW_CONNECTOR_FETCH`). **What leaves the Mac, exactly:**
  for the owner's own page, `https://gravatar.com/avatar/<sha256>?s=256&d=404`, where `<sha256>` is the SHA-256 of the
  owner's Settings email, trimmed and lowercased — the address itself never leaves the Mac and neither it nor the hash
  is logged or stored; for any person whose page lists a GitHub profile link, `https://github.com/<username>.png?size=256`
  with the username from that link. Nothing else: no name, no page text, no claim, no cookie or credential, a fixed
  User-Agent, and (as with any request) the Mac's network address. Each request is `https` to the provider's own hosts
  only (`gravatar.com` and its subdomains, `github.com`, `avatars.githubusercontent.com`), every redirect hop re-checked
  against that list and `net_guard`, at most three; 4 s a request (all its hops) and 10 s for the whole ladder, out of
  time being a transient miss; the body streamed and cut past 512 KB; kept only as a
  PNG or JPEG of 16–1024 px by its bytes (SVG refused whatever its header). `d=404` makes "no photo" a 404, so no
  default image is cached as a photo. **A public figure's portrait** (owner 2026-10-28, C; ruling 44's test): for a
  person page the full public test matched to ONE Wikidata item, after the GitHub rung — first ruling 44's local test
  once more, sending nothing; then `wbgetclaims` for that item's P18 (the item id only, on `org_sites.wikidata_get`'s
  rail: 4 s, ≤ 512 KB, no cookies, `net_guard`, a block never retried); then
  `https://commons.wikimedia.org/wiki/Special:FilePath/<file>?width=256` with the Commons file name P18 holds, every
  hop pinned to `commons.wikimedia.org` / `upload.wikimedia.org` and `net_guard`, under Wikimedia's User-Agent policy
  (`Cicada/1 (<repo URL>) httpx`, the project's contact). The person's name is never sent as a query; the Commons file name P18 holds may contain it (a portrait's file is usually named after its subject).
- **A project's organisation avatar** (owner 2026-10-28, E; behind `CICADA_ALLOW_LOGO_FETCH`, asked by `/logo` and the
  Sleep tail's logo warm-up like any logo): `https://api.github.com/users/<login>` with the owner login of a trusted
  repository URL, then — only when it answers `type: Organization` for that login — its `avatar_url` on
  `avatars.githubusercontent.com` at 256 px. Both pinned to those two hosts, SSRF-checked every hop, 4 s, ≤ 512 KB, no
  cookies; a personal account's avatar is never requested.
- **`CICADA_ALLOW_PERSON_PHOTO_PROXY`** (owner 2026-10-09; **on by default since ruling 36 D5, 2026-10-22** — the
  owner: "photo gate ON"; `off` still closes it) is the ToS rail's one exception: a
  person's photo through the unavatar.io avatar proxy, from an X, Instagram or LinkedIn profile link already in the
  person page's `sources:` and given as their own account (`https://x.com/<handle>` or twitter.com, one path segment;
  `https://www.instagram.com/<handle>`, one path segment, D5; `https://www.linkedin.com/in/<slug>` — never a post, a
  company page, a guess, or a link Cicada or an agent only proposed and the person has not taken). LinkedIn needs a login, so the proxy scrapes on Cicada's behalf; the owner chose
  that knowingly, and the person turns it on knowingly: each lookup tells a third party whom they know. It never runs
  past the two gates above. **What leaves the Mac, exactly:** the handle or slug, to unavatar.io only —
  `https://unavatar.io/x/<handle>?fallback=false`, `https://unavatar.io/instagram/<handle>?fallback=false` and
  `https://unavatar.io/linkedin/user:<slug>?fallback=false` — with
  the same fixed User-Agent, no cookie, no credential, no name and no page text; and, as with any request, the Mac's
  network address. Asked only after the email and GitHub rungs miss, X, then Instagram, then LinkedIn. `fallback=false` is unavatar's
  documented "404 when there is no avatar", so a default image is never cached as a photo. Every hop must stay on
  `unavatar.io` (a redirect elsewhere is refused and remembered as a miss) and pass `net_guard`; the same 4 s, 512 KB
  and raster-only rules. At most 25 lookups a UTC day across the install (the proxy's anonymous allowance per IP),
  counted in `$CICADA_HOME/pictures/proxy_budget.json`, outside every bank, and spent only once a request has passed
  the host and `net_guard` checks; a lookup over budget is a transient miss,
  asked again the next day, never a cached one. With the gate off, an X or LinkedIn link is not an identifier at all.
  **LinkedIn connections (owner 2026-10-17):** the profile link the person's own connections export put on a page it
  matched confidently — the connection's full name is the page's own name, or the person or an identified agent already listed
  that link (`match: name|link`) — counts as given and is asked at once, without waiting for the person to take the
  source: "If it's because I'm connected, unless the agent says 'Oh I'm not sure,' then we don't." An alias-only match
  (`match: alias`) is not sure, and its link is no identifier until the person takes it. Everything above still applies.

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

**litellm fetches nothing at import (2026-10-16).** `import litellm` used to request its model price-and-capability
table from GitHub (5 s timeout, falling back to the copy it ships), on every process start and behind no gate. `api/__init__.py`
forces `LITELLM_LOCAL_MODEL_COST_MAP=True` before any module can import litellm — the backend, the CLI, the MCP server and the
test suite all import that package first — and the CLI bootstrap and the settings file treat the name as a control key no
file can set. The table is the installed litellm's own, so prices and the key providers' tested defaults change only with
a litellm upgrade. A model the table does not list still runs; on OpenRouter its cost is OpenRouter's own reported charge
(`refs.cost_source: provider`, `storage.md`), elsewhere it is unknown (`None`) on the ledger, the Sleep page's cost lines
and the Usage aggregates, never `$0` (ruling 12).

**The Neural Engine search model's download (owner 2026-10-09).** EmbeddingGemma 2 (`api/services/model_fetch.py`) is
fetched only when the person asks: *Turn on* beside *Understand what you mean* in Settings → Privacy & data (the version picker and its confirm left the
app on 2026-10-22; `cicada index install` is the other door) — a selection alone never downloads
(`POST /embeddings/install` with `model`; the size is stated before the click from
the pins, `downloadBytes`), `make embedding-model-gemma2`, or `install.sh` on macOS 15+ — never on a schedule, never by Sleep,
never by the backend on its own. It reads one pinned revision of `FluidInference/embeddinggemma-2-coreml` from
`huggingface.co/<repo>/resolve/<revision>/<path>` (redirects followed to Hugging Face's own storage), the seven files
listed under `files` in `api/data/embeddinggemma-2.lock.json` and nothing else (never the audio encoder): about 585 MB, 30 s
to connect, 60 s between bytes, three tries a file, no cookies, no token, no account, a fixed `Cicada (search model
download)` user agent. Every file's size and sha256 are checked while it streams; one mismatch drops it and installs
nothing. The files land in `$CICADA_HOME/models/embeddinggemma-2` (staged beside it and swapped in whole), never in a
bank or the signed app; `NOTICE.txt` beside them carries the Apache 2.0 license and the Gemma Prohibited Use Policy.
The URLs are Cicada's own pins, never one someone else chose, so this is not a `net_guard` fetch — like the update
check and `scripts/fetch-embedding-model.sh`.

**The image encoder is its own click (design taste, 2026-10-14).** The same pinned revision's `vision_files` — the
vision `.mlpackage` and `position_embeddings.f16`, about 309 MB — are fetched only when the person presses *Turn on*
beside *Understand images* in Settings → Privacy & data (dimmed until the text encoder is here, so it is a second click;
the Looks page's own shortcut went with the page on 2026-10-20) (`POST /embeddings/install` with `model` and
`part: "vision"`), or runs `make
embedding-model-vision`; the text encoder is fetched first when it isn't here — the Looks shortcut's one click, whose
row states the combined size first (`vision.includesText`). Same transport, same checks (size and sha256 while streaming,
one mismatch installs nothing), staged in `.embeddinggemma-2.vision.partial` and grafted beside the text encoder, a
`cicada-vision.json` mark written last. **Nothing about a screenshot leaves the Mac:** the design board fetches no page,
no image and no font; its palette, tokens and vectors are computed here. A public page's HTML/CSS for tokens is a spec
item only (fetched once, on the person's click, through `net_guard` under the ToS rail) and is not built.

**The remote connector (G135) — the one way in from outside this Mac.** Off by default
(`~/.cicada/remote/settings.json`). When on, a **second listener on `127.0.0.1:8765`**
(`CICADA_REMOTE_PORT`) serves **only MCP and the agent API** (below) — none of the FastAPI routers — to cloud AI apps
through a tunnel **the person** runs (Tailscale Funnel or ngrok); **Cicada never starts, stops or
reconfigures a tunnel** — `GET /remote/status` only detects one — on PATH or in
the standard install folders, since an older LaunchAgent's PATH is bare (F2-back R-B15). Access is a per-connector
capability token `cic_rc_<id>_<secret>`: shown once, only its sha256 stored in
`~/.cicada/remote/connectors.db` (0600, never in a bank), scoped (`search`/`read`/`record` default;
`sources`/`answer`/`ask` opt-in — `sources` gates every verbatim word of the person's, recall's
episode excerpts and the inbox `Cause:` quote alike; `pending`, `mark_processed` and `repo_context`
never), expiring
(7/30/90 days) and revocable. It arrives as a secret link (`/c/<token>/mcp`) or a bearer header —
one verifier — or, since ruling 32, through sign-in (below), the way the docs now steer every app that supports it. Tools outside a connector's scopes are absent from `tools/list`; any `Origin` header
is refused; the listener has no access log (a secret link's path IS the token). Every remote write
commits alone as `Cicada-Author: <app harness>`, `Cicada-Session: rc_…`, trigger
`remote/<harness>`, no engine; a remote claim is `origin: remote:<id>` and can never be the
person's own words. Each call leaves one ids-only `remote_call` ledger row, filed beside `read` in
`reads-*.jsonl` so it never ticks the app's consumption domain. Every server-side fetch of someone
else's URL goes through `net_guard` (`is_global`, never `is_private`, because tailnet addresses are
neither; the name lookup runs off the event loop).

**Sign-in for the remote connector (ruling 32, owner 2026-10-19).** So claude.ai (web, desktop and its phone apps)
and ChatGPT can add Cicada as a custom connector, the G135 listener is also an **OAuth 2.1 authorization server**
(`api/remote/oauth.py`), and still serves nothing else: `/mcp`, the two protected-resource documents,
`/.well-known/oauth-authorization-server`, `/authorize`, `/authorize/wait`, `/token`, `/register` and `/revoke`; every
other path is a 404 and no FastAPI router is reachable. **Discovery:** a request to `/mcp` without a valid token is a 401
whose `WWW-Authenticate` carries `resource_metadata="<base>/.well-known/oauth-protected-resource/mcp"` and the default
scopes; that document names `<base>` as the one authorization server; the AS metadata advertises the code flow only,
`S256` only, `none`/`client_secret_post`/`client_secret_basic`, `client_id_metadata_document_supported` and
`authorization_response_iss_parameter_supported` (so ChatGPT uses its stable redirect URI). `<base>` is the person's
saved address, else the `Host` the tunnel forwarded. **Registration:** DCR (`/register`: https or loopback-http redirect
URIs only, ≤ 5, no fragment or credentials; unused clients pruned after a day, ≤ 200) or a Client ID Metadata Document
(an https `client_id`, fetched through `net_guard` under the ToS rail — 4 s, ≤ 64 KB, no cookies, no redirects — its
`client_id` must equal the URL, public clients only, cached a day; a client id that is not plain ASCII, or whose
host is not lower-case letters, digits, dots and dashes exactly as httpx would connect to it — a full-width dot, an
IDN, a host two parsers read apart — is refused before any fetch, so the host shown as publisher is the one asked). **Consent is never on the public page:** `/authorize`
checks the client and the redirect URI first (exact match; an `http` loopback URI matches on any port, RFC 8252 — Claude
Code's), and a mismatch is an error page, never a redirect (no open redirect); then it shows an eight-character code
and waits (meta refresh, no script, no form, a strict CSP, framing denied; it names no app). **The person approves by
typing that code** into the app — Settings → Devices → From anywhere, "A sign-in is waiting" — and only then sees who it
is and where it returns, choosing the scopes (what the app asked, else the defaults) and the expiry (7/30/90 days). The
app never lists codes and never offers a request to approve with a click (security review of #359: whoever starts a
sign-in collects its result from `/authorize/wait`'s redirect, PKCE included, so a stranger who registers an app called
"Claude" returning to claude.ai — or reuses Claude's public metadata-document client id — and waits for a click would
get the tokens; a typed code only the person's own page shows closes that). Waiting requests are listed only as
waiting, each with Deny, plus Deny all. A registered (DCR) client is never named or branded: it is "Unverified app
(registered <time> ago)" with the generic mark, and its connector's app is `other`; only a metadata-document client is
named, as "<its name>, published by <the host it was fetched from>" — the name is letters, digits, spaces, dashes and
apostrophes only, and one that claims a status ("published by", "verified", "official"…) is dropped. The loopback API is `GET /remote/oauth/requests`
(ref and times only), `POST /remote/oauth/match` and `POST /remote/oauth/approve` (by `userCode`, ten misses then a
minute's wait), `POST /remote/oauth/requests/{ref}/deny` and `…/deny-all`, behind the API token. The waiting page is
bound to its browser by an HttpOnly, Secure, `__Host-` cookie (Path=/, no Domain), so a leaked request id collects nothing; the client's `state` is
echoed untouched and `iss` rides every response, errors included. At most 50 requests wait; past that one is dropped —
the oldest of the source holding the most (the last address the tunnel appended to `X-Forwarded-For`, an IPv6
address as its /64, hashed), never the new one refused — so a flood evicts itself before the person's one sign-in; one unanswered for ten minutes
expires. The code is the one value stored in the clear (the page must show it again), and it is blanked when the
request is answered, denied or dropped.
**Tokens:** the code is single-use, 120 s, bound to the client, the redirect URI, the PKCE challenge and the resource;
a replayed code revokes what it issued. Access tokens (`cic_at_<connector>_<secret>`) live an hour; refresh tokens
(`cic_rt_…`) rotate on every use, and a rotated one presented again more than 30 s later (a client's own concurrent
refresh is forgiven) ends the whole grant and revokes the connector, so Settings shows it. An access token is good only for the resource it was issued for (its
audience). Every token, code, client secret and browser binding is stored as its sha256 only (`~/.cicada/remote/connectors.db`,
the same 0600 file), compared in constant time, and none is ever logged; the client's `state` is dropped once the
code is used. Approval creates an ordinary connector row (`auth: oauth`) — hashed, scoped, expiring, revocable — whose
app is read from where the code goes (claude.ai → Claude, chatgpt.com → ChatGPT, a loopback redirect from Claude's own
metadata document → Claude Code, else Other), so its writes carry that app's harness; revoking it in Settings ends its
access and refresh tokens at once, and a grant never outlives it. A signed-in connector has no link and cannot be
rotated. **Rate limits** (in memory): registration 10 then 2 a minute; authorization 10 then 6 a minute per source,
with no global ceiling (many sources could spend one; the 50-request cap and the fetch bucket already bound the cost);
token and revocation 30 a minute per registered client id and 300 in all — an unregistered id spends nothing (it is
refused as `invalid_client`), and a spent bucket still admits a valid refresh token or a live, unused authorization
code, so spamming an app's public client id cannot stop its sign-in or its renewal; document fetches 10 then 2 a
minute, each inside one overall 4 s deadline. A full client table (200) drops its oldest client that never got a grant
rather than refuse a new one, and any client — registered or a metadata document's — with no grant and no live request
is pruned after a day. A redirect URI with a backslash, a control character or a port that does not parse is refused,
registered or presented. **Origin:** refused everywhere except a GET of the two
sign-in pages (a browser navigation). Not supported: `private_key_jwt`, `client_credentials`, OpenID scopes.

**The agent API on the listener (G213; owner 2026-10-22, ruling 36 D3 — amends "serves only MCP").** A cloud agent
that cannot speak MCP (a texted personal agent, an agent that builds its own client from an OpenAPI document) can
reach only a public URL, so the listener also answers `POST /v1/<op>`, `GET /v1/me`, `GET /v1/openapi.json`,
`GET /v1/llms.txt` and `GET /llms.txt` — the same operations, envelope and status codes as the backend's own `/v1`
(`api.md`, "The agent API"), run by `api/remote/agent_api.call` through the one shared `RemoteRuntime`. Same gate,
same order: the `Origin` refusal, the token (`cic_at_`, `cic_rc_`, or an agent token `cic_api_` — which opens `/v1`
only, never `/mcp`), the per-connector rate limit, the 1 MB body cap; the `sources` scope still gates every verbatim
word of the person's, and a claim is `origin: remote:<id>`, never the person's own words. The two documents are open
(static, nothing about the person). No FastAPI router is reachable through it.

**The tunnel for sign-in is the person's, to this listener only.** claude.ai and ChatGPT reach the Mac from their own
servers, so the person exposes the G135 listener's port publicly with a stable hostname — `tailscale funnel --bg 8765`
or `ngrok http 8765 --url <their-domain>`. That is the one public port Cicada is ever reached on: the backend's own port
(8000) is never funnelled (the headless rail, `headless.md`), and Cicada never starts a tunnel. What the person runs is in
[`docs/connect-remote-apps.md`](../connect-remote-apps.md).

**A failed poll is recorded, not raised** (`sync_state.record_error`) and surfaces per-channel as
`lastError`; a gate-skipped poll is recorded distinctly (`record_skip`) so a skip never reads as a
failure or as a stale success.

**Media previews ride the picture gate (`CICADA_ALLOW_LOGO_FETCH`), like logos.** `GET /entities/{id}/preview` is the
app drawing a card; the first request for a page's source fetches it once (`media_preview.ensure_preview`) and every
later one is served from `$CICADA_HOME/previews/<bank>/`. With the gate off nothing is fetched and nothing is recorded
as a miss. A caller that runs on its own (`unattended=True`) also needs `CICADA_ALLOW_CONNECTOR_FETCH`; none does
today — no Sleep step warms previews. The fetch is the rail's: `net_guard` before the first request and every redirect
hop (≤ 3, never delegated to the client), 4 s, at most 512 KB read, no cookies, one fixed User-Agent; a walled host is
never asked, a 401/403/407/451 or a redirect onto a login host is a miss and is never retried with other headers.
Raster only, by magic bytes (PNG, JPEG, GIF, WebP; SVG refused; nothing under 16 px). A saved `.pdf` link is fetched
under the same 512 KB bound and its first page rendered in a child process (`pdf_page`); an arXiv or DOI paper is
never fetched (below). A YouTube video oEmbed gave no thumbnail for (embedding off) uses its standard still, a URL
Cicada builds on its own pin from the validated id. The person's own PDF (`POST /entities/{id}/picture/pdf`) fetches
nothing and is not gated.

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

**Exploring saved sites (G166, owner 2026-10-14) is the agent's browsing, not Cicada's fetch.** No server-side fetch is
added: the backend and the MCP server never open a site (`test_explore_tools.py` refuses every outbound connection
through the whole flow), so none of the three gates applies to it, and the connector gate is untouched. The person's own
agent visits each saved site **in their everyday signed-in Chrome session by default** (owner D2, amended): every
capture is marked `signed_in: true`, and the person's accounts carry the terms-of-service risk (the v3 acknowledgement
says so, D3). A switch in Reading in your browser (the Sources page) turns that off: the agent then explores in a private, cookie-less
`Target.createBrowserContext` the script creates and disposes of (verified drivable through browser-harness in a test
Chrome; an agent that cannot open one hands the site back as `skipped`, never falling back to the signed-in session).
The ToS rail's spirit binds the script: a wall or captcha is recorded `needs_login`/`blocked` with no screenshot and
**never retried with different headers, a different user agent or a different context**; consent banners are never
clicked or hidden (marked `consent_overlay`, a full-page one is `blocked`); one live lease per site, ≥ 8 s between pages
of a site, ≤ 30 an hour, ≤ 6 a lease and never past the hour's room (slice 2: only as many as the person's reason asks
for); further pages stay on the saved page's host, never a sign-in or account page, and only where robots.txt allows —
read once per visit by the agent's browser from the page's own origin without cookies (`credentials: 'omit'`), never
by Cicada; unread means no further page. Private workspaces and walled sites the person has not turned on are never
offered, and any site can be set to **Never explore**. Cicada's own "may have changed" probe (D6) is slice 3.

**Two ways in for what the person consumes (TODO ruling 47, owner 2026-10-28).** The owner's words: "connecting to
outside sources through api or third parties is good if mainly for ingestion, you know? Like a direct access to the
info we are consuming", then: "for a lot of stuff we can accept consumption over browser and macOS harness, that's what
I think. But for some specific things if we can do api integration that is awesome."

- **Tier 1, the default — the person's own browser and Mac.** What they read, watch and use is captured as they
  consume it, through the browser harness and the macOS harness: reading with the person's own agent (G166, above),
  the saved-list reads (G206), activity traces (G218, ruling 38, off by default; trace consolidation belongs to this
  tier) and the app's Mac readers. Every rail above is unchanged: the person's own signed-in session, Cicada never signs
  in on their behalf there, ticked or allowed sites only, the read limits, no backend scraping.
- **Tier 2 — an official API for a specific high-value source where one exists.** Telegram first (47a); candidates
  Notion, Readwise, Google, YouTube, Letterboxd (Spotify was one; it is export-only, see the table). "Cicada never signs in" is amended for this tier only: a
  connection is an API client the person authorised, never a browser session, cookie or profile, and the backend still
  never fetches a login-walled page. The existing Reddit, X and Pinterest connectors (`api/services/connectors/`) are
  of this kind.

**The choosing rule.** Each source's path is picked on purpose: an API when it gives clean, complete, structured data
the harness cannot (history, metadata, reliability); otherwise harness consumption. An export stays a way in either
way. As applied on 2026-10-28:

| Source | Path | Why |
|---|---|---|
| Telegram | API (47a) | full chat history and live updates; no harness sees them |
| Spotify | export only: the person's own "Extended streaming history" download (Spotify's privacy page), through G32's import; no API connector | Spotify's Developer Terms (v10, 15 May 2025) forbid it: §IV.2(b)(i) bars "using the Spotify Platform or any Spotify Content to train a machine learning or AI model or otherwise ingesting Spotify Content into a machine learning or AI model", and §IV.3(a) says "you may not store, aggregate or create compilations or databases of Spotify Content" and "Do not store Spotify Content indefinitely" — the bank is a lasting compilation that agents read, so the ToS rail rules the API out (2026-10-29). The download is the person's own data, given to them, not taken through the Spotify Platform. Capturing what is playing through the macOS harness waits on an owner ruling (G223) |
| Notion | API | a workspace's pages as structured blocks; a harness sees one page at a time |
| Readwise | API | highlights with their sources, complete |
| Google | Calendar on the Mac reader; API only for what the Mac cannot read (Drive, Docs), on ask | the Mac already reads Calendar |
| YouTube | harness (G71 browser history, Watch later through the agent) | the official API does not return watch history |
| Letterboxd | harness, plus its public per-diary RSS through the feed gate | its API is granted by request; adopt it only if granted |
| WhatsApp | local database, read by the app (built 2026-10-28, `whatsapp_source`; no network at all) | no sanctioned personal-account API; an unofficial client risks a ban |
| Pocket | export only | the service closed in 2025 |

What every tier-2 connection keeps:

- **The ToS rail below stands.** Official APIs or sanctioned connectors only. Never scraping behind a login, never an
  unofficial client that breaks a service's terms or risks the person's account being restricted — which is why
  WhatsApp stays on its local database, read by the app (no sanctioned personal-account API exists).
- **The person connects each one.** Off by default; the connect step says in plain words what it reads; disconnect and
  revoke are one click each, and disconnecting forgets the credential (`base.forget()`).
- **Read-only scopes wherever the service offers them.** Writing back to a service is a separate, explicit ask, never
  bundled into the connect.
- **Credentials** in `~/.cicada/secrets.env` (0600), or the keychain where the app holds them — never in a bank, a log or
  the repo (the rail below).
- **The normal capture path.** No model at capture; staged through `episode_staging`, scrubbed, with provenance; other
  people's words stay theirs (`external:<name>`, G179's rail); a demo bank refuses it like any capture.
- **Ruling 44's guard.** A private person's name is never sent to a service for a lookup. Ingesting the person's own
  account data is fine; looking people up through a connection is not.
- **Spend.** Rulings 4, 31 and 36 still apply: a connection that bills per call says so with its basis (as X's owned
  reads do), and none runs on a metered key nobody chose.
- **Gates.** A sync the person started is their click; a scheduled sync is a fetch Sleep or a timer starts on its own and
  sits behind `CICADA_ALLOW_CONNECTOR_FETCH`, like the connectors already are.

**47a — Telegram live sync, the first tier-2 case (owner yes, 2026-10-28).** Telegram's own client API (MTProto, through an
official client library) with the person's own login, so the chats they tick sync live like Messages, plus their history
when they ask. The session secret lives in `~/.cicada/secrets.env` (0600) or a 0600 file beside it in `~/.cicada` — never
in a bank. The connect step says in plain words that Cicada keeps a signed-in session to their account and how to end it
(Disconnect in Cicada, or Telegram's own Settings → Devices). Off until connected; only ticked chats are read (G179); the
bot channel (G29, `CICADA_TELEGRAM_BOT_TOKEN`) is unchanged. Built on `feat/telegram-live` (its own PR).

**The tier-2 framework (`api/services/connectors/tier2.py`, 2026-10-29).** One module behind every token connector
after Telegram. An adapter is a module in `ADAPTERS` with `TIER = 2`, so its Sources row, `GET/PUT/DELETE
/sources/connectors/{id}[/credentials]` and `POST …/sync` are the existing connector routes; it declares `TOKEN_ENV`,
`API_BASE`, `READS` (what it reads, in words — served as `reads`, with `tokenHelp`, on the status), `REFUSED_WORDS`,
`auth_headers`, `check(client)` and `fetch(client, cursor, bank) -> Batch`.
- **Connect** is the person's Save: `check` makes one read-only request to the service's own host with the pasted
  token; a refusal (or no answer) saves nothing and the 422 says why in words. **Disconnect** forgets every name in
  `SECRET_NAMES` and the connector's cursors in every bank.
- **Requests** go only to `API_BASE` (any other URL is refused), follow no redirect, keep no cookie (a fresh client per
  request), 15 s each; a 429 waits its `Retry-After` once (≤ 60 s), then stops in words with the cursor unmoved. No
  request carries a person's name or any query text.
- **Gates.** Refresh and `cicada connector sync` are the person's click (never gated). The scheduler's job
  (`tier2.scheduled_sync`, every 6 h, only connected connectors, the active bank) is a fetch Cicada starts on its own:
  behind `CICADA_ALLOW_CONNECTOR_FETCH` (a skip recorded in words), and skipped before any request while Sleep holds the
  pages. Sleep's tail never runs a tier-2 sync.
- **Errors** on the Sources row are the adapter's sentence or "<service> answered HTTP <status>" — never a URL, body or
  token (`sync_state.json` is in the bank and committed).
- **Credentials** — `CICADA_READWISE_TOKEN`, `CICADA_NOTION_TOKEN` in `secrets.env` (0600); every connector secret (the
  saved-content connectors' too) is in `connections.base.CONNECTOR_SECRET_ENV`, stripped from every engine child, so a
  model with tools never holds a key to the person's accounts. `CICADA_SECRET_ENV` (the master `CICADA_API_TOKEN`,
  the Telegram bot token and webhook secret) is stripped the same way, and the embedding worker and the PDF page
  reader start from `secretless_env()`, never a copy of the backend's environment. No remote door reaches these routes (the G135 listener
  serves `/mcp` and `/v1` only).

| Connector | Token | What is read | Terms |
|---|---|---|---|
| Readwise (`readwise.py`) | the person's access token, readwise.io/access_token (no read-only scope exists; only GETs are made) | `GET /api/v2/export/` (highlights with their books), `GET /api/v2/auth/` on Save | readwise.io/tos §8: "connect AI assistants and other tools to your content … through our APIs"; §3's scraper ban excepts the APIs |
| Notion (`notion.py`) | an internal connection with Read content only, shared page by page; a personal access token is refused | `POST /v1/search` (pages, no query), `GET /v1/pages/{id}/markdown`, `GET /v1/data_sources/{id}` (a row's database title), `GET /v1/users/me` on Save; Notion-Version 2026-03-11 | developers.notion.com: internal connections are for "syncing data from external tools"; 180 requests a minute per connection outside Business plans, honoured through `Retry-After` |
**47a amended — one-to-one chats only, each with the other person's consent (owner, 2026-10-28).** Telegram's terms, read the same day: API Terms §1.5 — "you are prohibited from using, accessing or aggregating data obtained from the Telegram platform to train … or otherwise engage in the development, enhancement or deployment of artificial intelligence, machine learning models" — and telegram.org/tos/content-licensing, "Large Language Models and AI": "Telegram firmly prohibits the scraping, indexing, harvesting, aggregation or use of data obtained from its platform to train, fine-tune, validate or otherwise engage in the development, enhancement, benchmarking or deployment of artificial intelligence, machine learning models and similar technologies. Exceptions may be granted in instances where all relevant users individually provide explicit, informed, affirmative and continued consent that is strictly limited to the specific content and chat, channel, or non-global context window for which it was requested." Sleep reads a sitting with a model, so the owner chose "1:1 with consent": group chats and channels are never offered and the backend refuses them; ticking a one-to-one chat needs the person to confirm, per chat and in plain words, that the other person agreed — explicitly, knowing what it means, for that chat only — said to be the person's responsibility, which Cicada cannot verify; the confirmation is kept with its date outside every bank (`$CICADA_HOME/telegram/consents.json`, 0600, a chat id and a time); unticking withdraws it and stops the reading. **Revisit** if Telegram grants Cicada an exception or changes those terms.

**How 47a is built.** `telegram_port` is the one seam to Telegram (plain values out, a fake in every test): Telethon v1
(MIT, pure Python, one hashed wheel for the Mac and a server, the whole login one `StringSession` string, no message
database of its own) over TDLib (Boost, faster at a full sync, but a native `libtdjson` to sign per platform and its
own encrypted message store — a second copy of the chats outside the bank). It is imported only when the person
connects. Its AES runs on `cryptg` (CC0, a hashed wheel); Telethon also imports `pyaes` unconditionally, which PyPI
ships as an sdist only while the release installs wheels only, so pyaes 1.6.1 (MIT) is carried as source in
`api/vendor/pyaes` (byte for byte from PyPI's sdist, its sha256 in `api/vendor/__init__.py`), loaded under its own
name by `telegram_port.load_telethon` when no installed one exists; the release lock is compiled `--only-binary :all:`
with pyaes left out, `test_release_build` fails any locked package with no wheel for the target, and the build's
import check loads the client (#504 review B5). **One-to-one is Telegram's peer, never a flag** (#504 review B4): a
user's marked peer id is positive, a group's negative, a channel's `-100…`; the tick route accepts only a chat
Telegram itself lists as one-to-one with a user, the flush drops any non-user peer's update, and the ingest refuses a
batch whose peer is not a user or does not match the conversation. `telegram_account` keeps the session at `$CICADA_HOME/telegram/session` — 0600 in a 0700 folder, beside
`secrets.env` but not in it, because `secrets.env` is projected into the environment every spawned `claude -p` and hook
inherits; a file anyone else can read is refused. **Connecting is "link a device" (ruling 49, owner 2026-10-29):**
`POST /sources/telegram/qr` asks Telegram for a sign-in token (`auth.exportLoginToken` through Telethon's `qr_login`,
`telegram_port.qr_start`/`qr_wait`) and answers `state: qr` with its `tg://login?token=…` link and expiry; a background
task waits for the person's phone to accept it (Telegram → Settings → Devices → Link Desktop Device), swaps in a fresh
token each time Telegram expires one (≈30 s; `QR_ROUNDS` = 10, then `off` with a sentence), and moves to `connected` —
or `password` for a two-step account, the one thing still typed. The wait is Telegram's own lifetime for the token
(measured on Telegram's clock through the client's time offset) less `QR_MARGIN_S`, never under `QR_FLOOR_S`, so a Mac
whose clock is off cannot burn the rounds; a refresh that finds the last token already scanned (`loginTokenSuccess`, or
a DC move then the import) is a sign-in, kept like any other. Any failure from the client in a sign-in step — a flood
wait, a socket error — answers a sentence (422), never a 500, and an unsigned client is closed. The link is held in memory only while shown, never
logged or kept. Number → code (`/connect`, `/code`) stays as the fallback. Stopping a sign-in half way (Disconnect while
`qr`, `code_sent` or `password` with no kept session) closes the client without a log-out — there is no session to
end. The session appears in Telegram → Devices as "Cicada", the OS family and Cicada's version
(`telegram_port.device_label`), never the Mac's name. **No local reader (ruling 49):** Telegram for macOS's own store
is a cache (the owner's probe: 59 one-to-one chats, median 1 message, none older than a year), so the official API is
the one Telegram path. The number goes to Telegram once and is never kept; codes and
passwords never. Disconnect logs the session out at Telegram, then deletes the file (a failed log-out still deletes
it and says where to end it). Cicada's own `api_id`/`api_hash`: a release carries the owner's pair in
`api/data/telegram_app.json`, written by `bundle.sh` from CI's `CICADA_TELEGRAM_API_ID` variable and
`CICADA_TELEGRAM_API_HASH` secret (`docs/RELEASING.md`); a person's own pair in `secrets.env` wins. One pair serves every
install (Telegram Desktop and TDLib clients ship theirs the same way); until the owner sets it, a release has none and
Connect says to add one (`credentials: null` on the status). The only network
peer is Telegram's own servers; no private name goes anywhere else.

**The ToS rail — this one is not negotiable.** A fetched page is 4 s / ≤ 512 KB / no cookies / never
behind auth. Consent interstitials and login walls are classified and retired as `junk` **without a
byte fetched**. **A block is never retried with different headers.** No scraping behind
authentication, ever.

**Credentials** live in `~/.cicada/secrets.env` (0600) — **never in a bank, never logged**. The
shared `base.forget()` removes them on disconnect, so a fields-vs-stored drift can't orphan a
secret. Where a vendor bills per request (X's "owned reads"), the sync result carries the count so a
cost is stated plainly rather than hidden behind a "connected" checkbox.
**A key is checked before it is saved (G50/G215, 2026-10-22):** one free GET of the provider's own model list, sent
only to that provider's fixed host (`key_check.PROBES`), on the person's Save, through `net_guard`, 6 s, no cookies,
nothing logged. A refused key is never saved; an unreachable provider is "Save without checking", the person's choice.
Only the key's last four characters ever leave the backend (`keyHint`). Every key a card stores is in
`MANAGED_KEY_ENV`, stripped from every `claude`/`codex` child (`scrubbed_env`). Where the key lives next (OS secret
store; never projected into the environment) is a pending rail amendment — research providers-2 §4.5.
Cicada's own Codex sign-in lives in `~/.cicada/codex/` — Codex's files, never opened by Cicada,
never in a bank.

**Video (Track V, 2026-09-05).** Only a provider's own player URL is ever loaded — YouTube
(`youtube-nocookie.com/embed/…`, incl. `videoseries?list=`), Vimeo, TikTok and Loom — and an
oEmbed response is read for its *fields* only, never its `html` blob: the player URL is derived
from the id by `video_urls.resolve` / `VideoRef`, so nothing a provider returns is ever executed.
**A stream is never derived** — no `yt-dlp`, no CDN or `.m3u8` URL lifted out of a page — so a
direct file the app plays is one the *user* saved as a direct URL. Twitch stays external (its
player validates `parent` against the real embedding origin; synthesising one is circumvention),
X and Instagram stay external. A video's picture is the backend's stored preview (`media_preview`: oEmbed's
`thumbnail_url`, else YouTube's standard still for the id) — a still image, never a frame or a stream, and the app no
longer loads it from the provider. The app itself makes **no** network call to classify: oEmbed runs
only on the ingest/enrich path, under the gates that path already has, and the three new
provider calls take the rail's own 4 s / ≤ 512 KB numbers rather than the older, looser `_TIMEOUT`.

---
