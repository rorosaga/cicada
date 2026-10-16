import Darwin
import XCTest
@testable import CicadaApp

/// G181 phase 3 — the Mac app as a server's client: the mode switch and its address rule, the base URL and the token
/// every request carries, the readers' outbox and its flush, the Devices page's model, and the one quiet word for where
/// a conversation, a save or a claim came from. The last test runs two real HTTP listeners on two loopback ports — a
/// "server" and "this Mac" — and proves the client talks to the one it was given and never to the other.
/// Synthetic tokens and placeholder names only; nothing leaves 127.0.0.1, nothing reads the real home.
final class HeadlessAppTests: XCTestCase {
    private var home: URL!

    override func setUpWithError() throws {
        home = FileManager.default.temporaryDirectory.appendingPathComponent("headless-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: home, withIntermediateDirectories: true)
        APIClient.invalidateToken()
        HeadlessStubProtocol.reset()
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: home)
        APIClient.invalidateToken()
        HeadlessStubProtocol.reset()
    }

    private let deviceToken = "cic_dev_abcd1234_" + String(repeating: "x", count: 43)

    private func runtime(port: Int = 8000) -> CicadaRuntime {
        CicadaRuntime.developer(codeRoot: URL(fileURLWithPath: "/nonexistent/checkout"), cicadaHome: home, port: port)
    }

    private func server(_ raw: String) -> ServerConnection {
        guard case .success(let url) = ServerConnection.validate(raw) else { XCTFail("bad \(raw)"); return .init(mode: .thisMac, source: .none) }
        return ServerConnection(mode: .server(url), source: .file)
    }

    // MARK: The address rule (runtime_layout.api_base, restated)

    func testAnAddressIsHttpsOrALoopbackTunnel() {
        let good = [
            ("https://cicada.example.ts.net", "https://cicada.example.ts.net"),
            ("https://cicada.example.ts.net/", "https://cicada.example.ts.net"),
            ("https://cicada.example.ts.net:8443/cicada/", "https://cicada.example.ts.net:8443/cicada"),
            ("http://127.0.0.1:18000", "http://127.0.0.1:18000"),
            ("http://localhost:18000", "http://localhost:18000"),
        ]
        for (raw, want) in good {
            guard case .success(let url) = ServerConnection.validate(raw) else { return XCTFail(raw) }
            XCTAssertEqual(url.absoluteString, want)
        }
        let bad: [(String, ServerConnection.AddressError)] = [
            ("http://cicada.example.ts.net", .needsHTTPS), ("ftp://example.com", .notHTTP),
            ("https://user:pw@example.com", .carriesExtras), ("https://example.com/?a=1", .carriesExtras),
            ("", .notAURL),
        ]
        for (raw, want) in bad {
            guard case .failure(let error) = ServerConnection.validate(raw) else { return XCTFail(raw) }
            XCTAssertEqual(error, want, raw)
        }
    }

    func testTheEnvironmentWinsThenTheAppsFileThenThisMac() throws {
        XCTAssertEqual(ServerConnection.resolve(environment: [:], cicadaHome: home).mode, .thisMac)
        try "https://cicada.example.ts.net\n".write(to: home.appendingPathComponent("api_base"), atomically: true, encoding: .utf8)
        let fromFile = ServerConnection.resolve(environment: [:], cicadaHome: home)
        XCTAssertEqual(fromFile.serverURL?.absoluteString, "https://cicada.example.ts.net")
        XCTAssertEqual(fromFile.source, .file)
        let fromEnv = ServerConnection.resolve(environment: ["CICADA_API_BASE": "http://127.0.0.1:18000"], cicadaHome: home)
        XCTAssertEqual(fromEnv.serverURL?.absoluteString, "http://127.0.0.1:18000")
        XCTAssertEqual(fromEnv.source, .environment)
    }

    func testAWrongAddressNeverFallsBackToThisMac() throws {
        try "http://cicada.example.ts.net\n".write(to: home.appendingPathComponent("api_base"), atomically: true, encoding: .utf8)
        let connection = ServerConnection.resolve(environment: [:], cicadaHome: home)
        XCTAssertTrue(connection.isServer)
        XCTAssertNotNil(connection.invalidReason)
        XCTAssertEqual(connection.baseURL(local: "http://127.0.0.1:8000"), ServerConnection.unreachableBase)
        XCTAssertFalse(ServerConnection.unreachableBase.contains("127.0.0.1"))
    }

    func testSavingWritesPrivateFilesAndThisMacRemovesOnlyTheAddress() throws {
        let url = try XCTUnwrap(try? ServerConnection.validate("https://cicada.example.ts.net").get())
        try ServerConnection.save(base: url, token: deviceToken, cicadaHome: home)
        for name in ["api_base.next", "device_token"] {
            let attrs = try FileManager.default.attributesOfItem(atPath: home.appendingPathComponent(name).path)
            XCTAssertEqual((attrs[.posixPermissions] as? NSNumber)?.intValue, 0o600, name)
        }
        XCTAssertEqual(ServerConnection.deviceToken(environment: [:], cicadaHome: home), deviceToken)
        ServerConnection.applyPending(cicadaHome: home)
        let attrs = try FileManager.default.attributesOfItem(atPath: home.appendingPathComponent("api_base").path)
        XCTAssertEqual((attrs[.posixPermissions] as? NSNumber)?.intValue, 0o600)
        XCTAssertTrue(ServerConnection.resolve(environment: [:], cicadaHome: home).isServer)
        try ServerConnection.forget(cicadaHome: home)
        ServerConnection.applyPending(cicadaHome: home)
        XCTAssertEqual(ServerConnection.resolve(environment: [:], cicadaHome: home).mode, .thisMac)
        XCTAssertFalse(FileManager.default.fileExists(atPath: home.appendingPathComponent("api_base").path))
        XCTAssertEqual(ServerConnection.deviceToken(environment: [:], cicadaHome: home), deviceToken)
    }

    /// Review fix: the hooks, the stdio MCP server and the CLI read `api_base` on every call, so a choice must not
    /// reach it before this app opens again — the whole Mac switches together, at launch.
    func testAChoiceWaitsForTheNextLaunchSoTheAgentsAndTheAppSwitchTogether() throws {
        try "https://old.example.ts.net\n".write(to: home.appendingPathComponent("api_base"), atomically: true, encoding: .utf8)
        let url = try XCTUnwrap(try? ServerConnection.validate("https://cicada.example.ts.net").get())
        try ServerConnection.save(base: url, token: nil, cicadaHome: home)
        // in place now (what the agents read): unchanged; what Settings shows as next: the new one
        XCTAssertEqual(ServerConnection.resolve(environment: [:], cicadaHome: home).host, "old.example.ts.net")
        XCTAssertEqual(ServerConnection.resolve(environment: [:], cicadaHome: home, includingPending: true).host,
                       "cicada.example.ts.net")
        try ServerConnection.forget(cicadaHome: home)
        XCTAssertEqual(ServerConnection.resolve(environment: [:], cicadaHome: home).host, "old.example.ts.net")
        XCTAssertEqual(ServerConnection.resolve(environment: [:], cicadaHome: home, includingPending: true).mode, .thisMac)
        ServerConnection.applyPending(cicadaHome: home)
        XCTAssertEqual(ServerConnection.resolve(environment: [:], cicadaHome: home).mode, .thisMac)
        XCTAssertFalse(FileManager.default.fileExists(atPath: home.appendingPathComponent("api_base.next").path))
        ServerConnection.applyPending(cicadaHome: home)          // nothing pending: nothing changes
        XCTAssertEqual(ServerConnection.resolve(environment: [:], cicadaHome: home).mode, .thisMac)
    }

    func testAGarbledFileIsAnInvalidServerNeverThisMac() throws {
        try Data([0xff, 0xfe, 0x00, 0x41]).write(to: home.appendingPathComponent("api_base"))
        let connection = ServerConnection.resolve(environment: [:], cicadaHome: home)
        XCTAssertTrue(connection.isServer)
        XCTAssertNotNil(connection.invalidReason)
    }

    func testTheDeviceIdIsReadFromItsOwnToken() {
        XCTAssertEqual(ServerConnection.deviceId(fromToken: deviceToken), "abcd1234")
        XCTAssertNil(ServerConnection.deviceId(fromToken: "some-master-token"))
        XCTAssertNil(ServerConnection.deviceId(fromToken: nil))
        XCTAssertFalse(ServerConnection.looksLikeDeviceToken("master"))
    }

    func testEachConnectionHasItsOwnDiskCache() {
        XCTAssertEqual(ServerConnection(mode: .thisMac, source: .none).cacheFolderName, "cache")
        let a = server("https://a.example.ts.net").cacheFolderName
        let b = server("https://b.example.ts.net").cacheFolderName
        XCTAssertNotEqual(a, "cache")
        XCTAssertNotEqual(a, b)
        // What a reader already sent belongs to the backend it went to: This Mac's keys are byte for byte as before.
        let mac = ServerConnection(mode: .thisMac, source: .none)
        XCTAssertEqual(mac.scoped("cicada.watchHistory.default.cursor"), "cicada.watchHistory.default.cursor")
        let onServer = server("https://a.example.ts.net").scoped("cicada.watchHistory.default.cursor")
        XCTAssertTrue(onServer.hasPrefix("cicada.watchHistory.default.cursor-server-"))
        XCTAssertEqual(server("https://a.example.ts.net").cacheFolderName, "cache" + server("https://a.example.ts.net").scopeSuffix)
    }

    // MARK: The base URL and the token

    func testOnAServerEveryRequestGoesThereWithThisDevicesToken() async throws {
        try "master-token\n".write(to: home.appendingPathComponent("api_token"), atomically: true, encoding: .utf8)
        try (deviceToken + "\n").write(to: home.appendingPathComponent("device_token"), atomically: true, encoding: .utf8)
        HeadlessStubProtocol.respond = { _ in (200, #"{"banks": [], "active": "default"}"#) }
        let client = APIClient(session: HeadlessStubProtocol.session(), connection: server("https://cicada.example.ts.net"),
                               runtime: runtime())
        _ = try await client.fetchBanks()
        let sent = try XCTUnwrap(HeadlessStubProtocol.requests.first)
        XCTAssertEqual(sent.url?.host, "cicada.example.ts.net")
        XCTAssertEqual(sent.url?.path, "/banks")
        XCTAssertEqual(sent.value(forHTTPHeaderField: "Authorization"), "Bearer \(deviceToken)")
    }

    func testOnThisMacTheLoopbackAndTheMasterTokenAreUnchanged() async throws {
        try "master-token\n".write(to: home.appendingPathComponent("api_token"), atomically: true, encoding: .utf8)
        try (deviceToken + "\n").write(to: home.appendingPathComponent("device_token"), atomically: true, encoding: .utf8)
        HeadlessStubProtocol.respond = { _ in (200, #"{"banks": [], "active": "default"}"#) }
        let client = APIClient(session: HeadlessStubProtocol.session(), connection: ServerConnection(mode: .thisMac, source: .none),
                               runtime: runtime(port: 8123))
        _ = try await client.fetchBanks()
        let sent = try XCTUnwrap(HeadlessStubProtocol.requests.first)
        XCTAssertEqual(sent.url?.absoluteString, "http://127.0.0.1:8123/banks")
        XCTAssertEqual(sent.value(forHTTPHeaderField: "Authorization"), "Bearer master-token")
    }

    func testTheDemoStaysOnThisMac() async throws {
        let client = APIClient(session: HeadlessStubProtocol.session(), connection: server("https://cicada.example.ts.net"),
                               runtime: runtime())
        do {
            _ = try await client.createDemoBank()
            XCTFail("a demo reached a server")
        } catch let error as ServerLinkError {
            XCTAssertEqual(error, .demoStaysLocal)
        }
        XCTAssertTrue(HeadlessStubProtocol.requests.isEmpty)
    }

    // MARK: The outbox

    func testOnlyAReadersPostOfBytesMayWait() {
        XCTAssertTrue(ReaderOutbox.queues("/sources/sync-notes"))
        XCTAssertTrue(ReaderOutbox.queues("/sources/sync-bookmarks"))
        XCTAssertTrue(ReaderOutbox.queues("/sources/folders/f1/sync?preview=false&resolve=true"))
        XCTAssertTrue(ReaderOutbox.queues("/sources/messages/sync"))
        XCTAssertFalse(ReaderOutbox.queues("/sources/sync-bookmarks?preview=true"))
        XCTAssertFalse(ReaderOutbox.queues("/sources/sync-bookmarks/fresh"))
        XCTAssertFalse(ReaderOutbox.queues("/sources/folders"))
        XCTAssertFalse(ReaderOutbox.queues("/inbox/i1/resolve"))
        XCTAssertFalse(ReaderOutbox.queues("/sleep/trigger"))
    }

    func testTheSameBytesWaitOnceAndDifferentBytesEachWait() async throws {
        let outbox = ReaderOutbox(folder: ReaderOutbox.folder(cicadaHome: home))
        try await outbox.put(method: "POST", path: "/sources/sync-notes", body: Data("a".utf8), bank: "default")
        try await outbox.put(method: "POST", path: "/sources/sync-notes", body: Data("a".utf8), bank: "default")
        try await outbox.put(method: "POST", path: "/sources/sync-notes", body: Data("b".utf8), bank: "default")
        let stored = try await outbox.put(method: "POST", path: "/inbox/x/resolve", body: Data("c".utf8), bank: "default")
        XCTAssertFalse(stored)
        let count = await outbox.count()
        XCTAssertEqual(count, 2)
        let folder = ReaderOutbox.folder(cicadaHome: home)
        let mode = try FileManager.default.attributesOfItem(atPath: folder.path)[.posixPermissions] as? NSNumber
        XCTAssertEqual(mode?.intValue, 0o700)
    }

    func testAFlushSendsOldestFirstStopsWhenTheServerIsAwayAndDropsWhatCanNeverLand() async throws {
        var clock = Date(timeIntervalSince1970: 1_800_000_000)
        let outbox = ReaderOutbox(folder: ReaderOutbox.folder(cicadaHome: home), now: { [clock] in clock })
        _ = clock
        for body in ["one", "two", "three"] {
            clock += 1
            let stamped = ReaderOutbox(folder: ReaderOutbox.folder(cicadaHome: home), now: { [clock] in clock })
            try await stamped.put(method: "POST", path: "/sources/sync-notes", body: Data(body.utf8), bank: "default")
        }
        let order = await outbox.entries().map { String(decoding: $0.entry.body, as: UTF8.self) }
        XCTAssertEqual(order, ["one", "two", "three"])
        // The server is still away: nothing leaves, nothing is lost.
        let away = await outbox.flush { _ in nil }
        XCTAssertEqual(away, ReaderOutbox.FlushResult(sent: 0, dropped: 0, waiting: 3))
        // Back: the first lands, the second can never land (422), the third meets a 503 and waits.
        let answers: [String: Int] = ["one": 200, "two": 422, "three": 503]
        let back = await outbox.flush { entry in answers[String(decoding: entry.body, as: UTF8.self)] }
        XCTAssertEqual(back, ReaderOutbox.FlushResult(sent: 1, dropped: 1, waiting: 1))
    }

    func testOldPostsAreDroppedPastTheAge() async throws {
        let folder = ReaderOutbox.folder(cicadaHome: home)
        let old = ReaderOutbox(folder: folder, now: { Date(timeIntervalSince1970: 1_800_000_000) })
        try await old.put(method: "POST", path: "/sources/sync-notes", body: Data("old".utf8), bank: nil)
        let later = ReaderOutbox(folder: folder, now: { Date(timeIntervalSince1970: 1_800_000_000 + ReaderOutbox.maxAge + 60) })
        try await later.put(method: "POST", path: "/sources/sync-notes", body: Data("new".utf8), bank: nil)
        let left = await later.entries().map { String(decoding: $0.entry.body, as: UTF8.self) }
        XCTAssertEqual(left, ["new"])
    }

    func testAReadersPostWaitsWhenTheServerIsAwayAndAnyOtherFailsAsBefore() async throws {
        HeadlessStubProtocol.fail = URLError(.cannotConnectToHost)
        let client = APIClient(session: HeadlessStubProtocol.session(), connection: server("https://cicada.example.ts.net"),
                               runtime: runtime())
        do {
            _ = try await client.syncNotes(dump: "note dump")
            XCTFail("expected the post to wait")
        } catch let error as ServerLinkError {
            XCTAssertEqual(error, .queuedOffline)
        }
        do {
            _ = try await client.triggerSleep()
            XCTFail("expected a failure")
        } catch is ServerLinkError {
            XCTFail("only a reader's post waits")
        } catch {}
        let waiting = await client.outbox.count()
        XCTAssertEqual(waiting, 1)
    }

    /// Review fix: a newer post never overtakes an older one on the same route — the older goes first, and while it
    /// cannot land the newer waits behind it (a snapshot replayed late would put the server back to an older state).
    func testANewerPostNeverOvertakesAnOlderOneOnTheSameRoute() async throws {
        let client = APIClient(session: HeadlessStubProtocol.session(), connection: server("https://cicada.example.ts.net"),
                               runtime: runtime())
        HeadlessStubProtocol.fail = URLError(.cannotConnectToHost)
        _ = try? await client.syncNotes(dump: "older dump")
        var waiting = await client.outbox.count()
        XCTAssertEqual(waiting, 1)
        // still away (503): the newer waits behind, and nothing newer was sent
        HeadlessStubProtocol.reset()
        HeadlessStubProtocol.respond = { _ in (503, "{}") }
        do {
            _ = try await client.syncNotes(dump: "newer dump")
            XCTFail("expected the post to wait")
        } catch let error as ServerLinkError {
            XCTAssertEqual(error, .queuedOffline)
        }
        XCTAssertEqual(HeadlessStubProtocol.requests.count, 1)
        XCTAssertTrue(String(decoding: HeadlessStubProtocol.requests[0].httpBody ?? Data(), as: UTF8.self).contains("older dump"))
        waiting = await client.outbox.count()
        XCTAssertEqual(waiting, 2)
        // back: oldest first, then the newest, which lands directly
        HeadlessStubProtocol.reset()
        HeadlessStubProtocol.respond = { _ in (200, #"{"created":0,"updated":0,"unchanged":0,"skipped":0}"#) }
        _ = try? await client.syncNotes(dump: "newest dump")
        let bodies = HeadlessStubProtocol.requests.map { String(decoding: $0.httpBody ?? Data(), as: UTF8.self) }
        XCTAssertEqual(bodies.count, 3)
        XCTAssertTrue(bodies[0].contains("older dump") && bodies[1].contains("newer dump") && bodies[2].contains("newest dump"))
        waiting = await client.outbox.count()
        XCTAssertEqual(waiting, 0)
    }

    func testOnThisMacNothingWaits() async throws {
        HeadlessStubProtocol.fail = URLError(.cannotConnectToHost)
        let client = APIClient(session: HeadlessStubProtocol.session(), connection: ServerConnection(mode: .thisMac, source: .none),
                               runtime: runtime())
        do {
            _ = try await client.syncNotes(dump: "note dump")
            XCTFail("expected a failure")
        } catch is ServerLinkError {
            XCTFail("This Mac never queues")
        } catch {}
        let waiting = await client.outbox.count()
        XCTAssertEqual(waiting, 0)
    }

    func testTheFlushSignsNowAndNamesTheMemoryItWasReadFor() async throws {
        try (deviceToken + "\n").write(to: home.appendingPathComponent("device_token"), atomically: true, encoding: .utf8)
        let client = APIClient(session: HeadlessStubProtocol.session(), connection: server("https://cicada.example.ts.net"),
                               runtime: runtime())
        try await client.outbox.put(method: "POST", path: "/sources/sync-notes", body: Data(#"{"notesDump":"x"}"#.utf8),
                                    bank: "alpha-memory")
        HeadlessStubProtocol.respond = { _ in (200, "{}") }
        let result = await client.flushOutbox()
        XCTAssertEqual(result.sent, 1)
        let sent = try XCTUnwrap(HeadlessStubProtocol.requests.first)
        XCTAssertEqual(sent.value(forHTTPHeaderField: "X-Cicada-Bank"), "alpha-memory")
        XCTAssertEqual(sent.value(forHTTPHeaderField: "Authorization"), "Bearer \(deviceToken)")
        XCTAssertEqual(sent.url?.path, "/sources/sync-notes")
    }

    // MARK: Where it came from

    func testOneQuietWordForWhereItCameFrom() {
        let names = ["abcd1234": "laptop", "efgh5678": "desk"]
        let mac = ServerConnection(mode: .thisMac, source: .none)
        let srv = server("https://cicada.example.ts.net")
        XCTAssertNil(DeviceOrigin.label(device: nil, connection: mac, names: names, myDevice: nil))
        XCTAssertEqual(DeviceOrigin.label(device: "abcd1234", connection: mac, names: names, myDevice: nil), "laptop")
        XCTAssertEqual(DeviceOrigin.label(device: nil, connection: srv, names: names, myDevice: "abcd1234"),
                       Copy.Devices.thisServer)
        XCTAssertEqual(DeviceOrigin.label(device: "abcd1234", connection: srv, names: names, myDevice: "abcd1234"),
                       Copy.Devices.thisDevice)
        XCTAssertEqual(DeviceOrigin.label(device: "efgh5678", connection: srv, names: names, myDevice: "abcd1234"), "desk")
        XCTAssertEqual(DeviceOrigin.label(device: "zzzz0000", connection: srv, names: names, myDevice: nil),
                       Copy.Devices.aDevice)
        XCTAssertEqual(DeviceOrigin.bankHost(srv), "on cicada.example.ts.net")
        XCTAssertNil(DeviceOrigin.bankHost(mac))
    }

    func testTheDeviceRidesTheSavedRowTheConversationAndTheReader() throws {
        let row = try JSONDecoder().decode(MediaFeedItem.self, from: Data(#"""
        {"mediaEntityId": "media-a", "url": "https://example.com/a", "title": "A", "mediaType": "url",
         "savedAt": "2026-10-16", "origin": "chrome", "device": "abcd1234"}
        """#.utf8))
        XCTAssertEqual(row.device, "abcd1234")
        XCTAssertTrue(FeedSourceLine.text(row, device: "laptop").hasSuffix("· from laptop"))
        XCTAssertFalse(FeedSourceLine.text(row).contains("from"))
        let older = try JSONDecoder().decode(MediaFeedItem.self, from: Data(#"""
        {"mediaEntityId": "media-a", "url": "https://example.com/a", "title": "A", "mediaType": "url"}
        """#.utf8))
        XCTAssertNil(older.device)
        let conversation = try JSONDecoder().decode(ProvenanceConversation.self, from: Data(#"""
        {"episodeId": "ep_2026-10-16_001", "device": "abcd1234"}
        """#.utf8))
        XCTAssertEqual(conversation.device, "abcd1234")
        let doc = try JSONDecoder().decode(EpisodeText.self, from: Data(#"""
        {"episode": "ep_2026-10-16_001", "text": "user: hi", "title": "t", "device": "abcd1234"}
        """#.utf8))
        XCTAssertEqual(doc.device, "abcd1234")
        XCTAssertTrue(ReaderHeader.meta(doc, device: "laptop").hasSuffix("from laptop"))
        XCTAssertFalse(ReaderHeader.meta(doc).contains("from"))
    }

    // MARK: The Devices page

    func testADeviceRecordDecodesFromAnOlderServerToo() throws {
        let rows = try JSONDecoder().decode(DeviceList.self, from: Data(#"""
        {"devices": [{"id": "abcd1234", "name": "laptop", "createdAt": "2026-10-16T10:00:00+00:00",
                      "revokedAt": null, "lastUsedAt": null, "useCount": 0, "active": true}]}
        """#.utf8)).devices
        XCTAssertEqual(rows.first?.current, false)
        XCTAssertEqual(rows.first?.name, "laptop")
    }

    @MainActor
    func testTheDevicesPageReadsOnAServerAndManagesOnThisMac() async {
        let api = FakeDevicesAPI()
        api.rows = [DeviceRecord(id: "abcd1234", name: "laptop", createdAt: "2026-10-16T10:00:00+00:00",
                                 lastUsedAt: "2026-10-16T11:00:00+00:00", current: true)]
        api.waiting = 2
        let now = Date(timeIntervalSince1970: 1_792_150_000)
        let onServer = DevicesPageModel(api: api, connection: server("https://cicada.example.ts.net"), now: { now })
        await onServer.refresh()
        XCTAssertFalse(onServer.canManage)
        XCTAssertEqual(onServer.reachable, true)
        XCTAssertEqual(onServer.waiting, 2)
        XCTAssertEqual(onServer.connectionLine, Copy.Devices.connectionServer("cicada.example.ts.net"))
        XCTAssertEqual(onServer.statusLine(at: now), Copy.Devices.reachable("just now"))
        await onServer.add(name: "desk")
        XCTAssertEqual(api.created, [])                       // a device never issues a device (ruling 28.1)

        let onMac = DevicesPageModel(api: api, connection: ServerConnection(mode: .thisMac, source: .none), now: { now })
        await onMac.refresh()
        XCTAssertTrue(onMac.canManage)
        XCTAssertEqual(onMac.waiting, 0)
        XCTAssertNil(onMac.statusLine(at: now))
        await onMac.add(name: "  desk ")
        XCTAssertEqual(api.created, ["desk"])
        XCTAssertEqual(onMac.created?.token, "cic_dev_new00000_" + String(repeating: "y", count: 43))

        api.healthy = false
        await onServer.refresh()
        XCTAssertEqual(onServer.reachable, false)
        XCTAssertTrue(onServer.statusLine(at: now)?.hasPrefix("Not reachable") == true)
    }

    @MainActor
    func testADeviceRowSaysWhenItWasAddedAndLastSeen() {
        let model = DevicesPageModel(api: FakeDevicesAPI(), connection: ServerConnection(mode: .thisMac, source: .none))
        let created = "2026-10-16T10:00:00+00:00"
        let seen = DeviceRecord(id: "a", name: "laptop", createdAt: created, lastUsedAt: "2026-10-16T10:00:00+00:00")
        let at = DevicesText.date(created)!.addingTimeInterval(3 * 3600)
        let line = model.detail(seen, at: at, locale: Locale(identifier: "en_US"))
        XCTAssertTrue(line.hasPrefix("added "), line)
        XCTAssertTrue(line.contains("last seen 3 hours ago"), line)
        let never = DeviceRecord(id: "b", name: "desk", createdAt: created)
        XCTAssertTrue(model.detail(never, at: at).hasSuffix(Copy.Devices.neverSeen))
        let revoked = DeviceRecord(id: "c", name: "old", createdAt: created, revokedAt: created, active: false)
        XCTAssertTrue(model.detail(revoked, at: at, locale: Locale(identifier: "en_US")).contains("revoked "))
    }

    @MainActor
    func testTheDirectoryNamesDevicesOnceLoaded() async {
        let api = FakeDevicesAPI()
        api.rows = [DeviceRecord(id: "efgh5678", name: "desk", createdAt: "")]
        let directory = DeviceDirectory(api: api, connection: server("https://cicada.example.ts.net"), myDevice: "abcd1234")
        XCTAssertEqual(directory.label(for: "efgh5678"), Copy.Devices.aDevice)
        directory.ensureLoaded()
        for _ in 0..<50 where !directory.loaded { await Task.yield() }
        XCTAssertEqual(directory.label(for: "efgh5678"), "desk")
        XCTAssertEqual(directory.label(for: "abcd1234"), Copy.Devices.thisDevice)
        XCTAssertEqual(directory.label(for: nil), Copy.Devices.thisServer)
    }

    // MARK: Settings → General

    @MainActor
    func testChoosingAServerIsCheckedBeforeAnythingIsWritten() async {
        let running = ServerConnection(mode: .thisMac, source: .none)
        var answer: ServerCheck = .unreachable
        let model = ConnectionSettingsModel(running: running, cicadaHome: home, environment: [:],
                                            probe: { _, _ in answer })
        model.choice = .server
        model.address = "http://cicada.example.ts.net"
        model.token = deviceToken
        await model.checkAndUse()
        XCTAssertEqual(model.result, .badAddress(Copy.Devices.addressNeedsHTTPS))
        model.address = "https://cicada.example.ts.net/"
        await model.checkAndUse()
        XCTAssertEqual(model.result, .unreachable)
        XCTAssertFalse(FileManager.default.fileExists(atPath: home.appendingPathComponent("api_base").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: home.appendingPathComponent("api_base.next").path))
        XCTAssertFalse(model.needsRestart)
        answer = .ok(deviceName: "laptop")
        await model.checkAndUse()
        XCTAssertTrue(model.needsRestart)
        XCTAssertEqual(model.saved.serverURL?.absoluteString, "https://cicada.example.ts.net")
        XCTAssertEqual(model.pendingLine, Copy.Devices.pendingServer("cicada.example.ts.net"))
        // nothing the agents read moves until Cicada opens again
        XCTAssertFalse(FileManager.default.fileExists(atPath: home.appendingPathComponent("api_base").path))
        XCTAssertEqual(ServerConnection.deviceToken(environment: [:], cicadaHome: home), deviceToken)
        XCTAssertTrue(model.tokenSaved)
        model.useThisMac()
        XCTAssertFalse(model.needsRestart)                    // back to what the app runs with
        XCTAssertEqual(model.saved.mode, .thisMac)
    }

    @MainActor
    func testTheEnvironmentLocksTheChoice() {
        let running = ServerConnection(mode: .server(URL(string: "https://cicada.example.ts.net")!), source: .environment)
        let model = ConnectionSettingsModel(running: running, cicadaHome: home,
                                            environment: ["CICADA_API_BASE": "https://cicada.example.ts.net"],
                                            probe: { _, _ in .unreachable })
        XCTAssertTrue(model.lockedByEnvironment)
        XCTAssertEqual(model.choice, .server)
    }

    func testTheProbeRefusesAMasterTokenWithoutSendingIt() async {
        let base = URL(string: "https://cicada.example.ts.net")!
        let answer = await ServerProbe.check(base: base, token: "master-token", session: HeadlessStubProtocol.session())
        XCTAssertEqual(answer, .notDeviceToken)
        XCTAssertTrue(HeadlessStubProtocol.requests.isEmpty)
    }

    func testTheProbeNamesThisDeviceAndTellsABadTokenApart() async {
        let base = URL(string: "https://cicada.example.ts.net")!
        HeadlessStubProtocol.respond = { request in
            switch request.url?.path {
            case "/healthz": return (200, #"{"version": "0.3.0", "memoryRoot": "/srv/memory"}"#)
            case "/devices": return (200, #"{"devices": [{"id": "abcd1234", "name": "laptop", "createdAt": "", "current": true}]}"#)
            default: return (404, "{}")
            }
        }
        let ok = await ServerProbe.check(base: base, token: deviceToken, session: HeadlessStubProtocol.session())
        XCTAssertEqual(ok, .ok(deviceName: "laptop"))
        XCTAssertNil(HeadlessStubProtocol.requests.first { $0.url?.path == "/healthz" }?
            .value(forHTTPHeaderField: "Authorization"))      // the open probe carries no token
        HeadlessStubProtocol.respond = { request in
            request.url?.path == "/healthz" ? (200, #"{"version": "0.3.0"}"#) : (401, "{}")
        }
        let bad = await ServerProbe.check(base: base, token: deviceToken, session: HeadlessStubProtocol.session())
        XCTAssertEqual(bad, .badToken)
        HeadlessStubProtocol.respond = { _ in (200, "<html></html>") }
        let other = await ServerProbe.check(base: base, token: deviceToken, session: HeadlessStubProtocol.session())
        XCTAssertEqual(other, .notCicada)
    }

    // MARK: Two backends on two loopback ports

    func testTheClientTalksToTheServerItWasGivenAndNeverToThisMac() async throws {
        let remote = try LoopbackHTTPServer { path in
            path.hasPrefix("/banks") ? (200, #"{"banks": [{"name": "default", "active": true}], "active": "default"}"#)
                                     : (200, #"{"total": 1, "created": 1, "updated": 0, "skipped": 0}"#)
        }
        let local = try LoopbackHTTPServer { _ in (200, #"{"banks": [], "active": "default"}"#) }
        defer { remote.stop(); local.stop() }
        try "master-token\n".write(to: home.appendingPathComponent("api_token"), atomically: true, encoding: .utf8)
        try (deviceToken + "\n").write(to: home.appendingPathComponent("device_token"), atomically: true, encoding: .utf8)
        let config = URLSessionConfiguration.ephemeral
        config.urlCache = nil
        let session = URLSession(configuration: config)
        let client = APIClient(session: session, connection: server("http://127.0.0.1:\(remote.port)"),
                               runtime: runtime(port: local.port))
        let banks = try await client.fetchBanks()
        XCTAssertEqual(banks.active, "default")
        XCTAssertEqual(remote.requests.count, 1)
        XCTAssertEqual(remote.requests.first?.headers["authorization"], "Bearer \(deviceToken)")
        XCTAssertTrue(local.requests.isEmpty, "a server's client never asks this Mac's backend")

        // The server goes away: a reader's post waits on this Mac, and nothing reaches this Mac's backend.
        let away = try LoopbackHTTPServer { _ in (200, "{}") }
        let gonePort = away.port
        away.stop()
        let offline = APIClient(session: session, connection: server("http://127.0.0.1:\(gonePort)"),
                                runtime: runtime(port: local.port))
        do {
            _ = try await offline.syncNotes(dump: "a note")
            XCTFail("expected the post to wait")
        } catch let error as ServerLinkError {
            XCTAssertEqual(error, .queuedOffline)
        }
        XCTAssertTrue(local.requests.isEmpty)

        // It answers again (here, at the first server's port): the waiting post goes there, signed by this device.
        let back = APIClient(session: session, connection: server("http://127.0.0.1:\(remote.port)"),
                             runtime: runtime(port: local.port))
        let flushed = await back.flushOutbox()
        XCTAssertEqual(flushed.sent, 1)
        XCTAssertEqual(remote.requests.last?.line, "POST /sources/sync-notes HTTP/1.1")
        XCTAssertEqual(remote.requests.last?.headers["authorization"], "Bearer \(deviceToken)")
        XCTAssertTrue(remote.requests.last?.body.contains("a note") == true)
        XCTAssertTrue(local.requests.isEmpty)
    }
}

// MARK: - Doubles

final class FakeDevicesAPI: DevicesAPI, @unchecked Sendable {
    var rows: [DeviceRecord] = []
    var healthy = true
    var waiting = 0
    var created: [String] = []

    func fetchDevices() async throws -> [DeviceRecord] { rows }
    func createDevice(name: String) async throws -> DeviceCreated {
        created.append(name)
        return DeviceCreated(device: DeviceRecord(id: "new00000", name: name, createdAt: ""),
                             token: "cic_dev_new00000_" + String(repeating: "y", count: 43))
    }
    func revokeDevice(id: String) async throws -> DeviceRecord { DeviceRecord(id: id, name: "", createdAt: "", active: false) }
    func fetchHealth() async throws -> HealthSnapshot {
        guard healthy else { throw URLError(.cannotConnectToHost) }
        return try JSONDecoder().decode(HealthSnapshot.self, from: Data(#"{"version": "0.3.0"}"#.utf8))
    }
    func outboxCount() async -> Int { waiting }
    func flushOutbox() async -> ReaderOutbox.FlushResult { ReaderOutbox.FlushResult() }
}

/// A URLProtocol double of its own (not `MockURLProtocol`), so these tests never share a handler with another file's.
final class HeadlessStubProtocol: URLProtocol {
    nonisolated(unsafe) static var respond: ((URLRequest) -> (Int, String))?
    nonisolated(unsafe) static var fail: URLError?
    nonisolated(unsafe) static var requests: [URLRequest] = []
    private static let lock = NSLock()

    static func reset() { lock.withLock { respond = nil; fail = nil; requests = [] } }

    static func session() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HeadlessStubProtocol.self]
        return URLSession(configuration: config)
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        var recorded = request
        if recorded.httpBody == nil, let stream = request.httpBodyStream {
            stream.open()
            var data = Data()
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let n = stream.read(&buffer, maxLength: buffer.count)
                if n <= 0 { break }
                data.append(buffer, count: n)
            }
            stream.close()
            recorded.httpBody = data
        }
        let (fail, respond) = Self.lock.withLock { () -> (URLError?, ((URLRequest) -> (Int, String))?) in
            Self.requests.append(recorded)
            return (Self.fail, Self.respond)
        }
        if let fail {
            client?.urlProtocol(self, didFailWithError: fail)
            return
        }
        let (status, body) = respond?(recorded) ?? (500, "{}")
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

/// A real HTTP/1.1 listener on 127.0.0.1 (an ephemeral port), answering every request with `respond(path)` and keeping
/// what it was sent. A stand-in for a backend: the client under test cannot tell it from one.
final class LoopbackHTTPServer: @unchecked Sendable {
    struct Received { let line: String; let headers: [String: String]; let body: String }

    let port: Int
    private let descriptor: Int32
    private let respond: @Sendable (String) -> (Int, String)
    private let lock = NSLock()
    private var received: [Received] = []
    private var stopped = false
    private let thread: Thread

    var requests: [Received] { lock.withLock { received } }

    init(respond: @escaping @Sendable (String) -> (Int, String)) throws {
        let socket = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard socket >= 0 else { throw POSIXError(.EIO) }
        var reuse: Int32 = 1
        setsockopt(socket, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(socket, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        guard bound == 0, Darwin.listen(socket, 8) == 0 else { Darwin.close(socket); throw POSIXError(.EIO) }
        var size = socklen_t(MemoryLayout<sockaddr_in>.size)
        _ = withUnsafeMutablePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(socket, $0, &size) }
        }
        descriptor = socket
        port = Int(UInt16(bigEndian: address.sin_port))
        self.respond = respond
        var serve: (() -> Void)?
        thread = Thread { serve?() }
        serve = { [weak self] in self?.loop() }
        thread.start()
    }

    func stop() {
        lock.withLock { stopped = true }
        Darwin.shutdown(descriptor, SHUT_RDWR)
        Darwin.close(descriptor)
    }

    private var isStopped: Bool { lock.withLock { stopped } }

    private func loop() {
        while !isStopped {
            var ready = pollfd(fd: descriptor, events: Int16(POLLIN), revents: 0)
            guard Darwin.poll(&ready, 1, 200) > 0 else { continue }
            let client = Darwin.accept(descriptor, nil, nil)
            guard client >= 0 else { continue }
            handle(client)
            Darwin.close(client)
        }
    }

    private func handle(_ client: Int32) {
        var noSignal: Int32 = 1
        setsockopt(client, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size))
        var timeout = timeval(tv_sec: 5, tv_usec: 0)
        setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        var bytes = Data()
        var buffer = [UInt8](repeating: 0, count: 8192)
        var headerEnd: Range<Data.Index>?
        while headerEnd == nil {
            let n = Darwin.recv(client, &buffer, buffer.count, 0)
            guard n > 0 else { return }
            bytes.append(contentsOf: buffer.prefix(n))
            headerEnd = bytes.range(of: Data("\r\n\r\n".utf8))
        }
        guard let end = headerEnd else { return }
        let head = String(decoding: bytes[..<end.lowerBound], as: UTF8.self).components(separatedBy: "\r\n")
        var headers: [String: String] = [:]
        for line in head.dropFirst() {
            guard let colon = line.firstIndex(of: ":") else { continue }
            headers[line[..<colon].lowercased()] = line[line.index(after: colon)...].trimmingCharacters(in: .whitespaces)
        }
        let length = Int(headers["content-length"] ?? "0") ?? 0
        var body = Data(bytes[end.upperBound...])
        while body.count < length {
            let n = Darwin.recv(client, &buffer, buffer.count, 0)
            guard n > 0 else { break }
            body.append(contentsOf: buffer.prefix(n))
        }
        let line = head.first ?? ""
        let path = line.split(separator: " ").dropFirst().first.map(String.init) ?? "/"
        lock.withLock { received.append(Received(line: line, headers: headers, body: String(decoding: body, as: UTF8.self))) }
        let (status, text) = respond(path)
        let payload = Data(text.utf8)
        let response = Data("HTTP/1.1 \(status) OK\r\nContent-Type: application/json\r\nContent-Length: \(payload.count)\r\nConnection: close\r\n\r\n".utf8) + payload
        _ = response.withUnsafeBytes { Darwin.send(client, $0.baseAddress, $0.count, 0) }
    }
}
