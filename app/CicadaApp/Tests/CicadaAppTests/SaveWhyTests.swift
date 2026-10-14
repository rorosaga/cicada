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

    func testThePanelSitsTopCentreUnderTheMenuBarWithOrWithoutANotch() {
        let size = CGSize(width: 440, height: 120)
        // A notched laptop: a 32 pt menu bar the notch sits in.
        let notched = SaveWhyPlacement.frames(screen: CGRect(x: 0, y: 0, width: 1512, height: 982),
                                              visible: CGRect(x: 0, y: 0, width: 1512, height: 950),
                                              notchTop: 32, size: size, distance: 14)
        XCTAssertEqual(notched.end, CGRect(x: 536, y: 982 - 32 - SaveWhyPlacement.gap - 120, width: 440, height: 120))
        XCTAssertEqual(notched.start.minY - notched.end.minY, 14, "it drops out of the menu bar")
        // No notch, a 24 pt menu bar: the same place.
        let plain = SaveWhyPlacement.frames(screen: CGRect(x: 0, y: 0, width: 1920, height: 1080),
                                            visible: CGRect(x: 0, y: 0, width: 1920, height: 1056),
                                            notchTop: 0, size: size, distance: 14)
        XCTAssertEqual(plain.end.midX, 960)
        XCTAssertEqual(plain.end.maxY, 1080 - 24 - SaveWhyPlacement.gap)
        // A hidden menu bar (full screen): the notch's height, else the usual one.
        let hidden = SaveWhyPlacement.frames(screen: CGRect(x: 0, y: 0, width: 1920, height: 1080),
                                             visible: CGRect(x: 0, y: 0, width: 1920, height: 1080),
                                             notchTop: 0, size: size, distance: 0)
        XCTAssertEqual(hidden.end.maxY, 1080 - SaveWhyPlacement.fallbackMenuBar - SaveWhyPlacement.gap)
        XCTAssertEqual(hidden.start, hidden.end)
    }

    func testTheDropIsInTheMotionBudgetAndStillUnderReduceMotion() {
        XCTAssertLessThanOrEqual(CicadaMotion.notchDropDuration, CicadaMotion.maxDuration)
        XCTAssertLessThanOrEqual(CicadaMotion.notchLeaveDuration, CicadaMotion.maxDuration)
        XCTAssertEqual(CicadaMotion.notchDrop(reduceMotion: true).distance, 0)
        XCTAssertEqual(CicadaMotion.notchLeave(reduceMotion: true).distance, 0)
        XCTAssertGreaterThan(CicadaMotion.notchDrop(reduceMotion: false).distance, 0)
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
    func testTheSignalCarriesWhetherTheWatchStartedTheSync() async {
        var seen: [Bool] = []
        BookmarkSyncSignal.observer = { _, live in seen.append(live) }
        defer { BookmarkSyncSignal.observer = nil }
        BookmarkSyncSignal.post(result([]))
        await BookmarkSyncSignal.$live.withValue(true) { BookmarkSyncSignal.post(result([])) }
        XCTAssertEqual(seen, [false, true])
    }
}

private actor FakeSavedWhyAPI: SavedWhyAPI {
    var posts: [(url: String, answer: SavedWhyAnswer)] = []

    func savedWhyOptions() async throws -> SavedWhyOptions {
        SavedWhyOptions(reasons: [
            .init(key: "design", label: "The design, the look"), .init(key: "product", label: "The product itself"),
            .init(key: "technique", label: "A technique to reuse"), .init(key: "read_later", label: "To read later"),
        ], projects: [.init(id: "alpha-project", name: "Alpha project")], maxText: 500)
    }

    func saveWhy(url: String, answer: SavedWhyAnswer) async throws { posts.append((url, answer)) }
}

@MainActor
private final class FakePresenter: SaveWhyPresenting {
    var shown = 0
    var hidden = 0
    func show(_ center: SaveWhyCenter) { shown += 1 }
    func hide() { hidden += 1 }
    func focusText() {}
}
