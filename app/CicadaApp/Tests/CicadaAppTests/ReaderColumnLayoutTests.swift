import SwiftUI
import XCTest
@testable import CicadaApp

/// R-DI6 / DR-31 — the Reader is never pushed off-window and never wants more than its column. The
/// clipped-text bug had two possible roots — a rigid child inside the Reader, or a page beside it
/// that would not give way — and both are measured here.
@MainActor
final class ReaderColumnLayoutTests: XCTestCase {
    override func tearDown() {
        CicadaTheme.uiScale = 1.0
        CicadaTheme.mode = .dark
        super.tearDown()
    }

    /// A conversation built to break a layout: an unbroken 300-character token, a long speaker
    /// line, a stale banner's worth of words, a cited span that runs across the token.
    private func hostileBlocks() -> [ReaderBlock] {
        let token = "https://example.com/" + String(repeating: "x", count: 300)
        let text = "user: can we stop? \(token)\nassistant: Yes. We moved the index to sqlite-vec for alpha-project."
        let doc = EpisodeText(episode: "ep_2026-09-03_004", text: text, title: String(repeating: "Long title ", count: 12),
                              timestamp: "2026-09-03T10:00:00+00:00", harness: "claude-code", origin: "claude-code",
                              turns: [EpisodeTurn(index: 1, start: 0, contentStart: 6, end: 19 + token.count, role: "user", marker: "user"),
                                      EpisodeTurn(index: 2, start: 20 + token.count, contentStart: 31 + token.count,
                                                  end: text.unicodeScalars.count, role: "assistant", marker: "assistant")])
        return ReaderLayout.blocks(doc: doc, scalars: ScalarText(doc.text), focus: 10..<60, focusStyle: .focus,
                                   others: [70..<90])
    }

    func testTheReadersTextNeverWantsMoreThanItsColumn() throws {
        // An agent turn's speaker line wears its real mark (DR-52) — an `OriginMark` over a
        // `LogoImage`, which reads the `Store` from the environment as it does in the app, where the
        // Store is always an ancestor (the same seam as `InboxFocusCardFitTests`).
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        for mode in [AppColorScheme.dark, .light] {
            CicadaTheme.mode = mode
            for scale in [0.8, 1.0, 1.4] {
                CicadaTheme.uiScale = scale
                for column: CGFloat in [360, 420] {
                    let width = column * CGFloat(scale)
                    let renderer = ImageRenderer(content: ReaderTurnsView(blocks: hostileBlocks(), landingTurn: 2, revealed: true)
                        .environment(store))
                    renderer.proposedSize = ProposedViewSize(width: width, height: nil)
                    let size = try XCTUnwrap(renderer.nsImage).size
                    XCTAssertLessThanOrEqual(size.width, width + 0.5, "\(column) × \(scale): \(size.width)")
                }
            }
        }
    }

    /// The host decides the Reader's width first; a page with a rigid 2000 pt child is clipped to the
    /// rest, never the Reader past the window's edge.
    func testAPageThatWillNotGiveWayNeverPushesTheReaderOffWindow() throws {
        for (content, reader) in [(CGFloat(1144), CGFloat(360)), (1384, 420)] {
            let host = ShellReaderHost(showsReader: true, navWidth: 56) {
                Color.clear.frame(width: 2000, height: 10)
            } reader: {
                Color.clear
            }
            let renderer = ImageRenderer(content: host)
            renderer.proposedSize = ProposedViewSize(width: content, height: 800)
            XCTAssertEqual(try XCTUnwrap(renderer.nsImage).size.width, content, accuracy: 0.5)
            let plan = ColumnLayout.plan(contentWidth: content, navWidth: 56, scale: 1, hasList: false,
                                         hasDetail: true, hasTrailing: true)
            XCTAssertEqual(plan.trailing, reader)
        }
    }
}
