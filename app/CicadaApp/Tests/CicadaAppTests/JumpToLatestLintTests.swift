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
}
