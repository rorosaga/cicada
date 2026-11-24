import Foundation

// G245 (ruling 78 (c), owner 2026-11-24: "who i have connected with and in chronological order which to me is super
// important") — the wire shape and the words of LinkedIn's Connections stream: `GET /sources/linkedin-connections/list`.
// The one route that names a connection, so the app holds what it brings in MEMORY ONLY: no cache on disk, no Store
// domain, nothing in a bank. Decoded leniently like every wire shape here (a field this build does not know, or a
// malformed one, drops that field alone, never the row). Pure and `Sendable`; nothing here draws.

/// One connection: a name, its headline, the profile link, the day it was made and how exactly that is known, and the
/// one person page it is when there is exactly one.
struct LinkedInConnection: Decodable, Hashable, Identifiable, Sendable {
    /// How exactly the day is known: a page that said "3 weeks ago" is a day counted back, so it is only a week's.
    enum Precision: String, Sendable { case day, week, month }

    let id: String
    let name: String
    var headline: String = ""
    var url: String?
    var day: String?
    var precision: Precision = .day
    var page: String?

    enum CodingKeys: String, CodingKey { case id, name, headline, url, day, precision, page }

    init(id: String, name: String, headline: String = "", url: String? = nil, day: String? = nil,
         precision: Precision = .day, page: String? = nil) {
        self.id = id; self.name = name; self.headline = headline; self.url = url; self.day = day
        self.precision = precision; self.page = page
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        headline = (try? c.decodeIfPresent(String.self, forKey: .headline)) ?? ""
        url = try? c.decodeIfPresent(String.self, forKey: .url)
        day = try? c.decodeIfPresent(String.self, forKey: .day)
        precision = (try? c.decodeIfPresent(String.self, forKey: .precision)).flatMap(Precision.init) ?? .day
        page = try? c.decodeIfPresent(String.self, forKey: .page)
    }
}

/// One page of the list, newest first. `total` is the matches' count under a search; `kept` is how many the kept
/// directory holds whatever the search says (what "Forget kept connections" would forget).
struct LinkedInConnectionsPage: Decodable, Equatable, Sendable {
    var rows: [LinkedInConnection] = []
    var total: Int = 0
    var offset: Int = 0
    var next: Int?
    var kept: Int = 0

    enum CodingKeys: String, CodingKey { case rows, total, offset, next, kept }

    init(rows: [LinkedInConnection] = [], total: Int = 0, offset: Int = 0, next: Int? = nil, kept: Int = 0) {
        self.rows = rows; self.total = total; self.offset = offset; self.next = next; self.kept = kept
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        rows = (try? c.decodeIfPresent([LinkedInConnection].self, forKey: .rows)) ?? []
        total = (try? c.decodeIfPresent(Int.self, forKey: .total)) ?? rows.count
        offset = (try? c.decodeIfPresent(Int.self, forKey: .offset)) ?? 0
        next = try? c.decodeIfPresent(Int.self, forKey: .next)
        kept = (try? c.decodeIfPresent(Int.self, forKey: .kept)) ?? total
    }
}

/// The connections' months and the words of a row, pure (`LinkedInConnectionsTests`).
enum LinkedInConnectionsText {
    /// One month of connections: its title ("November 2026"), how many of them there are when that is known, and the rows.
    struct Month: Identifiable, Equatable {
        let id: String
        let title: String
        /// Nil while the month may continue on a page not read yet (the last month of a partly read list).
        let count: Int?
        let rows: [LinkedInConnection]

        var heading: String { count.map { "\(title) · \(UsageFormat.count($0))" } ?? title }
    }

    /// The rows grouped by the month they were made, in the order sent (newest first). A connection with no day goes in one
    /// last group, "No date". A month's count is said only when the whole month is in hand: every month but the last one,
    /// or all of them once the list is read to its end (`complete`).
    static func months(_ rows: [LinkedInConnection], complete: Bool, locale: Locale = .autoupdatingCurrent) -> [Month] {
        var groups: [(id: String, title: String, rows: [LinkedInConnection])] = []
        for row in rows {
            let day = ISODay(row.day)
            let id = day.map { "\($0.civil.year)-\($0.civil.month)" } ?? "undated"
            if let index = groups.firstIndex(where: { $0.id == id }) {
                groups[index].rows.append(row)
            } else {
                groups.append((id, day.map { RelativeDay.fullMonthYear($0, locale: locale) } ?? Copy.Streams.connectionsNoDate, [row]))
            }
        }
        return groups.enumerated().map { index, group in
            let last = index == groups.count - 1
            return Month(id: group.id, title: group.title, count: (complete || !last) ? group.rows.count : nil, rows: group.rows)
        }
    }

    /// The day on a row's trailing edge: "Nov 14"; a week's precision is "around Nov 12", a month's "around Nov". The
    /// full date (or the month) is the row's help. Nil with no day.
    static func day(_ row: LinkedInConnection, today: ISODay, locale: Locale = .autoupdatingCurrent)
        -> (text: String, help: String)? {
        guard let day = ISODay(row.day) else { return nil }
        switch row.precision {
        case .day:
            return (RelativeDay.absolute(day, today: today, locale: locale), RelativeDay.full(day, locale: locale))
        case .week:
            let text = RelativeDay.absolute(day, today: today, locale: locale)
            return (Copy.Streams.connectionsAround(text), Copy.Streams.connectionsWeekHelp(RelativeDay.full(day, locale: locale)))
        case .month:
            let text = day.civil.year == today.civil.year ? RelativeDay.month(day, locale: locale)
                                                          : RelativeDay.monthYear(day, locale: locale)
            return (Copy.Streams.connectionsAround(text), Copy.Streams.connectionsMonthHelp(RelativeDay.fullMonthYear(day, locale: locale)))
        }
    }

    /// The connection's profile link, when it is an http(s) address with a host.
    static func profile(_ row: LinkedInConnection) -> URL? {
        guard let raw = row.url, let url = URL(string: raw), let scheme = url.scheme?.lowercased(),
              scheme == "https" || scheme == "http", url.host?.isEmpty == false else { return nil }
        return url
    }

    /// What the page says when there is nothing to list, by what the stream is doing. `searching` is a find with no match.
    enum Empty: Equatable {
        case off, waiting, noMatch
    }

    static func empty(streamOn: Bool, searching: Bool) -> Empty {
        searching ? .noMatch : (streamOn ? .waiting : .off)
    }
}
