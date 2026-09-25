import SwiftUI
import XCTest
@testable import CicadaApp

/// R-OB1, R-OB3 — six steps, one frame, and the keyboard never animates.
final class OnboardingPagesTests: XCTestCase {
    func testSixStepsInTheFlowsOrderWithTheSplitFrameOnTheWorkingPages() {
        XCTAssertEqual(OnboardingPage.allCases.map(\.step), [1, 2, 3, 4, 5, 6])
        XCTAssertEqual(OnboardingPage.welcome.next, .import)
        XCTAssertNil(OnboardingPage.ready.next)
        XCTAssertEqual(OnboardingPage.allCases.filter(\.isSplit), [.import, .agents, .whoReads, .keepRunning])
        XCTAssertEqual(OnboardingPage.agents.pane, .agents)
        XCTAssertNil(OnboardingPage.welcome.pane, "Welcome and You're set are the whole painting")
    }

    func testTheKeyboardNeverAnimatesAndThePointerRidesTheDrawer() {
        XCTAssertNil(OnboardingNav.animation(.keyboard, reduceMotion: false), "DR-60")
        XCTAssertNotNil(OnboardingNav.animation(.pointer, reduceMotion: false))
        XCTAssertNil(OnboardingNav.animation(.pointer, reduceMotion: true), "width is movement (CicadaMotion.columns)")
    }

    func testASegmentJumpsOnlyToAPageReachedAndNeverPastGetStarted() {
        XCTAssertTrue(OnboardingNav.canJump(to: .import, furthest: .whoReads, ownerSaved: true))
        XCTAssertFalse(OnboardingNav.canJump(to: .keepRunning, furthest: .whoReads, ownerSaved: true))
        XCTAssertFalse(OnboardingNav.canJump(to: .import, furthest: .import, ownerSaved: false), "R-OB2")
        XCTAssertTrue(OnboardingNav.canJump(to: .welcome, furthest: .import, ownerSaved: false))
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

    func testImportShowsTwoColumnsOnlyWhenTheyFit() {
        XCTAssertEqual(OnboardingLayout.importColumns(columnWidth: 772, scale: 1), 2, "1440 × 900, F-02")
        XCTAssertEqual(OnboardingLayout.importColumns(columnWidth: 532, scale: 1), 1, "1200 × 800")
        XCTAssertEqual(OnboardingLayout.importColumns(columnWidth: 772, scale: 1.4), 1)
    }
}
