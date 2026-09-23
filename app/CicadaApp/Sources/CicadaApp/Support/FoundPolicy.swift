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
    /// Singular; `startSummary` pluralises with `+ "s"`.
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

    /// Start's text twin: exactly what Start will do, counted.
    static func startSummary(_ ticked: [FoundItem], locale: Locale = .autoupdatingCurrent) -> String {
        func counted(_ n: Int, _ noun: String) -> String { "\(UsageFormat.count(n, locale: locale)) \(n == 1 ? noun : noun + "s")" }
        let apps = ticked.filter { $0.group == .agents }.count
        var brings: [String] = []
        let browsers = ticked.filter { $0.group == .browsers }
        if !browsers.isEmpty {
            let counts = browsers.compactMap(\.count)
            brings.append(counts.count == browsers.count ? counted(counts.reduce(0, +), "bookmark") : "your bookmarks")
        }
        for item in ticked where item.group == .chatHistory {
            if let n = item.count, let noun = item.countNoun { brings.append(counted(n, noun)) }
        }
        if ticked.contains(where: { $0.group == .notesAndVoice }) { brings.append("your notes") }
        var clauses: [String] = []
        if apps > 0 { clauses.append("Connects \(counted(apps, "app"))") }
        if !brings.isEmpty {
            let list = brings.count == 1 ? brings[0]
                : brings.dropLast().joined(separator: ", ") + " and " + brings[brings.count - 1]
            clauses.append((clauses.isEmpty ? "Brings in " : "brings in ") + list)
        }
        return clauses.isEmpty ? Copy.foundStartNothing : clauses.joined(separator: " and ") + "."
    }
}
