import Foundation
@testable import CicadaApp

/// Tests never reach this Mac's Contacts service (`contactsd`) or the person's address book (#527 review). Every
/// Messages Contacts read goes through `MessagesContacts`' two doors; a test class that builds a watcher installs this
/// trap in its `setUp`, and the doors then answer "not allowed" and no cards, and count every knock.
enum ContactsTrap {
    nonisolated(unsafe) static var knocks = 0

    static func install() {
        knocks = 0
        MessagesContacts.authorization = {
            ContactsTrap.knocks += 1
            return false
        }
        MessagesContacts.lookUp = { _ in
            ContactsTrap.knocks += 1
            return [:]
        }
    }
}
