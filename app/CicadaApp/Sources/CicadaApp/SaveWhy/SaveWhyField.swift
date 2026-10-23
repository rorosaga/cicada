import AppKit

/// G191 v7 — the panel's field grows with what is written (owner 2026-10-23: "for the first couple of newlines, have
/// the text input vertically expand smoothly until a limit arrives where it becomes scrollable").
///
/// **The cap is five lines.** The words are capped at 500 characters (`saved_why.MAX_TEXT`); at the field's 12 pt and
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
    /// What AppKit's text field keeps clear at the two ends of a line (its line-fragment padding, both sides).
    static let linePadding: CGFloat = 4

    /// The field's text font, as AppKit measures it: `CicadaTheme.metaFont` (12 pt, scaled).
    static var font: NSFont { NSFont.systemFont(ofSize: CicadaTheme.scaled(12)) }

    /// One line's height in `font`.
    static func lineHeight(_ font: NSFont = font) -> CGFloat {
        NSLayoutManager().defaultLineHeight(for: font).rounded(.up)
    }

    /// How many lines `text` takes at `width` in `font`: its own line breaks plus wrapping, at least one.
    static func lineCount(_ text: String, width: CGFloat, font: NSFont = font) -> Int {
        guard !text.isEmpty, width > 1 else { return 1 }
        // A trailing line break opens a new, empty line the measurement would not count.
        let measured = text.hasSuffix("\n") ? text + " " : text
        let rect = (measured as NSString).boundingRect(with: CGSize(width: width, height: .greatestFiniteMagnitude),
                                                       options: [.usesLineFragmentOrigin, .usesFontLeading],
                                                       attributes: [.font: font])
        return max(1, Int((rect.height / lineHeight(font)).rounded()))
    }

    /// The lines the field shows: one to `maxLines`; past that it scrolls.
    static func visibleLines(_ count: Int) -> Int { min(max(count, 1), maxLines) }

    /// The text area's height for `lines` visible lines (the capsule's padding is outside it).
    static func textHeight(lines: Int, lineHeight: CGFloat = lineHeight()) -> CGFloat {
        CGFloat(visibleLines(lines)) * lineHeight
    }

    /// How much taller the panel can get while it is open: the field at its cap, plus up to two rows of suggested
    /// reasons. The window is made that much taller up front (transparent below the card), so it never resizes under
    /// the person; the card's own shape grows inside it.
    static var growthReserve: CGFloat {
        let chipRow = lineHeight() + CicadaTheme.scaled(5) * 2 + CicadaTheme.scaled(6)
        return CGFloat(maxLines - 1) * lineHeight() + 2 * chipRow + CicadaTheme.spacingSM
    }
}
