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
}

/// `POST /sources/contacts-local/sync` — the whole address book (a removal needs the complete set).
struct ContactsSyncPayload: Encodable, Equatable, Sendable {
    let contacts: [ContactRecord]
}

/// Task 3's answer; lenient, so a backend one field ahead or behind never fails the sync.
struct ContactsSyncResult: Decodable, Equatable, Sendable {
    var contacts = 0, matched = 0, people = 0, ambiguous = 0, unmatched = 0, sourcesAdded = 0, sourcesRemoved = 0,
        photos = 0
    var bank = ""

    init(contacts: Int = 0, matched: Int = 0, people: Int = 0) {
        self.contacts = contacts; self.matched = matched; self.people = people
    }

    enum CodingKeys: String, CodingKey {
        case contacts, matched, people, ambiguous, unmatched, sourcesAdded, sourcesRemoved, photos, bank
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        contacts = c.lenient(.contacts, 0); matched = c.lenient(.matched, 0); people = c.lenient(.people, 0)
        ambiguous = c.lenient(.ambiguous, 0); unmatched = c.lenient(.unmatched, 0)
        sourcesAdded = c.lenient(.sourcesAdded, 0); sourcesRemoved = c.lenient(.sourcesRemoved, 0)
        photos = c.lenient(.photos, 0); bank = c.lenient(.bank, "")
    }
}

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
    /// `CNContactStore.currentHistoryToken` — it moves whenever the address book does (R-SR10).
    func historyToken() -> Data?
    func changes() -> AsyncStream<Void>
}

protocol ContactsSyncAPI: Sendable {
    func syncLocalContacts(_ payload: ContactsSyncPayload) async throws -> ContactsSyncResult
}

extension APIClient: ContactsSyncAPI {}

/// Pure pieces of the mapping (R-SR8): names trimmed, facts as booleans, a thumbnail only when it is small.
enum ContactMapper {
    static let photoCap = 64 * 1024

    static func record(id: String, given: String, family: String, organization: String, jobTitle: String,
                       emails: Int, phones: Int, hasBirthday: Bool, thumbnail: Data?) -> ContactRecord {
        let trim: (String) -> String = { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
        let photo = thumbnail.flatMap { !$0.isEmpty && $0.count <= photoCap ? $0.base64EncodedString() : nil }
        return ContactRecord(id: id, givenName: trim(given), familyName: trim(family),
                             hasOrganization: !trim(organization).isEmpty, hasJobTitle: !trim(jobTitle).isEmpty,
                             hasEmail: emails > 0, hasPhone: phones > 0, hasBirthday: hasBirthday, photoB64: photo)
    }
}
