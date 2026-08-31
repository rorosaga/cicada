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
    case browserBookmarks, appleNotes, telegram, savedContent

    var id: String { rawValue }

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
        case .savedContent: "Instagram saved / YouTube playlists"
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
        case .savedContent: "Saved posts and playlists from a data export."
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
        case .savedContent: "camera.fill"
        }
    }

    /// The `GET /sources/channels` ids this tile manages.
    ///
    /// Chat export owns **both** export channels — its walkthrough picker is
    /// where the user chooses Claude or ChatGPT, so one tile covers two rows.
    /// `pasteLink` and `savedContent` own none: they are alternative routes
    /// into `files`, which `bookmarksFile` already claims, and a channel must
    /// map back to exactly one tile for "Manage…" to be unambiguous.
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
        case .savedContent: []
        }
    }

    /// Reverse lookup for "Manage…" on a connected row.
    static func forChannel(_ channelId: String) -> AddSourceTile? {
        allCases.first { $0.channelIds.contains(channelId) }
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

    private var feeds: [FeedSubscription] { store.feeds.value ?? [] }
    private var calendars: [CalendarSubscription] { store.calendars.value ?? [] }

    private let columns = [GridItem(.adaptive(minimum: 190), spacing: CicadaTheme.spacingMD)]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().background(CicadaTheme.border)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    LazyVGrid(columns: columns, spacing: CicadaTheme.spacingMD) {
                        ForEach(AddSourceTile.allCases) { tile in
                            tileButton(tile)
                        }
                    }
                    if let expanded { flow(for: expanded) }
                    statusLine
                }
                .padding(CicadaTheme.spacingXL)
            }
        }
        .frame(width: 640, height: 620)
        .background(CicadaTheme.background)
        .onAppear {
            if expanded == nil, let initialTile {
                expanded = initialTile
                vendor = initialTile == .savedContent ? .instagram : .claude
            }
        }
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

    private func tileButton(_ tile: AddSourceTile) -> some View {
        Button {
            error = nil
            result = nil
            expanded = expanded == tile ? nil : tile
            if tile == .savedContent { vendor = .instagram }
            if tile == .chatExport { vendor = .claude }
        } label: {
            VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                Image(systemName: tile.icon)
                    .font(.system(size: 16, weight: .medium))
                    .foregroundStyle(expanded == tile ? CicadaTheme.accent : CicadaTheme.textSecondary)
                Text(tile.title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(CicadaTheme.textPrimary)
                    .lineLimit(1)
                Text(tile.blurb)
                    .font(CicadaTheme.captionFont)
                    .foregroundStyle(CicadaTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(CicadaTheme.spacingMD)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(expanded == tile ? CicadaTheme.accent.opacity(0.12) : CicadaTheme.surfaceElevated)
            )
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(expanded == tile ? CicadaTheme.accent.opacity(0.5) : CicadaTheme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .disabled(busy)
        .accessibilityLabel("\(tile.title). \(tile.blurb)")
    }

    // MARK: - Per-tile flows

    @ViewBuilder
    private func flow(for tile: AddSourceTile) -> some View {
        VStack(alignment: .leading, spacing: CicadaTheme.spacingMD) {
            switch tile {
            case .chatExport:
                WalkthroughPanel(vendor: $vendor) { pickChatExport() }
            case .savedContent:
                WalkthroughPanel(vendor: $vendor) { pickSavedContent() }
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
        panel.message = "Select a Claude, ChatGPT, or Gemini conversation export"
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
