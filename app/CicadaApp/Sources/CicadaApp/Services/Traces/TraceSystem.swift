import Foundation

/// G218 — every operating-system call activity traces make, behind a seam. The recorder and its tests see only these
/// protocols; the live implementations (`TraceSystemLive.swift`) are the only code that touches NSWorkspace,
/// Accessibility, Apple Events, ScreenCaptureKit, Vision or LocalAuthentication, and none of them ever calls an API
/// that raises a permission prompt on its own: every check is a preflight (`AXIsProcessTrusted`,
/// `CGPreflightScreenCaptureAccess`, `AEDeterminePermissionToAutomateTarget(askUserIfNeeded: false)`). Asking happens
/// only through the person's own click (`PermissionDragHelper` for Accessibility and Screen Recording; the browser's
/// own Automation prompt when they allow a browser).

/// The app in front.
struct TraceFrontApp: Equatable, Sendable {
    var bundleId: String
    var name: String
    var pid: Int32
}

/// The frontmost app and the moment it changes. No permission.
@MainActor
protocol TraceWorkspace: AnyObject {
    func frontmost() -> TraceFrontApp?
    /// Calls `handler` whenever another app comes to the front. Returns a token; dropping it stops the calls.
    func onActivation(_ handler: @escaping @MainActor () -> Void) -> AnyObject
}

/// Idle time, the locked screen and secure input. No permission.
protocol TraceIdleProbe: Sendable {
    func secondsSinceInput() -> TimeInterval
    func screenLocked() -> Bool
    /// A password field has focus somewhere (`IsSecureEventInputEnabled`): an automatic pause.
    func secureInput() -> Bool
}

/// The focused window's title (Accessibility).
protocol TraceWindowTitles: Sendable {
    /// `AXIsProcessTrusted()` — never the prompting variant.
    func trusted() -> Bool
    func focusedTitle(pid: Int32) -> String?
}

/// A Chromium browser's front tab, through Apple Events (Automation, per browser).
struct TraceBrowserTab: Equatable, Sendable {
    var url: String
    var title: String
    /// The front window's `mode` is `incognito`: nothing of this moment is recorded.
    var isPrivate: Bool
}

protocol TraceBrowserTabs: Sendable {
    /// Whether macOS already lets Cicada send this browser Apple Events, never asking.
    func granted(bundleId: String) -> Bool
    func frontTab(bundleId: String) async -> TraceBrowserTab?
}

/// One captured frame, already downscaled and encoded.
struct TraceCapturedFrame: Equatable, Sendable {
    var jpeg: Data
    var width: Int
    var height: Int
    /// Which connected screen (1 is the main one) of how many; 0 for a front-window frame.
    var display = 0
    var displays = 0
}

/// Which apps are browsers beyond the named list: every app macOS registers to open https: links (Launch Services, no
/// network). An unlisted browser — a beta, a fork, a new one — then fails closed (review of #456, B3).
protocol TraceBrowserRegistry: Sendable {
    func opensWebLinks(_ bundleId: String) -> Bool
}

/// The front window of an app, chosen from the window server's list, which is ordered front to back
/// (`CGWindowListCopyWindowInfo(.optionOnScreenOnly)`): the first normal-layer window that app owns. ScreenCaptureKit's
/// own window list has no documented order and counts covered windows as on screen, so it never chooses (B2).
enum TraceWindowPick {
    static func frontWindowID(in entries: [[String: Any]], pid: Int32) -> UInt32? {
        for entry in entries {
            guard (entry["kCGWindowOwnerPID"] as? Int).map(Int32.init) == pid
                    || (entry["kCGWindowOwnerPID"] as? Int32) == pid,
                  (entry["kCGWindowLayer"] as? Int ?? -1) == 0 else { continue }
            if let bounds = entry["kCGWindowBounds"] as? [String: Any],
               let w = bounds["Width"] as? Double, let h = bounds["Height"] as? Double, w < 64 || h < 64 {
                continue
            }
            if let id = entry["kCGWindowNumber"] as? Int { return UInt32(id) }
            if let id = entry["kCGWindowNumber"] as? UInt32 { return id }
        }
        return nil
    }
}

/// Screenshots (Screen Recording, ScreenCaptureKit).
///
/// **Front window** (consent sheet 1): the front app's front window only — the window the recorder already vetted.
/// **Every connected screen** (consent sheet 2, owner 2026-10-28): one frame per screen, each showing only the windows
/// of apps the policy may describe (`shown`) — every browser, chat or mail app (unless its titles were allowed), app
/// left out, password manager, notification banner and Cicada itself is cut out of the picture before it is taken
/// (`SCContentFilter(display:excludingApplications:exceptingWindows:)`), and a browser appears only through the one
/// front window whose tab was read and known not to be private (`keepFrontWindow`).
protocol TraceScreenCapture: Sendable {
    /// `CGPreflightScreenCaptureAccess()` — never the requesting variant.
    func hasAccess() -> Bool
    func captureFrontWindow(pid: Int32, maxSide: Int) async throws -> TraceCapturedFrame
    func captureScreens(frontPid: Int32, keepFrontWindow: Bool, maxSide: Int,
                        shown: @escaping @Sendable (String) -> Bool) async throws -> [TraceCapturedFrame]
}

/// On-device text recognition (Vision). Never a network service.
protocol TraceTextRecognizer: Sendable {
    func recognize(jpeg: Data) async -> String
}

/// Touch ID or the login password before screenshots are shown (LocalAuthentication).
protocol TraceAuthenticator: Sendable {
    func authenticate(reason: String) async -> Bool
}

/// Whether a permission is granted, by preflight only. `PermissionDragHelper` polls these.
enum TracePermission: String, CaseIterable, Sendable {
    case accessibility, screenRecording, fullDiskAccess
}

protocol TracePermissionProbe: Sendable {
    func granted(_ permission: TracePermission) -> Bool
}

/// The backend's traces routes — the only place a trace goes. Loopback only: the live client refuses when this app
/// talks to a server (`TraceBackendGate`), so a client Mac's traces never leave it.
protocol TraceBackend: Sendable {
    func traceSettings() async throws -> TraceSettingsAnswer
    func traceTurnOn(consentVersion: Int) async throws -> TraceSettingsAnswer
    func traceTurnOff() async throws -> TraceSettingsAnswer
    func traceUpdate(_ patch: [String: TracePatchValue]) async throws -> TraceSettingsAnswer
    func tracePause(until: String?) async throws -> TraceSettingsAnswer
    func traceSync(_ spans: [TraceSpan]) async throws -> TraceSyncResult
    func traceAddFrame(_ frame: TraceFramePost) async throws
    func traceTimeline(day: String) async throws -> TraceTimeline
    func traceSearch(_ query: String) async throws -> [TraceSearchHit]
    func traceFrameImage(id: String) async throws -> Data
    func traceFrameText(id: String) async throws -> TraceFrameText
    func traceForget(minutes: Int) async throws
    func traceWipe() async throws -> TraceSettingsAnswer
    // The page (2026-10-28): days as cards, deleting what the person picks, the digest's preview, what traces added.
    func traceDayCards() async throws -> [TraceDayCard]
    func traceDelete(day: String, spans: [String], frames: [String], all: Bool) async throws -> TraceDeleted
    func tracePreview(day: String?) async throws -> TraceDigestPreview
    func traceAdded() async throws -> TraceAdded
    func traceRemoveFromMemory() async throws -> TraceRemoval
    func traceUndoRemoval(id: String) async throws -> Int
}

/// A settings value on the wire (`PUT /sources/traces/settings`).
enum TracePatchValue: Equatable, Sendable, Encodable {
    case bool(Bool), int(Int), strings([String])

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .bool(let v): try c.encode(v)
        case .int(let v): try c.encode(v)
        case .strings(let v): try c.encode(v)
        }
    }
}

enum TraceBackendError: Error, Equatable {
    /// This app talks to a server: traces stay on the Mac that recorded them.
    case notThisMac
}

/// The one rule for where traces may be sent: This Mac's own backend, never a server (G181, G218).
enum TraceBackendGate {
    static func allows(_ connection: ServerConnection) -> Bool { !connection.isServer }
}
