import Foundation

/// A document indexed the way the server indexes it (design §4.1): every
/// evidence offset is a Python `str` index, i.e. a Unicode **scalar** (code
/// point) index — not a `Character` (grapheme), not UTF-16. `String.count`
/// would put a span after an emoji one place early, and an `NSRange` two, so
/// every provenance slice in the app goes through this one type (the rule
/// `ExcerptText.attributed` already follows for inbox excerpts,
/// `Models/InboxPresentation.swift`).
///
/// **Why an array, not `unicodeScalars.index(_:offsetBy:)`.** Offsetting a
/// view index is O(n) per call, and the Reader slices every turn of a
/// document of up to 400,000 characters (R-PB5): ~200 turns × 100 KB is tens
/// of millions of steps on the main thread. One `Array(unicodeScalars)` is a
/// single O(n) pass and makes every slice O(length of the slice).
struct ScalarText: Hashable {
    let scalars: [Unicode.Scalar]

    init(_ text: String) { scalars = Array(text.unicodeScalars) }

    var count: Int { scalars.count }

    /// Clamps `[start, end)` into the text — a stale or out-of-range offset
    /// must never trap a view (the server recomputes offsets on every read,
    /// and a cached payload can lag the bank by a moment).
    func clamped(_ start: Int, _ end: Int) -> Range<Int> {
        let lower = max(0, min(start, count))
        let upper = max(lower, min(end, count))
        return lower..<upper
    }

    func slice(_ start: Int, _ end: Int) -> String {
        let r = clamped(start, end)
        guard !r.isEmpty else { return "" }
        var view = String.UnicodeScalarView()
        view.append(contentsOf: scalars[r])
        return String(view)
    }

    /// Up to `radius` scalars either side of `[start, end)`, the span itself
    /// in the middle — the hover preview's shape when it is built client-side
    /// from a whole document (a derived chip, `EvidencePreview`).
    func around(_ start: Int, _ end: Int, radius: Int) -> (before: String, span: String, after: String) {
        let r = clamped(start, end)
        return (slice(r.lowerBound - radius, r.lowerBound), slice(r.lowerBound, r.upperBound),
                slice(r.upperBound, r.upperBound + radius))
    }
}
