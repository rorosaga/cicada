import Foundation

/// ROR-16, G118 — the one wire shape of "this part of this source" (`source_spans`, `SourceSpan` in `schemas.py`): the
/// server judges a stored span against the source as it is now, and only what may be drawn carries an `at`.
struct SourceSpan: Codable, Hashable {
    /// Where in the source. Text is the only medium drawn today; a time range for a recording or a page of a PDF would
    /// arrive as another `type`, which an older app reads as `.other`: it opens the source and draws no highlight.
    enum Place: Codable, Hashable {
        case text(start: Int, end: Int)
        case other(String)

        private enum Keys: String, CodingKey { case type, start, end }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            let type = try c.decodeIfPresent(String.self, forKey: .type) ?? "text"
            if type == "text", let start = try c.decodeIfPresent(Int.self, forKey: .start),
               let end = try c.decodeIfPresent(Int.self, forKey: .end) {
                self = .text(start: start, end: end)
            } else {
                self = .other(type)
            }
        }

        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: Keys.self)
            switch self {
            case let .text(start, end):
                try c.encode("text", forKey: .type)
                try c.encode(start, forKey: .start)
                try c.encode(end, forKey: .end)
            case let .other(type):
                try c.encode(type, forKey: .type)
            }
        }
    }

    enum Status: Hashable, Codable {
        case current, grown, derived, stale, held, unlocated
        /// A status a later backend adds: nothing is drawn from it.
        case other(String)

        init(from decoder: Decoder) throws {
            let raw = try decoder.singleValueContainer().decode(String.self)
            switch raw {
            case "current": self = .current
            case "grown": self = .grown
            case "derived": self = .derived
            case "stale": self = .stale
            case "held": self = .held
            case "unlocated": self = .unlocated
            default: self = .other(raw)
            }
        }

        func encode(to encoder: Encoder) throws {
            var c = encoder.singleValueContainer()
            switch self {
            case .current: try c.encode("current")
            case .grown: try c.encode("grown")
            case .derived: try c.encode("derived")
            case .stale: try c.encode("stale")
            case .held: try c.encode("held")
            case .unlocated: try c.encode("unlocated")
            case let .other(raw): try c.encode(raw)
            }
        }
    }

    let source: String
    let status: Status
    let kind: String
    let hash: String
    let at: Place?
    let claimId: String?
    /// The claim's, not the span's: whether it is still believed.
    let current: Bool

    private enum CodingKeys: String, CodingKey { case source, status, kind, hash, at, claimId, current }

    init(source: String, status: Status, kind: String = "user", hash: String = "", at: Place? = nil,
         claimId: String? = nil, current: Bool = true) {
        self.source = source
        self.status = status
        self.kind = kind
        self.hash = hash
        self.at = at
        self.claimId = claimId
        self.current = current
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        source = try c.decode(String.self, forKey: .source)
        status = try c.decodeIfPresent(Status.self, forKey: .status) ?? .current
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "user"
        hash = try c.decodeIfPresent(String.self, forKey: .hash) ?? ""
        at = try c.decodeIfPresent(Place.self, forKey: .at)
        claimId = try c.decodeIfPresent(String.self, forKey: .claimId)
        current = try c.decodeIfPresent(Bool.self, forKey: .current) ?? true
    }

    /// The offsets to wash, only for a status that may draw and a place this app can draw.
    var range: Range<Int>? {
        switch status {
        case .current, .grown, .derived: break
        default: return nil
        }
        guard case let .text(start, end)? = at, start >= 0, end > start else { return nil }
        return start..<end
    }
}

/// `GET /episodes/{id}/spans`: every span pointing into one source, grouped by page. Not a Store domain: read on demand
/// through `ProvenanceCache`, revalidated by its ETag.
struct SourceSpans: Codable, Hashable {
    struct Group: Codable, Hashable, Identifiable {
        let page: String
        let name: String
        let type: String
        let spans: [SourceSpan]
        var id: String { page }
    }

    let source: String
    let sourceKind: String
    let hash: String
    let length: Int
    let groups: [Group]

    /// Every place to wash, for `SourceSpansView.others`; duplicates fold.
    var ranges: [Range<Int>] {
        var seen = Set<Range<Int>>()
        return groups.flatMap(\.spans).compactMap(\.range).filter { seen.insert($0).inserted }
            .sorted { ($0.lowerBound, $0.upperBound) < ($1.lowerBound, $1.upperBound) }
    }
}

/// What a source is (`source_spans.kind_of`), for the words a citation opens it with.
enum SourceKind {
    static let conversation = "conversation", meeting = "meeting", note = "note", book = "book", save = "save"

    /// A source with turns to count and name. Anything else is one document: it has no "turn 1".
    static func hasTurns(_ kind: String?) -> Bool { kind == nil || kind == conversation || kind == meeting }
    /// One written thing the person keeps: its only turn is not "You".
    static func isOwnDocument(_ kind: String?) -> Bool { kind == note || kind == book || kind == save }
}
