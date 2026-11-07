import SwiftUI

/// ROR-118 round 3 — wrapped text that never strands a word. A question wraps at whatever width the card gives it, so a
/// string that just overflows one line leaves one or two short words alone on the second. This lays its one child out at
/// the narrowest width that keeps the line count the full width gives, so the lines come out even; a child that fits on
/// one line is left alone. It measures the child (a dozen proposals, no text arithmetic), so it holds for any string,
/// any size and any `uiScale`, and it is left-aligned at the container's leading edge.
struct BalancedLines: Layout {
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard let child = subviews.first else { return .zero }
        guard let width = proposal.width, width.isFinite, width > 0 else { return child.sizeThatFits(proposal) }
        return Self.balanced(child, within: width)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        guard let child = subviews.first else { return }
        let size = Self.balanced(child, within: bounds.width)
        child.place(at: bounds.origin, anchor: .topLeading,
                    proposal: ProposedViewSize(width: size.width, height: size.height))
    }

    private static func balanced(_ child: LayoutSubview, within width: CGFloat) -> CGSize {
        let full = child.sizeThatFits(ProposedViewSize(width: width, height: nil))
        let natural = child.sizeThatFits(.unspecified)
        // One line (or none): nothing to balance.
        guard natural.width > width + 0.5, full.height > 0 else { return CGSize(width: min(natural.width, width), height: full.height) }
        // Never narrower than 55 % of the room: a child that clips at a line limit would otherwise keep shrinking.
        var low = width * 0.55
        var high = width
        for _ in 0..<12 {
            let mid = (low + high) / 2
            if child.sizeThatFits(ProposedViewSize(width: mid, height: nil)).height <= full.height + 0.5 {
                high = mid
            } else {
                low = mid
            }
        }
        // A point of slack so a rounding difference never makes the final pass wrap one line more.
        return CGSize(width: min(width, high + 1), height: full.height)
    }
}
