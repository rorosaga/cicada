import SwiftUI

/// A working page's headline (DR-17's fourth call site: onboarding headlines) and its one line.
struct OnboardingHeadline: View {
    let title: String
    let subline: String

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            Text(title)
                .font(CicadaTheme.displayFont(size: 28))
                .tracking(CicadaTheme.displayTracking(size: 28))
                .foregroundStyle(CicadaTheme.textPrimary)
                .accessibilityAddTraits(.isHeader)
            Text(subline)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// "More sources any time on the Sources page" — a sentence ending in the one door into Settings
/// (`SettingsSectionLink`, R-DS22), so a pointer never re-types a destination (G68 §2.8).
struct OnboardingPointerLine: View {
    let lead: String
    let home: SettingsHome
    let label: String
    @Environment(AppRouter.self) private var router: AppRouter?

    init(lead: String, section: SettingsSection, label: String) {
        self.init(lead: lead, home: .settings(section, nil), label: label)
    }

    /// D6 — Sources and Agents are sidebar pages now; their pointer opens the page.
    init(lead: String, home: SettingsHome, label: String) {
        self.lead = lead
        self.home = home
        self.label = label
    }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text(lead).foregroundStyle(CicadaTheme.textSecondary)
            switch home {
            case let .settings(section, row): SettingsSectionLink(section: section, row: row, label: label)
            case .page, .readingInBrowser:
                Button { router?.open(home) } label: { Text(label).foregroundStyle(CicadaTheme.accentText) }
                    .buttonStyle(.cicadaPlain)
            }
        }
        .font(CicadaTheme.captionFont)
    }
}
