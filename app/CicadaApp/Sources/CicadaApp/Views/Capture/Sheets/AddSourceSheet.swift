import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// The Capture page's "+" picker (G62). A grid of tiles; picking one expands it
/// into that channel's flow inline. **All** explanatory copy about capture
/// lives here — the page behind it shows only what is already connected, so
/// this sheet is the single place a user learns what Cicada can read.
///
/// "Manage…" from a connected row opens this sheet already expanded on that
/// channel's tile (`initialTile:`), where feeds and calendars show their
/// current rows with remove buttons.
enum AddSourceTile: String, CaseIterable, Identifiable {
    case chatExport, bookmarksFile, pasteLink, rssFeed, calendar
    case browserBookmarks, appleNotes, telegram
    // G71 §4.1 — one tile per platform, replacing the combined `savedContent`
    // tile: the routes differ (two are Connect, four are Import file) and a
    // single "Instagram & YouTube" tile could not carry a route badge.
    case instagram, youtube, pinterest, reddit, tiktok, linkedin
    /// X's connector (Task 14, registry-driven) — a real Connect route,
    /// exactly like Pinterest and Reddit, now that `x.py` is wired into
    /// `ADAPTERS` and `channelIds` resolves against a live backend channel.
    case x

    var id: String { rawValue }

    var route: ImportRoute {
        switch self {
        case .pinterest, .reddit, .x: return .connect
        case .browserBookmarks, .appleNotes: return .sync
        case .rssFeed, .calendar: return .subscribe
        case .pasteLink: return .paste
        case .telegram: return .connect
        case .chatExport, .bookmarksFile, .instagram, .youtube, .tiktok, .linkedin:
            return .importFile
        }
    }

    var title: String {
        switch self {
        case .chatExport: "Chat export"
        case .bookmarksFile: "Bookmarks file"
        case .pasteLink: "Paste a link"
        case .rssFeed: "RSS feed"
        case .calendar: "Calendar"
        case .browserBookmarks: "Chrome & Safari bookmarks"
        case .appleNotes: "Apple Notes"
        case .telegram: "Telegram bot"
        case .instagram: "Instagram"
        case .youtube: "YouTube"
        case .pinterest: "Pinterest"
        case .reddit: "Reddit"
        case .tiktok: "TikTok"
        case .linkedin: "LinkedIn"
        case .x: "X"
        }
    }

    var blurb: String {
        switch self {
        case .chatExport: "Everything you've said to Claude or ChatGPT, backdated."
        case .bookmarksFile: "An exported bookmarks file — HTML or JSON."
        case .pasteLink: "One URL, saved and enriched right now."
        case .rssFeed: "A blog or Substack Cicada checks for new posts."
        case .calendar: "A webcal/ICS URL — events become episodes."
        case .browserBookmarks: "Read straight off this Mac. No login, no OAuth."
        case .appleNotes: "One-way import from your local Notes library."
        case .telegram: "Forward links and voice notes to your own bot."
        case .instagram: "Your saved posts, from a data export."
        case .youtube: "Playlists and watch history, from Takeout."
        case .pinterest: "Boards and pins, pulled straight from your account."
        case .reddit: "Saved posts and comments, pulled every night."
        case .tiktok: "Favourites and likes, from a data export."
        case .linkedin: "Saved items — links and dates, nothing more."
        case .x: "Bookmarks, pulled straight from your account."
        }
    }

    var icon: String {
        switch self {
        case .chatExport: "bubble.left.and.bubble.right"
        case .bookmarksFile: "bookmark"
        case .pasteLink: "link"
        case .rssFeed: "dot.radiowaves.up.forward"
        case .calendar: "calendar"
        case .browserBookmarks: "globe"
        case .appleNotes: "note.text"
        case .telegram: "paperplane.fill"
        case .instagram: "camera.fill"
        case .youtube: "play.rectangle.fill"
        case .pinterest: "pin.fill"
        case .reddit: "bubble.left.and.text.bubble.right.fill"
        case .tiktok: "music.note"
        case .linkedin: "briefcase.fill"
        case .x: "x.circle"
        }
    }

    /// The `GET /sources/channels` ids this tile manages.
    ///
    /// Chat export owns **both** export channels — its walkthrough picker is
    /// where the user chooses Claude or ChatGPT, so one tile covers two rows.
    /// `pasteLink` owns none: it is an alternative route into `files`, which
    /// `bookmarksFile` already claims. The four Import-file platform tiles
    /// (Instagram, YouTube, TikTok, LinkedIn) also own none — none of them
    /// has a persisted backend channel yet — and a channel must map back to
    /// exactly one tile for "Manage…" to be unambiguous.
    var channelIds: [String] {
        switch self {
        case .chatExport: ["chat-export:claude", "chat-export:chatgpt"]
        case .bookmarksFile: ["files"]
        case .pasteLink: []
        case .rssFeed: ["rss"]
        case .calendar: ["calendar"]
        case .browserBookmarks: ["bookmarks"]
        case .appleNotes: ["notes"]
        case .telegram: ["telegram"]
        case .pinterest: ["pinterest"]
        case .reddit: ["reddit"]
        // Task 14 — x.py joined ADAPTERS, so X resolves against a live
        // backend channel exactly like Pinterest and Reddit.
        case .x: ["x"]
        case .instagram, .youtube, .tiktok, .linkedin: []
        }
    }

    /// The bundled brand-mark PNG for this tile (Task 13), when the
    /// maintainers fetched one — `nil` for a tile whose row isn't a single
    /// platform's logo: multi-vendor exports, local file/paste actions, or a
    /// platform GROUP with no single brand mark (Chrome+Safari together,
    /// Apple Notes, RSS, Calendar all kept their SF Symbol — no sensible
    /// single logo exists for any of them).
    var logoName: String? {
        switch self {
        case .instagram: "instagram"
        case .youtube: "youtube"
        case .pinterest: "pinterest"
        case .reddit: "reddit"
        case .tiktok: "tiktok"
        case .linkedin: "linkedin"
        case .x: "x"
        case .telegram: "telegram"
        case .chatExport, .bookmarksFile, .pasteLink, .rssFeed, .calendar,
             .browserBookmarks, .appleNotes:
            nil
        }
    }

    /// Reverse lookup for "Manage…" on a connected row.
    static func forChannel(_ channelId: String) -> AddSourceTile? {
        allCases.first { $0.channelIds.contains(channelId) }
    }

    /// Which export vendors this tile's walkthrough offers.
    ///
    /// The panel used to render `WalkthroughVendor.allCases` for BOTH
    /// walkthrough tiles, so "Chat export" offered Google Takeout and
    /// Instagram — whose files belong to `POST /sources/upload`, not
    /// `POST /conversations/upload` — and the saved-content tile offered
    /// Claude and ChatGPT with the mismatch running the other way. Picking the
    /// wrong one uploaded the file to the wrong parser and reported "Imported
    /// 0". The tile, not the panel, decides.
    var vendors: [WalkthroughVendor] {
        switch self {
        case .chatExport: [.claude, .chatgpt]
        case .instagram: [.instagram]
        case .youtube: [.takeout]
        case .tiktok: [.tiktok]
        case .linkedin: [.linkedin]
        // The Reddit tile is Connect-first, but the GDPR export is the only
        // way past the API's ~1,000-item listing cap, so the walkthrough
        // rides along until Task 11's ConnectorSetupPanel lands.
        case .reddit: [.redditExport]
        default: []
        }
    }
}

struct AddSourceSheet: View {
    var initialTile: AddSourceTile?
    let onClose: () -> Void

    @Environment(Store.self) private var store

    @State private var expanded: AddSourceTile?
    @State private var vendor: WalkthroughVendor = .claude
    @State private var linkText = ""
    @State private var feedText = ""
    @State private var calendarText = ""
    @State private var busy = false
    @State private var result: String?
    @State private var error: String?
    @State private var removingFeed: String?
    @State private var removingCalendar: String?
    @State private var stage: ImportStage = .idle
    @State private var includeHistory = false
    /// The in-flight preview/import network Task, if any. Cancelled — not
    /// just abandoned — whenever a newer one supersedes it (G71 fix round 1,
    /// H1): a bare, unstored `Task {}` keeps running after `collapse()`, and
    /// its late response would otherwise overwrite whichever flow the user
    /// has since opened.
    @State private var importTask: Task<Void, Never>?
    /// Bumped every time `preview()`/`confirmImport()` starts a new request
    /// and every time `collapse()` tears one down. A response is only ever
    /// applied to `stage` if its captured generation still matches this one
    /// — belt-and-suspenders alongside `importTask` cancellation for the
    /// case where cancellation doesn't land before the response does.
    @State private var importGeneration = 0

    private var feeds: [FeedSubscription] { store.feeds.value ?? [] }
    private var calendars: [CalendarSubscription] { store.calendars.value ?? [] }

    /// Fixed three columns. `.adaptive(minimum: 190)` gave four cramped
    /// columns at 640 pt and forced `lineLimit(1)` on the titles.
    private static let columns = Array(
        repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingMD),
        count: 3
    )

    /// What Esc does. Backing out of a focused tile before closing the sheet
    /// means one keypress can't discard both a half-typed URL and the sheet.
    enum EscapeAction: Equatable { case back, close }

    static func escapeAction(expanded: AddSourceTile?) -> EscapeAction {
        expanded == nil ? .close : .back
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().background(CicadaTheme.border)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    // Focused mode: one tile at a time, with its own back
                    // control. The grid + an expanded flow together pushed the
                    // action buttons below the fold on a 620 pt sheet.
                    if let expanded {
                        backControl(from: expanded)
                        flow(for: expanded)
                    } else {
                        LazyVGrid(columns: Self.columns, spacing: CicadaTheme.spacingMD) {
                            ForEach(AddSourceTile.allCases) { tile in
                                tileButton(tile)
                            }
                        }
                    }
                    statusLine
                }
                .padding(CicadaTheme.spacingXL)
            }
        }
        .frame(width: 640, height: 620)
        .background(CicadaTheme.background)
        .onAppear {
            if expanded == nil, let initialTile {
                open(initialTile)
            }
        }
        .onKeyPress(.escape) {
            switch Self.escapeAction(expanded: expanded) {
            case .back: collapse()
            case .close: onClose()
            }
            return .handled
        }
    }

    private func backControl(from tile: AddSourceTile) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Button(action: collapse) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Image(systemName: "chevron.left").font(.system(size: 11, weight: .semibold))
                    Text("All sources").font(.system(size: 12, weight: .medium))
                }
                .foregroundStyle(CicadaTheme.textSecondary)
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel("Back to all sources")

            Text(tile.title)
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Spacer()
        }
    }

    /// Opening a tile resets the transient status AND pins the vendor picker
    /// to a vendor this tile actually offers.
    private func open(_ tile: AddSourceTile) {
        error = nil
        result = nil
        expanded = tile
        if let first = tile.vendors.first { vendor = first }
        // L5 (final review): `includeHistory` was never reset, so a TikTok
        // import's "Also import browsing history" toggle silently persisted
        // into a LATER Instagram/YouTube import — inert there today (only
        // TikTok reads it), but still wrong state to carry across tiles.
        includeHistory = false
    }

    private func collapse() {
        error = nil
        result = nil
        expanded = nil
        stage = .idle
        // H1: cancel the in-flight request AND bump the generation, so a
        // response already past its cancellation checkpoint still can't land
        // on the next flow's `stage`.
        importTask?.cancel()
        importTask = nil
        importGeneration += 1
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Text("Add a source")
                    .font(CicadaTheme.titleFont)
                    .foregroundStyle(CicadaTheme.textPrimary)
                Text("Anything you add lands in the queue for the next Sleep cycle.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
            }
            Spacer()
            Button("Done", action: onClose)
                .buttonStyle(.bordered)
                .accessibilityLabel("Close the add-source sheet")
        }
        .padding(CicadaTheme.spacingXL)
    }

    /// G71 §4.1 — every tile carries a route badge (Connect / Import file /
    /// Sync / Subscribe / Save) and, once the channel is live, the channel's
    /// own detail line in place of the static blurb.
    private func tileButton(_ tile: AddSourceTile) -> some View {
        let state = AddSourceTile.tileState(tile, channels: store.channels.value ?? [])
        return Button {
            open(tile)
        } label: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                if let logoName = tile.logoName {
                    LogoImage.platformTile(name: logoName, size: 32, systemFallback: tile.icon)
                } else {
                    Image(systemName: tile.icon)
                        .font(.system(size: 16, weight: .medium))
                        .foregroundStyle(CicadaTheme.textSecondary)
                }
                Text(tile.title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(state.detail ?? tile.blurb)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(state.badge)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(state.connected ? CicadaTheme.success : CicadaTheme.textTertiary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(CicadaTheme.spacingMD)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(CicadaTheme.surfaceElevated)
            )
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.cicadaPlain)
        .disabled(busy)
        .accessibilityLabel("\(tile.title). \(state.badge). \(state.detail ?? tile.blurb)")
    }

    // MARK: - Per-tile flows

    @ViewBuilder
    private func flow(for tile: AddSourceTile) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            switch tile {
            case .chatExport:
                WalkthroughPanel(vendors: tile.vendors, vendor: $vendor) { pickChatExport() }
            case .instagram, .youtube, .tiktok, .linkedin:
                // G71 §4.2–4.3 — drop straight into a live preview: the
                // walkthrough shows exactly where to click, then a drop (or
                // "Choose file…") parses the export via the staging-free
                // preview endpoint and shows what it contains before anything
                // is imported.
                VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
                    WalkthroughPanel(vendors: tile.vendors, vendor: $vendor) { pickForPreview() }
                    if tile == .tiktok {
                        Toggle("Also import browsing history (noisy)", isOn: $includeHistory)
                            .font(CicadaTheme.captionFont)
                            .accessibilityLabel("Also import TikTok browsing history")
                    }
                    ImportPreviewSection(stage: stage,
                                         onConfirm: { confirmImport($0) },
                                         onCancel: { stage = .idle })
                }
                .onDrop(of: [.fileURL], isTargeted: nil) { providers in
                    guard let provider = providers.first else { return false }
                    _ = provider.loadObject(ofClass: URL.self) { url, _ in
                        if let url { Task { @MainActor in preview(url) } }
                    }
                    return true
                }
            case .pinterest, .reddit, .x:
                ConnectorSetupPanel(connectorId: tile.rawValue, vendors: tile.vendors, vendor: $vendor)
            case .bookmarksFile:
                Text("A Netscape-format .html, a Chrome .json, a YouTube playlist .csv, or a whole Takeout .zip.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                Button("Choose file…") { pickSavedContent() }
                    .buttonStyle(.borderedProminent)
                    .accessibilityLabel("Choose a bookmarks file to import")
            case .pasteLink:
                textFlow(placeholder: "https://…", text: $linkText, action: "Save") { await saveLink() }
            case .rssFeed:
                textFlow(placeholder: "https://example.com/feed.xml", text: $feedText, action: "Subscribe") { await subscribeFeed() }
                feedList
            case .calendar:
                textFlow(placeholder: "webcal://… or https://…/calendar.ics", text: $calendarText, action: "Subscribe") { await subscribeCalendar() }
                calendarList
            case .browserBookmarks:
                Text("Cicada reads the Chrome and Safari bookmark files on this Mac directly. Only URLs it hasn't seen become new episodes.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                Button("Sync now") { Task { await syncBookmarks() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(busy)
                    .accessibilityLabel("Sync Chrome and Safari bookmarks now")
            case .appleNotes:
                Text("One-way import from Notes.app. The first sync asks macOS for automation access — allow it once.")
                    .font(CicadaTheme.bodyFont)
                    .foregroundStyle(CicadaTheme.textSecondary)
                Button("Sync now") { Task { await syncNotes() } }
                    .buttonStyle(.borderedProminent)
                    .disabled(busy)
                    .accessibilityLabel("Sync Apple Notes now")
            case .telegram:
                telegramInstructions
            }
        }
        .padding(CicadaTheme.spacingLG)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func textFlow(placeholder: String, text: Binding<String>, action: String,
                          run: @escaping () async -> Void) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            TextField(placeholder, text: text)
                .textFieldStyle(.roundedBorder)
                .onSubmit { Task { await run() } }
            Button(action) { Task { await run() } }
                .buttonStyle(.borderedProminent)
                .disabled(busy || text.wrappedValue.trimmingCharacters(in: .whitespaces).isEmpty)
                .accessibilityLabel(action)
        }
    }

    @ViewBuilder
    private var feedList: some View {
        if !feeds.isEmpty {
            VStack(spacing: CicadaTheme.spacingXS) {
                ForEach(feeds) { feed in
                    FeedSubscriptionRow(feed: feed, isRemoving: removingFeed == feed.url) {
                        Task {
                            removingFeed = feed.url
                            await store.perform(UnsubscribeFeed(url: feed.url))
                            removingFeed = nil
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var calendarList: some View {
        if !calendars.isEmpty {
            VStack(spacing: CicadaTheme.spacingXS) {
                ForEach(calendars) { cal in
                    CalendarSubscriptionRow(calendar: cal, isRemoving: removingCalendar == cal.url) {
                        Task {
                            removingCalendar = cal.url
                            await store.perform(UnsubscribeCalendar(url: cal.url))
                            removingCalendar = nil
                        }
                    }
                }
            }
        }
    }

    private var telegramInstructions: some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            Text("Create a bot with @BotFather, then set CICADA_TELEGRAM_BOT_TOKEN in api/.env and restart the backend. Forward it a link to save it, or send /note to capture a thought.")
                .font(CicadaTheme.bodyFont)
                .foregroundStyle(CicadaTheme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            CommandBox(command: "CICADA_TELEGRAM_BOT_TOKEN=<token>")
            Button {
                NSWorkspace.shared.open(URL(string: "https://t.me/BotFather")!)
            } label: {
                Label("Open BotFather", systemImage: "arrow.up.forward.app")
            }
            .buttonStyle(.bordered)
            .accessibilityLabel("Open BotFather in Telegram")
        }
    }

    @ViewBuilder
    private var statusLine: some View {
        if busy {
            HStack(spacing: CicadaTheme.spacingSM) {
                ProgressView().controlSize(.small)
                Text("Working…").font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.textTertiary)
            }
        } else if let result {
            Text(result).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.success)
        } else if let error {
            Text(error).font(CicadaTheme.captionFont).foregroundStyle(CicadaTheme.danger)
        }
    }

    // MARK: - Actions

    private func finish(_ message: String) async {
        result = message
        error = nil
        busy = false
        await store.refresh([.channels, .status, .sources])
    }

    private func fail(_ err: Error) {
        error = Self.friendlyError(err)
        result = nil
        busy = false
    }

    private func saveLink() async {
        let url = linkText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        busy = true
        do {
            let r = try await APIClient.shared.saveURL(url)
            linkText = ""
            await finish(r.message)
        } catch { fail(error) }
    }

    private func subscribeFeed() async {
        let url = feedText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        busy = true
        let ok = await store.perform(SubscribeFeed(url: url, tags: []))
        feedText = ok ? "" : feedText
        busy = false
        if ok { await finish("Subscribed — Cicada polls it from now on") } else { result = nil; error = store.toast }
    }

    private func subscribeCalendar() async {
        let url = calendarText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !url.isEmpty else { return }
        busy = true
        let ok = await store.perform(SubscribeCalendar(url: url, tags: []))
        calendarText = ok ? "" : calendarText
        busy = false
        if ok { await finish("Subscribed — events arrive on the next poll") } else { result = nil; error = store.toast }
    }

    private func syncBookmarks() async {
        busy = true
        do {
            let r = try await APIClient.shared.syncBookmarks()
            await finish("\(r.new) new · \(r.skipped) already saved")
        } catch { fail(error) }
    }

    private func syncNotes() async {
        busy = true
        do {
            let r = try await APIClient.shared.syncNotes()
            await finish("\(r.new) new · \(r.skipped) unchanged")
        } catch { fail(error) }
    }

    private func pickChatExport() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json, .html]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = true
        panel.message = "Select a Claude or ChatGPT conversation export"
        guard panel.runModal() == .OK else { return }
        let files = Self.expandToFiles(panel.urls, exts: ["json", "html"])
        guard !files.isEmpty else { error = "No JSON or HTML files found"; return }
        runImport(files: files) { try await APIClient.shared.uploadFile(fileURL: $0) }
    }

    private func pickSavedContent() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json, .html, .commaSeparatedText, .zip]
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.message = "Select a bookmarks/saved-content export (HTML, JSON, CSV, or ZIP)"
        guard panel.runModal() == .OK, !panel.urls.isEmpty else { return }
        runImport(files: panel.urls) { try await APIClient.shared.uploadSource(fileURL: $0) }
    }

    /// Pick a file and immediately preview it — nothing is imported until the
    /// user confirms what the preview showed them (G71 §4.3).
    private func pickForPreview() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json, .html, .commaSeparatedText, .zip]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "Select the export file to import"
        guard panel.runModal() == .OK, let url = panel.urls.first else { return }
        preview(url)
    }

    /// Cancels any prior in-flight preview/import and mints a new generation
    /// token before launching under it (G71 fix round 1, H1) — a response
    /// captured under an older generation is dropped rather than applied to
    /// `stage`, whether it lands after `collapse()` or after a newer drop on
    /// the SAME flow superseded it.
    private func startImportTask(_ work: @escaping (Int) async -> Void) {
        importTask?.cancel()
        importGeneration += 1
        let generation = importGeneration
        importTask = Task {
            await work(generation)
        }
    }

    private func preview(_ url: URL) {
        stage = .parsing(url.lastPathComponent)
        // Devin round-1, finding 4: capture the toggle's value at the moment
        // the PREVIEW is actually requested, not read live again later — the
        // network round trip (and the time the user spends looking at the
        // resulting preview) is exactly the window `includeHistory` could
        // drift in. `requestedIncludeHistory` is what both this preview
        // request AND the eventual Confirm use.
        let requestedIncludeHistory = includeHistory
        startImportTask { generation in
            do {
                let result = try await APIClient.shared.previewSource(
                    fileURL: url, includeHistory: requestedIncludeHistory)
                guard generation == self.importGeneration else { return }
                self.stage = ImportOverlayState.afterPreview(
                    result, file: url, includeHistory: requestedIncludeHistory)
            } catch {
                guard generation == self.importGeneration else { return }
                self.stage = .failed(Self.friendlyError(error))
            }
        }
    }

    /// Confirm re-posts the SAME file without the preview flag, carrying the
    /// EXACT `includeHistory` value the preview stage CAPTURED at request
    /// time (Devin round-1, finding 4 — replaces reading the live toggle
    /// here, which could have drifted since the preview was shown: flipping
    /// TikTok's "Also import browsing history" after previewing must not
    /// silently change what Confirm posts). Nothing is cached server-side:
    /// a preview that stages nothing must not stage bytes.
    ///
    /// Guards against a double-tap firing two imports (M4): once `stage` has
    /// left `.preview`, a repeat activation is a no-op rather than a second
    /// upload.
    private func confirmImport(_ url: URL) {
        guard case .preview(_, _, let previewedIncludeHistory) = stage else { return }
        stage = .importing
        startImportTask { generation in
            do {
                let response = try await APIClient.shared.uploadSource(
                    fileURL: url, includeHistory: previewedIncludeHistory)
                await self.store.refresh([.channels, .status, .sources])
                guard generation == self.importGeneration else { return }
                self.stage = .done(ImportOverlayState.summary(response))
            } catch {
                guard generation == self.importGeneration else { return }
                self.stage = .failed(Self.friendlyError(error))
            }
        }
    }

    private func runImport(files: [URL], upload: @escaping (URL) async throws -> UploadResponse) {
        busy = true
        error = nil
        result = nil
        Task {
            var created = 0, skipped = 0
            var firstError: String?
            for file in files {
                do {
                    let r = try await upload(file)
                    created += r.episodesCreated
                    skipped += r.duplicatesSkipped
                } catch {
                    if firstError == nil { firstError = Self.friendlyError(error) }
                }
            }
            if created == 0, let firstError {
                self.error = firstError
                self.result = nil
                busy = false
            } else {
                var summary = "Imported \(created), skipped \(skipped)"
                if firstError != nil { summary += " (some files failed)" }
                await finish(summary)
            }
        }
    }

    private static func expandToFiles(_ urls: [URL], exts: Set<String>) -> [URL] {
        var out: [URL] = []
        let fm = FileManager.default
        for url in urls {
            var isDir: ObjCBool = false
            if fm.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                if let e = fm.enumerator(at: url, includingPropertiesForKeys: nil) {
                    for case let f as URL in e where exts.contains(f.pathExtension.lowercased()) {
                        out.append(f)
                    }
                }
            } else if exts.contains(url.pathExtension.lowercased()) {
                out.append(url)
            }
        }
        return out
    }

    /// Same rule as the old SourcesView: surface the backend's `detail` rather
    /// than raw JSON, and give 404 a "not shipped yet" spin.
    static func friendlyError(_ error: Error) -> String {
        if case APIError.httpError(let code, let msg) = error {
            if code == 404 { return "That endpoint isn't available yet — update the Cicada backend." }
            if let data = msg.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let detail = obj["detail"] as? String {
                return detail
            }
            return msg
        }
        return error.localizedDescription
    }
}
