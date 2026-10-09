import XCTest
import SwiftUI
@testable import CicadaApp

/// Offscreen review renders for the large-bank fixes (never the app): the owner's Content in a wide card (two columns)
/// and the Graph's column (stacked), with "What you're connected to", the paged beliefs and the Source view's fold —
/// light and dark. Written only when `APP_SCALE_RENDER_DIR` names a folder.
final class AppScaleRenderTests: XCTestCase {
    @MainActor
    func testRenderTheOwnerPageForReview() throws {
        guard let dir = ProcessInfo.processInfo.environment["APP_SCALE_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set APP_SCALE_RENDER_DIR to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let f = OwnerScaleFixture.self
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        store.graph.value = GraphResponse(nodes: f.nodes, links: f.edges)
        store.graph.loadedAt = Date()
        let graph = GraphViewModel(store: store)
        let digest = ClaimDigest(f.claims)
        defer { CicadaTheme.mode = .dark }
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            CicadaTheme.uiScale = 1
            for (name, width) in [("wide", CGFloat(992)), ("column", GraphColumns.entityMax - 48)] {
                let main = VStack(alignment: .leading, spacing: CicadaTheme.spacingCard) {
                    PersonBeliefsSection(ordered: digest.newestFirst)
                    WhereThisCameFromSection(entityId: f.ownerId, state: .loaded(f.provenance))
                }
                let aside = PersonMapSection(personId: f.ownerId, name: "Owner Example", isOwner: true,
                                             navigate: { _ in }, showOnGraph: {})
                let view = VStack(alignment: .leading, spacing: CicadaTheme.spacingCard) { main; aside }
                    .padding(CicadaTheme.spacingLG)
                    .frame(width: width + CicadaTheme.spacingLG * 2)
                    .background(CicadaTheme.bgBase)
                    .environment(store)
                    .environment(graph)
                    .environment(\.colorScheme, mode == .dark ? .dark : .light)
                try write(view, width: width + CicadaTheme.spacingLG * 2,
                          to: dir, file: "owner-content-\(name)-\(mode == .dark ? "dark" : "light").png")
            }
            let source = SourceText.shown(f.markdown)
            let fold = VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(String(source.text.suffix(600))).font(CicadaTheme.monoFont).foregroundStyle(CicadaTheme.textSecondary)
                Text(Copy.Graph.sourceFolded(bytes: source.foldedBytes ?? 0))
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(CicadaTheme.spacingMD)
            .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgFocus))
            .padding(CicadaTheme.spacingLG)
            .frame(width: 504)
            .background(CicadaTheme.bgBase)
            .environment(\.colorScheme, mode == .dark ? .dark : .light)
            try write(fold, width: 504, to: dir, file: "source-fold-\(mode == .dark ? "dark" : "light").png")
            // The owner's header bug: the person Summary folded and unfolded, the facts strip below it; and a non-person
            // header with a long name. Nothing may draw over what follows.
            let longSummary = String(repeating: "A long summary sentence about the person and their work. ", count: 7)
            let person = Entity(id: "bob-example", name: "Bob Example", type: .person, status: .active, confidence: 0.9,
                                created: "2024-04-02", lastReferenced: "2026-09-30", decayRate: 0.05, sourceEpisodes: [],
                                tags: [], related: [], version: 1, markdownContent: "## Summary\n" + longSummary,
                                history: [])
            let facts = [PersonFact(kind: .knownSince, label: Copy.People.knownSince, value: "Apr 2, 2024 · 2 years"),
                         PersonFact(kind: .lastMentioned, label: Copy.People.lastMentioned, value: "Sep 30")]
            for expanded in [false, true] {
                let hero = PersonHero(entity: person, summary: longSummary, isStub: false, inputs: nil, facts: facts,
                                      summaryExpanded: expanded)
                    .padding(CicadaTheme.spacingLG)
                    .frame(width: 560)
                    .background(CicadaTheme.bgBase)
                    .environment(store)
                    .environment(\.colorScheme, mode == .dark ? .dark : .light)
                try write(hero, width: 560, to: dir,
                          file: "person-summary-\(expanded ? "expanded" : "collapsed")-\(mode == .dark ? "dark" : "light").png")
            }
            let project = Entity(id: "alpha-project", name: String(repeating: "Alpha Project Example ", count: 5),
                                 type: .project, status: .active, confidence: 0.9, created: "2024-04-02",
                                 lastReferenced: "2026-09-30", decayRate: 0.05, sourceEpisodes: [], tags: [], related: [],
                                 version: 1, markdownContent: "## Summary\n" + longSummary, history: [])
            let header = EntityCardHeader(
                entity: project, summary: longSummary, isStub: false, canGoBack: false, backTargetName: nil,
                onBack: {}, showsClose: true, onClose: {}, tabs: EntityTabs.tabs(claims: [], historyCount: 3),
                selection: .constant(.content), inset: EntityCardStyle.column.inset)
                .frame(width: 560)
                .background(CicadaTheme.bgBase)
                .environment(store)
                .environment(\.colorScheme, mode == .dark ? .dark : .light)
            try write(header, width: 560, to: dir, file: "project-header-\(mode == .dark ? "dark" : "light").png")
            // #244 — the History tab's last row: idle, reading, failed.
            let older = VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                OlderChangesRow(phase: .idle) {}
                OlderChangesRow(phase: .loading) {}
                OlderChangesRow(phase: .failed) {}
            }
            .padding(CicadaTheme.spacingLG)
            .frame(width: 504)
            .background(CicadaTheme.bgBase)
            .environment(\.colorScheme, mode == .dark ? .dark : .light)
            try write(older, width: 504, to: dir, file: "history-older-\(mode == .dark ? "dark" : "light").png")
        }
    }

    /// Owner 2026-10-09 — the card opens on its page: the article's first lines, then every other section closed
    /// behind its disclosure; and the same sections opened. Light and dark, at the Graph column's width.
    @MainActor
    func testRenderTheWikiCardForReview() throws {
        guard let dir = ProcessInfo.processInfo.environment["APP_SCALE_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set APP_SCALE_RENDER_DIR to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let f = OwnerScaleFixture.self
        let store = Store(cache: SnapshotCache(
            root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        ), api: FakeSyncAPI())
        store.graph.value = GraphResponse(nodes: f.nodes, links: f.edges)
        store.graph.loadedAt = Date()
        let graph = GraphViewModel(store: store)
        let digest = ClaimDigest(f.claims)
        let article = WikiArticle.build("## Summary\nThe owner.\n\n" + WikiPageFixture.prose
            .replacingOccurrences(of: "## Summary\nOwner Example is the person this memory belongs to.\n", with: ""))
        let width = GraphColumns.entityMax - 48
        defer { CicadaTheme.mode = .dark }
        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            CicadaTheme.uiScale = 1
            for open in [false, true] {
                let view = VStack(alignment: .leading, spacing: CicadaTheme.spacingCard) {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(article.rows.prefix(open ? 3 : 9)) { row in
                            WikiRowView(row: row, onSource: { _ in })
                                .padding(.top, row.id == 0 ? 0 : WikiRowView.gap(above: row, after: article.rows[row.id - 1]))
                        }
                    }
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    CardDisclosure(title: Copy.Graph.beliefsTitle, summary: Copy.Graph.sectionCount(digest.current.count),
                                   isOpen: .constant(open)) {
                        PersonBeliefsSection(ordered: digest.newestFirst, showsLabel: false)
                    }
                    CardDisclosure(title: Copy.Provenance.whereThisCameFrom,
                                   summary: Copy.Graph.conversationsSummary(f.provenance.totals.conversations),
                                   isOpen: .constant(open)) {
                        WhereThisCameFromSection(entityId: f.ownerId, state: .loaded(f.provenance), showsLabel: false)
                    }
                    CardDisclosure(title: PersonMapLayout.title(name: "Owner Example", isOwner: true),
                                   isOpen: .constant(open)) {
                        PersonMapSection(personId: f.ownerId, name: "Owner Example", isOwner: true, showsLabel: false,
                                         navigate: { _ in }, showOnGraph: {})
                    }
                    // A spinner does not draw offscreen; the sources section stays closed here.
                    CardDisclosure(title: Copy.Provenance.lookItUpAt, isOpen: .constant(false)) { EmptyView() }
                    CardDisclosure(title: Copy.Graph.details, summary: Copy.Graph.detailsSummary, isOpen: .constant(false)) {
                        EmptyView()
                    }
                    }
                }
                .padding(CicadaTheme.spacingLG)
                .frame(width: width + CicadaTheme.spacingLG * 2)
                .background(CicadaTheme.bgBase)
                .environment(store)
                .environment(graph)
                .environment(\.colorScheme, mode == .dark ? .dark : .light)
                try write(view, width: width + CicadaTheme.spacingLG * 2, to: dir,
                          file: "wiki-card-\(open ? "sections-open" : "sections-closed")-\(mode == .dark ? "dark" : "light").png")
            }
        }
    }

    @MainActor
    private func write<V: View>(_ view: V, width: CGFloat, to dir: String, file: String) throws {
        let renderer = ImageRenderer(content: view)
        renderer.proposedSize = ProposedViewSize(width: width, height: nil)
        renderer.scale = 2
        let image = try XCTUnwrap(renderer.nsImage)
        let tiff = try XCTUnwrap(image.tiffRepresentation)
        let png = try XCTUnwrap(NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]))
        try png.write(to: URL(fileURLWithPath: dir).appendingPathComponent(file))
    }
}
