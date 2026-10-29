import Foundation

/// Owner ruling 44 (G121) — why the page matters to the person, derived by the backend on every read
/// (`page_relevance`): `tense` is self | is | will_be | was | none, `line` the sentence. Never stored.
struct EntityRelevance: Codable, Equatable {
    var tense: String
    var line: String
    var conversations: Int = 0
    var lastMentioned: String = ""

    enum CodingKeys: String, CodingKey { case tense, line, conversations, lastMentioned }

    init(tense: String, line: String, conversations: Int = 0, lastMentioned: String = "") {
        self.tense = tense
        self.line = line
        self.conversations = conversations
        self.lastMentioned = lastMentioned
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        tense = try c.decodeIfPresent(String.self, forKey: .tense) ?? "none"
        line = try c.decodeIfPresent(String.self, forKey: .line) ?? ""
        conversations = (try? c.decodeIfPresent(Int.self, forKey: .conversations)) ?? 0
        lastMentioned = (try? c.decodeIfPresent(String.self, forKey: .lastMentioned)) ?? ""
    }

    /// The one line the card shows under the summary — none on the owner's own page ("This is you." repeats the
    /// name's "(you)", DR-38) and none when the backend sent no words.
    var shownLine: String? {
        let text = line.trimmingCharacters(in: .whitespacesAndNewlines)
        return tense == "self" || text.isEmpty ? nil : text
    }
}

/// Vision item 5 (2026-10-28) — what a page holds, from `GET /entities/{id}`'s `blocks` (`page_blocks.build`). `order`
/// names the blocks present, in the order a page reads them; each present block's data rides its own key. Decoded
/// tolerantly: a block this app does not know is ignored, a malformed one is nil. The wire is pinned on both sides by
/// `api/tests/fixtures/page_blocks.json` (`PageBlocksTests`). The entity card draws them in DR-78's order (ruling 48).
struct PageBlocks: Codable, Equatable {
    struct Ongoing: Codable, Equatable {
        var claimId: String
        var kind: String
        var status: String
        var text: String
        var since: String?
        var target: String?
        var verbatim: Bool?
    }

    struct Coordinates: Codable, Equatable {
        var lat: Double
        var lon: Double
        var label: String?
        var source: String?
        /// Part B (2026-10-29): who placed it — `geocoder` (the Mac's own) or `person`; nil when written by hand.
        var by: String?
    }

    struct Look: Codable, Equatable {
        var id: String
        var title: String?
        var site: String?
        var day: String?
        var palette: [String]?
        var fonts: [String]?
        var image: String?
    }

    struct Source: Codable, Equatable {
        var ref: String
        var kind: String?
        var label: String?
        var linkKind: String?
        var state: String
        var site: String?
        var checkedAt: String?
        var addedBy: String?
        var iconSite: String?
    }

    struct Sources: Codable, Equatable {
        var total: Int
        var proposed: Int?
        var tracked: Int?
        var items: [Source]?
    }

    struct Contributor: Codable, Equatable {
        var author: String
        var kind: String?
        var provider: String?
        var changes: Int?
        var last: String?
    }

    struct History: Codable, Equatable {
        var changes: Int
        var truncated: Bool?
        var bySleep: Int?
        var lastChange: String?
        var contributors: [Contributor]?
    }

    /// Ruling 48 (16), DR-80 — the article's citations (`page_citations`): one marker per cited line, at the line's end
    /// (an offset into the served prose, the same offsets as `WikiRow.source`), each naming the numbered sources it
    /// cites; the first six References; the counts behind References' closing line; and, on a page whose prose cites
    /// nothing yet, its beliefs as sentences. A marker's popover is read lazily (`GET /entities/{id}/citations/{n}`).
    struct Citations: Codable, Equatable {
        struct Marker: Equatable, Hashable {
            /// Where the cited line ends, in the served prose.
            var at: Int
            var refs: [Int]
        }

        struct Ref: Codable, Equatable, Identifiable {
            var n: Int
            var kind: String
            var title: String?
            var origin: String?
            var harness: String?
            var correspondent: String?
            var first: String?
            var last: String?
            var episodeId: String?
            var conversationId: String?

            var id: Int { n }
        }

        struct Belief: Codable, Equatable, Identifiable {
            var claimId: String
            var text: String
            var refs: [Int]
            var until: String?
            var inferred: Bool
            var verbatim: Bool

            var id: String { claimId }

            init(claimId: String, text: String, refs: [Int] = [], until: String? = nil, inferred: Bool = false,
                 verbatim: Bool = false) {
                self.claimId = claimId
                self.text = text
                self.refs = refs
                self.until = until
                self.inferred = inferred
                self.verbatim = verbatim
            }

            init(from decoder: Decoder) throws {
                let c = try decoder.container(keyedBy: CodingKeys.self)
                claimId = try c.decode(String.self, forKey: .claimId)
                text = (try? c.decodeIfPresent(String.self, forKey: .text)) ?? ""
                refs = (try? c.decodeIfPresent([Int].self, forKey: .refs)) ?? []
                until = (try? c.decodeIfPresent(String.self, forKey: .until)) ?? nil
                inferred = (try? c.decodeIfPresent(Bool.self, forKey: .inferred)) ?? false
                verbatim = (try? c.decodeIfPresent(Bool.self, forKey: .verbatim)) ?? false
            }
        }

        var markers: [Marker]
        var markersTotal: Int
        var refs: [Ref]
        var total: Int
        var conversations: Int
        var web: Int
        var pages: Int
        var beliefs: [Belief]
        /// Nil: part of the page's beliefs is in its claims ledger, which a card read never opens — "more", no count.
        var beliefsTotal: Int?

        enum CodingKeys: String, CodingKey {
            case markers, markersTotal, refs, total, conversations, web, pages, beliefs, beliefsTotal
        }

        init(markers: [Marker] = [], markersTotal: Int = 0, refs: [Ref] = [], total: Int = 0, conversations: Int = 0,
             web: Int = 0, pages: Int = 0, beliefs: [Belief] = [], beliefsTotal: Int? = 0) {
            self.markers = markers
            self.markersTotal = markersTotal
            self.refs = refs
            self.total = total
            self.conversations = conversations
            self.web = web
            self.pages = pages
            self.beliefs = beliefs
            self.beliefsTotal = beliefsTotal
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            // `[offset, n, …]` on the wire: compact, since an owner-sized page cites thousands of lines.
            let raw = (try? c.decodeIfPresent([[Int]].self, forKey: .markers)) ?? []
            markers = raw.compactMap { row in
                guard let at = row.first, row.count > 1 else { return nil }
                return Marker(at: at, refs: Array(row.dropFirst()))
            }
            markersTotal = (try? c.decodeIfPresent(Int.self, forKey: .markersTotal)) ?? markers.count
            refs = (try? c.decodeIfPresent([Ref].self, forKey: .refs)) ?? []
            total = (try? c.decodeIfPresent(Int.self, forKey: .total)) ?? refs.count
            conversations = (try? c.decodeIfPresent(Int.self, forKey: .conversations)) ?? 0
            web = (try? c.decodeIfPresent(Int.self, forKey: .web)) ?? 0
            pages = (try? c.decodeIfPresent(Int.self, forKey: .pages)) ?? 0
            beliefs = (try? c.decodeIfPresent([Belief].self, forKey: .beliefs)) ?? []
            beliefsTotal = c.contains(.beliefsTotal)
                ? ((try? c.decodeIfPresent(Int.self, forKey: .beliefsTotal)) ?? nil) : beliefs.count
        }

        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(markers.map { [$0.at] + $0.refs }, forKey: .markers)
            try c.encode(markersTotal, forKey: .markersTotal)
            try c.encode(refs, forKey: .refs)
            try c.encode(total, forKey: .total)
            try c.encode(conversations, forKey: .conversations)
            try c.encode(web, forKey: .web)
            try c.encode(pages, forKey: .pages)
            try c.encode(beliefs, forKey: .beliefs)
            try c.encode(beliefsTotal, forKey: .beliefsTotal)
        }

        /// The markers whose line ends inside `range` (a `WikiRow.source`): a line's own markers, never its neighbour's.
        func markers(endingIn range: Range<Int>) -> [Marker] {
            markers.filter { $0.at > range.lowerBound && $0.at <= range.upperBound }
        }
    }

    var shape: String
    var order: [String]
    var relevance: EntityRelevance?
    /// "In short" (ruling 48 part 5): Sleep's 2–3 sentences on a long, busy page (`in_short`). Never hand-edited.
    var summary: InShort?
    var ongoing: [Ongoing]
    var ongoingTotal: Int
    var coordinates: Coordinates?
    var looks: [Look]
    var sources: Sources?
    var citations: Citations?
    var history: History?

    enum CodingKeys: String, CodingKey {
        case shape, order, relevance, summary, ongoing, ongoingTotal, coordinates, looks, sources, citations, history
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        shape = (try? c.decodeIfPresent(String.self, forKey: .shape)) ?? ""
        order = (try? c.decodeIfPresent([String].self, forKey: .order)) ?? []
        relevance = (try? c.decodeIfPresent(EntityRelevance.self, forKey: .relevance)) ?? nil
        summary = (try? c.decodeIfPresent(InShort.self, forKey: .summary)) ?? nil
        ongoing = (try? c.decodeIfPresent([Ongoing].self, forKey: .ongoing)) ?? []
        ongoingTotal = (try? c.decodeIfPresent(Int.self, forKey: .ongoingTotal)) ?? ongoing.count
        coordinates = (try? c.decodeIfPresent(Coordinates.self, forKey: .coordinates)) ?? nil
        looks = (try? c.decodeIfPresent([Look].self, forKey: .looks)) ?? []
        sources = (try? c.decodeIfPresent(Sources.self, forKey: .sources)) ?? nil
        citations = (try? c.decodeIfPresent(Citations.self, forKey: .citations)) ?? nil
        history = (try? c.decodeIfPresent(History.self, forKey: .history)) ?? nil
    }
}

/// A citation marker's popover (`GET /entities/{id}/citations/{n}`, DR-80): the reference, the best evidence row's kind,
/// and its located words with the cited span (DR-18). Read when the person opens a marker, never on card open.
struct PageCitationDetail: Codable, Equatable {
    var n: Int
    var kind: String
    var title: String?
    var origin: String?
    var harness: String?
    var correspondent: String?
    var first: String?
    var last: String?
    var episodeId: String?
    var conversationId: String?
    var evidenceKind: String?
    var status: String?
    var span: ProvenanceSpan?
    var lines: Int?
}
