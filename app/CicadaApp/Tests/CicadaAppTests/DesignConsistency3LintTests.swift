import XCTest
@testable import CicadaApp

/// The consistency pass, round 3 (2026-10-20, §9): round 2's leftover inventory — the menu-bar menu, onboarding, the
/// ⌘K palette and the Reader's noted row — and a last sweep of literals that duplicate a theme token. Source lints, as
/// rounds 1 and 2: "a surface spelled its own" is a fact about the source.
final class DesignConsistency3LintTests: XCTestCase {
    private func code(_ file: URL) throws -> [(Int, String)] {
        try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            .map { ($0.offset + 1, $0.element) }
            .filter { !$0.1.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
    }

    private func sources() throws -> [URL] { try ThemeTokenTests.swiftSources() }

    private func source(_ name: String) throws -> URL {
        try XCTUnwrap(try sources().first { $0.lastPathComponent == name }, name)
    }

    /// Copy — the menu-bar menu's words, its hover text and the bookworm's moods come from `Copy.MenuBar` /
    /// `Copy.Mood`; `MenuBarManager` spelled every item, the clipboard flashes and the day words by hand until round 3.
    func testTheMenuBarSpeaksThroughCopy() throws {
        var offenders: [String] = []
        for (n, line) in try code(try source("MenuBarManager.swift")) {
            if line.contains(#"NSMenuItem(title: ""#) || line.contains(#"flashHeader(""#)
                || line.contains(#""Cicada"#) || line.contains(#"dateFormat = ""#) {
                offenders.append("MenuBarManager.swift:\(n)")
            }
        }
        let state = try String(contentsOf: try source("BookwormState.swift"), encoding: .utf8)
        let start = try XCTUnwrap(state.range(of: "var title: String {"))
        let end = try XCTUnwrap(state.range(of: "var caseName: String {", range: start.upperBound..<state.endIndex))
        for (offset, line) in state[start.lowerBound..<end.lowerBound].components(separatedBy: .newlines).enumerated()
        where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && line.contains("\"") {
            offenders.append("BookwormState.swift (title/detail, line +\(offset)): \(line.trimmingCharacters(in: .whitespaces))")
        }
        let renderer = try String(contentsOf: try source("BookwormRenderer.swift"), encoding: .utf8)
        if renderer.contains(#""Cicada — "#) { offenders.append("BookwormRenderer.swift spells the item's label") }
        XCTAssertEqual(offenders, [], "the menu bar's words live in Copy+MenuBar.swift")
    }

    /// DR-58 — the menu's next run reads in the app's day words, with the viewer's own clock.
    func testTheMenuBarsNextRunUsesTheDayWords() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: "UTC"))
        let locale = Locale(identifier: "en_US")
        let now = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 10, day: 20, hour: 15)))
        let tonight = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 10, day: 20, hour: 23)))
        let tomorrow = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 10, day: 21, hour: 3)))
        let later = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 10, day: 24, hour: 3)))
        func line(_ d: Date?) -> String {
            MenuBarManager.nextSleepLine(d, now: now, calendar: calendar, locale: locale)
                .replacingOccurrences(of: "\u{202F}", with: " ")
        }
        XCTAssertEqual(line(tonight), "Next sleep: Today, 11:00 PM")
        XCTAssertEqual(line(tomorrow), "Next sleep: Tomorrow, 3:00 AM")
        XCTAssertEqual(line(later), "Next sleep: Oct 24, 3:00 AM")
        XCTAssertEqual(line(nil), "Next sleep: not scheduled")
        XCTAssertTrue(line(tonight).hasPrefix(Copy.MenuBar.nextSleepPrefix), "the export lines anchor on this prefix")
        XCTAssertEqual(Copy.MenuBar.lastSleep(nil), "Last sleep: never")
    }

    /// DR-43 / DR-45 — onboarding says what is still arriving in words (no spinner) and the export walkthrough's
    /// vendor switch is the shared `TextTabs`, each tab with its vendor's real mark (DR-52).
    func testOnboardingUsesTheSharedWaitAndTabs() throws {
        var spinners: [String] = []
        for file in try sources() where file.path.contains("/Views/Onboarding/") {
            for (n, line) in try code(file) where line.contains("ProgressView(") {
                spinners.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertEqual(spinners, [], "DR-43: onboarding says it in words")
        let walkthrough = try String(contentsOf: try source("ExportWalkthroughSheet.swift"), encoding: .utf8)
        XCTAssertTrue(walkthrough.contains("TextTabs("), "the vendor switch is TextTabs (DR-45)")
        XCTAssertFalse(walkthrough.contains("v == vendor ? CicadaTheme.bgSelected"), "no hand-drawn selected pill")
        XCTAssertTrue(walkthrough.contains("mark: AnyView(VendorMark("), "each tab keeps its vendor's real mark (DR-52)")
    }

    /// DR-43 / DR-44 / DR-12 — the palette and its Ask answer wait in words (no spinner, no indeterminate bar), the
    /// row's type is a `Tag`, and no shape is a bare `RoundedRectangle`.
    func testThePaletteUsesTheSharedPieces() throws {
        var offenders: [String] = []
        let files = try sources().filter { $0.path.contains("/Views/Find/") || $0.lastPathComponent == "AskPanel.swift" }
        XCTAssertGreaterThanOrEqual(files.count, 4, "the palette's files moved — this lint would pass vacuously")
        for file in files {
            for (n, line) in try code(file)
            where line.contains("ProgressView(") || line.contains("Capsule().fill(CicadaTheme.surfaceHover")
                || line.contains(".background(CicadaTheme.surfaceHover)") {
                offenders.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertEqual(offenders, [], "the palette waits in words and draws its type as a Tag")
        let row = try String(contentsOf: try source("FindRowView.swift"), encoding: .utf8)
        XCTAssertTrue(row.contains("Tag(text: badge)"), "DR-44: the type capsule is the one pill")
        let ask = try String(contentsOf: try source("AskPanel.swift"), encoding: .utf8)
        XCTAssertTrue(ask.contains("ListSkeleton(message: Copy.AskWords.asking"), "asking reads over the still skeleton")
    }

    /// DR-48 — the Reader's "Noted from this conversation" row is a row: its current row is a selection, drawn by the
    /// shared fill (the cited span's wash is `CitedSpan`'s, in the text, and untouched).
    func testTheReadersNotedRowUsesTheSharedFill() throws {
        let text = try String(contentsOf: try source("ReaderColumn.swift"), encoding: .utf8)
        XCTAssertTrue(text.contains(".rowHover($hovering, selected: isCurrent)"))
    }

    /// The type ladder (DR-16, §4) — a `Text`, `Label` or field set at a size and weight the theme already names uses
    /// that token (13 → `bodyFont`, 13 medium → `rowFont`, 14 → `detailBodyFont`, 12 → `metaFont`, 12 medium →
    /// `metaMediumFont`, 11 → `captionFont`), and a glyph at 14, 12 or 10 regular is its icon role (DR-53: `list`,
    /// `inline`, `badge`). Round 3 moved 136 such literals; off-ladder sizes (10, 13 semibold, 14 medium …) are listed
    /// in §9, not hidden.
    func testALadderSizeIsSpelledByItsToken() throws {
        let pattern = try NSRegularExpression(pattern: #"CicadaTheme\.font\(size: (\d+)(?:, weight: \.(\w+))?\)"#)
        let text: Set<String> = ["13/regular", "13/medium", "14/regular", "12/regular", "12/medium", "11/regular"]
        let glyph: Set<String> = ["14/regular", "12/regular", "10/regular"]
        let receivers = ["Image(", "Text(", "Label(", "TextField(", "Button", "Toggle", "HStack", "VStack", "ZStack",
                         "Menu", "Link(", "Group", "LazyVStack", "ForEach"]
        var offenders: [String] = []
        var seen = 0
        for file in try sources() where !file.path.contains("/Theme/") {
            let all = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            for (i, line) in all.enumerated() where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") {
                let ns = line as NSString
                for match in pattern.matches(in: line, range: NSRange(location: 0, length: ns.length)) {
                    seen += 1
                    let weight = match.range(at: 2).location == NSNotFound ? "regular" : ns.substring(with: match.range(at: 2))
                    let key = "\(ns.substring(with: match.range(at: 1)))/\(weight)"
                    // The view the font is set on: the nearest opener on this line before the call, else above it.
                    var kind = "?"
                    var j = i
                    while j >= max(0, i - 6), kind == "?" {
                        let segment = j == i ? ns.substring(to: match.range.location) : all[j]
                        var best = -1
                        for r in receivers {
                            if let range = segment.range(of: r, options: .backwards) {
                                let at = segment.distance(from: segment.startIndex, to: range.lowerBound)
                                if at > best { best = at; kind = r }
                            }
                        }
                        j -= 1
                    }
                    let isText = ["Text(", "Label(", "TextField("].contains(kind)
                    if (isText && text.contains(key)) || (kind == "Image(" && glyph.contains(key)) {
                        offenders.append("\(file.lastPathComponent):\(i + 1) \(kind) \(key)")
                    }
                }
            }
        }
        XCTAssertEqual(offenders, [], "a ladder size is its CicadaTheme token (DR-16) and a glyph its icon role (DR-53)")
        XCTAssertGreaterThan(seen, 50, "the font-call pattern no longer matches — this lint would pass vacuously")
    }

    /// DR-70 — a padding or stack spacing that equals a spacing step is that token, so it scales with ⌘+/⌘−; a raw 4,
    /// 8, 12, 16, 24 or 32 did not. A cluster whose frame is spelled in points keeps its points, named here.
    func testASpacingStepIsSpelledByItsToken() throws {
        let fixedFrames: [String: String] = [
            "ImportFamilies.swift": "the family tile's mark cluster: 22 pt marks in a 48 pt frame, spelled in points",
            "AppearancePicker.swift": "the appearance miniatures: a 132 × 84 pt drawing of the app, spelled in points",
        ]
        let pattern = try NSRegularExpression(
            pattern: #"\.padding\((\.[a-zA-Z]+, )?(4|8|12|16|24|32)\)|(?<![a-zA-Z])spacing: (4|8|12|16|24|32)(?=[,)])"#)
        var offenders: [String] = []
        for file in try sources()
        where !file.path.contains("/Theme/") && fixedFrames[file.lastPathComponent] == nil {
            for (n, line) in try code(file) {
                if pattern.firstMatch(in: line, range: NSRange(location: 0, length: (line as NSString).length)) != nil {
                    offenders.append("\(file.lastPathComponent):\(n)")
                }
            }
        }
        XCTAssertEqual(offenders, [], "DR-70: use CicadaTheme.spacingXS … spacingXXL")
    }
}

/// DR-12 — every rounded rectangle is continuous: drawn through `CicadaTheme.shape(_:)`, never a bare
/// `RoundedRectangle(cornerRadius:` outside `Theme/`. DR-12 has named this lint since D landed; round 3 (2026-10-20)
/// moved the last 82 bare shapes and wrote it.
final class ContinuousCornerLintTests: XCTestCase {
    func testNoBareRoundedRectangleOutsideTheTheme() throws {
        var offenders: [String] = []
        let files = try ThemeTokenTests.swiftSources().filter { !$0.path.contains("/Theme/") }
        XCTAssertGreaterThan(files.count, 100, "found too few sources — the lint would pass vacuously")
        for file in files {
            let lines = try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines)
            for (n, line) in lines.enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && line.contains("RoundedRectangle(cornerRadius:") {
                offenders.append("\(file.lastPathComponent):\(n + 1)")
            }
        }
        XCTAssertEqual(offenders, [], "DR-12: draw through CicadaTheme.shape(_:)")
    }
}
