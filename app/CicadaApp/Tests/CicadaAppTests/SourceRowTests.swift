import XCTest
@testable import CicadaApp

/// Round 4 (T-Sources, decision 3) — one row, one set of words, every host. Synthetic channels only.
final class SourceRowTests: XCTestCase {
    private let now = ISO8601DateFormatter().date(from: "2026-09-24T21:40:00Z")!
    private let en = Locale(identifier: "en_US")

    private func channel(_ id: String = "chrome-bookmarks", lastSync: String? = "2026-09-24T21:38:00Z",
                         count: Int = 2104, noun: String? = "bookmark", error: String? = nil,
                         actions: [String] = ["sync"], parts: [ChannelPart] = []) -> SourceChannel {
        SourceChannel(id: id, label: id, connected: lastSync != nil, count: count, lastSync: lastSync,
                      lastError: error, countNoun: noun, actions: actions, parts: parts)
    }

    func testLastSyncedIsFullWordsAndJustNowUnderAMinute() {
        XCTAssertEqual(SourceRowText.lastSynced(now.addingTimeInterval(-20), now: now, locale: en), "Last synced just now")
        XCTAssertEqual(SourceRowText.lastSynced(now.addingTimeInterval(30), now: now, locale: en), "Last synced just now",
                       "a clock a little ahead never reads 'in 30 seconds'")
        XCTAssertEqual(SourceRowText.lastSynced(now.addingTimeInterval(-120), now: now, locale: en), "Last synced 2 minutes ago")
        XCTAssertEqual(SourceRowText.lastSynced(now.addingTimeInterval(-3600), now: now, locale: en), "Last synced 1 hour ago")
    }

    func testAnImportIsNeverASync() {
        let today = now.addingTimeInterval(-3 * 3600)
        let text = SourceRowText.imported(today, now: now, locale: en, timeZone: TimeZone(identifier: "UTC")!)
        XCTAssertTrue(text.hasPrefix("Imported "), text)
        XCTAssertFalse(text.contains("synced"))
        let status = SourceRowText.status(channel: channel("chat-export:claude", actions: ["import"]), watch: nil, run: nil)
        XCTAssertEqual(status, .imported(ISO8601DateFormatter().date(from: "2026-09-24T21:38:00Z")!))
    }

    func testStatusPrecedenceRunThenWatchThenErrorThenLastSync() {
        let run = SyncActivity.Run(detail: "Reading 3 open groups", fraction: nil, cancellable: true)
        XCTAssertEqual(SourceRowText.status(channel: channel(), watch: .watching, run: run),
                       .syncing(detail: "Reading 3 open groups", fraction: nil, cancellable: true))
        XCTAssertEqual(SourceRowText.status(channel: channel(), watch: .syncing, run: nil),
                       .syncing(detail: nil, fraction: nil, cancellable: false), "another reader's sync has no ×")
        XCTAssertEqual(SourceRowText.status(channel: channel(), watch: .blocked, run: nil), .problem(Copy.sourceNeedsAccess))
        XCTAssertEqual(SourceRowText.status(channel: channel(error: "Can't read the file. Try again."), watch: nil, run: nil),
                       .problem("Can't read the file"))
        XCTAssertEqual(SourceRowText.status(channel: channel(), watch: .watching, run: nil),
                       .synced(ISO8601DateFormatter().date(from: "2026-09-24T21:38:00Z")!))
        XCTAssertEqual(SourceRowText.status(channel: channel(lastSync: nil), watch: nil, run: nil), .idle)
        XCTAssertEqual(SourceRowText.status(channel: nil, watch: nil, run: nil), .idle)
        let connectedNoDate = SourceChannel(id: "contacts-local", label: "Contacts", connected: true, count: 0,
                                            actions: ["sync", "manage"])
        XCTAssertEqual(SourceRowText.status(channel: connectedNoDate, watch: nil, run: nil), .notYet)
        let files = SourceChannel(id: "files", label: "Files & links", connected: true, count: 3, actions: ["import"])
        XCTAssertEqual(SourceRowText.status(channel: files, watch: nil, run: nil), .idle,
                       "a source that never syncs is never 'Not synced yet'")
    }

    func testTheCountLineGroupsInTheReadersLocaleAndSaysItsParts() {
        let safari = channel("safari-bookmarks", count: 1927,
                             parts: [ChannelPart(key: "reading-list", count: 36), ChannelPart(key: "favorites", count: 12)])
        XCTAssertEqual(SourceRowText.countLine(safari, locale: en), "1,927 bookmarks · Reading List 36 · Favorites 12")
        XCTAssertEqual(SourceRowText.countLine(safari, locale: Locale(identifier: "de_DE")),
                       "1.927 bookmarks · Reading List 36 · Favorites 12")
        let contacts = channel("contacts-local", count: 214, noun: "contact", parts: [ChannelPart(key: "people", count: 18)])
        XCTAssertEqual(SourceRowText.countLine(contacts, locale: en), "214 contacts · matched to 18 people Cicada knows")
        XCTAssertNil(ChannelPartsText.phrase(ChannelPart(key: "surprise", count: 3), locale: en), "an unknown key says nothing")
        XCTAssertNil(SourceRowText.countLine(channel(lastSync: nil, noun: nil), locale: en))
    }

    func testTheRightSideAndTheSecondLineFollowTheStatus() {
        XCTAssertEqual(SourceRowText.trailing(.syncing(detail: "Reading 2 of 3 open groups", fraction: 0.66, cancellable: true),
                                              now: now, locale: en), Copy.syncingNow)
        XCTAssertEqual(SourceRowText.trailing(.notYet, now: now, locale: en), Copy.notSyncedYet)
        XCTAssertNil(SourceRowText.trailing(.idle, now: now, locale: en))
        let model = SourceRowModel(id: "chrome-tab-groups", origin: "chrome", title: "Open tab groups", line: "3 open groups",
                                   status: .syncing(detail: "Reading 2 of 3 open groups", fraction: nil, cancellable: true))
        XCTAssertEqual(SourceRowText.secondLine(model), "Reading 2 of 3 open groups", "a running sync's detail replaces the line")
        XCTAssertEqual(SourceRowText.accessibilityLabel(model, now: now, locale: en),
                       "Open tab groups. Reading 2 of 3 open groups. Syncing now")
    }
}
