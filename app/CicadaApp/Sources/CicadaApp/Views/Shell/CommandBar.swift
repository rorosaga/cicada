import SwiftUI

/// The titlebar's command bar (DR-23): a 520 × 32 pt bar centred in the 52 pt titlebar.
///
/// It holds, leading to trailing, the memory-bank selector (DR-24: the only one in the app),
/// "Search your memory", and a ⌘K keycap. A click anywhere outside the selector opens the find
/// palette through `AppRouter.requestPalette()` — the same door ⌘K uses, so the two can never
/// open different things.
///
/// Surface: `commandBarFill` (`bgHover` in dark, `bgMenu` in light), `cornerRadius`, the resting
/// ring, and the strong ring on hover. It is the chrome's one opaque surface; the toolbar's
/// glass platter is hidden (R-DS16).
///
/// ROR-118 round 2 — on Home alone (`quiet`) the bar is the memory-bank selector and nothing else: Home's own field is the
/// same palette body in the page, so a second "Search your memory" in the titlebar was two searches competing. ⌘K and the
/// menu item still open the palette over Home; the bar's size and place do not change (the toolbar item is one view in
/// both forms), and the tour's first stop draws the full bar when it points at it.
struct CommandBar: View {
    var quiet = false
    @Environment(AppRouter.self) private var router
    @Environment(BanksViewModel.self) private var banksVM
    @Environment(TourController.self) private var tour
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            if quiet { Spacer(minLength: 0) }
            BankSwitcher(banksVM: banksVM)
            if quiet { Spacer(minLength: 0) }
            if !quiet {
            Button { router.requestPalette() } label: {
                HStack(spacing: CicadaTheme.spacingSM) {
                    Image(systemName: "magnifyingglass")
                        .font(CicadaTheme.icon(.commandBar))
                        .accessibilityHidden(true)
                    Text(Copy.searchYourMemory)
                        .font(CicadaTheme.bodyFont)
                        .lineLimit(1)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    KeyHint("⌘K")
                }
                .foregroundStyle(CicadaTheme.textTertiary)
                .padding(.leading, CicadaTheme.spacingSM)
                .padding(.trailing, CicadaTheme.spacingXS)
                .frame(maxHeight: .infinity)
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .help(Copy.findInMemoryHelp)
            .accessibilityLabel("\(Copy.searchYourMemory), ⌘K")
            }
        }
        // Hover through `.onContinuousHover`, never `.onHover`: on macOS 26 an `.onHover`
        // anywhere above the search Button made AppKit drop the whole principal toolbar item,
        // so the bar — and with it the app's ONLY memory-bank selector — never appeared (DS-1
        // live check, 2026-09-24, bisected: root or inner stack, with or without
        // `.animation(_:value:)`). `CommandBarHoverLintTests` keeps it out of this file.
        .onContinuousHover { phase in
            let inside: Bool
            switch phase { case .active: inside = true; case .ended: inside = false }
            guard inside != hovering else { return }
            withAnimation(CicadaMotion.hover(reduceMotion: reduceMotion)) { hovering = inside }
        }
        .padding(.leading, CicadaTheme.spacingXS)
        .padding(.trailing, CicadaTheme.scaled(6))
        .frame(width: CicadaTheme.scaled(ShellMetrics.commandBarWidth), height: CicadaTheme.scaled(ShellMetrics.commandBarHeight))
        .background {
            CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.commandBarFill)
                .ringed(hovering ? .strong : .resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
                .opacity(quiet ? 0 : 1)
        }
        // G152 — the tour's first stop: the bar lives in the titlebar, out of the scrim's reach, so it draws the
        // focus ring itself (DR-5's first use) while the coach mark sits under it.
        .overlay {
            if tour.spotlights(.commandBar) {
                CicadaTheme.shape(CicadaTheme.cornerRadius)
                    .strokeBorder(CicadaTheme.focusRing, lineWidth: 2)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
        }
    }
}
