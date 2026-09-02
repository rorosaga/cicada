import SwiftUI

/// The native Settings window — ⌘, and the sidebar's footer gear (G68 §1).
///
/// Hosts the two setup pages that used to be sidebar rows. They are setup, not
/// workspace: you visit them once and then never again, which is exactly what
/// a Settings window is for.
struct SettingsScene: View {
    var body: some View {
        TabView {
            ConnectView()
                .tabItem { Label(Copy.agents, systemImage: "cable.connector") }
                .accessibilityLabel(Copy.agents)

            ConnectionsView()
                .tabItem { Label(Copy.plansAndKeys, systemImage: "creditcard") }
                .accessibilityLabel(Copy.plansAndKeys)

            SettingsSleepView()
                .tabItem { Label(Copy.schedule, systemImage: "moon.zzz") }
                .accessibilityLabel(Copy.schedule)
        }
        .frame(width: 820, height: 620)
        .background(CicadaTheme.background)
    }
}
