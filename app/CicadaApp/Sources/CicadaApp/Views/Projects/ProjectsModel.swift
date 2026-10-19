import SwiftUI

/// §5.3 / DR-36 — the detail column's widths, in units: the band runs to 880 (the approved mock), text stays ≤ 760.
enum ProjectLayout {
    static let detailMaxWidth: CGFloat = 880
    static let textMaxWidth: CGFloat = 760
}

/// §3.8 / R-PP9 — the band's green geometry (the list's mini bar retired with Projects v2, 2026-10-19). From the
/// project's first moment (or `created`, or an earlier target — whichever is first) to its end: with a plan, the latest target when it lies after today, else a week past today; with no plan, a
/// week past today and an open end — never a grey remainder that reads "almost done". The fill runs to today.
struct ProgressSpan: Equatable {
    static let tailDays = 7

    let start: ISODay
    let end: ISODay
    let today: ISODay
    let planned: Bool

    var days: Int { max(1, end - start) }
    var fill: Double { fraction(today) }

    func fraction(_ day: ISODay) -> Double { min(max(Double(day - start) / Double(days), 0), 1) }

    static func of(created: ISODay?, days: [ISODay], targets: [ISODay], planned: Bool, today: ISODay) -> ProgressSpan {
        let first = ([created].compactMap { $0 } + days + targets).min() ?? today
        let tail = today.adding(tailDays)
        let end: ISODay
        if planned, let last = targets.max(), last > today { end = last } else { end = tail }
        return ProgressSpan(start: min(first, today), end: end, today: today, planned: planned)
    }
}

/// Projects v2 (owner 2026-10-19, DESIGN_RULES §9) — the page's two tabs: what the person is doing now, and what they
/// did. Current holds the projects in motion and, folded under them, the ones fading; Past holds the rest, paged.
enum ProjectsTab: Hashable, Sendable { case current, past }

/// Where a project's derived section (`ProjectState`, the agent's own rule) puts it on the page: in motion → Current,
/// quiet → Fading (under Current), resting — a decaying or archived page, or nothing heard for 90 days — → Past.
enum ProjectsGroup: Hashable, Sendable {
    case current, fading, past

    init(_ section: ProjectState.Section) {
        switch section {
        case .inMotion: self = .current
        case .quiet: self = .fading
        case .resting: self = .past
        }
    }

    var tab: ProjectsTab { self == .past ? .past : .current }
}

/// One list row: the project, its derived state on the viewer's today, its depth under a shown parent, and — when it
/// has sub-projects in its group — how many and whether they are unfolded.
struct ProjectLine: Identifiable, Equatable {
    let row: ProjectRow
    let state: ProjectState.Output
    let depth: Int
    var children: Int = 0
    var expanded = false
    var id: String { row.id }
    var group: ProjectsGroup { ProjectsGroup(state.section) }
}

/// What the list column draws, top to bottom: rows, the Fading disclosure, Past's year labels and its "Show more".
enum ProjectsEntry: Identifiable, Equatable {
    case line(ProjectLine)
    case fading(count: Int, open: Bool)
    case year(String)
    case more(Int)

    var id: String {
        switch self {
        case .line(let line): line.id
        case .fading: "projects.fading"
        case .year(let label): "projects.year.\(label)"
        case .more: "projects.more"
        }
    }

    var line: ProjectLine? { if case .line(let line) = self { line } else { nil } }
}

/// The viewer's folds on the list: which parents show their parts, whether Fading is open, how much of Past is drawn.
struct ProjectsListOptions: Equatable {
    var expanded: Set<String> = []
    var fadingOpen = false
    var pastLimit = ProjectsModel.pageSize
}

/// G141 PJ-5, v2 — what the Projects list shows, pure (the `ClustersModel` pattern). Every word that depends on today
/// is computed here from the absolute days the server sent (R-PJ6, DR-58); `today` is an argument, so a test pins it
/// and midnight re-derives the list with no network.
enum ProjectsModel {
    /// Past draws this many rows at a time — never 600 at once.
    static let pageSize = 50

    static func state(_ row: ProjectRow, today: ISODay) -> ProjectState.Output {
        ProjectState.state(ProjectState.Input(row), today: today)
    }

    static func group(_ row: ProjectRow, today: ISODay) -> ProjectsGroup { ProjectsGroup(state(row, today: today).section) }

    /// DR-46 — find matches a project's name and one-liner, folded as the palette folds (one ranker, `QuickMatch`).
    static func matches(_ row: ProjectRow, query: String) -> Bool {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return true }
        return QuickMatch.matches(q, fields: [QuickMatch.Field(row.name, weight: QuickMatch.Weight.name),
                                             QuickMatch.Field(row.oneLiner, weight: QuickMatch.Weight.keyword)])
    }

    private static func states(_ rows: [ProjectRow], today: ISODay) -> [String: ProjectState.Output] {
        Dictionary(rows.map { ($0.id, state($0, today: today)) }, uniquingKeysWith: { first, _ in first })
    }

    /// The rows of one group in the given order, each parent followed by its sub-projects in the same group only when
    /// unfolded (`expanded`, or every parent while a find runs). A child whose parent is elsewhere sits flat; a cycle
    /// never hides a row.
    static func nest(_ rows: [ProjectRow], states: [String: ProjectState.Output], expanded: Set<String>,
                     openAll: Bool) -> [ProjectLine] {
        let ids = Set(rows.map(\.id))
        var kids: [String: [ProjectRow]] = [:]
        for row in rows {
            if let parent = row.parent, parent != row.id, ids.contains(parent) { kids[parent, default: []].append(row) }
        }
        let roots = rows.filter { row in row.parent.map { $0 == row.id || !ids.contains($0) } ?? true }
        // Everything a root reaches, folded or not: what is left after is a cycle, drawn flat so it never vanishes.
        var reached = Set<String>()
        var stack = roots.map(\.id)
        while let id = stack.popLast() {
            guard reached.insert(id).inserted else { continue }
            stack += (kids[id] ?? []).map(\.id)
        }
        var out: [ProjectLine] = []
        var placed = Set<String>()
        func append(_ row: ProjectRow, depth: Int) {
            guard placed.insert(row.id).inserted else { return }
            let children = (kids[row.id] ?? []).filter { !placed.contains($0.id) }
            let open = !children.isEmpty && (openAll || expanded.contains(row.id))
            out.append(ProjectLine(row: row, state: states[row.id] ?? state(row, today: .today()), depth: depth,
                                   children: children.count, expanded: open))
            if open { for child in children { append(child, depth: depth + 1) } }
        }
        for row in roots { append(row, depth: 0) }
        for row in rows where !reached.contains(row.id) { append(row, depth: 0) }
        return out
    }

    /// The list, top to bottom. Current: the projects in motion, then "Fading · n", folded unless the viewer opened it,
    /// a find runs, or nothing is in motion (a lone folded head would hide the whole tab). Past: newest heard first, under year labels, `pastLimit` rows and a "Show more" for the rest.
    static func entries(_ rows: [ProjectRow], tab: ProjectsTab, query: String, today: ISODay,
                        options: ProjectsListOptions = ProjectsListOptions()) -> [ProjectsEntry] {
        let searching = !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let states = states(rows, today: today)
        func members(_ g: ProjectsGroup) -> [ProjectRow] {
            rows.filter { row in states[row.id].map { ProjectsGroup($0.section) } == g && matches(row, query: query) }
        }
        func lines(_ rows: [ProjectRow]) -> [ProjectLine] {
            nest(rows, states: states, expanded: options.expanded, openAll: searching)
        }
        switch tab {
        case .current:
            var out = lines(members(.current)).map(ProjectsEntry.line)
            let fading = members(.fading)
            if !fading.isEmpty {
                let open = options.fadingOpen || searching || out.isEmpty
                out.append(.fading(count: fading.count, open: open))
                if open { out += lines(fading).map(ProjectsEntry.line) }
            }
            return out
        case .past:
            let past = lines(pastOrder(members(.past)))
            var out: [ProjectsEntry] = []
            var label: String?
            for line in past.prefix(max(options.pastLimit, 1)) {
                if line.depth == 0 {
                    let year = yearLabel(line.row)
                    if year != label { out.append(.year(year)) }
                    label = year
                }
                out.append(.line(line))
            }
            if past.count > options.pastLimit { out.append(.more(past.count - options.pastLimit)) }
            return out
        }
    }

    /// Past reads newest heard first; a project never heard from comes last; ties keep the server's order.
    static func pastOrder(_ rows: [ProjectRow]) -> [ProjectRow] {
        rows.enumerated().sorted { a, b in
            switch (a.element.lastMomentDay, b.element.lastMomentDay) {
            case let (x?, y?) where x != y: return x > y
            case (.some, nil): return true
            case (nil, .some): return false
            default: return a.offset < b.offset
            }
        }.map(\.element)
    }

    /// A Past label: the year the project was last heard from, or "Nothing heard yet".
    static func yearLabel(_ row: ProjectRow) -> String {
        ISODay(row.lastMomentDay).map { String($0.civil.year) } ?? Copy.Projects.nothingHeard
    }

    static func counts(_ rows: [ProjectRow], today: ISODay) -> [ProjectsGroup: Int] {
        var out: [ProjectsGroup: Int] = [.current: 0, .fading: 0, .past: 0]
        for row in rows { out[group(row, today: today), default: 0] += 1 }
        return out
    }

    /// Current counts everything it holds, fading included; Past the rest. `counts` is computed once per render.
    static func tabs(_ c: [ProjectsGroup: Int]) -> [TextTab<ProjectsTab>] {
        [TextTab(id: .current, label: Copy.Projects.current, count: (c[.current] ?? 0) + (c[.fading] ?? 0)),
         TextTab(id: .past, label: Copy.Projects.past, count: c[.past] ?? 0)]
    }

    /// Current, unless nothing is current and something is past.
    static func defaultTab(_ c: [ProjectsGroup: Int]) -> ProjectsTab {
        (c[.current] ?? 0) + (c[.fading] ?? 0) == 0 && (c[.past] ?? 0) > 0 ? .past : .current
    }

    /// DR-25 — "Projects", and R-PP8's "still indexing" while the server says `partial`. The tabs carry the counts
    /// and the open project says where it stands, so the eyebrow repeats neither (owner: avoid repetition).
    static func eyebrow(partial: Bool) -> String {
        Eyebrow.text(Copy.Projects.page, partial ? Copy.Projects.stillIndexing : "")
    }

    /// A milestone named after its own project ("Pick And Place Demo" on Pick And Place Demo) says only its day.
    static func milestoneName(_ name: String, project: String) -> String? {
        name.trimmingCharacters(in: .whitespaces).caseInsensitiveCompare(project.trimmingCharacters(in: .whitespaces))
            == .orderedSame ? nil : name
    }

    /// Where a project stands, as ONE signal (owner 2026-10-19: "one signal, not five"). In motion: the next
    /// milestone (overdue said so, never red — DR-7), else the plan's count, else when it was last heard. Fading: how
    /// long it has been quiet. Past: the day it was last heard — its year is the label above it, and a project never
    /// heard from says nothing (its label already does).
    static func standing(_ line: ProjectLine, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let row = line.row
        let last = ISODay(row.lastMomentDay)
        switch line.group {
        case .current:
            if let slug = line.state.next, let m = row.milestones.first(where: { $0.slug == slug }) {
                let name = milestoneName(m.name, project: row.name)
                guard let target = ISODay(m.target) else { return Copy.Projects.next(name, nil) }
                let day = RelativeDay.absolute(target, today: today, locale: locale)
                return target < today ? Copy.Projects.nextOverdue(name, since: day) : Copy.Projects.next(name, day)
            }
            if row.planned { return Copy.Projects.doneOf(row.progress) }
            return last.map { Copy.Projects.heard(RelativeDay.distance($0, today: today)) } ?? Copy.Projects.nothingHeard
        case .fading:
            return Copy.Projects.quietFor(days: last.map { today - $0 } ?? 0)
        case .past:
            return last.map { RelativeDay.dayInYear($0, locale: locale) } ?? ""
        }
    }

    /// A row's second line: what it is at rest, where it stands beside an open project — and nothing on the open row
    /// itself, whose detail says it beside it.
    static func secondLine(_ line: ProjectLine, style: ColumnPlan.ListStyle, selected: Bool, today: ISODay,
                           locale: Locale = .autoupdatingCurrent) -> String? {
        switch style {
        case .wide: return oneLine(line.row)
        case .triage:
            guard !selected else { return nil }
            let parts = line.children > 0 && !line.expanded ? Copy.Projects.parts(line.children) : ""
            let text = Eyebrow.text(parts, standing(line, today: today, locale: locale))
            return text.isEmpty ? nil : text
        case .titles, .hidden: return nil
        }
    }

    /// What the project is, in one line — the server's one-liner, or nothing (never a guess).
    static func oneLine(_ row: ProjectRow) -> String? {
        let text = row.oneLiner.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty ? nil : text
    }

    static func accessibilityLabel(_ line: ProjectLine, today: ISODay) -> String {
        let standing = standing(line, today: today)
        return Copy.Projects.rowLabel(line.row.name, standing: standing.isEmpty ? Copy.Projects.nothingHeard : standing,
                                      parts: line.children, expanded: line.expanded)
    }

    // MARK: - Keys (DR-68; every key path runs in `Instant.run`, DR-60)

    /// ↑/↓ from the open row. Past the last current row ↓ opens Fading and lands on its first row; past Past's last
    /// drawn row it draws the next page and moves on — so every project is reachable by keyboard.
    static func step(_ delta: Int, openId: String?, rows: [ProjectRow], tab: ProjectsTab, query: String,
                     today: ISODay, options: ProjectsListOptions) -> (open: String?, options: ProjectsListOptions) {
        var options = options
        var ids = entries(rows, tab: tab, query: query, today: today, options: options).compactMap(\.line).map(\.id)
        guard !ids.isEmpty else { return (nil, options) }
        guard let id = openId, let i = ids.firstIndex(of: id) else {
            return (delta >= 0 ? ids.first : ids.last, options)
        }
        if delta > 0, i == ids.count - 1 {
            if tab == .current, !options.fadingOpen { options.fadingOpen = true }
            else if tab == .past { options.pastLimit += pageSize }
            ids = entries(rows, tab: tab, query: query, today: today, options: options).compactMap(\.line).map(\.id)
        }
        return (ids[min(max(i + delta, 0), ids.count - 1)], options)
    }

    enum Side: Equatable { case expand(Bool), open(String), none }

    /// →/← on the open row: → unfolds a parent's parts; ← folds them, or on a part goes to its parent.
    static func side(_ delta: Int, line: ProjectLine?) -> Side {
        guard let line else { return .none }
        if delta > 0 { return line.children > 0 && !line.expanded ? .expand(true) : .none }
        if line.expanded { return .expand(false) }
        if line.depth > 0, let parent = line.row.parent { return .open(parent) }
        return .none
    }

    /// What a click on a row does. A plain row opens. A parent opens and unfolds its parts; clicked again while open,
    /// it folds or unfolds them (owner: "a dropdown that moves if I press again"). `expand` nil leaves the fold.
    static func tap(_ line: ProjectLine, openId: String?) -> (open: Bool, expand: Bool?) {
        guard line.children > 0 else { return (true, nil) }
        if openId == line.id { return (false, !line.expanded) }
        return (true, true)
    }

    /// How to show a project the list hides (a ⌘K landing): its tab, Fading opened, its parents in the group
    /// unfolded, and enough of Past drawn to reach it. Nil when the project is not in the list.
    struct Reveal: Equatable {
        let tab: ProjectsTab
        let openFading: Bool
        let expand: [String]
        let pastLimit: Int?
    }

    static func reveal(_ id: String, rows: [ProjectRow], today: ISODay, pastLimit: Int) -> Reveal? {
        guard let row = rows.first(where: { $0.id == id }) else { return nil }
        let states = states(rows, today: today)
        let g = group(row, today: today)
        let byId = Dictionary(rows.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var ancestors: [String] = []
        var seen: Set<String> = [id]
        var cursor = row.parent
        while let parent = cursor, seen.insert(parent).inserted, let p = byId[parent],
              states[parent].map({ ProjectsGroup($0.section) }) == g {
            ancestors.append(parent)
            cursor = p.parent
        }
        var limit: Int?
        if g == .past {
            let members = rows.filter { states[$0.id].map { ProjectsGroup($0.section) } == .past }
            let lines = nest(pastOrder(members), states: states, expanded: Set(ancestors), openAll: false)
            if let index = lines.firstIndex(where: { $0.id == id }), index >= pastLimit {
                limit = (index / pageSize + 1) * pageSize
            }
        }
        return Reveal(tab: g.tab, openFading: g == .fading, expand: ancestors, pastLimit: limit)
    }

    /// The same span over the detail's fuller data — the band's (R-PP9).
    static func span(_ t: ProjectTimeline, planned: Bool, today: ISODay) -> ProgressSpan {
        let items = t.items.filter { $0.kind != "created" }.compactMap { ISODay($0.day) }
        let threads = t.now.threads.compactMap { ISODay($0.since) }
        let targets = t.milestones.filter { $0.source != "expectedEnd" }.flatMap { m in
            [ISODay(m.target), ISODay(m.doneOn), earlierTarget(m)].compactMap { $0 }
        }
        return ProgressSpan.of(created: ISODay(t.project.created), days: items + threads, targets: targets,
                               planned: planned, today: today)
    }

    /// A moved milestone's previous target: the newest earlier claim in its chain — a `milestone`'s `target`, or a
    /// read-compat `due`'s own date, its `object` — so the chain crosses the `due` → `milestone` hop (R-PJ4).
    static func earlierTarget(_ m: ProjectMilestone) -> ISODay? {
        guard m.moved, m.chain.count > 1 else { return nil }
        let head = ISODay(m.target)
        for claim in m.chain.dropFirst() {
            if let day = ISODay(claim.target) ?? (claim.predicate == "due" ? ISODay(claim.object) : nil), day != head {
                return day
            }
        }
        return nil
    }

    /// A mark's hover words: the sentence's first six words.
    static func firstWords(_ text: String, count: Int = 6) -> String {
        let words = text.split(separator: " ")
        return words.count > count ? words.prefix(count).joined(separator: " ") + "…" : text
    }

    /// R-PP24 — a ⌘K entity row lands in Projects when its node is a project.
    static func isProject(_ id: String, in graph: GraphResponse?) -> Bool {
        graph?.nodes.contains { $0.id == id && $0.type == .project } ?? false
    }
}
