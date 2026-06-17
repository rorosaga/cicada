import Foundation

/// Shared filter state for the Graph and Topics tabs. Owned by
/// ``GraphViewModel`` so both surfaces read/write the same filter — Topics no
/// longer keeps its own independent type set. Pushed to graph.js via
/// `applyFilters(jsonObject)`.
struct GraphFilter: Equatable {
    var types: Set<EntityType> = Set(EntityType.selectableCases)
    var statuses: Set<EntityStatus> = [.active, .decaying]   // hide archived/dropped by default
    var minConfidence: Double = 0.0
    var minDegree: Int = 0          // 0 = show isolated nodes; 1 = hide leaves
    var tags: Set<String> = []
    var searchText: String = ""
    // Claim-layer filter axes (§2a context legend, §3a observer bar). Empty =
    // "no filter" (all-pass). graph.js dims/drops non-matching nodes/edges.
    var contexts: Set<String> = []
    var observers: Set<String> = []

    var allTypesSelected: Bool {
        types.count == EntityType.selectableCases.count
    }

    /// JSON-object payload for graph.js `applyFilters`. Sends `null` (omits) for
    /// dimensions that are "no filter" so the JS treats them as all-pass.
    var jsPayload: [String: Any] {
        var payload: [String: Any] = [
            "minConfidence": minConfidence,
            "minDegree": minDegree,
        ]
        payload["types"] = allTypesSelected ? nil : types.map(\.rawValue)
        // statuses: send the explicit set; null only when every status is on.
        let allStatus = statuses.count == EntityStatus.allCases.count
        payload["statuses"] = allStatus ? nil : statuses.map(\.rawValue)
        payload["tags"] = tags.isEmpty ? nil : Array(tags)
        // Claim-layer axes: send only when an explicit filter is active so the
        // JS treats absence as all-pass (matching the existing null semantics).
        payload["contexts"] = contexts.isEmpty ? nil : Array(contexts)
        payload["observers"] = observers.isEmpty ? nil : Array(observers)
        return payload
    }

    /// Apply this filter to a list of entities (Topics list, local search).
    func matches(_ entity: Entity) -> Bool {
        if !types.contains(entity.type) { return false }
        if !statuses.contains(entity.status) { return false }
        if entity.confidence < minConfidence { return false }
        if !tags.isEmpty && tags.isDisjoint(with: Set(entity.tags)) { return false }
        return true
    }

    mutating func toggleType(_ type: EntityType) {
        if types.contains(type) { types.remove(type) } else { types.insert(type) }
    }

    mutating func toggleStatus(_ status: EntityStatus) {
        if statuses.contains(status) { statuses.remove(status) } else { statuses.insert(status) }
    }

    mutating func toggleContext(_ context: String) {
        if contexts.contains(context) { contexts.remove(context) } else { contexts.insert(context) }
    }
}

/// A search hit returned by `GET /search` (or composed locally from the loaded
/// graph when the LEANN endpoint isn't shipped yet).
struct GraphSearchHit: Identifiable, Codable {
    let id: String
    let name: String
    let type: EntityType
    let status: EntityStatus
    let confidence: Double
    var score: Double
    var snippet: String

    enum CodingKeys: String, CodingKey {
        case id, name, type, status, confidence, score, snippet
    }

    init(id: String, name: String, type: EntityType, status: EntityStatus,
         confidence: Double, score: Double, snippet: String) {
        self.id = id
        self.name = name
        self.type = type
        self.status = status
        self.confidence = confidence
        self.score = score
        self.snippet = snippet
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        type = (try? c.decode(EntityType.self, forKey: .type)) ?? .unknown
        status = (try? c.decode(EntityStatus.self, forKey: .status)) ?? .active
        confidence = try c.decodeIfPresent(Double.self, forKey: .confidence) ?? 0
        score = try c.decodeIfPresent(Double.self, forKey: .score) ?? 0
        snippet = try c.decodeIfPresent(String.self, forKey: .snippet) ?? ""
    }
}

struct GraphSearchResponse: Codable {
    let results: [GraphSearchHit]
}
