import XCTest
@testable import CicadaApp

/// DR-22 / DR-45 / DR-5 — navigation and tab state never spend the accent: selection is
/// brightness plus one neutral fill. The scope grows as the shell and the page tracks add files.
final class SelectionTintLintTests: XCTestCase {
    static let scoped = ["Views/Shell/NavRail.swift", "Views/Common/TextTabs.swift", "Views/Settings/SettingsPanel.swift",
                         "Views/Inbox/InboxQuestionList.swift", "Views/Clusters/ClustersRows.swift",
                         "Views/Common/ListColumns.swift", "Views/Clusters/ClustersViewMenu.swift",
                         "Views/Feed/FeedRows.swift"]
    static let needles = ["CicadaTheme.accent", "CicadaTheme.wash", "CicadaTheme.onAccent", "accentColor"]

    func testNavigationAndTabStateNeverSpendTheAccent() throws {
        let files = try ThemeTokenTests.swiftSources()
        for path in Self.scoped {
            let file = try XCTUnwrap(files.first { $0.path.hasSuffix(path) }, "\(path) is missing — the lint would pass vacuously")
            for (i, line) in try String(contentsOf: file, encoding: .utf8).components(separatedBy: .newlines).enumerated()
            where !line.trimmingCharacters(in: .whitespaces).hasPrefix("//") {
                for needle in Self.needles where line.contains(needle) {
                    XCTFail("\(path):\(i + 1) spends the accent on navigation state (\(needle))")
                }
            }
        }
    }
}
