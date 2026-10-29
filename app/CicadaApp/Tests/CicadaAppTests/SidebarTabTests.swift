import XCTest
@testable import CicadaApp

/// G68 §1 — nine rows (G108 added Home at ⌘1; G141 PJ-5 added Projects at ⌘8; design taste added Looks at ⌘9 and the
/// owner moved looks onto their pages on 2026-10-20, so it went; the Sleep
/// redesign retired the Feed and gave its ⌘4 to Skills, 2026-10-16, ⌘ map A; ruling 36 D6 appended Agents at ⌘9,
/// 2026-10-22), stable
/// identities, and a decoder that survives a
/// selection written by an older build.
@MainActor
final class SidebarTabTests: XCTestCase {

    /// G108 ruled (spec decision 12): Home is the front door at ⌘1, Graph follows at ⌘2.
    /// Looks on pages (owner 2026-10-20): the ninth page, Looks, went — a look lives on the page of the thing it shows.
    /// Ruling 36 D6 (2026-10-22): Agents became a sidebar page, appended at the end so nothing before it moved (DR-22).
    func testTheSidebarIsNineRowsInVisualOrder() {
        XCTAssertEqual(AppTab.allCases, [.home, .graph, .clusters, .skills, .sleep, .inbox, .sources, .projects, .agents,
                                        .traces])
    }

    /// ⌘ map A (owner, 2026-10-16) — Skills takes the Feed's ⌘4 and nothing else moves: every shortcut a person
    /// learned still opens the page it opened.
    func testMapANothingButTheFeedsCellMoves() {
        XCTAssertEqual(AppTab.allCases.map { RailItem.shortcut(for: $0) },
                       ["⌘1", "⌘2", "⌘3", "⌘4", "⌘5", "", "⌘7", "⌘8", "⌘9", ""],
                       "Traces, the tenth page (2026-10-26), has no digit: ⌘0 is Actual Size; the Inbox left the rail "
                       + "and ⌘6 stays unused (ruling 48 (2))")
        XCTAssertEqual(RailItem.shortcut(for: .skills), "⌘4")
        XCTAssertEqual(RailItem.shortcut(for: .sleep), "⌘5")
        XCTAssertEqual(RailItem.shortcut(for: .inbox), "", "ruling 48 (2): ⌘6 is left unused, nothing moved into it")
        XCTAssertEqual(RailItem.shortcut(for: .agents), "⌘9", "Agents took the free ninth cell (ruling 36 D6)")
    }

    /// The one-time hint: only the key (⌘ held), only on Skills, only once per viewer.
    func testTheFeedMovedHintShowsOnceAndOnlyForTheKey() {
        XCTAssertTrue(FeedMovedHint.shouldShow(tab: .skills, commandHeld: true, alreadyShown: false))
        XCTAssertFalse(FeedMovedHint.shouldShow(tab: .skills, commandHeld: false, alreadyShown: false), "a click meant Skills")
        XCTAssertFalse(FeedMovedHint.shouldShow(tab: .skills, commandHeld: true, alreadyShown: true), "never again")
        XCTAssertFalse(FeedMovedHint.shouldShow(tab: .sleep, commandHeld: true, alreadyShown: false))
        XCTAssertEqual(Copy.feedMovedHint, "The Feed is now part of Sleep (⌘5) → Saved.")
    }

    /// Raw values ARE the persisted identity. A surviving tab must never
    /// change its own.
    func testSurvivingRawValuesAreUnchanged() {
        XCTAssertEqual(AppTab.home.rawValue, "Home")
        XCTAssertEqual(AppTab.graph.rawValue, "Graph")
        XCTAssertEqual(AppTab.clusters.rawValue, "Clusters")
        XCTAssertEqual(AppTab.skills.rawValue, "Skills")
        XCTAssertEqual(AppTab.sleep.rawValue, "Sleep")
        XCTAssertEqual(AppTab.inbox.rawValue, "Inbox")
        XCTAssertEqual(AppTab.sources.rawValue, "Sources")
        XCTAssertEqual(AppTab.projects.rawValue, "Projects")
        XCTAssertEqual(AppTab.agents.rawValue, "Agents")
        XCTAssertEqual(AppTab.traces.rawValue, "Traces")
    }

    // MARK: Hidden pages (owner 2026-10-26)

    /// Projects is hidden behind its one switch, and Traces shows only once traces were ever on; the cells that stay
    /// keep their digits (DR-22) — ⌘8 simply opens nothing while Projects is away.
    func testHiddenPagesLeaveTheRailAndNoDigitMoves() {
        XCTAssertTrue(PageSwitches.projectsPage, "ruling 45 (2026-10-27): back on with the redesign")
        XCTAssertEqual(AppTab.shown(tracesPage: false, projectsPage: false),
                       [.home, .graph, .clusters, .skills, .sleep, .sources, .agents])
        XCTAssertEqual(AppTab.shown(tracesPage: true).last, .traces)
        XCTAssertEqual(AppTab.shown(tracesPage: false),
                       [.home, .graph, .clusters, .skills, .sleep, .sources, .projects, .agents],
                       "the switch brings Projects back where it was")
        XCTAssertEqual(AppTab.shown(tracesPage: false, projectsPage: false).map { RailItem.shortcut(for: $0) },
                       ["⌘1", "⌘2", "⌘3", "⌘4", "⌘5", "⌘7", "⌘9"])
    }

    /// Every door to a hidden page lands where its content is now: a stored "Projects" selection, a ⌘K row, a hand-off.
    func testAHiddenPageLandsWhereItsContentIs() {
        XCTAssertEqual(AppTab.projects.landing(tracesPage: true, projectsPage: false), .clusters)
        XCTAssertEqual(AppTab.projects.landing(tracesPage: true, projectsPage: true), .projects)
        XCTAssertEqual(AppTab.traces.landing(tracesPage: false), .sources)
        XCTAssertEqual(AppTab.traces.landing(tracesPage: true), .traces)
        XCTAssertEqual(AppTab.restored(from: "Projects").landing(tracesPage: false, projectsPage: false), .clusters)
        XCTAssertEqual(AppTab.restored(from: "Projects").landing(tracesPage: false), .projects)
        XCTAssertEqual(AppTab.restored(from: "Traces").landing(tracesPage: false), .sources)
        for tab in AppTab.allCases where tab != .projects && tab != .traces {
            XCTAssertEqual(tab.landing(tracesPage: false), tab)
        }
    }

    /// The Traces page is on the rail while traces are on, or once they were ever on; never before, and a Wipe (which
    /// clears the consent and every day) takes it away.
    func testTheTracesPageShowsOnceTracesWereEverOn() {
        var settings = TraceSettings()
        var status = TraceStoreStatus()
        XCTAssertFalse(TracesPageVisibility.shown(settings: settings, status: status))
        settings.enabled = true
        XCTAssertTrue(TracesPageVisibility.shown(settings: settings, status: status))
        settings.enabled = false
        settings.consentedAt = "2026-10-20T09:00:00Z"
        XCTAssertTrue(TracesPageVisibility.shown(settings: settings, status: status), "turned off, still ever on")
        settings.consentedAt = nil
        status.days = 2
        XCTAssertTrue(TracesPageVisibility.shown(settings: settings, status: status), "days still kept")
    }

    /// CIC8 (2026-10-29) — the import is an action a person holding an export can find by typing what they hold, on
    /// ⌘K and on Home's field (the same index), with File → Import…'s shortcut.
    func testThePaletteFindsTheImportByWhatPeopleType() {
        let docs = PaletteActions.docs(QuickIndexInputs())
        let row = docs.first { $0.row.destination == .action(.importFile) }
        XCTAssertNotNil(row)
        XCTAssertEqual(row?.row.trailing, "⇧⌘I")
        let index = QuickIndex.build(QuickIndexInputs())
        for typed in ["chatgpt", "claude export", "chat export", "import", "zip"] {
            XCTAssertTrue(index.query(typed).rows.contains { $0.destination == .action(.importFile) }, typed)
        }
    }

    /// ⌘K offers only the pages the rail shows, each with its own digit.
    func testThePaletteGoesOnlyToShownPages() {
        let titles = { (traces: Bool) in
            PaletteActions.docs(QuickIndexInputs(tracesPage: traces)).map(\.row.title).filter { $0.hasPrefix("Go to ") }
        }
        XCTAssertTrue(titles(false).contains("Go to Projects"), "ruling 45: the page is back")
        XCTAssertFalse(titles(false).contains("Go to Traces"))
        XCTAssertTrue(titles(true).contains("Go to Traces"))
        let agents = PaletteActions.docs(QuickIndexInputs()).first { $0.row.title == "Go to Agents" }
        XCTAssertEqual(agents?.row.trailing, "⌘9")
    }

    /// The six retired raw values still exist in some user's defaults. Each
    /// must land on the page that inherited its content — never trap, never
    /// silently show the wrong thing. G124: Activity itself retired into
    /// Sources, taking the two G68 aliases with it.
    func testRetiredTabsFallBackToWhereTheirContentWent() {
        XCTAssertEqual(AppTab.restored(from: "Capture"), .sleep)
        XCTAssertEqual(AppTab.restored(from: "Feed"), .sleep, "the Feed is Sleep's Saved tab (2026-10-16)")
        XCTAssertEqual(AppTab.restored(from: "Activity"), .sources)
        XCTAssertEqual(AppTab.restored(from: "Contributors"), .sources)
        XCTAssertEqual(AppTab.restored(from: "Usage"), .sources)
        XCTAssertEqual(AppTab.restored(from: "Connections"), .graph)
        XCTAssertEqual(AppTab.restored(from: "Connect"), .graph)
        XCTAssertEqual(AppTab.restored(from: "Looks"), .clusters, "Looks went to the pages; Clusters filters to them")
    }

    func testUnknownOrMissingSelectionsFallBackToHome() {
        XCTAssertEqual(AppTab.restored(from: nil), .home, "a fresh install opens on the front door")
        XCTAssertEqual(AppTab.restored(from: ""), .home)
        XCTAssertEqual(AppTab.restored(from: "Nudges"), .home)
    }

    /// Relaunch restores the last tab, so nobody who lives in the graph is moved (D-3b: no).
    func testAStoredGraphSelectionStaysOnGraph() {
        XCTAssertEqual(AppTab.restored(from: "Graph"), .graph)
    }

    func testRoundTrippingASurvivingTabIsIdentity() {
        for tab in AppTab.allCases {
            XCTAssertEqual(AppTab.restored(from: tab.rawValue), tab)
        }
    }

    /// ⌘1–9 follow the visual order, and every row has an icon. Nine pages since Agents joined (ruling 36 D6,
    /// 2026-10-22), so every page still has a ⌘ slot — Skills at ⌘4, Agents at ⌘9. Traces (2026-10-26) is the tenth
    /// and the one page with none (DR-22: ⌘0 is Actual Size, and no shortcut moves to make room).
    func testEveryTabHasAShortcutSlotAndAnIcon() {
        XCTAssertEqual(AppTab.allCases.count, 10)
        XCTAssertEqual(AppTab.allCases.firstIndex(of: .home), 0, "⌘1 is Home")
        XCTAssertEqual(AppTab.allCases.firstIndex(of: .graph), 1, "⌘2 is Graph")
        XCTAssertNil(RailItem.key(for: .traces))
        for (index, tab) in AppTab.allCases.enumerated() {
            XCTAssertTrue(index < 9 || tab == .traces, "\(tab.rawValue) has no ⌘ slot")
            XCTAssertFalse(tab.icon.isEmpty, tab.rawValue)
            XCTAssertFalse(tab.icon.hasSuffix(".fill"), "DR-53: outline glyphs")
            XCTAssertEqual(tab.title, tab.rawValue, "the label and the identity must agree")
        }
    }

    /// The gear's attention dot (owner 2026-10-16): only when the engine the person CHOSE is a plan that is installed
    /// but signed out. A plan nobody chose, a key-based connection with no key ("not set up", not "expired") and a CLI
    /// that isn't installed never raise it.
    func testGearAttentionDotOnlyForTheChosenEngine() {
        func make(id: String, billing: String, available: Bool, connected: Bool) -> ConnectionStatus {
            ConnectionStatus(id: id, label: id, kind: billing, available: available,
                             connected: connected, plan: nil, planLabel: nil, tier: nil,
                             account: nil, priceUsdMonth: nil, priceNote: nil,
                             billing: billing, engineRole: nil, detail: nil,
                             how: nil, powers: [], login: nil)
        }
        func engine(_ selected: String) -> SleepEngineResponse {
            SleepEngineResponse(mode: selected, model: "", disambiguationModel: "", source: "prefs",
                                candidates: [], preview: nil, selected: selected)
        }
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let vm = ConnectionsViewModel(store: store)
        let signedOutClaude = make(id: "claude-plan", billing: "subscription", available: true, connected: false)
        let signedOutChatGPT = make(id: "chatgpt-plan", billing: "subscription", available: true, connected: false)

        store.connections.value = [make(id: "claude-plan", billing: "subscription", available: true, connected: true)]
        XCTAssertFalse(vm.needsAttention(engine: engine("agent")), "the chosen plan is signed in")

        store.connections.value = [signedOutClaude]
        XCTAssertTrue(vm.needsAttention(engine: engine("agent")), "the chosen plan is installed but signed out")

        // The QA case: the ChatGPT plan is available (its CLI is on the PATH) and signed out, but the person chose a key.
        store.connections.value = [signedOutChatGPT]
        XCTAssertFalse(vm.needsAttention(engine: engine("byok")), "a plan nobody chose is not the person's problem")
        XCTAssertTrue(vm.needsAttention(engine: engine("codex")), "the same plan, chosen, is")
        XCTAssertFalse(vm.needsAttention(engine: nil), "no engine read yet is no dot, never a guess")
        XCTAssertFalse(vm.needsAttention(engine: engine("auto")), "an automatic choice names no card")

        store.connections.value = [make(id: "openai-key", billing: "usage", available: true, connected: false)]
        XCTAssertFalse(vm.needsAttention(engine: engine("byok")), "a key that was never set is not an expired login")

        store.connections.value = [make(id: "claude-plan", billing: "subscription", available: false, connected: false)]
        XCTAssertFalse(vm.needsAttention(engine: engine("agent")), "a CLI that isn't installed can't have expired")
    }
}
