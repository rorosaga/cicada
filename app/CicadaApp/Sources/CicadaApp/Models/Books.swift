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
    /// "Finished · 20 Oct 2026 · you said so" — `books.STATUS_WORDS`, the day it is dated by, and whose word it is when
    /// it came from a conversation rather than a door.
    static func status(_ record: BookStatusRecord, locale: Locale = .autoupdatingCurrent) -> String {
        let word = Copy.bookStatusWords[record.status] ?? record.status
        let day = EntityDates.day(record.day, locale: locale)
        // Where it came from is said only when there is more than one way in (ROR-115).
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
