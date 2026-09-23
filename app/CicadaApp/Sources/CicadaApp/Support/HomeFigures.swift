import Foundation

struct HomeOriginChip: Equatable {
    let sourceId: String
    let mark: String
    let label: String
    let count: Int
}

struct HomeToday: Equatable {
    /// nil until `sourcesOverview` has loaded — shown as "—", never a guessed 0 (R-A14).
    let captured: Int?
    let origins: [HomeOriginChip]
}

enum HomeLastRead: Equatable {
    case loading, never
    case entry(SleepHistoryEntry)
    /// A read happened, but its commit is past the history page (the status's
    /// `lastSleepAt`, when it has one, dates it).
    case earlier(String?)
}

struct HomeNeedsYou {
    let shown: [InboxItem]
    let total: Int
}

struct HomeChip: Equatable {
    let id: String
    let name: String
}

struct HomeChips: Equatable {
    let shown: [HomeChip]
    let more: Int
}

/// Track I part b T9 (design §6.3, R-IB9) — Home's numbers, each shown once and
/// each a link to the page that owns it. Pure over what the Store already holds,
/// so "every number once" and "never a guess" are table-tested, not eyeballed.
enum HomeFigures {
    static let originLimit = 3
    static let needsYouLimit = 3
    static let chipLimit = 3

    /// Today's UTC bucket (the key `source_overview` writes) summed over every
    /// row; the three busiest origins become marks. Noun: captured (Sources v2).
    static func today(_ rows: [SourceOverview]?, today: Date) -> HomeToday {
        guard let rows else { return HomeToday(captured: nil, origins: []) }
        let counted = rows.map { (row: $0, n: sparklinePoints(activity: $0.activity, days: 1, today: today).last ?? 0) }
        let top = counted.filter { $0.n > 0 }
            .sorted { $0.n != $1.n ? $0.n > $1.n
                                   : $0.row.label.localizedCaseInsensitiveCompare($1.row.label) == .orderedAscending }
            .prefix(originLimit)
            .map { HomeOriginChip(sourceId: $0.row.id, mark: $0.row.mark, label: $0.row.label, count: $0.n) }
        return HomeToday(captured: counted.reduce(0) { $0 + $1.n }, origins: Array(top))
    }

    static func needsYou(_ inbox: [InboxItem]) -> HomeNeedsYou {
        HomeNeedsYou(shown: Array(inbox.prefix(needsYouLimit)), total: inbox.count)
    }

    /// A decay split or an inbox commit is not a read (G85): only `kind == "sleep"`.
    ///
    /// No sleep row on the page is not "never" (R-A14, never a guess): `GET
    /// /sleep/history` returns the newest 15 commits, inbox resolutions included,
    /// so fifteen answers since the last read push it off the page — and a decay
    /// commit only exists because a Sleep ran. "Nothing read yet" needs the
    /// status to say no read ever ran; a read that did run but is off the page
    /// is `.earlier` (I-b final review, finding 5). `hasRunBefore` nil = unknown.
    static func lastRead(_ history: [SleepHistoryEntry], loaded: Bool,
                         hasRunBefore: Bool?, lastSleepAt: String?) -> HomeLastRead {
        if let e = history.first(where: { $0.kind == "sleep" }) { return .entry(e) }
        guard loaded else { return .loading }
        if hasRunBefore == true || lastSleepAt != nil || history.contains(where: { $0.kind == "decay" }) {
            return .earlier(lastSleepAt)
        }
        return hasRunBefore == false ? .never : .loading
    }

    static func lastReadLine(_ e: SleepHistoryEntry, locale: Locale = .autoupdatingCurrent) -> String {
        var parts = [day(e.date, locale: locale) ?? String(e.date.prefix(10))]
        if e.entitiesCreated > 0 { parts.append("\(UsageFormat.count(e.entitiesCreated, locale: locale)) new") }
        if e.entitiesUpdated > 0 { parts.append("\(UsageFormat.count(e.entitiesUpdated, locale: locale)) updated") }
        if parts.count == 1 { parts.append(Copy.homeNothingChanged) }
        return parts.joined(separator: " · ")
    }

    /// The commit's `entities/<id>.md` files that still name a node — a page
    /// deleted since the read is never a chip, and a repeat counts once.
    static func chips(_ e: SleepHistoryEntry, nodes: [GraphNode]) -> HomeChips {
        var names: [String: String] = [:]
        for node in nodes where names[node.id] == nil { names[node.id] = node.name }
        var seen = Set<String>()
        var known: [HomeChip] = []
        for path in e.filesChanged where path.hasPrefix("entities/") && path.hasSuffix(".md") {
            let id = String(path.dropFirst("entities/".count).dropLast(3))
            guard let name = names[id], seen.insert(id).inserted else { continue }
            known.append(HomeChip(id: id, name: name))
        }
        return HomeChips(shown: Array(known.prefix(chipLimit)), more: max(0, known.count - chipLimit))
    }

    /// The day part of the history row's `date` (a `yyyy-MM-dd…` string), read
    /// in UTC and shown as the viewer's short month-day.
    static func day(_ raw: String, locale: Locale) -> String? {
        let parse = DateFormatter()
        parse.locale = Locale(identifier: "en_US_POSIX")
        parse.timeZone = TimeZone(identifier: "UTC")
        parse.dateFormat = "yyyy-MM-dd"
        guard let date = parse.date(from: String(raw.prefix(10))) else { return nil }
        let out = DateFormatter()
        out.locale = locale
        out.timeZone = TimeZone(identifier: "UTC")
        out.setLocalizedDateFormatFromTemplate("MMMd")
        return out.string(from: date)
    }
}
