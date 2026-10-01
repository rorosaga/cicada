# Study room sprites — the handoff prompt (backlog G176)

The prompt Rodrigo hands a fresh session to run the study room sprites work
([the brief](2026-09-29-study-room-sprites-brief.md), backlog G175 and G176). Paste everything inside the fence. If
the brief changes, edit this prompt in the same commit so the two never disagree.

```
Dated amendment 2026-10-01: read docs/specs/2026-10-01-bookworm-sprites-spec.md in full, then the older
docs/specs/2026-09-29-study-room-sprites-brief.md. The new spec and TODO ruling 18 win wherever they differ. Also read backlog rows G175 and G176 in docs/goals/memory-evolution.md, then CLAUDE.md and
docs/goals/working-method.md. Your job is the brief's Phase 1: Cicada's new bookworm and study room as real, detailed,
animated pixel art. The base design is approved; the deferred count props still require design rounds.

STEP 1 — Closed 2026-10-01: the worm is approved. Use the owner's reference set in
app/CicadaApp/Art/sprites/bookworm-2026-10-01/reference/; see the 2026-10-01 spec. The round-1 directions are
superseded. Charcoal-grey glasses replace orange; no antennae. Implement Runs A, B and C of that spec for the approved
character and room. Q1 remains deferred. The count props, queue as a room, time-of-day palettes and night light below
are future design rounds, not extra work in the approved sprite run.

STEP 2 — Future design rounds for the full count props and the queue as a room. The 2026-10-01 spec
ships the approved worm, lamp/fly, window/weather, bean bag, plant, mug and spine textures first; the older ideas below
remain a reference wherever they fall outside that scope.

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
  · The queue as a room, read left to right — pile → worm → cart → crate → bookcase (the canvas's "Queue" boards A–K are
    the reference, not the spec): the pile is what waits (one book per origin with a plate showing its mark and count, a
    ribbon on the book being read), the cart holds what was read and waits to be filed, the crate what was set aside
    (parked or could not be read), and the bookcase fills as batches file. Spines differ by kind (chats, pages, notes,
    videos) so hue is never the only signal, and the pile folds at any size without cutting a count. Give this its own
    design rounds with me — sprites and interactions — before anything reaches Swift.
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
- R-BW12 (2026-10-01): use computer use in Aseprite for hand-correctable parts and GUI review. Rebuild and export
  every sheet headless from the parts and Lua generators, with reproducible manifest hashes. The owner chose Codex
  (gpt-6.1-sol, extra-high effort) for this job only; this replaces the earlier model split. The small-models rule
  otherwise stands. PR to dev; no merge until the owner reviews preview.html and the composites.
- Before Phase 2, ask me the open questions: the final prop set, the count buckets, the animation-lint amendment, and
  any vendor-guideline conflicts.
- Work only in your own git worktree under .worktrees/. Never edit or switch branches in the main checkout: an
  auto-updater builds from it.
- PR to dev, and don't merge the design phase without me.
```
