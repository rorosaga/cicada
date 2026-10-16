import CoreGraphics

/// R-S1 — ONE column count for every section, derived once from the container
/// width in scaled units.
///
/// Two defects in one line. `SourceCardGrid`'s
/// `.adaptive(minimum: 220, maximum: 320)` hardcoded raw points while every
/// font and spacing token inside the card goes through `CicadaTheme.scaled`
/// (C2), so at ⌘+ the text grew 40 % and the column did not; and `.adaptive`
/// plus `alignment: .leading` left a card-shaped hole at the end of any section
/// whose last row was short (C3). A fixed count fixes both, and it changes in
/// one place when the window resizes OR `uiScale` moves.
enum SourceGridColumns {
    /// The width one card wants before the grid adds a column, scaled with the chrome. 290 pt at `uiScale == 1.0`
    /// (QA 2026-10-16): at 260 a 1200 pt window (a ~1,070 pt grid) drew four ~255 pt cards and truncated nearly every
    /// title and meta line ("Claude C…"), while three columns at 1100 truncated nothing — so a window under ~1,280 pt
    /// now gets three.
    static let unit: CGFloat = 290
    /// Never one column: a single-column Sources page reads as a list of
    /// eleven rows, which is the shape G124 replaced. Never five: past four the
    /// card's five bands stop fitting the tile width the metrics pin.
    static let minimum = 2
    static let maximum = 4

    static func count(width: CGFloat, scale: CGFloat) -> Int {
        // A `GeometryReader` hands out 0 on its first pass and, in a collapsed
        // split view, can hand out a non-finite width; `Int(_: CGFloat)` traps
        // on both NaN and infinity, so neither ever reaches the conversion.
        let resolved = scale.isFinite ? max(scale, 0.1) : 1
        guard width.isFinite, width > 0 else { return minimum }
        return max(minimum, min(maximum, Int((width / (unit * resolved)).rounded(.down))))
    }
}
