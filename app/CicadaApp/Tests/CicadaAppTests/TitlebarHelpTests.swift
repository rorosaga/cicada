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

    /// Exhaustive switch — a compile-time guarantee that a new case can't
    /// be added without every call site (and this test) being revisited.
    /// The pages answer for themselves as each D track lands (R-DG6, R-DL8).
    func testHelpContentCasesAreExhaustive() {
        for content: HelpContent in [.aboutCicada, .howSleepWorks, .inbox, .graph, .clusters, .feed, .sources, .projects] {
            switch content {
            case .aboutCicada, .howSleepWorks, .inbox, .graph, .clusters, .feed, .sources, .projects: break
            }
        }
    }

    /// R-DI17 / DR-25 — the Inbox's old subtitle and its keys live behind its `?`.
    func testTheInboxAnswersForItself() {
        XCTAssertEqual(HelpContent.page(.inbox), .inbox)
        XCTAssertEqual(HelpContent.page(.clusters), .clusters)
        XCTAssertEqual(HelpContent.page(.feed), .feed)
        XCTAssertEqual(HelpContent.page(.sources), .sources)
        XCTAssertEqual(HelpContent.page(.sleep), .howSleepWorks)
        XCTAssertEqual(HelpContent.page(.graph), .graph)
        XCTAssertEqual(HelpContent.page(.projects), .projects)
        XCTAssertEqual(ListHelp.projects.keys.map(\.key), ["⌘F", "↑ ↓", "⏎", "← →", "L", "M", "D", "Esc"])
        XCTAssertEqual(InboxHelp.keys.map(\.key), ["1–9", "↑ ↓", "⏎", "O", "L", "⌘Z", "Esc", "Tab"])
        // R-DG6 — the Graph's `?` says its keys and gestures in words.
        XCTAssertEqual(GraphHelp.keys.map(\.key), ["⌘F", "⌘K", "Esc", "⌘[", "Shift"])
        XCTAssertEqual(GraphHelp.gestures.map(\.key), ["Double-click", "Click empty space"])
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
