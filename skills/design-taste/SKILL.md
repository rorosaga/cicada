---
name: design-taste
description: >-
  Build UI in the style of what this person likes. Use before designing,
  building or restyling any interface, page, component or slide for them,
  and whenever they say they like how a site or screen looks ("save this
  style", "I love this layout"). Reads and fills their Cicada design board.
---

# Design taste

The person keeps a board of looks they like in Cicada: screenshots of sites and
screens, each with the page's link, what they liked in their own words, the
colours Cicada read from the pixels, and any HTML/CSS they pointed at. This skill
is how an agent uses it. Cicada is only its provenance — the taste is theirs.

## Before you build UI

1. Search the board with what you are about to make:
   `cicada_design_search(query="settings page, dark, dense tables")`.
   With no query it lists the newest looks.
2. Read the top three to five results. Each gives the link, the palette
   (largest share first), the look words (dark/light, muted/vivid, hues), the
   fonts, what the person liked, and the screenshot's file — open it if you can
   see images.
3. Build in that direction: take the palette's roles (the largest colour is the
   ground, a small vivid one is the accent), the type families, the spacing and
   radii from the snippets, and above all what the person said they liked.
   Never copy a site's logo, words or layout wholesale.
4. Say which looks you drew from, by name and link, in one line. If the board
   has nothing close, say so and ask whether to save a reference first.

## When the person likes a look

Save it: take a screenshot of what they are looking at (your browser tool, or a
file they gave you), then
`cicada_save_design(image_path="/abs/path/shot.png", url="https://…", note="<what they liked, in their words>", snippets=[{"lang": "css", "code": "…"}])`.
Ask what they like about it if they didn't say — the note is what makes the
reference useful later. Never save a page behind a login without them asking,
and never anything that shows other people's private data.

## Searching by picture

`cicada_design_search(image_path="/abs/path/example.png")` finds the saved looks
most like a picture. It needs the image model on their Mac; if the answer says
it isn't on, tell them they can turn it on from Cicada's Looks page.
