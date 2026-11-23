import SwiftUI

/// The views' side of `PageLine` (the page-text door, `Models/PageLine.swift`): page text, a claim, a question or a search
/// snippet drawn as one line of words — a link as the page's own name, no brackets, no stray `**`.
///
/// ```swift
/// PageLineText(item.askText)                      // a line, with the link index of the Store in the environment
/// PageLineText(row.snippet, bold: row.ranges, excerpt: true)   // a search passage, matched runs semibold
/// Text(PageLine.plain(x, links: store.links))     // where a view needs a `Text` of its own (`+`, a `Text` result)
/// .pageHelp(item.askText)                         // a tooltip built from page text
/// ```
///
/// The index comes from the `Store` in the environment (`Store.linkIndex`, built once per graph snapshot and tracked, so
/// a line repaints when the graph arrives); with none in the environment (a preview, a test host) a link reads as its
/// written words, still without brackets.
struct PageLineText: View {
    let raw: String
    var bold: [[Int]] = []
    var excerpt = false

    @Environment(Store.self) private var store: Store?

    init(_ raw: String, bold: [[Int]] = [], excerpt: Bool = false) {
        self.raw = raw
        self.bold = bold
        self.excerpt = excerpt
    }

    var body: some View {
        Text(PageLine.attributed(raw, bold: bold, links: store.links, excerpt: excerpt))
    }
}

extension Store {
    /// `linkIndex`, spelled like the optional's (`PageLine.plain(x, links: store.links)` in a view that holds either).
    var links: PageLinkIndex { linkIndex }
}

extension Optional where Wrapped == Store {
    /// The graph snapshot's link index, or the empty one before it has arrived.
    @MainActor var links: PageLinkIndex { self?.linkIndex ?? .empty }
}

private struct PageHelp: ViewModifier {
    let raw: String?
    var excerpt = false
    @Environment(Store.self) private var store: Store?

    func body(content: Content) -> some View {
        if let raw, !raw.isEmpty {
            content.help(PageLine.plain(raw, links: store.links, excerpt: excerpt))
        } else {
            content
        }
    }
}

private struct PageAccessibility: ViewModifier {
    let raw: String
    var prefix = ""
    @Environment(Store.self) private var store: Store?

    func body(content: Content) -> some View {
        content.accessibilityLabel(prefix + PageLine.plain(raw, links: store.links))
    }
}

extension View {
    /// A tooltip made of page text, as words. Nil or empty adds none.
    func pageHelp(_ raw: String?, excerpt: Bool = false) -> some View {
        modifier(PageHelp(raw: raw, excerpt: excerpt))
    }

    /// An accessibility label made of page text, as words (VoiceOver never hears a bracket).
    func pageAccessibilityLabel(_ raw: String, prefix: String = "") -> some View {
        modifier(PageAccessibility(raw: raw, prefix: prefix))
    }
}
