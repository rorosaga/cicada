import Foundation
import Observation

/// ROR-126 — one provider's export the person said yes to having their own agent request. `asked`: the agent has not
/// reported back; `requested`: it asked the provider, the export is on its way; `manual`: the page could not be driven
/// reliably, so this one stays by hand (`reason` says why in one short line).
struct ExportRequest: Decodable, Equatable, Identifiable {
    let vendor: String
    let state: String
    var reason: String?
    var id: String { vendor }
}

private struct LossyRequest: Decodable {
    let value: ExportRequest?
    init(from decoder: Decoder) throws { value = try? ExportRequest(from: decoder) }
}

struct ExportRequestsResponse: Decodable, Equatable {
    var requests: [ExportRequest] = []
    init(requests: [ExportRequest] = []) { self.requests = requests }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        requests = ((try? c.decode([LossyRequest].self, forKey: .requests)) ?? []).compactMap(\.value)
    }
    enum CodingKeys: String, CodingKey { case requests }
}

/// The pure rules, so the views and the tests read one function.
enum ExportAgentRules {
    /// An agent is connected (recall on) and can drive the person's browser: they chose its own tools for reading, or a
    /// browser skill is installed for it. "Let my agent choose" with nothing installed offers nothing — Cicada does
    /// not promise a browser it cannot see.
    static func canRequest(wiring: AgentWiringResponse?, methods: AgentMethodsResponse?) -> Bool {
        guard let wiring, wiring.agents.contains(where: { $0.installed && $0.recall == "on" }),
              let reading = methods?.job("reading") else { return false }
        if reading.chosen == "own" { return true }
        return reading.options.contains { $0.kind == "skill" && $0.state.values.contains("installed") }
    }

    /// The providers Home and the menu say the worm is waiting on: a wait the person started by hand, or one their
    /// agent has asked the provider for. A request still `asked` is not a wait yet, and `manual` ends it.
    static func waitingVendors(waits: [ExportWait], requests: [ExportRequest]) -> [String] {
        waits.map(\.vendor).filter { vendor in
            guard let r = requests.first(where: { $0.vendor == vendor }) else { return true }
            return r.state == "requested"
        }
    }
}

/// What the app knows about asking an agent to request exports. Not a Store domain: a few small reads, refreshed when
/// the offer or Home shows (the same shape as Settings' "How your agent reads").
@MainActor
@Observable
final class ExportAgentModel {
    private(set) var requests: [ExportRequest] = []
    private(set) var canRequest = false
    private(set) var loaded = false

    @ObservationIgnored private let fetchRequests: @MainActor () async throws -> ExportRequestsResponse
    @ObservationIgnored private let fetchWiring: @MainActor () async throws -> AgentWiringResponse
    @ObservationIgnored private let fetchMethods: @MainActor () async throws -> AgentMethodsResponse
    @ObservationIgnored private let ask: @MainActor (String) async throws -> ExportRequest
    @ObservationIgnored private let stop: @MainActor (String) async throws -> Void

    init(fetchRequests: @escaping @MainActor () async throws -> ExportRequestsResponse = { try await APIClient.shared.fetchExportRequests() },
         fetchWiring: @escaping @MainActor () async throws -> AgentWiringResponse = { try await APIClient.shared.fetchAgentWiring() },
         fetchMethods: @escaping @MainActor () async throws -> AgentMethodsResponse = { try await APIClient.shared.fetchAgentMethods() },
         ask: @escaping @MainActor (String) async throws -> ExportRequest = { try await APIClient.shared.askExportRequest(vendor: $0) },
         stop: @escaping @MainActor (String) async throws -> Void = { try await APIClient.shared.stopExportRequest(vendor: $0) }) {
        self.fetchRequests = fetchRequests; self.fetchWiring = fetchWiring; self.fetchMethods = fetchMethods
        self.ask = ask; self.stop = stop
    }

    func request(for vendor: String) -> ExportRequest? { requests.first { $0.vendor == vendor } }

    /// Reads the requests and, only when none is open, whether an agent could take one (two more reads).
    func refresh(waits: ExportWaitStore, bank: String) async {
        if let r = try? await fetchRequests() { requests = r.requests }
        // The agent said it could not: the wait the person's yes started has nothing to wait for.
        for r in requests where r.state == "manual" { waits.clear(vendor: r.vendor, bank: bank) }
        let wiring = try? await fetchWiring()
        let methods = try? await fetchMethods()
        canRequest = ExportAgentRules.canRequest(wiring: wiring, methods: methods)
        loaded = true
    }

    /// The person's yes for one provider. It starts the wait and its reminder in the same moment — the one place the
    /// reminder's permission is asked, from this click (ruling 58 amendment) — and tells the agent through the queue.
    func grant(vendor: ChatVendor, waits: ExportWaitStore, bank: String) async {
        guard let row = try? await ask(vendor.rawValue) else { return }
        requests.removeAll { $0.vendor == row.vendor }
        requests.append(row)
        await waits.remind(vendor: vendor.rawValue, bank: bank, delay: .tomorrowMorning)
    }

    func stopWaiting(vendor: String, waits: ExportWaitStore, bank: String) async {
        try? await stop(vendor)
        requests.removeAll { $0.vendor == vendor }
        waits.clear(vendor: vendor, bank: bank)
    }

    /// The export arrived: its request is done.
    func arrived(vendor: String) async {
        try? await stop(vendor)
        requests.removeAll { $0.vendor == vendor }
    }
}
