import WebKit
import XCTest
@testable import CicadaApp

/// Audit 2026-10-02 A07/A08 — the graph wrapper's ownership and its on-screen bridge. A real `WKWebView` built by
/// `GraphView.makeWebView` (no page is loaded into a window; a nonpersistent store is not needed because nothing
/// is fetched), so a retain cycle between the web view, its content controller and the coordinator shows up as
/// an object that outlives every external owner.
@MainActor
final class GraphViewLifecycleTests: XCTestCase {

    private func makeViewModel() -> GraphViewModel {
        let cache = SnapshotCache(root: FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString))
        return GraphViewModel(store: Store(cache: cache, api: FakeSyncAPI()))
    }

    /// Lets WebKit finish any deferred release before the weak references are read.
    private func settle() {
        RunLoop.main.run(until: Date().addingTimeInterval(0.05))
    }

    func testTheWebViewAndCoordinatorDeallocateAfterTeardown() {
        let vm = makeViewModel()
        weak var weakWebView: WKWebView?
        weak var weakCoordinator: GraphView.Coordinator?
        autoreleasepool {
            let coordinator = GraphView.Coordinator(viewModel: vm)
            let webView = GraphView.makeWebView(coordinator: coordinator)
            weakWebView = webView
            weakCoordinator = coordinator
            GraphView.teardown(webView, coordinator: coordinator)
            XCTAssertNil(coordinator.webView)
        }
        settle()
        XCTAssertNil(weakWebView, "the graph web view outlived its owners")
        XCTAssertNil(weakCoordinator, "the coordinator outlived its owners")
    }

    func testDroppingTheOwnersAloneNoLongerLeaksTheWebView() {
        // The cycle itself is gone: even a path that never reaches dismantle releases the web view.
        let vm = makeViewModel()
        weak var weakWebView: WKWebView?
        autoreleasepool {
            let coordinator = GraphView.Coordinator(viewModel: vm)
            weakWebView = GraphView.makeWebView(coordinator: coordinator)
        }
        settle()
        XCTAssertNil(weakWebView)
    }

    func testRepeatedRecreationDoesNotAccumulateGraphInstances() {
        let vm = makeViewModel()
        var survivors: [() -> WKWebView?] = []
        for _ in 0..<3 {
            autoreleasepool {
                let coordinator = GraphView.Coordinator(viewModel: vm)
                let webView = GraphView.makeWebView(coordinator: coordinator)
                weak var weakWebView = webView
                survivors.append { weakWebView }
                GraphView.teardown(webView, coordinator: coordinator)
            }
        }
        settle()
        XCTAssertEqual(survivors.compactMap { $0() }.count, 0)
    }

    func testTheActiveBridgeIsALiteralCall() {
        XCTAssertEqual(GraphJS.setGraphActive(true), "setGraphActive(true)")
        XCTAssertEqual(GraphJS.setGraphActive(false), "setGraphActive(false)")
    }

    func testAReopenedWindowsPageIsToldItsStateOnceItIsReady() {
        // The view model's flag is app-wide and stays true after a window closes; a new page is not ready yet.
        let vm = makeViewModel()
        vm.isGraphReady = true
        let coordinator = GraphView.Coordinator(viewModel: vm)
        XCTAssertNil(coordinator.activeCall(wanted: false), "nothing is sent before this page reports ready")
        XCTAssertNil(coordinator.lastActive, "and nothing is latched")
        coordinator.isGraphReady = true
        XCTAssertEqual(coordinator.activeCall(wanted: coordinator.wantsActive), "setGraphActive(false)")
        XCTAssertNil(coordinator.activeCall(wanted: false), "latched: one push per change")
        XCTAssertEqual(coordinator.activeCall(wanted: true), "setGraphActive(true)")
    }

    func testTheCoordinatorHoldsTheWebViewWeakly() {
        let coordinator = GraphView.Coordinator(viewModel: makeViewModel())
        autoreleasepool {
            let webView = WKWebView()
            coordinator.webView = webView
        }
        settle()
        XCTAssertNil(coordinator.webView)
    }
}
