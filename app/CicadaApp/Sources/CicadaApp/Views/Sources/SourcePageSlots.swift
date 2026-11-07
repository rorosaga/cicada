import AppKit
import SwiftUI

// The standard source page's connect area and footer for each source with a reader of its own (owner 2026-11-04;
// `SourcePageLayout`, DESIGN_RULES §9 2026-11-04). Each view draws one slot (`SourceSlot`) from its reader's state:
// one primary and at most one line for the connect area, the quiet actions for the footer. The content slot — the
// lists — is the source's own and is not drawn here.

/// Which of the page's two action slots a source view draws.
enum SourceSlot { case connect, footer }

// MARK: - A browser on this Mac

/// A browser's ways in, one switch each (2026-11-04: the page drew Settings' four rows and a paragraph): its
/// bookmarks, its open tab groups (Chrome), the YouTube it plays (Chrome), and the question asked on a bookmark. The
/// Full Disk Access fix shows where the read failed. Each switch's how is its hover.
struct BrowserWays: View {
    let spec: BrowserSpec
    let inventory: BrowserInventory
    @Environment(BrowserWatcher.self) private var watcher
    @Environment(TabGroupWatcher.self) private var tabGroups: TabGroupWatcher?
    @Environment(WatchHistoryWatcher.self) private var watchHistory: WatchHistoryWatcher?
    @AppStorage(SaveWhyPrefs.enabledKey) private var askWhy = false
    /// `isEnabled` reads this Mac's defaults, which SwiftUI does not observe: a flip redraws through this.
    @State private var flips = 0
    /// Sites the ask-why question was muted on (`SaveWhyPrefs.mutedHosts`), read when the page shows.
    @State private var muted = 0

    private var channel: String { spec.bookmarksChannel ?? spec.id }

    var body: some View {
        let _ = flips
        VStack(alignment: .leading, spacing: CicadaTheme.spacingSM) {
            if watcher.state(for: channel) == .blocked, let error = watcher.error(for: channel) {
                FullDiskAccessHint(error: error)
            }
            SourceConnectArea(ways: ways)
            if spec.id == WatchHistoryWatcher.browser { WatchHistoryState() }
        }
        .onAppear { muted = SaveWhyPrefs(defaults: .standard).mutedHosts.count }
    }

    private var ways: [SourceWayIn] {
        var out: [SourceWayIn] = []
        if spec.bookmarksChannel != nil {
            out.append(SourceWayIn(id: "bookmarks", icon: .mark(spec.origin), title: Copy.SourceLayout.bookmarks,
                                   control: .toggle(watcher.isEnabled(channel)) { on in
                                       if on { watcher.enable(channel) } else { watcher.disable(channel) }
                                       flips += 1
                                   }, help: Copy.SourceLayout.bookmarksHelp(spec.name)))
        }
        if spec.tabGroupsChannel != nil, let tabGroups {
            out.append(SourceWayIn(id: "tab-groups", icon: .symbol("square.stack"), title: Copy.tabGroupsTitle,
                                   control: .toggle(tabGroups.enabled) { on in
                                       if on { Task { await tabGroups.enable() } } else { tabGroups.disable() }
                                   }, help: Copy.tabGroupsSwitch))
        }
        if spec.id == WatchHistoryWatcher.browser, let watchHistory {
            out.append(SourceWayIn(id: "youtube", icon: .mark("youtube-playlist"), title: Copy.SourceLayout.youtubeHere,
                                   control: .toggle(watchHistory.enabled) { on in
                                       if on { Task { await watchHistory.enable() } } else { watchHistory.disable() }
                                   }, help: Copy.watchHistorySwitch))
        }
        if spec.bookmarksChannel != nil {
            out.append(SourceWayIn(id: "ask-why", icon: .symbol("questionmark.bubble"), title: Copy.SaveWhy.switchTitle,
                                   control: .toggle(askWhy) { on in
                                       let prefs = SaveWhyPrefs(defaults: .standard)
                                       if on { SaveWhySetup.turnOn(prefs: prefs, inventory: inventory, watcher: watcher) }
                                       else { prefs.enabled = false }
                                   }, help: Copy.SaveWhy.switchDetail))
        }
        // Review of #593: the sites the question was muted on could only be unmuted from Settings' old row. One quiet
        // row, only while something is muted.
        if BrowserWayRules.showsUnmute(muted: muted, hasBookmarks: spec.bookmarksChannel != nil) {
            out.append(SourceWayIn(id: "muted", icon: .symbol("speaker.slash"), title: Copy.SaveWhy.mutedLine(muted),
                                   control: .button(Copy.SaveWhy.unmuteAll) {
                                       SaveWhyPrefs(defaults: .standard).mutedHosts = []
                                       muted = 0
                                   }))
        }
        return out
    }
}

/// The browser page's pure rules (review of #593).
enum BrowserWayRules {
    /// "Unmute all" shows only on a browser whose bookmarks are read, and only while a site is muted.
    static func showsUnmute(muted: Int, hasBookmarks: Bool) -> Bool { hasBookmarks && muted > 0 }
}

/// What the YouTube watch-history reader is doing, said where its switch is (review of #593: the Settings row it
/// replaced showed a failed read and offered to stop a running one; the page said nothing).
enum WatchHistoryLine: Equatable {
    case none
    /// A read is running: its own words, and Stop when it can be stopped.
    case reading(String, cancellable: Bool)
    /// The read failed: the reader's own words, which carry their fix.
    case failed(String)

    static func of(enabled: Bool, status: WatchHistoryWatcher.Status, run: SyncActivity.Run?) -> WatchHistoryLine {
        if let run { return .reading(run.detail ?? Copy.watchHistoryReading, cancellable: run.cancellable) }
        guard enabled else { return .none }
        if case .failed(let why) = status { return .failed(why) }
        return .none
    }
}

/// The YouTube watch-history reader's state under its switch: a running read with Stop, or a failure — Full Disk
/// Access's exact fix when that is what failed, else the reader's words as the area's attention line.
struct WatchHistoryState: View {
    @Environment(WatchHistoryWatcher.self) private var watcher: WatchHistoryWatcher?
    @Environment(SyncActivity.self) private var activity: SyncActivity?

    var body: some View {
        if let watcher {
            switch WatchHistoryLine.of(enabled: watcher.enabled, status: watcher.status,
                                       run: activity?.run(for: WatchHistoryWatcher.channel)) {
            case .none:
                EmptyView()
            case .reading(let words, let cancellable):
                HStack(spacing: CicadaTheme.spacingSM) {
                    ProgressView().controlSize(.small)
                    SourceConnectLine(text: words)
                    if cancellable {
                        TextButton(title: Copy.stopSyncing, help: Copy.stopSyncingHelp) {
                            activity?.cancel(WatchHistoryWatcher.channel)
                        }
                    }
                    Spacer(minLength: 0)
                }
            case .failed(let why):
                if let error = watcher.failure, case .notReadable = error {
                    FullDiskAccessHint(error: error) { Task { _ = try? await watcher.syncNow() } }
                } else {
                    SourceConnectLine(text: why, isAttention: true)
                }
            }
        }
    }
}

/// G197 — one app's "request your export" on the chat-exports page: its real mark, its name, and its export page;
/// what the export holds and the steps are the row's hover.
enum ChatExportWay {
    static func of(_ vendor: ChatVendor) -> SourceWayIn {
        SourceWayIn(id: "export-\(vendor.rawValue)", icon: .mark(vendor.origin),
                    title: Copy.SourceLayout.requestExport(vendor.title),
                    control: .button(Copy.intakeOpenExportPage) { NSWorkspace.shared.open(vendor.walkthrough.exportURL) },
                    help: ([vendor.walkthrough.summary] + vendor.walkthrough.steps).joined(separator: " "))
    }
}

// MARK: - This Mac: Calendar, Contacts, Reminders, Apple Notes

/// Calendar on this Mac: Connect (the system prompt); refused, the privacy setting; on, Refresh and Disconnect.
struct CalendarSlot: View {
    let slot: SourceSlot
    @Environment(CalendarReader.self) private var reader

    var body: some View {
        switch slot {
        case .connect:
            switch reader.status {
            case .off:
                SourceConnectArea(primary: SourcePrimaryAction(title: Copy.Catalog.connectCalendar) {
                    Task { await reader.connect() }
                })
            case .denied:
                SourceConnectArea(primary: SourcePrimaryAction(title: Copy.openPrivacySettings) {
                    NSWorkspace.shared.open(CalendarRow.privacyURL)
                }, line: Copy.calendarDenied, lineIsAttention: true)
            case .failed(let why):
                SourceConnectArea(line: why, lineIsAttention: true)
            case .syncing, .synced:
                EmptyView()
            }
        case .footer:
            switch reader.status {
            case .off, .denied: EmptyView()
            case .syncing, .synced, .failed:
                SourcePageFooter(actions: [
                    .refresh(isDisabled: reader.status == .syncing) { Task { await reader.syncNow() } },
                    .disconnect("Calendar", message: Copy.calendarStopDetail) { reader.disconnect() },
                ])
            }
        }
    }
}

struct ContactsSlot: View {
    let slot: SourceSlot
    @Environment(ContactsReader.self) private var reader

    var body: some View {
        switch slot {
        case .connect:
            switch reader.status {
            case .off:
                SourceConnectArea(primary: SourcePrimaryAction(title: Copy.Catalog.connectContacts) {
                    Task { await reader.connect() }
                })
            case .denied:
                SourceConnectArea(primary: SourcePrimaryAction(title: Copy.openPrivacySettings) {
                    NSWorkspace.shared.open(ContactsRow.privacyURL)
                }, line: Copy.contactsDenied, lineIsAttention: true)
            case .failed(let why):
                SourceConnectArea(line: why, lineIsAttention: true)
            case .syncing, .watching, .empty:
                EmptyView()
            }
        case .footer:
            switch reader.status {
            case .off, .denied: EmptyView()
            case .syncing, .watching, .empty, .failed:
                SourcePageFooter(actions: [
                    .refresh(isDisabled: reader.status == .syncing) { Task { await reader.syncNow() } },
                    .disconnect("Contacts", message: Copy.contactsStopDetail) { reader.disconnect() },
                ])
            }
        }
    }
}

struct RemindersSlot: View {
    let slot: SourceSlot
    @Environment(RemindersReader.self) private var reader

    var body: some View {
        switch slot {
        case .connect:
            switch reader.status {
            case .off:
                SourceConnectArea(primary: SourcePrimaryAction(title: Copy.Catalog.connectReminders) {
                    Task { await reader.connect() }
                })
            case .denied:
                SourceConnectArea(primary: SourcePrimaryAction(title: Copy.openPrivacySettings) {
                    NSWorkspace.shared.open(RemindersRow.privacyURL)
                }, line: Copy.remindersDenied, lineIsAttention: true)
            case .failed(let why):
                SourceConnectArea(line: why, lineIsAttention: true)
            case .noLists, .syncing, .synced:
                EmptyView()
            }
        case .footer:
            if reader.enabled, reader.status != .denied {
                SourcePageFooter(actions: [
                    .refresh(isDisabled: reader.status == .syncing || reader.ticked.isEmpty) {
                        Task { await reader.syncNow() }
                    },
                    .disconnect(Copy.remindersTitle, message: Copy.remindersStopDetail) { reader.disconnect() },
                ])
            }
        }
    }
}

/// Apple Notes: Connect reads every folder once (the one Automation prompt) and keeps up; on, Refresh and Disconnect.
struct NotesSlot: View {
    let slot: SourceSlot
    @Environment(AppleNotesWatcher.self) private var notes
    @Environment(Store.self) private var store
    @State private var busy = false
    @State private var note: String?

    var body: some View {
        switch slot {
        case .connect:
            if !notes.enabled {
                SourceConnectArea(primary: SourcePrimaryAction(title: Copy.Catalog.connectNotes, isDisabled: busy) {
                    read()
                }, line: note ?? failure, lineIsAttention: failure != nil && note == nil)
            } else if let failure {
                SourceConnectArea(line: failure, lineIsAttention: true)
            }
        case .footer:
            if notes.enabled {
                SourcePageFooter(actions: [
                    .refresh(isDisabled: busy) { read() },
                    .disconnect("Apple Notes") {
                        notes.disconnect()
                        note = nil
                    },
                ], note: note)
            }
        }
    }

    private var failure: String? {
        if case .failed(let why) = notes.status { return why }
        return nil
    }

    private func read() {
        Task {
            busy = true
            defer { busy = false }
            do {
                let r = try await notes.syncNow()
                note = Copy.SourceLayout.notesRead(new: r.new, unchanged: r.skipped)
                await store.refresh([.channels, .status, .sources])
            } catch {
                note = AddSourceSheet.friendlyError(error)
            }
        }
    }
}

// MARK: - Meeting recorders and folders

/// A folder source (Folders, Hex, a folder of transcripts): "Add a folder" is the one primary while none is
/// watched, then a quiet footer action.
struct FolderSlot: View {
    let slot: SourceSlot
    /// Nil: any folder (Folders); "hex" or "" — a meeting folder, Hex's own or any recorder's.
    let meetings: String?
    let hasFolders: Bool
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var picked: PickedFolder?
    @State private var refused: String?
    /// Where Hex says it saves meetings (`LocalSourceWatcher.hexMeetingsFolder`); never checked before the click.
    @State private var hexFolder: URL?
    @State private var connecting = false

    private var title: String {
        meetings == SourceCatalog.hexId ? Copy.Catalog.addHexFolder : Copy.Catalog.addFolder
    }

    var body: some View {
        Group {
            switch slot {
            case .connect:
                if !hasFolders, meetings == SourceCatalog.hexId {
                    hexConnect
                } else if !hasFolders {
                    SourceConnectArea(primary: SourcePrimaryAction(title: title, systemImage: "folder.badge.plus",
                                                                   help: help) { pick() },
                                      line: refused, lineIsAttention: refused != nil)
                } else if let refused {
                    SourceConnectArea(line: refused, lineIsAttention: true)
                }
            case .footer:
                if hasFolders {
                    SourcePageFooter(actions: [SourceFooterAction(id: "add", title: title, help: help) { pick() }])
                }
            }
        }
        .sheet(item: $picked) { picked in
            if let meetings {
                AddMeetingFolderSheet(url: picked.url, recorder: meetings.isEmpty ? nil : meetings) { self.picked = nil }
            } else {
                AddFolderSheet(url: picked.url) { self.picked = nil }
            }
        }
    }

    /// Hex in one click (owner 2026-11-04). Opening this page never touches the folder: Hex's default sits under
    /// Documents, so whether it is there is asked only on the person's click, by *Connect Hex*. Its path is the hover,
    /// from Hex's own setting.
    private var hexConnect: some View {
        SourceConnectArea(
            primary: SourcePrimaryAction(title: Copy.SourceBrowser.hexConnect, help: hexFolder.map(HexConnectText.display),
                                         isDisabled: connecting) { Task { await connectHex() } },
            line: refused, lineIsAttention: refused != nil,
            ways: [SourceWayIn(id: "other", icon: .symbol("folder"), title: Copy.SourceBrowser.otherFolder,
                               control: .button(Copy.SourceLayout.choose) { pick() }, help: help)])
            .task { hexFolder = LocalSourceWatcher.hexMeetingsFolder() }
    }

    private func connectHex() async {
        connecting = true
        defer { connecting = false }
        do {
            try await localSources.connectHexFolder()
            refused = nil
        } catch FolderWatchError.missing {
            refused = Copy.SourceBrowser.hexNoFolder
        } catch {
            refused = AddSourceSheet.friendlyError(error)
        }
    }

    private var help: String {
        switch meetings {
        case nil: Copy.SearchFiles.addFolderPanel
        case SourceCatalog.hexId?: Copy.Catalog.hexHow
        default: Copy.Catalog.meetingFolderHow
        }
    }

    private func pick() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = help
        panel.prompt = "Choose"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        refused = nil
        // A watched folder's bytes are posted on every change, so a folder under a refused root is never watched.
        if let refusal = IntakeRouter.refusedRoot(of: [url]) {
            refused = refusal.panelText
            return
        }
        picked = PickedFolder(url: url)
    }
}

/// Wispr Flow: Connect opens its panel (turning it on, dictation opt-in); on, Refresh and Manage.
struct WisprSlot: View {
    let slot: SourceSlot
    /// The app was removed from this Mac: the status line says "Off · not installed" and there is nothing to connect.
    var notInstalled = false
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var showPanel = false

    var body: some View {
        Group {
            switch slot {
            case .connect:
                if notInstalled {
                    EmptyView()
                } else if !localSources.wisprSettings.enabled {
                    SourceConnectArea(primary: SourcePrimaryAction(title: Copy.SourceLayout.connect("Wispr Flow")) {
                        showPanel = true
                    })
                } else if let error = localSources.wisprError, case .notReadable = error {
                    FullDiskAccessHint(error: error)
                }
            case .footer:
                if localSources.wisprSettings.enabled, !notInstalled {
                    SourcePageFooter(actions: [
                        .refresh(isDisabled: localSources.syncing.contains(LocalSourceWatcher.wisprChannel)) {
                            Task { await localSources.syncWisprNow() }
                        },
                        SourceFooterAction(id: "manage", title: Copy.Catalog.manage) { showPanel = true },
                    ])
                }
            }
        }
        .sheet(isPresented: $showPanel) { WisprFlowPanel { showPanel = false } }
    }
}

// MARK: - Chats: Messages, WhatsApp, Telegram

/// A chat source on this Mac (Messages, WhatsApp): "Choose chats" is the one primary until a chat is ticked; then the
/// footer holds Choose chats… and Refresh. A missing permission shows its exact fix where the read failed.
struct ChatPickerSlot: View {
    enum Kind { case messages, whatsApp }
    let slot: SourceSlot
    let kind: Kind
    @Environment(MessagesWatcher.self) private var messages: MessagesWatcher?
    @Environment(WhatsAppWatcher.self) private var whatsApp: WhatsAppWatcher?
    @State private var showPanel = false
    @State private var note: String?

    private var ticked: Bool {
        switch kind {
        case .messages: !(messages?.tickedIds.isEmpty ?? true)
        case .whatsApp: !(whatsApp?.tickedIds.isEmpty ?? true)
        }
    }

    private var syncing: Bool {
        switch kind {
        case .messages: messages?.status == .syncing
        case .whatsApp: whatsApp?.status == .syncing
        }
    }

    private var needsAccess: BrowserFileError? {
        switch kind {
        case .messages: if case .needsAccess(let e)? = messages?.status { return e }
        case .whatsApp: if case .needsAccess(let e)? = whatsApp?.status { return e }
        }
        return nil
    }

    private var problem: String? {
        switch kind {
        case .messages:
            if case .failed(let why)? = messages?.status { return why }
            if case .missing? = messages?.status { return Copy.Messages.noneFound }
        case .whatsApp:
            if case .failed(let why)? = whatsApp?.status { return why }
            if case .missing? = whatsApp?.status { return Copy.Chats.whatsAppMissing }
        }
        return nil
    }

    var body: some View {
        Group {
            switch slot {
            case .connect:
                if let needsAccess {
                    FullDiskAccessHint(error: needsAccess)
                } else if !ticked {
                    SourceConnectArea(primary: SourcePrimaryAction(title: Copy.Catalog.chooseChats) { showPanel = true },
                                      line: problem, lineIsAttention: problem != nil)
                } else if let problem {
                    SourceConnectArea(line: problem, lineIsAttention: true)
                }
            case .footer:
                if ticked {
                    SourcePageFooter(actions: [
                        SourceFooterAction(id: "choose", title: Copy.SourceLayout.chooseChats) { showPanel = true },
                        .refresh(isDisabled: syncing) { refresh() },
                    ], note: note)
                }
            }
        }
        .sheet(isPresented: $showPanel) {
            switch kind {
            case .messages: MessagesPanel { showPanel = false }
            case .whatsApp: WhatsAppPanel { showPanel = false }
            }
        }
    }

    private func refresh() {
        Task {
            switch kind {
            case .messages: note = (try? await messages?.syncNow()) ?? nil
            case .whatsApp: note = (try? await whatsApp?.syncNow()) ?? nil
            }
        }
    }
}

/// Telegram (ruling 47a): Connect opens the sign-in sheet (the QR first); connected, the footer holds Choose chats… and
/// Disconnect; a session Telegram ended reads as the one thing to fix.
struct TelegramSlot: View {
    let slot: SourceSlot
    @Environment(TelegramChats.self) private var model
    @State private var showPanel = false

    var body: some View {
        Group {
            switch slot {
            case .connect:
                if model.status.state == "ended" {
                    SourceConnectArea(primary: SourcePrimaryAction(title: Copy.SourceLayout.reconnect) { showPanel = true },
                                      line: model.status.error ?? Copy.Chats.sessionEnded, lineIsAttention: true)
                } else if !model.connected {
                    SourceConnectArea(primary: SourcePrimaryAction(title: Copy.SourceLayout.connect("Telegram"),
                                                                   help: Copy.Chats.connectHelp) { showPanel = true })
                } else if model.tickedIds.isEmpty {
                    SourceConnectArea(primary: SourcePrimaryAction(title: Copy.Catalog.chooseChats) { showPanel = true })
                }
            case .footer:
                if model.connected {
                    SourcePageFooter(actions: [
                        SourceFooterAction(id: "choose", title: Copy.SourceLayout.chooseChats) { showPanel = true },
                        .disconnect("Telegram") { Task { await model.disconnect() } },
                    ])
                }
            }
        }
        .sheet(isPresented: $showPanel) { TelegramPanel { showPanel = false } }
        // The page draws this slot twice (connect and footer): only the connect area reads Telegram's state.
        .task { if slot == .connect { await model.refresh() } }
    }
}

// MARK: - Accounts connected through a connector (X, Reddit, Pinterest, Notion)

/// A connector account: Connect opens the connector's own panel in a sheet (its sign-in or token, one step at a time);
/// connected, the footer holds Refresh and Disconnect; a lapsed sign-in is the one thing to fix.
struct ConnectorSlot: View {
    let slot: SourceSlot
    let channel: SourceChannel
    let title: String
    var ways: [SourceWayIn] = []
    var vendors: [WalkthroughVendor] = []
    let needsSignIn: Bool
    /// ROR-118 round 4 — when a site's own way in (its list read through the person's AI app) leads, that is the one
    /// primary and the account connection becomes a way below it.
    var primaryOverride: SourcePrimaryAction? = nil

    @Environment(Store.self) private var store
    @Environment(LocalSourceWatcher.self) private var localSources
    @State private var showPanel = false
    @State private var vendor: WalkthroughVendor = .claude
    @State private var busy = false
    @State private var note: String?

    var body: some View {
        Group {
            switch slot {
            case .connect:
                if needsSignIn {
                    SourceConnectArea(primary: SourcePrimaryAction(title: Copy.SourceLayout.reconnect) { showPanel = true },
                                      line: channel.lastError, lineIsAttention: true, ways: ways)
                } else if !channel.connected, let lead = primaryOverride {
                    SourceConnectArea(primary: lead, ways: [
                        SourceWayIn(id: "account", icon: .symbol("person.crop.circle"),
                                    title: Copy.SourceLayout.useAccount(title),
                                    control: .button(Copy.SourceLayout.connectShort) { showPanel = true }),
                    ] + ways)
                } else if !channel.connected {
                    SourceConnectArea(primary: SourcePrimaryAction(title: Copy.SourceLayout.connect(title)) {
                        showPanel = true
                    }, ways: ways)
                } else {
                    SourceConnectArea(line: channel.lastError, lineIsAttention: channel.lastError != nil, ways: ways)
                }
            case .footer:
                if channel.connected {
                    SourcePageFooter(actions: [
                        .refresh(isDisabled: busy) { refresh() },
                        .disconnect(title) { disconnect() },
                    ], note: note)
                }
            }
        }
        .sheet(isPresented: $showPanel) {
            SettingsSheet(title: title, onClose: { showPanel = false }) {
                ConnectorSetupPanel(connectorId: channel.id, vendors: vendors, vendor: $vendor)
            }
        }
    }

    private func refresh() {
        Task {
            busy = true
            defer { busy = false }
            do { note = try await ChannelActions.sync(channel.id, store: store, local: localSources) }
            catch { note = AddSourceSheet.friendlyError(error) }
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
        }
    }

    private func disconnect() {
        Task {
            busy = true
            defer { busy = false }
            do { _ = try await APIClient.shared.forgetConnector(channel.id); note = nil }
            catch { note = AddSourceSheet.friendlyError(error) }
            await store.refresh([.channels, .sources, .sourcesOverview, .status])
        }
    }
}
