import Foundation

// MARK: - Permissions as a designed flow (onboarding v3, 2026-10-24, after HeyClicky's permission rows)

/// The drag helper's first-person lines, one per state (`PermissionAsk`): drag me in when Cicada is not in the list,
/// flip my toggle on when it is, and reopen to apply it when macOS wants a fresh process. Calm, no "!" (DR-59).
extension Copy {
    /// The Full Disk Access fix's button (Messages, Safari), which shows the drag helper.
    static let allowFullDiskAccess = "Allow Full Disk Access…"

    enum Permission {
        static func line(_ kind: TracePermission, ask: PermissionAsk) -> String {
            switch ask {
            case .drag: Copy.Traces.need(kind)
            case .flip: flip(kind)
            case .reopen: reopenLine
            }
        }

        static func flip(_ kind: TracePermission) -> String {
            switch kind {
            case .screenRecording: "I'm already in the Screen Recording list. Flip my toggle on."
            case .accessibility: "I'm already in the Accessibility list. Flip my toggle on."
            case .fullDiskAccess: "I'm already in the Full Disk Access list. Flip my toggle on."
            }
        }

        static let reopenLine = "Already on? Reopen Cicada to apply it."
        static let reopen = "Reopen Cicada"
        static let alreadyOn = "Already on? Reopen Cicada"
        static let reopenHelp = "Quit and open Cicada again. You come back to this step."
        /// The row's link after the helper was closed with ×.
        static let retryHelp = "Show the helper again"

        /// Calendar and Contacts keep macOS's own prompt; once it was refused, the tile opens the exact list instead.
        static let deniedTile = "Turned off in macOS. Click to open the setting"

        static var labels: [String] {
            TracePermission.allCases.map(flip) + [reopenLine, reopen, alreadyOn, reopenHelp, retryHelp, deniedTile]
        }
    }
}
