import Foundation

/// Round-4 D6 (R-FA2) — everything the detail column derives from one timeline on one day, built OFF the main actor:
/// the project's state, Lately's groups and count, and the chips' document index. Decoding already runs inside
/// `actor APIClient` (`ProjectsAPI`); this moves the rest out of `body`, where it ran on every evaluation, so a
/// story's size never blocks the main actor.
struct ProjectDerived: Equatable, Sendable {
    struct Key: Hashable, Sendable {
        let projectId: String
        let today: ISODay
        let revision: Int
    }

    let key: Key
    let state: ProjectState.Output
    let groups: [ProjectStory.Group]
    let happenings: Int
    let docIndex: EvidenceDocIndex

    static func build(_ t: ProjectTimeline, key: Key) -> ProjectDerived {
        ProjectDerived(key: key,
                       state: ProjectState.state(ProjectState.Input(t), today: key.today),
                       groups: ProjectStory.groups(t.items, today: key.today),
                       happenings: t.items.filter { $0.kind != "created" }.count,
                       docIndex: ProjectSource.docIndex(t))
    }

    /// Detached, so it never inherits the caller's main actor.
    static func make(_ t: ProjectTimeline, key: Key) async -> ProjectDerived {
        await Task.detached(priority: .userInitiated) { build(t, key: key) }.value
    }
}
