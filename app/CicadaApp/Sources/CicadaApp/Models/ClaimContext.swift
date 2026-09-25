import Foundation

/// The app's copy of `api/services/claim_contexts.py` (F1, owner review
/// 2026-09-23). A claim's context is an OPEN vocabulary (d2 §2) whose shape is
/// a short lowercase slug; anything else — a raw folder id a paper writer once
/// stored there, the inbox's `as of <date>` qualifier (G60) — keeps its job
/// as a claim key but is never a legend row (R-FX1). Both sides read
/// `api/tests/fixtures/claim_contexts.json`, so a rule changed on one side
/// only turns the other red.
enum ClaimContext {
    static let maxLength = 32

    static func isValid(_ context: String) -> Bool {
        guard !context.isEmpty, context.count <= maxLength else { return false }
        return context.range(of: #"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"#, options: .regularExpression) != nil
    }

    /// `machine-learning` → "Machine learning" (R-FX3). A value that is not a
    /// context is shown as it is: a `ContextPill` on a G60 claim reads
    /// "as of 2026-05-01", which is already words.
    static func displayName(_ context: String) -> String {
        guard isValid(context) else { return context }
        let spaced = context.replacingOccurrences(of: "-", with: " ")
        return spaced.prefix(1).uppercased() + spaced.dropFirst()
    }

    /// The Graph legend's rows: every context a node, a satellite or an edge
    /// carries, minus anything that is not a context, sorted.
    static func roster(nodes: [GraphNode], links: [GraphEdge]) -> [String] {
        var all = Set(nodes.flatMap(\.contexts))
        for node in nodes { if let c = node.context { all.insert(c) } }
        for link in links { if let c = link.context { all.insert(c) } }
        return all.filter(isValid).sorted()
    }

    /// A satellite (`bob-example#family`) is a view of its subject and has no
    /// page of its own — selecting it fetched `/entities/<id>#<ctx>` and opened
    /// an empty card (the owner's report). It opens its subject instead.
    static func cardTarget(for id: String, in nodes: [GraphNode]) -> String {
        nodes.first { $0.id == id && $0.isFacet }?.parentId ?? id
    }
}
