import XCTest
@testable import CicadaApp

/// PR #29 round 2 — the Clusters detail page's "go deeper" state. The view
/// used to fire one untracked Task per wikilink tap and assign whatever came
/// back, so a slow fetch landing after Back (or after a newer tap) silently
/// undid the navigation. `TopicDetailNavigation` is a pure value type: every
/// `navigate`/`goBack` mints a new generation, and a response is applied only
/// under the generation it was minted in. Same stub trick as
/// `EntityNavigationStackTests` — no real `Entity`, no view.
final class TopicDetailNavigationTests: XCTestCase {

    private struct Stub: Identifiable, Equatable {
        let id: String
        let name: String
    }

    private let a = Stub(id: "a", name: "A")
    private let b = Stub(id: "b", name: "B")
    private let c = Stub(id: "c", name: "C")
    /// A "full body" for `b` — same id, a different value, so a test can tell
    /// a stub from the fetched entity that upgrades it.
    private let fullB = Stub(id: "b", name: "B (full)")
    private let fullC = Stub(id: "c", name: "C (full)")

    // MARK: - Fresh

    func test_fresh_showsNothingPushed_hasNoBackTarget() {
        let nav = TopicDetailNavigation<Stub>()
        XCTAssertNil(nav.pushed)
        XCTAssertFalse(nav.canGoBack)
        XCTAssertNil(nav.backTarget?.name)
    }

    // MARK: - The reviewer's cases

    func test_navigateThenBack_ignoresTheLateResponse() {
        var nav = TopicDetailNavigation<Stub>()
        let token = nav.navigate(from: a, toStub: b)
        XCTAssertEqual(nav.pushed, b)
        XCTAssertEqual(nav.backTarget?.name, "A")

        nav.goBack(rootID: a.id)
        XCTAssertNil(nav.pushed, "back at the root, the view falls through to its own body")
        XCTAssertFalse(nav.canGoBack)

        XCTAssertFalse(nav.apply(fullB, token: token), "a response from before Back must be dropped")
        XCTAssertNil(nav.pushed, "…and must not re-open the entity the user just left")
        XCTAssertFalse(nav.canGoBack)
    }

    func test_aToBToC_withResponsesLandingCAB_endsOnC() {
        var nav = TopicDetailNavigation<Stub>()
        let tokenB = nav.navigate(from: a, toStub: b)
        let tokenC = nav.navigate(from: b, toStub: c)
        XCTAssertEqual(nav.pushed, c)

        // C's body lands first — it is the live navigation, so it applies.
        XCTAssertTrue(nav.apply(fullC, token: tokenC))
        XCTAssertEqual(nav.pushed, fullC)
        // A's body (the root's own `.task` load) is not routed through here at
        // all; then B's straggler arrives under a superseded token.
        XCTAssertFalse(nav.apply(fullB, token: tokenB))
        XCTAssertEqual(nav.pushed, fullC, "a superseded response must not overwrite the live card")

        // The trail is still A → B behind C.
        XCTAssertEqual(nav.backTarget?.name, "B")
        nav.goBack(rootID: a.id)
        XCTAssertEqual(nav.pushed, b)
        nav.goBack(rootID: a.id)
        XCTAssertNil(nav.pushed)
        XCTAssertFalse(nav.canGoBack)
    }

    // MARK: - The live response upgrades the stub

    func test_liveResponse_upgradesTheStubInPlace() {
        var nav = TopicDetailNavigation<Stub>()
        let token = nav.navigate(from: a, toStub: b)
        XCTAssertTrue(nav.apply(fullB, token: token))
        XCTAssertEqual(nav.pushed, fullB)
        XCTAssertEqual(nav.backTarget?.name, "A")
    }

    // MARK: - No stub: history is committed only when the body arrives

    func test_noStub_commitsHistoryOnlyWhenTheBodyArrives() {
        var nav = TopicDetailNavigation<Stub>()
        let token = nav.navigate(from: a, toStub: nil)
        XCTAssertNil(nav.pushed, "nothing to show yet")
        XCTAssertFalse(nav.canGoBack, "nothing accepted yet — no Back target")

        XCTAssertTrue(nav.apply(fullB, token: token))
        XCTAssertEqual(nav.pushed, fullB)
        XCTAssertEqual(nav.backTarget?.name, "A")
    }

    func test_noStub_failedOrSupersededFetch_leavesHistoryUntouched() {
        var nav = TopicDetailNavigation<Stub>()
        let stale = nav.navigate(from: a, toStub: nil)
        // The user taps another link before the first body arrives.
        _ = nav.navigate(from: a, toStub: c)
        XCTAssertEqual(nav.pushed, c)
        XCTAssertEqual(nav.backTarget?.name, "A")

        XCTAssertFalse(nav.apply(fullB, token: stale))
        XCTAssertEqual(nav.pushed, c)
        XCTAssertEqual(nav.backTarget?.name, "A", "the stale navigation must not add a trail entry")
        nav.goBack(rootID: a.id)
        XCTAssertNil(nav.pushed)
        XCTAssertFalse(nav.canGoBack)
    }
}
