import XCTest
@testable import CicadaApp

/// A backend stand-in: records every call, answers with defaults.
actor FakeLocalSourcesAPI: LocalSourcesAPI {
    struct SyncCall: Equatable { let files: [String]; let deleted: [String]; let preview: Bool; let resolve: Bool }
    var folders: [FolderRegistration]
    var settings = WisprFlowSettings()
    private(set) var syncCalls: [SyncCall] = []
    private(set) var wisprPosts = 0
    /// How many `fetchFolders` calls fail before one succeeds — a backend still starting.
    private var failingFetches: Int
    /// When set, the next `syncFolder` waits here until `release()` — a slow upload.
    private var holdNext = false
    private var gate: CheckedContinuation<Void, Never>?
    var isHolding: Bool { gate != nil }

    func failNextFetches(_ n: Int) { failingFetches = n }
    func holdNextSync() { holdNext = true }
    func release() {
        gate?.resume()
        gate = nil
    }

    init(folders: [FolderRegistration], failingFetches: Int = 0) {
        self.folders = folders
        self.failingFetches = failingFetches
    }

    func fetchFolders() async throws -> [FolderRegistration] {
        if failingFetches > 0 {
            failingFetches -= 1
            throw URLError(.cannotConnectToHost)
        }
        return folders
    }
    func registerFolder(label: String, path: String, projectName: String,
                        authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration {
        let folder = FolderRegistration(id: "new-1", label: label, path: path, include: ["**/*.md"], authorship: authorship)
        folders.append(folder)
        return folder
    }
    func updateFolder(id: String, authorship: [FolderAuthorshipRule]) async throws -> FolderRegistration {
        guard let i = folders.firstIndex(where: { $0.id == id }) else { throw URLError(.badURL) }
        folders[i].authorship = authorship
        return folders[i]
    }
    func removeFolder(id: String) async throws { folders.removeAll { $0.id == id } }
    func syncFolder(id: String, files: [FolderUpload], deleted: [String], preview: Bool,
                    resolve: Bool) async throws -> FolderSyncResult {
        syncCalls.append(SyncCall(files: files.map(\.relpath).sorted(), deleted: deleted, preview: preview, resolve: resolve))
        if holdNext {
            holdNext = false
            await withCheckedContinuation { gate = $0 }
        }
        var result = FolderSyncResult()
        result.preview = preview
        result.filesNew = files.count
        return result
    }
    func fetchWisprSettings() async throws -> WisprFlowSettings { settings }
    func saveWisprSettings(_ settings: WisprFlowSettings) async throws -> WisprFlowSettings {
        self.settings = settings
        return settings
    }
    func postWisprFlow(_ json: Data) async throws -> WisprFlowSyncResult {
        wisprPosts += 1
        return WisprFlowSyncResult()
    }
}

/// G133 — the watcher posts what moved, tombstones what went, and lights the
/// card through `BrowserWatcher` (R-F1, R-LS26).
@MainActor
final class LocalSourceWatcherTests: XCTestCase {
    private var root: URL!
    private var defaults: UserDefaults!

    override func setUpWithError() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("LocalSourceWatcherTests-\(UUID().uuidString)")
        for (rel, text) in ["README.md": "v1", "notes/idea.md": "an idea", ".git/HEAD": "ref"] {
            let url = root.appendingPathComponent(rel)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try text.write(to: url, atomically: true, encoding: .utf8)
        }
        defaults = UserDefaults(suiteName: "LocalSourceWatcherTests-\(UUID().uuidString)")
    }

    override func tearDownWithError() throws {
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: root.path)
        try? FileManager.default.removeItem(at: root)
        try? FileManager.default.removeItem(at: root.deletingLastPathComponent()
            .appendingPathComponent(root.lastPathComponent + "-manifests"))
    }

    private func make(_ api: FakeLocalSourcesAPI, lights: BrowserWatcher,
                      retryDelay: Duration = .seconds(2),
                      makeWatch: FolderWatchFactory? = nil) -> LocalSourceWatcher {
        let root = self.root!
        // Manifests live beside the watched folder, not in it: a mode-000 root
        // must not also hide the manifest the test reads back.
        return LocalSourceWatcher(
            lights: lights, api: api, defaults: defaults,
            manifests: FolderManifestStore(directory: root.deletingLastPathComponent()
                .appendingPathComponent(root.lastPathComponent + "-manifests")),
            wisprRoot: root.appendingPathComponent("no-wispr"),
            debounce: .seconds(60), minimumInterval: .zero, retryDelay: retryDelay, resolveRoot: { _ in root },
            makeWatch: makeWatch)
    }

    private var alpha: FolderRegistration {
        FolderRegistration(id: "alpha-1", label: "alpha-project", path: root.path,
                           include: ["**/*.md"], exclude: ["**/.git/**"])
    }

    func testAFolderPostsOnlyWhatChangedAndTombstonesWhatWentAway() async throws {
        let folder = FolderRegistration(id: "alpha-1", label: "alpha-project", path: root.path,
                                        include: ["**/*.md"], exclude: ["**/.git/**", "**/.manifests/**"])
        let api = FakeLocalSourcesAPI(folders: [folder])
        let lights = BrowserWatcher(defaults: defaults, channels: [])
        let watcher = make(api, lights: lights)

        await watcher.reload()
        var calls = await api.syncCalls
        XCTAssertEqual(calls, [.init(files: ["README.md", "notes/idea.md"], deleted: [], preview: false, resolve: false)])
        XCTAssertEqual(lights.state(for: "folder:alpha-1"), .watching)

        await watcher.syncFolder(watcher.folders[0], resolve: false)
        calls = await api.syncCalls
        XCTAssertEqual(calls.count, 1, "an unchanged folder posts nothing")

        try "v2, longer".write(to: root.appendingPathComponent("README.md"), atomically: true, encoding: .utf8)
        try FileManager.default.removeItem(at: root.appendingPathComponent("notes/idea.md"))
        await watcher.syncFolder(watcher.folders[0], resolve: false)
        calls = await api.syncCalls
        XCTAssertEqual(calls.last, .init(files: ["README.md"], deleted: ["notes/idea.md"], preview: false, resolve: false))
    }

    func testSyncNowAsksForPaperDetailsEvenWithNothingNew() async throws {
        let folder = FolderRegistration(id: "alpha-1", label: "alpha-project", path: root.path,
                                        include: ["**/*.md"], exclude: ["**/.manifests/**"])
        let api = FakeLocalSourcesAPI(folders: [folder])
        let watcher = make(api, lights: BrowserWatcher(defaults: defaults, channels: []))
        await watcher.reload()
        await watcher.syncNow(watcher.folders[0])
        let last = await api.syncCalls.last
        XCTAssertEqual(last, .init(files: [], deleted: [], preview: false, resolve: true))
    }

    func testAPreviewPostsEveryIncludedFileWithPreviewSet() async throws {
        let api = FakeLocalSourcesAPI(folders: [])
        let watcher = make(api, lights: BrowserWatcher(defaults: defaults, channels: []))
        let folder = try await watcher.addFolder(url: root, label: "alpha-project", projectName: "alpha-project",
                                                 agentGlobs: ["archive/**"])
        let result = try await watcher.preview(folder, root: root)
        XCTAssertTrue(result.preview)
        XCTAssertEqual(result.filesNew, 2)
        let calls = await api.syncCalls
        XCTAssertEqual(calls.map(\.preview), [true])
    }

    /// A spawned backend takes seconds to boot, and the app starts this watcher
    /// at launch: a folder list it could not fetch yet must be asked for again,
    /// not left empty (and every folder unwatched) until the next bank switch.
    func testAFolderListTheBackendCouldNotServeYetIsAskedForAgain() async throws {
        let folder = FolderRegistration(id: "alpha-1", label: "alpha-project", path: root.path,
                                        include: ["**/*.md"], exclude: ["**/.git/**", "**/.manifests/**"])
        let api = FakeLocalSourcesAPI(folders: [folder], failingFetches: 1)
        let watcher = make(api, lights: BrowserWatcher(defaults: defaults, channels: []), retryDelay: .milliseconds(20))
        await watcher.reload()
        XCTAssertTrue(watcher.folders.isEmpty, "the backend was not up yet")
        for _ in 0..<150 {
            if await !api.syncCalls.isEmpty { break }
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTAssertEqual(watcher.folders.map(\.id), ["alpha-1"])
        let calls = await api.syncCalls
        XCTAssertEqual(calls.first?.files, ["README.md", "notes/idea.md"], "the retry watched and synced the folder")
    }

    /// Review r1 (blocking): a folder the app can no longer list — a Files &
    /// Folders denial, a grant lost after a re-sign — once read as "every file
    /// deleted", tombstoning the folder's episodes as the person. Now nothing is
    /// posted, the manifest is kept, and the card shows the fix.
    func testAFolderTheAppCannotListPostsNoDeletionsAndShowsTheFix() async throws {
        let api = FakeLocalSourcesAPI(folders: [alpha])
        let lights = BrowserWatcher(defaults: defaults, channels: [])
        let watcher = make(api, lights: lights)
        await watcher.reload()
        var calls = await api.syncCalls
        XCTAssertEqual(calls.count, 1)

        try FileManager.default.setAttributes([.posixPermissions: 0o000], ofItemAtPath: root.path)
        await watcher.syncFolder(watcher.folders[0], resolve: false)
        calls = await api.syncCalls
        XCTAssertEqual(calls.count, 1, "nothing was posted, above all no deletions")
        XCTAssertEqual(lights.state(for: "folder:alpha-1"), .failed)
        XCTAssertEqual(watcher.folderErrors["alpha-1"], LocalSourceCopy.folderPermissionFix)

        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: root.path)
        await watcher.syncFolder(watcher.folders[0], resolve: false)
        calls = await api.syncCalls
        XCTAssertEqual(calls.count, 1, "the manifest survived: a restored grant re-posts nothing")
        XCTAssertEqual(lights.state(for: "folder:alpha-1"), .watching)
        XCTAssertNil(watcher.folderErrors["alpha-1"])
    }

    /// Review r1: a save that lands while an upload is in flight is synced when
    /// that upload ends, not left stale until the next edit.
    func testASaveDuringASlowSyncIsSyncedWhenItEnds() async throws {
        let api = FakeLocalSourcesAPI(folders: [alpha])
        let watcher = make(api, lights: BrowserWatcher(defaults: defaults, channels: []))
        await watcher.reload()
        try "v2, longer".write(to: root.appendingPathComponent("README.md"), atomically: true, encoding: .utf8)

        await api.holdNextSync()
        let inFlight = Task { await watcher.syncFolder(watcher.folders[0], resolve: false) }
        for _ in 0..<150 {
            if await api.isHolding { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        let holding = await api.isHolding
        XCTAssertTrue(holding)
        try "an idea, revised".write(to: root.appendingPathComponent("notes/idea.md"), atomically: true, encoding: .utf8)
        await watcher.syncFolder(watcher.folders[0], resolve: false)  // the save's event, mid-sync
        await api.release()
        await inFlight.value

        let calls = await api.syncCalls
        XCTAssertEqual(calls.dropFirst().map(\.files), [["README.md"], ["notes/idea.md"]])
    }

    /// Review r1: after a bank switch whose folder fetch failed, the previous
    /// bank's folders are neither kept, armed nor synced into the new bank, and
    /// their lights go out.
    func testAFailedFetchAfterABankSwitchDropsThePreviousBanksFolders() async throws {
        let api = FakeLocalSourcesAPI(folders: [alpha])
        let lights = BrowserWatcher(defaults: defaults, channels: [])
        let watcher = make(api, lights: lights)
        await watcher.reload(bank: "bank-a")
        XCTAssertEqual(lights.state(for: "folder:alpha-1"), .watching)

        await api.failNextFetches(1)
        await watcher.reload(bank: "bank-a")
        XCTAssertEqual(watcher.folders.map(\.id), ["alpha-1"], "the same bank keeps its last-known-good list")

        await api.failNextFetches(1)
        await watcher.reload(bank: "bank-b")
        XCTAssertTrue(watcher.folders.isEmpty)
        XCTAssertNil(lights.state(for: "folder:alpha-1"))
        let calls = await api.syncCalls
        XCTAssertEqual(calls.count, 1, "nothing from bank-a was posted into bank-b")
    }

    /// Review r1: a watch that did not start never reads "Watching".
    func testAWatchThatDidNotStartIsNotCalledWatching() async throws {
        let api = FakeLocalSourcesAPI(folders: [alpha])
        let lights = BrowserWatcher(defaults: defaults, channels: [])
        let watcher = make(api, lights: lights, makeWatch: { _, _ in nil })
        await watcher.reload()
        let calls = await api.syncCalls
        XCTAssertEqual(calls.count, 1, "the catch-up sync still ran")
        XCTAssertEqual(lights.state(for: "folder:alpha-1"), .stale)
        XCTAssertEqual(watcher.folderErrors["alpha-1"], LocalSourceCopy.folderNotWatched)
    }

    func testPublishedLightsReachTheExistingLookups() {
        let lights = BrowserWatcher(defaults: defaults, channels: [])
        lights.publish(.blocked, error: .notReadable(.wisprFlowDatabase, "/x"), for: "wispr-flow")
        XCTAssertEqual(lights.state(for: "wispr-flow"), .blocked)
        XCTAssertEqual(lights.error(for: "wispr-flow"), .notReadable(.wisprFlowDatabase, "/x"))
        lights.publish(nil, error: nil, for: "wispr-flow")
        XCTAssertNil(lights.state(for: "wispr-flow"))
    }
}
