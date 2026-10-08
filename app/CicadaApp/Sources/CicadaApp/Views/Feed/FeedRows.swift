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
    /// G162 — the Videos tab's strip opens the watch run.
    var chooseVideos: () -> Void = {}

    @Environment(FeedViewModel.self) private var viewModel
    @Environment(VideoStateCache.self) private var videoCache: VideoStateCache?
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
                        if style == .wide && !searching && showsVideosStrip {
                            // G162 — the Videos tab's own strip stands where the Connected strip stands elsewhere.
                            VideosStrip(summary: videoCache?.summary, choose: chooseVideos)
                                .padding(.bottom, CicadaTheme.spacingSM)
                        } else if style == .wide && !searching {
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

    /// The Videos tab, with a backend that answers the video reads.
    private var showsVideosStrip: Bool {
        viewModel.kind == .video && videoCache.map { !$0.isGone } == true
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
            // Once per render, not once per row: it reads every saved item.
            let showsRelevance = viewModel.scoresAreInformative
            ForEach(viewModel.visible) { item in
                FeedListRow(item: item, style: style, showsRelevance: showsRelevance,
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

    /// G162 — a video's state word ("Transcript", "Queued") joins its age; optional so a host without the cache (a
    /// layout test) draws the plain row.
    @Environment(VideoStateCache.self) private var videoCache: VideoStateCache?

    private var metaColor: Color { selected ? CicadaTheme.textTertiaryOnFill : CicadaTheme.textTertiary }
    private var title: String { item.title.isEmpty ? item.url : item.title }
    private var isVideo: Bool { FeedKind.of(item) == .video }
    private var videoState: VideoStateItem? { isVideo ? videoCache?.item(feedId: item.id) : nil }

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
            HStack(alignment: isVideo ? .center : .top, spacing: CicadaTheme.scaled(10)) {
                mark.frame(width: CicadaTheme.scaled(14)).padding(.top, isVideo ? 0 : CicadaTheme.scaled(2))
                if isVideo {
                    // G162 (§9 2026-09-30) — a 64 × 36 frame with its length at full width, 48 × 27 beside a detail.
                    VideoThumb(thumbnail: item.thumbnail, durationS: item.durationS,
                               width: style == .wide ? 64 : 48, height: style == .wide ? 36 : 27,
                               showsLength: style == .wide)
                }
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
                        if !(isVideo && style == .wide), let age = FeedDates.age(item, now: now) {
                            Text(age)
                                .font(CicadaTheme.metaFont)
                                .monospacedDigit()
                                .foregroundStyle(metaColor)
                                .help(FeedDates.day(item, withYear: true) ?? "")
                        }
                    }
                    Text(isVideo && style == .triage ? VideoWords.triageLine(item, state: videoState) : FeedRowText.detail(item))
                        .font(CicadaTheme.metaFont)
                        .foregroundStyle(metaColor)
                        .lineLimit(1)
                }
                if isVideo && style == .wide {
                    // The state word and the age, one tabular group at the trailing edge ("Transcript · 3h").
                    Text(VideoWords.trailing(state: videoState, age: FeedDates.age(item, now: now)))
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(metaColor)
                        .lineLimit(1)
                        .fixedSize()
                        .help(FeedDates.day(item, withYear: true) ?? "")
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
