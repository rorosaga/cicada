import SwiftUI

/// A pointer to another Settings section. Inside the panel it navigates in
/// place; outside it (an onboarding embed) it is `SettingsSectionLink`, the one
/// door into the panel (R-DS22). Link ink is `accentText` (DR-5 use 5).
struct SettingsInlineLink: View {
    let section: SettingsSection
    var row: SettingsRowID? = nil
    let label: String
    @Environment(SettingsFocus.self) private var focus: SettingsFocus?

    var body: some View {
        if let focus {
            Button { focus.go(section, row: row) } label: { Text("\(label) ›") }
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.accentText)
        } else {
            SettingsSectionLink(section: section, row: row, label: label)
        }
    }
}
