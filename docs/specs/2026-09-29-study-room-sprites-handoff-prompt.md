# Study room sprites — the handoff prompt (backlog G176)

The prompt Rodrigo hands a fresh session to run the study room sprites work
([the brief](2026-09-29-study-room-sprites-brief.md), backlog G175 and G176). Paste everything inside the fence. If
the brief changes, edit this prompt in the same commit so the two never disagree.

```
Read docs/specs/2026-09-29-study-room-sprites-brief.md in full. Where §9 and §10 (my later refinements) differ from §3/§4,
they win. Also read backlog rows G175 and G176 in docs/goals/memory-evolution.md, then CLAUDE.md and
docs/goals/working-method.md. Your job is the brief's Phase 1: Cicada's new bookworm and study room as real, detailed,
animated pixel art. It happens in two steps, and you stop between them.

STEP 1 — The worm's base design. Give me several directions to choose from before anything else.

Start from the concept in app/CicadaApp/Art/sprites/concept-2026-09-29/: its README, generator/worm.py and room.py, and
the boards, which are also on the design canvas https://claude.ai/artifact/FDqb1tSiqsWdFQEDGYm3JF (read it with the
Artifact tool). Treat it as a reference, not the answer. Its antenna language is superseded.

- Draw 5–6 genuinely different worm directions, not recolours of one. Vary:
  · silhouette and proportions (head-to-body ratio, segment count, chubby vs slender, how it sits or curls);
  · the face (eye style, brows, mouth, cheeks);
  · the glasses (round, square, half-moon, oversized);
  · the palette and the outline treatment;
  · the grid (32×32 vs 48×48 in the room).
  Every direction keeps these constants: NO antennae, recognisably a bookworm, glasses, and legible at 18×18 in the menu
  bar. Expression lives in the eyes, brows, mouth, posture and tail.
- For each direction, make:
  · a hero portrait at room size and the 18×18 menu-bar version;
  · an expression sheet: neutral, happy, sleepy, reading, worried, curious;
  · three short animated loops: idle, reading (with the pages flipping) and sleeping (with the z's);
  · a thumbnail of it sitting in the room, day and night.
- Author these in Aseprite. Put them on the design canvas side by side, one board per direction with a one-paragraph
  rationale, plus one comparison board with all directions at both sizes.
- Then STOP and ask me to pick one direction or combine parts ("A's body, C's face"). Iterate on my pick for as many
  rounds as I ask. Show each round as new boards, and keep the old ones.
- Don't build the room, props or marks until I've approved the final worm. Their palette and proportions follow from it.

STEP 2 — Once the worm is approved: the full character, the room and the props.

- The worm: every state and response animation in the brief, drawn in the approved design.
  · Reading (while consolidating): it holds an open book, its eyes track the lines, and it FLIPS THE PAGES — a real
    page-turn animation (the page lifts, curls across the spine and settles) every few seconds, never in lockstep. It
    sets each finished book aside and picks up the next.
  · Sleeping: on the bean bag, a slow breath, and z's rising from it — a small "z", then "zz", then "zzz", growing and
    fading as they drift up, looping gently.
  · Other moods get the same care: a yawn before sleep, a stretch on waking, a cheer when a cycle finishes, worry on an
    error, a gulp when fed a file.
  · It reacts to the props: it looks at the ringing phone, turns to the spinning globe, and glances at the computer when
    a batch starts.
- The room: far more detailed pixel art than the concept.
  · Textured walls and floor.
  · Furniture with volume and shading.
  · Lived-in details: a mug, a plant, framed pictures, cables, a rug.
  · One consistent light direction.
  · Day, afternoon and night palettes that follow SceneClock.
- Each prop below shows a real count: bucketed, and with a text version of the same count.
  · A CRT-style computer on the desk for AI conversations waiting to be consolidated. It is on, with a pixel chat
    window and the marks of the waiting conversations' origins, and it types or scrolls while a batch is read.
  · A phone for social saves (X, Reddit, Instagram, LinkedIn, Pinterest, TikTok). It is lit when some are waiting, and
    it RINGS once in a while: a short buzz-and-light loop, never constant.
  · A globe of the earth for web pages and links waiting to be read, with a pin when any of them needs a login. It SPINS
    when clicked.
  · A bookshelf and a reading pile for episodes waiting and what got filed. Books move from the pile to the shelf as
    batches file.
  · A TV for videos, a letter tray for inbox questions, a calendar for events.
  · A bean bag the worm sleeps on, and a night light that glows AT NIGHT.
- Every asset is interactive:
  · hover highlights it and shows the real count in words;
  · a click plays a small response animation and opens a popover with the counts and one link to where the thing lives.
  Clicks animate and inform; they never start work (the brief's rule). Every prop gets keyboard focus and a VoiceOver
  label.
- Marks are pixel art (G175): faithful pixel renditions of each vendor's own symbol, never a default icon. That covers
  ChatGPT, Codex, the Claude Code mascot, the Claude app, Telegram, Chrome, YouTube, X, Reddit, Apple Notes, Wispr Flow
  and the rest of OriginIconography's map. Use a generic glyph only for something that has no symbol. Keep a manifest
  entry per mark: the source mark, the vendor's brand-guideline link, and "pixel rendition". Flag any vendor whose
  guidelines forbid altered logos.
- Build a preview page that plays every animation and lets me hover over and click the props. Add animated boards to the
  design canvas for my review.

How to work:
- Author everything headless:
  /Applications/Aseprite.app/Contents/MacOS/aseprite -b --script <file>.lua
  Produce layered .aseprite sources with tagged animations and per-frame timings, export PNG sheets + JSON, and save
  them where the brief says.
- Use workflows: Opus for design and pixel art, Sonnet for scripts and code, and a critic before anything is final.
- Before Phase 2, ask me the open questions: the final prop set, the count buckets, the animation-lint amendment, and
  any vendor-guideline conflicts.
- Work only in your own git worktree under .worktrees/. Never edit or switch branches in the main checkout: an
  auto-updater builds from it.
- PR to dev, and don't merge the design phase without me.
```
