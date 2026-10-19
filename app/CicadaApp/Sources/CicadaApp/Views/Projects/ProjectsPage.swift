import SwiftUI

/// G141 PJ-5, v2 (owner 2026-10-19; DESIGN_RULES §9, §10) — the Projects page: a list page in progressive columns
/// (§5.3). STATE 0 is Current — the projects in motion as calm two-line rows, then a folded *Fading* group — or Past,
/// searchable and paged; a click narrows the list to the triage column and opens the project beside it; its evidence
/// opens the Reader as the third column, which this page hosts itself (`AppTab.hostsOwnReader`, R-DL7). Projects
/// clicked again in the rail comes back here (`AppRouter.reselect`). Its data is `ProjectsCache` — not a Store
/// domain (R-PJ7, R-PP3).
struct ProjectsPage: View {
    @Environment(Store.self) private var store
    @Environment(ProjectsCache.self) private var cache
    @Environment(BacklogCache.self) private var backlogCache
    @Environment(AppRouter.self) private var router
    @Environment(ProvenanceRouter.self) private var provenance
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var columns = ListColumns<String>()
    @State private var tab: ProjectsTab = .current
    /// Until the viewer picks a tab, the page follows `defaultTab` as the list arrives.
    @State private var tabChosen = false
    /// Which parents show their parts, and how much of Past is drawn; Fading's fold is remembered (DR-39).
    @State private var expanded: Set<String> = []
    @State private var pastLimit = ProjectsModel.pageSize
    @AppStorage("cicada.projects.fadingOpen") private var fadingOpen = false
    @State private var query = ""
    @State private var findOpen = false
    /// R-PP5 — the viewer's today; `.NSCalendarDayChanged` moves it and every word re-derives with no network.
    @State private var today = ISODay.today()
    @FocusState private var focus: ListFocus?
    /// R-PP17 / R-B21 — the third column's one slot besides the Reader: an entity's card or a backlog item.
    @State private var trailing: ProjectTrailing?

    private var rows: [ProjectRow] { cache.list?.projects ?? [] }

    /// Past's field is always there; Current finds only while ⌘F's row is open.
    private var activeQuery: String { tab == .past || findOpen ? query : "" }

    private var options: ProjectsListOptions {
        ProjectsListOptions(expanded: expanded, fadingOpen: fadingOpen, pastLimit: pastLimit)
    }

    /// DR-45 — a tab switch is instant; a project the new tab does not hold closes (R-DL6: a tab is navigation).
    /// Tapping the selected tab keeps it: there is no All to fall back to.
    private var tabSelection: Binding<ProjectsTab?> {
        Binding(get: { tab }, set: { newTab in
            guard let newTab, newTab != tab else { return }
            Instant.run {
                tab = newTab
                tabChosen = true
                pastLimit = ProjectsModel.pageSize
                if let id = columns.openId, let row = rows.first(where: { $0.id == id }),
                   ProjectsModel.group(row, today: today).tab != newTab {
                    columns.close()
                }
            }
        })
    }

    var body: some View {
        let entries = ProjectsModel.entries(rows, tab: tab, query: activeQuery, today: today, options: options)
        let lines = entries.compactMap(\.line)
        let counts = ProjectsModel.counts(rows, today: today)
        let openId = columns.openId
        ProgressiveColumns(hasDetail: openId != nil, hasTrailing: provenance.isPresented || trailing != nil,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: cache.list.map { ProjectsModel.eyebrow(partial: $0.partial) } ?? Copy.Projects.page,
                       horizontalPadding: openId == nil && !provenance.isPresented ? plan.gutter : CicadaTheme.spacingXL) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    AdaptiveTextTabs(tabs: ProjectsModel.tabs(counts), selection: tabSelection,
                                     menuTitle: Copy.Projects.tabMenu)
                    PageFindButton(isOpen: $findOpen).padding(.leading, CicadaTheme.spacingSM)
                }
            }
            .help(cache.list?.partial == true ? Copy.Projects.stillIndexingHelp : "")
        } list: { plan in
            ProjectsListColumn(
                entries: entries, style: plan.listStyle, today: today,
                state: ProjectsListState.of(phase: cache.listPhase, hasList: cache.list != nil, rows: rows.count,
                                            lines: entries.count,
                                            finding: !activeQuery.trimmingCharacters(in: .whitespaces).isEmpty),
                tab: tab, query: query, findOpen: $findOpen, findText: $query, openId: openId,
                tap: { tap($0) }, toggleParts: { toggleParts($0) }, toggleFading: { toggleFading() },
                showMore: { Instant.run { pastLimit += ProjectsModel.pageSize } },
                move: { move($0) }, side: { side($0, in: lines) },
                focusDetail: { focus = .detail }, escape: { escape() },
                retry: { Task { await cache.refreshList() } })
                .focused($focus, equals: .list)
                .tourAnchor(.projects)
        } detail: { plan in
            if let id = openId {
                let row = rows.first { $0.id == id }
                ProjectDetailColumn(
                    projectId: id, row: row, parentName: parentName(of: row?.parent), today: today, gutter: plan.gutter,
                    hiddenListCount: plan.listHidden ? lines.count : nil, openCard: trailing?.entityId,
                    openBacklogItem: trailing?.backlogItemId,
                    onShowList: { showList() }, onClose: { closeProject() }, onEscape: { escape() },
                    openProject: { openProject($0) }, openEntity: { openCard($0) }, openItem: { openItem($0) })
                    .id(id)
                    .focused($focus, equals: .detail)
                    .tourAnchor(.projectDetail)
            }
        } trailing: { _ in
            if provenance.isPresented {
                ReaderColumn().focused($focus, equals: .reader)
            } else if let card = trailing?.entityId {
                ProjectEntityColumn(entityId: card, openProject: { openProject($0) }, onClose: { closeTrailing() },
                                    onEscape: { escape() })
                    .id(card)
                    .focused($focus, equals: .reader)
            } else if let item = trailing?.backlogItemId, let project = openId {
                BacklogItemColumn(projectId: project, itemId: item, onClose: { closeTrailing() },
                                  onEscape: { escape() })
                    .id(BacklogCache.key(project, item))
                    .focused($focus, equals: .reader)
            }
        }
        .background(CicadaTheme.bgBase)
        // DR-46 — ⌘F opens Current's find row; published from a leaf (Clusters' reason: an if/else on the page rebuilt
        // it). Past's field is always there and takes ⌘F itself.
        .background { Color.clear.publishesPageFind(enabled: !findOpen && tab == .current) { findOpen = true } }
        .onChange(of: findOpen) { _, isOpen in if !isOpen && tab == .current { query = "" } }
        // Projects v2 — Projects clicked again in the sidebar: back to the root, like a tab bar (owner 2026-10-19).
        .onChange(of: router.reselections(of: .projects)) { _, _ in popToRoot() }
        .task { await cache.refreshList() }
        .onAppear { openPendingProject(); arrive() }
        .onChange(of: router.pendingProject) { _, _ in openPendingProject() }
        .onChange(of: cache.list?.projects.map(\.id)) { _, ids in
            guard let ids else { return }
            columns.reconcile(present: Set(ids))
            if !tabChosen { tab = ProjectsModel.defaultTab(ProjectsModel.counts(rows, today: today)) }
            expanded.formIntersection(ids)
        }
        // R-PP3 / R-B18 — a sync version event that moved what an ETag folds asks again (a 304 costs nothing).
        .onChange(of: store.version) { old, new in
            let projects = ProjectsRefresh.shouldRevalidate(old: old, new: new)
            let backlog = BacklogRefresh.shouldRevalidate(old: old, new: new)
            guard projects || backlog else { return }
            Task {
                if projects {
                    await cache.refreshList()
                    if let id = columns.openId { await cache.refreshTimeline(id) }
                }
                if backlog, let id = columns.openId {
                    await backlogCache.refreshList(id)
                    if let item = trailing?.backlogItemId { await backlogCache.refreshItem(id, item) }
                }
            }
        }
        // A bank switch forgets the card or item and the open project: ids repeat across banks.
        .onChange(of: store.bank) { _, _ in
            trailing = nil
            columns.close()
            expanded = []
            pastLimit = ProjectsModel.pageSize
        }
        .onReceive(NotificationCenter.default.publisher(for: .NSCalendarDayChanged)) { _ in today = ISODay.today() }
    }

    private func parentName(of id: String?) -> String? {
        guard let id else { return nil }
        return rows.first { $0.id == id }?.name ?? store.entityNames.name(for: id)
    }

    // MARK: - Paths (a pointer path may animate, a keyboard path never does — DR-60)

    /// A row's click: open it, and for a parent unfold its parts; the open parent clicked again folds or unfolds them.
    private func tap(_ line: ProjectLine) {
        let (opens, expand) = ProjectsModel.tap(line, openId: columns.openId)
        if let expand {
            withAnimation(CicadaMotion.groupExpand(reduceMotion: reduceMotion)) { setExpanded(line.id, expand) }
        }
        if opens { openProject(line.id) }
    }

    /// The chevron: fold or unfold a parent's parts without opening it.
    private func toggleParts(_ line: ProjectLine) {
        withAnimation(CicadaMotion.groupExpand(reduceMotion: reduceMotion)) { setExpanded(line.id, !line.expanded) }
    }

    private func setExpanded(_ id: String, _ open: Bool) {
        if open { expanded.insert(id) } else { expanded.remove(id) }
    }

    private func toggleFading() {
        withAnimation(CicadaMotion.groupExpand(reduceMotion: reduceMotion)) { fadingOpen.toggle() }
    }

    /// Projects clicked again in the rail: the Reader, the card or item and the project close together, the find
    /// clears, and the page shows its first screen. A pointer click closes on the columns' curve; ⌘8 never animates.
    private func popToRoot() {
        let change = {
            provenance.close()
            trailing = nil
            columns.close()
            findOpen = false
            query = ""
            pastLimit = ProjectsModel.pageSize
            tab = ProjectsModel.defaultTab(ProjectsModel.counts(rows, today: today))
            tabChosen = false
        }
        if router.lastReselectByKey {
            Instant.run { change() }
        } else {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { change() }
        }
        focus = .list
    }

    /// STATE 0 → 1 narrows the list on the drawer curve; a swap in place is instant (DR-61). A Reader the old project
    /// opened closes with it (DR-29).
    private func openProject(_ id: String) {
        let change = {
            columns.open(id)
            trailing = nil
            if provenance.isPresented { provenance.close() }
        }
        if columns.openId == nil {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { change() }
        } else {
            Instant.run { change() }
        }
        focus = .list
    }

    /// ↑/↓ — the neighbour opens in place; past the end of Current it opens Fading, past Past's page it draws the
    /// next (`ProjectsModel.step`). Never animated (DR-60).
    private func move(_ delta: Int) {
        Instant.run {
            let step = ProjectsModel.step(delta, openId: columns.openId, rows: rows, tab: tab, query: activeQuery,
                                          today: today, options: options)
            fadingOpen = step.options.fadingOpen
            pastLimit = step.options.pastLimit
            guard let next = step.open, next != columns.openId else { return }
            columns.open(next)
            trailing = nil
            if provenance.isPresented { provenance.close() }
        }
    }

    /// →/← — unfold or fold the open parent's parts, or from a part go to its parent. Never animated (DR-60).
    private func side(_ delta: Int, in lines: [ProjectLine]) {
        let line = columns.openId.flatMap { id in lines.first { $0.id == id } }
        Instant.run {
            switch ProjectsModel.side(delta, line: line) {
            case .expand(let open): if let line { setExpanded(line.id, open) }
            case .open(let parent):
                columns.open(parent)
                trailing = nil
                if provenance.isPresented { provenance.close() }
            case .none: break
            }
        }
    }

    /// DR-28 — Esc closes the rightmost open thing: the Reader, then the item or card, then the project.
    private func escape() {
        Instant.run {
            switch ProjectTrailing.escape(readerOpen: provenance.isPresented, trailing: trailing,
                                          projectOpen: columns.openId != nil) {
            case .reader: provenance.close()
            case .trailing: trailing = nil
            case .project:
                columns.close()
                focus = .list
            case .nothing: break
            }
        }
    }

    private func closeProject() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            provenance.close()
            trailing = nil
            columns.close()
        }
        focus = .list
    }

    /// R-PP17 — a chip or a member opens its card beside the project; the Reader steps aside (one slot). A Reader
    /// opened from inside the card returns to it on close.
    private func openCard(_ id: String) {
        trailing = .entity(id)
        if provenance.isPresented { provenance.close() }
    }

    /// R-B21 — a backlog row opens its item in the same slot; a Reader the old selection opened steps aside (DR-29).
    private func openItem(_ id: String) {
        trailing = .backlogItem(id)
        if provenance.isPresented { provenance.close() }
    }

    private func closeTrailing() { trailing = nil }

    /// DR-27 — "‹ N projects" brings the list back by closing the rightmost thing: the Reader, else the item or card,
    /// else the project.
    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if provenance.isPresented { provenance.close() } else if trailing != nil { trailing = nil } else { columns.close() }
        }
    }

    /// R-PP24 — a ⌘K project row lands here. Read-then-clear; the row is drawn first (R-DL12's reason): its tab,
    /// Fading opened, its parents unfolded and enough of Past drawn to reach it.
    private func openPendingProject() {
        guard let id = router.consumeProject() else { return }
        Instant.run {
            findOpen = false
            query = ""
            if let reveal = ProjectsModel.reveal(id, rows: rows, today: today, pastLimit: pastLimit) {
                if reveal.tab != tab {
                    tab = reveal.tab
                    tabChosen = true
                }
                if reveal.openFading { fadingOpen = true }
                expanded.formUnion(reveal.expand)
                if let limit = reveal.pastLimit { pastLimit = limit }
            }
            columns.open(id)
            // G150 (R-B25) — a ⌘K backlog landing opens its item through `openItem`, so a Reader left open steps
            // aside (R-B21: the Reader otherwise wins the slot and the landed item would not show); any other
            // project landing closes a stale item or card.
            if let item = router.consumeBacklogItem() { openItem(item) } else { trailing = nil }
        }
    }

    /// R-DL8 — the list takes the keys when the page appears (deferred one turn, R-DL4's reason).
    private func arrive() {
        DispatchQueue.main.async { focus = .list }
    }
}
