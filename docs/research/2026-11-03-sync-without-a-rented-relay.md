# Sync between devices without a rented relay (G132, ruling 51)

**Status:** research, 2026-11-03. Docs only: nothing was built, deployed, signed up for or spent. Prices, versions and
terms were checked on 2026-11-03 unless a source gives another date. No personal data appears here. Device names,
hostnames and addresses are left out or replaced with placeholders.

**The question (Rodrigo, 2026-11-03):** *"in the last acting owner conversation we were working on the sync between
machines for cicada (<server> and phone along with this one). Talking about having a main machine that runs
consolidation, and has memory synced between all nodes. We realized if we go on the tailscale route, there would be some
extra setup for all nodes, which is not exactly friendly for non-technical people and i was wondering if there was any
way to do a sync that doesnt need me to rent a relay or any of the sorts. Any ideas?"*

**Read first:** ruling 51 and 51a–e in [`TODO.md`](../goals/TODO.md); the [G132 row](../goals/memory-evolution.md#g132);
[the plan](../plans/2026-10-29-g132-sync-engine.md); `network.md` ("Decided, not built", "The relay: built on
localhost") and `headless.md`; the open PRs #572 (backend: one transport, direct first, relay as fallback) and #573
(app: Settings → Devices' Relay).

---

## 1. The short answer

**Yes, for the sync itself.** Cicada's devices can stay in sync with no server Cicada or the owner rents. It takes two
layers:

1. **The same network, directly.** Cicada already plans this; it needs only a Local Network permission prompt.
2. **The person's own cloud account as the encrypted mailbox when the devices are apart.** For Apple devices that is
   iCloud through CloudKit's private database, which costs Cicada nothing and also gives free pushes that wake the
   phone. Google Drive's app-data folder covers Linux and Android.

Ruling 51's sync was already designed as store-and-forward: idempotent transactions with a 7-day lifetime, deltas the
home can always rebuild from git, and frames sealed end to end. That design does not need a live relay. It needs a
mailbox both sides can reach, and the person already has one.

**One thing truly needs someone's always-on public server:** letting Claude's and ChatGPT's own phone apps call into
Cicada through the G135 connector. Their servers must reach a public address. That stays the person's own funnel
(ruling 32), or a hosted relay if the owner ever chooses one. The phone can still read and answer its inbox with no
public address, and the in-app chat (plan §6 b) needs none either.

The rest of this document gives the evidence, option by option, and the layered transport it leads to.

## 2. What "the relay" actually does: four jobs, not one

Ruling 51c bundled four jobs into the relay. They have different answers, so this document scores each option against
each job separately.

| Job | When it is needed | Does it need an always-on server? |
|---|---|---|
| **J1. Live path.** Frames flow while both devices are awake | Every fast-forward and every write, when both are online | **No** on the same network. Across networks it needs either a hole punch (which needs J3) or a forwarder |
| **J2. Mailbox.** Hold frames for a device that is asleep or off | A laptop home with its lid closed, a phone in a pocket | **Yes, something must be up.** It does not have to be ours: an always-on home is its own mailbox, and the person's cloud account is up |
| **J3. Rendezvous.** Tell devices each other's current addresses | Only for hole punching across networks | Yes, something both can reach. That can be the J2 mailbox, a public DHT, or a STUN server |
| **J4. Public address** for claude.ai and ChatGPT to call the G135 connector | Only for the AI apps' own servers | **Yes.** It must be a public, stable HTTPS name. Only funnel-style services or our own relay provide one |

**The design fact that makes "no rent" possible:** ruling 51a's transactions are already durable in each device's
outbox (7 days) and idempotent at the home (8-day key). Deltas are `cursor..HEAD` bundles the home can always rebuild,
and the E2E frames are transport-agnostic. Their counters already refuse a frame that arrives twice, by two paths
(`network.md`, "Direct first"). So J2 can be any dumb, eventually-consistent store that holds ciphertext for days.
Nothing has to be interactive except J4.

## 3. The facts every option is judged against

- **Sizes** (measured 2026-10-29 on a synthetic owner-scale bank, `network.md` mailbox table):
  - a capture commit's bundle is 1.1 KB p50 and 13 KB p95;
  - a heavy day is 11.2 MB when coalesced (18.5 MB as live per-commit deltas);
  - a drain's decay commit is about 10 MB synthetic, estimated at about 2.4 MB on the real bank;
  - the bootstrap is 53 MB synthetic, estimated at about 90 MB for the owner's real `.git` of 147 MB;
  - a coalesced standing mailbox is about 10–20 MB per bank.
- **Latency today** (#572, loopback): a fast-forward takes p50 365 ms direct and p50 473 ms over the relay. A sleeping
  home with 10 commits waiting catches up 0.17 s after its backend is up. Any mailbox below a few seconds is fine for
  this model.
- **The phone.** iOS suspends a backgrounded app. It cannot keep a listener or a websocket open, so it syncs:
  - in the foreground;
  - when the system grants background refresh, which is opportunistic;
  - when a push wakes it.
  A silent push needs an APNs provider, which is a server, with one exception: **CloudKit's own subscriptions push for
  free** (`CKDatabaseSubscription`). Those pushes may be coalesced, so each one is a hint to fetch, never the data.
  Apple's guidance is to fetch on launch, on each push and on request.
- **The laptop.** A closed-lid laptop on battery is asleep. The scheduled Sleep of 2026-11-03 at 3 AM failed on a
  network timeout with the lid closed. `sleep_catch_up` already runs a missed schedule after the Mac wakes.
- **Signing.** The Mac app is ad-hoc signed today, with no Developer ID and no notarization (`docs/RELEASING.md`).
  CloudKit needs an iCloud container entitlement, which needs a paid Apple Developer Program team. So does shipping the
  phone app to testers through TestFlight or the App Store. The phone app is Expo/React Native, has an Android package,
  and declares `ITSAppUsesNonExemptEncryption: false`. That export answer must be revisited once the phone carries the
  E2E layer.
- **Rails that bite.** The ones that matter here:
  - every device dials out, and nothing listens on a public port (ruling 51c, rail 3);
  - the relay never terminates TLS, and no plaintext memory leaves the person's devices (51c);
  - the backend binds 127.0.0.1 (G181 rail; #572 kept it);
  - the backend never opens `~/Library` paths, while the app reads and posts bytes (capture rail);
  - credentials never go in a bank (network rail);
  - copy is provider-neutral, though naming the person's *own* chosen account is allowed;
  - unset or off, nothing changes (51a).

## 4. The options

Each option below covers how it works, what the person sees, the cost and to whom, behaviour while the home is asleep,
the phone, Linux, the effort on top of #572, rail conflicts, and a verdict. §5 compares them in one table.

### 4.1 Same network, directly: Bonjour plus a socket (what #572 leaves open)

- **How.** The app advertises and browses `_cicada._tcp` (instance `c-<hash>`, already decided in #572). A peer
  connects and answers the relay's own challenge: a fresh nonce signed by a key on the home-signed membership. Then
  **the same sealed frames the relay carries** flow both ways.
  - There is no HTTP on this path and no bearer token, so the "pinned self-signed certificate" question in #572's
    *Needs the owner* goes away. The frames are already encrypted and signed end to end.
  - TLS with a PSK or a pinned key is optional hygiene that hides frame headers from the LAN. `network.md` already says
    "TLS on a direct socket is transport hygiene, not the trust boundary".
- **Who listens.** Per Apple's TN3179, as quoted in the phase-3b report:
  - accepting incoming TCP connections does not need local network access;
  - Bonjour does, and so do outgoing LAN connections;
  - a launchd *agent* is not exempt, but `AssociatedBundleIdentifiers` (already written by #572's
    `install-backend-agent.sh` change) attributes it to the app.

  So the **backend** can hold the frame socket itself, bound to a private address and only while the person shares a
  memory, while the **app** does the Bonjour half and hands the backend what it found (`POST /sync/discovered`, built).
  On Linux the backend does both, with no prompt there; `python-zeroconf` or Avahi handles Bonjour.
- **What the person sees:** one Local Network prompt, the first time they share a memory or add a device. Nothing else.
- **Cost:** nothing.
- **Home asleep:** nothing to talk to. This option does not cover J2.
- **Phone:** works while the app is in the foreground on the same Wi-Fi. That is also where pairing happens, since the
  QR is scanned in the same room, so **pairing and the 53–90 MB bootstrap belong on this path**, not in any mailbox.
- **Linux:** yes.
- **Effort on #572:** M. Add a frame-socket path beside `sync_relay_link`, reusing `Endpoint`, the counters and the
  in-process device door. Add the app's NWBrowser and NWListener half. Pairing over this path reuses the QR v2
  exchange.
- **Rails:** it amends "binds 127.0.0.1 only" for this one socket: private addresses only, off until the person shares
  a memory, and carrying no token. That is the owner's decision (D3).
- **Verdict: build it first.** It is free, has no setup, and carries pairing and the bootstrap.

**Apple peer-to-peer (AWDL, the transport under Multipeer Connectivity), for nearby devices on no shared Wi-Fi.**
Network framework's `includePeerToPeer` enables it for an app's own connections and listeners. Apple's DTS says AWDL
"has long been the transport layer underneath MultipeerConnectivity", and that moving to Network framework is the path
forward. Apple also warns that it "can consume significantly more power", so it should be up only briefly.

- It works Mac↔iPhone, app-owned, foreground only.
- It is useful for pairing and a bootstrap on a train or in a café. It is not a sync path.
- Wi-Fi Aware (iOS 26) is iPhone and iPad only. An Apple DTS engineer confirmed there is no macOS support, so it does
  not help Mac↔iPhone.
- **Verdict:** later, as a pairing nicety. Effort S–M once 4.1 exists.

### 4.2 Hole-punched P2P with no server of ours

**How often a punch works.** The best current measurement is ProbeLab's 2025 campaign: 4.4 M attempts from more than
85,000 networks found DCUtR hole punching succeeds **about 70% (±7.1%)** of the time, given that relay reservation and
address discovery succeeded first, with TCP and QUIC indistinguishable. Tailscale documents that a hard NAT on either
side relays rather than going direct. WebRTC vendors cite **about 10–20% of calls** needing TURN. Every source agrees
that mobile carrier CGNAT often behaves like a symmetric (hard) NAT. **The case that matters most, the phone on
cellular reaching a home behind a home router, is the one most likely to fail.**

**Every hole punch needs J3.** Both sides must learn their public mapping (STUN or the equivalent) and exchange
candidates at the same moment through something both can reach. "No server of ours" therefore means borrowing
someone else's.

- **iroh (n0).** iroh is 1.0 since June 2026; the Python `iroh` package is 1.2.0 (2026-10-22, PyPI), and Swift is built
  from the same "tier 2" FFI. Its hole punching is coordinated through its relays, and its default address lookup is
  pkarr/DNS at `dns.iroh.link`, run by n0. The relays are stateless: "they don't store your application data", so
  **there is no mailbox**.
  - n0's public relays are free but documented as **"suitable for development and hobby use only"**: rate-limited, no
    SLA, older versions dropped at will. The docs recommend against them for "sensitive or confidential data", and n0
    "may block offending IP addresses or users".
  - Production means n0's Pro plan, listed at $19/month with an included endpoint count and per-endpoint fees beyond
    it (n0's docs disagree on the overage rate), or a self-hosted `iroh-relay`. Either one is rent.
  - **Verdict: no.** The free tier's terms rule it out as a product default, and it still needs a mailbox.
- **Hyperswarm / HyperDHT (Holepunch).** Its public bootstrap nodes are "served on behalf of the commons". The stack is
  Node/Bare-first: there is no official Python or Swift, only a third-party C++ port with a Python wrapper, and Swift
  is "planned". **Verdict: no.**
- **libp2p (DCUtR plus circuit relay v2).** It needs public relay nodes. go-libp2p caps a relayed connection at 2 min and
  128 KB per direction (phase-3a research), there is no store-and-forward, py-libp2p is immature, and Swift has nothing
  production-grade. Borrowing IPFS's public nodes as relays is freeloading on a commons. **Verdict: no.**
- **WebRTC with public STUN.** STUN is cheap and widely offered for free (Google's and Cloudflare's public STUN
  servers), but it only reveals each device's own public address. The 10–20% of cases needing TURN need a TURN server,
  which is rent. Signalling would go through the J2 mailbox. That is "our own ICE": `aiortc` in Python and the heavy
  WebRTC framework on iOS. **Verdict: possible, later, only if measured mailbox latency hurts.**
- **The BitTorrent Mainline DHT through pkarr** is a genuine commons with no operator. It stores signed records of 1,000
  bytes or less under an Ed25519 key, which fits Cicada's device keys. Records must be republished about hourly, and a
  cache miss "might take few seconds" to resolve. It solves discovery only: no mailbox and no hole-punch coordination.
  Some networks treat DHT traffic as torrenting. **Verdict: park.**

**Is "someone else's free relay seeing only ciphertext" acceptable under the rails?** Technically yes: ruling 51c's
trust model is already "untrusted by design", and a borrowed relay learns what Cicada's own would (IPs, timing, sizes).
On terms, **no** for every free relay checked here:

- n0 says development and hobby use only;
- Syncthing's pool is volunteer-run for Syncthing, and no published terms invite other software;
- IPFS and libp2p relays are a commons built for IPFS.

A product that ships to other people cannot default to them. Tailscale's DERP (§4.5) is the exception: it is offered
to Tailscale's own users under its terms.

### 4.3 The person's own cloud as the mailbox

The phase-3a frames are the payload unchanged. The cloud only stores sealed frames named by sender and counter. A
receiver opens them with the same `Endpoint.open`, and the counters refuse duplicates.

**(a) CloudKit private database (iCloud): the recommended mailbox for Apple devices.**

- **How.** A custom zone `cicada-sync` in the app's container, in the person's **private** database. That database is
  per Apple ID, so every device signed into the person's Apple ID sees the same zone with no location to pair.
  - A `Frame` record: `recordName = <sender key>-<ctr>-<part>`, so a resend is idempotent. Its fields are `to` and
    `kind`, plus the sealed bytes as an asset of 1 MiB or less (the relay's frame bound).
  - A `Status` record per sender with a fixed name, so it is latest-only by overwrite.
  - Receivers fetch zone changes since their change token. `CKSyncEngine` (macOS 14+, iOS 17+) wraps this.
  - The home deletes a transaction once it has applied and answered it, and deletes deltas that every device's
    announced `copy_head` has passed or that it superseded (the `supersede` rule, done by the home).
  - CloudKit has no TTL, so the home enforces the 7-day expiry by sweeping.
- **Who talks to CloudKit.** On the Mac, **the app** (the entitlement is the app's): the backend hands outgoing frames to
  the app and receives incoming ones over loopback. No file is read, so the `~/Library` rail holds. On the phone, the
  phone app, through a native module.
- **What the person sees:** nothing, if they are signed into iCloud on each device, which is the normal state. One line
  in Settings → Devices names the person's own choice ("Your devices exchange encrypted updates through your iCloud").
- **Cost.** Nothing to the owner per user. Apple's DevRel: "the usage of a CloudKit private database is counted to the
  user's quota", and quota errors surface as `CKError.quotaExceeded`. The standing mailbox is about 10–20 MB once
  coalesced; the bootstrap goes over the LAN (4.1), not the cloud.
  - **Risk:** many people's free 5 GB tier is already full. Then Cicada says so in words and keeps syncing on the same
    network.
  - The owner's cost is the **Apple Developer Program**: one team, not per user. The same membership also unblocks
    Developer ID, notarization and phone distribution.
- **Home asleep:** frames wait in the person's iCloud. Pushes wake the app when it is running on the Mac, and wake the
  phone even when it is suspended (best effort, coalesced).
- **Phone:** the best option for it, because it is the only free push channel.
- **Linux:** **not practical.** CloudKit Web Services reach a private database only with an API token plus a user
  `ckWebAuthToken` from an Apple ID sign-in in a browser.
  - Server-to-server keys are documented for the **public** database only.
  - The token is "intended for a single round trip": every response returns a new one and invalidates the old.
  - It expires after 30 minutes, or **2 weeks** with "Keep me signed in" (Apple's archived reference). Whether rolling
    use extends the 2 weeks is undocumented.
  - A headless server would need the person to sign in again about every two weeks.
- **Effort on #572:** M–L.
  - A mailbox path in the transport. It is store-and-forward with no request/response, so `control` asks, such as the
    home-move peer calls, keep their short "asleep" timeout.
  - A loopback bridge route pair in the backend.
  - The app's CloudKit module, and the phone's native module.
  - It is gated on the developer team (D2).
- **Rails:** ciphertext only, on the person's own account; every device dials out; nothing listens. **It amends 51c**:
  the hosted relay stops being the default mailbox (D1).
- **ToS:** this is CloudKit's intended use (an app's data in the user's private database).

**(b) Google Drive app-data folder: the second mailbox (Linux, Android, non-Apple people).**

- **How.** The same frames as files in `appDataFolder`, using the `drive.appdata` scope, which **Google classifies as
  non-sensitive**: basic verification and no CASA security assessment. The backend speaks REST directly on Mac or Linux
  with an installed-app OAuth flow, keeping the refresh token in the keychain or `secrets.env`.
  - Drive's push (`changes.watch`) needs a public HTTPS webhook, so receivers **poll** `changes.list`.
  - Quotas are per project 1,000,000 units a minute and per user 325,000 a minute. A list costs 100 units, so polling
    once a minute is about 144k units a day per device, far inside the limits.
  - It is free; Google plans billing only above 400 M units a day per project.
- **What the person sees:** one "Connect your Google account" consent per device.
- **Cost:** nothing per user. The owner needs a free Google Cloud project and OAuth client, **published "In
  production"** with brand verification. Unverified apps show a warning and cap users, and refresh tokens issued while
  an app is in "Testing" expire after 7 days (Google's OAuth policy; re-verify before building).
- **Home asleep:** frames wait. **Phone:** Android natively; on iOS it works but has no free push, so it falls back to
  polling in the foreground or in background refresh. **Linux:** yes, the best fit there.
- **Effort:** M (backend only). **Rails:** as (a); a new outbound destination behind the person's own connect step.

**(c) Dropbox app folder.** It has the same shape as (b). Development apps cap at 500 linked users, and once 50 are
linked the developer has two weeks to win production approval or new links freeze. **Verdict:** only if testers ask
for it.

**(d) A private GitHub repository holding encrypted bundles.** It is natural for a git-shaped bank and free. But it
needs a GitHub account and a token (not non-technical), it has no push, and it means using a code host as a message
bus. **Verdict:** no as a mailbox. The push-only backup idea in the G132 row stays separate.

### 4.4 Tunnels without accounts (Cloudflare quick tunnels and the like)

Cloudflare's quick tunnels (`trycloudflare.com`) need no account. Cloudflare documents them as:

- **"intended for testing and development only"**;
- limited to 200 in-flight requests (beyond that, 429);
- **no Server-Sent Events**;
- no uptime guarantee;
- **a new hostname each time** one is created.

Until a 2026-10-02 change added a protected mode, anyone holding the URL could reach the service.

**Why they fail the rails and the job:**

1. **Cloudflare terminates TLS**, so memory crosses a third party in plaintext. That breaks 51c's "never terminate
   TLS / no plaintext memory leaves the person's devices".
2. It is an inbound public address onto a device, beyond the G135 listener the rails allow.
3. It does nothing for a sleeping home.
4. As the G135 address it fails too:
   - a hostname that changes at every start breaks the connector URL and the OAuth issuer the AI apps registered;
   - no SSE breaks streamable MCP.

**Verdict: no.** The same holds for ngrok's default HTTPS endpoints, which terminate at ngrok's edge. That already
applies to ruling 32's funnel option, and is worth a note there.

### 4.5 Anything else credible

**Tailscale, made as close to zero-setup as it gets.**

- **Today:**
  - each device installs the Tailscale app and signs in;
  - on iOS the person approves a VPN profile;
  - Cicada's Settings → Devices runs the one shown `tailscale serve` (built, owner 2026-10-29).
- **Free tier:** Tailscale's 2026-04-08 pricing change made the Personal plan free for up to 6 users with unlimited
  user devices.
- **Embedding it** removes the app install and the VPN profile, but not the account. `libtailscale` is a C library
  ("embeds Tailscale into a process") with a `swift` directory (TailscaleKit, built from source, no published binary)
  and a `python` directory whose status is undocumented. Go's `tsnet` is the reference.
  - Each device still signs in to a Tailscale account in a browser, the first one creating it. The home cannot mint
    auth keys for the others without an admin-console API credential.
  - The phone is foreground-only, as with everything else.
  - **There is no mailbox:** a sleeping home is unreachable.
- **The one thing it uniquely gives for free is J4:** `tsnet.ListenFunnel` serves a public HTTPS name, with TLS
  terminated *on the device*, on ports 443, 8443 or 10000, once the person allows Funnel in their admin console. That
  is ruling 32's funnel without the Tailscale app.
- **Effort:** L. It means a Go sidecar in the release bundle and a native module in the phone app.
- **Verdict:** keep Tailscale as the technical path it already is (no change). Revisit embedded `tsnet` **for J4 only**,
  if the owner wants the AI phone apps without a hosted relay.

**Syncthing's model.** Syncthing does exactly what ruling 51c describes: direct first, community relays that see only
TLS ciphertext and traffic volume, and global discovery servers run by the project. Its relays are "community-
contributed" for Syncthing users, and no published terms invite other software. It confirms the architecture; it does
not give Cicada free infrastructure.

**The person's own always-on machine as their relay.** A technical person with a server and a public address or port
forward can run `relay/` today (`network.md`, "Self-hosting the relay"). For people who have one, this costs nothing.
It stays the self-host path.

**An always-on home makes J2 nearly disappear.** If the home never sleeps, it is its own mailbox. Every device's
transactions apply as soon as they reach it, and a phone that was off simply asks `cursor..HEAD` when it wakes. What
remains is reach from outside the home network: J1 and J3, which is §4.3's mailbox or a tailnet. See §8.

## 5. Side by side

| Option | Setup the person sees | Cost, and to whom | Home asleep | iPhone | Linux | Effort on #572 | Rail conflicts | Verdict |
|---|---|---|---|---|---|---|---|---|
| 4.1 LAN frame socket + Bonjour | one Local Network prompt | none | — (live only) | foreground, same Wi-Fi | yes | M | amends loopback-only for one socket (D3) | **build first** |
| 4.1 AWDL nearby | none | none | — | foreground | no | S–M after 4.1 | none | later, pairing nicety |
| 4.2 iroh / Hyperswarm / libp2p | none | n0 Pro $19+/mo or self-host for production | no mailbox | foreground | yes (iroh) | L | free relays' terms | no |
| 4.2 own ICE (public STUN + cloud signalling) | none | none (no TURN → ~10–30% fail) | — | foreground | yes | L | a new outbound gate | defer; measure first |
| 4.3a CloudKit private DB | none if signed in to iCloud | person's iCloud quota; owner: Developer Program | **yes** | **yes, free push** | not practical | M–L | amends 51c default (D1) | **the mailbox for Apple devices** |
| 4.3b Drive app-data | one Google consent | free; owner: published OAuth client | yes | Android native; iOS polls | **yes** | M | new outbound destination | second mailbox |
| 4.3c Dropbox app folder | one consent | free; production approval | yes | polls | yes | M | same | only on demand |
| 4.3d private GitHub repo | account + token | free | yes, polled | weak | yes | M | — | no |
| 4.4 Quick tunnel | none | none | no | — | yes | S | **TLS terminated by a third party; public inbound** | **no** |
| 4.5 Tailscale (today) | app + sign-in per device, VPN profile on iOS | free Personal plan | no mailbox | yes (app) | yes | built | none | keep for technical users |
| 4.5 embedded `tsnet` | browser sign-in per device | free Personal plan | no mailbox | foreground | yes | L | none | J4 only, later |
| Cicada relay, self-hosted | paste a URL | the person's own box | yes | foreground + mailbox | yes | built | none | keep as advanced |
| Cicada relay, hosted | none | **owner rents** (~€6.50/mo up to ~€80–90/mo at 10k users, phase-3a research) | yes | yes | yes | built | none | only if J4 ever needs it |

## 6. Recommendation: a layered transport, no rent

The transport tries layers in order. Every layer carries **the same sealed, signed, counted frames** (phase 3a), so a
frame sent by two layers applies once.

1. **Same network: the LAN frame socket (§4.1).** It is found by the app's Bonjour, authenticated by the membership
   challenge, and carries no token. Pairing and the bootstrap use it, which suits pairing because the QR is scanned in
   person.
2. **Apart: the person's own cloud as the mailbox (§4.3).** iCloud for Apple devices, built first; Google Drive's
   app-data folder for Linux and Android, second. The home deletes what it has consumed and coalesces deltas, and
   CloudKit's free pushes wake the phone.
3. **Tailnet (unchanged):** the technical path that already exists. It covers an always-on Linux home and a person who
   already runs Tailscale.
4. **Cicada's relay, self-hosted (built, advanced setting):** for people with their own public machine.
5. **Not now:** hole punching, every borrowed free relay, quick tunnels, and a hosted relay. A hosted relay comes back
   only if the owner wants J4 (the AI apps on the phone) without the person's own funnel. Even then it would be the
   connector's address, not the sync path.

**What this changes in ruling 51c, if the owner agrees (D1):** "devices meet at an end-to-end-encrypted relay … hosted
by default" becomes "devices meet directly on their network and through an end-to-end-encrypted mailbox in the
person's own cloud account. Cicada's relay is self-hostable and optional, and a hosted one exists only if the owner
chooses it." The trust model is unchanged: the mailbox, like the relay, sees only ciphertext, sizes, timing and
counts. It is tied to the person's Apple ID or Google account instead of a random mailbox id, a provider the person
already trusts with that account.

## 7. What should change in #572 and #573 before merge

**#572 (backend): merge it, with four small changes.** Its core is right: one transport, the HTTP-shaped request run
in process through the device door, the E2E layer reused, no relay imported when unset, and the asleep-peer timeout.

1. **Name the fallback a mailbox, not "the relay".** Make the second path an interface, `deliver(frame)`, `poll()` or
   push, and `ack/delete`, with `sync_relay_link` as its first implementation. Then the CloudKit bridge and Drive slot
   in without touching the follower or the outbox. At minimum this is a docstring and a seam; the code can follow.
2. **The 30 s status heartbeat only on live paths.** A store-and-forward mailbox gets status on change only, as a
   latest-only record. Re-sealing every 30 s would be 2,880 cloud writes a day per home.
3. **QR v2: make `relay` optional and add a `paths` hint** (LAN candidates). A device paired in person over the LAN
   must not need a relay URL.
4. **Withdraw the *Needs the owner* item "a LAN listener with a pinned self-signed certificate".** Replace it with D3's
   frame socket, which carries frames, not HTTP. No token ever crosses the LAN, so no certificate pinning is needed for
   trust.

**#573 (app): hold the Relay section, or ship it only as *Your own relay (advanced)*.** A wss:// address field as a
main affordance asks a non-technical person for exactly the setup this question is trying to remove (UX principle 1).

- The QR v2 sheet, the six digits, "Two devices answered this code" and Revoke's new words are transport-agnostic.
  Keep them, and let them pair over the LAN path once it exists.
- Merge after #572's QR change so the sheet does not show a relay address it may not have.

## 8. Should a laptop be the home?

**It can be, and for a person with one computer it must be.** Nothing is lost while it sleeps:

- the other devices read their own replicas;
- their writes wait in their outboxes and in the mailbox (7 days);
- Sleep runs at the next wake (`sleep_catch_up`).

The cost is delay: a phone's answer to an inbox question lands when the lid opens, and a 3 AM schedule on a
closed-lid laptop is in effect "the next wake". Two things follow:

1. **When an always-on computer is in the group** (a desktop, a Mac mini, a Linux server), **the Sleep page should
   suggest making it the home**, in one line. That is the person's choice, never automatic, because ruling 51a moves
   the home only from the Sleep page.
   - An always-on home is its own mailbox: transactions apply as soon as they arrive, and scheduled Sleep runs on time.
   - The mailbox then matters only for reaching it from outside the home network.
   - **The catch for a Linux home:** it cannot use the iCloud mailbox (§4.3a). An always-on Linux home with an iPhone
     outside the house needs the Drive mailbox or a tailnet.
   - For the technical owner's three devices (a laptop, an always-on Linux server, a phone), the tailnet already does
     this. An always-on Mac home avoids the catch.
2. **A laptop home's schedule should say what it will do:** "runs at the first wake after 3:00". It should not fail on
   a network timeout in a dark wake; a missed run already catches up. Whether a lid-closed run should be skipped
   rather than started belongs to the scheduled-Sleep code, not this transport. It is noted here because the brief
   asked.

## 9. Decisions for the owner

Each decision is a one-line question with the recommended answer.

- **D1.** May the person's own cloud account (iCloud first, Google Drive second) be the encrypted mailbox, making the
  hosted relay optional rather than the default (amends 51c)? **Yes.**
- **D2.** Join the Apple Developer Program, about $99/year once for the owner and nothing per user, for CloudKit
  (which also gives Developer ID, notarization and TestFlight for the phone)? **Yes.**
- **D3.** Should the LAN path be a frame socket on a private address, carrying sealed frames with no HTTP and no token,
  off until the person shares a memory, with the app doing Bonjour, instead of #572's pinned-cert HTTPS listener
  (amends "binds 127.0.0.1" for that socket only)? **Yes.**
- **D4.** Should Local Network permission be asked only when the person first shares a memory or adds a device, never
  at first launch? **Yes** (as #572 proposed).
- **D5.** Defer hole punching (public STUN with cloud signalling, or iroh on paid or self-hosted relays) until the
  mailbox's latency is measured? **Yes, defer.**
- **D6.** For now, should the phone's Claude/ChatGPT connector keep needing the person's own funnel, with the in-app
  chat as the zero-setup phone path, and no hosted relay? **Yes.** Revisit with embedded `tsnet` Funnel or a hosted
  connector-only relay.
- **D7.** When an always-on computer is in the group, should the Sleep page suggest it as the home (one line, never
  automatic)? **Yes.**
- **D8.** Google Drive's app-data mailbox: build it only when a Linux-home or Android tester needs it, with a free
  Google Cloud OAuth client published "In production"? **Yes, second.**
- **D9.** #573: hold the Relay URL row, or ship it under *Your own relay (advanced)*, keeping the pairing sheet
  transport-agnostic? **Ship it as advanced, after #572's QR change.**

## 10. What to build next, in order

1. **#572's four changes (§7), then merge; #573 as advanced, after it.** S.
2. **The LAN frame socket and the app's Bonjour half; pairing and the bootstrap over it** (D3, D4). M. Measure: fast-
   forward p50/p95 on a real LAN against #572's loopback numbers, and the first copy of an owner-scale bank.
3. **A CloudKit spike, once D2 is done:** a Mac and an iPhone on one Apple ID. Measure write → push → fetch latency
   p50/p95 with the phone suspended; quota behaviour on a full 5 GB account; throttling (`requestRateLimited`); and the
   app bridge's cost when idle. The CloudKit mailbox is built only on those numbers.
4. **The CloudKit mailbox:** the backend's loopback bridge, the app's module and the phone's module. M–L.
5. **Laptop-home behaviour** (D7, §8.2). S.
6. **The Drive mailbox**, when a tester needs it (D8). M.

## 11. What I could not check

- **CloudKit's real latency, throttling and push delivery rate**, for a suspended phone and a sleeping Mac. Apple
  publishes none; §10.3 measures them.
- **Whether a CloudKit web token's 2-week life rolls forward with use.** It is undocumented, and it decides whether a
  Linux home could ever use iCloud.
- **Google's 7-day refresh-token expiry for "Testing" apps.** Stated from Google's OAuth policy as known; re-verify
  before building.
- **libtailscale's Python binding status**, and whether TailscaleKit runs on iOS without the VPN entitlement. A Flutter
  wrapper says a userspace tunnel needs none; TailscaleKit's own docs do not say.
- **The >90% "direct" figure some write-ups attribute to Tailscale.** No primary source was found, so it is not used.
- **A measured CGNAT share for any carrier.** The sources agree qualitatively only.
- **Whether DarkWake or Power Nap ever give a closed-lid laptop on battery enough network to run Sleep.** It is not
  relied on here.

## Sources

Accessed 2026-11-03 unless noted.

- iroh relays: <https://docs.iroh.computer/concepts/relays>; public relays' terms:
  <https://docs.iroh.computer/iroh-services/relays/public>; address lookup:
  <https://docs.iroh.computer/concepts/discovery>; pricing: <https://iroh.computer/pricing>,
  <https://docs.iroh.computer/iroh-services/relays/shared>; PyPI `iroh` release history: <https://pypi.org/pypi/iroh/json>
- ProbeLab, "Challenging Tribal Knowledge — Large Scale Measurement Campaign on Decentralized NAT Traversal"
  (arXiv 2510.27500): <https://arxiv.org/html/2510.27500v1>; per-NAT-class follow-up:
  <https://probelab.io/blog/can-libp2p-punch-through-nats/>
- Tailscale device connectivity (easy/hard NAT, relayed cases): <https://tailscale.com/kb/1411/device-connectivity>
- Tailscale pricing v4 (2026-04-08): <https://tailscale.com/blog/pricing-v4>, <https://tailscale.com/pricing/>
- libtailscale: <https://github.com/tailscale/libtailscale>; `tsnet` (`ListenFunnel`):
  <https://pkg.go.dev/tailscale.com/tsnet>
- WebRTC TURN share (vendor-cited): <https://www.metered.ca/blog/what-is-a-turn-server/>,
  <https://www.expressturn.com/blog/webrtc-calls-fail-on-mobile-networks>
- Hyperswarm/HyperDHT: <https://docs.pears.com/reference/building-blocks/hyperdht/>,
  <https://github.com/jjacke13/hyperdht-cpp>
- pkarr: <https://github.com/pubky/pkarr>
- Syncthing relaying: <https://docs.syncthing.net/users/relaying>, <https://docs.syncthing.net/users/strelaysrv>
- Apple TN3179, local network privacy (as quoted in the phase-3b report, fetched there 2026-10-30):
  <https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy>
- Network framework `includePeerToPeer`: <https://developer.apple.com/documentation/network/nwparameters/includepeertopeer>;
  DTS on Multipeer vs Network framework: <https://developer.apple.com/forums/thread/829633>
- Wi-Fi Aware: <https://developer.apple.com/documentation/wifiaware>; no macOS support:
  <https://developer.apple.com/forums/thread/787701>
- CloudKit private-database quota (Apple DevRel): <https://developer.apple.com/forums/thread/35633>;
  `CKDatabaseSubscription`: <https://developer.apple.com/documentation/cloudkit/ckdatabasesubscription>; CKSyncEngine:
  <https://developer.apple.com/documentation/cloudkit/cksyncengine-5sie5>; WWDC16 CloudKit best practices (pushes
  coalesced): <https://wwdcnotes.com/documentation/wwdc16-231-cloudkit-best-practices/>
- CloudKit Web Services (API token, `ckWebAuthToken`, 30 min / 2 weeks, server-to-server keys for the public
  database): <https://developer.apple.com/library/archive/documentation/DataManagement/Conceptual/CloudKitWebServicesReference/SettingUpWebServices.html>
- Google Drive scopes (`drive.appdata` non-sensitive):
  <https://developers.google.com/workspace/drive/api/guides/api-specific-auth>; usage limits:
  <https://developers.google.com/workspace/drive/api/guides/limits>
- Dropbox developer guide (development status, 500 users, 50-user review): <https://www.dropbox.com/developers/reference/developer-guide>
- Cloudflare Quick Tunnels: <https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/>; protected quick
  tunnels (2026-10-02): <https://developers.cloudflare.com/changelog/post/2026-10-02-protected-quick-tunnels/>
- Cicada's own measurements: `network.md` (the mailbox table, the cost model) and the phase-3a/3b reports and PR #572's
  body (latencies, idle cost).
