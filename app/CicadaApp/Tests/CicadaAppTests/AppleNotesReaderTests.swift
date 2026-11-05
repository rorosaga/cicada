import XCTest
@testable import CicadaApp

/// The app reads Apple Notes; the backend only parses the dump. No test runs the real `osascript` — it would raise
/// macOS's Automation prompt — so every read goes through a fake runner.
final class AppleNotesReaderTests: XCTestCase {
    private func output(status: Int32 = 0, stdout: String = "", stderr: String = "", timedOut: Bool = false)
        -> AppleNotesReader.Output {
        AppleNotesReader.Output(status: status, stdout: stdout, stderr: stderr, timedOut: timedOut)
    }

    func testAReadHandsTheScriptToTheRunnerAndReturnsTheDumpWithoutOsascriptsNewline() async throws {
        let record = ["id-1", "alpha-project", "body", "created", "modified", "Notes"]
            .joined(separator: AppleNotesReader.fieldSeparator)
        let seen = SeenScript()
        let dump = try await AppleNotesReader.read { script, timeout in
            seen.record(script, timeout)
            return AppleNotesReaderTests().output(stdout: record + "\n")
        }
        XCTAssertEqual(dump, record)
        XCTAssertEqual(seen.script, AppleNotesReader.script)
        XCTAssertEqual(seen.timeout, AppleNotesReader.timeout)
    }

    func testARefusedAutomationSaysWhereToTurnItOn() {
        let refused = output(status: 1, stderr: "execution error: Not authorized to send Apple events to Notes. (-1743)")
        XCTAssertEqual(AppleNotesReader.outcome(refused), .failure(.notAllowed))
        XCTAssertTrue(AppleNotesReader.ReadError.notAllowed.localizedDescription.contains("Automation"))
    }

    func testAnyOtherFailureOrATimeoutIsAnErrorAndNeverAnEmptyDump() {
        XCTAssertEqual(AppleNotesReader.outcome(output(status: 1, stderr: "(-600)")), .failure(.failed))
        XCTAssertEqual(AppleNotesReader.outcome(output(status: 127)), .failure(.failed))
        XCTAssertEqual(AppleNotesReader.outcome(output(status: 15, timedOut: true)), .failure(.timedOut))
    }

    func testAnEmptyLibraryIsAnEmptyDump() {
        XCTAssertEqual(AppleNotesReader.outcome(output(stdout: "\n")), .success(""))
    }

    /// `notes_sync.FIELD_SEP` / `RECORD_SEP` on the backend, and the characters the script emits.
    func testTheSeparatorsMatchTheBackendParser() {
        XCTAssertEqual(AppleNotesReader.fieldSeparator.unicodeScalars.map(\.value), [0x1E])
        XCTAssertEqual(AppleNotesReader.recordSeparator.unicodeScalars.map(\.value), [0x1D])
        XCTAssertTrue(AppleNotesReader.script.contains("set FS to (ASCII character 30)"))
        XCTAssertTrue(AppleNotesReader.script.contains("set RS to (ASCII character 29)"))
    }

    // MARK: - G234: locked notes

    /// The owner's "never requested": no event may name a note's `plaintext` (or anything else about it) except through
    /// the filter Notes evaluates itself. Filtering a bulk read afterwards would already have asked for the body.
    func testTheScriptNeverRequestsAnythingButAnIdAndANameOfALockedNote() {
        let script = AppleNotesReader.script
        XCTAssertFalse(script.contains("of every note of fld"), "an unfiltered bulk read asks for locked notes too")
        for property in ["id", "name", "plaintext", "creation date", "modification date"] {
            XCTAssertTrue(script.contains("set \(property == "id" ? "noteIds" : variable(property)) to \(property) of "
                                              + "(every note of fld whose password protected is false)"), property)
        }
        // A locked note yields its id and its name, and nothing else.
        let locked = script.components(separatedBy: .newlines).filter { $0.contains("whose password protected is true") }
            .map { $0.trimmingCharacters(in: .whitespaces) }
        XCTAssertEqual(locked, ["set lockedIds to id of (every note of fld whose password protected is true)",
                                "set lockedNames to name of (every note of fld whose password protected is true)"])
        XCTAssertFalse(script.contains(" body of "), "the HTML body is never asked for")
    }

    private func variable(_ property: String) -> String {
        ["name": "noteNames", "plaintext": "noteBodies", "creation date": "cDates", "modification date": "mDates"][property]!
    }

    /// The bulk lists are separate events: a note locked between them must not misalign one note's text with another's id.
    func testAFolderThatChangedDuringTheReadWaitsForTheNextOne() {
        let script = AppleNotesReader.script
        guard let bodies = script.range(of: "set mDates to"), let after = script.range(of: "set idsAfter to id of"),
              let check = script.range(of: "if idsAfter = noteIds then"), let emit = script.range(of: "set end of outList to (item i") else {
            return XCTFail("the read's order changed")
        }
        XCTAssertTrue(bodies.lowerBound < after.lowerBound && after.lowerBound < check.lowerBound
                      && check.lowerBound < emit.lowerBound)
    }

    func testLockedIdsAndTheTallyNeverReachTheDump() {
        let fs = AppleNotesReader.fieldSeparator, rs = AppleNotesReader.recordSeparator
        let note = ["id-1", "alpha-project", "body", "c", "m", "Notes", "2026-11-01T10:00:00", "0", "iCloud"]
            .joined(separator: fs)
        let lockedId = AppleNotesReader.lockedMark + fs + "id-locked"
        let lockedName = AppleNotesReader.lockedNameMark + fs + "canary-title"
        let raw = [lockedId, lockedName, note, lockedId, lockedName, AppleNotesReader.lockedNameMark + fs + " ",
                   AppleNotesReader.statsMark + fs + "3" + fs + "0" + fs + "0"].joined(separator: rs)
        let parts = AppleNotesReader.split(raw)
        XCTAssertEqual(parts.locked, ["id-locked"])
        XCTAssertEqual(parts.foldersRead, 3)
        XCTAssertEqual(parts.foldersFailed, 0)
        XCTAssertEqual(parts.accounts, ["id-1": "iCloud"])
        XCTAssertEqual(parts.lockedKeys, [AppleNotesReader.lockedKey(name: "canary-title")])
        XCTAssertFalse(parts.lockedKeys.joined().contains("canary-title"))
        XCTAssertFalse(parts.dump.contains("canary-title"))
        XCTAssertFalse(parts.dump.contains("id-locked"))
        XCTAssertFalse(parts.dump.contains(AppleNotesReader.statsMark))
        XCTAssertEqual(parts.dump.components(separatedBy: rs).count, 1)
        XCTAssertEqual(parts.dump.components(separatedBy: fs).count, 8)
    }

    /// "The same read saw it" protects a note only when the read saw every note, so a partial one sends no name keys.
    /// The ids still go: a note's own id is no guess.
    func testNameKeysGoOnlyWithACompleteRead() {
        let fs = AppleNotesReader.fieldSeparator, rs = AppleNotesReader.recordSeparator
        func parts(failed: String, waited: String) -> (keys: [String], locked: [String]) {
            let got = AppleNotesReader.split([AppleNotesReader.lockedMark + fs + "id-locked",
                                              AppleNotesReader.lockedNameMark + fs + "canary-title",
                                              AppleNotesReader.statsMark + fs + "3" + fs + failed + fs + waited]
                .joined(separator: rs))
            return (got.lockedKeys, got.locked)
        }
        XCTAssertEqual(parts(failed: "0", waited: "0").keys.count, 1)
        XCTAssertEqual(parts(failed: "1", waited: "0").keys, [])
        XCTAssertEqual(parts(failed: "0", waited: "1").keys, [])
        XCTAssertEqual(parts(failed: "1", waited: "1").locked, ["id-locked"])
        XCTAssertTrue(AppleNotesReader.script.contains("set waitedFolders to waitedFolders + 1"))
    }

    /// A Notes without the filter refuses every folder: that is a failed read, never "no notes".
    func testEveryFolderRefusedThrowsInsteadOfPostingNothing() async {
        let fs = AppleNotesReader.fieldSeparator
        do {
            _ = try await AppleNotesReader.syncNow { _, _ in
                AppleNotesReaderTests().output(stdout: AppleNotesReader.statsMark + fs + "0" + fs + "4" + fs + "0\n")
            }
            XCTFail("expected a failure")
        } catch {
            XCTAssertEqual(error as? AppleNotesReader.ReadError, .failed)
        }
    }

    /// The same bytes as `notes_sync.locked_key` (`test_locked_notes.py` pins this digest).
    func testALockedKeyMatchesTheBackendsHash() {
        XCTAssertEqual(AppleNotesReader.lockedKey(name: " Caf\u{0065}\u{0301} note\n"),
                       "1fc84b3abc2277e7d078a0b58f2dbf8e84f5d5d91e30059993db72f3e0999314")
    }

    func testThePageLineSaysTheCountAndIsAbsentAtZero() {
        XCTAssertNil(Copy.SourceBrowser.lockedNotes(0))
        XCTAssertEqual(Copy.SourceBrowser.lockedNotes(1), "1 locked note · Cicada can't read it")
        XCTAssertEqual(Copy.SourceBrowser.lockedNotes(12), "12 locked notes · Cicada can't read them")
    }

    func testAnOlderBackendsCollectionsDecodeWithNoLockedCount() throws {
        let tree = try JSONDecoder().decode(ChannelCollections.self, from: Data(#"{"channel":"notes","accounts":[]}"#.utf8))
        XCTAssertEqual(tree.locked, 0)
        let counted = try JSONDecoder().decode(ChannelCollections.self,
                                               from: Data(#"{"channel":"notes","accounts":[],"locked":12}"#.utf8))
        XCTAssertEqual(counted.locked, 12)
    }

    func testThePlistAsksToControlNotesInPlainWords() throws {
        let bundleScript = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("bundle.sh")
        let text = try String(contentsOf: bundleScript, encoding: .utf8)
        XCTAssertEqual(text.components(separatedBy: "<key>NSAppleEventsUsageDescription</key>").count - 1, 1)
        XCTAssertNotNil(text.range(of: "<key>NSAppleEventsUsageDescription</key><string>[^<]{20,}</string>",
                                   options: .regularExpression))
    }
}

private final class SeenScript: @unchecked Sendable {
    private let lock = NSLock()
    private(set) var script = ""
    private(set) var timeout: TimeInterval = 0

    func record(_ script: String, _ timeout: TimeInterval) {
        lock.lock(); defer { lock.unlock() }
        self.script = script
        self.timeout = timeout
    }
}
