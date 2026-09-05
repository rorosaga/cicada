import SwiftUI

/// Relevance-sorted media feed (§3.4). Browses items saved via the sources
/// pipeline (bookmarks, pasted URLs, RSS/Atom feeds), ordered by the relevance
/// metric (``confidence x recency-decay x personal weight``) or recency. Follows
/// the Topics screen's list + TopBarControls layout and the app's CicadaTheme.
struct FeedView: View {
    @Binding var selectedTab: AppTab
    @Environment(FeedViewModel.self) private var viewModel
    /// G126 R9 — Settings → Integrations' "Import in Feed →" hand-off. The
    /// router carries a one-shot tile across the sidebar-to-Feed boundary
    /// without either view importing the other.
    @Environment(AppRouter.self) private var router
    @State private var showUploadOverlay = false
    @State private var showAddSheet = false
    @State private var sheetTile: AddSourceTile?

    var body: some View {
        ZStack {
            // No .ignoresSafeArea(): the title bar is darkened at the window level
            // (CicadaApp). Ignoring the safe area here pushed content under the menu
            // bar and stretched the window to full screen height.
            CicadaTheme.background

            VStack(alignment: .leading, spacing: 0) {
                header

                ConnectedChannelsStrip { tile in openSheet(tile) }
                    .padding(.horizontal, CicadaTheme.spacingXL)
                    .padding(.bottom, CicadaTheme.spacingMD)

                searchAndSortRow

                Text("\(viewModel.filteredItems.count) item\(viewModel.filteredItems.count == 1 ? "" : "s")")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingXL)
                    .padding(.bottom, CicadaTheme.spacingSM)

                content
            }
            // Pin the header+search+scroll column to FILL the detail area. Without
            // this, the nested ScrollView reports its full content height as the
            // VStack's ideal, which propagates up and balloons the window vertically
            // under `.prominentDetail` (Sleep avoids it by making ScrollView a direct
            // ZStack child; Feed keeps a fixed header, so it must fill explicitly).
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

            // Top-right controls (Add + Upload + Sleep + Help), shared chrome.
            // `addButton` used to live inline in the page header's trailing
            // slot (PageHeader's own right-aligned HStack), which put it at
            // nearly the same top-right coordinates as this floating overlay
            // — the header's blue "+" circle bled out from behind the Help
            // button on every Feed render (G68 §1, round 2). Feed is the only
            // page that pairs a PageHeader trailing action with the floating
            // TopBarControls row, so folding the button into this same row
            // (same pattern as GraphContainerView's AskButton) removes the
            // collision entirely instead of just tuning padding.
            VStack {
                HStack {
                    Spacer()
                    HStack(spacing: CicadaTheme.spacingSM) {
                        addButton
                        TopBarControls(
                            selectedTab: $selectedTab,
                            showUploadOverlay: $showUploadOverlay
                        )
                    }
                    .padding(CicadaTheme.spacingLG)
                }
                Spacer()
            }

            if showUploadOverlay {
                UploadOverlay(isPresented: $showUploadOverlay)
                    .transition(.opacity)
            }
        }
        // No `.task { load() }` here: `FeedViewModel` is a thin projection
        // over `Store.sources`, which the Store already hydrates from disk
        // and keeps live via SSE — this tab renders instantly from whatever
        // the Store already has, on every revisit, with no per-view refetch.
        .onChange(of: showUploadOverlay) { _, isShowing in
            // Refresh after the upload overlay closes — newly saved items appear.
            if !isShowing { Task { await viewModel.load() } }
        }
        .animation(.spring(duration: 0.3), value: showUploadOverlay)
        // ⌘N while Feed is on screen opens the picker. Hidden-button pattern,
        // same as ContentView's ⌘K — and the ONLY registration of this
        // shortcut in the app.
        .background {
            Button("") { openSheet(nil) }
                .keyboardShortcut("n", modifiers: .command)
                .buttonStyle(.cicadaPlain)
                .frame(width: 0, height: 0)
                .opacity(0)
        }
        .sheet(isPresented: $showAddSheet) {
            AddSourceSheet(initialTile: sheetTile) { showAddSheet = false }
        }
        // A hand-off can arrive either while Feed is already on screen
        // (`onChange`) or right as it appears after `AppRouter` just
        // switched the tab (`onAppear`) — both call the same consumer, and
        // `consumeAddSource()`'s read-then-clear means a second firing for
        // the same hand-off is always a no-op.
        .onAppear { consumePendingAddSource() }
        .onChange(of: router.pendingAddSource) { _, _ in consumePendingAddSource() }
    }

    private func consumePendingAddSource() {
        guard let tile = router.consumeAddSource() else { return }
        openSheet(tile)
    }

    private var header: some View {
        PageHeader(title: Copy.feed, subtitle: Copy.feedSubtitle)
    }

    private var addButton: some View {
        Button { openSheet(nil) } label: {
            Image(systemName: "plus")
                .font(CicadaTheme.font(size: 13, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 28, height: 28)
                .background(Circle().fill(CicadaTheme.accent))
        }
        .buttonStyle(.cicadaPlain)
        .help("\(Copy.addASource) (⌘N)")
        .accessibilityLabel(Copy.addASource)
    }

    private func openSheet(_ tile: AddSourceTile?) {
        sheetTile = tile
        showAddSheet = true
    }

    private var searchAndSortRow: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "magnifyingglass")
                    .font(CicadaTheme.font(size: 12))
                    .foregroundStyle(CicadaTheme.textTertiary)
                TextField("Search saved media...", text: Binding(
                    get: { viewModel.searchText },
                    set: { viewModel.searchText = $0 }
                ))
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                if !viewModel.searchText.isEmpty {
                    Button { viewModel.searchText = "" } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(CicadaTheme.font(size: 11))
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    .buttonStyle(.cicadaPlain)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)

            Picker("", selection: Binding(
                get: { viewModel.sort },
                set: { viewModel.sort = $0 }
            )) {
                ForEach(FeedViewModel.SortMode.allCases) { mode in
                    Text(mode.label).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 200)
            .accessibilityLabel("Sort feed items")
        }
        .padding(.horizontal, CicadaTheme.spacingXL)
        .padding(.bottom, CicadaTheme.spacingMD)
    }

    @ViewBuilder
    private var content: some View {
        if viewModel.isLoading && viewModel.items.isEmpty {
            Spacer()
            HStack { Spacer(); ProgressView(); Spacer() }
            Spacer()
        } else if let err = viewModel.errorMessage, viewModel.items.isEmpty {
            emptyState(
                symbol: "exclamationmark.triangle",
                title: "Couldn't load the feed",
                subtitle: err
            )
        } else if viewModel.filteredItems.isEmpty {
            emptyState(
                symbol: "tray",
                title: "Nothing saved yet",
                subtitle: Copy.emptyFeedMessage,
                useBookworm: true
            )
        } else {
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(viewModel.filteredItems) { item in
                        FeedRow(item: item, showRelevance: viewModel.scoresAreInformative)
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXL)
            }
        }
    }

    /// G117: the truly-empty case (`useBookworm`) delegates to the shared
    /// `EmptyStateView` — one component, one action path. The error case
    /// (`errorMessage` non-nil) keeps its own symbol-based rendering: it is
    /// not "nothing here yet", it is "something went wrong", and offering
    /// the same "Open Integrations" action there would point at a fix that
    /// has nothing to do with a load failure.
    @ViewBuilder
    private func emptyState(
        symbol: String,
        title: String,
        subtitle: String,
        useBookworm: Bool = false
    ) -> some View {
        if useBookworm {
            EmptyStateView(
                title: title,
                message: subtitle,
                actionLabel: "Open Integrations",
                settingsSection: .integrations
            )
        } else {
            VStack(spacing: CicadaTheme.spacingMD) {
                Spacer()
                Image(systemName: symbol)
                    .font(CicadaTheme.font(size: 40))
                    .foregroundStyle(CicadaTheme.textTertiary)
                Text(title)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text(subtitle)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
                Spacer()
            }
            .frame(maxWidth: .infinity)
        }
    }
}

// MARK: - Feed Row

/// Internal (not `private`) since G124: a source's page (`ChannelSourceView`)
/// renders its items with the exact same row the Feed does.
struct FeedRow: View {
    let item: MediaFeedItem
    let showRelevance: Bool
    @State private var isHovered = false
    @State private var showPreview = false

    var body: some View {
        Button {
            // G11: tap opens an in-app rich preview (image lightbox, youtube
            // player, or site card + WebView) instead of going straight to the
            // browser. "Open externally" is still available inside the preview.
            showPreview = true
        } label: {
            HStack(spacing: CicadaTheme.spacingMD) {
                thumbnail

                VStack(alignment: .leading, spacing: 3) {
                    Text(item.title.isEmpty ? item.url : item.title)
                        .font(CicadaTheme.font(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)

                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(item.mediaType)
                            .font(CicadaTheme.font(size: 10, design: .monospaced))
                            .foregroundStyle(CicadaTheme.mediaPink)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(CicadaTheme.mediaPink.opacity(0.12))
                            .clipShape(Capsule())

                        if let site = item.site, !site.isEmpty {
                            Text(site)
                                .font(CicadaTheme.font(size: 10))
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .lineLimit(1)
                        }
                    }
                }

                Spacer()

                if showRelevance {
                    relevanceBadge
                }
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingMD)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(isHovered ? CicadaTheme.surfaceHover : .clear)
            )
        }
        .buttonStyle(.cicadaPlain)
        .onHover { isHovered = $0 }
        .animation(.easeInOut(duration: 0.12), value: isHovered)
        .sheet(isPresented: $showPreview) {
            FeedItemPreviewSheet(item: item)
        }
    }

    @ViewBuilder
    private var thumbnail: some View {
        if let thumb = item.thumbnail, let url = URL(string: thumb) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFill()
                default:
                    placeholderIcon
                }
            }
            .frame(width: 44, height: 44)
            .clipShape(RoundedRectangle(cornerRadius: 6))
        } else {
            placeholderIcon
                .frame(width: 44, height: 44)
                .background(CicadaTheme.mediaPink.opacity(0.1))
                .clipShape(RoundedRectangle(cornerRadius: 6))
        }
    }

    private var placeholderIcon: some View {
        Image(systemName: "photo.on.rectangle.angled")
            .font(CicadaTheme.font(size: 16))
            .foregroundStyle(CicadaTheme.mediaPink.opacity(0.7))
    }

    private var relevanceBadge: some View {
        VStack(alignment: .trailing, spacing: 2) {
            Text(String(format: "%.0f%%", item.relevance * 100))
                .font(CicadaTheme.font(size: 11, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.accent)
            Text("relevance")
                .font(CicadaTheme.font(size: 8))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}

// MARK: - Feed item preview (G11)
//
// In-app preview overlay for a tapped Feed row. Renders `MediaPreview` from the
// row's `MediaFeedItem`. The website card's description is seeded from the
// row itself — `GET /sources` carries each link's `## Description` excerpt
// (G102 R12) — so the preview is instant; fetching the backing media entity on
// open is only the fallback for a row an older backend served without one.
// Degrades quietly: if that fetch fails, the preview still renders without a
// description.
private struct FeedItemPreviewSheet: View {
    let item: MediaFeedItem
    @Environment(\.dismiss) private var dismiss
    @State private var enrichedDescription: String?

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(item.title.isEmpty ? item.url : item.title)
                    .font(CicadaTheme.headingFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Spacer()
                Button { dismiss() } label: {
                    Image(systemName: "xmark")
                        .font(CicadaTheme.font(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: 28, height: 28)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(Circle())
                }
                .buttonStyle(.cicadaPlain)
            }
            .padding(CicadaTheme.spacingLG)

            Divider().background(CicadaTheme.border)

            ScrollView {
                MediaPreview(model: previewModel)
                    .padding(CicadaTheme.spacingLG)
            }
        }
        .frame(width: 480, height: 520)
        .background(CicadaTheme.background)
        .task {
            // Seed from the row (G102: /sources now carries the excerpt), and
            // only fall back to fetching the entity when the row has none.
            guard enrichedDescription == nil else { return }
            if let seeded = item.description, !seeded.isEmpty {
                enrichedDescription = seeded
                return
            }
            if let entity = try? await APIClient.shared.fetchEntity(id: item.mediaEntityId) {
                enrichedDescription = Self.firstSection(
                    ["## Description", "## Summary"],
                    in: entity.markdownContent
                )
            }
        }
    }

    private var previewModel: MediaPreviewModel {
        var model = MediaPreviewModel(item: item)
        model.description = enrichedDescription
        return model
    }

    /// Extract the first present section body under one of the given headers.
    private static func firstSection(_ headers: [String], in markdown: String) -> String? {
        let lines = markdown.components(separatedBy: "\n")
        for header in headers {
            guard let start = lines.firstIndex(where: {
                $0.trimmingCharacters(in: .whitespaces) == header
            }) else { continue }
            var body: [String] = []
            for line in lines[(start + 1)...] {
                if line.trimmingCharacters(in: .whitespaces).hasPrefix("## ") { break }
                body.append(line)
            }
            let text = body.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty { return text }
        }
        return nil
    }
}
