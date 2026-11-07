import Foundation

/// G154 — one card as the app posts it: names, and WHICH facts the card holds — never an address, a number or an
/// employer's name (R-SR8) — plus its thumbnail when it has one.
struct ContactRecord: Encodable, Equatable, Sendable {
    let id: String
    let givenName: String
    let familyName: String
    let hasOrganization: Bool
    let hasJobTitle: Bool
    let hasEmail: Bool
    let hasPhone: Bool
    let hasBirthday: Bool
    let photoB64: String?
    /// Owner ruling 2026-10-20 — the address book's own "me" card: the backend gives it to the owner's page (G169),
    /// never to a namesake, and never keeps it waiting. A flag about the person, not a fact from anyone's card — sent
    /// only on that one card, so every other card crosses the wire exactly as before.
    var isMe: Bool = false
    /// Proposed ruling 55: the card's numbers as keyed hashes (`PhoneNumberKeys`), never a digit. Empty while the backend
    /// gives no key, and then the card crosses the wire exactly as before.
    var phoneKeys: [String] = []

    enum CodingKeys: String, CodingKey {
        case id, givenName, familyName, hasOrganization, hasJobTitle, hasEmail, hasPhone, hasBirthday, photoB64, isMe,
             phoneKeys
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(givenName, forKey: .givenName)
        try c.encode(familyName, forKey: .familyName)
        try c.encode(hasOrganization, forKey: .hasOrganization)
        try c.encode(hasJobTitle, forKey: .hasJobTitle)
        try c.encode(hasEmail, forKey: .hasEmail)
        try c.encode(hasPhone, forKey: .hasPhone)
        try c.encode(hasBirthday, forKey: .hasBirthday)
        try c.encodeIfPresent(photoB64, forKey: .photoB64)
        if isMe { try c.encode(true, forKey: .isMe) }
        if !phoneKeys.isEmpty { try c.encode(phoneKeys, forKey: .phoneKeys) }
    }
}

/// `POST /sources/contacts-local/sync` — the whole address book (a removal needs the complete set).
struct ContactsSyncPayload: Encodable, Equatable, Sendable {
    let contacts: [ContactRecord]
    /// Review of #393: the connection this sync belongs to (minted at each Connect). The backend drops a sync from a
    /// connection the person has since ended, so one sent before Disconnect never saves its cards back. Omitted when nil.
    var connection: String? = nil
}

/// `PUT /sources/contacts-local/book` — every card, for the Contacts page's faces alone (`contacts_book`): its names
/// and thumbnail, never which facts it holds.
struct ContactsBookPayload: Encodable, Equatable, Sendable {
    struct Card: Encodable, Equatable, Sendable {
        let id: String
        let givenName: String
        let familyName: String
        let photoB64: String?
    }

    let cards: [Card]
    var connection: String? = nil

    init(records: [ContactRecord], connection: String?) {
        cards = records.map { Card(id: $0.id, givenName: $0.givenName, familyName: $0.familyName, photoB64: $0.photoB64) }
        self.connection = connection
    }
}

/// Task 3's answer; lenient, so a backend one field ahead or behind never fails the sync.
struct ContactsSyncResult: Decodable, Equatable, Sendable {
    var contacts = 0, matched = 0, people = 0, ambiguous = 0, unmatched = 0, sourcesAdded = 0, sourcesRemoved = 0,
        photos = 0
    /// Owner ruling 2026-10-20 — cards that matched no page and wait outside the bank for a first mention.
    var waiting = 0
    var bank = ""

    init(contacts: Int = 0, matched: Int = 0, people: Int = 0) {
        self.contacts = contacts; self.matched = matched; self.people = people
    }

    enum CodingKeys: String, CodingKey {
        case contacts, matched, people, ambiguous, unmatched, sourcesAdded, sourcesRemoved, photos, waiting, bank
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        contacts = c.lenient(.contacts, 0); matched = c.lenient(.matched, 0); people = c.lenient(.people, 0)
        ambiguous = c.lenient(.ambiguous, 0); unmatched = c.lenient(.unmatched, 0)
        sourcesAdded = c.lenient(.sourcesAdded, 0); sourcesRemoved = c.lenient(.sourcesRemoved, 0)
        photos = c.lenient(.photos, 0); waiting = c.lenient(.waiting, 0); bank = c.lenient(.bank, "")
    }
}

/// `GET /sources/contacts-local/book`: every card on this Mac as a face. Not a Store domain and no ETag; held in memory
/// by `ChannelItemsCache`, read when the page opens and when the channels move.
struct ContactsBook: Decodable, Equatable, Sendable {
    var total = 0
    var inMemory = 0
    var cards: [ContactsBookCard] = []

    init() {}

    enum CodingKeys: String, CodingKey { case total, inMemory, cards }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        total = c.lenient(.total, 0)
        inMemory = c.lenient(.inMemory, 0)
        cards = (try? c.decode([ContactsBookCard].self, forKey: .cards)) ?? []
    }
}

/// One face: a key hashed from the card id, its name (empty when it has none), the page that carries it, and a hash of
/// its thumbnail for the picture's address. Never a fact of the card.
struct ContactsBookCard: Decodable, Identifiable, Equatable, Sendable {
    let key: String
    let name: String
    let entityId: String?
    let photo: String?
    /// The name folded once when it is read, so typing in the search never folds thousands of names again.
    let folded: String

    var id: String { key }

    init(key: String, name: String, entityId: String? = nil, photo: String? = nil) {
        self.key = key; self.name = name; self.entityId = entityId; self.photo = photo
        folded = ContactsBookSearch.fold(name)
    }

    enum CodingKeys: String, CodingKey { case key, name, entityId, photo }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(key: try c.decode(String.self, forKey: .key), name: c.lenient(.name, ""),
                  entityId: try? c.decodeIfPresent(String.self, forKey: .entityId),
                  photo: try? c.decodeIfPresent(String.self, forKey: .photo))
    }
}

/// The grid's search, in memory and pure: the query never leaves the app. Every word must appear in the name, with case
/// and accents folded; a nameless card matches only an empty query.
enum ContactsBookSearch {
    nonisolated static func fold(_ text: String) -> String {
        text.folding(options: [.diacriticInsensitive, .caseInsensitive, .widthInsensitive], locale: nil)
    }

    static func filter(_ cards: [ContactsBookCard], query: String) -> [ContactsBookCard] {
        let words = fold(SourceSearch.normalized(query)).split(whereSeparator: \.isWhitespace)
        guard !words.isEmpty else { return cards }
        return cards.filter { card in words.allSatisfy { card.folded.contains($0) } }
    }
}

enum ContactsBookText {
    static func title(_ card: ContactsBookCard) -> String { card.name.isEmpty ? Copy.SourceBrowser.contactNoName : card.name }
}

/// What the book's `PUT` answers; nothing here reads it.
struct ContactsBookSavedAnswer: Decodable, Sendable {}

enum ContactsAccess: Equatable, Sendable { case notDetermined, granted, denied, restricted }

enum ContactsReadError: Error, Equatable, LocalizedError {
    case empty

    /// Said in words on a card's Sync now (`AddSourceSheet.friendlyError` falls back to `localizedDescription`).
    var errorDescription: String? { Copy.contactsEmpty }
}

/// The seam over the Contacts framework, so a test never asks macOS for anything.
protocol ContactStore: AnyObject, Sendable {
    func access() -> ContactsAccess
    func requestAccess() async -> Bool
    func snapshot() async -> [ContactRecord]
    /// Proposed ruling 55: the same cards, each number as a keyed hash when the backend gave a key.
    func snapshot(numberKey: String?) async -> [ContactRecord]
    /// `CNContactStore.currentHistoryToken` — it moves whenever the address book does (R-SR10).
    func historyToken() -> Data?
    func changes() -> AsyncStream<Void>
}

extension ContactStore {
    func snapshot(numberKey: String?) async -> [ContactRecord] { await snapshot() }
}

protocol ContactsSyncAPI: Sendable {
    /// Proposed ruling 55: the key to hash a card's numbers with; `nil` while the feature is off.
    func numberMatchKey() async -> String?
    func syncLocalContacts(_ payload: ContactsSyncPayload) async throws -> ContactsSyncResult
    /// Review of #391: Contacts stopped — every bank's waiting cards are deleted on the backend; `connection` names the
    /// connection that ended, so a sync of it still in flight is dropped (review of #393).
    func forgetWaitingContacts(connection: String?) async throws
    /// Every card, for the Contacts page's faces. Kept where this Mac's backend is; never read by a match.
    func putContactsBook(_ payload: ContactsBookPayload) async throws
    /// What the backend holds of the book, so the reader posts one when it holds none (review of #602).
    func fetchContactsBook() async throws -> ContactsBook
    /// The same forget under a route that runs on this computer: on a copy, the one above goes to the home.
    func forgetContactsBook(connection: String?) async throws
}

extension ContactsSyncAPI {
    func numberMatchKey() async -> String? { nil }
}

extension APIClient: ContactsSyncAPI {}

/// Pure pieces of the mapping (R-SR8): names trimmed, facts as booleans, a thumbnail only when it is small.
enum ContactMapper {
    static let photoCap = 64 * 1024

    static func record(id: String, given: String, family: String, organization: String, jobTitle: String,
                       emails: Int, phones: Int, hasBirthday: Bool, thumbnail: Data?,
                       isMe: Bool = false, phoneKeys: [String] = []) -> ContactRecord {
        let trim: (String) -> String = { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        let photo = thumbnail.flatMap { !$0.isEmpty && $0.count <= photoCap ? $0.base64EncodedString() : nil }
        return ContactRecord(id: id, givenName: trim(given), familyName: trim(family),
                             hasOrganization: !trim(organization).isEmpty, hasJobTitle: !trim(jobTitle).isEmpty,
                             hasEmail: emails > 0, hasPhone: phones > 0, hasBirthday: hasBirthday, photoB64: photo,
                             isMe: isMe, phoneKeys: phoneKeys)
    }
}
