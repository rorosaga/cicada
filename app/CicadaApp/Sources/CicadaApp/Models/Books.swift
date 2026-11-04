import Foundation

// G39, G233 — the wire shapes of the book routes (`api/routers/books.py`).

struct AppleBooksSettingsReply: Decodable, Equatable, Sendable { let enabled: Bool }

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
