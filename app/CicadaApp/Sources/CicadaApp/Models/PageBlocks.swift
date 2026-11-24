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

    /// What the person marked in a book, word for word (ruling 64). Both words are null for a caller without `sources`.
    struct Marks: Codable, Equatable {
        struct Item: Codable, Equatable {
            var claimId: String
            var day: String?
            var text: String?
            var note: String?
            /// ROR-16 — where the passage stands in the book's record; the Reader's read judges it when opened.
            var evidence: Evidence?
        }

        var items: [Item]
        var total: Int
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

    /// G246 (ruling 81) — what a list of saved posts holds, read from the saves each time the page is served (never stored
    /// on the page): how many, the newest day, when THIS Mac last read the list, a folder's reason in the person's words,
    /// and the address the cards read (`channel`, `stream`, `folder` → `SourceListKey`). `source` is the origin whose real
    /// mark the page wears. `recent` is for agents and the CLI: the app draws its own five cards from the items route.
    struct ListBlock: Codable, Equatable {
        struct Why: Codable, Equatable {
            var text: String
            var at: String?
        }

        var site: String
        var stream: String
        var folder: String?
        var channel: String
        var label: String
        var source: String
        var count: Int
        var newest: String?
        var lastReadAt: String?
        var why: Why?

        enum CodingKeys: String, CodingKey { case site, stream, folder, channel, label, source, count, newest, lastReadAt, why }

        init(site: String = "", stream: String, folder: String? = nil, channel: String = "", label: String = "",
             source: String = "", count: Int = 0, newest: String? = nil, lastReadAt: String? = nil, why: Why? = nil) {
            self.site = site
            self.stream = stream
            self.folder = folder
            self.channel = channel
            self.label = label
            self.source = source
            self.count = count
            self.newest = newest
            self.lastReadAt = lastReadAt
            self.why = why
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            site = (try? c.decodeIfPresent(String.self, forKey: .site)) ?? ""
            stream = try c.decode(String.self, forKey: .stream)
            folder = (try? c.decodeIfPresent(String.self, forKey: .folder)) ?? nil
            channel = (try? c.decodeIfPresent(String.self, forKey: .channel)) ?? ""
            label = (try? c.decodeIfPresent(String.self, forKey: .label)) ?? ""
            source = (try? c.decodeIfPresent(String.self, forKey: .source)) ?? ""
            count = (try? c.decodeIfPresent(Int.self, forKey: .count)) ?? 0
            newest = (try? c.decodeIfPresent(String.self, forKey: .newest)) ?? nil
            lastReadAt = (try? c.decodeIfPresent(String.self, forKey: .lastReadAt)) ?? nil
            why = (try? c.decodeIfPresent(Why.self, forKey: .why)) ?? nil
        }

        /// The key the list's cards and its "All N" read under (`SourceListKey.make`).
        var listKey: String { SourceListKey.make(channel.isEmpty ? site : channel, stream: stream, folder: folder) }
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
            /// G104 slice 3 — every conversation this reference holds was removed from its source (kept as evidence).
            var sourceRemoved: Bool?
            /// G244 — an agent edited a source this reference holds (ruling 76); the server's `editedBy`.
            var editedBy: CorrectedBy?

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
        /// `blocks-7` — the mark each reference wears where it is cited: the distinct keys, and per reference (by number
        /// order, `refMarks[n - 1]`) an index into them. A passage may cite a source past the six References lines; it
        /// still draws its own mark. Empty from an older backend: a cluster then draws nothing for it, never a guess.
        var markKeys: [String]
        var refMarks: [Int]
        var total: Int
        var conversations: Int
        var web: Int
        var pages: Int
        var beliefs: [Belief]
        /// Nil: part of the page's beliefs is in its claims ledger, which a card read never opens — "more", no count.
        var beliefsTotal: Int?

        enum CodingKeys: String, CodingKey {
            case markers, markersTotal, refs, markKeys, refMarks, total, conversations, web, pages, beliefs, beliefsTotal
        }

        init(markers: [Marker] = [], markersTotal: Int = 0, refs: [Ref] = [], markKeys: [String] = [],
             refMarks: [Int] = [], total: Int = 0, conversations: Int = 0,
             web: Int = 0, pages: Int = 0, beliefs: [Belief] = [], beliefsTotal: Int? = 0) {
            self.markers = markers
            self.markersTotal = markersTotal
            self.refs = refs
            self.markKeys = markKeys
            self.refMarks = refMarks
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
            markKeys = (try? c.decodeIfPresent([String].self, forKey: .markKeys)) ?? []
            refMarks = (try? c.decodeIfPresent([Int].self, forKey: .refMarks)) ?? []
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
            try c.encode(markKeys, forKey: .markKeys)
            try c.encode(refMarks, forKey: .refMarks)
            try c.encode(total, forKey: .total)
            try c.encode(conversations, forKey: .conversations)
            try c.encode(web, forKey: .web)
            try c.encode(pages, forKey: .pages)
            try c.encode(beliefs, forKey: .beliefs)
            try c.encode(beliefsTotal, forKey: .beliefsTotal)
        }

        /// The mark key of reference `n` (`blocks-7`), or nil when the backend sent none for it.
        func markKey(forRef n: Int) -> String? {
            guard n >= 1, n <= refMarks.count else { return nil }
            let index = refMarks[n - 1]
            return markKeys.indices.contains(index) ? markKeys[index] : nil
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
    var marks: Marks?
    var coordinates: Coordinates?
    var looks: [Look]
    var sources: Sources?
    var citations: Citations?
    var history: History?
    /// G246 — a list of saved posts' own block; nil on every other page and from an older backend.
    var list: ListBlock?

    enum CodingKeys: String, CodingKey {
        case shape, order, relevance, summary, ongoing, ongoingTotal, marks, coordinates, looks, sources, citations, history, list
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        shape = (try? c.decodeIfPresent(String.self, forKey: .shape)) ?? ""
        order = (try? c.decodeIfPresent([String].self, forKey: .order)) ?? []
        relevance = (try? c.decodeIfPresent(EntityRelevance.self, forKey: .relevance)) ?? nil
        summary = (try? c.decodeIfPresent(InShort.self, forKey: .summary)) ?? nil
        ongoing = (try? c.decodeIfPresent([Ongoing].self, forKey: .ongoing)) ?? []
        ongoingTotal = (try? c.decodeIfPresent(Int.self, forKey: .ongoingTotal)) ?? ongoing.count
        marks = (try? c.decodeIfPresent(Marks.self, forKey: .marks)) ?? nil
        coordinates = (try? c.decodeIfPresent(Coordinates.self, forKey: .coordinates)) ?? nil
        looks = (try? c.decodeIfPresent([Look].self, forKey: .looks)) ?? []
        sources = (try? c.decodeIfPresent(Sources.self, forKey: .sources)) ?? nil
        citations = (try? c.decodeIfPresent(Citations.self, forKey: .citations)) ?? nil
        history = (try? c.decodeIfPresent(History.self, forKey: .history)) ?? nil
        list = (try? c.decodeIfPresent(ListBlock.self, forKey: .list)) ?? nil
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
    /// ROR-16 — what the source is, so a citation says what it opens.
    var sourceKind: String?
    var evidenceKind: String?
    var status: String?
    var span: ProvenanceSpan?
    var lines: Int?
    /// G104 slice 3 — the source behind this reference was removed; what it taught stays.
    var sourceRemoved: Bool?
    /// G244 — an agent edited the source behind this reference (ruling 76); the server's `editedBy`.
    var editedBy: CorrectedBy?

    /// The popover's correction note: the located span's when its words were changed, else the reference's own record.
    var correctionNote: String? { (span?.correctedBy ?? editedBy)?.note }

    /// Whether the popover says so: the reference's own word, or the located span's.
    var isSourceRemoved: Bool { sourceRemoved == true || span?.sourceRemoved == true }
}
