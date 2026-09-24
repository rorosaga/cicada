import XCTest
@testable import CicadaApp

/// G153 / R-OB16 — seven lines checked word for word against Project Gutenberg texts (2026-09-24), each attributed,
/// dated and long out of copyright; one per install, kept.
final class MemoryQuotesTests: XCTestCase {
    func testEveryQuoteIsAttributedDatedAndPublicDomain() {
        XCTAssertEqual(MemoryQuotes.all.count, 7)
        XCTAssertEqual(Set(MemoryQuotes.all.map(\.id)).count, MemoryQuotes.all.count)
        for q in MemoryQuotes.all {
            XCTAssertFalse(q.text.isEmpty || q.author.isEmpty || q.work.isEmpty, q.id)
            XCTAssertLessThan(q.year, 1900, "\(q.id): long out of copyright")
            XCTAssertTrue(q.source.contains("Project Gutenberg"), "\(q.id): the edition it was checked against")
            XCTAssertLessThanOrEqual(q.text.count, 140, "\(q.id): two card lines at most")
        }
    }

    func testTheBriefsExampleIsInTheTableWordForWord() throws {
        let wilde = try XCTUnwrap(MemoryQuotes.all.first { $0.author == "Oscar Wilde" })
        XCTAssertEqual(wilde.text, "Memory, my dear Cecily, is the diary that we all carry about with us.")
        XCTAssertEqual(wilde.work, "The Importance of Being Earnest")
        XCTAssertEqual(wilde.year, 1895)
    }

    func testOneQuoteIsChosenPerInstallAndKept() throws {
        let d = try XCTUnwrap(UserDefaults(suiteName: "cicada.test.quote.\(UUID().uuidString)"))
        let first = MemoryQuotes.chosen(defaults: d, random: { 3 })
        XCTAssertEqual(first, MemoryQuotes.all[3])
        XCTAssertEqual(MemoryQuotes.chosen(defaults: d, random: { 0 }), first, "a rerun shows the same line")
        d.set("retired-id", forKey: MemoryQuotes.defaultsKey)
        XCTAssertEqual(MemoryQuotes.chosen(defaults: d, random: { 1 }), MemoryQuotes.all[1], "an unknown id re-picks")
        XCTAssertEqual(MemoryQuotes.chosen(defaults: d, random: { -8 }), MemoryQuotes.all[1], "kept")
    }
}
