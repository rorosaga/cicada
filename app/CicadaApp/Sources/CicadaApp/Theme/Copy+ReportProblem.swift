import Foundation

/// Report a problem (tester readiness, 2026-10-26) — the sheet's words. Provider-neutral; no price or account words.
extension Copy {
    enum ReportProblem {
        static let title = "Report a problem"
        static let menuItem = "Report a Problem…"
        static let settingsButton = "Report a problem…"
        static let settingsDetail = "Shows what a report holds before anything is sent."
        static let lead = "Read it first. It holds versions, which sources are on, and recent log lines with names, "
            + "links and paths taken out. It never holds your memory's pages or conversations."
        static let publicNote = "Send copies this report and opens a public GitHub issue: anyone can read what you paste "
            + "there."
        static let privateNote = "Send copies this report and opens a new message to Cicada's author."
        static let loading = "Gathering the report…"
        static let backendUnreachable = "(The memory service did not answer, so this report has no logs.)"
        static let copy = "Copy"
        static let copied = "Copied"
        static let save = "Save…"
        static let send = "Send"
        static let close = "Close"
        static let sendHelp = "Copies the report and opens the page to paste it in. Nothing is sent by itself."

        static var labels: [String] { [title, menuItem, settingsButton, copy, copied, save, send, close] }
    }
}
