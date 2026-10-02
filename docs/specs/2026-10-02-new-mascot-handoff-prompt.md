# Handoff prompt: a new Cicada mascot

Saved at `docs/specs/2026-10-02-new-mascot-handoff-prompt.md`. It drives a fresh session through
`app/CicadaApp/Art/sprites/MAKING_A_MASCOT.md` (the guide), which holds every procedure. Both files must be committed to
the G176 branch (so they reach `dev` with it) before this prompt is used. Fill the six placeholders on the INPUTS lines,
then paste the block into a fresh Claude Code session started at the repository root (the main checkout).

````text
You are the orchestrator for a new Cicada mascot, <character-name> ("<Display Name>"). Deliver, for <character-name>:
every animation the bookworm has, adapted to its anatomy; its 16 dark-room relit sheets; its 18 x 18 menu-bar set if
it appears there; its 25 manifest entries (24 if D2 = room); its registry entry and Settings tile; and its tests. Reuse
the shared study room, skies, overlays and wall clock unchanged. Codex draws, headless. You plan, decide with the
owner, review, commit and integrate. Only the owner merges.

THE GUIDE. app/CicadaApp/Art/sprites/MAKING_A_MASCOT.md holds every procedure, command, number and check. Each step
below names the guide section to execute; do exactly what it says. Its §0.1 defines every placeholder and the
variables (NAME, DATE, BASE, WT, APPWT, ART, BW, RES, SRC, TESTS, SPEC, RUNS, ASE). Every Bash call starts a new shell,
so variables and the working directory never carry over: in Step 3 you write them, absolute, to
<scratchpad>/codex-<character-name>/env.sh, and every later Bash call begins with
`source <that file> && cd "$WT"` (or `cd "$APPWT"`). If this prompt and the guide disagree, STOP and ask the owner.

INPUTS (filled by the owner before pasting)
- Character id: <character-name>             (guide §0.1 rules; Step 1 checks them)
- Display name: <Display Name>
- Owner's words: <owner-ask>                  (verbatim; goes into every Codex preamble, guide §10.5)
- Base design: <base-design>
- Other references: <references>              (or "none")
- Placement: <placement>                      (room+menu | room | menu; default room+menu; it pre-answers decision D2,
                                               which you confirm at S2)
Use these values for every <…> elsewhere in this prompt and in the guide's commands.
Filled by you: <YYYY-MM-DD> = the day you create the worktree and art folder; <scratchpad> = this session's scratchpad
directory.
Filled by the owner at checkpoint 1: <model> and <effort>, the Codex model and reasoning effort (decision D1). If he
wants a tool other than Codex, STOP: guide §10, manifest.py's authoring field and Steps 8-12 must be rewritten first.

PRECONDITIONS (check them yourself before anything else; guide §0.5 Step 1 has the exact commands; cwd: repository
root, read-only apart from the fetch)
1. git fetch origin; BASE=$(git rev-parse origin/dev) (a commit id). Then:
     git ls-tree --name-only "$BASE" app/CicadaApp/Sources/CicadaApp/Sprites/MascotRegistry.swift \
       app/CicadaApp/Art/sprites/bookworm-2026-10-01/tools/verify_night.py \
       app/CicadaApp/Art/sprites/MAKING_A_MASCOT.md docs/specs/2026-10-02-study-room-scenery.md
   All four paths must print (git ls-tree exits 0 either way; read the output). If any is missing: STOP (S0) and ask
   the owner whether to wait for the G176 PR or to start from another branch he names; then BASE is that branch's
   commit, and every guide check uses "$BASE". The PR base stays dev and its body says it contains G176. Never merge
   that branch yourself.
2. The tool checks: Aseprite binary present (never started; `"$ASE" --version` is CLI-only and must print
   Aseprite 1.3.18.6-dev); codex --version prints codex-cli 0.160.0; Pillow with get_flattened_data; node; gh;
   gh auth status and codex login status both print "Logged in"; codex mcp list (name every enabled server in the
   preamble). A version that differs from its pin, or any failure: STOP and report which.
3. git worktree list | grep -c "<character-name>-" || true   must print 0, and
   git branch --list "feat/<character-name>-*"   must print nothing. Otherwise STOP (S0b): ask whether to resume, and
   resume per guide §0.5 Step 1 (S0b).
4. echo "<character-name>" | grep -Ex '[a-z][a-z0-9]*(-[a-z0-9]+)*' | grep -Ev '^(bookworm|room|test-skin)(-|$)' \
     | grep -Ev 'small|night' | grep -Ev '(^|-)(dark|lit)(-|$)'
   must print the name. Otherwise STOP and ask the owner for another id.
5. test -r on <base-design> and on each reference must succeed (skip the references when <references> is none).
   Otherwise STOP and ask for the files.
6. Open <base-design> and every reference and look at each one yourself.

RAILS (binding; guide §0.4 in full; restate them in every Codex prompt through the guide §10.5 preamble)
- Headless authoring only: "$ASE" -b with --script-param before --script. Never drive or share the owner's open
  Aseprite: never open, focus, attach to or quit it; never `open -a Aseprite`; never --script without -b; never computer
  use or any GUI tool; Codex calls no MCP tool at all; never touch Aseprite's recovery sessions, scripts folder or
  preferences. A GUI session only with the owner's approval for that one run, after he quits Aseprite (guide §10.6).
- Codex never commits, pushes, stashes, branches or resets. You review and commit with this session's attribution
  lines, citing G127. Never a bare git stash.
- Never make dev, make install-app, make run-app, app/CicadaApp/install_app.sh, app/CicadaApp/bundle.sh --run or swift
  run; never launch a built app; never point the app at a bank; never read memory/, ~/.cicada or ~/.claude/projects.
- Never work in the main checkout; one worktree per parallel run; never two Codex sessions in one worktree at once.
- Privacy rule on every word of every prompt, commit, PR and doc; placeholders only. Copy is provider-neutral. Own work
  only; stop well short of any existing character's trade dress.
- Same contract: the eight states, tags, canvases, slices, caps and response matrix are the bookworm's; state art only;
  no flash or strobe. The bookworm, the room and their manifest entries stay byte-identical ($BW/preview.html may
  differ only in its embedded palette).
- Departures are dated spec notes, never chat. PR against dev. Nothing merged without the owner's yes.
- Your Claude subagents follow docs/goals/working-method.md ("Workflow agents run on sonnet/haiku unless the owner says
  otherwise"); the owner's implement/review/fix-at-medium-effort rule is not in the repo, so confirm it at S1 if your
  loaded memory does not carry it.

THE PROCEDURE (guide §0.5; each step has its exact commands and its Accept check there; do not start a step until the
previous Accept holds)
Step 2   Plan mode: read the list in guide §0.5 Step 2; present the plan. STOP S1 until approved.
Step 3   Create .worktrees/<character-name>-sprites off $BASE; write env.sh. Work there from now on.
Step 4   Make the art folder; copy and hash the references; record RUNS in qa/runs-path.txt (guide §0.5 Step 4, §3).
Step 5   Reference analysis (guide §5.1, §5.2; tracing per Step 5): fitted grid, palette, identity list, ANATOMY MAP
         (bookworm element -> <character-name> element, keeping code-facing names), keep-outs (§5.10), budget check
         (palette keys, decoded pixels, redraw budget §8.13, bytes), boards. <placement> pre-answers D2. STOP S2
         (checkpoint 1): ask every decision marked S2 in guide §0.6 (D1-D8, D11-D13), each with its built default;
         record each answer as a dated line in the spec; add D1's model and effort to env.sh.
Step 6   Write the spec (guide §5.3): six reader subagents in parallel, one writer subagent, two critic subagents,
         then revise once yourself; every tag an exact table; run the tag-name check; commit the spec and references.
         STOP S3 (checkpoint 2): open questions, D9, D10, D14.
Step 7   Create .worktrees/<character-name>-app from the committed spec.
Step 8   Prepare the Codex runs: the helper scripts (guide §10.2), the preamble template (guide §10.5), and one prompt
         file per run, each the preamble filled for that run followed by its brief: runA.md (guide §5.11) and runC1.md
         (guide §9.6). Record each worktree's starting commit in $RUNS/<run>.base.
Step 9   Launch Run A (art) and Run C1 (app) in parallel, detached, with the owner's <model> and <effort>; wait for
         the first event with a Monitor until-loop, never a foreground sleep.
Step 10  Follow and wait (guide §10.3); resume on failure (guide §10.4, always passing RUNS, CODEX_MODEL and
         CODEX_EFFORT), never relaunch fresh.
Step 11  Accept each run yourself (HEAD unchanged since <run>.base; both pipelines end "sprites: OK (all)"; the
         bookworm and room files and manifest entries unchanged; app failures only on the expected-red list), then
         commit it.
Step 12  Review and fix rounds on the separate branches (guide §5.12): boards, five-lens art review, app review, one
         fix list, resume the same Codex session; at least two iterations on the face, the prop action and the z's.
         STOP S4 (checkpoint 3): send him the boards and GIFs (SendUserFile when available, otherwise their paths).
Step 13  Merge the app branch into the art branch (message and attribution per the guide); two byte-identical full
         rebuilds of both art folders; swift test twice with 0 failures; build montages of the composites and look at
         them, every key frame and every Mascot and scenery pane. A failure after the merge goes to runC2 (Run C1's
         thread in the art worktree) or Run A's thread; then redo Step 13.
Step 14  Docs (guide §5.14); the machine-path check. Step 15  Write $RUNS/pr-body.md, check it, open the PR against
         dev. STOP S5 (merge gate): the owner reviews preview.html, the composites and live CPU. Never merge.
         Step 16  Report.

WHAT <character-name> MUST HAVE (guide §6.8 is the checklist; §6 has every bookworm frame and ms; adapt through the
anatomy map; bookworm holds are the default, D8)
Room scale, 64 x 48, base row 47, one day sheet per state, frame 0 the key frame carrying every state mark:
- awake idle: breathing with lead-and-follow, irregular blinks with one double, one secondary motion (the tail flick).
- reading idle in three covers (idle, idle@2, idle@3, identical per-frame ms): eye-tracked reading lines, three
  uneven page flips, close, the BOOK SWAP (the finished prop tucked behind the body, the next cover rising and opening),
  each tag ending on the next cover; the cyclic recolour map. If it holds no book, its equivalent prop (D5).
- sleeping idle: shut eyes (one-row lids), a slow breath, z -> zz -> zzz rising, fading Z -> Y -> X and shrinking,
  inside the z box and clear of the clock.
- happy idle (happy face, glint, sway), hungry idle (half lids, nod off, jolt, slow blink, small yawn), digesting idle
  (two chews, swallow bulge, smile), curious idle (the ? glyph every frame, tilt, two blinks), error idle (BLACK X
  EYES every frame, worried brows, sweat drop, tremble, no blink, no red).
- Poses: attentive.<g> (gaze, glance, two blinks; reading looks up from the page), expectant.<g>, eager.
- Beats: perk.<g> (<= 400 ms), talk.<g>, gulp.center (paper in, bulge down, smile), shake.<g> (sad face),
  cheer.center (happy and digesting only), sleeping talk.center (shut-eye mumble with a z puff); each <= 800 ms.
- Transitions on the sleeping sheet: intro (the yawn) and outro (the stretch), each <= 1,600 ms; the outro's last
  frame checked against the key frames of digesting, happy, reading and hungry.
- Exact tag sets: awake 18, hungry 18, happy 19, reading 54, digesting 7, sleeping 4, error 1, curious 1 (122 tags);
  slices ink, eye, lensL, lensR, plus errorLensL on error.
- Budgets that bind the default holds (D8): each idle loop's frame boundaries per minute must stay at or under
  digesting 375, sleeping 415, every other state 615 (guide §8.13; the room cap is 1,800/min, now at 1,758 worst).
  Keep-outs in canvas cells, top-left (guide §5.10): clock box cols 58-63 x rows 8-22, no ink in any frame; z box
  cols 40-63 x rows 0-14, and rows 0-7 only at cols 58-63; window zone cols 0-19 x rows 0-29 (ruling 9); base row 47.
Night: <character-name>-<state>-night-dark and -night-lit for all 8 states (16 sheets), generated by the relight
  (guide §7.6), never drawn; same tags, frames, ms, slices and alpha mask as day; glyph colours kept; the contrast
  floors of guide §7.7 set for its own marks; day art frozen by day-art-contract.json. The room is dark iff the time is
  night or the base weather is rainy, in every scenery mode; dusk stays day-lit. In the dark the character draws
  -night-lit when a Sleep schedule is on (the lamp means the schedule, never scenery), otherwise -night-dark. By day it
  draws the day sheet whatever the lamp. In -night-dark only canvas cols 0-27 x rows 29-47 get window light. With the
  lamp lit, warmth reaches canvas cols 0-43 only, and cols 44-63 are identical in both night sheets. Design the
  identity marks to read in the shadow band (guide §7.2-§7.3).
Menu bar (if placement includes it, D2): <character-name>-small, 18 x 18, the 8 state tags (guide §6.4, §5.8),
  redrawn, never downsampled; rows 16-17 empty; badge zone clear; dark outlines on both bars; no night variant.
Shared, unchanged (guide §8.1): backdrop, lamp, fly, window, plant, bean bag, mug, the 15 skies (5 bases x
  day/dusk/night), the 6 overlays (mist x3, rainbow day/dusk, shooting star at night), the wall clock, the spines,
  room-plan.json, room-light-map.json, room-motion.json and palette.json (except <= 6 new keys, D3). The scenery logic
  and Settings -> Sleep -> The scenery (Local weather · How Sleep is doing · Choose) are mascot-independent. Its Preview
  draws the selected mascot: look at it with <character-name> selected. Your character only coexists with them
  (ruling 9, the clock box, the redraw budget).
App (guide §9): one MascotRegistry entry appended to all (D10 order); the Settings tile appears from it with no view
  edit; the D9 copy and its call sites (guide §9.6 owned paths); the MascotRegistryTests catalog updated; every
  default-skin test looped over MascotRegistry.all (guide §9.6); the decoded-pixel budget per D4. The prefix-aware
  patch to three bookworm tools (guide §4.7) lands before any new sheet.

DELIVERABLES CHECKLIST (guide §0.7 and §0.8 give the command for each)
[ ] reference/ unchanged (shasum -c of the start hashes passes)
[ ] the spec with every tag as an exact table and every dated owner decision (D1-D14) and departure
[ ] parts/ as the pixel authority; a fix_<topic>.lua record for every change after seeding
[ ] 8 day sheets with the exact 122 tags and slices; every state mark on every frame
[ ] 16 night sheets, an exact relight each; day-art-contract.json
[ ] <character-name>-small with 8 tags (if D2 includes the menu bar)
[ ] 25 manifest entries (24 if D2 = room) with generator, authoring (the D1 model, headless) and date as constants in
    tools/character.py, and hashes; no machine paths; the bookworm's and the room's entries unchanged
[ ] palette additions with night ramps and pane tints (D3); the prefix-aware patch to the bookworm's tools
[ ] preview.html with every tag at real timing in the shared room; check_preview.mjs green
[ ] README.md, TAG_TIMINGS.md, run reports, the reading-cycle demo GIF
[ ] the registry entry, the Settings tile (Mascot and scenery panes rendered and looked at), the D9 copy
[ ] tests: catalog updated, default-skin tests looped, budgets per D4; swift test twice with 0 failures
[ ] both art folders rebuilt twice byte-identical; the bookworm and room files unchanged against $BASE
[ ] docs updated (app.md, G127 and G176 rows, TODO ruling 18 amendment and header); the PR against dev
[ ] the owner's yes before any merge

YOUR FINAL REPORT TO THE OWNER (return exactly these items)
- the PR link and its base (dev)
- sheet, tag and frame counts (day, night, small) and the manifest entry count
- the decisions D1-D14 as he made them, each with its dated note
- what was hand-tuned, and what is still rough
- every spec departure with its dated note, and every held item
- both swift test counts and failures; both rebuild results (byteIdentical)
- the budget figures: decoded pixels (room + bookworm, room + <character-name>), bytes, the worst redraws per minute
  (the "Room redraw maximum" line per mascot, from the command in guide §0.8)
- the commands to rebuild ((cd "$ART" && tools/export_all.sh)) and to open the preview (open "$ART/preview.html", his
  to run)
- what still needs him: the preview and composites review, the live CPU measurement, the merge
````
