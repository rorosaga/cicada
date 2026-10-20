import SwiftUI

/// Add a skill (owner 2026-10-15): paste a GitHub link, `owner/repo` or an `npx skills add …` line; Cicada shows the
/// skill — its instructions, its files (scripts called out), where it comes from and the exact version — and only
/// then offers Install, which installs exactly what was shown, fixed to that commit. The one primary action on this
/// surface (DR-40). An agent's install request opens here too, so the person always sees the files first.
struct AddSkillSheet: View {
    let model: SkillsPageModel
    let input: SkillAddInput
    let agents: [SkillAgentInfo]
    let close: () -> Void

    @State private var source = ""
    @State private var looking = false
    @State private var preview: SkillPreview?
    @State private var problem: String?
    @State private var chosen: Set<String> = []
    @State private var installing = false
    @FocusState private var fieldFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.Skills.addTitle).font(CicadaTheme.headingFont)
            Text(Copy.Skills.addLead).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: CicadaTheme.spacingSM) {
                TextField(Copy.Skills.addPlaceholder, text: $source)
                    .focused($fieldFocused)
                    .cicadaField(isFocused: fieldFocused)
                    .onSubmit { look(choose: nil) }
                NeutralButton(title: looking ? Copy.Skills.looking : Copy.Skills.look, size: .compact,
                              isDisabled: looking || source.trimmingCharacters(in: .whitespaces).isEmpty) {
                    look(choose: nil)
                }
            }
            if let problem {
                Label(problem, systemImage: "exclamationmark.circle")
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let choices = preview?.choices, !choices.isEmpty {
                Text(Copy.Skills.chooseOne).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                ScrollView {
                    VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                        ForEach(choices) { choice in
                            TextButton(title: choice.name, inline: true) { look(choose: choice.path) }
                        }
                    }
                }
                .frame(maxHeight: CicadaTheme.scaled(200))
            } else if let preview, preview.planId != nil {
                shown(preview)
            }
            HStack(spacing: CicadaTheme.spacingSM) {
                if installing { ProgressView().controlSize(.small) }
                Spacer()
                TextButton(title: Copy.Skills.cancel, action: close)
                    .keyboardShortcut(.cancelAction)
                if let planId = preview?.planId {
                    PrimaryActionButton(title: Copy.Skills.installPinned) { install(planId) }
                        .disabled(chosen.isEmpty || installing)
                        .help(Copy.Skills.installPinnedHelp)
                }
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(620))
        .onAppear {
            source = input.source
            chosen = Set(input.agents.isEmpty ? agents.prefix(1).map(\.id) : input.agents)
            if !input.source.isEmpty { look(choose: nil) } else { fieldFocused = true }
        }
    }

    private func shown(_ preview: SkillPreview) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(preview.name ?? "").font(CicadaTheme.font(size: 14, weight: .medium))
                if let repo = preview.repo {
                    let line = Copy.Skills.fromRepo(repo.repo ?? "", String((repo.commit ?? "").prefix(7)))
                    if let url = (repo.commitUrl ?? repo.url).flatMap(URL.init(string:)) {
                        Link(line, destination: url).font(CicadaTheme.metaFont)
                    } else {
                        Text(line).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                    if let licence = repo.licence { Tag(text: licence) }
                }
            }
            if let description = preview.description, !description.isEmpty {
                Text(description).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ScrollView {
                Text(preview.skillMd ?? "")
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(CicadaTheme.spacingSM)
            }
            .frame(height: CicadaTheme.scaled(180))
            .settingsCardSurface()
            if preview.skillMdCut == true {
                Text(Copy.Skills.cutNote).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            let files = preview.files ?? []
            Text("\(Copy.Skills.files): " + files.map(\.path).joined(separator: ", "))
                .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            if !(preview.scripts ?? []).isEmpty {
                Label(Copy.Skills.scriptsWarning, systemImage: "exclamationmark.triangle")
                    .font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.warning)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: CicadaTheme.spacingMD) {
                Text(Copy.Skills.giveTo).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                ForEach(agents) { agent in
                    Toggle(agent.label, isOn: Binding(get: { chosen.contains(agent.id) },
                                                      set: { on in
                                                          if on { chosen.insert(agent.id) } else { chosen.remove(agent.id) }
                                                      }))
                        .toggleStyle(.checkbox)
                        .font(CicadaTheme.metaFont)
                }
            }
        }
    }

    private func look(choose: String?) {
        let text = source.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !looking else { return }
        looking = true
        problem = nil
        Task { @MainActor in
            defer { looking = false }
            do {
                let shown = try await model.preview(text, choose: choose)
                preview = shown
                if let suggested = shown.agents, !suggested.isEmpty, input.agents.isEmpty {
                    chosen = Set(suggested).intersection(agents.map(\.id))
                    if chosen.isEmpty { chosen = Set(agents.prefix(1).map(\.id)) }
                }
            } catch {
                preview = nil
                problem = SkillsError.words(error)
            }
        }
    }

    private func install(_ planId: String) {
        installing = true
        Task { @MainActor in
            let ok = await model.installPlan(planId, agents: agents.map(\.id).filter(chosen.contains),
                                             requestId: input.requestId)
            installing = false
            if ok { close() } else { problem = model.message }
        }
    }
}

/// Publish an agent's draft: pick the agents that get it.
struct PublishDraftSheet: View {
    let draft: SkillDraft
    let agents: [SkillAgentInfo]
    let done: ([String]?) -> Void
    @State private var chosen: Set<String> = []

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(draft.name).font(CicadaTheme.headingFont)
            Text(draft.description).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: CicadaTheme.spacingMD) {
                Text(Copy.Skills.giveTo).font(CicadaTheme.metaFont).foregroundStyle(CicadaTheme.textTertiary)
                ForEach(agents) { agent in
                    Toggle(agent.label, isOn: Binding(get: { chosen.contains(agent.id) },
                                                      set: { on in
                                                          if on { chosen.insert(agent.id) } else { chosen.remove(agent.id) }
                                                      }))
                        .toggleStyle(.checkbox)
                        .font(CicadaTheme.metaFont)
                }
            }
            HStack {
                Spacer()
                TextButton(title: Copy.Skills.cancel) { done(nil) }.keyboardShortcut(.cancelAction)
                PrimaryActionButton(title: Copy.Skills.publish) { done(agents.map(\.id).filter(chosen.contains)) }
                    .disabled(chosen.isEmpty)
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(480))
        .onAppear { chosen = Set(agents.prefix(1).map(\.id)) }
    }
}

/// A draft's whole SKILL.md, to read before publishing.
struct SkillTextSheet: View {
    let title: String
    let text: String
    let close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(title).font(CicadaTheme.headingFont)
            ScrollView {
                Text(text).font(CicadaTheme.metaFont).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(CicadaTheme.spacingSM)
            }
            .frame(height: CicadaTheme.scaled(360))
            .settingsCardSurface()
            HStack {
                Spacer()
                TextButton(title: Copy.Skills.close, action: close).keyboardShortcut(.cancelAction)
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(620))
    }
}
