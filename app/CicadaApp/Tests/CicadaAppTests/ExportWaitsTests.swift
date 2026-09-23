import XCTest
@testable import CicadaApp

final class FakeReminders: ReminderScheduling {
    let grant: Bool
    var permissionAsks = 0
    var scheduled: [String] = []
    var cancelled: [String] = []
    init(grant: Bool) { self.grant = grant }
    func requestPermission() async -> Bool { permissionAsks += 1; return grant }
    func schedule(_ wait: ExportWait) async { scheduled.append(wait.id) }
    func cancel(_ wait: ExportWait) { cancelled.append(wait.id) }
}

/// Track I part b (design §5.5, R-IB22) — a reminder is a per-viewer
/// convenience whose text twins work with notifications off.
@MainActor
final class ExportWaitsTests: XCTestCase {
    private let now = ISO8601DateFormatter().date(from: "2026-09-23T10:00:00Z")!
    private let en = Locale(identifier: "en_US")

    private func wait(_ vendor: String = "chatgpt", bank: String = "default", hoursAgo: Double = 2,
                      remindIn: Double = 21) -> ExportWait {
        ExportWait(vendor: vendor, bank: bank, requestedAt: now.addingTimeInterval(-hoursAgo * 3600),
                   remindAt: now.addingTimeInterval(remindIn * 3600))
    }

    private func suite() -> UserDefaults { UserDefaults(suiteName: "waits-\(UUID().uuidString)")! }

    func testOneWaitPerVendorPerBank() {
        let waits = ExportWaits.adding(wait(hoursAgo: 1), to: [wait(hoursAgo: 5), wait("claude")])
        XCTAssertEqual(waits.filter { $0.vendor == "chatgpt" }.count, 1)
        XCTAssertEqual(waits.count, 2)
    }

    func testAWaitExpiresAfterFourteenDaysAndBelongsToItsBank() {
        let old = wait(hoursAgo: 14 * 24 + 1), fresh = wait("claude", hoursAgo: 13 * 24)
        XCTAssertEqual(ExportWaits.pruned([old, fresh], now: now), [fresh])
        XCTAssertTrue(ExportWaits.active([wait(bank: "default")], bank: "beta-bank", now: now).isEmpty)
    }

    func testTheTwinsSayWhoAndWhen() {
        let w = wait()
        XCTAssertEqual(ExportWaits.stripLine(w, now: now, locale: en), "Waiting for your ChatGPT export · requested 2 hours ago")
        XCTAssertEqual(ExportWaits.menuLine(w, now: now, locale: en), "Waiting for ChatGPT export, requested 2 hours ago")
        XCTAssertEqual(ExportWaits.rowLine(w, now: now, locale: en), "Requested 2 hours ago · reminder in 21 hours")
    }

    func testTheDelaysAreWhatTheyMenuSays() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        let morning = ReminderDelay.tomorrowMorning.remindAt(from: now, calendar: cal)
        XCTAssertEqual(cal.component(.hour, from: morning), 9)
        XCTAssertEqual(cal.component(.day, from: morning), 24)
        XCTAssertEqual(ReminderDelay.threeHours.remindAt(from: now, calendar: cal), now.addingTimeInterval(3 * 3600))
        XCTAssertEqual(ReminderDelay.twoDays.remindAt(from: now, calendar: cal), now.addingTimeInterval(2 * 86_400))
    }

    func testPermissionIsAskedOnlyAtRemindAndADenialStillRecordsTheWait() async {
        let fake = FakeReminders(grant: false)
        let store = ExportWaitStore(defaults: suite(), scheduler: fake, now: { self.now })
        XCTAssertEqual(fake.permissionAsks, 0, "never asked before the person chose Remind me")
        let granted = await store.remind(vendor: "chatgpt", bank: "default", delay: .threeHours)
        XCTAssertFalse(granted)
        XCTAssertEqual(store.waits.map(\.vendor), ["chatgpt"], "the twins carry it")
        XCTAssertEqual(fake.permissionAsks, 1)
        XCTAssertTrue(fake.scheduled.isEmpty)
    }

    func testClearingAWaitCancelsItsNotificationAndItSurvivesARelaunch() async {
        let defaults = suite()
        let fake = FakeReminders(grant: true)
        let first = ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
        _ = await first.remind(vendor: "claude", bank: "default", delay: .twoDays)
        XCTAssertEqual(fake.scheduled, ["default|claude"])
        let relaunched = ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
        XCTAssertEqual(relaunched.waits.map(\.vendor), ["claude"])
        relaunched.clear(vendor: "claude", bank: "default")
        XCTAssertTrue(relaunched.waits.isEmpty)
        XCTAssertEqual(fake.cancelled, ["default|claude"])
    }

    func testTheNotificationCenterIsOnlyTouchedInsideARealAppBundle() {
        XCTAssertFalse(ReminderAvailability.isAvailable(bundleIdentifier: nil, bundlePath: "/x/CicadaApp"))
        XCTAssertFalse(ReminderAvailability.isAvailable(bundleIdentifier: "com.apple.dt.xctest.tool", bundlePath: "/x/xctest"))
        XCTAssertTrue(ReminderAvailability.isAvailable(bundleIdentifier: "com.example.cicada", bundlePath: "/Applications/Cicada.app"))
    }
}
