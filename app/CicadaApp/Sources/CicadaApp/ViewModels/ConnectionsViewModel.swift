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

    func stopPolling() { pollTask?.cancel(); pollTask = nil }

    func beginLogin(_ id: String) async -> LoginSession? {
        do {
            let session = try await APIClient.shared.beginLogin(id)
            switch session.mode {
            case "device-code":
                pendingLogin = session
                Task { await pollDeviceLogin(session) }
            case "terminal":
                awaitingTerminal = id
                Task { await pollUntilConnected(id) }
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
            try? await Task.sleep(for: .seconds(2))
            guard let latest = try? await APIClient.shared.loginState(session.connectionId, sessionId: session.sessionId) else { continue }
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
            try? await Task.sleep(for: .seconds(3))
            await load(fresh: true)
            if connections.first(where: { $0.id == id })?.connected == true {
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
