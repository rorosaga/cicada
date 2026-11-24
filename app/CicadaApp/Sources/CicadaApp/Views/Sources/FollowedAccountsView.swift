import AppKit
import SwiftUI

// G245 (ruling 79 (b), owner 2026-11-24: "Should the accounts you follow be read?" "2. yes") — X's Following: the accounts
// the person follows, newest first, as a plain list with a find and a count. A row is a face (the matched page's picture
// when the account is a page in memory, else one plain monogram), the name, the handle, a chip when it is a page (a
// quieter "Maybe their page" when only the name says so), the day it was first seen and X's bundled mark, which opens the
// profile. The list is not a page of anyone: nothing here makes one.
//
// Names come only from the local route and live in MEMORY ONLY: no disk cache, no Store domain, never a bank
// (`FollowedAccountsModel`). Empty, off and failed states say so in a line, never a prompt. Forget lives in the page's
// footer, beside the other kept directories'.
//
// Applies DR-37 (a group is one block), DR-38 (a word said once), DR-47 (the section label), DR-52 (a real mark or none),
// DR-59 (one line, the whole on hover), DR-81 (nothing drawn at zero: no find, no heading), the 2026-11-23 soft-card line.

/// The followed accounts, read page by page from the local route and held in memory alone.
@Observable
@MainActor
final class FollowedAccountsModel {
    enum Phase: Equatable { case idle, loading, loaded, failed(String) }

    typealias Fetch = (_ query: String, _ offset: Int, _ limit: Int) async throws -> FollowedAccountsPage

    static let pageSize = 50

    private(set) var rows: [FollowedAccount] = []
    private(set) var total = 0
    private(set) var kept = 0
    private(set) var next: Int?
    private(set) var phase: Phase = .idle
    private(set) var loadingMore = false
    /// The words the rows in hand were read for.
    private(set) var loadedQuery = ""

    init() {}

    /// Reads the first page for `query`. Rows in hand stay on screen while it is read (never blank), except when the page
    /// says nothing is kept any more (`keptCount` 0, after "Forget kept accounts"): a forgotten name is gone at once.
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
            if rows.isEmpty { phase = keptCount == 0 ? .loaded : .failed(Copy.Streams.followingFailed) }
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

private struct FollowedAccountsFetchKey: EnvironmentKey {
    static let defaultValue: FollowedAccountsModel.Fetch = { try await APIClient.shared.fetchFollowedAccounts(query: $0, offset: $1, limit: $2) }
}

extension EnvironmentValues {
    /// Where the Following tab reads from: the local route (a render or a test names another).
    var followedAccountsFetch: FollowedAccountsModel.Fetch {
        get { self[FollowedAccountsFetchKey.self] }
        set { self[FollowedAccountsFetchKey.self] = newValue }
    }
}

/// The Following tab's content: the model's read, the find, the rows. Owns the find and the model; the page tells it whether
/// the stream is on and how many accounts are kept (the key it reads again by).
struct FollowedAccountsSection: View {
    let streamOn: Bool
    let kept: Int

    @State private var model = FollowedAccountsModel()
    @State private var query = ""
    @Environment(\.followedAccountsFetch) private var fetch
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?

    var body: some View {
        FollowedAccountsContent(
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
struct FollowedAccountsContent: View {
    let rows: [FollowedAccount]
    let total: Int
    var hasMore = false
    var loadingMore = false
    let phase: FollowedAccountsModel.Phase
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
                case .idle, .loading: ListSkeleton(message: Copy.Streams.followingLoading, rows: 3)
                case .failed(let why): note(why)
                case .loaded:
                    note(FollowedAccountsText.empty(streamOn: streamOn, searching: false) == .off
                         ? Copy.Streams.followingOff : Copy.Streams.followingWaiting)
                }
            } else {
                SourceSearchHeader(query: $query, prompt: Copy.Streams.followingSearch(searching ? nil : total))
                if rows.isEmpty {
                    note(Copy.SourcePage.noMatch(query))
                } else {
                    VStack(spacing: 0) {
                        ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                            if index > 0 { divider }
                            FollowedAccountRow(row: row, today: today, onOpenPage: onOpenPage, onOpenProfile: onOpenProfile)
                        }
                    }
                    .padding(.vertical, CicadaTheme.spacingXS)
                    .softCard(ground: .page, shape: .block, inset: .none, fillsWidth: true)
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
            Text(Copy.capturedShown(rows.count, of: total, noun: ("account", "accounts")))
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

/// One followed account: face, name and handle (one button: the profile), the page's chip when there is one, the day.
struct FollowedAccountRow: View {
    let row: FollowedAccount
    let today: ISODay
    let onOpenPage: (String) -> Void
    let onOpenProfile: (URL) -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let face: CGFloat = 32

    var body: some View {
        let day = FollowedAccountsText.since(row, today: today)
        let profile = FollowedAccountsText.profile(row)
        HStack(spacing: CicadaTheme.spacingMD) {
            Button { if let profile { onOpenProfile(profile) } } label: {
                HStack(spacing: CicadaTheme.spacingMD) {
                    faceView
                    VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
                        Text(row.title)
                            .font(CicadaTheme.rowFont)
                            .foregroundStyle(CicadaTheme.textPrimary)
                            .lineLimit(1)
                            .truncationMode(.tail)
                        if let handle = FollowedAccountsText.handleLine(row) {
                            Text(handle)
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
            .help(profile != nil ? Copy.Streams.followingOpenProfile(row.title) : row.title)
            .accessibilityLabel([row.title, row.handle.isEmpty ? nil : "@\(row.handle)", day?.help].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: ", "))
            if let page = row.page {
                FollowedPageChip(maybe: row.proposed) { onOpenPage(page) }
            }
            Text(day?.text ?? "")
                .font(CicadaTheme.metaFont)
                .monospacedDigit()
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .frame(width: CicadaTheme.scaled(104), alignment: .trailing)
                .help(day?.help ?? "")
            ConnectionMarkChip(mark: "x", help: Copy.Streams.followingOpenProfile(row.title)) {
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

    /// The page's own picture when the account is a page in memory (the one precedence), else one plain monogram.
    @ViewBuilder
    private var faceView: some View {
        let side = CicadaTheme.scaled(Self.face)
        if let page = row.page, !row.proposed {
            EntityPicture(id: page, name: row.title, type: .person, size: Self.face)
                .frame(width: side, height: side)
        } else {
            EntityPictureFallback(type: .person, name: row.title, units: Self.face, frame: CGSize(width: side, height: side))
                .frame(width: side, height: side)
                .clipShape(Circle())
        }
    }
}

/// The soft chip that opens the page in memory; a name-only match says "Maybe" and is never drawn as the page's face.
struct FollowedPageChip: View {
    let maybe: Bool
    let action: () -> Void

    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Text(maybe ? Copy.Streams.followingMaybePageChip : Copy.Streams.followingPageChip)
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
        .help(maybe ? Copy.Streams.followingMaybeHelp : Copy.Streams.followingMatchHelp)
        .accessibilityLabel(maybe ? Copy.Streams.followingMaybeHelp : Copy.Streams.followingMatchHelp)
    }
}
