import XCTest
import SwiftUI
@testable import CicadaApp

/// The owner's page in a wide card drew its main column off the left edge: belief text clipped, only the rows' clocks
/// showing. A flow (contributors, tags, related, a belief's footer) reported its widest child's ideal width even when
/// that was wider than it was offered. It may not happen to any row of the card — an article line included: every row
/// stays inside the card at every width.
final class CardRowsStayInsideTests: XCTestCase {
    private struct Frames: PreferenceKey {
        static let defaultValue: [String: CGRect] = [:]
        static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
            value.merge(nextValue()) { $1 }
        }
    }

    private final class Box { var frames: [String: CGRect] = [:] }

    @MainActor
    private func frames(width: CGFloat) throws -> [String: CGRect] {
        let box = Box()
        func tagged(_ name: String) -> some View {
            GeometryReader { g in
                Color.clear.preference(key: Frames.self, value: [name: g.frame(in: .named("card"))])
            }
        }
        let wide = String(repeating: "related-page-with-a-long-name ", count: 8)
        let main = VStack(alignment: .leading, spacing: 12) {
            Text("A belief the person can read.").frame(maxWidth: .infinity, alignment: .leading)
                .background(tagged("row"))
            FlowLayout(spacing: 6) { Text(wide).lineLimit(1); Text("short") }
                .background(tagged("flow"))
            ClaimFooterFlow(spacing: 6) { Text(wide).lineLimit(1) }
                .background(tagged("footer"))
        }
        let line = WikiArticle.build("- " + wide + " [[a-very-long-wikilinked-page-name-that-has-to-wrap]]").rows[0]
        let view = VStack(alignment: .leading, spacing: 12) {
            main
            WikiRowView(row: line, onSource: { _ in }).background(tagged("article"))
        }
            .frame(width: width)
            .coordinateSpace(name: "card")
            .onPreferenceChange(Frames.self) { box.frames = $0 }
        let renderer = ImageRenderer(content: view)
        renderer.proposedSize = ProposedViewSize(width: width, height: nil)
        _ = try XCTUnwrap(renderer.nsImage)
        return box.frames
    }

    @MainActor
    func testEveryRowStaysInsideTheCardWideOrNarrow() throws {
        CicadaTheme.uiScale = 1
        for width in [GraphColumns.entityMax - 48, ColumnLayout.questionMaxWidth] {
            let f = try frames(width: width)
            XCTAssertEqual(Set(f.keys), ["row", "flow", "footer", "article"], "\(width)")
            for (name, rect) in f {
                XCTAssertGreaterThanOrEqual(rect.minX, -0.5, "\(name) at \(width): \(rect)")
                XCTAssertLessThanOrEqual(rect.maxX, width + 0.5, "\(name) at \(width): \(rect)")
            }
        }
    }
}
