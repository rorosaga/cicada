import Foundation

// MARK: - TopicDetailNavigation
//
// The Clusters detail page's "go deeper, then come back" state — the trail,
// the entity currently shown over the page's root entity, and which in-flight
// full-body fetch is still allowed to land. Wraps `EntityNavigationStack` and
// is, like it, a pure value type so the two rules a view gets wrong are unit
// tested without SwiftUI (`TopicDetailNavigationTests`):
//
// 1. A response applies only under the generation it was minted in. Every
//    `navigate`/`goBack` bumps the generation, so a slow fetch that returns
//    after the user pressed Back (or tapped a newer link) is dropped instead
//    of overwriting the card they are now looking at.
// 2. History is committed only once a destination is ACCEPTED — a graph stub
//    on the spot, otherwise when its body arrives — so a link to an id the
//    bank doesn't have never mints a Back target (the same rule as
//    `GraphViewModel.pushEntity`).
//
// PR #29 round 2. `TopicDetailView` owns one instance as `@State` and cancels
// the previous fetch Task on every `navigate`/`goBack`; the token check here
// is what makes that cancellation safe to miss.
struct TopicDetailNavigation<Element: Identifiable> {
    /// Identifies one navigation. A fetch started by `navigate` presents it
    /// to `apply`; only the most recently minted token is honoured.
    typealias Token = UInt

    private var history = EntityNavigationStack<Element>()
    private var generation: Token = 0
    /// The entity left behind by a stub-less navigation still waiting on its
    /// body — pushed onto `history` only once that body lands.
    private var pendingOrigin: Element?
    /// The entity shown over the root; `nil` when the root itself is shown.
    private(set) var pushed: Element?

    var canGoBack: Bool { !history.isEmpty }
    /// The entry Back would return to, without popping — what the card's
    /// Back label names.
    var backTarget: Element? { history.backTarget }

    /// Start navigating away from `current`. A `stub` (the graph's cached
    /// placeholder) is shown at once and commits history immediately; with
    /// no stub nothing changes until `apply` lands the body.
    mutating func navigate(from current: Element, toStub stub: Element?) -> Token {
        generation += 1
        if let stub {
            pendingOrigin = nil
            history.push(leaving: current)
            pushed = stub
        } else {
            pendingOrigin = current
        }
        return generation
    }

    /// Land a fetched body. Returns `false` — and changes nothing — when
    /// `token` is no longer the current navigation.
    @discardableResult
    mutating func apply(_ full: Element, token: Token) -> Bool {
        guard token == generation else { return false }
        if let origin = pendingOrigin {
            history.push(leaving: origin)
            pendingOrigin = nil
        }
        pushed = full
        return true
    }

    /// Back. Invalidates whatever is in flight, then pops. Landing on the
    /// root (`rootID`) clears `pushed` so the view falls through to its own
    /// freshly-loaded body instead of pinning a possibly-stale snapshot.
    mutating func goBack(rootID: Element.ID) {
        generation += 1
        pendingOrigin = nil
        guard let previous = history.pop() else { return }
        pushed = previous.id == rootID ? nil : previous
    }
}
