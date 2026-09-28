import Foundation

/// The entity card's Repository section, end to end: the backend names the declared repos, `GitRunner` runs git in
/// the ones on this Mac (off the main actor), and the backend parses what it printed into `RepoContext`s. Any
/// failure — no declarations, an unreachable backend, a refused post — is no section, as before.
enum RepoCard {
    typealias Declarations = @Sendable (_ entityId: String) async throws -> RepoDeclarationList
    typealias Observe = @Sendable (_ declarations: RepoDeclarationList) async -> [GitRunner.Observation]
    typealias Post = @Sendable (_ entityId: String, _ observations: [GitRunner.Observation]) async throws -> [RepoContext]

    static func load(
        entityId: String,
        declarations: Declarations = { try await APIClient.shared.fetchEntityRepoDeclarations(entityId: $0) },
        observe: Observe = { await GitRunner.observeAll($0) },
        post: Post = { try await APIClient.shared.postObservedRepos(entityId: $0, $1) }
    ) async -> [RepoContext] {
        guard let declared = try? await declarations(entityId), !declared.repos.isEmpty else { return [] }
        // Not detached: this nonisolated call already runs off the main actor, and the card's cancellation must
        // reach `ChildProcess`, which kills a git still running.
        let observations = await observe(declared)
        // A card that moved on (another entity, closed) never posts: the late answer would land nowhere.
        guard !Task.isCancelled, observations.count == declared.repos.count else { return [] }
        return (try? await post(entityId, observations)) ?? []
    }
}
