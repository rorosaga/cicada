import Foundation

/// G117 R5 — per-bank "has the first-run sheet run for this bank" flag, plus (onboarding v2, 2026-10-22) the step a
/// person reached, so quitting mid-way resumes there instead of at Welcome.
///
/// No existing `@AppStorage`-of-a-dynamic-key precedent exists in this
/// codebase (that property wrapper's key must be static at the call site,
/// and the bank name is only known at runtime), so this is a small,
/// unit-testable wrapper over plain `UserDefaults` instead — the
/// same fallback `UsageViewModel` already uses for a machine-global flag,
/// just keyed per bank here.
///
/// Hyrum: `cicada.hasOnboarded.<bank>` keeps its key and meaning. The step is new; it is stored as the step's word
/// (`OnboardingPage.storedName`) and read back through `OnboardingPage(stored:)`, which also maps the seven-step
/// flow's names, so no stored value ever traps or lands on a step that no longer exists.
enum OnboardingState {
    static func isOnboarded(bank: String, defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: key(bank))
    }

    /// Finishing (or skipping) setup also forgets the step: a rerun starts at Welcome.
    static func markOnboarded(bank: String, defaults: UserDefaults = .standard) {
        defaults.set(true, forKey: key(bank))
        defaults.removeObject(forKey: stepKey(bank))
    }

    /// Settings → General's "Run setup again" — clears the flag so the next
    /// `ContentView` check re-shows the sheet even on a non-empty bank.
    static func reset(bank: String, defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: key(bank))
        defaults.removeObject(forKey: stepKey(bank))
    }

    /// The step to resume on, or nil (start at Welcome). Welcome itself is never a resume point, and Done resumes
    /// as Done (the person only had Open Cicada left).
    static func savedStep(bank: String, defaults: UserDefaults = .standard) -> OnboardingPage? {
        guard let raw = defaults.string(forKey: stepKey(bank)), let page = OnboardingPage(stored: raw),
              page != .welcome else { return nil }
        return page
    }

    static func saveStep(_ page: OnboardingPage, bank: String, defaults: UserDefaults = .standard) {
        defaults.set(page.storedName, forKey: stepKey(bank))
    }

    private static func key(_ bank: String) -> String { "cicada.hasOnboarded.\(bank)" }
    private static func stepKey(_ bank: String) -> String { "cicada.onboarding.step.\(bank)" }
}
