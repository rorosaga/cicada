import Foundation

/// G179 (2026-10-28) — the backend's view of a WhatsApp or Telegram chat: the person's tick, and whether they asked
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

/// `GET /sources/telegram/status` — whether Telegram is connected (ruling 47a), and the consent sentence the connect
/// step shows word for word.
struct TelegramStatusAnswer: Decodable, Equatable, Sendable {
    var state = "off"
    var consent = ""
    /// What the person confirms per chat before it is read (ruling 47a amendment); `{name}` is the chat's name.
    var consentAsk = ""
    var credentials: String?
    var error: String?
    var listening = false
    /// While `state == "qr"`: the `tg://login` link the panel draws as a QR (owner 2026-10-29) — shown, never kept.
    var qrUrl: String?

    enum CodingKeys: String, CodingKey { case state, consent, consentAsk, credentials, error, listening, qrUrl }

    init(state: String = "off", consent: String = "", credentials: String? = nil, error: String? = nil,
         qrUrl: String? = nil) {
        self.state = state
        self.consent = consent
        self.credentials = credentials
        self.error = error
        self.qrUrl = qrUrl
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = (try? c.decodeIfPresent(String.self, forKey: .state)) ?? "off"
        consent = (try? c.decodeIfPresent(String.self, forKey: .consent)) ?? ""
        consentAsk = (try? c.decodeIfPresent(String.self, forKey: .consentAsk)) ?? ""
        credentials = try? c.decodeIfPresent(String.self, forKey: .credentials)
        error = try? c.decodeIfPresent(String.self, forKey: .error)
        listening = (try? c.decodeIfPresent(Bool.self, forKey: .listening)) ?? false
        qrUrl = try? c.decodeIfPresent(String.self, forKey: .qrUrl)
    }
}

/// One Telegram chat as the tick list shows it — names only; the backend never keeps an unticked one.
struct TelegramChatRow: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var name = ""
    var group = false
    var bot: Bool?
    var last: String?
    var ticked = false
    var history = false
    /// When the person confirmed the other person agreed (ruling 47a amendment).
    var consentedAt: String?

    enum CodingKeys: String, CodingKey { case id, name, group, bot, last, ticked, history, consentedAt }

    init(id: String, name: String = "", group: Bool = false, ticked: Bool = false, history: Bool = false) {
        self.id = id
        self.name = name
        self.group = group
        self.ticked = ticked
        self.history = history
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        group = (try? c.decodeIfPresent(Bool.self, forKey: .group)) ?? false
        bot = try? c.decodeIfPresent(Bool.self, forKey: .bot)
        last = try? c.decodeIfPresent(String.self, forKey: .last)
        ticked = (try? c.decodeIfPresent(Bool.self, forKey: .ticked)) ?? false
        history = (try? c.decodeIfPresent(Bool.self, forKey: .history)) ?? false
        consentedAt = try? c.decodeIfPresent(String.self, forKey: .consentedAt)
    }
}

struct TelegramChatsAnswer: Decodable, Equatable, Sendable {
    var chats: [TelegramChatRow] = []
}

/// The routes behind WhatsApp's and Telegram's rows. `source` is `whatsapp` or `telegram`.
protocol ChatSourcesAPI: Sendable {
    func fetchChatTicks(source: String) async throws -> ChatTickAnswer
    func describeChats(source: String, ids: [(id: String, group: Bool)]) async throws -> ChatTickAnswer
    func updateChat(source: String, id: String, name: String?, group: Bool?, ticked: Bool?, history: Bool?) async throws
        -> ChatTickAnswer
    func postWhatsApp(_ json: Data) async throws -> ChatSyncAnswer
    func telegramStatus() async throws -> TelegramStatusAnswer
    func telegramQR() async throws -> TelegramStatusAnswer
    func telegramConnect(phone: String) async throws -> TelegramStatusAnswer
    func telegramCode(_ code: String) async throws -> TelegramStatusAnswer
    func telegramPassword(_ password: String) async throws -> TelegramStatusAnswer
    func telegramDisconnect() async throws -> TelegramStatusAnswer
    func telegramChats() async throws -> TelegramChatsAnswer
    /// Tick a one-to-one Telegram chat with the person's confirmation that the other person agreed, or untick it
    /// (which withdraws that confirmation) — ruling 47a amendment.
    func telegramTick(id: String, name: String, ticked: Bool, consent: Bool) async throws -> ChatTickAnswer
}

extension APIClient: ChatSourcesAPI {}
