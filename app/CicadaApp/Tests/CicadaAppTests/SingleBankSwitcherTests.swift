import XCTest
@testable import CicadaApp

/// DR-24 — one bank selector, in the command bar. Two switcher VIEWS is the split-brain class
/// (CLAUDE.md): each drifts to its own idea of the active bank. The palette's "Switch to
/// <bank>" row and the intake card's switch are actions on the SAME `BanksViewModel` in the
/// SAME window, so they stay (R-DS19); Settings never switches banks.
final class SingleBankSwitcherTests: XCTestCase {
    func testTheSelectorIsBuiltInExactlyOnePlace() throws {
        var builders: [String] = []
        for file in try ThemeTokenTests.swiftSources() {
            let count = try String(contentsOf: file, encoding: .utf8).components(separatedBy: "BankSwitcher(banksVM:").count - 1
            if count > 0 { builders.append("\(file.lastPathComponent)×\(count)") }
        }
        XCTAssertEqual(builders, ["CommandBar.swift×1"])
    }

    func testOnlyTheKnownDoorsSwitchBanks() throws {
        let allowed: Set = ["BankSwitcher.swift", "ContentView.swift", "IntakeDoneCard.swift"]
        for file in try ThemeTokenTests.swiftSources() where !allowed.contains(file.lastPathComponent) {
            XCTAssertFalse(try String(contentsOf: file, encoding: .utf8).contains("banksVM.activate("), file.lastPathComponent)
        }
        for file in try ThemeTokenTests.swiftSources() where file.path.contains("/Views/Settings/") {
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains("BankSwitcher(") || text.contains(".activate("), "\(file.lastPathComponent): Settings never switches banks")
        }
    }
}
