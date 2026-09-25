import XCTest
@testable import CicadaApp

/// R-IA25 — a cold "Open With" delivers URLs before `.onAppear` attaches the router.
@MainActor
final class DockOpenQueueTests: XCTestCase {
    func testOpensWaitForTheRouterThenFlowStraightThrough() {
        let queue = DockOpenQueue()
        var seen: [[URL]] = []
        queue.receive([URL(fileURLWithPath: "/tmp/a.zip")])
        XCTAssertTrue(seen.isEmpty)
        queue.attach { seen.append($0) }
        queue.receive([URL(fileURLWithPath: "/tmp/b.json")])
        XCTAssertEqual(seen.map { $0.map(\.lastPathComponent) }, [["a.zip"], ["b.json"]])
    }
}
