import Foundation

/// The ⌘K palette's vocabulary (G136; round-3 design §3.3). Pure values: the
/// instant tier (`QuickIndex`), the server tier (`FindServerRows`), the merge
/// (`FindMerge`) and the views all speak these; nothing here touches the
/// network or the Store.

enum FindMode: String, Codable, Sendable { case find, ask }

enum FindKind: String, Codable, Sendable {
    case ask, entity, conversation, belief, media, source, inbox, setting, action, bank, askedBefore
}

/// A row's identity — the merge rule's dedupe key, `(kind, id)` (design §3.2),
/// and all a recent ever stores (R-SU6).
struct FindRowKey: Hashable, Codable, Sendable {
    let kind: FindKind
    let id: String
}

/// The fixed order (design §3.3: Top hit, Entities, Conversations, Beliefs,
/// Sources & papers, Inbox, Settings, Actions, Asked before), with the
/// empty-state groups (§3.6: Recent, Asked before, Suggested) in the same sequence.
enum FindGroupID: Int, CaseIterable, Comparable, Sendable {
    case ask, topHit, recent, entities, conversations, beliefs, sources, inbox, settings, actions, askedBefore, suggested

    static func < (lhs: FindGroupID, rhs: FindGroupID) -> Bool { lhs.rawValue < rhs.rawValue }

    var title: String {
        switch self {
        case .ask: ""
        case .topHit: "Top hit"
        case .recent: "Recent"
        case .entities: "Entities"
        case .conversations: "Conversations"
        case .beliefs: "Beliefs"
        case .sources: "Sources & papers"
        case .inbox: "Inbox"
        case .settings: "Settings"
        case .actions: "Actions"
        case .askedBefore: "Asked before"
        case .suggested: "Suggested"
        }
    }

    var glyph: String {
        switch self {
        case .ask: "sparkle.magnifyingglass"
        case .topHit: "star"
        case .recent: "clock"
        case .entities: "point.3.connected.trianglepath.dotted"
        case .conversations: "bubble.left.and.bubble.right"
        case .beliefs: "text.quote"
        case .sources: "photo.stack"
        case .inbox: "tray.full"
        case .settings: "gearshape"
        case .actions: "bolt"
        case .askedBefore: "arrow.uturn.left"
        case .suggested: "lightbulb"
        }
    }
}

/// A row's leading mark: the entity's own logo, a service's real mark
/// (`OriginMark` — installed app icon → bundled PNG → symbol), or a symbol.
enum FindMark: Equatable, Sendable {
    case entity(id: String, name: String, type: EntityType)
    case origin(String)
    case symbol(String)
}

/// A span into an evidence document (G118): what the Reader opens at.
struct ReaderSpan: Equatable, Sendable {
    let doc: String
    let start: Int?
    let end: Int?
    let hash: String?
    let claimId: String?
}

struct ConversationTarget: Equatable, Sendable {
    let span: ReaderSpan
    let conversationId: String?
    let harness: String?
    let origin: String?
    let title: String
}

/// R-SU13 — the palette's verbs, each one the same call the page that owns it makes.
enum PaletteAction: String, Codable, Sendable {
    case consolidate, stopConsolidating, zoomIn, zoomOut, actualSize, lightMode, darkMode
}

/// What a row opens. `ContentView.openFind(_:)` runs the navigating cases;
/// `FindPaletteModel.activate` handles `.ask`, `.askedBefore` and `.settings` itself.
enum FindDestination: Equatable, Sendable {
    case entity(id: String)
    case entityInClusters(id: String)
    case feedItem(mediaEntityId: String)
    case openURL(String)
    case source(id: String)
    case conversations(harness: String?, origin: String?, query: String?)
    case conversation(ConversationTarget)
    case belief(subjectId: String, claimId: String)
    case evidence(ReaderSpan)
    case inbox(id: String)
    case settings(SettingsSection)
    case tab(AppTab)
    case action(PaletteAction)
    case bank(name: String)
    case ask(String)
    case askedBefore(question: String)
}

struct FindRow: Identifiable, Equatable, Sendable {
    let key: FindRowKey
    var id: FindRowKey { key }
    var group: FindGroupID
    let title: String
    /// Scalar ranges to bold in `title` (`ExcerptText.attributed`).
    var titleRanges: [[Int]] = []
    var detail: String? = nil
    /// A passage, drawn in `quoteFont` (conversations).
    var snippet: String? = nil
    var snippetRanges: [[Int]] = []
    var badge: String? = nil
    var mark: FindMark
    var trailing: String? = nil
    /// "You said" / "Agent replied" / "From page" / "Inferred" (design §4.2's labels).
    var speaker: String? = nil
    /// Set only on a superseded belief: "until 3 Sep" (R-SU19).
    var history: String? = nil
    var score: Double = 0
    var tieBreak: Double = 0
    var destination: FindDestination
    var secondary: FindDestination? = nil
}

/// R-SU15 — a count is exact or it is "More…"; never a guessed number (design §3.3).
enum FindCount: Equatable, Sendable {
    case exact(Int)
    case atLeast

    /// Two tiers feeding one group: the local tier counts what it matched, the
    /// server counts lexical documents, and their union is unknown — unless one
    /// side found nothing.
    static func combine(local: FindCount?, server: FindCount) -> FindCount {
        switch (local, server) {
        case (nil, _), (.exact(0)?, _): return server
        case (_, .exact(0)): return local ?? server
        default: return .atLeast
        }
    }
}

struct FindSection: Identifiable, Equatable, Sendable {
    let group: FindGroupID
    let rows: [FindRow]
    /// The row under the group: "Show all N" (`.exact`) or "More…" (`.atLeast`); nil when all is shown.
    let more: FindCount?
    /// "5 of 12" beside the header — only for an exact count.
    let headerCount: String?
    var id: FindGroupID { group }
}

struct FindResults: Equatable, Sendable {
    static let perGroup = 5
    static let empty = FindResults()

    var query = ""
    var ask: FindRow? = nil
    var topHit: FindRow? = nil
    var groups: [FindGroupID: [FindRow]] = [:]
    /// Every local match per group (before the render cap).
    var localCounts: [FindGroupID: Int] = [:]
    /// The latest server pass's count per group — replaced by each pass, never compounded.
    var serverCounts: [FindGroupID: FindCount] = [:]

    var keys: Set<FindRowKey> {
        var out = Set(groups.values.flatMap { $0.map(\.key) })
        if let ask { out.insert(ask.key) }
        if let topHit { out.insert(topHit.key) }
        return out
    }

    var rowCount: Int { groups.values.reduce(0) { $0 + $1.count } + (topHit == nil ? 0 : 1) }
    var groupCount: Int { groups.values.filter { !$0.isEmpty }.count + (topHit == nil ? 0 : 1) }

    func row(for key: FindRowKey) -> FindRow? {
        if ask?.key == key { return ask }
        if topHit?.key == key { return topHit }
        for rows in groups.values { if let found = rows.first(where: { $0.key == key }) { return found } }
        return nil
    }

    func count(for group: FindGroupID) -> FindCount {
        let local = localCounts[group].map { FindCount.exact($0) }
        guard let server = serverCounts[group] else { return local ?? .exact(groups[group]?.count ?? 0) }
        return FindCount.combine(local: local, server: server)
    }

    /// What renders, in the fixed order: the Ask row, the top hit, then each
    /// non-empty group capped at `perGroup` unless expanded.
    func sections(expanded: Set<FindGroupID>) -> [FindSection] {
        var out: [FindSection] = []
        if let ask { out.append(FindSection(group: .ask, rows: [ask], more: nil, headerCount: nil)) }
        if let topHit { out.append(FindSection(group: .topHit, rows: [topHit], more: nil, headerCount: nil)) }
        for group in FindGroupID.allCases where group != .ask && group != .topHit {
            guard let rows = groups[group], !rows.isEmpty else { continue }
            let open = expanded.contains(group)
            let shown = open ? rows : Array(rows.prefix(Self.perGroup))
            let more: FindCount?
            var header: String? = nil
            switch count(for: group) {
            case .exact(let n):
                more = n > shown.count ? .exact(n) : nil
                if n > shown.count { header = "\(UsageFormat.count(shown.count)) of \(UsageFormat.count(n))" }
            case .atLeast:
                // An expanded "More…" group has asked for all the server will give (R-SU14).
                more = open ? nil : .atLeast
            }
            out.append(FindSection(group: group, rows: shown, more: more, headerCount: header))
        }
        return out
    }
}

/// R-SU18 — whether the provenance Reader (Track P's `ProvenanceRouter`,
/// round-3 design §1.4/§4.4) is in this build. `false` until that track
/// merges: a conversation row then opens its source's conversation list
/// filtered to its title, and a belief's "where it was said" secondary is
/// withheld rather than offered and dropped. Flip it in the same commit that
/// routes `.conversation` / `.evidence` through the Reader (`ContentView.openFind`).
enum FindReaderSeam {
    static let isAvailable = false
}
