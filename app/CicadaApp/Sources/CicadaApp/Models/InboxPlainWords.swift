import Foundation

/// Inbox v2 (owner 2026-10-26: "I don't really get the confirmation of links, for example. It's a bit weird, as are
/// possible duplicates and stuff"). What the two confusing kinds show a first-time reader, decided here so it is
/// tested without a view: the two sides of a possible duplicate, and what confirming a link does. Display only — the
/// answers each card sends are exactly the ones they sent before.

/// A possible duplicate's two sides, side by side: the name a conversation used (with its page when it has one) and the
/// existing page it may be. The existing page is the merge's data source (`mergeTargetHint`), as before.
struct MergePair: Equatable {
    struct Side: Equatable {
        let id: String
        let name: String
        let type: EntityType?
        let summary: String?
        /// A name below the promotion bar has no page yet: it is only a name said in a conversation.
        let hasPage: Bool
    }

    let mention: Side
    let existing: Side

    /// The candidate's name as Sleep wrote it ("Possible duplicate of Bob Example" → "Bob Example").
    static func candidateName(_ item: InboxItem) -> String? {
        let prefix = "possible duplicate of "
        guard let raw = item.uncertaintyType, raw.lowercased().hasPrefix(prefix) else { return nil }
        let name = String(raw.dropFirst(prefix.count)).trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty ? nil : name
    }

    static func of(_ item: InboxItem, nodes: [GraphNode]) -> MergePair {
        func node(_ id: String) -> GraphNode? {
            id.isEmpty ? nil : nodes.first { $0.id == id && !$0.isFacet }
        }
        func summary(_ node: GraphNode?) -> String? {
            let text = node?.summary?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return text.isEmpty ? nil : text
        }
        let mentionNode = node(item.entityId)
        let mention = Side(id: item.entityId, name: mentionNode?.name ?? item.displayName,
                           type: mentionNode?.type ?? item.entityType.flatMap(EntityType.init(rawValue:)),
                           summary: summary(mentionNode), hasPage: mentionNode != nil)
        let hint = (item.mergeTargetHint ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let existingNode = node(hint)
        let existingName = existingNode?.name ?? candidateName(item) ?? hint
        let existing = Side(id: hint, name: existingName, type: existingNode?.type, summary: summary(existingNode),
                            hasPage: existingNode != nil)
        return MergePair(mention: mention, existing: existing)
    }

    /// Whether the card can offer Merge at once: it knows which existing page the name would join.
    var canMerge: Bool { !existing.id.isEmpty }

    /// What Merge does, in one sentence: the name joins the existing page, and a page of its own folds into it.
    var mergeWords: String {
        mention.hasPage
            ? Copy.Inbox.Duplicate.mergeFolds(mention.name, existing.name)
            : Copy.Inbox.Duplicate.mergeNames(mention.name, existing.name)
    }
}

/// One waiting link of the "Confirm N links" review, in words: what kind of link it is, why Cicada proposed it, and
/// what confirming it changes. Taking a link makes it a trusted source of its page (`storage.md`, "Where to check"):
/// re-checked on a schedule, checked by agents before they answer, and — a person's own profile — where their picture
/// can come from, or — a site on a page that is not a person — where its logo comes from (G146/G159).
enum WhereToCheckWords {
    static let profileKinds: Set<String> = ["github", "x", "instagram", "linkedin"]

    /// "GitHub profile", "website" — the link kind as a person would say it.
    static func kindName(_ kind: String, pageType: String) -> String {
        switch kind {
        case "github": pageType == "person" ? "GitHub profile" : "GitHub page"
        case "x": "X profile"
        case "instagram": "Instagram profile"
        case "linkedin": "LinkedIn profile"
        case "scholar": "Google Scholar page"
        case "orcid": "ORCID record"
        case "repo": "repository"
        case "contacts": "Contacts card"
        case "app": "app"
        case "path": "folder"
        case "note": "note"
        default: "website"
        }
    }

    /// What confirming does, for this page and this kind of link.
    static func effect(_ row: WhereToCheckRow, kind: String) -> String {
        let name = row.pageName.isEmpty ? row.page : row.pageName
        let what = kindName(kind, pageType: row.pageType)
        if row.pageType == "person" {
            return profileKinds.contains(kind)
                ? Copy.WhereToCheck.effectPersonProfile(name, what)
                : Copy.WhereToCheck.effectPersonOther(name, what)
        }
        switch kind {
        case "website": return Copy.WhereToCheck.effectWebsite(name)
        case "repo", "github": return Copy.WhereToCheck.effectRepo(name, what)
        default: return Copy.WhereToCheck.effectOther(name, what)
        }
    }

    /// Why Cicada proposed it, from where it was found (DR-54: never an episode id).
    static func why(_ row: WhereToCheckRow) -> String {
        guard let evidence = row.evidence else { return Copy.WhereToCheck.fromAgentNoLine }
        if evidence.page == true { return Copy.WhereToCheck.fromPage }
        return (evidence.kind ?? "user") == "user" ? Copy.WhereToCheck.fromYou : Copy.WhereToCheck.fromAgent
    }

    /// The decline's words: a person's account is "Not theirs", anything else "Not this one".
    static func declineLabel(_ row: WhereToCheckRow) -> String {
        row.pageType == "person" ? Copy.WhereToCheck.notTheirs : Copy.WhereToCheck.notThis
    }

    /// The link as a short line: host and path, no scheme, no "www.", no trailing slash.
    static func shortRef(_ ref: String) -> String {
        guard let url = URL(string: ref), let host = url.host else { return ref }
        let bare = host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
        let path = url.path == "/" ? "" : url.path
        return bare + path
    }

    /// The rows under their pages, each page where its first row is, so a page with three links is named once.
    struct PageRows: Identifiable, Equatable {
        let page: String
        let pageName: String
        let pageType: String
        let rows: [WhereToCheckRow]

        var id: String { page }
    }

    static func byPage(_ rows: [WhereToCheckRow]) -> [PageRows] {
        var order: [String] = []
        var groups: [String: [WhereToCheckRow]] = [:]
        for row in rows {
            if groups[row.page] == nil { order.append(row.page) }
            groups[row.page, default: []].append(row)
        }
        return order.map { page in
            let rows = groups[page] ?? []
            return PageRows(page: page, pageName: rows[0].pageName.isEmpty ? page : rows[0].pageName,
                            pageType: rows[0].pageType, rows: rows)
        }
    }

    /// Pages shown before "Show N more": a long review starts short (DR-39), the rest one click away.
    static let firstPages = 3
}
