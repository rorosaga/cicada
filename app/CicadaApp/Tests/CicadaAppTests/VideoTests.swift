import XCTest
@testable import CicadaApp

// G162 — the app half of the watch run: the wire, the shared rules, the cache, the words, the button table, the run's
// model and progress, the copy's neutrality and the Sleep row.

// MARK: - The wire (P13: the server derives; the app decodes and labels)

final class VideoStateDecodeTests: XCTestCase {
    func testTheDemoWireDecodesWithItsThreeStates() throws {
        let demo = try VideoFixtures.demo()
        XCTAssertEqual(demo.state.items.map(\.state), [.transcript, .watchedAndTranscript, .none])
        XCTAssertEqual(demo.state.items[0].engine, .captions)
        XCTAssertEqual(demo.state.items[0].fidelity, .verbatim)
        XCTAssertEqual(demo.state.items[0].readBySleep, true)
        XCTAssertEqual(demo.state.queue, demo.summary.withoutShape, "one function feeds both blocks (N-6)")
        XCTAssertEqual(demo.summary.total, 3)
    }

    func testBothBoardMomentsDecodeAndTheirTabsAddUp() throws {
        for (name, tabs) in [("A", [13, 3, 7]), ("B", [8, 6, 9])] {
            let m = try VideoFixtures.moment(name)
            XCTAssertEqual(m.state.items.count, 23)
            XCTAssertEqual([m.summary.unread, m.summary.inQueue, m.summary.read], tabs, "moment \(name)")
            XCTAssertEqual(tabs.reduce(0, +), m.summary.total)
        }
        let b = try VideoFixtures.moment("B")
        XCTAssertEqual(b.summary.batch?.total, 5)
        XCTAssertEqual(b.summary.batch?.done, 2)
        XCTAssertTrue(b.state.items.contains { $0.failedCode != nil })
    }

    func testEveryStateTheSharedFixtureNamesIsKnown() throws {
        struct Case: Decodable { let state: String }
        struct File: Decodable { let cases: [Case] }
        let file = try JSONDecoder().decode(File.self, from: Data(contentsOf: VideoFixtures.apiFixtures
            .appendingPathComponent("video_state.json")))
        XCTAssertGreaterThanOrEqual(file.cases.count, 5, "a test over no cases passes vacuously")
        for c in file.cases {
            XCTAssertNotEqual(VideoWatchState(wire: c.state), .unknown, c.state)
            XCTAssertNotNil(VideoWords.stateTag(VideoWatchState(wire: c.state)))
        }
    }

    func testAnUnknownValueNeverDropsTheRow() throws {
        let json = #"""
        {"items": [
          {"key": "k1", "mediaEntityId": "m", "url": "u", "state": "hologram", "queueState": "floating",
           "failedCode": "moon", "engine": "gemini_url", "fidelity": "maybe"},
          {"url": "no key"},
          {"key": "k2", "mediaEntityId": "m2", "url": "u2", "state": "none"}
        ], "queue": {"total": 2, "unread": 1}, "nextChangeAt": "2026-09-29T15:00:00Z"}
        """#
        let decoded = try JSONDecoder().decode(VideosStateResponse.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.items.map(\.key), ["k1", "k2"], "a row with no key drops alone")
        XCTAssertEqual(decoded.items[0].state, .unknown)
        XCTAssertNil(decoded.items[0].queueState)
        XCTAssertNil(decoded.items[0].failedCode)
        XCTAssertNil(decoded.items[0].engine, "the retired engine name is not a value")
        XCTAssertNil(VideoWords.stateTag(.unknown))
        XCTAssertEqual(decoded.queue.nextChangeAt, "2026-09-29T15:00:00Z", "the top-level instant reaches the counts")
    }

    func testTheWatchBlockAndMediaTurnsDecode() throws {
        let json = #"""
        {"episode": "ep_2026-09-28_003", "text": "video [4:05]: hello", "turns": [
          {"index": 0, "start": 0, "contentStart": 14, "end": 19, "role": "media", "t": 245, "fidelity": "approximate"}],
         "watch": {"basis": "frames", "engine": "video_link", "fidelity": "approximate", "authorModel": "claude-opus-5-5",
                   "authorEffort": "high"}}
        """#
        let doc = try JSONDecoder().decode(EpisodeText.self, from: Data(json.utf8))
        XCTAssertEqual(doc.watch?.basis, .frames)
        XCTAssertEqual(doc.watch?.engine, .videoLink)
        XCTAssertEqual(doc.watch?.authorModel, "claude-opus-5-5")
        XCTAssertEqual(doc.turns.first?.t, 245)
        XCTAssertEqual(doc.turns.first?.fidelity, .approximate)
        let older = try JSONDecoder().decode(EpisodeText.self, from: Data(#"{"episode": "e", "text": ""}"#.utf8))
        XCTAssertNil(older.watch)
    }
}

private extension VideoSummary {
    var withoutShape: VideoSummary { self }
}

// MARK: - One rule for "a video" (P10)

final class VideoKindTests: XCTestCase {
    func testFeedKindAgreesWithTheSharedFixture() throws {
        struct Case: Decodable { let mediaType: String; let url: String; let kind: String?; let video: Bool }
        struct File: Decodable { let cases: [Case] }
        let file = try JSONDecoder().decode(File.self, from: Data(contentsOf: VideoFixtures.apiFixtures
            .appendingPathComponent("video_kind.json")))
        XCTAssertGreaterThanOrEqual(file.cases.count, 8)
        for c in file.cases {
            var object: [String: Any] = ["mediaEntityId": "m", "url": c.url, "title": "T", "mediaType": c.mediaType,
                                         "savedAt": "2026-09-13T10:00:00Z", "tags": []]
            if let kind = c.kind { object["kind"] = kind }
            let item = try JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: object))
            XCTAssertEqual(FeedKind.of(item) == .video, c.video, "\(c.mediaType) \(c.url) \(c.kind ?? "")")
        }
    }
}

// MARK: - The cache

@MainActor
final class VideoStateCacheTests: XCTestCase {
    private func state(_ items: [VideoStateItem], next: String? = nil) -> VideosStateResponse {
        VideosStateResponse(items: items, queue: VideoSummary.count(items: items, batch: nil, nextChangeAt: next),
                            nextChangeAt: next)
    }

    private let item = VideoStateItem(key: "k1", mediaEntityId: "media-a", url: "https://example.com/a.mp4")

    func testRevalidatesWithItsETagAndA304KeepsTheValue() async {
        let api = FakeVideosAPI()
        api.stateReplies = [FakeVideosAPI.fresh(state([item]), "e1"), FakeVideosAPI.notModified("e1")]
        let cache = VideoStateCache(api: api, sleeper: { _ in throw CancellationError() })
        await cache.refresh()
        await cache.refresh()
        XCTAssertEqual(api.stateETags, [nil, "e1"], "never an ETag with nothing cached")
        XCTAssertEqual(cache.items.map(\.key), ["k1"])
        XCTAssertEqual(cache.phase, .loaded)
    }

    func testAFailureKeepsTheLastValue() async {
        let api = FakeVideosAPI()
        api.stateReplies = [FakeVideosAPI.fresh(state([item]), "e1"), .failure(APIError.serverUnreachable)]
        let cache = VideoStateCache(api: api, sleeper: { _ in throw CancellationError() })
        await cache.refresh()
        await cache.refresh()
        XCTAssertEqual(cache.items.count, 1, "never blank (DR-43)")
    }

    func testA404HidesEveryVideoAddition() async {
        let api = FakeVideosAPI()
        api.stateReplies = [.failure(APIError.httpError(404, "{}"))]
        let cache = VideoStateCache(api: api)
        await cache.refresh()
        XCTAssertTrue(cache.isGone)
        XCTAssertNil(cache.summary)
        XCTAssertNil(VideosStripText.line(cache.summary))
    }

    func testResetForgetsEverything() async {
        let api = FakeVideosAPI()
        api.stateReplies = [FakeVideosAPI.fresh(state([item]), "e1"), FakeVideosAPI.fresh(state([]), "e2")]
        let cache = VideoStateCache(api: api, sleeper: { _ in throw CancellationError() })
        await cache.refresh()
        cache.reset()
        XCTAssertTrue(cache.items.isEmpty)
        XCTAssertFalse(cache.hasRead)
        await cache.refresh()
        XCTAssertEqual(api.stateETags.last ?? "x", nil, "a reset cache asks without an ETag")
    }

    func testAQueueTapPaintsAtOnceAndRollsBackWithTheServersSentence() async {
        let api = FakeVideosAPI()
        api.stateReplies = [FakeVideosAPI.fresh(state([item]), "e1")]
        api.putError = APIError.httpError(422, #"{"detail": "The video queue is full (2,000 videos)."}"#)
        let cache = VideoStateCache(api: api, sleeper: { _ in throw CancellationError() })
        await cache.refresh()
        let sentence = await cache.queue(key: "k1", want: .watch)
        XCTAssertEqual(sentence, "The video queue is full (2,000 videos).")
        XCTAssertNil(cache.item(key: "k1")?.queueState, "rolled back")
    }

    func testRevalidatesAtNextChangeWithoutAnETag() async {
        // H2 — a lease lapsing writes nothing; the cache asks again at `nextChangeAt`, never with the stale ETag.
        let api = FakeVideosAPI()
        var claimed = item
        claimed.queueState = .claimed
        claimed.claimedBy = "acme-agent"
        var lapsed = item
        lapsed.queueState = .queued
        api.stateReplies = [FakeVideosAPI.fresh(state([claimed], next: "2026-09-29T15:00:00Z"), "e1"),
                            FakeVideosAPI.fresh(state([lapsed]), "e2")]
        let fired = expectation(description: "slept until the lease")
        let now = VideoStateCache.parse("2026-09-29T14:15:00Z")!
        var waited: TimeInterval = 0
        let cache = VideoStateCache(api: api, now: { now }, sleeper: { seconds in
            waited = seconds
            fired.fulfill()
        })
        await cache.refresh()
        await fulfillment(of: [fired], timeout: 2)
        for _ in 0..<50 where cache.item(key: "k1")?.queueState != .queued { await Task.yield() }
        XCTAssertEqual(waited, 45 * 60, accuracy: 1)
        XCTAssertEqual(api.stateETags, [nil, nil], "the wake asks for the body, not a 304 of the old one")
        let rows = VideoRunModel.rows(items: [VideoFixtures.feedItem(id: "media-a", url: "https://example.com/a.mp4")],
                                      states: cache.items)
        XCTAssertEqual(VideoRunProgress.status(of: rows[0].state), .waiting, "a lapsed lease reads Waiting, never Picked up")
    }

    func testABankSwitchCancelsTheTimer() async {
        let api = FakeVideosAPI()
        api.stateReplies = [FakeVideosAPI.fresh(state([item], next: "2026-09-29T15:00:00Z"), "e1")]
        let cache = VideoStateCache(api: api, sleeper: { _ in try await Task.sleep(nanoseconds: 50_000_000) })
        await cache.refresh()
        cache.reset()
        try? await Task.sleep(nanoseconds: 150_000_000)
        XCTAssertEqual(api.stateETags.count, 1, "the timer died with the bank")
    }
}

final class VideoRefreshTests: XCTestCase {
    private func v(_ c: [String: String]) -> VersionVector { VersionVector(version: c.values.sorted().joined(), components: c) }

    func testTheComponentsItFollows() {
        XCTAssertEqual(Set(VideoRefresh.components), ["videoQueue", "episodes", "entities", "sources", "bank"])
        XCTAssertNil(VersionVector.mapping["videoQueue"], "not a Store domain (like backlog)")
    }

    func testAQueueOnlyChangeRevalidatesAndASleepTickDoesNot() {
        let old = v(["videoQueue": "1:0", "episodes": "a", "sleep": "s1"])
        XCTAssertTrue(VideoRefresh.shouldRevalidate(old: old, new: v(["videoQueue": "1:1", "episodes": "a", "sleep": "s1"])))
        XCTAssertFalse(VideoRefresh.shouldRevalidate(old: old, new: v(["videoQueue": "1:0", "episodes": "a", "sleep": "s2"])))
    }

    func testAnUnmappedComponentStillDecodes() throws {
        let json = #"{"version": "abc", "components": {"videoQueue": "12.5:1", "entities": "e"}}"#
        let vector = try JSONDecoder().decode(VersionVector.self, from: Data(json.utf8))
        XCTAssertEqual(vector.components["videoQueue"], "12.5:1")
    }
}

// MARK: - Words

final class VideoWordsTests: XCTestCase {
    private let us = Locale(identifier: "en_US"), utc = TimeZone(identifier: "UTC")!

    func testTheRowWordTableAndTheQueueWordWins() {
        func s(_ state: VideoWatchState, _ queue: VideoQueueState? = nil) -> VideoStateItem {
            VideoStateItem(key: "k", mediaEntityId: "m", url: "u", state: state, queueState: queue)
        }
        XCTAssertNil(VideoWords.rowWord(s(.none)))
        XCTAssertEqual(VideoWords.rowWord(s(.transcript)), "Transcript")
        XCTAssertEqual(VideoWords.rowWord(s(.watched)), "Watched")
        XCTAssertEqual(VideoWords.rowWord(s(.watchedAndTranscript)), "Both")
        XCTAssertEqual(VideoWords.rowWord(s(.recorded)), "Recorded")
        XCTAssertEqual(VideoWords.rowWord(s(.transcript, .queued)), "Queued")
        XCTAssertEqual(VideoWords.rowWord(s(.none, .claimed)), "Picked up")
        XCTAssertEqual(VideoWords.rowWord(s(.none, .failed)), "Couldn't do")
        XCTAssertEqual(VideoWords.trailing(state: s(.transcript), age: "3h"), "Transcript · 3h")
        XCTAssertEqual(VideoWords.trailing(state: s(.none), age: "2w"), "2w")
    }

    func testTheDetailLineHasNoVideoPrefix() {
        let item = VideoFixtures.feedItem(durationS: 494)
        XCTAssertEqual(VideoWords.detailLine(item, locale: us, timeZone: utc), "bob-example · youtube.com · 8:14 · saved Sep 13")
        XCTAssertEqual(FeedRowText.detail(item, locale: us, timeZone: utc), VideoWords.detailLine(item, locale: us, timeZone: utc))
        XCTAssertEqual(VideoWords.headerLine(item), "Video · youtube.com · 8:14")
        XCTAssertEqual(VideoWords.pickerLine(VideoFixtures.feedItem(channel: "Northwind Robotics")),
                       "Northwind Robotics · length unknown")
        let vimeo = VideoFixtures.feedItem(url: "https://vimeo.com/123456789", channel: "Leo", durationS: 588)
        XCTAssertEqual(VideoWords.pickerLine(vimeo), "Leo · Vimeo · 9:48", "a provider with no bundled mark is named (P12)")
    }

    func testTheOneQueueWordingOmitsZeroClauses() {
        XCTAssertEqual(VideoQueueLine.text(VideoSummary(total: 23, unread: 8, queued: 4, claimed: 1, failed: 1, read: 9)),
                       "4 queued · 1 picked up by an agent · 1 couldn't be done")
        XCTAssertEqual(VideoQueueLine.text(VideoSummary(queued: 3)), "3 queued")
        XCTAssertEqual(VideoQueueLine.text(VideoSummary(claimed: 2)), "2 picked up by agents")
        XCTAssertNil(VideoQueueLine.text(VideoSummary(total: 4, unread: 4)))
        XCTAssertEqual(VideosStripText.line(VideoSummary(total: 23, unread: 8, queued: 4, claimed: 1, failed: 1, read: 9)),
                       "8 not read yet · 4 queued · 1 picked up by an agent · 1 couldn't be done")
    }

    func testHonestyLines() {
        var s = VideoStateItem(key: "k", mediaEntityId: "m", url: "u", state: .watched, fidelity: .approximate, readBySleep: false)
        XCTAssertEqual(VideoWords.sleepLine(s), "Sleep hasn't read this yet. Wording is approximate (a model's reading, not captions).")
        XCTAssertEqual(VideoWords.caveatLine(s), "An agent recorded that it watched this. Cicada saw no frames itself.")
        s.state = .transcript
        s.readBySleep = nil
        s.fidelity = .verbatim
        XCTAssertNil(VideoWords.sleepLine(s), "an agent flipped the flag: the line says nothing")
        XCTAssertNil(VideoWords.caveatLine(s))
        s.state = .recorded
        XCTAssertEqual(VideoWords.caveatLine(s), "Recorded before Cicada asked how it was read.")
        for line in VideoWords.honestyLines(s) { XCTAssertFalse(line.lowercased().contains("in your graph")) }
    }

    func testAttributionIsBuiltFromData() {
        let line = VideoWords.attribution(recordedBy: "acme-agent", recordedAt: "2026-09-28T14:31:07Z", model: nil,
                                          effort: nil, locale: us, timeZone: utc)
        XCTAssertEqual(line, "Acme-Agent · model not shared by this app · Sep 28")
        let captured = VideoWords.attribution(recordedBy: "claude-code", recordedAt: "2026-09-28T14:31:07Z",
                                              model: "claude-sonnet-5-5", effort: nil, locale: us, timeZone: utc)
        XCTAssertEqual(captured?.hasSuffix("· Sep 28"), true)
        XCTAssertEqual(VideoWords.recordedTime("2026-09-29T14:40:00Z", locale: us, timeZone: utc)?
            .replacingOccurrences(of: "\u{202F}", with: " "), "2:40 PM", "the system writes a narrow space before PM")
    }

    func testTheFirstQuoteOfARecord() {
        let text = "Summary line.\nvideo [3:12]: A stored embedding costs one lookup, not one model call."
        let scalars = text.unicodeScalars.count
        let start = text.unicodeScalars.count - "A stored embedding costs one lookup, not one model call.".unicodeScalars.count
        let doc = EpisodeText(episode: "e", text: text, turns: [
            EpisodeTurn(index: 0, start: 0, contentStart: 0, end: 13, role: "page"),
            EpisodeTurn(index: 1, start: 14, contentStart: start, end: scalars, role: "media", t: 192),
        ])
        let quote = VideoQuote.first(doc)
        XCTAssertEqual(quote?.text, "\u{201C}A stored embedding costs one lookup, not one model call.\u{201D}")
        XCTAssertEqual(quote?.time, "3:12")
        XCTAssertNil(VideoQuote.first(EpisodeText(episode: "e", text: "no quotes")))
    }
}

// MARK: - The button table

final class VideoActionsTests: XCTestCase {
    private func s(_ state: VideoWatchState, _ queue: VideoQueueState? = nil, want: VideoWant? = nil,
                   code: VideoFailCode? = nil) -> VideoStateItem {
        VideoStateItem(key: "k", mediaEntityId: "m", url: "u", state: state, want: want, queueState: queue, failedCode: code)
    }

    func testEachStateGetsItsButtons() {
        let none = VideoActions.for(s(.none))
        XCTAssertTrue(none.queueTranscript.isShown && none.queueWatch.isShown)
        let transcript = VideoActions.for(s(.transcript))
        XCTAssertFalse(transcript.queueTranscript.isShown)
        XCTAssertTrue(transcript.queueWatch.isShown)
        XCTAssertEqual(VideoActions.for(s(.watched)).queueTranscript, .enabled(help: "Queue a transcript for exact wording"))
        let both = VideoActions.for(s(.watchedAndTranscript))
        XCTAssertFalse(both.queueTranscript.isShown || both.queueWatch.isShown)
        let recorded = VideoActions.for(s(.recorded))
        XCTAssertTrue(recorded.queueTranscript.isShown && recorded.queueWatch.isShown)
    }

    func testQueueStates() {
        let watch = VideoActions.for(s(.none, .queued, want: .watch))
        XCTAssertEqual(watch.status, .queued(.watch))
        XCTAssertEqual(watch.queueTranscript, .disabled(help: "Watching includes the transcript"))
        XCTAssertTrue(watch.showsRemove)
        let read = VideoActions.for(s(.none, .queued, want: .transcript))
        XCTAssertTrue(read.queueWatch.isShown)
        let claimed = VideoActions.for(VideoStateItem(key: "k", mediaEntityId: "m", url: "u", want: .watch,
                                                      queueState: .claimed, claimedBy: "acme-agent"))
        XCTAssertEqual(claimed.status, .pickedUp(by: "acme-agent", .watch))
        let failed = VideoActions.for(s(.none, .failed, code: .noCaptions))
        XCTAssertTrue(failed.showsTryAgain && failed.showsRemove)
        XCTAssertFalse(failed.showsOpenInBrowser)
    }

    func testNeedsLoginByPermission() {
        let unknown = VideoActions.for(s(.none, .failed, code: .needsLogin))
        XCTAssertTrue(unknown.showsOpenInBrowser && unknown.showsBrowserLine)
        XCTAssertFalse(unknown.showsAllowBrowser, "no button until this build can read the one permission")
        XCTAssertTrue(VideoActions.for(s(.none, .failed, code: .needsLogin), permission: .off).showsAllowBrowser)
        let on = VideoActions.for(s(.none, .failed, code: .needsLogin), permission: .on)
        XCTAssertFalse(on.showsAllowBrowser)
        XCTAssertEqual(on.browserLine, .on)
        XCTAssertEqual(VideoWords.failedReason(s(.none, .failed, code: .needsLogin)), "it needs you to sign in")
    }
}

// MARK: - The run

@MainActor
final class VideoRunModelTests: XCTestCase {
    func testTabsAreDisjointAndSumToTheTotalAtBothMoments() throws {
        for (name, expected) in [("A", [13, 3, 7]), ("B", [8, 6, 9])] {
            let m = try VideoFixtures.moment(name)
            let rows = VideoFixtures.rows(m)
            XCTAssertEqual(rows.count, 23, "every board video joins its Feed row")
            let counts = VideoRunModel.counts(rows)
            XCTAssertEqual([counts[.unread] ?? 0, counts[.queued] ?? 0, counts[.read] ?? 0], expected, "moment \(name)")
            XCTAssertEqual(counts[.unread], m.summary.unread)
            XCTAssertEqual(counts[.queued], m.summary.inQueue)
        }
    }

    func testNothingIsPreselectedAndAPickStartsAsATranscript() throws {
        let rows = VideoFixtures.rows(try VideoFixtures.moment("A"))
        let model = VideoRunModel()
        model.begin(summary: nil)
        XCTAssertEqual(model.mode, .choosing)
        XCTAssertTrue(model.selected.isEmpty)
        let first = VideoRunModel.rows(rows, in: .unread)[0]
        model.toggle(first)
        XCTAssertEqual(model.want(for: first), .transcript)
        model.set(first, want: .watch)
        XCTAssertEqual(model.want(for: first), .watch, "a menu change is client state; nothing is written")
        model.clearSelection()
        model.selectAllUnread(rows)
        XCTAssertEqual(model.selected.count, 13)
        XCTAssertEqual(Copy.Videos.selectAllUnread(13), "Select all 13 not read yet")
    }

    func testSizeWordsAndKnownMinutesOnly() {
        let picks: [(want: VideoWant, seconds: Int?)] = [(.transcript, nil), (.transcript, nil), (.transcript, 600),
                                                          (.watch, 588), (.watch, nil)]
        let size = VideoSizeSummary.of(picks)
        XCTAssertEqual(size.line, "3 light · 1 medium · 1 heavy (length unknown)")
        XCTAssertEqual(size.minutesLine, "10 min to watch, plus 1 of unknown length")
        for text in [size.line, size.minutesLine ?? ""] {
            XCTAssertFalse(text.contains("$"))
            XCTAssertFalse(text.lowercased().contains("token"))
        }
        XCTAssertEqual(VideoSize.of(want: .watch, seconds: 45 * 60), .heavy)
        XCTAssertEqual(VideoSize.of(want: .transcript, seconds: 4 * 3600), .heavy)
    }

    func testCopyForAnAgentHandsOffEveryPickAndOpensTheProgress() async throws {
        let rows = VideoFixtures.rows(try VideoFixtures.moment("A"))
        let api = FakeVideosAPI()
        let cache = VideoStateCache(api: api, sleeper: { _ in throw CancellationError() })
        let model = VideoRunModel()
        model.begin(summary: nil)
        model.selectAllUnread(rows)
        var copied: String?
        let sentence = await model.copyForAgent(rows: rows, cache: cache) { copied = $0 }
        XCTAssertNil(sentence)
        XCTAssertEqual(api.handoffs.first?.count, 13, "no cap (R-VU12)")
        XCTAssertEqual(copied, "Cicada has 13 videos waiting for you to read or watch.")
        XCTAssertEqual(model.mode, .progress)
        XCTAssertTrue(model.selected.isEmpty)
    }

    func testTheProgressAtMomentB() throws {
        let m = try VideoFixtures.moment("B")
        let batch = try XCTUnwrap(m.summary.batch)
        let members = VideoRunProgress.members(batch: batch, rows: VideoFixtures.rows(m))
        XCTAssertEqual(members.count, 5)
        XCTAssertEqual(members.filter { $0.status == .recorded }.count, batch.done,
                       "the numerator is batch.done and never moves on picked up")
        XCTAssertEqual(VideoRunProgress.meter(batch), .segments(count: 5, filled: 2))
        XCTAssertEqual(VideoRunProgress.meterLine(batch), "1 picked up by an agent · 1 waiting · 1 couldn't be done")
        let model = VideoRunModel()
        model.begin(summary: m.summary)
        XCTAssertEqual(model.mode, .progress, "an unfinished hand-off reopens its progress (G-1)")
        XCTAssertEqual(model.eyebrow(summary: m.summary), "Feed · Videos · Watch run · 2 of 5 recorded")
    }

    func testAboveTenTheMeterIsOneBarAndTheRowsAreGrouped() {
        let batch = VideoBatch(id: "b", total: 13, done: 5)
        XCTAssertEqual(VideoRunProgress.meter(batch), .continuous(fraction: 5.0 / 13.0))
        func member(_ status: VideoMemberStatus, _ n: Int) -> VideoRunMember {
            let item = VideoFixtures.feedItem(id: "m\(n)")
            return VideoRunMember(row: VideoRow(item: item, state: VideoStateItem(key: "k\(n)", mediaEntityId: "m\(n)",
                                                                                 url: item.url)), status: status)
        }
        let members = [member(.recorded, 1), member(.waiting, 2), member(.failed, 3), member(.pickedUp, 4)]
        XCTAssertEqual(VideoRunProgress.groups(members).map(\.title), ["Couldn't do", "Picked up", "Waiting", "Recorded"])
    }

    func testTheWideTriageColumnKeepsTheQuestionsFloor() {
        let wide = ColumnLayout.plan(contentWidth: 1384, navWidth: 56, scale: 1, hasDetail: true, hasTrailing: false,
                                     wideTriage: VideoRunLayout.pickerWidth)
        XCTAssertEqual(wide.list, 400)
        let narrow = ColumnLayout.plan(contentWidth: 850, navWidth: 56, scale: 1, hasDetail: true, hasTrailing: false,
                                       wideTriage: VideoRunLayout.pickerWidth)
        XCTAssertGreaterThanOrEqual(narrow.detail, ColumnLayout.minQuestion)
        let plain = ColumnLayout.plan(contentWidth: 1384, navWidth: 56, scale: 1, hasDetail: true, hasTrailing: false)
        XCTAssertEqual(plain.list, 328, "every other page keeps the table's width")
    }
}

// MARK: - Copy, the leaves-Mac note and the Sleep row

final class VideoCopyNeutralityTests: XCTestCase {
    /// R-VU11 (owner 2026-09-30) — no provider or model named as the one doing a job. Names reach the screen only as
    /// data (a harness label a record carries).
    static let names = ["gemini", "google", "claude", "codex", "chatgpt", "openai", "anthropic", "ollama", "openrouter",
                        "sonnet", "haiku", "opus", "gpt", "grok", "mistral", "groq", "whisper"]

    private func sources() throws -> [(String, String)] {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp")
        let files = ["Theme/Copy+Videos.swift", "Support/WatchLeavesMacNote.swift", "Views/Sleep/VideosWaitingRow.swift",
                     "Views/Common/NeutralCheckToggleStyle.swift"]
        let feed = try FileManager.default.contentsOfDirectory(atPath: root.appendingPathComponent("Views/Feed").path)
            .filter { $0.hasPrefix("Video") && $0.hasSuffix(".swift") }.map { "Views/Feed/" + $0 }
        XCTAssertGreaterThanOrEqual(feed.count, 8, "the scan found the video views")
        return try (files + feed).map { ($0, try String(contentsOf: root.appendingPathComponent($0), encoding: .utf8)) }
    }

    func testNoProviderOrModelIsNamedInTheVideoSurfaces() throws {
        for (path, text) in try sources() {
            // Code comments may cite a rule; only string literals reach a person.
            let literals = Self.stringLiterals(text)
            for literal in literals {
                let lower = literal.lowercased()
                for name in Self.names where lower.range(of: "\\b\(name)", options: .regularExpression) != nil {
                    XCTFail("\(path): \"\(literal)\" names \(name)")
                }
            }
        }
    }

    func testNoPriceOrTokenInTheVideoCopy() throws {
        for (path, text) in try sources() where path.hasSuffix("Copy+Videos.swift") {
            for literal in Self.stringLiterals(text) {
                XCTAssertFalse(literal.contains("$"), "\(path): \(literal)")
                XCTAssertFalse(literal.lowercased().contains("token"), "\(path): \(literal)")
                XCTAssertFalse(literal.lowercased().contains("being watched"), "R-VU9: \(literal)")
            }
        }
    }

    func testTheLeavesMacNoteIsExact() {
        XCTAssertEqual(WatchLeavesMacNote.text(), "Cicada sends nothing. Your agent decides where a video goes.")
    }

    static func stringLiterals(_ source: String) -> [String] {
        let pattern = #""((?:[^"\\\n]|\\.)*)""#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        let range = NSRange(source.startIndex..., in: source)
        return regex.matches(in: source, range: range).compactMap { Range($0.range(at: 1), in: source).map { String(source[$0]) } }
            .filter { !$0.isEmpty }
    }
}

final class SleepVideoRowTests: XCTestCase {
    func testTheRowSpeaksTheOneQueueWordingAndHidesAtZero() {
        XCTAssertEqual(VideosWaitingRowText.line(VideoSummary(total: 23, unread: 8, queued: 4, claimed: 1, failed: 1, read: 9)),
                       "4 queued · 1 picked up by an agent · 1 couldn't be done")
        XCTAssertNil(VideosWaitingRowText.line(VideoSummary(total: 23, unread: 23)))
        XCTAssertNil(VideosWaitingRowText.line(nil))
        XCTAssertEqual(Copy.Videos.sleepRowLink, "Choose videos ›")
    }

    func testTheRowStartsNothing() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources/CicadaApp/Views/Sleep/VideosWaitingRow.swift")
        let text = try String(contentsOf: root, encoding: .utf8)
        for needle in ["trigger", "consolidate", "PrimaryActionButton(", "handoff", "sleepVM"] {
            XCTAssertFalse(text.lowercased().contains(needle.lowercased()), "R-VU4: the row must not \(needle)")
        }
        XCTAssertTrue(text.contains("routeToVideos(choose: true)"), "its one action opens the picker")
    }
}

// MARK: - The Reader's view of a watch record

final class ProvenanceFidelityTests: XCTestCase {
    func testTheReaderHeaderIsBuiltFromData() {
        func doc(_ watch: EpisodeWatch?) -> EpisodeText { EpisodeText(episode: "e", text: "", harness: "acme-agent", watch: watch) }
        XCTAssertEqual(ReaderHeader.captureLine(doc(EpisodeWatch(basis: .both, engine: .videoLink))),
                       "A watch record: an agent recorded it from the video's frames and its transcript, reading the link directly. Cicada saw no frames itself.")
        XCTAssertEqual(ReaderHeader.captureLine(doc(EpisodeWatch(basis: .transcript, engine: .captions))),
                       "A watch record: an agent recorded it from the video's transcript, from captions. Cicada saw no frames itself.")
        XCTAssertEqual(ReaderHeader.captureLine(doc(EpisodeWatch(basis: nil, engine: nil))),
                       "A watch record: an agent recorded it before Cicada asked how it was read. Cicada saw no frames itself.")
        for engine in [VideoEngine.captions, .videoLink, .localFrames, .speechToText, .browser, .other] {
            let line = ReaderHeader.captureLine(doc(EpisodeWatch(basis: .frames, engine: engine))) ?? ""
            for name in VideoCopyNeutralityTests.names { XCTAssertFalse(line.lowercased().contains(name), line) }
        }
        XCTAssertNil(ReaderHeader.captureLine(doc(nil)), "a plain episode says nothing new")
    }

    func testAMediaTurnReadsAsTheVideoNotThePerson() {
        let approximate = EpisodeTurn(index: 0, start: 0, contentStart: 0, end: 1, role: "media", t: 245, fidelity: .approximate)
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(approximate, harness: nil, origin: nil), "From the video · 4:05 · approximate wording")
        let verbatim = EpisodeTurn(index: 0, start: 0, contentStart: 0, end: 1, role: "media", t: 0, fidelity: .verbatim)
        XCTAssertEqual(EvidenceSpeaker.turnSpeaker(verbatim, harness: nil, origin: nil), "From the video · 0:00")
    }

    func testTheMetaLineTakesTheWatchJoinsModel() {
        let doc = EpisodeText(episode: "ep_2026-09-22_001", text: "", timestamp: "2026-09-22T10:00:00Z", harness: "claude-code",
                              watch: EpisodeWatch(basis: .both, engine: .localFrames, fidelity: .verbatim,
                                                  authorModel: "claude-opus-5-5", authorEffort: "high"))
        let meta = ReaderHeader.meta(doc, locale: Locale(identifier: "en_US"), timeZone: TimeZone(identifier: "UTC")!)
        XCTAssertTrue(meta.contains("high effort"), meta)
    }
}
