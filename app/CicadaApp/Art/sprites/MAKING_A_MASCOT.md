# Making a Cicada mascot

How to turn an owner's base design into a complete Cicada mascot: every room-scale animation the bookworm has, its
dark-room relight, its 18 × 18 menu-bar set, its manifest entries, its registry entry and Settings tile, and its tests.
The shared study room (backdrop, lamp, fly, window, skies, overlays, wall clock) is reused unchanged.

- **This file:** `app/CicadaApp/Art/sprites/MAKING_A_MASCOT.md`.
- **The paste-in prompt that drives a fresh session through it:** `docs/specs/2026-10-02-new-mascot-handoff-prompt.md`.
- **Both files must be committed to the G176 branch** (so they reach `dev` with it) before the prompt is used: Step 1
  checks for this file on the base.
- **Snapshot.** Every number was read from the finished G176 branch at commit `e0c21b45` (the bookworm, the room, the
  dark-room relight, the skies and overlays, the wall clock, the sprite player, Settings → Sleep → The scenery and
  → Mascot, and the mascot registry). Re-measure anything you depend on; a stale number is worse than none.
- **Paths.** Every path is relative to the repository root. Inside a worktree, the worktree root is the repository root.
- **Contract vs calibration.** A number marked *contract* is read by code or tests: changing it means changing them in
  the same PR, with the owner's word. Everything else is the bookworm's *calibration*: a measured value your own spec
  may retune.

**Contents.** [0 Agent quickstart](#0-agent-quickstart) · [1 What binds](#1-what-binds) ·
[2 Prerequisites](#2-prerequisites) · [3 Folder layout](#3-folder-layout) · [4 The pipeline](#4-the-pipeline) ·
[5 From base design to shipped character](#5-from-base-design-to-shipped-character) ·
[6 Animation catalog](#6-animation-catalog) · [7 Lighting](#7-lighting) · [8 Scenery](#8-scenery) ·
[9 Mascot registry](#9-mascot-registry) · [10 Driving Codex](#10-driving-codex) ·
[11 Quality bars and checks](#11-quality-bars-and-checks) · [12 Known gotchas](#12-known-gotchas) ·
[13 Worked example: the bookworm](#13-worked-example-the-bookworm) · [Appendix A](#appendix-a-every-authoring-key-night-ramp-by-band-and-pane-tints) ·
[Appendix B](#appendix-b-the-light-map-over-the-whole-room-2--2-cell-preview)

---

## 0. Agent quickstart

Read this section first and execute it top to bottom. Every later section is reference for one of these steps.

### 0.1 Placeholders, short names and environment

**Placeholders** (each appears in `<angle-brackets>`; this is the only list):

| Placeholder | Meaning | Rule |
|---|---|---|
| `<character-name>` | The mascot id, sheet prefix stem and folder stem | Matches `[a-z][a-z0-9]*(-[a-z0-9]+)*`: a letter first (it becomes a Swift identifier, §9.1), no leading, trailing or double hyphen. Not `bookworm`, `room` or `test-skin`, and not starting with `bookworm-`, `room-` (every `"$RES/room-*"` byte-identity glob would match it) or `test-skin-` (a test uses it). Contains neither `small` nor `night` anywhere, and has no `dark` or `lit` segment: the tools classify sheets by substring (`'small' in name`, `'-night-' in name`, `$BW/tools/manifest.py:17,24`; `make_review.py:15`; `verify.py:58,304`). Step 1 runs the check. Stable forever once shipped: it is stored per viewer. |
| `<Display Name>` | The name on the Settings tile and in VoiceOver | The owner's pick. Lives in the registry, not in `Copy`. |
| `<owner-ask>` | The owner's own words for this character, verbatim | Goes into every Codex preamble (§10.5). His own design words are fine to quote (privacy rule). |
| `<YYYY-MM-DD>` | The date the art folder is created | The day Steps 3–4 run; `env.sh` fixes it as `DATE`. |
| `<base-design>` | Path to the owner's base design image | Read-only. If it is untracked in the main checkout (for example under `app/assets/`), it does not exist in a worktree: from the art worktree, copy it as `../../<path>`. |
| `<references>` | Paths to the owner's other references (emotions, menu-bar head), or `none` | Read-only; same rule as `<base-design>`. When it is `none`, skip it in the Step 1 readability check and in Step 4's `cp`. |
| `<placement>` | Where it appears: `room+menu` (default), `room`, or `menu` | Decision D2. |
| `<model>`, `<effort>` | The Codex model and reasoning effort that draw it | Decision D1; the owner's pick. |
| `<scratchpad>` | The session's scratchpad directory (absolute, outside the repo) | Runs, prompts and analysis scratch live under `<scratchpad>/codex-<character-name>`. A resumed session has a different scratchpad: it finds the old folder through `$ART/qa/runs-path.txt` (Step 4, S0b). |
| `<run>` | A Codex run name, for example `runA`, `runC1`, `runA-fix1` | One folder per run under `$RUNS`. |
| `<thread-id>` | A Codex thread id (first line of a run's `events.jsonl`) | Used to resume. |
| `<state>` | One of `awake sleeping digesting happy curious hungry reading error` | The eight `BookwormState` case names. |
| `<g>` | One of `left center right` | A gaze. |

**Short names** used in prose and set as shell variables by the block below (the shell values are absolute; the paths
here are repository-relative):

| Name | Path |
|---|---|
| `BASE` | The commit the branches start from: `origin/dev` at Step 1 (or the branch the owner names at S0), as a commit id |
| `WT` | the art worktree, `.worktrees/<character-name>-sprites` |
| `APPWT` | the app worktree, `.worktrees/<character-name>-app` |
| `ART` | `app/CicadaApp/Art/sprites/<character-name>-<YYYY-MM-DD>` (the new character's art folder) |
| `BW` | `app/CicadaApp/Art/sprites/bookworm-2026-10-01` (the worked example, and the owner of the shared room, `palette.json`, `room-plan.json` and `room-light-map.json`) |
| `RES` | `app/CicadaApp/Sources/CicadaApp/Resources/sprites` (one flat folder: every bundled sheet and the manifest) |
| `SRC` | `app/CicadaApp/Sources/CicadaApp` |
| `TESTS` | `app/CicadaApp/Tests/CicadaAppTests` |
| `SPEC` | `docs/specs/<YYYY-MM-DD>-<character-name>-sprites-spec.md` |
| `RUNS` | `<scratchpad>/codex-<character-name>` (absolute; outside the repo) |
| art worktree | `.worktrees/<character-name>-sprites` (branch `feat/<character-name>-sprites`) |
| app worktree | `.worktrees/<character-name>-app` (branch `feat/<character-name>-app`) |

**The variables block.** Every Bash tool call starts a new shell: neither shell variables nor the working directory
carry over, and a bare `$ART` or `$RUNS` in a later call is empty (`cd ""` stays put; `"$RUNS"/x` becomes `/x`). So in
Step 3, write this block once, with absolute paths, to `<scratchpad>/codex-<character-name>/env.sh` (Write tool), and
begin **every** later Bash call with `source <that file> && cd "$WT"` (or `cd "$APPWT"` for an app-worktree step).
Every command in this guide assumes it, and the guide's code blocks leave that first line out.

```sh
# <scratchpad>/codex-<character-name>/env.sh (written in Step 3; every value absolute)
export _ZO_DOCTOR=0 CICADA_CAPTURE=off PYTHONDONTWRITEBYTECODE=1
NAME=<character-name>
DATE=<YYYY-MM-DD>
BASE=<the commit id Step 1 printed>
WT=<absolute art worktree>                  # <repository root>/.worktrees/<character-name>-sprites
APPWT=<absolute app worktree>               # <repository root>/.worktrees/<character-name>-app (made in Step 7)
ART="$WT/app/CicadaApp/Art/sprites/$NAME-$DATE"
BW="$WT/app/CicadaApp/Art/sprites/bookworm-2026-10-01"
RES="$WT/app/CicadaApp/Sources/CicadaApp/Resources/sprites"
SRC="$WT/app/CicadaApp/Sources/CicadaApp"
TESTS="$WT/app/CicadaApp/Tests/CicadaAppTests"
SPEC="$WT/docs/specs/$DATE-$NAME-sprites-spec.md"
ASE="${ASEPRITE:-/Applications/Aseprite.app/Contents/MacOS/aseprite}"   # aseprite is not on PATH
export RUNS=<scratchpad>/codex-<character-name>
# appended after S2 answers D1:
export CODEX_MODEL=<model> CODEX_EFFORT=<effort>
```

- `RES`, `SRC` and `TESTS` point into the **art** worktree. In an app-worktree step, and in every Codex prompt, write
  the repository-relative path from the table above instead.
- `RUNS`, `CODEX_MODEL` and `CODEX_EFFORT` are exported, so `run-codex.sh` and `chain.sh` (§10.2) inherit them.
- In Step 4 the absolute `RUNS` path is also written to `$ART/qa/runs-path.txt` (gitignored). Never put it in a
  tracked file: Step 14 greps the diff for `/private/`.

**Environment variables** the tools read:

| Variable | Read by | Meaning |
|---|---|---|
| `ASEPRITE` | `export_all.sh`, `verify.py`, `manifest.py` | Overrides the Aseprite binary path (default `/Applications/Aseprite.app/Contents/MacOS/aseprite`). |
| `BUILDS` | `export_all.sh` | Space-separated builders to run (default: all of that folder's builders). |
| `STAGE` | `export_all.sh` | `all` (default) or `worm` (bookworm folder only: worm builders, no relight, no manifest). |
| `CICADA_CAPTURE=off` | Cicada's Stop hook | Keeps Cicada from capturing the Codex sessions it spawns. |
| `_ZO_DOCTOR=0` | zoxide | Silences the shell's zoxide warning in tool output. |
| `CODEX_WT`, `RUNS`, `CODEX_MODEL`, `CODEX_EFFORT` | `run-codex.sh`, `chain.sh` (§10.2) | Worktree, runs folder, model, effort (`run-codex.sh` defaults to `xhigh`; always pass the D1 effort). |
| `CICADA_WRITE_COMPOSITES=1` | Swift composite tests | Writes PNGs to `$TMPDIR/cicada-sprite-composites/`. |
| `PYTHONDONTWRITEBYTECODE=1` | Python | Keeps `__pycache__` out of the tree. |

### 0.2 Inputs

- [ ] `<base-design>`: the owner's base design (an image; treat it as an AI render on a loose grid, not pixel art).
- [ ] `<references>`: optional emotion sheets and a menu-bar head design.
- [ ] `<character-name>` and `<Display Name>`.
- [ ] `<owner-ask>`: the owner's own words for this character, verbatim.
- [ ] `<placement>` (D2; it pre-answers D2, which is confirmed at S2).
- [ ] The owner's answers to the decision points in §0.6, collected at the STOP points.

### 0.3 Outputs (exact files)

| # | File(s) | Count | Made by |
|---|---|---:|---|
| 1 | `$ART/reference/*` (the owner's files, byte-identical, hashed at start and end) | ≥ 1 | Step 4 |
| 2 | `$SPEC` (binding spec, with every dated owner decision) | 1 | Steps 5–6 |
| 3 | `$ART/parts/<character-name>-parts.aseprite` (64 × 48) and `$ART/parts/<character-name>-small-parts.aseprite` (18 × 18) | 2 | Run A |
| 4 | `$ART/src/<character-name>-<state>.aseprite` (day) | 8 | Run A builders |
| 5 | `$ART/src/<character-name>-<state>-night-dark.aseprite` and `-night-lit.aseprite` | 16 | Run A relight |
| 6 | `$ART/src/<character-name>-small.aseprite` | 1 | Run A |
| 7 | `$ART/lua/*` (helpers, builders, script table, relight, `fix_*` records) and `$ART/tools/*` (export, verify, manifest, preview, review, report, rebuild check) | — | Run A (§4.6) |
| 8 | `$ART/day-art-contract.json`, `$ART/preview.html`, `$ART/README.md`, `$ART/TAG_TIMINGS.md`, `$ART/<RUN>_REPORT.md`, `$ART/FILE_INVENTORY.txt`, `$ART/demo/*.gif`, `$ART/qa/.gitignore` | — | Run A |
| 9 | `$RES/<character-name>-<state>.{png,json}`, `$RES/<character-name>-<state>-night-{dark,lit}.{png,json}`, `$RES/<character-name>-small.{png,json}` | 25 pairs (50 files); 24 pairs if D2 = `room` | `$ART/tools/export_all.sh` |
| 10 | `$RES/sprites.manifest.json`: 25 new entries (36 → 61); 24 (36 → 60) if D2 = `room` | 1 file | `$ART/tools/manifest.py` |
| 11 | `$BW/palette.json` (≤ 6 new keys with ramps; D3); the prefix-aware patch to `$BW/tools/manifest.py`, `$BW/tools/verify_room.py`, `$BW/tools/make_preview.py` (§4.7); and `$BW/preview.html`, regenerated by the bookworm export (it embeds `palette.json`, `$BW/tools/make_preview.py:9`, so it differs from `$BASE` only in the embedded palette) | 5 files | Run A |
| 12 | `$SRC/Sprites/MascotRegistry.swift`: one new entry, appended to `all` | 1 line pair | Run C1 |
| 13 | The copy that names the bookworm (D9) and its call sites: `$SRC/Views/Sleep/StudyRoom.swift:317` (inside `WormHotspot`, which has no mascot in scope: it reads one through `@AppStorage(MascotPreference.defaultsKey)` + `MascotRegistry.resolve`); `$SRC/Theme/Copy+Welcome.swift:74` (`gsLeaveWhileReading`, a `static let` used at `$SRC/Views/Home/GettingStartedCard.swift:339` and in the `welcomeHomeSentences` array at `Copy+Welcome.swift:159`); `$SRC/Theme/Copy+Settings.swift:39` (`loginItemQuiet`, called from `$SRC/Services/LoginItemService.swift:50` and tested in `SettingsGeneralF10Tests.swift:63-67`) | 3 sites + 2 call-site files | Run C1 |
| 14 | Tests: `$TESTS/MascotRegistryTests.swift` catalog, and every default-skin test looped over `MascotRegistry.all` (§9.6) | — | Run C1 |
| 15 | Docs: `docs/architecture/app.md`, `docs/goals/memory-evolution.md` (G127 and G176 rows, edited in place), `docs/goals/TODO.md` (ruling 18 dated amendment, header, "Pick up here"), `docs/design/DESIGN_RULES.md` log if UI changed | — | Step 14 |
| 16 | One PR against `dev`, citing G127 | 1 | Step 15 |

### 0.4 Rails (binding; restate them in every Codex prompt)

1. **Author headless only.** Every Aseprite call is `"$ASE" -b … --script-param … --script …` (params before
   `--script`). The owner's 2026-10-02 rule (§1) supersedes the computer-use clause of R-BW12.
2. **Never drive or share the owner's open Aseprite.** Never open, focus, attach to or quit it; never `open -a
   Aseprite`; never run `--script` without `-b`; never use computer use or any GUI tool (`cua_repl`, `node_repl`,
   `computer-use`); never touch Aseprite's recovery sessions, `scripts/` folder or preferences. The only exception is a
   GUI session the owner approves for one run after quitting Aseprite himself (§10.6).
3. **Codex never commits, pushes, stashes, branches or resets.** Read-only git is fine. The orchestrator reviews each
   run and commits with the session's attribution lines, citing G127.
4. **Never `make dev`, `make install-app`, `make run-app`, `app/CicadaApp/install_app.sh`, `app/CicadaApp/bundle.sh --run` or `swift run`;
   never launch a built app; never point the app at a bank.** A running Cicada reads the owner's bank. `make app`
   (bundle only, no launch) is allowed. Read the `Makefile` before any `make`.
5. **Never read `memory/`, `~/.cicada` or `~/.claude/projects`.**
6. **Never work in the main checkout** (an auto-updater builds from it). One worktree per parallel run. Never a bare
   `git stash` (the stash stack is shared across worktrees).
7. **Privacy rule** (`CLAUDE.md`) on every word of every prompt, commit, PR and doc: nothing personal, placeholders
   only (`alpha-project`, `bob-example`). The owner's own design words may be quoted. **Copy is provider-neutral.**
8. **Licence: own work.** No third-party artwork or brand marks; stop well short of any existing character's trade dress
   (G127).
9. **Same contract.** Same eight states, same state × response matrix, same tag names, canvases, slices and timing caps
   (§9.5). It is state art: a loop shows only what is already true; it never speeds up, densifies or brightens with a
   count, an age or a stage; no flash or strobe.
10. **The bookworm and the room stay byte-identical.** Every `bookworm-*` and `room-*` file in `$RES`, every `$BW/src`
    and `$BW/parts` file, and their manifest entries are unchanged (proved in Steps 11 and 13). `$BW/preview.html` may
    differ from `$BASE` only in its embedded palette.
11. **Departures are dated spec notes, never chat.** A Codex run raises a departure; it never ships one.
12. **PR against `dev`. Nothing is merged without the owner's yes**, after he has reviewed `preview.html`, the
    composites and the live CPU. Promotion to `main` is his.

### 0.5 Procedure

Each step: the action, the exact command (with its working directory), the **Accept** check that proves it, and any
**STOP**. Do not start a step until the previous step's Accept holds. From Step 3 on, every Bash call begins with
`source <scratchpad>/codex-<character-name>/env.sh && cd "$WT"` (or `cd "$APPWT"`); the blocks below leave it out.

**Step 1. Check the preconditions.** cwd: repository root (the main checkout; read-only apart from the fetch). Fill
`<character-name>` (and `<base-design>`, `<references>`) from the inputs.

```sh
git fetch origin
BASE=$(git rev-parse origin/dev); echo "BASE=$BASE"   # or origin/<the branch the owner names at S0>
git ls-tree --name-only "$BASE" \
  app/CicadaApp/Sources/CicadaApp/Sprites/MascotRegistry.swift \
  app/CicadaApp/Art/sprites/bookworm-2026-10-01/tools/verify_night.py \
  app/CicadaApp/Art/sprites/MAKING_A_MASCOT.md \
  docs/specs/2026-10-02-study-room-scenery.md
ASE="${ASEPRITE:-/Applications/Aseprite.app/Contents/MacOS/aseprite}"; test -x "$ASE" && echo aseprite-ok
"$ASE" --version                      # CLI only, never the GUI; pinned: Aseprite 1.3.18.6-dev
codex --version                       # pinned: codex-cli 0.160.0
python3 -c "from PIL import Image; assert hasattr(Image.Image,'get_flattened_data'); print('pillow-ok')"
node --version; gh --version | head -1
gh auth status 2>&1 | grep -c 'Logged in'
codex login status 2>&1 | grep -c 'Logged in'
codex mcp list                        # every server it shows enabled is named in the §10.5 preamble
test -r <base-design> && echo base-ok; for r in <references>; do test -r "$r" || echo "UNREADABLE $r"; done
echo "<character-name>" | grep -Ex '[a-z][a-z0-9]*(-[a-z0-9]+)*' | grep -Ev '^(bookworm|room|test-skin)(-|$)' \
  | grep -Ev 'small|night' | grep -Ev '(^|-)(dark|lit)(-|$)'
git worktree list | grep -c "<character-name>-" || true
git branch --list "feat/<character-name>-*"
```

- **Accept:** `BASE=` prints a commit id; all four paths print (`git ls-tree` exits 0 even when a path is missing, so
  read the output); `aseprite-ok`; the two pinned version lines exactly; `pillow-ok`; the node and gh versions; both
  `Logged in` counts are ≥ 1; `base-ok` and no `UNREADABLE` line (skip the loop when `<references>` is `none`); the
  name check prints the name; the worktree count prints `0`; the branch list prints nothing. Note `BASE` for Step 3.
- **STOP** if a version differs from its pin: ask the owner. The bookworm's manifest records exactly these versions,
  and another Aseprite may export different bytes, so the bookworm's byte-identity could not be proved.
- **STOP** if the name check prints nothing: ask the owner for another id (§0.1 rules).
- **STOP S0** if a path is missing: G176 (with the registry, this guide and the handoff prompt) is not on the base. Ask
  the owner whether to wait for its PR or to start from another branch (for example `feat/study-room-sprites`); then
  `BASE=$(git rev-parse origin/<that branch>)` and rerun this step. Every `$BASE` check below works unchanged; the PR
  base stays `dev`, and the PR body says it contains G176. Never merge that branch yourself.
- **STOP S0b** if a worktree or branch already exists: a previous session started this character. Ask the owner whether
  to resume. **To resume:** read `.worktrees/<character-name>-sprites/app/CicadaApp/Art/sprites/<character-name>-*/qa/runs-path.txt`,
  `source` the `env.sh` in that folder, `git log` both branches, find the last step whose Accept held, and continue
  from the next one. Resume Codex threads per §10.4. If that folder is gone (the scratchpad was cleared), write a new
  `env.sh` (Step 3's values), and start any further Codex run fresh with a prompt that states what is on disk.

**Step 2. Read, then plan.** Enter plan mode (`EnterPlanMode`). Read, in order: this guide's §0–§5 and §9; `$BW/README.md`;
`docs/specs/2026-10-01-bookworm-sprites-spec.md` §1, §3, §4, §6, §11 (not §10.6); `docs/specs/2026-10-02-study-room-scenery.md`;
`docs/goals/TODO.md` ruling 18 with its dated amendments; the G127 and G176 rows of `docs/goals/memory-evolution.md`;
`CLAUDE.md`, `docs/goals/working-method.md`, `docs/design/DESIGN_RULES.md`; the Mascot paragraphs of
`docs/architecture/app.md` (around lines 488–504 and 533–573). Look at `<base-design>` and every reference yourself.

- **Accept:** a plan naming the phases (Steps 3–16), the worktrees, the Codex runs, and the decisions D1–D14.
- **STOP S1:** present the plan; write nothing until the owner approves it.

**Step 3. Create the art worktree and `env.sh`.** cwd: repository root (`BASE` from Step 1).

```sh
git worktree add -b feat/<character-name>-sprites .worktrees/<character-name>-sprites <BASE commit id>
git -C .worktrees/<character-name>-sprites rev-parse --abbrev-ref HEAD
(cd .worktrees/<character-name>-sprites && pwd)          # the absolute WT for env.sh
mkdir -p <scratchpad>/codex-<character-name>
```

Then write `<scratchpad>/codex-<character-name>/env.sh` (§0.1) with the Write tool, every value absolute.

- **Accept:** prints `feat/<character-name>-sprites`; and
  `source <scratchpad>/codex-<character-name>/env.sh && cd "$WT" && git rev-parse --abbrev-ref HEAD && echo "$ART"`
  prints the branch and an absolute `$ART`. From here on every Bash call starts with that `source … && cd "$WT"`.

**Step 4. Make the art folder; copy and hash the references.** cwd: `$WT`.

```sh
mkdir -p "$ART"/{reference,tracing,parts,src,lua,tools,demo,qa}
printf '*\n!.gitignore\n' > "$ART/qa/.gitignore"
printf '%s\n' "$RUNS" > "$ART/qa/runs-path.txt"          # gitignored; how a resumed session finds RUNS (S0b)
cp <base-design> <references> "$ART/reference/"           # leave <references> out when it is none
shasum -a 256 "$ART"/reference/* > "$RUNS/reference-start.sha256"
cp "$RUNS/reference-start.sha256" "$ART/qa/"
```

- **Accept:** `ls "$ART/reference"` lists every owner file; `wc -l < "$RUNS/reference-start.sha256"` equals that count;
  `cat "$ART/qa/runs-path.txt"` prints `$RUNS`.

**Step 5. Analyse the reference** (§5.1, §5.2). Measure the fitted grid and palette, write the identity list, the
anatomy map, the keep-outs and the budget check as `$SPEC` §0–§1, plus the §2 keep-outs, and render the boards with
Pillow into `$ART/qa/analysis/` (gitignored). `<placement>` pre-answers D2; confirm it at S2.

Tracing, headless (cwd `$ART`): copy `$BW/lua/ase_helpers.lua` and `$BW/lua/trace_reference.lua` into `$ART/lua/`. The
bookworm's script cannot run as copied: it reads `ART/palette.json` (absent in `$ART`), hard-codes
`reference/bookworm.png` and the 70 × 47 / 56 × 38 sizes, quantizes to 12 bookworm keys, and writes
`qa/reference-crop.png` and `qa/ref_*@8x.png`. In the copy, set the palette path to `../bookworm-2026-10-01/palette.json`,
the reference to `reference/<base-design basename>`, and the sizes to your fitted grid; tracing uses the nearest
existing keys until A2 adds the new ones. Then:

```sh
# cwd: $ART
"$ASE" -b --script-param art="$PWD" --script lua/trace_reference.lua   # writes tracing/ref_<w>x<h>.{aseprite,txt}
```

Render `qa/analysis/reference-vs-fit@6x.png` with Pillow from `tracing/ref_<w>x<h>.txt` beside the reference. If D2
includes the menu bar, run the copy again with the menu-head reference and its fitted grid, and render
`qa/analysis/menu-head-fit@8x.png` the same way.

- **Accept:** `grep -c '^## §1\. ' "$SPEC"` prints `1`; `ls "$ART/qa/analysis/reference-vs-fit@6x.png"
  "$ART/qa/analysis/menu-head-fit@8x.png"` succeeds (the second only if D2 includes the menu bar).
- **STOP S2 (checkpoint 1).** Show the owner the measured grid, the reference-vs-first-fit board, the anatomy map, the
  keep-outs and the budget options, and ask every decision marked S2 in §0.6 (D1–D8, D11–D13). Record each answer in `$SPEC` §0 as a dated line
  (`<YYYY-MM-DD>, owner: …`). Append `export CODEX_MODEL=<model> CODEX_EFFORT=<effort>` to `env.sh` from D1. Launch
  nothing before D1 is answered.

**Step 6. Write the spec; commit it with the references** (§5.3). Spawn six reader subagents in parallel (the six
areas in §5.3), one writer subagent, then two critic subagents (code accuracy; scope, art direction and rails). Revise
once yourself.

```sh
# cwd: $WT. Every required tag name must appear in the spec.
for t in idle attentive.left attentive.center attentive.right expectant.left expectant.center expectant.right \
  eager perk.left perk.center perk.right talk.left talk.center talk.right gulp.center shake.left shake.center \
  shake.right cheer.center intro outro 'idle@2' 'idle@3'; do grep -q "\`$t\`" "$SPEC" || echo "MISSING $t"; done
git add "$ART/reference" "$ART/qa/.gitignore" "$SPEC"
git commit -m "docs(sprites): <Display Name> sprite spec and the owner's references (G127)" -m "<the session's commit attribution lines>"
git show --stat --oneline HEAD | head -20
```

- **Accept:** the loop prints nothing; the commit lists the spec and every reference file.
- **STOP S3 (checkpoint 2).** The owner answers the spec's open questions (each has a built default and "one word to
  change"). Each answer becomes a dated note in `$SPEC`; commit it.

**Step 7. Create the app worktree** from the committed spec. cwd: `$WT`.

```sh
git worktree add -b feat/<character-name>-app "$APPWT" feat/<character-name>-sprites
git -C "$APPWT" rev-parse --abbrev-ref HEAD
```

- **Accept:** prints `feat/<character-name>-app`.

**Step 8. Prepare the Codex runs** (§10). Save `run-codex.sh`, `wait-run.sh`, `chain.sh` and `follow.py` from §10.2
into `$RUNS`. Write `$RUNS/common.md` (§10.5) as a **template**: it carries per-run placeholders (`<absolute worktree
path>`, `<the other worktree>`, `<the brief's owned paths>`). `run-codex.sh` takes one prompt file, so for each run
write `$RUNS/<run>.md` = the preamble filled for that run (its own worktree, the other one, its owned paths as
repository-relative paths), followed by its brief: `runA.md` (art, §5.11) and `runC1.md` (app, §9.6). Use the Write
tool or a quoted heredoc (`<<'EOF'`). Then record each worktree's starting commit.

```sh
chmod +x "$RUNS"/*.sh
ls "$RUNS"/{run-codex.sh,wait-run.sh,chain.sh,follow.py,common.md,runA.md,runC1.md}
grep -c -i 'no commit made' "$RUNS/runA.md" "$RUNS/runC1.md"
grep -c 'cua_repl' "$RUNS/runA.md" "$RUNS/runC1.md"
grep -c -E '<(absolute worktree path|the other worktree|the brief|every server|owner-ask|character-name|YYYY-MM-DD)' "$RUNS/runA.md" "$RUNS/runC1.md"
git -C "$WT" rev-parse HEAD > "$RUNS/runA.base"
git -C "$APPWT" rev-parse HEAD > "$RUNS/runC1.base"
```

- **Accept:** all seven files list; the first two counts are ≥ 1 for both prompts (each carries the preamble with the
  headless and no-commit rails); the placeholder count is `0` for both; both `.base` files hold a commit id. Every
  later run (`runA-fix1`, …) gets its own `<run>.md` and `<run>.base` the same way before it launches.

**Step 9. Launch Run A (art) and Run C1 (app) in parallel, detached.** cwd: `$WT`.

```sh
CODEX_WT="$WT" RUNS="$RUNS" CODEX_MODEL="$CODEX_MODEL" CODEX_EFFORT="$CODEX_EFFORT" \
  nohup "$RUNS/run-codex.sh" runA "$RUNS/runA.md" > "$RUNS/runA.nohup.log" 2>&1 & disown
CODEX_WT="$APPWT" RUNS="$RUNS" CODEX_MODEL="$CODEX_MODEL" CODEX_EFFORT="$CODEX_EFFORT" \
  nohup "$RUNS/run-codex.sh" runC1 "$RUNS/runC1.md" > "$RUNS/runC1.nohup.log" 2>&1 & disown
```

- **Accept:** `head -1 "$RUNS/runA/events.jsonl" | python3 -c "import json,sys;print(json.load(sys.stdin)['thread_id'])"`
  prints an id (same for `runC1`). Foreground `sleep` is blocked: wait for the file with a Monitor until-loop,
  `until [ -s "$RUNS/runA/events.jsonl" ]; do sleep 5; done` (and the same for `runC1`).

**Step 10. Follow and wait.** `python3 "$RUNS/follow.py" runA runC1` (run it detached or under a Monitor; §10.3).

- **Accept:** `cat "$RUNS/runA/exit" "$RUNS/runC1/exit"` prints `exit=0` twice. A non-zero exit or `turn.failed`
  means resume (§10.4), never relaunch fresh.

**Step 11. Accept each run yourself, then commit it.** cwd: the run's worktree. `<run>` is the run being accepted
(`runA`, `runA-fix1`, …).

```sh
# Art run (cwd: $WT)
grep -i 'no commit made' "$RUNS/<run>/last.md"
test "$(git rev-parse HEAD)" = "$(cat "$RUNS/<run>.base")" && echo unchanged
git status --short                        # only the paths the brief owns (§5.11)
(cd "$ART" && tools/export_all.sh) 2>&1 | tail -1
(cd "$BW" && tools/export_all.sh) 2>&1 | tail -1
git status --short -- "$RES/bookworm-*" "$RES/room-*" "$BW/src" "$BW/parts"
python3 -c "import json,subprocess;o=json.loads(subprocess.check_output(['git','show','$BASE:app/CicadaApp/Sources/CicadaApp/Resources/sprites/sprites.manifest.json']));n=json.load(open('$RES/sprites.manifest.json'));f=lambda m:{a['id']:a for a in m['assets'] if a['id'].startswith(('bookworm-','room-'))};print(f(o)==f(n))"
```

- **Accept (art run):** the report confirms no commit; `unchanged`; the last line of both exports is
  `sprites: OK (all)`; the second `git status` prints nothing (the bookworm and the room are byte-identical); the
  manifest check prints `True` (every bookworm and room entry equals `$BASE`'s). Then commit the run's paths with the
  attribution lines, citing G127.

```sh
# Run C1 (cwd: $APPWT): only its owned paths changed, and only expected-red tests fail
grep -i 'no commit made' "$RUNS/runC1/last.md"
test "$(git rev-parse HEAD)" = "$(cat "$RUNS/runC1.base")" && echo unchanged
git status --short          # only app/CicadaApp/Sources/CicadaApp/Sprites/MascotRegistry.swift, the three D9 copy
                            # sites and their call sites (Views/Sleep/StudyRoom.swift, Theme/Copy+Welcome.swift
                            # including its welcomeHomeSentences array, Theme/Copy+Settings.swift,
                            # Views/Home/GettingStartedCard.swift, Services/LoginItemService.swift, all under
                            # app/CicadaApp/Sources/CicadaApp/), and app/CicadaApp/Tests/CicadaAppTests/*
(cd app/CicadaApp && swift build 2>&1 | tail -1)
(cd app/CicadaApp && swift test 2>&1 | grep -E "Test Case .*failed|Executed [0-9]+ tests, with [0-9]+ failures" | sort -u)
```

- **Accept (app run):** the build succeeds; every failing test name is on the run's expected-red list (§9.6); nothing
  else changed. Then commit.
- **Reject** (resume the run with the failure, §10.4) if any check fails or the run touched a path its brief does not own.

**Step 12. Review and fix rounds** (§5.12). Render the boards headless, run the five-lens art review and the app code
review, merge them into one fix list, and resume the same Codex session with it. Iterate at least twice on the face,
the prop action (flip and swap) and the z's.

- **Accept:** a fix list file in `$RUNS/` with A/B/C items, each verified against a board; after the fix run, Step 11
  holds again.
- **STOP S4 (checkpoint 3).** The owner sees the contact sheets, comparison boards, menu-bar boards and demo GIFs (they
  live in gitignored `$ART/qa/`: send him each board and GIF with SendUserFile when it is available, otherwise list
  their paths) and picks the next round's scope. Anything that changes his design is held for him.

**Step 13. Integrate and prove determinism.** The fix rounds of Step 12 ran on the separate branches; now merge the
app branch into the art branch. cwd: `$WT`.

```sh
git merge --no-ff feat/<character-name>-app -m "Merge the <Display Name> app branch (G127)" -m "<the session's commit attribution lines>"
(cd "$ART" && tools/export_all.sh && python3 tools/check_rebuild.py record \
  && tools/export_all.sh && python3 tools/check_rebuild.py compare)
(cd "$BW" && tools/export_all.sh && python3 tools/check_scenery_rebuild.py record \
  && tools/export_all.sh && python3 tools/check_scenery_rebuild.py compare)
python3 -c "import json;print(json.load(open('$ART/qa/rebuild.json'))['byteIdentical'], json.load(open('$BW/qa/scenery-rebuild.json'))['byteIdentical'])"
git status --short -- "$RES" "$ART" "$BW"            # both pipelines reproduce the committed bytes
python3 -c "import json,subprocess;o=json.loads(subprocess.check_output(['git','show','$BASE:app/CicadaApp/Sources/CicadaApp/Resources/sprites/sprites.manifest.json']));n=json.load(open('$RES/sprites.manifest.json'));f=lambda m:{a['id']:a for a in m['assets'] if a['id'].startswith(('bookworm-','room-'))};print(f(o)==f(n))"
(cd app/CicadaApp && swift build 2>&1 | tail -1)
(cd app/CicadaApp && swift test 2>&1 | grep -E 'Executed [0-9]+ tests, with [0-9]+ failures' | tail -1)
(cd app/CicadaApp && swift test 2>&1 | grep -E 'Executed [0-9]+ tests, with [0-9]+ failures' | tail -1)
(cd app/CicadaApp && CICADA_WRITE_COMPOSITES=1 swift test --filter 'WindowSpritesTests|MascotSettingsTests|ScenerySettingsTests|SpriteClipTests' 2>&1 \
  | grep -E 'Room redraw maximum|Executed [0-9]+ tests, with [0-9]+ failures')
```

- **Accept:** `True True`; the `git status` prints nothing; the manifest check prints `True`; the build succeeds; both
  `swift test` lines read `with 0 failures` (note both counts); one `Room redraw maximum` line per mascot, each
  ≤ 1,800. The looped composites are named `<mascot.id>-<weatherTag>-<mood>-<lit|dark>-<scale>.png` under
  `$TMPDIR/cicada-sprite-composites/` (480 per skin), so build Pillow montages per time × lamp into
  `$ART/qa/composites/` and look at every montage, plus every key frame at 6×, every Mascot pane
  (`settings/mascot-<choice>-<scheme>.png`) and every scenery pane (`settings/<mode>-<scheme>-<id>.png`) that shows
  `<character-name>`.
- **If `swift test` fails after the merge,** resume Run C1's thread with `CODEX_WT` = the art worktree (`$WT`), naming
  the run `runC2`. Art fixes resume Run A's thread in the same worktree. Never run two Codex sessions in one worktree at
  once. Accept the run (Step 11), then redo Step 13 from the rebuilds.

**Step 14. Update the docs in the same branch** (§5.14). Then check privacy and machine paths.

```sh
git diff --stat "$BASE" -- docs/ "$ART/README.md"
git diff "$BASE" -- . ':(exclude)*.png' ':(exclude)*.aseprite' | grep -n -E '^\+.*(/Users/|/private/|/home/)' \
  | grep -v -E "not in|contains\(" || echo clean
```

- **Accept:** the stat lists `docs/architecture/app.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md` and
  `$SPEC`; the grep prints `clean`. If `CLAUDE.md` changed, also run
  `PYTHONDONTWRITEBYTECODE=1 api/.venv/bin/python -m pytest api/tests/test_claude_md_size.py -q -p no:cacheprovider`
  (run `(cd api && uv sync)` first in a fresh worktree) and expect `2 passed`.

**Step 15. Open the PR against `dev`.** First write `$RUNS/pr-body.md` with the Write tool: the summary, G127, the
owner's dated decisions D1–D14, the departures, both test counts, both `byteIdentical` results, what still needs the
owner, then the session's PR attribution lines. If `BASE` is not `origin/dev`, say that the PR contains G176. Run the
privacy and machine-path check on it: `grep -n -E '/Users/|/private/|/home/' "$RUNS/pr-body.md" || echo clean`, and
read every line against the privacy rule.

```sh
git push -u origin feat/<character-name>-sprites
gh pr create --base dev --head feat/<character-name>-sprites --title "<Display Name>: a second mascot (G127)" --body-file "$RUNS/pr-body.md"
gh pr view --json baseRefName -q .baseRefName
```

- **Accept:** prints `dev`. The body is privacy-clean, cites G127, lists the owner's dated decisions and ends with the
  session's PR attribution lines.
- **STOP S5 (the merge gate).** The owner opens `$ART/preview.html` himself (a browser tool cannot load `file://`),
  reviews the composites, and measures live CPU on the demo bank. Never merge.

**Step 16. Report** to the owner (the list in §0.8's last box).

### 0.6 Decision points (ask at the STOP named; build the default unless the owner changes it)

| ID | Question | Default to build | Ask at |
|---|---|---|---|
| D1 | Which Codex model and effort draw `<character-name>`? | The bookworm's model (`gpt-6.1-sol`, effort `xhigh`) was R-BW12's choice for the bookworm only, so it is a suggestion, not a default: launch nothing until he answers. Record it as a dated spec line and in `env.sh`. If the owner wants a tool other than Codex, STOP: §10, `manifest.py`'s `authoring` field and Steps 8–12 must be rewritten first. | S2 |
| D2 | Does it appear in the menu bar? (`<placement>` pre-answers it.) | **Yes (`room+menu`): build `<character-name>-small`.** The registry requires a `menuBarSheet`, and the selected mascot's 18 × 18 set is also what Home (24 pt), Getting started (24 pt) and Contributors draw. Alternative (`room`): point `menuBarSheet` at `bookworm-small` (the bookworm head shows in the menu bar while `<character-name>` is selected); then 24 new sheets and entries (`ls "$RES"/<character-name>-*.png \| wc -l` → 24, `ls "$RES"/*.png \| wc -l` → 60, manifest 60), and Run C1 makes `SpriteTestAssets.sheetNames` order-preserving unique (`SpriteTestAssets.swift:18` would list `bookworm-small` twice, failing `SpriteAssetTests.testManifestListsEveryBundledFileAndAllScenerySheets`'s `names.count == sheetNames.count * 2`). Every 25 / 61 in the checklists becomes 24 / 60. Alternative (`menu`): ask whether room sheets are wanted at all; the registry and its tests require all 24. | S2 |
| D3 | Palette: fit into the shared `$BW/palette.json` or a per-character palette? | **Shared.** Reuse the shared mark keys (`K` outline, `W` white, `j` lid, `r` mouth, `S` sweat, `Z Y X` z's, `q Q` sparkle, the book keys) and spend at most the 6 free keys (`] ^ e { } ~`) on identity colours, each with a 7-band night ramp and dusk/night pane tints (§7.5), in group `worm` with roles `worm.<character-name>.<part>` (the X-eye check needs the gap pixels to carry a `worm.*` role). If it needs more than 6: STOP; a per-character palette needs an owner-dated R-BW2 amendment ("One `palette.json` is read by the scripts and the tests") and generalised `SpriteAssetTests` and verifiers. | S2 |
| D4 | The decoded-pixel cap (8,388,608) cannot hold a second full set: bookworm + room use 6,151,414, a bookworm-sized set adds about 5.22 M. Which way? | **Per-mascot cap:** the room plus any one mascot's 25 sheets ≤ 8,388,608 (room 927,058 + bookworm 5,224,356 = 6,151,414 passes; the new set may use up to 7,461,550). Sheets load lazily per name, so a viewer pays for the mascot they selected (and the cache keeps both after a switch until relaunch; say so). Change `$BW/tools/verify_room.py:224-225`, the new `verify.py`, and `BookwormLookRendererTests.testDecodedPixelsAndDistinctRoomRectsStayBounded` in the same PR, recorded as a dated R-BW3 amendment. One word changes it: `raise` (total cap 16,777,216) or `pack` (fit the new set into the 2,237,194 px headroom, about 43 % of the bookworm's sheet area). | S2 |
| D5 | What is its reading prop (the bookworm's book)? | **A held book with the same three covers, the same `book.*` keys and roles and the same flip, close, swap and open**, so the book mark checks apply unchanged. Alternative: an equivalent prop with its own role and ≥ 20 px in every room frame (the tests that count `book.*` change in the same PR). | S2 |
| D6 | The anatomy map: what stands in for glasses and lenses, plus pupils, floating brows, mouth, tail, neck? | **Keep every code-facing name** (`eye`, `lensL`, `lensR`, `errorLensL` mean "the eye region left/right", `D`/`L` lens roles only if it wears glasses) and write a table bookworm element → character element (§5.1). If it has no glasses, the glasses-count checks are replaced by an equivalent identity-mark check named in the spec. | S2 |
| D7 | Where is the curious `?` on the canvas? | **The same box, (45, 16, 4, 9)**, so `palette.json`'s `night.glyphs.question` and `night_palette.py`'s assert (`$BW/tools/night_palette.py:19`) hold. If its anatomy needs another place, add a second glyph entry and teach `night_palette.py` and `build_mascot_night.lua`; then add `$BW/tools/night_palette.py` to Run A's owned paths (§5.11) and prove the bookworm export byte-identical. | S2 |
| D8 | Frame counts and timings | **The bookworm's exact holds** (§6), so the independent timing transcription carries over. Any change is a dated spec note, stays inside the caps (§6.2.5) and inside the redraw budget per state (§8.13). | S2 |
| D9 | Three strings name the bookworm: `StudyRoom.swift:317` (`"Bookworm, \(mood.title)"`, VoiceOver), `Copy+Welcome.swift:74` ("…The bookworm keeps reading."), `Copy+Settings.swift:39` ("…just the bookworm in the menu bar."). | **VoiceOver uses `"\(mascot.displayName), \(mood.title)"`** (unchanged for Bookworm); `WormHotspot` reads the mascot through `@AppStorage(MascotPreference.defaultsKey)` + `MascotRegistry.resolve`. The two prose strings take the selected mascot's name through a `Copy` function that returns today's exact text for Bookworm, and their call sites change with them (`GettingStartedCard.swift:339`, the `welcomeHomeSentences` array at `Copy+Welcome.swift:159`, `LoginItemService.swift:50`; §0.3 row 13). Ask the owner for `<character-name>`'s wording. | S3 |
| D10 | Tile order and default | **`all = [bookworm, <character-name>]`.** Bookworm stays the default and the fallback for unknown ids. | S3 |
| D11 | Error look | **Black X eyes plus the sweat drop, no red** (the owner's 2026-10-01 rule for the bookworm). | S2 |
| D12 | Menu-bar outlines | **Dark outlines on both menu-bar appearances, no variant** (the owner's 2026-10-01 rule). | S2 |
| D13 | The headless rule is not yet in ruling 18. | **Ask the owner to date an R-BW12 amendment:** "Dated owner amendment, <YYYY-MM-DD>: sprites are authored headless (`aseprite -b --script`); no run opens, attaches to or shares the owner's Aseprite; computer use in Aseprite is retired; a GUI session needs his approval per run after he quits Aseprite." | S2 |
| D14 | `brows.mad` and the demo GIFs | **Skip `mad`** (no tag uses it; the bookworm's is demo-only). Build the reading-cycle demo GIF. | S3 |

### 0.7 Deliverables checklist

- [ ] `$ART/reference/` unchanged: `shasum -a 256 -c "$RUNS/reference-start.sha256"` passes at the end.
- [ ] `$SPEC` with every tag as an exact table, every dated owner decision and every departure.
- [ ] `$ART/parts/*` as the pixel authority; a recorded correction (`lua/fix_<topic>.lua`, or `lua/gui_*.lua` from an approved GUI session) for every change after seeding.
- [ ] 8 day sheets `<character-name>-<state>` with the exact tag sets (122 tags: awake 18, hungry 18, happy 19, reading 54, digesting 7, sleeping 4, error 1, curious 1) and slices `ink`, `eye`, `lensL`, `lensR` (+ `errorLensL` on error).
- [ ] 16 night sheets, each an exact relight of its day sheet (same tags, frames, ms, slices, alpha mask).
- [ ] `<character-name>-small` with 8 tags (if D2 includes the menu bar).
- [ ] `$ART/day-art-contract.json` freezing the day art.
- [ ] 25 manifest entries (24 if D2 = `room`) with real `generator`, `authoring` (the D1 model, "headless"), `date` and hashes, all constants in `tools/character.py`; no machine paths.
- [ ] `$BW/palette.json` additions with ramps and pane tints (D3), and the prefix-aware patch to three `$BW/tools` files; the bookworm's manifest entries unchanged.
- [ ] `$ART/preview.html` (every tag at real timing, in the shared room) and `node "$ART/tools/check_preview.mjs"` green.
- [ ] `$ART/README.md`, `$ART/TAG_TIMINGS.md`, run reports, `$ART/demo/<character-name>-reading-cycle@6x.gif`.
- [ ] Registry entry; Settings tile renders (`MascotSettingsTests` panes); copy per D9.
- [ ] Tests: catalog updated; default-skin tests looped over `MascotRegistry.all`; budget tests per D4.
- [ ] Docs updated; PR against `dev`; the owner's yes before merge.

### 0.8 Acceptance checklist (each line is a command or a file)

- [ ] `(cd "$ART" && tools/export_all.sh) | tail -1` → `sprites: OK (all)`.
- [ ] `(cd "$BW" && tools/export_all.sh) | tail -1` → `sprites: OK (all)`.
- [ ] `ls "$RES"/<character-name>-*.png | wc -l` → `25`; `ls "$RES"/*.png | wc -l` → `61` (24 and 60 if D2 = `room`).
- [ ] `python3 -c "import json;print(len(json.load(open('$RES/sprites.manifest.json'))['assets']))"` → `61` (60 if D2 = `room`).
- [ ] `git diff --quiet "$BASE" -- "$RES"/bookworm-* "$RES"/room-* "$BW/src" "$BW/parts" && echo same` → `same`.
- [ ] Step 11's manifest check (every `bookworm-*` and `room-*` entry equals `$BASE`'s) → `True`.
- [ ] `$ART/qa/rebuild.json` and `$BW/qa/scenery-rebuild.json` both have `"byteIdentical": true`, and after both
      rebuilds `git status --short -- "$RES" "$ART" "$BW"` prints nothing.
- [ ] `node "$ART/tools/check_preview.mjs"` and `node "$BW/tools/check_preview.mjs"` exit 0.
- [ ] `(cd app/CicadaApp && swift test --filter 'MascotRegistryTests|MascotSettingsTests|ScenerySettingsTests|SpriteAssetTests|BookwormLookRendererTests|RoomClockTests|RoomClockSpriteTests|BookwormRendererTests|NightWormSpriteTests|RoomSpriteTests|BookwormArtTests|BookwormSpriteTests|BookwormPoseSpriteTests|BookwormStateTests|WindowSpritesTests|SpriteClipTests|DeskSceneLayoutTests|DeskHotspotTests|BookwormFramesBenchmarkTests|SleepNumbersLintTests' 2>&1 | grep -E 'Executed [0-9]+ tests, with [0-9]+ failures' | tail -1)` → `with 0 failures`.
- [ ] `(cd app/CicadaApp && swift test 2>&1 | grep -E 'Executed [0-9]+ tests, with [0-9]+ failures' | tail -1)` twice → `with 0 failures` both times; report both counts.
- [ ] `(cd app/CicadaApp && CICADA_WRITE_COMPOSITES=1 swift test --filter SpriteClipTests 2>&1 | grep 'Room redraw maximum')`
      → one line per mascot (once looped), each ≤ 1,800: the worst redraws per minute for the report.
- [ ] Every composite montage, key frame, Mascot pane and scenery pane showing `<character-name>` has been opened and looked at.
- [ ] `shasum -a 256 -c "$RUNS/reference-start.sha256"` → every line `OK`.
- [ ] `gh pr view --json baseRefName -q .baseRefName` → `dev`.
- [ ] The final report to the owner: the PR link; sheet, tag and frame counts; what was hand-tuned; what is still
      rough; every departure with its dated note; held items; both test counts; the worst redraws per minute (the
      `Room redraw maximum` lines); the commands to rebuild (`(cd "$ART" && tools/export_all.sh)`) and to open the
      preview (`open "$ART/preview.html"` is his to run).

---

## 1. What binds

Highest first. When two disagree, the higher one wins; record the conflict as a dated spec note.

1. **The owner's dated decisions.** `docs/goals/TODO.md` ruling 18 (R-BW1–R-BW12) and its dated amendments
   (2026-10-01 black X eyes and one menu sheet; 2026-10-02 Settings and the weather gate; 2026-10-02 timing; 2026-10-02
   wall clock; 2026-10-02 mascot selector), plus the dated notes in each spec.
   - **The headless rule (owner, 2026-10-02).** Recorded in `docs/specs/2026-10-02-study-room-sprites-finish-handoff.md`,
     "Rails and next step for the orchestrator": "No Aseprite GUI or computer use during integration: art fixes go into
     saved parts/scripts". This guide applies it to all authoring. It supersedes R-BW12's "with computer use in
     Aseprite" and the bookworm spec's §0, §3.1 parts row, §9 briefs and §10.6. Never copy those into a new spec or
     prompt. It is not yet in ruling 18: decision D13 asks the owner to date the amendment.
   - **The mascot amendment (owner, 2026-10-02):** "Another character will have its own base and the same
     pipeline/tag/canvas contract, plus one entry and manifest files; no state change."
2. **The scenery contract**, `docs/specs/2026-10-02-study-room-scenery.md`. It supersedes the old mood-only skies in the
   bookworm spec §5.1–5.2.
3. **The bookworm spec**, `docs/specs/2026-10-01-bookworm-sprites-spec.md`, as the template for rigour: §1 reference
   analysis, §3 tag tables, §4 state mapping, §6 pipeline, §7 app integration, §10.1–10.5 Aseprite cheat sheet and
   helper library (not §10.6), §11 open questions.
4. **This guide.**
5. `CLAUDE.md`, `docs/goals/working-method.md` and `docs/design/DESIGN_RULES.md`. Their rails apply throughout.

---

## 2. Prerequisites

| Need | Check (cwd: any) | Notes |
|---|---|---|
| Aseprite at `/Applications/Aseprite.app` | `test -x "$ASE" && echo ok`; `"$ASE" --version` → `Aseprite 1.3.18.6-dev` (pinned, Step 1) | 1.3.18.6-dev made the bookworm. `aseprite --version` and `-b` runs are CLI-only and allowed (`$BW/tools/manifest.py:13` runs `--version` on every export). Never start the GUI. `ASEPRITE` overrides the path. |
| Python 3 with Pillow that has `Image.get_flattened_data` | `python3 -c "from PIL import Image; print(hasattr(Image.Image,'get_flattened_data'))"` → `True` | 12.3.0 here. |
| Node | `node --version` | For `check_preview.mjs`. |
| Codex CLI on `PATH`, logged in | `codex --version` → `codex-cli 0.160.0` (pinned, Step 1); `codex login status` → `Logged in …` | Only for authoring; nothing at build time calls it. The bookworm's authoring provenance is static data in `$BW/authoring-provenance.json` (per family: day, night, scenery). |
| GitHub CLI, logged in | `gh --version`; `gh auth status` → `Logged in …` | For the PR. |
| `$BASE` (`origin/dev`) holds finished G176 with the registry, this guide and the handoff prompt | Step 1 | Otherwise STOP S0. |
| `api/.venv` (only if `CLAUDE.md` changes) | `test -x api/.venv/bin/python` | A new worktree has none (gitignored): `(cd api && uv sync)`. |

---

## 3. Folder layout

The new folder mirrors the bookworm's, minus the room (the room stays in `$BW`).

```
app/CicadaApp/Art/sprites/<character-name>-<YYYY-MM-DD>/
  reference/     the owner's originals; read-only; hashed at the start and the end
  tracing/       palette-quantized tracing bases on hidden layers (trace_reference.lua); never exported
  parts/         <character-name>-parts.aseprite (64×48), <character-name>-small-parts.aseprite (18×18): the pixel authority
  src/           builder output: 8 day + 16 night + 1 small .aseprite; committed; never hand-edited
  lua/           character.lua, helpers, builders, script table, relight, seed-once scripts, fix_* records
  tools/         character.py, export_all.sh, verify*.py, manifest.py, make_preview.py, review/report/rebuild tools
  demo/          GIFs for people; never bundled
  qa/            gitignored (`*` and `!.gitignore`) but holds qa/registry.json, which the verifiers read
  day-art-contract.json   preview.html   README.md   TAG_TIMINGS.md   <RUN>_REPORT.md   FILE_INVENTORY.txt
```

| File | Written by | Hand-edit? |
|---|---|---|
| `reference/*` | the owner | Never. |
| `parts/*.aseprite` | `seed_parts.lua` once, then recorded corrections | **Only here**, and only through a recorded correction: a headless `lua/fix_<topic>.lua` by default; a `lua/gui_*.lua` record only in an owner-approved GUI session (§10.6). |
| `src/*.aseprite` | the builders | Never. |
| `$RES/<character-name>-*.{png,json}` | the CLI export in `tools/export_all.sh` | Never. |
| `qa/registry.json` | the builders | Never. |
| `day-art-contract.json` | `tools/day_art_contract.py` | Never. |
| `preview.html`, `TAG_TIMINGS.md`, `FILE_INVENTORY.txt` | the tools | Never. |
| `$BW/palette.json` (shared) | by hand, from the spec | Yes, D3 only; the verifiers check it. |

**A fresh checkout has no `qa/` registries.** Run the folder's `tools/export_all.sh` before any verifier.

---

## 4. The pipeline

### 4.1 The flow

**parts** (hand-corrected `.aseprite`) → **builders** (Lua: compose the parts with the script table, add tags and
slices, assert the palette) → **`src/*.aseprite`** → **relight** (16 night sources from the saved day sources) →
**CLI export** to `$RES` PNG + JSON → **manifest** → **verify** → **preview**.

### 4.2 The bookworm's commands (cwd: `$BW`)

```sh
ASE="${ASEPRITE:-/Applications/Aseprite.app/Contents/MacOS/aseprite}"   # aseprite is not on PATH

# Full delivery, then the determinism proof
tools/export_all.sh                                   # last line: sprites: OK (all)
node tools/check_preview.mjs
python3 tools/check_scenery_rebuild.py record         # "First complete export recorded: N files"
tools/export_all.sh
python3 tools/check_scenery_rebuild.py compare        # writes qa/scenery-rebuild.json with "byteIdentical"

# Worm only (leaves the night sheets stale; rerun STAGE=all after any day-art change)
BUILDS="build_worm build_worm_small" STAGE=worm tools/export_all.sh
python3 tools/make_review.py
python3 tools/make_report.py                          # TAG_TIMINGS.md, FILE_INVENTORY.txt
python3 tools/make_scenery_review.py
python3 tools/make_integration_review.py             # after the Swift composites (quickstart Step 13)

# Helper self-test; prints "helpers: every public helper and additions passed"
"$ASE" -b --script-param art="$PWD" --script lua/test_helpers.lua

# Dev loop: rebuild one sheet headless, then look at rendered files (never the GUI)
"$ASE" -b --script-param art="$PWD" --script-param build=lua/build_worm.lua \
  --script-param result=src/bookworm-awake.aseprite --script-param tag=idle --script lua/dev_loop.lua
"$ASE" -b src/bookworm-awake.aseprite --tag idle --scale 6 --save-as qa/dev-awake-idle.gif
```

### 4.3 What `export_all.sh` does (read the script, not spec §6.1, which is older)

- **Environment.** `ASEPRITE` (binary), `BUILDS` (default every builder:
  `build_worm build_worm_small build_room build_clock build_weather build_skyfx build_spines`), `STAGE` (`all` or `worm`).
- **Paths.** `ART` is the script's parent folder; `RES` is `$ART/../../../Sources/CicadaApp/Resources/sprites`.
1. **Builds.** For each build, `run_lua <name>` removes `qa/.lua-completed`, runs
   `"$ASE" -b --script-param art="$ART" --script-param run="$script" --script-param status="$status" --script lua/run_checked.lua`,
   and fails with `Lua did not complete: <name>` unless the marker holds `completed`.
2. **Room checks and relight** (`STAGE=all` only): `check_room_parts`, then `build_night`.
3. **Export.** For each `src/*.aseprite` (with `STAGE=worm`, only `bookworm-*`): delete the old outputs, then
   `"$ASE" -b "$src" --sheet "$RES/$name.png" --data "$RES/$name.json" --format json-array --sheet-pack --list-tags --list-slices`;
   both outputs must exist and be non-empty.
4. **Post-processing.** `STAGE=all`: `manifest.py` → `verify.py` → `make_preview.py` (the manifest runs before verify
   because `verify_room` checks its hashes). `STAGE=worm`: `verify.py --worm-only`.
5. Prints `sprites: OK ($STAGE)`.

### 4.4 Build-order dependencies

- **`build_worm` before `build_worm_small`.** The small builder reads `qa/registry.json` without a guard.
- **`build_weather` before `build_skyfx`.** Skyfx appends 6 tags to `room-motion.json`.
- **`build_night` is not idempotent for the room.** It edits the six room sources in place; run twice without
  `build_room` in between and you get duplicate frames and tags. With `STAGE=all`, `BUILDS` must include `build_room`.
- **`build_night`, `build_clock` and `build_skyfx` assert `app.params.art`.** Always pass `--script-param art="$PWD"`.
- **`STAGE=worm` leaves the night sheets stale.** After any day-art change, run `STAGE=all`.

### 4.5 Determinism (a merge condition)

- **Within a run:** every verifier re-exports each source into a `qa/` temp folder and requires byte-identical PNG and
  JSON.
- **Across runs:** run the full pipeline twice, `record` before and `compare` after (§4.2).
- **Preconditions:** `--sheet-pack`, never `--trim`; CLI export only, never File > Export; durations set as
  `(ms+0.5)/1000`; `meta.image` is a basename (no machine path); saved `.aseprite` files are rewritten on every run
  and must themselves be byte-stable.
- **The bookworm's evidence:** Run A 22 files, Run B 52/52, worm fix 162 files, the final integration 119 files: all
  byte-identical. That is what proves no GUI accident leaked into the art.

### 4.6 The new character's own pipeline (what to copy into `$ART`, and what to change)

Set the name in exactly one place per language and read it everywhere:

```lua
-- $ART/lua/character.lua
return { name = '<character-name>', prefix = '<character-name>-', bw = '../bookworm-2026-10-01' }
```

```python
# $ART/tools/character.py
from pathlib import Path
ART = Path(__file__).resolve().parent.parent
BW = ART.parent / 'bookworm-2026-10-01'
RES = ART.parents[2] / 'Sources/CicadaApp/Resources/sprites'
NAME = '<character-name>'
PREFIX = NAME + '-'
PALETTE = BW / 'palette.json'          # D3 default: the shared palette
STATES = ['awake', 'sleeping', 'digesting', 'happy', 'curious', 'hungry', 'reading', 'error']
DAY = [PREFIX + s for s in STATES]
NIGHT = [f'{PREFIX}{s}-night-{l}' for s in STATES for l in ('dark', 'lit')]
SMALL = PREFIX + 'small'                 # D2 = room: no SMALL in OWN (the menu sheet is bookworm-small)
OWN = set(DAY) | set(NIGHT) | {SMALL}
# Manifest provenance: constants, recorded when Run A first exports; never date.today() or a live --version
DATE = '<YYYY-MM-DD>'
GENERATOR = 'Aseprite 1.3.18.6-dev'      # what "$ASE" --version printed
AUTHORING = 'codex-cli 0.160.0'          # what codex --version printed
```

| Copy from `$BW` | To `$ART` | Change |
|---|---|---|
| `lua/ase_helpers.lua`, `lua/run_checked.lua`, `lua/test_helpers.lua` | same names | Verbatim. Mind the `ase_helpers` quirk (§12). |
| `lua/dev_loop.lua` | same | Delete its header line "Then: open -a Aseprite …" (forbidden by the rails). |
| `lua/trace_reference.lua`, `lua/seed_parts.lua`, `lua/error_eyes.lua` | same | Patterns: rename parts and sheets through `character.lua`. |
| `lua/worm_scripts.lua` | `lua/mascot_scripts.lua` | The script table pattern (§5.4); part names from the anatomy map. |
| `lua/build_worm.lua`, `lua/build_worm_small.lua` | `lua/build_mascot.lua`, `lua/build_mascot_small.lua` | Sheet names from `character.lua`; palette from `$BW/palette.json`. |
| `lua/build_night.lua`, **worm half only**: lines 1–33 (palette, ramps, `relight`, `plan`) and lines 67–90 (`for _,state in ipairs…`) | `lua/build_mascot_night.lua` | Read `palette.json`, `room-light-map.json` and `room-plan.json` from `$BW`; prefix from `character.lua`; the `?` box per D7. **Never copy lines 34–66**: they relight the six room sources in place. |
| `tools/export_all.sh` | same | `BUILDS` default `build_mascot build_mascot_small`; always run `build_mascot_night` after them; export only `src/<character-name>-*.aseprite`; then `manifest.py` → `verify.py` → `make_preview.py`; no room builders. |
| `tools/verify.py` | same | `EXPECTED` keyed by `PREFIX`; the independent timing transcription (`IDLE_MS`, `READ_BLOCKS`, `POSE_MS`, `SMALL_MS`) from your spec; marks per D6; plus ports of `verify_room`'s ruling-9 worm mask (lines ~130–150) and `verify_clock.py`'s clearance for this character's 24 sheets; budgets per D4. |
| `tools/night_palette.py` | do not copy | Import it from `$BW/tools` (`sys.path.insert(0, str(BW / 'tools'))`): it reads the shared `$BW/palette.json`. |
| `tools/verify_night.py` | same | `NIGHT` from `character.py`; check only this character's 16 sheets; `day-art-contract.json` from `$ART`. |
| `tools/manifest.py` | same | Writes **only `OWN` ids** and merges (§4.7 rule). `date`, `generator` and `authoring` are constants in `tools/character.py` (`DATE='<YYYY-MM-DD>'`, plus the two version strings recorded when Run A first exports), never `date.today()` or a live `--version`, so a rebuild on another day or after a tool upgrade writes the same bytes. `generator` = `GENERATOR + ', headless (-b), from saved Aseprite sources and Lua'`; `authoring` = `AUTHORING + ' (<model>, <effort> effort); headless in Aseprite, from the owner's reference'` (never "computer use"); `script`/`source` relative to `$ART` (`lua/build_mascot.lua`, `src/<id>.aseprite`); `reference` = `reference/<file> <sha256>`. Serialize exactly as `$BW/tools/manifest.py:42`: `json.dumps(data, indent=1, ensure_ascii=False) + '\n'`, entries sorted by PNG file name, the `note` read from the file. |
| `tools/make_preview.py`, `tools/preview_template.html`, `tools/check_preview.mjs` | same | Show this character in the shared room (room sheets read from `$RES`); expected sheet set = `OWN` + the 11 `room-*`. |
| `tools/make_review.py`, `tools/make_report.py` | same | Prefix from `character.py`. |
| `tools/check_scenery_rebuild.py` | `tools/check_rebuild.py` | Snapshot `$ART/src/*`, `$ART/parts/*`, `$RES/<character-name>-*`, `$RES/sprites.manifest.json`, `$ART/day-art-contract.json`, `$ART/preview.html`; write `qa/rebuild.json` with `byteIdentical`. |
| — (new) | `tools/day_art_contract.py` | Writes `day-art-contract.json` (`dayTagsSha256`, `pngSha256`, `jsonSha256`, `tags` per day sheet and the small sheet), like `$BW/day-art-contract.json`; the bookworm has no generator for it. Run by hand, never by `export_all.sh`: by Run A once A3's day sheets pass `verify.py` (before A4), and again in every fix round that changes day art, committed with that round. Otherwise `verify_night.py` fails "day art/timing unchanged" (`$BW/tools/verify_night.py:42`). |

Do not copy `check_wormfix_rebuild.py` (stale, §12) or any `gui_*.lua`.

### 4.7 The prefix-aware patch to the bookworm's tools (required before any new sheet lands in `$RES`)

The bookworm's tools assume they own all of `$RES`. Three files must learn to leave other mascots' entries alone. The
patch must not change a single byte of any bookworm or room output.

| File:line (at `e0c21b45`) | Today | Change |
|---|---|---|
| `$BW/tools/manifest.py:16-40` | Rewrites the whole manifest from `sorted(RES.glob('*.png'))`; any name not starting `bookworm-` gets role `room`; asserts the id set equals bookworm + room. Builds `generator` live from `aseprite --version` (the one tool a rebuild needs) and `authoring` from the static `$BW/authoring-provenance.json` (family by sheet: day, night, scenery), so rebuilding never needs the Codex CLI; an Aseprite upgrade still rewrites every entry's `generator`. | Build entries only for its own ids (bookworm + the room contract); read the existing manifest and keep every other entry unchanged; **keep every existing own entry byte-for-byte (including `generator` and `authoring`) when that entry's `pngSha256` and `jsonSha256` are unchanged**; write all entries **ordered by PNG file name** with `json.dumps(data, indent=1, ensure_ascii=False) + '\n'` (today's rule, so a bookworm-only manifest stays byte-identical); keep the `note` already in the file; keep the equality assertion for its own ids only. |
| `$BW/tools/verify_room.py:65-67` | `complete PNG coverage` / `complete JSON coverage`: `$RES` stems must equal bookworm + room exactly. | Own set ⊆ `$RES` stems, and every other stem has a manifest entry. |
| `$BW/tools/verify_room.py:211-220` | `manifest complete coverage` (exact), and every entry's `source`/`script` must exist under `$BW`. | Own ids ⊆ manifest ids, every manifest id has both files; run the provenance and hash checks on every entry, but the `source`/`script` existence check only on own entries (others are checked by their own folder's verifier). |
| `$BW/tools/verify_room.py:224-225` | `decoded<=8388608` over every PNG in `$RES`. | Per D4 (default: room + bookworm ≤ 8,388,608; each other mascot is checked by its own verifier as room + itself). |
| `$BW/tools/make_preview.py:8` | Embeds every JSON in `$RES`, so `check_preview.mjs:39`'s exact set breaks. | Embed only bookworm + room sheets. (Line 9 also embeds `palette.json`, so once A2 adds keys every bookworm export rewrites `$BW/preview.html`: it may differ from `$BASE` only in the embedded palette, and Run A owns it, §5.11.) |

The manifest `note` is edited once, by hand, to name every art folder, in the commit that adds the new entries.

- **Accept (before new sheets exist):** `(cd "$BW" && tools/export_all.sh)` twice with `check_scenery_rebuild.py`
  `byteIdentical: true`, and `git diff --quiet "$BASE" -- "$RES" "$BW/src" "$BW/parts" && echo same` → `same`.
- **Accept (after the new sheets exist):** the bookworm export still ends `sprites: OK (all)`;
  `git diff --quiet "$BASE" -- "$RES"/bookworm-* "$RES"/room-* "$BW/src" "$BW/parts" && echo same` → `same`; and
  Step 11's manifest check prints `True` (the bookworm's and the room's entries equal `$BASE`'s).

Untouched on purpose: `$BW/tools/export_all.sh` (it exports only `$BW/src`), `verify.py` and `verify_night.py` (they
check bookworm names; `verify_night`'s "unexpected night tag" scan accepts other sheets because their tags are the day
names), `verify_clock.py` (bookworm names; the new character has its own port).

---

## 5. From base design to shipped character

Steps 5.1–5.3 are the orchestrator's (Claude); 5.4–5.10 are Run A's art work (Codex), specified in the spec and
checked by the verifiers; 5.11 is Run A's brief; 5.12–5.14 close the loop.

### 5.1 Reference analysis (quickstart Step 5)

- **Treat the references as AI renders on a loose grid, not pixel art.** Fit the grid (the bookworm's base was a fitted
  70 × 47; its menu-bar head about 20 × 16 cells at about 39 px per cell, spec §1.7). Take each colour as the median of
  that colour's interior; emotion files drift brighter, so snap them to the base.
- **A room-scale starting point is only a start.** The bookworm's 4/5 downsample to 56 × 38 "needs a full hand
  cleanup". The canvas is 64 × 48 with the base row at 47: leave headroom for a 3-px lift, the prop, the z box
  (cols 40–63 × rows 0–14) and the keep-outs (§5.10).
- **Tracing.** Write palette-quantized tracing bases to `$ART/tracing/` with `trace_reference.lua`, headless, on
  hidden layers only.
- **The 18 × 18 head is redrawn, never downsampled** (owner rule). If the design does not fit, shorten the least
  identity-bearing parts first (the bookworm lost temple and tail length); never shrink the identity features (for the
  bookworm, the lenses and pupils).
- **The identity list** names what makes the character recognisable (bookworm: big round lenses, plus pupils, floating
  brows, the book, a lime body with a shadow band). It becomes the state marks, the fidelity lens of the review and the
  verifier's pixel tests.
- **The anatomy map** (D6): one row per bookworm element, its `<character-name>` equivalent, and the code-facing name
  it keeps.

| Bookworm element | Code-facing name / where used | Equivalent to decide |
|---|---|---|
| Glasses and lenses | slices `lensL` (11,17,4,6), `lensR` (23,18,8,7), `errorLensL` (10,17,5,6), `eye` (27,21,2,2); roles `worm.glasses.dark`/`.light` (`D`/`L`) | eye regions; glasses-count check replacement if none |
| Plus pupils, gaze offsets | `eyes.center/left/right/up/down.l0..l3/far/wide/half/closed/error` parts | pupils |
| Floating brows | `brows.<v>` and `brows.<v>+1` for none, happy, sad, tired, worried, curious (mad unused) | brows or brow-equivalent |
| Mouth shapes | `mouth.talk1/talk2/gulpOpen/smile/yawn/mumble1/mumble2/chew1/chew2` | mouth |
| The book | `book.*` parts and roles: closed, closed.low, open (cover k), flip1–5, close1–3, down1–3, up1–3, open1–2, rest.sleep | the reading prop (D5) |
| Body: head, torso, tail | `body.<v>/head`, `/torso`, `/tail` with ≥ 2 rows of seam overlap | body parts that breathe and squash |
| Neck and tail (menu bar) | the 18 × 18 S-neck, a 1-px squash for bobs | small-set body |
| Sweat drop, z glyphs, `?`, glint, sparkles, paper | `fx.sweat.d1–d8`, `fx.z.{s,m,l}.{Z,Y,X}`, `fx.q.mark`, `fx.glint1–4`, `fx.sparkle1–4`, `fx.paper` | same glyphs, placed for its anatomy |
| Reading eye rows | line rows a (21–23), b (22–24), c (b + a `j` lid) | eye tracking rows |
| Swallow bulge | `fx.bulge.high/mid/low` (synthesized in `build_worm`) | throat or body bulge |
| Emotions → states | happy → `happy`, `digesting`, cheer; tired → `hungry`; worried → `error`; sad → `shake`; base → `awake`, `reading`; mad unused (R-BW7) | which reference shows which |

- **The keep-outs** (§5.10) and **the budget check**: palette keys (D3), decoded pixels (D4), redraw budget (§8.13),
  bytes (1,834,301 of 6,291,456 used; a bookworm-sized set adds about 1.40 MB: fits).
- **Boards from day one.** Reference-vs-sprite comparison boards at matching size. The bookworm review's headline catch
  was a fidelity failure: the redraw had turned the big round eyes into slots with crosshair pupils and fused the brows
  into the rims.

### 5.2 Palette (D3; schema in §7.4)

- **Shape:** `{version, note, colors:[{key, hex, group, role}], night{version, note, bands[7], ramps{key→7 hex}, glyphs},
  scenery{version, note, ramps{dusk, night}, colors[14]}, clock{version, colors{6}}}`.
- **Keys:** 87 legal single characters (`A–Z a–z 0–9 ! # $ % & ( ) * + , - / : ; < = > ? @ [ ] ^ { } ~`). Never `.`,
  space or `_` (transparent or erase in stamps); never a quote, backslash, backtick or `|`. **Keys and hexes are both
  unique** across `colors`.
- **Budget:** 81 used (room 26, weather 26, book 11, worm 9, fx 6, fly 2, spine 1); free: `] ^ e { } ~`. Derived
  colours (night, scenery and clock) cost no key.
- **Roles are dotted, and tests read them:** `celestial.*`, `cloud.*`, `weather.rain.*`, `weather.curtain.*`
  (`WindowSpritesTests`); `book.*`, `worm.glasses.*`, `worm.white`, `worm.outline`, `worm.small.body`
  (`BookwormPoseSpriteTests`); `worm.*` and keys `K` and `S` by letter (`SpriteTestAssets.assertErrorMarks`);
  `book.*` (`verify.py`). A colour with a role is used for nothing else. **Check marks by role, never by key letter**:
  after the merge a freed key letter was reused by the room and broke a key-based check (fixed in `d88bed60`).
- **Reserved hues** (no authored or derived colour may equal one): `#22C55E #EF4444 #F59E0B #3B82F6 #4A9EFF #8B5CF6
  #3BD97A #6B7280 #999999`. The bookworm's book blue `#097FFD` is near, not equal.
- **Pixel rules:** binary alpha only; no gradient, dither, fractional alpha or interpolation; light from the upper left;
  props outline with the darkest step of their own ramp, never `K`; each source uses fewer than 256 colours.
- **No red unless the owner asks.** `$BW/tools/verify.py` fails on any worm role containing `error`, `rimDark` or
  `small.rim`.
- **Name new identity colours `worm.<character-name>.<part>` in group `worm`** (for example `worm.<character-name>.body.light`).
  `SpriteTestAssets.assertErrorMarks` requires the pixels around each X eye to carry a `worm.*` role, and the badge
  guard treats `worm.glasses.*` and `worm.white` as identity ink. Never put `error`, `rimDark` or `small.rim` in a role.
- **Every new key needs** a 7-hex `night.ramps` entry and `scenery.ramps.dusk` / `.night` entries (§7.5), or
  `night_palette.py`'s coverage asserts fail.

### 5.3 The spec (quickstart Step 6)

- **How the bookworm's was written:** six parallel readers (worm code, room code, resources and motion infra, rulings,
  Aseprite tooling verified headless, the reference analysis) → one writer → two critics (code accuracy; scope, art
  direction and rails) → a revision. 3,072 lines.
- **Required contents** (the bookworm spec's section list as the template):
  1. §0 the owner's words, verbatim, and the scope; the dated decisions D1–D14.
  2. §1 the reference, measured: grid, palette, identity list, anatomy map, what each emotion changes.
  3. §2 grids and scales: canvas, lattice placement, keep-outs.
  4. §3 the asset catalog: palette additions with roles and ramps; the **sheet table** (file, canvas, layers back to
     front, the exact ordered tag set, users); slices; the parts list; **every tag as an exact table** (frame, content
     as part names plus whole-pixel offsets, ms; the total; blink start times and gaps, computed; the key frame's
     contents). Example: `awake/idle`: 34 frames, 13,200 ms, blinks at 3,040, 6,830 (double) and 8,700 ms; rows like
     `| 8 | blink.half | 60 |`.
  5. §4 state → tag, response → tag, precedence, the cover cycle, the state marks per frame (copy §6.6's table and
     adapt).
  6. §6 pipeline, manifest, preview, verifier (with its independent timing transcription).
  7. §7 app integration, file by file, with the tests that change (§9).
  8. §8 the exact doc-amendment texts.
  9. §9 the Codex run briefs (headless; §10.5).
  10. §10 the Aseprite cheat sheet (copy the bookworm spec §10.1–10.5; replace §10.6 with this guide's §10.6).
  11. §11 open questions, each with a **built default** and "one word to change".
- **Tag names come from the code, never typed twice.** The set is `BookwormArt.requiredTags(state)`; the order is
  `BookwormLook.reachable(for:)` through `BookwormArt.tag(_:cover:)`, transcribed as `COMMON`/`EXPECTED` in
  `$BW/tools/verify.py:18-28`.
- **Verify every tool fact headless before Codex sees it** (bookworm spec §10.1).
- **Every later departure becomes a dated spec note** ("<YYYY-MM-DD>, fix pass, review B4. …"), never chat.

### 5.4 Parts and builders (Run A)

- **Registration.** Each part variant is one tag with one frame on the full canvas, with no anchors. A frame is
  composed by pasting each part at (0,0) plus that frame's offset.
- **Body.** Split into `body.<v>/head`, `/torso` and `/tail` with **≥ 2 rows of seam overlap**, so breaths and squashes
  never open a gap.
- **Seeds create a parts file only when it is absent.** After that, parts change only through a recorded correction:
  a headless one-time `lua/fix_<topic>.lua` (palette colours via `drawPixel` through `H.px`/`H.rect`, run once with
  `"$ASE" -b --script-param art="$PWD" --script lua/fix_<topic>.lua` from `$ART`), as the bookworm's `fix_parts.lua`
  and `refine_wormfix_parts.lua` did. Never rerun one; `export_all.sh` runs none.
- **The script table** (`mascot_scripts.lua`, after `worm_scripts.lua`): `S.sheets[state][tag]` is a list of
  `{ms, parts=[{layer, tag, x, y, remap?}], body, eyes, note}`, built from a `rest` table and a helper
  `f(state, ms, opts)`; block helpers build long loops (`L` a reading line, `Bk` a blink, `F` a flip); `looks()`
  generates the pose and beat families; `S.order[state]` is the exact tag order.
- **The builder, per frame:** compose the parts → recolour (`H.recolor`, one pass from the original pixels) → the
  outline compositor (bookworm rule: enclosed `K` becomes `G` unless it touches glass `D`/`L`; exposed `G`/`g` becomes
  `K`) → `checkFrame` (the marks, §6.6).
- **The builder, at the end:** assert tag totals → create the tags last (`H.recorder`) → add the slices → save
  `src/`, `qa/<name>-key@8x.png`, the demo GIFs and `qa/registry.json`.
- **Slices the app and tests read:** `ink` (union of every frame's ink), `eye` (2 × 2; gaze origin), `lensL`, `lensR`
  (+ `errorLensL` on error). `eye`, `lensL`, `lensR` are identical across the 8 room sheets; night sheets copy them.
- **Layers**, back to front: `ref` (hidden; palette-locked pixels only), `book-back`, `body`, `book`, `face`, `brows`,
  `mouth`, `fx`. Rename the prop layers for a different prop (D5).

### 5.5 State loops (`idle`; full numbers in §6.1)

**Contract for every loop:** frame 0 is the key frame (it carries every state mark and is what Reduce Motion shows);
the base row is 47; every tag is `forward` with no `repeat` field in the JSON (Aseprite writes `repeat` only when > 0;
§12), and the app decides whether a tag loops or plays once (§6.2.4); no ping-pong (write the frames out; `--sheet-pack`
de-duplicates them); frames 40–4,000 ms in multiples of 10; a loop totals 0.4–30 s; seams are pixel-continuous.
**Blinks are irregular:** ≥ 3 blink runs in awake and reading `idle`, ≥ 2 elsewhere; cyclic gaps between run starts
have max/min ≥ 1.6; awake includes a double blink; never a metronome. Hungry blinks but is exempt; error never blinks;
sleeping's eyes stay shut.

**State art, not response art.** A loop shows only a state that is already true. No flash, no strobe, no motion with no
state behind it.

| State | What the loop shows | Bookworm calibration | Mark tested on every frame |
|---|---|---|---|
| awake | breath (inhale, hold, exhale), irregular blinks with one double, a secondary motion (tail flick) | 34 fr, 13,200 ms | ≥ 20 prop px; glasses ≥ 30 `D`, ≥ 6 `L` |
| reading | lines with eyes tracking left → right; 3 uneven page flips; close; **swap to the next prop**; open | 85 fr, 21,840 ms, × 3 covers | per line the pupil x-centroid is non-decreasing; exactly 3 uneven flips; both covers ≥ 6 px in swap frames |
| sleeping | eyes shut, slow breath, **z → zz → zzz** rising, fading by palette steps and shrinking (never alpha) | 32 × 250 ms | ≥ 4 lid px (`j`), 0 `W`; ≥ 3 `Z` on f0; z inside cols 40–63 × rows 0–14 |
| digesting | two chews, a swallow (1-px bulge high on the neck), a smile | 6 fr, 1,060 ms | |
| happy | breath under happy brows, a glint crossing a lens, uneven blinks, a sway | 27 fr, 7,170 ms | |
| hungry | half lids, nods off and jolts awake, a slow blink, a small yawn | 17 fr, 8,800 ms | |
| error | worried brows, **black X eyes**, a sweat drop, a tremble; **no blink** | 13 fr, 2,400 ms | X eyes; ≥ 1 `S`; no red |
| curious | a `?` glyph, a tilt, two blinks at uneven gaps | 8 fr, 3,600 ms | the `?` |

**Reading's prop cycle (contract):** `idle`, `idle@2`, `idle@3` have identical per-frame durations; each ends picking
up the next cover (`idle` → cover 2, `@2` → 3, `@3` → 1); covers come from a **cyclic** recolour map
(`B→1, b→2, H→3, 1→4, 2→5, 3→6, 4→B, 5→b, 6→H`) applied k−1 times (a one-way map would paint both books one colour in
the swap frames); every reading look exists in all 3 covers (18 × 3 = 54 tags).

### 5.6 Poses and beats (§6.2)

Each uses the state's rest face and keeps every state mark. Gaze `<g>`: the head turns 1 px toward g and the pupils use
`eyes.<g>` (reading looks up, `up.<g>`); gaze variants share durations frame for frame. **Lifts:** only `perk.*`,
`eager` and `cheer.center` lift, by n ≤ 3 px, always after a crouch; `eager` and `cheer` land on a 1-px squash at row
47; everything else squashes in place and never translates. **The verifiers compare each sheet's ordered tag list
exactly:** idle, attentive.left/center/right, expectant.left/center/right, eager, perk.left/center/right,
talk.left/center/right, gulp.center, shake.left/center/right, then cheer.center.

### 5.7 Transitions (§6.3)

`intro` (yawn) and `outro` (stretch), on the sleeping sheet only, ≤ 1,600 ms each. Frame 0 is exempt from the
key-frame rule (they never play under Reduce Motion). **Check the last outro frame against frame 0 of digesting, happy,
reading and hungry**: the bookworm's stretch → reading pops from a standing closed book to an open one (documented, not
fixed). The yawn closes the prop whatever the previous mood. Night sheets carry the same transitions.

### 5.8 The menu-bar set (D2; §6.4)

One sheet `<character-name>-small`, 18 × 18, 8 tags named by the state cases. Rows 16–17 empty in every frame (stage
dots); for curious, cols 9–17 × rows 11–17 carry no identity ink (count badge); eyes stay above row 11 (lens slices
`maxY ≤ 10`); sleeping eyes are one-row lids with ≥ 2 `K` per eye; reading shows ≥ 8 prop px; error shows exact 3 × 3
black diagonal Xs and ≥ 2 `S`. No night variant. One sheet for both menu-bar appearances, dark outlines (D12): check
every frame on `#ECECEC` and `#1E1E1E` at 1× and 2×, and export the @8x beside the reference. A bob or droop is a 1-px
neck squash, never a lift off row 0.

### 5.9 The dark-room relight (§7.6)

Never hand-draw a night sheet. `lua/build_mascot_night.lua` relights each saved day source through
`palette.json` `night.ramps` at the character's placement on `room-light-map.json` (offset (36, 7)), writing 16 sources
with tags, durations and slices copied exactly. `tools/verify_night.py` re-derives every frame independently.

### 5.10 Keep-outs (character canvas, top-left origin; computed from `$BW/room-plan.json`)

The character canvas sits at plan `(36, 9)` bottom-left, i.e. top-left `(36, 7)` in room cells; canvas pixel `(px, py)`
is room cell `(36 + px, 7 + py)`.

| Zone | Canvas region | Rule | Checked by |
|---|---|---|---|
| Ruling-9 window zone | cols 0–19 × rows 0–29 (the glass at room (20,5)–(55,36)) | Every celestial pixel of every weather frame stays visible, and ≥ 50 % of each frame's cloud pixels, against the union of every frame of all 8 sheets in each lighting plus the window frame. Keep ink out of it where you can. | `WindowSpritesTests.testRulingNineForEveryWeatherFrameAndEveryReachableWormFrame` (loop it over the registry, §9.6); the port in `$ART/tools/verify.py` |
| Wall clock | cols 58–63 × rows 8–22 (the clock box at room (94,15), 15 × 15) | No ink in any day or night frame. | `RoomClockTests`, `RoomClockSpriteTests` (both already iterate the registry); the `verify_clock` port |
| z box | cols 40–63 × rows 0–14 | Sleeping glyphs live here, never overlap each other, ≥ 3 × 3, and stay out of the clock box (so cols 58–63 only on rows 0–7). | `verify.py` |
| Base row | row 47 | Sits on the bean bag's `seat` row (scene row 9). Never moves except during a lift. | `DeskSceneLayoutTests` (seat), `verify.py` |
| Lift headroom | 3 rows above the tallest pose | For `perk`, `eager`, `cheer`. | `verify.py` |
| The pile | room cols ≥ 110 | Unreachable from the canvas (room cols 36–99). | — |
| Menu badge, stage dots | 18 × 18: cols 9–17 × rows 11–17 (curious); rows 16–17 (all) | No identity ink. | `BookwormPoseSpriteTests.testSmallStateMarksAndOverlaySpace` (loop it) |

The hotspot is the union of every state's `ink` slice except curious, and the gaze origin is the awake `eye` slice
(§9.2); a character with a different silhouette gets a different hotspot automatically.

### 5.11 Run A's brief: scope, owned paths, checks

Run A owns, and only Run A writes: `$ART/**`, `$RES/<character-name>-*`, `$RES/sprites.manifest.json`,
`$BW/palette.json`, `$BW/tools/manifest.py`, `$BW/tools/verify_room.py`, `$BW/tools/make_preview.py`, and
`$BW/preview.html` (regenerated by the bookworm export; it may differ from `$BASE` only in the embedded palette). With a
non-default D7 it also owns `$BW/tools/night_palette.py`, and proves the bookworm export byte-identical. It never writes
another `$BW` file, any `room-*` or `bookworm-*` file in `$RES`, any Swift file, or any doc outside `$ART`. (In the
brief, write these as repository-relative paths.)

| Task | Done when |
|---|---|
| A0 Copy the generic code (§4.6); `character.lua`, `character.py` | `"$ASE" -b --script-param art="$PWD" --script lua/test_helpers.lua` (cwd `$ART`) prints `helpers: every public helper and additions passed` |
| A1 The prefix-aware patch (§4.7) | §4.7's first Accept |
| A2 Palette additions (D3) | `python3 -c "import sys; sys.path.insert(0,'$BW/tools'); import night_palette as n; n.palette_data(); print('palette ok')"` → `palette ok`; the bookworm export stays byte-identical |
| A3 Parts, script table, builders: 8 day sheets and the small sheet | `$ART/tools/verify.py` passes the tag, timing, cap, mark, blink, tracking and slice checks |
| A4 Relight: 16 night sheets; `day-art-contract.json` (by hand with `tools/day_art_contract.py` once A3 passes, before the relight; again whenever day art changes, §4.6) | `verify_night.py` passes every frame |
| A5 Ruling 9, clock clearance, budgets (D4) for the 24 room sheets | the ports pass |
| A6 Manifest entries, preview, review boards, README, TAG_TIMINGS, report | `(cd "$ART" && tools/export_all.sh)` → `sprites: OK (all)`; `node tools/check_preview.mjs` exits 0 |
| A7 Two full rebuilds | `qa/rebuild.json` `byteIdentical: true` |

The closing report lists every file written, every tag (frames × ms), every hand-tune, what is left rough, every spec
disagreement with its reason, and the sentence "no commit made".

### 5.12 The review loop (quickstart Step 12)

1. **Render review output headless after every run:** tag GIFs at @6x (@8x for 18 × 18); **contact sheets** (every
   frame of a tag in a row at 6×, labelled with ms, so motion can be judged from a still); filmstrips;
   reference-vs-sprite **comparison boards** at matching size; menu-bar boards on `#ECECEC` and `#1E1E1E`; room
   composites for every mood × lamp × time at 1×, 3× and 6×; the Swift composites (quickstart Step 13).
2. **Five lenses in parallel:** fidelity to the reference, animation, pixel craft, the 18 × 18 set, spec conformance.
3. **An art director merges them into one fix list:** verify every item against a board or a key-grid dump;
   normalize coordinates to (row, col) and say so; file **A must-fix**, **B should-fix**, **C optional**; add
   "Dropped / needs a dated amendment first" (timing changes stay out: the tables are exact), "Genuinely good, do not
   regress", and "App-side consequences" (new slices, golden images, hand-off pops).
4. **App review:** three lenses plus two adversarial skeptics per finding; show each regression failing before its fix;
   check test strength by mutation.
5. **Codex fixes by resuming the same session** (§10.4). Anything that would change the owner's design is **held for
   him** (the bookworm's B12, a narrower menu lens, is still held).
6. **Iterate at least twice on the centrepieces:** the face, the prop action (flip and swap), the z's.
7. **Judge art from rendered PNGs and GIFs, never from a live GUI.** QA GIFs use an exact Pillow palette
   (`write_palette_gif`), because Aseprite's quantizer merges near colours.

### 5.13 Owner checkpoints

| STOP | He sees | He decides | Recorded as |
|---|---|---|---|
| S1 | the plan | approve | — |
| S2 (checkpoint 1) | measured grid, reference-vs-fit board, anatomy map, keep-outs, budget options | D1–D8, D11–D13 | dated lines in `$SPEC` §0 |
| S3 (checkpoint 2) | the spec's open questions, each with a built default | one word each; D9, D10, D14 | dated notes in `$SPEC` |
| S4 (checkpoint 3) | contact sheets, comparison boards, menu-bar boards, demo GIFs (sent with SendUserFile when available, otherwise their paths in `$ART/qa/`) | the next round's scope; held items | dated notes; the fix list |
| S5 (merge gate) | `$ART/preview.html` (he opens it), the composites, live CPU on the demo bank | merge or another round | his PR review |

Record each decision once, as a dated line in the spec, in `docs/goals/TODO.md` ruling 18 when it binds beyond this
character, and in the scenery contract when it touches the room, so it is never re-derived.

### 5.14 Docs, PR, merge (quickstart Steps 14–15)

1. **Docs in the same PR:**
   - `docs/architecture/app.md`: the Mascot paragraph (around lines 488–504; "today its only entry is **Bookworm**")
     and the closing line around 573 ("a second character's own design remains open").
   - `docs/goals/memory-evolution.md`: the G127 row (edit in place; never a new row) and the G176 row's "Open" list
     ("a second G127 character").
   - `docs/goals/TODO.md`: a dated amendment under ruling 18 (D3/D4/D13 as decided), the header and "Pick up here".
   - `docs/design/DESIGN_RULES.md` log if UI changed (cite the DR ids).
   - `$ART/README.md` and the spec's dated notes.
2. **`CLAUDE.md`** only if a rail changes (quickstart Step 14's size check).
3. **Merge order:** Step 12's fix rounds run on the separate branches; Step 13 merges the app branch into the art
   branch (failures after the merge go to `runC2` or Run A's thread, Step 13). Keep both sides of README and TODO
   conflicts and reconcile them.
4. **The PR is against `dev`**, cites G127, follows the privacy rule in every word, and waits for the owner (S5).

---

## 6. Animation catalog

The bookworm's complete animation set, as shipped. It is the template `<character-name>` reproduces: **tag names and
sets, the response matrix, the caps, the key-frame marks and the gaze-duration parity are contract; frame counts, holds
and pixel paths are calibration** (D8 keeps them by default). §6.8 is the adaptation checklist.

**Sources.** Every number comes from the shipped sheets `app/CicadaApp/Sources/CicadaApp/Resources/sprites/bookworm-*.json`
(`meta.frameTags`, every `frames[].duration`, `meta.slices`), with pixel counts measured from the matching PNGs. The
motion descriptions come from `app/CicadaApp/Art/sprites/bookworm-2026-10-01/TAG_TIMINGS.md`, `WORM_FIX_REPORT.md`,
`SCENERY_REPORT.md`, the bookworm spec §3.3–§3.7 and §4, and the scenery contract. The playback rules come from these
files under `app/CicadaApp/Sources/CicadaApp/`: `Sprites/BookwormArt.swift`, `Sprites/SpriteClip.swift`,
`MenuBar/BookwormPose.swift`, `MenuBar/BookwormOverlays.swift`, `MenuBar/BookwormRenderer.swift`, `MenuBarManager.swift`,
`Views/Common/BookwormView.swift`, `Views/Sleep/RoomModel.swift`, `Views/Sleep/SleepMood.swift` and
`Theme/CicadaMotion.swift`.

**Conventions.**
- `f0`, `f1`, … are **0-based frame numbers inside a tag**. `abs` is the 0-based index in the sheet's `frames` array.
- Times are integer milliseconds. "Start" is the offset of a frame from the start of its tag.
- In the JSON, every tag is `direction: forward` with no `repeat`. **The app decides whether a tag loops or plays once**
  (§6.2.4). Offsets: `+` is up, `−` is down, `x` marks a horizontal shift. The base row (canvas row 47) never moves,
  except during a lift.
- Colour letters (`K`, `W`, `j`, `r`, `S`, `Z`, …) are `palette.json` keys; Appendix A lists each with its role.
- "spec §…" in this chapter means the bookworm spec, `docs/specs/2026-10-01-bookworm-sprites-spec.md`.

### 6.0 Sheet inventory

| Sheet | Canvas | Tags | Frames | Unique packed cells | Sum of all frame ms | `ink` slice (x, y, w, h) |
|---|---|---:|---:|---:|---:|---|
| `bookworm-awake` | 64 × 48 | 18 | 135 | 61 | 38,070 | (4, 6, 56, 42) |
| `bookworm-reading` | 64 × 48 | 54 | 558 | 258 | 140,130 | (4, 6, 56, 42) |
| `bookworm-happy` | 64 × 48 | 19 | 135 | 69 | 32,760 | (4, 3, 56, 45) |
| `bookworm-hungry` | 64 × 48 | 18 | 118 | 62 | 34,150 | (4, 5, 56, 43) |
| `bookworm-digesting` | 64 × 48 | 7 | 39 | 27 | 4,540 | (4, 3, 56, 45) |
| `bookworm-sleeping` | 64 × 48 | 4 | 57 | 46 | 11,200 | (4, 0, 56, 48) |
| `bookworm-error` | 64 × 48 | 1 | 13 | 9 | 2,400 | (4, 8, 56, 40) |
| `bookworm-curious` | 64 × 48 | 1 | 8 | 5 | 3,600 | (4, 8, 56, 40) |
| `bookworm-small` | 18 × 18 | 8 | 32 | 21 | 22,070 | — |
| **Day + menu total** | | **130** | **1,095** | | | |
| 16 night sheets (§6.5) | 64 × 48 | 2 × 122 | 2 × 1,063 = **2,126** | | | the day sheet's rect |

**The shared slices** (one key, on frame 0) are identical on every room sheet (tested equal):

| Slice | Rect | Meaning / used by |
|---|---|---|
| `eye` | (27, 21, 2, 2) | The right lens's pupil centre in the rest composition. `BookwormArt.eyePixel` uses it for `DeskHotspots.eyeCell`. |
| `lensL` | (11, 17, 4, 6) | The left lens interior (normal). |
| `lensR` | (23, 18, 8, 7) | The right lens interior. |
| `errorLensL` | (10, 17, 5, 6) | **`bookworm-error` only.** The error's inner left rim moves out by 1 px, which leaves a green interior of 5 × 6 around the left X. |
| `ink` | per sheet (above) | The union of opaque pixels across the whole sheet. `BookwormArt.wormInk` unions these over every state except curious to make the worm hotspot (`DeskHotspots.wormCols` and `wormRows`). |
| small `lensL`, `lensR` | (2, 5, 4, 4), (10, 5, 5, 4) | The inner boxes of the menu head's lenses. |

**The rest face of each state** (spec §3.5): any family not listed for a frame uses that state's rest face.

| State | Brows | Eyes | Book | Mouth |
|---|---|---|---|---|
| awake | `none` | `center` | `closed` | `none` |
| reading | `none` | `down.*` (line rows a/b/c) | `open` (cover k) | `none` |
| happy | `happy` | `center` | `closed` | `none` |
| hungry | `tired` | `half` (heavy lids) | `closed` | `none` |
| digesting | `happy` | `happy` (one closed ∩ per lens) | `closed` | `chew*` |
| sleeping | `none` | `closed` | `rest.sleep` | `none` |
| error | `worried` | `error` (centred black X eyes) | `closed` | `none` |
| curious | `curious` (left happy arc + right tired bar) | `center` | `closed` | `none` |

`brows.mad` is drawn but no shipped tag uses it. It appears only in the unbundled demo `demo/bookworm-mad-demo@6x.gif`.


### 6.1 Room-scale states: the `idle` loop of each sheet

#### 6.1.0 Summary

| State | Sheet | Tag | Frames | Total ms | What moves |
|---|---|---|---:|---:|---|
| awake | `bookworm-awake` | `idle` | 34 | 13,200 | Three breaths. In each, the torso leads and the head follows one frame later, on the way up and on the way down. One tail flick. Irregular blinks: single blinks at 3,040 and 8,700 ms and a double blink at 6,830 ms (gaps 3.8 / 1.9 / 7.5 s). |
| reading | `bookworm-reading` | `idle` (cover 1), `idle@2`, `idle@3` | 85 each | 21,840 each | The pupils track 10 lines (four columns per line, then a return with a 1-px head bob). Three uneven page flips (after 3, 2 and 3 lines) and a close after 2 more. Blinks at 5,220, 7,940 and 18,310 ms (gaps 2.7 / 10.4 / 8.8 s). Then the book closes, is tucked behind the body, the **next** cover rises, and it opens. Cover cycle: blue → crimson → ochre → blue. |
| sleeping | `bookworm-sleeping` | `idle` | 32 | 8,000 (32 × 250) | Two slow 4-second breaths: torso, then head, rising and settling. A z → zz → zzz sequence rises and drifts up-right. Each glyph fades bright → mid → pale through palette steps (never alpha), and medium and large glyphs shrink one size on their last pale frame. |
| digesting | `bookworm-digesting` | `idle` | 6 | 1,060 | Two chews (the head dips 1 px on each `chew2`), a swallow bulge high on the neck, then a satisfied smile. The eyes stay closed ∩ throughout. |
| happy | `bookworm-happy` | `idle` | 27 | 7,170 | The awake breath under happy brows. Blinks at 2,340 and 3,720 ms (gaps 1.4 / 5.8 s). A 4-frame glint crosses the right lens's top rim. The head sways 1 px sideways before the last rest. |
| hungry | `bookworm-hungry` | `idle` | 17 | 8,800 | A slow, heavy breath with a delayed head exhale. The worm nods off (head −1, then eyes shut for 1.2 s), jolts awake with brows raised, gives one slow blink, then a small yawn. |
| curious | `bookworm-curious` | `idle` | 8 | 3,600 | A floating `?` that bobs 1 px. The head tilts 1 px. Blinks at 600 and 3,400 ms (gaps 2.8 / 0.8 s: a quick double across the loop seam). |
| error | `bookworm-error` | `idle` | 13 | 2,400 | Black X eyes in every frame and **no blink**. The worried brows hold. A sweat drop slides, elongates, detaches and re-forms. A 3-frame horizontal tremble follows. |

Where each state is shown: the Sleep page (`deriveSleepPageMood`) picks the first that applies from: awake (no status
yet), sleeping(stage) (running), reading (paused), error, digesting (< 6 s after a real finish), reading (intake in
flight), awake (no debt reading), happy (0 unprocessed), hungry (rested ≤ 20 % or > 48 h since the last cycle), and
otherwise reading. The Sleep page never shows curious; the menu bar's derivation is in §6.4.

Breath sub-parts (spec §3.4): `sit.in1` raises the torso hump 1 px, and `sit.in2` raises the torso 1 px and the head
1 px. On the exhale frame the torso is back at 0 while the head is still at +1. This "lead and follow" overlap repeats in
every breathing loop. The sub-part seams overlap by at least two rows, so a 1-px offset never opens a gap.

#### 6.1.1 `awake/idle`: 34 frames, 13,200 ms (abs 0–33)

| f | Start | ms | Frame |
|---:|---:|---:|---|
| 0 | 0 | 700 | `sit` (rest) |
| 1 | 700 | 180 | `sit.in1`: the torso rises (lead) |
| 2 | 880 | 220 | `sit.in2`: the head follows |
| 3 | 1,100 | 600 | hold `sit.in2` |
| 4 | 1,700 | 180 | exhale: torso 0, head still +1 (follow-through) |
| 5 | 1,880 | 260 | `sit` |
| 6 | 2,140 | 900 | `sit` |
| 7–9 | 3,040 | 60 · 90 · 60 | **blink 1**: `blink.half`, `closed`, `blink.half` |
| 10 | 3,250 | 500 | `sit` |
| 11–15 | 3,750 | 180 · 220 · 700 · 180 · 260 | breath 2 (in1, in2, hold, exhale, sit) |
| 16 | 5,290 | 600 | `sit` |
| 17 | 5,890 | 120 | `sit.tail1`: the tail tip flicks up 1 px |
| 18 | 6,010 | 120 | tail tip halfway back (a sub-pixel colour step) |
| 19 | 6,130 | 700 | `sit` |
| 20–22 | 6,830 | 90 · 120 · 90 | **double blink**: `closed`, `center`, `closed` |
| 23 | 7,130 | 1,570 | `sit` |
| 24–26 | 8,700 | 60 · 90 · 60 | **blink 3**: `blink.half`, `closed`, `blink.half` |
| 27 | 8,910 | 1,400 | `sit` |
| 28–32 | 10,310 | 180 · 220 · 600 · 180 · 260 | breath 3 |
| 33 | 11,750 | 1,450 | `sit` (seam back to f0) |

#### 6.1.2 `reading/idle`, `idle@2`, `idle@3`: 85 frames, 21,840 ms each

The tags are at abs 0–84, 186–270 and 372–456. Each tag starts with its own cover open, which is its key frame, and
**ends by raising and opening the next cover**: `idle` ends on cover 2, `@2` on cover 3 and `@3` on cover 1. That is why
the app's cover cycle is seamless. `@2` and `@3` are the cover-1 tag recoloured with the cyclic map {`B`→`1`, `b`→`2`,
`H`→`3`, `1`→`4`, `2`→`5`, `3`→`6`, `4`→`B`, `5`→`b`, `6`→`H`}, applied once for `@2` and twice for `@3`. Their
durations are identical.

**The building blocks:**

| Block | Frames · ms | Total | What moves |
|---|---|---:|---|
| `L`, one line | `down.l0` 420 · `down.l1` 380 · `down.l2` 380 · `down.l3` 420 · return 140 | 1,740 | The pupils step right along a line. On the return the pupils go back to `l0` one row lower and the head bobs −1. Lines alternate eye rows a (21–23), b (22–24) and c (row b plus a `j` lid). **B4:** a line followed immediately by `F` holds its `l3` column on the 140 ms return, with head 0, so there is no double reversal. |
| `F`, page flip | `flip1` 90 · `flip2` 90 · `flip3` 100 · `flip4` 90 · `flip5` 120 · settle 200 | 690 | The right page lifts, curls, stands over the spine, falls and lands. The pupils follow the page from right to left, then jump to the top of the right-hand page, and each new page starts at row a. |
| `Bk`, blink | `closed` 90 · `down.l0` 200 | 290 | |
| `C`, close | `close1` 100 · `close2` 120 · `close3` 140 | 360 | `close3` is a tilted in-between. |
| `Sw`, swap | `down1`–`down3` 140 each · `up1`–`up3` 140 each | 840 | The finished book is lowered and tucked behind the body on `book-back`. In `down2`/`down3` the incoming cover's top peeks on the foreground `book` layer, beside the outgoing book (A8). The next book then rises from behind the body. At least 20 book pixels stay visible in every frame; the minimum measured is 65, at f79. |
| `O`, open | `open1` 140 · `open2` 160 | 300 | `open1` is tilted. |

**The script** (`L L L · Bk · F · L · Bk · L · F · L L L · F · L · Bk · L · C · Sw · O`):

| Block | f | abs (cover 1) | Start | ms |
|---|---|---|---:|---:|
| L1–L3 | 0–14 | 0–14 | 0 | 5,220 |
| **Bk 1** | 15–16 | 15–16 | **5,220** | 290 |
| **F 1** | 17–22 | 17–22 | 5,510 | 690 |
| L4 | 23–27 | 23–27 | 6,200 | 1,740 |
| **Bk 2** | 28–29 | 28–29 | **7,940** | 290 |
| L5 (its return f34 holds `l3`) | 30–34 | 30–34 | 8,230 | 1,740 |
| **F 2** | 35–40 | 35–40 | 9,970 | 690 |
| L6–L8 (f55 holds `l3`) | 41–55 | 41–55 | 10,660 | 5,220 |
| **F 3** | 56–61 | 56–61 | 15,880 | 690 |
| L9 | 62–66 | 62–66 | 16,570 | 1,740 |
| **Bk 3** | 67–68 | 67–68 | **18,310** | 290 |
| L10 | 69–73 | 69–73 | 18,600 | 1,740 |
| C | 74–76 | 74–76 | 20,340 | 360 |
| Sw (the overlap is f78–79) | 77–82 | 77–82 | 20,700 | 840 |
| O (the next cover) | 83–84 | 83–84 | 21,540 | 300 |

Measured book pixels per frame: 219 while reading (flip1 included) and 221–238 on flip2–flip5 (229, 238, 238, 221).
Across close, swap and open (f74–84) they
are 220, 227, 154, 238, 183, **65**, 137, 209, 189, 168, 219.

**Cover selection** (`BookwormArt.coverIndex`): `cover = 1 + ⌊(now − SpriteClock.origin) / (21,840 ms × slowdown)⌋ mod 3`,
where `origin` is the reference date 0. It is always 1 under Reduce Motion. Every reading pose and beat uses the cover
`k` that is current when it is drawn, so `talk.left@2` is drawn during cover 2's 21.84 s. A pose that spans a cover
boundary switches the book's colour mid-pose; this is accepted (spec §11 Q6).

#### 6.1.3 `sleeping/idle`: 32 frames × 250 ms = 8,000 ms (abs 0–31)

**Breath** (body offsets): there are two identical 4,000 ms breaths, f0–15 and f16–31.

| f (first breath; +16 for the second) | Body |
|---|---|
| 0–1 | `slump` |
| 2–5 | inhale: the torso is +1 from f3 and the head +1 from f4 (the head follows) |
| 6–7 | hold |
| 8–11 | exhale: the head returns to 0 at f9 and the torso at f10 |
| 12–15 | `slump` |

**The z's.** Positions are each glyph's top-left (x, y) in canvas pixels. `z.s` is 3 × 3 (7 px), `z.m` 4 × 4 (10 px) and
`z.l` 5 × 5 (13 px). The colours are `Z` #8896FF (bright), `Y` #B3BBFF (mid) and `X` #DADFFF (pale). Every glyph stays
inside columns 40–63 × rows 0–14, clear of the figure, and no two glyphs overlap.

| Glyph | f | Path | Colour by frame (measured pixels) |
|---|---|---|---|
| "z": one `z.s` | 0–9 | (40 + ⌊f/2⌋, 12 − f): from (40, 12) to (44, 3), rising 1 px per frame and drifting +1 x every second frame | `Z` f0–5 (7 px) · `Y` f6–7 · `X` f8–9; gone from f10 |
| "zz": `z.m` A and B, with t = f − 8 | 8–19 | A = (43 + ⌊t/2⌋, 11 − ⌊t/2⌋), from (43, 11) to (48, 6); B = A + (5, −5) | `Z` f8–14 (20 px) · `Y` f15–17 · `X` f18–19; **f19 shrinks both to `z.s`** (14 px) |
| "zzz": S `z.s`, M `z.m`, L `z.l`, with t = f − 18 | 18–31 | S = (42 + ⌊t/3⌋, 11). M = S + (4, −5), shown from f20. L = M + (5, −6), shown from f22. The group drifts +1 x every third frame and does not rise; it ends at S (46, 11), M (50, 6), L (55, 0) | `Z` f18–25 (7 → 17 → 30 px) · `Y` f26–28 · `X` f29–31; **f31 shrinks M and L one size** (24 px) |

Frame 0, the key frame, shows a bright "z" (7 `Z` px). Every frame has closed lids (12 `j` px) and 0 `W` px.

#### 6.1.4 `happy/idle`: 27 frames, 7,170 ms (abs 0–26)

| f | Start | ms | Frame |
|---:|---:|---:|---|
| 0 | 0 | 700 | rest (happy brows) |
| 1–5 | 700 | 180 · 220 · 600 · 180 · 260 | breath (in1, in2, hold, exhale, sit) |
| 6 | 2,140 | 200 | rest |
| 7–9 | **2,340** | 60 · 90 · 60 | blink (`W` speculars drop from 7 px to 0) |
| 10 | 2,550 | 290 | rest |
| 11–14 | 2,840 | 70 each | `glint1`–`glint4`: a 2-px `W` glint crosses the right lens's top rim (9 `W` px) |
| 15 | 3,120 | 600 | rest |
| 16–18 | **3,720** | 60 · 90 · 60 | blink |
| 19 | 3,930 | 500 | rest |
| 20–24 | 4,430 | 180 · 220 · 700 · 180 · 260 | breath |
| 25 | 5,970 | 300 | sway: head +1 x |
| 26 | 6,270 | 900 | rest |

#### 6.1.5 `hungry/idle`: 17 frames, 8,800 ms (abs 0–16)

| f | Start | ms | Frame |
|---:|---:|---:|---|
| 0 | 0 | 900 | rest: `half` lids (22 `j` px) and tired brows |
| 1 | 900 | 260 | in1 |
| 2 | 1,160 | 300 | in2 |
| 3 | 1,460 | 800 | hold |
| 4 | 2,260 | 260 | out1 (torso) |
| 5 | 2,520 | 360 | out2: the delayed head exhale (A10) |
| 6 | 2,880 | 700 | rest |
| 7 | 3,580 | 400 | head −1 (droop) |
| 8 | 3,980 | 1,200 | head −1 + `closed` (nods off; 12 `j` px) |
| 9 | 5,180 | 120 | jolt: head 0, `half`, brows `tired+1` |
| 10 | 5,300 | 800 | rest |
| 11 | 6,100 | 300 | `closed` (slow blink) |
| 12 | 6,400 | 600 | rest |
| 13 | 7,000 | 200 | small yawn (`talk1`; 6 `r` px) |
| 14 | 7,200 | 500 | `yawn` + `closed` + head +1 (26 `r` px) |
| 15 | 7,700 | 200 | `talk1` |
| 16 | 7,900 | 900 | rest |

The hungry lids have a curved lower edge with both end pixels cleared to green, and they follow every gaze (B7).

#### 6.1.6 `digesting/idle`: 6 frames, 1,060 ms (abs 0–5)

| f | Start | ms | Frame |
|---:|---:|---:|---|
| 0 | 0 | 140 | `chew1` (3 `r` px) |
| 1 | 140 | 140 | `chew2` + head −1 (8 `r` px) |
| 2 | 280 | 140 | `chew1` |
| 3 | 420 | 140 | `chew2`, head −1 |
| 4 | 560 | 200 | swallow: no mouth, and a 1-px `g` bulge high on the neck |
| 5 | 760 | 300 | `smile` |

#### 6.1.7 `curious/idle`: 8 frames, 3,600 ms (abs 0–7)

| f | Start | ms | Frame |
|---:|---:|---:|---|
| 0 | 0 | 600 | rest + `q.mark` (a 5 × 7 `?` in `K` with a `W` core) |
| 1 | 600 | 90 | `closed` + `?` (blink) |
| 2 | 690 | 210 | rest + `?` |
| 3 | 900 | 300 | `?` −1 y (it bobs up) |
| 4 | 1,200 | 600 | tilt (head +1 x, +1 down) + `?` −1 |
| 5 | 1,800 | 300 | tilt + `?` |
| 6 | 2,100 | 1,300 | rest + `?` |
| 7 | 3,400 | 200 | `closed` + `?` (blink; it runs into f0's open eye, then f1 closes again) |

#### 6.1.8 `error/idle`: 13 frames, 2,400 ms (abs 0–12)

Every frame has the centred black X eyes: a 3 × 4 left X (`K.K / .K. / .K. / K.K` at (11, 18)) and a 6 × 5 right X
(`K....K / .K..K. / ..KK.. / .K..K. / K....K` at (24, 19)). Each X has a full green pixel of air inside its ring. The
worried brows and furrow hold in every frame. There is no red anywhere: the former `e` / `pupilError` colour was removed
from the palette.

| f | Start | ms | Frame (sweat `S` px, measured) |
|---:|---:|---:|---|
| 0 | 0 | 300 | `sweat.d3`: the held 5 × 6 pointed drop with a white highlight (9 `S` + 1 `W`) |
| 1 | 300 | 150 | `d4`: slides 1 px |
| 2 | 450 | 150 | `d5`: slides |
| 3 | 600 | 150 | `d6`: slides |
| 4 | 750 | 150 | `d7`: elongates (3 `S`) |
| 5 | 900 | 120 | `d8` detaches, and `d1` forms at the shoulder (3 `S`) |
| 6 | 1,020 | 200 | `d2`: forming (4 `S`) |
| 7 | 1,220 | 300 | `d3`: held drop |
| 8 | 1,520 | 80 | tremble −1 x (both Xs move together) |
| 9 | 1,600 | 80 | tremble +1 x |
| 10 | 1,680 | 80 | tremble −1 x |
| 11 | 1,760 | 300 | rest |
| 12 | 2,060 | 340 | `error.left`: the same centred Xs, a retained hold |

Frames f7–12 keep `d3`, so the seam back to f0 (`d3`) is continuous. Every sweat pixel stays above row 18.

#### 6.1.9 Blink cadence at a glance (start-to-start gaps, including the wrap)

| Loop | Blink starts (ms) | Gaps (s) | Closed length |
|---|---|---|---|
| awake `idle` | 3,040 · 6,830 (double) · 8,700 | 3.8 · 1.9 · 7.5 | 60 + 90 + 60, or a double of 90 / 120 open / 90 |
| happy `idle` | 2,340 · 3,720 | 1.4 · 5.8 | 60 + 90 + 60 |
| reading `idle@k` | 5,220 · 7,940 · 18,310 | 2.7 · 10.4 · 8.8 | 90 closed, then 200 on `down.l0` |
| curious `idle` | 600 · 3,400 | 2.8 · 0.8 | 90; 200 |
| hungry `idle` | 3,980 (nod) · 6,100 (slow) · 7,200 (in the yawn) | — | 1,200 · 300 · 500 |
| `attentive.<g>` (not hungry) | 1,400 · 3,430 | 2.0 · 3.9 | 50 + 80 + 50 |
| hungry `attentive.<g>` | 1,400 · 3,510 | 2.1 · 4.0 | 50 + 160 + 50 |
| error, sleeping | none (the X eyes and the shut eyes are the marks) | | |


### 6.2 Beats and poses (room scale)

#### 6.2.1 Every pose and beat tag

`<g>` is `left`, `center` or `right`. For left and right the head turns 1 px toward `g` and the pupils use `eyes.<g>`:
the right pupil travels −2/+1 and the left −1/+1, and a glance past the horizontal clamp moves up one row (A2). For
centre the pupils use `eyes.center`, or `wide` where marked. **The gaze variants share their durations frame for frame**
(tested), so a beat's length never depends on the gaze.

| Tag | Plays | f · ms | Total | Cap | What moves | Trigger |
|---|---|---|---:|---|---|---|
| `attentive.<g>` | loop | look 1400 · `blink.half` 50 · `closed` 80 · `blink.half` 50 · look 1250 · **glance** 300 · look 300 · `blink.half` 50 · `closed` 80 · `blink.half` 50 · look 2300 | **5,910**; hungry **6,070** (`closed` 160) | loop 0.4–30 s | The gaze is held, with two irregular blinks. The glance moves the pupils 1 px further toward g; for centre, 1 px up. Every attentive tag's f5 differs from its f0. Reading uses `up.<g>`: the worm looks up from the open page. | The pointer is in the room and not over a drag; gaze comes from the pointer x against the worm's own column span (`gazeFor`, with 1 cell of hysteresis). |
| `expectant.<g>` | loop | ready (`talk2`, brows +1, eyes g) 240 · dip (`crouch` −1) 140 · rise (back to rest height, no lift) 140 · ready 200 | **720** | loop | Raised brows and an open mouth, with a brief anticipatory crouch. | A file is dragged over the room (`RoomDrag.overRoom(gaze)`). |
| `eager` | loop | crouch −1 + `gulpOpen` + brows +1 100 · hop +2 120 · hop +1 100 · land: squash −1 140 | **460** | loop | Crouch, a two-pixel hop, overlap, then a landing that widens the contact patch on row 47 to columns 45–53 (B10). The open mouth and raised brows appear only on f0 (A10). | A file is dragged over the worm (`RoomDrag.overWorm`). |
| `perk.<g>` | once | crouch −1 60 · up +2, brows +1, `wide` 80 · +1 120 · 0 100 | **360** | perk ≤ 400 ms | Crouch, then a bright-eyed two-pixel hop and settle. | The pointer *reaches* the worm hotspot (an edge, never a level). Cooldown `SleepMotion.perkCooldown` = 2 s. |
| `talk.<g>` | once | `talk1` 80 · `none` 70 · `talk2` + head +1 90 · `talk1` 70 · `talk2` + head +1 90 · `none` 100 | **500** | beat ≤ 800 ms | Six mouth poses with a small head bob. | A click, Space or Return on the worm that steps to an answer rung (`RoomModel.poke`). Stepping past the last rung returns to the status and plays nothing. |
| `gulp.center` | once | `gulpOpen` 90 · + `paper` at the mouth 90 · closing on it 80 · closed + bulge high 90 · bulge mid 90 · bulge low 90 · `smile` 120 | **650** | beat | The mouth opens and a 3 × 3 paper scrap enters, overlapping the upper lip. An outlined 1-px neck bump travels down (B6), then a smile. In reading, `book.closed.low` is used in f0–5. | A drop is handed over (`FeedResult == .handedOver`). |
| `shake.<g>` | once | sad brows on every frame; head −1 x 70 · +1 x 70 · −1 x 70 · +1 x 70 · rest 150 | **430** | beat | The head oscillates **around its gaze position** and settles there (B5). This is the only use of the sad brows. | A drop the intake did not take (`FeedResult ≠ .handedOver`). |
| `cheer.center` | once | crouch −1 100 · +2 & `sparkle1` & `happy` eyes 100 · +3 & `sparkle2` 120 · +2 & `sparkle3` 100 · 0 & `sparkle4` 100 · squash −1 80 · settle 120 | **720** | beat | Anticipation (f0), then a rise to a +3 peak (f2). The happy closed eyes hold through the f5 landing squash and reopen at f6 (A5). Sparkle px (`q`/`Q`) by frame: 0, 8/1, 12/1, 8/0 (`sparkle3` is a gapped decaying 7 × 7 ring with no core), 4/1, 0, 0. | Sleep finishes with a new commit (`celebrateCompletion`); the cheer plays only while the mood is digesting or happy. |
| `sleeping/talk.center` | once | eyes `closed` throughout; `mumble1` 90 · `none` 90 · `mumble2` 90 · `none` 90 · `mumble1` + a `z.s` puff in `Y` at (40, 12) 90 · `none` 90 | **540** | beat | A tiny mumbling mouth, with a pale z on the fifth pose. This is the sleep-talk. | The same poke as `talk`. |

**Lifts.** Only `perk.*`, `eager` and `cheer.center` lift. A `+n` frame translates the whole figure, book included,
up `n` px (n ≤ 3). Every lift is preceded by a crouch, and `eager` and `cheer` land on a squash at row 47. Every other
"dip" or "crouch" is a 1-px squash, never a translation.

#### 6.2.2 Which sheet has which look (abs frame ranges)

| Tag | awake | reading `@1` / `@2` / `@3` | happy | hungry | digesting | sleeping | error | curious |
|---|---|---|---|---|---|---|---|---|
| `idle` | 0–33 | 0–84 / 186–270 / 372–456 | 0–26 | 0–16 | 0–5 | 0–31 | 0–12 | 0–7 |
| `attentive.left` | 34–44 | 85–95 / 271–281 / 457–467 | 27–37 | 17–27 | — | — | — | — |
| `attentive.center` | 45–55 | 96–106 / 282–292 / 468–478 | 38–48 | 28–38 | — | — | — | — |
| `attentive.right` | 56–66 | 107–117 / 293–303 / 479–489 | 49–59 | 39–49 | — | — | — | — |
| `expectant.left` | 67–70 | 118–121 / 304–307 / 490–493 | 60–63 | 50–53 | — | — | — | — |
| `expectant.center` | 71–74 | 122–125 / 308–311 / 494–497 | 64–67 | 54–57 | 6–9 | — | — | — |
| `expectant.right` | 75–78 | 126–129 / 312–315 / 498–501 | 68–71 | 58–61 | — | — | — | — |
| `eager` | 79–82 | 130–133 / 316–319 / 502–505 | 72–75 | 62–65 | 10–13 | — | — | — |
| `perk.left` | 83–86 | 134–137 / 320–323 / 506–509 | 76–79 | 66–69 | — | — | — | — |
| `perk.center` | 87–90 | 138–141 / 324–327 / 510–513 | 80–83 | 70–73 | — | — | — | — |
| `perk.right` | 91–94 | 142–145 / 328–331 / 514–517 | 84–87 | 74–77 | — | — | — | — |
| `talk.left` | 95–100 | 146–151 / 332–337 / 518–523 | 88–93 | 78–83 | — | — | — | — |
| `talk.center` | 101–106 | 152–157 / 338–343 / 524–529 | 94–99 | 84–89 | 14–19 | 32–37 | — | — |
| `talk.right` | 107–112 | 158–163 / 344–349 / 530–535 | 100–105 | 90–95 | — | — | — | — |
| `gulp.center` | 113–119 | 164–170 / 350–356 / 536–542 | 106–112 | 96–102 | 20–26 | — | — | — |
| `shake.left` | 120–124 | 171–175 / 357–361 / 543–547 | 113–117 | 103–107 | — | — | — | — |
| `shake.center` | 125–129 | 176–180 / 362–366 / 548–552 | 118–122 | 108–112 | 27–31 | — | — | — |
| `shake.right` | 130–134 | 181–185 / 367–371 / 553–557 | 123–127 | 113–117 | — | — | — | — |
| `cheer.center` | — | — | 128–134 | — | 32–38 | — | — | — |
| `intro` (yawn) | — | — | — | — | — | 38–47 | — | — |
| `outro` (stretch) | — | — | — | — | — | 48–56 | — | — |

These tag sets are the **18 common looks** of `BookwormLook.reachable(for:)` for awake, reading and hungry, plus
`cheer.center` for happy. Digesting has 7 tags, sleeping 2 plus `intro`/`outro`, and error and curious 1 each. That makes
84 (state, look) pairs, and a test asserts that each sheet's tag set **equals** `BookwormArt.requiredTags(state)`.

**The response matrix** (`BookwormState.acceptsGaze`, `acceptsDropPose`, `allows(_:)` in `MenuBar/BookwormPose.swift`):

| State | gaze | drop poses | perk | talk | gulp | shake | cheer |
|---|---|---|---|---|---|---|---|
| awake, reading, hungry | Y | Y | Y | Y | Y | Y | – |
| happy | Y | Y | Y | Y | Y | Y | Y |
| digesting | – | Y (centre only) | – | Y | Y | Y | Y |
| sleeping | – | – | – | Y (sleep-talk) | – | – | – |
| error, curious | – | – | – | – | – | – | – |

`perk`, `talk` and `shake` follow the gaze (`followsGaze`). `gulp` and `cheer` are centre-only. A state with no gaze
folds every beat to `.center`.

#### 6.2.3 Tag names are derived, never typed (spec §4.1, `BookwormArt.swift`)

```
sheet(state)        = "bookworm-\(state.caseName)" + lighting suffix ("" | "-night-dark" | "-night-lit")
small sheet         = "bookworm-small"; small tag = state.caseName
tag(look)           = look.keySegment ?? "idle"     // "attentive.left", "perk.center", ...
tag(look, cover k)  = k == 1 ? tag(look) : "\(tag(look))@\(k)"   // reading only, k ∈ 1…3
missing tag         = "<look>@k" → "<look>" → "idle" → frame 0 of the sheet; a missing sheet draws nothing at the same size
```

#### 6.2.4 Which clip plays (precedence, highest first) and how it plays

1. **Reduce Motion** (`profile == .still`): no beat and no transition. `attentive` folds to `idle`, while `expectant(g)`
   and `eager` stay, because the armed drop is a cue. The tag is **held on f0** (cover 1 for reading).
2. **A beat** (`room.reaction`) that `BookwormLook.beat(_:for:gaze:)` allows. It plays **once** from its `startedAt`
   and holds its last frame until `settleReaction` clears it after `length × slowdown`. A new beat restarts the clock. A
   beat clears any transition.
3. **A transition** (`room.transition`): `intro` or `outro`, always drawn from the sleeping sheet (§6.3). It plays once
   and holds its last frame until `settleTransition` clears it.
4. **The pose loop** `pose.effective(for:reduceMotion:)` (`WormStage.pose`: a drag outranks the pointer, which outranks
   idle). It **loops on the shared clock**: the phase is `(now − SpriteClock.origin) mod (total × slowdown)`, so a pose
   change does not restart at f0, and two worms tick in step.
5. **`idle`**.

| Playback profile | When | Effect |
|---|---|---|
| `full` | default | ms as authored |
| `gentle` | Low Power Mode | every hold × `CicadaMotion.spriteGentleSlowdown` = **2** (loops, beats, transitions, cover cycle and menu bar) |
| `still` | Reduce Motion | f0 only |
| paused | window hidden, `scenePaused`, or a snapshot | f0, with no timeline |

The timeline (`SpriteFrameSchedule`) wakes only at the union of the visible clips' frame boundaries; there is no fixed
frame rate. Reading also schedules a wake at each cover boundary.

#### 6.2.5 Caps every tag satisfies (`Theme/CicadaMotion.swift`, TODO ruling 18)

| Token | Value | Tightest shipped tag |
|---|---|---|
| `spriteFrameMin` / `spriteFrameMax` | 40 ms / 4,000 ms per frame | 50 ms (`blink.half` in attentive); 2,300 ms (attentive's last look) |
| `spriteLoopMin` / `spriteLoopMax` | 0.4 s / 30 s per looping tag | `eager` 460 ms; small `digesting` 500 ms; reading `idle` 21,840 ms |
| `spritePerkMax` | 0.4 s | `perk.*` 360 ms |
| `spriteBeatMax` | 0.8 s | `cheer.center` 720 ms; `gulp` 650; sleeping `talk` 540; `talk` 500; `shake` 430 |
| `spriteTransitionMax` | 1.6 s | `intro` 1,420 ms; `outro` 1,240 ms |
| `spriteTimerTolerance` | 0.2 | the menu bar's one-shot frame timers |


### 6.3 Transitions: the yawn and the stretch (`bookworm-sleeping` only)

#### 6.3.1 `intro`, the yawn: 10 frames, 1,420 ms (abs 38–47)

| f | Start | ms | Frame (measured book px / `j` lid px / `r` mouth px) |
|---:|---:|---:|---|
| 0 | 0 | 140 | from `sit`: `half` + `book.close3` (the book shuts, tilted; when coming from reading it follows the open book) — 154 / 22 / 0 |
| 1 | 140 | 120 | `talk1` + `book.closed` — 221 / 22 / 6 |
| 2 | 260 | 260 | `yawn` (6 × 5 oval) + head +1 — r 26 |
| 3 | 520 | 200 | `yawn` — r 26 |
| 4 | 720 | 120 | `talk1` — r 6 |
| 5 | 840 | 120 | `closed` |
| 6 | 960 | 120 | `slump` +1, with a tilted book (154) |
| 7 | 1,080 | 120 | `slump` +1 and `rest.sleep` (the book lands; 111) |
| 8 | 1,200 | 120 | `slump` |
| 9 | 1,320 | 100 | `slump` (it hands off to `sleeping/idle`) |

#### 6.3.2 `outro`, the stretch: 9 frames, 1,240 ms (abs 48–56)

| f | Start | ms | Frame (measured `j` px; `W` returns at f7) |
|---:|---:|---:|---|
| 0 | 0 | 120 | from `slump`: `stretch1` (+1 tall, tail up) — j 12 |
| 1 | 120 | 160 | `stretch2` (+2 tall) + `blink.half` — j 44 |
| 2 | 280 | 160 | `stretch2` + `talk1`, still `blink.half` (A9) — j 44 |
| 3 | 440 | 240 | `stretch2` + `yawn` — j 12, r 26 |
| 4 | 680 | 140 | `stretch1` + `half`, with a tilted book (154) |
| 5 | 820 | 100 | `sit` + `blink.half`, and the book stands closed (221) |
| 6 | 920 | 80 | `sit` + `closed` |
| 7 | 1,000 | 120 | `sit` + `center`: the highlighted open eye returns for the first time (7 `W` px) |
| 8 | 1,120 | 120 | `sit` |

Neither transition has a key-frame rule: they never play under Reduce Motion, and their f0 is never held.

#### 6.3.3 When they play (`RoomModel.moodChanged`, `BookwormView`)

| Rule | Code fact |
|---|---|
| Only a **real mood edge** animates | Each call first clears any transition, and drops a beat the new state does not allow. A transition starts only if all of these hold: Reduce Motion is off, `old != "awake"`, `new != awake`, `old != new`, and no beat is still playing. Cold starts and refreshes show the state at once. |
| **Yawn** (`.yawn` = `intro`) | The new mood is `.sleeping`, from any state other than awake: reading, happy, hungry, digesting, error or curious. |
| **Stretch** (`.stretch` = `outro`) | The old mood was `sleeping` and the new one is `digesting`, `happy`, `reading` or `hungry`. **Never to `error`**, whose X eyes must show at once, and never to or from `awake`. |
| Always drawn from the sleeping sheet | `BookwormArt.transitionClip` resolves `bookworm-sleeping` with the current lighting (`-night-dark` or `-night-lit` at night), whatever the current state. The outro plays after the mood has already left sleeping. |
| Once, then hold | The transition plays from `startedAt` and holds its last frame until `settleTransition` (length × slowdown). Then the new state's pose loop resumes at its shared-clock phase. |
| A beat wins | `play()` sets `transition = nil`, so a transition never resumes half-played behind a beat. |
| Room only | The small set never shows a transition (`size.set == .small`). |
| Known edge | The outro ends with a standing closed book, so stretch → reading switches to an open book in one frame. There is no opening beat; this is documented, not invented. |


### 6.4 The 18 × 18 menu-bar set (`bookworm-small`, 8 tags, 32 frames)

The owner's own head design: two round lenses ringed in `K` with lime (`m` #ACEC62) interiors and **3 × 3 plus-shaped
("cross") `K` pupils**, a bridge, a dome on rows 0–3, a short temple arm at columns 16–17 (rows 7–8), and an S-neck
down to row 15. **Rows 16–17 are transparent in every frame**, reserved for the code overlays. A bob or droop is a 1-px
squash of the neck (the head and glasses drop 1 px), never a lift off row 0. There is one sheet with dark outlines for
both the light (#ECECEC) and dark (#1E1E1E) menu bar. There is no template image and no appearance variant. The pixels
below were read from the shipped PNG.

| Tag (abs) | f · ms | Total | What each frame shows |
|---|---|---:|---|
| `awake` (0–4) | rest 1800 · blink 100 · rest 1400 · bob 300 · rest 600 | 4,200 | Plus pupils held. On the blink each pupil becomes a 1-row `K` lid line across its lens (row 7). The bob drops the head and glasses 1 row and shortens the neck by one row. |
| `sleeping` (5–8) | 700 · 700 · 700 · 700 | 2,800 | Lid lines (row 7) in every frame; never a plus pupil. A **tiny 2 × 2 z** at columns 16–17 sits on rows 3–4 in `Z` (f0), then rises to rows 2–3 in `Z` (f1), rows 1–2 in `Y` (f2) and rows 0–1 in `Y` (f3). On f3 a 1-px neck bulge (row 12) is the breath. |
| `digesting` (9–10) | chew1 250 · chew2 250 | 500 | There is no mouth in this design. Chewing is a 1-px neck bulge that steps down: row 11 on f0, row 12 on f1. |
| `happy` (11–15) | rest 1600 · bob 160 · rest 160 · sparkle 400 · rest 1200 | 3,520 | A rest pose, a 1-px neck-squash bob, then a **single `q` sparkle pixel** at (row 2, column 16) beside the dome. Plus pupils throughout; the closed happy eyes are not used here. |
| `curious` (16–19) | rest 1200 · brow up 300 · rest 900 · tilt 400 | 2,800 | A 3-px `K` brow on the dome over the right lens (row 2, columns 10–12) lifts to row 1 on f1. On f3 both plus pupils shift 1 px left. **Columns 9–17 × rows 11–17 carry no glasses ink**, because the badge is drawn there. |
| `hungry` (20–23) | half lids 2000 · closed 400 · half lids 1600 · droop 800 | 4,800 | Half lids: the top row of each lens interior (row 4) is solid `K` above the plus pupils. f1 is lid lines only. f3 droops the head 1 px with the half lids kept. |
| `reading` (24–27) | pupils left 600 · right 600 · page line moves 150 · left 600 | 1,950 | A tiny open book (7 × 4: `BCCbCCB / BPCbPCB / BCCbCCB / BBBBBBB`; 28 book px) at columns 0–6, rows 12–15, below the left lens, with row 11 clear. On f0 and f3 both plus pupils are 1 px left of rest. On f1–2 the right lens's pupil is 1 px right of rest and the left one is at rest. On f2 the grey page line moves one column (`BCPbPCB`). |
| `error` (28–31) | rest 600 · tremble 100 · rest 400 · drop lower 400 | 1,500 | **Black diagonal X eyes** (`K.K / .K. / K.K`) in both lenses in every frame, plus a two-pixel cyan drop (`S`) at column 17, rows 2–3. f1 trembles the neck 1 px left (rows 11–15). f3 drops the sweat 1 px, to rows 3–4. |

**Drawn in code, not in the sheet** (`MenuBar/BookwormOverlays.swift`, composited onto every frame by
`BookwormRenderer.smallImage` with the legacy nine-key palette):

| Overlay | State | Pixels |
|---|---|---|
| Badge | `.curious(count)` | A `q` (#FFCB57) pill 7 rows tall at rows 11–17, right-aligned, `digits × 4 + 1` wide. The count is clamped to 1…99 and drawn as 3 × 5 digits in `o` (#2B2140) starting at row 12. |
| Stage dots | `.sleeping(stage)` | Row 17, columns 1 / 5 / 9 / 13 / 17. Dot `i` is lit gold `a` (#E0A93A) when `i < stage` (the active stage 1…5) and plum `o` otherwise. The room worm has no dots or nightcap: the stage strip, the sentence and VoiceOver say the stage there. |
| (none) | every other state | blank |

**Playback in the menu bar** (`MenuBarManager.swift`): chained one-shot `Timer`s. Each frame waits its own duration ×
slowdown (2 under Low Power), with 20 % tolerance. The tag always loops. The step restarts at f0 when the state changes,
when the mascot is switched, or when Reduce Motion turns on. Animation stops (and holds the current frame, or f0 under
Reduce Motion) while the item is hidden or the displays sleep. The image cache is keyed by mascot, `spriteKey`
(`curious|<count>`, `sleeping|<stage>`), packed-cell index and point size; the image is 18 pt, 1 pt per art pixel. The
menu bar derives its state as sleeping > error > digesting (< 6 s after a finish) > hungry (48 h without an ingest) >
curious (inbox > 0) > happy, and `awake` before the first poll. **It never shows `reading`**. The small set is also
drawn in the app wherever a `BookwormView` is below 48 pt with no lattice. Home (24 pt) uses the menu bar's derivation.
Getting started (24 pt) maps its steps to awake, **reading** (waiting), sleeping(stage), happy and error; this is where
the small `reading` tag appears. Contributors draws the small `happy` f0 as the system avatar. The small set ignores
poses, beats and transitions. The 48 pt intake panel and the 96 pt empty states use the room sheets.


### 6.5 The night variants: `bookworm-<state>-night-dark` and `-night-lit`

| Fact | Value |
|---|---|
| Sheets | 16 = 8 states × {`night-dark`, `night-lit`}: awake, reading, happy, hungry, digesting, sleeping, error and curious. There is **no** night small sheet, because the menu bar has no room light. |
| Parity with day (verified on the shipped files) | Identical `frameTags` (names, from/to), identical per-frame `duration` arrays, identical `slices` (including `errorLensL`), identical packed frame rects, identical PNG size and an **identical alpha mask**. Only the RGB differs. That is 2,126 night frames checked pixel for pixel against the declared relight. |
| Relight | Each colour is mapped through `palette.json` `night.ramps` according to its band in `room-light-map.json`: shadow, moon-edge, moon, lamp-edge, lamp-low, lamp-mid or lamp-hot. The lamp bands apply only when lit, and the lamp-facing side of the worm is warmer. There is no interpolation, gradient, dithering or fractional alpha. `K` becomes #070A13 everywhere. |
| Marks kept legible | The z's keep their exact day colours in both variants: 653 `Z`/`Y`/`X` pixels summed over the 57 sleeping frames, 533 in the de-duplicated packed sheet. So do the sparkles: 35 `q`/`Q` pixels in each of the happy and digesting sheets. `verify_night.py` checks them frame by frame: 2 × (653 + 35 + 35) = 1,446 glyph-pixel checks (`SCENERY_REPORT.md`). The curious `?` uses a registered pale ramp (its `K` becomes #AAB5D8). Measured minimums: closed-lid contrast 38.58, and open-book line contrast 16.13 (the grey lines stay darker than the cream). The X eyes, sweat and every question frame pass. |
| Selection | `RoomLighting` is `.dark` iff `time == .night` or `base == .rainy` (`Scenery.lighting`), independently of the worm's mood. In the dark the suffix is `-night-lit` when the lamp is lit (`page.lampLit`, i.e. a Sleep schedule is on) and `-night-dark` otherwise. In daylight there is no suffix, whatever the lamp. Transitions, beats and the reading cover cycle use the same lighting variant. Per the scenery spec, a lighting swap crossfades with the pane, and is instant under Reduce Motion. |
| Generator | `lua/build_night.lua`, headless, from the saved day art (manifest `script`). |


### 6.6 State marks that must survive every frame (R-Z1, spec §4.4)

Frame 0 of every tag is its **key frame**: it is what Reduce Motion holds and what a legend thumbnail shows, so it
always carries the marks. The only exceptions are `intro` and `outro`.

| State | Mark | The tested rule | Measured on the shipped sheets |
|---|---|---|---|
| every room state | the glasses | ≥ 30 `D` px and ≥ 6 `L` px in every frame of every tag | `D` 70–71 (error 66, because of the widened left interior); `L` 37–38 |
| every room state | the held book (R-Z1, as amended by ruling 18) | ≥ 20 px with a `book.*` role in every frame of every tag, **transitions included** | minimum book px per sheet: awake, happy, hungry, digesting, error and curious 221; sleeping 111 (`rest.sleep`); reading 65 (swap f79) |
| reading | the book | ≥ 20 `book.*` px in every frame of every reading tag; the small `reading` tag ≥ 8 | room 65–238; small 28 |
| sleeping | eyes shut, and a z on the key frame | Every frame of `idle` and `talk.center` has ≥ 4 `j` px and **0** `W` px. `idle` f0 has ≥ 3 `Z` px. Small `sleeping`: inside each lens slice, the `K` pixels lie in **one row** and number ≥ 2 (a lid line, never the plus pupil). | `j` = 12 and `W` = 0 on every idle and talk frame; f0 `Z` = 7 |
| error | black X eyes + the drop (worried brows kept) | Every room frame has the centred 3 × 4 left and 6 × 5 right diagonal `K` Xs, a green gap from each ring, and ≥ 1 `S` px. The tremble moves both Xs together. Every small `error` frame has both 3 × 3 diagonal Xs and ≥ 2 `S` px. No red is used. | room `S` 3–9 in every frame; small `S` = 2 in every frame |
| happy, digesting, hungry, awake, curious | (no tested mark) | covered by the art review: happy brows, happy ∩ eyes and chew, half lids and tired brows, the neutral face, and the `?` in every curious frame | |
| every state, small set | the head and glasses | `K` + `m` only on rows 0–15 (plus each state's own mark); rows 16–17 empty for the code overlays | |

**What a response may never do** (the matrix in §6.2.2): a sleeping worm's eyes stay shut, because no gaze, drop pose,
perk, gulp, shake or cheer is reachable while sleeping. The error X eyes and drop are never covered, because error takes
no response and no transition goes to error. Curious takes no response, so its `?` is never hidden.


### 6.7 Known edges and open items (from the reports)

- The stretch → reading handoff pops from a standing closed book to an open book in one frame (§6.3.3).
- A reading pose or beat that spans a cover boundary (once every ~22 s) changes the book's colour mid-pose (spec §11 Q6;
  accepted).
- B12 (a narrower right lens on the menu head) is not applied and waits for the owner's decision on lens size.
- `brows.mad` is drawn and shown only in an unbundled demo (spec §11 Q3).
- The owner's motion review in `app/CicadaApp/Art/sprites/bookworm-2026-10-01/preview.html` and on the Sleep page remains
  a merge gate (`INTEGRATION_REPORT.md`).

### 6.8 What `<character-name>` must reproduce (the adaptation checklist)

Every row is required. "Equivalent" means the same state fact and timing role drawn on `<character-name>`'s anatomy
(the anatomy map, §5.1); the spec names each equivalent before any art.

| # | Bookworm animation | Where (§) | `<character-name>` equivalent must… | Contract checks |
|---|---|---|---|---|
| [ ] 1 | `awake/idle`: breath with lead-and-follow, irregular blinks incl. a double, a tail flick | 6.1.1 | breathe (torso leads, head follows), blink irregularly with one double, add one secondary motion | ≥ 3 blink runs, max/min gap ≥ 1.6; glasses/identity marks; ≥ 20 prop px |
| [ ] 2 | `reading/idle` × 3 covers: eye-tracked lines, 3 uneven page flips, close, **book swap** behind the body, next cover rises and opens | 6.1.2 | read with tracking eyes, turn pages unevenly, close, tuck the prop away and raise the next one; three covers by the cyclic recolour; each tag ends on the next cover | identical per-frame ms across `idle`, `@2`, `@3`; ≥ 20 prop px every frame; both covers ≥ 6 px in swap frames; seams pixel-equal |
| [ ] 3 | `sleeping/idle`: shut eyes, slow breath, **z → zz → zzz** rising, fading `Z → Y → X`, shrinking | 6.1.3 | keep the eyes shut (one-row lids), breathe slowly, run the z path inside the z box clear of the clock | ≥ 4 `j`, 0 `W` every frame; ≥ 3 `Z` on f0; glyphs ≥ 3 × 3, never overlapping |
| [ ] 4 | `happy/idle`: breath under happy brows, blinks, a lens glint, a sway | 6.1.4 | show the happy face, glint across an eye or lens, sway 1 px | ≥ 2 blink runs, irregular |
| [ ] 5 | `hungry/idle`: heavy half lids, nod off, jolt awake, slow blink, small yawn | 6.1.5 | show tiredness with lids that follow every gaze | half lids in rest frames |
| [ ] 6 | `digesting/idle`: two chews, swallow bulge, smile | 6.1.6 | chew twice, swallow (1-px bulge travelling high on the throat/body), smile | — |
| [ ] 7 | `curious/idle`: floating `?` that bobs, head tilt, two blinks | 6.1.7 | float the `?` in every frame (D7 box) | `?` in every frame |
| [ ] 8 | `error/idle`: **black X eyes** every frame, worried brows, sweat drop slides and re-forms, tremble, no blink | 6.1.8 | wear centred black X eyes with a green (body-colour) gap, a sweat drop in every frame, no blink, no red | X pattern + ≥ 1 `S` every frame; `errorLensL` slice |
| [ ] 9 | `attentive.<g>`: held gaze, two irregular blinks, a glance 1 px further | 6.2.1 | look toward g (reading looks up from the page), glance, blink | f5 ≠ f0; gaze variants same ms |
| [ ] 10 | `expectant.<g>`: ready face, dip, rise | 6.2.1 | anticipate a drop | 720 ms calibration |
| [ ] 11 | `eager`: crouch, hop +2, +1, land on a squash | 6.2.1 | hop at most 3 px after a crouch; land widening the base | 400–800 ms |
| [ ] 12 | `perk.<g>`: crouch, bright-eyed hop, settle | 6.2.1 | perk toward g | ≤ 400 ms |
| [ ] 13 | `talk.<g>`: six mouth poses with head bobs | 6.2.1 | talk | ≤ 800 ms |
| [ ] 14 | `gulp.center`: open, paper scrap enters, bulge travels down, smile (reading lowers the book) | 6.2.1 | take in the paper and swallow it visibly | ≤ 800 ms |
| [ ] 15 | `shake.<g>`: sad brows, head oscillates around its gaze position | 6.2.1 | refuse gently (the only use of the sad face) | ≤ 800 ms; settles on the gaze head |
| [ ] 16 | `cheer.center`: crouch, rise to +3 with sparkles, happy eyes, squash landing, settle | 6.2.1 | celebrate (happy and digesting only) | ≤ 800 ms; sparkles keep their day colours at night |
| [ ] 17 | `sleeping/talk.center`: shut-eye mumble with a pale z puff | 6.2.1 | sleep-talk | ≤ 800 ms; eyes shut every frame |
| [ ] 18 | `intro` (yawn) and `outro` (stretch) on the sleeping sheet | 6.3 | yawn into sleep (closing the prop) and stretch out of it | ≤ 1,600 ms each; outro's last frame checked against 4 key frames |
| [ ] 19 | The 18 × 18 set: 8 tags (blink-and-bob, rising tiny z, neck-bulge chew, sparkle, brow lift + tilt, half lids + droop, tiny book with pupils moving, black X eyes + drop) | 6.4 | redraw the head for 18 × 18 (never downsample) with the same 8 state facts | rows 16–17 empty; badge zone clear; lids, Xs, drop, book px |
| [ ] 20 | 16 night sheets | 6.5, 7.6 | be generated by the relight, never drawn | exact relight; identical alpha; glyph colours kept |
| [ ] 21 | The state marks on every frame | 6.6 | carry its identity marks on every frame (D6) | §6.6's table, adapted in the spec |

Not reproduced: `brows.mad` and the mad demo (D14); the nightcap and the room stage dots (retired by R-BW1).

---

## 7. Lighting

How the study room is lit by day and in the dark, and exactly how `<character-name>`'s 16 night sheets are made and
checked. Sources: `$BW/palette.json`, `$BW/room-light-map.json`, `$BW/room-plan.json`, `$BW/lua/build_night.lua`,
`$BW/tools/night_palette.py`, `$BW/tools/verify_night.py`, `$BW/SCENERY_REPORT.md`, `$SRC/Theme/Scenery.swift`,
`$SRC/Views/Sleep/DeskScene.swift`, TODO ruling 18 R-BW6. Numbers marked *recomputed* were measured from the shipped
files at `e0c21b45` for this guide.

### 7.1 Coordinate systems (three conventions; mixing them is the classic bug)

| Data | Origin | Units | Used by |
|---|---|---|---|
| `room-plan.json` layers, `worm`, `pile`; `DeskScene.plan` in Swift | **bottom-left** (`"origin": "bottom-left"`) | room cells, 160 × 64 | the app's layout and the art verifiers |
| `room-light-map.json` (`moon`, `lamp`) | **top-left** (`"origin": "top-left"`) | room cells, 160 × 64, one character per cell | `build_night.lua`, `verify_night.py` |
| Aseprite slices (`glass`, `seat`, `ink`, `shade`, `glow`, `eye`, `lens*`) and every in-sheet pixel | **top-left of that sheet's canvas** | sheet pixels (1 px = 1 room cell) | the app's hotspots and the registration checks |

Conversion from a plan layer to the light map, as `build_night.lua` does it: `topLeftY = 64 − layer.y − layer.h`. A
sheet pixel `(px, py)` lands on light-map cell `(layer.x + px, topLeftY + py)`. The character (plan `x=36, y=9, h=48`)
is relit at top-left **(36, 7)**, the offset `verify_night.py` also uses. On screen one cell is
`RoomLattice.cell(uiScale) = max(2, round(3 × uiScale))` points: the 160 × 64 room is 480 × 192 pt at 1.0 and
640 × 256 pt at 1.4.

### 7.2 When the room is dark, and what the lamp means

- **The room is dark iff `time == .night || base == .rainy`** (R-BW6; `Scenery.lighting`), in every scenery mode. Dusk
  keeps the day-lit interior (only the sky changes). Rain by day is dark. The character's mood never changes the
  lighting, and lighting never changes the mood.
- **The lamp means the Sleep schedule**, never scenery: `lampLit = schedule.enabled`
  (`$SRC/Views/Sleep/SleepPageModel.swift:157`; Settings passes `sleepVM.schedule.enabled`).
- **The fly** is the lit lamp's art: drawn only while `lampLit`, in either lighting, always its `buzz` tag, never
  relit.
- **By day the lamp is authored art, not a relight.** With the lamp lit, `room-backdrop/lit` differs from `dark` only
  inside its `glow` slice (0,10,26,54): 565 changed pixels in x 0–25, y 10–63, in `room.glow.0`, `room.glow.1` and
  `room.wall.1` (the wall around and under the shade, rows 10–33, and a small floor pool, rows 60–63), same alpha.
  `room-lamp/lit` differs only inside its `shade` slice (2,1,14,11): a warm underside and rim, 37 pixels, same
  silhouette. The fly appears. The window, plant, bean bag and mug stay `idle`. The character draws its day sheet in
  both lamp states: the day glow ends at room x 25 and never reaches the canvas (x ≥ 36).
- **The menu bar has no room light**: the 18 × 18 set has no night variant.

**Which tag each layer draws** (`RoomArt.tag`, `$SRC/Views/Sleep/DeskScene.swift:49-62`):

| Layer (plan z) | Day room, lamp off | Day room, lamp on | Dark room, lamp off | Dark room, lamp on |
|---|---|---|---|---|
| `backdrop` (0), `lamp` (6) | `dark` | `lit` | `night-dark` | `night-lit` |
| `clock` (1) | `face` (+ hands) | `face` | `face-night` (+ `-night` hands) | `face-night` |
| `pane` (2) | `room-weather/<base>-<time>` | same | same | same |
| `skyfx` (3) | `room-skyfx/<overlay>-<time>` or nothing | same | same | same |
| `window` (4), `plant` (5), `beanbag` (8), `mug` (9) | `idle` | `idle` | `night-dark` | `night-lit` |
| `fly` (7) | none | `room-fly/buzz` | none | `room-fly/buzz` |
| **the character** | `<character-name>-<state>` | `<character-name>-<state>` | `<character-name>-<state>-night-dark` | `<character-name>-<state>-night-lit` |

The suffix comes from `RoomLighting.suffix(lampLit:)` (`$SRC/Theme/Scenery.swift:49-52`): `""` by day, `-night-lit` or
`-night-dark` when dark. Transitions, beats and the reading cover cycle use the same lighting variant. A lighting
change crossfades the whole art layer with the pane in 0.4 s, instantly under Reduce Motion (§8.6).

### 7.3 The light map (`$BW/room-light-map.json`)

`{version: 1, cols: 160, rows: 64, origin: "top-left", note, moon[64], lamp[64]}`; each row is a 160-character string
of band digits. *"Pixel light bands: moon 0-2 always; lamp 0/3-6 only when lit. Higher band wins. No interpolation,
alpha or noise. The projected window has a mullion gap."*

| Map | Legal digits | Cells per band | Extent (top-left x, y) | Shape |
|---|---|---|---|---|
| `moon` | `0 1 2` | 0: 9,150; 1: 254; 2: 836 | bands 1–2 within x 17–69, y 36–63 | The window projected down-right onto the lower wall, bean bag and floor. Band 2 is the lit patch, band 1 its edge; a band-1 mullion gap runs down the middle and a band-1 break sits at the baseboard rows (y 54–55). |
| `lamp` | `0 3 4 5 6` | 0: 5,460; 3: 1,359; 4: 1,619; 5: 1,083; 6: 719 | x 0–79 (rightmost lit column per row 59–79) | Rings around the shade. Band 6 has two lobes within x 0–25: the wall around and under the shade (y 12–38) and the floor under the lamp (y 57–63). Bands 5, 4, 3 step outward. The baseboard's top row (y 54) is lamp-edge across x 0–61. |

The verifier enforces: every row 160 characters, legal digits only, all `0` from column 110 on (the pile column is never
lit); every legal band used at least once; origin and size exactly as declared.

**Consequences:**
- The lamp pool ends at x 79. The mug (x 100–107) and the right part of the character canvas (room x 80–99) are
  **identical in `night-dark` and `night-lit`**.
- **With the lamp lit, the warm bands replace the window light almost everywhere.** Lamp bands 3–6 always beat moon
  bands 1–2 and the whole moon patch lies inside the lamp's reach: only 5 of the 1,090 moonlit cells keep a moon band
  in `night-lit` (x 60–63, y 53–55, band 1; *recomputed*). **The cool window spill is a `night-dark` feature.**

**The light over the character canvas** (*recomputed*; canvas columns and rows, top-left origin; each character is the
highest band in a 2 × 2 block; `.` is band 0). This is what your character's pixels will be relit with:

```
Character canvas, UNLIT (night-dark): moon only
col→     0    10   20   30   40   50   60
row 0- 1 ................................
row 2- 3 ................................
row 4- 5 ................................
row 6- 7 ................................
row 8- 9 ................................
row10-11 ................................
row12-13 ................................
row14-15 ................................
row16-17 ................................
row18-19 ................................
row20-21 ................................
row22-23 ................................
row24-25 ................................
row26-27 ................................
row28-29 22222222222.....................
row30-31 22222222222.....................
row32-33 22222222222.....................
row34-35 222221222211....................
row36-37 222222222221....................
row38-39 222222222221....................
row40-41 2222221222211...................
row42-43 2222222222221...................
row44-45 22222222222211..................
row46-47 22222221222211..................
```

```
Character canvas, LIT (night-lit): max(moon, lamp)
col→     0    10   20   30   40   50   60
row 0- 1 4444444443333333333.............
row 2- 3 44444444443333333333............
row 4- 5 444444444443333333333...........
row 6- 7 444444444443333333333...........
row 8- 9 544444444444333333333...........
row10-11 5444444444443333333333..........
row12-13 5444444444443333333333..........
row14-15 5544444444444333333333..........
row16-17 5544444444444333333333..........
row18-19 5544444444444333333333..........
row20-21 5544444444444333333333..........
row22-23 5544444444444333333333..........
row24-25 5444444444443333333333..........
row26-27 5444444444443333333333..........
row28-29 444444444444333333333...........
row30-31 444444444443333333333...........
row32-33 44444444443333333333............
row34-35 44444444443333333333............
row36-37 4444444443333333333.............
row38-39 444444443333333333..............
row40-41 44444433333333333...............
row42-43 4444433333333333................
row44-45 444333333333333.................
row46-47 43333333333333..................
```

- **Unlit:** only the lower-left of the canvas (cols 0–27, rows 29–47; the 2 × 2 preview rounds this to row 28) gets
  moonlight (band 2, a band-1 edge and mullion); everything else is band 0 (shadow). Cells over all 3,072 canvas
  pixels: band 0 2,610, band 1 94, band 2 368.
- **Lit:** lamp bands 3–5 cover cols 0–43; band 5 only at cols 0–2, rows 9–27 (43 cells; the 2 × 2 preview rounds this
  to cols 0–3, rows 8–27); band 6 never reaches the canvas;
  **cols 44–63 are never lamp-lit**, so whatever the character draws there is identical in both night sheets.
  Cells: band 0 1,171, band 1 3, band 3 979, band 4 876, band 5 43.
- So the lamp-facing (left) side warms; the right side stays in shadow. Design the identity marks to read in band 0.
- Full-resolution dump (cwd: repository root):

```sh
python3 - <<'EOF'
import json; m = json.load(open('app/CicadaApp/Art/sprites/bookworm-2026-10-01/room-light-map.json'))
for lit in (False, True):
    print('night-lit' if lit else 'night-dark')
    for y in range(7, 55):
        print(''.join(str(max(int(m['moon'][y][x]), int(m['lamp'][y][x]) if lit else 0)) for x in range(36, 100)))
EOF
```

Appendix B has the same 2 × 2 preview over the whole room.

### 7.4 `palette.json`: keys, roles, derived colours

`$BW/palette.json` (version `2026-10-01`) is the single palette. The Lua builders (`H.paletteFromJson`), the Python
verifiers (`night_palette.py: palette_data / allowed_colors`) and the Swift acceptance loader all read it, and all three
accept exactly the same allowed-RGB set. Top level:

```
{ version, note, colors[81], night{version, note, bands[7], ramps{81 keys × 7}, glyphs{question}},
  scenery{version, note, ramps{dusk{81}, night{81}}, colors[14]}, clock{version, colors{6}} }
```

- **`colors`, the authoring keys:** `{"key": "<one char>", "hex": "#RRGGBB", "group": ..., "role": "<dotted.role>"}`.
  Legal keys and the 87-key budget are in §5.2; 81 are used; the free keys are `] ^ e { } ~`. Groups: room 26,
  weather 26, book 11, worm 9, fx 6, fly 2, spine 1. Hexes are unique across `colors`.
- **Role prefixes read by tests:** `celestial.` (sun, moon, star), `cloud.`, `book.`, `worm.lid`, `fx.sweat`. A colour
  in one of those roles is used for nothing else, because the visibility and contrast checks find pixels by role.
- **Derived colours are declared, never keyed** (*"Derived RGB ramps consume no authoring keys"*):

| Section | Shape | Coverage rule (asserted in `night_palette.py`) | Distinct RGBs |
|---|---|---|---|
| `night.ramps` | `key → [7 hex]`, indexed by band | every `colors` key, exactly 7 entries; `bands` equals the fixed list | 530 |
| `night.glyphs.question` | `box {x:45,y:16,w:4,h:9}` plus `colors {outline:#AAB5D8, core:#FDFDFD}` | the box must be exactly that | — |
| `scenery.ramps.dusk`, `scenery.ramps.night` | `key → hex` | both cover every `colors` key | 135 |
| `scenery.colors` | `[{id, hex, role}]`, 14 overlay colours | unique ids | — |
| `clock.colors` | `{face, rim, second, face-night, rim-night, second-night}` | exactly these six | — |

Together the file allows **699 distinct RGBs** (81 authored plus all derived). Lua loads the derived set into
`pal.derived`; `H.assertPalette` accepts it; `H.applyUsedPalette` writes only the colours a file actually uses into its
display palette (so adding a key never changes another file's bytes).

### 7.5 Night bands and ramps; authoring a ramp for a new key

`bands` is the fixed list `["shadow", "moon-edge", "moon", "lamp-edge", "lamp-low", "lamp-mid", "lamp-hot"]`, indexed
0–6. `ramps[key][band]` is that day colour's night colour under that band: a table lookup, never arithmetic. The values
are data; no generator in the repo recomputes them. They form two families (*recomputed* medians over the 75 keys with
non-constant ramps; luminance `.2126R + .7152G + .0722B`):

| Band | Name | Median luminance vs day | Median warmth (R − B) | Character |
|---|---|---:|---:|---|
| 0 | shadow | 23.6 % | −21 | deep cool blue-grey |
| 1 | moon-edge | 34.5 % | −29 | faint cool window edge |
| 2 | moon | 46.4 % | −34 | the cool window-light patch |
| 3 | lamp-edge | 31.1 % | +4 | neutral to slightly warm, the edge of the pool |
| 4 | lamp-low | 38.4 % | +18 | warm |
| 5 | lamp-mid | 50.7 % | +49 | warmer |
| 6 | lamp-hot | 64.3 % | +71 | hottest, beside the shade and under the lamp |

Every ramp is strictly increasing in luminance within each family (0 < 1 < 2 and 3 < 4 < 5 < 6). Lamp-edge is brighter
than shadow for all 75 keys and darker than moon for 70.

**Declared exceptions** (reuse them as they are):
- **`K` (outline, `#090707`)** is a constant `#070A13` in all seven bands: a cool near-black that never glows.
- **`Z`, `Y`, `X` (the z's) and `q`, `Q` (sparkles)** keep their day hex in every band, so the state glyphs read the
  same in the dark (1,446 per-frame glyph-pixel checks across the bookworm's night sheets).
- **`P` (page grey)** falls hardest (14–32 % of day), so the open book's lines stay darker than the cream page.
- **`S` (sweat)** stays light; `j` (lid) and `K` on the X eyes keep contrast against the body.
- **The `?` glyph** does not use the ramps: inside the canvas box (45, 16, 4, 9) on the curious sheets, `K` becomes
  `#AAB5D8` and `W` becomes `#FDFDFD` (D7).

**Authoring a ramp for a new key (D3):**
1. Find the existing key nearest in hue and luminance (Appendix A) and start from its 7 values scaled to your day
   luminance, keeping the family medians above as the target.
2. Keep 0 < 1 < 2 and 3 < 4 < 5 < 6 in luminance; bands 0–2 cool (R − B < 0), 3–6 warming.
3. No value may be a reserved hue (§5.2). Derived values may repeat across keys.
4. If the key is a state mark (lids, X eyes, sweat, a prop's lines), make its night contrast clear the floors in §7.7.
5. Add `scenery.ramps.dusk[key]` and `scenery.ramps.night[key]` too (coverage is asserted even though only pane pixels
   use them): the convention for non-sky keys is `night = night.ramps[key][1]` (52 keys do this) and a rose-tinted
   `dusk` like its nearest key's.
6. Check: `python3 -c "import sys; sys.path.insert(0,'$BW/tools'); import night_palette as n; n.palette_data(); print('palette ok')"`
   (cwd: repository root) prints `palette ok`; then both pipelines (§4.7 Accept).

Appendix A lists all 81 keys × 7 bands plus the pane tints.

### 7.6 The relight, and how `<character-name>`'s sheets are relit

The algorithm (`build_night.lua`, headless, deterministic, "never a GUI or a clock"):

```lua
-- per opaque pixel p of a sheet placed at plan (x, topLeftY)
band = moon[topLeftY + p.y][x + p.x]                                  -- 0, 1 or 2
if lit then band = max(band, lamp[topLeftY + p.y][x + p.x]) end       -- 0 or 3–6
pixel = ramps[dayRGB(p)][band + 1]                                    -- an undeclared day pixel is an error
-- curious only: inside the question box, K becomes outline #AAB5D8 and W becomes core #FDFDFD
```

- **Unlit (`night-dark`)** uses the moon map alone (bands 0–2); **lit (`night-lit`)** uses `max(moon, lamp)`.
- No blending, dithering, gradients or fractional alpha. The alpha mask is copied exactly.
- **Relit by the bookworm's run:** every `room-plan.json` layer except `pane`, `skyfx`, `fly` and `clock` (backdrop,
  window, plant, lamp, bean bag, mug, which gain `night-dark`/`night-lit` tags on their own sheets) and the 8 worm
  states (16 new sheets).
- **Not relit:** the sky (time-tinted instead, §8.7), the overlays (own colours), the fly (exists only when lit), the
  clock (own dark colours), the spines (the real pile is UI), the 18 × 18 set.

**For `<character-name>`** (`$ART/lua/build_mascot_night.lua`, the worm half of `build_night.lua`, §4.6):

1. Read `$BW/palette.json`, `$BW/room-light-map.json` and `$BW/room-plan.json` (`plan.worm` gives (36, 9, 64, 48), so
   top-left (36, 7)).
2. For each of the 8 states and each lamp state, open `$ART/src/<character-name>-<state>.aseprite`, and for every tag
   and every frame, flatten it, relight it and append it with the same duration (`H.recorder`, tags created last).
3. Copy every slice exactly; `H.assertPalette`; `H.applyUsedPalette`; save
   `$ART/src/<character-name>-<state>-night-{dark,lit}.aseprite`.
4. Never touch a room source and never relight the small sheet.
5. Freeze the day art first: `tools/day_art_contract.py` writes `dayTagsSha256`, `pngSha256`, `jsonSha256` and `tags`
   per day sheet, so a relight can never change a day pixel unnoticed.

Run from `$ART` as part of `tools/export_all.sh` (always after the day builders). One-off:
`"$ASE" -b --script-param art="$PWD" --script-param run=build_mascot_night --script-param status=qa/.lua-completed --script lua/run_checked.lua`
then `cat qa/.lua-completed` → `completed`.

### 7.7 Luminance and legibility checks (what `verify_night.py` holds a relight to)

- Every frame of every night sheet equals the relight of its day frame, pixel for pixel (the bookworm: 2,126 frames).
- Tags, ranges, direction, slices, frame count, durations and the 64 × 48 canvas equal the day sheet's; the PNG size
  and the **alpha mask** are identical.
- The glyph, sweat, page-line, closed-lid and X-eye floors (luminance, 0–255):

| Mark | Floor | Bookworm's measured minimum |
|---|---|---|
| sweat `S` (luminance) | ≥ 60 | passes |
| page lines `P` vs the neighbouring cream `C` (contrast) | ≥ 8 | 16.13 |
| closed lid `j` vs body `G` (contrast) | ≥ 12 | 38.58 |
| X eyes / outline `K` vs body `G` (contrast) | ≥ 18 | passes |
| the `?` glyph (luminance) | ≥ 140 | passes (declared colours) |
| z's and sparkles | unchanged day hex | 1,446 per-frame glyph-pixel checks pass |

  Set the equivalent floors for `<character-name>`'s own marks in the spec.
- **Room-level region checks** (bookworm's, on a rendered `sleeping` room with a `sunny` base; boxes top-left
  `(x0, y0, x1, y1)`): lamp wall `(0,14,18,34)`, plant `(21,42,33,64)`, near seat `(36,55,58,64)`, near worm
  `(42,25,58,42)`, far wall `(85,0,106,30)`, far worm `(82,40,99,54)`, sill `(18,37,58,41)`, moon floor `(30,58,65,64)`.
  - Lamp wall, plant, near seat, near worm: lit luminance ≥ 8 above dark, and lit warmth ≥ 12 above dark.
  - Far wall and far worm: lit equals dark exactly, and both below 40 % of day.
  - Dark room: the sill ≥ 8 brighter than the far wall; sill and moon floor have negative warmth (cool).
  - Backdrop means: `night-dark` < `night-lit` < 0.6 × day `lit`. The unlit mug's brightest pixel < 90.
  Port the "near worm" and "far worm" checks for `<character-name>`: its near (lamp-side) region must warm when lit,
  its far region must be identical in both night sheets.
- **Legibility by eye** (no script checks these): every state's key frame on the dark and lit boards at 1× and 6×;
  the identity marks readable in band 0; the X eyes, lids and `?` readable in both night sheets.

### 7.8 Measured lighting numbers (for calibration)

From `$BW/SCENERY_REPORT.md` (weighted luminance 0–255, sleeping worm, sunny base; boxes as in §7.7):

| Region | Night, lamp dark | Night, lamp lit | Day, lamp lit |
|---|---:|---:|---:|
| Whole backdrop | 43.39 | 62.26 | 185.63 |
| Lamp wall | 35.32 | 109.45 | 174.43 |
| Plant | 53.14 | 63.36 | 147.86 |
| Near seat | 51.54 | 74.05 | 103.43 |
| Near worm | 47.94 | 57.89 | 111.88 |
| Far wall | 41.93 | 41.93 | 184.18 |
| Far worm | 48.75 | 48.75 | 156.94 |

- The dark room is **23.4 %** of the day backdrop's luminance, **33.5 %** with the lamp lit.
- The clock's night dial is **29.66 %** of the day dial (50.43 / 170.01 over 149 dial pixels; *recomputed*).

Mean luminance over opaque pixels of each tag's first frame (*recomputed* from `$RES/room-*.png`):

| Sheet | Day tags | `night-dark` | `night-lit` |
|---|---|---:|---:|
| `room-backdrop` | `dark` 184.2, `lit` 185.6 | 43.4 | 62.3 |
| `room-lamp` | `dark` 108.4, `lit` 119.5 | 27.5 | 86.5 |
| `room-window` | `idle` 120.5 | 39.8 | 55.9 |
| `room-plant` | `idle` 107.5 | 42.0 | 52.6 |
| `room-beanbag` | `idle` 103.7 | 38.1 | 52.2 |
| `room-mug` | `idle` 129.2 | 32.3 | 32.3 (outside the pool) |

---

## 8. Scenery

The study room's time of day, weather, skies, overlays and wall clock. **All of it is shared room art, owned by the
bookworm's folder and reused unchanged by every mascot**; a character only has to coexist with it (§5.10, §8.13).
Sources: `docs/specs/2026-10-02-study-room-scenery.md`, `$BW/room-plan.json`, `$BW/room-motion.json`,
`$BW/lua/build_weather.lua`, `build_skyfx.lua`, `build_clock.lua`, `scenery_common.lua`, `$BW/tools/verify_room.py`,
`verify_clock.py`, `$BW/SCENERY_REPORT.md`, `$BW/INTEGRATION_REPORT.md`, `$SRC/Theme/{Scenery,SceneClock,SceneStore,LocalWeatherReader,Copy+Scenery}.swift`,
`$SRC/Views/Sleep/{DeskScene,StudyRoom,RoomClock,WindowWeather,RoomLattice}.swift`,
`$SRC/Views/Settings/ScenerySettings.swift`, `docs/architecture/network.md`, and the tests `SceneryTests`,
`RoomClockTests`, `SpriteClipTests`.

### 8.1 What is shared, what is per character

| Element | Files | Owner | For `<character-name>` |
|---|---|---|---|
| Backdrop, lamp, window, plant, bean bag, mug (day + `night-dark`/`night-lit` tags on each sheet) | `$RES/room-{backdrop,lamp,window,plant,beanbag,mug}.*` | `$BW` | Shared, unchanged |
| The fly | `$RES/room-fly.*` | `$BW` | Shared, unchanged |
| The 15 skies | `$RES/room-weather.*` | `$BW` | Shared, unchanged |
| The 6 overlays | `$RES/room-skyfx.*` | `$BW` | Shared, unchanged |
| The wall clock | `$RES/room-clock.*` | `$BW` | Shared, unchanged; your ink stays out of its box |
| The real pile's spine textures | `$RES/room-spines.*` | `$BW` | Shared, unchanged |
| Floor plan, light map, motion sidecar | `$BW/room-plan.json`, `room-light-map.json`, `room-motion.json` | `$BW` | Shared, read-only |
| Palette | `$BW/palette.json` | `$BW` | Shared (D3: you may add ≤ 6 keys) |
| Scenery logic, weather reader, Settings → The scenery | Swift (`Scenery.resolve`, `SceneClock`, `LocalWeatherReader`, `ScenerySettings`) | app | Shared, mascot-independent, unchanged |
| The character's 8 day, 16 night and 1 small sheet | `$RES/<character-name>-*` | `$ART` | Per character |
| Hotspot and gaze origin | derived from the character's `ink` and `eye` slices | app | Per character, automatic |

A skin never re-exports, restyles or re-registers a room sheet. To change the room itself, follow the scenery contract
and every room verifier, in its own PR, with the owner's word.

### 8.2 The decision model and the one resolver

The scenery contract splits the room into three independent pure functions. The owner's words: *"at night and in storm
and does dark environments, the room should be dark"*, decided as **"night and rainy"**; and for the two state skies,
*"a calm mist while a cycle runs, a rainbow when one just finished (a shooting star at night)"*.

1. **The character** shows Sleep's state (`BookwormState`) at any hour and in any weather. Scenery never changes it.
2. **The time of day** (`SkyPhase`: `day`, `dusk`, `night`) comes from `SceneClock` through `SceneStore`, unless
   *Choose* pins it.
3. **The base weather** (`WindowWeather`: `sunny`, `cloudy`, `windy`, `rainy`, `curtains`) comes from the source the
   viewer picked.

Two Sleep moments are **overlays in every mode**: `mist` while `sleeping` (a cycle is running); when `digesting` (a
cycle just finished), a `rainbow` by day or dusk and a `shootingstar` at night.

`Scenery.resolve` (`$SRC/Theme/Scenery.swift:75-94`):

```swift
static func resolve(mode: SceneryMode, clock: SkyPhase, forecast: WindowWeather?, mood: BookwormState,
                    manual: ManualScenery) -> Scenery
// time    = mode == .choose ? manual.time : clock
// base    = .choose → manual.base (source .chosen)
//           .sleep  → windowWeather(for: mood) (source .sleep)
//           .localWeather → forecast ?? windowWeather(for: mood) (source .localWeather, or .fallback when nil)
// overlay = .sleeping → .mist; .digesting → (time == .night ? .shootingstar : .rainbow); else nil
// lighting (computed) = time == .night || base == .rainy ? .dark : .day
```

No I/O, no clock read, no change to Sleep. Derived names: `weatherTag` = `"<base>-<time>"` (a `room-weather` tag);
`overlayTag` = `"<overlay>-<time>"` or nil (a `room-skyfx` tag; only the six real tags can occur); `lighting`; and
`RoomLighting.suffix(lampLit:)`, which picks the character sheet through `Mascot.roomSheet` (§9.1).

### 8.3 Time of day (`SceneClock`, `SceneStore`)

- `SceneClock.phase(at:timeZone:)` uses NOAA's general solar-position equations over the time zone's principal location
  (`TimeZoneCoordinates`, from IANA tzdb). No location permission, no network.
  - **day:** between the horizon crossings (zenith **90.833°**); a polar day is all day.
  - **dusk:** inside civil twilight (zenith **96°**) at either end; morning twilight is also `dusk` (no dawn phase).
  - **night:** everything else.
  - **No coordinates** for the zone: day 07:00–19:00 local, dusk 30 min either side, night otherwise.
- `SceneStore.shared.phase` recomputes at the next crossing or within the hour (`maxRecheck = 3600` s), and at once on a
  time-zone change or a wake. The room and Home's painting share it (Home uses its own three-value `SceneTime`).
  The wall clock reads `Date()` directly (§8.12).

### 8.4 Base weather by source

AppStorage keys, per viewer, never in a bank: `cicada.sleep.scenerySource` (default `localWeather`),
`cicada.sleep.sceneryTime` (default `day`), `cicada.sleep.sceneryWeather` (default `sunny`); unknown values fall back to
these defaults.

**How Sleep is doing** (`windowWeather(for:)`, `$SRC/Views/Sleep/WindowWeather.swift:22-30`):

| Mood | Base | Legend meaning (this source) |
|---|---|---|
| `sleeping`, `digesting`, `happy` | `sunny` | "Caught up. Nothing waiting." (the overlay's meaning wins when an overlay is up) |
| `reading`, `curious` | `cloudy` | "Things are waiting to be read." |
| `hungry` | `windy` | "Overdue: it's been a while." |
| `error` | `rainy` | "The last cycle failed." |
| `awake` | `curtains` | "Waiting to hear how Sleep is doing." |

**Local weather** (default; `WeatherReading.base`, `Scenery.swift:97-108`; Open-Meteo `current.weather_code` and
`wind_speed_10m` in km/h), first match wins:

| Order | Condition | Base |
|---|---|---|
| 1 | wind not finite or negative | nil (falls back) |
| 2 | code 51–67, 80–82 or 95–99 | `rainy` (precipitation beats wind; no lightning flash is ever drawn) |
| 3 | code 71, 73, 75, 77, 85 or 86 (snow) | `cloudy`, even in high wind |
| 4 | any other code outside 0–3, 45, 48 | nil (falls back) |
| 5 | wind ≥ 30 km/h | `windy` |
| 6 | code 0–1 → `sunny`; codes 2–3 and 45/48 → `cloudy` | |

`curtains` is never chosen by local weather. With no cached forecast (offline, refused, no city, unknown code, not yet
fetched), the base falls back to the mood mapping and the source becomes `.fallback`. **Choose** uses `manual.time` and
`manual.base` as they are.

**The local-weather read** (the app's own gate; `docs/architecture/network.md`):

| Aspect | Value |
|---|---|
| When | mode `localWeather` **and** the study room on screen; `.task(id: WeatherWatchKey(onScreen, mode, zone))` cancels on any change |
| Sent | the zone's principal city latitude/longitude, `current=weather_code,wind_speed_10m`, `wind_speed_unit=kmh`, `forecast_days=1`; no permission, zone id, viewer id or bank content |
| Endpoint | `https://api.open-meteo.com/v1/forecast` only; other hosts, paths, schemes, ports, userinfo, redirects and HTTP auth refused |
| Transport | ephemeral session; no cookies, credentials or URL cache; `User-Agent: weather-reader`; 4 s timeouts; non-200, non-JSON or > 64 KiB refused |
| Cadence | at most one attempt per 30 min, failures included |
| Cache | memory only, keyed by zone; expires after 30 min; cleared on failure |

### 8.5 Text twins

`Scenery.text` is the one string for the window legend's current line, the window's `.help` and its VoiceOver label
(`"Window, <text>"`): `"<Time> · <Base title> · <source>"`, then `". Local weather unavailable."` on fallback, then the
overlay's meaning ("A cycle is running." / "A cycle just finished.") or, with no overlay under Sleep or fallback, the
base's meaning. Tested examples: `"Night · Rainy · local weather"`,
`"Day · Windy · How Sleep is doing. Local weather unavailable. Overdue: it's been a while."`,
`"Night · Cloudy · your choice. A cycle just finished."`.

The legend popover (`WindowLegend`, `$SRC/Views/Sleep/WindowWeather.swift:50-87`) shows the current line
(`Scenery.text`), then *"A calm mist means a cycle is running. A rainbow, or a shooting star at night, means a cycle
just finished."* Under *How Sleep is doing* or the fallback it adds a five-row key: one `WeatherThumbnail` per base at
the current time, with its title and meaning. The current base's row is selected (`bgSelected`, `.isSelected`) and
shows the overlay's meaning when one is up. It ends with the link *"Change the scenery in Settings ›"* to Settings →
Sleep, at The scenery's Source row. Art never carries a fact the text does not.

### 8.6 Swaps, pauses, Reduce Motion, Low Power

- **One art layer swaps as a unit.** `SceneryRoomArt` keys a `ZStack` (all props plus the character) by
  `weatherTag + "|" + (overlayTag ?? "") + "|" + (lampLit ? "lit" : "dark")`. A change crossfades with
  `.transition(.opacity)` and `SleepMotion.weather` (**0.4 s easeInOut**); instant under Reduce Motion. Hotspots and the
  real pile are stable siblings outside it.
- **Shared phase.** Every looping sprite plays from one `SpriteClock.origin`, so a swap lands on the same step.
- **Reduce Motion** → `SpritePlaybackProfile.still`: first frames only, no `TimelineView`, no second hand.
- **Low Power** → `.gentle`: every hold doubles (`slowdown = 2`).
- **Paused while unseen.** The room is `onScreen` only when its window is visible, no host paused it and Settings is
  closed (`StudyRoom.swift:115`); `.environment(\.scenePaused, !onScreen)` reaches every sprite leaf.

### 8.7 The skies: `room-weather` (36 × 32, 15 tags, 588 frames)

Five Aseprite layers: `sky`, `far`, `near`, `fx`, `glass`. Each base reuses one historical drawing; the three times
retint or swap it. Every tag loops forward.

| Tag | Drawing | Frames | Hold (ms) | Loop (ms) | What is drawn |
|---|---|---:|---|---:|---|
| `sunny-day` | clear | 36 | 500 | 18,000 | full sun with 3 ray poses, two round clouds drift, a distant treeline |
| `sunny-dusk` | dawn | 36 | 300 | 10,800 | three sunrise bands, half sun, two thin clouds, paired rays alternating every 3 frames |
| `sunny-night` | night | 24 | 200 | 4,800 | static crescent moon at (7,3), 9 stars on a 4-phase cycle (cross, dot, dim dot, dot), stepping every 6 frames |
| `cloudy-day` | fair | 72 | 200 | 14,400 | partly hidden sun; near cloud moves every frame, far clouds every second frame (near y=6, far y=3 and y=5) |
| `cloudy-dusk` | fair, tinted | 72 | 200 | 14,400 | as day, rose tint |
| `cloudy-night` | fair, night | 72 | 200 | 14,400 | moon instead of sun, a dense cloud deck, stars every 3 frames, hidden wherever a cloud covers them |
| `windy-day` | overcast | 36 | 120 | 4,320 | grey streaks at y 6 and 11, a foreground tree leaning 0, 1, 2, 1 every 3 frames, 3 blowing leaves |
| `windy-dusk` | overcast, tinted | 36 | 120 | 4,320 | as day |
| `windy-night` | overcast, night | 36 | 120 | 4,320 | second streak at y=5; moon and stars, hidden behind cloud |
| `rainy-day` | storm | 48 | **100** | 4,800 | heavy static banks, 32 diagonal streaks, 4 glass drops forming and sliding, **no flash** |
| `rainy-dusk` | storm, tinted | 48 | 100 | 4,800 | as day |
| `rainy-night` | storm, night | 48 | 100 | 4,800 | dark blue rain, no moon or stars |
| `curtains-day` | curtains | 8 | 600, 300 alternating | 3,600 | closed folds, a breathing hem (0, 1, 2, 1, 0, −1, −2, −1), the light leak at x=17 |
| `curtains-dusk` | curtains, tinted | 8 | 600 / 300 | 3,600 | warm leak |
| `curtains-night` | curtains, tinted | 8 | 600 / 300 | 3,600 | nearly dark folds and leak |

- **Rain timing amendment (2026-10-02):** rain went from 80 to 100 ms holds (3,840 → 4,800 ms loops), pixels unchanged,
  to keep the room under the redraw cap (§8.13). `verify_room.py` pins 100 ms.
- **Sky bands:** rows 0–9 use `weather.sky.<drawing>.<a>`, rows 10–21 `.<b>`, rows 22–31 `.<c>`: (0, 1, 2) for night,
  dawn and clear; (0, 1, 1) for fair, overcast and storm. `curtains` fills with `weather.curtain.0`, then the folds.
- **Pane tints** (`scenery.ramps.dusk`/`.night`, applied by `build_weather.lua` through `scenery_common.lua: C.tint` to
  every opaque pane pixel; `day` is untinted; the pane only): dusk collapses every clear/fair/overcast/dawn/night sky
  band onto one rose ramp (`#51415E`, `#98636B`, `#C18B68`; storm keeps `#393745`, `#51475B`); night collapses every
  sky band onto the night-sky keys (`v #18243B`, `w #26334A`, `x #35465C`). **Celestial colours never tint** (sun `+ ,`,
  moon `-`, stars `/ :`). Clouds go rose at dusk and slate at night; rain `; <` and curtains `= >` have their own tints;
  the curtain leak `c` is `#FFF2C7` by day, `#D7AF82` at dusk, `#4B5266` at night. A sky's identity at dusk and night
  comes from its shapes, not its band colours.
- **Keys present per tag (day names):** sunny-day sky `7 8 9`, clouds `) *`, sun `+ ,`, treeline `n`; sunny-dusk `y z 0`,
  `) *`, `+ ,`; sunny-night `v w x`, moon `-`, stars `/ :`; cloudy-day/dusk `! #`, `) *`, `+ ,`, `n`; cloudy-night
  `! #`, `) *`, `-`, `/ :`, `n`; windy-day/dusk `$ %`, `) *`, `N l n o`; windy-night as day plus `-` and `/ :`;
  rainy-* `& (`, `; <`; curtains-* `= >`, `c`.
- **Checks that involve the character (ruling 9):** every celestial pixel in every frame of all 15 tags stays visible
  against the union of every pose, cover, beat and transition of all 8 moods plus the window frame; ≥ 50 % of each
  frame's cloud pixels stay visible (bookworm minimum 50 %, cloudy-day 63.64 %). Rain's maximum frame-to-frame luminance
  change is 0.210 % (day), 0.218 % (dusk), 0.285 % (night) against a 2 % limit. All 15 key frames differ.

Sky key-frame luminance (*recomputed*, first frame, 36 × 32, fully opaque): sunny 163.8 / 115.0 / 58.4; cloudy 187.1 /
100.9 / 55.3; windy 153.0 / 96.7 / 53.7; rainy 92.7 / 72.8 / 48.9; curtains 136.4 / 86.1 / 49.7 (day / dusk / night;
curtains must strictly decrease).

### 8.8 The overlays: `room-skyfx` (36 × 32, transparent, 6 tags, 180 frames)

Drawn **over the pane and under the window frame** (plan z=3), at the pane's registration.

| Tag | Frames | Hold (ms) | Loop (ms) | Drawing | Colour (`scenery.colors`) |
|---|---:|---:|---:|---|---|
| `mist-day` / `-dusk` / `-night` | 36 | 300 | 10,800 | two interrupted one-row wisps drifting 1 px per frame (row 6, x 20–34; row 23–24, x 1–15); ≤ 25 opaque px of 1,152; never a whiteout | `mist.day #C9DAD8`, `mist.dusk #BE9BA9`, `mist.night #697A99` |
| `rainbow-day` / `-dusk` | 12 | 600 | 7,200 | a complete five-band arc centred (20,18), radii 10–14, rows 3–18 (191 px); band = 14 − radius; a 1-px glint at (18 + phase, 7), phases 0, 1, 2, 1 every 3 frames | `rainbow.day.0–4` `#C77881 #D9A566 #8BA77A #77A9B9 #9791BC`; `rainbow.dusk.0–4` `#9F596F #B68059 #6B8067 #637C96 #82729E` |
| `shootingstar-night` | 48 | 250 | 12,000 | visible frames 0–7 only: a 3-px trail (5,3) → (12,6), tail in `celestial.star.1`; frames 8–47 empty (83.33 % empty, a 10 s rest) | `shootingstar #D0DCF3` |

Checks: no frame covers more than 35 % of the pane; overlay ink stays visible past the character and frame mask (mist
100 %, rainbow 57.59 %, shooting star 100 %); no overlay hides more than three quarters of any base's celestial key
pixels.

### 8.9 The floor plan (`$BW/room-plan.json`)

```
{"cols": 160, "rows": 64, "origin": "bottom-left",
 "layers": [ {prop, sheet, x, y, w, h, z} × 10 ],
 "worm": {"x": 36, "y": 9, "w": 64, "h": 48},
 "pile": {"x": 110, "y": 0, "w": 50, "h": 52}}
```

| z | prop | sheet | x, y (bottom-left) | w × h | Top-left y | Points at 1.0 (x, y, w, h) |
|---:|---|---|---|---|---:|---|
| 0 | `backdrop` | `room-backdrop` | 0, 0 | 110 × 64 | 0 | 0, 0, 330, 192 |
| 1 | `clock` | `room-clock` | 94, 34 | 15 × 15 | 15 | 282, 102, 45, 45 |
| 2 | `pane` | `room-weather` | 20, 27 | 36 × 32 | 5 | 60, 81, 108, 96 |
| 3 | `skyfx` | `room-skyfx` | 20, 27 | 36 × 32 | 5 | 60, 81, 108, 96 |
| 4 | `window` | `room-window` | 18, 23 | 40 × 38 | 3 | 54, 69, 120, 114 |
| 5 | `plant` | `room-plant` | 21, 0 | 12 × 22 | 42 | 63, 0, 36, 66 |
| 6 | `lamp` | `room-lamp` | 0, 0 | 18 × 50 | 14 | 0, 0, 54, 150 |
| 7 | `fly` | `room-fly` | 0, 32 | 20 × 26 | 6 | 0, 96, 60, 78 |
| 8 | `beanbag` | `room-beanbag` | 36, 0 | 62 × 12 | 52 | 108, 0, 186, 36 |
| 9 | `mug` | `room-mug` | 100, 0 | 8 × 9 | 55 | 300, 0, 24, 27 |
| — | the character | per state | 36, 9 | 64 × 48 | 7 | 108, 27, 192, 144 |
| — | pile (real UI) | — | 110, 0 | 50 × 52 | 12 | 330, 0, 150, 156 |

- Draw order is exactly this z list (`verify_room.py`, mirrored in `DeskScene.plan`; a Swift test compares them).
- Every layer has `x + w ≤ 110`; the pile column holds no room art.
- The window's `glass` slice `(2,2,36,32)` places the pane at `(20,27)`; the bean bag's `seat` slice `(4,2,54,1)` puts
  the seat on scene row 9, the character's baseline (canvas row 47).
- Hotspots at 1.0 for the bookworm (`INTEGRATION_REPORT.md`): worm `(40,9,56,48)` cells = `(120,27,168,144)` pt (from
  its ink union; yours follows your ink); lamp `(2,0,14,50)`; window, clipped at the worm, `(20,27,20,32)`. The clock is
  inert.

### 8.10 The motion sidecar (`$BW/room-motion.json`)

`{"tags": [{"tag", "elements": [{"name", "positions": [{x,y} × n], "steps": [{x,y} × n], "wrap": {x,y}}]}]}`, n = the
tag's frame count. It covers exactly the 15 weather tags then the 6 overlay tags, in sheet order (no `sheet` field: tag
names are unique). Integers only; steps reduced modulo `wrap` into `(−wrap/2, wrap/2]`; the seam rule
`position[i] + step[i] ≡ position[(i+1) mod n] (mod wrap)` holds for every element including last → first. `.phase`
elements hold a cyclic pose index in `x`. Cadence checks: rain `x = −1, −1, −1, 0`, `y = +4`; clouds 1 px per frame
(cloudy's far clouds every second frame); leaves `x +1`, `y 0/−1`. A character adds nothing here.

### 8.11 The prop sheets as shipped (`$RES/room-*.json`)

Every tag plays forward; static tags are one frame of 1,000 ms.

| Sheet | Canvas | Tags (frames) | Slices (top-left, sheet px) |
|---|---|---|---|
| `room-backdrop` | 110 × 64 | `dark`, `lit`, `night-dark`, `night-lit` (1 each) | `glow (0,10,26,54)` |
| `room-lamp` | 18 × 50 | `dark`, `lit`, `night-dark`, `night-lit` (1 each) | `shade (2,1,14,11)`, `ink (2,0,14,50)` |
| `room-window` | 40 × 38 | `idle`, `night-dark`, `night-lit` | `glass (2,2,36,32)` |
| `room-plant` | 12 × 22 | `idle`, `night-dark`, `night-lit` | `ink (0,0,12,22)` |
| `room-beanbag` | 62 × 12 | `idle`, `night-dark`, `night-lit` | `seat (4,2,54,1)`, `ink (0,0,62,12)` |
| `room-mug` | 8 × 9 | `idle`, `night-dark`, `night-lit` | `ink (0,1,8,8)` |
| `room-fly` | 20 × 26 | `buzz` (40 frames, 4,590 ms; holds 60–1,200 ms) | `ink (7,0,12,17)` |
| `room-spines` | 24 × 12 | `chat`, `page`, `note`, `video`, `other` (3 masks each) | — |
| `room-weather` | 36 × 32 | 15 tags (§8.7) | — |
| `room-skyfx` | 36 × 32 | 6 tags (§8.8) | — |
| `room-clock` | 15 × 15 | 8 tags, 362 frames (§8.12) | — |

The fly is 0–2 pixels per frame. Frames 32–38 (0-based; `ROOM_TAG_TIMINGS.md` counts them 1-based as 33–39) are empty
while it passes behind the shade. Frame 39 is a 1-px return. Frame 0 is the landed key frame (1,200 ms) and frame 30
holds on the right rim (600 ms).

### 8.12 The wall clock

The owner: *"a wall clock that reflects the computer's time with a thin red hand and black hand, and have it be darker
when the room is dark."*

- **Art (`build_clock.lua`).** 15 × 15, pivot at (7,7); layers `dial` and `hand`. Dial: `(x−7)² + (y−7)² ≤ 36` is
  `face`, `≤ 49` is `rim`; twelve tick pixels at length 5 and the centre cap in hand ink; day and night dials share one
  alpha mask. Hands: endpoint for index i is `(7 + round(sin(i·π/30)·len), 7 + round(−cos(i·π/30)·len))`, lengths hour 3,
  minute 5, second 6, each a 1-px line from the pivot (≤ len + 1 px, within 0.8 px of the true angle, 8-connected).
- **Colours (`clock.colors`):** `face #D6D3C7` / `face-night #313C52`; `rim #72737D` / `rim-night #20293D`;
  `second #B64645` / `second-night #8B4A5A`; hour and minute hands `K #090707` by day, `#070A13` at night.

| Tag | Frames | Frame i means |
|---|---:|---|
| `face`, `face-night` | 1 each | the dial |
| `hour`, `hour-night` | 60 | hour hand at i × 6°; app index = `(hour mod 12) × 5 + minute / 12` |
| `minute`, `minute-night` | 60 | minute i |
| `second`, `second-night` | 60 | second i |

Frames are listed at 1,000 ms but are angles; the app picks frames directly.

- **Placement:** bottom-left **(94,34)**, z=1; top-left (94,15); **(282,102,45,45) pt at 1.0**. In the character canvas
  that is **cols 58–63 × rows 8–22**: keep every day and night frame out of it (`RoomClockTests`,
  `RoomClockSpriteTests`; both iterate the registry). `INTEGRATION_REPORT.md` records the one fix: the app's box had
  been copied as (93,37) and was corrected to the plan's (94,34); a Swift equality test pins it.
- **App (`RoomClock.swift`).** `RoomClockReading.indices(at:zone:)` with a Gregorian calendar in `TimeZone.current`;
  `face`, `hour`, `minute`, plus `second` unless Reduce Motion, each `-night` when the lighting is dark. Its own
  `TimelineView(.periodic(from: Date(), by: CicadaMotion.roomClockTick = 1 s))` runs only while on screen and unpaused.
  Swaps with `.id(lighting)` and the 0.4 s crossfade. Help and VoiceOver: `"Wall clock, <system short time>"`,
  `accessibilitySortPriority` 2.5. Not a button.

### 8.13 The redraw budget (ruling 18 R-BW11) and the per-state headroom for a new character

**Rule.** The room's summed sprite redraws stay **≤ 1,800 per minute** in every steady combination of environment, mood
and lamp: each animated leaf's frame boundaries over 60 s, plus the clock's **60 ticks**; coincident boundaries on
separate leaves are summed. `SpriteClipTests.testEveryEnvironmentMoodAndLampStateStaysInsideTheRoomRedrawBudget`
covers **240 combinations** (5 bases × 3 times × 8 moods × 2 lamp states) with the weather tag, the character's `idle`
on its lighting sheet, the overlay and the fly. **As written it checks only the default skin**: loop it over
`MascotRegistry.all` (§9.6). Separately, mean CPU with the room frontmost stays ≤ 3 % of one core and within 2 points of
`dev` (the owner measures it on the demo bank before merge).

| Worst case: rainy-night + digesting + lamp lit | Rain | Fly | Worm | Shooting star | Clock | Total |
|---|---:|---:|---:|---:|---:|---:|
| 80 ms rain (before the amendment) | 749 | 520 | 340 | 239 | 60 | **1,908**, over |
| 100 ms rain (shipped) | 599 | 520 | 340 | 239 | 60 | **1,758** |

**Headroom for `<character-name>`'s `idle` loops** (*recomputed*: the worst non-character load per mood over all 30
environment × lamp combinations, and the boundaries the character's `idle` may add; a loop's boundaries per minute ≈
60,000 × frames ÷ loop ms; ±2 counting tolerance, so keep a margin):

| Mood | Worst other leaves (scene) | Bookworm `idle` boundaries/min | `<character-name>` `idle` must stay ≤ |
|---|---|---:|---:|
| digesting | 1,420 (rainy-night, lit: rain + fly + shooting star + clock) | 340 | **375** |
| sleeping | 1,380 (rainy, lit: rain + fly + mist + clock) | 240 | **415** |
| awake | 1,180 (rainy, lit: rain + fly + clock) | 159 | 615 |
| reading | 1,180 | 230 | 615 |
| happy | 1,180 | 226 | 615 |
| hungry | 1,180 | 116 | 615 |
| error | 1,180 | 325 | 615 |
| curious | 1,180 | 134 | 615 |

Low Power doubles every hold (roughly halving the sprite terms); Reduce Motion stops every loop and the second hand; a
hidden or occluded room, or open Settings, pauses all of it.

### 8.14 Settings → Sleep → The scenery (`$SRC/Views/Settings/ScenerySettings.swift`)

In `SettingsSleepView` after the schedule, followed by **Mascot** (§9.4). One `SettingsGroupCard` titled **"The
scenery"**:

1. **Source** (`.scenerySource`): menu picker *Local weather* · *How Sleep is doing* · *Choose*. Under Local weather the
   disclosure reads: *"Open-Meteo receives your time zone's city, every half hour while the study room is open; nothing
   else leaves your Mac."*
2. **Choose only:** *Time of day* (Day, Dusk, Night) and *Weather* (Sunny, Cloudy, Windy, Rainy, Curtains drawn) as
   `WeatherThumbnail` tiles (the first frame of `room-weather/<base>-<time>`), adaptive grid ≥ 88 scaled points;
   selection is `bgSelected` + a `textPrimary` ring + `.isSelected`, never hue alone; each tile a focusable plain button
   with `.help` and a VoiceOver label ("Weather, Rainy"); choosing is instant (DR-65).
3. **Preview** (`.sceneryPreview`): a live `SceneryRoomArt` at one point per cell, **drawing the selected mascot** in
   the Settings-derived mood with the lamp = `schedule.enabled`; detail line `scenery.text`; reads the weather cache,
   never fetches. A new character appears here automatically once selected.

### 8.15 Historical documents and known differences

- `$BW/ROOM_TAG_TIMINGS.md` is Run B's 2026-10-01 table (the seven old skies, storm at 80 ms); its fly, spine and
  static-prop timings are still correct, but it lists only the day prop tags: no `night-dark`/`night-lit`, no
  `room-skyfx`, no `room-clock`. Its tag names, sky set and storm timing are superseded by §8.7, §8.8, §8.11 and §8.12.
  It counts frames 1-based (§8.11).
- `$BW/RUN_B_REPORT.md` and `$BW/SCENERY_REPORT.md` are dated snapshots (Run B: 19 sheet pairs, the 19th a
  since-retired dark menu-bar variant; 82-entry palette; 7 mood skies; scenery run: rain at 80 ms).
- `$BW/README.md` also names superseded red pupils, a grey-rim menu variant and seven mood-only skies, as history; none
  is in the manifest.
- The final state is `$BW/INTEGRATION_REPORT.md`, `$BW/README.md` and TODO ruling 18:
  **36 sheet pairs, 429 tags, 4,426 frames; resources 1,834,301 bytes (cap 6 MiB); 6,151,414 decoded pixels (cap
  8,388,608); Swift 2,775 tests, 0 failures (twice).**
- The scenery contract's "35 sheet pairs" predates its own wall-clock amendment: with `room-clock` it is 36.
- Snow stays `cloudy` even at wind ≥ 30 km/h (tested); fog (45/48) at wind ≥ 30 km/h becomes `windy`.
- Not yet accepted for G176 itself: the owner's motion review in `$BW/preview.html` and on the Sleep page, the demo-bank
  review at 0.8×–1.4× and the live CPU measurement.

---

## 9. Mascot registry

A mascot is a **skin over one fixed contract**: the same eight states, the same state × response matrix, the same tag
names, canvases, slices and timing caps, and the same shared room. The registry only tells the readers **which sheet
names** to load. Source: `$SRC/Sprites/MascotRegistry.swift` (G176, "the mascot selector — Settings -> Sleep -> Mascot,
with Bookworm").

### 9.1 The registry entry

Abridged from the source (one-line bodies):

```swift
/// A skin over the same state/tag/canvas contract. Paths are repository-relative provenance, never viewer data.
struct Mascot: Identifiable, Equatable, Sendable {
    let id: String
    let displayName: String
    let roomSheetPrefix: String
    let menuBarSheet: String
    let artFolder: String

    func roomSheet(_ state: BookwormState, lighting: RoomLighting = .day, lampLit: Bool = false) -> String {
        "\(roomSheetPrefix)\(state.caseName)\(lighting.suffix(lampLit: lampLit))"
    }
    func selectionLabel(selected: Bool) -> String { selected ? "\(displayName), selected" : displayName }
}

/// The complete, ordered catalog. Adding a skin adds its sheets/manifest entries and one catalog entry.
enum MascotRegistry {
    static let bookworm = Mascot(id: "bookworm", displayName: "Bookworm", roomSheetPrefix: "bookworm-",
                                menuBarSheet: "bookworm-small", artFolder: "app/CicadaApp/Art/sprites/bookworm-2026-10-01")
    static let all = [bookworm]
    static func resolve(_ storedID: String) -> Mascot { all.first { $0.id == storedID } ?? bookworm }
}

/// Per-viewer preferences, separate from every bank. Views observe this key with AppStorage.
enum MascotPreference {
    static let defaultsKey = "cicada.mascot"
    static func selected(in defaults: UserDefaults = .standard) -> Mascot {
        MascotRegistry.resolve(defaults.string(forKey: defaultsKey) ?? MascotRegistry.bookworm.id)
    }
}
```

| Field | Meaning | Bookworm | `<character-name>` | Rules |
|---|---|---|---|---|
| `id` | The stored preference value (`cicada.mascot`), the tile identity, part of the menu-bar image cache key (`small\|<id>\|…`) | `bookworm` | `<character-name>` | Stable forever once shipped. Unique (tested). Case-sensitive. |
| `displayName` | Tile label, VoiceOver/help (`"<name>, selected"`), a Settings search keyword | `Bookworm` | `<Display Name>` | In the registry, not in `Copy`. |
| `roomSheetPrefix` | Prefix of the 24 room sheets | `bookworm-` | `<character-name>-` | Include the trailing `-`. Never `bookworm-`, `room-` or `test-skin-`, and never starting with `bookworm-` (tools and one test match that prefix). |
| `menuBarSheet` | Full name of the one 18 × 18 sheet | `bookworm-small` | `<character-name>-small` (D2) | A full name; distinct from the 24 room names (the test counts 25 distinct names). |
| `artFolder` | Repository-relative folder with sources, scripts and README; provenance only | `app/CicadaApp/Art/sprites/bookworm-2026-10-01` | `app/CicadaApp/Art/sprites/<character-name>-<YYYY-MM-DD>` | Must contain `README.md` (tested). Never shown to viewers. Never absolute. |

**Name formation:** `roomSheetPrefix + state.caseName + RoomLighting.suffix(lampLit:)`. `caseName` is one of
`awake sleeping digesting happy curious hungry reading error` (`$SRC/MenuBar/BookwormState.swift:66-77`);
`sleeping(stage:)` and `curious(count:)` each map to one sheet (the stage dots and count badge are drawn in code).

**Selection and persistence:** `cicada.mascot` in UserDefaults, per viewer, never in a bank. Missing means `bookworm`;
an unknown or removed id resolves to `MascotRegistry.bookworm` (the named constant, not `all.first`), so removing a
shipped entry is safe.

**The edit for `<character-name>`** (decision D10 sets the order; `all`'s order is the tile order):

```swift
static let <character-name-as-swift-identifier> = Mascot(id: "<character-name>", displayName: "<Display Name>",
    roomSheetPrefix: "<character-name>-", menuBarSheet: "<character-name>-small",
    artFolder: "app/CicadaApp/Art/sprites/<character-name>-<YYYY-MM-DD>")
static let all = [bookworm, <character-name-as-swift-identifier>]
```

(`<character-name-as-swift-identifier>` is `<character-name>` in lowerCamelCase, for example `alpha-robot` →
`alphaRobot`.)

### 9.2 Every place that resolves through it

There is **one funnel**: `BookwormArt.sheetName` calls `Mascot.roomSheet` or reads `Mascot.menuBarSheet`. No source file
outside `MascotRegistry.swift` contains a `"bookworm-` sheet literal.

| Where (`$SRC/…`) | What it resolves | Mascot comes from |
|---|---|---|
| `Sprites/MascotRegistry.swift:11-13` `Mascot.roomSheet` | a room sheet name | the entry |
| `Sprites/BookwormArt.swift:14-18` `sheetName(_:_:lighting:lampLit:mascot:)` | `.small` → `menuBarSheet`; `.room` → `roomSheet(...)` | argument; default `MascotPreference.selected()` |
| `BookwormArt.swift:46-53` `clip(...)` | sheet + clip; misses go exact → base look → `idle` → frame 0 (`fallbackClip`) | same |
| `BookwormArt.swift:55-63` `coverIndex(...)` | the reading sheet's `idle` total (the three-cover cycle) | same |
| `BookwormArt.swift:65-69` `beatLength(...)` | a reaction clip's length on the state's day sheet | same |
| `BookwormArt.swift:71-80` `transitionClip` / `transitionLength` | the **sleeping** sheet's `intro`/`outro` in the current lighting; length from the day sheet | same |
| `BookwormArt.swift:83-88` `wormInk` | union of every room state's `ink` slice except curious → the desk hotspot | the selected mascot |
| `BookwormArt.swift:90-95` `eyePixel` | the awake sheet's `eye` slice centre → the gaze origin | the selected mascot |
| `MenuBar/BookwormRenderer.swift:10-32` `cacheKey` / `smallImage` | the menu clip; cache key `small\|<mascot.id>\|<spriteKey>\|<rectIndex>\|<pt>` (two skins never share an image) | argument; default selected |
| `MenuBarManager.swift:26-29` `mascotChanged()` | resets the frame step and restarts the chained timer | — |
| `CicadaApp.swift:125, 228` | `@AppStorage(MascotPreference.defaultsKey)` and `.onChange(of: mascotRaw) { menuBarManager.mascotChanged() }` | preference |
| `Views/Common/BookwormView.swift:21, 25, 33-45, 69, 82` | observes the key; passes `MascotRegistry.resolve(mascotRaw)` explicitly to every reader | observed |
| `Views/Sleep/DeskHotspots.swift:8, 12, 16` | `wormInk`, `eyePixel` | selected |
| `Views/Sleep/RoomModel.swift:326, 350` | `beatLength`, `transitionLength` | selected |
| `Views/Contributors/ContributorsView.swift:335` | the small `happy` image as the system avatar | selected |
| `Views/Settings/MascotSettings.swift:5-22, 39-40` | `ForEach(MascotRegistry.all)`: each tile shows **its own** entry's art | the tile's entry |
| `Views/Settings/SettingsIndex.swift:92-93` | search keywords `["character", "avatar"] + displayName`s | catalog |
| `$TESTS/SpriteTestAssets.swift:9-18` | `dayWormNames`, `nightWormNames`, `sheetNames` from `MascotRegistry.all` + the 11 `room-*` | catalog |

Resources are bundled by directory (`app/CicadaApp/Package.swift`: `resources: [.copy("Resources")]`): new files in
`$RES` need no package edit.

**Copy that still names the bookworm** (D9): `$SRC/Views/Sleep/StudyRoom.swift:317` (`.accessibilityLabel("Bookworm,
\(mood.title)")` inside `WormHotspot`, lines 280–317, which has no mascot in scope: it reads one through
`@AppStorage(MascotPreference.defaultsKey)` + `MascotRegistry.resolve`); `$SRC/Theme/Copy+Welcome.swift:74`
(`gsLeaveWhileReading`, a `static let` used at `$SRC/Views/Home/GettingStartedCard.swift:339` and in the
`welcomeHomeSentences` array at `Copy+Welcome.swift:159`, which `CopyConstantsTests` reads); `$SRC/Theme/Copy+Settings.swift:39`
(`loginItemQuiet`, the login-start detail, called from `$SRC/Services/LoginItemService.swift:50` and tested in
`SettingsGeneralF10Tests.swift:63-67`). The "Show in menu bar" search keyword `"bookworm"` (`SettingsIndex.swift:104`)
stays.

### 9.3 What a new character must provide

**Sheets: 25 PNG + JSON pairs in `$RES` (flat); 24 if D2 = `room` (no small sheet).**

| Sheet | Canvas | Tags (exactly `BookwormArt.requiredTags(state)` / `smallRequiredTags()`) | Slices |
|---|---|---|---|
| `<character-name>-awake` | 64 × 48 | 18: `idle`, `attentive.{left,center,right}`, `expectant.{left,center,right}`, `eager`, `perk.{left,center,right}`, `talk.{left,center,right}`, `gulp.center`, `shake.{left,center,right}` | `ink`, `eye`, `lensL`, `lensR` |
| `<character-name>-happy` | 64 × 48 | awake's 18 + `cheer.center` (19) | same |
| `<character-name>-hungry` | 64 × 48 | awake's 18 | same |
| `<character-name>-reading` | 64 × 48 | awake's 18, each also `@2` and `@3` (54) | same |
| `<character-name>-digesting` | 64 × 48 | `idle`, `expectant.center`, `eager`, `talk.center`, `gulp.center`, `shake.center`, `cheer.center` (7) | same |
| `<character-name>-sleeping` | 64 × 48 | `idle`, `talk.center`, `intro`, `outro` (4) | same |
| `<character-name>-curious` | 64 × 48 | `idle` | same |
| `<character-name>-error` | 64 × 48 | `idle` | same + `errorLensL` |
| `<character-name>-<state>-night-dark`, `-night-lit` (16) | 64 × 48 | identical to the day sheet (tags, frame count, per-frame holds) | identical to day |
| `<character-name>-small` | 18 × 18 | `awake sleeping digesting happy curious hungry reading error` (8) | `lensL`, `lensR` |

The tag set is derived, never hand-listed (`BookwormLook.reachable(for:)` through the matrix,
`$SRC/MenuBar/BookwormPose.swift:100-156`); a tag outside it fails the exact-set test. Other rules:

- **Timing caps** (ruling 18; `$SRC/Theme/CicadaMotion.swift:162-168`): §6.2.5.
- **Slices:** `ink` = the union-ink bounds; `eye`, `lensL`, `lensR` equal across all room sheets.
- **Pixels:** binary alpha; every opaque pixel in the palette (D3); no reserved hue.
- **Footprint:** drawn at `DeskScene.wormCell = (36, 9)` (`$SRC/Views/Sleep/DeskScene.swift:35`); keep-outs in §5.10.
- **Menu bar:** one sheet for light and dark bars (dark outlines); code draws the count badge (rows 11–17,
  right-aligned) for curious and the stage dots (row 17, cols 1, 5, 9, 13, 17) for sleeping
  (`$SRC/MenuBar/BookwormOverlays.swift:55-78`).
- **Tiles:** the room `<character-name>-awake` `idle` first frame and the menu `awake` first frame must both have ink.
- **Export:** `--sheet-pack --format json-array --list-tags --list-slices`, no trim, RGBA8888.

**Manifest entries: 25 objects (24 if D2 = `room`) in `$RES/sprites.manifest.json`** (`{"note": "<non-empty>", "assets": [...]}`; 36
entries today: 24 `worm`, 1 `worm-small`, 7 `room` (the clock is written as `room`), one each of `weather`, `skyfx`,
`fly`, `spines`). Each entry is string → string:

| Key | Required | Rule |
|---|---|---|
| `id` | yes | the sheet name; `png` = `id + ".png"`, `json` = `id + ".json"` |
| `png`, `json` | yes | basenames in `$RES` |
| `role` | yes | one of `worm`, `worm-small`, `room`, `weather`, `skyfx`, `clock`, `fly`, `spines`: `worm` for the 24 room sheets, `worm-small` for the menu sheet |
| `generator`, `script`, `source`, `authoring`, `licence`, `processing` | yes, non-empty | provenance; `script` and `source` relative to `artFolder` (`lua/build_mascot.lua`, `src/<id>.aseprite`); `authoring` names the D1 model and "headless" |
| `date` | yes | `YYYY-MM-DD` |
| `pngSha256`, `jsonSha256` | yes | lowercase 64-hex SHA-256 of the raw bytes |
| `reference` | optional | `reference/<file> <sha256>` of the owner's reference |

No value may contain `/Users/` or `/private/`. The manifest ids must equal the bundled files exactly, both ways.
**The bookworm's `tools/manifest.py` cannot run once another skin's files exist** until the §4.7 patch lands.

**The art folder** (`$ART`, §3): `README.md` (**required by test**), `reference/`, `parts/`, `src/`, `lua/` (with the
relight), `tools/`, `TAG_TIMINGS.md`, `preview.html`. The room's sources stay in `$BW`.

**Palette:** `SpriteAssetTests.testPaletteKeysRolesBinaryAlphaAndReservedHues` checks every name in `sheetNames`
against **`$BW/palette.json`** (`SpriteTestAssets.art` is pinned to `Art/sprites/bookworm-2026-10-01`). So either draw
only from that palette plus ≤ 6 new keys (D3 default), or generalise the test to read each mascot's own palette (with
the R-BW2 amendment).

### 9.4 The Settings tile (Settings → Sleep → Mascot)

`$SRC/Views/Settings/MascotSettings.swift`, the group after The scenery, same list/tile grammar. Each tile shows its own
entry's room `<prefix>awake` `idle` first frame at 64 × 48 and its menu `awake` first frame at 36 × 36 (the 18 × 18 head
at 2×), the display name, a checkmark and neutral ring on the selected tile, native keyboard focus, and VoiceOver
`"<Display Name>, selected"`. No timer runs in a tile; there is no future-character copy. Adding the registry entry adds
the tile; no view edit. Snapshot panes: `CICADA_WRITE_COMPOSITES=1 swift test --filter MascotSettingsTests` writes
`$TMPDIR/cicada-sprite-composites/settings/mascot-<choice>-<scheme>.png` (valid and unknown choice × light and dark);
look at them.

### 9.5 What a new character must NOT change

- **The state machine:** `BookwormState` (cases, `caseName`, `spriteKey`, `title`/`detail`), `deriveBookwormState`
  (menu bar), `deriveSleepPageMood` (Sleep page), the `intakeInFlight` precedence (`$SRC/MenuBar/BookwormState.swift`).
- **The matrix and look grammar:** `acceptsGaze`, `acceptsDropPose`, `allows(_:)`, `BookwormLook.reachable`, `beat`,
  `keySegment`, `BookwormPose`, `BookwormReaction`, `Gaze` (`$SRC/MenuBar/BookwormPose.swift`). A skin draws the looks
  the matrix allows; it never adds or removes one.
- **The shared art contract** in `BookwormArt`: `states`, `roomFrame` 64 × 48, `smallFrame` 18 × 18, `covers = 3`,
  `tag()`, `requiredTags`, `smallRequiredTags`, `fallbackClip`; `RoomLighting.suffix`; the `CicadaMotion` sprite caps.
- **Code-drawn menu overlays** and their nine-key palette (`BookwormOverlays`, `BookwormPalette`).
- **The shared room** (§8.1): the 11 `room-*` sheets, their manifest entries and sources, `DeskScene.plan`,
  `wormCell`, `pileCell`, `room-plan.json`, `room-light-map.json`, `DeskHotspots`.
- **Type and view names** (`BookwormView`, `BookwormArt`, `BookwormRenderer`, …); the key `cicada.mascot`; the
  Bookworm fallback; the rule that a choice is per viewer and changes no state or capability.
- **Wiring:** no character-specific branch in `BookwormView`, `MascotSettings`, `MenuBarManager` or `DeskHotspots`; no
  future-character or "coming soon" copy. (D9's name lookup is not a branch: it reads `displayName`.)
- **The bookworm's sheets and hashes.**

### 9.6 Tests, and Run C1's brief

Run C1 owns, and only Run C1 writes: `$SRC/Sprites/MascotRegistry.swift`; the three D9 copy sites and their call
sites: `$SRC/Views/Sleep/StudyRoom.swift`, `$SRC/Theme/Copy+Welcome.swift` (including its `welcomeHomeSentences`
array), `$SRC/Theme/Copy+Settings.swift`, `$SRC/Views/Home/GettingStartedCard.swift` and
`$SRC/Services/LoginItemService.swift`; and `$TESTS/*`. `WormHotspot` reads the mascot through
`@AppStorage(MascotPreference.defaultsKey)` + `MascotRegistry.resolve`. It never writes art, `$RES`, docs or any other
source unless the spec names it. (In the brief, write these as repository-relative paths.)

**Automatic** (they iterate `MascotRegistry.all` or `SpriteTestAssets.sheetNames`; they check the new skin as soon as
the entry exists):

| Test | Checks |
|---|---|
| `MascotRegistryTests.testCatalogHasUniqueIDsAndExactlyTheOwnersBookworm` | unique ids; the fallback for `""`, unknown and wrong-case ids; **the exact catalog** (update it to `[bookworm, <character-name>]`) |
| `MascotRegistryTests.testEveryCatalogSheetIsInTheManifestAndHasTheSharedContract` | 25 distinct names in the manifest; PNG and JSON present; `<artFolder>/README.md`; every room sheet (day, dark, lit) 64 × 48 with tags exactly `requiredTags(state)`; menu sheet 18 × 18 with the 8 tags |
| `MascotRegistryTests.testAnExplicitDifferentSkinNeverFallsBackToBookwormSheets` | an unknown skin resolves to `nil`, never to bookworm art (`test-skin-`) |
| `MascotRegistryTests.testAppStorageChoicePersistsAndUnknownIDFallsBackWithoutTouchingViewerDefaults` | persistence in an isolated defaults suite |
| `MascotSettingsTests` (3 tests) | search landing, tile accessibility, `.onChange` wiring, no sheet literal in `BookwormView`; tile key frames have ink; the pane renders light and dark |
| `SpriteAssetTests` (all) | manifest = bundle exactly; raw-byte hashes; provenance fields, role enum, date, no machine paths; palette, binary alpha, reserved hues on every pixel; 6 MiB total; side ≤ 2048 |
| `RoomClockTests.testClockBoxNeverOverlapsAnyExistingDayWormFrameOrWindowShadePile`, `RoomClockSpriteTests.testClockInkClearsEveryDayAndNightWormFrameAndOtherProps` | every registered skin clears the clock |
| `BookwormRendererTests.testTwoSkinsNeverShareAnImageCacheEntry` | cache isolation by id |

**Default skin only today — loop each over `MascotRegistry.all` and pass `mascot:`** (they call
`BookwormArt.sheetName(...)` without `mascot:`, which resolves to Bookworm in the test process, or use `"bookworm-…"`
literals):

| Test (in `$TESTS/`) | What changes |
|---|---|
| `NightWormSpriteTests` (`testAllNightSheetsMatchDayTagsFramesTimingsSlicesAndSilhouettes`, `testNightBeatsAndTransitionsUseTheSameLightingSet`) | loop; night equals day for every skin |
| `RoomSpriteTests.testDayWormSliceContractIncludesErrorLensL` | loop; `errorLensL` per skin from the spec (the bookworm's literal is (10,17,5,6)) |
| `BookwormArtTests.testEyeAndLensSlicesAreEqualAcrossRoomSheets` | loop |
| `BookwormSpriteTests` (tag/canvas, small sheet, reading covers share durations) | loop |
| `BookwormPoseSpriteTests` (`testEveryRoomFrameKeepsTheBookGlassesAndStateMarks`, `testSmallStateMarksAndOverlaySpace` via `"bookworm-small"` → `mascot.menuBarSheet`, `testEveryBeatFitsTheMotionBudget`, `testGazeVariantsShareDurations`, `testBlinksHaveIrregularCyclicGaps`, `testLiftsAndSleepGlyphsStayInTheirBoxes`) | loop; identity counts (glasses `D`/`L`, book `book.*`) per the anatomy map (D5, D6) |
| `BookwormStateTests.testErrorFramesHaveBlackXEyesAndDropAndMove` | loop |
| `WindowSpritesTests.testRulingNineForEveryWeatherFrameAndEveryReachableWormFrame`, `testRoomCompositesAtUnitAndMaximumZoom` | loop. Composite names (`WindowSpritesTests.swift:79`, `"<weatherTag>-<mood>-<lit\|dark>-<scale>.png"`) carry no mascot id, so a looped test would overwrite one skin's images with another's: name them `<mascot.id>-<weatherTag>-<mood>-<lit\|dark>-<scale>.png` (480 per skin; Step 13 montages them) |
| `SpriteClipTests.testEveryEnvironmentMoodAndLampStateStaysInsideTheRoomRedrawBudget` | loop (§8.13); print one `Room redraw maximum` line per mascot under `CICADA_WRITE_COMPOSITES=1` |
| `DeskHotspotTests.test_theCellsTheDesignNames` | loop with each mascot selected: the worm hotspot equals that mascot's own ink union; keep the pinned `(40,9,56,48)` cells / `(120,27,168,144)` pt for Bookworm only |
| `BookwormFramesBenchmarkTests.testBenchmarkWarmClipsAndCropsForEveryReachableLook` | loop (warm every skin's clips) |
| `SleepNumbersLintTests.testEveryNamedDurationIsInsideTheBudget` | loop the perk and beat caps over every skin's sheets |
| The `"bookworm-…"` literals in `BookwormArtTests` (lines 32, 49, 52, 58), `BookwormRendererTests` (29, 66, 78) and `BookwormLookRendererTests` (11, 20) | resolve through `mascot.roomSheet` / `mascot.menuBarSheet` per skin, or justify a Bookworm-only pin in the run report |
| `MascotSettingsTests` (line 55: `for choice in ["bookworm", "missing-character"]`) | its choices never select the new id, so the new character's selected pane is never rendered: add every `MascotRegistry.all` id to the choices |
| `ScenerySettingsTests.testRenderEveryScenerySourceAndChosenSelection` | It renders the scenery Preview (which draws the selected mascot) with isolated defaults that have no `cicada.mascot`, so only Bookworm. Loop it: set `defaults.set(mascot.id, forKey: MascotPreference.defaultsKey)` per `MascotRegistry.all` and name the PNGs `<mode>-<scheme>-<id>.png`, so the new character's scenery panes exist to look at. |
| `SpriteTestAssets.sheetNames` (`SpriteTestAssets.swift:18`; D2 = `room` only) | make it order-preserving unique: with `menuBarSheet: "bookworm-small"` it lists that name twice and `SpriteAssetTests.testManifestListsEveryBundledFileAndAllScenerySheets` (`names.count == sheetNames.count * 2`) fails |
| `BookwormLookRendererTests.testDecodedPixelsAndDistinctRoomRectsStayBounded` | the 1,024-distinct-rect bound for every skin's prefix (today only `bookworm-`); the decoded-pixel cap per D4 |
| new: the D9 copy | a test that each copy function returns today's exact text for Bookworm |

Enumerate the rest with `grep -ln 'sheetName(\|"bookworm-' "$TESTS"/*.swift` (16 files at `e0c21b45`). Each hit is
looped over `MascotRegistry.all` or justified in the run report.

**Expected-red list** for Run C1 (it runs before the art lands): every test that loads a `<character-name>-*` sheet.
Write those tests fully; list each red test by name in the run report; they must all be green at Step 13.

**Budget headroom at `e0c21b45`:**

| Budget | Cap | Used | Bookworm's 25 sheets | One more bookworm-sized skin |
|---|---|---|---|---|
| Decoded pixels | 8,388,608 | 6,151,414 | 5,224,356 | about 11.4 M: **fails** the total cap → D4 |
| Bytes (PNG + JSON + manifest) | 6,291,456 | 1,834,301 | 1,402,669 | about 3.24 MB: fits |
| Redraws per minute | 1,800 | 1,758 worst | 340 (digesting) | per-state limits in §8.13 |

### 9.7 Build and test commands (cwd: the worktree root)

Never `swift run` the app (a bundle-less binary whose window never becomes key) and never launch it.

```sh
(cd app/CicadaApp && swift build)
# swift-testing may print summary lines after XCTest's, so never rely on `tail`: grep the XCTest line
(cd app/CicadaApp && swift test 2>&1 | grep -E 'Executed [0-9]+ tests, with [0-9]+ failures' | tail -1)   # baseline: 0 failures
(cd app/CicadaApp && swift test --filter 'MascotRegistryTests|MascotSettingsTests|ScenerySettingsTests|SpriteAssetTests|BookwormLookRendererTests|RoomClockTests|RoomClockSpriteTests|BookwormRendererTests|NightWormSpriteTests|RoomSpriteTests|BookwormArtTests|BookwormSpriteTests|BookwormPoseSpriteTests|BookwormStateTests|WindowSpritesTests|SpriteClipTests|DeskSceneLayoutTests|DeskHotspotTests|BookwormFramesBenchmarkTests|SleepNumbersLintTests' 2>&1 | grep -E 'Executed [0-9]+ tests, with [0-9]+ failures' | tail -1)
(cd app/CicadaApp && CICADA_WRITE_COMPOSITES=1 swift test --filter 'MascotSettingsTests|ScenerySettingsTests')   # Mascot and scenery panes
(cd app/CicadaApp && CICADA_WRITE_COMPOSITES=1 swift test --filter WindowSpritesTests)    # room composites
(cd app/CicadaApp && CICADA_WRITE_COMPOSITES=1 swift test --filter SpriteClipTests 2>&1 | grep 'Room redraw maximum')   # worst redraws/min
(cd "$BW" && python3 tools/make_integration_review.py)                                    # review boards and index
make app                                                                                  # bundle only; never run-app, dev or install-app
```

---

## 10. Driving Codex

### 10.1 The command

```sh
CICADA_CAPTURE=off _ZO_DOCTOR=0 codex exec -m <model> -c model_reasoning_effort=<effort> \
  --dangerously-bypass-approvals-and-sandbox -C <absolute worktree> --json -o <run-folder>/last.md - \
  < <prompt-file> > <run-folder>/events.jsonl 2> <run-folder>/stderr.log
```

- **The model is the owner's call** (D1). Launch nothing before he answers; record it as a dated spec line.
- The prompt goes in on stdin (`-`); `--json` streams events; `-o` writes the final message.
- `CICADA_CAPTURE=off` keeps Cicada from capturing its own spawned sessions; `_ZO_DOCTOR=0` silences zoxide.
- **The bypass flag gives full access, so the prompt's rails are the only fence.** Name every path the run must never
  touch. On 2026-10-02, `codex mcp list` in this install showed enabled `cua_repl`, `node_repl`, `blender`, `freecad`,
  `dokploy`, `context7` and `langfuse-docs`, with `computer-use`, `codex_app` and `code-review` installed but disabled;
  `-c mcp_servers.cua_repl.enabled=false` fails with "invalid transport". Only the prompt keeps them out: the preamble
  forbids every MCP tool and names what Step 1's `codex mcp list` showed.

### 10.2 The runner and helpers (save into `$RUNS`, then `chmod +x "$RUNS"/*.sh`)

Pass absolute paths; the runner changes directory before reading the prompt.

```zsh
#!/bin/zsh
# run-codex.sh <name> <abs-prompt-file> [thread-id]
#   needs CODEX_WT (absolute worktree), RUNS (runs folder) and CODEX_MODEL; CODEX_EFFORT defaults to xhigh
set -u
NAME=$1; PROMPT=$2; RESUME=${3:-}
W=${CODEX_WT:?}; OUT=${RUNS:?}/$NAME; MODEL=${CODEX_MODEL:?}; EFFORT=${CODEX_EFFORT:-xhigh}; mkdir -p $OUT
export CICADA_CAPTURE=off _ZO_DOCTOR=0
cd $W                                  # resume takes no -C, so cd first
if [[ -n $RESUME ]]; then
  codex exec resume $RESUME -m $MODEL -c model_reasoning_effort=$EFFORT --dangerously-bypass-approvals-and-sandbox \
    --json -o $OUT/last.md - < $PROMPT > $OUT/events.jsonl 2> $OUT/stderr.log
else
  codex exec -m $MODEL -c model_reasoning_effort=$EFFORT --dangerously-bypass-approvals-and-sandbox -C $W \
    --json -o $OUT/last.md - < $PROMPT > $OUT/events.jsonl 2> $OUT/stderr.log
fi
RC=$?; echo "exit=$RC" > $OUT/exit
```

Each run gets its own folder with `events.jsonl`, `last.md`, `stderr.log` and `exit`. A resumed run writes a new folder
(give it a new name, for example `runA-fix1`).

```zsh
#!/bin/zsh
# wait-run.sh <name>  (needs RUNS)
D=${RUNS:?}/$1
until [[ -f $D/events.jsonl ]]; do sleep 10; done
while [[ ! -f $D/exit ]] && pgrep -f "$D/last.md" >/dev/null; do sleep 30; done
sleep 5; echo "run $1 ended: $(cat $D/exit 2>/dev/null || echo 'no exit file')"
```

```zsh
#!/bin/zsh
# chain.sh <run> <next> <abs-prompt> <abs-worktree>  (needs RUNS, CODEX_MODEL and CODEX_EFFORT exported)
: ${RUNS:?} ${CODEX_MODEL:?} ${CODEX_EFFORT:?}   # fail loudly into the chain log, never silently
run=$1 next=$2 prompt=$3 wt=$4
$RUNS/wait-run.sh $run > $RUNS/$run/ended.txt
tid=$(head -1 $RUNS/$run/events.jsonl | python3 -c "import json,sys;print(json.load(sys.stdin)['thread_id'])")
CODEX_WT=$wt $RUNS/run-codex.sh $next $prompt $tid > $RUNS/$next.nohup.log 2>&1
```

```python
# follow.py — python3 "$RUNS/follow.py" runA runC1
import json, os, sys, time
base = os.path.dirname(os.path.abspath(__file__)); runs = sys.argv[1:]; files, done = {}, set()
while len(done) < len(runs):
    quiet = True
    for r in runs:
        p = os.path.join(base, r, 'events.jsonl')
        if r not in files:
            if not os.path.exists(p): continue
            files[r] = open(p)
        for line in iter(files[r].readline, ''):
            quiet = False
            try: e = json.loads(line)
            except ValueError: continue
            it = e.get('item') or {}
            if e.get('type') == 'item.completed' and it.get('type') == 'agent_message':
                print(f"[{r}] {(it.get('text') or '').strip().replace(chr(10), ' ')[:240]}", flush=True)
            if e.get('type') == 'turn.failed': print(f"[{r}] FAILED {json.dumps(e)[:300]}", flush=True)
        if r not in done and os.path.exists(os.path.join(base, r, 'exit')):
            done.add(r); print(f"[{r}] EXITED {open(os.path.join(base, r, 'exit')).read().strip()}", flush=True)
    if quiet: time.sleep(5)
```

### 10.3 Detach, follow, wait

- **Always detach** (quickstart Step 9): `nohup … & disown`. Runs take 1 to 15+ hours (the bookworm's Run A about
  4.5 h, Run B overnight), and an orchestrator shell, foreground or background, is killed at 2 h.
- **Follow** with `follow.py` (agent messages and `turn.failed` only; it also waits for runs not yet started).
- **Wait** for `<run>/exit` with a Monitor until-loop, or a detached `wait-run.sh`.

### 10.4 Resume, chain, recover

- **Resume** (review fixes, owner decisions, recovery): the thread id is the first event,
  `head -1 "$RUNS/<run>/events.jsonl" | python3 -c "import json,sys;print(json.load(sys.stdin)['thread_id'])"`; then
  `CODEX_WT=<abs worktree> RUNS="$RUNS" CODEX_MODEL=<model> CODEX_EFFORT=<effort> nohup "$RUNS/run-codex.sh" <next> "$RUNS/<next>.md" <thread-id> > "$RUNS/<next>.nohup.log" 2>&1 & disown`.
  Pass `CODEX_EFFORT` every time: without it `run-codex.sh` quietly falls back to `xhigh`. Write
  `git -C <abs worktree> rev-parse HEAD > "$RUNS/<next>.base"` first (Step 11 checks it). A resumed session keeps its
  whole context: cheaper and better than a fresh run.
- **Chain:** `RUNS="$RUNS" CODEX_MODEL=<model> CODEX_EFFORT=<effort> nohup "$RUNS/chain.sh" <run> <next> "$RUNS/<next>.md" <abs worktree> > "$RUNS/<next>.chain.log" 2>&1 & disown`
  waits for `<run>` to end, then resumes its thread with the next prompt (owner decisions and contract amendments land
  on running work without the orchestrator waiting). Never send its output to `/dev/null`: without the variables it
  would run `/wait-run.sh` and die on `${CODEX_MODEL:?}` with nothing to show for it. Write `<next>.base` when you
  launch the chain, and commit nothing in that worktree until the chained run ends.
- **Recover after an outage** ("stream disconnected"): resume with a prompt that states what survived on disk, the lock
  state (none under the headless rule unless a GUI session was approved), and the rails restated. Nothing is lost.
- **Stop on purpose** (the owner changes the contract mid-run): stop the run (rc 143), commit the new binding contract,
  resume with a "what changes for you" prompt.
- **Never edit a shell script while a running process executes it.**

### 10.5 Prompts

- **Write prompt files with the Write tool or a quoted heredoc (`<<'EOF'`).** An unquoted heredoc executed backticks
  and silently ate names from a bookworm prompt.
- **One prompt file per run.** `run-codex.sh` takes a single file, so `$RUNS/<run>.md` is the preamble below, filled
  for that run, followed by its brief: scope, owned paths (repository-relative), commands, checks, and (for app runs)
  the expected-red list. Run A's brief is §5.11; Run C1's is §9.6. `common.md` stays a template.
- **Pipeline files are owned by one run at a time:** `$BW/palette.json`, the verifiers, `export_all.sh`, the manifest,
  the preview, README and TODO are the merge hot spots.
- **A run raises departures; it never ships them.** The bookworm's Run A added a `bookworm-small-dark` variant on its
  own; it needed an owner ruling and was removed.

**The shared preamble, `$RUNS/common.md`** (a template: fill every `<…>` per run in `<run>.md`; keep every line):

```text
OWNER'S ASK (verbatim): "<owner-ask>"
WORKTREE: you work only in <absolute worktree path>. Another session works in <the other worktree>; never touch it.
  Never touch the main checkout.
GIT: read-only git only (status, diff, log, show). No commit, push, stash, branch, checkout, merge or reset.
SPEC: docs/specs/<YYYY-MM-DD>-<character-name>-sprites-spec.md is binding; read it in full first, then
  app/CicadaApp/Art/sprites/MAKING_A_MASCOT.md. Where this prompt and the spec differ, this prompt wins; report it.
REFERENCES: look at every file in app/CicadaApp/Art/sprites/<character-name>-<YYYY-MM-DD>/reference/ before drawing.
ASEPRITE, HEADLESS ONLY: ASE="${ASEPRITE:-/Applications/Aseprite.app/Contents/MacOS/aseprite}". Every call is
  "$ASE" -b ... with every --script-param before --script. Never open Aseprite's GUI, never `open -a Aseprite`, never
  --script without -b, never use computer use or any GUI tool. Call no MCP tool at all (`codex mcp list` shows
  <every server Step 1's codex mcp list showed enabled, e.g. cua_repl, node_repl, blender, freecad> enabled in this
  install). Never touch Aseprite's recovery sessions, scripts folder or preferences. The owner uses his own Aseprite;
  never interact with it. Parts change only through a headless lua/fix_<topic>.lua record.
APP: never make dev, make install-app, make run-app, app/CicadaApp/install_app.sh, app/CicadaApp/bundle.sh --run or
  swift run; never launch an app; never read memory/, ~/.cicada or ~/.claude/projects.
YOU OWN ONLY: <the brief's owned paths>. Never write anything else, in particular any bookworm-* or room-* file in
  app/CicadaApp/Sources/CicadaApp/Resources/sprites/ or any file in app/CicadaApp/Art/sprites/bookworm-2026-10-01/src
  or /parts.
PRIVACY: nothing personal in any file, comment, log or report; placeholders only. Copy is provider-neutral. Own work
  only: no third-party artwork, brand marks or trade dress.
CONTRACT: same states, tags, canvases, slices, caps and matrix as the bookworm; state art only; no flash or strobe.
QUALITY: true pixel art (binary alpha, palette-locked, whole pixels, light from the upper left); the spec's exact
  timings; look at every export at @6x (18x18 at @8x) before calling it done; iterate at least twice on the face, the
  prop action and the z's.
DEPARTURES: raise them in the report; never ship one.
CLOSING REPORT: every file written; every tag (frames x ms); every hand-tune; what is still rough; every spec
  disagreement with its reason; the last commands you ran and their final output lines; the sentence "no commit made".
```

### 10.6 The Aseprite rule: headless (owner, 2026-10-02)

- **Author headless:** `"$ASE" -b --script-param … --script …`. Params go before `--script`.
- **Why.** Computer use attached to the owner's running Aseprite; a crash during a playback check put one of his own
  documents into Aseprite's recovery sessions, and GUI Lua errors popped up as alerts on his screen. So: never let a run
  share his open Aseprite; never open, focus or quit it; never `open -a Aseprite` (it reuses his running instance);
  never delete his recovery sessions; never install scripts into Aseprite's `scripts/` folder or change its
  preferences; never run `--script` without `-b` (in the GUI it raises the "Give full trust" dialog).
- **The only exception** is a hand-correction or review session the owner approves for one run *after he has quit
  Aseprite*. In it: `mkdir "$RUNS/aseprite-gui.lock"` (≤ 20 min); open only files under `$ART`; run only a
  `lua/gui_<topic>.lua` record in the console (Pencil at 1 px, `app.useTool{tool='pencil', brush=Brush(1), …}` inside
  `app.transaction`, asserting `app.isUIAvailable`), never a builder; save, quit Aseprite, `rmdir` the lock; prove a
  byte-identical headless rebuild. Run no headless batch during the session (same macOS app identifier). Aseprite does
  not watch files: reopen after a rebuild.
- **Parts change only through recorded corrections** (§5.4); palette colours only; then rebuild headless and prove the
  rebuild byte-identical.

### 10.7 The orchestrator's own duties

- **Codex never commits.** Review each run (quickstart Step 11), then commit with the session's attribution lines and
  G127 cited. Every report must confirm "no commit made".
- **Read `last.md` and the report, not `stderr.log`.** Rejected `apply_patch` calls and "unable to locate image" for
  files not yet written are routine noise.
- **Run art and app in parallel** against one committed contract. Commit any amendment to **both** branches and chain
  it to both runs.
- **Review app code** with three lenses plus two adversarial skeptics per finding; fix in the same Codex session; show
  each regression failing before its fix; check test strength by mutation.
- **Your own Claude subagents** follow `docs/goals/working-method.md` ("Workflow agents run on sonnet/haiku unless the
  owner says otherwise"). The owner has also asked for implement/review/fix subagents at medium effort; that rule is
  not in the repository, so confirm it at S1 if your loaded memory does not carry it.

---

## 11. Quality bars and checks

| Bar | Enforced by (new character: `$ART/tools/…` ports; app: Swift tests looped per §9.6) |
|---|---|
| Palette lock: every opaque pixel a declared colour, hidden layers included | `H.assertPalette` in every builder; `verify*.py`; `SpriteAssetTests` |
| Binary alpha (0 or 255) | `verify.py`; `SpriteAssetTests` |
| Exact ordered tag list per sheet; forward; no `repeat` field | `verify.py` (`EXPECTED`); `MascotRegistryTests`; `BookwormSpriteTests` |
| **Exact timings from an independent transcription** (`IDLE_MS`, `READ_BLOCKS`, `POSE_MS`, `SMALL_MS`); a timing change goes into the script table **and** `verify.py` | `verify.py` |
| Caps: frame 40–4,000 ms; loop 0.4–30 s; beat ≤ 800; perk ≤ 400; transition ≤ 1,600; one-frame tags 1,000; animated room frames in multiples of 10 | `verify.py`; `SpriteTestAssets.assertCaps` |
| Full canvas, untrimmed; PNG size = `meta.size`; side ≤ 2,048 | `verify*.py`; `SpriteSheet.init?`; `SpriteAssetTests` |
| No `/Users/` or `/private/` in any JSON or manifest | verifiers; `manifest.py`; `SpriteAssetTests` |
| Slices: `ink` = recomputed union; `eye`/`lensL`/`lensR` identical across room sheets; `errorLensL` on error | `verify.py`; `RoomSpriteTests`; `BookwormArtTests` |
| Outline rule on the saved `body` layer (exported alone with `--layer body`) | `verify.py` |
| State marks on every frame (prop px, identity marks, lids, Xs, drop, z box, base row) | `checkFrame` in the builder; `verify.py`; `BookwormPoseSpriteTests`; `BookwormStateTests` |
| Irregular blinks (runs, max/min gap ≥ 1.6) | `verify.py`; `BookwormPoseSpriteTests.testBlinksHaveIrregularCyclicGaps` |
| Eye tracking while reading; exactly 3 uneven flips; cover seams pixel-equal; both covers ≥ 6 px in swap frames; attentive f5 ≠ f0 | `verify.py` |
| Tag GIFs match the sheet frames | `verify.py` (`--tag` after the filename, with `--save-as`) |
| Night: exact relight, identical alpha, contrast floors, day art frozen | `verify_night.py`; `NightWormSpriteTests` |
| Ruling 9; clock clearance; redraw budget | the `verify.py` ports; `WindowSpritesTests`; `RoomClockTests`; `RoomClockSpriteTests`; `SpriteClipTests` |
| Manifest complete, hashes match, required fields | `manifest.py`; `$BW/tools/verify_room.py`; `SpriteAssetTests` |
| Budgets: bytes ≤ 6 MiB; decoded pixels per D4; ≤ 1,024 distinct rects per room sheet | `verify_room.py`; `SpriteAssetTests`; `BookwormLookRendererTests` |
| Byte-identical re-export, within a run and across two runs | every verifier; `check_rebuild.py`; `check_scenery_rebuild.py` |
| Preview: no remote URLs, every sheet present, tile count = tag count, room combinations map correctly | `check_preview.mjs` (mock DOM; real playback is checked by eye) |
| The bookworm and the room unchanged | quickstart Step 11's `git status`/`git diff` checks |

**Human bars, which no script checks:** the silhouette and identity features match the reference side by side; timing
uses holds, anticipation, overlap and secondary motion; loops never pop; every look reads at 1× on light and dark and
in both night sheets; every composite has been looked at.

---

## 12. Known gotchas

**Aseprite CLI**
- `--script-param` must come **before** `--script`; params after it are dropped.
- **A batch run can exit 0 after a Lua error.** That is why `run_checked.lua` and its completion marker exist; never
  drop them.
- A missing input file for an export **exits 0** with "File not found": check outputs exist and are non-empty.
- `--tag` before the filename filters a `--sheet` but keeps whole-sprite indices; after the filename it is ignored for
  `--sheet` but filters `--save-as`. Never pass `--tag` for an app sheet.
- `--split-tags` with `--sheet` is broken. `--trim` changes frame sizes and collapses frames.
- `--sheet-pack` de-duplicates identical frames: index rects by frame position.
- `--save-as x.png` on a multi-frame sprite writes `x1.png`, `x2.png`, …
- Hidden layers are omitted from exports. In the JSON, `repeat` is a string present only when > 0; `from`/`to` are
  0-based and inclusive.
- Each headless `app.open`/save writes `~/Library/Application Support/Aseprite/files/<mangled>.ini` (bookworm spec
  §6.1); harmless, leave it, and never delete Aseprite's other support files.

**Aseprite API**
- Durations are truncated through a float: set `(ms+0.5)/1000` (plain `ms/1000` loses 1 ms on 48 values between 1,001
  and 4,095).
- **Appending a frame after a tag that ends on the last frame silently grows the tag.** Create tags last
  (`H.recorder`); `build_night` deletes the tags, appends, then recreates them.
- Creating layers via `pairs()` scrambles the stack: create them explicitly, back to front (`H.layers`).
  `layer.isReference` is read-only (use a hidden layer). `H.assertPalette` checks hidden cels too.
- `drawImage` blends, and transparent source pixels leave the destination unchanged: erase with `drawPixel(x,y,0)`.
- Reading a missing field **raises** instead of returning nil; `app.command.*` acts on `app.sprite`; `saveAs` changes
  `spr.filename`; `json.decode` returns floats.
- `"$ASE" --shell` with piped stdin runs one chunk per line: use globals.
- **`ase_helpers.lua` quirk:** the "additions" block (`H._parts = {}` and the helpers after it) appears four times,
  including inside `H.paletteFromJson`, `H.grid` and `H.loadReference`; each call resets the parts cache, so re-fill
  `H._parts` after loading the palette.

**GIF and Pillow**
- GIF delays are centiseconds: room frame ms are multiples of 10.
- GIFs ignore direction and repeats, and encoders merge held frames: compare pixel content and accumulated duration.
- Aseprite's GIF quantizer merged two night colours one RGB level apart: write QA GIFs with an exact Pillow palette.
- Read durations inside a `gif.seek(k)` loop; `ImageSequence.Iterator` reports a stale `info['duration']`.

**Process**
- **`qa/` is gitignored but holds the registries.** Build before verifying.
- **The bookworm's `manifest.py` reads its authoring provenance from the static `$BW/authoring-provenance.json`** and
  only the Aseprite binary's `--version` live, so a rebuild never needs the Codex CLI; an Aseprite upgrade still changes
  every bookworm entry's `generator` until §4.7's keep-unchanged rule lands. The new character records its model,
  versions and date as constants in `tools/character.py` (§4.6), never from a live CLI call.
- **The bookworm's tools own all of `$RES` until §4.7's patch lands:** `manifest.py` (exact-set assert, `role` by
  `bookworm-` prefix), `verify_room.py` (exact coverage; `source`/`script` resolved under `$BW`), `make_preview.py`
  (embeds every JSON, breaking `check_preview.mjs`'s exact set).
- **The redraw-budget, ruling-9, night, slice and pixel tests check only the default skin** until looped (§9.6): a
  green suite says nothing about the new character before that.
- The browser tool rejects `file://`: `preview.html` playback is a manual check by the owner. Say so; never claim it.
- Interrupted verifiers leave `qa/verify-*` and `qa/night-verify-*` temp folders; stale QA folders (the bookworm's
  `qa/bookworm-small-dark/`) inflate rebuild globs.
- Never a bare `git stash`: the stash stack is shared by every worktree and session.

**Docs and comments that are wrong today; do not trust them**
- **`docs/goals/TODO.md` R-BW12 and the bookworm spec §0, §3.1 parts row, §9 briefs, §10.6:** computer use in
  Aseprite. Superseded by the 2026-10-02 headless rule (§1, D13). The spec's manifest `authoring` example (§6.3) and §8
  amendment text repeat the phrase; do not copy them.
- **`$BW/lua/dev_loop.lua` header:** "Then: open -a Aseprite <file.aseprite>". Forbidden; delete it in your copy.
- **Bookworm spec §6.1's `export_all.sh`:** predates `run_checked`, `check_room_parts`, `build_night`, `build_clock`,
  `build_skyfx`, and runs verify before manifest. Read the real script (§4.3).
- **Bookworm spec §5.1–5.2's seven mood weathers** (also `ROOM_TAG_TIMINGS.md`, `RUN_B_REPORT.md`): superseded by the 15
  `<base>-<time>` tags (§8.7).
- **`$BW/tools/check_wormfix_rebuild.py`:** asserts exactly 162 files, but its globs now match more (night sheets), so
  it fails as written. Use `check_scenery_rebuild.py`.
- **The wall-clock position:** older notes say (93,37); the truth, pinned by a Swift test, is (94,34).
- **The G127 row** suggests a picker in Settings → General plus a right-click on the worm; the shipped selector is
  Settings → Sleep → Mascot (G176). Edit the row in place in your PR.
- **`docs/architecture/app.md`** says "today its only entry is **Bookworm**" and "a second character's own design
  remains open": your PR makes both wrong; update them.
- **Source comments that still describe red error pupils:** `$SRC/MenuBar/BookwormPose.swift:127` ("error pupils stay
  red"), `$SRC/MenuBar/BookwormState.swift:28-29` ("Red pupils and a glitch frame") and the unused
  `"e": 0xE5484D // error red pupils` key in `BookwormPalette` (`$SRC/MenuBar/BookwormOverlays.swift:15`). The shipped
  error look is black X eyes plus the sweat drop, with no red (D11). Do not copy these into a spec or prompt. A cleanup
  PR may fix them; a mascot PR does not need to.

---

## 13. Worked example: the bookworm

Art root: `app/CicadaApp/Art/sprites/bookworm-2026-10-01/`. Its finished state is commit `e0c21b45` on
`feat/study-room-sprites`; read it on `dev` once G176 merges (Step 1), or with `git show feat/study-room-sprites:<path>`
until then.

| What | Path (under the art root unless absolute-from-root) |
|---|---|
| Owner's originals | `reference/` (`bookworm.png` base, five emotions, `bookworm_all_states.png`, `bookworm_menu_bar.png`, `glasses.png`, `cicada.png`) |
| Tracing bases | `tracing/ref_70x47.*`, `tracing/ref_56x38.*` |
| Parts (authority) | `parts/worm-parts.aseprite` (64 × 48, 145 tags), `parts/worm-small-parts.aseprite` (18 × 18, 13), `parts/room-parts.aseprite` (110 × 64, 33) |
| Sources | `src/bookworm-<state>.aseprite` × 8, `src/bookworm-<state>-night-{dark,lit}.aseprite` × 16, `src/bookworm-small.aseprite`, `src/room-*.aseprite` × 11; `menubar.aseprite` (an alias at the art root) |
| Builders | `lua/build_worm.lua`, `build_worm_small.lua`, `build_night.lua`; room: `build_room`, `build_clock`, `build_weather`, `build_skyfx`, `build_spines`, `check_room_parts` |
| Script tables and libraries | `lua/worm_scripts.lua`, `error_eyes.lua`, `ase_helpers.lua`, `room_common.lua`, `scenery_common.lua`, `run_checked.lua` |
| Correction records | headless: `lua/fix_parts.lua`, `refine_wormfix_parts.lua`; GUI (before the headless rule): `gui_wormfix_face.lua`, `gui_owner_error.lua`, `gui_room_tune.lua`, `gui_room_final.lua` and other historical `gui_*` |
| Pipeline and verifiers | `tools/export_all.sh`, `verify.py`, `verify_night.py`, `verify_room.py`, `verify_clock.py`, `night_palette.py`, `manifest.py`, `make_preview.py`, `check_preview.mjs`, `check_scenery_rebuild.py` |
| Review tools | `tools/make_review.py`, `make_wormfix_review.py`, `make_scenery_review.py`, `make_integration_review.py`, `make_report.py` |
| Data | `palette.json`, `room-plan.json`, `room-motion.json`, `room-light-map.json`, `day-art-contract.json` (18 sheets) |
| Preview and demos | `preview.html`; `demo/bookworm-reading-cycle@6x.gif` (3 covers, 255 frames, 65,520 ms), `demo/bookworm-mad-demo@6x.gif` |
| Reports | `README.md`, `TAG_TIMINGS.md`, `ROOM_TAG_TIMINGS.md`, `RUN_B_REPORT.md`, `WORM_FIX_REPORT.md`, `SCENERY_REPORT.md`, `INTEGRATION_REPORT.md` |
| Bundled sheets | `app/CicadaApp/Sources/CicadaApp/Resources/sprites/` (73 files: 36 pairs + the manifest) |
| Specs | `docs/specs/2026-10-01-bookworm-sprites-spec.md`, `docs/specs/2026-10-02-study-room-scenery.md`, `docs/specs/2026-10-02-study-room-sprites-finish-handoff.md` |
| Rulings and backlog | `docs/goals/TODO.md` ruling 18; `docs/goals/memory-evolution.md` G107, G127, G176 |
| App code (under `app/CicadaApp/Sources/CicadaApp/`) | `Sprites/{AsepriteSheetData,SpriteSheet,SpriteClip,SpritePlayback,SpriteLayerView,BookwormArt,MascotRegistry}.swift`; `MenuBar/{BookwormState,BookwormPose,BookwormRenderer,BookwormOverlays}.swift`; `MenuBarManager.swift`; `Views/Common/BookwormView.swift`; `Views/Sleep/{DeskScene,RoomLattice,StudyRoom,RoomModel,RoomClock,DeskHotspots,WindowWeather}.swift`; `Views/Settings/{MascotSettings,ScenerySettings}.swift`; `Theme/{Scenery,SceneClock,SceneStore,CicadaMotion}.swift` |
| App tests (under `app/CicadaApp/Tests/CicadaAppTests/`) | `SpriteTestAssets`, `SpriteAssetTests`, `SpriteSheetTests`, `SpriteClipTests`, `BookwormArtTests`, `BookwormSpriteTests`, `BookwormPoseSpriteTests`, `BookwormStateTests`, `BookwormRendererTests`, `BookwormLookRendererTests`, `NightWormSpriteTests`, `RoomSpriteTests`, `WindowSpritesTests`, `RoomClockTests`, `RoomClockSpriteTests`, `DeskSceneLayoutTests`, `MascotRegistryTests`, `MascotSettingsTests`, `SceneryTests`, `SleepNumbersLintTests` |

**The run history, as a template for sequencing:**
1. **Spec workflow** (Claude): six readers → writer → two critics → revision; a 3,000-line binding spec.
2. **Run A (worm) and Run C1 (app part 1) in parallel**, two worktrees. Run A: 10 pairs, 138 tags, 1,127 frames.
3. **Five-lens art review and the C1 code review** → an art-director fix list and code fixes in the same sessions.
4. **Worm fix rounds 1–3** (before the headless rule, under a shared GUI lock), in parallel with Run B (the room),
   chained on owner decisions (black X eyes, no red; one dark-outline menu sheet); round 3 resumed after a network
   outage. Result: 9 sheets, 130 tags, 1,095 frames, 162 files byte-identical.
5. **Merges, then C2** (the app on the real sheets). Conflicts in README, TODO, the backlog row and `verify.py`; a
   freed key letter reused by the room broke a key-based check (judge by role); sheet counts 19 → 18.
6. **The owner's preview review**, which produced the scenery contract (time from the clock; weather from local weather,
   Sleep's state or his choice; a dark room at night and in rain; mist and rainbow/shooting-star overlays; a wall clock).
7. **Night and skies (art) and scenery (app) in parallel**, with the clock amendment chained to both. Result: 36 pairs,
   429 tags, 4,426 frames.
8. **Final integration and the mascot selector** (`e0c21b45`): palette loader from every declared section, the clock
   where the art put it, rain inside the redraw cap, pinned hotspots, Settings → Mascot with the registry.

**Lessons that made the quality:**
- A binding spec with exact names and numbers; owner decisions as dated rulings, never chat.
- Contact sheets (every frame of a tag in a row at 6× with ms) so motion can be judged from a still.
- A five-lens art review with an art-director synthesis, verified against boards.
- The headline catch was fidelity: side-by-side boards at matching size from day one.
- Verifiers for palette lock, binary alpha, tags, caps, marks per frame, eye tracking, blink irregularity, window
  visibility behind the character, rain-never-flashes, fly path continuity and every loop's seam.
- Two byte-identical full rebuilds from saved parts: the proof that nothing manual leaked into the art.
- The offline `preview.html` (every tag at real timing, with mood, lamp and weather controls) is the owner's main
  review surface.

---

## Appendix A. Every authoring key: night ramp by band and pane tints

Generated from `app/CicadaApp/Art/sprites/bookworm-2026-10-01/palette.json` at `e0c21b45`. Columns 0–6 are `night.ramps[key]` by band (§7.5). *Pane dusk* and *Pane night* are `scenery.ramps.dusk[key]` and `scenery.ramps.night[key]`; they apply only to `room-weather` pixels (§8.7). A day colour maps to exactly one cell of its row, chosen by band (relit props and characters) or by time (the pane).

| Key | Group | Role | Day | 0 shadow | 1 moon-edge | 2 moon | 3 lamp-edge | 4 lamp-low | 5 lamp-mid | 6 lamp-hot | Pane dusk | Pane night |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `K` | worm | `worm.outline` | `#090707` | `#070A13` | `#070A13` | `#070A13` | `#070A13` | `#070A13` | `#070A13` | `#070A13` | `#1B0C1E` | `#070A13` |
| `G` | worm | `worm.body.light` | `#9CC460` | `#314834` | `#3B5440` | `#49654D` | `#55682D` | `#7A8632` | `#8A8F37` | `#A5AB3E` | `#747E54` | `#3B5440` |
| `g` | worm | `worm.body.shadow` | `#679144` | `#253B2E` | `#2C4438` | `#375243` | `#455727` | `#62702A` | `#6E752E` | `#838B33` | `#545F43` | `#2C4438` |
| `D` | worm | `worm.glasses.dark` | `#4A4647` | `#121627` | `#1A2337` | `#263148` | `#211E25` | `#292227` | `#402C24` | `#543724` | `#423245` | `#1A2337` |
| `L` | worm | `worm.glasses.light` | `#858182` | `#1B1E31` | `#252D43` | `#343F58` | `#2C282C` | `#3B3031` | `#593E2E` | `#734E32` | `#665568` | `#252D43` |
| `W` | worm | `worm.white` | `#FDFDFD` | `#8593AF` | `#95A8BF` | `#AAC1D0` | `#A59F90` | `#C1B599` | `#D9C9A8` | `#EADBBC` | `#AEA0B2` | `#95A8BF` |
| `S` | fx | `fx.sweat` | `#5FC8FB` | `#3F678D` | `#4F80A7` | `#68A0C0` | `#588091` | `#779EA4` | `#98B6B9` | `#B4D0CA` | `#4F80B1` | `#4F80A7` |
| `m` | worm | `worm.small.body` | `#ACEC62` | `#202D2C` | `#2C403D` | `#3D594F` | `#343928` | `#474A2C` | `#6A5F29` | `#88782B` | `#7D9655` | `#2C403D` |
| `B` | book | `book.cover1.mid` | `#097FFD` | `#091E44` | `#0F2D5C` | `#163E78` | `#15273A` | `#152F46` | `#243D45` | `#324E50` | `#1B54B2` | `#0F2D5C` |
| `b` | book | `book.cover1.dark` | `#0055B9` | `#08183A` | `#0D254E` | `#143466` | `#132132` | `#12253A` | `#203038` | `#2D3D3F` | `#163B89` | `#0D254E` |
| `H` | book | `book.cover1.light` | `#2890FD` | `#0E2044` | `#14305C` | `#1E4378` | `#1B2A3A` | `#1E3446` | `#314345` | `#425450` | `#2E5EB2` | `#14305C` |
| `C` | book | `book.page.cream` | `#FEF7EC` | `#2C2F42` | `#3B4258` | `#515B73` | `#433B38` | `#614C43` | `#8D6341` | `#B47C4C` | `#AE9CA8` | `#3B4258` |
| `P` | book | `book.page.grey` | `#BCB8B4` | `#131A2B` | `#172035` | `#1C2840` | `#231C20` | `#2D2324` | `#3D2D23` | `#50372C` | `#877686` | `#2F374D` |
| `1` | book | `book.cover2.mid` | `#B8433A` | `#221525` | `#2E2235` | `#403045` | `#361E23` | `#4B2125` | `#6F2B21` | `#8F3621` | `#84303D` | `#2E2235` |
| `2` | book | `book.cover2.dark` | `#7E2620` | `#1A1121` | `#241D2F` | `#32293E` | `#2B1920` | `#391A20` | `#56221D` | `#702B1B` | `#621F2D` | `#241D2F` |
| `3` | book | `book.cover2.light` | `#D5675B` | `#261A2B` | `#33293B` | `#47394E` | `#3B2327` | `#542A2A` | `#7C3627` | `#9E4429` | `#964651` | `#33293B` |
| `4` | book | `book.cover3.mid` | `#C98A2B` | `#241F23` | `#312F32` | `#444141` | `#392921` | `#503222` | `#76411F` | `#98521D` | `#8F5B34` | `#312F32` |
| `5` | book | `book.cover3.dark` | `#8F5A12` | `#1C191F` | `#27262D` | `#36363B` | `#2E211E` | `#3E271E` | `#5D321A` | `#793F17` | `#6C3E25` | `#27262D` |
| `6` | book | `book.cover3.light` | `#E3AE52` | `#282429` | `#363539` | `#4A4A4B` | `#3E2F26` | `#583B29` | `#824C26` | `#A56027` | `#9E704B` | `#363539` |
| `j` | worm | `worm.lid` | `#46672F` | `#131D20` | `#172325` | `#1C2C2A` | `#1E2B1D` | `#28371D` | `#35411F` | `#454C24` | `#404636` | `#172325` |
| `r` | worm | `worm.mouth` | `#5A2230` | `#151124` | `#1D1C33` | `#2A2842` | `#241822` | `#2E1923` | `#472120` | `#5D291F` | `#4C1C37` | `#1D1C33` |
| `Z` | fx | `fx.z.bright` | `#8896FF` | `#8896FF` | `#8896FF` | `#8896FF` | `#8896FF` | `#8896FF` | `#8896FF` | `#8896FF` | `#6862B3` | `#8896FF` |
| `Y` | fx | `fx.z.mid` | `#B3BBFF` | `#B3BBFF` | `#B3BBFF` | `#B3BBFF` | `#B3BBFF` | `#B3BBFF` | `#B3BBFF` | `#B3BBFF` | `#8178B3` | `#B3BBFF` |
| `X` | fx | `fx.z.pale` | `#DADFFF` | `#DADFFF` | `#DADFFF` | `#DADFFF` | `#DADFFF` | `#DADFFF` | `#DADFFF` | `#DADFFF` | `#998EB3` | `#DADFFF` |
| `q` | fx | `fx.sparkle` | `#FFCB57` | `#FFCB57` | `#FFCB57` | `#FFCB57` | `#FFCB57` | `#FFCB57` | `#FFCB57` | `#FFCB57` | `#AF824E` | `#FFCB57` |
| `Q` | fx | `fx.sparkleCore` | `#FFF1B8` | `#FFF1B8` | `#FFF1B8` | `#FFF1B8` | `#FFF1B8` | `#FFF1B8` | `#FFF1B8` | `#FFF1B8` | `#AF9988` | `#FFF1B8` |
| `A` | room | `room.wall.0` | `#C7BEAA` | `#242737` | `#31384B` | `#444E62` | `#393130` | `#503F38` | `#765136` | `#96663C` | `#8D7A80` | `#31384B` |
| `E` | room | `room.wall.1` | `#D6CBB3` | `#262839` | `#343B4D` | `#475165` | `#3C3331` | `#544239` | `#7C5537` | `#9E6B3E` | `#968285` | `#343B4D` |
| `F` | room | `room.wall.2` | `#B3AA98` | `#212434` | `#2D3547` | `#3F495E` | `#352E2E` | `#493A35` | `#6D4B32` | `#8C5E37` | `#816E75` | `#2D3547` |
| `I` | room | `room.floor.0` | `#AA8864` | `#201F2C` | `#2C2E3D` | `#3D4150` | `#332928` | `#47322C` | `#694029` | `#87512B` | `#7C5A56` | `#2C2E3D` |
| `J` | room | `room.floor.1` | `#C5A47C` | `#242330` | `#303442` | `#434756` | `#382D2B` | `#4F3830` | `#75492D` | `#955C31` | `#8C6A64` | `#303442` |
| `M` | room | `room.floor.2` | `#765D48` | `#191928` | `#222737` | `#303649` | `#292225` | `#372727` | `#533324` | `#6C4024` | `#5D4045` | `#222737` |
| `N` | room | `room.wood.0` | `#5E493C` | `#151626` | `#1E2335` | `#2B3246` | `#251F23` | `#2F2325` | `#482D22` | `#5F3821` | `#4E343E` | `#1E2335` |
| `O` | room | `room.wood.1` | `#936C50` | `#1D1B29` | `#272939` | `#373A4B` | `#2F2426` | `#402B29` | `#5F3725` | `#7B4626` | `#6E494A` | `#272939` |
| `R` | room | `room.wood.2` | `#C69A69` | `#24222D` | `#31323E` | `#444551` | `#392C29` | `#4F362D` | `#75462A` | `#96582C` | `#8D6459` | `#31323E` |
| `T` | room | `room.lamp.0` | `#3F4A52` | `#111629` | `#182339` | `#23324B` | `#1F1F26` | `#262329` | `#3B2D26` | `#4E3927` | `#3C344B` | `#182339` |
| `U` | room | `room.lamp.1` | `#70818B` | `#181E32` | `#212D45` | `#2F3F5A` | `#28282D` | `#353033` | `#503E30` | `#684E34` | `#59556D` | `#212D45` |
| `V` | room | `room.lamp.2` | `#CBD7D5` | `#242A3E` | `#323D54` | `#45546D` | `#3A3536` | `#51453F` | `#77593D` | `#997046` | `#90899A` | `#323D54` |
| `a` | room | `room.lampWarm.0` | `#D39A53` | `#283247` | `#34435C` | `#455B78` | `#554632` | `#816239` | `#B17F3E` | `#D09242` | `#95644C` | `#D09242` |
| `c` | room | `room.lampWarm.1` | `#FFF2C7` | `#36435A` | `#465778` | `#5B739B` | `#746548` | `#B1925F` | `#E0BA7E` | `#FFE5AB` | `#D7AF82` | `#4B5266` |
| `d` | room | `room.glow.0` | `#DDC29B` | `#272735` | `#353948` | `#494F5E` | `#3D322F` | `#574035` | `#7F5233` | `#A26838` | `#9B7C77` | `#353948` |
| `f` | room | `room.glow.1` | `#EBCB9C` | `#292835` | `#373B48` | `#4C515F` | `#40332F` | `#5B4236` | `#855533` | `#AA6B38` | `#A38278` | `#373B48` |
| `h` | room | `room.bag.0` | `#564458` | `#14162A` | `#1C223B` | `#29304D` | `#413A2A` | `#4E4330` | `#5C4B33` | `#6B5436` | `#4A314F` | `#1C223B` |
| `i` | room | `room.bag.1` | `#826778` | `#1A1A2F` | `#242941` | `#333955` | `#4E4230` | `#5E4D35` | `#6E583B` | `#7D6340` | `#644662` | `#242941` |
| `k` | room | `room.bag.2` | `#BBA1AA` | `#222337` | `#2F334B` | `#414762` | `#615039` | `#745F41` | `#866D4B` | `#987953` | `#866980` | `#2F334B` |
| `l` | room | `room.leaf.0` | `#294A43` | `#0E1627` | `#142336` | `#1E3247` | `#1B1F24` | `#1F2326` | `#322D23` | `#433923` | `#2F3442` | `#142336` |
| `n` | room | `room.leaf.1` | `#49715B` | `#121C2B` | `#1A2A3B` | `#263B4E` | `#212527` | `#292C2A` | `#3F3927` | `#544829` | `#424C51` | `#1A2A3B` |
| `o` | room | `room.leaf.2` | `#799968` | `#19212D` | `#23323E` | `#314551` | `#2A2B28` | `#38362D` | `#54452A` | `#6D582C` | `#5F6458` | `#23323E` |
| `p` | room | `room.pot.0` | `#AE6751` | `#201A29` | `#2C2939` | `#3E394B` | `#342326` | `#482A29` | `#6B3626` | `#894426` | `#7E464B` | `#2C2939` |
| `s` | room | `room.pot.1` | `#D79568` | `#26212D` | `#34313E` | `#484451` | `#3C2B28` | `#55352D` | `#7C442A` | `#9F562C` | `#976158` | `#34313E` |
| `t` | room | `room.mug.0` | `#465D69` | `#12192D` | `#1A273E` | `#253651` | `#202229` | `#28272D` | `#3E332A` | `#52402C` | `#404059` | `#1A273E` |
| `u` | room | `room.mug.1` | `#ADD1CF` | `#20293D` | `#2C3C52` | `#3E526C` | `#343435` | `#48433E` | `#6A573C` | `#896E45` | `#7E8596` | `#2C3C52` |
| `v` | weather | `weather.sky.night.0` | `#18243B` | `#0B1125` | `#111C35` | `#1A2945` | `#181923` | `#191A25` | `#2A2122` | `#3A2A21` | `#51415E` | `#18243B` |
| `w` | weather | `weather.sky.night.1` | `#26334A` | `#0D1328` | `#141F38` | `#1D2C49` | `#1A1B25` | `#1E1D28` | `#302624` | `#413025` | `#98636B` | `#26334A` |
| `x` | weather | `weather.sky.night.2` | `#35465C` | `#0F162B` | `#17233B` | `#21314E` | `#1D1E27` | `#22222B` | `#372C28` | `#493729` | `#C18B68` | `#35465C` |
| `y` | weather | `weather.sky.dawn.0` | `#725363` | `#18182C` | `#22253D` | `#2F3450` | `#292028` | `#35252C` | `#513029` | `#693C2B` | `#51415E` | `#18243B` |
| `z` | weather | `weather.sky.dawn.1` | `#D59A84` | `#262231` | `#333243` | `#474558` | `#3B2C2C` | `#543631` | `#7C462F` | `#9E5833` | `#98636B` | `#26334A` |
| `0` | weather | `weather.sky.dawn.2` | `#F3C697` | `#2A2834` | `#393A47` | `#4E505D` | `#41332E` | `#5D4135` | `#885332` | `#AE6937` | `#C18B68` | `#35465C` |
| `7` | weather | `weather.sky.clear.0` | `#508EB0` | `#132038` | `#1B304C` | `#274264` | `#222A31` | `#2B3339` | `#424237` | `#57533D` | `#51415E` | `#18243B` |
| `8` | weather | `weather.sky.clear.1` | `#75ADC4` | `#18243B` | `#223550` | `#304A69` | `#292F34` | `#363B3C` | `#524C3A` | `#6B5F42` | `#98636B` | `#26334A` |
| `9` | weather | `weather.sky.clear.2` | `#A0CAD5` | `#1E283E` | `#2A3A54` | `#3A506D` | `#313336` | `#44413F` | `#65553D` | `#826B46` | `#C18B68` | `#35465C` |
| `!` | weather | `weather.sky.fair.0` | `#8DADB9` | `#1C243A` | `#26354E` | `#364A66` | `#2E2F32` | `#3E3B3A` | `#5D4C38` | `#785F3F` | `#51415E` | `#18243B` |
| `#` | weather | `weather.sky.fair.1` | `#B4CDD1` | `#21293D` | `#2D3B53` | `#3F516C` | `#353435` | `#4A423F` | `#6D563D` | `#8C6C45` | `#98636B` | `#26334A` |
| `$` | weather | `weather.sky.overcast.0` | `#74858C` | `#181F32` | `#222E45` | `#30405A` | `#29282D` | `#363133` | `#523F30` | `#6A5035` | `#51415E` | `#18243B` |
| `%` | weather | `weather.sky.overcast.1` | `#9BABAA` | `#1E2437` | `#29354B` | `#394962` | `#302E30` | `#423A38` | `#634B36` | `#7F5F3C` | `#98636B` | `#26334A` |
| `&` | weather | `weather.sky.storm.0` | `#344A56` | `#0F162A` | `#16233A` | `#20324C` | `#1D1F26` | `#22232A` | `#362D26` | `#493928` | `#393745` | `#18243B` |
| `(` | weather | `weather.sky.storm.1` | `#4F6470` | `#131A2E` | `#1B283F` | `#273853` | `#222329` | `#2A292E` | `#42352B` | `#57432E` | `#51475B` | `#26334A` |
| `)` | weather | `cloud.0` | `#CDD9D7` | `#252A3E` | `#323D54` | `#45546E` | `#3A3636` | `#524540` | `#78593E` | `#9A7147` | `#956F80` | `#35445D` |
| `*` | weather | `cloud.1` | `#EDF0E2` | `#292E40` | `#384156` | `#4D5A71` | `#403937` | `#5B4B41` | `#866040` | `#AB7A49` | `#C99B9B` | `#506079` |
| `+` | weather | `celestial.sun.0` | `#F4BE56` | `#2A272A` | `#39383A` | `#4F4E4C` | `#413126` | `#5E3F2A` | `#895126` | `#AE6628` | `#F4BE56` | `#F4BE56` |
| `,` | weather | `celestial.sun.1` | `#FFE59D` | `#2C2C35` | `#3B3F48` | `#51575F` | `#43382F` | `#614836` | `#8E5D33` | `#B47539` | `#FFE59D` | `#FFE59D` |
| `-` | weather | `celestial.moon.0` | `#E6E8C6` | `#282C3C` | `#364051` | `#4B5869` | `#3F3834` | `#59493D` | `#835E3B` | `#A77643` | `#E6E8C6` | `#E6E8C6` |
| `/` | weather | `celestial.star.0` | `#DFE6ED` | `#272C42` | `#353F58` | `#4A5774` | `#3D3838` | `#574843` | `#805D42` | `#A3764C` | `#DFE6ED` | `#DFE6ED` |
| `:` | weather | `celestial.star.1` | `#8A9BAB` | `#1B2237` | `#26324B` | `#354562` | `#2D2C31` | `#3D3638` | `#5B4636` | `#76583C` | `#8A9BAB` | `#8A9BAB` |
| `;` | weather | `weather.rain.0` | `#849EAB` | `#1A2237` | `#25324B` | `#344662` | `#2C2C31` | `#3B3738` | `#594736` | `#735A3C` | `#987487` | `#4F657E` |
| `<` | weather | `weather.rain.1` | `#B8CDDE` | `#222940` | `#2E3B55` | `#405170` | `#363437` | `#4B4241` | `#6F563F` | `#8F6C48` | `#C6A9B5` | `#738DA7` |
| `=` | weather | `weather.curtain.0` | `#735B6C` | `#18192D` | `#22263F` | `#303652` | `#292229` | `#36272D` | `#51322A` | `#6A3F2D` | `#493445` | `#1E253A` |
| `>` | weather | `weather.curtain.1` | `#B098A2` | `#212136` | `#2D3149` | `#3E4460` | `#342B2F` | `#493537` | `#6C4534` | `#8A573A` | `#825C67` | `#34384E` |
| `?` | fly | `fly.body.0` | `#292A2E` | `#0E1223` | `#141E32` | `#1E2A42` | `#1B1A22` | `#1F1B23` | `#32231F` | `#432C1E` | `#2F2136` | `#141E32` |
| `@` | fly | `fly.wing.0` | `#F3E5B3` | `#2A2C39` | `#393F4D` | `#4E5765` | `#413831` | `#5D4839` | `#885D37` | `#AE753E` | `#A89185` | `#393F4D` |
| `[` | spine | `spine.mask.0` | `#FFFFFF` | `#2C3045` | `#3B445C` | `#515D78` | `#433C3B` | `#614E46` | `#8E6545` | `#B47F50` | `#AFA1B3` | `#3B445C` |

Keys used: 81 of 87. Free keys: `]` `^` `e` `{` `}` `~`.

## Appendix B. The light map over the whole room (2 × 2-cell preview)

Each character is the highest band in a 2 × 2 block of `app/CicadaApp/Art/sprites/bookworm-2026-10-01/room-light-map.json`; `.` is band 0. Top-left origin, room cells. Columns 112–159 are omitted (all 0: the pile column is never lit). The JSON is the authority.

```
UNLIT room (night-dark): moon map only
x→     0         20        40        60        80        100   
y 0- 1 ........................................................
y 2- 3 ........................................................
y 4- 5 ........................................................
y 6- 7 ........................................................
y 8- 9 ........................................................
y10-11 ........................................................
y12-13 ........................................................
y14-15 ........................................................
y16-17 ........................................................
y18-19 ........................................................
y20-21 ........................................................
y22-23 ........................................................
y24-25 ........................................................
y26-27 ........................................................
y28-29 ........................................................
y30-31 ........................................................
y32-33 ........................................................
y34-35 ........................................................
y36-37 ........122222222222222222222...........................
y38-39 .........22222222222222222222...........................
y40-41 .........22222222222222222222...........................
y42-43 ..........22222222222221222211..........................
y44-45 ..........12222222222222222221..........................
y46-47 ..........112222222222221222211.........................
y48-49 ...........12222222222222222221.........................
y50-51 ...........112222222222222222211........................
y52-53 ............12222222222221222211........................
y54-55 ............11111111111111111111........................
y56-57 ............12222222222222222221........................
y58-59 .............12222222222222222221.......................
y60-61 ..............12222222222222222221......................
y62-63 ...............12222222212222222211.....................
```

```
LIT room (night-lit): max(moon, lamp)
x→     0         20        40        60        80        100   
y 0- 1 4444444444444444444444433333333333......................
y 2- 3 55555555554444444444444433333333333.....................
y 4- 5 555555555555544444444444443333333333....................
y 6- 7 5555555555555544444444444443333333333...................
y 8- 9 55555555555555554444444444443333333333..................
y10-11 55555555555555555444444444443333333333..................
y12-13 566666665555555555444444444443333333333.................
y14-15 666666666655555555444444444444333333333.................
y16-17 6666666666655555555444444444443333333333................
y18-19 6666666666665555555444444444443333333333................
y20-21 6666666666665555555544444444444333333333................
y22-23 6666666666666555555544444444444333333333................
y24-25 6666666666666555555544444444444333333333................
y26-27 6666666666666555555544444444444333333333................
y28-29 6666666666666555555544444444444333333333................
y30-31 6666666666665555555444444444443333333333................
y32-33 6666666666665555555444444444443333333333................
y34-35 666666666665555555544444444444333333333.................
y36-37 666666666555555555444444444443333333333.................
y38-39 556666655555555554444444444443333333333.................
y40-41 55555555555555554444444444443333333333..................
y42-43 5555555555555554444444444443333333333...................
y44-45 5555555555555544444444444433333333333...................
y46-47 555555555555444444444444433333333333....................
y48-49 44555555444444444444444433333333333.....................
y50-51 4444444444444444444444333333333333......................
y52-53 444444444444444444443333333333333.......................
y54-55 44444444444444443333333333333331........................
y56-57 5666666665555555444444444443333333333...................
y58-59 6666666666666555555444444444443333333333................
y60-61 6666666666666555555544444444443333333333................
y62-63 666666666666555555444444444443333333333.................
```
