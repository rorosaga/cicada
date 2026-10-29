import Foundation

// G227 follow-up (owner 2026-10-29) — the wire shapes of `page_joins` and the split sheet's pure rules.

/// `POST /entities/{id}/merge | split | history/{sha}/undo`.
struct PageJoinAnswer: Decodable, Equatable, Sendable {
    var kind: String
    var entityId: String
    var otherId: String?
    var commit: String?
    var restored: [String] = []
    var repointed: [String] = []
    /// Pages an undo took away (a split's new page): the card leaves one it was showing.
    var removed: [String] = []

    enum CodingKeys: String, CodingKey { case kind, entityId, otherId, commit, restored, repointed, removed }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = try c.decode(String.self, forKey: .kind)
        entityId = try c.decode(String.self, forKey: .entityId)
        otherId = try c.decodeIfPresent(String.self, forKey: .otherId)
        commit = try c.decodeIfPresent(String.self, forKey: .commit)
        restored = try c.decodeIfPresent([String].self, forKey: .restored) ?? []
        repointed = try c.decodeIfPresent([String].self, forKey: .repointed) ?? []
        removed = try c.decodeIfPresent([String].self, forKey: .removed) ?? []
    }
}
