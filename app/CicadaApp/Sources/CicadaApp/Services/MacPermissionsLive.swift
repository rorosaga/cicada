import AppKit
import ApplicationServices
import Carbon.HIToolbox
import Contacts
import EventKit
import Foundation
import UserNotifications

/// The Permissions step's live seams: the only code that reads or asks for the rows' permissions. The probe never
/// calls a prompting API; the asker runs only from a row's own button. Tests inject fakes (`MacPermissionsTests`).
final class LiveMacPermissionProbe: MacPermissionProbe, @unchecked Sendable {
    private let drag: any TracePermissionProbe
    private let memory: AutomationMemory

    init(drag: any TracePermissionProbe = LiveTracePermissionProbe(), memory: AutomationMemory = AutomationMemory()) {
        self.drag = drag
        self.memory = memory
    }

    func state(_ permission: MacPermission) async -> MacPermissionState {
        switch permission.way {
        case .drag(let kind):
            return drag.granted(kind) ? .granted : .notYet
        case .automation(let bundleId):
            // Off the main thread: the check can block while the target app is busy.
            let status = await Task.detached(priority: .utility) { Self.automationStatus(bundleId, ask: false) }.value
            if let state = MacPermissionRows.automationState(status) {
                memory.note(bundleId, state)
                return state
            }
            return memory.last(bundleId) ?? .notYet
        case .prompt:
            return await promptState(permission)
        }
    }

    private func promptState(_ permission: MacPermission) async -> MacPermissionState {
        switch permission {
        case .contacts:
            switch CNContactStore.authorizationStatus(for: .contacts) {
            case .authorized: return .granted
            case .notDetermined: return .notYet
            default: return .denied   // refused or restricted, as `SystemContactStore.access` reads it
            }
        case .calendars: return Self.eventKit(EKEventStore.authorizationStatus(for: .event))
        case .reminders: return Self.eventKit(EKEventStore.authorizationStatus(for: .reminder))
        case .notifications:
            // The notification centre raises in a process with no app bundle (`swift test`, a bare binary).
            guard ReminderAvailability.current else { return .notYet }
            let settings = await UNUserNotificationCenter.current().notificationSettings()
            switch settings.authorizationStatus {
            case .notDetermined: return .notYet
            case .denied: return .denied
            default: return .granted
            }
        default: return .notYet
        }
    }

    /// Full access only: a write-only grant reads nothing, so it is "not yet" and the row asks for the rest.
    static func eventKit(_ status: EKAuthorizationStatus) -> MacPermissionState {
        switch status {
        case .fullAccess: .granted
        case .notDetermined, .writeOnly: .notYet
        default: .denied
        }
    }

    /// `AEDeterminePermissionToAutomateTarget` for one app by bundle id. `ask` false never shows the prompt.
    nonisolated static func automationStatus(_ bundleId: String, ask: Bool) -> Int32 {
        var target = AEAddressDesc()
        let bytes = Array(bundleId.utf8)
        let created = bytes.withUnsafeBytes { raw in
            AECreateDesc(DescType(typeApplicationBundleID), raw.baseAddress, raw.count, &target)
        }
        guard created == noErr else { return Int32(created) }
        defer { AEDisposeDesc(&target) }
        return AEDeterminePermissionToAutomateTarget(&target, AEEventClass(typeWildCard), AEEventID(typeWildCard), ask)
    }
}

/// The rows' asks — each the moment the person clicked that row, never a probe.
@MainActor
struct LiveMacPermissionAsker: MacPermissionAsker {
    /// Stateless, so constructible as a default argument outside the main actor.
    nonisolated init() {}

    func ask(_ permission: MacPermission) async {
        switch permission {
        case .contacts:
            _ = try? await CNContactStore().requestAccess(for: .contacts)
        case .calendars:
            _ = try? await EKEventStore().requestFullAccessToEvents()
        case .reminders:
            _ = try? await EKEventStore().requestFullAccessToReminders()
        case .notifications:
            guard ReminderAvailability.current else { return }
            _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
        case .chrome, .notes:
            guard case .automation(let bundleId) = permission.way, await Self.launchQuietly(bundleId) else { return }
            _ = await Task.detached(priority: .userInitiated) {
                LiveMacPermissionProbe.automationStatus(bundleId, ask: true)
            }.value
        case .fullDiskAccess, .accessibility, .screenRecording:
            return   // drag lists: the row shows the drag helper instead
        }
    }

    /// macOS asks for Automation only while the target app runs: on the person's click it is opened in the background
    /// (not brought forward, hidden), then asked once it has launched.
    private static func launchQuietly(_ bundleId: String) async -> Bool {
        func running() -> NSRunningApplication? {
            NSRunningApplication.runningApplications(withBundleIdentifier: bundleId).first { $0.isFinishedLaunching }
        }
        if running() != nil { return true }
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleId) else { return false }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = false
        configuration.hides = true
        guard (try? await NSWorkspace.shared.openApplication(at: url, configuration: configuration)) != nil else {
            return false
        }
        for _ in 0..<CicadaTiming.automationLaunchTries {
            if running() != nil { return true }
            try? await Task.sleep(for: .seconds(CicadaTiming.automationLaunchStep))
        }
        return running() != nil
    }
}
