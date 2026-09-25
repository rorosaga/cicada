import SwiftUI

/// What the list column says before it has rows to draw, in precedence order (DR-43, DR-50).
enum ProjectsListState: Equatable {
    case loading, failed(String), empty, tabEmpty, noMatch, list

    static func of(phase: ProjectsCache.Phase, hasList: Bool, rows: Int, lines: Int, finding: Bool) -> ProjectsListState {
        if !hasList {
            if case .failed(let message) = phase { return .failed(message) }
            return .loading
        }
        if rows == 0 { return .empty }
        if lines == 0 { return finding ? .noMatch : .tabEmpty }
        return .list
    }
}

/// §5.3 / §10 — the Projects list in its three styles (R-PP7): one line at full width, two lines beside a project,
/// titles beside a project and the Reader. Selection is `bgSelected`, never the accent (DR-22, `SelectionTintLintTests`).
struct ProjectsListColumn: View {
    let lines: [ProjectLine]
    let style: ColumnPlan.ListStyle
    let today: ISODay
    let people: [String: [PersonMark]]
    let state: ProjectsListState
    let tab: ProjectsTab?
    let query: String
    @Binding var findOpen: Bool
    @Binding var findText: String
    let openId: String?
    let open: (String) -> Void
    let move: (Int) -> Void
    let focusDetail: () -> Void
    let escape: () -> Void
    let retry: () -> Void

    var body: some View {
        ScrollViewReader { proxy in
            VStack(alignment: .leading, spacing: 0) {
                // DR-46 — the find row sits above the scroll (Clusters' reason: a lazy row scrolled away is released).
                if findOpen {
                    PageFindRow(text: $findText, isOpen: $findOpen, prompt: Copy.Projects.find)
                        .padding(EdgeInsets(top: 0, leading: ListInsets.of(style).leading, bottom: CicadaTheme.spacingSM,
                                            trailing: ListInsets.of(style).trailing))
                }
                ScrollView {
                    LazyVStack(alignment: .leading,
                               spacing: style == .triage ? CicadaTheme.scaled(RowMetrics.twoLineGap) : 0) {
                        switch state {
                        case .loading:
                            ListSkeleton(message: Copy.Projects.gathering)
                        case .failed(let message):
                            ListErrorCard(title: Copy.Projects.loadFailedTitle, message: message, retry: retry)
                        case .empty:
                            EmptyStateView(title: Copy.Projects.emptyTitle, message: Copy.Projects.emptyMessage)
                        case .tabEmpty:
                            note(tab == .quiet ? Copy.Projects.noneQuiet : Copy.Projects.noneActive)
                        case .noMatch:
                            note(Copy.Projects.noMatch(query.trimmingCharacters(in: .whitespaces)))
                        case .list:
                            ForEach(lines) { line in
                                ProjectRowView(line: line, style: style, today: today, people: people[line.id] ?? [],
                                               selected: line.id == openId) { open(line.id) }
                                    .id(line.id)
                            }
                        }
                    }
                    .padding(ListInsets.of(style))
                }
                .onChange(of: openId) { _, id in
                    guard let id else { return }
                    Instant.run { proxy.scrollTo(id) }
                }
            }
        }
        .listKeys(move: move, enter: {
            guard openId != nil else { return false }
            focusDetail()
            return true
        }, escape: escape)
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.detailBodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.scaled(10))
    }
}

/// One project (R-PP7). The whole row opens it; the chevron is its visible twin, outside the row's button (a button
/// nested in a button is two targets for one click). Ages and counts are tabular (DR-21); ids only in `.help` (DR-54).
struct ProjectRowView: View {
    let line: ProjectLine
    let style: ColumnPlan.ListStyle
    let today: ISODay
    let people: [PersonMark]
    let selected: Bool
    let action: () -> Void

    var body: some View {
        HStack(spacing: CicadaTheme.scaled(10)) {
            Button(action: action) { content }
                .buttonStyle(.cicadaPlain)
                .accessibilityLabel(ProjectsModel.accessibilityLabel(line))
                .accessibilityAddTraits(selected ? [.isSelected] : [])
            if style == .wide {
                IconButton(systemName: "chevron.right", help: Copy.Projects.openHelp, action: action)
            }
        }
        .listRowSurface(height: ListRowSurface.height(style), selected: selected)
    }

    private var indent: CGFloat { CicadaTheme.scaled(CGFloat(line.depth) * (style == .wide ? 16 : 12)) }
    private var tertiary: Color { selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary }

    @ViewBuilder
    private var content: some View {
        let row = line.row
        let age = ProjectsModel.age(row, today: today)
        let bar = ProjectsModel.bar(row, today: today)
        let barHelp = Copy.Projects.barHelp(planned: row.planned, progress: row.progress)
        switch style {
        case .wide:
            HStack(spacing: CicadaTheme.scaled(10)) {
                TypeDot(type: .project).padding(.leading, indent)
                Text(row.name)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .frame(width: max(CicadaTheme.scaled(220) - indent, 0), alignment: .leading)
                Text(ProjectsModel.nowLine(line, today: today))
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), alignment: .leading)
                Spacer(minLength: 0)
                ProgressBarView(span: bar, width: 64, help: barHelp)
                Text(ProjectsModel.nextLine(line, today: today))
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(tertiary)
                    .lineLimit(1)
                    .frame(width: CicadaTheme.scaled(200), alignment: .leading)
                PeopleMarks(people: people, knockout: selected ? CicadaTheme.bgSelected : CicadaTheme.bgBase)
                    .frame(width: CicadaTheme.scaled(64), alignment: .trailing)
                Text(ProjectsModel.questions(row) ?? "")
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(tertiary)
                    .frame(width: CicadaTheme.scaled(74), alignment: .trailing)
                Text(age.text)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(tertiary)
                    .frame(width: CicadaTheme.scaled(40), alignment: .trailing)
                    .help(age.help)
            }
        case .triage:
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(5)) {
                HStack(spacing: CicadaTheme.scaled(10)) {
                    TypeDot(type: .project).padding(.leading, indent)
                    Text(row.name)
                        .font(selected ? CicadaTheme.rowFont : CicadaTheme.bodyFont)
                        .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    Text(age.text).font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(tertiary).help(age.help)
                }
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressBarView(span: bar, width: 40, help: barHelp)
                    Text(ProjectsModel.shortLine(line, today: today))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(tertiary)
                        .lineLimit(1)
                }
                .padding(.leading, indent + CicadaTheme.scaled(18))
            }
        case .titles, .hidden:
            HStack(spacing: CicadaTheme.scaled(10)) {
                TypeDot(type: .project).padding(.leading, indent)
                Text(row.name)
                    .font(selected ? CicadaTheme.rowFont : CicadaTheme.bodyFont)
                    .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .help(row.name)
                Spacer(minLength: 0)
            }
        }
    }
}

/// §3.8 / R-PP9 — the mini bar: `progressFill` from the first moment to today on the `bgBadge` track; with no plan,
/// the fill and a dashed open end, never a grey remainder. Solid, never a gradient; its words are its `.help` and its
/// accessibility label, since the track itself is not held to 3:1 (§3.8, disclosed).
struct ProgressBarView: View {
    let span: ProgressSpan
    let width: CGFloat
    let help: String

    var body: some View {
        let w = CicadaTheme.scaled(width)
        let h = CicadaTheme.scaled(4)
        let filled = max(h, w * CGFloat(span.fill))
        ZStack(alignment: .leading) {
            if span.planned {
                Capsule().fill(CicadaTheme.bgBadge)
            } else {
                MidLine()
                    .stroke(CicadaTheme.progressOpenEnd, style: StrokeStyle(lineWidth: 2, dash: [3, 2]))
                    .padding(.leading, filled + 2)
            }
            Capsule().fill(CicadaTheme.progressFill).frame(width: filled)
        }
        .frame(width: w, height: h)
        .help(help)
        .accessibilityElement()
        .accessibilityLabel(help)
    }
}

/// A horizontal line through the middle of its frame — the open end, and a quiet thread's dashed tail.
struct MidLine: Shape {
    func path(in rect: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: rect.minX, y: rect.midY))
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
        }
    }
}

/// R-PP7 — up to three people as initials in neutral circles, overlapped and knocked out of the row's own fill.
struct PeopleMarks: View {
    let people: [PersonMark]
    let knockout: Color

    var body: some View {
        HStack(spacing: -CicadaTheme.scaled(4)) {
            ForEach(people) { person in
                Text(person.initials)
                    .font(CicadaTheme.font(size: 9, weight: .medium))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(20), height: CicadaTheme.scaled(20))
                    .background(Circle().fill(CicadaTheme.bgButton))
                    .background(Circle().fill(knockout).padding(-2))
                    .help(person.name)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(people.isEmpty ? "" : Copy.Projects.people(people.map(\.name)))
    }
}
