import XCTest
@testable import CicadaApp

/// The consistency pass (2026-10-20, §9; DR-39, DR-40, DR-43, DR-53, DR-74; round 2: DR-48, DR-75, DR-76, §5.3): one component per thing, so the pages
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

    /// DR-39 / DR-53 — every fold draws `DisclosureChevron` (or `DisclosureHeader`, or `DisclosureButton` for a fold
    /// whose only control is its glyph): no hand-swapped `chevron.down`/`chevron.right`/`chevron.up` and no hand-turned
    /// chevron (a ‹ › pair that opens or closes the Reader is a direction, not a fold). Round 2 (2026-10-20) retired the
    /// `IconButton` exemption: its one user, Projects' "Around this project", draws `DisclosureButton`.
    func testEveryFoldDrawsTheOneDisclosureGlyph() throws {
        let swap = try NSRegularExpression(pattern: #""chevron\.(down|right|up)"\s*:\s*"chevron\.(down|right|up)""#)
        let turn = try NSRegularExpression(pattern: #"rotationEffect\(\.degrees\([^)]*\?\s*90"#)
        var offenders: [String] = []
        for file in try viewSources() where file.lastPathComponent != "Disclosure.swift" {
            for (n, line) in try lines(file) {
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

// MARK: - Round 2 (2026-10-20)

extension DesignConsistencyLintTests {
    /// DR-48 — a list row's fill is `rowHover` / `rowHoverFill` (Views/Common/RowHover.swift): selected over hover,
    /// only the pointer's hover eased. About twenty-five rows spelled `hovering ? bgHover : …` by hand, three ways.
    /// What remains on the list is not a list row, each named with why.
    func testEveryRowFillIsTheSharedOne() throws {
        let notRows: [String: String] = [
            "RowHover.swift": "the shared fill itself",
            "TextTabs.swift": "a tab, not a row (DR-45)",
            "GraphControlGroup.swift": "the Graph's control group button, a control",
            "MascotSettings.swift": "a Settings picker tile resting on bgFocus",
            "ScenerySettings.swift": "a Settings picker tile resting on bgFocus",
            "LinkCards.swift": "a link card resting on bgFocus",
            "ProjectSentence.swift": "a story row: bgFocus and the strong ring while selected, grows in place (Projects v2)",
            "EngineChooser.swift": "a Settings engine card resting on surface",
            "SleepRunDetails.swift": "a parked item's resting emphasis, not a hover",
        ]
        let handFill = try NSRegularExpression(
            pattern: #"\?\s*CicadaTheme\.(bgHover|surfaceHover)\b|CicadaTheme\.(bgHover|surfaceHover)\s*:"#)
        var offenders: [String] = []
        for file in try viewSources() where notRows[file.lastPathComponent] == nil {
            for (n, line) in try lines(file) {
                let range = NSRange(location: 0, length: (line as NSString).length)
                if handFill.firstMatch(in: line, range: range) != nil { offenders.append("\(file.lastPathComponent):\(n)") }
            }
        }
        XCTAssertEqual(offenders, [], "DR-48: a row's hover fill is rowHover / rowHoverFill")
        let shared = try XCTUnwrap(try viewSources().first { $0.lastPathComponent == "ListColumns.swift" })
        XCTAssertTrue(try String(contentsOf: shared, encoding: .utf8).contains(".rowHover("),
                      "ListRowSurface draws the shared fill too")
    }

    /// DR-75 — a page's way to add is `PageAddButton` in its eyebrow; a bare `+` is the Sleep tab row's alone (R-DL14).
    func testAPageAddsThroughOneLabelledButton() throws {
        let allowed: [String: String] = [
            "SleepTabRow.swift": "R-DL14: the one-shot import's door and ⌘N's only home",
            "GraphControlGroup.swift": "zoom in, not an add",
        ]
        var bare: [String] = []
        for file in try viewSources() where allowed[file.lastPathComponent] == nil {
            for (n, line) in try lines(file) where line.contains(#"IconButton(systemName: "plus""#) {
                bare.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertEqual(bare, [], "DR-75: add with PageAddButton")
        for page in ["SourcesPageView.swift", "LooksPage.swift"] {
            let file = try XCTUnwrap(try viewSources().first { $0.lastPathComponent == page })
            XCTAssertTrue(try String(contentsOf: file, encoding: .utf8).contains("PageAddButton("), page)
        }
    }

    /// §5.3 — Skills and Looks sit on the shared progressive columns (list → detail → Reader), with no fixed side
    /// column of their own, and host their own Reader.
    func testSkillsAndLooksUseTheProgressiveColumns() throws {
        for page in ["SkillsPage.swift", "LooksPage.swift"] {
            let file = try XCTUnwrap(try viewSources().first { $0.lastPathComponent == page })
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertTrue(text.contains("ProgressiveColumns("), "\(page): the shared columns")
            XCTAssertTrue(text.contains("listKeys("), "\(page): the list pages' keys (DR-68)")
            XCTAssertFalse(text.contains("detailWidth"), "\(page): no fixed-width side column")
        }
        XCTAssertTrue(AppTab.skills.hostsOwnReader)
        XCTAssertTrue(AppTab.looks.hostsOwnReader)
    }

    /// DR-76 — a field on a page, a column or a page's own sheet is `cicadaField`; the native rounded field stays in
    /// Settings' forms and the setup sheets, the Welcome card, and Skills' header (the owner's own design).
    func testAPageFieldIsTheAppsOwn() throws {
        let nativeDirs = ["/Views/Settings/", "/Views/Capture/Sheets/", "/Views/Intake/", "/Views/Connections/",
                          "/Views/Connect/", "/Views/Onboarding/"]
        let owners: Set<String> = ["SkillsPage.swift"]
        var offenders: [String] = []
        for file in try viewSources()
        where !nativeDirs.contains(where: { file.path.contains($0) }) && !owners.contains(file.lastPathComponent) {
            for (n, line) in try lines(file) where line.contains(".textFieldStyle(.roundedBorder)") {
                offenders.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertEqual(offenders, [], "DR-76: use .cicadaField()")
        let inbox = try XCTUnwrap(try viewSources().first { $0.lastPathComponent == "InboxFocusCard.swift" })
        XCTAssertTrue(try String(contentsOf: inbox, encoding: .utf8).contains(".cicadaField("),
                      "the Inbox's field, which first drew the style, draws through it")
    }

    /// DR-76 / DR-5 — no `cicadaField` lacks its focus ring (review of #377: six fields shipped without one). The field
    /// tracks its own focus unless the caller passes `isFocused:`; so a bare `.cicadaField()` must not sit on a field
    /// the caller already binds with `.focused(` (two bindings), and an `isFocused:` one must sit on a field the caller
    /// binds (else nothing ever lights it). The Inbox's field is bound by its own caller, one view out.
    func testEveryFieldShowsItsFocusRing() throws {
        let boundOutside: Set<String> = ["InboxFocusCard.swift"]
        var offenders: [String] = []
        var checked = 0
        for file in try viewSources() where file.lastPathComponent != "CicadaField.swift" {
            let all = try lines(file)
            for (index, (n, line)) in all.enumerated() where line.contains(".cicadaField(") {
                checked += 1
                // The field's own chain: back to the line that opens it.
                var chain: [String] = []
                var i = index
                while i >= 0 {
                    chain.append(all[i].1)
                    if all[i].1.contains("TextField(") || all[i].1.contains("SecureField(") { break }
                    i -= 1
                }
                let bound = chain.contains { $0.contains(".focused(") }
                // The prompt is drawn by the style in the tertiary ink; a titled field would draw the system's too.
                if !(chain.last ?? "").contains(#"TextField("","#) {
                    offenders.append("\(file.lastPathComponent):\(n) titles its field; the prompt goes to cicadaField")
                }
                let passes = line.contains("isFocused:")
                if passes && !bound && !boundOutside.contains(file.lastPathComponent) {
                    offenders.append("\(file.lastPathComponent):\(n) passes isFocused but binds no focus")
                }
                if !passes && bound { offenders.append("\(file.lastPathComponent):\(n) binds focus but passes none") }
            }
        }
        XCTAssertEqual(offenders, [], "DR-76: every cicadaField shows its focus ring")
        XCTAssertGreaterThanOrEqual(checked, 10, "the call pattern no longer matches — this lint would pass vacuously")
        let style = try XCTUnwrap(try viewSources().first { $0.lastPathComponent == "CicadaField.swift" })
        let text = try String(contentsOf: style, encoding: .utf8)
        XCTAssertTrue(text.contains("@FocusState"), "the field tracks its own focus when the caller passes none")
        XCTAssertFalse(text.contains("foregroundStyle(CicadaTheme.textPrimary"), "one ink for words and prompt")
        CicadaTheme.mode = .light
        XCTAssertEqual(CicadaField.promptInk, CicadaTheme.textTertiary, "the prompt is the tertiary step (DR-2)")
        CicadaTheme.mode = .dark
        XCTAssertNotEqual(CicadaField.ring(focused: true), CicadaField.ring(focused: false))
    }

    /// DR-68 — after ⏎ steps into a skill or a look, its detail holds the list's keys (↑/↓ swap in place, Esc closes
    /// the rightmost): review of #377 found Looks' ⏎ moved focus to a detail that could not take it, so every key died.
    func testTheDetailTakesTheKeysAfterReturn() throws {
        for page in ["SkillsPage.swift", "LooksPage.swift"] {
            let file = try XCTUnwrap(try viewSources().first { $0.lastPathComponent == page })
            let text = try String(contentsOf: file, encoding: .utf8)
            let start = try XCTUnwrap(text.range(of: "} detail: { plan in"), page)
            let end = try XCTUnwrap(text.range(of: ".focused($focus, equals: .detail)", range: start.upperBound..<text.endIndex),
                                    page)
            XCTAssertTrue(text[start.upperBound..<end.lowerBound].contains(".listKeys("),
                          "\(page): the detail is focusable and takes ↑/↓ · Esc before it is a focus target")
        }
    }

    /// DR-43 — Sources' lists read in words over the still skeleton, never a spinner.
    func testSourcesListsHaveNoSpinner() throws {
        for page in ["HarnessConversationsView.swift", "CapturedItemsList.swift", "WatchedDay.swift"] {
            let file = try XCTUnwrap(try viewSources().first { $0.lastPathComponent == page })
            let offenders = try lines(file).filter { $0.1.contains("ProgressView(") }.map { "\(page):\($0.0)" }
            XCTAssertEqual(offenders, [], "DR-43: words over ListSkeleton, no spinner")
        }
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
