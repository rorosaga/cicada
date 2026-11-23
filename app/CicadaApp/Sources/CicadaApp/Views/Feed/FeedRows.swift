import SwiftUI

/// Sleep › Saved and Videos (the Feed's list until it folded into Sleep, 2026-10-16) — the list column beside an open
/// item (STATE 1, §5.3): the find row above its own scroll, then the rows. With nothing open the same rows
/// (`FeedRowsContent`) scroll with the room on the Sleep page itself, under its sticky tab row, the export waits
/// (`ExportWaitStrip`) at their head. The Connected strip retired with the Feed: Sources holds every connected source
/// (its cards' Sync now).
struct FeedListColumn: View {
    let style: ColumnPlan.ListStyle
    @Binding var findOpen: Bool
    let searching: Bool
    let landingToken: Int
    /// The rows this tab shows (Saved's view, or the saved videos), already filtered by find.
    let items: [MediaFeedItem]
    let open: (MediaFeedItem) -> Void
    let move: (Int) -> Void
    let focusDetail: () -> Void
    let escape: () -> Void

    @Environment(FeedViewModel.self) private var viewModel

    private var searchText: Binding<String> {
        Binding(get: { viewModel.searchText }, set: { viewModel.searchText = $0 })
    }

    var body: some View {
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
                        FeedRowsContent(items: items, style: style, searching: searching, now: Date.now,
                                        openId: viewModel.columns.openId, open: open)
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
}

/// The saved rows themselves, in the state the list is in (§5.5): an error first (a failed fetch leaves nothing and
/// would read as "nothing saved"), loading second, the one honest empty state, a find with no match, then the rows.
/// No scroll view of its own: the Sleep page's scroll holds it with nothing open, `FeedListColumn`'s beside an item.
struct FeedRowsContent: View {
    let items: [MediaFeedItem]
    let style: ColumnPlan.ListStyle
    let searching: Bool
    let now: Date
    let openId: String?
    let open: (MediaFeedItem) -> Void

    @Environment(FeedViewModel.self) private var viewModel
    @Environment(IntakeRouter.self) private var intake

    var body: some View {
        switch FeedPageState.of(isLoading: viewModel.isLoading, error: viewModel.errorMessage,
                                hasItems: !viewModel.items.isEmpty, visibleEmpty: items.isEmpty,
                                searching: searching) {
        case .loading:
            ListSkeleton(message: Copy.Lists.readingFeed)
        case .failed(let message):
            ListErrorCard(title: Copy.Lists.feedLoadFailed, message: message) { Task { await viewModel.load() } }
        case .empty:
            // G117 — one honest empty state, one action; an export can land right here (R-IA27). The room above is
            // the other door (DESIGN §3.5).
            EmptyStateView(title: Copy.Lists.nothingSaved, message: Copy.SleepTabs.savedEmpty,
                           actionLabel: "Open Sources", settingsSection: .page(.sources),
                           onDropFiles: { intake.accept(urls: $0, from: .emptyState(.sleep)) })
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
            ForEach(items) { item in
                FeedListRow(item: item, style: style, showsRelevance: showsRelevance,
                            selected: item.id == openId, now: now) { open(item) }
                    .id(item.id)
            }
        }
    }
}

/// One saved item, as the app's soft card (owner 2026-11-23, DESIGN_RULES §9: "sure" — the lists wear the Superwhisper
/// look): its title (two lines at most) and under it one quiet line, `[site mark] Article · site · Saved 21 Nov`, with the
/// relevance and the age at its trailing edge. The mark is the item's own site (DR-52) or the origin's real mark — never
/// a kind glyph standing in for one (DR-48: a real mark or nothing; the kind is the line's first word). A video keeps its
/// frame at the card's leading edge. No chevron: the whole card is the button, and the open item is `bgSelected`. Only the
/// narrowest column (titles, beside the open item and the Reader) stays a dense one-line row. Relevance only when the
/// scores differ.
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
    private var isCard: Bool { style == .wide || style == .triage }

    var body: some View {
        if isCard {
            Button(action: open) { card.softCardRow(selected: selected) }
                .buttonStyle(.cicadaPlain)
                // The list's gutter was set for rows that pad themselves 10 pt: the card's edge lines up with the tab
                // row's and the page's text edge (the narrow column's own inset already is the card's).
                .padding(.horizontal, style == .wide ? CicadaTheme.scaled(10) : 0)
                .accessibilityLabel(Copy.Lists.feedRow(title: title, open: selected))
                .accessibilityAddTraits(selected ? .isSelected : [])
                // The card's gap (12) less the 2 pt the lazy stack already puts between its children.
                .padding(.bottom, CicadaTheme.cardGap - CicadaTheme.scaled(RowMetrics.twoLineGap))
        } else {
            Button(action: open) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    mark.frame(width: CicadaTheme.scaled(16))
                    titleText(lines: 1)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                .contentShape(Rectangle())
                .help(title)
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel(Copy.Lists.feedRow(title: title, open: selected))
            .accessibilityAddTraits(selected ? .isSelected : [])
            .listRowSurface(height: ListRowSurface.height(style, twoLineAtRest: true), selected: selected)
        }
    }

    /// Owner 2026-10-20 — the item's own site (`SavedLinkMark`: its icon, a family's bundled mark, else the site's
    /// monogram); where it was saved from is the detail's "Saved from" line, never this mark. A row the backend named
    /// no site for (an older backend) keeps the origin's mark. The dense row alone falls back to the kind's glyph (it has
    /// no words line to name the kind); a card draws a real mark or nothing.
    @ViewBuilder
    private var mark: some View {
        if let site = SavedLinkMarkModel.mark(item) {
            SavedLinkMark(mark: site, size: .inline)
        } else if let origin = FeedSourceLine.markOrigin(item) {
            OriginMark(origin: origin, size: CicadaTheme.scaled(16))
        } else if !isCard {
            Image(systemName: FeedKind.of(item).glyph)
                .font(CicadaTheme.icon(.inline))
                .foregroundStyle(CicadaTheme.textTertiary)
                .accessibilityHidden(true)
        }
    }

    private func titleText(lines: Int) -> some View {
        Text(title)
            .font(isCard ? CicadaTheme.detailBodyFont : CicadaTheme.rowFont)
            .foregroundStyle(CicadaTheme.textPrimary)
            .lineLimit(lines)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var card: some View {
        HStack(alignment: .center, spacing: CicadaTheme.scaled(12)) {
            if isVideo {
                // G162 (§9 2026-09-30) — a 64 × 36 frame with its length at full width, 48 × 27 beside a detail.
                VideoThumb(preview: item.preview, durationS: item.durationS,
                           width: style == .wide ? 64 : 48, height: style == .wide ? 36 : 27,
                           showsLength: style == .wide)
            }
            VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                titleText(lines: 2)
                HStack(spacing: CicadaTheme.scaled(6)) {
                    mark
                    Text(isVideo && style == .triage ? VideoWords.triageLine(item, state: videoState) : FeedRowText.detail(item))
                        .lineLimit(1)
                    Spacer(minLength: CicadaTheme.spacingSM)
                    if style == .wide && showsRelevance {
                        Text(Copy.Lists.relevanceShort(UsageFormat.percent(item.relevance * 100)))
                            .monospacedDigit()
                            .help(Copy.Lists.relevanceHelp)
                    }
                    if isVideo && style == .wide {
                        // The state word and the age, one tabular group at the trailing edge ("Transcript · 3h").
                        Text(VideoWords.trailing(state: videoState, age: FeedDates.age(item, now: now)))
                            .monospacedDigit()
                            .lineLimit(1)
                            .fixedSize()
                            .help(FeedDates.day(item, withYear: true) ?? "")
                    } else if let age = FeedDates.age(item, now: now) {
                        Text(age)
                            .monospacedDigit()
                            .help(FeedDates.day(item, withYear: true) ?? "")
                    }
                }
                .font(CicadaTheme.metaFont)
                .foregroundStyle(metaColor)
            }
        }
        .contentShape(Rectangle())
    }
}
