import XCTest
@testable import CicadaApp

/// Owner 2026-11-23: in every chat, app-wide, scrolling up from the newest message shows a round button that takes you
/// back to it. The Sleep queue's chat thread missed it (owner 2026-11-25), so this holds the rule at the source: a view
/// file that draws a conversation in a scroll view carries the three pieces `JumpToLatest.swift` documents — the anchor
/// after the newest row, the content's space, and the modifier on the scroll view — and opens at the newest message.
/// A source lint, because "a button exists in the diff" is not something a unit test of a pure function can tell you.
final class JumpToLatestLintTests: XCTestCase {
    /// What makes a file's scroll view a chat: it draws the Reader's chat rows, or it pins its scroll to the bottom.
    static let chatMarkers = ["ReaderChatRows(", "ChatThreadRows(", ".defaultScrollAnchor(", "anchor: .bottom)"]
    static let pieces = ["JumpToLatestAnchor(", ".jumpToLatestSpace(", ".jumpToLatest("]
    /// Files that define the pieces, or draw chat rows with no scroll view of their own.
    static let exempt = ["Views/Common/JumpToLatest.swift"]

    static func chatScrollFiles() throws -> [(file: URL, text: String)] {
        let files = try ThemeTokenTests.swiftSources()
        XCTAssertFalse(files.isEmpty, "found no sources — this lint would pass vacuously")
        return try files.compactMap { file in
            guard !exempt.contains(where: { file.path.hasSuffix($0) }) else { return nil }
            let text = try String(contentsOf: file, encoding: .utf8)
            let code = text.components(separatedBy: .newlines).filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
                .joined(separator: "\n")
            guard code.contains("ScrollView"), chatMarkers.contains(where: code.contains) else { return nil }
            return (file, code)
        }
    }

    func testEveryChatScrollViewCarriesTheJumpToLatestButton() throws {
        let chats = try Self.chatScrollFiles()
        // The lint must see the chats it is about, or a renamed marker would let it pass on nothing.
        for known in ["ReaderThread.swift", "SourceSpansView.swift", "ChatSourceList.swift", "CatchupView.swift"] {
            XCTAssertTrue(chats.contains { $0.file.lastPathComponent == known }, "\(known) is a chat scroll view and must be seen")
        }
        var missing: [String] = []
        for (file, code) in chats {
            for piece in Self.pieces where !code.contains(piece) { missing.append("\(file.lastPathComponent): \(piece)") }
        }
        XCTAssertEqual(missing, [], "a chat scroll view without the jump-to-latest pieces (owner 2026-11-23, 2026-11-25)")
    }

    func testEveryChatOpensAtItsNewestMessage() throws {
        var offenders: [String] = []
        for (file, code) in try Self.chatScrollFiles() {
            for (n, line) in code.components(separatedBy: .newlines).enumerated()
            where line.contains(".defaultScrollAnchor(") && !line.contains(".defaultScrollAnchor(.bottom)") {
                offenders.append("\(file.lastPathComponent): \(line.trimmingCharacters(in: .whitespaces)) (stripped line \(n + 1))")
            }
        }
        XCTAssertEqual(offenders, [], "a chat opens at its newest message, history above (DESIGN_RULES 2026-10-19 (5), 2026-11-25)")
    }

    /// 2026-11-25, seen in the running app: two SwiftUI measures of "above the newest message" failed (the content's
    /// coordinates are not the visible rectangle's while unmeasured lazy rows sit above; a self-measuring anchor goes
    /// silent once the lazy stack drops it). The scroll view's own distance from its end decides.
    func testTheScrollViewItselfDecidesWhetherTheViewIsAway() throws {
        let file = try XCTUnwrap(try ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Common/JumpToLatest.swift") })
        let code = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }.joined(separator: "\n")
        XCTAssertFalse(code.contains("onScrollGeometryChange"), "the content's coordinates are not the visible rectangle's")
        XCTAssertFalse(code.contains("bounds(of: .scrollView)"), "an anchor a lazy stack dropped measures nothing")
        XCTAssertFalse(code.contains("onDisappear"), "a view leaving a lazy stack is no measure of where the scroll view is")
        XCTAssertTrue(code.contains("isAway(distanceFromEnd:"), "the scroll view's distance from its end decides")
    }

    /// 2026-11-25, seen in the running app: the Sleep page's title row and room traded one id as the column crossed the
    /// beside width (opening the Reader narrows it), and the lazy stack kept both rooms. A row's id never depends on
    /// the width.
    func testTheSleepPagesTopRowsKeepOneIdEach() throws {
        let file = try XCTUnwrap(try ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Sleep/SleepView.swift") })
        let code = try String(contentsOf: file, encoding: .utf8)
        let conditional = code.components(separatedBy: .newlines).filter { $0.contains(".id(") && $0.contains("?") && $0.contains(":") }
        XCTAssertEqual(conditional.map { $0.trimmingCharacters(in: .whitespaces) }, [], "an id chosen by a condition")
        XCTAssertEqual(code.components(separatedBy: ".id(Self.topAnchor)").count - 1, 1, "one row is the top")
    }
}
