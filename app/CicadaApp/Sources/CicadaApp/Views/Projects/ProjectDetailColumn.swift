import SwiftUI

/// §5.3 STATE 1 — one project beside the list, top to bottom (the approved mock): the heading (DR-16's H1 role), the
/// band's header line and the band (Task 3), then the story in one scroll — Now, Lately, Plan, Around this project
/// (R-PP13), each collapsible and remembered per viewer (DR-39). One selection (R-PP11) rings the band's mark and
/// marks the section row; a pick from the band scrolls its row into view (DR-30). It reads `ProjectsCache` (R-PP3): a
/// skeleton on a first open, words when the project is gone, the error card with Retry — never a blank (DR-43).
struct ProjectDetailColumn: View {
    let projectId: String
    let row: ProjectRow?
    let parentName: String?
    let today: ISODay
    let gutter: CGFloat
    let hiddenListCount: Int?
    let openCard: String?
    let onShowList: () -> Void
    let onClose: () -> Void
    let onEscape: () -> Void
    let openProject: (String) -> Void
    let openEntity: (String) -> Void

    @Environment(ProjectsCache.self) private var cache
    @Environment(ProvenanceRouter.self) private var provenance
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    /// DR-39 — which sections this viewer folded, remembered (a convenience, so `UserDefaults`).
    @AppStorage("cicada.projects.collapsed") private var collapsedRaw = ""
    @State private var selection: ProjectKey?
    @State private var scrollToken = 0
    @State private var bandWidth: CGFloat = 0
    @FocusState private var bandFocused: Bool

    private var collapsed: Set<ProjectSection> {
        Set(collapsedRaw.split(separator: ",").compactMap { ProjectSection(rawValue: String($0)) })
    }

    private func setOpen(_ section: ProjectSection, _ open: Bool) {
        var c = collapsed
        if open { c.remove(section) } else { c.insert(section) }
        collapsedRaw = c.map(\.rawValue).sorted().joined(separator: ",")
    }

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
        bandView(band, t)
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(26)) {
                    sections(t, state: state)
                }
                .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), alignment: .leading)
                .padding(.top, CicadaTheme.spacingSM)
                .padding(.bottom, CicadaTheme.scaled(72))
                // Every chip below names its conversation's agent ("Claude Code replied") with no fetch per chip.
                .environment(\.evidenceDocIndex, ProjectSource.docIndex(t))
            }
            .onChange(of: scrollToken) { _, _ in
                guard let key = selection else { return }
                Instant.run { proxy.scrollTo(key.id, anchor: .center) }
            }
        }
    }

    @ViewBuilder
    private func sections(_ t: ProjectTimeline, state: ProjectState.Output) -> some View {
        let names = store.entityNames
        let readerEpisode = provenance.isPresented ? provenance.current?.episode : nil
        section(.now, title: Copy.Projects.now, meta: Copy.Projects.inMotionCount(t.now.threads.count)) {
            ProjectNowSection(timeline: t, state: state, today: today, selection: selection,
                              followups: ProjectStory.followups(store.visibleInbox),
                              pick: { pickRow($0, in: t) }, openEntity: openEntity, showSource: { show($0, in: t) },
                              openInbox: { router.routeToInboxItem($0) })
        }
        section(.lately, title: Copy.Projects.lately,
                meta: Copy.Projects.happeningsCount(t.items.filter { $0.kind != "created" }.count)) {
            ProjectLatelySection(timeline: t, state: state, today: today, selection: selection,
                                 readerEpisode: readerEpisode, names: names, pick: { pickRow($0, in: t) },
                                 openEntity: openEntity, showSource: { show($0, in: t) },
                                 closeReader: { provenance.close() })
        }
        section(.plan, title: Copy.Projects.plan,
                meta: state.planned ? Copy.Projects.doneOf(state.progress) : Copy.Projects.noPlanYet) {
            ProjectPlanSection(timeline: t, today: today, selection: selection, names: names,
                               pick: { pickRow($0, in: t) }, showSource: { show($0, in: t) })
        }
        if !t.cluster.groups.isEmpty || !t.cluster.alsoUses.isEmpty {
            section(.around, title: Copy.Projects.around, meta: "") {
                ProjectAroundSection(cluster: t.cluster, today: today, partial: t.partial, openCard: openCard,
                                     openEntity: openEntity, openProject: openProject,
                                     openSource: { provenance.open($0) })
            }
        }
    }

    private func section<Body: View>(_ s: ProjectSection, title: String, meta: String,
                                     @ViewBuilder body: () -> Body) -> some View {
        let open = !collapsed.contains(s)
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ProjectSectionHeader(title: title, meta: meta, isOpen: open) { setOpen(s, !open) }
            if open { body() }
        }
    }

    private func bandView(_ band: BandLayout, _ t: ProjectTimeline) -> some View {
        ProjectBandView(layout: band, selected: selection, isFocused: bandFocused) { pickMark($0, in: t) }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background {
                GeometryReader { geo in
                    Color.clear
                        .onAppear { bandWidth = geo.size.width }
                        .onChange(of: geo.size.width) { _, w in bandWidth = w }
                }
            }
            .padding(.top, CicadaTheme.scaled(6))
            .focusable()
            .focused($bandFocused)
            .focusEffectDisabled()
            // DR-68 — ← / → step along the band; ⏎ opens the selection's words in the Reader. Keys never animate.
            .onMoveCommand { direction in
                switch direction {
                case .left: step(band, -1)
                case .right: step(band, 1)
                default: break
                }
            }
            .onKeyPress(.return) {
                guard let key = selection else { return .ignored }
                show(key, in: t)
                return .handled
            }
    }

    // MARK: - Selection (R-PP11)

    /// A mark on the band: select it, open its section if folded, bring its row into view. The band takes the keys
    /// (R-PP23), so ←/→ walk on from the clicked mark and ⏎ opens its words — a mark's `Button` does not take focus
    /// on a click by itself.
    private func pickMark(_ key: ProjectKey, in t: ProjectTimeline) {
        pickRow(key, in: t)
        bandFocused = true
        guard selection == key else { return }
        if collapsed.contains(key.section) { setOpen(key.section, true) }
        scrollToken &+= 1
    }

    private func step(_ band: BandLayout, _ delta: Int) {
        Instant.run { selection = band.step(from: selection, delta: delta) }
        if let key = selection, collapsed.contains(key.section) { setOpen(key.section, true) }
        scrollToken &+= 1
    }

    /// A pick toggles; with the Reader open, a pick citing the same conversation re-lands it, any other closes it
    /// (DR-29).
    private func pickRow(_ key: ProjectKey, in t: ProjectTimeline) {
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

    /// "Show in conversation ›" and the band's ⏎: the Reader as the third column, on the cited words.
    private func show(_ key: ProjectKey, in t: ProjectTimeline) {
        guard let target = ProjectSource.target(for: key, in: t, projectId: projectId) else { return }
        // DR-60 — ⏎ is a keyboard path and never animates; a click on the link reads the same, instantly.
        Instant.run {
            selection = key
            provenance.open(target)
        }
    }

    // MARK: - Heading

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
                Menu {
                    Button(Copy.Projects.openCard) { openEntity(projectId) }
                } label: {
                    Image(systemName: "ellipsis").font(CicadaTheme.icon(.list))
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .fixedSize()
                .help(Copy.Projects.moreHelp)
                .accessibilityLabel(Copy.Projects.moreHelp)
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
                Text(oneLiner).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(2)
            }
        }
        .padding(.top, CicadaTheme.spacingSM)
    }

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
