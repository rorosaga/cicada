import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// The Capture page's "+" picker (G62). Three levels (2026-09-02 brief):
/// a logo-first grid of `ImportFamily` tiles, each opening into its member
/// tiles, each opening into that channel's flow inline. **All** explanatory
/// copy about capture lives here — the page behind it shows only what is
/// already connected, so this sheet is the single place a user learns what
/// Cicada can read.
///
/// "Manage…" from a connected row opens this sheet already expanded on that
/// channel's tile (`initialTile:`), where feeds and calendars show their
/// current rows with remove buttons. The tile — not the family — stays the
/// identity every channel maps to (R6).
enum AddSourceTile: String, CaseIterable, Identifiable {
    case chatExport, bookmarksFile, pasteLink, rssFeed, calendar
    // R6 — one tile per browser (was a combined `browserBookmarks`): the
    // catalog gives every browser its own mark, and a channel must map to
    // exactly one tile, so a shared "Chrome & Safari" row could no longer
    // own the split `chrome-bookmarks` / `safari-bookmarks` channels (R4).
    case safari, chrome, appleNotes, telegram
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
        case .safari, .chrome, .appleNotes: return .sync
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
        case .safari: "Safari"
        case .chrome: "Chrome"
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
        case .safari: "Bookmarks by folder, Reading List, and every tab open on your iPhone."
        case .chrome: "Bookmarks by folder, read straight off this Mac."
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
        case .safari: "safari"
        case .chrome: "globe"
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
    /// Safari likewise owns both of its rows (`safari-bookmarks`,
    /// `safari-tabs`): its panel is where the user picks bookmarks or
    /// iCloud tabs, so "Manage…" on either row lands on the same tile (R4).
    /// `pasteLink` owns none: it is an alternative route into `files`, which
    /// `bookmarksFile` already claims. The four Import-file platform tiles
    /// (Instagram, YouTube, TikTok, LinkedIn) also own none — none of them
    /// has a persisted backend channel yet — and a channel must map back to
    /// exactly one tile for "Manage…" to be unambiguous. The legacy combined
    /// `bookmarks` id is a backend read-time fallback only and is claimed
    /// by no tile.
    var channelIds: [String] {
        switch self {
        case .chatExport: ["chat-export:claude", "chat-export:chatgpt"]
        case .bookmarksFile: ["files"]
        case .pasteLink: []
        case .rssFeed: ["rss"]
        case .calendar: ["calendar"]
        case .safari: ["safari-bookmarks", "safari-tabs"]
        case .chrome: ["chrome-bookmarks"]
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
    /// row with no single brand mark (Apple Notes, RSS, Calendar all kept
    /// their SF Symbol — no sensible single logo exists for any of them).
    /// Safari and Chrome are `nil` too: their marks are DRAWN (R7 —
    /// `brandGlyph`, Task 4), not downloaded; the owner can drop
    /// `Resources/logos/safari.png` / `chrome.png` in and flip these two to
    /// prefer the PNG.
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
             .safari, .chrome, .appleNotes:
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

    /// Which of the three levels is showing (2026-09-02 brief, R6):
    /// `families → members → flow`. The old `expanded: AddSourceTile?` is
    /// now the computed projection below so every flow keeps compiling
    /// unchanged — a flow is still keyed on the leaf tile, never a family.
    @State private var level: CatalogLevel = .families
    /// Keyboard focus within the current grid (R10). Re-minted on every
    /// level change with that grid's count, and restored to the tile the
    /// user came from on the way back so Esc lands where they left.
    @State private var focus = CatalogFocus(index: 0, columns: 3, count: ImportFamily.allCases.count)
    /// Whether the grid itself holds keyboard focus. The focus ring on a
    /// tile is drawn only while this is true, so the ring is never a lie —
    /// if the arrows would not move anything, nothing is highlighted.
    @FocusState private var gridFocused: Bool
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
    /// H1): a bare, unstored `Task {}` keeps running after `back()`, and
    /// its late response would otherwise overwrite whichever flow the user
    /// has since opened.
    @State private var importTask: Task<Void, Never>?
    /// Bumped every time `preview()`/`confirmImport()` starts a new request
    /// and every time `back()` tears one down. A response is only ever
    /// applied to `stage` if its captured generation still matches this one
    /// — belt-and-suspenders alongside `importTask` cancellation for the
    /// case where cancellation doesn't land before the response does.
    @State private var importGeneration = 0

    private var feeds: [FeedSubscription] { store.feeds.value ?? [] }
    private var calendars: [CalendarSubscription] { store.calendars.value ?? [] }

    /// The leaf tile whose flow is open, if any — the shape every flow and
    /// action below was written against before the family layer existed.
    private var expanded: AddSourceTile? {
        if case .flow(let tile) = level { return tile }
        return nil
    }

    /// Fixed three columns at both grid levels. `.adaptive(minimum: 190)`
    /// gave four cramped columns at 640 pt and forced `lineLimit(1)` on the
    /// titles; `CatalogFocus` is minted with the same width so arrow-down
    /// lands on the tile visually below.
    private static let columnCount = 3
    private static let columns = Array(
        repeating: GridItem(.flexible(), spacing: CicadaTheme.spacingMD),
        count: columnCount
    )

    /// What Esc does. Backing out one level before closing the sheet means
    /// one keypress can't discard both a half-typed URL and the sheet — and
    /// with three levels that is one step each: `flow → members →
    /// families → close`.
    enum EscapeAction: Equatable { case back, close }

    static func escapeAction(level: CatalogLevel) -> EscapeAction {
        if case .families = level { return .close }
        return .back
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider().background(CicadaTheme.border)
            ScrollView {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingLG) {
                    // One level at a time, each with its own back control.
                    // The grid + an expanded flow together pushed the action
                    // buttons below the fold on a 620 pt sheet.
                    switch level {
                    case .families:
                        LazyVGrid(columns: Self.columns, spacing: CicadaTheme.spacingMD) {
                            ForEach(Array(ImportFamily.allCases.enumerated()), id: \.element.id) { i, family in
                                familyTile(family, focused: gridFocused && focus.index == i)
                            }
                        }
                    case .members(let family):
                        backControl(parent: "All sources", title: family.title)
                        LazyVGrid(columns: Self.columns, spacing: CicadaTheme.spacingMD) {
                            ForEach(Array(family.members.enumerated()), id: \.element.id) { i, tile in
                                memberTile(tile, focused: gridFocused && focus.index == i)
                            }
                        }
                    case .flow(let tile):
                        backControl(parent: ImportFamily.forTile(tile).title, title: tile.title)
                        flow(for: tile)
                    }
                    statusLine
                }
                .padding(CicadaTheme.spacingXL)
            }
            // R10 — the grid takes keyboard focus so arrows and Enter drive
            // it; the system ring is suppressed because each tile draws its
            // own accent ring for the focused index. Every handler yields
            // `.ignored` inside a flow so a text field there keeps its own
            // arrows and Enter (`textFlow`'s `.onSubmit`).
            .focusable()
            .focusEffectDisabled()
            .focused($gridFocused)
            .onKeyPress(.upArrow) { moveFocus(.up) }
            .onKeyPress(.downArrow) { moveFocus(.down) }
            .onKeyPress(.leftArrow) { moveFocus(.left) }
            .onKeyPress(.rightArrow) { moveFocus(.right) }
            .onKeyPress(.return) { activateFocused() }
        }
        .frame(width: 640, height: 620)
        .background(CicadaTheme.background)
        .onAppear {
            if expanded == nil, let initialTile {
                open(initialTile)
            } else {
                gridFocused = true
            }
        }
        .onKeyPress(.escape) {
            switch Self.escapeAction(level: level) {
            case .back: back()
            case .close: onClose()
            }
            return .handled
        }
    }

    /// Breadcrumb for the two inner levels: the back button is labelled with
    /// the level it returns to (`‹ All sources` at members, `‹ Browsers` at
    /// a flow) so where Esc lands is visible before it is pressed, and the
    /// heading is the current level's own title.
    private func backControl(parent: String, title: String) -> some View {
        HStack(spacing: CicadaTheme.spacingSM) {
            Button(action: back) {
                HStack(spacing: CicadaTheme.spacingXS) {
                    Image(systemName: "chevron.left").font(CicadaTheme.font(size: 11, weight: .semibold))
                    Text(parent).font(CicadaTheme.font(size: 12, weight: .medium))
                }
                .foregroundStyle(CicadaTheme.textSecondary)
            }
            .buttonStyle(.cicadaPlain)
            .accessibilityLabel("Back to \(parent)")

            Text(title)
                .font(CicadaTheme.headingFont)
                .foregroundStyle(CicadaTheme.textPrimary)
            Spacer()
        }
    }

    // MARK: - Levels

    /// Families → members. Focus restarts at the first member; the grid
    /// keeps keyboard focus so a second Enter opens that member.
    private func openFamily(_ family: ImportFamily) {
        error = nil
        result = nil
        level = .members(family)
        focus = CatalogFocus(index: 0, columns: Self.columnCount, count: family.members.count)
        gridFocused = true
    }

    /// Opening a tile resets the transient status AND pins the vendor picker
    /// to a vendor this tile actually offers. Also the landing for
    /// `initialTile` ("Manage…" from a connected row): it goes straight to
    /// the flow, and `back()` from there lands on the tile's family.
    private func open(_ tile: AddSourceTile) {
        error = nil
        result = nil
        level = .flow(tile)
        if let first = tile.vendors.first { vendor = first }
        // L5 (final review): `includeHistory` was never reset, so a TikTok
        // import's "Also import browsing history" toggle silently persisted
        // into a LATER Instagram/YouTube import — inert there today (only
        // TikTok reads it), but still wrong state to carry across tiles.
        includeHistory = false
    }

    /// One level back, restoring focus to the tile the user came from so
    /// Esc-then-Enter reopens it. Leaving a flow tears the flow down exactly
    /// as the old `collapse()` did; leaving the members level only clears
    /// the transient status.
    private func back() {
        error = nil
        result = nil
        switch level {
        case .families:
            return
        case .members(let family):
            level = .families
            focus = CatalogFocus(index: ImportFamily.allCases.firstIndex(of: family) ?? 0,
                                 columns: Self.columnCount, count: ImportFamily.allCases.count)
        case .flow(let tile):
            let family = ImportFamily.forTile(tile)
            level = .members(family)
            focus = CatalogFocus(index: family.members.firstIndex(of: tile) ?? 0,
                                 columns: Self.columnCount, count: family.members.count)
            stage = .idle
            // H1: cancel the in-flight request AND bump the generation, so a
            // response already past its cancellation checkpoint still can't
            // land on the next flow's `stage`.
            importTask?.cancel()
            importTask = nil
            importGeneration += 1
        }
        gridFocused = true
    }

    private func moveFocus(_ direction: CatalogFocus.Direction) -> KeyPress.Result {
        if case .flow = level { return .ignored }
        focus = focus.moved(direction)
        return .handled
    }

    /// Enter on the focused tile. Bounds-checked against the CURRENT grid
    /// rather than trusting `focus.count`, so a stale focus can never index
    /// past a shorter members list.
    private func activateFocused() -> KeyPress.Result {
        switch level {
        case .flow:
            return .ignored
        case .families:
            let families = ImportFamily.allCases
            guard families.indices.contains(focus.index) else { return .ignored }
            openFamily(families[focus.index])
        case .members(let family):
            guard family.members.indices.contains(focus.index) else { return .ignored }
            open(family.members[focus.index])
        }
        return .handled
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

    // MARK: - Tiles

    /// The card chrome both grid levels share: elevated fill, hairline
    /// border, and a 2 pt accent ring while this tile is the keyboard
    /// focus (R10). Only the ring varies, so a family and a member read as
    /// the same kind of thing at two depths.
    private func tileCard<Content: View>(focused: Bool, @ViewBuilder content: () -> Content) -> some View {
        content()
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(CicadaTheme.spacingMD)
            .background(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .fill(CicadaTheme.surfaceElevated)
            )
            .overlay(
                RoundedRectangle(cornerRadius: CicadaTheme.cornerRadiusSmall)
                    .stroke(focused ? CicadaTheme.accent : CicadaTheme.border, lineWidth: focused ? 2 : 1)
            )
    }

    /// A top-level family tile (2026-09-02 brief): its members' marks in a
    /// cluster, the family title and blurb, and an honest footer counting
    /// how many of its members are live — derived from the same
    /// `tileState` each member renders, so the family can never claim a
    /// connection its members don't show.
    private func familyTile(_ family: ImportFamily, focused: Bool) -> some View {
        let channels = store.channels.value ?? []
        let connected = family.members.filter { AddSourceTile.tileState($0, channels: channels).connected }.count
        let total = family.members.count
        let footer = connected > 0 ? "\(connected) of \(total) connected" : "\(total) source\(total == 1 ? "" : "s")"
        return Button {
            openFamily(family)
        } label: {
            tileCard(focused: focused) {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    FamilyMarkCluster(family: family)
                    Text(family.title)
                        .font(CicadaTheme.font(size: 12, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(family.blurb)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(footer)
                        .font(CicadaTheme.font(size: 10, weight: .semibold))
                        .foregroundStyle(connected > 0 ? CicadaTheme.success : CicadaTheme.textTertiary)
                }
            }
        }
        .buttonStyle(.cicadaPlain)
        .disabled(busy)
        .accessibilityLabel("\(family.title). \(family.blurb) \(footer).")
    }

    /// G71 §4.1 — every member tile carries a route badge (Connect / Import
    /// file / Sync / Subscribe / Save) and, once the channel is live, the
    /// channel's own detail line in place of the static blurb. Between them
    /// sits every way in (`routeLines`) so "folders" and "tabs" are visible
    /// before the tile opens.
    private func memberTile(_ tile: AddSourceTile, focused: Bool) -> some View {
        let state = AddSourceTile.tileState(tile, channels: store.channels.value ?? [])
        let routes = tile.routeLines.joined(separator: " · ")
        return Button {
            open(tile)
        } label: {
            tileCard(focused: focused) {
                VStack(alignment: .leading, spacing: CicadaTheme.spacingXS) {
                    MemberMark(tile: tile, size: 32)
                    Text(tile.title)
                        .font(CicadaTheme.font(size: 12, weight: .semibold))
                        .foregroundStyle(CicadaTheme.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(state.detail ?? tile.blurb)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(routes)
                        .font(CicadaTheme.captionFont)
                        .foregroundStyle(CicadaTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(state.badge)
                        .font(CicadaTheme.font(size: 10, weight: .semibold))
                        .foregroundStyle(state.connected ? CicadaTheme.success : CicadaTheme.textTertiary)
                }
            }
        }
        .buttonStyle(.cicadaPlain)
        .disabled(busy)
        .accessibilityLabel("\(tile.title). \(state.badge). \(state.detail ?? tile.blurb) \(routes).")
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
            // R1 — the panels read the browser files themselves and POST the
            // bytes; the sheet's old "Sync now" sent nothing and left the
            // launchd backend (no Full Disk Access) to silently sync nothing.
            case .safari:
                SafariImportPanel()
            case .chrome:
                BookmarkFolderPanel(browser: .chrome)
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
    /// `stage`, whether it lands after `back()` or after a newer drop on
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
