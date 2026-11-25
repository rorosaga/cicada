import Foundation

// G245 — the live ends of `SourceConnect` (plan 7): the snapshot a plan reads, built from the app's own models, and the
// closures that carry a plan out. Kept out of the pure file so its tests need no `AppRouter` and no reading model.

extension SourceConnect.State {
    /// The snapshot for one catalogue row. The caller reads `reading.loadSettings()` first (as every flip does), so the
    /// acknowledgement is the backend's now, never a stale one.
    @MainActor
    init(row: SourceCatalogRow, reading: ReadingAgentModel, siteSavesOn: Set<String>, readersOn: [String: Bool],
         permissions: [MacPermission: Bool] = [:]) {
        self.init(status: row.status, agentEnabled: reading.enabled, ackCurrent: !reading.needsFirstUseSheet,
                  savedListsOn: reading.savedListsOn, siteSavesOn: siteSavesOn, readersOn: readersOn,
                  permissions: permissions)
    }
}

extension SourceConnect.Deps {
    /// The page's, the card's and the notch's one set of closures. `noticeSaves` is the per-Mac flag and the watcher's
    /// refresh (`SiteSavePrefs().setConnected` then `SiteSaveWatcher.refresh`); `startReader` is the reader's own
    /// Connect, which only the app's owner of that reader can call (the readers share no protocol).
    @MainActor
    static func live(reading: ReadingAgentModel, router: AppRouter,
                     noticeSaves: @escaping @MainActor (String) -> Void,
                     startReader: @escaping @MainActor (String) async -> Bool) -> Self {
        SourceConnect.Deps(
            setList: { setting, key, on in await reading.setSwitch(setting: setting, key: key, on: on) },
            noticeSaves: noticeSaves,
            startReader: startReader,
            openPage: { router.routeToCatalogEntry($0) },
            raiseConsent: { router.routeToConsent($0) },
            lastNote: { reading.note },
            acknowledgeList: { setting, key in
                await reading.setSwitch(setting: setting, key: key, on: true, acknowledge: true)
            })
    }
}

/// The Mac readers a click can start — the readers share no protocol (`connect()`, `turnOn()`, `syncNow()`, a watcher's
/// `enable`), so this is the one place that knows which call each one's own Connect makes. The card's Connect and the
/// notch's Yes both run `SourceConnect.Step.startReader` through it; macOS's own permission prompt follows from the
/// reader's own call (never asked here). Answers whether the reader is on afterwards.
@MainActor
struct ReaderStarter {
    var calendar: CalendarReader?
    var contacts: ContactsReader?
    var notes: AppleNotesWatcher?
    var voiceMemos: VoiceMemosReader?
    var books: AppleBooksReader?
    var browsers: BrowserWatcher?

    func start(_ entryId: String) async -> Bool {
        if entryId.hasPrefix(SourceCatalog.browserPrefix) {
            guard let browsers else { return false }
            let installed = await Task.detached(priority: .userInitiated) { BrowserInventory.live() }.value
            guard let channel = installed.supported.first(where: {
                SourceCatalog.browserPrefix + $0.id == entryId })?.bookmarksChannel else { return false }
            browsers.enable(channel)
            return browsers.isEnabled(channel)
        }
        switch entryId {
        case CalendarRow.channelId:
            guard let calendar else { return false }
            await calendar.connect()
            return calendar.isEnabled
        case ContactsReader.channel:
            guard let contacts else { return false }
            await contacts.connect()
            return contacts.enabled
        case AppleNotesWatcher.channel:
            guard let notes else { return false }
            _ = try? await notes.syncNow()
            return notes.enabled
        case VoiceMemosReader.channel:
            guard let voiceMemos else { return false }
            await voiceMemos.turnOn()
            return voiceMemos.enabled
        case AppleBooksReader.channel:
            guard let books else { return false }
            await books.turnOn()
            return books.enabled
        default:
            return false
        }
    }
}
