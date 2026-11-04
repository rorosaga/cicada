import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The standard source page's PR screenshots for GitHub (owner 2026-11-04), rendered offscreen — an `NSHostingView` in
/// a never-shown window, never the running app — from synthetic repositories (placeholder names only): not connected,
/// the code, connected with the install step, and connected with both lists. These states need a real GitHub sign-in in
/// the app, which a verify run never presses. Skipped unless `SOURCE_PAGE_RENDER_DIR` names a folder; the PNGs land
/// there, light and dark. Pictures come from Cicada's API, offline under XCTest, so every row wears GitHub's mark.
@MainActor
final class SourcePageRenderTests: XCTestCase {
    private func code() -> GitHubConnectCode {
        GitHubConnectCode(userCode: "WDJB-MJHT", verificationUri: "https://github.com/login/device",
                          expiresAt: Int(Date().timeIntervalSince1970) + 14 * 60, interval: 5)
    }

    private func repo(_ id: Int, _ full: String, _ description: String?, _ language: String?, owned: Bool,
                      isPrivate: Bool = false) -> RepoRow {
        RepoRow(id: id, fullName: full, url: "https://github.com/\(full)", description: description,
                language: language, isPrivate: isPrivate, starred: !owned, owned: owned, entityId: "repo-\(id)")
    }

    private var lists: RepoLists {
        RepoLists(connected: true, owned: [
            repo(1, "verify-person/alpha-project", "Notes and scripts for the alpha project", "Python", owned: true),
            repo(2, "verify-person/meter-sim", "A small simulator for the meter demo", "Swift", owned: true,
                 isPrivate: true),
            repo(3, "verify-person/lantern", "Local-first storage experiments", "Rust", owned: true),
            repo(4, "verify-person/dotfiles", nil, "Shell", owned: true),
        ], starred: [
            repo(10, "example-org/widget-kit", "Composable widgets for example apps", "TypeScript", owned: false),
            repo(11, "bob-example/tiny-parser", "A parser in a few hundred lines", "Go", owned: false),
            repo(12, "example-org/graph-tools", "Force layouts and friends", "JavaScript", owned: false),
        ])
    }

    private func connectModel(_ status: GitHubConnectStatus) -> GitHubConnectModel {
        GitHubConnectModel(deps: .init(
            status: { status }, start: { self.code() }, poll: { GitHubConnectPoll(state: "pending") },
            installation: { status }, cancel: {},
            sync: { ConnectorSyncResult(status: "ok", reason: nil, new: 0, seen: 0, error: nil, resourcesRead: 0) },
            disconnect: {}, open: { _ in }, sleep: { _ in try? await Task.sleep(for: .seconds(3600)) }))
    }

    private func reposModel(_ lists: RepoLists) -> GitHubReposModel {
        GitHubReposModel(deps: .init(fetch: { lists },
                                     project: { _, _, _ in RepoProjectResult(project: "alpha", created: false) }))
    }

    func testRenderGitHubsStatesInBothAppearances() async throws {
        guard let dir = ProcessInfo.processInfo.environment["SOURCE_PAGE_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set SOURCE_PAGE_RENDER_DIR to render the source page screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        let channels = try JSONDecoder().decode([SourceChannel].self, from: Data("""
            [{"id": "github", "label": "GitHub", "connected": true, "count": 7, "lastSync": "\(ISO8601DateFormatter().string(from: Date()))",
              "actions": ["sync", "disconnect"]}]
            """.utf8))
        let sync = FakeSyncAPI()
        sync.replies[.channels] = .value(channels)
        sync.replies[.sourcesOverview] = .value([SourceOverview]())
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: sync)
        await store.refresh([.channels, .sourcesOverview])
        let entry = try XCTUnwrap(SourceCatalog.fixed.first { $0.id == "github" })
        CicadaTheme.uiScale = 1.0
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }

        let states: [(String, GitHubConnectStatus, RepoLists, SourceCatalogStatus)] = [
            ("not-connected", GitHubConnectStatus(available: true), RepoLists(), .off),
            ("code", GitHubConnectStatus(available: true, pending: code()), RepoLists(), .off),
            ("install", GitHubConnectStatus(available: true, connected: true, how: "app", installed: false,
                                            installUrl: "https://github.com/apps/example/installations/new"),
             RepoLists(connected: true, starred: lists.starred), .connected),
            ("connected", GitHubConnectStatus(available: true, connected: true, how: "app", installed: true), lists,
             .connected),
        ]
        for dark in [false, true] {
            CicadaTheme.mode = dark ? .dark : .light
            let scheme: ColorScheme = dark ? .dark : .light
            for (name, status, lists, catalogue) in states {
                let row = SourceCatalogRow(entry: entry, status: catalogue, lastSync: nil)
                let connect = connectModel(status)
                await connect.load()
                connect.stop()
                let repos = reposModel(lists)
                await repos.load()
                let page = GitHubSourcePage(row: row, onClose: {}, connect: connect, repos: repos)
                try write(page, size: CGSize(width: 820, height: 760), scheme: scheme, store: store,
                          to: base.appendingPathComponent("github-\(name)-\(dark ? "dark" : "light").png"))
            }
        }
    }

    private func write<V: View>(_ view: V, size: CGSize, scheme: ColorScheme, store: Store, to url: URL) throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(store)
            .environment(AppRouter())
            .environment(\.colorScheme, scheme)
        let host = NSHostingView(rootView: root)
        host.frame = CGRect(origin: .zero, size: size)
        host.appearance = NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = host.appearance
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.6))
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }
}
