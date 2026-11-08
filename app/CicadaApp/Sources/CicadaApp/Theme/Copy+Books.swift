import Foundation

// G39, G233 — Sources → Reading: Apple Books on this Mac and a Goodreads export. Provider-neutral: no service is named
// as the one doing a job; Apple Books and Goodreads are the person's own apps, named as such.
extension Copy {
    static let readingGroup = "Reading"
    static let appleBooksTitle = "Apple Books"
    static let goodreadsTitle = "Goodreads"
    // 2026-11-08: the person's own Google Books key, an optional source. Google Books is named because it is the source.
    static let googleBooksTitle = "Google Books"
    static let googleBooksKeyPrompt = "Paste your key"
    static let googleBooksSave = "Save"
    static let googleBooksMakeKey = "Make a key"
    static let googleBooksSaveFailed = "Couldn't save the key. Try again."
    static let googleBooksOn = "On · uses your key"
    static let googleBooksDisconnectKeeps = "Descriptions already added to books stay on their pages."
    static let bookScansTitle = "Book scans"
    // ROR-116: adding a book on the Mac. Typed or pasted, or read from the camera; the status is the person's to choose.
    static let bookAddPrompt = "ISBN"
    static let bookAdd = "Add"
    static let bookAddScan = "Scan"
    static let bookAddScanHelp = "Hold the barcode to your Mac's camera. Nothing is saved or sent but the number."
    static let bookScanClose = "Close"
    static let bookScanLookingUp = "Looking it up"
    static let bookScanAddedNoDetail = "Added"
    static func bookScanCount(_ n: Int) -> String { "\(n) added" }
    static let bookAddNotABook = "That is not a book's number."
    static let bookAddWaiting = "Added. Looking it up…"
    static let bookAddFailed = "Couldn't add it. Try again."
    static let bookAddOpen = "Open"
    static let bookAddNoCamera = "No camera on this Mac."
    static let bookAddCameraDenied = "Turn on Cicada in System Settings → Privacy & Security → Camera, then Scan."
    static func bookAddAdded(_ name: String) -> String { "Added · \(name)" }
    static func bookAddAlready(_ name: String) -> String { "Already in your books · \(name)" }
    /// `books.STATUS_WORDS` for the three a person can say about a book they add (the phone's three).
    static let bookAddStatuses: [(key: String, label: String)] = [("reading", "Reading"), ("finished", "Finished"),
                                                                   ("want", "Want to read")]
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
    static let appleBooksUnreadable = "Couldn't read this Apple Books library."
    /// macOS refused the read: the exact fix, in one line (the capture rail).
    static let appleBooksDenied = "Turn on Cicada in System Settings → Privacy & Security → Full Disk Access, then Refresh."
    static let appleBooksSyncFailed = "Couldn't sync Apple Books. Cicada will try again."
    static let appleBooksNeedsUpdate = "This version of Cicada's background service can't read books yet — update "
        + "Cicada."

    static let goodreadsHow = "From Goodreads: My Books → Import and export → Export Library. When the file is "
        + "ready, choose goodreads_library_export.csv here. Your shelves, ratings, dates, reviews and private notes "
        + "come in; nothing is read from the Goodreads site."
    static let goodreadsImport = "Import"
    /// Nothing is in memory until the person picks (G233).
    static func booksChoosing(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
        (n == 1 ? "1 book is" : "\(UsageFormat.count(n, locale: locale)) books are") + " waiting for your choice"
    }
    static func booksAddChosen(_ chosen: Int, of total: Int, locale: Locale = .autoupdatingCurrent) -> String {
        chosen == total ? "Add all" : "Add \(UsageFormat.count(chosen, locale: locale))"
    }
    static let booksSelectAll = "Select all"
    static let booksSelectNone = "Select none"
    static let booksLeaveOut = "Leave out"
    static let goodreadsReading = "Reading the export…"
    /// The description box (2026-11-06): where it came from, and the way back from a wrong title match.
    static func bookDescriptionSource(_ name: String, saved: String?) -> String {
        saved.map { "From \(name), saved \($0)" } ?? "From \(name)"
    }
    static let bookFoundByTitle = "Found by its title and author."
    static let bookNotThisBook = "Not this book"
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
