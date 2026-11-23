import Foundation

/// A page a link on an entity page points at, as the chip shows it (owner 2026-11-23, DESIGN_RULES §9): the page's own
/// name and, where it has one, its picture — never the words the link happened to be written under.
struct PageLinkTarget: Equatable, Sendable {
    let id: String
    /// The name every surface shows (`GraphNode.shownName`: qualified when another page shares the title, G227).
    let name: String
    let type: EntityType
}

/// Which page a written link means, from the graph snapshot the app already holds (no request per link). A ref
/// resolves only when it means **exactly one** page: the page whose id it is, else the one page whose name or alias it
/// is, else the sanitised id the click has always fallen back to. Two pages with one name, or a ref no page answers
/// to, resolve to nothing — the link then keeps its written words and today's behaviour, and the click asks which
/// (G227). Pure; `Store.linkIndex` memoises it per snapshot.
struct PageLinkIndex: Sendable {
    static let empty = PageLinkIndex(nodes: [])

    private let byId: [String: PageLinkTarget]
    private let byName: [String: [String]]
    private let byAlias: [String: [String]]

    init(nodes: [GraphNode]) {
        var ids: [String: PageLinkTarget] = [:]
        var names: [String: [String]] = [:]
        var aliases: [String: [String]] = [:]
        for node in nodes where !node.isFacet {
            ids[node.id] = PageLinkTarget(id: node.id, name: node.shownName, type: node.type)
            names[node.name.lowercased(), default: []].append(node.id)
            for alias in node.aliases where !alias.isEmpty {
                aliases[alias.lowercased(), default: []].append(node.id)
            }
        }
        byId = ids
        byName = names
        byAlias = aliases
    }

    func resolve(_ ref: String) -> PageLinkTarget? {
        let ref = ref.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !ref.isEmpty else { return nil }
        if let hit = byId[ref] { return hit }
        let lowered = ref.lowercased()
        if let named = byName[lowered] {
            return named.count == 1 ? byId[named[0]] : nil
        }
        if let aliased = byAlias[lowered] {
            let distinct = Set(aliased)
            if distinct.count == 1, let id = distinct.first { return byId[id] }
            return nil
        }
        return byId[MarkdownBody.sanitizeID(ref)]
    }
}

extension Store {
    /// The graph snapshot's link index, memoised on the snapshot's change token and size (`entityNames`' key), so a page
    /// of two hundred links costs dictionary lookups.
    var linkIndex: PageLinkIndex {
        let stamp = graph.loadedAt
        let nodes = graph.value?.nodes ?? []
        if let memo = linkIndexMemo, memo.stamp == stamp, memo.count == nodes.count { return memo.index }
        let index = PageLinkIndex(nodes: nodes)
        linkIndexMemo = (stamp, nodes.count, index)
        return index
    }
}
