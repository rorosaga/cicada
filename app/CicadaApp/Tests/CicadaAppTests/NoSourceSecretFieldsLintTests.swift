import XCTest
@testable import CicadaApp

/// Owner 2026-11-05 (ROR-113): "Any one that you ask for a token, find a way to sync it properly, either direct
/// integration, syncing some other type of way, or browser as last resort." So no source a person sees offers a secret
/// field: a source connects by its own sign-in in the browser, by the Mac's own readers, by a file, or not at all.
/// A source lint, because "a view drew a SecureField" is a fact about the source. The scope is every file where a
/// source is added, connected or set up; the engine and device settings are not sources and are not in it.
final class NoSourceSecretFieldsLintTests: XCTestCase {
    /// The short named exceptions: a password the person types for their own account's second step, held in memory for
    /// that call and never saved (Telegram's two-step verification, ruling 47a).
    private static let exceptions: Set<String> = ["ChatSourceRows.swift"]

    private func inScope(_ file: URL) -> Bool {
        let path = file.path
        return path.contains("/Views/Sources/") || path.contains("/Views/Capture/")
            || path.contains("/Views/Onboarding/SourcesStep.swift") || path.contains("/Views/Onboarding/SavedListsStep.swift")
            || path.contains("/Theme/Copy+GitHub.swift") || path.contains("/Theme/Copy+Connect.swift")
            || path.contains("/Views/Settings/IntegrationsView.swift") || path.contains("/Views/Settings/ChatSourceRows.swift")
    }

    private func code(_ file: URL) throws -> [(Int, String)] {
        try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            .map { ($0.offset + 1, $0.element) }
            .filter { !$0.1.trimmingCharacters(in: .whitespaces).hasPrefix("//") }
    }

    func testNoSourceSurfaceDrawsASecretField() throws {
        var offenders: [String] = []
        var scanned = 0
        for file in try ThemeTokenTests.swiftSources() where inScope(file) {
            scanned += 1
            guard !Self.exceptions.contains(file.lastPathComponent) else { continue }
            for (n, line) in try code(file) where line.contains("SecureField(") {
                offenders.append("\(file.lastPathComponent):\(n)")
            }
        }
        XCTAssertGreaterThan(scanned, 5, "the lint must see the source surfaces")
        XCTAssertEqual(offenders, [], "a source connects by sign-in, reader or file; it never asks for a secret (ROR-113)")
    }

    func testNoSourceCopyAsksForATokenKeyOrSecret() throws {
        let asks = try NSRegularExpression(
            pattern: #"(paste|enter|add|type)\s+(your\s+|a\s+|the\s+|an\s+)?(api\s+)?(token|key|secret|client\s*id|app\s*id|password)|secrets\.env|use a token"#,
            options: .caseInsensitive)
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where inScope(file) && !Self.exceptions.contains(file.lastPathComponent) {
            for (n, line) in try code(file) {
                let range = NSRange(location: 0, length: (line as NSString).length)
                if asks.firstMatch(in: line, range: range) != nil { offenders.append("\(file.lastPathComponent):\(n)") }
            }
        }
        XCTAssertEqual(offenders, [], "no source page tells the person to paste or file a secret (ROR-113)")
    }

    func testTheConnectorPanelDrawsNoField() throws {
        let panel = try ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "ConnectorSetupPanel.swift" }
        let text = try String(contentsOf: XCTUnwrap(panel), encoding: .utf8)
        XCTAssertFalse(text.contains("TextField(") || text.contains("SecureField("))
    }
}
