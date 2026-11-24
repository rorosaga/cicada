import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// G245 (ruling 78, plan 3.1) — the Sources root's PR screenshots, rendered offscreen (an `NSHostingView` in a
/// never-shown window, never the running app) from the stage-1 streams fixture and placeholder channels: a wide window
/// with some sources connected, one waiting on the person and the rest not connected; the same with no streams answer
/// (404: every card is the catalogue row alone); the find lit on a card; and the narrow rows beside an open source.
///
/// Skipped unless `SOURCES_ROOT_RENDER_DIR` names a folder; the PNGs land there as `root-*.png`. Run:
///
///     SOURCES_ROOT_RENDER_DIR=<folder> swift test --filter SourcesRootRenderTests
///
/// Pictures come from Cicada's API, which is offline under XCTest, so a mark with no bundled logo draws its glyph.
@MainActor
final class SourcesRootRenderTests: XCTestCase {
    private let chrome = BrowserInventory.catalog.first { $0.id == "chrome" }!
    private let safari = BrowserInventory.catalog.first { $0.id == "safari" }!

    private func iso(_ date: Date) -> String { ISO8601DateFormatter().string(from: date) }

    /// Connected: X (a list read in the browser), Apple Notes, Chrome's bookmarks, Reddit and Calendar; waiting on the
    /// person: GitHub (a lapsed sign-in) and Contacts (macOS refused); the rest of the catalogue is not connected.
    private func scene() throws -> (rows: [SourceCatalogRow], streams: ResolvedStreams) {
        let now = SourceStreamsFixture.now
        let channels = [
            SourceChannel(id: "x", label: "X", connected: true, count: 1_246, lastSync: iso(now.addingTimeInterval(-3_600 * 4)),
                          lastError: nil),
            SourceChannel(id: "notes", label: "Apple Notes", connected: true, count: 88,
                          lastSync: iso(now.addingTimeInterval(-60 * 12)), lastError: nil),
            SourceChannel(id: chrome.bookmarksChannel!, label: "Chrome", connected: true, count: 305,
                          lastSync: iso(now.addingTimeInterval(-3_600 * 6)), lastError: nil),
            SourceChannel(id: "reddit", label: "Reddit", connected: true, count: 31,
                          lastSync: iso(now.addingTimeInterval(-86_400 * 3)), lastError: nil),
            SourceChannel(id: "calendar-local", label: "Calendar", connected: true, count: 40,
                          lastSync: iso(now.addingTimeInterval(-60 * 50)), lastError: nil),
            SourceChannel(id: "github", label: "GitHub", connected: true, count: 12, lastSync: nil,
                          lastError: "401 token expired"),
        ]
        let entries = SourceCatalog.entries(browsers: [chrome, safari], wisprPresent: false, hexPresent: false,
                                            overview: [], channels: channels)
        let readers = ["notes": true, "calendar-local": true, ContactsReader.channel: true,
                       chrome.bookmarksChannel!: true]
        let waiting = [ContactsReader.channel: Copy.sourceNeedsAccess]
        let rows = SourceCatalog.rows(entries: entries, channels: channels, overview: [], readableSites: [],
                                      localReaders: readers, savedListsOn: ["x"], localAgent: true,
                                      savedListsRead: ["x"], waitingOn: waiting, suggested: ["linkedin", "youtube"])
        let app = StreamAppState(readers: readers, waitingOn: waiting)
        let streams = SourceStreamOverlay.resolve(try SourceStreamsFixture.load(), app: app, entries: entries,
                                                  now: SourceStreamsFixture.now)
        return (rows, streams)
    }

    private struct Env {
        let store: Store
        let usage: UsageViewModel
    }

    private func env() -> Env {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        return Env(store: store, usage: UsageViewModel(store: store))
    }

    /// The page as the person sees it: the header with its one button, then the root column.
    private func root(cards: [SourcesRoot.Card], connected: Int, state: SourcesRoot.State,
                      checked: Bool) -> some View {
        let gutter = CicadaTheme.spacingGutter
        return VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: Eyebrow.text(Copy.sources, Copy.Catalog.eyebrow(connected))) {
                HStack(spacing: CicadaTheme.spacingMD) {
                    if checked {
                        Text(Copy.Streams.checkedAgo("just now")).font(CicadaTheme.metaFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    NeutralButton(title: Copy.Streams.checkConnections, size: .compact) {}
                }
            }
            .frame(maxWidth: SourcesRootLayout.headerWidth(gutter: gutter), alignment: .leading)
            SourcesOverviewColumn(cards: cards, hasLoaded: true, onOpen: { _ in }, state: .constant(state),
                                  clock: SourceStreamsFixture.now)
        }
    }

    func testRenderTheRootInTheStatesThatMatter() throws {
        guard let dir = ProcessInfo.processInfo.environment["SOURCES_ROOT_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set SOURCES_ROOT_RENDER_DIR to render the Sources root's screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        let (rows, streams) = try scene()
        let cards = SourcesRoot.cards(rows: rows, streams: streams)
        let bare = SourcesRoot.cards(rows: rows, streams: ResolvedStreams())
        let connected = SourceCatalog.onCount(rows)
        let env = env()
        CicadaTheme.uiScale = 1.0
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }

        for dark in [true, false] {
            CicadaTheme.mode = dark ? .dark : .light
            let scheme: ColorScheme = dark ? .dark : .light
            let suffix = dark ? "dark" : "light"
            // A wide window, the streams answer in.
            try write(root(cards: cards, connected: connected, state: SourcesRoot.State(), checked: true),
                      size: CGSize(width: 1_280, height: 1_240), scheme: scheme, env: env,
                      to: base.appendingPathComponent("root-wide-\(suffix).png"))
            // The route 404s (an older backend): every card is the catalogue row alone.
            try write(root(cards: bare, connected: connected, state: SourcesRoot.State(), checked: false),
                      size: CGSize(width: 1_280, height: 1_240), scheme: scheme, env: env,
                      to: base.appendingPathComponent("root-absent-\(suffix).png"))
        }

        CicadaTheme.mode = .dark
        // A kind chosen, then the find lit on one card and the arrows moved to the next.
        try write(root(cards: cards, connected: connected, state: SourcesRoot.State(tab: .saved), checked: false),
                  size: CGSize(width: 1_280, height: 900), scheme: .dark, env: env,
                  to: base.appendingPathComponent("root-saved-dark.png"))
        try write(root(cards: cards, connected: connected, state: SourcesRoot.State(text: "likes"), checked: false),
                  size: CGSize(width: 1_280, height: 520), scheme: .dark, env: env,
                  to: base.appendingPathComponent("root-find-dark.png"))
        try write(root(cards: cards, connected: connected, state: SourcesRoot.State(text: "zzz"), checked: false),
                  size: CGSize(width: 1_280, height: 520), scheme: .dark, env: env,
                  to: base.appendingPathComponent("root-nomatch-dark.png"))

        // Beside an open source the list is the narrow rows, in the same order.
        let narrow = SourcesRoot.narrow(rows: rows, streams: streams, open: "x")
        let beside = HStack(alignment: .top, spacing: 0) {
            ScrollView {
                SourceCatalogList(cards: narrow, style: .triage, selection: .entry("x"), open: { _ in },
                                  clock: SourceStreamsFixture.now)
                    .padding(ListInsets.of(.triage))
            }
            .frame(width: 300)
            Rectangle().fill(CicadaTheme.border).frame(width: 1)
            Spacer()
        }
        try write(beside, size: CGSize(width: 700, height: 900), scheme: .dark, env: env,
                  to: base.appendingPathComponent("root-narrow-dark.png"))
    }

    private func write<V: View>(_ view: V, size: CGSize, scheme: ColorScheme, env: Env, to url: URL) throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(env.store)
            .environment(env.usage)
            .environment(ExploreCache())
            .environment(BrowserWatcher())
            .environment(AppRouter())
            .environment(\.colorScheme, scheme)
        let host = NSHostingView(rootView: root)
        host.frame = CGRect(origin: .zero, size: size)
        host.appearance = NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = host.appearance
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.4))
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }
}
