import XCTest
@testable import CicadaApp

/// G246 (ruling 81, plan Track K) — "Keep as a page": what the app draws for each answer, the click's one request, the
/// failure words, and Home's one dated line. The backend decides which saves are posts; the app draws what it says,
/// and nothing at all while the switch is off. Synthetic data only.
@MainActor
final class KeepAsPageTests: XCTestCase {
    private let link = "https://x.com/alex_example/status/1234567890123"

    private func state(_ word: String, canUndo: Bool = false, because: [String] = []) -> KeepAsPageState {
        KeepAsPageState(state: word, canUndo: canUndo, becauseOf: because, mediaEntityId: "media-a-post")
    }

    // MARK: What is offered

    func testARowOffersKeepAndAKeptPostOffersTheWayBackOnlyWhileNothingElseHoldsItsPage() {
        XCTAssertEqual(KeepAsPage.offer(state("row")), .keep)
        XCTAssertEqual(KeepAsPage.offer(state("kept", canUndo: true)), .back)
        XCTAssertNil(KeepAsPage.offer(state("kept", canUndo: false, because: ["note"])))
    }

    func testNothingIsOfferedForAWorkAPostWithAPageOrWhileTheSwitchIsOff() {
        for word in ["none", "page", "", "unheard-of"] { XCTAssertNil(KeepAsPage.offer(state(word)), word) }
        XCTAssertNil(KeepAsPage.offer(nil), "a failed read never draws a control")
        XCTAssertNil(KeepAsPage.offer(.none))
    }

    func testTheOffersSayWhatTheyDoInPlainWords() {
        XCTAssertEqual(KeepAsPageOffer.keep.title, "Keep as a page")
        XCTAssertEqual(KeepAsPageOffer.back.title, "Back to a row")
        XCTAssertTrue(KeepAsPageOffer.keep.asksToKeep)
        XCTAssertFalse(KeepAsPageOffer.back.asksToKeep)
        for offer in [KeepAsPageOffer.keep, .back] {
            for words in [offer.title, offer.help, offer.done] {
                for jargon in ["Sleep", "episode", "stamp", "HIDE", "claim", "G246", "ruling"] {
                    XCTAssertFalse(words.contains(jargon), "\(words) names an internal word")
                }
            }
        }
    }

    // MARK: Decoding

    func testTheStateAndTheReplyDecodeFromTheWireAndToleranceFillsWhatIsMissing() throws {
        let wire = #"{"state":"kept","canUndo":true,"becauseOf":[],"mediaEntityId":"media-a-post"}"#
        let decoded = try JSONDecoder().decode(KeepAsPageState.self, from: Data(wire.utf8))
        XCTAssertEqual(decoded, state("kept", canUndo: true))
        let bare = try JSONDecoder().decode(KeepAsPageState.self, from: Data("{}".utf8))
        XCTAssertEqual(bare, .none)
        let reply = try JSONDecoder().decode(
            KeepAsPageReply.self,
            from: Data(#"{"status":"kept","state":"kept","canUndo":true,"becauseOf":[],"mediaEntityId":"m","episodeId":"ep_2026-11-20_001"}"#.utf8))
        XCTAssertEqual(reply.status, "kept")
        XCTAssertEqual(reply.state.state, "kept")
        XCTAssertEqual(KeepAsPage.offer(reply.state), .back)
    }

    func testTheGraphCarriesHowManyPostsAreHiddenAndAnOlderBackendSaysZero() throws {
        let withCount = try JSONDecoder().decode(GraphResponse.self, from: Data(#"{"nodes":[],"links":[],"hiddenPosts":4812}"#.utf8))
        XCTAssertEqual(withCount.hiddenPosts, 4812)
        let older = try JSONDecoder().decode(GraphResponse.self, from: Data(#"{"nodes":[],"links":[]}"#.utf8))
        XCTAssertEqual(older.hiddenPosts, 0)
        XCTAssertEqual(GraphResponse().hiddenPosts, 0)
        let round = try JSONDecoder().decode(GraphResponse.self, from: try JSONEncoder().encode(withCount))
        XCTAssertEqual(round.hiddenPosts, 4812)
    }

    // MARK: The click

    func testPressingKeepPostsOneRequestAndTheControlTurnsIntoTheWayBack() async {
        var sent: [(String, Bool)] = []
        let model = KeepAsPageModel(
            fetch: { _ in self.state("row") },
            send: { url, kept in
                sent.append((url, kept))
                return KeepAsPageReply(status: "kept", state: self.state("kept", canUndo: true))
            })
        await model.load(url: link)
        XCTAssertEqual(model.offer, .keep)
        let reply = await model.press(url: link)
        XCTAssertEqual(reply?.status, "kept")
        XCTAssertEqual(sent.count, 1)
        XCTAssertEqual(sent.first?.0, link)
        XCTAssertEqual(sent.first?.1, true)
        XCTAssertEqual(model.offer, .back, "the same control is the way back")
        XCTAssertEqual(model.done, "Kept as a page")
        XCTAssertNil(model.failure)
        _ = await model.press(url: link)
        XCTAssertEqual(sent.last?.1, false, "pressed again, it asks for the way back")
    }

    func testAnUnchangedAnswerSaysNothingWasDone() async {
        let model = KeepAsPageModel(fetch: { _ in self.state("row") },
                                    send: { _, _ in KeepAsPageReply(status: "unchanged", state: self.state("none")) })
        await model.load(url: link)
        _ = await model.press(url: link)
        XCTAssertNil(model.done)
        XCTAssertNil(model.offer, "a work keeps its page: nothing is left to press")
    }

    func testAFailedReadDrawsNothingAndAFailedClickSaysWhyAndKeepsTheControl() async {
        struct Down: Error {}
        let silent = KeepAsPageModel(fetch: { _ in throw Down() }, send: { _, _ in throw Down() })
        await silent.load(url: link)
        XCTAssertNil(silent.offer)
        XCTAssertNil(silent.failure, "a read that failed says nothing: the control simply is not there")

        let busy = KeepAsPageModel(
            fetch: { _ in self.state("row") },
            send: { _, _ in throw APIError.httpError(409, #"{"code":"sleep_writing","detail":"Sleep is updating your memory — that wasn't kept. Try again in a moment."}"#) })
        await busy.load(url: link)
        let reply = await busy.press(url: link)
        XCTAssertNil(reply)
        XCTAssertEqual(busy.failure, Copy.Keep.busy)
        XCTAssertEqual(busy.offer, .keep, "the click can be made again")
        XCTAssertFalse(busy.working)
    }

    func testAPressWithNothingOfferedSendsNothing() async {
        var calls = 0
        let model = KeepAsPageModel(fetch: { _ in .none }, send: { _, _ in calls += 1; return KeepAsPageReply(status: "kept", state: .none) })
        await model.load(url: link)
        let reply = await model.press(url: link)
        XCTAssertNil(reply)
        XCTAssertEqual(calls, 0)
    }

    func testTheFailureWordsAreTheServersOwnSentenceOrAFixedOne() {
        XCTAssertEqual(KeepAsPage.failureLine(APIError.httpError(409, #"{"detail":"It has a page for another reason too, so it stays one."}"#)),
                       "It has a page for another reason too, so it stays one.")
        XCTAssertEqual(KeepAsPage.failureLine(APIError.httpError(404, #"{"detail":"That link isn't saved yet"}"#)), "That link isn't saved yet")
        XCTAssertEqual(KeepAsPage.failureLine(APIError.httpError(500, "boom")), Copy.Keep.failed)
        XCTAssertEqual(KeepAsPage.failureLine(APIError.serverUnreachable), Copy.Keep.failed)
        XCTAssertEqual(KeepAsPage.failureLine(APIError.httpError(409, "not json")), Copy.Keep.failed)
    }

    // MARK: Home's one dated line

    private func defaults(_ name: String) -> UserDefaults {
        let defaults = TestDefaults.suite("KeepAsPageTests.\(name)")!
        defaults.removePersistentDomain(forName: TestDefaults.path("KeepAsPageTests.\(name)"))
        return defaults
    }

    private let en = Locale(identifier: "en_US")
    private let day0 = Date(timeIntervalSince1970: 1_795_000_000)   // 2026-11-17 in UTC; the exact day is never asserted

    func testNothingIsSaidWhileNothingIsHiddenAndAStoredDayIsForgotten() {
        let d = defaults("zero")
        XCTAssertNil(HiddenPostsNote.observe(hidden: 0, bank: "alpha", now: day0, defaults: d))
        XCTAssertNil(HiddenPostsNote.line(hidden: 0, record: nil, now: day0, locale: en))
        let held = HiddenPostsNote.observe(hidden: 12, bank: "alpha", now: day0, defaults: d)
        XCTAssertNotNil(held)
        XCTAssertNil(HiddenPostsNote.observe(hidden: 0, bank: "alpha", now: day0, defaults: d), "the switch went off")
        XCTAssertNil(HiddenPostsNote.load(bank: "alpha", defaults: d))
    }

    func testTheLineSaysHowManyAndSinceWhenAndIsDatedByTheFirstDayThisMacSawThem() {
        let d = defaults("line")
        let first = HiddenPostsNote.observe(hidden: 4812, bank: "alpha", now: day0, defaults: d)
        let later = HiddenPostsNote.observe(hidden: 4830, bank: "alpha", now: day0.addingTimeInterval(86_400 * 3), defaults: d)
        XCTAssertEqual(first, later, "the day is the first one, not the latest")
        let line = HiddenPostsNote.line(hidden: 4830, record: later, now: day0.addingTimeInterval(86_400 * 3), locale: en)
        XCTAssertNotNil(line)
        XCTAssertTrue(line!.contains("4,830 saved posts now show under their lists"), line!)
        XCTAssertTrue(line!.contains("since"), line!)
        XCTAssertTrue(line!.hasSuffix("Open one to keep it as a page."), line!)
        XCTAssertEqual(Copy.Keep.moved(1, since: "24 Nov", locale: en),
                       "1 saved post now shows under its list (since 24 Nov). Open it to keep it as a page.")
    }

    func testTheLineGoesAfterAMonthOrAtGotItAndEachMemoryKeepsItsOwn() {
        let d = defaults("gone")
        let record = HiddenPostsNote.observe(hidden: 9, bank: "alpha", now: day0, defaults: d)
        XCTAssertNotNil(HiddenPostsNote.line(hidden: 9, record: record, now: day0.addingTimeInterval(86_400 * 29), locale: en))
        XCTAssertNil(HiddenPostsNote.line(hidden: 9, record: record, now: day0.addingTimeInterval(86_400 * 31), locale: en))
        let other = HiddenPostsNote.observe(hidden: 9, bank: "beta", now: day0.addingTimeInterval(86_400 * 40), defaults: d)
        XCTAssertNotNil(HiddenPostsNote.line(hidden: 9, record: other, now: day0.addingTimeInterval(86_400 * 41), locale: en))
        HiddenPostsNote.dismiss(bank: "beta", defaults: d)
        XCTAssertNil(HiddenPostsNote.line(hidden: 9, record: HiddenPostsNote.load(bank: "beta", defaults: d),
                                          now: day0.addingTimeInterval(86_400 * 41), locale: en))
        XCTAssertNotNil(HiddenPostsNote.load(bank: "alpha", defaults: d), "dismissing one memory's line leaves the other's")
    }

    func testTheLineNamesNoInternalWordAndNoProvider() {
        let line = Copy.Keep.moved(4812, since: "24 Nov", locale: en)
        for word in ["Sleep", "episode", "stamp", "claim", "G246", "ruling", "node", "graph"] {
            XCTAssertFalse(line.contains(word), "\(line) names \(word)")
        }
    }
}
