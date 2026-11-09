import Foundation

/// The memory switcher's two pure rules (app-fixes-1109): how a drag or ⌥-arrow changes the order, and how big a
/// memory is drawn next to the largest. The order itself is the server's (`POST /banks/order`, kept in `banks.yaml`).
enum BankOrder {
    /// `names` with `name` moved to sit before `target` (nil: last). A name not in the list, or dropped on itself,
    /// changes nothing.
    static func moved(_ names: [String], _ name: String, before target: String?) -> [String] {
        guard let from = names.firstIndex(of: name), name != target else { return names }
        var out = names
        out.remove(at: from)
        if let target, let to = out.firstIndex(of: target) { out.insert(name, at: to) } else { out.append(name) }
        return out
    }

    /// `name` moved one place up (-1) or down (+1); the ends stay.
    static func nudged(_ names: [String], _ name: String, by step: Int) -> [String] {
        guard let index = names.firstIndex(of: name) else { return names }
        let to = index + step
        guard names.indices.contains(to) else { return names }
        var out = names
        out.swapAt(index, to)
        return out
    }

    /// How big a memory is, in the one unit the switcher already says: entities and conversations together.
    static func size(_ bank: MemoryBank) -> Int { bank.entityCount + bank.episodeCount }

    /// The gauge's fill, 0…1, against the largest memory in the list. A memory that holds anything shows a sliver, never
    /// an empty track; an empty one shows none.
    static func fill(_ bank: MemoryBank, among banks: [MemoryBank]) -> Double {
        let biggest = banks.map(size).max() ?? 0
        guard biggest > 0, size(bank) > 0 else { return 0 }
        return max(0.06, Double(size(bank)) / Double(biggest))
    }

    /// Rows shown before the list scrolls.
    static let visibleRows = 7
}
