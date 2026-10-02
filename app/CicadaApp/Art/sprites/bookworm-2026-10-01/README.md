# Bookworm sprites — sources, preview and integration

**Open [preview.html](preview.html) in a browser straight from disk.** It plays every worm state, beat, transition,
three-cover reading cycle, the 15 time/weather skies, six overlays, lamp/fly and clock, day/dark rooms, and the
18 × 18 menu strips on both bar appearances at their real sheet timings. No server or network is needed.

**Current delivery (2026-10-02): 36 sheet pairs, 429 tags, 4,426 frames**, integrated with the app on
`feat/study-room-sprites`; owner review and merge to dev remain pending. The
[scenery contract](../../../../../docs/specs/2026-10-02-study-room-scenery.md) wins over the earlier sprite spec
where they differ. [INTEGRATION_REPORT.md](INTEGRATION_REPORT.md) records fixes, checks, exact render paths and open work.

| Sheets | Canvas | Tags |
|---|---|---|
| Eight `bookworm-<state>` | 64 × 48 | All states, poses, beats, covers and sleeping transitions |
| Sixteen `bookworm-<state>-night-{dark,lit}` | 64 × 48 | Exact day tags, frame counts, holds, slices and alpha |
| `bookworm-small` | 18 × 18 | Eight states; one dark-outline sheet on either menu appearance |
| `room-weather` | 36 × 32 | Five bases × day/dusk/night |
| `room-skyfx` | 36 × 32 | Three mist, two rainbow, one shooting-star loop |
| `room-backdrop`, `room-lamp` | Existing | `dark`, `lit`, `night-dark`, `night-lit` |
| `room-window`, `room-plant`, `room-beanbag`, `room-mug` | Existing | `idle`, `night-dark`, `night-lit` |
| `room-clock` | 15 × 15 | Two dials, 60 angles each for day/night hour/minute/second hands |
| `room-fly`, `room-spines` | Existing | Fly buzz; five kinds × body/light/shade masks |

Owner 2026-10-01: error has **black X eyes plus the drop**, never red pupils. The menu retains its dark outlines on a
dark bar. The day worm totals 130 tags / 1,095 frames. [TAG_TIMINGS.md](TAG_TIMINGS.md) gives its exact holds.
Owner 2026-10-02: clock/manual time and the chosen weather source are independent of the worm. Night or rain darkens
the room; the scheduled lamp supplies a warm near-side pool. Mist means running; rainbow by day/dusk and shooting star
by night mean just finished. The clock shows the Mac's civil time and sits at **(94,34)** in [room-plan.json](room-plan.json);
it is inert. Reduce Motion omits seconds and holds sprite key frames. Low Power doubles sprite holds; hidden rooms
and Settings pause the room's leaves.

Owner 2026-10-02: this character is named **Bookworm** in Settings → Sleep → Mascot, beside The scenery.
`MascotRegistry` supplies its id, display name, sheet prefix, menu sheet and this art folder. The per-viewer choice
defaults/falls back to `bookworm`; all shared sprite readers use the selected entry. The tile shows awake room/menu
key frames with a checkmark, keyboard focus and selected VoiceOver text. A later character uses its own base/prefix,
the same sheet/tag/canvas pipeline, new manifest entries and one registry entry.

**Integration timing amendment, 2026-10-02:** rain keeps all 48 frames/pixels and seamless steps, with **100 ms** holds
in all three times (4,800 ms loops), replacing 80 ms. Independent room leaves cost at most **1,758/minute**, including
60 clock ticks, against ruling 18's unchanged 1,800 cap. The worst case is rainy-night + digesting + lamp lit.
`verify_room.py` pins the new holds; `verify_night.py` still compares historical day pixels using the unchanged baseline.
The earlier timing tables in the dated run reports describe those earlier deliveries.

## Rebuild and review

Saved `parts/worm-parts.aseprite`, `parts/worm-small-parts.aseprite` and `parts/room-parts.aseprite` own the pixels.
**Never delete the finished parts or rerun a one-time migration.** Builders in `lua/` assemble `src/`; exports go
to the app's flat `Resources/sprites/`. References in `reference/` are read-only. Historical `gui_*.lua` files
record earlier native Pencil corrections; the current pipeline runs headless and does not drive the owner's Aseprite.

From this directory:

```sh
tools/export_all.sh
python3 tools/check_scenery_rebuild.py record
tools/export_all.sh
python3 tools/check_scenery_rebuild.py compare
node tools/check_preview.mjs
```

The repeat check covers **119** saved sources/parts/exports/sidecars/manifest/preview files. Verifiers check exact
palette/alpha, all-frame relight and state marks, frame timing/slices, every motion seam, no rain flash, all-mood window
visibility, all 360 clock angles and placement, provenance hashes and bundle budgets. `palette.json` declares
**81 authoring keys** (budget 87) and keyless night/scenery/clock colours: **699 distinct RGBs**. Python, Lua and the
app acceptance loader use these same declared colour groups.

From `app/CicadaApp/`, reproduce the actual app's composites and Settings panes:

```sh
CICADA_WRITE_COMPOSITES=1 swift test --filter WindowSpritesTests
CICADA_WRITE_COMPOSITES=1 swift test --filter ScenerySettingsTests
CICADA_WRITE_COMPOSITES=1 swift test --filter MascotSettingsTests
python3 Art/sprites/bookworm-2026-10-01/tools/make_integration_review.py
```

The writer copies **552 room PNGs and ten Settings PNGs** (six scenery, four Mascot valid/fallback) into gitignored `qa/integration/`, groups them into
24 labelled boards and records every path in `qa/integration/render-index.json`. Settings uses ImageRenderer,
isolated preferences and frozen sprite frames; the source menu's text twin replaces its unsupported native
snapshot control. This checks layout/art, not a real menu click or live app motion. The separate wall clock chooses
state angles, so it does not appear in `room-motion.json`.

[SCENERY_REPORT.md](SCENERY_REPORT.md), [RUN_B_REPORT.md](RUN_B_REPORT.md) and
[WORM_FIX_REPORT.md](WORM_FIX_REPORT.md) are dated delivery records, not the current acceptance status.
Earlier art runs included superseded red pupils, a grey-rim menu variant or seven mood-only skies;
none remains in the current manifest. `qa/` is reproducible and gitignored.

## Still open

Owner motion review in preview.html and the Sleep page, demo-bank light/dark review at 0.8×–1.4× and live CPU against
dev remain the merge gate. Q1 stays explicit: the worm sleeps while a cycle runs and reads while items wait; the
owner's earlier brief requested reading while consolidating. Count props (computer, phone, globe, TV, letter tray,
calendar), the queue as a room, G175 pixel brand marks and G127's alternative character base remain separate design rounds.
B12's narrower menu lens needs an owner decision. The sleeping-outro/reading handoff can still switch a closed book
to an open book in one frame; no named reading opening beat exists, so that limit is documented.
