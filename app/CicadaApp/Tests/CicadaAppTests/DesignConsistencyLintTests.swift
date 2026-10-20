import XCTest
@testable import CicadaApp

/// The consistency pass (2026-10-20, §9; DR-39, DR-40, DR-43, DR-53, DR-74): one component per thing, so the pages
/// cannot drift apart again. Before it, sixteen folds drew their chevron at five sizes, two ways, Skills' and Looks' side columns set their titles
/// in a face no other detail used, and the Inbox, Skills and Looks each spelled their own first-read state. Source
/// lints, because "a page built its own" is a fact about the source, not about one render.
final class DesignConsistencyLintTests: XCTestCase {
    private func lines(_ file: URL) throws -> [(Int, String)] {
        try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            .map { ($0.offset + 1, $0.element) }
            .filter { !$0.1.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
    }

    private func viewSources() throws -> [URL] {
        try ThemeTokenTests.swiftSources().filter { $0.path.contains("/Views/") }
    }

    /// DR-39 / DR-53 — every fold draws `DisclosureChevron` (or `DisclosureHeader`): no hand-swapped
    /// `chevron.down`/`chevron.right`/`chevron.up` and no hand-turned chevron (a ‹ › pair that opens or closes the
    /// Reader is a direction, not a fold). The one exception is an `IconButton` fold, whose 28 pt
    /// target is the control itself (DR-53).
    func testEveryFoldDrawsTheOneDisclosureGlyph() throws {
        let swap = try NSRegularExpression(pattern: #""chevron\.(down|right|up)"\s*:\s*"chevron\.(down|right|up)""#)
        let turn = try NSRegularExpression(pattern: #"rotationEffect\(\.degrees\([^)]*\?\s*90"#)
        var offenders: [String] = []
        for file in try viewSources() where file.lastPathComponent != "Disclosure.swift" {
            for (n, line) in try lines(file) where !line.contains("IconButton(") {
                let range = NSRange(location: 0, length: (line as NSString).length)
                if swap.firstMatch(in: line, range: range) != nil || turn.firstMatch(in: line, range: range) != nil {
                    offenders.append("\(file.lastPathComponent):\(n)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "a fold draws DisclosureChevron / DisclosureHeader (Views/Common/Disclosure.swift)")
    }

    /// DR-16 / DR-74 — a side column that shows one thing opens on `DetailHeader`: the thing's title in the detail face
    /// (display 22), its mark when it has one, and Close × at the column's top right. The focus-card grammar (§5.3: a
    /// head line of back · what it is · actions · ×, then the H1 at the same 22 pt) is the one other head, named here.
    func testEverySideColumnOpensOnTheSharedHead() throws {
        let focusCardHeads: Set<String> = [
            "ProjectDetailColumn.swift",   // a project: Part of · ⋯ · ×, then its name at 22 (Projects v2)
            "FeedItemDetail.swift",        // a saved item: its kind and site · copy · graph · ×, then its title
        ]
        let declares = try NSRegularExpression(pattern: #"^\s*(private )?struct \w+(DetailColumn|ItemColumn)\b"#,
                                              options: [.anchorsMatchLines])
        var checked = 0
        var offenders: [String] = []
        for file in try viewSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            let ns = text as NSString
            let found = declares.firstMatch(in: text, range: NSRange(location: 0, length: ns.length)) != nil
            guard found, !focusCardHeads.contains(file.lastPathComponent) else { continue }
            checked += 1
            if !text.contains("DetailHeader(") { offenders.append(file.lastPathComponent) }
        }
        XCTAssertEqual(offenders, [], "a side column's head is DetailHeader (Views/Common/DetailHeader.swift)")
        XCTAssertGreaterThanOrEqual(checked, 4, "the declaration pattern no longer matches — this lint would pass vacuously")
    }

    /// DR-43 — a list page's first read is `ListSkeleton` and its failure `ListErrorCard`: the still bars are spelled
    /// once, and no page answers a failed first read with an empty state that has no Retry.
    func testFirstReadStatesAreTheSharedPair() throws {
        var bars: [String] = []
        for file in try viewSources() where file.lastPathComponent != "ListColumns.swift" {
            for (n, line) in try lines(file) where line.contains("520 * fraction") {
                bars.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertEqual(bars, [], "a first read's skeleton is ListSkeleton")
        for page in ["SkillsPage.swift", "LooksPage.swift", "InboxPage.swift"] {
            let file = try XCTUnwrap(try viewSources().first { $0.lastPathComponent == page })
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertTrue(text.contains("ListErrorCard("), "\(page): a failed first read offers Retry (ListErrorCard)")
        }
    }

    /// DR-40 — four kinds of button. The native bordered styles stay inside Settings' forms and the setup sheets that
    /// sit over a page (capture, intake, connections); a page itself uses NeutralButton or PrimaryActionButton.
    func testNoPageUsesTheNativeBorderedButton() throws {
        let sheetDirs = ["/Views/Settings/", "/Views/Capture/Sheets/", "/Views/Intake/", "/Views/Connections/"]
        var offenders: [String] = []
        for file in try viewSources() where !sheetDirs.contains(where: { file.path.contains($0) }) {
            for (n, line) in try lines(file)
            where line.contains(".buttonStyle(.bordered)") || line.contains(".buttonStyle(.borderedProminent)") {
                offenders.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertEqual(offenders, [], "DR-40: a page's button is one of the four kinds")
    }

    /// DR-11 — a side column's edge comes from the theme (`columnEdge`), never a hand-drawn 1 pt rectangle.
    func testColumnEdgesComeFromTheTheme() throws {
        var offenders: [String] = []
        for file in try viewSources() {
            for (n, line) in try lines(file)
            where line.contains("Rectangle().fill(CicadaTheme.border).frame(width: 1)") {
                offenders.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertEqual(offenders, [], "DR-11: use .columnEdge()")
    }
}

/// DR-58 — a look's day reads in the app's one day grammar, never as the stored `YYYY-MM-DD`.
final class LooksDayWordsTests: XCTestCase {
    /// A fold's VoiceOver value carries the count the eye reads beside it ("Fading 4"), without the separator dot.
    func testAFoldSpeaksItsStateAndItsCount() {
        XCTAssertEqual(DisclosureHeader.spokenValue(isOpen: false, summary: "4"), "\(Copy.Lists.collapsed), 4")
        XCTAssertEqual(DisclosureHeader.spokenValue(isOpen: false, summary: "· 4,770"), "\(Copy.Lists.collapsed), 4,770")
        XCTAssertEqual(DisclosureHeader.spokenValue(isOpen: true, summary: nil), Copy.Lists.expanded)
    }

    func testALooksDayIsWordsNotTheStoredStamp() {
        let today = ISODay(year: 2026, month: 10, day: 20)
        XCTAssertEqual(LooksDay.words("2026-10-20", today: today), "Today")
        XCTAssertEqual(LooksDay.words("2026-10-19", today: today), "Yesterday")
        XCTAssertFalse(LooksDay.words("2026-09-23", today: today).contains("2026"), "this year's day carries no year")
        XCTAssertTrue(LooksDay.words("2025-09-23", today: today).contains("2025"), "another year's day says its year")
        XCTAssertEqual(LooksDay.words("", today: today), "")
    }
}
