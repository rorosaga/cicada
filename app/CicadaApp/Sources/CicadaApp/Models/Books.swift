import Foundation

// G39, G233 — the wire shapes of the book routes (`api/routers/books.py`).

struct AppleBooksSettingsReply: Decodable, Equatable, Sendable { let enabled: Bool }

/// `GET /entities/{id}/book-status` (ruling 61): the book's open status record.
struct BookStatusRecord: Decodable, Equatable, Sendable {
    let status: String
    let day: String?
    let claimId: String
    let fromChat: Bool
    /// Where the book came in from ("Apple Books", "Scanned"), in a fixed order; empty from an older backend.
    var ways: [String] = []

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decode(String.self, forKey: .status)
        day = try c.decodeIfPresent(String.self, forKey: .day)
        claimId = try c.decode(String.self, forKey: .claimId)
        fromChat = try c.decode(Bool.self, forKey: .fromChat)
        ways = try c.decodeIfPresent([String].self, forKey: .ways) ?? []
    }

    init(status: String, day: String?, claimId: String, fromChat: Bool, ways: [String] = []) {
        self.status = status; self.day = day; self.claimId = claimId; self.fromChat = fromChat; self.ways = ways
    }

    private enum CodingKeys: String, CodingKey { case status, day, claimId, fromChat, ways }
}

/// `POST /capture/isbn`'s answer: the scan's episode, whose result `GET /sources/books/scans/{id}` tells.
struct BookScanSent: Decodable, Equatable, Sendable {
    let episodeId: String?
    let isbn: String
}

/// `GET /sources/books/scans/{id}`: `waiting` until the number resolves at the home, then the page it landed on —
/// `existing` when that book was already in the bank (another edition, Apple Books, Goodreads).
struct BookScanResult: Decodable, Equatable, Sendable {
    let state: String
    let entityId: String?
    let name: String?
    let existing: Bool?
    /// What the Add shows of the book it found: its authors and its cover (the page's own picture path).
    var authors: [String]? = nil
    var cover: String? = nil
}

/// `GET /entities/{id}/book`: what a book's page leads with. Every field optional: an older backend sends none, and a
/// book the sources know nothing of leaves its line out.
struct BookCard: Decodable, Equatable, Sendable {
    struct Way: Decodable, Equatable, Sendable {
        let door: String
        let label: String
        /// The day the person scanned it (`YYYY-MM-DD`), for the scan alone.
        let day: String?
    }

    var subtitle: String? = nil
    var authors: [String] = []
    var published: String? = nil
    var pages: Int? = nil
    var publisher: String? = nil
    var subjects: [String] = []
    var descriptionSource: String? = nil
    var descriptionAt: String? = nil
    var descriptionUrl: String? = nil
    /// A title found this book (ruling 61, amended 2026-11-06): the box says so and offers "Not this book".
    var matchedByTitle: Bool = false
    var ways: [Way] = []

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        subtitle = try c.decodeIfPresent(String.self, forKey: .subtitle)
        authors = try c.decodeIfPresent([String].self, forKey: .authors) ?? []
        published = try c.decodeIfPresent(String.self, forKey: .published)
        pages = try c.decodeIfPresent(Int.self, forKey: .pages)
        publisher = try c.decodeIfPresent(String.self, forKey: .publisher)
        subjects = try c.decodeIfPresent([String].self, forKey: .subjects) ?? []
        descriptionSource = try c.decodeIfPresent(String.self, forKey: .descriptionSource)
        descriptionAt = try c.decodeIfPresent(String.self, forKey: .descriptionAt)
        descriptionUrl = try c.decodeIfPresent(String.self, forKey: .descriptionUrl)
        matchedByTitle = try c.decodeIfPresent(Bool.self, forKey: .matchedByTitle) ?? false
        ways = try c.decodeIfPresent([Way].self, forKey: .ways) ?? []
    }

    init(subtitle: String? = nil, authors: [String] = [], published: String? = nil, pages: Int? = nil,
         publisher: String? = nil, subjects: [String] = [], ways: [Way] = []) {
        self.subtitle = subtitle; self.authors = authors; self.published = published; self.pages = pages
        self.publisher = publisher; self.subjects = subjects; self.ways = ways
    }

    private enum CodingKeys: String, CodingKey {
        case subtitle, authors, published, pages, publisher, subjects, descriptionSource, descriptionAt
        case descriptionUrl, matchedByTitle, ways
    }

    /// "2019 · 320 pages · Example House": year, pages and publisher on one line; nil when none is known.
    var factsLine: String? {
        let parts = [published, pages.map { $0 == 1 ? "1 page" : "\($0) pages" }, publisher]
            .compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
}

struct BookStatusUndoReply: Decodable, Sendable { let status: String? }

/// `GET /sources/books`: book pages by their current status, and the scans whose number waits for its lookup.
struct BooksSummary: Decodable, Equatable, Sendable {
    let books: Int
    let reading: Int
    let finished: Int
    let want: Int
    let notStarted: Int
    let waiting: Int

    enum CodingKeys: String, CodingKey {
        case books, reading, finished, want, waiting
        case notStarted = "not_started"
    }
}

/// `POST /sources/goodreads/preview` — counts only.
struct GoodreadsPreview: Decodable, Equatable, Sendable {
    let books: Int
    let finished: Int
    let reading: Int
    let want: Int
    let reviews: Int
    let rated: Int
}

struct GoodreadsImportResult: Decodable, Equatable, Sendable {
    let books: Int
    let created: Int
    let updated: Int
    let unchanged: Int
}

/// The Reading pages' lines, pure (`AppleBooksReaderTests`).
enum BooksRowText {
    /// How a book came in, as one small label: "Scanned 5 Nov", "Apple Books", "Goodreads".
    static func way(_ way: BookCard.Way, locale: Locale = .autoupdatingCurrent) -> String {
        guard let day = way.day, let date = dayParser.date(from: day) else { return way.label }
        let f = DateFormatter()
        f.locale = locale
        f.setLocalizedDateFormatFromTemplate("dMMM")
        return "\(way.label) \(f.string(from: date))"
    }

    /// The Add's result line under the title: the authors, and "Already in your books" when the page was there before.
    static func found(authors: [String], existing: Bool) -> String {
        let who = authors.joined(separator: ", ")
        if !existing { return who }
        return who.isEmpty ? "Already in your books" : Copy.bookAddAlready(who)
    }

    private static let dayParser: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    /// "Finished · 20 Oct 2026 · you said so" — `books.STATUS_WORDS`, the day it is dated by, and whose word it is when
    /// it came from a conversation rather than a door.
    static func status(_ record: BookStatusRecord, locale: Locale = .autoupdatingCurrent) -> String {
        let word = Copy.bookStatusWords[record.status] ?? record.status
        let day = EntityDates.day(record.day, locale: locale)
        // Where it came from is said only when there is more than one way in (ROR-116).
        let ways = record.ways.count > 1 ? record.ways.joined(separator: " · ") : nil
        return ([word, day, record.fromChat ? Copy.bookStatusFromChat : nil, ways] as [String?]).compactMap { $0 }
            .joined(separator: " · ")
    }

    /// The connect area's one line (`SourceConnectArea`); `isProblem` when it is the one thing to fix.
    struct Line: Equatable {
        let text: String
        var isProblem = false
    }

    /// Apple Books' line: what the reader is doing, what is in, what a book's cap left out, or its failure. When it
    /// last came in is the status line's. A read that failed at the backend (`lastError`) outranks the counts.
    static func appleBooks(_ status: AppleBooksReader.Status, lastError: String? = nil,
                           locale: Locale = .autoupdatingCurrent) -> Line? {
        switch status {
        case .off: return nil
        case .syncing: return Line(text: Copy.appleBooksSyncing)
        case .failed(let why): return Line(text: why, isProblem: true)
        case .synced(_, let books, let highlights, let notKept):
            if let lastError, !lastError.isEmpty { return Line(text: lastError, isProblem: true) }
            let line = Copy.appleBooksHolds(books: books, highlights: highlights, locale: locale)
            return Line(text: notKept > 0 ? line + " · " + Copy.appleBooksNotKept(notKept, locale: locale) : line)
        }
    }

    static func goodreadsPreview(_ p: GoodreadsPreview, locale: Locale = .autoupdatingCurrent) -> String {
        Copy.goodreadsPreview(books: p.books, finished: p.finished, reading: p.reading, want: p.want,
                              reviews: p.reviews, locale: locale)
    }
}
