import Foundation

// Onboarding's Permissions step (owner 2026-11-03, G92): every macOS permission Cicada's app can use, one row each, its
// state live and its one button doing the right thing for that kind. The decisions are here, pure, so the step and
// Settings → Privacy & data render the same rows and the rules are tested without a window (`MacPermissionsTests`).
//
// **Never a probe that asks.** Every state is a preflight: `AXIsProcessTrusted`, `CGPreflightScreenCaptureAccess`, a
// protected file's open (Full Disk Access has no API), the frameworks' `authorizationStatus`, the notification
// centre's settings, and `AEDeterminePermissionToAutomateTarget(askUserIfNeeded: false)`. A prompt appears only from
// the row's own button, the person's click (`MacPermissionAsker`).

/// One permission macOS keeps for Cicada's app.
enum MacPermission: String, CaseIterable, Identifiable, Sendable {
    case fullDiskAccess, contacts, calendars, reminders, chrome, notes, notifications, accessibility, screenRecording
    /// G132 ruling 51f: asked only by the first-share step (owner D4), never in onboarding's list.
    case localNetwork

    var id: String { rawValue }

    /// How macOS grants it.
    enum Way: Equatable, Sendable {
        /// A Privacy & Security list Cicada is dragged into (or switched on in): no prompt exists.
        case drag(TracePermission)
        /// macOS's own one-time prompt; once refused, only the setting.
        case prompt
        /// Apple Events to one app: macOS's prompt, which needs that app running.
        case automation(bundleId: String)
    }

    var way: Way {
        switch self {
        case .fullDiskAccess: .drag(.fullDiskAccess)
        case .accessibility: .drag(.accessibility)
        case .screenRecording: .drag(.screenRecording)
        // Local Network has no preflight: macOS's prompt comes from the app's first Bonjour call (`LanDiscovery.ask`).
        case .contacts, .calendars, .reminders, .notifications, .localNetwork: .prompt
        case .chrome: .automation(bundleId: Self.chromeBundleId)
        case .notes: .automation(bundleId: Self.notesBundleId)
        }
    }

    /// Accessibility and Screen Recording serve activity traces alone (G218), which are off by default.
    var isTraces: Bool { self == .accessibility || self == .screenRecording }

    /// The installed app whose icon the row wears (`LogoTile`, DR-52); nil draws the row's glyph.
    var appBundleId: String? {
        switch self {
        case .contacts: "com.apple.AddressBook"
        case .calendars: "com.apple.iCal"
        case .reminders: "com.apple.reminders"
        case .chrome: Self.chromeBundleId
        case .notes: Self.notesBundleId
        case .fullDiskAccess, .notifications, .accessibility, .screenRecording, .localNetwork: nil
        }
    }

    var glyph: String {
        switch self {
        case .fullDiskAccess: "externaldrive"
        case .notifications: "bell"
        case .accessibility: "macwindow"
        case .screenRecording: "rectangle.dashed"
        case .localNetwork: "network"
        default: "app"
        }
    }

    static let chromeBundleId = "com.google.Chrome"
    static let notesBundleId = "com.apple.Notes"

    /// The exact list in System Settings, by its deep link (`x-apple.systempreferences:`). Privacy & Security's anchors
    /// are the long-standing `Privacy_*` names, which current macOS still resolves; Notifications is its own pane, opened
    /// on Cicada's own entry when the bundle has an identifier.
    func settingsURL(bundleId: String? = Bundle.main.bundleIdentifier) -> URL {
        let security = "x-apple.systempreferences:com.apple.preference.security?"
        let raw: String
        switch self {
        // The drag helper's own three (`PermissionDragHelperModel.settingsURL`), spelled the same.
        case .fullDiskAccess: raw = security + "Privacy_AllFiles"
        case .accessibility: raw = security + "Privacy_Accessibility"
        case .screenRecording: raw = security + "Privacy_ScreenCapture"
        case .contacts: raw = security + "Privacy_Contacts"
        case .calendars: raw = security + "Privacy_Calendars"
        case .reminders: raw = security + "Privacy_Reminders"
        case .chrome, .notes: raw = security + "Privacy_Automation"
        case .localNetwork: raw = security + "Privacy_LocalNetwork"
        case .notifications:
            raw = "x-apple.systempreferences:com.apple.Notifications-Settings.extension"
                + (bundleId.map { "?id=\($0)" } ?? "")
        }
        // swiftlint:disable:next force_unwrapping
        return URL(string: raw)!
    }
}

/// What a preflight says.
enum MacPermissionState: Equatable, Sendable {
    case granted
    /// Not asked yet, or (for a drag list) not switched on.
    case notYet
    /// Refused in macOS's prompt: macOS never asks again, so only the setting can change it.
    case denied
}

/// The row's one control.
enum MacPermissionAction: Equatable {
    /// Granted: a green dot and its word, no button.
    case none
    /// A drag list: open the exact list and float the drag helper over it (`PermissionDragHelper`).
    case drag(TracePermission)
    /// macOS's own prompt, on this click only.
    case ask
    /// Refused before: open the exact list, where its switch is.
    case openSettings
}

enum MacPermissionRows {
    /// The rows this Mac shows, in order: what reads the person's own things first, then the apps Cicada asks to act
    /// in, then notifications. Chrome only when it is installed. Traces' two only while traces are on — off by default,
    /// and their own consent sheet asks for them when the person turns traces on (ruling 38). Local Network never: it
    /// is asked only when the person first shares a memory or adds a device (G132, owner D4).
    static func visible(tracesOn: Bool, chromeInstalled: Bool) -> [MacPermission] {
        MacPermission.allCases.filter { permission in
            if permission == .localNetwork { return false }
            if permission.isTraces { return tracesOn }
            if permission == .chrome { return chromeInstalled }
            return true
        }
    }

    static func action(_ permission: MacPermission, state: MacPermissionState?) -> MacPermissionAction {
        if state == .granted { return .none }
        switch permission.way {
        case .drag(let kind): return .drag(kind)
        case .prompt, .automation: return state == .denied ? .openSettings : .ask
        }
    }

    /// `AEDeterminePermissionToAutomateTarget`'s answer as a state: nil when it cannot say (the app is not running,
    /// -600, or anything unexpected) — the last answer seen then stands (`AutomationMemory`).
    static func automationState(_ status: Int32) -> MacPermissionState? {
        switch status {
        case 0: .granted
        case -1743: .denied       // errAEEventNotPermitted
        case -1744: .notYet       // errAEEventWouldRequireUserConsent
        default: nil              // procNotFound (-600): not running
        }
    }

    /// The step's count line: how many of the shown rows are allowed.
    static func grantedCount(_ permissions: [MacPermission], states: [MacPermission: MacPermissionState]) -> Int {
        permissions.filter { states[$0] == .granted }.count
    }

    /// A row the person asked for that turned granted since the last look: the moment onboarding's one soft sound
    /// marks (DESIGN_RULES §9, 2026-10-24), and the drag helper's cue to close.
    static func newlyGranted(before: [MacPermission: MacPermissionState], after: [MacPermission: MacPermissionState],
                             asked: Set<MacPermission>) -> Set<MacPermission> {
        Set(asked.filter { after[$0] == .granted && before[$0] != .granted })
    }
}

/// The last Automation answer seen per app, so a row whose app is not running keeps its word instead of falling back
/// to "not yet". Hyrum: new keys `cicada.permission.automation.<bundle id>` (`granted` | `denied` | `notYet`); nothing
/// else reads them.
struct AutomationMemory {
    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    static func key(_ bundleId: String) -> String { "cicada.permission.automation.\(bundleId)" }

    func last(_ bundleId: String) -> MacPermissionState? {
        switch defaults.string(forKey: Self.key(bundleId)) {
        case "granted": .granted
        case "denied": .denied
        case "notYet": .notYet
        default: nil
        }
    }

    func note(_ bundleId: String, _ state: MacPermissionState) {
        let word = switch state {
        case .granted: "granted"
        case .denied: "denied"
        case .notYet: "notYet"
        }
        defaults.set(word, forKey: Self.key(bundleId))
    }
}

/// Reads a permission's state. Never asks.
protocol MacPermissionProbe: Sendable {
    func state(_ permission: MacPermission) async -> MacPermissionState
}

/// Asks macOS for a prompt-kind permission (and Automation). Called only from the row's own button.
@MainActor
protocol MacPermissionAsker {
    func ask(_ permission: MacPermission) async
}
