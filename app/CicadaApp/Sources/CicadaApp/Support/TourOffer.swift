import Foundation

/// G152 — the one seam between onboarding's last page and the guided tour. Onboarding's "Open Cicada" asks for the
/// offer; Home answers it once with "Take a quick tour?". The two sides were built in parallel (round 4 phase B), so
/// neither knows the other's views — only this flag.
///
/// Per viewer, never per bank: the tour teaches the app, not a memory. A plain `UserDefaults` wrapper, like
/// `OnboardingState`, so a test can pass its own suite.
enum TourOffer {
    static let pendingKey = "cicada.tour.offerPending"

    /// Onboarding is done and the person chose to open Cicada: the next Home offers the tour.
    static func request(defaults: UserDefaults = .standard) {
        defaults.set(true, forKey: pendingKey)
    }

    /// True once per request — reading it clears it, so a relaunch never offers the tour twice.
    static func consume(defaults: UserDefaults = .standard) -> Bool {
        guard defaults.bool(forKey: pendingKey) else { return false }
        defaults.removeObject(forKey: pendingKey)
        return true
    }
}
