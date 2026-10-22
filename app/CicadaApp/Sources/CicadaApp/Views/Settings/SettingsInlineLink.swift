import AppKit
import SwiftUI

/// A pointer to another Settings section. Inside the panel it navigates in
/// place; outside it (an onboarding embed) it is `SettingsSectionLink`, the one
/// door into the panel (R-DS22). Link ink is `accentText` (DR-5 use 5).
struct SettingsInlineLink: View {
    let home: SettingsHome
    let label: String
    @Environment(SettingsFocus.self) private var focus: SettingsFocus?
    @Environment(AppRouter.self) private var router: AppRouter?

    init(section: SettingsSection, row: SettingsRowID? = nil, label: String) {
        self.home = .settings(section, row)
        self.label = label
    }

    /// D6 — a link to where a retired page went: a row in the panel, or the sidebar page (Settings closes).
    init(home: SettingsHome, label: String) {
        self.home = home
        self.label = label
    }

    var body: some View {
        switch home {
        case let .settings(section, row):
            if let focus {
                Button { focus.go(section, row: row) } label: { Text("\(label) ›") }
                    .buttonStyle(.cicadaPlain)
                    .foregroundStyle(CicadaTheme.accentText)
            } else {
                SettingsSectionLink(section: section, row: row, label: label)
            }
        case .page, .readingInBrowser:
            Button { router?.open(home) } label: { Text("\(label) ›") }
                .buttonStyle(.cicadaPlain)
                .foregroundStyle(CicadaTheme.accentText)
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
