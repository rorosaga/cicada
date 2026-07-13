import SwiftUI

// MARK: - ContextLegend
//
// Floating graph overlay (§2a). Lists each active context with its color
// swatch and a toggle. Toggling drives the SAME existing filter pipeline
// (`graphVM.filter` → `applyFilters`) via a new `contexts` key the JS
// `rebuildVisible` honors — edges/facets in a deselected context drop, so
// "show me only the engineering subgraph" is one tap. Sibling to ZoomControls.

struct ContextLegend: View {
    @Environment(GraphViewModel.self) private var graphVM
    @State private var collapsed = false

    var body: some View {
        if graphVM.contextRoster.isEmpty {
            EmptyView()   // no claim contexts yet → no legend (graceful empty state)
        } else {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                header
                if !collapsed {
                    ForEach(graphVM.contextRoster, id: \.self) { context in
                        row(context)
                    }
                    if !graphVM.filter.contexts.isEmpty {
                        Button {
                            graphVM.filter.contexts = []
                        } label: {
                            Text("Clear")
                                .font(CicadaTheme.captionFont)
                                .foregroundStyle(CicadaTheme.accent)
                        }
                        .buttonStyle(.plain)
                        .padding(.top, 2)
                    }
                }
            }
            .padding(CicadaTheme.spacingMD)
            .frame(width: 168, alignment: .leading)
            .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)
        }
    }

    private var header: some View {
        HStack(spacing: CicadaTheme.spacingXS) {
            Text("CONTEXT")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.textTertiary)
                .tracking(1.2)
            Spacer()
            Button { collapsed.toggle() } label: {
                Image(systemName: collapsed ? "chevron.up" : "chevron.down")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .buttonStyle(.plain)
        }
    }

    private func row(_ context: String) -> some View {
        // Empty filter set = all-pass: every context reads as "on".
        let isOn = graphVM.filter.contexts.isEmpty || graphVM.filter.contexts.contains(context)
        return Button {
            graphVM.toggleContext(context)
        } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Circle()
                    .fill(CicadaTheme.contextColor(context))
                    .frame(width: 9, height: 9)
                    .opacity(isOn ? 1 : 0.35)
                Text(context)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(isOn ? CicadaTheme.textPrimary : CicadaTheme.textTertiary)
                Spacer()
            }
            .padding(.vertical, 2)
        }
        .buttonStyle(.plain)
    }
}
