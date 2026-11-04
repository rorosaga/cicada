import XCTest
@testable import CicadaApp

/// G197 layer c (2026-11-04) — an awaited export is picked up from Downloads by its member names alone, offered
/// once, and only while someone is waiting for it; a weekly nudge keeps the export coming.
@MainActor
final class ExportArrivalsTests: XCTestCase {
    private var dirs: [URL] = []

    override func tearDown() {
        for d in dirs { try? FileManager.default.removeItem(at: d) }
        dirs = []
        super.tearDown()
    }

    private func tempDir() -> URL {
        let d = FileManager.default.temporaryDirectory.appendingPathComponent("arrivals-\(UUID().uuidString)")
        try! FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        dirs.append(d)
        return d
    }

    /// A real zip, by the system's own `zip`, of empty-ish members at the given paths.
    private func zip(_ members: [String], named name: String, in folder: URL) -> URL {
        let src = tempDir()
        for m in members {
            let url = src.appendingPathComponent(m)
            try! FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try! Data("{}".utf8).write(to: url)
        }
        let out = folder.appendingPathComponent(name)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/zip")
        p.currentDirectoryURL = src
        p.arguments = ["-q", "-r", out.path] + members
        try! p.run()
        p.waitUntilExit()
        XCTAssertEqual(p.terminationStatus, 0)
        return out
    }

    // MARK: Whose export

    func testTheVendorIsReadFromTheFilesEachExportCarries() {
        XCTAssertEqual(ExportArrivals.vendor(members: ["conversations.json", "users.json", "projects.json"]), .claude)
        XCTAssertEqual(ExportArrivals.vendor(members: ["data-x/conversations.json", "data-x/users.json"]), .claude,
                       "nested in a folder")
        XCTAssertEqual(ExportArrivals.vendor(members: ["conversations.json", "user.json", "chat.html"]), .chatgpt)
        XCTAssertEqual(ExportArrivals.vendor(members: ["Takeout/My Activity/Gemini Apps/MyActivity.json"]), .gemini)
        XCTAssertNil(ExportArrivals.vendor(members: ["conversations.json"]), "no account file: nobody's")
        XCTAssertNil(ExportArrivals.vendor(members: ["conversations.json", "users.json", "user.json"]), "both: ambiguous")
        XCTAssertNil(ExportArrivals.vendor(members: ["photos/a.jpg", "users.json"]))
    }

    // MARK: Central directory

    func testMemberNamesComeFromTheCentralDirectory() {
        let z = zip(["conversations.json", "users.json", "sub/memories.json"], named: "a.zip", in: tempDir())
        XCTAssertEqual(Set(ZipMembers.names(of: z) ?? []), ["conversations.json", "users.json", "sub/memories.json"])
    }

    func testAZip64EndRecordIsFollowed() throws {
        let z = zip(["conversations.json", "users.json"], named: "b.zip", in: tempDir())
        var bytes = try Data(contentsOf: z)
        // Rewrite the classic end record as zip64's: record + locator, then a classic record of all-ones.
        let eocd = bytes.count - 22
        func le(_ v: UInt64, _ n: Int) -> Data { Data((0..<n).map { UInt8((v >> (8 * UInt64($0))) & 0xFF) }) }
        func read(_ at: Int, _ n: Int) -> UInt64 { (0..<n).reduce(0) { $0 | UInt64(bytes[at + $1]) << (8 * UInt64($1)) } }
        XCTAssertEqual(read(eocd, 4), 0x0605_4b50)
        let entries = read(eocd + 10, 2), dirSize = read(eocd + 12, 4), dirOffset = read(eocd + 16, 4)
        var tail = Data()
        tail += le(0x0606_4b50, 4) + le(44, 8) + le(45, 2) + le(45, 2) + le(0, 4) + le(0, 4)
        tail += le(entries, 8) + le(entries, 8) + le(dirSize, 8) + le(dirOffset, 8)
        tail += le(0x0706_4b50, 4) + le(0, 4) + le(UInt64(eocd), 8) + le(1, 4)
        tail += le(0x0605_4b50, 4) + le(0, 2) + le(0, 2) + le(0xFFFF, 2) + le(0xFFFF, 2)
        tail += le(0xFFFF_FFFF, 4) + le(0xFFFF_FFFF, 4) + le(0, 2)
        bytes = bytes.prefix(eocd) + tail
        try bytes.write(to: z)
        XCTAssertEqual(Set(ZipMembers.names(of: z) ?? []), ["conversations.json", "users.json"])
    }

    /// Review of #592, blocker 1: a crafted zip64 directory offset near `UInt64.max` trapped on `offset + size`.
    func testACraftedZip64OffsetNearTheTopIsNobodysAndNeverTraps() throws {
        let cases: [(UInt64, UInt64)] = [(UInt64.max - 10, 100), (UInt64.max, UInt64.max), (10, UInt64.max)]
        for (offset, size) in cases {
            let z = zip(["conversations.json", "users.json"], named: "evil.zip", in: tempDir())
            var bytes = try Data(contentsOf: z)
            let eocd = bytes.count - 22
            func le(_ v: UInt64, _ n: Int) -> Data { Data((0..<n).map { UInt8((v >> (8 * UInt64($0))) & 0xFF) }) }
            var tail = Data()
            tail += le(0x0606_4b50, 4) + le(44, 8) + le(45, 2) + le(45, 2) + le(0, 4) + le(0, 4)
            tail += le(2, 8) + le(2, 8) + le(size, 8) + le(offset, 8)
            tail += le(0x0706_4b50, 4) + le(0, 4) + le(UInt64(eocd), 8) + le(1, 4)
            tail += le(0x0605_4b50, 4) + le(0, 2) + le(0, 2) + le(0xFFFF, 2) + le(0xFFFF, 2)
            tail += le(0xFFFF_FFFF, 4) + le(0xFFFF_FFFF, 4) + le(0, 2)
            bytes = bytes.prefix(eocd) + tail
            try bytes.write(to: z)
            XCTAssertNil(ZipMembers.names(of: z))
        }
        // A locator pointing past the end, or at a record that would run off it.
        for recordAt in [UInt64.max - 3, UInt64.max] {
            let z = zip(["conversations.json", "users.json"], named: "evil2.zip", in: tempDir())
            var bytes = try Data(contentsOf: z)
            let eocd = bytes.count - 22
            func le(_ v: UInt64, _ n: Int) -> Data { Data((0..<n).map { UInt8((v >> (8 * UInt64($0))) & 0xFF) }) }
            var tail = le(0x0706_4b50, 4) + le(0, 4) + le(recordAt, 8) + le(1, 4)
            tail += le(0x0605_4b50, 4) + le(0, 2) + le(0, 2) + le(0xFFFF, 2) + le(0xFFFF, 2)
            tail += le(0xFFFF_FFFF, 4) + le(0xFFFF_FFFF, 4) + le(0, 2)
            bytes = bytes.prefix(eocd) + tail
            try bytes.write(to: z)
            XCTAssertNil(ZipMembers.names(of: z))
        }
    }

    func testANonZipOrATruncatedZipIsNobodys() throws {
        let folder = tempDir()
        let text = folder.appendingPathComponent("notes.zip")
        try Data("not a zip at all, just words".utf8).write(to: text)
        XCTAssertNil(ZipMembers.names(of: text))
        let z = zip(["conversations.json", "users.json"], named: "c.zip", in: folder)
        let data = try Data(contentsOf: z)
        try data.prefix(data.count - 10).write(to: z)
        XCTAssertNil(ZipMembers.names(of: z))
    }

    // MARK: Settling

    private func entry(_ name: String, _ size: Int64, _ t: TimeInterval = 0) -> FolderEntry {
        FolderEntry(name: name, size: size, modified: Date(timeIntervalSince1970: t))
    }

    func testAnOldExportIsNeverOfferedAndANewOneOnlyOnceSettled() {
        var t = ArrivalTracker(baseline: [entry("old.zip", 10), entry("notes.txt", 5)])
        XCTAssertEqual(t.look([entry("old.zip", 10), entry("new.zip", 50)]), [], "first look: new.zip is pending")
        XCTAssertTrue(t.waitingOnGrowth)
        XCTAssertEqual(t.look([entry("old.zip", 10), entry("new.zip", 80)]), [], "still growing")
        let ready = t.look([entry("old.zip", 10), entry("new.zip", 80)])
        XCTAssertEqual(ready.map(\.name), ["new.zip"])
        t.done(ready[0])
        XCTAssertEqual(t.look([entry("old.zip", 10), entry("new.zip", 80)]), [], "offered once")
        XCTAssertFalse(t.waitingOnGrowth)
    }

    func testAFileReplacedUnderAnOldNameIsNewAndAVanishedOneIsForgotten() {
        var t = ArrivalTracker(baseline: [entry("data.zip", 10, 1)])
        _ = t.look([entry("data.zip", 99, 2)])
        XCTAssertEqual(t.look([entry("data.zip", 99, 2)]).map(\.name), ["data.zip"])
        _ = t.look([entry("gone.zip", 5)])
        _ = t.look([])
        XCTAssertFalse(t.waitingOnGrowth)
        XCTAssertEqual(t.look([entry("x.txt", 5)]), [], "only zips")
    }

    func testAFileThatNeverSettlesIsDroppedAfterItsLooks() {
        var t = ArrivalTracker(baseline: [])
        for i in 0..<ExportArrivals.maxLooks { _ = t.look([entry("slow.zip", Int64(i + 1))]) }
        XCTAssertTrue(t.waitingOnGrowth)
        _ = t.look([entry("slow.zip", 999)])
        XCTAssertFalse(t.waitingOnGrowth)
    }

    // MARK: The watch

    private let future = Date().addingTimeInterval(86_400)

    private func watcher(_ folder: URL, vendors: Set<ChatVendor> = [.claude]) -> ExportArrivalWatcher {
        let w = ExportArrivalWatcher(folder: folder, sleep: { _ in try await Task.sleep(for: .seconds(3600)) },
                                     expirySleep: { _ in try await Task.sleep(for: .seconds(3600)) })
        w.waitedVendors = { vendors }
        w.waitsUntil = { [future] in future }
        return w
    }

    func testOnlyTheAwaitedVendorsExportIsDeliveredOnceAndOnlyWhileAWaitIsOpen() async {
        let downloads = tempDir()
        _ = zip(["conversations.json", "users.json"], named: "data-older.zip", in: downloads)
        let w = watcher(downloads)
        var delivered: [(String, ChatVendor)] = []
        w.deliver = { url, vendor in delivered.append((url.lastPathComponent, vendor)); return true }
        await w.lookOnce()
        XCTAssertFalse(w.isWatching, "not synced, no watch")
        w.sync()
        XCTAssertTrue(w.isWatching)
        _ = zip(["conversations.json", "users.json"], named: "data-new.zip", in: downloads)
        _ = zip(["conversations.json", "user.json", "chat.html"], named: "gpt.zip", in: downloads)
        _ = zip(["photo.jpg"], named: "photos.zip", in: downloads)
        await w.lookOnce()
        await w.lookOnce()
        await w.lookOnce()
        XCTAssertEqual(delivered.map(\.0), ["data-new.zip"], "the older export and the others are never handed on")
        XCTAssertEqual(delivered.map(\.1), [.claude])
        w.waitsUntil = { nil }
        w.sync()
        XCTAssertFalse(w.isWatching)
    }

    /// Review of #592, blocker 2: a wait that expired (or was cleared) while the stream stayed open kept Downloads
    /// being listed and zips being read. Nothing awaited now closes the watch before anything is read.
    func testALookWithNothingAwaitedClosesTheWatchAndReadsNothing() async {
        let downloads = tempDir()
        let w = watcher(downloads)
        var vendors: Set<ChatVendor> = [.claude]
        w.waitedVendors = { vendors }
        var delivered = 0
        w.deliver = { _, _ in delivered += 1; return true }
        w.sync()
        _ = zip(["conversations.json", "users.json"], named: "data.zip", in: downloads)
        await w.lookOnce()
        vendors = []                       // the 14 days passed: `active` prunes it on read
        await w.lookOnce()
        XCTAssertFalse(w.isWatching, "closed at the look, not left open")
        XCTAssertEqual(delivered, 0)
    }

    func testAnExpiredWaitNeverOpensTheWatchAndTheWatchClosesAtExpiry() async throws {
        let downloads = tempDir()
        let w = watcher(downloads)
        w.waitsUntil = { Date().addingTimeInterval(-1) }
        w.sync()
        XCTAssertFalse(w.isWatching, "already expired")
        var until: Date? = Date().addingTimeInterval(60)
        let fired = AsyncStream<Void>.makeStream()
        let timed = ExportArrivalWatcher(folder: downloads, sleep: { _ in try await Task.sleep(for: .seconds(3600)) },
                                         expirySleep: { _ in fired.continuation.yield() })
        timed.waitedVendors = { [.claude] }
        timed.waitsUntil = { until }
        timed.sync()
        XCTAssertTrue(timed.isWatching)
        until = nil                        // what the store says once the moment has passed
        for await _ in fired.stream { break }
        let deadline = ContinuousClock.now + .seconds(3)
        while timed.isWatching, ContinuousClock.now < deadline { try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertFalse(timed.isWatching, "the expiry timer closed it with no folder event at all")
    }

    func testABusyIntakeIsTriedAgainAtTheNextLook() async {
        let downloads = tempDir()
        let w = watcher(downloads, vendors: [.chatgpt])
        var tries = 0
        w.deliver = { _, _ in tries += 1; return tries > 1 }
        w.sync()
        _ = zip(["conversations.json", "user.json"], named: "gpt.zip", in: downloads)
        await w.lookOnce()
        await w.lookOnce()
        XCTAssertEqual(tries, 1, "busy: not done")
        await w.lookOnce()
        XCTAssertEqual(tries, 2, "ready again at the very next look")
        await w.lookOnce()
        XCTAssertEqual(tries, 2, "delivered: never again")
        w.stop()
    }

    /// Review of #592: a look that awaited across a `stop()` wrote its tracker back, leaving a watch with no stream.
    func testAStopDuringALookIsKept() async {
        let downloads = tempDir()
        let w = watcher(downloads)
        w.deliver = { [w] _, _ in w.stop(); return true }
        w.sync()
        _ = zip(["conversations.json", "users.json"], named: "data.zip", in: downloads)
        await w.lookOnce()
        await w.lookOnce()
        XCTAssertFalse(w.isWatching)
    }

    func testARefusedDownloadsIsSaidAndOpensNothing() {
        let missing = tempDir().appendingPathComponent("no-such-folder")
        let w = watcher(missing)
        var said = 0
        w.onRefused = { said += 1 }
        w.sync()
        XCTAssertFalse(w.isWatching)
        XCTAssertEqual(said, 1)
    }

    /// End to end through the real FSEvents watch and settle loop: an export copied in lands in the intake by itself.
    func testTheWatchItselfFindsAnExportCopiedIn() async {
        let downloads = tempDir()
        let w = ExportArrivalWatcher(folder: downloads, sleep: { _ in try await Task.sleep(for: .milliseconds(300)) },
                                     expirySleep: { _ in try await Task.sleep(for: .seconds(3600)) })
        let arrived = expectation(description: "delivered")
        w.waitedVendors = { [.claude] }
        w.waitsUntil = { [future] in future }
        w.deliver = { url, vendor in
            XCTAssertEqual(vendor, .claude)
            XCTAssertEqual(url.lastPathComponent, "export.zip")
            arrived.fulfill()
            return true
        }
        w.sync()
        let staged = zip(["conversations.json", "users.json"], named: "export.zip", in: tempDir())
        try? FileManager.default.copyItem(at: staged, to: downloads.appendingPathComponent("export.zip"))
        await fulfillment(of: [arrived], timeout: 15)
        w.stop()
    }

    // MARK: Weekly

    private let now = ISO8601DateFormatter().date(from: "2026-11-04T10:00:00Z")!
    private func suite() -> UserDefaults { UserDefaults(suiteName: "habits-\(UUID().uuidString)")! }

    func testEveryWeekRepeatsOnTheDayItWasTurnedOnAndStopsWhereItStarted() async {
        let defaults = suite()
        let fake = FakeReminders(grant: true)
        let store = ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
        let ok = await store.startWeekly(vendor: "claude", bank: "default")
        XCTAssertTrue(ok)
        XCTAssertTrue(store.weekly(vendor: "claude", bank: "default"))
        XCTAssertFalse(store.weekly(vendor: "claude", bank: "beta-bank"))
        XCTAssertEqual(fake.weekly.count, 1)
        XCTAssertEqual(fake.weekly[0].hour, 9)
        XCTAssertEqual(fake.weekly[0].weekday, Calendar.autoupdatingCurrent.component(.weekday, from: now))
        XCTAssertTrue(store.waits.isEmpty, "a habit is not a wait: nothing is watched until the nudge is tapped")
        let relaunched = ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
        XCTAssertTrue(relaunched.weekly(vendor: "claude", bank: "default"))
        relaunched.stopWeekly(vendor: "claude", bank: "default")
        XCTAssertEqual(fake.weeklyCancelled, ["default|claude"])
        XCTAssertFalse(ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
                        .weekly(vendor: "claude", bank: "default"))
    }

    /// Review of #592, blocker 4: a refused permission saved a weekly reminder the menu called on but that never fired.
    func testADeniedPermissionSavesNoWeeklyReminder() async {
        let defaults = suite()
        let fake = FakeReminders(grant: false)
        let store = ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
        let ok = await store.startWeekly(vendor: "chatgpt", bank: "default")
        XCTAssertFalse(ok)
        XCTAssertFalse(store.weekly(vendor: "chatgpt", bank: "default"))
        XCTAssertFalse(ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
                        .weekly(vendor: "chatgpt", bank: "default"))
        XCTAssertTrue(fake.weekly.isEmpty)
    }

    func testSavedWeeklyRemindersAreScheduledAgainAtLaunchOrDroppedWithoutPermission() async {
        let defaults = suite()
        let first = FakeReminders(grant: true)
        _ = await ExportWaitStore(defaults: defaults, scheduler: first, now: { self.now })
            .startWeekly(vendor: "claude", bank: "default")
        let relaunch = FakeReminders(grant: true)
        let again = ExportWaitStore(defaults: defaults, scheduler: relaunch, now: { self.now })
        await again.refreshWeekly()
        XCTAssertEqual(relaunch.weekly.map(\.id), ["default|claude"], "scheduled again at launch")
        XCTAssertEqual(relaunch.permissionAsks, 0, "never asks at launch")
        let revoked = FakeReminders(grant: true)
        revoked.authorized = false
        let off = ExportWaitStore(defaults: defaults, scheduler: revoked, now: { self.now })
        await off.refreshWeekly()
        XCTAssertFalse(off.weekly(vendor: "claude", bank: "default"), "never said to be on when it cannot fire")
        XCTAssertEqual(revoked.permissionAsks, 0)
    }

    /// Review of #592: a wait left by an earlier launch must not list Downloads (and raise its prompt) at launch.
    func testOnlyAWaitOpenedInThisRunArmsThePickupInItsOwnMemory() async {
        let defaults = suite()
        let fake = FakeReminders(grant: true)
        let first = ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
        _ = await first.remind(vendor: "claude", bank: "default", delay: .threeHours)
        XCTAssertEqual(first.armedVendors(bank: "default"), [.claude])
        XCTAssertEqual(first.armedUntil(bank: "default"), now.addingTimeInterval(ExportWaits.maxAge))
        XCTAssertTrue(first.armedVendors(bank: "beta-bank").isEmpty)
        let relaunched = ExportWaitStore(defaults: defaults, scheduler: fake, now: { self.now })
        XCTAssertEqual(relaunched.waits.map(\.vendor), ["claude"], "the wait itself survives")
        XCTAssertTrue(relaunched.armedVendors(bank: "default").isEmpty)
        XCTAssertNil(relaunched.armedUntil(bank: "default"))
    }

    func testTheWeeklyNudgeCarriesItsMemory() {
        XCTAssertEqual(ReminderTap(vendor: .claude, kind: .weekly, bank: "beta-bank").bank(fallback: "default"), "beta-bank")
        XCTAssertEqual(ReminderTap(vendor: .claude, kind: .weekly).bank(fallback: "default"), "default")
        XCTAssertEqual(ReminderTap(vendor: .claude, kind: .weekly, bank: "").bank(fallback: "default"), "default")
    }

    func testTappingTheNudgeOpensAWaitAndTheWatchFollowsTheWaits() async {
        let fake = FakeReminders(grant: true)
        let store = ExportWaitStore(defaults: suite(), scheduler: fake, now: { self.now })
        var seen: [Bool] = []
        store.onChange = { [store] in seen.append(!store.armedVendors(bank: "default").isEmpty) }
        await store.weeklyTapped(vendor: "claude", bank: "default")
        XCTAssertEqual(store.waits.map(\.vendor), ["claude"])
        XCTAssertEqual(fake.scheduled, ["default|claude"], "the next morning's 'should be in your email'")
        store.clear(vendor: "claude", bank: "default")
        XCTAssertEqual(seen, [true, false])
    }

    func testATapIsHeldWithItsKindUntilTheRouterAttaches() {
        let q = ReminderTapQueue()
        q.receive(ReminderTap(vendor: .claude, kind: .weekly))
        q.receive(ReminderTap(vendor: .chatgpt, kind: .due))
        var got: [ReminderTap] = []
        q.attach { got.append($0) }
        q.receive(ReminderTap(vendor: .claude, kind: .arrived))
        XCTAssertEqual(got.map(\.kind), [.weekly, .due, .arrived])
    }
}
