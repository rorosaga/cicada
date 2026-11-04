import AppKit
import SwiftUI

// 2026-11-04 (owner: "sources like Apple notes, reminders, contacts, calendar … should have a better user experience
// and UI"; "replicate this layout inside Apple Notes, starting from those that are iCloud … and then you go into it, and
// then you can see the notes … or you can see folders … if we can standardize so that this view maybe translates to
// some other place, like … the transcriptions that I have connected for hex or whisperflow, then it can work the same")
// — ONE browser for every source this Mac reads: accounts → collections → items, with one search and the Reader as the
// item view. It fills the standard source page's `content` slot (`SourcePageLayout`, app.md "The standard source
// page"); the page's head, connect area and footer stay the layout's.
//
//   • Apple Notes:   account (iCloud, On My Mac, a Gmail account) → folder → notes
//   • Calendar:      account (iCloud, Google, Exchange, On My Mac, Subscribed) → calendar → events
//   • Reminders:     account → list → reminders
//   • Meeting recorders: recorder → folder → meetings (title, day, how long), `MeetingsBrowser`
//   • Contacts:      every card on this Mac as a grid of faces — their photo, else their monogram (`ContactsGrid`)
//
// A level opens in the content's place (DR-81: never in place), "‹ <where you were>" and Esc return. Rows are DR-34's
// one-line rows with a trailing chevron in tertiary ink (`SourceGroupRow`'s grammar), hover a fill (DR-48); an account
// wears its own mark (DR-52: a bundled brand mark, else a system symbol — Apple's marks are never committed). No
// paragraph anywhere (DESIGN_RULES §9 2026-11-03); counts through `UsageFormat` (DR-21).

/// The content slot of a This Mac source's page, one call for every one of them: the right browser for the entry, or
/// nothing for an entry that is not one of these (the caller draws its own content then). Drawn only once something
/// came in (DR-81: a source with nothing in yet draws no search and no list; its connect area says how to start).
struct ThisMacSourceContent: View {
    let entry: SourceCatalogEntry
    /// The entry's channels as `/sources/channels` lists them (`SourceCatalog.channelsOf`).
    let channels: [SourceChannel]

    /// Whether this view draws the entry's content (Apple Notes, Calendar, Reminders, Contacts, the recorders).
    static func handles(_ entry: SourceCatalogEntry) -> Bool {
        ["notes", "calendar-local", RemindersReader.channel, ContactsReader.channel, SourceCatalog.hexId,
         SourceCatalog.meetingFoldersId].contains(entry.id)
    }

    var body: some View {
        switch entry.id {
        case "notes", "calendar-local", RemindersReader.channel:
            if channels.contains(where: { $0.count > 0 || $0.connected }) {
                // Each of these entries' id is its one channel's.
                SourceBrowser(channel: entry.id, sourceTitle: entry.title)
            }
        case ContactsReader.channel:
            if channels.contains(where: { $0.connected }) { ContactsGrid() }
        case SourceCatalog.hexId, SourceCatalog.meetingFoldersId:
            let folders = channels.map { (id: $0.id, label: $0.label) }
            if !folders.isEmpty { MeetingsBrowser(folders: folders, sourceTitle: entry.title) }
        default:
            EmptyView()
        }
    }
}

/// Accounts → collections → items for one channel.
struct SourceBrowser: View {
    /// The channel the items come from: `notes`, `calendar-local`, `reminders-local`.
    let channel: String
    /// The source's name, what the first level's back button returns to ("‹ Apple Notes").
    let sourceTitle: String

    @Environment(ChannelItemsCache.self) private var cache: ChannelItemsCache?
    @Environment(Store.self) private var store: Store?
    @State private var path: [SourceBrowserLevel] = []
    @State private var query = ""

    private var tree: ChannelCollections? { cache?.collections(channel) }

    /// Re-read when the channels move (a sync that brought something in lands here too; a 304 moves nothing).
    private var refreshKey: String {
        "\(channel)|\(store?.channels.loadedAt?.timeIntervalSinceReferenceDate ?? 0)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if let level = path.last {
                SourceBrowserHead(back: backTitle, title: level.title(channel: channel)) { pop() }
            }
            SourceSearchHeader(query: $query, prompt: prompt)
            content
        }
        .task(id: refreshKey) {
            await cache?.refreshCollections(channel)
            // One collection opens straight on its own list; the page's status line reads the channel's newest item.
            if case .items = SourceBrowserText.start(tree) { await cache?.refresh(channel) }
        }
        .onChange(of: channel) { _, _ in path = []; query = "" }
        .sourcePageBack(active: !path.isEmpty) { pop() }
    }

    // MARK: - What shows

    @ViewBuilder
    private var content: some View {
        let start = SourceBrowserText.start(tree)
        switch path.last {
        case .collection(let collection, _)?:
            items(SourceListKey.make(channel, collection: collection.id), cap: nil)
        case .all?:
            items(channel, cap: nil)
        case .account(let account)?:
            if !searching { collectionRows(account.collections) } else { items(channel, cap: nil) }
        case nil:
            if searching {
                items(channel, cap: nil)
            } else {
                switch start {
                case .accounts:
                    SourceSection(title: Copy.SourceBrowser.accounts) { accountRows(tree?.accounts ?? []) }
                    SourceSection(title: Copy.SourceBrowser.recent) { items(channel, cap: SourceBrowserText.recent) }
                case .collections(let account):
                    collectionRows(account.collections)
                    SourceSection(title: Copy.SourceBrowser.recent) { items(channel, cap: SourceBrowserText.recent) }
                case .items(let collection):
                    items(SourceListKey.make(channel, collection: collection.id), cap: nil)
                case .flat:
                    items(channel, cap: SourceItemsRules.cap)
                }
            }
        }
    }

    private var searching: Bool { !SourceSearch.normalized(query).isEmpty }

    private func items(_ key: String, cap: Int?) -> some View {
        SourceItemsSection(channel: key, query: query, cap: cap) { drill in
            if case .all = drill { push(.all) }
        }
    }

    private func accountRows(_ accounts: [SourceAccount]) -> some View {
        VStack(spacing: 0) {
            ForEach(accounts) { account in
                SourceBrowserRow(title: SourceBrowserText.accountName(account),
                                 meta: Copy.SourceBrowser.count(account.count, channel: channel)) {
                    SourceAccountMark(account: account, channel: channel)
                } open: { push(.account(account)) }
            }
        }
    }

    private func collectionRows(_ collections: [SourceCollection]) -> some View {
        VStack(spacing: 0) {
            ForEach(collections) { collection in
                SourceBrowserRow(title: collection.name,
                                 meta: Copy.SourceBrowser.count(collection.count, channel: channel)) {
                    Image(systemName: SourceBrowserLevel.collectionSymbol(channel))
                        .font(CicadaTheme.icon(.list))
                        .foregroundStyle(CicadaTheme.textSecondary)
                } open: {
                    push(.collection(collection, account: path.last?.account))
                }
            }
        }
    }

    // MARK: - The search's words

    private var prompt: String {
        switch path.last {
        case .collection(let collection, _)?:
            return Copy.SourceBrowser.search(collection.count, channel: channel, in: collection.name)
        case .account?:
            // An account's search reads the whole source (the backend narrows by collection only), and says so.
            return Copy.SourceBrowser.search(nil, channel: channel)
        default:
            let total = tree?.accounts.reduce(0) { $0 + $1.count }
            return Copy.SourceBrowser.search(total.flatMap { $0 > 0 ? $0 : nil }, channel: channel)
        }
    }

    // MARK: - Moving

    private var backTitle: String {
        guard path.count >= 2 else { return sourceTitle }
        return path[path.count - 2].title(channel: channel)
    }

    private func push(_ level: SourceBrowserLevel) {
        Instant.run {
            query = ""
            path.append(level)
        }
    }

    private func pop() {
        Instant.run {
            query = ""
            _ = path.popLast()
        }
    }
}

/// Esc on a source page steps back one level before it closes the page. The detail column is what holds the keyboard
/// focus, so its `onExitCommand` takes Esc ahead of a back button's `.cancelAction`, and a level opened in the page's
/// place (DR-81) says so here while it is open.
@Observable
@MainActor
final class SourcePageBack {
    @ObservationIgnored var step: (() -> Void)?

    /// Steps back when a level is open; false when Esc should close the page.
    func run() -> Bool {
        guard let step else { return false }
        step()
        return true
    }
}

extension View {
    /// While `active`, Esc on the source page runs `step`.
    func sourcePageBack(active: Bool, step: @escaping () -> Void) -> some View {
        modifier(SourcePageBackModifier(active: active, step: step))
    }
}

private struct SourcePageBackModifier: ViewModifier {
    let active: Bool
    let step: () -> Void
    @Environment(SourcePageBack.self) private var back: SourcePageBack?

    func body(content: Content) -> some View {
        content
            .onChange(of: active, initial: true) { _, on in back?.step = on ? step : nil }
            .onDisappear { if active { back?.step = nil } }
    }
}

/// One level of the browser the person opened.
enum SourceBrowserLevel: Hashable {
    case account(SourceAccount)
    case collection(SourceCollection, account: SourceAccount?)
    /// Every item, newest first (the Recent section's "All N").
    case all

    func title(channel: String) -> String {
        switch self {
        case .account(let account): SourceBrowserText.accountName(account)
        case .collection(let collection, _): collection.name
        case .all: Copy.SourceBrowser.noun(channel).many.capitalized
        }
    }

    var account: SourceAccount? {
        switch self {
        case .account(let account): account
        case .collection(_, let account): account
        case .all: nil
        }
    }

    /// A collection's glyph: a Notes folder, a calendar, a Reminders list.
    static func collectionSymbol(_ channel: String) -> String {
        switch channel {
        case "calendar-local": "calendar"
        case "reminders-local": "list.bullet"
        case "notes": "folder"
        default: "folder"
        }
    }
}

extension SourceAccount: Hashable {
    func hash(into hasher: inout Hasher) { hasher.combine(name); hasher.combine(provider) }
}

/// "‹ <where you were>" (Esc), then where you are, once.
struct SourceBrowserHead: View {
    let back: String
    let title: String
    let onBack: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
            TextButton(title: Copy.SourceBrowser.back(back), help: Copy.SourceBrowser.backHelp, action: onBack)
                .keyboardShortcut(.cancelAction)
                .padding(.leading, -CicadaTheme.scaled(10))
            Text(title)
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
                .lineLimit(1)
        }
    }
}

/// An account's mark: its provider's bundled brand mark where one is licensed (Google), else a system symbol (iCloud,
/// this Mac, Exchange), on DR-52's dense tile.
struct SourceAccountMark: View {
    let account: SourceAccount
    let channel: String

    var body: some View {
        let kind = account.kind
        LogoTile(logo: kind.logo(channel: channel), density: .dense, systemFallback: kind.symbol)
            .accessibilityHidden(true)
    }
}

/// One row that opens a level: its icon, its name, how many it holds, a chevron (DR-34, DR-48, DR-81).
struct SourceBrowserRow<Icon: View>: View {
    let title: String
    let meta: String?
    @ViewBuilder let icon: () -> Icon
    let open: () -> Void

    @State private var hovering = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: open) {
            HStack(spacing: CicadaTheme.spacingSM) {
                icon()
                    .frame(width: CicadaTheme.scaled(24), height: CicadaTheme.scaled(24))
                Text(title)
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                Spacer(minLength: CicadaTheme.spacingSM)
                if let meta {
                    Text(meta)
                        .font(CicadaTheme.metaFont)
                        .monospacedDigit()
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .lineLimit(1)
                        .fixedSize()
                }
                Image(systemName: "chevron.right")
                    .font(CicadaTheme.font(size: 10, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .accessibilityHidden(true)
            }
            .frame(minHeight: CicadaTheme.scaled(RowMetrics.oneLine))
            .padding(.horizontal, CicadaTheme.scaled(10))
            .rowHoverFill(hovering: hovering)
            .animation(CicadaMotion.hover(reduceMotion: reduceMotion), value: hovering)
            .contentShape(Rectangle())
        }
        .buttonStyle(.cicadaPlain)
        .onHover { hovering = $0 }
        .help(Copy.SourceBrowser.openHelp)
        .accessibilityLabel([title, meta].compactMap { $0 }.joined(separator: ", "))
        .accessibilityHint(Copy.SourcePage.groupOpenHelp)
    }
}
