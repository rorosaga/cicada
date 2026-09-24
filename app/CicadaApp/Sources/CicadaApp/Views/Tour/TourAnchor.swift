import SwiftUI

/// G152 — every target a stop can point at publishes its bounds; `TourLayer` reads them through ContentView's
/// `overlayPreferenceValue`, in the page area's own coordinates. A page that is not on screen publishes nothing, and
/// the stop's next candidate (or the middle of the page) takes over.
struct TourAnchorKey: PreferenceKey {
    static var defaultValue: [TourAnchorID: Anchor<CGRect>] = [:]
    static func reduce(value: inout [TourAnchorID: Anchor<CGRect>], nextValue: () -> [TourAnchorID: Anchor<CGRect>]) {
        value.merge(nextValue()) { _, new in new }
    }
}

extension View {
    /// Marks this view as the target of a tour stop (`TourPlan`). Reading bounds changes nothing on the page.
    func tourAnchor(_ id: TourAnchorID) -> some View {
        anchorPreference(key: TourAnchorKey.self, value: .bounds) { [id: $0] }
    }
}
