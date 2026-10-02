# Run B room tag timings

All indices below are play-order steps. Weather and fly tags play forward and loop. Props are static. Spine frames are masks, selected by role; they are never played as animation.

| Sheet / tag | Canvas | Frames | Each frame in ms | Total ms | Action |
|---|---|---:|---|---:|---|
| `room-backdrop/dark` | 110 × 64 | 1 | 1 × 1000 | 1000 | Static textured wall, planks, baseboard bevel, rug, cord and right trim |
| `room-backdrop/lit` | 110 × 64 | 1 | 1 × 1000 | 1000 | Same room with three warm palette bands and a small floor pool |
| `room-beanbag/idle` | 62 × 12 | 1 | 1 × 1000 | 1000 | Static dented bean bag with folded lobes and seat row 2 |
| `room-fly/buzz` | 20 × 26 | 40 | 1200, 80, 60, 60, 90, 90, 80, 60, 60, 60, 80, 90, 60, 60, 70, 90, 80, 60, 60, 70, 90, 80, 60, 60, 70, 90, 80, 60, 70, 90, 600, 70, 70, 70, 70, 70, 70, 70, 70, 120 | 4590 | Top landing, two uneven darts/loops, right-rim landing, return behind the shade and top landing; optional one-pixel wing glint |
| `room-lamp/dark` | 18 × 50 | 1 | 1 × 1000 | 1000 | Unlit shade, pole and broad foot |
| `room-lamp/lit` | 18 × 50 | 1 | 1 × 1000 | 1000 | Warm underside and rim, with the same silhouette |
| `room-mug/idle` | 8 × 9 | 1 | 1 × 1000 | 1000 | Static cup, handle, dark coffee and left highlight; no steam |
| `room-plant/idle` | 12 × 22 | 1 | 1 × 1000 | 1000 | Static three-branch foliage and terracotta pot; no invented sway |
| `room-spines/chat` | 24 × 12 | 3 | 3 × 1000 | 3000 | chat kind: body, light, shade masks in that order |
| `room-spines/page` | 24 × 12 | 3 | 3 × 1000 | 3000 | page kind: body, light, shade masks in that order |
| `room-spines/note` | 24 × 12 | 3 | 3 × 1000 | 3000 | note kind: body, light, shade masks in that order |
| `room-spines/video` | 24 × 12 | 3 | 3 × 1000 | 3000 | video kind: body, light, shade masks in that order |
| `room-spines/other` | 24 × 12 | 3 | 3 × 1000 | 3000 | other kind: body, light, shade masks in that order |
| `room-weather/night` | 36 × 32 | 24 | 24 × 200 | 4800 | Static crescent; nine staggered stars alternate cross, point and dim phases |
| `room-weather/dawn` | 36 × 32 | 36 | 36 × 300 | 10800 | Three sunrise bands and half sun; two thin clouds drift; paired rays change every three frames |
| `room-weather/clear` | 36 × 32 | 36 | 36 × 500 | 18000 | Full sun with alternating rays; two round clouds drift; distant trees |
| `room-weather/fair` | 36 × 32 | 72 | 72 × 200 | 14400 | Partly hidden sun; near cloud moves every frame, far clouds every second frame |
| `room-weather/overcast` | 36 × 32 | 36 | 36 × 120 | 4320 | Grey cloud streaks drift; foreground tree leans left/right with lag; three leaves blow across the pane |
| `room-weather/storm` | 36 × 32 | 48 | 48 × 80 | 3840 | 32 diagonal streaks follow -1/-1/-1/0 horizontal cadence and +4 vertical cadence; four glass drops form, lengthen and slide; no flash |
| `room-weather/curtains` | 36 × 32 | 8 | 600, 300, 600, 300, 600, 300, 600, 300 | 3600 | Still folds and narrow light leak; slightly breathing lower hems |
| `room-window/idle` | 40 × 38 | 1 | 1 × 1000 | 1000 | Static wood frame, crossbars and upper-left sill highlight |

Fly details: frame 1 holds on the top for 1,200 ms; frame 31 holds on the right rim for 600 ms. Frames 33–39 contain zero ink while the route passes behind the opaque shade. The other frames contain one body pixel or a body pixel plus one wing glint. The complete 40-frame loop is 4,590 ms.

The final frame and the first frame share the same landed pixel. Motion timing stays unchanged by counts, stages or time of day. Reduce Motion selects the first frame, and Low Power doubles all timings.
