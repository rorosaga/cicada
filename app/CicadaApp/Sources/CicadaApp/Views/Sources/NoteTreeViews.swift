import AppKit
import SwiftUI

// G245 (ruling 78, plan 5; owner 2026-11-24: "respect the folder structure, pins, recently modified and all these
// dynamics the app has itself, replicate it in cicada") — Apple Notes and Notion's pages, laid out the way their own app
// lays them:
//
//   • the folders as a real tree — nested, each with its count with everything under it, in the app's own order — the
//     account's name over its folders when there is more than one account;
//   • a folder opens in the content's place with a back head (the app's browse pattern, DR-81: no fold in place);
//   • the notes under Pinned and then Notes' own date groups (Today, Yesterday, Previous 7 Days, Previous 30 Days, then
//     months), each a title, the time, the one-line snippet; ordered by when it was last modified (Notion: last edited);
//   • where pins could not be read, one quiet line says so and offers the setting — never a prompt.
//
// Applies DR-34 (row heights from tokens), DR-37 (a group is one block), DR-47 (the section label), DR-48 (hover is a fill),
// DR-59 (one line, the whole on hover), DR-81 (a level opens in place; nothing drawn at zero), the 2026-11-23 soft-card
// line. Value-driven where it can be (`SourceViewsRenderTests` draws it from fixtures).

/// The accounts' folders as a tree: one soft block per account, a row per folder, indented by how deep it is. The array
/// the collections come in is already the tree walked top-down, in the owning app's order, so the rows are drawn as they
/// stand.
struct NoteFolderTree: View {
    let accounts: [SourceAccount]
    let channel: String
    var showsAccountNames: Bool
    let open: (SourceCollection, SourceAccount) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(accounts) { account in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    if showsAccountNames {
                        SectionLabel(SourceBrowserText.accountName(account), count: account.count)
                    }
                    NoteFolderRows(folders: account.collections, channel: channel) { open($0, account) }
                }
            }
        }
    }
}

/// A run of folder rows in one soft block, each indented by its depth beyond the block's own first level.
struct NoteFolderRows: View {
    let folders: [SourceCollection]
    let channel: String
    let open: (SourceCollection) -> Void

    var body: some View {
        if !folders.isEmpty {
            let base = folders.map { $0.depth ?? 0 }.min() ?? 0
            VStack(spacing: 0) {
                ForEach(Array(folders.enumerated()), id: \.element.id) { index, folder in
                    if index > 0 { divider(depth: (folder.depth ?? 0) - base) }
                    NoteFolderRow(folder: folder, indent: (folder.depth ?? 0) - base, channel: channel) { open(folder) }
                }
            }
            .padding(.vertical, CicadaTheme.spacingXS)
            .softCard(ground: .page, shape: .block, inset: .none, fillsWidth: true)
        }
    }

    private func divider(depth: Int) -> some View {
        Rectangle()
            .fill(CicadaTheme.ring(.resting))
            .frame(height: 1)
            .padding(.leading, CicadaTheme.scaled(14 + 26 + CGFloat(max(0, depth)) * NoteFolderRow.step))
            .padding(.trailing, CicadaTheme.scaled(14))
    }
}

struct NoteFolderRow: View {
    let folder: SourceCollection
    let indent: Int
    let channel: String
    let open: () -> Void

    /// How far one level of nesting moves a row in.
    static let step: CGFloat = 20

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let count = folder.total ?? folder.count
        Button(action: open) {
            HStack(spacing: CicadaTheme.spacingSM) {
                Image(systemName: SourceBrowserLevel.collectionSymbol(channel))
                    .font(CicadaTheme.icon(.list))
                    .foregroundStyle(CicadaTheme.textSecondary)
                    .frame(width: CicadaTheme.scaled(22))
                    .accessibilityHidden(true)
                Text(folder.name)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(Copy.NoteGroups.folderCount(count))
                    .font(CicadaTheme.metaFont)
                    .monospacedDigit()
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .fixedSize()
                Image(systemName: "chevron.right")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
            }
            .padding(.leading, CicadaTheme.scaled(CGFloat(max(0, indent)) * Self.step))
            .padding(.horizontal, CicadaTheme.scaled(14))
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .rowHoverFill(hovering: hovering)
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(Copy.NoteGroups.folderHelp(folder.name, notes: count))
        .accessibilityLabel("\(folder.name), \(count)")
        .accessibilityHint(Copy.SourcePage.groupOpenHelp)
    }
}

/// The one quiet line when pins could not be read, with the button that opens the setting (a preflight, never a prompt).
struct NotesPinsLine: View {
    var openSetting: () -> Void = { NSWorkspace.shared.open(MacPermission.fullDiskAccess.settingsURL()) }

    var body: some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Text(Copy.NoteGroups.pinsUnread)
                .font(CicadaTheme.metaFont)
                .foregroundStyle(CicadaTheme.textTertiary)
                .lineLimit(1)
                .truncationMode(.tail)
                .help(Copy.NoteGroups.pinsHelp)
            TextButton(title: Copy.NoteGroups.openSetting, help: Copy.NoteGroups.pinsHelp, inline: true, action: openSetting)
        }
        .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
    }
}

/// Notes as Notes lays them: Pinned, then the date groups, each group one soft block of rows. Value-driven.
struct NoteGroupsList: View {
    let items: [ChannelItem]
    let today: ISODay
    var channel: String
    let route: (ChannelItem) -> CapturedItemRoute?
    let open: (CapturedItemRoute) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            ForEach(NoteGroups.groups(items, today: today)) { group in
                VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
                    SectionLabel(group.title)
                    VStack(spacing: 0) {
                        ForEach(Array(group.items.enumerated()), id: \.element.id) { index, item in
                            if index > 0 { divider }
                            NoteRow(item: item, today: today, route: route(item), channel: channel, open: open)
                        }
                    }
                    .padding(.vertical, CicadaTheme.spacingXS)
                    .softCard(ground: .page, shape: .block, inset: .none, fillsWidth: true)
                }
            }
        }
    }

    private var divider: some View {
        Rectangle()
            .fill(CicadaTheme.ring(.resting))
            .frame(height: 1)
            .padding(.horizontal, CicadaTheme.scaled(14))
    }
}

/// One note: its title and time, and under them the one-line snippet. A row that opens something is a button with the row
/// hover (DR-48); "Open in Notes" stands over its trailing edge like every list's place control.
struct NoteRow: View {
    let item: ChannelItem
    let today: ISODay
    let route: CapturedItemRoute?
    let channel: String
    let open: (CapturedItemRoute) -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var snippet: String? {
        let words = (item.snippet ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return words.isEmpty ? nil : words
    }

    var body: some View {
        row.modifier(ItemPlaceControl(kind: item.placeKind, title: item.title) {
            try await APIClient.shared.fetchItemPlace(channel: channel, item: item.id)
        })
    }

    @ViewBuilder
    private var row: some View {
        let time = NoteGroups.time(item, today: today)
        if let route {
            Button { open(route) } label: { label(time) }
                .buttonStyle(.cicadaPlain)
                .onHover { hovering = $0 }
                .help(Copy.capturedOpenHelp(item.kind))
                .accessibilityLabel([item.title, snippet, time?.help].compactMap { $0 }.joined(separator: ", "))
                .accessibilityHint(Copy.capturedOpenHelp(item.kind))
        } else {
            label(time)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel([item.title, snippet, time?.help].compactMap { $0 }.joined(separator: ", "))
        }
    }

    private func label(_ time: (text: String, help: String)?) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.scaled(3)) {
            HStack(alignment: .firstTextBaseline, spacing: CicadaTheme.spacingSM) {
                Text(item.title)
                    .font(CicadaTheme.rowFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: CicadaTheme.spacingSM)
                if let time {
                    Text(time.text)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                        .fixedSize()
                        .help(time.help)
                }
            }
            if let snippet {
                Text(snippet)
                    .font(CicadaTheme.metaFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .help(snippet)
            }
        }
        .padding(.trailing, ItemPlaceControl.reserve(item.placeKind))
        .padding(.horizontal, CicadaTheme.scaled(14))
        .padding(.vertical, CicadaTheme.scaled(8))
        .frame(maxWidth: .infinity, minHeight: CicadaTheme.scaled(snippet == nil ? RowMetrics.oneLine : RowMetrics.twoLine),
               alignment: .leading)
        .rowHoverFill(hovering: hovering && route != nil)
        .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
        .contentShape(Rectangle())
    }
}

/// A folder's (or the source's) notes read from the items route and laid out in Notes' groups. `cap` nil is the whole list,
/// paged ("Show more"); else at most `cap` notes, then "All N" (`onAll`).
struct NotesGroupedList: View {
    /// The list key (`SourceListKey.make(channel, collection:)`).
    let key: String
    var query = ""
    var cap: Int?
    var onAll: () -> Void = {}

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(ProvenanceRouter.self) private var provenance: ProvenanceRouter?
    @Environment(AppRouter.self) private var router: AppRouter?
    @Environment(Store.self) private var store: Store?

    private var channel: String { SourceListKey.channel(of: key) }

    private var refreshKey: String {
        "\(key)|\(SourceSearch.normalized(query))|\(store?.channels.loadedAt?.timeIntervalSinceReferenceDate ?? 0)"
    }

    var body: some View {
        if let cache {
            content(cache)
                .task(id: refreshKey) {
                    if !SourceSearch.normalized(query).isEmpty {
                        try? await Task.sleep(for: SourceSearch.debounce)
                        guard !Task.isCancelled else { return }
                    }
                    await cache.refresh(key, query: query)
                }
        }
    }

    @ViewBuilder
    private func content(_ cache: ChannelItemsCache) -> some View {
        let searching = !SourceSearch.normalized(query).isEmpty
        if let list = cache.list(key, query: query) ?? (searching ? cache.list(key) : nil) {
            if list.items.isEmpty {
                note(searching ? Copy.SourcePage.noMatch(query) : Copy.NoteGroups.emptyFolder)
            } else {
                let rows = cap.map { Array(list.items.prefix($0)) } ?? list.items
                VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                    NoteGroupsList(items: rows, today: ISODay.today(), channel: channel,
                                   route: { CapturedItemRoute.of($0, interactive: true) },
                                   open: { SourcePageRouting.go($0, router: router, provenance: provenance) })
                    footer(list, cache: cache)
                }
            }
        } else {
            switch cache.phase(key, query: query) {
            case .failed(let why): note(why)
            case .gone: note(Copy.capturedNone)
            case .idle, .loading, .loaded: ListSkeleton(message: Copy.capturedLoading, rows: 3)
            }
        }
    }

    @ViewBuilder
    private func footer(_ list: ChannelItemsList, cache: ChannelItemsCache) -> some View {
        if let cap, list.total > cap {
            TextButton(title: Copy.SourcePage.all(list.total), help: Copy.SourcePage.allHelp, inline: true, flushLeading: true,
                       action: onAll)
        } else if cap == nil, list.hasMore {
            let loading = cache.isLoadingMore(key, query: query)
            HStack(spacing: CicadaTheme.spacingSM) {
                TextButton(title: loading ? Copy.capturedLoadingMore : Copy.capturedShowMore, inline: true, flushLeading: true) {
                    Task { await cache.loadMore(key, query: query) }
                }
                .disabled(loading)
                Spacer(minLength: CicadaTheme.spacingSM)
                Text(Copy.capturedShown(list.items.count, of: list.total, noun: ("note", "notes")))
                    .font(CicadaTheme.metaFont).monospacedDigit().foregroundStyle(CicadaTheme.textTertiary).lineLimit(1)
            }
        }
    }

    private func note(_ text: String) -> some View {
        Text(text)
            .font(CicadaTheme.metaFont)
            .foregroundStyle(CicadaTheme.textTertiary)
            .lineLimit(2)
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine), alignment: .leading)
    }
}
