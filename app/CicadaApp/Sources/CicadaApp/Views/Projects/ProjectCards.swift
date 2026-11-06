import SwiftUI

/// ROR-118 round 1 (DESIGN_RULES §9, 2026-11-06) — Current's wide list is cards, not bare rows: one ringed card a
/// project (DR-9, DR-37: it holds a group), its sub-projects inside it on a darker well so the nesting reads at a
/// glance. Round 2: a card is as tall as its content, so no card carries a gap another lacks. Round 3: the cards stand
/// in a grid, each a tile with where it stands anchored at its foot, and the thread is a stepper that names itself.
enum ProjectCardLayout {
    /// Round 3: the cards stand in a grid, as many columns as the width holds at a readable measure.
    static let columnMin: CGFloat = 360
    static let gap: CGFloat = 16
    static let maxColumns = 3

    /// Columns for a list this wide (an unmeasured list is drawn as two) — never more than the cards there are, and
    /// never fewer than two when the width holds two, so a lone card stands at half the list, not across it.
    static func columns(width: CGFloat, count: Int = maxColumns) -> Int {
        guard width > 0 else { return 2 }
        let fit = min(maxColumns, max(1, Int((width + gap) / (columnMin + gap))))
        return min(fit, max(count, 2))
    }

    /// Groups in rows of `columns`; the last row may be short.
    static func rows(_ groups: [ProjectCardGroup], columns: Int) -> [[ProjectCardGroup]] {
        let n = max(columns, 1)
        return stride(from: 0, to: groups.count, by: n).map { Array(groups[$0..<min($0 + n, groups.count)]) }
    }
}

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

/// Round 3 — a run of cards as a grid: equal-height tiles side by side, so a name sits beside what it is about and the
/// window is used across, not just down.
struct ProjectCardGrid: View {
    let groups: [ProjectCardGroup]
    let today: ISODay
    let open: (ProjectLine) -> Void
    @State private var width: CGFloat = 0

    var body: some View {
        let columns = ProjectCardLayout.columns(width: width, count: groups.count)
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(ProjectCardLayout.gap)) {
            ForEach(ProjectCardLayout.rows(groups, columns: columns), id: \.first?.id) { row in
                HStack(alignment: .top, spacing: CicadaTheme.scaled(ProjectCardLayout.gap)) {
                    ForEach(0..<columns, id: \.self) { i in
                        if i < row.count {
                            ProjectCard(group: row[i], today: today, open: open)
                        } else {
                            Color.clear.frame(maxWidth: .infinity, maxHeight: 1)
                        }
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
    }
}

/// One tile: the name and what it is on top, where it stands at the foot (a stepper over its words when there is a
/// plan), the sub-projects on a well beneath.
struct ProjectCard: View {
    let group: ProjectCardGroup
    let today: ISODay
    let open: (ProjectLine) -> Void

    @State private var hovering = false
    private var line: ProjectLine { group.root }
    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }
    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.radiusLarge) }

    var body: some View {
        VStack(alignment: .leading, spacing: s(14)) {
            Button { open(line) } label: {
                head.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(ProjectsModel.accessibilityLabel(line, today: today))
            if !group.kids.isEmpty { kids }
        }
        .padding(s(20))
        .frame(maxWidth: .infinity, minHeight: s(176), maxHeight: .infinity, alignment: .topLeading)
        .background(shape.fill(CicadaTheme.bgFocus))
        .ringed(hovering ? .strong : .resting, in: shape)
        .onHover { hovering = $0 }
    }

    private var head: some View {
        VStack(alignment: .leading, spacing: s(6)) {
            Text(line.row.name)
                .font(CicadaTheme.font(size: 20, weight: .medium))
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
                .help(line.row.name)
            if let one = ProjectsModel.oneLine(line.row) {
                Text(one).font(CicadaTheme.detailBodyFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(2)
                    .multilineTextAlignment(.leading)
            }
            Spacer(minLength: s(18))
            standing
        }
    }

    /// Where it stands: the steps of its plan (only with one, R-PJ11), then the one signal in words with the glyph
    /// that says which kind it is — a diamond for the next milestone, a clock for the last time it was heard.
    private var standing: some View {
        let text = ProjectsModel.standing(line, today: today)
        let steps = ProjectSteps.steps(line)
        return VStack(alignment: .leading, spacing: s(10)) {
            if !steps.isEmpty { ProjectSteps(steps: steps) }
            if !text.isEmpty {
                HStack(spacing: s(6)) {
                    Image(systemName: ProjectSteps.glyph(line)).font(CicadaTheme.icon(.inline))
                        .foregroundStyle(CicadaTheme.textSecondary).accessibilityHidden(true)
                    Text(text).font(CicadaTheme.metaMediumFont).monospacedDigit()
                        .foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                }
            }
        }
    }

    private var kids: some View {
        VStack(alignment: .leading, spacing: s(2)) {
            ForEach(group.kids) { kid in ProjectKidRow(line: kid, today: today) { open(kid) } }
        }
        .padding(s(4))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgBase))
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
                            Text(text).font(CicadaTheme.captionFont).monospacedDigit()
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

/// A plan in steps: one segment a milestone in date order — filled once done, the next one a step lighter, the rest
/// on the well (ROR-118 round 3; it replaces the miniature thread, whose diamonds and dots no one could name). There
/// is no stepper without a plan (R-PJ11) and no percentage; each segment names its milestone on hover.
struct ProjectSteps: View {
    enum State: Equatable { case done, next, later }
    struct Step: Equatable { let state: State; let name: String }

    let steps: [Step]

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
            Step(state: m.status == "done" ? .done : (m.slug == line.state.next ? .next : .later), name: m.name)
        }
    }

    /// The glyph of the one signal: a diamond when it names a milestone, else a clock.
    static func glyph(_ line: ProjectLine) -> String {
        line.group == .current && line.state.next.flatMap { slug in line.row.milestones.first { $0.slug == slug } } != nil
            ? "diamond" : "clock"
    }

    private func fill(_ state: State) -> Color {
        switch state {
        case .done: CicadaTheme.textPrimary
        case .next: CicadaTheme.textSecondary
        case .later: CicadaTheme.bgBadge
        }
    }

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(4)) {
            ForEach(Array(steps.enumerated()), id: \.offset) { _, step in
                Capsule().fill(fill(step.state)).frame(height: CicadaTheme.scaled(5)).help(step.name)
            }
        }
        .accessibilityHidden(true)
    }
}
