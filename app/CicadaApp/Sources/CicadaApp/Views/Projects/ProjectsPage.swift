import SwiftUI

/// G141 PJ-5, v2 (owner 2026-10-19; DESIGN_RULES §9, §10) — the Projects page: a list page in progressive columns
/// (§5.3). STATE 0 is Current — the projects in motion as calm two-line rows, sub-projects indented under them, then
/// *Gone quiet* under a static label, and Suggested as one line (Projects v3: no folds, decision 17) — or Past,
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
    /// How much of Past is drawn.
    @State private var pastLimit = ProjectsModel.pageSize
    @State private var query = ""
    @State private var findOpen = false
    /// R-PP5 — the viewer's today; `.NSCalendarDayChanged` moves it and every word re-derives with no network.
    @State private var today = ISODay.today()
    @FocusState private var focus: ListFocus?
    /// R-PP17 / R-B21 — the third column's one slot besides the Reader: an entity's card or a backlog item.
    @State private var trailing: ProjectTrailing?

    /// Ruling 45 (Q1): the list is the person's own; the rest waits under Suggested (with every pending accept or
    /// dismiss painted over what the server last said).
    private var rows: [ProjectRow] { cache.displayList?.projects.filter(\.mine) ?? [] }
    private var suggested: [SuggestedProject] { cache.displayList?.suggested ?? [] }
    @State private var creating = false
    @State private var naming: SuggestedProject?
    /// R-PP20 — Sleep is writing: the list's writes wait, their reason in `.help`.
    private var blocked: Bool { ProjectWriteGate.blocked(store.status.value) }

    /// Past's field is always there; Current finds only while ⌘F's row is open.
    private var activeQuery: String { tab == .past || findOpen ? query : "" }

    private var options: ProjectsListOptions { ProjectsListOptions(pastLimit: pastLimit) }

    /// Decision 9 — "N suggested by Cicada · Review" opens the suggestions in the detail slot under this id, which no
    /// page can have (a slug never starts with a space).
    static let suggestedColumn = " suggested"

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
                    // DR-75 — the page adds through one labelled button: New project.
                    PageAddButton(title: Copy.ProjectsMine.newProject, help: Copy.ProjectsMine.newProjectHelp) {
                        creating = true
                    }
                    .disabled(blocked)
                    .padding(.leading, CicadaTheme.spacingSM)
                }
            }
            .help(cache.list?.partial == true ? Copy.Projects.stillIndexingHelp : "")
        } list: { plan in
            ProjectsListColumn(
                entries: entries, style: plan.listStyle, today: today,
                state: ProjectsListState.of(phase: cache.listPhase, hasList: cache.list != nil, rows: rows.count,
                                            suggestions: suggested.count,
                                            lines: entries.count,
                                            finding: !activeQuery.trimmingCharacters(in: .whitespaces).isEmpty),
                tab: tab, query: query, findOpen: $findOpen, findText: $query, openId: openId,
                tap: { openProject($0.id) },
                showMore: { Instant.run { pastLimit += ProjectsModel.pageSize } },
                move: { move($0) }, side: { side($0, in: lines) },
                focusDetail: { focus = .detail }, escape: { escape() },
                retry: { Task { await cache.refreshList() } },
                suggestedFold: {
                    AnyView(Group {
                        let live = suggested.filter { !$0.dismissed }.count
                        if live > 0 && plan.listStyle != .titles && plan.listStyle != .hidden {
                            ProjectsSuggestedLine(count: live, selected: openId == Self.suggestedColumn,
                                                  review: { openProject(Self.suggestedColumn) })
                                .padding(.top, CicadaTheme.scaled(14))
                        }
                    })
                })
                .focused($focus, equals: .list)
                .tourAnchor(.projects)
        } detail: { plan in
            if openId == Self.suggestedColumn {
                ProjectsSuggestedColumn(
                    suggested: suggested, blocked: blocked, gutter: plan.gutter,
                    hiddenListCount: plan.listHidden ? lines.count : nil, onShowList: { showList() },
                    onClose: { closeProject() },
                    accept: { s in
                        if s.needsName { naming = s } else { Task { await change(.accept(id: s.id, name: nil)) } }
                    },
                    dismiss: { s in Task { await change(.dismiss(id: s.id)) } })
                    .focused($focus, equals: .detail)
                    .onExitCommand { escape() }
            } else if let id = openId {
                let row = rows.first { $0.id == id }
                ProjectDetailColumn(
                    projectId: id, row: row, parentName: parentName(of: row?.parent), today: today, gutter: plan.gutter,
                    available: plan.detail,
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
        .sheet(isPresented: $creating) {
            ProjectNameSheet(title: Copy.ProjectsMine.newProject) { name, description in
                Task {
                    if let made = await change(.create(name: name, description: description)) {
                        openProject(made.id)
                    }
                }
            }
        }
        .sheet(item: $naming) { s in
            ProjectNameSheet(title: Copy.ProjectsMine.nameItTitle, message: Copy.ProjectsMine.nameItMessage,
                             asksDescription: false, confirm: Copy.ProjectsMine.addToMine) { name, _ in
                Task {
                    if let made = await change(.accept(id: s.id, name: name)) { openProject(made.id) }
                }
            }
        }
        // DR-46 — ⌘F opens Current's find row; published from a leaf (Clusters' reason: an if/else on the page rebuilt
        // it). Past's field is always there and takes ⌘F itself.
        .background { Color.clear.publishesPageFind(enabled: !findOpen && tab == .current) { findOpen = true } }
        .onChange(of: findOpen) { _, isOpen in if !isOpen && tab == .current { query = "" } }
        // Projects v2 — Projects clicked again in the sidebar: back to the root, like a tab bar (owner 2026-10-19).
        .onRailReselect(.projects, router: router) { popToRoot() }
        .task { await cache.refreshList() }
        .onAppear { openPendingProject(); arrive() }
        .onChange(of: router.pendingProject) { _, _ in openPendingProject() }
        .onChange(of: cache.list?.projects.map(\.id)) { _, ids in
            guard let ids else { return }
            columns.reconcile(present: Set(ids).union([Self.suggestedColumn]))
            if !tabChosen { tab = ProjectsModel.defaultTab(ProjectsModel.counts(rows, today: today)) }
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
            pastLimit = ProjectsModel.pageSize
        }
        .onReceive(NotificationCenter.default.publisher(for: .NSCalendarDayChanged)) { _ in today = ISODay.today() }
    }

    /// Ruling 45 — one of the person's list writes through `Store.perform` (paint, send, roll back with a toast), then
    /// the list asks again.
    @discardableResult
    private func change(_ c: ProjectChange) async -> ProjectOwnershipResponse? {
        let w = ProjectOwnershipWrite(c, cache: cache)
        let ok = await store.perform(w)
        if ok { cache.confirmPaint(w.overlayId) }
        await cache.refreshList()
        return ok ? w.result : nil
    }

    private func parentName(of id: String?) -> String? {
        guard let id else { return nil }
        return rows.first { $0.id == id }?.name ?? store.entityNames.name(for: id)
    }

    // MARK: - Paths (a pointer path may animate, a keyboard path never does — DR-60)

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
        router.popToRoot(reduceMotion: reduceMotion, change)
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

    /// ↑/↓ — the neighbour opens in place; past Past's page it draws the next (`ProjectsModel.step`). Never animated
    /// (DR-60).
    private func move(_ delta: Int) {
        Instant.run {
            let step = ProjectsModel.step(delta, openId: columns.openId, rows: rows, tab: tab, query: activeQuery,
                                          today: today, options: options)
            pastLimit = step.options.pastLimit
            guard let next = step.open, next != columns.openId else { return }
            columns.open(next)
            trailing = nil
            if provenance.isPresented { provenance.close() }
        }
    }

    /// ← — from a sub-project, go to its parent. Never animated (DR-60).
    private func side(_ delta: Int, in lines: [ProjectLine]) {
        let line = columns.openId.flatMap { id in lines.first { $0.id == id } }
        Instant.run {
            switch ProjectsModel.side(delta, line: line) {
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

    /// R-PP24 — a ⌘K project row lands here. Read-then-clear; the row is drawn first (R-DL12's reason): its tab and
    /// enough of Past drawn to reach it.
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
