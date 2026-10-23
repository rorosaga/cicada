import Foundation

// MARK: - Onboarding: meet the bookworm (owner 2026-10-23)

/// The step that explains the menu-bar worm's number before it appears (`MenuBarStep`). What the number counts is
/// `StatusSnapshot.waitingForSleep` — `GET /status` `episodes.readable`, the conversations Sleep itself would read —
/// the badge's own source (`deriveBookwormState`), said in the menu bar's words ("12 conversations waiting for Sleep").
/// Plain words, no jargon: Sleep is said as what Cicada does, not as a page name. Under 40 words with the step's
/// buttons (`OnboardingStepsTests`).
extension Copy {
    enum MeetWorm {
        static let title = "Meet your bookworm"
        static let subline = "It lives in your menu bar."
        static let number = "Its number is how many conversations are waiting to become memory."
        static let goesDown = "When Cicada sleeps, it reads them and the number goes down."
        /// Under the worm while it counts an example (nothing waits yet), so the number is never read as the person's.
        static let example = "For example"
        /// Under the worm while it counts to the person's real waiting count: "3 waiting now".
        static func waitingNow(_ n: Int, locale: Locale = .autoupdatingCurrent) -> String {
            "\(UsageFormat.count(n, locale: locale)) waiting now"
        }
        /// The big worm's VoiceOver name: what it is and what its number means, once.
        static let imageLabel = "The menu-bar bookworm. Its number counts conversations waiting to become memory."
    }
}
