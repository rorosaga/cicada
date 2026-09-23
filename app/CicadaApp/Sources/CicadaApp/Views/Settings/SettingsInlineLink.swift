import SwiftUI

/// A pointer to another Settings section. Inside the Settings window it
/// navigates in place (and never through `UserDefaults` — that is the
/// cross-window seed, design §2.4); outside it (an onboarding embed) it is the
/// one cross-window entry point, `SettingsSectionLink`.
struct SettingsInlineLink: View {
    let section: SettingsSection
    var row: SettingsRowID? = nil
    let label: String
    @Environment(SettingsFocus.self) private var focus: SettingsFocus?

    var body: some View {
        if let focus {
            Button { focus.go(section, row: row) } label: { Text("\(label) ›") }
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.accent)
        } else {
            SettingsSectionLink(section: section, label: label)
        }
    }
}
