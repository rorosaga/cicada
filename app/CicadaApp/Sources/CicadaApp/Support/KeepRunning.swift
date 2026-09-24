import Foundation

/// F-06 (R-OB11, R-OB14) — the two lists, from what is true: with the app open, what keeps up; after quitting, what
/// waits — and whether agents' conversations are still saved depends on the background service (the app's own
/// backend stops with it). Apple Notes never appears as keeping up: it reads once and on Sync now (R-OB11).
enum KeepRunning {
    static func whileOpen() -> [String] {
        [Copy.keepOpenBrowsers, Copy.keepOpenCalendar, Copy.keepOpenAgents, Copy.keepOpenSleep]
    }

    static func afterQuit(backgroundRunning: Bool) -> [String] {
        backgroundRunning ? [Copy.keepQuitWaits, Copy.keepQuitAgentsSave, Copy.keepQuitSleep]
                          : [Copy.keepQuitWaits, Copy.keepQuitAgentsWait]
    }
}

/// F-05's and F-06's foot (R-OB17): "Everything stays…" only when nothing is read off this Mac (`LeavesMacNote` is
/// nil — Ollama, or Auto resolving to it); otherwise "Everything else stays…", because F-05 just said what leaves.
enum WhoReadsFoot {
    static func line(note: String?) -> String { note == nil ? Copy.privacyEverything : Copy.privacyEverythingElse }
}
