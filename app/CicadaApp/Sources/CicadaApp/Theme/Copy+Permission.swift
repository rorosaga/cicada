import Foundation

// MARK: - Permissions as a designed flow (onboarding v3, 2026-10-24, after HeyClicky's permission rows)

/// The drag helper's one line per state (`PermissionAsk`; owner 2026-11-03, one banner holding the app's icon): drag the
/// app in when it is not in the list, turn its switch on when it is, and reopen to apply it when macOS wants a fresh
/// process. Each says it once — no title repeated in a body. Calm, no "!" (DR-59).
extension Copy {
    /// The Full Disk Access fix's button (Messages, Safari), which shows the drag helper.
    static let allowFullDiskAccess = "Allow Full Disk Access…"

    enum Permission {
        static func line(_ kind: TracePermission, ask: PermissionAsk, app: String = "Cicada") -> String {
            switch ask {
            case .drag: Copy.Traces.need(kind, app: app)
            case .flip: flip(kind, app: app)
            case .reopen: reopenLine
            }
        }

        static func flip(_ kind: TracePermission, app: String = "Cicada") -> String {
            switch kind {
            case .screenRecording: "Turn on \(app)'s switch in Screen & System Audio Recording"
            case .accessibility: "Turn on \(app)'s switch in Accessibility"
            case .fullDiskAccess: "Turn on \(app)'s switch in Full Disk Access"
            }
        }

        /// The relaunch state's line; its one button says the act (`reopen`), so the line does not.
        static let reopenLine = "Already on? macOS applies it after a restart"
        static let reopen = "Reopen Cicada"
        static let alreadyOn = "Already on? Reopen Cicada"
        static let reopenHelp = "Quit and open Cicada again. You come back to this step."
        /// The row's link after the helper was closed with ×.
        static let retryHelp = "Show the helper again"

        /// Calendar and Contacts keep macOS's own prompt; once it was refused, the tile opens the exact list instead.
        static let deniedTile = "Turned off in macOS. Click to open the setting"

        static var labels: [String] {
            TracePermission.allCases.map { flip($0) } + [reopenLine, reopen, alreadyOn, reopenHelp, retryHelp, deniedTile]
        }
    }
}
