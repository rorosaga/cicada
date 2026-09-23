import SwiftUI

/// Liquid Glass, in exactly one file (G137, spec R-M5; plan R-M17 … R-M19).
///
/// **Chrome only.** HIG Materials: "Don't use Liquid Glass in the content
/// layer" — glass is for the sidebar, the toolbar, floating controls and ONE
/// prominent action per page. Content cards stay a standard material
/// (`GlassCard`, despite its name). Never glass on glass: what sits on a glass
/// surface uses fills and vibrancy (WWDC25-219). Never over the graph canvas
/// without the G109 frame-time check.
///
/// **Gated twice.** The package floor is macOS 14, so every glass API sits
/// behind `#available(macOS 26, *)` with a material fallback. On 26 the system
/// handles Reduce Transparency, Increase Contrast and Reduce Motion for glass
/// itself (WWDC25-219); the fallback branch is ours — opaque under Reduce
/// Transparency, a stronger border under Increase Contrast.
///
/// `#available` is only a RUNTIME check: the glass symbols must still exist in
/// the SDK at compile time, and they exist only in the macOS 26 SDK (M1 final
/// review, measured: `GlassEffectContainer` / `.glassEffect` fail to resolve
/// against MacOSX15.4 and MacOSX14.4). Xcode 26 does not install on macOS 14,
/// so without a compile-time guard the README's "macOS 14+, command line
/// tools" stops building. Each 26 branch therefore also sits inside
/// `#if canImport(SwiftUI, _version: 7.0)` — SwiftUI's module version is 7.x
/// in the 26 SDK, 6.x in 15 and 5.x in 14, so this tests the SDK itself.
/// `#if compiler(>=6.2)` was rejected: a 6.2 toolchain pointed at an older
/// SDK (`-sdk`) passes it and still fails. Each fallback is one private
/// function so the two `#if` arms never duplicate it.
///
/// `LiquidGlassLintTests` fails the build on a glass API anywhere else.
enum GlassLevel: CaseIterable {
    /// A floating control surface (`Glass.regular`).
    case control
    /// A clickable one — reacts to the pointer (`.regular.interactive()`).
    case interactive
    /// The one emphasised surface, accent-tinted (tint only this — WWDC25-219).
    case prominent
    /// Clear glass over art, with Apple's 35 % dim beneath it. Never mixed
    /// with `.control` in one group.
    case overImagery
}

/// The decisions the fallback branch makes, as pure functions (tested).
enum LiquidGlass {
    enum Fallback: Equatable { case material, opaque }

    static func fallback(reduceTransparency: Bool) -> Fallback { reduceTransparency ? .opaque : .material }
    static func strongBorder(contrast: ColorSchemeContrast) -> Bool { contrast == .increased }
    /// HIG Materials: over bright content, "consider adding a dark dimming
    /// layer of 35% opacity" beneath clear glass.
    static let overImageryDim: Double = 0.35
    /// `onAccent` only while the accent plate is drawn — a key window. See
    /// `PrimaryActionInk`.
    static func primaryInkIsOnAccent(_ state: ControlActiveState) -> Bool { state == .key }

    /// Track I T4 (R-IA16): whether the meadow pill draws system glass (macOS 26,
    /// transparency allowed) or our opaque capsule.
    static func meadowPillUsesGlass(reduceTransparency: Bool) -> Bool {
        #if canImport(SwiftUI, _version: 7.0)
        if #available(macOS 26, *) { return !reduceTransparency }
        return false
        #else
        return false
        #endif
    }

    /// On our capsule we draw the meadow plate, so `onMeadow` always reads; on
    /// glass the plate goes when the window is not key — the rule
    /// `PrimaryActionInk` measured for the accent plate (1.4:1 otherwise).
    static func meadowInkIsOnMeadow(_ state: ControlActiveState, usesGlass: Bool) -> Bool {
        !usesGlass || state == .key
    }
}

private struct LiquidGlassModifier<S: Shape>: ViewModifier {
    let level: GlassLevel
    let shape: S
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    @ViewBuilder
    func body(content: Content) -> some View {
        #if canImport(SwiftUI, _version: 7.0)
        if #available(macOS 26, *) {
            switch level {
            case .control: content.glassEffect(.regular, in: shape)
            case .interactive: content.glassEffect(.regular.interactive(), in: shape)
            case .prominent: content.glassEffect(.regular.tint(CicadaTheme.accent), in: shape)
            case .overImagery:
                content.glassEffect(.clear, in: shape)
                    .background(Color.black.opacity(LiquidGlass.overImageryDim), in: shape)
            }
        } else {
            fallback(content)
        }
        #else
        fallback(content)
        #endif
    }

    private func fallback(_ content: Content) -> some View {
        content
            .background(fallbackFill, in: shape)
            .background(level == .overImagery ? Color.black.opacity(LiquidGlass.overImageryDim) : Color.clear,
                        in: shape)
            .overlay(shape.stroke(LiquidGlass.strongBorder(contrast: contrast)
                                  ? CicadaTheme.textTertiary : CicadaTheme.border, lineWidth: 1))
    }

    private var fallbackFill: AnyShapeStyle {
        switch LiquidGlass.fallback(reduceTransparency: reduceTransparency) {
        case .opaque: AnyShapeStyle(CicadaTheme.surfaceElevated)
        case .material: AnyShapeStyle(Material.regularMaterial)
        }
    }
}

/// Neighbouring glass must share one container: glass cannot sample glass,
/// so siblings in different containers render inconsistently (WWDC25-323),
/// and one container is also the performance path. Plain content before 26.
struct LiquidGlassGroup<Content: View>: View {
    var spacing: CGFloat? = nil
    @ViewBuilder var content: () -> Content

    var body: some View {
        #if canImport(SwiftUI, _version: 7.0)
        if #available(macOS 26, *) {
            GlassEffectContainer(spacing: spacing) { content() }
        } else {
            content()
        }
        #else
        content()
        #endif
    }
}

/// The page's one prominent action (plan R-M18): `.glassProminent` on 26,
/// `.borderedProminent` before, accent-tinted, label through
/// `primaryActionInk()`.
struct PrimaryActionButton: View {
    let title: String
    var systemImage: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Group {
                if let systemImage { Label(title, systemImage: systemImage) } else { Text(title) }
            }
            .primaryActionInk()
        }
        .primaryActionStyle()
    }
}

/// The owner's "muted green pill" (design §7, D-4): `.glassProminent` tinted
/// `meadow` on macOS 26, an opaque meadow capsule before — and on 26 under Reduce
/// Transparency. Here, not in `MeadowPill.swift`, because `.glassProminent` lives
/// in this file only (`LiquidGlassLintTests`).
private struct MeadowPillStyleModifier: ViewModifier {
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    @ViewBuilder
    func body(content: Content) -> some View {
        #if canImport(SwiftUI, _version: 7.0)
        if #available(macOS 26, *), LiquidGlass.meadowPillUsesGlass(reduceTransparency: reduceTransparency) {
            content.buttonStyle(.glassProminent).tint(CicadaTheme.meadow)
        } else {
            content.buttonStyle(MeadowCapsuleButtonStyle())
        }
        #else
        content.buttonStyle(MeadowCapsuleButtonStyle())
        #endif
    }
}

/// The opaque capsule: meadow fill, a 0.97 press (`CicadaPlainButtonStyle`'s dip).
struct MeadowCapsuleButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, CicadaTheme.spacingLG)
            .padding(.vertical, CicadaTheme.spacingSM)
            .background(Capsule().fill(CicadaTheme.meadow.opacity(isEnabled ? 1 : 0.45)))
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.97 : 1)
            .animation(CicadaMotion.press(reduceMotion: reduceMotion), value: configuration.isPressed)
    }
}

/// Paints nothing on macOS 26, so the system's floating glass sidebar shows
/// (WWDC25-323: extra backgrounds interfere with it); the opaque theme
/// background before, exactly as the sidebar always looked there.
private struct SidebarChromeBackground: ViewModifier {
    @ViewBuilder
    func body(content: Content) -> some View {
        #if canImport(SwiftUI, _version: 7.0)
        if #available(macOS 26, *) {
            content
        } else {
            content.background(CicadaTheme.background)
        }
        #else
        content.background(CicadaTheme.background)
        #endif
    }
}

/// The prominent action's label ink — ONE writer, so the two callers
/// (`PrimaryActionButton`, `SettingsSectionLink(prominent:)`) cannot drift.
///
/// `onAccent` is only readable on the accent plate, and the plate is only
/// there while the window is key. M1 final review, measured offscreen on
/// macOS 26.6: in a window that is not key, `.borderedProminent` swaps the
/// accent plate for a neutral one (#2A3035 in dark) but a forced label ink
/// still applies, so `onAccent` (#0D1216) sat on it at about 1.4:1 — every
/// time the person switched apps, or had Settings in front, which is exactly
/// what this link opens. Forcing `controlActiveState = .key` brought the
/// accent plate back, which pins the cause on the window's active state.
/// Whether `.glassProminent` on 26 does the same is unverified (glass does
/// not render in `cacheDisplay`); the rule is applied there too and the
/// live check covers it.
private struct PrimaryActionInk: ViewModifier {
    @Environment(\.controlActiveState) private var activeState

    func body(content: Content) -> some View {
        content.foregroundStyle(LiquidGlass.primaryInkIsOnAccent(activeState)
                                ? CicadaTheme.onAccent : CicadaTheme.textPrimary)
    }
}

extension View {
    /// See `GlassLevel`. Chrome only; content cards use `glassCard()`.
    func liquidGlass<S: Shape>(_ level: GlassLevel = .control, in shape: S) -> some View {
        modifier(LiquidGlassModifier(level: level, shape: shape))
    }

    /// The prominent-action button style — for a `Button` or a `SettingsLink`
    /// (`SettingsSectionLink(prominent:)`). One per page. The caller's label
    /// uses `primaryActionInk()`, never a bare `onAccent`.
    @ViewBuilder
    func primaryActionStyle() -> some View {
        #if canImport(SwiftUI, _version: 7.0)
        if #available(macOS 26, *) {
            buttonStyle(.glassProminent).tint(CicadaTheme.accent)
        } else {
            borderedPrimaryAction()
        }
        #else
        borderedPrimaryAction()
        #endif
    }

    private func borderedPrimaryAction() -> some View {
        buttonStyle(.borderedProminent).tint(CicadaTheme.accent)
    }

    /// The prominent action's label ink — see `PrimaryActionInk`.
    func primaryActionInk() -> some View { modifier(PrimaryActionInk()) }

    /// See `MeadowPillStyleModifier` — the intake's Import / Read now only (R-IA16).
    func meadowPillStyle() -> some View { modifier(MeadowPillStyleModifier()) }

    /// The sidebar column's background — see `SidebarChromeBackground`.
    func sidebarChromeBackground() -> some View { modifier(SidebarChromeBackground()) }
}
