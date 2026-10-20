import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The consistency pass, round 2 (2026-10-20): the pages whose columns, add affordance, fields, fold and first-read
/// state moved onto the shared components, light and dark, offscreen. Env-gated:
/// `CICADA_CONSISTENCY2_SNAPSHOTS=<dir>`. Built through public inits only, so the same file renders the before
/// (origin/dev) and the after.
@MainActor
final class DesignConsistency2SnapshotTests: XCTestCase {
    func test_writeRoundTwoPagesForComparison() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_CONSISTENCY2_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_CONSISTENCY2_SNAPSHOTS=<dir> to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        CicadaTheme.uiScale = 1
        let out = URL(fileURLWithPath: dir)

        let api = Snapshot2SkillsAPI()
        api.page = try JSONDecoder().decode(SkillsPageData.self, from: Data(SkillsPageTests.payload.utf8))
        let skills = SkillsPageModel(api: api, pollInterval: .milliseconds(1))
        await skills.load()
        let skillName = try XCTUnwrap(skills.data?.installed.first?.name)

        let refs = LooksTests.fixtures.map(\.0)
        let images = Dictionary(uniqueKeysWithValues: LooksTests.fixtures.map { ($0.0.id, $0.1) })
        let tile: (DesignRefSummary) -> AnyView = { ref in
            AnyView(Image(nsImage: images[ref.id]!).resizable().scaledToFill())
        }
        let open = refs[min(4, refs.count - 1)]
        let composerImage = LooksTests.fixtures[0].1
        let composerInput = LooksComposerInput(image: composerImage, data: Data(), ext: "png", via: "drop")

        let cluster = try JSONDecoder().decode(ProjectCluster.self, from: Data(Self.cluster.utf8))
        let channels = ChannelItemsCache(api: Snapshot2HangingItemsAPI())

        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let name = mode == .dark ? "dark" : "light"
            let page = CGSize(width: 1376, height: 800)

            let skillsRoot = SkillsPageView(model: skills, tab: .constant(nil), selected: .constant(nil),
                                            addText: .constant(""), addFocused: FocusState<Bool>().projectedValue)
            try snapshot(skillsRoot, size: page, mode: mode, to: out.appendingPathComponent("skills-root-\(name).png"))
            let skillsOpen = SkillsPageView(model: skills, tab: .constant(nil), selected: .constant(skillName),
                                            addText: .constant(""), addFocused: FocusState<Bool>().projectedValue)
            try snapshot(skillsOpen, size: page, mode: mode, to: out.appendingPathComponent("skills-open-\(name).png"))

            let looksRoot = LooksBoardView(refs: refs, total: refs.count, phase: .loaded,
                                           vision: DesignVision(supported: true, installed: true), searching: false,
                                           searchNote: nil, query: .constant(""), open: nil, detail: nil,
                                           writeError: nil, tile: tile)
            try snapshot(looksRoot, size: page, mode: mode, to: out.appendingPathComponent("looks-root-\(name).png"))
            let looksOpen = LooksBoardView(refs: refs, total: refs.count, phase: .loaded,
                                           vision: DesignVision(supported: true, installed: true), searching: false,
                                           searchNote: nil, query: .constant(""), open: open, detail: nil,
                                           writeError: nil, tile: tile)
            try snapshot(looksOpen, size: page, mode: mode, to: out.appendingPathComponent("looks-open-\(name).png"))

            let composer = LooksComposer(input: composerInput, saving: false, error: nil, onCancel: {},
                                         onFindSimilar: { _ in }, onSave: { _ in })
            try snapshot(composer, size: CGSize(width: 460, height: 560), mode: mode,
                         to: out.appendingPathComponent("looks-composer-\(name).png"))

            let around = ProjectAroundSection(cluster: cluster, today: ISODay(year: 2026, month: 10, day: 20),
                                              partial: false, openCard: nil, openEntity: { _ in },
                                              openProject: { _ in }, openSource: { _ in })
                .padding(24)
                .frame(width: 560, alignment: .topLeading)
            try snapshot(around, size: CGSize(width: 560, height: 220), mode: mode,
                         to: out.appendingPathComponent("projects-around-\(name).png"))

            let captured = VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                DetailHeader(title: "Notes", closeHelp: "Close", onClose: {})
                CapturedItemsList(channel: "notes", style: .open)
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .frame(width: 620, alignment: .topLeading)
            try snapshot(captured, size: CGSize(width: 620, height: 360), mode: mode, channels: channels,
                         to: out.appendingPathComponent("sources-captured-loading-\(name).png"))
        }
    }

    static let cluster = """
    {"groups": [
      {"label": "Tools", "more": 0, "members": [
        {"id": "tool-alpha", "type": "tool", "name": "alpha-tool", "rolePhrase": "builds it", "fact": "",
         "lastSeen": "2026-10-18", "count": 4, "pending": false},
        {"id": "tool-beta", "type": "tool", "name": "beta-tool", "rolePhrase": "", "fact": "runs the tests",
         "lastSeen": "2026-10-02", "count": 2, "pending": false}]},
      {"label": "People", "more": 0, "members": [
        {"id": "person-bob", "type": "person", "name": "bob-example", "rolePhrase": "reviews", "fact": "",
         "lastSeen": "2026-10-11", "count": 3, "pending": false}]}
    ]}
    """

    private func snapshot<V: View>(_ view: V, size: CGSize, mode: AppColorScheme, channels: ChannelItemsCache? = nil,
                                   to url: URL) throws {
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let root = view
            .frame(width: size.width, height: size.height, alignment: .topLeading)
            .background(CicadaTheme.bgBase)
            .environment(store)
            .environment(ProvenanceRouter())
            .environment(AppRouter())
            .environment(channels ?? ChannelItemsCache(api: Snapshot2HangingItemsAPI()))
            .environment(\.colorScheme, mode == .dark ? .dark : .light)
        let host = NSHostingView(rootView: root)
        host.frame = NSRect(origin: .zero, size: size)
        let window = NSWindow(contentRect: host.frame.offsetBy(dx: -20_000, dy: -20_000), styleMask: [.borderless],
                              backing: .buffered, defer: false)
        window.appearance = NSAppearance(named: mode == .dark ? .darkAqua : .aqua)
        window.contentView = host
        window.orderFrontRegardless()
        defer { window.orderOut(nil) }
        host.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.3))
        host.layoutSubtreeIfNeeded()
        let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: url)
    }
}

/// A channel read that never answers, so a list renders its first-read state.
@MainActor
private final class Snapshot2HangingItemsAPI: ChannelItemsAPI {
    func fetchChannelItems(channel: String, offset: Int, limit: Int, etag: String?) async throws
        -> Conditional<ChannelItemsPage> {
        try await Task.sleep(for: .seconds(600))
        throw APIError.serverUnreachable
    }
}

private final class Snapshot2SkillsAPI: SkillsAPI, @unchecked Sendable {
    var page = SkillsPageData()

    func skillsPage() async throws -> SkillsPageData { page }
    func checkSkillUpdates(auto: Bool) async throws {}
    func previewSkill(source: String, choose: String?) async throws -> SkillPreview { SkillPreview() }
    func installSkill(planId: String?, suggestion: String?, agents: [String], requestId: String?) async throws
        -> SkillJob? { nil }
    func updateSkill(_ name: String, requestId: String?) async throws -> SkillJob? { nil }
    func updateAllSkills() async throws -> SkillJob? { nil }
    func setSkill(_ name: String, agent: String, on: Bool, requestId: String?) async throws {}
    func refreshSkill(_ name: String, requestId: String?) async throws {}
    func removeSkill(_ name: String) async throws {}
    func publishDraft(_ name: String, agents: [String]) async throws {}
    func discardDraft(_ name: String) async throws {}
    func dismissSkillRequest(_ id: String) async throws {}
    func skillJob(_ id: String) async throws -> SkillJob { SkillJob(id: id, kind: "update", label: "x", state: "done") }
    func skillsOnboarding() async throws -> SkillsOnboardingOffer { SkillsOnboardingOffer() }
    func answerSkillsOnboarding(install: [String], agents: [String]) async throws -> SkillJob? { nil }
}
