import SwiftUI
import XCTest
@testable import CicadaApp

/// G191 v3 — bookmarks, round 3 (owner 2026-10-15): the question at once in Chrome (the bubble seen in the window
/// list, the app's own diff of the file), re-saves asking again, the bookmark history in the menu bar, and Remove.
/// Synthetic window lists, synthetic bookmark files and placeholder sites only — no real browser is read.
final class BookmarksV3Tests: XCTestCase {

    // MARK: - The bubble detector, on recorded synthetic window lists

    /// A 1512 × 945 Chrome window at the top of a laptop screen (window-list coordinates, y down).
    private let browser = ListedWindow(number: 10, pid: 501, layer: 0, bounds: CGRect(x: 0, y: 37, width: 1512, height: 945))
    private let other = ListedWindow(number: 11, pid: 501, layer: 0, bounds: CGRect(x: 40, y: 80, width: 900, height: 700))

    /// Chrome's "Bookmark added": 336 × 214, under the toolbar (≈ 88 pt below the window's top), its right edge at the
    /// star, left of the toolbar's buttons.
    private func bookmarkBubble(_ n: Int = 20) -> ListedWindow {
        ListedWindow(number: n, pid: 501, layer: 0, bounds: CGRect(x: 1048, y: 37 + 82, width: 336, height: 214))
    }

    func testTheBookmarkBubbleRightAfterTheShortcutIsSeen() {
        var d = BookmarkBubbleDetector()
        d.baseline([browser, other])
        XCTAssertEqual(d.observe([browser, other, bookmarkBubble()], inputAge: 0.08), bookmarkBubble())
        XCTAssertNil(d.observe([browser, other, bookmarkBubble()], inputAge: 0.2), "the same window is seen once")
    }

    func testAWindowAlreadyOnScreenWhenWatchingStartsIsNeverABubble() {
        var d = BookmarkBubbleDetector()
        d.baseline([browser, bookmarkBubble()])
        XCTAssertNil(d.observe([browser, bookmarkBubble()], inputAge: 0.05))
    }

    /// The false positives Chromium's view code puts in the same corner, each recorded as a window list.
    func testChromesOtherBubblesAreNotTheBookmarkBubble() {
        // The password-save bubble opens on its own after a page loads: no key or click of the person's just before.
        var auto = BookmarkBubbleDetector()
        auto.baseline([browser])
        let password = ListedWindow(number: 30, pid: 501, layer: 0,
                                    bounds: CGRect(x: 1010, y: 37 + 82, width: 360, height: 290))
        XCTAssertNil(auto.observe([browser, password], inputAge: 3.5), "no input of the person's: not a save")

        var d = BookmarkBubbleDetector()
        d.baseline([browser])
        // The address bar's suggestions: as wide as the bar, starting at its own top.
        let suggestions = ListedWindow(number: 31, pid: 501, layer: 0,
                                       bounds: CGRect(x: 150, y: 37 + 44, width: 1180, height: 320))
        XCTAssertNil(d.observe([browser, suggestions], inputAge: 0.05))
        // A permission prompt: anchored at the left of the address bar.
        let permission = ListedWindow(number: 32, pid: 501, layer: 0,
                                      bounds: CGRect(x: 150, y: 37 + 82, width: 320, height: 180))
        XCTAssertNil(d.observe([browser, permission], inputAge: 0.05))
        // A menu (the app menu is a native menu, far above layer 20) and a tooltip-sized sliver.
        let menu = ListedWindow(number: 33, pid: 501, layer: 101, bounds: CGRect(x: 1200, y: 37 + 82, width: 300, height: 400))
        let tooltip = ListedWindow(number: 34, pid: 501, layer: 0, bounds: CGRect(x: 1200, y: 37 + 82, width: 120, height: 24))
        XCTAssertNil(d.observe([browser, menu, tooltip], inputAge: 0.05))
        // A second browser window is not a bubble either.
        XCTAssertNil(d.observe([browser, menu, tooltip, ListedWindow(number: 35, pid: 501, layer: 0,
                                                                     bounds: CGRect(x: 300, y: 200, width: 800, height: 600))],
                               inputAge: 0.05))
        // Another app's window in the same place.
        var mixed = BookmarkBubbleDetector()
        mixed.baseline([browser])
        let elsewhere = ListedWindow(number: 36, pid: 777, layer: 0, bounds: bookmarkBubble().bounds)
        XCTAssertNil(mixed.observe([browser, elsewhere], inputAge: 0.05), "anchored only on its own app's window")
    }

    func testANarrowBrowserWindowIsNeverRead() {
        let narrow = ListedWindow(number: 10, pid: 501, layer: 0, bounds: CGRect(x: 0, y: 37, width: 640, height: 800))
        var d = BookmarkBubbleDetector()
        d.baseline([narrow])
        let bubble = ListedWindow(number: 20, pid: 501, layer: 0, bounds: CGRect(x: 260, y: 37 + 82, width: 336, height: 214))
        XCTAssertNil(d.observe([narrow, bubble], inputAge: 0.05))
    }

    /// The extensions or profile menu opened by a click looks like a bubble; once it has come with no bookmark
    /// `refuseAfter` times it is not shown again — and once a bookmark taught the bubble's size, only that size counts.
    func testTheDetectorLearnsTheBubblesSizeAndForgetsTheOthers() {
        let extensions = ListedWindow(number: 40, pid: 501, layer: 0,
                                      bounds: CGRect(x: 1110, y: 37 + 80, width: 320, height: 268))
        var d = BookmarkBubbleDetector()
        d.baseline([browser])
        var n = 40
        for miss in 1...BookmarkBubblePolicy.refuseAfter {
            n += 1
            let window = ListedWindow(number: n, pid: 501, layer: 0, bounds: extensions.bounds)
            XCTAssertEqual(d.observe([browser, window], inputAge: 0.1), window, "still shown after \(miss - 1) misses")
            d.missed(BubbleSize(extensions.bounds))
        }
        let again = ListedWindow(number: 60, pid: 501, layer: 0, bounds: extensions.bounds)
        XCTAssertNil(d.observe([browser, again], inputAge: 0.1), "refused after \(BookmarkBubblePolicy.refuseAfter) misses")
        XCTAssertEqual(d.observe([browser, bookmarkBubble(42)], inputAge: 0.1), bookmarkBubble(42))
        d.confirm(BubbleSize(bookmarkBubble().bounds))
        let profile = ListedWindow(number: 43, pid: 501, layer: 0, bounds: CGRect(x: 1150, y: 37 + 80, width: 320, height: 420))
        XCTAssertNil(d.observe([browser, profile], inputAge: 0.1), "once learned, only the bookmark bubble's size counts")
        XCTAssertEqual(d.observe([browser, bookmarkBubble(44)], inputAge: 0.1), bookmarkBubble(44))
        for _ in 0..<5 { d.missed(BubbleSize(bookmarkBubble().bounds)) }
        XCTAssertEqual(d.learned, [BubbleSize(width: 336, height: 214)], "a learned size is never refused")
        XCTAssertEqual(d.observe([browser, bookmarkBubble(45)], inputAge: 0.1), bookmarkBubble(45))
    }

    /// Review 2026-10-15: one missed bubble — Chrome's "Edit bookmark" bubble on a page already bookmarked, Remove
    /// pressed in the bubble — must not switch the instant panel off. Misses below `refuseAfter` keep the size, and a
    /// bookmark at that size clears them.
    func testAFewMissesNeverRefuseTheRealBubble() {
        var d = BookmarkBubbleDetector()
        d.baseline([browser])
        let size = BubbleSize(bookmarkBubble().bounds)
        for _ in 1..<BookmarkBubblePolicy.refuseAfter { d.missed(size) }
        XCTAssertTrue(d.refused.isEmpty)
        XCTAssertEqual(d.observe([browser, bookmarkBubble(70)], inputAge: 0.1), bookmarkBubble(70))
        d.confirm(size)
        XCTAssertTrue(d.misses.isEmpty, "a bookmark at that size clears its misses")
        for _ in 1...BookmarkBubblePolicy.refuseAfter { d.missed(size) }
        XCTAssertTrue(d.refused.isEmpty, "never refused once a bookmark was seen at that size")
    }

    @MainActor
    func testWhatTheDetectorLearnedIsKeptPerBrowserAsSizesOnly() {
        let defaults = UserDefaults(suiteName: "BookmarksV3Tests.\(UUID().uuidString)")!
        let watcher = BookmarkBubbleWatcherHarness.make(defaults: defaults)
        watcher.feedback(channel: "chrome-bookmarks", size: BubbleSize(width: 336, height: 214), bookmarked: true)
        for _ in 1...BookmarkBubblePolicy.refuseAfter {
            watcher.feedback(channel: "chrome-bookmarks", size: BubbleSize(width: 320, height: 268), bookmarked: false)
        }
        watcher.feedback(channel: "chrome-bookmarks", size: BubbleSize(width: 360, height: 300), bookmarked: false)
        let memory = BubbleMemory.load("com.google.Chrome", defaults: defaults)
        XCTAssertEqual(memory.learned, [BubbleSize(width: 336, height: 214)])
        XCTAssertEqual(memory.refused, [BubbleSize(width: 320, height: 268)])
        XCTAssertEqual(memory.misses, [BubbleMiss(size: BubbleSize(width: 360, height: 300), count: 1)])
    }

    // MARK: - The app's own diff: re-save versus move

    private static let webkitOffset: Double = 11_644_473_600
    private func micros(_ date: Date) -> String { String(Int64((date.timeIntervalSince1970 + Self.webkitOffset) * 1_000_000)) }

    private func chrome(_ leaves: [(id: String, url: String, at: Date)], folder: [(id: String, url: String, at: Date)] = [],
                        mobile: [(id: String, url: String, at: Date)] = []) -> Data {
        func leaf(_ l: (id: String, url: String, at: Date)) -> [String: Any] {
            ["type": "url", "id": l.id, "name": "Title \(l.id)", "url": l.url, "date_added": micros(l.at)]
        }
        let bar: [String: Any] = ["type": "folder", "id": "1", "name": "Bookmarks bar",
                                  "children": leaves.map(leaf) + (folder.isEmpty ? [] : [
                                      ["type": "folder", "id": "50", "name": "Reading", "children": folder.map(leaf)]
                                  ])]
        let roots: [String: Any] = ["bookmark_bar": bar,
                                    "other": ["type": "folder", "id": "2", "name": "Other bookmarks", "children": []],
                                    "synced": ["type": "folder", "id": "3", "name": "Mobile bookmarks",
                                               "children": mobile.map(leaf)]]
        return try! JSONSerialization.data(withJSONObject: ["version": 1, "roots": roots])
    }

    private let old = Date(timeIntervalSince1970: 1_790_000_000)
    private let now = Date(timeIntervalSince1970: 1_800_000_000)

    @MainActor
    func testTheDiffNamesOneNewBookmarkAndNeverAMoveOrARename() {
        let diff = BookmarkFileDiff()
        let a = (id: "11", url: "https://alpha.example/a", at: old)
        let b = (id: "12", url: "https://beta.example/b", at: old.addingTimeInterval(60))
        XCTAssertNil(diff.record(channel: "chrome-bookmarks", entries: BookmarkFileParse.chromium(chrome([a, b])), live: true),
                     "no baseline yet: the first read only records")
        // Moved into a folder: nothing new.
        XCTAssertNil(diff.record(channel: "chrome-bookmarks",
                                 entries: BookmarkFileParse.chromium(chrome([a], folder: [b])), live: true))
        // One new bookmark: named, with Chrome's own instant.
        let c = (id: "13", url: "https://gamma.example/c", at: now)
        let named = diff.record(channel: "chrome-bookmarks",
                                entries: BookmarkFileParse.chromium(chrome([a, c], folder: [b])), live: true)
        XCTAssertEqual(named?.url, c.url)
        XCTAssertEqual(named?.addedAt, ISO8601DateFormatter().string(from: now))
        XCTAssertEqual(named?.resave, false)
        XCTAssertEqual(named?.origin, "chrome-bookmark")
        // Two at once (an import): nothing named.
        let d = (id: "14", url: "https://delta.example/d", at: now.addingTimeInterval(1))
        let e = (id: "15", url: "https://epsilon.example/e", at: now.addingTimeInterval(2))
        XCTAssertNil(diff.record(channel: "chrome-bookmarks",
                                 entries: BookmarkFileParse.chromium(chrome([a, c, d, e], folder: [b])), live: true))
    }

    @MainActor
    func testRemovedThenSavedAgainIsNamedAsAResave() {
        let diff = BookmarkFileDiff()
        let a = (id: "11", url: "https://alpha.example/a", at: old)
        let b = (id: "12", url: "https://beta.example/b", at: old)
        _ = diff.record(channel: "chrome-bookmarks", entries: BookmarkFileParse.chromium(chrome([a, b])), live: false)
        // Removed and saved again between two reads (one Chrome write): a new node, a newer instant.
        let again = (id: "40", url: b.url, at: now)
        let named = diff.record(channel: "chrome-bookmarks", entries: BookmarkFileParse.chromium(chrome([a, again])),
                                live: true)
        XCTAssertEqual(named?.url, b.url)
        XCTAssertEqual(named?.resave, true)
        // Removed (one read), then saved again (the next).
        _ = diff.record(channel: "chrome-bookmarks", entries: BookmarkFileParse.chromium(chrome([a])), live: true)
        let third = (id: "41", url: b.url, at: now.addingTimeInterval(30))
        XCTAssertEqual(diff.record(channel: "chrome-bookmarks", entries: BookmarkFileParse.chromium(chrome([a, third])),
                                   live: true)?.url, b.url)
    }

    @MainActor
    func testSafarisPlistIsDiffedByLinkAlone() throws {
        func plist(_ urls: [String]) throws -> Data {
            let leaves = urls.map { ["WebBookmarkType": "WebBookmarkTypeLeaf", "URLString": $0,
                                     "URIDictionary": ["title": "T"]] as [String: Any] }
            let root: [String: Any] = ["WebBookmarkType": "WebBookmarkTypeList", "Children": [
                ["WebBookmarkType": "WebBookmarkTypeList", "Title": "BookmarksBar", "Children": leaves]]]
            return try PropertyListSerialization.data(fromPropertyList: root, format: .binary, options: 0)
        }
        let diff = BookmarkFileDiff()
        _ = diff.record(channel: "safari-bookmarks",
                        entries: BookmarkFileParse.safari(try plist(["https://alpha.example/a"])), live: false)
        let named = diff.record(channel: "safari-bookmarks", entries: BookmarkFileParse.safari(
            try plist(["https://alpha.example/a", "https://beta.example/b"])), live: true)
        XCTAssertEqual(named?.url, "https://beta.example/b")
        XCTAssertNil(named?.addedAt, "Safari keeps no instant for a bookmark")
        XCTAssertEqual(named?.channel, "safari-bookmarks")
    }

    /// The measured stages after Chrome writes, on a synthetic 20,000-bookmark file: the app's read and its own parse
    /// and diff, against the base64 body the early look posts (the backend half is timed in pytest).
    @MainActor
    func testStageTimingsOnATwentyThousandBookmarkFile() throws {
        let leaves = (0..<20_000).map { (id: "\($0 + 100)", url: "https://site\($0 % 997).example/p/\($0)",
                                         at: old.addingTimeInterval(Double($0))) }
        let data = chrome(leaves)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("Bookmarks-\(UUID().uuidString)")
        try data.write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        let clock = ContinuousClock()
        var read = Data()
        let readTime = clock.measure { read = try! Data(contentsOf: url) }
        var entries: [BookmarkEntry] = []
        let parseTime = clock.measure { entries = BookmarkFileParse.chromium(read) }
        let diff = BookmarkFileDiff()
        _ = diff.record(channel: "chrome-bookmarks", entries: entries, live: false)
        let added = leaves + [(id: "99999", url: "https://new.example/x", at: now)]
        let next = BookmarkFileParse.chromium(chrome(added))
        var named: FreshBookmark?
        let diffTime = clock.measure { named = diff.record(channel: "chrome-bookmarks", entries: next, live: true) }
        var body = ""
        let encodeTime = clock.measure { body = read.base64EncodedString() }
        print("G191 v3 stages (20k bookmarks, \(data.count / 1024) KB): read \(readTime), parse \(parseTime), " +
              "diff \(diffTime), base64 for the look \(encodeTime) (\(body.count / 1024) KB)")
        XCTAssertEqual(entries.count, 20_000)
        XCTAssertEqual(named?.url, "https://new.example/x")
        XCTAssertLessThan(parseTime + diffTime, .seconds(2), "the app's own diff is well inside the budget")
    }

    /// Safari: the same stages on a synthetic 20,000-leaf binary plist (Safari's own write delay is not something a
    /// synthetic file can show; this is Cicada's part after the write).
    @MainActor
    func testSafariStageTimingsOnATwentyThousandBookmarkPlist() throws {
        func plist(_ n: Int) throws -> Data {
            let leaves = (0..<n).map { ["WebBookmarkType": "WebBookmarkTypeLeaf",
                                        "URLString": "https://site\($0 % 997).example/p/\($0)",
                                        "URIDictionary": ["title": "Site \($0)"]] as [String: Any] }
            let root: [String: Any] = ["WebBookmarkType": "WebBookmarkTypeList", "Children": [
                ["WebBookmarkType": "WebBookmarkTypeList", "Title": "BookmarksMenu", "Children": leaves]]]
            return try PropertyListSerialization.data(fromPropertyList: root, format: .binary, options: 0)
        }
        let before = try plist(20_000)
        let after = try plist(20_001)
        let clock = ContinuousClock()
        let diff = BookmarkFileDiff()
        var entries: [BookmarkEntry] = []
        let parse = clock.measure { entries = BookmarkFileParse.safari(before) }
        _ = diff.record(channel: "safari-bookmarks", entries: entries, live: false)
        var named: FreshBookmark?
        let next = BookmarkFileParse.safari(after)
        let diffTime = clock.measure { named = diff.record(channel: "safari-bookmarks", entries: next, live: true) }
        print("G191 v3 Safari stages (20k bookmarks, \(before.count / 1024) KB plist): parse \(parse), diff \(diffTime)")
        XCTAssertEqual(named?.url, "https://site\(20_000 % 997).example/p/20000")
    }

    // MARK: - Removing from Chrome

    func testTheChromeScriptChecksEachNodesURLAndCountsOnlyRealDeletes() throws {
        let a = (id: "11", url: "https://alpha.example/a", at: old)
        let inFolder = (id: "61", url: "https://alpha.example/a", at: old)
        let onPhone = (id: "71", url: "https://alpha.example/a", at: old)
        let entries = BookmarkFileParse.chromium(chrome([a], folder: [inFolder], mobile: [onPhone]))
        let nodes = ChromeBookmarkScript.nodes(for: a.url, in: entries)
        XCTAssertEqual(nodes.map(\.nodeId), ["11", "61"])
        XCTAssertEqual(ChromeBookmarkScript.unreachable(for: a.url, in: entries), 1, "Mobile bookmarks are not scriptable")
        let script = try XCTUnwrap(ChromeBookmarkScript.delete(nodes))
        XCTAssertTrue(script.hasPrefix("on run argv\n    set targetURL to item 1 of argv"))
        XCTAssertTrue(script.contains("set b to bookmark item id 11 of bookmarks bar"))
        XCTAssertTrue(script.contains("set b to bookmark item id 61 of bookmark folder id 50 of bookmarks bar"))
        XCTAssertEqual(script.components(separatedBy: "if (URL of b) is targetURL then").count - 1, 2,
                       "each delete only after its URL is checked — ids are per Chrome profile")
        XCTAssertFalse(script.contains("alpha.example"), "the URL is an argument, never part of the source")
        XCTAssertTrue(script.contains("return removed"))
        XCTAssertTrue(script.contains("if code is -1743 or code is -1744 then error message number code"),
                      "a refused Automation is not swallowed")
        // Nothing from the file reaches the script as code: an id that is not digits is dropped.
        let hostile = BookmarkEntry(url: a.url, title: "x", nodeId: "1 \" & do shell script \"x", root: "bookmark_bar")
        XCTAssertNil(ChromeBookmarkScript.delete([hostile]))
        XCTAssertNil(ChromeBookmarkScript.delete([BookmarkEntry(url: a.url, title: "", nodeId: "5", root: "synced")]))
    }

    /// Only this save's copy is targeted: the node whose `date_added` is the record's `lastSavedAt`; with several
    /// copies the confirmation says so and asks.
    func testRemoveTargetsTheCopyThisSaveMadeAndAsksAboutTheOthers() {
        let url = "https://alpha.example/a"
        let first = (id: "11", url: url, at: old)
        let second = (id: "61", url: url, at: now)
        let other = (id: "12", url: "https://beta.example/b", at: old)
        let entries = BookmarkFileParse.chromium(chrome([first, other], folder: [second]))
        let byFirst = ChromeRemovalPlan.make(url: url, lastSavedAt: ISO8601DateFormatter().string(from: old),
                                             entries: entries)
        XCTAssertEqual(byFirst.target?.nodeId, "11", "the copy whose date_added is this save's")
        XCTAssertTrue(byFirst.hasSeveral)
        XCTAssertEqual(byFirst.copies.map(\.nodeId), ["11", "61"])
        XCTAssertEqual(BookmarkRemoveFlow.confirmation(plan: byFirst, fromSafari: false), Copy.Bookmarks.chromeCopies(2))
        let unknown = ChromeRemovalPlan.make(url: url, lastSavedAt: nil, entries: entries)
        XCTAssertEqual(unknown.target?.nodeId, "61", "no instant on record: the newest copy")
        let single = ChromeRemovalPlan.make(url: "https://beta.example/b", lastSavedAt: nil, entries: entries)
        XCTAssertEqual(single.target?.nodeId, "12")
        XCTAssertFalse(single.hasSeveral)
        XCTAssertEqual(BookmarkRemoveFlow.confirmation(plan: single, fromSafari: false), Copy.Bookmarks.removeFromChrome)
        XCTAssertEqual(BookmarkRemoveFlow.confirmation(plan: nil, fromSafari: false), Copy.Bookmarks.removeCicadaOnly)
    }

    @MainActor
    func testRemoveRunsTheScriptWithTheURLAsItsArgument() async {
        let url = "https://alpha.example/a"
        let entries = BookmarkFileParse.chromium(chrome([(id: "11", url: url, at: old)]))
        var ran: [(String, String)] = []
        let outcome = await ChromeBookmarkRemoval.remove(url, nodes: ChromeBookmarkScript.nodes(for: url, in: entries)) {
            ran.append(($0, $1))
            return ChildProcess.Output(status: 0, stdout: "0\n", stderr: "")
        }
        XCTAssertEqual(ran.map(\.1), [url])
        XCTAssertEqual(outcome, .noneMatched, "another profile: nothing deleted, and it says so")
    }

    func testOsascriptsAnswerSaysWhatHappened() {
        XCTAssertEqual(ChromeBookmarkRemoval.outcome(ChildProcess.Output(status: 0, stdout: "1\n", stderr: "")),
                       .removed(1), "only the deletes the script really made")
        XCTAssertEqual(ChromeBookmarkRemoval.outcome(ChildProcess.Output(status: 0, stdout: "0\n", stderr: "")),
                       .noneMatched)
        let denied = ChildProcess.Output(status: 1, stdout: "",
                                         stderr: "execution error: Not authorized to send Apple events to Google Chrome. (-1743)")
        XCTAssertEqual(ChromeBookmarkRemoval.outcome(denied), .denied)
        let slow = ChildProcess.Output(status: 15, stdout: "", stderr: "", timedOut: true)
        XCTAssertEqual(ChromeBookmarkRemoval.outcome(slow), .failed("Chrome did not answer"))
        XCTAssertEqual(ChromeBookmarkRemoval.message(.denied), Copy.Bookmarks.chromeDenied)
        XCTAssertEqual(ChromeBookmarkRemoval.message(.noneMatched), Copy.Bookmarks.chromeNoneMatched)
    }

    /// Review 2026-10-15: Cicada forgets the bookmark first; Chrome is touched only when the backend agreed.
    @MainActor
    func testChromeIsTouchedOnlyAfterTheBackendAgrees() async {
        var order: [String] = []
        let refused = await BookmarkRemoveFlow.run(forget: { order.append("forget"); return false },
                                                   chrome: { order.append("chrome"); return .removed(1) })
        XCTAssertNil(refused)
        XCTAssertEqual(order, ["forget"], "a 409 from the backend: Chrome never asked")
        order = []
        let done = await BookmarkRemoveFlow.run(forget: { order.append("forget"); return true },
                                                chrome: { order.append("chrome"); return .removed(1) })
        XCTAssertEqual(order, ["forget", "chrome"])
        XCTAssertEqual(done, Copy.Bookmarks.removedFromChrome(1))
        let cicadaOnly = await BookmarkRemoveFlow.run(forget: { true }, chrome: nil)
        XCTAssertEqual(cicadaOnly, Copy.Bookmarks.removed)
    }

    // MARK: - The history list

    private func item(_ json: [String: Any]) throws -> MediaFeedItem {
        var base: [String: Any] = ["mediaEntityId": "media-x", "url": "https://alpha.example/a", "title": "Alpha",
                                   "mediaType": "url", "savedAt": "2026-10-01T10:00:00Z"]
        base.merge(json) { $1 }
        return try JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: base))
    }

    func testTheHistoryIsEveryBookmarkNewestSavedFirst() throws {
        let items = [
            try item(["mediaEntityId": "m1", "url": "https://www.alpha.example/a", "title": "Alpha notes",
                      "origin": "chrome-bookmark", "lastSavedAt": "2026-10-15T09:00:00Z"]),
            try item(["mediaEntityId": "m2", "url": "https://beta.example/b", "title": "Beta",
                      "origin": "safari-bookmark", "savedAt": "2026-10-15T11:00:00Z"]),
            try item(["mediaEntityId": "m3", "url": "https://gamma.example/c", "title": "Gamma",
                      "origin": "telegram"]),
            try item(["mediaEntityId": "m4", "url": "https://delta.example/d", "title": "Delta resaved",
                      "origin": "chrome-bookmark", "savedAt": "2026-09-01T10:00:00Z",
                      "lastSavedAt": "2026-10-15T12:00:00Z",
                      "savedWhy": ["reasons": ["design"], "labels": ["The design, the look"], "text": "the type",
                                   "at": "2026-10-15T12:00:05Z", "project": "alpha-project"],
                      "savedWhyHistory": [["reasons": ["product"], "labels": ["The product itself"],
                                           "at": "2026-09-01T10:00:00Z"],
                                          ["reasons": ["design"], "labels": ["The design, the look"],
                                           "text": "the type", "at": "2026-10-15T12:00:05Z",
                                           "project": "alpha-project"]]]),
        ]
        let rows = BookmarkHistory.rows(items, projectNames: ["alpha-project": "Alpha project"])
        XCTAssertEqual(rows.map(\.mediaEntityId), ["m4", "m2", "m1"], "a saved-again bookmark comes back to the top")
        XCTAssertEqual(rows[0].reasons, ["The design, the look", "For Alpha project"], "the newest answer's reasons")
        XCTAssertEqual(rows[0].words, "the type")
        XCTAssertEqual(rows[0].answers, 2)
        XCTAssertEqual(rows[2].host, "alpha.example")
        XCTAssertEqual(rows[1].browser, "Safari")
        XCTAssertEqual(Copy.Bookmarks.secondLine(rows[0]), "The design, the look · For Alpha project · “the type”")
        XCTAssertEqual(Copy.Bookmarks.secondLine(rows[1]), "beta.example", "no answer: the site")
    }

    func testTheHistorySearchesTitlesSitesReasonsAndWords() throws {
        let rows = BookmarkHistory.rows([
            try item(["mediaEntityId": "m1", "url": "https://alpha.example/a", "title": "Café design notes",
                      "origin": "chrome-bookmark"]),
            try item(["mediaEntityId": "m2", "url": "https://beta.example/b", "title": "Beta",
                      "origin": "chrome-bookmark",
                      "savedWhy": ["reasons": ["technique"], "labels": ["A technique to reuse"], "text": "sync trick"]]),
        ])
        XCTAssertEqual(BookmarkHistory.search(rows, query: "cafe").map(\.mediaEntityId), ["m1"], "accents folded")
        XCTAssertEqual(BookmarkHistory.search(rows, query: "TECHNIQUE sync").map(\.mediaEntityId), ["m2"])
        XCTAssertEqual(BookmarkHistory.search(rows, query: "beta.example").map(\.mediaEntityId), ["m2"])
        XCTAssertEqual(BookmarkHistory.search(rows, query: "  ").count, 2)
        XCTAssertTrue(BookmarkHistory.search(rows, query: "nothing here").isEmpty)
        XCTAssertEqual(BookmarkHistory.shortcut(2, in: rows)?.mediaEntityId, rows[1].mediaEntityId)
        XCTAssertNil(BookmarkHistory.shortcut(3, in: rows))
        XCTAssertNil(BookmarkHistory.shortcut(0, in: rows))
    }

    /// Pictures follow the rails: Cicada's own capture thumbnail, else its stored preview, else a monogram — never a
    /// URL the page names.
    func testTheRowPictureIsCicadasOwnCopyOrAMonogram() throws {
        let captured = try item(["origin": "chrome-bookmark", "captureThumb": "/explore/captures/media-x/20261014T100000Z-abcdef/thumb",
                                 "preview": "/entities/media-x/preview?v=1"])
        XCTAssertEqual(BookmarkHistory.row(captured).picture, .capture("/explore/captures/media-x/20261014T100000Z-abcdef/thumb"))
        let previewed = try item(["origin": "chrome-bookmark", "preview": "/entities/media-x/preview?v=1",
                                  "thumbnail": "https://cdn.alpha.example/og.png"])
        XCTAssertEqual(BookmarkHistory.row(previewed).picture, .preview("/entities/media-x/preview?v=1"))
        let bare = try item(["origin": "chrome-bookmark", "thumbnail": "https://cdn.alpha.example/og.png",
                             "captureThumb": "https://cdn.alpha.example/shot.png"])
        XCTAssertEqual(BookmarkHistory.row(bare).picture, .monogram("A"), "a web URL is never loaded")
    }

    func testTheHistoryOpensUnderTheStatusItemOnScreen() {
        let screen = NSRect(x: 0, y: 0, width: 1512, height: 944)
        let frame = BookmarkHistoryController.frame(size: CGSize(width: 400, height: 520),
                                                    anchor: NSRect(x: 1490, y: 945, width: 24, height: 37), screen: screen)
        XCTAssertEqual(frame.maxX, screen.maxX - 8, "kept on screen at the right edge")
        XCTAssertEqual(frame.maxY, 945 - 4)
    }

    func testTheSourcesWireDecodesTheHistoryFields() throws {
        let old = try item([:])
        XCTAssertNil(old.savedWhy)
        XCTAssertTrue(old.savedWhyAnswers.isEmpty, "an older backend's row still decodes")
        let one = try item(["savedWhy": ["reasons": ["design"], "labels": ["The design, the look"], "at": "a"]])
        XCTAssertEqual(one.savedWhyAnswers.map(\.reasons), [["design"]])
    }

    // MARK: - The bookmark page's writes

    @MainActor
    func testAnEditPaintsAtOnceAndRollsBackWhenRefused() async {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        var list = [SavedWhyRecord(reasons: ["design"], labels: ["The design, the look"], at: "2026-10-15T09:00:00+00:00",
                                   addedAt: "2026-10-15T08:59:50+00:00")]
        let binding = Binding(get: { list }, set: { list = $0 })
        let edit = SavedWhyWrite(url: "https://alpha.example/a", at: "2026-10-15T09:00:00+00:00",
                                 answer: SavedWhyAnswer(reasons: ["design", "product"], text: "and the pricing"),
                                 answers: binding, labels: ["design": "The design, the look", "product": "The product itself"])
        let ok = await store.perform(edit)
        XCTAssertTrue(ok)
        XCTAssertEqual(list.first?.reasons, ["design", "product"])
        XCTAssertEqual(list.first?.addedAt, "2026-10-15T08:59:50+00:00", "the moment of saving is kept")
        let writes = api.writes
        XCTAssertEqual(writes.last, "writeSavedWhy:https://alpha.example/a:2026-10-15T09:00:00+00:00:design,product")

        api.savedWhyError = APIError.httpError(409, "{\"detail\":\"Sleep is updating your memory\"}")
        let before = list
        let refused = await store.perform(SavedWhyWrite(url: "https://alpha.example/a", at: nil,
                                                        answer: SavedWhyAnswer(reasons: ["read_later"]), answers: binding))
        XCTAssertFalse(refused)
        XCTAssertEqual(list, before, "rolled back")
    }

    @MainActor
    func testRemoveGoesThroughTheStoreToTheRoute() async {
        let api = FakeSyncAPI()
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        let ok = await store.perform(BookmarkRemove(url: "https://alpha.example/a"))
        XCTAssertTrue(ok)
        let writes = api.writes
        XCTAssertTrue(writes.contains("removeBookmark:https://alpha.example/a"))
        XCTAssertEqual(BookmarkRemove(url: "x").refreshDomains, [.sources, .sourcesOverview, .channels])
    }

    // MARK: - The center: pending, named, confirmed, withdrawn

    private func options() -> SavedWhyOptions {
        SavedWhyOptions(reasons: [.init(key: "design", label: "The design, the look"),
                                  .init(key: "product", label: "The product itself")], projects: [], maxText: 500)
    }

    private func look(_ items: [FreshBookmark], firstSync: Bool = false) -> BookmarkSyncResult {
        var r = BookmarkSyncResult(new: 0, skipped: 0, sources: [
            BookmarkSyncSourceSummary(origin: "chrome-bookmark", channel: "chrome-bookmarks", found: 3, new: 0,
                                      skipped: 0, firstSync: firstSync)])
        r.fresh = items
        r.freshTotal = items.count
        return r
    }

    @MainActor
    private func center(_ api: V3FakeAPI, clock: Date) async -> (SaveWhyCenter, V3Presenter, [(BubbleSize, Bool)]) {
        let defaults = UserDefaults(suiteName: "BookmarksV3Tests.\(UUID().uuidString)")!
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        let presenter = V3Presenter()
        var uptime: TimeInterval = 100
        let center = SaveWhyCenter(prefs: prefs, api: api, presenter: presenter, now: { clock }, uptime: {
            uptime += 1   // every input lands past the arm delay
            return uptime
        })
        await center.refreshOptions()
        return (center, presenter, [])
    }

    /// The bubble opens the question at once, pending; the person taps; the diff names the link; the early look
    /// confirms it; the answer goes out with the save's own instant; the bubble's size is learned.
    @MainActor
    func testTheBubbleOpensTheQuestionAndTheLookBindsTheAnswer() async {
        let api = V3FakeAPI(options: options())
        let (center, presenter, _) = await center(api, clock: now)
        var taught: [(BubbleSize, Bool)] = []
        center.onBubbleFeedback = { _, size, bookmarked in taught.append((size, bookmarked)) }
        center.bubbleSeen(channel: "chrome-bookmarks", size: BubbleSize(width: 336, height: 214))
        XCTAssertEqual(presenter.shown, 1)
        XCTAssertTrue(center.state?.isPending == true)
        XCTAssertFalse(center.confirmed)
        center.input(.tapReason("design"))
        let saved = FreshBookmark(url: "https://alpha.example/a", title: "Alpha", origin: "chrome-bookmark",
                                  channel: "chrome-bookmarks", addedAt: ISO8601DateFormatter().string(from: now))
        center.candidate(saved)
        XCTAssertEqual(center.state?.item?.url, saved.url, "the diff names the link")
        XCTAssertFalse(center.confirmed, "named, not yet confirmed")
        center.input(.clickOutside)   // the person leaves before the backend answers
        await center.settle()
        let early = await api.posts
        XCTAssertTrue(early.isEmpty, "nothing posted before the backend agrees")
        await center.noticed(look([saved]), live: true, early: 1)
        await center.settle()
        let posts = await api.posts
        XCTAssertEqual(posts.map(\.url), [saved.url])
        XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(reasons: ["design"])])
        XCTAssertEqual(posts.map(\.addedAt), [saved.addedAt])
        XCTAssertEqual(presenter.shown, 1, "one panel, bound — never a second for the same save")
        XCTAssertEqual(taught.map(\.1), [true])
    }

    /// A bubble that was not the bookmark's (no bookmark comes): the panel withdraws after its bound and keeps
    /// nothing; the size is refused.
    @MainActor
    func testABubbleWithNoBookmarkWithdrawsAndKeepsNothing() async throws {
        let api = V3FakeAPI(options: options())
        let (center, presenter, _) = await center(api, clock: now)
        var taught: [Bool] = []
        center.onBubbleFeedback = { _, _, bookmarked in taught.append(bookmarked) }
        center.bubbleSeen(channel: "chrome-bookmarks", size: BubbleSize(width: 320, height: 268))
        center.input(.tapReason("product"))
        center.withdraw()   // what the bound's timer does at `pendingBound`
        XCTAssertEqual(center.lastOutcome, .withdrawn)
        XCTAssertEqual(presenter.hidden, 1)
        await center.settle()
        let posts = await api.posts
        XCTAssertTrue(posts.isEmpty, "a tap on a withdrawn panel is never saved against a guess")
        XCTAssertEqual(taught, [false])
        XCTAssertGreaterThan(SaveWhyPolicy.pendingBound, 2.5 + 0.35, "longer than Chrome's own write delay")
    }

    /// Review 2026-10-15: a bookmark the diff saw counts for the bubble whatever the decision — a muted site, a skip —
    /// so it can never be taught a miss.
    @MainActor
    func testABookmarkSeenTeachesTheBubbleEvenWhenTheQuestionIsSkipped() async {
        let api = V3FakeAPI(options: options())
        let (center, _, _) = await center(api, clock: now)
        center.prefs.mute("alpha.example")
        var taught: [Bool] = []
        center.onBubbleFeedback = { _, _, bookmarked in taught.append(bookmarked) }
        center.bubbleSeen(channel: "chrome-bookmarks", size: BubbleSize(width: 336, height: 214))
        let muted = FreshBookmark(url: "https://alpha.example/a", channel: "chrome-bookmarks",
                                  addedAt: ISO8601DateFormatter().string(from: now))
        center.candidate(muted)
        XCTAssertEqual(taught, [true], "recorded at once, before the skip")
        await center.noticed(look([muted]), live: true)
        XCTAssertEqual(center.lastDecision, .skip(.muted))
        center.withdraw()
        XCTAssertEqual(taught, [true], "the withdraw teaches no miss")
        // The backend's look alone (no diff baseline) records it the same way.
        var fromLook: [Bool] = []
        center.onBubbleFeedback = { _, _, bookmarked in fromLook.append(bookmarked) }
        center.bubbleSeen(channel: "chrome-bookmarks", size: BubbleSize(width: 336, height: 214))
        await center.noticed(look([FreshBookmark(url: "https://alpha.example/b", channel: "chrome-bookmarks")]),
                             live: true)
        XCTAssertEqual(fromLook, [true])
    }

    /// The backend refuses the bookmark (a first sync, several at once): the unconfirmed panel withdraws.
    @MainActor
    func testARefusalWithdrawsTheUnconfirmedPanel() async {
        let api = V3FakeAPI(options: options())
        let (center, _, _) = await center(api, clock: now)
        center.bubbleSeen(channel: "chrome-bookmarks", size: BubbleSize(width: 336, height: 214))
        let item = FreshBookmark(url: "https://alpha.example/a", channel: "chrome-bookmarks")
        await center.noticed(look([item], firstSync: true), live: true)
        XCTAssertEqual(center.lastDecision, .skip(.firstSync))
        XCTAssertEqual(center.lastOutcome, .withdrawn)
        // A look that found nothing new yet (Chrome has not written) leaves it waiting.
        center.bubbleSeen(channel: "chrome-bookmarks", size: BubbleSize(width: 336, height: 214))
        await center.noticed(look([]), live: true)
        XCTAssertTrue(center.isShowing, "still waiting for the file")
    }

    /// The app's diff alone opens the question (Safari, or a bubble missed), unconfirmed until the look agrees.
    @MainActor
    func testTheDiffAloneOpensAnUnconfirmedQuestion() async {
        let api = V3FakeAPI(options: options())
        let (center, presenter, _) = await center(api, clock: now)
        let item = FreshBookmark(url: "https://beta.example/b", title: "Beta", origin: "safari-bookmark",
                                 channel: "safari-bookmarks")
        center.candidate(item)
        XCTAssertEqual(presenter.shown, 1)
        XCTAssertFalse(center.confirmed)
        await center.noticed(look([item]).withChannel("safari-bookmarks"), live: true)
        XCTAssertTrue(center.confirmed)
        XCTAssertEqual(presenter.shown, 1)
    }

    func testTheCapturesComponentRefreshesTheSourcesDomain() {
        XCTAssertEqual(VersionVector.mapping["captures"], [.sources])
    }
}

private extension BookmarkSyncResult {
    func withChannel(_ channel: String) -> BookmarkSyncResult {
        var r = self
        r = BookmarkSyncResult(new: r.new, skipped: r.skipped, sources: [
            BookmarkSyncSourceSummary(origin: "safari-bookmark", channel: channel, found: 3, new: 0, skipped: 0,
                                      firstSync: false)], fresh: r.fresh, freshTotal: r.freshTotal)
        return r
    }
}

private actor V3FakeAPI: SavedWhyAPI {
    let options: SavedWhyOptions
    var posts: [(url: String, answer: SavedWhyAnswer, addedAt: String?)] = []
    init(options: SavedWhyOptions) { self.options = options }
    func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult {
        BookmarkSyncResult(new: 0, skipped: 0, sources: [])
    }
    func savedWhyOptions() async throws -> SavedWhyOptions { options }
    func saveWhy(url: String, answer: SavedWhyAnswer, at: Date, addedAt: String?) async throws {
        posts.append((url, answer, addedAt))
    }
}

@MainActor
private final class V3Presenter: SaveWhyPresenting {
    var shown = 0
    var hidden = 0
    func show(_ center: SaveWhyCenter) { shown += 1 }
    func hide() { hidden += 1 }
    func focusText() {}
}

/// The watcher's learning, reachable without a running browser.
@MainActor
enum BookmarkBubbleWatcherHarness {
    static func make(defaults: UserDefaults) -> BookmarkBubbleWatcher { BookmarkBubbleWatcher(defaults: defaults) }
}
