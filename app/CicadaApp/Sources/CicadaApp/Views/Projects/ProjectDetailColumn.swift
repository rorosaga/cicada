import SwiftUI

/// §5.3 STATE 1 — one project beside the list, top to bottom (the approved mock): the heading (DR-16's H1 role), the
/// band's header line and the band (Task 3), then the story in one scroll — Now, Lately, Plan, Backlog (G150),
/// Around this project (R-PP13), each collapsible and remembered per viewer (DR-39). One selection (R-PP11) rings the band's mark and
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
    let openBacklogItem: String?
    let onShowList: () -> Void
    let onClose: () -> Void
    let onEscape: () -> Void
    let openProject: (String) -> Void
    let openEntity: (String) -> Void
    let openItem: (String) -> Void

    @Environment(ProjectsCache.self) private var cache
    @Environment(ProvenanceRouter.self) private var provenance
    @Environment(Store.self) private var store
    @Environment(AppRouter.self) private var router
    @Environment(BacklogCache.self) private var backlogCache
    /// DR-39 — which sections this viewer folded, remembered (a convenience, so `UserDefaults`).
    @AppStorage("cicada.projects.collapsed") private var collapsedRaw = ""
    @State private var selection: ProjectKey?
    @State private var scrollToken = 0
    @State private var bandWidth: CGFloat = 0
    @FocusState private var bandFocused: Bool
    /// R-PP21 — the Log field; L focuses it.
    @FocusState private var logFocused: Bool
    /// Set by M, the menu and "No plan yet — Add a milestone" to open the Plan's add field; the Plan clears it once
    /// the field is open. A flag, not a counter: the story is a lazy stack (R-FA3), so a Plan below a long Lately is
    /// often built only after the request, with the request already in its initial value, and a counter's
    /// `.onChange` never fires then — the section reads the flag on appear too (final review, finding 1).
    @State private var addPending = false
    /// A scroll target that is not a selection (the Plan's section, for M).
    @State private var pendingScroll: String?
    /// R-PP23 — the Plan's Rename or Add field is open, so a letter is typing, not a key.
    @State private var planEditing = false
    /// G150 — the backlog's add fields are open, so a letter is typing, not a key.
    @State private var backlogEditing = false
    /// R-FA2 — the story's derivation, built off the main actor. The last value for the same project keeps painting
    /// while a newer one builds (never blank); the skeleton shows only before the first one.
    @State private var derived: ProjectDerived?
    /// R-PP26 — Resume's view model, one for the column now that Lately's rows are separate lazy children (R-FA3).
    @State private var conversations = ConversationsViewModel()

    /// R-FA2 — the column re-derives exactly when the project, the viewer's day or the cached payload moved.
    private var deriveKey: ProjectDerived.Key {
        .init(projectId: projectId, today: today, revision: cache.revision(projectId))
    }

    /// R-PP20 — Sleep is writing: every write control waits, its reason in `.help` (DR-41).
    private var blocked: Bool { ProjectWriteGate.blocked(store.status.value) }
    /// R-PP23 — a field of this column is being typed in; L · M · D stand aside.
    private var typing: Bool { logFocused || planEditing || backlogEditing }

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
            if let t = cache.display(projectId), let d = derived, d.key.projectId == projectId {
                content(t, d)
            } else if cache.display(projectId) != nil {
                // A timeline is here but its first derivation is still building (R-FA2): the first-open skeleton.
                header(name: row?.name ?? "", oneLiner: row?.oneLiner ?? "", parent: row?.parent)
                ListSkeleton(message: Copy.Projects.reading).padding(.top, CicadaTheme.spacingLG)
                Spacer(minLength: 0)
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
        // R-PP23 / DR-68 — L · M · D, the Inbox's O / L precedent (key presses on the focused column, never menu key
        // equivalents), and like its `field == nil`, never while a field of this column is being typed in. A key
        // never animates (DR-60).
        .onKeyPress(KeyEquivalent("l")) {
            guard cache.display(projectId) != nil, !blocked, !typing else { return .ignored }
            logFocused = true
            return .handled
        }
        .onKeyPress(KeyEquivalent("m")) {
            guard cache.display(projectId) != nil, !blocked, !typing else { return .ignored }
            Instant.run { requestAdd() }
            return .handled
        }
        .onKeyPress(KeyEquivalent("d")) { markSelectedDone() ? .handled : .ignored }
        .focusable()
        .focusEffectDisabled()
        .onExitCommand { onEscape() }
        .task(id: projectId) {
            selection = nil
            await cache.refreshTimeline(projectId)
            // R-B19 — a folded Backlog section still says "n open": `section(_:…)` builds its body only when open,
            // so the section's own `.task` never runs while it is folded.
            await backlogCache.refreshList(projectId)
        }
        // R-FA2 — derive off the main actor, only when the project, the day or the cached payload moved.
        .task(id: deriveKey) {
            guard let t = cache.display(projectId) else { return }
            let key = deriveKey
            let value = await ProjectDerived.make(t, key: key)
            guard !Task.isCancelled else { return }
            derived = value
        }
    }

    @ViewBuilder
    private func content(_ t: ProjectTimeline, _ d: ProjectDerived) -> some View {
        let state = d.state
        // R-FA2's one exception: the band depends on its measured width and scales with its marks, never with
        // participants, so it stays here rather than re-deriving off-main on every resize.
        let band = BandLayout.make(t, state: state, width: max(bandWidth - 2 * CicadaTheme.scaled(BandLayout.inset), 1),
                                   today: today)
        let names = store.entityNames
        let readerEpisode = provenance.isPresented ? provenance.current?.episode : nil
        let sectionGap = CicadaTheme.scaled(26)
        header(name: t.project.name, oneLiner: t.project.oneLiner, parent: t.project.parent)
        bandHeader(band, progress: state.progress)
        bandView(band, t)
        ScrollViewReader { proxy in
            ScrollView {
                // R-FA3 — one lazy stack whose children are every section AND every Lately label and row, so a long
                // story builds only what is on screen; the gaps the nested stacks gave ride on each child's padding.
                LazyVStack(alignment: .leading, spacing: 0) {
                    ProjectLogField(projectName: t.project.name, today: today, blocked: blocked, focus: $logFocused,
                                    save: { text, status, when in await write(.log(text: text, status: status, when: when)) },
                                    undo: { claimId in _ = await write(.withdraw(claimId: claimId)) })
                        .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth))
                    section(.now, title: Copy.Projects.now, meta: Copy.Projects.inMotionCount(t.now.threads.count)) {
                        ProjectNowSection(timeline: t, state: state, today: today, selection: selection,
                                          followups: ProjectStory.followups(store.visibleInbox),
                                          pick: { pickRow($0, in: t) }, openEntity: openEntity,
                                          showSource: { show($0, in: t) },
                                          openInbox: { router.routeToInboxItem($0) },
                                          settle: { id, status in Task { await write(.settle(claimId: id, status: status)) } },
                                          writesBlocked: blocked)
                    }
                    .padding(.top, sectionGap)
                    let latelyOpen = !collapsed.contains(.lately)
                    ProjectSectionHeader(title: Copy.Projects.lately, meta: Copy.Projects.happeningsCount(d.happenings),
                                         isOpen: latelyOpen) { setOpen(.lately, !latelyOpen) }
                        .padding(.top, sectionGap)
                    if latelyOpen {
                        ForEach(ProjectStory.latelyEntries(d.groups)) { entry in
                            latelyEntry(entry, t: t, state: state, names: names, readerEpisode: readerEpisode)
                                .padding(.top, entry.topPadding)
                        }
                        if let foot = ProjectStory.createdLine(t.items, today: today) {
                            ProjectLatelyFoot(text: foot).padding(.top, CicadaTheme.spacingMD)
                        }
                    }
                    section(.plan, title: Copy.Projects.plan,
                            meta: state.planned ? Copy.Projects.doneOf(state.progress) : Copy.Projects.noPlanYet) {
                        ProjectPlanSection(timeline: t, today: today, selection: selection, names: names,
                                           pick: { pickRow($0, in: t) }, showSource: { show($0, in: t) },
                                           markDone: { slug in
                                               Task { await write(.changeMilestone(slug: slug, change: MilestoneChange(status: "done"))) }
                                           },
                                           rename: { slug, name in
                                               Task { await write(.changeMilestone(slug: slug, change: MilestoneChange(name: name))) }
                                           },
                                           add: { name, target in Task { await write(.addMilestone(name: name, target: target)) } },
                                           addPending: $addPending, writesBlocked: blocked,
                                           onEditingChange: { planEditing = $0 })
                    }
                    .padding(.top, sectionGap)
                    .id(ProjectScroll.planSection)
                    // G150 (R-B19) — after Plan: the plan is what is dated, the backlog what is kept for later.
                    section(.backlog, title: Copy.Projects.Backlog.title,
                            meta: backlogCache.list(projectId)
                                .map { Copy.Projects.Backlog.openCount(BacklogModel.openCount($0)) } ?? "") {
                        ProjectBacklogSection(projectId: projectId, today: today, openItem: openBacklogItem,
                                              writesBlocked: blocked, open: openItem,
                                              onEditingChange: { backlogEditing = $0 })
                    }
                    .padding(.top, sectionGap)
                    .id("section.backlog")
                    if !t.cluster.groups.isEmpty || !t.cluster.alsoUses.isEmpty {
                        section(.around, title: Copy.Projects.around, meta: "") {
                            ProjectAroundSection(cluster: t.cluster, today: today, partial: t.partial, openCard: openCard,
                                                 openEntity: openEntity, openProject: openProject,
                                                 openSource: { provenance.open($0) })
                        }
                        .padding(.top, sectionGap)
                    }
                }
                .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), alignment: .leading)
                .padding(.top, CicadaTheme.spacingSM)
                .padding(.bottom, CicadaTheme.scaled(72))
                // Every chip below names its conversation's agent ("Claude Code replied") with no fetch per chip.
                .environment(\.evidenceDocIndex, d.docIndex)
            }
            .onChange(of: scrollToken) { _, _ in
                let target = pendingScroll ?? selection?.id
                pendingScroll = nil
                guard let target else { return }
                let steps = ProjectScroll.steps(to: target)
                guard steps.count > 1 else {
                    Instant.run { proxy.scrollTo(target, anchor: .center) }
                    return
                }
                // A milestone: land the Plan first so the lazy stack builds it, then centre the row a turn later.
                Instant.run { proxy.scrollTo(steps[0], anchor: .top) }
                Task { @MainActor in
                    await Task.yield()
                    Instant.run { proxy.scrollTo(target, anchor: .center) }
                }
            }
        }
    }

    /// R-FA3 — one Lately entry: a day label, or a row whose id IS its scroll id (`ProjectKey.item`), so a band pick
    /// lands on a row the lazy stack has not built yet.
    @ViewBuilder
    private func latelyEntry(_ entry: ProjectStory.LatelyEntry, t: ProjectTimeline, state: ProjectState.Output,
                             names: EntityNames, readerEpisode: String?) -> some View {
        switch entry {
        case .label(let group, _):
            ProjectLatelyLabel(group: group)
        case .item(let item):
            ProjectLatelyRow(item: item, timeline: t, state: state, today: today, selection: selection,
                             readerEpisode: readerEpisode, names: names, pick: { pickRow($0, in: t) },
                             openEntity: openEntity, showSource: { show($0, in: t) },
                             closeReader: { provenance.close() },
                             withdraw: { id in Task { await write(.withdraw(claimId: id)) } },
                             writesBlocked: blocked, conversations: conversations)
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

    // MARK: - Writes (R-PP19…R-PP23)

    /// R-PP19 — every write: a `ProjectWrite` through `Store.perform` (paint, send, roll back with a toast), then the
    /// cache asks again for what the server now holds (a 304 costs nothing).
    @discardableResult
    private func write(_ action: ProjectWrite.Action) async -> ProjectWriteResponse? {
        let w = ProjectWrite(projectId: projectId, action: action, cache: cache, day: today)
        let ok = await store.perform(w)
        if ok { cache.confirm(w.overlayId) }
        await cache.refreshTimeline(projectId)
        await cache.refreshList()
        return ok ? w.result : nil
    }

    /// M, the menu and "No plan yet — Add a milestone": open the Plan and its field, and bring it into view.
    /// Whether the Plan is collapsed, already built, or not yet built by the lazy stack, it opens the field from
    /// `addPending` on appear or on change, so no next-turn special case is needed.
    private func requestAdd() {
        setOpen(.plan, true)
        addPending = true
        pendingScroll = ProjectScroll.planSection
        scrollToken &+= 1
    }

    /// DR-68 (R-PP23) — D marks the selected thread or milestone done, dated today; never while typing, so a "d" in
    /// the Log or a milestone's name stays a letter.
    private func markSelectedDone() -> Bool {
        guard !blocked, !typing, let key = selection, let t = cache.display(projectId) else { return false }
        switch key {
        case .thread(let id):
            guard t.settleableThread(id) != nil else { return false }
            Task { await write(.settle(claimId: id, status: "done")) }
            return true
        case .milestone(let slug):
            guard let m = t.milestones.first(where: { $0.slug == slug }),
                  ProjectPlan.canMarkDone(ProjectPlan.Row(milestone: m, state: ProjectState.milestoneState(m, today: today)))
            else { return false }
            Task { await write(.changeMilestone(slug: slug, change: MilestoneChange(status: "done"))) }
            return true
        case .item:
            return false
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
                    // Both need a project on screen: the header also draws while it is still loading (no dead control).
                    Button(Copy.Projects.addMilestone) { requestAdd() }
                        .disabled(blocked || cache.display(projectId) == nil)
                    Button(Copy.Projects.logLabel(name)) { logFocused = true }
                        .disabled(blocked || cache.display(projectId) == nil)
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
                // The mock's "No plan yet — Add a milestone" (R-PP22).
                Text(Copy.Projects.noPlanAdd)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(Copy.Projects.barHelp(planned: false, progress: progress))
                TextButton(title: Copy.Projects.addMilestone, keyHint: "M", help: Copy.Projects.addMilestoneHelp) {
                    requestAdd()
                }
                .disabled(blocked)
            }
        }
        .font(CicadaTheme.metaFont)
        .monospacedDigit()
        .frame(height: CicadaTheme.scaled(22))
        .padding(.top, CicadaTheme.scaled(18))
    }
}
