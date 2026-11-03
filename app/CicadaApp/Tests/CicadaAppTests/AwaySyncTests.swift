import XCTest
@testable import CicadaApp

/// G229 — the sync the app does when it opens after being closed: which readers it lists, when it is over, what it
/// tells the backend, and the words the Sleep page and Home say (owner 2026-11-03: "there is no syncing indicator").
@MainActor
final class AwaySyncTests: XCTestCase {
    private let en = Locale(identifier: "en_US")
    private var t0 = Date(timeIntervalSince1970: 1_800_000_000)

    private func probe(_ id: String, _ label: String, _ phase: ReaderPhase) -> ReaderProbe {
        ReaderProbe(channel: id, label: label, phase: phase)
    }

    // MARK: The rules

    func testAReaderIsListedOnceSeenReadingAndDoneWhenItStops() {
        var rules = AwaySyncRules()
        let quiet = probe("notes", "Notes", .idle)
        XCTAssertEqual(rules.readers([quiet], now: t0), [], "never seen reading: nothing to catch up on")
        let reading = rules.readers([probe("imessage", "Messages", .reading), quiet], now: t0)
        XCTAssertEqual(reading.map(\.state), ["reading"])
        let after = rules.readers([probe("notes", "Notes", .reading), probe("imessage", "Messages", .idle)], now: t0)
        XCTAssertEqual(after.map(\.label), ["Messages", "Notes"], "first seen first: the list never reshuffles")
        XCTAssertEqual(after.map(\.state), ["done", "reading"])
    }

    func testASourceThatCannotBeReadIsListedWithItsFix() {
        var rules = AwaySyncRules()
        let out = rules.readers([probe("calendar-local", "Calendar", .failed(Copy.calendarDenied))], now: t0)
        XCTAssertEqual(out, [AwaySyncReader(channel: "calendar-local", label: "Calendar", state: "failed",
                                            fix: Copy.calendarDenied)])
    }

    func testItIsOverOnlyAfterTheSettleAndAQuietMoment() {
        var rules = AwaySyncRules()
        let heard = t0
        let reading = rules.readers([probe("imessage", "Messages", .reading)], now: t0)
        XCTAssertFalse(rules.settle(reading, heardAt: heard, now: t0.addingTimeInterval(30)), "still reading")
        let idle = rules.readers([probe("imessage", "Messages", .idle)], now: t0.addingTimeInterval(31))
        XCTAssertFalse(rules.settle(idle, heardAt: nil, now: t0.addingTimeInterval(60)), "the backend never heard")
        var early = AwaySyncRules()
        XCTAssertFalse(early.settle([], heardAt: heard, now: t0.addingTimeInterval(AwaySyncRules.settle - 1)),
                       "readers arm one by one after launch")
        XCTAssertTrue(early.settle([], heardAt: heard, now: t0.addingTimeInterval(AwaySyncRules.settle)))
        // Quiet: the last reader stopped a moment ago.
        var quiet = AwaySyncRules()
        _ = quiet.readers([probe("imessage", "Messages", .reading)], now: t0.addingTimeInterval(20))
        XCTAssertFalse(quiet.settle([], heardAt: heard, now: t0.addingTimeInterval(21)))
        XCTAssertTrue(quiet.settle([], heardAt: heard, now: t0.addingTimeInterval(20 + AwaySyncRules.quiet)))
        XCTAssertTrue(quiet.settle(reading, heardAt: heard, now: t0.addingTimeInterval(99)), "once over, over")
    }

    // MARK: The tracker

    private func defaults() -> UserDefaults {
        let name = "AwaySyncTests.\(UUID().uuidString)"
        let d = UserDefaults(suiteName: name)!
        d.removePersistentDomain(forName: name)
        return d
    }

    func testTheAwayWindowIsWhenTheAppWasLastOpenAndTheTrackerReportsUntilDone() async {
        let store = defaults()
        AppPresence(defaults: store).stamp(t0.addingTimeInterval(-5 * 3600))
        var clock = t0
        var phases: [ReaderProbe] = [probe("imessage", "Messages", .reading)]
        var sent: [AwaySyncReport] = []
        let tracker = AwaySyncTracker(probe: { phases }, send: { report in
            sent.append(report)
            return MachineAwaySync(state: report.done ? "done" : "reading", readers: report.readers, arrived: 9,
                                   newCount: 2)
        }, defaults: store, now: { clock })
        tracker.begin()
        XCTAssertEqual(tracker.report?.awaySince, t0.addingTimeInterval(-5 * 3600))
        XCTAssertEqual(AppPresence(defaults: store).last(), t0, "this launch is stamped after the window was read")
        await tracker.step()
        XCTAssertEqual(sent.count, 1)
        XCTAssertEqual(tracker.view?.isReading, true)
        clock = t0.addingTimeInterval(1)
        await tracker.step()
        XCTAssertEqual(sent.count, 1, "an unchanged word is not sent again")
        phases = [probe("imessage", "Messages", .idle)]
        clock = t0.addingTimeInterval(AwaySyncRules.settle + AwaySyncRules.quiet + 1)
        await tracker.step()
        XCTAssertEqual(sent.last?.done, true)
        XCTAssertEqual(sent.last?.readers.map(\.state), ["done"])
        XCTAssertEqual(tracker.view?.state, "done")
        phases = [probe("imessage", "Messages", .reading)]
        clock = clock.addingTimeInterval(5)
        let count = sent.count
        await tracker.step()
        XCTAssertEqual(sent.count, count, "a reader that starts after the sync is over is not part of it")
        clock = clock.addingTimeInterval(AwaySyncTracker.shownAfterDone)
        await tracker.step()
        XCTAssertNil(tracker.view, "a finished sync is shown for a while, then the line goes")
        XCTAssertTrue(tracker.finished)
    }

    func testARefusedReportShowsNothingAndIsTriedAgainLater() async {
        var clock = t0
        var attempts = 0
        let tracker = AwaySyncTracker(probe: { [] }, send: { _ in
            attempts += 1
            throw APIError.httpError(409, "demo")
        }, defaults: defaults(), now: { clock })
        tracker.begin()
        await tracker.step()
        clock = t0.addingTimeInterval(1)
        await tracker.step()
        XCTAssertEqual(attempts, 1, "not every second")
        clock = t0.addingTimeInterval(AwaySyncTracker.retryAfter)
        await tracker.step()
        XCTAssertEqual(attempts, 2)
        XCTAssertNil(tracker.view)
    }

    // MARK: The words

    func testTheLineSaysWhatIsSyncingHowMuchCameInAndThatItIsDone() {
        let reading = MachineAwaySync(state: "reading", readers: [
            .init(channel: "imessage", label: "Messages", state: "reading"),
            .init(channel: "notes", label: "Notes", state: "reading"),
            .init(channel: "calendar-local", label: "Calendar", state: "done")], arrived: 9, newCount: 14)
        XCTAssertEqual(AwaySyncWords.line(reading, locale: en),
                       "Syncing Messages and Notes — 14 new conversations so far. "
                       + "9 conversations came in while you were away.")
        XCTAssertEqual(AwaySyncWords.line(MachineAwaySync(state: "reading"), locale: en), "Syncing…",
                       "before any reader has started")
        let done = MachineAwaySync(state: "done", readers: [
            .init(channel: "imessage", label: "Messages", state: "done")], arrived: 1, newCount: 1)
        XCTAssertEqual(AwaySyncWords.line(done, locale: en),
                       "Synced Messages — 1 new conversation. 1 conversation came in while you were away.")
        XCTAssertEqual(AwaySyncWords.line(MachineAwaySync(state: "done", readers: done.readers), locale: en),
                       "Synced Messages — nothing new.")
        XCTAssertEqual(AwaySyncWords.line(MachineAwaySync(state: "done", arrived: 0), locale: en), "Synced.")
        XCTAssertEqual(AwaySyncWords.line(reading, machine: "studio-example", locale: en).prefix(36),
                       "studio-example is syncing Messages a")
        XCTAssertEqual(AwaySyncWords.line(done, machine: "studio-example", locale: en).prefix(30),
                       "studio-example synced Messages")
    }

    func testAListOfManyNamesTwoAndACount() {
        XCTAssertEqual(AwaySyncWords.list(["A", "B", "C"], en), "A, B and C")
        XCTAssertEqual(AwaySyncWords.list(["A", "B", "C", "D", "E"], en), "A, B and 3 more")
    }

    func testAFailureLeadsWithItsClauseThenTheReadersOwnFix() {
        let sync = MachineAwaySync(state: "done", readers: [
            .init(channel: "calendar-local", label: "Calendar", state: "failed", fix: Copy.calendarDenied)])
        XCTAssertEqual(AwaySyncWords.failures(sync),
                       [.init(channel: "calendar-local", lead: "Calendar couldn't be read.", fix: Copy.calendarDenied)])
        XCTAssertTrue(Copy.calendarDenied.contains("System Settings"), "the exact fix, in the reader's own words")
    }

    // MARK: The wire and the strip

    func testAMachineRowCarriesItsSyncAndTheSleepPageListsThisMachineFirst() throws {
        let wire = """
        {"devices": [
          {"id": null, "name": "studio-example", "current": true, "connected": true, "how": "local", "queue": 16,
           "catchUp": {"state": "reading", "openedAt": "2026-11-03T12:00:00Z", "awaySince": "2026-11-03T07:00:00Z",
                       "doneAt": null, "readers": [{"channel": "imessage", "label": "Messages", "state": "reading",
                       "fix": null}], "arrived": 9, "new": 2}},
          {"id": "dev_a", "name": "laptop-example", "current": false, "connected": true, "queue": 0,
           "catchUp": {"state": "done", "readers": [], "arrived": null, "new": 0}},
          {"id": "dev_b", "name": "phone-example", "connected": false, "queue": 0}]}
        """
        let rows = try JSONDecoder().decode(MachineStatusList.self, from: Data(wire.utf8)).devices
        XCTAssertEqual(rows[0].catchUp?.newCount, 2)
        XCTAssertEqual(rows[0].catchUp?.arrived, 9)
        XCTAssertNil(rows[2].catchUp)
        let entries = AwaySyncWords.machines(own: nil, rows: rows)
        XCTAssertEqual(entries.map(\.name), [nil, "laptop-example"], "this machine unnamed, another by its name")
        let fresher = MachineAwaySync(state: "done", newCount: 5)
        XCTAssertEqual(AwaySyncWords.machines(own: fresher, rows: rows).first?.catchUp, fresher,
                       "this machine's own report answers before the strip's poll does")
    }

    func testTheReportCarriesTheWholeWord() {
        let report = AwaySyncReport(session: "s1", openedAt: t0, awaySince: nil, readers: [
            .init(channel: "notes", label: "Notes", state: "failed", fix: "why")], done: false)
        let body = report.body
        XCTAssertEqual(body["session"] as? String, "s1")
        XCTAssertNil(body["awaySince"], "a first launch has no away time")
        XCTAssertEqual((body["readers"] as? [[String: Any]])?.first?["fix"] as? String, "why")
    }
}
