import SwiftUI
import XCTest
@testable import CicadaApp

/// The page's `?` lives in the titlebar, one per window, and answers for the visible page
/// (DR-23, R-DS18). It replaced `TopBarControls`, which four pages floated at four slightly
/// different offsets and which carried two flags that no longer did anything.
///
/// Track P R1 finished the audit: a page offers the `?` and nothing else — a cycle starts on
/// the Sleep page or from the menu-bar bookworm. Track I T5 (R-IA22) retired the Upload button
/// with `UploadOverlay`: every file arrives through the one `IntakeRouter`. Both rules survive
/// the move as lints below.
final class TitlebarHelpTests: XCTestCase {

    /// Track I T5 (R-IA22) — the Upload button retired with `UploadOverlay`; the one intake
    /// owns `Store.intakeInFlight`. Nothing may opt back into it.
    func testNoCallSiteOptsIntoTheRetiredUploadButton() throws {
        let sources = try ThemeTokenTests.swiftSources()
        XCTAssertFalse(sources.contains { $0.lastPathComponent == "UploadOverlay.swift" })
        for file in sources {
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains("showsUpload: true"), file.lastPathComponent)
        }
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

    /// Track P R1 survives the move: no page offers a global Sleep or Upload button — the `?`
    /// is the titlebar's only page control (R-DS18).
    func testTheTitlebarHelpIsTheOnlyPageControl() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Shell/TitlebarHelp.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertFalse(text.contains("triggerManually"))
        XCTAssertFalse(text.contains("showsSleep"))
    }
}
