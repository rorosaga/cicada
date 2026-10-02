# Bookworm and queue — concept, 2026-09-29

**Historical concept snapshot, superseded for the shipped worm and scenery.** The owner's 2026-10-01 Bookworm
design and the 2026-10-02 scenery contract replace the concepts' palette, seven mood-only skies and night-light
deferrals. The built delivery lives in `../bookworm-2026-10-01/`: 15 weather/time skies, a dark lamp-lit room and a
wall clock. The queue as a room and count-driven props remain open design rounds. These boards and their title
metadata preserve the earlier proposals; they are not the current app contract.

The Opus design pass behind the study-room sprites brief
(`docs/specs/2026-09-29-study-room-sprites-brief.md`). Concept art, not app assets: nothing here is loaded
by the app.

- `boards/` — the 16 design-canvas artboards (`Worm*`, `Queue*`, `.dc.html`), also published on the design canvas.
- `generator/` — the Python that draws every board from pixel grids and one fixture:
  - `worm.py` — the redesigned worm: 32 × 32 room frames, 18 × 18 menu-bar frames, an 11-key palette;
  - `room.py` — the study room as the queue (pile → worm → cart → crate → bookcase), 176 × 54 cells;
  - `fixture.py` — the one set of counts every board derives from (it asserts they sum to 1,187);
  - `boards_worm.py`, `boards_queue.py`, `boards_view.py` — write `boards/` (run from anywhere; paths are relative);
  - `old_worm.py`, `old_room.json` — the current worm and room, redrawn for the before/after board;
  - `px.py`, `ui.py`, `common.py` — the pixel grid and board scaffolding; `shot.py` renders PNG previews with
    headless Chrome (it reads the app's logos from `Sources/CicadaApp/Resources/logos`).

Regenerate: `python3 generator/boards_worm.py && python3 generator/boards_queue.py && python3 generator/boards_view.py`
(standard library only). The boards come out byte-identical to the published ones.

The brief's original Phase 1 proposed turning these frames/props into tagged Aseprite sources. The owner instead
supplied Bookworm's base design, now built through the saved-parts/headless pipeline with a native sprite player.
The CRT, phone, globe, TV, letter tray and calendar props still need their own design round.
