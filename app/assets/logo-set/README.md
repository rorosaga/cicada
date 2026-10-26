# Cicada logo set — 2026-10-22

45 marks, one per provider umbrella, each from the highest source on this ladder that had a
faithful SVG or a PNG of at least 256 px: the brand's own site icon or app icon → its official
GitHub assets → lobehub/lobe-icons (`@lobehub/icons-static-svg@1.97.0`) → svgl (pheralb/svgl @
`f9b726c`) → simple-icons (16.35.0, mono). simple-icons was never needed. Two marks come from
Wikimedia Commons (Scholar, RSS); in both cases there is no better official file, and they match
what the owner's site serves.

- `*.svg` / `*.png`: the set. 37 SVG, 8 PNG.
- `manifest.json`: slug, file, format, pixel size, source tier and URL, sha256, umbrella,
  sub-products, which bundled ids it replaces, dark-variant rule, licence and trademark note.
- `sheet.html` / `sheet.png`: each mark at 26 px in a 36 px rounded tile with a 1 px ring, on light
  and dark, beside today's bundled PNG. `sheet.png` is a headless Chrome 152 screenshot at 2x.
- `bundled/`: a copy of the PNGs the app ships today, so the sheet works on its own.
- `src/`: everything fetched (`site/` official site icons with `_log.json` listing every URL,
  `gh/` pinned repo assets, `lobe/`, `svgl/`, `si/`, `off/` and `apple/` from an earlier pass).

## Umbrellas (one mark each)

| Umbrella | Mark | Under it |
|---|---|---|
| Anthropic / Claude | Claude spark (claude.com) | Claude Code, Claude app, Claude API |
| OpenAI | blossom (chatgpt.com) | Codex, ChatGPT, OpenAI API, Dots |
| Google Gemini | four-colour sparkle (gemini.google.com) | Gemini app, Gemini CLI / Antigravity, Gemini API, Vertex AI |
| xAI Grok | Grok glyph (grok.com) | Grok app, Grok Build, Grok Bot, xAI API |
| Muse (Meta) | Muse's blue "m" squiggle (muse.ai) | Muse from Meta |
| GitHub Copilot | Copilot glyph (GitHub's Primer Octicons, pinned commit) | Copilot in VS Code, Copilot CLI |
| Devin | Cognition cluster (devin.ai) | Devin Desktop (Windsurf until 2026-06-02), Devin CLI, cloud Devin |

**OpenAI: the blossom, not a ChatGPT tile and not Dots' own mark.** The blossom is OpenAI itself,
so Codex, ChatGPT, the API and Dots all fit under it. Dots' yellow mark (kept at
`src/off/dots.svg`) would be a second OpenAI logo, which the owner asked to remove. The bundled
`codex.png` and `chatgpt.png` both go.

**Claude: the spark, not Anthropic's "A\".** Every Claude product shows the spark. The bundled
Claude Code badge (the spark plus a `>_` drawn by the app) can stay as a per-row detail, but the
logo is the one spark.

**Gemini:** the bundled `gemini-cli.png` goes. Gemini CLI and Antigravity are listed under the
sparkle.

## OpenCode: what was wrong

The bundled `opencode.png` is `opencode-logo-light-square.svg` from the console's brand folder.
That file is the "O" from the wordmark, meant to sit on a light page:

- a dark frame (`#211E1E`) on a transparent background
- a pale grey (`#CFCECD`) block filling the lower half
- portrait 4:5 proportions, padded into a square

At 26 px the thin dark frame drops out, and what you see is a grey slab.

What opencode.ai serves today (`/favicon.svg`, also the 180 px touch icon) is drawn the other way:

- a near-black square tile (`#131010`)
- a white portrait frame (64 units thick on 512)
- a mid-grey (`#5A5858`) block in the lower half

So the colours are inverted and the tile is part of the mark. That is the drawing people see in
their browser tab and dock, which is why the bundled one "looked so far from the original."

## What I could not get faithfully

- **Apple apps** (Calendar, Contacts, Messages, Notes, Safari): not in the set. They need extracting
  from the `.app` bundles on a Mac. `src/apple/` has 512 px PNGs from an earlier pass. I don't know
  where they came from, so they stay out.
- **Instinct: 64 px only.** The homepage links one icon, a stick figure at
  `instinct.com/redesign/favicon.ico`. There is no App Store app. instinct.com also serves an
  unlinked `favicon.svg` (a black "I" on white, `src/site/instinctcom-2.svg`). It is probably the
  older mark, so it is not used. Ask the owner which one Instinct shows in Messages.
- **Warp: 196 px.** warp.dev serves no SVG and nothing larger. svgl's `warp.svg` is the retired teal
  mark.
- **Muse (2026-10-26).** The owner asked for Muse's own mark: `muse.svg` is the SVG favicon muse.ai
  serves (the same drawing as its App Store icon). Meta's infinity (svgl) left the set with it.
- **GitHub Copilot (2026-10-26).** GitHub's brand site has published only lockups since 2025, so the
  bare Copilot glyph comes from GitHub's own Primer Octicons repo (`copilot-48.svg`, pinned commit).
  VS Code's icon left the set; Cline, Goose, Kiro and Poke left with their catalog rows.
- **claude.ai and openai.com answered 403.** claude.com and chatgpt.com served the same marks.
- **Style is not fully uniform, and can't be without restyling.** Some vendors publish a bare glyph
  (Claude, Gemini, Cursor, Groq, …). Others only publish a tiled app icon (Grok, OpenCode,
  OpenRouter, Amp, Hermes, Warp, Wispr, Notion, Instinct). Each is used as published.
  Where a tiled vendor also has a bare glyph, it came from a lower rung (lobe-icons, svgl) or is a
  redraw, so I kept the official tile.
- **Dark mode.** Five marks are black on transparent: OpenAI, Zed, Copilot, Devin and
  GitHub. These are flagged `dark_variant` and use the bundled set's existing rule: an exact
  luminance inversion on dark. Nothing else is recoloured.
- **WhatsApp, Spotify, YouTube, LinkedIn, Reddit, Instagram, Brave, Raindrop, Pinterest**: their
  sites serve only small rasters or masks (sizes in `manifest.json` notes), so the SVG is svgl's.
  Each was checked by eye against the site's own icon in `src/site/`.

## Licence

Every mark is its owner's trademark, used nominatively to identify the product. None is restyled,
recoloured (except the luminance inversion above) or combined, and no affiliation is claimed. The
lobe-icons and svgl packages are MIT, but that licence covers the catalogues, not the marks.
