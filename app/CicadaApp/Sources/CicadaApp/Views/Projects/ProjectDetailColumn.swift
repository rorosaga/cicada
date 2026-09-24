import SwiftUI

/// §5.3 STATE 1 — one project beside the list. The heading is DR-16's H1 role (`displayFont(size: 22)`): a
/// sub-project's "Part of <parent> ›" above it, the name with its "Project" tag, the one-liner; the column's controls
/// are "‹ N projects" when DR-27 hid the list, and Close ×. Under it, the band's header line — "Since Jul 15" and "1 of
/// 4 done" (or "No plan yet") — and the band itself from Task 3. It reads `ProjectsCache` (R-PP3): a skeleton on a
/// first open, words when the project is gone, the error card with Retry — never a blank (DR-43).
struct ProjectDetailColumn: View {
    let projectId: String
    let row: ProjectRow?
    let parentName: String?
    let today: ISODay
    let gutter: CGFloat
    let hiddenListCount: Int?
    let onShowList: () -> Void
    let onClose: () -> Void
    let onEscape: () -> Void
    let openProject: (String) -> Void

    @Environment(ProjectsCache.self) private var cache
    @Environment(ProvenanceRouter.self) private var provenance
    /// R-PP11 — one selection for the band and (Task 4) the sections.
    @State private var selection: ProjectKey?
    @State private var bandWidth: CGFloat = 0
    @FocusState private var bandFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let t = cache.display(projectId) {
                content(t)
            } else {
                header(name: row?.name ?? "", oneLiner: row?.oneLiner ?? "", parent: row?.parent)
                switch cache.phase(projectId) {
                case .gone:
                    Text(Copy.Projects.gone)
                        .font(CicadaTheme.detailBodyFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .padding(.top, CicadaTheme.spacingLG)
                case .failed(let message):
                    ListErrorCard(title: Copy.Projects.projectFailedTitle, message: message) {
                        Task { await cache.refreshTimeline(projectId) }
                    }
                default:
                    ListSkeleton(message: Copy.Projects.reading).padding(.top, CicadaTheme.spacingLG)
                }
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.detailMaxWidth), maxHeight: .infinity, alignment: .topLeading)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .padding(.horizontal, gutter)
        // R-DG11's reason — focus inside the column still reaches the page's Esc order (DR-28).
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { onEscape() }
        .task(id: projectId) {
            selection = nil
            await cache.refreshTimeline(projectId)
        }
    }

    @ViewBuilder
    private func content(_ t: ProjectTimeline) -> some View {
        let state = ProjectState.state(ProjectState.Input(t), today: today)
        let band = BandLayout.make(t, state: state, width: max(bandWidth - 2 * CicadaTheme.scaled(BandLayout.inset), 1),
                                   today: today)
        header(name: t.project.name, oneLiner: t.project.oneLiner, parent: t.project.parent)
        bandHeader(band, progress: state.progress)
        ProjectBandView(layout: band, selected: selection, isFocused: bandFocused) { pick($0, in: t) }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background { GeometryReader { geo in Color.clear.onAppear { bandWidth = geo.size.width }
                .onChange(of: geo.size.width) { _, w in bandWidth = w } } }
            .padding(.top, CicadaTheme.scaled(6))
            .focusable()
            .focused($bandFocused)
            .focusEffectDisabled()
            // DR-68 — ← / → step along the band; ⏎ opens the selection's words in the Reader. Keys never animate.
            .onMoveCommand { direction in
                switch direction {
                case .left: Instant.run { selection = band.step(from: selection, delta: -1) }
                case .right: Instant.run { selection = band.step(from: selection, delta: 1) }
                default: break
                }
            }
            .onKeyPress(.return) {
                guard let key = selection, let target = ProjectSource.target(for: key, in: t, projectId: projectId) else {
                    return .ignored
                }
                Instant.run { provenance.open(target) }
                return .handled
            }
        Spacer(minLength: 0)
    }

    /// R-PP11 — a pick rings the mark (a second pick clears it) and gives the band the keys (R-PP23). With the Reader
    /// open, a pick that cites the same conversation re-lands it in place; any other closes it (DR-29).
    private func pick(_ key: ProjectKey, in t: ProjectTimeline) {
        bandFocused = true
        Instant.run {
            selection = selection == key ? nil : key
            guard provenance.isPresented, let chosen = selection else { return }
            if let target = ProjectSource.target(for: chosen, in: t, projectId: projectId),
               target.episode == provenance.current?.episode {
                provenance.refocus(target)
            } else {
                provenance.close()
            }
        }
    }

    private func header(name: String, oneLiner: String, parent: String?) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                if let n = hiddenListCount {
                    TextButton(title: Copy.Projects.projectsBack(n), help: Copy.Lists.showList, action: onShowList)
                        .padding(.leading, -CicadaTheme.scaled(10))
                }
                if let parent, let parentName {
                    InlineLink(title: Copy.Projects.partOf(parentName), help: Copy.Projects.openHelp) { openProject(parent) }
                }
                Spacer(minLength: 0)
                IconButton(systemName: "xmark", help: Copy.Projects.closeHelp, action: onClose)
            }
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.scaled(10)) {
                Text(name)
                    .font(CicadaTheme.displayFont(size: 22))
                    .tracking(CicadaTheme.displayTracking(size: 22))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .accessibilityAddTraits(.isHeader)
                Tag(text: Copy.Projects.tag, dot: CicadaTheme.entityColor(for: .project))
            }
            if !oneLiner.isEmpty {
                Text(oneLiner)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(2)
            }
        }
        .padding(.top, CicadaTheme.spacingSM)
    }

    /// The band's header line (the mock): where the green starts, and "N of M done" in words (R-PJ11: never a
    /// percentage) — or "No plan yet", which Task 5 follows with "Add a milestone". It reads its words from the band,
    /// so the header line and the bar can never disagree (R-PP9).
    private func bandHeader(_ band: BandLayout, progress: ProjectProgress) -> some View {
        HStack(spacing: CicadaTheme.scaled(6)) {
            Text(band.since).foregroundStyle(CicadaTheme.textTertiary)
            Spacer(minLength: 0)
            if let words = band.progressWords {
                Text(words)
                    .fontWeight(.medium)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .help(Copy.Projects.barHelp(planned: true, progress: progress))
            } else {
                Text(Copy.Projects.noPlanYet)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(Copy.Projects.barHelp(planned: false, progress: progress))
            }
        }
        .font(CicadaTheme.metaFont)
        .monospacedDigit()
        .frame(height: CicadaTheme.scaled(22))
        .padding(.top, CicadaTheme.scaled(18))
    }
}
