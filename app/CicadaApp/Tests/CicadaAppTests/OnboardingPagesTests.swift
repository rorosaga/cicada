import SwiftUI
import XCTest
@testable import CicadaApp

/// Onboarding v2 (2026-10-22) — six steps since *Meet your bookworm* (owner 2026-10-23), one frame, a visible Skip on
/// the working steps and the worm's, and the keyboard never animates.
final class OnboardingPagesTests: XCTestCase {
    func testSixStepsInTheFlowsOrderWithTheSplitFrameAndSkipOnTheWorkingSteps() {
        XCTAssertEqual(OnboardingPage.allCases, [.welcome, .intelligence, .agents, .sources, .menuBar, .done])
        XCTAssertEqual(OnboardingPage.allCases.map(\.step), [1, 2, 3, 4, 5, 6])
        XCTAssertEqual(OnboardingPage.stepCount, OnboardingPage.allCases.count)
        XCTAssertEqual(OnboardingPage.welcome.next, .intelligence)
        XCTAssertEqual(OnboardingPage.sources.next, .menuBar, "the worm's step follows Sources: it counts what came in")
        XCTAssertEqual(OnboardingPage.menuBar.next, .done)
        XCTAssertEqual(OnboardingPage.done.previous, .menuBar)
        XCTAssertNil(OnboardingPage.done.next)
        XCTAssertEqual(OnboardingPage.allCases.filter(\.isSplit), [.intelligence, .agents, .sources])
        XCTAssertEqual(OnboardingPage.allCases.filter(\.skippable), [.intelligence, .agents, .sources, .menuBar])
    }

    /// Hyrum mode B — every step name either flow could have stored maps to a step that exists, and each new step
    /// round-trips through its stored word.
    func testEveryStoredStepNameMapsToAStepThatExists() {
        for page in OnboardingPage.allCases { XCTAssertEqual(OnboardingPage(stored: page.storedName), page) }
        XCTAssertEqual(OnboardingPage(stored: "import"), .sources)
        XCTAssertEqual(OnboardingPage(stored: "whoReads"), .intelligence)
        XCTAssertEqual(OnboardingPage(stored: "skills"), .sources)
        XCTAssertEqual(OnboardingPage(stored: "keepRunning"), .done)
        XCTAssertEqual(OnboardingPage(stored: "ready"), .done)
        XCTAssertEqual(OnboardingPage(stored: "menuBar"), .menuBar)
        XCTAssertEqual(OnboardingPage(stored: "done"), .done, "a step stored before the worm's step still lands on Done")
        XCTAssertNil(OnboardingPage(stored: "3"), "a raw number is never a step")
        XCTAssertNil(OnboardingPage(stored: ""))
    }

    /// Owner 2026-10-16 — the study room is onboarding's one illustration: the worm's mood says what each step is about,
    /// and the room is drawn at a whole number of points per cell (never resampled), up to 3 in the pane and 4 over the
    /// Welcome's card.
    func testTheRoomIsOnboardingsIllustrationAtWholePoints() {
        XCTAssertEqual(OnboardingPage.welcome.roomMood, .awake)
        XCTAssertEqual(OnboardingPage.intelligence.roomMood, .reading)
        XCTAssertEqual(OnboardingPage.sources.roomMood, .reading)
        XCTAssertEqual(OnboardingPage.agents.roomMood, .happy)
        XCTAssertEqual(OnboardingPage.done.roomMood, .happy)
        XCTAssertEqual(OnboardingRoomLayout.paneCell(paneWidth: 540), 3, "480 × 192 in the full pane")
        XCTAssertEqual(OnboardingRoomLayout.paneCell(paneWidth: 380), 2)
        XCTAssertEqual(OnboardingRoomLayout.paneCell(paneWidth: 240), 1)
        XCTAssertEqual(OnboardingRoomLayout.cardCell(cardWidth: 640), 4, "640 × 256 over the 640 pt card")
        XCTAssertEqual(OnboardingRoomLayout.cardCell(cardWidth: 2000), 4)
        XCTAssertEqual(OnboardingRoomLayout.cardCell(cardWidth: 0), 1, "a zero width never traps")
        for width in stride(from: CGFloat(0), through: 900, by: 37) {
            let cell = OnboardingRoomLayout.cardCell(cardWidth: width)
            XCTAssertEqual(cell, cell.rounded(), "\(width): a whole number of points per cell")
            XCTAssertTrue(width < 160 || CGFloat(RoomLattice.cols) * cell <= width, "\(width): the room fits")
        }
    }

    /// Paint is retired from onboarding: the frame draws the room, never a painting (owner 2026-10-16).
    func testOnboardingDrawsTheRoomNotAPainting() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first {
            $0.path.hasSuffix("Views/Onboarding/OnboardingView.swift")
        })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("OnboardingRoom(mood: page.roomMood"))
        XCTAssertFalse(text.contains("PaintedScene") || text.contains("OnboardingPane("))
    }

    func testTheKeyboardNeverAnimatesAndThePointerRidesTheDrawer() {
        XCTAssertNil(OnboardingNav.animation(.keyboard, reduceMotion: false), "DR-60")
        XCTAssertNotNil(OnboardingNav.animation(.pointer, reduceMotion: false))
        XCTAssertNil(OnboardingNav.animation(.pointer, reduceMotion: true), "width is movement (CicadaMotion.columns)")
    }

    func testASegmentJumpsOnlyToAPageReachedAndNeverPastGetStarted() {
        XCTAssertTrue(OnboardingNav.canJump(to: .intelligence, furthest: .sources, ownerSaved: true))
        XCTAssertFalse(OnboardingNav.canJump(to: .done, furthest: .sources, ownerSaved: true))
        XCTAssertFalse(OnboardingNav.canJump(to: .intelligence, furthest: .intelligence, ownerSaved: false), "R-OB2")
        XCTAssertTrue(OnboardingNav.canJump(to: .welcome, furthest: .agents, ownerSaved: false))
    }

    /// R-OB1 — the painting gives way before the column does, and goes rather than become a sliver.
    func testThePaneShrinksThenGoesAndTheColumnNeverDropsBelowItsMinimum() {
        XCTAssertEqual(OnboardingLayout.paneWidth(windowWidth: 1440, scale: 1), 540)
        XCTAssertEqual(OnboardingLayout.paneWidth(windowWidth: 1200, scale: 1), 540)
        XCTAssertEqual(OnboardingLayout.paneWidth(windowWidth: 1000, scale: 1), 380)
        XCTAssertEqual(OnboardingLayout.paneWidth(windowWidth: 800, scale: 1), 0)
        for scale in stride(from: CGFloat(0.8), through: 1.4001, by: 0.1) {
            for width in [CGFloat(800), 1000, 1200, 1440, 1800] {
                let pane = OnboardingLayout.paneWidth(windowWidth: width, scale: scale)
                XCTAssertTrue(pane == 0 || width - pane >= OnboardingLayout.minColumn * scale - 0.5, "\(width)@\(scale)")
                XCTAssertLessThanOrEqual(OnboardingLayout.cardWidth(windowWidth: width, scale: scale), width - 32 * scale)
            }
        }
        XCTAssertEqual(OnboardingLayout.paneWidth(windowWidth: 0, scale: 0), 0, "a zero width never traps")
    }
}
