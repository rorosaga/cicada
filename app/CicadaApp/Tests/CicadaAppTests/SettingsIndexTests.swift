import XCTest
@testable import CicadaApp

/// G139, design §2.4/§2.6 — the Settings index.
final class SettingsIndexTests: XCTestCase {
    private var all: [SettingsEntry] { SettingsIndex.staticEntries + SettingsIndex.pageEntries }

    func testEveryStaticRowIsIndexedExactlyOnce() {
        let ids = SettingsIndex.staticEntries.map(\.id)
        XCTAssertEqual(ids.count, Set(ids).count, "a row indexed twice")
        XCTAssertEqual(Set(ids), Set(SettingsIndex.staticIDs), "an id with no entry, or an entry with no id")
    }

    func testEverySectionHasAPageEntryAnchoredOnItsHeader() {
        XCTAssertEqual(SettingsIndex.pageEntries.map(\.section), SettingsSection.allCases)
        for entry in SettingsIndex.pageEntries { XCTAssertEqual(entry.anchor, .page(entry.section)) }
    }

    func testRankingFixtures() {
        XCTAssertEqual(SettingsIndex.search("zoom", in: all).first?.entry.id, .textSize)
        XCTAssertEqual(SettingsIndex.search("phone", in: all).first?.entry.id, .remoteSwitch)
        XCTAssertEqual(SettingsIndex.search("dark", in: all).first?.entry.id, .appearance)
        XCTAssertTrue(SettingsIndex.search("schedule", in: all).contains { $0.entry.id == .sleepRuns })
        XCTAssertEqual(SettingsIndex.search("engines", in: all).first?.entry.id, .page(.engines))
        XCTAssertEqual(SettingsIndex.search("tele", in: all).first?.entry.id, .telemetry)
        XCTAssertEqual(SettingsIndex.search("backup", in: all).first?.entry.id, .bankExport)
    }

    func testSectionTitlesFindTheirRowsAtLowWeight() {
        let hits = SettingsIndex.search("sleep", in: all)
        XCTAssertTrue(hits.contains { $0.entry.id == .sleepRuns })
        XCTAssertEqual(hits.first?.entry.id, .page(.sleep), "the section itself outranks its rows")
    }

    func testFromAnywhereRowsLandOnItsHeader() {
        let entry = SettingsIndex.staticEntries.first { $0.id == .remoteSwitch }
        XCTAssertEqual(entry?.anchor, .page(.remote), "R-O12 — Track R's view carries no anchors")
    }

    func testDynamicEntriesComeFromSnapshotsAndCarryNoSecret() {
        let connection = ConnectionStatus(id: "byok-openai", label: "OpenAI API key", kind: "usage",
                                          available: true, connected: true, plan: nil, planLabel: nil,
                                          tier: nil, account: "bob-example@example.com", priceUsdMonth: nil,
                                          priceNote: nil, billing: "usage", engineRole: nil, detail: nil, login: nil)
        let agents = AgentSetupCatalog.all(home: "/x/repo")
        let entries = SettingsIndex.dynamicEntries(channels: [], harnessRows: [], exportOnly: [.youtube],
                                                   connections: [connection], agents: agents)
        XCTAssertTrue(entries.contains { $0.id == .connection("byok-openai") && $0.section == .plansAndKeys })
        XCTAssertTrue(entries.contains { $0.id == .agent("claude-code") && $0.section == .agents })
        XCTAssertTrue(entries.contains { $0.id == .exportOnly("youtube") && $0.section == .integrations })
        let text = entries.map { ([$0.title, $0.detail ?? ""] + $0.keywords).joined(separator: " ") }.joined()
        XCTAssertFalse(text.contains("example.com"), "an account line is not a search keyword")
        XCTAssertFalse(text.contains("/x/repo"), "a command is not a search keyword")
    }

    func testCountsAndGroupsFollowSidebarOrder() {
        let hits = SettingsIndex.search("engine", in: all)
        let groups = SettingsIndex.grouped(hits).map(\.section)
        XCTAssertEqual(groups, SettingsSection.allCases.filter { groups.contains($0) }, "results read in sidebar order")
        XCTAssertEqual(SettingsIndex.counts(hits)[.engines], hits.filter { $0.entry.section == .engines }.count)
    }

    func testLiveValues() {
        var inputs = SettingsLiveValue.Inputs()
        inputs.scheduleMode = "daily"
        inputs.appearance = .system
        inputs.uiScale = 1.2
        XCTAssertEqual(SettingsLiveValue.text(for: .sleepRuns, inputs), "Daily")
        XCTAssertEqual(SettingsLiveValue.text(for: .appearance, inputs), "System")
        XCTAssertEqual(SettingsLiveValue.text(for: .textSize, inputs), "120%")
        XCTAssertNil(SettingsLiveValue.text(for: .runSetup, inputs))
    }
}
