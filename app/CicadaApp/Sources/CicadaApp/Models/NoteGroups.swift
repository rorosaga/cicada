import Foundation

// G245 (ruling 78, plan 5; owner 2026-11-24: "respect the folder structure, pins, recently modified and all these
// dynamics the app has itself, replicate it in cicada") — how a page of notes is laid out the way Notes lays its own:
// Pinned first, then Notes' own date groups (Today, Yesterday, Previous 7 Days, Previous 30 Days, then each month of this
// year, then each earlier year), each note ordered by when it was last modified, a note's time worded as Notes words it.
// Notion's pages take the same bands, by when they were last edited. Pure; `NoteGroupsTests` holds the sentences.

enum NoteGroups {
    /// One group: Pinned, a date band, a month or a year.
    struct Group: Identifiable, Equatable {
        let id: String
        let title: String
        let items: [ChannelItem]
    }

    /// The instant a note was last modified, as a day on the viewer's own calendar (a late-night note belongs to the
    /// day it was written where the person is), else the day the row carries.
    static func day(_ item: ChannelItem, calendar: Calendar = .autoupdatingCurrent) -> ISODay? {
        if let raw = item.modifiedAt, let instant = ISODate.parse(raw) { return ISODay.today(now: instant, calendar: calendar) }
        return ISODay(item.day)
    }

    /// The band a day falls in, by how far back it is (Notes' own cut-offs).
    enum Band: Hashable {
        case today, yesterday, previous7, previous30, month(year: Int, month: Int), year(Int)
    }

    static func band(_ day: ISODay, today: ISODay) -> Band {
        let back = today - day
        switch back {
        case ...0: return .today
        case 1: return .yesterday
        case 2...7: return .previous7
        case 8...30: return .previous30
        default:
            let c = day.civil
            return c.year == today.civil.year ? .month(year: c.year, month: c.month) : .year(c.year)
        }
    }

    /// The groups of a page, in the order the rows came (pinned first, then newest first). A note with no day goes in one
    /// last, untitled-by-date group, "Earlier". A group with nothing in it is never drawn (DR-81).
    static func groups(_ items: [ChannelItem], today: ISODay, calendar: Calendar = .autoupdatingCurrent,
                       locale: Locale = .autoupdatingCurrent) -> [Group] {
        var order: [String] = []
        var titles: [String: String] = [:]
        var held: [String: [ChannelItem]] = [:]
        func put(_ key: String, _ title: String, _ item: ChannelItem) {
            if titles[key] == nil { order.append(key); titles[key] = title }
            held[key, default: []].append(item)
        }
        for item in items {
            if item.pinned == true { put("pinned", Copy.SourcePage.pinned, item); continue }
            guard let day = day(item, calendar: calendar) else { put("earlier", Copy.NoteGroups.earlier, item); continue }
            switch band(day, today: today) {
            case .today: put("today", Copy.NoteGroups.today, item)
            case .yesterday: put("yesterday", Copy.NoteGroups.yesterday, item)
            case .previous7: put("previous7", Copy.NoteGroups.previous7, item)
            case .previous30: put("previous30", Copy.NoteGroups.previous30, item)
            case .month(let year, let month):
                put("m\(year)-\(month)", RelativeDay.fullMonth(day, locale: locale), item)
            case .year(let year):
                put("y\(year)", String(year), item)
            }
        }
        return order.map { Group(id: $0, title: titles[$0] ?? "", items: held[$0] ?? []) }
    }

    /// A note's time on its row, as Notes words it: the time of day for today and yesterday (the group says which), the weekday inside the last
    /// week, else the date. The full date and time is its help. Nil with nothing to say.
    static func time(_ item: ChannelItem, today: ISODay, calendar: Calendar = .autoupdatingCurrent,
                     locale: Locale = .autoupdatingCurrent) -> (text: String, help: String)? {
        guard let day = day(item, calendar: calendar) else { return nil }
        let instant = item.modifiedAt.flatMap(ISODate.parse)
        let full = RelativeDay.full(day, locale: locale)
        let clock = instant.map { time(of: $0, calendar: calendar, locale: locale) }
        let help = clock.map { "\(full) · \($0)" } ?? full
        switch today - day {
        case ...0:
            return (clock ?? Copy.NoteGroups.today, help)
        case 1:
            // The group already says Yesterday: the row says when in the day (the date when no instant came).
            return (clock ?? Copy.NoteGroups.yesterday, help)
        case 2...6:
            return (RelativeDay.weekday(day, locale: locale), help)
        default:
            return (RelativeDay.absolute(day, today: today, locale: locale), help)
        }
    }

    private static func time(of instant: Date, calendar: Calendar, locale: Locale) -> String {
        let f = DateFormatter()
        f.locale = locale
        f.calendar = calendar
        f.timeZone = calendar.timeZone
        f.timeStyle = .short
        f.dateStyle = .none
        return f.string(from: instant)
    }
}
