# Cicada — Context Passport Roadmap

**Date:** 2026-07-13 · **Supersedes:** the G-item backlog framing in [`memory-evolution.md`](memory-evolution.md) (G-numbers cross-referenced below; that doc stays the historical log)

## North star

Cicada is a **context passport of oneself**: all personal context in one place — conversations, calendar, music, projects, repos, people, ideas, tastes, possessions, wishlist, places, fitness — **transferable, easy to read, and easily explorable, visualizable, and auditable** through the app. A bank of knowledge covering the whole human experience, not just work.

Everything below is organized around that yardstick, grounded in a code-verified gap analysis (2026-07-13, two-agent audit on `dev` @ `ca345c9`).

---

## Where we are: the honest coverage map

| Domain | Coverage | What exists / what's missing |
|---|---|---|
| Conversations/chats | ✅ **Full** | The core pipeline: MCP capture, multi-format import (Claude/ChatGPT/Gemini), 5-stage Sleep, provenance. Only the quality gap (thin pages) remains → Track A |
| Bookmarks/reading | ✅ Strong | Chrome/Safari sync, RSS, media ingestion, relevance feed. Coarse media taxonomy (G2) |
| Projects | ✅ Strong | First-class type, repo links, due claims. No status/lifecycle board (G13) |
| Code repositories | ✅ Strong | `repos:` frontmatter + live git oracle + graph nodes + MCP tool (shipped 2026-07-13). No activity history over time (by design — live, never cached) |
| People | ✅ Strong | Extraction, dedup, sweep. Predicates are career-skewed: no `friend-of`, `family-of`, `likes` seeds → Track A3 |
| Skills/procedural | ✅ Strong | Stage-4 pattern detection. Interaction-scoped only, not hobbies/abilities |
| Calendar | 🟡 Partial | ICS connector shipped (2026-07-13), events → episodes. No event semantics, no "my week" view → Track B5 |
| Ideas | 🟡 Thin | Implicit `concept` entities only. G13 backlog-as-memory unbuilt → Track B6 |
| Preferences/taste | 🟡 Thin | Procedural prefs only; no `likes`/`enjoys` predicate seeds, mood-boards postponed (G14) |
| Places/travel | 🟡 Thin | `location` type + single-pin map hero. No all-locations map, no visited/want-to-visit semantics, travel absent from backlog → Tracks B3 + C1 |
| Music | ❌ None | Nothing. → Track B1 (**newly added to the to-do per owner request**) |
| Possessions | ❌ None | Nothing, not even a backlog line → Track B2 |
| Wishlist | ❌ None | Same → Track B2 |
| Fitness/health | ❌ None | Same → Track B4 |

**Cross-cutting pillars:**
- **Audit** — strongest pillar: git-blame history with author chips, `/contributors`, `/origins`, belief timeline. Done.
- **Explore** — good (graph, topics, vector+substring search) but the promised *cluster detection* is visual-layout-only, not algorithmic → Track C2.
- **Visualize** — strong per-entity heroes (YouTube, OG cards, lightbox, map pin) but **zero aggregate views**: no all-locations map, no timeline, no gallery, no dashboard → Track C1.
- **Portability** — structurally sound (memory/ is its own git repo; vector index is disposable/rebuildable; device-scoped refs degrade gracefully). Missing: a bank **export/import bundle** → Track D1.
- **Shipping** — plug-and-play for a technical user (`install.sh` + launchd + doctor + in-app MCP onboarding). **No .dmg / signed app — the single biggest gap between Cicada and a stranger running it** → Track D2.

---

## Track A — Memory quality (the brain)

The passport is only as good as what's written in it. Entity pages are median ~50 words; the fix machinery is now fully unblocked (corruption guard + ambiguous-subject guard shipped 2026-07-13).

| # | Item | Size | Notes |
|---|---|---|---|
| A1 | **Reconsolidation pilot #2** — 20–30 episodes in a scratch copy, deliberately including known corrections, to exercise the trust-gate COEXIST/CONFLICT paths pilot #1 never triggered | S (op) | Both pilot #1 blockers fixed. Copy + flag-flip + librarian loop, Sonnet 5 |
| A2 | **Full active-bank re-consolidation** — all **208** episodes of `claude-chats` (not 117 — that's the legacy root bank), agentic path, merge back after diff review | M (op, ~$10–20) | Supersedes G10. Decide agentic vs batch (`CICADA_CONSOLIDATION_MODEL=anthropic/claude-sonnet-5`) per pilot #2 results |
| A3 | **Personal predicate seeds** — `likes`, `enjoys`, `owns`, `wants`, `visited`, `wants-to-visit`, `friend-of`, `family-of`, `listens-to`, `practices` added to `predicates-seed.yaml` with canonical normalization | S | Unlocks B2/B3 typing without new entity types; currently these fall to the unaudited slugify long tail |
| A4 | **`claude-chats-v2`: execute or delete** — the bank is byte-identical to active with stale metadata and zero git commits; either actually run the Phase 2/3 runners against it + eval, or delete it to end the confusion | S–M | Bank-eval verdict 2026-07-13: HOLD |
| A5 | **Retire the legacy dual pipeline** (G19a) — `conflict_resolver.resolve_and_prune` still runs alongside the claim pipeline every cycle | M | ⚠️ First verify audit finding M2 (claim-decay archive tier reportedly dead at `claim_reconciler.py:424`) — the legacy path currently masks it |
| A6 | Reduce Rodrigo-node centrality via bridge/topic hubs (G7) | M | Graph readability; pairs with C2 |

## Track B — Domain coverage (the passport pages)

All connectors follow the shipped pattern: **keyless/local-first, episodes at capture, no LLM, dedup index, origin tag, Sleep consolidates.** Feasibility research 2026-07-13.

| # | Item | Size | Approach |
|---|---|---|---|
| B1 | **Music — Apple Music** *(new)* (G31) | **S** | AppleScript batch enumeration of Music.app (play counts, played date, loved, persistent ID) — a near-copy of `notes_sync.py`, same TCC consent model. `music_index.json` dedup, `origin: apple-music` |
| B1b | **Music — Spotify** *(new)* (G32) | M | Extended Streaming History export zip → import queue (keyless; export takes up to ~30 days to arrive, so ship Apple Music first). Aggregation policy (per-track vs per-session episodes) is the main design decision |
| B2 | **Possessions / wishlist / likes** (G34) | **S** | Not telemetry — first-person claims. Telegram verbs (`/own`, `/want`, `/like`) + the existing `cicada_write_claim` path (trust-gated, ambiguity-guarded) + A3 predicates. No new entity type needed initially |
| B3 | **Places & travel semantics** (G33, G35) | M | `visited` / `wants-to-visit` claims on `location` entities (A3); optional Google Takeout import (Saved Places + Semantic Location History) — schema-drift risk, keep parser defensive |
| B4 | **Fitness — Apple Health** (G36) | L | `export.zip` → import queue, `iterparse` (files reach GBs), daily-rollup episodes (not per-sample). Inherently manual sync loop (iPhone export + AirDrop); no macOS API exists. Do last or on explicit demand. Extend later with clinical Health Records (G45) — same `export.zip`, opt-in |
| B5 | **Calendar deepening** | M | Decide event semantics: recurring events → claims on people/projects (`meets-weekly-with`), plus a "my week" agenda surface in the app (pairs with C1 timeline) |
| B6 | **Ideas & tasks as memory** (G13) | M–L | Claims with `idea`/`todo`/`open-question` predicates + inbox surfacing ("you had an open idea about X"). Consider a `cicada_note` MCP quick-capture verb |
| B7 | **Reading & life-log connectors** *(new, research 2026-07-13)* (G39–G43, G46) | S | Apple Books highlights (local SQLite, no export step), Kindle clippings (`My Clippings.txt`), Photos metadata via `osxphotos` (people/places/dates, never pixels), Journaling (`/journal` `/dream` Telegram verbs), Voice Memos (local Whisper transcribe), Contacts.app (birthday/employer corroboration). Same shipped keyless-local-connector pattern; best ROI found in the domain research pass |
| B8 | **Education, courses & certificates** *(new, research 2026-07-13)* (G44) | M | LinkedIn export (`Certifications.csv`/`Education.csv`) + per-course certificate PDFs dropped into a watch-folder; no unified keyless API across providers, stays multi-source and periodic |

## Track C — The reading experience (explore · visualize · audit)

| # | Item | Size | Notes |
|---|---|---|---|
| C1 | **Aggregate views** — the passport's chapters: all-locations **map** (extend the shipped MapKit hero), **timeline** (episodes/claims over time; reuse BeliefTimelineView patterns), **media gallery** (G14-lite), **"my week"** agenda | M–L | The single highest-leverage app work for the vision; per-entity heroes are done, aggregates don't exist |
| C2 | **Real cluster detection** — algorithmic communities (Louvain over the edge graph, or tag-cluster reuse), colored in the d3 view + a Clusters navigation that reflects them | M | CLAUDE.md has promised this since the MVP list; current clustering is visual layout only |
| C3 | **Passport dashboard** — a "who am I" overview page: per-domain coverage tiles, freshest facts, decaying areas, origin mix | M | Becomes the app's landing surface; doubles as the thesis demo screen |
| C4 | Mood-boards / aesthetics entities (G14, owner-postponed) | L | Unblocks after C1 gallery |

## Track D — The passport itself (portability & shipping)

| # | Item | Size | Notes |
|---|---|---|---|
| D1 | **Bank export/import bundle** — `GET /banks/{name}/export` producing a zip (memory git repo + manifest + schema version), and the import counterpart | M | The "transferable" clause of the vision; today only chat-export *import* exists |
| D2 | **.dmg packaging** — embedded Python runtime (or PyInstaller-style backend binary), signed + notarized app, drag-to-Applications | L | **The launch blocker** for anyone-but-you. Current: `git clone` + `install.sh` + Swift toolchain. Everything else on this roadmap is usable by you without it |
| D3 | Share Extension (marked "Coming soon" in SyncSetupView) (G37) | M | Share-sheet capture from any Mac app — any app with a share button exports straight to Cicada. iOS companion app (share sheet on iPhone) is the natural later extension of the same idea, not scoped now |
| D4 | Docs truth pass — CLAUDE.md done 2026-07-13; keep `memory-evolution.md` statuses live as tracks ship | S | Recurring |

## Decisions that gate work (answer once, unblock much)

1. **G2 taxonomy**: recommend **claims-first** — model music/possessions/wishlist/travel as predicates on existing types (A3) and only add entity types (`track`? `item`?) when an aggregate view (C1) demonstrably needs them. Avoids reopening the promotion-threshold design per domain.
2. **D2 (architecture fork) / D4 (peers & multi-bank)**: still research-only; nothing above hard-depends on them except G8.
3. **Calendar event semantics** (B5): episodes-only (today) vs claims-on-entities for recurring events.

## Suggested sequencing (solo, thesis-compatible)

1. **Week 1 — quality + quick wins:** A1 pilot #2 → A3 predicate seeds → B2 possessions/wishlist verbs → B1 Apple Music. *(Mostly S items; immediate passport breadth.)*
2. **Week 2 — the pass + the views:** A2 full reconsolidation (gated on A1) → C1 aggregate map + timeline → B5 calendar semantics.
3. **Week 3 — depth:** B1b Spotify + B3 places imports → C2 clusters → C3 dashboard → A4/A5 cleanup.
4. **When shipping to others matters:** D1 export → D2 .dmg → D3 share extension.

---

*Verification provenance: coverage map and pillar assessments from a read-only two-agent code audit (Sonnet 5) against `dev` @ `ca345c9`; connector approaches from a feasibility pass grounded in the shipped connector patterns (`bookmark_sync.py`, `feed_registry.py`, `calendar_registry.py`, `notes_sync.py`, `telegram_capture.py`). Estimates are relative to the calendar connector (~1–2 sessions = S).*
