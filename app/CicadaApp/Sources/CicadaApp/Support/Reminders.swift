import AppKit
import UserNotifications

/// Main-actor, like the store that calls it: the fake's counters and the live
/// scheduler's notification centre are then touched from one isolation domain,
/// never across an `await` from the main actor into a nonisolated method.
@MainActor
protocol ReminderScheduling {
    func requestPermission() async -> Bool
    func schedule(_ wait: ExportWait) async
    func cancel(_ wait: ExportWait)
}

/// `UNUserNotificationCenter.current()` raises in a process with no app bundle
/// (`swift test`, a bare `swift run`), so it is touched only inside a real `.app`.
enum ReminderAvailability {
    static func isAvailable(bundleIdentifier: String?, bundlePath: String) -> Bool {
        bundleIdentifier != nil && bundlePath.hasSuffix(".app")
    }
    static var current: Bool {
        isAvailable(bundleIdentifier: Bundle.main.bundleIdentifier, bundlePath: Bundle.main.bundlePath)
    }
}

/// One-shot local notifications; nothing fetched, nothing sent (design §5.5).
struct LiveReminderScheduler: ReminderScheduling {
    nonisolated static let userInfoVendor = "vendor"

    /// Stateless, so constructible anywhere — `ExportWaitStore`'s default
    /// argument is evaluated outside the main actor.
    nonisolated init() {}

    func requestPermission() async -> Bool {
        guard ReminderAvailability.current else { return false }
        return (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])) ?? false
    }

    func schedule(_ wait: ExportWait) async {
        guard ReminderAvailability.current else { return }
        let content = UNMutableNotificationContent()
        content.title = Copy.reminderTitle(ExportWaits.vendorTitle(wait.vendor))
        content.body = Copy.reminderBody
        content.userInfo = [Self.userInfoVendor: wait.vendor]
        let parts = Calendar.autoupdatingCurrent.dateComponents([.year, .month, .day, .hour, .minute], from: wait.remindAt)
        let request = UNNotificationRequest(identifier: Self.identifier(wait), content: content,
                                            trigger: UNCalendarNotificationTrigger(dateMatching: parts, repeats: false))
        try? await UNUserNotificationCenter.current().add(request)
    }

    func cancel(_ wait: ExportWait) {
        guard ReminderAvailability.current else { return }
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [Self.identifier(wait)])
    }

    static func identifier(_ wait: ExportWait) -> String { "cicada.exportWait.\(wait.id)" }
}

/// A tapped reminder, held until the router attaches (the `DockOpenQueue` shape).
@MainActor
final class ReminderTapQueue {
    private var pending: [ChatVendor] = []
    private var handler: ((ChatVendor) -> Void)?

    func receive(_ vendor: ChatVendor) { if let handler { handler(vendor) } else { pending.append(vendor) } }

    func attach(_ handler: @escaping (ChatVendor) -> Void) {
        self.handler = handler
        let queued = pending
        pending = []
        queued.forEach(handler)
    }
}
