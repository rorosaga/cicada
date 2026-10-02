# Worm fix pass — 2026-10-01; owner decisions completed 2026-10-02

This pass revises Run A's saved worm art against the art-director fix list and the owner's two later decisions. It delivers nine sheets, **130 tags / 1,095 frames**, one dark-outline menu sheet for both bar appearances and regenerated review demos. Every tag's behavior, frame count and exact millisecond holds are in [TAG_TIMINGS.md](TAG_TIMINGS.md). The surviving sheets retain their original frame counts, tag order and duration arrays. The removed dark variant accounts for eight fewer tags and 32 fewer frames. No Swift implementation changed, and no commit was made.

The room eyes now read as the owner's broad green eyes with a solid right pupil and a left sliver. The independently drawn menu head retains its normal plus pupils; error has black diagonal Xs at both scales. The reference comparison boards were rebuilt and inspected personally: `qa/compare/emotions@6x.png`, `qa/compare/menubar@8x.png` and `qa/compare/error-owner@6x-8x.png`. All ten original files in `reference/` byte-match commit `6c8e3b09` (`qa/wormfix-reference-hashes.json`). Generated comparisons no longer enter that folder.

## Owner decisions — 2026-10-01

**Black X eyes, no red — done.** Every room error frame (#0–12, 2,400 ms loop) shows a centered 3 × 4 left X and a larger 6 × 5 right X in `K`. Each has a full green pixel of air around its box. Only the error's inner left rim moves one pixel outward to make a 5 × 6 interior at `(10,17)`; the outside glasses silhouette stays unchanged. The extra `errorLensL=(10,17,5,6)` slice records that adjustment while common lens registration stays stable. Worried brows and the forming/sliding drop are retained. Every small error frame (#28–31, 1,500 ms loop) has a 3 × 3 diagonal `K.K / .K. / K.K` X in each lens and two cyan sweat pixels. Those Xs read differently from the normal plus pupils at 1× and 2× on both bars. The red error colour `e` / `worm.pupilError` is unused and removed from the palette and saved parts. `verify_owner_error_xs` independently checks the X patterns, shared room head offset, green gap, drop and absence of the former red in every exported error frame; `verify_owner_error_lens_slice` checks the added slice. The requested dated owner lines are in spec §3.5, §3.7, §4.4 and §11 Q4, with the necessary interior-box note in §3.3.

**Dark outlines on every bar — done.** `bookworm-small-dark` is deleted from source, exports, build/registry entries and active QA previews. Its `R` / `worm.small.rimDark` palette key is removed. `W` remains because other sheets use it for real highlights. There are now **26 palette entries**. The one coloured `bookworm-small` sheet is used on `#ECECEC` and `#1E1E1E`; no appearance variant or template rendition is supplied. Spec §11 Q8 records the exact dated decision. The regenerated `qa/menubar-comparison@{1,2,8}x.png` strips contain only the light and dark rows of this same sheet. The black rims have low contrast on the dark bar, as the owner explicitly requested; lime lens silhouettes, black eye holes and neck still identify the head.

The black-X parts were saved with Aseprite's native 1 px Pencil before the network interruption. On resume, the GUI generator continued from its pending write prompt and completed both builders. The room loop was inspected at 800%, the small loop at 800%, using onion skin and timeline playback. The green gaps, both Xs and falling drops were checked again against the fresh all-frame strips and worried-reference board. No saved pixel work was lost.

## A — must-fix

Frame numbers below are zero-based absolute sheet indices, unless a tag-local frame is explicitly named. The all-frame filmstrips have these same labels.

| Item | Result / implementation | Frame evidence inspected |
|---|---|---|
| **A1** body outlines | **Done, with a structural-glass exception.** The body-only compositor replaces enclosed skin `K` with fill and exposed four-adjacent `G/g` with `K`. Black pixels beside `D/L` stay because they are the glasses' inner rings. Torso/tail seams overlap two rows; native pencil repairs the slump seam, breath cap, crouch stray and tail cap. The closed-book spine also gains its outline. Independent checks inspect the saved body layer of all room frames. | Awake #0–4/#17–18; sleeping #0/#3–9/#19–25 and intro #45–47; gulp #116–117; crouch #72. `qa/compare/outline-breath-tail@6x.png`, sleeping/awake filmstrips and saved-layer verifier. |
| **A2** eyes | **Done; error updated by the owner.** Right interior is 8 × 7 at c23–30/r18–24; normal left is 4 × 6 at c11–14/r17–22. Right rest pupil is solid 3 × 3, with a clear side column at −2/+1 gaze; left pupil is a sliver. Downward rows a/b/c, reference highlight stairs, rounded wide pupil and hungry gaze variants are rebuilt with native pencil. Clamped far glances move up. Every attentive tag's local #5 differs from #0. Slice/clamp changes have dated spec notes. Error now uses both centered diagonal black Xs and the error-only 5 × 6 left interior described above. | All six emotion comparisons; awake attentive first/last poses and local #5; hungry attentive/expectant/perk/talk; reading #0–16/#23–55 and attentive.center on all covers. Room error #0–12 and small #28–31 all carry black Xs and sweat. |
| **A3** brows | **Done.** Happy/tired/sad/worried/curious stamps and their raised versions float above the head/rims. The worried furrow is a separate row. Curious combines happy-left/tired-right. | `qa/compare/emotions@6x.png`, key-frame boards for happy/hungry/error/curious, native parts at 800%. |
| **A4** sweat | **Done.** Held d3 is pointed 5 × 6 with a left white highlight; d1/d2 form at the shoulder. d4–d6 slide one pixel at a time, d7 elongates and d8 detaches. Every sweat pixel remains above r18. Exact holds stay unchanged. | Error #0–7, both iterations of `qa/compare/sweat@6x.png`, native error playback. |
| **A5** happy eyes | **Done.** One black ∩ per lens without white speculars. Closed happy eyes remain through cheer local #5 squash and reopen at #6. | Digesting #0–38 and happy cheer #128–134; `qa/compare/landing-cheer@6x.png`. |
| **A6** mouths | **Done.** Red interiors meet 3 × 2 talk1, 4 × 3 talk2, 5 × 4 gulp and the 6 × 5 yawn silhouette. Lower lips replace full black mouth rings; chews follow the same treatment. | Awake talk/gulp #95–119, hungry yawn/chew #6–16, sleeping intro #39–43/outro #50–53; mouth parts at 800%. |
| **A7** shading | **Done.** All body variants use the translated reference shadow band, clipped to each silhouette, including neck/bridge, underside arch and tail edge. Rest/flick share the tail shading pattern. | Base/reference board, awake breath #0–4/tail #17–18, sleeping idle and stretch frames. |
| **A8** cover swap | **Done, foreground peek clarified.** Outgoing and incoming covers coexist in down2/down3. The incoming top is a foreground `book` cel for those two frames; the outgoing book and subsequent rise remain on `book-back`. A first rebuild exposed only four incoming pixels; the second refinement enlarged the visible 3/6-row peek. Both cover ramps now pass the ≥6-pixel check on all covers. | Reading #73–84, #264–265/#450–451 overlap on covers 2/3; `qa/compare/cover-swap@6x.png` and the continuous 65,520 ms demo. |
| **A9** wake blink | **Done.** Sleeping outro local #2 uses `blink.half`; the highlighted open eye first returns at local #7. | Sleeping absolute #48–56, especially #50/#55; outro filmstrip. |
| **A10** frame contents | **Done, z minimum clarified.** Sparkle3 is a gapped decaying 7 × 7 `q` ring without `Q`; hungry idle #5 has the delayed head exhale; eager mouth/raised brows occur only on anticipation local #0. Final pale medium/large z glyphs shrink one size; the smallest remains readable at 3 × 3. | Happy cheer #131, hungry idle #5, awake eager #79–82, sleeping #8–9/#18–19/#30–31; z and landing boards. |
| **A11** small set | **Done in the single menu sheet.** Bob preserves both bottom rims by dropping a neck row. Chew/sleep neck contour moves outward; hungry lids move to r4. Curious has a rest brow and a lifted brow. Reading book uses the prescribed outlined seven-column stamp on r12–15, with r11 clear. The later owner decision removes the grey-rim variant. | All 32 small frames at 8×; awake #3, happy #12, hungry #23, digesting #9–10, sleeping #8, curious #16–19, reading #24–27 and error #28–31. The same art on light/dark comparison strips at 1×/2×/8×. |
| **A12** hygiene | **Done.** `verify.py` writes all menu comparisons and the pixel close-up to `qa/`. The generated reference PNG and stale demo comparison PNGs are removed. Owner reference files are unchanged. | `qa/menubar-comparison@{1,2,8}x.png`, `qa/menubar-pixel@8x.png`, reference hash report and final diff. |

## B — craft improvements

| Item | Result / implementation | Frame evidence inspected |
|---|---|---|
| **B1** tail cap | **Done.** Flat upturned three-pixel cap, straight outer edge and matching one-pixel-up flick. A second refinement removes the extra outside pixel beside the cap. | Awake #0/#17–18; native tail part and outline board. |
| **B2** closed book | **Done.** Removed the heavy black wedge, doubled corners and orphan cream; restored the single-step cover edge and separated the page tip from the lens. | Base comparison, awake #0, gulp book-low and sleepy book; book part close-up. |
| **B3** book transitions | **Done.** close3/open1 are tilted in-betweens. Intro local #6 shows the slump and tilted book; #7 lands the sleeping book. Outro #4 uses the tilted book. Sleeping rest shows a cover top with a front page strip and separating outline. Additional close1/close2 outline pixels were corrected after the first visual pass. | Reading #73–76/#82–84; sleeping intro #44–45/outro #52–53; native page-flip/onion-skin inspection. |
| **B4** pre-flip reversal | **Done, dated clarification.** A return immediately followed by a flip holds l3/head 0 for the same 140 ms. All other line returns retain their specified bob. Page eye rows restart at a. | Reading #16–22/#34–40/#55–61; page-flip board and complete idle filmstrips. |
| **B5** gaze shakes | **Done.** The shake offsets oscillate around each gaze head and settle in that gaze instead of centered. | Awake #120–134, reading gaze shakes on all covers, hungry/happy shakes; native tag playback. |
| **B6** swallow | **Done.** The 3 × 3 paper scrap overlaps the upper lip with the red mouth visible below; a corner cream pixel remains on #2. An outlined one-pixel neck bump with 2 × 2 shade travels downward on the body layer. | Awake #113–119; digesting #4; all gaze-state gulp filmstrips and `qa/compare/gulp@6x.png`. |
| **B7** hungry lids | **Done.** Curved lower edge clears its two end pixels to green; every hungry gaze follows its direction. | Hungry #0, attentive first/far frames and perk.right/talk.right; tired/reference comparison. |
| **B8** tiny z | **Done.** 3 × 3 glyph is `ZZZ / .Z. / ZZZ`. Palette variants share the stamp. | Sleeping #0/#8–9; z board and native playback. |
| **B9** open book / flip | **Done in two iterations.** Outer black rim, spaced word-run rows 38/40/42, cleaned cream top stairs and left-side rim light. All five moving pages have a grey edge and black cap where edge-on. The second pass rebases curl diffs onto the corrected open book rather than reintroducing the original page marks. | Reading #0/#17–22, full cover idle strips and native 800% flip with onion skin. |
| **B10** land | **Done with connected coordinates.** Eager/cheer land is distinct from crouch: widened body contact patch r47 c45–53 and a lowered head. Suggested c3/c60 would be detached from this saved silhouette, so the dated spec note uses the actual base. | Awake #79/#82, happy #128/#133; both landing boards and body-layer check. |
| **B11** tiny sweat | **Done.** Two-pixel cyan drop in rest and the lowered pose, beside the new X eyes in the single dark-outline sheet. | Small error #28–31 at 8× and light/dark menu-bar strips. |
| **B12** narrow right menu lens | **Not applied.** It explicitly needs owner approval and would shrink a lens/remove the right reading gaze, contrary to the later owner instruction to preserve lens/pupil size. Temple arm and gaze remain as Run A drew them. | Owner/menu comparison, small reading #24–27 and full small key/filmstrip boards. |
| **B13** mad brow | **Done, raised to float.** Rebuilt the inward V ramps; left/right stamps are lifted one/three rows to keep the same clear-gap rule as A3. Remains an unbundled demo only. | `qa/compare-mad@6x.png`, combined emotions board, `demo/bookworm-mad-demo@6x.gif`. |

## C — optional items

| Item | Decision / evidence |
|---|---|
| Bridge | **Done:** horizontal black bar/lit upper edge on every head variant; base/glasses comparison. |
| Neck dent | **Left unchanged:** the outline repair and new band already restore a clean connected neck. Avoid another silhouette change after the required pass. |
| Trunk edge rhythm | **Left unchanged:** the automated exposed-skin outline pass closes the contour; an extra shape shift is optional. |
| Temple outline | **Done:** black pixel above the arm's light at r18 c35; base comparison. |
| Head dome cadence | **Left unchanged:** preserve the approved silhouette while fixing its eyes/brows. |
| Curious question core | **Left unchanged:** retains the specified white core/palette mark. It remains a small optional exposed highlight. |
| Sleeping mumble head bob | **Left unchanged:** exact specified pose/timing retained; mumble remains subtle. |
| Tiny sleeping z | **Done:** final rise ends at r0–1/c16–17, clear of the head; small sleeping filmstrip. |
| Menu alias / record classification | **Done:** small builder writes `menubar.aseprite`; README separates active pipeline from one-time migrations, historical GUI records and inventories. |

## Dropped items respected

- All timing changes stay dropped: breath/hold, perk hang, shake decay, flip cadence, rotating line holds, hungry nod depth, longer digesting, sweat acceleration, extra transition frames and calmer menu cadence. Frame holds are checked against the original timing tables.
- Lifts remain rigid whole-figure moves.
- Reading head-bob stays on line returns, with only the approved B4 pre-flip clarification.
- Small happy retains rest/bob/sparkle rather than adding closed happy eyes.
- Small error keeps Run A's neck-only tremble; no new full-head translation was introduced.
- Small slices remain inner boxes, clarified in §3.3; no small lens reshaping.
- Cover `H/B` colours and contrast remain unchanged.
- Glasses' upper-right highlights retain the reference ramp rather than changing to `D`.
- Room wide pupil follows A2's rounded stamp, superseding the dropped plus proposal; normal menu pupils remain pluses. The later owner's black diagonal X decision applies only to error at both scales.

## Native work, verification and iteration

The face, eye, brow, mouth, sweat and selected outline pixels were authored with **Aseprite's native 1 px Pencil** in locked palette colours using `lua/gui_wormfix_face.lua`, executed through computer use in the GUI. It saved the parts, and `gui_wormfix_build.lua` assembled the first-pass sources inside Aseprite. `gui_owner_error.lua` then applied the owner's X eyes with the native Pencil and saved both parts; `gui_owner_build.lua` rebuilt the final nine sources inside the GUI. The same generators also ran headless. `gui_wormfix_inspect.lua` opened the page flip at 800%; onion skin and the next-frame control were used before normal playback. The GUI stroke records name the precise hand-tuned pixels; saved parts remain the source of truth.

The first revision changed face, outline, shadow, book, z and small parts. Its overlap check caught four visible incoming-cover pixels. The second refinement enlarged that peek, corrected open-book curl inheritance and tail edge, then added close1/close2 contour pixels. The native face pass was rerun and saved before final builds. Comparison boards, all-frame filmstrips and the final 6×/8× exports were inspected again. No interpolation, gradients or colour blending was introduced.

Evidence lives in regenerable `qa/`:

- `wormfix-owner-export-1.log` and `wormfix-owner-export-2.log`: successful final worm builds and verifiers, including exported-source pixel equality, every frame's marks, palette/alpha, timing, seams, actual tag GIF timing and the new owner checks. The earlier `wormfix-final-export-*` logs describe the historical first pass.
- `wormfix-rebuild-comparison.json`: SHA-256 comparison of two complete final saved-source rebuilds, covering all **162** source/export/demo/tag-GIF files.
- `wormfix-native-source.json` and `wormfix-native-gif.json`: completed final native playback records, one entry for every surviving tag, **130 clips** each. Both GUI dialogs visibly reached `COMPLETE: 130 clips`.
- `wormfix-native-demos.json`: completed continuous three-cover reading and mad demo playback; its GUI dialog visibly reached `COMPLETE: continuous reading + mad`.
- `wormfix-gui-sessions.json`: historical first-pass sessions and the two resumed sessions. The final lock ran from 11:47:31 to 12:02:35 UTC on 2026-10-02, under 20 minutes. Only this worktree's documents were closed; the shared lock was released.
- `wormfix-baseline-parity.json`: original tag order and every frame duration match commit `6c8e3b09`.
- `wormfix-helper-tests.log`: every existing public Aseprite helper check passed.
- `wormfix-final-swift.log`: first-pass Swift verification, **2,720 tests passed, zero failures**. Earlier baseline and isolated runs failed the same two assertions in `SleepViewModelTests.test_pollLoop_doesNotFireEarly_whenStoreStatusStaysIdleThroughout`; those logs are retained. That full run passed without changing the code. The later owner decisions change only art, its generators/checks and documentation; the two new complete asset builds rerun the verifier, and no Swift source or test refers to the deleted variant.
- `wormfix-reference-hashes.json`: all ten original reference files are unchanged.

The new verifier helpers are deliberately separate for the Run B merge: `verify_wormfix_lens_slices`, `verify_wormfix_attentive`, `verify_wormfix_swap`, `verify_wormfix_body_outline`, `verify_owner_error_xs`, `verify_owner_error_lens_slice` and `verify_owner_single_menubar`.

## Limits and integration decisions

The review's literal enclosed-black rule would remove structural inner glass rings, so its skin pass has the documented `D/L` exception. B10's suggested far-edge coordinates were changed to the connected contact patch. Tiny z stays at a 3 × 3 floor instead of shrinking into an unreadable dot. The latest owner decision supersedes the earlier grey-rim approval: dark outlines remain on both bars and the variant is removed. B12 remains pending because it changes the owner's lens size and reading gaze. These are recorded as short dated spec notes; no unrelated spec sections were revised.

Remaining rough edges are the unchanged optional question-mark core and subtle sleeping mumble. The resting pupil is a solid 3 × 3 pixel block at this scale, as A2 directs; the wide pose carries the larger rounded shape. The narrow left sliver is deliberately asymmetric. The sleeping outro ends with a standing closed book, so an app transition straight to reading's open-book key frame still needs the reading opening beat or an accepted handoff pop.

App integration remains the orchestrator's separate run: adopt `lensL=(11,17,4,6)` and `lensR=(23,18,8,7)` on all eight room sheets, retain `eye=(27,21,2,2)`, preserve the additional error-only left interior slice, use the single dark-outline small sheet on both appearances, refresh any golden images and preserve the cover cycle. The approved art is exempt from the working-surface palette rules in its own pixel-art area (DR-13); application motion/accessibility rails remain DR-61/DR-66 and the dated sprite spec. No app launch, integration or live-room claim is made here.

[WORM_FIX_FILES.txt](WORM_FIX_FILES.txt) enumerates the changed/new public files, removed generated files and local QA outputs. [FILE_INVENTORY.txt](FILE_INVENTORY.txt) is the whole-directory inventory, including inherited records. Original reference files are excluded from both write lists.
