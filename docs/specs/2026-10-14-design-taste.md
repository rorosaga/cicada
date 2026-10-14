# Design taste — remembering the look of what the person likes

Owner, 2026-10-14: *"work on the design and implementation of extracting the design/views/aesthetics of websites i like
with screenshots and snippets and other stuff. Embeddings model here btw might be extremely useful".*

Status: **slice 1 built** on `feat/design-taste` (marked ✅ below); everything else here is the design for later
slices. Related rows: G61 (sources), G159 (pictures and previews), G166 (reading with the person's own agent), G162
(video), G112 (skills). Prior art credited: DigUp (github.com/ARahim3/DigUp, MIT) for per-type units, exclusion lists,
an exact-word boost and model-version stamping — ideas only, no code.

## 1. What a design reference is

A reference is the person saying **"I like how this looks"**, with enough attached that an agent can later build in
that direction:

| Piece | What it is | Where it lives | Memory or cache |
|---|---|---|---|
| The screenshot | What the person was looking at (a viewport, a region, a whole page) | `<bank>/assets/design/<id>.<png\|jpg>` ✅ | **Memory** (an asset in the bank, like an uploaded picture) |
| The page | Its link and site | frontmatter `url`, `site` ✅ | Memory |
| What they liked | Their own words | body `## What I liked` ✅ | Memory |
| Colours | Palette with shares, read from the pixels | frontmatter `palette`, `look` ✅ | Memory (deterministic, recomputable, small) |
| Type and spacing | Font families, sizes, spacing, radii, colours from selected CSS | frontmatter `tokens` ✅ | Memory |
| Snippets | HTML/CSS the person selected (or the public page gave) | body `## Snippets` ✅ | Memory |
| The visible region | Where in the page the screenshot sits | frontmatter `region` ✅ (accepted, not yet captured by the app) | Memory |
| Image and note vectors | EmbeddingGemma 2 vectors | `$CICADA_HOME/design-index/<bank-id>.sqlite` ✅ | **Cache** (derived, disposable, outside every bank) |
| A model's description | "Editorial, warm serif, generous margins…" | frontmatter `described` + `described_by` (later) | Memory, written in Sleep or on a click, never at capture |

**Why the screenshot is memory, not a cache.** A preview or a logo can be fetched again; the person's capture of a
page as it looked that day cannot. If it lived outside the bank, handing the bank over would lose every look — a
portability bug by CLAUDE.md's own definition. The cost is git weight (one PNG/JPEG per look, ≤ 4 MB, the app shrinks to
≤ 2560 px); that trade is open question 2.

**Not an entity.** The ten types stay closed. A reference is a store like backlogs (G150): one markdown file per item,
one writer (`design_refs`), never extracted by Stage 1, never decaying. It may point at a page it is about (`entity:`,
e.g. a company or tool page that already exists) and never creates one. A later Sleep step may link references to
pages and claims (`likes_style_of`?) — open question 6.

## 2. How a reference is captured (three doors, all inside the rails)

Cicada never spawns a browser and never signs in (G166); the backend never fetches behind a login and never opens a
path a request names. So every screenshot comes from something the person controls.

1. **Drop or paste in the app** ✅ — onto the Looks page (or `+` → a file). The app reads the image (it is the app's job
   to read; ⌘V goes through SwiftUI's paste command, never `NSPasteboard.general`), shrinks it (`DesignImageShrink`),
   and the composer asks for the link, a name and what they liked; *Save to Looks* posts bytes to `POST /design`.
2. **The person's own agent** ✅ — `cicada_save_design` over MCP. An agent with a browser tool (the person's own, signed
   in as them, at their request) takes the screenshot and sends it as a file path (stdio only: the MCP server is the
   agent's child, so reading the file it just saved is the agent's own read, restricted to a PNG/JPEG outside the
   harness homes, Cicada's home, `~/Library` and the bank) or as base64. It may add the HTML/CSS the person pointed at
   and the visible region. Written as the harness, with the session trailer.
3. **Capture in the app** (later) — a *Capture what I'm looking at* action (menu-bar worm and ⌘⇧L): ScreenCaptureKit
   with the person's Screen Recording permission, a region picker, and — when the frontmost app is a browser the person
   already turned on for reading (G126) — its current tab's URL. Only on the person's action; nothing is captured on a
   timer. Cost: a new TCC prompt, which the owner disliked for FDA-heavy flows (open question 3).

A public page's **HTML/CSS for tokens** (computed colours, `font-family`, spacing scale, radii) may be fetched once, on
the person's click (*Read this page's styles*), by the backend through `net_guard` under the ToS rail (4 s, ≤ 512 KB, no
cookies, walled hosts never asked, a block never retried) — the `media_preview` pattern. Not built: slice 1 reads
tokens only from snippets someone selected.

## 3. What is extracted, and when

**At capture (no model, ✅):** the palette (`design_palette.palette`: pixels at ≤ 256 px, 5-bit bins merged greedily under
RGB distance 28, every colour ≥ 1 %, largest first) and its words (`dark`/`light`, `muted`/`vivid`, hue names); CSS
tokens from snippets (regular expressions, most frequent first). Pixels come from `image_decode`: macOS's `sips` in a
child process over a temporary file the backend wrote itself, returning a BMP parsed with numpy — the server keeps no
image library and a hostile file costs a failed decode, never the backend. "No LLM at capture time" holds: nothing here
is a model.

**After capture (✅):** the image vector and the note vector (§4), in the background after a save and on every search;
never by Sleep; the background job never runs while Sleep runs.

**In Sleep or on a click (later):** a model's short description of the look in words ("dense dark dashboard, one soft
blue accent, Inter at 14 px"), provider-neutral copy, stored with `described_by` (the engine) so it is provenance, not
the person's words. It would read the screenshot with the person's own engine (an image-capable one) — spend is the
existing Sleep spend rules (ruling 4 for scheduled runs).

## 4. Embedding and search: one space for words and pictures

EmbeddingGemma 2 puts text, images, video and audio in one 768-wide space (Matryoshka to 128). The Core ML export ships
a vision encoder beside the text one: `vision_70/140/280` turn 16 px patches into 70/140/280 tokens already projected
into the text model's input space; the text model then embeds `<bos> <|image> tokens <image|> <eos>` as it would a
sentence. So **one cosine compares "dark minimal dashboard with serif headings" with a screenshot.** ✅

- **Download** ✅: the vision `.mlpackage` and `position_embeddings.f16` (≈ 309 MB) are pinned in
  `api/data/embeddinggemma-2.lock.json` as `vision_files` at the same revision; fetched only by the person's click
  (Looks → *Turn on*, or `make embedding-model-vision`), every file sha256-checked, grafted beside the text encoder with
  a mark written last. The audio encoder is never fetched.
- **Budget** ✅: 70 tokens on the GPU (`CPU_AND_GPU`, as the export recommends): ≈ 15 ms an image published, 87.0 % vs
  89.5 % zero-shot at 280. Preprocessing follows the export's card (aspect kept, sides in 48 px steps, ≤ 9 × budget
  patches, RGB in [0, 1], row-major 16 × 16 × RGB patches, position table `x + y`, a 3 × 3 average pool). Input dtypes
  are read from the compiled model's `metadata.json`. **Not verified against the real model here** (nothing was
  downloaded); the opt-in test `test_real_encoder_puts_pictures_and_words_in_one_space` (`CICADA_REAL_VISION=1`) is the
  check to run on the owner's Mac.
- **The index** ✅: outside the bank, rows stamped with model and hash (DigUp's model-version stamping), so a new model or
  a changed note re-embeds exactly what moved.
- **Search** ✅: words (whole word 2, prefix 1, exact phrase +3 — DigUp's boost), the query against screenshots, the
  query against notes; or an example picture against screenshots. Legs fused by reciprocal rank (k = 60), so a
  text–image cosine (≈ 0.2–0.35) never competes with a text–text one (≈ 0.5–0.8). Without the image encoder, notes and
  words; without EmbeddingGemma 2, words. The query is never logged or stored.
- **Later**: region crops (embed the hero, the nav and the cards separately — DigUp's per-type units: a "unit" is a
  region, not a page); an exclusion list (sites or tags never shown to agents); video frames through the same encoder
  for motion references (G162 never downloads a video, so only a stream the person plays in the app).

## 5. How agents use it

- **MCP** ✅: `cicada_save_design` (§2) and `cicada_design_search` (words, a picture, or nothing for the newest; each row
  carries link, palette, look words, fonts, the person's words and the screenshot's path). Stdio only in slice 1
  (`NEVER_REMOTE`); the CLI rows `cicada design save|search` are proposed spellings.
- **The skill** ✅ (`skills/design-taste/SKILL.md`): before building UI, search the board with what you are making,
  read the top looks (and open the screenshots), build in that direction from the palette roles, the type, the spacing
  and what the person liked — never copying a logo, words or a layout — and cite which looks you drew from. Not yet
  installed by `SkillInstaller` (open question 7).
- **G112 (later)**: compile the board into a portable *design brief* skill per person — a few palettes with roles, type
  pairings, spacing scale, "likes / avoids" in their words, each line citing references — so a harness with no Cicada at
  all still builds in their taste. Cicada stays its provenance.
- **Handshake (later)**: one line when the board is non-empty ("the person keeps a design board: search it before
  building UI"), inside the 1,800-token budget, with R12 checked.

## 6. The app surface

✅ **Looks**, the ninth rail page (⌘9): a board of tiles (screenshot, name, a proportional colour strip, site, day); the
eyebrow's search field (words; the board re-ranks); drop or paste anywhere → a composer (link, name, what you liked;
*Find similar* or *Save to Looks*); a click opens the reference beside the board (screenshot, link, what you liked,
colours with shares and words, type, snippets, who saved it and how, *Remove*). When the image model isn't here, one row
offers it with its size. Shown on the demo bank, which now holds five made-up looks (four the person's, one an agent's).

Later: group by tag or by look word ("Dark", "Editorial"); compare two looks side by side; pick colours off a screenshot;
*Copy as CSS variables*; an *Apply to…* hand-off that opens the agent with the skill and the chosen looks.

## 7. Rails check

- No browser spawned, no sign-in, no fetch behind auth: every screenshot is the person's or their agent's. ✅
- The backend parses bytes; it opens only its own temporary files and the bank. ✅
- No LLM at capture time; descriptions only in Sleep or on a click. ✅ (none built)
- Models only on the person's click, pinned and verified, into `~/.cicada/models`. ✅
- Derived index disposable, outside every bank, never in git; the query never logged. ✅
- Demo bank refuses capture (409 / agent refusal); the demo's own board is generated. ✅
- Write admission held through the commit; the person's writes commit alone as `user`. ✅
- Provider-neutral copy. ✅
- The ten entity types stay closed. ✅

## 8. Open questions only the owner can answer

1. **Placement and name.** A ninth rail page called *Looks* (⌘9), or a tab inside the Feed, or another name
   (*Taste*, *Inspiration*, *Design*)? It is built as ⌘9 because it was the first free cell (the Projects ruling's
   reasoning), not because anyone decided it.
2. **Screenshots in git.** Keep each screenshot in the bank (portable, ≤ 4 MB each, grows the repo), or keep only a
   small thumbnail in the bank and the full image in a store outside it (lighter git, a bank handed over loses the full
   pictures)? Or Git LFS?
3. **In-app capture.** Is a Screen Recording permission prompt acceptable for *Capture what I'm looking at*, given your
   dislike of permission-heavy flows? Or is drop/paste plus the agent enough?
4. **Fetching a public page's styles.** May the backend fetch a page's HTML/CSS once, on your click, for its tokens
   (fonts, colours, spacing), under the ToS rail — or only ever what you or your agent selected?
5. **Remote connections.** Should a cloud app with a remote connector be able to save or search looks? Under which scope
   (`record` to save; is a screenshot "your own words" and so `sources`-gated to read)?
6. **Into the graph.** Should Sleep link a look to pages and claims (e.g. a `likes_style_of` predicate on your own
   page, or a project that uses a look), or should the board stay apart from the graph?
7. **The skill.** Install `design-taste` with Cicada's own skills (`SkillInstaller`), mention the board in the
   handshake, or keep it opt-in from Settings → Skills?
8. **Model descriptions.** Do you want a model to describe each look in words (in Sleep, on your engine, with its
   spend), or only on a click per look, or never?
9. **What counts as a look.** Websites only, or also app screens, posters, slides, photos of objects — the same board,
   or separate boards per kind?
