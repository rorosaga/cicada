import Foundation

// G39, G233 — Sources → Reading: Apple Books on this Mac and a Goodreads export. Provider-neutral: no service is named
// as the one doing a job; Apple Books and Goodreads are the person's own apps, named as such.
extension Copy {
    static let readingGroup = "Reading"
    static let appleBooksTitle = "Apple Books"
    static let goodreadsTitle = "Goodreads"
    static let appleBooksOff = "Turn on to bring in your library: what you're reading and have finished, your "
        + "highlights and your notes. macOS asks once whether Cicada may read Apple Books' data."
    static let appleBooksTurnOn = "Turn on"
    static let appleBooksTurnOff = "Turn off"
    static let appleBooksSyncing = "Reading your library…"
    static func appleBooksSynced(_ when: String, books: Int, highlights: Int,
                                 locale: Locale = .autoupdatingCurrent) -> String {
        let b = books == 1 ? "1 book" : "\(UsageFormat.count(books, locale: locale)) books"
        let h = highlights == 1 ? "1 highlight" : "\(UsageFormat.count(highlights, locale: locale)) highlights"
        return "Synced \(when) · \(b) · \(h)"
    }
    /// Re-check of #600: a book over its cap keeps its oldest highlights; the rest are said, never silently dropped.
    static func appleBooksNotKept(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        (n == 1 ? "1 highlight" : "\(UsageFormat.count(n, locale: locale)) highlights") + " past a book's limit not kept"
    }
    static let appleBooksMissing = "Apple Books has no library on this Mac yet. Open Apple Books once, then Sync now."
    static let appleBooksUnreadable = "Cicada couldn't read Apple Books' library. If macOS asked about another app's "
        + "data, allow it, then Sync now."
    static let appleBooksSyncFailed = "Couldn't sync Apple Books. Cicada will try again."
    static let appleBooksNeedsUpdate = "This version of Cicada's background service can't read books yet — update "
        + "Cicada."
    static let appleBooksStopTitle = "Stop reading Apple Books?"
    static let appleBooksStopDetail = "Books already in your memory stay there."
    static let appleBooksReads = "Your library and its status, every highlight (the book's words) and every note "
        + "(yours). Only books that changed are sent again. Cicada never writes to Apple Books."

    static let goodreadsHow = "From Goodreads: My Books → Import and export → Export Library. When the file is "
        + "ready, choose goodreads_library_export.csv here. Your shelves, ratings, dates, reviews and private notes "
        + "come in; nothing is read from the Goodreads site."
    static let goodreadsChoose = "Choose the export…"
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
