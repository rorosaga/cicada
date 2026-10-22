import XCTest
@testable import CicadaApp

/// Settings defaults (owner 2026-10-22: "Remove all those environment variables and stuff in the settings page. Let's
/// just work towards the good defaults."). These hold both halves of that change:
///
/// - **Removed stays removed.** No Settings page shows an environment variable, a file path, a raw model id or a
///   maintenance button; the rows that did are gone from the pages and from the search index, and Advanced is gone.
/// - **Trust stays reachable.** Every control over the person's data, privacy, consent and trust is still drawn and
///   still found by search (Hyrum audit 2026-10-22, "Kept on purpose").
///
/// Removing a control never removed its key: the backend routes, the `cicada` commands and every stored value stay.
final class SettingsDefaultsTests: XCTestCase {
    /// Every file a Settings page is drawn from.
    private static let pageDirs = ["/Views/Settings/", "/Views/Connect/", "/Views/Connections/"]

    private func pageSources() throws -> [(name: String, code: String)] {
        try ThemeTokenTests.swiftSources()
            .filter { f in Self.pageDirs.contains { f.path.contains($0) } }
            .map { ($0.lastPathComponent, try String(contentsOf: $0, encoding: .utf8)) }
    }

    /// Code lines only: a doc comment may say what left and why.
    private func codeLines(_ text: String) -> String {
        text.components(separatedBy: .newlines)
            .filter { !$0.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
            .joined(separator: "\n")
    }

    private var all: [SettingsEntry] { SettingsIndex.staticEntries + SettingsIndex.pageEntries }

    // MARK: Removed stays removed

    func testAdvancedIsGoneAndASavedSelectionStillOpens() {
        XCTAssertFalse(SettingsSection.allCases.map(\.rawValue).contains("advanced"))
        XCTAssertEqual(SettingsSection.restored(from: "advanced"), .general)
    }

    func testTheRemovedRowsAreNeitherIndexedNorDrawn() throws {
        let removed = ["backendStatus", "mcpCommand", "apiToken", "envOverrides", "settingsFile",
                       "engineModel", "searchModel", "searchIndex", "searchAdvanced", "enrichLinks", "agentsInstall"]
        let ids = Set(SettingsIndex.staticIDs.map(\.rawValue))
        let pages = try pageSources().map(\.code).joined(separator: "\n")
        for name in removed {
            XCTAssertFalse(ids.contains(name), "\(name) is still indexed")
            XCTAssertFalse(pages.contains("SettingsRow(.\(name),"), "\(name) is still drawn")
            XCTAssertFalse(pages.contains(".settingsRow(.\(name))"), "\(name) is still anchored")
        }
    }

    /// The screen never names a variable, a settings file or a home-relative path. Copy files are scanned too: a
    /// string a page shows lives there.
    func testNoSettingsPageOrItsCopyShowsAVariableOrAPath() throws {
        let copies = ["Copy+Settings.swift", "Copy+Devices.swift", "Copy+HomeSleep.swift", "Copy+SearchFiles.swift",
                      "Copy+SearchModel.swift"]
        let copyFiles = try ThemeTokenTests.swiftSources().filter { copies.contains($0.lastPathComponent) }
        XCTAssertEqual(copyFiles.count, copies.count)
        let sources = try pageSources() + copyFiles.map { ($0.lastPathComponent, try String(contentsOf: $0, encoding: .utf8)) }
        for (name, text) in sources {
            // Agents' own setup snippets carry the variable an agent's config needs; they are commands the person
            // pastes into that agent, not a setting (ConnectView's catalog, AgentSetupSteps).
            if ["ConnectView.swift", "AgentSetupSteps.swift"].contains(name) { continue }
            let code = codeLines(text)
            // String literals only: a Swift identifier like `ProcessInfo…["CICADA_HOME"]` is not on screen.
            let literals = code.components(separatedBy: "\"").enumerated().filter { $0.offset % 2 == 1 }.map(\.element)
            for literal in literals {
                for needle in ["CICADA_", "api/.env", "secrets.env", "~/.cicada", "api_token", "device_token", "LaunchAgent",
                               "Model id"] {
                    XCTAssertFalse(literal.contains(needle), "\(name) shows \"\(literal)\"")
                }
            }
        }
    }

    func testTheEngineChooserHasNoModelPicker() throws {
        let chooser = try XCTUnwrap(pageSources().first { $0.name == "EngineChooser.swift" }).code
        let code = codeLines(chooser)
        XCTAssertFalse(code.contains("Picker(\"Model\""))
        XCTAssertFalse(code.contains("TextField("), "no free-text model id")
        XCTAssertFalse(code.contains("selectedModel"))
        XCTAssertTrue(code.contains("providerPicker("), "the API key card still asks which key")
        XCTAssertTrue(code.contains("overageToggle("), "ruling 15's switch stays")
        let line = EngineChooser.previewLine(SleepEnginePreview(engine: "claude-cli", model: "sonnet", why: ""),
                                             label: Copy.EngineMenu.whenYouStart)
        XCTAssertFalse(line.contains("sonnet"), "Settings says who reads, not a model id")
    }

    func testThePinnedEngineIsSaidInWords() {
        let text = Copy.EngineMenu.pinnedByEnvironment("agent")
        XCTAssertFalse(text.contains("CICADA_"))
        XCTAssertFalse(text.contains(".env"))
    }

    func testUnsavedKeysFoldAndPlansStayOpen() {
        func connection(_ id: String, mode: String?, connected: Bool) throws -> ConnectionStatus {
            let login = mode.map { #","login":{"mode":"\#($0)"}"# } ?? ""
            let json = #"{"id":"\#(id)","label":"\#(id)","kind":"x","connected":\#(connected)\#(login)}"#
            return try JSONDecoder().decode(ConnectionStatus.self, from: Data(json.utf8))
        }
        guard let plan = try? connection("claude-plan", mode: "terminal", connected: false),
              let saved = try? connection("byok-anthropic", mode: "key", connected: true),
              let unsaved = try? connection("byok-openai", mode: "key", connected: false),
              let oauth = try? connection("byok-openrouter", mode: "oauth", connected: false) else {
            return XCTFail("ConnectionStatus no longer decodes its minimal shape")
        }
        let split = ConnectionsView.split([plan, saved, unsaved, oauth])
        XCTAssertEqual(ConnectionsView.unconnectedDetail(unsaved), Copy.keyCardDetail, "never the secrets path")
        XCTAssertNil(ConnectionsView.unconnectedDetail(saved))
        XCTAssertEqual(split.open.map(\.id), ["claude-plan", "byok-anthropic"])
        XCTAssertEqual(split.folded.map(\.id), ["byok-openai", "byok-openrouter"])
    }

    // MARK: Trust stays reachable

    /// Each kept control: drawn on its page, and a plain search lands on it.
    func testEveryTrustControlIsStillDrawnAndFound() throws {
        let kept: [(id: SettingsRowID, section: SettingsSection, query: String)] = [
            (.sleepUsePlan, .intelligence, "scheduled runs may use my plan"),  // ruling 4c
            (.engineChoice, .intelligence, "engine"),                           // ruling 31
            (.engineOverage, .intelligence, "extra usage"),                     // ruling 15
            (.engineAutoClaude, .intelligence, "claude plan"),
            (.autoUpdate, .general, "install updates automatically"),           // G182
            (.bankExport, .privacy, "export"),
            (.bankDelete, .privacy, "delete a bank"),
            (.memoryLocation, .privacy, "memory folder"),
            (.telemetry, .privacy, "usage ledger"),
            (.outboundConnectors, .privacy, "nightly connector check"),         // the three gates, read-only
            (.outboundFeeds, .privacy, "feeds and calendars"),
            (.outboundLogos, .privacy, "logos"),
            (.credentials, .privacy, "api keys"),
            (.transcripts, .privacy, "agent conversations"),
            (.memoryHome, .devices, "server"),                                  // This Mac or a server
            (.devicesList, .devices, "revoke"),                                 // ruling 28
            (.remoteSwitch, .devices, "connector"),                             // G135
            (.scenerySource, .sleep, "weather"),                                // G176's consent
            (.searchMeaning, .privacy, "understand what you mean"),             // a download is the person's click
            (.searchImages, .privacy, "understand images"),
        ]
        let ids = Set(SettingsIndex.staticIDs)
        for row in kept {
            XCTAssertTrue(ids.contains(row.id), "\(row.id.rawValue) left the index")
            XCTAssertEqual(SettingsIndex.entry(for: row.id, in: all)?.section, row.section, row.id.rawValue)
            let hits = SettingsIndex.search(row.query, in: all).prefix(5).map(\.entry.id)
            XCTAssertTrue(hits.contains(row.id) || hits.contains(SettingsIndex.entry(for: row.id, in: all)?.anchor ?? row.id),
                          "\"\(row.query)\" no longer finds \(row.id.rawValue)")
        }
    }

    /// D6 (2026-10-22): the trust controls that left Settings with their page keep a home there — the Agents page
    /// (page edits, remembers automatically), the Sources page (reading, bookmarks' why, Calendar, Contacts).
    func testEveryTrustControlThatLeftSettingsHasAHome() {
        let moved: [(SettingsRowID, AppTab)] = [
            (.agentsEditors, .agents), (.agentsAutoRecall, .agents), (.commandLineTool, .agents),
            (.readingAgent, .sources), (.readingExploreSignedIn, .sources), (.saveWhy, .sources),
            (.calendarApp, .sources), (.contactsApp, .sources),
        ]
        for (row, tab) in moved { XCTAssertEqual(SettingsIndex.retiredRows[row], .page(tab), row.rawValue) }
    }

    func testPrivacyStillExportsDeletesAndRemovesKeys() throws {
        let privacy = try XCTUnwrap(pageSources().first { $0.name == "PrivacyView.swift" }).code
        XCTAssertTrue(privacy.contains("APIClient.shared.exportBank("))
        XCTAssertTrue(privacy.contains("APIClient.shared.deleteBank("))
        XCTAssertTrue(privacy.contains("connectionsVM.removeKey("))
        XCTAssertTrue(privacy.contains("activateFileViewerSelecting"), "Show in Finder still opens the memory folder")
    }
}
