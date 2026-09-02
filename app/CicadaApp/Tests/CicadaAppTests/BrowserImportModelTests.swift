import XCTest
@testable import CicadaApp

/// R5 — folder selection is a minimal set of path prefixes; R3/R8 — the
/// honest one-line result. Pure models, no view.
final class BrowserImportModelTests: XCTestCase {

    private func node(_ path: String, _ count: Int, _ children: [BookmarkFolderNode] = []) -> BookmarkFolderNode {
        BookmarkFolderNode(name: path.split(separator: "/").last.map(String.init) ?? "All bookmarks",
                           path: path, count: count, children: children)
    }

    private var tree: BookmarkFolderNode {
        node("", 6, [
            node("BookmarksBar", 5, [node("BookmarksBar/Big Folder", 4)]),
            node("com.apple.ReadingList", 1),
        ])
    }

    func testDefaultSelectionIsEverythingAndSendsNoFilter() {
        let sel = BookmarkFolderSelection.all
        XCTAssertNil(sel.requestFolders)
        XCTAssertEqual(sel.selectedCount(in: tree), 6)
        XCTAssertTrue(sel.isSelected(""))
        XCTAssertTrue(sel.isSelected("BookmarksBar/Big Folder"), "a selected parent covers its children")
    }

    func testTogglingOneFolderNarrowsTheRequest() {
        var sel = BookmarkFolderSelection.all
        sel.toggle(tree)                                   // untick root → nothing
        XCTAssertEqual(sel.selectedCount(in: tree), 0)
        XCTAssertEqual(sel.requestFolders, [])
        sel.toggle(tree.children[0].children[0])           // tick Big Folder
        XCTAssertEqual(sel.requestFolders, ["BookmarksBar/Big Folder"])
        XCTAssertEqual(sel.selectedCount(in: tree), 4)
        XCTAssertFalse(sel.isSelected("BookmarksBar"))
    }

    func testTogglingAParentClearsItsChildrenFromTheRequest() {
        var sel = BookmarkFolderSelection(paths: ["BookmarksBar/Big Folder"])
        sel.toggle(tree.children[0])                       // tick Favorites
        XCTAssertEqual(sel.requestFolders, ["BookmarksBar"], "the child is implied, not sent twice")
        XCTAssertEqual(sel.selectedCount(in: tree), 5)
    }

    /// Unticking a folder that was only covered by an ancestor drops the
    /// ancestor — the user is narrowing, not carving, and re-ticks siblings.
    func testUntickingACoveredChildDropsTheCoveringAncestor() {
        var sel = BookmarkFolderSelection(paths: ["BookmarksBar"])
        sel.toggle(tree.children[0].children[0])           // untick Big Folder
        XCTAssertEqual(sel.requestFolders, [])
        XCTAssertFalse(sel.isSelected("BookmarksBar"))
        XCTAssertEqual(sel.selectedCount(in: tree), 0)
    }

    /// A prefix match is at a segment boundary only: "BookmarksBar" must not
    /// cover a sibling whose name merely starts with the same letters.
    func testPrefixMatchesAtSegmentBoundariesOnly() {
        let sel = BookmarkFolderSelection(paths: ["BookmarksBar"])
        XCTAssertTrue(sel.isSelected("BookmarksBar/Big Folder"))
        XCTAssertFalse(sel.isSelected("BookmarksBarMore"))
    }

    func testDeviceSummaryLine() {
        let devices = [SafariTabsDevice(name: "Bob's iPhone", count: 202), SafariTabsDevice(name: "Bob's MacBook", count: 0)]
        XCTAssertEqual(SafariTabsDevice.line(devices[0]), "Bob's iPhone · 202 tabs")
        XCTAssertEqual(SafariTabsDevice.line(devices[1]), "Bob's MacBook · 0 tabs")
        XCTAssertEqual(SafariTabsDevice.line(SafariTabsDevice(name: "iPad", count: 1)), "iPad · 1 tab")
    }

    func testSyncSummaries() {
        XCTAssertEqual(BrowserImportSummary.tabs(SafariTabsSyncResult(new: 180, skipped: 22, seen: 202, devices: [])),
                       "180 new · 22 already saved · 202 tabs seen")
        XCTAssertEqual(BrowserImportSummary.tabs(SafariTabsSyncResult(new: 0, skipped: 1, seen: 1, devices: [])),
                       "Nothing new · 1 already saved · 1 tab seen")
        XCTAssertEqual(BrowserImportSummary.bookmarks(BookmarkSyncResult(new: 0, skipped: 500, sources: [])),
                       "Nothing new · 500 already saved")
        XCTAssertEqual(BrowserImportSummary.bookmarks(BookmarkSyncResult(new: 3, skipped: 0, sources: [])),
                       "3 new · 0 already saved")
    }

    func testDecodesTheBackendShapes() throws {
        let preview = try JSONDecoder().decode(SafariTabsPreview.self, from: Data(#"{"total":3,"devices":[{"name":"Bob's iPhone","count":3}],"warnings":[]}"#.utf8))
        XCTAssertEqual(preview.devices.first?.count, 3)
        XCTAssertNil(preview.devices.first?.selected, "a preview row carries no selection yet")
        let synced = try JSONDecoder().decode(SafariTabsSyncResult.self, from: Data(#"{"new":1,"skipped":2,"seen":3,"devices":[{"name":"iPad","count":3,"selected":true}]}"#.utf8))
        XCTAssertEqual(synced.devices.first?.selected, true)
        let tree = try JSONDecoder().decode(BookmarkTreePreview.self, from: Data(#"{"sources":[{"origin":"safari-bookmark","total":1,"tree":{"name":"All bookmarks","path":"","count":1,"children":[{"name":"Reading List","path":"com.apple.ReadingList","count":1,"children":[]}]}}]}"#.utf8))
        XCTAssertEqual(tree.sources[0].tree.children[0].name, "Reading List")
        XCTAssertEqual(tree.sources[0].tree.children[0].id, "com.apple.ReadingList", "id is the path key, not the display name")
        // R4 — the per-source `channel` the backend now stamps is optional on
        // decode, so an older backend without it still parses.
        let legacy = try JSONDecoder().decode(BookmarkSyncResult.self, from: Data(#"{"new":1,"skipped":0,"sources":[{"origin":"safari-bookmark","found":1,"new":1,"skipped":0}]}"#.utf8))
        XCTAssertNil(legacy.sources[0].channel)
        let current = try JSONDecoder().decode(BookmarkSyncResult.self, from: Data(#"{"new":1,"skipped":0,"sources":[{"origin":"safari-bookmark","channel":"safari-bookmarks","found":1,"new":1,"skipped":0}]}"#.utf8))
        XCTAssertEqual(current.sources[0].channel, "safari-bookmarks")
    }
}
