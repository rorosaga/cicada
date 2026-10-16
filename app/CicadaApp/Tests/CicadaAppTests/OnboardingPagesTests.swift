import SwiftUI
import XCTest
@testable import CicadaApp

/// R-OB1, R-OB3 — seven steps (the skills step joined after Agents, 2026-10-15), one frame, and the keyboard never
/// animates.
final class OnboardingPagesTests: XCTestCase {
    func testSevenStepsInTheFlowsOrderWithTheSplitFrameOnTheWorkingPages() {
        XCTAssertEqual(OnboardingPage.allCases.map(\.step), [1, 2, 3, 4, 5, 6, 7])
        XCTAssertEqual(OnboardingPage.stepCount, OnboardingPage.allCases.count)
        XCTAssertEqual(OnboardingPage.welcome.next, .import)
        XCTAssertEqual(OnboardingPage.agents.next, .skills)
        XCTAssertEqual(OnboardingPage.skills.next, .whoReads)
        XCTAssertNil(OnboardingPage.ready.next)
        XCTAssertEqual(OnboardingPage.allCases.filter(\.isSplit), [.import, .agents, .skills, .whoReads, .keepRunning])
    }

    /// Owner 2026-10-16 — the study room is onboarding's one illustration: the worm's mood says what each step is about,
    /// and the room is drawn at a whole number of points per cell (never resampled), up to 3 in the pane and 4 over the
    /// Welcome's card.
    func testTheRoomIsOnboardingsIllustrationAtWholePoints() {
        XCTAssertEqual(OnboardingPage.welcome.roomMood, .awake)
        XCTAssertEqual(OnboardingPage.import.roomMood, .reading)
        XCTAssertEqual(OnboardingPage.agents.roomMood, OnboardingPage.skills.roomMood, "the skills are the agents'")
        XCTAssertEqual(OnboardingPage.keepRunning.roomMood, .sleeping(stage: 1))
        XCTAssertEqual(OnboardingPage.ready.roomMood, .happy)
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

    /// F-02 live pass — the privacy banner is never wider than the flow's column and never cuts its sentence: at the
    /// 1200 × 800 column, at every zoom, it fits; squeezed to a sliver it grows taller (it wraps) instead of staying
    /// one clipped line.
    @MainActor
    func testThePrivacyBannerFitsTheColumnAndWrapsRatherThanTruncates() throws {
        let saved = CicadaTheme.uiScale
        defer { CicadaTheme.uiScale = saved }
        for scale in [1.0, 1.2, 1.4] {
            CicadaTheme.uiScale = scale
            let s = CGFloat(scale)
            let column = 1200 - OnboardingLayout.paneWidth(windowWidth: 1200, scale: s)
                - 2 * OnboardingLayout.columnPadding * s
            func rendered(_ width: CGFloat) throws -> CGSize {
                let renderer = ImageRenderer(content: ImportPrivacyBanner(memoryRoot: "/tmp"))
                renderer.proposedSize = ProposedViewSize(width: width, height: nil)
                return try XCTUnwrap(renderer.nsImage).size
            }
            let atColumn = try rendered(column)
            let squeezed = try rendered(260 * s)
            XCTAssertLessThanOrEqual(atColumn.width, column + 0.5, "\(scale): \(atColumn.width) > \(column)")
            XCTAssertLessThanOrEqual(squeezed.width, 260 * s + 0.5, "\(scale)")
            XCTAssertGreaterThan(squeezed.height, atColumn.height, "\(scale): a narrow banner wraps, never truncates")
            if scale == 1.0 {
                // The live pass's column: title and sentence one line each, Show in Finder trailing — one row, as
                // tall as the button and the banner's padding (the old layout wrapped the title to three lines).
                XCTAssertLessThanOrEqual(atColumn.height, TextButton.height + 2 * 12 + 0.5, "\(atColumn.height)")
            }
        }
    }
}
