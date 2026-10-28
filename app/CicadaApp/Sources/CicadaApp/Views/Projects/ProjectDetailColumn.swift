import SwiftUI

/// §5.3 STATE 1 — one project beside the list, top to bottom (Projects v3, decisions 9, 10 and 17, owner 2026-10-28):
/// the heading (DR-16's H1 role) with the person's line, ONE line of where it stands and what's next, the band, the Log
/// field, then the open sections in the order the person needs them — Pulse, In motion, Coming up, Timeline — and the
/// knowledge panel beside them: Pages in this project, Conversations, Sources & influences. **No folds** (DR-81 as
/// proposed): a section with nothing in it is not drawn; a section with more than `ProjectOpen.cap` rows ends in
/// "All N", which swaps the card's column to that full list (Esc back) — never an in-place expansion. One selection
/// (R-PP11) rings the band's mark and marks the row; a pick whose row the capped section does not show opens its full
/// list. It reads `ProjectsCache` (R-PP3): a skeleton on a first open, words when the project is gone, the error card
/// with Retry — never a blank (DR-43).
struct ProjectDetailColumn: View {
    let projectId: String
    let row: ProjectRow?
    let parentName: String?
    let today: ISODay
    let gutter: CGFloat
    /// The column's width as the page's column plan gives it (`ColumnPlan.detail`): what the card and the panel fit in.
    /// Read from the plan, never measured from this column's own frame, which grows with what it draws.
    var available: CGFloat = 0
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
    @State private var selection: ProjectKey?
    @State private var scrollToken = 0
    @State private var bandWidth: CGFloat = 0
    @FocusState private var bandFocused: Bool
    /// R-PP21 — the Log field; L focuses it.
    @FocusState private var logFocused: Bool
    /// Set by M, the menu and the header's "Add a milestone" to open Coming up's add field; the section clears it once
    /// the field is open. A flag, not a counter (final review of PJ-5, finding 1): the section reads it on appear too,
    /// and it draws Coming up even while the project plans nothing yet.
    @State private var addPending = false
    /// A scroll target that is not a selection (Coming up, for M).
    @State private var pendingScroll: String?
    /// R-PP23 — Coming up's Rename or Add field is open, so a letter is typing, not a key.
    @State private var planEditing = false
    /// G150 — the backlog's add fields are open, so a letter is typing, not a key.
    @State private var backlogEditing = false
    /// R-FA2 — the story's derivation, built off the main actor. The last value for the same project keeps painting
    /// while a newer one builds (never blank); the skeleton shows only before the first one.
    @State private var derived: ProjectDerived?
    /// R-PP26 — Resume's view model, one for the column.
    @State private var conversations = ConversationsViewModel()
    @State private var addingInfluence = false
    @State private var addingPage = false
    /// Decision 17 — the full list an "All N" opened in place of the sections; Esc or Back returns. Owned by the page,
    /// so its Esc (from whichever column holds the keys) closes the full list before the project (DR-28).
    @Binding var full: ProjectOpen.Full?

    /// R-FA2 — the column re-derives exactly when the project, the viewer's day or the cached payload moved.
    private var deriveKey: ProjectDerived.Key {
        .init(projectId: projectId, today: today, revision: cache.revision(projectId))
    }

    /// R-PP20 — Sleep is writing: every write control waits, its reason in `.help` (DR-41).
    private var blocked: Bool { ProjectWriteGate.blocked(store.status.value) }
    /// R-PP23 — a field of this column is being typed in; L · M · D stand aside.
    private var typing: Bool { logFocused || planEditing || backlogEditing }

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
        .frame(maxWidth: cap, maxHeight: .infinity, alignment: .topLeading)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .padding(.horizontal, gutter)
        .sheet(isPresented: $addingInfluence) {
            AddInfluenceSheet(candidates: pageCandidates) { url, what, entity, how, note in
                Task { await change(.addInfluence(id: projectId, url: url, what: what, entity: entity, how: how,
                                                  note: note)) }
            }
        }
        .sheet(isPresented: $addingPage) {
            AddProjectPageSheet(candidates: pageCandidates.filter { c in
                !(cache.display(projectId)?.pages.contains { $0.id == c.id && !$0.isProposed } ?? false)
            }) { id, name, type in
                Task { await change(.tiePage(id: projectId, entity: id, name: name, type: type, remove: false)) }
            }
        }
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
        // DR-28 — Esc closes the rightmost thing: a full list first (decision 17's "Esc back"), then the page's rule.
        .onExitCommand {
            if full != nil { Instant.run { full = nil } } else { onEscape() }
        }
        .task(id: projectId) {
            selection = nil
            full = nil
            await cache.refreshTimeline(projectId)
            await cache.refreshConversations(projectId)
            // G150 — Coming up reads the open backlog.
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
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                // The page scrolls as one (review of #493): the header, the line and the band ride with the story.
                header(name: t.project.name, oneLiner: t.project.oneLiner, parent: t.project.parent, ref: t.project)
                standingLine(ProjectSummary.make(t, state: state, today: today), t)
                // The band's width is the column's, measured by a flexible zero-height probe (review of #493).
                Color.clear
                    .frame(maxWidth: .infinity, maxHeight: 0)
                    .background {
                        GeometryReader { geo in
                            Color.clear
                                .onAppear { bandWidth = geo.size.width }
                                .onChange(of: geo.size.width) { _, w in bandWidth = w }
                        }
                    }
                bandView(band, t)
                    .padding(.bottom, CicadaTheme.spacingMD)
                HStack(alignment: .top, spacing: CicadaTheme.scaled(ProjectKnowledgeLayout.gap)) {
                LazyVStack(alignment: .leading, spacing: 0) {
                    if let full {
                        fullList(full, t: t, state: state, d: d)
                    } else {
                        sections(t, state: state, d: d)
                    }
                }
                .frame(maxWidth: CicadaTheme.scaled(wide ? ProjectKnowledgeLayout.cardWidth : ProjectLayout.textMaxWidth),
                       alignment: .leading)
                .padding(.top, CicadaTheme.spacingSM)
                .padding(.bottom, wide ? CicadaTheme.scaled(72) : CicadaTheme.spacingLG)
                // Every chip below names its conversation's agent ("Claude Code replied") with no fetch per chip.
                .environment(\.evidenceDocIndex, d.docIndex)
                if wide {
                    knowledgePanel(t)
                        .frame(width: CicadaTheme.scaled(ProjectKnowledgeLayout.panelWidth))
                        .padding(.top, CicadaTheme.spacingSM)
                }
                }
                if !wide {
                    // Q7: at narrow widths the panel sits under the card.
                    knowledgePanel(t)
                        .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), alignment: .leading)
                        .padding(.bottom, CicadaTheme.scaled(72))
                }
                }
                // The scroll's content is exactly the column's width (review of #493).
                .frame(width: contentWidth > 0 ? min(contentWidth, cap) : nil, alignment: .leading)
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
                Instant.run { proxy.scrollTo(steps[0], anchor: .top) }
                Task { @MainActor in
                    await Task.yield()
                    Instant.run { proxy.scrollTo(target, anchor: .center) }
                }
            }
        }
    }

    // MARK: - The open sections (decision 9)

    @ViewBuilder
    private func sections(_ t: ProjectTimeline, state: ProjectState.Output, d: ProjectDerived) -> some View {
        let gap = CicadaTheme.scaled(26)
        ProjectLogField(projectName: t.project.name, today: today, blocked: blocked, focus: $logFocused,
                        save: { text, status, when in await write(.log(text: text, status: status, when: when)) },
                        undo: { claimId in _ = await write(.withdraw(claimId: claimId)) })
            .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth))
        let pulse = ProjectPulse.pulse(ProjectPulse.Input(t), today: today)
        if !pulse.empty {
            ProjectPulseView(pulse: pulse, today: today, pick: { reveal($0, in: t, state: state) })
                .padding(.top, gap)
        }
        let threads = t.now.threads.count
        let pending = ProjectStory.pendingLine(t.pending, today: today)
        if threads > 0 || pending != nil {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ProjectOpenLabel(title: Copy.ProjectsOpen.inMotion, count: threads) { open(.inMotion) }
                nowSection(t, state: state, limit: ProjectOpen.cap)
            }
            .padding(.top, gap)
        }
        let coming = ProjectOpen.comingUp(t, backlog: backlogCache.list(projectId), today: today)
        if !coming.isEmpty || planEditing || addPending {
            let shown = coming.capped()
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                ProjectOpenLabel(title: Copy.ProjectsOpen.comingUp, count: coming.count) { open(.comingUp) }
                planSection(t, rows: shown.milestones, showsAddButton: false)
                ForEach(shown.backlog) { item in
                    ProjectBacklogLine(item: item, selected: openBacklogItem == item.id, open: openItem)
                }
            }
            .padding(.top, gap)
            .id(ProjectScroll.planSection)
        }
        let entries = ProjectOpen.timeline(t)
        if !entries.isEmpty {
            ProjectOpenLabel(title: Copy.ProjectsOpen.timeline, count: entries.count) { open(.timeline) }
                .padding(.top, gap)
                .padding(.bottom, CicadaTheme.spacingSM)
            ForEach(entries.prefix(ProjectOpen.cap)) { entry in
                timelineRow(entry, t: t, state: state).padding(.top, CicadaTheme.spacingXS)
            }
        }
    }

    /// The full list an "All N" opened: its head (Back · title · count) and every row; Coming up's also carries the
    /// whole backlog with its tabs and its add fields (G150).
    @ViewBuilder
    private func fullList(_ kind: ProjectOpen.Full, t: ProjectTimeline, state: ProjectState.Output,
                          d: ProjectDerived) -> some View {
        let back = { Instant.run { full = nil } }
        switch kind {
        case .inMotion:
            ProjectFullHead(title: Copy.ProjectsOpen.inMotion, count: t.now.threads.count, back: back)
            nowSection(t, state: state, limit: nil).padding(.top, CicadaTheme.spacingSM)
        case .comingUp:
            let coming = ProjectOpen.comingUp(t, backlog: backlogCache.list(projectId), today: today)
            ProjectFullHead(title: Copy.ProjectsOpen.comingUp, count: coming.count, back: back)
            planSection(t, rows: coming.milestones, showsAddButton: true)
                .padding(.top, CicadaTheme.spacingSM)
                .id(ProjectScroll.planSection)
            SectionLabel(Copy.ProjectsOpen.backlog)
                .padding(.horizontal, CicadaTheme.spacingMD)
                .padding(.top, CicadaTheme.scaled(26))
                .padding(.bottom, CicadaTheme.spacingSM)
            ProjectBacklogSection(projectId: projectId, today: today, openItem: openBacklogItem,
                                  writesBlocked: blocked, open: openItem, onEditingChange: { backlogEditing = $0 })
        case .timeline:
            let entries = ProjectOpen.timeline(t)
            ProjectFullHead(title: Copy.ProjectsOpen.timeline, count: entries.count, back: back)
                .padding(.bottom, CicadaTheme.spacingSM)
            ForEach(entries) { entry in
                timelineRow(entry, t: t, state: state).padding(.top, CicadaTheme.spacingXS)
            }
            if let foot = ProjectStory.createdLine(t.items, today: today) {
                ProjectLatelyFoot(text: foot).padding(.top, CicadaTheme.spacingMD)
            }
        case .pages:
            ProjectFullHead(title: Copy.ProjectsOpen.pagesTitle, count: t.pagesTotal, back: back)
                .padding(.bottom, CicadaTheme.spacingSM)
            pagesBlock(t, limit: nil)
        case .conversations:
            let page = cache.displayConversations(projectId)
            ProjectFullHead(title: Copy.ProjectsOpen.conversationsTitle,
                            count: page?.total ?? t.conversationCount, back: back)
                .padding(.bottom, CicadaTheme.spacingSM)
            knowledge(t).conversationsBlock(limit: nil)
        case .influences:
            ProjectFullHead(title: Copy.ProjectsOpen.influencesTitle, count: t.influences.count, back: back)
                .padding(.bottom, CicadaTheme.spacingSM)
            knowledge(t).influencesBlock(limit: nil)
        }
    }

    private func nowSection(_ t: ProjectTimeline, state: ProjectState.Output, limit: Int?) -> some View {
        ProjectNowSection(timeline: t, state: state, today: today, selection: selection,
                          followups: ProjectStory.followups(store.visibleInbox),
                          pick: { pickRow($0, in: t) }, openEntity: openEntity,
                          showSource: { show($0, in: t) },
                          openInbox: { router.routeToInboxItem($0) },
                          settle: { id, status in Task { await write(.settle(claimId: id, status: status)) } },
                          writesBlocked: blocked, limit: limit)
    }

    private func planSection(_ t: ProjectTimeline, rows: [ProjectPlan.Row], showsAddButton: Bool) -> some View {
        ProjectPlanSection(timeline: t, rows: rows, today: today, selection: selection, names: store.entityNames,
                           pick: { pickRow($0, in: t) }, showSource: { show($0, in: t) },
                           showsAddButton: showsAddButton,
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

    /// A Timeline row: the story's own row (its sentence, chips, status and day; selected, its words and Resume), or a
    /// milestone marked done as a filled diamond with its Tag. Its id IS its scroll id (R-FA3).
    @ViewBuilder
    private func timelineRow(_ entry: ProjectOpen.TimelineEntry, t: ProjectTimeline,
                             state: ProjectState.Output) -> some View {
        switch entry {
        case .item(let item):
            let readerEpisode = provenance.isPresented ? provenance.current?.episode : nil
            ProjectLatelyRow(item: item, timeline: t, state: state, today: today, selection: selection,
                             readerEpisode: readerEpisode, names: store.entityNames, pick: { pickRow($0, in: t) },
                             openEntity: openEntity, showSource: { show($0, in: t) },
                             closeReader: { provenance.close() },
                             withdraw: { id in Task { await write(.withdraw(claimId: id)) } },
                             writesBlocked: blocked, conversations: conversations)
                .id(entry.id)
        case .milestone(let m):
            ProjectMilestoneDoneRow(milestone: m, today: today, selected: selection == .milestone(m.slug),
                                    pick: { pickRow($0, in: t) })
                .id(entry.id)
        }
    }

    private func open(_ kind: ProjectOpen.Full) {
        Instant.run { full = kind }
    }

    private func bandView(_ band: BandLayout, _ t: ProjectTimeline) -> some View {
        ProjectBandView(layout: band, selected: selection, isFocused: bandFocused) { pickMark($0, in: t) }
            .frame(maxWidth: .infinity, alignment: .leading)
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

    /// A mark on the band: select it, bring its row into view — opening its section's full list when the capped
    /// section does not show it (decision 17: never an in-place expansion).
    private func pickMark(_ key: ProjectKey, in t: ProjectTimeline) {
        pickRow(key, in: t)
        bandFocused = true
        guard selection == key else { return }
        bringIntoView(key, in: t)
    }

    private func step(_ band: BandLayout, _ delta: Int) {
        Instant.run { selection = band.step(from: selection, delta: delta) }
        if let key = selection, let t = cache.display(projectId) { bringIntoView(key, in: t) } else { scrollToken &+= 1 }
    }

    private func bringIntoView(_ key: ProjectKey, in t: ProjectTimeline) {
        if let d = derived, full == nil,
           !ProjectOpen.isShown(key, in: t, state: d.state, backlog: backlogCache.list(projectId), today: today) {
            Instant.run { full = ProjectOpen.full(for: key, in: t) }
        }
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

    // MARK: - The knowledge panel (Q7) and the person's other writes

    private var contentWidth: CGFloat { available > 0 ? max(available - 2 * gutter, 0) : 0 }
    private var wide: Bool { ProjectKnowledgeLayout.sideBySide(available: contentWidth) }
    /// The column's own cap (DR-36's measure): the card alone, or the card and the panel side by side.
    private var cap: CGFloat {
        CicadaTheme.scaled(wide ? ProjectLayout.detailMaxWidth + ProjectKnowledgeLayout.panelWidth
                                    + ProjectKnowledgeLayout.gap : ProjectLayout.detailMaxWidth)
    }

    private func knowledge(_ t: ProjectTimeline) -> ProjectKnowledgePanel {
        ProjectKnowledgePanel(
            timeline: t, conversations: cache.displayConversations(projectId), blocked: blocked,
            openConversation: { row in provenance.open(ReaderTarget(episode: row.episodeId, subjectId: projectId, knownTitle: row.title, knownHarness: row.harness, fromProject: projectId)) },
            untie: { row in Task { await change(.tie(id: projectId, episode: row.episodeId, remove: true)) } },
            openEntity: openEntity, addInfluence: { addingInfluence = true },
            undoInfluence: { row in
                Task { await change(.withdrawInfluence(id: projectId, claimId: row.claimId, page: row.page,
                                                       ref: row.claimId == nil ? row.ref : nil,
                                                       predicate: row.predicate)) }
            },
            allConversations: { open(.conversations) }, allInfluences: { open(.influences) })
    }

    private func pagesBlock(_ t: ProjectTimeline, limit: Int?) -> some View {
        ProjectPagesBlock(
            timeline: t, blocked: blocked, limit: limit, openEntity: openEntity, add: { addingPage = true },
            take: { p in Task { await change(.tiePage(id: projectId, entity: p.id, name: p.name, type: p.type,
                                                      remove: false)) } },
            remove: { p in Task { await change(.tiePage(id: projectId, entity: p.id, name: p.name, type: p.type,
                                                        remove: true)) } },
            all: limit == nil ? nil : { open(.pages) })
    }

    /// Pages in this project first (decision 10), then Conversations and Sources & influences, each open and capped.
    private func knowledgePanel(_ t: ProjectTimeline) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ProjectKnowledgePanel.block { pagesBlock(t, limit: ProjectOpen.cap) }
            knowledge(t)
        }
    }

    /// The pages "Add an influence" and "Add a page" offer by name: every live page but this project.
    private var pageCandidates: [(id: String, name: String, type: String)] {
        (store.graph.value?.nodes ?? []).filter { $0.id != projectId }
            .map { (id: $0.id, name: $0.name, type: $0.type.rawValue) }
    }

    /// A `ProjectOwnershipWrite` through `Store.perform` (paint, send, roll back with a toast), then the caches ask
    /// again for what the server now holds.
    @discardableResult
    private func change(_ c: ProjectChange) async -> ProjectOwnershipResponse? {
        let w = ProjectOwnershipWrite(c, cache: cache)
        let ok = await store.perform(w)
        if ok { cache.confirmPaint(w.overlayId) }
        await cache.refreshTimeline(projectId)
        await cache.refreshConversations(projectId)
        await cache.refreshList()
        return ok ? w.result : nil
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

    /// M, the menu and the header's "Add a milestone": draw Coming up with its add field open, and bring it into view.
    private func requestAdd() {
        if full != nil && full != .comingUp { full = nil }
        addPending = true
        pendingScroll = ProjectScroll.planSection
        scrollToken &+= 1
    }

    /// DR-68 (R-PP23) — D marks the selected thread or milestone done, dated today; never while typing.
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

    private func header(name: String, oneLiner: String, parent: String?, ref: ProjectRef? = nil) -> some View {
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
                    // Every item needs a project on screen: the header also draws while it is still loading.
                    Button(Copy.Projects.addMilestone) { requestAdd() }
                        .disabled(blocked || cache.display(projectId) == nil)
                    Button(Copy.ProjectsOpen.addToBacklog) { open(.comingUp) }
                        .disabled(cache.display(projectId) == nil)
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
            if let ref {
                // Ruling 45 (Q5): the person's own header, edited in place; Sleep's first line shows only when they
                // wrote none. How it came to be theirs and who last edited it ride in the header's `.help` (owner
                // 2026-10-28: the meta line made the head too dense).
                ProjectHeaderEditor(ref: ref, blocked: blocked) { newName, newDescription in
                    Task { await change(.header(id: projectId, name: newName, description: newDescription)) }
                }
            } else {
                Text(name)
                    .font(CicadaTheme.displayFont(size: 22))
                    .tracking(CicadaTheme.displayTracking(size: 22))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .accessibilityAddTraits(.isHeader)
                if !oneLiner.isEmpty {
                    Text(oneLiner).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary).lineLimit(2)
                }
            }
        }
        .padding(.top, CicadaTheme.spacingSM)
    }

    /// Projects v3 (owner 2026-10-28: "the header block is still too dense") — where it stands and what's next as ONE
    /// line under the description: "In motion · 3 of 6 milestones done · Next: Fibreglass the hull, Nov 8". What happened
    /// last is the Timeline's first row and the band's newest mark, so it is not said here too (DR-38). Next is a
    /// button onto its row; with nothing planned, "Add a milestone" (M) takes its place.
    private func standingLine(_ summary: ProjectSummary, _ t: ProjectTimeline) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingXS) {
            Text(summary.stands)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
            if let next = summary.next, let key = next.key {
                Text("·").foregroundStyle(CicadaTheme.textTertiary)
                Button { reveal(key, in: t, state: derived?.state) } label: {
                    Text(Copy.ProjectsOpen.nextInline(next.text))
                        .foregroundStyle(selection == key ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
                        .lineLimit(1)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.cicadaPlain)
                .help(Copy.Projects.summaryHelp)
            } else if summary.next == nil {
                Text("·").foregroundStyle(CicadaTheme.textTertiary)
                TextButton(title: Copy.Projects.addMilestone, keyHint: "M", help: Copy.Projects.addMilestoneHelp,
                           inline: true) { requestAdd() }
                    .disabled(blocked)
            }
        }
        .font(CicadaTheme.bodyFont)
        .monospacedDigit()
        .frame(maxWidth: CicadaTheme.scaled(ProjectLayout.textMaxWidth), alignment: .leading)
        .padding(.top, CicadaTheme.spacingSM)
    }

    /// A click on Next or a pulse fact: its row selected (the band rings its mark) and brought into view.
    private func reveal(_ key: ProjectKey, in t: ProjectTimeline, state: ProjectState.Output?) {
        Instant.run { selection = key }
        bringIntoView(key, in: t)
    }
}
