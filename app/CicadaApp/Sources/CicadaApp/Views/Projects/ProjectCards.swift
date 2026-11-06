import SwiftUI

/// ROR-118 round 1 (DESIGN_RULES §9, 2026-11-06) — Current's wide list is cards, not bare rows: one ringed card a
/// project (DR-9, DR-37: it holds a group), its sub-projects inside it on a darker well so the nesting reads at a
/// glance, and the card stretches to fill the window instead of leaving it black (DR-35: the gaps grow, not the type).
enum ProjectCardLayout {
    /// A card never gets shorter than this, nor taller than `maxHeight`, whatever the window.
    static let minHeight: CGFloat = 168
    static let maxHeight: CGFloat = 272
    /// What one sub-project row adds inside its parent's card.
    static let childHeight: CGFloat = 64

    /// The parent card's resting height so the cards together fill `viewport`: the sub-project rows come off first,
    /// then the rest is shared, within the card bounds.
    static func height(viewport: CGFloat, cards: Int, children: Int, gap: CGFloat) -> CGFloat {
        guard cards > 0, viewport > 0 else { return CicadaTheme.scaled(minHeight) }
        let free = viewport - CGFloat(children) * CicadaTheme.scaled(childHeight)
            - CGFloat(cards - 1) * gap - CicadaTheme.scaled(48)
        return min(max(free / CGFloat(cards), CicadaTheme.scaled(minHeight)), CicadaTheme.scaled(maxHeight))
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

struct ProjectCard: View {
    let group: ProjectCardGroup
    let today: ISODay
    let minHeight: CGFloat
    let open: (ProjectLine) -> Void

    @State private var hovering = false
    private var line: ProjectLine { group.root }
    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }
    private var shape: RoundedRectangle { CicadaTheme.shape(CicadaTheme.radiusLarge) }

    var body: some View {
        VStack(alignment: .leading, spacing: s(12)) {
            Button { open(line) } label: { head.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .contentShape(Rectangle()) }
                .buttonStyle(.cicadaPlain)
                .accessibilityLabel(ProjectsModel.accessibilityLabel(line, today: today))
            if !group.kids.isEmpty { kids }
        }
        .padding(s(20))
        .frame(maxWidth: .infinity, minHeight: minHeight, alignment: .topLeading)
        .background(shape.fill(CicadaTheme.bgFocus))
        .ringed(hovering ? .strong : .resting, in: shape)
        .onHover { hovering = $0 }
    }

    private var head: some View {
        VStack(alignment: .leading, spacing: s(6)) {
            HStack(alignment: .firstTextBaseline, spacing: s(12)) {
                Text(line.row.name)
                    .font(CicadaTheme.font(size: 17, weight: .medium))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .help(line.row.name)
                Spacer(minLength: s(12))
                standing(line)
            }
            if let one = ProjectsModel.oneLine(line.row) {
                Text(one).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(2)
            }
            Spacer(minLength: s(16))
            ProjectThread(span: ProjectThread.span(line.row, today: today), marks: ProjectThread.marks(line.row))
                .frame(height: s(26))
                .accessibilityHidden(true)
        }
    }

    /// One signal, one pill, at the end of the project's own line (DR-44).
    @ViewBuilder
    private func standing(_ l: ProjectLine) -> some View {
        let text = ProjectsModel.standing(l, today: today)
        if !text.isEmpty { Tag(text: text).lineLimit(1) }
    }

    private var kids: some View {
        VStack(alignment: .leading, spacing: s(2)) {
            ForEach(group.kids) { kid in ProjectKidRow(line: kid, today: today) { open(kid) } }
        }
        .padding(s(4))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.bgBase))
    }
}

/// A sub-project on its parent's card: a hook from the parent, its own name at 13, where it stands at the end.
private struct ProjectKidRow: View {
    let line: ProjectLine
    let today: ISODay
    let action: () -> Void
    @State private var hovering = false

    private func s(_ v: CGFloat) -> CGFloat { CicadaTheme.scaled(v) }

    var body: some View {
        Button(action: action) {
            HStack(alignment: .center, spacing: s(10)) {
                Elbow().stroke(CicadaTheme.textTertiary, lineWidth: 1).frame(width: s(14), height: s(22))
                    .padding(.leading, s(4)).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: s(2)) {
                    Text(line.row.name).font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary).lineLimit(1)
                    if let one = ProjectsModel.oneLine(line.row) {
                        Text(one).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                    }
                }
                Spacer(minLength: s(12))
                let text = ProjectsModel.standing(line, today: today)
                if !text.isEmpty { Tag(text: text).lineLimit(1) }
            }
            .padding(.horizontal, s(10))
            .frame(maxWidth: .infinity, minHeight: s(ProjectCardLayout.childHeight - 8), alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .rowHover($hovering)
        .accessibilityLabel(ProjectsModel.accessibilityLabel(line, today: today))
    }
}

/// A sub-project's hook: down from its parent, then across to its name.
private struct Elbow: Shape {
    func path(in rect: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: rect.minX, y: rect.minY))
            p.addLine(to: CGPoint(x: rect.minX, y: rect.midY - 3))
            p.addQuadCurve(to: CGPoint(x: rect.minX + 3, y: rect.midY), control: CGPoint(x: rect.minX, y: rect.midY))
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
        }
    }
}

/// The project's thread in miniature — the band's own shapes in the text ladder (DR-13: Meadow stays on the band):
/// a solid run from its first day to today, a dashed open end when there is no plan (R-PJ11), the plan's remainder as
/// the track only when there is one, a diamond a milestone (filled once done) and the Today dot.
struct ProjectThread: View {
    struct Mark: Equatable { let day: ISODay; let done: Bool }

    let span: ProgressSpan
    let marks: [Mark]

    static func span(_ row: ProjectRow, today: ISODay) -> ProgressSpan {
        let targets = row.milestones.filter { $0.source != "expectedEnd" }.compactMap { ISODay($0.target) }
        let days = ([row.activity.first?.day, row.lastMomentDay]).compactMap { ISODay($0) }
        return ProgressSpan.of(created: ISODay(row.created), days: days, targets: targets, planned: row.planned,
                               today: today)
    }

    static func marks(_ row: ProjectRow) -> [Mark] {
        row.milestones.filter { $0.source != "expectedEnd" }.compactMap { m in
            guard let day = ISODay(m.status == "done" ? (m.doneOn ?? m.target) : m.target) else { return nil }
            return Mark(day: day, done: m.status == "done")
        }
    }

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let y = geo.size.height / 2
            let today = min(max(w * span.fill, 0), w)
            ZStack(alignment: .leading) {
                if span.planned {
                    Capsule().fill(CicadaTheme.bgBadge).frame(width: w, height: 3).position(x: w / 2, y: y)
                } else {
                    MidLine().stroke(CicadaTheme.progressOpenEnd, style: StrokeStyle(lineWidth: 2, dash: [3, 4]))
                        .frame(width: max(w - today, 0), height: 3).position(x: today + max(w - today, 0) / 2, y: y)
                }
                Capsule().fill(CicadaTheme.textSecondary).frame(width: max(today, 3), height: 3)
                    .position(x: max(today, 3) / 2, y: y)
                ForEach(Array(marks.enumerated()), id: \.offset) { _, mark in
                    diamond(done: mark.done).position(x: min(max(w * span.fraction(mark.day), 5), w - 5), y: y)
                }
                Circle().fill(CicadaTheme.textPrimary).frame(width: 9, height: 9)
                    .background(Circle().fill(CicadaTheme.bgFocus).padding(-2.5))
                    .position(x: min(max(today, 5), w - 5), y: y)
            }
        }
    }

    private func diamond(done: Bool) -> some View {
        let shape = CicadaTheme.shape(2)
        return shape.fill(done ? CicadaTheme.textPrimary : CicadaTheme.bgFocus)
            .overlay { if !done { shape.strokeBorder(CicadaTheme.textSecondary, lineWidth: 1.5) } }
            .frame(width: 9, height: 9)
            .background(shape.fill(CicadaTheme.bgFocus).padding(-2.5))
            .rotationEffect(.degrees(45))
    }
}
