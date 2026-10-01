# G176 app integration, Run C part 1

The binding implementation plan is §7–§9 of
[`2026-10-01-bookworm-sprites-spec.md`](../specs/2026-10-01-bookworm-sprites-spec.md).
This worktree builds the app against that contract while the art runs supply the sheets separately.

## Global constraints and rulings

- Only this worktree is writable. No commits, installation, app launch, bank access or git mutations.
- State derivation, the response matrix, scheduling and interaction copy remain unchanged except for §7's edits.
- Ruling 18 supplies sprite timing caps. DR-13, DR-50, DR-61, DR-65 and DR-66 apply.
- Synthetic test sheets belong only to the test target. Missing production sheets draw no art, cache the failure,
  and retain the declared layout. Asset tests fail explicitly until real art arrives.
- The orchestrator performs the separate-agent review and commits. Local review runs sequentially.

## Tasks and verification

1. Add `Sprites/AsepriteSheetData`, `SpriteSheet`, `SpriteClip`, `SpritePlayback`, `SpriteLayerView` and fixtures.
   Write decoder, crop, clock and boundary tests first; run `swift test --filter 'SpriteSheetTests|SpriteClipTests'`.
2. Add `BookwormArt`, sizing and overlays; replace the mascot cache and menu timer with sheet playback.
   Run `swift test --filter 'BookwormArtTests|BookwormRendererTests'`.
3. Replace `BookwormView` and plumb transitions through `RoomModel` and `WormStage`.
   Pin both completion callback orders and run `swift test --filter RoomModelTests`.
4. Add the lattice, room layers, slice-derived hotspots, weather thumbnails and spine masks. Retire code grids.
   Amend the listed lints and tests only as §7 specifies. Run their filtered suites.
5. Write all real-sheet acceptance checks: manifest, pixels, marks, geometry, ruling 9, budget and composites.
   No file-existence skips. Literal hotspot measurements await the real sheets; independently measure their PNG ink
   in the acceptance tests at 3 pt meanwhile.
6. Update every §8 doc and draft the PR body with Q1 first and PR `#n`. Run `swift test` and the CLAUDE size test.
7. Review the behavioral diff line by line, then correctness and rails/privacy/docs. Record exact results and
   unresolved art-dependent checks in the final handoff message.

## Handoff

Run C part 1 is complete. Two full runs each executed 2,730 tests: 2,689 passed and 41 failed only on missing art
inputs, with zero unexpected failures. The specified CLAUDE-size check passed. The orchestrator holds the run report
and PR body outside this repository. Runs A/B must land before literal hotspot
measurements, composites, bundled app contents and the owner's visual/CPU review can be completed.
