import SwiftUI
import XCTest
@testable import CicadaApp

/// ROR-118 round 3 — `BalancedLines` narrows wrapped text to the narrowest width that keeps its line count, so no short
/// word is left alone on the last line, for any string.
@MainActor
final class BalancedLinesTests: XCTestCase {
    private func measure(_ string: String, room: CGFloat, balanced: Bool) -> CGSize {
        let text = Text(string).font(.system(size: 15, weight: .medium)).fixedSize(horizontal: false, vertical: true)
        let content: AnyView = balanced ? AnyView(BalancedLines { text }) : AnyView(text)
        return NSHostingController(rootView: content)
            .sizeThatFits(in: CGSize(width: room, height: .greatestFiniteMagnitude))
    }

    func testAnOrphanIsPulledBackIntoEvenLines() {
        let q = "Bob started calibrating the gripper camera, last heard 3 weeks ago. How did it go?"
        let plain = measure(q, room: 420, balanced: false)
        let balanced = measure(q, room: 420, balanced: true)
        XCTAssertEqual(balanced.height, plain.height, accuracy: 0.5, "the line count never changes")
        XCTAssertGreaterThan(plain.height, 20, "the control wraps")
        XCTAssertLessThan(balanced.width, plain.width - 20, "the lines are narrowed to come out even")
    }

    func testAShortStringIsLeftAlone() {
        let plain = measure("Did it go well?", room: 420, balanced: false)
        let balanced = measure("Did it go well?", room: 420, balanced: true)
        XCTAssertEqual(balanced.height, plain.height, accuracy: 0.5)
        XCTAssertEqual(balanced.width, plain.width, accuracy: 1)
    }
}
