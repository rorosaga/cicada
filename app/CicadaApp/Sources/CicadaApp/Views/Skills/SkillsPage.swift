import AppKit
import SwiftUI

/// The Skills page (owner 2026-10-15, third take) — a rail page at ⌘4 (DR-22). One plain table: the skill (its name and
/// one muted line), the agents that have it (one pull-down that ticks agents on and off), and one quiet word of status;
/// details in a side column when a row is selected; an agent's request as one line above the table. The top row is
/// every other page's (owner 2026-10-20): the tabs Installed · Discover · Drafts in the eyebrow row (DR-25, DR-45),
/// then Check for updates and a labelled *Add a skill* (DR-75, ⌘N) that opens the Add sheet. No pictures on rows.
/// Applies DR-22, DR-25, DR-37, DR-40, DR-41, DR-43 (never blank over good data), DR-44, DR-45, DR-47, DR-48, DR-59,
/// DR-75. G201 slice (a) (TODO ruling 35, 2026-10-22): a Kind column (one word, a pull-down to correct it — DR-40's
/// `TextButton`, as the Agents cell), Claude Code's plugins as their own read-only group under the table (DR-20/DR-47
/// `SectionLabel`, DR-48 rows, DR-21 counts), and one weight line above it — DR-59's dated exception for an estimated
/// token count, said as an estimate with its basis on hover.
///
/// The app decides nothing: the backend reads the folders, checks upstream and writes every file
/// (`api/services/skill_store.py`); a click here is one route (`SkillsPageModel`).
struct SkillsPage: View {
    @State private var model = SkillsPageModel()
    @State private var adding: SkillAddInput?
    @State private var publishing: SkillDraft?
    @State private var reading: SkillDraft?
    @State private var tab: SkillsTab?
    @State private var selected: String?
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        SkillsPageView(model: model, tab: $tab, selected: $selected,
                       onAdd: { adding = SkillAddInput(source: "", requestId: nil, agents: []) },
                       onReview: { request in
                           adding = SkillAddInput(source: request.source ?? "", requestId: request.id,
                                                  agents: request.agents)
                       },
                       onPublish: { publishing = $0 }, onRead: { reading = $0 })
            .background(CicadaTheme.bgBase)
            .task { await model.appeared() }
            // Say it once — Skills clicked again in the rail: Installed, nothing selected.
            .onRailReselect(.skills, router: router) {
                router?.popToRoot(reduceMotion: reduceMotion) {
                    provenance?.close()
                    tab = nil
                    selected = nil
                }
            }
            .sheet(item: $adding) { input in
                AddSkillSheet(model: model, input: input, agents: model.data?.agents ?? []) { adding = nil }
            }
            .sheet(item: $publishing) { draft in
                PublishDraftSheet(draft: draft, agents: model.data?.agents ?? []) { chosen in
                    publishing = nil
                    if let chosen { Task { await model.publish(draft.name, agents: chosen) } }
                }
            }
            .sheet(item: $reading) { draft in
                SkillTextSheet(title: draft.name, text: draft.text) { reading = nil }
            }
    }
}

/// Installed is the page's own view (`nil`, DR-45's "All"); Discover and Drafts are the other two.
enum SkillsTab: Hashable { case discover, drafts }

/// What the Add sheet opens with: the header field's text, or an agent's request to review.
struct SkillAddInput: Identifiable {
    let id = UUID()
    let source: String
    let requestId: String?
    let agents: [String]
}

/// The page, pure over the model's state. Round 2 of the consistency pass (2026-10-20): the table and a skill's details
/// sit on the shared progressive columns (§5.3) like Sources and Projects — the table full width with nothing open; a
/// skill opens the triage list (two-line rows) beside its detail, which takes the rest; the Reader, when something
/// opens it, is the third column, and DR-27 hides the list before the detail or the Reader drop below their floors
/// ("‹ N skills" brings it back). ↑/↓ move the open skill, ⏎ steps into it, Esc closes the rightmost (DR-28, DR-68).
/// The top row is every other page's since 2026-10-20 (owner): the tabs in the eyebrow row, then the page's actions.
struct SkillsPageView: View {
    let model: SkillsPageModel
    @Binding var tab: SkillsTab?
    @Binding var selected: String?
    var onAdd: () -> Void = {}
    var onReview: (SkillRequest) -> Void = { _ in }
    var onPublish: (SkillDraft) -> Void = { _ in }
    var onRead: (SkillDraft) -> Void = { _ in }

    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @AppStorage(ShellMetrics.labelledKey) private var labelledSidebar = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var focus: ListFocus?

    private var data: SkillsPageData? { model.data }
    private var selectedSkill: InstalledSkill? {
        tab == nil ? selected.flatMap { name in data?.installed.first { $0.name == name } } : nil
    }
    private var readerOpen: Bool { provenance?.isPresented ?? false }

    var body: some View {
        let open = selectedSkill
        ProgressiveColumns(hasDetail: open != nil, hasTrailing: readerOpen,
                           navWidth: ShellMetrics.navWidth(labelled: labelledSidebar)) { _ in
            header
        } list: { plan in
            content(plan)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .listKeys(move: { move($0) }, enter: { enterDetail() }, escape: { escape() })
                .focused($focus, equals: .list)
        } detail: { plan in
            if let skill = open {
                SkillDetailColumn(skill: skill, busy: model.busy.contains(skill.name),
                                  backLabel: plan.listHidden ? Copy.Skills.skillsBack(data?.installed.count ?? 0) : nil,
                                  onShowList: { showList() },
                                  onClose: { close() },
                                  onUpdate: { Task { await model.update(skill.name) } },
                                  onRefresh: { Task { await model.refresh(skill.name) } },
                                  onRemove: {
                                      Instant.run { selected = nil }
                                      Task { await model.remove(skill.name) }
                                  })
                    .id(skill.name)
                    .columnEdge()   // DR-11: the one permitted rule, from the theme
                    // After ⏎ the detail holds the keys: ↑/↓ still swap the skill in place, Esc closes the rightmost
                    // (DR-28, DR-68); ⏎ here steps nowhere further.
                    .listKeys(move: { move($0) }, enter: { false }, escape: { escape() })
                    .focused($focus, equals: .detail)
            }
        } trailing: { _ in
            ReaderColumn().focused($focus, equals: .reader)
        }
    }

    /// The top row (owner 2026-10-20: "align the top row with every other page"): the tabs in the eyebrow row, Check
    /// for updates, and *Add a skill* (DR-75, ⌘N), which opens the Add sheet; then an agent's requests, a message and
    /// running jobs.
    private var header: some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: Copy.Skills.page) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    TextTabs(tabs: [TextTab(id: nil, label: Copy.Skills.installed, count: data?.installed.count),
                                    TextTab(id: .discover, label: Copy.Skills.discover, count: nil),
                                    TextTab(id: .drafts, label: Copy.Skills.drafts,
                                            count: (data?.drafts.count ?? 0) == 0 ? nil : data?.drafts.count)],
                             selection: $tab)
                    IconButton(systemName: "arrow.clockwise", help: Copy.Skills.checkHelp,
                               accessibilityLabel: Copy.Skills.check) { Task { await model.checkNow() } }
                        .disabled(model.checking)
                        .padding(.leading, CicadaTheme.spacingSM)
                    PageAddButton(title: Copy.Skills.add, help: Copy.Skills.addHelp,
                                  shortcut: KeyboardShortcut("n", modifiers: .command), action: onAdd)
                }
            }
            ForEach(data?.requests ?? []) { request in
                SkillRequestLine(request: request, agents: data?.agents ?? [], busy: model.busy.contains(request.id),
                                 onReview: { onReview(request) },
                                 onApprove: { Task { await model.approve(request) } },
                                 onDismiss: { Task { await model.dismiss(request) } })
                    .padding(.horizontal, CicadaTheme.spacingGutter)
                    .padding(.bottom, CicadaTheme.spacingSM)
            }
            if let message = model.message {
                Label(message, systemImage: "exclamationmark.circle")
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.spacingGutter).padding(.bottom, CicadaTheme.spacingSM)
            }
            ForEach(model.jobs) { job in
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text(Copy.Skills.jobRunning(job.step ?? job.label))
                        .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                }
                .padding(.horizontal, CicadaTheme.spacingGutter).padding(.bottom, CicadaTheme.spacingSM)
            }
        }
    }

    // MARK: Paths (R-DL8, DR-28, DR-60)

    /// A click from the table opens the columns on their curve; a swap, and every key, is instant (DR-60). A Reader
    /// the old skill had open closes with it (DR-29).
    private func select(_ name: String) {
        let change = {
            selected = selected == name ? nil : name
            if readerOpen { provenance?.close() }
        }
        if selected == nil {
            withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) { change() }
        } else {
            Instant.run { change() }
        }
        DispatchQueue.main.async { focus = .list }
    }

    private func move(_ delta: Int) {
        guard tab == nil, let names = data?.installed.map(\.name) else { return }
        Instant.run {
            var columns = ListColumns<String>()
            if let selected { columns.open(selected) }
            guard let next = columns.neighbour(delta, in: names) else { return }
            selected = next
            if readerOpen { provenance?.close() }
        }
    }

    private func enterDetail() -> Bool {
        guard selectedSkill != nil else { return false }
        focus = .detail
        return true
    }

    /// DR-28 — the Reader, then the skill.
    private func escape() {
        Instant.run {
            if readerOpen { provenance?.close() } else if selected != nil { selected = nil }
        }
    }

    private func close() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            provenance?.close()
            selected = nil
        }
    }

    /// "‹ N skills" — the list comes back by closing the Reader that hid it (DR-27).
    private func showList() {
        withAnimation(CicadaMotion.columns(reduceMotion: reduceMotion)) {
            if readerOpen { provenance?.close() } else { selected = nil }
        }
    }

    @ViewBuilder
    private func content(_ plan: ColumnPlan) -> some View {
        switch (model.phase, data) {
        // DR-43 — the list pages' one first-read pair: words over a still skeleton, then why it failed and Retry.
        case (.failed(let why), nil):
            ListErrorCard(title: Copy.Skills.loadFailedTitle, message: why) { Task { await model.load() } }
        case (_, nil):
            ListSkeleton(message: Copy.Skills.loading)
                .padding(.horizontal, CicadaTheme.scaled(30))
        case (_, let data?):
            ScrollView {
                Group {
                    switch tab {
                    case nil: installed(data, style: plan.listStyle)
                    case .discover?: discover(data)
                    case .drafts?: drafts(data)
                    }
                }
                .padding(plan.listStyle == .wide ? EdgeInsets(top: 0, leading: CicadaTheme.spacingGutter,
                                                              bottom: CicadaTheme.scaled(72),
                                                              trailing: CicadaTheme.spacingGutter)
                                                 : ListInsets.of(plan.listStyle))
            }
        }
    }

    // MARK: Installed: the table, or the list beside a skill

    @ViewBuilder
    private func installed(_ data: SkillsPageData, style: ColumnPlan.ListStyle) -> some View {
        if data.installed.isEmpty && data.plugins.isEmpty {
            // DR-50 — the one empty state, with the rail's glyph (2026-10-22), like Graph, Inbox and Projects.
            EmptyStateView(systemImage: "puzzlepiece.extension", title: Copy.Skills.emptyInstalledTitle,
                           message: Copy.Skills.emptyInstalledMessage)
        } else if style == .wide {
            VStack(alignment: .leading, spacing: 0) {
                if let line = SkillPluginWords.weight(data.weight) {
                    Text(line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                        .monospacedDigit().lineLimit(1).help(Copy.Skills.weightHelp)
                        .padding(.horizontal, CicadaTheme.spacingSM).padding(.bottom, CicadaTheme.spacingXS)
                }
                SkillsTableHeader()
                ForEach(data.installed) { skill in
                    Divider().overlay(CicadaTheme.border)
                    SkillTableRow(skill: skill, selected: skill.name == selected,
                                  busy: model.busy.contains(skill.name),
                                  onSelect: { select(skill.name) },
                                  onToggle: { agent in Task { await model.toggle(skill, agent: agent) } },
                                  onUpdate: { Task { await model.update(skill.name) } },
                                  onRefresh: { Task { await model.refresh(skill.name) } },
                                  onKind: { choice in Task { await model.setKind(skill.kind, to: choice) } })
                }
                if !data.plugins.isEmpty {
                    SkillPluginsGroup(plugins: data.plugins, busy: model.busy) { kind, choice in
                        Task { await model.setKind(kind, to: choice) }
                    }
                    .padding(.top, CicadaTheme.spacingLG)
                }
            }
        } else {
            // §5.3 STATE 1/2 — beside a skill the table narrows to the list pages' rows: the name and its one line
            // (titles only beside the Reader), at the shared heights and fill (DR-34, DR-48).
            VStack(alignment: .leading, spacing: 0) {
                ForEach(data.installed) { skill in
                    SkillListRow(skill: skill, style: style, selected: skill.name == selected) { select(skill.name) }
                }
            }
        }
    }

    // MARK: Discover and Drafts

    private func discover(_ data: SkillsPageData) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(data.suggested.enumerated()), id: \.element.id) { index, item in
                if index > 0 { Divider().overlay(CicadaTheme.border) }
                SuggestedSkillRow(skill: item, uv: data.uv, busy: model.busy.contains(item.id)) {
                    Task { await model.installSuggested(item.id, agents: []) }
                }
            }
        }
    }

    @ViewBuilder
    private func drafts(_ data: SkillsPageData) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if data.drafts.isEmpty {
                Text(Copy.Skills.madeEmpty).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.vertical, CicadaTheme.spacingSM)
            }
            ForEach(data.drafts) { draft in
                DraftSkillRow(draft: draft, busy: model.busy.contains(draft.name), onRead: { onRead(draft) },
                              onPublish: { onPublish(draft) },
                              onDiscard: { Task { await model.discard(draft.name) } },
                              onKind: { choice in Task { await model.setKind(draft.kind, to: choice) } })
                Divider().overlay(CicadaTheme.border)
            }
            if !data.noticed.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    SectionLabel(Copy.Skills.noticedTitle)
                    Text(Copy.Skills.noticedLine).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    ForEach(data.noticed) { item in
                        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                            Text(item.name).font(CicadaTheme.bodyFont)
                            Text(item.description).font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textSecondary).lineLimit(1)
                            Spacer(minLength: CicadaTheme.spacingSM)
                            SkillKindMenu(kind: item.kind, busy: model.busy.contains(item.kind.key)) { choice in
                                Task { await model.setKind(item.kind, to: choice) }
                            }
                            Tag(text: Copy.Skills.noticedState(item.state, item.conversations))
                        }
                    }
                }
                .padding(.vertical, CicadaTheme.spacingMD)
            }
        }
    }
}

// MARK: - The table

enum SkillsTableLayout {
    static let agentsWidth: CGFloat = 220
    static let kindWidth: CGFloat = 100
    static let statusWidth: CGFloat = 120
}

struct SkillsTableHeader: View {
    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            SectionLabel(Copy.Skills.skillColumn).frame(maxWidth: .infinity, alignment: .leading)
            SectionLabel(Copy.Skills.agentsColumn)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.agentsWidth), alignment: .leading)
            SectionLabel(Copy.Skills.kindColumn)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.kindWidth), alignment: .leading)
            SectionLabel(Copy.Skills.statusColumn)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.statusWidth), alignment: .leading)
        }
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.spacingSM)
    }
}

/// One skill: its name and one muted line, the agents pull-down, one word of status. A click selects it (details in
/// the detail column); DR-48: the shared row fill (`rowHover`), never a lift.
struct SkillTableRow: View {
    let skill: InstalledSkill
    let selected: Bool
    let busy: Bool
    var onSelect: () -> Void = {}
    var onToggle: (SkillAgentState) -> Void = { _ in }
    var onUpdate: () -> Void = {}
    var onRefresh: () -> Void = {}
    var onKind: (String) -> Void = { _ in }
    @State private var hovering = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(skill.name).font(CicadaTheme.rowFont).lineLimit(1)
                Text(skill.description).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .onTapGesture(perform: onSelect)
            SkillAgentsPullDown(agents: skill.agents, busy: busy, onToggle: onToggle)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.agentsWidth), alignment: .leading)
            SkillKindMenu(kind: skill.kind, busy: busy, onChoose: onKind)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.kindWidth), alignment: .leading)
            SkillStatusCell(skill: skill, onUpdate: onUpdate, onRefresh: onRefresh)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.statusWidth), alignment: .leading)
        }
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.spacingSM)
        .rowHover($hovering, selected: selected)
        .opacity(busy ? NeutralButton.disabledOpacity : 1)
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

/// A skill in the narrowed list beside its detail (§5.3): its name, and its one line in the triage column (a titles-only
/// column beside the Reader drops it). The list pages' row surface: one height per role, the shared fill (DR-34, DR-48).
struct SkillListRow: View {
    let skill: InstalledSkill
    let style: ColumnPlan.ListStyle
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                Text(skill.name)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                if style == .triage, !skill.description.isEmpty {
                    Text(skill.description)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                }
            }
            .listRowSurface(height: ListRowSurface.height(style), selected: selected)
        }
        .buttonStyle(.cicadaPlain)
        .accessibilityLabel(skill.name)
        .accessibilityAddTraits(selected ? [.isSelected] : [])
    }
}

/// "Claude Code, Codex +1 ▾" — a pull-down of every agent installed on this Mac: tick to give it the skill, untick to
/// take it away; an agent that reads another's folder shows a hollow tick and "through Claude Code".
struct SkillAgentsPullDown: View {
    let agents: [SkillAgentState]
    let busy: Bool
    var onToggle: (SkillAgentState) -> Void = { _ in }
    @State private var open = false

    var body: some View {
        TextButton(title: SkillAgentWords.summary(agents) + " ▾", inline: true) { open.toggle() }
            .disabled(busy || agents.isEmpty)
            .popover(isPresented: $open, arrowEdge: .bottom) {
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                    ForEach(agents) { agent in
                        Button { if agent.canToggle { onToggle(agent) } } label: {
                            HStack(spacing: CicadaTheme.spacingSM) {
                                Image(systemName: SkillAgentWords.glyph(agent))
                                    .font(CicadaTheme.icon(.inline))
                                    .foregroundStyle(agent.state == "through" ? CicadaTheme.textTertiary
                                                     : CicadaTheme.textPrimary)
                                    .frame(width: CicadaTheme.scaled(16))
                                Text(agent.label).font(CicadaTheme.bodyFont)
                                if let through = SkillAgentWords.through(agent) {
                                    Text(through).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                }
                                Spacer(minLength: CicadaTheme.spacingSM)
                            }
                            .padding(.horizontal, CicadaTheme.spacingSM)
                            .frame(height: CicadaTheme.scaled(28))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.cicadaPlain)
                        .disabled(!agent.canToggle)
                        .help(agent.note ?? Copy.Skills.agentHelp(agent.label, on: agent.isOn))
                    }
                }
                .padding(CicadaTheme.spacingSM)
                .frame(minWidth: CicadaTheme.scaled(240))
            }
    }
}

/// The pull-down's words, pure.
enum SkillAgentWords {
    /// "Claude Code, Codex +1", "Claude Code", or "None".
    static func summary(_ agents: [SkillAgentState]) -> String {
        let on = agents.filter(\.isOn).map(\.label)
        guard !on.isEmpty else { return Copy.Skills.noAgents }
        let head = on.prefix(2).joined(separator: ", ")
        return on.count > 2 ? "\(head) +\(on.count - 2)" : head
    }

    static func glyph(_ agent: SkillAgentState) -> String {
        switch agent.state {
        case "on": "checkmark.square"
        case "through": "checkmark.square.dashed"
        default: "square"
        }
    }

    /// "through Claude Code" for an agent that sees the skill in another agent's folder.
    static func through(_ agent: SkillAgentState) -> String? {
        guard agent.state == "through", let note = agent.note else { return nil }
        // The backend's note reads "Has it through Claude Code's folder." — the pull-down keeps the agent's name.
        let name = note.replacingOccurrences(of: "Has it through ", with: "")
            .replacingOccurrences(of: "'s folder.", with: "").replacingOccurrences(of: ".", with: "")
        return "through \(name)"
    }
}

/// One quiet word: "Up to date" with a dot, "Local", "⚠ Refresh", or an Update chip whose popover lists the changes
/// and holds the one Update (the owner: never "Update available" and "What changed" spelled out on the row).
struct SkillStatusCell: View {
    let skill: InstalledSkill
    var onUpdate: () -> Void = {}
    var onRefresh: () -> Void = {}
    @State private var showChanges = false

    var body: some View {
        switch skill.status {
        case "update":
            NeutralButton(title: Copy.Skills.update, size: .compact) { showChanges = true }
                .popover(isPresented: $showChanges, arrowEdge: .bottom) {
                    SkillChangesPopover(update: skill.update) {
                        showChanges = false
                        onUpdate()
                    }
                    .frame(width: CicadaTheme.scaled(360))
                }
        case "refresh":
            TextButton(title: "⚠ " + Copy.Skills.refresh, help: Copy.Skills.refreshHelp, inline: true,
                       action: onRefresh)
        case "current":
            HStack(spacing: CicadaTheme.scaled(6)) {
                Circle().fill(CicadaTheme.success).frame(width: CicadaTheme.scaled(6), height: CicadaTheme.scaled(6))
                Text(Copy.Skills.upToDate).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            }
        case "unchecked":
            Text(Copy.Skills.notChecked).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        default:
            Text(Copy.Skills.local).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}

// MARK: - The side column

/// A selected skill: where it comes from, its versions, the tool's state, the Mac permissions in words, the start of
/// its instructions, and Remove.
struct SkillDetailColumn: View {
    let skill: InstalledSkill
    let busy: Bool
    /// "‹ N skills" when DR-27 hid the list.
    var backLabel: String? = nil
    var onShowList: () -> Void = {}
    var onClose: () -> Void = {}
    var onUpdate: () -> Void = {}
    var onRefresh: () -> Void = {}
    var onRemove: () -> Void = {}
    @State private var confirmRemove = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                DetailHeader(title: skill.name, backLabel: backLabel, onShowList: onShowList,
                             closeHelp: Copy.Skills.closeHelp, onClose: onClose)
                source
                if let tool = skill.tool, tool.text == "older" {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        Label(Copy.Skills.olderLine(tool: tool.version, text: tool.textVersion),
                              systemImage: "exclamationmark.triangle")
                            .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.warning)
                            .fixedSize(horizontal: false, vertical: true)
                        NeutralButton(title: Copy.Skills.refreshInstructions, size: .compact,
                                      help: Copy.Skills.refreshHelp, action: onRefresh)
                    }
                }
                if skill.status == "update" {
                    SkillChangesPopover(update: skill.update, onUpdate: onUpdate)
                        .settingsCardSurface()
                }
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    if !skill.version.label.isEmpty { fact(Copy.Skills.versionLabel, skill.version.label) }
                    if let tool = skill.tool, tool.installed {
                        fact(Copy.Skills.toolLabel, Copy.Skills.toolLine(tool.version, from: tool.from))
                    }
                    if let line = skill.permissions?.line {
                        fact(Copy.Skills.checkedForCicada, line)
                        Text(Copy.Skills.otherAppsDiffer).font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary).fixedSize(horizontal: false, vertical: true)
                    }
                    // DR-58 — a day in the app's one day grammar ("Yesterday", "Oct 3"), never a raw ISO stamp.
                    if let day = ISODay(skill.details.installedAt) {
                        fact(Copy.Skills.installedLabel, RelativeDay.phrase(day, today: .today()))
                    }
                    if let licence = skill.details.licence { fact(Copy.Skills.licenceLabel, licence) }
                    ForEach(skill.details.folders, id: \.path) { folder in
                        fact(Copy.Skills.foldersLabel,
                             folder.path + (folder.linked ? " · \(Copy.Skills.linkedFolder)" : ""))
                    }
                }
                if let excerpt = skill.details.excerpt, !excerpt.isEmpty {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        SectionLabel(Copy.Skills.instructions)
                        Text(excerpt).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                            .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                    }
                }
                NeutralButton(title: Copy.Skills.removeEllipsis, size: .compact, isDisabled: busy,
                              help: Copy.Skills.removeHelp) { confirmRemove = true }
                    .confirmationDialog(Copy.Skills.removeTitle(skill.name), isPresented: $confirmRemove) {
                        Button(Copy.Skills.remove, role: .destructive, action: onRemove)
                    } message: {
                        Text(Copy.Skills.removeHelp)
                    }
            }
            .padding(.horizontal, CicadaTheme.spacingXL)
            .padding(.bottom, CicadaTheme.spacingXL)
            // DR-36 — the detail takes the columns' remainder; its text keeps the focus card's measure, as Sources'.
            .frame(maxWidth: CicadaTheme.scaled(ColumnLayout.questionMaxWidth + 64), alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private var source: some View {
        if let url = skill.source.url.flatMap(URL.init(string:)) {
            Link(skill.source.label + " ↗", destination: url).font(CicadaTheme.metaFont)
        } else {
            Text(skill.source.kind == "cicada" ? Copy.Skills.madeByCicada
                 : (skill.source.kind == "local" ? Copy.Skills.onThisMac : skill.source.label))
                .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private func fact(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
            Text(label).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(84), alignment: .leading)
            Text(value).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
        }
    }
}

/// What an update brings: "0.1.13 → 0.2.0", each change (a commit that touched the skill, or a release and its
/// notes), the link to the whole story, and the one Update.
struct SkillChangesPopover: View {
    let update: SkillUpdate
    let onUpdate: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text(Copy.Skills.changesTitle(from: update.from, to: update.latest))
                .font(CicadaTheme.rowFont)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(Array((update.changes ?? []).enumerated()), id: \.offset) { _, change in
                        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                                Text(change.title).font(CicadaTheme.bodyFont)
                                Spacer(minLength: CicadaTheme.spacingSM)
                                if let date = change.date {
                                    Text(date).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                                        .monospacedDigit()
                                }
                            }
                            if let detail = change.detail, !detail.isEmpty {
                                Text(detail).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                }
            }
            .frame(maxHeight: CicadaTheme.scaled(260))
            HStack {
                if let link = update.link.flatMap(URL.init(string:)) {
                    Link(update.linkLabel ?? Copy.Skills.whatChanged, destination: link).font(CicadaTheme.metaFont)
                }
                Spacer()
                NeutralButton(title: Copy.Skills.update, size: .compact, action: onUpdate)
            }
        }
        .padding(CicadaTheme.spacingMD)
    }
}

// MARK: - Other rows

/// One catalog suggestion (Discover): what it lets an agent do, and its one way in. No picture.
struct SuggestedSkillRow: View {
    let skill: SuggestedSkill
    let uv: UvInfo
    let busy: Bool
    var onInstall: () -> Void = {}
    @State private var copied = false

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(skill.title).font(CicadaTheme.rowFont)
                    if let url = skill.sourceUrl.flatMap(URL.init(string:)) {
                        Link((skill.publisher ?? url.host() ?? "") + " ↗", destination: url).font(CicadaTheme.metaFont)
                    }
                }
                Text(skill.summary).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(2)
                if skill.method == "tool" && !uv.present {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(Copy.Skills.needsUv).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                        if let url = URL(string: uv.installUrl) {
                            Link(Copy.Skills.getUv, destination: url).font(CicadaTheme.metaFont)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            action
        }
        .padding(.vertical, CicadaTheme.spacingSM)
    }

    @ViewBuilder
    private var action: some View {
        if skill.method == "manual" {
            if let text = skill.manual.first?.text {
                NeutralButton(title: copied ? Copy.Skills.copied : Copy.Skills.copyForAgent, size: .compact,
                              help: Copy.Skills.setUpInAgent) {
                    AppPasteboard.copy(text)
                    copied = true
                }
            }
        } else {
            NeutralButton(title: busy ? Copy.Skills.installing : Copy.Skills.install, size: .compact,
                          isDisabled: busy || (skill.method == "tool" && !uv.present),
                          disabledHelp: skill.method == "tool" && !uv.present ? Copy.Skills.needsUv : nil,
                          action: onInstall)
        }
    }
}

/// An agent's ask, one line above the table: "Claude Code wants to add pdf-forms · Review".
struct SkillRequestLine: View {
    let request: SkillRequest
    let agents: [SkillAgentInfo]
    let busy: Bool
    var onReview: () -> Void = {}
    var onApprove: () -> Void = {}
    var onDismiss: () -> Void = {}

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(SkillRequestWords.line(request, agents: agents)).font(CicadaTheme.bodyFont).lineLimit(1)
                .help(request.reason)
            Spacer(minLength: CicadaTheme.spacingSM)
            TextButton(title: Copy.Skills.dismiss, inline: true, action: onDismiss)
            if request.action == "install" {
                NeutralButton(title: Copy.Skills.review, size: .compact, action: onReview)
            } else {
                NeutralButton(title: Copy.Skills.approve, size: .compact, isDisabled: busy, action: onApprove)
            }
        }
    }
}

/// A skill an agent drafted, held until the person publishes it.
struct DraftSkillRow: View {
    let draft: SkillDraft
    let busy: Bool
    var onRead: () -> Void = {}
    var onPublish: () -> Void = {}
    var onDiscard: () -> Void = {}
    var onKind: (String) -> Void = { _ in }

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(draft.name).font(CicadaTheme.rowFont)
                    Text(Copy.Skills.madeBy(draft.authorLabel)).font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Text(draft.description).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            SkillKindMenu(kind: draft.kind, busy: busy, onChoose: onKind)
            TextButton(title: Copy.Skills.discard, inline: true, action: onDiscard)
            TextButton(title: Copy.Skills.readIt, inline: true, action: onRead)
            NeutralButton(title: Copy.Skills.publish, size: .compact, isDisabled: busy,
                          help: Copy.Skills.publishHelp, action: onPublish)
        }
        .padding(.vertical, CicadaTheme.spacingSM)
    }
}


// MARK: - Kinds and plugins (G201 slice (a), TODO ruling 35)

/// A skill's kind as one quiet word — "About you", "Generic", "Not sure" — and a pull-down to correct it, the Agents
/// cell's pattern (DR-40 `TextButton`, a popover of plain rows). "your choice" follows the word once the person chose.
struct SkillKindMenu: View {
    let kind: SkillKind
    let busy: Bool
    var onChoose: (String) -> Void = { _ in }
    @State private var open = false

    var body: some View {
        TextButton(title: SkillPluginWords.kind(kind.kind) + " ▾", help: Copy.Skills.kindHelp, inline: true) {
            open.toggle()
        }
        .disabled(busy || kind.key.isEmpty)
        .accessibilityLabel("\(Copy.Skills.kindColumn): \(SkillPluginWords.kind(kind.kind))"
                            + (kind.by == "person" ? ", \(Copy.Skills.kindYours)" : ""))
        .popover(isPresented: $open, arrowEdge: .bottom) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                ForEach(SkillKind.choices, id: \.self) { choice in
                    Button {
                        open = false
                        onChoose(choice)
                    } label: {
                        HStack(spacing: CicadaTheme.spacingSM) {
                            Image(systemName: "checkmark")
                                .font(CicadaTheme.icon(.inline)).frame(width: CicadaTheme.scaled(16))
                                .opacity(choice == kind.kind ? 1 : 0)
                            Text(SkillPluginWords.kind(choice)).font(CicadaTheme.bodyFont)
                            if choice == kind.kind, kind.by == "person" {
                                Text(Copy.Skills.kindYours).font(CicadaTheme.metaFont)
                                    .foregroundStyle(CicadaTheme.textTertiary)
                            }
                            Spacer(minLength: CicadaTheme.spacingSM)
                        }
                        .padding(.horizontal, CicadaTheme.spacingSM)
                        .frame(height: CicadaTheme.scaled(28))
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.cicadaPlain)
                }
            }
            .padding(CicadaTheme.spacingSM)
            .frame(minWidth: CicadaTheme.scaled(200))
        }
    }
}

/// Claude Code's plugins, read-only, under the table on the same columns: the plugin (its name and "v1.2.0 ·
/// marketplace"), the agent it belongs to, and On / Off / Per project; then each skill it brings, indented, with its
/// kind. Nothing here toggles a plugin — the line under the label says where the person does (DR-38: said once).
struct SkillPluginsGroup: View {
    let plugins: [SkillPlugin]
    let busy: Set<String>
    var onKind: (SkillKind, String) -> Void = { _, _ in }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                SectionLabel(Copy.Skills.pluginsTitle)
                Text(Copy.Skills.pluginsLine).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            .padding(.horizontal, CicadaTheme.spacingSM).padding(.bottom, CicadaTheme.spacingSM)
            ForEach(plugins) { plugin in
                Divider().overlay(CicadaTheme.border)
                SkillPluginRow(plugin: plugin)
                ForEach(plugin.skills) { skill in
                    SkillPluginSkillRow(skill: skill, busy: busy.contains(skill.kind.key)) { choice in
                        onKind(skill.kind, choice)
                    }
                }
            }
        }
    }
}

struct SkillPluginRow: View {
    let plugin: SkillPlugin

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(plugin.name).font(CicadaTheme.rowFont).lineLimit(1)
                Text(plugin.skills.isEmpty ? [SkillPluginWords.meta(plugin), Copy.Skills.pluginNoSkills]
                        .filter { !$0.isEmpty }.joined(separator: " · ") : SkillPluginWords.meta(plugin))
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
                    .monospacedDigit()
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Text(Copy.Skills.pluginsHarness).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.agentsWidth), alignment: .leading)
            Color.clear.frame(width: CicadaTheme.scaled(SkillsTableLayout.kindWidth), height: 1)
            Text(SkillPluginWords.state(plugin)).font(CicadaTheme.metaFont)
                .foregroundStyle(plugin.enabled == true ? CicadaTheme.textSecondary : CicadaTheme.textTertiary)
                .help(plugin.note ?? Copy.Skills.pluginsLine)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.statusWidth), alignment: .leading)
        }
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.spacingSM)
        .accessibilityElement(children: .combine)
    }
}

struct SkillPluginSkillRow: View {
    let skill: SkillPlugin.Skill
    let busy: Bool
    var onKind: (String) -> Void = { _ in }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(skill.name).font(CicadaTheme.bodyFont).lineLimit(1)
                Text(skill.description).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            .padding(.leading, CicadaTheme.spacingLG)
            .frame(maxWidth: .infinity, alignment: .leading)
            Text(skill.userOnly ? Copy.Skills.userOnly : "").font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary).help(skill.userOnly ? Copy.Skills.userOnlyHelp : "")
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.agentsWidth), alignment: .leading)
            SkillKindMenu(kind: skill.kind, busy: busy, onChoose: onKind)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.kindWidth), alignment: .leading)
            Color.clear.frame(width: CicadaTheme.scaled(SkillsTableLayout.statusWidth), height: 1)
        }
        .padding(.vertical, CicadaTheme.scaled(4))
        .padding(.horizontal, CicadaTheme.spacingSM)
    }
}
