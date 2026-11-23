import XCTest

/// 2026-11-23 — tests make settings suites only through `TestDefaults`, so none lands in `~/Library/Preferences`
/// (about 60,000 had: `removePersistentDomain` empties a suite but leaves its file behind).
final class TestDefaultsLintTests: XCTestCase {
    func testEverySuiteATestMakesGoesThroughTestDefaults() throws {
        let tests = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        let walker = try XCTUnwrap(FileManager.default.enumerator(at: tests, includingPropertiesForKeys: nil))
        var offenders: [String] = []
        for case let file as URL in walker where file.pathExtension == "swift" {
            guard file.lastPathComponent != "TestDefaults.swift",
                  file.lastPathComponent != "TestDefaultsLintTests.swift" else { continue }
            let text = try String(contentsOf: file, encoding: .utf8)
            for (i, line) in text.components(separatedBy: "\n").enumerated()
            where line.contains("UserDefaults(suiteName:")
                || (line.contains("removePersistentDomain(forName:") && !line.contains("TestDefaults.path(")) {
                offenders.append("\(file.lastPathComponent):\(i + 1)")
            }
        }
        XCTAssertEqual(offenders, [], "use TestDefaults.suite(_:) and TestDefaults.path(_:)")
    }

    func testASuiteLivesInTheRunsOwnFolderAndNeverInPreferences() throws {
        let name = "TestDefaultsLintTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(TestDefaults.suite(name))
        defaults.set("x", forKey: "k")
        XCTAssertEqual(TestDefaults.suite(name)?.string(forKey: "k"), "x", "reopened by name, the same suite")
        XCTAssertTrue(TestDefaults.path(name).hasPrefix(TestDefaults.parent.path))
        defaults.removePersistentDomain(forName: TestDefaults.path(name))
        XCTAssertNil(TestDefaults.suite(name)?.string(forKey: "k"))
        let prefs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Preferences")
        XCTAssertFalse(FileManager.default.fileExists(atPath: prefs.appendingPathComponent("\(name).plist").path))
    }
}
