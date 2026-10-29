import Foundation

/// G179 (2026-10-28) — the backend's view of a WhatsApp chat: the person's tick, and whether they asked
/// for its history. Lenient — a backend a field ahead or behind never fails the list.
struct ChatTickState: Decodable, Equatable, Sendable {
    var id: String
    var ticked = false
    var group = false
    var history = false

    enum CodingKeys: String, CodingKey { case id, ticked, group, history }

    init(id: String, ticked: Bool = false, group: Bool = false, history: Bool = false) {
        self.id = id
        self.ticked = ticked
        self.group = group
        self.history = history
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        ticked = (try? c.decodeIfPresent(Bool.self, forKey: .ticked)) ?? false
        group = (try? c.decodeIfPresent(Bool.self, forKey: .group)) ?? false
        history = (try? c.decodeIfPresent(Bool.self, forKey: .history)) ?? false
    }
}

struct ChatTickAnswer: Decodable, Equatable, Sendable {
    var conversations: [ChatTickState] = []
    var tickedIds: Set<String> { Set(conversations.filter(\.ticked).map(\.id)) }
}

struct ChatSyncAnswer: Decodable, Equatable, Sendable {
    var created = 0
    var updated = 0
    var kept = 0

    enum CodingKeys: String, CodingKey { case created, updated, kept }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        created = (try? c.decodeIfPresent(Int.self, forKey: .created)) ?? 0
        updated = (try? c.decodeIfPresent(Int.self, forKey: .updated)) ?? 0
        kept = (try? c.decodeIfPresent(Int.self, forKey: .kept)) ?? 0
    }
}

/// The routes behind a chat source's row (`source`: `whatsapp`).
protocol ChatSourcesAPI: Sendable {
    func fetchChatTicks(source: String) async throws -> ChatTickAnswer
    func describeChats(source: String, ids: [(id: String, group: Bool)]) async throws -> ChatTickAnswer
    func updateChat(source: String, id: String, name: String?, group: Bool?, ticked: Bool?, history: Bool?) async throws
        -> ChatTickAnswer
    func postWhatsApp(_ json: Data) async throws -> ChatSyncAnswer
}

extension APIClient: ChatSourcesAPI {}
