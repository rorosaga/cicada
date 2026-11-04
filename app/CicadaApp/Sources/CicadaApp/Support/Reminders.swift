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
    /// G197 layer c — the weekly nudge to ask for a fresh export, repeating until stopped.
    func scheduleWeekly(_ habit: ExportHabit) async
    func cancelWeekly(_ habit: ExportHabit)
    /// The awaited export landed in Downloads and its preview is open — said only while Cicada is not in front.
    func announceArrival(_ vendor: ChatVendor) async
}

/// What a tapped Cicada notification about an export asks for.
enum ReminderTapKind: String {
    /// The export should be in the person's email (R-IB22): open the intake idle.
    case due
    /// Time to ask for a fresh one (G197 layer c): open the export page and a wait.
    case weekly
    /// It arrived and the preview is open: bring the window forward.
    case arrived
}

struct ReminderTap: Equatable {
    let vendor: ChatVendor
    let kind: ReminderTapKind
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
    nonisolated static let userInfoKind = "kind"

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

    func scheduleWeekly(_ habit: ExportHabit) async {
        guard ReminderAvailability.current else { return }
        let content = UNMutableNotificationContent()
        content.title = Copy.reminderWeeklyTitle(ExportWaits.vendorTitle(habit.vendor))
        content.body = Copy.reminderWeeklyBody
        content.userInfo = [Self.userInfoVendor: habit.vendor, Self.userInfoKind: ReminderTapKind.weekly.rawValue]
        let request = UNNotificationRequest(identifier: Self.identifier(habit), content: content,
                                            trigger: UNCalendarNotificationTrigger(dateMatching: habit.dateComponents,
                                                                                   repeats: true))
        try? await UNUserNotificationCenter.current().add(request)
    }

    func cancelWeekly(_ habit: ExportHabit) {
        guard ReminderAvailability.current else { return }
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [Self.identifier(habit)])
    }

    func announceArrival(_ vendor: ChatVendor) async {
        guard ReminderAvailability.current else { return }
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        guard settings.authorizationStatus == .authorized else { return }
        let content = UNMutableNotificationContent()
        content.title = Copy.reminderArrivedTitle(vendor.title)
        content.body = Copy.reminderArrivedBody
        content.userInfo = [Self.userInfoVendor: vendor.rawValue, Self.userInfoKind: ReminderTapKind.arrived.rawValue]
        let request = UNNotificationRequest(identifier: "cicada.exportArrived.\(vendor.rawValue)", content: content,
                                            trigger: nil)
        try? await UNUserNotificationCenter.current().add(request)
    }

    static func identifier(_ wait: ExportWait) -> String { "cicada.exportWait.\(wait.id)" }
    static func identifier(_ habit: ExportHabit) -> String { "cicada.exportWeekly.\(habit.id)" }
}

/// A tapped reminder, held until the router attaches (the `DockOpenQueue` shape).
@MainActor
final class ReminderTapQueue {
    private var pending: [ReminderTap] = []
    private var handler: ((ReminderTap) -> Void)?

    func receive(_ tap: ReminderTap) { if let handler { handler(tap) } else { pending.append(tap) } }

    func attach(_ handler: @escaping (ReminderTap) -> Void) {
        self.handler = handler
        let queued = pending
        pending = []
        queued.forEach(handler)
    }
}
