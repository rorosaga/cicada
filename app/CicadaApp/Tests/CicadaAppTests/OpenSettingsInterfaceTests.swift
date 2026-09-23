import SwiftUI
import XCTest
@testable import CicadaApp

/// Spike O0, static half (R-O2). `OpenSettingsAction` is public SwiftUI API
/// from macOS 14.0 — the 26.1 SDK's interface declares both the struct and
/// `EnvironmentValues.openSettings` `@available(macOS 14.0, *)`. This probe
/// compiling at the package's macOS 14 deployment target with no
/// `#available` guard is the proof. Whether calling it opens the Settings
/// scene is the runtime half, run by the orchestrator and recorded in the
/// design doc's A5; until then nothing in `Sources/` may call it
/// (`EmptyStateView`'s rule).
private struct OpenSettingsProbe: View {
    @Environment(\.openSettings) private var openSettings
    var body: some View { Button("probe") { openSettings() } }
}

final class OpenSettingsInterfaceTests: XCTestCase {
    func testOpenSettingsIsReachableAtTheDeploymentTarget() {
        _ = OpenSettingsProbe()
    }

    func testNoSourceCallsOpenSettingsBeforeTheRuntimeSpikePasses() throws {
        for file in try ThemeTokenTests.swiftSources() {
            let text = try String(contentsOf: file, encoding: .utf8)
            XCTAssertFalse(text.contains("\\.openSettings)"),
                           "\(file.lastPathComponent) reads openSettings — R-O2 keeps it out until A5 records the spike")
        }
    }
}
