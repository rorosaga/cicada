import SwiftUI

/// F-09's first-time "Make it yours" (owner, round-4 decision 8; R-HO15) — Appearance where a person who has just finished setup will see them, once. The Welcome's Start arms it (`SetupRunner`
/// calls `SetupEffects.armAppearanceTip` beside the plan's Getting started record; the demo plan has none, so it never
/// does) and phase B's onboarding calls `arm()` when its last page closes. × dismisses it for good; both
/// settings live on in Settings → General, which its foot links to. Per viewer, in defaults.
///
/// Owner 2026-10-14 (Home review #4, the minimum): it never sits above Needs you (`HomeArrangement`), it lasts one
/// session — the first launch that shows it marks it seen, and a later launch never shows it again. Its Scene row
/// retired with the painted art (owner 2026-10-16). The side placement beside the column's headline retired with it: that spot sat above everything.
enum AppearanceTipPolicy {
    static let armedKey = "cicada.home.appearanceTipArmed"
    static let dismissedKey = "cicada.home.appearanceTipDismissed"
    /// Set the first time the tip is on screen; with it set, only the session that set it still shows the tip.
    static let seenKey = "cicada.home.appearanceTipSeen"

    static func visible(armed: Bool, dismissed: Bool, seenBefore: Bool = false, shownThisSession: Bool = false) -> Bool {
        armed && !dismissed && (!seenBefore || shownThisSession)
    }

    static func arm(_ defaults: UserDefaults = .standard) { defaults.set(true, forKey: armedKey) }

    /// The tip's own `onAppear`: this session may keep showing it; a later one will not.
    @MainActor static func noteShown(_ defaults: UserDefaults = .standard) {
        shownThisSession = true
        defaults.set(true, forKey: seenKey)
    }

    @MainActor static var shownThisSession = false

    /// The rise plays on the first landing of a session only: Home is rebuilt on every tab switch (R-IB3).
    @MainActor static var hasRisenThisSession = false
}

/// F-09's card padding (R-HO15). It is a row of Home's column now, never beside it. The same 12 pt as every card on
/// Home (`spacingMD`: the tour offer, the empty block, Getting started since the looks pass).
enum AppearanceTipLayout {
    static let padding: CGFloat = 12
}

/// The card itself (DR-9's `glassCard` material, DR-40: one IconButton, TextButtons and a link — no primary on Home).
/// It writes the same keys Settings → General does, so a pick here takes effect at once.
struct AppearanceTip: View {
    @AppStorage(ThemeStore.defaultsKey) private var appearanceRaw: String = AppearancePreference.defaultChoice.rawValue
    @AppStorage(AppearanceTipPolicy.dismissedKey) private var dismissed = false
    @Environment(AppRouter.self) private var router
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var risen = AppearanceTipPolicy.hasRisenThisSession

    private var appearance: Binding<AppearancePreference> {
        Binding(get: { AppearancePreference.stored(appearanceRaw) }, set: { appearanceRaw = $0.rawValue })
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Text(Copy.tipTitle)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 0)
                IconButton(systemName: "xmark", help: Copy.tipDismiss) { dismissed = true }
            }
            SectionLabel(Copy.appearance)
            PillPicker(title: Copy.appearance, selection: appearance,
                       options: AppearancePreference.allCases.map { PillOption(value: $0, label: $0.label) },
                       compact: true)
            HStack(spacing: CicadaTheme.spacingXS) {
                Text(Copy.tipFindIt)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                InlineLink(title: Copy.settingsGeneral) { router.openSettings(.general, row: .appearance) }
            }
        }
        .padding(CicadaTheme.scaled(AppearanceTipLayout.padding))
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
        .opacity(risen ? 1 : 0)
        .offset(y: risen || reduceMotion ? 0 : CicadaTheme.scaled(6))   // DR-66 — the moving value is gated
        .accessibilityElement(children: .contain)
        .onAppear {
            AppearanceTipPolicy.noteShown()
            guard !risen else { return }
            AppearanceTipPolicy.hasRisenThisSession = true
            withAnimation(CicadaMotion.tipRise(reduceMotion: reduceMotion)) { risen = true }
        }
    }
}
