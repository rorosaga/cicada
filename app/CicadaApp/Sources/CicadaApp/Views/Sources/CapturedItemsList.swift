import SwiftUI

/// G161 (the owner, 2026-09-28: "out of the 229 notes for example, see which ones it detected … a small list that
/// opens below each thing") — what a source brought in, by name, under its row: a "What came in" disclosure,
/// collapsed until the viewer opens it and remembered per channel (DR-39); open, one-line rows — the item's own title
/// and its compact age, the date in `.help` (DR-34, DR-58) — the first twenty, then "Show more" loads the next twenty
/// in place. One component wherever a source row is drawn: onboarding's Import page (`interactive: false` — a Reader
/// opened there would sit hidden under the onboarding layer), Settings → Integrations, and the Sources detail column
/// (`style: .open`, where the list is the page's content rather than a detail under a row).
///
/// It reads `ChannelItemsCache` (never a Store domain) and keeps the last list while a newer one is read (never
/// blank). Every environment value is optional, so a host without one draws nothing rather than trapping.
struct CapturedItemsList: View {
    enum Style { case disclosure, open }

    let channel: String
    var interactive: Bool = true
    var style: Style = .disclosure

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(Store.self) private var store: Store?
    @AppStorage private var remembered: Bool
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(channel: String, interactive: Bool = true, style: Style = .disclosure) {
        self.channel = channel
        self.interactive = interactive
        self.style = style
        _remembered = AppStorage(wrappedValue: false, CapturedItems.openKey(channel))
    }

    private var isOpen: Bool { style == .open || remembered }

    /// Re-read when the list opens and whenever the channels move (`/sources/channels` ETags over the same
    /// components this list does, so a sync that brought something in lands here too; a 304 moves nothing).
    private var refreshKey: String {
        "\(channel)|\(isOpen)|\(store?.channels.loadedAt?.timeIntervalSinceReferenceDate ?? 0)"
    }

    private var noun: (one: String, many: String) {
        CapturedItems.noun(channel: channel,
                           countNoun: store?.channels.value?.first { $0.id == channel }?.countNoun)
    }

    var body: some View {
        if let cache {
            VStack(alignment: .leading, spacing: 0) {
                switch style {
                case .disclosure: disclosure
                case .open: SectionLabel(Copy.capturedTitle).frame(minHeight: CicadaTheme.scaled(28), alignment: .leading)
                }
                if isOpen { content(cache) }
            }
            .task(id: refreshKey) {
                guard isOpen else { return }
                await cache.refresh(channel)
            }
        }
    }

    // MARK: The disclosure

    private var disclosure: some View {
        Button { remembered.toggle() } label: {
            HStack(spacing: CicadaTheme.scaled(6)) {
                Image(systemName: remembered ? "chevron.down" : "chevron.right")
                    .font(CicadaTheme.icon(.inline))
                    .frame(width: CicadaTheme.scaled(12))
                    .iconHover(hovering: hovering)
                Text(Copy.capturedTitle)
                Spacer(minLength: 0)
            }
            .font(CicadaTheme.metaMediumFont)
            .foregroundStyle(hovering ? CicadaTheme.textPrimary : CicadaTheme.textSecondary)
            .frame(height: CicadaTheme.scaled(28))
            .contentShape(Rectangle())
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(Copy.capturedHelp)
        .accessibilityLabel(Copy.capturedTitle)
        .accessibilityValue(remembered ? Copy.Lists.expanded : Copy.Lists.collapsed)
    }

    // MARK: The rows

    @ViewBuilder
    private func content(_ cache: ChannelItemsCache) -> some View {
        if let list = cache.list(channel) {
            if list.items.isEmpty {
                line(channel == "contacts-local" ? Copy.capturedNoPeople : Copy.capturedNone)
            } else {
                let today = ISODay.today()
                VStack(spacing: 0) {
                    ForEach(list.items, id: \.self) { item in
                        CapturedItemRow(item: item, today: today,
                                        route: CapturedItemRoute.of(item, interactive: interactive), open: go)
                    }
                }
                if list.hasMore { showMore(list, loading: cache.isLoadingMore(channel), cache: cache) }
            }
        } else {
            switch cache.phase(channel) {
            case .failed(let why): line(why)
            case .gone: line(Copy.capturedNone)
            case .idle, .loading, .loaded:
                HStack(spacing: CicadaTheme.spacingXS) {
                    ProgressView().controlSize(.small)
                    line(Copy.capturedLoading)
                }
            }
        }
    }

    private func line(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(1)
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
            .help(text)
    }

    private func showMore(_ list: ChannelItemsList, loading: Bool, cache: ChannelItemsCache) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextButton(title: Copy.capturedShowMore) { Task { await cache.loadMore(channel) } }
                .disabled(loading)
            if loading { ProgressView().controlSize(.small) }
            Spacer(minLength: CicadaTheme.spacingSM)
            Text(Copy.capturedShown(list.items.count, of: list.total, noun: noun))
                .font(CicadaTheme.metaFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
        .padding(.horizontal, CicadaTheme.scaled(10))
    }

    /// Every hand-off closes Settings first (the Feed and Clusters routes do so themselves), so the Reader or the
    /// card is never left under the panel.
    private func go(_ route: CapturedItemRoute) {
        switch route {
        case .reader(let episode, let title):
            router?.closeSettings()
            provenance?.open(ReaderTarget(episode: episode, knownTitle: title))
        case .feed(let id):
            router?.routeToFeedItem(id)
        case .entity(let id):
            router?.routeToClustersEntity(id)
        }
    }
}

/// One captured item: its title and compact age on one 36 pt line (DR-34), the full date in `.help` (DR-58). A row
/// that opens something is a button with the row hover (DR-48: a fill, never a lift); a preview row is plain text.
private struct CapturedItemRow: View {
    let item: ChannelItem
    let today: ISODay
    let route: CapturedItemRoute?
    let open: (CapturedItemRoute) -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let age = CapturedItems.age(item, today: today)
        if let route {
            Button { open(route) } label: { label(age) }
                .buttonStyle(.cicadaPlain)
                .onHover { hovering = $0 }
                .help(Copy.capturedOpenHelp(item.kind))
                .accessibilityLabel(Copy.capturedRowLabel(item.title, age: age?.help))
                .accessibilityHint(Copy.capturedOpenHelp(item.kind))
        } else {
            label(age)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(Copy.capturedRowLabel(item.title, age: age?.help))
        }
    }

    private func label(_ age: (text: String, help: String)?) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(item.title)
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer(minLength: CicadaTheme.spacingSM)
            if let age {
                Text(age.text)
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .help(age.help)
            }
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
        .padding(.horizontal, CicadaTheme.scaled(10))
        .background(hovering && route != nil ? CicadaTheme.bgHover : Color.clear,
                    in: CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .contentShape(Rectangle())
    }
}
