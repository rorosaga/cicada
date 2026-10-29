import Contacts
import Foundation

/// The name and Contacts photo of a conversation's other side, found on this Mac by its handle (a phone number or an
/// address). Read only after the person allowed Contacts (G154's prompt); never asked from here, never sent anywhere —
/// the photo is drawn in the app (the picture rails: the Contacts photo is allowed; nothing from the web).
struct MessagesContactCard: Equatable, Sendable {
    var name: String
    var thumbnail: Data?
    /// The card's own Contacts identifier — the same opaque id the Contacts sync posts — set only when exactly ONE
    /// card holds the handle (one person across sources, 2026-10-28). Never a phone number or an address.
    var id: String? = nil
}

enum MessagesContacts {
    static var allowed: Bool { CNContactStore.authorizationStatus(for: .contacts) == .authorized }

    /// The cards for `handles`, keyed by handle. Empty when Contacts is not allowed.
    static func cards(for handles: [String]) async -> [String: MessagesContactCard] {
        guard allowed, !handles.isEmpty else { return [:] }
        return await Task.detached(priority: .utility) { () -> [String: MessagesContactCard] in
            let store = CNContactStore()
            let keys: [CNKeyDescriptor] = [CNContactFormatter.descriptorForRequiredKeys(for: .fullName),
                                           CNContactThumbnailImageDataKey as CNKeyDescriptor]
            var out: [String: MessagesContactCard] = [:]
            for handle in Set(handles) where !handle.isEmpty {
                let predicate = handle.contains("@")
                    ? CNContact.predicateForContacts(matchingEmailAddress: handle)
                    : CNContact.predicateForContacts(matching: CNPhoneNumber(stringValue: handle))
                guard let found = try? store.unifiedContacts(matching: predicate, keysToFetch: keys),
                      let contact = found.first else { continue }
                let name = CNContactFormatter.string(from: contact, style: .fullName) ?? ""
                out[handle] = MessagesContactCard(name: name, thumbnail: contact.thumbnailImageData,
                                                  id: found.count == 1 ? contact.identifier : nil)
            }
            return out
        }.value
    }
}
