import XCTest
@testable import CicadaApp

// SNSS bytes written by hand from Chromium's format (`command_storage_backend.cc`,
// `session_service_commands.cc`, `base/token.cc`) — never read from a real profile.
fileprivate func le16(_ v: UInt16) -> [UInt8] { [UInt8(v & 0xff), UInt8(v >> 8)] }
fileprivate func le32(_ v: UInt32) -> [UInt8] { (0..<4).map { UInt8((v >> (8 * UInt32($0))) & 0xff) } }
fileprivate func le32i(_ v: Int32) -> [UInt8] { le32(UInt32(bitPattern: v)) }
fileprivate func le64(_ v: UInt64) -> [UInt8] { (0..<8).map { UInt8((v >> (8 * UInt64($0))) & 0xff) } }

struct PickleWriter {
    private(set) var payload: [UInt8] = []
    mutating func int32(_ v: Int32) { payload += le32i(v) }
    mutating func uint32(_ v: UInt32) { payload += le32(v) }
    mutating func uint64(_ v: UInt64) { payload += le64(v) }
    mutating func bool(_ v: Bool) { int32(v ? 1 : 0) }
    mutating func string(_ s: String) { let b = Array(s.utf8); int32(Int32(b.count)); payload += b; pad() }
    mutating func string16(_ s: String) {
        let units = Array(s.utf16); int32(Int32(units.count)); for u in units { payload += le16(u) }; pad()
    }
    private mutating func pad() { while payload.count % 4 != 0 { payload.append(0) } }
    var bytes: [UInt8] { le32(UInt32(payload.count)) + payload }
}

struct SNSSWriter {
    enum Era { case m87, m88, m113 }
    private(set) var data = Data()
    init(version: Int32 = 3, magic: UInt32 = 0x53534E53) { data.append(contentsOf: le32(magic) + le32i(version)) }
    mutating func command(_ id: UInt8, _ contents: [UInt8]) {
        data.append(contentsOf: le16(UInt16(contents.count + 1)) + [id] + contents)
    }
    mutating func marker() { command(255, []) }
    mutating func tabWindow(window: Int32, tab: Int32) { command(0, le32i(window) + le32i(tab)) }
    mutating func tabIndex(tab: Int32, index: Int32) { command(2, le32i(tab) + le32i(index)) }
    mutating func selected(tab: Int32, index: Int32) { command(7, le32i(tab) + le32i(index)) }
    mutating func navigation(tab: Int32, index: Int32, url: String, title: String) {
        var p = PickleWriter()
        p.int32(tab); p.int32(index); p.string(url); p.string16(title)
        p.string("encoded page state — never read"); p.int32(0)
        command(6, p.bytes)
    }
    mutating func tabClosed(_ tab: Int32) { command(16, le32i(tab) + [0, 0, 0, 0] + le64(0)) }
    mutating func windowClosed(_ window: Int32) { command(17, le32i(window) + [0, 0, 0, 0] + le64(0)) }
    mutating func group(tab: Int32, high: UInt64, low: UInt64, has: Bool = true) {
        // Built in steps: as one `+` chain of six arrays, swiftc gives up ("unable to type-check this expression in
        // reasonable time") — verified while reviewing this plan.
        var payload = le32i(tab)
        payload += [0, 0, 0, 0]
        payload += le64(high)
        payload += le64(low)
        payload.append(has ? 1 : 0)
        payload += [UInt8](repeating: 0, count: 7)
        command(25, payload)
    }
    mutating func metadata(high: UInt64, low: UInt64, title: String, color: UInt32, collapsed: Bool = false,
                           savedGuid: String? = nil, era: Era = .m113) {
        var p = PickleWriter()
        p.uint64(high); p.uint64(low); p.string16(title); p.uint32(color)
        if era != .m87 { p.bool(collapsed) }
        if era == .m113 {
            p.bool(savedGuid != nil)
            if let savedGuid { p.string(savedGuid) }
        }
        command(27, p.bytes)
    }
    mutating func garbageTail() { data.append(contentsOf: le16(200) + [27, 1, 2]) }
}

/// Round 4 (G160 first slice) — Chrome's open tab groups out of its session file, and nothing else.
final class ChromiumSessionParserTests: XCTestCase {
    /// Window 1: tab 12 (index 0) and tab 11 (index 1) in alpha-project, tab 13 ungrouped, tab 14 (index 3) in Papers.
    private func session(era: SNSSWriter.Era = .m113) -> SNSSWriter {
        var w = SNSSWriter()
        for (tab, index) in [(11, 1), (12, 0), (13, 2), (14, 3)] as [(Int32, Int32)] {
            w.tabWindow(window: 1, tab: tab)
            w.tabIndex(tab: tab, index: index)
        }
        w.navigation(tab: 11, index: 0, url: "https://example.com/alpha/doc", title: "Design doc")
        w.navigation(tab: 12, index: 0, url: "https://example.com/alpha/issues", title: "Issues")
        w.navigation(tab: 13, index: 0, url: "https://example.org/news", title: "News")
        w.navigation(tab: 14, index: 0, url: "https://example.org/paper", title: "A paper")
        w.metadata(high: 1, low: 2, title: "alpha-project", color: 1, era: era)
        w.metadata(high: 3, low: 4, title: "Papers", color: 4, era: era)
        w.group(tab: 11, high: 1, low: 2)
        w.group(tab: 12, high: 1, low: 2)
        w.group(tab: 14, high: 3, low: 4)
        w.marker()
        return w
    }

    func testTwoGroupsWithTheirTabsInWindowOrder() throws {
        let groups = try ChromiumSessionParser.parse(session().data)
        XCTAssertEqual(groups.map(\.title), ["alpha-project", "Papers"])
        XCTAssertEqual(groups.map(\.color), ["blue", "green"])
        XCTAssertEqual(groups[0].tabs.map(\.title), ["Issues", "Design doc"], "ordered by the tab's index")
        XCTAssertEqual(groups[0].key, "00000000000000010000000000000002")
        XCTAssertFalse(groups.flatMap(\.tabs).contains { $0.title == "News" }, "an ungrouped tab is never read out")
    }

    func testTheSelectedNavigationIsTheTabsPageNotTheLastOne() throws {
        var w = session()
        w.navigation(tab: 11, index: 1, url: "https://example.com/alpha/later", title: "Later")
        w.selected(tab: 11, index: 0)
        let tabs = try ChromiumSessionParser.parse(w.data)[0].tabs
        XCTAssertEqual(tabs.map(\.title), ["Issues", "Design doc"])
    }

    func testShortPicklesFromBeforeM88AndM113AreReadNotRefused() throws {
        let old = try ChromiumSessionParser.parse(session(era: .m87).data)
        XCTAssertEqual(old.map(\.title), ["alpha-project", "Papers"])
        XCTAssertEqual(old.map(\.collapsed), [false, false])
        XCTAssertNil(old[0].savedGuid)
        var w = SNSSWriter()
        w.tabWindow(window: 1, tab: 1)
        w.navigation(tab: 1, index: 0, url: "https://example.com/a", title: "A")
        w.metadata(high: 9, low: 9, title: "Folded", color: 2, collapsed: true, era: .m88)
        w.group(tab: 1, high: 9, low: 9)
        w.marker()
        let folded = try ChromiumSessionParser.parse(w.data)
        XCTAssertEqual(folded.map(\.collapsed), [true])
        XCTAssertEqual(folded.map(\.color), ["red"])
    }

    func testASavedGroupCarriesItsGuid() throws {
        var w = SNSSWriter()
        w.tabWindow(window: 1, tab: 1)
        w.navigation(tab: 1, index: 0, url: "https://example.com/a", title: "A")
        w.metadata(high: 5, low: 6, title: "Saved", color: 0, savedGuid: "7c9e6679-7425-40de-944b-e07fc1f90ae7")
        w.group(tab: 1, high: 5, low: 6)
        w.marker()
        XCTAssertEqual(try ChromiumSessionParser.parse(w.data).first?.savedGuid, "7c9e6679-7425-40de-944b-e07fc1f90ae7")
    }

    func testAClosedTabOrWindowLeavesItsGroupAndAnEmptyGroupIsDropped() throws {
        var w = session()
        w.tabClosed(11)
        w.group(tab: 12, high: 1, low: 2, has: false)
        let groups = try ChromiumSessionParser.parse(w.data)
        XCTAssertEqual(groups.map(\.title), ["Papers"], "alpha-project has no open tab left")
        var closed = session()
        closed.windowClosed(1)
        XCTAssertEqual(try ChromiumSessionParser.parse(closed.data), [])
    }

    func testATornTailKeepsWhatCameBefore() throws {
        var w = session()
        w.garbageTail()
        XCTAssertEqual(try ChromiumSessionParser.parse(w.data).count, 2)
    }

    func testOnlyAClearFileWithItsMarkerIsTrusted() {
        XCTAssertThrowsError(try ChromiumSessionParser.parse(SNSSWriter(version: 5).data)) {
            XCTAssertEqual($0 as? ChromiumSessionError, .unsupportedVersion(5), "encrypted — never decoded")
        }
        XCTAssertThrowsError(try ChromiumSessionParser.parse(SNSSWriter(magic: 0x12345678).data)) {
            XCTAssertEqual($0 as? ChromiumSessionError, .notASessionFile)
        }
        var unfinished = SNSSWriter()
        unfinished.tabWindow(window: 1, tab: 1)
        XCTAssertThrowsError(try ChromiumSessionParser.parse(unfinished.data)) {
            XCTAssertEqual($0 as? ChromiumSessionError, .noMarker, "Chrome was still writing its initial state")
        }
    }

    /// A card's Sync now shows `localizedDescription` — a refused file must read as a sentence there too.
    func testAnUnreadableFileIsSaidInWords() {
        XCTAssertEqual(ChromiumSessionError.unsupportedVersion(5).localizedDescription, Copy.tabGroupsUnreadable)
    }

    func testSessionFilesAreNewestFirstAndNeverTheRecentlyClosedList() {
        let dir = URL(fileURLWithPath: "/tmp/Sessions")
        let files = ChromiumSessionFiles.sessionFiles(
            in: dir, names: ["Tabs_13370000000000009", "Session_13370000000000001", "Session_13370000000000002",
                             "Session_x", ".DS_Store"])
        XCTAssertEqual(files.map(\.lastPathComponent), ["Session_13370000000000002", "Session_13370000000000001"])
    }

    func testTheNewestFileStillBeingWrittenFallsBackToTheOneBefore() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("Sessions-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        var unfinished = SNSSWriter()
        unfinished.tabWindow(window: 1, tab: 1)
        try unfinished.data.write(to: dir.appendingPathComponent("Session_2"))
        try session().data.write(to: dir.appendingPathComponent("Session_1"))
        XCTAssertEqual(try ChromiumSessionFiles.newestGroups(in: dir).map(\.title), ["alpha-project", "Papers"])
        XCTAssertThrowsError(try ChromiumSessionFiles.newestGroups(in: dir.appendingPathComponent("nope"))) {
            guard let error = $0 as? BrowserFileError, case .missing = error else { return XCTFail("\($0)") }
        }
    }
}
