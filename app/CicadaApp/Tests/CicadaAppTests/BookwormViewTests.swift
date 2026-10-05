import XCTest
@testable import CicadaApp

final class BookwormViewTests: XCTestCase {
    func testSharedArtFrameIsOneLabelledImageForEverySize() throws {
        let source = SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp/Views/Common/BookwormView.swift")
        let text = try String(contentsOf: source)
        let frame = try XCTUnwrap(text.range(of: ".frame(width: size.size.width, height: size.size.height)"))
        let caption = try XCTUnwrap(text.range(of: "if let caption", range: frame.upperBound..<text.endIndex))
        let artFrame = text[frame.lowerBound..<caption.lowerBound]
        let visibility = try XCTUnwrap(artFrame.range(of: ".background { if snapshotDate == nil { WindowVisibilityReader { windowVisible = $0 } } }"))
        let element = try XCTUnwrap(artFrame.range(of: ".accessibilityElement(children: .ignore)"),
                                  "the shared frame must expose an element even for decorative or missing art")
        let image = try XCTUnwrap(artFrame.range(of: ".accessibilityAddTraits(.isImage)"))
        let label = try XCTUnwrap(artFrame.range(of: ".accessibilityLabel(\"\\(state.title) — \\(state.detail)\")"))
        XCTAssertLessThan(visibility.lowerBound, element.lowerBound)
        XCTAssertLessThan(element.lowerBound, image.lowerBound)
        XCTAssertLessThan(image.lowerBound, label.lowerBound)

        // The Sleep room deliberately supplies the text twin through its hotspot instead.
        let room = try String(contentsOf: SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp/Views/Sleep/StudyRoom.swift"))
        let stage = try XCTUnwrap(room.range(of: "struct WormStage: View"))
        let pose = try XCTUnwrap(room.range(of: "static func pose", range: stage.upperBound..<room.endIndex))
        let stageBody = room[stage.lowerBound..<pose.lowerBound]
        XCTAssertTrue(stageBody.contains(".accessibilityHidden(true)"))
        XCTAssertFalse(stageBody.contains(".task(id:"), "lighting swaps must not restart beat/transition lifetimes")
        XCTAssertTrue(room[..<stage.lowerBound].contains(".task(id: room.reaction?.id)"))
        XCTAssertTrue(room[..<stage.lowerBound].contains(".task(id: room.transition?.id)"))
    }

    func testReadingCoverIsChosenInsideThePlayerClosure() throws {
        let source = SpriteTestAssets.root.appendingPathComponent("Sources/CicadaApp/Views/Common/BookwormView.swift")
        let text = try String(contentsOf: source)
        let timeline = try XCTUnwrap(text.range(of: "SpriteLayerPlayer(tracks: tracks) { date in"))
        let cover = try XCTUnwrap(text.range(of: "BookwormArt.coverIndex(at: date"))
        XCTAssertGreaterThan(cover.lowerBound, timeline.lowerBound)
        XCTAssertTrue(text.contains("BookwormArt.transitionClip($0.kind, lighting: lighting, lampLit: lampLit, mascot: mascot)"))
        XCTAssertTrue(text.contains("BookwormArt.clip(state, look: look, cover: cover, set: size.set, lighting: lighting, lampLit: lampLit, mascot: mascot)"))
        XCTAssertTrue(text.contains("WindowVisibilityReader"))
        XCTAssertTrue(text.contains("SceneRunPolicy.isPaused"))
        XCTAssertTrue(text.contains(".accessibilityLabel(\"\\(state.title) — \\(state.detail)\")"))
    }
}
