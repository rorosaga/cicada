import SwiftUI

/// One recommended skill (the sub-page, R-O5): why, where it comes from, what
/// it needs in plain words, the terms note, Cicada's own note, and per agent
/// either "Install in …" (the consent sheet) or — for a hosted connector —
/// the command to paste into the agent. ⌘[ and Esc go back (Esc through
/// `SettingsFocus.escapeBack`, which `SkillsView` sets while this is open).
struct SkillDetailView: View {
    let skill: RecommendedSkill
    let back: () -> Void
    @State private var consentAgent: String?
    @Environment(SkillsViewModel.self) private var vm

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SettingsDetailHeader(section: .skills, subpage: .init(title: skill.title, back: back))
                .padding(.horizontal, CicadaTheme.spacingXL)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    header
                    if !skill.why.isEmpty { Text(skill.why).font(CicadaTheme.bodyFont).fixedSize(horizontal: false, vertical: true) }
                    needs
                    if let terms = skill.terms { termsBox(terms) }
                    if let note = skill.cicadaNote {
                        Label(note, systemImage: "sparkles").font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
                    }
                    SettingsGroupCard(header: "Install") {
                        ForEach(skill.agents, id: \.self) { agent in agentRow(agent) }
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.vertical, CicadaTheme.spacingLG)
                .frame(maxWidth: CicadaTheme.scaled(760), alignment: .leading)
            }
        }
        .sheet(item: Binding(get: { consentAgent.map(AgentChoice.init) }, set: { consentAgent = $0?.id })) { choice in
            // Handed on explicitly: the sheet reloads the catalog after an
            // install, and a missing `@Observable` in the environment is a
            // crash, not a no-op.
            SkillConsentSheet(skill: skill, agent: choice.id) { consentAgent = nil }
                .environment(vm)
        }
    }

    private struct AgentChoice: Identifiable { let id: String }

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            LogoImage.platformTile(name: skill.mark ?? "", size: CicadaTheme.scaled(44), systemFallback: skill.symbol)
            VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
                Text(skill.summary).font(CicadaTheme.bodyFont)
                HStack(spacing: CicadaTheme.spacingSM) {
                    Text("\(skill.publisher) · \(skill.licence)").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    if let url = URL(string: skill.sourceUrl) { Link("Source", destination: url).font(CicadaTheme.captionFont) }
                }
            }
        }
    }

    /// Plain words for every need the catalog lists; empty lists draw nothing.
    private var needs: some View {
        let n = skill.needs
        let keys: [String] = n.keys.map { key in key.optional ? key.name + " (optional)" : key.name }
        // Built in two statements: one array literal with a trailing `.filter`
        // is past the type checker's time budget ("unable to type-check this
        // expression in reasonable time", measured).
        let all: [(String, String)] = [
            ("Programs", n.binaries.joined(separator: ", ")),
            ("Keys", keys.joined(separator: ", ")),
            ("Accounts", n.accounts.joined(separator: ", ")),
            ("Talks to", n.network.joined(separator: "; ")),
            ("Writes", n.writes.joined(separator: ", ")),
            ("May use", n.allowedTools ?? ""),
            ("Adds", n.hooks.joined(separator: "; ")),
            ("First time", n.firstRun ?? ""),
            ("Limits", n.limits.joined(separator: " ")),
        ]
        let lines = all.filter { !$0.1.isEmpty }
        return SettingsGroupCard(header: Copy.whatItNeeds) {
            ForEach(lines, id: \.0) { label, value in
                HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                    Text(label).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                        .frame(width: CicadaTheme.scaled(80), alignment: .leading)
                    Text(value).font(CicadaTheme.captionFont).fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, CicadaTheme.spacingMD)
                .padding(.vertical, CicadaTheme.spacingXS)
            }
        }
    }

    private func termsBox(_ terms: SkillTerms) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Label(terms.summary, systemImage: "exclamationmark.triangle").foregroundStyle(CicadaTheme.warning)
            if !terms.safeUses.isEmpty {
                Text("Fine to use with \(terms.safeUses.joined(separator: " and ")).").foregroundStyle(CicadaTheme.textSecondary)
            }
            if let url = URL(string: terms.url) { Link("Read the terms", destination: url) }
        }
        .font(CicadaTheme.captionFont)
        .padding(CicadaTheme.spacingMD)
        .frame(maxWidth: .infinity, alignment: .leading)
        .settingsCardSurface()
    }

    private func agentRow(_ agent: String) -> some View {
        let plan = skill.install[agent] ?? SkillInstallPlan()
        return VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            HStack(spacing: CicadaTheme.spacingSM) {
                LogoImage.platformTile(name: SkillAgent.mark(agent), size: CicadaTheme.scaled(20), systemFallback: "terminal")
                Text(SkillAgent.label(agent)).font(CicadaTheme.bodyFont)
                Text(SkillAgent.stateLabel(skill.state[agent] ?? "not_installed"))
                    .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                Spacer()
                // A plan with no steps has nothing to show consent for.
                if plan.runnable && !plan.steps.isEmpty && skill.state[agent] != "installed" {
                    Button(Copy.installIn(SkillAgent.label(agent))) { consentAgent = agent }
                }
            }
            if !plan.runnable {
                Text(Copy.connectInYourAgent).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                ForEach(plan.steps, id: \.argv) { step in
                    CommandBox(command: step.argv.map(SnippetEscape.shell).joined(separator: " "))
                }
            }
        }
        .padding(.horizontal, CicadaTheme.spacingMD)
        .padding(.vertical, CicadaTheme.spacingSM)
    }
}
