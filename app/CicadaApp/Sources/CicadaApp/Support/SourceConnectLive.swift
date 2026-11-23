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
            lastNote: { reading.note })
    }
}
