import Foundation

// G198 (owner ruling 2026-10-14) — who wrote each part of a page, when and why: `GET /entities/{id}/blame`, read from
// git by the backend (`page_blame`) and never stored. Not a Store domain: fetched when "Where this comes from" shows,
// cached in memory by `ProvenanceCache` (R-PB11). Every decoder is tolerant: a field an older or newer backend leaves
// out decodes to its empty value, never a failed section.

/// One commit that wrote lines of the page.
struct PageBlameCommit: Decodable, Equatable, Identifiable {
    var hash: String
    var date: String
    var subject: String
    var author: String
    var authorKind: String?
    var authorProvider: String?
    /// An agent edit's reason (its commit's `Reason:` line); nil for every other commit.
    var reason: String?
    var trigger: String?
    /// "user" when the person applied an agent's proposed edit (the commit names both).
    var acceptedBy: String?

    var id: String { hash }

    enum CodingKeys: String, CodingKey {
        case hash, date, subject, author, authorKind, authorProvider, reason, trigger, acceptedBy
    }

    init(hash: String, date: String, subject: String = "", author: String, authorKind: String? = nil,
         authorProvider: String? = nil, reason: String? = nil, trigger: String? = nil, acceptedBy: String? = nil) {
        self.hash = hash
        self.date = date
        self.subject = subject
        self.author = author
        self.authorKind = authorKind
        self.authorProvider = authorProvider
        self.reason = reason
        self.trigger = trigger
        self.acceptedBy = acceptedBy
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        hash = try c.decodeIfPresent(String.self, forKey: .hash) ?? ""
        date = try c.decodeIfPresent(String.self, forKey: .date) ?? ""
        subject = try c.decodeIfPresent(String.self, forKey: .subject) ?? ""
        author = try c.decodeIfPresent(String.self, forKey: .author) ?? "unknown"
        authorKind = try c.decodeIfPresent(String.self, forKey: .authorKind)
        authorProvider = try c.decodeIfPresent(String.self, forKey: .authorProvider)
        reason = try c.decodeIfPresent(String.self, forKey: .reason)
        trigger = try c.decodeIfPresent(String.self, forKey: .trigger)
        acceptedBy = try c.decodeIfPresent(String.self, forKey: .acceptedBy)
    }
}

/// One author's share of a section: how many lines, when they last changed it, and which commits (newest first).
struct PageBlameContributor: Decodable, Equatable, Identifiable {
    var author: String
    var authorKind: String?
    var authorProvider: String?
    var lines: Int
    var lastDate: String?
    var commits: [String]

    var id: String { author }

    enum CodingKeys: String, CodingKey { case author, authorKind, authorProvider, lines, lastDate, commits }

    init(author: String, authorKind: String? = nil, authorProvider: String? = nil, lines: Int = 0,
         lastDate: String? = nil, commits: [String] = []) {
        self.author = author
        self.authorKind = authorKind
        self.authorProvider = authorProvider
        self.lines = lines
        self.lastDate = lastDate
        self.commits = commits
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        author = try c.decodeIfPresent(String.self, forKey: .author) ?? "unknown"
        authorKind = try c.decodeIfPresent(String.self, forKey: .authorKind)
        authorProvider = try c.decodeIfPresent(String.self, forKey: .authorProvider)
        lines = try c.decodeIfPresent(Int.self, forKey: .lines) ?? 0
        lastDate = try c.decodeIfPresent(String.self, forKey: .lastDate)
        commits = try c.decodeIfPresent([String].self, forKey: .commits) ?? []
    }
}

/// One section of the page's prose: an H2 title, "Article › <title>" for an article section, "(lead)" before any
/// heading.
struct PageBlameSection: Decodable, Equatable, Identifiable {
    var title: String
    var lineStart: Int
    var lineEnd: Int
    var contributors: [PageBlameContributor]

    var id: String { title }

    enum CodingKeys: String, CodingKey { case title, lineStart, lineEnd, contributors }

    init(title: String, lineStart: Int = 0, lineEnd: Int = 0, contributors: [PageBlameContributor] = []) {
        self.title = title
        self.lineStart = lineStart
        self.lineEnd = lineEnd
        self.contributors = contributors
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        lineStart = try c.decodeIfPresent(Int.self, forKey: .lineStart) ?? 0
        lineEnd = try c.decodeIfPresent(Int.self, forKey: .lineEnd) ?? 0
        contributors = try c.decodeIfPresent([PageBlameContributor].self, forKey: .contributors) ?? []
    }
}

struct PageBlame: Decodable, Equatable {
    var entityId: String
    var commits: [PageBlameCommit]
    var sections: [PageBlameSection]
    var uncommittedLines: Int

    enum CodingKeys: String, CodingKey { case entityId, commits, sections, uncommittedLines }

    init(entityId: String, commits: [PageBlameCommit] = [], sections: [PageBlameSection] = [],
         uncommittedLines: Int = 0) {
        self.entityId = entityId
        self.commits = commits
        self.sections = sections
        self.uncommittedLines = uncommittedLines
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entityId = try c.decodeIfPresent(String.self, forKey: .entityId) ?? ""
        commits = try c.decodeIfPresent([PageBlameCommit].self, forKey: .commits) ?? []
        sections = try c.decodeIfPresent([PageBlameSection].self, forKey: .sections) ?? []
        uncommittedLines = try c.decodeIfPresent(Int.self, forKey: .uncommittedLines) ?? 0
    }

    func commit(_ hash: String) -> PageBlameCommit? { commits.first { $0.hash == hash } }
}

/// The words "Who wrote it" says — pure and tested, so the row, its help and its accessibility label agree.
enum PageBlameWords {
    /// What the backend calls a line git has not seen yet (`page_blame.UNCOMMITTED`).
    static let uncommitted = "uncommitted"
    /// At most this many authors per section; the rest are counted in words.
    static let visibleContributors = 3

    /// Sections that have at least one written line, in page order.
    static func sections(_ blame: PageBlame) -> [PageBlameSection] {
        blame.sections.filter { !$0.contributors.isEmpty }
    }

    /// The section's title as the card reads it: "(lead)" is the opening text before any heading.
    static func title(_ section: PageBlameSection) -> String {
        section.title == "(lead)" ? Copy.PageEdits.lead : section.title
    }

    /// A contributor's name: the one naming rule every other provenance surface uses (`ContributorIdentity`).
    static func name(_ c: PageBlameContributor) -> String {
        if c.author == uncommitted || c.authorKind == uncommitted { return Copy.PageEdits.notSavedYet }
        return ContributorIdentity.displayName(author: c.author,
                                               kind: ContributorIdentity.kind(author: c.author, serverKind: c.authorKind))
    }

    /// "12 lines · 14 Oct" — how much and when last (DR-58: the day as stored, formatted when read).
    static func detail(_ c: PageBlameContributor, locale: Locale = .autoupdatingCurrent) -> String {
        var parts = [Copy.PageEdits.lines(c.lines)]
        if let day = EntityDates.shortDay(c.lastDate, locale: locale) { parts.append(day) }
        return parts.joined(separator: " · ")
    }

    /// The reason of this contributor's newest commit that gave one (an agent edit), with "accepted by you" when the
    /// person applied it from the inbox. Nil when none of their commits carries a reason.
    static func reason(_ c: PageBlameContributor, in blame: PageBlame) -> String? {
        for hash in c.commits {
            guard let commit = blame.commit(hash), let reason = commit.reason?.trimmingCharacters(in: .whitespaces),
                  !reason.isEmpty else { continue }
            return commit.acceptedBy == "user" ? Copy.PageEdits.reasonAccepted(reason) : Copy.PageEdits.reason(reason)
        }
        return nil
    }

    static func visible(_ section: PageBlameSection) -> [PageBlameContributor] {
        Array(section.contributors.prefix(visibleContributors))
    }

    static func more(_ section: PageBlameSection) -> String? {
        let hidden = section.contributors.count - visibleContributors
        return hidden > 0 ? Copy.PageEdits.moreWriters(hidden) : nil
    }
}
