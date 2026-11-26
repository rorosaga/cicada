import AppKit
import SwiftUI
import XCTest
@testable import CicadaApp

/// The PR screenshots of Settings → Privacy & data → "Folders its agent may read", rendered offscreen (an `NSHostingView` in a
/// never-shown window — never the running app) from a JSON dump of a scratch backend's `GET /settings/agent-folders`.
/// Skipped unless `AGENT_FOLDERS_RENDER_DIR` names a folder holding `folders.json`; the PNGs land beside it, light and dark.
@MainActor
final class AgentReadFoldersRenderTests: XCTestCase {
    func testRenderTheListInBothAppearances() async throws {
        guard let dir = ProcessInfo.processInfo.environment["AGENT_FOLDERS_RENDER_DIR"], !dir.isEmpty else {
            throw XCTSkip("set AGENT_FOLDERS_RENDER_DIR to render the agent folders screenshots")
        }
        let base = URL(fileURLWithPath: dir)
        let response = try JSONDecoder().decode(AgentReadFoldersResponse.self,
                                                from: Data(contentsOf: base.appendingPathComponent("folders.json")))
        let store = Store(cache: SnapshotCache(root: FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)), api: FakeSyncAPI())
        CicadaTheme.uiScale = 1.0
        let held = CicadaTheme.mode
        defer { CicadaTheme.mode = held }
        for dark in [false, true] {
            CicadaTheme.mode = dark ? .dark : .light
            let scheme: ColorScheme = dark ? .dark : .light
            let model = AgentReadFoldersModel(deps: .init(load: { response }, set: { _, _ in response },
                                                          add: { _ in response }, remove: { _ in response }))
            await model.load()
            let view = AgentReadFoldersGroup(model: model)
                .padding(CicadaTheme.spacingXL)
                .frame(width: 640, alignment: .topLeading)
                .background(CicadaTheme.bgBase)
                .environment(store)
                .environment(\.colorScheme, scheme)
            let host = NSHostingView(rootView: view)
            host.frame = CGRect(origin: .zero, size: CGSize(width: 640, height: 640))
            host.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
            window.appearance = host.appearance
            window.contentView = host
            host.layoutSubtreeIfNeeded()
            RunLoop.main.run(until: Date().addingTimeInterval(0.4))
            host.layoutSubtreeIfNeeded()
            let fit = host.fittingSize
            host.frame = CGRect(origin: .zero, size: CGSize(width: 640, height: min(max(fit.height, 200), 900)))
            host.layoutSubtreeIfNeeded()
            let rep = try XCTUnwrap(host.bitmapImageRepForCachingDisplay(in: host.bounds))
            host.cacheDisplay(in: host.bounds, to: rep)
            let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
            try png.write(to: base.appendingPathComponent("agent-folders-\(dark ? "dark" : "light").png"))
        }
    }
}
