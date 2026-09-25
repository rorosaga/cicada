import XCTest
@testable import CicadaApp

/// Track I part b — the one turn-on (extracted from `OnThisMacStrip`, part a
/// T7) that the `+` strip, the Welcome's Start and Getting started share.
@MainActor
final class FoundTurnOnTests: XCTestCase {
    private func wiring() -> AgentWiringResponse {
        AgentWiringResponse(agents: [AgentWiring(id: "codex", installed: true, binary: "/bin/codex", recall: "off",
                                                 autosave: "off",
                                                 connect: [AgentWiringStep(step: "mcp", display: "d0", argv: ["a"], touches: [])],
                                                 detail: nil)],
                            python: "/R/api/.venv/bin/python", repo: "/R", memory: "/M")
    }

    private func deps(wiring: AgentWiringResponse? = nil, connect: AgentConnectOutcome = .done,
                      sync: Result<String, Error> = .success("412 bookmarks saved"),
                      readiness: FoundItem.Readiness? = .ready,
                      opened: @escaping (URL) -> Void = { _ in }, drop: IntakeOutcome? = nil) -> FoundTurnOnDeps {
        FoundTurnOnDeps(wiring: { wiring }, installRoot: URL(fileURLWithPath: "/R"),
                        connect: { _, _, _ in connect }, syncBrowser: { _ in try sync.get() },
                        readiness: { _ in readiness }, open: opened, commitDrop: { _ in drop }, refresh: {})
    }

    func testAnAgentRunsItsStepsAndReportsOn() async {
        let r = await FoundTurnOn.run(.agent("codex"), deps: deps(wiring: wiring()))
        XCTAssertEqual(r, .on(nil))
    }

    func testARefusalHandsBackTheLinesAndAnExitThreeIsItsSentence() async {
        let refused = await FoundTurnOn.run(.agent("codex"), deps: deps(wiring: wiring(), connect: .refused(["d0"])))
        XCTAssertEqual(refused, .refused(["d0"]))
        let invalid = await FoundTurnOn.run(.agent("codex"),
                                            deps: deps(wiring: wiring(), connect: .failed(Copy.foundInvalidSettings)))
        XCTAssertEqual(invalid, .failed(Copy.foundInvalidSettings))
    }

    private func unprobed(recall: String = "unknown", autosave: String = "unknown") -> AgentWiringResponse {
        AgentWiringResponse(agents: [AgentWiring(id: "codex", installed: true, binary: "/bin/codex", recall: recall,
                                                 autosave: autosave, connect: [], detail: nil)],
                            python: "/R/api/.venv/bin/python", repo: "/R", memory: "/M")
    }

    /// I-b final review, finding 1 — a probe that timed out has no steps; its
    /// Retry re-probes, and a healthy answer turns the row on.
    func testNoStepsReprobesAndAHealthyAnswerIsOn() async {
        var current = unprobed()
        var refreshes = 0
        let d = FoundTurnOnDeps(wiring: { current }, installRoot: URL(fileURLWithPath: "/R"),
                                connect: { _, _, _ in XCTFail("nothing to run"); return .done },
                                syncBrowser: { _ in "" }, readiness: { _ in nil }, open: { _ in },
                                commitDrop: { _ in nil },
                                refresh: { refreshes += 1; current = self.unprobed(recall: "on", autosave: "on") })
        let r = await FoundTurnOn.run(.agent("codex"), deps: d)
        XCTAssertEqual(refreshes, 1, "Retry is a re-probe")
        XCTAssertEqual(r, .on(nil))
    }

    /// …and a probe still unanswered hands the row back to the derived
    /// readiness (`.rechecked`), never a sticky `.failed` a later probe cannot clear.
    func testNoStepsAndStillUnknownIsNeverAStickyFailure() async {
        let r = await FoundTurnOn.run(.agent("codex"), deps: deps(wiring: unprobed()))
        XCTAssertEqual(r, .rechecked)
    }

    func testNoWiringMeansTheBackendIsDownNotThatTheAgentIsOff() async {
        let r = await FoundTurnOn.run(.agent("codex"), deps: deps(wiring: nil))
        XCTAssertEqual(r, .failed(Copy.foundBackendDown))
    }

    func testABlockedBrowserOpensFullDiskAccessAndReadsNothing() async {
        var opened: [URL] = []
        let r = await FoundTurnOn.run(.browser("safari-bookmarks"),
                                      deps: deps(readiness: .needsPermission, opened: { opened.append($0) }))
        XCTAssertEqual(r, .needsPermission)
        XCTAssertEqual(opened, [BrowserFileError.fullDiskAccessURL])
    }

    func testABrowserSyncReturnsItsOwnLine() async {
        let r = await FoundTurnOn.run(.browser("chrome-bookmarks"), deps: deps())
        XCTAssertEqual(r, .on("412 bookmarks saved"))
    }

    /// Round 4 phase A final review, finding 1 — the row's × during a first
    /// sync is a stop, said as a stop (R-SR11), and the browser stays on.
    func testStoppingABrowsersFirstSyncIsAStopNotAFailure() async {
        let r = await FoundTurnOn.run(.browser("brave-bookmarks"), deps: deps(sync: .failure(CancellationError())))
        XCTAssertEqual(r, .on(Copy.syncStopped))
    }

    func testCursorOpensItsDeepLinkAndClaudeDesktopFinishesInSettings() async {
        var opened: [URL] = []
        let cursor = await FoundTurnOn.run(.agent("cursor"), deps: deps(wiring: wiring(), opened: { opened.append($0) }))
        XCTAssertEqual(cursor, .openedApp)
        XCTAssertEqual(opened.first?.scheme, "cursor")
        let desktop = await FoundTurnOn.run(.agent("claude-desktop"), deps: deps())
        XCTAssertEqual(desktop, .finishInSettings(.agents))
    }

    func testADroppedExportIsCommittedAndSaysWhatCameIn() async {
        var outcome = IntakeOutcome(vendor: "chatgpt", origin: "chatgpt-export")
        outcome.created = 3
        let r = await FoundTurnOn.run(.dropped("x"), deps: deps(drop: outcome))
        XCTAssertEqual(r, .on(IntakeSummary.headline(outcome)))
    }

    // MARK: App sources (R-OB9) and untick (R-OB8)

    private func driver(start: @escaping () async throws -> String? = { "312 events" },
                        onStop: @escaping () -> Void = {}, keepsUp: Bool = true) -> AppSourceDriver {
        AppSourceDriver(start: start, stop: onStop, isOn: { true }, keepsUp: keepsUp)
    }

    func testARegisteredAppSourceStartsAndSaysWhatCameIn() async {
        var d = deps()
        d.apps = ["calendar-local": driver()]
        let r = await FoundTurnOn.run(.app("calendar-local"), deps: d)
        XCTAssertEqual(r, .on("312 events"))
    }

    func testAnUnregisteredAppStillFinishesInIntegrations() async {
        let r = await FoundTurnOn.run(.app("pinterest"), deps: deps())
        XCTAssertEqual(r, .finishInSettings(.integrations))
    }

    func testAnAppSourcesFailureIsItsRowsAndAStopIsAStop() async {
        var d = deps()
        d.apps = ["wispr-flow": driver(start: { throw BrowserImportActions.ImportActionError.failed("Needs access") }),
                  "notes": driver(start: { throw CancellationError() })]
        let failed = await FoundTurnOn.run(.app("wispr-flow"), deps: d)
        let stopped = await FoundTurnOn.run(.app("notes"), deps: d)
        XCTAssertEqual(failed, .failed(AddSourceSheet.friendlyError(BrowserImportActions.ImportActionError.failed("Needs access"))))
        XCTAssertEqual(stopped, .on(Copy.syncStopped))
    }

    /// The ids the Import table and the drivers share are plain strings, so the table stays nonisolated; this pins
    /// the one that mirrors another type's constant.
    func testTheWisprIdIsTheWatchersChannel() {
        XCTAssertEqual(AppSourceDrivers.wispr, LocalSourceWatcher.wisprChannel)
    }

    /// Seam 4 — the row's run and light are keyed by the reader's channel, so the ids must be those channels.
    func testTheContactsAndTabGroupIdsAreTheirReadersChannels() {
        XCTAssertEqual(AppSourceDrivers.contacts, ContactsReader.channel)
        XCTAssertEqual(AppSourceDrivers.tabGroups, TabGroupWatcher.channel)
        XCTAssertEqual(BrowserInventory.spec(id: "chrome")?.tabGroupsChannel, AppSourceDrivers.tabGroups)
    }

    func testContactsAndTabGroupsStartAndStopThroughTheirDrivers() async {
        var stopped: [String] = []
        var d = deps()
        d.apps = [AppSourceDrivers.contacts: driver(start: { "12 contacts" }, onStop: { stopped.append("contacts") }),
                  AppSourceDrivers.tabGroups: driver(start: { "2 open groups" }, onStop: { stopped.append("groups") })]
        let contacts = await FoundTurnOn.run(.app(AppSourceDrivers.contacts), deps: d)
        let groups = await FoundTurnOn.run(.app(AppSourceDrivers.tabGroups), deps: d)
        XCTAssertEqual(contacts, .on("12 contacts"))
        XCTAssertEqual(groups, .on("2 open groups"))
        await FoundTurnOn.stop(.app(AppSourceDrivers.contacts), deps: d)
        await FoundTurnOn.stop(.app(AppSourceDrivers.tabGroups), deps: d)
        XCTAssertEqual(stopped, ["contacts", "groups"])
    }

    // MARK: The live Contacts and tab-group drivers, over fakes (never the real address book or Chrome profile)

    private func contactsReader(_ store: FakeContactStore) -> ContactsReader {
        ContactsReader(store: store, api: FakeContactsAPI(), defaults: UserDefaults(suiteName: "seam4-\(UUID())")!,
                       bank: { "alpha" })
    }

    private func liveDeps(contacts: ContactsReader? = nil, tabGroups: TabGroupWatcher? = nil) -> FoundTurnOnDeps {
        var d = deps()
        d.apps = AppSourceDrivers.live(calendar: nil, local: nil, store: nil, contacts: contacts, tabGroups: tabGroups)
        return d
    }

    func testNoReaderRegistersNoDriverAndTheRowFinishesInIntegrations() async {
        XCTAssertTrue(AppSourceDrivers.live(calendar: nil, local: nil, store: nil).isEmpty)
        let r = await FoundTurnOn.run(.app(AppSourceDrivers.contacts), deps: liveDeps())
        XCTAssertEqual(r, .finishInSettings(.integrations))
    }

    func testContactsConnectsOnTheTickAndTheUntickDisconnects() async throws {
        let store = FakeContactStore()
        let reader = contactsReader(store)
        let d = liveDeps(contacts: reader)
        let r = await FoundTurnOn.run(.app(AppSourceDrivers.contacts), deps: d)
        XCTAssertEqual(r, .on(nil), "the channel's count line fills the row in")
        XCTAssertEqual(store.snapshots, 1, "one read, after the one prompt")
        XCTAssertTrue(try XCTUnwrap(d.apps[AppSourceDrivers.contacts]).isOn())
        await FoundTurnOn.stop(.app(AppSourceDrivers.contacts), deps: d)
        XCTAssertFalse(reader.enabled)
        XCTAssertFalse(try XCTUnwrap(d.apps[AppSourceDrivers.contacts]).isOn())
    }

    func testContactsRefusedIsItsOwnSentenceAndAnEmptyBookIsALine() async {
        let refused = FakeContactStore()
        refused.grant = false
        let denied = await FoundTurnOn.run(.app(AppSourceDrivers.contacts), deps: liveDeps(contacts: contactsReader(refused)))
        XCTAssertEqual(denied, .failed(Copy.contactsDenied))
        let blank = FakeContactStore()
        blank.records = []
        let empty = await FoundTurnOn.run(.app(AppSourceDrivers.contacts), deps: liveDeps(contacts: contactsReader(blank)))
        XCTAssertEqual(empty, .on(Copy.contactsEmpty), "nothing to read is not a failure")
    }

    func testTabGroupsTurnOnAndNoSessionsYetIsALineNotAFailure() async throws {
        // An empty temporary folder stands in for Chrome's Sessions/: nothing of the person's is opened.
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("seam4-\(UUID().uuidString)/Sessions")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir.deletingLastPathComponent()) }
        let api = FakeTabGroupsAPI()
        let watcher = TabGroupWatcher(api: api, defaults: UserDefaults(suiteName: "seam4-\(UUID())")!, directory: dir,
                                      makeWatch: { _, _ in nil }, bank: { "alpha" })
        let d = liveDeps(tabGroups: watcher)
        let r = await FoundTurnOn.run(.app(AppSourceDrivers.tabGroups), deps: d)
        XCTAssertEqual(r, .on(Copy.tabGroupsNoneYet))
        XCTAssertTrue(watcher.enabled, "the switch stays on; the watch catches Chrome's first save")
        XCTAssertEqual(api.payloads.count, 0)
        await FoundTurnOn.stop(.app(AppSourceDrivers.tabGroups), deps: d)
        XCTAssertFalse(watcher.enabled)
        XCTAssertFalse(try XCTUnwrap(d.apps[AppSourceDrivers.tabGroups]).isOn())
    }

    func testUntickTurnsOffABrowserOrAnAppAndNeverAnAgentOrADrop() async {
        var disabled: [String] = [], stopped = 0
        var d = deps()
        d.disableBrowser = { disabled.append($0) }
        d.apps = ["calendar-local": driver(onStop: { stopped += 1 })]
        await FoundTurnOn.stop(.browser("safari-bookmarks"), deps: d)
        await FoundTurnOn.stop(.app("calendar-local"), deps: d)
        await FoundTurnOn.stop(.agent("codex"), deps: d)
        await FoundTurnOn.stop(.dropped("x"), deps: d)
        XCTAssertEqual(disabled, ["safari-bookmarks"])
        XCTAssertEqual(stopped, 1, "an agent is disconnected in Settings → Agents; a drop is never un-imported")
    }
}
