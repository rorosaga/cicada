# Bundled fonts

**Instrument Serif** — the display face of the Meadow visual system (G137, spec R-M3): page
titles, onboarding headlines and empty-state titles at 22 pt and above. Never body text, never a
number.

| File | PostScript name | sha256 |
|---|---|---|
| `InstrumentSerif-Regular.ttf` | `InstrumentSerif-Regular` | `498efd461f6ddfcb7a111bf9a565709d2085d48201d501ead960d93e84ffbb88` |
| `InstrumentSerif-Italic.ttf` | `InstrumentSerif-Italic` | `08939b8bdf534afec24ae0ef5e03f948940cd9a8fe08e7fecbad040e62327385` |
| `OFL.txt` | — | `129ed7618959716959f2941fdd5b49e0ad6e6c1d78726761786a00253d865521` |

- **Copyright:** Copyright 2022 The Instrument Serif Project Authors
  (https://github.com/Instrument/instrument-serif).
- **Licence:** SIL Open Font License, Version 1.1. The full text is `OFL.txt` beside the fonts,
  and it ships inside the app bundle with them, which is what the OFL asks. No Reserved Font Name.
- **Source:** `google/fonts`, `ofl/instrumentserif/` on `main` (upstream commit
  `65c0ef225f386a3c7e87570a4aa9cc0262c2fd81` per its `METADATA.pb`), fetched 2026-09-23.
  Unmodified: no subsetting, no renaming.
- **Loading:** `CicadaFonts.registerBundled()` (`Theme/CicadaFonts.swift`) registers both faces
  with CoreText for this process at launch, from `Bundle.cicadaResources`' bare `fonts`
  directory. `CicadaTheme.displayFont(size:italic:)` is the only code that names them.
