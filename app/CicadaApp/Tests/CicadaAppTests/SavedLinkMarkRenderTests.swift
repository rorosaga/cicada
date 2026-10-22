import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// Owner 2026-10-20 — the PR's before/after, rendered offscreen (an `NSHostingView` in a never-shown window, never the
/// running app). Sleep › Saved rows and Sleep › Waiting rows of synthetic saved links and one conversation. "Before" is
/// the same rows as an older backend serves them (no site named), which draws exactly the old mark — the browser's;
/// "after" names the site. Two sites' icons are synthetic squares primed into `SiteIconStore` so nothing is asked of a
/// backend; a family's bundled mark and a monogram show the fallback rungs. Skipped unless `SITE_MARKS_RENDER_DIR`
/// names a folder.
@MainActor
final class SavedLinkMarkRenderTests: XCTestCase {
    func testRenderSleepRowsBeforeAndAfter() async throws {
        guard let dir = ProcessInfo.processInfo.environment["SITE_MARKS_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set SITE_MARKS_RENDER_DIR to render the site-mark screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        await SiteIconStore.shared.prime(Self.square(.systemTeal, "P"), savedSite: "paperfold.io", bank: store.bank)
        await SiteIconStore.shared.prime(Self.square(.systemOrange, "L"), savedSite: "lanternworks.dev", bank: store.bank)
        CicadaTheme.uiScale = 1.0
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }

        for named in [false, true] {
            let saved = try [
                feed("m1", "A field guide to paper folding", "https://www.paperfold.io/guide", "paperfold.io", named),
                feed("m2", "Lantern: a tiny build tool", "https://lanternworks.dev/", "lanternworks.dev", named),
                feed("m3", "A post about design systems", "https://www.linkedin.com/posts/x", "linkedin", named,
                     host: "linkedin.com"),
                feed("m4", "Notes on quiet software", "https://quietpages.example/notes", "quietpages.example", named),
            ]
            let waiting = try [
                episode("ep_2026-10-20_1", "A field guide to paper folding", "https://www.paperfold.io/guide",
                        named ? "paperfold.io" : nil),
                episode("ep_2026-10-20_2", "Lantern changelog", "https://lanternworks.dev/changelog",
                        named ? "lanternworks.dev" : nil),
                conversation("ep_2026-10-20_3", "Planning the release notes"),
            ]
            for dark in [false, true] {
                CicadaTheme.mode = dark ? .dark : .light
                let scheme: ColorScheme = dark ? .dark : .light
                let view = VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    SectionLabel("Saved")
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                        ForEach(saved) { item in
                            FeedListRow(item: item, style: .wide, selected: false,
                                        now: ISO8601DateFormatter().date(from: "2026-10-20T12:00:00Z")!) {}
                        }
                    }
                    SectionLabel("Waiting").padding(.top, CicadaTheme.spacingLG)
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(waiting) { EpisodeRow(item: $0) }
                    }
                }
                .padding(24)
                let name = "sleep-rows-\(named ? "after" : "before")-\(dark ? "dark" : "light").png"
                try await write(view, size: CGSize(width: 720, height: 560), scheme: scheme, store: store,
                          to: base.appendingPathComponent(name))
            }
        }
    }

    private func feed(_ id: String, _ title: String, _ url: String, _ key: String, _ named: Bool,
                      host: String? = nil) throws -> MediaFeedItem {
        var json: [String: Any] = ["mediaEntityId": id, "url": url, "title": title, "mediaType": "bookmark",
                                   "site": host ?? key, "savedAt": "2026-10-19T09:00:00Z", "tags": [],
                                   "status": "active", "relatedCount": 0, "relevance": 0,
                                   "origin": "chrome-bookmark"]
        if named { json["siteKey"] = key }
        return try JSONDecoder().decode(MediaFeedItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    private func episode(_ id: String, _ title: String, _ url: String, _ site: String?) throws -> EpisodeQueueItem {
        var json: [String: Any] = ["id": id, "timestamp": "2026-10-20T08:00:00Z", "source": "chrome-bookmark",
                                   "origin": "chrome-bookmark", "title": title, "preview": "", "processed": false,
                                   "copyKind": "link", "copyValue": url]
        if let site { json["site"] = site }
        return try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: json))
    }

    private func conversation(_ id: String, _ title: String) throws -> EpisodeQueueItem {
        let json: [String: Any] = ["id": id, "timestamp": "2026-10-20T07:00:00Z", "source": "claude-code",
                                   "origin": "claude-code", "title": title, "preview": "", "processed": false,
                                   "copyKind": "conversation", "copyValue": "s-1"]
        return try JSONDecoder().decode(EpisodeQueueItem.self, from: JSONSerialization.data(withJSONObject: json))
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

    private func write<V: View>(_ view: V, size: CGSize, scheme: ColorScheme, store: Store, to url: URL) async throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(store)
            .environment(\.colorScheme, scheme)
        let host = NSHostingView(rootView: root)
        host.frame = CGRect(origin: .zero, size: size)
        host.appearance = NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = host.appearance
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        // Yield the main actor so each mark's `.task` takes its primed answer, then lay out again.
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
