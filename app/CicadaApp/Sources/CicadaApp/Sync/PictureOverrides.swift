import Foundation

/// C11 (G146 plan R-PE10) — one picture write as the app shows it: the picture it paints, the inputs the card's menu
/// reads, and when it settled (`.distantFuture` while the request is in flight).
struct PictureOverride: Equatable {
    var picture: EntityPictureRef?
    var inputs: PictureInputs?
    var at: Date
}

extension Store {
    /// Pure, so `nonisolated`: `Store` is `@MainActor`, and a main-actor static called from a nonisolated synchronous
    /// context (a non-`@MainActor` test's property initialiser, a pure helper) is a compile error, not a warning.
    nonisolated static func pictureKey(bank: String, id: String) -> String { "\(bank)/\(id)" }

    /// The graph snapshot's pictures by id — `.some(nil)` for a node with none, absent for an id the graph has no
    /// node for. Memoised on the snapshot's change token and size (`entityNames`' key).
    var pictureIndex: [String: EntityPictureRef?] {
        let stamp = graph.loadedAt
        let nodes = graph.value?.nodes ?? []
        if let memo = pictureIndexMemo, memo.stamp == stamp, memo.count == nodes.count { return memo.index }
        var index: [String: EntityPictureRef?] = [:]
        for node in nodes where !node.isFacet { index[node.id] = .some(node.pictureRef) }
        pictureIndexMemo = (stamp, nodes.count, index)
        return index
    }

    /// A write in flight always shows. A settled one shows until a NEWER snapshot disagrees with it — someone else
    /// moved the picture since — so an agreeing snapshot never throws away the override's fresher inputs.
    func pictureOverride(for id: String) -> PictureOverride? {
        guard let override = pictureOverrides[Self.pictureKey(bank: bank, id: id)] else { return nil }
        if override.at == .distantFuture { return override }
        guard let loaded = graph.loadedAt, loaded > override.at else { return override }
        if let entry = pictureIndex[id], entry != override.picture { return nil }
        return override
    }

    /// What an entity avatar draws (C11): the write, else the graph node, else what the surface holds (a full page, for
    /// an id the graph has no node for). Nil draws the D fallback.
    func picture(for id: String, held: EntityPictureRef? = nil) -> EntityPictureRef? {
        if let override = pictureOverride(for: id) { return override.picture }
        if let entry = pictureIndex[id] { return entry }
        return held
    }

    func pictureInputs(for id: String, held: PictureInputs?) -> PictureInputs? {
        pictureOverride(for: id)?.inputs ?? held
    }
}
