import AppKit
import XCTest
@testable import CicadaApp

final class SpriteSheetTests: XCTestCase {
    static func fixture(_ name: String = "probe") throws -> SpriteSheet {
        try XCTUnwrap(SpriteSheets.sheet(named: name, in: Bundle.module), "synthetic fixture \(name)")
    }

    func testDecoderReadsMillisecondsTagsSlicesAndSourceSize() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "probe", withExtension: "json", subdirectory: "sprites"))
        let data = try JSONDecoder().decode(AsepriteSheetData.self, from: Data(contentsOf: url))
        XCTAssertEqual(data.frames.map(\.frameMs), [100, 200, 300])
        XCTAssertEqual(data.frames[0].sourceSize.w, 2)
        XCTAssertEqual(data.meta.frameTags[0].direction, "forward")
        XCTAssertEqual(data.meta.slices[0].keys[0].bounds.cgRect, CGRect(x: 0, y: 0, width: 1, height: 1))
    }

    func testDirectionsExpandWithoutDuplicatingEnds() throws {
        let sheet = try Self.fixture()
        XCTAssertEqual(sheet.clip("forward")?.order, [0, 1, 2])
        XCTAssertEqual(sheet.clip("reverse")?.order, [2, 1, 0])
        XCTAssertEqual(sheet.clip("pingpong")?.order, [0, 1, 2, 1])
        XCTAssertEqual(sheet.clip("pingpong_reverse")?.order, [2, 1, 0, 1])
        XCTAssertEqual(sheet.clip("pingpong")?.seconds, [0.1, 0.2, 0.3, 0.2])
    }

    func testCropUsesTopLeftCoordinatesAndDeduplicatedRects() throws {
        let sheet = try Self.fixture()
        XCTAssertEqual(sheet.rectIndex, [0, 1, 0])
        let cg = try XCTUnwrap(sheet.frameImage(1))
        let rep = NSBitmapImageRep(cgImage: cg)
        var pixel = [Int](repeating: 0, count: 4)
        rep.getPixel(&pixel, atX: 0, y: 0)
        XCTAssertEqual(pixel, [0, 0, 255, 255])
        XCTAssertTrue(sheet.frameImage(0) === sheet.frameImage(2))
        XCTAssertNil(sheet.frameImage(-1))
        XCTAssertNil(sheet.frameImage(3))
    }

    func testMissingSheetIsCachedAndNeverCrashes() {
        XCTAssertNil(SpriteSheets.sheet(named: "synthetic-missing", in: Bundle.module))
        XCTAssertNil(SpriteSheets.sheet(named: "synthetic-missing", in: Bundle.module))
    }

    func testCorruptExportsAreMissingSheets() {
        for name in ["bad-json", "bad-png"] {
            XCTAssertNil(SpriteSheets.sheet(named: name, in: Bundle.module))
            XCTAssertNil(SpriteSheets.sheet(named: name, in: Bundle.module))
        }
    }

    func testInvalidFrameAndTagGeometryIsRejected() throws {
        let sheet = try Self.fixture()
        let url = try XCTUnwrap(Bundle.module.url(forResource: "probe", withExtension: "json", subdirectory: "sprites"))
        let original = try Data(contentsOf: url)
        let mutations: [(String, String)] = [
            ("\"duration\": 100", "\"duration\": 0"),
            ("\"x\": 2", "\"x\": 3"),
            ("\"to\": 2", "\"to\": 3"),
            ("\"direction\": \"forward\"", "\"direction\": \"unknown\""),
        ]
        let text = try XCTUnwrap(String(data: original, encoding: .utf8))
        for (before, after) in mutations {
            XCTAssertTrue(text.contains(before))
            let data = try JSONDecoder().decode(AsepriteSheetData.self, from: Data(text.replacingOccurrences(of: before, with: after).utf8))
            XCTAssertNil(SpriteSheet(name: "invalid", data: data, image: sheet.image), before)
        }
    }
}
