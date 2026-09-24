import Foundation
import Observation
import ServiceManagement

/// `SMAppService.Status`, as the four answers Cicada acts on (any future case reads as not registered).
enum LoginItemStatus: Equatable, Sendable { case notRegistered, enabled, requiresApproval, notFound }

/// Round-4 D3 (C7) — the one seam over `SMAppService.mainApp`, so a test never touches the real login items.
protocol LoginItemControlling: Sendable {
    func status() -> LoginItemStatus
    func register() throws
    func unregister() throws
    func openSystemSettingsLoginItems()
}

struct MainAppLoginItem: LoginItemControlling {
    func status() -> LoginItemStatus {
        switch SMAppService.mainApp.status {
        case .enabled: .enabled
        case .requiresApproval: .requiresApproval
        case .notFound: .notFound
        default: .notRegistered
        }
    }
    func register() throws { try SMAppService.mainApp.register() }
    func unregister() throws { try SMAppService.mainApp.unregister() }
    func openSystemSettingsLoginItems() { SMAppService.openSystemSettingsLoginItems() }
}

/// What the Settings row says (R-FA7). `notKept` is D3's honesty: the person asked, macOS did not keep it — an
/// ad-hoc-signed build may never reach `.enabled`, and the row must not pretend it did.
enum LoginItemState: Equatable {
    case off, on, needsApproval
    case notKept(String)

    static func derive(status: LoginItemStatus, requested: Bool, error: String? = nil) -> LoginItemState {
        if requested, let error { return .notKept(error) }
        switch status {
        case .enabled: return .on
        case .requiresApproval: return .needsApproval
        case .notRegistered, .notFound: return requested ? .notKept(Copy.loginItemNotKept) : .off
        }
    }

    var detail: String {
        switch self {
        case .off: Copy.loginItemOff
        case .on: Copy.loginItemOn
        case .needsApproval: Copy.loginItemNeedsApproval
        case .notKept(let why): why
        }
    }

    var offersSettings: Bool {
        switch self {
        case .needsApproval, .notKept: true
        case .off, .on: false
        }
    }
}

@MainActor
@Observable
final class LoginItemService {
    static let requestedKey = "cicada.loginItem.requested"

    private(set) var state: LoginItemState = .off
    private(set) var requested: Bool

    @ObservationIgnored private let control: LoginItemControlling
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private var lastError: String?

    init(control: LoginItemControlling = MainAppLoginItem(), defaults: UserDefaults = .standard) {
        self.control = control
        self.defaults = defaults
        requested = defaults.bool(forKey: Self.requestedKey)
        let status = control.status()
        if status == .enabled, !requested {
            requested = true
            defaults.set(true, forKey: Self.requestedKey)
        }
        state = .derive(status: status, requested: requested)
    }

    /// Re-read macOS's answer — on appear and whenever the app becomes active (the person may have just used System
    /// Settings). A switch-off made there while Cicada ran clears the intent rather than reading as "not kept".
    func refresh() {
        let status = control.status()
        if state == .on, status == .notRegistered { remember(false) }
        // Allowed from System Settings while the intent said off: the person's answer is on (R-FA7).
        if status == .enabled, !requested { remember(true) }
        state = .derive(status: status, requested: requested, error: lastError)
    }

    func setEnabled(_ on: Bool) {
        remember(on)
        lastError = nil
        do {
            if on { try control.register() } else { try control.unregister() }
        } catch {
            // Unregistering something never registered throws; only a failed turn-on is news.
            if on { lastError = Copy.loginItemFailed(error.localizedDescription) }
        }
        refresh()
    }

    func openSystemSettings() { control.openSystemSettingsLoginItems() }

    private func remember(_ on: Bool) {
        requested = on
        defaults.set(on, forKey: Self.requestedKey)
    }
}
