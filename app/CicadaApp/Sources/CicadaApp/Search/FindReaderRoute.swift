import Foundation

/// R-SU18 — a palette hit's span → where the Reader opens (Track P's
/// `ReaderTarget`). A whole span lands on its words; anything less opens
/// the document at the top — never a guessed offset. A hit's span is never
/// `derived`: `/search` ships stored spans and passage offsets only.
enum FindReaderRoute {
    static func target(for span: ReaderSpan, title: String? = nil, harness: String? = nil) -> ReaderTarget {
        let focus: ReaderTarget.Focus
        if let start = span.start, let end = span.end, start >= 0, end > start {
            focus = .span(start: start, end: end, hash: span.hash, derived: false)
        } else {
            focus = .none
        }
        return ReaderTarget(episode: span.doc, focus: focus, knownTitle: title, knownHarness: harness)
    }
}
