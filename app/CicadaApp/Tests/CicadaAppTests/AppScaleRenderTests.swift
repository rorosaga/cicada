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
                let view = PersonColumns(main: main, aside: aside)
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
