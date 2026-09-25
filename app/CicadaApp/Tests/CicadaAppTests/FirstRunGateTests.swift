import XCTest
@testable import CicadaApp

/// G117 — the first-run sheet used to open over an onboarded bank's real data
/// on every cold launch, because `ContentView` decided in `.onAppear`, before
/// `Store.hydrate()` had resolved the active bank and before the graph
/// snapshot had loaded: `isOnboarded` was asked about the placeholder bank and
/// `?? true` read "not loaded yet" as "empty". `FirstRunGate` is the pure
/// decision that replaced that expression, so the rule — unknown is never
/// empty — can be asserted without standing up a window.
final class FirstRunGateTests: XCTestCase {

    /// All 16 input combinations: exactly one may open the sheet.
    func testOnlyOneOfSixteenCombinationsOpensTheSheet() {
        var opened: [[Bool]] = []
        for bankResolved in [false, true] {
            for isOnboarded in [false, true] {
                for graphLoaded in [false, true] {
                    for graphIsEmpty in [false, true] {
                        let show = FirstRunGate.shouldShow(
                            bankResolved: bankResolved,
                            isOnboarded: isOnboarded,
                            graphLoaded: graphLoaded,
                            graphIsEmpty: graphIsEmpty
                        )
                        if show { opened.append([bankResolved, isOnboarded, graphLoaded, graphIsEmpty]) }
                    }
                }
            }
        }
        XCTAssertEqual(opened.count, 1, "exactly one of the 16 input combinations may open the sheet")
        XCTAssertEqual(opened.first, [true, false, true, true],
                       "bank resolved, not onboarded, graph loaded, graph empty")
    }

    /// The defect, stated directly: on a cold launch the bank has not been
    /// resolved and the graph has not loaded. Nothing is known, so nothing
    /// opens — whatever the stored onboarding flag happens to say about the
    /// placeholder bank name.
    func testColdLaunchWithUnresolvedBankAndUnloadedGraphStaysClosed() {
        XCTAssertFalse(FirstRunGate.shouldShow(
            bankResolved: false,
            isOnboarded: false,
            graphLoaded: false,
            graphIsEmpty: true
        ))
        // The same moment, one beat later: the graph is still unloaded even
        // once the roster has named the bank.
        XCTAssertFalse(FirstRunGate.shouldShow(
            bankResolved: true,
            isOnboarded: false,
            graphLoaded: false,
            graphIsEmpty: true
        ))
    }

    /// An onboarded bank never sees the sheet again, empty graph or not.
    func testOnboardedBankNeverOpensTheSheet() {
        XCTAssertFalse(FirstRunGate.shouldShow(
            bankResolved: true,
            isOnboarded: true,
            graphLoaded: true,
            graphIsEmpty: true
        ))
        XCTAssertFalse(FirstRunGate.shouldShow(
            bankResolved: true,
            isOnboarded: true,
            graphLoaded: true,
            graphIsEmpty: false
        ))
    }

    /// The case the sheet exists for: a fresh bank whose graph has actually
    /// loaded and really is empty.
    func testFreshBankWithALoadedEmptyGraphOpensTheSheet() {
        XCTAssertTrue(FirstRunGate.shouldShow(
            bankResolved: true,
            isOnboarded: false,
            graphLoaded: true,
            graphIsEmpty: true
        ))
    }

    /// An imported bank never gets the tour: it was never onboarded on this
    /// Mac, but it arrived with memory in it, so there is nothing to set up.
    func testFreshBankWithANonEmptyGraphNeverOpensTheSheet() {
        XCTAssertFalse(FirstRunGate.shouldShow(
            bankResolved: true,
            isOnboarded: false,
            graphLoaded: true,
            graphIsEmpty: false
        ))
    }
}
