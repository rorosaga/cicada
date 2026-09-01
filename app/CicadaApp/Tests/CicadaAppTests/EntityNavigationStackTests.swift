import XCTest
@testable import CicadaApp

/// Bug 3 / G108 — the entity card's "go deeper, then come back" trail.
/// `EntityNavigationStack` is a pure value type (no SwiftUI, no Observation)
/// so push/pop/reset can be asserted directly without constructing a real
/// `Entity` or spinning up a view. A tiny local stub stands in for whatever
/// `Element` the production owners (`GraphViewModel`, `TopicsView`'s
/// `TopicDetailView`) actually store.
final class EntityNavigationStackTests: XCTestCase {

    private struct Stub: Equatable {
        let id: String
        let name: String
    }

    private let alejandra = Stub(id: "alejandra-gomez", name: "Alejandra Gómez")
    private let camila = Stub(id: "camila-quintero", name: "Camila Quintero")
    private let diego = Stub(id: "diego-rivas", name: "Diego Rivas")

    // MARK: - Fresh stack

    func test_freshStack_isEmpty_hasNoBackTarget() {
        let stack = EntityNavigationStack<Stub>()
        XCTAssertTrue(stack.isEmpty)
        XCTAssertEqual(stack.depth, 0)
        XCTAssertNil(stack.backTarget)
    }

    // MARK: - Push

    func test_push_leavingNil_isNoOp() {
        var stack = EntityNavigationStack<Stub>()
        stack.push(leaving: nil)
        XCTAssertTrue(stack.isEmpty, "nothing was open yet — there is nothing to remember")
    }

    func test_push_remembersTheEntityBeingLeft() {
        var stack = EntityNavigationStack<Stub>()
        stack.push(leaving: alejandra)
        XCTAssertFalse(stack.isEmpty)
        XCTAssertEqual(stack.depth, 1)
        XCTAssertEqual(stack.backTarget, alejandra)
    }

    func test_push_toArbitraryDepth_keepsOldestAtTheBottom() {
        // Alejandra -> Camila -> Diego: pushing at each hop remembers the
        // entity being LEFT, so the trail should read oldest-first.
        var stack = EntityNavigationStack<Stub>()
        stack.push(leaving: alejandra) // leaving Alejandra to view Camila
        stack.push(leaving: camila)    // leaving Camila to view Diego
        XCTAssertEqual(stack.depth, 2)
        XCTAssertEqual(stack.trail, [alejandra, camila])
        // The MOST RECENT hop (Camila) is what Back returns to first.
        XCTAssertEqual(stack.backTarget, camila)
    }

    // MARK: - Pop

    func test_pop_onEmptyStack_returnsNil() {
        var stack = EntityNavigationStack<Stub>()
        XCTAssertNil(stack.pop())
    }

    func test_pop_returnsMostRecentlyVisited_thenTheOneBeforeIt() {
        var stack = EntityNavigationStack<Stub>()
        stack.push(leaving: alejandra)
        stack.push(leaving: camila)

        // "if I click it should take me to Camila's page and then if I
        // press go back it takes me to Alejandra, so I can just go deeper
        // and deeper" — the user's own description of the desired behavior.
        XCTAssertEqual(stack.pop(), camila)
        XCTAssertEqual(stack.pop(), alejandra)
        XCTAssertNil(stack.pop())
        XCTAssertTrue(stack.isEmpty)
    }

    func test_pop_toArbitraryDepth_unwindsInReverseOrder() {
        var stack = EntityNavigationStack<Stub>()
        stack.push(leaving: alejandra)
        stack.push(leaving: camila)
        stack.push(leaving: diego)
        XCTAssertEqual(stack.depth, 3)

        XCTAssertEqual(stack.pop(), diego)
        XCTAssertEqual(stack.depth, 2)
        XCTAssertEqual(stack.backTarget, camila)

        XCTAssertEqual(stack.pop(), camila)
        XCTAssertEqual(stack.pop(), alejandra)
        XCTAssertTrue(stack.isEmpty)
    }

    // MARK: - Reset

    func test_reset_dropsTheWholeTrail() {
        var stack = EntityNavigationStack<Stub>()
        stack.push(leaving: alejandra)
        stack.push(leaving: camila)
        stack.push(leaving: diego)
        XCTAssertEqual(stack.depth, 3)

        stack.reset()

        XCTAssertTrue(stack.isEmpty)
        XCTAssertNil(stack.backTarget)
        XCTAssertNil(stack.pop())
    }

    func test_reset_thenPush_startsAFreshTrail() {
        var stack = EntityNavigationStack<Stub>()
        stack.push(leaving: alejandra)
        stack.reset()

        stack.push(leaving: diego)

        XCTAssertEqual(stack.depth, 1)
        XCTAssertEqual(stack.backTarget, diego)
    }
}
