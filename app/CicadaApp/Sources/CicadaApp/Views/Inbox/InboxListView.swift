import SwiftUI

/// The unified Inbox screen. One scrollable list of `InboxCardView`s, sorted by
/// priority then recency, with a kind filter and the bookworm "all caught up"
/// empty state. Replaces the separate Nudges + Clarifications tabs.
struct InboxListView: View {
    @Environment(InboxViewModel.self) private var viewModel
    @State private var kindFilter: InboxKind?

    private var visibleItems: [InboxItem] {
        let base = kindFilter.map { k in viewModel.items.filter { $0.kind == k } }
            ?? viewModel.items
        return base.sorted {
            if $0.priority != $1.priority { return $0.priority > $1.priority }
            return $0.createdDateValue > $1.createdDateValue
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            headerBar

            if viewModel.items.isEmpty {
                emptyState
            } else {
                ScrollView {
                    LazyVStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(visibleItems) { item in
                            InboxCardView(item: item) { action, answer, mergeTarget in
                                Task {
                                    await viewModel.resolve(
                                        id: item.id, action: action,
                                        answer: answer, mergeTarget: mergeTarget
                                    )
                                }
                            }
                            .transition(.asymmetric(
                                insertion: .opacity,
                                removal: .opacity.combined(with: .scale(scale: 0.96)).combined(with: .move(edge: .trailing))
                            ))
                        }
                    }
                    .padding(CicadaTheme.spacingXL)
                    .animation(.spring(duration: 0.3), value: viewModel.items.map(\.id))
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CicadaTheme.background)
        .task { await viewModel.loadInbox() }
    }

    // MARK: - Header (title + kind filter chips)

    private var headerBar: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(
                title: "Inbox",
                subtitle: "Nudges and clarifications waiting on you."
            ) {
                if !viewModel.items.isEmpty {
                    Text("\(viewModel.items.count) pending")
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                }
            }

            if !viewModel.items.isEmpty {
                HStack(spacing: CicadaTheme.spacingSM) {
                    KindChip(label: "All", color: CicadaTheme.accent,
                             count: viewModel.items.count,
                             selected: kindFilter == nil) {
                        kindFilter = nil
                    }
                    ForEach(orderedKinds, id: \.self) { kind in
                        KindChip(label: kind.label, color: kind.color,
                                 count: viewModel.countByKind[kind] ?? 0,
                                 selected: kindFilter == kind) {
                            kindFilter = (kindFilter == kind) ? nil : kind
                        }
                    }
                    Spacer()
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingMD)
            }
        }
    }

    /// Kinds present in the current inbox, in a stable display order.
    private var orderedKinds: [InboxKind] {
        let present = Set(viewModel.items.map(\.kind))
        return [.decay, .conflict, .clarification, .mergeSuggestion].filter { present.contains($0) }
    }

    // MARK: - Empty state ("All caught up", featuring the bookworm)

    private var emptyState: some View {
        VStack(spacing: CicadaTheme.spacingLG) {
            Spacer()
            Image(nsImage: BookwormRenderer.image(grid: BookwormSprites.happy, pointSize: 88))
                .renderingMode(.template)
                .interpolation(.none)
                .foregroundStyle(CicadaTheme.accent.opacity(0.85))

            Text("All caught up")
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)

            Text("Nothing needs your attention right now.\nThe bookworm will surface new items after the next Sleep cycle.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Kind filter chip

private struct KindChip: View {
    let label: String
    let color: Color
    let count: Int
    let selected: Bool
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Circle()
                    .fill(color)
                    .frame(width: 7, height: 7)
                Text(label)
                    .font(.system(size: 11, weight: .medium))
                Text("\(count)")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
            .foregroundStyle(selected ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, 6)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(selected ? color.opacity(0.18) : (isHovered ? CicadaTheme.surfaceHover : CicadaTheme.surface.opacity(0.5)))
            )
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(selected ? color.opacity(0.5) : Color.clear, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.12), value: isHovered)
        .animation(.easeInOut(duration: 0.15), value: selected)
    }
}
