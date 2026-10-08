import XCTest
import SwiftUI
@testable import CicadaApp

/// The owner clicked a person's two-line Summary and the full text drew over the picture line and the facts strip,
/// with a selection highlight on top. A selectable `Text` is an AppKit `SelectionTextField`; clicking one opens a field
/// editor that shows ALL of its text at its own height, outside SwiftUI's layout. So no selectable text in an entity
/// card's header may be cut short in the frame it was laid out in — it either shows all of itself or is not selectable.
final class HeaderOverlapTests: XCTestCase {
    private static func fields(in view: NSView) -> [NSTextField] {
        (view as? NSTextField).map { [$0] } ?? [] + view.subviews.flatMap { fields(in: $0) }
    }

    @MainActor
    private func cutSelectableText<V: View>(_ view: V, width: CGFloat) -> [String] {
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        let host = NSHostingView(rootView: view.frame(width: width).environment(store))
        host.frame = NSRect(x: 0, y: 0, width: width, height: 1_200)
        host.layoutSubtreeIfNeeded()
        let found = Self.fields(in: host)
        XCTAssertFalse(found.isEmpty, "the header's selectable text is AppKit text fields")
        return found.compactMap { field in
            // All of its text at its width — what the field editor shows on a click, whatever line limit it was given.
            let whole = field.attributedStringValue.boundingRect(
                with: NSSize(width: field.frame.width - 4, height: .greatestFiniteMagnitude),
                options: [.usesLineFragmentOrigin, .usesFontLeading]).height
            return whole > field.frame.height + 1 ? "\(field.stringValue.prefix(30))… \(Int(whole)) > \(Int(field.frame.height))" : nil
        }
    }

    private func entity(type: EntityType) -> Entity {
        Entity(id: "bob-example", name: String(repeating: "Bob Example ", count: 9), type: type, status: .active,
               confidence: 0.9, created: "2026-01-01", lastReferenced: "2026-09-01", decayRate: 0.05,
               sourceEpisodes: [], tags: [], related: [], version: 1,
               markdownContent: "## Summary\n" + String(repeating: "A long summary sentence about the page. ", count: 12),
               history: [])
    }

    @MainActor
    func testNoSelectableHeaderTextIsCutShortOnAPersonCard() {
        let person = entity(type: .person)
        let hero = PersonHero(entity: person, summary: EntityHeaderWords.summary(markdown: person.markdownContent,
                                                                                isStub: false),
                              isStub: false, inputs: nil, facts: [])
        XCTAssertEqual(cutSelectableText(hero, width: 504), [])
    }

    @MainActor
    func testNoSelectableHeaderTextIsCutShortOnOtherCards() {
        let page = entity(type: .project)
        let header = EntityCardHeader(
            entity: page, summary: EntityHeaderWords.summary(markdown: page.markdownContent, isStub: false),
            isStub: false, canGoBack: false, backTargetName: nil, onBack: {}, showsClose: true, onClose: {},
            tabs: EntityTabs.tabs(claims: [], historyCount: 1), selection: .constant(.content),
            inset: EntityCardStyle.column.inset)
        XCTAssertEqual(cutSelectableText(header, width: 504), [])
    }

    /// Expanding the person's Summary grows the header: what follows it moves down, nothing is drawn over.
    @MainActor
    func testAnExpandedSummaryPushesWhatFollowsItDown() throws {
        let text = String(repeating: "A long summary sentence about the person. ", count: 12)
        func height(expanded: Bool) throws -> CGFloat {
            let view = VStack(alignment: .leading, spacing: 0) {
                EntitySummaryText(text: text, isStub: false, lineLimit: 2, expanded: expanded)
                Color.red.frame(height: 10)
            }
            let renderer = ImageRenderer(content: view)
            renderer.proposedSize = ProposedViewSize(width: 400, height: nil)
            return try XCTUnwrap(renderer.nsImage).size.height
        }
        XCTAssertGreaterThan(try height(expanded: true), try height(expanded: false) + 20)
    }
}
