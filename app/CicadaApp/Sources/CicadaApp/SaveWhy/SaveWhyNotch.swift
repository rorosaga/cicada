import AppKit
import SwiftUI

/// G191 v2 (owner 2026-10-14: "the thing coming down out of the notch … the same black as the notch … seamless") —
/// where the panel sits and the shape it grows from. Pure, so it is tested against a notch rect and a plain screen
/// without a display.
///
/// **The picture.** The panel is the notch growing: its window's top edge is the screen's top edge, its body is the
/// notch's black, and at rest it is exactly the notch's size and place — invisible against the hardware — before a
/// spring grows it down and out into the question. Where the grown body meets the top of the screen its corners flare
/// outward (`ear`), the way the hardware notch meets the menu bar; its bottom corners are continuous and round. The
/// top band, as tall as the notch, holds nothing (the camera housing sits in its middle); the content starts under it.
/// On a Mac without a notch the same shape grows from a zero-height sliver at the top centre, its band the menu bar.
enum SaveWhyNotch {
    /// The outward flare where the panel meets the screen's top edge.
    static let ear: CGFloat = 10
    /// The grown panel's bottom corners.
    static let bottomRadius: CGFloat = 22
    /// The hardware notch's own bottom corners — the shape's corners at rest, so the start matches the notch.
    static let notchBottomRadius: CGFloat = 9
    /// A Mac without a notch: the width of the sliver the panel grows from (about a notch's width).
    static let plainWidth: CGFloat = 190
    /// The menu bar's height when the screen does not say (full screen, auto-hide) and there is no notch either.
    static let fallbackMenuBar: CGFloat = 24

    /// The hardware notch in screen coordinates (origin bottom-left), from the two menu-bar areas either side of it
    /// (`NSScreen.auxiliaryTopLeftArea` / `auxiliaryTopRightArea`) and the safe-area top inset. Nil on a screen with
    /// no notch (no inset, or no areas).
    static func notchRect(screen: CGRect, topLeft: CGRect?, topRight: CGRect?, topInset: CGFloat) -> CGRect? {
        guard topInset > 0, let topLeft, let topRight, topRight.minX > topLeft.maxX else { return nil }
        return CGRect(x: topLeft.maxX, y: screen.maxY - topInset, width: topRight.minX - topLeft.maxX,
                      height: topInset)
    }

    /// The empty band at the top of the panel: the notch's height, else the menu bar's.
    static func band(screen: CGRect, visible: CGRect, notch: CGRect?) -> CGFloat {
        if let notch { return notch.height }
        let menuBar = screen.maxY - visible.maxY
        return menuBar > 0 ? menuBar : fallbackMenuBar
    }

    /// The shape's size at rest: the notch plus its two ears (so the body is the notch exactly), or a sliver.
    static func collapsed(notch: CGRect?) -> CGSize {
        CGSize(width: (notch?.width ?? plainWidth) + 2 * ear, height: notch?.height ?? 0)
    }

    /// The window: `size` (the whole view — band, ears and content) centred under the notch (else the screen),
    /// its top flush with the screen's top edge.
    static func frame(screen: CGRect, notch: CGRect?, size: CGSize) -> CGRect {
        let midX = notch?.midX ?? screen.midX
        return CGRect(x: (midX - size.width / 2).rounded(), y: screen.maxY - size.height,
                      width: size.width, height: size.height)
    }
}

/// The panel's outline at `progress` 0 (the notch at rest) … 1 (grown to the view's bounds), animatable so one spring
/// drives the grow and the shrink. Top-centred: the top edge always lies on the screen's top edge.
struct SaveWhyNotchShape: Shape {
    var progress: CGFloat
    let collapsed: CGSize
    var ear: CGFloat = SaveWhyNotch.ear
    var bottomRadius: CGFloat = SaveWhyNotch.bottomRadius
    var restRadius: CGFloat = SaveWhyNotch.notchBottomRadius

    var animatableData: CGFloat {
        get { progress }
        set { progress = newValue }
    }

    func path(in rect: CGRect) -> Path {
        // A spring's overshoot may carry progress past 1: the bounds clip it, so the width and height stop there and
        // only the corners keep the give.
        let p = min(max(progress, 0), 1)
        let width = collapsed.width + (rect.width - collapsed.width) * p
        let height = collapsed.height + (rect.height - collapsed.height) * p
        var path = Path()
        guard width > 2 * ear, height > 0.5 else { return path }
        let left = rect.midX - width / 2
        let right = rect.midX + width / 2
        let top = rect.minY
        let bottom = top + height
        let e = min(ear, height / 2)
        let r = min(restRadius + (bottomRadius - restRadius) * p, (width - 2 * e) / 2, height - e)
        // The ears: concave quarter-curves from the top edge into the body's sides.
        path.move(to: CGPoint(x: left, y: top))
        path.addQuadCurve(to: CGPoint(x: left + e, y: top + e), control: CGPoint(x: left + e, y: top))
        path.addLine(to: CGPoint(x: left + e, y: bottom - r))
        // Continuous bottom corners: a cubic whose handles run past the quarter-circle's, so the curvature eases in.
        path.addCurve(to: CGPoint(x: left + e + r, y: bottom),
                      control1: CGPoint(x: left + e, y: bottom - r * 0.28),
                      control2: CGPoint(x: left + e + r * 0.28, y: bottom))
        path.addLine(to: CGPoint(x: right - e - r, y: bottom))
        path.addCurve(to: CGPoint(x: right - e, y: bottom - r),
                      control1: CGPoint(x: right - e - r * 0.28, y: bottom),
                      control2: CGPoint(x: right - e, y: bottom - r * 0.28))
        path.addLine(to: CGPoint(x: right - e, y: top + e))
        path.addQuadCurve(to: CGPoint(x: right, y: top), control: CGPoint(x: right - e, y: top))
        path.closeSubpath()
        return path
    }
}
