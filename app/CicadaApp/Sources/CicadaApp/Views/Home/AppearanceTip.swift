import SwiftUI

/// F-09's first-time "Make it yours" (owner, round-4 decision 8; R-HO15) — Appearance and Scene where a person who has
/// just finished setup will see them, once. The Welcome's Start arms it (`SetupRunner` calls `SetupEffects.armAppearanceTip`
/// beside the plan's Getting started record; the demo plan has none, so it never does) and phase B's onboarding calls `arm()` when its last page
/// closes. × and Hide both dismiss it for good; both settings live on in Settings → General, which its foot links to.
/// No hours, no city, no sunrise times here — the explanation is Settings' (decision 8). Per viewer, in defaults.
enum AppearanceTipPolicy {
    static let armedKey = "cicada.home.appearanceTipArmed"
    static let dismissedKey = "cicada.home.appearanceTipDismissed"

    static func visible(armed: Bool, dismissed: Bool) -> Bool { armed && !dismissed }

    static func arm(_ defaults: UserDefaults = .standard) { defaults.set(true, forKey: armedKey) }

    /// The rise plays on the first landing of a session only: Home is rebuilt on every tab switch (R-IB3).
    @MainActor static var hasRisenThisSession = false
}

/// F-09's placement (R-HO15): a 264 pt card beside the 760 pt column at the headline's height while the page has room
/// for it and a 24 pt gap each side, otherwise the column's first row (the 1200 × 800 window).
enum AppearanceTipLayout {
    enum Placement: Equatable { case side, inline }

    static let width: CGFloat = 264
    static let gap: CGFloat = 24
    static let edgeInset: CGFloat = 24
    static let padding: CGFloat = 12

    static func placement(pageWidth: CGFloat, scale: CGFloat) -> Placement {
        guard pageWidth > 0, scale > 0 else { return .inline }
        return (pageWidth / scale - HomeLayout.columnWidth) / 2 >= width + gap + edgeInset ? .side : .inline
    }
}

/// The card itself (DR-9's `glassCard` material, DR-40: one IconButton, TextButtons and a link — no primary on Home).
/// It writes the same keys Settings → General does, so a pick here crossfades the band above at once.
struct AppearanceTip: View {
    @AppStorage(ThemeStore.defaultsKey) private var appearanceRaw: String = AppearancePreference.dark.rawValue
    @AppStorage(HeroScenePreference.defaultsKey) private var sceneRaw = HeroScenePreference.automatic.rawValue
    @AppStorage(AppearanceTipPolicy.dismissedKey) private var dismissed = false
    @Environment(AppRouter.self) private var router
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var risen = AppearanceTipPolicy.hasRisenThisSession

    private var appearance: Binding<AppearancePreference> {
        Binding(get: { AppearancePreference.stored(appearanceRaw) }, set: { appearanceRaw = $0.rawValue })
    }

    private var scene: Binding<HeroScenePreference> {
        Binding(get: { HeroScenePreference.stored(sceneRaw) }, set: { sceneRaw = $0.rawValue })
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
            SectionLabel(Copy.scene)
            PillPicker(title: Copy.scene, selection: scene,
                       options: HeroScenePreference.allCases.map { PillOption(value: $0, label: $0.label) },
                       compact: true)
            HStack(spacing: CicadaTheme.spacingXS) {
                TextButton(title: Copy.tipHide, inline: true) { dismissed = true }
                Text(Copy.tipFindIt)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                InlineLink(title: Copy.settingsGeneral) { router.openSettings(.general, row: .heroScene) }
            }
        }
        .padding(CicadaTheme.scaled(AppearanceTipLayout.padding))
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
        .opacity(risen ? 1 : 0)
        .offset(y: risen || reduceMotion ? 0 : CicadaTheme.scaled(6))   // DR-66 — the moving value is gated
        .accessibilityElement(children: .contain)
        .onAppear {
            guard !risen else { return }
            AppearanceTipPolicy.hasRisenThisSession = true
            withAnimation(CicadaMotion.tipRise(reduceMotion: reduceMotion)) { risen = true }
        }
    }
}
