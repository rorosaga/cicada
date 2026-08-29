import Foundation
import Observation

// G50: provider connections — probe/connect/disconnect through the vendor CLIs.
@Observable
@MainActor
final class ConnectionsViewModel {
    var connections: [ConnectionStatus] = []
    var isLoading = false
    var errorMessage: String?
    /// Active device-code login (ChatGPT/Codex) being polled.
    var pendingLogin: LoginSession?
    /// Connection id whose Terminal hand-off is in progress (Claude).
    var awaitingTerminal: String?

    private var pollTask: Task<Void, Never>?
    /// The device-code or terminal-hand-off poll spawned by `beginLogin`. Tracked
    /// separately from `pollTask` (the 30 s background refresh) so leaving the
    /// page via `stopPolling()` cancels an in-flight login poll too, instead of
    /// letting it keep running for up to 5 minutes.
    private var loginTask: Task<Void, Never>?

    func load(fresh: Bool = false) async {
        isLoading = connections.isEmpty
        defer { isLoading = false }
        errorMessage = nil
        do {
            connections = try await APIClient.shared.fetchConnections(fresh: fresh)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Refresh every 30 s while the page is visible (matches the backend TTL).
    func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                await self?.load()
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel(); pollTask = nil
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
            if let idx = connections.firstIndex(where: { $0.id == id }) {
                connections[idx] = latest
            }
            if latest.connected {
                await load()
                awaitingTerminal = nil
                return
            }
        }
        awaitingTerminal = nil
    }

    func logout(_ id: String) async {
        do { _ = try await APIClient.shared.logout(id); await load(fresh: true) }
        catch { errorMessage = error.localizedDescription }
    }

    func saveKey(_ id: String, key: String) async {
        do { _ = try await APIClient.shared.setKey(id, key: key); await load(fresh: true) }
        catch { errorMessage = error.localizedDescription }
    }

    func removeKey(_ id: String) async {
        do { _ = try await APIClient.shared.removeKey(id); await load(fresh: true) }
        catch { errorMessage = error.localizedDescription }
    }

    func setTier(_ id: String, tier: String?) async {
        do { _ = try await APIClient.shared.setTier(id, tier: tier); await load(fresh: true) }
        catch { errorMessage = error.localizedDescription }
    }
}
