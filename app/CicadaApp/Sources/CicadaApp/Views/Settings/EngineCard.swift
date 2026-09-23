import SwiftUI

/// The engine picker in a glass card — onboarding step 2 still embeds this
/// (`FirstRunSheet.swift`). Everything it does is `EngineChooser`, the one
/// component Settings → Engines renders too (G139, R-O8); onboarding can
/// switch to the chooser directly later.
struct EngineCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            SettingsGroupHeader("Engine")
            EngineChooser()
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }
}
