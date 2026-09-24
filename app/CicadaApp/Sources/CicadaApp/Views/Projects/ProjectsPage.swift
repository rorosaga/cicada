import SwiftUI

/// G141 PJ-5 — the Projects page (DESIGN_RULES §10, the first screen designed for D): a list page in progressive
/// columns (§5.3). STATE 0 is every project as a one-line row; a click narrows the list to the triage column and opens
/// the project beside it; its evidence opens the Reader as the third column, which this page hosts itself
/// (`AppTab.hostsOwnReader`, R-DL7). Its data is `ProjectsCache` — not a Store domain (R-PJ7, R-PP3).
struct ProjectsPage: View {
    @Environment(Store.self) private var store
    @Environment(ProjectsCache.self) private var cache
    @Environment(AppRouter.self) private var router
    @Environment(ProvenanceRouter.self) private var provenance
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @State private var columns = ListColumns<String>()
    @State private var tab: ProjectsTab? = .active
    /// R-PP6 — until the viewer picks a tab, the page follows `defaultTab` as the list arrives.
    @State private var tabChosen = false
    @State private var query = ""
    @State private var findOpen = false
    /// R-PP5 — the viewer's today; `.NSCalendarDayChanged` moves it and every word re-derives with no network.
    @State private var today = ISODay.today()
    @FocusState private var focus: ListFocus?
    /// R-PP17 — an entity's card in the third column; the Reader wins the slot.
    @State private var card: String?

    private var rows: [ProjectRow] { cache.list?.projects ?? [] }

    /// DR-45 — a tab switch is instant; a project the new tab does not show closes (R-DL6: a tab is navigation).
    private var tabSelection: Binding<ProjectsTab?> {
        Binding(get: { tab }, set: { newTab in
            Instant.run {
                tab = newTab
                tabChosen = true
                if let id = columns.openId,
                   !ProjectsModel.lines(rows, tab: newTab, query: "", today: today).contains(where: { $0.id == id }) {
                    columns.close()
                }
            }
        })
    }

    var body: some View {
        let lines = ProjectsModel.lines(rows, tab: tab, query: findOpen ? query : "", today: today)
        let people = ProjectsModel.peopleIndex(store.graph.value)
        let openId = columns.openId
        ProgressiveColumns(hasDetail: openId != nil, hasTrailing: provenance.isPresented || card != nil,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { plan in
            EyebrowRow(eyebrow: eyebrow(lines),
                       horizontalPadding: openId == nil && !provenance.isPresented ? plan.gutter : CicadaTheme.spacingXL) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    AdaptiveTextTabs(tabs: ProjectsModel.tabs(rows, today: today), selection: tabSelection,
                                     menuTitle: Copy.Projects.tabMenu)
                    PageFindButton(isOpen: $findOpen).padding(.leading, CicadaTheme.spacingSM)
                }
            }
            .help(cache.list?.partial == true ? Copy.Projects.stillIndexingHelp : "")
        } list: { plan in
            ProjectsListColumn(
                lines: lines, style: plan.listStyle, today: today, people: people,
                state: ProjectsListState.of(phase: cache.listPhase, hasList: cache.list != nil, rows: rows.count,
                                            lines: lines.count,
                                            finding: findOpen && !query.trimmingCharacters(in: .whitespaces).isEmpty),
                tab: tab, query: query, findOpen: $findOpen, findText: $query, openId: openId,
                open: { openProject($0) }, move: { move($0, in: lines) },
                focusDetail: { focus = .detail }, escape: { escape() },
                retry: { Task { await cache.refreshList() } })
                .focused($focus, equals: .list)
        } detail: { plan in
            if let id = openId {
                let row = rows.first { $0.id == id }
                ProjectDetailColumn(
                    projectId: id, row: row, parentName: parentName(of: row?.parent), today: today, gutter: plan.gutter,
                    hiddenListCount: plan.listHidden ? lines.count : nil, openCard: card,
                    onShowList: { showList() }, onClose: { closeProject() }, onEscape: { escape() },
                    openProject: { openProject($0) }, openEntity: { openCard($0) })
                    .id(id)
                    .focused($focus, equals: .detail)
            }
        } trailing: { _ in
            if provenance.isPresented {
                ReaderColumn().focused($focus, equals: .reader)
            } else if let card {
                ProjectEntityColumn(entityId: card, openProject: { openProject($0) }, onClose: { closeCard() },
                                    onEscape: { escape() })
                    .id(card)
                    .focused($focus, equals: .reader)
            }
        }
        .background(CicadaTheme.bgBase)
        // DR-46 — ⌘F opens the find row; published from a leaf (Clusters' reason: an if/else on the page rebuilt it).
        .background { Color.clear.publishesPageFind(enabled: !findOpen) { findOpen = true } }
        .onChange(of: findOpen) { _, isOpen in if !isOpen { query = "" } }
        .task { await cache.refreshList() }
        .onAppear { openPendingProject(); arrive() }
        .onChange(of: router.pendingProject) { _, _ in openPendingProject() }
        .onChange(of: cache.list?.projects.map(\.id)) { _, ids in
            guard let ids else { return }
            columns.reconcile(present: Set(ids))
            if !tabChosen { tab = ProjectsModel.defaultTab(rows, today: today) }
        }
        // R-PP3 — a sync version event that moved what the ETags fold asks again (a 304 costs nothing).
        .onChange(of: store.version) { old, new in
            guard ProjectsRefresh.shouldRevalidate(old: old, new: new) else { return }
            Task {
                await cache.refreshList()
                if let id = columns.openId { await cache.refreshTimeline(id) }
            }
        }
        // A bank switch forgets the card and the open project: ids repeat across banks.
        .onChange(of: store.bank) { _, _ in
            card = nil
            columns.close()
        }
        .onReceive(NotificationCenter.default.publisher(for: .NSCalendarDayChanged)) { _ in today = ISODay.today() }
    }

    private func eyebrow(_ lines: [ProjectLine]) -> String {
        guard let list = cache.list else { return Copy.Projects.page }
        let openId = columns.openId
        let position = openId.flatMap { id in lines.firstIndex { $0.id == id }.map { $0 + 1 } }
        let openPlanned = openId.flatMap { id in rows.first { $0.id == id }?.planned }
        return ProjectsModel.eyebrow(visible: lines.count, tab: tab, position: position, openPlanned: openPlanned,
                                     partial: list.partial)
    }

    private func parentName(of id: String?) -> String? {
        guard let id else { return nil }
        return rows.first { $0.id == id }?.name ?? store.entityNames.name(for: id)
    }

    // MARK: - Paths (a pointer path may animate, a keyboard path never does — DR-60)

    /// STATE 0 → 1 narrows the list on the drawer curve; a swap in place is instant (DR-61). A Reader the old project
    /// opened closes with it (DR-29).
    private func openProject(_ id: String) {
        let change = {
            columns.open(id)
            card = nil
            if provenance.isPresented { provenance.close() }
        }
        if columns.openId == nil {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { change() }
        } else {
            Instant.run { change() }
        }
        focus = .list
    }

    private func move(_ delta: Int, in lines: [ProjectLine]) {
        Instant.run {
            guard let next = columns.neighbour(delta, in: lines.map(\.id)) else { return }
            columns.open(next)
            card = nil
            if provenance.isPresented { provenance.close() }
        }
    }

    /// DR-28 — Esc closes the rightmost open thing: the Reader, then the card, then the project.
    private func escape() {
        Instant.run {
            if provenance.isPresented {
                provenance.close()
            } else if card != nil {
                card = nil
            } else if columns.openId != nil {
                columns.close()
                focus = .list
            }
        }
    }

    private func closeProject() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            provenance.close()
            card = nil
            columns.close()
        }
        focus = .list
    }

    /// R-PP17 — a chip or a member opens its card beside the project; the Reader steps aside (one slot). A Reader
    /// opened from inside the card returns to it on close.
    private func openCard(_ id: String) {
        card = id
        if provenance.isPresented { provenance.close() }
    }

    private func closeCard() { card = nil }

    /// DR-27 — "‹ N projects" brings the list back by closing the rightmost thing: the Reader, else the card, else
    /// the project.
    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if provenance.isPresented { provenance.close() } else if card != nil { card = nil } else { columns.close() }
        }
    }

    /// R-PP24 — a ⌘K project row lands here. Read-then-clear; a project the tab hides opens All first, so its row is
    /// drawn (R-DL12's reason).
    private func openPendingProject() {
        guard let id = router.consumeProject() else { return }
        Instant.run {
            findOpen = false
            query = ""
            if !ProjectsModel.lines(rows, tab: tab, query: "", today: today).contains(where: { $0.id == id }) {
                tab = nil
                tabChosen = true
            }
            columns.open(id)
        }
    }

    /// R-DL8 — the list takes the keys when the page appears (deferred one turn, R-DL4's reason).
    private func arrive() {
        DispatchQueue.main.async { focus = .list }
    }
}
