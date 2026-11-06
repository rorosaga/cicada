import XCTest
@testable import CicadaApp

/// 2026-11-06 — a stranger's first engine and first file. The plan row says what to run when its tool isn't on the Mac
/// and notices when it arrives; a file that doesn't go in is named, explained and never read out of an exception.
final class FirstEngineAndFileTests: XCTestCase {
    // MARK: The plan row

    private func connection(_ id: String, available: Bool, next: String? = nil, detail: String? = nil) -> ConnectionStatus {
        var c = ConnectionStatus(id: id, label: id, kind: "subscription", available: available, connected: false,
                                 plan: nil, planLabel: nil, tier: nil, account: nil, priceUsdMonth: nil, priceNote: nil,
                                 billing: "subscription", engineRole: nil, detail: detail, login: nil)
        c.nextCommand = next
        return c
    }

    func testTheBackendsInstallLineDecodesAndMakesTheRowAskForIt() throws {
        let json = #"{"id":"claude-plan","label":"Claude plan","kind":"subscription","available":false,"connected":false,"#
            + #""detail":"Claude Code is not installed on this Mac.","nextCommand":"curl -fsSL https://claude.ai/install.sh | bash"}"#
        let row = try JSONDecoder().decode(ConnectionStatus.self, from: Data(json.utf8))
        XCTAssertTrue(row.needsInstall)
        XCTAssertEqual(IntelligenceRow.installLine(for: row, isKey: false, isLocal: false),
                       "curl -fsSL https://claude.ai/install.sh | bash")
    }

    func testARowWhoseToolIsHereOrWhichIsNotAPlanAsksForNothing() {
        let here = connection("claude-plan", available: true, next: "curl x | bash")
        XCTAssertFalse(here.needsInstall)
        XCTAssertNil(IntelligenceRow.installLine(for: here, isKey: false, isLocal: false))
        let older = connection("claude-plan", available: false)       // an older backend sends no line
        XCTAssertNil(IntelligenceRow.installLine(for: older, isKey: false, isLocal: false))
        let missing = connection("chatgpt-plan", available: false, next: "curl y | sh")
        XCTAssertNil(IntelligenceRow.installLine(for: missing, isKey: true, isLocal: false), "a key row")
        XCTAssertNil(IntelligenceRow.installLine(for: missing, isKey: false, isLocal: true), "a local model")
        XCTAssertNil(IntelligenceRow.installLine(for: nil, isKey: false, isLocal: false))
    }

    func testTheRowReadsNotInstalledNotNotConnectedAndSaysWhereToPasteIt() {
        XCTAssertEqual(Copy.Intelligence.notInstalled, "Not installed")
        XCTAssertEqual(Copy.Intelligence.pasteInTerminal, "Paste this in Terminal.")
    }

    private func card(_ id: String, label: String, available: Bool, next: String? = nil, notReady: Bool = false)
        -> SleepEngineCandidate {
        var c = SleepEngineCandidate(id: id, label: label, available: available, connected: false, models: [], detail: nil)
        c.nextCommand = next
        c.notReady = notReady
        return c
    }

    func testHomesPlanCardsLeadToTheSameFix() {
        let cards = [card("agent", label: "Claude plan", available: false, next: "curl a | bash"),
                     card("codex", label: "ChatGPT plan", available: false, next: "curl b | sh"),
                     card("local", label: "Ollama", available: false)]
        XCTAssertEqual(EngineOption.installHint(cards), "To use your Claude plan or ChatGPT plan, install it in")
        XCTAssertNil(EngineOption.installHint([card("agent", label: "Claude plan", available: true)]), "installed")
        XCTAssertNil(EngineOption.installHint([card("agent", label: "Claude plan", available: false)]), "no line to give")
        XCTAssertNil(EngineOption.installHint([card("cursor", label: "Cursor", available: false, next: "z")]),
                     "the person's own tools keep their own row")
    }

    func testTheAppAsksAgainOnReturnOnlyWhileAToolIsStillMissing() {
        let missing = connection("claude-plan", available: false, next: "curl a | bash")
        let here = connection("claude-plan", available: true)
        XCTAssertTrue(MissingTools.waiting(connections: [missing], candidates: []))
        XCTAssertTrue(MissingTools.waiting(connections: [here],
                                           candidates: [card("codex", label: "ChatGPT plan", available: false, next: "c")]))
        XCTAssertFalse(MissingTools.waiting(connections: [here], candidates: []), "nothing missing: no probe on activation")
        XCTAssertFalse(MissingTools.waiting(connections: [], candidates: [card("cursor", label: "Cursor", available: false,
                                                                                next: "x", notReady: true)]),
                       "an app that is here but not ready is not an install")
    }

    // MARK: A file that does not go in

    func testNoFrameworkSentenceReachesThePerson() {
        let timedOut = IntakeFailureWords.reason(URLError(.timedOut))
        XCTAssertEqual(timedOut, Copy.intakeStoppedWaiting)
        XCTAssertFalse(timedOut.contains("The request timed out"))
        XCTAssertEqual(IntakeFailureWords.reason(URLError(.networkConnectionLost)), Copy.intakeBackendGone)
        XCTAssertEqual(IntakeFailureWords.reason(CocoaError(.fileReadNoPermission)), Copy.intakeCannotOpen)
        XCTAssertEqual(IntakeFailureWords.reason(APIError.decodingError("keyNotFound(CodingKeys…)")), Copy.intakeCouldNotRead)
        XCTAssertEqual(IntakeFailureWords.reason(IntakeRouterError.job("OSError: disk full")), Copy.intakeWriteStopped)
        XCTAssertEqual(IntakeFailureWords.reason(NSError(domain: "x", code: 1)), Copy.intakeCouldNotRead)
        XCTAssertEqual(IntakeFailureWords.reason(APIError.httpError(500, "Internal Server Error")), Copy.intakeCouldNotRead)
    }

    func testASentenceTheBackendWroteForThePersonPassesThrough() {
        let body = #"{"detail":"This zip is damaged or didn't finish downloading. Download the export again, then drop the whole .zip."}"#
        XCTAssertEqual(IntakeFailureWords.reason(APIError.httpError(400, body)),
                       "This zip is damaged or didn't finish downloading. Download the export again, then drop the whole .zip.")
        XCTAssertEqual(IntakeFailureWords.reason(APIError.httpError(422, #"{"detail":[{"msg":"field required"}]}"#)),
                       Copy.intakeCouldNotRead, "a validation list is not for a person")
    }

    func testWhenEveryFileFailsEachOneIsNamedWithItsReason() {
        let a = URL(fileURLWithPath: "/tmp/conversations.json"), b = URL(fileURLWithPath: "/tmp/export-1.zip")
        let c = URL(fileURLWithPath: "/tmp/c.json"), d = URL(fileURLWithPath: "/tmp/d.json"), e = URL(fileURLWithPath: "/tmp/e.json")
        let results = [IntakeFileSniff(url: a, sniff: IntakeSniff(recognized: false, reason: "This file is damaged or was cut short.")),
                       IntakeFileSniff(url: b, error: Copy.intakeBackendGone)]
        guard case .failed(let text) = IntakePreview.aggregate(results, capped: false) else { return XCTFail("fails") }
        XCTAssertEqual(text, "conversations.json: This file is damaged or was cut short.\nexport-1.zip: \(Copy.intakeBackendGone)")
        let five = [a, b, c, d, e].map { IntakeFileSniff(url: $0, error: "no") }
        guard case .failed(let many) = IntakePreview.aggregate(five, capped: false) else { return XCTFail("fails") }
        XCTAssertEqual(many.split(separator: "\n").count, 4)
        XCTAssertTrue(many.hasSuffix("and 2 more"))
    }

    func testAPartiallyFailedImportNamesTheFilesNotJustThatSomeFailed() {
        XCTAssertEqual(Copy.intakeSomeFailed(["a.zip"]), "a.zip wasn't imported")
        XCTAssertEqual(Copy.intakeSomeFailed(["a.zip", "b.json"]), "2 files weren't imported: a.zip, b.json")
    }

    func testABigFileIsSaidBeforeTheWaitNotAfterIt() throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("fe-big-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let small = dir.appendingPathComponent("small.json"), big = dir.appendingPathComponent("conversations.json")
        try Data("[]".utf8).write(to: small)
        FileManager.default.createFile(atPath: big.path, contents: nil)
        let handle = try FileHandle(forWritingTo: big)
        try handle.truncate(atOffset: UInt64(IntakeFailureWords.bigFileBytes) + 1)   // sparse: no disk used
        try handle.close()
        XCTAssertNil(IntakeFailureWords.bigFileNote([small]))
        let note = try XCTUnwrap(IntakeFailureWords.bigFileNote([small, big]))
        XCTAssertTrue(note.hasPrefix("conversations.json is "), note)
        XCTAssertTrue(note.hasSuffix("A file this big takes a few minutes."), note)
    }

    func testTheUploadWaitOutlastsTheMeasuredReadOfABigExport() {
        // 150 MB: 110 s to sniff and 3.5 min to import on a busy Mac. The default 60 s ended it with a false failure.
        XCTAssertGreaterThan(APIClient.uploadTimeout, 15 * 60)
    }

    // MARK: A watched folder's skipped files

    func testAFolderNamesWhatItLeftOut() {
        XCTAssertNil(LocalSourceCopy.skipped(tooLarge: [], unreadable: []))
        XCTAssertEqual(LocalSourceCopy.skipped(tooLarge: ["notes/big.txt"], unreadable: []),
                       "big.txt is over 2 MB, so Cicada skipped it.")
        XCTAssertEqual(LocalSourceCopy.skipped(tooLarge: [], unreadable: ["locked.md"]),
                       "Cicada couldn't open locked.md, so it skipped it.")
        XCTAssertEqual(LocalSourceCopy.skipped(tooLarge: ["a/big.txt", "b.txt"], unreadable: ["locked.md"]),
                       "Cicada skipped 3 files, starting with big.txt: over 2 MB, or not openable.")
    }

    func testTheScannerReportsTheFilesItLeftOut() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("fe-folder-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try Data("hello".utf8).write(to: root.appendingPathComponent("ok.md"))
        try Data("x".utf8).write(to: root.appendingPathComponent("huge.md"))
        let current = ["ok.md": FolderFileStat(size: 5, modified: 1),
                       "huge.md": FolderFileStat(size: FolderScanner.maxFileBytes + 1, modified: 1),
                       "gone.md": FolderFileStat(size: 3, modified: 1)]
        let read = FolderScanner.readUploads(root: root, changed: ["gone.md", "huge.md", "ok.md"], current: current, manifest: [:])
        XCTAssertEqual(read.uploads.map(\.relpath), ["ok.md"])
        XCTAssertEqual(read.tooLarge, ["huge.md"])
        XCTAssertEqual(read.unreadable, ["gone.md"])
        XCTAssertNotNil(LocalSourceCopy.skipped(tooLarge: read.tooLarge, unreadable: read.unreadable))
    }
}
