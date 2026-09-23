import XCTest
@testable import CicadaApp

/// Design §6.1 / Z-P24 — `frames(for:)` is recomposed twice per tick
/// (`BookwormView.body` and `BookwormRenderer.cachedImage`), and poses
/// multiply those calls. A memo ships only if this benchmark moves.
final class BookwormFramesBenchmarkTests: XCTestCase {
    func test_benchmark_framesForEveryReachableLook() {
        let pairs = BookwormPoseSpriteTests.pageStates.flatMap { state in
            BookwormLook.reachable(for: state).map { (state, $0) }
        }
        measure {
            for _ in 0..<20 {
                for (state, look) in pairs { _ = BookwormSprites.frames(for: state, look: look) }
            }
        }
    }
}
