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

    private func watcher(_ folder: URL) -> ExportArrivalWatcher {
        ExportArrivalWatcher(folder: folder, sleep: { _ in try await Task.sleep(for: .seconds(3600)) })
    }

    func testOnlyTheAwaitedVendorsExportIsDeliveredOnceAndOnlyWhileAWaitIsOpen() async {
        let downloads = tempDir()
        _ = zip(["conversations.json", "users.json"], named: "data-older.zip", in: downloads)
        let w = watcher(downloads)
        var delivered: [(String, ChatVendor)] = []
        w.waitedVendors = { [.claude] }
        w.deliver = { url, vendor in delivered.append((url.lastPathComponent, vendor)); return true }
        await w.lookOnce()
        XCTAssertFalse(w.isWatching, "no wait, no watch")
        w.sync(anyWait: true)
        XCTAssertTrue(w.isWatching)
        _ = zip(["conversations.json", "users.json"], named: "data-new.zip", in: downloads)
        _ = zip(["conversations.json", "user.json", "chat.html"], named: "gpt.zip", in: downloads)
        _ = zip(["photo.jpg"], named: "photos.zip", in: downloads)
        await w.lookOnce()
        await w.lookOnce()
        await w.lookOnce()
        XCTAssertEqual(delivered.map(\.0), ["data-new.zip"], "the older export and the others are never handed on")
        XCTAssertEqual(delivered.map(\.1), [.claude])
        w.sync(anyWait: false)
        XCTAssertFalse(w.isWatching)
    }

    func testABusyIntakeIsTriedAgainAtTheNextLook() async {
        let downloads = tempDir()
        let w = watcher(downloads)
        var tries = 0
        w.waitedVendors = { [.chatgpt] }
        w.deliver = { _, _ in tries += 1; return tries > 1 }
        w.sync(anyWait: true)
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

    /// End to end through the real FSEvents watch and settle loop: an export copied in lands in the intake by itself.
    func testTheWatchItselfFindsAnExportCopiedIn() async {
        let downloads = tempDir()
        let w = ExportArrivalWatcher(folder: downloads, sleep: { _ in try await Task.sleep(for: .milliseconds(300)) })
        let arrived = expectation(description: "delivered")
        w.waitedVendors = { [.claude] }
        w.deliver = { url, vendor in
            XCTAssertEqual(vendor, .claude)
            XCTAssertEqual(url.lastPathComponent, "export.zip")
            arrived.fulfill()
            return true
        }
        w.sync(anyWait: true)
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

    func testADeniedPermissionStillRecordsTheHabit() async {
        let fake = FakeReminders(grant: false)
        let store = ExportWaitStore(defaults: suite(), scheduler: fake, now: { self.now })
        let ok = await store.startWeekly(vendor: "chatgpt", bank: "default")
        XCTAssertFalse(ok)
        XCTAssertTrue(store.weekly(vendor: "chatgpt", bank: "default"))
        XCTAssertTrue(fake.weekly.isEmpty)
    }

    func testTappingTheNudgeOpensAWaitAndTheWatchFollowsTheWaits() async {
        let fake = FakeReminders(grant: true)
        let store = ExportWaitStore(defaults: suite(), scheduler: fake, now: { self.now })
        var seen: [Bool] = []
        store.onChange = { [store] in seen.append(store.anyWait) }
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
