import AppKit
import XCTest
@testable import CicadaApp

/// G191 — "What made you save this?": when the question is asked (the trigger rules), what the panel does with each
/// tap, key and timer (its state), where it sits, and the center that ties them to the API. Synthetic bookmarks only.
final class SaveWhyTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)

    private func iso(_ date: Date) -> String { ISO8601DateFormatter().string(from: date) }

    private func fresh(_ url: String = "https://www.alpha.example/post", ageSeconds: TimeInterval? = 30) -> FreshBookmark {
        FreshBookmark(url: url, title: "Alpha post", origin: "chrome-bookmark", channel: "chrome-bookmarks",
                      episodeId: "ep_2027-01-15_001", addedAt: ageSeconds.map { iso(now.addingTimeInterval(-$0)) })
    }

    private func result(_ items: [FreshBookmark], total: Int? = nil, firstSync: Bool = false) -> BookmarkSyncResult {
        var r = BookmarkSyncResult(new: items.count, skipped: 4, sources: [
            BookmarkSyncSourceSummary(origin: "chrome-bookmark", channel: "chrome-bookmarks", found: 5,
                                      new: items.count, skipped: 4, firstSync: firstSync),
        ])
        r.fresh = items
        r.freshTotal = total ?? items.count
        return r
    }

    private func inputs(_ r: BookmarkSyncResult, enabled: Bool = true, live: Bool = true, lastAsked: Date? = nil,
                        muted: Set<String> = [], showing: Bool = false) -> SaveWhyPolicy.Inputs {
        .init(enabled: enabled, live: live, result: r, now: now, lastAsked: lastAsked, mutedHosts: muted,
              showing: showing)
    }

    // MARK: - The trigger rules

    func testOneBookmarkMadeAMomentAgoIsAsked() {
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh()]))), .ask(fresh()))
    }

    func testTheSwitchIsOffByDefaultAndOffNeverAsks() {
        let defaults = UserDefaults(suiteName: "SaveWhyTests.\(UUID().uuidString)")!
        XCTAssertFalse(SaveWhyPrefs(defaults: defaults).enabled, "G191 (7): on only after the owner tries it")
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh()]), enabled: false)), .skip(.off))
    }

    func testOnlyASyncTheWatchStartedAsks() {
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh()]), live: false)), .skip(.notLive),
                       "a catch-up, Sync now, Turn on or import never asks")
    }

    func testAFirstSyncNeverAsks() {
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh()], firstSync: true))), .skip(.firstSync))
    }

    func testABulkImportNeverAsks() {
        let many = (0..<3).map { fresh("https://bulk.example/\($0)") }
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result(many, total: 40))), .skip(.bulk))
        // Two new at once is already "many": the panel is about one bookmark.
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh(), fresh("https://beta.example")]))), .skip(.bulk))
    }

    func testAReorganisedBookmarkBarNeverAsks() {
        // Moved bookmarks are URLs Cicada already holds: the backend reports nothing fresh.
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([]))), .skip(.noneNew))
    }

    func testABookmarkMadeLongAgoNeverAsks() {
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh(ageSeconds: 6 * 60)]))), .skip(.notRecent),
                       "another device's bookmark synced in late is not a moment of saving")
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh(ageSeconds: -10 * 60)]))), .skip(.notRecent))
        // A browser that records no instant (a Safari bookmark) relies on the live watch alone.
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh(ageSeconds: nil)]))), .ask(fresh(ageSeconds: nil)))
    }

    func testTheRateLimitAndTheOpenPanelHoldTheNextQuestion() {
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh()]), lastAsked: now.addingTimeInterval(-60))),
                       .skip(.rateLimited))
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh()]),
                                                   lastAsked: now.addingTimeInterval(-SaveWhyPolicy.minimumGap))),
                       .ask(fresh()))
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh()]), showing: true)), .skip(.showing))
    }

    func testAMutedSiteIsNeverAsked() {
        XCTAssertEqual(fresh().host, "alpha.example", "www. is the same site")
        XCTAssertEqual(SaveWhyPolicy.decide(inputs(result([fresh()]), muted: ["alpha.example"])), .skip(.muted))
    }

    // MARK: - The panel's state

    private func panel() -> SaveWhyPanelState {
        SaveWhyPanelState(item: fresh(), order: ["design", "product", "technique", "read_later"], maxText: 20)
    }

    func testOneTapSavesAfterTheLingerWithNoConfirm() {
        var s = panel()
        XCTAssertEqual(SaveWhyPanelState.opening(), [.startTimer(SaveWhyPolicy.askTimeout)])
        XCTAssertEqual(s.send(.tapReason("design")), [.startTimer(SaveWhyPolicy.linger)])
        XCTAssertEqual(s.phase, .answered)
        let answer = SavedWhyAnswer(reasons: ["design"])
        XCTAssertEqual(s.send(.lingerElapsed), [.post(answer), .close])
        XCTAssertEqual(s.phase, .closed(.answered(answer)))
        XCTAssertEqual(s.send(.tapReason("product")), [], "a closed panel ignores everything")
    }

    func testASecondTapAddsInThePanelsOrderAndATapCanBeTakenBack() {
        var s = panel()
        _ = s.send(.tapReason("product"))
        _ = s.send(.tapReason("design"))
        _ = s.send(.tapProject("alpha-project"))
        XCTAssertEqual(s.selection, SavedWhyAnswer(reasons: ["design", "product"], project: "alpha-project"))
        _ = s.send(.tapProject("alpha-project"))
        _ = s.send(.tapReason("product"))
        XCTAssertEqual(s.send(.tapReason("design")), [.startTimer(SaveWhyPolicy.askTimeout)],
                       "nothing chosen again: back to asking, on the question's own timer")
        XCTAssertEqual(s.phase, .asking)
    }

    func testClosingWithNothingChosenIsSilent() {
        for event in [SaveWhyPanelState.Event.escape, .clickOutside, .timeout] {
            var s = panel()
            XCTAssertEqual(s.send(event), [.close], "\(event) posts nothing")
            XCTAssertEqual(s.phase, .closed(.dismissed))
        }
    }

    func testATapIsAnAnswerEvenIfThePanelIsClosedEarly() {
        var s = panel()
        _ = s.send(.tapReason("technique"))
        XCTAssertEqual(s.send(.clickOutside), [.post(SavedWhyAnswer(reasons: ["technique"])), .close])
    }

    func testSomethingElseSendsTheWordsWithTheTapsOnReturn() {
        var s = panel()
        _ = s.send(.tapReason("design"))
        XCTAssertEqual(s.send(.tapOther), [.startTimer(SaveWhyPolicy.writingTimeout), .focusText])
        XCTAssertEqual(s.send(.tapReason("product")), [], "a tap while writing waits for Return")
        _ = s.send(.draftChanged("  the   onboarding flow and much more text "))
        XCTAssertEqual(s.draft.count, 20, "capped at the backend's maxText")
        XCTAssertEqual(s.send(.submitText),
                       [.post(SavedWhyAnswer(reasons: ["design", "product"], text: "the onboarding f")), .close])
    }

    func testAnUnsentDraftIsDroppedButTheTapsAreKept() {
        var s = panel()
        _ = s.send(.tapReason("read_later"))
        _ = s.send(.tapOther)
        _ = s.send(.draftChanged("half a thought"))
        XCTAssertEqual(s.send(.escape), [.post(SavedWhyAnswer(reasons: ["read_later"])), .close])
        var empty = panel()
        _ = empty.send(.tapOther)
        _ = empty.send(.draftChanged("   "))
        XCTAssertEqual(empty.send(.submitText), [.close], "blank words and no taps: nothing to post")
    }

    func testDontAskMutesTheSiteAndKeepsWhatWasTapped() {
        var s = panel()
        XCTAssertEqual(s.send(.dontAskForSite), [.mute("alpha.example"), .close])
        XCTAssertEqual(s.phase, .closed(.muted(nil)))
        var tapped = panel()
        _ = tapped.send(.tapReason("design"))
        XCTAssertEqual(tapped.send(.dontAskForSite),
                       [.mute("alpha.example"), .post(SavedWhyAnswer(reasons: ["design"])), .close])
    }

    // MARK: - Placement and motion

    /// A 14-inch notched laptop, in screen points: the notch is the gap between the two menu-bar areas.
    private let notchedScreen = CGRect(x: 0, y: 0, width: 1512, height: 982)
    private var notch: CGRect? {
        SaveWhyNotch.notchRect(screen: notchedScreen,
                               topLeft: CGRect(x: 0, y: 950, width: 662, height: 32),
                               topRight: CGRect(x: 850, y: 950, width: 662, height: 32), topInset: 32)
    }

    func testTheNotchIsTheGapBetweenTheMenuBarAreas() {
        XCTAssertEqual(notch, CGRect(x: 662, y: 950, width: 188, height: 32))
        XCTAssertNil(SaveWhyNotch.notchRect(screen: notchedScreen, topLeft: nil, topRight: nil, topInset: 0),
                     "a screen with no notch has none")
        XCTAssertNil(SaveWhyNotch.notchRect(screen: notchedScreen, topLeft: .zero, topRight: .zero, topInset: 0))
    }

    func testOnANotchedMacThePanelIsTheNotchGrown() {
        let size = CGSize(width: 460, height: 200)
        let frame = SaveWhyNotch.frame(screen: notchedScreen, notch: notch, size: size)
        XCTAssertEqual(frame.maxY, notchedScreen.maxY, "the top edge is flush with the screen's — the notch's own")
        XCTAssertEqual(frame.midX, notch!.midX, "centred under the notch")
        XCTAssertEqual(frame.size, size)
        XCTAssertEqual(SaveWhyNotch.band(screen: notchedScreen, visible: notchedScreen, notch: notch), 32,
                       "the empty band is the notch's height, so nothing sits behind the camera")
        let rest = SaveWhyNotch.collapsed(notch: notch)
        XCTAssertEqual(rest, CGSize(width: 188 + 2 * SaveWhyNotch.ear, height: 32),
                       "at rest the body is exactly the notch, so the start is invisible against it")
    }

    func testWithoutANotchTheSameShapeDropsFromTheTopCentre() {
        let screen = CGRect(x: 0, y: 0, width: 1920, height: 1080)
        let size = CGSize(width: 460, height: 190)
        let frame = SaveWhyNotch.frame(screen: screen, notch: nil, size: size)
        XCTAssertEqual(frame.maxY, 1080)
        XCTAssertEqual(frame.midX, 960)
        XCTAssertEqual(SaveWhyNotch.band(screen: screen, visible: CGRect(x: 0, y: 0, width: 1920, height: 1056),
                                         notch: nil), 24, "the band is the menu bar")
        XCTAssertEqual(SaveWhyNotch.band(screen: screen, visible: screen, notch: nil), SaveWhyNotch.fallbackMenuBar,
                       "a hidden menu bar (full screen) keeps the usual band")
        XCTAssertEqual(SaveWhyNotch.collapsed(notch: nil).height, 0, "it grows from a sliver at the top edge")
        // A second display's own origin: centred on that screen, flush with its top.
        let side = CGRect(x: 1920, y: 200, width: 1440, height: 900)
        let onSide = SaveWhyNotch.frame(screen: side, notch: nil, size: size)
        XCTAssertEqual(onSide.midX, side.midX)
        XCTAssertEqual(onSide.maxY, side.maxY)
    }

    func testTheShapeGrowsFromTheNotchToTheWholePanel() {
        let bounds = CGRect(x: 0, y: 0, width: 460, height: 200)
        let rest = SaveWhyNotch.collapsed(notch: notch)
        let atRest = SaveWhyNotchShape(progress: 0, collapsed: rest).path(in: bounds).boundingRect
        XCTAssertEqual(atRest.width, rest.width, accuracy: 0.5)
        XCTAssertEqual(atRest.height, rest.height, accuracy: 0.5)
        XCTAssertEqual(atRest.midX, bounds.midX, accuracy: 0.5)
        XCTAssertEqual(atRest.minY, 0, accuracy: 0.5, "top-anchored: it hangs from the screen's edge")
        let grown = SaveWhyNotchShape(progress: 1, collapsed: rest).path(in: bounds).boundingRect
        XCTAssertEqual(grown.width, bounds.width, accuracy: 0.5)
        XCTAssertEqual(grown.height, bounds.height, accuracy: 0.5)
        let overshoot = SaveWhyNotchShape(progress: 1.2, collapsed: rest).path(in: bounds).boundingRect
        XCTAssertLessThanOrEqual(overshoot.width, bounds.width + 0.5, "a spring's give never leaves the window")
        XCTAssertTrue(SaveWhyNotchShape(progress: 0, collapsed: SaveWhyNotch.collapsed(notch: nil))
            .path(in: bounds).isEmpty, "no notch: nothing shows before it grows")
    }

    func testTheGrowIsInTheMotionBudgetAndOnlyFadesUnderReduceMotion() {
        XCTAssertLessThanOrEqual(CicadaMotion.notchGrowDuration, CicadaMotion.maxDuration)
        XCTAssertLessThanOrEqual(CicadaMotion.notchShrinkDuration, CicadaMotion.maxDuration)
        XCTAssertLessThan(CicadaMotion.notchShrinkDuration, CicadaMotion.notchGrowDuration, "it leaves quicker")
        XCTAssertEqual(CicadaMotion.notchShrinkLength(reduceMotion: true), CicadaMotion.reducedFadeDuration)
        XCTAssertEqual(CicadaMotion.notchShrinkLength(reduceMotion: false), CicadaMotion.notchShrinkDuration)
    }

    func testThePanelIsAboveTheMenuBarAndBelowMenus() {
        XCTAssertGreaterThan(SaveWhyPanelController.level.rawValue, NSWindow.Level.statusBar.rawValue)
        XCTAssertLessThan(SaveWhyPanelController.level.rawValue, NSWindow.Level.popUpMenu.rawValue)
    }

    // MARK: - The center

    @MainActor
    func testTheCenterAsksOncePostsTheAnswerAndRespectsTheRateLimit() async {
        let defaults = UserDefaults(suiteName: "SaveWhyTests.\(UUID().uuidString)")!
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        let api = FakeSavedWhyAPI()
        let presenter = FakePresenter()
        let center = SaveWhyCenter(prefs: prefs, api: api, presenter: presenter, now: { [now] in now })

        await center.noticed(result([fresh()]), live: true)
        XCTAssertEqual(presenter.shown, 1)
        XCTAssertEqual(center.state?.order, ["design", "product", "technique", "read_later"])
        center.send(.tapReason("product"))
        center.send(.escape)
        await center.settle()
        XCTAssertEqual(presenter.hidden, 1)
        XCTAssertEqual(center.lastOutcome, .answered(SavedWhyAnswer(reasons: ["product"])))
        let posts = await api.posts
        XCTAssertEqual(posts.map(\.url), [fresh().url])
        XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(reasons: ["product"])])

        // The next new bookmark a minute later waits: one question per `minimumGap`.
        await center.noticed(result([fresh("https://beta.example/x")]), live: true)
        XCTAssertEqual(center.lastDecision, .skip(.rateLimited))
        XCTAssertEqual(presenter.shown, 1)
    }

    /// The debug harness shows the panel for a sample bookmark at once, past every rule, and writes nothing.
    @MainActor
    func testThePreviewShowsAtOnceAndWritesNothing() async {
        let defaults = UserDefaults(suiteName: "SaveWhyTests.\(UUID().uuidString)")!
        let prefs = SaveWhyPrefs(defaults: defaults)   // the switch is off: the preview does not care
        let api = FakeSavedWhyAPI()
        let presenter = FakePresenter()
        let center = SaveWhyCenter(prefs: prefs, api: api, presenter: presenter, now: { [now] in now })
        await center.preview(channel: "safari-bookmarks")
        XCTAssertEqual(presenter.shown, 1)
        XCTAssertEqual(center.state?.item.channel, "safari-bookmarks")
        XCTAssertEqual(center.state?.item.host, "alpha.example", "a placeholder site, never a real one")
        center.send(.tapReason("design"))
        center.send(.dontAskForSite)
        await center.settle()
        let posts = await api.posts
        XCTAssertTrue(posts.isEmpty, "a preview's answer is never posted")
        XCTAssertTrue(prefs.mutedHosts.isEmpty, "nor is its site muted")
        XCTAssertNil(prefs.lastAsked, "nor does it spend the rate limit")
        // The next real bookmark is asked as usual.
        prefs.enabled = true
        await center.noticed(result([fresh()]), live: true)
        XCTAssertEqual(presenter.shown, 2)
        center.send(.tapReason("product"))
        center.send(.escape)
        await center.settle()
        let real = await api.posts
        XCTAssertEqual(real.map(\.url), [fresh().url])
    }

    func testThePreviewExistsOnlyInADeveloperBuildWithItsKeySet() {
        XCTAssertTrue(SaveWhyPreview.isAvailable(flag: true, distribution: .developer))
        XCTAssertFalse(SaveWhyPreview.isAvailable(flag: false, distribution: .developer), "hidden by default")
        XCTAssertFalse(SaveWhyPreview.isAvailable(flag: true, distribution: .release), "never in a release app")
        XCTAssertEqual(SaveWhyPreview.browsers.map(\.channel), ["chrome-bookmarks", "safari-bookmarks"])
    }

    @MainActor
    func testTheCenterMutesASiteForGood() async {
        let defaults = UserDefaults(suiteName: "SaveWhyTests.\(UUID().uuidString)")!
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        let center = SaveWhyCenter(prefs: prefs, api: FakeSavedWhyAPI(), presenter: FakePresenter(),
                                   now: { [now] in now })
        await center.noticed(result([fresh()]), live: true)
        center.send(.dontAskForSite)
        XCTAssertEqual(prefs.mutedHosts, ["alpha.example"])
        prefs.lastAsked = nil
        await center.noticed(result([fresh("https://alpha.example/other")]), live: true)
        XCTAssertEqual(center.lastDecision, .skip(.muted))
    }

    @MainActor
    func testAnAnswerRefusedWhileSleepWritesIsHeldAndSentWithItsOwnTime() async {
        let defaults = UserDefaults(suiteName: "SaveWhyTests.\(UUID().uuidString)")!
        let prefs = SaveWhyPrefs(defaults: defaults)
        prefs.enabled = true
        let api = FakeSavedWhyAPI()
        await api.fail(with: [APIError.httpError(409, "{\"code\":\"sleep_writing\"}")])
        var clock = now
        let center = SaveWhyCenter(prefs: prefs, api: api, presenter: FakePresenter(), now: { clock })

        await center.noticed(result([fresh()]), live: true)
        center.send(.tapReason("design"))
        center.send(.clickOutside)
        await center.settle()
        XCTAssertEqual(center.heldCount, 1, "a 409 holds the answer instead of losing it")
        XCTAssertEqual(SaveWhyOutbox(defaults: defaults).entries.first?.at, now, "held with the time it was given")

        // Sleep is still writing at the first retry: kept.
        await api.fail(with: [APIError.httpError(409, "")])
        clock = now.addingTimeInterval(60)
        await center.retryHeld()
        XCTAssertEqual(center.heldCount, 1)

        // Sleep let go: sent, with the original time, and gone from the queue.
        clock = now.addingTimeInterval(300)
        await center.retryHeld()
        XCTAssertEqual(center.heldCount, 0)
        let posts = await api.posts
        let times = await api.times
        XCTAssertEqual(posts.map(\.answer), [SavedWhyAnswer(reasons: ["design"])])
        XCTAssertEqual(times, [now])
    }

    @MainActor
    func testAHeldAnswerIsDroppedWhenRefusedForGoodOrADayOld() async {
        let defaults = UserDefaults(suiteName: "SaveWhyTests.\(UUID().uuidString)")!
        let outbox = SaveWhyOutbox(defaults: defaults)
        outbox.hold(.init(url: "https://alpha.example/a", answer: SavedWhyAnswer(reasons: ["design"]), at: now))
        outbox.hold(.init(url: "https://beta.example/b", answer: SavedWhyAnswer(reasons: ["product"]),
                          at: now.addingTimeInterval(-25 * 3600)))
        let api = FakeSavedWhyAPI()
        await api.fail(with: [APIError.httpError(404, "That link isn't saved yet")])
        let center = SaveWhyCenter(prefs: SaveWhyPrefs(defaults: defaults), api: api, now: { [now] in now })
        await center.retryHeld()
        XCTAssertEqual(center.heldCount, 0, "404 drops the first; the second is over a day old")
        let posts = await api.posts
        XCTAssertTrue(posts.isEmpty)
        XCTAssertEqual(SaveWhyOutbox.verdict(for: APIError.serverUnreachable), .hold)
        XCTAssertEqual(SaveWhyOutbox.verdict(for: URLError(.cannotConnectToHost)), .hold)
        XCTAssertEqual(SaveWhyOutbox.verdict(for: APIError.httpError(422, "")), .drop)
    }

    @MainActor
    func testTheSignalCarriesWhetherTheWatchStartedTheSync() async {
        var seen: [BookmarkSyncSignal.Delivery] = []
        BookmarkSyncSignal.observer = { _, delivery in seen.append(delivery) }
        defer { BookmarkSyncSignal.observer = nil }
        BookmarkSyncSignal.post(result([]))
        await BookmarkSyncSignal.$live.withValue(true) { BookmarkSyncSignal.post(result([])) }
        // G191 live: a sync an early look already spoke for only says its links are saved — it never asks again.
        await BookmarkSyncSignal.$live.withValue(true) { BookmarkSyncSignal.post(result([]), lookedEarly: true) }
        XCTAssertEqual(seen, [.synced(live: false), .synced(live: true), .afterEarlyLook])
    }
}

private actor FakeSavedWhyAPI: SavedWhyAPI {
    var posts: [(url: String, answer: SavedWhyAnswer)] = []
    var times: [Date] = []
    /// Errors to throw on the next posts, in order (then succeed).
    var failures: [Error] = []
    func fail(with errors: [Error]) { failures = errors }

    func freshBookmarks(_ bytes: BookmarkBytes) async throws -> BookmarkSyncResult {
        BookmarkSyncResult(new: 0, skipped: 0, sources: [])
    }

    func savedWhyOptions() async throws -> SavedWhyOptions {
        SavedWhyOptions(reasons: [
            .init(key: "design", label: "The design, the look"), .init(key: "product", label: "The product itself"),
            .init(key: "technique", label: "A technique to reuse"), .init(key: "read_later", label: "To read later"),
        ], projects: [.init(id: "alpha-project", name: "Alpha project")], maxText: 500)
    }

    func saveWhy(url: String, answer: SavedWhyAnswer, at: Date) async throws {
        if !failures.isEmpty { throw failures.removeFirst() }
        posts.append((url, answer))
        times.append(at)
    }
}

@MainActor
private final class FakePresenter: SaveWhyPresenting {
    var shown = 0
    var hidden = 0
    func show(_ center: SaveWhyCenter) { shown += 1 }
    func hide() { hidden += 1 }
    func focusText() {}
}
