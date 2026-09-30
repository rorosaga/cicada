import SwiftUI

/// G61 S3-a — one edit to one of a page's sources, run by `Store.perform` like every write the app sends. The card's
/// list is painted with what the server will answer (`SourceChange.apply`, the same function the tests run) and
/// replaced by the server's own list when it lands; a failure restores the list and toasts the server's sentence.
/// The list lives on the card (`@State`), not in a Store domain — `EntitySource`s are fetched per open page — so the
/// mutation holds a binding to it.
struct EntitySourceWrite: Mutation {
    let entityId: String
    /// The entry as it stood when the person chose — its `id` and `(ref, predicate)` are the key.
    let source: EntitySource
    let change: SourceChange
    let sources: Binding<[EntitySource]>
    private let previous = MutationMemo<[EntitySource]>()
    private let failure = MutationMemo<any Error>()

    init(entityId: String, source: EntitySource, change: SourceChange, sources: Binding<[EntitySource]>) {
        self.entityId = entityId
        self.source = source
        self.change = change
        self.sources = sources
    }

    func optimistic(_ store: Store) async {
        previous.value = sources.wrappedValue
        sources.wrappedValue = SourceList.applying(change, toId: source.id, in: sources.wrappedValue)
    }

    func request(_ api: any SyncAPI) async throws {
        do {
            sources.wrappedValue = try await api.changeEntitySource(entityId: entityId, source: source, change: change)
        } catch {
            failure.value = error
            throw error
        }
    }

    func rollback(_ store: Store) async {
        if let previous = previous.value { sources.wrappedValue = previous }
    }

    var failureMessage: String { SourceWriteFailure.message(failure.value) }
}
