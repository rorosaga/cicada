import SwiftUI
import XCTest
@testable import CicadaApp

final class MascotRegistryTests: XCTestCase {
    func testCatalogHasUniqueIDsAndExactlyTheOwnersBookworm() {
        XCTAssertEqual(MascotRegistry.all, [Mascot(id: "bookworm", displayName: "Bookworm",
            roomSheetPrefix: "bookworm-", menuBarSheet: "bookworm-small",
            artFolder: "app/CicadaApp/Art/sprites/bookworm-2026-10-01")])
        XCTAssertEqual(Set(MascotRegistry.all.map(\.id)).count, MascotRegistry.all.count)
        XCTAssertEqual(MascotRegistry.resolve("bookworm"), MascotRegistry.bookworm)
        for id in ["", "removed-mascot", "BOOKWORM"] {
            XCTAssertEqual(MascotRegistry.resolve(id), MascotRegistry.bookworm)
        }
    }

    func testEveryCatalogSheetIsInTheManifestAndHasTheSharedContract() throws {
        let manifest = try JSONDecoder().decode(SpriteAssetTests.Manifest.self,
            from: Data(contentsOf: SpriteTestAssets.url("sprites.manifest", ext: "json")))
        let ids = Set(try manifest.assets.map { try XCTUnwrap($0["id"]) })
        for mascot in MascotRegistry.all {
            var names: Set<String> = [mascot.menuBarSheet]
            for state in BookwormArt.states {
                names.insert(mascot.roomSheet(state))
                for lit in [false, true] { names.insert(mascot.roomSheet(state, lighting: .dark, lampLit: lit)) }
            }
            XCTAssertEqual(names.count, 25)
            XCTAssertTrue(names.isSubset(of: ids), mascot.id)
            for name in names {
                _ = try SpriteTestAssets.url(name, ext: "png")
                _ = try SpriteTestAssets.url(name, ext: "json")
            }
            let artURL = SpriteTestAssets.root.deletingLastPathComponent().deletingLastPathComponent()
                .appendingPathComponent(mascot.artFolder)
            XCTAssertTrue(FileManager.default.fileExists(atPath: artURL.appendingPathComponent("README.md").path))
            for state in BookwormArt.states { for lighting in [RoomLighting.day, .dark] { for lit in [false, true] {
                let sheet = try SpriteTestAssets.sheet(mascot.roomSheet(state, lighting: lighting, lampLit: lit))
                XCTAssertEqual(sheet.frameSize, BookwormArt.roomFrame)
                XCTAssertEqual(Set(sheet.tags.keys), BookwormArt.requiredTags(state), sheet.name)
            } } }
            let small = try SpriteTestAssets.sheet(mascot.menuBarSheet)
            XCTAssertEqual(small.frameSize, BookwormArt.smallFrame)
            XCTAssertEqual(Set(small.tags.keys), BookwormArt.smallRequiredTags())
        }
    }

    func testBookwormNamesAndClipsResolveForEveryStateLightingAndLamp() throws {
        for state in BookwormArt.states { for lighting in [RoomLighting.day, .dark] { for lit in [false, true] {
            let suffix = lighting == .day ? "" : (lit ? "-night-lit" : "-night-dark")
            let name = "bookworm-\(state.caseName)\(suffix)"
            XCTAssertEqual(BookwormArt.sheetName(state, .room, lighting: lighting, lampLit: lit,
                                                 mascot: MascotRegistry.bookworm), name)
            let room = try XCTUnwrap(BookwormArt.clip(state, look: .idle, lighting: lighting, lampLit: lit,
                                                     mascot: MascotRegistry.bookworm))
            XCTAssertEqual(room.0.name, name)
            XCTAssertEqual(room.1.tag, "idle")
            XCTAssertEqual(BookwormArt.sheetName(state, .small, lighting: lighting, lampLit: lit,
                                                 mascot: MascotRegistry.bookworm), "bookworm-small")
            let small = try XCTUnwrap(BookwormArt.clip(state, look: .idle, set: .small,
                                                       lighting: lighting, lampLit: lit, mascot: MascotRegistry.bookworm))
            XCTAssertEqual(small.0.name, "bookworm-small")
            XCTAssertEqual(small.1.tag, state.caseName)
            for transition in [BookwormTransition.yawn, .stretch] {
                let pair = try XCTUnwrap(BookwormArt.transitionClip(transition, lighting: lighting,
                                                                    lampLit: lit, mascot: MascotRegistry.bookworm))
                XCTAssertEqual(pair.0.name, "bookworm-sleeping\(suffix)")
                XCTAssertEqual(pair.1.tag, transition.rawValue)
            }
        } } }
    }

    func testAnExplicitDifferentSkinNeverFallsBackToBookwormSheets() {
        let other = Mascot(id: "test-skin", displayName: "Test", roomSheetPrefix: "test-skin-",
                           menuBarSheet: "test-skin-menu", artFolder: "Art/test")
        for state in BookwormArt.states {
            XCTAssertEqual(BookwormArt.sheetName(state, .room, mascot: other), "test-skin-\(state.caseName)")
            XCTAssertEqual(BookwormArt.sheetName(state, .room, lighting: .dark, lampLit: true, mascot: other),
                           "test-skin-\(state.caseName)-night-lit")
            XCTAssertEqual(BookwormArt.sheetName(state, .small, mascot: other), "test-skin-menu")
            XCTAssertNil(BookwormArt.clip(state, look: .idle, mascot: other))
            XCTAssertNil(BookwormArt.clip(state, look: .idle, set: .small, mascot: other))
        }
        XCTAssertNil(BookwormArt.transitionClip(.yawn, mascot: other))
        XCTAssertNil(BookwormArt.transitionClip(.stretch, mascot: other))
        XCTAssertEqual(BookwormArt.coverIndex(at: SpriteClock.origin.addingTimeInterval(100), profile: .full, mascot: other), 1)
    }

    @MainActor
    func testAppStorageChoicePersistsAndUnknownIDFallsBackWithoutTouchingViewerDefaults() throws {
        let suite = "com.cicada.mascot-test.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let choice = AppStorage(wrappedValue: MascotRegistry.bookworm.id, MascotPreference.defaultsKey, store: defaults)
        XCTAssertEqual(choice.wrappedValue, "bookworm")
        XCTAssertEqual(MascotPreference.selected(in: defaults), MascotRegistry.bookworm)
        choice.wrappedValue = "bookworm"
        let reopened = try XCTUnwrap(UserDefaults(suiteName: suite))
        XCTAssertEqual(reopened.string(forKey: MascotPreference.defaultsKey), "bookworm")
        choice.wrappedValue = "missing-character"
        XCTAssertEqual(reopened.string(forKey: MascotPreference.defaultsKey), "missing-character")
        XCTAssertEqual(MascotPreference.selected(in: reopened), MascotRegistry.bookworm)
        XCTAssertEqual(MascotRegistry.resolve(choice.wrappedValue).selectionLabel(selected: true), "Bookworm, selected")
    }
}
