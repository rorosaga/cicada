import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// "Say it once" (owner 2026-10-19) — the PR's before/after screenshots, rendered offscreen (an `NSHostingView` in a
/// never-shown window — never the running app) from a demo bank served by a scratch backend the person running the
/// test started (`CICADA_API_AUTH=off`, a scratch `CICADA_HOME`, `POST /banks/demo`). Skipped unless
/// `SAY_IT_ONCE_RENDER_DIR` names a folder; `SAY_IT_ONCE_BASE` is that backend (default `http://127.0.0.1:8791`) and
/// `SAY_IT_ONCE_PHASE` prefixes the files (`before` / `after`). The test's own client reaches only that base.
@MainActor
final class SayItOnceRenderTests: XCTestCase {
    override func setUp() {
        super.setUp()
        ContactsTrap.install()   // never this Mac's Contacts service (#527 review)
    }

    private struct Env {
        let store: Store
        let router: AppRouter
        let graphVM: GraphViewModel
        let inboxVM: InboxViewModel
        let sleepVM: SleepViewModel
        let engineVM: SleepEngineViewModel
        let feedVM: FeedViewModel
        let usageVM: UsageViewModel
        let homeSearch: HomeSearch
        let find: FindPaletteModel
        let activity: SyncActivity
        let lights: BrowserWatcher
        let messages: MessagesWatcher
    }

    private func client(_ base: String) -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        return APIClient(session: URLSession(configuration: config),
                         connection: ServerConnection(mode: .thisMac, source: .none),
                         runtime: .developer(codeRoot: URL(fileURLWithPath: "/nonexistent")),
                         baseOverride: base)
    }

    private func makeEnv(_ api: APIClient) async -> Env {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: api)
        await store.refresh(Set(SyncDomain.allCases).subtracting([.askHistory, .quickRecents]))
        let sleepVM = SleepViewModel(
            store: store,
            fetchSleepStatus: { try await api.fetchSleepStatus() },
            requestCancel: { try await api.cancelSleep() },
            fetchHistory: { try await api.fetchSleepHistory(limit: 15) },
            fetchDetail: { try await api.fetchSleepCycleDetail($0) },
            fetchEngine: { try await api.fetchSleepEngine() },
            putSchedule: { try await api.updateSchedule($0) },
            requestEnd: { try await api.endSleepRun() },
            requestRetry: { try await api.retryParked(ids: $0) },
            fetchRunOptions: { try await api.fetchRunOptions() },
            putRunOptions: { try await api.updateRunOptions($0) },
            fetchQueue: { try await api.fetchSleepQueue(limit: 200) },
            fetchRun: { try await api.fetchSleepRun($0) },
            fetchEpisodes: { try await api.fetchEpisodeQueue(etag: $0) },
            fetchSchedule: { try await api.fetchSchedule() })
        await sleepVM.load()
        await sleepVM.loadQueue()
        let engineVM = SleepEngineViewModel(fetch: { try await api.fetchSleepEngine() })
        await engineVM.load()
        let find = FindPaletteModel(store: store)
        let activity = SyncActivity()
        let lights = BrowserWatcher(activity: activity)
        return Env(store: store, router: AppRouter(), graphVM: GraphViewModel(store: store),
                   inboxVM: InboxViewModel(store: store), sleepVM: sleepVM, engineVM: engineVM,
                   feedVM: FeedViewModel(store: store), usageVM: UsageViewModel(store: store),
                   homeSearch: HomeSearch(model: FindPaletteModel(store: store, ask: find.ask, keepsRecents: false)),
                   find: find, activity: activity, lights: lights,
                   messages: MessagesWatcher(lights: lights, activity: activity, bank: { [store] in store.bank }))
    }

    func testRenderEveryPageItsRootAndItsDetails() async throws {
        let vars = ProcessInfo.processInfo.environment
        guard let dir = vars["SAY_IT_ONCE_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set SAY_IT_ONCE_RENDER_DIR (and start a scratch demo backend) to render the screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        let phase = vars["SAY_IT_ONCE_PHASE"] ?? "after"
        let only = vars["SAY_IT_ONCE_ONLY"].map { Set($0.split(separator: ",").map(String.init)) }
        let api = client(vars["SAY_IT_ONCE_BASE"] ?? "http://127.0.0.1:8791")
        let env = await makeEnv(api)
        XCTAssertNotNil(env.store.graph.value, "the scratch backend answered")
        CicadaTheme.uiScale = 1.0
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        let size = CGSize(width: 1240, height: 820)
        let person = env.store.graph.value?.nodes.first { $0.type == .person && !$0.isOwner }?.id
        let project = env.store.graph.value?.nodes.first { $0.type == .project }?.id

        for dark in [false, true] {
            CicadaTheme.mode = dark ? .dark : .light
            let scheme: ColorScheme = dark ? .dark : .light
            let suffix = dark ? "dark" : "light"
            func shot(_ name: String, _ view: some View, setup: () -> Void = {}) async throws {
                if let only, !only.contains(name) { return }
                setup()
                try await write(view, env: env, size: size, scheme: scheme,
                                to: base.appendingPathComponent("\(phase)-\(name)-\(suffix).png"))
            }
            try await shot("home", HomeView(open: { _ in }, selectedTab: .constant(.home)))
            try await shot("sleep-waiting", SleepView(selectedTab: .constant(.sleep)))
            try await shot("sleep-past", SleepView(selectedTab: .constant(.sleep))) {
                env.router.pendingSleepDetails = .pastNights
            }
            try await shot("inbox", InboxPage()) { env.inboxVM.columns.close() }
            try await shot("inbox-open", InboxPage()) {
                if let first = env.inboxVM.visible.first { env.inboxVM.columns.land(first.id) }
            }
            try await shot("inbox-review", InboxPage()) {
                env.inboxVM.columns.close()
                if let kind = env.inboxVM.reviewEntries.first?.kind { env.inboxVM.startReview(kind) }
            }
            env.inboxVM.endReview()
            try await shot("clusters", ClustersPage())
            if let person {
                try await shot("clusters-person", ClustersPage()) { env.router.pendingClustersEntity = person }
            }
            if let project {
                try await shot("clusters-project", ClustersPage()) { env.router.pendingClustersEntity = project }
            }
        }
    }

    private func write<V: View>(_ view: V, env: Env, size: CGSize, scheme: ColorScheme, to url: URL) async throws {
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(env.store)
            .environment(env.router)
            .environment(env.graphVM)
            .environment(env.inboxVM)
            .environment(env.sleepVM)
            .environment(env.engineVM)
            .environment(env.feedVM)
            .environment(env.usageVM)
            .environment(env.homeSearch)
            .environment(env.find)
            .environment(env.activity)
            .environment(env.lights)
            .environment(env.messages)
            .environment(ProvenanceRouter())
            .environment(ProvenanceCache())
            .environment(TourController())
            .environment(SetupRunner())
            .environment(IntakeRouter())
            .environment(ExportWaitStore())
            .environment(ReadingSitesCache())
            .environment(VideoStateCache())
            .environment(ChannelItemsCache())
            .environment(ExploreCache())
            .environment(ProjectsCache())
            .environment(BacklogCache())
            .environment(SaveWhyCenter())
            .environment(BanksViewModel(store: env.store))
            .environment(LocalInventory(probes: LocalInventoryProbes(wiring: { nil }, isInstalled: { _ in false },
                                                                     browserPresence: { _ in .absent },
                                                                     claudeDesktopHasCicada: { nil })))
            .environment(TabGroupWatcher(lights: env.lights, activity: env.activity))
            .environment(LocalSourceWatcher(lights: env.lights))
            .environment(\.colorScheme, scheme)
        let host = NSHostingView(rootView: root)
        host.frame = CGRect(origin: .zero, size: size)
        host.appearance = NSAppearance(named: scheme == .dark ? .darkAqua : .aqua)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = host.appearance
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        for _ in 0..<8 {
            RunLoop.main.run(until: Date().addingTimeInterval(0.1))
            try await Task.sleep(nanoseconds: 250_000_000)
            host.layoutSubtreeIfNeeded()
        }
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
        window.contentView = nil
    }
}
