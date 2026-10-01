import XCTest
@testable import CicadaApp

final class BookwormViewTests: XCTestCase {
    func testReadingCoverIsChosenInsideTheTimelineClosure() throws {
        let source = SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp/Views/Common/BookwormView.swift")
        let text = try String(contentsOf: source)
        let timeline = try XCTUnwrap(text.range(of: "TimelineView(SpriteFrameSchedule"))
        let cover = try XCTUnwrap(text.range(of: "BookwormArt.coverIndex(at: context.date"))
        XCTAssertGreaterThan(cover.lowerBound, timeline.lowerBound)
        XCTAssertTrue(text.contains("BookwormArt.transitionClip($0.kind)"))
        XCTAssertTrue(text.contains("WindowVisibilityReader"))
        XCTAssertTrue(text.contains("SceneRunPolicy.isPaused"))
        XCTAssertTrue(text.contains(".accessibilityLabel(\"\\(state.title) — \\(state.detail)\")"))
    }
}
