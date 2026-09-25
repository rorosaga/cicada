import XCTest
@testable import CicadaApp

/// F1 (R-FX8, R-FX11) — the app reads an entity page the way the server does:
/// the ```claims fence is stripped before any section is read. The owner saw
/// `claims - id: clm_… text: …` flattened inside the Summary box of pages
/// whose only section is the Summary (the fence follows the last section).
final class EntityProseTests: XCTestCase {
    private let fence = String(repeating: "`", count: 3)

    private func page(summary: String, extra: String = "") -> String {
        "## Summary\n\(summary)\(extra)\n\n\(fence)claims\n- id: clm_alpha\n  text: alpha-project uses sqlite-vec\n  subject: alpha-project\n\(fence)\n"
    }

    func testTheFenceNeverReachesASection() {
        let md = page(summary: "Alpha Project — created via agentic write.")
        XCTAssertEqual(EntityProse.section(named: "## Summary", in: md), "Alpha Project — created via agentic write.")
        XCTAssertEqual(EntityProse.firstSection(["## Description", "## Summary"], in: md),
                       "Alpha Project — created via agentic write.")
        XCTAssertNil(EntityProse.section(named: "## Summary", in: "## Summary\n\n\(fence)claims\n- id: x\n\(fence)\n"))
        XCTAssertFalse(EntityProse.stripClaimsFence(md).contains("clm_alpha"))
    }

    func testOtherCodeBlocksSurvive() {
        let md = "## Summary\nx\n\n\(fence)swift\nlet a = 1\n\(fence)\n\n\(fence)claims\n- id: c\n\(fence)\n"
        let stripped = EntityProse.stripClaimsFence(md)
        XCTAssertTrue(stripped.contains("let a = 1"))
        XCTAssertFalse(stripped.contains("- id: c"))
    }

    func testAnUnterminatedFenceIsHiddenToTheEnd() {
        XCTAssertEqual(EntityProse.stripClaimsFence("## Summary\nx\n\n\(fence)claims\n- id: c\n"), "## Summary\nx")
    }

    func testThePlaceholderIsRecognisedAndNothingElseIs() {
        XCTAssertTrue(EntityProse.isPlaceholderSummary("Alpha Project — created via agentic write."))
        XCTAssertFalse(EntityProse.isPlaceholderSummary("Alpha Project depends on sqlite-vec."))
        XCTAssertFalse(EntityProse.isPlaceholderSummary("Alpha Project — created via agentic write.\nMore."))
    }

    func testBeliefsShowOnlyOnAFullPageWhoseProseIsAtMostASummary() {
        XCTAssertTrue(EntityProse.showsBeliefs(markdown: page(summary: "Alpha-project depends on sqlite-vec."), isStub: false))
        XCTAssertFalse(EntityProse.showsBeliefs(markdown: page(summary: "x", extra: "\n\n## Key Facts\n- y"), isStub: false))
        XCTAssertFalse(EntityProse.showsBeliefs(markdown: "Alpha Project keeps notes.", isStub: true),
                       "the graph-node stub never triggers a claims fetch")
    }
}
