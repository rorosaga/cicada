import AppKit
import UserNotifications

/// R-IA25 — URLs from the Dock ("Open With", a drop on the icon) arrive through
/// the app delegate, and on a cold launch they arrive BEFORE `ContentView`'s
/// `.onAppear` has attached the router. They wait here, then flow straight through.
@MainActor
final class DockOpenQueue {
    private var pending: [URL] = []
    private var handler: (([URL]) -> Void)?

    func receive(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        if let handler { handler(urls) } else { pending += urls }
    }

    func attach(_ handler: @escaping ([URL]) -> Void) {
        self.handler = handler
        guard !pending.isEmpty else { return }
        let urls = pending
        pending = []
        handler(urls)
    }
}

/// The one AppKit hook SwiftUI's `App` lacks for a Dock open (F10), and — Track I
/// part b (R-IB22) — the notification centre's delegate for export reminders.
@MainActor
final class CicadaAppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let opens = DockOpenQueue()
    /// A tapped reminder waits here until `.onAppear` attaches the router — a tap
    /// can relaunch the app, and then it arrives before the window exists.
    let reminderTaps = ReminderTapQueue()

    func application(_ application: NSApplication, open urls: [URL]) {
        opens.receive(urls)
    }

    /// DR-42 (R-DI3) — set by `CicadaApp` once the Store exists.
    var heldAnswer: () -> Bool = { false }
    var sendHeldAnswer: (@MainActor () async -> Void)?

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard QuitFlush.reply(hasHeld: heldAnswer()) == .terminateLater, let send = sendHeldAnswer else {
            return .terminateNow
        }
        Task { @MainActor in
            _ = await QuitFlush.run(send, limit: .seconds(CicadaTiming.quitFlushLimit))
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    /// Only inside a real `.app`: `UNUserNotificationCenter.current()` raises in a
    /// process with no bundle proxy (`swift test`, a bare `swift run`).
    func applicationDidFinishLaunching(_ notification: Notification) {
        // R-OB18 — the 'oapp' event is current only now; first, because the reminder guard below returns early in a
        // process with no bundle (`swift test`, a bare `swift run`).
        LaunchState.shared.record(LaunchKind.resolve(event: NSAppleEventManager.shared().currentAppleEvent,
                                                     arguments: ProcessInfo.processInfo.arguments))
        guard ReminderAvailability.current else { return }
        UNUserNotificationCenter.current().delegate = self
    }

    /// A tap opens the one intake, idle, for that vendor — never a cycle (G125 R10).
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let vendor = response.notification.request.content.userInfo[LiveReminderScheduler.userInfoVendor] as? String
        Task { @MainActor in
            if let vendor, let v = ChatVendor(rawValue: vendor) { self.reminderTaps.receive(v) }
        }
        completionHandler()
    }

    /// Shown even while Cicada is frontmost — the person asked for this nudge.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}
