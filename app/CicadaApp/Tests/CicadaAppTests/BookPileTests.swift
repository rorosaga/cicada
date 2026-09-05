import XCTest
@testable import CicadaApp

/// G125 R9 — the book pile is a pure layout: spine height on a log scale of
/// characters queued, sorted largest-first, folded beyond `maxBooks` into one
/// remainder spine. Every case here is exact numbers, not "didn't crash" —
/// the height formula and the fold are load-bearing for how the pile reads
/// at a glance.
final class BookPileTests: XCTestCase {

    private func volume(_ origin: String, count: Int, chars: Int, remaining: Int? = nil) -> OriginVolume {
        OriginVolume(origin: origin, count: count, chars: chars, remaining: remaining ?? count)
    }

    // MARK: bookPileLayout — height

    func test_height_zeroCharsIsTheEightPointFloor() {
        let specs = bookPileLayout([volume("claude-code", count: 1, chars: 0)])
        XCTAssertEqual(specs.first?.height ?? -1, 8, accuracy: 0.01)
    }

    func test_height_twoThousandCharsIsFourteen() {
        // 8 + 6*log2(1 + 2000/2000) = 8 + 6*log2(2) = 8 + 6 = 14
        let specs = bookPileLayout([volume("claude-code", count: 1, chars: 2000)])
        XCTAssertEqual(specs.first?.height ?? -1, 14, accuracy: 0.01)
    }

    func test_height_twoMillionCharsClampsAtForty() {
        let specs = bookPileLayout([volume("claude-code", count: 1, chars: 2_000_000)])
        XCTAssertEqual(specs.first?.height ?? -1, 40, accuracy: 0.01)
    }

    // MARK: bookPileLayout — sort

    func test_sortsByCharsDescendingThenOriginAscending() {
        let buckets = [
            volume("safari-tab", count: 1, chars: 500),
            volume("claude-code", count: 1, chars: 500),
            volume("telegram", count: 1, chars: 5000),
        ]
        let specs = bookPileLayout(buckets)
        XCTAssertEqual(specs.map(\.origin), ["telegram", "claude-code", "safari-tab"])
    }

    // MARK: bookPileLayout — fold beyond maxBooks

    func test_nineBucketsWithMaxBooksEightFoldsTheNinthIntoARemainder() {
        let buckets = (1...9).map { i in
            volume("origin-\(i)", count: i, chars: i * 1000)
        }
        let specs = bookPileLayout(buckets, maxBooks: 8)
        XCTAssertEqual(specs.count, 9)
        XCTAssertFalse(specs[0..<8].contains { $0.isRemainder })
        let remainder = try? XCTUnwrap(specs.last)
        XCTAssertEqual(remainder?.isRemainder, true)
        XCTAssertEqual(remainder?.origin, "+more")
        // The smallest bucket (origin-1, count 1) is the one folded out —
        // sorted desc by chars means it's dropped last, i.e. sorted first
        // eight are origin-9..origin-2, and origin-1 (count 1) is folded.
        XCTAssertEqual(remainder?.count, 1)
    }

    // MARK: bookPileLayout — width fraction

    func test_widthFractionIsRemainingOverCountWhileRunning() {
        let specs = bookPileLayout([volume("claude-code", count: 12, chars: 1000, remaining: 3)])
        XCTAssertEqual(specs.first?.widthFraction ?? -1, 0.25, accuracy: 0.001)
    }

    func test_widthFractionIsFullWhenRemainingEqualsCount() {
        let specs = bookPileLayout([volume("claude-code", count: 12, chars: 1000, remaining: 12)])
        XCTAssertEqual(specs.first?.widthFraction ?? -1, 1, accuracy: 0.001)
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
}
