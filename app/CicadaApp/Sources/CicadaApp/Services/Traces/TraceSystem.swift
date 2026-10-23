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
}

/// Screenshots (Screen Recording, ScreenCaptureKit). Only the front app's front window is captured — the window the
/// recorder already vetted (not private, not excluded) — never the whole display, so nothing behind it is taken.
protocol TraceScreenCapture: Sendable {
    /// `CGPreflightScreenCaptureAccess()` — never the requesting variant.
    func hasAccess() -> Bool
    func captureFrontWindow(pid: Int32, maxSide: Int) async throws -> TraceCapturedFrame
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
