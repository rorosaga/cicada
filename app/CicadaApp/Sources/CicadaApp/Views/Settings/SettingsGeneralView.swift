import SwiftUI

/// Settings → General (G130 R8, re-laid for G139): Appearance (now with
/// System, R-O4), Text size (a direct binding onto `CicadaTheme.uiScale`, so
/// the slider and ⌘+/⌘−/⌘0 stay in lockstep — the setter clamps and is
/// idempotent) and Run setup again (G117: clears the active bank's
/// `OnboardingState` first, then asks the main window for the sheet).
///
/// Appearance writes the same `cicada.colorScheme` key the sidebar's sun/moon
/// toggle already writes, so the two never disagree; `"system"` is the one new
/// value, and `ThemeStore` resolves it against the Mac's own appearance.
struct SettingsGeneralView: View {
    @AppStorage(ThemeStore.defaultsKey) private var appearanceRaw: String = AppearancePreference.dark.rawValue
    // G117 — "Run setup again" needs the active bank (to clear the right
    // per-bank `OnboardingState` flag) and the cross-scene hand-off
    // (Settings is its own window, same reasoning as every other
    // `AppRouter` use — see that type's own doc comment).
    @Environment(AppRouter.self) private var router
    @Environment(Store.self) private var store
    @Environment(SetupRunner.self) private var runner

    private var appearance: Binding<AppearancePreference> {
        Binding(get: { AppearancePreference.stored(appearanceRaw) }, set: { appearanceRaw = $0.rawValue })
    }

    /// A direct `Binding` onto `CicadaTheme.uiScale` — not a locally-drafted
    /// `@State` mirror — so dragging this slider AND choosing ⌘+/⌘−/⌘0 from
    /// the View menu while Settings is open stay in lockstep: reading
    /// `CicadaTheme.uiScale` in `get` subscribes this view's body to the same
    /// `@Observable` store every other token reads (R2's mechanism). The
    /// setter already clamps/steps (R1) and is idempotent (R4).
    private var scale: Binding<Double> {
        Binding(get: { CicadaTheme.uiScale }, set: { CicadaTheme.uiScale = $0 })
    }

    var body: some View {
        SettingsPage(section: .general) {
            SettingsGroupCard {
                SettingsRow(.appearance, title: Copy.appearance) {
                    PillPicker(title: Copy.appearance, selection: appearance,
                               options: AppearancePreference.allCases.map { PillOption(value: $0, label: $0.label) })
                }
                SettingsDivider()
                SettingsRow(.textSize, title: Copy.textSize, detail: Copy.textSizeDetail) {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Slider(value: scale, in: ThemeStore.scaleRange, step: ThemeStore.scaleStep)
                            .frame(width: CicadaTheme.scaled(160))
                        Text("\(Int((CicadaTheme.uiScale * 100).rounded()))%")
                            .font(CicadaTheme.monoFont)
                            .foregroundStyle(CicadaTheme.textSecondary)
                            .frame(width: CicadaTheme.scaled(44), alignment: .trailing)
                        Button(Copy.actualSize) { CicadaTheme.resetZoom() }
                            .buttonStyle(.cicadaPlain)
                            .font(CicadaTheme.captionFont)
                            .foregroundStyle(CicadaTheme.accent)
                            .disabled(CicadaTheme.uiScale == 1.0)
                    }
                }
                SettingsDivider()
                SettingsRow(.runSetup, title: Copy.setup, detail: Copy.runSetupDetail) {
                    HStack(spacing: CicadaTheme.spacingSM) {
                        Button(Copy.runSetupAgain) {
                            OnboardingState.reset(bank: store.bank)
                            router.requestFirstRun()
                        }
                        // R-IB17 — the checklist is re-openable: records an
                        // (empty) Getting started card for the active bank and
                        // lands on Home, where it lists what was found. Beside
                        // Run setup again, in the same row, so G139's search
                        // index lands on both.
                        Button(Copy.gsShowChecklist) {
                            GettingStartedState.record(bank: store.bank, enabled: [])
                            // A card already seen done this session would
                            // otherwise reopen as "You're set up." (finding 4).
                            runner.sawDoneThisSession = false
                            runner.checklistChanged()
                            router.pendingTab = .home
                            router.activateMainWindow()
                        }
                    }
                }
            }
        }
    }
}
