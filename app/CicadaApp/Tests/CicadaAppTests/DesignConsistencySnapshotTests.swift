import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The design-consistency pass's review renders (2026-10-20): the pages whose head, disclosures and load states moved
/// onto the shared components, light and dark, offscreen. Env-gated: `CICADA_CONSISTENCY_SNAPSHOTS=<dir>`. The views
/// are built through their public inits only, so the same file renders the before (origin/dev) and the after.
@MainActor
final class DesignConsistencySnapshotTests: XCTestCase {
    func test_writeTheConvergedPagesForComparison() async throws {
        guard let dir = ProcessInfo.processInfo.environment["CICADA_CONSISTENCY_SNAPSHOTS"], !dir.isEmpty else {
            throw XCTSkip("set CICADA_CONSISTENCY_SNAPSHOTS=<dir> to write the review renders")
        }
        try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        defer { CicadaTheme.mode = .dark; CicadaTheme.uiScale = 1 }
        let out = URL(fileURLWithPath: dir)

        // Skills: a skill open beside the table, and a first read that failed.
        let api = SnapshotSkillsAPI()
        api.page = try JSONDecoder().decode(SkillsPageData.self, from: Data(SkillsPageTests.payload.utf8))
        let loaded = SkillsPageModel(api: api, pollInterval: .milliseconds(1))
        await loaded.load()
        let skillName = try XCTUnwrap(loaded.data?.installed.first?.name)
        let failing = SnapshotSkillsAPI()
        failing.fails = true
        let failed = SkillsPageModel(api: failing, pollInterval: .milliseconds(1))
        await failed.load()

        // Looks: a look open beside the board, and a board that could not be read.
        let refs = LooksTests.fixtures.map(\.0)
        let images = Dictionary(uniqueKeysWithValues: LooksTests.fixtures.map { ($0.0.id, $0.1) })
        let tile: (DesignRefSummary) -> AnyView = { ref in
            AnyView(Image(nsImage: images[ref.id]!).resizable().scaledToFill())
        }

        for mode in [AppColorScheme.light, .dark] {
            CicadaTheme.mode = mode
            let name = mode == .dark ? "dark" : "light"
            let skills = SkillsPageView(model: loaded, tab: .constant(nil), selected: .constant(skillName))
                .background(CicadaTheme.bgBase)
            try snapshot(skills, size: CGSize(width: 1180, height: 640), mode: mode,
                         to: out.appendingPathComponent("skills-open-\(name).png"))
            let skillsFailed = SkillsPageView(model: failed, tab: .constant(nil), selected: .constant(nil))
                .background(CicadaTheme.bgBase)
            try snapshot(skillsFailed, size: CGSize(width: 1000, height: 460), mode: mode,
                         to: out.appendingPathComponent("skills-failed-\(name).png"))

            let looks = PageLooksBlock(refs: refs, unplaced: [], entityId: "alpha-project", tile: tile,
                                       emptyOpen: .constant(false), onOpen: { _ in })
                .padding(24).frame(width: 720, alignment: .topLeading).background(CicadaTheme.bgBase)
            try snapshot(looks, size: CGSize(width: 720, height: 640), mode: mode,
                         to: out.appendingPathComponent("page-looks-\(name).png"))

            // Every folding section, side by side: Projects' detail and list, the entity card.
            let disclosures = VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                ProjectSectionHeader(title: "What happened", meta: "9", isOpen: false, toggle: {})
                ProjectSectionHeader(title: "Plan", meta: "", isOpen: true, toggle: {})
                ProjectsDisclosure(title: "Fading", count: 4, isOpen: false, help: "", action: {})
                CardDisclosure(title: "Where this came from", summary: "· 12", isOpen: .constant(false)) { EmptyView() }
                CardDisclosure(title: "Beliefs", isOpen: .constant(true)) {
                    Text("Open content").font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                }
            }
            .padding(24)
            .frame(width: 420, alignment: .leading)
            .background(CicadaTheme.bgPane)
            try snapshot(disclosures, size: CGSize(width: 420, height: 300), mode: mode,
                         to: out.appendingPathComponent("disclosures-\(name).png"))
        }
    }

    private func snapshot<V: View>(_ view: V, size: CGSize, mode: AppColorScheme, to url: URL) throws {
        let host = NSHostingView(rootView: view.environment(\.colorScheme, mode == .dark ? .dark : .light))
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

private struct SnapshotFailure: LocalizedError {
    var errorDescription: String? { "The server didn't answer." }
}

private final class SnapshotSkillsAPI: SkillsAPI, @unchecked Sendable {
    var page = SkillsPageData()
    var fails = false

    func skillsPage() async throws -> SkillsPageData {
        if fails { throw SnapshotFailure() }
        return page
    }
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
    func setSkillKind(key: String, kind: String?) async throws {}
}
