import Foundation
import Observation

/// G132 phase 1 — one memory on every device: what Settings → Devices shows about sharing this computer's memory
/// (`/sync/publish`, the home) and keeping a copy of another computer's (`/sync/replica`). Not a Store domain: read when
/// the page opens and every 30 s while it is open, kept in memory. The backend owns both choices; the app only asks.

struct PublishState: Decodable, Equatable, Sendable {
    let publish: Bool
    /// `env`, `settings` or `default` — an environment setting fixes the switch.
    let source: String
    let demo: Bool
}

struct ReplicaState: Decodable, Equatable, Sendable {
    struct CopyState: Decodable, Equatable, Sendable {
        let status: String
        let text: String
        let seq: Int?
        let homeSeq: Int?
        let behind: Int?
        /// When the home last answered (`replica.state()`), ISO; the route line's "reached …".
        var lastContact: String?
    }

    struct Outbox: Decodable, Equatable, Sendable {
        let waiting: Int
        let held: Int
        let rejected: Int
        let captures: Int
        /// G132 ruling 51f: the next change made here would not be kept (an older backend sends none).
        var full: Bool?
    }

    /// `local`, `client` or `replica`.
    let mode: String
    /// Both a server and a home are set: the sentence that says this computer uses the server.
    let conflict: String?
    let replica: CopyState?
    let outbox: Outbox?
    let home: String?

    var isReplica: Bool { mode == "replica" }
    /// The copy stopped following and only the person's "Copy again" brings it back.
    var needsCopyAgain: Bool { ["diverged", "home_rewritten"].contains(replica?.status ?? "") }
    /// Changes and captures made here, still on their way to the home.
    var onItsWay: Int { (outbox?.waiting ?? 0) + (outbox?.held ?? 0) + (outbox?.captures ?? 0) }
}

struct ReplicaSetupAnswer: Decodable, Equatable, Sendable {
    let mode: String
    let home: String?
    let restart: Bool
}

@MainActor
@Observable
final class MemoryCopyModel {
    var publish: PublishState?
    var replica: ReplicaState?
    var address = ""
    var code = ""
    var busy = false
    var error: String?
    /// The backend restarts to change mode; the page says so until it answers again.
    var restarting = false
    /// G132 ruling 51f: this copy's routes to its home (`/sync/routes`), read only while it is a copy.
    var routes: SyncRoutes?

    /// Shown only on a computer that keeps its own memory or a copy — never while this app uses a server.
    var shown: Bool { replica.map { $0.mode != "client" } ?? false }
    /// Sharing is offered only on this computer's own memory, and never for a demo (review of #567: `demo` is the
    /// backend's real answer, and `isDemo` — the Store's own view of the open bank — is asked too).
    func canShare(isDemo: Bool) -> Bool { replica?.mode == "local" && publish?.demo == false && !isDemo }
    func isDemoMemory(isDemo: Bool) -> Bool { isDemo || publish?.demo == true }

    /// Does a running Sleep hold the copy switch (DR-41)? Only on a Mac that is not a copy (review of #567): a copy never
    /// runs Sleep — the run the Store shows there is the home's — so "Stop keeping a copy" stays available, and the
    /// copy's following, behind and on-its-way lines stay shown.
    nonisolated static func sleepBlocks(sleeping: Bool, isCopy: Bool) -> Bool { sleeping && !isCopy }

    /// A failed read keeps what the card last showed (review of #567): the card never drops to nothing mid-page.
    func refresh() async {
        if let fresh = try? await APIClient.shared.fetchReplica() {
            replica = fresh
            restarting = false
        }
        if replica?.mode == "local", let fresh = try? await APIClient.shared.fetchPublish() {
            publish = fresh
        }
        routes = replica?.isReplica == true ? (try? await APIClient.shared.fetchRoutes()) ?? routes : nil
    }

    /// The route a copy is using to its home, in words: "Same network · reached 2 minutes ago", "Queued · reached
    /// yesterday" while no route answers. Never an address or a port. Nil before the backend says anything.
    nonisolated static func routeLine(_ routes: SyncRoutes?, lastContact: String?, now: Date = Date()) -> String? {
        guard let routes else { return nil }
        let word = routes.toHome.queued || routes.toHome.active == nil
            ? Copy.LocalNetwork.queued : (LanRules.routeWord(routes.toHome.active) ?? Copy.LocalNetwork.queued)
        let reached = lastContact.flatMap(ISODate.parse).map { Copy.LocalNetwork.reached($0, now: now) }
        return [word, reached].compactMap { $0 }.joined(separator: " · ")
    }

    func setShare(_ on: Bool) async {
        await run { self.publish = try await APIClient.shared.setPublish(on) }
        await LanDiscovery.shared.refresh()     // the door opens with the share: advertise it (once allowed)
    }

    func keepCopy() async {
        let home = address.trimmingCharacters(in: .whitespaces)
        let code = code.trimmingCharacters(in: .whitespaces)
        guard !home.isEmpty, !code.isEmpty else { return }
        await run {
            _ = try await APIClient.shared.keepCopy(home: home, code: code)
            self.code = ""
            try await self.restart()
        }
    }

    func stopCopy() async {
        await run {
            try await APIClient.shared.stopCopy()
            try await self.restart()
        }
    }

    func copyAgain() async {
        await run { try await APIClient.shared.copyAgain() }
        await refresh()
    }

    private func restart() async throws {
        restarting = true
        try await APIClient.shared.restartForCopy()
    }

    private func run(_ body: @escaping () async throws -> Void) async {
        busy = true
        error = nil
        defer { busy = false }
        do {
            try await body()
        } catch APIError.httpError(_, let raw) {
            error = Self.detail(raw) ?? Copy.MemoryCopy.failed
        } catch {
            self.error = Copy.MemoryCopy.failed
        }
    }

    /// The backend's own sentence (`detail`) from an error body, when it sent one.
    nonisolated static func detail(_ raw: String) -> String? {
        guard let data = raw.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = object["detail"] as? String, !detail.isEmpty else { return nil }
        return detail
    }
}
