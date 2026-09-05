import SwiftUI
import XCTest
@testable import CicadaApp

/// `TopBarControls` carries two visibility flags and a `help` selector.
/// G125 Task 7 added them so the Sleep page could hide the Sleep/Upload pair
/// (R10 — the one Consolidate control moved into the study list's footer)
/// while keeping its `?` button, pointed at *How Cicada sleeps*.
///
/// Track P R1 finished the audit: the DEFAULT is now "`?` only". A cycle
/// starts on the Sleep page or from the menu-bar bookworm, and a one-shot
/// import lives behind the Feed's `+` (the G126 rule), so a global Sleep or
/// Upload button had nothing left to do. It is executed as a default flip
/// rather than five call-site edits because `Views/Sleep/SleepView.swift`
/// and `Views/Feed/FeedView.swift` are owned by other tracks this round —
/// a signature change would conflict at merge, a default flip cannot, and
/// the flags survive as a documented opt-in seam for a page that later
/// earns one back.
final class TopBarControlsTests: XCTestCase {

    /// Track P R1 — the audit resolved by REMOVING, and the removal is a
    /// default, not five edits.
    func testFlagsDefaultToHidingBothButtonsAndTheAboutPopover() {
        let view = TopBarControls(selectedTab: .constant(.graph), showUploadOverlay: .constant(false))
        XCTAssertFalse(view.showsSleep, "Sleep starts on the Sleep page (G125 R10), never from a global button")
        XCTAssertFalse(view.showsUpload, "a one-shot import lives behind the Feed's + (G126 rule)")
        XCTAssertEqual(view.help, .aboutCicada)
    }

    /// The Sleep page's explicit call site is unchanged by the default flip —
    /// it still says what it means, and still asks for its own popover.
    func testSleepPageStillAsksForTheSleepExplainerExplicitly() {
        let view = TopBarControls(
            selectedTab: .constant(.sleep),
            showUploadOverlay: .constant(false),
            showsSleep: false,
            showsUpload: false,
            help: .howSleepWorks
        )
        XCTAssertEqual(view.help, .howSleepWorks)
    }

    /// Exhaustive switch — a compile-time guarantee that a THIRD case can't
    /// be added without every call site (and this test) being revisited.
    func testHelpContentIsExactlyTwoCases() {
        for content: HelpContent in [.aboutCicada, .howSleepWorks] {
            switch content {
            case .aboutCicada, .howSleepWorks: break
            }
        }
    }
}
