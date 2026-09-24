import CoreGraphics

/// G152 — where a coach mark sits (pure; `TourTests`). Under its target when there is room, else over it, else beside
/// it; a target too big for any of those (a full-width list) keeps the callout at the foot of the page, where page
/// content — always top-aligned — is least likely to be; no target at all puts it in the middle. Always inside the
/// page with a 16 pt margin, so it is never cut by the window's edge or pushed under the rail.
enum CoachMarkLayout {
    static let width: CGFloat = 320
    static let margin: CGFloat = 16
    static let gap: CGFloat = 12
    /// The hole is this much larger than its target, so the focus ring never sits on the target's own edge.
    static let holeInset: CGFloat = 6

    enum Edge: Equatable { case below, above, trailing, leading, foot, center }

    struct Placement: Equatable {
        var origin: CGPoint
        var edge: Edge
    }

    static func place(target: CGRect?, container: CGSize, callout: CGSize, scale: CGFloat) -> Placement {
        let m = margin * scale, g = gap * scale
        let w = callout.width, h = callout.height
        func clampX(_ x: CGFloat) -> CGFloat { min(max(x, m), max(m, container.width - w - m)) }
        func clampY(_ y: CGFloat) -> CGFloat { min(max(y, m), max(m, container.height - h - m)) }
        guard let t = target, !t.isNull, t.width > 0 else {
            return Placement(origin: CGPoint(x: clampX((container.width - w) / 2), y: clampY((container.height - h) / 2)),
                             edge: .center)
        }
        if t.maxY + g + h <= container.height - m {
            return Placement(origin: CGPoint(x: clampX(t.midX - w / 2), y: t.maxY + g), edge: .below)
        }
        if t.minY - g - h >= m {
            return Placement(origin: CGPoint(x: clampX(t.midX - w / 2), y: t.minY - g - h), edge: .above)
        }
        if t.maxX + g + w <= container.width - m {
            return Placement(origin: CGPoint(x: t.maxX + g, y: clampY(t.minY)), edge: .trailing)
        }
        if t.minX - g - w >= m {
            return Placement(origin: CGPoint(x: t.minX - g - w, y: clampY(t.minY)), edge: .leading)
        }
        return Placement(origin: CGPoint(x: clampX((container.width - w) / 2), y: clampY(container.height - h - m)),
                         edge: .foot)
    }

    /// The command bar is a toolbar item centred in the WINDOW (DR-23), while the page area starts after the rail, so
    /// in the page's coordinates its centre is `(pageWidth − navWidth) / 2`. A zero-height rect on the page's top
    /// edge: the callout sits right under the titlebar, as F-08 draws it.
    static func commandBarRect(pageWidth: CGFloat, navWidth: CGFloat, scale: CGFloat) -> CGRect {
        let w = ShellMetrics.commandBarWidth * scale
        return CGRect(x: (pageWidth - navWidth) / 2 - w / 2, y: 0, width: w, height: 0)
    }
}
