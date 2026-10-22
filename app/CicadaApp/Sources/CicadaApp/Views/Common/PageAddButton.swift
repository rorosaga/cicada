import SwiftUI

/// DR-75 (consistency pass, round 2, 2026-10-20) — a page's one way to add a thing: a compact `NeutralButton` (DR-40)
/// at the trailing end of the eyebrow row (DR-25), the `plus` glyph and a verb-and-noun label ("Add a source",
/// "Add a look"), with what it adds in `.help`. Sources drew a labelled button and Looks a bare `+`; a bare glyph hides
/// what it adds, so the labelled one is kept. The one exception is the Sleep page's tab-row `+` (R-DL14: ⌘N's only
/// home, drawn in whichever row is on screen); Skills adds from its own field (the owner's header).
struct PageAddButton: View {
    let title: String
    let help: String
    var shortcut: KeyboardShortcut? = nil
    let action: () -> Void

    var body: some View {
        NeutralButton(title: title, systemImage: "plus", size: .compact, shortcut: shortcut, help: help,
                      action: action)
            .accessibilityLabel(title)
    }
}
