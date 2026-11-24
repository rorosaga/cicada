import AppKit
import SwiftUI

// G245 (ruling 78 (c), owner 2026-11-24: "who i have connected with and in chronological order which to me is super
// important") — LinkedIn's Connections: the people the person connected with, newest first, a month at a time
// ("November 2026 · 14"). Each row is a face (the person's page's picture where the connection is a page in memory,
// else one plain monogram), the name, the headline, the day it was made ("around" when LinkedIn only said a week or a
// month), the LinkedIn mark that opens the profile, and — when it matches a page — a chip that opens that page.
//
// Names come only from the local route and live in MEMORY ONLY: no disk cache, no Store domain, never a bank
// (`LinkedInConnectionsModel`). The page's own find narrows by name or headline (the route does it); empty, off and
// failed states say so in a line, never a prompt.
//
// Applies DR-37 (a group is one block), DR-38 (a word said once: the month heads the group, the row says the day),
// DR-47 (the section label), DR-52 (a real mark or none: the site's bundled mark, a plain monogram for a face), DR-59
// (one line, the whole on hover), DR-81 (nothing drawn at zero: no find, no heading), the 2026-11-23 soft-card line.

/// The kept connections, read page by page from the local route and held in memory alone.
@Observable
@MainActor
final class LinkedInConnectionsModel {
    enum Phase: Equatable { case idle, loading, loaded, failed(String) }

    typealias Fetch = (_ query: String, _ offset: Int, _ limit: Int) async throws -> LinkedInConnectionsPage

    static let pageSize = 50

    private(set) var rows: [LinkedInConnection] = []
    private(set) var total = 0
    private(set) var kept = 0
    private(set) var next: Int?
    private(set) var phase: Phase = .idle
    private(set) var loadingMore = false
    /// The words the rows in hand were read for.
    private(set) var loadedQuery = ""

    init() {}

    /// Reads the first page for `query`. Rows already in hand stay on screen while it is read (never blank), except when
    /// the page says nothing is kept any more (`kept` 0, after "Forget kept connections"): a forgotten name is gone from
    /// the screen at once, before the read and whether or not it succeeds.
    func load(query: String, kept keptCount: Int? = nil, using fetch: Fetch) async {
        let words = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if keptCount == 0, !rows.isEmpty { empty() }
        if rows.isEmpty { phase = .loading }
        do {
            let page = try await fetch(words, 0, Self.pageSize)
            guard !Task.isCancelled else { return }
            rows = page.rows
            total = page.total
            kept = page.kept
            next = page.next
            loadedQuery = words
            phase = .loaded
        } catch {
            guard !Task.isCancelled, !(error is CancellationError), (error as? URLError)?.code != .cancelled else { return }
            // Nothing kept is an empty list, not a failed read: the words say so, never an error about names that are gone.
            if rows.isEmpty { phase = keptCount == 0 ? .loaded : .failed(Copy.Streams.connectionsFailed) }
        }
    }

    private func empty() {
        rows = []; total = 0; kept = 0; next = nil; phase = .loaded
    }

    /// The next page of the same search, appended.
    func more(using fetch: Fetch) async {
        guard let offset = next, !loadingMore else { return }
        loadingMore = true
        defer { loadingMore = false }
        do {
            let page = try await fetch(loadedQuery, offset, Self.pageSize)
            guard !Task.isCancelled else { return }
            let known = Set(rows.map(\.id))
            rows += page.rows.filter { !known.contains($0.id) }
            total = page.total
            next = page.next
        } catch {
            // A page that did not come is asked again by the same button.
        }
    }

    var hasMore: Bool { next != nil }
}

private struct LinkedInConnectionsFetchKey: EnvironmentKey {
    static let defaultValue: LinkedInConnectionsModel.Fetch = { try await APIClient.shared.fetchLinkedInConnections(query: $0, offset: $1, limit: $2) }
}

extension EnvironmentValues {
    /// Where the Connections tab reads from: the local route (a render or a test names another).
    var linkedInConnectionsFetch: LinkedInConnectionsModel.Fetch {
        get { self[LinkedInConnectionsFetchKey.self] }
        set { self[LinkedInConnectionsFetchKey.self] = newValue }
    }
}

/// The Connections tab's content: the model's read, the find, the months. Owns the find and the model; the page tells it
/// whether the stream is on and how many connections are kept (the key it reads again by).
struct LinkedInConnectionsSection: View {
    let streamOn: Bool
    let kept: Int

    @State private var model = LinkedInConnectionsModel()
    @State private var query = ""
    @Environment(\.linkedInConnectionsFetch) private var fetch
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?

    var body: some View {
        LinkedInConnectionsContent(
            rows: model.rows, total: model.total, hasMore: model.hasMore, loadingMore: model.loadingMore,
            phase: model.phase, streamOn: streamOn, query: $query, today: ISODay.today(),
            onOpenPage: { SourcePageRouting.go(.entity($0), router: router, provenance: provenance) },
            onOpenProfile: { NSWorkspace.shared.open($0) },
            onMore: { Task { await model.more(using: fetch) } })
            .task(id: "\(kept)|\(query)") {
                if !query.trimmingCharacters(in: .whitespaces).isEmpty {
                    try? await Task.sleep(for: SourceSearch.debounce)
                    guard !Task.isCancelled else { return }
                }
                await model.load(query: query, kept: kept, using: fetch)
            }
    }
}

/// Value-driven (`SourcePageRenderTests` draws it from fixtures).
struct LinkedInConnectionsContent: View {
    let rows: [LinkedInConnection]
    let total: Int
    var hasMore = false
    var loadingMore = false
    let phase: LinkedInConnectionsModel.Phase
    let streamOn: Bool
    @Binding var query: String
    let today: ISODay
    let onOpenPage: (String) -> Void
    let onOpenProfile: (URL) -> Void
    let onMore: () -> Void

    private var searching: Bool { !SourceSearch.normalized(query).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            if rows.isEmpty && !searching {
                switch phase {
                case .idle, .loading: ListSkeleton(message: Copy.Streams.connectionsLoading, rows: 3)
                case .failed(let why): note(why)
                case .loaded:
                    note(LinkedInConnectionsText.empty(streamOn: streamOn, searching: false) == .off
                         ? Copy.Streams.connectionsOff : Copy.Streams.connectionsWaiting)
                }
            } else {
                SourceSearchHeader(query: $query, prompt: Copy.Streams.connectionsSearch(searching ? nil : total))
                if rows.isEmpty {
                    note(Copy.SourcePage.noMatch(query))
                } else {
                    ForEach(LinkedInConnectionsText.months(rows, complete: !hasMore)) { month in
                        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                            SectionLabel(month.heading)
                            VStack(spacing: 0) {
                                ForEach(Array(month.rows.enumerated()), id: \.element.id) { index, row in
                                    if index > 0 { divider }
                                    LinkedInConnectionRow(row: row, today: today, onOpenPage: onOpenPage,
                                                          onOpenProfile: onOpenProfile)
                                }
                            }
                            .padding(.vertical, CicadaTheme.spacingXS)
                            .softCard(ground: .page, shape: .block, inset: .none, fillsWidth: true)
                        }
                    }
                    if hasMore { moreRow }
                }
            }
        }
    }

    private var moreRow: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextButton(title: loadingMore ? Copy.capturedLoadingMore : Copy.capturedShowMore, inline: true, flushLeading: true,
                       action: onMore)
                .disabled(loadingMore)
            Spacer(minLength: CicadaTheme.spacingSM)
            Text(Copy.capturedShown(rows.count, of: total, noun: ("connection", "connections")))
                .font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
        }
    }

    private var divider: some View {
        Rectangle()
            .fill(CicadaTheme.ring(.resting))
            .frame(height: 1)
            .padding(.leading, CicadaTheme.scaled(62))
            .padding(.trailing, CicadaTheme.scaled(14))
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(2)
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
    }
}

/// One connection: face, name and headline (one button: the profile), the day, the page's chip when there is one.
struct LinkedInConnectionRow: View {
    let row: LinkedInConnection
    let today: ISODay
    let onOpenPage: (String) -> Void
    let onOpenProfile: (URL) -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let face: CGFloat = 32

    var body: some View {
        let day = LinkedInConnectionsText.day(row, today: today)
        let profile = LinkedInConnectionsText.profile(row)
        HStack(spacing: CicadaTheme.spacingMD) {
            Button { if let profile { onOpenProfile(profile) } } label: {
                HStack(spacing: CicadaTheme.spacingMD) {
                    faceView
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                        Text(row.name)
                            .font(CicadaTheme.rowFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                            .truncationMode(.tail)
                        if !row.headline.isEmpty {
                            Text(row.headline)
                                .font(CicadaTheme.metaFont)
                                .foregroundStyle(CicadaTheme.textTertiary)
                                .lineLimit(1)
                                .truncationMode(.tail)
                        }
                    }
                    Spacer(minLength: CicadaTheme.spacingSM)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.cicadaPlain)
            .disabled(profile == nil)
            .help(profile != nil ? Copy.Streams.connectionsOpenProfile(row.name) : row.name)
            .accessibilityLabel([row.name, row.headline, day?.help].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", "))
            // The page's chip first, then the day and the mark: those two stand in one column down the whole list.
            if let page = row.page {
                ConnectionPageChip(help: Copy.Streams.connectionsMatchHelp) { onOpenPage(page) }
            }
            Text(day?.text ?? "")
                .font(CicadaTheme.metaFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .frame(width: CicadaTheme.scaled(104), alignment: .trailing)
                .help(day?.help ?? "")
            ConnectionMarkChip(mark: "linkedin", help: Copy.Streams.connectionsOpenProfile(row.name)) {
                if let profile { onOpenProfile(profile) }
            }
            .opacity(profile == nil ? 0 : 1)
            .disabled(profile == nil)
        }
        .padding(.horizontal, CicadaTheme.scaled(14))
        .padding(.vertical, CicadaTheme.scaled(10))
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.twoLine))
        .rowHoverFill(hovering: hovering)
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .onHover { hovering = $0 }
    }

    /// The page's own picture when the connection is a page in memory (the one precedence), else one plain monogram.
    @ViewBuilder
    private var faceView: some View {
        if let page = row.page {
            EntityPicture(id: page, name: row.name, type: .person, size: Self.face)
                .frame(width: CicadaTheme.scaled(Self.face), height: CicadaTheme.scaled(Self.face))
        } else {
            let side = CicadaTheme.scaled(Self.face)
            EntityPictureFallback(type: .person, name: row.name, units: Self.face, frame: CGSize(width: side, height: side))
                .frame(width: side, height: side)
                .clipShape(Circle())
        }
    }
}

/// A link to a site, as the site's bundled real mark alone (the profile on LinkedIn): bare until the pointer is on it.
struct ConnectionMarkChip: View {
    let mark: String
    let help: String
    let action: () -> Void

    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            LogoImage(name: mark, size: CicadaTheme.scaled(16))
                .frame(width: CicadaTheme.scaled(28), height: CicadaTheme.scaled(28))
                .rowHoverFill(hovering: hovering)
                .contentShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(help)
        .accessibilityLabel(help)
    }
}

/// The soft chip that opens the person's page in memory.
struct ConnectionPageChip: View {
    let help: String
    let action: () -> Void

    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Text(Copy.Streams.connectionsPageChip)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .lineLimit(1)
                .padding(.horizontal, CicadaTheme.scaled(8))
                .frame(height: CicadaTheme.scaled(24))
                .background(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).fill(CicadaTheme.bgFocus))
                .rowHoverFill(hovering: hovering)
                .overlay(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall).strokeBorder(CicadaTheme.ring(.resting), lineWidth: 1))
                .contentShape(CicadaTheme.shape(CicadaTheme.cornerRadiusSmall))
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(help)
        .accessibilityLabel(help)
    }
}
