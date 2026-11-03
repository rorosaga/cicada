import SwiftUI

/// G231 — Settings → General's switch for the notch's connect suggestion (on by default), and under it each app the
/// person said No to, with Suggest again. Per Mac, like the suggestion's own memory (`ConnectSuggestStore`).
struct ConnectSuggestSettingCard: View {
    /// Optional, so a page rendered without the app's center (a test, a preview) draws no card rather than trapping.
    @Environment(ConnectSuggestCenter.self) private var center: ConnectSuggestCenter?

    var body: some View {
        if let center { card(center) }
    }

    private func card(_ center: ConnectSuggestCenter) -> some View {
        SettingsGroupCard {
            SettingsRow(.connectSuggest, title: Copy.ConnectSuggest.settingTitle,
                        detail: Copy.ConnectSuggest.settingDetail) {
                Toggle(Copy.ConnectSuggest.settingTitle, isOn: Binding(get: { center.enabled },
                                                                       set: { center.enabled = $0 }))
                    .toggleStyle(.switch)
                    .labelsHidden()
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
    }
}
