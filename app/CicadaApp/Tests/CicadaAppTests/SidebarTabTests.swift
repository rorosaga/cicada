import XCTest
@testable import CicadaApp

/// G68 §1 — six rows, stable identities, and a decoder that survives a
/// selection written by an older build.
@MainActor
final class SidebarTabTests: XCTestCase {

    func testTheSidebarIsSixRowsInVisualOrder() {
        XCTAssertEqual(AppTab.allCases, [.graph, .clusters, .feed, .sleep, .inbox, .activity])
    }

    /// Raw values ARE the persisted identity. A surviving tab must never
    /// change its own.
    func testSurvivingRawValuesAreUnchanged() {
        XCTAssertEqual(AppTab.graph.rawValue, "Graph")
        XCTAssertEqual(AppTab.clusters.rawValue, "Clusters")
        XCTAssertEqual(AppTab.feed.rawValue, "Feed")
        XCTAssertEqual(AppTab.sleep.rawValue, "Sleep")
        XCTAssertEqual(AppTab.inbox.rawValue, "Inbox")
        XCTAssertEqual(AppTab.activity.rawValue, "Activity")
    }

    /// The five retired raw values still exist in some user's defaults. Each
    /// must land on the page that inherited its content — never trap, never
    /// silently show the wrong thing.
    func testRetiredTabsFallBackToWhereTheirContentWent() {
        XCTAssertEqual(AppTab.restored(from: "Capture"), .feed)
        XCTAssertEqual(AppTab.restored(from: "Contributors"), .activity)
        XCTAssertEqual(AppTab.restored(from: "Usage"), .activity)
        XCTAssertEqual(AppTab.restored(from: "Connections"), .graph)
        XCTAssertEqual(AppTab.restored(from: "Connect"), .graph)
    }

    func testUnknownOrMissingSelectionsFallBackToGraph() {
        XCTAssertEqual(AppTab.restored(from: nil), .graph)
        XCTAssertEqual(AppTab.restored(from: ""), .graph)
        XCTAssertEqual(AppTab.restored(from: "Nudges"), .graph)
    }

    func testRoundTrippingASurvivingTabIsIdentity() {
        for tab in AppTab.allCases {
            XCTAssertEqual(AppTab.restored(from: tab.rawValue), tab)
        }
    }

    /// ⌘1–6 follow the visual order, and every row has an icon.
    func testEveryTabHasAShortcutSlotAndAnIcon() {
        XCTAssertEqual(AppTab.allCases.count, 6)
        for (index, tab) in AppTab.allCases.enumerated() {
            XCTAssertLessThan(index, 9, "\(tab.rawValue) has no ⌘ slot")
            XCTAssertFalse(tab.icon.isEmpty, tab.rawValue)
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
