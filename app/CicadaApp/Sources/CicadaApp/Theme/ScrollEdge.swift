import SwiftUI

/// The top edge of a page that scrolls under the titlebar band (owner 2026-10-06). On macOS 26 the system's soft scroll
/// edge eases content out where it meets the band instead of a hard cut; earlier systems keep the plain edge. A system
/// edge treatment of the chrome boundary — not a glass material on content (DR-14), not a shadow (DR-9/10), not a header
/// wash (DR-13). `scrollEdgeEffectStyle` exists only in the macOS 26 SDK, so the call sits inside the same compile-time
/// guard `LiquidGlass.swift` uses.
struct SoftTopScrollEdge: ViewModifier {
    func body(content: Content) -> some View {
        #if canImport(SwiftUI, _version: 7.0)
        if #available(macOS 26, *) {
            content.scrollEdgeEffectStyle(.soft, for: .top)
        } else {
            content
        }
        #else
        content
        #endif
    }
}

extension View {
    /// The one door for a page's soft top scroll edge.
    func softTopScrollEdge() -> some View { modifier(SoftTopScrollEdge()) }
}

/// The top edge of a scroll view that runs under a pinned bar (the entity card's tabs, owner 2026-11-23: *"the bar with
/// the buttons for content, perspectives and such kind of cuttoff the text in a weird way"*): the text fades out over its
/// first 16 pt instead of being sliced mid-line under the bar. A mask, not a fill, so it follows whatever ground the
/// view sits on in either theme, and not a glass material or a shadow (DR-9, DR-10, DR-14). It starts where a page's own
/// top inset ends (16–18 pt), so a page at rest is never touched by it.
struct FadedTopScrollEdge: ViewModifier {
    var height: CGFloat = CicadaTheme.scaled(16)

    func body(content: Content) -> some View {
        content.mask(alignment: .top) {
            VStack(spacing: 0) {
                LinearGradient(colors: [.clear, .black], startPoint: .top, endPoint: .bottom)
                    .frame(height: height)
                Rectangle().fill(.black)
            }
        }
    }
}

extension View {
    /// The one door for a scroll view's faded top edge under a pinned bar.
    func fadedTopEdge(height: CGFloat = CicadaTheme.scaled(16)) -> some View {
        modifier(FadedTopScrollEdge(height: height))
    }
}

/// ROR-118 - the bottom edge of a panel whose content runs past it (Settings was cut flush at a row with no cue that
/// more follows): the content eases into the panel's own ground over its last 36 pt, and the system's soft edge is
/// asked for where it exists. A fill the colour of the surface, never a shadow or a glass material (DR-9, DR-14);
/// it takes no hits.
struct SoftBottomScrollEdge: ViewModifier {
    func body(content: Content) -> some View {
        edge(content)
            .overlay(alignment: .bottom) {
                LinearGradient(colors: [CicadaTheme.bgBase.opacity(0), CicadaTheme.bgBase],
                               startPoint: .top, endPoint: .bottom)
                    .frame(height: CicadaTheme.scaled(36))
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            }
    }

    @ViewBuilder
    private func edge(_ content: Content) -> some View {
        #if canImport(SwiftUI, _version: 7.0)
        if #available(macOS 26, *) {
            content.scrollEdgeEffectStyle(.soft, for: .bottom)
        } else {
            content
        }
        #else
        content
        #endif
    }
}

extension View {
    /// The one door for a panel's soft bottom edge.
    func softBottomScrollEdge() -> some View { modifier(SoftBottomScrollEdge()) }
}
