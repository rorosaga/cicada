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
