import Foundation

/// G133 — what a Feed row needs to show a paper's byline and to be found by
/// author, arXiv id or DOI (R7 §5.2). Optional everywhere: a non-paper row and
/// an older backend carry none of it.
struct PaperSummary: Codable, Equatable, Hashable {
    var authors: [String]
    var arxivId: String?
    var doi: String?
    var published: String?
    var venue: String?

    enum CodingKeys: String, CodingKey { case authors, arxivId, doi, published, venue }

    init(authors: [String] = [], arxivId: String? = nil, doi: String? = nil, published: String? = nil,
         venue: String? = nil) {
        self.authors = authors; self.arxivId = arxivId; self.doi = doi; self.published = published; self.venue = venue
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        authors = try c.decodeIfPresent([String].self, forKey: .authors) ?? []
        arxivId = try c.decodeIfPresent(String.self, forKey: .arxivId)
        doi = try c.decodeIfPresent(String.self, forKey: .doi)
        published = try c.decodeIfPresent(String.self, forKey: .published)
        venue = try c.decodeIfPresent(String.self, forKey: .venue)
    }
}

/// One personal-tier reason a paper is in memory, as a span into the person's
/// own file (G118 / G121): the snippet, where the words sit in it, the file,
/// the heading above, and the file's date.
///
/// Only `predicate` and `episode` are required on the wire; every other field
/// decodes with a default (the Global Constraints' decode-tolerance rule), so
/// a span the server could not fully resolve still renders as a plain quote
/// instead of dropping the whole card.
struct PaperWhyItem: Codable, Equatable, Identifiable {
    var predicate: String
    var text: String?
    var target: String?
    var snippet: String
    var highlightStart: Int
    var highlightEnd: Int
    var file: String?
    var heading: String?
    var edited: String?
    var kind: String
    var episode: String
    var start: Int
    var end: Int
    var stale: Bool

    var id: String { "\(predicate)|\(episode)|\(start)" }

    enum CodingKeys: String, CodingKey {
        case predicate, text, target, snippet, highlightStart, highlightEnd, file, heading, edited
        case kind, episode, start, end, stale
    }

    init(predicate: String, text: String? = nil, target: String? = nil, snippet: String = "",
         highlightStart: Int = -1, highlightEnd: Int = -1, file: String? = nil, heading: String? = nil,
         edited: String? = nil, kind: String = "user", episode: String, start: Int = -1, end: Int = -1,
         stale: Bool = false) {
        self.predicate = predicate; self.text = text; self.target = target; self.snippet = snippet
        self.highlightStart = highlightStart; self.highlightEnd = highlightEnd; self.file = file
        self.heading = heading; self.edited = edited; self.kind = kind; self.episode = episode
        self.start = start; self.end = end; self.stale = stale
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        predicate = try c.decode(String.self, forKey: .predicate)
        text = try c.decodeIfPresent(String.self, forKey: .text)
        target = try c.decodeIfPresent(String.self, forKey: .target)
        snippet = try c.decodeIfPresent(String.self, forKey: .snippet) ?? ""
        // -1 is "no highlight": `PaperCard.highlighted` shows the sentence plainly.
        highlightStart = try c.decodeIfPresent(Int.self, forKey: .highlightStart) ?? -1
        highlightEnd = try c.decodeIfPresent(Int.self, forKey: .highlightEnd) ?? -1
        file = try c.decodeIfPresent(String.self, forKey: .file)
        heading = try c.decodeIfPresent(String.self, forKey: .heading)
        edited = try c.decodeIfPresent(String.self, forKey: .edited)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "user"
        episode = try c.decode(String.self, forKey: .episode)
        start = try c.decodeIfPresent(Int.self, forKey: .start) ?? -1
        end = try c.decodeIfPresent(Int.self, forKey: .end) ?? -1
        stale = try c.decodeIfPresent(Bool.self, forKey: .stale) ?? false
    }
}

/// `GET /entities/{id}/paper` — the card's two tiers (G121): why, then context.
/// `entityId` is the one required key; the lists, the flag and the title
/// default, so an older or newer backend still yields a card.
struct PaperDetail: Codable, Equatable {
    var entityId: String
    var title: String
    var authors: [String]
    var venue: String?
    var published: String?
    var arxivId: String?
    var doi: String?
    var absUrl: String?
    var doiUrl: String?
    var sections: [String]
    var why: [PaperWhyItem]
    var agentOnly: Bool
    var context: String?
    var contextSource: String?
    var contextAsOf: String?

    enum CodingKeys: String, CodingKey {
        case entityId, title, authors, venue, published, arxivId, doi, absUrl, doiUrl, sections, why
        case agentOnly, context, contextSource, contextAsOf
    }

    init(entityId: String, title: String = "", authors: [String] = [], venue: String? = nil,
         published: String? = nil, arxivId: String? = nil, doi: String? = nil, absUrl: String? = nil,
         doiUrl: String? = nil, sections: [String] = [], why: [PaperWhyItem] = [], agentOnly: Bool = false,
         context: String? = nil, contextSource: String? = nil, contextAsOf: String? = nil) {
        self.entityId = entityId; self.title = title; self.authors = authors; self.venue = venue
        self.published = published; self.arxivId = arxivId; self.doi = doi; self.absUrl = absUrl
        self.doiUrl = doiUrl; self.sections = sections; self.why = why; self.agentOnly = agentOnly
        self.context = context; self.contextSource = contextSource; self.contextAsOf = contextAsOf
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decode(String.self, forKey: .entityId)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? entityId
        authors = try c.decodeIfPresent([String].self, forKey: .authors) ?? []
        venue = try c.decodeIfPresent(String.self, forKey: .venue)
        published = try c.decodeIfPresent(String.self, forKey: .published)
        arxivId = try c.decodeIfPresent(String.self, forKey: .arxivId)
        doi = try c.decodeIfPresent(String.self, forKey: .doi)
        absUrl = try c.decodeIfPresent(String.self, forKey: .absUrl)
        doiUrl = try c.decodeIfPresent(String.self, forKey: .doiUrl)
        sections = try c.decodeIfPresent([String].self, forKey: .sections) ?? []
        why = try c.decodeIfPresent([PaperWhyItem].self, forKey: .why) ?? []
        agentOnly = try c.decodeIfPresent(Bool.self, forKey: .agentOnly) ?? false
        context = try c.decodeIfPresent(String.self, forKey: .context)
        contextSource = try c.decodeIfPresent(String.self, forKey: .contextSource)
        contextAsOf = try c.decodeIfPresent(String.self, forKey: .contextAsOf)
    }
}
