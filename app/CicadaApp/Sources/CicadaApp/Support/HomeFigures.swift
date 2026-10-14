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
    /// A read happened, but its commit is past the history page — or the
    /// history could not be read and the status says a read ran (the status's
    /// `lastSleepAt`, when it has one, dates it).
    case earlier(String?)
    /// The history could not be read and nothing else says whether a read ever ran.
    case failed
}

struct HomeNeedsYou {
    let shown: [InboxItem]
    let total: Int
}

struct HomeChip: Equatable {
    let id: String
    let name: String
    /// The page's type, for the `Tag`'s dot (DR-44, R-HS6).
    let type: EntityType
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
    ///
    /// A failed fetch is never "Loading…" forever (owner 2026-10-14): the
    /// status's own last read dates it when the status has one, the status's
    /// "never ran" is still "Nothing read yet", and otherwise it says so.
    static func lastRead(_ history: [SleepHistoryEntry], loaded: Bool, failed: Bool = false,
                         hasRunBefore: Bool?, lastSleepAt: String?) -> HomeLastRead {
        if let e = history.first(where: { $0.kind == "sleep" }) { return .entry(e) }
        let ran = hasRunBefore == true || lastSleepAt != nil || history.contains(where: { $0.kind == "decay" })
        guard loaded else {
            guard failed else { return .loading }
            if ran { return .earlier(lastSleepAt) }
            return hasRunBefore == false ? .never : .failed
        }
        if ran { return .earlier(lastSleepAt) }
        return hasRunBefore == false ? .never : .loading
    }

    /// "Today 07:27 · 33 updated" — when the read was, then only the counts that happened.
    static func lastReadLine(_ e: SleepHistoryEntry, now: Date = Date(), locale: Locale = .autoupdatingCurrent,
                             calendar: Calendar = .autoupdatingCurrent) -> String {
        var parts = [when(e.date, now: now, locale: locale, calendar: calendar) ?? String(e.date.prefix(10))]
        if e.entitiesCreated > 0 { parts.append("\(UsageFormat.count(e.entitiesCreated, locale: locale)) new") }
        if e.entitiesUpdated > 0 { parts.append("\(UsageFormat.count(e.entitiesUpdated, locale: locale)) updated") }
        if parts.count == 1 { parts.append(Copy.homeNothingChanged) }
        return parts.joined(separator: " · ")
    }

    /// The commit's `entities/<id>.md` files that still name a node — a page
    /// deleted since the read is never a chip, and a repeat counts once.
    static func chips(_ e: SleepHistoryEntry, nodes: [GraphNode]) -> HomeChips {
        var byId: [String: GraphNode] = [:]
        for node in nodes where byId[node.id] == nil { byId[node.id] = node }
        var seen = Set<String>()
        var known: [HomeChip] = []
        for path in e.filesChanged where path.hasPrefix("entities/") && path.hasSuffix(".md") {
            let id = String(path.dropFirst("entities/".count).dropLast(3))
            guard let node = byId[id], seen.insert(id).inserted else { continue }
            known.append(HomeChip(id: id, name: node.name, type: node.type))
        }
        return HomeChips(shown: Array(known.prefix(chipLimit)), more: max(0, known.count - chipLimit))
    }

    /// When a read was, in the viewer's own words and clock: "Today 07:27", "Yesterday 23:10", "Oct 3 07:27".
    /// `raw` is the history row's `date` or the status's `lastSleepAt` — git's ISO-8601 instant with its offset
    /// (`--date=iso-strict`, R-A11), shown in the viewer's zone. A bare `yyyy-MM-dd` (an older backend) is the day
    /// alone; anything else is nil. The day word is `RelativeDay`'s, the one place it is spelled.
    static func when(_ raw: String, now: Date = Date(), locale: Locale = .autoupdatingCurrent,
                     calendar: Calendar = .autoupdatingCurrent) -> String? {
        let today = ISODay.today(now: now, calendar: calendar)
        guard let instant = instant(raw) else {
            guard raw.count == 10, let day = ISODay(raw) else { return nil }
            return RelativeDay.phrase(day, today: today, locale: locale)
        }
        let c = calendar.dateComponents([.year, .month, .day], from: instant)
        let day = ISODay(year: c.year ?? 1970, month: c.month ?? 1, day: c.day ?? 1)
        let time = DateFormatter()
        time.locale = locale
        time.calendar = calendar
        time.timeZone = calendar.timeZone
        time.setLocalizedDateFormatFromTemplate("jmm")
        return "\(RelativeDay.phrase(day, today: today, locale: locale)) \(time.string(from: instant))"
    }

    private static func instant(_ raw: String) -> Date? {
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        if let d = plain.date(from: raw) { return d }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return fractional.date(from: raw)
    }
}
