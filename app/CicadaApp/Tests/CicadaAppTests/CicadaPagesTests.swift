import XCTest
@testable import CicadaApp

/// G139 — the Cicada group's new pages (design §2.2; R-O17, R-O18, R-O21).
final class CicadaPagesTests: XCTestCase {
    func testTheCicadaGroupReadsInTheDesignsOrder() {
        XCTAssertEqual(SettingsGroup.cicada.sections, [.general, .you, .privacy, .memory, .sleep])
        XCTAssertEqual(SettingsGroup.enginesAndKeys.sections, [.engines, .plansAndKeys, .advanced])
        for section in [SettingsSection.you, .privacy, .memory, .advanced] {
            XCTAssertLessThanOrEqual(section.subtitle.count, 60)
            XCTAssertFalse(section.subtitle.lowercased().contains(section.title.lowercased()))
        }
    }

    // MARK: You — only a real change is written (the PUT commits the owner page)

    func testOwnerDraftWritesOnlyARealChange() {
        let saved = OwnerSettings(name: "Alex Example", handle: nil, email: nil, observer: "alex-example", entityId: "alex-example")
        var draft = OwnerDraft(saved)
        XCTAssertNil(draft.update(from: saved), "nothing changed, nothing to commit")
        draft.handle = "  octocat "
        XCTAssertEqual(draft.update(from: saved)?.handle, "octocat")
        draft.name = "   "
        XCTAssertNil(draft.update(from: saved), "the backend 400s on a blank name; never send it")
        draft = OwnerDraft(saved)
        draft.email = ""
        XCTAssertNil(draft.update(from: saved), "empty and absent are the same fact")
    }

    // MARK: Wire tolerance

    func testNewStatusFieldsDecodeAndAnOlderPayloadStillDoes() throws {
        let old = #"{"sleep":{"status":"idle","stage":0,"totalStages":5},"inbox":{"total":0,"byKind":{}},"episodes":{"unprocessed":0}}"#
        let decoded = try JSONDecoder().decode(StatusSnapshot.self, from: Data(old.utf8))
        XCTAssertNil(decoded.telemetry)
        XCTAssertNil(decoded.gates)
        let new = #"{"sleep":{"status":"idle","stage":0,"totalStages":5},"inbox":{"total":0,"byKind":{}},"episodes":{"unprocessed":0},"telemetry":"off","gates":{"connectorFetch":true,"feedFetch":false,"logoFetch":true},"envOverrides":["CICADA_LLM_MODE"]}"#
        let full = try JSONDecoder().decode(StatusSnapshot.self, from: Data(new.utf8))
        XCTAssertEqual(full.telemetry, "off")
        XCTAssertEqual(full.gates?.feedFetch, false)
        XCTAssertEqual(full.envOverrides, ["CICADA_LLM_MODE"])
    }

    func testBanksAndHealthDecodeTheirNewFieldsTolerantly() throws {
        let bank = try JSONDecoder().decode(MemoryBank.self, from: Data(#"{"name":"default","active":true,"entityCount":1,"episodeCount":2,"createdAt":"","legacy":true}"#.utf8))
        XCTAssertTrue(bank.legacy)
        let older = try JSONDecoder().decode(MemoryBank.self, from: Data(#"{"name":"x","active":false,"entityCount":0,"episodeCount":0,"createdAt":""}"#.utf8))
        XCTAssertFalse(older.legacy)
        let health = try JSONDecoder().decode(HealthSnapshot.self, from: Data(#"{"memoryRoot":"/tmp/m","version":"0.9","entityCount":3,"episodeCount":4}"#.utf8))
        XCTAssertEqual(health.version, "0.9")
        XCTAssertEqual(health.entityCount, 3)
        let trash = try JSONDecoder().decode(BankTrashResult.self, from: Data(#"{"banks":[],"active":"default","trashedTo":".trash/scratch-20260923T100000Z"}"#.utf8))
        XCTAssertEqual(trash.trashedTo, ".trash/scratch-20260923T100000Z")
    }

    // MARK: Advanced — every switch the backend can report has plain words

    func testEveryKnownEnvSwitchHasAMeaning() throws {
        let py = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("api/services/env_overrides.py")
        let text = try String(contentsOf: py, encoding: .utf8)
        let known = text.components(separatedBy: "\"").filter { $0.hasPrefix("CICADA_") && !$0.contains("<") && !$0.contains("{") }
        XCTAssertFalse(known.isEmpty)
        for name in Set(known) {
            XCTAssertNotNil(EnvOverrideCopy.meaning(name), "\(name) is reported by the backend but has no plain words")
        }
    }

    // MARK: Memory

    func testMaintenanceLinesSayWhatHappenedInWords() {
        XCTAssertEqual(MemoryMaintenanceText.index(SearchIndexStatus(state: "building", builtAt: nil, documents: nil)),
                       "Building for the first time…")
        XCTAssertEqual(MemoryMaintenanceText.index(SearchIndexStatus(state: "unavailable", builtAt: nil, documents: nil)),
                       "Not available on this Mac — search still works from your pages.")
        XCTAssertTrue((MemoryMaintenanceText.index(SearchIndexStatus(state: "ready", builtAt: nil, documents: 1200)) ?? "").hasPrefix("Up to date"))
        XCTAssertEqual(MemoryMaintenanceText.links(EnrichLinksReport(summarized: 3, remaining: 12), locale: Locale(identifier: "en_US")),
                       "Described 3 links · 12 still to go")
        XCTAssertEqual(MemoryMaintenanceText.links(EnrichLinksReport(), locale: Locale(identifier: "en_US")),
                       "Nothing to fetch — every saved link has a description.")
    }

    /// R-O17 — the dedup sweep has no row until its endpoint stops blocking the
    /// event loop, reaches the Inbox on a dry run and commits what it merges.
    func testNoPageCallsTheDedupSweep() throws {
        for file in try ThemeTokenTests.swiftSources() {
            XCTAssertFalse(try String(contentsOf: file, encoding: .utf8).contains("dedup-sweep"), file.lastPathComponent)
        }
    }
}
