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
        default:
            // G117 R2: the wire protocol reserves exactly "agent" and the
            // "external:" prefix. Everything else — the legacy literal
            // "rodrigo", the fresh-bank keyword "owner", or a name-derived
            // slug like "bob-example" — is the owner's own entity id by
            // construction, whatever this bank's onboarding resolved it to.
            self = wire.hasPrefix("external:")
                ? .external(String(wire.dropFirst("external:".count)))
                : .rodrigo
        }
    }

    init(from d: Decoder) throws { self.init(wire: try d.singleValueContainer().decode(String.self)) }
    func encode(to e: Encoder) throws { var c = e.singleValueContainer(); try c.encode(wire) }

    var label: String {
        switch self {
        case .agent: return "Cicada"
        case .rodrigo: return Copy.you
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

    /// G118 slice 2 (§4.6) — plain words for a non-technical reader. The axis
    /// is unchanged and still orthogonal to confidence; only its name changed.
    var label: String {
        switch self {
        case .userStated: return Copy.Provenance.youToldCicada
        case .agentExtracted: return Copy.Provenance.cicadaNoticed
        case .agentReflected: return Copy.Provenance.cicadaConcluded
        case .external: return Copy.Provenance.fromASource
        case .unknown: return Copy.Provenance.notRecorded
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
    // G118 slice 1 shipped `evidence` on the wire and this model dropped it
    // (CodingKeys never named it). Slice 2 reads it back, with the four author
    // and conversation fields R-PB13 added beside it. All optional-with-default:
    // a legacy claim has no evidence and an older backend none of the rest.
    let evidence: [Evidence]
    let sessionIds: [String]
    let origin: String?
    let recordedAt: String?
    /// `user` | `system` | `model` | `harness` | `unknown`, from the server's
    /// one `git_service.author_identity` rule — nil against an older backend,
    /// where `ContributorIdentity.kind(author:)` falls back to the author id.
    let authorKind: String?
    let authorProvider: String?

    var isValid: Bool { validTo == nil }

    enum CodingKeys: String, CodingKey {
        case id, text, subject, predicate, object, objectKind, observer, context
        case epistemic, sourceTrust, confidence, validFrom, validTo
        case supersededBy, supersedes, sourceEpisodes, premises, authoredBy
        case evidence, sessionIds, origin, recordedAt, authorKind, authorProvider
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
        evidence = try k.decodeIfPresent([Evidence].self, forKey: .evidence) ?? []
        sessionIds = try k.decodeIfPresent([String].self, forKey: .sessionIds) ?? []
        origin = try k.decodeIfPresent(String.self, forKey: .origin)
        recordedAt = try k.decodeIfPresent(String.self, forKey: .recordedAt)
        // The server defaults both to "unknown"/null; an older backend omits
        // them. "unknown" from the wire is kept verbatim — it is the server's
        // answer, not a gap.
        authorKind = try k.decodeIfPresent(String.self, forKey: .authorKind)
        authorProvider = try k.decodeIfPresent(String.self, forKey: .authorProvider)
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
    // G11: when the transcluded ref resolves to a media entity, the backend MAY
    // surface the image/thumbnail url here so the card renders the image inline
    // instead of a text summary. Optional + decode-tolerant: nil against a
    // backend that doesn't send it, in which case the card degrades to the
    // existing text summary. (Frontend stream: inert until the backend emits it.)
    let mediaURL: String?
    let mediaType: String?

    enum CodingKeys: String, CodingKey {
        case kind, ref, title, summary, claims, resolved, mediaURL, mediaType
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "entity"
        ref = try c.decodeIfPresent(String.self, forKey: .ref) ?? ""
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        summary = try c.decodeIfPresent(String.self, forKey: .summary) ?? ""
        claims = try c.decodeIfPresent([Claim].self, forKey: .claims) ?? []
        resolved = try c.decodeIfPresent(Bool.self, forKey: .resolved) ?? false
        mediaURL = try c.decodeIfPresent(String.self, forKey: .mediaURL)
        mediaType = try c.decodeIfPresent(String.self, forKey: .mediaType)
    }

    init(
        kind: String, ref: String, title: String, summary: String,
        claims: [Claim], resolved: Bool,
        mediaURL: String? = nil, mediaType: String? = nil
    ) {
        self.kind = kind
        self.ref = ref
        self.title = title
        self.summary = summary
        self.claims = claims
        self.resolved = resolved
        self.mediaURL = mediaURL
        self.mediaType = mediaType
    }
}
