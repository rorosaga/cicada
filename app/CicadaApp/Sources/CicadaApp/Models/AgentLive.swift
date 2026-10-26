import Foundation

/// Round 4 C8 — `GET /agents/live`, decoded leniently (a backend a field ahead or behind never blanks the page).
struct AgentLiveRow: Decodable, Equatable, Identifiable {
    let id: String
    var connected = false
    var lastSeenAt: String? = nil
    var via: String? = nil
    /// Onboarding v3 — the latest tool call (the agent asked Cicada something), never a connect or a harness's own
    /// wiring check; nil on an older backend, which then never confirms a first call.
    var lastCalledAt: String? = nil

    init(id: String, connected: Bool = false, lastSeenAt: String? = nil, via: String? = nil,
         lastCalledAt: String? = nil) {
        self.id = id; self.connected = connected; self.lastSeenAt = lastSeenAt; self.via = via
        self.lastCalledAt = lastCalledAt
    }

    enum CodingKeys: String, CodingKey { case id, connected, lastSeenAt, via, lastCalledAt }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        connected = c.lenient(.connected, false)
        lastSeenAt = c.lenient(.lastSeenAt)
        via = c.lenient(.via)
        lastCalledAt = c.lenient(.lastCalledAt)
    }

    /// Connected on this Mac — its config names Cicada or it called through stdio (`via` `config` or `mcp`), never
    /// only through the remote connector. Only such an agent can read a walled site's saved list in the person's
    /// signed-in browser (G166/G206: those reading tools are stdio only).
    var connectedLocally: Bool { connected && via != "remote" }
}

struct AgentLiveResponse: Decodable, Equatable {
    var agents: [AgentLiveRow] = []

    init(agents: [AgentLiveRow] = []) { self.agents = agents }

    /// Whether any agent on this Mac is connected (`AgentLiveRow.connectedLocally`) — what a list read in the
    /// person's browser needs before the Sources page may call it Connected.
    static func anyConnectedLocally(_ rows: some Sequence<AgentLiveRow>) -> Bool {
        rows.contains { $0.connectedLocally }
    }

    enum CodingKeys: String, CodingKey { case agents }

    init(from decoder: Decoder) throws {
        agents = try decoder.container(keyedBy: CodingKeys.self).lenient(.agents, [])
    }
}
