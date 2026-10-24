import AppKit
import Foundation

// Onboarding v3 (2026-10-24, after HeyClicky's permission flow) — what `PermissionDragHelper` remembers between two
// looks, and between two launches. All of it is pure or injected, so the tests never open System Settings, never read a
// real permission and never relaunch anything.

/// Where a permission was asked, so a relaunch comes back to the same step.
enum PermissionPlace: Equatable {
    /// Onboarding's Sources step; `browser` is the browser channel whose tick asked (Safari), started again on return.
    case onboarding(browser: String?)
    /// Sources → Traces (Screen Recording, Accessibility).
    case traces
    /// Anywhere else (Messages, a browser row, Home's Getting started): the Sources page.
    case sources

    var word: String {
        switch self {
        case .onboarding(let browser): browser.map { "onboarding:\($0)" } ?? "onboarding"
        case .traces: "traces"
        case .sources: "sources"
        }
    }

    init?(word: String) {
        switch word {
        case "traces": self = .traces
        case "sources": self = .sources
        case "onboarding": self = .onboarding(browser: nil)
        default:
            guard word.hasPrefix("onboarding:") else { return nil }
            let browser = String(word.dropFirst("onboarding:".count))
            self = .onboarding(browser: browser.isEmpty ? nil : browser)
        }
    }

    var isOnboarding: Bool { if case .onboarding = self { true } else { false } }
}

/// The marker a relaunch leaves for the next launch: which permission, asked where, and when. One key, read once and
/// cleared; a marker older than `maxAge` is stale (the person relaunched some other day) and is dropped unread.
///
/// Hyrum: a new key, `cicada.permission.resume`, holding `<kind>|<place>|<epoch seconds>`. Nothing else reads it.
struct PermissionResume: Equatable {
    static let defaultsKey = "cicada.permission.resume"
    /// Long enough for a slow relaunch, short enough that tomorrow's launch never reopens today's helper.
    static let maxAge: TimeInterval = 10 * 60

    let kind: TracePermission
    let place: PermissionPlace
    let at: Date

    var encoded: String { "\(kind.rawValue)|\(place.word)|\(Int(at.timeIntervalSince1970))" }

    static func decode(_ raw: String) -> PermissionResume? {
        let parts = raw.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
        guard parts.count == 3, let kind = TracePermission(rawValue: parts[0]),
              let place = PermissionPlace(word: parts[1]), let seconds = Double(parts[2]) else { return nil }
        return PermissionResume(kind: kind, place: place, at: Date(timeIntervalSince1970: seconds))
    }

    func save(_ defaults: UserDefaults = .standard) { defaults.set(encoded, forKey: Self.defaultsKey) }

    /// The marker, if one is waiting and fresh, for a caller that handles `matching` places — removed once read. A
    /// stale or unreadable marker is removed too; one for another caller's place is left for that caller.
    static func take(matching: (PermissionPlace) -> Bool, now: Date = Date(),
                     defaults: UserDefaults = .standard) -> PermissionResume? {
        guard let raw = defaults.string(forKey: defaultsKey) else { return nil }
        guard let marker = decode(raw), now.timeIntervalSince(marker.at) <= maxAge,
              now.timeIntervalSince(marker.at) >= -60 else {
            defaults.removeObject(forKey: defaultsKey)
            return nil
        }
        guard matching(marker.place) else { return nil }
        defaults.removeObject(forKey: defaultsKey)
        return marker
    }
}

/// Whether Cicada has been seen in a permission's list before. macOS has no question for "is this app in the list but
/// switched off" that does not prompt, so the helper keeps its own evidence: once a preflight has said yes, Cicada is
/// in that list, and a later no means its switch is off — "Flip my toggle on." rather than "Drag me in."
///
/// Hyrum: new keys `cicada.permission.seen.<kind>` (a Bool). Nothing else reads them.
struct PermissionMemory {
    let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    func inList(_ kind: TracePermission) -> Bool { defaults.bool(forKey: Self.key(kind)) }
    func noteGranted(_ kind: TracePermission) { defaults.set(true, forKey: Self.key(kind)) }

    static func key(_ kind: TracePermission) -> String { "cicada.permission.seen.\(kind.rawValue)" }
}

extension TracePermission {
    /// macOS applies these grants only to a fresh process: `CGPreflightScreenCaptureAccess` (and a protected file's
    /// open) can stay false until Cicada is reopened. Accessibility applies at once, so its poll alone ticks it.
    var needsRelaunch: Bool {
        switch self {
        case .screenRecording, .fullDiskAccess: true
        case .accessibility: false
        }
    }
}

/// Quits Cicada and opens it again. Live: leaves the marker, waits for this process to exit, then `open`s the bundle.
@MainActor
protocol AppRelauncher {
    func relaunch(resume: PermissionResume)
}

struct LiveAppRelauncher: AppRelauncher {
    func relaunch(resume: PermissionResume) {
        resume.save()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        // Positional arguments only — nothing is interpolated into the script. It waits for this pid to exit, then
        // opens the same bundle, as a person double-clicking it would.
        process.arguments = ["-c", "while /bin/kill -0 \"$1\" 2>/dev/null; do /bin/sleep 0.2; done; /usr/bin/open \"$2\"",
                             "sh", String(ProcessInfo.processInfo.processIdentifier), Bundle.main.bundlePath]
        do {
            try process.run()
        } catch {
            UserDefaults.standard.removeObject(forKey: PermissionResume.defaultsKey)
            return
        }
        NSApp.terminate(nil)
    }
}
