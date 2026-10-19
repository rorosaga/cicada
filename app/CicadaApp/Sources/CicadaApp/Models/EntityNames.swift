import Foundation

/// R-DL5 (DR-54, DR-56) — an entity id shown as its page's name. The server's inbox options carry a claim's object, and
/// when that object is a page it is the page's id ("tool-example-a"); the owner's live check read the slug where the
/// page says "Tool Example A". Display only: nothing that is sent changes (option keys, a merge's target and survivor),
/// and a label that is not EXACTLY an id the graph holds stays verbatim — an unknown slug is never humanised.
struct EntityNames: Equatable {
    static let empty = EntityNames(byId: [:])

    let byId: [String: String]

    init(byId: [String: String]) { self.byId = byId }

    /// A facet satellite (`bob-example#work`) is a view of a page, not a page.
    init(nodes: [GraphNode]) {
        byId = Dictionary(nodes.filter { !$0.isFacet }.map { ($0.id, $0.name) }, uniquingKeysWith: { first, _ in first })
    }

    func name(for id: String) -> String? {
        let key = id.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let name = byId[key], !name.isEmpty else { return nil }
        return name
    }

    func display(_ label: String) -> String { name(for: label) ?? label }
}

extension Store {
    /// The graph snapshot's names by id, memoised on the snapshot's change token and size (the pair
    /// `GraphViewModel.clusterSearchIndex()` keys on), so a card reading it per option costs one dictionary lookup.
    var entityNames: EntityNames {
        let stamp = graph.loadedAt
        let nodes = graph.value?.nodes ?? []
        if let memo = entityNamesMemo, memo.stamp == stamp, memo.count == nodes.count { return memo.names }
        let names = EntityNames(nodes: nodes)
        entityNamesMemo = (stamp, nodes.count, names)
        return names
    }
}
