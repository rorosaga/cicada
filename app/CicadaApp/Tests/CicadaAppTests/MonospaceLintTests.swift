import XCTest
@testable import CicadaApp

/// DR-19 — monospace is only for what a person would copy: code, commands, paths, keys,
/// hashes, ids. Never a tag, a pill, a label, a date, a count or a key hint (R-DS10). Each
/// allowed file says why; a file that stops needing it must leave the list.
final class MonospaceLintTests: XCTestCase {
    static let allowed: [String: String] = [
        "Theme/CicadaTheme.swift": "defines monoFont",
        "Views/Common/CommandBox.swift": "a command the person copies",
        "Views/Common/DiffView.swift": "diff lines and their line numbers",
        "Views/Common/MarkdownBody.swift": "fenced code blocks",
        "Views/Common/FoundRow.swift": "the exact paths and commands shown before consent",
        "Views/Common/VideoPlayerView.swift": "a local file path",
        "Views/Settings/LocalSourceRows.swift": "watched folder paths",
        "Views/Settings/SkillConsentSheet.swift": "an installer's output",
        "Views/Settings/AdvancedView.swift": "environment variable names",
        "Views/Home/GettingStartedCard.swift": "the refused paths, shown to inspect",
        "Views/Intake/OnThisMacStrip.swift": "the refused paths, shown to inspect",
        "Views/Graph/EntityDetailCard.swift": "repo paths, commit hashes, branch names, the raw markdown source",
        "Views/Connections/DeviceCodeLogin.swift": "a device code the person types",
        "Views/Connect/RemoteAccessView.swift": "an HTTPS address the person pastes",
    ]
    static let needles = ["design: .monospaced", "monoFont"]

    func testMonospaceIsOnlyForWhatAPersonWouldCopy() throws {
        var offenders: [String] = []
        for file in try ThemeTokenTests.swiftSources() where !Self.allowed.keys.contains(where: { file.path.hasSuffix($0) }) {
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") && Self.needles.contains(where: line.contains) {
                offenders.append("\(file.lastPathComponent):\(i + 1)")
            }
        }
        XCTAssertEqual(offenders, [], "DR-19 — SF (with .monospacedDigit() for a number), not mono")
    }

    func testEveryAllowedFileStillNeedsIt() throws {
        let files = try ThemeTokenTests.swiftSources()
        for path in Self.allowed.keys {
            let file = try XCTUnwrap(files.first { $0.path.hasSuffix(path) }, "\(path) is gone — drop it")
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertTrue(Self.needles.contains(where: text.contains), "\(path) no longer uses mono — drop it")
        }
    }
}
