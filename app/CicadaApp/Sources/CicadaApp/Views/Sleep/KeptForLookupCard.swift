import SwiftUI

/// Owner 2026-11-23 — "it would be nice to see what was kept ... in a nice orderly manner". The Waiting list's last
/// card. Ruling 80 (owner 2026-11-24: saving is already a reason) changed what it holds, never how it looks: the older
/// saves Sleep has not read yet — it reads about `perNight` of them a night, newest first, and one first when the person
/// talks about it. Closed, it is the one line it was: the tray tile wearing the count. Open, it is ordered the way the
/// list above it is: a row per source (its real mark, its name, how many), most first; a source opens to its items as the
/// same episode cards, newest first, thirty at a time. Nothing is fetched until it is opened.
///
/// DR-9 / DR-12 (the source card's chrome), DR-38 (the count is said once, on the badge), DR-44 / DR-52 (real marks),
/// DR-60 (only a pointer's click eases). The cards wear no new/updated marker and are never faded: a save here neither
/// waits for tonight nor was read.
struct KeptForLookupCard: View {
    let kept: Int
    /// How many Sleep reads a night, from the backend (`keptPerNight`); nil from an older one.
    var perNight: Int? = nil
    /// Tests and renders hand the loader in; the live card reads the backend.
    var load: (String?, Int) async throws -> SleepKept = { origin, offset in
        try await APIClient.shared.fetchSleepKept(origin: origin, offset: offset, limit: KeptForLookupModel.page)
    }
    /// Renders seed it open; the live card starts closed.
    var initiallyOpen = false
    var initiallyOpenSources: Set<String> = []

    @State private var model = KeptForLookupModel()
    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            head
            if model.open {
                opened
                    .padding(.horizontal, CicadaTheme.spacingSM)
                    .padding(.bottom, CicadaTheme.spacingSM)
                    .transition(.opacity)
            }
        }
        .sourceCardChrome(lit: hovering)
        .onAppear {
            guard initiallyOpen, !model.open else { return }
            model.open = true
            model.openSources = initiallyOpenSources
        }
        // Opened, or the count moved while open: read the breakdown again, and every open source's first page.
        .task(id: KeptForLookupModel.Trigger(open: model.open, kept: kept)) {
            guard model.open else { return }
            await model.refresh(load: load)
        }
    }

    private var head: some View {
        Button {
            withAnimation(SleepMotion.disclosure(reduceMotion: reduceMotion)) { model.open.toggle() }
        } label: {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: "tray")
                    .font(CicadaTheme.icon(.inline))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: StudyListCard.markSize, height: StudyListCard.markSize)
                    .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgBadge))
                    .overlay(alignment: .topTrailing) { StudyListCard.badge(kept) }
                    .padding(.trailing, CicadaTheme.spacingXS)
                Text(Copy.SleepV5.savesNotReadRow)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingMD)
                // The badge stops at "99+": past it, the whole number is said here.
                if kept > 99 {
                    Text(UsageFormat.count(kept))
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .padding(.trailing, CicadaTheme.spacingSM)
                }
            }
            .padding(.horizontal, StudyListCard.cardInset)
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine + 16))
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(Copy.savesNotReadYet(kept, perNight: perNight) ?? "")
        .accessibilityLabel(Copy.savesNotReadYet(kept, perNight: perNight) ?? Copy.SleepV5.savesNotReadRow)
        .accessibilityValue(model.open ? Copy.Lists.expanded : Copy.Lists.collapsed)
    }

    @ViewBuilder
    private var opened: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(2)) {
            Text(Copy.Kept.explanation(perNight: perNight))
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, CicadaTheme.spacingSM)
                .padding(.bottom, CicadaTheme.spacingSM)
            if let sources = model.sources {
                ForEach(sources) { source in
                    sourceRow(source)
                    if model.openSources.contains(source.origin) {
                        items(source)
                            .padding(.vertical, CicadaTheme.spacingXS)
                            .transition(.opacity)
                    }
                }
            } else {
                Text(model.failed ? Copy.Kept.failed : Copy.RunCard.loading)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingSM)
                    .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
            }
        }
    }

    private func sourceRow(_ source: SleepKept.Source) -> some View {
        KeptSourceRow(source: source, isOpen: model.openSources.contains(source.origin)) {
            withAnimation(SleepMotion.disclosure(reduceMotion: reduceMotion)) { model.toggle(source.origin) }
            Task { await model.loadFirstPage(source.origin, load: load) }
        }
    }

    @ViewBuilder
    private func items(_ source: SleepKept.Source) -> some View {
        let shown = model.items[source.origin] ?? []
        LazyVStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            ForEach(shown) { EpisodeCard(item: $0, showsState: false) }
            if shown.isEmpty {
                Text(model.failedSources.contains(source.origin) ? Copy.Kept.failed : Copy.RunCard.loading)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .padding(.horizontal, CicadaTheme.spacingSM)
            } else if shown.count < source.count {
                TextButton(title: Copy.Kept.showMore(shown: shown.count, of: source.count)) {
                    Task { await model.loadMore(source.origin, load: load) }
                }
                .disabled(model.loading.contains(source.origin))
                .padding(.horizontal, CicadaTheme.spacingSM)
            }
        }
    }
}

/// One source inside the kept card: its real mark (DR-52), its name, how many it keeps. A click opens its items.
private struct KeptSourceRow: View {
    let source: SleepKept.Source
    let isOpen: Bool
    let toggle: () -> Void
    @State private var hovering = false

    var body: some View {
        let name = OriginIconography.label(for: source.origin)
        Button(action: toggle) {
            HStack(spacing: CicadaTheme.spacingSM) {
                StudyListCard.mark(source.origin, size: CicadaTheme.scaled(20))
                Text(name)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: CicadaTheme.spacingMD)
                Text(UsageFormat.count(source.count))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            .padding(.horizontal, CicadaTheme.spacingSM)
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .rowHoverFill(hovering: hovering || isOpen)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .accessibilityLabel(Copy.Kept.sourceLabel(name, count: source.count))
        .accessibilityValue(isOpen ? Copy.Lists.expanded : Copy.Lists.collapsed)
    }
}

/// The kept card's state, with no view in it (`KeptForLookupTests`): which sources are open, each one's pages so far.
@MainActor
@Observable
final class KeptForLookupModel {
    static let page = 30

    struct Trigger: Hashable {
        let open: Bool
        let kept: Int
    }

    var open = false
    var openSources: Set<String> = []
    private(set) var sources: [SleepKept.Source]?
    private(set) var items: [String: [EpisodeQueueItem]] = [:]
    private(set) var failed = false
    private(set) var failedSources: Set<String> = []
    private(set) var loading: Set<String> = []

    typealias Loader = (String?, Int) async throws -> SleepKept

    func toggle(_ origin: String) { openSources.formSymmetricDifference([origin]) }

    /// The breakdown, then the first page of every source that is open (one that left the breakdown closes).
    func refresh(load: Loader) async {
        do {
            let got = try await load(nil, 0)
            sources = got.sources
            failed = false
            openSources.formIntersection(Set(got.sources.map(\.origin)))
        } catch {
            failed = sources == nil
            return
        }
        for origin in openSources.sorted() { await fetch(origin, offset: 0, load: load) }
    }

    func loadFirstPage(_ origin: String, load: Loader) async {
        guard openSources.contains(origin), items[origin] == nil else { return }
        await fetch(origin, offset: 0, load: load)
    }

    func loadMore(_ origin: String, load: Loader) async {
        await fetch(origin, offset: items[origin]?.count ?? 0, load: load)
    }

    private func fetch(_ origin: String, offset: Int, load: Loader) async {
        guard !loading.contains(origin) else { return }
        loading.insert(origin)
        defer { loading.remove(origin) }
        do {
            let got = try await load(origin, offset)
            failedSources.remove(origin)
            if offset == 0 {
                items[origin] = got.items
            } else {
                // A page that overlaps what is shown (a save arrived meanwhile) never repeats a card.
                let have = Set((items[origin] ?? []).map(\.id))
                items[origin, default: []].append(contentsOf: got.items.filter { !have.contains($0.id) })
            }
        } catch {
            if items[origin] == nil { failedSources.insert(origin) }
        }
    }
}
