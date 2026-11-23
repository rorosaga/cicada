import Foundation

/// A passage's sources, as the one cluster of marks that ends it (owner 2026-11-23, DESIGN_RULES §9, amends DR-80: no
/// superscript numbers anywhere on the page). Pure, so `PageInlineTests` holds the rule; `SourceCluster` draws it.
///
/// The rule: the mark of where each source was said — up to three, the first of each kind, in the order the passage
/// cited them — then the rest as one "+N" (every source after the marks shown, so the marks and the N always add up to
/// the passage's sources). Six conversations in one app are that app's mark and "+5", not six identical tiles.
struct SourceClusterModel: Equatable {
    /// The most marks drawn; a fourth kind of source and beyond is the "+N".
    static let places = 3

    /// The marks drawn, left to right.
    let marks: [String]
    /// Sources not represented by a mark drawn; 0 when every source has its own.
    let more: Int
    /// How many sources the passage cites in all.
    let total: Int

    /// `keys` — one mark key per source in the order cited (`PageBlocks.Citations.markKey`); a source the backend gave
    /// no mark for is `nil` and draws the unknown mark's stand-in, so it still counts.
    init(keys: [String?]) {
        var seen: [String] = []
        for key in keys {
            let key = key ?? Self.unknown
            if !seen.contains(key) { seen.append(key) }
        }
        marks = Array(seen.prefix(Self.places))
        total = keys.count
        more = max(keys.count - marks.count, 0)
    }

    static let unknown = "unknown"

    var isEmpty: Bool { total == 0 }

    /// "+3", quiet, after the marks.
    var moreWords: String? { more > 0 ? Copy.RunCard.moreSources(more) : nil }
}
