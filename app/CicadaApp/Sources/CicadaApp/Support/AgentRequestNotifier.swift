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
    /// Set only by the card's "Notify me" click: the person's own opt-in, in words, per viewer. Without it nothing is
    /// posted, even when macOS already allows Cicada's notifications (say, for an export reminder) (review of #428).
    static let optInKey = "cicada.agentRequests.notify"

    enum Permission: Equatable { case unknown, notAsked, allowed, refused }

    private(set) var permission: Permission = .unknown
    private(set) var optedIn: Bool
    /// Posted ids with when they were posted, so the remembered set keeps the newest (`remember`).
    @ObservationIgnored private var posted: [String: Double]
    @ObservationIgnored private var waiting: [InboxItem] = []
    @ObservationIgnored private var categoryInstalled = false

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        optedIn = defaults.bool(forKey: Self.optInKey)
        posted = (defaults.dictionary(forKey: Self.postedKey) as? [String: Double]) ?? [:]
    }

    @ObservationIgnored private let defaults: UserDefaults

    /// The Inbox card's in-words ask shows while the person has not opted in — whatever macOS already allows — and
    /// is gone once they did, or once macOS refused (their choice in System Settings stands).
    var asksInWords: Bool { !optedIn && permission != .refused }

    /// Called whenever the inbox's agent requests change: each new one is posted once (or held until the person allows
    /// notifications in the card).
    func observe(_ requests: [InboxItem]) {
        let fresh = Self.unposted(requests, posted: Set(posted.keys))
        guard !fresh.isEmpty, ReminderAvailability.current else { return }
        Task {
            await refreshPermission()
            switch Self.route(optedIn: optedIn, permission: permission) {
            case .post: for item in fresh { await post(item) }
            case .hold: waiting = fresh
            case .drop:
                // Never asked again: their choice in System Settings stands. The Inbox card still shows the request.
                remember(fresh.map(\.id))
            }
        }
    }

    enum Route: Equatable { case post, hold, drop }

    /// Pure: post only after the person's own opt-in AND macOS's allowance; hold until the opt-in; drop once macOS
    /// refused.
    nonisolated static func route(optedIn: Bool, permission: Permission) -> Route {
        if permission == .refused { return .drop }
        guard optedIn else { return .hold }
        return permission == .allowed ? .post : .hold
    }

    static func unposted(_ requests: [InboxItem], posted: Set<String>) -> [InboxItem] {
        requests.filter { $0.kind == .agentRequest && !posted.contains($0.id) && $0.request?.notification != nil }
    }

    /// The person's click on the card's "Notify me": records their opt-in, then asks macOS only if it was never
    /// asked, then posts what waited.
    func requestPermission() async {
        optedIn = true
        defaults.set(true, forKey: Self.optInKey)
        guard ReminderAvailability.current else { return }
        await refreshPermission()
        if permission == .notAsked {
            let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])) ?? false
            permission = granted ? .allowed : .refused
        }
        let pending = waiting
        waiting = []
        if permission == .allowed { for item in pending { await post(item) } } else { remember(pending.map(\.id)) }
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

    private func remember(_ ids: [String], now: Date = .now) {
        for id in ids { posted[id] = now.timeIntervalSince1970 }
        posted = Self.newest(posted, keep: 200)
        defaults.set(posted, forKey: Self.postedKey)
    }

    /// The newest `keep` ids by when they were posted (ties by id, so the cut is stable).
    nonisolated static func newest(_ posted: [String: Double], keep: Int) -> [String: Double] {
        guard posted.count > keep else { return posted }
        let kept = posted.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }.prefix(keep)
        return Dictionary(uniqueKeysWithValues: kept.map { ($0.key, $0.value) })
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
