import Foundation

/// G179 — one conversation in the Messages database, as the Settings list shows it: one-to-one, or a group
/// (2026-10-28). App-side only: `handle` and a group's `members` (phone numbers or addresses) are used to find names
/// and photos on this Mac and never leave the app; the backend knows the conversation by `id`, a hash of `chat.guid`,
/// and a member by `MessagesReader.memberKey`.
struct MessagesConversation: Identifiable, Equatable, Sendable {
    let id: String
    let chatRowId: Int64
    let handle: String
    let displayName: String
    let service: String
    let lastActivity: Date?
    let fromMe: Int
    let fromThem: Int
    var isGroup = false
    /// A group's members' handles — app-only, never posted.
    var members: [String] = []

    var messageCount: Int { fromMe + fromThem }
}

/// One group member as posted: its participant key, the name the person sees for them (their Contacts card, else
/// nothing — never the handle), and the id of the person's one-to-one chat with them when there is one (so a member
/// the person marked an AI agent there stays one here).
struct MessagesMemberPayload: Equatable, Sendable {
    let key: String
    let name: String
    let direct: String?
    /// The member's ONE address-book card, by its Contacts id (never the handle); nil when none or several.
    var contact: String? = nil

    var json: [String: Any] {
        var out: [String: Any] = ["key": key, "name": name]
        if let direct { out["direct"] = direct }
        if let contact { out["contact"] = contact }
        return out
    }
}

/// Where a ticked conversation's reading stopped, per memory: the highest `message.ROWID` posted, and, per posted row
/// edited or unsent within `MessagesReader.editWindow`, the edit or unsend time (`date_edited` / `date_retracted`,
/// Apple nanoseconds) last posted for it — an edit keeps its old ROWID. Per row, not one maximum: an edit that reaches
/// this Mac late carries an earlier time than one already seen and would hide under a single watermark.
///
/// A cursor saved before `edits` existed (it carried a single `changed` time) decodes with no record: the next pass
/// re-posts the window's edited rows once, and the backend's per-message merge keeps them as they are.
struct MessagesCursor: Codable, Equatable, Sendable {
    var rowid: Int64 = 0
    var edits: [Int64: Int64] = [:]

    init(rowid: Int64 = 0, edits: [Int64: Int64] = [:]) {
        self.rowid = rowid
        self.edits = edits
    }

    enum CodingKeys: String, CodingKey { case rowid, edits }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        rowid = (try? c.decodeIfPresent(Int64.self, forKey: .rowid)) ?? 0
        edits = (try? c.decodeIfPresent([Int64: Int64].self, forKey: .edits)) ?? [:]
    }
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

        /// `actor` is a free-form block on the wire (`agent_detectors.Actor.to_dict`), so its keys arrive as the backend
        /// wrote them — `decided_by`, not camelCased by the response model. Both spellings are read: reading only
        /// `decidedBy` left every person's mark at "none", and the pill kept saying "suggested" after the person chose.
        enum CodingKeys: String, CodingKey { case name, kind, decidedBy, decidedBySnake = "decided_by", detection }
        init(name: String = "", kind: String = "unknown", decidedBy: String = "none", detection: String? = nil) {
            self.name = name; self.kind = kind; self.decidedBy = decidedBy; self.detection = detection
        }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            name = c.lenient(.name, ""); kind = c.lenient(.kind, "unknown")
            decidedBy = c.lenient(.decidedBy) ?? c.lenient(.decidedBySnake) ?? "none"
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
    /// The correspondent's own page when one exists (`messages_source.waiting`: the page Sleep resolves the decided
    /// correspondent to, never a page that only shares the chat's name) — the bubble draws that page's picture.
    var page: String? = nil

    var id: String { conversation }

    enum CodingKeys: String, CodingKey { case conversation, name, kind, messages, sittings, page }
    init(conversation: String, name: String, kind: String = "unknown", messages: Int, sittings: Int = 1,
         page: String? = nil) {
        self.conversation = conversation; self.name = name; self.kind = kind; self.messages = messages
        self.sittings = sittings; self.page = page
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        conversation = try c.decode(String.self, forKey: .conversation)
        name = c.lenient(.name, ""); kind = c.lenient(.kind, "unknown")
        messages = c.lenient(.messages, 0); sittings = c.lenient(.sittings, 0)
        let raw: String? = c.lenient(.page)
        page = raw?.isEmpty == false ? raw : nil
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
        group = conversation.isGroup
        fromMe = conversation.fromMe
        fromThem = conversation.fromThem
    }
}

/// One ticked chat's shared Messages photo, as posted (`PUT /sources/messages/photos`, 2026-10-16): the small PNG the
/// app made (`MessagesSharedPhotos.downsized`), or none — the chat shares no photo, so the backend drops a stored one.
struct MessagesPhotoPayload: Encodable, Equatable, Sendable {
    let conversation: String
    let photoB64: String?

    init(conversation: String, photo: Data?) {
        self.conversation = conversation
        photoB64 = photo?.base64EncodedString()
    }
}

struct MessagesPhotosAnswer: Decodable, Sendable {
    var stored = 0
    var removed = 0
    var unchanged = 0
    /// Each posted chat's linked page, or nil while it has none (the backend links it as the page appears).
    var pages: [String: String?] = [:]
    enum CodingKeys: String, CodingKey { case stored, removed, unchanged, pages }
    init(stored: Int = 0, removed: Int = 0, unchanged: Int = 0, pages: [String: String?] = [:]) {
        self.stored = stored; self.removed = removed; self.unchanged = unchanged; self.pages = pages
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        stored = c.lenient(.stored, 0); removed = c.lenient(.removed, 0); unchanged = c.lenient(.unchanged, 0)
        pages = (try? c.decode([String: String?].self, forKey: .pages)) ?? [:]
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
    func setMessagesSuggestAgents(_ on: Bool) async throws -> MessagesSettingsAnswer
    func postMessages(_ json: Data) async throws -> MessagesSyncResult
    func fetchMessagesWaiting() async throws -> MessagesWaitingAnswer
    /// The shared photos of ticked chats, kept by the backend outside every bank and drawn at each chat's page.
    func putMessagesPhotos(_ photos: [MessagesPhotoPayload]) async throws -> MessagesPhotosAnswer
}

extension APIClient: MessagesAPI {}
