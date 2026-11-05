import XCTest
@testable import CicadaApp

/// ROR-116 — adding a book on the Mac: the number a barcode or a field holds, and where a book came in from. Invented
/// numbers with valid check digits; no camera is opened.
final class BookAddTests: XCTestCase {
    func testAnISBN13IsTakenFromHyphensAndAnISBN10IsConverted() {
        XCTAssertEqual(BookISBN.parse("9784000000000"), "9784000000000")
        XCTAssertEqual(BookISBN.parse("978-4-00-000000-0"), "9784000000000")
        XCTAssertNil(BookISBN.parse("000000000X"))                    // an ISBN-10 whose check fails
        XCTAssertEqual(BookISBN.parse("0000000000"), "9780000000002")   // ISBN-10 → 13
    }

    func testAPriceCodeAShortNumberAndAWrongCheckDigitAreNotBooks() {
        XCTAssertNil(BookISBN.parse("4006381333931"))                    // a valid EAN that is not a book's
        XCTAssertNil(BookISBN.parse("9784000000001"))                    // check digit off by one
        XCTAssertNil(BookISBN.parse("12345"))
        XCTAssertNil(BookISBN.parse(""))
    }

    func testTheStatusLineSaysWhereABookCameFromOnlyWithMoreThanOneWayIn() {
        let locale = Locale(identifier: "en_US")
        func record(_ ways: [String]) -> BookStatusRecord {
            BookStatusRecord(status: "reading", day: nil, claimId: "c1", fromChat: false, ways: ways)
        }
        XCTAssertEqual(BooksRowText.status(record(["Apple Books", "Scanned"]), locale: locale),
                       "Reading now · Apple Books · Scanned")
        XCTAssertEqual(BooksRowText.status(record(["Scanned"]), locale: locale), "Reading now")
        XCTAssertEqual(BooksRowText.status(record([]), locale: locale), "Reading now")
    }

    func testAnOlderBackendsStatusDecodesWithNoWays() throws {
        let old = #"{"status":"finished","day":"2026-10-20","claimId":"c9","fromChat":false}"#
        XCTAssertEqual(try JSONDecoder().decode(BookStatusRecord.self, from: Data(old.utf8)).ways, [])
        let new = #"{"status":"finished","day":null,"claimId":"c9","fromChat":false,"ways":["Apple Books","Scanned"]}"#
        XCTAssertEqual(try JSONDecoder().decode(BookStatusRecord.self, from: Data(new.utf8)).ways,
                       ["Apple Books", "Scanned"])
    }

    func testTheScanResultDecodesWaitingAndAnExistingPage() throws {
        let waiting = try JSONDecoder().decode(BookScanResult.self, from: Data(#"{"state":"waiting"}"#.utf8))
        XCTAssertEqual(waiting.state, "waiting")
        XCTAssertNil(waiting.name)
        let added = try JSONDecoder().decode(
            BookScanResult.self, from: Data(#"{"state":"added","entityId":"a-book","name":"A Book","existing":true}"#.utf8))
        XCTAssertEqual(added.existing, true)
        XCTAssertEqual(Copy.bookAddAlready("A Book"), "Already in your books · A Book")
    }

    /// G233 — the book's page leads with the book; being scanned is one small label with its day.
    func testABookCardReadsItsFactsLineAndLabelsHowItCameIn() throws {
        let json = #"""
        {"subtitle":"A Tale","authors":["Ada Example"],"published":"2019","pages":320,"publisher":"Example House",
         "subjects":["Orchards"],"ways":[{"door":"book-scan","label":"Scanned","day":"2026-11-05"},
                                         {"door":"apple-books","label":"Apple Books"}]}
        """#
        let card = try JSONDecoder().decode(BookCard.self, from: Data(json.utf8))
        XCTAssertEqual(card.factsLine, "2019 · 320 pages · Example House")
        let en = Locale(identifier: "en_US")
        XCTAssertEqual(BooksRowText.way(card.ways[0], locale: en), "Scanned Nov 5")
        XCTAssertEqual(BooksRowText.way(card.ways[1], locale: en), "Apple Books")
        let bare = try JSONDecoder().decode(BookCard.self, from: Data("{}".utf8))
        XCTAssertNil(bare.factsLine)
        XCTAssertEqual(BooksRowText.found(authors: [], existing: true), "Already in your books")
        XCTAssertEqual(BooksRowText.found(authors: ["Ada Example"], existing: false), "Ada Example")
    }
}
