# Cicada app icon: the book and glasses

2026-09-30. The owner asked for the book and glasses as the macOS app icon, on a very dark gray background.

Source art (drawn in Aseprite):

- `cicada-book-glasses-128.aseprite`: the editable source. The approved artwork is one layer, and a separate
  `Glasses rim correction` layer matches the two lower lens rims and removes stray dark pixels under them.
- `cicada-book-glasses-128.png`: its transparent 128 px export. The icon generator reads this file.

The icon itself is built by `app/CicadaApp/Art/AppIcon/make-icon.swift` (no dependencies beyond the macOS SDK):

    swift app/CicadaApp/Art/AppIcon/make-icon.swift      # from the repository root

It crops the art to its opaque pixels and centres it on Apple's app-icon grid: an 824 px continuous-corner plate in a
1024 canvas, filled with a near-black graphite (`#202124` to `#141517`) with a faint light edge. At 1024 px each art pixel
is a 5 × 5 square drawn with nearest-neighbour. Every other size is first blown up with nearest-neighbour to a whole
multiple and then area-averaged down, so pixel edges stay hard and nothing rings. It writes `Cicada.icns` and a
`Cicada-1024.png` preview beside itself. `app/CicadaApp/bundle.sh` copies `Cicada.icns` into
`Contents/Resources/`, and the bundle's `Info.plist` names it as `CFBundleIconFile`.

After editing the art, export the 128 px PNG from Aseprite, rerun the script and commit the new `.icns`.
