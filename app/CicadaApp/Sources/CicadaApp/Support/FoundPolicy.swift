import Foundation

enum FoundItemID: Hashable {
    case agent(String)      // "claude-code", "codex", "cursor", "claude-desktop"
    case browser(String)    // a BrowserWatch channel id
    case app(String)        // notes & voice (Tracks F/N, part b)
    case dropped(String)    // a file dropped on the Welcome
}

enum FoundGroup: Int, CaseIterable, Comparable {
    case agents, browsers, notesAndVoice, chatHistory
    static func < (a: FoundGroup, b: FoundGroup) -> Bool { a.rawValue < b.rawValue }
}

struct FoundItem: Equatable, Identifiable {
    enum Content: Equatable { case ownIntentionalAct, ownArchive, includesOthers }
    enum Readiness: Equatable { case ready, checking, needsPermission, needsGrant, alreadyOn, failed(String) }

    let id: FoundItemID
    let group: FoundGroup
    let title: String
    let isPresent: Bool
    let content: Content
    let readiness: Readiness
    let opensAnotherApp: Bool
    var count: Int? = nil
    /// Singular — what `count` counts (the one-scroll Welcome's retired start line pluralised it, R-OB6).
    var countNoun: String? = nil
}

/// Track I T6 (design §4.1.4, D-2) — the visible checklist IS the consent. A row
/// is pre-ticked only when it is the person's own intentional act (their agent
/// sessions from now on, bookmarks they saved), needs no new macOS permission and
/// opens no other app; everything else is shown unticked, never hidden.
enum FoundPolicy {
    static func defaultOn(_ i: FoundItem) -> Bool {
        i.isPresent && i.content == .ownIntentionalAct && i.readiness == .ready && !i.opensAnotherApp
    }

    static func order(_ items: [FoundItem]) -> [FoundItem] {
        items.filter(\.isPresent).sorted {
            if $0.group != $1.group { return $0.group < $1.group }
            let (a, b) = (defaultOn($0), defaultOn($1))
            if a != b { return a }
            return $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending
        }
    }
}
