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
    /// G139 (R-O15) — the section and the row to land on; D6 — or the sidebar page a retired section became (Settings
    /// closes on the way, `AppRouter.open(_:)`).
    let home: SettingsHome
    let accessibilityText: String
    let label: Label
    /// G137 R-M18: an empty state's one action is the page's one prominent action — same door, drawn through
    /// `primaryActionStyle()` (its label through `primaryActionInk()`) instead of as link text. Off by default.
    var prominent: Bool = false
    /// Optional so a link rendered outside the main window's tree (a preview) draws without trapping.
    @Environment(AppRouter.self) private var router: AppRouter?

    init(section: SettingsSection, row: SettingsRowID? = nil, accessibilityText: String,
         prominent: Bool = false, @ViewBuilder label: () -> Label) {
        self.init(home: .settings(section, row), accessibilityText: accessibilityText, prominent: prominent,
                  label: label)
    }

    init(home: SettingsHome, accessibilityText: String, prominent: Bool = false, @ViewBuilder label: () -> Label) {
        self.home = home
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
        .accessibilityLabel("\(accessibilityText), opens \(destination)")
    }

    private var destination: String {
        switch home {
        case let .settings(section, _): "\(Copy.settings) — \(section.title)"
        case let .page(tab): tab.title
        case .readingInBrowser: Copy.Reading.inBrowserTitle
        }
    }

    private func open() { router?.open(home) }
}

extension SettingsSectionLink where Label == Text {
    /// The text link every earlier call site uses: link ink (DR-5 use 5, `accentText`), or —
    /// `prominent` — the page's one prominent action (the body inks it).
    init(section: SettingsSection, row: SettingsRowID? = nil, label: String, prominent: Bool = false) {
        self.init(home: .settings(section, row), label: label, prominent: prominent)
    }

    init(home: SettingsHome, label: String, prominent: Bool = false) {
        self.init(home: home, accessibilityText: label, prominent: prominent) {
            prominent ? Text(label) : Text(label).foregroundStyle(CicadaTheme.accentText)
        }
    }
}
