import SwiftUI
import XCTest
@testable import CicadaApp

/// G125 Task 7 — `TopBarControls` grows two visibility flags and a `help`
/// selector so the Sleep page can hide the Sleep/Upload pair (R10 — the one
/// Consolidate control moved into the study list's footer) while keeping its
/// `?` button, and swap the popover it opens for *How Cicada sleeps*.
/// Every OTHER call site (`GraphContainerView`, `TopicsView`, `FeedView`)
/// passes neither new argument, so their defaults must keep showing both
/// buttons with the original "About these actions" popover.
final class TopBarControlsTests: XCTestCase {

    func testFlagsDefaultToShowingBothButtonsAndTheActionsPopover() {
        let view = TopBarControls(selectedTab: .constant(.sleep), showUploadOverlay: .constant(false))
        XCTAssertTrue(view.showsSleep)
        XCTAssertTrue(view.showsUpload)
        XCTAssertEqual(view.help, .actions)
    }

    func testSleepPageCanHideBothButtonsAndAskForTheSleepExplainer() {
        let view = TopBarControls(
            selectedTab: .constant(.sleep),
            showUploadOverlay: .constant(false),
            showsSleep: false,
            showsUpload: false,
            help: .howSleepWorks
        )
        XCTAssertFalse(view.showsSleep)
        XCTAssertFalse(view.showsUpload)
        XCTAssertEqual(view.help, .howSleepWorks)
    }

    /// Exhaustive switch — a compile-time guarantee that a THIRD case can't
    /// be added without every call site (and this test) being revisited.
    func testHelpContentIsExactlyTwoCases() {
        for content: HelpContent in [.actions, .howSleepWorks] {
            switch content {
            case .actions, .howSleepWorks: break
            }
        }
    }
}
