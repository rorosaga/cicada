import SwiftUI

/// Track I T4 (design §7, R-IA16) — the one meadow pill: the intake panel's
/// Import and the done card's Read now (part b adds the Welcome's Start).
/// Everywhere else the primary action stays `accent` (`PrimaryActionButton`).
/// It lifts on hover because it starts something.
struct MeadowPill: View {
    let title: String
    var systemImage: String? = nil
    var isBusy = false
    let action: () -> Void

    @Environment(\.controlActiveState) private var activeState
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    private var ink: Color {
        let glass = LiquidGlass.meadowPillUsesGlass(reduceTransparency: reduceTransparency)
        return LiquidGlass.meadowInkIsOnMeadow(activeState, usesGlass: glass) ? CicadaTheme.onMeadow : CicadaTheme.textPrimary
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: CicadaTheme.spacingXS) {
                if isBusy {
                    ProgressView().controlSize(.small)
                } else if let systemImage {
                    Image(systemName: systemImage)
                }
                Text(title).font(CicadaTheme.font(size: 14, weight: .semibold))
            }
            .foregroundStyle(ink)
        }
        .meadowPillStyle()
        .hoverLift(scale: 1.02, lift: 1)
        .disabled(isBusy)
        .accessibilityLabel(title)
    }
}
