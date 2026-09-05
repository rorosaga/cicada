import SwiftUI

/// Settings → General (G130 R8): the Settings scene's first tab, holding the
/// two "how the whole app looks" controls that used to have no settings home
/// at all — Appearance (the same `cicada.colorScheme` key the sidebar's
/// sun/moon toggle already writes, so the two never disagree) and Text size
/// (a slider over `CicadaTheme.uiScale`, the same value ⌘+/⌘−/⌘0 change).
/// Track C's sidebar redesign is expected to turn this same tab into the
/// General section of its own settings sidebar rather than replace it, so
/// this stays its own file/tab now instead of folding into an existing one.
struct SettingsGeneralView: View {
    @AppStorage("cicada.colorScheme") private var colorSchemeRaw: String = AppColorScheme.dark.rawValue

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(title: Copy.general, subtitle: Copy.generalSubtitle) {}

            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    appearanceCard
                    textSizeCard
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXL)
            }
        }
    }

    /// A direct `Binding` onto `CicadaTheme.uiScale` — not a locally-drafted
    /// `@State` mirror — so dragging this slider AND choosing ⌘+/⌘−/⌘0 from
    /// the View menu while Settings is open stay in lockstep: reading
    /// `CicadaTheme.uiScale` in `get` subscribes this view's body to the same
    /// `@Observable` store every other token reads (R2's mechanism), so a
    /// menu zoom while this tab is open moves the thumb without this view
    /// doing anything special. The setter already clamps/steps (R1) and is
    /// idempotent (R4), so a slider drag that lands off-step is corrected on
    /// write, not here.
    private var scaleBinding: Binding<Double> {
        Binding(get: { CicadaTheme.uiScale }, set: { CicadaTheme.uiScale = $0 })
    }

    private var appearanceCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("APPEARANCE")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            Picker("", selection: $colorSchemeRaw) {
                Text("Dark").tag(AppColorScheme.dark.rawValue)
                Text("Light").tag(AppColorScheme.light.rawValue)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(maxWidth: 220)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private var textSizeCard: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            Text("TEXT SIZE")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)

            HStack(spacing: CicadaTheme.spacingMD) {
                Slider(value: scaleBinding, in: ThemeStore.scaleRange, step: ThemeStore.scaleStep)
                Text("\(Int(CicadaTheme.uiScale * 100))%")
                    .font(CicadaTheme.monoFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: 48, alignment: .trailing)
            }

            Button("Actual size") { CicadaTheme.resetZoom() }
                .buttonStyle(.cicadaPlain)
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.accent)
                .disabled(CicadaTheme.uiScale == 1.0)

            Text("⌘+ and ⌘− do the same from any page.")
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textTertiary)
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }
}
