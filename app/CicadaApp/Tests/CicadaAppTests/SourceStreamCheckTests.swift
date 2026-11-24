import XCTest
@testable import CicadaApp

/// G245 (plan 3.3) — Check now ends every stream that is on in one definite word and a time.
@MainActor
final class SourceStreamCheckTests: XCTestCase {
    private let now = SourceStreamsFixture.now
    private let chrome = BrowserInventory.catalog.first { $0.id == "chrome" }!

    private var entries: [SourceCatalogEntry] {
        SourceCatalog.entries(browsers: [chrome], wisprPresent: false, hexPresent: false, overview: [])
    }

    private final class Log {
        var ran: [String] = []
        var asked: [[String]] = []
        var published = 0
        var runFails: Set<String> = []
        var backend: SourceStreamsResponse?
        var backendThrows = false
    }

    private func model(_ log: Log) -> SourceStreamCheckModel {
        SourceStreamCheckModel(deps: SourceStreamCheckModel.Deps(
            now: { self.now },
            runReader: { channel in
                log.ran.append(channel)
                if log.runFails.contains(channel) { throw APIError.serverUnreachable }
                return "ok"
            },
            askBackend: { sources in
                log.asked.append(sources)
                if log.backendThrows { throw APIError.httpError(404, "Not Found") }
                return log.backend ?? SourceStreamsResponse()
            }))
    }

    private func resolve(_ response: SourceStreamsResponse, _ app: StreamAppState) -> ResolvedStreams {
        SourceStreamOverlay.resolve(response, app: app, entries: entries, now: now)
    }

    private func run(_ m: SourceStreamCheckModel, _ log: Log, sources: [String] = [], app: StreamAppState,
                     response: SourceStreamsResponse? = nil) async throws {
        let base = try response ?? SourceStreamsFixture.load()
        await m.check(sources: sources, current: resolve(base, app), resolve: { self.resolve($0, app) },
                      publish: { _ in log.published += 1 })
    }

    private let appOn = StreamAppState(readers: [AppleNotesWatcher.channel: true, "chrome-bookmarks": true],
                                       siteSavesOn: ["x"])

    // MARK: The app's readers

    func testAnAppReaderWithARunNowIsRunAndEndsInRead() async throws {
        let log = Log()
        let m = model(log)
        try await run(m, log, sources: ["notes"], app: appOn)
        XCTAssertEqual(log.ran, [AppleNotesWatcher.channel])
        XCTAssertEqual(m.result("notes.notes")?.word, .read)
        XCTAssertEqual(m.result("notes.notes")?.at, now)
        XCTAssertTrue(log.asked.isEmpty, "nothing for the backend to say about a reader on this Mac")
        XCTAssertFalse(m.isChecking)
        XCTAssertTrue(m.checking.isEmpty)
    }

    func testAReaderThatFailsEndsInCouldntRead() async throws {
        let log = Log()
        log.runFails = [AppleNotesWatcher.channel]
        let m = model(log)
        try await run(m, log, sources: ["notes"], app: appOn)
        XCTAssertEqual(m.result("notes.notes")?.word, .couldntRead)
    }

    func testAMissingPermissionIsSaidWithoutRunningAnything() async throws {
        let log = Log()
        let m = model(log)
        let app = StreamAppState(readers: [AppleNotesWatcher.channel: false],
                                 waitingOn: [AppleNotesWatcher.channel: Copy.sourceNeedsAccess])
        try await run(m, log, sources: ["notes"], app: app)
        XCTAssertTrue(log.ran.isEmpty, "never a prompt, never a read macOS would refuse")
        XCTAssertEqual(m.result("notes.notes")?.word, .needsAccess)
    }

    func testAnAppRemovedFromThisMacEndsInNotInstalled() async throws {
        let log = Log()
        let m = model(log)
        try await run(m, log, sources: ["notes"], app: StreamAppState(notInstalled: [AppleNotesWatcher.channel]))
        XCTAssertEqual(m.result("notes.notes")?.word, .notInstalled)
        XCTAssertTrue(log.ran.isEmpty)
    }

    func testAStreamThatIsOffHasNoWord() async throws {
        let log = Log()
        let m = model(log)
        try await run(m, log, sources: ["notes"], app: StreamAppState(readers: [AppleNotesWatcher.channel: false]))
        XCTAssertNil(m.result("notes.notes"), "nothing is read from it, so it has no word to give")
        XCTAssertTrue(log.ran.isEmpty)
    }

    func testASavesYouMakeStreamIsAnsweredByTheFlagAndAccessibilityAlone() async throws {
        let log = Log()
        let m = model(log)
        try await run(m, log, sources: ["x"], app: StreamAppState(siteSavesOn: ["x"]))
        XCTAssertEqual(m.result("x.saves")?.word, .read)
        let log2 = Log()
        let m2 = model(log2)
        try await run(m2, log2, sources: ["x"], app: StreamAppState(siteSavesOn: ["x"], permissions: [.accessibility: false]))
        XCTAssertEqual(m2.result("x.saves")?.word, .needsAccess)
        XCTAssertTrue(log.ran.isEmpty && log2.ran.isEmpty)
    }

    func testTheBrowsersBookmarkReaderIsRunByItsChannel() async throws {
        let log = Log()
        let m = model(log)
        try await run(m, log, sources: ["browser:chrome"], app: appOn)
        XCTAssertEqual(log.ran, ["chrome-bookmarks"])
        XCTAssertEqual(m.result("browser:chrome.bookmarks")?.word, .read)
        XCTAssertNil(m.result("browser:chrome.tab_groups"), "off")
    }

    // MARK: The backend's part

    private func browserList(checked: Bool, health: StreamHealth? = .read, paused: Bool = false) -> SourceStreamsResponse {
        SourceStreamsResponse(sources: [SourceStreamsSource(id: "x", streams: [
            SourceStream(id: "x.bookmarks", label: "Bookmarks", kind: .saved, how: .browser, owner: .backend,
                         state: .on, health: health, lastReadAt: now.addingTimeInterval(-3600),
                         pausedUntil: paused ? now.addingTimeInterval(3600) : nil,
                         checkRequestedAt: checked ? now : nil, count: 5)])])
    }

    func testABrowserListIsAskedOfTheBackendAndSaysYourAIAppReadsItNextWithTheLastResult() async throws {
        let log = Log()
        log.backend = browserList(checked: true)
        let m = model(log)
        try await run(m, log, sources: ["x"], app: StreamAppState(), response: browserList(checked: false))
        XCTAssertEqual(log.asked, [["x"]])
        XCTAssertEqual(log.published, 1, "the answer reaches the streams cache")
        let r = try XCTUnwrap(m.result("x.bookmarks"))
        XCTAssertEqual(r.word, .yourAIAppReadsNext)
        XCTAssertEqual(r.previous, .read, "the last result beside it")
    }

    func testACheckNeverLiftsAPauseASignedOutListKeepsSayingSo() async throws {
        let log = Log()
        log.backend = browserList(checked: true, health: .signedOut, paused: true)
        let m = model(log)
        try await run(m, log, sources: ["x"], app: StreamAppState(), response: browserList(checked: false, health: .signedOut, paused: true))
        XCTAssertEqual(m.result("x.bookmarks")?.word, .signedOut)
    }

    func testAnAccountsRefusalIsSignedOutAndAnUnconfirmedOneIsCouldntRead() async throws {
        func account(_ health: StreamHealth?) -> SourceStreamsResponse {
            SourceStreamsResponse(sources: [SourceStreamsSource(id: "github", streams: [
                SourceStream(id: "github.stars", label: "Stars", kind: .code, how: .account, control: .setup,
                             state: .on, health: health, lastReadAt: now)])])
        }
        for (health, word) in [(StreamHealth.signedOut, StreamWord.signedOut), (.read, .read), (.couldntRead, .couldntRead),
                               (.notRead, .couldntRead)] {
            let log = Log()
            log.backend = account(health)
            let m = model(log)
            try await run(m, log, sources: ["github"], app: StreamAppState(), response: account(.read))
            XCTAssertEqual(m.result("github.stars")?.word, word, "\(String(describing: health))")
        }
    }

    func testOneBackendCallCoversEverySourceThatNeedsIt() async throws {
        let log = Log()
        log.backend = try SourceStreamsFixture.load()
        let m = model(log)
        try await run(m, log, app: appOn)   // empty: every source
        XCTAssertEqual(log.asked.count, 1)
        XCTAssertEqual(Set(log.asked[0]), ["github", "x", "youtube"],
                       "the sources with a browser or account stream that is on")
        XCTAssertEqual(m.result("youtube.watch_later")?.word, .signedOut, "the pause stands")
        XCTAssertEqual(m.result("github.stars")?.word, .read)
        XCTAssertNotNil(m.lastCheckedAt)
    }

    func testABackendThatCannotBeAskedSaysSoAndKeepsTheAppsOwnResults() async throws {
        let log = Log()
        log.backendThrows = true
        let m = model(log)
        try await run(m, log, app: appOn)
        XCTAssertEqual(m.failure, Copy.Streams.checkFailed)
        XCTAssertNil(m.result("github.stars"), "no word is invented for a stream that could not be asked")
        XCTAssertEqual(m.result("notes.notes")?.word, .read, "the app's own readers still ran")
        XCTAssertEqual(log.published, 0)
        XCTAssertTrue(m.checking.isEmpty)
    }

    func testACheckInFlightIsNotStartedTwiceAndAResetForgetsEverything() async throws {
        let log = Log()
        let m = model(log)
        try await run(m, log, sources: ["notes"], app: appOn)
        XCTAssertNotNil(m.result("notes.notes"))
        m.reset()
        XCTAssertNil(m.result("notes.notes"))
        XCTAssertNil(m.lastCheckedAt)
        XCTAssertNil(m.failure)
    }

    /// The backend's own `checked` result names the word where it is one of the six; anything else falls to the stream.
    func testTheBackendsCheckedResultNamesTheWord() throws {
        let response = try SourceStreamsFixture.load()
        let resolved = resolve(response, StreamAppState())
        let bookmarks = try XCTUnwrap(resolved.stream("x.bookmarks"))
        XCTAssertEqual(SourceStreamCheckModel.backendWord(bookmarks, checked: "requested"), .yourAIAppReadsNext)
        XCTAssertEqual(SourceStreamCheckModel.backendWord(bookmarks, checked: "signed_out"), .signedOut)
        XCTAssertEqual(SourceStreamCheckModel.backendWord(bookmarks, checked: "read"), .read)
        XCTAssertEqual(SourceStreamCheckModel.backendWord(bookmarks, checked: "failed"), .couldntRead)
        XCTAssertEqual(SourceStreamCheckModel.backendWord(bookmarks, checked: "paused"),
                       SourceStreamCheckModel.backendWord(bookmarks), "a pause is never lifted by a word of its own")
        XCTAssertEqual(SourceStreamCheckModel.backendWord(bookmarks, checked: "a word from a newer backend"),
                       SourceStreamCheckModel.backendWord(bookmarks))
    }
}
