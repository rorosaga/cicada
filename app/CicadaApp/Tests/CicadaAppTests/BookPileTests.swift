import XCTest
@testable import CicadaApp

/// G125 R9 — the book pile is a pure layout: one book per source, largest first by count, folded beyond `maxBooks`
/// into one remainder book. Every case here is exact numbers, not "didn't crash".
final class BookPileTests: XCTestCase {

    private func volume(_ origin: String, count: Int, chars: Int, remaining: Int? = nil) -> OriginVolume {
        OriginVolume(origin: origin, count: count, chars: chars, remaining: remaining ?? count)
    }

    // MARK: bookPileLayout — order

    func test_sortsByCountDescendingThenCharsThenOrigin() {
        let buckets = [
            volume("safari-tab", count: 3, chars: 500),
            volume("claude-code", count: 3, chars: 500),
            volume("rss", count: 3, chars: 9000),
            volume("telegram", count: 9, chars: 10),
        ]
        XCTAssertEqual(bookPileLayout(buckets).map(\.origin), ["telegram", "rss", "claude-code", "safari-tab"])
    }

    // MARK: bookPileLayout — fold beyond maxBooks

    func test_nineBucketsWithMaxBooksEightFoldsTheNinthIntoARemainder() {
        let buckets = (1...9).map { i in volume("origin-\(i)", count: i, chars: i * 1000) }
        let specs = bookPileLayout(buckets, maxBooks: 8)
        XCTAssertEqual(specs.count, 9)
        XCTAssertFalse(specs[0..<8].contains { $0.isRemainder })
        XCTAssertEqual(specs.last?.isRemainder, true)
        XCTAssertEqual(specs.last?.origin, "+more")
        XCTAssertEqual(specs.last?.count, 1, "the smallest source is the one folded")
        XCTAssertEqual(PileBooks.maxBooks, 7)
    }

    func test_theRemainderCarriesTheSumOfWhatItAbsorbed() {
        let buckets = (1...10).map { i in volume("origin-\(i)", count: i, chars: 0, remaining: i - 1) }
        let fold = bookPileLayout(buckets).last
        XCTAssertEqual(fold?.count, 1 + 2 + 3)
        XCTAssertEqual(fold?.remaining, 0 + 1 + 2)
    }

    // MARK: bookPileLayout — what is still unread

    func test_remainingIsCarriedAndClamped() {
        XCTAssertEqual(bookPileLayout([volume("claude-code", count: 12, chars: 1000, remaining: 3)]).first?.remaining, 3)
        XCTAssertEqual(BookSpec(origin: "rss", count: 4, remaining: 9).remaining, 4)
        XCTAssertEqual(BookSpec(origin: "rss", count: 4, remaining: -2).remaining, 0)
        XCTAssertEqual(BookSpec(origin: "rss", count: 4).remaining, 4)
    }

    // MARK: bookPileLayout — empty

    func test_emptyInputIsEmptyOutput() {
        let empty: [OriginVolume] = []
        XCTAssertEqual(bookPileLayout(empty), [])
    }

    // MARK: originVolumes

    private func episode(id: String, origin: String, chars: Int) -> EpisodeQueueItem {
        let json = """
        {"id":"\(id)","timestamp":"2026-09-01T00:00:00Z","source":"mcp","origin":"\(origin)",
         "title":null,"preview":"","chars":\(chars),"processed":false}
        """
        return try! JSONDecoder().decode(EpisodeQueueItem.self, from: Data(json.utf8))
    }

    func test_originVolumes_sumsCharsPerOriginFromQueuedRows() {
        let queued = [
            episode(id: "1", origin: "claude-code", chars: 500),
            episode(id: "2", origin: "claude-code", chars: 700),
            episode(id: "3", origin: "safari-tab", chars: 100),
        ]
        let volumes = originVolumes(queued: queued, queueByOrigin: [:], readByOrigin: [:], running: false)
        let byOrigin = Dictionary(uniqueKeysWithValues: volumes.map { ($0.origin, $0) })
        XCTAssertEqual(byOrigin["claude-code"]?.chars, 1200)
        XCTAssertEqual(byOrigin["claude-code"]?.count, 2)
        XCTAssertEqual(byOrigin["safari-tab"]?.chars, 100)
    }

    func test_originVolumes_notRunning_remainingEqualsCount() {
        let queued = [episode(id: "1", origin: "claude-code", chars: 500)]
        let volumes = originVolumes(queued: queued, queueByOrigin: ["claude-code": 99], readByOrigin: ["claude-code": 50], running: false)
        XCTAssertEqual(volumes.first?.remaining, 1)
    }

    func test_originVolumes_running_remainingIsQueueMinusReadClampedToZero() {
        let queued = [episode(id: "1", origin: "claude-code", chars: 500)]
        let volumes = originVolumes(queued: queued, queueByOrigin: ["claude-code": 10], readByOrigin: ["claude-code": 4], running: true)
        XCTAssertEqual(volumes.first?.remaining, 6)
    }

    func test_originVolumes_running_remainingClampsAtZeroNeverNegative() {
        let queued = [episode(id: "1", origin: "claude-code", chars: 500)]
        // readByOrigin ahead of queueByOrigin should never happen, but the
        // clamp keeps a transient race from ever drawing a negative width.
        let volumes = originVolumes(queued: queued, queueByOrigin: ["claude-code": 2], readByOrigin: ["claude-code": 5], running: true)
        XCTAssertEqual(volumes.first?.remaining, 0)
    }

    /// An origin the episode cap left out of THIS cycle is queued but is not
    /// a key of `queueByOrigin` at all (distinct from the zero-remaining
    /// case above, where it IS a key). `studyRows` renders that as "next
    /// cycle" rather than a bogus "0 of 0" — the pile must match: the book
    /// stays on the pile.
    func test_originVolumes_running_originLeftOutOfCycleByCapStaysFullWidth() {
        let queued = [
            episode(id: "1", origin: "claude-code", chars: 500),
            episode(id: "2", origin: "safari-tab", chars: 100),
        ]
        let volumes = originVolumes(queued: queued, queueByOrigin: ["claude-code": 10], readByOrigin: ["claude-code": 4], running: true)
        let byOrigin = Dictionary(uniqueKeysWithValues: volumes.map { ($0.origin, $0) })
        XCTAssertEqual(byOrigin["safari-tab"]?.remaining, 1)
        XCTAssertEqual(byOrigin["safari-tab"]?.count, 1)
    }

    func test_theFattestBookIsAtTheBottomOfThePile() {
        let books = bookPileLayout([
            OriginVolume(origin: "safari-tab", count: 188, chars: 40_000, remaining: 188),
            OriginVolume(origin: "telegram", count: 1, chars: 100, remaining: 1),
            OriginVolume(origin: "claude-code", count: 6, chars: 900_000, remaining: 6),
        ])
        XCTAssertEqual(books.map(\.origin), ["safari-tab", "claude-code", "telegram"])
        let placed = PileBooks.stack(books)
        XCTAssertEqual(placed.sorted { $0.y < $1.y }.map(\.spec.origin), ["safari-tab", "claude-code", "telegram"])
        XCTAssertEqual(placed.map(\.step), [3, 1, 0])
        XCTAssertTrue(PileBooks.stack([]).isEmpty)
    }
}
