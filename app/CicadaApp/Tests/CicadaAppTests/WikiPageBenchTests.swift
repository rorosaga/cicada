import XCTest
import SwiftUI
import AppKit
@testable import CicadaApp

/// The wiki page at owner scale (`WikiPageFixture`: ~180 KB of prose, ~1,700 lines): what drawing it used to cost
/// (`MarkdownBody`, every line laid out at once) against the article (`WikiArticle` rows built once off the main actor,
/// drawn lazily). The budget test always runs; the print-only benches run with `CICADA_APP_BENCH=1`, and
/// `CICADA_WIKI_BENCH_JSON` (a folder of saved `/entities`, `/claims` and `/provenance` answers) adds the decodes.
final class WikiPageBenchTests: XCTestCase {
    private func ms(_ label: String, runs: Int = 5, _ body: () -> Void) -> Double {
        body()
        var best = Double.infinity
        for _ in 0..<runs {
            let start = DispatchTime.now().uptimeNanoseconds
            body()
            best = min(best, Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000)
        }
        print(String(format: "BENCH %-40@ %8.2f ms", label as NSString, best))
        return best
    }

    /// Lays `view` out in a 900-point-tall window, as the card's column does, and returns the main-thread time.
    @MainActor
    private func layout<V: View>(_ label: String, width: CGFloat = 504, _ view: V) -> Double {
        _ = NSApplication.shared
        let start = DispatchTime.now().uptimeNanoseconds
        let hosting = NSHostingView(rootView: view.frame(width: width, height: 900))
        hosting.frame = NSRect(x: 0, y: 0, width: width, height: 900)
        hosting.layoutSubtreeIfNeeded()
        let rep = hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds)
        if let rep { hosting.cacheDisplay(in: hosting.bounds, to: rep) }
        let elapsed = Double(DispatchTime.now().uptimeNanoseconds - start) / 1_000_000
        print(String(format: "BENCH %-40@ %8.2f ms", label as NSString, elapsed))
        return elapsed
    }

    @MainActor
    func testTheFirstScreenOfAnOwnerSizedPageIsCheap() {
        CicadaTheme.uiScale = 1
        let prose = WikiPageFixture.prose
        let head = WikiArticle.build(prose, maxRows: WikiArticleCache.firstScreenRows)
        let full = WikiArticle.build(prose)
        XCTAssertEqual(Array(full.rows.prefix(head.rows.count)), head.rows, "the first screen is the article's start")
        XCTAssertFalse(head.complete)
        XCTAssertTrue(full.complete)
        XCTAssertGreaterThan(full.rows.count, 1_500)
        let headBuild = ms("WikiArticle first screen (main)") {
            _ = WikiArticle.build(prose, maxRows: WikiArticleCache.firstScreenRows)
        }
        let cache = WikiArticleCache()
        let key = WikiArticleCache.Key(markdown: prose, dropping: WikiArticle.ownSurfaces)
        _ = cache.article(key)
        let drawn = layout("article first screen, lazy", ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                ForEach(full.rows) { WikiRowView(row: $0, onSource: { _ in }) }
            }
        })
        // Generous for a debug build on a loaded machine; `MarkdownBody` took ~2 s here (the opt-in bench).
        XCTAssertLessThan(headBuild, 50)
        XCTAssertLessThan(drawn, 600)
    }

    @MainActor
    func testPrintWhereTheOwnerPagesTimeWent() throws {
        guard ProcessInfo.processInfo.environment["CICADA_APP_BENCH"] == "1" else {
            throw XCTSkip("set CICADA_APP_BENCH=1 to print the wiki page numbers")
        }
        CicadaTheme.uiScale = 1
        let prose = WikiPageFixture.prose
        print("BENCH prose bytes \(prose.utf8.count), lines \(prose.split(separator: "\n").count)")
        _ = ms("header Summary (per render)") { _ = EntityHeaderWords.summary(markdown: prose, isStub: false) }
        _ = ms("old bodyForRendering (per render)") {
            _ = EntityProse.stripSection(named: "## Description",
                                         from: EntityProse.stripSection(named: "## Summary",
                                                                        from: EntityProse.stripClaimsFence(prose)))
        }
        _ = ms("old showsBeliefs (per render)") { _ = EntityProse.showsBeliefs(markdown: prose, isStub: false) }
        _ = ms("WikiArticle full build (off main)", runs: 3) { _ = WikiArticle.build(prose) }
        let full = WikiArticle.build(prose)
        print("BENCH article rows \(full.rows.count)")
        _ = layout("old MarkdownBody, every line", ScrollView { MarkdownBody(text: prose) })
        _ = layout("new article, lazy", ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                ForEach(full.rows) { WikiRowView(row: $0, onSource: { _ in }) }
            }
        })
        _ = layout("new article, inside the card's VStack", ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("toolbar")
                VStack(alignment: .leading) {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(full.rows) { WikiRowView(row: $0, onSource: { _ in }) }
                    }
                }
                Text("sections")
            }
        })

        guard let dir = ProcessInfo.processInfo.environment["CICADA_WIKI_BENCH_JSON"] else { return }
        let decoder = JSONDecoder()
        func data(_ name: String) throws -> Data { try Data(contentsOf: URL(fileURLWithPath: dir).appendingPathComponent(name)) }
        let entity = try data("entities_owner-example.json")
        let claims = try data("entities_owner-example_claims_include_superseded_true.json")
        let provenance = try data("entities_owner-example_provenance.json")
        XCTAssertNoThrow(try decoder.decode(Entity.self, from: entity))
        XCTAssertNoThrow(try decoder.decode(EntityProvenance.self, from: provenance))
        print("BENCH json bytes entity \(entity.count) claims \(claims.count) provenance \(provenance.count)")
        _ = ms("decode /entities/{id}", runs: 3) { _ = try? decoder.decode(Entity.self, from: entity) }
        _ = ms("decode /claims (all)", runs: 3) { _ = try? decoder.decode(ClaimListResponse.self, from: claims) }
        _ = ms("decode /provenance", runs: 3) { _ = try? decoder.decode(EntityProvenance.self, from: provenance) }
        let list = try decoder.decode(ClaimListResponse.self, from: claims).claims
        _ = ms("ClaimDigest (off main)", runs: 3) { _ = ClaimDigest(list) }
    }
}

/// Owner-sized prose (placeholder names only), shaped like the measured owner page: a Summary, ~1,000 Key Facts
/// bullets with wikilinks, then eight sections of a paragraph and 90 detail bullets with inline markdown. ~180 KB.
enum WikiPageFixture {
    static let prose: String = {
        let words = "rover garden lantern harbor meadow signal kettle orchard cedar delta".split(separator: " ")
        let verbs = ["uses", "prefers", "works on", "reads about", "plans"]
        var lines = ["## Summary", "Owner Example is the person this memory belongs to.", "", "## Key Facts"]
        for i in 0..<1_000 {
            lines.append("- Owner Example \(verbs[i % 5]) [[thing-\(String(format: "%04d", i % 400))]] for the "
                         + "\(words[i % 10]) \(words[(i * 3) % 10]) work, noted across several conversations (\(2023 + i % 4)).")
        }
        for s in 0..<8 {
            lines += ["", "## Section \(s)", ""]
            lines.append((0..<12).map { "A paragraph sentence about \(words[(s + $0) % 10]) and [[thing-\(String(format: "%04d", (s * 7 + $0) % 400))]]." }
                .joined(separator: " "))
            lines.append("")
            for k in 0..<90 {
                lines.append("- Detail \(s).\(k): \(words[k % 10]) \(words[(k * 7) % 10]) with **emphasis** and `code` and a [link](https://example.com/\(k)).")
            }
        }
        return lines.joined(separator: "\n")
    }()
}
