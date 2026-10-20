import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// marks-2's PR screenshots, rendered offscreen (an `NSHostingView` in a never-shown window, never the running app) from
/// placeholder rows: a YouTube saved list whose videos draw their stills, and the Sources root's saved rows with their
/// faces — "before" newest first (sites with no icon yet lead, as letters), "after" with the sites whose icon is cached
/// first (the backend's new order). Stills and icons are synthetic images primed into the stores, so nothing is asked of
/// a backend. Skipped unless `MARKS_RENDER_DIR` names a folder.
@MainActor
final class MarksThatAppearRenderTests: XCTestCase {
    func testRenderTheYouTubeListAndTheRootFaces() async throws {
        guard let dir = ProcessInfo.processInfo.environment["MARKS_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set MARKS_RENDER_DIR to render the marks-2 screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let usage = UsageViewModel(store: store)
        let sleepVM = SleepViewModel(store: store)
        let cache = ChannelItemsCache(api: NoItems())
        let palette: [(NSColor, String)] = [(.systemRed, "1"), (.systemIndigo, "2"), (.systemGreen, "3"),
                                            (.systemOrange, "4")]
        for (i, (color, label)) in palette.enumerated() {
            await SourcePictureStore.shared.prime(Self.still(color, label),
                                                  path: "/sources/saved/media-v\(i + 1)/still", bank: store.bank)
        }
        for (site, color, letter) in [("paperfold.io", NSColor.systemTeal, "P"),
                                      ("lanternworks.dev", .systemOrange, "L"),
                                      ("quietpages.net", .systemPurple, "Q"),
                                      ("tidepool.app", .systemBlue, "T")] {
            await SiteIconStore.shared.prime(Self.square(color, letter), savedSite: site, bank: store.bank)
        }
        CicadaTheme.uiScale = 1.0
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        let today = try XCTUnwrap(ISODay("2026-10-20"))

        let videos = try [
            item("media-v1", "How paper folds hold their shape", "2026-10-20", video: true),
            item("media-v2", "A short talk on quiet software", "2026-10-19", video: true),
            item("media-v3", "Building a tiny compiler, part 1", "2026-10-17", video: true),
            item("media-v4", "Tide tables explained", "2026-10-12", video: true),
            item("media-v5", "A video whose still has not arrived", "2026-10-03", video: true),
        ]
        func faces(_ sites: [(String, String)]) -> [[String: Any]] {
            sites.enumerated().map { ["kind": "site", "id": "media-f\($0.offset)", "label": $0.element.0,
                                      "site": $0.element.1] }
        }
        let newestFirst = [("cobaltnotes.zz", "cobaltnotes.zz"), ("paperfold.io", "paperfold.io"),
                           ("rivetmail.zz", "rivetmail.zz")]
        let iconsFirst = [("paperfold.io", "paperfold.io"), ("lanternworks.dev", "lanternworks.dev"),
                          ("quietpages.net", "quietpages.net")]
        let safariBefore = [("emberfield.zz", "emberfield.zz"), ("eastwind.zz", "eastwind.zz"),
                            ("tidepool.app", "tidepool.app")]
        let safariAfter = [("tidepool.app", "tidepool.app"), ("emberfield.zz", "emberfield.zz"),
                           ("eastwind.zz", "eastwind.zz")]

        for dark in [false, true] {
            CicadaTheme.mode = dark ? .dark : .light
            let scheme: ColorScheme = dark ? .dark : .light
            let suffix = dark ? "dark" : "light"
            let list = VStack(alignment: .leading, spacing: 0) {
                SectionLabel("Saved").frame(minHeight: 28, alignment: .leading)
                ForEach(videos) { SavedItemRow(item: $0, today: today, route: nil, open: { _ in }) }
            }
            .padding(24)
            try await write(list, size: CGSize(width: 640, height: 380), scheme: scheme, store: store, usage: usage,
                            sleepVM: sleepVM, cache: cache, to: base.appendingPathComponent("youtube-saved-\(suffix).png"))
            for (name, chrome, safari) in [("before", newestFirst, safariBefore), ("after", iconsFirst, safariAfter)] {
                let rows = try [
                    overview("chrome-bookmarks", "Chrome", faces(chrome), more: 260),
                    overview("safari-bookmarks", "Safari", faces(safari), more: 233),
                ]
                let root = SourcesOverviewColumn(rows: rows, hasLoaded: true, onOpen: { _ in })
                try await write(root, size: CGSize(width: 760, height: 300), scheme: scheme, store: store,
                                usage: usage, sleepVM: sleepVM, cache: cache,
                                to: base.appendingPathComponent("sources-faces-\(name)-\(suffix).png"))
            }
        }
    }

    private func item(_ id: String, _ title: String, _ day: String, video: Bool) throws -> ChannelItem {
        ChannelItem(kind: .media, id: id, title: title, day: day, host: "youtube.com", site: "youtube.com",
                    video: video)
    }

    private func overview(_ id: String, _ label: String, _ faces: [[String: Any]], more: Int) throws -> SourceOverview {
        let json: [String: Any] = ["id": id, "label": label, "kind": "browser", "mark": id, "items": 300 + more,
                                   "connected": true, "channelId": id, "intent": "saved", "faces": faces,
                                   "facesMore": more, "lastActivityAt": "2026-10-20T09:00:00Z"]
        return try JSONDecoder().decode(SourceOverview.self, from: JSONSerialization.data(withJSONObject: json))
    }

    /// A synthetic video still: a 16:9 colour field with a number (no real video's frame).
    private static func still(_ color: NSColor, _ label: String) -> NSImage {
        NSImage(size: NSSize(width: 160, height: 90), flipped: false) { rect in
            color.withAlphaComponent(0.85).setFill()
            rect.fill()
            let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 40, weight: .bold),
                                                        .foregroundColor: NSColor.white]
            let text = NSAttributedString(string: label, attributes: attrs)
            let size = text.size()
            text.draw(at: NSPoint(x: (rect.width - size.width) / 2, y: (rect.height - size.height) / 2))
            return true
        }
    }

    /// A synthetic site icon: a rounded colour square with a letter (no real site's mark).
    private static func square(_ color: NSColor, _ letter: String) -> NSImage {
        NSImage(size: NSSize(width: 64, height: 64), flipped: false) { rect in
            color.setFill()
            NSBezierPath(roundedRect: rect, xRadius: 14, yRadius: 14).fill()
            let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 38, weight: .bold),
                                                        .foregroundColor: NSColor.white]
            let text = NSAttributedString(string: letter, attributes: attrs)
            let size = text.size()
            text.draw(at: NSPoint(x: (rect.width - size.width) / 2, y: (rect.height - size.height) / 2))
            return true
        }
    }

    private func write<V: View>(_ view: V, size: CGSize, scheme: ColorScheme, store: Store, usage: UsageViewModel,
                                sleepVM: SleepViewModel, cache: ChannelItemsCache, to url: URL) async throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(store)
            .environment(usage)
            .environment(sleepVM)
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
        // Yield the main actor so each picture's `.task` takes its primed answer, then lay out again.
        for _ in 0..<5 {
            try await Task.sleep(nanoseconds: 100_000_000)
            RunLoop.main.run(until: Date().addingTimeInterval(0.05))
        }
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }
}

/// No list is opened in these renders.
private final class NoItems: ChannelItemsAPI, @unchecked Sendable {
    func fetchChatSittings(conversation: String, etag: String?) async throws -> Conditional<ChatSittings> {
        throw APIError.httpError(404, "")
    }

    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        throw APIError.httpError(404, "")
    }

    func fetchWatchedDay(episode: String, etag: String?) async throws -> Conditional<WatchedDay> {
        throw APIError.httpError(404, "")
    }
}
