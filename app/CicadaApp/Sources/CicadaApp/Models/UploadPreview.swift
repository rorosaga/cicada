import Foundation

/// One grouping inside a dropped export — an Instagram collection, a YouTube
/// playlist, a Pinterest board, a bookmark folder — and how many items it holds.
struct UploadCollection: Codable, Equatable, Hashable, Identifiable {
    let name: String
    let kind: String
    let count: Int

    /// Name alone is not unique across kinds, and a colliding `ForEach` id
    /// silently collapses rows (the same bug the heatmap weekday column had).
    var id: String { "\(kind):\(name)" }

    init(name: String, kind: String, count: Int) {
        self.name = name
        self.kind = kind
        self.count = count
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = (try? c.decode(String.self, forKey: .name)) ?? ""
        kind = (try? c.decode(String.self, forKey: .kind)) ?? "list"
        count = (try? c.decode(Int.self, forKey: .count)) ?? 0
    }
}

/// `POST /sources/upload?preview=true` — what a dropped export CONTAINS.
/// Answering it stages nothing, so this is safe to request on every drop.
struct UploadPreview: Codable, Equatable {
    let recognized: Bool
    let platform: String
    let total: Int
    let collections: [UploadCollection]
    let warnings: [String]

    init(recognized: Bool, platform: String, total: Int,
         collections: [UploadCollection], warnings: [String]) {
        self.recognized = recognized
        self.platform = platform
        self.total = total
        self.collections = collections
        self.warnings = warnings
    }

    /// Tolerant on purpose: a backend older than G71 answers the same endpoint
    /// with an upload response, and a partially-populated body must render as
    /// "not recognized" rather than throwing inside the overlay.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        recognized = (try? c.decode(Bool.self, forKey: .recognized)) ?? false
        platform = (try? c.decode(String.self, forKey: .platform)) ?? "unknown"
        total = (try? c.decode(Int.self, forKey: .total)) ?? 0
        collections = (try? c.decode([UploadCollection].self, forKey: .collections)) ?? []
        warnings = (try? c.decode([String].self, forKey: .warnings)) ?? []
    }
}
