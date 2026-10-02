# The study room's scenery: real time, real weather, a dark room (G176, 2026-10-02)

Owner decisions of 2026-10-02 that amend the 2026-10-01 sprite spec
([`2026-10-01-bookworm-sprites-spec.md`](2026-10-01-bookworm-sprites-spec.md)) and TODO ruling 18. Where they differ,
this file wins. It is the shared contract for the art run and the app run that build it in parallel.

## The owner's words

> "Only thing i notice is that the room when at night should be dark but it isn't. Shouldn't it be a dark color and just
> have the glow of the lamp?"
>
> "thing is i want the worm to be able to sleep at night and at day, and do all the emotions and stuff, but at night and
> in storm and does dark environments, the room should be dark, no?"
>
> Asked what decides day or night: "real clock and if we can also read weather somehow we can make it influence the
> state, and this can be turned off in settings and set the env manually. Show little pics of the available settings like
> you did in the html but in settings for selecting the scenary."
>
> Which environments make the room dark: **night and rainy**. What the two state skies become: **a calm mist while a cycle
> runs, a rainbow when one just finished (a shooting star at night)**.

## The model

Three independent things, each a pure function of its inputs:

1. **The worm** shows Sleep's state (`BookwormState`, its matrix, its beats), at any hour, in any weather. Unchanged.
2. **The time of day** is `SceneClock`'s `day · dusk · night` (`Theme/SceneClock.swift`: the Mac's time zone and solar
   position; no location permission, no network) — or the person's manual choice.
3. **The weather** has a source the person picks in Settings (the *scenery* setting):
   - **Local weather** (default): the current conditions for the time zone's principal city (the coordinates
     `TimeZoneCoordinates` already holds; never the person's location), mapped to a base weather. If the forecast cannot
     be read (offline, refused, not yet fetched), the room falls back to *How Sleep is doing*, and says so.
   - **How Sleep is doing**: today's state mapping (below), time still by the clock.
   - **Choose**: a fixed time and base weather the person picks from thumbnails; the clock and the forecast are ignored.

**Two Sleep moments are layers over any weather, in every mode:** while a cycle runs, a **calm mist** drifts across the
window; when a cycle just finished (`digesting`), a **rainbow** by day or dusk, a **shooting star** by night. They are state
art (a total function of the mood); the base weather under them is environment art.

**The room is dark when the time is night or the base weather is rainy** — in any mode. A dark room is lit only by the
lamp (when lit; the lamp still means "Sleep is scheduled") and faintly by the window. Otherwise the room is in day light
(dusk keeps the day-lit room; only the sky changes).

### Base weathers and the state mapping

| Base weather | Local weather (Open-Meteo `weather_code`, `wind_speed_10m`) | How Sleep is doing (mood → base) |
|---|---|---|
| `sunny` | codes 0–1 | `happy` (caught up), and the base under the mist (`sleeping`) and the rainbow (`digesting`) |
| `cloudy` | codes 2–3, 45/48 (fog), snow codes until snow is drawn | `reading`, `curious` (things are waiting) |
| `windy` | wind ≥ 30 km/h with no precipitation (overrides `sunny`/`cloudy`) | `hungry` (overdue) |
| `rainy` | drizzle, rain, showers, thunderstorm (51–67, 80–82, 95–99); never a lightning flash | `error` (the last cycle failed) |
| `curtains` | — (manual only) | `awake` (waiting to hear how Sleep is doing) |

Overlays: `mist` while `sleeping`; `rainbow` (day, dusk) / `shootingstar` (night) while `digesting`. In *Local weather*
and *Choose*, the window no longer encodes overdue/failed/waiting — the worm and the sentence already do; the overlays
still encode running/finished.

## The art contract (sheet and tag names)

All sheets 1 px = one room cell, palette-locked, binary alpha, per-frame durations in the JSON, built headless by
`tools/export_all.sh` from saved parts. Names are fixed; both runs code against them.

| Sheet | Canvas | Tags |
|---|---|---|
| `room-weather` | 36 × 32 | `<base>-<time>` for base ∈ {`sunny`, `cloudy`, `windy`, `rainy`, `curtains`} × time ∈ {`day`, `dusk`, `night`}: **15 tags**, each a seamless loop (night: moon and twinkling stars where the sky is clear; rainy-night: dark rain, no flash; curtains: the light behind them follows the time). Replaces the old seven tags. |
| `room-skyfx` | 36 × 32, transparent | `mist-day`, `mist-dusk`, `mist-night`, `rainbow-day`, `rainbow-dusk`, `shootingstar-night`: **6 tags**, drawn over the pane and under the window frame, never hiding the base weather's key shapes entirely. |
| `room-backdrop`, `room-lamp` | as today | `dark`, `lit` (day-lit room, lamp off/on) + `night-dark`, `night-lit` (dark room, lamp off/on) |
| `room-window`, `room-plant`, `room-beanbag`, `room-mug` | as today | `idle` (day-lit) + `night-dark`, `night-lit` |
| `room-fly` | as today | `buzz` (only while the lamp is lit, either lighting) |
| `room-spines` | as today | unchanged (the real pile is UI, not room light) |
| `bookworm-<state>` (8 room states) | 64 × 48 | unchanged (day-lit) |
| `bookworm-<state>-night-dark`, `bookworm-<state>-night-lit` (8 states × 2) | 64 × 48 | exactly the day sheet's tags, frame counts and per-frame durations, relit for the dark room as the worm sits on the bean bag (lamp side warmer when lit); state marks (closed eyes, z's, X eyes, the drop, the `?`, the book) stay legible |
| `bookworm-small` | 18 × 18 | unchanged (the menu bar has no room light) |

`room-plan.json` gains the `skyfx` layer between `pane` and `window`. `room-motion.json` covers all 15 weather tags and
the 6 sky-fx tags. The manifest covers every sheet: **35 sheet pairs** (8 day worm + 16 night worm + the small worm + 10
room sheets). Tests derive the expected set from this table, never from a typed count.

## The app contract

- `WindowWeather` becomes the base weather (`sunny`, `cloudy`, `windy`, `rainy`, `curtains`) plus the time (`SkyPhase`)
  and an optional overlay (`mist`, `rainbow`/`shootingstar`), each a pure function: `scenery(mode, clock phase, forecast,
  mood, manual choice) -> (base, time, overlay, source)`. Room lighting: `dark` iff `time == .night || base == .rainy`.
- The room picks `night-*` tags and `bookworm-<state>-night-*` sheets when dark (lamp lit/unlit), else today's. The swap
  crossfades with the pane (the existing R-Z12 crossfade, instant under Reduce Motion); no new timer.
- **Settings → the scenery** (the in-app Settings panel; D's list grammar): the source picker (Local weather · How Sleep is
  doing · Choose), a one-line disclosure of what *Local weather* sends ("your time zone's city, every half hour while the
  study room is open; nothing else leaves your Mac"), and **thumbnails** drawn from the sheets' key frames — the time
  (day · dusk · night) and the base weathers — selectable under *Choose*, with a small live room preview of the current
  selection. Every tile has a text label and a VoiceOver label.
- **Local weather fetch**: the app, not the backend; one host (the forecast service), HTTPS, 4 s timeout, ≤ 64 KB, no
  cookies, no identifiers; at most once per 30 min and only while the room is on screen; cached in memory; offline-safe
  (falls back to *How Sleep is doing*). Off when the person picks another source. Documented in
  `docs/architecture/network.md` as its own gate, with a one-line rail edit in `CLAUDE.md`.
- **Text twins**: the window's legend and `.help` name the time, the base weather and its source ("Night · Rainy · local
  weather"), and the overlay's meaning ("A cycle is running." / "A cycle just finished."); under *How Sleep is doing* the
  base weather keeps its old meanings. VoiceOver reads the same.
- **No click on art starts work**; the scenery setting changes only what the room shows.

## Rulings this amends (dated 2026-10-02, the owner)

- **R-Z11** ("the window's sky is a total function of the mood, never the clock or a count") becomes: the time of day
  follows the clock (or the person's choice); the base weather follows the source the person picked; the mist and the
  rainbow/shooting star still follow the mood. *Refused* stays for a lightning flash.
- **R-A13 / ruling 18**: the room's lighting is a pure function of (time, base weather, lamp).
- **The network rails**: one new, documented, opt-out app-side read of public weather for a public city's coordinates.
