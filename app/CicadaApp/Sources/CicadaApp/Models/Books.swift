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

/// The Reading rows' lines, pure (`AppleBooksReaderTests`).
enum BooksRowText {
    static func appleBooks(_ status: AppleBooksReader.Status, now: Date, locale: Locale = .autoupdatingCurrent) -> String {
        switch status {
        case .off: return Copy.appleBooksOff
        case .syncing: return Copy.appleBooksSyncing
        case .failed(let why): return why
        case .synced(let at, let books, let highlights, let notKept):
            let relative = RelativeDateTimeFormatter()
            relative.unitsStyle = .full
            relative.dateTimeStyle = .named
            relative.locale = locale
            let line = Copy.appleBooksSynced(relative.localizedString(for: at, relativeTo: now), books: books,
                                             highlights: highlights, locale: locale)
            return notKept > 0 ? line + " · " + Copy.appleBooksNotKept(notKept, locale: locale) : line
        }
    }

    static func goodreadsPreview(_ p: GoodreadsPreview, locale: Locale = .autoupdatingCurrent) -> String {
        Copy.goodreadsPreview(books: p.books, finished: p.finished, reading: p.reading, want: p.want,
                              reviews: p.reviews, locale: locale)
    }
}
