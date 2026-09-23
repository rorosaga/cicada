import SwiftUI

/// Consent before a third-party installer runs (R-O26): what the skill can do
/// and needs, the terms note, the exact command under a disclosure, and a
/// checkbox the Install button waits for. Running shows progress and can be
/// cancelled (the process is terminated); the result is said plainly, with
/// the installer's last lines when it failed.
struct SkillConsentSheet: View {
    let skill: RecommendedSkill
    let agent: String
    let close: () -> Void
    @Environment(SkillsViewModel.self) private var vm
    @State private var understood = false
    @State private var showCommand = false
    @State private var running: Task<Void, Never>?
    @State private var outcome: SkillInstaller.Outcome?

    private var agentName: String { SkillAgent.label(agent) }
    private var command: Result<SkillInstaller.Command, SkillInstaller.PlanError> {
        SkillInstaller.command(for: skill.install[agent] ?? SkillInstallPlan()) { SkillInstaller.resolveProgram($0) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text(Copy.installTitle(skill.title, agentName)).font(CicadaTheme.headingFont)
            Text(Copy.installLead(agentName)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.textSecondary)
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if let tools = skill.needs.allowedTools { bullet("It may use: \(tools).") }
                if let first = skill.needs.firstRun { bullet(first) }
                ForEach(skill.needs.writes, id: \.self) { bullet("Writes \($0).") }
                ForEach(skill.needs.network, id: \.self) { bullet("Talks to \($0).") }
                if let terms = skill.terms { bullet(terms.summary) }
                if let note = skill.cicadaNote { bullet(note) }
            }
            DisclosureGroup(Copy.showExactCommand, isExpanded: $showCommand) {
                switch command {
                case .success(let c):
                    ForEach(c.displayLines, id: \.self) { CommandBox(command: $0) }
                case .failure(.programMissing(let program)):
                    Text(Copy.agentMissing(program)).font(CicadaTheme.captionFont)
                    ForEach(skill.install[agent]?.steps ?? [], id: \.argv) {
                        CommandBox(command: $0.argv.map(SnippetEscape.shell).joined(separator: " "))
                    }
                case .failure:
                    Text(Copy.connectInYourAgent).font(CicadaTheme.captionFont)
                }
            }
            .font(CicadaTheme.captionFont)
            switch outcome {
            case .succeeded?:
                Text(Copy.installedStartNew(agentName)).font(CicadaTheme.bodyFont).foregroundStyle(CicadaTheme.success)
            case .failed(let output)?:
                Text(Copy.installDidntFinish).font(CicadaTheme.bodyFont)
                ScrollView { Text(output).font(CicadaTheme.monoFont).textSelection(.enabled).privacySensitive() }
                    .frame(maxHeight: CicadaTheme.scaled(140))
            case nil:
                Toggle(Copy.understandThirdParty, isOn: $understood).toggleStyle(.checkbox)
            }
            HStack {
                if running != nil { ProgressView().controlSize(.small); Text(Copy.installing).font(CicadaTheme.captionFont) }
                Spacer()
                Button(outcome == nil ? "Cancel" : "Done") { running?.cancel(); close() }
                    .keyboardShortcut(.cancelAction)
                if outcome == nil {
                    Button(Copy.install) { start() }
                        .keyboardShortcut(.defaultAction)
                        .disabled(!understood || running != nil || (try? command.get()) == nil)
                }
            }
        }
        .padding(CicadaTheme.spacingXL)
        .frame(width: CicadaTheme.scaled(560))
    }

    private func bullet(_ text: String) -> some View {
        Label(text, systemImage: "circle.fill").labelStyle(.titleOnly)
            .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func start() {
        guard understood, case .success(let c) = command else { return }
        running = Task { @MainActor in
            let result = await SkillInstaller.run(c)
            outcome = result
            running = nil
            await vm.load()
        }
    }
}
