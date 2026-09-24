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

/// F-07's lines (R-OB15), from real state: the agents Cicada saw connect, in catalog order, and how Cicada starts.
enum ReadySummary {
    static func agents(connected: Set<String>, locale: Locale = .autoupdatingCurrent) -> String? {
        let names = AgentCatalog.featured.filter { connected.contains($0.id) }.map(\.name)
        guard !names.isEmpty else { return nil }
        let formatter = ListFormatter()
        formatter.locale = locale
        return Copy.readyAgentsConnected(formatter.string(from: names) ?? names.joined(separator: ", "))
    }

    static func startup(opensAtLogin: Bool, menuBar: Bool) -> String? {
        switch (opensAtLogin, menuBar) {
        case (true, true): Copy.readyOpensAtLoginMenuBar
        case (true, false): Copy.readyOpensAtLogin
        case (false, true): Copy.readyMenuBar
        case (false, false): nil
        }
    }
}

/// F-01's marks row: every featured agent that has a real mark (DR-52) — a glyph never stands in on a welcome.
/// Main-actor because `LogoImage.exists` (a view's static) is.
@MainActor
enum WelcomeMarks {
    static var entries: [AgentCatalogEntry] {
        AgentCatalog.featured.filter { entry in entry.mark.map { LogoImage.exists(name: $0) } ?? false }
    }
}
