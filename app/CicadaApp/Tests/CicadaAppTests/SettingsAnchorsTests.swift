import XCTest
@testable import CicadaApp

/// Hyrum audit B1 (2026-10-22): fourteen Settings sections became eleven. Every place that names a spot in Settings
/// must still land on the row it named: a search entry, a deep link in the app's own code (Home, onboarding, the
/// engine menu, an inline pointer), a saved `cicada.settingsSection`, and the old page anchors docs and harness scripts
/// name (`settings.row.page:<raw>`). A row is "drawn on a section" when one of that section's view files draws it.
final class SettingsAnchorsTests: XCTestCase {
    /// Which files draw each section's page, from the panel's `detailView` down. A new row file joins its section here.
    static let pageFiles: [SettingsSection: [String]] = [
        .general: ["Views/Settings/SettingsGeneralView.swift", "Views/Settings/SettingsDemoTourGroup.swift"],
        .you: ["Views/Settings/YouView.swift"],
        .privacy: ["Views/Settings/PrivacyView.swift"],
        .searchFiles: ["Views/Settings/SearchFilesView.swift", "Views/Settings/FadePaceCard.swift"],
        .sleep: ["Views/Settings/SettingsSleepView.swift", "Views/Settings/ScenerySettings.swift",
                 "Views/Settings/MascotSettings.swift"],
        .integrations: ["Views/Settings/IntegrationsView.swift", "Views/Settings/BrowsersSection.swift",
                        "Views/Settings/CalendarRow.swift", "Views/Settings/ContactsRow.swift"],
        .reading: ["Views/Settings/ReadingWebView.swift"],
        .agents: ["Views/Connect/ConnectView.swift", "Views/Connect/AutoRecallGroup.swift",
                  "Views/Connect/PageEditorsGroup.swift", "Views/Settings/CommandLineToolRow.swift"],
        .devices: ["Views/Settings/DevicesSettingsView.swift"],
        .skills: ["Views/Settings/SkillsView.swift"],
        .engines: ["Views/Settings/EnginesView.swift", "Views/Settings/EngineChooser.swift",
                   "Views/Connections/ConnectionsView.swift"],
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
    }

    /// Every search entry and every page lands on a row its section draws.
    func testEverySearchEntryLandsOnADrawnRow() throws {
        for entry in SettingsIndex.pageEntries + SettingsIndex.staticEntries where !entry.anchor.rawValue.contains(":")
            || Self.swiftName[entry.anchor.rawValue] != nil || entry.anchor == .page(entry.section) {
            XCTAssertTrue(try isDrawn(entry.anchor, on: entry.section),
                          "\(entry.id.rawValue) lands on \(entry.anchor.rawValue), not drawn on \(entry.section)")
        }
    }

    /// A saved selection, a deep link or a harness script that names a retired page opens its new home on the group
    /// that inherited it, never General.
    func testEveryRetiredSectionOpensWhereItMoved() throws {
        XCTAssertEqual(Set(SettingsSection.retired.keys), ["memory", "remote", "plansAndKeys"])
        for (raw, home) in SettingsSection.retired {
            XCTAssertNil(SettingsSection(rawValue: raw), "\(raw) is retired")
            XCTAssertEqual(SettingsSection.restored(from: raw), home.section, raw)
            XCTAssertEqual(home.row.rawValue, "page:\(raw)", "the group keeps the old header's anchor")
            XCTAssertTrue(try isDrawn(home.row, on: home.section), "\(raw)'s group is not drawn on \(home.section)")
            let found = SettingsIndex.staticEntries.first { $0.id == home.row }
            XCTAssertEqual(found?.section, home.section, "searching the old page's name finds its group")
        }
        XCTAssertEqual(SettingsSection.restored(from: "advanced"), .general)
        XCTAssertEqual(SettingsSection.restored(from: "bogus"), .general)
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

    /// "Settings → <section>" in what a person or an agent reads names a section that exists.
    func testNoCopyOrCurrentDocNamesARetiredSection() throws {
        let retired = ["Settings → Memory", "Settings → From anywhere", "Settings → Plans & keys",
                       "Settings → Search & files", "Settings → Agents → From anywhere", "Settings → General → Command-line"]
        let roots = ["app/CicadaApp/Sources", "api", "docs/architecture", "docs/connect-remote-apps.md",
                     "docs/settings-outside-the-app.md", "docs/RELEASING.md", ".claude/skills/verify-cicada", "scripts",
                     "Makefile"]
        var scanned = 0
        for root in roots {
            let url = Self.repo.appendingPathComponent(root)
            let files: [URL]
            if (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true {
                files = (FileManager.default.enumerator(at: url, includingPropertiesForKeys: nil)?
                    .compactMap { $0 as? URL } ?? [])
                    .filter { ["swift", "py", "md", "sh"].contains($0.pathExtension) && !$0.path.contains("/.build/") }
            } else {
                files = [url]
            }
            for file in files {
                guard let text = try? String(contentsOf: file, encoding: .utf8) else { continue }
                scanned += 1
                for phrase in retired {
                    XCTAssertFalse(text.contains(phrase), "\(file.path) still says \"\(phrase)\"")
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
