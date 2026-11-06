import Foundation

extension Store {
    /// The one predicate every empty state asks before it says the memory is empty.
    ///
    /// A page that has no value for `domain` may say "nothing here" only when the backend answered and said so. When
    /// the domain's last read failed (`domainErrors`, latched at the failure and cleared when it next lands) or the
    /// backend is not answering at all (`reach`), the honest sentence is that the memory could not be read. Callers
    /// pair it with their own emptiness test — a snapshot holding a value was read, however old.
    func couldNotRead(_ domain: SyncDomain) -> Bool {
        domainErrors[domain] != nil || reach != .up
    }
}
