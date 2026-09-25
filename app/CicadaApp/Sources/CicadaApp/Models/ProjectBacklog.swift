import Foundation

/// G150 — a project's backlog on the wire (`api/routers/backlog.py`). Decoded leniently like every Projects type
/// (R-PP2's reason): a server that adds or drops a field never blanks the section. Not a Store domain —
/// `BacklogCache` fetches it on demand (R-B18). Every property is `var` so the cache can paint a status move before
/// the server answers (R-B22).
enum BacklogStatus: String, CaseIterable, Hashable, Sendable {
    case open, doing, done, dropped
}

struct BacklogLink: Decodable, Equatable, Hashable, Sendable {
    var kind: String
    var ref: String
}

/// One signed note (R-B4). `by` is the author id (`user`, a harness label, `cicada`), `byLabel` the heading's words.
/// `authorModel`/`authorEffort` are the turn's model and effort for a harness note once round 4's join fills them
/// (R-B6); nil until then — never guessed here.
struct BacklogNote: Equatable, Sendable {
    var day: String
    var text: String
    var by: String
    var byKind: String
    var byProvider: String?
    var byLabel: String
    var at: String?
    var session: String?
    var authorModel: String?
    var authorEffort: String?
}

extension BacklogNote: Decodable {
    enum CodingKeys: String, CodingKey {
        case day, text, by, byKind, byProvider, byLabel, at, session, authorModel, authorEffort
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        day = try c.decodeIfPresent(String.self, forKey: .day) ?? ""
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        by = try c.decodeIfPresent(String.self, forKey: .by) ?? "agent"
        byKind = try c.decodeIfPresent(String.self, forKey: .byKind) ?? "harness"
        byProvider = try c.decodeIfPresent(String.self, forKey: .byProvider)
        byLabel = try c.decodeIfPresent(String.self, forKey: .byLabel) ?? ""
        at = try c.decodeIfPresent(String.self, forKey: .at)
        session = try c.decodeIfPresent(String.self, forKey: .session)
        authorModel = try c.decodeIfPresent(String.self, forKey: .authorModel)
        authorEffort = try c.decodeIfPresent(String.self, forKey: .authorEffort)
    }
}

struct BacklogItemSummary: Equatable, Identifiable, Sendable {
    var id: String
    var project: String
    var title: String
    var status: String
    var triage: String?
    var paid: Bool
    var created: String
    var updated: String
    var addedBy: String
    var addedByKind: String
    var addedByLabel: String
    var noteCount: Int
    var lastNoteDay: String?
    var lastNoteBy: String?
    var order: Int?

    /// An unknown state reads as open — the item is still on the list, never dropped from view by a newer server.
    var backlogStatus: BacklogStatus { BacklogStatus(rawValue: status) ?? .open }
}

extension BacklogItemSummary: Decodable {
    enum CodingKeys: String, CodingKey {
        case id, project, title, status, triage, paid, created, updated, addedBy, addedByKind, addedByLabel
        case noteCount, lastNoteDay, lastNoteBy, order
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? id
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "open"
        triage = try c.decodeIfPresent(String.self, forKey: .triage)
        paid = try c.decodeIfPresent(Bool.self, forKey: .paid) ?? false
        created = try c.decodeIfPresent(String.self, forKey: .created) ?? ""
        updated = try c.decodeIfPresent(String.self, forKey: .updated) ?? created
        addedBy = try c.decodeIfPresent(String.self, forKey: .addedBy) ?? "user"
        addedByKind = try c.decodeIfPresent(String.self, forKey: .addedByKind) ?? "user"
        addedByLabel = try c.decodeIfPresent(String.self, forKey: .addedByLabel) ?? ""
        noteCount = try c.decodeIfPresent(Int.self, forKey: .noteCount) ?? 0
        lastNoteDay = try c.decodeIfPresent(String.self, forKey: .lastNoteDay)
        lastNoteBy = try c.decodeIfPresent(String.self, forKey: .lastNoteBy)
        order = try c.decodeIfPresent(Int.self, forKey: .order)
    }
}

/// An item in full: the summary's fields plus its reasoning, its notes, its links and its file (in `.help` only).
struct BacklogItem: Equatable, Identifiable, Sendable {
    var summary: BacklogItemSummary
    var descriptionText: String
    var notes: [BacklogNote]
    var links: [BacklogLink]
    var session: String?
    var path: String

    var id: String { summary.id }
}

extension BacklogItem: Decodable {
    enum CodingKeys: String, CodingKey {
        case descriptionText = "description"
        case notes, links, session, path
    }

    init(from decoder: Decoder) throws {
        summary = try BacklogItemSummary(from: decoder)
        let c = try decoder.container(keyedBy: CodingKeys.self)
        descriptionText = try c.decodeIfPresent(String.self, forKey: .descriptionText) ?? ""
        notes = try c.decodeIfPresent([BacklogNote].self, forKey: .notes) ?? []
        links = try c.decodeIfPresent([BacklogLink].self, forKey: .links) ?? []
        session = try c.decodeIfPresent(String.self, forKey: .session)
        path = try c.decodeIfPresent(String.self, forKey: .path) ?? ""
    }
}

struct BacklogList: Equatable, Sendable {
    var project: String
    var projectName: String
    var prefix: String
    var counts: [String: Int]
    var items: [BacklogItemSummary]
    var tzName: String

    func count(_ status: BacklogStatus) -> Int { counts[status.rawValue] ?? 0 }
}

extension BacklogList: Decodable {
    enum CodingKeys: String, CodingKey { case project, projectName, prefix, counts, items, tzName }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
        projectName = try c.decodeIfPresent(String.self, forKey: .projectName) ?? project
        prefix = try c.decodeIfPresent(String.self, forKey: .prefix) ?? ""
        counts = (try? c.decodeIfPresent([String: Int].self, forKey: .counts)) ?? [:]
        items = try c.decodeIfPresent([BacklogItemSummary].self, forKey: .items) ?? []
        tzName = try c.decodeIfPresent(String.self, forKey: .tzName) ?? "UTC"
    }
}

/// G150 — every decision the Backlog section and the item card make, pure (the `ProjectsModel` pattern): `today` is
/// an argument, so a test pins it and midnight re-derives every word with no network (DR-58).
enum BacklogModel {
    /// R-B19 (DR-45) — Open · Doing · Done, and All as the tabs' nil: a dropped item shows only under All.
    static func tabs(_ list: BacklogList) -> [TextTab<BacklogStatus>] {
        [TextTab(id: .open, label: Copy.Projects.Backlog.open, count: list.count(.open)),
         TextTab(id: .doing, label: Copy.Projects.Backlog.doing, count: list.count(.doing)),
         TextTab(id: .done, label: Copy.Projects.Backlog.done, count: list.count(.done)),
         TextTab(id: nil, label: Copy.Projects.Backlog.all, count: list.counts.values.reduce(0, +))]
    }

    /// The server's order (R-B19), filtered by the tab; nil is All.
    static func rows(_ list: BacklogList, tab: BacklogStatus?) -> [BacklogItemSummary] {
        list.items.filter { tab == nil || $0.backlogStatus == tab }
    }

    /// The first of Open, Doing, Done that holds anything — a backlog that is all done opens on Done, never on an
    /// empty Open.
    static func defaultTab(_ list: BacklogList) -> BacklogStatus? {
        [BacklogStatus.open, .doing, .done].first { list.count($0) > 0 } ?? .open
    }

    /// What a folded section says beside its label (R-B19): items open or doing.
    static func openCount(_ list: BacklogList) -> Int { list.count(.open) + list.count(.doing) }

    static func emptyLine(tab: BacklogStatus?) -> String {
        switch tab {
        case .open?: Copy.Projects.Backlog.emptyOpen
        case .doing?: Copy.Projects.Backlog.emptyDoing
        case .done?: Copy.Projects.Backlog.emptyDone
        case .dropped?: Copy.Projects.Backlog.emptyDropped
        case nil: Copy.Projects.Backlog.emptyAll
        }
    }

    /// DR-58 — the age of the last note, else of the item, computed at read from an absolute day; the full date is
    /// the `.help`.
    static func age(_ row: BacklogItemSummary, today: ISODay,
                    locale: Locale = .autoupdatingCurrent) -> (text: String, help: String) {
        guard let day = ISODay(row.lastNoteDay ?? row.created) else { return ("", "") }
        return (RelativeDay.compactAge(day, today: today), RelativeDay.full(day, locale: locale))
    }

    static func triageLabel(_ triage: String?) -> String? {
        switch triage {
        case "apply": Copy.Projects.Backlog.apply
        case "research": Copy.Projects.Backlog.research
        case "decide": Copy.Projects.Backlog.decide
        default: nil
        }
    }

    static func statusLabel(_ status: BacklogStatus) -> String {
        switch status {
        case .open: Copy.Projects.Backlog.open
        case .doing: Copy.Projects.Backlog.doing
        case .done: Copy.Projects.Backlog.done
        case .dropped: Copy.Projects.Backlog.dropped
        }
    }

    /// R-B20 — the moves an item can make from where it stands.
    static func moves(from status: BacklogStatus) -> [BacklogStatus] {
        switch status {
        case .open: [.doing, .done, .dropped]
        case .doing: [.done, .dropped]
        case .done, .dropped: [.open]
        }
    }

    static func moveLabel(_ to: BacklogStatus) -> String {
        switch to {
        case .open: Copy.Projects.Backlog.reopen
        case .doing: Copy.Projects.Backlog.start
        case .done: Copy.Projects.Backlog.markDone
        case .dropped: Copy.Projects.Backlog.drop
        }
    }

    static func moveHelp(_ to: BacklogStatus) -> String {
        switch to {
        case .open: Copy.Projects.Backlog.reopenHelp
        case .doing: Copy.Projects.Backlog.startHelp
        case .done: Copy.Projects.Backlog.markDoneHelp
        case .dropped: Copy.Projects.Backlog.dropHelp
        }
    }

    /// "claude-opus-5-5" → "Opus 5.5"; any other family reads as its own id (never a guess at a product name).
    static func modelWords(_ id: String) -> String {
        let parts = id.lowercased().split(separator: "-").map(String.init)
        guard parts.first == "claude", parts.count >= 2 else { return id }
        let family = parts[1].prefix(1).uppercased() + parts[1].dropFirst()
        let version = parts.dropFirst(2).filter { $0.allSatisfy(\.isNumber) }.joined(separator: ".")
        return version.isEmpty ? family : "\(family) \(version)"
    }

    /// R-B6 — who wrote a note, in words: "You", "Claude Code", and — when the wire carries the turn's model and
    /// effort — "Claude Code · Opus 5.5 · high effort".
    static func authorLine(_ note: BacklogNote) -> String {
        var bits = [note.byLabel.isEmpty ? ContributorIdentity.displayName(author: note.by, kind: note.byKind)
                                         : note.byLabel]
        if let model = note.authorModel, !model.isEmpty { bits.append(modelWords(model)) }
        if let effort = note.authorEffort, !effort.isEmpty { bits.append(Copy.Projects.Backlog.effort(effort)) }
        return bits.joined(separator: " · ")
    }

    /// The item card's blurb: who added it and on which day (DR-58's absolute form; the full date is `.help`).
    static func addedLine(_ row: BacklogItemSummary, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let who = row.addedByLabel.isEmpty ? ContributorIdentity.displayName(author: row.addedBy, kind: row.addedByKind)
                                           : row.addedByLabel
        guard let day = ISODay(row.created) else { return Copy.Projects.Backlog.addedBy(who) }
        return Copy.Projects.Backlog.addedBy(who, day: RelativeDay.absolute(day, today: today, locale: locale))
    }

    /// VoiceOver hears the row the way the eye reads it: the id, the task, its state, its triage and its age.
    static func accessibilityLabel(_ row: BacklogItemSummary, today: ISODay,
                                   locale: Locale = .autoupdatingCurrent) -> String {
        [row.id, row.title, statusLabel(row.backlogStatus), triageLabel(row.triage),
         age(row, today: today, locale: locale).help].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", ")
    }
}
