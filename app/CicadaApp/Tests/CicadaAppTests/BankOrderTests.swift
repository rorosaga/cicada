import XCTest
@testable import CicadaApp

/// app-fixes-1109 item 4 — the memory switcher's reorder and size rules.
final class BankOrderTests: XCTestCase {
    private func bank(_ name: String, _ entities: Int, _ episodes: Int) -> MemoryBank {
        MemoryBank(name: name, active: false, entityCount: entities, episodeCount: episodes, createdAt: "", description: nil)
    }

    func testADropMovesBeforeItsTargetAndAKeyMovesOnePlace() {
        let names = ["a", "b", "c", "d"]
        XCTAssertEqual(BankOrder.moved(names, "d", before: "b"), ["a", "d", "b", "c"])
        XCTAssertEqual(BankOrder.moved(names, "a", before: nil), ["b", "c", "d", "a"])
        XCTAssertEqual(BankOrder.moved(names, "b", before: "b"), names)
        XCTAssertEqual(BankOrder.moved(names, "ghost", before: "b"), names)
        XCTAssertEqual(BankOrder.nudged(names, "c", by: -1), ["a", "c", "b", "d"])
        XCTAssertEqual(BankOrder.nudged(names, "a", by: -1), names, "the ends stay")
    }

    func testTheGaugeIsRelativeToTheLargestAndNeverEmptyForAMemoryThatHoldsSomething() {
        let banks = [bank("big", 80, 120), bank("small", 1, 0), bank("empty", 0, 0)]
        XCTAssertEqual(BankOrder.fill(banks[0], among: banks), 1)
        XCTAssertEqual(BankOrder.fill(banks[1], among: banks), 0.06, "a sliver, not an empty track")
        XCTAssertEqual(BankOrder.fill(banks[2], among: banks), 0)
        XCTAssertEqual(BankOrder.fill(banks[0], among: []), 0)
    }
}
