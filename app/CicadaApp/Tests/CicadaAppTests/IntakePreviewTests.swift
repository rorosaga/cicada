import XCTest
@testable import CicadaApp

/// Track I T5 — a drop of several files becomes ONE preview. A known extra
/// (`user.json`) is a quiet "Skipped" line; an unreadable file is named with the
/// backend's reason; only a drop with nothing readable fails (design §5.2).
final class IntakePreviewTests: XCTestCase {
    private func url(_ name: String) -> URL { URL(fileURLWithPath: "/tmp/intake/\(name)") }
    private func chat(_ vendor: String, new: Int, grown: Int = 0, same: Int = 0, from: String, to: String) -> IntakeSniff {
        IntakeSniff(recognized: true, kind: "chat", vendor: vendor, origin: "\(vendor)-export",
                    members: ["conversations.json"], counts: IntakeCounts(conversations: new + grown + same),
                    dateRange: IntakeDateRange(from: from, to: to), delta: IntakeDelta(new: new, grown: grown, unchanged: same),
                    titles: [IntakeTitle(title: "t-\(to)", date: to)])
    }

    func testAFolderDropAggregatesAndNamesWhatItSkipped() throws {
        let phase = IntakePreview.aggregate([
            IntakeFileSniff(url: url("conversations.json"),
                            sniff: chat("chatgpt", new: 3, grown: 1, same: 2, from: "2023-03-01", to: "2026-09-01")),
            IntakeFileSniff(url: url("user.json"),
                            sniff: IntakeSniff(ignored: [IntakeIgnored(name: "user.json", reason: "account details, not conversations")])),
            IntakeFileSniff(url: url("chat.html"), sniff: IntakeSniff(reason: "This looks like ChatGPT's chat.html viewer.")),
        ], capped: false)
        guard case .preview(let p) = phase else { return XCTFail("\(phase)") }
        XCTAssertEqual(p.chatFiles.map(\.lastPathComponent), ["conversations.json"])
        XCTAssertEqual(p.vendor, "chatgpt")
        XCTAssertEqual(p.delta, IntakeDelta(new: 3, grown: 1, unchanged: 2))
        XCTAssertEqual(p.importCount, 4, "Import N means new + grew")
        XCTAssertEqual(p.skipped.map(\.name), ["user.json", "chat.html"])
    }

    func testTwoVendorsSumAndKeepTheWiderRange() throws {
        guard case .preview(let p) = IntakePreview.aggregate([
            IntakeFileSniff(url: url("a.zip"), sniff: chat("claude", new: 2, from: "2025-01-01", to: "2025-06-01")),
            IntakeFileSniff(url: url("b.zip"), sniff: chat("chatgpt", new: 5, from: "2024-02-01", to: "2026-01-01")),
        ], capped: false) else { return XCTFail() }
        XCTAssertNil(p.vendor, "two vendors is 'Chat history', never one of them")
        XCTAssertEqual(p.dateFrom, "2024-02-01")
        XCTAssertEqual(p.dateTo, "2026-01-01")
        XCTAssertEqual(p.titles.first?.date, "2026-01-01", "newest first")
    }

    func testNothingReadableFailsWithTheBackendsOwnWords() {
        let phase = IntakePreview.aggregate([
            IntakeFileSniff(url: url("chat.html"), sniff: IntakeSniff(reason: "This looks like ChatGPT's chat.html viewer.")),
        ], capped: false)
        XCTAssertEqual(phase, .failed("This looks like ChatGPT's chat.html viewer."))
    }

    func testSavedContentCountsItsItems() throws {
        guard case .preview(let p) = IntakePreview.aggregate([
            IntakeFileSniff(url: url("bookmarks.html"),
                            sniff: IntakeSniff(recognized: true, kind: "saved", platform: "bookmarks", counts: IntakeCounts(items: 2))),
        ], capped: false) else { return XCTFail() }
        XCTAssertEqual(p.savedFiles.count, 1)
        XCTAssertEqual(p.importCount, 2)
    }

    func testTitlesAreCappedAndSaySo() throws {
        let many = (0..<(IntakePreview.maxTitles + 3)).map { IntakeTitle(title: "t\($0)", date: nil) }
        guard case .preview(let p) = IntakePreview.aggregate([
            IntakeFileSniff(url: url("c.json"), sniff: IntakeSniff(recognized: true, kind: "chat", titles: many)),
        ], capped: true) else { return XCTFail() }
        XCTAssertEqual(p.titles.count, IntakePreview.maxTitles)
        XCTAssertTrue(p.titlesTruncated)
        XCTAssertTrue(p.warnings.contains(Copy.intakeCapped(IntakeRouter.maxFiles)))
    }

    func testANewMemoryAssumesEverythingIsNew() throws {
        guard case .preview(let p) = IntakePreview.aggregate([
            IntakeFileSniff(url: url("c.json"), sniff: chat("claude", new: 1, grown: 2, same: 3, from: "2026-01-01", to: "2026-01-02")),
        ], capped: false) else { return XCTFail() }
        XCTAssertEqual(p.assumingEmptyBank().delta, IntakeDelta(new: 6, grown: 0, unchanged: 0))
    }
}
