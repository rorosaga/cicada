import SwiftUI

/// "Open Settings, on this section" — the ONE way any surface sends the reader into Settings
/// (G125 v3 P5, re-seated by DR-33 / R-DS22).
///
/// Settings is a panel in this window now, so the link is a plain `Button` that hands its
/// section and row to `AppRouter.openSettings(_:row:)`. The two `UserDefaults` seeds it used to
/// write before a `SettingsLink` opened the scene — and the nonce and freshness window the row
/// seed needed to cross windows — are gone: nothing crosses a window any more. P5 survives in
/// its real form, one door, which `SleepQueueCardV3Tests` holds. Fired while the panel is
/// open, it re-lands in place.
///
/// The label is generic so a whole row can be the link (L final review, finding 1: a folder or
/// Wispr Flow row on the Feed strip has its settings in Integrations).
struct SettingsSectionLink<Label: View>: View {
    let section: SettingsSection
    /// G139 (R-O15) — land on (scroll to and briefly wash) this row once the panel shows it.
    let row: SettingsRowID?
    let accessibilityText: String
    let label: Label
    /// G137 R-M18: an empty state's one action is the page's one prominent action — same
    /// door, drawn through `primaryActionStyle()` (its label through `primaryActionInk()`)
    /// instead of as link text. Off by default, so every other caller (the Sleep page's
    /// schedule link, a Feed-strip row) renders as a quiet link.
    var prominent: Bool = false
    /// Optional so a link rendered outside the main window's tree (a preview) draws without
    /// trapping; in the app the router is always there.
    @Environment(AppRouter.self) private var router: AppRouter?

    init(section: SettingsSection, row: SettingsRowID? = nil, accessibilityText: String,
         prominent: Bool = false, @ViewBuilder label: () -> Label) {
        self.section = section
        self.row = row
        self.accessibilityText = accessibilityText
        self.prominent = prominent
        self.label = label()
    }

    var body: some View {
        Group {
            if prominent {
                Button(action: open) { label.primaryActionInk() }
                    .primaryActionStyle()
            } else {
                Button(action: open) { label }
                    .buttonStyle(.cicadaPlain)
            }
        }
        .accessibilityLabel("\(accessibilityText), opens \(Copy.settings) — \(section.title)")
    }

    private func open() { router?.openSettings(section, row: row) }
}

extension SettingsSectionLink where Label == Text {
    /// The text link every earlier call site uses: link ink (DR-5 use 5, `accentText`), or —
    /// `prominent` — the page's one prominent action (the body inks it).
    init(section: SettingsSection, row: SettingsRowID? = nil, label: String, prominent: Bool = false) {
        self.init(section: section, row: row, accessibilityText: label, prominent: prominent) {
            prominent ? Text(label) : Text(label).foregroundStyle(CicadaTheme.accentText)
        }
    }
}
