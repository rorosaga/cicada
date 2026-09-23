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
struct CommandBar: View {
    @Environment(AppRouter.self) private var router
    @Environment(BanksViewModel.self) private var banksVM
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            BankSwitcher(banksVM: banksVM)
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
        .padding(.leading, CicadaTheme.spacingXS)
        .padding(.trailing, CicadaTheme.scaled(6))
        .frame(width: CicadaTheme.scaled(ShellMetrics.commandBarWidth), height: CicadaTheme.scaled(ShellMetrics.commandBarHeight))
        .background(CicadaTheme.shape(CicadaTheme.cornerRadius).fill(CicadaTheme.commandBarFill))
        .ringed(hovering ? .strong : .resting, in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .onHover { hovering = $0 }
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
    }
}
