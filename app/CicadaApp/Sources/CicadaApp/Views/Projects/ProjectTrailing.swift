import Foundation

/// G150 (R-B21) — what the Projects page's third column holds besides the Reader: an entity's card (R-PP17) or a
/// backlog item. One slot: opening one replaces the other, and the Reader, when open, wins it (DR-31).
enum ProjectTrailing: Equatable {
    case entity(String)
    case backlogItem(String)

    var entityId: String? {
        switch self {
        case .entity(let id): id
        case .backlogItem: nil
        }
    }

    var backlogItemId: String? {
        switch self {
        case .backlogItem(let id): id
        case .entity: nil
        }
    }

    /// DR-28 — what Esc (and DR-27's "‹ N projects") closes next: the Reader, then the item or card, then the project.
    enum Step: Equatable { case reader, trailing, project, nothing }

    static func escape(readerOpen: Bool, trailing: ProjectTrailing?, projectOpen: Bool) -> Step {
        if readerOpen { return .reader }
        if trailing != nil { return .trailing }
        return projectOpen ? .project : .nothing
    }
}
