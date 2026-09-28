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
