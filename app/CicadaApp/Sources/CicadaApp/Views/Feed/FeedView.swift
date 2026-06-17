import SwiftUI

/// Relevance-sorted media feed (§3.4). Browses items saved via the sources
/// pipeline (bookmarks, pasted URLs, RSS/Atom feeds), ordered by the relevance
/// metric (``confidence x recency-decay x personal weight``) or recency. Follows
/// the Topics screen's list + TopBarControls layout and the app's CicadaTheme.
struct FeedView: View {
    @Binding var selectedTab: AppTab
    @State private var viewModel = FeedViewModel()
    @State private var showUploadOverlay = false

    var body: some View {
        ZStack {
            // No .ignoresSafeArea(): the title bar is darkened at the window level
            // (CicadaApp). Ignoring the safe area here pushed content under the menu
            // bar and stretched the window to full screen height.
            CicadaTheme.background

            VStack(alignment: .leading, spacing: 0) {
                header

                searchAndSortRow

                Text("\(viewModel.filteredItems.count) item\(viewModel.filteredItems.count == 1 ? "" : "s")")
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingXL)
                    .padding(.bottom, CicadaTheme.spacingSM)

                content
            }

            // Top-right controls (Upload + Sleep), shared chrome.
            VStack {
                HStack {
                    Spacer()
                    TopBarControls(
                        selectedTab: $selectedTab,
                        showUploadOverlay: $showUploadOverlay
                    )
                    .padding(CicadaTheme.spacingLG)
                }
                Spacer()
            }

            if showUploadOverlay {
                UploadOverlay(isPresented: $showUploadOverlay)
                    .transition(.opacity)
            }
        }
        .task { await viewModel.load() }
        .onChange(of: showUploadOverlay) { _, isShowing in
            // Refresh after the upload overlay closes — newly saved items appear.
            if !isShowing { Task { await viewModel.load() } }
        }
        .animation(.spring(duration: 0.3), value: showUploadOverlay)
    }

    private var header: some View {
        PageHeader(
            title: "Feed",
            subtitle: "Recently ingested sources and saved resources."
        )
    }

    private var searchAndSortRow: some View {
        HStack(spacing: CicadaTheme.spacingMD) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 12))
                    .foregroundStyle(CicadaTheme.textTertiary)
                TextField("Search saved media...", text: $viewModel.searchText)
                    .textFieldStyle(.plain)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                if !viewModel.searchText.isEmpty {
                    Button { viewModel.searchText = "" } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 11))
                            .foregroundStyle(CicadaTheme.textTertiary)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingSM)
            .glassCard(cornerRadius: CicadaTheme.cornerRadiusSmall)

            Picker("", selection: $viewModel.sort) {
                ForEach(FeedViewModel.SortMode.allCases) { mode in
                    Text(mode.label).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 200)
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
                subtitle: "Save bookmarks, paste URLs, or add an RSS feed.\nThey appear here sorted by relevance.",
                useBookworm: true
            )
        } else {
            ScrollView {
                LazyVStack(spacing: 2) {
                    ForEach(viewModel.filteredItems) { item in
                        FeedRow(item: item)
                    }
                }
                .padding(.horizontal, CicadaTheme.spacingXL)
                .padding(.bottom, CicadaTheme.spacingXL)
            }
        }
    }

    private func emptyState(
        symbol: String,
        title: String,
        subtitle: String,
        useBookworm: Bool = false
    ) -> some View {
        VStack(spacing: CicadaTheme.spacingMD) {
            Spacer()
            if useBookworm {
                // The animated mascot greets the empty ingestion area, mirroring
                // the Inbox "all caught up" worm and the upload overlay.
                BookwormView(state: .awake, pointSize: 72)
            } else {
                Image(systemName: symbol)
                    .font(.system(size: 40))
                    .foregroundStyle(CicadaTheme.textTertiary)
            }
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

// MARK: - Feed Row

private struct FeedRow: View {
    let item: MediaFeedItem
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
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .lineLimit(1)

                    HStack(spacing: CicadaTheme.spacingSM) {
                        Text(item.mediaType)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(CicadaTheme.mediaPink)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(CicadaTheme.mediaPink.opacity(0.12))
                            .clipShape(Capsule())

                        if let site = item.site, !site.isEmpty {
                            Text(site)
                                .font(.system(size: 10))
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .lineLimit(1)
                        }
                    }
                }

                Spacer()

                relevanceBadge
            }
            .padding(.horizontal, CicadaTheme.spacingMD)
            .padding(.vertical, CicadaTheme.spacingMD)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(isHovered ? CicadaTheme.surfaceHover : .clear)
            )
        }
        .buttonStyle(.plain)
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
            .font(.system(size: 16))
            .foregroundStyle(CicadaTheme.mediaPink.opacity(0.7))
    }

    private var relevanceBadge: some View {
        VStack(alignment: .trailing, spacing: 2) {
            Text(String(format: "%.0f%%", item.relevance * 100))
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .foregroundStyle(CicadaTheme.accent)
            Text("relevance")
                .font(.system(size: 8))
                .foregroundStyle(CicadaTheme.textTertiary)
        }
    }
}

// MARK: - Feed item preview (G11)
//
// In-app preview overlay for a tapped Feed row. Renders `MediaPreview` from the
// row's `MediaFeedItem`, and best-effort enriches the website card's description
// by fetching the backing media entity on open (the Feed payload has no
// description). Degrades quietly: if the fetch fails, the preview still renders
// without a description.
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
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .frame(width: 28, height: 28)
                        .background(CicadaTheme.surfaceHover)
                        .clipShape(Circle())
                }
                .buttonStyle(.plain)
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
            // Enrich the description (only useful for website/bookmark cards).
            guard enrichedDescription == nil else { return }
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
