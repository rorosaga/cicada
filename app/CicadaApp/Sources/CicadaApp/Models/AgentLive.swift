import Foundation

/// Round 4 C8 — `GET /agents/live`, decoded leniently (a backend a field ahead or behind never blanks the page).
struct AgentLiveRow: Decodable, Equatable, Identifiable {
    let id: String
    var connected = false
    var lastSeenAt: String? = nil
    var via: String? = nil

    init(id: String, connected: Bool = false, lastSeenAt: String? = nil, via: String? = nil) {
        self.id = id; self.connected = connected; self.lastSeenAt = lastSeenAt; self.via = via
    }

    enum CodingKeys: String, CodingKey { case id, connected, lastSeenAt, via }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        connected = c.lenient(.connected, false)
        lastSeenAt = c.lenient(.lastSeenAt)
        via = c.lenient(.via)
    }
}

struct AgentLiveResponse: Decodable, Equatable {
    var agents: [AgentLiveRow] = []

    init(agents: [AgentLiveRow] = []) { self.agents = agents }

    enum CodingKeys: String, CodingKey { case agents }

    init(from decoder: Decoder) throws {
        agents = try decoder.container(keyedBy: CodingKeys.self).lenient(.agents, [])
    }
}
