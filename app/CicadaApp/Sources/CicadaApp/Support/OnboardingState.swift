import Foundation

/// G117 R5 — per-bank "has the first-run sheet run for this bank" flag.
///
/// No existing `@AppStorage`-of-a-dynamic-key precedent exists in this
/// codebase (that property wrapper's key must be static at the call site,
/// and the bank name is only known at runtime), so this is a small,
/// unit-testable wrapper over plain `UserDefaults.standard` instead — the
/// same fallback `UsageViewModel` already uses for a machine-global flag,
/// just keyed per bank here.
enum OnboardingState {
    static func isOnboarded(bank: String) -> Bool {
        UserDefaults.standard.bool(forKey: key(bank))
    }

    static func markOnboarded(bank: String) {
        UserDefaults.standard.set(true, forKey: key(bank))
    }

    /// Settings → General's "Run setup again" — clears the flag so the next
    /// `ContentView` check re-shows the sheet even on a non-empty bank.
    static func reset(bank: String) {
        UserDefaults.standard.removeObject(forKey: key(bank))
    }

    private static func key(_ bank: String) -> String { "cicada.hasOnboarded.\(bank)" }
}
