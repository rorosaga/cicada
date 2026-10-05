# G176 follow-ups — handoff prompt (2026-10-02)

The fixes left open when the new bookworm and study room shipped (PRs #164 and #165, merged to `dev` and installed on
2026-10-02). Paste the fenced block into a fresh Claude Code session started at the repository root (the main checkout).
Everything it needs is in the repo; nothing depends on an earlier session's scratch files.

````text
Read, in this order: CLAUDE.md, docs/goals/working-method.md, the head of docs/goals/TODO.md ("Where things stand",
ruling 18 and its 2026-10-01 / 2026-10-02 amendments), the G176 row in docs/goals/memory-evolution.md, and
docs/architecture/app.md's Sleep page, mascot and "The sprite art and its preview" paragraphs. The sprite work itself is
documented in app/CicadaApp/Art/sprites/MAKING_A_MASCOT.md (§6 animation catalog, §7 lighting, §8 scenery, §10 driving
Codex, §11 quality bars).

Context: the owner's new bookworm and study room shipped on 2026-10-02 (PRs #164, #165): Aseprite sprite sheets played by
a native player (app/CicadaApp/Sources/CicadaApp/Sprites/*), the room on a 160 × 64 lattice (Views/Sleep/DeskScene.swift,
StudyRoom.swift, RoomClock.swift), the scenery model (Theme/Scenery.swift, LocalWeatherReader.swift), Settings → Sleep →
The scenery and → Mascot. Four things are open. Work them in this order, one PR to `dev` each, using the working method
(plan → critic → implement test-first → per-task review → two-lens final review → verify yourself → PR). Implementation
may be handed to Codex (gpt-6.1-sol, reasoning xhigh) as MAKING_A_MASCOT.md §10 describes, or to workflow agents; you
review, verify and commit. Rails: work in your own worktree under .worktrees/ (never edit, switch or stash in the main
checkout — an auto-updater builds from it); never `make dev` or `install_app.sh` without the owner's word (they replace
his installed app); never point a running Cicada at a bank without his word; never read memory/, ~/.cicada or
~/.claude/projects; privacy rule on every word; PRs to `dev`, merged only when the owner says so.

1. THE SLEEP PAGE'S CPU (primary). — DONE 2026-10-05 on `perf/sleep-page-cpu`: 12.0% → 2.54% (TODO ruling 18's player
   amendment). Skip to item 2; the hidden graph's web view is the audit's A07, not this item.
   Measured 2026-10-02 on the installed release build of origin/dev 0d745538, with the Sleep page visible (a dark,
   rainy room, lamp off): 11.9% of one core on average over 12 samples of 5 s (`top -l 13 -s 5 -pid <pid> -stats
   pid,cpu`), peak 14.4%. Ruling 18 and the 2026-10-01 spec (R-BW11) set the bar: at most 3% of one core, and within 2
   points of the previous build, whose room was static. The frame-boundary budget already holds (the worst scenery —
   rainy night + digesting + lamp lit — is 1,758 boundaries a minute against a 1,800 cap), so the cost is per boundary,
   not the boundary count.
   a. Reproduce and attribute before changing anything. Measure with the Sleep page visible, with another page visible
      and with the window hidden (menu-bar worm only), on a RELEASE build. Profile with `sample <pid> 10` and/or
      Instruments (Time Profiler, SwiftUI) while the Sleep page is on screen; force the worst scenery from Settings →
      Sleep → The scenery → Choose (Night, Rainy) with the lamp lit. Measuring needs the app on screen: ask the owner
      first, then either run the worktree's bundle (`make app`; read the Makefile target, it must build in the worktree
      and install nothing) after quitting his installed app, or let him run it; relaunch his app afterwards.
   b. Suspects to confirm or rule out with numbers: each sprite layer's `TimelineView` re-evaluating SwiftUI bodies of
      the whole room at every boundary; frame crops or `CGImage` work redone per tick instead of cached; nine-plus
      full-size layers redrawn at 3 pt per cell when only one or two moved; `WindowVisibilityReader`; the menu bar's
      chained timer (`MenuBarManager.tick`, MenuBarManager.swift:225) re-rendering its image every frame; a hidden
      WKWebView (the graph) kept alive; the 1 Hz clock leaf.
   c. Fix at the cause while keeping every rule: per-frame timings come from the sheets; Reduce Motion shows key
      frames (no second hand); Low Power doubles holds; nothing ticks while hidden or while Settings is open; no
      interpolated transforms (whole-pixel only); every text twin and VoiceOver label unchanged. Likely shapes: draw the
      static layers once into one cached image per (lighting, lamp, weather key) and animate only the layers that move;
      one scheduler for the room instead of one per layer; cached frame images keyed by (sheet, rect); a layer-backed
      view that swaps `contents` instead of re-rendering SwiftUI. Choose by measurement.
   d. Acceptance: in that worst scenery, ≤ 3% of one core averaged over 60 s on a release build with the Sleep page on
      screen; ≤ 0.5% with the window hidden; the same visible frames as before (the composite tests and preview.html
      unchanged); a regression test that pins the cheap path (e.g. a count of body evaluations or image renders per
      minute for a fixed scenery). Put every number, before and after, in the PR body, and record it in TODO ruling 18.

2. THE BACKEND TEST THAT FAILS ON `dev`.
   `api/tests/test_cycle_usage.py::test_history_and_detail_join_usage_from_the_ledger` fails on a clean `dev` (it failed
   identically before PR #164, which touched no backend code): `rows[0].usage_summary` is `None` at
   test_cycle_usage.py:384, so the sleep history row is not joined with its usage from the telemetry ledger. The test
   writes ledger events stamped `2026-09-29T10:00:00.000Z`. First lead to verify, not a conclusion: a fixed fixture date
   that has fallen outside a time window the join or the ledger read applies (working-method.md §1 records the same
   failure shape for the calendar tests, fixed by building dates relative to today). Find the cause in
   `api/services/git_service.py` (`get_sleep_history`, `get_sleep_cycle_detail`), `api/services/cycle_usage.py` and
   `api/services/telemetry.py`; fix the code if the join is wrong, or the fixture if it is on a timer — never weaken the
   assertion. The backend baseline is 0 failures: `api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`.

3. THE AUTO-UPDATER IS BLOCKED (the owner's call; do not touch his files).
   scripts/dev/auto-update.sh only fast-forwards the main checkout when it has no tracked changes. The main checkout has
   an uncommitted change to `api/config.py` (a few lines), so logs/auto-update.log has said "skip: tracked changes on
   dev" every five minutes since at least 2026-10-02 and his app no longer updates itself (#164/#165 were installed by
   hand). Show him `git -C <main checkout> diff api/config.py` and ask: commit it through a branch and PR, stash it
   under a named tag, or discard it. Do nothing to that file without his answer. Then offer (build only if he wants it)
   a visible signal when the updater skips — e.g. a line in Settings → General or a one-time notification — since the
   skip went unnoticed.

4. Q1 — THE OWNER DECIDES, THEN BUILD.
   While a Sleep cycle runs, the worm plays its sleeping state (z → zz → zzz on the bean bag), as the state machine has
   always said; the owner's 2026-09-29 words were "be reading books when consolidating". Ask him once, with both
   options: keep sleeping while a cycle runs, or read (page flips, eyes tracking lines, the three-cover swap) while a
   cycle runs and sleep only when nothing runs. If he chooses reading, it is a mapping change, not new art: the state
   → sheet resolution (Sprites/BookwormArt.swift, Sprites/MascotRegistry.swift), the mood derivation and its tests, the
   window overlay rule (the mist marks a running cycle — keep it), the worm's text twins and sentence, and the docs
   (TODO ruling 18 amendment dated with his answer, the G176 row, app.md). Also do the remaining live look the TODO
   names: the Sleep page in light and dark at 0.8×–1.4× zoom (the demo bank procedure only with his word).

Finish each item with: what changed and why (with numbers), the tests, both suites green (`cd app/CicadaApp && swift
test`; the backend command above), the PR link, and what you need from the owner. Update TODO.md's "Where things stand"
and the G176 row as each lands.
````
