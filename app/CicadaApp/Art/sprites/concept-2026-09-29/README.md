# Bookworm and queue — concept, 2026-09-29

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

Next (the brief's Phase 1): turn `worm.py`'s frames and the room's props into layered, tagged `.aseprite` sources with
real per-frame timings via headless Aseprite + Lua, add the CRT, phone, TV, letter tray and calendar props, and export
sprite sheets for a native player.
