import AppKit
import Observation
import UserNotifications

/// G205 — an agent's request reaches the person as a Mac notification, once per request, in the backend's own words
/// (`request.notification`: title, body, the page to open). Permission is asked only when the first request arrives,
/// and in words first: the Inbox card says what a notification would be for and the person's click asks macOS
/// (never a system prompt out of nowhere). The ids already posted are remembered per viewer (`UserDefaults`), so a
/// relaunch never repeats one. Nothing is fetched or sent: the notification is local.
@MainActor
@Observable
final class AgentRequestNotifier {
    static let shared = AgentRequestNotifier()

    static let category = "cicada.agentRequest"
    static let doneAction = "cicada.agentRequest.done"
    static let notNowAction = "cicada.agentRequest.dismiss"
    nonisolated static let userInfoId = "agentRequest"
    nonisolated static let userInfoURL = "openUrl"
    private static let postedKey = "cicada.agentRequests.notified"

    enum Permission: Equatable { case unknown, notAsked, allowed, refused }

    private(set) var permission: Permission = .unknown
    @ObservationIgnored private var posted: Set<String>
    @ObservationIgnored private var waiting: [InboxItem] = []
    @ObservationIgnored private var categoryInstalled = false

    init() {
        posted = Set(UserDefaults.standard.stringArray(forKey: Self.postedKey) ?? [])
    }

    /// The Inbox card's in-words ask shows only while a request waits and macOS has not been asked.
    var asksInWords: Bool { permission == .notAsked }

    /// Called whenever the inbox's agent requests change: each new one is posted once (or held until the person allows
    /// notifications in the card).
    func observe(_ requests: [InboxItem]) {
        let fresh = requests.filter { !posted.contains($0.id) && $0.request?.notification != nil }
        guard !fresh.isEmpty, ReminderAvailability.current else { return }
        Task {
            await refreshPermission()
            switch permission {
            case .allowed: for item in fresh { await post(item) }
            case .notAsked: waiting = fresh
            case .refused, .unknown:
                // Never asked again: their choice in System Settings stands. The Inbox card still shows the request.
                remember(fresh.map(\.id))
            }
        }
    }

    /// The person's click on the card's "Notify me" — the one moment macOS is asked.
    func requestPermission() async {
        guard ReminderAvailability.current else { return }
        let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])) ?? false
        permission = granted ? .allowed : .refused
        let pending = waiting
        waiting = []
        if granted { for item in pending { await post(item) } } else { remember(pending.map(\.id)) }
    }

    private func refreshPermission() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        permission = switch settings.authorizationStatus {
        case .notDetermined: .notAsked
        case .denied: .refused
        default: .allowed
        }
    }

    private func installCategory() {
        guard !categoryInstalled else { return }
        categoryInstalled = true
        let done = UNNotificationAction(identifier: Self.doneAction, title: Copy.AgentRequests.signedIn)
        let notNow = UNNotificationAction(identifier: Self.notNowAction, title: Copy.AgentRequests.notNow)
        let category = UNNotificationCategory(identifier: Self.category, actions: [done, notNow], intentIdentifiers: [])
        UNUserNotificationCenter.current().setNotificationCategories([category])
    }

    private func post(_ item: InboxItem) async {
        guard let words = item.request?.notification else { return }
        installCategory()
        let content = UNMutableNotificationContent()
        content.title = words.title
        content.body = words.body
        content.categoryIdentifier = Self.category
        var info: [String: String] = [Self.userInfoId: item.id]
        if let url = words.openUrl { info[Self.userInfoURL] = url }
        content.userInfo = info
        let request = UNNotificationRequest(identifier: "cicada.agentRequest.\(item.id)", content: content, trigger: nil)
        try? await UNUserNotificationCenter.current().add(request)
        remember([item.id])
    }

    private func remember(_ ids: [String]) {
        posted.formUnion(ids)
        UserDefaults.standard.set(Array(posted.suffix(200)), forKey: Self.postedKey)
    }

    /// The notification's buttons and its body tap (`CicadaAppDelegate`): "I signed in" resolves `done` (lifts the
    /// site's pause), "Not now" dismisses, a tap opens the page in the person's browser. Only an http(s) page opens.
    static func handle(id: String, action: String, openUrl: String?) async {
        switch action {
        case doneAction: try? await APIClient.shared.resolveInboxItem(id: id, action: "resolve", optionKey: "done")
        case notNowAction: try? await APIClient.shared.resolveInboxItem(id: id, action: "resolve", optionKey: "dismiss")
        default:
            if let openUrl, let url = URL(string: openUrl), ["http", "https"].contains(url.scheme?.lowercased() ?? "") {
                NSWorkspace.shared.open(url)
            }
        }
    }
}
