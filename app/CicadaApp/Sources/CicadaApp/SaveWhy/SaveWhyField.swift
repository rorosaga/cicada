import AppKit
import SwiftUI

/// G191 v7 — the panel's field grows with what is written (owner 2026-10-23: "for the first couple of newlines, have
/// the text input vertically expand smoothly until a limit arrives where it becomes scrollable").
///
/// **The field sizes itself** (owner 2026-11-23, twice: "the text is cutting off"). Its height is AppKit's own layout of
/// its words — `TextField(axis: .vertical)` with `lineLimit(1...maxLines)` and a vertical `fixedSize` — never a line
/// count measured beside it. The prediction it replaced measured the words apart from the field (first at the wrong
/// size, then breaking a long word differently from the field editor) and clipped every line it under-counted.
///
/// **The cap is five lines.** The words are capped at 500 characters (`saved_why.MAX_TEXT`); at the field's 13 pt and
/// its width (≈ 370 pt) a line holds about 60 of them, so five lines show ≈ 300 — most answers whole, never scrolling
/// — while the card stays a short drop from the notch (≈ 75 pt of text at 1×, the panel well under a quarter of a
/// 13-inch screen) and never covers the page the person just saved. Past five the field scrolls inside itself.
///
/// **It eases, and never under Reduce Motion.** DR-60 lists the keyboard *commands* that never animate (⌘1–9, Esc, ⏎,
/// ↑/↓ …): a command moves the person somewhere, and motion there would delay them. A field growing to hold the words
/// being typed is not a command — it is the content's own size changing, which the owner asked to happen
/// "smoothly" — so it eases over `CicadaMotion.fieldGrowDuration` (0.12 s, shorter than a keystroke's repeat, so it
/// never lags the typing). Height is movement, so under Reduce Motion it changes in one frame (DR-66). Recorded as a
/// dated ruling in DESIGN_RULES.md (2026-10-23).
enum SaveWhyField {
    static let maxLines = 5
    /// The field's own insets (the capsule's padding), at 1×; scaled where drawn.
    static let horizontalInset: CGFloat = 10
    static let verticalInset: CGFloat = 6
    /// The field's text size at 1×: the ONE number the field is drawn in (`swiftUIFont`) and the window's reserve and
    /// the capsule's corner are sized from (`font`, `lineHeight`).
    static let fontSize: CGFloat = 13

    /// The field's text font, as SwiftUI draws it.
    static var swiftUIFont: Font { CicadaTheme.font(size: fontSize) }

    /// The field's text font, as AppKit measures it.
    static var font: NSFont { NSFont.systemFont(ofSize: CicadaTheme.scaled(fontSize)) }

    /// One line's height in `font`.
    static func lineHeight(_ font: NSFont = font) -> CGFloat {
        NSLayoutManager().defaultLineHeight(for: font).rounded(.up)
    }

    /// How much taller the panel can get while it is open: the field at its cap, plus up to two rows of suggested
    /// reasons. The window is made that much taller up front (transparent below the card), so it never resizes under
    /// the person; the card's own shape grows inside it.
    static var growthReserve: CGFloat {
        let chipRow = lineHeight() + CicadaTheme.scaled(5) * 2 + CicadaTheme.scaled(6)
        return CGFloat(maxLines - 1) * lineHeight() + 2 * chipRow + CicadaTheme.spacingSM
    }
}
