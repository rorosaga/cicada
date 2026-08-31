import XCTest
@testable import CicadaApp

/// G68 §1 — Usage and Contributors are two views of the same question ("what
/// did the system do, and who did it"), so they share one page and one
/// remembered segment.
final class ActivitySectionTests: XCTestCase {

    func testSegmentLabelsAreTheOldPageNames() {
        XCTAssertEqual(ActivitySection.allCases.map(\.rawValue), ["Usage", "Contributors"])
    }

    /// The persisted segment is a raw string in `@AppStorage`. A value written
    /// by another build — or nothing at all — must fall back, never trap.
    func testRestoreFallsBackToUsage() {
        XCTAssertEqual(ActivitySection.restored(from: "Contributors"), .contributors)
        XCTAssertEqual(ActivitySection.restored(from: "Usage"), .usage)
        XCTAssertEqual(ActivitySection.restored(from: nil), .usage)
        XCTAssertEqual(ActivitySection.restored(from: ""), .usage)
        XCTAssertEqual(ActivitySection.restored(from: "Origins"), .usage)
    }

    func testActivityCopyFollowsTheSubtitleRule() {
        XCTAssertEqual(Copy.activity, "Activity")
        XCTAssertLessThanOrEqual(Copy.activitySubtitle.count, 60)
        XCTAssertFalse(Copy.activitySubtitle.lowercased().contains("activity"))
    }
}
