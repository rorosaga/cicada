import AppKit
import SwiftUI

/// The Skills page (owner 2026-10-15, third take) — the tenth rail page, after Looks (DR-22). One plain table: the
/// skill (its name and one muted line), the agents that have it (one pull-down that ticks agents on and off), and one
/// quiet word of status; details in a side column when a row is selected; adding a skill from one field in the
/// header (⌘N); an agent's request as one line above the table; tabs Installed · Discover · Drafts. No pictures on
/// rows. Applies DR-22, DR-25, DR-37, DR-40, DR-41, DR-43 (never blank over good data), DR-44, DR-45, DR-47, DR-48,
/// DR-59.
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
    @State private var addText = ""
    @FocusState private var addFocused: Bool
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        SkillsPageView(model: model, tab: $tab, selected: $selected, addText: $addText, addFocused: $addFocused,
                       onAdd: { source in
                           adding = SkillAddInput(source: source, requestId: nil, agents: [])
                           addText = ""
                       },
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
                    tab = nil
                    selected = nil
                }
            }
            .background {
                // ⌘N — the add field (a page-local key; no menu item claims it on this page).
                Button("") { addFocused = true }.keyboardShortcut("n", modifiers: .command).hidden()
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

/// The page, pure over the model's state.
struct SkillsPageView: View {
    let model: SkillsPageModel
    @Binding var tab: SkillsTab?
    @Binding var selected: String?
    @Binding var addText: String
    var addFocused: FocusState<Bool>.Binding
    var onAdd: (String) -> Void = { _ in }
    var onReview: (SkillRequest) -> Void = { _ in }
    var onPublish: (SkillDraft) -> Void = { _ in }
    var onRead: (SkillDraft) -> Void = { _ in }

    static let detailWidth: CGFloat = 360

    private var data: SkillsPageData? { model.data }
    private var selectedSkill: InstalledSkill? {
        tab == nil ? selected.flatMap { name in data?.installed.first { $0.name == name } } : nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: Copy.Skills.page) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    TextField(Copy.Skills.addPlaceholder, text: $addText)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: CicadaTheme.scaled(340))
                        .focused(addFocused)
                        .onSubmit { submitAdd() }
                        .help(Copy.Skills.addHelp)
                    KeyHint("⌘N")
                    IconButton(systemName: "arrow.clockwise", help: Copy.Skills.checkHelp,
                               accessibilityLabel: Copy.Skills.check) { Task { await model.checkNow() } }
                        .disabled(model.checking)
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
            TextTabs(tabs: [TextTab(id: nil, label: Copy.Skills.installed, count: data?.installed.count),
                            TextTab(id: .discover, label: Copy.Skills.discover, count: nil),
                            TextTab(id: .drafts, label: Copy.Skills.drafts,
                                    count: (data?.drafts.count ?? 0) == 0 ? nil : data?.drafts.count)],
                     selection: $tab)
                .padding(.horizontal, CicadaTheme.spacingGutter)
                .padding(.bottom, CicadaTheme.spacingMD)
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
            HStack(alignment: .top, spacing: 0) {
                content.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                if let skill = selectedSkill {
                    SkillDetailColumn(skill: skill, busy: model.busy.contains(skill.name),
                                      onClose: { Instant.run { selected = nil } },
                                      onUpdate: { Task { await model.update(skill.name) } },
                                      onRefresh: { Task { await model.refresh(skill.name) } },
                                      onRemove: {
                                          Instant.run { selected = nil }
                                          Task { await model.remove(skill.name) }
                                      })
                        .frame(width: CicadaTheme.scaled(Self.detailWidth))
                        .columnEdge()   // DR-11: the one permitted rule, from the theme
                }
            }
        }
    }

    private func submitAdd() {
        let text = addText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty { onAdd(text) }
    }

    @ViewBuilder
    private var content: some View {
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
                    case nil: installed(data)
                    case .discover?: discover(data)
                    case .drafts?: drafts(data)
                    }
                }
                .padding(.horizontal, selectedSkill == nil ? CicadaTheme.spacingGutter : CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.scaled(72))
            }
        }
    }

    // MARK: Installed: the table

    @ViewBuilder
    private func installed(_ data: SkillsPageData) -> some View {
        if data.installed.isEmpty {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text(Copy.Skills.emptyInstalledTitle).font(CicadaTheme.bodyFont)
                Text(Copy.Skills.emptyInstalledMessage).font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
        } else {
            VStack(alignment: .leading, spacing: 0) {
                SkillsTableHeader()
                ForEach(data.installed) { skill in
                    Divider().overlay(CicadaTheme.border)
                    SkillTableRow(skill: skill, selected: skill.name == selected,
                                  busy: model.busy.contains(skill.name),
                                  onSelect: { Instant.run { selected = selected == skill.name ? nil : skill.name } },
                                  onToggle: { agent in Task { await model.toggle(skill, agent: agent) } },
                                  onUpdate: { Task { await model.update(skill.name) } },
                                  onRefresh: { Task { await model.refresh(skill.name) } })
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
                              onDiscard: { Task { await model.discard(draft.name) } })
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
    static let statusWidth: CGFloat = 120
}

struct SkillsTableHeader: View {
    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            SectionLabel(Copy.Skills.skillColumn).frame(maxWidth: .infinity, alignment: .leading)
            SectionLabel(Copy.Skills.agentsColumn)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.agentsWidth), alignment: .leading)
            SectionLabel(Copy.Skills.statusColumn)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.statusWidth), alignment: .leading)
        }
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.spacingSM)
    }
}

/// One skill: its name and one muted line, the agents pull-down, one word of status. A click selects it (details in
/// the side column); DR-48: hover `bgHover`, selected `bgSelected`, never a lift.
struct SkillTableRow: View {
    let skill: InstalledSkill
    let selected: Bool
    let busy: Bool
    var onSelect: () -> Void = {}
    var onToggle: (SkillAgentState) -> Void = { _ in }
    var onUpdate: () -> Void = {}
    var onRefresh: () -> Void = {}
    @State private var hovering = false

    var body: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(skill.name).font(CicadaTheme.font(size: 13, weight: .medium)).lineLimit(1)
                Text(skill.description).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .onTapGesture(perform: onSelect)
            SkillAgentsPullDown(agents: skill.agents, busy: busy, onToggle: onToggle)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.agentsWidth), alignment: .leading)
            SkillStatusCell(skill: skill, onUpdate: onUpdate, onRefresh: onRefresh)
                .frame(width: CicadaTheme.scaled(SkillsTableLayout.statusWidth), alignment: .leading)
        }
        .padding(.vertical, CicadaTheme.spacingSM)
        .padding(.horizontal, CicadaTheme.spacingSM)
        .background(selected ? CicadaTheme.bgSelected : (hovering ? CicadaTheme.bgHover : Color.clear))
        .onHover { hovering = $0 }
        .opacity(busy ? NeutralButton.disabledOpacity : 1)
        .accessibilityElement(children: .contain)
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
    var onClose: () -> Void = {}
    var onUpdate: () -> Void = {}
    var onRefresh: () -> Void = {}
    var onRemove: () -> Void = {}
    @State private var confirmRemove = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                DetailHeader(title: skill.name, closeHelp: Copy.Skills.closeHelp, onClose: onClose)
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
                .font(CicadaTheme.font(size: 13, weight: .medium))
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
                    Text(skill.title).font(CicadaTheme.font(size: 13, weight: .medium))
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

    var body: some View {
        HStack(alignment: .center, spacing: CicadaTheme.spacingMD) {
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(draft.name).font(CicadaTheme.font(size: 13, weight: .medium))
                    Text(Copy.Skills.madeBy(draft.authorLabel)).font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
                Text(draft.description).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            TextButton(title: Copy.Skills.discard, inline: true, action: onDiscard)
            TextButton(title: Copy.Skills.readIt, inline: true, action: onRead)
            NeutralButton(title: Copy.Skills.publish, size: .compact, isDisabled: busy,
                          help: Copy.Skills.publishHelp, action: onPublish)
        }
        .padding(.vertical, CicadaTheme.spacingSM)
    }
}
