import SwiftUI

/// The unified Inbox screen. One scrollable list of `InboxCardView`s, sorted by
/// priority then recency, with a kind filter and the bookworm "nothing pending"
/// empty state, which states what the backend last did rather than promising a
/// cycle (G115 R12). Replaces the separate Nudges + Clarifications tabs.
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

            // Order matters. Error first: a failed `GET /inbox` leaves `items`
            // empty and would otherwise read as the happy state. Loading
            // second: an empty snapshot mid-first-fetch is not "nothing pending",
            // and claiming it is for a round-trip is the worst possible lie for
            // this page to tell.
            if let err = viewModel.errorMessage, viewModel.items.isEmpty {
                errorState(err)
            } else if viewModel.isLoading {
                loadingState
            } else if viewModel.items.isEmpty {
                emptyState
            } else {
                ScrollView {
                    LazyVStack(spacing: CicadaTheme.spacingSM) {
                        ForEach(visibleItems) { item in
                            InboxCardView(item: item) { resolution in
                                await viewModel.resolve(
                                    id: item.id,
                                    action: resolution.action,
                                    answer: resolution.answer,
                                    optionKey: resolution.optionKey,
                                    remindDays: resolution.remindDays,
                                    mergeTarget: resolution.mergeTarget,
                                    mergeSurvivor: resolution.mergeSurvivor
                                )
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
        // The title bar is darkened at the window level (titlebarAppearsTransparent
        // + dark backgroundColor in CicadaApp), so the content background must NOT
        // ignoreSafeArea here — combined with maxHeight:.infinity that extended the
        // content under the menu bar and stretched the whole window to full height.
        .background(CicadaTheme.background)
    }

    // MARK: - Header (title + kind filter chips)

    private var headerBar: some View {
        VStack(alignment: .leading, spacing: 0) {
            PageHeader(
                title: "Inbox",
                subtitle: Copy.inboxSubtitle
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
        return [.decay, .conflict, .clarification, .mergeSuggestion, .removal].filter { present.contains($0) }
    }

    // MARK: - Empty state ("Nothing pending" + the truth, featuring the bookworm)

    private var emptyState: some View {
        // G117: same shared shell as Graph/Feed/Sources, but `emptyStateDetail`
        // — the R12-honest, possibly two-line "what Sleep actually did" text —
        // stays exactly as computed. "Nothing pending" is a GOOD state, not a
        // deficiency to fix, so it carries no action (unlike a graph or a
        // sources list with nothing in it, where Integrations is the fix).
        EmptyStateView(title: "Nothing pending", message: emptyStateDetail)
    }

    /// R12: say what is true, not what the bookworm will do. Sleep asks
    /// questions; if it has not run, nothing has been asked yet. The old copy
    /// ("the bookworm will surface new items after the next Sleep cycle")
    /// promised a future that a disabled schedule or a failed cycle never
    /// delivers.
    private var emptyStateDetail: String {
        var lines: [String] = []
        if let last = viewModel.lastSleepAt,
           let days = InboxAge.days(since: last, now: .now) {
            lines.append("Last Sleep cycle \(InboxAge.phrase(days: days)).")
        } else {
            lines.append("Sleep has not run yet, so nothing has been asked.")
        }
        let queued = viewModel.unprocessedEpisodes
        if queued > 0 {
            lines.append("\(queued) episode\(queued == 1 ? "" : "s") waiting for the next cycle.")
        }
        return lines.joined(separator: "\n")
    }

    // MARK: - Loading state (first fetch, nothing cached)

    private var loadingState: some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            Spacer()
            ProgressView().controlSize(.small)
            Text("Checking what needs you…")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
            Spacer()
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: - Error state (load failure — distinct from "Nothing pending")

    private func errorState(_ message: String) -> some View {
        VStack(spacing: CicadaTheme.spacingLG) {
            Spacer()
            Image(systemName: "exclamationmark.triangle")
                .font(CicadaTheme.font(size: 40))
                .foregroundStyle(CicadaTheme.textTertiary)

            Text("Couldn't load the inbox")
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)

            Text(message)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)

            Button {
                Task { await viewModel.loadInbox() }
            } label: {
                Text("Retry")
                    .font(CicadaTheme.font(size: 12, weight: .medium))
                    .padding(.horizontal, CicadaTheme.spacingMD)
                    .padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
            .tint(CicadaTheme.accent)

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
                    .font(CicadaTheme.font(size: 11, weight: .medium))
                Text("\(count)")
                    .font(CicadaTheme.font(size: 10, design: .monospaced))
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
        .buttonStyle(.cicadaPlain)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.12), value: isHovered)
        .animation(.easeInOut(duration: 0.15), value: selected)
    }
}
