import XCTest
import SwiftUI
@testable import CicadaApp

/// The owner's page in a wide card drew its main column off the left edge: belief text clipped, only the rows' clocks
/// showing. A fixed-width column centres a child that is wider than it, and a flow (contributors, tags, related, a
/// belief's footer) reported its widest child's ideal width even when that was wider than it was offered. Neither may
/// happen: every row stays inside the card at every width.
final class PersonColumnsTests: XCTestCase {
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
        let view = PersonColumns(main: main, aside: Color.clear.frame(height: 40).background(tagged("aside")))
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
        for width in [GraphColumns.entityMax - 48, 992] {
            let f = try frames(width: width)
            XCTAssertEqual(Set(f.keys), ["row", "flow", "footer", "aside"], "\(width)")
            for (name, rect) in f {
                XCTAssertGreaterThanOrEqual(rect.minX, -0.5, "\(name) at \(width): \(rect)")
                XCTAssertLessThanOrEqual(rect.maxX, width + 0.5, "\(name) at \(width): \(rect)")
            }
        }
    }

    @MainActor
    func testWideCardsGetTwoColumnsAndNarrowOnesStack() throws {
        CicadaTheme.uiScale = 1
        let wide = try frames(width: 992)
        XCTAssertLessThan(try XCTUnwrap(wide["row"]).maxX, try XCTUnwrap(wide["aside"]).minX, "side by side")
        let narrow = try frames(width: 512)
        XCTAssertGreaterThan(try XCTUnwrap(narrow["aside"]).minY, try XCTUnwrap(narrow["row"]).maxY, "stacked")
    }
}
