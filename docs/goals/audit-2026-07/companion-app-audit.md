# Cicada Companion App — Final Health Report

Date: 2026-07-02 · Branch: `feat/memory-evolution` · Sources: API robustness sweep, app build/runtime run, UX code review of `app/CicadaApp/Sources/CicadaApp`

---

## 1. Verdict: Is the companion app working?

**Mechanically yes, functionally no — and the gap is invisible by design flaw.** The app builds (after a cache clean), launches, and all six sidebar views navigate without crashes; the FastAPI backend survived the full adversarial sweep with zero 500s, no path traversal, and graceful degradation everywhere. But the end-to-end product is currently a beautiful shell over nothing: a stale `CICADA_MEMORY_PATH` in `api/.env` (still pointing at the pre-move `roros_lab/thesis/cicada` location) means the backend serves an empty, uncommitted memory bank instead of the real 1036-entity `claude-chats` bank, so every screen renders empty. Worse, the primary Graph screen has no loading, error, *or* empty state — its ViewModel sets `errorMessage`/`isLoading` that no view ever reads — so this misconfiguration (or any backend failure) presents as a silent black void. One config fix likely restores the data path, but the pervasive silent-failure pattern (print-only error handling, `try?` swallowing, unisolated `@Observable` writes) is the real ship risk and must be addressed before end users touch this.

---

## 2. Build + runtime result

**Build:** First `./bundle.sh` run **failed** with stale-module-cache PCH errors across ~20 compile units (`PCH was compiled with module cache path '/Users/rorosaga/Documents/roros_lab/thesis/cicada/...'` + `missing required module 'SwiftShims'`) — the `.build` directory embeds absolute paths from before the repo move. `rm -rf .build && ./bundle.sh` then succeeded in 9.22s, producing `/Users/rorosaga/Documents/roros_lab/cicada/app/CicadaApp/.build/arm64-apple-macosx/debug/Cicada.app`.

**Runtime:** App launched (after a macOS TCC prompt for Documents access blocked the first window — see `app_main.png`). All six views navigated via synthesized clicks (AX activation doesn't work, see issue 13). No crashes, no error banners. App quit cleanly; backend PID 65016 left running.

**What the screenshots showed** (all under `/private/tmp/claude-501/-Users-rorosaga-Documents-roros-lab-cicada/cfed79b7-57b4-4204-9e32-ad7b24660e07/scratchpad/`):

| Screenshot | Finding |
|---|---|
| `app_main.png` | First launch blocked by Documents-folder permission dialog |
| `app_graph.png` | Graph = pure black void (0 nodes, no empty-state UI); zoom/legend controls visible on first load only |
| `app_graph_final.png`, `app_graph_revisit.png` | Zoom −/+/fullscreen and legend controls **permanently gone** after navigating away and back (reproduced twice) |
| `app_clusters.png` | Contradictory "11/11" filter pill above "0 clusters" |
| `app_feed.png`, `app_inbox.png` | Designed empty states present but bottom-heavy (~65–70% down the window) |
| `app_sleep.png` | "No episodes queued" empty state renders fine |
| `app_contributors.png` | Renders, empty (wrong memory bank) |

---

## 3. API health table

Raw responses saved in `/tmp/` (`status.json`, `graph.json`, `inbox.json`, `contributors.json`, `sources.json`, `banks.json`, `sleephist.json`, `healthz.json`, `ask.json`, `e1–e4.json`, `a1–a2.json`, `i1.json`).

| Endpoint | Result | Notes |
|---|---|---|
| `GET /healthz` | 200 | But exposes the root cause: `memoryPath: .../thesis/cicada/memory`, `entityCount: 0`, `leannPresent: false` |
| `GET /graph` | 200, ~1ms | 0 nodes / 0 edges — empty bank, not a bug per se |
| `GET /banks` | 200 | Single synthetic "default" bank, entityCount 0, created 2026-07-03 |
| `GET /contributors` | 200 | `[]` |
| `GET /sources` | 200 | `{"items":[],"total":0}` |
| `GET /sleep/history` | 200 | `[]` |
| `POST /ask` | 200 | Graceful low-confidence "nothing in memory" answer on empty results; `top_k` bounds validated correctly |
| `GET /entities/{id}/history` | 404 clean | `{"detail":"Entity <id> not found"}` — **happy path untestable** (no entity exists in served bank) |
| `GET /entities/{id}/history/{commit}/diff` | 404 clean | Same — only the 404 branch exercised |
| Adversarial (path traversal, flag injection, `/tmp/pwn` attempt, malformed input) | All clean 4xx | **Zero 500s, no artifacts created, no injection succeeded** |

Backend robustness: **solid.** Backend configuration: **broken** (issue 1).

---

## 4. Ranked issue list

### Launch-blocking

**1. [BLOCKER] Stale `CICADA_MEMORY_PATH` — backend serves an empty memory bank end-to-end**
Merged finding from all three reviews. `api/.env` (last modified 2026-06-18) still points at `/Users/rorosaga/Documents/roros_lab/thesis/cicada/memory` (pre-move path, empty, no git commits); the running uvicorn never loaded it and fell back to `~/cicada/memory` (also 0 entities). The real bank — `claude-chats`, 1036 entity files, full git history — sits at `/Users/rorosaga/Documents/roros_lab/cicada/memory` per `banks.yaml`. Every view is empty; `/ask` retrieval, entity history/diff, contributors, and sources were never meaningfully happy-path tested.
**Fix:** Update `api/.env` to `CICADA_MEMORY_PATH=/Users/rorosaga/Documents/roros_lab/cicada/memory`, restart the backend, then **re-run the entity history/diff and `/ask` happy-path tests** (this closes the API sweep's "untested" gap). Also: log the resolved memory root at startup and surface it in the app so a misresolved root is ever visible again.

**2. [BLOCKER] Graph screen has no error, loading, or empty state — blank black void for every failure mode**
`GraphViewModel.swift:25-26` declares `isLoading`/`errorMessage` and `loadGraph()` sets them, but `ContentView.swift`'s `GraphContainerView` (lines 50–137) and `TopicsView.swift` never read them. Backend down, 500, decode error, JS crash, or genuinely-zero-entities all render identically: pure black (`app_graph.png`). Every other view has a designed empty state; the landing screen has none. A new install looks broken on arrival.
**Fix:** Add a three-state overlay to `GraphContainerView` — spinner (`isLoading`), error banner + retry (`errorMessage`), and "No entities yet — run a Sleep cycle or upload a conversation" (loaded, 0 nodes) — reusing the pattern already correct in `FeedView.swift:110-119`.

**3. [BLOCKER-adjacent, HIGH] `GraphViewModel` and `InboxViewModel` are not `@MainActor` — unisolated `@Observable` writes on the primary data paths**
`GraphViewModel.swift:9` and `InboxViewModel.swift:8` lack `@MainActor` (unlike Banks/Contributors/Sleep VMs). `loadGraph()` (136–178) mutates nodes/edges/errorMessage after crossing the `APIClient` actor boundary with no isolation. The file's own comment at lines 123–126 documents this exact bug class ("detail card was stuck showing the placeholder") and half-fixed it for `loadFullEntity` only. This is a stuck-UI bug waiting to fire on the app-launch path.
**Fix:** Mark both classes `@MainActor`, matching the other three ViewModels.

**4. [HIGH] Graph controls (zoom, fullscreen, legend) vanish permanently after tab switch**
Reproduced twice (`app_graph_final.png`, `app_graph_revisit.png`). `ContentView.swift:46` switches views via `switch selectedTab`, tearing down and recreating the graph subtree; the recreated WKWebView never restores the in-HTML controls. With 0 nodes it's unverified whether node rendering also fails on revisit — likely worse with data.
**Fix:** Retain the WKWebView across tab switches (ZStack visibility / VM-held view), or ensure recreation reloads `index.html` and re-pushes graph data.

**5. [HIGH] JS errors from the graph webview are print()'d and discarded**
`GraphView.swift:130-132`: the `jsError` bridge case only prints. `graph.js:109-122` built its `window.onerror` handler specifically to catch "inexplicably blank canvas" cases; the Swift side throws the signal away. Any d3 exception is invisible.
**Fix:** Route `jsError` into `graphVM.errorMessage` (feeds the overlay from issue 2).

**6. [HIGH] Entity detail card freezes on placeholder if the fetch fails**
`GraphViewModel.swift:180-193` catches with `print()` only. Clicking a node during any network/decode failure leaves a permanently empty card indistinguishable from an entity with no content.
**Fix:** Set an error flag on failure and render it in `EntityDetailCard`.

### Should fix before launch (medium)

**7. [MEDIUM] Backend death is invisible app-wide** — `StatusService.swift:13-15` `try?`-swallows status fetches and `CicadaApp.swift:87-99`'s 30s loop no-ops on nil; `SleepViewModel.swift:136-140` retries poll errors forever at 1s with no cap and never sets `errorMessage`. If uvicorn crashes mid-session, nothing anywhere in the app says so. **Fix:** consecutive-failure threshold driving a visible "backend disconnected" state in the menu bar; retry cap in the sleep poll so `SleepView.swift:43-45`'s banner can fire.

**8. [MEDIUM] Claims/timeline fetch failures render as "genuinely empty"** — `EntityDetailCard.swift:754-758` and `BeliefTimelineView.swift:85-91` `try?`-swallow all errors, then show "No claims/timeline yet." **Fix:** separate `loadError` state from loaded-and-empty.

**9. [MEDIUM] Data race in multi-file drop** — `UploadOverlay.swift:307-320` appends to a shared local `[URL]` from concurrent `loadObject` completions (arbitrary queues). Dropping several files can crash. **Fix:** serialize appends (serial queue / lock / actor) before the `.notify` read.

**10. [MEDIUM] `bundle.sh` breaks after a repo move (stale `.build` absolute paths)** — dev hygiene, not end-user facing, but will bite release builds. **Fix:** stamp the checkout path in `.build` and auto-`swift package clean` on mismatch.

### Polish (low)

**11. [LOW] First-launch Documents TCC prompt blocks the window** (`app_main.png`) — expected for a debug build, but the .dmg onboarding should default the memory root to `~/cicada/memory` (as documented) and/or explain the permission.
**12. [LOW] Sidebar rows are static text, not accessible controls** — AX activation is a no-op; VoiceOver and UI automation cannot navigate. Fix: Buttons with `.isButton` trait or List selection.
**13. [LOW] Clusters header shows contradictory "11/11" pill above "0 clusters"** (`app_clusters.png`) — label the pill ("Types: 11/11") or hide filters when empty.
**14. [LOW] Feed/Inbox empty states sit at ~65–70% window height, not centered** (`app_feed.png`, `app_inbox.png`) — `frame(maxHeight: .infinity)` centering.
**15. [LOW] Missing bundled `graph/index.html` fails silently** — `GraphView.swift:28-31` has no `else`; a packaging regression yields a blank webview with no diagnostic. Fold into issue 2's error surface.
**16. [LOW] `SleepTriggerResponse`/`EpisodeQueueItem`/`ScheduleConfig` are strict Codable** (`APIClient.swift:238-257`) while every sibling model has tolerant custom decoders — future backend rename hard-fails. Align or document.
**17. [LOW] CLAUDE.md documents a stale app source path** — actual code lives at `app/CicadaApp/Sources/CicadaApp`, not `app/CicadaApp/CicadaApp`. Update the doc.

---

## 5. Top-5 pre-launch fixes

1. **Fix `CICADA_MEMORY_PATH` in `api/.env` and restart the backend** — one-line config change that un-breaks the entire product; then re-run the entity history/diff and `/ask` happy-path tests that were blocked, and add startup logging of the resolved memory root. (Issue 1)
2. **Give the Graph screen loading/error/empty states** — wire `graphVM.isLoading`/`errorMessage` plus the `jsError` bridge into a visible overlay, and add a "No entities yet" empty state. Kills issues 2, 5, and 15 with one overlay. (Issues 2, 5, 15)
3. **Mark `GraphViewModel` and `InboxViewModel` `@MainActor`** — two-line change eliminating a documented, already-bitten class of stuck-UI concurrency bugs on the two most-used screens. (Issue 3)
4. **Fix graph controls disappearing on tab revisit** — keep the WKWebView alive across tab switches or fully re-initialize on recreation; the primary screen degrades permanently after one navigation otherwise. (Issue 4)
5. **Add an app-wide "backend disconnected" signal** — failure threshold on the 30s status poll driving a menu-bar/banner state, plus a retry cap on the Sleep poll loop. Without it, every other fix still fails silently when uvicorn dies. (Issue 7)

Items 1–3 are hard launch gates; 4–5 are strongly recommended before end users see the app. Everything in the polish tier can ship in a fast-follow.