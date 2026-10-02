import SwiftUI
import XCTest
@testable import CicadaApp

final class MascotSettingsTests: XCTestCase {
    func testLabelsSearchAndKeyboardSelectionAreTheRealCatalog() throws {
        XCTAssertEqual(Copy.Mascot.title, "Mascot")
        XCTAssertEqual(MascotRegistry.bookworm.selectionLabel(selected: true), "Bookworm, selected")
        XCTAssertEqual(MascotRegistry.bookworm.selectionLabel(selected: false), "Bookworm")
        for query in ["mascot", "bookworm", "avatar"] {
            let entry = SettingsSearchLanding.topHit(query, in: SettingsIndex.staticEntries)
            XCTAssertEqual(entry?.section, .sleep)
            XCTAssertEqual(entry?.anchor, .mascot, query)
        }
        let root = SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp")
        let tile = try String(contentsOf: root.appendingPathComponent("Views/Settings/MascotSettings.swift"))
        XCTAssertTrue(tile.contains("ForEach(MascotRegistry.all)"))
        XCTAssertTrue(tile.contains(".focusable()"))
        XCTAssertTrue(tile.contains(".accessibilityLabel(mascot.selectionLabel(selected: selected))"))
        XCTAssertTrue(tile.contains(".accessibilityAddTraits(selected ? .isSelected : [])"))
        XCTAssertTrue(tile.contains("Image(systemName: \"checkmark\")"))
        XCTAssertTrue(tile.contains("transaction.disablesAnimations = true"))
        XCTAssertFalse(tile.contains("TimelineView") || tile.contains("WindowVisibilityReader"))
        let app = try String(contentsOf: root.appendingPathComponent("CicadaApp.swift"))
        XCTAssertTrue(app.contains(".onChange(of: mascotRaw) { _, _ in menuBarManager.mascotChanged() }"))
        let view = try String(contentsOf: root.appendingPathComponent("Views/Common/BookwormView.swift"))
        XCTAssertTrue(view.contains("@AppStorage(MascotPreference.defaultsKey)"))
        XCTAssertFalse(view.contains("\"bookworm-"))
    }

    func testTileKeyFramesAreVisibleAndHaveTheRequestedTwoSizes() throws {
        for mascot in MascotRegistry.all {
            for (name, tag, size) in [(mascot.roomSheet(.awake), "idle", BookwormArt.roomFrame),
                                      (mascot.menuBarSheet, "awake", BookwormArt.smallFrame)] {
                let sheet = try SpriteTestAssets.sheet(name)
                let clip = try SpriteTestAssets.clip(sheet, tag)
                XCTAssertEqual(sheet.frameSize, size)
                XCTAssertFalse(try SpriteTestAssets.plane(sheet, frame: XCTUnwrap(clip.order.first)).ink.isEmpty)
            }
        }
    }

    @MainActor
    func testRenderMascotPaneInBothAppearancesWithUnknownChoiceFallback() throws {
        let write = ProcessInfo.processInfo.environment["CICADA_WRITE_COMPOSITES"] == "1"
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("cicada-sprite-composites/settings")
        if write { try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true) }
        let suite = "com.cicada.mascot-render.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let saved = CicadaTheme.mode
        defer { CicadaTheme.mode = saved }
        for scheme in AppColorScheme.allCases {
            CicadaTheme.mode = scheme
            for choice in ["bookworm", "missing-character"] {
                defaults.set(choice, forKey: MascotPreference.defaultsKey)
                let pane = MascotSettings()
                    .defaultAppStorage(defaults)
                    .environment(\.spriteSnapshotDate, Date(timeIntervalSince1970: 12 * 3600))
                    .environment(\.scenePaused, true)
                    .padding(24).frame(width: 640).background(CicadaTheme.background)
                let renderer = ImageRenderer(content: pane)
                renderer.scale = 2
                let cg = try XCTUnwrap(renderer.cgImage)
                XCTAssertEqual(cg.width, 1280)
                XCTAssertGreaterThan(cg.height, 200)
                if write {
                    let bytes = try XCTUnwrap(NSBitmapImageRep(cgImage: cg).representation(using: .png, properties: [:]))
                    try bytes.write(to: dir.appendingPathComponent("mascot-\(choice)-\(scheme.rawValue).png"))
                }
            }
        }
    }
}
