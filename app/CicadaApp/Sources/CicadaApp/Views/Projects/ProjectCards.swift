import SwiftUI

/// ROR-118 round 4 (DESIGN_RULES §9, 2026-11-06) — Current at rest has one lead and a list. The first project stands as
/// a card across the window: its name and what it is on the left, its plan on the right as the milestones themselves
/// (a mark, a name, a day), its sub-projects on a well beneath. Every other project is one row of a single ringed list —
/// name over what it is, where it stands at the end — with its sub-projects indented under it. Round 3's equal tiles
/// gave a project with no plan a dead gap beside one with a plan; a row has no such gap, and the lead is the one thing
/// to look at. The window below is empty because the person has few projects: nothing is added to fill it.
/// A root project and the sub-projects that follow it in the list.
struct ProjectCardGroup: Identifiable, Equatable {
    let root: ProjectLine
    let kids: [ProjectLine]
    var id: String { root.id }

    /// Lines in list order → one group per root; a line that opens the list at depth > 0 stands as its own root.
    static func groups(_ lines: [ProjectLine]) -> [ProjectCardGroup] {
        var out: [ProjectCardGroup] = []
        for line in lines {
            if line.depth > 0, let last = out.popLast() {
                out.append(ProjectCardGroup(root: last.root, kids: last.kids + [line]))
            } else {
                out.append(ProjectCardGroup(root: line, kids: []))
            }
        }
        return out
    }
}

extension ProjectCardGroup {
    /// Current's entries as runs of cards with the static *Gone quiet* label between them.
    enum Block: Identifiable {
        case cards([ProjectCardGroup])
        case quiet

        var id: String {
            switch self {
            case .quiet: "quiet"
            case .cards(let g): g.first?.id ?? "empty"
            }
        }
    }

    static func blocks(_ entries: [ProjectsEntry]) -> [Block] {
        var runs: [[ProjectLine]] = []
        var out: [Block] = []
        for entry in entries {
            switch entry {
            case .line(let line):
                if runs.isEmpty { runs.append([]) }
                runs[runs.count - 1].append(line)
            case .quiet:
                if let run = runs.popLast() { out.append(.cards(groups(run))) }
                out.append(.quiet)
                runs.append([])
            default: break
            }
        }
        if let run = runs.last, !run.isEmpty { out.append(.cards(groups(run))) }
        return out
    }
}

/// Current's run of cards: the lead (only the first run, so *Gone quiet* never has one) then the rest as one list.
struct ProjectCardGrid: View {
    let groups: [ProjectCardGroup]
    let today: ISODay
    var leads = true
    let open: (ProjectLine) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(16)) {
            if leads, let lead = groups.first {
                ProjectLeadCard(group: lead, today: today, open: open)
            }
            let rest = leads ? Array(groups.dropFirst()) : groups
            if !rest.isEmpty { ProjectRestList(groups: rest, today: today, open: open) }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

/// A project's picture beside its name — only when it has one; a project with none draws nothing (CLAUDE.md, Pictures).
private struct ProjectMark: View {
    let line: ProjectLine
    let size: CGFloat
    var body: some View {
        EntityPicture(id: line.id, name: line.row.name, type: .project, size: size, collapsesWhenEmpty: true)
    }
}

/// The one signal in words with the glyph that says which kind it is: a diamond for the next milestone, a clock for the
/// last time it was heard.
private struct ProjectStanding: View {
    let line: ProjectLine
    let today: ISODay
    var body: some View {
        let text = ProjectsModel.standing(line, today: today)
        if !text.isEmpty {
            HStack(spacing: CicadaTheme.scaled(6)) {
                Image(systemName: ProjectSteps.glyph(line)).font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textSecondary).accessibilityHidden(true)
                Text(text).font(CicadaTheme.metaMediumFont).monospacedDigit()
                    .foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
            }
        }
    }
}

/// The sub-projects of a card or row, on the `bgBase` well.
private struct ProjectKids: View {
    let kids: [ProjectLine]
    let today: ISODay
    let open: (ProjectLine) -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
            ForEach(kids) { kid in ProjectKidRow(line: kid, today: today) { open(kid) } }
        }
        .padding(CicadaTheme.scaled(4))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgBase))
    }
}

/// The lead: name and what it is beside its plan, the sub-projects beneath.
struct ProjectLeadCard: View {
    let group: ProjectCardGroup
    let today: ISODay
    let open: (ProjectLine) -> Void

    @State private var hovering = false
    private var line: ProjectLine { group.root }
    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }
    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.radiusLarge) }

    var body: some View {
        let steps = ProjectSteps.steps(line, without: group.kids)
        VStack(alignment: .leading, spacing: s(20)) {
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: s(48)) {
                    head(steps: steps)
                    if !steps.isEmpty { ProjectSteps(steps: steps, today: today).frame(width: s(400)) }
                }
                VStack(alignment: .leading, spacing: s(20)) {
                    head(steps: steps)
                    if !steps.isEmpty { ProjectSteps(steps: steps, today: today) }
                }
            }
            if !group.kids.isEmpty { ProjectKids(kids: group.kids, today: today, open: open) }
        }
        .padding(s(24))
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(shape.fill(CicadaTheme.bgFocus))
        .ringed(hovering ? .strong : .resting, in: shape)
        .onHover { hovering = $0 }
    }

    private func head(steps: [ProjectSteps.Step]) -> some View {
        Button { open(line) } label: {
            HStack(alignment: .top, spacing: s(14)) {
                ProjectMark(line: line, size: 36)
                VStack(alignment: .leading, spacing: s(8)) {
                    Text(line.row.name)
                        .font(CicadaTheme.font(size: 24, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary).lineLimit(2).multilineTextAlignment(.leading)
                    if let one = ProjectsModel.oneLine(line.row) {
                        Text(one).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textSecondary)
                            .lineLimit(3).multilineTextAlignment(.leading)
                    }
                    // A plan names its own next step; only a project with none says when it was last heard.
                    if steps.isEmpty { ProjectStanding(line: line, today: today).padding(.top, s(6)) }
                }
            }
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityLabel(ProjectsModel.accessibilityLabel(line, today: today))
    }
}

/// Every other project: one ringed list, a row a project with a hairline between, sub-projects indented beneath.
struct ProjectRestList: View {
    let groups: [ProjectCardGroup]
    let today: ISODay
    let open: (ProjectLine) -> Void

    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.radiusLarge) }

    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(groups.enumerated()), id: \.element.id) { i, group in
                if i > 0 { Rectangle().fill(CicadaTheme.border).frame(height: 1).padding(.horizontal, CicadaTheme.scaled(20)) }
                ProjectListRow(group: group, today: today, open: open)
            }
        }
        .padding(.vertical, CicadaTheme.scaled(6))
        .frame(maxWidth: .infinity)
        .background(shape.fill(CicadaTheme.bgFocus))
        .ringed(.resting, in: shape)
    }
}

private struct ProjectListRow: View {
    let group: ProjectCardGroup
    let today: ISODay
    let open: (ProjectLine) -> Void
    @State private var hovering = false

    private var line: ProjectLine { group.root }
    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }

    var body: some View {
        VStack(alignment: .leading, spacing: s(6)) {
            Button { open(line) } label: {
                HStack(alignment: .center, spacing: s(14)) {
                    ProjectMark(line: line, size: 28)
                    VStack(alignment: .leading, spacing: s(3)) {
                        Text(line.row.name).font(CicadaTheme.font(size: 17, weight: .medium))
                            .foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                        if let one = ProjectsModel.oneLine(line.row) {
                            Text(one).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                        }
                    }
                    Spacer(minLength: s(16))
                    ProjectStanding(line: line, today: today)
                }
                .padding(.horizontal, s(20)).padding(.vertical, s(14))
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .rowHover($hovering)
            .accessibilityLabel(ProjectsModel.accessibilityLabel(line, today: today))
            if !group.kids.isEmpty {
                ProjectKids(kids: group.kids, today: today, open: open)
                    .padding(.horizontal, s(14)).padding(.bottom, s(10))
            }
        }
    }
}

/// A sub-project on its parent's card: the turn-down glyph from the parent, its name, where it stands.
private struct ProjectKidRow: View {
    let line: ProjectLine
    let today: ISODay
    let action: () -> Void
    @State private var hovering = false

    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }

    var body: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: s(10)) {
                Image(systemName: "arrow.turn.down.right").font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textSecondary).padding(.top, s(2)).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: s(2)) {
                    HStack(alignment: .firstTextBaseline, spacing: s(12)) {
                        Text(line.row.name).font(CicadaTheme.rowFont)
                            .foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                        Spacer(minLength: 0)
                        let text = ProjectsModel.standing(line, today: today)
                        if !text.isEmpty {
                            Text(text).font(CicadaTheme.metaFont).monospacedDigit()
                                .foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                        }
                    }
                    if let one = ProjectsModel.oneLine(line.row) {
                        Text(one).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                    }
                }
            }
            .padding(.horizontal, s(10)).padding(.vertical, s(8))
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering)
        .accessibilityLabel(ProjectsModel.accessibilityLabel(line, today: today))
    }
}

/// A plan as its milestones: a mark, a name and a day each, in date order. Done ones carry a check, the one the project
/// is heading for a ring in primary ink, the rest a quiet ring; an overdue next day reads in the warning ink. Only with a
/// plan (R-PJ11: no plan, nothing here; no percentage). It replaces round 3's unlabelled segments, which no one could name.
struct ProjectSteps: View {
    enum State: Equatable { case done, next, later }
    struct Step: Equatable { let state: State; let name: String; var day: ISODay? = nil }

    /// A plan longer than this drops its oldest done steps first.
    static let cap = 5

    let steps: [Step]
    var today: ISODay = ISODay.today()

    /// The plan's milestones by date, undated last; the open one the project is heading for is the next.
    static func steps(_ line: ProjectLine) -> [Step] {
        let planned = line.row.milestones.filter { $0.source != "expectedEnd" }
        let ordered = planned.enumerated().sorted { a, b in
            switch (ISODay(a.element.target), ISODay(b.element.target)) {
            case let (x?, y?): x != y ? x < y : a.offset < b.offset
            case (_?, nil): true
            case (nil, _?): false
            default: a.offset < b.offset
            }
        }.map(\.element)
        return ordered.map { m in
            let done = m.status == "done"
            return Step(state: done ? .done : (m.slug == line.state.next ? .next : .later), name: m.name,
                        day: ISODay(done ? (m.doneOn ?? m.target) : m.target))
        }
    }

    /// The lead's plan without a milestone a sub-project of its own carries by name: the sub-project's row says it, once.
    static func steps(_ line: ProjectLine, without kids: [ProjectLine]) -> [Step] {
        let names = Set(kids.map { $0.row.name.lowercased() })
        return steps(line).filter { !names.contains($0.name.lowercased()) }
    }

    /// What a card draws of a long plan: the oldest done steps go first, then the far end.
    static func visible(_ steps: [Step]) -> [Step] {
        var out = steps
        while out.count > cap, out.first?.state == .done { out.removeFirst() }
        return Array(out.prefix(cap))
    }

    /// The glyph of the one signal: a diamond when it names a milestone, else a clock.
    static func glyph(_ line: ProjectLine) -> String {
        line.group == .current && line.state.next.flatMap { slug in line.row.milestones.first { $0.slug == slug } } != nil
            ? "diamond" : "clock"
    }

    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }

    private func mark(_ state: State) -> (name: String, ink: Color) {
        switch state {
        case .done: ("checkmark.circle.fill", CicadaTheme.textSecondary)
        case .next: ("circle", CicadaTheme.textPrimary)
        case .later: ("circle", CicadaTheme.textTertiary)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: s(2)) {
            ForEach(Array(Self.visible(steps).enumerated()), id: \.offset) { _, step in
                let m = mark(step.state)
                let overdue = step.state == .next && (step.day.map { $0 < today } ?? false)
                HStack(spacing: s(12)) {
                    Image(systemName: m.name).font(CicadaTheme.icon(.inline)).foregroundStyle(m.ink)
                        .frame(width: s(18)).accessibilityHidden(true)
                    Text(step.name).font(step.state == .next ? CicadaTheme.rowFont : CicadaTheme.bodyFont)
                        .foregroundStyle(step.state == .later ? CicadaTheme.textSecondary : CicadaTheme.textPrimary)
                        .lineLimit(1)
                    Spacer(minLength: s(12))
                    if let day = step.day {
                        Text(RelativeDay.absolute(day, today: today)).font(CicadaTheme.metaFont).monospacedDigit()
                            .foregroundStyle(overdue ? CicadaTheme.warning : CicadaTheme.textSecondary)
                    }
                }
                .padding(.vertical, s(7))
            }
        }
        .accessibilityHidden(true)
    }
}
