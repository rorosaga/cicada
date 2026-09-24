import SwiftUI
import XCTest
@testable import CicadaApp

/// DR-43 / R-DI21 — every variant renders inside the focus card, and nothing in it is rigid: at the
/// question column's floor (440) and its cap (720), at 1× and 1.4×, the card never wants more width
/// than it is given (a rigid child is how the Reader's text clipped). The demo bank has no removal,
/// divergence, normalization or informational item; this is where they are reached.
@MainActor
final class InboxFocusCardFitTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    private static let cause = #","cause":{"episodeId":"ep_2026-08-25_001","timestamp":"2026-08-25T10:00:00Z","harness":"claude-code","conversationTitle":"Alpha project storage: a very long conversation title that has to truncate somewhere","excerpt":"Discussed swapping alpha-project's flat-CSV storage for sqlite-vec so anomaly lookups do not need a full scan; https://example.com/an-unbroken-url-that-is-far-longer-than-any-column-could-ever-be-at-this-size","mentionOffsets":[[10,70]],"start":0,"tier":"claim","spanKind":"asserted"}"#
    private static let options = #","options":[{"key":"a","label":"Tool Example A","description":"8 months ago · last mentioned Jan 5","ageDays":240},{"key":"b","label":"Tool Example B","description":"4 weeks ago · last mentioned Aug 25","ageDays":28,"recommended":true}]"#

    static let fixtures: [String: String] = [
        "conflict": #"{"id":"1","kind":"conflict","requiredInput":"choice","title":"What does alpha-project use now?","allowOther":true,"allowDefer":true,"hint":"You said https://example.com/alpha-project is where to check","extractorModel":"gpt-5.4-mini","extractorConfidence":0.85"# + options + cause + "}",
        "informational": #"{"id":"1","kind":"conflict","requiredInput":"choice","title":"What does alpha-project use?","predicate":"uses","informational":true"# + options + "}",
        "decay": #"{"id":"1","kind":"decay","requiredInput":"choice","title":"Still tracking Beta Project?","allowDefer":true,"options":[{"key":"archive","label":"Archive","description":"Last mentioned 3 months ago · move it to the archive; it comes back on the next mention"},{"key":"keep","label":"Keep active","description":"Last mentioned 3 months ago · still relevant"}]}"#,
        "legacyDecay": #"{"id":"1","kind":"decay","requiredInput":"choice","title":"No recent mentions of Beta Project"}"#,
        "freeText": #"{"id":"1","kind":"clarification","requiredInput":"freetext","title":"Who is bob-example?","allowOther":true,"allowDefer":true}"#,
        "merge": #"{"id":"1","kind":"merge_suggestion","requiredInput":"merge","title":"Tool Example A (CLI)","entityName":"Tool Example A (CLI)","mergeTargetHint":"tool-example-a","suggestedClassification":"tool"}"#,
        "removal": #"{"id":"1","kind":"removal","requiredInput":"choice","title":"Removed from Chrome","channel":"chrome-bookmarks","options":[{"key":"keep","label":"Keep it"},{"key":"remove","label":"Archive it"}]}"#,
        "divergence": #"{"id":"1","kind":"divergence","requiredInput":"choice","title":"Keep your statement?","allowDefer":true"# + options + "}",
        "normalization": #"{"id":"1","kind":"normalization","requiredInput":"choice","title":"Was this fold right?","options":[{"key":"correct","label":"Correct fold"},{"key":"wrong","label":"Wrong fold"}]}"#,
        "followup": #"{"id":"1","kind":"followup","requiredInput":"choice","title":"t","question":"“Wire the lab cluster” — last heard 3 weeks ago. How did it go?","allowOther":true,"options":[{"key":"done","label":"Done","description":"Finished — dated today"},{"key":"still","label":"Still going"},{"key":"stopped","label":"Stopped"},{"key":"didnt","label":"That didn't happen"},{"key":"remind_later","label":"Not now — ask again in 30 days"}]}"#,
        "dismissOnly": #"{"id":"1","kind":"conflict","requiredInput":"none","title":"Nothing to pick"}"#,
    ]

    func testEveryVariantFitsItsColumnAtEveryZoomInBothThemes() throws {
        // The source line's real mark (DR-52) is a `LogoImage`, which reads the `Store` from the
        // environment as it does in the app, where the Store is always an ancestor.
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for scale in [1.0, 1.4] {
                CicadaTheme.uiScale = scale
                for width: CGFloat in [440, 720] {
                    let proposed = width * CGFloat(scale)
                    for (name, json) in Self.fixtures {
                        let item = try JSONDecoder().decode(InboxItem.self, from: Data(json.utf8))
                        let renderer = ImageRenderer(content: InboxFocusCard(item: item, padding: 28, onClose: {}) { _ in }
                            .environment(store))
                        renderer.proposedSize = ProposedViewSize(width: proposed, height: nil)
                        let size = try XCTUnwrap(renderer.nsImage, name).size
                        XCTAssertLessThanOrEqual(size.width, proposed + 0.5, "\(name) at \(width) × \(scale) wants \(size.width)")
                        XCTAssertGreaterThan(size.height, 80, "\(name) rendered nothing")
                    }
                }
            }
        }
    }
}
