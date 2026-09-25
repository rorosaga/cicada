import SwiftUI

/// Direction D's depth (DESIGN_RULES §3.5 — DR-9, DR-10, DR-11). One file, so a shadow cannot
/// arrive anywhere else (`ElevationLintTests`).
///
/// - A surface that sits IN the page (a card, a block, an option row, the command bar) gets an
///   inset ring: white 7 % in dark, black 8 % in light. Never a border stroke, never a shadow.
/// - A surface that FLOATS (the palette, a tooltip, a toast, the Settings panel) gets the
///   floating ring, and in light mode ONE soft shadow (0 12 32, black 14 %). Dark mode has no
///   shadows at all: on graphite a shadow reads as dirt, and the ring already separates.
/// - The one permitted rule is a column's leading edge.
extension View {
    func ringed<S: InsettableShape>(_ ring: CicadaTheme.Ring = .resting, in shape: S) -> some View {
        overlay(shape.strokeBorder(CicadaTheme.ring(ring), lineWidth: 1))
    }

    func floatingSurface<S: InsettableShape>(in shape: S, fill: Color? = nil) -> some View {
        modifier(FloatingSurface(shape: shape, fill: fill))
    }

    func columnEdge(_ edge: HorizontalEdge = .leading) -> some View {
        overlay(alignment: edge == .leading ? .leading : .trailing) {
            Rectangle().fill(CicadaTheme.ring(.edge)).frame(width: 1)
        }
    }
}

private struct FloatingSurface<S: InsettableShape>: ViewModifier {
    let shape: S
    let fill: Color?

    @ViewBuilder
    func body(content: Content) -> some View {
        let surface = content
            .background(shape.fill(fill ?? CicadaTheme.bgMenu))
            .overlay(shape.strokeBorder(CicadaTheme.ring(.floating), lineWidth: 1))
        // Reading `mode` subscribes this view, so a theme flip adds or drops the shadow.
        if CicadaTheme.mode == .light {
            surface.shadow(color: .black.opacity(0.14), radius: 16, y: 12)
        } else {
            surface
        }
    }
}
