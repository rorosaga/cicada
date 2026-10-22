import XCTest
@testable import CicadaApp

/// Hyrum audit B1 and ruling 36 D6 (2026-10-22): fourteen Settings sections became eleven, then six. Every place that
/// names a spot in Settings must still land on the row it named — or, for a page that became a sidebar page, on that
/// page: a search entry, a deep link in the app's own code, a saved `cicada.settingsSection`, and the old page anchors
/// docs and harness scripts name (`settings.row.page:<raw>`). A row is "drawn on a section" when one of that section's
/// view files draws it.
final class SettingsAnchorsTests: XCTestCase {
    /// Which files draw each section's page, from the panel's `detailView` down. A new row file joins its section here.
    static let pageFiles: [SettingsSection: [String]] = [
        .general: ["Views/Settings/SettingsGeneralView.swift", "Views/Settings/SettingsDemoTourGroup.swift"],
        .you: ["Views/Settings/YouView.swift"],
        .intelligence: ["Views/Settings/IntelligenceView.swift"],
        .sleep: ["Views/Settings/SettingsSleepView.swift", "Views/Settings/ScenerySettings.swift",
                 "Views/Settings/MascotSettings.swift"],
        .devices: ["Views/Settings/DevicesSettingsView.swift"],
        .privacy: ["Views/Settings/PrivacyView.swift", "Views/Settings/SearchFilesView.swift",
                   "Views/Settings/FadePaceCard.swift"],
    ]

    /// The anchors whose raw value is not their Swift name.
    static let swiftName: [String: String] = [
        "page:memory": "memoryGroup", "page:remote": "fromAnywhere", "page:plansAndKeys": "plansAndKeys",
    ]

    private static let sources = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources/CicadaApp")
    private static var repo: URL {
        sources.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    }

    private func code(of section: SettingsSection) throws -> String {
        let files = try XCTUnwrap(Self.pageFiles[section], "\(section) has no files listed")
        return try files.map { try String(contentsOf: Self.sources.appendingPathComponent($0), encoding: .utf8) }
            .joined(separator: "\n")
    }

    /// Whether `row` is drawn on `section`'s page: its header, a `SettingsRow`, a `SettingsRowShell` or a `.settingsRow`.
    private func isDrawn(_ row: SettingsRowID, on section: SettingsSection) throws -> Bool {
        if row == .page(section) {
            let text = try code(of: section)
            return ["SettingsPage(section: .\(section.rawValue))", "SettingsDetailHeader(section: .\(section.rawValue))"]
                .contains { text.contains($0) }
        }
        let name = Self.swiftName[row.rawValue] ?? row.rawValue
        let text = try code(of: section)
        return ["SettingsRow(.\(name),", "SettingsRow(.\(name))", "SettingsRowShell(.\(name))", ".settingsRow(.\(name))"]
            .contains { text.contains($0) }
    }

    func testEveryPageMapsToItsFiles() {
        XCTAssertEqual(Set(Self.pageFiles.keys), Set(SettingsSection.allCases))
        XCTAssertEqual(SettingsSection.allCases, [.general, .you, .intelligence, .sleep, .devices, .privacy],
                       "ruling 36 D6: six sections, in this order")
    }

    /// Every search entry and every page lands on a row its section draws.
    func testEverySearchEntryLandsOnADrawnRow() throws {
        for entry in SettingsIndex.pageEntries + SettingsIndex.staticEntries where !entry.anchor.rawValue.contains(":")
            || Self.swiftName[entry.anchor.rawValue] != nil || entry.anchor == .page(entry.section) {
            XCTAssertTrue(try isDrawn(entry.anchor, on: entry.section),
                          "\(entry.id.rawValue) lands on \(entry.anchor.rawValue), not drawn on \(entry.section)")
        }
    }

    /// A saved selection, a deep link or a harness script that names a retired page opens its new home: the row that
    /// inherited it, or the sidebar page it became — never blank.
    func testEveryRetiredSectionOpensWhereItMoved() throws {
        XCTAssertEqual(Set(SettingsSection.retired.keys),
                       ["memory", "remote", "plansAndKeys", "engines", "searchFiles", "integrations", "reading",
                        "agents", "skills"])
        for (raw, home) in SettingsSection.retired {
            XCTAssertNil(SettingsSection(rawValue: raw), "\(raw) is retired")
            let landing = SettingsSection.restoredLanding(from: raw, legacyAgentsMode: nil)
            switch home {
            case let .settings(section, row):
                let row = try XCTUnwrap(row)
                XCTAssertEqual(SettingsSection.restored(from: raw), section, raw)
                XCTAssertTrue(try isDrawn(row, on: section), "\(raw)'s row is not drawn on \(section)")
                XCTAssertEqual(landing.section, section, raw)
                XCTAssertEqual(landing.row, row, "a saved \(raw) lands on its row, not the page's top")
            case let .page(tab):
                XCTAssertTrue([AppTab.sources, .agents, .skills].contains(tab), raw)
                XCTAssertEqual(landing.section, .general, "the panel cannot show a page; it opens General")
                XCTAssertNil(landing.row)
            case .readingInBrowser:
                XCTAssertEqual(raw, "reading", "Reading the web's switches, in the Sources page's sheet")
                XCTAssertEqual(landing.section, .general)
            }
        }
        // B1's three keep the old header's anchor.
        for raw in ["memory", "remote", "plansAndKeys"] where raw != "memory" {
            XCTAssertEqual(SettingsSection.retired[raw]?.row?.rawValue, "page:\(raw)")
        }
        let anywhere = SettingsSection.restoredLanding(from: "agents", legacyAgentsMode: "anywhere")
        XCTAssertEqual(anywhere.section, .devices)
        XCTAssertEqual(anywhere.row, .fromAnywhere)
        XCTAssertNil(SettingsSection.restoredLanding(from: "sleep", legacyAgentsMode: nil).row, "a living page opens at its top")
        XCTAssertEqual(SettingsSection.restored(from: "advanced"), .general)
        XCTAssertEqual(SettingsSection.restored(from: "bogus"), .general)
    }

    /// D6: a row that left with its page keeps a home — drawn on a surviving section, or the page it went to.
    func testEveryRetiredRowHasAHome() throws {
        for (row, home) in SettingsIndex.retiredRows {
            XCTAssertFalse(SettingsIndex.staticIDs.contains(row), "\(row.rawValue) is both live and retired")
            if case let .settings(section, target) = home {
                XCTAssertTrue(try isDrawn(try XCTUnwrap(target), on: section), "\(row.rawValue) → \(section)")
            }
        }
    }

    /// `AppRouter.open(_:)` sends a page home to its tab, Settings closed; a Settings home opens the panel on its row.
    @MainActor
    func testTheRouterOpensEachKindOfHome() {
        let router = AppRouter()
        router.openSettings(.general)
        router.open(.page(.agents))
        XCTAssertFalse(router.settingsOpen)
        XCTAssertEqual(router.pendingTab, .agents)
        router.open(.readingInBrowser)
        XCTAssertEqual(router.pendingTab, .sources)
        XCTAssertTrue(router.pendingReadingSheet, "the Sources page opens Reading in your browser")
        router.open(.settings(.intelligence, .plansAndKeys))
        XCTAssertTrue(router.settingsOpen)
        XCTAssertEqual(router.pendingSettings?.section, .intelligence)
        XCTAssertEqual(router.pendingSettings?.row, .plansAndKeys)
    }

    /// Every link the app's own code makes into Settings (`openSettings`, `SettingsInlineLink`, `SettingsSectionLink`,
    /// `focus.go`, a palette destination) names a row its section draws.
    func testEveryDeepLinkInTheAppLandsOnADrawnRow() throws {
        let pattern = #"(?:openSettings\(|SettingsInlineLink\(section: |SettingsSectionLink\(section: |focus\.go\(|\.settings\()\.([a-zA-Z]+), (?:row: )?\.([a-zA-Z]+)\b"#
        let regex = try NSRegularExpression(pattern: pattern)
        var checked = 0
        for file in try ThemeTokenTests.swiftSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
                let sectionName = String(text[Range(match.range(at: 1), in: text)!])
                let rowName = String(text[Range(match.range(at: 2), in: text)!])
                guard rowName != "page", rowName != "channel", rowName != "skill" else { continue }
                let section = try XCTUnwrap(SettingsSection.allCases.first { "\($0)" == sectionName },
                                            "\(file.lastPathComponent) links to .\(sectionName), which is not a section")
                let rawRow = Self.swiftName.first { $0.value == rowName }?.key ?? rowName
                XCTAssertTrue(try isDrawn(SettingsRowID(rawRow), on: section),
                              "\(file.lastPathComponent) links to \(sectionName) › \(rowName), which that page does not draw")
                checked += 1
            }
        }
        XCTAssertGreaterThan(checked, 10, "a scan over nothing passes vacuously")
    }

    /// "Settings → <section>" in what a person or an agent reads names a section that exists, even when a line break
    /// or a comment marker falls inside the phrase. `docs/plans`, `docs/specs`, `docs/goals` and `docs/research` are
    /// dated history and keep the names of their day.
    func testNoCopyOrCurrentDocNamesARetiredSection() throws {
        let gap = #"[\s/#*]+"#
        let retired = [
            "Memory\\b", "From\(gap)anywhere", "Plans\(gap)&\(gap)keys", "Search\(gap)&\(gap)files",
            "Search\(gap)&\(gap)memory", "Devices\(gap)&\(gap)access", "Agents\\b", "General\(gap)→\(gap)Command",
            "Engines\\b", "Integrations\\b", "Reading\(gap)the\(gap)web", "Skills\\b",
        ].map { try! NSRegularExpression(pattern: "Settings\(gap)→\(gap)" + $0) }
        func caught(_ text: String) -> Bool {
            retired.contains { $0.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) != nil }
        }
        XCTAssertTrue(caught("devices (Settings →\n/// Engines). DR-59"), "a phrase broken by a comment line")
        XCTAssertTrue(caught("open Settings → Plans & keys"))
        XCTAssertFalse(caught("open Settings → Devices → Apps outside this machine"))
        XCTAssertTrue(caught("Settings → Search & memory"))
        XCTAssertFalse(caught("Settings → Intelligence"))
        let roots = ["app/CicadaApp/Sources", "api", "mcp", "skills", "plugins", "scripts", "Makefile", "CLAUDE.md",
                     "install.md", "docs/architecture", "docs/design", "docs/connect-remote-apps.md",
                     "docs/settings-outside-the-app.md", "docs/RELEASING.md", ".claude/skills/verify-cicada"]
        var scanned = 0
        for root in roots {
            let url = Self.repo.appendingPathComponent(root)
            let files: [URL]
            if (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true {
                files = (FileManager.default.enumerator(at: url, includingPropertiesForKeys: nil)?
                    .compactMap { $0 as? URL } ?? [])
                    .filter { ["swift", "py", "md", "sh", "json", "txt"].contains($0.pathExtension)
                        && !$0.path.contains("/.build/") && !$0.path.contains("/.venv/") && !$0.path.contains("/node_modules/") }
            } else {
                files = [url]
            }
            for file in files {
                guard var text = try? String(contentsOf: file, encoding: .utf8) else { continue }
                // DESIGN_RULES' rulings log is dated history: its lines are never edited, and keep their day's names.
                if file.lastPathComponent == "DESIGN_RULES.md", let log = text.range(of: "## 9. Rulings log"),
                   let next = text.range(of: "## 10.", range: log.upperBound..<text.endIndex) {
                    text.removeSubrange(log.lowerBound..<next.lowerBound)
                }
                scanned += 1
                let range = NSRange(text.startIndex..., in: text)
                for regex in retired {
                    if let hit = regex.firstMatch(in: text, range: range), let found = Range(hit.range, in: text) {
                        XCTFail("\(file.path) still says \"\(text[found])\"")
                    }
                }
            }
        }
        XCTAssertGreaterThan(scanned, 100, "a scan over nothing passes vacuously")
    }

    /// Reading's method pickers wait under a fold while the switch is off; a landing on any of them opens it.
    func testALandingOnAReadingMethodOpensItsFold() {
        XCTAssertTrue(ReadingMethodsFold.holds(.readingMethods))
        XCTAssertTrue(ReadingMethodsFold.holds(.watchingMethods))
        XCTAssertTrue(ReadingMethodsFold.holds(.readingMethod("skill")))
        XCTAssertTrue(ReadingMethodsFold.holds(.watchingMethod("browser")))
        XCTAssertFalse(ReadingMethodsFold.holds(.readingAgent))
        XCTAssertFalse(ReadingMethodsFold.holds(.readingSites))
    }
}
