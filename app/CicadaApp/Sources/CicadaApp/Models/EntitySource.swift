import Foundation

/// One "where to look this fact up" reference on an entity page (G61).
/// Matches `EntitySource` in `api/models/schemas.py`.
struct EntitySource: Codable, Identifiable, Hashable {
    var ref: String
    var kind: String        // url | path | note | app | repo
    var predicate: String?
    var addedBy: String
    var addedAt: String
    /// G61 phase 2 S1 — optional so an older backend still decodes. `access` is the STATED value only: the
    /// derived one (`fact_sources.effective_access`) is not on this endpoint (R-DG18).
    var access: String?
    /// An agent-found source the person took.
    var accepted: Bool?
    /// The person's "Only I know" for this fact.
    var onlyMe: Bool?

    /// Stable within one payload — the backend addresses sources by index. G61 phase 2 S1 keys an entry on
    /// `(ref, predicate)`, so one link can back two facts: the predicate is part of the row's identity, or
    /// `ForEach` would see two rows with one id (DS-3a).
    var id: String { "\(kind)|\(ref)|\(predicate ?? "")" }

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
