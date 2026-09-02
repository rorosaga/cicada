import Foundation

/// One "where to look this fact up" reference on an entity page (G61).
/// Matches `EntitySource` in `api/models/schemas.py`.
struct EntitySource: Codable, Identifiable, Hashable {
    var ref: String
    var kind: String        // url | path | note
    var predicate: String?
    var addedBy: String
    var addedAt: String

    /// Stable within one payload — the backend addresses sources by index.
    var id: String { "\(kind)|\(ref)" }

    var url: URL? { kind == "url" ? URL(string: ref) : nil }

    var icon: String {
        switch kind {
        case "url": "link"
        case "path": "folder"
        default: "text.quote"
        }
    }
}

struct EntitySourceList: Codable {
    var entityId: String
    var sources: [EntitySource]
}
