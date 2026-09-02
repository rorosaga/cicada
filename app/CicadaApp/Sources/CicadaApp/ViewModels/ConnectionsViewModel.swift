import Foundation
import Observation

// G50: provider connections — probe/connect/disconnect through the vendor CLIs.
/// Thin projection over `Store.connections` (§5.5), moved from a per-view
/// `@State` to an app-level, environment-injected VM in Task 7 so switching
/// away from and back to this tab renders instantly from the snapshot.
///
/// Mutations (`beginLogin`/`logout`/`saveKey`/…) need the *freshest* possible
/// probe (bypassing the backend's own TTL cache via `fresh: true`), which
/// `SyncAPI.fetchConnections(etag:)` — the conditional GET the Store polls —
/// doesn't support. Rather than keep a second, parallel copy of the
/// connections array, those paths write the fresh result straight into
/// `store.connections` (and its disk cache) via `setConnections`, so the
/// Store stays the single source of truth and every reader (this VM
/// included) sees the same value.
@Observable
@MainActor
final class ConnectionsViewModel {
    private let store: Store

    var errorMessage: String?
    /// Active device-code login (ChatGPT/Codex) being polled.
    var pendingLogin: LoginSession?
    /// Connection id whose Terminal hand-off is in progress (Claude).
    var awaitingTerminal: String?

    /// The device-code or terminal-hand-off poll spawned by `beginLogin`.
    /// `stopPolling()` cancels an in-flight login poll on page exit, instead
    /// of letting it keep running for up to 5 minutes.
    private var loginTask: Task<Void, Never>?

    init(store: Store) {
        self.store = store
    }

    var connections: [ConnectionStatus] { store.connections.value ?? [] }

    var isLoading: Bool { store.connections.isEmpty && store.connections.isRefreshing }

    /// A subscription whose CLI is installed but is no longer signed in —
    /// the one connection state that quietly degrades Sleep, Ask and
    /// clarification wording, so it earns the gear's dot. A key-based
    /// connection with no key is "not set up yet", not "expired", and a CLI
    /// that isn't installed can't have expired.
    var needsAttention: Bool {
        connections.contains { $0.billing == "subscription" && $0.available && !$0.connected }
    }

    /// Writes a freshly-probed connections array straight into the Store
    /// (value + cache), so this VM never holds a copy that can drift from
    /// what every other reader of `store.connections` sees.
    private func setConnections(_ result: [ConnectionStatus]) {
        store.connections.value = result
        store.connections.loadedAt = Date()
        let bank = store.bank
        let cache = store.cache
        Task { await cache.save(result, etag: nil, domain: .connections, bank: bank) }
    }

    func load(fresh: Bool = false) async {
        errorMessage = nil
        guard fresh else {
            await store.refresh([.connections])
            if store.connections.value == nil {
                errorMessage = store.toast
            }
            return
        }
        do {
            setConnections(try await APIClient.shared.fetchConnections(fresh: true))
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func stopPolling() {
        loginTask?.cancel(); loginTask = nil
    }

    func beginLogin(_ id: String) async -> LoginSession? {
        do {
            let session = try await APIClient.shared.beginLogin(id)
            loginTask?.cancel()
            switch session.mode {
            case "device-code":
                pendingLogin = session
                loginTask = Task { [weak self] in await self?.pollDeviceLogin(session) }
            case "terminal":
                awaitingTerminal = id
                loginTask = Task { [weak self] in await self?.pollUntilConnected(id) }
            default: break
            }
            return session
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    private func pollDeviceLogin(_ session: LoginSession) async {
        for _ in 0..<150 { // 5 minutes at 2 s
            if Task.isCancelled { return }
            try? await Task.sleep(for: .seconds(2))
            if Task.isCancelled { return }
            guard let latest = try? await APIClient.shared.loginState(session.connectionId, sessionId: session.sessionId) else { continue }
            if Task.isCancelled { return }
            pendingLogin = latest
            if latest.state != "pending" {
                await load(fresh: true)
                if latest.state == "done" { pendingLogin = nil }
                return
            }
        }
    }

    private func pollUntilConnected(_ id: String) async {
        for _ in 0..<100 { // ~5 minutes at 3 s
            if Task.isCancelled { return }
            try? await Task.sleep(for: .seconds(3))
            if Task.isCancelled { return }
            guard let latest = try? await APIClient.shared.fetchConnection(id, fresh: true) else { continue }
            if Task.isCancelled { return }
            if var current = store.connections.value, let idx = current.firstIndex(where: { $0.id == id }) {
                current[idx] = latest
                setConnections(current)
            }
            if latest.connected {
                await load()
                awaitingTerminal = nil
                return
            }
        }
        awaitingTerminal = nil
    }

    // MARK: Mutations (§5.4)
    //
    // Each flips the row locally through `Store.perform` (instant card
    // update), then — on success only — re-probes with `fresh: true` so the
    // server's authoritative row (real account, real price note) replaces the
    // optimistic one. A failure rolls the row back and the Store's toast
    // explains why; `errorMessage` mirrors it for the inline banner.

    func logout(_ id: String) async {
        await mutate(LogoutConnection(id: id))
    }

    func saveKey(_ id: String, key: String) async {
        await mutate(SetConnectionKey(id: id, key: key))
    }

    func removeKey(_ id: String) async {
        await mutate(RemoveConnectionKey(id: id))
    }

    func setTier(_ id: String, tier: String?) async {
        await mutate(SetConnectionTier(id: id, tier: tier))
    }

    func setUseForSleep(_ id: String, on: Bool) async {
        await mutate(SetUseForSleep(id: id, on: on))
    }

    private func mutate(_ mutation: any Mutation) async {
        errorMessage = nil
        if await store.perform(mutation) {
            await load(fresh: true)
        } else {
            errorMessage = store.toast
        }
    }
}
