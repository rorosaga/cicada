import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Sources v3's PR screenshots, rendered offscreen (an `NSHostingView` in a never-shown window — never the running
/// app) from a JSON dump of the demo bank's `GET /sources/overview` and a saved source's
/// `GET /sources/channels/{id}/items`. Skipped unless `SOURCES_V3_RENDER_DIR` names a folder holding `overview.json`
/// and `lists.json`; the PNGs land beside them, light and dark.
@MainActor
final class SourcesV3RenderTests: XCTestCase {
    private struct Lists: Decodable {
        let pages: [String: ChannelItemsPage]
        init(from decoder: Decoder) throws { pages = try decoder.singleValueContainer().decode([String: ChannelItemsPage].self) }
    }

    func testRenderTheRootAndChromesListInBothAppearances() async throws {
        guard let dir = ProcessInfo.processInfo.environment["SOURCES_V3_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set SOURCES_V3_RENDER_DIR to render the Sources v3 screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        let rows = try JSONDecoder().decode(SourceOverviewResponse.self,
                                            from: Data(contentsOf: base.appendingPathComponent("overview.json"))).sources
        let lists = try JSONDecoder().decode(Lists.self, from: Data(contentsOf: base.appendingPathComponent("lists.json")))
        let chromeId = "chrome-bookmarks"
        let chrome = try XCTUnwrap(rows.first { $0.id == chromeId })
        let page = try XCTUnwrap(lists.pages[chromeId])

        let api = FakeChannelItemsAPI()
        api.replies = [.success(Conditional(value: page, etag: "\"r\"", notModified: false))]
        let cache = ChannelItemsCache(api: api)
        await cache.refresh(chrome.itemsListId)
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let usage = UsageViewModel(store: store)
        let groups = SourceIntentGroups.group(rows)
        CicadaTheme.uiScale = 1.0
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }

        for dark in [false, true] {
            CicadaTheme.mode = dark ? .dark : .light
            let scheme: ColorScheme = dark ? .dark : .light
            let suffix = dark ? "dark" : "light"
            // STATE 0 — the root.
            let root = VStack(alignment: .leading, spacing: 0) {
                EyebrowRow(eyebrow: SourcesModel.eyebrow(groups: groups, open: nil))
                SourcesOverviewColumn(rows: rows, hasLoaded: true, onOpen: { _ in })
            }
            try write(root, size: CGSize(width: 900, height: 720), scheme: scheme, store: store, usage: usage,
                      cache: cache, to: base.appendingPathComponent("sources-root-\(suffix).png"))

            // STATE 1 — Chrome open: the rows beside its list (the second click).
            let open = VStack(alignment: .leading, spacing: 0) {
                EyebrowRow(eyebrow: SourcesModel.eyebrow(groups: groups, open: .source(chromeId)))
                HStack(alignment: .top, spacing: 0) {
                    SourceGroupsList(groups: groups, style: .triage, selection: .source(chromeId),
                                     liveness: { SourceLiveness.of(row: $0, channel: nil, watch: nil) }, open: { _ in })
                        .padding(ListInsets.of(.triage))
                        .frame(width: 300, alignment: .topLeading)
                    Rectangle().fill(CicadaTheme.border).frame(width: 1)
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                        DetailHeader(title: chrome.label, blurb: SourceBlurb.text(for: chrome),
                                     closeHelp: Copy.Lists.closeSource, onClose: {}) {
                            OriginMark(origin: chrome.mark, size: CicadaTheme.scaled(20))
                        }
                        CapturedItemsList(channel: chrome.itemsListId, style: .saved)
                    }
                    .padding(.horizontal, CicadaTheme.spacingXL)
                    .frame(maxWidth: .infinity, alignment: .topLeading)
                }
            }
            try write(open, size: CGSize(width: 1100, height: 720), scheme: scheme, store: store, usage: usage,
                      cache: cache, to: base.appendingPathComponent("sources-chrome-\(suffix).png"))
        }
    }

    private func write<V: View>(_ view: V, size: CGSize, scheme: ColorScheme, store: Store, usage: UsageViewModel,
                                cache: ChannelItemsCache, to url: URL) throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(store)
            .environment(usage)
            .environment(ExploreCache())
            .environment(BrowserWatcher())
            .environment(IntakeRouter())
            .environment(cache)
            .environment(AppRouter())
            .environment(\.colorScheme, scheme)
        let host = NSHostingView(rootView: root)
        host.frame = CGRect(origin: .zero, size: size)
        host.appearance = NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = host.appearance
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.3))
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }
}
