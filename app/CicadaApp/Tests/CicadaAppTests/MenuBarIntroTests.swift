import XCTest
@testable import CicadaApp

/// Owner 2026-10-23 — the menu-bar worm appears only after onboarding's *Meet your bookworm* step explained it: hidden
/// before the step, shown after it, shown after Skip (with no flight), and every install from before the gate keeps its
/// worm exactly as it was (Hyrum: an absent key reads `done`; `cicada.menuBar.visible` is untouched).
@MainActor
final class MenuBarIntroTests: XCTestCase {
    private var defaults: UserDefaults!
    private var suite: String!

    override func setUp() {
        super.setUp()
        suite = "MenuBarIntroTests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
        super.tearDown()
    }

    // MARK: The gate

    func testAFreshInstallsWormWaitsForTheStep() {
        XCTAssertEqual(MenuBarIntro.prepareAtLaunch(defaults, keys: { [] }), .waiting)
        XCTAssertEqual(defaults.string(forKey: MenuBarIntro.defaultsKey), "waiting", "stored as a word")
        let manager = MenuBarManager()
        manager.setIntroPhase(MenuBarIntro.phase(defaults))
        manager.setVisible(true)
        XCTAssertFalse(manager.isVisible, "hidden before the step, though the switch is on")
    }

    func testPassingTheStepShowsTheWormAndRemembersIt() {
        MenuBarIntro.prepareAtLaunch(defaults, keys: { [] })
        let manager = MenuBarManager()
        manager.setIntroPhase(MenuBarIntro.phase(defaults))
        manager.introduce(.fly(from: CGRect(x: 100, y: 100, width: 144, height: 144)), defaults: defaults)
        XCTAssertTrue(manager.isVisible)
        XCTAssertEqual(MenuBarIntro.phase(defaults), .done)
        XCTAssertEqual(MenuBarIntro.prepareAtLaunch(defaults, keys: { [] }), .done,
                       "the next launch never hides it again")
    }

    func testSkipShowsTheWormWithoutTheFlight() {
        MenuBarIntro.prepareAtLaunch(defaults, keys: { [] })
        let manager = MenuBarManager()
        manager.setIntroPhase(.waiting)
        manager.introduce(.instant, defaults: defaults)
        XCTAssertTrue(manager.isVisible)
        XCTAssertEqual(MenuBarIntro.phase(defaults), .done)
        // Onboarding v3: the flight is Done's closing beat. Skip and Continue on the worm's step only move on to Done;
        // Open Cicada by pointer flies (when the worm's frame is known), ⏎ never does (DR-60).
        let view = try? source("Views/Onboarding/OnboardingView.swift")
        XCTAssertTrue(view?.contains("onSkip: { go(.done, .pointer) }") == true, "Skip moves on, the worm waits")
        XCTAssertTrue(view?.contains("case .done: openCicada(input == .keyboard ? .openCicadaByKey : .openCicadaByPointer")
                      == true, "⏎ on Done is the key's exit")
        XCTAssertEqual(OnboardingExit.openCicadaByKey.reveal(from: CGRect(x: 1, y: 1, width: 9, height: 9),
                                                            reduceMotion: false), .instant, "⏎ never flies (DR-60)")
        XCTAssertEqual(OnboardingExit.openCicadaByPointer.reveal(from: nil, reduceMotion: false), .instant,
                       "no frame, no flight")
    }

    /// Hyrum: anyone who ran an earlier build has some `cicada.` key — the switch, a theme, an onboarded bank — and no
    /// intro key. Their worm is never hidden, and nothing is written for them.
    func testAnInstallFromBeforeTheGateKeepsItsWorm() {
        for keys in [["cicada.hasOnboarded.default"], ["cicada.menuBar.visible"], ["cicada.colorScheme"],
                     ["cicada.onboarding.step.default", "NSWindow Frame main"]] {
            XCTAssertEqual(MenuBarIntro.prepareAtLaunch(defaults, keys: { keys }), .done, "\(keys)")
            XCTAssertNil(defaults.object(forKey: MenuBarIntro.defaultsKey), "\(keys): nothing written")
        }
        let manager = MenuBarManager()
        manager.setIntroPhase(MenuBarIntro.phase(defaults))
        XCTAssertTrue(manager.isVisible, "an absent key reads done")
    }

    func testTheSwitchStillHidesItAndAWaitingWormNeverOverridesTheSwitch() {
        XCTAssertTrue(MenuBarIntro.shows(preference: true, phase: .done))
        XCTAssertFalse(MenuBarIntro.shows(preference: false, phase: .done))
        XCTAssertFalse(MenuBarIntro.shows(preference: true, phase: .waiting))
        XCTAssertFalse(MenuBarIntro.shows(preference: false, phase: .waiting))
        let manager = MenuBarManager()
        manager.setIntroPhase(.waiting)
        manager.setVisible(false)
        manager.introduce(.instant, defaults: defaults)
        XCTAssertFalse(manager.isVisible, "the person's switch keeps it hidden")
        XCTAssertEqual(MenuBarIntro.phase(defaults), .done, "but the intro is over")
        manager.setVisible(true)
        XCTAssertTrue(manager.isVisible)
    }

    func testAStoredValueNoBuildWroteReadsDoneNeverTraps() {
        defaults.set("someday", forKey: MenuBarIntro.defaultsKey)
        XCTAssertEqual(MenuBarIntro.phase(defaults), .done)
        defaults.set(true, forKey: MenuBarIntro.defaultsKey)
        XCTAssertEqual(MenuBarIntro.phase(defaults), .done)
    }

    /// A rerun (Run setup again) meets a worm already in the menu bar: passing the step again changes nothing.
    func testARerunNeverHidesOrFliesAWormAlreadyThere() {
        let manager = MenuBarManager()
        manager.setIntroPhase(.done)
        manager.introduce(.fly(from: .zero), defaults: defaults)
        XCTAssertTrue(manager.isVisible)
        XCTAssertNil(defaults.object(forKey: MenuBarIntro.defaultsKey), "nothing to record")
    }

    /// Unknown is never "no onboarding" (`FirstRunGate`'s rule): the worm is let out without its step only once the
    /// gate's inputs are known and it will not raise onboarding.
    func testTheGateSettlesAWaitingWormOnlyWhenNoOnboardingIsComing() {
        XCTAssertTrue(MenuBarIntro.settlesWithoutStep(bankResolved: true, graphLoaded: true, gateShows: false,
                                                      onboardingShowing: false))
        XCTAssertFalse(MenuBarIntro.settlesWithoutStep(bankResolved: false, graphLoaded: true, gateShows: false,
                                                       onboardingShowing: false))
        XCTAssertFalse(MenuBarIntro.settlesWithoutStep(bankResolved: true, graphLoaded: false, gateShows: false,
                                                       onboardingShowing: false))
        XCTAssertFalse(MenuBarIntro.settlesWithoutStep(bankResolved: true, graphLoaded: true, gateShows: true,
                                                       onboardingShowing: false))
        XCTAssertFalse(MenuBarIntro.settlesWithoutStep(bankResolved: true, graphLoaded: true, gateShows: false,
                                                       onboardingShowing: true))
    }

    func testEveryWayOutOfOnboardingLetsTheWormIn() throws {
        let content = try source("ContentView.swift")
        XCTAssertTrue(content.contains("if !showing { menuBar?.introduce(.instant) }"),
                      "Set up later, the demo and every other exit show it, with no flight")
        let app = try source("CicadaApp.swift")
        // Stored properties initialise in declaration order before `init`, and some write a `cicada.` key as they are
        // built (`ExportWaits`, seen live 2026-10-23): the decision is the first stored property.
        let prepare = try XCTUnwrap(app.range(of: "private let menuBarIntroAtLaunch = MenuBarIntro.prepareAtLaunch()"))
        let firstState = try XCTUnwrap(app.range(of: "@State private var"))
        XCTAssertLessThan(prepare.lowerBound, firstState.lowerBound, "decided before anything writes a cicada. key")
        let phase = try XCTUnwrap(app.range(of: "menuBarManager.setIntroPhase(MenuBarIntro.phase())"))
        let setup = try XCTUnwrap(app.range(of: "menuBarManager.setup("))
        XCTAssertLessThan(phase.lowerBound, setup.lowerBound, "a waiting worm is never shown for a frame")
    }

    func testReduceMotionTurnsTheFlightIntoAFadeAndNothingElse() {
        let fly = MenuBarReveal.fly(from: CGRect(x: 1, y: 2, width: 3, height: 4))
        XCTAssertEqual(fly.resolved(reduceMotion: true), .fade)
        XCTAssertEqual(fly.resolved(reduceMotion: false), fly)
        XCTAssertEqual(MenuBarReveal.instant.resolved(reduceMotion: true), .instant)
        XCTAssertEqual(MenuBarReveal.instant.resolved(reduceMotion: false), .instant)
    }

    func testTheFlightLandsOnTheSpriteCentredInItsButton() {
        let landing = MenuBarFlight.centred(size: 18, in: CGRect(x: 1000, y: 875, width: 30, height: 24))
        XCTAssertEqual(landing, CGRect(x: 1006, y: 878, width: 18, height: 18))
        let screens = [CGRect(x: 0, y: 0, width: 1512, height: 949)]
        XCTAssertTrue(MenuBarFlight.landsOnMenuBar(CGRect(x: 1000, y: 925, width: 30, height: 24), screens: screens))
        // Seen live 2026-10-23: a full menu bar kept the item off screen while its frame still read as a rect.
        XCTAssertFalse(MenuBarFlight.landsOnMenuBar(CGRect(x: -6, y: -42, width: 30, height: 24), screens: screens))
        XCTAssertFalse(MenuBarFlight.landsOnMenuBar(CGRect(x: 700, y: 400, width: 30, height: 24), screens: screens),
                       "the middle of a screen is not the menu bar")
        XCTAssertGreaterThan(CicadaMotion.wormFlightDuration, CicadaMotion.maxDuration,
                             "a demonstration at reading pace, the dated DR-61 exception")
        XCTAssertLessThanOrEqual(CicadaMotion.wormFlightDuration, CicadaMotion.walkthroughGlide)
        XCTAssertEqual(CicadaMotion.wormRevealFadeDuration, CicadaMotion.reducedFadeDuration, "DR-66's short fade")
    }

    private func source(_ suffix: String) throws -> String {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("CicadaApp/" + suffix) })
        return try String(contentsOf: file, encoding: .utf8)
    }
}

/// The step's words, and the number it explains: the badge's own source.
final class MenuBarStepTests: XCTestCase {
    func testTheStepExplainsWhatTheBadgeReallyCounts() {
        XCTAssertEqual(Copy.MeetWorm.title, "Meet your bookworm")
        // Onboarding v3: the worm speaks for itself, and points at the real item on a rerun.
        XCTAssertEqual(Copy.MeetWorm.subline, "I'll live in your menu bar.")
        XCTAssertEqual(Copy.MeetWorm.sublineShown, "That's me, up in your menu bar.")
        XCTAssertEqual(Copy.MeetWorm.number, "My number counts conversations waiting to become memory.")
        XCTAssertEqual(Copy.MeetWorm.goesDown, "When I sleep, I read them and it goes down.")
        XCTAssertTrue(Copy.waitingForSleep(3).contains("conversations waiting"),
                      "the same noun the menu bar's tooltip uses")
        for line in [Copy.MeetWorm.title, Copy.MeetWorm.subline, Copy.MeetWorm.sublineShown, Copy.MeetWorm.number,
                     Copy.MeetWorm.goesDown] {
            for jargon in ["episode", "consolidat", "badge", "queue", "readable", "Sleep cycle"] {
                XCTAssertFalse(line.localizedCaseInsensitiveContains(jargon), "\(line) says \(jargon)")
            }
        }
    }

    /// The number is `StatusSnapshot.waitingForSleep` — what the badge draws (`deriveBookwormState`) — never the inbox.
    func testTheNumberIsTheBadgesOwnSourceNotTheInbox() throws {
        var snapshot = StatusSnapshot(
            sleep: .init(status: "idle", stage: 0, totalStages: 5, cycleId: nil, error: nil),
            inbox: .init(total: 190, byKind: [:]),
            episodes: .init(unprocessed: 9, lastIngestedAt: ISO8601DateFormatter().string(from: Date()), readable: 3),
            lastSleepAt: nil, nextSleepAt: nil)
        XCTAssertEqual(deriveBookwormState(snapshot, justFinishedAt: nil), .curious(count: 3))
        XCTAssertEqual(MenuBarStepModel.target(waiting: snapshot.waitingForSleep), 3)
        XCTAssertEqual(MenuBarStepModel.caption(waiting: snapshot.waitingForSleep), "3 waiting now")
        snapshot.episodes.readable = nil
        XCTAssertEqual(MenuBarStepModel.target(waiting: snapshot.waitingForSleep), 9, "an older backend's unprocessed")
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Onboarding/OnboardingView.swift")
        })
        let view = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(view.contains("MenuBarStep(waiting: store.status.value?.waitingForSleep"),
                      "the step reads the badge's number, never the inbox")
    }

    func testWithNothingWaitingItCountsAnExampleAndSaysSo() {
        for waiting in [nil, 0, -2] as [Int?] {
            XCTAssertEqual(MenuBarStepModel.target(waiting: waiting), MenuBarStepModel.exampleCount)
            XCTAssertEqual(MenuBarStepModel.caption(waiting: waiting), Copy.MeetWorm.example)
            XCTAssertTrue(MenuBarStepModel.isExample(waiting: waiting))
        }
        XCTAssertEqual(MenuBarStepModel.caption(waiting: 1_204), "1,204 waiting now".replacingOccurrences(
            of: ",", with: Locale.autoupdatingCurrent.groupingSeparator ?? ","))
    }

    func testTheCountGoesUpOneByOneThenInEvenJumpsAndAlwaysLandsOnItsNumber() {
        XCTAssertEqual(MenuBarStepModel.countSteps(to: 12), Array(1...12))
        XCTAssertEqual(MenuBarStepModel.countSteps(to: 1), [1])
        XCTAssertEqual(MenuBarStepModel.countSteps(to: 0), [])
        for target in [25, 99, 100, 133, 2_104] {
            let steps = MenuBarStepModel.countSteps(to: target)
            XCTAssertEqual(steps.last, target)
            XCTAssertLessThanOrEqual(steps.count, CicadaMotion.wormCountMaxSteps)
            XCTAssertEqual(steps, steps.sorted())
            XCTAssertEqual(Set(steps).count, steps.count, "strictly increasing")
            XCTAssertGreaterThanOrEqual(steps.first ?? 0, 1)
        }
    }

    /// One loop: nothing waiting, up to the number (held), Sleep's five dots, and round again.
    func testTheLoopShowsTheNumberGoingUpThenSleepTakingItAway() {
        let beats = MenuBarStepModel.beats(target: 12)
        XCTAssertEqual(beats.first?.state, .happy)
        XCTAssertEqual(beats.dropFirst().prefix(12).map(\.state), (1...12).map { BookwormState.curious(count: $0) })
        XCTAssertEqual(beats[12].hold, CicadaMotion.wormCountHold, "it holds on the number")
        XCTAssertEqual(beats.suffix(5).map(\.state), (1...5).map { BookwormState.sleeping(stage: $0) })
        XCTAssertTrue(beats.allSatisfy { $0.hold > 0 })
        XCTAssertEqual(MenuBarStepModel.still(target: 12), .curious(count: 12), "Reduce Motion holds on the number")
    }

    /// The worm is the menu bar's own sprite (the small sheet with its badge), at a whole number of points per pixel.
    func testTheBigWormIsTheMenuBarsSpriteScaledByWholePixels() {
        let size = BookwormSize.resolve(pointSize: MenuBarStep.wormPointSize, uiScale: 1, latticeCell: nil, set: .small)
        XCTAssertEqual(size.set, .small)
        XCTAssertEqual(size.pixelScale, 8)
        XCTAssertEqual(size.size, CGSize(width: 144, height: 144))
        XCTAssertEqual(BookwormSize.resolve(pointSize: 144, uiScale: 1, latticeCell: nil).set, .room,
                       "without the override a big worm is the room sheet")
        let zoomed = BookwormSize.resolve(pointSize: MenuBarStep.wormPointSize, uiScale: 1.4, latticeCell: nil, set: .small)
        XCTAssertEqual(zoomed.pixelScale, zoomed.pixelScale.rounded())
    }
}
