import SwiftUI

/// Settings → Skills (G138, design §2.2 and A2): Cicada's own two skills; at
/// most five recommended skills from the reviewed catalog, each a card that
/// opens its detail (the one sub-page, R-O5); and what is already installed.
/// Never a download count, a star count or a price. Installing, updating and
/// giving a skill to each agent live on the Skills page (owner 2026-10-15):
/// every row here hands off to it.
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

/// One of Cicada's own skills: what it does, and the door to the Skills page, where it is installed, updated and
/// given to each agent (the backend's `skill_store` writes it; the app writes no skill folder).
private struct CicadaSkillRow: View {
    let bundle: CicadaSkillBundle
    @Environment(AppRouter.self) private var router

    var body: some View {
        SettingsRow(.skill(bundle.rawValue), title: bundle.title, detail: bundle.summary) {
            NeutralButton(title: Copy.openSkills, size: .compact) { router.routeToSkills() }
        }
    }
}

/// Cicada's hand-written skills, by name (the Skills page installs them from the checkout, G112 compiles more). The
/// words match the backend's `skill_inventory._own_suggestion`.
enum CicadaSkillBundle: String, CaseIterable, Identifiable {
    case cicada
    case cicadaLibrarian = "cicada-librarian"
    /// 2026-10-16: when the person asks about someone, their agent reads that one LinkedIn profile in their browser.
    case linkedinPeople = "linkedin-people"

    var id: String { rawValue }
    var title: String {
        switch self {
        case .cicada: "Recall and save"
        case .cicadaLibrarian: "Tidy as you work"
        case .linkedinPeople: "What people do now"
        }
    }
    var summary: String {
        switch self {
        case .cicada: "Tells your agent when to look things up in Cicada and when to save."
        case .cicadaLibrarian: "Lets your agent file what you just did into Cicada, the way Sleep would."
        case .linkedinPeople:
            "When you ask about someone, your agent reads their LinkedIn profile in your browser and updates what Cicada knows."
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
