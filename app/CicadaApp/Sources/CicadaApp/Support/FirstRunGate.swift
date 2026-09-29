import Foundation

/// G117 — decides whether the four-step first-run sheet ("Who's using
/// Cicada?") may open. Pure, so the decision is testable without a window.
///
/// **The defect this exists to close.** The gate used to be an inline
/// expression in `ContentView.onAppear`:
/// `!OnboardingState.isOnboarded(bank: store.bank) && (store.graph.value?.nodes.isEmpty ?? true)`.
/// Both halves read state that had not arrived yet. `Store.bank` is still its
/// initial `"default"` until `Store.hydrate()` resolves the active bank out of
/// the cached roster, and `hydrate()` runs asynchronously from
/// `bootstrap()` — after this view's `.onAppear`. So `isOnboarded` was asked
/// about a bank the user may never have had, while `?? true` read "the graph
/// has not loaded yet" as "the graph is empty". On a cold launch of an
/// existing, fully onboarded bank both misreads lined up and the sheet opened
/// as a modal over the owner's real data.
///
/// **The rule.** Unknown is never empty. The sheet opens only once every input
/// is actually known: the roster has resolved which bank is active, that bank
/// has not been onboarded, the graph snapshot has loaded, and what loaded has
/// no nodes. A modal thrown over an unknown state is the worse failure — it
/// covers real memory and asks the owner to introduce themselves again. The
/// opposite failure is cheap and self-correcting: a genuinely fresh bank whose
/// first fetch has not landed shows `EmptyStateView` for a moment, and the
/// gate is re-evaluated (not just on `.onAppear`) the instant the bank or the
/// graph snapshot changes.
enum FirstRunGate {
    /// - Parameters:
    ///   - bankResolved: the bank roster snapshot has loaded, so `Store.bank`
    ///     names the active bank rather than the placeholder `"default"`.
    ///   - isOnboarded: `OnboardingState.isOnboarded(bank:)` for that bank.
    ///   - graphLoaded: the graph snapshot has a value. A hydrated on-disk
    ///     cache counts — serving the first frame from disk is the point of
    ///     the cache, and a cache hit is a real answer about this bank.
    ///   - graphIsEmpty: that loaded graph has no nodes.
    /// - Returns: `true` only when the bank is known, unonboarded, and its
    ///   graph has loaded and is empty.
    static func shouldShow(
        bankResolved: Bool,
        isOnboarded: Bool,
        graphLoaded: Bool,
        graphIsEmpty: Bool
    ) -> Bool {
        bankResolved && !isOnboarded && graphLoaded && graphIsEmpty
    }
}

/// Every new bank starts with its owner's page (`bank_registry.create_bank` →
/// `owner_identity.seed_owner_page`), so "the graph has no nodes" stopped being
/// the mark of a bank nobody has put anything in. **Empty means no node but the
/// owner's**: the first-run gate, the Graph's and Clusters' "Nothing here yet"
/// states read it, and a bank that has only its seeded owner page still meets
/// the Welcome and the drop-a-file target. `GraphNode.isOwner` is the
/// `owner: true` key, the same flag the seed writes.
extension Sequence where Element == GraphNode {
    var hasNoContentBeyondOwner: Bool { allSatisfy(\.isOwner) }
}

extension Sequence where Element == Entity {
    var hasNoContentBeyondOwner: Bool { allSatisfy(\.isOwner) }
}
