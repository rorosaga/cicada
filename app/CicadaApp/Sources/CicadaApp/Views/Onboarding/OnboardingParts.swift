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

/// "More sources any time in Settings → Integrations" — a sentence ending in the one door into Settings
/// (`SettingsSectionLink`, R-DS22), so a pointer never re-types a destination (G68 §2.8).
struct OnboardingPointerLine: View {
    let lead: String
    let section: SettingsSection
    let label: String

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text(lead).foregroundStyle(CicadaTheme.textSecondary)
            SettingsSectionLink(section: section, label: label)
        }
        .font(CicadaTheme.captionFont)
    }
}
