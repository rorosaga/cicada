import Foundation

/// A source's conversations past `/conversations/recent`'s cap (G136 R-SU22).
/// The loaded page filters locally at once; only a page that HIT the cap can
/// be hiding an older title, so only then does a debounced `?q=` widen it.
enum ConversationSearch {
    /// CLAUDE.md: the recent list is CAPPED (limit ≤ 200) and never a membership test.
    static let cap = 200

    /// Only a page that HIT the cap can be hiding a title; below it the local
    /// filter already saw everything. One character stays local (R-SU2).
    static func needsServer(loaded: Int, query: String) -> Bool {
        loaded >= cap && SearchTiming.wantsServer(query)
    }

    /// Local rows first, in their order; server rows the page lacked, after —
    /// deduped by id, so a widening never shows one conversation twice.
    static func merge(local: [ConversationSummary], server: [ConversationSummary]) -> [ConversationSummary] {
        var seen = Set(local.map(\.id))
        return local + server.filter { seen.insert($0.id).inserted }
    }
}
