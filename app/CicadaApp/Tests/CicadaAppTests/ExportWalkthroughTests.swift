import XCTest
@testable import CicadaApp

/// R-OB21 — *See how* is data: chat-exports.md's captions, the one table of export links, a camera that walks one
/// step every three seconds, and nothing moving under Reduce Motion.
final class ExportWalkthroughTests: XCTestCase {
    func testEveryCaptionIsEightWordsOrFewerAndASentence() {
        for caption in ExportWalkthrough.allCaptions {
            XCTAssertLessThanOrEqual(caption.split(separator: " ").count, 8, caption)
            XCTAssertTrue(caption.hasSuffix("."), caption)
        }
    }

    func testTheStepsAreChatExportsMds() {
        XCTAssertEqual(ChatVendor.allCases.map { ExportWalkthrough.scene($0).steps.count }, [7, 7, 11])
    }

    func testThePageItOpensIsTheOneExportTable() {
        for vendor in ChatVendor.allCases {
            let scene = ExportWalkthrough.scene(vendor)
            XCTAssertEqual(scene.exportURL, vendor.walkthrough.exportURL)
            XCTAssertEqual(scene.exportURL.scheme, "https")
            XCTAssertTrue(scene.exportURL.host?.hasSuffix(scene.host) == true, "\(vendor): the address bar is the page's")
        }
    }

    /// chat-exports.md §3 — Takeout's "Gemini" product is Gems configs, not chats; the walkthrough must say Gemini Apps.
    func testGeminiNamesGeminiAppsNotTheGeminiProduct() {
        let gemini = ExportWalkthrough.scene(.gemini)
        XCTAssertTrue(gemini.steps.contains { $0.caption.contains("Gemini Apps") })
        XCTAssertTrue(gemini.path.contains("Gemini Apps"))
    }

    func testTheCameraWalksOneStepEveryThreeSecondsAndLoops() {
        let chat = ExportWalkthrough.scene(.chatgpt)
        XCTAssertEqual(ExportWalkthrough.frame(at: 0, scene: chat, reduceMotion: false).step, 0)
        XCTAssertEqual(ExportWalkthrough.frame(at: 3.0, scene: chat, reduceMotion: false).step, 1)
        XCTAssertEqual(ExportWalkthrough.frame(at: 20.9, scene: chat, reduceMotion: false).step, 6)
        XCTAssertEqual(ExportWalkthrough.frame(at: 21.0, scene: chat, reduceMotion: false).step, 0, "it loops")
        XCTAssertEqual(ExportWalkthrough.frame(at: -5, scene: chat, reduceMotion: false).step, 0, "a clock skew never traps")
    }

    func testTheCameraGlidesThenHoldsAndThePointerLandsOnTheTarget() {
        let chat = ExportWalkthrough.scene(.chatgpt)
        let step = chat.steps[1]
        let start = ExportWalkthrough.frame(at: 3.0, scene: chat, reduceMotion: false)
        XCTAssertEqual(start.scale, chat.steps[0].zoom, accuracy: 0.001, "it glides from where the last step held")
        let held = ExportWalkthrough.frame(at: 3.0 + CicadaMotion.walkthroughGlide, scene: chat, reduceMotion: false)
        XCTAssertEqual(held.scale, step.zoom, accuracy: 0.001)
        XCTAssertEqual(held.focus.x, step.target.midX, accuracy: 0.001)
        let landed = ExportWalkthrough.frame(at: 3.0 + CicadaMotion.walkthroughPointer, scene: chat, reduceMotion: false)
        XCTAssertEqual(landed.pointer?.x ?? -1, step.target.midX, accuracy: 0.001)
        XCTAssertEqual(held.overlay, .menu)
    }

    func testReduceMotionNeverZoomsOrMovesAPointer() {
        let gemini = ExportWalkthrough.scene(.gemini)
        for t in stride(from: 0.0, through: 33.0, by: 0.7) {
            let f = ExportWalkthrough.frame(at: t, scene: gemini, reduceMotion: true)
            XCTAssertEqual(f.scale, 1)
            XCTAssertNil(f.pointer)
            XCTAssertEqual(f.ringOpacity, 1, "the target is ringed in place")
        }
    }

    func testTheRingPulsesOnceAfterThePointerLands() {
        XCTAssertEqual(ExportWalkthrough.ringOpacity(1.0), 0)
        XCTAssertEqual(ExportWalkthrough.ringOpacity(1.9), 1, accuracy: 0.01)
        XCTAssertEqual(ExportWalkthrough.ringOpacity(2.5), 0)
    }

    func testThePagesEdgeNeverShows() {
        let size = CGSize(width: 700, height: 400)
        XCTAssertEqual(WalkthroughGeometry.offset(size: size, scale: 1, focus: CGPoint(x: 0.9, y: 0.9)), .zero)
        XCTAssertEqual(WalkthroughGeometry.offset(size: size, scale: 2, focus: .zero), .zero)
        XCTAssertEqual(WalkthroughGeometry.offset(size: size, scale: 2, focus: CGPoint(x: 1, y: 1)),
                       CGSize(width: -700, height: -400))
    }

    /// Never a screenshot or a copy of a vendor's UI: the vendor appears only as its real mark and name.
    func testTheSheetDrawsAWireframeAndTheVendorsRealMark() throws {
        let file = try XCTUnwrap(ThemeTokenTests.swiftSources().first { $0.path.hasSuffix("Views/Onboarding/ExportWalkthroughSheet.swift") })
        let text = try String(contentsOf: file, encoding: .utf8)
        XCTAssertTrue(text.contains("VendorMark("))
        XCTAssertFalse(text.contains("Image(\""), "no bundled picture of anyone's UI")
        XCTAssertFalse(text.contains("NSImage(named"))
    }
}
