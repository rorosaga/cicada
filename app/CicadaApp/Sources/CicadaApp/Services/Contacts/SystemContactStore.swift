import Contacts
import Foundation

/// G154 — the real `ContactStore`: the Mac's address book (every account the Contacts app holds), after the one
/// standard prompt (`NSContactsUsageDescription`). Only the keys a fact needs are fetched; the notes field is never
/// requested — it needs Apple's `com.apple.developer.contacts.notes` entitlement, and it is where the most personal
/// words live. Nothing is ever written back.
final class SystemContactStore: ContactStore, @unchecked Sendable {
    private let store = CNContactStore()

    func access() -> ContactsAccess {
        let status = CNContactStore.authorizationStatus(for: .contacts)
        if status == .authorized { return .granted }
        if status == .notDetermined { return .notDetermined }
        if status == .restricted { return .restricted }
        return .denied
    }

    func requestAccess() async -> Bool {
        (try? await store.requestAccess(for: .contacts)) ?? false
    }

    func historyToken() -> Data? { store.currentHistoryToken }

    /// Every card, mapped. Detached at utility priority: a large address book takes a moment, never on the main actor.
    func snapshot() async -> [ContactRecord] {
        let store = self.store
        return await Task.detached(priority: .utility) { () -> [ContactRecord] in
            let keys = [CNContactGivenNameKey, CNContactFamilyNameKey, CNContactOrganizationNameKey,
                        CNContactJobTitleKey, CNContactEmailAddressesKey, CNContactPhoneNumbersKey,
                        CNContactBirthdayKey, CNContactThumbnailImageDataKey] as [CNKeyDescriptor]
            final class Box { var records: [ContactRecord] = [] }
            let box = Box()
            do {
                try store.enumerateContacts(with: CNContactFetchRequest(keysToFetch: keys)) { contact, _ in
                    box.records.append(ContactMapper.record(
                        id: contact.identifier, given: contact.givenName, family: contact.familyName,
                        organization: contact.organizationName, jobTitle: contact.jobTitle,
                        emails: contact.emailAddresses.count, phones: contact.phoneNumbers.count,
                        hasBirthday: contact.birthday != nil, thumbnail: contact.thumbnailImageData))
                }
            } catch {
                return []   // never posted (R-SR10)
            }
            return box.records
        }.value
    }

    func changes() -> AsyncStream<Void> {
        AsyncStream { continuation in
            let task = Task {
                for await _ in NotificationCenter.default.notifications(named: .CNContactStoreDidChange) {
                    continuation.yield()
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
