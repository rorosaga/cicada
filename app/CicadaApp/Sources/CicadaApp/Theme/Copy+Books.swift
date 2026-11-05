import Foundation

// G39, G233 — Sources → Reading: Apple Books on this Mac and a Goodreads export. Provider-neutral: no service is named
// as the one doing a job; Apple Books and Goodreads are the person's own apps, named as such.
extension Copy {
    static let readingGroup = "Reading"
    static let appleBooksTitle = "Apple Books"
    static let goodreadsTitle = "Goodreads"
    static let bookScansTitle = "Book scans"
    static let bookScansLine = "Scan a book with Cicada on your phone."
    // Ruling 61: the same words a status record is written in (`books.STATUS_WORDS`).
    static let bookStatusWords = ["reading": "Reading now", "finished": "Finished", "want": "Want to read",
                                  "not_started": "Not started"]
    static let bookStatusFromChat = "you said so"
    static let bookStatusNotRight = "Not right"
    static let bookStatusNotRightHelp = "Take this back; the status before it returns."
    /// The Connect button's hover: what is read, and the one prompt that comes with the first read.
    static let appleBooksConnectHelp = "Your library and its status, your highlights and your notes. macOS asks once "
        + "whether Cicada may read Apple Books' data. Cicada never writes to Apple Books."
    static let appleBooksSyncing = "Reading your library…"
    static func appleBooksHolds(books: Int, highlights: Int, locale: Locale = .autoupdatingCurrent) -> String {
        let b = books == 1 ? "1 book" : "\(UsageFormat.count(books, locale: locale)) books"
        let h = highlights == 1 ? "1 highlight" : "\(UsageFormat.count(highlights, locale: locale)) highlights"
        return "\(b) · \(h)"
    }
    /// Re-check of #600: a book over its cap keeps its oldest highlights; the rest are said, never silently dropped.
    static func appleBooksNotKept(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        (n == 1 ? "1 highlight" : "\(UsageFormat.count(n, locale: locale)) highlights") + " past a book's limit not kept"
    }
    static let appleBooksMissing = "No library here yet. Open Apple Books once, then Refresh."
    static let appleBooksUnreadable = "Couldn't read the library. If macOS asked, allow it, then Refresh."
    static let appleBooksSyncFailed = "Couldn't sync Apple Books. Cicada will try again."
    static let appleBooksNeedsUpdate = "This version of Cicada's background service can't read books yet — update "
        + "Cicada."

    static let goodreadsHow = "From Goodreads: My Books → Import and export → Export Library. When the file is "
        + "ready, choose goodreads_library_export.csv here. Your shelves, ratings, dates, reviews and private notes "
        + "come in; nothing is read from the Goodreads site."
    static let goodreadsImport = "Import"
    static let goodreadsReading = "Reading the export…"
    static func goodreadsPreview(books: Int, finished: Int, reading: Int, want: Int, reviews: Int,
                                 locale: Locale = .autoupdatingCurrent) -> String {
        func n(_ v: Int) -> String { UsageFormat.count(v, locale: locale) }
        let head = books == 1 ? "1 book" : "\(n(books)) books"
        var parts = ["\(n(finished)) finished", "\(n(reading)) reading", "\(n(want)) want to read"]
        if reviews > 0 { parts.append(reviews == 1 ? "1 review" : "\(n(reviews)) reviews") }
        return "\(head): " + parts.joined(separator: " · ")
    }
    static func goodreadsImported(_ books: Int, locale: Locale = .autoupdatingCurrent) -> String {
        "Imported " + (books == 1 ? "1 book" : "\(UsageFormat.count(books, locale: locale)) books")
    }
    static let goodreadsFailed = "That file isn't a Goodreads library export."
}
