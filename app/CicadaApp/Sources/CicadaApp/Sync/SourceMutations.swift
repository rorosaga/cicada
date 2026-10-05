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

    /// A trusted site draws the page's mark (`logo_service.domain_for`): the graph's picture moves with it.
    var refreshDomains: Set<SyncDomain> { [.graph] }
}

/// Audit 2026-10-02 A06 — an add to a page's sources, run by `Store.perform` so a failure says the server's sentence
/// (`SourceWriteFailure.message`, as an edit does) instead of vanishing behind `try?`. Nothing is painted before the
/// answer — the server decides the entry's shape — so there is nothing to roll back; the list is the server's answer.
struct EntitySourceAdd: Mutation {
    let entityId: String
    let ref: String
    let predicate: String?
    let sources: Binding<[EntitySource]>
    private let failure = MutationMemo<any Error>()

    init(entityId: String, ref: String, predicate: String?, sources: Binding<[EntitySource]>) {
        self.entityId = entityId
        self.ref = ref
        self.predicate = predicate
        self.sources = sources
    }

    func optimistic(_ store: Store) async {}

    func request(_ api: any SyncAPI) async throws {
        do {
            sources.wrappedValue = try await api.addEntitySource(entityId: entityId, ref: ref, predicate: predicate)
        } catch {
            failure.value = error
            throw error
        }
    }

    func rollback(_ store: Store) async {}

    var failureMessage: String { SourceWriteFailure.message(failure.value) }

    /// None here: the card forgets the site's cached icon first and then refreshes `.graph` itself, on success only.
    var refreshDomains: Set<SyncDomain> { [] }
}

/// Audit A05 — one open page's source writes, run one at a time in the order the person made them. Each mutation's
/// optimistic step then snapshots the list the previous write left, so a failure rolls back only its own change and
/// a slow first answer can never overwrite a newer one. Card-local, like the list it edits: another page has its own.
@MainActor
final class SourceWriteQueue {
    private var tail: Task<Void, Never>?

    @discardableResult
    func run<T: Sendable>(_ work: @escaping @MainActor () async -> T) -> Task<T, Never> {
        let previous = tail
        let task = Task { @MainActor in
            await previous?.value
            return await work()
        }
        tail = Task { @MainActor in _ = await task.value }
        return task
    }
}

/// Audit A06 — what the add field holds once its request is answered. The draft stays in the field while the request
/// is in flight; a success clears it unless the person has typed something new, a failure keeps what they have (the
/// submitted text if they cleared the field).
enum SourceDraft {
    static func afterAdd(submitted: String, current: String, landed: Bool) -> String {
        if landed { return current == submitted ? "" : current }
        return current.isEmpty ? submitted : current
    }
}
