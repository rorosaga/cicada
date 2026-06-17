import SwiftUI

// MARK: - ObserverFilterBar
//
// Graph-level "who believes what" lens (§3a). A segmented control
// All · Cicada · Rodrigo · External that calls `applyFilters` with an
// `observers` array; graph.js DIMS (not deletes) non-matching nodes via the
// focus-alpha mechanism, so the contrast reads as "this is the slice Rodrigo
// personally asserts vs. what the agent inferred." Sibling to FilterButton.

struct ObserverFilterBar: View {
    @Environment(GraphViewModel.self) private var graphVM
    @State private var selection: String? = nil   // nil = All

    /// The fixed segments. "external" is a synthetic wire matching every
    /// `external:*` observer (handled by GraphViewModel.setObserver).
    private var segments: [(label: String, wire: String?, symbol: String)] {
        [
            ("All", nil, "circle.grid.2x2"),
            ("Cicada", "agent", "cpu"),
            ("Rodrigo", "rodrigo", "person.fill"),
            ("External", "external", "quote.bubble.fill"),
        ]
    }

    var body: some View {
        // Only show once the graph actually carries observer data — otherwise
        // the filter is a no-op control that would just confuse the demo.
        if graphVM.observerRoster.isEmpty {
            EmptyView()
        } else {
            HStack(spacing: 1) {
                ForEach(segments, id: \.label) { seg in
                    segmentButton(seg)
                }
            }
            .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
        }
    }

    private func segmentButton(_ seg: (label: String, wire: String?, symbol: String)) -> some View {
        let isSelected = selection == seg.wire
        return Button {
            selection = seg.wire
            graphVM.setObserver(seg.wire)
        } label: {
            HStack(spacing: 4) {
                Image(systemName: seg.symbol)
                    .font(.system(size: 10, weight: .medium))
                Text(seg.label)
                    .font(.system(size: 11, weight: .medium))
            }
            .foregroundStyle(isSelected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(height: 32)
            .background(isSelected ? CicadaTheme.surfaceHover : .clear)
        }
        .buttonStyle(.plain)
    }
}
