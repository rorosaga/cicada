import XCTest
@testable import CicadaApp

/// G245 (plan 2.1 `owner: app`, critic app6) — the app overwrites state, health and why from its own switches and
/// permissions; count and lastReadAt stay the backend's.
@MainActor
final class SourceStreamOverlayTests: XCTestCase {
    private let now = SourceStreamsFixture.now
    private let chrome = BrowserInventory.catalog.first { $0.id == "chrome" }!
    private let safari = BrowserInventory.catalog.first { $0.id == "safari" }!

    private var entries: [SourceCatalogEntry] {
        SourceCatalog.entries(browsers: [chrome, safari], wisprPresent: false, hexPresent: false, overview: [])
    }

    private func resolve(_ app: StreamAppState = StreamAppState()) throws -> ResolvedStreams {
        SourceStreamOverlay.resolve(try SourceStreamsFixture.load(), app: app, entries: entries, now: now)
    }

    func testABackendOwnedStreamPassesThroughUntouched() throws {
        let resolved = try resolve(StreamAppState(readers: [AppleNotesWatcher.channel: false]))
        let bookmarks = try XCTUnwrap(resolved.stream("x.bookmarks"))
        XCTAssertEqual(bookmarks.stream.state, .on)
        XCTAssertEqual(bookmarks.stream.health, .read)
        XCTAssertEqual(bookmarks.word, .read)
        XCTAssertEqual(bookmarks.tone, .browser)
        XCTAssertEqual(try XCTUnwrap(resolved.stream("youtube.watch_later")).word, .signedOut)
        XCTAssertEqual(try XCTUnwrap(resolved.stream("youtube.history")).word, .off)
        XCTAssertEqual(resolved.accounts["x"]?.handle, "@alpha-account")
    }

    func testAnAppOwnedStreamFollowsItsReadersOwnSwitchWhateverTheBackendSays() throws {
        // The backend says Notes is on and read; this Mac's reader was turned off.
        let off = try resolve(StreamAppState(readers: [AppleNotesWatcher.channel: false]))
        let notes = try XCTUnwrap(off.stream("notes.notes"))
        XCTAssertEqual(notes.stream.state, .off)
        XCTAssertNil(notes.stream.health)
        XCTAssertEqual(notes.word, .off)
        XCTAssertEqual(notes.stream.count, 88, "the count stays the backend's")
        XCTAssertEqual(notes.stream.lastReadAt, ISODate.parse("2026-11-24T07:30:00Z"), "and so does the last read")

        let on = try resolve(StreamAppState(readers: [AppleNotesWatcher.channel: true]))
        XCTAssertEqual(try XCTUnwrap(on.stream("notes.notes")).word, .read)
        XCTAssertEqual(try XCTUnwrap(on.stream("notes.notes")).reader, AppleNotesWatcher.channel,
                       "Notes has a run-now: Check can run it")
    }

    func testAnAppReaderTurnedOnThatHasNeverReadIsNotReadYet() throws {
        let response = SourceStreamsResponse(sources: [SourceStreamsSource(id: "notes", streams: [
            SourceStream(id: "notes.notes", label: "Notes", kind: .notes, how: .app, owner: .app, state: .on)])])
        let resolved = SourceStreamOverlay.resolve(response, app: StreamAppState(readers: [AppleNotesWatcher.channel: true]),
                                                   entries: entries, now: now)
        XCTAssertEqual(try XCTUnwrap(resolved.stream("notes.notes")).word, .notReadYet)
    }

    func testAPermissionMacOSTookAwayIsNeedsAccessWithItsFix() throws {
        let app = StreamAppState(readers: [AppleNotesWatcher.channel: false],
                                 waitingOn: [AppleNotesWatcher.channel: Copy.sourceNeedsAccess])
        let notes = try XCTUnwrap(resolve(app).stream("notes.notes"))
        XCTAssertEqual(notes.stream.state, .on, "the person turned it on; macOS stopped it")
        XCTAssertEqual(notes.word, .needsAccess)
        XCTAssertEqual(notes.fix, .notes)
        XCTAssertEqual(notes.tone, .attention)
        XCTAssertEqual(notes.stream.why, Copy.sourceNeedsAccess)
    }

    func testAFailedReadThatIsNotAPermissionIsCouldntRead() throws {
        let app = StreamAppState(readers: [AppleNotesWatcher.channel: true],
                                 waitingOn: [AppleNotesWatcher.channel: "The notes dump was empty."])
        let notes = try XCTUnwrap(resolve(app).stream("notes.notes"))
        XCTAssertEqual(notes.word, .couldntRead)
        XCTAssertNil(notes.fix)
        XCTAssertEqual(notes.stream.why, "The notes dump was empty.")
    }

    func testAnAppRemovedFromThisMacIsNotInstalled() throws {
        let notes = try XCTUnwrap(resolve(StreamAppState(notInstalled: [AppleNotesWatcher.channel])).stream("notes.notes"))
        XCTAssertEqual(notes.stream.state, .unavailable)
        XCTAssertEqual(notes.word, .notInstalled)
        XCTAssertNil(notes.reader, "nothing to run")
    }

    func testFullDiskAccessMissingForSafariReadsNeedsAccessEvenWhileTheSwitchIsOn() throws {
        let response = SourceStreamsResponse(sources: [SourceStreamsSource(id: "browser:safari", streams: [
            SourceStream(id: "browser:safari.bookmarks", label: "Bookmarks", kind: .saved, how: .app, owner: .app,
                         state: .on, lastReadAt: now)])])
        let app = StreamAppState(readers: ["safari-bookmarks": true], permissions: [.fullDiskAccess: false])
        let safariRow = try XCTUnwrap(SourceStreamOverlay.resolve(response, app: app, entries: entries, now: now)
            .stream("browser:safari.bookmarks"))
        XCTAssertEqual(safariRow.word, .needsAccess)
        XCTAssertEqual(safariRow.fix, .fullDiskAccess)
        let granted = StreamAppState(readers: ["safari-bookmarks": true], permissions: [.fullDiskAccess: true])
        XCTAssertEqual(try XCTUnwrap(SourceStreamOverlay.resolve(response, app: granted, entries: entries, now: now)
            .stream("browser:safari.bookmarks")).word, .read)
        // A permission nothing has checked is unknown, and unknown counts as given: never a false alarm.
        let unknown = StreamAppState(readers: ["safari-bookmarks": true])
        XCTAssertEqual(try XCTUnwrap(SourceStreamOverlay.resolve(response, app: unknown, entries: entries, now: now)
            .stream("browser:safari.bookmarks")).word, .read)
    }

    func testABrowsersThreeReadersAreToldApartByTheStream() throws {
        let readers: [String: Bool] = ["chrome-bookmarks": true, TabGroupWatcher.channel: false,
                                       WatchHistoryWatcher.channel: true]
        let resolved = try resolve(StreamAppState(readers: readers))
        XCTAssertEqual(try XCTUnwrap(resolved.stream("browser:chrome.bookmarks")).stream.state, .on)
        XCTAssertEqual(try XCTUnwrap(resolved.stream("browser:chrome.tab_groups")).stream.state, .off)
        XCTAssertEqual(try XCTUnwrap(resolved.stream("browser:chrome.history")).stream.state, .on)
        XCTAssertEqual(try XCTUnwrap(resolved.stream("browser:chrome.history")).reader, WatchHistoryWatcher.channel)
        XCTAssertEqual(try XCTUnwrap(resolved.stream("browser:chrome.tab_groups")).reader, TabGroupWatcher.channel)
        XCTAssertEqual(try XCTUnwrap(resolved.stream("browser:chrome.bookmarks")).reader, "chrome-bookmarks")
    }

    func testAnAppStreamWithNoSwitchOfThisMacsKeepsTheBackendsWords() throws {
        // Nothing in `readers` for chrome: the overlay has no switch to read and must not invent one.
        let chrome = try XCTUnwrap(resolve().stream("browser:chrome.bookmarks"))
        XCTAssertEqual(chrome.stream.state, .on)
        XCTAssertEqual(chrome.word, .read)
        XCTAssertNil(chrome.reader)
    }

    // MARK: Saves you make

    private func saves(_ app: StreamAppState) throws -> ResolvedStream {
        try XCTUnwrap(resolve(app).stream("x.saves"))
    }

    func testSavesYouMakeIsTheNotchsPerMacFlag() throws {
        XCTAssertEqual(try saves(StreamAppState()).word, .off)
        let on = try saves(StreamAppState(siteSavesOn: ["x"]))
        XCTAssertEqual(on.stream.state, .on)
        XCTAssertEqual(on.word, .read)
        XCTAssertNil(on.fix)
        XCTAssertNil(on.reader, "nothing to run: Check reads the flag and the permission")
    }

    func testWithoutAccessibilityTheRowSaysSoWithTheButtonAndNeverPrompts() throws {
        let row = try saves(StreamAppState(siteSavesOn: ["x"], permissions: [.accessibility: false]))
        XCTAssertEqual(row.stream.state, .on, "the flag is the person's")
        XCTAssertEqual(row.word, .needsAccess)
        XCTAssertEqual(row.fix, .accessibility)
        XCTAssertEqual(row.stream.why, Copy.Streams.accessibilityWhy)
        // Off stays off, whatever Accessibility says: nothing is asked of a person who did not turn it on.
        let off = try saves(StreamAppState(permissions: [.accessibility: false]))
        XCTAssertEqual(off.word, .off)
        XCTAssertNil(off.fix)
    }

    func testSavesYouMakeIsPerSiteKeyedBySourceId() throws {
        XCTAssertEqual(try saves(StreamAppState(siteSavesOn: ["instagram"])).word, .off)
    }
}
