import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Serves the dumped lists and the dumped day, by channel — never the network.
private final class DumpAPI: ChannelItemsAPI, @unchecked Sendable {
    let pages: [String: ChannelItemsPage]
    let day: WatchedDay?
    init(pages: [String: ChannelItemsPage], day: WatchedDay?) { self.pages = pages; self.day = day }

    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        guard let page = pages[channel] else { throw APIError.httpError(404, "") }
        return Conditional(value: page, etag: nil, notModified: false)
    }

    func fetchWatchedDay(episode: String, etag: String?) async throws -> Conditional<WatchedDay> {
        guard let day, day.episode == episode else { throw APIError.httpError(404, "") }
        return Conditional(value: day, etag: nil, notModified: false)
    }
}

/// Sources v4's PR screenshots, rendered offscreen (an `NSHostingView` in a never-shown window — never the running app)
/// from a JSON dump of a demo bank with synthetic Messages sittings and YouTube days (placeholder names): the root with
/// its faces, Messages by chat under its one header, and a watched day opened to its videos. Skipped unless
/// `SOURCES_V4_RENDER_DIR` names a folder holding `overview.json`, `channels.json`, `lists.json` and `day.json`; the PNGs
/// land beside them, light and dark. Pictures come from Cicada's API, which is offline under XCTest (#348), so every
/// face and still draws its fallback here.
@MainActor
final class SourcesV4RenderTests: XCTestCase {
    func testRenderTheRootMessagesAndAWatchedDayInBothAppearances() async throws {
        guard let dir = ProcessInfo.processInfo.environment["SOURCES_V4_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set SOURCES_V4_RENDER_DIR to render the Sources v4 screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        func load<T: Decodable>(_ name: String, as: T.Type) throws -> T {
            try JSONDecoder().decode(T.self, from: Data(contentsOf: base.appendingPathComponent(name)))
        }
        let rows = try load("overview.json", as: SourceOverviewResponse.self).sources
        let channels = try load("channels.json", as: SourceChannelsResponse.self).channels
        let pages = try load("lists.json", as: [String: ChannelItemsPage].self)
        let day = try load("day.json", as: WatchedDay.self)

        let cache = ChannelItemsCache(api: DumpAPI(pages: pages, day: day))
        for key in pages.keys { await cache.refresh(key) }
        await cache.refreshDay(day.episode)
        let sync = FakeSyncAPI()
        sync.replies[.channels] = .value(channels)
        sync.replies[.sourcesOverview] = .value(rows)
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: sync)
        await store.refresh([.channels, .sourcesOverview])
        let usage = UsageViewModel(store: store)
        let sleepVM = SleepViewModel(store: store)
        let groups = SourceIntentGroups.group(rows)
        CicadaTheme.uiScale = 1.0
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        let messages = try XCTUnwrap(rows.first { $0.id == "imessage" })
        let history = try XCTUnwrap(rows.first { $0.id == "youtube-history" })
        let today = try XCTUnwrap(ISODay("2026-10-19"))

        for dark in [false, true] {
            CicadaTheme.mode = dark ? .dark : .light
            let scheme: ColorScheme = dark ? .dark : .light
            let suffix = dark ? "dark" : "light"
            let env = Env(store: store, usage: usage, cache: cache, sleepVM: sleepVM)

            // STATE 0 — the root: faces on Messages and on each saved source.
            let root = VStack(alignment: .leading, spacing: 0) {
                EyebrowRow(eyebrow: SourcesModel.eyebrow(groups: groups, open: nil))
                SourcesOverviewColumn(rows: rows, hasLoaded: true, onOpen: { _ in })
            }
            try write(root, size: CGSize(width: 900, height: 900), scheme: scheme, env: env,
                      to: base.appendingPathComponent("sources-v4-root-\(suffix).png"))

            // Messages open: one header (what it is, its state, Consolidate · N waiting), then the chats.
            let open = opened(groups: groups, selected: messages.id) {
                SourceDetailHead(source: messages, onClose: {})
                CapturedItemsList(channel: "imessage", style: .open).padding(.horizontal, CicadaTheme.spacingXL)
            }
            try write(open, size: CGSize(width: 1100, height: 640), scheme: scheme, env: env,
                      to: base.appendingPathComponent("sources-v4-messages-\(suffix).png"))

            // YouTube history: one row per day, the newest opened to its videos.
            let page = try XCTUnwrap(pages["youtube-history"])
            let days = opened(groups: groups, selected: history.id) {
                SourceDetailHead(source: history, onClose: {})
                VStack(alignment: .leading, spacing: 0) {
                    SectionLabel(Copy.capturedTitle).frame(minHeight: 28, alignment: .leading)
                    ForEach(Array(page.items.enumerated()), id: \.element.id) { index, item in
                        WatchedDayRow(item: item, today: today, initiallyOpen: index == 0)
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
            }
            try write(days, size: CGSize(width: 1100, height: 640), scheme: scheme, env: env,
                      to: base.appendingPathComponent("sources-v4-youtube-\(suffix).png"))
        }
    }

    private struct Env {
        let store: Store
        let usage: UsageViewModel
        let cache: ChannelItemsCache
        let sleepVM: SleepViewModel
    }

    private func opened<Detail: View>(groups: [SourceIntentGroups.Group], selected: String,
                                      @ViewBuilder detail: () -> Detail) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: SourcesModel.eyebrow(groups: groups, open: .source(selected)))
            HStack(alignment: .top, spacing: 0) {
                SourceGroupsList(groups: groups, style: .triage, selection: .source(selected),
                                 liveness: { SourceLiveness.of(row: $0, channel: nil, watch: nil) }, open: { _ in })
                    .padding(ListInsets.of(.triage))
                    .frame(width: 300, alignment: .topLeading)
                Rectangle().fill(CicadaTheme.border).frame(width: 1)
                VStack(alignment: .leading, spacing: 0, content: detail)
                    .frame(maxWidth: .infinity, alignment: .topLeading)
            }
        }
    }

    private func write<V: View>(_ view: V, size: CGSize, scheme: ColorScheme, env: Env, to url: URL) throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(env.store)
            .environment(env.usage)
            .environment(env.sleepVM)
            .environment(ExploreCache())
            .environment(BrowserWatcher())
            .environment(IntakeRouter())
            .environment(env.cache)
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
