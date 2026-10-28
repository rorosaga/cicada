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
/// `api/tests/fixtures/page_blocks.json` (`PageBlocksTests`). The layout that draws them waits on a design decision;
/// today the card shows only `relevance`'s line.
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

    var shape: String
    var order: [String]
    var relevance: EntityRelevance?
    var ongoing: [Ongoing]
    var ongoingTotal: Int
    var coordinates: Coordinates?
    var looks: [Look]
    var sources: Sources?
    var history: History?

    enum CodingKeys: String, CodingKey {
        case shape, order, relevance, ongoing, ongoingTotal, coordinates, looks, sources, history
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        shape = (try? c.decodeIfPresent(String.self, forKey: .shape)) ?? ""
        order = (try? c.decodeIfPresent([String].self, forKey: .order)) ?? []
        relevance = (try? c.decodeIfPresent(EntityRelevance.self, forKey: .relevance)) ?? nil
        ongoing = (try? c.decodeIfPresent([Ongoing].self, forKey: .ongoing)) ?? []
        ongoingTotal = (try? c.decodeIfPresent(Int.self, forKey: .ongoingTotal)) ?? ongoing.count
        coordinates = (try? c.decodeIfPresent(Coordinates.self, forKey: .coordinates)) ?? nil
        looks = (try? c.decodeIfPresent([Look].self, forKey: .looks)) ?? []
        sources = (try? c.decodeIfPresent(Sources.self, forKey: .sources)) ?? nil
        history = (try? c.decodeIfPresent(History.self, forKey: .history)) ?? nil
    }
}
