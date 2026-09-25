import SwiftUI

/// Settings → Skills (G138, design §2.2 and A2): Cicada's own two skills,
/// written by the app with a marker (R-O26); at most five recommended skills
/// from the reviewed catalog, each a card that opens its detail (the one
/// sub-page, R-O5); and what is already installed. Never a download count, a
/// star count or a price.
struct SkillsView: View {
    @Environment(SkillsViewModel.self) private var vm
    @Environment(SettingsFocus.self) private var focus: SettingsFocus?
    @State private var openSkill: String?

    var body: some View {
        Group { page }
            // A search hit or deep link that lands on Skills while a detail is
            // open must show the list the row lives on (R-O5: switching
            // sections resets the sub-page by recreating this view; landing on
            // the same section does not).
            .onChange(of: focus?.landedNonce ?? 0) { _, _ in openSkill = nil }
            // R-O5 — while a detail is open, Esc goes back to the list instead
            // of closing the panel (the ×'s `.cancelAction` would win over a
            // view-level exit command; see `SettingsFocus.escapeBack`).
            .onChange(of: openSkill, initial: true) { _, open in
                focus?.escapeBack = open == nil ? nil : { openSkill = nil }
            }
            .onDisappear { focus?.escapeBack = nil }
    }

    @ViewBuilder
    private var page: some View {
        if let id = openSkill, let skill = vm.all.first(where: { $0.id == id }) {
            SkillDetailView(skill: skill) { openSkill = nil }
        } else {
            SettingsPage(section: .skills) {
                SettingsGroupCard(header: Copy.cicadasOwnGroup) {
                    ForEach(Array(CicadaSkillBundle.allCases.enumerated()), id: \.element) { index, bundle in
                        if index > 0 { SettingsDivider() }
                        CicadaSkillRow(bundle: bundle)
                    }
                }
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    HStack(alignment: .firstTextBaseline) {
                        SettingsGroupHeader(Copy.recommendedGroup)
                        Spacer()
                        if let date = vm.response?.reviewedAt, !date.isEmpty {
                            Text(Copy.reviewedOn(date)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                        }
                    }
                    .padding(.horizontal, CicadaTheme.spacingXS)
                    if let problem = vm.problem {
                        Text(problem).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                    }
                    ForEach(vm.shown) { skill in
                        RecommendedSkillCard(skill: skill) { openSkill = skill.id }
                    }
                }
                if !vm.installedHere.isEmpty {
                    SettingsGroupCard(header: Copy.installedGroup) {
                        ForEach(vm.installedHere) { skill in
                            SettingsRow(.skill(skill.id), title: skill.title, detail: skill.summary) {
                                Button("Details") { openSkill = skill.id }
                            }
                        }
                    }
                }
                Text(Copy.skillsFootnote).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        }
    }
}

/// One of Cicada's own skills: a pill per place it can go, each with the one
/// action its state allows (install, update, remove) — never over a copy the
/// person changed.
private struct CicadaSkillRow: View {
    let bundle: CicadaSkillBundle
    @State private var refresh = 0
    @State private var problem: String?
    private let home = FileManager.default.homeDirectoryForCurrentUser
    private let root = BackendProcess.installRoot()

    var body: some View {
        SettingsRow(.skill(bundle.rawValue), title: bundle.title, detail: problem ?? bundle.summary) {
            EmptyView()
        } below: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                ForEach(SkillInstaller.Target.allCases) { target in
                    let state = SkillInstaller.ownState(bundle, target, home: home, installRoot: root)
                    HStack(spacing: CicadaTheme.spacingSM) {
                        LogoImage.platformTile(name: target.mark, size: CicadaTheme.scaled(16), systemFallback: "terminal")
                        Text(target.label).font(CicadaTheme.captionFont)
                        Text(Self.caption(state)).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                        Spacer()
                        action(state, target)
                    }
                }
            }
            .id(refresh)
        }
    }

    @ViewBuilder
    private func action(_ state: SkillInstaller.OwnState, _ target: SkillInstaller.Target) -> some View {
        switch state {
        case .notInstalled, .installedByHand(sameAsCicada: true):
            Button(Copy.install) { perform { try SkillInstaller.install(bundle, target, home: home, installRoot: root) } }
        case .updateAvailable:
            Button(Copy.update) { perform { try SkillInstaller.install(bundle, target, home: home, installRoot: root) } }
        case .current:
            Button(Copy.remove, role: .destructive) { perform { try SkillInstaller.remove(bundle, target, home: home, installRoot: root) } }
        default:
            EmptyView()
        }
    }

    private func perform(_ work: () throws -> Void) {
        do { try work(); problem = nil } catch { problem = Copy.differentCopy }
        refresh &+= 1
    }

    static func caption(_ state: SkillInstaller.OwnState) -> String {
        switch state {
        case .sourceMissing: Copy.sourceMissing
        case .notInstalled: "Not installed"
        case .current: "Installed"
        case .updateAvailable: "Installed · an update is ready"
        case .changedByYou: Copy.changedByYou
        case .installedByHand(let same): same ? Copy.installedByHand : Copy.differentCopy
        }
    }
}

/// A recommended skill as a card that opens its detail — the one thing on this
/// page that opens something, so it lifts on hover (R-M14).
private struct RecommendedSkillCard: View {
    let skill: RecommendedSkill
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            HStack(alignment: .top, spacing: CicadaTheme.spacingMD) {
                LogoImage.platformTile(name: skill.mark ?? "", size: CicadaTheme.scaled(32), systemFallback: skill.symbol)
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    Text(skill.title).font(CicadaTheme.font(size: 13, weight: .semibold)).foregroundStyle(CicadaTheme.textPrimary)
                    Text(skill.summary).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    if let terms = skill.terms {
                        Label(terms.summary, systemImage: "exclamationmark.triangle")
                            .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.warning)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Text(([skill.licence] + skill.agents.map(SkillAgent.label)).joined(separator: " · "))
                        .font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
                }
                Spacer(minLength: CicadaTheme.spacingSM)
                Image(systemName: "chevron.right").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
            .padding(CicadaTheme.spacingMD)
            .frame(maxWidth: .infinity, alignment: .leading)
            .settingsCardSurface()
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .hoverLift()
        .settingsRow(.skill(skill.id))
    }
}
