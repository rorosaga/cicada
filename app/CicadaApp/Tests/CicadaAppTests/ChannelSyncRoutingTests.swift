import XCTest
@testable import CicadaApp

/// L final review (finding 1): "Sync now" on a folder or Wispr Flow row, from
/// the Sources card, the source page or the Feed strip, went to
/// `BrowserImportActions.syncChannel` and threw "Unknown channel folder:…" —
/// only the Integrations rows reached `LocalSourceWatcher`. `notes` and the
/// three connectors fell through the same `default:`. One routing table now
/// answers every id, and this file holds it to the registry.
@MainActor
final class ChannelSyncRoutingTests: XCTestCase {

    /// Every channel id `api/services/channel_registry.py::build_channels` can
    /// emit with the `sync` action. Mirrored — deliberately, byte for byte — by
    /// `api/tests/test_folder_source.py::APP_SYNC_ROUTED`, which builds
    /// the real registry and fails when a new `sync` row appears that is not in
    /// its list; add the id to both, and a route here.
    static let registrySyncIds = [
        "chrome-bookmarks", "safari-bookmarks", "safari-tabs", "notes",
        "pinterest", "reddit", "x",
        "folder:alpha-project-1a2b3c", "wispr-flow",
        "calendar-local",
    ]

    func testEverySyncIdTheRegistryEmitsHasAHandler() {
        for id in Self.registrySyncIds {
            XCTAssertNotNil(ChannelActions.syncRoute(for: id), "no Sync now handler for \(id)")
        }
    }

    func testLocalSourcesRouteToTheWatcherNotTheBrowserReader() {
        XCTAssertEqual(ChannelActions.syncRoute(for: "folder:alpha-project-1a2b3c"),
                       .folder(id: "alpha-project-1a2b3c"))
        XCTAssertEqual(ChannelActions.syncRoute(for: LocalSourceWatcher.wisprChannel), .wisprFlow)
        XCTAssertEqual(ChannelActions.syncRoute(for: "safari-tabs"), .browserFile)
        XCTAssertEqual(ChannelActions.syncRoute(for: "notes"), .notes)
        XCTAssertEqual(ChannelActions.syncRoute(for: "reddit"), .connector)
        XCTAssertEqual(ChannelActions.syncRoute(for: "calendar-local"), .calendarLocal,
                       "Sync now on the Calendar card runs the app's EventKit reader (G142)")
        XCTAssertNil(ChannelActions.syncRoute(for: "folder:"), "an empty folder id is not a folder")
        XCTAssertNil(ChannelActions.syncRoute(for: "rss"), "rss polls; it has no sync")
    }

    /// The Feed strip's "Manage…" for a folder used to call
    /// `AddSourceTile.forChannel`, get nil, and open the generic add-source
    /// sheet. The row is now the Integrations link, so the menu drops the item a
    /// closure could not honour.
    func testALocalSourceRowManagesInIntegrations() {
        let folder = SourceChannel(id: "folder:alpha-project-1a2b3c", label: "alpha-project", connected: true,
                                   count: 3, lastSync: nil, detail: nil, actions: ["sync", "manage"])
        XCTAssertTrue(ChannelActions.managesInIntegrations(folder.id))
        XCTAssertTrue(ChannelActions.managesInIntegrations(LocalSourceWatcher.wisprChannel))
        XCTAssertFalse(ChannelActions.managesInIntegrations("safari-tabs"))
        XCTAssertNil(AddSourceTile.forChannel(folder.id), "why the add-source sheet was the wrong answer")
        XCTAssertEqual(ConnectedChannelRow.menuActions(for: folder), ["sync"])
    }

    // MARK: the watcher's reporting entry points

    private func makeWatcher(_ api: FakeLocalSourcesAPI, root: URL, defaults: UserDefaults) -> LocalSourceWatcher {
        LocalSourceWatcher(
            lights: BrowserWatcher(defaults: defaults, channels: []), api: api, defaults: defaults,
            manifests: FolderManifestStore(directory: root.appendingPathExtension("manifests")),
            wisprRoot: root.appendingPathComponent("no-wispr"),
            debounce: .seconds(60), minimumInterval: .zero, resolveRoot: { _ in root },
            makeWatch: { _, _ in nil })
    }

    func testSyncNowByIdRunsTheFolderSyncAndSaysSo() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("ChannelSyncRouting-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try "v1".write(to: root.appendingPathComponent("README.md"), atomically: true, encoding: .utf8)
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: root.appendingPathExtension("manifests"))
        }
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "ChannelSyncRouting-\(UUID().uuidString)"))
        let folder = FolderRegistration(id: "alpha-1", label: "alpha-project", path: root.path, include: ["**/*.md"])
        let api = FakeLocalSourcesAPI(folders: [folder])
        let watcher = makeWatcher(api, root: root, defaults: defaults)
        await watcher.reload()

        let result = try await watcher.syncNow(folderId: "alpha-1")
        // The watch factory returns nil, so the sync went through and the note
        // about the watch rides along — never an error.
        XCTAssertTrue(result.hasPrefix(LocalSourceCopy.synced), result)
        let last = await api.syncCalls.last
        XCTAssertEqual(last?.resolve, true, "Sync now asks for paper details (R-LS18)")

        do {
            _ = try await watcher.syncNow(folderId: "missing-9")
            XCTFail("an unknown folder must not report a sync")
        } catch {
            XCTAssertEqual(error.localizedDescription, LocalSourceCopy.folderNotSetUpHere)
            XCTAssertFalse(error.localizedDescription.contains("folder:"), "no internal id in the copy")
        }
    }

    func testWisprSyncWhileTurnedOffSaysSoInsteadOfSynced() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("ChannelSyncRouting-\(UUID().uuidString)")
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "ChannelSyncRouting-\(UUID().uuidString)"))
        let watcher = makeWatcher(FakeLocalSourcesAPI(folders: []), root: root, defaults: defaults)
        do {
            _ = try await watcher.syncWisprNowReporting()
            XCTFail("a turned-off source must not report a sync")
        } catch {
            XCTAssertEqual(error.localizedDescription, LocalSourceCopy.wisprTurnedOff)
        }
    }

    /// G142: Sync now on the Calendar card never starts the first EventKit read — Connect in Settings does.
    func testCalendarSyncNowBeforeConnectSaysSoInWords() async {
        let suite = "ChannelSyncRoutingTests.calendar.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("ChannelSyncRouting-cal-\(UUID().uuidString)")
        let reader = CalendarReader(store: FakeCalendarStore(), defaults: defaults)
        let store = Store(cache: SnapshotCache(root: root.appendingPathComponent("cache")), api: FakeSyncAPI())
        do {
            _ = try await ChannelActions.sync("calendar-local", store: store,
                                              local: makeWatcher(FakeLocalSourcesAPI(folders: []), root: root, defaults: defaults),
                                              calendar: reader)
            XCTFail("an unconnected calendar must not sync")
        } catch {
            XCTAssertEqual(error.localizedDescription, Copy.calendarConnectFirst)
        }
    }
}
