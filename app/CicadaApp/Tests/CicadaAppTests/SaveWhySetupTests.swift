import XCTest
@testable import CicadaApp

/// G191 v2 — one switch that works: turning "Ask why" on turns on the bookmark watch of every browser here, a refused
/// read names its permission, and the row says the next bookmark is the first one asked. Real temp folders stand in
/// for the browsers' files; a folder with no permissions stands in for Safari's protected one.
@MainActor
final class SaveWhySetupTests: XCTestCase {
    private var dir: URL!
    private var suite: String!
    private var defaults: UserDefaults!

    private let both = BrowserInventory.detect { ["com.google.Chrome", "com.apple.Safari"].contains($0) }

    override func setUp() async throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("SaveWhySetup-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir.appendingPathComponent("Chrome"),
                                                withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: dir.appendingPathComponent("Safari"),
                                                withIntermediateDirectories: true)
        try "{}".write(to: dir.appendingPathComponent("Chrome/Bookmarks"), atomically: true, encoding: .utf8)
        try "<plist/>".write(to: dir.appendingPathComponent("Safari/Bookmarks.plist"), atomically: true,
                             encoding: .utf8)
        suite = "SaveWhySetupTests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
    }

    override func tearDown() async throws {
        try? FileManager.default.setAttributes([.posixPermissions: 0o755],
                                               ofItemAtPath: dir.appendingPathComponent("Safari").path)
        try? FileManager.default.removeItem(at: dir)
        defaults.removePersistentDomain(forName: suite)
    }

    /// Safari's folder refuses every open, the way macOS refuses one without Full Disk Access.
    private func protectSafari() throws {
        try FileManager.default.setAttributes([.posixPermissions: 0o000],
                                              ofItemAtPath: dir.appendingPathComponent("Safari").path)
    }

    private func makeWatcher() -> BrowserWatcher {
        BrowserWatcher(
            defaults: defaults,
            channels: [("chrome-bookmarks", .chromeBookmarks), ("safari-bookmarks", .safariBookmarks)],
            paths: { [dir] file in
                file == .chromeBookmarks ? [dir!.appendingPathComponent("Chrome/Bookmarks")]
                                         : [dir!.appendingPathComponent("Safari/Bookmarks.plist")]
            },
            debounce: .milliseconds(60), minimumInterval: .milliseconds(1),
            performSync: { _, _ in "ok" })
    }

    private func status(_ watcher: BrowserWatcher) -> SaveWhySetup.Status {
        SaveWhySetup.status(inventory: both, state: watcher.state(for:), isEnabled: watcher.isEnabled)
    }

    func testTurningItOnWatchesEveryInstalledBrowserEvenOnesTurnedOff() {
        // The measured case: both watches explicitly off, the switch never set.
        defaults.set(false, forKey: BrowserWatchPolicy.enabledKey("chrome-bookmarks"))
        defaults.set(false, forKey: BrowserWatchPolicy.enabledKey("safari-bookmarks"))
        let prefs = SaveWhyPrefs(defaults: defaults)
        let watcher = makeWatcher()
        XCTAssertEqual(SaveWhySetup.status(inventory: both, state: watcher.state(for:), isEnabled: watcher.isEnabled).off,
                       ["Chrome", "Safari"])

        let turned = SaveWhySetup.turnOn(prefs: prefs, inventory: both, watcher: watcher)
        XCTAssertTrue(prefs.enabled)
        XCTAssertEqual(turned, ["chrome-bookmarks", "safari-bookmarks"])
        XCTAssertTrue(watcher.isEnabled("chrome-bookmarks"))
        XCTAssertTrue(watcher.isEnabled("safari-bookmarks"))
        XCTAssertEqual(status(watcher), .init(watching: ["Chrome", "Safari"]))
        let lines = SaveWhySetup.lines(enabled: true, status: status(watcher))
        XCTAssertEqual(lines, [Copy.SaveWhy.watching(["Chrome", "Safari"])])
        XCTAssertTrue(lines[0].contains("next bookmark"), "the seed, said: the bookmarks already there never ask")
        watcher.stop()
    }

    func testAMissingPermissionIsNamedWithItsBrowser() throws {
        try protectSafari()
        let watcher = makeWatcher()
        SaveWhySetup.turnOn(prefs: SaveWhyPrefs(defaults: defaults), inventory: both, watcher: watcher)
        XCTAssertEqual(watcher.state(for: "safari-bookmarks"), .blocked)
        XCTAssertEqual(status(watcher), .init(watching: ["Chrome"], needsFullDiskAccess: ["Safari"]))
        let lines = SaveWhySetup.lines(enabled: true, status: status(watcher))
        XCTAssertEqual(lines.first, Copy.SaveWhy.needsFullDiskAccess("Safari"), "the one thing to do comes first")
        XCTAssertTrue(lines.first!.contains("Full Disk Access"))
        XCTAssertEqual(lines.last, Copy.SaveWhy.watching(["Chrome"]))
        watcher.stop()
    }

    func testOnlyInstalledBrowsersCicadaCanSyncAreTurnedOn() {
        let chromeAndArc = BrowserInventory.detect { ["com.google.Chrome", "company.thebrowser.Browser"].contains($0) }
        XCTAssertEqual(SaveWhySetup.channels(inventory: chromeAndArc), ["chrome-bookmarks"],
                       "an unsupported browser is never turned on; an absent one is not on this Mac")
        let watcher = makeWatcher()
        XCTAssertEqual(SaveWhySetup.turnOn(prefs: SaveWhyPrefs(defaults: defaults), inventory: chromeAndArc,
                                           watcher: watcher), ["chrome-bookmarks"])
        XCTAssertNil(defaults.object(forKey: BrowserWatchPolicy.enabledKey("safari-bookmarks")))
        watcher.stop()
    }

    func testTurningItOffLeavesTheWatchesAlone() {
        let prefs = SaveWhyPrefs(defaults: defaults)
        let watcher = makeWatcher()
        SaveWhySetup.turnOn(prefs: prefs, inventory: both, watcher: watcher)
        prefs.enabled = false
        XCTAssertTrue(watcher.isEnabled("chrome-bookmarks"), "the bookmarks are still captured as they always were")
        XCTAssertEqual(SaveWhySetup.lines(enabled: false, status: status(watcher)), [])
        watcher.stop()
    }

    func testTheRowSaysWhenNothingCanAsk() {
        XCTAssertEqual(SaveWhySetup.lines(enabled: true, status: .init()), [Copy.SaveWhy.nothingWatched])
        XCTAssertEqual(SaveWhySetup.lines(enabled: true, status: .init(watching: ["Chrome"], off: ["Safari"])),
                       [Copy.SaveWhy.watching(["Chrome"]), Copy.SaveWhy.leftOff(["Safari"])])
        XCTAssertEqual(Copy.SaveWhy.willWatch(["Chrome", "Safari"]),
                       "Turning this on also watches your bookmarks in Chrome and Safari.")
    }
}

/// 2026-10-14 — the menu-bar badge: 133 waiting read as "99", and as a consolidation count.
final class BookwormBadgeTests: XCTestCase {
    func testTheBadgeSaysNinetyNinePlusPastNinetyNine() {
        XCTAssertEqual(BookwormOverlays.badgeText(98), "98")
        XCTAssertEqual(BookwormOverlays.badgeText(99), "99")
        XCTAssertEqual(BookwormOverlays.badgeText(100), "99+")
        XCTAssertEqual(BookwormOverlays.badgeText(133), "99+")
        XCTAssertEqual(BookwormState.curious(count: 133).badgeCount, BookwormState.curious(count: 140).badgeCount,
                       "every count over 99 draws the same frames")
        XCTAssertNotEqual(BookwormState.curious(count: 99).spriteKey, BookwormState.curious(count: 100).spriteKey)
    }

    func testTheNinetyNinePlusPillFitsTheFrame() {
        let grid = BookwormOverlays.badgeOverlay(133)
        XCTAssertEqual(grid.count, BookwormOverlays.size)
        XCTAssertTrue(grid.allSatisfy { $0.count == BookwormOverlays.size })
        // The pill row (row 11) is 13 pixels wide — three glyphs — and ends at the frame's right edge.
        let pill = Array(grid[11])
        XCTAssertEqual(pill.filter { $0 == "q" }.count, 13)
        XCTAssertEqual(pill.last, "q")
        // The plus: its crossbar row has three ink pixels in the third glyph's cell.
        let crossbar = Array(grid[14])
        XCTAssertEqual(String(crossbar[14...16]), "ooo")
        XCTAssertNotEqual(BookwormOverlays.badgeOverlay(99), grid)
    }

    func testTheNumberIsSaidInWords() {
        XCTAssertEqual(BookwormState.curious(count: 133).detail, "133 questions waiting")
        XCTAssertEqual(BookwormState.curious(count: 1).detail, "1 question waiting")
        XCTAssertEqual(MenuBarManager.toolTip(for: .curious(count: 133)), "Cicada — 133 questions waiting in the inbox")
        XCTAssertEqual(Copy.menuBarInboxLine(133), "Inbox: 133 questions waiting")
        XCTAssertEqual(Copy.menuBarInboxLine(0), "Inbox: no questions waiting")
    }
}
