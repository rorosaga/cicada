import SwiftUI

/// Owner 2026-11-25: while a list's bubble is open on the canvas, one small chip at the top says which list it is and how
/// to leave it — the source's mark, the list's name, what it holds, and ×. The name opens the list's own page when it has
/// one. An opaque floating surface like the Graph's other group (R-DG2); no accent (DR-5); SF type.
struct GraphBubbleChip: View {
    let bubble: GraphBubble
    @Environment(GraphViewModel.self) private var graphVM

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            if let mark = bubble.mark, OriginMark.hasRealMark(mark) {
                OriginMark(origin: mark, size: CicadaTheme.scaled(16))
            }
            if let page = bubble.pageId {
                Button { graphVM.selectEntity(id: page) } label: { title }
                    .buttonStyle(.plain)
                    .help(Copy.Graph.bubbleOpenPage)
            } else {
                title
            }
            Text(Copy.Graph.bubbleHolds(bubble.count, noun: bubble.kindNoun))
                .font(CicadaTheme.captionFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
            IconButton(systemName: "xmark", help: Copy.Graph.bubbleClose) { graphVM.zoomAction = .closeBubble }
        }
        .padding(.leading, CicadaTheme.spacingMD)
        .padding(.trailing, CicadaTheme.spacingXS)
        .frame(height: CicadaTheme.scaled(GraphControlGroup.height))
        .floatingSurface(in: CicadaTheme.shape(CicadaTheme.cornerRadius))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Copy.Graph.bubbleLabel(bubble.name))
    }

    private var title: some View {
        Text(bubble.name)
            .font(CicadaTheme.rowFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .lineLimit(1)
    }
}
