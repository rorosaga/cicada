import Foundation

// MARK: - EntityNavigationStack
//
// The "go deeper, then come back" history for an open entity card (bug 3 /
// G108 — this is the entity-card stack specifically, NOT an app-wide
// navigation model; G108 leaves that undecided). Pushing an entity remembers
// the one being left; popping returns to it, repeatedly, to arbitrary depth.
//
// Pure value type — no SwiftUI, no Observation — so push/pop/reset can be
// unit tested directly (`EntityNavigationStackTests`) without constructing a
// real `Entity` or spinning up a view. `GraphViewModel` and `TopicDetailView`
// each own one independent instance, keyed on `Entity`.
struct EntityNavigationStack<Element> {
    /// Entities visited before the current one, oldest first. The CURRENT
    /// entity itself is never stored here — it lives in whatever the owner
    /// already tracks separately (e.g. `GraphViewModel.selectedEntity`).
    private(set) var trail: [Element] = []

    var isEmpty: Bool { trail.isEmpty }
    var depth: Int { trail.count }

    /// The entry Back would return to, without popping. `nil` at the root —
    /// this is what a Back control reads to say what it goes back TO.
    var backTarget: Element? { trail.last }

    /// Remember `current` (the entity being left) so Back can return to it,
    /// then the caller moves forward to the destination. A `nil` `current`
    /// (nothing was open yet) is a no-op — there is nothing to remember.
    mutating func push(leaving current: Element?) {
        guard let current else { return }
        trail.append(current)
    }

    /// Pop and return the most recently visited entry, or `nil` at the root.
    @discardableResult
    mutating func pop() -> Element? {
        trail.popLast()
    }

    /// Drop the whole trail. Called whenever the user picks a different
    /// entity from OUTSIDE the card (a graph node click, a search/Ask jump)
    /// or switches to a different tab — a stale multi-level trail from an
    /// old exploration is worse than none.
    mutating func reset() {
        trail.removeAll()
    }
}
