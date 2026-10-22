import XCTest
@testable import CicadaApp

/// G139 — the Cicada group's new pages (design §2.2; R-O17, R-O18, R-O21).
final class CicadaPagesTests: XCTestCase {
    func testTheCicadaGroupReadsInTheDesignsOrder() {
        // Hyrum audit B1 (2026-10-22): Memory joined Search & files, now Search & memory.
        XCTAssertEqual(SettingsGroup.cicada.sections, [.general, .you, .privacy, .searchFiles, .sleep])
        // Settings defaults (owner 2026-10-22): Advanced is gone. B1: Plans & keys is a group on Engines.
        XCTAssertEqual(SettingsGroup.enginesAndKeys.sections, [.engines])
        XCTAssertNil(SettingsSection(rawValue: "advanced"))
        XCTAssertEqual(SettingsSection.restored(from: "advanced"), .general, "a saved Advanced reopens on General")
        for section in [SettingsSection.you, .privacy, .searchFiles] {
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

    /// The Settings file's wire still decodes (`/status` sends it for the CLI); nothing in the app shows it any more.
    func testSettingsFileSourcesStillDecode() throws {
        let body = #"{"sleep":{"status":"idle","stage":0,"totalStages":5},"inbox":{"total":0,"byKind":{}},"episodes":{"unprocessed":0},"settings":{"file":"api/.env","fromFile":["CICADA_AGENT_MAX_CONCURRENCY"],"fromEnvironment":[],"replacedByEnvironment":[]}}"#
        let status = try JSONDecoder().decode(StatusSnapshot.self, from: Data(body.utf8))
        XCTAssertEqual(status.settings?.fromFile, ["CICADA_AGENT_MAX_CONCURRENCY"])
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

    // MARK: Memory

    /// Settings defaults (owner 2026-10-22): Memory keeps How things fade; the link-preview button left (Sleep's
    /// tail describes saved links on every run). Hyrum audit B1: the card is drawn on Search & memory, under the old
    /// page's anchor.
    func testHowThingsFadeIsOnSearchAndMemory() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Settings/SearchFilesView.swift") })
        let page = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(page.contains("FadePaceCard()\n                .settingsRow(.memoryGroup)"))
        XCTAssertFalse(page.contains("enrich-links"), "no maintenance button")
    }

    /// R-O17 — the dedup sweep has no row until its endpoint stops blocking the
    /// event loop, reaches the Inbox on a dry run and commits what it merges.
    func testNoPageCallsTheDedupSweep() throws {
        for file in try ThemeTokenTests.swiftSources() {
            XCTAssertFalse(try String(contentsOf: file, encoding: .utf8).contains("dedup-sweep"), file.lastPathComponent)
        }
    }
}
