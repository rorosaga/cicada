import SwiftUI

/// R-PP6 — which projects a tab shows; `nil` is All. A resting project shows only under All.
enum ProjectsTab: Hashable, Sendable { case active, quiet }

/// One list row: the project, its derived state on the viewer's today, and its depth under a visible parent.
struct ProjectLine: Identifiable, Equatable {
    let row: ProjectRow
    let state: ProjectState.Output
    let depth: Int
    var id: String { row.id }
}

/// R-PP7 — a person beside a project, drawn as initials (a person has no service mark, DR-52).
struct PersonMark: Identifiable, Equatable {
    let id: String
    let name: String
    var initials: String { ProjectsModel.initials(name) }
}

/// §5.3 / DR-36 — the detail column's widths, in units: the band runs to 880 (the approved mock), text stays ≤ 760.
enum ProjectLayout {
    static let detailMaxWidth: CGFloat = 880
    static let textMaxWidth: CGFloat = 760
}

/// §3.8 / R-PP9 — the green bar's geometry, shared by the list row's mini bar and the band, so the two never disagree
/// about how full a project is. From the project's first moment (or `created`, or an earlier target — whichever is
/// first) to its end: with a plan, the latest target when it lies after today, else a week past today; with no plan, a
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

/// G141 PJ-5 — what the Projects list shows, pure (the `ClustersModel` pattern). Every word that depends on today is
/// computed here from the absolute days the server sent (R-PJ6, DR-58); `today` is an argument, so a test pins it and
/// midnight re-derives the list with no network.
enum ProjectsModel {
    static func state(_ row: ProjectRow, today: ISODay) -> ProjectState.Output {
        ProjectState.state(ProjectState.Input(row), today: today)
    }

    static func shows(_ state: ProjectState.Output, tab: ProjectsTab?) -> Bool {
        switch tab {
        case .active: state.section == .inMotion
        case .quiet: state.section == .quiet
        case nil: true
        }
    }

    /// DR-46 — find matches a project's name and one-liner, folded as the palette folds (one ranker, `QuickMatch`).
    static func matches(_ row: ProjectRow, query: String) -> Bool {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return true }
        return QuickMatch.matches(q, fields: [QuickMatch.Field(row.name, weight: QuickMatch.Weight.name),
                                             QuickMatch.Field(row.oneLiner, weight: QuickMatch.Weight.keyword)])
    }

    /// The rows in the server's order (newest activity first), each parent followed by its shown children (§11.2),
    /// at most two levels deep; a child whose parent is not shown sits flat.
    static func lines(_ rows: [ProjectRow], tab: ProjectsTab?, query: String, today: ISODay) -> [ProjectLine] {
        let states = Dictionary(rows.map { ($0.id, state($0, today: today)) }, uniquingKeysWith: { first, _ in first })
        let visible = rows.filter { shows(states[$0.id] ?? state($0, today: today), tab: tab) && matches($0, query: query) }
        let ids = Set(visible.map(\.id))
        var out: [ProjectLine] = []
        var placed = Set<String>()
        func append(_ row: ProjectRow, depth: Int) {
            guard placed.insert(row.id).inserted else { return }
            out.append(ProjectLine(row: row, state: states[row.id] ?? state(row, today: today), depth: depth))
            guard depth < 2 else { return }
            for child in visible where child.parent == row.id { append(child, depth: depth + 1) }
        }
        for row in visible where row.parent.map({ !ids.contains($0) }) ?? true { append(row, depth: 0) }
        for row in visible where !placed.contains(row.id) { append(row, depth: 0) }   // a cycle never hides a row
        return out
    }

    static func tabs(_ rows: [ProjectRow], today: ISODay) -> [TextTab<ProjectsTab>] {
        let sections = rows.map { state($0, today: today).section }
        return [TextTab(id: .active, label: Copy.Projects.active, count: sections.filter { $0 == .inMotion }.count),
                TextTab(id: .quiet, label: Copy.Projects.quiet, count: sections.filter { $0 == .quiet }.count),
                TextTab(id: nil, label: Copy.Lists.all, count: rows.count)]
    }

    /// R-PP6 — Active unless nothing is in motion, then All.
    static func defaultTab(_ rows: [ProjectRow], today: ISODay) -> ProjectsTab? {
        rows.contains { state($0, today: today).section == .inMotion } ? .active : nil
    }

    /// DR-25 — "Projects · 6 active"; with a project open, "Projects · 1 of 6 · Planned" (the mock); R-PP8's
    /// "still indexing" while the server says `partial`.
    static func eyebrow(visible: Int, tab: ProjectsTab?, position: Int?, openPlanned: Bool?, partial: Bool) -> String {
        let indexing = partial ? Copy.Projects.stillIndexing : ""
        if let openPlanned {
            return Eyebrow.text(Copy.Projects.page, position.map { Copy.Projects.position($0, of: visible) } ?? "",
                                openPlanned ? Copy.Projects.planned : Copy.Projects.noPlanYet, indexing)
        }
        let count: String
        switch tab {
        case .active: count = Copy.Projects.countActive(visible)
        case .quiet: count = Copy.Projects.countQuiet(visible)
        case nil: count = UsageFormat.count(visible)
        }
        return Eyebrow.text(Copy.Projects.page, count, indexing)
    }

    /// R-PP7 — where a project stands now, the first rung that holds (a missing fact never shows a guess).
    static func nowLine(_ line: ProjectLine, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let row = line.row
        let st = line.state
        if let live = row.openThreads.filter({ !st.isQuiet($0.claimId) }).max(by: { $0.since < $1.since }) {
            return live.text
        }
        if let quiet = row.openThreads.first {
            return Copy.Projects.quietThread(days: st.thread(quiet.claimId)?.quietDays ?? 0, text: quiet.text)
        }
        let last = ISODay(row.lastMomentDay)
        switch st.section {
        case .quiet:
            return Copy.Projects.quietFor(days: last.map { today - $0 } ?? 0)
        case .resting:
            return last.map { Copy.Projects.resting(lastHeard: RelativeDay.absolute($0, today: today, locale: locale)) }
                ?? Copy.Projects.nothingHeard
        case .inMotion:
            if !row.oneLiner.isEmpty { return row.oneLiner }
            return last.map { Copy.Projects.lastHeard(RelativeDay.absolute($0, today: today, locale: locale)) }
                ?? Copy.Projects.nothingHeard
        }
    }

    /// "Next · First grasp, Oct 1", "Next · First grasp, overdue since Sep 9", "1 of 4 done" or "No plan yet" — never
    /// red (DR-7) and never a percentage (R-PJ11). Progress is the server's (`row.progress`): a row carries only five
    /// milestones, so counting them here could undercount.
    static func nextLine(_ line: ProjectLine, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let row = line.row
        if let slug = line.state.next, let m = row.milestones.first(where: { $0.slug == slug }) {
            guard let target = ISODay(m.target) else { return Copy.Projects.next(m.name, nil) }
            let day = RelativeDay.absolute(target, today: today, locale: locale)
            return target < today ? Copy.Projects.nextOverdue(m.name, since: day) : Copy.Projects.next(m.name, day)
        }
        return row.planned ? Copy.Projects.doneOf(row.progress) : Copy.Projects.noPlanYet
    }

    /// The triage row's second line: "1 of 4 done · First grasp Oct 1", or "No plan yet · last Sep 14".
    static func shortLine(_ line: ProjectLine, today: ISODay, locale: Locale = .autoupdatingCurrent) -> String {
        let row = line.row
        guard row.planned else {
            return Copy.Projects.noPlanLast(ISODay(row.lastMomentDay).map { RelativeDay.absolute($0, today: today, locale: locale) })
        }
        let next = line.state.next.flatMap { slug in row.milestones.first { $0.slug == slug } }.map { m in
            Copy.Projects.nextShort(m.name, ISODay(m.target).map { RelativeDay.absolute($0, today: today, locale: locale) })
        }
        return Copy.Projects.shortPlanned(row.progress, next: next)
    }

    /// DR-58 — the compact age, with the full date as its `.help` ("—" with its reason when nothing happened yet).
    static func age(_ row: ProjectRow, today: ISODay, locale: Locale = .autoupdatingCurrent) -> (text: String, help: String) {
        let last = ISODay(row.lastMomentDay)
        return (RelativeDay.compactAge(last, today: today),
                last.map { Copy.Projects.lastActivity(RelativeDay.full($0, locale: locale)) } ?? Copy.Projects.noActivity)
    }

    static func questions(_ row: ProjectRow) -> String? {
        row.followups > 0 ? Copy.Projects.questions(row.followups) : nil
    }

    static func accessibilityLabel(_ line: ProjectLine) -> String {
        Copy.Projects.rowLabel(line.row.name, planned: line.row.planned, progress: line.row.progress)
    }

    static func bar(_ row: ProjectRow, today: ISODay) -> ProgressSpan {
        let days = (row.activity.map(\.day) + [row.lastMomentDay].compactMap { $0 } + row.openThreads.map(\.since))
            .compactMap { ISODay($0) }
        let targets = row.milestones.flatMap { [ISODay($0.target), ISODay($0.doneOn)].compactMap { $0 } }
        return ProgressSpan.of(created: ISODay(row.created), days: days, targets: targets, planned: row.planned,
                               today: today)
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

    /// R-PP7 — each project's `person` neighbours in the graph the Store holds, the owner and facets left out, at most
    /// three, by degree then name. `ProjectRow` carries no people; this is data the app already has.
    static func peopleIndex(_ graph: GraphResponse?) -> [String: [PersonMark]] {
        guard let graph else { return [:] }
        var nodes: [String: GraphNode] = [:]
        for node in graph.nodes where !node.isFacet { nodes[node.id] = node }
        var found: [String: [GraphNode]] = [:]
        for edge in graph.links {
            for (a, b) in [(edge.source, edge.target), (edge.target, edge.source)] {
                guard let project = nodes[a], project.type == .project,
                      let person = nodes[b], person.type == .person, !person.isOwner,
                      !(found[a]?.contains { $0.id == person.id } ?? false) else { continue }
                found[a, default: []].append(person)
            }
        }
        return found.mapValues { people in
            people.sorted { ($0.degree, $1.name) > ($1.degree, $0.name) }.prefix(3).map { PersonMark(id: $0.id, name: $0.name) }
        }
    }

    static func initials(_ name: String) -> String {
        name.split(separator: " ").prefix(2).compactMap(\.first).map { String($0).uppercased() }.joined()
    }

    /// R-PP24 — a ⌘K entity row lands in Projects when its node is a project.
    static func isProject(_ id: String, in graph: GraphResponse?) -> Bool {
        graph?.nodes.contains { $0.id == id && $0.type == .project } ?? false
    }
}
