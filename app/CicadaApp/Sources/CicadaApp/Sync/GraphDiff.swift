import Foundation

/// The minimal change set between two `/graph` snapshots (§5.6).
///
/// A delta is what `graph.js::updateGraphDelta` needs to mutate the live d3
/// simulation in place — nodes keep their `x/y/vx/vy`, so a post-Sleep refresh
/// that touched one entity nudges one node instead of re-laying-out the whole
/// graph.
struct GraphDelta: Sendable {
    /// Nodes present in the new snapshot but not the old one.
    var added: [GraphNode] = []
    /// Nodes present in both whose `contentHash` differs (or is missing on
    /// either side — see `GraphDiff.diff`).
    var updated: [GraphNode] = []
    /// Ids present in the old snapshot but not the new one.
    var removed: [String] = []
    /// The complete new link set, but **only** when the link set actually
    /// changed. `nil` means "links are unchanged, don't touch them" — links
    /// are replaced wholesale rather than diffed because d3.forceLink rewrites
    /// their endpoints into node references once the simulation starts, which
    /// makes per-link identity fiddly and buys very little.
    var links: [GraphEdge]?
    /// True when there is no prior snapshot to diff against, i.e. this push
    /// must go through `updateGraph` (full replace), not `updateGraphDelta`.
    /// In that case `added` holds every node and `links` every link.
    var isFull: Bool = false

    /// Nothing to push (only meaningful for a non-full delta).
    var isEmpty: Bool {
        !isFull && added.isEmpty && updated.isEmpty && removed.isEmpty && links == nil
    }
}

enum GraphDiff {
    /// Diff two graph snapshots by node id + `contentHash`.
    ///
    /// - `old == nil` → `isFull` (every node in `added`, every link in `links`).
    /// - An **empty `contentHash` on either side** counts as *changed*. An
    ///   older backend that doesn't emit the field would otherwise make every
    ///   node compare equal and the delta would silently drop real edits; with
    ///   this rule the transport degrades to "everything is an update", which
    ///   is redundant but never wrong.
    static func diff(old: GraphResponse?, new: GraphResponse) -> GraphDelta {
        guard let old else {
            return GraphDelta(added: new.nodes, updated: [], removed: [],
                              links: new.links, isFull: true)
        }

        var oldById: [String: GraphNode] = [:]
        oldById.reserveCapacity(old.nodes.count)
        for n in old.nodes { oldById[n.id] = n }

        var newIds = Set<String>()
        newIds.reserveCapacity(new.nodes.count)

        var added: [GraphNode] = []
        var updated: [GraphNode] = []
        for n in new.nodes {
            newIds.insert(n.id)
            guard let prev = oldById[n.id] else {
                added.append(n)
                continue
            }
            if prev.contentHash.isEmpty || n.contentHash.isEmpty
                || prev.contentHash != n.contentHash {
                updated.append(n)
            }
        }

        let removed = old.nodes.map(\.id).filter { !newIds.contains($0) }

        let links: [GraphEdge]? = linkSetChanged(old: old.links, new: new.links)
            ? new.links
            : nil

        return GraphDelta(added: added, updated: updated, removed: removed,
                          links: links, isFull: false)
    }

    /// Link identity is `(source, target, label, context, claimId)`. Compared
    /// as a multiset-ish pair (set + count) so a pure reordering by the backend
    /// doesn't force a link replacement, but any real add/remove/relabel does.
    private static func linkSetChanged(old: [GraphEdge], new: [GraphEdge]) -> Bool {
        if old.count != new.count { return true }
        return Set(old.map(key)) != Set(new.map(key))
    }

    private static func key(_ e: GraphEdge) -> String {
        "\(e.source)\u{1}\(e.target)\u{1}\(e.label)\u{1}\(e.context ?? "")\u{1}\(e.claimId ?? "")"
    }
}
