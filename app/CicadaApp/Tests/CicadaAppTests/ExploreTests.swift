import XCTest
@testable import CicadaApp

/// G166 exploring — the app's half: the click starts a run and keeps the prompt to copy, the run card's progress line,
/// one tap stops it, the wire decodes leniently, the sync components that revalidate it, and Settings' signed-in switch
/// (D2 amended). A fake API; nothing reaches a backend, a browser or the person's clipboard.
@MainActor
final class ExploreTests: XCTestCase {
    final class FakeAPI: ExploreAPI, @unchecked Sendable {
        var state = ExploreState()
        var candidates = ExploreCandidates(eligible: 3, neverExplored: 2, agentEnabled: true, skillVerified: true)
        var started: [(ExploreScope, [String])] = []
        var stops = 0
        var startError: Error?

        func fetchExploreState(etag: String?) async throws -> Conditional<ExploreState> {
            Conditional(value: state, etag: "\"s\"", notModified: false)
        }
        func fetchExploreCandidates(etag: String?) async throws -> Conditional<ExploreCandidates> {
            Conditional(value: candidates, etag: "\"c\"", notModified: false)
        }
        func startExplore(scope: ExploreScope, origins: [String]) async throws -> ExploreStartResponse {
            if let startError { throw startError }
            started.append((scope, origins))
            state = ExploreState(batch: ExploreBatch(total: 2, waiting: 2))
            return ExploreStartResponse(batch: ExploreStartedBatch(id: "x_abcdef", total: 2), prompt: "Explore 2 of my saved sites…")
        }
        func stopExplore() async throws -> ExploreStopResponse {
            stops += 1
            state = ExploreState(batch: ExploreBatch(stoppedAt: "2026-10-14T12:00:00Z", total: 2, done: 0))
            return ExploreStopResponse(stopped: true, dropped: 2, finishing: 0)
        }
        func fetchExplorePrompt() async throws -> ExplorePromptResponse { ExplorePromptResponse(prompt: "again") }
        var looks: [(String, String)] = []
        var lookError: Error?
        func saveLook(mediaEntityId: String, url: String) async throws -> ExploreLookResponse {
            if let lookError { throw lookError }
            looks.append((mediaEntityId, url))
            return ExploreLookResponse(key: "abc123def456", mediaEntityId: mediaEntityId, joined: false,
                                       prompt: "Explore 1 of my saved sites…")
        }
    }

    func testTheClickStartsARunAndKeepsThePromptToCopy() async {
        let api = FakeAPI()
        let cache = ExploreCache(api: api)
        await cache.refreshCandidates()
        XCTAssertNil(cache.blockedReason(scope: .neverExplored))
        let ok = await cache.start(scope: .neverExplored, origins: ["chrome-bookmark"])
        XCTAssertTrue(ok)
        XCTAssertEqual(api.started.first?.0, .neverExplored)
        XCTAssertEqual(api.started.first?.1, ["chrome-bookmark"])
        XCTAssertEqual(cache.prompt, "Explore 2 of my saved sites…")
        XCTAssertTrue(cache.showsCard)
        XCTAssertTrue(cache.batch?.isRunning ?? false)
    }

    func testTheButtonSaysWhyItCannotStart() async {
        let api = FakeAPI()
        api.candidates.agentEnabled = false
        let cache = ExploreCache(api: api)
        await cache.refreshCandidates()
        XCTAssertEqual(cache.blockedReason(scope: .all), Copy.Explore.startHelpOff)
        api.candidates = ExploreCandidates(eligible: 3, neverExplored: 0, agentEnabled: true, skillVerified: true)
        await cache.refreshCandidates()
        XCTAssertEqual(cache.blockedReason(scope: .neverExplored), Copy.Explore.startHelpNone)
        XCTAssertNil(cache.blockedReason(scope: .all))
        api.candidates.demo = true
        await cache.refreshCandidates()
        XCTAssertEqual(cache.blockedReason(scope: .all), Copy.Explore.startHelpDemo)
    }

    func testARefusedStartShowsTheServersSentence() async {
        let api = FakeAPI()
        api.startError = APIError.httpError(409, #"{"detail":"Turn on reading first."}"#)
        let cache = ExploreCache(api: api)
        let ok = await cache.start(scope: .all)
        XCTAssertFalse(ok)
        XCTAssertNotNil(cache.note)
        XCTAssertNil(cache.prompt)
    }

    func testOneTapStopsTheRun() async {
        let api = FakeAPI()
        let cache = ExploreCache(api: api)
        await cache.start(scope: .all)
        await cache.stop()
        XCTAssertEqual(api.stops, 1)
        XCTAssertFalse(cache.batch?.isRunning ?? true)
        XCTAssertTrue(Copy.Explore.progress(cache.batch!).hasPrefix("Stopped at 0 of 2"))
    }

    func testTheProgressLineCountsAgentsWallsAndTime() {
        let running = ExploreBatch(total: 534, done: 212, waiting: 300, claimed: 4, agents: 4, needsLogin: 3, gone: 2,
                                   etaMinutes: 40)
        XCTAssertEqual(Copy.Explore.progress(running),
                       "Exploring 212 of 534 · 4 agents working · 3 need your sign-in · 2 gone · about 40 min left")
        let waiting = ExploreBatch(total: 5, waiting: 5)
        XCTAssertEqual(Copy.Explore.progress(waiting), "Exploring 0 of 5 · waiting for an agent")
        let done = ExploreBatch(total: 5, done: 5)
        XCTAssertEqual(Copy.Explore.progress(done), "Explored 5 of 5")
        XCTAssertNil(Copy.Explore.startedBy(ExploreStarter()))
        XCTAssertEqual(Copy.Explore.startedBy(ExploreStarter(kind: "agent", harness: "claude-code")),
                       "Started by Claude Code at your request")
    }

    func testTheWireDecodesLenientlyAndAnOlderBackendIsGone() async throws {
        let json = #"{"batch": {"id": "x_1", "startedBy": {"kind": "agent", "harness": "codex"}, "total": 3, "done": 1,"#
            + #" "waiting": 1, "claimed": 1, "agents": 1, "etaMinutes": null, "surprise": true},"#
            + #" "items": [{"key": null, "mediaEntityId": "media-a", "url": "https://a.bob-example.org/", "state": "explored","#
            + #" "latest": {"id": "20261014T140200Z-aaaaaa", "capturedAt": "2026-10-14T14:02:00Z", "outcome": "captured","#
            + #" "signedIn": true, "thumbUrl": "/explore/captures/media-a/20261014T140200Z-aaaaaa/thumb"}}]}"#
        let state = try JSONDecoder().decode(ExploreState.self, from: Data(json.utf8))
        XCTAssertEqual(state.batch?.startedBy.harness, "codex")
        XCTAssertNil(state.batch?.etaMinutes)
        XCTAssertEqual(state.items.first?.latest?.signedIn, true)
        XCTAssertEqual(try JSONDecoder().decode(ExploreCandidates.self, from: Data("{}".utf8)).exploreSignedIn, true)

        final class Gone: ExploreAPI, @unchecked Sendable {
            func fetchExploreState(etag: String?) async throws -> Conditional<ExploreState> { throw APIError.httpError(404, "") }
            func fetchExploreCandidates(etag: String?) async throws -> Conditional<ExploreCandidates> { throw APIError.httpError(404, "") }
            func startExplore(scope: ExploreScope, origins: [String]) async throws -> ExploreStartResponse { throw APIError.httpError(404, "") }
            func stopExplore() async throws -> ExploreStopResponse { throw APIError.httpError(404, "") }
            func fetchExplorePrompt() async throws -> ExplorePromptResponse { throw APIError.httpError(404, "") }
            func saveLook(mediaEntityId: String, url: String) async throws -> ExploreLookResponse {
                throw APIError.httpError(404, "")
            }
        }
        let cache = ExploreCache(api: Gone())
        await cache.refresh()
        XCTAssertTrue(cache.isGone, "an older backend has no explore routes: the button disappears")
    }

    func testTheRunRevalidatesOnTheQueueAndCaptureComponentsOnly() {
        func vector(_ c: [String: String]) -> VersionVector { VersionVector(version: "v", components: c) }
        let base = ["exploreQueue": "1", "captures": "1", "sources": "1", "reading": "1", "bank": "b", "graph": "1"]
        XCTAssertFalse(ExploreRefresh.shouldRevalidate(old: vector(base), new: vector(base.merging(["graph": "2"]) { $1 })))
        XCTAssertTrue(ExploreRefresh.shouldRevalidate(old: vector(base), new: vector(base.merging(["exploreQueue": "2"]) { $1 })))
        XCTAssertTrue(ExploreRefresh.shouldRevalidate(old: vector(base), new: vector(base.merging(["captures": "2"]) { $1 })))
    }

    func testABankSwitchForgetsTheRun() async {
        let cache = ExploreCache(api: FakeAPI())
        await cache.start(scope: .all)
        cache.reset()
        XCTAssertNil(cache.batch)
        XCTAssertNil(cache.prompt)
        XCTAssertFalse(cache.showsCard)
    }

    // MARK: Settings → Reading the web: the signed-in switch

    func testTheSignedInSwitchDefaultsOnAndWritesOnlyItself() async {
        var sent: [Bool] = []
        var deps = ReadingAgentModel.Deps.live
        deps.fetch = { ReadingSettingsResponse(agentEnabled: true, ackCurrent: true) }
        deps.writeExplore = { on in
            sent.append(on)
            return ReadingSettingsResponse(agentEnabled: true, ackCurrent: true, exploreSignedIn: on)
        }
        let model = ReadingAgentModel(deps: deps)
        await model.load()
        XCTAssertTrue(model.exploreSignedIn, "the person's signed-in session is the default (D2 amended)")
        let ok = await model.setExploreSignedIn(false)
        XCTAssertTrue(ok)
        XCTAssertEqual(sent, [false])
        XCTAssertFalse(model.exploreSignedIn)
        XCTAssertTrue(model.enabled, "turning signed-in exploring off leaves reading on")
    }

    func testNeverExploreSendsTheSiteNameAndLiftsIt() async {
        var sent: [[String: Bool]] = []
        var deps = ReadingAgentModel.Deps.live
        deps.fetch = { ReadingSettingsResponse(agentEnabled: true, ackCurrent: true) }
        deps.writeNever = { patch in
            sent.append(patch)
            let on = patch.filter(\.value).keys
            return ReadingSettingsResponse(agentEnabled: true, ackCurrent: true,
                                           neverExplore: Dictionary(uniqueKeysWithValues: on.map { ($0, "2026-10-14") }))
        }
        let model = ReadingAgentModel(deps: deps)
        await model.load()
        let added = await model.setNeverExplore("https://www.Bob-Example.org/pricing", true)
        XCTAssertTrue(added)
        XCTAssertEqual(sent.first, ["bob-example.org": true])
        XCTAssertEqual(model.neverExplore, ["bob-example.org"])
        await model.setNeverExplore("bob-example.org", false)
        XCTAssertEqual(sent.last, ["bob-example.org": false])
        XCTAssertEqual(model.neverExplore, [])
        let empty = await model.setNeverExplore("   ", true)
        XCTAssertFalse(empty)
        XCTAssertEqual(sent.count, 2, "an empty name sends nothing")
    }

    func testTheSettingsDecodeTheExploreFieldsAndTheSheetSaysSo() throws {
        let body = #"{"agentEnabled": true, "allowedSites": {}, "ackCurrent": true, "exploreSignedIn": false,"#
            + #" "neverExplore": {"bob-example.org": "2026-10-14"}}"#
        let settings = try JSONDecoder().decode(ReadingSettingsResponse.self, from: Data(body.utf8))
        XCTAssertFalse(settings.exploreSignedIn)
        XCTAssertEqual(settings.neverExplore, ["bob-example.org": "2026-10-14"])
        XCTAssertTrue(Copy.Reading.sheetExploring.contains("signed-in session"))
        XCTAssertTrue(Copy.Reading.sheetExploring.contains("your account"))
        // D6: the explore switches left Settings with Reading the web; their anchors land on the Sources page.
        XCTAssertEqual(SettingsIndex.retiredRows[.readingExploreSignedIn], .readingInBrowser)
        XCTAssertEqual(SettingsIndex.retiredRows[.readingNeverExplore], .readingInBrowser)
    }
}
