import AppKit
import SwiftUI

/// The Skills page (owner 2026-10-15) — the tenth rail page, ⌘0, at the end so no shortcut moves (DR-22): every
/// skill on this Mac's coding agents, where it came from, whether it is current, and which agents have it; Cicada's
/// suggestions; what agents drafted; what agents asked for. Applies DR-22, DR-25 (the eyebrow), DR-37, DR-39 (Details
/// start collapsed), DR-40 (one primary: Add a skill's Install), DR-41, DR-43 (never blank over good data), DR-44,
/// DR-47, DR-48 and DR-59.
///
/// The app decides nothing: the backend reads the folders, checks upstream, and writes every file
/// (`api/services/skill_store.py`); a click here is one route.
struct SkillsPage: View {
    @State private var model = SkillsPageModel()
    @State private var adding: SkillAddInput?
    @State private var openDetails: Set<String> = []
    @State private var publishing: SkillDraft?
    @State private var reading: SkillDraft?

    var body: some View {
        SkillsPageView(model: model, openDetails: $openDetails,
                       onAdd: { adding = SkillAddInput(source: "", requestId: nil, agents: []) },
                       onReview: { request in
                           adding = SkillAddInput(source: request.source ?? "", requestId: request.id,
                                                  agents: request.agents)
                       },
                       onPublish: { publishing = $0 }, onRead: { reading = $0 })
            .background(CicadaTheme.bgBase)
            .task { await model.appeared() }
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

/// What the Add sheet opens with: empty from the page's +, or an agent's request to review.
struct SkillAddInput: Identifiable {
    let id = UUID()
    let source: String
    let requestId: String?
    let agents: [String]
}

/// The page, pure over the model's state (an offscreen render can feed it fixtures).
struct SkillsPageView: View {
    let model: SkillsPageModel
    @Binding var openDetails: Set<String>
    var onAdd: () -> Void = {}
    var onReview: (SkillRequest) -> Void = { _ in }
    var onPublish: (SkillDraft) -> Void = { _ in }
    var onRead: (SkillDraft) -> Void = { _ in }

    private var eyebrow: String {
        Eyebrow.text(Copy.Skills.page, (model.data?.installed.count ?? 0) == 0 ? ""
                     : Copy.Skills.eyebrowCount(model.data?.installed.count ?? 0))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            EyebrowRow(eyebrow: eyebrow) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(checkedLine)
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                    NeutralButton(title: model.checking ? Copy.Skills.checking : Copy.Skills.check, size: .compact,
                                  isDisabled: model.checking, help: Copy.Skills.checkHelp) {
                        Task { await model.checkNow() }
                    }
                    if !model.updatesAvailable.isEmpty {
                        NeutralButton(title: Copy.Skills.updateAll, size: .compact,
                                      isDisabled: model.busy.contains("update-all"),
                                      help: Copy.Skills.updateAllHelp(model.updatesAvailable.count)) {
                            Task { await model.updateAll() }
                        }
                    }
                    IconButton(systemName: "plus", help: Copy.Skills.add, accessibilityLabel: Copy.Skills.add,
                               action: onAdd)
                }
            }
            if let message = model.message {
                Label(message, systemImage: "exclamationmark.circle")
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .padding(.horizontal, CicadaTheme.spacingGutter)
                    .padding(.bottom, CicadaTheme.spacingMD)
            }
            ForEach(model.jobs) { job in
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    Text(Copy.Skills.jobRunning(job.step ?? job.label))
                        .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                }
                .padding(.horizontal, CicadaTheme.spacingGutter)
                .padding(.bottom, CicadaTheme.spacingSM)
            }
            content
        }
    }

    private var checkedLine: String {
        guard let stamp = model.data?.checkedAt, let date = ISO8601DateFormatter().date(from: stamp) else {
            return Copy.Skills.neverChecked
        }
        return Copy.Skills.checkedAgo(RelativeDateTimeFormatter().localizedString(for: date, relativeTo: Date()))
    }

    @ViewBuilder
    private var content: some View {
        switch (model.phase, model.data) {
        case (.failed(let why), nil):
            EmptyStateView(title: Copy.Skills.loadFailedTitle, message: why)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case (_, nil):
            Text(Copy.Skills.loading).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case (_, let data?):
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXL) {
                    if !data.requests.isEmpty { requests(data) }
                    installed(data)
                    if !data.suggested.isEmpty { suggested(data) }
                    made(data)
                }
                .frame(maxWidth: CicadaTheme.scaled(880), alignment: .leading)
                .padding(.horizontal, CicadaTheme.spacingGutter)
                .padding(.bottom, CicadaTheme.scaled(72))
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    // MARK: Sections

    private func requests(_ data: SkillsPageData) -> some View {
        section(Copy.Skills.waiting) {
            ForEach(data.requests) { request in
                SkillRequestRow(request: request, agents: data.agents, busy: model.busy.contains(request.id),
                                onReview: { onReview(request) },
                                onApprove: { Task { await model.approve(request) } },
                                onDismiss: { Task { await model.dismiss(request) } })
            }
        }
    }

    @ViewBuilder
    private func installed(_ data: SkillsPageData) -> some View {
        section(Copy.Skills.installed) {
            if data.installed.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(Copy.Skills.emptyInstalledTitle).font(CicadaTheme.bodyFont)
                    Text(Copy.Skills.emptyInstalledMessage).font(CicadaTheme.metaFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                .padding(CicadaTheme.spacingMD)
            }
            ForEach(Array(data.installed.enumerated()), id: \.element.id) { index, skill in
                if index > 0 { Divider().overlay(CicadaTheme.border) }
                InstalledSkillRow(skill: skill, busy: model.busy.contains(skill.name),
                                  detailsOpen: openDetails.contains(skill.name),
                                  onDetails: {
                                      Instant.run {
                                          if openDetails.contains(skill.name) { openDetails.remove(skill.name) }
                                          else { openDetails.insert(skill.name) }
                                      }
                                  },
                                  onToggle: { agent in Task { await model.toggle(skill, agent: agent) } },
                                  onUpdate: { Task { await model.update(skill.name) } },
                                  onRefresh: { Task { await model.refresh(skill.name) } },
                                  onRemove: { Task { await model.remove(skill.name) } })
            }
        }
    }

    private func suggested(_ data: SkillsPageData) -> some View {
        section(Copy.Skills.suggested) {
            ForEach(Array(data.suggested.enumerated()), id: \.element.id) { index, item in
                if index > 0 { Divider().overlay(CicadaTheme.border) }
                SuggestedSkillRow(skill: item, uv: data.uv, busy: model.busy.contains(item.id)) {
                    Task { await model.installSuggested(item.id, agents: []) }
                }
            }
        }
    }

    @ViewBuilder
    private func made(_ data: SkillsPageData) -> some View {
        section(Copy.Skills.made) {
            if data.drafts.isEmpty && data.noticed.isEmpty {
                Text(Copy.Skills.madeEmpty).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .padding(CicadaTheme.spacingMD)
            }
            ForEach(data.drafts) { draft in
                DraftSkillRow(draft: draft, busy: model.busy.contains(draft.name), onRead: { onRead(draft) },
                              onPublish: { onPublish(draft) },
                              onDiscard: { Task { await model.discard(draft.name) } })
            }
            if !data.noticed.isEmpty {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    Text(Copy.Skills.noticedTitle).font(CicadaTheme.font(size: 13, weight: .medium))
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
                .padding(CicadaTheme.spacingMD)
            }
        }
    }

    private func section<Content: View>(_ title: String, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            SectionLabel(title)
            VStack(alignment: .leading, spacing: 0) { content() }
                .frame(maxWidth: .infinity, alignment: .leading)
                .settingsCardSurface()
        }
    }
}

// MARK: - Rows

/// One installed skill: its name and line, where it came from, its version and whether it is current, the agents
/// that have it (a checkbox each), a tool skill's state, the permissions in words; Details behind a disclosure.
struct InstalledSkillRow: View {
    let skill: InstalledSkill
    let busy: Bool
    let detailsOpen: Bool
    var onDetails: () -> Void = {}
    var onToggle: (SkillAgentState) -> Void = { _ in }
    var onUpdate: () -> Void = {}
    var onRefresh: () -> Void = {}
    var onRemove: () -> Void = {}
    @State private var hovering = false
    @State private var showChanges = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(skill.name).font(CicadaTheme.font(size: 14, weight: .medium))
                source
                if !skill.version.label.isEmpty { Tag(text: skill.version.label) }
                Spacer(minLength: CicadaTheme.spacingSM)
                updateState
            }
            if !skill.description.isEmpty {
                Text(skill.description).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .lineLimit(2).fixedSize(horizontal: false, vertical: true)
            }
            agents
            if let tool = skill.tool { toolLine(tool) }
            if let line = skill.permissions?.line {
                Label(line, systemImage: skill.permissions?.ready == true ? "checkmark.shield" : "lock.shield")
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                TextButton(title: detailsOpen ? Copy.Skills.hideDetails : Copy.Skills.details, inline: true,
                           action: onDetails)
                Spacer()
            }
            if detailsOpen { details }
        }
        .padding(CicadaTheme.spacingMD)
        .background(hovering ? CicadaTheme.bgHover : Color.clear)
        .onHover { hovering = $0 }
        .opacity(busy ? NeutralButton.disabledOpacity : 1)
        .disabled(busy)
    }

    @ViewBuilder
    private var source: some View {
        if let url = skill.source.url.flatMap(URL.init(string:)) {
            Link(skill.source.label, destination: url).font(CicadaTheme.metaFont)
        } else {
            Text(skill.source.kind == "cicada" ? Copy.Skills.madeByCicada
                 : (skill.source.kind == "local" ? Copy.Skills.onThisMac : skill.source.label))
                .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    @ViewBuilder
    private var updateState: some View {
        if skill.update.state == "available" {
            // The owner (2026-10-15): one quiet chip; what changed opens from it, never spelled out on the row.
            NeutralButton(title: Copy.Skills.updateAvailable, size: .compact) { showChanges = true }
                .popover(isPresented: $showChanges, arrowEdge: .bottom) {
                    SkillChangesPopover(update: skill.update) {
                        showChanges = false
                        onUpdate()
                    }
                }
        } else if skill.update.state == "current" {
            Text(Copy.Skills.upToDate).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
        }
    }

    private var agents: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            ForEach(skill.agents) { agent in
                Toggle(agent.label, isOn: Binding(get: { agent.isOn }, set: { _ in onToggle(agent) }))
                    .toggleStyle(.checkbox)
                    .font(CicadaTheme.metaFont)
                    .disabled(!agent.canToggle)
                    .help(agent.note ?? Copy.Skills.agentHelp(agent.label, on: agent.isOn))
            }
        }
    }

    @ViewBuilder
    private func toolLine(_ tool: SkillTool) -> some View {
        if !tool.installed {
            Label(Copy.Skills.toolMissing, systemImage: "wrench.and.screwdriver")
                .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
        } else if tool.text == "older" {
            HStack(spacing: CicadaTheme.spacingSM) {
                Label(Copy.Skills.olderText, systemImage: "arrow.triangle.2.circlepath")
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.warning)
                NeutralButton(title: Copy.Skills.refresh, size: .compact, help: Copy.Skills.refreshHelp,
                              action: onRefresh)
            }
        }
    }

    private var details: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            ForEach(skill.details.folders, id: \.path) { folder in
                detail(Copy.Skills.foldersLabel, [folder.path, folder.linked ? Copy.Skills.linkedFolder : nil,
                                                  folder.byCicada ? Copy.Skills.byCicada : nil]
                    .compactMap { $0 }.joined(separator: " · "))
            }
            if let commit = skill.details.commit {
                detail(Copy.Skills.commitLabel, [String(commit.prefix(12)), skill.details.ref].compactMap { $0 }
                    .joined(separator: " · "))
            }
            if let tool = skill.tool, tool.installed {
                detail(Copy.Skills.toolLabel, "\(tool.command) " + Copy.Skills.toolLine(tool.version, from: tool.from))
            }
            if let when = skill.details.installedAt { detail(Copy.Skills.installedLabel, String(when.prefix(10))) }
            if let licence = skill.details.licence { detail(Copy.Skills.licenceLabel, licence) }
            HStack {
                Spacer()
                NeutralButton(title: Copy.Skills.remove, size: .compact, help: Copy.Skills.removeHelp,
                              action: onRemove)
            }
        }
        .padding(.top, CicadaTheme.spacingXS)
    }

    private func detail(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
            Text(label).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                .frame(width: CicadaTheme.scaled(80), alignment: .leading)
            Text(value).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary).textSelection(.enabled)
        }
    }
}

/// One catalog suggestion: what it lets an agent do, and its one way in.
struct SuggestedSkillRow: View {
    let skill: SuggestedSkill
    let uv: UvInfo
    let busy: Bool
    var onInstall: () -> Void = {}
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Image(systemName: skill.symbol ?? "sparkles").font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textTertiary)
                Text(skill.title).font(CicadaTheme.font(size: 14, weight: .medium))
                if let url = skill.sourceUrl.flatMap(URL.init(string:)) {
                    Link(skill.publisher ?? url.host() ?? "", destination: url).font(CicadaTheme.metaFont)
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                action
            }
            Text(skill.summary).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if let reach = skill.reach {
                Text(reach).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            if skill.method == "tool" && !uv.present {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text(Copy.Skills.needsUv).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    if let url = URL(string: uv.installUrl) {
                        Link(Copy.Skills.getUv, destination: url).font(CicadaTheme.metaFont)
                    }
                }
            }
        }
        .padding(CicadaTheme.spacingMD)
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

/// One agent's ask, waiting for the person: review an install (the Add sheet shows the files), or do it.
struct SkillRequestRow: View {
    let request: SkillRequest
    let agents: [SkillAgentInfo]
    let busy: Bool
    var onReview: () -> Void = {}
    var onApprove: () -> Void = {}
    var onDismiss: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(SkillRequestWords.line(request, agents: agents)).font(CicadaTheme.bodyFont)
                Spacer(minLength: CicadaTheme.spacingSM)
                TextButton(title: Copy.Skills.dismiss, inline: true, action: onDismiss)
                if request.action == "install" {
                    NeutralButton(title: Copy.Skills.review, size: .compact, action: onReview)
                } else {
                    NeutralButton(title: Copy.Skills.approve, size: .compact, isDisabled: busy, action: onApprove)
                }
            }
            if !request.reason.isEmpty {
                Text(request.reason).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            }
        }
        .padding(CicadaTheme.spacingMD)
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
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(draft.name).font(CicadaTheme.font(size: 14, weight: .medium))
                Text(Copy.Skills.madeBy(draft.authorLabel)).font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                Tag(text: Copy.Skills.held)
                Spacer(minLength: CicadaTheme.spacingSM)
                TextButton(title: Copy.Skills.discard, inline: true, action: onDiscard)
                TextButton(title: Copy.Skills.readIt, inline: true, action: onRead)
                NeutralButton(title: Copy.Skills.publish, size: .compact, isDisabled: busy,
                              help: Copy.Skills.publishHelp, action: onPublish)
            }
            Text(draft.description).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
            if let reason = draft.reason, !reason.isEmpty {
                Text(reason).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
        .padding(CicadaTheme.spacingMD)
    }
}

/// What an update brings: each change (a commit that touched the skill, or a release and its notes), the link to
/// the whole story, and the one Update.
struct SkillChangesPopover: View {
    let update: SkillUpdate
    let onUpdate: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text([Copy.Skills.whatChanged, update.latest].compactMap { $0 }.joined(separator: " · "))
                .font(CicadaTheme.font(size: 13, weight: .medium))
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    ForEach(Array((update.changes ?? []).enumerated()), id: \.offset) { _, change in
                        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                                Text(change.title).font(CicadaTheme.bodyFont)
                                Spacer(minLength: CicadaTheme.spacingSM)
                                if let date = change.date { Text(date).font(CicadaTheme.metaFont)
                                    .foregroundStyle(CicadaTheme.textTertiary).monospacedDigit() }
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
        .frame(width: CicadaTheme.scaled(360))
    }
}
