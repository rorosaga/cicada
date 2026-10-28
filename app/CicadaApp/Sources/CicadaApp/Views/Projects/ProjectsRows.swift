import SwiftUI

/// What the list column says before it has rows to draw, in precedence order (DR-43, DR-50).
enum ProjectsListState: Equatable {
    case loading, failed(String), empty, emptyMine, tabEmpty, noMatch, list

    /// `suggestions` (ruling 45): none of the person's own yet, but Cicada suggests some — say so above the fold.
    static func of(phase: ProjectsCache.Phase, hasList: Bool, rows: Int, suggestions: Int = 0, lines: Int,
                   finding: Bool) -> ProjectsListState {
        if !hasList {
            if case .failed(let message) = phase { return .failed(message) }
            return .loading
        }
        if rows == 0 { return suggestions > 0 ? .emptyMine : .empty }
        if lines == 0 { return finding ? .noMatch : .tabEmpty }
        return .list
    }
}

/// Projects v2 (2026-10-19) / §5.3 — the list in its three styles: two lines at rest (name over what it is, where it
/// stands at the end), two lines beside a project (name over where it stands), titles beside a project and the Reader.
/// Current ends with a static *Gone quiet* label over its rows (Projects v3: no folds, decision 17); Past carries year
/// labels, a find field and "Show more". Selection is `bgSelected`, never the accent (DR-22, `SelectionTintLintTests`).
struct ProjectsListColumn: View {
    let entries: [ProjectsEntry]
    let style: ColumnPlan.ListStyle
    let today: ISODay
    let state: ProjectsListState
    let tab: ProjectsTab
    let query: String
    @Binding var findOpen: Bool
    @Binding var findText: String
    let openId: String?
    let tap: (ProjectLine) -> Void
    let showMore: () -> Void
    let move: (Int) -> Void
    var side: (Int) -> Void = { _ in }
    let focusDetail: () -> Void
    let escape: () -> Void
    let retry: () -> Void
    /// Ruling 45 / decision 9 — Suggested as one line, drawn after the rows (and after the empty words when none are
    /// the person's).
    var suggestedFold: () -> AnyView = { AnyView(EmptyView()) }

    var body: some View {
        ScrollViewReader { proxy in
            VStack(alignment: .leading, spacing: 0) {
                // DR-46 — the find row sits above the scroll (Clusters' reason: a lazy row scrolled away is released).
                // Past is the archive, so its field is always there; Current opens one on ⌘F.
                // The titles column beside the Reader is too narrow for a field: it would spill onto the project.
                if tab == .past && style != .titles && style != .hidden {
                    CicadaSearchField(text: $findText, prompt: Copy.Projects.findPast)
                        .padding(findInsets)
                } else if findOpen {
                    PageFindRow(text: $findText, isOpen: $findOpen, prompt: Copy.Projects.find)
                        .padding(findInsets)
                }
                ScrollView {
                    LazyVStack(alignment: .leading,
                               spacing: style == .titles || style == .hidden ? 0 : CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                        switch state {
                        case .loading:
                            ListSkeleton(message: Copy.Projects.gathering)
                        case .failed(let message):
                            ListErrorCard(title: Copy.Projects.loadFailedTitle, message: message, retry: retry)
                        case .empty:
                            EmptyStateView(systemImage: "point.topleft.down.to.point.bottomright.curvepath",
                                           title: Copy.Projects.emptyTitle, message: Copy.Projects.emptyMessage)
                        case .emptyMine:
                            note(Copy.ProjectsMine.emptyMineMessage)
                            suggestedFold()
                        case .tabEmpty:
                            note(tab == .past ? Copy.Projects.nonePast : Copy.Projects.noneCurrent)
                            suggestedFold()
                        case .noMatch:
                            note(Copy.Projects.noMatch(query.trimmingCharacters(in: .whitespaces)))
                        case .list:
                            ForEach(entries) { entry in
                                self.entry(entry).id(entry.id)
                            }
                            suggestedFold()
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
        .clipped()   // nothing in the list column ever draws over the project beside it
        .listKeys(move: move, side: side, enter: {
            guard openId != nil else { return false }
            focusDetail()
            return true
        }, escape: escape)
    }

    private var findInsets: EdgeInsets {
        EdgeInsets(top: 0, leading: ListInsets.of(style).leading, bottom: CicadaTheme.spacingSM,
                   trailing: ListInsets.of(style).trailing)
    }

    @ViewBuilder
    private func entry(_ entry: ProjectsEntry) -> some View {
        switch entry {
        case .line(let line):
            ProjectRowView(line: line, style: style, today: today, selected: line.id == openId,
                           action: { tap(line) })
        case .quiet:
            SectionLabel(Copy.ProjectsOpen.goneQuiet)
                .padding(.horizontal, CicadaTheme.scaled(10))
                .padding(.top, CicadaTheme.scaled(14))
                .padding(.bottom, CicadaTheme.scaled(2))
                .help(Copy.Projects.fadingHelp)
        case .year(let label):
            SectionLabel(label)
                .padding(.horizontal, CicadaTheme.scaled(10))
                .padding(.top, CicadaTheme.scaled(14))
                .padding(.bottom, CicadaTheme.scaled(2))
        case .more(let left):
            TextButton(title: Copy.Projects.showMore(min(left, ProjectsModel.pageSize), left: left),
                       help: Copy.Projects.showMoreHelp, action: showMore)
                .padding(.top, CicadaTheme.spacingSM)
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.detailBodyFont)
            .foregroundStyle(CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.scaled(10))
    }
}

/// One project: the name, what it is in one line, where it stands as one signal (owner 2026-10-19). A sub-project sits
/// indented under its parent, always shown — no chevron, nothing to fold (Projects v3, decision 9; amends 2026-10-19's
/// "dropdown that moves if I press again", with the owner's newer preference).
struct ProjectRowView: View {
    let line: ProjectLine
    let style: ColumnPlan.ListStyle
    let today: ISODay
    let selected: Bool
    let action: () -> Void

    private var indent: CGFloat { CicadaTheme.scaled(CGFloat(min(line.depth, 2)) * 14) }
    private var tertiary: Color { selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary }

    var body: some View {
        Button(action: action) {
            content.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading).contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityLabel(ProjectsModel.accessibilityLabel(line, today: today))
        .accessibilityAddTraits(selected ? [.isSelected] : [])
        .padding(.leading, indent)
        .listRowSurface(height: ListRowSurface.height(style, twoLineAtRest: true), selected: selected)
    }

    private var name: some View {
        Text(line.row.name)
            .font(CicadaTheme.font(size: 13, weight: selected || style == .wide ? .medium : .regular))
            .foregroundStyle(selected || style == .wide ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .lineLimit(1)
            .help(line.row.name)
    }

    @ViewBuilder
    private var content: some View {
        let second = ProjectsModel.secondLine(line, style: style, selected: selected, today: today)
        switch style {
        case .wide:
            HStack(spacing: CicadaTheme.spacingMD) {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    name
                    if let second {
                        Text(second).font(CicadaTheme.metaFont).foregroundStyle(tertiary).lineLimit(1)
                    }
                }
                Spacer(minLength: CicadaTheme.spacingMD)
                Text(ProjectsModel.standing(line, today: today))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(1)
                    .frame(maxWidth: CicadaTheme.scaled(260), alignment: .trailing)
            }
        case .triage:
            // The open row is only its name: the detail beside it says where it stands.
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                name
                if let second {
                    Text(second).font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(tertiary).lineLimit(1)
                }
            }
        case .titles, .hidden:
            name
        }
    }
}

/// A horizontal line through the middle of its frame — a quiet thread's dashed tail on the band.
struct MidLine: Shape {
    func path(in rect: CGRect) -> Path {
        Path { p in
            p.move(to: CGPoint(x: rect.minX, y: rect.midY))
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
        }
    }
}
