# Art direction: Cicada's painted meadow

This document is the design identity for every painted asset in
`app/CicadaApp/Sources/CicadaApp/Resources/art/`. It tells an artist what to paint and an
engineer what to accept, bundle and test. It sits under [`DESIGN_RULES.md`](DESIGN_RULES.md).
**DR-13** limits where painting may appear: EmptyStateView, Welcome and onboarding, the Home band,
and the reward moments those surfaces carry. It never sits behind data. **DR-14** keeps Liquid Glass
out of it. Text never sits directly on paint (§10). This document does not relax any of those rules.

The owner's brief (2026-09-24):

> Pastel paintings, similar to Monet's but a tad bit leaning to more realistic. Generate the highest
> resolution possible. The Home painting follows the person's clock with four scenes (Automatic ·
> Day · Afternoon · Night), and switching between options is smooth.

**Why a new set.** The shipped `hero-day` has its meadow line at about 86 % of its height. Its
`-dark` sibling puts the hills at about 75 %, with different clouds and grass, so a crossfade
between them jumps. Its brushwork also drifts toward a glossy, anime-like finish. The new set fixes
both problems. It has **one composition in three lights**, painted in one hand.

---

## 1. The style in words

**Pastel impressionist painting in the spirit of Monet's meadows, a touch more realistic.**

- **Brushwork.** The strokes are soft, broken and visible. Colour is laid side by side instead of
  blended smooth. Grass is suggested by directional strokes, not drawn blade by blade. Up close you
  see paint. From a step back you see a real meadow.
- **Light.** The light is luminous and pastel. Shadows are coloured (lavender, blue-green, lilac)
  and never grey or black. The whole picture sits in the upper-middle values. Pure white is saved
  for a few highlights at most, and there is no black.
- **Forms.** Forms and perspective are believable: a real horizon, atmospheric haze on the
  distance, grass that gets smaller and bluer as it recedes, and dandelions at a plausible scale.
  This is the "more realistic than Monet" part. Forms hold together, but edges stay soft.
- **Edges.** There are no hard outlines anywhere. Edges are lost and found. A cloud's edge
  dissolves into sky, and a blade's tip dissolves into air.
- **Focus.** Depth of field is painterly. The foreground corners are the most resolved, and the
  distance melts into broad strokes.
- **Mood.** Calm, spacious and quietly optimistic. Nothing dramatic happens, and no weather event
  occurs.
- **Never:**
  - photo-realism, HDR glow, lens flare, chromatic aberration or bokeh discs;
  - cartoon, anime, cel shading, a "concept-art" gloss or a 3D render;
  - vector flatness;
  - text, logos, a watermark or a signature;
  - people, animals, buildings, fences, paths, trees in the foreground, or any human trace.
- **Artist references.** Monet's poppy fields and meadows (for example *Poppy Field near
  Argenteuil*, 1873), Sisley and Pissarro. **A prompt may name only artists whose work is in the
  public domain.** It never names a living artist, a film studio or a game.

**Calm beside graphite.** The paintings sit next to D's graphite UI (`bgBase` `#111213` dark and
`#F7F7F5` light), so they are held to three rules:

1. **Chroma.** No region larger than 5 % of the frame exceeds OKLCH chroma 0.14. Dandelion yellow
   is the only saturated note, and it stays in the corners.
2. **Day.** No pixel is brighter than `#FBF8EF`, so a light window never glares.
3. **Night.** Mean OKLCH lightness is between 0.20 and 0.30. The painting reads as night without
   looking like a hole beside `#111213`, and the moon is its only near-white.

---

## 2. Palette per time of day

Each swatch is a target that artists and colour checks match by eye. It is not a token, and none
of these colours enters `CicadaTheme` (DR-13).

### Day: late morning, sun high at the upper left

| Role | Hex | Note |
|---|---|---|
| Sky, zenith | `#8DB8DE` | soft cornflower, more pastel than the shipped hero's `#4A9BE0` |
| Sky, middle | `#A9CBE6` | |
| Sky, at the horizon | `#DCE9EF` | pale haze |
| Cloud, lit | `#FBF7EC` | cream white, never `#FFFFFF` |
| Cloud, shadow | `#B9BFD9` | lavender-blue grey |
| Sunlight | `#F6EBC8` | cream, on cloud tops and grass tips |
| Distant hills | `#A9BFB0` | atmospheric blue-green |
| Grass, lit | `#A8C77A` | fresh green |
| Grass, middle | `#7FA65E` | |
| Grass, shadow | `#4F7349` | the darkest value in the day painting |
| Dandelion | `#F2D25C` | soft yellow, never lemon |
| Dandelion clock | `#F4F1E6` | |
| Seed (motion layer) | `#FFFDF6` at 70 % | |

### Afternoon: golden hour, honey light low from the left

| Role | Hex | Note |
|---|---|---|
| Sky, high | `#B7C3DE` | lilac blue |
| Sky, low | `#F3C9A6` | apricot |
| Glow at the horizon | `#F8DDB0` | honey |
| Sun | `#FBE7B5` | soft disc, never a starburst |
| Cloud, lit (left flanks and undersides) | `#F6C9A8` | peach |
| Cloud, shadow | `#A99BC0` | lilac |
| Distant hills | `#B6A7BE` | lilac haze |
| Grass, backlit | `#C9B870` | honey green, strongest on the left |
| Grass, middle | `#8E9A5A` | |
| Grass, shadow | `#5F6577` | lilac-tinted, long shadows falling to the right |
| Dandelion | `#F3C45E` | honey |
| Dandelion clock | `#F7E6CF` | with a warm rim |
| Seed (motion layer) | `#FBE3B8` at 70 % | seeds glint honey |

### Night: moon at the upper right

| Role | Hex | Note |
|---|---|---|
| Sky, zenith | `#16233A` | |
| Sky, middle | `#1F3348` | |
| Sky, at the horizon | `#2E4A55` | blue-green |
| Moon | `#EEF0F6` | the painting's only near-white |
| Moon halo | `#B8BEDC` | lavender silver, soft and wide |
| Cloud body | `#3A4863` | |
| Cloud rim (moon side) | `#9FA7C6` | |
| Hills | `#2A3C4B` | |
| Ground mist | `#4A6070` | thin, in the valley only |
| Grass, moonlit | `#6F8C86` | silver green |
| Grass, middle | `#2D4640` | |
| Grass, shadow | `#16262A` | darkest value; still not black |
| Dandelion clock | `#D9DDE8` | glows pale |
| Dandelion head | `#8C8A5E` | closed or dim at night |
| Firefly core (motion layer) | `#F4D98B` | glow `#E9B75E` at 30 %, sparse and warm |
| Star (motion layer) | `#E6EAF5` | small, sparse |

---

## 3. The master composition

There is **one** meadow. Every hero scene (day, afternoon and night) is this picture in a different
light. Coordinates are fractions of the frame: `x` runs left to right, `y` runs top to bottom, and
the frame is 16:10.

```
 x: 0        0.36              0.64         1
y 0 ┌─────────┬──────────────────┬───────────┐   day sun ↖ (0.02, 0.02), off-frame glow
    │ C1 big  │                  │     moon ●│   night moon (0.86, 0.10)
    │ cloud   │   CALM SKY       │           │
    │         │   gradient only  │  C2 big   │
0.42│grass tip│                  │  cloud    │   left grass reaches y 0.42 at x = 0
0.50│ ▲▲      │── Home band top at 1400 pt ──│
    │ ▲▲▲  c3 │                  │  c4   ▲▲  │   small low clouds just above the hills
0.62│▲▲▲▲ ~~~hills~~~~~~~~~~~~~~~~~~~~ ▲▲▲▲  │   afternoon sun (0.10, 0.52), behind the left grass
0.66│▲▲▲▲▲ ═══════ HORIZON / meadow line ════│
0.74│▲▲▲▲▲▲──── Home band bottom ─────▲▲▲▲▲▲ │
    │▲▲▲▲▲▲▲  ┌──────────────────┐  ▲▲▲▲▲▲▲ │
    │▲▲✿▲▲▲▲  │ WELCOME CARD     │ ▲▲▲✿▲▲▲▲ │   ✿ dandelions only in the corners
0.92│▲▲▲▲▲▲▲  └──────────────────┘ ▲▲▲▲▲▲▲▲ │
  1 └──────────────────────────────────────────┘
```

| Element | Where | Rule |
|---|---|---|
| **Horizon, the meadow line** | `y = 0.660 ± 0.005` across the valley, x 0.35–0.65 | the same row in all three scenes; the Home band anchors to it |
| Distant hills | tops at y 0.60–0.64, lowest in the valley at x 0.45–0.55 | soft and hazy; no trees stand out |
| Corner grass, left | top edge y ≈ 0.42 at x = 0, descending to meet the meadow near x 0.32 | the tallest, most resolved grass in the picture |
| Corner grass, right | top edge y ≈ 0.46 at x = 1, meeting the meadow near x 0.70 | a little lower than the left, so the frame is not symmetrical |
| Dandelions | x 0–0.25 and 0.75–1, y 0.55–0.95; the nearest head is at most 5 % of the width | yellow heads and white clocks mixed, 5–9 on each side; none in the centre |
| Low meadow | x 0.33–0.67, y 0.66–1.0 | low, soft, lightly blurred; no tall stems and no heads |
| Cloud C1 | x 0–0.38, y 0.02–0.45 | the big billowing anchor |
| Cloud C2 | x 0.62–1.0, y 0.20–0.52 | the second anchor |
| Clouds c3 and c4 | small, x 0.18–0.34 and 0.64–0.80, y 0.55–0.62 | just above the hills; they give scale |
| **Calm sky** | x 0.36–0.64, y 0–0.50 | gradient and faint stroke texture only: no cloud, sun, moon, seed or star baked in |
| Light source | day: glow off-frame at (0.02, 0.02); afternoon: sun disc at (0.10, 0.52), partly behind the left grass, which it backlights; night: moon at (0.86, 0.10), halo radius 0.06 of the width | a light source changes between scenes and a form never does |

**What may change between scenes:** colour, light direction, shadows, cast light, the sun or moon,
and the colour of the clouds. Dandelion heads may close at night, but only inside their day
bounding box. **What must not change:** the silhouette of the grass masses, hills, horizon and
anchor clouds, and where each dandelion stands.

**The crossfade test.** Every set (hero, each pane framing, each cloud) must pass it before it is
accepted:

1. Blend day with afternoon, and afternoon with night, at 50 %. No large form (grass mass, hill
   line, horizon or anchor cloud) shows a doubled contour. Fine blade detail may differ, because
   a crossfade of about a second hides it.
2. Automated check. Downscale each scene to 720 px wide, equalise each scene's luminance histogram,
   take Sobel edges and keep the strongest 20 %. At least 85 % of day's strong edges must fall
   within 3 px of the other scene's edges, measured after a 3 px dilation.
3. The horizon row, measured on each scene, is within ±0.005 of 0.660.

### Safe areas

**Welcome, full-bleed.** The painting fills a 1440 × 900 pt window with aspect-fill and is
centred.

- The card's zone is x 0.33–0.67, y 0.64–0.92, about 490 × 250 pt. It has the low meadow behind
  it, with no dandelion head, no tall stem and no bright highlight. The card is its own surface,
  so text never sits on paint.
- The calm sky above it (x 0.36–0.64, y 0–0.50) stays empty. Motion (drifting clouds, seeds and
  stars) may cross it.

**Home band.** The band is 208 pt tall and as wide as the window, up to about 1400 pt. It is cut
from the hero like this:

- The hero is scaled to the window's width. At 1400 pt wide the hero is 875 pt tall.
- The band is positioned so that **the horizon sits at two thirds of the band's height.** At
  1400 pt that is the slice y 0.50–0.74. At 1000 pt it is y 0.44–0.77. At 1920 pt it is
  y 0.55–0.72.
- **The Home safe strip is y 0.42–0.78.** It must read as a complete landscape on its own: the
  anchor clouds' undersides, c3 and c4, the hills, the meadow line and the corner grass tops with
  their dandelions.
- Nothing essential lives only above y 0.42. The sun glow and the moon fall outside the band, and
  that is intended, because the band is about the ground.
- **Note for the Home track.** The 2026-09-24 ruling fades the 120 pt band into `bgBase` from
  40 % down. On the 208 pt band that fade would dim the meadow line, which sits at 67 %. The fade
  should start at 72 % or lower. That change is a DESIGN_RULES §9 amendment, not a decision this
  document can make.

---

## 4. The five split-pane framings

In the split canvas the painting fills the left 45 % of the window, **648 × 900 pt**, shipped as
**1296 × 1800 px** (aspect 0.72). Every framing is the **same meadow** as the master, in the same
style and palette, painted from a different place. Each framing ships in all three scenes and must
pass the crossfade test.

- The pane is drawn with aspect-fill around its focal point. The keep-box must survive any crop
  down to aspect 0.60 or up to 0.90.
- The right 8 % of the pane meets the page, so it carries no focal element.

| Framing (file id) | Page | What you see | Horizon | Focal point (x, y) | Keep-box |
|---|---|---|---|---|---|
| `import` | Import | **Close grass.** Eye level at grass height. Blades and three or four dandelions fill the lower 60 %, with the nearest stems in soft focus. Sky shows above the tips, and the horizon hides behind the blades. | y 0.40, mostly hidden | (0.42, 0.62) | x 0.15–0.80, y 0.30–0.95 |
| `agents` | Agents | **Open sky.** The camera tilts up. A thin meadow line with grass tips runs along the bottom, and the tall sky holds two large clouds, one high-left and one mid-right. The middle band is open for drifting clouds. | y 0.88 | (0.45, 0.40) | x 0.10–0.85, y 0.10–0.95 |
| `who-reads` | Who reads | **Dandelion heads.** Near macro, but still a painting. Three to five clocks and one or two yellow heads stand at mid-height (y 0.35–0.70), with the meadow and sky behind them in broad soft strokes. | y 0.72, soft | (0.45, 0.50) | x 0.15–0.80, y 0.25–0.80 |
| `keep-running` | Keep it running | **The moon over the meadow.** The moon sits at (0.58, 0.20) in every scene. **Day:** a pale daytime moon in blue sky. **Afternoon:** the moon rising pale over an apricot afterglow. **Night:** full moonlight, silvered grass and thin mist in the valley. | y 0.62 | (0.55, 0.35) | x 0.20–0.85, y 0.10–0.75 |
| `ready` | Ready | **Wide pull-back.** The master meadow seen from further back and a little higher: the grass bowl small at the bottom, the hills in full, a big sky. It bookends Welcome. | y 0.55 | (0.45, 0.55) | x 0.10–0.85, y 0.20–0.90 |

The panes carry **no sway layers**. Their motion is drifting clouds, where there is sky, and the
particles described in §5.

---

## 5. Animation layers

Motion is layered over the paintings. Each layer is a cut-out that must be indistinguishable from
the painting it sits on when at rest.

**Stacking order, back to front:** the plate (the hero or a pane), then stars (night only), then
drifting clouds, then the grass corners (hero only), then particles (seeds by day, fireflies by
night), then the UI.

### Clouds: three shapes, each in three scenes

| Shape | Silhouette | Canvas |
|---|---|---|
| `cloud-1` | tall, billowing cumulus | 1200 × 600 px (drawn ≤ 600 × 300 pt) |
| `cloud-2` | long, low, flat-bottomed cumulus | 1200 × 600 px |
| `cloud-3` | a small pair of puffs | 1200 × 600 px |

- **One alpha, three colourings.** The day cloud is painted first. The afternoon and night clouds
  are relit from it, and **the day file's alpha channel is applied to all three**, so a cloud
  crossfading mid-drift never changes shape.
- **The light matches the scene.**
  - Day: cream tops lit from the upper left, with lavender-blue undersides.
  - Afternoon: lit low from the left. The left flank and undersides are peach and apricot, and the
    top and right side are lilac.
  - Night: silver rims on the upper-right (moon) edge and a slate-blue body. The app draws night
    clouds at 40 % opacity (`MeadowRules`), so the rim must still read at that opacity.
- The cloud is centred on its canvas with margin on every side and is never cropped. All four
  corners are transparent (`testSpritesAreCutOutNotPlates`).
- Clouds drift only through the sky band at y 0.08–0.42 of the hero, above the hills. They may
  pass over the anchor clouds.

### Grass corners: `grass-left`, `grass-right` (hero only)

- **Cut them out of the painting; don't paint them separately.** For each scene, cut the front
  clump from that scene's hero corner. Use **one mask for all three scenes**. The scenes register,
  so their layers register too.
- The cut leaves a hole, so the shipped hero is a **plate.** Behind each clump, the plate carries
  a *back row*: shorter, slightly darker and bluer grass, inpainted in the scene's palette. When a
  clump sways, the back row is what shows, never a ghost of the clump.
- **At rest, the plate plus both layers must match the approved painting** to within a mean
  CIEDE2000 difference of 1.5.
- **Size and anchor.** Each layer is 1200 × 900 px (600 × 450 pt at the 1440 pt Welcome width),
  anchored to its bottom corner. At 1440 pt the layer and the hero share a pixel grid.
- **Pivot.** Sway rotates the layer about its bottom edge by at most 1.5°. The bottom edge is the
  roots: its bottom rows are opaque across the full width, and no blade crosses the bottom edge at
  an angle. The top and inner edges are fully transparent. The back row must cover everything a
  1.8° swing would reveal, which is the 1.5° maximum plus a 20 % margin.
- **Edges.** Decontaminate the edge colour toward the scene's grass, so no light halo shows
  against the plate. This matters most at night.
- **Fallback.** Generate isolated grass on transparency with the hero as the reference image,
  then histogram-match it to the hero's corner region. Use this only if a cut fails, and say so in
  `processing`.

### Grass edge: `grass-edge` (a tileable strip)

- The strip is **2400 × 240 px** (1200 × 120 pt) and repeats left to right, for the bottom of
  empty states and similar surfaces.
- **Tiling.** The 64 px columns at each end continue into each other. Check it by rolling the
  strip half its width and looking for a seam.
- The top is transparent and the bottom 40 px are opaque.
- At most two yellow heads per tile, and no clock within 200 px of either end, so a repeat is not
  noticed.
- The strip is painted in the same hand and palette as the hero's foreground grass. Its
  afternoon and night versions are relit from the day strip, keeping the same alpha.

### Particles: drawn by the app, never painted

The paintings carry **no drifting seeds, fireflies or stars.** Dandelion clocks stay attached to
their stems. Particles are drawn by the app and follow these rules:

- **Seeds** (day and afternoon) rise only from the corner dandelion clusters, in the §2 seed
  colour. They are soft discs with a tuft and no hard edge.
- **Fireflies** (night) number 12 or fewer on screen. They stay at grass height (y > 0.55) in the
  corners and never enter the Welcome card's zone.
- **Stars** (night) number 40 or fewer. They appear only above y 0.58, never inside the moon's
  halo radius × 2 and never over a cloud. Under Reduce Motion they are drawn still, so a still
  night still has stars.

---

## 6. Technical spec

### Sizes, formats and names

Everything is authored at 2× the point size it is drawn at (`MeadowArt.pixelsPerPoint`).

| Role | File name | Pixels | Format | Files |
|---|---|---|---|---|
| `hero` | `hero-day.jpg`, `hero-afternoon.jpg`, `hero-night.jpg` | 2880 × 1800 | JPEG | 3 |
| `pane` | `pane-<framing>-<scene>.jpg`, with framing `import`, `agents`, `who-reads`, `keep-running` or `ready` | 1296 × 1800 | JPEG | 15 |
| `cloud` | `cloud-<1\|2\|3>-<scene>.png` | 1200 × 600 | PNG RGBA | 9 |
| `grass-corner` | `grass-left-<scene>.png`, `grass-right-<scene>.png` | 1200 × 900 | PNG RGBA | 6 |
| `grass-edge` | `grass-edge-<scene>.png` | 2400 × 240 | PNG RGBA | 3 |

- `<scene>` is `day`, `afternoon` or `night`. The Home band has no file of its own; it is cut from
  `hero-<scene>` at runtime, as in §3.
- **The `-dark` suffix retires.** The shipped 14 files leave with this set.
- A surface with no scene setting uses `day` under the light theme and `night` under the dark
  theme. Where Automatic follows the clock, the app decides that.

**Opaque paintings are JPEG q86**: progressive, 4:4:4 chroma (4:2:0 bleeds the yellow heads into
the grass), sRGB with the ICC profile embedded and all other metadata stripped. Use PNG only if it
comes out smaller, which painterly work almost never does.

- **Never palette-quantise an opaque painting.** The shipped hero did, and pastel skies are exactly
  where 256 colours band.
- If a contrast-stretched sky crop shows banding, add blue-noise dither of at most 1 LSB before
  encoding.

**Layers are PNG RGBA.**

- Resize with premultiplied Lanczos. Then run oxipng at level 4.
- pngquant (at most 256 colours with alpha, quality 80–95) is allowed on layers only, and
  `processing` must then say "quantized". `testAFileRecordedAsLanczosResizedWasNotNearestNeighbour`
  depends on that word.

### Getting the highest resolution

1. **Generate** at the generator's largest native size, and record the size in `processing`.
   - Landscape is 3:2 (for example 1536 × 1024), cropped to 16:10.
   - Portrait is 2:3, cropped to 0.72.
   - Frame the prompt so that the crop loses only margin.
   - Make at least 4 candidates and record the pick as "k of N".
2. **Upscale** to a master at twice the shipped size (hero 5760 × 3600, pane 2592 × 3600).
   - Use at most two passes of at most 2× each, with an upscaler that keeps brushwork.
   - Never use a "face", "photo" or "enhance" mode, which adds photographic texture.
   - Record the tool, the model and each factor.
3. **Relight** afternoon and night as image edits, with the day master as the reference image (the
   §7 relight prompts).
   - Never make night by darkening day.
   - Make at least 4 candidates per scene and keep the one that registers best.
   - A residual drift may be corrected with a small affine or thin-plate warp. Record it. If it
     still fails the crossfade test, regenerate.
4. **Cut** the grass layers and paint the plate's back row (§5).
5. **Downsample** the master to the shipped size with Lanczos and encode as above.
6. **Archive masters outside the repo**, as a release asset or in the owner's archive, named
   `<id>-master.png`. The manifest keeps each master's sha256, so anyone can confirm that a
   re-export came from it.

### Byte budget

| Role | Cap per file | Expected per file | Count | Expected total |
|---|---|---|---|---|
| hero | 1.4 MB | ~0.9 MB | 3 | ~2.7 MB |
| pane | 800 KB | ~500 KB | 15 | ~7.5 MB |
| cloud | 400 KB | ~250 KB | 9 | ~2.3 MB |
| grass-corner | 900 KB | ~550 KB | 6 | ~3.3 MB |
| grass-edge | 500 KB | ~300 KB | 3 | ~0.9 MB |
| **all 36 files** | | | | **~16.7 MB** |

- **The total budget is 20 MiB.** `ArtAssetTests.byteBudget` goes from `4 * 1024 * 1024` to
  `20 * 1024 * 1024`, and the per-file caps above become a per-role table in the same test.
- The total is the binding limit, and the per-file caps catch one bad export. About 17 MB of art
  in a native app bundle is the price of the resolution the owner asked for.
- **If the set goes over the budget,** concede in this order: first quantise the PNG layers, then
  drop the panes to q82. The heroes are never lowered.

### Test changes that come with the set

These are for the implementation track. This document only names them.

- **Roles** become `hero`, `pane`, `cloud`, `grass-corner` and `grass-edge`.
- **`longestSideCap`**: hero 2880, pane 1800, cloud 1200, grass-corner 1200. The grass edge stays
  at ≤ 2400 × 240.
- **`variant`/`pairsWith` becomes `scene` + `set`.** The "dark sibling of the same size" test
  becomes: *every set has day, afternoon and night, all with the same pixel size.*
- A layer set's three files share one alpha channel. Assert that the alpha channels are
  byte-identical.

### Provenance: `art.manifest.json`

Every bundled file has exactly one entry, and `ArtAssetTests` holds each file to its bytes, as it
does today. An entry has these fields:

| Field | Content |
|---|---|
| `id` | the file name without its extension |
| `file` | the file name |
| `role` | `hero`, `pane`, `cloud`, `grass-corner` or `grass-edge` |
| `set` | the composition the file belongs to: `hero`, `pane-import`, `cloud-1`, `grass-left`, … |
| `scene` | `day`, `afternoon` or `night` |
| `framing` | panes only |
| `generator` | the tool and its version, plus the image model if it is disclosed |
| `prompt` | the **exact, full** prompt sent, including the wrapper line |
| `reference` | for a relight or a cut: the sha256 of the day master or plate it was made from |
| `date` | ISO date |
| `licence` | "MIT, as this repository (see LICENSE). Generated for Cicada; no third-party artwork or brand marks." |
| `processing` | every step in order: native size, pick "k of N", upscaler and factors, any warp, the cut mask and back-row inpaint, resize filter, quantisation, encoder and settings |
| `masterSha256` | the sha256 of the archived master |
| `sha256` | the sha256 of the bundled bytes |

Regenerating or re-processing a file means a new entry in the same commit.

---

## 7. Prompt kit

**Assembly.** Build a prompt from these blocks, in this order:

- **A new painting:** WRAPPER + BASE + SCENE(day) + ASSET + NEGATIVE.
- **A relight:** WRAPPER + RELIGHT(scene) + NEGATIVE, sent with the day image attached as the
  reference.

Record the assembled text verbatim in the manifest. WRAPPER is the Codex image tool's line, so drop
it for other generators.

### WRAPPER

```
Use your image generation tool to create ONE image, at the largest size available for this aspect. Save nothing else.
```

### BASE (the style)

```
A pastel impressionist oil painting in the spirit of Claude Monet's meadow paintings, a touch more realistic: soft, broken, visible brushstrokes with colour laid side by side rather than blended smooth; luminous pastel light; believable forms, scale and atmospheric perspective, with the distance hazier, bluer and softer than the foreground; lost-and-found edges and no outlines anywhere; coloured shadows (lavender, blue-green, lilac), never grey or black; values kept light-to-middle, calm and spacious, quietly optimistic. Up close it reads as paint; from a step back it reads as a real meadow.
```

### NEGATIVE

```
Not a photograph, no photo-realism, no HDR, no lens flare, no bokeh discs, no chromatic aberration; not cartoon, not anime, no cel shading, no glossy concept-art finish, not a 3D render, not vector art. No text, letters, logos, watermark or signature. No people, animals, birds, insects, buildings, fences, paths, poles or wires. No pure black and no pure white areas.
```

### SCENE blocks (new paintings are always painted as day first)

**SCENE(day)**

```
Late-morning light from the upper left, just outside the frame. Pastel sky: soft cornflower blue at the top, paler toward a hazy cream-blue horizon. Clouds cream-white where lit with lavender-blue shadowed undersides. Fresh spring greens in the grass, cream sunlight on the blade tips, soft butter-yellow dandelions and white dandelion clocks.
```

### ASSET blocks

**hero (the master, 16:10; generate at 3:2 and crop)**

```
Wide landscape, 16:10, with a little extra sky and foreground margin so it can be cropped. A calm meadow seen from grass height. Lush grass rises in the bottom-left and bottom-right corners in a gentle bowl: at the far left edge the grass reaches about 42 percent down from the top of the picture, at the far right edge about 46 percent down, and both sides slope down to meet the meadow. The bottom centre is a low, soft, slightly blurred meadow with no tall stems and no flowers. The meadow line (the horizon) runs level exactly two thirds of the way down the picture, with soft hazy distant hills just above it, lowest in the middle. Yellow dandelions and white dandelion clocks only in the two corner clumps, five to nine on each side, the nearest no bigger than a twentieth of the picture's width; none in the centre. One big billowing cumulus cloud in the upper left, a second big cloud on the right between one fifth and one half of the way down, and two small clouds just above the hills on either side. The centre-top of the sky, the middle third of the width down to halfway, is completely empty open sky: only a soft gradient and faint brush texture. No sun disc in frame, only its glow in the top-left corner. No drifting seeds, no stars, no fireflies.
```

**pane-import (portrait 0.72; generate at 2:3 and crop)**

```
Tall portrait, 2:3, with a little side margin so it can be cropped narrower. The same calm meadow, painted from inside the grass at blade height. Grass blades and three or four dandelions (two yellow heads, one or two white clocks) fill the lower sixty percent, the nearest stems soft and slightly out of focus, the main cluster just left of centre and a little below the middle. Above the tips, a band of pastel sky with one soft cloud; the horizon is hidden behind the blades about forty percent down. The right tenth of the picture stays quiet: grass and sky only, no flower. No drifting seeds.
```

**pane-agents**

```
Tall portrait, 2:3, with a little side margin so it can be cropped narrower. The same calm meadow, looking up at a tall open sky. A thin level meadow line with soft grass tips runs along the very bottom, about seven eighths of the way down. Two large soft cumulus clouds: one high on the left, one in the middle-right. The middle band of the sky, from one quarter to two thirds of the way down, is open: only a soft gradient and brush texture. The right tenth stays quiet. No sun disc, no birds, no drifting seeds.
```

**pane-who-reads**

```
Tall portrait, 2:3, with a little side margin so it can be cropped narrower. The same calm meadow, close to a few dandelions, still clearly a painting rather than a macro photograph. Three to five white dandelion clocks and one or two yellow dandelion heads on long stems stand between one third and seven tenths of the way down, grouped just left of centre, their seeds all still attached. Behind them the meadow and the sky dissolve into broad, soft pastel strokes, with the horizon softly about seventy percent down. The right tenth stays quiet. No drifting seeds.
```

**pane-keep-running (painted first as day; the moon stays in all three scenes)**

```
Tall portrait, 2:3, with a little side margin so it can be cropped narrower. The same calm meadow at a middle distance, the horizon level about sixty percent down, with soft hazy hills and a gentle valley. A pale daytime moon, a soft round waxing-gibbous disc, hangs in the blue sky a little right of centre, about one fifth of the way down. Grass and a few dandelion clocks in the lower corners, the lower middle a calm open meadow. The right tenth stays quiet. No sun disc, no stars.
```

**pane-ready**

```
Tall portrait, 2:3, with a little side margin so it can be cropped narrower. The same calm meadow seen from further back and a little higher: the grassy bowl with its dandelions is small at the bottom, the soft hills are fully visible, and the level horizon sits a little above the middle, about fifty-five percent down. A big spacious pastel sky with two soft cumulus clouds, one upper left and one middle right. Calm, open, a sense of arrival. The right tenth stays quiet. No drifting seeds.
```

**cloud-1, cloud-2, cloud-3 (sprites, 2:1, transparent)**

Prepend this to the shape line: `A single isolated cloud, centred with generous empty margin on all sides, not cropped. Fully transparent background (PNG with alpha): no sky, no ground, nothing else in the image. Landscape 2:1 canvas.`

- cloud-1: `A tall, billowing, rounded cumulus cloud.`
- cloud-2: `A long, low cumulus cloud with a soft flat underside, about three times as wide as it is tall.`
- cloud-3: `A small pair of soft cumulus puffs, one slightly larger, drifting side by side.`

**grass-edge (a tileable strip)**

```
A long, low horizontal strip of meadow grass, 10:1, seen from blade height, standing on a fully opaque band of grass along the bottom sixth, with blade tips feathering into a fully transparent background above (PNG with alpha): no sky, nothing else. Even density along the whole length with no single standout clump, at most two small yellow dandelions near the middle and none near either end, so the strip can repeat left to right without a visible seam.
```

After generation, make it seamless with an offset-and-inpaint on the seam, and record that in
`processing`.

**grass-left, grass-right (fallback only; the default is the cut in §5)**

```
One clump of lush meadow grass with three to five dandelions (yellow heads and white clocks), rooted along the full width of the bottom edge and rising toward the [left|right] edge, where it is tallest, feathering to fully transparent at the top and at the inner side (PNG with alpha): no sky, no ground plane, nothing else. 4:3 canvas.
```

Attach `hero-day` as a reference and colour-match the result to its corner.

### RELIGHT blocks (image edits of the attached day image)

**RELIGHT(afternoon)**

```
Repaint the attached painting at golden hour. Keep the composition exactly the same: every cloud, hill, the horizon, every grass mass and every dandelion stays in the same place with the same shape and size; nothing is added, removed, moved or re-drawn. Change only the light and colour, in the same brushwork: honey sunlight low from the left, with a soft sun disc low on the left partly seen through the grass (hero only; elsewhere the sun stays out of frame); the sky lilac-blue at the top warming to apricot and honey at the horizon; clouds peach and apricot on their left flanks and undersides, lilac in shadow; grass honey-green and backlit on the left, lilac-tinted shadows falling to the right; dandelions honey-yellow, clocks with a warm rim. Same pastel impressionist style, calm, not saturated.
```

**RELIGHT(night)**

```
Repaint the attached painting as a calm moonlit night. Keep the composition exactly the same: every cloud, hill, the horizon, every grass mass and every dandelion stays in the same place with the same shape and size; nothing is added, removed or moved (yellow dandelion heads may close into dim buds within their own outline). Change only the light and colour, in the same brushwork: a full, soft lavender-silver moon high in the upper right with a wide gentle halo (hero only; on a pane keep its moon where it is, or keep the moon out of frame if there is none); the sky deep blue-green at the top, lighter teal-blue at the horizon; clouds slate-blue with silver rims on their moon side; grass silver-green where moonlit and deep blue-green in shadow, never black; dandelion clocks glowing pale silver; thin mist lying in the valley only. No stars and no fireflies (those are added separately). Luminous, calm night, the moon the only near-white.
```

**Relighting sprites and strips.** For clouds and grass layers, add this sentence to the relight:
`Keep the transparent background and the exact silhouette.` After generation, apply the day file's
alpha channel.

### A fully assembled example: `hero-day`

```
Use your image generation tool to create ONE image, at the largest size available for this aspect. Save nothing else. A pastel impressionist oil painting in the spirit of Claude Monet's meadow paintings, a touch more realistic: soft, broken, visible brushstrokes with colour laid side by side rather than blended smooth; luminous pastel light; believable forms, scale and atmospheric perspective, with the distance hazier, bluer and softer than the foreground; lost-and-found edges and no outlines anywhere; coloured shadows (lavender, blue-green, lilac), never grey or black; values kept light-to-middle, calm and spacious, quietly optimistic. Up close it reads as paint; from a step back it reads as a real meadow. Late-morning light from the upper left, just outside the frame. Pastel sky: soft cornflower blue at the top, paler toward a hazy cream-blue horizon. Clouds cream-white where lit with lavender-blue shadowed undersides. Fresh spring greens in the grass, cream sunlight on the blade tips, soft butter-yellow dandelions and white dandelion clocks. Wide landscape, 16:10, with a little extra sky and foreground margin so it can be cropped. A calm meadow seen from grass height. Lush grass rises in the bottom-left and bottom-right corners in a gentle bowl: at the far left edge the grass reaches about 42 percent down from the top of the picture, at the far right edge about 46 percent down, and both sides slope down to meet the meadow. The bottom centre is a low, soft, slightly blurred meadow with no tall stems and no flowers. The meadow line (the horizon) runs level exactly two thirds of the way down the picture, with soft hazy distant hills just above it, lowest in the middle. Yellow dandelions and white dandelion clocks only in the two corner clumps, five to nine on each side, the nearest no bigger than a twentieth of the picture's width; none in the centre. One big billowing cumulus cloud in the upper left, a second big cloud on the right between one fifth and one half of the way down, and two small clouds just above the hills on either side. The centre-top of the sky, the middle third of the width down to halfway, is completely empty open sky: only a soft gradient and faint brush texture. No sun disc in frame, only its glow in the top-left corner. No drifting seeds, no stars, no fireflies. Not a photograph, no photo-realism, no HDR, no lens flare, no bokeh discs, no chromatic aberration; not cartoon, not anime, no cel shading, no glossy concept-art finish, not a 3D render, not vector art. No text, letters, logos, watermark or signature. No people, animals, birds, insects, buildings, fences, paths, poles or wires. No pure black and no pure white areas.
```

### Acceptance checklist, per set

- [ ] Its style matches §1: brushwork visible at 100 %, no outlines, no anime or photo look.
- [ ] Its palette is within reach of the §2 swatches, and it passes the chroma, day-highlight and
      night-lightness rules.
- [ ] The composition matches §3 or §4, including the horizon row and the safe areas: the card
      zone, the Home strip, the pane keep-box and the quiet right edge.
- [ ] All three scenes pass the crossfade test.
- [ ] Layers: plate plus layers at rest match the painting; the alpha is shared across scenes; the
      bottom edge is roots-opaque; the edge strip tiles.
- [ ] Sizes, formats and bytes are within §6, and the manifest entry is complete.

---

## As shipped (2026-09-24, round-4 T-Home)

The set in `Resources/art/` differs from §6's size table and §3–§4's targets in the ways below. `ArtAssetTests` holds §6's caps as
ceilings, not exact sizes (DESIGN_RULES §9, R-HO8), and the app reads the measured points below.

- **Heroes are 2376 × 1485 and the grass corners 990 × 743.** The generator's ceiling is about 1.57 MP (1586 × 992 at
  16:10), and §6 caps upscaling at 1.5×. The corners keep the hero's pixel grid (990 / 2376 = 1200 / 2880).
- **Clouds are 1200 × 600**, downsampled from the generator's 1774 × 887; the three `cloud-3` files are posterised to
  meet the 400 KB cap, and their entries say so.
- **A retouch pass replaced eight files** (both moons, the afternoon hero's highlights and its two grass layers, the
  three night clouds); each entry records it, and every layer set still shares one alpha.
- **The night moon sits at (0.719, 0.112) with a halo radius of 0.029 W**, and the afternoon sun at about
  (0.05, 0.48). The app's star exclusion and light pool use these measured points (`SceneLayout`), not §3's targets.
- **The panes' horizons and the keep-running moon miss §4 slightly** (who-reads 0.60, ready 0.57, the moon at
  (0.65, 0.13)); the app's pane regions follow the paintings.
- **The Home band fades from 72 % down** (R-HO6), below the meadow line, as §3's note asked.
- **Total:** 36 files, 17,399,664 bytes (16.59 MiB), under the 20 MiB budget.
