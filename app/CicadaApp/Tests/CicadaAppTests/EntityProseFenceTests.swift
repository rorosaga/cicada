import XCTest
@testable import CicadaApp

/// `EntityProse.stripClaimsFence` finds fences by search rather than by splitting every line (an owner-sized page is
/// ~110k lines, nearly all inside the fence). It must give exactly what the line-by-line reading gave.
final class EntityProseFenceTests: XCTestCase {
    /// The line-by-line implementation this replaced, kept as the oracle.
    private func lineByLine(_ markdown: String) -> String {
        let fence = "```"
        var kept: [String] = []
        var inFence = false
        for line in markdown.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if inFence {
                if trimmed == fence { inFence = false }
                continue
            }
            if line.hasPrefix(fence), trimmed == fence + "claims" {
                inFence = true
                continue
            }
            kept.append(line)
        }
        return kept.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func testTheSameAnswerAsReadingLineByLine() {
        let cases = [
            "", "\n", "## Summary\nAlpha.", "## Summary\nAlpha.\n\n```claims\n- id: a\n```\n",
            "## Summary\nAlpha.\n```claims\n- id: a\n```", "```claims\n- id: a\n```\nAfter.",
            "Before\n```claims\nnever closed\nstill yaml", "A\n  ```claims\nindented is not a fence\n```\nB",
            "A\n```claims   \n- x\n  ```  \nB\n```claims\n- y\n```\nC", "A ```claims inline\nB",
            "```python\ncode\n```\n```claims\n- z\n```\n", "A\r\n```claims\r\n- id\r\n```\r\nB",
            "```claims\n```\n```claims\n```", "x\n```claims\ntext with ``` inside\n```\ny",
            "## Summary\nOwner.\n\n```claims\n" + String(repeating: "- id: c\n  text: t\n", count: 500) + "```\n",
        ]
        for markdown in cases {
            XCTAssertEqual(EntityProse.stripClaimsFence(markdown), lineByLine(markdown), markdown.debugDescription)
        }
    }

    func testRandomDocumentsAgree() {
        let pieces = ["## Summary", "Alpha.", "", "```claims", "```", "- id: a", "  ```", "```claims  ", "text ```",
                      "```claims x", "\t```", "B"]
        var seed: UInt64 = 7
        func next() -> Int { seed = seed &* 6364136223846793005 &+ 1442695040888963407; return Int(seed >> 33) }
        for _ in 0..<2_000 {
            let markdown = (0..<(next() % 12)).map { _ in pieces[next() % pieces.count] }
                .joined(separator: "\n") + (next() % 2 == 0 ? "\n" : "")
            XCTAssertEqual(EntityProse.stripClaimsFence(markdown), lineByLine(markdown), markdown.debugDescription)
        }
    }

    /// Clusters' search reads a page's prose, never its claims YAML (R-FX8) — on the owner's page that fence is 2.6 MB
    /// folded again after every opened card.
    func testClustersSearchesTheProseNotTheFence() {
        let page = Entity(id: "alpha-project", name: "Alpha Project", type: .project, status: .active, confidence: 1,
                          created: "", lastReferenced: "", decayRate: 0, sourceEpisodes: [], tags: [], related: [],
                          version: 1, markdownContent: "## Summary\nA rover arm.\n\n```claims\n- id: zebracorn\n```\n",
                          history: [])
        let index = ClusterSearchIndex([page])
        XCTAssertEqual(index.rank("rover").map(\.id), ["alpha-project"])
        XCTAssertEqual(index.rank("zebracorn").map(\.id), [])
    }
}
