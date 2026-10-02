# Study room sprites — finishing handoff (G176, 2026-10-02)

The prompt a fresh session runs to take the new bookworm and study room from "drawn and wired on a branch" to "a PR the
owner can review". Paste the fenced prompt at the end. Everything it needs is in this file and the branch; nothing
depends on an earlier session's scratch files.

## Where it stands

**Branch `feat/study-room-sprites`, worktree `.worktrees/study-room-sprites`** (under the main checkout). Not pushed, no
PR yet. It merges three lines of work, all done by Codex (gpt-6.1-sol, extra-high effort) in Aseprite, under computer use
for review and hand edits and headless Lua for every reproducible pixel:

- **The worm** (Run A, then a worm fix pass after a five-lens art review): the owner's own design
  (`app/CicadaApp/Art/sprites/bookworm-2026-10-01/reference/bookworm.png`) at 64 × 48 in every `BookwormState`, with
  breathing, irregular blinks, eyes tracking lines, a real page flip and a three-cover book swap, z → zz → zzz sleep, the
  yawn and stretch transitions, and every beat; the owner's menu-bar head (`reference/bookworm_menu_bar.png`) at 18 × 18
  in eight states. Nine worm sheets, 130 tags, 1,095 frames.
- **The room** (Run B): wall and floor, the window with seven animated weathers behind the glass (night, dawn, sunny,
  partly cloudy, windy, rainy with no flash, curtains), the lamp dark and lit with a pixel-sized fly that flies only while
  it is lit, the bean bag, plant and mug, five spine textures for the real pile, `room-plan.json`, `room-motion.json`.
  Nine room sheets.
- **The app** (Run C part 1 and its review fixes): an Aseprite json-array decoder, clips with per-frame durations,
  `SpriteLayerView` on a `TimelineView` that rests when unseen, key frames under Reduce Motion and half speed under Low
  Power; the worm behind the unchanged state machine and response matrix; the room on a 160 × 64 lattice; the menu bar on
  chained per-frame timers; spine textures; TODO ruling 18 and the doc edits.

**The owner's decisions (2026-10-01), already in the art:** the error state shows **black X eyes** (no red pupils), and
the menu bar keeps **its dark outlines on a dark bar** (no dark-bar variant: 18 sheet pairs).

**Verified by the orchestrator (2026-10-02):** `tools/export_all.sh` run twice from the saved sources reproduces every
bundled sheet byte for byte (58 files identical across the two runs, and identical to the committed PNG/JSON), and
`verify.py` passes. The offline preview, `app/CicadaApp/Art/sprites/bookworm-2026-10-01/preview.html`, renders in a
browser from `file://`. `swift test`: **2,735 tests, 5 failures**, all follow-ons of the art landing:

| Test | Why it fails | The fix |
|---|---|---|
| `BookwormPoseSpriteTests.testEveryRoomFrameKeepsTheBookGlassesAndStateMarks` | expects palette key `e` (error red) | the error mark is now black X eyes + the sweat drop |
| `BookwormPoseSpriteTests.testSmallStateMarksAndOverlaySpace` | same | same, at 18 × 18 |
| `BookwormStateTests.testErrorFramesHaveRedPupilsAndMove` | same | rename and assert the X shapes in both lenses + the drop |
| `RoomSpriteTests.testRoomSheetsHaveExactTagsCanvasesAndSlices` (`:30`) | the error sheet carries an extra `errorLensL` slice (the X-eye fix moved the left lens's inner rim 1 px in that state only) | add the slice to the contract, or fold it away in the art, per the spec's dated §3.3 note |
| `RoomSpriteTests.testFlyIsPixelSizedOutsideTheGlassAndPileAndRestsOnTheShade` (`:60`) | frame 0 of the fly is not judged "on the shade"; Run B's own `verify_room.py` passes its fly check | decide from spec §5.4 whether the art's frame 0 or the test's transform (lamp canvas h = 50, fly canvas at (0, 32) h = 26, y-flip) is wrong and fix that side, never by weakening the assertion |

Other notes for the integration run:
- The worm fix pass changed the room lens slices to `lensL = (11,17,4,6)`, `lensR = (23,18,8,7)`; `eye` stays
  `(27,21,2,2)`. The rest pupil is solid and one row higher; right-lens gaze travel is −2/+1.
- The hand-off from the sleeping outro (a standing closed book) to the reading key frame (an open book) can pop; prefer
  playing reading's opening beat first, otherwise document it.
- One existing polling test fails under heavy machine load (two Codex sessions + exports); it passed on every quiet run.
  If it flakes, rerun it alone and name it.
- Review item B12 (a narrower menu-bar lens) is held for the owner: it would move away from his drawing.
- The docs carry interim status from three parallel runs (`docs/goals/TODO.md` head, the G176 row, the art `README.md`,
  which still describes the 19-sheet bundle and the dark variant): reconcile them to the final truth.

**Open after this PR (record, do not build):** the count-driven props (computer, phone, globe, TV, letter tray,
calendar), the queue as a room (cart, crate, bookcase), pixel brand marks (G175), time-of-day room palettes and the night
light, and Q1 (when the worm sleeps vs reads — the spec keeps today's states; the owner's 2026-09-29 words say "reading
books when consolidating").

## Rails for this step

- Work only in `.worktrees/study-room-sprites`. Never edit, switch or stash in the main checkout (an auto-updater builds
  from it).
- **Do not drive Aseprite.** The owner uses his own Aseprite; a computer-use run attached to it on 2026-10-01 and a crash
  put one of his own documents into Aseprite's recovery sessions. Art fixes, if any, go into the saved parts/scripts and
  are rebuilt headless with `tools/export_all.sh`.
- Never `make dev` or `install_app.sh` (they install over the owner's app); `make app` builds inside the worktree —
  confirm by reading the Makefile target. Never point a running Cicada at a bank.
- Codex runs are launched with `CICADA_CAPTURE=off` and detached, e.g.
  `CICADA_CAPTURE=off nohup codex exec -m gpt-6.1-sol -c model_reasoning_effort=xhigh --dangerously-bypass-approvals-and-sandbox -C <worktree> --json -o <out>/last.md - < <prompt.md> > <out>/events.jsonl 2> <out>/stderr.log &`
  — a foreground shell is killed at two hours, and a run can be resumed with `codex exec resume <thread_id>` (the id is
  the first line of `events.jsonl`) after a network drop.
- Privacy rule (CLAUDE.md) on every word of docs, commits and the PR body. Copy stays provider-neutral.
- PR to `dev`; **never merge** — the owner reviews the motion and the room first.

```
Read docs/specs/2026-10-02-study-room-sprites-finish-handoff.md in the worktree .worktrees/study-room-sprites (branch
feat/study-room-sprites) in full, then CLAUDE.md, docs/goals/working-method.md and
docs/specs/2026-10-01-bookworm-sprites-spec.md (§7–§9 closely; its dated 2026-10-01 notes are the owner's decisions).

Finish G176's first PR: the owner's new bookworm and study room on the real sprite sheets.

1. Hand Codex (gpt-6.1-sol, extra-high effort, launched as the handoff says) "Run C part 2": make `swift test` fully
   green by fixing the five failures in the handoff's table at their cause; pin the hotspot rects and gaze edges measured
   from the real sheets; render the room composites (`CICADA_WRITE_COMPOSITES=1 swift test --filter WindowSpritesTests`)
   and look at every one; check Reduce Motion, Low Power and the hidden-window pause; `make app` and confirm the bundle
   holds the 36 sheet files plus the manifest; handle the sleeping→reading pop; reconcile TODO.md (ruling 18 + the two
   owner decisions as dated amendments), the G176/G107/G125/G127 rows, docs/architecture/app.md, DESIGN_RULES and the art
   README to the final truth. No Aseprite GUI. No commits by Codex.
2. Review its work with a workflow: correctness/regressions, test integrity (no weakened assertion), and
   rails/accessibility/docs/privacy, with adversarial verification of every finding; send confirmed findings back to the
   same Codex session; repeat until clean.
3. Verify yourself: `swift test` twice, the CLAUDE.md size test, `tools/export_all.sh` twice byte-identical, the preview
   page in a browser, the composites.
4. Commit in reviewable steps citing G176, push, open the PR against dev with Q1 first, the owner's two decisions, the
   DR ids (DR-13, DR-50, DR-61, DR-65, DR-66) and ruling 18. Do not merge. Tell me what to look at and how.
```
