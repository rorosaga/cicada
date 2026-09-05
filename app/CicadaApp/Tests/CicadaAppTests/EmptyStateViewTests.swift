import XCTest
@testable import CicadaApp

/// G117 — every empty-state message is one sentence a person can read at a
/// glance (the same ≤60-char rule G125 R8 applies to the Sleep bubble).
final class EmptyStateViewTests: XCTestCase {
    func testEveryEmptyStateMessageIsOneShortSentence() {
        let messages = [
            Copy.emptyGraphMessage, Copy.emptyInboxMessage,
            Copy.emptyFeedMessage, Copy.emptySourcesMessage,
        ]
        for m in messages {
            XCTAssertLessThanOrEqual(m.count, 60, m)
            XCTAssertFalse(m.hasSuffix("!"), m)
        }
    }
}
