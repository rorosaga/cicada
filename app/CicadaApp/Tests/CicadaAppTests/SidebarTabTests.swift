import XCTest
@testable import CicadaApp

/// G68 §1 — nine rows (G108 added Home at ⌘1; G141 PJ-5 added Projects at ⌘8; design taste added Looks at ⌘9; the Sleep
/// redesign retired the Feed and gave its ⌘4 to Skills, 2026-10-16, ⌘ map A), stable
/// identities, and a decoder that survives a
/// selection written by an older build.
@MainActor
final class SidebarTabTests: XCTestCase {

    /// G108 ruled (spec decision 12): Home is the front door at ⌘1, Graph follows at ⌘2.
    func testTheSidebarIsNineRowsInVisualOrder() {
        XCTAssertEqual(AppTab.allCases, [.home, .graph, .clusters, .skills, .sleep, .inbox, .sources, .projects, .looks])
    }

    /// ⌘ map A (owner, 2026-10-16) — Skills takes the Feed's ⌘4 and nothing else moves: every shortcut a person
    /// learned still opens the page it opened.
    func testMapANothingButTheFeedsCellMoves() {
        XCTAssertEqual(AppTab.allCases.map { RailItem.shortcut(for: $0) },
                       ["⌘1", "⌘2", "⌘3", "⌘4", "⌘5", "⌘6", "⌘7", "⌘8", "⌘9"])
        XCTAssertEqual(RailItem.shortcut(for: .skills), "⌘4")
        XCTAssertEqual(RailItem.shortcut(for: .sleep), "⌘5")
        XCTAssertEqual(RailItem.shortcut(for: .inbox), "⌘6")
        XCTAssertEqual(RailItem.shortcut(for: .looks), "⌘9")
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
        XCTAssertEqual(AppTab.looks.rawValue, "Looks")
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

    /// ⌘1–9 follow the visual order, and every row has an icon. Nine pages since the Feed folded into Sleep
    /// (2026-10-16), so every page has a ⌘ slot — Skills at ⌘4.
    func testEveryTabHasAShortcutSlotAndAnIcon() {
        XCTAssertEqual(AppTab.allCases.count, 9)
        XCTAssertEqual(AppTab.allCases.firstIndex(of: .home), 0, "⌘1 is Home")
        XCTAssertEqual(AppTab.allCases.firstIndex(of: .graph), 1, "⌘2 is Graph")
        for (index, tab) in AppTab.allCases.enumerated() {
            XCTAssertTrue(index < 9, "\(tab.rawValue) has no ⌘ slot")
            XCTAssertFalse(tab.icon.isEmpty, tab.rawValue)
            XCTAssertFalse(tab.icon.hasSuffix(".fill"), "DR-53: outline glyphs")
            XCTAssertEqual(tab.title, tab.rawValue, "the label and the identity must agree")
        }
    }

    /// The gear's attention dot: a subscription that is installed but signed
    /// out. A key-based connection with no key is "not set up", not "expired",
    /// and must not raise it.
    func testGearAttentionDotOnlyForAnExpiredSubscription() {
        func make(id: String, billing: String, available: Bool, connected: Bool) -> ConnectionStatus {
            ConnectionStatus(id: id, label: id, kind: billing, available: available,
                             connected: connected, plan: nil, planLabel: nil, tier: nil,
                             account: nil, priceUsdMonth: nil, priceNote: nil,
                             billing: billing, engineRole: nil, detail: nil,
                             how: nil, powers: [], login: nil)
        }
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        let vm = ConnectionsViewModel(store: store)

        store.connections.value = [make(id: "claude-plan", billing: "subscription", available: true, connected: true)]
        XCTAssertFalse(vm.needsAttention)

        store.connections.value = [make(id: "claude-plan", billing: "subscription", available: true, connected: false)]
        XCTAssertTrue(vm.needsAttention, "an installed but signed-out subscription needs attention")

        store.connections.value = [make(id: "openai-key", billing: "usage", available: true, connected: false)]
        XCTAssertFalse(vm.needsAttention, "a key that was never set is not an expired login")

        store.connections.value = [make(id: "claude-plan", billing: "subscription", available: false, connected: false)]
        XCTAssertFalse(vm.needsAttention, "a CLI that isn't installed can't have expired")
    }
}
