import SwiftUI

/// G150 (R-B19) — a project's backlog, under Plan: text tabs Open · Doing · Done · All (DR-45; a dropped item shows
/// only under All, R-PP6's precedent), one row per item — its id (R-B24: the address people cite, never monospace,
/// DR-19), its title, a triage `Tag` and a "Paid AI" `Tag` (DR-44), the age of its last note (DR-58, the full date
/// in `.help`) — and "Add to backlog". A row opens the item as the third column (R-B21); the open one wears the
/// story's selected surface (`StoryRowSurface` — never the accent, DR-5). Its data is `BacklogCache` (R-B18): a line
/// while it reads, the error card with Retry, never a blank (DR-43).
struct ProjectBacklogSection: View {
    let projectId: String
    let today: ISODay
    let openItem: String?
    let writesBlocked: Bool
    let open: (String) -> Void
    /// R-PP23's rule — true while the add fields are open, so the column's L · M · D stand aside.
    var onEditingChange: (Bool) -> Void = { _ in }

    @Environment(BacklogCache.self) private var cache
    @Environment(Store.self) private var store
    @State private var tab: BacklogStatus? = .open
    /// Until the viewer picks a tab, the section follows `BacklogModel.defaultTab` as the list arrives (R-PP6).
    @State private var tabChosen = false
    @State private var adding = false
    @State private var newTitle = ""
    @State private var newWhy = ""
    @FocusState private var titleFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            if let list = cache.list(projectId) {
                content(list)
            } else {
                switch cache.listPhase(projectId) {
                case .failed(let message):
                    ListErrorCard(title: Copy.Projects.Backlog.failedTitle, message: message) {
                        Task { await cache.refreshList(projectId) }
                    }
                case .gone:
                    line(Copy.Projects.Backlog.emptyAll)
                default:
                    line(Copy.Projects.Backlog.reading)
                }
            }
        }
        .task(id: projectId) { await cache.refreshList(projectId) }
        // `initial: true` — folding the section or switching projects rebuilds this view with the list already
        // cached, so a plain `onChange` would never fire and an all-done backlog would reopen on an empty Open.
        .onChange(of: cache.list(projectId).flatMap(BacklogModel.defaultTab), initial: true) { _, next in
            if !tabChosen, let next { tab = next }
        }
        .onChange(of: adding) { _, editing in onEditingChange(editing) }
        // Folding the section while the fields are open removes this view first (PJ-5's final-review reason).
        .onDisappear { onEditingChange(false) }
    }

    @ViewBuilder
    private func content(_ list: BacklogList) -> some View {
        let rows = BacklogModel.rows(list, tab: tab)
        AdaptiveTextTabs(tabs: BacklogModel.tabs(list), selection: tabBinding, menuTitle: Copy.Projects.Backlog.tabMenu)
            .padding(.bottom, CicadaTheme.spacingXS)
        if rows.isEmpty { line(BacklogModel.emptyLine(tab: tab)) }
        ForEach(rows) { row in rowView(row) }
        addRow
    }

    /// DR-45 / DR-60 — a tab switch is instant.
    private var tabBinding: Binding<BacklogStatus?> {
        Binding(get: { tab }, set: { next in
            Instant.run {
                tab = next
                tabChosen = true
            }
        })
    }

    private func line(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.bodyFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .padding(.horizontal, CicadaTheme.spacingMD)
    }

    private func rowView(_ row: BacklogItemSummary) -> some View {
        let selected = openItem == row.id
        let age = BacklogModel.age(row, today: today)
        return Button { open(row.id) } label: {
            HStack(spacing: CicadaTheme.spacingMD) {
                Text(row.id)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .frame(minWidth: CicadaTheme.scaled(44), alignment: .leading)
                Text(row.title)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(row.backlogStatus == .dropped ? CicadaTheme.textTertiary : CicadaTheme.textPrimary)
                    .lineLimit(1)
                if let triage = BacklogModel.triageLabel(row.triage) { Tag(text: triage) }
                if row.paid { Tag(text: Copy.Projects.Backlog.paid) }
                Spacer(minLength: CicadaTheme.spacingSM)
                if tab == nil {
                    Text(BacklogModel.statusLabel(row.backlogStatus))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Text(age.text)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .help(age.help)
            }
            .modifier(StoryRowSurface(selected: selected))
        }
        .buttonStyle(.cicadaPlain)
        .help(Copy.Projects.Backlog.rowHelp(row.id))
        .accessibilityLabel(BacklogModel.accessibilityLabel(row, today: today))
        .accessibilityAddTraits(selected ? [.isSelected] : [])
        .id("backlog:\(row.id)")
    }

    @ViewBuilder
    private var addRow: some View {
        if adding {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                TextField(Copy.Projects.Backlog.titlePlaceholder, text: $newTitle)
                    .textFieldStyle(.roundedBorder)
                    .focused($titleFocused)
                    .onSubmit(submit)
                    .onExitCommand { cancel() }
                    .accessibilityLabel(Copy.Projects.Backlog.titleLabel)
                TextField(Copy.Projects.Backlog.descriptionPlaceholder, text: $newWhy, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(2...6)
                    .onExitCommand { cancel() }
                    .accessibilityLabel(Copy.Projects.Backlog.descriptionLabel)
                HStack(spacing: CicadaTheme.spacingSM) {
                    Spacer(minLength: 0)
                    TextButton(title: Copy.Projects.cancel) { cancel() }
                    NeutralButton(title: Copy.Projects.add, size: .compact,
                                  isDisabled: writesBlocked || newTitle.trimmingCharacters(in: .whitespaces).isEmpty,
                                  help: Copy.Projects.Backlog.addHelp,
                                  disabledHelp: writesBlocked ? Copy.Projects.sleepRunningHelp
                                                              : Copy.Projects.Backlog.titleLabel) {
                        submit()
                    }
                }
            }
            .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth))
            .padding(.horizontal, CicadaTheme.spacingMD)
        } else {
            TextButton(title: Copy.Projects.Backlog.add, help: Copy.Projects.Backlog.addHelp) {
                adding = true
                DispatchQueue.main.async { titleFocused = true }
            }
            .disabled(writesBlocked)
            .padding(.leading, CicadaTheme.scaled(2))
        }
    }

    /// The person's add (R-B22: nothing painted — the id is the server's), then the new item opens beside the
    /// project.
    private func submit() {
        let title = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty, !writesBlocked else { return }
        let why = newWhy.trimmingCharacters(in: .whitespacesAndNewlines)
        cancel()
        Task {
            let write = BacklogWrite(projectId: projectId, action: .add(title: title, description: why), cache: cache)
            let ok = await store.perform(write)
            await cache.refreshList(projectId)
            if ok, let item = write.result { open(item.id) }
        }
    }

    private func cancel() {
        adding = false
        newTitle = ""
        newWhy = ""
    }
}
