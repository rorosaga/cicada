# G176: study room scenery, app implementation

The binding contract is `docs/specs/2026-10-02-study-room-scenery.md`. This app work is reviewed and committed by the
orchestrator; the separate art run supplies resources. No application install, bank access, art editing or git mutation.

1. Add pure scenery tests, then implement five base weathers, clock/manual time, mood overlays and lighting in
   `Theme/Scenery.swift`. Preserve the worm's state and response matrix. Text twins share the resolved scenery.
2. Add injected weather-reader tests, then implement a visible-room-only, memory-only reader and bounded transport in
   `Theme/LocalWeatherReader.swift`: fixed HTTPS endpoint, four seconds, 64 KiB, no cookies/auth/redirects, thirty minutes
   between attempts including failures. Reuse `SceneStore.phase`, with its existing boundary/wake/time-zone checks.
3. Integrate `DeskScene`, `StudyRoom`, `BookwormArt` and `BookwormView`: skyfx between pane/window, lighting-selected
   props and worm sheets. Room appearance layers crossfade using `SleepMotion.weather` (instant under Reduce Motion).
   The worm is a separate sibling, fading only on its lighting set; an active transition/beat suppresses that fade,
   including error → sleeping's simultaneous rainy/dark → sunny/day change. Its response starts fully visible.
   The contract's wall-clock amendment adds a separate visible-only one-second leaf, tested civil-time hand indices,
   dark dial/hands and no second hand under Reduce Motion. Its state frames never use the sprite loop schedule.
4. Add scenery rows to Settings → Sleep using `SettingsRow`, `SettingsGroupCard`, per-viewer `AppStorage`, sheet key
   frames, labelled keyboard controls and a live inert preview. Index each row for Settings search.
5. Fix black-X/drop and slice contracts. Verify fly frame 0 against top-left sprite/bottom-left room coordinates.
   Add full acceptance tests for night sheets, weather/skyfx/clock tags, plan, motion and 36-pair manifest; missing art stays red.
6. Review correctness and privacy/accessibility/docs in the main thread. Update ruling 18, G176/G107/G125/G127,
   app/network architecture, the one-line network rail and the design log.

Validation: `cd app/CicadaApp && swift test --filter SceneryTests` first; targeted model/reader/art tests while building;
then `cd app/CicadaApp && swift test` twice, capturing counts and every failing name. Finally
`PYTHONDONTWRITEBYTECODE=1 <main-checkout>/api/.venv/bin/python -m pytest api/tests/test_claude_md_size.py -q -p no:cacheprovider`.

Rulings: no flash; dark iff night or rainy; lamp means schedule; overlays mean running/finished in every source;
fallback names How Sleep is doing; changing scenery never starts work. Art verification is separate from the owner's
visual acceptance. Count props, the queue as a room, G175 marks and Q1 remain open.
