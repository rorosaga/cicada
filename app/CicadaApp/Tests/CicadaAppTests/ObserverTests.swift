import XCTest
@testable import CicadaApp

/// G117 R2 — the wire protocol has exactly two reserved keywords, "agent"
/// and the "external:" prefix; ANY other string is the owner's own entity
/// id, whatever the bank's onboarding resolved it to. This is what makes
/// Task 1's backend fix (which can hand a claim's observer field a value
/// like "bob-example" instead of the literal "rodrigo") render correctly
/// without the app ever being told what that value is.
final class ObserverTests: XCTestCase {
    func testLegacyLiteralStillDecodesAsOwner() {
        XCTAssertEqual(Observer(wire: "rodrigo"), .rodrigo)
    }

    func testAnArbitraryResolvedSlugDecodesAsOwnerNotExternal() {
        XCTAssertEqual(Observer(wire: "bob-example"), .rodrigo)
        XCTAssertEqual(Observer(wire: "owner"), .rodrigo)
    }

    func testAgentAndExternalAreUnaffected() {
        XCTAssertEqual(Observer(wire: "agent"), .agent)
        XCTAssertEqual(Observer(wire: "external:karpathy-talk"), .external("karpathy-talk"))
    }
}
