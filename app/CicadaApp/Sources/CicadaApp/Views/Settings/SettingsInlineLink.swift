import AppKit
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

/// Settings defaults, pass 2 (owner 2026-10-22): where a value Cicada's setup fixes can be changed — a link to the
/// one docs page that says how, opened in the person's browser on their click. The page never names the variable or
/// the file itself. Same ink and chevron as `SettingsInlineLink`; the address is in `.help`.
struct SettingsHelpLink: View {
    let url: URL
    var label: String = Copy.SettingsHelp.howToChange

    var body: some View {
        Button { NSWorkspace.shared.open(url) } label: { Text("\(label) ›") }
            .buttonStyle(.cicadaPlain)
            .foregroundStyle(CicadaTheme.accentText)
            .help(url.absoluteString)
    }
}
