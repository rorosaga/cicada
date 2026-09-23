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
/// **Gated.** The package floor is macOS 14, so every glass API sits behind
/// `#available(macOS 26, *)` with a material fallback. On 26 the system
/// handles Reduce Transparency, Increase Contrast and Reduce Motion for glass
/// itself (WWDC25-219); the fallback branch is ours — opaque under Reduce
/// Transparency, a stronger border under Increase Contrast.
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
}

private struct LiquidGlassModifier<S: Shape>: ViewModifier {
    let level: GlassLevel
    let shape: S
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    func body(content: Content) -> some View {
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
            content
                .background(fallbackFill, in: shape)
                .background(level == .overImagery ? Color.black.opacity(LiquidGlass.overImageryDim) : Color.clear,
                            in: shape)
                .overlay(shape.stroke(LiquidGlass.strongBorder(contrast: contrast)
                                      ? CicadaTheme.textTertiary : CicadaTheme.border, lineWidth: 1))
        }
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
        if #available(macOS 26, *) {
            GlassEffectContainer(spacing: spacing) { content() }
        } else {
            content()
        }
    }
}

/// The page's one prominent action (plan R-M18): `.glassProminent` on 26,
/// `.borderedProminent` before, accent-tinted, label in `onAccent`.
struct PrimaryActionButton: View {
    let title: String
    var systemImage: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Group {
                if let systemImage { Label(title, systemImage: systemImage) } else { Text(title) }
            }
            .foregroundStyle(CicadaTheme.onAccent)
        }
        .primaryActionStyle()
    }
}

/// Paints nothing on macOS 26, so the system's floating glass sidebar shows
/// (WWDC25-323: extra backgrounds interfere with it); the opaque theme
/// background before, exactly as the sidebar always looked there.
private struct SidebarChromeBackground: ViewModifier {
    func body(content: Content) -> some View {
        if #available(macOS 26, *) {
            content
        } else {
            content.background(CicadaTheme.background)
        }
    }
}

extension View {
    /// See `GlassLevel`. Chrome only; content cards use `glassCard()`.
    func liquidGlass<S: Shape>(_ level: GlassLevel = .control, in shape: S) -> some View {
        modifier(LiquidGlassModifier(level: level, shape: shape))
    }

    /// The prominent-action button style — for a `Button` or a `SettingsLink`
    /// (`SettingsSectionLink(prominent:)`). One per page. The caller's label
    /// uses `CicadaTheme.onAccent`.
    @ViewBuilder
    func primaryActionStyle() -> some View {
        if #available(macOS 26, *) {
            buttonStyle(.glassProminent).tint(CicadaTheme.accent)
        } else {
            buttonStyle(.borderedProminent).tint(CicadaTheme.accent)
        }
    }

    /// The sidebar column's background — see `SidebarChromeBackground`.
    func sidebarChromeBackground() -> some View { modifier(SidebarChromeBackground()) }
}
