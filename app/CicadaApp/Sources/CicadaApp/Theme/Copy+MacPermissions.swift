import Foundation

// MARK: - Permissions, one row each (owner 2026-11-03, G92)

/// The Permissions step and Settings → Privacy & data's card: a name and one line per row — what it unlocks, never how
/// macOS works. Calm, no "!" (DR-59); apps are named, never a provider or model (provider-neutral copy).
extension Copy {
    enum MacPermissions {
        static let title = "A few permissions"
        static let subline = "Each one lets me read a little more. Allow what you like; skip the rest."
        static let settingsTitle = "Permissions"
        static let allowed = "Allowed"
        static let allow = "Allow…"
        static let openSetting = "Open setting"
        static let openSettingHelp = "Turned off in macOS. Opens the setting"
        static let allowHelp = "Opens the list in System Settings with my icon to drag in"
        static let askHelp = "macOS asks you once"
        static func count(_ granted: Int, of total: Int) -> String { "\(granted) of \(total) allowed" }

        static func name(_ permission: MacPermission) -> String {
            switch permission {
            case .fullDiskAccess: "Full Disk Access"
            case .contacts: "Contacts"
            case .calendars: "Calendars"
            case .reminders: "Reminders"
            case .chrome: "Control Chrome"
            case .notes: "Control Notes"
            case .notifications: "Notifications"
            case .accessibility: "Accessibility"
            case .screenRecording: "Screen Recording"
            case .localNetwork: Copy.LocalNetwork.name
            }
        }

        /// What the row unlocks, in one line.
        static func unlocks(_ permission: MacPermission) -> String {
            switch permission {
            case .fullDiskAccess: "Messages, Safari and WhatsApp"
            case .contacts: "Names and photos for the people you mention"
            case .calendars: "Your events"
            case .reminders: "The reminder lists you choose"
            case .chrome: "The page you save, and removing a bookmark when you ask"
            case .notes: "Apple Notes"
            case .notifications: "A nudge when an export is ready or an agent needs you"
            case .accessibility: "Window titles in traces"
            case .screenRecording: "Screenshots in traces"
            case .localNetwork: Copy.LocalNetwork.unlocks
            }
        }

        static var labels: [String] {
            MacPermission.allCases.flatMap { [name($0), unlocks($0)] }
                + [title, subline, settingsTitle, allowed, allow, openSetting, openSettingHelp, allowHelp, askHelp]
        }
    }
}
