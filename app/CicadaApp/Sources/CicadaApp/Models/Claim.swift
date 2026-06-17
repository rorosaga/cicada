import Foundation

// MARK: - Observer

/// Who holds a belief. Drives the observer filter + badges. `external:<name>` is
/// the high-value media/RSS provenance case (an opaque associated value here so
/// we keep the closed core + open tail without losing the name on the wire).
enum Observer: Codable, Hashable, Identifiable {
    case agent
    case rodrigo
    case external(String)           // "external:karpathy-talk" → .external("karpathy-talk")

    var id: String { wire }

    var wire: String {
        switch self {
        case .agent: return "agent"
        case .rodrigo: return "rodrigo"
        case .external(let n): return "external:\(n)"
        }
    }

    init(wire: String) {
        switch wire {
        case "agent": self = .agent
        case "rodrigo": self = .rodrigo
        default:
            self = wire.hasPrefix("external:")
                ? .external(String(wire.dropFirst("external:".count)))
                : .external(wire)
        }
    }

    init(from d: Decoder) throws { self.init(wire: try d.singleValueContainer().decode(String.self)) }
    func encode(to e: Encoder) throws { var c = e.singleValueContainer(); try c.encode(wire) }

    var label: String {
        switch self {
        case .agent: return "Cicada"
        case .rodrigo: return "Rodrigo"
        case .external(let n): return n
        }
    }

    var sfSymbol: String {
        switch self {
        case .agent: return "cpu"
        case .rodrigo: return "person.fill"
        case .external: return "quote.bubble.fill"
        }
    }
}

// MARK: - Epistemic + SourceTrust

/// How a belief was arrived at. Drives decay; small closed enum with a
/// forward-compat `.unknown` fallback (same tolerance pattern as `EntityType`).
enum Epistemic: String, Codable {
    case explicit, deductive, inductive, abductive, unknown
    init(from d: Decoder) throws {
        self = Epistemic(rawValue: (try? d.singleValueContainer().decode(String.self)) ?? "") ?? .unknown
    }
}

/// Source-trust axis — ORTHOGONAL to `confidence`. Closed enum with a
/// forward-compat fallback.
enum SourceTrust: String, Codable {
    case userStated = "user_stated"
    case agentExtracted = "agent_extracted"
    case agentReflected = "agent_reflected"
    case external
    case unknown
    init(from d: Decoder) throws {
        self = SourceTrust(rawValue: (try? d.singleValueContainer().decode(String.self)) ?? "") ?? .unknown
    }

    var label: String {
        switch self {
        case .userStated: return "user stated"
        case .agentExtracted: return "agent extracted"
        case .agentReflected: return "agent reflected"
        case .external: return "external"
        case .unknown: return "unknown"
        }
    }
}

// MARK: - Claim

/// The atom of the CPCG claim layer. Mirrors the in-page ` ```claims ` YAML
/// schema on the wire as camelCase; decodes defensively (`decodeIfPresent`)
/// exactly like `Entity` / `GraphNode` / `MediaFeedItem` so an older backend
/// (one that doesn't yet emit claims) never blanks a view.
struct Claim: Identifiable, Codable, Hashable {
    let id: String                    // clm_2026-05-05_009
    let text: String
    let subject: String
    let predicate: String
    let object: String
    let objectKind: String            // "node" | "literal"
    let observer: Observer
    let context: String               // engineering|family|… (OPEN; default "general")
    let epistemic: Epistemic
    let sourceTrust: SourceTrust
    let confidence: Double
    let validFrom: String
    let validTo: String?              // nil = currently valid
    let supersededBy: String?
    let supersedes: String?
    let sourceEpisodes: [String]
    let premises: [String]
    let authoredBy: String            // model id or "user" — same vocabulary as Contributor.author

    var isValid: Bool { validTo == nil }

    enum CodingKeys: String, CodingKey {
        case id, text, subject, predicate, object, objectKind, observer, context
        case epistemic, sourceTrust, confidence, validFrom, validTo
        case supersededBy, supersedes, sourceEpisodes, premises, authoredBy
    }

    init(from c: Decoder) throws {
        let k = try c.container(keyedBy: CodingKeys.self)
        id = try k.decode(String.self, forKey: .id)
        text = try k.decodeIfPresent(String.self, forKey: .text) ?? ""
        subject = try k.decodeIfPresent(String.self, forKey: .subject) ?? ""
        predicate = try k.decodeIfPresent(String.self, forKey: .predicate) ?? ""
        object = try k.decodeIfPresent(String.self, forKey: .object) ?? ""
        objectKind = try k.decodeIfPresent(String.self, forKey: .objectKind) ?? "literal"
        observer = try k.decodeIfPresent(Observer.self, forKey: .observer) ?? .agent
        context = try k.decodeIfPresent(String.self, forKey: .context) ?? "general"
        epistemic = try k.decodeIfPresent(Epistemic.self, forKey: .epistemic) ?? .unknown
        sourceTrust = try k.decodeIfPresent(SourceTrust.self, forKey: .sourceTrust) ?? .unknown
        confidence = try k.decodeIfPresent(Double.self, forKey: .confidence) ?? 0
        validFrom = try k.decodeIfPresent(String.self, forKey: .validFrom) ?? ""
        validTo = try k.decodeIfPresent(String.self, forKey: .validTo)
        supersededBy = try k.decodeIfPresent(String.self, forKey: .supersededBy)
        supersedes = try k.decodeIfPresent(String.self, forKey: .supersedes)
        sourceEpisodes = try k.decodeIfPresent([String].self, forKey: .sourceEpisodes) ?? []
        premises = try k.decodeIfPresent([String].self, forKey: .premises) ?? []
        authoredBy = try k.decodeIfPresent(String.self, forKey: .authoredBy) ?? "unknown"
    }
}

// MARK: - Response envelopes

/// `GET /entities/{id}/claims` envelope.
struct ClaimListResponse: Codable {
    let claims: [Claim]

    enum CodingKeys: String, CodingKey { case claims }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        claims = try c.decodeIfPresent([Claim].self, forKey: .claims) ?? []
    }
}

/// `GET /entities/{id}/timeline?predicate=&context=` — claims for one
/// `(subject, predicate, context)` key, newest first, INCLUDING superseded
/// ones (this is the historical view, so `validTo != nil` are included).
struct ClaimTimeline: Codable {
    let subject: String
    let predicate: String
    let context: String
    let claims: [Claim]

    enum CodingKeys: String, CodingKey { case subject, predicate, context, claims }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        subject = try c.decodeIfPresent(String.self, forKey: .subject) ?? ""
        predicate = try c.decodeIfPresent(String.self, forKey: .predicate) ?? ""
        context = try c.decodeIfPresent(String.self, forKey: .context) ?? ""
        claims = try c.decodeIfPresent([Claim].self, forKey: .claims) ?? []
    }
}

/// `GET /transclude?ref=<urlencoded>` — one resolved embed. `resolved == false`
/// → render a soft "missing embed" stub.
struct TransclusionPayload: Codable {
    let kind: String          // "entity" | "facet" | "claim"
    let ref: String
    let title: String
    let summary: String       // generated card line, for entity/facet
    let claims: [Claim]       // Claim[] for facet/claim kinds; [] otherwise
    let resolved: Bool

    enum CodingKeys: String, CodingKey { case kind, ref, title, summary, claims, resolved }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "entity"
        ref = try c.decodeIfPresent(String.self, forKey: .ref) ?? ""
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        summary = try c.decodeIfPresent(String.self, forKey: .summary) ?? ""
        claims = try c.decodeIfPresent([Claim].self, forKey: .claims) ?? []
        resolved = try c.decodeIfPresent(Bool.self, forKey: .resolved) ?? false
    }

    init(kind: String, ref: String, title: String, summary: String, claims: [Claim], resolved: Bool) {
        self.kind = kind
        self.ref = ref
        self.title = title
        self.summary = summary
        self.claims = claims
        self.resolved = resolved
    }
}
