import SwiftUI

/// §5.3 / §10 Feed — the saved items in the list column. With nothing open the Connected strip and the export waits
/// scroll WITH the list (R-DL17: the old page stacked them above it and could push its own header under the titlebar);
/// beside a detail the column is rows only.
struct FeedListColumn: View {
    let style: ColumnPlan.ListStyle
    @Binding var findOpen: Bool
    let searching: Bool
    let landingToken: Int
    let open: (MediaFeedItem) -> Void
    let move: (Int) -> Void
    let focusDetail: () -> Void
    let escape: () -> Void
    let openSheet: (AddSourceTile?) -> Void

    @Environment(FeedViewModel.self) private var viewModel
    @Environment(IntakeRouter.self) private var intake

    private var searchText: Binding<String> {
        Binding(get: { viewModel.searchText }, set: { viewModel.searchText = $0 })
    }

    var body: some View {
        let now = Date.now
        ScrollViewReader { proxy in
            VStack(alignment: .leading, spacing: 0) {
                // DR-46 — the find row sits above the scroll, never in the lazy stack: a lazy row scrolled far away is
                // released, and the field would take its focus and its ⌘F publisher with it.
                if findOpen {
                    PageFindRow(text: searchText, isOpen: $findOpen, prompt: Copy.Lists.findFeed)
                        .padding(EdgeInsets(top: 0, leading: ListInsets.of(style).leading, bottom: CicadaTheme.spacingSM,
                                            trailing: ListInsets.of(style).trailing))
                }
                ScrollView {
                    LazyVStack(alignment: .leading,
                               spacing: style == .titles || style == .hidden ? 0 : CicadaTheme.scaled(RowMetrics.twoLineGap)) {
                        if style == .wide && !searching {
                            // Labelled, not a trailing closure: `FeedLayoutPinTests` finds the call by its opening paren.
                            ConnectedChannelsStrip(onManage: { openSheet($0) })
                                .padding(.horizontal, CicadaTheme.scaled(10))
                                .padding(.bottom, CicadaTheme.spacingMD)
                            ExportWaitStrip()
                        }
                        content(now)
                    }
                    .padding(ListInsets.of(style))
                }
                .onChange(of: landingToken) { _, _ in
                    guard let id = viewModel.columns.openId else { return }
                    Instant.run { proxy.scrollTo(id, anchor: .center) }
                }
                .onChange(of: viewModel.columns.openId) { _, id in
                    guard let id else { return }
                    Instant.run { proxy.scrollTo(id) }
                }
            }
        }
        .listKeys(move: move, enter: {
            guard viewModel.columns.openId != nil else { return false }
            focusDetail()
            return true
        }, escape: escape)
    }

    @ViewBuilder
    private func content(_ now: Date) -> some View {
        switch FeedPageState.of(isLoading: viewModel.isLoading, error: viewModel.errorMessage,
                                hasItems: !viewModel.items.isEmpty, visibleEmpty: viewModel.visible.isEmpty,
                                searching: searching) {
        case .loading:
            ListSkeleton(message: Copy.Lists.readingFeed)
        case .failed(let message):
            ListErrorCard(title: Copy.Lists.feedLoadFailed, message: message) { Task { await viewModel.load() } }
        case .empty:
            // G117 — one honest empty state, one action; an export can land right here (R-IA27).
            EmptyStateView(title: Copy.Lists.nothingSaved, message: Copy.emptyFeedMessage,
                           actionLabel: "Open Integrations", settingsSection: .integrations,
                           onDropFiles: { intake.accept(urls: $0, from: .emptyState(.feed)) })
        case .noMatch:
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                Text(Copy.Lists.noFeedMatch(SearchAllMemoryRow.trimmed(viewModel.searchText)))
                    .font(CicadaTheme.detailBodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                SearchAllMemoryRow(query: viewModel.searchText)
            }
            .padding(.horizontal, CicadaTheme.scaled(10))
        case .list:
            ForEach(viewModel.visible) { item in
                FeedListRow(item: item, style: style, showsRelevance: viewModel.scoresAreInformative,
                            selected: item.id == viewModel.columns.openId, now: now) { open(item) }
                    .id(item.id)
            }
        }
    }
}

/// One saved item (§10: "Rows are 56 pt: mark, title and source line, with a thumbnail only for media"). The origin's
/// real mark where one exists (DR-52), else the kind's glyph — never both (DR-48). Relevance only when the scores differ.
struct FeedListRow: View {
    let item: MediaFeedItem
    let style: ColumnPlan.ListStyle
    var showsRelevance = false
    let selected: Bool
    let now: Date
    let open: () -> Void

    private var metaColor: Color { selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary }
    private var title: String { item.title.isEmpty ? item.url : item.title }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Button(action: open) {
                content
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(Copy.Lists.feedRow(title: title, open: selected))
            .accessibilityAddTraits(selected ? .isSelected : [])
            if style == .wide {
                IconButton(systemName: "chevron.right", help: Copy.Lists.openItem, action: open)
                    .accessibilityHidden(true)
            }
        }
        .listRowSurface(height: ListRowSurface.height(style, twoLineAtRest: true), selected: selected)
    }

    @ViewBuilder
    private var mark: some View {
        if let origin = FeedSourceLine.markOrigin(item) {
            OriginMark(origin: origin, size: CicadaTheme.scaled(12))
        } else {
            Image(systemName: FeedKind.of(item).glyph)
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
        }
    }

    private var titleText: some View {
        Text(title)
            .font(CicadaTheme.font(size: 13, weight: .medium))
            .foregroundStyle(CicadaTheme.textPrimary)
            .lineLimit(1)
    }

    @ViewBuilder
    private var content: some View {
        switch style {
        case .wide, .triage:
            HStack(alignment: .top, spacing: CicadaTheme.scaled(10)) {
                mark.frame(width: CicadaTheme.scaled(14)).padding(.top, CicadaTheme.scaled(2))
                VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                    HStack(spacing: CicadaTheme.spacingMD) {
                        titleText
                        Spacer(minLength: 0)
                        if style == .wide && showsRelevance {
                            Text(UsageFormat.percent(item.relevance * 100))
                                .font(CicadaTheme.metaFont)
                                .monospacedDigit()
                                .foregroundStyle(metaColor)
                                .help(Copy.Lists.relevanceHelp)
                        }
                        if let age = FeedDates.age(item, now: now) {
                            Text(age)
                                .font(CicadaTheme.metaFont)
                                .monospacedDigit()
                                .foregroundStyle(metaColor)
                                .help(FeedDates.day(item, withYear: true) ?? "")
                        }
                    }
                    Text(FeedRowText.detail(item))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(metaColor)
                        .lineLimit(1)
                }
                if style == .wide, FeedKind.of(item) == .video, let thumb = item.thumbnail, let url = URL(string: thumb) {
                    AsyncImage(url: url) { phase in
                        if case .success(let image) = phase { image.resizable().scaledToFill() } else { CicadaTheme.bgSelected }
                    }
                    .frame(width: CicadaTheme.scaled(36), height: CicadaTheme.scaled(36))
                    .clipShape(CicadaTheme.shape(CicadaTheme.radiusXS))
                    .accessibilityHidden(true)
                }
            }
        case .titles, .hidden:
            HStack(spacing: CicadaTheme.spacingSM) {
                mark.frame(width: CicadaTheme.scaled(14))
                titleText
            }
            .help(title)
        }
    }
}
