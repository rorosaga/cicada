import SwiftUI
import XCTest
@testable import CicadaApp

/// `TopBarControls` carries two visibility flags and a `help` selector.
/// G125 Task 7 added them so the Sleep page could hide the Sleep/Upload pair
/// (R10 — the one Consolidate control moved into the study list's footer)
/// while keeping its `?` button, pointed at *How Cicada sleeps*.
///
/// Track P R1 finished the audit: the DEFAULT is now "`?` only". A cycle
/// starts on the Sleep page or from the menu-bar bookworm, so a global Sleep
/// button had nothing left to do. It is executed as a default flip rather
/// than five call-site edits because a signature change would conflict at
/// merge and a default flip cannot, and the flags survive as a documented
/// opt-in seam for a page that later earns one back.
///
/// Final review F1 walked the Upload half back one page: the Feed opts in
/// again, because "a one-shot import lives behind the `+`" is only true of
/// `UploadMode.conversations` — `UploadMode.project` (an export into a
/// chosen or newly created bank) has no `AddSourceTile`, and `UploadOverlay`
/// is the only writer of `Store.intakeInFlight` (G125 R2). The last test
/// below is what makes that opt-in a rule instead of a habit.
final class TopBarControlsTests: XCTestCase {

    /// Track P R1 — the audit resolved by REMOVING, and the removal is a
    /// default, not five edits.
    func testFlagsDefaultToHidingBothButtonsAndTheAboutPopover() {
        let view = TopBarControls(selectedTab: .constant(.graph), showUploadOverlay: .constant(false))
        XCTAssertFalse(view.showsSleep, "Sleep starts on the Sleep page (G125 R10), never from a global button")
        XCTAssertFalse(view.showsUpload, "every page but the Feed inherits \"? only\" (F1)")
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

    /// Final review F1 — a source lint, the same shape as
    /// `FontLiteralLintTests`, because the defect it guards is invisible to a
    /// behavior test: flipping a DEFAULT silently strands a call site, and
    /// SwiftUI gives no seam to assert "this view tree contains an Upload
    /// button". `UploadOverlay` is the only route to `UploadMode.project`
    /// and the only writer of `Store.intakeInFlight`, so if this assertion
    /// ever fails, both are unreachable from the running app.
    func testFeedIsTheOneCallSiteThatOptsBackIntoUpload() throws {
        // …/Tests/CicadaAppTests/<this file> → …/Sources/CicadaApp
        let feed = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("Sources/CicadaApp/Views/Feed/FeedView.swift")
        let text = try String(contentsOf: feed, encoding: .utf8)
        XCTAssertTrue(
            text.contains("showsUpload: true"),
            "FeedView must pass showsUpload: true — it is the only presenter of UploadOverlay, "
            + "which is the only route to UploadMode.project and the only writer of Store.intakeInFlight."
        )
        XCTAssertTrue(text.contains("UploadOverlay(isPresented:"), "…and it must still present it")
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
