# Study room sprites — finishing handoff (G176, 2026-10-02)

Final integration is complete on `feat/study-room-sprites`, in `.worktrees/study-room-sprites`.
The orchestrator handles commits and the PR to `dev`; owner acceptance and merge remain pending.
This handoff supersedes its earlier five-failure/day-art-only snapshot. The binding contract is
[`2026-10-02-study-room-scenery.md`](2026-10-02-study-room-scenery.md), with the original spec's §7,
dated owner decisions and TODO ruling 18 still applying.

## Where it stands

- **Art:** 36 sheet pairs, 429 tags, 4,426 frames. The owner's eight-state worm and one menu sheet;
  16 relit night worm sheets; room/props; five weather bases × day/dusk/night; mist, rainbow and
  shooting star overlays; the wall clock. Saved parts and headless scripts are authoritative.
- **Owner 2026-10-01:** error shows black X eyes and the drop, with no red pupils. The menu worm
  keeps its dark outlines on both bars; there is no alternate dark-bar sheet.
- **Owner 2026-10-02:** scenery follows real time and the selected weather source independently
  of the worm. Night and rain darken the room; the lamp supplies a local warm pool; the real wall
  clock follows local time. Settings offers Local weather, How Sleep is doing and Choose, with
  time/weather thumbnails and the public-city weather disclosure.
- **Owner 2026-10-02, mascot:** Settings → Sleep → Mascot names the sole entry Bookworm. A pure registry and
  per-viewer preference route all shared room/menu/empty/intake sprite reads; unknown ids fall back to Bookworm.
  The selected tile shows room/menu key frames, a checkmark, keyboard focus and selected VoiceOver text. A later
  character supplies its own base/prefix/sheets, manifest entries and one registry entry.
- **App:** per-frame sprite player, room/worm/menu wiring, scenery model, weather reader and clock.
  Reduce Motion holds key frames and hides seconds; Low Power doubles sprite holds; hidden rooms
  and Settings pause sprites, clock and weather reads. The state machine and response matrix stay.

## Cause fixes and verification

The acceptance palette now reads every declared colour section exactly like the art verifier;
81 authoring keys alone consume the 87-key budget, with 699 allowed RGBs overall. Binary alpha,
reserved hues, provenance and shape checks remain enforced, with one useful defect per sheet.
The clock's app placement matches the art plan at **(94,34)**. Rain holds **100 ms** instead of
80 ms across all three times, with every frame/pixel/wrap unchanged: the measured worst room
falls from **1,908 to 1,758 boundaries/minute**, including the clock, under the unchanged **1,800 cap**.
Settings' existing pause now reaches the sprite leaves as well as the reader and clock.

The five-lens review fixes keep mood/overlay/day-lamp changes outside the worm's lighting-only fade identity;
align the clock to whole seconds (minutes under Reduce Motion); suppress viewer-language headers and disclose the
network address; handle backwards time and visible stale-while-revalidate weather. Tests now cover every night
state mark, plan-mapped fly occlusion and distinct source render heights. Partial/worm exports rebuild saved-parts
predecessors, all night art, manifest and full acceptance; static family provenance removes the Codex CLI dependency.

Two stable-resource full Swift suites after all review fixes pass **2,785 tests each, zero failures**; no polling flake.
The CLAUDE.md size/link checks pass **2 tests**. Two full headless exports pass all verifiers and
match **120 files byte for byte**; the actual documented worm-stage and partial skyfx exports match them too.
Both independent night/fx builders pass two-run 38-file comparisons; six pipeline regressions pass.
The offline preview smoke check passes 36 sheets / 429 tags /
480 room combinations. `make app` builds only the worktree bundle, containing **36 PNG/JSON pairs
plus the manifest (73 files)** with matching hashes. `git diff --check` is clean.

The integration writer renders **552 room composites** and **ten Settings panes** (six scenery and four Mascot,
including valid/unknown choices in both appearances). All were
inspected through labelled boards or individual PNGs. Literal hotspot/gaze pins, every inspected
path, observations, logs and snapshot limitations are recorded in
[`INTEGRATION_REPORT.md`](../../app/CicadaApp/Art/sprites/bookworm-2026-10-01/INTEGRATION_REPORT.md).
The offline motion review entry remains
[`preview.html`](../../app/CicadaApp/Art/sprites/bookworm-2026-10-01/preview.html).

## Open work and owner review

**Q1 first in the PR:** running Sleep still sleeps while queued/paused work reads; the owner's
09-29 brief requested reading while consolidating. No art fixes that state-machine decision.
Count-driven props (computer, phone, globe, TV, letter tray, calendar), the queue as a room
(cart/crate/bookcase), G175 pixel marks and a second G127 character's own base remain separate design rounds.
Time-of-day scenery, dark-room/lamp lighting and the clock are built.

B12's narrower menu lens remains held for the owner. The sleeping-outro's standing closed book
can become the reading key frame's open book in one frame; the sheets have no named opening beat.
The integration report records this limitation rather than inventing a transition.

Before merge, the owner reviews motion in `preview.html` and the Sleep page, then the demo-bank
room in light/dark at 0.8×–1.4×. Live idle CPU still needs measurement: ≤ 3% of one core and within
2 percentage points of `dev`. Static ImageRenderer panes use a source-menu text twin because
native menu views are unsupported; they do not establish menu interaction or live playback.

## Rails and next step for the orchestrator

Work only in this worktree. Do not edit, switch or stash in the main checkout or other worktrees.
No Aseprite GUI or computer use during integration: art fixes go into saved parts/scripts and
`tools/export_all.sh` is rebuilt twice byte-identical. No `make dev`, `install_app.sh`, app launch,
bank access, commit, push, stash, branch or reset by the integration worker. Privacy and
provider-neutral copy apply.

Review correctness/regressions, assertion integrity, accessibility, docs and privacy against the
report and diff. The orchestrator then commits and opens the PR to `dev` with Q1 first, the
2026-10-01 and 2026-10-02 owner decisions, DR-13, DR-50, DR-61, DR-65, DR-66 and ruling 18.
Do not merge before the owner review and live measurement above.
