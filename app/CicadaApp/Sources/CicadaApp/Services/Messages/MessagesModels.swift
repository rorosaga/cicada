import Foundation

/// G179 — one 1:1 conversation in the Messages database, as the Settings list shows it. App-side only: `handle` (the
/// phone number or address) is used to find the contact's name and photo on this Mac and never leaves the app; the
/// backend knows the conversation by `id`, a hash of `chat.guid`.
struct MessagesConversation: Identifiable, Equatable, Sendable {
    let id: String
    let chatRowId: Int64
    let handle: String
    let displayName: String
    let service: String
    let lastActivity: Date?
    let fromMe: Int
    let fromThem: Int

    var messageCount: Int { fromMe + fromThem }
}

/// Where a ticked conversation's reading stopped, per memory: the highest `message.ROWID` posted, and the newest
/// edit or unsend time (`date_edited` / `date_retracted`, Apple nanoseconds) seen — an edit keeps its old ROWID.
struct MessagesCursor: Codable, Equatable, Sendable {
    var rowid: Int64 = 0
    var changed: Int64 = 0
}

/// One read of a ticked conversation, ready to post: the rows past the cursor (plus edited or unsent ones), already
/// serialised off the main actor.
struct MessagesPass: Sendable {
    var json: Data
    var cursor: MessagesCursor
    var count: Int
    var hasMore: Bool
}

/// `POST /sources/messages/conversations`' answer for one conversation: the person's tick and mark, and the
/// detectors' suggestion. Lenient — a backend a field ahead or behind never fails the list.
struct MessagesConversationState: Decodable, Equatable, Sendable {
    struct Actor: Decodable, Equatable, Sendable {
        var name = ""
        var kind = "unknown"
        var decidedBy = "none"
        var detection: String?

        enum CodingKeys: String, CodingKey { case name, kind, decidedBy, detection }
        init(name: String = "", kind: String = "unknown", decidedBy: String = "none", detection: String? = nil) {
            self.name = name; self.kind = kind; self.decidedBy = decidedBy; self.detection = detection
        }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            name = c.lenient(.name, ""); kind = c.lenient(.kind, "unknown"); decidedBy = c.lenient(.decidedBy, "none")
            detection = try? c.decodeIfPresent(String.self, forKey: .detection)
        }
    }

    struct Suggestion: Decodable, Equatable, Sendable {
        var outcome = "unknown"
        var label: String?
        enum CodingKeys: String, CodingKey { case outcome, label }
        init(outcome: String = "unknown", label: String? = nil) { self.outcome = outcome; self.label = label }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            outcome = c.lenient(.outcome, "unknown")
            label = try? c.decodeIfPresent(String.self, forKey: .label)
        }
    }

    var id: String
    var ticked = false
    var actor = Actor()
    var suggestion = Suggestion()
    /// The person's own mark (`agent` | `person`), nil when they never chose.
    var markedKind: String?

    enum CodingKeys: String, CodingKey { case id, ticked, actor, suggestion, marked }
    enum MarkKeys: String, CodingKey { case kind }

    init(id: String, ticked: Bool = false, actor: Actor = Actor(), suggestion: Suggestion = Suggestion(),
         markedKind: String? = nil) {
        self.id = id; self.ticked = ticked; self.actor = actor; self.suggestion = suggestion; self.markedKind = markedKind
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        ticked = c.lenient(.ticked, false)
        actor = (try? c.decode(Actor.self, forKey: .actor)) ?? Actor()
        suggestion = (try? c.decode(Suggestion.self, forKey: .suggestion)) ?? Suggestion()
        markedKind = (try? c.nestedContainer(keyedBy: MarkKeys.self, forKey: .marked))
            .flatMap { try? $0.decodeIfPresent(String.self, forKey: .kind) }
    }

    var isAgent: Bool { actor.kind == "agent" }
    /// The detectors think so but nobody has said: the list asks.
    var asksIfAgent: Bool { markedKind == nil && suggestion.outcome == "uncertain" }
}

struct MessagesConversationsAnswer: Decodable, Sendable {
    var suggestAgents = true
    var conversations: [MessagesConversationState] = []
    enum CodingKeys: String, CodingKey { case suggestAgents, conversations }
    init(suggestAgents: Bool = true, conversations: [MessagesConversationState] = []) {
        self.suggestAgents = suggestAgents; self.conversations = conversations
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        suggestAgents = c.lenient(.suggestAgents, true)
        conversations = (try? c.decode([MessagesConversationState].self, forKey: .conversations)) ?? []
    }
}

/// `GET /sources/messages/settings` — which conversations are ticked in this memory.
struct MessagesSettingsAnswer: Decodable, Sendable {
    struct Entry: Decodable, Sendable {
        var ticked = false
        var name = ""
        enum CodingKeys: String, CodingKey { case ticked, name }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            ticked = c.lenient(.ticked, false); name = c.lenient(.name, "")
        }
    }
    var suggestAgents = true
    var conversations: [String: Entry] = [:]
    var reattributed = 0
    enum CodingKeys: String, CodingKey { case suggestAgents, conversations, reattributed }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        suggestAgents = c.lenient(.suggestAgents, true)
        conversations = (try? c.decode([String: Entry].self, forKey: .conversations)) ?? [:]
        reattributed = c.lenient(.reattributed, 0)
    }

    var tickedIds: Set<String> { Set(conversations.filter(\.value.ticked).keys) }
}

struct MessagesSyncResult: Decodable, Equatable, Sendable {
    var created = 0, updated = 0, skipped = 0, tombstoned = 0, kept = 0, sittings = 0
    enum CodingKeys: String, CodingKey { case created, updated, skipped, tombstoned, kept, sittings }
    init(created: Int = 0, updated: Int = 0, skipped: Int = 0, tombstoned: Int = 0, kept: Int = 0, sittings: Int = 0) {
        self.created = created; self.updated = updated; self.skipped = skipped; self.tombstoned = tombstoned
        self.kept = kept; self.sittings = sittings
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        created = c.lenient(.created, 0); updated = c.lenient(.updated, 0); skipped = c.lenient(.skipped, 0)
        tombstoned = c.lenient(.tombstoned, 0); kept = c.lenient(.kept, 0); sittings = c.lenient(.sittings, 0)
    }
}

/// `GET /sources/messages/waiting` — one conversation whose messages Sleep has not read yet. Not a Store domain: the
/// Sleep page and Home fetch it in memory with the queue (`MessagesWatcher.refreshWaiting`).
struct MessagesWaitingItem: Decodable, Equatable, Identifiable, Sendable {
    var conversation: String
    var name = ""
    var kind = "unknown"
    var messages = 0
    var sittings = 0

    var id: String { conversation }

    enum CodingKeys: String, CodingKey { case conversation, name, kind, messages, sittings }
    init(conversation: String, name: String, kind: String = "unknown", messages: Int, sittings: Int = 1) {
        self.conversation = conversation; self.name = name; self.kind = kind; self.messages = messages
        self.sittings = sittings
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversation = try c.decode(String.self, forKey: .conversation)
        name = c.lenient(.name, ""); kind = c.lenient(.kind, "unknown")
        messages = c.lenient(.messages, 0); sittings = c.lenient(.sittings, 0)
    }
}

struct MessagesWaitingAnswer: Decodable, Sendable {
    var conversations: [MessagesWaitingItem] = []
    enum CodingKeys: String, CodingKey { case conversations }
    init(conversations: [MessagesWaitingItem] = []) { self.conversations = conversations }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversations = (try? c.decode([MessagesWaitingItem].self, forKey: .conversations)) ?? []
    }
}

/// What the app tells the backend about one listed conversation: its id, the name the person sees, and how many
/// messages each side sent — never the handle, never a word.
struct MessagesConversationPayload: Encodable, Equatable, Sendable {
    let id: String
    let name: String
    let displayName: String
    let service: String
    let group: Bool
    let fromMe: Int
    let fromThem: Int

    init(_ conversation: MessagesConversation, name: String) {
        id = conversation.id
        self.name = name
        displayName = conversation.displayName
        service = conversation.service
        group = false
        fromMe = conversation.fromMe
        fromThem = conversation.fromThem
    }
}

/// The person's answer to "who is this?" — or `clear` to go back to the detectors' suggestion.
enum MessagesMark: String, Sendable { case agent, person, clear }

/// The backend calls the Messages source makes — `APIClient` in the app, a fake in tests.
protocol MessagesAPI: Sendable {
    func fetchMessagesSettings() async throws -> MessagesSettingsAnswer
    func describeMessagesConversations(_ conversations: [MessagesConversationPayload]) async throws
        -> MessagesConversationsAnswer
    func updateMessagesConversation(id: String, name: String?, ticked: Bool?, mark: MessagesMark?) async throws
        -> MessagesSettingsAnswer
    func postMessages(_ json: Data) async throws -> MessagesSyncResult
    func fetchMessagesWaiting() async throws -> MessagesWaitingAnswer
}

extension APIClient: MessagesAPI {}
