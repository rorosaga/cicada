import XCTest
@testable import CicadaApp

final class BookwormFramesBenchmarkTests: XCTestCase {
    func testBenchmarkWarmClipsAndCropsForEveryReachableLook() throws {
        let pairs = try BookwormSpriteTests.states.flatMap { state -> [(SpriteSheet, SpriteClip)] in
            let sheet = try SpriteTestAssets.sheet(BookwormArt.sheetName(state, .room))
            return try BookwormLook.reachable(for: state).map { (sheet, try SpriteTestAssets.clip(sheet, BookwormArt.tag($0))) }
        }
        for (sheet, clip) in pairs { for index in clip.order { _ = sheet.frameImage(index) } }
        measure {
            for _ in 0..<20 {
                for state in BookwormSpriteTests.states {
                    for look in BookwormLook.reachable(for: state) {
                        if let (sheet, clip) = BookwormArt.clip(state, look: look) { _ = sheet.frameImage(clip.order[0]) }
                    }
                }
            }
        }
    }
}
