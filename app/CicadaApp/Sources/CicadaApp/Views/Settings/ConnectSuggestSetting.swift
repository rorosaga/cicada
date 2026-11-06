import SwiftUI

/// G231 — Settings → General's row for the notch's connect suggestion (on by default), and under it each app the
/// person said No to, with Suggest again. Per Mac, like the suggestion's own memory (`ConnectSuggestStore`).
struct ConnectSuggestSettingRow: View {
    /// Optional, so a page rendered without the app's center (a test, a preview) draws no card rather than trapping.
    @Environment(ConnectSuggestCenter.self) private var center: ConnectSuggestCenter?

    var body: some View {
        if let center { row(center) }
    }

    /// Round 1 (ROR-118): one row inside General's switches card, its sentence a tooltip instead of a paragraph.
    private func row(_ center: ConnectSuggestCenter) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            SettingsDivider()
            SettingsRow(.connectSuggest, title: Copy.ConnectSuggest.settingTitle) {
                Toggle(Copy.ConnectSuggest.settingTitle, isOn: Binding(get: { center.enabled },
                                                                       set: { center.enabled = $0 }))
                    .toggleStyle(.switch)
                    .labelsHidden()
                    .help(Copy.ConnectSuggest.settingDetail)
            } below: {
                let declined = center.declined
                if !declined.isEmpty {
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(4)) {
                        Text(Copy.ConnectSuggest.declinedLabel)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.textTertiary)
                        ForEach(declined, id: \.id) { app in
                            HStack(spacing: CicadaTheme.spacingSM) {
                                Text(app.name)
                                    .font(CicadaTheme.metaFont)
                                    .foregroundStyle(CicadaTheme.textSecondary)
                                Spacer()
                                TextButton(title: Copy.ConnectSuggest.suggestAgain,
                                           help: Copy.ConnectSuggest.suggestAgainHelp(app.name)) {
                                    center.undoDecline(app.id)
                                }
                            }
                        }
                    }
                    .padding(.top, CicadaTheme.scaled(2))
                }
            }
        }
        // The old sentence on the whole row, not only on the switch.
        .help(Copy.ConnectSuggest.settingDetail)
    }
}
